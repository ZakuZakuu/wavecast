"""Estimated Ark text-model cost in CNY, from token receipts.

The figures are the per-million-token rates observed on the 2026-10-14 experiment receipts.
They are an estimate for diagnostics, not a contract quote or a bill (trial credit and
discounts are not modelled).  The USD cost fields of the usage ledger stay empty for Ark:
nothing here is converted between currencies.

An unknown model, or a response without token counts, has an *unknown* cost, never zero.
A model whose rate depends on the time of day (peak versus idle) has no single estimate; it
reports the range between the two published rates instead of a permanent constant.
"""

from dataclasses import dataclass

PRICE_VERSION = "ark-experiment-receipts-2026-10-14"


@dataclass(frozen=True)
class ArkRate:
    input_cny_per_million: float
    output_cny_per_million: float
    cached_input_cny_per_million: float


@dataclass(frozen=True)
class ArkPrice:
    """One model's rate; ``peak`` is set only when the price depends on the time of day."""

    standard: ArkRate
    peak: ArkRate | None = None


ARK_PRICES: dict[str, ArkPrice] = {
    "doubao-seed-2-1-pro-260915": ArkPrice(ArkRate(6.0, 30.0, 1.2)),
    "doubao-seed-2-1-lite-260915": ArkPrice(ArkRate(0.8, 2.7, 0.16)),
    # Idle-time rate observed on the receipts; the peak input/output rate was 2/8.  The cached
    # rate at peak was not observed, so the upper bound prices cached tokens as plain input.
    "deepseek-v4-1-flash-260910": ArkPrice(ArkRate(1.0, 4.0, 0.02), peak=ArkRate(2.0, 8.0, 2.0)),
}


@dataclass(frozen=True)
class CostEstimate:
    cny: float | None
    cny_low: float | None
    cny_high: float | None
    basis: str


def _cost(rate: ArkRate, input_tokens: int, output_tokens: int, cached: int | None) -> float:
    cached_tokens = cached or 0
    uncached = max(0, input_tokens - cached_tokens)
    return round(
        (
            uncached * rate.input_cny_per_million
            + cached_tokens * rate.cached_input_cny_per_million
            + output_tokens * rate.output_cny_per_million
        )
        / 1_000_000,
        8,
    )


def estimate_cost(
    model: str, input_tokens: int | None, output_tokens: int | None, cached_tokens: int | None
) -> CostEstimate:
    price = ARK_PRICES.get(model)
    if price is None:
        return CostEstimate(None, None, None, "unknown_model")
    if input_tokens is None or output_tokens is None:
        return CostEstimate(None, None, None, "usage_missing")
    if price.peak is not None:
        return CostEstimate(
            None,
            _cost(price.standard, input_tokens, output_tokens, cached_tokens),
            _cost(price.peak, input_tokens, output_tokens, None),
            "time_dependent_price",
        )
    estimate = _cost(price.standard, input_tokens, output_tokens, cached_tokens)
    # Without a cache split the estimate prices every input token in full: an upper bound.
    basis = (
        "usage_and_known_cache"
        if cached_tokens is not None
        else "cache_split_unreported_upper_bound"
    )
    return CostEstimate(estimate, estimate, estimate, basis)
