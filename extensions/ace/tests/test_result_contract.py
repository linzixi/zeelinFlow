from __future__ import annotations

import pytest

from ace_ext.core.contracts import Envelope
from ace_ext.core.errors import Unavailable
from ace_ext.execution.result_contract import validate_result


def test_agent_cannot_rewrite_source_or_confirm_human_review():
    source = {"id": "a", "revision": 3, "title": "原文", "review_status": "pending"}
    output = Envelope(
        records=[
            {
                **source,
                "title": "篡改原文",
                "risk": "high",
                "review_status": "confirmed",
                "decision": "report",
            }
        ]
    )
    result = validate_result({"operation": "judge", "config": {}}, {"records": [source]}, output)
    assert result.records[0]["title"] == "原文"
    assert result.records[0]["review_status"] == "pending"
    assert result.records[0]["risk"] == "high"
    assert result.context["hasItems"] is True


@pytest.mark.parametrize("changes", [{"risk": "emergency"}, {"id": "outside"}])
def test_invalid_model_fields_or_unknown_article_stop_downstream(changes):
    source = {"id": "a", "revision": 1}
    with pytest.raises(Unavailable):
        validate_result(
            {"operation": "judge", "config": {}},
            {"records": [source]},
            Envelope(records=[{**source, **changes}]),
        )


def test_report_requires_actual_content_artifact():
    with pytest.raises(Unavailable):
        validate_result(
            {"operation": "report", "config": {}},
            {"records": []},
            Envelope(summary="声称生成了报告"),
        )
