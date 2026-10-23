import { Handle, Position, type NodeProps, type Node as FlowNode } from "@xyflow/react";
import { Bot, Database, Radio } from "lucide-react";
import type { CanvasNode } from "../../lib/models";
import { LANE, STATUS } from "../../lib/models";

type CardNode = FlowNode<{ node: CanvasNode; status: string }, "ace">;
export default function NodeCard({ data, selected }: NodeProps<CardNode>) {
  const Icon =
    data.node.executor === "agent" ? Bot : data.node.executor === "delivery" ? Radio : Database;
  return (
    <div className={`ace-node ${selected ? "selected" : ""} lane-${data.node.executor} state-${data.status} ${data.node.enabled ? "" : "disabled"}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-meta">
        <Icon size={14} />
        <span>{LANE[data.node.executor]}</span>
        {data.node.trigger.kind === "cron" && <span className="node-schedule">定时</span>}
      </div>
      <strong title={data.node.title}>{data.node.title}</strong>
      <div className="node-footer">
        <span className={`status-dot ${data.status}`} />
        <span>{!data.node.enabled ? "已停用" : STATUS[data.status] ?? "就绪"}</span>
        <span>
          {data.node.operation === "ingest"
            ? "采集 → 入库"
            : data.node.executor === "agent"
              ? "按需执行"
              : "独立任务"}
        </span>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
