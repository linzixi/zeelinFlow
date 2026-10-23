from __future__ import annotations
import json
import re
from typing import Any, Mapping
_LIST_SEPARATOR = re.compile(r"[,，;；\n]+")
def config_value(config: Mapping[str, Any], name: str, default: Any = None) -> Any:
    if name in config:
        return config[name]
    parts = name.split("_")
    camel = parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])
    return config.get(camel, default)

def config_list(
    config: Mapping[str, Any],
    name: str,
    default: tuple[str, ...] = (),
) -> list[str]:
    value = config_value(config, name)
    if value is None or value == "":
        return list(default)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            return [item.strip() for item in _LIST_SEPARATOR.split(stripped) if item.strip()]
        return config_list({name: parsed}, name, default)
    if isinstance(value, Mapping):
        items = value.values()
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = value
    else:
        items = (value,)
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result

def config_bool(config: Mapping[str, Any], name: str, default: bool = False) -> bool:
    value = config_value(config, name)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default

def config_int(
    config: Mapping[str, Any],
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        value = int(config_value(config, name, default))
    except (TypeError, ValueError, OverflowError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value

def config_float(
    config: Mapping[str, Any],
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        value = float(config_value(config, name, default))
    except (TypeError, ValueError, OverflowError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value
