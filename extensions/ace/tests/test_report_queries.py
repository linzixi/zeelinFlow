from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from ace_ext.core.contracts import ArticleInput, ArticlePatch, Envelope, Window
from ace_ext.core.errors import Forbidden, Unavailable
from ace_ext.governance.workspaces import WorkspaceRepository
from ace_ext.persistence import report_datasets, report_queries, report_schema
from ace_ext.persistence.articles import ArticleRepository
from ace_ext.persistence.tasks import TaskRepository
from ace_ext.reporting.agent import validate
from ace_ext.reporting.models import Query


def dataset_fixture(database, scope, graph):
    governance = WorkspaceRepository(database, scope.tenant_id)
    team = governance.create_team(scope.owner_id, "数仓验证团队")
    workspace = governance.create_workspace(scope.owner_id, team["id"], "数仓验证")
    canvas = governance.create_canvas(scope.owner_id, workspace["id"], "画布", graph)
    now = datetime(2026, 10, 22, 16, 0, tzinfo=UTC)
    articles = ArticleRepository(database)
    rows = articles.ingest(
        scope,
        canvas["id"],
        [
            ArticleInput(
                source_id=str(i),
                title="真实来源的占位测试文章",
                content="包含100%关键词而非指令",
                url=f"https://example.com/{i}",
                ingested_at=now - timedelta(seconds=1 + i * 61),
                raw={"platform_name": "视频"},
            )
            for i in range(3)
        ],
        mode="live",
    )
    # 模拟节点成功结果，仅测试仓储统计，不使用外部模型。
    with database.transaction() as connection:
        from ace_ext.persistence import schema as s

        for i, row in enumerate(rows):
            data = {
                **row["data"],
                "sentiment": "negative" if i == 0 else "positive",
                "assessment_status": "done",
            }
            connection.execute(
                s.articles.update().where(s.articles.c.id == row["id"]).values(data=data)
            )
    tasks = TaskRepository(database, tenant_id=scope.tenant_id)
    tasks.launch(
        scope,
        canvas["id"],
        origin="manual",
        mode="live",
        key="report",
        window=Window(start=now - timedelta(minutes=5), end=now),
        start="judge",
        single=True,
    )
    task = tasks.claim("agent", lease_seconds=90)
    dataset = report_datasets.prepare(tasks, task, "report-thread-" + scope.tenant_id)
    service = SimpleNamespace(
        database=database,
        governance=governance,
        settings=SimpleNamespace(ace_df_tenant=scope.tenant_id),
    )
    return service, dataset, rows, articles, team, canvas


def test_sql_counts_freeze_revisions_and_deny_other_threads_teams_reviewers(database, scope, graph):
    service, dataset, rows, articles, team, canvas = dataset_fixture(database, scope, graph)

    def run(**kwargs):
        return report_queries.execute(
            service, scope.owner_id, "report-thread-" + scope.tenant_id, Query(**kwargs)
        )

    overview = run(operation="overview")
    assert overview["total"] == 3
    assert {g["label"]: g["count"] for g in overview["sentiments"]} == {
        "positive": 2,
        "negative": 1,
    }
    points = run(operation="timeseries")["points"]
    assert len(points) == 3 and points[-1]["time"].endswith("23:59:00+08:00")
    assert run(operation="articles", keyword="100%", sentiment="negative")["total"] == 1
    assert run(operation="articles", keyword="%' OR 1=1 --")["total"] == 0
    articles.patch(
        scope, canvas["id"], rows[0]["id"], ArticlePatch(revision=1, sentiment="positive")
    )
    assert run(operation="overview")["sentiments"] == overview["sentiments"]
    with database.transaction() as connection:
        audits = list(
            connection.execute(
                select(report_schema.queries).where(
                    report_schema.queries.c.dataset_id == dataset["id"]
                )
            ).mappings()
        )
    assert len(audits) == 5 and audits[0]["result"]["query_id"] == audits[0]["id"]
    with pytest.raises(Forbidden):
        report_queries.execute(service, scope.owner_id, "other-thread", Query(operation="overview"))
    service.governance.set_member(scope.owner_id, team["id"], "reviewer", "reviewer", "审核")
    with pytest.raises(Forbidden):
        report_queries.execute(
            service, "reviewer", "report-thread-" + scope.tenant_id, Query(operation="overview")
        )
    service.governance.create_team(scope.owner_id, "另一团队")
    with pytest.raises(Forbidden):
        run(operation="overview")


def test_no_arbitrary_sql_and_no_unqueried_evidence():
    with pytest.raises(ValidationError):
        Query(operation="overview", sql="DELETE FROM anything")
    with pytest.raises(Unavailable, match="真实数仓查询"):
        validate(Envelope(context={"report": {}}), [])
    report = {
        "title": "报告",
        "executive_summary": [{"text": "发现", "query_ids": ["forged"], "article_ids": []}],
        "recommendations": [{"text": "建议", "query_ids": ["real"]}],
        "limitations": ["数据有限"],
    }
    audits = [
        {"id": "real", "spec": {"operation": op}, "result": {}}
        for op in ["overview", "breakdown", "timeseries", "articles"]
    ]
    audits += [
        {"id": "real", "spec": {"operation": "breakdown", "dimension": d}, "result": {}}
        for d in ("platform", "problem", "source")
    ]
    with pytest.raises(Unavailable, match="没有查询过"):
        validate(Envelope(context={"report": json.loads(json.dumps(report))}), audits)
    audits[0]["spec"]["sentiment"] = "negative"
    with pytest.raises(Unavailable, match="全量基准"):
        validate(Envelope(context={"report": report}), audits)


def test_unmatched_edited_excerpt_is_not_presented_as_source_quote():
    row = dict(
        article_id="a",
        revision=2,
        source="s",
        platform="p",
        sentiment="negative",
        problem="p",
        brand="b",
        review_status="pending",
        data={"title": "真实标题", "content": "原文并未指责产品", "news_dig": "严重造假"},
    )
    evidence = report_queries.evidence(row)
    assert evidence["quote"] == "原文并未指责产品"
    assert "未匹配原文" in evidence["evidence_limit"]


def test_skipped_article_does_not_count_historical_transcription(database, scope, graph):
    service, dataset, rows, _, _, _ = dataset_fixture(database, scope, graph)
    with database.transaction() as connection:
        connection.execute(
            report_schema.facts.update()
            .where(
                report_schema.facts.c.dataset_id == dataset["id"],
                report_schema.facts.c.article_id == rows[0]["id"],
            )
            .values(assessment_status="skipped", data={"sis_status": "fallback_source"})
        )
    result = report_queries.execute(
        service, scope.owner_id, "report-thread-" + scope.tenant_id, Query(operation="overview")
    )
    statuses = {g["label"]: g["count"] for g in result["transcription"]}
    assert statuses == {"not_required": 2, "skipped": 1}
