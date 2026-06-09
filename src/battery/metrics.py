"""Metric calculations for BESS dispatch results."""

import pandas as pd

from src.battery.data import prepare_simulation_data
from src.battery.parameters import (
    FIXED_SURPLUS_ONLY,
    BatteryParameters,
    ScenarioParameters,
)


def fixed_import_price(
    prepared_df: pd.DataFrame,
    scenario: ScenarioParameters,
) -> float:
    """Return scenario fixed import price or derive it from dynamic prices."""
    if scenario.fixed_import_price_eur_per_kwh is not None:
        return scenario.fixed_import_price_eur_per_kwh

    return float(prepared_df["dynamic_import_price_eur_per_kwh"].mean())


def calculate_baseline_metrics(
    analysis_df: pd.DataFrame,
    scenario: ScenarioParameters,
) -> dict[str, float]:
    """Calculate no-battery baseline metrics."""
    prepared_df = prepare_simulation_data(analysis_df, scenario)
    fixed_price = fixed_import_price(prepared_df, scenario)
    total_load_kwh = float(prepared_df["gross_load_kwh"].sum())
    total_generation_kwh = float(prepared_df["local_generation_kwh"].sum())
    grid_import_kwh = float(prepared_df["grid_import_kwh"].sum())
    grid_export_kwh = float(prepared_df["grid_export_kwh"].sum())

    dynamic_grid_import_cost_eur = float(
        (
            prepared_df["grid_import_kwh"]
            * prepared_df["dynamic_import_price_eur_per_kwh"]
        ).sum()
    )
    fixed_grid_import_cost_eur = grid_import_kwh * fixed_price
    grid_export_revenue_eur = grid_export_kwh * scenario.export_price_eur_per_kwh
    dynamic_net_cost_eur = dynamic_grid_import_cost_eur - grid_export_revenue_eur
    fixed_net_cost_eur = fixed_grid_import_cost_eur - grid_export_revenue_eur
    self_consumption_ratio = (
        1 - grid_export_kwh / total_generation_kwh
        if total_generation_kwh > 0
        else 0
    )

    return {
        "baseline_dynamic_grid_import_cost_eur": dynamic_grid_import_cost_eur,
        "baseline_fixed_grid_import_cost_eur": fixed_grid_import_cost_eur,
        "baseline_grid_export_revenue_eur": grid_export_revenue_eur,
        "baseline_dynamic_net_cost_eur": dynamic_net_cost_eur,
        "baseline_fixed_net_cost_eur": fixed_net_cost_eur,
        "baseline_dynamic_effective_cost_eur_per_load_kwh": (
            dynamic_net_cost_eur / total_load_kwh
        ),
        "baseline_fixed_effective_cost_eur_per_load_kwh": (
            fixed_net_cost_eur / total_load_kwh
        ),
        "baseline_grid_import_kwh": grid_import_kwh,
        "baseline_grid_export_kwh": grid_export_kwh,
        "baseline_peak_grid_import_kwh": float(
            prepared_df["grid_import_kwh"].max()
        ),
        "baseline_self_consumption_ratio": self_consumption_ratio,
        "total_load_kwh": total_load_kwh,
        "total_generation_kwh": total_generation_kwh,
        "fixed_import_price_eur_per_kwh": fixed_price,
    }


def calculate_dispatch_metrics(
    analysis_df: pd.DataFrame,
    dispatch_df: pd.DataFrame,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
) -> dict[str, float | str]:
    """Calculate metrics for one BESS dispatch result."""
    prepared_df = prepare_simulation_data(analysis_df, scenario)
    if len(prepared_df) != len(dispatch_df):
        raise ValueError("analysis_df and dispatch_df must have the same row count.")

    fixed_price = fixed_import_price(prepared_df, scenario)
    total_load_kwh = float(prepared_df["gross_load_kwh"].sum())
    total_generation_kwh = float(prepared_df["local_generation_kwh"].sum())
    grid_import_kwh = float(dispatch_df["grid_import_kwh"].sum())
    grid_export_kwh = float(dispatch_df["grid_export_kwh"].sum())

    dynamic_grid_import_cost_eur = float(
        (
            dispatch_df["grid_import_kwh"].reset_index(drop=True)
            * prepared_df["dynamic_import_price_eur_per_kwh"].reset_index(drop=True)
        ).sum()
    )
    fixed_grid_import_cost_eur = grid_import_kwh * fixed_price
    grid_export_revenue_eur = grid_export_kwh * scenario.export_price_eur_per_kwh
    dynamic_net_cost_eur = dynamic_grid_import_cost_eur - grid_export_revenue_eur
    fixed_net_cost_eur = fixed_grid_import_cost_eur - grid_export_revenue_eur
    self_consumption_ratio = (
        1 - grid_export_kwh / total_generation_kwh
        if total_generation_kwh > 0
        else 0
    )
    baseline = calculate_baseline_metrics(analysis_df, scenario)

    discharge_throughput_kwh = float(dispatch_df["discharge_to_load_kwh"].sum())
    battery_degradation_cost_eur = (
        discharge_throughput_kwh * battery.degradation_cost_eur_per_kwh
    )

    if scenario.dispatch_strategy == FIXED_SURPLUS_ONLY:
        price_model = "fixed"
        grid_import_cost_eur = fixed_grid_import_cost_eur
        electricity_net_cost_eur = fixed_net_cost_eur
        baseline_net_cost_eur = baseline["baseline_fixed_net_cost_eur"]
    else:
        price_model = "dynamic"
        grid_import_cost_eur = dynamic_grid_import_cost_eur
        electricity_net_cost_eur = dynamic_net_cost_eur
        baseline_net_cost_eur = baseline["baseline_dynamic_net_cost_eur"]

    net_cost_eur = electricity_net_cost_eur + battery_degradation_cost_eur

    return {
        "scenario": scenario.name,
        "dispatch_strategy": scenario.dispatch_strategy,
        "price_model": price_model,
        "capacity_kwh": battery.capacity_kwh,
        "c_rate": battery.c_rate,
        "degradation_cost_eur_per_kwh": battery.degradation_cost_eur_per_kwh,
        "grid_import_cost_eur": grid_import_cost_eur,
        "grid_export_revenue_eur": grid_export_revenue_eur,
        "electricity_net_cost_eur": electricity_net_cost_eur,
        "battery_degradation_cost_eur": battery_degradation_cost_eur,
        "net_cost_eur": net_cost_eur,
        "effective_cost_eur_per_load_kwh": net_cost_eur / total_load_kwh,
        "cost_savings_eur": baseline_net_cost_eur - net_cost_eur,
        "grid_import_kwh": grid_import_kwh,
        "grid_export_kwh": grid_export_kwh,
        "battery_charge_throughput_kwh": float(
            dispatch_df["battery_charge_kwh"].sum()
        ),
        "battery_discharge_throughput_kwh": discharge_throughput_kwh,
        "approximate_cycles": discharge_throughput_kwh / battery.capacity_kwh,
        "peak_grid_import_kwh": float(dispatch_df["grid_import_kwh"].max()),
        "self_consumption_ratio": self_consumption_ratio,
        "self_consumption_improvement": (
            self_consumption_ratio - baseline["baseline_self_consumption_ratio"]
        ),
        "fixed_import_price_eur_per_kwh": fixed_price,
    }
