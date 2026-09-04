"""Run the established hourly BESS capacity-sensitivity experiment."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from time import perf_counter

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.battery.experiment_defaults import (
    TERMINAL_VALUE_WINDOW_HOURS,
    make_standard_batteries,
    make_standard_scenarios,
)
from src.battery.audit import create_audit_export_config
from src.battery.data import load_smart_company_analysis
from src.battery.experiment_runner import (
    DEFAULT_MAX_PARALLEL_WORKERS,
    METADATA_COLUMNS,
    run_bess_experiment,
)


EXPERIMENT_NAME = "capacity_sensitivity"
ANALYSIS_RESOLUTION = "hour"
CAPACITIES_KWH = [250, 500, 1000, 2000]
MAX_PARALLEL_WORKERS = DEFAULT_MAX_PARALLEL_WORKERS
RESULTS_PATH = PROJECT_ROOT / "results" / "battery" / "experiment_results.csv"


def run_capacity_sensitivity(
    analysis_df: pd.DataFrame,
    capacities_kwh: list[float] | None = None,
    run_timestamp: str | None = None,
    max_workers: int | None = None,
    terminal_value_window_hours: float | None = TERMINAL_VALUE_WINDOW_HOURS,
    dispatch_dir: Path | None = None,
) -> pd.DataFrame:
    """Run the standard capacity study using the shared experiment engine."""
    capacities = CAPACITIES_KWH if capacities_kwh is None else capacities_kwh
    batteries = make_standard_batteries(capacities)
    scenarios = make_standard_scenarios(terminal_value_window_hours)
    return run_bess_experiment(
        analysis_df=analysis_df,
        batteries=batteries,
        scenarios=scenarios,
        experiment_name=EXPERIMENT_NAME,
        run_timestamp=run_timestamp,
        max_workers=max_workers,
        audit_export=create_audit_export_config(dispatch_dir),
        baseline_scenario=scenarios[0],
    )


def main() -> None:
    run_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    script_start_time = perf_counter()
    print("Loading smart-company analysis data...")
    analysis_df = load_smart_company_analysis(resolution=ANALYSIS_RESOLUTION)
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


if __name__ == "__main__":
    main()
