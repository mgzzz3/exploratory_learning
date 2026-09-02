from __future__ import annotations

from app.clients.ai.base import (
    ContentGenerationError,
    ContentGenerator,
    GroundedContentGenerator,
    GroundingValidator,
)
from app.clients.ai.local import LocalContentGenerator
from app.clients.ai.openai_compatible import (
    DeepSeekContentGenerator,
    OpenAICompatibleContentGenerator,
)
from app.clients.ai.registry import (
    AIProviderCapabilityError,
    AIProviderError,
    AIProviderNotFoundError,
    AIProviderSpec,
    build_content_generator,
    build_research_model,
    get_ai_provider,
    register_ai_provider,
)

# Importing the module registers the built-in provider.
from app.clients.ai import deepseek as _deepseek  # noqa: F401  isort: skip

__all__ = [
    "AIProviderCapabilityError",
    "AIProviderError",
    "AIProviderNotFoundError",
    "AIProviderSpec",
    "ContentGenerationError",
    "ContentGenerator",
    "DeepSeekContentGenerator",
    "GroundedContentGenerator",
    "GroundingValidator",
    "LocalContentGenerator",
    "OpenAICompatibleContentGenerator",
    "build_content_generator",
    "build_research_model",
    "get_ai_provider",
    "register_ai_provider",
]
