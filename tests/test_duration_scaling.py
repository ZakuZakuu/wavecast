import asyncio

import pytest
from wavecast.assembly import (
    LiveEpisodeAssemblyRequest,
    create_episode_assembly_service,
    route_limits_for_duration,
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
)
from wavecast.models.episode import CoverParams, EpisodeSeed
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
from wavecast.orchestration.runtime import StagedProgressiveRuntimeAdapter
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderConfigurationError


def test_unscaled_limits_stay_fixed_whatever_the_request() -> None:
    for seconds in (300, 1320, 2520, 4320):
        assert route_limits_for_duration(seconds, scaled=False) == (5, 8)


@pytest.mark.parametrize(
    ("seconds", "tracks", "chapters"),
    [
        (300, 3, 6),  # never fewer than three tracks
        (1320, 6, 9),  # SHORT, 22 min
        (2160, 10, 15),  # AUTO, 36 min
        (2520, 11, 16),  # STANDARD, 42 min
        (4320, 14, 21),  # DEEP, 72 min is capped
    ],
)
def test_scaled_limits_follow_the_requested_duration(
    seconds: int, tracks: int, chapters: int
) -> None:
    assert route_limits_for_duration(seconds, scaled=True) == (tracks, chapters)


def test_scaled_limits_stay_inside_the_schema_ceilings() -> None:
    for seconds in range(60, 20_000, 137):
        tracks, chapters = route_limits_for_duration(seconds, scaled=True)
        assert 3 <= tracks <= 14
        assert tracks < chapters <= 32
        LiveEpisodeAssemblyRequest(topic="x", desired_duration_seconds=seconds, max_tracks=tracks, max_chapters=chapters)


def test_scaled_limits_never_shrink_a_longer_request() -> None:
    previous = (0, 0)
    for seconds in range(300, 6000, 60):
        current = route_limits_for_duration(seconds, scaled=True)
        assert current[0] >= previous[0]
        previous = current


class _Prompt:
    def __init__(self) -> None:
        self.prompt = ""

    async def structured(self, prompt: str, _type: type[object], **_kwargs: object) -> object:
        self.prompt = prompt
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


def _curator_prompt(max_tracks: int, seconds: int) -> str:
    llm = _Prompt()
    asyncio.run(
        CuratorService(llm).curate(
            ResearchBundle(anchors=[], taste_hypotheses=[], evidence=[], candidates=[]),
            FastStartPlan(
                anchor_understanding=[],
                immediate_taste_hypotheses=[],
                next_candidates=[],
                first_narration=NarrationScript(text="start", intended_duration_seconds=5),
            ),
            desired_duration_seconds=seconds,
            max_tracks=max_tracks,
        )
    )
    return llm.prompt


def test_curator_prompt_is_unchanged_for_the_default_five_track_route() -> None:
    prompt = _curator_prompt(5, 2520)

    assert "prefer a 3-5 track-bearing listening arc" in prompt
    assert "The listener asked for about" not in prompt


def test_curator_is_asked_to_fill_a_long_programme_when_the_limit_is_raised() -> None:
    prompt = _curator_prompt(11, 2520)

    assert "prefer a 3-11 track-bearing listening arc" in prompt
    assert "about 42 minutes" in prompt
    assert "up to 11 track-bearing chapters" in prompt
    assert "not fewer than 8" in prompt


def _seed(minutes: int) -> EpisodeSeed:
    return EpisodeSeed(
        id=f"scaling-{minutes}",
        title="Scaling",
        topic="A deterministic staged route",
        short_description="test",
        estimated_duration_seconds=minutes * 60,
        opening_track_ref="mock:opening",
        opening_track_title="Opening Track",
        opening_track_artist="Opening Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
    )


@pytest.mark.parametrize(("scaling", "expected_tracks"), [(False, 5), (True, 11)])
def test_the_runtime_sizes_the_persisted_route_from_the_request(
    scaling: bool, expected_tracks: int
) -> None:
    assembly = create_episode_assembly_service(
        ProviderSettings(mode="mock", duration_scaling=scaling)
    )
    orchestrator = EpisodeOrchestrator(
        InMemoryEpisodeRepository(), progressive_runtime=StagedProgressiveRuntimeAdapter(assembly)
    )
    episode = orchestrator.start(_seed(42))

    buffered = asyncio.run(
        orchestrator.ensure_buffer_async(episode.id, target_chapters=1, target_ahead_seconds=300)
    )

    assert buffered.progressive_session is not None
    assert buffered.progressive_session.max_tracks == expected_tracks


def test_duration_scaling_flag_defaults_off_and_is_validated(monkeypatch) -> None:
    monkeypatch.delenv("WAVECAST_DURATION_SCALING", raising=False)
    assert ProviderSettings.from_env().duration_scaling is False
    monkeypatch.setenv("WAVECAST_DURATION_SCALING", "on")
    assert ProviderSettings.from_env().duration_scaling is True
    monkeypatch.setenv("WAVECAST_DURATION_SCALING", "sometimes")
    with pytest.raises(ProviderConfigurationError):
        ProviderSettings.from_env()
