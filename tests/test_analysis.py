from datetime import UTC, datetime, timedelta

import pytest

from app.analysis import analyze, cumulative_energy_delta, detect_changes, integrate_power
from app.config import Settings
from app.models import Period, Sample


def samples(start: datetime, values: list[float], minutes: int = 15) -> list[Sample]:
    return [
        Sample(timestamp=start + timedelta(minutes=index * minutes), value=value)
        for index, value in enumerate(values)
    ]


def test_analysis_calculates_statistics_energy_and_sustained_change() -> None:
    settings = Settings(
        temperature_entity="sensor.temperature",
        humidity_entity="sensor.humidity",
        power_entity="sensor.power",
    )
    start = datetime(2026, 6, 24, tzinfo=UTC)
    period = Period("test", start, start + timedelta(hours=1))
    history = {
        "sensor.temperature": samples(start, [20.0, 20.0, 22.0, 22.0]),
        "sensor.humidity": samples(start, [45.0, 45.0, 45.0, 45.0]),
        "sensor.power": samples(start, [1000.0] * 5),
    }

    result = analyze(history, period, settings)

    assert result.statistics["temperature_mean"] == 21.0
    assert result.statistics["temperature_coverage"] == 1.0
    assert result.statistics["energy_kwh"] == 1.0
    assert [event.kind for event in result.events] == ["temperature_rise"]
    assert result.warnings == []


def test_sparse_data_produces_warnings_instead_of_fabricated_values() -> None:
    settings = Settings(
        temperature_entity="sensor.temperature",
        humidity_entity="sensor.humidity",
        power_entity="sensor.power",
    )
    start = datetime(2026, 6, 24, tzinfo=UTC)
    period = Period("test", start, start + timedelta(hours=2))

    result = analyze({"sensor.temperature": samples(start, [20.0])}, period, settings)

    assert result.statistics["humidity_mean"] is None
    assert result.statistics["energy_kwh"] is None
    assert "No usable humidity data was found" in result.warnings
    assert "Temperature data coverage is below 50%" in result.warnings


def test_temperature_changes_are_split_at_significant_extremes() -> None:
    start = datetime(2026, 6, 24, tzinfo=UTC)
    readings = samples(start, [20.0, 22.0, 21.5, 23.0, 20.0, 20.5, 22.0])

    events = detect_changes(readings, "temperature", 1.5, "°C")

    assert [event.kind for event in events] == [
        "temperature_rise",
        "temperature_drop",
        "temperature_rise",
    ]
    assert [(event.start, event.end, event.change) for event in events] == [
        (start, start + timedelta(minutes=45), 3.0),
        (start + timedelta(minutes=45), start + timedelta(minutes=60), -3.0),
        (start + timedelta(minutes=60), start + timedelta(minutes=90), 2.0),
    ]


def test_humidity_changes_use_minimum_and_maximum_points() -> None:
    start = datetime(2026, 6, 24, tzinfo=UTC)
    readings = samples(start, [50.0, 48.0, 57.0, 55.0, 47.0])

    events = detect_changes(readings, "humidity", 8.0, "%")

    assert [event.kind for event in events] == ["humidity_rise", "humidity_drop"]
    assert events[0].start == start + timedelta(minutes=15)
    assert events[0].end == start + timedelta(minutes=30)
    assert events[0].change == 9.0
    assert events[1].start == start + timedelta(minutes=30)
    assert events[1].end == start + timedelta(minutes=60)
    assert events[1].change == -10.0


def test_calm_temperature_series_is_split_around_daily_extremes() -> None:
    start = datetime(2026, 6, 24, tzinfo=UTC)
    readings = samples(start, [20.0, 20.8, 19.7, 20.6])

    events = detect_changes(readings, "temperature", 1.5, "°C")

    assert [event.kind for event in events] == [
        "temperature_rise",
        "temperature_drop",
        "temperature_rise",
    ]
    assert [event.change for event in events] == pytest.approx([0.8, -1.1, 0.9])


def test_flat_environment_series_does_not_create_events() -> None:
    start = datetime(2026, 6, 24, tzinfo=UTC)

    assert detect_changes(samples(start, [20.0, 20.0, 20.0]), "temperature", 1.5, "°C") == []


def test_power_integration_skips_large_gaps() -> None:
    start = datetime(2026, 6, 24, tzinfo=UTC)
    readings = [
        Sample(start, 1000.0),
        Sample(start + timedelta(minutes=30), 1000.0),
        Sample(start + timedelta(hours=3), 1000.0),
    ]

    energy, coverage = integrate_power(readings, max_gap_minutes=60)

    assert energy == pytest.approx(0.5)
    assert coverage == pytest.approx(1 / 6)


def test_cumulative_energy_handles_meter_reset() -> None:
    start = datetime(2026, 6, 24, tzinfo=UTC)
    readings = samples(start, [10.0, 10.5, 0.1, 0.4])

    assert cumulative_energy_delta(readings) == pytest.approx(0.9)
