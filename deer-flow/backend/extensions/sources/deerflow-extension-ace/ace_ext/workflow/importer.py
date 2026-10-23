from __future__ import annotations

from copy import deepcopy

from ace_ext.workflow.catalog import build_registry
from ace_ext.workflow.models import Bounds, Edge, Graph, Group, Node, Trigger

CMC_TIMES = ["08:30", "10:30", "12:30", "14:30", "16:30", "18:30"]


def import_cmc(source: dict) -> Graph:
    """保留源节点类型与业务内容；迁移执行方式、布局与用户指定调度。"""
    catalog = {entry.type_id: entry for entry in build_registry().palette()}
    nodes = []
    for raw in source["graph"]["nodes"]:
        item = deepcopy(raw)
        spec = catalog[item["type"]]
        item.update(executor=spec.executor, operation=spec.operation)
        config = item["config"]
        for key in (
            "programPath",
            "config_path",
            "webhook_url",
            "signing_secret",
            "validationSuite",
        ):
            config.pop(key, None)
        key = item["id"]
        if key in ("clock", "time"):
            item.update(executor="data", operation="window")
            item["instructions"] = "按入库时间回看150分钟，固定北京时间08:30至18:30每两小时启动。"
        elif key == "common_prepare":
            item.update(executor="data", operation="normalize")
        elif key.endswith("processing"):
            item["config"]["branch"] = key.split("_")[0]
        elif key.endswith("document"):
            item["config"].update(branch=key.split("_")[0], report_period="实时预警")
        elif item["type"] == "es_query":
            item["config"]["source_key"] = key
        if key == "clock":
            item["title"] = "定时监测 · 每日六个时点"
            item["trigger"] = Trigger(kind="cron", enabled=False, runAtTimes=CMC_TIMES)
        nodes.append(Node.model_validate(item))
    graph = Graph.model_construct(
        schemaVersion=1,
        nodes=nodes,
        edges=[Edge.model_validate(edge) for edge in source["graph"]["edges"]],
        groups=[],
    )
    _layout(graph)
    return Graph.model_validate(graph.model_dump(mode="json"))


def _layout(graph: Graph) -> None:
    positions = {
        "clock": (40, 100),
        "time": (40, 270),
        "special_search_1": (360, 100),
        "special_search_2": (360, 270),
        "special_search_3": (360, 440),
        "fund_search": (360, 610),
        "fund_clean": (680, 610),
        "common_content": (1000, 270),
        "common_prepare": (1320, 270),
        "special_processing": (1700, 100),
        "special_document": (2020, 100),
        "special_push": (2340, 100),
        "fund_processing": (1700, 610),
        "fund_document": (2020, 610),
        "fund_push": (2340, 610),
    }
    for node in graph.nodes:
        node.x, node.y = positions[node.id]
    groups = [
        ("shared", "数据采集与准备", "#60a5fa", list(positions)[:9]),
        ("special", "专项舆情研判", "#34d399", list(positions)[9:12]),
        ("fund", "基金招募研判", "#fbbf24", list(positions)[12:]),
    ]
    for key, name, color, members in groups:
        xs = [positions[member][0] for member in members]
        ys = [positions[member][1] for member in members]
        graph.groups.append(
            Group(
                id=key,
                name=name,
                color=color,
                nodeIds=members,
                bounds=Bounds(
                    x=min(xs) - 24,
                    y=min(ys) - 56,
                    width=max(xs) - min(xs) + 296,
                    height=max(ys) - min(ys) + 192,
                ),
            )
        )
