"""Ark adapter: request shape, single attempt, usage and cost on every outcome."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIConnectionError, APIStatusError
from pydantic import BaseModel, ConfigDict
from wavecast.providers import ark as ark_module
from wavecast.providers.ark import ArkLLMProvider
from wavecast.providers.ark_pricing import estimate_cost
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderIncompleteResponseError,
    ProviderInvalidResponseError,
    ProviderOutputLimitError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderSchemaValidationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.providers.strict_schema import StrictSchemaUnsupportedError
from wavecast.providers.usage import UsageLedger, usage_diagnostics

LITE = "doubao-seed-2-1-lite-260915"
PRO = "doubao-seed-2-1-pro-260915"
FLASH = "deepseek-v4-1-flash-260910"


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


def settings(**overrides: Any) -> ProviderSettings:
    return ProviderSettings(**{"mode": "live", "ark_api_key": "test", **overrides})


def response(
    content: str | None = '{"answer": "ok"}',
    *,
    finish_reason: str | None = "stop",
    usage: Any = "default",
    model: str = LITE,
) -> SimpleNamespace:
    if usage == "default":
        usage = SimpleNamespace(
            prompt_tokens=2171,
            completion_tokens=478,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
        )
    return SimpleNamespace(
        id="req-1",
        model=model,
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason, message=SimpleNamespace(content=content)
            )
        ],
        usage=usage,
    )


class FakeCompletions:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if callable(self.outcome):
            return await self.outcome()
        return self.outcome


def make(outcome: Any, *, model: str = LITE, **overrides: Any) -> tuple[ArkLLMProvider, FakeCompletions, UsageLedger]:
    completions = FakeCompletions(outcome)
    ledger = UsageLedger()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = ArkLLMProvider(
        settings(**overrides), model=model, role="writer", ledger=ledger, client=client
    )
    return provider, completions, ledger


def status_error(code: int) -> APIStatusError:
    request = httpx.Request("POST", "https://ark.test/chat/completions")
    return APIStatusError("boom", response=httpx.Response(code, request=request), body=None)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_request_uses_the_verified_chat_strict_shape() -> None:
    provider, completions, _ = make(response())

    result = run(
        provider.structured(
            "write json",
            Answer,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=InferenceProfile.DEEP,
        )
    )

    assert result == Answer(answer="ok")
    (call,) = completions.calls
    assert call["model"] == LITE
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True
    assert call["response_format"]["json_schema"]["name"] == "Answer"
    assert call["response_format"]["json_schema"]["schema"] == {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    assert call["temperature"] == 0.7
    assert call["stream"] is False
    assert call["max_completion_tokens"] == 12288  # DEEP: the longer limit
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning" not in call and "reasoning_effort" not in call and "input" not in call
    assert call["messages"][-1] == {"role": "user", "content": "write json"}


def test_every_profile_disables_thinking_and_ignores_reasoning_effort() -> None:
    for profile in InferenceProfile:
        provider, completions, _ = make(response())
        run(provider.structured("p", Answer, profile=profile))
        assert completions.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
        assert "reasoning" not in completions.calls[0]


def test_sdk_retries_are_off_and_the_credential_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(ark_module, "AsyncOpenAI", FakeClient)
    ArkLLMProvider(settings(), model=LITE)
    assert captured["max_retries"] == 0
    assert captured["base_url"] == "https://ark.cn-beijing.volces.com/api/v3"
    assert captured["api_key"] == "test"

    with pytest.raises(ProviderConfigurationError):
        ArkLLMProvider(ProviderSettings(mode="live"), model=LITE)
    with pytest.raises(ValueError):
        ArkLLMProvider(settings(), model="")


def test_success_records_tokens_and_a_cny_estimate_not_usd() -> None:
    provider, _, ledger = make(response())

    run(provider.structured("p", Answer, stage="writer"))

    (event,) = ledger.events
    assert (event.provider, event.input_tokens, event.output_tokens) == ("ark", 2171, 478)
    assert event.cached_input_tokens == 0
    assert event.actual_cost_usd is None and event.estimated_cost_usd is None
    assert event.metadata["estimated_cost_cny"] == 0.0030274  # matches the experiment receipt
    assert event.metadata["cost_basis"] == "usage_and_known_cache"
    assert event.metadata["price_version"]
    assert event.metadata["stage"] == "writer"
    assert event.metadata["usage_known"] is True and event.metadata["outcome"] == "ok"


def test_the_diagnostic_projection_keeps_cny_and_outcome_fields() -> None:
    provider, _, ledger = make(response())
    run(provider.structured("p", Answer, stage="writer"))

    diagnostics = usage_diagnostics(ledger)

    (projected,) = diagnostics["provider_events"]
    assert projected["estimated_cost_cny"] == 0.0030274
    assert projected["cost_basis"] == "usage_and_known_cache"
    assert projected["role"] == "writer" and projected["outcome"] == "ok"
    assert projected["request_dispatched"] is True and projected["usage_known"] is True
    assert diagnostics["usage"]["estimated_cost_cny"] == 0.0030274
    assert diagnostics["usage"]["actual_cost_usd"] == 0
    assert diagnostics["usage"]["cost_unknown_calls"] == 0


@pytest.mark.parametrize(
    ("content", "finish", "error"),
    [
        ('{"answer": "ok", "subject_note": "x"}', "stop", ProviderSchemaValidationError),
        ("not json", "stop", ProviderSchemaValidationError),
        ('{"answer": "o', "length", ProviderOutputLimitError),
        ('{"answer": "ok"}', "content_filter", ProviderIncompleteResponseError),
        ('{"answer": "ok"}', None, ProviderIncompleteResponseError),
        ("", "stop", ProviderInvalidResponseError),
        (None, "stop", ProviderInvalidResponseError),
    ],
)
def test_answers_the_application_rejects_still_record_the_real_tokens_and_are_not_resent(
    content: str | None, finish: str | None, error: type[Exception]
) -> None:
    provider, completions, ledger = make(response(content, finish_reason=finish))

    with pytest.raises(error):
        run(provider.structured("p", Answer))

    assert len(completions.calls) == 1  # never resent, never downgraded
    (event,) = ledger.events
    assert (event.input_tokens, event.output_tokens) == (2171, 478)
    assert event.metadata["estimated_cost_cny"] == 0.0030274
    assert event.metadata["outcome"] != "ok"


def test_missing_usage_makes_the_cost_unknown_not_zero() -> None:
    provider, _, ledger = make(response(usage=None))

    run(provider.structured("p", Answer))

    (event,) = ledger.events
    assert event.input_tokens is None and event.output_tokens is None
    assert event.metadata["usage_known"] is False
    assert event.metadata["estimated_cost_cny"] is None
    assert event.metadata["cost_basis"] == "usage_missing"
    totals = usage_diagnostics(ledger)["usage"]
    assert totals["estimated_cost_cny"] == 0 and totals["cost_unknown_calls"] == 1


def test_a_cache_split_that_is_not_reported_prices_the_input_in_full() -> None:
    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=100)
    provider, _, ledger = make(response(usage=usage))

    run(provider.structured("p", Answer))

    (event,) = ledger.events
    assert event.cached_input_tokens is None
    assert event.metadata["cost_basis"] == "cache_split_unreported_upper_bound"
    assert event.metadata["estimated_cost_cny"] == pytest.approx(0.00107)


def test_cached_tokens_are_priced_at_the_cached_rate() -> None:
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=100,
        prompt_tokens_details=SimpleNamespace(cached_tokens=600),
    )
    provider, _, ledger = make(response(usage=usage, model=PRO), model=PRO)

    run(provider.structured("p", Answer))

    (event,) = ledger.events
    assert (event.cached_input_tokens, event.uncached_input_tokens) == (600, 400)
    assert event.metadata["estimated_cost_cny"] == pytest.approx(0.00612)


def test_pro_matches_the_experiment_receipt() -> None:
    assert estimate_cost(PRO, 1257, 1128, 0).cny == 0.041382


def test_flash_has_a_price_range_not_a_permanent_constant() -> None:
    estimate = estimate_cost(FLASH, 1107, 1303, 0)

    assert estimate.cny is None
    assert estimate.cny_low == 0.006319  # the idle-time receipt
    assert estimate.cny_high == pytest.approx(0.012638)  # the peak rate
    assert estimate.basis == "time_dependent_price"
    provider, _, ledger = make(response(model=FLASH), model=FLASH)
    run(provider.structured("p", Answer))
    totals = usage_diagnostics(ledger)["usage"]
    assert totals["estimated_cost_cny"] == 0
    assert totals["estimated_cost_cny_low"] > 0 and totals["estimated_cost_cny_high"] > totals["estimated_cost_cny_low"]
    assert totals["cost_unknown_calls"] == 0


def test_an_unknown_model_has_an_unknown_cost() -> None:
    estimate = estimate_cost("some-future-model-270101", 10, 10, 0)
    assert (estimate.cny, estimate.cny_low, estimate.cny_high) == (None, None, None)
    assert estimate.basis == "unknown_model"


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (401, ProviderAuthenticationError),
        (403, ProviderPermissionError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
        (503, ProviderUnavailableError),
        (400, ProviderRequestError),
        (404, ProviderRequestError),
        (402, ProviderRequestError),  # no balance-specific mapping is invented
    ],
)
def test_http_failures_are_classified_coarsely_and_sent_once(code: int, error: type[Exception]) -> None:
    provider, completions, ledger = make(status_error(code))

    with pytest.raises(error):
        run(provider.structured("p", Answer, stage="writer"))

    assert len(completions.calls) == 1
    (event,) = ledger.events
    assert event.metadata["outcome"] == "http_error" and event.metadata["http_status"] == code
    assert event.metadata["request_dispatched"] is True and event.metadata["response_received"] is True
    assert event.input_tokens is None and event.metadata["usage_known"] is False
    assert event.metadata["estimated_cost_cny"] is None and event.metadata["cost_basis"] == "no_receipt"
    assert usage_diagnostics(ledger)["usage"]["cost_unknown_calls"] == 1


def test_auth_errors_stay_distinguishable_but_share_a_base() -> None:
    assert issubclass(ProviderPermissionError, ProviderAuthenticationError)
    assert ProviderPermissionError is not ProviderAuthenticationError


def test_a_timeout_is_one_attempt_with_an_unknown_cost() -> None:
    async def slow() -> Any:
        await asyncio.sleep(5)

    provider, completions, ledger = make(slow, ark_timeout_seconds=0.05)

    with pytest.raises(ProviderTimeoutError):
        run(provider.structured("p", Answer))

    assert len(completions.calls) == 1
    (event,) = ledger.events
    assert event.metadata["outcome"] == "timeout"
    assert event.metadata["request_dispatched"] is True and event.metadata["response_received"] is False
    assert event.metadata["estimated_cost_cny"] is None and event.metadata["usage_known"] is False


def test_a_connection_failure_is_unavailable_and_not_retried() -> None:
    error = APIConnectionError(request=httpx.Request("POST", "https://ark.test"))
    provider, completions, ledger = make(error)

    with pytest.raises(ProviderUnavailableError):
        run(provider.structured("p", Answer))

    assert len(completions.calls) == 1
    assert ledger.events[0].metadata["outcome"] == "connection_error"


def test_cancellation_propagates_and_leaves_an_unknown_cost_event() -> None:
    async def scenario() -> tuple[UsageLedger, FakeCompletions]:
        started = asyncio.Event()

        async def hang() -> Any:
            started.set()
            await asyncio.sleep(30)

        provider, completions, ledger = make(hang)
        task = asyncio.create_task(provider.structured("p", Answer))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return ledger, completions

    ledger, completions = run(scenario())

    assert len(completions.calls) == 1
    (event,) = ledger.events
    assert event.metadata["outcome"] == "cancelled"
    assert event.metadata["request_dispatched"] is True and event.metadata["response_received"] is False
    assert event.metadata["estimated_cost_cny"] is None and event.metadata["usage_known"] is False


def test_an_unsupported_schema_fails_before_any_request_or_event() -> None:
    class FreeForm(BaseModel):
        data: dict[str, str]

    provider, completions, ledger = make(response())

    with pytest.raises(StrictSchemaUnsupportedError):
        run(provider.structured("p", FreeForm))

    assert completions.calls == [] and ledger.events == []


def test_the_ledger_never_carries_prompts_or_answers() -> None:
    provider, _, ledger = make(
        response('{"answer": "SECRET-ANSWER"}'), ark_api_key="KEY-do-not-log"
    )
    run(provider.structured("SECRET-PROMPT", Answer))

    dumped = str(usage_diagnostics(ledger)) + str(ledger.events)
    assert "SECRET" not in dumped and "KEY-do-not-log" not in dumped
