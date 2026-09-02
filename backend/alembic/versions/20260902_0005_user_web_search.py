"""Add per-user web search preference.

Revision ID: 20260902_0005
Revises: 20260901_0004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0005"
down_revision: Union[str, Sequence[str], None] = "20260901_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "web_search_enabled" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "web_search_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def downgrade() -> None:
    op.drop_column("users", "web_search_enabled")
