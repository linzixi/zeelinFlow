"""通过原生初始化和 PAT API 建立本机验证账号，凭据仅保存在忽略目录。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: loopback DeerFlow Gateway; no pre-existing admin for first run
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import httpx
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    account_path = ROOT / ".runtime" / "local-login.json"
    if account_path.exists():
        account = json.loads(account_path.read_text(encoding="utf-8"))
    else:
        account = {
            "email": "ace@example.com",
            "password": secrets.token_urlsafe(24) + "aA7!",
        }
    with httpx.Client(
        base_url="http://127.0.0.1:8001", timeout=30, trust_env=False
    ) as client:
        setup = client.get("/api/v1/auth/setup-status")
        setup.raise_for_status()
        if setup.json()["needs_setup"]:
            response = client.post("/api/v1/auth/initialize", json=account)
        else:
            response = client.post(
                "/api/v1/auth/login/local",
                data={"username": account["email"], "password": account["password"]},
            )
        response.raise_for_status()
        profile = client.get("/api/v1/auth/me")
        profile.raise_for_status()
        user = profile.json()
        account_path.write_text(
            json.dumps(account, ensure_ascii=False), encoding="utf-8"
        )
        current = dotenv_values(ROOT / ".env")
        if not current.get("ACE_DF_AGENT_API_TOKEN"):
            token = client.post(
                "/api/v1/auth/pats",
                headers={"X-CSRF-Token": client.cookies.get("csrf_token", "")},
                json={
                    "name": "ACE local scheduled nodes",
                    "expires_in_days": 90,
                    "scopes": [
                        "threads:read",
                        "threads:write",
                        "runs:create",
                        "runs:read",
                        "runs:cancel",
                    ],
                },
            )
            token.raise_for_status()
            set_key(ROOT / ".env", "ACE_DF_AGENT_API_TOKEN", token.json()["token"])
            set_key(ROOT / ".env", "ACE_DF_AGENT_OWNER_ID", user["id"])
        cookies = [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": "127.0.0.1",
                "path": "/",
                "expires": cookie.expires or -1,
                "httpOnly": cookie.name == "access_token",
                "secure": False,
                "sameSite": "Lax",
            }
            for cookie in client.cookies.jar
        ]
        (ROOT / ".runtime" / "browser-state.json").write_text(
            json.dumps({"cookies": cookies, "origins": []}), encoding="utf-8"
        )
    print("Local account initialized; credentials remain in .runtime/local-login.json.")


if __name__ == "__main__":
    main()
