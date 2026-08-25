from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app

from .fakes import FakeContentGenerator, FakeWechatClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+aiosqlite://",
        jwt_secret="test-secret-with-at-least-32-characters",
        jwt_ttl_minutes=60,
        wechat_app_id="test-app-id",
        wechat_app_secret="test-app-secret",
        deepseek_api_key="test-deepseek-key",
    )


@pytest.fixture
def wechat() -> FakeWechatClient:
    return FakeWechatClient()


@pytest.fixture
def generator() -> FakeContentGenerator:
    return FakeContentGenerator()


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
    wechat: FakeWechatClient,
    generator: FakeContentGenerator,
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        settings=settings,
        engine=engine,
        wechat_client=wechat,
        content_generator=generator,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


async def login(client: AsyncClient, code: str = "owner") -> dict[str, str]:
    response = await client.post("/api/v1/auth/wechat", json={"code": code})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
