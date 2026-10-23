from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from deerflow_extension_api.agent_runs import AgentRun

from ace_ext.core.config import Settings
from ace_ext.core.contracts import Envelope, Window
from ace_ext.core.errors import Unavailable
from ace_ext.execution.agent_worker import AgentWorker
from ace_ext.execution.native_runs import NativeRuns
from ace_ext.persistence.tasks import TaskRepository


class HostRuns:
    def __init__(self):
        self.starts = 0
        self.message = None

    async def create_thread(self, **kwargs):
        return kwargs["thread_id"]

    async def start(self, **kwargs):
        self.starts += 1
        self.message = kwargs["input"]["messages"][0]
        return AgentRun(kwargs["thread_id"], "native-run", "running")

    async def wait(self, **kwargs):
        return AgentRun(kwargs["thread_id"], kwargs["run_id"], "success")

    async def get_state(self, **kwargs):
        return {
            "values": {
                "messages": [
                    self.message,
                    {
                        "role": "assistant",
                        "content": Envelope(summary="真实适配器契约验证").model_dump_json(),
                    },
                ]
            }
        }


def test_known_agent_after_process_lease_loss_is_observed_not_restarted(
    database, scope, saved_project
):
    repo = TaskRepository(database, tenant_id=scope.tenant_id)
    now = datetime.now(UTC)
    run = repo.launch(
        scope,
        saved_project["id"],
        mode="live",
        origin="manual",
        key="native",
        start="judge",
        single=True,
        window=Window(start=now - timedelta(minutes=150), end=now),
    )
    task = repo.claim("agent", lease_seconds=10)
    host = HostRuns()
    worker = AgentWorker(repo, 30)
    worker.bind(scope.owner_id, host)
    asyncio.run(worker.execute(task, repo.input(task)))
    assert host.starts == 1
    repo.recover_expired(now=task["lease_until"] + 1)
    recovered = repo.claim("agent", lease_seconds=90, now=task["lease_until"] + 2)
    assert recovered["attempt"] == 1
    # 新 Worker 使用经重新验证的能力；只观察已有 run，不提交第二次模型执行。
    restarted = AgentWorker(repo, 30)
    restarted.bind(scope.owner_id, host)
    result = asyncio.run(restarted.execute(recovered, repo.input(recovered)))
    repo.complete(recovered["id"], recovered["lease_token"], result)
    assert host.starts == 1
    assert repo.detail(scope, saved_project["id"], run["id"])["status"] == "succeeded"


def test_agent_rejects_other_turn_or_pending_interrupt():
    state = {
        "values": {
            "messages": [
                {"role": "user", "id": "another-turn"},
                {"role": "assistant", "content": Envelope().model_dump_json()},
            ]
        }
    }
    with pytest.raises(Unavailable, match="输入已变化"):
        AgentWorker._parse_output(state, expected_input="expected")
    with pytest.raises(Unavailable, match="等待人工"):
        AgentWorker._parse_output({"interrupts": [{"id": "approval"}]})


def test_pat_transport_uses_native_auth_and_namespaced_idempotency():
    seen = []

    def respond(request):
        assert request.headers["Authorization"] == "Bearer dfp_test"
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/runs"):
            assert request.headers["Idempotency-Key"] == "qingbo.ace:task:1"
            assert json.loads(request.content)["input"]["messages"][0]["id"] == "input-1"
            return httpx.Response(
                200, json={"thread_id": "thread", "run_id": "run", "status": "success"}
            )
        return httpx.Response(200, json={"thread_id": "thread"})

    async def execute():
        client = NativeRuns(
            Settings(
                database_url="sqlite://",
                redis_conn_string="redis://localhost",
                ace_df_agent_api_token="dfp_test",
                ace_df_agent_owner_id="owner",
            ),
            transport=httpx.MockTransport(respond),
        )
        await client.create_thread(thread_id="thread", assistant_id="lead_agent")
        result = await client.start(
            thread_id="thread", input={"messages": [{"id": "input-1"}]}, idempotency_key="task:1"
        )
        await client.close()
        return result

    assert asyncio.run(execute()).run_id == "run"
    assert seen == [("POST", "/api/threads"), ("POST", "/api/threads/thread/runs")]
