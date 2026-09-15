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
    def __init__(
        self,
        provider: str,
        delay: float = 0,
        *,
        fail: bool = False,
        ledger: UsageLedger | None = None,
    ) -> None:
        self.provider = provider
        self.delay = delay
        self.fail = fail
        self.ledger = ledger
        self.calls: list[str] = []

    async def search(
        self, query: str, *, limit: int = 5, stage: str | None = None
    ) -> list[SearchResult]:
        del limit
        self.calls.append(query)
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError(f"{self.provider} failed")
        result = [
            SearchResult(
                title=f"{self.provider} Artist - Candidate",
                url=f"https://example.test/{self.provider}",
                snippet=f"{self.provider} evidence",
                provider=self.provider,
                query=query,
                score=0.8,
            )
        ]
        if self.ledger:
            self.ledger.record(
                UsageEvent(
                    provider=self.provider,
                    operation="search",
                    request_id=query,
                    elapsed_ms=1,
                    search_queries=1,
                    metadata={"stage": stage} if stage else {},
                )
            )
        return result


def request() -> FastResearchInput:
    return FastResearchInput(
        topic="smooth urban lounge",
        anchor_tracks=["3rd Coast - Jealousy", "3rd Coast - Luv is True"],
        desired_duration_seconds=1800,
    )


def test_fast_research_runs_both_queries_concurrently_and_records_stage() -> None:
    ledger = UsageLedger()
    exa = DelayedSearch("exa", delay=0.04, ledger=ledger)
    tavily = DelayedSearch("tavily", delay=0.04, ledger=ledger)
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
    assert result.bundle.candidates == []
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


def test_background_queries_have_distinct_local_bridge_and_cross_scene_roles() -> None:
    queries = build_background_queries(request())

    assert len(queries) == 3
    assert len(set(queries)) == 3
    assert "close musical similarity" in queries[0]
    assert "bridge" in queries[1]
    assert "cross-scene" in queries[2]
    assert "same-artist" in queries[2]


def test_background_same_provider_events_keep_distinct_stage_attribution() -> None:
    from wavecast.intelligence.models import FastResearchResult, ResearchBundle
    from wavecast.intelligence.research import BackgroundResearchService

    ledger = UsageLedger()

    class StageSearch(DelayedSearch):
        async def search(
            self, query: str, *, limit: int = 5, stage: str | None = None
        ) -> list[SearchResult]:
            result = await super().search(query, limit=limit, stage=stage)
            ledger.record(
                UsageEvent(
                    provider=self.provider,
                    operation="search",
                    request_id=query,
                    elapsed_ms=1,
                    metadata={"stage": stage},
                )
            )
            return result

    fast_result = FastResearchResult(
        bundle=ResearchBundle(
            anchors=request().anchor_tracks,
            taste_hypotheses=[],
            evidence=[],
            candidates=[],
        ),
        elapsed_ms=0,
        queries=["fast-exa", "fast-tavily"],
    )
    tavily = StageSearch("tavily", delay=0.01)
    background = BackgroundResearchService(
        discovery=StageSearch("exa", delay=0.01),
        research=tavily,
        ledger=ledger,
        deadline_seconds=0.2,
    )

    result = asyncio.run(background.run(request(), fast_result))

    assert result is not None
    tavily_events = [event for event in ledger.events if event.provider == "tavily"]
    assert len(tavily_events) == 2
    assert {event.request_id for event in tavily_events} == set(
        build_background_queries(request())[1:]
    )
    assert all(event.metadata["stage"] == "background_research" for event in tavily_events)
