"""Text-model roles are bound one by one; an unconfigured role keeps the model it always had."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from wavecast.assembly import MockEpisodeAssemblyLLM, create_episode_assembly_service
from wavecast.providers.config import LLM_ROLES, ProviderSettings
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.recommendations import (
    DeterministicRecommendationPlanner,
    ProviderBackedRecommendationPlanner,
)
from wavecast.storage import LocalObjectStorageProvider

ENV_NAMES = (
    [f"WAVECAST_{name}_PROVIDER" for name in ("FAST_START", "RESEARCH", "CURATOR", "WRITER")]
    + [f"WAVECAST_{name}_PROVIDER" for name in ("RESEARCH_PLAN", "MATERIAL", "FACT_CHECK", "TRACK_RESEARCH")]
    + ["WAVECAST_PROPOSAL_PLANNER", "WAVECAST_PROVIDER_MODE", "ARK_API_KEY", "ARK_BASE_URL"]
    + [f"ARK_{role.upper()}_MODEL" for role in LLM_ROLES]
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def resolved(settings: ProviderSettings) -> dict[str, str]:
    return {role: settings.resolved_llm(role) for role in LLM_ROLES}


def test_defaults_are_unchanged_mock_and_deepseek() -> None:
    assert set(resolved(ProviderSettings(mode="mock")).values()) == {"mock"}
    assert set(resolved(ProviderSettings(mode="live")).values()) == {"deepseek"}


def test_writer_on_ark_does_not_move_the_fact_checker_or_track_research() -> None:
    settings = ProviderSettings(mode="live", writer_provider="ark")

    roles = resolved(settings)
    assert roles["writer"] == "ark"
    assert roles["fact_check"] == roles["track_research"] == "deepseek"
    assert roles["research_plan"] == roles["curator"] == roles["fast_start"] == "deepseek"
    assert roles["proposal"] == roles["material"] == "deepseek"


def test_writer_on_ark_under_global_mock_leaves_the_others_mock() -> None:
    roles = resolved(ProviderSettings(mode="mock", writer_provider="ark"))

    assert roles["writer"] == "ark"
    assert {role: choice for role, choice in roles.items() if role != "writer"} == {
        role: "mock" for role in LLM_ROLES if role != "writer"
    }


def test_an_explicit_deepseek_or_mock_writer_still_carries_the_roles_that_shared_it() -> None:
    # Exactly the previous behaviour: fact checking and track research followed writer_llm.
    assert ProviderSettings(mode="mock", writer_provider="deepseek").resolved_llm("fact_check") == "deepseek"
    assert ProviderSettings(mode="mock", writer_provider="deepseek").resolved_llm("track_research") == "deepseek"
    assert ProviderSettings(mode="live", writer_provider="mock").resolved_llm("fact_check") == "mock"
    assert ProviderSettings(mode="live", writer_provider="mock").resolved_llm("track_research") == "mock"


def test_explicit_track_research_with_ark_writer_and_global_mock_accepts_the_brief_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from types import SimpleNamespace

    from wavecast.intelligence.track_research import _Briefing
    from wavecast.providers.deepseek import DeepSeekLLMProvider
    from wavecast.providers.llm_factory import build_llm
    from wavecast.providers.profiles import InferenceProfile, StructuredTransport
    from wavecast.providers.usage import UsageLedger

    monkeypatch.setenv("WAVECAST_PROVIDER_MODE", "mock")
    monkeypatch.setenv("WAVECAST_WRITER_PROVIDER", "ark")
    monkeypatch.setenv("WAVECAST_TRACK_RESEARCH_PROVIDER", "deepseek")
    settings = ProviderSettings.from_env()
    requested = []

    class Responses:
        async def create(self, **kwargs):  # noqa: ANN003
            requested.append(kwargs["text"]["format"]["name"])
            return SimpleNamespace(status="completed", output=[SimpleNamespace(
                type="message", content=[SimpleNamespace(type="output_text", text='{"points":[]}')],
            )])

    monkeypatch.setattr(
        "wavecast.providers.llm_factory.DeepSeekLLMProvider",
        lambda *args, **kwargs: DeepSeekLLMProvider(*args, **kwargs, client=SimpleNamespace(responses=Responses())),
    )
    client = build_llm(settings, "track_research", ledger=UsageLedger(), mock=MockEpisodeAssemblyLLM())
    result = asyncio.run(client.structured(
        "brief", _Briefing, transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
        profile=InferenceProfile.FAST, stage="track_brief",
    ))
    assert requested == ["_Briefing"] and isinstance(result, _Briefing)


def test_the_research_planner_still_follows_the_research_capability() -> None:
    assert ProviderSettings(mode="mock", research_provider="live").resolved_llm("research_plan") == "deepseek"
    assert ProviderSettings(mode="live", research_provider="mock").resolved_llm("research_plan") == "mock"


def test_each_role_can_be_bound_on_its_own() -> None:
    settings = ProviderSettings(
        mode="live",
        proposal_planner="ark",
        fact_check_provider="ark",
        material_provider="ark",
        research_plan_provider="mock",
        track_research_provider="ark",
    )

    assert resolved(settings) == {
        "proposal": "ark",
        "fast_start": "deepseek",
        "research_plan": "mock",
        "material": "ark",
        "curator": "deepseek",
        "writer": "deepseek",
        "fact_check": "ark",
        "track_research": "ark",
    }


def test_environment_selectors_and_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAVECAST_PROVIDER_MODE", "live")
    monkeypatch.setenv("WAVECAST_WRITER_PROVIDER", "ark")
    monkeypatch.setenv("WAVECAST_FACT_CHECK_PROVIDER", "deepseek")
    monkeypatch.setenv("ARK_API_KEY", "KEY-123")
    monkeypatch.setenv("ARK_WRITER_MODEL", " doubao-seed-2-1-lite-260915 ")
    monkeypatch.setenv("ARK_PROPOSAL_MODEL", "doubao-seed-2-1-pro-260915")

    settings = ProviderSettings.from_env()

    assert settings.resolved_llm("writer") == "ark"
    assert settings.resolved_llm("fact_check") == "deepseek"
    assert settings.ark_model_for("writer") == "doubao-seed-2-1-lite-260915"
    assert settings.ark_model_for("proposal") == "doubao-seed-2-1-pro-260915"
    assert settings.credential_for("ark") == "KEY-123"
    assert "KEY-123" not in repr(settings)


def test_an_unknown_selector_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAVECAST_FACT_CHECK_PROVIDER", "gpt")
    with pytest.raises(ProviderConfigurationError):
        ProviderSettings.from_env()


def test_a_role_on_ark_without_a_model_or_key_fails_clearly_and_only_then() -> None:
    settings = ProviderSettings(mode="live", writer_provider="ark")
    with pytest.raises(ProviderConfigurationError, match="ARK_WRITER_MODEL"):
        settings.ark_model_for("writer")
    with pytest.raises(ProviderConfigurationError):
        ProviderSettings(mode="live").credential_for("ark")


# --- assembly wiring --------------------------------------------------------------------------


class Marker:
    def __init__(self, kind: str, **kwargs: Any) -> None:
        self.kind = kind
        self.kwargs = kwargs


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "wavecast.providers.llm_factory.DeepSeekLLMProvider",
        lambda *_a, **kw: Marker("deepseek", **kw),
    )
    monkeypatch.setattr(
        "wavecast.providers.llm_factory.ArkLLMProvider",
        lambda *_a, **kw: Marker("ark", **kw),
    )
    for name in ("ExaSearchProvider", "TavilySearchProvider"):
        monkeypatch.setattr(f"wavecast.assembly.{name}", lambda *_a, **_kw: Marker("search"))


def build(tmp_path: Path, **overrides: Any):
    base: dict[str, Any] = {
        "mode": "mock",
        "research_provider": "live",
        "deepseek_api_key": "k",
        "ark_api_key": "k",
        "ark_models": {"writer": "doubao-seed-2-1-lite-260915"},
        "exa_api_key": "k",
        "tavily_api_key": "k",
        "music_provider": "mock",
        "tts_provider": "mock",
    }
    return create_episode_assembly_service(
        ProviderSettings(**{**base, **overrides}),
        storage=LocalObjectStorageProvider(tmp_path / "audio"),
    )


def test_assembly_gives_the_ark_writer_alone_to_the_writer(tmp_path: Path, fakes: None) -> None:
    service = build(tmp_path, writer_provider="ark")
    pipeline = service.background_pipeline

    assert pipeline.writer.llm.kind == "ark"
    assert pipeline.writer.llm.kwargs["model"] == "doubao-seed-2-1-lite-260915"
    assert pipeline.writer.llm.kwargs["role"] == "writer"
    # Unconfigured: they keep the base model, not the Writer's.
    assert not hasattr(pipeline.writer, "fact_checker")
    assert isinstance(service.track_research._llm, MockEpisodeAssemblyLLM)


def test_assembly_under_live_mode_keeps_deepseek_for_the_roles_next_to_an_ark_writer(
    tmp_path: Path, fakes: None
) -> None:
    service = build(tmp_path, mode="live", writer_provider="ark")
    pipeline = service.background_pipeline

    assert pipeline.writer.llm.kind == "ark"
    assert not hasattr(pipeline.writer, "fact_checker")
    assert service.track_research._llm.kind == "deepseek"
    assert pipeline.curator.llm.kind == "deepseek"


def test_assembly_does_not_construct_the_legacy_fact_check_client(tmp_path: Path, fakes: None) -> None:
    service = build(
        tmp_path,
        mode="live",
        fact_check_provider="ark",
        ark_api_key=None,
        ark_models={},
    )

    assert service.background_pipeline.writer.llm.kind == "deepseek"
    assert not hasattr(service.background_pipeline.writer, "fact_checker")


def test_unused_ark_settings_never_stop_a_service(tmp_path: Path, fakes: None) -> None:
    # Ark selected for a role with no consumer (material), no key, no model: nothing is built.
    service = build(
        tmp_path, mode="live", material_provider="ark", ark_api_key=None, ark_models={}
    )

    assert service.background_pipeline.writer.llm.kind == "deepseek"


def test_an_ark_role_without_a_model_stops_assembly_with_a_clear_error(
    tmp_path: Path, fakes: None
) -> None:
    with pytest.raises(ProviderConfigurationError, match="ARK_WRITER_MODEL"):
        build(tmp_path, writer_provider="ark", ark_models={})


def test_recommendation_planner_can_carry_its_own_source_label() -> None:
    planner = ProviderBackedRecommendationPlanner(lambda: MockEpisodeAssemblyLLM(), source="ark_planner")  # type: ignore[arg-type,return-value]
    assert planner.source == "ark_planner"
    assert ProviderBackedRecommendationPlanner(lambda: MockEpisodeAssemblyLLM()).source == "deepseek_planner"  # type: ignore[arg-type,return-value]
    assert DeterministicRecommendationPlanner().source


# --- ownership: every client the service created is closed once --------------------------------


class Closeable:
    closes: list[str] = []

    def __init__(self, name: str) -> None:
        self.name = name

    async def aclose(self) -> None:
        Closeable.closes.append(self.name)


@pytest.fixture
def closing_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    Closeable.closes = []
    counter = {"n": 0}

    def make(prefix: str):
        def factory(*_args: Any, **kwargs: Any) -> Closeable:
            counter["n"] += 1
            return Closeable(f"{prefix}:{kwargs.get('role', 'x')}:{counter['n']}")

        return factory

    monkeypatch.setattr("wavecast.providers.llm_factory.DeepSeekLLMProvider", make("deepseek"))
    monkeypatch.setattr("wavecast.providers.llm_factory.ArkLLMProvider", make("ark"))
    monkeypatch.setattr("wavecast.assembly.ExaSearchProvider", make("exa"))
    monkeypatch.setattr("wavecast.assembly.TavilySearchProvider", make("tavily"))


def test_aclose_closes_every_role_client_and_the_deep_search_once(
    tmp_path: Path, closing_fakes: None
) -> None:
    import asyncio

    service = build(
        tmp_path,
        mode="live",
        writer_provider="ark",
        fact_check_provider="ark",
        ark_models={"writer": "w", "fact_check": "f"},
    )

    asyncio.run(service.aclose())

    closed = Closeable.closes
    assert len(closed) == len(set(closed)), "a client was closed twice"
    # fast_start, research_plan, curator, writer, track_research + exa, tavily,
    # and the separate advanced-depth tavily instance.
    assert len([c for c in closed if c.startswith(("deepseek", "ark"))]) == 5
    assert not any(c.startswith("ark:fact_check") for c in closed)
    assert any(c.startswith("ark:writer") for c in closed)
    assert len([c for c in closed if c.startswith("tavily")]) == 2
    assert len([c for c in closed if c.startswith("exa")]) == 1


def test_a_client_shared_by_two_roles_is_closed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    Closeable.closes = []
    shared = Closeable("shared")
    monkeypatch.setattr("wavecast.providers.llm_factory.DeepSeekLLMProvider", lambda *_a, **_k: shared)
    for name in ("ExaSearchProvider", "TavilySearchProvider"):
        monkeypatch.setattr(f"wavecast.assembly.{name}", lambda *_a, **_kw: Marker("search"))

    service = build(tmp_path, mode="live")
    asyncio.run(service.aclose())

    assert Closeable.closes == ["shared"]


def test_one_failing_close_does_not_leave_the_others_open(
    tmp_path: Path, closing_fakes: None
) -> None:
    import asyncio

    service = build(tmp_path, mode="live")
    first = service._owned_clients[0]

    async def explode() -> None:
        raise RuntimeError("close failed")

    first.aclose = explode  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="close failed"):
        asyncio.run(service.aclose())

    assert len(Closeable.closes) >= 5  # everything else was still closed


def test_roles_not_created_are_not_closed_or_required(tmp_path: Path, fakes: None) -> None:
    import asyncio

    # Track research disabled: no client is built for it, and closing works.
    service = build(tmp_path, mode="live", track_research=False)

    assert service.track_research is None
    asyncio.run(service.aclose())
