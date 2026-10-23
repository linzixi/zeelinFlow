from __future__ import annotations

import time

from sqlalchemy import select

from ace_ext.core.contracts import Envelope, Window
from ace_ext.core.errors import Conflict, LeaseLost, NotFound
from ace_ext.persistence import schema as s
from ace_ext.persistence.articles import read_snapshot
from ace_ext.persistence.database import (
    Database,
    Scope,
    base,
    event,
    identifier,
    project,
    snapshot,
    where_scope,
)
from ace_ext.persistence.results import persist_results
from ace_ext.persistence.task_launch import launch
from ace_ext.persistence.task_state import TERMINAL, advance, enqueue


class TaskRepository:
    def __init__(self, database: Database, *, tenant_id: str | None = None):
        self.db = database
        self.tenant_id = tenant_id

    def launch(self, scope: Scope, project_id: str, **options) -> dict:
        with self.db.transaction() as connection:
            return launch(connection, scope, project_id, **options)

    def claim(self, executor: str, *, lease_seconds: int, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        with self.db.transaction() as connection:
            query = (
                select(s.tasks)
                .join(s.projects, s.projects.c.id == s.tasks.c.project_id)
                .join(s.runs, s.runs.c.id == s.tasks.c.run_id)
                .where(
                    s.tasks.c.executor == executor,
                    s.tasks.c.status == "queued",
                    s.tasks.c.available_at <= now,
                    s.projects.c.deleted_at.is_(None),
                    s.runs.c.status == "running",
                )
            )
            if self.tenant_id:
                query = query.where(s.tasks.c.tenant_id == self.tenant_id)
            row = (
                connection.execute(
                    query.order_by(s.tasks.c.created_at, s.tasks.c.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            task = dict(row)
            changes = dict(
                status="running",
                attempt=task["attempt"] + (0 if task["thread_id"] else 1),
                lease_token=identifier(),
                lease_until=now + lease_seconds,
                started_at=now,
                finished_at=None,
                error=None,
            )
            result = connection.execute(
                s.tasks.update()
                .where(s.tasks.c.id == task["id"], s.tasks.c.status == "queued")
                .values(**changes)
            )
            if result.rowcount != 1:
                return None
            task.update(changes)
            scope = Scope(task["tenant_id"], task["context"]["owner_id"])
            self._record_attempt(connection, scope, task)
            event(
                connection,
                scope,
                task["project_id"],
                "task.started",
                {"attempt": task["attempt"]},
                run_id=task["run_id"],
                task_id=task["id"],
            )
            return task

    def input(self, task: dict) -> dict:
        with self.db.transaction() as connection:
            return read_snapshot(
                connection,
                Scope(task["tenant_id"], task["context"]["owner_id"]),
                task["project_id"],
                task["input_snapshot_id"],
            )["payload"]

    def heartbeat(self, task_id: str, token: str, *, lease_seconds: int) -> None:
        with self.db.transaction() as connection:
            self._fenced(connection, task_id, token)
            connection.execute(
                s.tasks.update()
                .where(s.tasks.c.id == task_id)
                .values(lease_until=time.time() + lease_seconds)
            )

    def agent_started(self, task_id: str, token: str, thread_id: str, run_id: str) -> None:
        with self.db.transaction() as connection:
            task = self._fenced(connection, task_id, token)
            connection.execute(
                s.tasks.update()
                .where(s.tasks.c.id == task_id)
                .values(status="waiting_agent", thread_id=thread_id, agent_run_id=run_id)
            )
            event(
                connection,
                Scope(task["tenant_id"], task["context"]["owner_id"]),
                task["project_id"],
                "agent.started",
                {"thread_id": thread_id, "run_id": run_id},
                run_id=task["run_id"],
                task_id=task_id,
            )

    def agent_intent(self, task_id: str, token: str, thread_id: str) -> None:
        with self.db.transaction() as connection:
            task = self._fenced(connection, task_id, token)
            context = dict(task["context"])
            if task["thread_id"] != thread_id:
                context.pop("agent_terminal_status", None)
            connection.execute(
                s.tasks.update()
                .where(s.tasks.c.id == task_id)
                .values(status="waiting_agent", thread_id=thread_id, context=context)
            )

    def agent_terminal(self, task_id: str, token: str, status: str) -> None:
        with self.db.transaction() as connection:
            task = self._fenced(connection, task_id, token)
            context = {**task["context"], "agent_terminal_status": status}
            connection.execute(
                s.tasks.update().where(s.tasks.c.id == task_id).values(context=context)
            )

    def complete(self, task_id: str, token: str, output: Envelope) -> None:
        with self.db.transaction() as connection:
            task = self._fenced(connection, task_id, token)
            scope = Scope(task["tenant_id"], task["context"]["owner_id"])
            persist_results(connection, task, output)
            output_id = snapshot(
                connection,
                scope,
                task["project_id"],
                output.model_dump(mode="json"),
                mode=task["context"]["mode"],
                kind="node_output",
                window=task["context"]["window"],
            )
            self._finish(connection, task, "succeeded", output_id=output_id)
            event(
                connection,
                scope,
                task["project_id"],
                "task.succeeded",
                {"output_snapshot_id": output_id, "count": len(output.records)},
                run_id=task["run_id"],
                task_id=task_id,
            )
            advance(connection, task["run_id"])

    def fail(self, task_id: str, token: str, message: str, *, retryable: bool = True) -> None:
        with self.db.transaction() as connection:
            task = self._fenced(connection, task_id, token)
            scope = Scope(task["tenant_id"], task["context"]["owner_id"])
            unresolved = task["thread_id"] and not task["context"].get("agent_terminal_status")
            self._finish(
                connection, task, "waiting_review" if unresolved else "failed", error=message
            )
            # 已启动 Agent 的未知结果必须先对账，禁止以重试制造第二个运行。
            if retryable and not task["thread_id"] and task["attempt"] < task["max_attempts"]:
                changes = dict(
                    status="queued",
                    available_at=time.time() + 2 ** task["attempt"],
                    finished_at=None,
                )
                connection.execute(
                    s.tasks.update().where(s.tasks.c.id == task_id).values(**changes)
                )
                enqueue(connection, scope, {**task, **changes})
            else:
                advance(connection, task["run_id"])
            event(
                connection,
                scope,
                task["project_id"],
                "task.failed",
                {"message": message},
                run_id=task["run_id"],
                task_id=task_id,
            )

    def defer(self, task_id: str, token: str, *, at: float, reason: str) -> None:
        with self.db.transaction() as connection:
            task = self._fenced(connection, task_id, token)
            self._finish(connection, task, "deferred", error=reason)
            connection.execute(
                s.tasks.update()
                .where(s.tasks.c.id == task_id)
                .values(
                    status="queued",
                    available_at=at,
                    finished_at=None,
                    max_attempts=task["max_attempts"] + 1,
                )
            )
            event(
                connection,
                Scope(task["tenant_id"], task["context"]["owner_id"]),
                task["project_id"],
                "task.deferred",
                {"available_at": at, "reason": reason},
                run_id=task["run_id"],
                task_id=task_id,
            )

    def recover_expired(self, *, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self.db.transaction() as connection:
            query = select(s.tasks.c.id, s.tasks.c.lease_token).where(
                s.tasks.c.status.in_(["running", "waiting_agent"]), s.tasks.c.lease_until < now
            )
            if self.tenant_id:
                query = query.where(s.tasks.c.tenant_id == self.tenant_id)
            expired = connection.execute(query).all()
        count = 0
        for task_id, token in expired:
            try:
                count += self._recover_one(task_id, token, now)
            except LeaseLost:
                # 另一恢复者或心跳已推进此任务，继续扫描其余任务。
                continue
        return count

    def _recover_one(self, task_id: str, token: str, now: float) -> int:
        with self.db.transaction() as connection:
            task = self._fenced(connection, task_id, token, allow_expired=True)
            if task["lease_until"] >= now:
                return 0
            scope = Scope(task["tenant_id"], task["context"]["owner_id"])
            self._finish(connection, task, "failed", error="执行进程租约到期")
            status = (
                "queued"
                if task["thread_id"]
                else ("queued" if task["attempt"] < task["max_attempts"] else "failed")
            )
            connection.execute(
                s.tasks.update()
                .where(s.tasks.c.id == task_id)
                .values(
                    status=status,
                    available_at=now,
                    finished_at=None if status != "failed" else now,
                )
            )
            if status == "queued":
                enqueue(connection, scope, task)
            event(
                connection,
                scope,
                task["project_id"],
                "task.lease_expired",
                {"next_status": status},
                run_id=task["run_id"],
                task_id=task_id,
            )
            advance(connection, task["run_id"])
            return 1

    def list(self, scope: Scope, project_id: str, *, limit: int = 30) -> list[dict]:
        with self.db.transaction() as connection:
            project(connection, scope, project_id)
            columns = [column for column in s.runs.c if column.name != "graph"]
            return [
                dict(row)
                for row in connection.execute(
                    select(*columns)
                    .where(where_scope(s.runs, scope, project_id))
                    .order_by(s.runs.c.created_at.desc())
                    .limit(min(limit, 100))
                ).mappings()
            ]

    def detail(self, scope: Scope, project_id: str, run_id: str) -> dict:
        with self.db.transaction() as connection:
            project(connection, scope, project_id)
            run = self._run(connection, scope, project_id, run_id)
            run["tasks"] = [
                dict(row)
                for row in connection.execute(
                    select(s.tasks).where(s.tasks.c.run_id == run_id).order_by(s.tasks.c.created_at)
                ).mappings()
            ]
            run["events"] = [
                dict(row)
                for row in connection.execute(
                    select(s.events)
                    .where(s.events.c.run_id == run_id)
                    .order_by(s.events.c.created_at)
                ).mappings()
            ]
            return run

    def retry(self, scope: Scope, project_id: str, task_id: str) -> dict:
        with self.db.transaction() as connection:
            project(connection, scope, project_id, lock=True)
            task = self._owned_task(connection, scope, project_id, task_id)
            run = self._run(connection, scope, project_id, task["run_id"])
            if task["status"] not in ("failed", "waiting_review") or run["status"] == "cancelled":
                raise Conflict("仅可恢复已失败或等待核对的任务")
            if task["context"].get("agent_terminal_status"):
                context = {
                    key: value
                    for key, value in task["context"].items()
                    if key != "agent_terminal_status"
                }
                event(
                    connection,
                    scope,
                    project_id,
                    "agent.retry_authorized",
                    {
                        "previous_thread_id": task["thread_id"],
                        "previous_run_id": task["agent_run_id"],
                        "attempt": task["attempt"],
                    },
                    run_id=task["run_id"],
                    task_id=task_id,
                )
                connection.execute(
                    s.tasks.update()
                    .where(s.tasks.c.id == task_id)
                    .values(thread_id=None, agent_run_id=None, context=context)
                )
            connection.execute(
                s.tasks.update()
                .where(s.tasks.c.id == task_id)
                .values(
                    status="queued",
                    max_attempts=task["attempt"] + 3,
                    finished_at=None,
                    error=None,
                    available_at=time.time(),
                )
            )
            connection.execute(
                s.tasks.update()
                .where(s.tasks.c.run_id == task["run_id"], s.tasks.c.status == "skipped")
                .values(status="blocked", finished_at=None)
            )
            connection.execute(
                s.runs.update()
                .where(s.runs.c.id == task["run_id"])
                .values(status="running", finished_at=None)
            )
            enqueue(connection, scope, task)
            return {"task_id": task_id, "status": "queued"}

    def replay(
        self, scope: Scope, project_id: str, task_id: str, *, key: str, downstream=False
    ) -> dict:
        with self.db.transaction() as connection:
            project(connection, scope, project_id, lock=True)
            task = self._owned_task(connection, scope, project_id, task_id)
            run = self._run(connection, scope, project_id, task["run_id"])
            if task["status"] not in TERMINAL or not task["input_snapshot_id"]:
                raise Conflict("仅可回溯有输入快照的已结束任务")
            return launch(
                connection,
                scope,
                project_id,
                origin="replay",
                mode=run["mode"],
                key=key,
                window=Window.model_validate(run["window"]),
                start=task["node_id"],
                single=not downstream,
                input_snapshot_id=task["input_snapshot_id"],
                frozen={"graph": run["graph"], "revision": run["graph_revision"]},
                replay_of=run["id"],
            )

    def cancel(self, scope: Scope, project_id: str, run_id: str) -> dict:
        with self.db.transaction() as connection:
            project(connection, scope, project_id)
            run = self._run(connection, scope, project_id, run_id)
            if run["status"] in TERMINAL:
                return run
            connection.execute(
                s.runs.update()
                .where(s.runs.c.id == run_id)
                .values(status="cancelled", finished_at=time.time())
            )
            active = (
                connection.execute(
                    select(s.tasks).where(
                        s.tasks.c.run_id == run_id, s.tasks.c.status.not_in(TERMINAL)
                    )
                )
                .mappings()
                .all()
            )
            for row in active:
                self._finish(connection, dict(row), "cancelled")
            event(connection, scope, project_id, "run.cancelled", {}, run_id=run_id)
            return {**run, "status": "cancelled", "tasks": [dict(row) for row in active]}

    @staticmethod
    def _run(connection, scope: Scope, project_id: str, run_id: str) -> dict:
        row = (
            connection.execute(
                select(s.runs)
                .where(where_scope(s.runs, scope, project_id), s.runs.c.id == run_id)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if row is None:
            raise NotFound("运行记录不存在")
        return dict(row)

    @staticmethod
    def _owned_task(connection, scope: Scope, project_id: str, task_id: str) -> dict:
        row = (
            connection.execute(
                select(s.tasks)
                .where(where_scope(s.tasks, scope, project_id), s.tasks.c.id == task_id)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if row is None:
            raise NotFound("任务不存在")
        return dict(row)

    @staticmethod
    def _fenced(connection, task_id: str, token: str, *, allow_expired: bool = False) -> dict:
        run_id = connection.execute(
            select(s.tasks.c.run_id).where(s.tasks.c.id == task_id)
        ).scalar()
        connection.execute(select(s.runs.c.id).where(s.runs.c.id == run_id).with_for_update())
        row = (
            connection.execute(select(s.tasks).where(s.tasks.c.id == task_id).with_for_update())
            .mappings()
            .first()
        )
        if (
            row is None
            or row["lease_token"] != token
            or row["status"] not in ("running", "waiting_agent")
            or (not allow_expired and row["lease_until"] < time.time())
        ):
            raise LeaseLost("任务租约已失效，本次结果不能写回")
        return dict(row)

    @staticmethod
    def _finish(
        connection,
        task: dict,
        status: str,
        *,
        error: str | None = None,
        output_id: str | None = None,
    ) -> None:
        connection.execute(
            s.tasks.update()
            .where(s.tasks.c.id == task["id"])
            .values(
                status=status,
                error=error,
                output_snapshot_id=output_id,
                lease_token=None,
                lease_until=None,
                finished_at=time.time(),
            )
        )
        connection.execute(
            s.attempts.update()
            .where(s.attempts.c.task_id == task["id"], s.attempts.c.attempt == task["attempt"])
            .values(
                status=status, error=error, output_snapshot_id=output_id, finished_at=time.time()
            )
        )

    @staticmethod
    def _record_attempt(connection, scope: Scope, task: dict) -> None:
        attempt_values = dict(
            lease_token=task["lease_token"],
            status="running",
            error=None,
            output_snapshot_id=None,
            finished_at=None,
        )
        if task["thread_id"]:
            connection.execute(
                s.attempts.update()
                .where(s.attempts.c.task_id == task["id"], s.attempts.c.attempt == task["attempt"])
                .values(**attempt_values)
            )
        else:
            connection.execute(
                s.attempts.insert().values(
                    **base(scope, task["project_id"]),
                    task_id=task["id"],
                    attempt=task["attempt"],
                    input_snapshot_id=task["input_snapshot_id"],
                    **attempt_values,
                )
            )
