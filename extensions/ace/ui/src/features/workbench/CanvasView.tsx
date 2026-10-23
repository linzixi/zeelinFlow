import { useEffect, useMemo, useRef, useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type NodeProps,
  type Node as FlowNode,
  type NodeChange,
  type ReactFlowInstance,
} from "@xyflow/react";
import type { Graph, NodeType, RunDetail } from "../../lib/models";
import { canConnect, fitGroups, removeNode } from "./graph";
import EdgeInspector from "./EdgeInspector";
import NodeLibrary from "./NodeLibrary";

import NodeCard from "./NodeCard";

const nodeTypes = {
  ace: NodeCard,
  group: ({ data }: NodeProps) => <div className="ace-group-label">{String(data.label)}</div>,
};

interface Props {
  graph: Graph;
  catalog: NodeType[];
  run: RunDetail | null;
  onChange(graph: Graph): void;
  onSelect(id: string | null): void;
}
export default function CanvasView({ graph, catalog, run, onChange, onSelect }: Props) {
  const flow = useRef<Pick<ReactFlowInstance, "setCenter" | "screenToFlowPosition" | "fitView"> | null>(null);
  const region = useRef<HTMLDivElement>(null);
  const [libraryOpen, setLibraryOpen] = useState(() => window.innerWidth > 900);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const collapse = () => { if (media.matches) setLibraryOpen(false); };
    media.addEventListener("change", collapse);
    let timer: ReturnType<typeof setTimeout>;
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => void flow.current?.fitView({ padding: 0.15, minZoom: 0.05 }), 150);
    });
    if (region.current) observer.observe(region.current);
    return () => { media.removeEventListener("change", collapse); observer.disconnect(); clearTimeout(timer); };
  }, []);
  const [selected, setSelected] = useState<string[]>([]);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const nodes = useMemo(() => {
    const groups: FlowNode[] = graph.groups
      .filter((group) => group.nodeIds.length)
      .map((group) => ({
        id: `group:${group.id}`,
        type: "group",
        position: { x: group.bounds.x, y: group.bounds.y },
        data: { label: group.name },
        draggable: true,
        selectable: false,
        dragHandle: ".ace-group-label",
        style: { width: group.bounds.width, height: group.bounds.height },
        className: "ace-group",
        zIndex: -1,
      }));
    return [
      ...groups,
      ...graph.nodes.map((node) => ({
        id: node.id,
        type: "ace",
        position: { x: node.x, y: node.y },
        data: {
          node,
          status: run?.tasks.find((task) => task.node_id === node.id)?.status ?? "idle",
        },
        selected: selected.includes(node.id),
        width: 248,
        height: 112,
      })),
    ];
  }, [graph, run, selected]);
  const edges = useMemo(
    () =>
      graph.edges.map((edge) => ({
        ...edge,
        type: "smoothstep",
        selected: selectedEdge === edge.id,
        className: edge.executionDisabled ? "planning-edge" :
          run?.tasks.some(task => task.node_id === edge.source && ["running", "waiting_agent"].includes(task.status)) ? "running-edge" : "execution-edge",
      })),
    [graph.edges, run, selectedEdge],
  );
  function changes(values: NodeChange[]) {
    let updated = graph;
    for (const value of values) {
      if (!("id" in value)) continue;
      if (value.type === "select") {
        setSelected((previous) =>
          value.selected
            ? [...new Set([...previous, value.id])]
            : previous.filter((id) => id !== value.id),
        );
      }
      if (value.id.startsWith("group:")) {
        const group = updated.groups.find((item) => `group:${item.id}` === value.id);
        if (group && value.type === "position" && value.position) {
          const dx = value.position.x - group.bounds.x,
            dy = value.position.y - group.bounds.y;
          updated = fitGroups({
            ...updated,
            nodes: updated.nodes.map((node) =>
              group.nodeIds.includes(node.id) ? { ...node, x: node.x + dx, y: node.y + dy } : node,
            ),
          });
        }
        continue;
      }
      if (value.type === "position" && value.position) {
        const position = value.position;
        updated = {
          ...updated,
          nodes: updated.nodes.map((node) =>
            node.id === value.id ? { ...node, x: position.x, y: position.y } : node,
          ),
        };
      }
      if (value.type === "remove") updated = removeNode(updated, value.id);
    }
    if (updated !== graph) onChange(fitGroups(updated));
  }
  return (
    <div className={`canvas-layout ${libraryOpen ? "" : "library-collapsed"}`}>
      {libraryOpen && <NodeLibrary
        graph={graph}
        catalog={catalog}
        selected={selected}
        onChange={onChange}
        onSelect={onSelect}
        getPosition={() => {
          const rect = region.current?.getBoundingClientRect();
          return rect && flow.current ? flow.current.screenToFlowPosition({
            x: rect.left + rect.width / 2 - 124, y: rect.top + rect.height / 2 - 56,
          }) : { x: 0, y: 0 };
        }}
      />}
      <div ref={region} className="flow-region" aria-label="工作流画布">
        <button className="library-toggle" aria-label={libraryOpen ? "收起节点库" : "展开节点库"}
          onClick={() => setLibraryOpen(!libraryOpen)}>
          {libraryOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}节点库
        </button>
        <ReactFlow
          onInit={(instance) => {
            flow.current = instance;
          }}
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15, minZoom: 0.05 }}
          multiSelectionKeyCode="Shift"
          minZoom={0.05}
          maxZoom={1.6}
          onNodesChange={changes}
          onNodeClick={(_, node) => {
            setSelectedEdge(null);
            if (!node.id.startsWith("group:")) onSelect(node.id);
          }}
          onNodeDoubleClick={(_, node) => {
            if (!node.id.startsWith("group:")) {
              requestAnimationFrame(
                () =>
                  void flow.current?.setCenter(node.position.x + 124, node.position.y + 56, {
                    zoom: 0.85,
                    duration: 200,
                  }),
              );
            }
          }}
          onEdgeClick={(_, edge) => {
            onSelect(null);
            setSelectedEdge(edge.id);
          }}
          onEdgesChange={(changes) => {
            const selected = changes.find(change => change.type === "select" && change.selected);
            if (selected && "id" in selected) setSelectedEdge(selected.id);
          }}
          onPaneClick={() => {
            onSelect(null);
            setSelectedEdge(null);
          }}
          onSelectionChange={({ nodes: chosen }) =>
            setSelected((previous) => {
              const next = chosen.map((node) => node.id);
              return next.length === previous.length &&
                next.every((id, index) => id === previous[index])
                ? previous
                : next;
            })
          }
          onEdgesDelete={(deleted) =>
            onChange({
              ...graph,
              edges: graph.edges.filter((edge) => !deleted.some((item) => item.id === edge.id)),
            })
          }
          isValidConnection={(connection) =>
            canConnect(graph, connection.source, connection.target)
          }
          onConnect={(connection) =>
            onChange({
              ...graph,
              edges: [
                ...graph.edges,
                {
                  id: crypto.randomUUID(),
                  source: connection.source,
                  target: connection.target,
                  label: "",
                  conditionKey: "",
                  conditionValue: "",
                  executionDisabled: false,
                },
              ],
            })
          }
          deleteKeyCode={["Backspace", "Delete"]}
        >
          <Background gap={24} size={1} color="#2c3750" />
          <Controls fitViewOptions={{ padding: 0.15, minZoom: 0.05 }} />
          <MiniMap pannable zoomable />
        </ReactFlow>
        <div className="canvas-legend">
          <span className="legend-data" />
          数据处理 <span className="legend-agent" />
          Agent 沙箱 <span className="legend-delivery" />
          结果应用
        </div>
      </div>
      {graph.edges.find((edge) => edge.id === selectedEdge) && (
        <EdgeInspector
          edge={graph.edges.find((edge) => edge.id === selectedEdge)!}
          graph={graph}
          onChange={onChange}
          onClose={() => setSelectedEdge(null)}
        />
      )}
    </div>
  );
}
