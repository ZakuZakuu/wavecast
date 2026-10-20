"""Real-length routes and bounded continuation, using only offline providers."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from wavecast.assembly import LiveEpisodeAssemblyRequest
from wavecast.intelligence.models import (
    ChapterPlan,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    ResolvedTrack,
    TrackProposal,
)
from wavecast.models.episode import (
    CoverParams,
    EpisodeSeed,
    EpisodeState,
    LiveEpisode,
    MusicSegment,
)
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
from wavecast.orchestration.runtime import StagedProgressiveRuntimeAdapter
from wavecast.presentation import HostMode, PresentationIntent
from wavecast.providers.contracts import TrackMetadata
from wavecast.providers.errors import ProviderSchemaValidationError
from wavecast.providers.fakes import MockMusicProvider
from wavecast.stations import StationId

from tests.test_episode_assembly import RecordingAssemblyLLM, service


class DurationLLM(RecordingAssemblyLLM):
    def __init__(self, tracks, *, repair="extend"):
        super().__init__()
        self.tracks = tracks
        self.repair = repair
        self.route_prompts = []

    def chapter(self, track, index):
        return ChapterPlan(
            index=index,
            track=TrackProposal(artist=track.artist, title=track.title, confidence=0.9),
            narrative_role=NarrativeRole.BRIDGE,
            reason="A supported next step in this musical theme",
            novelty_distance=NoveltyDistance.CLOSE,
            narration_goal="Explain this step without changing the theme",
        )

    async def structured(self, prompt, output_type, **kwargs):
        if output_type is ProgramSkeleton:
            self.route_prompts.append(prompt)
            if len(self.route_prompts) == 1:
                chapters = [self.chapter(t, i) for i, t in enumerate(self.tracks[1:4])]
            else:
                if self.repair == "fail":
                    raise ProviderSchemaValidationError("offline invalid continuation")
                committed = json.loads(prompt.split("Committed: ", 1)[1].split("\n", 1)[0])
                chapters = [ChapterPlan.model_validate(c) for c in committed]
                if self.repair == "extend":
                    chapters += [self.chapter(t, len(committed) + i)
                                 for i, t in enumerate(self.tracks[4:])]
                elif self.repair == "missing":
                    missing = self.tracks[0].model_copy(update={"title": "Unavailable recording"})
                    chapters.append(self.chapter(missing, len(committed)))
            return ProgramSkeleton(thesis="A coherent route", chapters=chapters,
                                   estimated_duration_seconds=2100)
        return await super().structured(prompt, output_type, **kwargs)


def setup_route(tmp_path, *, repair="extend", lengths=None):
    lengths = lengths or [254, 145, 173, 119, 400, 400, 400, 400, 400]
    tracks = [TrackMetadata(track_ref=f"mock:duration-{i}", artist=f"Duration Artist {i}",
                            title=f"Recording {i}", duration_seconds=seconds, playable=True)
              for i, seconds in enumerate(lengths)]
    music = MockMusicProvider()
    music._tracks.update({t.track_ref: t for t in tracks})
    llm = DurationLLM(tracks, repair=repair)
    assembly = service(tmp_path, llm, music)
    assembly.duration_scaling = True
    opening = ResolvedTrack(track_ref=tracks[0].track_ref, canonical_artist=tracks[0].artist,
                            canonical_title=tracks[0].title, duration_seconds=tracks[0].duration_seconds)
    return assembly, llm, tracks, opening


@pytest.mark.parametrize("locked", [False, True], ids=["full-version", "progressive-prefix"])
def test_short_route_is_extended_once_toward_the_actual_music_budget(tmp_path, locked):
    assembly, llm, tracks, opening = setup_route(tmp_path)
    locked_track = ResolvedTrack(track_ref=tracks[1].track_ref, canonical_artist=tracks[1].artist,
                                canonical_title=tracks[1].title, duration_seconds=145) if locked else None
    emergency = AsyncMock(wraps=assembly._extend_underfilled_locked_route_from_catalog)
    assembly._extend_underfilled_locked_route_from_catalog = emergency
    session = asyncio.run(assembly.prepare_progressive_session(
        LiveEpisodeAssemblyRequest(topic="A specific musical direction", desired_duration_seconds=2100,
                                   max_tracks=10, max_chapters=15),
        opening_track=opening, locked_successor=locked_track,
    ))
    route = [opening, *[c.resolved_track for c in session.chapters if c.resolved_track]]
    assert [t.track_ref for t in route[:4]] == [t.track_ref for t in tracks[:4]]
    # The existing 80% trigger must not become the stopping target for the repair.
    assert sum(t.duration_seconds or 0 for t in route) >= 1800
    assert len({t.track_ref for t in route}) == len(route)
    assert len(llm.route_prompts) == 2
    assert "Confirmed route music: 691 seconds" in llm.route_prompts[1]
    assert "Remaining music:" in llm.route_prompts[1]
    assert not any(d.code == "duration_shortfall" for d in session.diagnostics)
    if not locked:
        emergency.assert_not_awaited()


@pytest.mark.parametrize("repair", ["empty", "fail"])
def test_an_exhausted_repair_keeps_the_short_playable_route_without_retrying(tmp_path, repair):
    assembly, llm, _, opening = setup_route(tmp_path, repair=repair)
    emergency = AsyncMock()
    assembly._extend_underfilled_locked_route_from_catalog = emergency
    session = asyncio.run(assembly.prepare_progressive_session(
        LiveEpisodeAssemblyRequest(topic="A specific musical direction", desired_duration_seconds=2100,
                                   max_tracks=10, max_chapters=15), opening_track=opening,
    ))
    assert len(llm.route_prompts) == 2
    assert sum(c.resolved_track is not None for c in session.chapters) == 3
    diagnostic = next(d for d in session.diagnostics if d.code == "duration_shortfall")
    assert "music_seconds=691" in diagnostic.detail
    assert "bounded_continuation_exhausted" in diagnostic.detail
    emergency.assert_not_awaited()


def test_long_recordings_do_not_request_more_songs(tmp_path):
    assembly, llm, _, opening = setup_route(tmp_path, lengths=[500] * 9)
    session = asyncio.run(assembly.prepare_progressive_session(
        LiveEpisodeAssemblyRequest(topic="Long musical works", desired_duration_seconds=2100,
                                   max_tracks=10, max_chapters=15), opening_track=opening,
    ))
    assert len(llm.route_prompts) == 1
    assert not any(d.code == "duration_shortfall" for d in session.diagnostics)


def test_full_version_does_not_replace_an_unavailable_addition_with_arbitrary_catalog_music(tmp_path):
    assembly, llm, _, opening = setup_route(tmp_path, repair="missing")
    replacement = AsyncMock(side_effect=AssertionError("no unselected catalog fill"))
    assembly._resolve_catalog_replacement = replacement
    session = asyncio.run(assembly.prepare_progressive_session(
        LiveEpisodeAssemblyRequest(topic="A particular musical facet", desired_duration_seconds=2100,
                                   max_tracks=10, max_chapters=15), opening_track=opening,
    ))
    assert len(llm.route_prompts) == 2
    assert sum(c.resolved_track is not None for c in session.chapters) == 3
    replacement.assert_not_awaited()


def test_a_finite_work_ends_with_its_confirmed_versions_without_extra_curation(tmp_path):
    assembly, llm, tracks, opening = setup_route(tmp_path)
    music = assembly.retrieval.registry.get("mock")
    for i in range(1, 4):
        tracks[i] = tracks[i].model_copy(update={
            "title": "Recording 0", "artist": ["Mira Fields", "Signal Garden", "Southbound FM"][i - 1],
        })
        music._tracks[tracks[i].track_ref] = tracks[i]
    session = asyncio.run(assembly.prepare_progressive_session(
        LiveEpisodeAssemblyRequest(topic="《Recording 0》的不同版本", station=StationId.LINEAGE,
                                   desired_duration_seconds=2100,
                                   max_tracks=10, max_chapters=15), opening_track=opening,
    ))
    assert len(llm.route_prompts) == 1
    assert all(c.resolved_track.canonical_title == "Recording 0"
               for c in session.chapters if c.resolved_track)
    assert "limited_work" in next(d.detail for d in session.diagnostics
                                  if d.code == "duration_shortfall")


def test_full_materialization_extends_before_writing_a_final_ending(tmp_path):
    assembly, llm, tracks, _ = setup_route(tmp_path)
    orchestrator = EpisodeOrchestrator(InMemoryEpisodeRepository(),
                                      progressive_runtime=StagedProgressiveRuntimeAdapter(assembly))
    seed = EpisodeSeed(
        id="duration-recovery", title="A musical direction", topic="A specific musical direction",
        short_description="A coherent route", estimated_duration_seconds=2100,
        opening_track_ref=tracks[0].track_ref, opening_track_artist=tracks[0].artist,
        opening_track_title=tracks[0].title, opening_track_duration_seconds=254,
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
        presentation_intent=PresentationIntent(host_mode=HostMode.NONE),
    )
    episode = orchestrator.start(seed)
    result = asyncio.run(orchestrator.materialize_all_async(episode.id))
    assert result.state is EpisodeState.MATERIALIZED
    assert result.timeline_duration_seconds >= 1800
    assert len(llm.route_prompts) == 2
    assert result.duration_notice is None
    assert sum(isinstance(s, MusicSegment) for s in result.timeline_segments) > 4


@pytest.mark.parametrize("state,seconds,notice", [
    (EpisodeState.STREAMING, 825, False),
    (EpisodeState.MATERIALIZING, 825, False),
    (EpisodeState.MATERIALIZED, 825, True),
    (EpisodeState.PUBLISHED, 825, True),
    (EpisodeState.MATERIALIZED, 1680, False),
    (EpisodeState.MATERIALIZED, 2100, False),
])
def test_actual_duration_notice_is_final_and_survives_state_round_trip(state, seconds, notice):
    episode = LiveEpisode(seed_id="seed", state=state, program_estimated_duration_seconds=2100,
                          segments=[MusicSegment(id="music", chapter_id="chapter-1", order=0,
                                                 track_ref="mock:music", title="Recording",
                                                 planned_duration_seconds=seconds)])
    payload = episode.model_dump(mode="json")
    assert (payload["duration_notice"] is not None) is notice
    if notice:
        assert payload["duration_notice"] == {"target_seconds": 2100, "actual_seconds": seconds}
    restored = LiveEpisode.model_validate(payload)
    assert restored.duration_notice == episode.duration_notice
