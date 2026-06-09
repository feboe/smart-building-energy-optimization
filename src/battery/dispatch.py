"""Shared dispatch helpers and validation for BESS simulations."""

import math

import pandas as pd

from src.battery.parameters import BatteryParameters

DISPATCH_COLUMNS = [
    "observation_timestamp",
    "local_timestamp",
    "gross_load_kwh",
    "local_generation_kwh",
    "available_surplus_kwh",
    "demand_after_generation_kwh",
    "future_surplus_kwh",
    "reserved_surplus_headroom_kwh",
    "grid_charge_soc_limit_kwh",
    "dynamic_import_price_eur_per_kwh",
    "low_price_threshold_eur_per_kwh",
    "high_price_threshold_eur_per_kwh",
    "is_low_price",
    "is_high_price",
    "charge_from_surplus_kwh",
    "charge_from_grid_kwh",
    "battery_charge_kwh",
    "discharge_to_load_kwh",
    "grid_import_kwh",
    "grid_export_kwh",
    "soc_start_kwh",
    "soc_end_kwh",
]


def max_charge_input_kwh(
    soc_kwh: float,
    battery: BatteryParameters,
    timestep_hours: float = 1.0,
) -> float:
    """Return maximum source energy that can charge the battery this step."""
    power_limited_input = battery.max_charge_power_kw * timestep_hours
    capacity_limited_input = (
        max(battery.max_soc_kwh - soc_kwh, 0) / battery.eta_charge
    )
    return max(min(power_limited_input, capacity_limited_input), 0)


def max_discharge_to_load_kwh(
    soc_kwh: float,
    battery: BatteryParameters,
    timestep_hours: float = 1.0,
) -> float:
    """Return maximum load energy that can be served by the battery this step."""
    power_limited_output = battery.max_discharge_power_kw * timestep_hours
    capacity_limited_output = (
        max(soc_kwh - battery.min_soc_kwh, 0) * battery.eta_discharge
    )
    return max(min(power_limited_output, capacity_limited_output), 0)


def validate_dispatch_results(
    dispatch_df: pd.DataFrame,
    battery: BatteryParameters,
    expected_row_count: int | None = None,
    tolerance: float = 1e-6,
) -> None:
    """Validate physical feasibility for a dispatch result."""
    missing_columns = sorted(set(DISPATCH_COLUMNS) - set(dispatch_df.columns))
    if missing_columns:
        raise ValueError(f"Missing dispatch columns: {missing_columns}")

    if expected_row_count is not None and len(dispatch_df) != expected_row_count:
        raise ValueError(
            "Dispatch row count does not match input row count: "
            f"{len(dispatch_df)} != {expected_row_count}"
        )

    nonnegative_columns = [
        "charge_from_surplus_kwh",
        "charge_from_grid_kwh",
        "battery_charge_kwh",
        "discharge_to_load_kwh",
        "grid_import_kwh",
        "grid_export_kwh",
    ]
    finite_columns = [
        "gross_load_kwh",
        "local_generation_kwh",
        "available_surplus_kwh",
        "demand_after_generation_kwh",
        "grid_charge_soc_limit_kwh",
        "dynamic_import_price_eur_per_kwh",
        *nonnegative_columns,
        "soc_start_kwh",
        "soc_end_kwh",
    ]
    for column in finite_columns:
        numeric_values = pd.to_numeric(dispatch_df[column], errors="coerce")
        is_finite = numeric_values.map(math.isfinite)
        if (~is_finite).any():
            raise ValueError(f"{column} contains non-finite values.")

    for column in nonnegative_columns:
        if (dispatch_df[column] < -tolerance).any():
            raise ValueError(f"{column} contains negative values.")

    if (dispatch_df["soc_start_kwh"] < battery.min_soc_kwh - tolerance).any():
        raise ValueError("SOC start falls below the configured minimum.")

    if (dispatch_df["soc_end_kwh"] < battery.min_soc_kwh - tolerance).any():
        raise ValueError("SOC end falls below the configured minimum.")

    if (dispatch_df["soc_start_kwh"] > battery.max_soc_kwh + tolerance).any():
        raise ValueError("SOC start exceeds the configured maximum.")

    if (dispatch_df["soc_end_kwh"] > battery.max_soc_kwh + tolerance).any():
        raise ValueError("SOC end exceeds the configured maximum.")

    battery_charge_error = (
        dispatch_df["battery_charge_kwh"]
        - dispatch_df["charge_from_surplus_kwh"]
        - dispatch_df["charge_from_grid_kwh"]
    ).abs()
    if (battery_charge_error > tolerance).any():
        raise ValueError("Battery charge does not match charge components.")

    if (
        dispatch_df["battery_charge_kwh"]
        > battery.max_charge_power_kw + tolerance
    ).any():
        raise ValueError("Battery charge exceeds the configured power limit.")

    if (
        dispatch_df["discharge_to_load_kwh"]
        > battery.max_discharge_power_kw + tolerance
    ).any():
        raise ValueError("Battery discharge exceeds the configured power limit.")

    if (
        dispatch_df["charge_from_surplus_kwh"]
        > dispatch_df["available_surplus_kwh"] + tolerance
    ).any():
        raise ValueError("Battery charges more surplus than available.")

    if (
        dispatch_df["discharge_to_load_kwh"]
        > dispatch_df["demand_after_generation_kwh"] + tolerance
    ).any():
        raise ValueError("Battery discharges more energy than remaining demand.")

    simultaneous_charge_discharge = (
        dispatch_df["battery_charge_kwh"] > tolerance
    ) & (dispatch_df["discharge_to_load_kwh"] > tolerance)
    if simultaneous_charge_discharge.any():
        raise ValueError("Battery charges and discharges in the same timestep.")

    export_balance_error = (
        dispatch_df["grid_export_kwh"]
        - dispatch_df["available_surplus_kwh"]
        + dispatch_df["charge_from_surplus_kwh"]
    ).abs()
    if (export_balance_error > tolerance).any():
        raise ValueError("Grid export is not equal to leftover local surplus.")

    energy_balance_error = (
        dispatch_df["local_generation_kwh"]
        + dispatch_df["grid_import_kwh"]
        + dispatch_df["discharge_to_load_kwh"]
        - dispatch_df["gross_load_kwh"]
        - dispatch_df["charge_from_surplus_kwh"]
        - dispatch_df["charge_from_grid_kwh"]
        - dispatch_df["grid_export_kwh"]
    ).abs()
    if (energy_balance_error > tolerance).any():
        raise ValueError("Dispatch energy balance is inconsistent.")

    soc_balance_error = (
        dispatch_df["soc_start_kwh"]
        + dispatch_df["battery_charge_kwh"] * battery.eta_charge
        - dispatch_df["discharge_to_load_kwh"] / battery.eta_discharge
        - dispatch_df["soc_end_kwh"]
    ).abs()
    if (soc_balance_error > tolerance).any():
        raise ValueError("Dispatch SOC balance is inconsistent.")
