"""One live acceptance of a single researched portrait passage, from a topic.

Chain (each paid stage at most the stated number of times, no retry, no fallback):
  Pro research planning -> existing Exa/Tavily search execution -> Pro material extraction ->
  Lite two-host writing -> Pro light fact check -> (only on a confirmed factual problem: one
  local repair + one re-check) -> Doubao B voice -> WAV and local HLS.

No old material, source link or frozen evidence is given to any model: the only input is the
topic.  Caps: search requests <= 3, text-model calls <= 6, speech calls <= 1, estimated Ark text
cost <= 1 CNY.  Search and Doubao costs are reported separately; an unknown cost is "unknown",
never zero.  Dry-run by default (no network); ``--offline`` runs the same code on scripted
fakes; ``--live`` spends.  Editorial artifacts are saved stage by stage; credentials, raw
requests/responses and reasoning never are.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from wavecast.arrangement.models import AudioClip, MixPlan
from wavecast.intelligence import research as research_module
from wavecast.intelligence.dialogue_budget import (
    DIALOGUE_CHARS_PER_SECOND,
    dialogue_budget_for,
)
from wavecast.intelligence.dialogue_check import DialogueCheck, DialogueFactChecker
from wavecast.intelligence.dialogue_metrics import DialogueMetrics
from wavecast.intelligence.dialogue_pipeline import DialoguePipeline, DialogueStatus
from wavecast.intelligence.dialogue_writer import (
    DialogueRepair,
    DialogueRepairer,
    DialogueSlot,
    DialogueWriter,
)
from wavecast.intelligence.models import (
    FastResearchInput,
    FastStartPlan,
    NarrationScript,
    ResearchBundle,
    ResearchDepth,
    ResearchPlan,
)
from wavecast.intelligence.research import (
    BackgroundResearchPlanner,
    BackgroundResearchService,
)
from wavecast.intelligence.story_material import StoryMaterialDraft, StoryMaterialService
from wavecast.intelligence.trace import GenerationTrace
from wavecast.materialization import NarrationMaterializer
from wavecast.models.dialogue import DialogueDraft, DialoguePurpose
from wavecast.orchestration.dialogue_timeline import narration_segment_from_record, voice_segment
from wavecast.providers.ark import ArkLLMProvider
from wavecast.providers.config import ProviderSettings
from wavecast.providers.dialogue_speech import MockDialogueSpeechProvider
from wavecast.providers.doubao_podcast import (
    DoubaoPodcastSpeechProvider,
    DoubaoPodcastWebSocketTransport,
)
from wavecast.providers.doubao_voices import VOICE_COMBINATION_B
from wavecast.providers.errors import ProviderUnavailableError
from wavecast.providers.fakes import MockTTSProvider
from wavecast.providers.search import ExaSearchProvider, TavilySearchProvider
from wavecast.providers.strict_schema import to_strict_schema
from wavecast.providers.usage import UsageLedger, usage_diagnostics, usage_scope
from wavecast.rendering import render_program_prefix
from wavecast.stations import StationId
from wavecast.storage import LocalObjectStorageProvider
from wavecast.storage.dialogue_artifacts import DialogueArtifactStore

PRO = "doubao-seed-2-1-pro-260915"
LITE = "doubao-seed-2-1-lite-260915"
MAX_SEARCH_REQUESTS = 3
MAX_TEXT_CALLS = 6
MAX_SPEECH_CALLS = 1
ARK_COST_CAP_CNY = 1.0
PLANNER_DEADLINE_SECONDS = 65.0  # formal runtime: 20 s (shorter than a measured Ark answer)
TOPIC = "方大同"
STATION = StationId.PORTRAIT


class Stop(BaseException):
    """Ends the whole run at once. A BaseException, so no ``except Exception`` fallback in the
    existing research code can turn a failed stage into a quietly different one."""


class Shared:
    """Counters shared by every guarded client of this run."""

    def __init__(self, ledger: UsageLedger) -> None:
        self.ledger = ledger
        self.search_requests = 0
        self.text_calls = 0
        self.search_log: list[dict[str, Any]] = []
        self.text_log: list[dict[str, Any]] = []

    def ark_cost(self) -> tuple[float, bool]:
        """(known estimated CNY, any Ark call whose cost is unknown)."""
        total, unknown = 0.0, False
        for event in self.ledger.events:
            if event.provider != "ark":
                continue
            price = event.metadata.get("estimated_cost_cny")
            if isinstance(price, (int, float)) and not isinstance(price, bool):
                total += float(price)
            else:
                unknown = True
        return round(total, 6), unknown


class GuardedLLM:
    """Counts and caps text-model calls and the estimated Ark cost; delegates everything else."""

    def __init__(self, inner: Any, shared: Shared, role: str) -> None:
        self._inner, self._shared, self.role = inner, shared, role

    async def structured(self, prompt: str, output_type: type, **kwargs: Any) -> Any:
        shared = self._shared
        cost, unknown = shared.ark_cost()
        if shared.text_calls >= MAX_TEXT_CALLS:
            raise Stop("text_call_cap")
        if cost >= ARK_COST_CAP_CNY or unknown:
            raise Stop("ark_cost_cap_or_unknown_cost")
        shared.text_calls += 1
        started = time.monotonic()
        entry: dict[str, Any] = {"n": shared.text_calls, "role": self.role, "stage": kwargs.get("stage")}
        shared.text_log.append(entry)
        try:
            return await self._inner.structured(prompt, output_type, **kwargs)
        except BaseException as error:
            entry["error_type"] = type(error).__name__
            raise
        finally:
            entry["seconds"] = round(time.monotonic() - started, 2)

    async def aclose(self) -> None:
        close = getattr(self._inner, "aclose", None)
        if close is not None:
            await close()


class CountedSearch:
    """Counts requests before they are sent; past the cap nothing is sent."""

    def __init__(self, inner: Any, shared: Shared, label: str) -> None:
        self._inner, self._shared, self._label = inner, shared, label

    async def search(self, query: str, *, limit: int = 5, stage: str | None = None) -> list[Any]:
        shared = self._shared
        if shared.search_requests >= MAX_SEARCH_REQUESTS:
            raise ProviderUnavailableError("search request cap reached; nothing was sent")
        shared.search_requests += 1
        started = time.monotonic()
        entry: dict[str, Any] = {
            "n": shared.search_requests, "provider": self._label, "query": query, "limit": limit, "stage": stage,
        }
        shared.search_log.append(entry)
        try:
            results = await self._inner.search(query, limit=limit, stage=stage)
            entry["result_count"] = len(results)
            return results
        except BaseException as error:
            entry["error_type"] = type(error).__name__
            raise
        finally:
            entry["seconds"] = round(time.monotonic() - started, 2)

    async def aclose(self) -> None:
        close = getattr(self._inner, "aclose", None)
        if close is not None:
            await close()


class RecordingPlanner:
    """The existing planner, but a failure ends the run instead of falling back to a generic plan."""

    def __init__(self, inner: Any, sink: dict[str, Any]) -> None:
        self._inner, self._sink = inner, sink

    async def plan(self, request: Any, fast_result: Any, *, trace: Any = None) -> ResearchPlan:
        try:
            plan = await self._inner.plan(request, fast_result, trace=trace)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._sink["error_type"] = type(error).__name__
            raise Stop("research_plan_failed") from None
        self._sink["plan"] = plan
        return plan


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--offline", action="store_true")
    parser.add_argument("--prompt-keys", action="store_true")
    parser.add_argument("--run-dir", type=Path, required=True)
    return parser.parse_args()


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fast_request() -> FastResearchInput:
    return FastResearchInput(
        topic=TOPIC, anchor_artists=[TOPIC], desired_duration_seconds=1200,
        depth=ResearchDepth.DEEP,  # the portrait station's research depth in the formal runtime
    )


def empty_fast_result(request: FastResearchInput) -> Any:
    """No fast stage ran: the planner starts from the topic alone (a recorded difference)."""

    bundle = ResearchBundle(anchors=list(request.anchor_artists), taste_hypotheses=[], evidence=[], candidates=[])
    plan = FastStartPlan(
        anchor_understanding=[], immediate_taste_hypotheses=[], next_candidates=[],
        first_narration=NarrationScript(text="-", intended_duration_seconds=1),
    )
    return SimpleNamespace(bundle=bundle, queries=[], plan=plan)


def planner_prompt_for_check() -> str:
    request = fast_request()
    return BackgroundResearchPlanner._prompt(request, empty_fast_result(request))  # noqa: SLF001


def cap_selection() -> None:
    """Formal deep budget is 2 Exa + 5 Tavily (after 2 fast queries). Here: the first three of
    the plan's queries, in plan order, whichever providers they route to."""

    original = research_module.select_background_queries

    def capped(plan: Any, fast_queries: Any, *, max_exa: int = 1, max_tavily: int = 2) -> Any:
        return original(plan, fast_queries, max_exa=MAX_SEARCH_REQUESTS, max_tavily=MAX_SEARCH_REQUESTS)[
            :MAX_SEARCH_REQUESTS
        ]

    research_module.select_background_queries = capped  # type: ignore[assignment]


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    budget = dialogue_budget_for(STATION)
    assert budget is not None
    schemas = {
        model.__name__: to_strict_schema(model.model_json_schema())
        for model in (ResearchPlan, StoryMaterialDraft, DialogueDraft, DialogueCheck, DialogueRepair)
    }
    prompt = planner_prompt_for_check()
    forbidden = ("Hitoradio", "爱爱爱", "我们能不能", "http", "live-fdt", "冻结")
    return {
        "topic": TOPIC,
        "station": STATION.value,
        "research_depth": "deep (portrait station)",
        "models": {"research_plan": PRO, "material": PRO, "writer_and_repair": LITE, "fact_check": PRO},
        "caps": {
            "search_requests": MAX_SEARCH_REQUESTS, "text_calls": MAX_TEXT_CALLS,
            "speech_calls": MAX_SPEECH_CALLS, "ark_estimated_cost_cny": ARK_COST_CAP_CNY,
        },
        "text_call_plan": "planner 1 + material 1 + writer 1 + check 1 + (repair 1 + re-check 1 only on a confirmed factual issue) = 4..6",
        "automatic_retry": {"search": False, "text": False, "speech": False},
        "writer_fallback_or_single_host_fallback": False,
        "strict_schemas_ok": sorted(schemas),
        "planner_prompt_chars": len(prompt),
        "planner_prompt_contains_old_material": [word for word in forbidden if word in prompt],
        "budget": {
            "target_seconds": [budget.target_min_seconds, budget.target_max_seconds],
            "target_characters": list(budget.target_characters),
            "hard_max_seconds": budget.hard_max_seconds,
            "chars_per_second": DIALOGUE_CHARS_PER_SECOND,
        },
        "voices": "combination B (A=刘飞, B=潇磊), speed 0, wav",
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "credentials_present": {
            "exa_env": bool(os.environ.get("EXA_API_KEY")),
            "tavily_env": bool(os.environ.get("TAVILY_API_KEY")),
            "ark": bool(os.environ.get("ARK_API_KEY")) or "needs --prompt-keys",
            "doubao_podcast": bool(os.environ.get("DOUBAO_PODCAST_API_KEY")) or "needs --prompt-keys",
        },
        "differences_from_formal_runtime": [
            "no fast stage (the formal one makes 1 Exa + 1 Tavily query and one fast-start model call first); the planner starts from the topic alone",
            f"at most {MAX_SEARCH_REQUESTS} search requests in total (the first three planned queries, in plan order); formal deep budget is 2 Exa + 5 Tavily",
            f"planner deadline {PLANNER_DEADLINE_SECONDS:.0f}s instead of 20s; a planner failure stops the run instead of falling back to a generic plan",
            "provider max_attempts=1 (formal default 2: one retry on transient errors)",
            "the passage's slot has no neighbouring songs (just_played/upcoming are empty); no music is rendered, only the voice HLS",
            "evidence goes to material extraction as the whole research bundle (formal: evidence scoped to the chapter's track); material reads at most the first 12 items, 900 characters each",
            "episode/ledger/usage-store wiring of the runtime is not used; the pipeline pieces are called directly",
        ],
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    info = preflight(args)
    info["mode"] = "live" if args.live else "offline" if args.offline else "dry_run"
    if not args.live and not args.offline:
        return {**info, "status": "preflight_ready", "network_calls": 0}
    if info["planner_prompt_contains_old_material"]:
        raise ValueError("planner_prompt_not_clean")
    if not info["ffmpeg"]:
        raise ValueError("ffmpeg_unavailable")

    ark_key = os.environ.get("ARK_API_KEY", "") if args.live else ""
    podcast_key = os.environ.get("DOUBAO_PODCAST_API_KEY", "") if args.live else ""
    if args.live and args.prompt_keys:
        ark_key = getpass.getpass("Temporary Ark key: ")
        podcast_key = getpass.getpass("Temporary Doubao podcast key: ")
    if args.live and not (ark_key and podcast_key):
        raise ValueError("temporary_keys_required")
    if args.live and not (os.environ.get("EXA_API_KEY") and os.environ.get("TAVILY_API_KEY")):
        raise ValueError("search_keys_missing")
    args.run_dir.mkdir(parents=True, exist_ok=False)
    with (args.run_dir / "attempt.json").open("x", encoding="utf-8") as marker:
        json.dump(info, marker, ensure_ascii=False, indent=2)

    budget = dialogue_budget_for(STATION)
    assert budget is not None
    ledger = UsageLedger()
    shared = Shared(ledger)
    storage = LocalObjectStorageProvider(args.run_dir / "assets")
    state: dict[str, Any] = {**info, "status": "started", "stage": "research_plan"}
    stage_seconds: dict[str, float] = {}
    clock = time.monotonic()
    owned: list[Any] = []

    def mark(stage: str) -> None:
        nonlocal clock
        now = time.monotonic()
        stage_seconds[stage] = round(now - clock, 2)
        clock = now
        state["stage_seconds"] = dict(stage_seconds)

    def keep(name: str, value: Any) -> None:
        save(args.run_dir / name, value)
        state.setdefault("saved_artifacts", []).append(name)

    episode_id, story_id = "research-dialogue-probe", "live-research"
    settings = ProviderSettings(
        mode="live", exa_api_key=os.environ.get("EXA_API_KEY") or "offline",
        tavily_api_key=os.environ.get("TAVILY_API_KEY") or "offline",
        ark_api_key=ark_key or None, ark_max_output_tokens=4096, max_attempts=1,
    )
    try:
        if args.offline:
            from tests.offline_research_fakes import (
                offline_clients,  # scripted stand-ins, no network
            )

            fakes = offline_clients(budget)
            planner_llm, material_llm, writer_llm, checker_llm = (
                GuardedLLM(llm, shared, role) for llm, role in zip(
                    (fakes.planner, fakes.material, fakes.writer, fakes.checker),
                    ("research_plan", "material", "writer", "fact_check"), strict=True,
                )
            )
            discovery = CountedSearch(fakes.exa, shared, "exa")
            research = CountedSearch(fakes.tavily, shared, "tavily")
            deep = CountedSearch(fakes.tavily_deep, shared, "tavily_advanced")
            speech: Any = MockDialogueSpeechProvider(storage, fixed_duration_seconds=40)
            state["evidence_provenance"] = "offline scripted fakes; no network"
        else:
            ark: list[Any] = []
            for model, role in ((PRO, "research_plan"), (PRO, "material"), (LITE, "writer"), (PRO, "fact_check")):
                client = ArkLLMProvider(settings, model=model, role=role, ledger=ledger)
                owned.append(client)
                ark.append(GuardedLLM(client, shared, role))
            planner_llm, material_llm, writer_llm, checker_llm = ark
            exa = ExaSearchProvider(settings, ledger=ledger)
            tav = TavilySearchProvider(settings, ledger=ledger)
            tav_deep = TavilySearchProvider(settings, ledger=ledger, search_depth="advanced")
            owned += [exa, tav, tav_deep]
            discovery = CountedSearch(exa, shared, "exa")
            research = CountedSearch(tav, shared, "tavily")
            deep = CountedSearch(tav_deep, shared, "tavily_advanced")
            speech = DoubaoPodcastSpeechProvider(
                DoubaoPodcastWebSocketTransport(podcast_key, max_audio_seconds=float(budget.hard_max_seconds)),
                storage, ledger=ledger,
            )

        with usage_scope(episode_id):
            # --- 1-2. Pro research planning, then the existing search service executes it -----
            cap_selection()
            sink: dict[str, Any] = {}
            trace = GenerationTrace(request_id=episode_id)
            request = fast_request()
            service = BackgroundResearchService(
                discovery=discovery, research=research, deep_research=deep, ledger=ledger,
                planner=RecordingPlanner(BackgroundResearchPlanner(planner_llm), sink),  # type: ignore[arg-type]
                planner_deadline_seconds=PLANNER_DEADLINE_SECONDS,
            )
            bundle = await service.run(request, empty_fast_result(request), trace=trace)
            mark("research_plan_and_search")
            fallback = [e.name for e in trace.events if e.name == "background_research_plan_fallback"]
            plan: ResearchPlan | None = sink.get("plan")
            state["research_plan_source"] = "pro_planner" if plan is not None and not fallback else "generic_fallback"
            keep("01_research_plan.json", {
                "status": "normalised plan from the Pro research planner" if plan else "no plan",
                "plan": plan.model_dump(mode="json") if plan else None,
                "selected_queries": [
                    {k: v for k, v in e.metadata.items() if k == "selected_queries"}
                    for e in trace.events if e.name == "background_started"
                ],
            })
            keep("02_search_calls.json", {"requests": shared.search_log})
            if bundle is None or state["research_plan_source"] != "pro_planner":
                raise Stop("research_plan_not_used")
            evidence = list(bundle.evidence)
            state["search"] = {
                "requests": shared.search_requests,
                "failed_requests": sum("error_type" in e for e in shared.search_log),
                "evidence_items": len(evidence),
                "uncertainties": list(bundle.uncertainties),
            }
            keep("03_evidence_sources.json", {
                "note": "normalised search results as they entered the material step (excerpts, not raw responses)",
                "uncertainties": list(bundle.uncertainties),
                "evidence": [e.model_dump(mode="json") for e in evidence],
            })
            if not evidence:
                raise Stop("no_usable_evidence")

            # --- 3. Pro material extraction ---------------------------------------------------
            state["stage"] = "material"
            material = await StoryMaterialService(material_llm).extract(  # type: ignore[arg-type]
                evidence, story_id=story_id, subject=TOPIC, recording_refs=[]
            )
            mark("material")
            if material is None:
                raise Stop("no_verified_material")
            state["verified_facts"] = len(material.facts)
            keep("04_material.normalized.json", {
                "status": "normalised_and_verified_by_code",
                "material": material.model_dump(mode="json"),
            })

            # --- 4-5. Lite writer, Pro light check, optional one repair + re-check -----------
            state["stage"] = "dialogue"
            reports: list[dict[str, Any]] = []
            timeline: dict[str, float] = {}

            class RecWriter(DialogueWriter):
                async def write(self, material, slot, budget):  # type: ignore[no-untyped-def]
                    started = time.monotonic()
                    draft = await super().write(material, slot, budget)
                    timeline["writer"] = round(time.monotonic() - started, 2)
                    chars = sum(len(t.text) for t in draft.turns)
                    keep("05_candidate.unchecked.json", {
                        "status": "UNCHECKED candidate: not fact-checked, not approved for broadcast",
                        "measure": {
                            "turns": len(draft.turns), "characters": chars,
                            "target_characters": list(budget.target_characters),
                            "within_target": budget.target_characters[0] <= chars <= budget.target_characters[1],
                        },
                        "turns": [t.model_dump(mode="json") for t in draft.turns],
                    })
                    return draft

            class RecChecker(DialogueFactChecker):
                async def review(self, block, material):  # type: ignore[no-untyped-def]
                    started = time.monotonic()
                    report = await super().review(block, material)
                    index = len(reports) + 1
                    timeline[f"check_{index}"] = round(time.monotonic() - started, 2)
                    record = {
                        "check": "first" if index == 1 else "after_repair",
                        "model_checked": report.model_checked,
                        "passed": bool(report.model_checked and not report.issues),
                        "issues": [i.model_dump(mode="json") for i in report.issues],
                        "hints": [h.model_dump(mode="json") for h in report.hints],
                        "supported_by_turn": {str(t): r for t, r in report.supported.items()},
                        "turns_checked": [t.model_dump(mode="json") for t in block.turns],
                    }
                    reports.append(record)
                    keep("06_check.first.json" if index == 1 else "08_check.after_repair.json", record)
                    return report

            class RecRepairer(DialogueRepairer):
                async def repair(self, block, material, problems):  # type: ignore[no-untyped-def]
                    started = time.monotonic()
                    fixes = await super().repair(block, material, problems)
                    timeline["repair"] = round(time.monotonic() - started, 2)
                    keep("07_repair.json", {
                        "status": "the one allowed local repair",
                        "reasons": {str(k): v for k, v in problems.items()},
                        "before": {str(i): block.turns[i].text for i in problems if i < len(block.turns)},
                        "fixes": [f.model_dump(mode="json") for f in fixes.fixes],
                    })
                    return fixes

            metrics = DialogueMetrics()
            pipeline = DialoguePipeline(
                writer=RecWriter(writer_llm),  # type: ignore[arg-type]
                checker=RecChecker(checker_llm),  # type: ignore[arg-type]
                repairer=RecRepairer(writer_llm),  # type: ignore[arg-type]
                max_calls=4, metrics=metrics, ledger=ledger,
            )
            slot = DialogueSlot(
                slot_id="probe:portrait", block_id="probe-block", purpose=DialoguePurpose.STORY,
                station=STATION, just_played=None, upcoming=None,
            )
            outcome = await pipeline.produce(material, slot)
            mark("dialogue_pipeline")
            state["dialogue"] = {
                "status": outcome.status.value, "reason": outcome.reason, "calls": outcome.calls,
                "first_check_passed": bool(reports and reports[0]["passed"]),
                "repaired_turns": outcome.repaired_turns, "information_loss_sentences": outcome.information_loss_sentences,
                "stage_seconds": timeline, "metrics": metrics.summary(),
            }
            if outcome.status not in (DialogueStatus.READY, DialogueStatus.REPAIRED) or outcome.block is None:
                raise Stop(f"dialogue_not_ready:{outcome.reason}")
            block = outcome.block
            keep("09_final_script.json", {
                "status": "REPAIRED once" if outcome.status is DialogueStatus.REPAIRED else "CHECKED unchanged",
                "estimated_seconds": block.duration_seconds,
                "turns": [t.model_dump(mode="json") for t in block.turns],
            })
            (args.run_dir / "09_final_script.txt").write_text(
                "\n".join(f"{t.speaker.value}: {t.text}" for t in block.turns) + "\n", encoding="utf-8"
            )

            # --- 6. Doubao B voice -> WAV -> local HLS ----------------------------------------
            artifacts = DialogueArtifactStore(storage)
            await artifacts.save(episode_id, outcome.to_record())
            segment = narration_segment_from_record(outcome.to_record(), chapter_id="chapter-1", order=0)
            materializer = NarrationMaterializer(
                MockTTSProvider(storage), storage, dialogue_speech=speech,
                dialogue_voices=VOICE_COMBINATION_B, dialogue_speed=0, dialogue_format="wav",
            )
            state["stage"] = "speech"
            await voice_segment(materializer, artifacts, episode_id, segment)
            mark("speech")
            if segment.dialogue_audio is None or not segment.audio_source_url:
                raise Stop("speech_did_not_produce_snapshot")
            stored = await storage.get(segment.dialogue_audio.cache_key)
            if stored is None:
                raise Stop("speech_asset_missing")
            (args.run_dir / "dialogue.wav").write_bytes(stored.content)
            state["stage"] = "hls"
            duration = float(segment.dialogue_audio.duration_seconds)
            mix = MixPlan(
                episode_id=episode_id, duration_seconds=duration,
                clips=(AudioClip(
                    id="probe-voice", segment_id=segment.id, source_url=segment.audio_source_url,
                    lane="VOICE", timeline_start_seconds=0, source_offset_seconds=0,
                    playable_duration_seconds=duration,
                ),), segment_starts={segment.id: 0},
            )
            manifest = await render_program_prefix(mix, storage, complete=True)
            if not manifest.chunks:
                raise Stop("hls_has_no_chunks")
            mark("hls")
            state.update(
                status="completed", audio_seconds=duration, estimated_seconds=block.duration_seconds,
                hls_chunks=len(manifest.chunks),
            )
            state["turn_timings"] = stored.metadata.get("turn_timings")
    except asyncio.CancelledError:
        state.update(status="cancelled", error_type="CancelledError")
        raise
    except Stop as stop:
        state.update(status="failed", reason=str(stop), failed_stage=state.get("stage"))
    except Exception as error:  # safe diagnosis: never persist provider exception text
        state.update(status="failed", error_type=type(error).__name__, failed_stage=state.get("stage"))
    finally:
        cost, unknown = shared.ark_cost()
        diagnostics = usage_diagnostics(ledger, scope=episode_id)
        exa_usd = [e.actual_cost_usd for e in ledger.events if e.provider == "exa" and e.operation == "search"]
        tav_credits = [e.search_credits for e in ledger.events if e.provider == "tavily" and e.operation == "search"]
        audio = [e for e in ledger.events if e.provider not in {"ark", "exa", "tavily"}]
        state["calls"] = {
            "search_requests": shared.search_requests, "text_calls": shared.text_calls,
            "speech_events": len(audio),
        }
        state["text_calls_log"] = shared.text_log
        state["search_calls_log"] = shared.search_log
        state["costs"] = {
            "ark_estimated_cny_known": cost,
            "ark_any_call_cost_unknown": unknown,
            "exa_actual_usd": (
                round(sum(v for v in exa_usd if v is not None), 6) if exa_usd and all(v is not None for v in exa_usd) else "unknown"
            ),
            "tavily_credits": (
                sum(v for v in tav_credits if v is not None) if tav_credits and all(v is not None for v in tav_credits) else "unknown"
            ),
            "tavily_currency": "unknown (credits only; no price is assumed)",
            "doubao_speech": "unpriced: audio tokens recorded, currency cost unknown",
        }
        state["conclusions"] = {
            "portrait_research_chain_passed": state.get("status") == "completed",
            "scope": "a single passage from a topic, not a dynamic multi-segment programme",
            "casual_length_control": "not_passed (earlier attempt, untouched)",
        }
        state["usage"] = diagnostics
        save(args.run_dir / "summary.safe.json", state)
        for client in owned:
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()
    return state


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    parsed = arguments()
    try:
        result = asyncio.run(run(parsed))
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"status": "stopped", "error_type": type(error).__name__, "automatic_retry": False}))
        raise SystemExit(1) from None
    print(json.dumps({k: v for k, v in result.items() if k not in {"usage", "text_calls_log", "search_calls_log"}}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] in ("preflight_ready", "completed") else 1)
