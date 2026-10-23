"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { TeamMember } from "@/lib/ace-types";
import { aceApi } from "@/lib/api";

import { useTeamAccess } from "./team-access";

const roles = [
  { id: "admin", name: "团队管理员" },
  { id: "orchestrator", name: "编排师" },
  { id: "reviewer", name: "预警审核" },
];

export function TeamManagement() {
  const access = useTeamAccess();
  const cache = useQueryClient();
  const team = access?.active_team_id ?? "";
  const canManage = access?.permissions.includes("team.manage");
  const query = useQuery({
    queryKey: ["ace-members", team],
    queryFn: () => aceApi.members(team),
    enabled: Boolean(team && canManage),
  });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("reviewer");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  async function change(address: string, next: string, revision?: number) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await aceApi.setMember(team, address, next, revision);
      await query.refetch();
      await cache.invalidateQueries({ queryKey: ["ace-access"] });
      setEmail("");
      setNotice("成员权限已更新，下一次请求立即生效。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新失败");
    } finally {
      setBusy(false);
    }
  }
  async function createTeam() {
    setBusy(true);
    setError("");
    try {
      await aceApi.createTeam(name.trim());
      window.location.href = "/workspace/teams";
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="mx-auto w-full max-w-5xl space-y-7 p-6 md:p-10">
      <div>
        <p className="text-muted-foreground text-sm">组织与访问控制</p>
        <h1 className="mt-1 text-2xl font-semibold">团队与成员</h1>
        <p className="text-muted-foreground mt-2 text-sm">
          一个账号可以加入多个团队，角色分别生效。切换团队后，项目和操作权限随之切换。
        </p>
      </div>
      <div className="overflow-auto rounded-lg border">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">角色权限范围</caption>
          <thead className="bg-muted">
            <tr>
              <th className="p-4">角色</th>
              <th>项目 / 画布 / Agent</th>
              <th>预警文章审核编辑</th>
              <th>成员管理</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            <tr>
              <td className="p-4">团队管理员</td>
              <td>允许</td>
              <td>允许</td>
              <td>允许</td>
            </tr>
            <tr>
              <td className="p-4">编排师</td>
              <td>允许</td>
              <td>允许</td>
              <td>不允许</td>
            </tr>
            <tr>
              <td className="p-4">预警审核</td>
              <td>不允许</td>
              <td>允许</td>
              <td>不允许</td>
            </tr>
          </tbody>
        </table>
      </div>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {canManage ? (
        <section className="space-y-4">
          <h2 className="text-lg font-medium">当前团队成员</h2>
          {query.isPending ? (
            <p role="status">正在加载成员…</p>
          ) : query.isError ? (
            <p role="alert">读取成员失败。</p>
          ) : (
            <div className="divide-y rounded-lg border">
              {query.data?.map((member) => (
                <MemberRow
                  key={member.user_id}
                  member={member}
                  busy={busy}
                  onChange={(next) =>
                    void change(member.label, next, member.revision)
                  }
                />
              ))}
            </div>
          )}
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void change(email, role);
            }}
          >
            <Input
              className="max-w-sm"
              type="email"
              aria-label="成员邮箱"
              placeholder="已注册账号的邮箱"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            <select
              aria-label="新增成员角色"
              className="bg-background rounded-md border px-3"
              value={role}
              onChange={(event) => setRole(event.target.value)}
            >
              {roles.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <Button disabled={busy || !email}>添加成员</Button>
          </form>
        </section>
      ) : (
        <p>当前角色可以查看权限说明；成员变更由团队管理员操作。</p>
      )}
      {access?.platform_admin && (
        <section className="space-y-3 border-t pt-6">
          <h2 className="font-medium">建立团队</h2>
          <form
            className="flex max-w-xl gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void createTeam();
            }}
          >
            <Input
              aria-label="新团队名称"
              placeholder="例如：汽车客户服务团队"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={128}
            />
            <Button disabled={busy || !name.trim()}>新建团队</Button>
          </form>
        </section>
      )}
    </main>
  );
}

function MemberRow({
  member,
  busy,
  onChange,
}: {
  member: TeamMember;
  busy: boolean;
  onChange: (role: string) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 p-4">
      <span className="min-w-0 truncate">{member.label}</span>
      <select
        aria-label={`${member.label}的团队角色`}
        className="bg-background rounded-md border p-2 text-sm"
        value={member.role}
        disabled={busy}
        onChange={(event) => onChange(event.target.value)}
      >
        {roles.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
        <option value="disabled">移出团队</option>
      </select>
    </div>
  );
}
