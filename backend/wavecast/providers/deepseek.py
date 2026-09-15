"""DeepSeek inference adapter; prompts and agent workflow deliberately stay outside it."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from time import perf_counter
from typing import Any

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
from .profiles import InferenceProfile, StructuredTransport, policy_for
from .usage import UsageEvent, UsageLedger


class DeepSeekLLMProvider:
    def __init__(
        self,
        settings: ProviderSettings,
        *,
        ledger: UsageLedger | None = None,
        client: Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_attempts: int | None = None,
    ) -> None:
        self.settings = settings
        self.ledger = ledger or UsageLedger()
        self.sleep = sleep
        self.max_attempts = max_attempts if max_attempts is not None else settings.max_attempts
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self._owns_client = client is None
        self.client: Any = client or AsyncOpenAI(
            api_key=settings.credential_for("deepseek"),
            base_url=settings.deepseek_base_url,
            # Per-profile asyncio.wait_for calls enforce the actual budget.  The
            # transport cap must be no shorter than the bounded DEEP profile.
            timeout=max(
                settings.deepseek_timeout_seconds, settings.deepseek_deep_timeout_seconds
            ),
            max_retries=0,
        )

    async def structured(
        self,
        prompt: str,
        output_type: type[BaseModel],
        *,
        transport: StructuredTransport = StructuredTransport.CHAT_JSON,
        profile: InferenceProfile = InferenceProfile.BALANCED,
        stage: str | None = None,
    ) -> BaseModel:
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
        policy = policy_for(
            profile,
            default_timeout_seconds=self.settings.deepseek_timeout_seconds,
            deep_timeout_seconds=self.settings.deepseek_deep_timeout_seconds,
            default_max_output_tokens=self.settings.deepseek_max_output_tokens,
            default_max_attempts=self.max_attempts,
        )
        if transport is StructuredTransport.CHAT_JSON:
            policy = replace(policy, transport=transport, reasoning_effort=None)
        attempt_limit = 1 if profile is InferenceProfile.FAST else self.max_attempts
        last_failure: ProviderError | None = None
        for attempt in range(attempt_limit):
            started_at = perf_counter()
            try:
                response = await asyncio.wait_for(
                    self._request(
                        messages=messages,
                        schema=output_type.model_json_schema(),
                        output_type=output_type,
                        policy=policy,
                    ),
                    timeout=policy.timeout_seconds,
                )
                elapsed_ms = int((perf_counter() - started_at) * 1000)
                self._record(response, elapsed_ms, transport=transport, stage=stage)
                content = self._response_content(response, transport)
                if not content:
                    raise ProviderInvalidResponseError("deepseek returned empty structured output")
                try:
                    parsed = output_type.model_validate_json(content)
                except ValidationError as error:
                    raise ProviderInvalidResponseError(
                        "deepseek structured output did not match the requested schema"
                    ) from error
                return parsed
            except ProviderError as error:
                last_failure = error
            except AuthenticationError as error:
                last_failure = ProviderAuthenticationError("deepseek authentication failed")
                last_failure.__cause__ = error
            except RateLimitError as error:
                last_failure = ProviderRateLimitError("deepseek rate limited the request")
                last_failure.__cause__ = error
            except TimeoutError as error:
                last_failure = ProviderTimeoutError("deepseek timed out")
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
            if last_failure is None:
                raise AssertionError("provider error must be set")
            retry_invalid_output = isinstance(last_failure, ProviderInvalidResponseError)
            if attempt == attempt_limit - 1 or (
                not retry_invalid_output and not is_retryable(last_failure)
            ):
                raise last_failure
            await self.sleep(0.25 * (2**attempt))
        raise AssertionError("bounded structured loop must return or raise")

    async def _request(
        self,
        *,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        output_type: type[BaseModel],
        policy: Any,
    ) -> Any:
        if policy.transport is StructuredTransport.CHAT_JSON:
            return await self.client.chat.completions.create(
                model=self.settings.deepseek_model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=policy.max_output_tokens,
            )
        kwargs: dict[str, Any] = {
            "model": self.settings.deepseek_model,
            "input": messages,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": output_type.__name__,
                    "schema": schema,
                }
            },
            "max_output_tokens": policy.max_output_tokens,
        }
        if policy.reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": policy.reasoning_effort}
        return await self.client.responses.create(**kwargs)

    @staticmethod
    def _response_content(response: Any, transport: StructuredTransport) -> str | None:
        if transport is StructuredTransport.CHAT_JSON:
            choices = _field(response, "choices", [])
            first_choice = choices[0] if isinstance(choices, (list, tuple)) and choices else None
            content = _field(_field(first_choice, "message"), "content")
            return content if isinstance(content, str) else None

        status = _field(response, "status", "completed")
        if status in {"failed", "incomplete"}:
            reason = _field(_field(response, "incomplete_details"), "reason")
            suffix = f" ({reason})" if reason else ""
            raise ProviderInvalidResponseError(f"deepseek response was {status}{suffix}")

        # Parse the explicit Responses payload.  The SDK's output_text convenience
        # property is intentionally not used: compatibility payloads can make it
        # raise even when output.message.content contains valid text.
        output = _field(response, "output", [])
        if not isinstance(output, (list, tuple)):
            return None
        for item in output:
            if _field(item, "type") != "message":
                continue
            content_items = _field(item, "content", [])
            if not isinstance(content_items, (list, tuple)):
                continue
            for part in content_items:
                if _field(part, "type") == "output_text":
                    text = _field(part, "text")
                    if isinstance(text, str) and text:
                        return text
        return None

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.close()

    def _record(
        self,
        response: Any,
        elapsed_ms: int,
        *,
        transport: StructuredTransport,
        stage: str | None,
    ) -> None:
        usage = _field(response, "usage")
        choices = _field(response, "choices", [])
        first_choice = choices[0] if isinstance(choices, (list, tuple)) and choices else None
        details = _field(usage, "completion_tokens_details") or _field(
            usage, "output_tokens_details"
        )
        input_tokens = _field(usage, "prompt_tokens")
        if input_tokens is None:
            input_tokens = _field(usage, "input_tokens")
        output_tokens = _field(usage, "completion_tokens")
        if output_tokens is None:
            output_tokens = _field(usage, "output_tokens")
        metadata: dict[str, Any] = {
            "model": self.settings.deepseek_model,
            "transport": transport.value,
            "finish_reason": _field(first_choice, "finish_reason")
            or _field(response, "status"),
            "reasoning_tokens": _field(details, "reasoning_tokens"),
        }
        if stage is not None:
            metadata["stage"] = stage
        self.ledger.record(
            UsageEvent(
                provider="deepseek",
                operation="structured",
                request_id=_field(response, "_request_id") or _field(response, "id"),
                elapsed_ms=elapsed_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                metadata=metadata,
            )
        )


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read SDK objects and dict-like compatibility payloads without coercion."""
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default) if value is not None else default
