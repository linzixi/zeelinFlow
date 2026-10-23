from __future__ import annotations

from sqlalchemy import select

from ace_ext.core.contracts import Window
from ace_ext.core.errors import Unavailable
from ace_ext.persistence import report_schema as r
from ace_ext.persistence import schema as s
from ace_ext.persistence.articles import article_payload
from ace_ext.persistence.database import Scope, base, snapshot, where_scope


def prepare(repo, task: dict, thread_id: str) -> dict:
    """冻结当次项目数仓及文章版本，重启后继续使用同一查询数据集。"""
    scope = Scope(task["tenant_id"], task["context"]["owner_id"])
    window = Window.model_validate(
        task["node"]["config"].get("report_window") or task["context"]["window"]
    )
    with repo.db.transaction() as connection:
        repo._fenced(connection, task["id"], task["lease_token"])
        old = (
            connection.execute(select(r.datasets).where(r.datasets.c.task_id == task["id"]))
            .mappings()
            .first()
        )
        if old:
            if old["thread_id"] != thread_id:
                connection.execute(
                    r.datasets.update()
                    .where(r.datasets.c.id == old["id"])
                    .values(thread_id=thread_id)
                )
            return {**dict(old), "thread_id": thread_id}
        rows = list(
            connection.execute(
                select(s.articles)
                .where(
                    where_scope(s.articles, scope, task["project_id"]),
                    s.articles.c.deleted_at.is_(None),
                    s.articles.c.mode == task["context"]["mode"],
                    s.articles.c.ingested_at >= window.start.timestamp(),
                    s.articles.c.ingested_at < window.end.timestamp(),
                )
                .order_by(s.articles.c.ingested_at, s.articles.c.id)
                .limit(10001)
            ).mappings()
        )
        if len(rows) > 10000:
            raise Unavailable("报告时间窗超过一万篇，请缩小范围后重试")
        records = [article_payload(dict(row)) for row in rows]
        dataset = dict(
            **base(scope, task["project_id"]),
            task_id=task["id"],
            thread_id=thread_id,
            actor_id=task["context"].get("actor_id", scope.owner_id),
            snapshot_id=snapshot(
                connection,
                scope,
                task["project_id"],
                {"records": records},
                mode=task["context"]["mode"],
                kind="report_dataset",
                window=window.model_dump(mode="json"),
            ),
            window=window.model_dump(mode="json"),
            mode=task["context"]["mode"],
            row_count=len(rows),
        )
        connection.execute(r.datasets.insert().values(**dataset))
        if rows:
            connection.execute(r.facts.insert(), [fact(scope, dataset, row) for row in rows])
        return dataset


def fact(scope, dataset, row):
    data = article_payload(dict(row))
    # 未完成的新一轮分析不能沿用上一轮 sentiment 冒充本轮已完成结果。
    sentiment = (
        data.get("sentiment", "unknown") if data.get("assessment_status") == "done" else "unknown"
    )
    return dict(
        **base(scope, dataset["project_id"]),
        dataset_id=dataset["id"],
        article_id=row["id"],
        revision=row["revision"],
        ingested_at=row["ingested_at"],
        sentiment=sentiment,
        platform=str(
            data.get("raw", {}).get("platform_name") or data.get("media_type") or "未知平台"
        )[:200],
        source=str(data.get("source") or "未知来源")[:200],
        brand=str(data.get("predicted_car") or "未标注")[:1000],
        problem=str(data.get("question_type") or "未标注")[:1000],
        review_status=data.get("review_status", "pending"),
        assessment_status=data.get("assessment_status", "unknown"),
        data=data,
    )
