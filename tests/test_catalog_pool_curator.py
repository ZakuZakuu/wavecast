import asyncio

import pytest
from wavecast.assembly import (
    LiveEpisodeAssemblyRequest,
    create_episode_assembly_service,
)
from wavecast.catalog_pool import (
    AvailabilityStatus,
    CandidateOutcome,
    CatalogPool,
    CatalogPoolBuilder,
    PoolBuildConfig,
    PoolEntry,
    PoolSource,
    artist_named_in_query,
)
from wavecast.intelligence.curation import CuratorService
from wavecast.intelligence.models import (
    ChapterPlan,
    FastStartPlan,
    NarrationScript,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    ResearchBundle,
    ResolvedTrack,
    TrackProposal,
)
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.providers.retrieval import VersionKind

from tests.test_episode_assembly import RecordingAssemblyLLM, service


def entry(
    ref: str, artist: str, title: str, source: PoolSource = PoolSource.KEYWORD_SEARCH
) -> PoolEntry:
    return PoolEntry(
        track_ref=f"netease:{ref}",
        artist=artist,
        title=title,
        primary_artist=artist.split(",")[0].strip(),
        duration_seconds=200,
        version_kind=VersionKind.UNKNOWN,
        source=source,
    )


# --- pool lookup and listing -------------------------------------------------------------


def test_find_matches_the_curator_copy_of_a_listed_track_including_script_variants() -> None:
    pool = CatalogPool(entries=[entry("1", "久石譲, 奥戸巴寿", "Spirited Away")])

    assert pool.find("久石譲, 奥戸巴寿", "Spirited Away") is not None
    assert pool.find("久石让", "spirited away") is not None  # shortened, variant, other case
    assert pool.find("久石譲", "Another Song") is None
    assert pool.find("木村弓", "Spirited Away") is None


def test_listing_orders_by_trust_and_caps_tracks_per_artist() -> None:
    pool = CatalogPool(
        entries=[
            *[entry(f"k{i}", "Spam Channel", f"Jazz {i}") for i in range(5)],
            entry("a", "Bill Evans", "Peace Piece", PoolSource.LLM_CANDIDATE),
            entry("b", "Oscar Peterson", "Hymn to Freedom", PoolSource.ARTIST_SEARCH),
        ]
    )

    listed = pool.listing(max_per_artist=2)

    assert [item.track_ref for item in listed[:2]] == ["netease:a", "netease:b"]
    assert sum(item.primary_artist == "Spam Channel" for item in listed) == 2


def test_artists_named_by_the_listener_get_a_higher_cap() -> None:
    pool = CatalogPool(
        entries=[
            *[entry(f"s{i}", "椎名林檎", f"Song {i}", PoolSource.ARTIST_SEARCH) for i in range(8)],
            *[entry(f"o{i}", "Other", f"Other {i}") for i in range(8)],
        ]
    )

    listed = pool.listing(max_per_artist=3, max_per_anchor_artist=6)

    assert sum(item.primary_artist == "椎名林檎" for item in listed) == 6
    assert sum(item.primary_artist == "Other" for item in listed) == 3


def test_listing_is_bounded_and_deterministic() -> None:
    pool = CatalogPool(entries=[entry(str(i), f"Artist {i}", f"Song {i}") for i in range(60)])

    first = pool.listing(max_entries=10)

    assert len(first) == 10
    assert first == pool.listing(max_entries=10)


def test_unavailable_lists_known_unplayable_tracks_only() -> None:
    pool = CatalogPool(
        outcomes=[
            CandidateOutcome(
                source=PoolSource.ARTIST_SEARCH,
                artist="椎名林檎",
                title="本能",
                status=AvailabilityStatus.UNPLAYABLE,
            ),
            CandidateOutcome(
                source=PoolSource.ARTIST_SEARCH,
                artist="A",
                title="Outage",
                status=AvailabilityStatus.PROVIDER_ERROR,
            ),
        ]
    )

    assert pool.unavailable() == [{"artist": "椎名林檎", "title": "本能"}]


@pytest.mark.parametrize(
    ("query", "credit", "expected"),
    [
        ("椎名林檎", "椎名林檎, TOWA TEI", True),
        ("久石让 宫崎骏", "久石譲", True),  # script variant
        ("Bill Evans jazz", "Bill Evans", True),
        ("late night jazz", "Late Night Jazz Band", False),  # query is not inside the name
        ("lynchpin", "Lyn", False),  # no partial-word match for Latin names
        ("deep house", "X", False),  # one-character names are never matched
    ],
)
def test_artist_named_in_query(query: str, credit: str, expected: bool) -> None:
    assert artist_named_in_query(query, credit) is expected


# --- Curator prompt ----------------------------------------------------------------------


class _PromptRecorder:
    def __init__(self, output: ProgramSkeleton) -> None:
        self.output = output
        self.prompt = ""

    async def structured(
        self, prompt: str, _output_type: type[object], **_kwargs: object
    ) -> object:
        self.prompt = prompt
        return self.output


def _skeleton() -> ProgramSkeleton:
    return ProgramSkeleton(
        thesis="fixture",
        estimated_duration_seconds=60,
        chapters=[
            ChapterPlan(
                index=0,
                narrative_role=NarrativeRole.BRIDGE,
                reason="fixture",
                novelty_distance=NoveltyDistance.CLOSE,
                narration_goal="fixture",
            )
        ],
    )


def _curate(pool: CatalogPool | None) -> str:
    recorder = _PromptRecorder(_skeleton())
    asyncio.run(
        CuratorService(recorder).curate(
            ResearchBundle(anchors=[], taste_hypotheses=[], evidence=[], candidates=[]),
            FastStartPlan(
                anchor_understanding=[],
                immediate_taste_hypotheses=[],
                next_candidates=[],
                first_narration=NarrationScript(text="start", intended_duration_seconds=5),
            ),
            desired_duration_seconds=60,
            catalog_pool=pool,
        )
    )
    return recorder.prompt


def test_curator_prompt_lists_available_and_unavailable_tracks() -> None:
    pool = CatalogPool(
        entries=[entry("1", "久石譲", "娜乌西卡安魂曲", PoolSource.LLM_CANDIDATE)],
        outcomes=[
            CandidateOutcome(
                source=PoolSource.ARTIST_SEARCH,
                artist="椎名林檎",
                title="本能",
                status=AvailabilityStatus.UNPLAYABLE,
            )
        ],
    )

    prompt = _curate(pool)

    assert "Available catalog tracks were verified playable" in prompt
    assert "娜乌西卡安魂曲" in prompt
    assert "Unavailable:" in prompt and "本能" in prompt
    assert "netease:1" not in prompt  # provider references stay out of the prompt


def test_curator_prompt_is_unchanged_without_a_pool_or_with_an_empty_pool() -> None:
    baseline = _curate(None)

    assert "Available catalog tracks" not in baseline
    assert _curate(CatalogPool()) == baseline


# --- assembly integration ----------------------------------------------------------------


class _PoolSkeletonLLM(RecordingAssemblyLLM):
    """Curator picks a pool track by its catalog artist and title."""

    async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
        if output_type is ProgramSkeleton:
            self.curator_prompts.append(prompt)
            return ProgramSkeleton(
                thesis="fixture",
                chapters=[
                    ChapterPlan(
                        index=0,
                        track=TrackProposal(
                            artist="Southbound FM", title="Afterimage Avenue", confidence=0.9
                        ),
                        narrative_role=NarrativeRole.BRIDGE,
                        reason="a verified pool track",
                        novelty_distance=NoveltyDistance.CLOSE,
                        narration_goal="connect to the pool track",
                    )
                ],
                estimated_duration_seconds=5 * 60,
            )
        return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]

    curator_prompts: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.curator_prompts = []


OPENING = ResolvedTrack(
    track_ref="mock:opening", canonical_artist="Mira Fields", canonical_title="Neon First Light"
)


def _prepare(assembly: object) -> object:
    return asyncio.run(
        assembly.prepare_progressive_session(  # type: ignore[attr-defined]
            LiveEpisodeAssemblyRequest(
                topic="Southbound FM", desired_duration_seconds=5 * 60, max_tracks=3
            ),
            opening_track=OPENING,
        )
    )


def test_pool_is_offered_to_the_curator_and_resolves_its_choice_without_a_new_search(
    tmp_path,
) -> None:
    llm = _PoolSkeletonLLM()
    assembly = service(tmp_path, llm)
    searches: list[str] = []
    provider = assembly.retrieval.registry.get("mock")
    original_search = provider.search

    async def recording_search(query: str, *, limit: int = 5):  # type: ignore[no-untyped-def]
        searches.append(query)
        return await original_search(query, limit=limit)

    provider.search = recording_search  # type: ignore[method-assign]
    assembly.catalog_pool_builder = CatalogPoolBuilder(assembly.retrieval)

    session = _prepare(assembly)

    prompt = llm.curator_prompts[0]
    assert "Available catalog tracks were verified playable" in prompt
    assert "Afterimage Avenue" in prompt
    assert "Neon First Light" not in prompt.split("Available:")[1]  # reserved opening excluded
    chosen = [c.resolved_track for c in session.chapters if c.resolved_track]  # type: ignore[attr-defined]
    assert [track.canonical_title for track in chosen][0] == "Afterimage Avenue"
    assert "Southbound FM Afterimage Avenue" not in searches  # pool hit, no resolution search


def test_without_a_builder_the_curator_prompt_and_resolution_are_unchanged(tmp_path) -> None:
    llm = _PoolSkeletonLLM()
    assembly = service(tmp_path, llm)
    assert assembly.catalog_pool_builder is None

    session = _prepare(assembly)

    assert "Available catalog tracks" not in llm.curator_prompts[0]
    assert session.chapters[0].resolved_track.canonical_title == "Afterimage Avenue"  # type: ignore[attr-defined]


def test_a_failing_pool_never_stops_generation(tmp_path) -> None:
    class ExplodingBuilder(CatalogPoolBuilder):
        async def build(self, **_kwargs: object) -> CatalogPool:  # type: ignore[override]
            raise RuntimeError("catalog exploded")

    llm = _PoolSkeletonLLM()
    assembly = service(tmp_path, llm)
    assembly.catalog_pool_builder = ExplodingBuilder(assembly.retrieval)

    session = _prepare(assembly)

    assert "Available catalog tracks" not in llm.curator_prompts[0]
    assert session.chapters[0].resolved_track.canonical_title == "Afterimage Avenue"  # type: ignore[attr-defined]


def test_a_curator_choice_outside_the_pool_still_goes_through_exact_resolution(tmp_path) -> None:
    llm = _PoolSkeletonLLM()
    assembly = service(tmp_path, llm)
    # No verification budget: only FastStart's own candidate can be in the pool, so the
    # Curator's pick (Afterimage Avenue) is outside it.
    assembly.catalog_pool_builder = CatalogPoolBuilder(
        assembly.retrieval, PoolBuildConfig(max_verifications=0)
    )

    session = _prepare(assembly)

    offered = llm.curator_prompts[0].split("Available:")[1]
    assert "Midnight Transfer" in offered
    assert "Afterimage Avenue" not in offered
    assert session.chapters[0].resolved_track.canonical_title == "Afterimage Avenue"  # type: ignore[attr-defined]


# --- configuration -----------------------------------------------------------------------


def test_catalog_pool_flag_defaults_off_and_is_validated(monkeypatch) -> None:
    monkeypatch.delenv("WAVECAST_CATALOG_POOL", raising=False)
    assert ProviderSettings.from_env().catalog_pool is False
    monkeypatch.setenv("WAVECAST_CATALOG_POOL", "on")
    assert ProviderSettings.from_env().catalog_pool is True
    monkeypatch.setenv("WAVECAST_CATALOG_POOL", "maybe")
    with pytest.raises(ProviderConfigurationError):
        ProviderSettings.from_env()


def test_factory_builds_the_pool_only_when_enabled(tmp_path) -> None:
    from wavecast.storage.assets import LocalObjectStorageProvider

    storage = LocalObjectStorageProvider(tmp_path / "audio")
    off = create_episode_assembly_service(ProviderSettings(), storage=storage)
    on = create_episode_assembly_service(ProviderSettings(catalog_pool=True), storage=storage)

    assert off.catalog_pool_builder is None
    assert on.catalog_pool_builder is not None


def test_the_locked_successor_is_not_offered_to_the_curator_again(tmp_path) -> None:
    llm = _PoolSkeletonLLM()
    assembly = service(tmp_path, llm)
    assembly.catalog_pool_builder = CatalogPoolBuilder(assembly.retrieval)
    successor = ResolvedTrack(
        track_ref="mock:bridge",
        canonical_artist="Signal Garden",
        canonical_title="Midnight Transfer",
    )

    asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="Southbound FM", desired_duration_seconds=5 * 60, max_tracks=3
            ),
            opening_track=OPENING,
            locked_successor=successor,
        )
    )

    offered = llm.curator_prompts[0].split("Available:")[1]
    assert "Midnight Transfer" not in offered
    assert "Afterimage Avenue" in offered
