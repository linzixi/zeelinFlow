"""Project ownership for scheduled definitions and their generated conversations."""

from __future__ import annotations

import asyncio

from sqlalchemy.exc import IntegrityError

from app.gateway.authz import _get_route_authorization_config, _resolve_route_scoped_authorization
from app.gateway.deps import get_local_provider
from app.gateway.scheduled_task_errors import scheduler_error
from deerflow.runtime.run_origin import DEERFLOW_ORIGIN_KEY, make_origin


async def authorize_project(user_id: str, project_id: str | None, *, background: bool = False) -> None:
    """Apply the optional deployment policy using the real owner, never internal admin."""
    if not (await asyncio.to_thread(_get_route_authorization_config)).enabled:
        return
    user = await get_local_provider().get_user(user_id)
    if user is None or getattr(user, "disabled", False):
        raise scheduler_error(403, "permission_denied", "定时任务账号不可用")
    try:
        provider, _ = await asyncio.to_thread(_resolve_route_scoped_authorization, user, is_internal=False)
        hook = getattr(provider, "authorize_scheduled_project", None)
        if hook is not None and (await hook(user_id, project_id, background=background)) is not True:
            raise scheduler_error(403, "permission_denied", "请选择有权限的项目")
    except Exception as exc:
        raise scheduler_error(403, "permission_denied", "定时任务项目权限校验未通过") from exc


async def resolve_project(thread_store, user_id: str, project_id: str | None, thread_id: str | None) -> str | None:
    """Inherit a source/reused conversation's project and reject conflicting selection."""
    if thread_id:
        thread = await thread_store.get(thread_id, user_id=user_id)
        if not thread:
            raise scheduler_error(404, "thread_not_found", "对话不存在或无权访问")
        inherited = thread.get("metadata", {}).get("deerflow_project_id")
        if project_id and project_id != inherited:
            raise scheduler_error(422, "invalid_schedule", "定时任务与复用对话必须属于同一个项目")
        return inherited
    return project_id


async def validate_project(request, user_id: str, project_id: str | None, thread_id: str | None = None, *, thread_store=None) -> str | None:
    """Validate REST selection before storing a task definition."""
    if thread_id:
        project_id = await resolve_project(thread_store or request.app.state.thread_store, user_id, project_id, thread_id)
    if project_id:
        project = await request.app.state.project_repo.get(project_id, user_id=user_id)
        if not project or project["status"] != "active":
            raise scheduler_error(422, "invalid_schedule", "项目不存在或已归档")
    await authorize_project(user_id, project_id)
    return project_id


async def prepare_scheduled_thread(request, owner: str | None, thread_id: str, metadata: dict | None) -> None:
    """Materialize project membership before run admission reads project context."""
    task_id = (metadata or {}).get("scheduled_task_id")
    if not owner or not task_id:
        return
    repo = request.app.state.scheduled_task_repo
    task = await repo.get(task_id, user_id=owner)
    if not task:
        raise scheduler_error(404, "task_not_found", "定时任务不存在")
    store = request.app.state.thread_store
    source = task.get("thread_id") or (task.get("origin_thread_id") if not task.get("project_id") else None)
    project_id = await resolve_project(store, owner, task.get("project_id"), source)
    await authorize_project(owner, project_id, background=True)
    if project_id:
        project = await request.app.state.project_repo.get(project_id, user_id=owner)
        if not project or project["status"] != "active":
            raise scheduler_error(403, "permission_denied", "定时任务项目已不可用")
    existing = await store.get(thread_id, user_id=owner)
    if existing:
        if existing.get("metadata", {}).get("deerflow_project_id") != project_id:
            raise scheduler_error(403, "permission_denied", "运行对话与任务项目不一致")
        return
    try:
        await store.create(thread_id, user_id=owner, assistant_id=task.get("assistant_id"), project_id=project_id, metadata={DEERFLOW_ORIGIN_KEY: make_origin("schedule")})
    except IntegrityError:
        # A concurrent retry may have materialized the same occurrence.
        existing = await store.get(thread_id, user_id=owner)
        if not existing or existing.get("metadata", {}).get("deerflow_project_id") != project_id:
            raise scheduler_error(403, "permission_denied", "运行对话不可访问") from None
