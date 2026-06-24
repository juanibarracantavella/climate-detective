from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.periods import resolve_period


def test_today_starts_at_local_midnight_and_ends_at_current_minute() -> None:
    timezone = ZoneInfo("Europe/Amsterdam")
    now = datetime(2026, 6, 24, 13, 42, 38, tzinfo=timezone)

    period = resolve_period("today", timezone, now)

    assert period.start == datetime(2026, 6, 24, 0, 0, tzinfo=timezone)
    assert period.end == datetime(2026, 6, 24, 13, 42, tzinfo=timezone)


def test_yesterday_spans_25_hours_across_fall_dst_transition() -> None:
    timezone = ZoneInfo("Europe/Amsterdam")
    now = datetime(2025, 10, 27, 12, 0, tzinfo=timezone)

    period = resolve_period("yesterday", timezone, now)

    elapsed_hours = (period.end.timestamp() - period.start.timestamp()) / 3600
    assert period.start.date().isoformat() == "2025-10-26"
    assert elapsed_hours == 25


def test_last_seven_days_includes_today_and_six_previous_dates() -> None:
    timezone = ZoneInfo("UTC")
    now = datetime(2026, 6, 24, 12, 0, tzinfo=timezone)

    period = resolve_period("last_7_days", timezone, now)

    assert period.start.isoformat() == "2026-06-18T00:00:00+00:00"
    assert period.end == now


def test_unknown_period_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown period"):
        resolve_period("last_year", ZoneInfo("UTC"))
