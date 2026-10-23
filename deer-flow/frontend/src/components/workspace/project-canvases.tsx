"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { aceApi } from "@/lib/api";

import { PluginSurfaces } from "./plugin-surfaces";

export function ProjectCanvases({ nativeId }: { nativeId: string }) {
  const query = useQuery({
    queryKey: ["ace-project", nativeId],
    queryFn: () => aceApi.project(nativeId),
  });
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const search = useSearchParams();
  const router = useRouter();
  const selected = search.get("canvas");
  const canvas =
    query.data?.canvases.find((item) => item.id === selected) ??
    query.data?.canvases[0];
  function choose(id: string, confirmed = false) {
    if (
      !confirmed &&
      !document.dispatchEvent(
        new Event("ace:before-navigation", { cancelable: true }),
      )
    )
      return;
    const params = new URLSearchParams(search.toString());
    params.set("canvas", id);
    router.replace(`?${params.toString()}`, { scroll: false });
  }
  async function create() {
    if (!query.data || !name.trim() || busy) return;
    if (
      !document.dispatchEvent(
        new Event("ace:before-navigation", { cancelable: true }),
      )
    )
      return;
    setBusy(true);
    try {
      const item = await aceApi.createCanvas(
        query.data.project.id,
        name.trim(),
      );
      setName("");
      setError("");
      await query.refetch();
      choose(item.id, true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }
  if (query.isPending) return <p role="status">正在载入项目画布…</p>;
  if (query.isError)
    return <p role="alert">无法读取项目画布，请刷新或检查团队权限。</p>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <select
          aria-label="项目画布"
          className="bg-background rounded-md border p-2 text-sm"
          value={canvas?.id ?? ""}
          onChange={(event) => choose(event.target.value)}
        >
          {query.data?.canvases.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <Input
            aria-label="新画布名称"
            placeholder="新画布名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <Button variant="outline" disabled={!name.trim() || busy}>
            {busy ? "正在建立…" : "新建画布"}
          </Button>
        </form>
      </div>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      {canvas ? (
        <PluginSurfaces
          key={canvas.id}
          slot="page"
          namespace="qingbo.ace"
          surfaceId="workbench"
        />
      ) : (
        <p className="text-muted-foreground border p-8">
          这个项目还没有画布。建立画布后即可添加数据处理与 Agent 节点。
        </p>
      )}
    </div>
  );
}
