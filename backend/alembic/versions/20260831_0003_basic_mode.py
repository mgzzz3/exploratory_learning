"""Persist generation mode and unique basic fallback permit IDs.

Revision ID: 20260831_0003
Revises: 20260828_0002
"""
import sqlalchemy as sa
from alembic import op

revision = "20260831_0003"
down_revision = "20260828_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("learning_sessions")}
    additions = [
        sa.Column("generation_mode", sa.String(20), nullable=False, server_default="legacy"),
        sa.Column("verification_notice", sa.String(100), nullable=True),
        sa.Column("basic_fallback_id", sa.String(32), nullable=True),
    ]
    for column in additions:
        if column.name not in columns:
            op.add_column("learning_sessions", column)
    constraints = {item["name"] for item in sa.inspect(bind).get_unique_constraints("learning_sessions")}
    if "uq_sessions_basic_fallback_id" not in constraints:
        with op.batch_alter_table("learning_sessions") as batch:
            batch.create_unique_constraint("uq_sessions_basic_fallback_id", ["basic_fallback_id"])
    length = "json_array_length" if bind.dialect.name == "sqlite" else "JSON_LENGTH"
    array_type = "array" if bind.dialect.name == "sqlite" else "ARRAY"
    op.execute(sa.text(
        "UPDATE learning_sessions SET generation_mode='grounded' "
        "WHERE generation_mode='legacy' AND retrieved_at IS NOT NULL "
        f"AND JSON_TYPE(sources)='{array_type}' AND {length}(sources)>0"
    ))


def downgrade() -> None:
    with op.batch_alter_table("learning_sessions") as batch:
        batch.drop_constraint("uq_sessions_basic_fallback_id", type_="unique")
        batch.drop_column("basic_fallback_id")
        batch.drop_column("verification_notice")
        batch.drop_column("generation_mode")
