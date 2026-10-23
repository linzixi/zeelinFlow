from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from ace_ext.api import models as m
from ace_ext.core.contracts import Window
from ace_ext.core.errors import AceError, Forbidden
from ace_ext.execution.service import ExecutionService
from ace_ext.governance.actions import (
    is_reviewer,
    list_canvases,
    require_reviewable,
    resolve_action_scope,
)
from ace_ext.persistence.database import Scope
from ace_ext.persistence.migrations import VERSION
from ace_ext.persistence.projects import ProjectRepository
from ace_ext.workflow.catalog import build_registry
from ace_ext.workflow.importer import import_cmc


class Actions:
    def __init__(self, service: ExecutionService, sample: Path):
        self.service, self.sample = service, sample
        self.projects = ProjectRepository(service.database)
        self.schemas = {
            "list_projects": m.ListProjects,
            "access": m.Empty,
            "create_project": m.CreateProject,
            "seed_cmc": m.Empty,
            "get_project": m.ProjectRequest,
            "save_project": m.SaveProject,
            "catalog": m.Empty,
            "run": m.RunRequest,
            "list_runs": m.ProjectRequest,
            "run_detail": m.RunDetail,
            "cancel_run": m.RunDetail,
            "retry_task": m.TaskRequest,
            "replay_task": m.ReplayRequest,
            "list_articles": m.ArticleQuery,
            "update_article": m.UpdateArticle,
            "article_history": m.ArticleHistory,
            "import_articles": m.ImportArticles,
            "snapshot": m.SnapshotRequest,
            "health": m.Empty,
        }

    def handler(self, name: str):
        async def handle(payload, context):
            try:
                request = self.schemas[name].model_validate(payload)
                scope = await asyncio.to_thread(
                    resolve_action_scope,
                    self.service.governance,
                    context.principal.user_id,
                    name,
                    getattr(request, "project_id", ""),
                )
                if context.agent_runs is not None:
                    self.service.agents.bind(context.principal.user_id, context.agent_runs)
                result = await asyncio.to_thread(self._dispatch, name, scope, request)
                if name == "cancel_run":
                    await self._cancel_agents(result, context.agent_runs)
                return {"ok": True, "data": result}
            except ValidationError:
                return {
                    "ok": False,
                    "error": {"code": "invalid", "message": "参数无效，请检查输入"},
                }
            except AceError as exc:
                return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
            except ValueError:
                return {"ok": False, "error": {"code": "invalid", "message": "节点或时间配置无效"}}

        return handle

    async def _cancel_agents(self, result: dict, handle) -> None:
        if handle is None:
            return
        for task in result.get("tasks", []):
            if task.get("thread_id") and task.get("agent_run_id"):
                await handle.cancel(thread_id=task["thread_id"], run_id=task["agent_run_id"])

    def _dispatch(self, name: str, scope: Scope, request) -> object:
        params = request.model_dump(exclude={"project_id"})
        project_id = getattr(request, "project_id", "")
        tasks, articles = self.service.tasks, self.service.articles
        if name == "access":
            return self.service.governance.context(scope.actor)
        if name == "health":
            return {
                "database": "connected",
                "redis": self.service.queue.health(),
                "workers": len(self.service.workers),
                "schemaVersion": VERSION,
            }
        if name == "catalog":
            return [asdict(node) for node in build_registry().palette()]
        if name == "list_projects":
            return list_canvases(self.service.governance, scope.actor, request)
        if name == "create_project":
            raise Forbidden("请在团队项目内新建画布")
        if name == "seed_cmc":
            result = self._seed(scope)
            self.service.governance.bootstrap(scope.owner_id)
            return result
        if name == "get_project":
            return self.projects.get(scope, project_id)
        if name == "save_project":
            return self.projects.save(
                scope, project_id, request.graph, request.revision, name=request.name
            )
        if name == "run":
            return self._run(scope, request)
        if name == "list_runs":
            return tasks.list(scope, project_id)
        if name == "run_detail":
            return tasks.detail(scope, project_id, request.run_id)
        if name == "cancel_run":
            return tasks.cancel(scope, project_id, request.run_id)
        if name == "retry_task":
            return tasks.retry(scope, project_id, request.task_id)
        if name == "replay_task":
            return tasks.replay(
                scope, project_id, request.task_id, key=request.key, downstream=request.downstream
            )
        if name == "list_articles":
            params["alerts_only"] = is_reviewer(self.service.governance, scope)
            return articles.list(scope, project_id, **params)
        if name in {"update_article", "article_history"} and is_reviewer(
            self.service.governance, scope
        ):
            require_reviewable(articles, scope, project_id, request.article_id)
        if name == "update_article":
            return articles.patch(scope, project_id, request.article_id, request.patch)
        if name == "article_history":
            return articles.history(scope, project_id, request.article_id)
        if name == "import_articles":
            return articles.ingest(scope, project_id, request.records, mode=request.mode)
        if name == "snapshot":
            return articles.read_snapshot(scope, project_id, request.snapshot_id)
        raise ValueError("未知操作")

    def _seed(self, scope: Scope) -> dict:
        source = json.loads(self.sample.read_text(encoding="utf-8"))
        return self.projects.ensure_sample(
            scope,
            "CMC 资本 · 实时监测",
            import_cmc(source),
            source={
                "sample": "cmc-realtime",
                "sourceProjectId": source["sourceProjectId"],
                "sourceRevision": source["revision"],
                "mode": "simulation",
            },
        )

    def _run(self, scope: Scope, request: m.RunRequest) -> dict:
        end = request.end or datetime.now(UTC)
        definition = self.projects.get(scope, request.project_id)["graph"]["nodes"]
        first = next(
            (n for n in definition if n["id"] == request.start), definition[0] if definition else {}
        )
        lookback = request.lookback_minutes or first.get("trigger", {}).get("lookbackMinutes", 150)
        closed = first.get("config", {}).get("closed_window_minutes")
        if request.end is None and closed:
            end = end.replace(
                minute=end.minute // int(closed) * int(closed), second=0, microsecond=0
            )
        if end.tzinfo is None:
            raise ValueError("检查时间必须带时区")
        return self.service.tasks.launch(
            scope,
            request.project_id,
            origin="manual",
            mode=request.mode,
            key=request.key,
            start=request.start,
            single=request.single,
            window=Window(start=end - timedelta(minutes=lookback), end=end),
        )
