"""Tests for chronological load forecasting splits."""

import pandas as pd

from src.forecasting.splits import (
    DEFAULT_FORECAST_SPLITS,
    EXTENDED_TRAINING_SPLIT,
    TEST_SPLIT,
    TRAINING_SPLIT,
    VALIDATION_SPLIT,
    ForecastSplit,
    select_forecast_split,
    select_valid_forecast_origins,
)


def test_default_splits_are_contiguous_and_non_overlapping() -> None:
    assert [split.name for split in DEFAULT_FORECAST_SPLITS] == [
        "training",
        "validation",
        "test",
    ]
    assert TRAINING_SPLIT.end == VALIDATION_SPLIT.start
    assert VALIDATION_SPLIT.end == TEST_SPLIT.start
    assert all(split.start < split.end for split in DEFAULT_FORECAST_SPLITS)


def test_extended_training_split_starts_at_pv_coverage_and_ends_at_validation() -> None:
    assert EXTENDED_TRAINING_SPLIT.start == pd.Timestamp("2019-06-28T22:00:00Z")
    assert EXTENDED_TRAINING_SPLIT.end == pd.Timestamp("2020-10-01T00:00:00Z")
    assert EXTENDED_TRAINING_SPLIT.end == VALIDATION_SPLIT.start


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


def test_select_valid_forecast_origins_excludes_missing_history_and_horizon() -> None:
    index = pd.date_range("2020-01-01T00:00:00Z", periods=240, freq="h")
    prepared_data = pd.DataFrame({"gross_load_kwh": range(len(index))}, index=index)
    small_split = ForecastSplit(name="small", start=index[50], end=index[220])

    origins = select_valid_forecast_origins(prepared_data, small_split)

    assert origins[0] == index[168]
    assert origins[-1] == index[195]
    assert len(origins) == 28
    assert origins[-1] + pd.Timedelta(hours=24) < small_split.end


def test_extended_training_origins_wait_for_required_history() -> None:
    index = pd.date_range(
        EXTENDED_TRAINING_SPLIT.start,
        periods=240,
        freq="h",
    )
    prepared_data = pd.DataFrame({"gross_load_kwh": range(len(index))}, index=index)

    origins = select_valid_forecast_origins(prepared_data, EXTENDED_TRAINING_SPLIT)

    assert origins[0] == EXTENDED_TRAINING_SPLIT.start + pd.Timedelta(hours=168)
    assert origins[-1] == index[-25]
