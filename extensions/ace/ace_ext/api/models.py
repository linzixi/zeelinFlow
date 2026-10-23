from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ace_ext.core.contracts import ArticleInput, ArticlePatch, Contract, Mode
from ace_ext.workflow.models import Graph


class Empty(Contract):
    pass


class ListProjects(Contract):
    workspace_id: str | None = None
    native_project_id: str | None = None


class ProjectRequest(Contract):
    project_id: str = Field(min_length=1, max_length=64)


class SaveProject(ProjectRequest):
    revision: int = Field(ge=1)
    graph: Graph
    name: str = Field(min_length=1, max_length=200)


class CreateProject(Contract):
    name: str = Field(min_length=1, max_length=200)
    graph: Graph


class RunRequest(ProjectRequest):
    key: str = Field(min_length=1, max_length=180)
    mode: Mode = "simulation"
    start: str | None = None
    single: bool = False
    end: datetime | None = None
    lookback_minutes: int | None = Field(default=None, ge=1, le=44640)


class RunDetail(ProjectRequest):
    run_id: str = Field(min_length=1, max_length=64)


class TaskRequest(ProjectRequest):
    task_id: str = Field(min_length=1, max_length=64)


class ReplayRequest(TaskRequest):
    key: str = Field(min_length=1, max_length=180)
    downstream: bool = False


class ArticleQuery(ProjectRequest):
    query: str = Field(default="", max_length=200)
    risk: str = ""
    review_status: str = ""
    mode: str = ""
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class UpdateArticle(ProjectRequest):
    article_id: str = Field(min_length=1, max_length=64)
    patch: ArticlePatch


class ArticleHistory(ProjectRequest):
    article_id: str = Field(min_length=1, max_length=64)


class ImportArticles(ProjectRequest):
    mode: Mode = "simulation"
    records: list[ArticleInput] = Field(max_length=1000)


class SnapshotRequest(ProjectRequest):
    snapshot_id: str = Field(min_length=1, max_length=64)
