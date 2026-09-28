from wavecast.audio_timing import (
    TrackSectionKind,
    TrackTimingProfile,
    TimingInterval,
    safe_incoming_music_overlap_seconds,
    safe_outgoing_narration_overlap_seconds,
    track_timing_profile_from_payload,
)


def test_timing_profile_derives_instrumental_windows_without_lyric_text() -> None:
    profile = track_timing_profile_from_payload(
        {
            "source_duration_seconds": 60,
            "lyric_timestamps_available": True,
            "lyric_lines": [
                {"start_seconds": 5, "end_seconds": 10},
                {"start_seconds": 20, "end_seconds": 25},
                {"start_seconds": 44, "end_seconds": 50},
            ],
            "vocal_intervals": [
                {"start_seconds": 5, "end_seconds": 10},
                {"start_seconds": 20, "end_seconds": 25},
                {"start_seconds": 44, "end_seconds": 50},
            ],
        }
    )

    assert profile is not None
    assert profile.first_vocal_start_seconds == 5
    assert profile.last_vocal_end_seconds == 50
    assert [section.kind for section in profile.sections] == [
        TrackSectionKind.INTRO_INSTRUMENTAL,
        TrackSectionKind.VOCAL,
        TrackSectionKind.INSTRUMENTAL_GAP,
        TrackSectionKind.VOCAL,
        TrackSectionKind.INSTRUMENTAL_GAP,
        TrackSectionKind.VOCAL,
        TrackSectionKind.OUTRO_INSTRUMENTAL,
    ]
    assert "text" not in profile.model_dump_json()


def test_safe_overlap_uses_vocal_boundaries_when_available() -> None:
    profile = TrackTimingProfile(
        source_duration_seconds=60,
        lyric_timestamps_available=True,
        lyric_lines=(TimingInterval(start_seconds=3, end_seconds=8),),
        vocal_intervals=(
            TimingInterval(start_seconds=3, end_seconds=8),
            TimingInterval(start_seconds=45, end_seconds=50),
        ),
    )

    assert safe_outgoing_narration_overlap_seconds(
        profile,
        fallback_seconds=5,
        max_seconds=12,
        guard_seconds=0.75,
    ) == 9.25
    assert safe_incoming_music_overlap_seconds(
        profile,
        fallback_seconds=5,
        guard_seconds=0.75,
    ) == 2.25


def test_safe_overlap_preserves_fixed_fallback_without_timed_lyrics() -> None:
    profile = TrackTimingProfile(source_duration_seconds=60)

    assert safe_outgoing_narration_overlap_seconds(
        profile,
        fallback_seconds=5,
        max_seconds=12,
    ) == 5
    assert safe_incoming_music_overlap_seconds(
        profile,
        fallback_seconds=5,
    ) == 5
