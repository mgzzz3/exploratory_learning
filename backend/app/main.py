from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.routes import assists, auth, battles, games, health, me
from app.clients.ai import (
    ContentGenerator,
    build_content_generator,
    build_research_model,
)
from app.clients.wechat import LocalWechatClient, WechatApiClient, WechatClient
from app.core.config import Settings, get_settings
from app.core.generation_budget import GenerationBudget
from app.core.errors import install_error_handlers
from app.core.observability import GenerationDiagnosticsMiddleware, GenerationMetrics, install_private_logging
from app.db.session import build_engine, build_session_factory
from app.services.generation_strategy import (
    GroundedGenerationStrategy,
    LegacyGenerationStrategy,
    LocalResearcher,
    QuestionGenerationStrategy,
    build_generation_strategy,
)


def build_grounded_generation_strategy(
    settings: Settings,
    content_generator: ContentGenerator,
    research_model,
) -> QuestionGenerationStrategy:
    if settings.should_use_mock_research:
        researcher = LocalResearcher()
    else:
        from app.clients.tavily import AdaptiveTavilyExtract, AdaptiveTavilySearch
        from app.services.research_agent import ResearchAgent

        researcher = ResearchAgent(
            model=research_model,
            search=AdaptiveTavilySearch(
                tavily_api_key=settings.tavily_api_key,
                timeout_seconds=settings.tavily_search_timeout_seconds,
                transient_retries=settings.tavily_transient_retries,
            ),
            extract=AdaptiveTavilyExtract(
                tavily_api_key=settings.tavily_api_key,
                basic_timeout_seconds=settings.tavily_extract_basic_timeout_seconds,
                advanced_timeout_seconds=(
                    settings.tavily_extract_advanced_timeout_seconds
                ),
                transient_retries=settings.tavily_transient_retries,
                page_char_limit=settings.research_page_char_limit,
            ),
            max_tool_calls=settings.research_max_tool_calls,
            max_model_calls=settings.research_max_model_calls,
            max_search_calls=settings.research_max_search_calls,
            max_extract_calls=settings.research_max_extract_calls,
            total_timeout_seconds=settings.research_total_timeout_seconds,
            page_char_limit=settings.research_page_char_limit,
            context_char_limit=settings.research_model_context_char_limit,
        )
    if not hasattr(content_generator, "generate_grounded") or not hasattr(
        content_generator, "validate_grounding"
    ):
        raise TypeError("grounded 内容生成器必须支持有据生成和事实校验")
    return GroundedGenerationStrategy(
        researcher=researcher,
        generator=content_generator,
        validator=content_generator,
        budget_factory=lambda: GenerationBudget.start(
            total_seconds=settings.research_total_timeout_seconds,
            generation_reserve_seconds=settings.research_generation_reserve_seconds,
            finalization_reserve_seconds=settings.research_finalization_reserve_seconds,
            validation_reserve_seconds=settings.grounding_validation_reserve_seconds,
        ),
    )


def create_app(
    *,
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    wechat_client: WechatClient | None = None,
    content_generator: ContentGenerator | None = None,
    generation_strategy: QuestionGenerationStrategy | None = None,
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
        content_generator = build_content_generator(settings)

    research_chat_model = (
        build_research_model(settings) if settings.research_enabled else None
    )
    if generation_strategy is None:
        generation_strategy = build_generation_strategy(
            settings=settings,
            content_generator=content_generator,
            grounded_factory=lambda active_settings: build_grounded_generation_strategy(
                active_settings,
                content_generator,
                research_chat_model,
            ),
        )

    app = FastAPI(title=settings.app_name, version="0.1.0")
    install_private_logging()
    app.state.generation_metrics = GenerationMetrics()
    app.add_middleware(GenerationDiagnosticsMiddleware, settings=settings, metrics=app.state.generation_metrics)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.wechat_client = wechat_client
    app.state.content_generator = content_generator
    app.state.research_chat_model = research_chat_model
    app.state.generation_strategy = generation_strategy
    # Direct AI generation without web research; selected per user preference.
    app.state.direct_generation_strategy = LegacyGenerationStrategy(content_generator)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    for router in (
        health.router,
        auth.router,
        games.router,
        battles.router,
        assists.router,
        me.router,
    ):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
