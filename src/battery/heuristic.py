"""Heuristic dispatch rules for BESS simulations."""

import pandas as pd

from src.battery.data import prepare_simulation_data
from src.battery.dispatch import (
    DISPATCH_COLUMNS,
    max_charge_input_kwh,
    max_discharge_to_load_kwh,
    validate_dispatch_results,
)
from src.battery.parameters import (
    DYNAMIC_SURPLUS_GRID_CHARGING,
    DYNAMIC_SURPLUS_ONLY,
    FIXED_SURPLUS_ONLY,
    BatteryParameters,
    ScenarioParameters,
)


def run_heuristic_dispatch(
    analysis_df: pd.DataFrame,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
    initial_soc_kwh: float | None = None,
) -> pd.DataFrame:
    """Run the heuristic dispatch rule configured by the scenario."""
    prepared_df = prepare_simulation_data(analysis_df, scenario)
    soc_kwh = _initial_soc(initial_soc_kwh, battery)

    if scenario.dispatch_strategy == FIXED_SURPLUS_ONLY:
        return _run_dispatch_loop(
            prepared_df=prepared_df,
            battery=battery,
            scenario=scenario,
            initial_soc_kwh=soc_kwh,
            always_discharge=True,
            allow_grid_charging=False,
            use_price_thresholds=False,
            reserve_future_surplus=False,
        )

    if scenario.dispatch_strategy == DYNAMIC_SURPLUS_ONLY:
        return _run_dispatch_loop(
            prepared_df=prepared_df,
            battery=battery,
            scenario=scenario,
            initial_soc_kwh=soc_kwh,
            always_discharge=False,
            allow_grid_charging=False,
            use_price_thresholds=True,
            reserve_future_surplus=False,
        )

    if scenario.dispatch_strategy == DYNAMIC_SURPLUS_GRID_CHARGING:
        return _run_dispatch_loop(
            prepared_df=prepared_df,
            battery=battery,
            scenario=scenario,
            initial_soc_kwh=soc_kwh,
            always_discharge=False,
            allow_grid_charging=True,
            use_price_thresholds=True,
            reserve_future_surplus=True,
        )

    raise ValueError(f"Unknown dispatch strategy: {scenario.dispatch_strategy}")


def _initial_soc(
    initial_soc_kwh: float | None,
    battery: BatteryParameters,
) -> float:
    soc_kwh = battery.min_soc_kwh if initial_soc_kwh is None else float(initial_soc_kwh)
    if not battery.min_soc_kwh <= soc_kwh <= battery.max_soc_kwh:
        raise ValueError("initial_soc_kwh must be within configured SOC limits.")
    return soc_kwh


def _run_dispatch_loop(
    prepared_df: pd.DataFrame,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
    initial_soc_kwh: float,
    always_discharge: bool,
    allow_grid_charging: bool,
    use_price_thresholds: bool,
    reserve_future_surplus: bool,
) -> pd.DataFrame:
    records = []
    soc_kwh = initial_soc_kwh
    prices = prepared_df["dynamic_import_price_eur_per_kwh"]

    for index, row in prepared_df.iterrows():
        current_price = float(row["dynamic_import_price_eur_per_kwh"])
        if use_price_thresholds:
            horizon_prices = prices.iloc[index : index + scenario.horizon_hours]
            low_price_threshold = float(
                horizon_prices.quantile(scenario.low_price_quantile)
            )
            high_price_threshold = float(
                horizon_prices.quantile(scenario.high_price_quantile)
            )
            is_low_price = current_price <= low_price_threshold
            is_high_price = current_price >= high_price_threshold
        else:
            low_price_threshold = float("nan")
            high_price_threshold = float("nan")
            is_low_price = False
            is_high_price = False

        soc_start_kwh = soc_kwh
        available_surplus_kwh = float(row["available_surplus_kwh"])
        demand_after_generation_kwh = float(row["demand_after_generation_kwh"])
        charge_power_remaining_kwh = battery.max_charge_power_kw
        (
            future_surplus_kwh,
            reserved_surplus_headroom_kwh,
            grid_charge_soc_limit_kwh,
        ) = _future_surplus_reserve(
            prepared_df=prepared_df,
            index=index,
            battery=battery,
            scenario=scenario,
            reserve_future_surplus=reserve_future_surplus,
        )

        charge_limit_kwh = min(
            max_charge_input_kwh(soc_kwh, battery),
            charge_power_remaining_kwh,
        )
        charge_from_surplus_kwh = min(available_surplus_kwh, charge_limit_kwh)
        soc_kwh += charge_from_surplus_kwh * battery.eta_charge
        charge_power_remaining_kwh -= charge_from_surplus_kwh
        remaining_surplus_kwh = available_surplus_kwh - charge_from_surplus_kwh

        discharge_to_load_kwh = 0.0
        should_discharge = demand_after_generation_kwh > 0 and (
            always_discharge or is_high_price
        )
        if should_discharge:
            discharge_to_load_kwh = min(
                demand_after_generation_kwh,
                max_discharge_to_load_kwh(soc_kwh, battery),
            )
            soc_kwh -= discharge_to_load_kwh / battery.eta_discharge

        remaining_deficit_kwh = demand_after_generation_kwh - discharge_to_load_kwh

        charge_from_grid_kwh = 0.0
        if (
            allow_grid_charging
            and discharge_to_load_kwh == 0
            and is_low_price
            and charge_power_remaining_kwh > 0
        ):
            reserve_limited_charge_kwh = (
                max(
                    grid_charge_soc_limit_kwh - soc_kwh,
                    0,
                )
                / battery.eta_charge
            )
            charge_from_grid_kwh = min(
                max_charge_input_kwh(soc_kwh, battery),
                charge_power_remaining_kwh,
                reserve_limited_charge_kwh,
                _grid_connection_charge_limit_kwh(
                    remaining_deficit_kwh,
                    scenario,
                ),
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
                "future_surplus_kwh": future_surplus_kwh,
                "reserved_surplus_headroom_kwh": reserved_surplus_headroom_kwh,
                "grid_charge_soc_limit_kwh": grid_charge_soc_limit_kwh,
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


def _future_surplus_reserve(
    prepared_df: pd.DataFrame,
    index: int,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
    reserve_future_surplus: bool,
) -> tuple[float, float, float]:
    if not reserve_future_surplus:
        return float("nan"), float("nan"), battery.max_soc_kwh

    horizon_surplus = prepared_df["available_surplus_kwh"].iloc[
        index + 1 : index + scenario.horizon_hours
    ]
    future_surplus_kwh = float(horizon_surplus.sum())
    usable_capacity_kwh = battery.max_soc_kwh - battery.min_soc_kwh
    reserved_surplus_headroom_kwh = min(
        future_surplus_kwh * battery.eta_charge * scenario.surplus_reserve_fraction,
        usable_capacity_kwh,
    )
    grid_charge_soc_limit_kwh = max(
        battery.max_soc_kwh - reserved_surplus_headroom_kwh,
        battery.min_soc_kwh,
    )

    return (
        future_surplus_kwh,
        reserved_surplus_headroom_kwh,
        grid_charge_soc_limit_kwh,
    )


def _grid_connection_charge_limit_kwh(
    remaining_deficit_kwh: float,
    scenario: ScenarioParameters,
    timestep_hours: float = 1.0,
) -> float:
    if scenario.grid_connection_limit_kw is None:
        return float("inf")

    grid_limit_kwh = scenario.grid_connection_limit_kw * timestep_hours
    return max(grid_limit_kwh - remaining_deficit_kwh, 0)
