from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from ace_ext.api.actions import Actions
from ace_ext.governance.workspaces import WorkspaceRepository
from ace_ext.persistence.articles import ArticleRepository
from ace_ext.persistence.tasks import TaskRepository


def test_reviewer_cannot_read_graph_or_execute_and_cross_team_is_denied(database, scope, graph):
    repo = WorkspaceRepository(database, scope.tenant_id)
    team = repo.create_team(scope.owner_id, "团队一")
    repo.set_member(scope.owner_id, team["id"], "reviewer", "reviewer", "审核员")
    project = repo.create_workspace(scope.owner_id, team["id"], "共享项目")
    canvas = repo.create_canvas(scope.owner_id, project["id"], "取数画布", graph)
    service = SimpleNamespace(
        database=database,
        governance=repo,
        settings=SimpleNamespace(ace_df_tenant=scope.tenant_id),
        tasks=TaskRepository(database, tenant_id=scope.tenant_id),
        articles=ArticleRepository(database),
    )
    actions = Actions(service, Path("unused"))
    context = SimpleNamespace(principal=SimpleNamespace(user_id="reviewer"), agent_runs=None)

    def call(name, payload):
        return asyncio.run(actions.handler(name)(payload, context))

    for name in ["get_project", "list_runs"]:
        result = call(name, {"project_id": canvas["id"]})
        assert not result["ok"] and result["error"]["code"] == "forbidden"
    result = call("run", {"project_id": canvas["id"], "key": "blocked"})
    assert not result["ok"]
    result = call("list_articles", {"project_id": canvas["id"]})
    assert result["ok"] and result["data"]["total"] == 0
    result = call("list_projects", {})
    assert len(result["data"]) == 1 and "graph" not in result["data"][0]
    second = repo.create_team(scope.owner_id, "团队二")
    foreign = repo.create_workspace(scope.owner_id, second["id"], "不可见项目")
    other = repo.create_canvas(scope.owner_id, foreign["id"], "私有画布", graph)
    result = call("list_articles", {"project_id": other["id"]})
    assert not result["ok"]
