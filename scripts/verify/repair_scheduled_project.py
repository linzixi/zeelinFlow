"""精确修复用户已确认的定时任务项目归属，不运行任务或发送通知。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes; only NULL -> confirmed project
Requires: stopped Gateway for --apply; native Python and root .env
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ace_ext.governance.policy import TeamAuthorization
from deerflow.persistence import bootstrap

ROOT = Path(__file__).resolve().parents[2]
OWNER = "6e346930-6540-4112-85ff-dc7ea4ff1402"
TASK = "task-738aefb198c040e8b71f9fdbc5fb2bfa"
PROJECT = "b3b4d7dadf0646128a84d0bfc70a4fa5"
THREADS = ("756a5ffd-85d3-4962-9034-c6444b265ae2", "06928c8c-d725-4c2e-9861-2815e3503ffe")


def verify(connection: sqlite3.Connection) -> dict:
    assert connection.execute("SELECT email FROM users WHERE id=?", (OWNER,)).fetchone()[0] == "1@qq.com"
    assert connection.execute("SELECT user_id,status FROM projects WHERE id=?", (PROJECT,)).fetchone() == (OWNER, "active")
    assert not connection.execute("SELECT 1 FROM runs WHERE status IN ('pending','running') LIMIT 1").fetchone(), "运行尚未结束"
    assert not connection.execute("SELECT 1 FROM scheduled_task_runs WHERE status IN ('queued','launching','running') LIMIT 1").fetchone(), "定时运行尚未结束"
    task = connection.execute("SELECT user_id,status,next_run_at,run_count FROM scheduled_tasks WHERE id=?", (TASK,)).fetchone()
    assert task and task[0] == OWNER
    for thread in THREADS:
        row = connection.execute("SELECT user_id,project_id FROM threads_meta WHERE thread_id=?", (thread,)).fetchone()
        assert row and row[0] == OWNER and row[1] in (None, PROJECT)
        assert connection.execute("SELECT 1 FROM scheduled_task_runs WHERE task_id=? AND thread_id=?", (TASK, thread)).fetchone()
    policy = TeamAuthorization(str(ROOT / ".env"))
    try:
        assert asyncio.run(policy.authorize_scheduled_project(OWNER, PROJECT))
    finally:
        policy.db.close()
    return {"task_id": TASK, "project_id": PROJECT, "thread_ids": THREADS, "schedule_before": task[1:]}


async def migrate(path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    try:
        await asyncio.to_thread(command.upgrade, bootstrap._get_alembic_config(engine), "head")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    apply = parser.parse_args().apply
    path = ROOT / ".runtime/deerflow/data/deerflow.db"
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        report = verify(connection)
        if apply:
            with socket.socket() as probe:
                assert probe.connect_ex(("127.0.0.1", 8001)) != 0, "先停止 Gateway"
            backup = ROOT / ".runtime/backups" / f"scheduled-project-{datetime.now(UTC):%Y%m%dT%H%M%S}.db"
            backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(backup) as target:
                connection.backup(target)
    if apply:
        asyncio.run(migrate(path))
        with sqlite3.connect(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            verify(connection)
            assigned = connection.execute("SELECT project_id FROM scheduled_tasks WHERE id=?", (TASK,)).fetchone()[0]
            assert assigned in (None, PROJECT), "任务已有其他归属，停止修复"
            now = datetime.now(UTC).replace(tzinfo=None).isoformat(" ")
            connection.execute("UPDATE scheduled_tasks SET project_id=?,updated_at=? WHERE id=? AND user_id=? AND project_id IS NULL", (PROJECT, now, TASK, OWNER))
            for thread in THREADS:
                connection.execute("UPDATE threads_meta SET project_id=?,updated_at=? WHERE thread_id=? AND user_id=? AND project_id IS NULL", (PROJECT, now, thread, OWNER))
            after = verify(connection)
            assert after["schedule_before"] == report["schedule_before"]
        report["applied"] = True
        report["backup"] = str(backup.relative_to(ROOT))
        report["notifications_sent"] = 0
        output = ROOT / "output/verification/scheduled-project-repair.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
