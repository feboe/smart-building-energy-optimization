"""Offline tests for SMARD ingestion helpers."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from src.database import MEASUREMENT_COLUMNS
from src.smard_client import SmardConfig
from src.smard_pipeline import (
    SmardSeries,
    extract_measurements,
    filter_chunk_timestamps,
    timestamp_ms_to_datetime,
)


def test_timestamp_ms_to_datetime_returns_utc_datetime() -> None:
    timestamp = timestamp_ms_to_datetime(1_609_459_200_000)

    assert timestamp == datetime(2021, 1, 1, tzinfo=timezone.utc)


def test_filter_chunk_timestamps_selects_overlapping_chunks() -> None:
    available_timestamps = [
        1_609_459_200_000,
        1_610_064_000_000,
        1_610_668_800_000,
    ]

    selected_timestamps = filter_chunk_timestamps(
        available_timestamps=available_timestamps,
        start_date=datetime(2021, 1, 5, tzinfo=timezone.utc),
        end_date=datetime(2021, 1, 8, tzinfo=timezone.utc),
    )

    assert selected_timestamps == [
        1_609_459_200_000,
        1_610_064_000_000,
    ]


def test_filter_chunk_timestamps_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="end_date"):
        filter_chunk_timestamps(
            available_timestamps=[1_609_459_200_000],
            start_date=datetime(2021, 1, 2, tzinfo=timezone.utc),
            end_date=datetime(2021, 1, 1, tzinfo=timezone.utc),
        )


def test_extract_smard_measurements_outputs_database_shape() -> None:
    series = SmardSeries(
        series_name="day_ahead_price",
        display_name="Day-ahead price",
        category="market_price",
        config=SmardConfig(
            smard_filter_id="4169",
            region="DE-LU",
            resolution="hour",
        ),
        unit="EUR/MWh",
    )
    payload = {
        "series": [
            [1_609_459_200_000, 50.0],
            [1_609_462_800_000, None],
        ]
    }

    measurements_df = extract_measurements(
        payload=payload,
        import_id=11,
        series=series,
    )

    assert list(measurements_df.columns) == MEASUREMENT_COLUMNS
    assert measurements_df["import_id"].tolist() == [11, 11]
    assert measurements_df["source_system"].tolist() == ["SMARD", "SMARD"]
    assert measurements_df["source_series_id"].tolist() == ["4169", "4169"]
    assert measurements_df["series_name"].tolist() == [
        "day_ahead_price",
        "day_ahead_price",
    ]
    assert measurements_df["category"].tolist() == ["market_price", "market_price"]
    assert measurements_df["region"].tolist() == ["DE-LU", "DE-LU"]
    assert measurements_df["resolution"].tolist() == ["hour", "hour"]
    assert measurements_df["unit"].tolist() == ["EUR/MWh", "EUR/MWh"]
    assert measurements_df["observation_timestamp"].tolist() == [
        pd.Timestamp("2021-01-01T00:00:00Z").to_pydatetime(),
        pd.Timestamp("2021-01-01T01:00:00Z").to_pydatetime(),
    ]
    assert measurements_df.loc[0, "value"] == pytest.approx(50.0)
    assert pd.isna(measurements_df.loc[1, "value"])


def test_extract_smard_measurements_rejects_missing_series() -> None:
    series = SmardSeries(
        series_name="day_ahead_price",
        display_name="Day-ahead price",
        category="market_price",
        config=SmardConfig(smard_filter_id="4169"),
    )

    with pytest.raises(ValueError, match="series"):
        extract_measurements(
            payload={},
            import_id=11,
            series=series,
        )
