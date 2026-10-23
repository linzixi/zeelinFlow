from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Double,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()


def scoped(name: str, *columns) -> Table:
    return Table(
        "ace_df_" + name,
        metadata,
        Column("id", String(64), primary_key=True),
        Column("tenant_id", String(64), nullable=False),
        Column("project_id", String(64), nullable=False),
        Column("created_at", Double, nullable=False),
        *columns,
        Index(f"ix_df_{name}_scope", "tenant_id", "project_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )


projects = scoped(
    "projects",
    Column("owner_id", String(128), nullable=False),
    Column("name", String(200), nullable=False),
    Column("description", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("graph", JSON, nullable=False),
    Column("source", JSON, nullable=False),
    Column("updated_at", Double, nullable=False),
    Column("deleted_at", Double),
)
graphs = scoped(
    "graph_revisions",
    Column("revision", Integer, nullable=False),
    Column("graph", JSON, nullable=False),
    Column("actor", String(128), nullable=False),
    UniqueConstraint("tenant_id", "project_id", "revision", name="uq_df_graph_revision"),
)
articles = scoped(
    "articles",
    Column("identity_hash", String(64), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("data", JSON, nullable=False),
    Column("overrides", JSON, nullable=False),
    Column("mode", String(16), nullable=False),
    Column("branch", String(40), nullable=False),
    Column("risk", String(16), nullable=False),
    Column("review_status", String(16), nullable=False),
    Column("ingested_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
    Column("deleted_at", Double),
    UniqueConstraint("tenant_id", "project_id", "identity_hash", "mode", name="uq_df_article"),
)
article_revisions = scoped(
    "article_revisions",
    Column("article_id", String(64), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("data", JSON, nullable=False),
    Column("actor", String(128), nullable=False),
    Column("reason", Text, nullable=False),
    UniqueConstraint("article_id", "revision", name="uq_df_article_revision"),
)
snapshots = scoped(
    "snapshots",
    Column("digest", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("mode", String(16), nullable=False),
    Column("kind", String(24), nullable=False),
    Column("window", JSON, nullable=False),
)
runs = scoped(
    "runs",
    Column("owner_id", String(128), nullable=False),
    Column("graph_revision", Integer, nullable=False),
    Column("graph", JSON, nullable=False),
    Column("status", String(24), nullable=False),
    Column("origin", String(24), nullable=False),
    Column("mode", String(16), nullable=False),
    Column("window", JSON, nullable=False),
    Column("idempotency_key", String(180), nullable=False),
    Column("replay_of", String(64)),
    Column("finished_at", Double),
    UniqueConstraint("tenant_id", "project_id", "idempotency_key", name="uq_df_run_key"),
)
tasks = scoped(
    "tasks",
    Column("run_id", String(64), nullable=False),
    Column("node_id", String(80), nullable=False),
    Column("node", JSON, nullable=False),
    Column("executor", String(16), nullable=False),
    Column("status", String(24), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("input_snapshot_id", String(64)),
    Column("output_snapshot_id", String(64)),
    Column("lease_token", String(64)),
    Column("lease_until", Double),
    Column("available_at", Double, nullable=False),
    Column("started_at", Double),
    Column("finished_at", Double),
    Column("error", Text),
    Column("thread_id", String(128)),
    Column("agent_run_id", String(128)),
    Column("context", JSON, nullable=False),
    UniqueConstraint("run_id", "node_id", name="uq_df_task_node"),
    Index("ix_df_task_claim", "executor", "status", "available_at"),
)
attempts = scoped(
    "attempts",
    Column("task_id", String(64), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("lease_token", String(64), nullable=False),
    Column("status", String(24), nullable=False),
    Column("error", Text),
    Column("finished_at", Double),
    Column("input_snapshot_id", String(64)),
    Column("output_snapshot_id", String(64)),
    UniqueConstraint("task_id", "attempt", name="uq_df_attempt"),
)
events = scoped(
    "events",
    Column("run_id", String(64)),
    Column("task_id", String(64)),
    Column("kind", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
)
outbox = scoped(
    "outbox",
    Column("task_id", String(64), nullable=False),
    Column("executor", String(16), nullable=False),
    Column("published_at", Double),
    Column("publish_attempts", Integer, nullable=False, default=0),
)
schedules = scoped(
    "schedules",
    Column("node_id", String(80), nullable=False),
    Column("owner_id", String(128), nullable=False),
    Column("trigger", JSON, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("mode", String(16), nullable=False),
    Column("next_at", Double, nullable=False),
    Column("last_at", Double),
    UniqueConstraint("tenant_id", "project_id", "node_id", name="uq_df_schedule_node"),
)
