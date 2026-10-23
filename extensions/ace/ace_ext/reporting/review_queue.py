"""从对话的可信项目归属查询实时审核队列，不读取报告冻结快照。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.run_origin import DEERFLOW_ORIGIN_KEY
from sqlalchemy import case, func, select

from ace_ext.core.errors import Forbidden, Unavailable
from ace_ext.governance import schema as g
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import Scope, event, identifier
from ace_ext.reporting.review_queue_details import QueueOptions, read_details


async def query_review_queue(
    service, user: str, thread_id: str, options: QueueOptions | None = None
) -> dict:
    """身份与项目只从宿主线程表读取；模型不能指定其他项目或用户。"""
    factory = getattr(service, "native_session_factory", None)
    if factory is None:
        raise Unavailable("项目数据查询服务尚未就绪，请稍后重试；不能将失败当作零条")
    if not user or not thread_id:
        raise Forbidden("请在已选择项目的对话中查询待审核数量")
    async with factory() as session:
        row = (
            await session.execute(
                select(ThreadMetaRow.project_id, ThreadMetaRow.metadata_json)
                .join(ProjectRow, ProjectRow.id == ThreadMetaRow.project_id)
                .where(
                    ThreadMetaRow.thread_id == thread_id,
                    ThreadMetaRow.user_id == user,
                    ProjectRow.user_id == user,
                    ProjectRow.status == "active",
                )
            )
        ).first()
    if row is None:
        raise Forbidden("当前对话没有可访问的有效项目，请先选择项目")
    background = (row.metadata_json or {}).get(DEERFLOW_ORIGIN_KEY, {}).get("kind") == "schedule"
    return await asyncio.to_thread(
        read_queue, service, user, thread_id, row.project_id, background=background, options=options
    )


def read_queue(
    service, user: str, thread_id: str, native_id: str, *, background=False, options=None
) -> dict:
    """与文章列表使用同一实时表与预警判定，聚合后记录查询口径和结果。"""
    repo = service.governance
    with service.database.transaction() as connection:
        workspace_id = connection.execute(
            select(g.native_projects.c.project_id).where(
                g.native_projects.c.tenant_id == repo.tenant,
                g.native_projects.c.native_id == native_id,
                g.native_projects.c.user_id == user,
            )
        ).scalar()
        if not workspace_id:
            raise Forbidden("当前对话未关联团队项目")
        workspace = repo.workspace(user, workspace_id, "chat")
        repo.require(user, workspace["team_id"], "articles.read", connection)
        if not background and repo.context(user)["active_team_id"] != workspace["team_id"]:
            raise Forbidden("请切换到对话所属团队后查询")
        canvases = connection.execute(
            select(s.projects.c.id, s.projects.c.name)
            .join(g.canvas_links, g.canvas_links.c.canvas_id == s.projects.c.id)
            .where(
                s.projects.c.tenant_id == repo.tenant,
                g.canvas_links.c.tenant_id == repo.tenant,
                g.canvas_links.c.project_id == workspace_id,
                s.projects.c.deleted_at.is_(None),
            )
            .order_by(s.projects.c.id)
            .limit(101)
        ).all()
        if len(canvases) > 100:
            raise Unavailable("项目画布超过100个，暂不能返回完整汇总；查询失败不代表零条")
        rows = _counts(connection, repo.tenant, [row.id for row in canvases])
        result = _result(workspace, canvases, rows)
        if options and options.include_details:
            result["details"] = read_details(connection, repo.tenant, canvases, options)
        result["query_id"] = identifier()
        event(
            connection,
            Scope(repo.tenant, workspace["owner_id"], user),
            workspace_id,
            "warehouse.review_queue",
            {"actor_id": user, "thread_id": thread_id, "native_project_id": native_id, **result},
        )
        return result


def _counts(connection, tenant: str, canvas_ids: list[str]) -> list:
    alert = s.articles.c.data["decision"].as_string().in_(["report", "review"])
    return (
        connection.execute(
            select(
                s.articles.c.project_id,
                s.articles.c.review_status,
                func.count().label("total"),
                func.sum(case((alert, 1), else_=0)).label("alerts"),
                func.max(s.articles.c.updated_at).label("updated_at"),
            )
            .where(
                s.articles.c.tenant_id == tenant,
                s.articles.c.project_id.in_(canvas_ids),
                s.articles.c.deleted_at.is_(None),
                s.articles.c.mode == "live",
            )
            .group_by(s.articles.c.project_id, s.articles.c.review_status)
        )
        .mappings()
        .all()
    )


def _result(workspace: dict, canvases: list, rows: list) -> dict:
    def summarize(items):
        return {
            "total_articles": sum(int(r["total"]) for r in items),
            "pending_articles": sum(
                int(r["total"]) for r in items if r["review_status"] == "pending"
            ),
            "alert_articles": sum(int(r["alerts"]) for r in items),
            "pending_alert_articles": sum(
                int(r["alerts"]) for r in items if r["review_status"] == "pending"
            ),
        }

    latest = max((r["updated_at"] for r in rows), default=None)
    return {
        "workspace_id": workspace["id"],
        "project_name": workspace["name"],
        "mode": "live",
        "queried_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "latest_article_update": datetime.fromtimestamp(
            latest, ZoneInfo("Asia/Shanghai")
        ).isoformat()
        if latest
        else None,
        **summarize(rows),
        "canvases": [
            {
                "canvas_id": c.id,
                "name": c.name,
                **summarize([r for r in rows if r["project_id"] == c.id]),
            }
            for c in canvases
        ],
        "definition": (
            "当前项目所有未删除画布中的 live 文章；待审核=review_status:pending；"
            "预警=decision:report或review。默认回答全部待审核，同时说明预警待审核子集。"
        ),
        "coverage": (
            "实时本地入库记录，不是报告快照或全网数据；不含simulation。"
            "相同URL在不同画布分别计数。查询时间不表示重新采集。"
        ),
    }
