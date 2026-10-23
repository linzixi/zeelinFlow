import { fetch as authenticatedFetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  CanvasSummary,
  TeamMember,
  TeamProject,
  WorkspaceAccess,
} from "./ace-types";

async function request<T>(
  path: string,
  method = "GET",
  body?: object,
): Promise<T> {
  const response = await authenticatedFetch(
    `${getBackendBaseURL()}/api/ace${path}`,
    {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    },
  );
  const value: unknown = await response.json();
  if (!response.ok) {
    const detail =
      typeof value === "object" && value && "detail" in value
        ? value.detail
        : "操作失败";
    throw new Error(typeof detail === "string" ? detail : "请检查输入或权限");
  }
  return value as T;
}
export const aceApi = {
  context: () => request<WorkspaceAccess>("/context"),
  selectTeam: (team_id: string) => request("/active-team", "POST", { team_id }),
  createTeam: (name: string) => request("/teams", "POST", { name }),
  members: (team: string) =>
    request<TeamMember[]>(`/teams/${encodeURIComponent(team)}/members`),
  setMember: (
    team_id: string,
    email: string,
    role: string,
    revision?: number,
  ) => request("/members", "PUT", { team_id, email, role, revision }),
  createProject: (team_id: string, name: string, description: string) =>
    request<TeamProject>("/projects", "POST", { team_id, name, description }),
  openProject: (id: string) =>
    request<{ native_project_id: string }>(
      `/projects/${encodeURIComponent(id)}/open`,
      "POST",
    ),
  project: (nativeId: string) =>
    request<{ project: TeamProject; canvases: CanvasSummary[] }>(
      `/native-projects/${encodeURIComponent(nativeId)}`,
    ),
  createCanvas: (id: string, name: string) =>
    request<CanvasSummary>(
      `/projects/${encodeURIComponent(id)}/canvases`,
      "POST",
      { name },
    ),
};
