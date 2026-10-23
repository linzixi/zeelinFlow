"""Deployment request policy cannot bypass the existing authentication gate."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway import request_authorization as policy
from deerflow.authz.provider import AuthzDecision, Principal


@pytest.mark.asyncio
async def test_optional_http_policy_and_denial(monkeypatch):
    request = SimpleNamespace(method="GET", scope={"path": "/api/models", "root_path": ""})
    monkeypatch.setattr(policy, "get_request_route_path", lambda _: "/api/models")
    provider = SimpleNamespace(authorize_http=AsyncMock(return_value=AuthzDecision(allow=False)))
    monkeypatch.setattr(policy, "_resolve_route_scoped_authorization", lambda *a, **k: (provider, Principal(user_id="reviewer")))
    with pytest.raises(HTTPException) as exc:
        await policy.authorize_http_request(request, object())
    assert exc.value.status_code == 403
    provider.authorize_http.side_effect = RuntimeError("database unavailable")
    with pytest.raises(HTTPException):
        await policy.authorize_http_request(request, object())
    monkeypatch.setattr(policy, "_resolve_route_scoped_authorization", lambda *a, **k: (object(), Principal(user_id="user")))
    await policy.authorize_http_request(request, object())


@pytest.mark.asyncio
async def test_list_policy_preserves_optional_provider_and_filters(monkeypatch):
    request = SimpleNamespace(state=SimpleNamespace(user=object()))
    rows = [{"thread_id": "a"}, {"thread_id": "b"}]
    provider = SimpleNamespace(filter_http_records=AsyncMock(return_value=rows[:1]))
    def resolve(user, *, is_internal):
        assert not is_internal
        return provider, None
    monkeypatch.setattr(policy, "_resolve_route_scoped_authorization", resolve)
    assert await policy.filter_http_records(request, "threads", rows) == rows[:1]
    provider = object()
    assert await policy.filter_http_records(request, "threads", rows) == rows
