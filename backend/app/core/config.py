from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
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
    question_generation_mode: Literal["grounded", "legacy"] = "grounded"
    # Selector for the pluggable AI provider registry in app.clients.ai.
    ai_provider: str = "deepseek"
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

    deepseek_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "DEEPSEEK_API"),
    )
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    ai_max_retries: int = Field(default=3, ge=1, le=5)

    tavily_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        validation_alias="TAVILY_API_KEY",
    )
    tavily_search_timeout_seconds: int = Field(default=8, ge=1, le=8)
    tavily_extract_basic_timeout_seconds: int = Field(default=12, ge=1, le=12)
    tavily_extract_advanced_timeout_seconds: int = Field(default=25, ge=1, le=25)
    tavily_transient_retries: int = Field(default=1, ge=0, le=1)
    research_max_tool_calls: int = Field(default=4, ge=1, le=4)
    research_max_model_calls: int = Field(default=6, ge=1, le=6)
    research_max_search_calls: int = Field(default=2, ge=1, le=2)
    research_max_extract_calls: int = Field(default=2, ge=1, le=2)
    research_max_search_results: int = Field(default=8, ge=2, le=8)
    research_max_full_content_results: int = Field(default=3, ge=1, le=3)
    research_max_extract_urls: int = Field(default=3, ge=1, le=3)
    research_page_char_limit: int = Field(default=120_000, ge=40_000, le=120_000)
    research_model_context_char_limit: int = Field(
        default=40_000,
        ge=4_000,
        le=40_000,
    )
    research_total_timeout_seconds: int = Field(default=85, ge=30, le=85)
    research_generation_reserve_seconds: int = Field(default=40, gt=0)
    research_finalization_reserve_seconds: int = Field(default=15, gt=0)
    grounding_validation_reserve_seconds: int = Field(default=15, gt=0)

    ad_unit_id: str = ""
    use_mock_services: bool = False

    @model_validator(mode="after")
    def validate_generation_budget_reserves(self) -> Settings:
        research_window = (
            self.research_total_timeout_seconds
            - self.research_generation_reserve_seconds
        )
        if research_window <= 0:
            raise ValueError("生成校验预留必须小于总预算")
        if self.research_finalization_reserve_seconds >= research_window:
            raise ValueError("研究整理预留必须小于研究阶段预算")
        if (
            self.grounding_validation_reserve_seconds
            >= self.research_generation_reserve_seconds
        ):
            raise ValueError("必需校验预留必须小于生成校验预留")
        return self

    @model_validator(mode="after")
    def validate_production_generation_credentials(self) -> Settings:
        if self.environment != "production" or self.use_mock_services:
            return self
        missing: list[str] = []
        if (
            self.question_generation_mode == "grounded"
            and not self.tavily_api_key.get_secret_value()
        ):
            missing.append("TAVILY_API_KEY")
        # Provider-specific credentials are declared by each AI provider spec.
        from app.clients.ai.registry import ai_provider_credentials_missing

        missing.extend(ai_provider_credentials_missing(self))
        if missing:
            raise ValueError(f"生产生成服务缺少配置：{', '.join(missing)}")
        return self

    @property
    def research_enabled(self) -> bool:
        return self.question_generation_mode == "grounded"

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
        from app.clients.ai.registry import ai_provider_credentials_missing

        return bool(ai_provider_credentials_missing(self))

    @property
    def should_use_mock_research(self) -> bool:
        if not self.research_enabled:
            return True
        if self.use_mock_services:
            return True
        if self.environment == "production":
            return False
        from app.clients.ai.registry import ai_provider_credentials_missing

        return bool(
            ai_provider_credentials_missing(self)
            or not self.tavily_api_key.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
