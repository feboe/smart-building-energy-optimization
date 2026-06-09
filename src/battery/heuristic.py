"""Rolling-horizon heuristic dispatch for BESS simulations."""

import pandas as pd

from src.battery.data import prepare_simulation_data
from src.battery.dispatch import (
    DISPATCH_COLUMNS,
    max_charge_input_kwh,
    max_discharge_to_load_kwh,
    validate_dispatch_results,
)
from src.battery.parameters import BatteryParameters, ScenarioParameters


def run_heuristic_dispatch(
    analysis_df: pd.DataFrame,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
    initial_soc_kwh: float | None = None,
) -> pd.DataFrame:
    """Run the price-aware rolling-horizon heuristic."""
    prepared_df = prepare_simulation_data(analysis_df, scenario)
    soc_kwh = (
        battery.min_soc_kwh if initial_soc_kwh is None else float(initial_soc_kwh)
    )
    if not battery.min_soc_kwh <= soc_kwh <= battery.max_soc_kwh:
        raise ValueError("initial_soc_kwh must be within configured SOC limits.")

    records = []
    prices = prepared_df["dynamic_import_price_eur_per_kwh"]

    for index, row in prepared_df.iterrows():
        horizon_prices = prices.iloc[index : index + scenario.horizon_hours]
        low_price_threshold = float(
            horizon_prices.quantile(scenario.low_price_quantile)
        )
        high_price_threshold = float(
            horizon_prices.quantile(scenario.high_price_quantile)
        )
        current_price = float(row["dynamic_import_price_eur_per_kwh"])
        is_low_price = current_price <= low_price_threshold
        is_high_price = current_price >= high_price_threshold

        soc_start_kwh = soc_kwh
        available_surplus_kwh = float(row["available_surplus_kwh"])
        demand_after_generation_kwh = float(row["demand_after_generation_kwh"])

        charge_limit_kwh = max_charge_input_kwh(soc_kwh, battery)
        charge_from_surplus_kwh = min(available_surplus_kwh, charge_limit_kwh)
        soc_kwh += charge_from_surplus_kwh * battery.eta_charge
        remaining_surplus_kwh = available_surplus_kwh - charge_from_surplus_kwh
        remaining_charge_limit_kwh = max_charge_input_kwh(soc_kwh, battery)

        discharge_to_load_kwh = 0.0
        if demand_after_generation_kwh > 0 and is_high_price:
            discharge_to_load_kwh = min(
                demand_after_generation_kwh,
                max_discharge_to_load_kwh(soc_kwh, battery),
            )
            soc_kwh -= discharge_to_load_kwh / battery.eta_discharge

        remaining_deficit_kwh = demand_after_generation_kwh - discharge_to_load_kwh

        charge_from_grid_kwh = 0.0
        if (
            scenario.allow_grid_charging
            and discharge_to_load_kwh == 0
            and is_low_price
        ):
            charge_from_grid_kwh = min(
                remaining_charge_limit_kwh,
                max_charge_input_kwh(soc_kwh, battery),
            )
            soc_kwh += charge_from_grid_kwh * battery.eta_charge

        battery_charge_kwh = charge_from_surplus_kwh + charge_from_grid_kwh
        grid_import_kwh = remaining_deficit_kwh + charge_from_grid_kwh
        grid_export_kwh = remaining_surplus_kwh

        records.append(
            {
                "observation_timestamp": row["observation_timestamp"],
                "local_timestamp": row["local_timestamp"],
                "gross_load_kwh": row["gross_load_kwh"],
                "local_generation_kwh": row["local_generation_kwh"],
                "available_surplus_kwh": available_surplus_kwh,
                "demand_after_generation_kwh": demand_after_generation_kwh,
                "dynamic_import_price_eur_per_kwh": current_price,
                "low_price_threshold_eur_per_kwh": low_price_threshold,
                "high_price_threshold_eur_per_kwh": high_price_threshold,
                "is_low_price": is_low_price,
                "is_high_price": is_high_price,
                "charge_from_surplus_kwh": charge_from_surplus_kwh,
                "charge_from_grid_kwh": charge_from_grid_kwh,
                "battery_charge_kwh": battery_charge_kwh,
                "discharge_to_load_kwh": discharge_to_load_kwh,
                "grid_import_kwh": grid_import_kwh,
                "grid_export_kwh": grid_export_kwh,
                "soc_start_kwh": soc_start_kwh,
                "soc_end_kwh": soc_kwh,
            }
        )

    dispatch_df = pd.DataFrame(records, columns=DISPATCH_COLUMNS)
    validate_dispatch_results(
        dispatch_df=dispatch_df,
        battery=battery,
        expected_row_count=len(prepared_df),
    )
    return dispatch_df

