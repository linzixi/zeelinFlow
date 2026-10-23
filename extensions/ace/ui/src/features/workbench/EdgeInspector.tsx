import { X, Trash2 } from "lucide-react";
import type { CanvasEdge, Graph } from "../../lib/models";

interface Props {
  edge: CanvasEdge;
  graph: Graph;
  onChange(graph: Graph): void;
  onClose(): void;
}
export default function EdgeInspector({ edge, graph, onChange, onClose }: Props) {
  function update(changes: Partial<CanvasEdge>) {
    onChange({
      ...graph,
      edges: graph.edges.map((item) => (item.id === edge.id ? { ...item, ...changes } : item)),
    });
  }
  return (
    <aside className="inspector" aria-label="连线配置">
      <div className="inspector-header">
        <h2>连线配置</h2>
        <button className="icon-button" aria-label="关闭连线配置" onClick={onClose}>
          <X size={16} />
        </button>
      </div>
      <p>
        {graph.nodes.find((node) => node.id === edge.source)?.title} →{" "}
        {graph.nodes.find((node) => node.id === edge.target)?.title}
      </p>
      <label>
        连线名称
        <input value={edge.label} onChange={(event) => update({ label: event.target.value })} />
      </label>
      <label>
        条件字段
        <input
          placeholder="例如 hasItems，留空则总是继续"
          value={edge.conditionKey}
          onChange={(event) => update({ conditionKey: event.target.value })}
        />
      </label>
      <label>
        条件值
        <input
          placeholder="例如 true"
          value={edge.conditionValue}
          onChange={(event) => update({ conditionValue: event.target.value })}
        />
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          checked={!edge.executionDisabled}
          onChange={(event) => update({ executionDisabled: !event.target.checked })}
        />
        参与执行依赖
      </label>
      <p className="muted">
        上游成功后按输出上下文判断。多条输入会等各上游结束，再合并满足条件的数据。
      </p>
      <button
        className="danger"
        onClick={() => {
          onChange({ ...graph, edges: graph.edges.filter((item) => item.id !== edge.id) });
          onClose();
        }}
      >
        <Trash2 size={15} />
        删除连线
      </button>
    </aside>
  );
}
