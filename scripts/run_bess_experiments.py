"""Run BESS capacity sensitivity experiments and save summary metrics."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from time import perf_counter

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.battery.data import load_smart_company_analysis
from src.battery.heuristic import run_heuristic_dispatch
from src.battery.metrics import calculate_baseline_metrics, calculate_dispatch_metrics
from src.battery.optimization import run_optimized_dispatch
from src.battery.parameters import BatteryParameters, ScenarioParameters
from src.battery.scenarios import (
    make_battery_parameters,
    make_dynamic_surplus_and_grid_charging_scenario,
    make_dynamic_surplus_only_scenario,
    make_fixed_surplus_only_scenario,
)

EXPERIMENT_NAME = "capacity_sensitivity"
CAPACITIES_KWH = [250, 500, 1000, 2000]
MAX_PARALLEL_WORKERS = min(4, os.cpu_count() or 1)
RESULTS_PATH = PROJECT_ROOT / "results" / "bess_experiment_results.csv"

C_RATE = 0.5
MIN_SOC_FRACTION = 0.10
MAX_SOC_FRACTION = 1.00
ETA_CHARGE = 0.95
ETA_DISCHARGE = 0.95
DEGRADATION_COST_EUR_PER_KWH = 0.03

IMPORT_MARKUP_EUR_PER_KWH = 0.115
EXPORT_PRICE_EUR_PER_KWH = 0.08
HORIZON_HOURS = 24
GRID_CONNECTION_LIMIT_KW = 500.0
SURPLUS_RESERVE_FRACTION = 1.0

METADATA_COLUMNS = [
    "experiment_name",
    "run_timestamp",
    "elapsed_seconds",
    "method",
    "scenario",
    "price_model",
    "capacity_kwh",
    "import_markup_eur_per_kwh",
    "export_price_eur_per_kwh",
    "horizon_hours",
    "low_price_quantile",
    "high_price_quantile",
    "eta_charge",
    "eta_discharge",
    "min_soc_fraction",
    "max_soc_fraction",
]


@dataclass(frozen=True)
class _DispatchJob:
    capacity_kwh: float
    scenario: ScenarioParameters


def main() -> None:
    run_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    script_start_time = perf_counter()
    print("Loading smart-company analysis data...")
    analysis_df = load_smart_company_analysis()
    analysis_df = analysis_df.head(500)  # Limit rows for faster experimentation
    print(f"Loaded {len(analysis_df):,} rows.")

    results_df = run_capacity_sensitivity(
        analysis_df=analysis_df,
        capacities_kwh=CAPACITIES_KWH,
        run_timestamp=run_timestamp,
    )

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(RESULTS_PATH, index=False)
    print(f"Saved {len(results_df):,} result rows to {RESULTS_PATH}.")
    print(f"Total elapsed time: {perf_counter() - script_start_time:.2f} seconds.")


def run_capacity_sensitivity(
    analysis_df: pd.DataFrame,
    capacities_kwh: list[float] | None = None,
    run_timestamp: str | None = None,
    max_workers: int | None = None,
) -> pd.DataFrame:
    """Run baseline, heuristic, and LP experiments for the configured capacities."""
    capacities = CAPACITIES_KWH if capacities_kwh is None else capacities_kwh
    timestamp = run_timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")

    fixed_scenario = make_fixed_surplus_only_scenario(
        export_price_eur_per_kwh=EXPORT_PRICE_EUR_PER_KWH,
        import_markup_eur_per_kwh=IMPORT_MARKUP_EUR_PER_KWH,
        horizon_hours=HORIZON_HOURS,
    )

    rows = _baseline_rows(
        analysis_df=analysis_df,
        scenario=fixed_scenario,
        run_timestamp=timestamp,
    )

    jobs = _dispatch_jobs(capacities)
    worker_count = _resolve_max_workers(max_workers, len(jobs))
    if jobs and worker_count == 1:
        rows.extend(_run_dispatch_jobs_serial(analysis_df, jobs, timestamp))
    elif jobs:
        rows.extend(
            _run_dispatch_jobs_parallel(
                analysis_df=analysis_df,
                jobs=jobs,
                run_timestamp=timestamp,
                max_workers=worker_count,
            )
        )

    results_df = pd.DataFrame(rows)
    results_df = results_df.sort_values(
        ["capacity_kwh", "method", "scenario"],
        ignore_index=True,
    )
    ordered_columns = METADATA_COLUMNS + [
        column for column in results_df.columns if column not in METADATA_COLUMNS
    ]
    return results_df[ordered_columns]


def _dispatch_jobs(capacities_kwh: list[float]) -> list[_DispatchJob]:
    return [
        _DispatchJob(capacity_kwh=capacity_kwh, scenario=scenario)
        for capacity_kwh in capacities_kwh
        for scenario in _make_scenarios()
    ]


def _resolve_max_workers(max_workers: int | None, job_count: int) -> int:
    if job_count <= 0:
        return 1
    if max_workers is None:
        resolved_workers = MAX_PARALLEL_WORKERS
    else:
        if max_workers <= 0:
            raise ValueError("max_workers must be greater than zero.")
        resolved_workers = max_workers
    return min(resolved_workers, job_count)


def _run_dispatch_jobs_serial(
    analysis_df: pd.DataFrame,
    jobs: list[_DispatchJob],
    run_timestamp: str,
) -> list[dict]:
    rows = []
    for job in jobs:
        print(f"Running capacity {job.capacity_kwh:g} kWh, {job.scenario.name}...")
        job_rows = _run_dispatch_job(
            analysis_df=analysis_df,
            job=job,
            run_timestamp=run_timestamp,
        )
        rows.extend(job_rows)
        _print_job_completion(job, job_rows)
    return rows


def _run_dispatch_jobs_parallel(
    analysis_df: pd.DataFrame,
    jobs: list[_DispatchJob],
    run_timestamp: str,
    max_workers: int,
) -> list[dict]:
    print(f"Running {len(jobs)} capacity-scenario jobs with {max_workers} workers...")
    rows = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_job = {
            executor.submit(
                _run_dispatch_job,
                analysis_df=analysis_df,
                job=job,
                run_timestamp=run_timestamp,
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
    run_timestamp: str,
) -> list[dict]:
    battery = _make_battery(job.capacity_kwh)
    scenario = job.scenario
    rows = []

    start_time = perf_counter()
    heuristic_dispatch_df = run_heuristic_dispatch(
        analysis_df=analysis_df,
        battery=battery,
        scenario=scenario,
    )
    heuristic_metrics = calculate_dispatch_metrics(
        analysis_df=analysis_df,
        dispatch_df=heuristic_dispatch_df,
        battery=battery,
        scenario=scenario,
    )
    rows.append(
        _with_metadata(
            row=heuristic_metrics,
            method="heuristic",
            scenario=scenario,
            run_timestamp=run_timestamp,
            elapsed_seconds=perf_counter() - start_time,
        )
    )

    start_time = perf_counter()
    optimized_dispatch_df = run_optimized_dispatch(
        analysis_df=analysis_df,
        battery=battery,
        scenario=scenario,
    )
    optimized_metrics = calculate_dispatch_metrics(
        analysis_df=analysis_df,
        dispatch_df=optimized_dispatch_df,
        battery=battery,
        scenario=scenario,
    )
    rows.append(
        _with_metadata(
            row=optimized_metrics,
            method="lp_optimization",
            scenario=scenario,
            run_timestamp=run_timestamp,
            elapsed_seconds=perf_counter() - start_time,
        )
    )
    return rows


def _print_job_completion(job: _DispatchJob, rows: list[dict]) -> None:
    elapsed_by_method = {row["method"]: row["elapsed_seconds"] for row in rows}
    print(
        f"Completed capacity {job.capacity_kwh:g} kWh, {job.scenario.name}: "
        f"heuristic {elapsed_by_method['heuristic']:.2f}s, "
        f"lp_optimization {elapsed_by_method['lp_optimization']:.2f}s"
    )


def _make_battery(capacity_kwh: float) -> BatteryParameters:
    return make_battery_parameters(
        capacity_kwh=capacity_kwh,
        c_rate=C_RATE,
        min_soc_fraction=MIN_SOC_FRACTION,
        max_soc_fraction=MAX_SOC_FRACTION,
        eta_charge=ETA_CHARGE,
        eta_discharge=ETA_DISCHARGE,
        degradation_cost_eur_per_kwh=DEGRADATION_COST_EUR_PER_KWH,
    )


def _make_scenarios() -> list[ScenarioParameters]:
    return [
        make_fixed_surplus_only_scenario(
            export_price_eur_per_kwh=EXPORT_PRICE_EUR_PER_KWH,
            import_markup_eur_per_kwh=IMPORT_MARKUP_EUR_PER_KWH,
            horizon_hours=HORIZON_HOURS,
        ),
        make_dynamic_surplus_only_scenario(
            export_price_eur_per_kwh=EXPORT_PRICE_EUR_PER_KWH,
            import_markup_eur_per_kwh=IMPORT_MARKUP_EUR_PER_KWH,
            horizon_hours=HORIZON_HOURS,
        ),
        make_dynamic_surplus_and_grid_charging_scenario(
            export_price_eur_per_kwh=EXPORT_PRICE_EUR_PER_KWH,
            import_markup_eur_per_kwh=IMPORT_MARKUP_EUR_PER_KWH,
            horizon_hours=HORIZON_HOURS,
            surplus_reserve_fraction=SURPLUS_RESERVE_FRACTION,
            grid_connection_limit_kw=GRID_CONNECTION_LIMIT_KW,
        ),
    ]


def _baseline_rows(
    analysis_df: pd.DataFrame,
    scenario: ScenarioParameters,
    run_timestamp: str,
) -> list[dict]:
    start_time = perf_counter()
    baseline_metrics = calculate_baseline_metrics(
        analysis_df=analysis_df,
        scenario=scenario,
    )
    elapsed_seconds = perf_counter() - start_time
    fixed_row = _baseline_row(
        baseline_metrics=baseline_metrics,
        price_model="fixed",
        grid_import_cost_eur=baseline_metrics["baseline_fixed_grid_import_cost_eur"],
        electricity_net_cost_eur=baseline_metrics["baseline_fixed_net_cost_eur"],
        net_cost_eur=baseline_metrics["baseline_fixed_net_cost_eur"],
        effective_cost_eur_per_load_kwh=baseline_metrics[
            "baseline_fixed_effective_cost_eur_per_load_kwh"
        ],
    )
    dynamic_row = _baseline_row(
        baseline_metrics=baseline_metrics,
        price_model="dynamic",
        grid_import_cost_eur=baseline_metrics["baseline_dynamic_grid_import_cost_eur"],
        electricity_net_cost_eur=baseline_metrics["baseline_dynamic_net_cost_eur"],
        net_cost_eur=baseline_metrics["baseline_dynamic_net_cost_eur"],
        effective_cost_eur_per_load_kwh=baseline_metrics[
            "baseline_dynamic_effective_cost_eur_per_load_kwh"
        ],
    )
    return [
        _with_metadata(
            fixed_row,
            "baseline",
            scenario,
            run_timestamp,
            elapsed_seconds=elapsed_seconds,
        ),
        _with_metadata(
            dynamic_row,
            "baseline",
            scenario,
            run_timestamp,
            elapsed_seconds=elapsed_seconds,
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
        "c_rate": None,
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
        "soc_range_utilization": 0.0,
        "surplus_capture_ratio": 0.0,
        "peak_grid_import_kwh": baseline_metrics["baseline_peak_grid_import_kwh"],
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
    run_timestamp: str,
    elapsed_seconds: float,
) -> dict:
    enriched_row = dict(row)
    enriched_row.update(
        {
            "experiment_name": EXPERIMENT_NAME,
            "run_timestamp": run_timestamp,
            "elapsed_seconds": elapsed_seconds,
            "method": method,
            "import_markup_eur_per_kwh": scenario.import_markup_eur_per_kwh,
            "export_price_eur_per_kwh": scenario.export_price_eur_per_kwh,
            "horizon_hours": scenario.horizon_hours,
            "low_price_quantile": scenario.low_price_quantile,
            "high_price_quantile": scenario.high_price_quantile,
            "eta_charge": ETA_CHARGE,
            "eta_discharge": ETA_DISCHARGE,
            "min_soc_fraction": MIN_SOC_FRACTION,
            "max_soc_fraction": MAX_SOC_FRACTION,
        }
    )
    return enriched_row


if __name__ == "__main__":
    main()
