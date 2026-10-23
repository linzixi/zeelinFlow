"use client";

import { useId } from "react";

import { useProjects } from "@/core/projects/hooks";

export function ScheduledProjectSelect({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const id = useId();
  const projects = useProjects("active");
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-medium">
        所属项目 *
      </label>
      <select
        id={id}
        aria-label="所属项目"
        className="bg-background border-input rounded-md border px-3 py-2 text-sm"
        value={value}
        disabled={disabled || projects.isLoading}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">请选择当前团队的项目</option>
        {projects.data?.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
      <p className="text-muted-foreground text-xs">
        {projects.isError
          ? "项目加载失败，请关闭后重试。"
          : "每次运行产生的对话保留在此项目；复用对话也必须属于此项目。"}
      </p>
    </div>
  );
}
