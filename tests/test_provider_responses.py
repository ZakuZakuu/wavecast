import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import (
    ProviderInvalidResponseError,
    ProviderOutputLimitError,
    ProviderSchemaValidationError,
)
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


class SequencedResponses:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.responses[len(self.calls) - 1]


def response_client(response: SimpleNamespace) -> tuple[SimpleNamespace, FakeResponses]:
    responses = FakeResponses(response)
    return SimpleNamespace(responses=responses), responses


def response_settings() -> ProviderSettings:
    return ProviderSettings(mode="live", deepseek_api_key="test")


class RaisingOutputTextResponse:
    id = "response-property"
    status = "completed"
    usage = SimpleNamespace(input_tokens=7, output_tokens=4)
    output = [
        SimpleNamespace(
            type="message",
            content=[SimpleNamespace(type="output_text", text='{"answer":"from output"}')],
        )
    ]

    @property
    def output_text(self) -> str:
        raise TypeError("SDK convenience property cannot parse compatibility payload")


def test_responses_json_schema_validates_and_maps_fast_profile() -> None:
    response = SimpleNamespace(
        id="response-1",
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text='{"answer":"ready"}')],
            )
        ],
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


@pytest.mark.parametrize(
    ("profile", "effort", "max_output_tokens"),
    [
        (InferenceProfile.FAST, "none", 2048),
        (InferenceProfile.BALANCED, "low", 4096),
        (InferenceProfile.SYNTHESIS, "none", 4096),
        (InferenceProfile.DEEP, "high", 12288),
        (InferenceProfile.CURATOR, "none", 12288),
    ],
)
def test_responses_reasoning_profiles_use_exact_request_shape(
    profile: InferenceProfile, effort: str, max_output_tokens: int
) -> None:
    response = SimpleNamespace(
        id="response-profile",
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text='{"answer":"ok"}')],
            )
        ],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client, responses = response_client(response)

    async def run() -> None:
        provider = DeepSeekLLMProvider(response_settings(), client=client, max_attempts=1)
        assert await provider.structured(
            "tiny test", ResponseAnswer,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=profile,
        ) == ResponseAnswer(answer="ok")

    asyncio.run(run())
    request = responses.calls[0]
    assert request["reasoning"] == {"effort": effort}
    assert request["max_output_tokens"] == max_output_tokens
    assert "output_config" not in request


def test_responses_output_is_source_of_truth_when_output_text_property_raises() -> None:
    client, responses = response_client(RaisingOutputTextResponse())

    async def run() -> ResponseAnswer:
        provider = DeepSeekLLMProvider(response_settings(), client=client, max_attempts=1)
        return await provider.structured(
            "tiny test",
            ResponseAnswer,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=InferenceProfile.FAST,
        )

    assert asyncio.run(run()) == ResponseAnswer(answer="from output")
    assert len(responses.calls) == 1


def test_responses_output_text_null_is_a_normalized_empty_response() -> None:
    response = {
        "id": "response-null",
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": None}]}
        ],
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }
    client, responses = response_client(response)  # type: ignore[arg-type]
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
    assert ledger.totals().input_tokens == 3


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


def test_responses_max_output_incomplete_records_usage_and_does_not_retry() -> None:
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
        with pytest.raises(ProviderOutputLimitError, match=r"incomplete \(max_output_tokens\)"):
            await provider.structured(
                "tiny test",
                ResponseAnswer,
                transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
                profile=InferenceProfile.SYNTHESIS,
            )

    asyncio.run(run())
    assert len(responses.calls) == 1
    assert ledger.events[0].request_id == "response-incomplete"
    assert ledger.totals().input_tokens == 3
    assert ledger.totals().output_tokens == 4


def test_responses_malformed_json_keeps_bounded_retry_behavior() -> None:
    responses = SequencedResponses(
        [
            SimpleNamespace(
                id="response-malformed",
                status="completed",
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", text="not-json")],
                    )
                ],
                usage=SimpleNamespace(input_tokens=2, output_tokens=1),
            ),
            SimpleNamespace(
                id="response-recovered",
                status="completed",
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", text='{"answer":"ok"}')],
                    )
                ],
                usage=SimpleNamespace(input_tokens=2, output_tokens=1),
            ),
        ]
    )
    client = SimpleNamespace(responses=responses)
    ledger = UsageLedger()

    async def run() -> None:
        provider = DeepSeekLLMProvider(response_settings(), client=client, ledger=ledger)
        assert await provider.structured(
            "tiny test",
            ResponseAnswer,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=InferenceProfile.SYNTHESIS,
        ) == ResponseAnswer(answer="ok")

    asyncio.run(run())
    assert len(responses.calls) == 2
    assert len(ledger.events) == 2


def test_responses_schema_validation_error_is_typed() -> None:
    response = SimpleNamespace(
        id="response-schema-invalid",
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="not-json")],
            )
        ],
        usage=SimpleNamespace(input_tokens=2, output_tokens=1),
    )
    client, responses = response_client(response)
    ledger = UsageLedger()

    async def run() -> None:
        provider = DeepSeekLLMProvider(response_settings(), client=client, ledger=ledger)
        with pytest.raises(ProviderSchemaValidationError, match="did not match"):
            await provider.structured(
                "tiny test",
                ResponseAnswer,
                transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
                profile=InferenceProfile.FAST,
            )

    asyncio.run(run())
    assert len(responses.calls) == 1


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
