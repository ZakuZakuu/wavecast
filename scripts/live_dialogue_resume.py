"""Resume a stopped dialogue probe with ONE bounded local repair, then voice it once.

Starts from the saved editorial artifacts of a run that stopped at the fact check (normalised
material, the *unchecked* candidate, the check result and the stated conditions).  It does not
re-extract material or re-run the full Writer.  New paid calls, at most, each once:

    Lite repair of the turns the saved check flagged  ->  Pro re-check of the whole passage
    ->  Doubao B-voice speech  ->  local WAV and the real HLS renderer.

Any failure stops the run: no second repair, no redraw, no single-voice fallback.  The previous
run directory is only read.  Raw prompts/responses are never saved; the usage of the earlier run
and of this increment are reported separately.  The existing check rules are left as they are -
a short quotation rule that may be too strict for first-person interviews is recorded as an open
issue, not claimed to be right.

Default: validate the saved run and print the plan (no network, no keys).  ``--offline`` runs the
whole path on fixtures; ``--live --prompt-keys`` makes the paid calls.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from live_dialogue_probe import LITE, PRO, save
from wavecast.arrangement.models import AudioClip, MixPlan
from wavecast.intelligence.dialogue import block_from_draft
from wavecast.intelligence.dialogue_budget import dialogue_budget_for, estimate_dialogue_seconds
from wavecast.intelligence.dialogue_check import (
    DialogueCheck,
    DialogueCheckReport,
    DialogueFactChecker,
)
from wavecast.intelligence.dialogue_pipeline import (
    DialogueOutcome,
    DialoguePipeline,
    DialogueStatus,
)
from wavecast.intelligence.dialogue_writer import DialogueRepair, DialogueRepairer, TurnFix
from wavecast.materialization import NarrationMaterializer
from wavecast.models.dialogue import DialogueBlock, DialogueDraft, DialogueIssue, DialoguePurpose
from wavecast.models.story_material import StoryMaterial
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

EPISODE_ID = "dialogue-live-probe"
SLOT_ID, BLOCK_ID = "probe:before-track", "probe-block"
SOURCES = ("attempt.json", "summary.safe.json", "material.normalized.json", "candidate.unchecked.json", "check.result.json")


class ResumeRefused(ValueError):
    """The saved run is not one this script may continue from."""


@dataclass
class Prior:
    directory: Path
    hashes: dict[str, str]
    station: StationId
    conditions: dict[str, Any]
    summary: dict[str, Any]
    material: StoryMaterial
    draft: DialogueDraft
    block: DialogueBlock
    issues: list[DialogueIssue]
    flagged: dict[int, str]


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--offline", action="store_true")
    parser.add_argument("--prompt-keys", action="store_true")
    parser.add_argument("--from-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--repair-model", default=LITE)
    parser.add_argument("--checker-model", default=PRO)
    return parser.parse_args()


def load_prior(directory: Path) -> Prior:
    """Read and verify the saved run.  Nothing here writes to it."""

    for name in SOURCES:
        if not (directory / name).is_file():
            raise ResumeRefused(f"missing_{name}")
    hashes = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in SOURCES}
    attempt, summary, material_file, candidate, check = (
        json.loads((directory / name).read_text(encoding="utf-8")) for name in SOURCES
    )
    if summary.get("status") != "failed" or summary.get("failed_stage") != "fact_check":
        raise ResumeRefused("the_saved_run_did_not_stop_at_the_fact_check")
    if summary.get("reason") != "fact_check_rejected_no_repair":
        raise ResumeRefused("the_saved_run_was_not_refused_by_the_check")
    conditions = attempt.get("conditions") or {}
    station = StationId(conditions.get("station", ""))
    budget = dialogue_budget_for(station)
    if budget is None or conditions.get("hard_max_seconds") != budget.hard_max_seconds:
        raise ResumeRefused("the_saved_conditions_do_not_match_the_station_budget")
    if not str(candidate.get("status", "")).startswith("UNCHECKED"):
        raise ResumeRefused("the_saved_candidate_is_not_marked_unchecked")
    material = StoryMaterial.model_validate(material_file["material"])
    draft = DialogueDraft.model_validate({"turns": candidate["turns"]})
    characters = sum(len(turn.text) for turn in draft.turns)
    measure = candidate.get("measure") or {}
    if (measure.get("turns"), measure.get("characters")) != (len(draft.turns), characters):
        raise ResumeRefused("the_saved_candidate_does_not_match_its_recorded_measure")
    if check.get("passed") or not check.get("model_checked") or not check.get("issues"):
        raise ResumeRefused("the_saved_check_is_not_a_model_checked_refusal")
    issues = [DialogueIssue.model_validate(item) for item in check["issues"]]
    if any(issue.turn >= len(draft.turns) for issue in issues):
        raise ResumeRefused("a_flagged_turn_is_outside_the_candidate")
    report = DialogueCheckReport(issues=issues, model_checked=True)
    flagged = report.flagged_turns()
    if len(flagged) > (len(draft.turns) + 1) // 2:
        raise ResumeRefused("too_many_turns_flagged_for_a_local_repair")
    block = block_from_draft(
        draft, block_id=BLOCK_ID, slot_id=SLOT_ID, purpose=DialoguePurpose.STORY,
        duration_seconds=estimate_dialogue_seconds(characters),
        allowed_fact_refs=material.fact_ids, story_id=material.story_id,
    )  # fmt: skip
    if block.duration_seconds > budget.hard_max_seconds:
        raise ResumeRefused("the_saved_candidate_is_over_the_hard_maximum")
    return Prior(directory, hashes, station, conditions, summary, material, draft, block, issues, flagged)


def offline_fixes(prior: Prior) -> DialogueRepair:
    """Fixture repair for the offline path ONLY: drop the attribution lead-in, keep the facts."""

    fixes = []
    for index in sorted(prior.flagged):
        turn = prior.block.turns[index]
        text = re.sub(r"(他还说过|他说过|他曾说过)[，,]", "", turn.text, count=1)
        fixes.append(TurnFix(turn=index, text=text.strip(), fact_refs=list(turn.fact_refs)))
    return DialogueRepair(fixes=fixes)


class _OfflinePassingChecker:
    """Offline stand-in for the whole-passage re-check: passes, and says so.

    A scripted judge cannot reproduce what the real checker cites (one source window per
    sentence that must carry every qualifier), so offline the re-check is stubbed and only the
    path around it is exercised.  The real code gates run only on the live call.
    """

    async def review(self, block: DialogueBlock, material: StoryMaterial) -> DialogueCheckReport:
        return DialogueCheckReport(model_checked=True, supported={0: []})


async def run(args: argparse.Namespace) -> dict[str, Any]:
    prior = load_prior(args.from_dir)
    budget = dialogue_budget_for(prior.station)
    assert budget is not None
    schemas = [to_strict_schema(model.model_json_schema()) for model in (DialogueRepair, DialogueCheck)]
    if shutil.which("ffmpeg") is None:
        raise ResumeRefused("ffmpeg_unavailable")
    flagged = prior.flagged
    plan = {
        "resumed_from": str(prior.directory),
        "source_sha256": prior.hashes,
        "condition": prior.conditions,
        "flagged_turns": sorted(flagged),
        "flagged_reasons_codes": sorted({issue.code for issue in prior.issues}),
        "unchanged_turns": [i for i in range(len(prior.block.turns)) if i not in flagged],
        "strict_schemas_ok": len(schemas) == 2,
        "max_new_paid_calls": {"repair_lite": 1, "recheck_pro": 1, "speech": 1},
        "automatic_retry": False,
        "second_repair_or_redraw_or_single_voice_fallback": False,
        "max_audio_seconds": budget.hard_max_seconds,
        "repaired_once": True,
        "mode": "live" if args.live else "offline" if args.offline else "dry_run",
    }
    if not args.live and not args.offline:
        return {**plan, "status": "plan_validated", "network_calls": 0}

    ark_key = os.environ.get("ARK_API_KEY", "") if args.live else ""
    podcast_key = os.environ.get("DOUBAO_PODCAST_API_KEY", "") if args.live else ""
    if args.live and args.prompt_keys:
        ark_key = getpass.getpass("Temporary Ark key: ")
        podcast_key = getpass.getpass("Temporary Doubao podcast key: ")
    if args.live and not (ark_key and podcast_key):
        raise ResumeRefused("temporary_keys_required")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    with (args.run_dir / "attempt.json").open("x", encoding="utf-8") as marker:
        json.dump(plan, marker, ensure_ascii=False, indent=2)

    ledger = UsageLedger()
    clients: list[ArkLLMProvider] = []
    storage = LocalObjectStorageProvider(args.run_dir / "assets")
    state: dict[str, Any] = {**plan, "status": "started", "stage": "repair"}
    stage_seconds: dict[str, float] = {}
    clock = time.monotonic()
    material, block = prior.material, prior.block

    def mark(stage: str) -> None:
        nonlocal clock
        now = time.monotonic()
        stage_seconds[stage] = round(now - clock, 2)
        clock = now
        state["stage_seconds"] = dict(stage_seconds)

    def keep(name: str, value: Any) -> None:
        save(args.run_dir / name, value)
        state.setdefault("saved_artifacts", []).append(name)

    try:
        if args.offline:
            from tests.dialogue_fixtures import ScriptedLLM

            fixture = offline_fixes(prior)
            repair_llm: Any = ScriptedLLM(fixture)
            checker_llm: Any = None
            speech: Any = MockDialogueSpeechProvider(storage, fixed_duration_seconds=3)
            state["provenance"] = "OFFLINE: fixture repair, re-check STUBBED to pass; no model produced or judged the text"
        else:
            settings = ProviderSettings(mode="live", ark_api_key=ark_key, ark_max_output_tokens=4096)
            for model, role in ((args.repair_model, "writer"), (args.checker_model, "fact_check")):
                clients.append(ArkLLMProvider(settings, model=model, role=role, ledger=ledger))
            repair_llm, checker_llm = clients
            speech = DoubaoPodcastSpeechProvider(
                DoubaoPodcastWebSocketTransport(podcast_key, max_audio_seconds=float(budget.hard_max_seconds)),
                storage, ledger=ledger,
            )  # fmt: skip
        with usage_scope(EPISODE_ID):
            repair = await DialogueRepairer(repair_llm).repair(block, material, flagged)
            mark("repair")
            keep("repair.output.json", {
                "status": "repair output of the model; unchecked",
                "fixes": [fix.model_dump(mode="json") for fix in repair.fixes],
            })
            state["stage"] = "apply_repair"
            repaired = DialoguePipeline._apply(block, repair, set(flagged), material)
            if repaired is None:
                raise ValueError("invalid_repair")
            # Only the flagged turns may differ: same count, same speakers, other turns identical.
            same_shape = len(repaired.turns) == len(block.turns) and all(
                new.speaker == old.speaker and (i in flagged or new == old)
                for i, (old, new) in enumerate(zip(block.turns, repaired.turns, strict=True))
            )
            characters = sum(len(turn.text) for turn in repaired.turns)
            state["after_repair"] = {
                "turns": len(repaired.turns),
                "characters": characters,
                "estimated_seconds": repaired.duration_seconds,
                "within_target": budget.target_characters[0] <= characters <= budget.target_characters[1],
                "over_hard_max": repaired.duration_seconds > budget.hard_max_seconds,
                "only_flagged_turns_changed": same_shape,
            }
            keep("candidate.repaired.unchecked.json", {
                "status": "UNCHECKED: after one local repair; not yet re-checked",
                "changed_turns": sorted(flagged),
                "turns": [
                    {"turn": i, "speaker": new.speaker.value, "changed": i in flagged,
                     "before": old.text if i in flagged else None, "text": new.text, "fact_refs": new.fact_refs}
                    for i, (old, new) in enumerate(zip(block.turns, repaired.turns, strict=True))
                ],
                "measure": state["after_repair"],
            })  # fmt: skip
            if not same_shape:
                raise ValueError("repair_changed_more_than_the_flagged_turns")
            if repaired.duration_seconds > budget.hard_max_seconds:
                raise ValueError("too_long_after_repair")
            state["stage"] = "recheck"
            checker: Any = _OfflinePassingChecker() if args.offline else DialogueFactChecker(checker_llm)
            second = await checker.review(repaired, material)
            mark("recheck")
            keep("check.after-repair.json", {
                "model_checked": second.model_checked,
                "passed": bool(second.model_checked and not second.issues),
                "issues": [issue.model_dump(mode="json") for issue in second.issues],
                "supported_by_turn": {str(turn): refs for turn, refs in second.supported.items()},
            })
            if not second.model_checked or second.issues:
                state["issue_codes"] = sorted({issue.code for issue in second.issues})
                raise ValueError("unresolved_after_repair")
            outcome = DialogueOutcome(
                status=DialogueStatus.REPAIRED, block=repaired, material=material,
                first_check_issues=prior.issues, repaired_turns=sorted(flagged),
                calls=4, model_checked=True, station_value=prior.station.value,
            )  # fmt: skip
            artifacts = DialogueArtifactStore(storage)
            await artifacts.save(EPISODE_ID, outcome.to_record())
            keep("candidate.checked.json", {
                "status": "CHECKED after ONE local repair (turns " + ", ".join(map(str, sorted(flagged))) + ")",
                "turns": [turn.model_dump(mode="json") for turn in repaired.turns],
            })
            segment = narration_segment_from_record(outcome.to_record(), chapter_id="chapter-1", order=0)
            materializer = NarrationMaterializer(
                MockTTSProvider(storage), storage, dialogue_speech=speech,
                dialogue_voices=VOICE_COMBINATION_B, dialogue_speed=0, dialogue_format="wav",
            )  # fmt: skip
            state["stage"] = "speech"
            await voice_segment(materializer, artifacts, EPISODE_ID, segment)
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
                episode_id=EPISODE_ID, duration_seconds=duration,
                clips=(AudioClip(
                    id="probe-voice", segment_id=segment.id, source_url=segment.audio_source_url,
                    lane="VOICE", timeline_start_seconds=0, source_offset_seconds=0,
                    playable_duration_seconds=duration,
                ),), segment_starts={segment.id: 0},
            )  # fmt: skip
            manifest = await render_program_prefix(mix, storage, complete=True)
            if not manifest.chunks:
                raise ValueError("hls_has_no_chunks")
            if await render_program_prefix(mix, storage, complete=True) != manifest:
                raise ValueError("hls_not_repeatable")
            mark("hls")
            state.update(status="completed", audio_seconds=duration, hls_chunks=len(manifest.chunks))
            state["turn_timings"] = stored.metadata.get("turn_timings")
    except asyncio.CancelledError:
        state.update(status="cancelled", error_type="CancelledError")
        raise
    except Exception as error:  # never persist provider exception text
        state.update(status="failed", error_type=type(error).__name__, failed_stage=state.get("stage"))
        if isinstance(error, ValueError) and re.fullmatch(r"[a-z_]+", str(error)):
            state["reason"] = str(error)
    finally:
        before = (prior.summary.get("providers") or {}).get("usage") or {}
        state["conclusions"] = {
            f"{prior.station.value}_chain_passed_after_one_local_repair": state.get("status") == "completed" and args.live,
            "first_pass_without_repair": False,
            "casual_length_control": "not_passed (earlier attempt, not re-tested)",
            "open_issue": (
                "first-person interview attribution ('he said ...') is refused by the short-quotation "
                "qualifier rule; the rule is kept as it is and is NOT claimed to be right"
            ),
        }
        # Two ledgers, never summed into one claim: the earlier run, and this increment.
        state["previous_run_usage"] = {
            "source": str(prior.directory / "summary.safe.json"),
            "estimated_cost_cny": before.get("estimated_cost_cny"),
            "input_tokens": before.get("input_tokens"),
            "output_tokens": before.get("output_tokens"),
            "paid_calls": prior.summary.get("live_calls"),
        }
        state["increment"] = usage_diagnostics(ledger, scope=EPISODE_ID)
        state["increment_paid_calls"] = len(ledger.events) if args.live else 0
        save(args.run_dir / "summary.safe.json", state)
        for client in clients:
            await client.aclose()
    return state


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    arguments_ = arguments()
    try:
        result = asyncio.run(run(arguments_))
    except (Exception, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, ResumeRefused) else None
        print(json.dumps({"status": "stopped", "error_type": type(error).__name__, "reason": reason, "automatic_retry": False}))
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] in ("plan_validated", "completed") else 1)
