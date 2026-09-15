import asyncio
from time import monotonic

from wavecast.intelligence.models import FastResearchInput
from wavecast.intelligence.research import (
    FastResearchService,
    build_background_queries,
    normalize_results,
)
from wavecast.intelligence.trace import GenerationTrace
from wavecast.providers.contracts import SearchResult
from wavecast.providers.usage import UsageEvent, UsageLedger


class DelayedSearch:
    def __init__(self, provider: str, delay: float = 0, *, fail: bool = False) -> None:
        self.provider = provider
        self.delay = delay
        self.fail = fail
        self.calls: list[str] = []

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        del limit
        self.calls.append(query)
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError(f"{self.provider} failed")
        return [
            SearchResult(
                title=f"{self.provider} Artist - Candidate",
                url=f"https://example.test/{self.provider}",
                snippet=f"{self.provider} evidence",
                provider=self.provider,
                query=query,
                score=0.8,
            )
        ]


def request() -> FastResearchInput:
    return FastResearchInput(
        topic="smooth urban lounge",
        anchor_tracks=["3rd Coast - Jealousy", "3rd Coast - Luv is True"],
        desired_duration_seconds=1800,
    )


def test_fast_research_runs_both_queries_concurrently_and_records_stage() -> None:
    exa = DelayedSearch("exa", delay=0.04)
    tavily = DelayedSearch("tavily", delay=0.04)
    ledger = UsageLedger()
    ledger.record(UsageEvent(provider="exa", operation="search", elapsed_ms=1))
    ledger.record(UsageEvent(provider="tavily", operation="search", elapsed_ms=1))
    trace = GenerationTrace(request_id="fast-1")
    service = FastResearchService(
        discovery=exa, research=tavily, ledger=ledger, deadline_seconds=0.2
    )

    started = monotonic()
    result = asyncio.run(service.run(request(), trace=trace))
    elapsed = monotonic() - started

    assert elapsed < 0.08
    assert len(exa.calls) == 1
    assert len(tavily.calls) == 1
    assert len(result.bundle.evidence) == 2
    assert "fast_research" in {
        event.metadata.get("stage") for event in ledger.events if event.metadata.get("stage")
    }
    assert trace.time_to_first_script_ms is None


def test_fast_research_keeps_success_when_one_provider_fails() -> None:
    exa = DelayedSearch("exa")
    tavily = DelayedSearch("tavily", fail=True)
    service = FastResearchService(discovery=exa, research=tavily, deadline_seconds=0.2)

    result = asyncio.run(service.run(request()))

    assert len(result.bundle.evidence) == 1
    assert any("tavily unavailable" in item for item in result.bundle.uncertainties)


def test_fast_research_anchor_only_is_valid_when_both_providers_fail() -> None:
    exa = DelayedSearch("exa", fail=True)
    tavily = DelayedSearch("tavily", fail=True)
    service = FastResearchService(discovery=exa, research=tavily, deadline_seconds=0.2)

    result = asyncio.run(service.run(request()))

    assert result.bundle.evidence == []
    assert result.bundle.candidates == []
    assert len(result.bundle.uncertainties) == 2
    assert result.bundle.anchors == request().anchor_tracks


def test_research_results_are_deduplicated_by_url_and_context_is_trimmed() -> None:
    first = SearchResult(
        title="A", url="https://example.test/a", snippet="x" * 1000, provider="exa", query="q"
    )
    duplicate = first.model_copy(update={"provider": "tavily"})

    normalized = normalize_results([first, duplicate])

    assert len(normalized) == 1
    assert len(normalized[0].snippet) == 600
    assert build_background_queries(request())[0] not in {
        "unused fast query"
    }
