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
