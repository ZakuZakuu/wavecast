"""How varied are the openings of repeated proposals for the same request? (#202)

usage: uv run python scripts/eval_opening_diversity.py "<prompt>" [--samples 8] [--station casual]

Runs the proposal stage (one DeepSeek call and a few catalog lookups each; no research, no
TTS) ``samples`` times, four at a time, and prints the distribution of opening tracks.  Needs the
live provider configuration (the same selectors as scripts/cloud/start-api.sh --live); prints
counts and public track names only, never keys, tokens or URLs.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from wavecast.intelligence.models import OutputLanguage
from wavecast.proposals import LLMProgramProposalGenerator, ProposalGenerationRequest
from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.factory import build_music_registry
from wavecast.providers.retrieval import MusicRetrievalService
from wavecast.providers.usage import UsageLedger
from wavecast.stations import StationId

_PARALLEL = 4


async def main(prompt: str, samples: int, station: StationId | None) -> None:
    settings = ProviderSettings.from_env()
    generator = LLMProgramProposalGenerator(
        DeepSeekLLMProvider(settings.for_live_capability(), ledger=UsageLedger()),
        MusicRetrievalService(build_music_registry(settings)),
    )

    async def one() -> tuple[str, str]:
        try:
            proposal = (
                await generator.generate(
                    ProposalGenerationRequest(
                        prompt=prompt, output_language=OutputLanguage.ZH_CN, station=station
                    )
                )
            )[0]
        except Exception as error:  # noqa: BLE001 - report the class, never the message
            return ("(failed)", f"{type(error).__name__}:{getattr(error, 'reason', '')}")
        return (proposal.opening_track_artist, proposal.opening_track_title)

    results: list[tuple[str, str]] = []
    for start in range(0, samples, _PARALLEL):
        results += await asyncio.gather(*(one() for _ in range(min(_PARALLEL, samples - start))))
    ok = [item for item in results if item[0] != "(failed)"]
    print(f"prompt={prompt!r} samples={samples} ok={len(ok)} distinct_openings={len(set(ok))}")
    for (artist, title), count in Counter(results).most_common():
        print(f"  {count}x {artist} - {title}")
    print("artists:", dict(Counter(artist for artist, _ in ok)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--station", choices=[station.value for station in StationId], default=None)
    args = parser.parse_args()
    asyncio.run(main(args.prompt, args.samples, StationId(args.station) if args.station else None))
