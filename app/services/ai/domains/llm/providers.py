"""
AI provider factory for creating AI model instances.


Uses PydanticAI agents with support for multiple providers.

"""


# providers stays the address every caller imports; what moved is
# re-exported so none of them had to change.

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from app.services.ai.domains.llm.agents import (
    get_agent as get_agent,
)
from app.services.ai.domains.llm.base import (
    SUPPORTED_PROVIDERS as SUPPORTED_PROVIDERS,
)
from app.services.ai.domains.llm.base import (
    ProviderError as ProviderError,
)
from app.services.ai.domains.llm.base import (
    ProviderNotInstalledError as ProviderNotInstalledError,
)
from app.services.ai.domains.llm.base import (
    get_supported_providers as get_supported_providers,
)
from app.services.ai.domains.llm.base import (
    require_api_key as require_api_key,
)
from app.services.ai.domains.llm.model_factory import (
    get_provider_model_class as get_provider_model_class,
)
from app.services.ai.domains.llm.model_factory import (
    model_for as model_for,
)
from app.services.ai.domains.llm.model_factory import (
    validate_provider_support as validate_provider_support,
)

# Re-exported so tests can patch ``app.services.ai.domains.llm.providers.<Name>``
# directly — patch targets follow the import path, not the source path,
# for clarity in test failure output.
__all__ = [
    "Agent",
    "ModelSettings",
    "AsyncOpenAI",
    "OpenAIChatModel",
    "OpenAIProvider",
]


# Lazy loading of provider model classes to avoid import errors
