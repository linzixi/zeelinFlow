from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ace_ext.core.contracts import ArticleInput, ArticlePatch, Envelope, Window
from ace_ext.persistence.articles import ArticleRepository
from ace_ext.persistence.projects import ProjectRepository
from ace_ext.persistence.task_state import _condition_matches, routed_records
from ace_ext.persistence.tasks import TaskRepository
from ace_ext.workflow.models import Graph
from ace_ext.workflow.sgm import import_sgm


def test_import_preserves_original_node_order_edges_and_rules():
    source = json.loads(
        (Path(__file__).parents[3] / "migration/source/sgm.json").read_text("utf-8")
    )
    graph = import_sgm(source)
    assert [n.id for n in graph.nodes] == [n["id"] for n in source["graph"]["nodes"]]
    assert [e.model_dump() for e in graph.edges] == source["graph"]["edges"]
    assert graph.nodes[3].config["original_only_platforms"] == ["weibo", "media_toutiao"]
    assert graph.nodes[5].config["asr_failure_policy"] == "fallback-to-source"
    assert graph.nodes[13].config["auto_send"] is False


def test_mixed_batch_routes_each_record_without_leaking_sibling_branch():
    payload = {
        "records": [{"id": "text"}, {"id": "video"}],
        "context": {
            "route": ["text", "video"],
            "record_routes": {"route": {"text": "text", "video": "video"}},
        },
    }
    edge = {"conditionKey": "route", "conditionValue": "video"}
    assert _condition_matches(edge, payload)
    assert routed_records(edge, payload) == [{"id": "video"}]
    assert not _condition_matches({**edge, "conditionValue": "missing"}, payload)


def test_human_negative_override_controls_actual_downstream_branch(database, scope):
    graph = Graph.model_validate(
        {
            "nodes": [
                {
                    "id": "judge",
                    "title": "情感",
                    "type": "code_agent",
                    "executor": "agent",
                    "operation": "judge",
                    "config": {"sgm_stage": "sentiment"},
                },
                {"id": "extract", "title": "负面", "type": "code_agent", "executor": "agent"},
            ],
            "edges": [
                {
                    "id": "negative",
                    "source": "judge",
                    "target": "extract",
                    "conditionKey": "routes",
                    "conditionValue": "negative",
                }
            ],
        }
    )
    project = ProjectRepository(database).create(scope, "人工复核分支", graph)
    articles = ArticleRepository(database)
    now = datetime.now(UTC)
    row = articles.ingest(
        scope,
        project["id"],
        [
            ArticleInput(
                source_id="source",
                title="人工确认负面",
                content="原文",
                url="https://example.com/manual",
                ingested_at=now - timedelta(seconds=10),
            )
        ],
        mode="live",
    )[0]
    articles.patch(scope, project["id"], row["id"], ArticlePatch(revision=1, sentiment="negative"))
    repo = TaskRepository(database, tenant_id=scope.tenant_id)
    repo.launch(
        scope,
        project["id"],
        origin="manual",
        mode="live",
        key="override-route",
        window=Window(start=now - timedelta(minutes=5), end=now),
    )
    task = repo.claim("agent", lease_seconds=90)
    source = repo.input(task)["records"][0]
    repo.complete(
        task["id"],
        task["lease_token"],
        Envelope(
            records=[{**source, "sentiment": "neutral"}],
            context={"routes": ["complete"], "record_routes": {"routes": {row["id"]: "complete"}}},
        ),
    )
    downstream = repo.claim("agent", lease_seconds=90)
    assert downstream and downstream["node_id"] == "extract"
    assert repo.input(downstream)["records"][0]["sentiment"] == "negative"
