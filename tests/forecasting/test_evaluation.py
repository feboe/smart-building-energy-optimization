"""Tests for load forecast evaluation."""

import pandas as pd
import pytest

from src.forecasting.config import (
    ForecastConfig,
    ForecastExperimentConfig,
    ForecastSplit,
)
from src.forecasting.evaluation import (
    EVALUATED_FORECAST_COLUMNS,
    EVALUATION_FORECAST_COLUMNS,
    METRIC_COLUMNS,
    ForecastEvaluationResult,
    calculate_forecast_metrics,
    join_forecasts_with_actuals,
    run_forecast_evaluation,
)
from src.forecasting.models import DailyNaiveForecaster


class _RecordingForecaster:
    required_history_hours = 12

    def __init__(self) -> None:
        self.training_origins: pd.DatetimeIndex | None = None

    def fit(
        self,
        prepared_data: pd.DataFrame,
        training_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> "_RecordingForecaster":
        self.training_origins = training_origins
        return self

    def predict(
        self,
        prepared_data: pd.DataFrame,
        forecast_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> pd.DataFrame:
        config = forecast_config or ForecastConfig()
        return pd.DataFrame(
            {
                "forecast_origin": forecast_origins,
                "forecast_timestamp": forecast_origins + pd.Timedelta(hours=1),
                "horizon_hours": 1,
                "model_name": "recording_forecaster",
                "prediction_kwh": [
                    prepared_data.at[
                        origin + pd.Timedelta(hours=1),
                        config.target_column,
                    ]
                    for origin in forecast_origins
                ],
            }
        )


def _make_forecasts(experiment_name: str = "daily_validation") -> pd.DataFrame:
    origin = pd.Timestamp("2021-01-01T00:00:00Z")
    return pd.DataFrame(
        {
            "experiment_name": [experiment_name, experiment_name],
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

    assert list(evaluated_forecasts.columns) == EVALUATED_FORECAST_COLUMNS
    assert evaluated_forecasts["actual_kwh"].tolist() == [10.0, 10.0]
    assert evaluated_forecasts["error_kwh"].tolist() == [2.0, -2.0]
    assert evaluated_forecasts["absolute_error_kwh"].tolist() == [2.0, 2.0]
    assert evaluated_forecasts["squared_error_kwh"].tolist() == [4.0, 4.0]

    metrics = calculate_forecast_metrics(evaluated_forecasts)

    assert list(metrics.columns) == METRIC_COLUMNS
    overall = metrics.loc[metrics["metric_scope"] == "overall"].iloc[0]
    assert overall["experiment_name"] == "daily_validation"
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


@pytest.mark.parametrize("invalid_prediction", [float("nan"), float("inf")])
def test_join_forecasts_rejects_non_finite_predictions(
    invalid_prediction: float,
) -> None:
    forecasts = _make_forecasts().assign(prediction_kwh=[invalid_prediction, 8.0])

    with pytest.raises(ValueError, match="prediction_kwh values must be finite"):
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


def test_evaluation_keeps_the_same_model_separate_across_experiments() -> None:
    first_experiment = _make_forecasts("first_experiment")
    second_experiment = _make_forecasts("second_experiment")

    evaluated_forecasts = join_forecasts_with_actuals(
        pd.concat([first_experiment, second_experiment], ignore_index=True),
        _make_actuals(),
    )
    metrics = calculate_forecast_metrics(evaluated_forecasts)

    assert len(evaluated_forecasts) == 4
    assert metrics.loc[
        metrics["metric_scope"] == "overall", "experiment_name"
    ].tolist() == ["first_experiment", "second_experiment"]


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


def test_run_forecast_evaluation_returns_all_result_levels() -> None:
    index = pd.date_range("2020-01-01T00:00:00Z", periods=300, freq="h")
    prepared_data = pd.DataFrame(
        {"gross_load_kwh": [float(position % 24) for position in range(len(index))]},
        index=index,
    )
    training_split = ForecastSplit("training", index[0], index[220])
    evaluation_split = ForecastSplit("evaluation", index[220], index[-1])

    experiment_config = ForecastExperimentConfig(
        "daily_naive_evaluation",
        training_split,
        evaluation_split,
    )

    result = run_forecast_evaluation(
        DailyNaiveForecaster(),
        prepared_data,
        experiment_config,
    )

    assert isinstance(result, ForecastEvaluationResult)
    assert not result.forecasts.empty
    assert list(result.forecasts.columns) == EVALUATION_FORECAST_COLUMNS
    assert len(result.evaluated_forecasts) == len(result.forecasts)
    assert result.forecasts["experiment_name"].unique().tolist() == [
        "daily_naive_evaluation"
    ]
    assert result.evaluated_forecasts["experiment_name"].unique().tolist() == [
        "daily_naive_evaluation"
    ]
    assert result.metrics["experiment_name"].unique().tolist() == [
        "daily_naive_evaluation"
    ]
    assert result.metrics["model_name"].unique().tolist() == ["daily_naive"]
    assert result.metrics.loc[
        result.metrics["metric_scope"] == "overall", "mae_kwh"
    ].item() == pytest.approx(0.0)


def test_run_forecast_evaluation_uses_model_history_requirement() -> None:
    index = pd.date_range("2020-01-01T00:00:00Z", periods=100, freq="h")
    prepared_data = pd.DataFrame(
        {"gross_load_kwh": [float(position) for position in range(len(index))]},
        index=index,
    )
    experiment_config = ForecastExperimentConfig(
        "recording_evaluation",
        ForecastSplit("training", index[0], index[40]),
        ForecastSplit("evaluation", index[40], index[80]),
    )
    forecaster = _RecordingForecaster()

    run_forecast_evaluation(forecaster, prepared_data, experiment_config)

    assert forecaster.training_origins is not None
    assert forecaster.training_origins[0] == index[forecaster.required_history_hours]
