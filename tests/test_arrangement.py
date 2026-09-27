import pytest
from wavecast.arrangement import plan_episode_mix
from wavecast.models.episode import (
    MusicSegment,
    NarrationRole,
    NarrationSegment,
    PlayableEpisode,
    SegmentState,
)


def fixture_episode() -> PlayableEpisode:
    return PlayableEpisode(
        id="episode-phase6",
        segments=[
            MusicSegment(
                id="music-a", chapter_id="a", order=0, track_ref="track:a",
                state=SegmentState.AUDIO_READY, planned_duration_seconds=40,
                actual_duration_seconds=40, audio_source_url="/a.mp3", title="A", artist="A",
            ),
            NarrationSegment(
                id="voice-a", chapter_id="a", order=1,
                state=SegmentState.AUDIO_READY, planned_duration_seconds=8,
                actual_duration_seconds=8, audio_source_url="/voice-a.mp3", title="Voice A",
            ),
            MusicSegment(
                id="music-b", chapter_id="b", order=2, track_ref="track:b",
                state=SegmentState.AUDIO_READY, planned_duration_seconds=35,
                actual_duration_seconds=35, audio_source_url="/b.mp3", title="B", artist="B",
            ),
            NarrationSegment(
                id="outro", chapter_id="b", order=3,
                state=SegmentState.AUDIO_READY, planned_duration_seconds=7,
                actual_duration_seconds=7, audio_source_url="/outro.mp3", title="Outro",
            ),
        ],
    )


def test_planner_creates_voice_music_overlap_and_ducking() -> None:
    plan = plan_episode_mix(fixture_episode())
    music_a = next(clip for clip in plan.clips if clip.segment_id == "music-a")
    voice = next(clip for clip in plan.clips if clip.segment_id == "voice-a")
    music_b = next(clip for clip in plan.clips if clip.segment_id == "music-b")

    assert music_a.timeline_start_seconds < voice.timeline_start_seconds < music_a.timeline_end_seconds
    assert music_b.timeline_start_seconds < voice.timeline_end_seconds
    assert any(0 < point.gain <= 0.35 for point in music_a.gain_automation)
    assert music_a.timeline_end_seconds > music_b.timeline_start_seconds
    assert next(point for point in music_a.gain_automation if point.offset_seconds == 0).gain == 1
    assert next(point for point in music_b.gain_automation if point.offset_seconds == 9).gain == 0.35
    assert next(point for point in music_b.gain_automation if point.offset_seconds == 9.5).gain == 1


def test_planner_is_deterministic_and_bounds_all_clips() -> None:
    first = plan_episode_mix(fixture_episode()).model_dump(mode="json")
    second = plan_episode_mix(fixture_episode()).model_dump(mode="json")

    assert first == second
    plan = plan_episode_mix(fixture_episode())
    for clip in plan.clips:
        assert clip.timeline_start_seconds >= 0
        assert clip.timeline_end_seconds <= plan.duration_seconds
        assert clip.fade_in_seconds <= clip.playable_duration_seconds
        assert clip.fade_out_seconds <= clip.playable_duration_seconds


def test_narration_exposes_transport_safe_edge_fade_metadata() -> None:
    plan = plan_episode_mix(fixture_episode())
    voice = next(clip for clip in plan.clips if clip.segment_id == "voice-a")

    assert voice.fade_in_seconds == pytest.approx(0.08)
    assert voice.fade_out_seconds == pytest.approx(0.08)


def test_final_outro_overlays_last_music_tail() -> None:
    plan = plan_episode_mix(fixture_episode())
    last_music = next(clip for clip in plan.clips if clip.segment_id == "music-b")
    outro = next(clip for clip in plan.clips if clip.segment_id == "outro")

    assert outro.timeline_start_seconds < last_music.timeline_end_seconds



def _music(identifier: str, order: int, duration: int) -> MusicSegment:
    return MusicSegment(
        id=identifier,
        chapter_id=identifier,
        order=order,
        state=SegmentState.AUDIO_READY,
        planned_duration_seconds=duration,
        actual_duration_seconds=duration,
        track_ref=f"track:{identifier}",
        audio_source_url=f"/{identifier}.mp3",
        title=identifier,
        artist=identifier,
    )


def _voice(
    identifier: str,
    order: int,
    duration: int,
    role: NarrationRole,
) -> NarrationSegment:
    return NarrationSegment(
        id=identifier,
        chapter_id=identifier,
        order=order,
        state=SegmentState.AUDIO_READY,
        planned_duration_seconds=duration,
        actual_duration_seconds=duration,
        audio_source_url=f"/{identifier}.mp3",
        title=identifier,
        narration_role=role,
    )


def _episode(*segments: MusicSegment | NarrationSegment) -> PlayableEpisode:
    return PlayableEpisode(id="role-aware", segments=list(segments))


def test_track_intro_anchors_incoming_music_to_voice_start() -> None:
    plan = plan_episode_mix(_episode(_music("a", 0, 40), _voice("intro", 1, 8, NarrationRole.TRACK_INTRO), _music("b", 2, 35)))
    voice = next(clip for clip in plan.clips if clip.segment_id == "intro")
    incoming = next(clip for clip in plan.clips if clip.segment_id == "b")

    assert incoming.timeline_start_seconds >= voice.timeline_start_seconds
    assert incoming.timeline_start_seconds == voice.timeline_start_seconds
    assert incoming.timeline_start_seconds < voice.timeline_end_seconds


def test_transition_places_incoming_after_transition_start() -> None:
    plan = plan_episode_mix(_episode(_music("a", 0, 40), _voice("bridge", 1, 8, NarrationRole.TRANSITION), _music("b", 2, 35)))
    transition = next(clip for clip in plan.clips if clip.segment_id == "bridge")
    incoming = next(clip for clip in plan.clips if clip.segment_id == "b")

    assert transition.timeline_start_seconds < next(
        clip for clip in plan.clips if clip.segment_id == "a"
    ).timeline_end_seconds
    assert transition.timeline_start_seconds < incoming.timeline_start_seconds
    assert incoming.timeline_start_seconds <= transition.timeline_end_seconds


def test_outro_has_no_phantom_incoming_music() -> None:
    plan = plan_episode_mix(_episode(_music("a", 0, 40), _voice("outro", 1, 7, NarrationRole.OUTRO)))
    music = next(clip for clip in plan.clips if clip.segment_id == "a")
    outro = next(clip for clip in plan.clips if clip.segment_id == "outro")

    assert outro.timeline_start_seconds < music.timeline_end_seconds
    assert plan.duration_seconds >= outro.timeline_end_seconds
    assert len([clip for clip in plan.clips if clip.lane == "MUSIC"]) == 1


def test_track_intro_wins_after_multiple_narration_blocks() -> None:
    plan = plan_episode_mix(
        _episode(
            _music("a", 0, 40),
            _voice("transition", 1, 6, NarrationRole.TRANSITION),
            _voice("general", 2, 4, NarrationRole.GENERAL),
            _voice("track-intro", 3, 8, NarrationRole.TRACK_INTRO),
            _music("b", 4, 35),
        )
    )
    voices = [
        clip for clip in plan.clips if clip.lane == "VOICE"
    ]
    track_intro = next(clip for clip in voices if clip.segment_id == "track-intro")
    incoming = next(clip for clip in plan.clips if clip.segment_id == "b")

    assert all(left.timeline_end_seconds <= right.timeline_start_seconds for left, right in zip(voices, voices[1:]))
    assert incoming.timeline_start_seconds == track_intro.timeline_start_seconds
    assert incoming.timeline_start_seconds > next(
        clip for clip in voices if clip.segment_id == "transition"
    ).timeline_start_seconds


def test_prefix_segment_starts_are_stable_when_future_music_is_ready() -> None:
    prefix = plan_episode_mix(
        _episode(_music("a", 0, 40), _voice("intro", 1, 8, NarrationRole.TRACK_INTRO))
    )
    full = plan_episode_mix(
        _episode(_music("a", 0, 40), _voice("intro", 1, 8, NarrationRole.TRACK_INTRO), _music("b", 2, 35))
    )

    assert full.segment_starts["a"] == prefix.segment_starts["a"]
    assert full.segment_starts["intro"] == prefix.segment_starts["intro"]


def test_direct_music_crossfade_remains_bounded() -> None:
    plan = plan_episode_mix(_episode(_music("a", 0, 40), _music("b", 1, 35)))
    assert plan.segment_starts["b"] == 37


@pytest.mark.parametrize("bridge_role", [NarrationRole.TRANSITION, NarrationRole.INTRO])
def test_semantic_bridge_survives_trailing_general(
    bridge_role: NarrationRole,
) -> None:
    plan = plan_episode_mix(
        _episode(
            _music("a", 0, 40),
            _voice("bridge", 1, 6, bridge_role),
            _voice("general", 2, 4, NarrationRole.GENERAL),
            _music("b", 3, 35),
        )
    )
    voices = [clip for clip in plan.clips if clip.lane == "VOICE"]
    bridge = next(clip for clip in voices if clip.segment_id == "bridge")
    general = next(clip for clip in voices if clip.segment_id == "general")
    incoming = next(clip for clip in plan.clips if clip.segment_id == "b")

    assert bridge.timeline_end_seconds <= general.timeline_start_seconds
    assert incoming.timeline_start_seconds >= general.timeline_start_seconds
    assert incoming.timeline_start_seconds <= general.timeline_end_seconds
    assert incoming.timeline_start_seconds > bridge.timeline_start_seconds


def test_music_gain_automation_stays_bounded_for_role_aware_gap() -> None:
    plan = plan_episode_mix(
        _episode(
            _music("a", 0, 40),
            _voice("bridge", 1, 6, NarrationRole.TRANSITION),
            _voice("general", 2, 4, NarrationRole.GENERAL),
            _music("b", 3, 35),
        )
    )
    for clip in plan.clips:
        assert all(0 <= point.gain <= 1 for point in clip.gain_automation)
