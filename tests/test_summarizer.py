import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Settings
from app.models import AnalysisResult, Event, Period
from app.summarizer import SYSTEM_PROMPT, Summarizer, build_chat_payload


def test_summarizer_reads_openai_compatible_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "A calm day at home."}}]},
        )

    settings = Settings(
        nebius_base_url="https://model.example/v1",
        nebius_api_key="secret",
        nebius_model="test-model",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    summarizer = Summarizer(settings, client)
    start = datetime(2026, 6, 24, tzinfo=UTC)
    period = Period("today", start, start + timedelta(hours=1))
    analysis = AnalysisResult(
        statistics={"temperature_mean": 21.0, "humidity_mean": 45.0}, events=[]
    )

    summary, warning = asyncio.run(summarizer.summarize(period, analysis))
    asyncio.run(client.aclose())

    assert summary == "A calm day at home."
    assert warning is None


def test_missing_key_uses_fallback_without_network_request() -> None:
    settings = Settings(nebius_api_key="")
    summarizer = Summarizer(settings)
    start = datetime(2026, 6, 24, tzinfo=UTC)
    period = Period("today", start, start + timedelta(hours=1))
    analysis = AnalysisResult(
        statistics={
            "temperature_mean": 21.0,
            "humidity_mean": 45.0,
            "energy_kwh": 1.2,
        },
        events=[],
    )

    summary, warning = asyncio.run(summarizer.summarize(period, analysis))

    assert "21.0 °C" in summary
    assert warning == "Nebius is not configured; using local summary"


def test_missing_model_uses_fallback_without_network_request() -> None:
    settings = Settings(nebius_api_key="secret", nebius_model="")
    summarizer = Summarizer(settings)
    start = datetime(2026, 6, 24, tzinfo=UTC)
    period = Period("today", start, start + timedelta(hours=1))
    analysis = AnalysisResult(statistics={"temperature_mean": 21.0}, events=[])

    summary, warning = asyncio.run(summarizer.summarize(period, analysis))

    assert "21.0 °C" in summary
    assert warning == "Nebius is not configured; using local summary"


def test_chat_payload_contains_only_derived_facts() -> None:
    settings = Settings(nebius_model="demo-model")
    start = datetime(2026, 6, 24, tzinfo=UTC)
    period = Period("today", start, start + timedelta(hours=1))
    analysis = AnalysisResult(
        statistics={"temperature_mean": 21.0, "energy_kwh": 1.25},
        events=[
            Event(
                "temperature_drop",
                start,
                start + timedelta(minutes=30),
                -1.25,
                "°C",
            )
        ],
        warnings=["Humidity coverage is insufficient"],
    )

    payload = build_chat_payload(period, analysis, settings)
    facts = payload["messages"][1]["content"]

    assert payload["model"] == "demo-model"
    assert payload["max_tokens"] == 450
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert "two plain" in SYSTEM_PROMPT
    assert "keep every number and unit unchanged" in SYSTEM_PROMPT
    assert "PERIOD: 2026-06-24T00:00:00+00:00" in facts
    assert "MEASUREMENT: Temperature mean 21 °C." in facts
    assert "MEASUREMENT: Energy use 1.25 kWh." in facts
    assert "Temperature dropped 1.25 °C" in facts
    assert "WARNING: Humidity coverage is insufficient" in facts


def test_chat_payload_omits_empty_warnings() -> None:
    settings = Settings(nebius_model="demo-model")
    start = datetime(2026, 6, 24, tzinfo=UTC)
    period = Period("today", start, start + timedelta(hours=1))
    analysis = AnalysisResult(statistics={"temperature_mean": 21.0}, events=[])

    payload = build_chat_payload(period, analysis, settings)
    facts = payload["messages"][1]["content"]

    assert "WARNING:" not in facts
