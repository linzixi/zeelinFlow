import type { CanvasNode, Graph, NodeType } from "../../lib/models";

export function fitGroups(graph: Graph): Graph {
  return {
    ...graph,
    groups: graph.groups.map((group) => {
      const nodes = graph.nodes.filter((node) => group.nodeIds.includes(node.id));
      if (!nodes.length) return { ...group, nodeIds: [] };
      const left = Math.min(...nodes.map((node) => node.x)) - 24;
      const top = Math.min(...nodes.map((node) => node.y)) - 56;
      return {
        ...group,
        nodeIds: nodes.map((node) => node.id),
        bounds: {
          x: left,
          y: top,
          width: Math.max(...nodes.map((node) => node.x)) + 272 - left,
          height: Math.max(...nodes.map((node) => node.y)) + 136 - top,
        },
      };
    }),
  };
}
export function removeNode(graph: Graph, id: string): Graph {
  return fitGroups({
    ...graph,
    nodes: graph.nodes.filter((node) => node.id !== id),
    edges: graph.edges.filter((edge) => edge.source !== id && edge.target !== id),
  });
}
export function canConnect(graph: Graph, source: string, target: string): boolean {
  if (
    source === target ||
    graph.edges.some((edge) => edge.source === source && edge.target === target)
  )
    return false;
  const seen = new Set<string>();
  const pending = [target];
  while (pending.length) {
    const id = pending.pop()!;
    if (id === source) return false;
    if (seen.has(id)) continue;
    seen.add(id);
    pending.push(
      ...graph.edges
        .filter((edge) => edge.source === id && !edge.executionDisabled)
        .map((edge) => edge.target),
    );
  }
  return true;
}
export function newNode(type: NodeType, index: number): CanvasNode {
  return {
    id: `node_${crypto.randomUUID().slice(0, 8)}`,
    type: type.type_id,
    title: type.title,
    x: 360 + index * 24,
    y: 820,
    executor: type.executor,
    operation: type.operation,
    instructions: "",
    skill: "",
    agentRef: "lead_agent",
    config: {},
    enabled: true,
    inputContract: "ArticleBatch.v1",
    outputContract: "ArticleBatch.v1",
    trigger: {
      kind: "event",
      enabled: false,
      cron: "",
      runAtTimes: [],
      timezone: "Asia/Shanghai",
      lookbackMinutes: 150,
    },
  };
}
