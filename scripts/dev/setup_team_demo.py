"""创建本地多团队示例成员；随机密码仅保存忽略目录，不发送邀请。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: native Gateway and local administrator; stdout status only
"""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/verify"))
from local_client import browser_state, call, login, root_client


def accounts() -> dict:
    path = ROOT / ".runtime/team-demo-accounts.json"
    values = json.loads(path.read_text("utf-8")) if path.exists() else {}
    for label in ("manager", "editor", "reviewer"):
        if label not in values:
            values[label] = {
                "email": f"ace.{label}@example.com",
                "password": secrets.token_urlsafe(24) + "aA7!",
            }
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    with httpx.Client(
        base_url="http://127.0.0.1:8001", timeout=45, trust_env=False
    ) as client:
        for label, account in values.items():
            result = client.post("/api/v1/auth/register", json=account)
            duplicate = (
                result.status_code == 400
                and result.json().get("detail", {}).get("code")
                == "email_already_exists"
            )
            if result.status_code != 201 and not duplicate:
                raise RuntimeError(f"注册{label}失败: HTTP {result.status_code}")
            with login(account) as session:
                browser_state(session, label)
    return values


def main() -> None:
    values = accounts()
    with root_client() as client:
        current = call(client, "GET", "/api/ace/context")
        email = call(client, "GET", "/api/v1/auth/me")["email"]
        for team in current["teams"]:
            call(
                client,
                "PUT",
                "/api/ace/members",
                json={"team_id": team["id"], "email": email, "role": team["role"]},
            )
        first = next(
            team["id"] for team in current["teams"] if team["name"] != "汽车客户团队"
        )
        automotive = next(
            (team for team in current["teams"] if team["name"] == "汽车客户团队"), None
        )
        if not automotive:
            automotive = call(
                client, "POST", "/api/ace/teams", json={"name": "汽车客户团队"}
            )
        for label, role in [
            ("manager", "admin"),
            ("editor", "orchestrator"),
            ("reviewer", "reviewer"),
        ]:
            call(
                client,
                "PUT",
                "/api/ace/members",
                json={
                    "team_id": automotive["id"],
                    "email": values[label]["email"],
                    "role": role,
                },
            )
        call(
            client,
            "PUT",
            "/api/ace/members",
            json={
                "team_id": first,
                "email": values["editor"]["email"],
                "role": "reviewer",
            },
        )
        call(client, "POST", "/api/ace/active-team", json={"team_id": automotive["id"]})
        prepare_project(client, automotive, values)
    print(
        "Local team demo prepared; credentials remain in .runtime/team-demo-accounts.json."
    )


def prepare_project(client, automotive, values):
    context = call(client, "GET", "/api/ace/context")
    project = next(
        (row for row in context["projects"] if row["name"] == "上汽通用 · 舆情监测"),
        None,
    )
    if not project:
        project = call(
            client,
            "POST",
            "/api/ace/projects",
            json={
                "team_id": automotive["id"],
                "name": "上汽通用 · 舆情监测",
                "description": "真实取数、情感与问题打标、人工审核；飞书仅预览",
            },
        )
    native = call(client, "POST", f"/api/ace/projects/{project['id']}/open")
    browser_state(client, "admin")
    path = ROOT / "output/verification/team-demo.json"
    previous = json.loads(path.read_text("utf-8")) if path.exists() else {}
    report = {
        **previous,
        "team_id": automotive["id"],
        "workspace_id": project["id"],
        **native,
        "accounts": {label: account["email"] for label, account in values.items()},
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
