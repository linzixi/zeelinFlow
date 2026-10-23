from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

if TYPE_CHECKING:
    from ace_ext.workflow.models import Graph


def validate_graph(graph: Graph) -> None:
    nodes = {node.id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes):
        raise ValueError("节点编号不能重复")
    if len({edge.id for edge in graph.edges}) != len(graph.edges):
        raise ValueError("连线编号不能重复")
    adjacency: dict[str, list[str]] = {key: [] for key in nodes}
    degree = dict.fromkeys(nodes, 0)
    for edge in graph.edges:
        if edge.source not in nodes or edge.target not in nodes:
            raise ValueError("连线引用了不存在的节点")
        if not edge.executionDisabled:
            adjacency[edge.source].append(edge.target)
            degree[edge.target] += 1
    ready = [key for key, count in degree.items() if not count]
    visited = 0
    while ready:
        key = ready.pop()
        visited += 1
        for target in adjacency[key]:
            degree[target] -= 1
            if not degree[target]:
                ready.append(target)
    if visited != len(nodes):
        raise ValueError("执行连线存在循环，请用定时触发表示周期任务")
    for node in graph.nodes:
        validate_trigger(node.trigger)
    for group in graph.groups:
        if any(key not in nodes for key in group.nodeIds):
            raise ValueError("分组包含不存在的节点")
        for key in group.nodeIds:
            node, bounds = nodes[key], group.bounds
            if (
                node.x < bounds.x
                or node.y < bounds.y
                or node.x + 248 > bounds.x + bounds.width
                or node.y + 112 > bounds.y + bounds.height
            ):
                raise ValueError("功能分组边界必须实际包住成员节点")


def validate_trigger(trigger) -> None:
    try:
        ZoneInfo(trigger.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("无效的触发器时区") from exc
    if trigger.kind != "cron":
        return
    if trigger.runAtTimes:
        for value in trigger.runAtTimes:
            parts = value.split(":")
            if (
                len(parts) != 2
                or any(not part.isdigit() for part in parts)
                or len(value) != 5
                or int(parts[0]) > 23
                or int(parts[1]) > 59
            ):
                raise ValueError("固定时间须为 HH:MM")
    elif not croniter.is_valid(trigger.cron) or len(trigger.cron.split()) != 5:
        raise ValueError("请输入有效的五段 cron 或每日固定时间")


def reachable(graph: Graph, start: str | None, single: bool = False) -> set[str]:
    if start is None:
        return {node.id for node in graph.nodes if node.enabled}
    if start not in {node.id for node in graph.nodes if node.enabled}:
        raise ValueError("请选择已启用的节点")
    selected, queue = {start}, [start]
    event_nodes = {node.id for node in graph.nodes if node.enabled and node.trigger.kind == "event"}
    while queue and not single:
        key = queue.pop()
        for edge in graph.edges:
            if (
                edge.source == key
                and not edge.executionDisabled
                and edge.target not in selected
                and edge.target in event_nodes
            ):
                selected.add(edge.target)
                queue.append(edge.target)
    return selected & {node.id for node in graph.nodes if node.enabled}
