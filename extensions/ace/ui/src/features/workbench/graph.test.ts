import assert from "node:assert/strict";
import test from "node:test";
import { canConnect, fitGroups, newNode, removeNode } from "./graph";
import type { Graph, NodeType } from "../../lib/models";

const entry: NodeType = {
  type_id: "es_query",
  title: "取数",
  executor: "data",
  operation: "ingest",
  category: "数据",
};
const a = { ...newNode(entry, 0), id: "a", x: 100, y: 100 };
const b = { ...newNode(entry, 1), id: "b", x: 500, y: 300 };
const graph: Graph = {
  schemaVersion: 1,
  nodes: [a, b],
  edges: [
    {
      id: "ab",
      source: "a",
      target: "b",
      label: "",
      conditionKey: "",
      conditionValue: "",
      executionDisabled: false,
    },
  ],
  groups: [
    {
      id: "g",
      name: "数据",
      color: "#abc",
      nodeIds: ["a", "b"],
      bounds: { x: 0, y: 0, width: 1, height: 1 },
    },
  ],
};
test("prevent cycles and duplicate connections", () => {
  assert.equal(canConnect(graph, "b", "a"), false);
  assert.equal(canConnect(graph, "a", "b"), false);
});
test("group boundary follows moved members and deletion removes dangling references", () => {
  const fitted = fitGroups(graph);
  assert.ok(fitted.groups[0].bounds.width >= 648);
  const removed = removeNode(fitted, "b");
  assert.deepEqual(removed.groups[0].nodeIds, ["a"]);
  assert.equal(removed.edges.length, 0);
});
