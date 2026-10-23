from __future__ import annotations

from datetime import timedelta

from ace_ext.core.contracts import ArticleInput, Envelope, Window


def sample_articles(window: Window, source_key: str) -> list[ArticleInput]:
    """固定合成案例；所有名称/风险情节为模拟，不能用于客户报送。"""
    cases = [
        (
            "special_search_1",
            "demo-a",
            "【模拟】样例文旅企业收到整改通知",
            "negative",
            "high",
            "special",
        ),
        (
            "special_search_1",
            "demo-b",
            "【模拟】样例品牌完成常规产品上新",
            "positive",
            "low",
            "special",
        ),
        (
            "special_search_2",
            "demo-c",
            "【模拟】样例食品企业启动产品召回",
            "negative",
            "high",
            "special",
        ),
        (
            "special_search_3",
            "demo-d",
            "【模拟】样例出行企业公布战略融资",
            "positive",
            "medium",
            "special",
        ),
        (
            "fund_search",
            "demo-e",
            "【模拟】样例产业基金公开遴选管理机构",
            "neutral",
            "medium",
            "fund",
        ),
        ("fund_search", "demo-f", "【模拟】样例基金往期遴选结果公告", "neutral", "low", "fund"),
    ]
    result = []
    for source, key, title, sentiment, risk, branch in cases:
        if source != source_key:
            continue
        result.append(
            ArticleInput(
                source_id=key,
                title=title,
                url=f"https://example.invalid/ace/{key}",
                source="模拟数据源",
                content=f"{title}。这是用于流程验证的合成资料，不是真实新闻。",
                published_at=window.end - timedelta(minutes=30),
                ingested_at=window.end - timedelta(minutes=10),
                branch=branch,
                metrics={"matched_media": 24 if risk == "high" else 5, "reads": 3200},
                raw={
                    "simulation": True,
                    "expected_sentiment": sentiment,
                    "expected_risk": risk,
                    "source_key": source,
                    "expected_decision": "observe" if risk == "low" else "report",
                },
            )
        )
    return result


def simulate_agent(node: dict, payload: dict) -> Envelope:
    branch = node["config"].get("branch")
    records = [
        dict(record)
        for record in payload.get("records", [])
        if not branch or record.get("branch") == branch
    ]
    if node["operation"] == "report":
        records = [record for record in records if record.get("decision") == "report"]
        return Envelope(
            records=records,
            summary=f"模拟生成{len(records)}条记录的报告",
            artifacts=[
                {
                    "name": f"{node['title']}.md",
                    "kind": "report",
                    "content": "# 模拟报告\n\n"
                    + "\n\n".join(
                        f"## {row['title']}\n{row.get('summary', '')}" for row in records
                    ),
                }
            ],
            context={"simulation": True, "hasItems": bool(records)},
        )
    for record in records:
        expected = record.get("raw", {})
        record.update(
            sentiment=expected.get("expected_sentiment", "unknown"),
            risk=expected.get("expected_risk", "unknown"),
            decision=expected.get("expected_decision", "review"),
            summary="模拟研判结果，仅验证节点流转。" + str(record.get("content", "")),
            tags=["模拟资料", "基金招募" if branch == "fund" else "专项舆情"],
            assessment_status="done",
            review_status="pending",
        )
    return Envelope(
        records=records,
        summary=f"模拟研判完成，共{len(records)}条",
        context={
            "simulation": True,
            "hasItems": any(row.get("decision") == "report" for row in records),
        },
    )
