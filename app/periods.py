from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import Period

SUPPORTED_PERIODS = ("today", "yesterday", "last_7_days")


def resolve_period(name: str, timezone: ZoneInfo, now: datetime | None = None) -> Period:
    if name not in SUPPORTED_PERIODS:
        supported = ", ".join(SUPPORTED_PERIODS)
        raise ValueError(f"Unknown period '{name}'. Expected one of: {supported}")

    current = now or datetime.now(timezone)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone).replace(second=0, microsecond=0)
    today_start = datetime.combine(current.date(), time.min, tzinfo=timezone)

    if name == "today":
        return Period(name=name, start=today_start, end=current)
    if name == "yesterday":
        start = datetime.combine(current.date() - timedelta(days=1), time.min, tzinfo=timezone)
        return Period(name=name, start=start, end=today_start)

    start = datetime.combine(current.date() - timedelta(days=6), time.min, tzinfo=timezone)
    return Period(name=name, start=start, end=current)
