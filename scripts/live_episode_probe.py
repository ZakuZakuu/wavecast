#!/usr/bin/env python3
"""Opt-in bounded live end-to-end episode assembly probe.

No provider call is made unless ``--run-live`` is supplied.  The report contains
only stage timings, usage totals, catalog identities and timeline metadata; it
never prints prompts, narration text, provider payloads or credentials.
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
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderConfigurationError, ProviderError

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
    allowed = {"fallback", "candidate_count", "chapter_count", "query_count", "elapsed_ms"}
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


def _report(result) -> dict[str, object]:
    episode = result.playable_episode
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
        "trace": _safe_trace(result),
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
        report = {"status": "failed", "stage": error.stage, "error_type": type(error).__name__}
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
