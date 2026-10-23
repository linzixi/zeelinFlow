"""部署权限批处理保持逐项结果、失败策略与请求隔离。"""

import asyncio
from types import SimpleNamespace

import pytest

from app.gateway.authz import _ALL_PERMISSIONS, resolve_route_permissions
from deerflow.authz.provider import AuthzDecision
from deerflow.config.authorization_config import AuthorizationConfig


class BatchProvider:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result

    async def aauthorize_many(self, requests):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        if self.result is not None:
            return self.result
        return [AuthzDecision(allow=r.target == "threads:read") for r in requests]

    async def aauthorize(self, request):
        raise AssertionError("批处理提供者不应触发逐项数据库查询")


def configure(monkeypatch, provider, fail_closed=True):
    monkeypatch.setattr(
        "app.gateway.authz._get_route_authorization_config",
        lambda: AuthorizationConfig(enabled=True, fail_closed=fail_closed),
    )
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", lambda _: provider)
    return SimpleNamespace(id="batch-user", system_role="user")


@pytest.mark.asyncio
async def test_route_permissions_use_one_batch_per_request(monkeypatch):
    provider = BatchProvider()
    user = configure(monkeypatch, provider)
    assert await resolve_route_permissions(user, is_internal=False) == ["threads:read"]
    provider.result = [AuthzDecision(allow=False) for _ in _ALL_PERMISSIONS]
    assert await resolve_route_permissions(user, is_internal=False) == []
    assert provider.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [[], [True] * len(_ALL_PERMISSIONS), RuntimeError("offline")])
@pytest.mark.parametrize("fail_closed", [True, False])
async def test_batch_failures_preserve_configured_failure_mode(monkeypatch, invalid, fail_closed):
    provider = BatchProvider(invalid)
    user = configure(monkeypatch, provider, fail_closed)
    result = await resolve_route_permissions(user, is_internal=False)
    assert result == ([] if fail_closed else list(_ALL_PERMISSIONS))
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_batch_cancellation_does_not_grant_permissions(monkeypatch):
    provider = BatchProvider(asyncio.CancelledError())
    user = configure(monkeypatch, provider, fail_closed=False)
    with pytest.raises(asyncio.CancelledError):
        await resolve_route_permissions(user, is_internal=False)
