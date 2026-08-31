from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from alembic import command
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import LearningSession
from app.services.generation_strategy import GenerationResult
from .fakes import generated_game
from .test_generation_strategy import grounded_result
from .test_grounding_migration import alembic_config
from .test_game_generation_pipeline import add_user, row_counts


def basic_result(permit_id=None):
    return GenerationResult(
        game=generated_game("高情商聊天"), display_topic="高情商聊天", input_type="keyword",
        level_source_ids=[[], [], []], generation_mode="basic", verification_notice="未经联网核验",
        basic_fallback_id=permit_id or uuid4().hex,
    )


def test_result_modes_are_unambiguous_and_basic_requires_notice_and_no_evidence():
    result = basic_result()
    assert result.generation_mode == "basic"
    assert grounded_result().generation_mode == "grounded"
    for updates in [
        {"verification_notice": None}, {"verification_notice": "已核验"},
        {"basic_fallback_id": None}, {"retrieved_at": grounded_result().retrieved_at},
        {"sources": grounded_result().sources}, {"level_source_ids": [["src_aaaaaaaaaaaa"], [], []]},
        {"generation_mode": "legacy"}, {"generation_mode": "grounded"},
    ]:
        with pytest.raises(ValidationError):
            GenerationResult.model_validate({**result.model_dump(), **updates})


def test_incremental_mode_migration_preserves_and_backfills_evidence(tmp_path):
    path = tmp_path / "modes.db"
    config = alembic_config(path)
    command.upgrade(config, "20260828_0002")
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO users (id,openid,nickname,completed_games,learned_points,sound_enabled,vibration_enabled,created_at,updated_at) VALUES ('u','o','n',0,0,1,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        for name, sources, date in [("old", [], None), ("verified", [{"id": "src_aaaaaaaaaaaa"}], "2026-08-01"), ("empty", [], "2026-08-01"), ("undated", [{"id": "src_aaaaaaaaaaaa"}], None)]:
            db.execute("INSERT INTO learning_sessions (id,user_id,topic,title,status,hearts,current_level,summary,started_at,input_type,sources,retrieved_at) VALUES (?,'u','t','t','active',3,0,'[]',CURRENT_TIMESTAMP,'keyword',?,?)", (name, json.dumps(sources), date))
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT id,generation_mode,verification_notice,basic_fallback_id FROM learning_sessions ORDER BY id").fetchall()
        assert rows == [("empty", "legacy", None, None), ("old", "legacy", None, None), ("undated", "legacy", None, None), ("verified", "grounded", None, None)]
        db.execute("UPDATE learning_sessions SET basic_fallback_id='unique-test' WHERE id='old'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE learning_sessions SET basic_fallback_id='unique-test' WHERE id='empty'")
    command.downgrade(config, "20260828_0002")
    command.upgrade(config, "head")


@pytest.mark.anyio
async def test_database_unique_permit_and_roundtrip_mode(engine):
    from app.services.game import persist_generated_game, find_basic_game
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = await add_user(db)
        result = basic_result()
        out = await persist_generated_game(db, user_id=user.id, generated=result)
        assert out.generation_mode == "basic" and out.verification_notice == "未经联网核验"
        assert out.sources == [] and out.retrieved_at is None
        assert await row_counts(db) == (1, 3)
        replay = await find_basic_game(db, user_id=user.id, permit_id=result.basic_fallback_id)
        assert replay.id == out.id
        assert await find_basic_game(db, user_id="different-user", permit_id=result.basic_fallback_id) is None
        # A duplicate arriving after a competing commit is resolved by the unique index.
        repeated = await persist_generated_game(db, user_id=user.id, generated=result)
        assert repeated.id == out.id
        assert await row_counts(db) == (1, 3)


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["levels", "flush", "commit", "cancel"])
async def test_basic_transaction_failure_leaves_no_partial_game(engine, monkeypatch, phase):
    import asyncio
    from app.services.game import persist_generated_game
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = await add_user(db)
        result = basic_result()
        def fail(*args, **kwargs):
            raise RuntimeError("forced")
        async def async_fail(*args, **kwargs):
            if phase == "cancel": raise asyncio.CancelledError
            fail()
        if phase == "levels": monkeypatch.setattr("app.services.game._add_levels", fail)
        else: monkeypatch.setattr(db, "flush" if phase == "flush" else "commit", async_fail)
        with pytest.raises(asyncio.CancelledError if phase == "cancel" else RuntimeError):
            await persist_generated_game(db, user_id=user.id, generated=result)
    async with sessions() as db:
        assert await row_counts(db) == (0, 0)
