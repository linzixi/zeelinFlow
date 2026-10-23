import type { Graph, RunDetail, Mode } from "../../lib/models";
import { STATUS } from "../../lib/models";

export default function WorkbenchFooter({
  graph,
  run,
  mode,
}: {
  graph: Graph | null;
  run: RunDetail | null;
  mode: Mode;
}) {
  const counts = {
    done: run?.tasks.filter((t) => t.status === "succeeded").length ?? 0,
    running: run?.tasks.filter((t) => ["running", "waiting_agent"].includes(t.status)).length ?? 0,
  };
  return (
    <footer className="workbench-footer">
      <span>
        <i className="connected-dot" />
        本地数据空间
      </span>
      <span>
        {graph?.nodes.length ?? 0} 个节点 · {graph?.edges.length ?? 0} 条连线
      </span>
      <span className="footer-run">
        {run
          ? `${STATUS[run.status]} · 完成 ${counts.done} / ${run.tasks.length} · 执行中 ${counts.running}`
          : "等待触发"}
      </span>
      <span>北京时间 · {mode === "simulation" ? "模拟数据，不对外推送" : "正式数据模式"}</span>
    </footer>
  );
}
