from __future__ import annotations

import json

from deerflow_extension_api.plugins import ModelTool, PluginToolResult
from pydantic import ValidationError

from ace_ext.core.errors import AceError
from ace_ext.reporting.review_queue import query_review_queue
from ace_ext.reporting.review_queue_details import QueueOptions


def review_queue_tool(service) -> ModelTool:
    async def invoke(payload, context):
        try:
            options = QueueOptions.model_validate(dict(payload))
            result = await query_review_queue(
                service, context.principal.user_id, context.thread_id or "", options
            )
            return PluginToolResult(
                content=json.dumps(result, ensure_ascii=False),
                artifact={"schema": "ace.review-queue.v1", **result},
            )
        except ValidationError:
            return PluginToolResult(
                content="查询参数无效：请使用合法筛选和分页参数；项目由当前对话确定。"
            )
        except AceError as exc:
            return PluginToolResult(content=f"查询失败：{exc}。失败不代表待审核数量为0。")

    return ModelTool(
        "project_review_queue",
        "查询当前项目此刻的审核数量和文章明细列表。普通项目对话、定时任务对话都可用，无需绑定画布节点。"
        "用户要求明细、标题、链接或列表时必须设置include_details=true查询，不要要求用户上传或粘贴已有项目数据。"
        "明细默认筛选pending，每页最多50条，返回标题、链接、来源、时间、审核状态等。"
        "用户要求全部时按next_offset继续分页直到has_more=false；不要把一页说成全部。"
        "只看预警时设置alerts_only=true；其他状态用review_status筛选，all表示全部状态。"
        "问题包含还有多少数据待审核、审核进度、预警待审核时优先调用此工具，不要读取历史对话推算数量。"
        "从实时文章数据库返回全部文章/全部待审核/预警文章/预警待审核四个数字、查询时间、数据更新时间和query_id。"
        "默认回答全部待审核，并补充预警待审核子集，两者不可混淆；不是冻结报告数仓。"
        "项目和用户由服务端确定，只读统计，不运行采集、模型、推送，也不能修改审核状态。",
        QueueOptions.model_json_schema(),
        invoke,
        response_format="content_and_artifact",
    )
