from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ace_ext.core.contracts import ArticleInput, ArticlePatch, Window
from ace_ext.core.errors import Conflict
from ace_ext.persistence.articles import ArticleRepository


def article(title="模拟文章", **extra):
    return ArticleInput(
        source_id="test-1",
        title=title,
        url="https://example.invalid/a",
        ingested_at=datetime.now(UTC),
        **extra,
    )


def test_dedup_does_not_overwrite_editor_and_snapshot_is_immutable(database, scope, saved_project):
    repo, key = ArticleRepository(database), saved_project["id"]
    original = repo.ingest(scope, key, [article()], mode="simulation")
    row = original[0]
    assert row["revision"] == 1
    repo.patch(
        scope,
        key,
        row["id"],
        ArticlePatch(revision=1, title="人工核实后的标题", risk="high", note="原文核对"),
    )
    now = datetime.now(UTC)
    window = Window(start=now - timedelta(minutes=150), end=now + timedelta(minutes=1))
    before = repo.capture(scope, key, window, mode="simulation")
    repo.ingest(scope, key, [article(title="采集端更新标题")], mode="simulation")
    current = repo.list(scope, key)["items"][0]
    assert current["data"]["title"] == "人工核实后的标题"
    assert current["risk"] == "high"
    assert repo.read_snapshot(scope, key, before)["payload"]["records"][0]["revision"] == 2
    assert repo.list(scope, key)["total"] == 1
    assert len(repo.history(scope, key, row["id"])) == 3
    with pytest.raises(Conflict):
        repo.patch(scope, key, row["id"], ArticlePatch(revision=1, risk="low"))


def test_mode_and_ingestion_window_isolation(database, scope, saved_project):
    repo, key = ArticleRepository(database), saved_project["id"]
    repo.ingest(scope, key, [article()], mode="simulation")
    repo.ingest(scope, key, [article()], mode="live")
    assert repo.list(scope, key, mode="live")["total"] == 1
    now = datetime.now(UTC)
    snapshot = repo.capture(
        scope,
        key,
        Window(start=now - timedelta(days=2), end=now - timedelta(days=1)),
        mode="simulation",
    )
    assert repo.read_snapshot(scope, key, snapshot)["payload"]["records"] == []
