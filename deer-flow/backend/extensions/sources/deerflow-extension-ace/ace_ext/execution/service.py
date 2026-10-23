from __future__ import annotations

import asyncio
import logging

from ace_ext.core.config import Settings
from ace_ext.core.errors import AceError, DeferUntil, LeaseLost
from ace_ext.execution.agent_worker import AgentWorker
from ace_ext.execution.data_worker import DataWorker
from ace_ext.execution.native_runs import NativeRuns
from ace_ext.execution.queue import QueueNotifications
from ace_ext.governance.workspaces import WorkspaceRepository
from ace_ext.persistence.articles import ArticleRepository
from ace_ext.persistence.database import Database
from ace_ext.persistence.migrations import migrate
from ace_ext.persistence.schedules import ScheduleRepository
from ace_ext.persistence.tasks import TaskRepository

logger = logging.getLogger(__name__)


class ExecutionService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = Database(settings.database_url.get_secret_value(), echo=settings.db_echo)
        self.tasks = TaskRepository(self.database, tenant_id=settings.ace_df_tenant)
        self.articles = ArticleRepository(self.database)
        self.governance = WorkspaceRepository(self.database, settings.ace_df_tenant)
        self.data = DataWorker(self.articles, settings)
        self.agents = AgentWorker(self.tasks, settings.ace_df_agent_timeout_seconds)
        self.native = (
            NativeRuns(settings) if settings.ace_df_agent_api_token.get_secret_value() else None
        )
        if self.native:
            self.agents.bind(self.native.owner_id, self.native)
        self.queue = QueueNotifications(self.database, settings)
        self.schedules = ScheduleRepository(self.database, settings.ace_df_tenant)
        self.workers: list[asyncio.Task] = []
        self.stopping = asyncio.Event()
        self.native_session_factory = None

    async def start(self, _deps=None) -> None:
        self.native_session_factory = getattr(_deps, "session_factory", None)
        if self.settings.db_auto_create:
            await asyncio.to_thread(migrate, self.database)
        await asyncio.to_thread(self.governance.bootstrap, self.settings.ace_df_agent_owner_id)
        self.stopping.clear()
        for executor, count in [
            ("data", self.settings.ace_df_data_workers),
            ("agent", self.settings.ace_df_agent_workers),
            ("delivery", 1),
        ]:
            self.workers.extend(asyncio.create_task(self._worker(executor)) for _ in range(count))
        self.workers.append(asyncio.create_task(self._maintenance()))

    async def stop(self) -> None:
        self.stopping.set()
        self.agents.stopping.set()
        # 等待已提交的数据库/连接器线程完成，避免关闭连接池后线程继续写入。
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        self.agents.handles.clear()
        if self.native:
            await self.native.close()
        self.queue.close()
        self.database.close()

    async def _maintenance(self) -> None:
        while not self.stopping.is_set():
            try:
                await asyncio.to_thread(self.queue.publish)
                await asyncio.to_thread(self.tasks.recover_expired)
                await asyncio.to_thread(self.schedules.dispatch_due)
            except Exception as exc:
                logger.error("ace_maintenance_failed kind=%s", type(exc).__name__)
            await asyncio.sleep(self.settings.ace_df_poll_seconds)

    async def _worker(self, executor: str) -> None:
        while not self.stopping.is_set():
            try:
                await asyncio.to_thread(self.queue.consume, executor)
                task = await asyncio.to_thread(
                    self.tasks.claim, executor, lease_seconds=self.settings.ace_df_lease_seconds
                )
                if task:
                    await self._execute(task)
                    continue
            except Exception as exc:
                logger.error("ace_worker_failed executor=%s kind=%s", executor, type(exc).__name__)
            await asyncio.sleep(self.settings.ace_df_poll_seconds)

    async def _execute(self, task: dict) -> None:
        heartbeat = asyncio.create_task(self._heartbeat(task))
        try:
            payload = await asyncio.to_thread(self.tasks.input, task)
            output = (
                await self.agents.execute(task, payload)
                if task["executor"] == "agent"
                else await asyncio.to_thread(self.data.execute, task, payload)
            )
            await asyncio.to_thread(self.tasks.complete, task["id"], task["lease_token"], output)
        except DeferUntil as exc:
            await asyncio.to_thread(
                self.tasks.defer, task["id"], task["lease_token"], at=exc.at, reason=str(exc)
            )
        except LeaseLost:
            logger.info("ace_result_fenced task=%s", task["id"])
        except Exception as exc:
            message = (
                str(exc) if isinstance(exc, AceError) else "节点执行失败，请检查任务配置和连接器"
            )
            try:
                await asyncio.to_thread(
                    self.tasks.fail,
                    task["id"],
                    task["lease_token"],
                    message,
                    retryable=not isinstance(exc, AceError),
                )
            except LeaseLost:
                logger.info("ace_failure_fenced task=%s", task["id"])
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self, task: dict) -> None:
        while True:
            await asyncio.sleep(self.settings.ace_df_lease_seconds / 3)
            await asyncio.to_thread(
                self.tasks.heartbeat,
                task["id"],
                task["lease_token"],
                lease_seconds=self.settings.ace_df_lease_seconds,
            )
