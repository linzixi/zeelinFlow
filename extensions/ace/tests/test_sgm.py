from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from ace_ext.core.contracts import Envelope, Window
from ace_ext.core.errors import LeaseLost, Unavailable
from ace_ext.execution.sgm_agent import chunks, validate
from ace_ext.execution.sgm_data import skip_reason, transform
from ace_ext.persistence import agent_batches
from ace_ext.persistence.tasks import TaskRepository
from ace_ext.resources.sgm_source import SgmSource, request_params


def test_source_rejects_partial_or_changing_pages(monkeypatch):
    config = SimpleNamespace(
        sqty_app_id="demo", sqty_app_secret=SecretStr("test"), sqty_api_url="https://example.com"
    )
    window = Window(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 2, tzinfo=UTC))
    source = SgmSource(config)
    monkeypatch.setattr(source, "_page", lambda *a: {"data": {"data": [], "total": 1}})
    with pytest.raises(Unavailable, match="不完整"):
        source.fetch({}, window)
    params = request_params(config, window, 1)
    assert params["appId"] == params["app_id"] == "demo"
    assert [params[f"scheme_id[{i}]"] for i in range(4)] == [51, 52, 43, 55]


def test_sgm_business_filters_and_video_route():
    row = {
        "id": "x",
        "title": "别克车辆",
        "content": "问题描述",
        "raw": {"news_first_tag": ["常规信息"]},
    }
    assert not skip_reason(row)
    assert skip_reason({**row, "raw": {"news_first_tag": []}})
    assert skip_reason({**row, "raw": {**row["raw"], "is_reply": 1}})
    assert (
        skip_reason(
            {
                **row,
                "title": "[源文章无标题]",
                "content": "",
                "raw": {**row["raw"], "news_title": ""},
            }
        )
        == "no-chinese-text"
    )
    video = {
        **row,
        "raw": {
            **row["raw"],
            "platform": "video",
            "news_video_urls": ["https://example.com/v.mp4"],
        },
    }
    assert transform(video, "route")["media_route"] == "video"
    assert (
        transform({**video, "raw": {**video["raw"], "platform": "weibo"}}, "route")["media_route"]
        == "text"
    )


def test_model_batches_complete_ids_and_problem_contract():
    rows = [
        {"id": str(i), "title": "内容", "content": "原文", "sentiment": "negative"}
        for i in range(25)
    ]
    assert [len(batch) for batch in chunks(rows)] == [12, 12, 1]
    with pytest.raises(Unavailable):
        validate(rows, Envelope(records=[{"id": "0"}] * 25), "sentiment")
    result = validate(rows[:1], Envelope(records=[{"id": "0"}]), "problems")[0]
    assert result["sentiment"] == "negative" and result["extraction_status"] == "review_required"
    alias = validate(
        rows[:1], Envelope(records=[{"id": "article_1", "sentiment": "positive"}]), "sentiment"
    )
    assert alias[0]["id"] == rows[0]["id"]


def test_missing_evidence_preserves_candidate_but_clears_unverified_quote():
    row = {
        "title": "尾门关不上",
        "content": "车主说尾门关不上",
        "sentiment": "negative",
        "problem_codes": [1],
        "news_dig": "尾门关不上",
    }
    assert transform(row, "policy")["preview_eligible"]
    for quote in ("未检测到负面评价内容", "编造的故障"):
        result = transform({**row, "news_dig": quote}, "policy")
        assert result["decision"] == "review" and result["preview_eligible"]
        assert result["news_dig"] == "" and result["sentiment"] == "negative"
        assert "人工核验" in result["evidence_limit"]


def test_batch_checkpoint_survives_resume_and_is_lease_fenced(database, scope, saved_project):
    repo = TaskRepository(database, tenant_id=scope.tenant_id)
    now = datetime.now(UTC)
    repo.launch(
        scope,
        saved_project["id"],
        origin="manual",
        mode="live",
        key="batch-test",
        window=Window(start=now - timedelta(minutes=5), end=now),
        start="judge",
        single=True,
    )
    task = repo.claim("agent", lease_seconds=90)
    batch = agent_batches.prepare(repo, task, 0)
    agent_batches.save(repo, task, batch, run_id="run", result=[{"id": "a"}])
    recovered = agent_batches.prepare(repo, task, 0)
    assert recovered["thread_id"] == batch["thread_id"] and recovered["result"] == [{"id": "a"}]
    with pytest.raises(LeaseLost):
        agent_batches.save(repo, {**task, "lease_token": "stale"}, batch, run_id="bad")
