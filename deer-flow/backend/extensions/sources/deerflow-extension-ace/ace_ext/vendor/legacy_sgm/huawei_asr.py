"""Huawei SIS asynchronous ASR client using the APIG SDK-HMAC signature."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

import requests


class SgmHuaweiAsrError(RuntimeError):
    """A Huawei ASR request failed or returned an invalid contract."""


@dataclass(frozen=True)
class HuaweiAsrResult:
    state: str
    transcript: str = ""
    duration_ms: int = 0
    segments: tuple[Mapping[str, Any], ...] = ()
    reason: str = ""


def _signed_headers(
    method: str,
    url: str,
    body: bytes,
    *,
    access_key: str,
    secret_key: str,
    content_type: str | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    try:
        from huaweicloudsdkcore.auth.credentials import BasicCredentials
        from huaweicloudsdkcore.sdk_request import SdkRequest
        from huaweicloudsdkcore.signer.signer import Signer
    except ImportError as exc:
        raise SgmHuaweiAsrError(
            "宿主能力网关未安装 huaweicloudsdkcore"
        ) from exc
    if not access_key or not secret_key:
        raise SgmHuaweiAsrError("Huawei ASR access key/secret key is required")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SgmHuaweiAsrError("Huawei ASR URL must use HTTPS")
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type
    if now is not None:
        headers["X-Sdk-Date"] = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request = SdkRequest(
        method=method.upper(),
        schema=parsed.scheme,
        host=parsed.netloc,
        resource_path=parsed.path or "/",
        query_params=[],
        header_params=headers,
        body=body,
    )
    signed = Signer(BasicCredentials(access_key, secret_key)).sign(request)
    return dict(signed.header_params)


def _request(
    method: str,
    url: str,
    *,
    access_key: str,
    secret_key: str,
    payload: Mapping[str, Any] | None = None,
    timeout: int = 30,
) -> Mapping[str, Any]:
    body = (
        json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if payload is not None
        else b""
    )
    headers = _signed_headers(
        method,
        url,
        body,
        access_key=access_key,
        secret_key=secret_key,
        content_type="application/json" if payload is not None else None,
    )
    try:
        response = requests.request(
            method, url, headers=headers, data=body or None, timeout=max(3, int(timeout))
        )
    except requests.RequestException as exc:
        raise SgmHuaweiAsrError(f"Huawei ASR request failed ({type(exc).__name__})") from None
    try:
        decoded = response.json()
    except ValueError:
        decoded = {}
    result = decoded if isinstance(decoded, Mapping) else {}
    if response.status_code >= 400:
        code = str(result.get("error_code") or result.get("code") or response.status_code)
        raise SgmHuaweiAsrError(f"Huawei ASR HTTP {response.status_code}, code={code}")
    return result


def submit_asr_job(
    endpoint: str,
    media_url: str,
    *,
    access_key: str,
    secret_key: str,
    timeout: int = 30,
) -> str:
    payload = {
        "config": {
            "audio_format": "auto",
            "property": "chinese_16k_media",
            "add_punc": "yes",
        },
        "data_url": str(media_url),
    }
    result = _request(
        "POST",
        endpoint.rstrip("/"),
        access_key=access_key,
        secret_key=secret_key,
        payload=payload,
        timeout=timeout,
    )
    job_id = str(result.get("job_id") or "").strip()
    if not job_id:
        raise SgmHuaweiAsrError("Huawei ASR response has no job_id")
    return job_id


def read_asr_job(
    endpoint: str,
    job_id: str,
    *,
    access_key: str,
    secret_key: str,
    timeout: int = 30,
) -> HuaweiAsrResult:
    result = _request(
        "GET",
        endpoint.rstrip("/") + "/" + quote(str(job_id), safe="-_.~"),
        access_key=access_key,
        secret_key=secret_key,
        timeout=timeout,
    )
    status = str(result.get("status") or "").strip().upper()
    if status == "ERROR":
        code = str(result.get("error_code") or result.get("code") or "").strip()
        reason = "huawei-asr-error" + (f":{code}" if code else "")
        return HuaweiAsrResult(state="failed", reason=reason)
    if status != "FINISHED":
        return HuaweiAsrResult(state="pending")
    raw_segments = result.get("segments")
    segments = tuple(
        dict(item) for item in raw_segments or () if isinstance(item, Mapping)
    ) if isinstance(raw_segments, list) else ()
    text: list[str] = []
    for segment in segments:
        nested = segment.get("result")
        if isinstance(nested, Mapping):
            value = str(nested.get("text") or "").strip()
            if value:
                text.append(value)
    transcript = " ".join(text).strip()
    if not transcript:
        return HuaweiAsrResult(
            state="no_transcript",
            segments=segments,
            reason="huawei-asr-no-transcript",
        )
    try:
        duration = int(result.get("audio_duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    return HuaweiAsrResult(
        state="completed", transcript=transcript, duration_ms=duration, segments=segments
    )
