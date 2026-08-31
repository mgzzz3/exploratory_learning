"""Add grounded generation source metadata.

Revision ID: 20260828_0002
Revises: 20260825_0001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260828_0002"
down_revision: Union[str, Sequence[str], None] = "20260825_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    session_columns = {
        column["name"] for column in inspector.get_columns("learning_sessions")
    }
    level_columns = {column["name"] for column in inspector.get_columns("levels")}

    # MySQL DDL is non-transactional, so a failed migration can leave the first
    # columns behind. The guards make retrying that partial migration safe.
    if "input_type" not in session_columns:
        op.add_column(
            "learning_sessions",
            sa.Column(
                "input_type",
                sa.String(length=20),
                nullable=False,
                server_default="keyword",
            ),
        )
    if "source_input" not in session_columns:
        op.add_column(
            "learning_sessions",
            sa.Column("source_input", sa.Text(), nullable=True),
        )
    if "retrieved_at" not in session_columns:
        op.add_column(
            "learning_sessions",
            sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "sources" not in session_columns:
        op.add_column(
            "learning_sessions",
            sa.Column("sources", sa.JSON(), nullable=True),
        )
    if "source_ids" not in level_columns:
        op.add_column(
            "levels",
            sa.Column("source_ids", sa.JSON(), nullable=True),
        )

    # MySQL does not allow a default value on JSON columns in all supported
    # configurations. Backfill legacy rows before enforcing NOT NULL instead.
    op.execute(sa.text("UPDATE learning_sessions SET sources = '[]' WHERE sources IS NULL"))
    op.execute(sa.text("UPDATE levels SET source_ids = '[]' WHERE source_ids IS NULL"))

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("learning_sessions") as batch_op:
            batch_op.alter_column(
                "sources",
                existing_type=sa.JSON(),
                nullable=False,
            )
        with op.batch_alter_table("levels") as batch_op:
            batch_op.alter_column(
                "source_ids",
                existing_type=sa.JSON(),
                nullable=False,
            )
    else:
        op.alter_column(
            "learning_sessions",
            "sources",
            existing_type=sa.JSON(),
            nullable=False,
        )
        op.alter_column(
            "levels",
            "source_ids",
            existing_type=sa.JSON(),
            nullable=False,
        )


def downgrade() -> None:
    op.drop_column("levels", "source_ids")
    op.drop_column("learning_sessions", "sources")
    op.drop_column("learning_sessions", "retrieved_at")
    op.drop_column("learning_sessions", "source_input")
    op.drop_column("learning_sessions", "input_type")
