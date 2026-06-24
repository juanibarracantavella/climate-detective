import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Settings
from app.models import AnalysisResult, Period
from app.summarizer import Summarizer


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
