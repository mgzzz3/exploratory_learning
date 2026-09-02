from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.clients.ai.openai_compatible import OpenAICompatibleContentGenerator
from app.clients.ai.registry import AIProviderSpec, register_ai_provider

if TYPE_CHECKING:
    from app.core.config import Settings


def _credentials_missing(settings: "Settings") -> list[str]:
    if settings.deepseek_api_key.get_secret_value():
        return []
    return ["DEEPSEEK_API/DEEPSEEK_API_KEY"]


def _build_content_generator(settings: "Settings") -> OpenAICompatibleContentGenerator:
    return OpenAICompatibleContentGenerator(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        max_retries=settings.ai_max_retries,
    )


def _build_research_model(settings: "Settings") -> Any:
    # LangChain's DeepSeek integration stays an optional dependency of this provider.
    from app.clients.research import build_research_chat_model

    return build_research_chat_model(settings)


register_ai_provider(
    AIProviderSpec(
        name="deepseek",
        build_content_generator=_build_content_generator,
        build_research_model=_build_research_model,
        credentials_missing=_credentials_missing,
    )
)
