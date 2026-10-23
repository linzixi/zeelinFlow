from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .gsdata_es import EsGatewayClient, EsGatewayError, EsNewsService, NewsSearchParams


_RECOUNT_BATCH_SIZE = 20
_RECOUNT_ATTEMPTS = 3


def completed_window(config: dict[str, Any], now: datetime | None = None) -> tuple[str, str]:
    zone = ZoneInfo(str(config.get("timezone", "Asia/Shanghai")))
    now = now.astimezone(zone) if now is not None else datetime.now(zone)
    if "weekday" not in config or "hour" not in config:
        raise ValueError("完整周期必须显式配置 weekday 和 hour，不从项目示例推定截止时间。")
    weekday = int(config["weekday"])
    hour = int(config["hour"])
    days = int(config.get("days", 7))
    if not 0 <= weekday <= 6 or not 0 <= hour <= 23 or not 1 <= days <= 31:
        raise ValueError("完整周期的星期、小时或天数无效。")
    end = (now - timedelta(days=(now.weekday() - weekday) % 7)).replace(hour=hour, minute=0, second=0, microsecond=0)
    if end > now:
        end -= timedelta(days=7)
    return tuple(value.strftime("%Y-%m-%d %H:%M:%S") for value in (end - timedelta(days=days), end))


def query_window(config: dict[str, Any], now: datetime | None = None) -> tuple[str, str]:
    mode = config.get("mode", "completed")
    if mode == "completed":
        return completed_window(config, now)
    if mode != "recent_days":
        raise ValueError("时间窗口模式必须为 completed 或 recent_days。")
    days = int(config.get("days", 7))
    if not 1 <= days <= 31:
        raise ValueError("最近自然日天数必须为 1–31。")
    zone = ZoneInfo(str(config.get("timezone", "Asia/Shanghai")))
    end = now.astimezone(zone) if now is not None else datetime.now(zone)
    start = (end - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def _body(response: dict[str, Any]) -> dict[str, Any]:
    body = response
    for _depth in range(4):
        if body.get("error") or body.get("timed_out") or body.get("_shards", {}).get("failed", 0):
            raise EsGatewayError("ES 查询超时或分片失败，不能使用部分结果。")
        if "aggregations" in body or "aggs" in body:
            return {**body, "aggregations": body.get("aggregations", body.get("aggs"))}
        nested = next((body[key] for key in ("data", "result") if isinstance(body.get(key), dict)), None)
        if nested is None:
            break
        body = nested
    raise EsGatewayError("ES 未返回有效聚合结果。")


def cluster_statement(service: EsNewsService, params: NewsSearchParams, *, limit: int, rank_by: str, match_fields: list[str],
                      sim_hash_field: str = "news_sim_hash", representative_sort: str = "relevance",
                      highlight_fields: list[str] | None = None) -> dict[str, Any]:
    if not 1 <= limit <= 500 or rank_by not in {"relevance", "propagation", "latest"}:
        raise ValueError("聚合条数必须为 1–500，排序必须为 relevance、propagation 或 latest。")
    if not match_fields or any(not isinstance(field, str) or not field.strip() for field in match_fields):
        raise ValueError("必须配置关键词匹配字段。")
    if sim_hash_field not in {"news_sim_hash", "news_sim_hash.hash"}:
        raise ValueError("相似哈希字段必须为 news_sim_hash 或 news_sim_hash.hash。")
    sorts = {"relevance": [{"_score": "desc"}, {"news_posttime": "desc"}],
             "earliest": [{"news_posttime": "asc"}], "latest": [{"news_posttime": "desc"}]}
    if representative_sort not in sorts:
        raise ValueError("代表文章排序必须为 relevance、earliest 或 latest。")
    highlight_fields = highlight_fields or []
    if not isinstance(highlight_fields, list) or any(not isinstance(field, str) or field not in {"news_content", "news_origin_content", "news_ocr", "news_ocr_content"} for field in highlight_fields):
        raise ValueError("全文高亮字段必须是支持的正文或 OCR 字段列表。")
    # Apply keywords only to the configured match fields. A second implicit
    # full-text condition incorrectly excludes publisher/account searches.
    from dataclasses import replace
    statement = service.build_query(replace(params, keywords=()), page_size=1)
    groups = [group.strip() for expression in params.keywords for group in expression.split("|") if group.strip()]
    if not groups:
        raise ValueError("关键词不能为空。")
    if any("(" in group or ")" in group or any(not term.strip() for term in group.split("+")) for group in groups):
        raise ValueError("关键词仅支持已展开的 OR 词组及组内 + AND；括号表达式请先展开。")
    scored = {"bool": {"should": [{"bool": {"must": [
        {"multi_match": {"query": term.strip(), "type": "phrase", "fields": match_fields}}
        for term in group.split("+")
    ]}} for group in groups], "minimum_should_match": 1}}
    statement["query"] = {"bool": {"filter": [statement["query"]], "must": [scored]}}
    for key in ("from", "sort", "collapse"):
        statement.pop(key, None)
    statement["size"] = 0
    statement["track_total_hits"] = True
    has_hash = {"bool": {"filter": [{"exists": {"field": sim_hash_field}}], "must_not": [{"term": {"news_sim_hash": ""}}]}}
    fields = list(dict.fromkeys([*service.NEWS_LIST_BACK_FIELDS, "news_sim_hash", "news_content", "news_origin_content", "news_ocr", "news_ocr_content", "news_local_url", "media_id", "media_name", "media_level"]))
    representative = {"size": 1, "_source": fields, "sort": sorts[representative_sort]}
    if highlight_fields:
        representative["highlight"] = {"require_field_match": False, "pre_tags": [""], "post_tags": [""],
                                        "fields": {field: {"number_of_fragments": 0} for field in highlight_fields}}
    statement["aggs"] = {
        "with_hash": {"filter": has_hash, "aggs": {"clusters": {
            "terms": {"field": sim_hash_field, "size": limit, "shard_size": max(2000, limit * 5),
                      "order": [{ {"relevance": "best_score", "propagation": "_count", "latest": "latest_time"}[rank_by]: "desc"}, {"_key": "asc"}], "show_term_doc_count_error": True},
            "aggs": {"best_score": {"max": {"script": {"source": "_score"}}},
                     "latest_time": {"max": {"field": params.time_field}},
                     "representative": {"top_hits": representative}},
        }}},
        "without_hash": {"filter": {"bool": {"must_not": [has_hash]}}},
    }
    return statement


def search_clusters(client: EsGatewayClient, service: EsNewsService, params: NewsSearchParams, *, limit: int, rank_by: str, match_fields: list[str],
                    sim_hash_field: str = "news_sim_hash", representative_sort: str = "relevance",
                    highlight_fields: list[str] | None = None,
                    on_recount_batch: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    statement = cluster_statement(service, params, limit=limit, rank_by=rank_by, match_fields=match_fields,
                                  sim_hash_field=sim_hash_field, representative_sort=representative_sort, highlight_fields=highlight_fields)
    response = _body(client.search(statement, index=params.index, start_time=params.start_time, end_time=params.end_time, time_field=params.time_field))
    aggregation = response["aggregations"]
    clusters = aggregation["with_hash"]["clusters"]
    buckets = clusters["buckets"]
    if not isinstance(buckets, list) or len(buckets) > limit:
        raise EsGatewayError("ES 相似簇数量异常。")
    counts: dict[str, Any] = {}
    recount_batches = (len(buckets) + _RECOUNT_BATCH_SIZE - 1) // _RECOUNT_BATCH_SIZE
    for offset in range(0, len(buckets), _RECOUNT_BATCH_SIZE):
        batch = buckets[offset:offset + _RECOUNT_BATCH_SIZE]
        expected_values = [bucket["key"] for bucket in batch]
        expected_keys = {str(value) for value in expected_values}
        selected = None
        batch_counts = None
        last_error = ""
        # A terms aggregation can briefly report shard approximation errors even
        # when every requested hash is present. Retry the exact request with a
        # larger shard_size before failing the run; incomplete counts must never
        # be sent downstream as if they were exact.
        for attempt in range(_RECOUNT_ATTEMPTS):
            recount = {"size": 0, "query": deepcopy(statement["query"]), "aggs": {"selected": {
                "terms": {"field": sim_hash_field, "include": expected_values,
                          "size": len(batch), "shard_size": (len(batch) if attempt == 0
                                                               else max(1000, len(batch) * 5 * (attempt + 1))),
                          "order": {"_key": "asc"}, "show_term_doc_count_error": True},
                    "aggs": {"media": {"terms": {"field": "media_id", "size": 1000,
                                  "show_term_doc_count_error": True},
                                  "aggs": {"sample": {"top_hits": {"size": 1, "_source": ["media_id", "media_name", "media_level"]}}}},
                          "missing_media": {"missing": {"field": "media_id"}}}}}}
            try:
                selected = _body(client.search(recount, index=params.index, start_time=params.start_time,
                                               end_time=params.end_time, time_field=params.time_field))["aggregations"]["selected"]
                returned = selected.get("buckets")
                if isinstance(returned, list):
                    candidate = {str(bucket["key"]): bucket for bucket in returned}
                    if (len(candidate) != len(returned) or set(candidate) != expected_keys
                            or set(counts).intersection(candidate)):
                        raise EsGatewayError("入选相似簇缺少复核计数，或返回了重复、非请求哈希。")
                    if (selected.get("sum_other_doc_count", -1) == 0
                            and selected.get("doc_count_error_upper_bound", -1) == 0):
                        batch_counts = candidate
                        break
                    if len(batch) == 1:
                        raise EsGatewayError(
                            "入选相似簇复核计数不完整（单个哈希复核仍有分片误差，"
                            f"遗漏文档数={selected.get('sum_other_doc_count', '缺失')}，"
                            f"计数误差上限={selected.get('doc_count_error_upper_bound', '缺失')}）。"
                        )
                last_error = (
                    f"遗漏文档数={selected.get('sum_other_doc_count', '缺失')}，"
                    f"计数误差上限={selected.get('doc_count_error_upper_bound', '缺失')}，"
                    f"返回哈希数={len(returned) if isinstance(returned, list) else '无效'}"
                )
            except EsGatewayError as exc:
                # A returned bucket mismatch is a data-integrity failure, not a
                # transient shard approximation; stop immediately so no
                # partial batch can be mistaken for a complete result. A
                # gateway response that explicitly reports timed-out/failed
                # shards is retryable before we give up.
                if str(exc) != "ES 查询超时或分片失败，不能使用部分结果。":
                    raise
                last_error = str(exc)
            except Exception as exc:  # provider and test-double transport errors are retryable here
                last_error = str(exc)
            if attempt + 1 < _RECOUNT_ATTEMPTS:
                time.sleep(0.15 * (attempt + 1))
        if batch_counts is None:
            raise EsGatewayError(
                "入选相似簇复核计数不完整或哈希集合不一致（已重试 %d 次：%s）。"
                % (_RECOUNT_ATTEMPTS, last_error or "未知错误")
            )
        counts.update(batch_counts)
        if on_recount_batch is not None:
            on_recount_batch(offset // _RECOUNT_BATCH_SIZE + 1, recount_batches)
    records = []
    for bucket in buckets:
        hits = bucket["representative"]["hits"]["hits"]
        if not hits or str(bucket["key"]) not in counts:
            raise EsGatewayError("入选相似簇缺少代表文章或复核计数。")
        source = dict(hits[0]["_source"])
        content_sources = {}
        highlights = hits[0].get("highlight", {})
        if not isinstance(highlights, dict):
            raise EsGatewayError("ES 正文高亮响应格式无效。")
        for field in highlight_fields or []:
            if isinstance(source.get(field), str) and source[field].strip():
                content_sources[field] = "source"
                continue
            fragments = highlights.get(field, [])
            if not isinstance(fragments, list) or len(fragments) > 1 or any(not isinstance(fragment, str) for fragment in fragments):
                raise EsGatewayError("ES 全文高亮必须返回单个完整字段，不能把多个片段当作全文。")
            if fragments and fragments[0].strip():
                source[field] = fragments[0]
                content_sources[field] = "whole_field_highlight"
            else:
                content_sources[field] = "missing"
        if highlight_fields:
            source["es_content_sources"] = content_sources
        count = counts[str(bucket["key"])]
        media = count["media"]
        media_complete = (media.get("sum_other_doc_count", 0) == 0 and media.get("doc_count_error_upper_bound", -1) == 0
                          and count["missing_media"]["doc_count"] == 0 and all(entry.get("key") not in (None, "") for entry in media["buckets"]))
        source.update({
            "record_id": str(source.get("news_uuid") or bucket["key"]),
            "sim_hash": bucket["key"], "sim_hash_field": sim_hash_field, "retrieval_score": bucket["best_score"]["value"],
            "cluster_document_count": bucket.get("doc_count"),
            "cluster_doc_count_error_upper_bound": bucket.get("doc_count_error_upper_bound"),
            "cluster_other_documents": max(0, bucket["doc_count"] - 1) if type(bucket.get("doc_count")) is int else None,
            "matched_document_count": count["doc_count"], "other_matched_documents": max(0, count["doc_count"] - 1),
            "matched_media_count": len(media["buckets"]) if media_complete else None,
            "matched_media": [entry["sample"]["hits"]["hits"][0]["_source"] for entry in media["buckets"]],
            "media_complete": media_complete,
        })
        records.append(source)
    total = response.get("hits", {}).get("total")
    if isinstance(total, dict):
        if total.get("relation", "eq") != "eq":
            raise EsGatewayError("ES 未返回精确匹配文档总数。")
        total = total.get("value", 0)
    if type(total) is not int or total < len(records):
        raise EsGatewayError("ES 匹配文档总数缺失或与返回记录不一致。")
    return {"records": records, "total": total, "coverage": {
        "candidateLimit": limit, "rankBy": rank_by, "simHashField": sim_hash_field, "representativeSort": representative_sort,
        "highlightFields": highlight_fields or [], "missingHashDocuments": aggregation["without_hash"]["doc_count"],
        "sumOtherDocCount": clusters.get("sum_other_doc_count"), "docCountErrorUpperBound": clusters.get("doc_count_error_upper_bound"),
        "countScope": "同一关键词、平台、时间范围内的相同哈希记录；不是全网事件传播量。",
        "recountBatchSize": _RECOUNT_BATCH_SIZE,
        "recountRequests": (len(buckets) + _RECOUNT_BATCH_SIZE - 1) // _RECOUNT_BATCH_SIZE,
        "countSnapshot": "代表文章与各批复核计数来自独立查询，可能受延迟入库影响。",
        "complete": False,
    }}
