import asyncio
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError
from pydantic import BaseModel
from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import ProviderInvalidResponseError, ProviderTimeoutError
from wavecast.providers.search import ExaSearchProvider, TavilySearchProvider
from wavecast.providers.usage import UsageLedger


class StructuredAnswer(BaseModel):
    answer: str


class FakeCompletions:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls = 0

    async def create(self, **_kwargs: object) -> SimpleNamespace:
        output = self.outputs[self.calls]
        self.calls += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=output), finish_reason="stop"
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=7,
                completion_tokens=3,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
            ),
            _request_id="deepseek-request",
        )


def fake_deepseek_client(outputs: list[str]) -> tuple[SimpleNamespace, FakeCompletions]:
    completions = FakeCompletions(outputs)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def live_settings() -> ProviderSettings:
    return ProviderSettings(
        mode="live", deepseek_api_key="test", exa_api_key="test", tavily_api_key="test"
    )


def test_deepseek_parses_typed_json_and_records_token_usage() -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    async def run() -> None:
        client, completions = fake_deepseek_client(['{"missing": true}', '{"answer": "ok"}'])
        ledger = UsageLedger()
        provider = DeepSeekLLMProvider(
            live_settings(), client=client, ledger=ledger, sleep=no_sleep
        )

        result = await provider.structured("tiny test", StructuredAnswer)

        assert result == StructuredAnswer(answer="ok")
        assert completions.calls == 2
        assert ledger.totals().input_tokens == 14
        assert ledger.totals().output_tokens == 6

    asyncio.run(run())


def test_deepseek_rejects_malformed_json_after_bounded_retry() -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    async def run() -> None:
        client, completions = fake_deepseek_client(["not-json", "still-not-json"])
        ledger = UsageLedger()
        provider = DeepSeekLLMProvider(
            live_settings(), client=client, ledger=ledger, sleep=no_sleep
        )

        with pytest.raises(ProviderInvalidResponseError):
            await provider.structured("tiny test", StructuredAnswer)
        assert completions.calls == 2
        assert ledger.totals().input_tokens == 14
        assert ledger.totals().output_tokens == 6
        assert all(event.metadata["finish_reason"] == "stop" for event in ledger.events)
        assert all(event.metadata["reasoning_tokens"] == 2 for event in ledger.events)

    asyncio.run(run())


def test_deepseek_records_usage_before_empty_content_is_rejected() -> None:
    async def run() -> None:
        client, completions = fake_deepseek_client([""])
        ledger = UsageLedger()
        settings = ProviderSettings(
            mode="live", deepseek_api_key="test", deepseek_timeout_seconds=20
        )
        provider = DeepSeekLLMProvider(
            settings, client=client, ledger=ledger, max_attempts=1
        )

        with pytest.raises(ProviderInvalidResponseError):
            await provider.structured("tiny test", StructuredAnswer)

        assert completions.calls == 1
        assert ledger.totals().input_tokens == 7
        assert ledger.totals().output_tokens == 3
        assert ledger.events[0].metadata == {
            "model": "deepseek-flash",
            "transport": "chat_json",
            "finish_reason": "stop",
            "reasoning_tokens": 2,
        }

    asyncio.run(run())


def test_deepseek_uses_its_own_timeout_and_bounds_one_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    openai_options: dict[str, object] = {}
    completion_options: list[dict[str, object]] = []

    class CapturingCompletions:
        async def create(self, **kwargs: object) -> SimpleNamespace:
            completion_options.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"answer": "ok"}'))],
                usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
                _request_id="deepseek-request",
            )

    class CapturingOpenAI:
        def __init__(self, **kwargs: object) -> None:
            openai_options.update(kwargs)
            self.chat = SimpleNamespace(completions=CapturingCompletions())

    monkeypatch.setattr("wavecast.providers.deepseek.AsyncOpenAI", CapturingOpenAI)
    settings = ProviderSettings(
        mode="live",
        deepseek_api_key="test",
        timeout_seconds=20,
        deepseek_timeout_seconds=90,
        deepseek_max_output_tokens=4096,
        deepseek_deep_max_output_tokens=12288,
    )

    async def run() -> None:
        provider = DeepSeekLLMProvider(settings)
        assert await provider.structured("tiny test", StructuredAnswer) == StructuredAnswer(answer="ok")

    asyncio.run(run())
    assert openai_options["timeout"] == 90
    assert completion_options[0]["max_tokens"] == 4096
    assert len(completion_options) == 1


def test_deepseek_timeout_remains_normalized_without_an_extra_attempt() -> None:
    class TimeoutCompletions:
        def __init__(self) -> None:
            self.calls = 0

        async def create(self, **_kwargs: object) -> SimpleNamespace:
            self.calls += 1
            raise APITimeoutError(httpx.Request("POST", "https://api.deepseek.com/chat/completions"))

    async def run() -> None:
        completions = TimeoutCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        settings = ProviderSettings(
            mode="live", deepseek_api_key="test", deepseek_timeout_seconds=90
        )
        provider = DeepSeekLLMProvider(settings, client=client, max_attempts=1)

        with pytest.raises(ProviderTimeoutError):
            await provider.structured("tiny test", StructuredAnswer)
        assert completions.calls == 1

    asyncio.run(run())


def test_exa_normalizes_results_cost_and_request_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.exa.ai/search")
        payload = json_loads(request.content)
        assert payload["type"] == "auto"
        assert payload["contents"] == {"text": False, "highlights": True}
        return httpx.Response(
            200,
            json={
                "requestId": "exa-request",
                "resolvedSearchType": "neural",
                "costDollars": {"total": 0.012},
                "results": [
                    {
                        "id": "exa-id",
                        "title": "A discovery",
                        "url": "https://example.test/discovery",
                        "highlights": ["Useful highlight"],
                        "publishedDate": "2005-01-01",
                        "score": 0.8,
                    }
                ],
            },
        )

    async def run() -> None:
        ledger = UsageLedger()
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = ExaSearchProvider(live_settings(), client=client, ledger=ledger)
        results = await provider.search("music discovery", limit=1)
        await client.aclose()

        assert results[0].content == "Useful highlight"
        assert results[0].request_id == "exa-request"
        assert results[0].published_at == "2005-01-01"
        assert ledger.totals().actual_cost_usd == 0.012
        assert ledger.events[0].metadata["resolved_search_type"] == "neural"

    asyncio.run(run())


def test_tavily_normalizes_results_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json_loads(request.content)
        assert payload["topic"] == "general"
        assert payload["search_depth"] == "advanced"
        assert payload["include_answer"] is False
        assert payload["include_raw_content"] is False
        assert payload["include_usage"] is True
        return httpx.Response(
            200,
            json={
                "request_id": "tavily-request",
                "usage": {"credits": 2},
                "results": [
                    {
                        "title": "Evidence",
                        "url": "https://example.test/evidence",
                        "content": "Relevant evidence",
                        "score": 0.7,
                    }
                ],
            },
        )

    async def run() -> None:
        ledger = UsageLedger()
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = TavilySearchProvider(live_settings(), client=client, ledger=ledger)
        results = await provider.search("music evidence", limit=1, search_depth="advanced")
        await client.aclose()

        assert results[0].provider == "tavily"
        assert results[0].content == "Relevant evidence"
        assert ledger.totals().search_credits == 2
        assert ledger.events[0].metadata["search_depth"] == "advanced"

    asyncio.run(run())


def json_loads(content: bytes) -> dict[str, object]:
    import json

    loaded = json.loads(content)
    assert isinstance(loaded, dict)
    return loaded
