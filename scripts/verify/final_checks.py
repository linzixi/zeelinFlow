"""核对浏览器产生的真实修订、项目附件会话与运行功能状态。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes (stale revision request must be rejected)
Requires: completed browser review and attachment checks; no external delivery
"""

from __future__ import annotations

import json

from local_client import ROOT, call, login, root_client
from team_access import action


def main():
    demo = json.loads((ROOT / "output/verification/team-demo.json").read_text("utf-8"))
    accounts = json.loads(
        (ROOT / ".runtime/team-demo-accounts.json").read_text("utf-8")
    )
    with login(accounts["reviewer"]) as client:
        rows = action(
            client, "list_articles", {"project_id": demo["canvas_id"], "limit": 200}
        )["data"]["items"]
        article = next(row for row in rows if "XTS后尾门" in row["data"]["title"])
        assert article["review_status"] == "watching"
        assert article["data"]["problem_content"] == "尾门无法关闭（依据现有文字）"
        history = action(
            client,
            "article_history",
            {"project_id": demo["canvas_id"], "article_id": article["id"]},
        )["data"]
        assert history[0]["reason"].startswith("本地验收：")
        assert history[0]["actor"] == call(client, "GET", "/api/v1/auth/me")["id"]
        conflict = action(
            client,
            "update_article",
            {
                "project_id": demo["canvas_id"],
                "article_id": article["id"],
                "patch": {
                    "revision": article["revision"] - 1,
                    "summary": "应拒绝的过期提交",
                },
            },
        )
        assert not conflict["ok"] and conflict["error"]["code"] == "conflict"
        review = {
            "article_id": article["id"],
            "revision": article["revision"],
            "actor": history[0]["actor"],
            "history_saved": True,
            "stale_revision_denied": True,
        }
    thread = "799bb81c-11bb-46e2-81de-fe1010b85c52"
    with root_client() as client:
        call(client, "POST", "/api/ace/active-team", json={"team_id": demo["team_id"]})
        assert (
            call(client, "GET", f"/api/threads/{thread}")["metadata"][
                "deerflow_project_id"
            ]
            == demo["native_project_id"]
        )
        state = call(client, "GET", f"/api/threads/{thread}/state")
        messages = state["values"]["messages"]
        tools = [
            tool["name"]
            for message in messages
            for tool in message.get("tool_calls", [])
        ]
        assert "read_file" in tools
        assert "SGM-PROJECT-ATTACHMENT-20261023" in json.dumps(
            messages, ensure_ascii=False
        )
        features = call(client, "GET", "/api/features")
    report = {
        "passed": True,
        "review": review,
        "chat": {
            "thread_id": thread,
            "project_id": demo["native_project_id"],
            "tools": tools,
            "attachment_read": True,
        },
        "features": features,
    }
    (ROOT / "output/verification/final-checks.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "Reviewer revision/history/CAS and real project attachment conversation passed."
    )


if __name__ == "__main__":
    main()
