from __future__ import annotations

from typing import Literal

from pydantic import Field

from ace_ext.core.contracts import Contract


class Query(Contract):
    operation: Literal["overview", "breakdown", "timeseries", "articles"]
    dimension: Literal["sentiment", "platform", "source", "brand", "problem", "review_status"] = (
        "sentiment"
    )
    interval: Literal["minute", "hour", "day"] = "minute"
    sentiment: Literal["", "positive", "neutral", "negative", "unknown"] = ""
    keyword: str = Field(default="", max_length=200)
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=10000)
    article_ids: list[str] = Field(default_factory=list, max_length=50)


class Finding(Contract):
    text: str = Field(min_length=1, max_length=2000)
    article_ids: list[str] = Field(default_factory=list, max_length=20)
    query_ids: list[str] = Field(min_length=1, max_length=20)


class Narrative(Contract):
    title: str = Field(min_length=1, max_length=200)
    executive_summary: list[Finding] = Field(min_length=1, max_length=8)
    viewpoints: list[Finding] = Field(default_factory=list, max_length=12)
    evolution: list[Finding] = Field(default_factory=list, max_length=8)
    recommendations: list[Finding] = Field(min_length=1, max_length=8)
    limitations: list[str] = Field(min_length=1, max_length=12)
