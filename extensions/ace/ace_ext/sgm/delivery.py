from __future__ import annotations

import hashlib
import time

import httpx

from ace_ext.core.errors import Unavailable
from ace_ext.sgm.business import legacy_article
from ace_ext.sgm.profile import config_int, stage_config
from ace_ext.vendor.legacy_sgm import rules


def decide(row: dict, *, evidence: bool) -> dict:
    raw = legacy_article(row)
    eligible = row.get("sentiment") == "negative" and not row.get("skip_reason")
    eligible = eligible and rules._delivery_open(raw) and rules._sina_delivery_allowed(raw)
    delivery = stage_config("delivery")
    delay = config_int(delivery, "standard_delay_seconds", 10)
    if rules._integer(raw.get("news_img_status")) == 0 and rules._values(raw.get("news_img_urls")):
        delay = config_int(delivery, "image_delay_seconds", 180)
    result = {
        **row,
        "preview_eligible": eligible,
        "would_send": eligible,
        "delivered": False,
        "delivery_delay_seconds": delay,
        "delivery_reason": "负面候选，仅生成预览" if eligible else "原平台过滤或已处理",
    }
    # Original ACE: type=3 is enrichment, never a second sentiment veto.
    if eligible and not evidence:
        result.update(
            decision="review",
            risk="unknown",
            evidence_limit=(
                row.get("evidence_limit", "") + "；摘要缺少可核对摘录，保留负面候选待人工复核"
            ).lstrip("；"),
        )
    return result


def validate_url(settings, row: dict) -> dict:
    if row.get("raw", {}).get("platform") != "media_toutiao" or not row.get("preview_eligible"):
        return row
    if (
        not settings.sgm_etl_token.get_secret_value()
        or not settings.sgm_etl_secret.get_secret_value()
    ):
        return {**row, "url_checked": False, "url_check_reason": "ETL 凭据未配置"}
    with httpx.Client(timeout=settings.sgm_etl_timeout, trust_env=False) as client:
        for _ in range(settings.sgm_etl_retries):
            timestamp = str(int(time.time() * 1000))
            token = settings.sgm_etl_token.get_secret_value()
            sign = hashlib.md5(
                (settings.sgm_etl_secret.get_secret_value() + token + timestamp).encode()
            ).hexdigest()
            try:
                response = client.post(
                    settings.sgm_etl_host.rstrip("/") + "/etl/v3/post_details/url/etl_adapter",
                    params={"token": token, "timestamp": timestamp, "sign": sign},
                    data={"news_url": row["url"]},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    continue
                ret = int(payload.get("ret", 0))
                if ret in {200, 400, 404} and "请求参数错误" not in str(payload.get("errmsg", "")):
                    return {
                        **row,
                        "url_http_code": ret,
                        "url_checked": True,
                        "preview_eligible": ret != 400,
                        "would_send": ret != 400,
                    }
            except (httpx.HTTPError, ValueError, TypeError):
                continue
    raise Unavailable("头条链接校验失败，已保留负面候选，请重试节点")
