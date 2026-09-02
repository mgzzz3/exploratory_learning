from __future__ import annotations

import pytest

from app.clients.ai import (
    AIProviderCapabilityError,
    AIProviderError,
    AIProviderNotFoundError,
    AIProviderSpec,
    LocalContentGenerator,
    OpenAICompatibleContentGenerator,
    build_content_generator,
    get_ai_provider,
    register_ai_provider,
)
from app.clients.ai.registry import _PROVIDERS
from app.core.config import Settings


def make_settings(**overrides) -> Settings:
    defaults = {
        "_env_file": None,
        "environment": "development",
        "use_mock_services": False,
        "deepseek_api_key": "test-deepseek-key",
    }
    return Settings(**{**defaults, **overrides})


def test_deepseek_provider_builds_configured_generator() -> None:
    settings = make_settings(deepseek_model="configured-model")

    generator = build_content_generator(settings)

    assert isinstance(generator, OpenAICompatibleContentGenerator)
    assert generator.model == "configured-model"


def test_unknown_provider_fails_with_registered_names() -> None:
    with pytest.raises(AIProviderNotFoundError, match="deepseek"):
        get_ai_provider("missing-provider")


def test_missing_credentials_fall_back_to_local_generator() -> None:
    settings = make_settings(deepseek_api_key="")

    assert settings.should_use_mock_content_generator is True
    assert isinstance(build_content_generator(settings), LocalContentGenerator)


def test_custom_provider_plugs_in_without_touching_deepseek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubGenerator(LocalContentGenerator):
        pass

    stub = StubGenerator()
    spec = AIProviderSpec(
        name="stub",
        build_content_generator=lambda settings: stub,
        credentials_missing=lambda settings: [],
    )
    monkeypatch.setitem(_PROVIDERS, "stub", spec)
    settings = make_settings(ai_provider="stub")

    assert build_content_generator(settings) is stub
    # The default provider keeps working unchanged.
    assert get_ai_provider("deepseek").name == "deepseek"


def test_duplicate_registration_is_rejected() -> None:
    spec = AIProviderSpec(
        name="deepseek",
        build_content_generator=lambda settings: LocalContentGenerator(),
    )
    with pytest.raises(AIProviderError, match="deepseek"):
        register_ai_provider(spec)
