import { useEffect, useState } from "react";
import { Search, RefreshCw, FileText, ArrowRight } from "lucide-react";
import type { Api } from "../../lib/api";
import type { Article } from "../../lib/models";
import { formatTime, REVIEW, RISK } from "../../lib/models";
import ArticleEditor from "./ArticleEditor";
import { startPolling } from "./polling";

export default function ArticleList({ api, projectId }: { api: Api; projectId: string }) {
  const [query, setQuery] = useState("");
  const [risk, setRisk] = useState("");
  const [review, setReview] = useState("");
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const [items, setItems] = useState<Article[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Article | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const result = await api.articles(projectId, query, risk, review, offset);
        if (active) {
          setItems(result.items);
          setTotal(result.total);
          setError("");
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "读取文章失败");
      } finally {
        if (active) setLoading(false);
      }
    }
    setLoading(true);
    let stop: (() => void) | undefined;
    const delay = setTimeout(() => { stop = startPolling(load, 10000); }, 200);
    return () => {
      active = false;
      clearTimeout(delay);
      stop?.();
    };
  }, [api, projectId, query, risk, review, offset, version]);
  return (
    <div className="articles-view">
      <div className="view-heading">
        <div>
          <small>数据资产 / 预警结果</small>
          <h2>
            预警文章 <span>{total}</span>
          </h2>
          <p>查看研判依据、确认预警，并保留每一次人工修订。</p>
        </div>
        <button onClick={() => setVersion(version + 1)}>
          <RefreshCw size={14} />
          刷新
        </button>
      </div>
      <div className="filter-bar">
        <div className="search-field">
          <Search size={16} />
          <input
            aria-label="搜索文章标题"
            placeholder="搜索文章标题…"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setOffset(0);
            }}
          />
        </div>
        <select
          aria-label="筛选风险等级"
          value={risk}
          onChange={(event) => {
            setRisk(event.target.value);
            setOffset(0);
          }}
        >
          <option value="">全部风险等级</option>
          {Object.entries(RISK).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="筛选处理状态"
          value={review}
          onChange={(event) => {
            setReview(event.target.value);
            setOffset(0);
          }}
        >
          <option value="">全部处理状态</option>
          {Object.entries(REVIEW).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      {loading ? (
        <div className="empty-state" aria-busy="true">
          正在读取文章…
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <FileText size={32} />
          <h3>暂无匹配的文章</h3>
          <p>暂无可审核结果，请稍后刷新或调整筛选条件。</p>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="article-table">
            <thead>
              <tr>
                <th>文章与研判</th>
                <th>业务分支</th>
                <th>风险等级</th>
                <th>处理状态</th>
                <th>入库时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((article) => (
                <tr key={article.id}>
                  <td>
                    <button className="article-title" onClick={() => setSelected(article)}>
                      {article.data.title.trim() || "无标题文章"}
                    </button>
                    <p className="article-excerpt">
                      {article.data.summary || article.data.content}
                    </p>
                    <small>
                      {article.data.source} ·{" "}
                      {article.mode === "simulation" ? "模拟数据" : "实时数据"} · v
                      {article.revision}
                    </small>
                  </td>
                  <td>{article.branch === "sgm" ? "上汽通用" : article.branch === "fund" ? "基金招募" : "专项舆情"}</td>
                  <td>
                    <span className={`risk-badge ${article.risk}`}>
                      {RISK[article.risk] ?? article.risk}
                    </span>
                  </td>
                  <td>
                    <span className={`review-badge ${article.review_status}`}>
                      {REVIEW[article.review_status] ?? article.review_status}
                    </span>
                  </td>
                  <td className="time-cell">{formatTime(article.data.ingested_at)}</td>
                  <td>
                    <button className="text-button" onClick={() => setSelected(article)}>
                      核验 / 修改
                      <ArrowRight size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="pagination">
        <span>
          共 {total} 条 · 当前 {total ? offset + 1 : 0}–{Math.min(offset + 50, total)}
        </span>
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>
          上一页
        </button>
        <button disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>
          下一页
        </button>
      </div>
      {selected && (
        <ArticleEditor
          key={selected.id}
          article={selected}
          projectId={projectId}
          api={api}
          onClose={() => setSelected(null)}
          onSaved={() => setVersion(version + 1)}
        />
      )}
    </div>
  );
}
