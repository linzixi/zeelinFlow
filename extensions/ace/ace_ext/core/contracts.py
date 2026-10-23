from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Executor = Literal["data", "agent", "delivery"]
Origin = Literal["manual", "scheduled", "event", "replay"]
Mode = Literal["simulation", "live"]
TaskStatus = Literal[
    "blocked",
    "queued",
    "running",
    "waiting_agent",
    "waiting_review",
    "succeeded",
    "failed",
    "cancelled",
    "skipped",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Window(Contract):
    start: datetime
    end: datetime
    timeField: str = "ingested_at"
    timezone: str = "Asia/Shanghai"

    @model_validator(mode="after")
    def validate_window(self) -> Window:
        if not self.start.tzinfo or not self.end.tzinfo or self.start >= self.end:
            raise ValueError("数据时间窗必须带时区且开始时间早于结束时间")
        return self


class ArticleInput(Contract):
    source_id: str = Field(min_length=1, max_length=180)
    title: str = Field(min_length=1, max_length=1000)
    url: str = Field(default="", max_length=3000)
    source: str = Field(default="人工录入", max_length=160)
    content: str = Field(default="", max_length=200000)
    published_at: datetime | None = None
    ingested_at: datetime
    branch: str = Field(default="special", max_length=40)
    metrics: dict[str, int] = Field(default_factory=dict)
    raw: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_times(self) -> ArticleInput:
        for value in (self.ingested_at, self.published_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("文章时间必须带时区")
        return self


class ArticlePatch(Contract):
    revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    summary: str | None = Field(default=None, max_length=10000)
    sentiment: Literal["positive", "neutral", "negative", "unknown"] | None = None
    risk: Literal["high", "medium", "low", "unknown"] | None = None
    review_status: Literal["pending", "confirmed", "excluded", "watching"] | None = None
    tags: list[str] | None = None
    predicted_car: str | None = Field(default=None, max_length=1000)
    problem_content: str | None = Field(default=None, max_length=1000)
    news_dig: str | None = Field(default=None, max_length=10000)
    note: str = Field(default="", max_length=4000)


class Envelope(Contract):
    schemaVersion: Literal[1] = 1
    records: list[dict[str, JsonValue]] = Field(default_factory=list)
    summary: str = ""
    context: dict[str, JsonValue] = Field(default_factory=dict)
    artifacts: list[dict[str, JsonValue]] = Field(default_factory=list)
