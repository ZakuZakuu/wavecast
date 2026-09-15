from wavecast.providers.errors import ProviderInvalidResponseError

from scripts.live_curation_eval import sanitized_failure_reason


def test_sanitized_incomplete_reason_exposes_only_safe_max_token_metadata() -> None:
    assert (
        sanitized_failure_reason(
            ProviderInvalidResponseError(
                "deepseek response was incomplete (max_output_tokens)"
            )
        )
        == "incomplete:max_output_tokens"
    )
    assert (
        sanitized_failure_reason(
            ProviderInvalidResponseError("deepseek response was incomplete (content_filter)")
        )
        == "incomplete"
    )


def test_sanitized_failure_reason_does_not_expose_provider_payloads() -> None:
    reason = sanitized_failure_reason(
        ProviderInvalidResponseError("deepseek returned prompt and hidden reasoning payload")
    )

    assert reason == "ProviderInvalidResponseError"
