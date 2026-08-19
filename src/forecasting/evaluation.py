"""Chronological forecast evaluation and metric calculation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from src.forecasting.config import (
    ForecastConfig,
    ForecastExperimentConfig,
    ForecastSplit,
)
from src.forecasting.data import validate_prepared_forecasting_data
from src.forecasting.models import FORECAST_COLUMNS

EVALUATION_FORECAST_COLUMNS = ["experiment_name", *FORECAST_COLUMNS]
EVALUATED_FORECAST_COLUMNS = [
    *EVALUATION_FORECAST_COLUMNS,
    "actual_kwh",
    "error_kwh",
    "absolute_error_kwh",
    "squared_error_kwh",
]
METRIC_COLUMNS = [
    "experiment_name",
    "model_name",
    "metric_scope",
    "horizon_hours",
    "sample_count",
    "mae_kwh",
    "rmse_kwh",
    "bias_kwh",
    "wape_percent",
]


class Forecaster(Protocol):
    """Structural interface required by the shared evaluation workflow."""

    required_history_hours: int

    def fit(
        self,
        prepared_data: pd.DataFrame,
        training_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> Forecaster: ...

    def predict(
        self,
        prepared_data: pd.DataFrame,
        forecast_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> pd.DataFrame: ...


@dataclass(frozen=True)
class ForecastEvaluationResult:
    """Forecasts, row-level errors, and metrics from one evaluation."""

    forecasts: pd.DataFrame
    evaluated_forecasts: pd.DataFrame
    metrics: pd.DataFrame


def select_forecast_split(
    prepared_data: pd.DataFrame,
    forecast_split: ForecastSplit,
    forecast_config: ForecastConfig | None = None,
) -> pd.DataFrame:
    """Return rows inside a split's half-open UTC time interval."""
    config = forecast_config or ForecastConfig()
    validate_prepared_forecasting_data(prepared_data, config)
    return prepared_data.loc[
        (prepared_data.index >= forecast_split.start)
        & (prepared_data.index < forecast_split.end)
    ].copy()


def select_valid_forecast_origins(
    prepared_data: pd.DataFrame,
    forecast_split: ForecastSplit,
    required_history_hours: int,
    forecast_config: ForecastConfig | None = None,
) -> pd.DatetimeIndex:
    """Select origins with enough history and labels contained in the split."""
    config = forecast_config or ForecastConfig()
    if required_history_hours < 0:
        raise ValueError("required_history_hours must not be negative.")
    validate_prepared_forecasting_data(prepared_data, config)

    first_eligible_origin = prepared_data.index.min() + pd.Timedelta(
        hours=required_history_hours
    )
    last_eligible_origin = prepared_data.index.max() - pd.Timedelta(
        hours=config.horizon_hours
    )
    split_horizon_end = forecast_split.end - pd.Timedelta(hours=config.horizon_hours)
    origin_mask = (
        (prepared_data.index >= forecast_split.start)
        & (prepared_data.index < split_horizon_end)
        & (prepared_data.index >= first_eligible_origin)
        & (prepared_data.index <= last_eligible_origin)
    )
    return prepared_data.index[origin_mask]


def run_forecast_evaluation(
    model: Forecaster,
    prepared_data: pd.DataFrame,
    experiment_config: ForecastExperimentConfig,
    forecast_config: ForecastConfig | None = None,
) -> ForecastEvaluationResult:
    """Fit and evaluate one model using chronological forecast origins."""
    config = forecast_config or ForecastConfig()
    training_origins = select_valid_forecast_origins(
        prepared_data,
        experiment_config.training_split,
        model.required_history_hours,
        config,
    )
    evaluation_origins = select_valid_forecast_origins(
        prepared_data,
        experiment_config.evaluation_split,
        model.required_history_hours,
        config,
    )

    model.fit(prepared_data, training_origins, config)
    forecasts = model.predict(prepared_data, evaluation_origins, config).copy()
    forecasts.insert(0, "experiment_name", experiment_config.name)
    evaluated_forecasts = join_forecasts_with_actuals(
        forecasts,
        prepared_data,
        config,
    )
    metrics = calculate_forecast_metrics(evaluated_forecasts)
    return ForecastEvaluationResult(
        forecasts=forecasts,
        evaluated_forecasts=evaluated_forecasts,
        metrics=metrics,
    )


def join_forecasts_with_actuals(
    forecasts: pd.DataFrame,
    prepared_data: pd.DataFrame,
    forecast_config: ForecastConfig | None = None,
) -> pd.DataFrame:
    """Attach actual target values and row-level forecast errors to forecasts."""
    config = forecast_config or ForecastConfig()
    _validate_forecasts(forecasts)
    validate_prepared_forecasting_data(prepared_data, config)

    actuals = prepared_data[[config.target_column]].rename(
        columns={config.target_column: "actual_kwh"}
    )
    evaluated_forecasts = forecasts.merge(
        actuals,
        how="left",
        left_on="forecast_timestamp",
        right_index=True,
        validate="many_to_one",
    )
    if evaluated_forecasts["actual_kwh"].isna().any():
        missing_timestamps = evaluated_forecasts.loc[
            evaluated_forecasts["actual_kwh"].isna(), "forecast_timestamp"
        ]
        examples = ", ".join(
            timestamp.isoformat() for timestamp in missing_timestamps[:3]
        )
        raise ValueError(
            "Forecast timestamps are missing from prepared actuals: " f"{examples}"
        )

    evaluated_forecasts["error_kwh"] = (
        evaluated_forecasts["prediction_kwh"] - evaluated_forecasts["actual_kwh"]
    )
    evaluated_forecasts["absolute_error_kwh"] = evaluated_forecasts["error_kwh"].abs()
    evaluated_forecasts["squared_error_kwh"] = evaluated_forecasts["error_kwh"] ** 2
    return evaluated_forecasts.loc[:, EVALUATED_FORECAST_COLUMNS]


def calculate_forecast_metrics(evaluated_forecasts: pd.DataFrame) -> pd.DataFrame:
    """Calculate MAE, RMSE, bias, and WAPE overall and per model horizon."""
    required_columns = {
        "experiment_name",
        "model_name",
        "horizon_hours",
        "actual_kwh",
        "error_kwh",
        "absolute_error_kwh",
        "squared_error_kwh",
    }
    missing_columns = sorted(required_columns - set(evaluated_forecasts.columns))
    if missing_columns:
        raise ValueError(f"Evaluated forecasts are missing columns: {missing_columns}")
    if evaluated_forecasts.empty:
        raise ValueError("Evaluated forecasts are empty.")

    overall = _aggregate_metrics(
        evaluated_forecasts.groupby(
            ["experiment_name", "model_name"],
            sort=True,
        ),
        metric_scope="overall",
    )
    by_horizon = _aggregate_metrics(
        evaluated_forecasts.groupby(
            ["experiment_name", "model_name", "horizon_hours"],
            sort=True,
        ),
        metric_scope="horizon",
    )
    metrics = pd.concat([overall, by_horizon], ignore_index=True)
    metrics["horizon_hours"] = metrics["horizon_hours"].astype("Int64")
    return metrics.loc[:, METRIC_COLUMNS]


def _validate_forecasts(forecasts: pd.DataFrame) -> None:
    required_columns = {"experiment_name", *FORECAST_COLUMNS}
    missing_columns = sorted(required_columns - set(forecasts.columns))
    if missing_columns:
        raise ValueError(f"Forecasts are missing columns: {missing_columns}")
    if forecasts.empty:
        raise ValueError("Forecasts are empty.")
    experiment_names = forecasts["experiment_name"]
    empty_experiment_names = experiment_names.astype(str).str.strip().eq("")
    if experiment_names.isna().any() or empty_experiment_names.any():
        raise ValueError("Forecast experiment_name values must not be empty.")
    predictions = pd.to_numeric(forecasts["prediction_kwh"], errors="coerce")
    if predictions.isna().any() or not predictions.map(math.isfinite).all():
        raise ValueError("Forecast prediction_kwh values must be finite numbers.")
    forecast_key = [
        "experiment_name",
        "model_name",
        "forecast_origin",
        "forecast_timestamp",
    ]
    if forecasts[forecast_key].duplicated().any():
        raise ValueError(
            "Forecasts contain duplicate model, origin, and target timestamp pairs "
            "within an experiment."
        )

    for column in ("forecast_origin", "forecast_timestamp"):
        if not isinstance(forecasts[column].dtype, pd.DatetimeTZDtype):
            raise ValueError(f"Forecast column {column!r} must use the UTC timezone.")
        if str(forecasts[column].dt.tz) != "UTC":
            raise ValueError(f"Forecast column {column!r} must use the UTC timezone.")

    expected_timestamps = forecasts["forecast_origin"] + pd.to_timedelta(
        forecasts["horizon_hours"], unit="h"
    )
    if not forecasts["forecast_timestamp"].equals(expected_timestamps):
        raise ValueError("Forecast timestamps must equal origin plus horizon_hours.")
    if (forecasts["horizon_hours"] <= 0).any():
        raise ValueError("Forecast horizon_hours must be positive.")


def _aggregate_metrics(
    grouped_forecasts: pd.core.groupby.generic.DataFrameGroupBy,
    metric_scope: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group_key, group in grouped_forecasts:
        experiment_name, model_name, horizon_hours = _unpack_group_key(group_key)
        rows.append(
            {
                "experiment_name": experiment_name,
                "model_name": model_name,
                "metric_scope": metric_scope,
                "horizon_hours": horizon_hours,
                "sample_count": len(group),
                "mae_kwh": group["absolute_error_kwh"].mean(),
                "rmse_kwh": math.sqrt(group["squared_error_kwh"].mean()),
                "bias_kwh": group["error_kwh"].mean(),
                "wape_percent": _calculate_wape_percent(group),
            }
        )
    return pd.DataFrame(rows)


def _unpack_group_key(group_key: object) -> tuple[str, str, int | None]:
    if not isinstance(group_key, tuple):
        raise ValueError("Forecast metric groups must include an experiment name.")
    if len(group_key) == 2:
        return str(group_key[0]), str(group_key[1]), None
    return str(group_key[0]), str(group_key[1]), int(group_key[2])


def _calculate_wape_percent(forecasts: pd.DataFrame) -> float:
    actual_energy = forecasts["actual_kwh"].abs().sum()
    if actual_energy == 0:
        return float("nan")
    return 100 * forecasts["absolute_error_kwh"].sum() / actual_energy
