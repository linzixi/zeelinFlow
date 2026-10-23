from __future__ import annotations

import pytest

from ace_ext.core.errors import AceError
from ace_ext.governance.api import CanvasInput
from ace_ext.governance.repository import GovernanceRepository


def test_membership_roles_and_active_team_are_independent(database, scope):
    repo = GovernanceRepository(database, scope.tenant_id)
    first = repo.create_team(scope.owner_id, "汽车业务")
    second = repo.create_team(scope.owner_id, "资本业务")
    repo.set_member(scope.owner_id, first["id"], "reviewer", "reviewer", "审核员")
    repo.set_member(scope.owner_id, second["id"], "reviewer", "orchestrator", "审核员")
    repo.select_team("reviewer", first["id"])
    assert repo.context("reviewer")["role"] == "reviewer"
    with pytest.raises(AceError):
        repo.require("reviewer", first["id"], "canvas.write")
    repo.require("reviewer", first["id"], "articles.write")
    repo.select_team("reviewer", second["id"])
    repo.require("reviewer", second["id"], "canvas.write")
    with pytest.raises(AceError):
        repo.set_member("reviewer", second["id"], "outsider", "admin", "外部")


def test_team_isolation_revocation_and_last_admin(database, scope):
    repo = GovernanceRepository(database, scope.tenant_id)
    team = repo.create_team(scope.owner_id, "隔离团队")
    with pytest.raises(AceError):
        repo.select_team("outsider", team["id"])
    with pytest.raises(AceError):
        repo.set_member(scope.owner_id, team["id"], scope.owner_id, "reviewer", "管理员")
    repo.set_member(scope.owner_id, team["id"], "editor2", "orchestrator", "编排师")
    repo.require("editor2", team["id"], "canvas.write")
    repo.set_member(scope.owner_id, team["id"], "editor2", "disabled", "编排师")
    with pytest.raises(AceError):
        repo.require("editor2", team["id"], "canvas.write")
    other = GovernanceRepository(database, scope.tenant_id + "foreign")
    assert not other.context(scope.owner_id)["teams"]


def test_new_canvas_starts_as_editable_empty_draft():
    draft = CanvasInput(name="新画布")
    assert draft.graph.nodes == [] and draft.graph.edges == []
