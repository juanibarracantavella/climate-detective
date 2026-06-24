import asyncio
import json
from datetime import timedelta

import httpx

from app.config import Settings
from app.main import create_app
from app.models import AnalysisResult, Period, Sample


class FakeHistory:
    async def history(self, period: Period) -> dict[str, list[Sample]]:
        return {
            "sensor.temperature": [Sample(period.start, 20.0)],
            "sensor.humidity": [Sample(period.start, 45.0)],
            "sensor.power": [
                Sample(period.start, 1000.0),
                Sample(min(period.start + timedelta(minutes=15), period.end), 1000.0),
            ],
        }


class FakeSummarizer:
    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, period: Period, analysis: AnalysisResult) -> tuple[str, str | None]:
        self.calls += 1
        return "Synthetic summary.", None


class FakeSnapshot:
    async def current_snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "entity_id": "sensor.temperature",
                "value": 21.5,
                "raw_state": "21.5",
                "unit": "°C",
                "friendly_name": "Temperature",
                "last_changed": "2026-06-24T10:00:00+00:00",
                "last_updated": "2026-06-24T10:00:00+00:00",
                "error": None,
            },
            {
                "entity_id": "sensor.missing",
                "value": None,
                "raw_state": None,
                "unit": None,
                "friendly_name": None,
                "last_changed": None,
                "last_updated": None,
                "error": "Home Assistant returned HTTP 404",
            },
        ]


def test_summary_endpoint_returns_inspectable_facts() -> None:
    settings = Settings(
        temperature_entity="sensor.temperature",
        humidity_entity="sensor.humidity",
        power_entity="sensor.power",
    )
    app = create_app(settings, FakeHistory(), FakeSummarizer())

    response = asyncio.run(get(app, "/api/summary", period="today"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == "Synthetic summary."
    assert payload["statistics"]["temperature_mean"] == 20.0
    assert payload["units"]["temperature"] == "°C"
    assert payload["period"]["name"] == "today"
    assert "events" in payload


def test_summary_endpoint_rejects_unknown_period() -> None:
    app = create_app(Settings(), FakeHistory(), FakeSummarizer())

    response = asyncio.run(get(app, "/api/summary", period="last_year"))

    assert response.status_code == 422
    assert "Unknown period" in response.json()["detail"]


def test_summary_prompt_endpoint_returns_exact_llm_body_without_inference() -> None:
    settings = Settings(
        temperature_entity="sensor.temperature",
        humidity_entity="sensor.humidity",
        power_entity="sensor.power",
        nebius_model="demo-model",
    )
    summarizer = FakeSummarizer()
    app = create_app(settings, FakeHistory(), summarizer)

    response = asyncio.run(get(app, "/api/summary-prompt", period="today"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "demo-model"
    assert payload["temperature"] == 0.1
    assert payload["max_tokens"] == 220
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["messages"][0]["role"] == "system"
    facts = json.loads(payload["messages"][1]["content"])
    assert facts["statistics"]["temperature_mean"] == 20.0
    assert facts["period"]["start"]
    assert "summary" not in payload
    assert summarizer.calls == 0


def test_home_sensors_endpoint_returns_successes_and_errors() -> None:
    app = create_app(Settings(), FakeHistory(), FakeSummarizer(), snapshot_source=FakeSnapshot())

    response = asyncio.run(get(app, "/api/home-sensors"))

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["sensors"]) == 2
    assert payload["sensors"][0]["value"] == 21.5
    assert payload["sensors"][1]["error"] == "Home Assistant returned HTTP 404"
    assert payload["fetched_at"].endswith("+00:00")


async def get(app, path: str, **params: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, params=params)
