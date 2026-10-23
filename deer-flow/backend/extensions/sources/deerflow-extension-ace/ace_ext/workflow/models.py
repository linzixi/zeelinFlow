from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from ace_ext.core.contracts import Contract, Executor


class Trigger(Contract):
    kind: Literal["manual", "event", "cron"] = "event"
    enabled: bool = False
    cron: str = ""
    timezone: str = "Asia/Shanghai"
    runAtTimes: list[str] = Field(default_factory=list)
    lookbackMinutes: int = Field(default=150, ge=1, le=44640)
    mode: Literal["simulation", "live"] = "simulation"


class Node(Contract):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    x: float = 0
    y: float = 0
    executor: Executor = "data"
    operation: str = "normalize"
    instructions: str = Field(default="", max_length=100000)
    skill: str = Field(default="", max_length=100000)
    agentRef: str = "lead_agent"
    inputContract: str = "ArticleBatch.v1"
    outputContract: str = "ArticleBatch.v1"
    config: dict[str, JsonValue] = Field(default_factory=dict)
    trigger: Trigger = Field(default_factory=Trigger)
    enabled: bool = True


class Edge(Contract):
    id: str = Field(min_length=1, max_length=180)
    source: str
    target: str
    label: str = ""
    conditionKey: str = ""
    conditionValue: str = ""
    executionDisabled: bool = False


class Bounds(Contract):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class Group(Contract):
    id: str
    name: str
    color: str = "#64748b"
    nodeIds: list[str]
    bounds: Bounds


class Graph(Contract):
    schemaVersion: Literal[1] = 1
    nodes: list[Node] = Field(default_factory=list, max_length=200)
    edges: list[Edge] = Field(default_factory=list, max_length=1000)
    groups: list[Group] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_graph(self) -> Graph:
        from ace_ext.workflow.validation import validate_graph

        validate_graph(self)
        return self
