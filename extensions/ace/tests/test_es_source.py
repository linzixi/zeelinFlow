from __future__ import annotations

from datetime import datetime

import pytest

from ace_ext.core.contracts import Window
from ace_ext.core.errors import Unavailable
from ace_ext.resources.es_source import EsSource


def test_es_parameters_pin_ingestion_window_and_keep_query_semantics():
    start = datetime.fromisoformat("2026-10-22T06:00:00+08:00")
    end = datetime.fromisoformat("2026-10-22T08:30:00+08:00")
    params = EsSource._parameters(
        {
            "keywords": ["CMC+资本", "华人文化"],
            "time_field": "news_posttime",
            "match_fields": ["news_title"],
            "excluded_keywords": ["广告"],
            "collapse": False,
        },
        Window(start=start, end=end),
    )
    assert params.start_time == start and params.end_time == end
    assert params.time_field == "solr_create_time"
    assert params.keyword_fields == ("news_title",)
    assert params.keywords == ("CMC+资本", "华人文化")
    assert params.excluded_keywords == ("广告",)


def test_es_document_limit_fails_closed_and_missing_ingestion_time_rejected():
    class Source:
        def get_news_list_back(self, *args, **kwargs):
            return {"total": 3, "list": [{"news_uuid": "one"}, {"news_uuid": "two"}]}

    with pytest.raises(Unavailable, match="超过上限"):
        EsSource._query(None, Source(), None, {"max_results": 2, "page_size": 2})
    with pytest.raises(Unavailable, match="入库时间"):
        EsSource._article({"newsTitle": "文章", "newsUuid": "one"}, {"id": "fetch"}, None)


def test_short_page_with_remaining_total_is_not_success():
    class Source:
        def get_news_list_back(self, *args, **kwargs):
            return {"total": 3, "list": [{"news_uuid": "one"}]}

    with pytest.raises(Unavailable, match="不完整"):
        EsSource._query(None, Source(), None, {"max_results": 10, "page_size": 2})
