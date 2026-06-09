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


def _make_valid_dispatch(make_analysis_df):
    battery = _make_exact_battery()
    analysis_df = make_analysis_df(
        [
            {"total_w": -40_000, "pv_w": -80_000},
            {"total_w": 20_000},
        ]
    )
    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_fixed_surplus_only_scenario(),
    )
    return battery, dispatch_df


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


def test_dispatch_applies_charge_and_discharge_efficiency(
    make_analysis_df,
) -> None:
    battery = make_battery_parameters(
        capacity_kwh=200,
        c_rate=1.0,
        min_soc_fraction=0.0,
        eta_charge=0.95,
        eta_discharge=0.95,
    )
    analysis_df = make_analysis_df(
        [
            {"total_w": -100_000, "pv_w": -200_000},
            {"total_w": 100_000},
        ]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_fixed_surplus_only_scenario(),
    )

    assert dispatch_df.loc[0, "charge_from_surplus_kwh"] == pytest.approx(100.0)
    assert dispatch_df.loc[0, "soc_end_kwh"] == pytest.approx(95.0)
    assert dispatch_df.loc[1, "discharge_to_load_kwh"] == pytest.approx(90.25)
    assert dispatch_df.loc[1, "grid_import_kwh"] == pytest.approx(9.75)
    assert dispatch_df.loc[1, "soc_end_kwh"] == pytest.approx(0.0)


def test_dispatch_respects_minimum_soc_reserve(
    make_analysis_df,
) -> None:
    battery = make_battery_parameters(
        capacity_kwh=100,
        c_rate=1.0,
        min_soc_fraction=0.10,
        eta_charge=1.0,
        eta_discharge=1.0,
    )
    analysis_df = make_analysis_df([{"total_w": 50_000}])

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_fixed_surplus_only_scenario(),
    )

    assert dispatch_df.loc[0, "soc_start_kwh"] == pytest.approx(10.0)
    assert dispatch_df.loc[0, "discharge_to_load_kwh"] == pytest.approx(0.0)
    assert dispatch_df.loc[0, "grid_import_kwh"] == pytest.approx(50.0)
    assert dispatch_df.loc[0, "soc_end_kwh"] == pytest.approx(10.0)


def test_dispatch_respects_c_rate_power_limit(
    make_analysis_df,
) -> None:
    battery = make_battery_parameters(
        capacity_kwh=100,
        c_rate=0.5,
        min_soc_fraction=0.0,
        eta_charge=1.0,
        eta_discharge=1.0,
    )
    analysis_df = make_analysis_df(
        [
            {"total_w": -100_000, "pv_w": -200_000},
            {"total_w": 100_000},
        ]
    )

    dispatch_df = run_heuristic_dispatch(
        analysis_df,
        battery,
        make_fixed_surplus_only_scenario(),
    )

    assert dispatch_df.loc[0, "charge_from_surplus_kwh"] == pytest.approx(50.0)
    assert dispatch_df.loc[0, "grid_export_kwh"] == pytest.approx(50.0)
    assert dispatch_df.loc[0, "soc_end_kwh"] == pytest.approx(50.0)
    assert dispatch_df.loc[1, "discharge_to_load_kwh"] == pytest.approx(50.0)
    assert dispatch_df.loc[1, "grid_import_kwh"] == pytest.approx(50.0)


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


def test_validate_dispatch_results_rejects_soc_start_below_bounds(
    make_analysis_df,
) -> None:
    battery, dispatch_df = _make_valid_dispatch(make_analysis_df)
    dispatch_df.loc[0, "soc_start_kwh"] = -1.0

    with pytest.raises(ValueError, match="SOC start falls below"):
        validate_dispatch_results(dispatch_df, battery)


def test_validate_dispatch_results_rejects_charge_power_above_limit(
    make_analysis_df,
) -> None:
    battery, dispatch_df = _make_valid_dispatch(make_analysis_df)
    dispatch_df.loc[0, "charge_from_surplus_kwh"] = 101.0
    dispatch_df.loc[0, "battery_charge_kwh"] = 101.0

    with pytest.raises(ValueError, match="charge exceeds"):
        validate_dispatch_results(dispatch_df, battery)


def test_validate_dispatch_results_rejects_discharge_power_above_limit(
    make_analysis_df,
) -> None:
    battery, dispatch_df = _make_valid_dispatch(make_analysis_df)
    dispatch_df.loc[1, "discharge_to_load_kwh"] = 101.0

    with pytest.raises(ValueError, match="discharge exceeds"):
        validate_dispatch_results(dispatch_df, battery)


def test_validate_dispatch_results_rejects_surplus_charge_above_available(
    make_analysis_df,
) -> None:
    battery, dispatch_df = _make_valid_dispatch(make_analysis_df)
    dispatch_df.loc[0, "charge_from_surplus_kwh"] = 41.0
    dispatch_df.loc[0, "battery_charge_kwh"] = 41.0

    with pytest.raises(ValueError, match="more surplus than available"):
        validate_dispatch_results(dispatch_df, battery)


def test_validate_dispatch_results_rejects_discharge_above_remaining_demand(
    make_analysis_df,
) -> None:
    battery, dispatch_df = _make_valid_dispatch(make_analysis_df)
    dispatch_df.loc[1, "discharge_to_load_kwh"] = 21.0

    with pytest.raises(ValueError, match="more energy than remaining demand"):
        validate_dispatch_results(dispatch_df, battery)


def test_validate_dispatch_results_rejects_simultaneous_charge_and_discharge(
    make_analysis_df,
) -> None:
    battery, dispatch_df = _make_valid_dispatch(make_analysis_df)
    dispatch_df.loc[1, "charge_from_grid_kwh"] = 1.0
    dispatch_df.loc[1, "battery_charge_kwh"] = 1.0

    with pytest.raises(ValueError, match="charges and discharges"):
        validate_dispatch_results(dispatch_df, battery)


def test_validate_dispatch_results_rejects_export_not_leftover_surplus(
    make_analysis_df,
) -> None:
    battery, dispatch_df = _make_valid_dispatch(make_analysis_df)
    dispatch_df.loc[0, "grid_export_kwh"] = 1.0

    with pytest.raises(ValueError, match="leftover local surplus"):
        validate_dispatch_results(dispatch_df, battery)


def test_validate_dispatch_results_rejects_inconsistent_charge_components(
    make_analysis_df,
) -> None:
    battery, dispatch_df = _make_valid_dispatch(make_analysis_df)
    dispatch_df.loc[0, "battery_charge_kwh"] = 41.0

    with pytest.raises(ValueError, match="charge components"):
        validate_dispatch_results(dispatch_df, battery)
