from __future__ import annotations

import asyncio

import pytest
from wavecast.assembly import MockEpisodeAssemblyLLM, create_episode_assembly_service
from wavecast.providers.config import ProviderSettings
from wavecast.providers.factory import build_music_registry
from wavecast.providers.fakes import FakeSearchProvider, MockTTSProvider
from wavecast.storage import LocalObjectStorageProvider


def test_music_selector_can_enable_netease_under_global_mock() -> None:
    registry = build_music_registry(
        ProviderSettings(
            mode="mock",
            music_provider="netease",
            netease_music_api_base_url="https://music.test",
        )
    )
    try:
        assert list(registry.providers) == ["netease"]
        assert registry.preference == ("netease",)
    finally:
        asyncio.run(registry.aclose())


def test_writer_override_does_not_enable_sibling_capabilities(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class LiveLLM:
        pass

    monkeypatch.setattr(
        "wavecast.assembly.DeepSeekLLMProvider",
        lambda *_args, **_kwargs: LiveLLM(),
    )
    service = create_episode_assembly_service(
        ProviderSettings(
            mode="mock",
            writer_provider="deepseek",
            deepseek_api_key="test",
        ),
        storage=LocalObjectStorageProvider(tmp_path / "audio"),
    )

    assert isinstance(service.fast_path.planner.llm, MockEpisodeAssemblyLLM)
    assert isinstance(service.background_pipeline.research.discovery, FakeSearchProvider)
    assert isinstance(service.background_pipeline.research.research, FakeSearchProvider)
    assert isinstance(service.background_pipeline.curator.llm, MockEpisodeAssemblyLLM)
    assert isinstance(service.background_pipeline.writer.llm, LiveLLM)
    assert isinstance(service.materializer.tts_provider, MockTTSProvider)


def test_research_override_enables_only_research_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class LiveLLM:
        pass

    class Discovery:
        pass

    class Research:
        pass

    monkeypatch.setattr(
        "wavecast.assembly.DeepSeekLLMProvider",
        lambda *_args, **_kwargs: LiveLLM(),
    )
    monkeypatch.setattr(
        "wavecast.assembly.ExaSearchProvider",
        lambda *_args, **_kwargs: Discovery(),
    )
    monkeypatch.setattr(
        "wavecast.assembly.TavilySearchProvider",
        lambda *_args, **_kwargs: Research(),
    )
    service = create_episode_assembly_service(
        ProviderSettings(
            mode="mock",
            research_provider="live",
            deepseek_api_key="test",
            exa_api_key="test",
            tavily_api_key="test",
        ),
        storage=LocalObjectStorageProvider(tmp_path / "audio"),
    )

    assert isinstance(service.fast_path.planner.llm, MockEpisodeAssemblyLLM)
    assert isinstance(service.background_pipeline.research.discovery, Discovery)
    assert isinstance(service.background_pipeline.research.research, Research)
    assert isinstance(service.background_pipeline.research.planner.llm, LiveLLM)
    assert isinstance(service.background_pipeline.curator.llm, MockEpisodeAssemblyLLM)
    assert isinstance(service.background_pipeline.writer.llm, MockEpisodeAssemblyLLM)
    assert isinstance(service.materializer.tts_provider, MockTTSProvider)


def test_tts_override_selects_minimax_without_enabling_other_capabilities(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class LiveTTS:
        provider_name = "minimax"

    monkeypatch.setattr(
        "wavecast.assembly.MiniMaxTTSProvider",
        lambda *_args, **_kwargs: LiveTTS(),
    )
    service = create_episode_assembly_service(
        ProviderSettings(
            mode="mock",
            tts_provider="minimax",
            minimax_api_key="test",
            minimax_tts_voice_id="voice",
        ),
        storage=LocalObjectStorageProvider(tmp_path / "audio"),
    )

    assert isinstance(service.fast_path.planner.llm, MockEpisodeAssemblyLLM)
    assert isinstance(service.background_pipeline.research.discovery, FakeSearchProvider)
    assert isinstance(service.background_pipeline.curator.llm, MockEpisodeAssemblyLLM)
    assert isinstance(service.background_pipeline.writer.llm, MockEpisodeAssemblyLLM)
    assert isinstance(service.materializer.tts_provider, LiveTTS)
