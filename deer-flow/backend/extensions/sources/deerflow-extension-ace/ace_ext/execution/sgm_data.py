from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select

from ace_ext.core.contracts import Envelope
from ace_ext.persistence import schema as s
from ace_ext.persistence.database import Scope, where_scope
from ace_ext.sgm.business import legacy_article, mapping, select_preview_records
from ace_ext.sgm.delivery import decide, validate_url
from ace_ext.sgm.evidence import clean_evidence, verified_quote
from ace_ext.sgm.profile import use_profile
from ace_ext.vendor.legacy_sgm import rules


def values(value):
    return rules._values(value)


def skip_reason(row):
    return rules._skip_reason(legacy_article(row))


def transform(row, stage):
    result, raw = dict(row), legacy_article(row)
    if stage == "normalize":
        result.update(
            fingerprint=rules._title_hash(raw),
            media_type=str(raw.get("platform_name") or row.get("source", "")),
        )
    elif stage == "prepare":
        reason = skip_reason(row)
        result.update(skip_reason=reason, assessment_status="skipped" if reason else "pending")
        if reason:
            result.update(decision="exclude", summary=reason, risk="low", sentiment="unknown")
    elif stage in {"route", "branch"}:
        video, _ = rules._is_video(raw)
        result["media_route"] = (
            "complete" if row.get("skip_reason") else "video" if video else "text"
        )
        if not video:
            result["sis_status"] = "not_required"
    elif stage == "mapping":
        return mapping(row)
    elif stage == "policy":
        evidence = verified_quote(row)
        return decide(row if evidence else clean_evidence(row, row), evidence=evidence)
    return result


def profile(task, articles):
    with articles.db.transaction() as connection:
        graph = connection.execute(
            select(s.runs.c.graph).where(s.runs.c.id == task["run_id"])
        ).scalar_one()
    aliases = {
        "normalize": "normalize",
        "prepare": "dispatch",
        "route": "media_route",
        "transcription": "sis",
        "mapping": "classify",
        "related": "aggregate",
        "policy": "decision",
        "checkpoint": "retry",
        "preview": "card",
        "receipt": "delivery",
    }
    return {
        aliases.get(n["config"].get("sgm_data"), n["config"].get("sgm_stage", "")): n["config"]
        for n in graph["nodes"]
    }


def execute(task, payload, articles, settings=None):
    with use_profile(profile(task, articles)):
        return execute_scoped(task, payload, articles, settings)


def execute_scoped(task, payload, articles, settings):
    stage = task["node"]["config"].get("sgm_data")
    records = [transform(row, stage) for row in payload.get("records", [])]
    if stage == "transcription":
        from ace_ext.sgm.transcription import execute as transcribe

        records = transcribe(articles.db, settings, task, records)
    if stage == "related":
        records = related(records, task, articles)
    if stage == "policy":
        records = [validate_url(settings, row) for row in records]
    artifacts = payload.get("artifacts", [])
    if stage == "preview":
        records, cards = select_preview_records(records)
        artifacts = [
            {
                "name": "sgm-feishu-preview.json",
                "mimeType": "application/json",
                "content": json.dumps(
                    {"preview_only": True, "cards": cards}, ensure_ascii=False, indent=2
                ),
            }
        ]
    if stage == "quality":
        quality(records, artifacts)
    if stage == "receipt":
        receipt = {
            "mode": "preview",
            "external_messages_sent": 0,
            "source_revision": 209,
            "run_id": task["run_id"],
            "items": [
                {
                    "article_id": r["id"],
                    "effect_key": f"sgm:{task['project_id']}:{r['id']}:feishu-card",
                    "would_send": bool(r.get("preview_eligible") and not r.get("related_to")),
                    "related_to": r.get("related_to"),
                    "delay_seconds": r.get("delivery_delay_seconds", 0),
                    "feishu_push_status": 0,
                    "delivered": False,
                }
                for r in records
            ],
        }
        artifacts = [
            *artifacts,
            {
                "name": "sgm-preview-receipt.json",
                "mimeType": "application/json",
                "content": json.dumps(receipt, ensure_ascii=False, indent=2),
            },
        ]
    context = {
        "preview_only": True,
        "delivered": False,
        "source_revision": 209,
        "hasItems": bool(records),
        "stage": stage,
    }
    if stage in {"route", "branch"}:
        routes = {r["id"]: r["media_route"] for r in records}
        context.update(route=sorted(set(routes.values())), record_routes={"route": routes})
    return Envelope(
        records=records,
        artifacts=artifacts,
        summary=f"{task['node']['title']}：{len(records)}篇",
        context=context,
    )


def quality(records, artifacts):
    for artifact in artifacts:
        if artifact.get("name") != "sgm-feishu-preview.json":
            continue
        for preview in json.loads(artifact["content"])["cards"]:
            card = preview["card"]
            if card.get("schema") != "2.0" or not card.get("body", {}).get("elements"):
                raise ValueError("预览卡片结构不完整")
            if len(json.dumps(card, ensure_ascii=False).encode()) > 30000:
                raise ValueError("预览卡片超过原平台30KB限制")
    if any(row.get("delivered") for row in records):
        raise ValueError("本地验收不应包含真实发送标记")


def related(records, task, articles):
    scope = Scope(task["tenant_id"], task["context"]["owner_id"])
    end = datetime.fromisoformat(task["context"]["window"]["end"]).timestamp()
    with articles.db.transaction() as connection:
        history = [
            dict(row["data"], id=row["id"])
            for row in connection.execute(
                select(s.articles).where(
                    where_scope(s.articles, scope, task["project_id"]),
                    s.articles.c.mode == task["context"]["mode"],
                    s.articles.c.deleted_at.is_(None),
                    s.articles.c.ingested_at >= end - 86400,
                    s.articles.c.ingested_at <= end,
                )
            ).mappings()
        ]
    combined = {r["id"]: r for r in [*history, *records]}
    for row in records:
        fingerprint = row.get("fingerprint")
        candidates = [
            other
            for other in combined.values()
            if fingerprint
            and other.get("fingerprint") == fingerprint
            and other.get("url") != row["url"]
            and rules._delivery_open(legacy_article(other))
        ]
        row["related_links"] = [
            {
                "id": r["id"],
                "url": r["url"],
                "platform_name": r.get("raw", {}).get("platform_name", ""),
                "media_name": r.get("source", ""),
            }
            for r in candidates[:100]
        ]
        row["related_urls"] = [r["url"] for r in row["related_links"]]
        row["related_to"] = None
    return records
