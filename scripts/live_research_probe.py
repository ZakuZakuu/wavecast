"""One bounded, manual provider-quality probe for the 3rd Coast scenario."""

import argparse
import asyncio
import json
from pathlib import Path

from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import SearchResult
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import ProviderConfigurationError, ProviderError
from wavecast.providers.probe import ResearchProbeReport
from wavecast.providers.routing import SearchIntent, SearchRouter
from wavecast.providers.search import ExaSearchProvider, TavilySearchProvider
from wavecast.providers.usage import UsageLedger

MAX_EXA_QUERIES = 2
MAX_TAVILY_QUERIES = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", action="append", required=True)
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def require_live_settings() -> ProviderSettings:
    settings = ProviderSettings.from_env()
    if settings.mode != "live":
        raise ProviderConfigurationError("set WAVECAST_PROVIDER_MODE=live for the research probe")
    return settings


def compact_results(results: list[SearchResult]) -> list[dict[str, object]]:
    return [
        result.model_dump(include={"title", "url", "snippet", "content", "provider", "query"})
        for result in results
    ]


async def run(anchors: list[str]) -> ResearchProbeReport:
    settings = require_live_settings()
    ledger = UsageLedger()
    async with (
        ExaSearchProvider(settings, ledger=ledger) as exa,
        TavilySearchProvider(settings, ledger=ledger) as tavily,
        DeepSeekLLMProvider(settings, ledger=ledger) as llm,
    ):
        router = SearchRouter(discovery=exa, research=tavily)
        anchor_text = " and ".join(anchors)
        discovery_queries = [
            f"music similar to {anchor_text}; smooth female vocals male rap jazzy house R&B lounge 2000s Korean Japanese music",
            f"{anchor_text} related artists scenes beyond DJMAX",
        ][:MAX_EXA_QUERIES]
        research_queries = [
            f"{anchor_text} DJMAX context musical style",
            "3rd Coast Korean music group Jealousy Luv is True",
            "2000s Korean Japanese jazzy house R&B lounge artists",
        ][:MAX_TAVILY_QUERIES]
        discovery = [
            await router.search(SearchIntent.DISCOVERY, query, limit=4)
            for query in discovery_queries
        ]
        evidence = [
            await router.search(SearchIntent.RESEARCH, query, limit=4) for query in research_queries
        ]
        synthesis_input = {
            "anchors": anchors,
            "exa_discovery": [compact_results(results) for results in discovery],
            "tavily_evidence": [compact_results(results) for results in evidence],
            "constraints": [
                "Do not assume every candidate is a DJMAX artist.",
                "Distinguish evidence from uncertainty.",
                "Cite result URLs in evidence_references when available.",
            ],
        }
        report = await llm.structured(
            "Synthesize this bounded provider probe into the requested JSON report. "
            f"Input: {json.dumps(synthesis_input, ensure_ascii=False)}",
            ResearchProbeReport,
        )
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
    print(f"Usage: {ledger.totals().model_dump_json()}")
    return report


if __name__ == "__main__":
    arguments = parse_args()
    try:
        probe_report = asyncio.run(run(arguments.anchor))
    except ProviderError as error:
        raise SystemExit(f"Live research probe failed: {error}") from error
    if arguments.json_output:
        arguments.json_output.write_text(
            json.dumps(probe_report.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
