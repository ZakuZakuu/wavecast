"""One short dialogue probe. Dry-run by default; each paid stage once, failure stops.

Uses frozen Evidence, not a new search. No repair, Writer fallback or API retry.
Offline mode uses the explicitly reconstructed test fixture and makes no network calls.
Editorial records and completed audio may be saved; raw prompts/responses never are.
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
from pathlib import Path
from typing import Any

from wavecast.arrangement.models import AudioClip, MixPlan
from wavecast.intelligence.dialogue import block_from_draft
from wavecast.intelligence.dialogue_budget import dialogue_budget_for, estimate_dialogue_seconds
from wavecast.intelligence.dialogue_check import DialogueCheck, DialogueFactChecker
from wavecast.intelligence.dialogue_pipeline import DialogueOutcome, DialogueStatus
from wavecast.intelligence.dialogue_writer import DialogueSlot, DialogueWriter
from wavecast.intelligence.models import Evidence
from wavecast.intelligence.story_material import StoryMaterialDraft, StoryMaterialService
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
from wavecast.providers.fakes import MockTTSProvider
from wavecast.providers.strict_schema import to_strict_schema
from wavecast.providers.usage import UsageLedger, usage_diagnostics, usage_scope
from wavecast.rendering import render_program_prefix
from wavecast.stations import StationId
from wavecast.storage import LocalObjectStorageProvider
from wavecast.storage.dialogue_artifacts import DialogueArtifactStore

PRO = "doubao-seed-2-1-pro-260915"
LITE = "doubao-seed-2-1-lite-260915"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--offline", action="store_true")
    parser.add_argument("--prompt-keys", action="store_true")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--material-model", default=PRO)
    parser.add_argument("--writer-model", default=LITE)
    parser.add_argument("--checker-model", default=PRO)
    return parser.parse_args()


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def run(args: argparse.Namespace) -> dict[str, Any]:
    raw = args.evidence.read_bytes()
    evidence = [Evidence.model_validate(item) for item in json.loads(raw)]
    if not evidence:
        raise ValueError("empty_evidence")
    schemas = {
        model.__name__: to_strict_schema(model.model_json_schema())
        for model in (StoryMaterialDraft, DialogueDraft, DialogueCheck)
    }
    if shutil.which("ffmpeg") is None:
        raise ValueError("ffmpeg_unavailable")
    preflight = {
        "evidence_count": len(evidence),
        "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        "strict_schemas": list(schemas),
        "models": [args.material_model, args.writer_model, args.checker_model],
        "max_paid_calls": 4,
        "automatic_retry": False,
        "repair_or_writer_fallback": False,
        "max_audio_seconds": 70,
        "mode": "live" if args.live else "offline" if args.offline else "dry_run",
    }
    if not args.live and not args.offline:
        return {**preflight, "status": "preflight_ready", "network_calls": 0}

    ark_key = os.environ.get("ARK_API_KEY", "") if args.live else ""
    podcast_key = os.environ.get("DOUBAO_PODCAST_API_KEY", "") if args.live else ""
    if args.live and args.prompt_keys:
        ark_key = getpass.getpass("Temporary Ark key: ")
        podcast_key = getpass.getpass("Temporary Doubao podcast key: ")
    if args.live and not (ark_key and podcast_key):
        raise ValueError("temporary_keys_required")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    # Exclusive marker: an interrupted or failed run is not silently retried on restart.
    with (args.run_dir / "attempt.json").open("x", encoding="utf-8") as marker:
        json.dump(preflight, marker, ensure_ascii=False, indent=2)

    ledger = UsageLedger()
    clients: list[ArkLLMProvider] = []
    storage = LocalObjectStorageProvider(args.run_dir / "assets")
    state: dict[str, Any] = {**preflight, "status": "started", "stage": "material"}
    episode_id, story_id = "dialogue-live-probe", "live-fdt"
    track_ref = "frozen:fdt-ai-ai-ai"
    try:
        if args.offline:
            from wavecast.intelligence.story_material import verify_material

            from tests.dialogue_fixtures import JudgingLLM, ScriptedLLM, clean_draft, material_draft
            from tests.dialogue_fixtures import evidence as fixture_evidence

            evidence = fixture_evidence()
            story_id, track_ref = "fdt", "netease:track-ai-ai-ai"
            known = verify_material(material_draft(), evidence, story_id=story_id, recording_refs=[track_ref])
            assert known is not None
            short_draft = clean_draft().model_copy(update={"turns": clean_draft().turns[:2]})
            material_llm: Any = ScriptedLLM(material_draft())
            writer_llm: Any = ScriptedLLM(short_draft)
            checker_llm: Any = JudgingLLM(known, [short_draft], insufficient=())
            speech: Any = MockDialogueSpeechProvider(storage, fixed_duration_seconds=3)
            state["evidence_provenance"] = "reconstructed offline fixture; not frozen search"
        else:
            settings = ProviderSettings(mode="live", ark_api_key=ark_key, ark_max_output_tokens=4096)
            for model, role in zip(
                (args.material_model, args.writer_model, args.checker_model),
                ("material", "writer", "fact_check"), strict=True,
            ):
                clients.append(ArkLLMProvider(settings, model=model, role=role, ledger=ledger))
            material_llm, writer_llm, checker_llm = clients
            speech = DoubaoPodcastSpeechProvider(
                DoubaoPodcastWebSocketTransport(podcast_key, max_audio_seconds=70), storage, ledger=ledger
            )
        with usage_scope(episode_id):
            material = await StoryMaterialService(material_llm).extract(
                evidence, story_id=story_id, subject="方大同早期的国语创作", recording_refs=[track_ref]
            )
            if material is None:
                raise ValueError("no_verified_material")
            state["verified_facts"] = len(material.facts)
            state["stage"] = "writer"
            slot = DialogueSlot(
                slot_id="probe:before-track", block_id="probe-block", purpose=DialoguePurpose.STORY,
                station=StationId.CASUAL, just_played="我们能不能", upcoming="爱爱爱",
            )
            budget = dialogue_budget_for(slot.station)
            assert budget is not None
            draft = await DialogueWriter(writer_llm).write(material, slot, budget)
            block = block_from_draft(
                draft, block_id=slot.block_id, slot_id=slot.slot_id, purpose=slot.purpose,
                duration_seconds=estimate_dialogue_seconds(sum(len(t.text) for t in draft.turns)),
                allowed_fact_refs=material.fact_ids, story_id=story_id,
            )
            if block.duration_seconds > budget.hard_max_seconds:
                raise ValueError("draft_exceeds_short_probe_budget")
            state["turns"] = len(block.turns)
            state["estimated_seconds"] = block.duration_seconds
            state["stage"] = "fact_check"
            checked = await DialogueFactChecker(checker_llm).review(block, material)
            if not checked.model_checked or checked.issues:
                state["issue_codes"] = sorted({issue.code for issue in checked.issues})
                raise ValueError("fact_check_rejected_no_repair")
            outcome = DialogueOutcome(
                status=DialogueStatus.READY, block=block, material=material,
                calls=2, model_checked=True, station_value=slot.station.value,
            )
            artifacts = DialogueArtifactStore(storage)
            await artifacts.save(episode_id, outcome.to_record())
            segment = narration_segment_from_record(outcome.to_record(), chapter_id="chapter-1", order=0)
            materializer = NarrationMaterializer(
                MockTTSProvider(storage), storage, dialogue_speech=speech,
                dialogue_voices=VOICE_COMBINATION_B, dialogue_speed=0, dialogue_format="wav",
            )
            state["stage"] = "speech"
            await voice_segment(materializer, artifacts, episode_id, segment)
            if segment.dialogue_audio is None or not segment.audio_source_url:
                raise ValueError("speech_did_not_produce_snapshot")
            stored = await storage.get(segment.dialogue_audio.cache_key)
            if stored is None:
                raise ValueError("speech_asset_missing")
            (args.run_dir / "dialogue.wav").write_bytes(stored.content)
            # HLS is the real renderer with real generated speech; this is not a full music programme.
            state["stage"] = "hls"
            duration = float(segment.dialogue_audio.duration_seconds)
            plan = MixPlan(
                episode_id=episode_id, duration_seconds=duration,
                clips=(AudioClip(
                    id="probe-voice", segment_id=segment.id, source_url=segment.audio_source_url,
                    lane="VOICE", timeline_start_seconds=0, source_offset_seconds=0,
                    playable_duration_seconds=duration,
                ),), segment_starts={segment.id: 0},
            )
            manifest = await render_program_prefix(plan, storage, complete=True)
            if not manifest.chunks:
                raise ValueError("hls_has_no_chunks")
            again = await render_program_prefix(plan, storage, complete=True)
            if again != manifest:
                raise ValueError("hls_not_repeatable")
            state.update(status="completed", audio_seconds=duration, hls_chunks=len(manifest.chunks))
    except asyncio.CancelledError:
        state.update(status="cancelled", error_type="CancelledError")
        raise
    except Exception as error:  # safe diagnosis: never persist provider exception text
        state.update(status="failed", error_type=type(error).__name__)
        if isinstance(error, ValueError) and str(error) in {
            "no_verified_material", "draft_exceeds_short_probe_budget", "fact_check_rejected_no_repair",
        }:
            state["reason"] = str(error)
    finally:
        state["providers"] = usage_diagnostics(ledger, scope=episode_id)
        state["live_calls"] = len(ledger.events) if args.live else 0
        save(args.run_dir / "summary.safe.json", state)
        for client in clients:
            await client.aclose()
    return state


if __name__ == "__main__":
    # Keep HTTP/websocket libraries from emitting payloads or credentials at DEBUG level.
    logging.basicConfig(level=logging.WARNING)
    args = arguments()
    try:
        result = asyncio.run(run(args))
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"status": "stopped", "error_type": type(error).__name__, "automatic_retry": False}))
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] in ("preflight_ready", "completed") else 1)
