"use client";

import type { ExtensionModelTool } from "@/core/extensions/contracts";
import { useI18n } from "@/core/i18n/hooks";

export function ExtensionTools({
  tools,
  enabled,
}: {
  tools?: ExtensionModelTool[];
  enabled: boolean;
}) {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  if (!tools?.length) return null;
  return (
    <section
      className="space-y-4 border-t pt-6"
      aria-label={zh ? "扩展算子" : "Extension tools"}
    >
      <div>
        <h3 className="text-lg font-semibold">
          {zh ? "扩展算子" : "Extension tools"} ({tools.length})
        </h3>
        <p className="text-muted-foreground mt-2 text-sm">
          {zh
            ? "在对话中按用途提问即可使用。数据访问遵守项目权限与各算子的适用范围；参数定义供查看。"
            : "Ask in a conversation to use these tools. Access follows project permissions and each tool’s scope. Parameter definitions are for reference."}
        </p>
      </div>
      {tools.map((tool) => (
        <article key={tool.name} className="space-y-3 rounded-xl border p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-mono text-sm font-semibold break-all">
              {tool.name}
            </h4>
            <span className="text-muted-foreground text-xs">
              {enabled
                ? zh
                  ? "随扩展启用"
                  : "Enabled with extension"
                : zh
                  ? "扩展未启用"
                  : "Extension disabled"}
            </span>
          </div>
          <p className="text-muted-foreground text-sm leading-6">
            {tool.description}
          </p>
          <details>
            <summary className="cursor-pointer text-sm">
              {zh ? "查看参数" : "View parameters"}
            </summary>
            <pre className="bg-muted mt-3 max-h-80 overflow-auto rounded-lg p-3 text-xs">
              {JSON.stringify(tool.input_schema, null, 2)}
            </pre>
          </details>
        </article>
      ))}
    </section>
  );
}
