import asyncio

import httpx

from app.config import Settings
from app.home_assistant import HomeAssistantClient, numeric_state, parse_history


def test_parse_history_handles_minimal_response_and_bad_states() -> None:
    payload = [
        [
            {
                "entity_id": "sensor.temperature",
                "state": "20.0",
                "last_changed": "2026-06-24T10:00:00+00:00",
            },
            {"state": "unavailable", "last_changed": "2026-06-24T10:10:00+00:00"},
            {"state": "21.5", "last_changed": "2026-06-24T10:15:00+00:00"},
            {"state": "22.0", "last_changed": "not-a-date"},
        ]
    ]

    result = parse_history(payload, ("sensor.temperature", "sensor.humidity"))

    assert [sample.value for sample in result["sensor.temperature"]] == [20.0, 21.5]
    assert result["sensor.humidity"] == []


def test_current_snapshot_normalizes_values_and_isolates_sensor_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.headers["content-type"] == "application/json"
        if request.url.path.endswith("sensor.temperature"):
            return httpx.Response(
                200,
                json={
                    "entity_id": "sensor.temperature",
                    "state": "21.75",
                    "attributes": {
                        "unit_of_measurement": "°C",
                        "friendly_name": "Indoor temperature",
                    },
                    "last_changed": "2026-06-24T10:00:00+00:00",
                    "last_updated": "2026-06-24T10:01:00+00:00",
                },
            )
        return httpx.Response(404, json={"message": "Entity not found"})

    settings = Settings(
        ha_base_url="https://home.example",
        ha_token="test-token",
        home_sensor_entity_ids=("sensor.temperature", "sensor.missing"),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    home_assistant = HomeAssistantClient(settings, client)

    snapshot = asyncio.run(home_assistant.current_snapshot())
    asyncio.run(client.aclose())

    assert snapshot[0] == {
        "entity_id": "sensor.temperature",
        "value": 21.75,
        "raw_state": "21.75",
        "unit": "°C",
        "friendly_name": "Indoor temperature",
        "last_changed": "2026-06-24T10:00:00+00:00",
        "last_updated": "2026-06-24T10:01:00+00:00",
        "error": None,
    }
    assert snapshot[1]["entity_id"] == "sensor.missing"
    assert snapshot[1]["value"] is None
    assert snapshot[1]["error"] == "Home Assistant returned HTTP 404"


def test_numeric_state_rejects_non_finite_and_non_numeric_values() -> None:
    assert numeric_state("42") == 42
    assert numeric_state("42.5") == 42.5
    assert numeric_state("unavailable") is None
    assert numeric_state("nan") is None
