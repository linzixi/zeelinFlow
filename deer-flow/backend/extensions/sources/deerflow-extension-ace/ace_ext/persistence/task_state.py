from __future__ import annotations

import time

from sqlalchemy import select

from ace_ext.persistence import schema as s
from ace_ext.persistence.articles import read_snapshot
from ace_ext.persistence.database import Scope, base, digest, event, snapshot

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "skipped"})


def enqueue(connection, scope: Scope, task: dict) -> None:
    connection.execute(
        s.outbox.insert().values(
            **base(scope, task["project_id"]),
            task_id=task["id"],
            executor=task["executor"],
            published_at=None,
            publish_attempts=0,
        )
    )
    event(
        connection,
        scope,
        task["project_id"],
        "task.queued",
        {},
        run_id=task["run_id"],
        task_id=task["id"],
    )


def _condition_matches(edge: dict, payload: dict) -> bool:
    key = edge.get("conditionKey", "")
    if not key:
        return True
    value = payload.get("context", {}).get(key, payload.get(key))
    if isinstance(value, list):
        return str(edge.get("conditionValue", "")).lower() in [str(x).lower() for x in value]
    return str(value).lower() == str(edge.get("conditionValue", "")).lower()


def routed_records(edge: dict, payload: dict) -> list[dict]:
    """Batch branches carry a per-record route map so mixed batches stay disjoint."""
    key = edge.get("conditionKey", "")
    routes = payload.get("context", {}).get("record_routes", {}).get(key)
    records = payload.get("records", [])
    if routes is None:
        return records
    expected = str(edge.get("conditionValue", "")).lower()
    return [
        row
        for row in records
        if expected
        in [
            str(value).lower()
            for value in (
                routes.get(row.get("id"), [])
                if isinstance(routes.get(row.get("id")), list)
                else [routes.get(row.get("id"))]
            )
        ]
    ]


def _merge_inputs(connection, scope: Scope, run: dict, parents: list[dict]) -> str:
    upstream, records, artifacts = {}, {}, []
    for parent in parents:
        payload = read_snapshot(connection, scope, run["project_id"], parent["output_snapshot_id"])[
            "payload"
        ]
        upstream[parent["node_id"]] = payload
        artifacts.extend(payload.get("artifacts", []))
        for record in routed_records(parent.get("input_edge", {}), payload):
            records[str(record.get("id") or digest(record))] = record
    payload = {
        "schemaVersion": 1,
        "records": list(records.values()),
        "artifacts": artifacts,
        "context": {"upstream": upstream, "origin": run["origin"], "mode": run["mode"]},
    }
    return snapshot(
        connection,
        scope,
        run["project_id"],
        payload,
        mode=run["mode"],
        kind="node_input",
        window=run["window"],
    )


def advance(connection, run_id: str) -> None:
    """调用方持有 run 行锁；结果、下游状态、Outbox 同事务提交。"""
    run = dict(
        connection.execute(select(s.runs).where(s.runs.c.id == run_id).with_for_update())
        .mappings()
        .one()
    )
    if run["status"] == "cancelled":
        return
    scope = Scope(run["tenant_id"], run["owner_id"])
    tasks = {
        row["node_id"]: dict(row)
        for row in connection.execute(select(s.tasks).where(s.tasks.c.run_id == run_id)).mappings()
    }
    changed = True
    while changed:
        changed = False
        for task in tasks.values():
            if task["status"] != "blocked":
                continue
            edges = [
                edge
                for edge in run["graph"]["edges"]
                if edge["target"] == task["node_id"]
                and not edge["executionDisabled"]
                and edge["source"] in tasks
            ]
            parents = [tasks[edge["source"]] for edge in edges]
            if not all(parent["status"] in TERMINAL for parent in parents):
                continue
            allowed = [
                {**parent, "input_edge": edge}
                for edge, parent in zip(edges, parents, strict=True)
                if parent["status"] == "succeeded"
                and _condition_matches(
                    edge,
                    read_snapshot(
                        connection, scope, run["project_id"], parent["output_snapshot_id"]
                    )["payload"],
                )
            ]
            rejected = any(parent["status"] in {"failed", "cancelled"} for parent in parents)
            if rejected or (parents and not allowed):
                changes = {"status": "skipped", "finished_at": time.time()}
            else:
                changes = {
                    "status": "queued",
                    "available_at": time.time(),
                    "input_snapshot_id": _merge_inputs(connection, scope, run, allowed),
                }
            task.update(changes)
            connection.execute(s.tasks.update().where(s.tasks.c.id == task["id"]).values(**changes))
            if task["status"] == "queued":
                enqueue(connection, scope, task)
            changed = True
    statuses = {task["status"] for task in tasks.values()}
    if statuses <= TERMINAL:
        status = "failed" if "failed" in statuses else "succeeded"
        connection.execute(
            s.runs.update()
            .where(s.runs.c.id == run_id)
            .values(status=status, finished_at=time.time())
        )
        event(connection, scope, run["project_id"], f"run.{status}", {}, run_id=run_id)
