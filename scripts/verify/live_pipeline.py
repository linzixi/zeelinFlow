"""用合成新闻验证真实模型研判、报告与 Word 产物，不连接业务源或发送消息。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: no (isolated tenant per run, diagnostic records retained)
Requires: native Gateway, configured model, local database and PAT
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ace_ext.core.config import Settings
from ace_ext.core.contracts import ArticleInput, Window
from ace_ext.execution.agent_worker import AgentWorker
from ace_ext.execution.native_runs import NativeRuns
from ace_ext.persistence import schema as s
from ace_ext.persistence.articles import ArticleRepository
from ace_ext.persistence.database import Database, Scope
from ace_ext.persistence.projects import ProjectRepository
from ace_ext.persistence.tasks import TaskRepository
from ace_ext.workflow.models import Graph

ROOT = Path(__file__).resolve().parents[2]


def graph() -> Graph:
    return Graph.model_validate(
        {
            "nodes": [
                {
                    "id": "judge",
                    "title": "合成新闻风险研判",
                    "type": "llm_record_analysis",
                    "executor": "agent",
                    "operation": "judge",
                    "instructions": "这是隔离合成验证。"
                    "只按给定正文逐条判断风险、情感、是否需要报送。"
                    "公共安全召回为高风险且decision=report；"
                    "普通上新为低风险且decision=observe。"
                    "保留全部记录。不得联网、使用bash、发送消息。",
                },
                {
                    "id": "report",
                    "title": "合成预警报告",
                    "type": "document_template",
                    "executor": "agent",
                    "operation": "report",
                    "instructions": "只根据输入中decision=report的记录撰写中文预警报告，"
                    "含标题、摘要、依据和来源。正文明确标注合成验证。"
                    '返回artifacts数组，每个元素包含"name":"验证报告.md"和"content":"正文"。'
                    "records保留报告引用的记录。不得联网、使用bash、发送消息。",
                },
            ],
            "edges": [{"id": "jr", "source": "judge", "target": "report"}],
        }
    )


async def execute(repo, worker, scope, project_id):
    now = datetime.now(UTC)
    run = repo.launch(
        scope,
        project_id,
        origin="manual",
        mode="live",
        key="verify",
        window=Window(start=now - timedelta(minutes=150), end=now),
    )
    outputs = []
    for _ in range(2):
        task = repo.claim("agent", lease_seconds=420)
        try:
            result = await worker.execute(task, repo.input(task))
            repo.complete(task["id"], task["lease_token"], result)
            outputs.append(result)
        except Exception:
            repo.fail(
                task["id"], task["lease_token"], "真实链路验证未通过", retryable=False
            )
            raise
    assert repo.detail(scope, project_id, run["id"])["status"] == "succeeded"
    assert any(row["risk"] == "high" for row in outputs[0].records)
    assert any(item["name"].endswith(".docx") for item in outputs[-1].artifacts)
    return {
        "status": "passed",
        "run_id": run["id"],
        "synthetic": True,
        "external_delivery": False,
        "nodes": [output.context for output in outputs],
        "artifacts": [item["name"] for item in outputs[-1].artifacts],
    }


async def main() -> None:
    settings = Settings(_env_file=ROOT / ".env")
    database = Database(settings.database_url.get_secret_value())
    scope = Scope("verify_" + uuid.uuid4().hex, settings.ace_df_agent_owner_id)
    project = ProjectRepository(database).create(scope, "隔离真实研判与报告", graph())
    repo, client = (
        TaskRepository(database, tenant_id=scope.tenant_id),
        NativeRuns(settings),
    )
    worker = AgentWorker(repo, 360)
    worker.bind(scope.owner_id, client)
    ArticleRepository(database).ingest(
        scope,
        project["id"],
        [
            ArticleInput(
                source_id="synthetic-a",
                title="【模拟】食品企业因污染风险召回产品",
                content="合成验证：样例企业发现产品存在污染隐患，启动全国召回并公布退款安排。",
                url="https://example.invalid/recall",
                ingested_at=datetime.now(UTC),
            ),
            ArticleInput(
                source_id="synthetic-b",
                title="【模拟】品牌发布常规新品",
                content="合成验证：样例品牌按计划推出新品，无异常事件。",
                url="https://example.invalid/launch",
                ingested_at=datetime.now(UTC),
            ),
        ],
        mode="live",
    )
    try:
        report = await execute(repo, worker, scope, project["id"])
        destination = ROOT / "output/verification/live-pipeline.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))
    finally:
        with database.transaction() as connection:
            connection.execute(
                s.projects.update()
                .where(s.projects.c.id == project["id"])
                .values(deleted_at=time.time())
            )
        await client.close()
        database.close()


if __name__ == "__main__":
    asyncio.run(main())
