"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Folder, Plus, ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { aceApi } from "@/lib/api";

import { useTeamAccess } from "./team-access";

export function ProjectChooser({ newChatPath }: { newChatPath?: string }) {
  const access = useTeamAccess();
  const router = useRouter();
  const cache = useQueryClient();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function open(id: string) {
    setBusy(true);
    setError("");
    try {
      const result = await aceApi.openProject(id);
      router.push(
        newChatPath
          ? `${newChatPath}?project=${result.native_project_id}`
          : `/workspace/projects/${result.native_project_id}`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "打开项目失败");
    } finally {
      setBusy(false);
    }
  }
  async function create() {
    if (!access?.active_team_id || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const project = await aceApi.createProject(
        access.active_team_id,
        name.trim(),
        "",
      );
      setName("");
      await cache.invalidateQueries({ queryKey: ["ace-access"] });
      await open(project.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="mx-auto w-full max-w-5xl space-y-6 p-6">
      <div>
        <p className="text-muted-foreground text-sm">
          {
            access?.teams.find((team) => team.id === access.active_team_id)
              ?.name
          }
        </p>
        <h1 className="mt-1 text-2xl font-semibold">
          {newChatPath ? "为新对话选择项目" : "团队项目"}
        </h1>
        <p className="text-muted-foreground mt-2 text-sm">
          项目统一组织画布、预警文章、对话和资料。
        </p>
      </div>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      <div className="divide-y rounded-lg border">
        {access?.projects.map((project) => (
          <button
            key={project.id}
            disabled={busy}
            onClick={() => void open(project.id)}
            className="hover:bg-muted flex w-full items-center gap-4 p-5 text-left"
          >
            <Folder className="text-muted-foreground size-5" />
            <span className="flex-1">
              <strong className="font-medium">{project.name}</strong>
              <span className="text-muted-foreground mt-1 block text-sm">
                {project.description || "进入项目，管理画布与对话"}
              </span>
            </span>
            <ArrowRight className="size-4" />
          </button>
        ))}
        {!access?.projects.length && (
          <p className="text-muted-foreground p-8">
            当前团队暂无项目，可在下方建立第一个项目。
          </p>
        )}
      </div>
      {access?.permissions.includes("projects.write") && (
        <form
          className="flex max-w-xl gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <Input
            aria-label="新项目名称"
            placeholder="新项目名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={128}
          />
          <Button disabled={busy || !name.trim()}>
            <Plus className="size-4" />
            建立项目
          </Button>
        </form>
      )}
    </section>
  );
}
