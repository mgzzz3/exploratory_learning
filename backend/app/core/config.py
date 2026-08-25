from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "AI 万物学堂 API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "mysql+asyncmy://root:password@127.0.0.1:3306/ai_school?charset=utf8mb4"
    jwt_secret: str = Field(
        default="development-only-secret-change-before-production",
        min_length=32,
    )
    jwt_ttl_minutes: int = Field(default=60 * 24 * 7, ge=5, le=60 * 24 * 30)
    cors_origins: list[str] = [
        "http://localhost:10086",
        "http://127.0.0.1:10086",
        "https://bkgame.cc",
        "https://www.bkgame.cc",
    ]

    wechat_app_id: str = Field(
        default="",
        validation_alias=AliasChoices("WECHAT_APP_ID", "WX_APP_ID"),
    )
    wechat_app_secret: str = Field(
        default="",
        validation_alias=AliasChoices("WECHAT_APP_SECRET", "WX_APP_SECRET"),
    )
    wechat_api_base_url: str = "https://api.weixin.qq.com"

    deepseek_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "DEEPSEEK_API"),
    )
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    ai_max_retries: int = Field(default=3, ge=1, le=5)

    ad_unit_id: str = ""
    use_mock_services: bool = False

    @property
    def should_use_mock_wechat(self) -> bool:
        if self.use_mock_services:
            return True
        if self.environment == "production":
            return False
        return not (self.wechat_app_id and self.wechat_app_secret)

    @property
    def should_use_mock_content_generator(self) -> bool:
        if self.use_mock_services:
            return True
        if self.environment == "production":
            return False
        return not self.deepseek_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
