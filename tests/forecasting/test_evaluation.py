"""Tests for load forecast evaluation."""

import pandas as pd
import pytest

from src.forecasting.evaluation import (
    METRIC_COLUMNS,
    calculate_forecast_metrics,
    join_forecasts_with_actuals,
)


def _make_forecasts() -> pd.DataFrame:
    origin = pd.Timestamp("2021-01-01T00:00:00Z")
    return pd.DataFrame(
        {
            "forecast_origin": [origin, origin],
            "forecast_timestamp": [
                origin + pd.Timedelta(hours=1),
                origin + pd.Timedelta(hours=2),
            ],
            "horizon_hours": [1, 2],
            "model_name": ["daily_naive", "daily_naive"],
            "prediction_kwh": [12.0, 8.0],
        }
    )


def _make_actuals() -> pd.DataFrame:
    index = pd.date_range("2021-01-01T00:00:00Z", periods=3, freq="h")
    return pd.DataFrame({"gross_load_kwh": [0.0, 10.0, 10.0]}, index=index)


def test_join_forecasts_with_actuals_and_calculate_metrics() -> None:
    evaluated_forecasts = join_forecasts_with_actuals(_make_forecasts(), _make_actuals())

    assert evaluated_forecasts["actual_kwh"].tolist() == [10.0, 10.0]
    assert evaluated_forecasts["error_kwh"].tolist() == [2.0, -2.0]
    assert evaluated_forecasts["absolute_error_kwh"].tolist() == [2.0, 2.0]
    assert evaluated_forecasts["squared_error_kwh"].tolist() == [4.0, 4.0]

    metrics = calculate_forecast_metrics(evaluated_forecasts)

    assert list(metrics.columns) == METRIC_COLUMNS
    overall = metrics.loc[metrics["metric_scope"] == "overall"].iloc[0]
    assert pd.isna(overall["horizon_hours"])
    assert overall["sample_count"] == 2
    assert overall["mae_kwh"] == pytest.approx(2.0)
    assert overall["rmse_kwh"] == pytest.approx(2.0)
    assert overall["bias_kwh"] == pytest.approx(0.0)
    assert overall["wape_percent"] == pytest.approx(20.0)

    by_horizon = metrics.loc[metrics["metric_scope"] == "horizon"]
    assert by_horizon["horizon_hours"].tolist() == [1, 2]
    assert by_horizon["sample_count"].tolist() == [1, 1]
    assert by_horizon["wape_percent"].tolist() == pytest.approx([20.0, 20.0])


def test_join_forecasts_rejects_duplicate_model_origin_target_pairs() -> None:
    forecasts = pd.concat([_make_forecasts(), _make_forecasts().iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate model"):
        join_forecasts_with_actuals(forecasts, _make_actuals())


def test_join_forecasts_allows_the_same_target_from_different_models() -> None:
    daily_forecasts = _make_forecasts()
    weekly_forecasts = _make_forecasts().assign(model_name="weekly_naive")

    evaluated_forecasts = join_forecasts_with_actuals(
        pd.concat([daily_forecasts, weekly_forecasts], ignore_index=True),
        _make_actuals(),
    )

    assert len(evaluated_forecasts) == 4
    assert evaluated_forecasts["model_name"].unique().tolist() == [
        "daily_naive",
        "weekly_naive",
    ]


def test_join_forecasts_rejects_missing_actual_timestamp() -> None:
    actuals = _make_actuals().iloc[:2]

    with pytest.raises(ValueError, match="missing from prepared actuals"):
        join_forecasts_with_actuals(_make_forecasts(), actuals)


def test_wape_is_undefined_when_total_actual_energy_is_zero() -> None:
    forecasts = _make_forecasts()
    actuals = _make_actuals().assign(gross_load_kwh=0.0)

    evaluated_forecasts = join_forecasts_with_actuals(forecasts, actuals)
    metrics = calculate_forecast_metrics(evaluated_forecasts)

    assert metrics["wape_percent"].isna().all()
