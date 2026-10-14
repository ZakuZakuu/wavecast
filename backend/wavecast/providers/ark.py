"""Volcengine Ark text inference adapter (Chat Completions, strict JSON Schema output).

Prompts and agent workflow stay outside it.  The request shape is the one the 2026-10-14
experiment used: ``response_format`` json_schema with ``strict`` true, thinking disabled,
``temperature`` 0.7, no streaming, ``max_completion_tokens``.  Only the Lite Writer run was
measured with strict schema; nothing here claims Pro or Flash were.

Every call is sent exactly once.  The SDK's own retries are off, and a timeout, a rate limit
or an invalid answer is never resent, never downgraded to ``json_object`` and never moved to
another model: a failed call may still have been billed, so repeating it is the caller's
decision, taken with its own budget.
"""

import asyncio
import re
from time import perf_counter
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .ark_pricing import PRICE_VERSION, estimate_cost
from .config import ProviderSettings
from .errors import (
    ProviderAuthenticationError,
    ProviderError,
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
from .profiles import InferenceProfile, StructuredTransport
from .response_fields import cache_split, count, field
from .strict_schema import to_strict_schema
from .usage import UsageEvent, UsageLedger

ARK_TEMPERATURE = 0.7
TRANSPORT_LABEL = "ark_chat_json_schema_strict"
_SYSTEM_PROMPT = "Return only a JSON object that satisfies the response schema."


class ArkLLMProvider:
    """One Ark model serving one role; construct one per (role, model)."""

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        model: str,
        role: str = "unspecified",
        ledger: UsageLedger | None = None,
        client: Any | None = None,
    ) -> None:
        if not model:
            raise ValueError("an Ark model id is required")
        self.settings = settings
        self.model = model
        self.role = role
        self.ledger = ledger or UsageLedger()
        self._owns_client = client is None
        self.client: Any = client or AsyncOpenAI(
            api_key=settings.credential_for("ark"),
            base_url=settings.ark_base_url,
            timeout=max(settings.ark_timeout_seconds, settings.ark_deep_timeout_seconds),
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
        # ``transport`` and the profile's reasoning effort are accepted for the shared
        # protocol and not forwarded: Ark always gets the Chat strict request below, with
        # thinking disabled.  The profile only picks the time and output limits.
        schema = to_strict_schema(output_type.model_json_schema())  # raises before any request
        timeout_seconds, max_output_tokens = self._limits(profile)
        name = re.sub(r"[^A-Za-z0-9_-]", "_", output_type.__name__)[:64] or "structured_output"
        started_at = perf_counter()
        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": name, "strict": True, "schema": schema},
                    },
                    max_completion_tokens=max_output_tokens,
                    temperature=ARK_TEMPERATURE,
                    stream=False,
                    extra_body={"thinking": {"type": "disabled"}},
                ),
                timeout=timeout_seconds,
            )
        except asyncio.CancelledError:
            self._record_failure(started_at, "cancelled", stage)
            raise
        except (TimeoutError, APITimeoutError) as error:
            self._record_failure(started_at, "timeout", stage)
            raise ProviderTimeoutError("ark timed out") from error
        except APIConnectionError as error:
            self._record_failure(started_at, "connection_error", stage)
            raise ProviderUnavailableError("ark is temporarily unavailable") from error
        except APIStatusError as error:
            self._record_failure(
                started_at, "http_error", stage, status_code=error.status_code, received=True
            )
            raise _status_error(error.status_code) from error

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        parsed, failure = self._read(response, output_type, elapsed_ms, stage)
        if failure is not None:
            raise failure
        assert parsed is not None
        return parsed

    def _limits(self, profile: InferenceProfile) -> tuple[float, int]:
        """Time and output limits for a profile.

        The FAST profile's 15 s / 2048-token caps were sized for DeepSeek.  Ark answers the
        measured proposal and writer calls in 22 to 55 s, so FAST gets the ordinary limits;
        only DEEP and CURATOR get the longer ones.  Callers keep their own deadlines.
        """

        if profile in (InferenceProfile.DEEP, InferenceProfile.CURATOR):
            return self.settings.ark_deep_timeout_seconds, self.settings.ark_deep_max_output_tokens
        return self.settings.ark_timeout_seconds, self.settings.ark_max_output_tokens

    def _read(
        self,
        response: Any,
        output_type: type[BaseModel],
        elapsed_ms: int,
        stage: str | None,
    ) -> tuple[BaseModel | None, ProviderError | None]:
        """Validate the answer.  The usage event is recorded in every case: it was billed."""

        choices = field(response, "choices", [])
        choice = choices[0] if isinstance(choices, (list, tuple)) and choices else None
        finish_reason = field(choice, "finish_reason")
        content = field(field(choice, "message"), "content")

        parsed: BaseModel | None = None
        failure: ProviderError | None = None
        outcome = "ok"
        if choice is None:
            outcome, failure = "empty", ProviderInvalidResponseError("ark returned no choices")
        elif finish_reason == "length":
            outcome, failure = (
                "output_limit",
                ProviderOutputLimitError("ark stopped at the output limit"),
            )
        elif finish_reason != "stop":
            outcome, failure = (
                "incomplete",
                ProviderIncompleteResponseError(f"ark response was incomplete ({finish_reason!r})"),
            )
        elif not isinstance(content, str) or not content:
            outcome, failure = (
                "empty",
                ProviderInvalidResponseError("ark returned empty structured output"),
            )
        else:
            try:
                parsed = output_type.model_validate_json(content)
            except ValidationError as error:
                outcome = "schema_invalid"
                failure = ProviderSchemaValidationError(
                    "ark structured output did not match the requested schema"
                )
                failure.__cause__ = error

        self._record_success(response, elapsed_ms, stage, finish_reason, outcome)
        return parsed, failure

    def _record_success(
        self, response: Any, elapsed_ms: int, stage: str | None, finish_reason: Any, outcome: str
    ) -> None:
        usage = field(response, "usage")
        input_tokens = count(field(usage, "prompt_tokens"))
        output_tokens = count(field(usage, "completion_tokens"))
        cached, uncached = cache_split(usage, input_tokens)
        reasoning = count(field(field(usage, "completion_tokens_details"), "reasoning_tokens"))
        estimate = estimate_cost(self.model, input_tokens, output_tokens, cached)
        response_model = field(response, "model")
        metadata: dict[str, Any] = {
            "model": self.model,
            "role": self.role,
            "response_model": response_model if isinstance(response_model, str) else None,
            "transport": TRANSPORT_LABEL,
            "finish_reason": finish_reason if isinstance(finish_reason, str) else None,
            "reasoning_tokens": reasoning,
            "outcome": outcome,
            "request_dispatched": True,
            "response_received": True,
            "usage_known": input_tokens is not None and output_tokens is not None,
            "estimated_cost_cny": estimate.cny,
            "estimated_cost_cny_low": estimate.cny_low,
            "estimated_cost_cny_high": estimate.cny_high,
            "cost_basis": estimate.basis,
            "price_version": PRICE_VERSION,
        }
        if stage is not None:
            metadata["stage"] = stage
        request_id = field(response, "id")
        self.ledger.record(
            UsageEvent(
                provider="ark",
                operation="structured",
                request_id=request_id if isinstance(request_id, str) else None,
                elapsed_ms=elapsed_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached,
                uncached_input_tokens=uncached,
                metadata=metadata,
            )
        )

    def _record_failure(
        self,
        started_at: float,
        outcome: str,
        stage: str | None,
        *,
        status_code: int | None = None,
        received: bool = False,
    ) -> None:
        """A call without a usage receipt: tokens and cost are unknown, which is not zero."""

        metadata: dict[str, Any] = {
            "model": self.model,
            "role": self.role,
            "transport": TRANSPORT_LABEL,
            "outcome": outcome,
            "request_dispatched": True,
            "response_received": received,
            "usage_known": False,
            "estimated_cost_cny": None,
            "estimated_cost_cny_low": None,
            "estimated_cost_cny_high": None,
            "cost_basis": "no_receipt",
            "price_version": PRICE_VERSION,
            "http_status": status_code,
        }
        if stage is not None:
            metadata["stage"] = stage
        self.ledger.record(
            UsageEvent(
                provider="ark",
                operation="structured",
                elapsed_ms=int((perf_counter() - started_at) * 1000),
                metadata=metadata,
            )
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.close()


def _status_error(status_code: int) -> ProviderError:
    """Coarse HTTP classification only; no vendor error code is interpreted."""

    if status_code == 401:
        return ProviderAuthenticationError("ark authentication failed")
    if status_code == 403:
        return ProviderPermissionError("ark denied permission for this request")
    if status_code == 429:
        return ProviderRateLimitError("ark rate limited the request")
    if 500 <= status_code < 600:
        return ProviderUnavailableError("ark is temporarily unavailable")
    return ProviderRequestError(f"ark rejected the request with HTTP {status_code}")
