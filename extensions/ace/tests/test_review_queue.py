from __future__ import annotations

import json
from datetime import UTC, datetime
from types import MappingProxyType, SimpleNamespace

import pytest
import pytest_asyncio
from deerflow.extensions.plugin_tools import _build_tool
from deerflow.persistence.projects import ProjectRepository as NativeProjects
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.runtime.run_origin import DEERFLOW_ORIGIN_KEY, make_origin
from deerflow_extension_api.plugins import PluginContribution
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ace_ext.core.contracts import ArticleInput, ArticlePatch
from ace_ext.core.errors import Forbidden
from ace_ext.governance.workspaces import WorkspaceRepository
from ace_ext.persistence import schema as s
from ace_ext.persistence.articles import ArticleRepository
from ace_ext.reporting.review_queue import query_review_queue
from ace_ext.reporting.review_queue_tool import review_queue_tool


@pytest_asyncio.fixture
async def queue_fixture(database, scope, graph, tmp_path):
    repo = WorkspaceRepository(database, scope.tenant_id)
    team = repo.create_team(scope.owner_id, "Team")
    workspace = repo.create_workspace(scope.owner_id, team["id"], "Workspace")
    canvas = repo.create_canvas(scope.owner_id, workspace["id"], "Canvas", graph)
    repo.set_member(scope.owner_id, team["id"], "worker", "orchestrator", "Worker")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'native.db'}")
    async with engine.begin() as connection:
        for table in (ProjectRow.__table__, ThreadMetaRow.__table__):
            await connection.run_sync(table.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    native = await NativeProjects(factory).create(name="Workspace", user_id="worker")
    repo.bind_native("worker", workspace["id"], native["id"])
    threads = ThreadMetaRepository(factory)
    await threads.create("chat", user_id="worker", project_id=native["id"])
    await threads.create(
        "scheduled",
        user_id="worker",
        project_id=native["id"],
        metadata={DEERFLOW_ORIGIN_KEY: make_origin("schedule")},
    )
    articles = ArticleRepository(database)
    rows = articles.ingest(
        scope,
        canvas["id"],
        [
            ArticleInput(
                source_id=str(i),
                title=f"Record {i}",
                url=f"https://example.com/{i}",
                ingested_at=datetime.now(UTC),
            )
            for i in range(6)
        ],
        mode="live",
    )
    with database.transaction() as connection:
        for i in (0, 1):
            connection.execute(
                s.articles.update()
                .where(s.articles.c.id == rows[i]["id"])
                .values(data={**rows[i]["data"], "decision": "report"})
            )
        connection.execute(
            s.articles.update()
            .where(s.articles.c.id == rows[1]["id"])
            .values(review_status="confirmed")
        )
        connection.execute(
            s.articles.update().where(s.articles.c.id == rows[4]["id"]).values(mode="simulation")
        )
        connection.execute(
            s.articles.update().where(s.articles.c.id == rows[5]["id"]).values(deleted_at=1)
        )
    service = SimpleNamespace(database=database, governance=repo, native_session_factory=factory)
    yield service, rows, articles, team, canvas, threads
    await engine.dispose()


@pytest.mark.asyncio
async def test_live_count_matches_list_and_changes_after_review(queue_fixture, scope):
    service, rows, articles, _, canvas, _ = queue_fixture
    first = await query_review_queue(service, "worker", "chat")
    assert (
        first["total_articles"],
        first["pending_articles"],
        first["alert_articles"],
        first["pending_alert_articles"],
    ) == (4, 3, 2, 1)
    assert (
        first["pending_articles"]
        == articles.list(scope, canvas["id"], review_status="pending", mode="live")["total"]
    )
    assert (
        first["pending_alert_articles"]
        == articles.list(
            scope, canvas["id"], review_status="pending", mode="live", alerts_only=True
        )["total"]
    )
    articles.patch(
        scope, canvas["id"], rows[0]["id"], ArticlePatch(revision=1, review_status="confirmed")
    )
    second = await query_review_queue(service, "worker", "scheduled")
    assert (second["pending_articles"], second["pending_alert_articles"]) == (2, 0)
    assert first["query_id"] != second["query_id"]
    with service.database.transaction() as connection:
        audit = (
            connection.execute(
                select(s.events.c.payload).where(
                    s.events.c.kind == "warehouse.review_queue",
                    s.events.c.tenant_id == scope.tenant_id,
                )
            )
            .scalars()
            .all()
        )
    assert len(audit) == 2 and audit[-1]["thread_id"] == "scheduled"


@pytest.mark.asyncio
async def test_owner_team_reviewer_and_unassigned_guards(queue_fixture, scope):
    service, _, _, team, _, threads = queue_fixture
    for user, thread in [("outsider", "chat"), ("worker", "unknown")]:
        with pytest.raises(Forbidden):
            await query_review_queue(service, user, thread)
    await threads.create("unassigned", user_id="worker")
    with pytest.raises(Forbidden):
        await query_review_queue(service, "worker", "unassigned")
    service.governance.create_team("worker", "Other team")
    with pytest.raises(Forbidden):
        await query_review_queue(service, "worker", "chat")
    assert (await query_review_queue(service, "worker", "scheduled"))["pending_articles"] == 3
    service.governance.set_member(
        scope.owner_id, team["id"], "worker", "reviewer", "Reviewer", revision=1
    )
    with pytest.raises(Forbidden):
        await query_review_queue(service, "worker", "scheduled")


@pytest.mark.asyncio
async def test_model_tool_cannot_supply_project_or_treat_unavailable_as_zero(queue_fixture):
    service, *_ = queue_fixture
    tool = review_queue_tool(service)
    context = SimpleNamespace(principal=SimpleNamespace(user_id="worker"), thread_id="chat")
    bad = await tool.handler({"project_id": "foreign"}, context)
    assert bad.artifact is None
    result = await tool.handler({}, context)
    assert result.artifact["pending_articles"] == 3
    service.native_session_factory = None
    failed = await tool.handler({}, context)
    assert failed.artifact is None and "失败不代表" in failed.content


@pytest.mark.asyncio
async def test_native_tool_adapter_with_readonly_parameters(queue_fixture):
    service, rows, _, _, _, _ = queue_fixture
    declaration = review_queue_tool(service)
    plugin = PluginContribution(
        namespace="qingbo.ace", title="ACE", enabled=True, tools=(declaration,)
    )
    tool = _build_tool("ace", plugin, declaration)
    runtime = SimpleNamespace(context={"user_id": "worker", "thread_id": "chat"})
    content, artifact = await tool.coroutine(runtime=runtime)
    assert artifact["pending_articles"] == 3
    content, artifact = await tool.coroutine(runtime=runtime, include_details=True)
    assert len(artifact["details"]["items"]) == 3
    assert len(json.dumps({"content": content, "artifact": artifact}).encode()) < 65536
    with service.database.transaction() as connection:
        for row in rows:
            connection.execute(
                s.articles.update()
                .where(s.articles.c.id == row["id"])
                .values(
                    data={
                        **row["data"],
                        "summary": "长" * 1000,
                        "title": "题" * 1000,
                        "url": "https://example.com/" + "字" * 2000,
                    }
                )
            )
    content, artifact = await tool.coroutine(runtime=runtime, include_details=True, limit=50)
    assert artifact["details"]["has_more"]
    assert artifact["details"]["next_offset"] == len(artifact["details"]["items"])
    context = SimpleNamespace(principal=SimpleNamespace(user_id="worker"), thread_id="chat")
    bad = await declaration.handler(MappingProxyType({"limit": "50"}), context)
    assert bad.artifact is None


@pytest.mark.asyncio
async def test_detail_pagination_filters_and_guards(queue_fixture, scope):
    service, rows, articles, team, _, _ = queue_fixture
    tool = review_queue_tool(service)
    context = SimpleNamespace(principal=SimpleNamespace(user_id="worker"), thread_id="chat")
    collected = []
    for offset in (0, 2):
        result = await tool.handler(
            {"include_details": True, "limit": 2, "offset": offset}, context
        )
        page = result.artifact["details"]
        assert page["total"] == 3
        assert page["has_more"] == (offset == 0)
        collected.extend(page["items"])
        assert json.loads(result.content)["details"] == page
    assert {r["id"] for r in collected} == {rows[i]["id"] for i in (0, 2, 3)}
    assert len(collected) == 3
    assert all(r["title"] and r["url"] and "raw" not in r for r in collected)
    alerts = await tool.handler({"include_details": True, "alerts_only": True}, context)
    assert alerts.artifact["details"]["items"][0]["id"] == rows[0]["id"]
    articles.patch(
        scope,
        rows[0]["project_id"],
        rows[0]["id"],
        ArticlePatch(revision=1, review_status="confirmed"),
    )
    empty = await tool.handler({"include_details": True, "alerts_only": True}, context)
    assert empty.artifact["details"]["total"] == 0
    assert empty.artifact["details"]["items"] == []
    for invalid in (
        {"limit": 51},
        {"offset": -1},
        {"review_status": "bad"},
        {"project_id": "other"},
    ):
        assert (await tool.handler(invalid, context)).artifact is None
    context.principal.user_id = "outsider"
    assert (await tool.handler({"include_details": True}, context)).artifact is None
    context.principal.user_id = "worker"
    service.governance.set_member(
        scope.owner_id, team["id"], "worker", "reviewer", "Reviewer", revision=1
    )
    assert (await tool.handler({"include_details": True}, context)).artifact is None
