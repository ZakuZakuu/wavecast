import asyncio

import pytest
from wavecast.intelligence.models import OutputLanguage, RadioScript
from wavecast.intelligence.writer import WriterService
from wavecast.presentation import HostMode
from wavecast.proposals import (
    DeterministicMockProgramProposalGenerator,
    ProposalGenerationRequest,
)
from wavecast.stations import STATION_PROFILES, StationId, resolve_presentation_intent

from tests.test_intelligence_services import StructuredFixture, skeleton


def test_every_station_has_a_profile() -> None:
    assert set(STATION_PROFILES) == set(StationId)


@pytest.mark.parametrize(
    ("station", "expected"),
    [
        (StationId.CASUAL, HostMode.LIGHT),
        (StationId.CRATE, HostMode.LIGHT),
        (StationId.PORTRAIT, HostMode.FULL),
        (StationId.LINEAGE, HostMode.FULL),
        (StationId.NIGHT, HostMode.NONE),
        (None, HostMode.LIGHT),
    ],
)
def test_the_station_sets_the_default_hosting(station: StationId | None, expected: HostMode) -> None:
    assert resolve_presentation_intent("随便放点好听的", station).host_mode is expected


def test_explicit_wording_beats_the_station_default() -> None:
    assert resolve_presentation_intent("多讲一点", StationId.NIGHT).host_mode is HostMode.FULL
    assert resolve_presentation_intent("只听歌", StationId.LINEAGE).host_mode is HostMode.NONE


def test_the_station_travels_from_request_to_proposal_to_seed() -> None:
    request = ProposalGenerationRequest(prompt="睡前听的安静音乐", station=StationId.NIGHT)

    proposal = asyncio.run(DeterministicMockProgramProposalGenerator().generate(request))[0]

    assert proposal.station is StationId.NIGHT
    assert proposal.presentation_intent.host_mode is HostMode.NONE
    seed = proposal.to_episode_seed()
    assert seed.station is StationId.NIGHT
    assert seed.presentation_intent.host_mode is HostMode.NONE


def test_the_station_reaches_the_live_episode_and_the_writer_prompt() -> None:
    from wavecast.models.episode import CoverParams, EpisodeSeed
    from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository

    seed = EpisodeSeed(
        id="station-seed",
        title="Station",
        topic="x",
        short_description="x",
        estimated_duration_seconds=600,
        opening_track_ref="mock:opening",
        opening_track_title="Opening",
        opening_track_artist="Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
        station=StationId.LINEAGE,
    )
    episode = EpisodeOrchestrator(InMemoryEpisodeRepository()).start(seed)
    assert episode.station is StationId.LINEAGE

    fixture = StructuredFixture(RadioScript(blocks=[]))
    chapter = skeleton().chapters[0].model_copy(update={"evidence_ids": []})
    asyncio.run(
        WriterService(fixture).write(
            chapter, [], station=episode.station, output_language=OutputLanguage.ZH_CN
        )
    )
    assert "Station: 来龙去脉" in fixture.prompts[0]

    other = StructuredFixture(RadioScript(blocks=[]))
    asyncio.run(WriterService(other).write(chapter, []))
    assert "Station:" not in other.prompts[0]


def test_the_station_is_carried_into_the_progressive_session() -> None:
    from wavecast.assembly import create_episode_assembly_service
    from wavecast.models.episode import CoverParams, EpisodeSeed
    from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
    from wavecast.orchestration.runtime import StagedProgressiveRuntimeAdapter
    from wavecast.providers.config import ProviderSettings

    seed = EpisodeSeed(
        id="station-session",
        title="Station",
        topic="A deterministic staged route",
        short_description="x",
        estimated_duration_seconds=900,
        opening_track_ref="mock:opening",
        opening_track_title="Opening Track",
        opening_track_artist="Opening Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
        station=StationId.CRATE,
    )
    orchestrator = EpisodeOrchestrator(
        InMemoryEpisodeRepository(),
        progressive_runtime=StagedProgressiveRuntimeAdapter(
            create_episode_assembly_service(ProviderSettings(mode="mock"))
        ),
    )
    episode = orchestrator.start(seed)

    buffered = asyncio.run(
        orchestrator.ensure_buffer_async(episode.id, target_chapters=1, target_ahead_seconds=300)
    )

    assert buffered.progressive_session is not None
    assert buffered.progressive_session.station is StationId.CRATE


def test_idents_are_short_spoken_chinese_with_no_digits() -> None:
    from wavecast.stations import STATION_IDENTS

    assert set(STATION_IDENTS) == set(StationId) - {StationId.NIGHT}
    for forms in STATION_IDENTS.values():
        assert len(forms) >= 3
        for form in forms:
            assert len(form) <= 20
            assert not any(char.isdigit() for char in form)


def test_ident_choice_is_deterministic_and_varies_with_the_seed() -> None:
    from wavecast.stations import pick_ident

    assert pick_ident(StationId.CASUAL, "a") == pick_ident(StationId.CASUAL, "a")
    assert len({pick_ident(StationId.CASUAL, f"seed-{n}") for n in range(40)}) == 3
    assert pick_ident(StationId.NIGHT, "a") is None
    assert pick_ident(None, "a") is None
