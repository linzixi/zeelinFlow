"""本机验证客户端；不输出密码或Cookie。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: running native Gateway; stdout unused
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def login(account: dict):
    client = httpx.Client(base_url="http://127.0.0.1:8001", timeout=45, trust_env=False)
    result = client.post(
        "/api/v1/auth/login/local",
        data={
            "username": account["email"],
            "password": account["password"],
        },
    )
    result.raise_for_status()
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token", "")
    try:
        yield client
    finally:
        client.close()


def root_client():
    return login(json.loads((ROOT / ".runtime/local-login.json").read_text("utf-8")))


def call(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.is_error:
        # 响应错误可能携带用户输入；仅输出路由及状态。
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
    return response.json() if response.content else None


def browser_state(client: httpx.Client, name: str) -> None:
    cookies = [
        {
            "name": c.name,
            "value": c.value,
            "domain": "127.0.0.1",
            "path": "/",
            "expires": c.expires or -1,
            "httpOnly": c.name == "access_token",
            "secure": False,
            "sameSite": "Lax",
        }
        for c in client.cookies.jar
    ]
    (ROOT / f".runtime/{name}-browser-state.json").write_text(
        json.dumps({"cookies": cookies, "origins": []}),
        encoding="utf-8",
    )
