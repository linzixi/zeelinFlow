"""Bounded database adapter for the external SGM SIS transcription service.

This module does not call Huawei SIS or any other ASR HTTP endpoint.  It writes
the legacy download/transcription task row to the configured ``videosisdb``
database.  The separately operated SIS service consumes that table, downloads
the video, calls ASR, and writes status/transcript data back for polling.

Database connection values are supplied by the caller, normally from server
environment variables.  No host, account, password, or secret is embedded in
this module.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

try:  # Keep the framework importable before optional DB dependencies install.
    import pymysql
except ImportError:  # pragma: no cover - exercised in dependency-free installs
    pymysql = None  # type: ignore[assignment]


class SgmSisError(RuntimeError):
    """A SIS task could not be safely built, submitted, or read."""


@dataclass(frozen=True)
class SgmSisDatabaseConfig:
    """Caller-supplied connection settings for the external SIS task DB."""

    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str
    table: str = "gsdata_commerce_download_entity"
    connect_timeout: int = 5
    read_timeout: int = 10
    write_timeout: int = 10


@dataclass(frozen=True)
class SgmSisSubmission:
    news_uuid: str
    submitted: bool
    already_submitted: bool


@dataclass(frozen=True)
class SgmSisResult:
    """Normalized view of one external SIS task row."""

    news_uuid: str
    found: bool
    state: str
    status: Any = None
    content: str = ""
    status_column: str | None = None
    content_column: str | None = None
    crawler_status: Any = None
    media_url: str = ""

    @property
    def completed(self) -> bool:
        return self.state == "completed"


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HTTP_URL = re.compile(r"https?://[^\s\"'<>\\]+", re.IGNORECASE)
_TASK_FIELDS = (
    "news_uuid",
    "news_url",
    "unique_identity",
    "news_posttime",
    "news_video_urls",
    "news_contain_video",
    "limit_download_duration",
    "article_type",
    "entity_type",
)
_STATUS_CANDIDATES = (
    "sis_status",
    "asr_status",
    "task_status",
    "download_status",
    "status",
)
_CONTENT_CANDIDATES = (
    "news_content",
    "sis_content",
    "asr_content",
    "transcript",
    "result_text",
    "content",
)
_CRAWLER_STATUS_CANDIDATES = ("crawler_status",)
_MEDIA_URL_CANDIDATES = ("ocr_urls", "obs_url", "media_url", "download_url")
_COMPLETE_STATUSES = {
    "1",
    "complete",
    "completed",
    "done",
    "finish",
    "finished",
    "success",
    "succeeded",
}
_PENDING_STATUSES = {"0", "created", "pending", "processing", "queued", "running", "submitted"}
_FAILED_STATUSES = {
    "-2",
    "-1",
    "2",
    "7",
    "8",
    "9",
    "error",
    "failed",
    "failure",
    "not_found",
    "timeout",
}


def correlation_key(project_id: Any, article_id: Any, news_url: Any) -> str:
    """Return the legacy ``md5(project_id + article_id + news_url)`` key."""

    project = project_id if project_id is not None else ""
    article = article_id if article_id is not None else ""
    url = news_url if news_url is not None else ""
    raw = f"{project}{article}{url}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _normalized_http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().strip("\"'")
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def _extract_first_video_url(value: Any, *, depth: int) -> str | None:
    if depth > 8 or value is None:
        return None
    if isinstance(value, Mapping):
        preferred = ("url", "video_url", "videoUrl", "play_url", "playUrl", "src")
        for key in preferred:
            if key in value:
                found = _extract_first_video_url(value[key], depth=depth + 1)
                if found:
                    return found
        for nested in value.values():
            found = _extract_first_video_url(nested, depth=depth + 1)
            if found:
                return found
        return None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            found = _extract_first_video_url(nested, depth=depth + 1)
            if found:
                return found
        return None
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate or candidate.lower() in {"null", "none", "[]", "{}"}:
        return None
    try:
        decoded = json.loads(candidate)
    except (TypeError, ValueError):
        decoded = None
    if decoded is not None and decoded != candidate:
        found = _extract_first_video_url(decoded, depth=depth + 1)
        if found:
            return found

    direct = _normalized_http_url(candidate)
    if direct:
        return direct
    match = _HTTP_URL.search(candidate)
    if not match:
        return None
    return _normalized_http_url(match.group(0).rstrip(".,;)]}"))


def extract_first_video_url(value: Any) -> str | None:
    """Extract the first HTTP(S) video URL from JSON, lists, or plain text."""

    return _extract_first_video_url(value, depth=0)


def build_task_payload(
    *,
    project_id: Any,
    article_id: Any,
    news_url: Any,
    news_posttime: Any,
    news_video_urls: Any,
) -> dict[str, Any]:
    """Build the exact legacy ``gsdata_commerce_download_entity`` row."""

    project = str(project_id or "").strip()
    article = str(article_id if article_id is not None else "").strip()
    article_url = str(news_url or "").strip()
    video_url = extract_first_video_url(news_video_urls)
    if not project:
        raise SgmSisError("SIS project_id is required")
    if not article:
        raise SgmSisError("SIS article_id is required")
    if not article_url:
        raise SgmSisError("SIS news_url is required")
    if not video_url:
        raise SgmSisError("SIS video URL is required")

    return {
        "news_uuid": correlation_key(project, article, article_url),
        "news_url": article_url,
        "unique_identity": project,
        "news_posttime": news_posttime,
        "news_video_urls": video_url,
        "news_contain_video": "1",
        "limit_download_duration": 300,
        "article_type": -3,
        "entity_type": 3,
    }


def _validate_identifier(value: str, *, label: str) -> str:
    candidate = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(candidate):
        raise SgmSisError(f"Invalid SIS {label}")
    return candidate


def _bounded_int(value: Any, *, label: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise SgmSisError(f"Invalid SIS {label}") from None
    if not minimum <= parsed <= maximum:
        raise SgmSisError(f"Invalid SIS {label}")
    return parsed


def _validate_config(config: SgmSisDatabaseConfig) -> tuple[int, int, int, int]:
    if not str(config.host or "").strip():
        raise SgmSisError("SIS database host is required")
    if not str(config.user or "").strip():
        raise SgmSisError("SIS database user is required")
    if not str(config.password or ""):
        raise SgmSisError("SIS database password is required")
    if not str(config.database or "").strip():
        raise SgmSisError("SIS database name is required")
    port = _bounded_int(config.port, label="database port", minimum=1, maximum=65535)
    connect_timeout = _bounded_int(
        config.connect_timeout,
        label="database timeout",
        minimum=1,
        maximum=300,
    )
    read_timeout = _bounded_int(
        config.read_timeout,
        label="database timeout",
        minimum=1,
        maximum=300,
    )
    write_timeout = _bounded_int(
        config.write_timeout,
        label="database timeout",
        minimum=1,
        maximum=300,
    )
    _validate_identifier(config.table, label="table")
    return port, connect_timeout, read_timeout, write_timeout


def _driver() -> Any:
    if pymysql is None:
        raise SgmSisError("PyMySQL is required for SIS database access")
    return pymysql


def _connect(config: SgmSisDatabaseConfig) -> Any:
    port, connect_timeout, read_timeout, write_timeout = _validate_config(config)
    driver = _driver()
    try:
        return driver.connect(
            host=config.host,
            port=port,
            user=config.user,
            password=config.password,
            database=config.database,
            charset="utf8mb4",
            cursorclass=driver.cursors.DictCursor,
            autocommit=False,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
        )
    except Exception as exc:
        raise SgmSisError(f"SIS database connection failed ({type(exc).__name__})") from None


def _close_quietly(resource: Any) -> None:
    if resource is None:
        return
    try:
        resource.close()
    except Exception:
        pass


def _rollback_quietly(connection: Any) -> None:
    try:
        connection.rollback()
    except Exception:
        pass


def _is_duplicate(exc: Exception) -> bool:
    args = getattr(exc, "args", ())
    if not args:
        return False
    try:
        return int(args[0]) == 1062
    except (TypeError, ValueError):
        return False


def _validated_task(task: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in _TASK_FIELDS if field not in task]
    if missing:
        raise SgmSisError("SIS task payload is incomplete")
    row = {field: task[field] for field in _TASK_FIELDS}
    news_uuid = str(row["news_uuid"] or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", news_uuid):
        raise SgmSisError("Invalid SIS news_uuid")
    if not str(row["unique_identity"] or "").strip():
        raise SgmSisError("Invalid SIS unique_identity")
    if not _normalized_http_url(row["news_url"]):
        raise SgmSisError("Invalid SIS news_url")
    if not _normalized_http_url(row["news_video_urls"]):
        raise SgmSisError("Invalid SIS video URL")
    row["news_uuid"] = news_uuid
    return row


def submit_task(
    config: SgmSisDatabaseConfig,
    task: Mapping[str, Any],
) -> SgmSisSubmission:
    """Insert one task, treating an existing/deduplicated ``news_uuid`` as success."""

    row = _validated_task(task)
    table = _validate_identifier(config.table, label="table")
    connection = _connect(config)
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT `news_uuid` FROM `{table}` WHERE `news_uuid`=%s LIMIT 1",
            (row["news_uuid"],),
        )
        if cursor.fetchone():
            return SgmSisSubmission(
                news_uuid=row["news_uuid"],
                submitted=False,
                already_submitted=True,
            )

        quoted = ", ".join(f"`{field}`" for field in _TASK_FIELDS)
        placeholders = ", ".join(["%s"] * len(_TASK_FIELDS))
        cursor.execute(
            f"INSERT INTO `{table}` ({quoted}) VALUES ({placeholders})",
            tuple(row[field] for field in _TASK_FIELDS),
        )
        connection.commit()
        return SgmSisSubmission(
            news_uuid=row["news_uuid"],
            submitted=True,
            already_submitted=False,
        )
    except Exception as exc:
        _rollback_quietly(connection)
        if _is_duplicate(exc):
            return SgmSisSubmission(
                news_uuid=row["news_uuid"],
                submitted=False,
                already_submitted=True,
            )
        if isinstance(exc, SgmSisError):
            raise
        raise SgmSisError(f"SIS task submission failed ({type(exc).__name__})") from None
    finally:
        _close_quietly(cursor)
        _close_quietly(connection)


def _column_names(rows: Sequence[Any]) -> dict[str, str]:
    columns: dict[str, str] = {}
    for row in rows:
        value: Any = None
        if isinstance(row, Mapping):
            value = row.get("Field") or row.get("field") or row.get("COLUMN_NAME")
        elif isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
            value = row[0] if row else None
        name = str(value or "").strip()
        if _IDENTIFIER.fullmatch(name):
            columns[name.lower()] = name
    return columns


def _select_column(
    configured: str | None,
    candidates: Sequence[str],
    columns: Mapping[str, str],
) -> str | None:
    if configured:
        requested = _validate_identifier(configured, label="column")
        actual = columns.get(requested.lower())
        if actual:
            return actual
    for candidate in candidates:
        actual = columns.get(candidate.lower())
        if actual:
            return actual
    return None


def _content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def _normalized_state(
    *,
    found: bool,
    status: Any,
    content: str,
    crawler_status: Any = None,
) -> str:
    if not found:
        return "missing"
    status_text = str(status).strip().lower() if status is not None else ""
    if status_text in _COMPLETE_STATUSES:
        return "completed"
    if status_text in _FAILED_STATUSES:
        return "failed"
    if status_text in _PENDING_STATUSES:
        return "pending"
    if not status_text and content:
        return "completed"
    crawler_status_text = (
        str(crawler_status).strip().lower() if crawler_status is not None else ""
    )
    # The legacy downloader table has no ASR status column. Its documented
    # crawler states are 0=queued, 3=downloading, 1=downloaded, -1=failed and
    # -2=not found. A failed row can still expose a partial media URL, which
    # the caller deliberately checks before acting on this terminal state.
    if crawler_status_text in {"-2", "-1"}:
        return "failed"
    if crawler_status_text in {"0", "1", "3"}:
        return "pending"
    return "unknown"


def read_task_result(
    config: SgmSisDatabaseConfig,
    news_uuid: str,
    *,
    status_column: str | None = None,
    content_column: str | None = None,
) -> SgmSisResult:
    """Read one task using configured columns or safe discovered fallbacks."""

    key = str(news_uuid or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise SgmSisError("Invalid SIS news_uuid")
    table = _validate_identifier(config.table, label="table")
    connection = _connect(config)
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(f"SHOW COLUMNS FROM `{table}`")
        columns = _column_names(cursor.fetchall() or ())
        uuid_column = columns.get("news_uuid")
        if not uuid_column:
            raise SgmSisError("SIS task table has no news_uuid column")
        selected_status = _select_column(status_column, _STATUS_CANDIDATES, columns)
        selected_content = _select_column(content_column, _CONTENT_CANDIDATES, columns)
        selected_crawler_status = _select_column(None, _CRAWLER_STATUS_CANDIDATES, columns)
        selected_media_url = _select_column(None, _MEDIA_URL_CANDIDATES, columns)

        fields = [f"`{uuid_column}` AS `_sis_news_uuid`"]
        if selected_status:
            fields.append(f"`{selected_status}` AS `_sis_status`")
        if selected_content:
            fields.append(f"`{selected_content}` AS `_sis_content`")
        if selected_crawler_status:
            fields.append(f"`{selected_crawler_status}` AS `_sis_crawler_status`")
        if selected_media_url:
            fields.append(f"`{selected_media_url}` AS `_sis_media_url`")
        cursor.execute(
            f"SELECT {', '.join(fields)} FROM `{table}` "
            f"WHERE `{uuid_column}`=%s LIMIT 1",
            (key,),
        )
        row = cursor.fetchone()
        if not row:
            return SgmSisResult(
                news_uuid=key,
                found=False,
                state="missing",
                status_column=selected_status,
                content_column=selected_content,
            )
        if isinstance(row, Mapping):
            status = row.get("_sis_status") if selected_status else None
            content = _content_text(row.get("_sis_content")) if selected_content else ""
            crawler_status = (
                row.get("_sis_crawler_status") if selected_crawler_status else None
            )
            raw_media_url = row.get("_sis_media_url") if selected_media_url else None
        else:
            values = list(row)
            offset = 1
            status = values[offset] if selected_status and len(values) > offset else None
            offset += 1 if selected_status else 0
            content = (
                _content_text(values[offset])
                if selected_content and len(values) > offset
                else ""
            )
            offset += 1 if selected_content else 0
            crawler_status = (
                values[offset]
                if selected_crawler_status and len(values) > offset
                else None
            )
            offset += 1 if selected_crawler_status else 0
            raw_media_url = (
                values[offset] if selected_media_url and len(values) > offset else None
            )
        media_url = extract_first_video_url(raw_media_url) or ""
        return SgmSisResult(
            news_uuid=key,
            found=True,
            state=_normalized_state(
                found=True,
                status=status,
                content=content,
                crawler_status=crawler_status,
            ),
            status=status,
            content=content,
            status_column=selected_status,
            content_column=selected_content,
            crawler_status=crawler_status,
            media_url=media_url,
        )
    except Exception as exc:
        if isinstance(exc, SgmSisError):
            raise
        raise SgmSisError(f"SIS task read failed ({type(exc).__name__})") from None
    finally:
        _close_quietly(cursor)
        _close_quietly(connection)


def poll_task_result(
    config: SgmSisDatabaseConfig,
    news_uuid: str,
    *,
    attempts: int = 1,
    interval_seconds: float = 0,
    status_column: str | None = None,
    content_column: str | None = None,
) -> SgmSisResult:
    """Boundedly poll until the task completes/fails or attempts are exhausted."""

    poll_attempts = _bounded_int(
        attempts,
        label="poll attempts",
        minimum=1,
        maximum=120,
    )
    try:
        poll_interval = float(interval_seconds)
    except (TypeError, ValueError, OverflowError):
        raise SgmSisError("Invalid SIS poll interval") from None
    if not 0 <= poll_interval <= 300:
        raise SgmSisError("Invalid SIS poll interval")
    result: SgmSisResult | None = None
    for attempt in range(poll_attempts):
        result = read_task_result(
            config,
            news_uuid,
            status_column=status_column,
            content_column=content_column,
        )
        if result.state in {"completed", "failed"}:
            return result
        if attempt + 1 < poll_attempts and poll_interval:
            time.sleep(poll_interval)
    if result is None:  # Guarded by the attempts validation above.
        raise SgmSisError("SIS poll produced no result")
    return result
