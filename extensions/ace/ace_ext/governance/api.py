from __future__ import annotations

import asyncio

from deerflow_extension_api.auth import resolve_principal
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ace_ext.core.contracts import Contract
from ace_ext.core.errors import AceError
from ace_ext.workflow.models import Graph


class TeamInput(Contract):
    name: str = Field(min_length=1, max_length=128)


class SelectTeam(Contract):
    team_id: str = Field(min_length=1, max_length=64)


class MemberInput(SelectTeam):
    email: str = Field(min_length=3, max_length=200)
    role: str
    revision: int | None = None


class WorkspaceInput(SelectTeam):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)


class CanvasInput(Contract):
    name: str = Field(min_length=1, max_length=128)
    graph: Graph = Field(default_factory=lambda: Graph(nodes=[], edges=[]))


def build_router(service) -> APIRouter:
    router = APIRouter(prefix="/api/ace", tags=["ace-governance"])
    repo = service.governance
    native_lock = asyncio.Lock()

    def principal(request):
        value = resolve_principal(request)
        if not value:
            raise HTTPException(401, "请先登录")
        return value

    async def invoke(function, *args, **kwargs):
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        except AceError as exc:
            status = {"forbidden": 403, "not_found": 404, "conflict": 409}.get(exc.code, 422)
            raise HTTPException(status, str(exc)) from exc

    @router.get("/context")
    async def context(request: Request):
        user = principal(request)
        result = await invoke(repo.context, user.user_id)
        result["platform_admin"] = user.is_admin
        result["projects"] = (
            await invoke(repo.list_workspaces, user.user_id, result["active_team_id"])
            if result["active_team_id"]
            else []
        )
        return result

    @router.post("/teams")
    async def create_team(body: TeamInput, request: Request):
        user = principal(request)
        if not user.is_admin:
            raise HTTPException(403, "只有平台管理员可以新建团队")
        return await invoke(repo.create_team, user.user_id, body.name)

    @router.post("/active-team")
    async def active_team(body: SelectTeam, request: Request):
        await invoke(repo.select_team, principal(request).user_id, body.team_id)
        return {"ok": True}

    @router.get("/teams/{team_id}/members")
    async def members(team_id: str, request: Request):
        return await invoke(repo.list_members, principal(request).user_id, team_id)

    @router.put("/members")
    async def member(body: MemberInput, request: Request):
        actor = principal(request).user_id
        await invoke(repo.require, actor, body.team_id, "team.manage")
        from app.gateway.deps import get_user_repository

        target = await get_user_repository().get_user_by_email(body.email)
        if not target:
            raise HTTPException(404, "账号尚未注册，请先创建账号")
        return await invoke(
            repo.set_member,
            actor,
            body.team_id,
            str(target.id),
            body.role,
            body.email,
            body.revision,
        )

    _register_workspace_routes(router, repo, principal, invoke, native_lock)
    return router


def _register_workspace_routes(router, repo, principal, invoke, native_lock):
    @router.post("/projects")
    async def create_workspace(body: WorkspaceInput, request: Request):
        return await invoke(
            repo.create_workspace,
            principal(request).user_id,
            body.team_id,
            body.name,
            body.description,
        )

    @router.post("/projects/{workspace_id}/open")
    async def open_workspace(workspace_id: str, request: Request):
        user = principal(request).user_id
        workspace = await invoke(repo.workspace, user, workspace_id, "chat")
        await invoke(repo.select_team, user, workspace["team_id"])
        async with native_lock:
            native_id = await invoke(repo.native_id, user, workspace_id)
            native_repo = request.app.state.project_repo
            if not native_id:
                # 原生项目是个人对话容器；共享画布与数据归属上面的团队项目。
                rows = await native_repo.list(user_id=user)
                native = next(
                    (
                        row
                        for row in rows
                        if row.get("presentation", {}).get("ace_workspace_id") == workspace_id
                    ),
                    None,
                )
                if not native:
                    native = await native_repo.create(
                        name=workspace["name"],
                        presentation={"ace_workspace_id": workspace_id},
                        user_id=user,
                    )
                native_id = native["id"]
                await invoke(repo.bind_native, user, workspace_id, native_id)
        return {"native_project_id": native_id, "workspace_id": workspace_id}

    @router.get("/native-projects/{native_id}")
    async def project_context(native_id: str, request: Request):
        user = principal(request).user_id
        binding = await invoke(repo.native_binding, user, native_id)
        workspace = await invoke(repo.workspace, user, binding["project_id"])
        return {
            "project": workspace,
            "canvases": await invoke(repo.canvases, user, workspace["id"]),
        }

    @router.post("/projects/{workspace_id}/canvases")
    async def create_canvas(workspace_id: str, body: CanvasInput, request: Request):
        return await invoke(
            repo.create_canvas, principal(request).user_id, workspace_id, body.name, body.graph
        )

    return router
