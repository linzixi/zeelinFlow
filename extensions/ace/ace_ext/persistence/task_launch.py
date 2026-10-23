from __future__ import annotations

import time

from sqlalchemy import select

from ace_ext.core.contracts import Window
from ace_ext.persistence import schema as s
from ace_ext.persistence.articles import capture_articles, read_snapshot
from ace_ext.persistence.database import Scope, base, event, project
from ace_ext.persistence.task_state import enqueue
from ace_ext.workflow.models import Graph
from ace_ext.workflow.validation import reachable


def launch(
    connection,
    scope: Scope,
    project_id: str,
    *,
    origin: str,
    mode: str,
    key: str,
    window: Window,
    start: str | None = None,
    single: bool = False,
    input_snapshot_id: str | None = None,
    frozen: dict | None = None,
    replay_of: str | None = None,
) -> dict:
    current = project(connection, scope, project_id, lock=True)
    existing = (
        connection.execute(
            select(s.runs).where(
                s.runs.c.tenant_id == scope.tenant_id,
                s.runs.c.project_id == project_id,
                s.runs.c.idempotency_key == key,
            )
        )
        .mappings()
        .first()
    )
    if existing:
        return dict(existing)
    definition = frozen or current
    graph = Graph.model_validate(definition["graph"])
    selected = reachable(graph, start, single)
    if not selected:
        raise ValueError("没有可执行的节点")
    if input_snapshot_id:
        captured = read_snapshot(connection, scope, project_id, input_snapshot_id)
        if captured["mode"] != mode:
            raise ValueError("不能跨模拟/正式模式使用快照")
    else:
        input_snapshot_id = capture_articles(connection, scope, project_id, window, mode)
    run = dict(
        **base(scope, project_id),
        owner_id=scope.owner_id,
        graph_revision=definition["revision"],
        graph=graph.model_dump(mode="json"),
        status="running",
        origin=origin,
        mode=mode,
        window=window.model_dump(mode="json"),
        idempotency_key=key,
        replay_of=replay_of,
        finished_at=None,
    )
    connection.execute(s.runs.insert().values(**run))
    _create_tasks(connection, scope, project_id, graph, selected, run, input_snapshot_id)
    event(
        connection,
        scope,
        project_id,
        "run.created",
        {"graph_revision": run["graph_revision"]},
        run_id=run["id"],
    )
    return run


def _create_tasks(connection, scope, project_id, graph, selected, run, input_snapshot_id):
    for node in graph.nodes:
        if node.id not in selected:
            continue
        parents = [
            edge.source
            for edge in graph.edges
            if edge.target == node.id and edge.source in selected and not edge.executionDisabled
        ]
        task = dict(
            **base(scope, project_id),
            run_id=run["id"],
            node_id=node.id,
            node=node.model_dump(mode="json"),
            executor=node.executor,
            status="blocked" if parents else "queued",
            attempt=0,
            max_attempts=3,
            input_snapshot_id=None if parents else input_snapshot_id,
            output_snapshot_id=None,
            available_at=time.time(),
            context={
                "origin": run["origin"],
                "mode": run["mode"],
                "window": run["window"],
                "owner_id": scope.owner_id,
                "actor_id": scope.actor,
                "schemaVersion": 1,
            },
            lease_token=None,
            lease_until=None,
            error=None,
            thread_id=None,
            agent_run_id=None,
            started_at=None,
            finished_at=None,
        )
        connection.execute(s.tasks.insert().values(**task))
        if task["status"] == "queued":
            enqueue(connection, scope, task)
