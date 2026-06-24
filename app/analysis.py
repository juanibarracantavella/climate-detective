from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime

from app.config import Settings
from app.models import AnalysisResult, Event, Period, Sample


def analyze(history: dict[str, list[Sample]], period: Period, settings: Settings) -> AnalysisResult:
    temperature = _within(history.get(settings.temperature_entity, []), period)
    humidity = _within(history.get(settings.humidity_entity, []), period)
    power = _within(history.get(settings.power_entity, []), period, include_end=True)

    temperature_bins = resample_mean(temperature, settings.resample_minutes)
    humidity_bins = resample_mean(humidity, settings.resample_minutes)
    power_bins = resample_mean(power, settings.resample_minutes)

    warnings: list[str] = []
    expected_bins = max(
        1,
        math.ceil(
            (period.end.timestamp() - period.start.timestamp()) / (settings.resample_minutes * 60)
        ),
    )
    statistics_result: dict[str, float | int | None] = {}
    statistics_result.update(
        _environment_statistics("temperature", temperature_bins, expected_bins)
    )
    statistics_result.update(_environment_statistics("humidity", humidity_bins, expected_bins))

    if settings.power_kind == "power":
        energy_kwh, power_coverage = integrate_power(power, max_gap_minutes=60)
        statistics_result["energy_kwh"] = _rounded(energy_kwh)
        statistics_result["power_mean_w"] = _rounded(
            statistics.fmean(sample.value for sample in power_bins) if power_bins else None
        )
        statistics_result["power_coverage"] = _rounded(power_coverage)
    else:
        statistics_result["energy_kwh"] = _rounded(cumulative_energy_delta(power))
        statistics_result["power_mean_w"] = None
        statistics_result["power_coverage"] = _rounded(
            len(power_bins) / expected_bins if power_bins else 0.0
        )

    for label, samples in (
        ("temperature", temperature_bins),
        ("humidity", humidity_bins),
        ("power", power_bins),
    ):
        if not samples:
            warnings.append(f"No usable {label} data was found")
    for label in ("temperature", "humidity"):
        coverage = statistics_result.get(f"{label}_coverage")
        if isinstance(coverage, float) and coverage < 0.5:
            warnings.append(f"{label.title()} data coverage is below 50%")

    events = detect_changes(
        temperature_bins,
        "temperature",
        settings.temperature_change_threshold,
        settings.temperature_unit,
    )
    events.extend(
        detect_changes(
            humidity_bins,
            "humidity",
            settings.humidity_change_threshold,
            settings.humidity_unit,
        )
    )
    if settings.power_kind == "power":
        events.extend(
            detect_power_spikes(power_bins, settings.power_spike_threshold_w, settings.power_unit)
        )
    events.sort(key=lambda event: event.start)
    return AnalysisResult(statistics=statistics_result, events=events[:20], warnings=warnings)


def _within(samples: list[Sample], period: Period, *, include_end: bool = False) -> list[Sample]:
    if include_end:
        return [sample for sample in samples if period.start <= sample.timestamp <= period.end]
    return [sample for sample in samples if period.start <= sample.timestamp < period.end]


def resample_mean(samples: list[Sample], minutes: int) -> list[Sample]:
    if minutes <= 0:
        raise ValueError("Resampling interval must be positive")
    interval_seconds = minutes * 60
    buckets: dict[int, list[float]] = defaultdict(list)
    zones: dict[int, object] = {}
    for sample in samples:
        bucket = int(sample.timestamp.timestamp()) // interval_seconds * interval_seconds
        buckets[bucket].append(sample.value)
        zones[bucket] = sample.timestamp.tzinfo
    return [
        Sample(
            timestamp=datetime.fromtimestamp(bucket, tz=zones[bucket]),  # type: ignore[arg-type]
            value=statistics.fmean(values),
        )
        for bucket, values in sorted(buckets.items())
    ]


def _environment_statistics(
    name: str, samples: list[Sample], expected_bins: int
) -> dict[str, float | int | None]:
    values = [sample.value for sample in samples]
    return {
        f"{name}_count": len(values),
        f"{name}_coverage": _rounded(len(values) / expected_bins),
        f"{name}_min": _rounded(min(values) if values else None),
        f"{name}_max": _rounded(max(values) if values else None),
        f"{name}_mean": _rounded(statistics.fmean(values) if values else None),
    }


def detect_changes(
    samples: list[Sample], name: str, threshold: float, unit: str, min_bins: int = 2
) -> list[Event]:
    if len(samples) <= min_bins:
        return []

    candidates: list[Event] = []
    for index in range(min_bins, len(samples)):
        start_sample = samples[index - min_bins]
        end_sample = samples[index]
        change = end_sample.value - start_sample.value
        if abs(change) < threshold:
            continue
        direction = "rise" if change > 0 else "drop"
        candidates.append(
            Event(
                kind=f"{name}_{direction}",
                start=start_sample.timestamp,
                end=end_sample.timestamp,
                change=change,
                unit=unit,
            )
        )
    return merge_events(candidates)


def merge_events(events: list[Event]) -> list[Event]:
    merged: list[Event] = []
    for event in events:
        if merged and merged[-1].kind == event.kind and event.start <= merged[-1].end:
            previous = merged[-1]
            merged[-1] = Event(
                kind=previous.kind,
                start=previous.start,
                end=max(previous.end, event.end),
                change=previous.change
                if abs(previous.change) >= abs(event.change)
                else event.change,
                unit=previous.unit,
            )
        else:
            merged.append(event)
    return merged


def detect_power_spikes(samples: list[Sample], threshold_w: float, unit: str) -> list[Event]:
    if len(samples) < 3:
        return []
    baseline = statistics.median(sample.value for sample in samples)
    return [
        Event(
            kind="power_spike",
            start=sample.timestamp,
            end=sample.timestamp,
            change=sample.value - baseline,
            unit=unit,
        )
        for sample in samples
        if sample.value >= baseline + threshold_w
    ]


def integrate_power(samples: list[Sample], max_gap_minutes: int = 60) -> tuple[float | None, float]:
    ordered = sorted(samples, key=lambda sample: sample.timestamp)
    if len(ordered) < 2:
        return None, 0.0
    watt_seconds = 0.0
    covered_seconds = 0.0
    span_seconds = ordered[-1].timestamp.timestamp() - ordered[0].timestamp.timestamp()
    for first, second in zip(ordered, ordered[1:], strict=False):
        seconds = second.timestamp.timestamp() - first.timestamp.timestamp()
        if seconds <= 0 or seconds > max_gap_minutes * 60:
            continue
        watt_seconds += (first.value + second.value) / 2 * seconds
        covered_seconds += seconds
    coverage = covered_seconds / span_seconds if span_seconds > 0 else 0.0
    return watt_seconds / 3_600_000, min(1.0, coverage)


def cumulative_energy_delta(samples: list[Sample]) -> float | None:
    ordered = sorted(samples, key=lambda sample: sample.timestamp)
    if len(ordered) < 2:
        return None
    total = 0.0
    for first, second in zip(ordered, ordered[1:], strict=False):
        delta = second.value - first.value
        total += delta if delta >= 0 else max(0.0, second.value)
    return total


def _rounded(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None
