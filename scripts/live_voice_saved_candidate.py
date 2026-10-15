"""Voice a previously saved candidate passage once. Dry-run by default; one speech call at most.

Reads the material and the candidate script that an earlier run saved (it never searches,
extracts, writes, checks or repairs anything), re-validates them with today's basic validation
(fact ids inside the material, structure, the station's hard length ceiling), then makes ONE
Doubao B-voice synthesis, writes the WAV and renders the local HLS.  The earlier run directory
is only read.  No retry.  A failure stops the run and is diagnosed; the speech cost is reported
as unknown (Doubao is unpriced here), never as zero.  The saved passage is recorded as not
model-checked, which is what it is.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from wavecast.arrangement.models import AudioClip, MixPlan
from wavecast.intelligence.dialogue import DialogueValidationError, block_from_draft
from wavecast.intelligence.dialogue_budget import dialogue_budget_for, estimate_dialogue_seconds
from wavecast.intelligence.dialogue_pipeline import DialogueOutcome, DialogueStatus
from wavecast.materialization import NarrationMaterializer
from wavecast.models.dialogue import DialogueDraft, DialoguePurpose
from wavecast.models.story_material import StoryMaterial
from wavecast.orchestration.dialogue_timeline import narration_segment_from_record, voice_segment
from wavecast.providers.dialogue_speech import MockDialogueSpeechProvider
from wavecast.providers.doubao_podcast import (
    DoubaoPodcastSpeechProvider,
    DoubaoPodcastWebSocketTransport,
)
from wavecast.providers.doubao_voices import VOICE_COMBINATION_B
from wavecast.providers.fakes import MockTTSProvider
from wavecast.providers.usage import UsageLedger, usage_diagnostics, usage_scope
from wavecast.rendering import render_program_prefix
from wavecast.stations import StationId
from wavecast.storage import LocalObjectStorageProvider
from wavecast.storage.dialogue_artifacts import DialogueArtifactStore

STATION = StationId.PORTRAIT
INPUTS = ("04_material.normalized.json", "05_candidate.unchecked.json")
# Keys an earlier build added to facts only for its (retired) checker; today's model has no place for them.
RETIRED_FACT_KEYS = ("source_title", "context")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--offline", action="store_true", help="same inputs and validation, mock speech")
    parser.add_argument("--prompt-keys", action="store_true")
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    return parser.parse_args()


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_inputs(source: Path) -> tuple[StoryMaterial, DialogueDraft, dict[str, str], dict[str, Any]]:
    missing = [name for name in INPUTS if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"saved_inputs_missing:{','.join(missing)}")
    hashes = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in INPUTS}
    raw_material = json.loads((source / INPUTS[0]).read_text(encoding="utf-8"))["material"]
    for fact in raw_material["facts"]:
        for key in RETIRED_FACT_KEYS:
            fact.pop(key, None)
    candidate = json.loads((source / INPUTS[1]).read_text(encoding="utf-8"))
    material = StoryMaterial.model_validate(raw_material)
    draft = DialogueDraft.model_validate({"turns": candidate["turns"]})
    return material, draft, hashes, candidate.get("measure", {})


async def run(args: argparse.Namespace) -> dict[str, Any]:
    budget = dialogue_budget_for(STATION)
    assert budget is not None
    material, draft, hashes, saved_measure = load_inputs(args.source_run)
    characters = sum(len(t.text) for t in draft.turns)
    estimated = estimate_dialogue_seconds(characters)
    slot_id, block_id = "probe:portrait", "probe-block"
    state: dict[str, Any] = {
        "mode": "live" if args.live else "offline" if args.offline else "dry_run",
        "source_run": args.source_run.name,
        "source_input_sha256": hashes,
        "reused": "material and candidate script from the earlier run; no search, extraction, writing, check or repair now",
        "station": STATION.value,
        "voices": "combination B (A=刘飞, B=潇磊), speed 0, wav",
        "max_speech_calls": 1,
        "automatic_retry": False,
        "model_checked": False,
        "measure": {
            "turns": len(draft.turns), "characters": characters, "estimated_seconds": estimated,
            "target_seconds": [budget.target_min_seconds, budget.target_max_seconds],
            "target_characters": list(budget.target_characters),
            "within_target": budget.target_characters[0] <= characters <= budget.target_characters[1],
            "hard_max_seconds": budget.hard_max_seconds, "over_hard_max": estimated > budget.hard_max_seconds,
        },
        "saved_measure_in_source": saved_measure,
    }
    try:
        block = block_from_draft(
            draft, block_id=block_id, slot_id=slot_id, purpose=DialoguePurpose.STORY,
            duration_seconds=estimated, allowed_fact_refs=material.fact_ids, story_id=material.story_id,
        )
    except DialogueValidationError as error:
        return {**state, "status": "refused", "validation_problems": error.problems[:5]}
    if block.duration_seconds > budget.hard_max_seconds:
        return {**state, "status": "refused", "validation_problems": ["over_hard_max"]}
    state["validation"] = "passed: fact ids inside the material, structure, hard length ceiling"
    if not args.live and not args.offline:
        return {**state, "status": "preflight_ready", "network_calls": 0}
    if shutil.which("ffmpeg") is None:
        raise ValueError("ffmpeg_unavailable")

    key = os.environ.get("DOUBAO_PODCAST_API_KEY", "") if args.live else ""
    if args.live and args.prompt_keys:
        key = getpass.getpass("Temporary Doubao podcast key: ")
    if args.live and not key:
        raise ValueError("temporary_key_required")
    args.run_dir.mkdir(parents=True, exist_ok=False)
    with (args.run_dir / "attempt.json").open("x", encoding="utf-8") as marker:
        json.dump(state, marker, ensure_ascii=False, indent=2)

    episode_id = "voice-saved-candidate"
    ledger = UsageLedger()
    storage = LocalObjectStorageProvider(args.run_dir / "assets")
    seconds: dict[str, float] = {}
    clock = time.monotonic()

    def mark(stage: str) -> None:
        nonlocal clock
        now = time.monotonic()
        seconds[stage] = round(now - clock, 2)
        clock = now
        state["stage_seconds"] = dict(seconds)

    speech: Any = (
        DoubaoPodcastSpeechProvider(
            DoubaoPodcastWebSocketTransport(key, max_audio_seconds=float(budget.hard_max_seconds)),
            storage, ledger=ledger,
        )
        if args.live else MockDialogueSpeechProvider(storage, fixed_duration_seconds=estimated)
    )
    state["stage"] = "speech"
    try:
        with usage_scope(episode_id):
            outcome = DialogueOutcome(
                status=DialogueStatus.READY, block=block, material=material, calls=1,
                model_checked=False, station_value=STATION.value,
            )
            save(args.run_dir / "final_script.json", {
                "status": "validated by code only; NOT model-checked; one Writer call, made in the source run",
                "estimated_seconds": block.duration_seconds,
                "turns": [t.model_dump(mode="json") for t in block.turns],
            })
            (args.run_dir / "final_script.txt").write_text(
                "\n".join(f"{t.speaker.value}: {t.text}" for t in block.turns) + "\n", encoding="utf-8"
            )
            artifacts = DialogueArtifactStore(storage)
            await artifacts.save(episode_id, outcome.to_record())
            segment = narration_segment_from_record(outcome.to_record(), chapter_id="chapter-1", order=0)
            materializer = NarrationMaterializer(
                MockTTSProvider(storage), storage, dialogue_speech=speech,
                dialogue_voices=VOICE_COMBINATION_B, dialogue_speed=0, dialogue_format="wav",
            )
            started = time.monotonic()
            await voice_segment(materializer, artifacts, episode_id, segment)
            state["speech_call_seconds"] = round(time.monotonic() - started, 2)
            mark("speech")
            if segment.dialogue_audio is None or not segment.audio_source_url:
                raise ValueError("speech_did_not_produce_snapshot")
            stored = await storage.get(segment.dialogue_audio.cache_key)
            if stored is None:
                raise ValueError("speech_asset_missing")
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
                raise ValueError("hls_has_no_chunks")
            again = await render_program_prefix(mix, storage, complete=True)
            if again != manifest:
                raise ValueError("hls_not_repeatable")
            mark("hls")
            state.update(
                status="completed", audio_seconds=duration, estimated_seconds=block.duration_seconds,
                audio_minus_estimate_seconds=round(duration - block.duration_seconds, 2),
                hls_chunks=len(manifest.chunks), turn_timings=stored.metadata.get("turn_timings"),
            )
    except asyncio.CancelledError:
        state.update(status="cancelled", error_type="CancelledError")
        raise
    except Exception as error:  # safe diagnosis: never persist provider exception text
        state.update(status="failed", error_type=type(error).__name__, failed_stage=state.get("stage"))
    finally:
        events = ledger.for_scope(episode_id)
        state["speech_events"] = len(events) if args.live else 0
        state["costs"] = {"doubao_speech": "unpriced: audio tokens recorded, currency cost unknown (not zero)"}
        state["conclusions"] = {
            "saved_candidate_voiced": state.get("status") == "completed",
            "scope": "one saved passage; not a dynamic multi-segment programme",
            "model_checked": False,
        }
        state["usage"] = usage_diagnostics(ledger, scope=episode_id)
        save(args.run_dir / "summary.safe.json", state)
    return state


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    parsed = arguments()
    try:
        result = asyncio.run(run(parsed))
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"status": "stopped", "error_type": type(error).__name__, "detail": str(error)[:120] if isinstance(error, (FileNotFoundError, ValueError)) else None}))
        raise SystemExit(1) from None
    print(json.dumps({k: v for k, v in result.items() if k != "usage"}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] in ("preflight_ready", "completed") else 1)
