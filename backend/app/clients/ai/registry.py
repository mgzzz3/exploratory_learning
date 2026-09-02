from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.clients.ai.base import ContentGenerator
from app.clients.ai.local import LocalContentGenerator

if TYPE_CHECKING:
    from app.core.config import Settings


ContentGeneratorFactory = Callable[["Settings"], ContentGenerator]
ResearchModelFactory = Callable[["Settings"], Any]
CredentialsCheck = Callable[["Settings"], list[str]]


@dataclass(frozen=True)
class AIProviderSpec:
    """One pluggable AI backend.

    A new provider only needs its own module that calls
    register_ai_provider with factories; existing providers and services
    stay untouched.
    """

    name: str
    build_content_generator: ContentGeneratorFactory
    build_research_model: ResearchModelFactory | None = None
    credentials_missing: CredentialsCheck | None = None


class AIProviderError(RuntimeError):
    pass


class AIProviderNotFoundError(AIProviderError):
    pass


class AIProviderCapabilityError(AIProviderError):
    pass


_PROVIDERS: dict[str, AIProviderSpec] = {}


def register_ai_provider(spec: AIProviderSpec) -> None:
    if spec.name in _PROVIDERS:
        raise AIProviderError(f"AI 提供商已注册：{spec.name}")
    _PROVIDERS[spec.name] = spec


def get_ai_provider(name: str) -> AIProviderSpec:
    try:
        return _PROVIDERS[name]
    except KeyError:
        registered = "、".join(sorted(_PROVIDERS)) or "无"
        raise AIProviderNotFoundError(
            f"未注册的 AI 提供商：{name}（已注册：{registered}）"
        ) from None


def ai_provider_credentials_missing(settings: "Settings") -> list[str]:
    provider = get_ai_provider(settings.ai_provider)
    if provider.credentials_missing is None:
        return []
    return provider.credentials_missing(settings)


def build_content_generator(settings: "Settings") -> ContentGenerator:
    if settings.should_use_mock_content_generator:
        return LocalContentGenerator()
    return get_ai_provider(settings.ai_provider).build_content_generator(settings)


def build_research_model(settings: "Settings") -> Any:
    if settings.should_use_mock_research:
        return None
    provider = get_ai_provider(settings.ai_provider)
    if provider.build_research_model is None:
        raise AIProviderCapabilityError(
            f"AI 提供商 {provider.name} 未提供联网研究模型"
        )
    return provider.build_research_model(settings)
