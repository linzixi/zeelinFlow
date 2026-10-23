from __future__ import annotations

import asyncio
import re

from deerflow.authz.provider import AuthzDecision, AuthzReason, AuthzRequest
from sqlalchemy import select

from ace_ext.core.config import Settings
from ace_ext.core.errors import AceError
from ace_ext.governance.roles import allowed
from ace_ext.governance.workspaces import WorkspaceRepository
from ace_ext.persistence import schema as s
from ace_ext.persistence.agent_batches import batches
from ace_ext.persistence.database import Database


class TeamAuthorization:
    """部署方授权提供者；每次重新读成员关系，撤权不依赖重启。"""

    name = "ace-team-policy"

    def __init__(self, env_file: str):
        self.settings = Settings(_env_file=env_file)
        self.db = Database(self.settings.database_url.get_secret_value())
        self.repo = WorkspaceRepository(self.db, self.settings.ace_df_tenant)

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        return self._authorize_many([request])[0]

    def _authorize_many(self, requests: list[AuthzRequest]) -> list[AuthzDecision]:
        # 同一批次只读一次成员关系；下次请求重新读取，撤权立即生效。
        contexts, decisions = {}, []
        for request in requests:
            user = request.principal.user_id
            if user and user not in contexts:
                contexts[user] = self.repo.context(user)
            decisions.append(self._decide(request, contexts.get(user, {})))
        return decisions

    def _decide(self, request: AuthzRequest, context: dict) -> AuthzDecision:
        principal = request.principal
        if not principal.user_id:
            return self.verdict(False)
        if request.resource == "http":
            raise ValueError("HTTP策略必须异步执行")
        if request.resource in {"plugin", "plugin_page", "plugin_action", "plugin_surface"}:
            return self.verdict(
                request.target.startswith("qingbo.ace") or allowed(context["role"], "chat")
            )
        if request.resource == "plugin_management":
            return self.verdict(principal.role == "admin")
        return self.verdict(allowed(context["role"], "chat"))

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        if request.resource == "http":
            return await self.authorize_http(request)
        return await asyncio.to_thread(self.authorize, request)

    async def aauthorize_many(self, requests: list[AuthzRequest]) -> list[AuthzDecision]:
        return await asyncio.to_thread(self._authorize_many, requests)

    async def authorize_scheduled_project(
        self, user: str, project_id: str | None, *, background: bool = False
    ) -> bool:
        from ace_ext.governance.scheduled_policy import project_access

        return await asyncio.to_thread(
            project_access, self.repo, user, project_id, background=background
        )

    def filter_resources(self, principal, resource_type, candidates):
        requests = [AuthzRequest(principal, resource_type, "use", target) for target in candidates]
        return [
            target
            for target, decision in zip(candidates, self._authorize_many(requests), strict=True)
            if decision.allow
        ]

    @staticmethod
    def verdict(value: bool, message="当前团队角色不允许访问此功能") -> AuthzDecision:
        return AuthzDecision(
            allow=value, reasons=[] if value else [AuthzReason("team_forbidden", message)]
        )

    async def authorize_http(self, check: AuthzRequest) -> AuthzDecision:
        request = check.context["request"]
        user, path = check.principal.user_id, check.target.rstrip("/")
        context = await asyncio.to_thread(self.repo.context, user)
        if path in {
            "/api/v1/auth/me",
            "/api/v1/auth/change-password",
            "/api/ace/context",
            "/api/ace/active-team",
        }:
            return self.verdict(True)
        if path.startswith("/api/ace/"):
            return self.verdict(True)  # 贡献路由逐操作校验成员与角色。
        if path == "/api/plugins" and request.method == "GET":
            return self.verdict(True)
        if path.startswith("/api/plugins/qingbo.ace/"):
            return self.verdict("/actions/" in path or "/assets/" in path)
        if not allowed(context["role"], "chat"):
            return self.verdict(False)
        # Composer requests public upload constraints before a draft thread exists.
        if request.method == "GET" and re.fullmatch(r"/api/threads/[^/]+/uploads/limits", path):
            return self.verdict(True)
        try:
            if path.startswith("/api/scheduled-tasks/"):
                from ace_ext.governance.scheduled_policy import authorize_task_http

                if not await authorize_task_http(self, request, user, path):
                    return self.verdict(False, "定时任务不属于当前团队项目")
            project_match = re.match(r"^/api/projects/([^/]+)", path)
            if project_match and project_match[1] not in {"config", "trash"}:
                await asyncio.to_thread(self.repo.native_binding, user, project_match[1])
            if path == "/api/projects" and request.method == "POST":
                return self.verdict(False, "请在团队项目入口新建项目")
            if path == "/api/threads" and request.method == "POST":
                body = await request.json()
                node_thread = await asyncio.to_thread(self._node_thread, user, body)
                # LangGraph SDK repeats create(if_exists=do_nothing) after the
                # project-aware composer has materialized an attachment thread.
                existing = (
                    not body.get("project_id")
                    and body.get("thread_id")
                    and await self._thread_access(request, user, body["thread_id"])
                )
                if not node_thread and not existing:
                    await asyncio.to_thread(
                        self.repo.native_binding, user, body.get("project_id", "")
                    )
            thread_match = re.match(r"^/api/threads/([^/]+)", path)
            if thread_match and thread_match[1] not in {"search", "count"}:
                if not await self._thread_access(request, user, thread_match[1]):
                    return self.verdict(False, "对话不属于当前团队的项目")
            if path.startswith("/api/runs"):
                return self.verdict(False, "请先在项目中创建对话")
            if path.endswith("/move") and request.method == "POST":
                body = await request.json()
                await asyncio.to_thread(self.repo.native_binding, user, body.get("project_id", ""))
        except (AceError, ValueError):
            return self.verdict(False, "请选择当前团队中有权限的项目")
        return self.verdict(True)

    async def _thread_access(self, request, user: str, thread_id: str) -> bool:
        if await asyncio.to_thread(self._node_thread_id, user, thread_id):
            return True
        record = await request.app.state.thread_store.get(thread_id, user_id=user)
        if not record:
            return False
        native_id = record.get("metadata", {}).get("deerflow_project_id")
        if not native_id:
            # Explicit migration of an owned legacy conversation; destination is
            # separately checked by authorize_http before the native move route.
            return request.method == "POST" and request.url.path.endswith("/move")
        await asyncio.to_thread(self.repo.native_binding, user, native_id)
        return True

    async def filter_http_records(self, request, kind: str, rows: list) -> list:
        user = str(request.state.user.id)
        result = []
        for row in rows:
            try:
                if kind == "projects":
                    await asyncio.to_thread(self.repo.native_binding, user, row["id"])
                elif kind == "scheduled_tasks":
                    from ace_ext.governance.scheduled_policy import task_access

                    if not await task_access(self, request, user, row):
                        continue
                elif not await self._thread_access(request, user, row["thread_id"]):
                    continue
                result.append(row)
            except AceError:
                continue
        return result

    def _node_thread_id(self, user: str, thread_id: str) -> bool:
        with self.db.transaction() as connection:
            row = (
                connection.execute(
                    select(s.tasks).where(
                        s.tasks.c.thread_id == thread_id,
                        s.tasks.c.tenant_id == self.repo.tenant,
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                row = (
                    connection.execute(
                        select(s.tasks)
                        .join(batches, batches.c.task_id == s.tasks.c.id)
                        .where(
                            batches.c.thread_id == thread_id,
                            s.tasks.c.tenant_id == self.repo.tenant,
                        )
                    )
                    .mappings()
                    .first()
                )
        if not row or row["context"].get("actor_id", row["context"].get("owner_id")) != user:
            return False
        self.repo.canvas_scope(user, row["project_id"], "runs.write")
        return True

    def _node_thread(self, user: str, body: dict) -> bool:
        task_id = body.get("metadata", {}).get("ace_task_id")
        if not task_id:
            return False
        with self.db.transaction() as connection:
            row = (
                connection.execute(
                    select(s.tasks).where(
                        s.tasks.c.id == task_id,
                        s.tasks.c.tenant_id == self.repo.tenant,
                        s.tasks.c.thread_id == body.get("thread_id"),
                    )
                )
                .mappings()
                .first()
            )
            if not row or row["context"].get("actor_id", row["context"].get("owner_id")) != user:
                return False
        self.repo.canvas_scope(user, row["project_id"], "runs.write")
        return True
