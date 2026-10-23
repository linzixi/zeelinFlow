import { useState } from "react";
import type { CanvasNode } from "../../lib/models";

export default function ReportSettings({ node, onChange }: {
  node: CanvasNode; onChange: (changes: Partial<CanvasNode>) => void;
}) {
  const raw = node.config.report_window;
  const window = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  const [start, setStart] = useState(String(window.start ?? "").slice(0, 16));
  const [end, setEnd] = useState(String(window.end ?? "").slice(0, 16));
  const [error, setError] = useState("");
  function apply() {
    if (!start || !end || start >= end) {
      setError("请选择开始和结束时间，结束时间须晚于开始时间。");
      return;
    }
    onChange({ config: { ...node.config, report_window: {
      start: `${start}:00+08:00`, end: `${end}:00+08:00`,
      timeField: "ingested_at", timezone: "Asia/Shanghai",
    } } });
    setError("");
  }
  return <section className="inspector-section">
    <h3>智能问数范围</h3>
    <p>按本项目入库时间查询，时间为北京时间。报告会保存统计口径、原文版本和查询记录。</p>
    <label>开始时间<input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} /></label>
    <label>结束时间<input type="datetime-local" value={end} onChange={e => setEnd(e.target.value)} /></label>
    <button onClick={apply}>应用报告时间范围</button>
    <button onClick={() => {
      const { report_window: _window, ...config } = node.config;
      onChange({ config }); setStart(""); setEnd(""); setError("");
    }}>跟随本次运行时间</button>
    {error && <p role="alert">{error}</p>}
    <p>在“处理要求”中输入想了解的问题。可用总览、分组统计、时间序列和原文检索四类只读算子。</p>
  </section>;
}
