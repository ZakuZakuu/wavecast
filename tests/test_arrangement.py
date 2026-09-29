import pytest
from wavecast.arrangement import plan_episode_mix
from wavecast.audio_timing import (
    TimingInterval,
    TrackSection,
    TrackSectionKind,
    TrackTimingProfile,
)
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
    assert music_a.timeline_end_seconds == music_b.timeline_start_seconds
    assert next(point for point in music_a.gain_automation if point.offset_seconds == 0).gain == 1
    assert next(point for point in music_a.gain_automation if point.offset_seconds == 36).gain == pytest.approx(0.30)
    assert next(point for point in music_a.gain_automation if point.offset_seconds == 40).gain == 0
    assert next(point for point in music_b.gain_automation if point.offset_seconds == 4).gain == pytest.approx(0.30)
    assert next(point for point in music_b.gain_automation if point.offset_seconds == 5.5).gain == 1


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

    assert incoming.timeline_start_seconds > voice.timeline_start_seconds
    assert incoming.timeline_start_seconds == next(
        clip for clip in plan.clips if clip.segment_id == "a"
    ).timeline_end_seconds
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
    assert track_intro.timeline_start_seconds < incoming.timeline_start_seconds
    assert incoming.timeline_start_seconds < track_intro.timeline_end_seconds
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
    assert plan.segment_starts["b"] == 30
    a = next(clip for clip in plan.clips if clip.segment_id == "a")
    b = next(clip for clip in plan.clips if clip.segment_id == "b")
    assert next(point for point in a.gain_automation if point.offset_seconds == 30).gain == 1
    assert next(point for point in a.gain_automation if point.offset_seconds == 40).gain == 0
    assert next(point for point in b.gain_automation if point.offset_seconds == 0).gain == 0
    assert next(point for point in b.gain_automation if point.offset_seconds == 10).gain == 1


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
    assert incoming.timeline_start_seconds > next(
        clip for clip in plan.clips if clip.segment_id == "a"
    ).timeline_end_seconds
    assert incoming.timeline_start_seconds < general.timeline_end_seconds
    assert incoming.timeline_start_seconds > bridge.timeline_start_seconds


def test_narrated_bridge_separates_duck_fade_out_and_incoming_fade() -> None:
    plan = plan_episode_mix(
        _episode(
            _music("a", 0, 40),
            _voice("bridge", 1, 8, NarrationRole.TRANSITION),
            _music("b", 2, 35),
        )
    )
    outgoing = next(clip for clip in plan.clips if clip.segment_id == "a")
    voice = next(clip for clip in plan.clips if clip.segment_id == "bridge")
    incoming = next(clip for clip in plan.clips if clip.segment_id == "b")

    assert voice.timeline_start_seconds == 36
    assert incoming.timeline_start_seconds == outgoing.timeline_end_seconds == 40
    assert next(
        point for point in outgoing.gain_automation if point.offset_seconds == 36
    ).gain == pytest.approx(0.30)
    assert next(
        point for point in outgoing.gain_automation if point.offset_seconds == 40
    ).gain == 0
    assert next(
        point for point in incoming.gain_automation if point.offset_seconds == 0
    ).gain == 0
    assert next(
        point for point in incoming.gain_automation if point.offset_seconds == 4
    ).gain == pytest.approx(0.30)
    assert next(
        point for point in incoming.gain_automation if point.offset_seconds == 5.5
    ).gain == 1


def test_voice_without_track_handoff_uses_ducking_not_bridge_fade() -> None:
    plan = plan_episode_mix(
        _episode(
            _music("a", 0, 40),
            _voice("overlay", 1, 8, NarrationRole.GENERAL),
        )
    )
    music = next(clip for clip in plan.clips if clip.segment_id == "a")
    voice = next(clip for clip in plan.clips if clip.segment_id == "overlay")

    assert voice.timeline_start_seconds == 36
    assert next(
        point for point in music.gain_automation if point.offset_seconds == 36
    ).gain == pytest.approx(0.30)
    assert next(
        point for point in music.gain_automation if point.offset_seconds == 40
    ).gain == pytest.approx(0.30)


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


def _timing_profile(
    *,
    duration: int,
    first_vocal_start: float,
    last_vocal_end: float,
) -> TrackTimingProfile:
    return TrackTimingProfile(
        source_duration_seconds=duration,
        lyric_timestamps_available=True,
        lyric_lines=(
            TimingInterval(
                start_seconds=first_vocal_start,
                end_seconds=min(first_vocal_start + 4, last_vocal_end),
            ),
            TimingInterval(
                start_seconds=max(first_vocal_start + 5, last_vocal_end - 4),
                end_seconds=last_vocal_end,
            ),
        ),
        vocal_intervals=(
            TimingInterval(
                start_seconds=first_vocal_start,
                end_seconds=min(first_vocal_start + 4, last_vocal_end),
            ),
            TimingInterval(
                start_seconds=max(first_vocal_start + 5, last_vocal_end - 4),
                end_seconds=last_vocal_end,
            ),
        ),
    )


def test_opening_host_uses_safe_instrumental_window_without_breaking_crossfade() -> None:
    opening = _music("a", 0, 60).model_copy(
        update={
            "timing_profile": TrackTimingProfile(
                source_duration_seconds=60,
                lyric_timestamps_available=True,
                lyric_lines=(
                    TimingInterval(start_seconds=24, end_seconds=28),
                    TimingInterval(start_seconds=48, end_seconds=52),
                ),
                vocal_intervals=(
                    TimingInterval(start_seconds=24, end_seconds=28),
                    TimingInterval(start_seconds=48, end_seconds=52),
                ),
                sections=(
                    TrackSection(
                        kind=TrackSectionKind.INTRO_INSTRUMENTAL,
                        start_seconds=0,
                        end_seconds=24,
                    ),
                    TrackSection(
                        kind=TrackSectionKind.VOCAL,
                        start_seconds=24,
                        end_seconds=52,
                    ),
                    TrackSection(
                        kind=TrackSectionKind.OUTRO_INSTRUMENTAL,
                        start_seconds=52,
                        end_seconds=60,
                    ),
                ),
            )
        }
    )
    opening_host = _voice(
        "segment-opening-host",
        1,
        8,
        NarrationRole.INTRO,
    )
    next_music = _music("b", 2, 35)

    plan = plan_episode_mix(_episode(opening, opening_host, next_music))

    voice = next(
        clip for clip in plan.clips if clip.segment_id == "segment-opening-host"
    )
    first = next(clip for clip in plan.clips if clip.segment_id == "a")
    second = next(clip for clip in plan.clips if clip.segment_id == "b")

    assert voice.timeline_start_seconds == pytest.approx(6.0)
    assert voice.timeline_end_seconds < 24
    assert second.timeline_start_seconds == pytest.approx(50.0)
    assert first.timeline_end_seconds == pytest.approx(60.0)
    assert next(
        point for point in first.gain_automation if point.offset_seconds == 6.0
    ).gain == pytest.approx(0.30)
    assert next(
        point for point in first.gain_automation if point.offset_seconds == 15.5
    ).gain == pytest.approx(1.0)
    assert second.fade_in_seconds == pytest.approx(10.0)


def test_lyric_timing_places_voice_after_last_outgoing_vocal() -> None:
    outgoing = _music("a", 0, 60).model_copy(
        update={
            "timing_profile": _timing_profile(
                duration=60,
                first_vocal_start=5,
                last_vocal_end=50,
            )
        }
    )
    plan = plan_episode_mix(
        _episode(
            outgoing,
            _voice("bridge", 1, 12, NarrationRole.TRANSITION),
            _music("b", 2, 35),
        )
    )

    voice = next(clip for clip in plan.clips if clip.segment_id == "bridge")
    assert voice.timeline_start_seconds == pytest.approx(50.75)
    assert voice.timeline_start_seconds > 50


def test_lyric_timing_keeps_incoming_vocal_out_from_under_narration() -> None:
    incoming = _music("b", 2, 35).model_copy(
        update={
            "timing_profile": _timing_profile(
                duration=35,
                first_vocal_start=3,
                last_vocal_end=30,
            )
        }
    )
    plan = plan_episode_mix(
        _episode(
            _music("a", 0, 40),
            _voice("bridge", 1, 8, NarrationRole.TRANSITION),
            incoming,
        )
    )

    voice = next(clip for clip in plan.clips if clip.segment_id == "bridge")
    music = next(clip for clip in plan.clips if clip.segment_id == "b")
    assert music.timeline_start_seconds == pytest.approx(voice.timeline_end_seconds - 2.25)
    # The first vocal begins after the narration has finished plus the guard.
    assert music.timeline_start_seconds + 3 >= voice.timeline_end_seconds + 0.75


def test_missing_timing_profile_retains_existing_fixed_bridge_geometry() -> None:
    plan = plan_episode_mix(
        _episode(
            _music("a", 0, 40),
            _voice("bridge", 1, 8, NarrationRole.TRANSITION),
            _music("b", 2, 35),
        )
    )
    voice = next(clip for clip in plan.clips if clip.segment_id == "bridge")
    incoming = next(clip for clip in plan.clips if clip.segment_id == "b")

    assert voice.timeline_start_seconds == 36
    assert incoming.timeline_start_seconds == 40
