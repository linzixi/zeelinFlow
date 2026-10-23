from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select

from ace_ext.core.errors import Forbidden, Unavailable
from ace_ext.governance.roles import allowed
from ace_ext.persistence import report_schema as r
from ace_ext.persistence.database import base, digest, project, where_scope
from ace_ext.reporting.models import Query
from ace_ext.sgm.evidence import verified_quote


def authorize(service, user: str, thread_id: str) -> tuple:
    context = service.governance.context(user)
    if not allowed(context["role"], "canvas.read"):
        raise Forbidden("当前团队角色不能使用智能问数")
    with service.database.transaction() as connection:
        dataset = (
            connection.execute(
                select(r.datasets).where(
                    r.datasets.c.tenant_id == service.settings.ace_df_tenant,
                    r.datasets.c.thread_id == thread_id,
                    r.datasets.c.actor_id == user,
                )
            )
            .mappings()
            .first()
        )
        if not dataset:
            raise Forbidden(
                "此工具查询报告冻结快照，仅供报告节点使用；"
                "当前项目待审核数量请调用 project_review_queue 工具"
            )
        scope = service.governance.canvas_scope(user, dataset["project_id"], "canvas.read")
        project(connection, scope, dataset["project_id"])
        return scope, dict(dataset)


def execute(service, user: str, thread_id: str, query: Query) -> dict:
    scope, dataset = authorize(service, user, thread_id)
    with service.database.transaction() as connection:
        conditions = [
            where_scope(r.facts, scope, dataset["project_id"]),
            r.facts.c.dataset_id == dataset["id"],
        ]
        if query.sentiment:
            conditions.append(r.facts.c.sentiment == query.sentiment)
        if query.article_ids:
            conditions.append(r.facts.c.article_id.in_(query.article_ids))
        if query.keyword:
            # JSON extraction is deliberately parameterized; LIKE wildcards are literal user text.
            conditions.append(
                r.facts.c.data["content"].as_string().contains(query.keyword, autoescape=True)
            )
        result = run_query(connection, conditions, query)
        result.update(
            dataset_id=dataset["id"],
            snapshot_id=dataset["snapshot_id"],
            window=dataset["window"],
            mode=dataset["mode"],
            denominator="当前项目、入库时间半开区间、URL 去重文章；未完成标注计 unknown",
            coverage="仅本地已入库数据，不能据此宣称全网覆盖或连续七天走势",
        )
        audit = dict(
            **base(scope, dataset["project_id"]),
            dataset_id=dataset["id"],
            thread_id=thread_id,
            actor_id=user,
            spec=query.model_dump(mode="json"),
            result=result,
        )
        result["query_id"] = audit["id"]
        result["result_hash"] = digest(result)
        connection.execute(r.queries.insert().values(**audit))
        return result


def run_query(connection, conditions, query):
    count = connection.execute(
        select(func.count()).select_from(r.facts).where(*conditions)
    ).scalar_one()
    if query.operation == "overview":
        return {
            "total": count,
            "sentiments": grouped(connection, conditions, r.facts.c.sentiment),
            "assessment": grouped(connection, conditions, r.facts.c.assessment_status),
            "review": grouped(connection, conditions, r.facts.c.review_status),
            "transcription": grouped(
                connection,
                conditions,
                case(
                    (r.facts.c.assessment_status == "skipped", "skipped"),
                    else_=func.coalesce(r.facts.c.data["sis_status"].as_string(), "not_required"),
                ),
            ),
            "limitations": [
                "缺少粉丝量与转发关系，不能推断意见领袖影响力或机器人账号",
                "短窗口热度仅为本批次入库量，不等于全网讨论量或预测",
            ],
        }
    if query.operation == "breakdown":
        groups = grouped(connection, conditions, r.facts.c[query.dimension])
        return {
            "total": count,
            "dimension": query.dimension,
            "groups": groups[query.offset : query.offset + query.limit],
            "group_count": len(groups),
        }
    if query.operation == "timeseries":
        width = {"minute": 60, "hour": 3600, "day": 86400}[query.interval]
        bucket = func.floor((r.facts.c.ingested_at + 28800) / width) * width - 28800
        groups = connection.execute(
            select(bucket.label("bucket"), r.facts.c.sentiment, func.count().label("count"))
            .where(*conditions)
            .group_by(bucket, r.facts.c.sentiment)
            .order_by(bucket)
        ).mappings()
        rows = [
            {
                **dict(row),
                "time": datetime.fromtimestamp(
                    row["bucket"], ZoneInfo("Asia/Shanghai")
                ).isoformat(),
            }
            for row in groups
        ]
        if len(rows) > 500:
            raise Unavailable("时间序列超过500个点，请改用小时或天粒度")
        return {
            "total": count,
            "interval": query.interval,
            "timezone": "Asia/Shanghai",
            "points": rows,
            "time_basis": "入库时间，不是事件发生时间；缺失桶表示本地未有记录",
        }
    rows = connection.execute(
        select(r.facts)
        .where(*conditions)
        .order_by(r.facts.c.ingested_at, r.facts.c.article_id)
        .offset(query.offset)
        .limit(query.limit)
    ).mappings()
    return {
        "total": count,
        "offset": query.offset,
        "articles": [evidence(dict(row)) for row in rows],
    }


def grouped(connection, conditions, column):
    rows = connection.execute(
        select(column.label("label"), func.count().label("count"))
        .where(*conditions)
        .group_by(column)
        .order_by(func.count().desc(), column)
    ).mappings()
    return [dict(row) for row in rows]


def evidence(row):
    data = row["data"]
    excerpt_valid = verified_quote(data)
    original = data.get("content") or data.get("title", "")
    limit = data.get("evidence_limit", "")
    if data.get("news_dig") and not excerpt_valid:
        limit += "；编辑摘录未匹配原文，报告已改用现有正文或标题"
    return {
        "id": row["article_id"],
        "revision": row["revision"],
        "title": data.get("title", ""),
        "url": data.get("url", ""),
        "source": row["source"],
        "platform": row["platform"],
        "sentiment": row["sentiment"],
        "quote": data["news_dig"] if excerpt_valid else original[:1800],
        "quote_truncated": not excerpt_valid and len(original) > 1800,
        "problem": row["problem"],
        "brand": row["brand"],
        "review_status": row["review_status"],
        "evidence_limit": limit,
        "sis_status": data.get("sis_status", "not_required"),
    }
