"""Exa and Tavily search adapters normalized to the Wavecast search contract."""

from time import perf_counter
from typing import Any, Literal

import httpx

from .config import ProviderSettings
from .contracts import SearchResult
from .http import request_json
from .usage import UsageEvent, UsageLedger

SearchDepth = Literal["basic", "advanced"]


class ExaSearchProvider:
    endpoint = "https://api.exa.ai/search"

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        ledger: UsageLedger | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.ledger = ledger or UsageLedger()
        self.client = client or httpx.AsyncClient(timeout=settings.timeout_seconds)
        self._owns_client = client is None
        self.api_key = settings.credential_for("exa")

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        started_at = perf_counter()
        payload, response = await request_json(
            self.client,
            provider="exa",
            method="POST",
            url=self.endpoint,
            max_attempts=self.settings.max_attempts,
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "query": query,
                "type": "auto",
                "numResults": limit,
                # Highlights offer downstream reasoning context without requesting full bodies.
                "contents": {"text": False, "highlights": True},
            },
        )
        request_id = _optional_string(payload.get("requestId")) or response.headers.get(
            "x-request-id"
        )
        result_items = payload.get("results", [])
        if not isinstance(result_items, list):
            result_items = []
        normalized = [
            self._normalize(item, query, request_id)
            for item in result_items
            if isinstance(item, dict)
        ]
        cost = payload.get("costDollars")
        actual_cost = cost.get("total") if isinstance(cost, dict) else None
        self.ledger.record(
            UsageEvent(
                provider="exa",
                operation="search",
                request_id=request_id,
                elapsed_ms=int((perf_counter() - started_at) * 1000),
                search_queries=1,
                actual_cost_usd=actual_cost if isinstance(actual_cost, (int, float)) else None,
                metadata={
                    "resolved_search_type": payload.get("resolvedSearchType"),
                    "result_count": len(normalized),
                },
            )
        )
        return normalized

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    @staticmethod
    def _normalize(item: dict[str, Any], query: str, request_id: str | None) -> SearchResult:
        highlights = item.get("highlights")
        highlight_text = (
            " ".join(value for value in highlights if isinstance(value, str))
            if isinstance(highlights, list)
            else ""
        )
        content = (
            _optional_string(item.get("text"))
            or highlight_text
            or _optional_string(item.get("summary"))
        )
        return SearchResult(
            title=_optional_string(item.get("title")) or "Untitled Exa result",
            url=_optional_string(item.get("url")) or "",
            snippet=highlight_text or content or "",
            content=content,
            published_at=_optional_string(item.get("publishedDate")),
            provider="exa",
            query=query,
            score=_optional_float(item.get("score")),
            request_id=request_id,
            metadata={"result_id": item.get("id")} if item.get("id") else {},
        )


class TavilySearchProvider:
    endpoint = "https://api.tavily.com/search"

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        ledger: UsageLedger | None = None,
        client: httpx.AsyncClient | None = None,
        search_depth: SearchDepth = "basic",
    ) -> None:
        self.settings = settings
        self.ledger = ledger or UsageLedger()
        self.client = client or httpx.AsyncClient(timeout=settings.timeout_seconds)
        self._owns_client = client is None
        self.api_key = settings.credential_for("tavily")
        self.search_depth = search_depth

    async def search(
        self, query: str, *, limit: int = 5, search_depth: SearchDepth | None = None
    ) -> list[SearchResult]:
        depth = search_depth or self.search_depth
        started_at = perf_counter()
        payload, response = await request_json(
            self.client,
            provider="tavily",
            method="POST",
            url=self.endpoint,
            max_attempts=self.settings.max_attempts,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "query": query,
                "topic": "general",
                "search_depth": depth,
                "include_answer": False,
                "include_raw_content": False,
                "max_results": limit,
            },
        )
        request_id = _optional_string(payload.get("request_id")) or response.headers.get(
            "x-request-id"
        )
        result_items = payload.get("results", [])
        if not isinstance(result_items, list):
            result_items = []
        normalized = [
            self._normalize(item, query, request_id)
            for item in result_items
            if isinstance(item, dict)
        ]
        usage = payload.get("usage")
        credits = usage.get("credits") if isinstance(usage, dict) else None
        self.ledger.record(
            UsageEvent(
                provider="tavily",
                operation="search",
                request_id=request_id,
                elapsed_ms=int((perf_counter() - started_at) * 1000),
                search_queries=1,
                search_credits=float(credits) if isinstance(credits, (int, float)) else None,
                metadata={"search_depth": depth, "result_count": len(normalized)},
            )
        )
        return normalized

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    @staticmethod
    def _normalize(item: dict[str, Any], query: str, request_id: str | None) -> SearchResult:
        content = _optional_string(item.get("content"))
        return SearchResult(
            title=_optional_string(item.get("title")) or "Untitled Tavily result",
            url=_optional_string(item.get("url")) or "",
            snippet=content or "",
            content=content,
            published_at=_optional_string(item.get("published_date")),
            provider="tavily",
            query=query,
            score=_optional_float(item.get("score")),
            request_id=request_id,
        )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None
