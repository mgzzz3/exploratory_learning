from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.clients.ai import LocalContentGenerator
from app.db.models import LearningSession, Level
from app.db.session import build_engine
from app.main import create_app
from app.services.generation_strategy import GroundedGenerationStrategy, LocalResearcher

from .fakes import FakeContentGenerator, FakeWechatClient


@pytest.mark.mysql
def test_mysql_migration_and_core_flow(monkeypatch: pytest.MonkeyPatch) -> None:
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
    command.downgrade(config, "20260825_0001")
    command.upgrade(config, "head")
    command.check(config)

    async def exercise_core_flow() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            question_generation_mode="grounded",
            database_url=database_url,
            jwt_secret="mysql-test-secret-with-at-least-32-characters",
            use_mock_services=True,
        )
        engine = build_engine(database_url)
        content_generator = LocalContentGenerator()

        async def keep_public_url(value: str) -> str:
            return value

        grounded_strategy = GroundedGenerationStrategy(
            researcher=LocalResearcher(),
            generator=content_generator,
            validator=content_generator,
            normalize_url=keep_public_url,
        )
        app = create_app(
            settings=settings,
            engine=engine,
            wechat_client=FakeWechatClient(),
            content_generator=content_generator,
            generation_strategy=grounded_strategy,
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
            assert len(created.json()["sources"]) == 2
            assert created.json()["retrieved_at"] is not None
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

            long_url = "https://docs.example.com/" + ("guide/" * 280)
            url_game = await client.post(
                "/api/v1/games",
                headers=owner_headers,
                json={"topic": long_url},
            )
            assert url_game.status_code == 201, url_game.text
            assert url_game.json()["input_type"] == "url"
            assert len(url_game.json()["sources"]) == 1

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            url_row = await db.scalar(
                select(LearningSession).where(LearningSession.input_type == "url")
            )
            assert url_row is not None
            assert url_row.source_input == long_url
            assert isinstance(url_row.sources, list) and len(url_row.sources) == 1
            assert url_row.retrieved_at is not None
            level_source_ids = list(
                (
                    await db.scalars(
                        select(Level.source_ids)
                        .where(Level.session_id == url_row.id)
                        .order_by(Level.position)
                    )
                ).all()
            )
            assert all(isinstance(item, list) and item for item in level_source_ids)

        def fail_after_session_flush(*args, **kwargs) -> None:
            del args, kwargs
            raise RuntimeError("forced persistence failure")

        monkeypatch.setattr("app.services.game._add_levels", fail_after_session_flush)
        rollback_app = create_app(
            settings=settings,
            engine=engine,
            wechat_client=FakeWechatClient(),
            content_generator=content_generator,
            generation_strategy=grounded_strategy,
        )
        async with AsyncClient(
            transport=ASGITransport(app=rollback_app),
            base_url="http://mysql-test",
        ) as rollback_client:
            owner = await rollback_client.post('/api/v1/auth/wechat', json={'code':'mysql-owner'})
            failure = await rollback_client.post('/api/v1/games',
                headers={'Authorization': f"Bearer {owner.json()['access_token']}"},
                json={'topic':'必须回滚的游戏'})
            assert failure.status_code == 500
            assert failure.json()['error']['details']['fallback'] == {'available':False}
            assert 'forced persistence failure' not in failure.text
        async with sessions() as db:
            rolled_back = await db.scalar(
                select(func.count())
                .select_from(LearningSession)
                .where(LearningSession.topic == "必须回滚的游戏")
            )
            assert rolled_back == 0
        await engine.dispose()

    asyncio.run(exercise_core_flow())
