from pathlib import Path

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

    assert settings.deepseek_api_key == "test-deepseek-key"


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
