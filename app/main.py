from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from app.analysis import analyze
from app.config import Settings
from app.home_assistant import HomeAssistantClient, HomeAssistantError
from app.models import AnalysisResult, Period, Sample
from app.periods import resolve_period
from app.summarizer import Summarizer, build_chat_payload


class HistorySource(Protocol):
    async def history(self, period: Period) -> dict[str, list[Sample]]: ...


class SnapshotSource(Protocol):
    async def current_snapshot(self) -> list[dict[str, Any]]: ...


class SummarySource(Protocol):
    async def summarize(
        self, period: Period, analysis: AnalysisResult
    ) -> tuple[str, str | None]: ...


@dataclass(slots=True)
class CacheEntry:
    expires_at: float
    value: dict[str, Any]


def create_app(
    settings: Settings | None = None,
    history_source: HistorySource | None = None,
    summary_source: SummarySource | None = None,
    snapshot_source: SnapshotSource | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    default_home_assistant = HomeAssistantClient(resolved_settings)
    home_assistant = history_source or default_home_assistant
    home_sensors = snapshot_source or default_home_assistant
    summarizer = summary_source or Summarizer(resolved_settings)
    cache: dict[str, CacheEntry] = {}

    application = FastAPI(
        title="Climate Detective",
        version="0.1.0",
        description="Explain Home Assistant climate and energy history.",
    )

    @application.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/home-sensors")
    async def home_sensor_snapshot() -> dict[str, Any]:
        try:
            sensors = await home_sensors.current_snapshot()
        except HomeAssistantError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "fetched_at": datetime.now(UTC).isoformat(),
            "sensors": sensors,
        }

    @application.get("/api/summary")
    async def summary(
        period: str = Query(default="today", description="Calendar period preset"),
    ) -> dict[str, Any]:
        try:
            resolved_period = resolve_period(period, resolved_settings.timezone())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        cache_key = (
            f"{resolved_period.name}:{resolved_period.start.isoformat()}:"
            f"{resolved_period.end.isoformat()}"
        )
        cached = cache.get(cache_key)
        if cached and cached.expires_at > time.monotonic():
            return cached.value

        try:
            history = await home_assistant.history(resolved_period)
        except HomeAssistantError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        result = analyze(history, resolved_period, resolved_settings)
        summary_text, summary_warning = await summarizer.summarize(resolved_period, result)
        warnings = [*result.warnings]
        if summary_warning:
            warnings.append(summary_warning)

        response = {
            "period": {
                "name": resolved_period.name,
                "start": resolved_period.start.isoformat(),
                "end": resolved_period.end.isoformat(),
            },
            "summary": summary_text,
            "events": [event.as_dict() for event in result.events],
            "statistics": result.statistics,
            "units": {
                "temperature": resolved_settings.temperature_unit,
                "humidity": resolved_settings.humidity_unit,
                "energy": "kWh",
                "power": resolved_settings.power_unit,
            },
            "warnings": warnings,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        cache[cache_key] = CacheEntry(
            expires_at=time.monotonic() + resolved_settings.cache_ttl_seconds,
            value=response,
        )
        return response

    @application.get("/api/summary-prompt")
    async def summary_prompt(
        period: str = Query(default="today", description="Calendar period preset"),
    ) -> dict[str, Any]:
        """Return the exact LLM request body without invoking the LLM."""
        try:
            resolved_period = resolve_period(period, resolved_settings.timezone())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            history = await home_assistant.history(resolved_period)
        except HomeAssistantError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        result = analyze(history, resolved_period, resolved_settings)
        return build_chat_payload(resolved_period, result, resolved_settings)

    static_directory = Path(__file__).resolve().parent.parent / "static"
    application.mount("/", StaticFiles(directory=static_directory, html=True), name="static")
    return application


app = create_app()
