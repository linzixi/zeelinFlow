import { useEffect, useState } from "react";
import { Clock3, RotateCcw, ExternalLink, X, StopCircle } from "lucide-react";
import type { Api, HostContext } from "../../lib/api";
import type { Run, RunDetail, Snapshot, Task } from "../../lib/models";
import { formatTime, LANE, STATUS } from "../../lib/models";
import SnapshotView from "./SnapshotView";
import { startPolling } from "./polling";

interface Props {
  api: Api;
  host: HostContext;
  projectId: string;
  run: RunDetail | null;
  focusTask: Task | null;
  onRun(run: RunDetail): void;
}
export default function RunView({ api, host, projectId, run, focusTask, onRun }: Props) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(focusTask?.id ?? null);
  const selected = run?.tasks.find((task) => task.id === selectedId) ?? null;
  const setSelected = (task: Task | null) => setSelectedId(task?.id ?? null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const load = () =>
      api
        .runs(projectId)
        .then((result) => {
          if (active) setRuns(result);
        })
        .catch((reason: Error) => {
          if (active) setError(reason.message);
        });
    const stop = startPolling(load, 15000);
    return () => {
      active = false;
      stop();
    };
  }, [api, projectId]);
  async function action(callback: () => Promise<unknown>, refresh = false) {
    try {
      await callback();
      setError("");
      if (refresh && run) onRun(await api.detail(projectId, run.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    }
  }
  function duration(task: Task) {
    return task.started_at
      ? `${Math.max(0, (task.finished_at ?? Date.now() / 1000) - task.started_at).toFixed(1)} 秒`
      : "—";
  }
  return (
    <div className="runs-view">
      <aside className="run-history">
        <div className="section-title">
          <Clock3 size={16} />
          <h2>运行历史</h2>
        </div>
        {runs.length === 0 && <p className="muted">暂无运行记录</p>}
        {runs.map((item) => (
          <button
            key={item.id}
            className={`run-item ${run?.id === item.id ? "active" : ""}`}
            onClick={() =>
              void action(async () => {
                onRun(await api.detail(projectId, item.id));
                setSelected(null);
              })
            }
          >
            <strong>{formatTime(item.created_at)}</strong>
            <span>
              <i className={`status-dot ${item.status}`} />
              {STATUS[item.status] ?? item.status}
            </span>
            <small>
              {item.origin === "replay"
                ? "快照回溯"
                : item.origin === "scheduled"
                  ? "定时触发"
                  : "手动触发"}{" "}
              · 画布 v{item.graph_revision}
            </small>
          </button>
        ))}
      </aside>
      <section className="run-details">
        {error && (
          <p role="alert" className="error-banner">
            {error}
          </p>
        )}
        {!run ? (
          <div className="empty-state">
            <Clock3 size={32} />
            <h3>选择一条运行记录</h3>
            <p>每个节点的状态、时间、输入快照和结果都保留在这里。</p>
          </div>
        ) : (
          <>
            <div className="view-heading">
              <div>
                <small>
                  {run.mode === "simulation" ? "模拟运行" : "正式运行"} · 画布 v{run.graph_revision}
                </small>
                <h2>节点运行详情</h2>
                <p>
                  {formatTime(run.created_at)} · {STATUS[run.status]}
                </p>
              </div>
              {run.status === "running" && (
                <button onClick={() => void action(() => api.cancel(projectId, run.id), true)}>
                  <StopCircle size={15} />
                  取消运行
                </button>
              )}
            </div>
            <div className="run-progress">
              <span>
                {run.tasks.filter((task) => task.status === "succeeded").length} /{" "}
                {run.tasks.length} 节点完成
              </span>
              <span>数据、研判与结果分别保留，可按节点回溯。</span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>节点</th>
                    <th>执行方式</th>
                    <th>状态</th>
                    <th>耗时</th>
                    <th>尝试</th>
                    <th>查看</th>
                  </tr>
                </thead>
                <tbody>
                  {run.tasks.map((task) => (
                    <tr key={task.id} className={selected?.id === task.id ? "selected-row" : ""}>
                      <td>
                        <strong>{task.node.title}</strong>
                        {task.error && <p className="field-error">{task.error}</p>}
                      </td>
                      <td>{LANE[task.executor]}</td>
                      <td>
                        <span className={`state-label ${task.status}`}>
                          <i className={`status-dot ${task.status}`} />
                          {STATUS[task.status]}
                        </span>
                      </td>
                      <td>{duration(task)}</td>
                      <td>{task.attempt}</td>
                      <td>
                        <button
                          className="text-button"
                          onClick={() => {
                            setSelected(task);
                            setSnapshot(null);
                          }}
                        >
                          数据与上下文
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {selected && (
              <section className="task-context">
                <div className="section-title">
                  <h3>{selected.node.title}</h3>
                  <button
                    className="icon-button"
                    aria-label="收起任务详情"
                    onClick={() => setSelected(null)}
                  >
                    <X size={15} />
                  </button>
                </div>
                <div className="task-context-actions">
                  {selected.input_snapshot_id && (
                    <button
                      onClick={() =>
                        void action(async () =>
                          setSnapshot(await api.snapshot(projectId, selected.input_snapshot_id!)),
                        )
                      }
                    >
                      输入快照
                    </button>
                  )}
                  {selected.output_snapshot_id && (
                    <button
                      onClick={() =>
                        void action(async () =>
                          setSnapshot(await api.snapshot(projectId, selected.output_snapshot_id!)),
                        )
                      }
                    >
                      输出与产物
                    </button>
                  )}
                  {["failed", "waiting_review"].includes(selected.status) && (
                    <button
                      onClick={() => void action(() => api.retry(projectId, selected.id), true)}
                    >
                      <RotateCcw size={14} />
                      {selected.status === "waiting_review" ? "核对并恢复" : "重试节点"}
                    </button>
                  )}
                  {["succeeded", "failed"].includes(selected.status) && (
                    <button
                      onClick={() =>
                        void action(async () => {
                          const replay = await api.replay(projectId, selected.id);
                          onRun(await api.detail(projectId, replay.id));
                        })
                      }
                    >
                      <RotateCcw size={14} />
                      按原快照回溯
                    </button>
                  )}
                  {selected.thread_id && host.openConversation && (
                    <button
                      onClick={() => void action(() => host.openConversation!(selected.thread_id!))}
                    >
                      <ExternalLink size={14} />
                      查看 DeerFlow 会话
                    </button>
                  )}
                </div>
                {snapshot && <SnapshotView key={snapshot.id} snapshot={snapshot} />}
              </section>
            )}
          </>
        )}
      </section>
    </div>
  );
}
