"""ACE 的独立数据、任务与可视化编排扩展。"""

from pathlib import Path

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import BackendAction, BrowserAssets, PluginContribution

from ace_ext.api.actions import Actions
from ace_ext.core.config import Settings
from ace_ext.execution.service import ExecutionService
from ace_ext.governance.api import build_router
from ace_ext.reporting.review_queue_tool import review_queue_tool
from ace_ext.reporting.tools import query_tool


@extension(api="0.2.8", name="ace")
def install(registry, config):
    env_file = config.get("env_file")
    if not env_file or not Path(env_file).is_absolute():
        raise ValueError("ACE 扩展需要部署方指定绝对路径的本地环境文件")
    service = ExecutionService(Settings(_env_file=env_file))
    actions = Actions(service, Path(__file__).parent / "samples" / "cmc-realtime.json")
    if not registry.plugin(
        PluginContribution(
            namespace="qingbo.ace",
            title="ACE 工作台",
            description="画布编排、预警文章与任务回溯",
            enabled=True,
            frontend=BrowserAssets("ace.v1", Path(__file__).parent),
            backend=tuple(BackendAction(name, actions.handler(name)) for name in actions.schemas),
            tools=(query_tool(service), review_queue_tool(service)),
        )
    ):
        raise RuntimeError("当前 DeerFlow 不支持 ACE 全栈扩展协议")
    registry.service(service)
    registry.routers([build_router(service)])
