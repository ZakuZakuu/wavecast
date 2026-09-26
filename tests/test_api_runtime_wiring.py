from __future__ import annotations

import importlib

import pytest
from wavecast.materialization import NarrationMaterializer
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.providers.fakes import MockTTSProvider
from wavecast.storage import LocalObjectStorageProvider


@pytest.fixture
def api_module():
    return importlib.import_module("services.api.main")


def test_live_runtime_configuration_fails_closed_without_real_provider(
    api_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_configuration(*args: object, **kwargs: object) -> object:
        raise ProviderConfigurationError("real music provider is not configured")

    monkeypatch.setattr(api_module, "create_episode_assembly_service", fail_configuration)

    with pytest.raises(ProviderConfigurationError, match="real music provider"):
        api_module._build_progressive_runtime(
            ProviderSettings(mode="live"), LocalObjectStorageProvider()
        )


def test_configure_narration_materializer_rebuilds_active_runtime(
    api_module, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    old_state = (
        api_module.audio_storage,
        api_module.narration_materializer,
        api_module.music_snapshot_store,
        api_module.progressive_runtime,
        api_module.orchestrator,
        api_module.scheduler,
    )
    storage = LocalObjectStorageProvider(tmp_path / "audio-b")
    runtime = object()
    monkeypatch.setattr(api_module, "_build_progressive_runtime", lambda settings, storage: runtime)

    try:
        api_module.configure_narration_materializer(
            NarrationMaterializer(MockTTSProvider(storage), storage)
        )

        assert api_module.audio_storage is storage
        assert api_module.progressive_runtime is runtime
        assert api_module.orchestrator.progressive_runtime is runtime
        assert api_module.orchestrator.audio_provider is api_module.audio_provider
        assert api_module.scheduler.orchestrator is api_module.orchestrator
    finally:
        (
            api_module.audio_storage,
            api_module.narration_materializer,
            api_module.music_snapshot_store,
            api_module.progressive_runtime,
            api_module.orchestrator,
            api_module.scheduler,
        ) = old_state


@pytest.mark.parametrize(
    ("track_ref", "expected_url"),
    [
        ("netease:17266838", "/api/audio/sidecar/netease/17266838"),
        ("qqmusic:0039MnYb0qxYhV", "/api/audio/sidecar/qqmusic/0039MnYb0qxYhV"),
        ("audius:artist/track", "/api/audio/audius/artist%2Ftrack"),
    ],
)
def test_real_music_audio_provider_uses_same_origin_proxy_routes(
    api_module,
    track_ref: str,
    expected_url: str,
) -> None:
    provider = api_module._build_audio_provider(
        ProviderSettings(mode="mock", music_provider="auto")
    )

    music = provider.music_source(track_ref)
    narration = provider.narration_source("segment-1", "hello", 8)

    assert music.source_url == expected_url
    assert music.duration_seconds == 30
    assert narration.source_url.startswith("/api/audio/mock/narration/")


def test_mock_music_audio_provider_keeps_mock_route(api_module) -> None:
    provider = api_module._build_audio_provider(ProviderSettings(mode="mock"))

    music = provider.music_source("mock:opening")

    assert music.source_url.startswith("/api/audio/mock/music/")


def test_pure_mock_keeps_deterministic_progressive_runtime(
    api_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    assembly = object()
    monkeypatch.setattr(
        api_module,
        "create_episode_assembly_service",
        lambda settings, storage: assembly,
    )

    runtime = api_module._build_progressive_runtime(
        ProviderSettings(mode="mock"),
        LocalObjectStorageProvider(),
    )

    assert runtime is not None
    assert runtime.assembly is assembly


def test_music_only_live_override_does_not_activate_progressive_runtime(
    api_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_build(*args: object, **kwargs: object) -> object:
        raise AssertionError("music-only rollout must not build progressive assembly")

    monkeypatch.setattr(api_module, "create_episode_assembly_service", unexpected_build)

    runtime = api_module._build_progressive_runtime(
        ProviderSettings(mode="mock", music_provider="netease"),
        LocalObjectStorageProvider(),
    )

    assert runtime is None


def test_api_orchestrator_uses_configured_audio_provider(api_module) -> None:
    assert api_module.orchestrator.audio_provider is api_module.audio_provider
