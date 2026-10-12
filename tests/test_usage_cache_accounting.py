import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel
from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider, _cache_split
from wavecast.providers.profiles import StructuredTransport
from wavecast.providers.usage import (
    UsageEvent,
    UsageLedger,
    safe_usage_event,
    usage_diagnostics,
    usage_run_kind,
)


class Answer(BaseModel):
    answer: str


def _settings() -> ProviderSettings:
    return ProviderSettings(mode="live", deepseek_api_key="test", exa_api_key="x", tavily_api_key="x")


def _chat(usage: Any, model: str | None = "deepseek-flash-0001") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"answer": "ok"}'), finish_reason="stop")],
        usage=usage,
        model=model,
        _request_id="r1",
    )


def _responses(usage: Any) -> SimpleNamespace:
    return SimpleNamespace(
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text='{"answer": "ok"}')],
            )
        ],
        usage=usage,
        model="deepseek-flash-0001",
        id="r2",
    )


def _run(response: SimpleNamespace, transport: StructuredTransport) -> UsageLedger:
    class Completions:
        async def create(self, **_kwargs: object) -> SimpleNamespace:
            return response

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions()), responses=Completions()
    )
    ledger = UsageLedger()
    provider = DeepSeekLLMProvider(_settings(), client=client, ledger=ledger)
    asyncio.run(provider.structured("p", Answer, transport=transport, stage="writer"))
    return ledger


def test_chat_cache_hit_and_miss_are_recorded() -> None:
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=50,
        prompt_cache_hit_tokens=640,
        prompt_cache_miss_tokens=360,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=20),
    )
    [event] = _run(_chat(usage), StructuredTransport.CHAT_JSON).events
    assert (event.input_tokens, event.cached_input_tokens, event.uncached_input_tokens) == (1000, 640, 360)
    assert event.output_tokens == 50
    assert event.metadata["reasoning_tokens"] == 20
    assert event.metadata["response_model"] == "deepseek-flash-0001"
    assert event.metadata["transport"] == "chat_json"
    assert event.metadata["stage"] == "writer"


def test_responses_cached_tokens_derive_the_uncached_part() -> None:
    usage = SimpleNamespace(
        input_tokens=2000,
        output_tokens=100,
        input_tokens_details=SimpleNamespace(cached_tokens=1500),
        output_tokens_details=SimpleNamespace(reasoning_tokens=30),
    )
    [event] = _run(_responses(usage), StructuredTransport.RESPONSES_JSON_SCHEMA).events
    assert (event.cached_input_tokens, event.uncached_input_tokens) == (1500, 500)
    assert event.metadata["reasoning_tokens"] == 30
    assert event.metadata["transport"] == "responses_json_schema"


def test_a_reported_zero_hit_is_a_real_zero() -> None:
    usage = SimpleNamespace(
        input_tokens=800, output_tokens=5, input_tokens_details=SimpleNamespace(cached_tokens=0)
    )
    [event] = _run(_responses(usage), StructuredTransport.RESPONSES_JSON_SCHEMA).events
    assert (event.cached_input_tokens, event.uncached_input_tokens) == (0, 800)


@pytest.mark.parametrize(
    "usage",
    [
        SimpleNamespace(prompt_tokens=100, completion_tokens=5),
        SimpleNamespace(input_tokens=100, output_tokens=5, input_tokens_details=None),
        SimpleNamespace(input_tokens=100, output_tokens=5, input_tokens_details=SimpleNamespace(cached_tokens=None)),
        SimpleNamespace(input_tokens=100, output_tokens=5, input_tokens_details=SimpleNamespace(cached_tokens="7")),
        SimpleNamespace(input_tokens=100, output_tokens=5, input_tokens_details=SimpleNamespace(cached_tokens=-1)),
        # More cached than sent cannot be right: treat the split as unknown rather than guess.
        SimpleNamespace(input_tokens=100, output_tokens=5, input_tokens_details=SimpleNamespace(cached_tokens=500)),
        None,
    ],
)
def test_missing_or_unreliable_cache_fields_are_unknown_not_zero(usage: Any) -> None:
    assert _cache_split(usage, 100) == (None, None)


def test_dict_payloads_and_missing_model_are_supported() -> None:
    usage = {"prompt_tokens": 90, "completion_tokens": 4, "prompt_cache_hit_tokens": 64}
    [event] = _run(_chat(usage, model=None), StructuredTransport.CHAT_JSON).events
    assert (event.cached_input_tokens, event.uncached_input_tokens) == (64, 26)
    assert event.metadata["response_model"] is None


def test_totals_leave_unreported_calls_out_of_the_hit_rate() -> None:
    ledger = UsageLedger()
    ledger.record(UsageEvent(provider="deepseek", operation="structured", elapsed_ms=1, input_tokens=1000, output_tokens=10, cached_input_tokens=600, uncached_input_tokens=400, metadata={"stage": "writer", "reasoning_tokens": 4}))
    ledger.record(UsageEvent(provider="deepseek", operation="structured", elapsed_ms=1, input_tokens=500, output_tokens=10, metadata={"stage": "writer"}))
    totals = ledger.totals()
    assert totals.input_tokens == 1500
    assert totals.output_tokens == 20
    assert totals.reasoning_tokens == 4  # not added into output_tokens
    assert (totals.cached_input_tokens, totals.uncached_input_tokens) == (600, 400)
    assert totals.cache_reported_input_tokens == 1000
    assert totals.cache_unreported_calls == 1
    assert totals.actual_cost_usd == 0


def test_run_kind_labels_replays_and_reports_hold_no_prompt_text() -> None:
    ledger = UsageLedger()
    with usage_run_kind("replay"):
        ledger.record(UsageEvent(provider="deepseek", operation="structured", elapsed_ms=1, input_tokens=10, metadata={"stage": "fact_check"}))
    ledger.record(UsageEvent(provider="deepseek", operation="structured", elapsed_ms=1, input_tokens=10, metadata={"stage": "fact_check", "prompt": "secret prompt"}))
    replay, plain = ledger.events
    assert replay.metadata["run_kind"] == "replay"
    assert "run_kind" not in plain.metadata
    report = usage_diagnostics(ledger)
    assert report["provider_events"][0]["run_kind"] == "replay"
    assert "prompt" not in safe_usage_event(plain)
    assert report["usage_by_stage"]["fact_check"]["cache_unreported_calls"] == 2
