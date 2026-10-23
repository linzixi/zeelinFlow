from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx

from ace_ext.core.config import Settings
from ace_ext.core.contracts import ArticleInput, Envelope, Window
from ace_ext.core.errors import DeferUntil, Unavailable
from ace_ext.execution.simulation import sample_articles
from ace_ext.persistence.articles import ArticleRepository, article_payload
from ace_ext.persistence.database import Scope
from ace_ext.resources.es_source import EsSource
from ace_ext.resources.sgm_source import SgmSource
from ace_ext.workflow.scheduling import delivery_policy


class DataWorker:
    def __init__(self, articles: ArticleRepository, settings: Settings):
        self.articles, self.settings = articles, settings

    def execute(self, task: dict, payload: dict) -> Envelope:
        node, context = task["node"], task["context"]
        operation = node["operation"]
        window = Window.model_validate(context["window"])
        if node["config"].get("sgm_data"):
            from ace_ext.execution.sgm_data import execute

            return execute(task, payload, self.articles, self.settings)
        if operation == "ingest":
            return self._ingest(task, window)
        if operation == "delivery":
            return self._delivery(task, payload, window)
        records = list(payload.get("records", []))
        if operation == "content":
            records = self._content(records)
        elif operation in ("normalize", "deduplicate"):
            records = list(
                {str(record.get("url") or record.get("id")): record for record in records}.values()
            )
        elif operation == "metrics":
            if context["mode"] != "simulation":
                return self._refresh_metrics(task, records)
            records = [
                {**record, "metrics_refreshed_at": datetime.now(UTC).isoformat()}
                for record in records
            ]
        elif operation == "history":
            records = self.articles.compare_history(
                Scope(task["tenant_id"], context["owner_id"]),
                task["project_id"],
                records,
                before=task["created_at"],
            )
        elif operation not in ("window", "persist"):
            raise ValueError("此节点的数据执行方式尚未配置")
        return Envelope(
            records=records,
            summary=f"{node['title']}：处理{len(records)}条",
            context={"runAllowed": True, "hasItems": bool(records), "window": context["window"]},
        )

    def _ingest(self, task: dict, window: Window) -> Envelope:
        node, context = task["node"], task["context"]
        coverage = []
        if context["mode"] == "simulation":
            records = sample_articles(window, str(node["config"].get("source_key", "")))
        elif node["config"].get("connector") == "sgm":
            records, coverage = SgmSource(self.settings).fetch(node, window)
        elif node["type"] == "es_query" and not self.settings.ace_df_source_url:
            records, coverage = EsSource(self.settings).fetch(node, window)
        else:
            response = self._source_request(
                "articles",
                {
                    "window": window.model_dump(mode="json"),
                    "node_type": node["type"],
                    "config": node["config"],
                },
            )
            if response.get("complete") is not True:
                raise Unavailable("数据源返回不完整，本轮停止下游处理")
            records = [ArticleInput.model_validate(value) for value in response.get("records", [])]
        rows = self.articles.ingest(
            Scope(task["tenant_id"], context["owner_id"]),
            task["project_id"],
            records,
            mode=context["mode"],
        )
        return Envelope(
            records=[article_payload(row) for row in rows],
            summary=f"采集并入库{len(rows)}条",
            context={
                "coverage": coverage,
                "complete": all(item.get("complete", False) for item in coverage),
            },
        )

    def _refresh_metrics(self, task: dict, records: list[dict]) -> Envelope:
        response = self._source_request("metrics", {"schemaVersion": 1, "records": records})
        metrics = response.get("metrics")
        if not isinstance(metrics, dict) or any(row["id"] not in metrics for row in records):
            raise Unavailable("互动数据响应无效")
        if any(
            not isinstance(value, dict) or any(type(n) is not int or n < 0 for n in value.values())
            for value in metrics.values()
        ):
            raise Unavailable("互动数据必须为非负整数")
        return Envelope(
            records=[
                {
                    **row,
                    "metrics": metrics[row["id"]],
                    "metrics_refreshed_at": datetime.now(UTC).isoformat(),
                }
                for row in records
            ],
            summary="互动数据刷新完成",
        )

    def _content(self, records: list[dict]) -> list[dict]:
        missing = [row for row in records if not row.get("content")]
        contents = {}
        if missing:
            response = self._source_request("content", {"schemaVersion": 1, "records": missing})
            contents = response.get("contents", {})
            if not isinstance(contents, dict) or any(
                not isinstance(contents.get(row["id"]), str)
                or not contents[row["id"]].strip()
                or len(contents[row["id"]]) > 200000
                for row in missing
            ):
                raise Unavailable("正文补齐结果不完整，停止下游研判")
        return [
            {
                **row,
                "content": row.get("content") or contents[row["id"]],
                "content_status": "available",
            }
            for row in records
        ]

    def _source_request(self, endpoint: str, payload: dict) -> dict:
        if not self.settings.ace_df_source_url:
            raise Unavailable("尚未配置正式数据源，请在本地环境配置数据连接器")
        headers = {
            "Authorization": f"Bearer {self.settings.ace_df_source_token.get_secret_value()}"
        }
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"{self.settings.ace_df_source_url.rstrip('/')}/{endpoint}",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict):
            raise Unavailable("数据源响应格式错误")
        return result

    @staticmethod
    def _delivery(task: dict, payload: dict, window: Window) -> Envelope:
        local = datetime.now(ZoneInfo("Asia/Shanghai"))
        if (
            task["context"]["origin"] == "scheduled"
            and task["context"]["mode"] == "live"
            and local.hour < 9
            and window.end.astimezone(local.tzinfo).date() == local.date()
        ):
            raise DeferUntil(
                local.replace(hour=9, minute=0, second=0, microsecond=0).timestamp(),
                "首轮结果等待北京时间09:00",
            )
        allowed, reason = delivery_policy(
            origin=task["context"]["origin"],
            mode=task["context"]["mode"],
            now=datetime.now(UTC),
            window_end=window.end,
        )
        return Envelope(
            records=payload.get("records", []),
            artifacts=payload.get("artifacts", []),
            summary=reason if not allowed else "推送预览已保存，尚未启用发送连接器",
            context={"delivered": False, "delivery_allowed": allowed, "preview_only": True},
        )
