"""Discovery exposes declarations to signed-in viewers without invoking tools."""

from __future__ import annotations

import pytest
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from deerflow_extension_api.plugins import ModelTool, PluginContribution
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers.plugins import router
from deerflow.extensions.registry import ExtensionRegistry


@pytest.mark.parametrize("enabled", [False, True])
def test_authenticated_tool_catalog_preserves_schema_and_deployment_state(enabled):
    async def handler(payload, context):
        pytest.fail("Discovery must never invoke tools")

    schema = {"type": "object", "properties": {"limit": {"type": "integer", "maximum": 50}}}
    registry = ExtensionRegistry()
    with registry.attributed_to("test:install"):
        registry.plugin(
            PluginContribution(
                namespace="example.query",
                title="Query",
                enabled=enabled,
                tools=(ModelTool("records", "Read project records", schema, handler),),
            )
        )
    app = FastAPI()
    app.state.extensions = registry.build()
    identity = {"principal": ExtensionPrincipal("member")}
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: identity["principal"])
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/plugins")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        entry = response.json()[0]
        assert entry["settings"]["enabled"] is enabled
        assert entry["model_tools"] == [
            {
                "name": "records",
                "description": "Read project records",
                "input_schema": schema,
            }
        ]
        identity["principal"] = None
        assert client.get("/api/plugins").status_code == 401
