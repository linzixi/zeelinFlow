"""汇总真实SGM运行和审核权限证据；只保存卡片，不发送消息。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes (read-only APIs)
Requires: completed SGM runs; stdout aggregate counts only
"""

from __future__ import annotations

import json
from collections import Counter

from local_client import ROOT, call, login, root_client
from team_access import action


def main():
    demo = json.loads((ROOT / "output/verification/team-demo.json").read_text("utf-8"))
    main_run = json.loads(
        (ROOT / "output/verification/sgm-live.json").read_text("utf-8")
    )
    final_run = json.loads(
        (ROOT / "output/verification/sgm-finalize.json").read_text("utf-8")
    )
    policy_run = json.loads(
        (ROOT / "output/verification/sgm-policy.json").read_text("utf-8")
    )
    assert main_run["status"] == final_run["status"] == "succeeded"
    assert policy_run["status"] == "succeeded"
    canvas = demo["canvas_id"]
    with root_client() as client:
        call(client, "POST", "/api/ace/active-team", json={"team_id": demo["team_id"]})
        articles = action(
            client,
            "list_articles",
            {"project_id": canvas, "mode": "live", "limit": 200},
        )["data"]
        rows = articles["items"]
        negative = [r for r in rows if r["data"].get("sentiment") == "negative"]
        assert len(rows) == articles["total"] == 111 and len(negative) == 5
        assert all(
            r["data"].get("assessment_status") == "done"
            and r["data"].get("problem_content")
            and r["data"].get("news_dig")
            for r in negative
        )
        assert not any(r["data"].get("delivered") for r in rows)
        task = next(
            t
            for t in policy_run["tasks"]
            if t["node"]["config"].get("sgm_data") == "preview"
        )
        snapshot = action(
            client,
            "snapshot",
            {"project_id": canvas, "snapshot_id": task["output_snapshot_id"]},
        )["data"]
        cards = json.loads(snapshot["payload"]["artifacts"][0]["content"])
        assert cards["preview_only"] and len(cards["cards"]) == 4
        (ROOT / "output/verification/sgm-feishu-preview.json").write_text(
            json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    verify_reviewer(demo, rows)
    write_report(demo, main_run, final_run, policy_run, rows, negative, cards)


def write_report(demo, main_run, final_run, policy_run, rows, negative, cards):
    canvas = demo["canvas_id"]
    report = {
        "passed": True,
        "canvas_id": canvas,
        "window": main_run["window"],
        "main_run": main_run["run_id"],
        "final_run": final_run["id"],
        "policy_run": policy_run["id"],
        "policy_nodes": len(policy_run["tasks"]),
        "main_nodes": 16,
        "final_nodes": 11,
        "articles": len(rows),
        "sentiments": dict(Counter(r["data"].get("sentiment") for r in rows)),
        "assessment": dict(Counter(r["data"].get("assessment_status") for r in rows)),
        "alerts": len(negative),
        "preview_cards": len(cards["cards"]),
        "evidence_review": sum(r["data"].get("decision") == "review" for r in negative),
        "sent_messages": 0,
        "video_fallback": sum(
            r["data"].get("sis_status") == "fallback_source" for r in negative
        ),
        "alerts_detail": [
            {
                "id": r["id"],
                **{
                    k: r["data"].get(k)
                    for k in (
                        "title",
                        "url",
                        "predicted_car",
                        "problem_codes",
                        "tags",
                        "problem_content",
                        "news_dig",
                        "evidence_limit",
                    )
                },
            }
            for r in negative
        ],
    }
    (ROOT / "output/verification/sgm-acceptance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "alerts_detail"},
            ensure_ascii=False,
        )
    )


def verify_reviewer(demo, rows):
    accounts = json.loads(
        (ROOT / ".runtime/team-demo-accounts.json").read_text("utf-8")
    )
    with login(accounts["reviewer"]) as client:
        call(client, "POST", "/api/ace/active-team", json={"team_id": demo["team_id"]})
        result = action(
            client, "list_articles", {"project_id": demo["canvas_id"], "limit": 200}
        )["data"]
        assert result["total"] == 5 and all(
            r["data"].get("decision") in ("report", "review") for r in result["items"]
        )
        ordinary = next(r for r in rows if r["data"].get("decision") == "observe")
        for name, extra in [
            ("article_history", {}),
            (
                "update_article",
                {
                    "patch": {
                        "revision": ordinary["revision"],
                        "summary": "禁止越权修改",
                    }
                },
            ),
        ]:
            denied = action(
                client,
                name,
                {
                    "project_id": demo["canvas_id"],
                    "article_id": ordinary["id"],
                    **extra,
                },
            )
            assert not denied["ok"] and denied["error"]["code"] == "forbidden"


if __name__ == "__main__":
    main()
