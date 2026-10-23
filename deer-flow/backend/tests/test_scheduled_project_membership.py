from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway import scheduled_task_projects as projects
from deerflow.persistence.base import Base
from deerflow.persistence.projects import ProjectRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository


@pytest_asyncio.fixture
async def storage(tmp_path, monkeypatch):
    from deerflow.persistence import models  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'projects.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    state = SimpleNamespace(thread_store=ThreadMetaRepository(sf), project_repo=ProjectRepository(sf), scheduled_task_repo=ScheduledTaskRepository(sf))
    project = await state.project_repo.create(name="Scheduled project", user_id="owner")
    gate = AsyncMock(return_value=None)
    monkeypatch.setattr(projects, "authorize_project", gate)
    yield SimpleNamespace(app=SimpleNamespace(state=state)), project["id"], gate
    await engine.dispose()


async def create_task(request, project_id, **overrides):
    return await request.app.state.scheduled_task_repo.create(**{
        "task_id": "task-one", "user_id": "owner", "thread_id": None,
        "project_id": project_id, "context_mode": "fresh_thread_per_run", "assistant_id": "lead_agent",
        "title": "Test", "prompt": "Do not invoke any model", "schedule_type": "cron",
        "schedule_spec": {"cron": "0 9 * * *"}, "timezone": "UTC", "next_run_at": datetime.now(UTC), **overrides,
    })


@pytest.mark.asyncio
async def test_fresh_thread_has_project_before_launch_and_retry_is_idempotent(storage):
    request, project, gate = storage
    await create_task(request, project)
    for _ in range(2):
        await projects.prepare_scheduled_thread(request, "owner", "run-thread", {"scheduled_task_id": "task-one"})
    row = await request.app.state.thread_store.get("run-thread", user_id="owner")
    assert row["metadata"]["deerflow_project_id"] == project
    assert await request.app.state.thread_store.get("run-thread", user_id="other") is None
    gate.assert_awaited_with("owner", project, background=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("reuse", [True, False])
async def test_source_project_inherited_for_legacy_and_reuse(storage, reuse):
    request, project, _ = storage
    await request.app.state.thread_store.create("source", user_id="owner", project_id=project)
    await create_task(request, None, thread_id="source" if reuse else None, origin_thread_id="source", context_mode="reuse_thread" if reuse else "fresh_thread_per_run")
    target = "source" if reuse else "fresh"
    await projects.prepare_scheduled_thread(request, "owner", target, {"scheduled_task_id": "task-one"})
    row = await request.app.state.thread_store.get(target, user_id="owner")
    assert row["metadata"]["deerflow_project_id"] == project


@pytest.mark.asyncio
async def test_denied_owner_or_revoked_project_never_materializes_thread(storage):
    request, project, gate = storage
    await create_task(request, project)
    with pytest.raises(HTTPException):
        await projects.prepare_scheduled_thread(request, "other", "fresh", {"scheduled_task_id": "task-one"})
    gate.side_effect = HTTPException(403, "revoked")
    with pytest.raises(HTTPException):
        await projects.prepare_scheduled_thread(request, "owner", "fresh", {"scheduled_task_id": "task-one"})
    assert await request.app.state.thread_store.get("fresh", user_id="owner") is None


@pytest.mark.asyncio
async def test_archived_project_and_cross_project_reuse_rejected(storage):
    request, project, _ = storage
    await request.app.state.thread_store.create("source", user_id="owner", project_id=project)
    with pytest.raises(HTTPException) as exc:
        await projects.validate_project(request, "owner", "another-project", "source")
    assert exc.value.status_code == 422
    await create_task(request, project)
    await request.app.state.project_repo.set_status(project, "archived", user_id="owner")
    with pytest.raises(HTTPException):
        await projects.prepare_scheduled_thread(request, "owner", "fresh", {"scheduled_task_id": "task-one"})


@pytest.mark.asyncio
async def test_rest_selection_cannot_use_foreign_project(storage):
    request, project, _ = storage
    with pytest.raises(HTTPException):
        await projects.validate_project(request, "other", project)
