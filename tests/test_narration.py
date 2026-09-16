import asyncio

import pytest
from wavecast.materialization import NarrationMaterializer
from wavecast.models.episode import CoverParams, EpisodeSeed, NarrationSegment, SegmentState
from wavecast.narration import render_narration
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
from wavecast.providers.errors import ProviderInvalidResponseError, ProviderUnavailableError
from wavecast.providers.fakes import MockTTSProvider
from wavecast.storage import LocalObjectStorageProvider


def narration_segment(*, state: SegmentState = SegmentState.SCRIPT_READY) -> NarrationSegment:
    return NarrationSegment(
        id="narration-1",
        chapter_id="chapter-1",
        order=1,
        state=state,
        planned_duration_seconds=99,
        title="Intro",
        narration_text="A restrained radio introduction.",
        tts_cues=["pause_short", "unknown-provider-tag", "breath"],
    )


def test_cue_renderer_allowlist_ignores_unknown_values() -> None:
    rendered = render_narration("Hello", ["pause_short", "unknown", "breath"])

    assert rendered.text == "Hello (breath)"
    assert rendered.recognized_cues == ("pause_short", "breath")


def test_cue_renderer_never_emits_positionless_pause_markers() -> None:
    rendered = render_narration(
        "Hello, listener.", ["pause_short", "pause_medium", "pause_long", "breath"]
    )

    assert "<#" not in rendered.text
    assert not rendered.text.startswith("<#")
    assert not rendered.text.endswith("#>")
    assert "#> <#" not in rendered.text
    assert rendered.text == "Hello, listener. (breath)"


def test_mock_materializer_stores_browser_audio_and_is_idempotent(tmp_path) -> None:
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    provider = MockTTSProvider(storage)
    materializer = NarrationMaterializer(provider, storage)
    first = narration_segment()

    asyncio.run(materializer.materialize(first))

    assert first.state is SegmentState.AUDIO_READY
    assert first.audio_source_url.startswith("/api/assets/audio/")
    assert first.actual_duration_seconds is not None
    assert first.actual_duration_seconds < first.planned_duration_seconds
    stored = asyncio.run(storage.get(first.asset_ref))
    assert stored is not None
    assert stored.content_type == "audio/wav"
    assert provider.calls == 1

    second = narration_segment()
    second.id = "narration-2"
    asyncio.run(materializer.materialize(second))

    assert second.state is SegmentState.AUDIO_READY
    assert second.asset_ref == first.asset_ref
    assert provider.calls == 1


def test_materializer_returns_failed_segment_to_script_ready(tmp_path) -> None:
    class FailingProvider:
        async def synthesize(self, text: str, *, cues: list[str]):
            del text, cues
            raise ProviderUnavailableError("temporary TTS outage")

    storage = LocalObjectStorageProvider(tmp_path / "audio")
    segment = narration_segment()
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(NarrationMaterializer(FailingProvider(), storage).materialize(segment))
    assert segment.state is SegmentState.SCRIPT_READY


def test_committed_narration_cannot_be_regenerated(tmp_path) -> None:
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    segment = narration_segment(state=SegmentState.COMMITTED)

    with pytest.raises(ProviderInvalidResponseError, match="requires SCRIPT_READY"):
        asyncio.run(NarrationMaterializer(MockTTSProvider(storage), storage).materialize(segment))


@pytest.mark.parametrize(
    "state",
    [
        SegmentState.PLANNED,
        SegmentState.COMMITTED,
        SegmentState.PLAYED,
        SegmentState.SKIPPED,
        SegmentState.AUDIO_GENERATING,
    ],
)
def test_materializer_rejects_non_script_ready_states_without_tts_call(
    tmp_path, state: SegmentState
) -> None:
    class CountingProvider:
        calls = 0

        async def synthesize(self, text: str, *, cues: list[str]):
            del text, cues
            self.calls += 1
            raise AssertionError("TTS must not be called for an invalid materialization state")

    storage = LocalObjectStorageProvider(tmp_path / "audio")
    provider = CountingProvider()
    segment = narration_segment(state=state)
    with pytest.raises(ProviderInvalidResponseError, match="requires SCRIPT_READY"):
        asyncio.run(NarrationMaterializer(provider, storage).materialize(segment))
    assert provider.calls == 0


def test_missing_script_cannot_trigger_tts(tmp_path) -> None:
    class CountingProvider:
        calls = 0

        async def synthesize(self, text: str, *, cues: list[str]):
            del text, cues
            self.calls += 1
            raise AssertionError("TTS must not be called without a script")

    storage = LocalObjectStorageProvider(tmp_path / "audio")
    provider = CountingProvider()
    segment = narration_segment()
    segment.narration_text = None
    with pytest.raises(ProviderInvalidResponseError, match="no script text"):
        asyncio.run(NarrationMaterializer(provider, storage).materialize(segment))
    assert provider.calls == 0


def test_local_storage_rejects_path_traversal(tmp_path) -> None:
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    with pytest.raises(ValueError):
        asyncio.run(storage.put("../secret.mp3", b"secret", "audio/mpeg"))


def test_audio_asset_endpoint_serves_stored_content(tmp_path, monkeypatch) -> None:
    import services.api.main as api

    storage = LocalObjectStorageProvider(tmp_path / "audio")
    asyncio.run(storage.put("fixture.mp3", b"mp3-fixture", "audio/mpeg"))
    monkeypatch.setattr(api, "audio_storage", storage)

    response = asyncio.run(api.audio_asset("fixture.mp3"))

    assert response.body == b"mp3-fixture"
    assert response.media_type == "audio/mpeg"


def test_mock_vertical_slice_moves_music_to_narration_to_next_music(tmp_path) -> None:
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(repository)
    episode = runtime.start(
        EpisodeSeed(
            id="tts-seed",
            title="TTS fixture",
            topic="Narration materialization",
            short_description="A fixture",
            estimated_duration_seconds=300,
            opening_track_ref="mock:opening",
            opening_track_title="Opening",
            opening_track_artist="Artist",
            cover=CoverParams(family="test", seed=1, palette=("#000", "#fff")),
        )
    )
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    materializer = NarrationMaterializer(MockTTSProvider(storage), storage)
    narration = episode.segment("segment-narration-1")
    narration.narration_text = "Welcome to the next track."
    narration.state = SegmentState.SCRIPT_READY

    asyncio.run(materializer.materialize(narration))
    repository.save(episode)
    after_opening = runtime.complete_current_segment(episode.id)
    assert after_opening.current_segment_id == narration.id
    assert after_opening.segment(narration.id).state is SegmentState.COMMITTED

    after_narration = runtime.complete_current_segment(episode.id)
    assert after_narration.is_playing is False
    next_music = runtime.next_playable(episode.id)
    assert next_music.current_segment_id == "segment-bridge"
    assert next_music.segment("segment-bridge").is_committed
    assert narration.audio_source_url.startswith("/api/assets/audio/")
