import { useEffect, useState } from "react";
import type { Api } from "../../lib/api";
import type { Project } from "../../lib/models";
import ArticleList from "./ArticleList";

export default function ReviewApp({ api }: { api: Api }) {
  const [projects, setProjects] = useState<Pick<Project, "id" | "name">[]>([]);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    void api.projects(true).then(items => {
      if (active) { setProjects(items); setSelected(items[0]?.id ?? ""); }
    }).catch((reason: Error) => { if (active) setError(reason.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api]);
  return <main className="ace-app">
    <header className="workbench-header"><h1>待审核预警文章</h1>
      <select aria-label="审核项目画布" value={selected} onChange={event => setSelected(event.target.value)}>
        {projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
    </header>
    {error && <p role="alert" className="error-banner">{error}</p>}
    {loading ? <p role="status">正在载入文章列表…</p> : selected ? <ArticleList key={selected} api={api} projectId={selected} /> : <div className="empty-state"><h2>当前团队暂无预警文章</h2><p>编排师建立画布并完成数据处理后，文章将出现在这里。</p></div>}
  </main>;
}
