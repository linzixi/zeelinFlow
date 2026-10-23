from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_profile: ContextVar[dict | None] = ContextVar("sgm_profile", default=None)


@contextmanager
def use_profile(stages: dict):
    token = _profile.set(stages)
    try:
        yield
    finally:
        _profile.reset(token)


def stage_config(stage: str) -> dict:
    return (_profile.get() or {}).get(stage, {})


from ace_ext.vendor.legacy_sgm.config import config_bool, config_int, config_list, config_value  # noqa: E402,F401
