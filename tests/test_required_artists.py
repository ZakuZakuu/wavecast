"""A request that names artists gets a programme that plays them, or does not claim to."""

import asyncio

from wavecast.assembly import (
    LiveEpisodeAssemblyRequest,
    _pool_artist_queries,
    _route_summary,
    create_episode_assembly_service,
)
from wavecast.catalog_pool import CatalogPoolBuilder
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
from wavecast.models.episode import CoverParams, EpisodeSeed
from wavecast.models.progressive import ProgressiveAssemblySession
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
from wavecast.orchestration.runtime import StagedProgressiveRuntimeAdapter
from wavecast.proposals import DeterministicMockProgramProposalGenerator, ProposalGenerationRequest
from wavecast.providers.config import ProviderSettings

from tests.test_catalog_pool_curator import _PromptRecorder, _skeleton
from tests.test_episode_assembly import RecordingAssemblyLLM, service

OPENING = ResolvedTrack(
    track_ref="mock:opening", canonical_artist="Mira Fields", canonical_title="Neon First Light"
)


def proposal(artist: str, title: str) -> TrackProposal:
    return TrackProposal(artist=artist, title=title, confidence=0.9)


# --- the Curator is told ------------------------------------------------------------------


def _curator_prompt(required: list[str]) -> str:
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
            required_artists=required,
        )
    )
    return recorder.prompt


def test_the_curator_is_told_which_artists_the_route_must_play() -> None:
    prompt = _curator_prompt(["Mogwai", "Explosions in the Sky"])

    assert "Required artists" in prompt
    assert '["Mogwai","Explosions in the Sky"]' in prompt
    assert "at least one track by each" in prompt
    assert "never another artist" in prompt


def test_the_curator_prompt_is_unchanged_when_no_artist_is_named() -> None:
    assert "Required artists" not in _curator_prompt([])
    assert _curator_prompt([]) == _curator_prompt(["", "  "])


# --- the pool searches for them -------------------------------------------------------------


def test_named_artists_lead_the_pool_searches_and_are_never_cut() -> None:
    proposals = [proposal(name, f"Song {i}") for i, name in enumerate(["A1", "A2", "A3", "A4"])]

    queries = _pool_artist_queries(proposals, ["Mogwai", "Explosions in the Sky"], "")

    assert queries[:2] == ["Mogwai", "Explosions in the Sky"]
    assert queries[2:] == ["A1", "A2", "A3"]  # the model's artists keep their own cap


def test_name_like_phrases_in_the_request_are_searched_even_if_the_model_forgot_them() -> None:
    queries = _pool_artist_queries(
        [proposal("Hammock", "Tape")], [], "从 Mogwai 到 Explosions in the Sky"
    )

    assert queries == ["Hammock", "Mogwai", "Explosions in the Sky"]


def test_an_artist_is_not_searched_twice_under_different_spelling() -> None:
    queries = _pool_artist_queries(
        [proposal("mogwai", "Auto Rock")], ["Mogwai"], "Mogwai live"
    )

    assert queries == ["Mogwai"]


def test_the_pool_behaves_as_before_when_no_artist_is_named() -> None:
    proposals = [proposal(name, f"S{i}") for i, name in enumerate(["久石譲", "久石让", "Bill Evans"])]

    assert _pool_artist_queries(proposals) == ["久石譲", "Bill Evans"]


# --- the plan is patched, and what stays unmet is recorded ---------------------------------


class _SouthboundOnlyLLM(RecordingAssemblyLLM):
    """A Curator that forgot the required artist and filled the route with one artist."""

    curator_prompts: list[str]

    def __init__(
        self, roles: tuple[NarrativeRole, NarrativeRole] = (NarrativeRole.BRIDGE, NarrativeRole.DISCOVERY)
    ) -> None:
        super().__init__()
        self.curator_prompts = []
        self.roles = roles

    async def structured(self, prompt: str, output_type: type[object], **kwargs: object) -> object:
        if output_type is ProgramSkeleton:
            self.curator_prompts.append(prompt)
            return ProgramSkeleton(
                thesis="fixture",
                chapters=[
                    ChapterPlan(
                        index=0,
                        track=proposal("Southbound FM", "Afterimage Avenue"),
                        narrative_role=self.roles[0],
                        reason="a Southbound FM song",
                        novelty_distance=NoveltyDistance.CLOSE,
                        narration_goal="talk about Southbound FM",
                    ),
                    ChapterPlan(
                        index=1,
                        track=proposal("Southbound FM", "Daybreak in Stereo"),
                        narrative_role=self.roles[1],
                        reason="another Southbound FM song",
                        novelty_distance=NoveltyDistance.CLOSE,
                        narration_goal="talk about Southbound FM again",
                    ),
                ],
                estimated_duration_seconds=5 * 60,
            )
        return await super().structured(prompt, output_type, **kwargs)  # type: ignore[arg-type]


def _prepare(assembly: object, required: list[str]) -> ProgressiveAssemblySession:
    return asyncio.run(
        assembly.prepare_progressive_session(  # type: ignore[attr-defined]
            LiveEpisodeAssemblyRequest(
                topic="Southbound FM and Signal Garden",
                desired_duration_seconds=5 * 60,
                max_tracks=3,
                required_artists=required,
            ),
            opening_track=OPENING,
        )
    )


def _played(session: ProgressiveAssemblySession) -> list[str]:
    return [
        f"{item.resolved_track.canonical_artist} - {item.resolved_track.canonical_title}"
        for item in session.chapters
        if item.resolved_track is not None
    ]


def test_an_artist_the_curator_left_out_is_found_in_the_catalog_and_played(tmp_path) -> None:
    llm = _SouthboundOnlyLLM()

    session = _prepare(service(tmp_path, llm), ["Signal Garden"])

    assert "Required artists" in llm.curator_prompts[0]
    assert _played(session) == [
        "Southbound FM - Afterimage Avenue",
        "Signal Garden - Midnight Transfer",
    ]
    assert session.required_artists == ["Signal Garden"]
    assert session.unfulfilled_artists == []


def test_the_first_future_chapter_may_be_given_up_because_the_opening_is_reserved(tmp_path) -> None:
    llm = _SouthboundOnlyLLM(roles=(NarrativeRole.DISCOVERY, NarrativeRole.BRIDGE))

    session = _prepare(service(tmp_path, llm), ["Signal Garden"])

    assert _played(session) == [
        "Signal Garden - Midnight Transfer",
        "Southbound FM - Daybreak in Stereo",
    ]


def test_a_patched_route_is_logged_with_counts_only(tmp_path, caplog) -> None:
    with caplog.at_level("INFO", logger="wavecast.assembly"):
        _prepare(service(tmp_path, _SouthboundOnlyLLM()), ["Signal Garden", "Nobody Known"])

    logged = [r.getMessage() for r in caplog.records if "required_artists_checked" in r.getMessage()]
    assert logged == ["required_artists_checked required=2 absent=2 patched=1 unpatched=1"]


def test_a_request_that_names_artists_uses_the_pool_even_when_the_flag_is_off(tmp_path) -> None:
    llm = _SouthboundOnlyLLM()
    assembly = service(tmp_path, llm)
    assert assembly.catalog_pool_builder is None

    _prepare(assembly, ["Signal Garden"])

    assert "Available catalog tracks were verified playable" in llm.curator_prompts[0]
    assert "Midnight Transfer" in llm.curator_prompts[0].split("Available:")[1]


def test_a_request_that_names_no_artist_still_needs_the_flag_for_the_pool(tmp_path) -> None:
    llm = _SouthboundOnlyLLM()

    _prepare(service(tmp_path, llm), [])

    assert "Available catalog tracks" not in llm.curator_prompts[0]


def test_the_swapped_chapter_talks_about_the_new_artist_not_the_old_one(tmp_path) -> None:
    session = _prepare(service(tmp_path, _SouthboundOnlyLLM()), ["Signal Garden"])

    swapped = session.chapters[1].chapter

    assert swapped.track is not None and swapped.track.artist == "Signal Garden"
    assert "Southbound" not in swapped.reason + swapped.narration_goal
    assert swapped.evidence_ids == []


def test_the_full_pool_path_also_searches_the_named_artist(tmp_path) -> None:
    llm = _SouthboundOnlyLLM()
    assembly = service(tmp_path, llm)
    assembly.catalog_pool_builder = CatalogPoolBuilder(assembly.retrieval)

    session = _prepare(assembly, ["Signal Garden"])

    offered = llm.curator_prompts[0].split("Available:")[1]
    assert "Midnight Transfer" in offered
    assert "Signal Garden - Midnight Transfer" in _played(session)
    assert session.unfulfilled_artists == []


def test_an_artist_with_nothing_playable_is_unfulfilled_and_the_route_is_untouched(
    tmp_path,
) -> None:
    session = _prepare(service(tmp_path, _SouthboundOnlyLLM()), ["Nobody Known"])

    assert _played(session) == [
        "Southbound FM - Afterimage Avenue",
        "Southbound FM - Daybreak in Stereo",
    ]
    assert session.unfulfilled_artists == ["Nobody Known"]


def test_an_artist_the_opening_already_plays_is_not_chased(tmp_path) -> None:
    session = _prepare(service(tmp_path, _SouthboundOnlyLLM()), ["Mira Fields"])

    assert _played(session) == [
        "Southbound FM - Afterimage Avenue",
        "Southbound FM - Daybreak in Stereo",
    ]
    assert session.unfulfilled_artists == []


def test_without_a_named_artist_the_route_is_exactly_what_the_curator_planned(tmp_path) -> None:
    session = _prepare(service(tmp_path, _SouthboundOnlyLLM()), [])

    assert _played(session) == [
        "Southbound FM - Afterimage Avenue",
        "Southbound FM - Daybreak in Stereo",
    ]
    assert session.required_artists == [] and session.unfulfilled_artists == []


def test_a_failing_coverage_search_never_stops_generation(tmp_path, monkeypatch) -> None:
    async def exploding(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("catalog exploded")

    monkeypatch.setattr(CatalogPoolBuilder, "build", exploding)

    session = _prepare(service(tmp_path, _SouthboundOnlyLLM()), ["Signal Garden"])

    assert _played(session) == [
        "Southbound FM - Afterimage Avenue",
        "Southbound FM - Daybreak in Stereo",
    ]
    assert session.unfulfilled_artists == ["Signal Garden"]


# --- the request reaches the pipeline and the host --------------------------------------------


def _started_episode(required: list[str], *, runtime_out: list | None = None):  # type: ignore[no-untyped-def,type-arg]
    seed = EpisodeSeed(
        id="required-artists",
        title="Route",
        topic="A deterministic staged route",
        short_description="x",
        estimated_duration_seconds=900,
        opening_track_ref="mock:opening",
        opening_track_title="Neon First Light",
        opening_track_artist="Mira Fields",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
        required_artists=required,
    )
    runtime = StagedProgressiveRuntimeAdapter(
        create_episode_assembly_service(ProviderSettings(mode="mock"))
    )
    if runtime_out is not None:
        runtime_out.append(runtime)
    orchestrator = EpisodeOrchestrator(InMemoryEpisodeRepository(), progressive_runtime=runtime)
    episode = orchestrator.start(seed)
    assert episode.required_artists == required
    return asyncio.run(
        orchestrator.ensure_buffer_async(episode.id, target_chapters=1, target_ahead_seconds=300)
    )


def test_the_seeds_artists_reach_the_session_and_what_is_not_played_is_off_limits_to_the_host() -> (
    None
):
    episode = _started_episode(["Signal Garden", "Nobody Known"])
    session = episode.progressive_session
    assert session is not None

    played, unplayed = _route_summary(session, episode)

    assert session.required_artists == ["Signal Garden", "Nobody Known"]
    assert session.unfulfilled_artists == ["Nobody Known"]
    assert any(label.startswith("Signal Garden") for label in played)
    assert "Nobody Known" in unplayed
    assert "Signal Garden" not in unplayed


def test_the_writer_is_told_which_requested_artists_the_programme_does_not_play(
    monkeypatch,
) -> None:
    from wavecast.intelligence.writer import WriterService

    seen: list[tuple[str, ...]] = []
    original = WriterService.write

    async def recording(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(tuple(kwargs.get("unfulfilled_artists", ())))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(WriterService, "write", recording)
    runtimes: list = []  # type: ignore[type-arg]
    episode = _started_episode(["Signal Garden", "Nobody Known"], runtime_out=runtimes)

    asyncio.run(runtimes[0].author_narration(episode, "chapter-2"))

    assert seen == [("Nobody Known",)]


def test_a_programme_that_names_no_artist_has_nothing_unfulfilled() -> None:
    episode = _started_episode([])
    session = episode.progressive_session
    assert session is not None

    assert session.required_artists == [] and session.unfulfilled_artists == []


def test_seeds_saved_before_the_field_existed_have_no_required_artists() -> None:
    generated = asyncio.run(
        DeterministicMockProgramProposalGenerator().generate(
            ProposalGenerationRequest(prompt="Persona 游戏音乐")
        )
    )[0]
    payload = generated.to_episode_seed().model_dump(mode="json")
    del payload["required_artists"]

    assert EpisodeSeed.model_validate(payload).required_artists == []


def test_a_proposal_carries_the_artists_the_model_listed_into_its_seed() -> None:
    from wavecast.proposals import ProgramProposal

    generated = asyncio.run(
        DeterministicMockProgramProposalGenerator().generate(
            ProposalGenerationRequest(prompt="从 Mogwai 到 Explosions in the Sky")
        )
    )[0]
    proposal_with_artists = ProgramProposal.model_validate(
        {**generated.model_dump(mode="json"), "required_artists": ["Mogwai", "Explosions in the Sky"]}
    )

    assert proposal_with_artists.to_episode_seed().required_artists == [
        "Mogwai",
        "Explosions in the Sky",
    ]
