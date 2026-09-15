"""DeepSeek inference adapter; prompts and agent workflow deliberately stay outside it."""

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, Self

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from .config import ProviderSettings
from .errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    is_retryable,
)
from .usage import UsageEvent, UsageLedger


class DeepSeekLLMProvider:
    def __init__(
        self,
        settings: ProviderSettings,
        *,
        ledger: UsageLedger | None = None,
        client: Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.ledger = ledger or UsageLedger()
        self.sleep = sleep
        self._owns_client = client is None
        self.client: Any = client or AsyncOpenAI(
            api_key=settings.credential_for("deepseek"),
            base_url=settings.deepseek_base_url,
            timeout=settings.timeout_seconds,
            max_retries=0,
        )

    async def structured(self, prompt: str, output_type: type[BaseModel]) -> BaseModel:
        schema = json.dumps(output_type.model_json_schema(), ensure_ascii=False)
        messages = [
            {
                "role": "system",
                "content": (
                    "Return only a JSON object that validates against this JSON Schema. "
                    f"Schema: {schema}"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        last_failure: ProviderError | None = None
        for attempt in range(self.settings.max_attempts):
            started_at = perf_counter()
            try:
                response = await self.client.chat.completions.create(
                    model=self.settings.deepseek_model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                if not content:
                    raise ProviderInvalidResponseError("deepseek returned empty structured output")
                try:
                    parsed = output_type.model_validate_json(content)
                except ValidationError as error:
                    raise ProviderInvalidResponseError(
                        "deepseek structured output did not match the requested schema"
                    ) from error
                self._record(response, int((perf_counter() - started_at) * 1000))
                return parsed
            except ProviderError as error:
                last_failure = error
            except AuthenticationError as error:
                last_failure = ProviderAuthenticationError("deepseek authentication failed")
                last_failure.__cause__ = error
            except RateLimitError as error:
                last_failure = ProviderRateLimitError("deepseek rate limited the request")
                last_failure.__cause__ = error
            except APITimeoutError as error:
                last_failure = ProviderTimeoutError("deepseek timed out")
                last_failure.__cause__ = error
            except APIConnectionError as error:
                last_failure = ProviderUnavailableError("deepseek is temporarily unavailable")
                last_failure.__cause__ = error
            except APIStatusError as error:
                if error.status_code in {401, 403}:
                    last_failure = ProviderAuthenticationError("deepseek authentication failed")
                elif error.status_code == 429:
                    last_failure = ProviderRateLimitError("deepseek rate limited the request")
                elif 500 <= error.status_code < 600:
                    last_failure = ProviderUnavailableError("deepseek is temporarily unavailable")
                else:
                    last_failure = ProviderInvalidResponseError(
                        f"deepseek request failed with HTTP {error.status_code}"
                    )
                last_failure.__cause__ = error
            except (AttributeError, IndexError, TypeError) as error:
                last_failure = ProviderInvalidResponseError(
                    "deepseek returned an incomplete completion payload"
                )
                last_failure.__cause__ = error
            if last_failure is None:
                raise AssertionError("provider error must be set")
            retry_invalid_output = isinstance(last_failure, ProviderInvalidResponseError)
            if attempt == self.settings.max_attempts - 1 or (
                not retry_invalid_output and not is_retryable(last_failure)
            ):
                raise last_failure
            await self.sleep(0.25 * (2**attempt))
        raise AssertionError("bounded structured loop must return or raise")

    async def aclose(self) -> None:
        if not self._owns_client:
            return
        close = getattr(self.client, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    def _record(self, response: Any, elapsed_ms: int) -> None:
        usage = getattr(response, "usage", None)
        self.ledger.record(
            UsageEvent(
                provider="deepseek",
                operation="structured",
                request_id=getattr(response, "_request_id", None),
                elapsed_ms=elapsed_ms,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                metadata={"model": self.settings.deepseek_model},
            )
        )
