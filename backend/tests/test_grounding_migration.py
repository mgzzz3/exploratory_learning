from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def alembic_config(database_path: Path) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path}",
    )
    return config


def test_grounding_migration_upgrades_existing_rows_without_fake_sources(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy.db"
    config = alembic_config(database_path)
    command.upgrade(config, "20260825_0001")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO users (
              id, openid, nickname, completed_games, learned_points,
              sound_enabled, vibration_enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "user-1",
                "openid-1",
                "旧用户",
                0,
                0,
                1,
                1,
                "2026-08-01 00:00:00",
                "2026-08-01 00:00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO learning_sessions (
              id, user_id, topic, title, status, hearts, current_level,
              summary, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "game-1",
                "user-1",
                "旧主题",
                "旧主题",
                "active",
                3,
                0,
                json.dumps(["一", "二", "三"]),
                "2026-08-01 00:00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO levels (
              id, session_id, position, tier, title, intro, question,
              options, correct_option, wrong_explanation, praise, takeaway
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "level-1",
                "game-1",
                0,
                "novice",
                "旧关卡",
                "这是旧关卡的介绍文字",
                "这是旧关卡的问题吗？",
                json.dumps(["A", "B", "C"]),
                0,
                "这是原来的错误解释",
                "答对了真不错",
                "这是旧知识点",
            ),
        )
        connection.commit()

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        game = connection.execute(
            """
            SELECT input_type, source_input, retrieved_at, sources
            FROM learning_sessions WHERE id = 'game-1'
            """
        ).fetchone()
        level = connection.execute(
            "SELECT source_ids FROM levels WHERE id = 'level-1'"
        ).fetchone()

    assert game == ("keyword", None, None, "[]")
    assert level == ("[]",)

    command.downgrade(config, "20260825_0001")
    command.upgrade(config, "head")
