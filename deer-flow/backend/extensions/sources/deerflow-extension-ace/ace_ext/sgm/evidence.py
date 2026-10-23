from __future__ import annotations

import re


def verified_quote(row: dict) -> bool:
    source = re.sub(r"\s+", "", row.get("title", "") + "\n" + row.get("content", ""))
    quotes = [
        re.sub(r"\s+", "", part) for part in row.get("news_dig", "").splitlines() if part.strip()
    ]
    return bool(quotes and all(part in source for part in quotes))


def clean_evidence(source: dict, fields: dict) -> dict:
    """未匹配原文的模型摘录不得进入卡片；保留 type=2 负面候选。"""
    if verified_quote({**source, **fields}):
        return {**fields, "extraction_status": "complete"}
    return {
        **fields,
        "news_dig": "",
        "extraction_status": "review_required",
        "decision": "review",
        "evidence_limit": "模型未提供可核对原文摘录，已清空摘录并保留负面候选待人工核验",
    }
