from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from ace_ext.core.contracts import Window
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import Database, Scope, base, project, where_scope
from ace_ext.persistence.task_launch import launch
from ace_ext.workflow.models import Graph, Trigger
from ace_ext.workflow.scheduling import next_occurrence


def sync_schedules(connection, scope: Scope, row: dict) -> None:
    existing = {
        item["node_id"]: dict(item)
        for item in connection.execute(
            select(s.schedules).where(where_scope(s.schedules, scope, row["id"]))
        ).mappings()
    }
    for node in Graph.model_validate(row["graph"]).nodes:
        current = existing.pop(node.id, None)
        if node.trigger.kind != "cron":
            if current:
                connection.execute(
                    s.schedules.update()
                    .where(s.schedules.c.id == current["id"])
                    .values(enabled=False)
                )
            continue
        data = node.trigger.model_dump(mode="json")
        enabled = node.trigger.enabled and node.enabled
        if current and current["trigger"] == data and current["enabled"] == enabled:
            continue
        values = dict(
            node_id=node.id,
            owner_id=scope.owner_id,
            trigger=data,
            enabled=enabled,
            mode=node.trigger.mode,
            next_at=next_occurrence(node.trigger, datetime.now(UTC)).timestamp(),
        )
        if current:
            connection.execute(
                s.schedules.update().where(s.schedules.c.id == current["id"]).values(**values)
            )
        else:
            connection.execute(s.schedules.insert().values(**base(scope, row["id"]), **values))
    for current in existing.values():
        connection.execute(
            s.schedules.update().where(s.schedules.c.id == current["id"]).values(enabled=False)
        )


class ScheduleRepository:
    def __init__(self, database: Database, tenant_id: str):
        self.db, self.tenant_id = database, tenant_id

    def dispatch_due(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(UTC)
        with self.db.transaction() as connection:
            due = (
                connection.execute(
                    select(s.schedules)
                    .join(s.projects, s.projects.c.id == s.schedules.c.project_id)
                    .where(
                        s.projects.c.deleted_at.is_(None),
                        s.schedules.c.tenant_id == self.tenant_id,
                        s.schedules.c.enabled.is_(True),
                        s.schedules.c.next_at <= now.timestamp(),
                    )
                    .order_by(s.schedules.c.next_at)
                    .limit(20)
                )
                .mappings()
                .all()
            )
        runs = []
        for item in due:
            dispatched = self._dispatch(dict(item), now)
            if dispatched:
                runs.append(dispatched)
        return runs

    def _dispatch(self, item: dict, now: datetime) -> str | None:
        scope = Scope(item["tenant_id"], item["owner_id"])
        with self.db.transaction() as connection:
            # 保存和调度均先锁项目，再锁触发器，避免相反锁序。
            project(connection, scope, item["project_id"], lock=True)
            current = (
                connection.execute(
                    select(s.schedules).where(s.schedules.c.id == item["id"]).with_for_update()
                )
                .mappings()
                .one()
            )
            if not current["enabled"] or current["next_at"] > now.timestamp():
                return None
            trigger = Trigger.model_validate(current["trigger"])
            at = datetime.fromtimestamp(current["next_at"], UTC)
            window = Window(start=at - timedelta(minutes=trigger.lookbackMinutes), end=at)
            run = launch(
                connection,
                scope,
                item["project_id"],
                origin="scheduled",
                mode=current["mode"],
                key=f"schedule:{item['id']}:{at.isoformat()}",
                window=window,
                start=item["node_id"],
            )
            connection.execute(
                s.schedules.update()
                .where(s.schedules.c.id == item["id"])
                .values(last_at=at.timestamp(), next_at=next_occurrence(trigger, at).timestamp())
            )
            return run["id"]
