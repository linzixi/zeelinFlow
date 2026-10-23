from __future__ import annotations

import time

from sqlalchemy import select

from ace_ext.core.contracts import Envelope
from ace_ext.persistence import schema as s
from ace_ext.persistence.articles import article_payload, read_snapshot
from ace_ext.persistence.database import Scope, base, event, where_scope


def persist_results(connection, task: dict, output: Envelope) -> None:
    """更新本节点授权输入中的文章；人工修订/新版本优先，快照结果仍完整留存。"""
    operation = task["node"]["operation"]
    if operation not in ("judge", "metrics", "content", "persist"):
        return
    scope = Scope(task["tenant_id"], task["context"]["owner_id"])
    source = read_snapshot(connection, scope, task["project_id"], task["input_snapshot_id"])
    allowed = {row["id"]: row for row in source["payload"].get("records", []) if "id" in row}
    fields = _editable_fields(operation)
    for index, result in enumerate(output.records):
        article_id = result.get("id")
        if not article_id:
            continue
        if article_id not in allowed:
            raise ValueError("节点结果引用了输入之外的文章")
        row = (
            connection.execute(
                select(s.articles)
                .where(
                    where_scope(s.articles, scope, task["project_id"]),
                    s.articles.c.id == article_id,
                )
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ValueError("节点结果引用的文章不存在")
        if row["revision"] != allowed[article_id].get("revision"):
            event(
                connection,
                scope,
                task["project_id"],
                "article.analysis_stale",
                {"article_id": article_id, "current_revision": row["revision"]},
                run_id=task["run_id"],
                task_id=task["id"],
            )
            output.context.setdefault("stale_analysis", []).append(result)
            output.records[index] = article_payload(dict(row))
            continue
        changes = {key: result[key] for key in fields if key in result}
        data = {**row["data"], **changes, **row["overrides"]}
        data["last_task_id"] = task["id"]
        revision = row["revision"] + 1
        output.records[index] = {**result, **data, "revision": revision}
        connection.execute(
            s.articles.update()
            .where(s.articles.c.id == article_id)
            .values(
                data=data,
                revision=revision,
                risk=data.get("risk", "unknown"),
                review_status=data.get("review_status", "pending"),
                updated_at=time.time(),
            )
        )
        connection.execute(
            s.article_revisions.insert().values(
                **base(scope, task["project_id"]),
                article_id=article_id,
                revision=revision,
                data=data,
                actor=f"task:{task['id']}",
                reason=f"节点执行：{task['node']['title']}",
            )
        )
    refresh_sgm_routes(task, output)


def refresh_sgm_routes(task: dict, output: Envelope) -> None:
    """分支以落库后的有效情感为准；人工覆盖或并发修订可能改变模型判断。"""
    if task["node"].get("config", {}).get("sgm_stage") not in {"sentiment", "problems"}:
        return
    routes = {
        row["id"]: "negative" if row.get("sentiment") == "negative" else "complete"
        for row in output.records
        if not row.get("skip_reason")
    }
    output.context.update(routes=sorted(set(routes.values())), record_routes={"routes": routes})


def _editable_fields(operation: str) -> tuple[str, ...]:
    fields = (
        ("metrics", "metrics_refreshed_at")
        if operation == "metrics"
        else (
            "summary",
            "sentiment",
            "risk",
            "tags",
            "decision",
            "assessment_status",
            "predicted_car",
            "news_dig",
            "problem_content",
            "problem_codes",
            "sgm_stage",
            "skip_reason",
            "fingerprint",
            "media_type",
            "media_route",
            "sis_status",
            "evidence_limit",
            "preview_eligible",
            "delivery_reason",
            "related_urls",
            "delivered",
            "question_type",
            "media_attribute",
            "related_links",
            "related_to",
            "would_send",
            "delivery_delay_seconds",
            "url_http_code",
            "url_checked",
            "url_check_reason",
            "extraction_status",
        )
    )
    if operation == "content":
        fields = (
            "content",
            "content_status",
            "source_content",
            "transcript",
            "sis_status",
            "sis_job_id",
            "sis_correlation",
            "asr_job_id",
            "evidence_limit",
        )
    return fields
