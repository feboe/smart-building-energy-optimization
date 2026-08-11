"""Leakage-safe feature engineering for direct load forecasting."""

import math

import pandas as pd

from src.forecasting.config import ForecastConfig

FEATURE_METADATA_COLUMNS = [
    "forecast_origin",
    "forecast_timestamp",
    "horizon_hours",
]
LOAD_FEATURE_COLUMNS = [
    "target_local_hour",
    "target_local_isodow",
    "target_is_weekend",
    "target_local_month",
    "load_same_hour_previous_day",
    "load_same_hour_previous_week",
    "load_current",
    "load_lag_1h",
    "load_lag_24h",
    "load_lag_168h",
    "load_mean_24h",
    "load_std_24h",
    "load_mean_168h",
]
TARGET_FEATURE_COLUMN = "target_kwh"
MAX_HISTORY_HOURS = 168
MAX_LEAKAGE_SAFE_HORIZON_HOURS = 24


def build_forecast_features(
    prepared_data: pd.DataFrame,
    forecast_origins: pd.DatetimeIndex,
    include_target: bool = False,
    forecast_config: ForecastConfig | None = None,
) -> pd.DataFrame:
    """Build one leakage-safe feature row per origin and forecast horizon.

    Calendar features describe the target timestamp. All load-based features use
    measurements that are available at or before the forecast origin.
    """
    config = forecast_config or ForecastConfig()
    _validate_feature_input(prepared_data, forecast_origins, config)

    target = prepared_data[config.target_column]
    feature_rows: list[dict[str, object]] = []
    for origin in forecast_origins:
        origin_features = _origin_load_features(target, origin)
        for horizon_hours in range(1, config.horizon_hours + 1):
            forecast_timestamp = origin + pd.Timedelta(hours=horizon_hours)
            target_row = prepared_data.loc[forecast_timestamp]
            row = {
                "forecast_origin": origin,
                "forecast_timestamp": forecast_timestamp,
                "horizon_hours": horizon_hours,
                "target_local_hour": int(target_row["local_hour"]),
                "target_local_isodow": int(target_row["local_isodow"]),
                "target_is_weekend": bool(target_row["is_weekend"]),
                "target_local_month": int(target_row["local_month"]),
                "load_same_hour_previous_day": _load_at(
                    target,
                    forecast_timestamp - pd.Timedelta(hours=24),
                    "same-hour previous day",
                ),
                "load_same_hour_previous_week": _load_at(
                    target,
                    forecast_timestamp - pd.Timedelta(hours=168),
                    "same-hour previous week",
                ),
                **origin_features,
            }
            if include_target:
                row[TARGET_FEATURE_COLUMN] = _load_at(
                    target,
                    forecast_timestamp,
                    "training target",
                )
            feature_rows.append(row)

    columns = [*FEATURE_METADATA_COLUMNS, *LOAD_FEATURE_COLUMNS]
    if include_target:
        columns.append(TARGET_FEATURE_COLUMN)
    return pd.DataFrame(feature_rows, columns=columns)


def _validate_feature_input(
    prepared_data: pd.DataFrame,
    forecast_origins: pd.DatetimeIndex,
    forecast_config: ForecastConfig,
) -> None:
    if forecast_config.horizon_hours > MAX_LEAKAGE_SAFE_HORIZON_HOURS:
        raise ValueError(
            "Load features support at most a 24-hour horizon to prevent leakage."
        )

    required_columns = {
        forecast_config.target_column,
        "local_hour",
        "local_isodow",
        "is_weekend",
        "local_month",
    }
    missing_columns = sorted(required_columns - set(prepared_data.columns))
    if missing_columns:
        raise ValueError(f"Prepared data is missing feature columns: {missing_columns}")
    if prepared_data.empty:
        raise ValueError("Prepared data is empty.")
    if not isinstance(prepared_data.index, pd.DatetimeIndex):
        raise ValueError("Prepared data must use a UTC DatetimeIndex.")
    if prepared_data.index.tz is None or str(prepared_data.index.tz) != "UTC":
        raise ValueError("Prepared data index must use the UTC timezone.")
    if prepared_data.index.has_duplicates:
        raise ValueError("Prepared data index must not contain duplicate timestamps.")
    if not prepared_data.index.is_monotonic_increasing:
        raise ValueError("Prepared data index must be sorted in ascending order.")

    expected_index = pd.date_range(
        start=prepared_data.index.min(),
        end=prepared_data.index.max(),
        freq=forecast_config.frequency,
        tz="UTC",
    )
    if not prepared_data.index.equals(expected_index):
        raise ValueError(
            "Prepared data index must be continuous at the forecast frequency."
        )

    if not isinstance(forecast_origins, pd.DatetimeIndex):
        raise ValueError("forecast_origins must be a UTC DatetimeIndex.")
    if forecast_origins.empty:
        raise ValueError("forecast_origins must not be empty.")
    if forecast_origins.tz is None or str(forecast_origins.tz) != "UTC":
        raise ValueError("forecast_origins must use the UTC timezone.")
    if forecast_origins.has_duplicates:
        raise ValueError("forecast_origins must not contain duplicate timestamps.")
    if not forecast_origins.is_monotonic_increasing:
        raise ValueError("forecast_origins must be sorted in ascending order.")

    for origin in forecast_origins:
        _validate_origin(prepared_data.index, origin, forecast_config)


def _validate_origin(
    data_index: pd.DatetimeIndex,
    origin: pd.Timestamp,
    forecast_config: ForecastConfig,
) -> None:
    if origin not in data_index:
        raise ValueError(
            f"Forecast origin is not present in prepared data: {origin.isoformat()}"
        )

    history_start = origin - pd.Timedelta(hours=MAX_HISTORY_HOURS)
    if history_start not in data_index:
        raise ValueError(
            f"Forecast from {origin.isoformat()} does not have {MAX_HISTORY_HOURS} "
            "hours of historical context."
        )

    final_forecast_timestamp = origin + pd.Timedelta(hours=forecast_config.horizon_hours)
    if final_forecast_timestamp not in data_index:
        raise ValueError(
            f"Forecast from {origin.isoformat()} does not have a complete "
            f"forecast horizon ending at {final_forecast_timestamp.isoformat()}."
        )


def _origin_load_features(target: pd.Series, origin: pd.Timestamp) -> dict[str, float]:
    recent_24_hours = target.loc[origin - pd.Timedelta(hours=23) : origin]
    recent_168_hours = target.loc[origin - pd.Timedelta(hours=167) : origin]
    return {
        "load_current": _load_at(target, origin, "current load"),
        "load_lag_1h": _load_at(
            target,
            origin - pd.Timedelta(hours=1),
            "one-hour lag",
        ),
        "load_lag_24h": _load_at(
            target,
            origin - pd.Timedelta(hours=24),
            "24-hour lag",
        ),
        "load_lag_168h": _load_at(
            target,
            origin - pd.Timedelta(hours=168),
            "168-hour lag",
        ),
        "load_mean_24h": _finite_statistic(recent_24_hours.mean(), "24-hour mean"),
        "load_std_24h": _finite_statistic(
            recent_24_hours.std(ddof=0),
            "24-hour standard deviation",
        ),
        "load_mean_168h": _finite_statistic(recent_168_hours.mean(), "168-hour mean"),
    }


def _load_at(target: pd.Series, timestamp: pd.Timestamp, description: str) -> float:
    value = target.at[timestamp]
    if pd.isna(value):
        raise ValueError(
            f"Cannot build features: {description} at {timestamp.isoformat()} is missing."
        )
    return _finite_statistic(value, description)


def _finite_statistic(value: float, description: str) -> float:
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError(f"Cannot build features: {description} is not finite.")
    return numeric_value
