"""Data loading and preparation for BESS simulations."""

import math

import pandas as pd

from src.config import DatabaseConfig, load_database_config
from src.database import create_analysis_views, create_tables, open_connection
from src.battery.parameters import ScenarioParameters

ANALYSIS_VIEW_NAMES = {
    "hour": "smart_company_analysis_hourly",
    "15min": "smart_company_analysis_15min",
}
REQUIRED_ANALYSIS_COLUMNS = [
    "observation_timestamp",
    "local_timestamp",
    "resolution",
    "timestep_hours",
    "total_w",
    "pv_w",
    "chp_w",
    "gross_load_raw_w",
    "gross_load_w",
    "gross_load_quality_issue",
    "day_ahead_price_eur_per_kwh",
]
REQUIRED_NUMERIC_COLUMNS = [
    "timestep_hours",
    "total_w",
    "pv_w",
    "chp_w",
    "gross_load_raw_w",
    "day_ahead_price_eur_per_kwh",
]
PHYSICAL_TOLERANCE = 1e-6


def load_smart_company_analysis(
    resolution: str,
    database_config: DatabaseConfig | None = None,
    recreate_views: bool = True,
) -> pd.DataFrame:
    """Load one resolution from the 2021 smart-company analysis view."""
    if resolution not in ANALYSIS_VIEW_NAMES:
        raise ValueError(
            f"resolution must be one of {sorted(ANALYSIS_VIEW_NAMES)}."
        )

    analysis_view_name = ANALYSIS_VIEW_NAMES[resolution]
    config = database_config or load_database_config()
    with open_connection(config) as connection:
        if recreate_views:
            create_tables(connection)
            create_analysis_views(connection)

        df = pd.read_sql_query(
            f"""
            SELECT *
            FROM {analysis_view_name}
            ORDER BY observation_timestamp;
            """,
            connection,
        )

    _validate_loaded_analysis(df, resolution)
    return df


def _validate_loaded_analysis(df: pd.DataFrame, expected_resolution: str) -> None:
    """Validate the database contract for one loaded analysis resolution."""
    required_columns = {
        "observation_timestamp",
        "resolution",
        "timestep_hours",
        "day_ahead_price_eur_per_kwh",
    }
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise ValueError(f"Analysis view is missing columns: {missing_columns}")
    if df.empty:
        raise ValueError(
            f"Analysis view contains no rows for resolution {expected_resolution!r}."
        )
    if set(df["resolution"].dropna().unique()) != {expected_resolution}:
        raise ValueError("Analysis view returned an unexpected or mixed resolution.")
    if df["observation_timestamp"].duplicated().any():
        raise ValueError(
            "Analysis view contains duplicate timestamps within a resolution."
        )
    if df["timestep_hours"].isna().any():
        raise ValueError("Analysis view contains missing timestep durations.")
    if df["day_ahead_price_eur_per_kwh"].isna().any():
        raise ValueError("Analysis view contains rows without a day-ahead price.")


def validate_analysis_data(df: pd.DataFrame) -> None:
    """Validate that required simulation input columns are present and usable."""
    missing_columns = sorted(set(REQUIRED_ANALYSIS_COLUMNS) - set(df.columns))
    if missing_columns:
        raise ValueError(f"Missing analysis columns: {missing_columns}")

    if df.empty:
        raise ValueError("Analysis data is empty.")

    for column in REQUIRED_NUMERIC_COLUMNS:
        if df[column].isna().any():
            raise ValueError(f"{column} contains missing values.")

    if df["resolution"].isna().any() or df["resolution"].nunique() != 1:
        raise ValueError("Analysis data must contain exactly one resolution.")


def prepare_simulation_data(
    df: pd.DataFrame,
    scenario: ScenarioParameters,
) -> pd.DataFrame:
    """Add derived simulation columns without modifying the input DataFrame."""
    validate_analysis_data(df)
    prepared_df = df.copy()

    prepared_df["observation_timestamp"] = pd.to_datetime(
        prepared_df["observation_timestamp"], utc=True
    )
    prepared_df["local_timestamp"] = pd.to_datetime(prepared_df["local_timestamp"])

    for column in REQUIRED_NUMERIC_COLUMNS:
        try:
            prepared_df[column] = pd.to_numeric(
                prepared_df[column],
                errors="raise",
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{column} contains nonnumeric values.") from exc

        is_finite = prepared_df[column].map(math.isfinite)
        if (~is_finite).any():
            raise ValueError(f"{column} contains non-finite values.")

    try:
        prepared_df["gross_load_w"] = pd.to_numeric(
            prepared_df["gross_load_w"],
            errors="raise",
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("gross_load_w contains nonnumeric values.") from exc
    finite_gross_load = prepared_df["gross_load_w"].dropna().map(math.isfinite)
    if (~finite_gross_load).any():
        raise ValueError("gross_load_w contains non-finite values.")

    prepared_df = prepared_df.sort_values("observation_timestamp").reset_index(
        drop=True
    )
    _validate_simulation_timestamps(prepared_df)
    prepared_df = _impute_invalid_gross_load(prepared_df)

    prepared_df["grid_power_raw_kw"] = prepared_df["total_w"] / 1000
    prepared_df["pv_generation_kw"] = (-prepared_df["pv_w"] / 1000).clip(lower=0)
    prepared_df["chp_generation_kw"] = (-prepared_df["chp_w"] / 1000).clip(lower=0)
    prepared_df["local_generation_kw"] = (
        prepared_df["pv_generation_kw"] + prepared_df["chp_generation_kw"]
    )
    prepared_df["gross_load_kw"] = prepared_df["gross_load_w"] / 1000
    prepared_df["grid_power_kw"] = (
        prepared_df["gross_load_kw"] - prepared_df["local_generation_kw"]
    )
    prepared_df["grid_energy_kwh"] = (
        prepared_df["grid_power_kw"] * prepared_df["timestep_hours"]
    )
    prepared_df["pv_generation_kwh"] = (
        prepared_df["pv_generation_kw"] * prepared_df["timestep_hours"]
    )
    prepared_df["chp_generation_kwh"] = (
        prepared_df["chp_generation_kw"] * prepared_df["timestep_hours"]
    )
    prepared_df["local_generation_kwh"] = (
        prepared_df["pv_generation_kwh"] + prepared_df["chp_generation_kwh"]
    )
    prepared_df["gross_load_kwh"] = (
        prepared_df["gross_load_kw"] * prepared_df["timestep_hours"]
    )
    prepared_df["grid_import_kwh"] = prepared_df["grid_energy_kwh"].clip(lower=0)
    prepared_df["grid_export_kwh"] = (-prepared_df["grid_energy_kwh"]).clip(lower=0)
    _validate_reconstructed_energy_columns(prepared_df)

    prepared_df["dynamic_import_price_eur_per_kwh"] = (
        prepared_df["day_ahead_price_eur_per_kwh"] + scenario.import_markup_eur_per_kwh
    )
    prepared_df["available_surplus_kwh"] = (
        prepared_df["local_generation_kwh"] - prepared_df["gross_load_kwh"]
    ).clip(lower=0)
    prepared_df["demand_after_generation_kwh"] = (
        prepared_df["gross_load_kwh"] - prepared_df["local_generation_kwh"]
    ).clip(lower=0)

    return prepared_df


def _validate_simulation_timestamps(prepared_df: pd.DataFrame) -> None:
    """Require unique, continuous timestamps at the configured resolution."""
    timestamps = prepared_df["observation_timestamp"]
    if timestamps.isna().any():
        raise ValueError("observation_timestamp contains missing values.")
    if timestamps.duplicated().any():
        raise ValueError("observation_timestamp contains duplicate values.")
    if prepared_df["timestep_hours"].nunique() != 1:
        raise ValueError("timestep_hours must be constant within a simulation.")

    timestep_hours = float(prepared_df["timestep_hours"].iloc[0])
    if timestep_hours <= 0:
        raise ValueError("timestep_hours must be greater than zero.")
    expected_step = pd.to_timedelta(timestep_hours, unit="h")
    actual_steps = timestamps.diff().dropna()
    if (actual_steps != expected_step).any():
        raise ValueError(
            "observation_timestamp is not continuous at the configured step."
        )


def _impute_invalid_gross_load(prepared_df: pd.DataFrame) -> pd.DataFrame:
    """Interpolate flagged gross load values while preserving raw measurements."""
    result = prepared_df.copy()
    missing_gross_load = result["gross_load_w"].isna()
    flagged_gross_load = result["gross_load_quality_issue"].notna()
    if not missing_gross_load.equals(flagged_gross_load):
        raise ValueError(
            "Missing gross load values and gross load quality flags are inconsistent."
        )

    gross_load_by_time = result.set_index("observation_timestamp")["gross_load_w"]
    interpolated_gross_load = gross_load_by_time.interpolate(
        method="time",
        limit_area="inside",
    )
    if interpolated_gross_load.isna().any():
        raise ValueError("Gross load contains values that cannot be interpolated.")

    result["gross_load_was_imputed"] = missing_gross_load
    result["gross_load_w"] = interpolated_gross_load.to_numpy()
    return result


def _validate_reconstructed_energy_columns(
    prepared_df: pd.DataFrame,
    tolerance: float = PHYSICAL_TOLERANCE,
) -> None:
    """Validate the canonical BESS energy convention after reconstruction."""
    nonnegative_columns = [
        "gross_load_kwh",
        "grid_import_kwh",
        "grid_export_kwh",
        "pv_generation_kwh",
        "chp_generation_kwh",
        "local_generation_kwh",
    ]
    for column in nonnegative_columns:
        if (prepared_df[column] < -tolerance).any():
            raise ValueError(f"{column} contains negative values.")

    expected_import_kwh = prepared_df["grid_energy_kwh"].clip(lower=0)
    expected_export_kwh = (-prepared_df["grid_energy_kwh"]).clip(lower=0)
    import_error = (prepared_df["grid_import_kwh"] - expected_import_kwh).abs()
    export_error = (prepared_df["grid_export_kwh"] - expected_export_kwh).abs()
    if (import_error > tolerance).any():
        raise ValueError("Reconstructed grid import is inconsistent.")
    if (export_error > tolerance).any():
        raise ValueError("Reconstructed grid export is inconsistent.")

    load_error = (
        prepared_df["gross_load_kwh"]
        - prepared_df["grid_energy_kwh"]
        - prepared_df["local_generation_kwh"]
    ).abs()
    if (load_error > tolerance).any():
        raise ValueError("Reconstructed gross load is inconsistent.")
