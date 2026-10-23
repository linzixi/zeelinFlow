from __future__ import annotations

import asyncio

from deerflow.authz.provider import AuthzRequest, Principal
from sqlalchemy import event

from ace_ext.governance.policy import TeamAuthorization
from ace_ext.governance.workspaces import WorkspaceRepository


def test_permission_batch_reads_membership_once_and_observes_revocation(database, scope):
    policy = TeamAuthorization.__new__(TeamAuthorization)
    policy.db = database
    policy.repo = WorkspaceRepository(database, scope.tenant_id)
    team = policy.repo.create_team(scope.owner_id, "权限验证")
    policy.repo.set_member(scope.owner_id, team["id"], "worker", "orchestrator", "编排师")
    requests = [
        AuthzRequest(Principal(user_id="worker"), "route", "read", f"resource-{i}:read")
        for i in range(13)
    ]
    queries = []

    def record_query(*args):
        queries.append(args[2])

    event.listen(database.engine, "before_cursor_execute", record_query)
    try:
        result = asyncio.run(policy.aauthorize_many(requests))
    finally:
        event.remove(database.engine, "before_cursor_execute", record_query)
    assert all(item.allow for item in result)
    assert len(queries) == 2  # 同批权限只读取一次团队与当前团队选择。
    policy.repo.set_member(scope.owner_id, team["id"], "worker", "reviewer", "审核员")
    assert not any(item.allow for item in asyncio.run(policy.aauthorize_many(requests)))


def test_permission_batch_keeps_principals_and_resource_rules_separate(database, scope):
    policy = TeamAuthorization.__new__(TeamAuthorization)
    policy.db = database
    policy.repo = WorkspaceRepository(database, scope.tenant_id)
    team = policy.repo.create_team(scope.owner_id, "多用户验证")
    policy.repo.set_member(scope.owner_id, team["id"], "reviewer", "reviewer", "审核员")
    requests = [
        AuthzRequest(Principal(user_id=scope.owner_id), "route", "read", "threads:read"),
        AuthzRequest(Principal(user_id="reviewer"), "route", "read", "threads:read"),
        AuthzRequest(Principal(user_id="reviewer"), "plugin", "use", "qingbo.ace"),
        AuthzRequest(Principal(user_id="reviewer"), "plugin", "use", "other.plugin"),
        AuthzRequest(Principal(), "plugin", "use", "qingbo.ace"),
    ]
    assert [item.allow for item in asyncio.run(policy.aauthorize_many(requests))] == [
        True, False, True, False, False,
    ]
