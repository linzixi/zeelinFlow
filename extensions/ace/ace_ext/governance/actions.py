from __future__ import annotations

from ace_ext.core.errors import Forbidden
from ace_ext.governance.roles import allowed

ACTION_PERMISSIONS = {
    "get_project": "canvas.read",
    "save_project": "canvas.write",
    "run": "runs.write",
    "list_runs": "runs.read",
    "run_detail": "runs.read",
    "cancel_run": "runs.write",
    "retry_task": "runs.write",
    "replay_task": "runs.write",
    "list_articles": "articles.read",
    "update_article": "articles.write",
    "article_history": "articles.read",
    "import_articles": "canvas.write",
    "snapshot": "runs.read",
}


def resolve_action_scope(repo, user: str, name: str, project_id: str):
    context = repo.context(user)
    permission = ACTION_PERMISSIONS.get(name)
    if permission and project_id:
        if not allowed(context["role"], permission):
            raise Forbidden("当前团队角色没有此操作权限")
        return repo.canvas_scope(user, project_id, permission)
    if name in {"catalog", "create_project", "seed_cmc", "health"} and not allowed(
        context["role"], "canvas.write"
    ):
        raise Forbidden("当前角色不能访问编排能力")
    return repo.scope(user)


def list_canvases(repo, user: str, request) -> list[dict]:
    context = repo.context(user)
    workspace_id = request.workspace_id
    if request.native_project_id:
        workspace_id = repo.native_binding(user, request.native_project_id)["project_id"]
    workspaces = (
        [repo.workspace(user, workspace_id)]
        if workspace_id
        else repo.list_workspaces(user, context["active_team_id"])
        if context["active_team_id"]
        else []
    )
    rows = [canvas for workspace in workspaces for canvas in repo.canvases(user, workspace["id"])]
    if not allowed(context["role"], "canvas.read"):
        return [{key: row[key] for key in ("id", "name", "revision")} for row in rows]
    return rows


def is_reviewer(repo, scope) -> bool:
    return repo.context(scope.actor)["role"] == "reviewer"


def require_reviewable(articles, scope, project_id, article_id) -> None:
    with articles.db.transaction() as connection:
        row = articles._get(connection, scope, project_id, article_id)
        if row["data"].get("decision") not in {"report", "review"}:
            raise Forbidden("审核人员只能访问预警文章")
