from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from ace_ext.core.contracts import Envelope, Window
from ace_ext.core.errors import Conflict, LeaseLost
from ace_ext.persistence import schema as s
from ace_ext.persistence.tasks import TaskRepository


def launch(repo, scope, project, key="once", **kwargs):
    now = datetime.now(UTC)
    return repo.launch(
        scope,
        project,
        origin="manual",
        mode="simulation",
        key=key,
        window=Window(start=now - timedelta(minutes=150), end=now),
        **kwargs,
    )


def test_task_fanout_commits_output_before_outbox(database, scope, saved_project):
    repo, key = TaskRepository(database, tenant_id=scope.tenant_id), saved_project["id"]
    run = launch(repo, scope, key)
    assert launch(repo, scope, key)["id"] == run["id"]
    task = repo.claim("data", lease_seconds=60)
    assert task["node_id"] == "fetch"
    assert repo.claim("data", lease_seconds=60) is None
    repo.complete(task["id"], task["lease_token"], Envelope(records=[{"title": "one"}]))
    agent = repo.claim("agent", lease_seconds=60)
    data = repo.claim("data", lease_seconds=60)
    assert agent["node_id"] == "judge" and data["node_id"] == "metrics"
    assert repo.input(agent)["records"] == [{"title": "one"}]
    with database.transaction() as connection:
        assert (
            len(
                connection.execute(
                    select(s.outbox).where(s.outbox.c.tenant_id == scope.tenant_id)
                ).all()
            )
            == 3
        )
    repo.fail(agent["id"], agent["lease_token"], "模型暂不可用", retryable=False)
    repo.complete(data["id"], data["lease_token"], Envelope())
    detail = repo.detail(scope, key, run["id"])
    assert detail["status"] == "failed"
    assert {t["status"] for t in detail["tasks"]} == {"succeeded", "failed"}


def test_lease_fencing_retry_replay_uses_frozen_input(database, scope, saved_project):
    repo, key = TaskRepository(database, tenant_id=scope.tenant_id), saved_project["id"]
    run = launch(repo, scope, key, single=True, start="fetch")
    task = repo.claim("data", lease_seconds=10, now=100)
    # 本轮任务按真实时间可领取，后续显式推进时钟模拟 Worker 崩溃。
    assert task is None
    task = repo.claim("data", lease_seconds=10)
    repo.recover_expired(now=task["lease_until"] + 1)
    recovered = repo.claim("data", lease_seconds=60, now=task["lease_until"] + 2)
    assert recovered["id"] == task["id"] and recovered["attempt"] == 2
    with pytest.raises(LeaseLost):
        repo.complete(task["id"], task["lease_token"], Envelope(summary="迟到结果"))
    repo.complete(recovered["id"], recovered["lease_token"], Envelope(summary="已恢复"))
    replay = repo.replay(scope, key, recovered["id"], key="replay-1")
    assert replay["replay_of"] == run["id"] and replay["origin"] == "replay"
    assert replay["graph_revision"] == run["graph_revision"]
    pending = repo.detail(scope, key, replay["id"])["tasks"][0]
    assert pending["input_snapshot_id"] == recovered["input_snapshot_id"]


def test_cancel_fences_completion(database, scope, saved_project):
    repo, key = TaskRepository(database, tenant_id=scope.tenant_id), saved_project["id"]
    run = launch(repo, scope, key)
    task = repo.claim("data", lease_seconds=60)
    repo.cancel(scope, key, run["id"])
    with pytest.raises(LeaseLost):
        repo.complete(task["id"], task["lease_token"], Envelope())
    assert repo.detail(scope, key, run["id"])["status"] == "cancelled"
    with pytest.raises(Conflict):
        repo.retry(scope, key, task["id"])
