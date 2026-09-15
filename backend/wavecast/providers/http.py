"""Bounded retry and error normalization for HTTP-only provider adapters."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .errors import (
    ProviderAuthenticationError,
    ProviderBudgetExceededError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    is_retryable,
)


def normalize_http_error(provider: str, status_code: int, detail: str = "") -> ProviderError:
    message = f"{provider} request failed with HTTP {status_code}"
    if detail:
        message = f"{message}: {detail[:240]}"
    if status_code in {401, 403}:
        return ProviderAuthenticationError(message)
    if status_code == 402 or (provider.lower() == "tavily" and status_code in {432, 433}):
        return ProviderBudgetExceededError(message)
    if status_code == 429:
        return ProviderRateLimitError(message)
    if 500 <= status_code < 600:
        return ProviderUnavailableError(message)
    return ProviderInvalidResponseError(message)


async def request_json(
    client: httpx.AsyncClient,
    *,
    provider: str,
    method: str,
    url: str,
    max_attempts: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    **kwargs: Any,
) -> tuple[dict[str, Any], httpx.Response]:
    for attempt in range(max_attempts):
        try:
            response = await client.request(method, url, **kwargs)
            if response.is_error:
                raise normalize_http_error(provider, response.status_code, response.text)
            try:
                payload = response.json()
            except ValueError as error:
                raise ProviderInvalidResponseError(f"{provider} returned malformed JSON") from error
            if not isinstance(payload, dict):
                raise ProviderInvalidResponseError(
                    f"{provider} returned a non-object JSON response"
                )
            return payload, response
        except httpx.TimeoutException as error:
            failure: ProviderError = ProviderTimeoutError(f"{provider} timed out")
            failure.__cause__ = error
        except httpx.RequestError as error:
            failure = ProviderUnavailableError(f"{provider} transport failed")
            failure.__cause__ = error
        except ProviderError as error:
            failure = error
        if not is_retryable(failure) or attempt == max_attempts - 1:
            raise failure
        await sleep(0.25 * (2**attempt))
    raise AssertionError("bounded request loop must return or raise")
