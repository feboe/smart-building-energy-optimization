"""Join forecast output to actuals and calculate comparable error metrics."""

import math

import pandas as pd

from src.forecasting.baselines import FORECAST_COLUMNS
from src.forecasting.config import ForecastConfig

EVALUATED_FORECAST_COLUMNS = [
    *FORECAST_COLUMNS,
    "actual_kwh",
    "error_kwh",
    "absolute_error_kwh",
    "squared_error_kwh",
]
METRIC_COLUMNS = [
    "model_name",
    "metric_scope",
    "horizon_hours",
    "sample_count",
    "mae_kwh",
    "rmse_kwh",
    "bias_kwh",
    "wape_percent",
]


def join_forecasts_with_actuals(
    forecasts: pd.DataFrame,
    prepared_data: pd.DataFrame,
    forecast_config: ForecastConfig | None = None,
) -> pd.DataFrame:
    """Attach actual target values and row-level forecast errors to forecasts."""
    config = forecast_config or ForecastConfig()
    _validate_forecasts(forecasts)
    _validate_actuals(prepared_data, config)

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
        evaluated_forecasts.groupby("model_name", sort=True),
        metric_scope="overall",
    )
    by_horizon = _aggregate_metrics(
        evaluated_forecasts.groupby(["model_name", "horizon_hours"], sort=True),
        metric_scope="horizon",
    )
    metrics = pd.concat([overall, by_horizon], ignore_index=True)
    metrics["horizon_hours"] = metrics["horizon_hours"].astype("Int64")
    return metrics.loc[:, METRIC_COLUMNS]


def _validate_forecasts(forecasts: pd.DataFrame) -> None:
    missing_columns = sorted(set(FORECAST_COLUMNS) - set(forecasts.columns))
    if missing_columns:
        raise ValueError(f"Forecasts are missing columns: {missing_columns}")
    if forecasts.empty:
        raise ValueError("Forecasts are empty.")
    forecast_key = ["model_name", "forecast_origin", "forecast_timestamp"]
    if forecasts[forecast_key].duplicated().any():
        raise ValueError(
            "Forecasts contain duplicate model, origin, and target timestamp pairs."
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


def _validate_actuals(
    prepared_data: pd.DataFrame,
    forecast_config: ForecastConfig,
) -> None:
    if forecast_config.target_column not in prepared_data.columns:
        raise ValueError(
            f"Prepared actuals are missing target column {forecast_config.target_column!r}."
        )
    if not isinstance(prepared_data.index, pd.DatetimeIndex):
        raise ValueError("Prepared actuals must use a UTC DatetimeIndex.")
    if prepared_data.index.tz is None or str(prepared_data.index.tz) != "UTC":
        raise ValueError("Prepared actuals index must use the UTC timezone.")
    if prepared_data.index.has_duplicates:
        raise ValueError("Prepared actuals index must not contain duplicate timestamps.")


def _aggregate_metrics(
    grouped_forecasts: pd.core.groupby.generic.DataFrameGroupBy,
    metric_scope: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group_key, group in grouped_forecasts:
        model_name, horizon_hours = _unpack_group_key(group_key)
        rows.append(
            {
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


def _unpack_group_key(group_key: object) -> tuple[str, int | None]:
    if isinstance(group_key, tuple):
        return str(group_key[0]), int(group_key[1])
    return str(group_key), None


def _calculate_wape_percent(forecasts: pd.DataFrame) -> float:
    actual_energy = forecasts["actual_kwh"].abs().sum()
    if actual_energy == 0:
        return float("nan")
    return 100 * forecasts["absolute_error_kwh"].sum() / actual_energy
