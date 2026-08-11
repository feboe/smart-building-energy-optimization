"""Tests for leakage-safe load forecast features."""

from statistics import pstdev

import pandas as pd
import pandas.testing as pdt
import pytest

from src.forecasting.features import (
    FEATURE_METADATA_COLUMNS,
    LOAD_FEATURE_COLUMNS,
    TARGET_FEATURE_COLUMN,
    build_forecast_features,
)
from src.forecasting.config import ForecastConfig


def _make_prepared_data(
    periods: int = 240,
    start: str = "2020-10-17T00:00:00Z",
) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="h")
    local_index = index.tz_convert("Europe/Berlin")
    local_isodow = local_index.dayofweek + 1
    return pd.DataFrame(
        {
            "gross_load_kwh": range(periods),
            "local_timestamp": local_index,
            "local_hour": local_index.hour,
            "local_isodow": local_isodow,
            "is_weekend": local_isodow.isin([6, 7]),
            "local_month": local_index.month,
        },
        index=index,
    )


def test_build_forecast_features_uses_expected_calendar_and_load_values() -> None:
    prepared_data = _make_prepared_data()
    origin = pd.Timestamp("2020-10-25T00:00:00Z")

    features = build_forecast_features(
        prepared_data,
        pd.DatetimeIndex([origin]),
        include_target=True,
    )

    assert list(features.columns) == [
        *FEATURE_METADATA_COLUMNS,
        *LOAD_FEATURE_COLUMNS,
        TARGET_FEATURE_COLUMN,
    ]
    assert len(features) == 24

    first_horizon = features.iloc[0]
    assert first_horizon["forecast_timestamp"] == pd.Timestamp("2020-10-25T01:00:00Z")
    assert first_horizon["horizon_hours"] == 1
    assert first_horizon["target_local_hour"] == 2
    assert first_horizon["target_local_isodow"] == 7
    assert first_horizon["target_is_weekend"]
    assert first_horizon["target_local_month"] == 10
    assert not first_horizon["target_is_holiday"]
    assert not first_horizon["target_is_bridge_day"]
    assert not first_horizon["target_is_christmas_shutdown"]

    origin_position = prepared_data.index.get_loc(origin)
    assert first_horizon["load_same_hour_previous_day"] == origin_position - 23
    assert first_horizon["load_same_hour_previous_week"] == origin_position - 167
    assert first_horizon["load_current"] == origin_position
    assert first_horizon["load_lag_1h"] == origin_position - 1
    assert first_horizon["load_lag_24h"] == origin_position - 24
    assert first_horizon["load_lag_168h"] == origin_position - 168
    assert first_horizon["load_mean_24h"] == pytest.approx(
        sum(range(origin_position - 23, origin_position + 1)) / 24
    )
    assert first_horizon["load_std_24h"] == pytest.approx(
        pstdev(range(origin_position - 23, origin_position + 1))
    )
    assert first_horizon["load_mean_168h"] == pytest.approx(
        sum(range(origin_position - 167, origin_position + 1)) / 168
    )
    assert first_horizon[TARGET_FEATURE_COLUMN] == origin_position + 1


def test_features_use_the_target_timestamp_calendar_across_dst() -> None:
    prepared_data = _make_prepared_data()
    origin = pd.Timestamp("2020-10-25T00:00:00Z")

    features = build_forecast_features(prepared_data, pd.DatetimeIndex([origin]))

    assert features.loc[0, "forecast_timestamp"] == pd.Timestamp("2020-10-25T01:00:00Z")
    assert features.loc[0, "target_local_hour"] == 2
    assert features.loc[1, "forecast_timestamp"] == pd.Timestamp("2020-10-25T02:00:00Z")
    assert features.loc[1, "target_local_hour"] == 3


def test_features_flag_hessian_public_holidays_and_bridge_days() -> None:
    prepared_data = _make_prepared_data(
        periods=400,
        start="2020-05-10T00:00:00Z",
    )
    holiday_origin = pd.Timestamp("2020-05-20T21:00:00Z")
    bridge_day_origin = pd.Timestamp("2020-05-21T21:00:00Z")

    holiday_features = build_forecast_features(
        prepared_data,
        pd.DatetimeIndex([holiday_origin]),
    )
    bridge_day_features = build_forecast_features(
        prepared_data,
        pd.DatetimeIndex([bridge_day_origin]),
    )

    assert holiday_features.loc[0, "forecast_timestamp"] == pd.Timestamp(
        "2020-05-20T22:00:00Z"
    )
    assert holiday_features.loc[0, "target_is_holiday"]
    assert not holiday_features.loc[0, "target_is_bridge_day"]
    assert bridge_day_features.loc[0, "forecast_timestamp"] == pd.Timestamp(
        "2020-05-21T22:00:00Z"
    )
    assert not bridge_day_features.loc[0, "target_is_holiday"]
    assert bridge_day_features.loc[0, "target_is_bridge_day"]


def test_features_flag_the_observed_christmas_shutdown_window() -> None:
    prepared_data = _make_prepared_data(
        periods=600,
        start="2020-12-10T00:00:00Z",
    )
    shutdown_start_origin = pd.Timestamp("2020-12-23T22:00:00Z")
    shutdown_end_origin = pd.Timestamp("2021-01-01T22:00:00Z")
    after_shutdown_origin = pd.Timestamp("2021-01-02T22:00:00Z")

    shutdown_start_features = build_forecast_features(
        prepared_data,
        pd.DatetimeIndex([shutdown_start_origin]),
    )
    shutdown_end_features = build_forecast_features(
        prepared_data,
        pd.DatetimeIndex([shutdown_end_origin]),
    )
    after_shutdown_features = build_forecast_features(
        prepared_data,
        pd.DatetimeIndex([after_shutdown_origin]),
    )

    assert shutdown_start_features.loc[0, "forecast_timestamp"] == pd.Timestamp(
        "2020-12-23T23:00:00Z"
    )
    assert shutdown_start_features.loc[0, "target_is_christmas_shutdown"]
    assert shutdown_end_features.loc[0, "forecast_timestamp"] == pd.Timestamp(
        "2021-01-01T23:00:00Z"
    )
    assert shutdown_end_features.loc[0, "target_is_christmas_shutdown"]
    assert after_shutdown_features.loc[0, "forecast_timestamp"] == pd.Timestamp(
        "2021-01-02T23:00:00Z"
    )
    assert not after_shutdown_features.loc[0, "target_is_christmas_shutdown"]


def test_features_do_not_change_when_future_load_values_change() -> None:
    prepared_data = _make_prepared_data()
    origin = pd.Timestamp("2020-10-25T00:00:00Z")

    original_features = build_forecast_features(
        prepared_data,
        pd.DatetimeIndex([origin]),
    )
    changed_data = prepared_data.copy()
    changed_data.loc[changed_data.index > origin, "gross_load_kwh"] = -999.0

    changed_features = build_forecast_features(
        changed_data,
        pd.DatetimeIndex([origin]),
    )

    pdt.assert_frame_equal(original_features, changed_features)


def test_feature_builder_rejects_insufficient_history() -> None:
    prepared_data = _make_prepared_data()

    with pytest.raises(ValueError, match="168 hours of historical context"):
        build_forecast_features(prepared_data, prepared_data.index[[100]])


def test_feature_builder_rejects_incomplete_horizon() -> None:
    prepared_data = _make_prepared_data()

    with pytest.raises(ValueError, match="complete forecast horizon"):
        build_forecast_features(prepared_data, prepared_data.index[[-1]])


def test_feature_builder_rejects_horizons_that_would_leak() -> None:
    prepared_data = _make_prepared_data(periods=300)

    with pytest.raises(ValueError, match="at most a 24-hour horizon"):
        build_forecast_features(
            prepared_data,
            prepared_data.index[[200]],
            forecast_config=ForecastConfig(horizon_hours=25),
        )
