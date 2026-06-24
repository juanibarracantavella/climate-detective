import pytest

from app.config import ConfigurationError, Settings

NEBIUS_ENVIRONMENT_VARIABLES = (
    "NEBIUS_PROFILE",
    "NEBIUS_BASE_URL",
    "NEBIUS_API_KEY",
    "NEBIUS_MODEL",
    "NEBIUS_FAST_BASE_URL",
    "NEBIUS_FAST_API_KEY",
    "NEBIUS_FAST_MODEL",
    "NEBIUS_STRONG_BASE_URL",
    "NEBIUS_STRONG_API_KEY",
    "NEBIUS_STRONG_MODEL",
)


def test_strong_nebius_profile_is_selected_and_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_nebius_environment(monkeypatch)
    monkeypatch.setenv("NEBIUS_PROFILE", "strong")
    monkeypatch.setenv("NEBIUS_STRONG_BASE_URL", "https://strong.example")
    monkeypatch.setenv("NEBIUS_STRONG_API_KEY", "strong-secret")
    monkeypatch.setenv("NEBIUS_STRONG_MODEL", "strong-model")

    settings = Settings.from_env()

    assert settings.nebius_profile == "strong"
    assert settings.nebius_base_url == "https://strong.example/v1"
    assert settings.nebius_api_key == "strong-secret"
    assert settings.nebius_model == "strong-model"


def test_fast_nebius_profile_can_be_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_nebius_environment(monkeypatch)
    monkeypatch.setenv("NEBIUS_PROFILE", "fast")
    monkeypatch.setenv("NEBIUS_FAST_BASE_URL", "https://fast.example/v1/")
    monkeypatch.setenv("NEBIUS_FAST_API_KEY", "fast-secret")
    monkeypatch.setenv("NEBIUS_FAST_MODEL", "fast-model")

    settings = Settings.from_env()

    assert settings.nebius_profile == "fast"
    assert settings.nebius_base_url == "https://fast.example/v1"
    assert settings.nebius_api_key == "fast-secret"
    assert settings.nebius_model == "fast-model"


def test_unknown_nebius_profile_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_nebius_environment(monkeypatch)
    monkeypatch.setenv("NEBIUS_PROFILE", "other")

    with pytest.raises(ConfigurationError, match="NEBIUS_PROFILE"):
        Settings.from_env()


def _clear_nebius_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NEBIUS_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
