"""定时任务按项目授权；后台执行不依赖用户当前浏览的团队。"""

from __future__ import annotations

import re

from sqlalchemy import select

from ace_ext.core.errors import AceError
from ace_ext.governance import schema as g


def project_access(repo, user: str, native_id: str | None, *, background: bool) -> bool:
    if not native_id:
        return False
    try:
        if not background:
            repo.native_binding(user, native_id)
            return True
        with repo.db.transaction() as connection:
            workspace_id = connection.execute(
                select(g.native_projects.c.project_id).where(
                    g.native_projects.c.tenant_id == repo.tenant,
                    g.native_projects.c.user_id == user,
                    g.native_projects.c.native_id == native_id,
                )
            ).scalar()
        if not workspace_id:
            return False
        repo.workspace(user, workspace_id, "chat")
        return True
    except AceError:
        return False


async def task_access(policy, request, user: str, task: dict) -> bool:
    if task.get("user_id") != user:
        return False
    native_id = task.get("project_id")
    if not native_id:
        source = task.get("thread_id") or task.get("origin_thread_id")
        thread = await request.app.state.thread_store.get(source, user_id=user) if source else None
        native_id = (thread or {}).get("metadata", {}).get("deerflow_project_id")
    return await policy.authorize_scheduled_project(user, native_id)


async def authorize_task_http(policy, request, user: str, path: str) -> bool:
    match = re.fullmatch(r"/api/scheduled-tasks/([^/]+)(?:/.*)?", path)
    if not match or match[1] == "preview-cron":
        return True
    task = await request.app.state.scheduled_task_repo.get(match[1], user_id=user)
    if not task:
        return False
    return await task_access(policy, request, user, task)
