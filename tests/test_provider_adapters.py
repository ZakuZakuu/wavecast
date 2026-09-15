import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel
from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import ProviderInvalidResponseError
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
            choices=[SimpleNamespace(message=SimpleNamespace(content=output))],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
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
        assert ledger.totals().input_tokens == 7
        assert ledger.totals().output_tokens == 3

    asyncio.run(run())


def test_deepseek_rejects_malformed_json_after_bounded_retry() -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    async def run() -> None:
        client, completions = fake_deepseek_client(["not-json", "still-not-json"])
        provider = DeepSeekLLMProvider(live_settings(), client=client, sleep=no_sleep)

        with pytest.raises(ProviderInvalidResponseError):
            await provider.structured("tiny test", StructuredAnswer)
        assert completions.calls == 2

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
