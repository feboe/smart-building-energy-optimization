"""Architecture checks for the shared BESS experiment runner."""

from __future__ import annotations

import sys

import pandas as pd
import pytest

import scripts.battery.run_bess_simulation as simulation_cli
from scripts.battery.experiment_defaults import (
    C_RATE,
    DEGRADATION_COST_EUR_PER_KWH,
    ETA_CHARGE,
    ETA_DISCHARGE,
    GRID_CONNECTION_LIMIT_KW,
    HORIZON_HOURS,
    make_standard_batteries,
    make_standard_scenarios,
)
from src.battery.audit import create_audit_export_config
from src.battery.experiment_runner import run_bess_experiment
from src.battery.heuristic import run_heuristic_dispatch
from src.battery.metrics import calculate_baseline_metrics, calculate_dispatch_metrics
from src.battery.optimization import run_optimized_dispatch


RUN_TIMESTAMP = "2021-01-01T00:00:00+00:00"


def _short_analysis(make_analysis_df) -> pd.DataFrame:
    return make_analysis_df(
        [
            {"total_w": -50_000, "pv_w": -100_000},
            {"total_w": 20_000, "day_ahead_price_eur_per_kwh": 0.05},
            {"total_w": 80_000, "day_ahead_price_eur_per_kwh": 0.50},
        ]
    )


def _stable_summary(frame: pd.DataFrame) -> pd.DataFrame:
    stable = frame.drop(columns=["elapsed_seconds", "dispatch_file"]).copy()
    return stable.sort_values(
        ["capacity_kwh", "method", "scenario", "price_model"],
        ignore_index=True,
    )


def test_standard_builders_keep_established_assumptions() -> None:
    battery = make_standard_batteries([1000])[0]
    scenarios = make_standard_scenarios(4.0)

    assert battery.max_charge_power_kw == 1000 * C_RATE == 500
    assert battery.max_discharge_power_kw == 500
    assert battery.eta_charge == ETA_CHARGE
    assert battery.eta_discharge == ETA_DISCHARGE
    assert battery.degradation_cost_eur_per_kwh == DEGRADATION_COST_EUR_PER_KWH
    assert [scenario.name for scenario in scenarios] == [
        "fixed_surplus_only",
        "dynamic_surplus_only",
        "dynamic_surplus_grid_charging",
    ]
    assert {scenario.horizon_hours for scenario in scenarios} == {HORIZON_HOURS}
    assert {scenario.terminal_value_window_hours for scenario in scenarios} == {4.0}
    assert scenarios[-1].grid_connection_limit_kw == GRID_CONNECTION_LIMIT_KW


def test_shared_runner_matches_direct_model_execution(make_analysis_df) -> None:
    """Golden-master the orchestration against direct model component calls."""
    analysis_df = _short_analysis(make_analysis_df)
    battery = make_standard_batteries([1000])[0]
    scenarios = make_standard_scenarios(4.0)
    result = run_bess_experiment(
        analysis_df,
        [battery],
        scenarios,
        experiment_name="golden_master",
        run_timestamp=RUN_TIMESTAMP,
        max_workers=1,
    )

    baseline = calculate_baseline_metrics(analysis_df, scenarios[0])
    fixed_baseline = result.query(
        "method == 'baseline' and price_model == 'fixed'"
    ).iloc[0]
    dynamic_baseline = result.query(
        "method == 'baseline' and price_model == 'dynamic'"
    ).iloc[0]
    assert fixed_baseline.net_cost_eur == pytest.approx(
        baseline["baseline_fixed_net_cost_eur"]
    )
    assert dynamic_baseline.net_cost_eur == pytest.approx(
        baseline["baseline_dynamic_net_cost_eur"]
    )

    for scenario in scenarios:
        for method, dispatch in (
            ("heuristic", run_heuristic_dispatch(analysis_df, battery, scenario)),
            ("lp_optimization", run_optimized_dispatch(analysis_df, battery, scenario)),
        ):
            expected = calculate_dispatch_metrics(
                analysis_df, dispatch, battery, scenario
            )
            actual = result.query(
                "method == @method and scenario == @scenario.name"
            ).iloc[0]
            for metric, expected_value in expected.items():
                if expected_value is None:
                    assert pd.isna(actual[metric])
                else:
                    assert actual[metric] == pytest.approx(expected_value)


def test_serial_and_parallel_runners_are_equivalent(make_analysis_df, tmp_path) -> None:
    analysis_df = _short_analysis(make_analysis_df)
    batteries = make_standard_batteries([1000])
    scenarios = make_standard_scenarios(4.0)
    serial_dir = tmp_path / "serial"
    parallel_dir = tmp_path / "parallel"

    serial = run_bess_experiment(
        analysis_df,
        batteries,
        scenarios,
        experiment_name="parallel_equivalence",
        run_timestamp=RUN_TIMESTAMP,
        max_workers=1,
        audit_export=create_audit_export_config(serial_dir),
    )
    parallel = run_bess_experiment(
        analysis_df,
        batteries,
        scenarios,
        experiment_name="parallel_equivalence",
        run_timestamp=RUN_TIMESTAMP,
        max_workers=2,
        audit_export=create_audit_export_config(parallel_dir),
    )

    pd.testing.assert_frame_equal(
        _stable_summary(serial),
        _stable_summary(parallel),
        check_exact=False,
        rtol=1e-9,
        atol=1e-9,
    )
    assert sorted(path.name for path in serial_dir.glob("*.parquet")) == sorted(
        path.name for path in parallel_dir.glob("*.parquet")
    )


def test_general_cli_defaults_to_15_minute_resolution(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["runner"])
    general_args = simulation_cli.parse_args()

    assert general_args.resolutions == ["15min"]
    assert general_args.days == 7
    assert general_args.terminal_value_window_hours == 4.0


def test_terminal_value_setting_reaches_all_scenarios() -> None:
    assert {
        scenario.terminal_value_window_hours
        for scenario in make_standard_scenarios(None)
    } == {None}
    assert {
        scenario.terminal_value_window_hours
        for scenario in make_standard_scenarios(4.0)
    } == {4.0}


@pytest.mark.parametrize(
    ("extra_args", "expected_terminal_value"),
    [([], 4.0), (["--no-terminal-value"], None)],
)
def test_general_cli_forwards_terminal_value_configuration(
    make_analysis_df,
    monkeypatch,
    tmp_path,
    extra_args,
    expected_terminal_value,
) -> None:
    analysis_df = _short_analysis(make_analysis_df)
    captured = {}

    def fake_runner(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame({"result": [1]})

    monkeypatch.setattr(
        simulation_cli, "load_smart_company_analysis", lambda **_: analysis_df
    )
    monkeypatch.setattr(simulation_cli, "run_bess_simulation", fake_runner)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--days",
            "1",
            "--output",
            str(tmp_path / "summary.csv"),
            *extra_args,
        ],
    )

    simulation_cli.main()

    assert captured["terminal_value_window_hours"] == expected_terminal_value
    assert set(captured["analysis_by_resolution"]) == {"15min"}
