import { createStore } from "zustand/vanilla";
import type { Graph, Project, RunDetail } from "../lib/models";

interface State {
  project: Project | null;
  graph: Graph | null;
  dirty: boolean;
  selected: string | null;
  tab: "canvas" | "articles" | "runs";
  run: RunDetail | null;
  load(project: Project): void;
  saved(project: Project, submitted: Graph): void;
  edit(graph: Graph): void;
  select(id: string | null): void;
  setTab(tab: State["tab"]): void;
  setRun(run: RunDetail | null): void;
}
export function createWorkbenchStore() {
  return createStore<State>((set) => ({
    project: null,
    graph: null,
    dirty: false,
    selected: null,
    tab: "canvas",
    run: null,
    load: (project) => set({ project, graph: project.graph, dirty: false, selected: null }),
    saved: (project, submitted) => set((state) => ({
      project,
      ...(state.graph === submitted ? { graph: project.graph, dirty: false } : {}),
    })),
    edit: (graph) => set({ graph, dirty: true }),
    select: (selected) => set({ selected }),
    setTab: (tab) => set({ tab }),
    setRun: (run) => set({ run }),
  }));
}
export type WorkbenchStore = ReturnType<typeof createWorkbenchStore>;
