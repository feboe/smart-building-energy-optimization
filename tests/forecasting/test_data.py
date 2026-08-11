"""Tests for forecasting data preparation."""

import pandas as pd
import pytest

from src.forecasting.data import prepare_forecasting_data


def _make_forecasting_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_prepare_forecasting_data_uses_utc_index_and_imputes_flagged_target() -> None:
    forecasting_df = _make_forecasting_df(
        [
            {
                "observation_timestamp": "2020-10-25T00:00:00Z",
                "local_timestamp": "2020-10-25 02:00:00",
                "gross_load_raw_kwh": 100.0,
                "gross_load_kwh": 100.0,
                "gross_load_quality_issue": None,
            },
            {
                "observation_timestamp": "2020-10-25T01:00:00Z",
                "local_timestamp": "2020-10-25 02:00:00",
                "gross_load_raw_kwh": -4.68,
                "gross_load_kwh": None,
                "gross_load_quality_issue": "negative_gross_load",
            },
            {
                "observation_timestamp": "2020-10-25T02:00:00Z",
                "local_timestamp": "2020-10-25 03:00:00",
                "gross_load_raw_kwh": 300.0,
                "gross_load_kwh": 300.0,
                "gross_load_quality_issue": None,
            },
        ]
    )

    prepared_df = prepare_forecasting_data(forecasting_df)

    assert prepared_df.index.equals(
        pd.date_range("2020-10-25T00:00:00Z", periods=3, freq="h")
    )
    assert prepared_df["gross_load_kwh"].tolist() == pytest.approx([100.0, 200.0, 300.0])
    assert prepared_df["gross_load_was_imputed"].tolist() == [False, True, False]
    assert prepared_df.loc[pd.Timestamp("2020-10-25T01:00:00Z"), "local_timestamp"] == pd.Timestamp(
        "2020-10-25 02:00:00"
    )


def test_prepare_forecasting_data_rejects_unflagged_timestamp_gap() -> None:
    forecasting_df = _make_forecasting_df(
        [
            {
                "observation_timestamp": "2020-01-01T00:00:00Z",
                "local_timestamp": "2020-01-01 01:00:00",
                "gross_load_raw_kwh": 100.0,
                "gross_load_kwh": 100.0,
                "gross_load_quality_issue": None,
            },
            {
                "observation_timestamp": "2020-01-01T02:00:00Z",
                "local_timestamp": "2020-01-01 03:00:00",
                "gross_load_raw_kwh": 300.0,
                "gross_load_kwh": 300.0,
                "gross_load_quality_issue": None,
            },
        ]
    )

    with pytest.raises(ValueError, match="remains missing"):
        prepare_forecasting_data(forecasting_df)


def test_prepare_forecasting_data_rejects_duplicate_utc_timestamps() -> None:
    forecasting_df = _make_forecasting_df(
        [
            {
                "observation_timestamp": "2020-01-01T00:00:00Z",
                "local_timestamp": "2020-01-01 01:00:00",
                "gross_load_raw_kwh": 100.0,
                "gross_load_kwh": 100.0,
                "gross_load_quality_issue": None,
            },
            {
                "observation_timestamp": "2020-01-01T00:00:00Z",
                "local_timestamp": "2020-01-01 01:00:00",
                "gross_load_raw_kwh": 200.0,
                "gross_load_kwh": 200.0,
                "gross_load_quality_issue": None,
            },
        ]
    )

    with pytest.raises(ValueError, match="duplicate"):
        prepare_forecasting_data(forecasting_df)


def test_prepare_forecasting_data_rejects_missing_required_columns() -> None:
    forecasting_df = pd.DataFrame(
        {
            "observation_timestamp": ["2020-01-01T00:00:00Z"],
            "gross_load_kwh": [100.0],
        }
    )

    with pytest.raises(ValueError, match="Missing forecasting columns"):
        prepare_forecasting_data(forecasting_df)
