from __future__ import annotations

import time
from unittest.mock import Mock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from test_tasks import launch

from ace_ext.core.config import Settings
from ace_ext.core.contracts import Envelope
from ace_ext.core.errors import LeaseLost
from ace_ext.execution.queue import QueueNotifications
from ace_ext.persistence import schema as s
from ace_ext.persistence.tasks import TaskRepository


def test_redis_outage_retains_outbox_and_db_can_run(database, scope, saved_project):
    repo = TaskRepository(database, tenant_id=scope.tenant_id)
    launch(repo, scope, saved_project["id"], single=True, start="fetch")
    queue = QueueNotifications(
        database,
        Settings(
            database_url="sqlite://",
            redis_conn_string="redis://localhost",
            ace_df_tenant=scope.tenant_id,
        ),
    )
    queue.redis.close()
    queue.redis = Mock()
    queue.redis.pipeline.side_effect = RedisConnectionError("offline")
    assert queue.publish() == 0
    with database.transaction() as connection:
        pending = (
            connection.execute(select(s.outbox).where(s.outbox.c.tenant_id == scope.tenant_id))
            .mappings()
            .one()
        )
        assert pending["published_at"] is None
    task = repo.claim("data", lease_seconds=60)
    repo.complete(task["id"], task["lease_token"], Envelope(summary="数据库兜底完成"))


def test_deferred_delivery_survives_new_repository_and_fences_old_worker(
    database,
    scope,
    saved_project,
):
    repo = TaskRepository(database, tenant_id=scope.tenant_id)
    launch(repo, scope, saved_project["id"], single=True, start="fetch")
    task = repo.claim("data", lease_seconds=60)
    at = time.time() + 1800
    repo.defer(task["id"], task["lease_token"], at=at, reason="等待09:00")
    restarted = TaskRepository(database, tenant_id=scope.tenant_id)
    assert restarted.claim("data", lease_seconds=60, now=at - 1) is None
    resumed = restarted.claim("data", lease_seconds=60, now=at + 1)
    assert resumed["id"] == task["id"]
    assert resumed["input_snapshot_id"] == task["input_snapshot_id"]
    with pytest.raises(LeaseLost):
        repo.complete(task["id"], task["lease_token"], Envelope())


def test_known_terminal_agent_can_retry_without_reusing_failed_run(database, scope, saved_project):
    repo = TaskRepository(database, tenant_id=scope.tenant_id)
    run = launch(repo, scope, saved_project["id"], single=True, start="judge")
    task = repo.claim("agent", lease_seconds=60)
    repo.agent_started(task["id"], task["lease_token"], "first-thread", "failed-run")
    repo.agent_terminal(task["id"], task["lease_token"], "error")
    repo.fail(task["id"], task["lease_token"], "模型错误", retryable=False)
    assert repo.detail(scope, saved_project["id"], run["id"])["status"] == "failed"
    repo.retry(scope, saved_project["id"], task["id"])
    retry = repo.claim("agent", lease_seconds=60)
    assert retry["attempt"] == 2 and retry["thread_id"] is None
    assert retry["agent_run_id"] is None
    events = repo.detail(scope, saved_project["id"], run["id"])["events"]
    assert any(event["payload"].get("previous_run_id") == "failed-run" for event in events)
