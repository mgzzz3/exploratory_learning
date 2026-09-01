from __future__ import annotations

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


def table_names(database_path: Path) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {row[0] for row in rows}


def test_battle_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "battle.db"
    config = alembic_config(database_path)

    command.upgrade(config, "head")
    tables = table_names(database_path)
    assert {
        "battle_rooms",
        "battle_participants",
        "battle_answers",
    }.issubset(tables)
    with sqlite3.connect(database_path) as connection:
        answer_constraints = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='battle_answers'"
        ).fetchone()[0]
        participant_constraints = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='battle_participants'"
        ).fetchone()[0]
    assert "uq_battle_answer_participant_level" in answer_constraints
    assert "uq_battle_participant_room_user" in participant_constraints

    command.downgrade(config, "20260831_0003")
    tables_after_downgrade = table_names(database_path)
    assert not {
        "battle_rooms",
        "battle_participants",
        "battle_answers",
    } & tables_after_downgrade
