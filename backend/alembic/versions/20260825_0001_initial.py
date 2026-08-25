"""Create the MVP learning game tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("openid", sa.String(128), nullable=False),
        sa.Column("unionid", sa.String(128), nullable=True),
        sa.Column("nickname", sa.String(40), nullable=False),
        sa.Column("completed_games", sa.Integer(), nullable=False),
        sa.Column("learned_points", sa.Integer(), nullable=False),
        sa.Column("sound_enabled", sa.Boolean(), nullable=False),
        sa.Column("vibration_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_openid", "users", ["openid"], unique=True)

    op.create_table(
        "learning_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("topic", sa.String(80), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("hearts", sa.Integer(), nullable=False),
        sa.Column("current_level", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learning_sessions_status", "learning_sessions", ["status"])
    op.create_index("ix_learning_sessions_user_id", "learning_sessions", ["user_id"])
    op.create_index(
        "ix_sessions_user_status",
        "learning_sessions",
        ["user_id", "status"],
    )

    op.create_table(
        "levels",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("title", sa.String(40), nullable=False),
        sa.Column("intro", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("correct_option", sa.Integer(), nullable=False),
        sa.Column("wrong_explanation", sa.Text(), nullable=False),
        sa.Column("praise", sa.Text(), nullable=False),
        sa.Column("takeaway", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["learning_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "position", name="uq_level_session_position"),
    )
    op.create_index("ix_levels_session_id", "levels", ["session_id"])

    op.create_table(
        "answer_attempts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("level_position", sa.Integer(), nullable=False),
        sa.Column("selected_option", sa.Integer(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("hearts_after", sa.Integer(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["learning_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_answer_attempts_session_id", "answer_attempts", ["session_id"])

    op.create_table(
        "assist_tokens",
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("assisted_by", sa.String(36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assisted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["learning_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index("ix_assist_tokens_expires_at", "assist_tokens", ["expires_at"])
    op.create_index("ix_assist_tokens_session_id", "assist_tokens", ["session_id"])

    op.create_table(
        "revive_events",
        sa.Column("id", sa.String(80), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["learning_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revive_events_session_id", "revive_events", ["session_id"])


def downgrade() -> None:
    op.drop_table("revive_events")
    op.drop_table("assist_tokens")
    op.drop_table("answer_attempts")
    op.drop_table("levels")
    op.drop_table("learning_sessions")
    op.drop_table("users")
