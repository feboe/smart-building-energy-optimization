"""General physical invariant tests for BESS dispatch outputs."""

import pandas as pd
import pytest

from src.battery.dispatch import validate_dispatch_results
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


def test_fixed_surplus_only_dispatch_satisfies_physics(
    make_analysis_df,
    assert_dispatch_physics,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": -50_000, "pv_w": -100_000},
            {"total_w": 50_000},
        ]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_fixed_surplus_only_scenario(),
    )

    assert_dispatch_physics(dispatch_df, battery)


def test_dynamic_surplus_only_dispatch_satisfies_physics(
    make_analysis_df,
    assert_dispatch_physics,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {
                "total_w": -50_000,
                "pv_w": -100_000,
                "day_ahead_price_eur_per_kwh": 0.10,
            },
            {"total_w": 50_000, "day_ahead_price_eur_per_kwh": 0.30},
        ]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_only_scenario(),
    )

    assert_dispatch_physics(dispatch_df, battery)


def test_dynamic_grid_charging_dispatch_satisfies_physics(
    make_analysis_df,
    assert_dispatch_physics,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": 20_000, "day_ahead_price_eur_per_kwh": 0.05},
            {"total_w": 100_000, "day_ahead_price_eur_per_kwh": 0.50},
        ]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_dynamic_surplus_and_grid_charging_scenario(
            grid_connection_limit_kw=150,
            surplus_reserve_fraction=0.0,
        ),
    )

    assert_dispatch_physics(dispatch_df, battery)


def test_validate_dispatch_results_rejects_nonfinite_values(
    make_analysis_df,
) -> None:
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": -50_000, "pv_w": -100_000},
            {"total_w": 50_000},
        ]
    )
    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_fixed_surplus_only_scenario(),
    )
    dispatch_df.loc[0, "gross_load_kwh"] = float("nan")

    with pytest.raises(ValueError, match="gross_load_kwh"):
        validate_dispatch_results(dispatch_df, battery)


def test_validate_dispatch_results_rejects_missing_columns() -> None:
    battery = _make_exact_battery()
    dispatch_df = pd.DataFrame()

    with pytest.raises(ValueError, match="Missing dispatch columns"):
        validate_dispatch_results(dispatch_df, battery)
