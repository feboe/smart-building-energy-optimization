"""Tests for optional, self-contained LP audit dispatch exports."""

from __future__ import annotations

import sys

import pandas as pd
import pytest
import scripts.battery.run_bess_simulation as simulation_runner
from scripts.battery.run_bess_simulation import run_bess_simulation
from src.battery.audit import build_lp_audit_dataframe
from src.battery.metrics import calculate_dispatch_metrics
from src.battery.optimization import HORIZON_DIAGNOSTIC_COLUMNS, run_optimized_dispatch
from src.battery.scenarios import (
    make_battery_parameters,
    make_dynamic_surplus_and_grid_charging_scenario,
)


def _battery():
    return make_battery_parameters(
        capacity_kwh=100,
        max_charge_power_kw=100,
        max_discharge_power_kw=100,
        min_soc_fraction=0.1,
        eta_charge=0.95,
        eta_discharge=0.95,
        degradation_cost_eur_per_kwh=0.03,
    )


def _scenario(terminal_value_window_hours: float | None = 4.0):
    return make_dynamic_surplus_and_grid_charging_scenario(
        export_price_eur_per_kwh=0.08,
        import_markup_eur_per_kwh=0.115,
        horizon_hours=4,
        terminal_value_window_hours=terminal_value_window_hours,
    )


def test_horizon_diagnostics_are_opt_in_and_audit_sums_match_metrics(make_analysis_df):
    analysis_df = make_analysis_df(
        [
            {"total_w": 50_000, "day_ahead_price_eur_per_kwh": 0.05},
            {"total_w": -20_000, "pv_w": -70_000, "day_ahead_price_eur_per_kwh": 0.1},
            {"total_w": 80_000, "day_ahead_price_eur_per_kwh": 0.4},
        ]
    )
    battery = _battery()
    scenario = _scenario()

    standard_dispatch = run_optimized_dispatch(analysis_df, battery, scenario)
    audited_dispatch = run_optimized_dispatch(
        analysis_df,
        battery,
        scenario,
        include_horizon_diagnostics=True,
    )

    assert not (set(HORIZON_DIAGNOSTIC_COLUMNS) & set(standard_dispatch.columns))
    assert set(HORIZON_DIAGNOSTIC_COLUMNS).issubset(audited_dispatch.columns)
    assert set(audited_dispatch["solver_status"]) == {"Optimal"}
    assert audited_dispatch["planning_horizon_steps"].tolist() == [3, 2, 1]
    assert audited_dispatch["planning_horizon_end_timestamp"].iloc[0] == pd.Timestamp(
        "2021-01-01T03:00:00Z"
    )

    audit_df = build_lp_audit_dataframe(
        analysis_df,
        audited_dispatch,
        battery,
        scenario,
        run_timestamp="2021-01-01T00:00:00+00:00",
    )
    required_columns = {
        "pv_generation_kw",
        "chp_generation_kwh",
        "used_import_price_eur_per_kwh",
        "charge_from_grid_kw",
        "soc_end_pct",
        "baseline_net_cost_eur",
        "cost_savings_eur",
        "remaining_grid_connection_headroom_kwh",
        *HORIZON_DIAGNOSTIC_COLUMNS,
    }
    assert required_columns.issubset(audit_df.columns)
    assert audit_df["net_cost_eur"].sum() == pytest.approx(
        audit_df["baseline_net_cost_eur"].sum() - audit_df["cost_savings_eur"].sum()
    )
    metrics = calculate_dispatch_metrics(
        analysis_df,
        audited_dispatch,
        battery,
        scenario,
    )
    assert audit_df["grid_import_kwh"].sum() == pytest.approx(
        metrics["grid_import_kwh"]
    )
    assert audit_df["net_cost_eur"].sum() == pytest.approx(metrics["net_cost_eur"])
    assert audit_df["cost_savings_eur"].sum() == pytest.approx(
        metrics["cost_savings_eur"]
    )
    assert (audit_df["remaining_grid_connection_headroom_kwh"] >= 0).all()


def test_multi_resolution_runner_exports_only_three_lp_parquet_files(
    make_analysis_df,
    tmp_path,
):
    analysis_df = make_analysis_df(
        [
            {"total_w": -50_000, "pv_w": -100_000},
            {"total_w": 50_000, "day_ahead_price_eur_per_kwh": 0.5},
        ]
    )
    dispatch_dir = tmp_path / "dispatch"

    result_df = run_bess_simulation(
        {"hour": analysis_df},
        capacities_kwh=[1000],
        run_timestamp="2021-01-01T00:00:00+00:00",
        max_workers=2,
        dispatch_dir=dispatch_dir,
    )

    export_files = sorted(dispatch_dir.glob("*.parquet"))
    assert len(export_files) == 3
    assert set(result_df.loc[result_df["method"] == "lp_optimization", "dispatch_file"])
    assert result_df.loc[result_df["method"] != "lp_optimization", "dispatch_file"].isna().all()
    for path in export_files:
        audit_df = pd.read_parquet(path)
        assert len(audit_df) == len(analysis_df)
        assert set(audit_df["method"]) == {"lp_optimization"}
        assert set(audit_df["resolution"]) == {"hour"}
        scenario = audit_df["scenario"].iloc[0]
        summary = result_df.query(
            "method == 'lp_optimization' and scenario == @scenario"
        ).iloc[0]
        assert audit_df["grid_import_kwh"].sum() == pytest.approx(
            summary.grid_import_kwh
        )
        assert audit_df["grid_export_kwh"].sum() == pytest.approx(
            summary.grid_export_kwh
        )
        assert audit_df["battery_charge_kwh"].sum() == pytest.approx(
            summary.battery_charge_throughput_kwh
        )
        assert audit_df["discharge_to_load_kwh"].sum() == pytest.approx(
            summary.battery_discharge_throughput_kwh
        )
        assert audit_df["net_cost_eur"].sum() == pytest.approx(summary.net_cost_eur)
        assert audit_df["cost_savings_eur"].sum() == pytest.approx(
            summary.cost_savings_eur
        )


def test_multi_resolution_runner_rejects_nonempty_dispatch_directory(make_analysis_df, tmp_path):
    analysis_df = make_analysis_df([{}])
    dispatch_dir = tmp_path / "existing_dispatch"
    dispatch_dir.mkdir()
    (dispatch_dir / "previous.parquet").touch()

    with pytest.raises(ValueError, match="new or empty"):
        run_bess_simulation(
            {"hour": analysis_df},
            capacities_kwh=[1000],
            max_workers=1,
            dispatch_dir=dispatch_dir,
        )


def test_audit_diagnostics_keep_terminal_fields_empty_when_disabled(make_analysis_df):
    analysis_df = make_analysis_df([{"total_w": 50_000}])
    dispatch_df = run_optimized_dispatch(
        analysis_df,
        _battery(),
        _scenario(terminal_value_window_hours=None),
        include_horizon_diagnostics=True,
    )

    assert pd.isna(dispatch_df["terminal_reference_price_eur_per_kwh"].iloc[0])
    assert dispatch_df["terminal_value_eur_per_kwh_soc"].iloc[0] == 0.0
    assert dispatch_df["horizon_terminal_credit_eur"].iloc[0] == 0.0


def test_cli_without_dispatch_export_keeps_existing_summary_behavior(
    make_analysis_df,
    monkeypatch,
    tmp_path,
):
    """The optional audit export must not change normal summary-file writes."""
    output_path = tmp_path / "existing_summary.csv"
    output_path.write_text("previous,result\n")
    analysis_df = make_analysis_df([{}])
    captured = {}

    def fake_runner(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame({"result": [1]})

    monkeypatch.setattr(
        simulation_runner, "load_smart_company_analysis", lambda **_: analysis_df
    )
    monkeypatch.setattr(simulation_runner, "run_bess_simulation", fake_runner)
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--resolutions", "hour", "--output", str(output_path)],
    )

    simulation_runner.main()

    assert captured["dispatch_dir"] is None
    assert pd.read_csv(output_path).to_dict("list") == {"result": [1]}
