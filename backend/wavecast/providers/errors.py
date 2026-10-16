"""Provider-neutral failures. Adapters never expose vendor SDK exceptions."""


class ProviderError(RuntimeError):
    pass


class ProviderConfigurationError(ProviderError):
    pass


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderPermissionError(ProviderAuthenticationError):
    """The credential was understood but is not allowed to do this (HTTP 403)."""

    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class ProviderInvalidResponseError(ProviderError):
    pass


class ProviderRequestError(ProviderInvalidResponseError):
    """The provider rejected the request itself (HTTP 4xx other than auth and rate limits)."""

    pass


class ProviderSchemaValidationError(ProviderInvalidResponseError):
    """The provider returned JSON that failed the requested structured schema."""

    pass


class ProviderIncompleteResponseError(ProviderInvalidResponseError):
    """The provider stopped before completing a non-output-limit response."""

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
