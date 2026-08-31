from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_deepseek import ChatDeepSeek

from app.clients.research import (
    ResearchModelCapabilityError,
    build_research_chat_model,
    validate_research_model_capabilities,
)
from app.core.config import Settings


def research_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="development",
        use_mock_services=False,
        deepseek_api_key="deepseek-test-secret",
        tavily_api_key="tavily-test-secret",
        deepseek_base_url="https://deepseek.test",
        deepseek_model="configured-tool-model",
    )


def test_research_model_uses_exact_configured_deepseek_model() -> None:
    model = build_research_chat_model(research_settings())

    assert isinstance(model, ChatDeepSeek)
    assert model.model_name == "configured-tool-model"
    assert model.extra_body == {"thinking": {"type": "disabled"}}
    assert "deepseek-test-secret" not in repr(model)


def test_research_model_capability_gate_binds_tools_and_structured_output() -> None:
    model = build_research_chat_model(research_settings())

    validated = validate_research_model_capabilities(model)

    assert validated is model


def test_research_model_capability_gate_rejects_missing_features() -> None:
    unsupported = SimpleNamespace(model_name="unsupported")

    with pytest.raises(ResearchModelCapabilityError, match="Tool Calls"):
        validate_research_model_capabilities(unsupported)


def test_mock_research_mode_does_not_build_remote_model() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        use_mock_services=True,
    )

    assert build_research_chat_model(settings) is None
