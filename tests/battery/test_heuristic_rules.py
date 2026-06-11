"""Heuristic-specific BESS dispatch rule tests."""

import pytest

from src.battery.heuristic import run_heuristic_dispatch
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
    )


@pytest.mark.parametrize(
    "scenario",
    [
        make_fixed_surplus_only_scenario(),
        make_dynamic_surplus_only_scenario(),
    ],
)
def test_surplus_only_scenarios_never_charge_from_grid(
    make_analysis_df,
    scenario,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {
                "total_w": -40_000,
                "pv_w": -80_000,
                "day_ahead_price_eur_per_kwh": 0.05,
            },
            {"total_w": 40_000, "day_ahead_price_eur_per_kwh": 0.50},
        ]
    )

    dispatch_df = run_heuristic_dispatch(analysis_df, battery, scenario)

    assert dispatch_df["charge_from_grid_kwh"].sum() == pytest.approx(0.0)


def test_fixed_surplus_only_charges_surplus_then_discharges_deficit(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": -30_000, "pv_w": -60_000},
            {"total_w": 20_000},
        ]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_fixed_surplus_only_scenario(),
    )

    assert dispatch_df.loc[0, "charge_from_surplus_kwh"] == pytest.approx(30.0)
    assert dispatch_df.loc[0, "soc_end_kwh"] == pytest.approx(30.0)
    assert dispatch_df.loc[1, "discharge_to_load_kwh"] == pytest.approx(20.0)
    assert dispatch_df.loc[1, "grid_import_kwh"] == pytest.approx(0.0)


def test_dynamic_grid_charging_charges_from_grid_only_in_low_price_hours(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": 10_000, "day_ahead_price_eur_per_kwh": 0.00},
            {"total_w": 10_000, "day_ahead_price_eur_per_kwh": 0.40},
            {"total_w": 100_000, "day_ahead_price_eur_per_kwh": 1.00},
        ]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_and_grid_charging_scenario(
            grid_connection_limit_kw=200,
            surplus_reserve_fraction=0.0,
        ),
    )

    grid_charge_rows = dispatch_df["charge_from_grid_kwh"] > 1e-6
    assert grid_charge_rows.any()
    assert dispatch_df.loc[grid_charge_rows, "is_low_price"].all()
    assert dispatch_df.loc[
        ~dispatch_df["is_low_price"], "charge_from_grid_kwh"
    ].sum() == pytest.approx(0.0)


def test_dynamic_surplus_only_discharges_only_in_high_price_hours(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {
                "total_w": -60_000,
                "pv_w": -120_000,
                "day_ahead_price_eur_per_kwh": 0.10,
            },
            {"total_w": 20_000, "day_ahead_price_eur_per_kwh": 0.20},
            {"total_w": 20_000, "day_ahead_price_eur_per_kwh": 0.90},
        ]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_only_scenario(),
    )

    discharge_rows = dispatch_df["discharge_to_load_kwh"] > 1e-6
    assert dispatch_df.loc[1, "discharge_to_load_kwh"] == pytest.approx(0.0)
    assert dispatch_df.loc[2, "discharge_to_load_kwh"] == pytest.approx(20.0)
    assert dispatch_df.loc[discharge_rows, "is_high_price"].all()


def test_grid_connection_limit_caps_extra_grid_charging(make_analysis_df) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [{"total_w": 20_000, "day_ahead_price_eur_per_kwh": 0.0}]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_and_grid_charging_scenario(
            grid_connection_limit_kw=50,
            surplus_reserve_fraction=0.0,
        ),
    )

    assert dispatch_df.loc[0, "charge_from_grid_kwh"] == pytest.approx(30.0)
    assert dispatch_df.loc[0, "grid_import_kwh"] == pytest.approx(50.0)


def test_grid_connection_limit_does_not_shed_natural_deficit(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [{"total_w": 80_000, "day_ahead_price_eur_per_kwh": 0.0}]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_and_grid_charging_scenario(
            grid_connection_limit_kw=50,
            surplus_reserve_fraction=0.0,
        ),
    )

    assert dispatch_df.loc[0, "charge_from_grid_kwh"] == pytest.approx(0.0)
    assert dispatch_df.loc[0, "grid_import_kwh"] == pytest.approx(80.0)


def test_future_surplus_headroom_limits_grid_charging(make_analysis_df) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": 10_000, "day_ahead_price_eur_per_kwh": 0.0},
            {
                "total_w": -40_000,
                "pv_w": -80_000,
                "day_ahead_price_eur_per_kwh": 0.5,
            },
        ]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_and_grid_charging_scenario(
            horizon_hours=2,
            grid_connection_limit_kw=500,
            surplus_reserve_fraction=1.0,
        ),
    )

    assert dispatch_df.loc[0, "future_surplus_kwh"] == pytest.approx(40.0)
    assert dispatch_df.loc[0, "reserved_surplus_headroom_kwh"] == pytest.approx(40.0)
    assert dispatch_df.loc[0, "grid_charge_soc_limit_kwh"] == pytest.approx(60.0)
    assert dispatch_df.loc[0, "charge_from_grid_kwh"] == pytest.approx(60.0)


def test_zero_future_surplus_reserve_allows_full_grid_charging(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": 10_000, "day_ahead_price_eur_per_kwh": 0.0},
            {
                "total_w": -40_000,
                "pv_w": -80_000,
                "day_ahead_price_eur_per_kwh": 0.5,
            },
        ]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_and_grid_charging_scenario(
            horizon_hours=2,
            grid_connection_limit_kw=500,
            surplus_reserve_fraction=0.0,
        ),
    )

    assert dispatch_df.loc[0, "reserved_surplus_headroom_kwh"] == pytest.approx(0.0)
    assert dispatch_df.loc[0, "grid_charge_soc_limit_kwh"] == pytest.approx(100.0)
    assert dispatch_df.loc[0, "charge_from_grid_kwh"] == pytest.approx(100.0)
