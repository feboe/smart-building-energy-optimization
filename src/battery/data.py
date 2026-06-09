"""Data loading and preparation for BESS simulations."""

import math

import pandas as pd

from src.config import DatabaseConfig, load_database_config
from src.database import create_analysis_views, create_tables, open_connection
from src.battery.parameters import ScenarioParameters

ANALYSIS_VIEW_NAME = "smart_company_analysis"
REQUIRED_ANALYSIS_COLUMNS = [
    "observation_timestamp",
    "local_timestamp",
    "total_w",
    "pv_w",
    "chp_w",
    "day_ahead_price_eur_per_kwh",
]
REQUIRED_NUMERIC_COLUMNS = [
    "total_w",
    "pv_w",
    "chp_w",
    "day_ahead_price_eur_per_kwh",
]
PHYSICAL_TOLERANCE = 1e-6


def load_smart_company_analysis(
    database_config: DatabaseConfig | None = None,
    recreate_views: bool = True,
) -> pd.DataFrame:
    """Load the 2021 smart-company analysis view from PostgreSQL."""
    config = database_config or load_database_config()
    with open_connection(config) as connection:
        if recreate_views:
            create_tables(connection)
            create_analysis_views(connection)

        df = pd.read_sql_query(
            f"""
            SELECT *
            FROM {ANALYSIS_VIEW_NAME}
            ORDER BY local_timestamp;
            """,
            connection,
        )

    return df


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
    prepared_df["local_timestamp"] = pd.to_datetime(
        prepared_df["local_timestamp"]
    )

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

    prepared_df = prepared_df.sort_values("local_timestamp").reset_index(drop=True)
    prepared_df["grid_energy_kwh"] = prepared_df["total_w"] / 1000
    prepared_df["pv_generation_kwh"] = (
        -prepared_df["pv_w"] / 1000
    ).clip(lower=0)
    prepared_df["chp_generation_kwh"] = (
        -prepared_df["chp_w"] / 1000
    ).clip(lower=0)
    prepared_df["local_generation_kwh"] = (
        prepared_df["pv_generation_kwh"] + prepared_df["chp_generation_kwh"]
    )
    prepared_df["gross_load_kwh"] = (
        prepared_df["grid_energy_kwh"] + prepared_df["local_generation_kwh"]
    )
    prepared_df["grid_import_kwh"] = prepared_df["grid_energy_kwh"].clip(lower=0)
    prepared_df["grid_export_kwh"] = (-prepared_df["grid_energy_kwh"]).clip(lower=0)
    _validate_reconstructed_energy_columns(prepared_df)

    prepared_df["dynamic_import_price_eur_per_kwh"] = (
        prepared_df["day_ahead_price_eur_per_kwh"]
        + scenario.import_markup_eur_per_kwh
    )
    prepared_df["available_surplus_kwh"] = (
        prepared_df["local_generation_kwh"] - prepared_df["gross_load_kwh"]
    ).clip(lower=0)
    prepared_df["demand_after_generation_kwh"] = (
        prepared_df["gross_load_kwh"] - prepared_df["local_generation_kwh"]
    ).clip(lower=0)

    return prepared_df


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
