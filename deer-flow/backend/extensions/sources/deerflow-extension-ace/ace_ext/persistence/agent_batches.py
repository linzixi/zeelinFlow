from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, Integer, String, UniqueConstraint, select

from ace_ext.persistence.database import Scope, base, event
from ace_ext.persistence.schema import scoped

batches = scoped(
    "agent_batches",
    Column("task_id", String(64), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("thread_id", String(64), nullable=False),
    Column("run_id", String(64)),
    Column("result", JSON),
    UniqueConstraint("task_id", "attempt", "ordinal", name="uq_df_batch"),
)


def prepare(repo, task, ordinal):
    with repo.db.transaction() as connection:
        repo._fenced(connection, task["id"], task["lease_token"])
        row = (
            connection.execute(
                select(batches).where(
                    batches.c.task_id == task["id"],
                    batches.c.attempt == task["attempt"],
                    batches.c.ordinal == ordinal,
                )
            )
            .mappings()
            .first()
        )
        if row:
            return dict(row)
        # 同一冻结任务的人工重试复用成功批次，失败/未知结果仍走独立新回执。
        previous = connection.execute(
            select(batches)
            .where(
                batches.c.task_id == task["id"],
                batches.c.ordinal == ordinal,
                batches.c.attempt < task["attempt"],
            )
            .order_by(batches.c.attempt.desc())
        ).mappings()
        for cached in previous:
            values = cached["result"]
            if isinstance(values, list) and (not values or "_batch_error" not in values[0]):
                return dict(cached)
        row = {
            **base(Scope(task["tenant_id"], task["context"]["owner_id"]), task["project_id"]),
            "task_id": task["id"],
            "attempt": task["attempt"],
            "ordinal": ordinal,
            "thread_id": str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"ace:{task['id']}:{task['attempt']}:{ordinal}")
            ),
            "run_id": None,
            "result": None,
        }
        connection.execute(batches.insert().values(**row))
        return row


def save(repo, task, batch, **values):
    with repo.db.transaction() as connection:
        repo._fenced(connection, task["id"], task["lease_token"])
        connection.execute(batches.update().where(batches.c.id == batch["id"]).values(**values))
        event(
            connection,
            Scope(task["tenant_id"], task["context"]["owner_id"]),
            task["project_id"],
            "agent.batch_completed" if "result" in values else "agent.batch_started",
            {
                "batch": batch["ordinal"],
                "thread_id": batch["thread_id"],
                "run_id": values.get("run_id", batch.get("run_id")),
            },
            run_id=task["run_id"],
            task_id=task["id"],
        )
    batch.update(values)


def completed(repo, task, ordinal):
    """查找同一冻结任务中已成功的逻辑批次，包括之前重试的成功回执。"""
    with repo.db.transaction() as connection:
        repo._fenced(connection, task["id"], task["lease_token"])
        rows = connection.execute(
            select(batches)
            .where(
                batches.c.task_id == task["id"],
                batches.c.ordinal.between(ordinal * 10, ordinal * 10 + 9),
                batches.c.attempt <= task["attempt"],
            )
            .order_by(batches.c.attempt.desc(), batches.c.ordinal.desc())
        ).mappings()
        for row in rows:
            result = row["result"]
            if isinstance(result, list) and (not result or "_batch_error" not in result[0]):
                return dict(row)
    return None
