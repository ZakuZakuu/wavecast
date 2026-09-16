import asyncio

from wavecast.evals import RETRIEVAL_BENCHMARK_CASES, SYNTHETIC_RETRIEVAL_FIXTURES
from wavecast.providers.contracts import TrackMetadata
from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService, VersionKind


class FixtureProvider:
    def __init__(
        self,
        name: str,
        tracks: list[TrackMetadata],
        *,
        failure: Exception | None = None,
    ) -> None:
        self.name = name
        self.tracks = tracks
        self.failure = failure

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        del query
        if self.failure is not None:
            raise self.failure
        return self.tracks[:limit]


def benchmark_providers() -> dict[str, FixtureProvider]:
    grouped: dict[str, list[TrackMetadata]] = {}
    for fixture in SYNTHETIC_RETRIEVAL_FIXTURES:
        grouped.setdefault(fixture.provider, []).append(
            TrackMetadata(
                track_ref=fixture.track_ref,
                artist=fixture.artist,
                title=fixture.title,
                duration_seconds=fixture.duration_seconds,
                playable=True,
            )
        )
    grouped["audius"].append(
        TrackMetadata(
            track_ref="audius:broad-match",
            artist="Other Artist",
            title="Same Song",
            duration_seconds=170,
            playable=True,
        )
    )
    return {name: FixtureProvider(name, tracks) for name, tracks in grouped.items()}


def test_retrieval_benchmark_covers_long_tail_queries() -> None:
    queries = {case.query for case in RETRIEVAL_BENCHMARK_CASES}

    assert "3rd Coast - Jealousy" in queries
    assert "3rd Coast - Luv is True" in queries
    assert "Clazziquai Project" in queries
    assert "Persona 4 - Specialist" in queries
    persona_case = next(
        case for case in RETRIEVAL_BENCHMARK_CASES if case.case_id == "persona-4-specialist"
    )
    assert persona_case.requested_artist is None
    assert persona_case.requested_title == "Specialist"


def test_synthetic_retrieval_fixtures_preserve_version_alternatives() -> None:
    assert len(SYNTHETIC_RETRIEVAL_FIXTURES) == 5
    assert sum(
        fixture.version_kind is VersionKind.UNKNOWN for fixture in SYNTHETIC_RETRIEVAL_FIXTURES
    ) == 3
    assert any(fixture.version_kind is VersionKind.LIVE for fixture in SYNTHETIC_RETRIEVAL_FIXTURES)
    assert any(fixture.version_kind is VersionKind.REMIX for fixture in SYNTHETIC_RETRIEVAL_FIXTURES)


def test_synthetic_retrieval_benchmark_is_functional() -> None:
    providers = benchmark_providers()
    service = MusicRetrievalService(
        MusicProviderRegistry(providers, preference=("qqmusic", "netease", "audius"))
    )

    report = asyncio.run(
        service.search_report(
            "Fixture Artist - Same Song",
            requested_artist="Fixture Artist",
            requested_title="Same Song",
            limit=4,
        )
    )

    assert len(report.groups) == 4
    assert {
        group.candidates[0].version_kind
        for group in report.groups
        if group.candidates[0].artist == "Fixture Artist"
    } == {VersionKind.UNKNOWN, VersionKind.LIVE, VersionKind.REMIX}
    unknown_group = next(
        group for group in report.groups if group.candidates[0].version_kind is VersionKind.UNKNOWN
    )
    assert {candidate.provider for candidate in unknown_group.candidates} == {
        "netease",
        "qqmusic",
        "audius",
    }
    assert report.candidates[0].artist == "Fixture Artist"
    assert report.candidates[0].title == "Same Song"
    broad_match = next(candidate for candidate in report.candidates if candidate.artist == "Other Artist")
    assert report.candidates[0].score > broad_match.score

    limited = asyncio.run(
        service.search_report(
            "Fixture Artist - Same Song",
            requested_artist="Fixture Artist",
            requested_title="Same Song",
            limit=2,
        )
    )
    assert len(limited.groups) == 2
    limited_unknown = next(
        group
        for group in limited.groups
        if group.candidates[0].version_kind is VersionKind.UNKNOWN
    )
    assert len(limited_unknown.candidates) == 3

    failing_registry = MusicProviderRegistry(
        {
            **providers,
            "broken": FixtureProvider(
                "broken", [], failure=ProviderInvalidResponseError("fixture failure")
            ),
        }
    )
    failed_report = asyncio.run(
        MusicRetrievalService(failing_registry).search_report(
            "Fixture Artist - Same Song",
            requested_artist="Fixture Artist",
            requested_title="Same Song",
            limit=3,
        )
    )
    assert any(failure.provider == "broken" for failure in failed_report.failures)
    assert len(failed_report.groups) == 3
