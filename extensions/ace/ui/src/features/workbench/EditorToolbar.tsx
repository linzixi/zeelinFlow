import { Activity, FileText, GitBranch, Play, Save, Check } from "lucide-react";
import type { Mode } from "../../lib/models";

type Tab = "canvas" | "articles" | "runs";
interface Props {
  tab: Tab; onTab: (tab: Tab) => void;
  dirty: boolean; revision?: number; busy: boolean; canRun: boolean;
  mode: Mode; onMode: (mode: Mode) => void; onSave: () => void; onRun: () => void;
}
export default function EditorToolbar({ tab, onTab, dirty, revision, busy, canRun, mode, onMode, onSave, onRun }: Props) {
  return (
      <div className="workbench-toolbar">
        <nav aria-label="工作区视图">
          <button
            className={tab === "canvas" ? "tab active" : "tab"}
            onClick={() => onTab("canvas")}
          >
            <GitBranch size={16} />
            可视化编排
          </button>
          <button
            className={tab === "articles" ? "tab active" : "tab"}
            onClick={() => onTab("articles")}
          >
            <FileText size={16} />
            预警文章
          </button>
          <button
            className={tab === "runs" ? "tab active" : "tab"}
            onClick={() => onTab("runs")}
          >
            <Activity size={16} />
            运行记录
          </button>
        </nav>
        <div className="toolbar-actions">
          <span className={dirty ? "save-status unsaved" : "save-status"}>
            {dirty ? (
              "有未保存修改"
            ) : (
              <>
                <Check size={13} />
                已保存 · v{revision}
              </>
            )}
          </span>
          <button disabled={busy || !dirty} onClick={() => onSave()}>
            <Save size={14} />
            保存
          </button>
          <select
            aria-label="运行模式"
            value={mode}
            onChange={(event) => onMode(event.target.value as Mode)}
          >
            <option value="simulation">模拟运行</option>
            <option value="live">正式运行</option>
          </select>
          <button
            className="primary"
            disabled={busy || !canRun}
            onClick={() => onRun()}
          >
            <Play size={14} />
            {busy ? "处理中…" : "运行画布"}
          </button>
        </div>
      </div>
  );
}
