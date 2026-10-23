import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "zustand";
import {
  RefreshCw,
  Workflow,
  Maximize,
  Minimize,
} from "lucide-react";
import { createApi, type HostContext } from "../../lib/api";
import { createWorkbenchStore } from "../../stores/workbenchStore";
import type { Mode, NodeType, Project, Task } from "../../lib/models";
import EditorToolbar from "./EditorToolbar";
import WorkbenchFooter from "./WorkbenchFooter";
import { fitGroups } from "./graph";
import CanvasView from "./CanvasView";
import NodeInspector from "./NodeInspector";
import ArticleList from "./ArticleList";
import RunView from "./RunView";
import { useUnsavedGuard } from "./useUnsavedGuard";
import { startPolling } from "./polling";

export default function EditorApp({ host }: { host: HostContext }) {
  const [store] = useState(createWorkbenchStore);
  const state = useStore(store);
  useUnsavedGuard(store);
  const api = useMemo(() => createApi(host), [host]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [catalog, setCatalog] = useState<NodeType[]>([]);
  const [mode, setMode] = useState<Mode>("simulation");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [focusTask, setFocusTask] = useState<Task | null>(null);
  const embedded = window.location.pathname.startsWith("/workspace/projects/");
  const root = useRef<HTMLElement>(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    const changed = () => setExpanded(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", changed);
    return () => document.removeEventListener("fullscreenchange", changed);
  }, []);
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [loaded, types] = await Promise.all([api.projects(), api.catalog()]);
        const selected = new URLSearchParams(window.location.search).get("canvas");
        const initial = loaded.find(item => item.id === selected) ?? loaded[0];
        if (active) {
          setProjects(loaded);
          setCatalog(types);
          if (initial) store.getState().load(initial);
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "加载失败");
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [api, store]);
  const projectId = state.project?.id;
  const runId = state.run?.id;
  useEffect(() => {
    if (!projectId) return;
    let active = true;
    setFocusTask(null);
    void api.runs(projectId).then(async (runs) => {
      const latest = runs[0] ? await api.detail(projectId, runs[0].id) : null;
      if (active && !store.getState().run) store.getState().setRun(latest);
    }).catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [api, projectId, store]);
  useEffect(() => {
    if (!projectId || !runId || state.run?.status !== "running") return;
    let active = true;
    const stop = startPolling(() =>
      api
        .detail(projectId, runId)
        .then((run) => {
          if (active) store.getState().setRun(run);
        })
        .catch((reason: Error) => {
          if (active) setError(reason.message);
        }), 2000);
    return () => {
      active = false;
      stop();
    };
  }, [api, projectId, runId, state.run?.status, store]);
  const perform = useCallback(async (callback: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await callback();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作未完成");
    } finally {
      setBusy(false);
    }
  }, []);
  async function save() {
    const current = store.getState();
    if (!current.project || !current.graph) return;
    const saved = await api.save(current.project, fitGroups(current.graph));
    store.getState().saved(saved, current.graph);
    setProjects((items) => items.map((item) => (item.id === saved.id ? saved : item)));
    setNotice(`已保存画布版本 ${saved.revision}`);
  }
  async function run(start?: string) {
    if (!projectId) return;
    if (store.getState().dirty) await save();
    if (store.getState().dirty) throw new Error("保存期间又有修改，请保存后再运行。");
    const created = await api.run(projectId, mode, start, Boolean(start));
    store.getState().setRun(await api.detail(projectId, created.id));
    setNotice(start ? "节点任务已提交" : "工作流任务已提交，各节点将独立执行");
  }
  const selectedNode = state.graph?.nodes.find((node) => node.id === state.selected);
  if (loading)
    return (
      <div className="ace-app">
        <div className="empty-state" aria-busy="true">
          <Workflow size={32} />
          <h2>正在载入 ACE 工作台…</h2>
        </div>
      </div>
    );
  return (
    <main className="ace-app" ref={root}>
      <header className="workbench-header">
        <div className="brand-mark">
          <Workflow size={22} />
        </div>
        <div className="brand-title">
          <small>ACE / 工作流控制台</small>
          <h1>{state.project?.name ?? "ACE 工作台"}</h1>
        </div>
        {!embedded && <div className="project-selector">
          <select
            aria-label="选择画布"
            value={projectId ?? ""}
            disabled={busy || state.dirty}
            onChange={(event) =>
              void perform(async () => {
                const project = await api.project(event.target.value);
                store.getState().load(project);
                store.getState().setRun(null);
              })
            }
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </div>}
        <button
          aria-label={expanded ? "退出全屏" : "全屏工作台"}
          onClick={() =>
            void perform(async () => {
              if (expanded) await document.exitFullscreen();
              else await root.current?.requestFullscreen();
            })
          }
        >
          {expanded ? <Minimize size={16} /> : <Maximize size={16} />}
          {expanded ? "退出全屏" : "全屏"}
        </button>
      </header>
      <EditorToolbar tab={state.tab} onTab={state.setTab} dirty={state.dirty}
        revision={state.project?.revision} busy={busy} canRun={Boolean(projectId)}
        mode={mode} onMode={setMode} onSave={() => void perform(save)}
        onRun={() => void perform(() => run())} />
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button
            onClick={() =>
              void perform(async () => {
                if (state.dirty && !window.confirm("重新加载会放弃尚未保存的画布修改，是否继续？"))
                  return;
                if (projectId) state.load(await api.project(projectId));
              })
            }
          >
            <RefreshCw size={13} />
            重新加载
          </button>
        </div>
      )}
      {notice && (
        <div role="status" className="notice-banner">
          {notice}
        </div>
      )}
      {state.tab === "canvas" && state.graph && (
        <div className={`canvas-with-inspector ${selectedNode ? "inspecting" : ""}`}>
          <CanvasView
            key={projectId}
            graph={state.graph}
            catalog={catalog}
            run={state.run}
            onChange={state.edit}
            onSelect={state.select}
          />
          {selectedNode && (
            <NodeInspector
              key={selectedNode.id}
              node={selectedNode}
              graph={state.graph}
              task={state.run?.tasks.find((task) => task.node_id === selectedNode.id)}
              onChange={state.edit}
              onClose={() => state.select(null)}
              onRun={(id) => void perform(() => run(id))}
              onTask={(task) => {
                setFocusTask(task);
                state.setTab("runs");
              }}
            />
          )}
        </div>
      )}
      {state.tab === "articles" && projectId && (
        <ArticleList key={projectId} api={api} projectId={projectId} />
      )}
      {state.tab === "runs" && projectId && (
        <RunView
          key={`${projectId}-${focusTask?.id ?? ""}`}
          api={api}
          host={host}
          projectId={projectId}
          run={state.run}
          focusTask={focusTask}
          onRun={state.setRun}
        />
      )}
      <WorkbenchFooter graph={state.graph} run={state.run} mode={state.run?.mode ?? mode} />
    </main>
  );
}
