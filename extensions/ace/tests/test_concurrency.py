from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import select

from ace_ext.core.contracts import Envelope, Window
from ace_ext.persistence import schema as s
from ace_ext.persistence.projects import ProjectRepository
from ace_ext.persistence.tasks import TaskRepository
from ace_ext.workflow.models import Graph


def test_mysql_simultaneous_parents_release_join_once(database, scope, monkeypatch):
    if database.engine.dialect.name != "mysql":
        pytest.skip("验证 MySQL MVCC 与真实并发连接")
    graph = Graph.model_validate(
        {
            "nodes": [
                {"id": key, "title": key, "type": "code_agent"} for key in ("a", "b", "join")
            ],
            "edges": [{"id": key, "source": key, "target": "join"} for key in ("a", "b")],
        }
    )
    project = ProjectRepository(database).create(scope, "并发汇合", graph)
    repo = TaskRepository(database, tenant_id=scope.tenant_id)
    now = datetime.now(UTC)
    run = repo.launch(
        scope,
        project["id"],
        mode="simulation",
        origin="manual",
        key="join",
        window=Window(start=now - timedelta(minutes=150), end=now),
    )
    parents = [repo.claim("data", lease_seconds=60) for _ in range(2)]
    barrier = Barrier(2)
    original = repo._fenced

    def synchronized(connection, task_id, token, **kwargs):
        connection.execute(select(s.tasks.c.run_id).where(s.tasks.c.id == task_id)).scalar_one()
        barrier.wait(timeout=10)
        return original(connection, task_id, token, **kwargs)

    monkeypatch.setattr(repo, "_fenced", synchronized)
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(
                repo.complete,
                task["id"],
                task["lease_token"],
                Envelope(records=[{"id": task["node_id"]}]),
            )
            for task in parents
        ]
        for future in futures:
            future.result(timeout=20)
    monkeypatch.setattr(repo, "_fenced", original)
    join = repo.claim("data", lease_seconds=60)
    assert join and join["node_id"] == "join"
    assert {record["id"] for record in repo.input(join)["records"]} == {"a", "b"}
    assert repo.claim("data", lease_seconds=60) is None
    repo.complete(join["id"], join["lease_token"], Envelope())
    assert repo.detail(scope, project["id"], run["id"])["status"] == "succeeded"
