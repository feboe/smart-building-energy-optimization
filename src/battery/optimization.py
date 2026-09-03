"""LP optimization dispatch for BESS simulations."""

import math

import pandas as pd
import pulp

from src.battery.data import prepare_simulation_data
from src.battery.dispatch import (
    DISPATCH_COLUMNS,
    horizon_steps,
    max_charge_input_kwh,
    max_discharge_to_load_kwh,
    validate_dispatch_results,
)
from src.battery.metrics import fixed_import_price
from src.battery.parameters import (
    DYNAMIC_SURPLUS_GRID_CHARGING,
    FIXED_SURPLUS_ONLY,
    BatteryParameters,
    ScenarioParameters,
)

OPTIMAL_STATUS = "Optimal"
NUMERIC_TOLERANCE = 1e-9
SOC_BOUND_TOLERANCE = 1e-4

HORIZON_DIAGNOSTIC_COLUMNS = [
    "planning_horizon_steps",
    "planning_horizon_duration_hours",
    "planning_horizon_end_timestamp",
    "solver_status",
    "terminal_reference_price_eur_per_kwh",
    "terminal_value_eur_per_kwh_soc",
    "planned_terminal_soc_kwh",
    "planned_terminal_usable_soc_kwh",
    "planned_terminal_value_eur",
    "horizon_operating_cost_eur",
    "horizon_terminal_credit_eur",
    "horizon_objective_eur",
]
HorizonSolutionValue = float | int | str | pd.Timestamp | None
HorizonSolution = dict[str, HorizonSolutionValue]
DispatchRecordValue = float | int | bool | str | pd.Timestamp | None
DispatchRecord = dict[str, DispatchRecordValue]


def run_optimized_dispatch(
    analysis_df: pd.DataFrame,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
    initial_soc_kwh: float | None = None,
    solver: pulp.LpSolver | None = None,
    solver_msg: bool = False,
    include_horizon_diagnostics: bool = False,
) -> pd.DataFrame:
    """Run rolling-horizon LP dispatch for one BESS scenario."""
    prepared_df = prepare_simulation_data(analysis_df, scenario)
    soc_kwh = _initial_soc(initial_soc_kwh, battery)
    fixed_price = fixed_import_price(prepared_df, scenario)

    records = []
    timestep_hours = float(prepared_df["timestep_hours"].iloc[0])
    planning_steps = horizon_steps(scenario.horizon_hours, timestep_hours)
    for index in range(len(prepared_df)):
        horizon_df = prepared_df.iloc[index : index + planning_steps].reset_index(
            drop=True
        )
        solution = _solve_horizon(
            horizon_df=horizon_df,
            horizon_initial_soc_kwh=soc_kwh,
            battery=battery,
            scenario=scenario,
            fixed_import_price_eur_per_kwh=fixed_price,
            solver=solver,
            solver_msg=solver_msg,
        )

        row = prepared_df.iloc[index]
        record = _build_dispatch_record(
            row=row,
            horizon_df=horizon_df,
            solution=solution,
            soc_start_kwh=soc_kwh,
            battery=battery,
            scenario=scenario,
            include_horizon_diagnostics=include_horizon_diagnostics,
        )
        records.append(record)
        soc_kwh = float(record["soc_end_kwh"])

    output_columns = DISPATCH_COLUMNS + (
        HORIZON_DIAGNOSTIC_COLUMNS if include_horizon_diagnostics else []
    )
    dispatch_df = pd.DataFrame(records, columns=output_columns)
    validate_dispatch_results(
        dispatch_df=dispatch_df,
        battery=battery,
        expected_row_count=len(prepared_df),
    )
    return dispatch_df


def _initial_soc(
    initial_soc_kwh: float | None,
    battery: BatteryParameters,
) -> float:
    soc_kwh = battery.min_soc_kwh if initial_soc_kwh is None else float(initial_soc_kwh)
    if (
        soc_kwh < battery.min_soc_kwh - SOC_BOUND_TOLERANCE
        or soc_kwh > battery.max_soc_kwh + SOC_BOUND_TOLERANCE
    ):
        raise ValueError("initial_soc_kwh must be within configured SOC limits.")
    return _clean_soc_value(soc_kwh, battery)


def _solve_horizon(
    horizon_df: pd.DataFrame,
    horizon_initial_soc_kwh: float,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
    fixed_import_price_eur_per_kwh: float,
    solver: pulp.LpSolver | None,
    solver_msg: bool,
) -> HorizonSolution:
    time_steps = range(len(horizon_df))
    model = pulp.LpProblem("bess_rolling_horizon", pulp.LpMinimize)

    charge_from_surplus = pulp.LpVariable.dicts(
        "charge_from_surplus",
        time_steps,
        lowBound=0,
    )
    charge_from_grid = pulp.LpVariable.dicts(
        "charge_from_grid",
        time_steps,
        lowBound=0,
    )
    discharge_to_load = pulp.LpVariable.dicts(
        "discharge_to_load",
        time_steps,
        lowBound=0,
    )
    grid_import = pulp.LpVariable.dicts("grid_import", time_steps, lowBound=0)
    grid_export = pulp.LpVariable.dicts("grid_export", time_steps, lowBound=0)
    soc = pulp.LpVariable.dicts(
        "soc",
        time_steps,
        lowBound=battery.min_soc_kwh,
        upBound=battery.max_soc_kwh,
    )

    allow_grid_charging = scenario.dispatch_strategy == DYNAMIC_SURPLUS_GRID_CHARGING

    for step in time_steps:
        row = horizon_df.iloc[step]
        available_surplus_kwh = float(row["available_surplus_kwh"])
        demand_after_generation_kwh = float(row["demand_after_generation_kwh"])
        timestep_hours = float(row["timestep_hours"])
        previous_soc = horizon_initial_soc_kwh if step == 0 else soc[step - 1]

        model += (
            grid_import[step] + discharge_to_load[step]
            == demand_after_generation_kwh + charge_from_grid[step]
        ), f"deficit_balance_{step}"

        model += (
            grid_export[step] == available_surplus_kwh - charge_from_surplus[step]
        ), f"surplus_balance_{step}"

        model += (
            charge_from_surplus[step] <= available_surplus_kwh
        ), f"surplus_charge_limit_{step}"
        model += (
            discharge_to_load[step] <= demand_after_generation_kwh
        ), f"load_discharge_limit_{step}"
        model += (
            discharge_to_load[step]
            <= battery.max_discharge_power_kw * timestep_hours
        ), f"discharge_power_limit_{step}"
        model += (
            charge_from_surplus[step] + charge_from_grid[step]
            <= battery.max_charge_power_kw * timestep_hours
        ), f"charge_power_limit_{step}"

        if allow_grid_charging:
            grid_charge_limit = _grid_connection_charge_limit_kwh(
                remaining_deficit_kwh=demand_after_generation_kwh,
                scenario=scenario,
                timestep_hours=timestep_hours,
            )
            model += (
                charge_from_grid[step] <= grid_charge_limit
            ), f"grid_connection_charge_limit_{step}"
        else:
            model += charge_from_grid[step] == 0, f"disable_grid_charge_{step}"

        model += (
            soc[step]
            == previous_soc
            + (charge_from_surplus[step] + charge_from_grid[step]) * battery.eta_charge
            - discharge_to_load[step] / battery.eta_discharge
        ), f"soc_balance_{step}"

    terminal_reference_price_eur_per_kwh = _terminal_reference_price_eur_per_kwh(
        horizon_df=horizon_df,
        scenario=scenario,
        fixed_import_price_eur_per_kwh=fixed_import_price_eur_per_kwh,
    )
    terminal_value_eur_per_kwh_soc = _terminal_value_from_reference_price(
        terminal_reference_price_eur_per_kwh=terminal_reference_price_eur_per_kwh,
        battery=battery,
    )
    operating_cost = pulp.lpSum(
        _import_price(row, scenario, fixed_import_price_eur_per_kwh)
        * grid_import[step]
        - scenario.export_price_eur_per_kwh * grid_export[step]
        + battery.degradation_cost_eur_per_kwh * discharge_to_load[step]
        for step, (_, row) in zip(time_steps, horizon_df.iterrows())
    )
    terminal_credit = terminal_value_eur_per_kwh_soc * (
        soc[len(horizon_df) - 1] - battery.min_soc_kwh
    )
    model += (operating_cost - terminal_credit, "net_electricity_cost")

    status_code = model.solve(solver or pulp.PULP_CBC_CMD(msg=solver_msg))
    status = pulp.LpStatus[status_code]
    if status != OPTIMAL_STATUS:
        raise RuntimeError(f"LP optimization failed with solver status: {status}")

    planned_terminal_soc_kwh = _variable_value(soc[len(horizon_df) - 1])
    planned_terminal_usable_soc_kwh = max(
        planned_terminal_soc_kwh - battery.min_soc_kwh,
        0.0,
    )
    horizon_operating_cost_eur = _clean_value(pulp.value(operating_cost))
    horizon_terminal_credit_eur = _clean_value(pulp.value(terminal_credit))
    return {
        "charge_from_surplus_kwh": _variable_value(charge_from_surplus[0]),
        "charge_from_grid_kwh": _variable_value(charge_from_grid[0]),
        "discharge_to_load_kwh": _variable_value(discharge_to_load[0]),
        "planning_horizon_steps": len(horizon_df),
        "planning_horizon_duration_hours": float(horizon_df["timestep_hours"].sum()),
        "planning_horizon_end_timestamp": (
            pd.Timestamp(horizon_df["observation_timestamp"].iloc[-1])
            + pd.to_timedelta(float(horizon_df["timestep_hours"].iloc[-1]), unit="h")
        ),
        "solver_status": status,
        "terminal_reference_price_eur_per_kwh": terminal_reference_price_eur_per_kwh,
        "terminal_value_eur_per_kwh_soc": terminal_value_eur_per_kwh_soc,
        "planned_terminal_soc_kwh": planned_terminal_soc_kwh,
        "planned_terminal_usable_soc_kwh": planned_terminal_usable_soc_kwh,
        "planned_terminal_value_eur": horizon_terminal_credit_eur,
        "horizon_operating_cost_eur": horizon_operating_cost_eur,
        "horizon_terminal_credit_eur": horizon_terminal_credit_eur,
        "horizon_objective_eur": _clean_value(pulp.value(model.objective)),
    }


def _build_dispatch_record(
    row: pd.Series,
    horizon_df: pd.DataFrame,
    solution: HorizonSolution,
    soc_start_kwh: float,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
    include_horizon_diagnostics: bool,
) -> DispatchRecord:
    available_surplus_kwh = float(row["available_surplus_kwh"])
    demand_after_generation_kwh = float(row["demand_after_generation_kwh"])
    current_price = float(row["dynamic_import_price_eur_per_kwh"])
    timestep_hours = float(row["timestep_hours"])

    max_charge_kwh = max_charge_input_kwh(soc_start_kwh, battery, timestep_hours)
    charge_from_surplus_kwh = _clean_bound_value(
        float(solution["charge_from_surplus_kwh"]),
        lower_bound=0.0,
        upper_bound=min(available_surplus_kwh, max_charge_kwh),
    )
    charge_from_grid_kwh = _clean_bound_value(
        float(solution["charge_from_grid_kwh"]),
        lower_bound=0.0,
        upper_bound=max(max_charge_kwh - charge_from_surplus_kwh, 0.0),
    )
    discharge_to_load_kwh = _clean_bound_value(
        float(solution["discharge_to_load_kwh"]),
        lower_bound=0.0,
        upper_bound=min(
            demand_after_generation_kwh,
            max_discharge_to_load_kwh(soc_start_kwh, battery, timestep_hours),
        ),
    )
    battery_charge_kwh = _clean_value(charge_from_surplus_kwh + charge_from_grid_kwh)

    grid_import_kwh = _clean_value(
        demand_after_generation_kwh + charge_from_grid_kwh - discharge_to_load_kwh
    )
    grid_export_kwh = _clean_value(available_surplus_kwh - charge_from_surplus_kwh)
    soc_end_kwh = _clean_soc_value(
        soc_start_kwh
        + battery_charge_kwh * battery.eta_charge
        - discharge_to_load_kwh / battery.eta_discharge,
        battery,
    )

    (
        low_price_threshold,
        high_price_threshold,
        is_low_price,
        is_high_price,
    ) = _price_threshold_context(horizon_df, scenario, current_price)

    record: DispatchRecord = {
        "observation_timestamp": row["observation_timestamp"],
        "local_timestamp": row["local_timestamp"],
        "timestep_hours": timestep_hours,
        "gross_load_kwh": row["gross_load_kwh"],
        "local_generation_kwh": row["local_generation_kwh"],
        "available_surplus_kwh": available_surplus_kwh,
        "demand_after_generation_kwh": demand_after_generation_kwh,
        "future_surplus_kwh": float("nan"),
        "reserved_surplus_headroom_kwh": float("nan"),
        "grid_charge_soc_limit_kwh": battery.max_soc_kwh,
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
        "soc_end_kwh": soc_end_kwh,
    }
    if include_horizon_diagnostics:
        record.update(
            {
                column: solution[column]
                for column in HORIZON_DIAGNOSTIC_COLUMNS
            }
        )
    return record


def _price_threshold_context(
    horizon_df: pd.DataFrame,
    scenario: ScenarioParameters,
    current_price: float,
) -> tuple[float, float, bool, bool]:
    if scenario.dispatch_strategy == FIXED_SURPLUS_ONLY:
        return float("nan"), float("nan"), False, False

    horizon_prices = horizon_df["dynamic_import_price_eur_per_kwh"]
    low_price_threshold = float(horizon_prices.quantile(scenario.low_price_quantile))
    high_price_threshold = float(horizon_prices.quantile(scenario.high_price_quantile))
    return (
        low_price_threshold,
        high_price_threshold,
        current_price <= low_price_threshold,
        current_price >= high_price_threshold,
    )


def _import_price(
    row: pd.Series,
    scenario: ScenarioParameters,
    fixed_import_price_eur_per_kwh: float,
) -> float:
    if scenario.dispatch_strategy == FIXED_SURPLUS_ONLY:
        return fixed_import_price_eur_per_kwh

    return float(row["dynamic_import_price_eur_per_kwh"])


def _terminal_reference_price_eur_per_kwh(
    horizon_df: pd.DataFrame,
    scenario: ScenarioParameters,
    fixed_import_price_eur_per_kwh: float,
) -> float | None:
    """Return the all-in import-price reference used for terminal valuation."""
    window_hours = scenario.terminal_value_window_hours
    if window_hours is None:
        return None

    if horizon_df.empty:
        raise ValueError("Cannot calculate a terminal value for an empty horizon.")

    if scenario.dispatch_strategy == FIXED_SURPLUS_ONLY:
        import_price_eur_per_kwh = fixed_import_price_eur_per_kwh
    else:
        timestep_hours = float(horizon_df["timestep_hours"].iloc[0])
        window_steps = horizon_steps(window_hours, timestep_hours)
        price_window = horizon_df.iloc[-min(window_steps, len(horizon_df)) :]
        durations = price_window["timestep_hours"]
        return float(
            (
                price_window["dynamic_import_price_eur_per_kwh"] * durations
            ).sum()
            / durations.sum()
        )
    return import_price_eur_per_kwh


def _terminal_value_eur_per_kwh_soc(
    horizon_df: pd.DataFrame,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
    fixed_import_price_eur_per_kwh: float,
) -> float:
    """Return terminal value per internal kWh of usable battery SOC.

    Kept as a small public-by-convention helper for model-level tests.  Horizon
    diagnostics additionally expose its price reference separately.
    """
    return _terminal_value_from_reference_price(
        terminal_reference_price_eur_per_kwh=_terminal_reference_price_eur_per_kwh(
            horizon_df=horizon_df,
            scenario=scenario,
            fixed_import_price_eur_per_kwh=fixed_import_price_eur_per_kwh,
        ),
        battery=battery,
    )


def _terminal_value_from_reference_price(
    terminal_reference_price_eur_per_kwh: float | None,
    battery: BatteryParameters,
) -> float:
    """Return terminal value per internal kWh of usable battery SOC."""
    if terminal_reference_price_eur_per_kwh is None:
        return 0.0

    return max(
        0.0,
        battery.eta_discharge
        * (
            terminal_reference_price_eur_per_kwh
            - battery.degradation_cost_eur_per_kwh
        ),
    )


def _grid_connection_charge_limit_kwh(
    remaining_deficit_kwh: float,
    scenario: ScenarioParameters,
    timestep_hours: float = 1.0,
) -> float:
    if scenario.grid_connection_limit_kw is None:
        return math.inf

    grid_limit_kwh = scenario.grid_connection_limit_kw * timestep_hours
    return max(grid_limit_kwh - remaining_deficit_kwh, 0)


def _variable_value(variable: pulp.LpVariable) -> float:
    value = pulp.value(variable)
    if value is None:
        raise RuntimeError(f"LP variable has no solved value: {variable.name}")
    return _clean_value(value)


def _clean_value(value: float) -> float:
    numeric_value = float(value)
    if abs(numeric_value) < NUMERIC_TOLERANCE:
        return 0.0
    return numeric_value


def _clean_bound_value(
    value: float,
    lower_bound: float,
    upper_bound: float | None = None,
) -> float:
    numeric_value = _clean_value(value)
    if abs(numeric_value - lower_bound) <= SOC_BOUND_TOLERANCE:
        return lower_bound
    if (
        upper_bound is not None
        and abs(numeric_value - upper_bound) <= SOC_BOUND_TOLERANCE
    ):
        return upper_bound
    return numeric_value


def _clean_soc_value(value: float, battery: BatteryParameters) -> float:
    numeric_value = _clean_value(value)
    if (
        numeric_value < battery.min_soc_kwh
        and battery.min_soc_kwh - numeric_value <= SOC_BOUND_TOLERANCE
    ):
        return battery.min_soc_kwh
    if (
        numeric_value > battery.max_soc_kwh
        and numeric_value - battery.max_soc_kwh <= SOC_BOUND_TOLERANCE
    ):
        return battery.max_soc_kwh
    return numeric_value
