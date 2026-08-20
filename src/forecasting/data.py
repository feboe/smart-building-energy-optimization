"""Load and prepare the canonical time series for forecasting."""

import math

import pandas as pd

from src.config import DatabaseConfig, load_database_config
from src.database import create_analysis_views, create_tables, open_connection
from src.forecasting.config import ForecastConfig

FORECASTING_VIEW_NAME = "smart_company_forecasting"


def load_smart_company_forecasting(
    database_config: DatabaseConfig | None = None,
    recreate_views: bool = True,
) -> pd.DataFrame:
    """Load the all-years forecasting view from PostgreSQL."""
    config = database_config or load_database_config()
    with open_connection(config) as connection:
        if recreate_views:
            create_tables(connection)
            create_analysis_views(connection)

        return pd.read_sql_query(
            f"""
            SELECT *
            FROM {FORECASTING_VIEW_NAME}
            ORDER BY observation_timestamp;
            """,
            connection,
        )


def prepare_forecasting_data(
    df: pd.DataFrame,
    forecast_config: ForecastConfig | None = None,
) -> pd.DataFrame:
    """Return a continuous UTC-indexed frame with flagged targets imputed.

    The source view preserves invalid observations with a null target and a
    quality issue. This preparation step imputes only those flagged targets;
    unflagged gaps remain errors so they cannot be silently hidden.
    """
    config = forecast_config or ForecastConfig()
    validate_forecasting_data(df, config)
    prepared_df = df.copy()

    timestamp_column = config.observation_timestamp_column
    local_timestamp_column = config.local_timestamp_column
    target_column = config.target_column

    prepared_df[timestamp_column] = pd.to_datetime(
        prepared_df[timestamp_column],
        utc=True,
        errors="raise",
    )
    prepared_df[local_timestamp_column] = pd.to_datetime(
        prepared_df[local_timestamp_column],
        errors="raise",
    )
    _coerce_numeric_columns(prepared_df, config)

    if prepared_df[timestamp_column].isna().any():
        raise ValueError(f"{timestamp_column} contains missing timestamps.")
    if prepared_df[timestamp_column].duplicated().any():
        raise ValueError(f"{timestamp_column} contains duplicate timestamps.")

    prepared_df = prepared_df.sort_values(timestamp_column).set_index(timestamp_column)
    expected_index = pd.date_range(
        start=prepared_df.index.min(),
        end=prepared_df.index.max(),
        freq=config.frequency,
        tz="UTC",
        name=timestamp_column,
    )
    prepared_df = prepared_df.reindex(expected_index)

    missing_target = prepared_df[target_column].isna()
    flagged_target = missing_target & prepared_df[config.target_quality_column].notna()
    interpolated_target = prepared_df[target_column].interpolate(
        method="time",
        limit_area="inside",
    )
    imputed_target = flagged_target & interpolated_target.notna()

    prepared_df.loc[imputed_target, target_column] = interpolated_target.loc[
        imputed_target
    ]
    prepared_df[config.imputation_flag_column] = imputed_target

    _raise_for_unresolved_targets(prepared_df, config)
    return prepared_df


def validate_forecasting_data(
    df: pd.DataFrame,
    forecast_config: ForecastConfig | None = None,
) -> None:
    """Validate that forecasting input has the columns needed for preparation."""
    config = forecast_config or ForecastConfig()
    required_columns = {
        config.observation_timestamp_column,
        config.local_timestamp_column,
        config.target_column,
        config.raw_target_column,
        config.target_quality_column,
    }
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise ValueError(f"Missing forecasting columns: {missing_columns}")
    if df.empty:
        raise ValueError("Forecasting data is empty.")


def validate_prepared_forecasting_data(
    prepared_data: pd.DataFrame,
    forecast_config: ForecastConfig | None = None,
) -> None:
    """Validate the common UTC time-series contract used by forecasters."""
    config = forecast_config or ForecastConfig()
    if config.target_column not in prepared_data.columns:
        raise ValueError(
            f"Prepared data is missing target column {config.target_column!r}."
        )
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
        freq=config.frequency,
        tz="UTC",
    )
    if not prepared_data.index.equals(expected_index):
        raise ValueError(
            "Prepared data index must be continuous at the forecast frequency."
        )


def validate_forecast_origins(
    forecast_origins: pd.DatetimeIndex,
    data_index: pd.DatetimeIndex,
) -> pd.DatetimeIndex:
    """Validate and return forecast origins present in a prepared time series."""
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

    unknown_origins = forecast_origins.difference(data_index)
    if not unknown_origins.empty:
        examples = ", ".join(timestamp.isoformat() for timestamp in unknown_origins[:3])
        raise ValueError(f"forecast_origins are not present in prepared data: {examples}")
    return forecast_origins


def _coerce_numeric_columns(
    prepared_df: pd.DataFrame,
    config: ForecastConfig,
) -> None:
    """Require finite numeric target values while preserving missing-value flags."""
    for column in (config.target_column, config.raw_target_column):
        try:
            prepared_df[column] = pd.to_numeric(prepared_df[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{column} contains nonnumeric values.") from exc

        non_missing_values = prepared_df[column].dropna()
        is_finite = non_missing_values.map(math.isfinite)
        if (~is_finite).any():
            raise ValueError(f"{column} contains non-finite values.")


def _raise_for_unresolved_targets(
    prepared_df: pd.DataFrame,
    config: ForecastConfig,
) -> None:
    """Reject gaps that were unflagged or could not be safely interpolated."""
    unresolved_target_timestamps = prepared_df.index[
        prepared_df[config.target_column].isna()
    ]
    if unresolved_target_timestamps.empty:
        return

    examples = ", ".join(
        timestamp.isoformat() for timestamp in unresolved_target_timestamps[:3]
    )
    raise ValueError(
        "Forecast target remains missing after flagged-target imputation at "
        f"{len(unresolved_target_timestamps)} timestamp(s): {examples}"
    )
