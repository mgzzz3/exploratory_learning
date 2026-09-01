"""Create battle system tables.

Revision ID: 20260901_0004
Revises: 20260831_0003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260901_0004"
down_revision: Union[str, Sequence[str], None] = "20260831_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "battle_rooms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "host_user_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("topic", sa.String(length=80), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="generating",
        ),
        sa.Column("error_message", sa.String(length=200), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["host_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_battle_rooms_host_user_id"),
        "battle_rooms",
        ["host_user_id"],
    )
    op.create_index(
        op.f("ix_battle_rooms_session_id"),
        "battle_rooms",
        ["session_id"],
    )
    op.create_index(
        op.f("ix_battle_rooms_status"),
        "battle_rooms",
        ["status"],
    )
    op.create_index(
        op.f("ix_battle_rooms_expires_at"),
        "battle_rooms",
        ["expires_at"],
    )

    op.create_table(
        "battle_participants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("room_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column(
            "status",
            sa.String(length=12),
            nullable=False,
            server_default="joined",
        ),
        sa.Column("current_level", sa.Integer(), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False),
        sa.Column("total_seconds", sa.Integer(), nullable=True),
        sa.Column("result", sa.String(length=10), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["battle_rooms.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "room_id",
            "user_id",
            name="uq_battle_participant_room_user",
        ),
    )
    op.create_index(
        op.f("ix_battle_participants_room_id"),
        "battle_participants",
        ["room_id"],
    )
    op.create_index(
        op.f("ix_battle_participants_user_id"),
        "battle_participants",
        ["user_id"],
    )

    op.create_table(
        "battle_answers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("room_id", sa.String(length=36), nullable=False),
        sa.Column("participant_id", sa.String(length=36), nullable=False),
        sa.Column("level_position", sa.Integer(), nullable=False),
        sa.Column("selected_option", sa.Integer(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["battle_rooms.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["battle_participants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "participant_id",
            "level_position",
            name="uq_battle_answer_participant_level",
        ),
    )
    op.create_index(
        op.f("ix_battle_answers_room_id"),
        "battle_answers",
        ["room_id"],
    )
    op.create_index(
        op.f("ix_battle_answers_participant_id"),
        "battle_answers",
        ["participant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_battle_answers_participant_id"),
        table_name="battle_answers",
    )
    op.drop_index(op.f("ix_battle_answers_room_id"), table_name="battle_answers")
    op.drop_table("battle_answers")
    op.drop_index(
        op.f("ix_battle_participants_user_id"),
        table_name="battle_participants",
    )
    op.drop_index(
        op.f("ix_battle_participants_room_id"),
        table_name="battle_participants",
    )
    op.drop_table("battle_participants")
    op.drop_index(
        op.f("ix_battle_rooms_expires_at"),
        table_name="battle_rooms",
    )
    op.drop_index(op.f("ix_battle_rooms_status"), table_name="battle_rooms")
    op.drop_index(op.f("ix_battle_rooms_session_id"), table_name="battle_rooms")
    op.drop_index(
        op.f("ix_battle_rooms_host_user_id"),
        table_name="battle_rooms",
    )
    op.drop_table("battle_rooms")
