from __future__ import annotations

import pytest

from ace_ext.core.config import Settings
from ace_ext.core.errors import Unavailable
from ace_ext.execution.data_worker import DataWorker
from ace_ext.persistence.articles import ArticleRepository


@pytest.fixture
def worker(database):
    return DataWorker(
        ArticleRepository(database),
        Settings(database_url="sqlite://", redis_conn_string="redis://localhost"),
    )


def test_content_fetches_only_missing_records_and_preserves_existing(worker, monkeypatch):
    seen = []

    def source(endpoint, payload):
        seen.append(payload["records"])
        assert endpoint == "content"
        return {"contents": {"b": "补齐后的正文"}}

    monkeypatch.setattr(worker, "_source_request", source)
    result = worker._content([{"id": "a", "content": "已采集正文"}, {"id": "b"}])
    assert seen == [[{"id": "b"}]]
    assert [row["content"] for row in result] == ["已采集正文", "补齐后的正文"]


def test_missing_content_or_partial_metrics_stops_downstream(worker, monkeypatch):
    monkeypatch.setattr(worker, "_source_request", lambda *args: {})
    with pytest.raises(Unavailable, match="不完整"):
        worker._content([{"id": "b"}])
    monkeypatch.setattr(worker, "_source_request", lambda *args: {"metrics": {}})
    with pytest.raises(Unavailable, match="无效"):
        worker._refresh_metrics({}, [{"id": "a"}])
