"""Optional deployment HTTP policy after identity resolution.

Providers may implement async authorize_http. Existing providers retain their
resource-level behavior. Errors fail closed; native ownership checks remain.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.gateway.authz import _resolve_route_scoped_authorization
from app.gateway.request_path import get_request_route_path
from deerflow.authz.provider import AuthzRequest


async def authorize_http_request(request, user, *, is_internal=False) -> None:
    try:
        provider, principal = _resolve_route_scoped_authorization(user, is_internal=is_internal)
        handler = getattr(provider, "authorize_http", None)
        if handler is None:
            return
        decision = await handler(AuthzRequest(
            principal=principal, resource="http", action=request.method,
            target=get_request_route_path(request), context={"request": request},
        ))
    except Exception as exc:
        raise HTTPException(403, "访问策略暂不可用") from exc
    if not decision.allow:
        raise HTTPException(403, "当前团队角色不允许访问此功能或项目")


async def filter_http_records(request, kind: str, rows: list) -> list:
    """Let deployment policy narrow owned list records; never widen ownership."""
    try:
        provider, _ = _resolve_route_scoped_authorization(
            request.state.user, is_internal=getattr(request.state, "auth_source", "") == "internal",
        )
        handler = getattr(provider, "filter_http_records", None)
        return await handler(request, kind, rows) if handler else rows
    except Exception as exc:
        raise HTTPException(403, "访问策略暂不可用") from exc
