from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NebiusProfile = Literal["strong", "fast"]

HOME_SENSOR_ENTITY_IDS = (
    "sensor.meteo_aqara_balcony_temperature",
    "sensor.meteo_aqara_balcony_humidity",
    "sensor.abs_hum_balcony",
    "sensor.average_indoor_temperature",
    "sensor.average_indoor_humidity",
    "sensor.average_indoor_abs_hum",
    "sensor.total_power_meter_power",
)


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    ha_base_url: str = "https://home.cosasdejuan.es"
    ha_token: str = ""
    temperature_entity: str = "sensor.average_indoor_temperature"
    humidity_entity: str = "sensor.average_indoor_humidity"
    power_entity: str = "sensor.total_power_meter_power"
    home_sensor_entity_ids: tuple[str, ...] = HOME_SENSOR_ENTITY_IDS
    power_kind: Literal["power", "energy"] = "power"
    temperature_unit: str = "°C"
    humidity_unit: str = "%"
    power_unit: str = "W"
    home_timezone: str = "UTC"
    nebius_profile: NebiusProfile = "strong"
    nebius_base_url: str = "http://127.0.0.1:8000/v1"
    nebius_api_key: str = ""
    nebius_model: str = "Qwen/Qwen3-0.6B"
    request_timeout_seconds: float = 15.0
    llm_timeout_seconds: float = 30.0
    cache_ttl_seconds: int = 120
    resample_minutes: int = 15
    temperature_change_threshold: float = 1.5
    humidity_change_threshold: float = 8.0
    power_spike_threshold_w: float = 1000.0

    @classmethod
    def from_env(cls) -> Settings:
        power_kind = os.getenv("HA_POWER_KIND", "power").lower()
        if power_kind not in {"power", "energy"}:
            raise ConfigurationError("HA_POWER_KIND must be 'power' or 'energy'")

        nebius_profile = os.getenv("NEBIUS_PROFILE", "strong").lower()
        if nebius_profile not in {"strong", "fast"}:
            raise ConfigurationError("NEBIUS_PROFILE must be 'strong' or 'fast'")
        nebius_prefix = f"NEBIUS_{nebius_profile.upper()}_"
        nebius_base_url = os.getenv(
            f"{nebius_prefix}BASE_URL",
            os.getenv("NEBIUS_BASE_URL", "http://127.0.0.1:8000/v1"),
        )
        nebius_api_key = os.getenv(f"{nebius_prefix}API_KEY", os.getenv("NEBIUS_API_KEY", ""))
        nebius_model = os.getenv(
            f"{nebius_prefix}MODEL", os.getenv("NEBIUS_MODEL", "Qwen/Qwen3-0.6B")
        )

        settings = cls(
            ha_base_url=os.getenv("HA_BASE_URL", "https://home.cosasdejuan.es").rstrip("/"),
            ha_token=os.getenv("HA_TOKEN", ""),
            temperature_entity=os.getenv(
                "HA_TEMPERATURE_ENTITY", "sensor.average_indoor_temperature"
            ),
            humidity_entity=os.getenv("HA_HUMIDITY_ENTITY", "sensor.average_indoor_humidity"),
            power_entity=os.getenv("HA_POWER_ENTITY", "sensor.total_power_meter_power"),
            power_kind=power_kind,  # type: ignore[arg-type]
            temperature_unit=os.getenv("HA_TEMPERATURE_UNIT", "°C"),
            humidity_unit=os.getenv("HA_HUMIDITY_UNIT", "%"),
            power_unit=os.getenv("HA_POWER_UNIT", "W"),
            home_timezone=os.getenv("HOME_TIMEZONE", "UTC"),
            nebius_profile=nebius_profile,  # type: ignore[arg-type]
            nebius_base_url=_openai_base_url(nebius_base_url),
            nebius_api_key=nebius_api_key,
            nebius_model=nebius_model,
        )
        settings.timezone()
        return settings

    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.home_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"Unknown HOME_TIMEZONE: {self.home_timezone}") from exc

    @property
    def entity_ids(self) -> tuple[str, str, str]:
        return self.temperature_entity, self.humidity_entity, self.power_entity


def _openai_base_url(url: str) -> str:
    base_url = url.rstrip("/")
    return base_url if base_url.endswith("/v1") else f"{base_url}/v1"
