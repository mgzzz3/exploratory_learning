from __future__ import annotations

import asyncio
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import httpx
import pytest
from sqlalchemy import text, select, func
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.clients.ai import ContentGenerationError
from app.core.config import Settings
from app.db.models import LearningSession, User
from app.db.session import build_engine
from app.main import create_app
from .conftest import login
from .fakes import FakeWechatClient, FakeContentGenerator, generated_game
from .test_grounded_persistence import FailingStrategy
from .test_game_generation_pipeline import row_counts


@pytest.mark.mysql
def test_mysql_basic_migration_and_multiconnection_idempotency():
    url = os.getenv("TEST_MYSQL_DATABASE_URL")
    if not url:
        pytest.skip("需要独立可丢弃 MySQL 8 测试库")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("只允许独立 _test 库")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "base")
    command.upgrade(config, "20260828_0002")

    async def seed_old_records():
        engine = build_engine(url)
        async with engine.begin() as connection:
            version = await connection.scalar(text("SELECT VERSION()"))
            assert version.startswith("8.")
            await connection.execute(text("INSERT INTO users (id,openid,nickname,completed_games,learned_points,sound_enabled,vibration_enabled,created_at,updated_at) VALUES ('migration-u','migration-o','n',0,0,1,1,NOW(),NOW())"))
            for name, sources, date in [("old", "[]", None), ("verified", '[{"id":"src_aaaaaaaaaaaa"}]', "2026-08-01 00:00:00")]:
                await connection.execute(text("INSERT INTO learning_sessions (id,user_id,topic,title,status,hearts,current_level,summary,started_at,input_type,sources,retrieved_at) VALUES (:id,'migration-u','t','t','active',3,0,'[]',NOW(),'keyword',:sources,:date)"), {"id":name, "sources":sources, "date":date})
        await engine.dispose()
    asyncio.run(seed_old_records())
    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "20260828_0002")
    command.upgrade(config, "head")
    command.check(config)

    async def exercise():
        engine = build_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            assert await db.scalar(select(LearningSession.generation_mode).where(LearningSession.id == "old")) == "legacy"
            assert await db.scalar(select(LearningSession.generation_mode).where(LearningSession.id == "verified")) == "grounded"
        gate = asyncio.Event()
        class RacingGenerator(FakeContentGenerator):
            async def generate(self, topic):
                self.calls.append(topic)
                if len(self.calls) == 2:
                    gate.set()
                await asyncio.wait_for(gate.wait(), 3)
                return generated_game(topic)
        generator = RacingGenerator()
        settings = Settings(_env_file=None, environment="test", question_generation_mode="grounded", use_mock_services=True, database_url=url, jwt_secret="mysql-basic-test-secret-at-least-32-characters")
        app = create_app(settings=settings, engine=engine, wechat_client=FakeWechatClient(), content_generator=generator, generation_strategy=FailingStrategy(ContentGenerationError("offline")))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            owner = await login(client, "basic-owner")
            other = await login(client, "basic-other")
            failed = await client.post("/api/v1/games", headers=owner, json={"topic":"高情商聊天"})
            token = failed.json()["error"]["details"]["fallback"]["token"]
            payload = {"topic":"高情商聊天", "fallback_token":token, "acknowledge_unverified":True}
            first, second = await asyncio.gather(*[client.post("/api/v1/games/basic", headers=owner, json=payload) for _ in range(2)])
            assert first.status_code == second.status_code == 201
            assert first.json() == second.json()
            assert first.json()["generation_mode"] == "basic"
            assert len(generator.calls) == 2  # No promise of exactly-once external billing.
            replay = await client.post("/api/v1/games/basic", headers=owner, json=payload)
            assert replay.json() == first.json() and len(generator.calls) == 2
            denied = await client.post("/api/v1/games/basic", headers=other, json=payload)
            assert denied.status_code == 403
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(LearningSession).where(LearningSession.generation_mode == "basic")) == 1
                assert await row_counts(db) == (3, 3)
        # Rollback each persistence stage using actual MySQL connections.
        from app.services.game import persist_generated_game
        from .test_basic_persistence import basic_result
        for phase in ("flush", "levels", "commit", "cancel"):
            async with sessions() as db:
                user_id = await db.scalar(select(User.id).where(User.openid == "openid-basic-owner"))
                async def fail(*args, **kwargs):
                    if phase == "cancel": raise asyncio.CancelledError
                    raise RuntimeError("injected persistence failure")
                def fail_levels(*args, **kwargs):
                    raise RuntimeError("injected persistence failure")
                with pytest.MonkeyPatch.context() as patch:
                    if phase == "levels": patch.setattr("app.services.game._add_levels", fail_levels)
                    else: patch.setattr(db, "flush" if phase == "flush" else "commit", fail)
                    with pytest.raises(asyncio.CancelledError if phase == "cancel" else RuntimeError):
                        await persist_generated_game(db, user_id=user_id, generated=basic_result())
            async with sessions() as db:
                assert await row_counts(db) == (3, 3)
        # Different requests/apps retain their own grounded/legacy/basic strategy.
        from app.services.generation_strategy import LegacyGenerationStrategy
        from .test_grounded_persistence import StaticStrategy
        from .test_generation_strategy import grounded_result
        legacy_generator = FakeContentGenerator()
        legacy_app = create_app(settings=settings.model_copy(update={"question_generation_mode":"legacy"}), engine=engine, wechat_client=FakeWechatClient(), content_generator=legacy_generator, generation_strategy=LegacyGenerationStrategy(legacy_generator))
        grounded_app = create_app(settings=settings, engine=engine, wechat_client=FakeWechatClient(), content_generator=FakeContentGenerator(), generation_strategy=StaticStrategy(grounded_result()))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as basic_client, httpx.AsyncClient(transport=httpx.ASGITransport(app=legacy_app), base_url="http://test") as legacy_client, httpx.AsyncClient(transport=httpx.ASGITransport(app=grounded_app), base_url="http://test") as grounded_client:
            results = await asyncio.gather(
                basic_client.post("/api/v1/games/basic", headers=owner, json=payload),
                legacy_client.post("/api/v1/games", headers=owner, json={"topic":"旧版主题"}),
                grounded_client.post("/api/v1/games", headers=owner, json={"topic":"Harness Engineering"}),
            )
            assert [item.status_code for item in results] == [201,201,201]
            assert [item.json()["generation_mode"] for item in results] == ["basic","legacy","grounded"]
            assert len(generator.calls) == 2 and legacy_generator.calls == ["旧版主题"]
        await engine.dispose()
    asyncio.run(exercise())
