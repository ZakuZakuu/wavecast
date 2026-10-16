"""What a real whole-programme run showed about the research planner (docs/research/.../programme-acceptance-20261015.md).

The opening host's voice, which the run also showed, is covered in test_ledger_attribution.py."""

from __future__ import annotations

from wavecast.assembly import _planner_deadline_seconds
from wavecast.intelligence.research import BACKGROUND_RESEARCH_PLANNER_DEADLINE_SECONDS
from wavecast.providers.config import ProviderSettings


def test_an_ark_planner_gets_arks_own_time_not_the_fast_models_twenty_seconds() -> None:
    ark = ProviderSettings(mode="live", research_plan_provider="ark", ark_api_key="k",
                           ark_models={"research_plan": "m"}, ark_timeout_seconds=60.0)
    other = ProviderSettings(mode="mock")

    assert _planner_deadline_seconds(ark) == 65.0  # a 20 s deadline cancelled a Pro planner mid-answer
    assert _planner_deadline_seconds(other) == BACKGROUND_RESEARCH_PLANNER_DEADLINE_SECONDS
    shorter = ProviderSettings(mode="live", research_plan_provider="ark", ark_api_key="k",
                               ark_models={"research_plan": "m"}, ark_timeout_seconds=5.0)
    assert _planner_deadline_seconds(shorter) == BACKGROUND_RESEARCH_PLANNER_DEADLINE_SECONDS  # never below the default
