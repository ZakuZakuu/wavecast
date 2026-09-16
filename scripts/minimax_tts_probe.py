#!/usr/bin/env python3
"""Opt-in, single-request MiniMax TTS smoke probe.

This script is intentionally not part of CI.  It requires ``--run-live`` and a
fully configured live environment before making one paid request.  The output
contains only safe request metadata and the WaveCast browser asset URL.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv
from wavecast.narration import render_narration
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderConfigurationError, ProviderError
from wavecast.providers.minimax import MiniMaxTTSProvider
from wavecast.storage import LocalObjectStorageProvider

TEXT = "今晚，我们从一首歌开始，听见城市夜色的回声。"
_SAFE_STATUS_PATTERN = re.compile(r"(?:HTTP|status)\s+(\d{3,4})\b", re.IGNORECASE)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_probe_environment() -> None:
    """Load the repository-local .env for this explicitly opt-in probe.

    The probe is a local diagnostic command, so the checked-out .env is the
    source of truth and takes precedence over stale exported provider values.
    CI has no .env file and remains credential-free.
    """
    load_dotenv(_PROJECT_ROOT / ".env", override=True)


async def _run_probe(settings: ProviderSettings) -> None:
    storage = LocalObjectStorageProvider()
    provider = MiniMaxTTSProvider(settings, storage=storage)
    rendered = render_narration(TEXT, [])
    started = perf_counter()
    try:
        asset = await provider.synthesize(rendered.text, cues=list(rendered.recognized_cues))
    finally:
        await provider.aclose()
    elapsed_ms = int((perf_counter() - started) * 1000)
    cache_hit = bool(asset.metadata.get("cache_hit", False))
    print(f"model={settings.minimax_tts_model}")
    print(f"voice_id={settings.minimax_tts_voice_id}")
    print(f"chars={len(TEXT)}")
    print(f"elapsed_ms={elapsed_ms}")
    print(f"duration={asset.duration}")
    print(f"cache={'hit' if cache_hit else 'miss'}")
    print(f"browser_asset_url={asset.playback_url}")


def _print_safe_failure(error: ProviderError) -> None:
    """Print only a provider error class and numeric status metadata."""
    print(f"error_type={type(error).__name__}", file=sys.stderr)
    match = _SAFE_STATUS_PATTERN.search(str(error))
    if match:
        print(f"provider_status={match.group(1)}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one opt-in MiniMax TTS smoke request")
    parser.add_argument(
        "--run-live",
        action="store_true",
        help="authorize the single live MiniMax request; omitted means no request",
    )
    args = parser.parse_args()
    if not args.run_live:
        raise SystemExit("pass --run-live explicitly; no provider calls were made")

    _load_probe_environment()
    settings = ProviderSettings.from_env()
    if settings.mode != "live":
        raise SystemExit("set WAVECAST_PROVIDER_MODE=live before running the probe")
    if not settings.minimax_api_key or not settings.minimax_tts_voice_id:
        raise SystemExit("configure MINIMAX_API_KEY and MINIMAX_TTS_VOICE_ID before running the probe")

    try:
        asyncio.run(_run_probe(settings))
    except ProviderConfigurationError as error:
        raise SystemExit("minimax probe configuration is incomplete") from error
    except ProviderError as error:
        # Never print provider response bodies, even when an adapter error is detailed.
        _print_safe_failure(error)
        raise SystemExit("minimax probe failed") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
