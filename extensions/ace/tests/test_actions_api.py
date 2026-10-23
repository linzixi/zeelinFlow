from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from ace_ext.api.actions import Actions
from ace_ext.governance.workspaces import WorkspaceRepository
from ace_ext.persistence.articles import ArticleRepository
from ace_ext.persistence.tasks import TaskRepository


def api(database, scope):
    governance = WorkspaceRepository(database, scope.tenant_id)
    governance.create_team(scope.owner_id, "接口测试团队")
    governance.create_team("other", "其他团队")
    service = SimpleNamespace(
        database=database,
        settings=SimpleNamespace(ace_df_tenant=scope.tenant_id),
        tasks=TaskRepository(database, tenant_id=scope.tenant_id),
        articles=ArticleRepository(database),
        governance=governance,
    )
    sample = Path(__file__).resolve().parents[1] / "ace_ext/samples/cmc-realtime.json"
    return Actions(service, sample)


def call(actions, name, owner, payload):
    context = SimpleNamespace(principal=SimpleNamespace(user_id=owner), agent_runs=None)
    return asyncio.run(actions.handler(name)(payload, context))


def test_api_enforces_owner_and_cas_and_hides_validation_details(database, scope, saved_project):
    actions = api(database, scope)
    key = saved_project["id"]
    denied = call(actions, "get_project", "other", {"project_id": key})
    assert denied["ok"] is False and denied["error"]["code"] == "not_found"
    payload = {"project_id": key, "name": "编辑后", "graph": saved_project["graph"], "revision": 1}
    assert call(actions, "save_project", scope.owner_id, payload)["ok"] is True
    assert call(actions, "save_project", scope.owner_id, payload)["error"]["code"] == "conflict"
    invalid = call(
        actions,
        "run",
        scope.owner_id,
        {"project_id": key, "key": "invalid-date", "end": "2026-10-22T12:00:00"},
    )
    assert invalid["error"]["message"] == "节点或时间配置无效"


def test_seed_repeated_mounts_reuse_one_project(database, scope):
    actions = api(database, scope)
    first = call(actions, "seed_cmc", scope.owner_id, {})
    second = call(actions, "seed_cmc", scope.owner_id, {})
    assert first["ok"] and second["ok"] and first["data"]["id"] == second["data"]["id"]
