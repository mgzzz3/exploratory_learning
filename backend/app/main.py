from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.routes import assists, auth, games, health, me
from app.clients.ai import ContentGenerator, DeepSeekContentGenerator, LocalContentGenerator
from app.clients.wechat import LocalWechatClient, WechatApiClient, WechatClient
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.db.session import build_engine, build_session_factory


def create_app(
    *,
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    wechat_client: WechatClient | None = None,
    content_generator: ContentGenerator | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or build_engine(settings.database_url)
    if wechat_client is None:
        wechat_client = (
            LocalWechatClient()
            if settings.should_use_mock_wechat
            else WechatApiClient(
                app_id=settings.wechat_app_id,
                app_secret=settings.wechat_app_secret,
                base_url=settings.wechat_api_base_url,
            )
        )
    if content_generator is None:
        content_generator = (
            LocalContentGenerator()
            if settings.should_use_mock_content_generator
            else DeepSeekContentGenerator(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
                max_retries=settings.ai_max_retries,
            )
        )

    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.wechat_client = wechat_client
    app.state.content_generator = content_generator
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    for router in (health.router, auth.router, games.router, assists.router, me.router):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
