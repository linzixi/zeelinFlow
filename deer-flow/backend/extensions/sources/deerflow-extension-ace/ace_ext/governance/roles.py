from __future__ import annotations

ROLE_LABELS = {"admin": "团队管理员", "orchestrator": "编排师", "reviewer": "预警审核"}
REVIEW = frozenset({"projects.read", "articles.read", "articles.write"})
AUTHOR = REVIEW | frozenset(
    {"projects.write", "canvas.read", "canvas.write", "runs.read", "runs.write", "chat"}
)
PERMISSIONS = {"admin": AUTHOR | {"team.manage"}, "orchestrator": AUTHOR, "reviewer": REVIEW}


def allowed(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, frozenset())
