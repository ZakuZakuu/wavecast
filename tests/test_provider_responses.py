import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.providers.usage import UsageLedger


class ResponseAnswer(BaseModel):
    answer: str


class FakeResponses:
    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.response


def response_client(response: SimpleNamespace) -> tuple[SimpleNamespace, FakeResponses]:
    responses = FakeResponses(response)
    return SimpleNamespace(responses=responses), responses


def response_settings() -> ProviderSettings:
    return ProviderSettings(mode="live", deepseek_api_key="test")


def test_responses_json_schema_validates_and_maps_fast_profile() -> None:
    response = SimpleNamespace(
        id="response-1",
        status="completed",
        output_text='{"answer":"ready"}',
        usage=SimpleNamespace(
            input_tokens=11,
            output_tokens=8,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
    )
    client, responses = response_client(response)
    ledger = UsageLedger()

    async def run() -> None:
        provider = DeepSeekLLMProvider(
            response_settings(), client=client, ledger=ledger, max_attempts=2
        )
        result = await provider.structured(
            "tiny test",
            ResponseAnswer,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=InferenceProfile.FAST,
            stage="fast_start",
        )
        assert result == ResponseAnswer(answer="ready")

    asyncio.run(run())
    request = responses.calls[0]
    assert request["text"]["format"]["type"] == "json_schema"  # type: ignore[index]
    assert request["text"]["format"]["schema"]["title"] == "ResponseAnswer"  # type: ignore[index]
    assert request["reasoning"] == {"effort": "none"}
    assert request["max_output_tokens"] == 2048
    assert len(responses.calls) == 1
    assert ledger.events[0].request_id == "response-1"
    assert ledger.events[0].metadata["transport"] == "responses_json_schema"
    assert ledger.events[0].metadata["stage"] == "fast_start"
    assert ledger.events[0].metadata["reasoning_tokens"] == 0


def test_responses_empty_output_records_usage_before_normalized_failure() -> None:
    response = SimpleNamespace(
        id="response-empty",
        status="completed",
        output_text="",
        usage=SimpleNamespace(
            input_tokens=13,
            output_tokens=21,
            output_tokens_details=SimpleNamespace(reasoning_tokens=17),
        ),
    )
    client, responses = response_client(response)
    ledger = UsageLedger()

    async def run() -> None:
        provider = DeepSeekLLMProvider(response_settings(), client=client, ledger=ledger)
        with pytest.raises(ProviderInvalidResponseError, match="empty structured output"):
            await provider.structured(
                "tiny test",
                ResponseAnswer,
                transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
                profile=InferenceProfile.FAST,
            )

    asyncio.run(run())
    assert len(responses.calls) == 1
    assert ledger.totals().input_tokens == 13
    assert ledger.totals().output_tokens == 21
    assert ledger.events[0].metadata["reasoning_tokens"] == 17


def test_responses_incomplete_output_is_normalized_without_retry() -> None:
    response = SimpleNamespace(
        id="response-incomplete",
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        output=[],
        usage=SimpleNamespace(input_tokens=3, output_tokens=4),
    )
    client, responses = response_client(response)
    ledger = UsageLedger()

    async def run() -> None:
        provider = DeepSeekLLMProvider(response_settings(), client=client, ledger=ledger)
        with pytest.raises(ProviderInvalidResponseError, match="incomplete"):
            await provider.structured(
                "tiny test",
                ResponseAnswer,
                transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
                profile=InferenceProfile.FAST,
            )

    asyncio.run(run())
    assert len(responses.calls) == 1
    assert ledger.totals().output_tokens == 4


def test_responses_failed_status_is_normalized_and_usage_is_kept() -> None:
    response = SimpleNamespace(
        id="response-failed",
        status="failed",
        error=SimpleNamespace(code="server_error"),
        output=[],
        usage=SimpleNamespace(input_tokens=5, output_tokens=6),
    )
    client, responses = response_client(response)
    ledger = UsageLedger()

    async def run() -> None:
        provider = DeepSeekLLMProvider(response_settings(), client=client, ledger=ledger)
        with pytest.raises(ProviderInvalidResponseError, match="failed"):
            await provider.structured(
                "tiny test",
                ResponseAnswer,
                transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
                profile=InferenceProfile.FAST,
            )

    asyncio.run(run())
    assert len(responses.calls) == 1
    assert ledger.totals().input_tokens == 5
    assert ledger.totals().output_tokens == 6
