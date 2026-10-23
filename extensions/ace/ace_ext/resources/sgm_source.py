from __future__ import annotations

import hashlib
import html
import re
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from ace_ext.core.contracts import ArticleInput, Window
from ace_ext.core.errors import Unavailable

SCHEMES = (51, 52, 43, 55)
LOCAL = ZoneInfo("Asia/Shanghai")


def request_params(settings, window: Window, page: int) -> dict:
    timestamp = str(int(time.time()))
    values = {"appId": settings.sqty_app_id, "timestamp": timestamp}
    canonical = "&".join(
        f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(values.items())
    )
    sign = hashlib.md5(
        f"{canonical}&app_secret={settings.sqty_app_secret.get_secret_value()}".encode()
    ).hexdigest()
    return {
        **values,
        "app_id": settings.sqty_app_id,
        "sign": sign,
        "start_time": window.start.astimezone(LOCAL).strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": window.end.astimezone(LOCAL).strftime("%Y-%m-%d %H:%M:%S"),
        "page": page,
        "limit": 50,
        **{f"scheme_id[{index}]": value for index, value in enumerate(SCHEMES)},
    }


class SgmSource:
    """完整窗口分页采集；失败时不交付部分记录，签名和凭据不进入快照。"""

    def __init__(self, settings):
        self.settings = settings

    def fetch(self, node: dict, window: Window) -> tuple[list[ArticleInput], list[dict]]:
        if not self.settings.sqty_app_id or not self.settings.sqty_app_secret.get_secret_value():
            raise Unavailable("请配置上汽通用数据源凭据")
        if not self.settings.sqty_api_url.startswith("https://"):
            raise Unavailable("上汽通用数据源必须使用 HTTPS")
        rows, total, pages = [], None, 0
        with httpx.Client(timeout=60, trust_env=False) as client:
            for page in range(1, 201):
                payload = self._page(client, window, page)
                data = payload.get("data", {})
                batch, current = data.get("data"), data.get("total")
                if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
                    raise Unavailable("上汽通用分页格式错误")
                try:
                    current = int(current)
                except (ValueError, TypeError) as exc:
                    raise Unavailable("上汽通用缺少完整记录总数") from exc
                if current < 0 or (total is not None and current != total):
                    raise Unavailable("采集期间总数变化，请重跑同一时间窗")
                total, pages = current, page
                rows.extend(batch)
                if len(rows) >= total:
                    break
                if not batch:
                    raise Unavailable("分页提前结束，本轮数据不完整")
        if len(rows) != total:
            raise Unavailable("上汽通用数据未完整覆盖，本轮停止")
        usable = [row for row in rows if str(row.get("news_url") or "").strip()]
        articles = [to_article(row, window) for row in usable]
        unique = {row.url: row for row in articles}
        coverage = {
            "complete": True,
            "total": total,
            "fetched": len(rows),
            "pages": pages,
            "empty_url": len(rows) - len(usable),
            "duplicates": len(articles) - len(unique),
            "schemes": list(SCHEMES),
            "window": window.model_dump(mode="json"),
            "endpoint": self.settings.sqty_api_url,
            "unique": len(unique),
        }
        return list(unique.values()), [coverage]

    def _page(self, client, window, page):
        try:
            response = client.get(
                self.settings.sqty_api_url, params=request_params(self.settings, window, page)
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise Unavailable("上汽通用数据请求失败，请重试此窗口") from exc
        if not isinstance(payload, dict) or payload.get("code") != 10000:
            raise Unavailable("上汽通用接口未授权或拒绝本次查询")
        return payload


def clean_text(value) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip()


def source_time(value, fallback):
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=LOCAL)
    except ValueError:
        return fallback


def to_article(row: dict, window: Window) -> ArticleInput:
    url = str(row["news_url"]).strip()
    content = clean_text(row.get("news_content") or row.get("news_origin_content"))
    title = clean_text(row.get("news_title")) or "[源文章无标题]"
    if len(title) > 1000:
        content = title + "\n" + content
        title = title[:987] + "…[完整标题见正文]"
    return ArticleInput(
        source_id=hashlib.sha256(url.encode()).hexdigest(),
        title=title,
        url=url,
        source=str(row.get("media_name") or row.get("news_site") or "上汽通用定制接口"),
        content=content,
        published_at=source_time(row.get("news_posttime"), None),
        ingested_at=source_time(
            row.get("push_time") or row.get("create_time") or row.get("solr_create_time"),
            window.start,
        ),
        branch="sgm",
        raw=row,
    )
