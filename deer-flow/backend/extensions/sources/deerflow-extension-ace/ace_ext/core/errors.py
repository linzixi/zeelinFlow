from __future__ import annotations


class AceError(Exception):
    """可安全展示的领域错误。"""

    code = "invalid"


class NotFound(AceError):
    code = "not_found"


class Forbidden(AceError):
    code = "forbidden"


class Conflict(AceError):
    code = "conflict"


class LeaseLost(Conflict):
    code = "lease_lost"


class Unavailable(AceError):
    code = "unavailable"


class RetryableAgentError(Unavailable):
    """已确认终态的模型失败或无效输出，可用新批次重试；不包含取消和未知回执。"""


class DeferUntil(AceError):
    def __init__(self, at: float, message: str):
        super().__init__(message)
        self.at = at
