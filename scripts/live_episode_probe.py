#!/usr/bin/env python3
"""Opt-in bounded live end-to-end episode assembly probe.

No provider call is made unless ``--run-live`` is supplied.  The report contains
only stage timings, usage totals, catalog identities and timeline metadata; it
never prints prompts, narration text, provider payloads or credentials.

Before constructing any live research, LLM, or TTS provider, the probe checks
the configured music sidecar readiness and resolves every explicit anchor.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from wavecast.assembly import (
    EpisodeAssemblyError,
    LiveEpisodeAssemblyRequest,
    create_episode_assembly_service,
)
from wavecast.intelligence.curation import CuratorContractError
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import (
    ProviderAuthenticationError,
    ProviderBudgetExceededError,
    ProviderConfigurationError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderOutputLimitError,
    ProviderRateLimitError,
    ProviderSchemaValidationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from wavecast.providers.usage import UsageEvent, UsageLedger, usage_diagnostics

if __package__:
    from scripts.music_preflight import MusicPreflightError, preflight_music
else:  # pragma: no cover - exercised by direct opt-in script execution
    from music_preflight import MusicPreflightError, preflight_music

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="authorize one bounded live run")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--anchor", action="append", default=[])
    parser.add_argument("--max-tracks", type=int, default=4)
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def _load_probe_environment() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=True)


def _safe_trace(result) -> list[dict[str, object]]:
    allowed = {
        "fallback",
        "candidate_count",
        "chapter_count",
        "query_count",
        "elapsed_ms",
        "research_facet_count",
        "planned_background_query_count",
        "plan_source",
        "selected_queries",
        "chapter_index",
        "reference_kind",
        "dropped_reference_count",
        "remaining_reference_count",
    }
    return [
        {
            "name": event.name,
            "elapsed_ms": event.elapsed_from_start_ms,
            "metadata": {
                key: value for key, value in event.metadata.items() if key in allowed
            },
        }
        for event in result.trace.events
    ]


_KNOWN_PROVIDER_ERRORS = (
    ProviderTimeoutError,
    ProviderRateLimitError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderUnavailableError,
    ProviderBudgetExceededError,
    ProviderOutputLimitError,
    ProviderInvalidResponseError,
    ProviderError,
)


def _nearest_known_cause(error: EpisodeAssemblyError) -> ProviderError | CuratorContractError | None:
    cause = error.__cause__
    while cause is not None:
        if isinstance(cause, _KNOWN_PROVIDER_ERRORS) or isinstance(cause, CuratorContractError):
            return cause
        cause = cause.__cause__
    return None


def _failure_reason_code(
    stage: str,
    cause: ProviderError | CuratorContractError | None,
    explicit_reason_code: str | None = None,
) -> str:
    if explicit_reason_code:
        return explicit_reason_code
    if isinstance(cause, CuratorContractError):
        return cause.reason_code
    if isinstance(cause, ProviderTimeoutError):
        return "provider_timeout"
    if isinstance(cause, ProviderRateLimitError):
        return "provider_rate_limit"
    if isinstance(cause, ProviderAuthenticationError):
        return "provider_authentication"
    if isinstance(cause, ProviderConfigurationError):
        return "provider_configuration"
    if isinstance(cause, ProviderUnavailableError):
        return "provider_unavailable"
    if isinstance(cause, ProviderBudgetExceededError):
        return "provider_budget_exceeded"
    if isinstance(cause, ProviderOutputLimitError):
        return "provider_output_limit"
    if isinstance(cause, ProviderSchemaValidationError):
        if stage == "curator":
            return "curator_schema_invalid"
        return "structured_output_invalid"
    if isinstance(cause, ProviderInvalidResponseError):
        return "structured_output_invalid"
    return "unknown_provider_failure"


def _safe_usage_event(event: UsageEvent) -> dict[str, object]:
    from wavecast.providers.usage import safe_usage_event

    return safe_usage_event(event)


def _usage_diagnostics(ledger: UsageLedger) -> dict[str, object]:
    return usage_diagnostics(ledger)


def _failure_report(error: EpisodeAssemblyError, ledger: UsageLedger) -> dict[str, object]:
    cause = _nearest_known_cause(error)
    report: dict[str, object] = {
        "status": "failed",
        "stage": error.stage,
        "error_type": type(error).__name__,
        "cause_type": type(cause).__name__ if cause is not None else "UnknownError",
        "reason_code": _failure_reason_code(error.stage, cause, error.reason_code),
        **_usage_diagnostics(ledger),
    }
    if error.diagnostics:
        report.update(error.diagnostics)
    return report


def _report(result) -> dict[str, object]:
    episode = result.playable_episode
    research_plan = result.research_plan or result.fast_plan.research_plan
    writer_chapters = [
        {
            "chapter_index": item.chapter_index,
            "available_slots": [
                _safe_slot_context(slot) for slot in item.available_slots
            ],
            "parsed_blocks": [
                _safe_script_block(block) for block in item.parsed_blocks
            ],
            "normalized_blocks": [
                _safe_script_block(block) for block in item.normalized_blocks
            ],
            "normalized_slot_contexts": [
                _safe_slot_context(slot) for slot in item.normalized_slot_contexts
            ],
        }
        for item in result.writer_chapters
    ]
    return {
        "status": "ok",
        "timings": result.timings.model_dump(),
        "duration": result.duration_summary.model_dump(),
        "fast": {
            "fallback": result.trace.fallback_used,
            "ttfs_ms": result.trace.time_to_first_script_ms,
            "taste_dimensions": [
                hypothesis.dimension for hypothesis in result.fast_plan.immediate_taste_hypotheses
            ],
        },
        "research_plan": {
            "central_question": research_plan.central_question,
            "research_mode": research_plan.research_mode.value,
            "no_research_reason": research_plan.no_research_reason,
            "facets": [
                {
                    "id": facet.id,
                    "label": facet.label,
                    "question": facet.question,
                    "priority": facet.priority,
                    "source_preferences": list(facet.source_preferences),
                }
                for facet in research_plan.facets
            ],
            "background_queries": [
                {
                    "intent": query.intent.value,
                    "facet_ids": list(query.facet_ids),
                    "query": query.query,
                    "rationale": query.rationale,
                }
                for query in research_plan.background_queries
            ],
        },
        "research_evidence": [
            {
                "id": item.id,
                "canonical_url": item.canonical_url or item.source_url,
                "source_domain": item.source_domain,
                "source_category": item.source_category.value,
                "source_preference_rank": item.source_preference_rank,
                "source_provider": item.source_provider,
                "source_title": item.source_title,
                "confidence": item.confidence,
                "facet_ids": list(item.facet_ids),
                "search_intent": item.search_intent.value if item.search_intent else None,
            }
            for item in result.research_evidence
        ],
        "program_skeleton": {
            "thesis": result.skeleton.thesis,
            "estimated_duration_seconds": result.skeleton.estimated_duration_seconds,
            "chapters": [
                {
                    "index": chapter.index,
                    "narrative_role": chapter.narrative_role.value,
                    "reason": chapter.reason,
                    "narration_goal": chapter.narration_goal,
                    "evidence_ids": list(chapter.evidence_ids),
                    "claim_support": [
                        {
                            "claim_type": support.claim_type.value,
                            "claim": support.claim,
                            "evidence_ids": list(support.evidence_ids),
                        }
                        for support in chapter.claim_support
                    ],
                    "novelty_distance": (
                        chapter.novelty_distance.value if chapter.novelty_distance else None
                    ),
                    "track": (
                        {"artist": chapter.track.artist, "title": chapter.track.title}
                        if chapter.track is not None
                        else None
                    ),
                }
                for chapter in result.skeleton.chapters
            ],
        },
        "tracks": [
            {
                "artist": track.canonical_artist,
                "title": track.canonical_title,
                "track_ref": track.track_ref,
            }
            for track in result.resolved_tracks
        ],
        "unresolved": [
            {
                "chapter_index": item.chapter_index,
                "artist": item.proposal.artist,
                "title": item.proposal.title,
                "reason": item.reason,
            }
            for item in result.unresolved_proposals
        ],
        "segments": [
            {
                "kind": segment.kind.value,
                "state": segment.state.value,
                "duration_seconds": segment.duration_seconds,
                "asset_url": _safe_asset_url(segment.audio_source_url),
            }
            for segment in episode.segments
        ],
        "usage": result.usage.model_dump(),
        "usage_by_stage": {
            stage: totals.model_dump() for stage, totals in result.usage_by_stage.items()
        },
        "provider_events": list(result.provider_events),
        "trace": _safe_trace(result),
        "writer_chapters": writer_chapters,
        "writer_counts": {
            "generated_blocks": sum(
                len(item.parsed_blocks) for item in result.writer_chapters
            ),
            "normalized_blocks": sum(
                len(item.normalized_blocks) for item in result.writer_chapters
            ),
            "final_timeline_narration_segments": sum(
                segment.kind.value == "NARRATION" for segment in episode.segments
            ),
        },
    }


def _safe_track(track) -> dict[str, str] | None:
    if track is None:
        return None
    return {
        "track_ref": track.track_ref,
        "artist": track.canonical_artist,
        "title": track.canonical_title,
    }


def _safe_script_block(block) -> dict[str, object]:
    return {
        "kind": block.kind.value,
        "text": block.text,
        "tts_text": block.tts_text,
        "duration_seconds": block.intended_duration_seconds,
        "track_index": block.track_index,
        "tts_cues": list(block.tts_cues),
        "evidence_ids": list(block.evidence_ids),
        "claim_support": [
            {
                "claim_type": support.claim_type.value,
                "claim": support.claim,
                "evidence_ids": list(support.evidence_ids),
            }
            for support in block.claim_support
        ],
    }


def _safe_slot_context(context) -> dict[str, object]:
    return {
        "slot_id": context.slot_id,
        "chapter_index": context.chapter_index,
        "placement": context.placement.value,
        "allowed_block_kinds": [kind.value for kind in context.allowed_block_kinds],
        "chapter_track": _safe_track(context.chapter_track),
        "just_played_track": _safe_track(context.just_played_track),
        "upcoming_track": _safe_track(context.upcoming_track),
        "is_opening": context.is_opening,
        "is_final": context.is_final,
    }


def _safe_asset_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("/api/"):
        return url
    parsed = urlsplit(url)
    if parsed.scheme and parsed.hostname:
        return f"{parsed.scheme}://{parsed.hostname}/[external-redacted]"
    return "[external-redacted]"


async def _run(arguments: argparse.Namespace) -> int:
    settings = ProviderSettings.from_env()
    if settings.mode != "live":
        raise ProviderConfigurationError("set WAVECAST_PROVIDER_MODE=live in the local .env")

    try:
        await preflight_music(settings, arguments.anchor)
    except MusicPreflightError as error:
        report = {
            "status": "preflight_failed",
            "stage": "music_readiness",
            "reason": str(error),
        }
        if arguments.json_output:
            arguments.json_output.write_text(json.dumps(report, ensure_ascii=False) + "\n")
        print(json.dumps(report, ensure_ascii=False))
        return 2

    service = create_episode_assembly_service(settings)
    try:
        result = await service.assemble(
            LiveEpisodeAssemblyRequest(
                topic=arguments.topic,
                anchor_tracks=arguments.anchor,
                max_tracks=arguments.max_tracks,
            ),
            request_id="live-episode-probe",
        )
        report = _report(result)
    except EpisodeAssemblyError as error:
        report = _failure_report(error, service.ledger)
        if arguments.json_output:
            arguments.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False))
        return 1
    finally:
        await service.aclose()

    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.json_output:
        arguments.json_output.write_text(serialized + "\n")
    print(serialized)
    return 0


def main() -> int:
    arguments = parse_args()
    if not arguments.run_live:
        raise SystemExit("pass --run-live explicitly; no provider calls were made")
    _load_probe_environment()
    try:
        return asyncio.run(_run(arguments))
    except (ProviderConfigurationError, ProviderError) as error:
        print(
            json.dumps(
                {"status": "failed", "stage": "configuration", "error_type": type(error).__name__}
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
