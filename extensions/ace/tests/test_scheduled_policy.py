from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ace_ext.governance.policy import TeamAuthorization
from ace_ext.governance.scheduled_policy import authorize_task_http
from ace_ext.governance.workspaces import WorkspaceRepository


def test_schedule_role_team_isolation_and_live_revocation(database, scope):
    policy = TeamAuthorization.__new__(TeamAuthorization)
    policy.db = database
    policy.repo = repo = WorkspaceRepository(database, scope.tenant_id)
    team = repo.create_team(scope.owner_id, "Scheduled team")
    workspace = repo.create_workspace(scope.owner_id, team["id"], "Project")
    repo.set_member(scope.owner_id, team["id"], "worker", "admin", "Administrator")
    repo.bind_native("worker", workspace["id"], "native-project")
    assert asyncio.run(policy.authorize_scheduled_project("worker", "native-project"))
    assert not asyncio.run(policy.authorize_scheduled_project("other", "native-project"))
    assert not asyncio.run(policy.authorize_scheduled_project("worker", None))
    repo.create_team("worker", "Other team")
    assert not asyncio.run(policy.authorize_scheduled_project("worker", "native-project"))
    assert asyncio.run(
        policy.authorize_scheduled_project("worker", "native-project", background=True)
    )
    repo.set_member(scope.owner_id, team["id"], "worker", "reviewer", "Reviewer", revision=1)
    assert not asyncio.run(
        policy.authorize_scheduled_project("worker", "native-project", background=True)
    )


def test_schedule_detail_rejects_foreign_owner_and_unassigned_task():
    policy = SimpleNamespace(authorize_scheduled_project=AsyncMock(return_value=False))
    repo = SimpleNamespace(get=AsyncMock(return_value={"user_id": "owner", "project_id": None}))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(scheduled_task_repo=repo)))
    assert not asyncio.run(
        authorize_task_http(policy, request, "owner", "/api/scheduled-tasks/task-one/trigger")
    )
    assert not asyncio.run(
        authorize_task_http(policy, request, "other", "/api/scheduled-tasks/task-one/runs")
    )
