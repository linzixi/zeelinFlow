from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ace_ext.core.contracts import Window
from ace_ext.persistence.tasks import TaskRepository


def test_history_omits_graph_but_detail_retains_frozen_definition(database, scope, saved_project):
    repo = TaskRepository(database, tenant_id=scope.tenant_id)
    now = datetime.now(UTC)
    run = repo.launch(
        scope,
        saved_project["id"],
        origin="manual",
        mode="simulation",
        key="summary-check",
        window=Window(start=now - timedelta(minutes=5), end=now),
    )
    rows = repo.list(scope, saved_project["id"])
    assert len(rows) == 1 and rows[0]["id"] == run["id"]
    assert "graph" not in rows[0]
    detail = repo.detail(scope, saved_project["id"], run["id"])
    assert detail["graph"] == saved_project["graph"]
    assert len(detail["tasks"]) == 3
