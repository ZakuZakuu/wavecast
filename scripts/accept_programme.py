"""One bounded acceptance of a whole programme through the real progressive runtime.

A virtual listener drives the real API (proposal -> episode -> heartbeat -> program-render ->
playback checkpoints) in real time against a live (or, for a rehearsal, mock) backend run
in this process, so every paid call passes through the budget guard installed here.

Modes
  preflight   no network, no spend: configuration, guard behaviour, database, ffmpeg, music
              reachability is checked separately by the caller
  rehearse    the same run against the mock providers (no spend, no keys) to prove the harness
  live        one real attempt: no retry (provider max_attempts=1, one worker attempt), the first
              failure stops new paid calls, the budget is checked before every call
  requery     a fresh process reads an earlier run's usage back from storage (restart check)

Keys are read from stdin with --prompt-keys (Ark, then Doubao podcast), never from argv, never
written anywhere.  Search keys come from the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import os
import shutil
import sys
import time
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "backend"), str(REPO)]

PRO = "doubao-seed-2-1-pro-260915"
LITE = "doubao-seed-2-1-lite-260915"
BUDGET_CNY = 5.0
BUDGET_EXA_USD = 0.20
LISTENER = "acceptance-20261015"
PROMPT = "方大同人物志"
PORT = 8000
OVERALL_TIMEOUT_SECONDS = float(os.environ.get("ACCEPT_TIMEOUT_SECONDS", 100 * 60))
# Worst-case reservations used before a call whose price is only known afterwards.
RESERVE_EXA_USD = 0.015
RESERVE_DOUBAO_CNY = 0.6
RESERVE_MINIMAX_CNY = 0.05
MAX_DEEPSEEK_CALLS = 150


class BudgetStop(Exception):
    """Raised instead of a paid call that must not be made."""


# --- the meter and the guards ---------------------------------------------------------------------


class Meter:
    def __init__(self) -> None:
        self.cny = 0.0  # known CNY estimates (Ark, Doubao)
        self.exa_usd = 0.0
        self.inflight_cny = 0.0
        self.inflight_exa = 0.0
        self.calls: Counter[str] = Counter()
        self.denied: Counter[str] = Counter()
        self.unknown_cost_events = 0
        self.tripped: str | None = None
        self.frozen = False

    def observe(self, event: Any) -> None:
        metadata = event.metadata
        price = metadata.get("estimated_cost_cny")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            self.cny += float(price)
        elif event.provider in {"ark", "doubao_podcast"}:
            self.unknown_cost_events += 1
        if event.provider == "exa":
            if event.actual_cost_usd is not None:
                self.exa_usd += event.actual_cost_usd
            else:
                self.unknown_cost_events += 1

    def trip(self, reason: str) -> None:
        self.tripped = self.tripped or reason

    @contextlib.asynccontextmanager
    async def permit(self, kind: str, *, cny: float = 0.0, usd: float = 0.0) -> AsyncIterator[None]:
        if self.tripped or self.frozen:
            self.denied[kind] += 1
            raise BudgetStop(f"{kind}: {'frozen after completion' if self.frozen else self.tripped}")
        if self.cny + self.inflight_cny + cny > BUDGET_CNY:
            self.denied[kind] += 1
            self.trip("cny_budget")
            raise BudgetStop(f"{kind}: CNY budget would be exceeded")
        if self.exa_usd + self.inflight_exa + usd > BUDGET_EXA_USD:
            self.denied[kind] += 1
            raise BudgetStop(f"{kind}: Exa budget would be exceeded")
        self.calls[kind] += 1
        self.inflight_cny += cny
        self.inflight_exa += usd
        try:
            yield
        finally:
            self.inflight_cny -= cny
            self.inflight_exa -= usd

    def snapshot(self) -> dict[str, Any]:
        return {
            "ark_and_doubao_cny_known": round(self.cny, 6),
            "exa_usd_actual": round(self.exa_usd, 6),
            "unknown_cost_events": self.unknown_cost_events,
            "paid_calls_started": dict(self.calls),
            "paid_calls_denied": dict(self.denied),
            "tripped": self.tripped,
            "budget": {"cny": BUDGET_CNY, "exa_usd": BUDGET_EXA_USD},
        }


def install_guards(meter: Meter, *, live: bool) -> None:
    """Patch the provider classes before the API module builds anything."""
    from wavecast.orchestration.worker import GenerationWorker, GenerationWorkerPolicy
    from wavecast.providers.ark import ArkLLMProvider
    from wavecast.providers.ark_pricing import ARK_PRICES
    from wavecast.providers.config import ProviderSettings
    from wavecast.providers.deepseek import DeepSeekLLMProvider
    from wavecast.providers.doubao_podcast import DoubaoPodcastSpeechProvider
    from wavecast.providers.minimax import MiniMaxTTSProvider
    from wavecast.providers.profiles import InferenceProfile
    from wavecast.providers.search import ExaSearchProvider
    from wavecast.providers.usage import UsageLedger

    # No automatic retry anywhere we control: one attempt per provider request, one worker attempt.
    original_from_env = ProviderSettings.from_env.__func__  # type: ignore[attr-defined]
    ProviderSettings.from_env = classmethod(  # type: ignore[method-assign]
        lambda cls: replace(original_from_env(cls), max_attempts=1)
    )
    original_worker_init = GenerationWorker.__init__

    def worker_init(self: Any, jobs: Any, orchestrator: Any, **kwargs: Any) -> None:
        kwargs["policy"] = GenerationWorkerPolicy(max_attempts=1)
        original_worker_init(self, jobs, orchestrator, **kwargs)

    GenerationWorker.__init__ = worker_init  # type: ignore[method-assign]

    original_record = UsageLedger.record

    def record(self: Any, event: Any) -> None:
        meter.observe(event)
        original_record(self, event)

    UsageLedger.record = record  # type: ignore[method-assign]

    if not live:
        return

    original_ark = ArkLLMProvider.structured

    async def ark_structured(self: Any, prompt: str, output_type: Any, **kwargs: Any) -> Any:
        profile = kwargs.get("profile", InferenceProfile.BALANCED)
        _timeout, max_out = self._limits(profile)
        price = ARK_PRICES.get(self.model)
        reserve = (
            (len(prompt) * price.standard.input_cny_per_million + max_out * price.standard.output_cny_per_million)
            / 1_000_000
            if price is not None
            else 0.5
        )
        async with meter.permit("ark", cny=reserve):
            return await original_ark(self, prompt, output_type, **kwargs)

    ArkLLMProvider.structured = ark_structured  # type: ignore[method-assign]

    original_exa = ExaSearchProvider.search

    async def exa_search(self: Any, query: str, **kwargs: Any) -> Any:
        async with meter.permit("exa", usd=RESERVE_EXA_USD):
            return await original_exa(self, query, **kwargs)

    ExaSearchProvider.search = exa_search  # type: ignore[method-assign]

    original_speech = DoubaoPodcastSpeechProvider.synthesize_dialogue

    async def speech(self: Any, request: Any) -> Any:
        async with meter.permit("doubao", cny=RESERVE_DOUBAO_CNY):
            return await original_speech(self, request)

    DoubaoPodcastSpeechProvider.synthesize_dialogue = speech  # type: ignore[method-assign]

    original_minimax = MiniMaxTTSProvider.synthesize

    async def minimax(self: Any, *args: Any, **kwargs: Any) -> Any:
        async with meter.permit("minimax", cny=RESERVE_MINIMAX_CNY):
            return await original_minimax(self, *args, **kwargs)

    MiniMaxTTSProvider.synthesize = minimax  # type: ignore[method-assign]

    original_deepseek = DeepSeekLLMProvider.structured

    async def deepseek(self: Any, *args: Any, **kwargs: Any) -> Any:
        if meter.calls["deepseek"] >= MAX_DEEPSEEK_CALLS:
            meter.denied["deepseek"] += 1
            raise BudgetStop("deepseek: call cap")
        async with meter.permit("deepseek"):
            return await original_deepseek(self, *args, **kwargs)

    DeepSeekLLMProvider.structured = deepseek  # type: ignore[method-assign]


# --- environment ------------------------------------------------------------------------------------


def apply_env(mode: str, root: Path, database: str, keys: dict[str, str]) -> dict[str, str]:
    """The settings of this run; returns the non-secret ones for the record."""
    live = mode == "live"
    settings: dict[str, str] = {
        "WAVECAST_PROVIDER_MODE": "live" if live else "mock",
        "WAVECAST_RECOMMENDATION_PLANNER": "deterministic",
        "WAVECAST_DATABASE_URL": f"postgresql+asyncpg://wavecast_cloud:wavecast_cloud@127.0.0.1:5432/{database}",
        "WAVECAST_AUDIO_ROOT": str(root / "audio"),
        "WAVECAST_BACKGROUND_GENERATION_ENABLED": "1",
    }
    if live:
        settings.update(
            {
                "WAVECAST_SEARCH_BACKEND": "exa",
                "WAVECAST_DIALOGUE_RADIO": "on",
                "WAVECAST_DIALOGUE_SPEECH_PROVIDER": "doubao",
                "WAVECAST_RESEARCH_PLAN_PROVIDER": "ark",
                "ARK_RESEARCH_PLAN_MODEL": PRO,
                "WAVECAST_MATERIAL_PROVIDER": "ark",
                "ARK_MATERIAL_MODEL": PRO,
                "WAVECAST_WRITER_PROVIDER": "ark",
                "ARK_WRITER_MODEL": LITE,
                "WAVECAST_MUSIC_PROVIDER": "inherit",
            }
        )
    for name in ("BETTER_AUTH_DATABASE_URL", "BETTER_AUTH_SECRET", "WAVECAST_AUTH_JWKS_URL",
                 "WAVECAST_AUTH_ISSUER", "WAVECAST_AUTH_AUDIENCE"):
        os.environ.pop(name, None)
    os.environ.update(settings)
    if live:
        os.environ["ARK_API_KEY"] = keys["ark"]
        os.environ["DOUBAO_PODCAST_API_KEY"] = keys["doubao"]
    return settings


def server_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for noisy in ("httpx", "httpcore", "websockets", "uvicorn.access", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)  # request URLs can carry signed links


# --- the virtual listener -----------------------------------------------------------------------------


class Recorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.start = time.monotonic()

    def __call__(self, event: str, **data: Any) -> None:
        line = {"t": round(time.monotonic() - self.start, 2), "event": event, **data}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def segment_rows(episode: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in sorted(episode.get("segments", []), key=lambda s: s["order"]):
        dialogue = item.get("dialogue")
        rows.append(
            {
                "order": item["order"], "id": item["id"], "kind": item["kind"], "state": item["state"],
                "chapter_id": item.get("chapter_id"), "title": item.get("title"), "artist": item.get("artist"),
                "planned_seconds": item.get("planned_duration_seconds"),
                "actual_seconds": item.get("actual_duration_seconds"),
                "role": item.get("narration_role"), "two_host": dialogue is not None,
                "text": item.get("narration_text"),
            }
        )
    return rows


HEARTBEAT_SECONDS = 10.0  # the web client's heartbeat timer (use-programme-playback.ts)
CHECKPOINT_SECONDS = 5.0
POLL_SECONDS = 3.0
RENDER_RETRY_SECONDS = 20.0


class Listener:
    """A virtual listener that behaves like the web player where the server can tell.

    The web player keeps its heartbeat on a timer of its own, reports its position as it plays, and,
    when the server answers a heartbeat with 409 (the lease lapsed), takes the lease back with
    ``resume``.  None of those waits for a programme render.  Here each is a task of its own, so a
    render that takes minutes cannot make the server think the listener left, and the position it
    reports follows the audio that has actually been published.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        meter: Meter,
        rec: Any,
        episode_id: str,
        *,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        checkpoint_seconds: float = CHECKPOINT_SECONDS,
    ) -> None:
        self.client = client
        self.meter = meter
        self.rec = rec
        self.episode_id = episode_id
        self.heartbeat_seconds = heartbeat_seconds
        self.checkpoint_seconds = checkpoint_seconds
        self.playhead = 0.0
        self.has_audio = False
        self.lease_lost = 0
        self.lease_recovered = 0
        self._recovering = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []

    async def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return await self.client.request(
            method, f"/api/episodes/{self.episode_id}{path}", headers={"X-Wavecast-Listener": LISTENER}, **kwargs
        )

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._every(self.heartbeat_seconds, self._heartbeat), name="heartbeat"),
            asyncio.create_task(self._every(self.checkpoint_seconds, self._checkpoint), name="checkpoint"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []

    async def _every(self, seconds: float, action: Any) -> None:
        while True:
            try:
                await action()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a lost request is retried by the next tick, as in the browser
                pass
            await asyncio.sleep(seconds)

    async def _heartbeat(self) -> None:
        response = await self.call("POST", "/heartbeat", timeout=30)
        if response.status_code == 409:
            await self.recover()

    async def _checkpoint(self) -> None:
        if self.has_audio:
            await self.call("POST", "/program-playback-checkpoint", json={"position_seconds": round(self.playhead, 2)}, timeout=30)

    async def recover(self) -> None:
        """Take the lease back, once at a time.  Never after a failure: the run has stopped spending."""
        if self._recovering.locked():
            return
        async with self._recovering:
            self.lease_lost += 1
            self.rec("lease_lost")
            if self.meter.tripped is not None or self.meter.frozen:
                self.rec("lease_not_recovered", reason="run_stopped")
                return
            response = await self.call("POST", "/resume", timeout=60)
            if response.status_code == 200:
                self.lease_recovered += 1
                self.rec("lease_recovered")


async def drive(
    client: httpx.AsyncClient,
    meter: Meter,
    run_dir: Path,
    rec: Any,
    speed: float = 1.0,
    *,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    checkpoint_seconds: float = CHECKPOINT_SECONDS,
    poll_seconds: float = POLL_SECONDS,
    render_retry_seconds: float = RENDER_RETRY_SECONDS,
) -> dict[str, Any]:
    headers = {"X-Wavecast-Listener": LISTENER}
    report: dict[str, Any] = {"status": "started"}

    async def call(method: str, path: str, **kwargs: Any) -> httpx.Response:
        return await client.request(method, f"/api{path}", headers=headers, **kwargs)

    rec("proposal_requested", prompt=PROMPT, station="portrait", duration="SHORT")
    proposals = await call(
        "POST", "/program-proposals",
        json={"prompt": PROMPT, "duration_intent": "SHORT", "count": 1, "station": "portrait"},
        timeout=120,
    )
    if proposals.status_code != 200:
        meter.trip("proposal_failed")
        return {**report, "status": "failed", "failed_at": "proposal", "http": proposals.status_code}
    proposal = proposals.json()["proposals"][0]
    (run_dir / "proposal.json").write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    rec("proposal_ready", id=proposal["id"], title=proposal.get("title"),
        opening=[proposal.get("opening_track_artist"), proposal.get("opening_track_title")],
        estimated_seconds=proposal.get("estimated_duration_seconds"))
    started = await call("POST", f"/episodes/from-seed/{proposal['id']}", timeout=180)
    if started.status_code != 200:
        meter.trip("episode_start_failed")
        return {**report, "status": "failed", "failed_at": "episode_start", "http": started.status_code}
    episode = started.json()
    episode_id = episode["id"]
    report["episode_id"] = episode_id
    rec("episode_started", id=episode_id, estimated_seconds=episode["program_estimated_duration_seconds"])

    listener = Listener(
        client, meter, rec, episode_id,
        heartbeat_seconds=heartbeat_seconds, checkpoint_seconds=checkpoint_seconds,
    )
    listener.start()
    try:
        result = await _listen(listener, call, meter, rec, speed, poll_seconds, render_retry_seconds)
    finally:
        await listener.stop()
    result.update({"lease_lost": listener.lease_lost, "lease_recovered": listener.lease_recovered})
    return {**report, **result}


async def _listen(
    listener: Listener,
    call: Any,
    meter: Meter,
    rec: Any,
    speed: float,
    poll_seconds: float,
    render_retry_seconds: float,
) -> dict[str, Any]:
    episode_id = listener.episode_id
    begun = time.monotonic()
    last = begun
    stalled_since: float | None = None
    stalls: list[dict[str, float]] = []
    first_audio_at: float | None = None
    manifest: dict[str, Any] | None = None
    last_poll = last_render = 0.0
    render_signature: Any = None
    render_failures = 0
    seen_states: dict[str, str] = {}
    render: asyncio.Task[httpx.Response] | None = None
    render_signature_pending: Any = None

    async def render_program() -> httpx.Response:
        return await call("POST", f"/episodes/{episode_id}/program-render", timeout=300)

    try:
        while True:
            now = time.monotonic()
            dt, last = now - last, now
            elapsed = now - begun
            if elapsed > OVERALL_TIMEOUT_SECONDS:
                meter.trip("overall_timeout")
                return {"status": "failed", "failed_at": "timeout", **stats(stalls, first_audio_at)}
            frontier = float(manifest["renderedFrontierSeconds"]) if manifest else 0.0
            complete = bool(manifest and manifest.get("complete"))
            # The position follows the audio that has been published, and only that.
            if manifest and listener.playhead < frontier - 0.05:
                if first_audio_at is None:
                    first_audio_at = elapsed
                    listener.has_audio = True
                    rec("first_audio", seconds_since_start=round(elapsed, 1))
                listener.playhead = min(frontier, listener.playhead + dt * speed)
                if stalled_since is not None:
                    stalls.append({"start_playhead": round(listener.playhead, 1), "seconds": round(now - stalled_since, 1)})
                    rec("stall_ended", seconds=round(now - stalled_since, 1), playhead=round(listener.playhead, 1))
                    stalled_since = None
            elif manifest and not complete and stalled_since is None and first_audio_at is not None:
                stalled_since = now
                rec("stall_started", playhead=round(listener.playhead, 1), frontier=round(frontier, 1))
            if complete and listener.playhead >= frontier - 0.1:
                await call("POST", f"/episodes/{episode_id}/completed")
                rec("completed", playhead=round(listener.playhead, 1), frontier=round(frontier, 1))
                return {"status": "completed", "playhead_end": round(listener.playhead, 1),
                        "published_seconds": round(frontier, 1), "listening_seconds": round(elapsed, 1),
                        **stats(stalls, first_audio_at)}
            # A render that has finished is read here; it never held the loop (or the heartbeat) up.
            if render is not None and render.done():
                finished, render = render, None
                try:
                    rendered = finished.result()
                except Exception:  # noqa: BLE001 - counted like any other not-ready render
                    render_failures += 1
                    rec("render_not_ready", http="error")
                else:
                    if rendered.status_code == 200:
                        render_signature = render_signature_pending
                        new_manifest = rendered.json()
                        if manifest is None or new_manifest["renderedFrontierSeconds"] != manifest["renderedFrontierSeconds"]:
                            rec("published", frontier=round(new_manifest["renderedFrontierSeconds"], 1),
                                complete=new_manifest.get("complete"), chunks=len(new_manifest["chunks"]))
                        manifest = new_manifest
                    else:
                        render_failures += 1
                        rec("render_not_ready", http=rendered.status_code)
            if now - last_poll >= poll_seconds:
                last_poll = now
                response = await call("GET", f"/episodes/{episode_id}")
                episode = response.json()
                for row in segment_rows(episode):
                    if seen_states.get(row["id"]) != row["state"]:
                        seen_states[row["id"]] = row["state"]
                        rec("segment_state", order=row["order"], kind=row["kind"], two_host=row["two_host"],
                            state=row["state"], title=(row["title"] or "")[:40], role=row["role"])
                states = [s["state"] for s in episode["segments"]]
                signature = (len(states), tuple(sorted(Counter(states).items())), episode.get("version"))
                due = signature != render_signature or (not complete and now - last_render >= render_retry_seconds)
                if due and render is None and render_failures < 40:
                    last_render = now
                    render_signature_pending = signature
                    render = asyncio.create_task(render_program(), name="program-render")
                if episode["state"] == "CANCELLED":
                    meter.trip("episode_cancelled")
                    return {"status": "failed", "failed_at": "episode_cancelled", **stats(stalls, first_audio_at)}
                failed_job = await job_failed(episode_id)
                if failed_job:
                    meter.trip("generation_job_failed")
                    rec("generation_job_failed", detail=failed_job)
                    return {"status": "failed", "failed_at": "generation_job", "job": failed_job,
                            **stats(stalls, first_audio_at)}
            await asyncio.sleep(0.05 if poll_seconds < 1 else 0.5)
    finally:
        if render is not None and not render.done():
            render.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await render


def stats(stalls: list[dict[str, float]], first_audio_at: float | None) -> dict[str, Any]:
    return {"first_audio_after_seconds": None if first_audio_at is None else round(first_audio_at, 1),
            "stalls": stalls, "stall_seconds_total": round(sum(item["seconds"] for item in stalls), 1)}


async def job_failed(episode_id: str) -> str | None:
    """The durable generation job's state, from the repository the API itself uses."""
    try:
        from services.api import main as api  # noqa: PLC0415

        job = await asyncio.to_thread(api.generation_job_repository.get_for_episode, episode_id)
    except Exception:  # noqa: BLE001 - diagnostics only
        return None
    if job is not None and str(job.status.value) == "FAILED":
        return f"status=FAILED attempts={job.attempts} error={job.last_error_code}"
    return None


# --- collecting the deliverables ------------------------------------------------------------------------


async def collect(client: httpx.AsyncClient, episode_id: str, run_dir: Path, meter: Meter, rec: Recorder) -> dict[str, Any]:
    headers = {"X-Wavecast-Listener": LISTENER}
    out: dict[str, Any] = {}

    async def get(path: str) -> Any:
        response = await client.get(f"/api{path}", headers=headers, timeout=120)
        return response.json() if response.status_code == 200 else {"http": response.status_code}

    episode = await get(f"/episodes/{episode_id}")
    rows = segment_rows(episode) if "segments" in episode else []
    (run_dir / "segments.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "script.txt").write_text(
        "\n\n".join(
            f"[{r['order']:02d} {r['kind']} {r['state']}{' 两位主持' if r['two_host'] else ''}] {r['artist'] or ''} {r['title'] or ''}\n{r['text'] or ''}"
            for r in rows
        ) + "\n",
        encoding="utf-8",
    )
    mix = await get(f"/episodes/{episode_id}/mix-plan")
    (run_dir / "mix_plan.json").write_text(json.dumps(mix, ensure_ascii=False, indent=2)[:2_000_000], encoding="utf-8")
    evidence = await get(f"/episodes/{episode_id}/evidence")
    (run_dir / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    usage = await get(f"/episodes/{episode_id}/usage")
    (run_dir / "usage_before_restart.json").write_text(json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")
    out["usage_events"] = (usage.get("providers") or {}).get("usage", {}).get("event_count")
    out["costs"] = usage.get("costs")
    # The whole programme as one listenable file, from the same HLS the player would use.
    target = run_dir / "programme.mp3"
    playlist = f"http://127.0.0.1:{PORT}/api/program-streams/{episode_id}.m3u8"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", "-i", playlist, "-c:a", "libmp3lame", "-b:a", "128k", str(target),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=900)
    except TimeoutError:
        process.kill()
    out["mp3"] = {"ok": process.returncode == 0 and target.exists(), "bytes": target.stat().st_size if target.exists() else 0}
    if out["mp3"]["ok"]:
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(target),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await probe.communicate()
        out["mp3"]["seconds"] = float(stdout.decode().strip() or 0)
    # Resuming must not spend: freeze the paid calls and ask again.
    before = dict(meter.calls)
    meter.frozen = True
    await client.post(f"/api/episodes/{episode_id}/resume", headers=headers, timeout=60)
    await client.post(f"/api/episodes/{episode_id}/program-render", headers=headers, timeout=300)
    await asyncio.sleep(5)
    out["resume_check"] = {
        "paid_calls_before": before, "paid_calls_after": dict(meter.calls),
        "paid_calls_denied_while_frozen": dict(meter.denied),
        "spent_again": dict(meter.calls) != before,
    }
    rec("collected", **{k: v for k, v in out.items() if k in {"usage_events", "mp3"}})
    return out


# --- entry points ---------------------------------------------------------------------------------------


async def serve_and_drive(args: argparse.Namespace, keys: dict[str, str]) -> dict[str, Any]:
    live = args.mode == "live"
    root = args.run_dir
    root.mkdir(parents=True, exist_ok=False)
    database = args.database
    settings = apply_env(args.mode, root, database, keys)
    meter = Meter()
    install_guards(meter, live=live)
    server_logging()
    import uvicorn  # noqa: PLC0415

    from services.api import main as api  # noqa: PLC0415

    rec = Recorder(root / "timeline.jsonl")
    config = uvicorn.Config(api.app, host="127.0.0.1", port=PORT, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.2)
    summary: dict[str, Any] = {
        "mode": args.mode, "listener": LISTENER, "prompt": PROMPT, "station": "portrait", "duration": "SHORT",
        "settings": settings, "database": database,
    }
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", trust_env=False, timeout=60) as client:
            result = await drive(client, meter, root, rec, speed=args.speed if not live else 1.0)
            summary["drive"] = result
            if result.get("episode_id"):
                if not live:
                    await seed_rehearsal_events(api, result["episode_id"])
                summary["collected"] = await collect(client, result["episode_id"], root, meter, rec)
    finally:
        summary["meter"] = meter.snapshot()
        server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(server_task, timeout=60)
        (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


async def seed_rehearsal_events(api: Any, episode_id: str) -> None:
    """Mock providers record nothing: seed two events so persistence and the restart check have
    something to prove (rehearsal only)."""
    from wavecast.providers.usage import UsageEvent, usage_scope  # noqa: PLC0415

    ledger = api._usage_ledger()  # noqa: SLF001
    with usage_scope(episode_id):
        ledger.record(UsageEvent(provider="exa", operation="search", elapsed_ms=5, search_queries=1,
                                 actual_cost_usd=0.007, metadata={"stage": "rehearsal", "outcome": "ok"}))
        ledger.record(UsageEvent(provider="ark", operation="structured", elapsed_ms=9, input_tokens=10, output_tokens=2,
                                 metadata={"stage": "rehearsal", "outcome": "ok", "estimated_cost_cny": 0.01}))
    await ledger.flush()


async def requery(args: argparse.Namespace) -> dict[str, Any]:
    """A fresh process: nothing in memory, so whatever the report shows came from storage."""
    root = args.run_dir
    earlier = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    episode_id = earlier["drive"]["episode_id"]
    os.environ.update({
        "WAVECAST_PROVIDER_MODE": "mock", "WAVECAST_RECOMMENDATION_PLANNER": "deterministic",
        "WAVECAST_DATABASE_URL": earlier["settings"]["WAVECAST_DATABASE_URL"],
        "WAVECAST_AUDIO_ROOT": earlier["settings"]["WAVECAST_AUDIO_ROOT"],
        "WAVECAST_BACKGROUND_GENERATION_ENABLED": "0",
    })
    server_logging()
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from services.api import main as api  # noqa: PLC0415

    with TestClient(api.app) as client:
        response = client.get(f"/api/episodes/{episode_id}/usage", headers={"X-Wavecast-Listener": LISTENER})
        after = response.json()
    (root / "usage_after_restart.json").write_text(json.dumps(after, ensure_ascii=False, indent=2), encoding="utf-8")
    before = json.loads((root / "usage_before_restart.json").read_text(encoding="utf-8"))

    def ids(report: dict[str, Any]) -> list[str]:
        return sorted(e["event_id"] for e in (report.get("providers") or {}).get("provider_events", []))

    return {
        "http": response.status_code, "events_before": len(ids(before)), "events_after": len(ids(after)),
        "same_events": ids(before) == ids(after), "costs_same": before.get("costs") == after.get("costs"),
        "stored_events": after.get("stored_events"),
    }


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    import asyncio as _asyncio  # noqa: PLC0415

    from wavecast.providers.usage import UsageEvent  # noqa: PLC0415

    meter = Meter()

    async def check() -> dict[str, Any]:
        results: dict[str, Any] = {}
        meter.cny = BUDGET_CNY - 0.1
        try:
            async with meter.permit("doubao", cny=RESERVE_DOUBAO_CNY):
                results["budget_guard_denies_over_budget"] = False
        except BudgetStop:
            results["budget_guard_denies_over_budget"] = True
        meter.cny, meter.tripped = 0.0, None
        meter.observe(UsageEvent(provider="exa", operation="search", elapsed_ms=1, actual_cost_usd=0.007))
        meter.observe(UsageEvent(provider="ark", operation="structured", elapsed_ms=1, metadata={"estimated_cost_cny": 0.3}))
        results["meter_adds_known_costs"] = (round(meter.cny, 3), round(meter.exa_usd, 3)) == (0.3, 0.007)
        meter.frozen = True
        try:
            async with meter.permit("ark", cny=0.01):
                results["frozen_denies"] = False
        except BudgetStop:
            results["frozen_denies"] = True
        return results

    out = _asyncio.run(check())
    out["ffmpeg"] = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
    out["env_present"] = {name: bool(os.environ.get(name)) for name in (
        "EXA_API_KEY", "DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "MINIMAX_TTS_VOICE_ID",
        "NETEASE_MUSIC_API_BASE_URL", "NETEASE_MUSIC_API_BEARER_TOKEN")}
    out["tavily_key_needed"] = False
    out["wiring"] = wiring_report()
    return out


def wiring_report() -> dict[str, Any]:
    """Build the real API module under the live settings with placeholder keys (no request is
    made at construction) and report what it resolved."""
    settings = apply_env("live", Path("/tmp/accept-wiring-check"), "wavecast_accept_20261015",
                         {"ark": "placeholder", "doubao": "placeholder"})
    meter = Meter()
    install_guards(meter, live=True)
    from wavecast.providers.config import LLM_ROLES  # noqa: PLC0415

    from services.api import main as api  # noqa: PLC0415

    cfg = api._provider_settings  # noqa: SLF001
    roles = {role: cfg.resolved_llm(role) for role in LLM_ROLES}
    models = {role: cfg.ark_models.get(role) for role in LLM_ROLES if roles[role] == "ark"}
    runtime = api.progressive_runtime
    assembly = runtime.assembly if runtime is not None else None
    research = assembly.background_pipeline.research if assembly is not None else None
    return {
        "mode": cfg.mode, "max_attempts": cfg.max_attempts, "search_backend": cfg.search_backend,
        "dialogue_radio": cfg.dialogue_radio, "dialogue_speech": cfg.dialogue_speech_provider,
        "roles": roles, "ark_models": models,
        "music": cfg.resolved_music_provider, "tts": cfg.resolved_tts_provider,
        "worker_attempts": api.generation_worker.policy.max_attempts,
        "assembly_has_dialogue_runtime": bool(assembly is not None and assembly.dialogue_runtime is not None),
        "research_label": getattr(research, "research_label", None),
        "tavily_built": research is not None and research.research is not research.discovery,
        "audio_root_in_run_area": str(api.AUDIO_ROOT).startswith("/tmp/accept-wiring-check"),
        "settings_applied": sorted(settings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["preflight", "rehearse", "live", "requery"], required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--database", default="wavecast_accept_20261015")
    parser.add_argument("--prompt-keys", action="store_true")
    parser.add_argument("--speed", type=float, default=1.0, help="rehearsal only: play faster than real time")
    args = parser.parse_args()
    if args.mode == "preflight":
        print(json.dumps(preflight(args), ensure_ascii=False, indent=2))
        return 0
    if args.run_dir is None:
        parser.error("--run-dir is required")
    if args.mode == "requery":
        print(json.dumps(asyncio.run(requery(args)), ensure_ascii=False, indent=2))
        return 0
    keys: dict[str, str] = {}
    if args.mode == "live":
        if not args.prompt_keys:
            parser.error("live needs --prompt-keys (Ark, then Doubao podcast, one per line on stdin)")
        keys = {"ark": getpass.getpass("Ark key: "), "doubao": getpass.getpass("Doubao podcast key: ")}
        if not all(keys.values()):
            raise SystemExit("keys_missing")
        missing = [n for n in ("EXA_API_KEY", "DEEPSEEK_API_KEY", "MINIMAX_API_KEY") if not os.environ.get(n)]
        if missing:
            raise SystemExit(f"environment_missing:{','.join(missing)}")
    summary = asyncio.run(serve_and_drive(args, keys))
    safe = {k: v for k, v in summary.items() if k != "settings"}
    print(json.dumps(safe, ensure_ascii=False, indent=2)[:6000])
    return 0 if summary.get("drive", {}).get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
