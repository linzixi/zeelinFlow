from __future__ import annotations

from sqlalchemy import select

from ace_ext.core.errors import Forbidden, NotFound
from ace_ext.governance import schema as g
from ace_ext.governance.repository import GovernanceRepository
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import Scope, base
from ace_ext.persistence.projects import ProjectRepository
from ace_ext.workflow.models import Graph


class WorkspaceRepository(GovernanceRepository):
    def bootstrap(self, owner: str) -> None:
        if not owner:
            return
        context = self.context(owner)
        team = context["active_team_id"]
        if not team:
            team = self.create_team(owner, "清博智能 · 项目团队")["id"]
        for canvas in ProjectRepository(self.db).list(self.scope(owner)):
            with self.db.transaction() as connection:
                linked = connection.execute(
                    select(g.canvas_links.c.id).where(
                        g.canvas_links.c.canvas_id == canvas["id"],
                    )
                ).first()
            if not linked:
                self.create_workspace(owner, team, canvas["name"], key=canvas["id"])
                self.link_canvas(owner, canvas["id"], canvas["id"])

    def link_canvas(self, user: str, workspace_id: str, canvas_id: str) -> None:
        self.workspace(user, workspace_id, "canvas.write")
        with self.db.transaction() as connection:
            connection.execute(
                g.canvas_links.insert().values(
                    **base(self.scope(user), workspace_id),
                    canvas_id=canvas_id,
                )
            )

    def create_canvas(self, user: str, workspace_id: str, name: str, graph: Graph) -> dict:
        workspace = self.workspace(user, workspace_id, "canvas.write")
        with self.db.transaction() as connection:
            canvas = ProjectRepository(self.db).create(
                self.scope(workspace["owner_id"]),
                name,
                graph,
                source={"workspace_id": workspace_id, "created_by": user},
                connection=connection,
            )
            connection.execute(
                g.canvas_links.insert().values(
                    **base(self.scope(user), workspace_id),
                    canvas_id=canvas["id"],
                )
            )
        return canvas

    def canvas_scope(self, user: str, canvas_id: str, permission: str) -> Scope:
        with self.db.transaction() as connection:
            row = (
                connection.execute(
                    select(s.projects.c.owner_id, g.canvas_links.c.project_id)
                    .join(
                        g.canvas_links,
                        g.canvas_links.c.canvas_id == s.projects.c.id,
                    )
                    .where(s.projects.c.id == canvas_id, s.projects.c.tenant_id == self.tenant)
                )
                .mappings()
                .first()
            )
        if row:
            workspace = self.workspace(user, row["project_id"], permission)
            if self.context(user)["active_team_id"] != workspace["team_id"]:
                raise Forbidden("请先切换到画布所属团队")
            return Scope(self.tenant, row["owner_id"], actor_id=user)
        # 未归属的旧私人画布仍由原仓储的owner过滤保护。
        return self.scope(user)

    def canvases(self, user: str, workspace_id: str) -> list[dict]:
        self.workspace(user, workspace_id)
        with self.db.transaction() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(s.projects)
                    .join(
                        g.canvas_links,
                        g.canvas_links.c.canvas_id == s.projects.c.id,
                    )
                    .where(
                        g.canvas_links.c.project_id == workspace_id,
                        g.canvas_links.c.tenant_id == self.tenant,
                        s.projects.c.deleted_at.is_(None),
                    )
                ).mappings()
            ]

    def native_binding(self, user: str, native_id: str) -> dict:
        with self.db.transaction() as connection:
            row = (
                connection.execute(
                    select(g.native_projects).where(
                        g.native_projects.c.tenant_id == self.tenant,
                        g.native_projects.c.user_id == user,
                        g.native_projects.c.native_id == native_id,
                    )
                )
                .mappings()
                .first()
            )
        if not row:
            raise NotFound("请从团队项目入口打开项目")
        workspace = self.workspace(user, row["project_id"], "chat")
        if self.context(user)["active_team_id"] != workspace["team_id"]:
            raise Forbidden("请先切换到项目所属团队")
        return dict(row)

    def native_id(self, user: str, workspace_id: str) -> str | None:
        with self.db.transaction() as connection:
            return connection.execute(
                select(g.native_projects.c.native_id).where(
                    g.native_projects.c.tenant_id == self.tenant,
                    g.native_projects.c.project_id == workspace_id,
                    g.native_projects.c.user_id == user,
                )
            ).scalar()

    def bind_native(self, user: str, workspace_id: str, native_id: str) -> None:
        self.workspace(user, workspace_id, "chat")
        with self.db.transaction() as connection:
            connection.execute(
                g.native_projects.insert().values(
                    **base(self.scope(user), workspace_id),
                    user_id=user,
                    native_id=native_id,
                )
            )
