"""验证真实登录、团队隔离、项目归属和审核员 API 权限。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes (named project canvas and fixed verification thread)
Requires: running Gateway, setup_team_demo; stdout contains no credentials
"""

from __future__ import annotations

import json
import uuid

from local_client import ROOT, call, login, root_client


def action(client, name, payload):
    return call(client, "POST", f"/api/plugins/qingbo.ace/actions/{name}", json=payload)


def main():
    demo = json.loads((ROOT / "output/verification/team-demo.json").read_text("utf-8"))
    accounts = json.loads(
        (ROOT / ".runtime/team-demo-accounts.json").read_text("utf-8")
    )
    with root_client() as client:
        call(client, "POST", "/api/ace/active-team", json={"team_id": demo["team_id"]})
        project = call(
            client, "GET", f"/api/ace/native-projects/{demo['native_project_id']}"
        )
        canvases = project["canvases"]
        canvas = (
            canvases[0]
            if canvases
            else call(
                client,
                "POST",
                f"/api/ace/projects/{demo['workspace_id']}/canvases",
                json={"name": "上汽通用 · 取数打标与预警"},
            )
        )
        demo["canvas_id"] = canvas["id"]
        thread = str(
            uuid.uuid5(uuid.NAMESPACE_URL, "ace:project-ownership-verification")
        )
        assert (
            client.post(
                "/api/threads", json={"thread_id": str(uuid.uuid4())}
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/threads/{uuid.uuid4()}/runs", json={"assistant_id": "lead_agent"}
            ).status_code
            == 403
        )
        call(
            client,
            "POST",
            "/api/threads",
            json={"thread_id": thread, "project_id": demo["native_project_id"]},
        )
        assert (
            call(client, "GET", f"/api/threads/{thread}")["metadata"][
                "deerflow_project_id"
            ]
            == demo["native_project_id"]
        )
        # SDK repeats creation without project_id after uploading attachments.
        call(
            client,
            "POST",
            "/api/threads",
            json={"thread_id": thread, "if_exists": "do_nothing"},
        )
        assert (
            client.get(f"/api/threads/{uuid.uuid4()}/uploads/limits").status_code == 200
        )
        other = next(
            t
            for t in call(client, "GET", "/api/ace/context")["teams"]
            if t["id"] != demo["team_id"]
        )
        call(client, "POST", "/api/ace/active-team", json={"team_id": other["id"]})
        assert client.get(f"/api/threads/{thread}").status_code == 403
        assert (
            client.post(
                "/api/threads", json={"thread_id": thread, "if_exists": "do_nothing"}
            ).status_code
            == 403
        )
        assert thread not in [
            r["thread_id"] for r in call(client, "POST", "/api/threads/search", json={})
        ]
        call(client, "POST", "/api/ace/active-team", json={"team_id": demo["team_id"]})
        features = call(client, "GET", "/api/features")
    verify_members(accounts, demo, canvas, thread, other)
    save_report(demo, features)


def verify_members(accounts, demo, canvas, thread, other):
    with login(accounts["reviewer"]) as client:
        for path in [
            "/api/models",
            "/api/projects",
            "/api/agents",
            "/api/features",
            f"/api/threads/{thread}",
        ]:
            assert client.get(path).status_code == 403, path
        for name in ("get_project", "list_runs", "catalog"):
            result = action(
                client, name, {} if name == "catalog" else {"project_id": canvas["id"]}
            )
            assert not result["ok"] and result["error"]["code"] == "forbidden", name
        assert action(client, "list_articles", {"project_id": canvas["id"]})["ok"]
        rows = action(client, "list_projects", {})["data"]
        assert rows and all("graph" not in row for row in rows)
    with login(accounts["editor"]) as client:
        call(client, "POST", "/api/ace/active-team", json={"team_id": demo["team_id"]})
        assert action(client, "get_project", {"project_id": canvas["id"]})["ok"]
        assert (
            client.get(f"/api/ace/teams/{demo['team_id']}/members").status_code == 403
        )
        call(client, "POST", "/api/ace/active-team", json={"team_id": other["id"]})
        assert call(client, "GET", "/api/ace/context")["role"] == "reviewer"
        assert client.get("/api/models").status_code == 403
        call(client, "POST", "/api/ace/active-team", json={"team_id": demo["team_id"]})


def save_report(demo, features):
    (ROOT / "output/verification/team-demo.json").write_text(
        json.dumps(demo, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "output/verification/team-access.json").write_text(
        json.dumps(
            {
                "passed": True,
                "checks": [
                    "project_required",
                    "run_bypass_denied",
                    "cross_team_thread_denied",
                    "filtered_search",
                    "reviewer_api_denied",
                    "reviewer_article_access",
                    "member_management_denied",
                    "multi_team_role_switch",
                ],
                "features": features,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Team and project API verification passed.")


if __name__ == "__main__":
    main()
