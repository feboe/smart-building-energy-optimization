"""Tests for forecasting configuration."""

import pytest

from src.forecasting.config import ForecastConfig


def test_forecast_config_has_load_forecasting_defaults() -> None:
    config = ForecastConfig()

    assert config.target_column == "gross_load_kwh"
    assert config.holiday_country == "DE"
    assert config.holiday_subdivision == "HE"
    assert config.frequency == "h"
    assert config.horizon_hours == 24


def test_forecast_config_rejects_nonpositive_horizon() -> None:
    with pytest.raises(ValueError, match="horizon_hours"):
        ForecastConfig(horizon_hours=0)


@pytest.mark.parametrize(
    ("option", "value"),
    [("holiday_country", ""), ("holiday_subdivision", "")],
)
def test_forecast_config_rejects_empty_holiday_configuration(
    option: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match=option):
        ForecastConfig(**{option: value})
