from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Connection, create_engine, select
from sqlalchemy.pool import StaticPool

from ace_ext.core.errors import NotFound
from ace_ext.persistence import schema as s


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    owner_id: str
    actor_id: str | None = None

    @property
    def actor(self) -> str:
        return self.actor_id or self.owner_id


def identifier() -> str:
    return uuid.uuid4().hex


def digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def base(scope: Scope, project_id: str, *, key: str | None = None) -> dict:
    return dict(
        id=key or identifier(),
        tenant_id=scope.tenant_id,
        project_id=project_id,
        created_at=time.time(),
    )


class Database:
    def __init__(self, url: str, *, echo: bool = False):
        options = {"pool_pre_ping": True, "echo": echo}
        # 状态更新在 run 行锁下串行化；汇合读取必须看到前一持锁事务的提交。
        if url.startswith("mysql"):
            options["isolation_level"] = "READ COMMITTED"
        if url == "sqlite://":
            options.update(poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.engine = create_engine(url, **options)

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.begin() as connection:
            yield connection

    def close(self) -> None:
        self.engine.dispose()


def project(connection: Connection, scope: Scope, project_id: str, *, lock=False) -> dict:
    query = select(s.projects).where(
        s.projects.c.id == project_id,
        s.projects.c.tenant_id == scope.tenant_id,
        s.projects.c.owner_id == scope.owner_id,
        s.projects.c.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().first()
    if row is None:
        raise NotFound("项目不存在或没有访问权限")
    return dict(row)


def where_scope(table, scope: Scope, project_id: str):
    return (table.c.tenant_id == scope.tenant_id) & (table.c.project_id == project_id)


def event(
    connection: Connection,
    scope: Scope,
    project_id: str,
    kind: str,
    payload: dict,
    *,
    run_id: str | None = None,
    task_id: str | None = None,
) -> None:
    connection.execute(
        s.events.insert().values(
            **base(scope, project_id), kind=kind, payload=payload, run_id=run_id, task_id=task_id
        )
    )


def snapshot(
    connection: Connection,
    scope: Scope,
    project_id: str,
    payload: dict,
    *,
    mode: str,
    kind: str,
    window: dict,
) -> str:
    row = dict(
        **base(scope, project_id),
        digest=digest(payload),
        payload=payload,
        mode=mode,
        kind=kind,
        window=window,
    )
    connection.execute(s.snapshots.insert().values(**row))
    return row["id"]
