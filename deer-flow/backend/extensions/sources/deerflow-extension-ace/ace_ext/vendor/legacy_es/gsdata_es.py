"""中台 ES 网关的 Python 封装。

本模块按照 ``EsOem.php`` 的 HTTP 传输方式和 ``EsService.php`` 的查询链式
调用进行迁移，调用的是中台网关而不是原生 Elasticsearch 节点。索引路由、
鉴权和时间权限都由网关负责，因此这里必须保留 PHP 的请求体结构。
"""

from __future__ import annotations

import calendar
import json
import math
import re
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import lru_cache
from hashlib import sha256
from html.parser import HTMLParser
from threading import Lock
from typing import Any, Callable, Iterator, Mapping, Sequence, TypedDict, Union
from zoneinfo import ZoneInfo

import httpx


JsonObject = dict[str, Any]
DateTimeInput = Union[datetime, date, str]
SUPPORTED_TIME_FIELDS = frozenset({"news_posttime", "solr_create_time"})


class NewsListResult(TypedDict):
    """新闻查询统一返回结构，兼容 PHP 的 ``total/list`` 格式。"""

    total: int
    list: list[JsonObject]


class EsGatewayError(RuntimeError):
    """中台拒绝请求或返回无法解析的响应时抛出的异常。"""


@dataclass
class _QueryGate:
    lock: Any = field(default_factory=Lock)
    next_allowed: float = 0.0


@lru_cache(maxsize=128)
def _query_gate(endpoint: str, credential_digest: str) -> _QueryGate:
    return _QueryGate()


def _gateway_busy(response: httpx.Response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code not in {200, 501}:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return (isinstance(body, dict) and str(body.get("code")) == "501"
            and "服务器太忙" in str(body.get("msg", "")))


def _gateway_error_detail(text: str) -> str:
    details: list[str] = []

    def collect(value: Any, depth: int = 0) -> None:
        if depth > 6 or len(details) >= 3:
            return
        if isinstance(value, Mapping):
            collect(value.get("root_cause"), depth + 1)
            if isinstance(value.get("type"), str) and isinstance(value.get("reason"), str):
                detail = f"{value['type']}: {value['reason']}"
                if detail not in details:
                    details.append(detail)
            for key in ("error", "caused_by", "msg", "message"):
                collect(value.get(key), depth + 1)
        elif isinstance(value, list):
            for item in value[:3]:
                collect(item, depth + 1)
        elif isinstance(value, str):
            try:
                nested = json.loads(value)
            except (ValueError, TypeError):
                match = re.search(r'\{\s*"error"\s*:', value)
                if match is None:
                    return
                try:
                    nested, _end = json.JSONDecoder().raw_decode(value[match.start():])
                except ValueError:
                    return
            collect(nested, depth + 1)

    collect(text)
    return "; ".join(details)[:1000] if details else text.strip()[:500]


@dataclass(frozen=True)
class EsGatewayConfig:
    """中台网关连接配置：地址、Token、时区和允许回溯的最大月份。"""

    token: str
    gateway_url: str = "http://gateway.gsdatas.cn/mg/search/es"
    # Keep the legacy middleware routes used by EsOem.php.
    scroll_url: str = "http://gateway.gsdatas.cn/es/search/sharding/scroll/three"
    analyze_url: str = "http://gateway.gsdatas.cn/es/search/analyze/three"
    update_url: str = "http://gateway.gsdatas.cn/es/operate/three"
    default_index: str = "web,aq,weibo,wx,app,bbs,journal,media,video,comment"
    timeout_seconds: float = 30.0
    timezone: str = "Asia/Shanghai"
    max_lookback_months: int = 3
    max_query_attempts: int = 5
    query_interval_seconds: float = 1.0
    busy_retry_base_seconds: float = 2.0
    busy_retry_max_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.token.strip():
            raise ValueError("ES gateway token cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        if self.max_lookback_months <= 0:
            raise ValueError("max_lookback_months must be greater than 0")
        if type(self.max_query_attempts) is not int or not 1 <= self.max_query_attempts <= 8:
            raise ValueError("max_query_attempts must be an integer between 1 and 8")
        if not 0 <= self.query_interval_seconds <= self.busy_retry_max_seconds <= 60:
            raise ValueError("query_interval_seconds must be between 0 and busy_retry_max_seconds, at most 60")
        if not 0 < self.busy_retry_base_seconds <= self.busy_retry_max_seconds:
            raise ValueError("busy_retry_base_seconds must be positive and at most busy_retry_max_seconds")
        ZoneInfo(self.timezone)


def _subtract_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _as_datetime(
    value: DateTimeInput, timezone: ZoneInfo, *, end_of_day: bool = False
) -> datetime:
    parsed_date_only = False
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        raw = value.strip()
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                parsed_date_only = fmt == "%Y-%m-%d"
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError(
                f"invalid datetime {value!r}; expected YYYY-MM-DD HH:MM:SS"
            )
    else:
        raise TypeError("time values must be datetime, date, or string")
    if end_of_day and (
        isinstance(value, date) and not isinstance(value, datetime)
        or isinstance(value, str) and parsed_date_only
    ):
        parsed = parsed.replace(hour=23, minute=59, second=59)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _milliseconds(value: datetime) -> str:
    return str(int(value.timestamp() * 1000))


class EsGatewayClient:
    """同步 HTTP 客户端，封装查询、滚动查询、分词和文档更新接口。"""

    def __init__(
        self,
        config: EsGatewayConfig,
        *,
        http_client: httpx.Client | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self._client = http_client or httpx.Client(
            timeout=config.timeout_seconds,
            follow_redirects=False,
        )
        self._owns_client = http_client is None
        self._clock = clock
        self._query_gate = _query_gate(config.gateway_url.rstrip("/"), sha256(config.token.encode()).hexdigest())
        self.query_stats = {"requests": 0, "busyRetries": 0, "waitSeconds": 0.0}

    def now(self) -> datetime:
        timezone = ZoneInfo(self.config.timezone)
        value = self._clock() if self._clock is not None else datetime.now(timezone)
        return value.replace(tzinfo=timezone) if value.tzinfo is None else value.astimezone(timezone)

    def _now(self) -> datetime:
        """保留 PHP 迁移代码使用的内部时间别名。"""
        return self.now()

    def normalize_time_range(
        self,
        start_time: DateTimeInput | None,
        end_time: DateTimeInput | None,
    ) -> tuple[datetime, datetime]:
        """统一时区并应用中台三个月的时间查询权限限制。"""
        timezone = ZoneInfo(self.config.timezone)
        now = self._now()
        minimum = _subtract_months(now, self.config.max_lookback_months).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start = _as_datetime(start_time or minimum, timezone)
        end = _as_datetime(end_time or now, timezone, end_of_day=True)
        start = max(start, minimum)
        if start > end:
            raise ValueError("start_time cannot be later than end_time")
        return start, end

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "EsGatewayClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        retry_busy: bool = False,
    ) -> JsonObject:
        # 对应 EsOem.php::query()：Authorization 使用完整 Token，DSL 放在
        # statement 字符串中，网关要求 application/json 请求体。
        content = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8") if payload is not None else None

        def send() -> httpx.Response:
            try:
                return self._client.request(
                    method,
                    url,
                    headers={
                        "Authorization": self.config.token,
                        "Accept": "application/plain",
                        "Content-Type": "application/json",
                    },
                    content=content,
                    params=params,
                    timeout=self.config.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise EsGatewayError(f"ES gateway request failed: {exc}") from exc

        if retry_busy:
            for attempt in range(self.config.max_query_attempts):
                with self._query_gate.lock:
                    wait = max(0.0, self._query_gate.next_allowed - time.monotonic())
                    if wait > self.config.busy_retry_max_seconds:
                        raise EsGatewayError("ES 网关仍在冷却期，等待时间超过自动重试上限，请稍后重试。")
                    if wait:
                        self.query_stats["waitSeconds"] += wait
                        time.sleep(wait)
                    if attempt:
                        self.query_stats["busyRetries"] += 1
                    self.query_stats["requests"] += 1
                    try:
                        response = send()
                    finally:
                        self._query_gate.next_allowed = time.monotonic() + self.config.query_interval_seconds
                    if not _gateway_busy(response):
                        break
                    delay = min(self.config.busy_retry_max_seconds, self.config.busy_retry_base_seconds * 2 ** attempt)
                    retry_after = response.headers.get("Retry-After", "")
                    if retry_after:
                        try:
                            specified = float(retry_after)
                        except ValueError:
                            try:
                                deadline = parsedate_to_datetime(retry_after)
                                if deadline.tzinfo is None:
                                    deadline = deadline.replace(tzinfo=ZoneInfo("UTC"))
                                specified = (deadline - self.now()).total_seconds()
                            except (TypeError, ValueError, OverflowError):
                                specified = 0.0
                        if math.isfinite(specified):
                            delay = max(delay, specified)
                    self._query_gate.next_allowed = max(self._query_gate.next_allowed, time.monotonic() + delay)
                    if attempt + 1 == self.config.max_query_attempts:
                        raise EsGatewayError(
                            f"ES 网关持续繁忙，当前查询已尝试 {self.config.max_query_attempts} 次"
                            f"（HTTP {response.status_code}），请稍后重试；未把本次未完成结果作为成功返回。"
                        )
                    if delay > self.config.busy_retry_max_seconds:
                        raise EsGatewayError("ES 网关要求的 Retry-After 超过自动等待上限，请稍后重试。")
        else:
            response = send()
        if response.is_error:
            detail = _gateway_error_detail(response.text)
            raise EsGatewayError(
                f"ES gateway returned HTTP {response.status_code}: {detail}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise EsGatewayError("ES gateway response is not valid JSON") from exc
        if not isinstance(data, dict):
            raise EsGatewayError("ES gateway JSON response must be an object")
        return data

    def search(
        self,
        statement: Mapping[str, Any],
        *,
        index: str | None = None,
        start_time: DateTimeInput | None = None,
        end_time: DateTimeInput | None = None,
        time_field: str = "news_posttime",
    ) -> JsonObject:
        payload = self.build_search_payload(
            statement,
            index=index,
            start_time=start_time,
            end_time=end_time,
            time_field=time_field,
        )
        return self._request_json("POST", self.config.gateway_url, payload=payload, retry_busy=True)

    def build_search_payload(
        self,
        statement: Mapping[str, Any],
        *,
        index: str | None = None,
        start_time: DateTimeInput | None = None,
        end_time: DateTimeInput | None = None,
        time_field: str = "news_posttime",
    ) -> JsonObject:
        """构造 PHP query() 请求体，但不发送网络请求。"""
        if time_field not in SUPPORTED_TIME_FIELDS:
            raise ValueError("time_field must be 'news_posttime' or 'solr_create_time'")
        start, end = self.normalize_time_range(start_time, end_time)
        # solr_create_time 是入库时间；网关路由需要向前扩 7 天，DSL
        # 中的 solr_create_time 范围仍保持用户传入的精确窗口。
        gateway_start = start - timedelta(days=7) if time_field == "solr_create_time" else start
        return {
            "index": (index or self.config.default_index).strip(),
            "statement": json.dumps(
                statement, ensure_ascii=False, separators=(",", ":")
            ),
            "startStamp": _milliseconds(gateway_start),
            "endStamp": _milliseconds(end),
        }

    def scroll(
        self,
        statement: Mapping[str, Any],
        *,
        scroll_id: str = "",
        index: str | None = None,
        start_time: DateTimeInput | None = None,
        end_time: DateTimeInput | None = None,
    ) -> JsonObject:
        # scroll 接口沿用 search 的参数，并额外携带上一次响应返回的 scrollId。
        start, end = self.normalize_time_range(start_time, end_time)
        payload = {
            "index": (index or self.config.default_index).strip(),
            "statement": json.dumps(
                statement, ensure_ascii=False, separators=(",", ":")
            ),
            "startStamp": _milliseconds(start),
            "endStamp": _milliseconds(end),
            "scrollId": scroll_id,
        }
        return self._request_json("POST", self.config.scroll_url, payload=payload)

    def analyze(
        self,
        texts: str | Sequence[str],
        *,
        index: str,
        analyzer: str = "my_analyzer",
    ) -> list[str]:
        # PHP EsOem::fenci() uses POST with the statement in the JSON body.
        values = [texts] if isinstance(texts, str) else list(texts)
        payload = {
            "index": index,
            "statement": json.dumps(
                {"analyzer": analyzer, "text": values},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        data = self._request_json("POST", self.config.analyze_url, payload=payload)
        tokens = data.get("tokens", [])
        if not isinstance(tokens, list):
            raise EsGatewayError("ES analyze response field 'tokens' must be a list")
        return [
            str(item["token"])
            for item in tokens
            if isinstance(item, Mapping) and item.get("token") is not None
        ]

    def iter_scroll(
        self,
        statement: Mapping[str, Any],
        *,
        index: str | None = None,
        start_time: DateTimeInput | None = None,
        end_time: DateTimeInput | None = None,
        max_pages: int = 1_000,
    ) -> Iterator[JsonObject]:
        """持续读取 scroll 结果，并逐条产出归一化后的 ``_source``。"""
        if max_pages <= 0:
            raise ValueError("max_pages must be greater than 0")
        scroll_id = ""
        for _page in range(max_pages):
            response = self.scroll(
                statement,
                scroll_id=scroll_id,
                index=index,
                start_time=start_time,
                end_time=end_time,
            )
            _total, rows = normalize_search_response(response)
            if not rows:
                return
            yield from rows
            next_scroll_id = response.get("_scroll_id") or response.get("scrollId")
            if not next_scroll_id:
                raise EsGatewayError("scroll response with hits is missing a scroll id")
            scroll_id = str(next_scroll_id)
        raise EsGatewayError(f"scroll exceeded max_pages={max_pages}")

    def update_document(
        self,
        *,
        index: str,
        document_id: str,
        updates: Mapping[str, Any],
    ) -> bool:
        # 更新接口对应 EsOem.php 的 PUT 调用，statement 格式为 {"doc": {...}}。
        if not index.strip() or not document_id.strip() or not updates:
            raise ValueError("index, document_id, and updates are required")
        payload = {
            "index": index,
            "docId": document_id,
            "statement": json.dumps(
                {"doc": dict(updates)}, ensure_ascii=False, separators=(",", ":")
            ),
        }
        data = self._request_json(
            "PUT", self.config.update_url, payload=payload, params={"index": index}
        )
        return data.get("result") == "updated"


def _term_query(field: str, value: Any) -> JsonObject:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {"terms": {field: list(value)}}
    return {"term": {field: value}}


class EsQueryBuilder:
    """复刻 EsService.php 链式查询的轻量 DSL 构造器。"""

    KEYWORD_FIELDS = (
        "news_title",
        "news_content",
        "news_ocr",
        "news_origin_content",
    )

    def __init__(self) -> None:
        self._source: list[str] | None = None
        self._must: list[JsonObject] = []
        self._filter: list[JsonObject] = []
        self._must_not: list[JsonObject] = []
        self._sort: list[JsonObject] = []
        self._collapse: str | None = None
        self._highlight: JsonObject | None = None
        self._aggregations: JsonObject = {}
        self._from = 0
        self._size = 20

    def select(self, fields: Sequence[str]) -> "EsQueryBuilder":
        normalized = [str(field).strip() for field in fields if str(field).strip()]
        self._source = list(dict.fromkeys(normalized))
        return self

    def where(self, field: str, value: Any) -> "EsQueryBuilder":
        self._filter.append(_term_query(field, value))
        return self

    def where_not(self, field: str, value: Any) -> "EsQueryBuilder":
        self._must_not.append(_term_query(field, value))
        return self

    def raw_filter(self, query: Mapping[str, Any]) -> "EsQueryBuilder":
        self._filter.append(deepcopy(dict(query)))
        return self

    def search_time(
        self,
        start_time: DateTimeInput | None,
        end_time: DateTimeInput | None,
        *,
        field: str = "news_posttime",
    ) -> "EsQueryBuilder":
        bounds: JsonObject = {}
        if start_time is not None:
            bounds["gte"] = _dsl_time(start_time)
        if end_time is not None:
            bounds["lte"] = _dsl_time(end_time)
        if bounds:
            self._filter.append({"range": {field: bounds}})
        return self

    def postdate(
        self, start_date: DateTimeInput | None, end_date: DateTimeInput | None
    ) -> "EsQueryBuilder":
        bounds: JsonObject = {}
        if start_date is not None:
            bounds["gte"] = int(_dsl_time(start_date)[:10].replace("-", ""))
        if end_date is not None:
            bounds["lte"] = int(_dsl_time(end_date)[:10].replace("-", ""))
        if bounds:
            self._filter.append({"range": {"news_postdate": bounds}})
        return self

    def phrase_like(self, fields: str | Sequence[str], value: str) -> "EsQueryBuilder":
        if not value.strip():
            return self
        if isinstance(fields, str):
            self._must.append({"match_phrase_prefix": {fields: value}})
        else:
            self._must.append(
                {
                    "multi_match": {
                        "query": value,
                        "fields": list(fields),
                        "type": "phrase_prefix",
                    }
                }
            )
        return self

    def keywords(self, groups: Sequence[str | Sequence[str]], *, fields: Sequence[str] | None = None) -> "EsQueryBuilder":
        # 每组内部用 must 表示“与”，多组放入 should 表示“或”；这是页面分析词
        # 中 “+” 和 “|” 的实际语义，而不是把整串关键词当成一个短语。
        should: list[JsonObject] = []
        for group in groups:
            words = (
                [part.strip() for part in group.split("+")]
                if isinstance(group, str)
                else [str(part).strip() for part in group]
            )
            clauses = [
                {
                    "multi_match": {
                        "query": word,
                        "fields": list(fields or self.KEYWORD_FIELDS),
                        "type": "phrase",
                        "operator": "OR",
                    }
                }
                for word in words
                if word
            ]
            if clauses:
                should.append({"bool": {"must": clauses}})
        if should:
            self._must.append(
                {"bool": {"should": should, "minimum_should_match": 1}}
            )
        return self

    def keywords_with_proximity(
        self,
        groups: Sequence[str | Sequence[str]],
        *,
        max_gaps: int = 0,
    ) -> "EsQueryBuilder":
        """按 PHP 的可选 span/intervals 方案限制同字段内关键词间距。"""
        if max_gaps < 0:
            raise ValueError("max_gaps cannot be negative")
        should: list[JsonObject] = []
        for field in self.KEYWORD_FIELDS:
            for group in groups:
                words = (
                    [part.strip() for part in group.split("+")]
                    if isinstance(group, str)
                    else [str(part).strip() for part in group]
                )
                intervals = [
                    {"match": {"query": word, "max_gaps": 0}}
                    for word in words
                    if word
                ]
                if intervals:
                    should.append(
                        {
                            "intervals": {
                                field: {
                                    "all_of": {
                                        "intervals": intervals,
                                        "max_gaps": max_gaps,
                                        "ordered": False,
                                    }
                                }
                            }
                        }
                    )
        if should:
            self._must.append(
                {"bool": {"should": should, "minimum_should_match": 1}}
            )
        return self

    def exclude_keywords(self, keywords: Sequence[str]) -> "EsQueryBuilder":
        # 排除词使用 must_not。PHP 还会在存在排除词时固定排除未认证微博的
        # “垃圾”内容，这个条件属于业务规则，不能省略。
        has_keywords = False
        for keyword in keywords:
            if keyword.strip():
                has_keywords = True
                self._must_not.append(
                    {
                        "multi_match": {
                            "query": keyword,
                            "fields": list(self.KEYWORD_FIELDS),
                            "type": "phrase",
                            "operator": "OR",
                            "slop": 1,
                        }
                    }
                )
        if has_keywords:
            self._must_not.append(
                {
                    "bool": {
                        "must": [
                            {"term": {"platform": "weibo"}},
                            {"terms": {"media_is_verified": [0, -1, ""]}},
                            {"term": {"news_content_field": "垃圾"}},
                        ]
                    }
                }
            )
        return self

    def exists(self, field: str) -> "EsQueryBuilder":
        """要求字段存在且不等于空字符串。"""
        self._filter.append({"bool": {"must_not": [{"term": {field: ""}}]}})
        self._filter.append({"exists": {"field": field}})
        return self

    def wildcard(self, field: str, keyword: str) -> "EsQueryBuilder":
        if keyword:
            self._must.append({"wildcard": {field: f"*{keyword}*"}})
        return self

    def media_levels(
        self, levels: Mapping[str, Sequence[str]]
    ) -> "EsQueryBuilder":
        choices = [
            {
                "bool": {
                    "filter": [
                        _term_query("media_organization", organization),
                        _term_query("media_level", children),
                    ]
                }
            }
            for organization, children in levels.items()
            if organization and children
        ]
        if choices:
            self._filter.append(
                {"bool": {"should": choices, "minimum_should_match": 1}}
            )
        return self

    def content_fields(self, fields: Sequence[str]) -> "EsQueryBuilder":
        values = [field for field in fields if field]
        if values:
            self._filter.append({"terms": {"news_content_field": values}})
        return self

    def platforms(
        self,
        platforms: Sequence[str],
        *,
        platform_names: Sequence[str] = (),
    ) -> "EsQueryBuilder":
        # 平台代码过滤写入 platform，抖音/小红书等名称过滤写入 platform_name；
        # 索引路由由 EsNewsService._resolve_index() 单独处理。
        if platforms and not platform_names:
            self._filter.append({"terms": {"platform": list(platforms)}})
            return self
        if platform_names and not platforms:
            self._filter.append({"terms": {"platform_name": list(platform_names)}})
            return self
        choices: list[JsonObject] = []
        if platforms:
            choices.append({"terms": {"platform": list(platforms)}})
        if platform_names:
            choices.append({"terms": {"platform_name": list(platform_names)}})
        if choices:
            self._filter.append(
                {"bool": {"should": choices, "minimum_should_match": 1}}
            )
        return self

    def content_areas(self, areas: Mapping[str, Any]) -> "EsQueryBuilder":
        choices: list[JsonObject] = []
        provinces = _sequence_value(areas.get("province"))
        cities = _sequence_value(areas.get("city"))
        if provinces:
            choices.append({"terms": {"news_content_province": provinces}})
        if cities:
            choices.append({"terms": {"news_content_city": cities}})
        counties = areas.get("county") or []
        if isinstance(counties, Sequence) and not isinstance(counties, (str, bytes)):
            for county in counties:
                if not isinstance(county, Mapping) or not county.get("county"):
                    continue
                clauses: list[JsonObject] = []
                county_cities = _sequence_value(county.get("city"))
                if county_cities:
                    clauses.append({"terms": {"news_content_city": county_cities}})
                clauses.append(_term_query("news_content_county", county["county"]))
                choices.append({"bool": {"filter": clauses}})
        if choices:
            self._filter.append(
                {"bool": {"should": choices, "minimum_should_match": 1}}
            )
        return self

    def emotions(self, values: Sequence[str]) -> "EsQueryBuilder":
        normalized = [value for value in values if value]
        if normalized:
            self._filter.append({"terms": {"news_emotion": normalized}})
        return self

    def collapse(self, field: str) -> "EsQueryBuilder":
        self._collapse = field.strip() or None
        return self

    def order_by(self, field: str, direction: str = "desc") -> "EsQueryBuilder":
        normalized = direction.lower()
        if normalized not in {"asc", "desc"}:
            raise ValueError("sort direction must be 'asc' or 'desc'")
        self._sort.append({field: {"order": normalized}})
        return self

    def sort_by_script(
        self, script: str, direction: str = "desc"
    ) -> "EsQueryBuilder":
        normalized = direction.lower()
        if normalized not in {"asc", "desc"}:
            raise ValueError("sort direction must be 'asc' or 'desc'")
        if not script.strip():
            raise ValueError("sort script cannot be empty")
        self._sort.append(
            {
                "_script": {
                    "script": {"source": script},
                    "type": "number",
                    "order": normalized,
                }
            }
        )
        return self

    def highlight(
        self,
        fields: Sequence[str],
        *,
        pre_tag: str = "<em>",
        post_tag: str = "</em>",
    ) -> "EsQueryBuilder":
        normalized = [field for field in fields if field]
        if normalized:
            self._highlight = {
                "require_field_match": False,
                "pre_tags": [pre_tag],
                "post_tags": [post_tag],
                "fields": {
                    field: {"number_of_fragments": 0} for field in normalized
                },
            }
        return self

    def count_only(self) -> "EsQueryBuilder":
        self._size = 0
        return self

    def raw_aggregation(
        self, name: str, aggregation: Mapping[str, Any]
    ) -> "EsQueryBuilder":
        if not name.strip():
            raise ValueError("aggregation name cannot be empty")
        self._aggregations[name] = deepcopy(dict(aggregation))
        self._size = 0
        return self

    def group_by(
        self, field: str, *, size: int | None = None, name: str = "group_result"
    ) -> "EsQueryBuilder":
        terms: JsonObject = {"field": field}
        if size is not None:
            if size <= 0:
                raise ValueError("aggregation size must be greater than 0")
            terms["size"] = size
        return self.raw_aggregation(name, {"terms": terms})

    def cardinality(
        self, field: str, *, name: str = "group_count"
    ) -> "EsQueryBuilder":
        return self.raw_aggregation(name, {"cardinality": {"field": field}})

    def sum_field(self, field: str, *, name: str | None = None) -> "EsQueryBuilder":
        return self.raw_aggregation(name or field, {"sum": {"field": field}})

    def date_histogram(
        self,
        *,
        field: str = "news_posttime",
        interval: str = "day",
        name: str = "group_by_date",
        min_bound: str | None = None,
        max_bound: str | None = None,
    ) -> "EsQueryBuilder":
        if interval not in {"day", "hour"}:
            raise ValueError("date histogram interval must be 'day' or 'hour'")
        histogram: JsonObject = {
            "field": field,
            "interval": interval,
            "format": "yyyy-MM-dd HH" if interval == "hour" else "yyyy-MM-dd",
            "min_doc_count": 0,
        }
        if min_bound is not None and max_bound is not None:
            histogram["extended_bounds"] = {"min": min_bound, "max": max_bound}
        return self.raw_aggregation(name, {"date_histogram": histogram})

    def offset(self, value: int) -> "EsQueryBuilder":
        if value < 0:
            raise ValueError("offset cannot be negative")
        self._from = value
        return self

    def limit(self, value: int) -> "EsQueryBuilder":
        if value < 0 or value > 10_000:
            raise ValueError("limit must be between 0 and 10000")
        self._size = value
        return self

    def paginate(self, page: int = 1, page_size: int = 20) -> "EsQueryBuilder":
        # ES 默认 from+size 不能超过 10000，PHP 在入口处也执行同样的限制。
        if page <= 0 or page_size <= 0:
            raise ValueError("page and page_size must be greater than 0")
        if page * page_size > 10_000:
            raise ValueError("page window cannot exceed Elasticsearch limit 10000")
        self._from = (page - 1) * page_size
        self._size = page_size
        return self

    def build(self) -> JsonObject:
        body: JsonObject = {"from": self._from, "size": self._size}
        if self._source is not None:
            body["_source"] = list(self._source)
        bool_query: JsonObject = {}
        if self._must:
            bool_query["must"] = deepcopy(self._must)
        if self._filter:
            bool_query["filter"] = deepcopy(self._filter)
        if self._must_not:
            bool_query["must_not"] = deepcopy(self._must_not)
        body["query"] = {"bool": bool_query} if bool_query else {"match_all": {}}
        if self._sort:
            body["sort"] = deepcopy(self._sort)
        if self._collapse:
            body["collapse"] = {"field": self._collapse}
        if self._highlight:
            body["highlight"] = deepcopy(self._highlight)
        if self._aggregations:
            body["aggs"] = deepcopy(self._aggregations)
        return body


def _dsl_time(value: DateTimeInput) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return value.strip()


def _sequence_value(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(str(item).strip() for item in _sequence_value(value) if str(item).strip())
    )


def _php_not_empty(value: Any) -> bool:
    """模拟 PHP ``empty()`` 在查询参数中的常用判断。"""
    if value is None or value is False or value == 0 or value == "0" or value == "":
        return False
    if isinstance(value, (Sequence, Mapping)) and not isinstance(value, (str, bytes)):
        return bool(value)
    return True


@dataclass(frozen=True)
class NewsSearchParams:
    """PHP 查询参数数组的类型化表示，统一内部命名后再生成 DSL。"""

    search_title: str = ""
    keywords: tuple[str, ...] = ()
    required_keywords: tuple[str, ...] = ()
    excluded_keywords: tuple[str, ...] = ()
    start_time: DateTimeInput | None = None
    end_time: DateTimeInput | None = None
    time_field: str = "solr_create_time"
    platforms: tuple[str, ...] = ()
    platform_names: tuple[str, ...] = ()
    content_fields: tuple[str, ...] = ()
    keyword_fields: tuple[str, ...] = ()
    required_keyword_fields: tuple[str, ...] = ()
    media_levels: Mapping[str, Sequence[str]] = field(default_factory=dict)
    content_areas: Mapping[str, Any] = field(default_factory=dict)
    emotions: tuple[str, ...] = ("正面", "中性")
    deduplicate: bool = True
    word_spacing_slop: int | None = None
    index: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "search_title", str(self.search_title or "").strip())
        normalized_time_field = str(self.time_field or "solr_create_time").strip()
        if normalized_time_field not in SUPPORTED_TIME_FIELDS:
            raise ValueError("time_field must be 'news_posttime' or 'solr_create_time'")
        object.__setattr__(self, "time_field", normalized_time_field)
        for name in (
            "keywords",
            "required_keywords",
            "excluded_keywords",
            "platforms",
            "platform_names",
            "content_fields",
            "keyword_fields",
            "required_keyword_fields",
            "emotions",
        ):
            object.__setattr__(self, name, _string_tuple(getattr(self, name)))
        if self.index is not None:
            normalized_index = self.index.strip()
            object.__setattr__(self, "index", normalized_index or None)
        if self.word_spacing_slop is not None:
            normalized_slop = int(self.word_spacing_slop)
            if normalized_slop < 0:
                raise ValueError("word_spacing_slop cannot be negative")
            object.__setattr__(self, "word_spacing_slop", normalized_slop)

    @classmethod
    def from_php_map(cls, values: Mapping[str, Any]) -> "NewsSearchParams":
        """转换 ``EsService::getNewsList()`` 使用的参数及其平台别名。"""
        if not isinstance(values, Mapping):
            raise TypeError("PHP-compatible search parameters must be a mapping")

        platforms: list[str] = []
        platform_names: list[str] = list(
            _string_tuple(values.get("platformNames", values.get("platform_names", ())))
        )
        for platform in _string_tuple(values.get("platforms", values.get("platform", ()))):
            if platform == "all":
                platforms.extend(("web", "weibo", "media_toutiao", "wx"))
                platform_names.extend(("抖音", "小红书"))
            elif platform in {"抖音", "小红书"}:
                platform_names.append(platform)
            else:
                platforms.append(platform)

        excluded = values.get(
            "keywordsExclude", values.get("keywords_exclude", values.get("excludedKeywords", ()))
        )
        if isinstance(excluded, str):
            excluded = [part.strip() for part in excluded.split(",")]
        word_spacing_slop = values.get("word_spacing_slop")
        if word_spacing_slop is None and values.get("wordSpacingSlopSwitch"):
            word_spacing_slop = values.get("wordSpacingSlop", 0)

        return cls(
            search_title=values.get("newsTitle", values.get("search_title", "")),
            keywords=_string_tuple(values.get("keywords", ())),
            excluded_keywords=_string_tuple(excluded),
            start_time=values.get("startDate", values.get("start_time")),
            end_time=values.get("endDate", values.get("end_time")),
            time_field=values.get("timeField", values.get("time_field", values.get("searchTime", "solr_create_time"))),
            platforms=tuple(dict.fromkeys(platforms)),
            platform_names=tuple(dict.fromkeys(platform_names)),
            content_fields=_string_tuple(
                values.get("newsContentField", values.get("content_fields", ()))
            ),
            media_levels=values.get(
                "mediaLevelList", values.get("media_levels", {})
            )
            or {},
            content_areas=values.get("contentArea", values.get("content_areas", {}))
            or {},
            emotions=_string_tuple(values.get("emotions", ("正面", "中性"))),
            deduplicate=_php_not_empty(
                values.get("collapse", values.get("deduplicate", True))
            ),
            word_spacing_slop=word_spacing_slop,
            index=values.get("index"),
        )

    @classmethod
    def from_php_back_map(cls, values: Mapping[str, Any]) -> "NewsSearchParams":
        """转换 ``EsService::getNewsListBack()`` 使用的页面请求参数。"""
        if not isinstance(values, Mapping):
            raise TypeError("PHP-compatible search parameters must be a mapping")
        excluded = values.get(
            "keywords_exclude",
            values.get("keywordsExclude", values.get("excluded_keywords", ())),
        )
        if isinstance(excluded, str):
            excluded = [part.strip() for part in excluded.split(",")]
        return cls(
            keywords=_string_tuple(values.get("keywords", ())),
            excluded_keywords=_string_tuple(excluded),
            start_time=values.get("start_time", values.get("startDate")),
            end_time=values.get("end_time", values.get("endDate")),
            time_field=values.get("time_field", values.get("timeField", values.get("searchTime", "solr_create_time"))),
            platforms=_string_tuple(values.get("platform", values.get("platforms", ()))),
            content_fields=_string_tuple(
                values.get("newsContentField", values.get("content_fields", ()))
            ),
            media_levels=values.get("mediaLevel", values.get("media_levels", {})) or {},
            emotions=(),
            deduplicate=_php_not_empty(values.get("collapse", 1)),
            index=values.get("index"),
        )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _strip_tags(value: Any) -> str:
    parser = _TextExtractor()
    parser.feed(str(value or ""))
    parser.close()
    return "".join(parser.parts)


def normalize_search_response(data: Mapping[str, Any]) -> tuple[int, list[JsonObject]]:
    """兼容网关的 ``hits`` 响应和旧版 ``total/list`` 响应，并提取高亮字段。"""
    current: Mapping[str, Any] = data
    for wrapper in ("data", "result"):
        nested = current.get(wrapper)
        if isinstance(nested, Mapping) and ("hits" in nested or "list" in nested):
            current = nested
            break

    if "list" in current:
        rows = current.get("list")
        if not isinstance(rows, list):
            raise EsGatewayError("ES response field 'list' must be a list")
        total_value = current.get("total", len(rows))
        total = _total_value(total_value)
        if not all(isinstance(row, Mapping) for row in rows):
            raise EsGatewayError("ES response list items must be objects")
        return total, [dict(row) for row in rows]

    hits = current.get("hits")
    if not isinstance(hits, Mapping):
        raise EsGatewayError("ES response must contain a 'hits' object or 'list' array")
    raw_rows = hits.get("hits", [])
    if not isinstance(raw_rows, list):
        raise EsGatewayError("ES response hits.hits must be a list")
    rows: list[JsonObject] = []
    for hit in raw_rows:
        if not isinstance(hit, Mapping):
            raise EsGatewayError("ES hit must be an object")
        source = hit.get("_source", {})
        if not isinstance(source, Mapping):
            raise EsGatewayError("ES hit _source must be an object")
        item = dict(source)
        highlight = hit.get("highlight")
        if isinstance(highlight, Mapping):
            for field_name, fragments in highlight.items():
                if isinstance(fragments, Sequence) and not isinstance(fragments, (str, bytes)) and fragments:
                    item[str(field_name)] = fragments[0]
        if hit.get("_index") is not None:
            item.setdefault("_index", hit["_index"])
        rows.append(item)
    return _total_value(hits.get("total", len(rows))), rows


def _total_value(value: Any) -> int:
    if isinstance(value, Mapping):
        value = value.get("value", 0)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise EsGatewayError("ES total count must be an integer") from exc


def _aggregation_value(data: Mapping[str, Any], name: str) -> int:
    """读取网关响应中的聚合值，兼容 data/result 包装层。"""
    current: Mapping[str, Any] = data
    for wrapper in ("data", "result"):
        nested = current.get(wrapper)
        if isinstance(nested, Mapping) and ("aggs" in nested or "aggregations" in nested):
            current = nested
            break
    aggregations = current.get("aggs") or current.get("aggregations")
    if not isinstance(aggregations, Mapping):
        raise EsGatewayError(f"ES aggregation response is missing 'aggs.{name}'")
    aggregation = aggregations.get(name)
    if not isinstance(aggregation, Mapping) or "value" not in aggregation:
        raise EsGatewayError(f"ES aggregation response is missing 'aggs.{name}.value'")
    return _total_value(aggregation["value"])


class EsNewsService:
    """新闻查询业务层，对应 PHP 的 ``EsService``。"""

    # getNewsList() 的 select 字段
    NEWS_LIST_FIELDS = (
        "news_uuid",
        "platform_name",
        "media_name",
        "news_title",
        "news_digest",
        "news_posttime",
        "news_emotion",
        "platform",
        "news_author",
        "news_url",
        "news_content_field",
        "news_sim_hash",
        "news_ocr",
    )
    # getNewsListBack() 的 select 字段
    NEWS_LIST_BACK_FIELDS = (*NEWS_LIST_FIELDS[:10], "news_ocr", "solr_create_time")
    NEWS_FIELDS = NEWS_LIST_FIELDS  # 兼容旧代码

    def __init__(
        self,
        client: EsGatewayClient,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.client = client
        self._clock = clock

    def _now(self) -> datetime:
        timezone = ZoneInfo(self.client.config.timezone)
        value = self._clock() if self._clock is not None else self.client.now()
        return value.replace(tzinfo=timezone) if value.tzinfo is None else value.astimezone(timezone)

    def build_query(
        self,
        params: NewsSearchParams | Mapping[str, Any],
        *,
        page: int = 1,
        page_size: int = 20,
        sort: str = "desc",
    ) -> JsonObject:
        # build_query 只负责生成 DSL，便于日志审计和 dry-run；真正请求由 search 完成。
        normalized, start_time, end_time = self._prepare_request(params)
        return self._build_query(
            normalized,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    def build_query_back(
        self,
        params: NewsSearchParams | Mapping[str, Any],
        *,
        page: int = 1,
        page_size: int = 20,
        sort: str = "desc",
    ) -> JsonObject:
        """构造 PHP ``getNewsListBack()`` 使用的 DSL，不发起请求。"""
        normalized = (
            params
            if isinstance(params, NewsSearchParams)
            else NewsSearchParams.from_php_back_map(params)
        )
        if page <= 0 or page_size <= 0:
            raise ValueError("page and page_size must be greater than 0")
        if page * page_size > 10_000:
            raise ValueError("page window cannot exceed Elasticsearch limit 10000")
        _normalized, start_time, end_time = self._prepare_request(normalized)
        return self._build_query(
            normalized,
            fields=self.NEWS_LIST_BACK_FIELDS,
            include_excluded_keywords=True,
            include_emotions=False,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    def build_count_query(
        self,
        params: NewsSearchParams | Mapping[str, Any],
        *,
        fields: Sequence[str] | None = None,
        include_excluded_keywords: bool = True,
        include_emotions: bool = True,
    ) -> JsonObject:
        """构造按 news_sim_hash 去重的总数查询 DSL。"""
        normalized = params if isinstance(params, NewsSearchParams) else NewsSearchParams.from_php_map(params)
        _normalized, start_time, end_time = self._prepare_request(normalized)
        return self._build_query(
            normalized,
            fields=fields,
            include_excluded_keywords=include_excluded_keywords,
            include_emotions=include_emotions,
            count_only=True,
            start_time=start_time,
            end_time=end_time,
            page=1,
            page_size=1,
            sort="desc",
        )

    def _build_query(
        self,
        params: NewsSearchParams,
        *,
        fields: Sequence[str] | None = None,
        include_excluded_keywords: bool = True,
        include_emotions: bool = True,
        count_only: bool = False,
        start_time: datetime,
        end_time: datetime,
        page: int,
        page_size: int,
        sort: str,
    ) -> JsonObject:
        # 按 PHP EsService 的链式查询组织 DSL：字段、时间、关键词、过滤、排序、分页。
        builder = (
            EsQueryBuilder()
            .select(fields or self.NEWS_LIST_FIELDS)
            .search_time(start_time, end_time, field=params.time_field)
            .phrase_like("news_title", params.search_title)
        )
        if params.word_spacing_slop is None:
            # keyword() 未开启 span 查询时，使用默认的短语匹配。
            builder.keywords(params.keywords, fields=params.keyword_fields or None)
        else:
            builder.keywords_with_proximity(
                params.keywords, max_gaps=params.word_spacing_slop
            )
        builder.keywords(params.required_keywords, fields=params.required_keyword_fields or None)
        if include_excluded_keywords:
            builder = builder.exclude_keywords(params.excluded_keywords)
        builder = (
            builder.media_levels(params.media_levels)
            .content_fields(params.content_fields)
            .platforms(params.platforms, platform_names=params.platform_names)
            .content_areas(params.content_areas)
        )
        if include_emotions:
            builder.emotions(params.emotions)
        if count_only:
            builder.count_only().cardinality("news_sim_hash", name="news_sim_hash_cardinality")
        else:
            builder.order_by("news_posttime", sort).paginate(page, page_size)
        if params.deduplicate and not count_only:
            # collapse=1 按 news_sim_hash 折叠；collapse=0 时 PHP 不添加此节点。
            builder.collapse("news_sim_hash")
        return builder.build()

    def _prepare_request(
        self,
        params: NewsSearchParams | Mapping[str, Any],
    ) -> tuple[NewsSearchParams, datetime, datetime]:
        # 未传时间时沿用 PHP 默认最近 7 天，再交给网关统一执行三个月上限。
        normalized = (
            params
            if isinstance(params, NewsSearchParams)
            else NewsSearchParams.from_php_map(params)
        )
        now = self._now()
        start_time, end_time = self.client.normalize_time_range(
            normalized.start_time or now - timedelta(days=7),
            normalized.end_time or now,
        )
        return normalized, start_time, end_time

    def search(
        self,
        params: NewsSearchParams | Mapping[str, Any],
        *,
        page: int = 1,
        page_size: int = 20,
        sort: str = "desc",
    ) -> NewsListResult:
        """执行标准新闻查询并返回兼容 PHP 的 ``total/list`` 结果。"""
        normalized = (
            params
            if isinstance(params, NewsSearchParams)
            else NewsSearchParams.from_php_map(params)
        )
        return self._search_normalized(
            normalized,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    def get_news_list_back(
        self,
        params: NewsSearchParams | Mapping[str, Any],
        *,
        page: int = 1,
        page_size: int = 20,
        api_type: int = 1,
        sort: str = "desc",
    ) -> NewsListResult | dict[str, Any]:
        """对应 PHP ``getNewsListBack()``，保留其校验和字段范围。"""
        if page <= 0 or page_size <= 0:
            raise ValueError("page and page_size must be greater than 0")
        # PHP 在构造 DSL 前直接拒绝超过 ES 10000 条窗口的请求。
        if page * page_size > 10_000:
            return {"total": 0, "list": []}
        normalized = (
            params
            if isinstance(params, NewsSearchParams)
            else NewsSearchParams.from_php_back_map(params)
        )
        if not normalized.keywords and api_type == 1:
            return {"msg": "关键词不能为空"}
        if any(len(group.split("+")) > 10 for group in normalized.keywords):
            return {"msg": "单组关键词不能超过10个"}
        if len(normalized.keywords) + len(normalized.excluded_keywords) > 150:
            return {"msg": "关键词不能超过150个"}
        return self._search_normalized(
            normalized,
            page=page,
            page_size=page_size,
            sort=sort,
            fields=self.NEWS_LIST_BACK_FIELDS,
            include_excluded_keywords=True,
            include_emotions=False,
        )

    def _search_normalized(
        self,
        params: NewsSearchParams,
        *,
        page: int,
        page_size: int,
        sort: str,
        fields: Sequence[str] | None = None,
        include_excluded_keywords: bool = True,
        include_emotions: bool = True,
    ) -> NewsListResult:
        """执行已归一化参数，供两个 PHP 兼容入口共用。"""
        _normalized, start_time, end_time = self._prepare_request(params)
        response = self.client.search(
            self._build_query(
                params,
                fields=fields,
                include_excluded_keywords=include_excluded_keywords,
                include_emotions=include_emotions,
                start_time=start_time,
                end_time=end_time,
                page=page,
                page_size=page_size,
                sort=sort,
            ),
            index=self._resolve_index(params),
            start_time=start_time,
            end_time=end_time,
            time_field=params.time_field,
        )
        total, rows = normalize_search_response(response)
        if params.deduplicate:
            total = self._count_normalized(
                params,
                fields=fields,
                include_excluded_keywords=include_excluded_keywords,
                include_emotions=include_emotions,
                start_time=start_time,
                end_time=end_time,
            )
        return {
            "total": total,
            "list": [self._map_article(row, params.keywords) for row in rows],
        }

    def _count_normalized(
        self,
        params: NewsSearchParams,
        *,
        fields: Sequence[str] | None,
        include_excluded_keywords: bool,
        include_emotions: bool,
        start_time: datetime,
        end_time: datetime,
    ) -> int:
        response = self.client.search(
            self._build_query(
                params,
                fields=fields,
                include_excluded_keywords=include_excluded_keywords,
                include_emotions=include_emotions,
                count_only=True,
                start_time=start_time,
                end_time=end_time,
                page=1,
                page_size=1,
                sort="desc",
            ),
            index=self._resolve_index(params),
            start_time=start_time,
            end_time=end_time,
            time_field=params.time_field,
        )
        return _aggregation_value(response, "news_sim_hash_cardinality")

    def get_news_list(
        self,
        params: NewsSearchParams | Mapping[str, Any],
        *,
        page: int = 1,
        page_size: int = 20,
        sort: str = "desc",
    ) -> NewsListResult:
        """对应 PHP ``getNewsList()`` 的默认查询。"""
        normalized = (
            params
            if isinstance(params, NewsSearchParams)
            else NewsSearchParams.from_php_map(params)
        )
        return self._search_normalized(
            normalized,
            page=page,
            page_size=page_size,
            sort=sort,
            include_excluded_keywords=False,
            include_emotions=True,
        )

    def _resolve_index(self, params: NewsSearchParams) -> str:
        # media_*、app_*、video_* 是平台代码，但网关索引只接受 media/app/video
        # 三类前缀；因此这里做路由归并，DSL 中仍保留原平台代码。
        if params.index:
            return params.index
        if params.platforms and not params.platform_names:
            indices: list[str] = []
            for platform in params.platforms:
                if platform.startswith(("media_", "app_", "video_")):
                    index = platform.split("_", 1)[0]
                else:
                    index = platform
                if index not in indices:
                    indices.append(index)
            return ",".join(indices)
        return self.client.config.default_index

    @staticmethod
    def _map_article(item: Mapping[str, Any], keywords: Sequence[str]) -> JsonObject:
        platform_name = _strip_tags(item.get("platform_name") or item.get("media_name"))
        media_name = _strip_tags(item.get("media_name") or item.get("platform_name"))
        title = str(item.get("news_title") or item.get("news_digest") or "")
        digest = str(item.get("news_digest") or item.get("news_title") or "")
        # PHP 使用 str_ireplace($keyword) 直接替换整个关键词组，不拆分 “+”。
        for keyword in (str(group).strip() for group in keywords if str(group).strip()):
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)
            title = pattern.sub(lambda match: f"<em>{match.group(0)}</em>", title)
            digest = pattern.sub(lambda match: f"<em>{match.group(0)}</em>", digest)
        return {
            "newsUuid": item.get("news_uuid", ""),
            "platformName": platform_name,
            "mediaName": media_name,
            "newsTitle": title,
            "newsDigest": digest,
            "news_ocr": item.get("news_ocr", ""),
            "newsPosttime": item.get("news_posttime", ""),
            "newsEmotion": item.get("news_emotion", ""),
            "platform": item.get("platform", ""),
            "newsContentField": item.get("news_content_field", []),
            "newsUrl": item.get("news_url", ""),
            "simHash": item.get("news_sim_hash", ""),
        }
