from wavecast.arrangement import plan_episode_mix
from wavecast.models.episode import MusicSegment, NarrationSegment, PlayableEpisode, SegmentState


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
    assert next(point for point in music_b.gain_automation if point.offset_seconds == 10).gain == 0.35
    assert next(point for point in music_b.gain_automation if point.offset_seconds == 10.5).gain == 1


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


def test_final_outro_overlays_last_music_tail() -> None:
    plan = plan_episode_mix(fixture_episode())
    last_music = next(clip for clip in plan.clips if clip.segment_id == "music-b")
    outro = next(clip for clip in plan.clips if clip.segment_id == "outro")

    assert outro.timeline_start_seconds < last_music.timeline_end_seconds
