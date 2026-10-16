"""Read SDK objects and dict-like compatibility payloads shared by the inference adapters."""

from collections.abc import Mapping
from typing import Any


def field(value: Any, name: str, default: Any = None) -> Any:
    """Read SDK objects and dict-like compatibility payloads without coercion."""
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default) if value is not None else default


def count(value: Any) -> int | None:
    """A reported token count; anything else (missing, null, negative, not a number) is unknown."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return int(value)


def cache_split(usage: Any, input_tokens: Any) -> tuple[int | None, int | None]:
    """Prompt-cache hit/miss tokens from either response shape, or ``(None, None)`` if unreported.

    Chat Completions reports ``prompt_cache_hit_tokens`` / ``prompt_cache_miss_tokens`` (DeepSeek)
    or ``prompt_tokens_details.cached_tokens`` (Ark); Responses reports
    ``input_tokens_details.cached_tokens``.  A miss count is only derived from the total when the
    hit count is reported and does not exceed it; a zero hit count is a real zero.
    """

    total = count(input_tokens)
    hit = count(field(usage, "prompt_cache_hit_tokens"))
    miss = count(field(usage, "prompt_cache_miss_tokens"))
    if hit is None:
        for details in ("input_tokens_details", "prompt_tokens_details"):
            hit = count(field(field(usage, details), "cached_tokens"))
            if hit is not None:
                break
    if hit is None:
        return None, None
    if miss is None and total is not None and hit <= total:
        miss = total - hit
    if total is not None and hit > total:
        return None, None
    return hit, miss
