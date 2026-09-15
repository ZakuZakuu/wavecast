"""Deterministic search routing. Agent reasoning never chooses a vendor implicitly."""

from enum import StrEnum
from typing import Protocol

from .contracts import SearchResult
from .errors import ProviderUnavailableError


class SearchIntent(StrEnum):
    DISCOVERY = "discovery"
    RESEARCH = "research"
    EXACT = "exact"


class SearchCallable(Protocol):
    async def search(
        self, query: str, *, limit: int = 5, stage: str | None = None
    ) -> list[SearchResult]: ...


class SearchRouter:
    def __init__(self, *, discovery: SearchCallable, research: SearchCallable) -> None:
        self.discovery = discovery
        self.research = research

    async def search(
        self, intent: SearchIntent, query: str, *, limit: int = 5
    ) -> list[SearchResult]:
        if intent is SearchIntent.DISCOVERY:
            return await self.discovery.search(query, limit=limit)
        if intent is SearchIntent.RESEARCH:
            return await self.research.search(query, limit=limit)
        raise ProviderUnavailableError("exact search is reserved for a future Serper adapter")
