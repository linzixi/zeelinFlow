import { useState } from "react";
import { Play, Trash2, X } from "lucide-react";
import type { CanvasNode, Graph, Json, Task } from "../../lib/models";
import { LANE, STATUS } from "../../lib/models";
import { removeNode } from "./graph";
import ReportSettings from "./ReportSettings";
import NodeTriggerSettings from "./NodeTriggerSettings";

interface Props {
  node: CanvasNode;
  graph: Graph;
  task?: Task;
  onChange(graph: Graph): void;
  onClose(): void;
  onRun(id: string): void;
  onTask(task: Task): void;
}
export default function NodeInspector({
  node,
  graph,
  task,
  onChange,
  onClose,
  onRun,
  onTask,
}: Props) {
  const [configText, setConfigText] = useState(JSON.stringify(node.config, null, 2));
  const [error, setError] = useState("");
  function update(changes: Partial<CanvasNode>) {
    onChange({
      ...graph,
      nodes: graph.nodes.map((item) => (item.id === node.id ? { ...item, ...changes } : item)),
    });
  }
  return (
    <aside className="inspector" aria-label="节点配置">
      <div className="inspector-header">
        <div>
          <small>{LANE[node.executor]}</small>
          <h2>节点配置</h2>
        </div>
        <button className="icon-button" aria-label="关闭节点配置" onClick={onClose}>
          <X size={16} />
        </button>
      </div>
      <label>
        节点名称
        <input value={node.title} onChange={(event) => update({ title: event.target.value })} />
      </label>
      <div className="form-row">
        <label>
          执行方式
          <select
            value={node.executor}
            onChange={(event) => update({ executor: event.target.value as CanvasNode["executor"] })}
          >
            <option value="data">数据处理队列</option>
            <option value="agent">DeerFlow Agent</option>
            <option value="delivery">结果应用</option>
          </select>
        </label>
        <label>
          启用状态
          <select
            value={String(node.enabled)}
            onChange={(event) => update({ enabled: event.target.value === "true" })}
          >
            <option value="true">启用</option>
            <option value="false">停用</option>
          </select>
        </label>
      </div>
      <label>
        处理要求
        <textarea
          rows={6}
          value={node.instructions}
          onChange={(event) => update({ instructions: event.target.value })}
        />
      </label>
      {node.executor === "agent" && (
        <>
          <label>
            DeerFlow Agent
            <input
              value={node.agentRef}
              onChange={(event) => update({ agentRef: event.target.value })}
            />
          </label>
          <details>
            <summary>节点 Skill</summary>
            <textarea
              aria-label="节点 Skill"
              rows={7}
              value={node.skill}
              onChange={(event) => update({ skill: event.target.value })}
            />
          </details>
        </>
      )}
      {node.type === "warehouse_report" && <ReportSettings node={node} onChange={update} />}
      <NodeTriggerSettings node={node} onChange={update} />
      <details>
        <summary>输入输出与高级参数</summary>
        <label>
          处理操作
          <input
            value={node.operation}
            onChange={(event) => update({ operation: event.target.value })}
          />
        </label>
        <label>
          输入契约
          <input
            value={node.inputContract}
            onChange={(event) => update({ inputContract: event.target.value })}
          />
        </label>
        <label>
          输出契约
          <input
            value={node.outputContract}
            onChange={(event) => update({ outputContract: event.target.value })}
          />
        </label>
        <label>
          参数 JSON
          <textarea
            className="code-text"
            rows={10}
            value={configText}
            onChange={(event) => setConfigText(event.target.value)}
          />
        </label>
        <button
          onClick={() => {
            try {
              const parsed: unknown = JSON.parse(configText);
              if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
              update({ config: parsed as Record<string, Json> });
              setError("");
            } catch {
              setError("参数必须是有效的 JSON 对象");
            }
          }}
        >
          应用参数
        </button>
        {error && (
          <p role="alert" className="field-error">
            {error}
          </p>
        )}
        <small>原节点类型：{node.type}</small>
      </details>
      {task && (
        <button className="task-link" onClick={() => onTask(task)}>
          最近执行 · {STATUS[task.status] ?? task.status} · 第 {task.attempt} 次尝试
        </button>
      )}
      <div className="inspector-actions">
        <button className="primary" onClick={() => onRun(node.id)}>
          <Play size={14} />
          运行此节点
        </button>
        <button
          className="danger icon-button"
          aria-label="删除此节点"
          onClick={() => {
            onChange(removeNode(graph, node.id));
            onClose();
          }}
        >
          <Trash2 size={15} />
        </button>
      </div>
    </aside>
  );
}
