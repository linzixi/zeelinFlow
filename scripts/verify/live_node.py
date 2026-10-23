"""在独立验证租户验证真实 DeerFlow 节点与文件工具，不发送业务消息。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: no (each run retains diagnostic records)
Requires: local native Gateway, configured model and local PAT
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ace_ext.core.config import Settings
from ace_ext.core.contracts import Window
from ace_ext.execution.agent_worker import AgentWorker
from ace_ext.execution.native_runs import NativeRuns
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import Database, Scope
from ace_ext.persistence.projects import ProjectRepository
from ace_ext.persistence.tasks import TaskRepository
from ace_ext.workflow.models import Graph

ROOT = Path(__file__).resolve().parents[2]


async def main() -> None:
    settings = Settings(_env_file=ROOT / ".env")
    database = Database(settings.database_url.get_secret_value())
    scope = Scope("verify_" + uuid.uuid4().hex, settings.ace_df_agent_owner_id)
    marker = "ACE_NATIVE_" + uuid.uuid4().hex[:12]
    graph = build_graph(marker)
    project = ProjectRepository(database).create(scope, "隔离原生能力验证", graph)
    repo, client = (
        TaskRepository(database, tenant_id=scope.tenant_id),
        NativeRuns(settings),
    )
    worker = AgentWorker(repo, 240)
    worker.bind(scope.owner_id, client)
    now = datetime.now(UTC)
    run = repo.launch(
        scope,
        project["id"],
        origin="manual",
        mode="live",
        key="proof",
        window=Window(start=now - timedelta(minutes=1), end=now),
    )
    task = repo.claim("agent", lease_seconds=300)
    try:
        output = await worker.execute(task, repo.input(task))
        assert marker in output.summary
        state = await client.get_state(thread_id=output.context["deerflow_thread_id"])
        messages = state.get("values", state).get("messages", [])
        calls = [
            call.get("name")
            for message in messages
            for call in message.get("tool_calls", [])
        ]
        assert "write_file" in calls and "read_file" in calls, calls
        repo.complete(task["id"], task["lease_token"], output)
        report = {
            "status": "passed",
            "run_id": run["id"],
            "task_id": task["id"],
            "native_thread_id": output.context["deerflow_thread_id"],
            "native_run_id": output.context["deerflow_run_id"],
            "tools": calls,
            "input": "synthetic",
            "external_delivery": False,
        }
        destination = ROOT / "output" / "verification"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "live-node.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report))
    except Exception as exc:  # noqa: BLE001 - CLI boundary records failure and always cleans up
        repo.fail(
            task["id"],
            task["lease_token"],
            "原生执行验证未通过，请查关联会话",
            retryable=False,
        )
        print(
            json.dumps(
                {"status": "failed", "kind": type(exc).__name__, "task_id": task["id"]}
            )
        )
        raise SystemExit(1) from None
    finally:
        with database.transaction() as connection:
            connection.execute(
                s.projects.update()
                .where(s.projects.c.id == project["id"])
                .values(deleted_at=time.time())
            )
        await client.close()
        database.close()


def build_graph(marker):
    return Graph.model_validate(
        {
            "nodes": [
                {
                    "id": "proof",
                    "title": "原生 Agent 与文件工具验证",
                    "type": "code_agent",
                    "executor": "agent",
                    "operation": "judge",
                    "instructions": f"这是一轮合成测试。必须调用 write_file 工具将 {marker} 写入 "
                    "/mnt/user-data/workspace/ace-proof.txt，然后调用 read_file 读取确认。"
                    f"不要调用 bash、不联网搜索、不发送消息。最终 summary 只写实际读回的 {marker}，"
                    "records=[]，artifacts=[]，context.hasItems=false；仅返回要求的 JSON 对象。",
                }
            ]
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
