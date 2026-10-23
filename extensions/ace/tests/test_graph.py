from __future__ import annotations

import pytest
from pydantic import ValidationError

from ace_ext.workflow.models import Graph
from ace_ext.workflow.validation import reachable


def test_branches_and_visual_edges():
    graph = Graph.model_validate(
        {
            "nodes": [
                {"id": key, "type": "code_agent", "title": key} for key in ("source", "a", "b")
            ],
            "edges": [
                {"id": "sa", "source": "source", "target": "a"},
                {"id": "sb", "source": "source", "target": "b"},
                {"id": "bs", "source": "b", "target": "source", "executionDisabled": True},
            ],
        }
    )
    assert reachable(graph, "source") == {"source", "a", "b"}
    assert reachable(graph, "a") == {"a"}
    assert reachable(graph, "source", single=True) == {"source"}


def test_cycle_and_missing_nodes_rejected():
    for edges in [
        [{"id": "a", "source": "a", "target": "a"}],
        [{"id": "b", "source": "a", "target": "missing"}],
    ]:
        with pytest.raises(ValidationError):
            Graph(nodes=[{"id": "a", "type": "es_query", "title": "取数"}], edges=edges)


def test_group_requires_actual_boundary():
    with pytest.raises(ValidationError, match="包住"):
        Graph(
            nodes=[{"id": "a", "type": "es_query", "title": "取数", "x": 100}],
            groups=[
                {
                    "id": "g",
                    "name": "采集",
                    "nodeIds": ["a"],
                    "bounds": {"x": 0, "y": 0, "width": 220, "height": 140},
                }
            ],
        )


def test_invalid_trigger_rejected():
    with pytest.raises(ValidationError):
        Graph(
            nodes=[
                {
                    "id": "a",
                    "type": "es_query",
                    "title": "取数",
                    "trigger": {"kind": "cron", "runAtTimes": ["25:00"]},
                }
            ]
        )
