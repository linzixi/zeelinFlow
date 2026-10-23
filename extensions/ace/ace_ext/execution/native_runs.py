from __future__ import annotations

import asyncio
from collections.abc import Mapping

import httpx
from deerflow_extension_api.agent_runs import AgentRun, AgentRunError

from ace_ext.core.config import Settings


class NativeRuns:
    """通过原生 PAT 路由执行节点；重启后仍逐次校验令牌、作用域和所有权。

    凭据由部署方保存在环境文件中，仅用于其绑定用户。不是序列化的 AgentRuns
    句柄，也不从数据库中的用户 ID 构造宿主权限。
    """

    def __init__(self, settings: Settings, *, transport=None):
        self.owner_id = settings.ace_df_agent_owner_id
        self.client = httpx.AsyncClient(
            base_url=settings.ace_df_gateway_url.rstrip("/"),
            timeout=45,
            trust_env=False,
            transport=transport,
            headers={
                "Authorization": f"Bearer {settings.ace_df_agent_api_token.get_secret_value()}"
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, path: str, **kwargs):
        response = await self.client.request(method, path, **kwargs)
        if response.is_error:
            raise AgentRunError(response.status_code, "DeerFlow 拒绝节点请求，请检查授权和运行状态")
        return response.json() if response.content else {}

    async def create_thread(
        self, *, assistant_id: str, thread_id: str, metadata: Mapping | None = None
    ) -> str:
        try:
            await self._request(
                "POST",
                "/api/threads",
                json={
                    "assistant_id": assistant_id,
                    "thread_id": thread_id,
                    "metadata": dict(metadata or {}),
                },
            )
        except AgentRunError as exc:
            if exc.status_code != 409:
                raise
            existing = await self._request("GET", f"/api/threads/{thread_id}")
            if any(
                existing.get("metadata", {}).get(key) != value
                for key, value in (metadata or {}).items()
            ):
                raise AgentRunError(409, "节点会话归属不一致") from exc
        return thread_id

    async def start(
        self,
        *,
        thread_id: str,
        input: Mapping,
        idempotency_key: str,
        context: Mapping | None = None,
    ) -> AgentRun:
        result = await self._request(
            "POST",
            f"/api/threads/{thread_id}/runs",
            headers={"Idempotency-Key": f"qingbo.ace:{idempotency_key}"},
            json={"input": dict(input)},
        )
        return self._run(result)

    async def get(self, *, thread_id: str, run_id: str) -> AgentRun:
        return self._run(await self._request("GET", f"/api/threads/{thread_id}/runs/{run_id}"))

    async def get_state(self, *, thread_id: str) -> dict:
        return await self._request("GET", f"/api/threads/{thread_id}/state")

    async def wait(self, *, thread_id: str, run_id: str, timeout: float = 30) -> AgentRun:
        end = asyncio.get_running_loop().time() + timeout
        while True:
            run = await self.get(thread_id=thread_id, run_id=run_id)
            if run.status not in ("pending", "running", "queued"):
                return run
            if asyncio.get_running_loop().time() >= end:
                raise TimeoutError
            await asyncio.sleep(1)

    async def cancel(self, *, thread_id: str, run_id: str) -> None:
        await self._request(
            "POST", f"/api/threads/{thread_id}/runs/{run_id}/cancel", params={"action": "interrupt"}
        )

    @staticmethod
    def _run(result: dict) -> AgentRun:
        return AgentRun(
            thread_id=result["thread_id"],
            run_id=result["run_id"],
            status=result["status"],
            assistant_id=result.get("assistant_id"),
        )
