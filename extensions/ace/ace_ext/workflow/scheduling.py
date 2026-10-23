from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter

from ace_ext.workflow.models import Trigger
from ace_ext.workflow.validation import validate_trigger


def next_occurrence(trigger: Trigger, after: datetime) -> datetime:
    """严格在 after 之后求下次触发；固定时点绝不按保存时间计算间隔。"""
    validate_trigger(trigger)
    if after.tzinfo is None:
        raise ValueError("调度时间必须携带时区")
    local = after.astimezone(ZoneInfo(trigger.timezone))
    if trigger.runAtTimes:
        for day in (0, 1):
            date = local + timedelta(days=day)
            for value in sorted(set(trigger.runAtTimes)):
                hour, minute = map(int, value.split(":"))
                candidate = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate > local:
                    return candidate
        raise ValueError("未能计算下一触发时间")
    return croniter(trigger.cron, local).get_next(datetime)


def delivery_policy(
    *, origin: str, mode: str, now: datetime, window_end: datetime
) -> tuple[bool, str]:
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    if mode != "live" or origin == "replay":
        return False, "模拟或历史回放仅保留预览"
    if now - window_end > timedelta(minutes=150) or window_end > now:
        return False, "历史数据或未来时间窗不得对外推送"
    if origin == "scheduled":
        if local.hour < 9:
            return False, "首轮结果等待北京时间09:00"
        if local.hour >= 20:
            return False, "已超出定时推送时段"
    return True, "允许推送实时结果"
