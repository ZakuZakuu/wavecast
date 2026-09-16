"""Credential-free retrieval benchmark cases and synthetic version fixtures."""

from pydantic import BaseModel, Field

from wavecast.providers.retrieval import VersionKind


class RetrievalBenchmarkCase(BaseModel):
    case_id: str
    query: str
    requested_artist: str | None = None
    requested_title: str | None = None


class RetrievalFixtureTrack(BaseModel):
    provider: str
    track_ref: str
    artist: str
    title: str
    duration_seconds: int = Field(gt=0)
    version_kind: VersionKind = VersionKind.UNKNOWN


RETRIEVAL_BENCHMARK_CASES: tuple[RetrievalBenchmarkCase, ...] = (
    RetrievalBenchmarkCase(
        case_id="third-coast-jealousy",
        query="3rd Coast - Jealousy",
        requested_artist="3rd Coast",
        requested_title="Jealousy",
    ),
    RetrievalBenchmarkCase(
        case_id="third-coast-luv-is-true",
        query="3rd Coast - Luv is True",
        requested_artist="3rd Coast",
        requested_title="Luv is True",
    ),
    RetrievalBenchmarkCase(case_id="clazziquai-project", query="Clazziquai Project"),
    RetrievalBenchmarkCase(
        case_id="persona-4-specialist",
        query="Persona 4 - Specialist",
        requested_title="Specialist",
    ),
)


SYNTHETIC_RETRIEVAL_FIXTURES: tuple[RetrievalFixtureTrack, ...] = (
    RetrievalFixtureTrack(
        provider="netease",
        track_ref="netease:studio-1",
        artist="Fixture Artist",
        title="Same Song",
        duration_seconds=180,
    ),
    RetrievalFixtureTrack(
        provider="qqmusic",
        track_ref="qqmusic:studio-1",
        artist="Fixture Artist",
        title="Same Song",
        duration_seconds=181,
    ),
    RetrievalFixtureTrack(
        provider="audius",
        track_ref="audius:studio-1",
        artist="Fixture Artist",
        title="Same Song",
        duration_seconds=182,
    ),
    RetrievalFixtureTrack(
        provider="audius",
        track_ref="audius:live-1",
        artist="Fixture Artist",
        title="Same Song (Live)",
        duration_seconds=220,
        version_kind=VersionKind.LIVE,
    ),
    RetrievalFixtureTrack(
        provider="netease",
        track_ref="netease:remix-1",
        artist="Fixture Artist",
        title="Same Song - Remix",
        duration_seconds=190,
        version_kind=VersionKind.REMIX,
    ),
)
