"""普通用户安装内置业务能力，保持凭据隔离和启动命令限制。"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from app.gateway.routers import capabilities, personal_mcp
from deerflow.capabilities.business import connection_config
from deerflow.config.paths import Paths
from deerflow.mcp.user_config import read_user_mcp_config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("deerflow.mcp.user_config.get_paths", lambda: Paths(base_dir=tmp_path))
    app = FastAPI()
    app.dependency_overrides[get_config] = lambda: SimpleNamespace()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.user = SimpleNamespace(id=request.headers.get("test-user", "alice"), system_role="user")
        request.state.auth_source = "session"
        return await call_next(request)

    app.include_router(capabilities.router)
    app.include_router(personal_mcp.router)
    with TestClient(app) as browser:
        yield browser


@pytest.mark.parametrize("provider,credentials", [
    ("dingtalk", {"access_token": "test-token", "sign_secret": "SEC-test-secret"}),
    ("wecom", {"webhook_key": "test-webhook"}),
    ("hubspot", {"access_token": "test-token"}),
])
def test_user_can_install_read_and_delete_bundled_capability(client, provider, credentials):
    body = {"plugin_id": provider, "name": provider, "configuration": credentials, "scope": "user"}
    response = client.post("/api/capabilities/installations", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["plugin_id"] == provider
    assert all(secret not in response.text for secret in credentials.values())
    assert provider in read_user_mcp_config("alice")["mcpServers"]
    peer = client.get("/api/capabilities/installations/business?scope=user", headers={"test-user": "bob"})
    assert peer.json()["items"] == []
    assert client.post("/api/capabilities/installations", json=body).status_code == 409
    assert client.delete(f"/api/mcp/personal/config/servers/{provider}").status_code == 200
    assert client.get("/api/capabilities/installations/business?scope=user").json()["items"] == []


def test_user_cannot_override_bundled_working_directory(client):
    definition = connection_config("dingtalk", {"access_token": "test-token", "sign_secret": "SEC-test-secret"})
    definition["cwd"] = "untrusted-directory"
    response = client.post("/api/mcp/personal/config/servers", json={"mcp_servers": {"dingtalk": definition}})
    assert response.status_code == 403
    assert not read_user_mcp_config("alice")["mcpServers"]
