import { useEffect, useRef, useState } from "react";
import { X, Save } from "lucide-react";
import type { Api } from "../../lib/api";
import type { Article, ArticlePatch, ArticleRevision } from "../../lib/models";
import { formatTime, REVIEW, RISK } from "../../lib/models";
import { articleChanges } from "./articleDraft";

interface Props {
  article: Article;
  projectId: string;
  api: Api;
  onClose(): void;
  onSaved(): void;
}
export default function ArticleEditor({ article, projectId, api, onClose, onSaved }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  const [draft, setDraft] = useState<ArticlePatch>({
    revision: article.revision,
    title: article.data.title,
    summary: article.data.summary,
    sentiment: article.data.sentiment,
    risk: article.risk,
    review_status: article.review_status,
    tags: article.data.tags,
    note: "",
    predicted_car: article.data.predicted_car,
    problem_content: article.data.problem_content,
    news_dig: article.data.news_dig,
  });
  const [history, setHistory] = useState<ArticleRevision[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    api
      .articleHistory(projectId, article.id)
      .then((result) => {
        if (active) setHistory(result);
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      });
    return () => {
      active = false;
    };
  }, [api, article.id, projectId]);
  async function save() {
    setBusy(true);
    setError("");
    try {
      await api.updateArticle(projectId, article, articleChanges(article, draft));
      onSaved();
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog ref={dialog} className="drawer-backdrop" onCancel={onClose} aria-label="编辑预警文章">
      <section className="article-editor">
        <div className="inspector-header">
          <div>
            <small>文章修订 · 版本 {article.revision}</small>
            <h2>核验与修改</h2>
          </div>
          <button aria-label="关闭文章编辑" className="icon-button" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <label>
          文章标题
          <input
            autoFocus
            value={draft.title}
            onChange={(event) => setDraft({ ...draft, title: event.target.value })}
          />
        </label>
        <div className="article-source">
          {article.data.source} · {formatTime(article.data.published_at)}
        </div>
        <div className="original-content">{article.data.content || "暂无正文"}</div>
        {article.branch === "sgm" && <>
          {article.data.sis_status === "awaiting_service" && <p role="status">视频待转写，当前判断仅依据已有标题和正文。</p>}
          {article.data.evidence_limit && <p role="status">{article.data.evidence_limit}</p>}
          <label>涉及车型<input value={draft.predicted_car ?? ""} onChange={(event) => setDraft({ ...draft, predicted_car: event.target.value })} /></label>
          <label>问题概述<input value={draft.problem_content ?? ""} onChange={(event) => setDraft({ ...draft, problem_content: event.target.value })} /></label>
          <label>负面原文摘录<textarea rows={4} value={draft.news_dig ?? ""} onChange={(event) => setDraft({ ...draft, news_dig: event.target.value })} /></label>
        </>}
        <label>
          研判摘要
          <textarea
            rows={5}
            value={draft.summary}
            onChange={(event) => setDraft({ ...draft, summary: event.target.value })}
          />
        </label>
        <div className="form-row">
          <label>
            风险等级
            <select
              value={draft.risk}
              onChange={(event) => setDraft({ ...draft, risk: event.target.value })}
            >
              {Object.entries(RISK).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            情感
            <select
              value={draft.sentiment}
              onChange={(event) => setDraft({ ...draft, sentiment: event.target.value })}
            >
              <option value="unknown">未判断</option>
              <option value="negative">负面</option>
              <option value="neutral">中性</option>
              <option value="positive">正面</option>
            </select>
          </label>
        </div>
        <label>
          处理状态
          <select
            value={draft.review_status}
            onChange={(event) => setDraft({ ...draft, review_status: event.target.value })}
          >
            {Object.entries(REVIEW).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          标签
          <input
            value={draft.tags.join(", ")}
            onChange={(event) =>
              setDraft({
                ...draft,
                tags: event.target.value
                  .split(/[,，]/)
                  .map((item) => item.trim())
                  .filter(Boolean),
              })
            }
          />
        </label>
        <label>
          修订说明
          <textarea
            rows={2}
            placeholder="记录核验依据与修改原因…"
            value={draft.note}
            onChange={(event) => setDraft({ ...draft, note: event.target.value })}
          />
        </label>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        <button
          className="primary"
          disabled={busy || (draft.title !== article.data.title && !draft.title.trim())}
          onClick={() => void save()}
        >
          <Save size={15} />
          {busy ? "保存中…" : "保存修订"}
        </button>
        <details className="history-list">
          <summary>修订历史 · {history.length}</summary>
          {history.map((item) => (
            <div key={item.id}>
              <strong>版本 {item.revision}</strong>
              <span>{formatTime(item.created_at)}</span>
              <p>{item.reason}</p>
            </div>
          ))}
        </details>
      </section>
    </dialog>
  );
}
