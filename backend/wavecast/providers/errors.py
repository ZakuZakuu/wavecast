"""Provider-neutral failures. Adapters never expose vendor SDK exceptions."""


class ProviderError(RuntimeError):
    pass


class ProviderConfigurationError(ProviderError):
    pass


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class ProviderInvalidResponseError(ProviderError):
    pass


class ProviderOutputLimitError(ProviderInvalidResponseError):
    """The provider stopped before producing a complete structured response."""

    pass


class ProviderBudgetExceededError(ProviderError):
    pass


def is_retryable(error: ProviderError) -> bool:
    return isinstance(
        error, (ProviderRateLimitError, ProviderTimeoutError, ProviderUnavailableError)
    )
