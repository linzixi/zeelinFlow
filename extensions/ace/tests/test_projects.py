from __future__ import annotations

import pytest
from sqlalchemy import delete, inspect

from ace_ext.core.errors import Conflict, NotFound
from ace_ext.persistence.database import Scope
from ace_ext.persistence.migrations import MIGRATIONS, VERSION, migrate
from ace_ext.persistence.projects import ProjectRepository


def test_migration_repeat_preserves_state(database, scope, saved_project):
    assert migrate(database) == VERSION
    assert ProjectRepository(database).get(scope, saved_project["id"])["revision"] == 1
    assert "ace_df_projects" in inspect(database.engine).get_table_names()


def test_graph_revision_cas_and_owner_isolation(database, scope, graph, saved_project):
    repo = ProjectRepository(database)
    updated = repo.save(scope, saved_project["id"], graph, 1)
    assert updated["revision"] == 2
    with pytest.raises(Conflict):
        repo.save(scope, saved_project["id"], graph, 1)
    with pytest.raises(NotFound):
        repo.get(Scope("test", "another-user"), saved_project["id"])
    with pytest.raises(NotFound):
        repo.get(Scope("another-tenant", scope.owner_id), saved_project["id"])
    assert [item["revision"] for item in repo.history(scope, saved_project["id"])] == [2, 1]


def test_large_legacy_config_is_archived_without_losing_history(isolated_schema, scope, graph):
    graph.nodes[0].config["source_config"] = {"validationSuite": "x" * 300000}
    repo = ProjectRepository(isolated_schema)
    project = repo.create(scope, "历史配置迁移", graph)
    with isolated_schema.transaction() as connection:
        connection.execute(delete(MIGRATIONS).where(MIGRATIONS.c.version == 3))
    assert migrate(isolated_schema) == VERSION
    current = repo.get(scope, project["id"])
    assert current["revision"] == 2
    assert "source_config" not in current["graph"]["nodes"][0]["config"]
    history = repo.history(scope, project["id"])
    assert "source_config" in history[-1]["graph"]["nodes"][0]["config"]
    migrate(isolated_schema)
    assert repo.get(scope, project["id"])["revision"] == 2
