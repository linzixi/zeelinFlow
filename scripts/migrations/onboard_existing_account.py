"""将本机既有账号加入示例团队，保留原对话并绑定SGM项目个人容器。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes
Requires: native Python environment; modifies new runtime only, no passwords
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from ace_ext.core.config import Settings
from ace_ext.governance.workspaces import WorkspaceRepository
from ace_ext.persistence.database import Database, event
from deerflow.persistence.projects.sql import ProjectRepository
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/verify"))
from local_client import call, root_client

EMAIL = "1@qq.com"
THREAD = "ccdaa590-70fe-486e-9439-aa1632a084f2"


async def main():
    demo = json.loads((ROOT / "output/verification/team-demo.json").read_text("utf-8"))
    native_path = ROOT / ".runtime/deerflow/data/deerflow.db"
    with sqlite3.connect(native_path.as_uri() + "?mode=ro", uri=True) as connection:
        user = connection.execute(
            "SELECT id FROM users WHERE email=?", (EMAIL,)
        ).fetchone()[0]
    with root_client() as client:
        for team in call(client, "GET", "/api/ace/context")["teams"]:
            call(
                client,
                "PUT",
                "/api/ace/members",
                json={"team_id": team["id"], "email": EMAIL, "role": "admin"},
            )
    settings = Settings(_env_file=ROOT / ".env")
    db = Database(settings.database_url.get_secret_value())
    repo = WorkspaceRepository(db, settings.ace_df_tenant)
    repo.select_team(user, demo["team_id"])
    engine = create_async_engine("sqlite+aiosqlite:///" + native_path.as_posix())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    projects, threads = ProjectRepository(sessions), ThreadMetaRepository(sessions)
    native_id = repo.native_id(user, demo["workspace_id"])
    if not native_id:
        existing = await projects.list(user_id=user)
        native = next(
            (
                p
                for p in existing
                if p.get("presentation", {}).get("ace_workspace_id")
                == demo["workspace_id"]
            ),
            None,
        )
        if not native:
            native = await projects.create(
                name="上汽通用 · 舆情监测",
                presentation={"ace_workspace_id": demo["workspace_id"]},
                user_id=user,
            )
        native_id = native["id"]
        repo.bind_native(user, demo["workspace_id"], native_id)
    thread = await threads.get(THREAD, user_id=user)
    assert thread, "Original owner must still own the conversation"
    backup = ROOT / ".runtime/legacy-thread-before-project.json"
    if not backup.exists():
        backup.write_text(
            json.dumps(thread, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if not thread.get("metadata", {}).get("deerflow_project_id"):
        assert await threads.set_project(THREAD, native_id, user_id=user)
        with db.transaction() as connection:
            event(
                connection,
                repo.scope(user),
                demo["workspace_id"],
                "migration.thread_project_bound",
                {"thread_id": THREAD, "native_project_id": native_id},
            )
    await engine.dispose()
    db.close()
    print(
        "Existing account joined both teams; owned conversation preserved in project."
    )


if __name__ == "__main__":
    asyncio.run(main())
