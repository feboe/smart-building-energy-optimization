"""Shared orchestration for BESS baseline, heuristic, and LP experiments."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from time import perf_counter

import pandas as pd

from src.battery.audit import (
    AuditExportConfig,
    build_lp_audit_dataframe,
    dispatch_export_path,
    format_export_path,
    write_audit_parquet_atomically,
)
from src.battery.heuristic import run_heuristic_dispatch
from src.battery.metrics import calculate_baseline_metrics, calculate_dispatch_metrics
from src.battery.optimization import run_optimized_dispatch
from src.battery.parameters import BatteryParameters, ScenarioParameters


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAX_PARALLEL_WORKERS = min(4, os.cpu_count() or 1)

METADATA_COLUMNS = [
    "experiment_name",
    "run_timestamp",
    "elapsed_seconds",
    "method",
    "scenario",
    "price_model",
    "capacity_kwh",
    "max_charge_power_kw",
    "max_discharge_power_kw",
    "charge_c_rate",
    "discharge_c_rate",
    "import_markup_eur_per_kwh",
    "export_price_eur_per_kwh",
    "horizon_hours",
    "terminal_value_window_hours",
    "terminal_value_applied",
    "dispatch_file",
    "low_price_quantile",
    "high_price_quantile",
    "eta_charge",
    "eta_discharge",
    "min_soc_fraction",
    "max_soc_fraction",
]


@dataclass(frozen=True)
class _DispatchJob:
    battery: BatteryParameters
    scenario: ScenarioParameters


def run_bess_experiment(
    analysis_df: pd.DataFrame,
    batteries: list[BatteryParameters],
    scenarios: list[ScenarioParameters],
    experiment_name: str,
    run_timestamp: str | None = None,
    max_workers: int | None = None,
    audit_export: AuditExportConfig | None = None,
    baseline_scenario: ScenarioParameters | None = None,
) -> pd.DataFrame:
    """Run all requested BESS configurations and return a compact KPI summary.

    Inputs are already resolved deliberately.  This module does not decide
    which capacities, resolution, tariff, or output path belongs to a study.
    """
    if analysis_df.empty:
        raise ValueError("analysis_df must not be empty.")
    if not batteries:
        raise ValueError("batteries must not be empty.")
    if not scenarios:
        raise ValueError("scenarios must not be empty.")
    if not experiment_name:
        raise ValueError("experiment_name must not be empty.")

    timestamp = run_timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    baseline_parameters = baseline_scenario or scenarios[0]
    rows = _baseline_rows(
        analysis_df=analysis_df,
        scenario=baseline_parameters,
        battery=batteries[0],
        experiment_name=experiment_name,
        run_timestamp=timestamp,
    )
    jobs = [
        _DispatchJob(battery=battery, scenario=scenario)
        for battery in batteries
        for scenario in scenarios
    ]
    worker_count = resolve_max_workers(max_workers, len(jobs))
    if worker_count == 1:
        rows.extend(
            _run_dispatch_jobs_serial(
                analysis_df, jobs, experiment_name, timestamp, audit_export
            )
        )
    else:
        rows.extend(
            _run_dispatch_jobs_parallel(
                analysis_df,
                jobs,
                experiment_name,
                timestamp,
                worker_count,
                audit_export,
            )
        )

    results_df = pd.DataFrame(rows).sort_values(
        ["capacity_kwh", "method", "scenario"], ignore_index=True
    )
    ordered_columns = METADATA_COLUMNS + [
        column for column in results_df.columns if column not in METADATA_COLUMNS
    ]
    return results_df[ordered_columns]


def resolve_max_workers(max_workers: int | None, job_count: int) -> int:
    """Return a valid worker count bounded by the number of jobs."""
    if job_count <= 0:
        return 1
    if max_workers is not None and max_workers <= 0:
        raise ValueError("max_workers must be greater than zero.")
    requested_workers = (
        DEFAULT_MAX_PARALLEL_WORKERS if max_workers is None else max_workers
    )
    return min(requested_workers, job_count)


def _run_dispatch_jobs_serial(
    analysis_df: pd.DataFrame,
    jobs: list[_DispatchJob],
    experiment_name: str,
    run_timestamp: str,
    audit_export: AuditExportConfig | None,
) -> list[dict]:
    rows: list[dict] = []
    for job in jobs:
        print(f"Running capacity {job.battery.capacity_kwh:g} kWh, {job.scenario.name}...")
        job_rows = _run_dispatch_job(
            analysis_df, job, experiment_name, run_timestamp, audit_export
        )
        rows.extend(job_rows)
        _print_job_completion(job, job_rows)
    return rows


def _run_dispatch_jobs_parallel(
    analysis_df: pd.DataFrame,
    jobs: list[_DispatchJob],
    experiment_name: str,
    run_timestamp: str,
    max_workers: int,
    audit_export: AuditExportConfig | None,
) -> list[dict]:
    print(f"Running {len(jobs)} capacity-scenario jobs with {max_workers} workers...")
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_job = {
            executor.submit(
                _run_dispatch_job,
                analysis_df,
                job,
                experiment_name,
                run_timestamp,
                audit_export,
            ): job
            for job in jobs
        }
        for future in as_completed(future_to_job):
            job = future_to_job[future]
            job_rows = future.result()
            rows.extend(job_rows)
            _print_job_completion(job, job_rows)
    return rows


def _run_dispatch_job(
    analysis_df: pd.DataFrame,
    job: _DispatchJob,
    experiment_name: str,
    run_timestamp: str,
    audit_export: AuditExportConfig | None,
) -> list[dict]:
    battery, scenario = job.battery, job.scenario
    rows: list[dict] = []

    start_time = perf_counter()
    heuristic_dispatch_df = run_heuristic_dispatch(analysis_df, battery, scenario)
    heuristic_metrics = calculate_dispatch_metrics(
        analysis_df, heuristic_dispatch_df, battery, scenario
    )
    rows.append(
        _with_metadata(
            heuristic_metrics,
            "heuristic",
            scenario,
            battery,
            experiment_name,
            run_timestamp,
            perf_counter() - start_time,
        )
    )

    start_time = perf_counter()
    optimized_dispatch_df = run_optimized_dispatch(
        analysis_df,
        battery,
        scenario,
        include_horizon_diagnostics=audit_export is not None,
    )
    optimized_metrics = calculate_dispatch_metrics(
        analysis_df, optimized_dispatch_df, battery, scenario
    )
    optimized_row = _with_metadata(
        optimized_metrics,
        "lp_optimization",
        scenario,
        battery,
        experiment_name,
        run_timestamp,
        perf_counter() - start_time,
    )
    if audit_export is not None:
        audit_df = build_lp_audit_dataframe(
            analysis_df, optimized_dispatch_df, battery, scenario, run_timestamp
        )
        export_path = dispatch_export_path(
            audit_export,
            resolution=str(analysis_df["resolution"].iloc[0]),
            battery=battery,
            scenario=scenario,
        )
        write_audit_parquet_atomically(audit_df, export_path)
        optimized_row["dispatch_file"] = format_export_path(export_path, PROJECT_ROOT)
    rows.append(optimized_row)
    return rows


def _print_job_completion(job: _DispatchJob, rows: list[dict]) -> None:
    elapsed_by_method = {row["method"]: row["elapsed_seconds"] for row in rows}
    print(
        f"Completed capacity {job.battery.capacity_kwh:g} kWh, {job.scenario.name}: "
        f"heuristic {elapsed_by_method['heuristic']:.2f}s, "
        f"lp_optimization {elapsed_by_method['lp_optimization']:.2f}s"
    )


def _baseline_rows(
    analysis_df: pd.DataFrame,
    scenario: ScenarioParameters,
    battery: BatteryParameters,
    experiment_name: str,
    run_timestamp: str,
) -> list[dict]:
    start_time = perf_counter()
    baseline_metrics = calculate_baseline_metrics(analysis_df, scenario)
    elapsed_seconds = perf_counter() - start_time
    fixed_row = _baseline_row(
        baseline_metrics,
        "fixed",
        baseline_metrics["baseline_fixed_grid_import_cost_eur"],
        baseline_metrics["baseline_fixed_net_cost_eur"],
        baseline_metrics["baseline_fixed_net_cost_eur"],
        baseline_metrics["baseline_fixed_effective_cost_eur_per_load_kwh"],
    )
    dynamic_row = _baseline_row(
        baseline_metrics,
        "dynamic",
        baseline_metrics["baseline_dynamic_grid_import_cost_eur"],
        baseline_metrics["baseline_dynamic_net_cost_eur"],
        baseline_metrics["baseline_dynamic_net_cost_eur"],
        baseline_metrics["baseline_dynamic_effective_cost_eur_per_load_kwh"],
    )
    return [
        _with_metadata(
            fixed_row,
            "baseline",
            scenario,
            battery,
            experiment_name,
            run_timestamp,
            elapsed_seconds,
        ),
        _with_metadata(
            dynamic_row,
            "baseline",
            scenario,
            battery,
            experiment_name,
            run_timestamp,
            elapsed_seconds,
        ),
    ]


def _baseline_row(
    baseline_metrics: dict[str, float],
    price_model: str,
    grid_import_cost_eur: float,
    electricity_net_cost_eur: float,
    net_cost_eur: float,
    effective_cost_eur_per_load_kwh: float,
) -> dict:
    return {
        "scenario": "no_bess_baseline",
        "dispatch_strategy": "baseline",
        "price_model": price_model,
        "capacity_kwh": 0,
        "max_charge_power_kw": None,
        "max_discharge_power_kw": None,
        "charge_c_rate": None,
        "discharge_c_rate": None,
        "grid_connection_limit_kw": None,
        "degradation_cost_eur_per_kwh": 0.0,
        "grid_import_cost_eur": grid_import_cost_eur,
        "grid_export_revenue_eur": baseline_metrics["baseline_grid_export_revenue_eur"],
        "electricity_net_cost_eur": electricity_net_cost_eur,
        "battery_degradation_cost_eur": 0.0,
        "net_cost_eur": net_cost_eur,
        "effective_cost_eur_per_load_kwh": effective_cost_eur_per_load_kwh,
        "cost_savings_eur": 0.0,
        "grid_import_kwh": baseline_metrics["baseline_grid_import_kwh"],
        "grid_export_kwh": baseline_metrics["baseline_grid_export_kwh"],
        "battery_charge_throughput_kwh": 0.0,
        "battery_discharge_throughput_kwh": 0.0,
        "approximate_cycles": 0.0,
        "grid_charge_share": 0.0,
        "average_grid_charge_price_eur_per_kwh": None,
        "average_battery_discharge_price_eur_per_kwh": None,
        "grid_charge_arbitrage_spread_eur_per_kwh": None,
        "initial_soc_kwh": None,
        "final_soc_kwh": None,
        "final_usable_soc_kwh": None,
        "soc_change_kwh": None,
        "soc_range_utilization": 0.0,
        "surplus_capture_ratio": 0.0,
        "peak_grid_import_kwh": baseline_metrics["baseline_peak_grid_import_kwh"],
        "peak_grid_import_kw": baseline_metrics["baseline_peak_grid_import_kw"],
        "self_consumption_ratio": baseline_metrics["baseline_self_consumption_ratio"],
        "self_consumption_improvement": 0.0,
        "fixed_import_price_eur_per_kwh": baseline_metrics[
            "fixed_import_price_eur_per_kwh"
        ],
    }


def _with_metadata(
    row: dict,
    method: str,
    scenario: ScenarioParameters,
    battery: BatteryParameters,
    experiment_name: str,
    run_timestamp: str,
    elapsed_seconds: float,
) -> dict:
    enriched_row = dict(row)
    enriched_row.update(
        {
            "experiment_name": experiment_name,
            "run_timestamp": run_timestamp,
            "elapsed_seconds": elapsed_seconds,
            "method": method,
            "import_markup_eur_per_kwh": scenario.import_markup_eur_per_kwh,
            "export_price_eur_per_kwh": scenario.export_price_eur_per_kwh,
            "horizon_hours": scenario.horizon_hours,
            "terminal_value_window_hours": scenario.terminal_value_window_hours,
            "terminal_value_applied": (
                method == "lp_optimization"
                and scenario.terminal_value_window_hours is not None
            ),
            "dispatch_file": None,
            "low_price_quantile": scenario.low_price_quantile,
            "high_price_quantile": scenario.high_price_quantile,
            "eta_charge": battery.eta_charge,
            "eta_discharge": battery.eta_discharge,
            "min_soc_fraction": battery.min_soc_fraction,
            "max_soc_fraction": battery.max_soc_fraction,
        }
    )
    return enriched_row
