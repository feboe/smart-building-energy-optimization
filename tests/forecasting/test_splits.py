"""Tests for chronological load forecasting splits."""

import pandas as pd

from src.forecasting.config import ForecastConfig, ForecastSplit
from src.forecasting.evaluation import (
    select_forecast_split,
    select_valid_forecast_origins,
)

TRAINING_SPLIT = ForecastSplit(
    name="training",
    start=pd.Timestamp("2019-06-28T22:00:00Z"),
    end=pd.Timestamp("2020-10-01T00:00:00Z"),
)
VALIDATION_SPLIT = ForecastSplit(
    name="validation",
    start=pd.Timestamp("2020-10-01T00:00:00Z"),
    end=pd.Timestamp("2021-01-01T00:00:00Z"),
)
def test_select_forecast_split_uses_half_open_intervals() -> None:
    index = pd.date_range("2020-09-30T23:00:00Z", periods=3, freq="h")
    prepared_data = pd.DataFrame({"gross_load_kwh": [1.0, 2.0, 3.0]}, index=index)

    training_data = select_forecast_split(prepared_data, TRAINING_SPLIT)
    validation_data = select_forecast_split(prepared_data, VALIDATION_SPLIT)

    assert training_data.index.tolist() == [pd.Timestamp("2020-09-30T23:00:00Z")]
    assert validation_data.index.tolist() == [
        pd.Timestamp("2020-10-01T00:00:00Z"),
        pd.Timestamp("2020-10-01T01:00:00Z"),
    ]


def test_select_forecast_split_uses_custom_forecast_config() -> None:
    index = pd.date_range("2020-09-30T22:00:00Z", periods=3, freq="2h")
    prepared_data = pd.DataFrame({"custom_target": [1.0, 2.0, 3.0]}, index=index)
    config = ForecastConfig(target_column="custom_target", frequency="2h")

    selected_data = select_forecast_split(
        prepared_data,
        VALIDATION_SPLIT,
        config,
    )

    assert selected_data.index.tolist() == index[1:].tolist()


def test_select_valid_forecast_origins_excludes_missing_history_and_horizon() -> None:
    index = pd.date_range("2020-01-01T00:00:00Z", periods=240, freq="h")
    prepared_data = pd.DataFrame({"gross_load_kwh": range(len(index))}, index=index)
    small_split = ForecastSplit(name="small", start=index[50], end=index[220])

    origins = select_valid_forecast_origins(
        prepared_data,
        small_split,
        required_history_hours=168,
    )

    assert origins[0] == index[168]
    assert origins[-1] == index[195]
    assert len(origins) == 28
    assert origins[-1] + pd.Timedelta(hours=24) < small_split.end


def test_training_origins_wait_for_required_history() -> None:
    index = pd.date_range(
        TRAINING_SPLIT.start,
        periods=240,
        freq="h",
    )
    prepared_data = pd.DataFrame({"gross_load_kwh": range(len(index))}, index=index)

    origins = select_valid_forecast_origins(
        prepared_data,
        TRAINING_SPLIT,
        required_history_hours=168,
    )

    assert origins[0] == TRAINING_SPLIT.start + pd.Timedelta(hours=168)
    assert origins[-1] == index[-25]
