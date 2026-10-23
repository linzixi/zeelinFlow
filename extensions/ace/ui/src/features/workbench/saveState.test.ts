import assert from "node:assert/strict";
import test from "node:test";
import { createWorkbenchStore } from "../../stores/workbenchStore";
import type { Project } from "../../lib/models";

const project: Project = { id: "canvas", name: "画布", revision: 1, description: "", source: {}, updated_at: 0, graph: {
  schemaVersion: 1, nodes: [], edges: [], groups: [],
} };

test("saving does not discard edits made while the request is in flight", () => {
  const store = createWorkbenchStore();
  store.getState().load(project);
  const submitted = store.getState().graph!;
  const newer = { ...submitted, groups: [] };
  store.getState().edit(newer);
  store.getState().saved({ ...project, revision: 2 }, submitted);
  assert.equal(store.getState().graph, newer);
  assert.equal(store.getState().dirty, true);
  assert.equal(store.getState().project?.revision, 2);
});

test("saving the current graph clears dirty without losing selection", () => {
  const store = createWorkbenchStore();
  store.getState().load(project);
  store.getState().select("node");
  store.getState().saved({ ...project, revision: 2 }, store.getState().graph!);
  assert.equal(store.getState().dirty, false);
  assert.equal(store.getState().selected, "node");
});
