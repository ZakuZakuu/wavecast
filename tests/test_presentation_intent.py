from wavecast.presentation import (
    HostMode,
    OpeningStrategy,
    TransitionStyle,
    infer_presentation_intent,
    narration_ratio_for_host_mode,
)


def test_pure_music_request_disables_host_without_disabling_mixing() -> None:
    intent = infer_presentation_intent("只放歌，不要旁白，做成 DJ mix")

    assert intent.host_mode is HostMode.NONE
    assert intent.opening_strategy is OpeningStrategy.OPPORTUNISTIC
    assert intent.transition_style is TransitionStyle.DJ


def test_guided_quick_tour_uses_full_host_and_early_bridge() -> None:
    intent = infer_presentation_intent("带我了解 neo soul，快速探索一遍")

    assert intent.host_mode is HostMode.FULL
    assert intent.opening_strategy is OpeningStrategy.EARLY_BRIDGE
    assert intent.transition_style is TransitionStyle.RADIO


def test_full_track_request_preserves_song_and_default_light_host() -> None:
    intent = infer_presentation_intent("完整播放每一整首爵士，不要截歌")

    assert intent.host_mode is HostMode.LIGHT
    assert intent.opening_strategy is OpeningStrategy.FULL_TRACK
    assert intent.transition_style is TransitionStyle.RADIO


def test_host_modes_have_distinct_narration_density() -> None:
    none = narration_ratio_for_host_mode(HostMode.NONE)
    light = narration_ratio_for_host_mode(HostMode.LIGHT)
    full = narration_ratio_for_host_mode(HostMode.FULL)

    assert none == 0
    assert 0 < light < full
    assert full == 0.15
