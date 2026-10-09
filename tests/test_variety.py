"""The same request does not always start, or look, the same way (#202)."""

import asyncio

from wavecast.catalog_pool import CatalogPool, PoolEntry, PoolSource
from wavecast.intelligence.curation import _catalog_pool_context
from wavecast.proposals import (
    OpeningTrackCandidate,
    ProgramProposalDraft,
    ProposalGenerationRequest,
    _rotated,
)
from wavecast.providers.retrieval import VersionKind

from tests.test_program_proposals import _live_generator


def entry(ref: str, artist: str, source: PoolSource = PoolSource.KEYWORD_SEARCH) -> PoolEntry:
    return PoolEntry(
        track_ref=f"netease:{ref}",
        artist=artist,
        title=f"Song {ref}",
        primary_artist=artist,
        duration_seconds=200,
        version_kind=VersionKind.UNKNOWN,
        source=source,
    )


# --- rotating the opening candidates ----------------------------------------------------------


def test_without_a_seed_the_candidates_keep_their_order() -> None:
    assert _rotated([1, 2, 3, 4], "") == [1, 2, 3, 4]
    assert _rotated([1], "any") == [1]
    assert _rotated([], "any") == []


def test_a_rotation_keeps_the_cyclic_order_and_is_reproducible() -> None:
    items = ["a", "b", "c", "d"]

    first = _rotated(items, "seed-1")

    assert first == _rotated(items, "seed-1")
    assert sorted(first) == items
    start = items.index(first[0])
    assert first == items[start:] + items[:start]


def test_different_seeds_start_at_different_candidates() -> None:
    items = ["a", "b", "c", "d"]

    starts = {_rotated(items, f"proposal-{n}")[0] for n in range(60)}

    assert starts == set(items)


# --- the opening of a proposal ----------------------------------------------------------------


def _draft(*candidates: tuple[str, str]) -> ProgramProposalDraft:
    return ProgramProposalDraft(
        title="夜行",
        short_description="一段夜里的路线。",
        editorial_route=["起点", "转折", "收束"],
        opening_track_candidates=[OpeningTrackCandidate(artist=a, title=t) for a, t in candidates],
    )


MOCK_OPENINGS = (
    ("Mira Fields", "Neon First Light"),
    ("Signal Garden", "Midnight Transfer"),
    ("Southbound FM", "Daybreak in Stereo"),
)


def _opening_for(seed: str, draft: ProgramProposalDraft) -> str:
    generator, _llm = _live_generator(None)  # type: ignore[arg-type]
    resolved, _seconds, _profile = asyncio.run(generator._resolve_opening_track(draft, seed=seed))
    assert resolved is not None
    return resolved.canonical_title


def test_the_opening_is_reproducible_for_a_seed_and_varies_across_seeds() -> None:
    draft = _draft(*MOCK_OPENINGS)

    assert _opening_for("proposal-1", draft) == _opening_for("proposal-1", draft)
    openings = {_opening_for(f"proposal-{n}", draft) for n in range(40)}

    assert openings == {title for _artist, title in MOCK_OPENINGS}


def test_an_unplayable_candidate_is_skipped_whatever_the_rotation() -> None:
    draft = _draft(("Ghost Band", "Never Released"), *MOCK_OPENINGS[:2])

    openings = {_opening_for(f"proposal-{n}", draft) for n in range(40)}

    assert openings == {"Neon First Light", "Midnight Transfer"}


def test_proposals_generated_one_after_another_do_not_all_open_alike() -> None:
    from wavecast.proposals import ProgramProposalDraftBatch

    generator, llm = _live_generator(ProgramProposalDraftBatch(proposals=[_draft(*MOCK_OPENINGS)]))

    openings = {
        asyncio.run(generator.generate(ProposalGenerationRequest(prompt="夜里开车")))[0]
        .opening_track_title
        for _ in range(24)
    }

    assert len(openings) >= 2
    assert "not ranked" in llm.prompt  # the model is told the candidates are interchangeable


# --- the tracks the Curator sees first ---------------------------------------------------------


def _pool() -> CatalogPool:
    return CatalogPool(
        entries=[
            *(entry(f"l{n}", f"Llm {n}", PoolSource.LLM_CANDIDATE) for n in range(3)),
            *(entry(f"a{n}", "Anchor", PoolSource.ARTIST_SEARCH) for n in range(8)),
            *(entry(f"k{n}", f"Keyword {n}") for n in range(6)),
        ]
    )


def test_a_pool_listing_without_a_seed_is_unchanged() -> None:
    pool = _pool()

    assert [item.track_ref for item in pool.listing()] == [item.track_ref for item in pool.listing(seed="")]
    assert [item.track_ref for item in pool.listing()][:3] == ["netease:l0", "netease:l1", "netease:l2"]


def test_a_seeded_listing_is_reproducible_and_differs_between_seeds() -> None:
    pool = _pool()

    first = [item.track_ref for item in pool.listing(seed="programme-1")]

    assert first == [item.track_ref for item in pool.listing(seed="programme-1")]
    orders = {tuple(item.track_ref for item in pool.listing(seed=f"programme-{n}")) for n in range(20)}
    assert len(orders) > 5


def test_a_seeded_listing_keeps_tiers_caps_and_contents() -> None:
    pool = _pool()
    baseline = pool.listing()

    for n in range(20):
        listed = pool.listing(seed=f"programme-{n}")
        # trusted sources first, as before
        assert [item.source for item in listed][:3] == [PoolSource.LLM_CANDIDATE] * 3
        assert len([item for item in listed if item.primary_artist == "Anchor"]) == 6  # anchor cap
        assert len([item for item in listed if item.source is PoolSource.KEYWORD_SEARCH]) == len(
            [item for item in baseline if item.source is PoolSource.KEYWORD_SEARCH]
        )


def test_the_curator_is_shown_a_different_first_page_per_seed_and_told_the_order_means_nothing() -> None:
    pool = _pool()

    prompts = {_catalog_pool_context(pool, f"programme-{n}") for n in range(12)}

    assert len(prompts) > 3
    assert all("do not favour the first ones" in prompt for prompt in prompts)
    assert _catalog_pool_context(pool, "a") == _catalog_pool_context(pool, "a")
    assert _catalog_pool_context(None, "a") == ""


# --- the seed reaches the Curator --------------------------------------------------------------


def test_the_programme_id_seeds_the_curators_view_of_the_pool(tmp_path, monkeypatch) -> None:
    from wavecast.assembly import LiveEpisodeAssemblyRequest
    from wavecast.catalog_pool import CatalogPoolBuilder
    from wavecast.intelligence.curation import CuratorService
    from wavecast.intelligence.models import ResolvedTrack

    from tests.test_episode_assembly import service

    seen: list[str] = []
    original = CuratorService.curate

    async def recording(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs.get("variety_seed", "<missing>"))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(CuratorService, "curate", recording)
    assembly = service(tmp_path)
    assembly.catalog_pool_builder = CatalogPoolBuilder(assembly.retrieval)

    asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="Southbound FM",
                desired_duration_seconds=5 * 60,
                max_tracks=3,
                variety_seed="programme-77",
            ),
            opening_track=ResolvedTrack(
                track_ref="mock:opening", canonical_artist="Mira Fields", canonical_title="Neon First Light"
            ),
        )
    )

    assert seen and set(seen) == {"programme-77"}


def test_the_runtime_passes_the_episode_seed_id_as_the_variety_seed(monkeypatch) -> None:
    from wavecast.intelligence.curation import CuratorService

    from tests.test_required_artists import _started_episode

    seen: list[str] = []
    original = CuratorService.curate

    async def recording(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs.get("variety_seed", "<missing>"))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(CuratorService, "curate", recording)

    _started_episode([])

    assert seen and set(seen) == {"required-artists"}


def test_curate_uses_the_seed_when_it_lists_the_pool() -> None:
    from wavecast.intelligence.curation import CuratorService
    from wavecast.intelligence.models import FastStartPlan, NarrationScript, ResearchBundle

    from tests.test_catalog_pool_curator import _PromptRecorder, _skeleton

    def prompt_for(seed: str) -> str:
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
                catalog_pool=_pool(),
                variety_seed=seed,
            )
        )
        return recorder.prompt

    assert prompt_for("a") == prompt_for("a")
    assert len({prompt_for(f"programme-{n}") for n in range(8)}) > 2
