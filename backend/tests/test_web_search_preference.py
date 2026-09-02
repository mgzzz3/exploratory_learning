from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from app.clients.ai import LocalContentGenerator
from app.core.config import Settings
from app.db.base import Base
from app.main import create_app

from .conftest import login
from .fakes import FakeWechatClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        question_generation_mode="grounded",
        database_url="sqlite+aiosqlite://",
        jwt_secret="test-secret-with-at-least-32-characters",
        jwt_ttl_minutes=60,
        wechat_app_id="test-app-id",
        wechat_app_secret="test-app-secret",
        deepseek_api_key="test-deepseek-key",
        tavily_api_key="",
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def client(
    settings: Settings,
    engine: AsyncEngine,
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        settings=settings,
        engine=engine,
        wechat_client=FakeWechatClient(),
        content_generator=LocalContentGenerator(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.mark.anyio
async def test_web_search_prefers_grounded_generation_by_default(
    client: AsyncClient,
) -> None:
    headers = await login(client)

    response = await client.post(
        "/api/v1/games",
        headers=headers,
        json={"topic": "Python 基础"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["generation_mode"] == "grounded"
    assert len(response.json()["sources"]) >= 2
    assert response.json()["retrieved_at"] is not None


@pytest.mark.anyio
async def test_disabling_web_search_switches_to_direct_ai(client: AsyncClient) -> None:
    headers = await login(client)
    disabled = await client.patch(
        "/api/v1/me/settings",
        headers=headers,
        json={"web_search_enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["web_search_enabled"] is False

    response = await client.post(
        "/api/v1/games",
        headers=headers,
        json={"topic": "Python 基础"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["generation_mode"] == "legacy"
    assert response.json()["sources"] == []
    assert response.json()["retrieved_at"] is None


@pytest.mark.anyio
async def test_disabling_web_search_rejects_url_input(client: AsyncClient) -> None:
    headers = await login(client)
    await client.patch(
        "/api/v1/me/settings",
        headers=headers,
        json={"web_search_enabled": False},
    )

    response = await client.post(
        "/api/v1/games",
        headers=headers,
        json={"topic": "https://example.com/article"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "URL_REQUIRES_RESEARCH"
