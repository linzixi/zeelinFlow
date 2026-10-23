from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ace_ext.core.config import Settings
from ace_ext.core.contracts import ArticleInput, Window
from ace_ext.core.errors import Unavailable
from ace_ext.vendor.legacy_es.es_clusters import search_clusters
from ace_ext.vendor.legacy_es.es_record_fields import EvidenceFieldsNewsService
from ace_ext.vendor.legacy_es.gsdata_es import EsGatewayClient, EsGatewayConfig, NewsSearchParams

EVIDENCE = [
    "news_content",
    "news_origin_content",
    "news_sim_hash",
    "solr_create_time",
    "news_url",
    "news_uuid",
    "news_title",
    "news_posttime",
    "media_name",
]


class EsSource:
    """保留 ACE 多轮/簇复核语义；时间窗由任务快照确定，凭据仅从部署配置读取。"""

    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch(self, node: dict, window: Window) -> tuple[list[ArticleInput], list[dict]]:
        token = self.settings.gsdata_es_token.get_secret_value()
        if not token:
            raise Unavailable("尚未配置 ES 网关凭据，请配置 GSDATAS_ES_TOKEN")
        config = node["config"]
        rounds = config.get("query_rounds") or {node["id"]: {}}
        if not isinstance(rounds, dict) or len(rounds) > 20:
            raise Unavailable("ES 查询轮次配置无效")
        records, coverage = [], []
        gateway = EsGatewayConfig(
            token=token, gateway_url=self.settings.gsdata_es_gateway_url, max_query_attempts=3
        )
        with EsGatewayClient(gateway) as client:
            for key, override in rounds.items():
                effective = {**config, **override}
                params = self._parameters(effective, window)
                service = EvidenceFieldsNewsService(client, EVIDENCE)
                rows, evidence = self._query(client, service, params, effective)
                for row in rows:
                    row = {**row, "source_round": str(key), "source_node": node["id"]}
                    records.append(self._article(row, node, window))
                coverage.append({"round": str(key), **evidence})
        return records, coverage

    @staticmethod
    def _parameters(config: dict, window: Window) -> NewsSearchParams:
        if not config.get("keywords"):
            raise Unavailable("采集节点需要关键词")
        return NewsSearchParams(
            keywords=config["keywords"],
            excluded_keywords=config.get("excluded_keywords", []),
            required_keywords=config.get("required_keywords", []),
            start_time=window.start,
            end_time=window.end,
            time_field="solr_create_time",
            keyword_fields=config.get("match_fields", []),
            required_keyword_fields=config.get("required_match_fields", []),
            platforms=config.get("platforms", []),
            platform_names=config.get("platform_names", []),
            content_fields=config.get("content_fields", []),
            media_levels=config.get("media_levels", {}),
            content_areas=config.get("content_areas", {}),
            emotions=config.get("emotions", []),
            deduplicate=bool(config.get("collapse", False)),
            index=config.get("index"),
        )

    @staticmethod
    def _query(client, service, params, config) -> tuple[list[dict], dict]:
        limit = min(max(int(config.get("max_results", 1000)), 1), 10000)
        if config.get("query_mode") == "clusters":
            result = search_clusters(
                client,
                service,
                params,
                limit=min(limit, 500),
                rank_by=config.get("rank_by", "propagation"),
                match_fields=config.get("match_fields") or ["news_title", "news_content"],
                sim_hash_field=config.get("sim_hash_field", "news_sim_hash.hash"),
                representative_sort=config.get("representative_sort", "earliest"),
                highlight_fields=config.get("highlight_fields", []),
            )
            return result["records"], result["coverage"]
        if config.get("query_mode", "documents") != "documents":
            raise Unavailable("不支持的 ES 查询模式")
        size = min(max(int(config.get("page_size", 100)), 1), 1000, limit)
        records, page = [], 1
        while page * size <= 10000:
            result = service.get_news_list_back(params, page=page, page_size=size, sort="desc")
            if "msg" in result:
                raise Unavailable("ES 查询参数未通过校验")
            batch = result["list"]
            records.extend(batch)
            if len(records) > limit:
                break
            if len(records) >= result["total"]:
                return records, {"complete": True, "total": result["total"]}
            if len(batch) < size:
                raise Unavailable("ES 分页结果不完整，请重新采集")
            if len(records) >= limit:
                break
            page += 1
        raise Unavailable("ES 返回量超过上限，请缩小时间窗，避免遗漏数据")

    @staticmethod
    def _article(row: dict, node: dict, window: Window) -> ArticleInput:
        def value(*keys):
            return next((row[key] for key in keys if row.get(key)), "")

        title = html.unescape(re.sub(r"<[^>]+>", "", str(value("news_title", "newsTitle"))))
        url = str(value("news_url", "newsUrl"))
        source_id = (
            str(value("news_uuid", "newsUuid", "record_id"))
            or hashlib.sha256((url + title).encode()).hexdigest()
        )
        ingested = _date(value("solr_create_time"))
        if ingested is None:
            raise Unavailable("来源缺少入库时间，无法确认150分钟窗口")
        if window and not window.start <= ingested < window.end:
            raise Unavailable("来源记录超出入库时间窗，请检查数据源时间字段")
        return ArticleInput(
            source_id=source_id,
            title=title,
            url=url,
            source=str(value("media_name", "mediaName", "platformName") or "ES 网关"),
            content=str(value("news_content", "news_origin_content")),
            published_at=_date(value("news_posttime", "newsPosttime")),
            ingested_at=ingested,
            branch="fund" if node["id"].startswith("fund") else "special",
            raw=row,
            metrics={
                key: row[key]
                for key in ("matched_document_count", "matched_media_count")
                if type(row.get(key)) is int
            },
        )


def _date(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(
            value / 1000 if value > 1e11 else value, ZoneInfo("Asia/Shanghai")
        )
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
