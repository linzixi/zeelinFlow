from __future__ import annotations

from ace_ext.workflow.models import Bounds, Edge, Graph, Group, Node, Trigger


def with_report(graph: Graph) -> Graph:
    """原十六节点和分支保持不变；新报告等待分析与预览完成后读取本地数仓。"""
    if any(node.id == "sgm_warehouse_report" for node in graph.nodes):
        return graph
    node = Node(
        id="sgm_warehouse_report",
        type="warehouse_report",
        title="上汽通用 · 智能问数报告",
        executor="agent",
        operation="report",
        x=990,
        y=840,
        trigger=Trigger(lookbackMinutes=5),
        instructions="分析本时间段上汽通用的舆情。解释主要车型问题、负面原文、平台来源与情感分布，"
        "区分已成功转写和仅基于标题正文的判断。以执行摘要、观点分类、时间线、话题演变、"
        "来源分布、行动建议组织报告。明确短窗口不能作七天预测，禁止推送消息。",
    )
    return graph.model_copy(
        update={
            "nodes": [*graph.nodes, node],
            "edges": [
                *graph.edges,
                Edge(id="sgm-report-sentiment", source=graph.nodes[4].id, target=node.id),
                Edge(id="sgm-report-receipt", source=graph.nodes[13].id, target=node.id),
            ],
            "groups": [
                *graph.groups,
                Group(
                    id="sgm-report-group",
                    name="05 数仓问数与报告",
                    nodeIds=[node.id],
                    bounds=Bounds(x=966, y=784, width=296, height=192),
                ),
            ],
        }
    )
