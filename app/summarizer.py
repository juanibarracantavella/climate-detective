from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.models import AnalysisResult, Event, Period

SYSTEM_PROMPT = """Write a friendly 100 to 160 word household sensor report in two plain
paragraphs. Use only the supplied fact lines and keep every number and unit unchanged. Paragraph one
summarizes the PERIOD and MEASUREMENT lines. Paragraph two narrates 3 to 6 notable EVENT lines in
chronological order, using one sentence per selected event. Include any WARNING lines naturally.
Do not add explanations, causes, conclusions, headings, bullets, or markdown."""


class Summarizer:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def summarize(self, period: Period, analysis: AnalysisResult) -> tuple[str, str | None]:
        if not self.settings.nebius_api_key or not self.settings.nebius_model:
            return (
                fallback_summary(
                    analysis,
                    temperature_unit=self.settings.temperature_unit,
                    humidity_unit=self.settings.humidity_unit,
                ),
                "Nebius is not configured; using local summary",
            )

        payload = build_chat_payload(period, analysis, self.settings)
        headers = {"Authorization": f"Bearer {self.settings.nebius_api_key}"}
        url = f"{self.settings.nebius_base_url}/chat/completions"
        try:
            if self._client is not None:
                response = await self._client.post(url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            content = _extract_content(response.json())
            return content, None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return (
                fallback_summary(
                    analysis,
                    temperature_unit=self.settings.temperature_unit,
                    humidity_unit=self.settings.humidity_unit,
                ),
                "Nebius summary failed; using local summary",
            )


def build_chat_payload(
    period: Period, analysis: AnalysisResult, settings: Settings
) -> dict[str, Any]:
    """Build the exact JSON body sent to the OpenAI-compatible endpoint."""
    return {
        "model": settings.nebius_model,
        "temperature": 0.1,
        "max_tokens": 450,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_fact_lines(period, analysis, settings)},
        ],
    }


def build_fact_lines(period: Period, analysis: AnalysisResult, settings: Settings) -> str:
    """Format derived facts so a small language model can copy them reliably."""
    lines = [f"PERIOD: {period.start.isoformat()} to {period.end.isoformat()}."]
    stats = analysis.statistics

    for label, unit in (
        ("temperature", settings.temperature_unit),
        ("humidity", settings.humidity_unit),
    ):
        values: list[str] = []
        for field, title in (("mean", "mean"), ("min", "minimum"), ("max", "maximum")):
            value = stats.get(f"{label}_{field}")
            if isinstance(value, (int, float)):
                values.append(f"{title} {_with_unit(value, unit)}")
        coverage = stats.get(f"{label}_coverage")
        if isinstance(coverage, (int, float)):
            values.append(f"coverage {_display_number(coverage * 100)}%")
        if values:
            lines.append(f"MEASUREMENT: {label.title()} {'; '.join(values)}.")

    power_values: list[str] = []
    energy = stats.get("energy_kwh")
    if isinstance(energy, (int, float)):
        power_values.append(f"energy use {_with_unit(energy, 'kWh')}")
    power_mean = stats.get("power_mean_w")
    if isinstance(power_mean, (int, float)):
        power_values.append(f"mean power {_with_unit(power_mean, settings.power_unit)}")
    power_coverage = stats.get("power_coverage")
    if isinstance(power_coverage, (int, float)):
        power_values.append(f"power coverage {_display_number(power_coverage * 100)}%")
    if power_values:
        power_text = "; ".join(power_values)
        lines.append(f"MEASUREMENT: {power_text[:1].upper()}{power_text[1:]}.")

    lines.extend(_event_fact(event) for event in analysis.events)
    lines.extend(f"WARNING: {warning}" for warning in analysis.warnings)
    return "\n".join(lines)


def _event_fact(event: Event) -> str:
    label, _, direction = event.kind.partition("_")
    if event.kind == "power_spike":
        return (
            f"EVENT: At {event.start.isoformat()}, power was "
            f"{_with_unit(abs(event.change), event.unit)} above the interval median."
        )
    verb = "rose" if direction == "rise" else "dropped" if direction == "drop" else "changed"
    return (
        f"EVENT: {label.title()} {verb} {_with_unit(abs(event.change), event.unit)} from "
        f"{event.start.isoformat()} to {event.end.isoformat()}."
    )


def _with_unit(value: float | int, unit: str) -> str:
    separator = "" if unit == "%" else " "
    return f"{_display_number(value)}{separator}{unit}"


def _display_number(value: float | int) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _extract_content(payload: Any) -> str:
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Empty LLM response")
    return content.strip()


def fallback_summary(
    analysis: AnalysisResult,
    temperature_unit: str = "°C",
    humidity_unit: str = "%",
) -> str:
    stats = analysis.statistics
    parts: list[str] = []
    temperature = stats.get("temperature_mean")
    humidity = stats.get("humidity_mean")
    energy = stats.get("energy_kwh")
    if isinstance(temperature, (float, int)):
        parts.append(f"The average temperature was {temperature:.1f} {temperature_unit}")
    if isinstance(humidity, (float, int)):
        parts.append(f"average humidity was {humidity:.1f}{humidity_unit}")
    if isinstance(energy, (float, int)):
        parts.append(f"estimated energy use was {energy:.2f} kWh")
    summary = ", and ".join(parts) + "." if parts else "No usable sensor data was found."
    if analysis.events:
        summary += f" {len(analysis.events)} sensor event(s) were detected."
    if analysis.warnings:
        summary += " Some sensor data was missing or incomplete."
    return summary
