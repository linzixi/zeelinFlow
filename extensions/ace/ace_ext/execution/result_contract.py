from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ace_ext.core.contracts import Envelope
from ace_ext.core.errors import Unavailable
from ace_ext.resources.report_export import add_editable_documents


class Assessment(BaseModel):
    """模型只提供研判字段，文章原文、版本和人工核验状态由平台维护。"""

    model_config = ConfigDict(extra="ignore")
    sentiment: Literal["positive", "neutral", "negative", "unknown"] = "unknown"
    risk: Literal["high", "medium", "low", "unknown"] = "unknown"
    decision: Literal["report", "observe", "review", "exclude"] = "review"
    summary: str = Field(default="", max_length=10000)
    tags: list[str] = Field(default_factory=list, max_length=50)


def validate_result(node: dict, payload: dict, output: Envelope) -> Envelope:
    """验证归属和结果字段；下游收到原始证据与受限分析字段的合并结果。"""
    branch = node.get("config", {}).get("branch")
    allowed = {
        row["id"]: row
        for row in payload.get("records", [])
        if "id" in row and (not branch or row.get("branch") == branch)
    }
    records, seen = [], set()
    for row in output.records:
        key = row.get("id")
        if not isinstance(key, str) or key not in allowed or key in seen:
            raise Unavailable("Agent 结果包含重复或输入之外的文章")
        seen.add(key)
        source = allowed[key]
        if node["operation"] == "judge":
            try:
                fields = Assessment.model_validate(row).model_dump()
            except ValidationError as exc:
                raise Unavailable("Agent 研判字段未通过结果契约校验") from exc
            records.append({**source, **fields, "assessment_status": "done"})
        else:
            records.append(dict(source))
    if node["operation"] == "judge" and seen != set(allowed):
        raise Unavailable("Agent 未处理完整批次，请核对关联会话")
    if node["operation"] == "report":
        if not output.artifacts or any(
            not isinstance(item.get("content"), str) or not item["content"].strip()
            for item in output.artifacts
        ):
            raise Unavailable("报告节点没有返回可保存的正文产物")
    output.records = records
    output.context["hasItems"] = any(row.get("decision") == "report" for row in records)
    return add_editable_documents(output) if node["operation"] == "report" else output
