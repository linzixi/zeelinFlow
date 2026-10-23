from __future__ import annotations

import json

from ace_ext.vendor.legacy_sgm import card, rules

PROBLEMS = {
    1: "产品质量",
    2: "技术支持",
    3: "售后服务质量",
    4: "配件供应",
    5: "销售服务质量",
    6: "政策及补贴",
    7: "销售其他问题",
    8: "产品体验",
    9: "非正常营运",
    10: "企业舆情",
    11: "风险案例",
}


def legacy_article(row: dict) -> dict:
    raw = dict(row.get("raw", {}))
    raw.update(
        id=row.get("id", ""),
        news_url=row.get("url", ""),
        news_title=raw.get("news_title", row.get("title", "")),
        news_content=row.get("content", ""),
    )
    aliases = {
        "predicted_car": "brand_type",
        "question_type": "question_type",
        "problem_content": "question_desc",
        "news_dig": "news_digest",
        "media_attribute": "media_attr",
        "url_http_code": "url_http_code",
    }
    for key, legacy in aliases.items():
        if row.get(key):
            raw[legacy] = row[key]
    return raw


def mapping(row: dict) -> dict:
    raw = legacy_article(row)
    brand = row.get("predicted_car", "") or card._business_car_model(raw)
    if not brand:
        hits = raw.get("hit_keywords", {})
        if isinstance(hits, str):
            try:
                hits = json.loads(hits)
            except ValueError:
                hits = {}
        if isinstance(hits, dict):
            brand = ",".join(hits)
    category = card._question_type(raw)
    return {
        **row,
        "predicted_car": brand,
        "question_type": category,
        "media_attribute": card._media_attribute(raw),
        "tags": list(
            dict.fromkeys(
                [
                    *row.get("tags", []),
                    *rules._string_values(raw.get("news_second_tag")),
                    *rules._string_values(raw.get("news_third_tag")),
                ]
            )
        ),
        "problem_codes": [k for k, v in PROBLEMS.items() if v == category]
        or row.get("problem_codes", []),
    }


def build_preview(row: dict) -> dict:
    raw = legacy_article(row)
    result = card.build_article_card(
        raw,
        related_links=row.get("related_links", []),
        media_type_options=["用户舆情", "媒体舆情", "小号媒体舆情"],
        question_type_options=list(PROBLEMS.values()),
        video=row.get("media_route") == "video",
    )
    return {
        "article_id": row["id"],
        "card": result,
        "preview_only": True,
        "review_required": row.get("decision") == "review",
        "evidence_limit": row.get("evidence_limit", ""),
        "related_urls": row.get("related_urls", []),
    }


def select_preview_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """只在实际放入卡片的链接间做本轮预览去重，不写真实推送或占用状态。"""
    reserved, previews, updated = {}, [], []
    for source in records:
        row = {**source, "related_to": reserved.get(source["id"])}
        if row.get("preview_eligible") and not row["related_to"]:
            candidates = [
                link for link in row.get("related_links", []) if link["id"] not in reserved
            ]
            selected = card.select_article_related_links(
                legacy_article(row),
                related_links=candidates,
                url_http_code=404,
                media_type_options=["用户舆情", "媒体舆情", "小号媒体舆情"],
                question_type_options=list(PROBLEMS.values()),
                video=row.get("media_route") == "video",
            )
            row["related_links"] = list(selected)
            row["related_urls"] = [link["url"] for link in selected]
            reserved[row["id"]] = row["id"]
            reserved.update({link["id"]: row["id"] for link in selected})
            previews.append(build_preview(row))
        updated.append(row)
    return updated, previews
