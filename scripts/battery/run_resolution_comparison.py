"""Compare the existing BESS experiment at hourly and 15-minute resolution.

The default seven-day window is intentionally short.  It is an integration and
runtime check, not a full-year experiment; use ``--days 365`` explicitly when
the model is ready for the annual comparison.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import math
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.battery.run_experiments import run_capacity_sensitivity
from src.battery.data import ANALYSIS_VIEW_NAMES, load_smart_company_analysis

DEFAULT_CAPACITIES_KWH = [1000.0]
DEFAULT_DAYS = 7
DEFAULT_RESULTS_PATH = (
    PROJECT_ROOT / "results" / "battery" / "time_resolution_comparison.csv"
)


def run_bess_resolution_comparison(
    analysis_by_resolution: dict[str, pd.DataFrame],
    capacities_kwh: list[float] | None = None,
    run_timestamp: str | None = None,
    max_workers: int | None = None,
    terminal_value_window_hours: float | None = 4.0,
    dispatch_dir: Path | None = None,
) -> pd.DataFrame:
    """Run the standard baseline, heuristic, and LP scenarios per resolution."""
    timestamp = run_timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    capacities = DEFAULT_CAPACITIES_KWH if capacities_kwh is None else capacities_kwh
    if not capacities or any(
        not math.isfinite(capacity_kwh) or capacity_kwh <= 0
        for capacity_kwh in capacities
    ):
        raise ValueError("capacities_kwh must contain finite positive values.")

    result_frames = []
    for resolution_index, (resolution, analysis_df) in enumerate(
        analysis_by_resolution.items()
    ):
        if resolution not in ANALYSIS_VIEW_NAMES:
            raise ValueError(f"Unsupported resolution: {resolution!r}.")
        if analysis_df.empty:
            raise ValueError(f"Analysis data for {resolution!r} is empty.")
        actual_resolutions = set(analysis_df["resolution"].dropna().unique())
        if actual_resolutions != {resolution}:
            raise ValueError(
                f"Analysis data for {resolution!r} contains unexpected resolutions: "
                f"{sorted(actual_resolutions)}."
            )
        timestep_values = pd.to_numeric(analysis_df["timestep_hours"], errors="raise")
        if timestep_values.nunique() != 1:
            raise ValueError("Each comparison input must have one timestep_hours value.")
        timestep_hours = float(timestep_values.iloc[0])
        timestamps = pd.to_datetime(
            analysis_df["observation_timestamp"],
            utc=True,
            errors="raise",
        )
        analysis_start_utc = timestamps.min().isoformat()
        analysis_end_utc_exclusive = (
            timestamps.max() + pd.to_timedelta(timestep_hours, unit="h")
        ).isoformat()

        result_df = run_capacity_sensitivity(
            analysis_df=analysis_df,
            capacities_kwh=capacities,
            run_timestamp=timestamp,
            max_workers=max_workers,
            terminal_value_window_hours=terminal_value_window_hours,
            dispatch_dir=dispatch_dir,
            prepare_dispatch_dir=resolution_index == 0,
        ).copy()
        result_df["experiment_name"] = "time_resolution_comparison"
        result_df.insert(1, "resolution", resolution)
        result_df.insert(2, "timestep_hours", timestep_hours)
        result_df.insert(3, "analysis_start_utc", analysis_start_utc)
        result_df.insert(4, "analysis_end_utc_exclusive", analysis_end_utc_exclusive)
        result_df.insert(5, "simulation_rows", len(analysis_df))
        result_frames.append(result_df)

    if not result_frames:
        raise ValueError("At least one resolution must be provided.")

    return pd.concat(result_frames, ignore_index=True).sort_values(
        ["resolution", "capacity_kwh", "method", "scenario", "price_model"],
        ignore_index=True,
    )


def select_time_window(
    analysis_df: pd.DataFrame,
    start: str | None,
    end: str | None,
    days: int | None,
) -> pd.DataFrame:
    """Return a common half-open UTC window without changing input data."""
    if days is not None and days <= 0:
        raise ValueError("days must be greater than zero when configured.")

    timestamps = pd.to_datetime(analysis_df["observation_timestamp"], utc=True)
    window_start = pd.to_datetime(start, utc=True) if start else timestamps.min()
    if end:
        window_end = pd.to_datetime(end, utc=True)
    elif days is not None:
        window_end = window_start + pd.Timedelta(days=days)
    else:
        window_end = timestamps.max() + pd.Timedelta(microseconds=1)
    if window_end <= window_start:
        raise ValueError("end must be after start.")

    selected = analysis_df.loc[
        (timestamps >= window_start) & (timestamps < window_end)
    ].copy()
    if selected.empty:
        raise ValueError("The selected time window contains no analysis data.")
    return selected.reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resolutions",
        nargs="+",
        choices=sorted(ANALYSIS_VIEW_NAMES),
        default=["hour", "15min"],
    )
    parser.add_argument(
        "--capacities-kwh",
        nargs="+",
        type=float,
        default=DEFAULT_CAPACITIES_KWH,
        help="Battery capacities to compare in kWh (default: 1000).",
    )
    parser.add_argument("--start", help="UTC start timestamp, inclusive.")
    parser.add_argument("--end", help="UTC end timestamp, exclusive.")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help="Length from start; ignored when --end is supplied (default: 7).",
    )
    parser.add_argument("--max-workers", type=int)
    terminal_value_group = parser.add_mutually_exclusive_group()
    terminal_value_group.add_argument(
        "--terminal-value-window-hours",
        type=float,
        default=4.0,
        help="Terminal-value price window in real hours (default: 4).",
    )
    terminal_value_group.add_argument(
        "--no-terminal-value",
        action="store_true",
        help="Disable terminal SOC valuation for an A/B comparison.",
    )
    parser.add_argument(
        "--dispatch-dir",
        type=Path,
        help="Empty directory for one LP audit Parquet file per scenario.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    analysis_by_resolution = {}
    for resolution in args.resolutions:
        print(f"Loading {resolution} analysis data...")
        analysis_df = load_smart_company_analysis(resolution=resolution)
        selected_df = select_time_window(analysis_df, args.start, args.end, args.days)
        print(f"Selected {len(selected_df):,} {resolution} rows.")
        analysis_by_resolution[resolution] = selected_df

    terminal_value_window_hours = (
        None if args.no_terminal_value else args.terminal_value_window_hours
    )
    results_df = run_bess_resolution_comparison(
        analysis_by_resolution=analysis_by_resolution,
        capacities_kwh=args.capacities_kwh,
        max_workers=args.max_workers,
        terminal_value_window_hours=terminal_value_window_hours,
        dispatch_dir=args.dispatch_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(args.output, index=False)
    print(f"Saved {len(results_df):,} result rows to {args.output}.")


if __name__ == "__main__":
    main()
