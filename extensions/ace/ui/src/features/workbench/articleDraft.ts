import type { Article, ArticleChanges, ArticlePatch } from "../../lib/models";

export function articleChanges(article: Article, draft: ArticlePatch): ArticleChanges {
  const original = { ...article.data, risk: article.risk, review_status: article.review_status };
  const entries = Object.entries(draft).filter(([key, value]) =>
    key === "revision" || key === "note" ||
    JSON.stringify(value) !== JSON.stringify(original[key as keyof typeof original]),
  );
  return { revision: draft.revision, note: draft.note, ...Object.fromEntries(entries) };
}
