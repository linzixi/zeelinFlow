from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeType:
    type_id: str
    title: str
    executor: str
    operation: str
    category: str
    owner: str = "ace"
    palette_order: int = 100
    ownership: str = "system"
    origin: str = "migration"


class NodeTypeRegistry:
    def __init__(self):
        self._types: dict[str, NodeType] = {}

    def register(self, node_type: NodeType) -> None:
        if node_type.type_id in self._types:
            raise ValueError("节点类型重复注册")
        self._types[node_type.type_id] = node_type

    def palette(self) -> list[NodeType]:
        return sorted(self._types.values(), key=lambda value: value.palette_order)


def build_registry() -> NodeTypeRegistry:
    registry = NodeTypeRegistry()
    for order, (type_id, title, executor, operation, category) in enumerate(
        [
            ("opinion_n01", "监测时间", "data", "window", "触发与数据"),
            ("es_query", "ES 数据采集", "data", "ingest", "触发与数据"),
            ("opinion_fetch", "爱品数据采集", "data", "ingest", "触发与数据"),
            ("record_select", "标准化与筛选", "data", "normalize", "触发与数据"),
            ("record_content", "正文补齐", "data", "content", "触发与数据"),
            ("record_deduplicate", "事件去重", "data", "deduplicate", "触发与数据"),
            ("etl_article_interactions", "互动数据刷新", "data", "metrics", "触发与数据"),
            ("project_history_compare", "历史比对", "data", "history", "触发与数据"),
            ("project_state_persist", "结果入库", "data", "persist", "触发与数据"),
            ("llm_record_analysis", "舆情预警判断", "agent", "judge", "Agent 与报告"),
            ("llm_classification", "文章标签分类", "agent", "judge", "Agent 与报告"),
            ("code_agent", "代码处理 Agent", "agent", "judge", "Agent 与报告"),
            ("document_template", "报告生成", "agent", "report", "Agent 与报告"),
            ("warehouse_report", "智能问数报告", "agent", "report", "Agent 与报告"),
            ("dingtalk_robot", "预警推送", "delivery", "delivery", "结果应用"),
        ]
    ):
        registry.register(
            NodeType(type_id, title, executor, operation, category, palette_order=order)
        )
    return registry
