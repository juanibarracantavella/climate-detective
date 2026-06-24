from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings
from app.models import AnalysisResult, Period

SYSTEM_PROMPT = """You summarize household sensor facts in at most four short sentences.
Use only the supplied facts. Do not guess causes, occupancy, appliance identity, or safety.
State important missing-data warnings. Use friendly, plain language and preserve all units."""


class Summarizer:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def summarize(self, period: Period, analysis: AnalysisResult) -> tuple[str, str | None]:
        if not self.settings.nebius_api_key:
            return (
                fallback_summary(
                    analysis,
                    temperature_unit=self.settings.temperature_unit,
                    humidity_unit=self.settings.humidity_unit,
                ),
                "Nebius is not configured; using local summary",
            )

        facts = {
            "period": {
                "start": period.start.isoformat(),
                "end": period.end.isoformat(),
            },
            **analysis.facts(),
        }
        payload = {
            "model": self.settings.nebius_model,
            "temperature": 0.1,
            "max_tokens": 220,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(facts, separators=(",", ":"))},
            ],
        }
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
        summary += f" {len(analysis.events)} notable change(s) were detected."
    if analysis.warnings:
        summary += " Some sensor data was missing or incomplete."
    return summary
