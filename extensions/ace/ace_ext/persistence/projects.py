from __future__ import annotations

import time
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ace_ext.core.errors import Conflict
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import (
    Database,
    Scope,
    base,
    event,
    identifier,
    project,
    where_scope,
)
from ace_ext.persistence.schedules import sync_schedules
from ace_ext.workflow.models import Graph


class ProjectRepository:
    def __init__(self, database: Database):
        self.db = database

    def list(self, scope: Scope) -> list[dict]:
        with self.db.transaction() as connection:
            query = (
                select(s.projects)
                .where(
                    s.projects.c.tenant_id == scope.tenant_id,
                    s.projects.c.owner_id == scope.owner_id,
                    s.projects.c.deleted_at.is_(None),
                )
                .order_by(s.projects.c.updated_at.desc())
            )
            return [dict(row) for row in connection.execute(query).mappings()]

    def get(self, scope: Scope, project_id: str) -> dict:
        with self.db.transaction() as connection:
            return project(connection, scope, project_id)

    def create(
        self,
        scope: Scope,
        name: str,
        graph: Graph,
        *,
        source: dict | None = None,
        project_id: str | None = None,
        connection=None,
    ) -> dict:
        project_id = project_id or identifier()
        if connection is None:
            with self.db.transaction() as current:
                return self.create(
                    scope, name, graph, source=source, project_id=project_id, connection=current
                )
        else:
            row = dict(
                **base(scope, project_id, key=project_id),
                owner_id=scope.owner_id,
                name=name,
                description="",
                revision=1,
                graph=graph.model_dump(mode="json"),
                source=source or {},
                updated_at=time.time(),
                deleted_at=None,
            )
            connection.execute(s.projects.insert().values(**row))
            self._revision(connection, scope, row)
            return row

    def save(
        self, scope: Scope, project_id: str, graph: Graph, revision: int, *, name: str | None = None
    ) -> dict:
        with self.db.transaction() as connection:
            current = project(connection, scope, project_id, lock=True)
            if current["revision"] != revision:
                raise Conflict("画布已被其他窗口修改，请重新加载后合并")
            changes = dict(
                revision=revision + 1,
                graph=graph.model_dump(mode="json"),
                updated_at=time.time(),
                name=name or current["name"],
            )
            updated = connection.execute(
                s.projects.update()
                .where(s.projects.c.id == project_id, s.projects.c.revision == revision)
                .values(**changes)
            )
            if updated.rowcount != 1:
                raise Conflict("画布版本冲突")
            result = {**current, **changes}
            self._revision(connection, scope, result)
            return result

    def ensure_sample(self, scope: Scope, name: str, graph: Graph, source: dict) -> dict:
        existing = next(
            (item for item in self.list(scope) if item["source"].get("sample") == source["sample"]),
            None,
        )
        if existing:
            return existing
        key = uuid.uuid5(
            uuid.NAMESPACE_URL, f"ace:{scope.tenant_id}:{scope.owner_id}:{source['sample']}"
        ).hex
        try:
            return self.create(scope, name, graph, source=source, project_id=key)
        except IntegrityError:
            # 并发首访由唯一主键决定胜者，失败方读取同一个正式样例。
            return self.get(scope, key)

    def history(self, scope: Scope, project_id: str) -> list[dict]:
        with self.db.transaction() as connection:
            project(connection, scope, project_id)
            query = select(s.graphs).where(where_scope(s.graphs, scope, project_id))
            return [
                dict(row)
                for row in connection.execute(query.order_by(s.graphs.c.revision.desc())).mappings()
            ]

    @staticmethod
    def _revision(connection, scope: Scope, row: dict) -> None:
        connection.execute(
            s.graphs.insert().values(
                **base(scope, row["id"]),
                revision=row["revision"],
                graph=row["graph"],
                actor=scope.actor,
            )
        )
        event(connection, scope, row["id"], "graph.saved", {"revision": row["revision"]})
        sync_schedules(connection, scope, row)
