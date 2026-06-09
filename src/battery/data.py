"""Data loading and preparation for BESS simulations."""

import pandas as pd

from src.config import DatabaseConfig, load_database_config
from src.database import create_analysis_views, create_tables, open_connection
from src.battery.parameters import ScenarioParameters

ANALYSIS_VIEW_NAME = "smart_company_analysis"
REQUIRED_ANALYSIS_COLUMNS = [
    "observation_timestamp",
    "local_timestamp",
    "gross_load_kwh",
    "grid_import_kwh",
    "grid_export_kwh",
    "pv_generation_kwh",
    "chp_generation_kwh",
    "day_ahead_price_eur_per_kwh",
]


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

    if df["day_ahead_price_eur_per_kwh"].isna().any():
        raise ValueError("Analysis data contains missing day-ahead prices.")


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

    numeric_columns = [
        "gross_load_kwh",
        "grid_import_kwh",
        "grid_export_kwh",
        "pv_generation_kwh",
        "chp_generation_kwh",
        "day_ahead_price_eur_per_kwh",
    ]
    for column in numeric_columns:
        prepared_df[column] = pd.to_numeric(prepared_df[column], errors="raise")

    prepared_df = prepared_df.sort_values("local_timestamp").reset_index(drop=True)
    prepared_df["dynamic_import_price_eur_per_kwh"] = (
        prepared_df["day_ahead_price_eur_per_kwh"]
        + scenario.import_markup_eur_per_kwh
    )
    prepared_df["local_generation_kwh"] = (
        prepared_df["pv_generation_kwh"] + prepared_df["chp_generation_kwh"]
    )
    prepared_df["available_surplus_kwh"] = (
        prepared_df["local_generation_kwh"] - prepared_df["gross_load_kwh"]
    ).clip(lower=0)
    prepared_df["demand_after_generation_kwh"] = (
        prepared_df["gross_load_kwh"] - prepared_df["local_generation_kwh"]
    ).clip(lower=0)

    return prepared_df

