"""Tests for the optional LP terminal-energy value."""

import math

import pandas as pd
import pytest

from src.battery.data import prepare_simulation_data
from src.battery.metrics import calculate_dispatch_metrics, fixed_import_price
from src.battery.optimization import (
    _terminal_value_eur_per_kwh_soc,
    run_optimized_dispatch,
)
from src.battery.parameters import FIXED_SURPLUS_ONLY, ScenarioParameters
from src.battery.scenarios import (
    make_battery_parameters,
    make_dynamic_surplus_only_scenario,
    make_fixed_surplus_only_scenario,
)


def _battery(
    *,
    eta_discharge: float = 0.95,
    degradation_cost_eur_per_kwh: float = 0.03,
):
    return make_battery_parameters(
        capacity_kwh=100,
        max_charge_power_kw=100,
        max_discharge_power_kw=100,
        min_soc_fraction=0.10,
        eta_charge=1.0,
        eta_discharge=eta_discharge,
        degradation_cost_eur_per_kwh=degradation_cost_eur_per_kwh,
    )


@pytest.mark.parametrize(
    "value",
    [0, -1, math.nan, math.inf, -math.inf, True, "four"],
)
def test_terminal_value_window_must_be_positive_and_finite(value) -> None:
    with pytest.raises(ValueError, match="terminal_value_window_hours"):
        make_dynamic_surplus_only_scenario(
            horizon_hours=4,
            terminal_value_window_hours=value,
        )


def test_terminal_value_window_must_not_exceed_horizon() -> None:
    with pytest.raises(ValueError, match="must not exceed horizon_hours"):
        make_dynamic_surplus_only_scenario(
            horizon_hours=4,
            terminal_value_window_hours=4.1,
        )


def test_terminal_value_is_disabled_by_default(make_analysis_df) -> None:
    battery = _battery()
    scenario = make_dynamic_surplus_only_scenario(horizon_hours=4)
    prepared_df = prepare_simulation_data(
        make_analysis_df([{} for _ in range(4)]), scenario
    )

    assert (
        _terminal_value_eur_per_kwh_soc(
            prepared_df, battery, scenario, fixed_import_price(prepared_df, scenario)
        )
        == 0.0
    )


def test_dynamic_terminal_value_uses_last_four_all_in_hourly_prices(
    make_analysis_df,
) -> None:
    battery = _battery(eta_discharge=0.8, degradation_cost_eur_per_kwh=0.05)
    scenario = make_dynamic_surplus_only_scenario(
        horizon_hours=5,
        import_markup_eur_per_kwh=0.10,
        terminal_value_window_hours=4.0,
    )
    prepared_df = prepare_simulation_data(
        make_analysis_df(
            [
                {"day_ahead_price_eur_per_kwh": 0.00},
                {"day_ahead_price_eur_per_kwh": 0.10},
                {"day_ahead_price_eur_per_kwh": 0.20},
                {"day_ahead_price_eur_per_kwh": 0.30},
                {"day_ahead_price_eur_per_kwh": 0.40},
            ]
        ),
        scenario,
    )

    value = _terminal_value_eur_per_kwh_soc(
        prepared_df, battery, scenario, fixed_import_price(prepared_df, scenario)
    )

    assert value == pytest.approx(0.8 * (((0.10 + 0.20 + 0.30 + 0.40) / 4 + 0.10) - 0.05))


def test_dynamic_terminal_value_uses_last_sixteen_quarter_hour_prices(
    make_analysis_df,
) -> None:
    battery = _battery(eta_discharge=1.0, degradation_cost_eur_per_kwh=0.0)
    scenario = make_dynamic_surplus_only_scenario(
        horizon_hours=5,
        terminal_value_window_hours=4.0,
    )
    analysis_df = make_analysis_df(
        [
            {
                "resolution": "15min",
                "timestep_hours": 0.25,
                "day_ahead_price_eur_per_kwh": 0.0 if step < 4 else 0.20,
            }
            for step in range(20)
        ]
    )
    prepared_df = prepare_simulation_data(analysis_df, scenario)

    value = _terminal_value_eur_per_kwh_soc(
        prepared_df, battery, scenario, fixed_import_price(prepared_df, scenario)
    )

    assert value == pytest.approx(0.20)


def test_terminal_value_uses_all_remaining_intervals_for_shortened_horizon(
    make_analysis_df,
) -> None:
    battery = _battery(eta_discharge=1.0, degradation_cost_eur_per_kwh=0.0)
    scenario = make_dynamic_surplus_only_scenario(
        horizon_hours=4,
        terminal_value_window_hours=4.0,
    )
    prepared_df = prepare_simulation_data(
        make_analysis_df(
            [
                {"day_ahead_price_eur_per_kwh": 0.20},
                {"day_ahead_price_eur_per_kwh": 0.40},
            ]
        ),
        scenario,
    )

    value = _terminal_value_eur_per_kwh_soc(
        prepared_df, battery, scenario, fixed_import_price(prepared_df, scenario)
    )

    assert value == pytest.approx(0.30)


def test_fixed_scenario_uses_its_full_fixed_import_price(make_analysis_df) -> None:
    battery = _battery(eta_discharge=0.9, degradation_cost_eur_per_kwh=0.05)
    scenario = ScenarioParameters(
        name="fixed",
        dispatch_strategy=FIXED_SURPLUS_ONLY,
        horizon_hours=4,
        fixed_import_price_eur_per_kwh=0.70,
        terminal_value_window_hours=4.0,
    )
    prepared_df = prepare_simulation_data(
        make_analysis_df(
            [
                {"day_ahead_price_eur_per_kwh": 0.10},
                {"day_ahead_price_eur_per_kwh": 0.90},
            ]
        ),
        scenario,
    )

    value = _terminal_value_eur_per_kwh_soc(
        prepared_df, battery, scenario, fixed_import_price(prepared_df, scenario)
    )

    assert value == pytest.approx(0.9 * (0.70 - 0.05))


def test_terminal_value_floors_negative_net_value_at_zero(make_analysis_df) -> None:
    battery = _battery(eta_discharge=0.95, degradation_cost_eur_per_kwh=0.30)
    scenario = make_dynamic_surplus_only_scenario(
        horizon_hours=4,
        terminal_value_window_hours=4.0,
    )
    prepared_df = prepare_simulation_data(
        make_analysis_df([{"day_ahead_price_eur_per_kwh": 0.10} for _ in range(4)]),
        scenario,
    )

    assert (
        _terminal_value_eur_per_kwh_soc(
            prepared_df, battery, scenario, fixed_import_price(prepared_df, scenario)
        )
        == 0.0
    )


def test_terminal_value_preserves_usable_soc_at_a_horizon_boundary(make_analysis_df) -> None:
    battery = _battery(eta_discharge=1.0, degradation_cost_eur_per_kwh=0.0)
    analysis_df = make_analysis_df(
        [
            {"total_w": 90_000, "day_ahead_price_eur_per_kwh": 0.50},
            {"day_ahead_price_eur_per_kwh": 1.00},
            {"day_ahead_price_eur_per_kwh": 1.00},
            {"day_ahead_price_eur_per_kwh": 1.00},
        ]
    )
    without_value = run_optimized_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_only_scenario(horizon_hours=4),
        initial_soc_kwh=100,
    )
    with_value = run_optimized_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_only_scenario(
            horizon_hours=4,
            terminal_value_window_hours=4.0,
        ),
        initial_soc_kwh=100,
    )

    assert without_value.loc[0, "soc_end_kwh"] == pytest.approx(battery.min_soc_kwh)
    assert with_value.loc[0, "soc_end_kwh"] == pytest.approx(100.0)


def test_terminal_value_is_not_included_in_reported_cost_kpis(make_analysis_df) -> None:
    battery = _battery(eta_discharge=1.0, degradation_cost_eur_per_kwh=0.0)
    scenario = make_dynamic_surplus_only_scenario(
        horizon_hours=4,
        terminal_value_window_hours=4.0,
    )
    analysis_df = make_analysis_df(
        [
            {"total_w": 90_000, "day_ahead_price_eur_per_kwh": 0.50},
            {"day_ahead_price_eur_per_kwh": 1.00},
            {"day_ahead_price_eur_per_kwh": 1.00},
            {"day_ahead_price_eur_per_kwh": 1.00},
        ]
    )
    dispatch_df = run_optimized_dispatch(
        analysis_df, battery, scenario, initial_soc_kwh=100
    )

    metrics = calculate_dispatch_metrics(analysis_df, dispatch_df, battery, scenario)

    assert metrics["grid_import_cost_eur"] == pytest.approx(45.0)
    assert metrics["electricity_net_cost_eur"] == pytest.approx(45.0)
    assert metrics["net_cost_eur"] == pytest.approx(45.0)
    assert metrics["initial_soc_kwh"] == pytest.approx(100.0)
    assert metrics["final_soc_kwh"] == pytest.approx(100.0)
    assert metrics["final_usable_soc_kwh"] == pytest.approx(
        100.0 - battery.min_soc_kwh
    )
    assert metrics["soc_change_kwh"] == pytest.approx(0.0)
