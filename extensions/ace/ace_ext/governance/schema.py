from __future__ import annotations

from sqlalchemy import Column, Double, Integer, String, Text, UniqueConstraint

from ace_ext.persistence.schema import scoped

teams = scoped("teams", Column("name", String(128), nullable=False))
members = scoped(
    "team_members",
    Column("user_id", String(128), nullable=False),
    Column("role", String(24), nullable=False),
    Column("label", String(200), nullable=False),
    Column("revision", Integer, nullable=False),
    UniqueConstraint("tenant_id", "project_id", "user_id", name="uq_df_team_user"),
)
preferences = scoped(
    "user_workspace",
    Column("active_team_id", String(64), nullable=False),
    UniqueConstraint("tenant_id", "project_id", name="uq_df_workspace_user"),
)
workspaces = scoped(
    "workspaces",
    Column("team_id", String(64), nullable=False),
    Column("owner_id", String(128), nullable=False),
    Column("name", String(128), nullable=False),
    Column("description", Text, nullable=False),
    Column("deleted_at", Double),
)
native_projects = scoped(
    "native_projects",
    Column("user_id", String(128), nullable=False),
    Column("native_id", String(64), nullable=False),
    UniqueConstraint("tenant_id", "project_id", "user_id", name="uq_df_native_workspace"),
    UniqueConstraint("native_id", name="uq_df_native_id"),
)
canvas_links = scoped(
    "canvas_links",
    Column("canvas_id", String(64), nullable=False),
    UniqueConstraint("canvas_id", name="uq_df_canvas_link"),
)
