import { useState } from "react";
import { Plus, FolderPlus, Workflow } from "lucide-react";
import type { Graph, NodeType } from "../../lib/models";
import { fitGroups, newNode } from "./graph";

interface Props {
  graph: Graph;
  catalog: NodeType[];
  selected: string[];
  onChange(graph: Graph): void;
  onSelect(id: string): void;
  getPosition(): { x: number; y: number };
}
export default function NodeLibrary({ graph, catalog, selected, onChange, onSelect, getPosition }: Props) {
  const [search, setSearch] = useState("");
  const [groupName, setGroupName] = useState("");
  function addGroup() {
    if (!selected.length || !groupName.trim()) return;
    onChange(
      fitGroups({
        ...graph,
        groups: [
          ...graph.groups,
          {
            id: crypto.randomUUID(),
            name: groupName,
            color: "#64748b",
            nodeIds: selected,
            bounds: { x: 0, y: 0, width: 300, height: 180 },
          },
        ],
      }),
    );
    setGroupName("");
  }
  return (
    <aside className="node-library">
      <div className="section-title">
        <Workflow size={16} />
        <h2>节点库</h2>
      </div>
      <input
        aria-label="搜索节点"
        placeholder="搜索节点…"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {[...new Set(catalog.map((item) => item.category))].map((category) => (
        <section key={category}>
          <h3>{category}</h3>
          {catalog
            .filter((item) => item.category === category && item.title.includes(search))
            .map((item) => (
              <button
                className="palette-item"
                key={item.type_id}
                onClick={() => {
                  const node = { ...newNode(item, graph.nodes.length), ...getPosition() };
                  onChange({ ...graph, nodes: [...graph.nodes, node] });
                  onSelect(node.id);
                }}
              >
                <span>{item.title}</span>
                <Plus size={13} />
              </button>
            ))}
        </section>
      ))}
      <div className="group-builder">
        <h3>功能分组</h3>
        <p>按住 Shift 选择节点，再建立分组。</p>
        <input
          aria-label="分组名称"
          placeholder="分组名称"
          value={groupName}
          onChange={(event) => setGroupName(event.target.value)}
        />
        <button disabled={!selected.length || !groupName.trim()} onClick={addGroup}>
          <FolderPlus size={14} />
          包住选中节点
        </button>
        {graph.groups.map((group) => (
          <div className="group-row" key={group.id}>
            <input
              aria-label={`分组：${group.name}`}
              value={group.name}
              onChange={(event) =>
                onChange({
                  ...graph,
                  groups: graph.groups.map((item) =>
                    item.id === group.id ? { ...item, name: event.target.value } : item,
                  ),
                })
              }
            />
            <button
              className="icon-button"
              aria-label={`移除分组：${group.name}`}
              onClick={() =>
                onChange({
                  ...graph,
                  groups: graph.groups.filter((item) => item.id !== group.id),
                })
              }
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}
