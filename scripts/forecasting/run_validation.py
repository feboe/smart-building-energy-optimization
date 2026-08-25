"""Reproduce the fixed load-forecast validation and save summary metrics."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.forecasting.config import (
    ForecastConfig,
    ForecastExperimentConfig,
    ForecastSplit,
    HGBConfig,
)
from src.forecasting.data import (
    load_smart_company_forecasting,
    prepare_forecasting_data,
)
from src.forecasting.evaluation import ForecastEvaluationResult, run_forecast_evaluation
from src.forecasting.models import (
    DailyNaiveForecaster,
    HistGradientBoostingLoadForecaster,
    WeeklyNaiveForecaster,
)

DEFAULT_OUTPUT_DIRECTORY = PROJECT_ROOT / "results" / "forecasting"
TRAINING_SPLIT = ForecastSplit(
    name="validation_training",
    start=pd.Timestamp("2019-06-28T22:00:00Z"),
    end=pd.Timestamp("2020-10-01T00:00:00Z"),
)
VALIDATION_SPLIT = ForecastSplit(
    name="validation_2020_q4",
    start=pd.Timestamp("2020-10-01T00:00:00Z"),
    end=pd.Timestamp("2021-01-01T00:00:00Z"),
)


def main() -> None:
    """Run the frozen Q4 2020 comparison and write reproducible artifacts."""
    args = _parse_args()
    run_start = perf_counter()
    forecast_config = ForecastConfig(horizon_hours=24)

    print("Loading and preparing forecasting data...")
    data = prepare_forecasting_data(
        load_smart_company_forecasting(recreate_views=False),
        forecast_config,
    )
    results = run_validation_experiments(data, forecast_config)
    metrics = pd.concat(
        [result.metrics for result in results.values()],
        ignore_index=True,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.output_dir / "validation_metrics.csv"
    metrics.to_csv(metrics_path, index=False)

    print("\nValidation results")
    _print_overall_metrics(metrics)
    print(f"\nSaved metrics to {metrics_path}.")

    if args.save_forecasts:
        forecasts = pd.concat(
            [result.evaluated_forecasts for result in results.values()],
            ignore_index=True,
        )
        forecasts_path = args.output_dir / "validation_forecasts.csv"
        forecasts.to_csv(forecasts_path, index=False)
        print(f"Saved {len(forecasts):,} evaluated rows to {forecasts_path}.")

    print(f"Completed in {perf_counter() - run_start:.1f} seconds.")


def run_validation_experiments(
    prepared_data: pd.DataFrame,
    forecast_config: ForecastConfig | None = None,
) -> dict[str, ForecastEvaluationResult]:
    """Evaluate the fixed baselines and default HGB model on Q4 2020."""
    config = forecast_config or ForecastConfig()
    models = {
        "daily_naive_validation": DailyNaiveForecaster(),
        "weekly_naive_validation": WeeklyNaiveForecaster(),
        "hgb_default_validation": HistGradientBoostingLoadForecaster(HGBConfig()),
    }
    results: dict[str, ForecastEvaluationResult] = {}
    for experiment_name, model in models.items():
        print(f"Running {experiment_name}...")
        results[experiment_name] = run_forecast_evaluation(
            model=model,
            prepared_data=prepared_data,
            experiment_config=ForecastExperimentConfig(
                name=experiment_name,
                training_split=TRAINING_SPLIT,
                evaluation_split=VALIDATION_SPLIT,
            ),
            forecast_config=config,
        )
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the fixed Q4 2020 load-forecast validation.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help=f"Artifact directory (default: {DEFAULT_OUTPUT_DIRECTORY}).",
    )
    parser.add_argument(
        "--save-forecasts",
        action="store_true",
        help="Also save the large row-level forecast and error table.",
    )
    return parser.parse_args()


def _print_overall_metrics(metrics: pd.DataFrame) -> None:
    overall = metrics.loc[
        metrics["metric_scope"].eq("overall"),
        [
            "experiment_name",
            "sample_count",
            "mae_kwh",
            "rmse_kwh",
            "bias_kwh",
            "wape_percent",
        ],
    ].sort_values("mae_kwh")
    print(overall.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
