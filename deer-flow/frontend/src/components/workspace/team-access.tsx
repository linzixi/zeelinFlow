"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { createContext, useContext } from "react";
import { toast } from "sonner";

import { useAuth } from "@/core/auth/AuthProvider";
import type { WorkspaceAccess } from "@/lib/ace-types";
import { aceApi } from "@/lib/api";

import { PluginSurfaces } from "./plugin-surfaces";
import { ProjectChooser } from "./team-projects";

const AccessContext = createContext<WorkspaceAccess | null>(null);
export function useTeamAccess() {
  return useContext(AccessContext);
}

export function TeamSwitcher() {
  const access = useTeamAccess();
  if (!access) return null;
  return (
    <div className="flex items-center gap-2 p-3">
      <select
        aria-label="当前团队"
        className="border-input bg-background min-w-0 flex-1 rounded-md border p-2 text-sm"
        value={access.active_team_id ?? ""}
        onChange={(event) => {
          if (
            !document.dispatchEvent(
              new Event("ace:before-navigation", { cancelable: true }),
            )
          )
            return;
          void aceApi
            .selectTeam(event.target.value)
            .then(() => {
              window.location.href = "/workspace/projects";
            })
            .catch(() => toast.error("团队切换失败，请重试"));
        }}
      >
        {access.teams.map((team) => (
          <option key={team.id} value={team.id}>
            {team.name} · {access.roles[team.role]}
          </option>
        ))}
      </select>
    </div>
  );
}

export function TeamAccessBoundary({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const search = useSearchParams();
  const query = useQuery({
    queryKey: ["ace-access", user?.id],
    queryFn: aceApi.context,
    retry: false,
    refetchInterval: 15000,
    staleTime: 5000,
  });
  if (query.isPending)
    return (
      <div role="status" className="p-8">
        正在加载团队权限…
      </div>
    );
  if (query.isError)
    return (
      <div role="alert" className="p-8">
        无法读取团队权限。
        <button onClick={() => void query.refetch()}>重试</button>
      </div>
    );
  const access = query.data;
  if (!access) return null;
  const reviewer = access.role === "reviewer";
  const newChat =
    (pathname.endsWith("/new") && pathname.includes("/chats/")) ||
    pathname === "/workspace/agents/new";
  return (
    <AccessContext.Provider value={access}>
      {reviewer ? (
        <div className="bg-background flex h-screen flex-col">
          <header className="flex items-center justify-between border-b px-6 py-2">
            <div>
              <strong>预警审核工作台</strong>
              <p className="text-muted-foreground text-sm">
                {user?.email} · 仅可查看和编辑预警文章
              </p>
            </div>
            <TeamSwitcher />
            <button className="text-sm" onClick={() => void logout()}>
              退出登录
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-auto p-4">
            <PluginSurfaces
              slot="page"
              namespace="qingbo.ace"
              surfaceId="workbench"
            />
          </div>
        </div>
      ) : !access.active_team_id ? (
        <div className="p-8">
          <h1>尚未加入团队</h1>
          <p>请联系团队管理员添加此账号。</p>
          <button onClick={() => void logout()}>退出登录</button>
        </div>
      ) : newChat && !search.get("project") ? (
        <div className="p-8">
          <Link href="/workspace/projects">返回项目</Link>
          <ProjectChooser newChatPath={pathname} />
        </div>
      ) : (
        children
      )}
    </AccessContext.Provider>
  );
}
