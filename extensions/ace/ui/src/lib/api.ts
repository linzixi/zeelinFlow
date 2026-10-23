import type {
  Article,
  ArticleChanges,
  ArticleRevision,
  Graph,
  Mode,
  NodeType,
  Project,
  Run,
  RunDetail,
  Snapshot,
} from "../lib/models";

export interface HostContext {
  locale: string;
  signal: AbortSignal;
  callBackend(action: string, payload: object): Promise<unknown>;
  openConversation?(threadId: string): Promise<void>;
}
export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
  ) {
    super(message);
  }
}
export function createApi(host: HostContext) {
  async function call<T>(action: string, payload: object = {}): Promise<T> {
    if (new TextEncoder().encode(JSON.stringify(payload)).length > 250 * 1024) {
      throw new ApiError("配置超过单次保存上限，请将长脚本或验证记录存为技能文件后引用。", "size");
    }
    if (host.signal.aborted) throw new DOMException("已取消", "AbortError");
    const raw = await host.callBackend(action, payload);
    if (host.signal.aborted) throw new DOMException("已取消", "AbortError");
    if (!raw || typeof raw !== "object" || !("ok" in raw))
      throw new ApiError("服务返回格式错误", "response");
    if (raw.ok !== true) {
      const error = "error" in raw && typeof raw.error === "object" && raw.error ? raw.error : {};
      throw new ApiError(
        "message" in error ? String(error.message) : "请求未完成",
        "code" in error ? String(error.code) : "unknown",
      );
    }
    if (!("data" in raw)) throw new ApiError("服务返回数据缺失", "response");
    return raw.data as T;
  }
  return {
    access: () => call<{ role: string; permissions: string[] }>("access"),
    projects: (all = false) => {
      const nativeId = /^\/workspace\/projects\/([^/]+)/.exec(window.location.pathname)?.[1];
      return call<Project[]>("list_projects", !all && nativeId ? { native_project_id: nativeId } : {});
    },
    seed: () => call<Project>("seed_cmc"),
    catalog: () => call<NodeType[]>("catalog"),
    project: (project_id: string) => call<Project>("get_project", { project_id }),
    save: (project: Project, graph: Graph) =>
      call<Project>("save_project", {
        project_id: project.id,
        name: project.name,
        revision: project.revision,
        graph,
      }),
    run: (project_id: string, mode: Mode, start?: string, single = false) =>
      call<Run>("run", { project_id, mode, start, single, key: crypto.randomUUID() }),
    runs: (project_id: string) => call<Run[]>("list_runs", { project_id }),
    detail: (project_id: string, run_id: string) =>
      call<RunDetail>("run_detail", { project_id, run_id }),
    cancel: (project_id: string, run_id: string) => call<Run>("cancel_run", { project_id, run_id }),
    retry: (project_id: string, task_id: string) => call("retry_task", { project_id, task_id }),
    replay: (project_id: string, task_id: string) =>
      call<Run>("replay_task", { project_id, task_id, key: crypto.randomUUID() }),
    articles: (
      project_id: string,
      query: string,
      risk: string,
      review_status: string,
      offset = 0,
    ) =>
      call<{ items: Article[]; total: number }>("list_articles", {
        project_id,
        query,
        risk,
        review_status,
        offset,
        limit: 50,
      }),
    updateArticle: (project_id: string, article: Article, patch: ArticleChanges) =>
      call<Article>("update_article", { project_id, article_id: article.id, patch }),
    articleHistory: (project_id: string, article_id: string) =>
      call<ArticleRevision[]>("article_history", { project_id, article_id }),
    snapshot: (project_id: string, snapshot_id: string) =>
      call<Snapshot>("snapshot", { project_id, snapshot_id }),
  };
}
export type Api = ReturnType<typeof createApi>;
