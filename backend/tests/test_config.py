from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.clients.ai import DeepSeekContentGenerator
from app.clients.wechat import LocalWechatClient
from app.core.config import ROOT_ENV_FILE, Settings
from app.main import create_app


def test_default_env_file_is_repository_root() -> None:
    repository_root = Path(__file__).resolve().parents[2]

    assert ROOT_ENV_FILE == repository_root / ".env"


def test_deepseek_api_alias_is_loaded_from_env_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API=test-deepseek-key\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    settings = Settings(_env_file=env_file)

    assert settings.deepseek_api_key.get_secret_value() == "test-deepseek-key"


def test_wx_credentials_are_loaded_from_env_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "WX_APP_ID=test-app-id\nWX_APP_SECRET=test-app-secret\n",
        encoding="utf-8",
    )
    for name in ("WECHAT_APP_ID", "WECHAT_APP_SECRET", "WX_APP_ID", "WX_APP_SECRET"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=env_file)

    assert settings.wechat_app_id == "test-app-id"
    assert settings.wechat_app_secret == "test-app-secret"
    assert settings.should_use_mock_wechat is False


def test_real_deepseek_can_be_used_with_local_wechat() -> None:
    settings = Settings(
        _env_file=None,
        environment="development",
        use_mock_services=False,
        wechat_app_id="",
        wechat_app_secret="",
        deepseek_api_key="test-deepseek-key",
    )

    assert settings.should_use_mock_wechat is True
    assert settings.should_use_mock_content_generator is False

    app = create_app(settings=settings)

    assert isinstance(app.state.wechat_client, LocalWechatClient)
    assert isinstance(app.state.content_generator, DeepSeekContentGenerator)


def test_explicit_mock_mode_overrides_available_credentials() -> None:
    settings = Settings(
        _env_file=None,
        environment="development",
        use_mock_services=True,
        wechat_app_id="test-app-id",
        wechat_app_secret="test-app-secret",
        deepseek_api_key="test-deepseek-key",
    )

    assert settings.should_use_mock_wechat is True
    assert settings.should_use_mock_content_generator is True


def test_production_research_requires_tavily_and_deepseek_keys() -> None:
    with pytest.raises(ValidationError, match="TAVILY_API_KEY"):
        Settings(
            _env_file=None,
            environment="production",
            use_mock_services=False,
            deepseek_api_key="deepseek-secret",
            tavily_api_key="",
        )


def test_question_generation_mode_defaults_to_grounded_and_rejects_invalid() -> None:
    settings = Settings(_env_file=None, use_mock_services=True)

    assert settings.question_generation_mode == "grounded"
    assert settings.research_enabled is True

    with pytest.raises(ValidationError, match="question_generation_mode"):
        Settings(
            _env_file=None,
            use_mock_services=True,
            question_generation_mode="automatic",
        )


def test_production_legacy_requires_only_deepseek_key() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        question_generation_mode="legacy",
        use_mock_services=False,
        deepseek_api_key="deepseek-secret",
        tavily_api_key="",
    )

    assert settings.research_enabled is False
    assert settings.tavily_api_key.get_secret_value() == ""

    with pytest.raises(ValidationError, match="DEEPSEEK_API"):
        Settings(
            _env_file=None,
            environment="production",
            question_generation_mode="legacy",
            use_mock_services=False,
            deepseek_api_key="",
            tavily_api_key="",
        )


@pytest.mark.parametrize("mode", ["grounded", "legacy"])
def test_mock_mode_allows_both_generation_modes_without_keys(mode: str) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        question_generation_mode=mode,
        use_mock_services=True,
        deepseek_api_key="",
        tavily_api_key="",
    )

    assert settings.question_generation_mode == mode


def test_legacy_app_does_not_run_research_capability_gate(monkeypatch) -> None:
    calls: list[Settings] = []

    def unexpected_research_build(settings: Settings):
        calls.append(settings)
        raise AssertionError("legacy must not initialize research")

    monkeypatch.setattr(
        "app.main.build_research_chat_model",
        unexpected_research_build,
    )
    settings = Settings(
        _env_file=None,
        environment="development",
        question_generation_mode="legacy",
        use_mock_services=True,
    )

    app = create_app(settings=settings)

    assert calls == []
    assert app.state.research_chat_model is None

    with pytest.raises(ValidationError, match="DEEPSEEK_API"):
        Settings(
            _env_file=None,
            environment="production",
            use_mock_services=False,
            deepseek_api_key="",
            tavily_api_key="tavily-secret",
        )


def test_mock_mode_allows_missing_research_keys() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        use_mock_services=True,
        deepseek_api_key="",
        tavily_api_key="",
    )

    assert isinstance(settings.deepseek_api_key, SecretStr)
    assert isinstance(settings.tavily_api_key, SecretStr)
    assert settings.deepseek_api_key.get_secret_value() == ""
    assert settings.tavily_api_key.get_secret_value() == ""


def test_research_keys_are_redacted_from_repr_and_json() -> None:
    settings = Settings(
        _env_file=None,
        use_mock_services=True,
        deepseek_api_key="deepseek-sensitive-value",
        tavily_api_key="tavily-sensitive-value",
    )

    rendered = repr(settings)
    dumped = settings.model_dump_json()

    assert "deepseek-sensitive-value" not in rendered
    assert "tavily-sensitive-value" not in rendered
    assert "deepseek-sensitive-value" not in dumped
    assert "tavily-sensitive-value" not in dumped
    assert "**********" in dumped


def test_research_budget_defaults_and_boundaries() -> None:
    settings = Settings(_env_file=None, use_mock_services=True)

    assert settings.tavily_search_timeout_seconds == 8
    assert settings.tavily_extract_basic_timeout_seconds == 12
    assert settings.tavily_extract_advanced_timeout_seconds == 25
    assert settings.tavily_transient_retries == 1
    assert settings.research_max_tool_calls == 4
    assert settings.research_max_model_calls == 6
    assert settings.research_max_search_calls == 2
    assert settings.research_max_extract_calls == 2
    assert settings.research_max_search_results == 8
    assert settings.research_max_full_content_results == 3
    assert settings.research_max_extract_urls == 3
    assert settings.research_page_char_limit == 120_000
    assert settings.research_model_context_char_limit == 40_000
    assert settings.research_total_timeout_seconds == 85

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            use_mock_services=True,
            research_max_tool_calls=5,
        )

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            use_mock_services=True,
            research_model_context_char_limit=120_001,
        )


def test_generation_reserve_defaults_leave_research_and_exploration_windows() -> None:
    settings = Settings(_env_file=None, use_mock_services=True)

    assert settings.research_generation_reserve_seconds == 40
    assert settings.research_finalization_reserve_seconds == 15
    assert settings.grounding_validation_reserve_seconds == 15
    research_window = (
        settings.research_total_timeout_seconds
        - settings.research_generation_reserve_seconds
    )
    assert research_window == 45
    assert research_window - settings.research_finalization_reserve_seconds == 30


@pytest.mark.parametrize(
    "field",
    [
        "research_total_timeout_seconds",
        "research_generation_reserve_seconds",
        "research_finalization_reserve_seconds",
        "grounding_validation_reserve_seconds",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_budget_reserves_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, use_mock_services=True, **{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"research_total_timeout_seconds": 86},
        {"research_generation_reserve_seconds": 85},
        {"research_generation_reserve_seconds": 86},
        {"research_finalization_reserve_seconds": 45},
        {"research_finalization_reserve_seconds": 46},
        {"grounding_validation_reserve_seconds": 40},
        {"grounding_validation_reserve_seconds": 41},
        {"research_total_timeout_seconds": 55},
        {"research_total_timeout_seconds": 40},
        {"research_max_tool_calls": 5},
        {"research_max_search_calls": 3},
        {"research_max_extract_calls": 3},
        {"research_max_model_calls": 7},
    ],
)
def test_budget_reserves_and_call_caps_reject_invalid_combinations(overrides) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, use_mock_services=True, **overrides)


def test_budget_reserves_can_shorten_total_with_explicit_valid_reserves() -> None:
    settings = Settings(
        _env_file=None,
        use_mock_services=True,
        research_total_timeout_seconds=30,
        research_generation_reserve_seconds=14,
        research_finalization_reserve_seconds=6,
        grounding_validation_reserve_seconds=5,
    )

    assert settings.research_total_timeout_seconds == 30
    assert settings.research_generation_reserve_seconds == 14
    assert settings.research_finalization_reserve_seconds == 6
    assert settings.grounding_validation_reserve_seconds == 5
