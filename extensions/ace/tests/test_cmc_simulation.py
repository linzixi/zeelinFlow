from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ace_ext.core.config import Settings
from ace_ext.core.contracts import ArticlePatch, Window
from ace_ext.execution.agent_worker import AgentWorker
from ace_ext.execution.data_worker import DataWorker
from ace_ext.persistence.articles import ArticleRepository
from ace_ext.persistence.projects import ProjectRepository
from ace_ext.persistence.tasks import TaskRepository
from ace_ext.workflow.importer import CMC_TIMES, import_cmc


def load_graph():
    path = Path(__file__).resolve().parents[3] / "migration/source/cmc-realtime.json"
    return import_cmc(json.loads(path.read_text(encoding="utf-8")))


def test_actual_cmc_fifteen_nodes_with_two_independent_branches(database, scope):
    graph = load_graph()
    assert len(graph.nodes) == 15
    assert graph.nodes[0].trigger.runAtTimes == CMC_TIMES
    assert graph.nodes[1].executor == "data"
    saved = ProjectRepository(database).create(scope, "CMC隔离模拟", graph)
    repo = TaskRepository(database, tenant_id=scope.tenant_id)
    articles = ArticleRepository(database)
    settings = Settings(database_url="sqlite://", redis_conn_string="redis://localhost:6379")
    worker = DataWorker(articles, settings)
    agent = AgentWorker(repo, 30)
    now = datetime.now(UTC)
    run = repo.launch(
        scope,
        saved["id"],
        origin="manual",
        mode="simulation",
        key="cmc-sim",
        window=Window(start=now - timedelta(minutes=150), end=now),
    )
    finished = []
    for _ in range(30):
        for lane in ("data", "agent", "delivery"):
            task = repo.claim(lane, lease_seconds=90)
            if task is None:
                continue
            payload = repo.input(task)
            output = (
                asyncio.run(agent.execute(task, payload))
                if lane == "agent"
                else worker.execute(task, payload)
            )
            if lane == "delivery":
                assert output.context["delivered"] is False
            repo.complete(task["id"], task["lease_token"], output)
            finished.append(task["node_id"])
    detail = repo.detail(scope, saved["id"], run["id"])
    assert detail["status"] == "succeeded"
    assert len(finished) == 15
    assert set(finished) == {node.id for node in graph.nodes}
    items = articles.list(scope, saved["id"])["items"]
    assert len(items) == 6 and sum(item["risk"] == "high" for item in items) == 2
    first = next(item for item in items if item["risk"] == "high")
    revised = articles.patch(
        scope,
        saved["id"],
        first["id"],
        ArticlePatch(revision=first["revision"], review_status="confirmed", note="模拟人工核验"),
    )
    assert revised["review_status"] == "confirmed"
    judgement = next(task for task in detail["tasks"] if task["node_id"] == "special_processing")
    replay = repo.replay(scope, saved["id"], judgement["id"], key="replay-original-judgment")
    replay_task = repo.claim("agent", lease_seconds=90)
    repo.complete(
        replay_task["id"],
        replay_task["lease_token"],
        asyncio.run(agent.execute(replay_task, repo.input(replay_task))),
    )
    assert repo.detail(scope, saved["id"], replay["id"])["status"] == "succeeded"
    assert articles.list(scope, saved["id"], review_status="confirmed")["total"] == 1
    detail = repo.detail(scope, saved["id"], replay["id"])
    output_id = detail["tasks"][0]["output_snapshot_id"]
    output = articles.read_snapshot(scope, saved["id"], output_id)["payload"]
    confirmed = next(row for row in output["records"] if row["id"] == first["id"])
    assert confirmed["review_status"] == "confirmed"
    assert output["context"]["stale_analysis"]
