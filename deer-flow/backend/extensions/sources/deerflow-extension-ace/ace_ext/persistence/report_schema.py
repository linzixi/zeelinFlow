from __future__ import annotations

from sqlalchemy import JSON, Column, Double, Integer, String, UniqueConstraint

from ace_ext.persistence.schema import scoped

datasets = scoped(
    "report_datasets",
    Column("task_id", String(64), nullable=False, unique=True),
    Column("thread_id", String(64), nullable=False, unique=True),
    Column("actor_id", String(128), nullable=False),
    Column("snapshot_id", String(64), nullable=False),
    Column("window", JSON, nullable=False),
    Column("mode", String(16), nullable=False),
    Column("row_count", Integer, nullable=False),
)
facts = scoped(
    "report_facts",
    Column("dataset_id", String(64), nullable=False, index=True),
    Column("article_id", String(64), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("ingested_at", Double, nullable=False),
    Column("sentiment", String(16), nullable=False),
    Column("platform", String(200), nullable=False),
    Column("source", String(200), nullable=False),
    Column("brand", String(1000), nullable=False),
    Column("problem", String(1000), nullable=False),
    Column("review_status", String(32), nullable=False),
    Column("assessment_status", String(32), nullable=False),
    Column("data", JSON, nullable=False),
    UniqueConstraint("dataset_id", "article_id", name="uq_df_report_fact"),
)
queries = scoped(
    "report_queries",
    Column("dataset_id", String(64), nullable=False, index=True),
    Column("thread_id", String(64), nullable=False),
    Column("actor_id", String(128), nullable=False),
    Column("spec", JSON, nullable=False),
    Column("result", JSON, nullable=False),
)
