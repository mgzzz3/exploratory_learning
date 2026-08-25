from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.db.session import build_engine
from app.main import create_app

from .fakes import FakeContentGenerator, FakeWechatClient


def test_mysql_migration_and_core_flow() -> None:
    database_url = os.getenv("TEST_MYSQL_DATABASE_URL")
    if not database_url:
        pytest.skip("设置 TEST_MYSQL_DATABASE_URL 后运行真实 MySQL 集成测试")
    database_name = make_url(database_url).database or ""
    if not database_name.endswith("_test"):
        pytest.fail("MySQL 集成测试只允许使用以 _test 结尾的独立数据库")

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)

    async def exercise_core_flow() -> None:
        settings = Settings(
            environment="test",
            database_url=database_url,
            jwt_secret="mysql-test-secret-with-at-least-32-characters",
            use_mock_services=True,
        )
        engine = build_engine(database_url)
        app = create_app(
            settings=settings,
            engine=engine,
            wechat_client=FakeWechatClient(),
            content_generator=FakeContentGenerator(),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://mysql-test",
        ) as client:
            owner = await client.post("/api/v1/auth/wechat", json={"code": "mysql-owner"})
            helper = await client.post("/api/v1/auth/wechat", json={"code": "mysql-helper"})
            owner_headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}
            helper_headers = {"Authorization": f"Bearer {helper.json()['access_token']}"}
            created = await client.post(
                "/api/v1/games",
                headers=owner_headers,
                json={"topic": "MySQL 集成测试"},
            )
            assert created.status_code == 201, created.text
            game_id = created.json()["id"]
            for _ in range(3):
                answer = await client.post(
                    f"/api/v1/games/{game_id}/answers",
                    headers=owner_headers,
                    json={"option": 1, "attempt_id": str(uuid4())},
                )
                assert answer.status_code == 200, answer.text
            share = await client.post(
                f"/api/v1/games/{game_id}/share",
                headers=owner_headers,
            )
            assisted = await client.post(
                f"/api/v1/assists/{share.json()['token']}",
                headers=helper_headers,
            )
            assert assisted.status_code == 200, assisted.text
            assert assisted.json()["hearts"] == 3
        await engine.dispose()

    asyncio.run(exercise_core_flow())
