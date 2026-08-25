"""Regression tests for timestep-independent BESS dispatch."""

import pytest

from src.battery.dispatch import horizon_steps, validate_dispatch_results
from src.battery.heuristic import run_heuristic_dispatch
from src.battery.metrics import calculate_baseline_metrics, calculate_dispatch_metrics
from src.battery.optimization import run_optimized_dispatch
from src.battery.scenarios import (
    make_battery_parameters,
    make_dynamic_surplus_and_grid_charging_scenario,
    make_fixed_surplus_only_scenario,
)


def _exact_battery():
    return make_battery_parameters(
        capacity_kwh=100,
        c_rate=1.0,
        min_soc_fraction=0.0,
        eta_charge=1.0,
        eta_discharge=1.0,
    )


def _quarter_hour_rows() -> list[dict]:
    return [
        {
            "resolution": "15min",
            "timestep_hours": 0.25,
            "total_w": -100_000,
            "pv_w": -200_000,
        }
        for _ in range(4)
    ] + [
        {
            "resolution": "15min",
            "timestep_hours": 0.25,
            "total_w": 100_000,
        }
        for _ in range(4)
    ]


@pytest.mark.parametrize("dispatch", [run_heuristic_dispatch, run_optimized_dispatch])
def test_four_quarter_hours_match_an_hour_of_constant_power(
    make_analysis_df,
    dispatch,
) -> None:
    battery = _exact_battery()
    scenario = make_fixed_surplus_only_scenario(horizon_hours=2)
    hourly_df = make_analysis_df(
        [
            {"total_w": -100_000, "pv_w": -200_000},
            {"total_w": 100_000},
        ]
    )
    quarter_hour_df = make_analysis_df(_quarter_hour_rows())

    hourly_dispatch = dispatch(hourly_df, battery, scenario)
    quarter_hour_dispatch = dispatch(quarter_hour_df, battery, scenario)

    for column in [
        "battery_charge_kwh",
        "discharge_to_load_kwh",
        "grid_import_kwh",
        "grid_export_kwh",
    ]:
        assert quarter_hour_dispatch[column].sum() == pytest.approx(
            hourly_dispatch[column].sum()
        )
    assert quarter_hour_dispatch.iloc[-1]["soc_end_kwh"] == pytest.approx(
        hourly_dispatch.iloc[-1]["soc_end_kwh"]
    )


@pytest.mark.parametrize("dispatch", [run_heuristic_dispatch, run_optimized_dispatch])
def test_quarter_hour_power_and_grid_limits_are_scaled(
    make_analysis_df,
    dispatch,
) -> None:
    battery = _exact_battery()
    scenario = make_dynamic_surplus_and_grid_charging_scenario(
        horizon_hours=2,
        grid_connection_limit_kw=50,
        surplus_reserve_fraction=0.0,
    )
    analysis_df = make_analysis_df(
        [
            {
                "resolution": "15min",
                "timestep_hours": 0.25,
                "total_w": 20_000,
                "day_ahead_price_eur_per_kwh": 0.0,
            },
            *[
                {
                    "resolution": "15min",
                    "timestep_hours": 0.25,
                    "total_w": 100_000,
                    "day_ahead_price_eur_per_kwh": 1.0,
                }
                for _ in range(7)
            ],
        ]
    )

    dispatch_df = dispatch(analysis_df, battery, scenario)

    assert dispatch_df["battery_charge_kwh"].max() <= 25.0 + 1e-6
    assert dispatch_df["discharge_to_load_kwh"].max() <= 25.0 + 1e-6
    assert dispatch_df.loc[0, "charge_from_grid_kwh"] == pytest.approx(7.5)
    assert dispatch_df.loc[0, "grid_import_kwh"] == pytest.approx(12.5)
    validate_dispatch_results(dispatch_df, battery)


def test_horizon_steps_use_real_hours_and_reject_inexact_combinations() -> None:
    assert horizon_steps(24, 1.0) == 24
    assert horizon_steps(24, 0.25) == 96
    with pytest.raises(ValueError, match="integer multiple"):
        horizon_steps(1, 0.3)


def test_peak_grid_import_is_reported_in_kw_for_quarter_hour_dispatch(
    make_analysis_df,
) -> None:
    battery = _exact_battery()
    scenario = make_fixed_surplus_only_scenario()
    analysis_df = make_analysis_df(
        [
            {
                "resolution": "15min",
                "timestep_hours": 0.25,
                "total_w": 100_000,
            }
        ]
    )
    dispatch_df = run_heuristic_dispatch(analysis_df, battery, scenario)

    baseline = calculate_baseline_metrics(analysis_df, scenario)
    metrics = calculate_dispatch_metrics(analysis_df, dispatch_df, battery, scenario)

    assert baseline["baseline_peak_grid_import_kwh"] == pytest.approx(25.0)
    assert baseline["baseline_peak_grid_import_kw"] == pytest.approx(100.0)
    assert metrics["peak_grid_import_kwh"] == pytest.approx(25.0)
    assert metrics["peak_grid_import_kw"] == pytest.approx(100.0)
