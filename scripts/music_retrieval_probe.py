"""Opt-in normalized metadata probe for configured music catalog sidecars."""

import argparse
import asyncio
import time

from wavecast.providers.audius import AudiusMusicProvider
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderConfigurationError, ProviderError
from wavecast.providers.netease import NeteaseMusicProvider
from wavecast.providers.qqmusic import QQMusicProvider
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService

DEFAULT_QUERIES = (
    "3rd Coast - Jealousy",
    "3rd Coast - Luv is True",
    "Clazziquai Project",
    "Persona 4 - Specialist",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="confirm the opt-in network probe")
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--limit", type=int, default=5)
    return parser.parse_args()


def configured_providers(settings: ProviderSettings) -> dict[str, object]:
    providers: dict[str, object] = {}
    if settings.netease_music_api_base_url:
        providers["netease"] = NeteaseMusicProvider(settings)
    if settings.qq_music_api_base_url:
        providers["qqmusic"] = QQMusicProvider(settings)
    if settings.mode == "live" and (settings.audius_api_key or settings.audius_bearer_token):
        providers["audius"] = AudiusMusicProvider(settings)
    return providers


async def run(queries: list[str], limit: int) -> None:
    settings = ProviderSettings.from_env()
    if settings.mode != "live":
        raise ProviderConfigurationError("set WAVECAST_PROVIDER_MODE=live for this opt-in probe")
    if not queries:
        queries = list(DEFAULT_QUERIES)
    configured = configured_providers(settings)
    if not configured:
        raise ProviderConfigurationError(
            "configure at least one NETEASE_MUSIC_API_BASE_URL, QQ_MUSIC_API_BASE_URL, or Audius credential"
        )
    registry = MusicProviderRegistry(configured)
    retrieval = MusicRetrievalService(registry)
    try:
        for query in queries:
            started = time.perf_counter()
            report = await retrieval.search_report(query, limit=limit)
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            for candidate in report.candidates:
                print(
                    f"query={query!r} provider={candidate.provider} "
                    f"artist={candidate.artist!r} title={candidate.title!r} "
                    f"version={candidate.version_kind.value} playable={candidate.playable} "
                    f"elapsed_ms={elapsed_ms}"
                )
            for failure in report.failures:
                print(f"query={query!r} provider={failure.provider} failure={failure.kind}")
    finally:
        for provider in configured.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


if __name__ == "__main__":
    arguments = parse_args()
    if not arguments.run_live:
        raise SystemExit("pass --run-live explicitly; no provider calls were made")
    try:
        asyncio.run(run(arguments.queries or [], arguments.limit))
    except ProviderError as error:
        raise SystemExit(f"music retrieval probe failed: {error}") from error
