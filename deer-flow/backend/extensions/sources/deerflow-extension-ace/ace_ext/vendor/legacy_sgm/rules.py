"""Verbatim ACE rules; stage configuration is supplied through a ContextVar."""
from __future__ import annotations
import json
import re
import hashlib
from typing import Any, Mapping
from ace_ext.sgm.profile import config_bool, config_list, config_value, stage_config
from .sis import extract_first_video_url
_CHINESE = re.compile(r"[\u4e00-\u9fff]")
_VIDEO_PLATFORMS = {"video", "media_toutiao"}
def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default

def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped in {"[]", "{}", "null"}:
            return []
        try:
            return _values(json.loads(stripped))
        except (TypeError, ValueError):
            return [stripped]
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_values(item))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_values(item))
        return result
    return [str(value)]

def _delivery_open(article: Mapping[str, Any]) -> bool:
    policy = stage_config("decision") or stage_config("dispatch")
    fields = config_list(
        policy,
        "delivery_status_fields",
        ("feishu_push_status", "feishu_callback_status", "feishu_link_status"),
    )
    return all(
        _integer(article.get(field)) == 0
        for field in fields
    )

def _skip_reason(article: Mapping[str, Any]) -> str:
    policy = stage_config("dispatch")
    if not _delivery_open(article):
        return "already-pushed-or-related"
    first_tag_field = str(config_value(policy, "first_tag_field", "news_first_tag") or "").strip()
    first_tags = _values(article.get(first_tag_field)) if first_tag_field else []
    if config_bool(policy, "require_first_tag", True) and not first_tags:
        return "missing-first-tag"
    irrelevant = set(config_list(policy, "irrelevant_first_tags", ("无关信息",)))
    if first_tags and first_tags[0] in irrelevant:
        return "irrelevant-first-tag"
    platform_field = str(config_value(policy, "platform_field", "platform") or "platform")
    origin_field = str(config_value(policy, "origin_field", "news_is_origin") or "news_is_origin")
    platform = str(article.get(platform_field) or "")
    is_origin = _integer(article.get(origin_field)) == 1
    if platform in set(config_list(policy, "original_only_platforms", ("weibo", "media_toutiao"))) and not is_origin:
        return f"{platform}-repost-excluded"
    reply_field = str(config_value(policy, "reply_field", "is_reply") or "is_reply")
    if config_bool(policy, "exclude_replies", True) and _integer(article.get(reply_field)) == 1:
        return "reply-excluded"
    evidence = "".join(
        str(article.get(field) or "")
        for field in config_list(policy, "text_fields", ("news_title", "news_content"))
    )
    if config_bool(policy, "require_chinese", True) and not _CHINESE.search(evidence):
        return "no-chinese-text"
    return ""

def _is_video(article: Mapping[str, Any]) -> tuple[bool, str]:
    policy = stage_config("media_route")
    platform_field = str(config_value(policy, "platform_field", "platform") or "platform")
    video_url_field = str(config_value(policy, "video_url_field", "news_video_urls") or "news_video_urls")
    platform = str(article.get(platform_field) or "")
    video_url = extract_first_video_url(article.get(video_url_field)) or ""
    video_platforms = set(config_list(policy, "video_platforms", tuple(_VIDEO_PLATFORMS)))
    return platform in video_platforms and bool(video_url), video_url

def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped in {"[]", "{}", "null"}:
            return []
        try:
            return _string_values(json.loads(stripped))
        except (TypeError, ValueError):
            return [stripped]
    if isinstance(value, Mapping):
        values: list[str] = []
        for item in value.values():
            values.extend(_string_values(item))
        return values
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_string_values(item))
        return values
    return [str(value)]

def _sina_delivery_allowed(article: Mapping[str, Any]) -> bool:
    policy = stage_config("delivery")
    if not config_bool(policy, "sina_filter_enabled", True):
        return True
    platform_names = set(
        config_list(policy, "sina_platform_names", ("新浪新闻", "新浪网"))
    )
    if str(article.get("platform_name") or "").strip() not in platform_names:
        return True
    allowed_tags = set(
        config_list(
            policy,
            "sina_allowed_tags",
            ("售后服务质量", "产品质量", "低价信息"),
        )
    )
    tags = {
        *_string_values(article.get("news_second_tag")),
        *_string_values(article.get("news_third_tag")),
    }
    summary = str(article.get("question_desc") or "")
    summary_terms = config_list(policy, "sina_summary_terms", ("低价信息",))
    return bool(tags & allowed_tags) or any(term in summary for term in summary_terms)

def _title_hash(record: Mapping[str, Any]) -> str:
    chinese_title = "".join(re.findall(r"[\u4e00-\u9fff]", str(record.get("news_title") or record.get("title") or "")))
    content = "".join(re.findall(r"[\u4e00-\u9fff]", str(record.get("news_content") or "")))[:20]
    return hashlib.md5((chinese_title + content).encode("utf-8")).hexdigest()
