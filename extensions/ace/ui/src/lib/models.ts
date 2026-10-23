export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Executor = "data" | "agent" | "delivery";
export type Mode = "simulation" | "live";
export interface Trigger {
  kind: "manual" | "event" | "cron";
  enabled: boolean;
  cron: string;
  timezone: string;
  runAtTimes: string[];
  lookbackMinutes: number;
  mode?: Mode;
}
export interface CanvasNode {
  id: string;
  type: string;
  title: string;
  x: number;
  y: number;
  executor: Executor;
  operation: string;
  instructions: string;
  skill: string;
  agentRef: string;
  config: Record<string, Json>;
  trigger: Trigger;
  enabled: boolean;
  inputContract: string;
  outputContract: string;
}
export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  conditionKey: string;
  conditionValue: string;
  executionDisabled: boolean;
}
export interface CanvasGroup {
  id: string;
  name: string;
  color: string;
  nodeIds: string[];
  bounds: { x: number; y: number; width: number; height: number };
}
export interface Graph {
  schemaVersion: 1;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  groups: CanvasGroup[];
}
export interface Project {
  id: string;
  name: string;
  description: string;
  revision: number;
  graph: Graph;
  source: Record<string, Json>;
  updated_at: number;
}
export interface NodeType {
  type_id: string;
  title: string;
  executor: Executor;
  operation: string;
  category: string;
}
export interface ArticleData {
  title: string;
  url: string;
  content: string;
  source: string;
  summary: string;
  sentiment: string;
  risk: string;
  tags: string[];
  review_status: string;
  published_at: string | null;
  ingested_at: string;
  metrics: Record<string, number>;
  decision?: string;
  predicted_car?: string;
  problem_content?: string;
  news_dig?: string;
  sis_status?: string;
  evidence_limit?: string;
  last_task_id?: string;
}
export interface Article {
  id: string;
  revision: number;
  data: ArticleData;
  branch: string;
  mode: Mode;
  risk: string;
  review_status: string;
  updated_at: number;
}
export interface ArticlePatch {
  revision: number;
  title: string;
  summary: string;
  sentiment: string;
  risk: string;
  review_status: string;
  tags: string[];
  note: string;
  predicted_car?: string;
  problem_content?: string;
  news_dig?: string;
}
export interface ArticleRevision {
  id: string;
  revision: number;
  actor: string;
  reason: string;
  data: ArticleData;
  created_at: number;
}
export type ArticleChanges = Pick<ArticlePatch, "revision" | "note"> & Partial<ArticlePatch>;
export interface Task {
  id: string;
  node_id: string;
  node: CanvasNode;
  status: string;
  executor: Executor;
  attempt: number;
  input_snapshot_id: string | null;
  output_snapshot_id: string | null;
  started_at: number | null;
  finished_at: number | null;
  error: string | null;
  thread_id: string | null;
  agent_run_id: string | null;
}
export interface Run {
  id: string;
  status: string;
  mode: Mode;
  origin: string;
  graph_revision: number;
  created_at: number;
  finished_at: number | null;
  replay_of: string | null;
}
export interface RunDetail extends Run {
  tasks: Task[];
  events: { id: string; kind: string; created_at: number; payload: Json }[];
}
export interface Snapshot {
  id: string;
  digest: string;
  kind: string;
  created_at: number;
  mode: Mode;
  payload: {
    records: Record<string, Json>[];
    summary?: string;
    context: Record<string, Json>;
    artifacts?: Record<string, Json>[];
  };
}
export const STATUS: Record<string, string> = {
  blocked: "等待上游",
  queued: "排队中",
  running: "执行中",
  waiting_agent: "Agent 执行中",
  waiting_review: "等待人工核对",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  skipped: "已跳过",
};
export const RISK: Record<string, string> = {
  high: "高风险",
  medium: "中风险",
  low: "低风险",
  unknown: "未研判",
};
export const REVIEW: Record<string, string> = {
  pending: "待核验",
  confirmed: "已确认",
  excluded: "已排除",
  watching: "持续观察",
};
export const LANE: Record<Executor, string> = {
  data: "数据处理",
  agent: "Agent 沙箱",
  delivery: "结果应用",
};
export function formatTime(value: number | string | null): string {
  if (!value) return "—";
  return new Date(typeof value === "number" ? value * 1000 : value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
