"""Opt-in probe that builds a verified-playable catalog pool (ADR 0022).

Only the configured music catalog sidecar is contacted: no LLM, research or TTS
provider is constructed, so no paid call is made.  Output lists counts, catalog
artist/title strings and timings; it never prints playback URLs.

Example:
    WAVECAST_PROVIDER_MODE=live NETEASE_MUSIC_API_BASE_URL=http://127.0.0.1:3101 \
      uv run python scripts/catalog_pool_probe.py --run-live \
      --artist 椎名林檎 --keyword "椎名林檎 代表作" --proposal "久石让 - 娜乌西卡安魂曲"
"""

import argparse
import asyncio

from wavecast.catalog_pool import CatalogPoolBuilder, PoolBuildConfig
from wavecast.intelligence.models import TrackProposal
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.providers.factory import build_music_registry
from wavecast.providers.retrieval import MusicRetrievalService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="confirm the opt-in network probe")
    parser.add_argument("--artist", action="append", default=[], help="artist-centred query")
    parser.add_argument("--keyword", action="append", default=[], help="topic keyword query")
    parser.add_argument(
        "--proposal", action="append", default=[], help='LLM-style candidate: "Artist - Title"'
    )
    parser.add_argument("--max-verifications", type=int, default=24)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=45.0)
    return parser.parse_args()


def parse_proposal(value: str) -> TrackProposal:
    artist, separator, title = value.partition(" - ")
    if not separator or not artist.strip() or not title.strip():
        raise SystemExit(f'--proposal must look like "Artist - Title": {value!r}')
    return TrackProposal(artist=artist.strip(), title=title.strip(), confidence=0.5)


async def run(arguments: argparse.Namespace) -> None:
    settings = ProviderSettings.from_env()
    if settings.mode != "live":
        raise ProviderConfigurationError("set WAVECAST_PROVIDER_MODE=live for this opt-in probe")
    registry = build_music_registry(settings)
    builder = CatalogPoolBuilder(
        MusicRetrievalService(registry),
        PoolBuildConfig(
            max_verifications=arguments.max_verifications,
            concurrency=arguments.concurrency,
            timeout_seconds=arguments.timeout,
        ),
    )
    try:
        pool = await builder.build(
            proposals=[parse_proposal(item) for item in arguments.proposal],
            artist_queries=arguments.artist,
            keyword_queries=arguments.keyword,
        )
    finally:
        for _name, provider in registry.ordered():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
    print("summary:", pool.summary())
    for entry in pool.entries:
        print(
            f"playable source={entry.source.value} artist={entry.artist!r} "
            f"title={entry.title!r} seconds={entry.duration_seconds}"
        )
    for outcome in pool.outcomes:
        if outcome.status.value != "playable":
            print(
                f"{outcome.status.value} source={outcome.source.value} "
                f"artist={outcome.artist!r} title={outcome.title!r}"
            )


if __name__ == "__main__":
    parsed = parse_args()
    if not parsed.run_live:
        raise SystemExit("pass --run-live explicitly; no catalog calls were made")
    asyncio.run(run(parsed))
