"""Builds the text model bound to one role, from the resolved provider settings."""

from .ark import ArkLLMProvider
from .config import LLMRole, ProviderSettings
from .contracts import ProgressiveLLMProvider
from .deepseek import DeepSeekLLMProvider
from .usage import UsageLedger


def build_llm(
    settings: ProviderSettings,
    role: LLMRole,
    *,
    ledger: UsageLedger,
    mock: ProgressiveLLMProvider,
) -> ProgressiveLLMProvider:
    """The model for ``role``.  Credentials and the Ark model id are only required when the
    role actually resolves to that provider, so unused Ark settings never stop a service."""

    choice = settings.resolved_llm(role)
    if choice == "mock":
        return mock
    live = settings.for_live_capability()
    if choice == "ark":
        return ArkLLMProvider(live, model=live.ark_model_for(role), role=role, ledger=ledger)
    return DeepSeekLLMProvider(live, ledger=ledger)
