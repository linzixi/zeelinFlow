"""Read-only card builders extracted verbatim from ACE; no token or send functions."""
from __future__ import annotations
import json
import re
from typing import Any, Mapping, Sequence
from .canvas_defaults import SGM_STAGE_DEFAULTS
from ace_ext.sgm.profile import config_int, config_list, config_value, stage_config
class SgmFeishuError(RuntimeError):
    pass
_MAX_RELATED_LINKS = 100
_MAX_CARD_BYTES = 30000
def _text(value: Any, *, default: str = "") -> str:
    raw = default if value is None or value == "" else value
    return str(raw).replace("\x00", "").strip()

def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value

def _option_names(values: Sequence[Any] | None, selected: str) -> list[str]:
    names: list[str] = []
    for value in values or ():
        name = _text(value)[:80]
        if name and name not in names:
            names.append(name)
        if len(names) >= 30:
            break
    if selected and selected not in names:
        names.append(selected)
    return names

def _select(
    *,
    name: str,
    selected: str,
    options: Sequence[str],
    placeholder: str,
) -> dict[str, Any]:
    element: dict[str, Any] = {
        "tag": "select_static",
        "name": name,
        "placeholder": {"tag": "plain_text", "content": placeholder},
        "options": [
            {
                "text": {"tag": "plain_text", "content": option},
                "value": option,
            }
            for option in options
        ],
        "type": "default",
        "width": "fill",
        "disabled": False,
        "behaviors": [{"type": "callback", "value": {"select_static": "click"}}],
        "margin": "0px 0px 12px 0px",
    }
    if selected:
        element["initial_option"] = selected
    return element

def _business_car_model(article: Mapping[str, Any]) -> str:
    explicit = _text(article.get("brand_type") or article.get("car_model"))
    if explicit:
        return explicit
    business_tag = _json_value(article.get("business_tag"))
    if isinstance(business_tag, Mapping):
        second_level = business_tag.get("second_level")
        if isinstance(second_level, Sequence) and not isinstance(second_level, (str, bytes)):
            return ",".join(_text(value) for value in second_level if _text(value))
        return _text(second_level)
    return ""

def _question_type(article: Mapping[str, Any]) -> str:
    explicit = _text(article.get("question_type") or article.get("questionType"))
    if explicit:
        return explicit
    for field in ("news_second_tag", "news_third_tag"):
        value = _json_value(article.get(field))
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                candidate = _text(item)
                if candidate:
                    return candidate
        elif isinstance(value, Mapping):
            for item in value.values():
                candidate = _text(item)
                if candidate:
                    return candidate
        else:
            candidate = _text(value)
            if candidate and candidate not in {"[]", "{}", "null"}:
                return candidate
    return ""

def _media_attribute(article: Mapping[str, Any]) -> str:
    card_config = stage_config("card")
    raw_labels = config_value(
        card_config,
        "media_attribute_labels",
        SGM_STAGE_DEFAULTS["card"]["media_attribute_labels"],
    )
    labels = raw_labels if isinstance(raw_labels, Mapping) else {}
    media_label = str(labels.get("media") or "媒体舆情")
    small_media_label = str(labels.get("small_media") or "小号媒体舆情")
    attr = _text(article.get("media_attr"))
    if not attr:
        level = _text(article.get("custom_media_level"))
        attr = level if level.endswith("舆情") else f"{level}舆情" if level else ""
    if attr == media_label:
        organization = _text(article.get("media_organization"))
        followers = _integer(article.get("media_followers_count"))
        organizations = set(
            config_list(
                card_config,
                "media_organizations",
                tuple(SGM_STAGE_DEFAULTS["card"]["media_organizations"]),
            )
        )
        threshold = config_int(
            card_config,
            "large_account_followers",
            int(SGM_STAGE_DEFAULTS["card"]["large_account_followers"]),
            minimum=0,
            maximum=1_000_000_000,
        )
        if organization not in organizations and followers <= threshold:
            return small_media_label
    return attr

def _is_video(article: Mapping[str, Any]) -> bool:
    card_config = stage_config("card")
    video_platforms = set(
        config_list(
            card_config,
            "video_platforms",
            tuple(SGM_STAGE_DEFAULTS["card"]["video_platforms"]),
        )
    )
    video_platform_names = set(
        config_list(
            card_config,
            "video_platform_names",
            tuple(SGM_STAGE_DEFAULTS["card"]["video_platform_names"]),
        )
    )
    if _text(article.get("platform")) in video_platforms:
        return True
    if _text(article.get("platform_name")) in video_platform_names:
        return True
    videos = _json_value(article.get("news_video_urls"))
    if isinstance(videos, str):
        return bool(videos.strip() and videos.strip() not in {"[]", "{}"})
    return bool(videos)

def _safe_url(value: Any) -> str:
    url = (
        _text(value)
        .replace("<", "")
        .replace(">", "")
        .replace("\r", "")
        .replace("\n", "")[:500]
    )
    return url if url.startswith(("http://", "https://")) else ""

def _markdown_text(value: Any, *, limit: int) -> str:
    text = _text(value)[:limit]
    return re.sub(r"([\\`*_\[\]()<>~])", r"\\\1", text)

def _build_article_card(
    article: Mapping[str, Any],
    *,
    related_links: Sequence[Mapping[str, Any]] | None = None,
    url_http_code: int | None = None,
    media_type_options: Sequence[str] | None = None,
    question_type_options: Sequence[str] | None = None,
    video: bool | None = None,
) -> dict[str, Any]:
    """Build one card from an already selected set of related links."""
    article_id = _text(article.get("id") or article.get("articleId") or "0")[:64]
    title = _text(article.get("news_title") or article.get("title"), default="无标题")[:200]
    digest = _text(
        article.get("news_digest") or article.get("news_content"),
        default="无内容摘要",
    )
    if len(digest) > 200:
        digest = digest[:200] + "..."
    attr = _media_attribute(article)[:80]
    question_type = _question_type(article)[:80]
    embedded_media_options = article.get("media_type_options")
    embedded_question_options = article.get("question_type_options")
    media_options = _option_names(
        media_type_options
        or (
            embedded_media_options
            if isinstance(embedded_media_options, Sequence)
            and not isinstance(embedded_media_options, (str, bytes))
            else None
        ),
        attr,
    )
    question_options = _option_names(
        question_type_options
        or (
            embedded_question_options
            if isinstance(embedded_question_options, Sequence)
            and not isinstance(embedded_question_options, (str, bytes))
            else None
        ),
        question_type,
    )

    is_video = _is_video(article) if video is None else bool(video)
    card_config = stage_config("card")
    header = str(
        config_value(
            card_config,
            "video_header" if is_video else "standard_header",
            SGM_STAGE_DEFAULTS["card"]["video_header" if is_video else "standard_header"],
        )
    )
    raw_suffixes = config_value(
        card_config,
        "header_suffixes",
        SGM_STAGE_DEFAULTS["card"]["header_suffixes"],
    )
    suffixes = raw_suffixes if isinstance(raw_suffixes, Mapping) else {}
    code = _integer(url_http_code if url_http_code is not None else article.get("url_http_code"))
    if (
        _text(article.get("platform")) in set(config_list(
            card_config,
            "deleted_platforms",
            tuple(SGM_STAGE_DEFAULTS["card"]["deleted_platforms"]),
        ))
        and str(code) in set(config_list(
            card_config,
            "deleted_http_codes",
            tuple(SGM_STAGE_DEFAULTS["card"]["deleted_http_codes"]),
        ))
    ):
        header += str(suffixes.get("deleted") or "")
    follower_threshold = config_int(
        card_config, "large_account_followers", 50_000, minimum=0, maximum=1_000_000_000
    )
    if _integer(article.get("media_followers_count")) > follower_threshold:
        header += str(suffixes.get("large_account") or "")
    if (
        _integer(article.get("news_img_status")) == 1
        and _text(article.get("news_img_result")) in set(config_list(
            card_config,
            "image_positive_values",
            tuple(SGM_STAGE_DEFAULTS["card"]["image_positive_values"]),
        ))
    ):
        header += str(suffixes.get("configured_image") or "")
    if (
        _text(article.get("platform_name")) in set(config_list(
            card_config,
            "manual_push_platform_names",
            tuple(SGM_STAGE_DEFAULTS["card"]["manual_push_platform_names"]),
        ))
        and _text(article.get("douyin_url_code"))
        and bool(article.get("manual_push_exists"))
    ):
        header += str(suffixes.get("manual_push") or "")

    link_ids: list[str] = []
    link_display: list[str] = []
    for item in related_links or ():
        raw_link_id = item.get("id")
        if raw_link_id is None or raw_link_id == "":
            raw_link_id = item.get("article_id")
        link_id = _text(raw_link_id)[:64]
        name = _text(item.get("name"))[:100]
        if not name:
            name = "-".join(
                value
                for value in (
                    _text(item.get("platform_name")),
                    _text(item.get("media_name")),
                )
                if value
            )[:100] or "链接"
        url = _safe_url(item.get("url") or item.get("news_url"))
        if link_id:
            link_ids.append(link_id)
        display_name = _markdown_text(name, limit=100)
        link_display.append(f"{display_name}：<{url}>" if url else f"{display_name}：")

    source_url = "" if _text(article.get("platform_name")) in set(
        config_list(
            card_config,
            "hide_source_url_platform_names",
            tuple(SGM_STAGE_DEFAULTS["card"]["hide_source_url_platform_names"]),
        )
    ) else _safe_url(
        article.get("news_url") or article.get("url")
    )
    media_name = _text(article.get("platform_name"))[:100]
    author = _text(article.get("author") or article.get("media_name"))[:255]
    reply_count = max(0, _integer(article.get("news_comment_count")))
    question_desc = _text(
        article.get("question_desc")
        or article.get("problemDescription")
        or article.get("negativeExcerpt")
    )[:1000]
    elements: list[dict[str, Any]] = [
        {
            "tag": "input",
            "name": "biz_id",
            "label": {"tag": "plain_text", "content": "事件ID："},
            "default_value": article_id,
            "disabled": True,
            "width": "fill",
            "placeholder": {"tag": "plain_text", "content": "ID"},
        },
        {"tag": "markdown", "content": "**媒体属性：**"},
        _select(
            name="media_attr",
            selected=attr,
            options=media_options,
            placeholder="请选择媒体属性",
        ),
        {
            "tag": "markdown",
            "content": (
                f"**媒体名称：** {_markdown_text(media_name, limit=100)}\n"
                f"**作者：** {_markdown_text(author, limit=255)}\n"
                f"**链接时间：** {_markdown_text(article.get('news_posttime') or article.get('publishedAt'), limit=64)}\n"
                f"**回复：** {reply_count}"
            ),
        },
        {
            "tag": "input",
            "name": "car_model",
            "label": {"tag": "plain_text", "content": "品牌/车型："},
            "default_value": _business_car_model(article)[:255],
            "width": "fill",
            "placeholder": {"tag": "plain_text", "content": "请填写品牌/车型"},
        },
        {
            "tag": "input",
            "name": "question_desc",
            "label": {"tag": "plain_text", "content": "问题概述："},
            "input_type": "multiline_text",
            "rows": 4,
            "auto_resize": True,
            "default_value": question_desc,
            "width": "fill",
            "placeholder": {"tag": "plain_text", "content": "请描述问题概述"},
        },
        {"tag": "markdown", "content": "**问题分类：**"},
        _select(
            name="question_type",
            selected=question_type,
            options=question_options,
            placeholder="请选择问题分类",
        ),
        {
            "tag": "markdown",
            "content": (
                f"**链接地址：** {'<' + source_url + '>' if source_url else ''}\n"
                f"**文章标题：** {_markdown_text(title, limit=200)}"
            ),
        },
        {
            "tag": "input",
            "name": "news_digest",
            "label": {"tag": "plain_text", "content": "内容摘要："},
            "input_type": "multiline_text",
            "rows": 6,
            "auto_resize": True,
            "default_value": digest,
            "width": "fill",
            "placeholder": {"tag": "plain_text", "content": "请输入内容摘要"},
        },
        {
            "tag": "markdown",
            "content": "**相关链接：**\n" + ("\n".join(link_display) if link_display else "无"),
        },
        {
            "tag": "column_set",
            "flex_mode": "none",
            "background_style": "default",
            "horizontal_spacing": "default",
            "columns": [
                {
                    "tag": "column",
                    "width": "auto",
                    "vertical_align": "top",
                    "elements": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "标记为已处理"},
                            "type": "primary",
                            "action_type": "form_submit",
                            "name": "submit_button",
                            "value": {
                                "biz_id": article_id,
                                "extra_link_id": json.dumps(link_ids, ensure_ascii=False),
                            },
                        }
                    ],
                }
            ],
            "margin": "0px",
        },
    ]
    card = {
        "schema": "2.0",
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": header},
            "template": "red" if is_video else "green",
        },
        "body": {
            "elements": [
                {"tag": "form", "name": "lark_feedback_form", "elements": elements}
            ]
        },
    }
    return card

def select_article_related_links(
    article: Mapping[str, Any],
    *,
    related_links: Sequence[Mapping[str, Any]] | None = None,
    url_http_code: int | None = None,
    media_type_options: Sequence[str] | None = None,
    question_type_options: Sequence[str] | None = None,
    video: bool | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Select the largest ordered related-link prefix that fits one card.

    The database uses this same selector before leasing rows.  Consequently a
    link is never marked as consumed unless it is present in the sent card.
    """
    selected: list[Mapping[str, Any]] = []
    for related in (related_links or ())[:_MAX_RELATED_LINKS]:
        candidate = [*selected, related]
        card = _build_article_card(
            article,
            related_links=candidate,
            url_http_code=url_http_code,
            media_type_options=media_type_options,
            question_type_options=question_type_options,
            video=video,
        )
        if len(json.dumps(card, ensure_ascii=False).encode("utf-8")) > _MAX_CARD_BYTES:
            break
        selected.append(related)
    return tuple(selected)

def build_article_card(
    article: Mapping[str, Any],
    *,
    related_links: Sequence[Mapping[str, Any]] | None = None,
    url_http_code: int | None = None,
    media_type_options: Sequence[str] | None = None,
    question_type_options: Sequence[str] | None = None,
    video: bool | None = None,
) -> dict[str, Any]:
    """Build the legacy-compatible Schema 2.0 form for one article."""
    selected = select_article_related_links(
        article,
        related_links=related_links,
        url_http_code=url_http_code,
        media_type_options=media_type_options,
        question_type_options=question_type_options,
        video=video,
    )
    card = _build_article_card(
        article,
        related_links=selected,
        url_http_code=url_http_code,
        media_type_options=media_type_options,
        question_type_options=question_type_options,
        video=video,
    )
    if len(json.dumps(card, ensure_ascii=False).encode("utf-8")) > _MAX_CARD_BYTES:
        raise SgmFeishuError("飞书文章卡片超过 30KB 限制。")
    return card
