import asyncio

import pytest
from wavecast.composer import _narration_role
from wavecast.intelligence.models import RadioScriptBlockKind
from wavecast.materialization import NarrationMaterializer
from wavecast.models.episode import NarrationRole, NarrationSegment, SegmentState
from wavecast.providers.fakes import MockTTSProvider
from wavecast.speech import SpeechDirector, SpeechProfile
from wavecast.storage import LocalObjectStorageProvider


@pytest.mark.parametrize(
    ("kind", "role"),
    [
        (RadioScriptBlockKind.INTRO, NarrationRole.INTRO),
        (RadioScriptBlockKind.TRACK_INTRO, NarrationRole.TRACK_INTRO),
        (RadioScriptBlockKind.TRANSITION, NarrationRole.TRANSITION),
        (RadioScriptBlockKind.OUTRO, NarrationRole.OUTRO),
    ],
)
def test_composer_maps_script_kind_to_typed_narration_role(kind, role) -> None:
    assert _narration_role(kind) is role


def test_speech_director_is_deterministic_and_bounded() -> None:
    first = SpeechDirector.profile_for(NarrationRole.TRACK_INTRO, "\u5148\u542c\u8fd9\u4e00\u9996")
    second = SpeechDirector.profile_for(NarrationRole.TRACK_INTRO, "\u5148\u542c\u8fd9\u4e00\u9996")

    assert first == second
    assert 0.5 <= first.speed <= 2.0
    assert first.speed == 0.82


def test_mixed_cjk_and_latin_is_slower_than_same_role_plain_cjk() -> None:
    plain = SpeechDirector.profile_for(
        NarrationRole.TRANSITION, "\u6211\u4eec\u7ee7\u7eed\u542c\u4e0b\u4e00\u9996"
    )
    mixed = SpeechDirector.profile_for(
        NarrationRole.TRANSITION, "\u6211\u4eec\u7ee7\u7eed\u542c Musiq Soulchild"
    )

    assert mixed.speed < plain.speed
    assert mixed.speed >= 0.5


def test_tts_cache_key_includes_selected_profile() -> None:
    provider = MockTTSProvider(LocalObjectStorageProvider())
    slow = SpeechProfile(speed=0.78)
    quick = SpeechProfile(speed=0.82)

    assert provider.cache_key(
        "\u540c\u4e00\u6bb5\u65c1\u767d", [], profile=slow
    ) != provider.cache_key("\u540c\u4e00\u6bb5\u65c1\u767d", [], profile=quick)
    assert provider.cache_key(
        "\u540c\u4e00\u6bb5\u65c1\u767d", [], profile=slow
    ) == provider.cache_key("\u540c\u4e00\u6bb5\u65c1\u767d", [], profile=slow)


def test_materializer_passes_profile_and_keeps_visible_text(tmp_path) -> None:
    storage = LocalObjectStorageProvider(tmp_path / "audio")

    class RecordingTTS:
        provider_name = "recording"

        def __init__(self) -> None:
            self.profiles: list[SpeechProfile | None] = []
            self.calls = 0

        def cache_key(self, text, cues, *, profile=None):
            return MockTTSProvider(storage).cache_key(text, cues, profile=profile)

        async def synthesize(self, text, *, cues, profile=None):
            self.calls += 1
            self.profiles.append(profile)
            return await MockTTSProvider(storage).synthesize(text, cues=cues, profile=profile)

    provider = RecordingTTS()
    segment = NarrationSegment(
        id="speech-profile-segment",
        chapter_id="chapter-1",
        order=1,
        state=SegmentState.SCRIPT_READY,
        planned_duration_seconds=30,
        title="Track intro",
        narration_text="\u542c\u542c\u8fd9\u4e00\u6bb5\u3002",
        tts_cues=["breath"],
        narration_role=NarrationRole.TRACK_INTRO,
    )

    asyncio.run(NarrationMaterializer(provider, storage).materialize(segment))

    assert segment.narration_text == "\u542c\u542c\u8fd9\u4e00\u6bb5\u3002"
    assert provider.calls == 1
    assert provider.profiles == [SpeechProfile(speed=0.82)]


def test_speech_director_tracks_provider_baseline() -> None:
    default = SpeechDirector.profile_for(NarrationRole.TRANSITION, "继续听下去")
    overridden = SpeechDirector.profile_for(
        NarrationRole.TRANSITION,
        "继续听下去",
        baseline_speed=0.9,
    )

    assert default.speed == 0.8
    assert overridden.speed == 0.9
