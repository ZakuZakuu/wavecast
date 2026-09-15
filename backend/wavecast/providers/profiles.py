"""Provider-neutral structured inference transports and latency profiles."""

from dataclasses import dataclass
from enum import StrEnum


class StructuredTransport(StrEnum):
    CHAT_JSON = "chat_json"
    RESPONSES_JSON_SCHEMA = "responses_json_schema"


class InferenceProfile(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


@dataclass(frozen=True)
class InferencePolicy:
    transport: StructuredTransport
    timeout_seconds: float
    max_output_tokens: int
    max_attempts: int
    reasoning_effort: str | None


def policy_for(
    profile: InferenceProfile,
    *,
    default_timeout_seconds: float,
    deep_timeout_seconds: float | None = None,
    default_max_output_tokens: int,
    deep_max_output_tokens: int | None = None,
    default_max_attempts: int,
) -> InferencePolicy:
    if profile is InferenceProfile.FAST:
        return InferencePolicy(
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            timeout_seconds=min(default_timeout_seconds, 15.0),
            max_output_tokens=min(default_max_output_tokens, 2048),
            max_attempts=1,
            reasoning_effort="none",
        )
    if profile is InferenceProfile.DEEP:
        return InferencePolicy(
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            timeout_seconds=deep_timeout_seconds or default_timeout_seconds,
            max_output_tokens=deep_max_output_tokens or default_max_output_tokens,
            max_attempts=default_max_attempts,
            reasoning_effort="high",
        )
    return InferencePolicy(
        transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
        timeout_seconds=default_timeout_seconds,
        max_output_tokens=default_max_output_tokens,
        max_attempts=default_max_attempts,
        reasoning_effort="low",
    )
