"""以已核对的账号/对话归属复验真实审核统计；只产生查询审计，不启动 Agent 或通知。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes for business data; appends read audit
Requires: installed extension, local native SQLite and ACE MySQL
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from ace_ext.core.config import Settings
from ace_ext.governance.workspaces import WorkspaceRepository
from ace_ext.persistence.database import Database
from ace_ext.reporting.review_queue_tool import review_queue_tool
from deerflow.extensions.plugin_tools import _build_tool
from deerflow_extension_api.auth import ExtensionPrincipal
from deerflow_extension_api.plugins import (
    PluginContribution,
    PluginToolResult,
    ToolContext,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
OWNER = "6e346930-6540-4112-85ff-dc7ea4ff1402"


def native_probe_tool(service):
    declaration = review_queue_tool(service)
    plugin = PluginContribution(
        namespace="qingbo.ace", title="ACE", enabled=True, tools=(declaration,)
    )
    native = _build_tool("ace", plugin, declaration)

    async def handler(payload, context):
        runtime = SimpleNamespace(
            context={
                "user_id": context.principal.user_id,
                "thread_id": context.thread_id,
            }
        )
        content, artifact = await native.coroutine(runtime=runtime, **payload)
        return PluginToolResult(content=content, artifact=artifact)

    return SimpleNamespace(handler=handler)


async def verify_details(tool, context) -> dict:
    records = []
    offset = 0
    while True:
        response = await tool.handler(
            {"include_details": True, "limit": 50, "offset": offset}, context
        )
        assert response.artifact, response.content
        page = response.artifact["details"]
        records.extend(page["items"])
        if not page["has_more"]:
            break
        offset = page["next_offset"]
    assert len(records) == page["total"]
    assert len({row["id"] for row in records}) == len(records)
    assert all(row["title"] and row["review_status"] == "pending" for row in records)
    alerts = await tool.handler({"include_details": True, "alerts_only": True}, context)
    assert alerts.artifact
    return {"pending_details": records, "alert_details": alerts.artifact["details"]}


async def main() -> None:
    settings = Settings(_env_file=ROOT / ".env")
    database = Database(settings.database_url.get_secret_value())
    path = ROOT / ".runtime/deerflow/data/deerflow.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    service = SimpleNamespace(
        database=database,
        governance=WorkspaceRepository(database, settings.ace_df_tenant),
        native_session_factory=async_sessionmaker(engine),
    )
    results = {}
    try:
        tool = native_probe_tool(service)
        for kind, thread in {
            "ordinary_chat": "ccdaa590-70fe-486e-9439-aa1632a084f2",
            "scheduled_chat": "4c7dff21-416a-41c0-900c-f8b718cbb252",
        }.items():
            context = ToolContext(ExtensionPrincipal(OWNER), {}, thread)
            result = await tool.handler({}, context)
            assert result.artifact, result.content
            results[kind] = dict(result.artifact)
            results[kind]["verified_details"] = await verify_details(tool, context)
        keys = (
            "total_articles",
            "pending_articles",
            "alert_articles",
            "pending_alert_articles",
        )
        assert all(
            results["ordinary_chat"][k] == results["scheduled_chat"][k] for k in keys
        )
        output = ROOT / "output/verification/review-queue-details-live.json"
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")
        print(
            json.dumps(
                {
                    "verified_contexts": list(results),
                    **{k: results["scheduled_chat"][k] for k in keys},
                    "queried_at": results["scheduled_chat"]["queried_at"],
                    "notifications_sent": 0,
                },
                ensure_ascii=False,
            )
        )
    finally:
        database.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
