from __future__ import annotations

import asyncio
import math
from datetime import datetime
from typing import Any

import httpx

from app.config import Settings
from app.models import Period, Sample


class HomeAssistantError(RuntimeError):
    """A safe-to-display Home Assistant integration failure."""


class HomeAssistantClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def history(self, period: Period) -> dict[str, list[Sample]]:
        if not self.settings.ha_token:
            raise HomeAssistantError("Home Assistant is not configured: HA_TOKEN is missing")

        url = f"{self.settings.ha_base_url}/api/history/period/{period.start.isoformat()}"
        params = {
            "end_time": period.end.isoformat(),
            "filter_entity_id": ",".join(self.settings.entity_ids),
            "minimal_response": "",
            "no_attributes": "",
        }
        headers = {"Authorization": f"Bearer {self.settings.ha_token}"}

        try:
            if self._client is not None:
                response = await self._client.get(url, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(
                    timeout=self.settings.request_timeout_seconds
                ) as client:
                    response = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise HomeAssistantError("Home Assistant timed out") from exc
        except httpx.HTTPError as exc:
            raise HomeAssistantError("Home Assistant could not be reached") from exc

        if response.status_code == 401:
            raise HomeAssistantError("Home Assistant rejected HA_TOKEN")
        if response.is_error:
            raise HomeAssistantError(f"Home Assistant returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise HomeAssistantError("Home Assistant returned invalid JSON") from exc
        return parse_history(payload, self.settings.entity_ids)

    async def current_snapshot(self) -> list[dict[str, Any]]:
        """Fetch all allowlisted current states, isolating failures per entity."""
        if not self.settings.ha_token:
            return [
                sensor_error(entity_id, "Home Assistant is not configured: HA_TOKEN is missing")
                for entity_id in self.settings.home_sensor_entity_ids
            ]

        headers = {
            "Authorization": f"Bearer {self.settings.ha_token}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            return await asyncio.gather(
                *(
                    self._fetch_current_sensor(self._client, entity_id, headers)
                    for entity_id in self.settings.home_sensor_entity_ids
                )
            )

        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
            return await asyncio.gather(
                *(
                    self._fetch_current_sensor(client, entity_id, headers)
                    for entity_id in self.settings.home_sensor_entity_ids
                )
            )

    async def _fetch_current_sensor(
        self,
        client: httpx.AsyncClient,
        entity_id: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        url = f"{self.settings.ha_base_url}/api/states/{entity_id}"
        try:
            response = await client.get(url, headers=headers)
        except httpx.TimeoutException:
            return sensor_error(entity_id, "Home Assistant timed out")
        except httpx.HTTPError:
            return sensor_error(entity_id, "Home Assistant could not be reached")

        if response.status_code == 401:
            return sensor_error(entity_id, "Home Assistant rejected HA_TOKEN")
        if response.is_error:
            return sensor_error(entity_id, f"Home Assistant returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            return sensor_error(entity_id, "Home Assistant returned invalid JSON")

        try:
            return normalize_current_state(payload, entity_id)
        except (TypeError, ValueError):
            return sensor_error(entity_id, "Home Assistant returned an invalid sensor state")


def parse_history(payload: Any, entity_ids: tuple[str, ...]) -> dict[str, list[Sample]]:
    if not isinstance(payload, list):
        raise HomeAssistantError("Home Assistant history has an unexpected shape")

    result = {entity_id: [] for entity_id in entity_ids}
    for group in payload:
        if not isinstance(group, list) or not group:
            continue
        entity_id = next(
            (
                item.get("entity_id")
                for item in group
                if isinstance(item, dict) and item.get("entity_id") in result
            ),
            None,
        )
        if entity_id is None:
            continue

        samples: dict[datetime, Sample] = {}
        for item in group:
            if not isinstance(item, dict):
                continue
            try:
                value = float(item["state"])
                timestamp = datetime.fromisoformat(item.get("last_changed") or item["last_updated"])
            except (KeyError, TypeError, ValueError):
                continue
            if timestamp.tzinfo is None:
                continue
            samples[timestamp] = Sample(timestamp=timestamp, value=value)
        result[entity_id] = sorted(samples.values(), key=lambda sample: sample.timestamp)
    return result


def normalize_current_state(payload: Any, requested_entity_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("State payload must be an object")
    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    raw_state = payload.get("state")
    value = numeric_state(raw_state)
    return {
        "entity_id": requested_entity_id,
        "value": value,
        "raw_state": raw_state,
        "unit": attributes.get("unit_of_measurement"),
        "friendly_name": attributes.get("friendly_name"),
        "last_changed": payload.get("last_changed"),
        "last_updated": payload.get("last_updated"),
        "error": None,
    }


def numeric_state(raw_state: Any) -> int | float | None:
    if isinstance(raw_state, bool) or raw_state is None:
        return None
    try:
        value = float(raw_state)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return int(value) if value.is_integer() else value


def sensor_error(entity_id: str, message: str) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "value": None,
        "raw_state": None,
        "unit": None,
        "friendly_name": None,
        "last_changed": None,
        "last_updated": None,
        "error": message,
    }
