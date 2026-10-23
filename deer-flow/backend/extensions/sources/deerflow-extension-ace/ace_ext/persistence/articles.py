from __future__ import annotations

import time

from sqlalchemy import func, select

from ace_ext.core.contracts import ArticleInput, ArticlePatch, Window
from ace_ext.core.errors import Conflict, NotFound
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import (
    Database,
    Scope,
    base,
    digest,
    event,
    project,
    snapshot,
    where_scope,
)


def article_payload(row: dict) -> dict:
    return {**row["data"], "id": row["id"], "revision": row["revision"], "mode": row["mode"]}


def capture_articles(
    connection, scope: Scope, project_id: str, window: Window, mode: str, branch: str | None = None
) -> str:
    query = select(s.articles).where(
        where_scope(s.articles, scope, project_id),
        s.articles.c.mode == mode,
        s.articles.c.deleted_at.is_(None),
        s.articles.c.ingested_at >= window.start.timestamp(),
        s.articles.c.ingested_at < window.end.timestamp(),
    )
    if branch:
        query = query.where(s.articles.c.branch == branch)
    records = [article_payload(dict(row)) for row in connection.execute(query).mappings()]
    return snapshot(
        connection,
        scope,
        project_id,
        {"schemaVersion": 1, "records": records, "context": {}, "artifacts": []},
        mode=mode,
        kind="warehouse",
        window=window.model_dump(mode="json"),
    )


def read_snapshot(connection, scope: Scope, project_id: str, snapshot_id: str) -> dict:
    row = (
        connection.execute(
            select(s.snapshots).where(
                where_scope(s.snapshots, scope, project_id), s.snapshots.c.id == snapshot_id
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NotFound("数据快照不存在")
    return dict(row)


class ArticleRepository:
    def __init__(self, database: Database):
        self.db = database

    def ingest(
        self, scope: Scope, project_id: str, records: list[ArticleInput], *, mode: str
    ) -> list[dict]:
        with self.db.transaction() as connection:
            project(connection, scope, project_id, lock=True)
            result = [
                self._ingest_one(connection, scope, project_id, record, mode) for record in records
            ]
            event(connection, scope, project_id, "articles.ingested", {"count": len(result)})
            return result

    def _ingest_one(
        self, connection, scope: Scope, project_id: str, record: ArticleInput, mode: str
    ) -> dict:
        identity = digest(record.url.strip() or f"{record.source}:{record.source_id}")
        existing = (
            connection.execute(
                select(s.articles)
                .where(
                    where_scope(s.articles, scope, project_id),
                    s.articles.c.identity_hash == identity,
                    s.articles.c.mode == mode,
                )
                .with_for_update()
            )
            .mappings()
            .first()
        )
        data = record.model_dump(mode="json")
        if existing:
            row = dict(existing)
            data = {**row["data"], **data, **row["overrides"]}
            # 首次入库时间定义增量归属，重复抓取不能把旧记录变为新消息。
            data["ingested_at"] = row["data"]["ingested_at"]
            row.update(data=data, revision=row["revision"] + 1, updated_at=time.time())
            connection.execute(
                s.articles.update()
                .where(s.articles.c.id == row["id"])
                .values(data=data, revision=row["revision"], updated_at=row["updated_at"])
            )
        else:
            data.update(
                summary="", sentiment="unknown", risk="unknown", tags=[], review_status="pending"
            )
            row = dict(
                **base(scope, project_id),
                identity_hash=identity,
                revision=1,
                data=data,
                overrides={},
                mode=mode,
                branch=record.branch,
                risk="unknown",
                review_status="pending",
                ingested_at=record.ingested_at.timestamp(),
                updated_at=time.time(),
                deleted_at=None,
            )
            connection.execute(s.articles.insert().values(**row))
        self._history(connection, scope, row, "collector", "采集入库")
        return row

    def list(
        self,
        scope: Scope,
        project_id: str,
        *,
        query: str = "",
        risk: str = "",
        review_status: str = "",
        mode: str = "",
        offset: int = 0,
        limit: int = 50,
        alerts_only: bool = False,
    ) -> dict:
        with self.db.transaction() as connection:
            project(connection, scope, project_id)
            filters = [
                where_scope(s.articles, scope, project_id),
                s.articles.c.deleted_at.is_(None),
            ]
            if alerts_only:
                filters.append(s.articles.c.data["decision"].as_string().in_(["report", "review"]))
            for field, value in [("risk", risk), ("review_status", review_status), ("mode", mode)]:
                if value:
                    filters.append(s.articles.c[field] == value)
            if query:
                filters.append(
                    s.articles.c.data["title"].as_string().contains(query, autoescape=True)
                )
            total = connection.execute(
                select(func.count()).select_from(s.articles).where(*filters)
            ).scalar()
            rows = connection.execute(
                select(s.articles)
                .where(*filters)
                .order_by(s.articles.c.updated_at.desc(), s.articles.c.id)
                .offset(max(0, offset))
                .limit(min(max(limit, 1), 200))
            ).mappings()
            return {"items": [dict(row) for row in rows], "total": total}

    def patch(self, scope: Scope, project_id: str, article_id: str, patch: ArticlePatch) -> dict:
        with self.db.transaction() as connection:
            project(connection, scope, project_id, lock=True)
            row = self._get(connection, scope, project_id, article_id)
            if row["revision"] != patch.revision:
                raise Conflict("文章已更新，请重新加载后修改")
            changes = patch.model_dump(exclude_none=True, exclude={"revision", "note"})
            updated = {
                **row,
                "data": {**row["data"], **changes},
                "overrides": {**row["overrides"], **changes},
                "revision": row["revision"] + 1,
                "updated_at": time.time(),
            }
            updated.update(
                {key: value for key, value in changes.items() if key in ("risk", "review_status")}
            )
            result = connection.execute(
                s.articles.update()
                .where(s.articles.c.id == article_id, s.articles.c.revision == patch.revision)
                .values(**updated)
            )
            if result.rowcount != 1:
                raise Conflict("文章版本冲突")
            self._history(connection, scope, updated, scope.actor, patch.note or "人工修订")
            event(
                connection,
                scope,
                project_id,
                "article.revised",
                {"article_id": article_id, "revision": updated["revision"]},
            )
            return updated

    def history(self, scope: Scope, project_id: str, article_id: str) -> list[dict]:
        with self.db.transaction() as connection:
            project(connection, scope, project_id)
            query = select(s.article_revisions).where(
                where_scope(s.article_revisions, scope, project_id),
                s.article_revisions.c.article_id == article_id,
            )
            return [
                dict(row)
                for row in connection.execute(
                    query.order_by(s.article_revisions.c.revision.desc())
                ).mappings()
            ]

    def capture(self, scope: Scope, project_id: str, window: Window, *, mode: str) -> str:
        with self.db.transaction() as connection:
            project(connection, scope, project_id, lock=True)
            return capture_articles(connection, scope, project_id, window, mode)

    def compare_history(
        self, scope: Scope, project_id: str, records: list[dict], *, before: float
    ) -> list[dict]:
        """以本轮开始前的已落库分析为比较基线，不把本轮采集修订当历史判断。"""
        ids = [row["id"] for row in records]
        with self.db.transaction() as connection:
            project(connection, scope, project_id)
            query = select(s.article_revisions).where(
                where_scope(s.article_revisions, scope, project_id),
                s.article_revisions.c.article_id.in_(ids),
                s.article_revisions.c.created_at < before,
                s.article_revisions.c.actor.startswith("task:"),
            )
            previous = {}
            for row in connection.execute(
                query.order_by(s.article_revisions.c.revision.desc())
            ).mappings():
                if row["data"].get("assessment_status") == "done":
                    previous.setdefault(row["article_id"], row["data"])
        return [
            {
                **row,
                "history": {
                    "previously_assessed": row["id"] in previous,
                    "previous": previous.get(row["id"]),
                    "cutoff": before,
                },
            }
            for row in records
        ]

    def read_snapshot(self, scope: Scope, project_id: str, snapshot_id: str) -> dict:
        with self.db.transaction() as connection:
            project(connection, scope, project_id)
            return read_snapshot(connection, scope, project_id, snapshot_id)

    @staticmethod
    def _get(connection, scope: Scope, project_id: str, article_id: str) -> dict:
        row = (
            connection.execute(
                select(s.articles)
                .where(
                    where_scope(s.articles, scope, project_id),
                    s.articles.c.id == article_id,
                    s.articles.c.deleted_at.is_(None),
                )
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if row is None:
            raise NotFound("文章不存在")
        return dict(row)

    @staticmethod
    def _history(connection, scope: Scope, row: dict, actor: str, reason: str) -> None:
        connection.execute(
            s.article_revisions.insert().values(
                **base(scope, row["project_id"]),
                article_id=row["id"],
                revision=row["revision"],
                data=row["data"],
                actor=actor,
                reason=reason,
            )
        )
