"""可选的部署权限批处理；结果仅用于当前请求，不缓存授权。"""

from __future__ import annotations

import asyncio
import logging

from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzRequest, Principal

logger = logging.getLogger(__name__)


async def resolve_permission_batch(
    provider: AuthorizationProvider, principal: Principal, permissions: list[str], *, fail_closed: bool
) -> list[str] | None:
    """返回本批允许的权限；没有批处理钩子时使用原有逐项校验。"""
    handler = getattr(provider, "aauthorize_many", None)
    if handler is None:
        return None
    requests = [
        AuthzRequest(principal, "route", permission.split(":", 1)[1], permission)
        for permission in permissions
    ]
    try:
        decisions = await handler(requests)
        if (
            not isinstance(decisions, list)
            or len(decisions) != len(requests)
            or any(not isinstance(item, AuthzDecision) for item in decisions)
        ):
            raise TypeError("aauthorize_many must return one AuthzDecision per request")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Authorization batch failed", exc_info=True)
        return [] if fail_closed else list(permissions)
    return [permission for permission, decision in zip(permissions, decisions) if decision.allow]
