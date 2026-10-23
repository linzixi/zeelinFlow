from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import pytest

from ace_ext.core.config import Settings
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import Database, Scope
from ace_ext.persistence.migrations import migrate
from ace_ext.persistence.projects import ProjectRepository
from ace_ext.workflow.models import Graph


def pytest_addoption(parser):
    parser.addoption("--mysql", action="store_true", help="使用本地配置的隔离验证租户")


@pytest.fixture
def database(request, scope):
    url = "sqlite://"
    if request.config.getoption("--mysql"):
        config = Settings(_env_file=Path(__file__).resolve().parents[3] / ".env")
        url = config.database_url.get_secret_value()
    database = Database(url)
    migrate(database)
    yield database
    with database.transaction() as connection:
        connection.execute(
            s.projects.update()
            .where(
                s.projects.c.tenant_id == scope.tenant_id, s.projects.c.owner_id == scope.owner_id
            )
            .values(deleted_at=time.time())
        )
    database.close()


@pytest.fixture
def scope():
    return Scope("test_" + uuid4().hex, "editor")


@pytest.fixture
def isolated_schema():
    instance = Database("sqlite://")
    migrate(instance)
    yield instance
    instance.close()


@pytest.fixture
def graph():
    return Graph.model_validate(
        {
            "nodes": [
                {"id": "fetch", "type": "es_query", "title": "采集", "operation": "ingest"},
                {"id": "judge", "type": "code_agent", "title": "判断", "executor": "agent"},
                {"id": "metrics", "type": "etl_article_interactions", "title": "刷新"},
            ],
            "edges": [
                {"id": "fj", "source": "fetch", "target": "judge"},
                {"id": "fm", "source": "fetch", "target": "metrics"},
            ],
        }
    )


@pytest.fixture
def saved_project(database, scope, graph):
    return ProjectRepository(database).create(scope, "隔离验证", graph)
