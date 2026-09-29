"""Regression tests for BESS standby and passive-loss modelling."""

import math

import pytest

from src.battery.audit import build_lp_audit_dataframe
from src.battery.data import prepare_bess_simulation_data
from src.battery.dispatch import self_discharge_loss_kwh, validate_dispatch_results
from src.battery.heuristic import run_heuristic_dispatch
from src.battery.metrics import calculate_baseline_metrics, calculate_dispatch_metrics
from src.battery.optimization import _solve_horizon, run_optimized_dispatch
from src.battery.parameters import BESS_MODEL_VERSION
from src.battery.scenarios import (
    make_battery_parameters,
    make_fixed_surplus_only_scenario,
)


def _loss_battery(**overrides):
    configured = {
        "capacity_kwh": 100.0,
        "max_charge_power_kw": 100.0,
        "max_discharge_power_kw": 100.0,
        "min_soc_fraction": 0.0,
        "eta_charge": 1.0,
        "eta_discharge": 1.0,
    }
    configured.update(overrides)
    return make_battery_parameters(**configured)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"standby_power_kw": -0.01},
        {"standby_power_kw": math.inf},
        {"self_discharge_rate_per_month": -0.01},
        {"self_discharge_rate_per_month": math.inf},
        {"self_discharge_rate_per_month": 1.0},
    ],
)
def test_loss_parameters_reject_invalid_values(kwargs) -> None:
    with pytest.raises(ValueError):
        _loss_battery(**kwargs)


def test_bess_preparation_adds_standby_without_mutating_historical_input(
    make_analysis_df,
) -> None:
    analysis_df = make_analysis_df(
        [
            {
                "resolution": "15min",
                "timestep_hours": 0.25,
                "total_w": 0.0,
                "pv_w": -100_000.0,
            }
        ]
    )
    original_columns = analysis_df.columns.tolist()
    battery = _loss_battery(standby_power_kw=5.0)

    prepared = prepare_bess_simulation_data(
        analysis_df,
        make_fixed_surplus_only_scenario(),
        battery,
    )

    assert analysis_df.columns.tolist() == original_columns
    assert prepared.loc[0, "gross_load_kwh"] == pytest.approx(25.0)
    assert prepared.loc[0, "bess_standby_consumption_kwh"] == pytest.approx(1.25)
    assert prepared.loc[0, "site_load_with_bess_kwh"] == pytest.approx(26.25)
    assert prepared.loc[0, "available_surplus_kwh"] == pytest.approx(0.0)
    assert prepared.loc[0, "demand_after_generation_kwh"] == pytest.approx(1.25)


@pytest.mark.parametrize("dispatch", [run_heuristic_dispatch, run_optimized_dispatch])
def test_local_generation_then_grid_supplies_bess_standby(make_analysis_df, dispatch) -> None:
    analysis_df = make_analysis_df(
        [
            {
                "resolution": "15min",
                "timestep_hours": 0.25,
                "total_w": 0.0,
                "pv_w": -100_000.0,
            }
        ]
    )
    battery = _loss_battery(standby_power_kw=5.0)
    dispatch_df = dispatch(
        analysis_df,
        battery,
        make_fixed_surplus_only_scenario(),
    )

    assert dispatch_df.loc[0, "gross_load_kwh"] == pytest.approx(25.0)
    assert dispatch_df.loc[0, "site_load_with_bess_kwh"] == pytest.approx(26.25)
    assert dispatch_df.loc[0, "grid_import_kwh"] == pytest.approx(1.25)
    validate_dispatch_results(dispatch_df, battery)


@pytest.mark.parametrize("dispatch", [run_heuristic_dispatch, run_optimized_dispatch])
def test_existing_soc_supplies_bess_standby_before_grid_import(
    make_analysis_df,
    dispatch,
) -> None:
    battery = _loss_battery(standby_power_kw=5.0)
    dispatch_df = dispatch(
        make_analysis_df([{}]),
        battery,
        make_fixed_surplus_only_scenario(),
        initial_soc_kwh=10.0,
    )

    assert dispatch_df.loc[0, "site_load_with_bess_kwh"] == pytest.approx(5.0)
    assert dispatch_df.loc[0, "discharge_to_load_kwh"] == pytest.approx(5.0)
    assert dispatch_df.loc[0, "grid_import_kwh"] == pytest.approx(0.0)
    assert dispatch_df.loc[0, "soc_end_kwh"] == pytest.approx(5.0)
    validate_dispatch_results(dispatch_df, battery)


@pytest.mark.parametrize("dispatch", [run_heuristic_dispatch, run_optimized_dispatch])
def test_self_discharge_is_timestep_consistent_and_stops_at_minimum(
    make_analysis_df,
    dispatch,
) -> None:
    battery = _loss_battery(self_discharge_rate_per_month=0.01)
    scenario = make_fixed_surplus_only_scenario(horizon_hours=2)
    hourly = dispatch(make_analysis_df([{}]), battery, scenario, initial_soc_kwh=100.0)
    quarter_hour = dispatch(
        make_analysis_df(
            [
                {"resolution": "15min", "timestep_hours": 0.25}
                for _ in range(4)
            ]
        ),
        battery,
        scenario,
        initial_soc_kwh=100.0,
    )

    assert quarter_hour.loc[3, "soc_end_kwh"] == pytest.approx(
        hourly.loc[0, "soc_end_kwh"]
    )
    assert quarter_hour["self_discharge_loss_kwh"].sum() == pytest.approx(
        hourly["self_discharge_loss_kwh"].sum()
    )
    at_minimum = dispatch(
        make_analysis_df([{}]),
        battery,
        scenario,
        initial_soc_kwh=battery.min_soc_kwh,
    )
    assert at_minimum.loc[0, "self_discharge_loss_kwh"] == 0.0


def test_lp_horizon_applies_self_discharge_to_every_planned_step(make_analysis_df) -> None:
    battery = _loss_battery(self_discharge_rate_per_month=0.01)
    scenario = make_fixed_surplus_only_scenario(horizon_hours=2)
    horizon = prepare_bess_simulation_data(
        make_analysis_df([{}, {}]), scenario, battery
    )

    solution = _solve_horizon(
        horizon_df=horizon,
        horizon_initial_soc_kwh=100.0,
        battery=battery,
        scenario=scenario,
        fixed_import_price_eur_per_kwh=0.1,
        solver=None,
        solver_msg=False,
    )

    assert solution["planned_terminal_soc_kwh"] == pytest.approx(
        100.0 * (1 - 0.01) ** (2 / 720)
    )


def test_baseline_stays_unchanged_and_summary_and_audit_export_passive_losses(
    make_analysis_df,
) -> None:
    analysis_df = make_analysis_df(
        [
            {"total_w": -10_000.0, "pv_w": -20_000.0},
            {"total_w": 10_000.0},
        ]
    )
    scenario = make_fixed_surplus_only_scenario(horizon_hours=2)
    battery = _loss_battery(
        standby_power_kw=5.0,
        self_discharge_rate_per_month=0.01,
    )
    baseline_before = calculate_baseline_metrics(analysis_df, scenario)
    dispatch = run_optimized_dispatch(
        analysis_df,
        battery,
        scenario,
        initial_soc_kwh=50.0,
        include_horizon_diagnostics=True,
    )
    metrics = calculate_dispatch_metrics(analysis_df, dispatch, battery, scenario)
    audit = build_lp_audit_dataframe(
        analysis_df,
        dispatch,
        battery,
        scenario,
        run_timestamp="2021-01-01T00:00:00+00:00",
        experiment_name="passive_loss_test",
    )

    assert calculate_baseline_metrics(analysis_df, scenario) == baseline_before
    assert metrics["model_version"] == BESS_MODEL_VERSION
    assert metrics["standby_power_kw"] == 5.0
    assert metrics["bess_standby_consumption_kwh"] == pytest.approx(10.0)
    assert metrics["self_discharge_loss_kwh"] == pytest.approx(
        dispatch["self_discharge_loss_kwh"].sum()
    )
    required_passive_loss_columns = {
        "model_version",
        "standby_power_kw",
        "self_discharge_rate_per_month",
        "bess_standby_consumption_kwh",
        "site_load_with_bess_kwh",
        "self_discharge_loss_kwh",
    }
    assert required_passive_loss_columns.issubset(audit.columns)
    assert set(audit["model_version"]) == {BESS_MODEL_VERSION}
    assert set(audit["experiment_name"]) == {"passive_loss_test"}


def test_validator_rejects_manipulated_passive_loss_columns(make_analysis_df) -> None:
    battery = _loss_battery(standby_power_kw=5.0, self_discharge_rate_per_month=0.01)
    dispatch = run_heuristic_dispatch(
        make_analysis_df([{}]),
        battery,
        make_fixed_surplus_only_scenario(),
        initial_soc_kwh=50.0,
    )

    invalid_standby = dispatch.copy()
    invalid_standby.loc[0, "bess_standby_consumption_kwh"] += 1.0
    with pytest.raises(ValueError, match="standby"):
        validate_dispatch_results(invalid_standby, battery)

    invalid_loss = dispatch.copy()
    invalid_loss.loc[0, "self_discharge_loss_kwh"] += 1.0
    with pytest.raises(ValueError, match="Self-discharge"):
        validate_dispatch_results(invalid_loss, battery)

    invalid_soc = dispatch.copy()
    invalid_soc.loc[0, "soc_end_kwh"] += 1.0
    with pytest.raises(ValueError, match="SOC balance"):
        validate_dispatch_results(invalid_soc, battery)


def test_self_discharge_helper_uses_only_usable_soc() -> None:
    battery = _loss_battery(min_soc_fraction=0.1, self_discharge_rate_per_month=0.01)

    assert self_discharge_loss_kwh(10.0, battery, 1.0) == 0.0
    assert self_discharge_loss_kwh(100.0, battery, 720.0) == pytest.approx(0.9)
