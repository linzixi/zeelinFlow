from __future__ import annotations

from sqlalchemy import select

from ace_ext.core.errors import Conflict, Forbidden, NotFound
from ace_ext.governance import schema as g
from ace_ext.governance.roles import PERMISSIONS, ROLE_LABELS, allowed
from ace_ext.persistence.database import Database, Scope, base, event, identifier


class GovernanceRepository:
    def __init__(self, database: Database, tenant: str):
        self.db, self.tenant = database, tenant

    def scope(self, user: str) -> Scope:
        return Scope(self.tenant, user)

    def member(self, user: str, team: str, connection=None) -> dict | None:
        query = select(g.members).where(
            g.members.c.tenant_id == self.tenant,
            g.members.c.project_id == team,
            g.members.c.user_id == user,
            g.members.c.role != "disabled",
        )
        if connection is None:
            with self.db.transaction() as current:
                return self.member(user, team, current)
        row = connection.execute(query).mappings().first()
        return dict(row) if row else None

    def require(self, user: str, team: str, permission: str, connection=None) -> dict:
        member = self.member(user, team, connection)
        if not member or not allowed(member["role"], permission):
            raise Forbidden("当前团队角色没有此操作权限")
        return member

    def create_team(self, user: str, name: str) -> dict:
        key = identifier()
        row = {**base(self.scope(user), key, key=key), "name": name}
        with self.db.transaction() as connection:
            connection.execute(g.teams.insert().values(**row))
            connection.execute(
                g.members.insert().values(
                    **base(self.scope(user), key),
                    user_id=user,
                    role="admin",
                    label=user,
                    revision=1,
                )
            )
            event(connection, self.scope(user), key, "team.created", {"actor": user})
        self.select_team(user, key)
        return row

    def set_member(
        self, actor: str, team: str, user: str, role: str, label: str, revision: int | None = None
    ) -> dict:
        if role not in {*ROLE_LABELS, "disabled"}:
            raise Forbidden("角色无效")
        with self.db.transaction() as connection:
            # 团队行串行化管理员调整，避免并发降权造成无管理员。
            connection.execute(
                select(g.teams.c.id)
                .where(
                    g.teams.c.id == team,
                    g.teams.c.tenant_id == self.tenant,
                )
                .with_for_update()
            ).first()
            self.require(actor, team, "team.manage", connection)
            query = select(g.members).where(
                g.members.c.tenant_id == self.tenant,
                g.members.c.project_id == team,
                g.members.c.user_id == user,
            )
            old = connection.execute(query).mappings().first()
            if old and revision is not None and old["revision"] != revision:
                raise Conflict("成员权限已变更，请刷新后重试")
            if old and old["role"] == "admin" and role != "admin":
                admins = connection.execute(
                    select(g.members.c.id).where(
                        g.members.c.tenant_id == self.tenant,
                        g.members.c.project_id == team,
                        g.members.c.role == "admin",
                    )
                ).all()
                if len(admins) <= 1:
                    raise Conflict("团队至少保留一名管理员")
            changes = {
                "role": role,
                "label": label,
                "revision": (old["revision"] if old else 0) + 1,
            }
            if old:
                connection.execute(
                    g.members.update().where(g.members.c.id == old["id"]).values(**changes)
                )
            else:
                connection.execute(
                    g.members.insert().values(
                        **base(self.scope(actor), team), user_id=user, **changes
                    )
                )
            event(
                connection,
                self.scope(actor),
                team,
                "team.member_changed",
                {
                    "actor": actor,
                    "user_id": user,
                    "before": old["role"] if old else None,
                    **changes,
                },
            )
        return {"user_id": user, **changes}

    def select_team(self, user: str, team: str) -> None:
        with self.db.transaction() as connection:
            self.require(user, team, "projects.read", connection)
            query = (g.preferences.c.tenant_id == self.tenant) & (
                g.preferences.c.project_id == user
            )
            old = connection.execute(select(g.preferences.c.id).where(query)).first()
            if old:
                connection.execute(g.preferences.update().where(query).values(active_team_id=team))
            else:
                connection.execute(
                    g.preferences.insert().values(
                        **base(self.scope(user), user), active_team_id=team
                    )
                )

    def context(self, user: str) -> dict:
        with self.db.transaction() as connection:
            teams = [
                dict(row)
                for row in connection.execute(
                    select(
                        g.teams.c.id,
                        g.teams.c.name,
                        g.members.c.role,
                    )
                    .join(g.members, g.members.c.project_id == g.teams.c.id)
                    .where(
                        g.teams.c.tenant_id == self.tenant,
                        g.members.c.tenant_id == self.tenant,
                        g.members.c.user_id == user,
                        g.members.c.role != "disabled",
                    )
                ).mappings()
            ]
            selected = connection.execute(
                select(g.preferences.c.active_team_id).where(
                    g.preferences.c.tenant_id == self.tenant,
                    g.preferences.c.project_id == user,
                )
            ).scalar()
            active = next(
                (row for row in teams if row["id"] == selected), teams[0] if teams else None
            )
            role = active["role"] if active else "none"
            return {
                "user_id": user,
                "teams": teams,
                "active_team_id": active["id"] if active else None,
                "role": role,
                "permissions": sorted(PERMISSIONS.get(role, [])),
                "roles": ROLE_LABELS,
            }

    def list_members(self, user: str, team: str) -> list[dict]:
        with self.db.transaction() as connection:
            self.require(user, team, "team.manage", connection)
            return [
                dict(row)
                for row in connection.execute(
                    select(g.members).where(
                        g.members.c.tenant_id == self.tenant,
                        g.members.c.project_id == team,
                    )
                ).mappings()
            ]

    def workspace(self, user: str, key: str, permission="projects.read") -> dict:
        with self.db.transaction() as connection:
            row = (
                connection.execute(
                    select(g.workspaces).where(
                        g.workspaces.c.id == key,
                        g.workspaces.c.tenant_id == self.tenant,
                        g.workspaces.c.deleted_at.is_(None),
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound("项目不存在或没有访问权限")
            self.require(user, row["team_id"], permission, connection)
            return dict(row)

    def list_workspaces(self, user: str, team: str) -> list[dict]:
        with self.db.transaction() as connection:
            self.require(user, team, "projects.read", connection)
            return [
                dict(row)
                for row in connection.execute(
                    select(g.workspaces).where(
                        g.workspaces.c.tenant_id == self.tenant,
                        g.workspaces.c.team_id == team,
                        g.workspaces.c.deleted_at.is_(None),
                    )
                ).mappings()
            ]

    def create_workspace(self, user: str, team: str, name: str, description="", key=None) -> dict:
        with self.db.transaction() as connection:
            self.require(user, team, "projects.write", connection)
            key = key or identifier()
            row = {
                **base(self.scope(user), key, key=key),
                "team_id": team,
                "owner_id": user,
                "name": name,
                "description": description,
                "deleted_at": None,
            }
            connection.execute(g.workspaces.insert().values(**row))
            return row
