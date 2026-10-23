import test from "node:test";
import assert from "node:assert/strict";
import { articleChanges } from "./articleDraft";
import type { Article, ArticlePatch } from "../../lib/models";

test("review-only edits do not freeze automatic sentiment or submit an unchanged blank title", () => {
  const draft: ArticlePatch = { revision: 3, title: " ", summary: "模型说明", sentiment: "negative",
    risk: "medium", review_status: "watching", tags: ["车型"], note: "核验" };
  const article = { revision: 3, risk: "medium", review_status: "pending",
    data: { ...draft, review_status: "pending" } } as unknown as Article;
  assert.deepEqual(articleChanges(article, draft), { revision: 3, review_status: "watching", note: "核验" });
  assert.equal(articleChanges(article, { ...draft, sentiment: "neutral" }).sentiment, "neutral");
});
