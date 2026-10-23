"""Persist project membership for scheduled conversations; legacy rows remain NULL."""

from __future__ import annotations

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision = "0048_scheduled_project"
down_revision = "0047_mcp_oauth_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    safe_add_column("scheduled_tasks", sa.Column("project_id", sa.String(64), nullable=True))


def downgrade() -> None:
    safe_drop_column("scheduled_tasks", "project_id")
