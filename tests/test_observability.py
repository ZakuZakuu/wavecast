import asyncio
import logging

import pytest
from fastapi.testclient import TestClient
from wavecast.providers.errors import ProviderAuthenticationError
from wavecast.providers.usage import (
    UsageEvent,
    UsageLedger,
    scoped_to_episode,
    usage_diagnostics,
    usage_scope,
)

from services.api import main as api_module
from tests.test_catalog_pool import SidecarLikeCatalog, builder, proposal, track


def _event(operation: str = "chat", stage: str | None = "writer", **fields: object) -> UsageEvent:
    return UsageEvent(
        provider="deepseek",
        operation=operation,
        elapsed_ms=120,
        metadata={"stage": stage} if stage else {},
        **fields,  # type: ignore[arg-type]
    )


def test_events_are_attributed_to_the_scope_they_were_recorded_in() -> None:
    ledger = UsageLedger()
    with usage_scope("episode-a"):
        ledger.record(_event(input_tokens=10, output_tokens=5))
    with usage_scope("episode-b"):
        ledger.record(_event(input_tokens=1))
    ledger.record(_event())

    assert [event.scope for event in ledger.events] == ["episode-a", "episode-b", None]
    report = usage_diagnostics(ledger, scope="episode-a")
    assert report["usage"]["input_tokens"] == 10
    assert report["usage"]["event_count"] == 1
    assert report["usage_by_stage"]["writer"]["output_tokens"] == 5
    assert usage_diagnostics(ledger)["usage"]["event_count"] == 3


def test_the_scope_is_restored_even_when_the_block_fails() -> None:
    with pytest.raises(RuntimeError), usage_scope("boom"):
        raise RuntimeError
    assert _event().scope is None


def test_the_ledger_keeps_only_the_most_recent_events() -> None:
    ledger = UsageLedger(max_events=3)
    for index in range(5):
        ledger.record(_event(input_tokens=index))

    assert [event.input_tokens for event in ledger.events] == [2, 3, 4]


def test_each_provider_call_is_logged_without_prompt_or_url_content(caplog) -> None:
    ledger = UsageLedger()
    secret = "https://signed.example/audio?token=SECRET"
    with caplog.at_level(logging.INFO, logger="wavecast.usage"), usage_scope("ep-1"):
        event = _event(input_tokens=7)
        event.metadata["prompt"] = "private prompt text"
        event.metadata["playback_url"] = secret
        ledger.record(event)

    line = next(record.getMessage() for record in caplog.records if "provider_call" in record.getMessage())
    assert "provider=deepseek" in line and "stage=writer" in line and "scope=ep-1" in line
    assert "in=7" in line and "ms=120" in line
    assert "private prompt" not in line and "SECRET" not in line


def test_scoped_to_episode_marks_calls_made_while_working_on_an_episode() -> None:
    ledger = UsageLedger()

    class Worker:
        @scoped_to_episode
        async def work(self, episode: object, value: int) -> int:
            ledger.record(_event())
            return value + 1

    class Episode:
        id = "episode-9"

    assert asyncio.run(Worker().work(Episode(), 1)) == 2
    assert ledger.events[0].scope == "episode-9"
    assert _event().scope is None


def test_catalog_failures_are_counted_by_provider_and_kind() -> None:
    class Refused(SidecarLikeCatalog):
        async def search(self, query: str, *, limit: int = 5):  # type: ignore[no-untyped-def]
            raise ProviderAuthenticationError("music request failed with HTTP 401")

    catalog = Refused([track("1", "A", "One")], {"A One": ["1"]})

    pool = asyncio.run(builder(catalog).build(proposals=[proposal("A", "One")]))

    assert pool.failure_kinds == {"netease:ProviderAuthenticationError": pool.search_failure_count}
    assert pool.summary()["failure_kinds"] == pool.failure_kinds
    assert "HTTP 401" not in str(pool.summary())


def test_an_unavailable_catalog_is_told_apart_from_a_refused_credential() -> None:
    catalog = SidecarLikeCatalog([track("1", "A", "One")], {"A One": ["1"]}, fail_search=True)

    pool = asyncio.run(builder(catalog).build(proposals=[proposal("A", "One")]))

    assert list(pool.failure_kinds) == ["netease:ProviderUnavailableError"]


def test_the_usage_endpoint_summarises_an_episode_for_its_owner_only() -> None:
    client = TestClient(api_module.app)
    owner = {"X-Wavecast-Listener": "usage-owner"}
    created = client.post("/api/episodes/from-seed/synthpop-return", headers=owner).json()

    response = client.get(f"/api/episodes/{created['id']}/usage", headers=owner)

    assert response.status_code == 200
    body = response.json()
    assert body["episode_id"] == created["id"]
    assert body["programme"]["music_segments"] >= 1
    assert set(body["programme"]) >= {
        "estimated_duration_seconds",
        "timeline_duration_seconds",
        "narration_skipped",
    }
    other = client.get(
        f"/api/episodes/{created['id']}/usage", headers={"X-Wavecast-Listener": "stranger"}
    )
    assert other.status_code == 404


def test_failures_of_artist_searches_are_counted_too() -> None:
    catalog = SidecarLikeCatalog([track("1", "A", "One")], {"A": ["1"]}, fail_search=True)

    pool = asyncio.run(builder(catalog).build(artist_queries=["A"]))

    assert pool.failure_kinds == {"netease:ProviderUnavailableError": 1}


def test_finishing_a_programme_logs_estimated_against_actual_length(caplog) -> None:
    from wavecast.models.episode import CoverParams, EpisodeSeed
    from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository

    seed = EpisodeSeed(
        id="seed-log",
        title="Log",
        topic="Test topic",
        short_description="x",
        estimated_duration_seconds=300,
        opening_track_ref="mock:opening",
        opening_track_title="Opening",
        opening_track_artist="Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
    )
    orchestrator = EpisodeOrchestrator(InMemoryEpisodeRepository())
    episode = orchestrator.start(seed)

    with caplog.at_level(logging.INFO, logger="wavecast.orchestration.episode"):
        done = orchestrator.materialize_all(episode.id)

    line = next(
        record.getMessage() for record in caplog.records if "episode_materialized" in record.getMessage()
    )
    assert "estimated_s=300" in line
    assert f"actual_s={done.timeline_duration_seconds}" in line
    assert "music=" in line and "skipped=0" in line


def test_skipped_narration_is_counted_even_though_the_timeline_leaves_it_out(caplog) -> None:
    from wavecast.models.episode import (
        CoverParams,
        EpisodeSeed,
        NarrationSegment,
        SegmentState,
    )
    from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository

    seed = EpisodeSeed(
        id="seed-skip",
        title="Skip",
        topic="Test topic",
        short_description="x",
        estimated_duration_seconds=300,
        opening_track_ref="mock:opening",
        opening_track_title="Opening",
        opening_track_artist="Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
    )
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    episode = orchestrator.start(seed)
    episode.segments.append(
        NarrationSegment(
            id="skipped-one",
            chapter_id="chapter-9",
            order=99,
            state=SegmentState.SKIPPED,
            planned_duration_seconds=1,
            title="Optional narration skipped",
        )
    )
    repository.save(episode)

    with caplog.at_level(logging.INFO, logger="wavecast.orchestration.episode"):
        orchestrator.materialize_all(episode.id)

    line = next(
        record.getMessage() for record in caplog.records if "episode_materialized" in record.getMessage()
    )
    assert "skipped=1" in line

    client = TestClient(api_module.app)
    headers = {"X-Wavecast-Listener": "skip-owner"}
    created = client.post("/api/episodes/from-seed/synthpop-return", headers=headers).json()
    stored = api_module.orchestrator.get(created["id"])
    stored.segments.append(
        NarrationSegment(
            id="skipped-two",
            chapter_id="chapter-9",
            order=99,
            state=SegmentState.SKIPPED,
            planned_duration_seconds=1,
            title="Optional narration skipped",
        )
    )
    api_module.repository.save(stored)
    body = client.get(f"/api/episodes/{created['id']}/usage", headers=headers).json()
    assert body["programme"]["narration_skipped"] == 1
