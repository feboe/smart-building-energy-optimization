"""Tests for seasonal-naive load forecasters."""

import pandas as pd
import pytest

from src.forecasting.baselines import (
    FORECAST_COLUMNS,
    DailyNaiveForecaster,
    WeeklyNaiveForecaster,
)


def _make_prepared_data(periods: int = 240) -> pd.DataFrame:
    index = pd.date_range("2020-01-01T00:00:00Z", periods=periods, freq="h")
    return pd.DataFrame({"gross_load_kwh": range(periods)}, index=index)


@pytest.mark.parametrize(
    ("forecaster", "lag_hours", "model_name"),
    [
        (DailyNaiveForecaster(), 24, "daily_naive"),
        (WeeklyNaiveForecaster(), 168, "weekly_naive"),
    ],
)
def test_seasonal_naive_forecasters_use_the_expected_lag(
    forecaster: DailyNaiveForecaster | WeeklyNaiveForecaster,
    lag_hours: int,
    model_name: str,
) -> None:
    prepared_data = _make_prepared_data()
    origins = prepared_data.index[[180, 181]]

    assert forecaster.fit(prepared_data, origins) is forecaster
    forecasts = forecaster.predict(prepared_data, origins)

    assert list(forecasts.columns) == FORECAST_COLUMNS
    assert len(forecasts) == len(origins) * 24
    assert forecasts["forecast_origin"].dt.tz is not None
    assert str(forecasts["forecast_origin"].dt.tz) == "UTC"
    assert forecasts["forecast_timestamp"].dt.tz is not None
    assert str(forecasts["forecast_timestamp"].dt.tz) == "UTC"
    assert forecasts["model_name"].unique().tolist() == [model_name]
    assert not forecasts[["forecast_origin", "forecast_timestamp"]].duplicated().any()

    for origin in origins:
        forecast_for_origin = forecasts.loc[forecasts["forecast_origin"] == origin]
        assert forecast_for_origin["horizon_hours"].tolist() == list(range(1, 25))
        expected = [
            prepared_data.at[
                origin + pd.Timedelta(hours=horizon - lag_hours), "gross_load_kwh"
            ]
            for horizon in range(1, 25)
        ]
        assert forecast_for_origin["prediction_kwh"].tolist() == expected


def test_daily_naive_rejects_origins_without_sufficient_history() -> None:
    prepared_data = _make_prepared_data()

    with pytest.raises(ValueError, match="24 hours of historical context"):
        DailyNaiveForecaster().predict(prepared_data, prepared_data.index[[10]])


def test_weekly_naive_rejects_origins_without_sufficient_history() -> None:
    prepared_data = _make_prepared_data()

    with pytest.raises(ValueError, match="168 hours of historical context"):
        WeeklyNaiveForecaster().predict(prepared_data, prepared_data.index[[100]])


def test_forecaster_rejects_incomplete_forecast_horizon() -> None:
    prepared_data = _make_prepared_data()

    with pytest.raises(ValueError, match="complete forecast horizon"):
        DailyNaiveForecaster().predict(prepared_data, prepared_data.index[[-1]])


def test_forecaster_rejects_missing_target_column() -> None:
    prepared_data = _make_prepared_data().rename(
        columns={"gross_load_kwh": "different_target"}
    )

    with pytest.raises(ValueError, match="missing target column"):
        DailyNaiveForecaster().predict(
            prepared_data,
            pd.date_range("2020-01-02T00:00:00Z", periods=1, freq="h"),
        )


def test_forecaster_rejects_missing_source_target_value() -> None:
    prepared_data = _make_prepared_data()
    origin = prepared_data.index[180]
    prepared_data.loc[origin - pd.Timedelta(hours=23), "gross_load_kwh"] = None

    with pytest.raises(ValueError, match="source target.*missing"):
        DailyNaiveForecaster().predict(prepared_data, pd.DatetimeIndex([origin]))
