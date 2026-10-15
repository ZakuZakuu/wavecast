"""Two things a real whole-programme run showed (see docs/research/.../programme-acceptance-20261015.md)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from wavecast.assembly import _planner_deadline_seconds
from wavecast.intelligence.research import BACKGROUND_RESEARCH_PLANNER_DEADLINE_SECONDS
from wavecast.providers.config import ProviderSettings
from wavecast.providers.usage import UsageEvent

from services.api import main as api_module


def test_an_ark_planner_gets_arks_own_time_not_the_fast_models_twenty_seconds() -> None:
    ark = ProviderSettings(mode="live", research_plan_provider="ark", ark_api_key="k",
                           ark_models={"research_plan": "m"}, ark_timeout_seconds=60.0)
    other = ProviderSettings(mode="mock")

    assert _planner_deadline_seconds(ark) == 65.0  # a 20 s deadline cancelled a Pro planner mid-answer
    assert _planner_deadline_seconds(other) == BACKGROUND_RESEARCH_PLANNER_DEADLINE_SECONDS
    shorter = ProviderSettings(mode="live", research_plan_provider="ark", ark_api_key="k",
                               ark_models={"research_plan": "m"}, ark_timeout_seconds=5.0)
    assert _planner_deadline_seconds(shorter) == BACKGROUND_RESEARCH_PLANNER_DEADLINE_SECONDS  # never below the default


def test_the_opening_hosts_voice_is_recorded_against_the_new_episode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(api_module.app)
    owner = {"X-Wavecast-Listener": "opening-host-scope"}
    original = api_module.narration_materializer.materialize
    seen: list[str | None] = []

    async def recording(segment, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = await original(segment, *args, **kwargs)
        event = UsageEvent(provider="minimax", operation="tts", elapsed_ms=1, usage_characters=58)
        api_module._usage_ledger().record(event)  # noqa: SLF001
        seen.append(event.scope)
        return result

    monkeypatch.setattr(api_module.narration_materializer, "materialize", recording)
    batch = client.post(
        "/api/program-proposals",
        json={"prompt": "something to listen to", "count": 1, "duration_intent": "SHORT"},
        headers=owner,
    )
    assert batch.status_code == 200, batch.text
    proposal = batch.json()["proposals"][0]

    created = client.post(f"/api/episodes/from-seed/{proposal['id']}", headers=owner)

    assert created.status_code == 200
    assert seen == [created.json()["id"]]
    asyncio.run(api_module._usage_ledger().flush())  # noqa: SLF001
