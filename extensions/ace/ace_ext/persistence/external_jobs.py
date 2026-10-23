from __future__ import annotations

import time

from sqlalchemy import JSON, Column, Double, String, UniqueConstraint, select

from ace_ext.core.errors import LeaseLost
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import Scope, base, digest, event

jobs = s.scoped(
    "external_jobs",
    Column("task_id", String(64), nullable=False),
    Column("article_id", String(64), nullable=False),
    Column("source_hash", String(64), nullable=False),
    Column("state", String(32), nullable=False),
    Column("data", JSON, nullable=False),
    Column("updated_at", Double, nullable=False),
    UniqueConstraint("task_id", "article_id", name="uq_df_external_article"),
)


def fence(connection, task: dict):
    row = (
        connection.execute(select(s.tasks).where(s.tasks.c.id == task["id"]).with_for_update())
        .mappings()
        .one()
    )
    if row["lease_token"] != task["lease_token"] or row["lease_until"] < time.time():
        raise LeaseLost("外部任务租约已失效")


def prepare(database, task: dict, article: dict) -> dict:
    scope = Scope(task["tenant_id"], task["context"]["owner_id"])
    with database.transaction() as connection:
        fence(connection, task)
        row = (
            connection.execute(
                select(jobs).where(jobs.c.task_id == task["id"], jobs.c.article_id == article["id"])
            )
            .mappings()
            .first()
        )
        if row:
            return dict(row)
        source_hash = digest(
            {"url": article["url"], "videos": article.get("raw", {}).get("news_video_urls")}
        )
        cached = (
            connection.execute(
                select(jobs)
                .where(
                    jobs.c.tenant_id == task["tenant_id"],
                    jobs.c.project_id == task["project_id"],
                    jobs.c.article_id == article["id"],
                    jobs.c.source_hash == source_hash,
                    jobs.c.state == "completed",
                )
                .order_by(jobs.c.updated_at.desc())
            )
            .mappings()
            .first()
        )
        now = time.time()
        row = dict(
            **base(scope, task["project_id"]),
            task_id=task["id"],
            article_id=article["id"],
            source_hash=source_hash,
            state="completed" if cached else "queued",
            updated_at=now,
            data={
                **(cached["data"] if cached else {}),
                "errors": 0,
                "began_at": now,
                **({"cached_from": cached["id"]} if cached else {}),
            },
        )
        connection.execute(jobs.insert().values(**row))
        return row


def save(database, task: dict, job: dict, state: str, **fields) -> None:
    scope = Scope(task["tenant_id"], task["context"]["owner_id"])
    with database.transaction() as connection:
        fence(connection, task)
        job.update(state=state, data={**job["data"], **fields}, updated_at=time.time())
        connection.execute(
            jobs.update()
            .where(jobs.c.id == job["id"])
            .values(state=state, data=job["data"], updated_at=job["updated_at"])
        )
        event(
            connection,
            scope,
            task["project_id"],
            "sgm.sis." + state,
            {
                "article_id": job["article_id"],
                "job_id": job["id"],
                "error": fields.get("error", ""),
            },
            run_id=task["run_id"],
            task_id=task["id"],
        )
