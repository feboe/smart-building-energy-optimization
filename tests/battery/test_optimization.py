"""LP optimizer-specific BESS dispatch tests."""

import pytest

from src.battery.dispatch import DISPATCH_COLUMNS, validate_dispatch_results
from src.battery.optimization import run_optimized_dispatch
from src.battery.scenarios import (
    make_battery_parameters,
    make_dynamic_surplus_and_grid_charging_scenario,
    make_dynamic_surplus_only_scenario,
    make_fixed_surplus_only_scenario,
)


def _make_exact_battery():
    return make_battery_parameters(
        capacity_kwh=100,
        c_rate=1.0,
        min_soc_fraction=0.0,
        eta_charge=1.0,
        eta_discharge=1.0,
        degradation_cost_eur_per_kwh=0.01,
    )


@pytest.mark.parametrize(
    "scenario",
    [
        make_fixed_surplus_only_scenario(horizon_hours=4),
        make_dynamic_surplus_only_scenario(horizon_hours=4),
        make_dynamic_surplus_and_grid_charging_scenario(
            horizon_hours=4,
            grid_connection_limit_kw=200,
            surplus_reserve_fraction=0.0,
        ),
    ],
)
def test_optimized_dispatch_satisfies_physics_for_all_scenarios(
    make_analysis_df,
    scenario,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {
                "total_w": -50_000,
                "pv_w": -100_000,
                "day_ahead_price_eur_per_kwh": 0.05,
            },
            {"total_w": 40_000, "day_ahead_price_eur_per_kwh": 0.50},
            {"total_w": 20_000, "day_ahead_price_eur_per_kwh": 0.20},
            {
                "total_w": -30_000,
                "pv_w": -60_000,
                "day_ahead_price_eur_per_kwh": 0.10,
            },
        ]
    )

    dispatch_df = run_optimized_dispatch(analysis_df, battery, scenario)

    assert list(dispatch_df.columns) == DISPATCH_COLUMNS
    assert len(dispatch_df) == len(analysis_df)
    validate_dispatch_results(dispatch_df, battery)


@pytest.mark.parametrize(
    "scenario",
    [
        make_fixed_surplus_only_scenario(horizon_hours=3),
        make_dynamic_surplus_only_scenario(horizon_hours=3),
    ],
)
def test_surplus_only_optimizer_never_charges_from_grid(
    make_analysis_df,
    scenario,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": 20_000, "day_ahead_price_eur_per_kwh": 0.00},
            {"total_w": 80_000, "day_ahead_price_eur_per_kwh": 1.00},
            {
                "total_w": -100_000,
                "pv_w": -200_000,
                "day_ahead_price_eur_per_kwh": 0.10,
            },
        ]
    )

    dispatch_df = run_optimized_dispatch(analysis_df, battery, scenario)

    assert dispatch_df["charge_from_grid_kwh"].sum() == pytest.approx(0.0)


def test_fixed_surplus_only_optimizer_charges_surplus_then_discharges_deficit(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": -50_000, "pv_w": -100_000},
            {"total_w": 40_000},
        ]
    )

    dispatch_df = run_optimized_dispatch(
        analysis_df,
        battery,
        make_fixed_surplus_only_scenario(horizon_hours=2),
    )

    assert dispatch_df.loc[0, "charge_from_surplus_kwh"] >= 40.0
    assert dispatch_df.loc[1, "discharge_to_load_kwh"] == pytest.approx(40.0)
    assert dispatch_df.loc[1, "grid_import_kwh"] == pytest.approx(0.0)
    validate_dispatch_results(dispatch_df, battery)


def test_dynamic_surplus_only_optimizer_uses_surplus_for_high_price_deficit(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {
                "total_w": -50_000,
                "pv_w": -100_000,
                "day_ahead_price_eur_per_kwh": 0.10,
            },
            {"total_w": 40_000, "day_ahead_price_eur_per_kwh": 1.00},
        ]
    )

    dispatch_df = run_optimized_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_only_scenario(horizon_hours=2),
    )

    assert dispatch_df.loc[0, "charge_from_surplus_kwh"] >= 40.0
    assert dispatch_df.loc[1, "discharge_to_load_kwh"] == pytest.approx(40.0)
    assert dispatch_df.loc[1, "grid_import_kwh"] == pytest.approx(0.0)
    validate_dispatch_results(dispatch_df, battery)


def test_dynamic_grid_charging_uses_low_price_charge_and_high_price_discharge(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": 20_000, "day_ahead_price_eur_per_kwh": 0.00},
            {"total_w": 80_000, "day_ahead_price_eur_per_kwh": 1.00},
            {
                "total_w": -100_000,
                "pv_w": -200_000,
                "day_ahead_price_eur_per_kwh": 0.10,
            },
        ]
    )

    dispatch_df = run_optimized_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_and_grid_charging_scenario(
            horizon_hours=3,
            grid_connection_limit_kw=200,
            surplus_reserve_fraction=0.0,
        ),
    )

    assert dispatch_df.loc[0, "charge_from_grid_kwh"] > 0
    assert dispatch_df.loc[1, "discharge_to_load_kwh"] > 0


def test_dynamic_grid_charging_optimizer_charges_then_discharges_without_recharge(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": 0, "day_ahead_price_eur_per_kwh": 0.00},
            {"total_w": 50_000, "day_ahead_price_eur_per_kwh": 1.00},
        ]
    )

    dispatch_df = run_optimized_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_and_grid_charging_scenario(
            horizon_hours=2,
            grid_connection_limit_kw=100,
            surplus_reserve_fraction=0.0,
        ),
    )

    assert dispatch_df.loc[0, "charge_from_grid_kwh"] == pytest.approx(50.0)
    assert dispatch_df.loc[1, "discharge_to_load_kwh"] == pytest.approx(50.0)
    assert dispatch_df.loc[1, "grid_import_kwh"] == pytest.approx(0.0)
    validate_dispatch_results(dispatch_df, battery)


def test_dynamic_grid_charging_optimizer_does_not_charge_without_future_value(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": 0, "day_ahead_price_eur_per_kwh": 0.10},
            {"total_w": 0, "day_ahead_price_eur_per_kwh": 0.20},
        ]
    )

    dispatch_df = run_optimized_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_and_grid_charging_scenario(
            horizon_hours=2,
            grid_connection_limit_kw=100,
            surplus_reserve_fraction=0.0,
        ),
    )

    assert dispatch_df["charge_from_grid_kwh"].sum() == pytest.approx(0.0)
    assert dispatch_df["discharge_to_load_kwh"].sum() == pytest.approx(0.0)
    validate_dispatch_results(dispatch_df, battery)


def test_grid_connection_limit_caps_extra_grid_charging(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": 80_000, "day_ahead_price_eur_per_kwh": 0.00},
            {"total_w": 100_000, "day_ahead_price_eur_per_kwh": 1.00},
            {
                "total_w": -100_000,
                "pv_w": -200_000,
                "day_ahead_price_eur_per_kwh": 0.10,
            },
        ]
    )

    dispatch_df = run_optimized_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_and_grid_charging_scenario(
            horizon_hours=3,
            grid_connection_limit_kw=100,
            surplus_reserve_fraction=0.0,
        ),
    )

    assert dispatch_df.loc[0, "charge_from_grid_kwh"] == pytest.approx(20.0)
    assert dispatch_df.loc[0, "grid_import_kwh"] == pytest.approx(100.0)


def test_optimizer_handles_shorter_final_horizon(make_analysis_df) -> None:
    battery = _make_exact_battery()
    scenario = make_dynamic_surplus_and_grid_charging_scenario(
        horizon_hours=24,
        grid_connection_limit_kw=200,
        surplus_reserve_fraction=0.0,
    )
    analysis_df = make_analysis_df(
        [
            {"total_w": 20_000, "day_ahead_price_eur_per_kwh": 0.00},
            {"total_w": 80_000, "day_ahead_price_eur_per_kwh": 1.00},
            {
                "total_w": -100_000,
                "pv_w": -200_000,
                "day_ahead_price_eur_per_kwh": 0.10,
            },
        ]
    )

    dispatch_df = run_optimized_dispatch(analysis_df, battery, scenario)

    assert len(dispatch_df) == 3
    validate_dispatch_results(dispatch_df, battery)
