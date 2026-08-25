"""Run the frozen load forecasters on the final 2021 test period."""

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
    name="final_training",
    start=pd.Timestamp("2019-06-28T22:00:00Z"),
    end=pd.Timestamp("2021-01-01T00:00:00Z"),
)
TEST_SPLIT = ForecastSplit(
    name="final_test_2021",
    start=pd.Timestamp("2021-01-01T00:00:00Z"),
    end=pd.Timestamp("2022-01-01T00:00:00Z"),
)


def main() -> None:
    """Fit the frozen models through 2020 and evaluate them once on 2021."""
    args = _parse_args()
    run_start = perf_counter()
    forecast_config = ForecastConfig(horizon_hours=24)

    print("Loading and preparing forecasting data...")
    data = prepare_forecasting_data(
        load_smart_company_forecasting(recreate_views=False),
        forecast_config,
    )
    results = run_final_test_experiments(data, forecast_config)
    evaluated_forecasts = pd.concat(
        [result.evaluated_forecasts for result in results.values()],
        ignore_index=True,
    )
    metrics = pd.concat(
        [result.metrics for result in results.values()],
        ignore_index=True,
    )
    diagnostic_forecasts = _add_local_time_columns(
        evaluated_forecasts,
        data,
        forecast_config,
    )
    monthly_metrics = summarize_error_slices(
        diagnostic_forecasts,
        ["experiment_name", "model_name", "target_local_month"],
    )
    hourly_metrics = summarize_error_slices(
        diagnostic_forecasts,
        ["experiment_name", "model_name", "target_local_hour"],
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "final_test_metrics.csv": metrics,
        "final_test_monthly_metrics.csv": monthly_metrics,
        "final_test_hourly_metrics.csv": hourly_metrics,
    }
    for filename, frame in artifacts.items():
        path = args.output_dir / filename
        frame.to_csv(path, index=False)
        print(f"Saved {len(frame):,} rows to {path}.")

    print("\nFinal 2021 test results")
    overall = _overall_metrics(metrics)
    print(overall.round(2).to_string(index=False))
    print("\nHGB MAE improvement over baselines")
    print(_baseline_improvements(overall).round(2).to_string(index=False))

    if args.save_forecasts:
        forecasts_path = args.output_dir / "final_test_forecasts.csv"
        evaluated_forecasts.to_csv(forecasts_path, index=False)
        print(
            f"Saved {len(evaluated_forecasts):,} evaluated rows to "
            f"{forecasts_path}."
        )

    print(f"Completed in {perf_counter() - run_start:.1f} seconds.")


def run_final_test_experiments(
    prepared_data: pd.DataFrame,
    forecast_config: ForecastConfig | None = None,
) -> dict[str, ForecastEvaluationResult]:
    """Fit the fixed models on pre-2021 labels and evaluate on the final test."""
    config = forecast_config or ForecastConfig()
    models = {
        "daily_naive_final_test_2021": DailyNaiveForecaster(),
        "weekly_naive_final_test_2021": WeeklyNaiveForecaster(),
        "hgb_default_final_test_2021": HistGradientBoostingLoadForecaster(HGBConfig()),
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
                evaluation_split=TEST_SPLIT,
            ),
            forecast_config=config,
        )
    return results


def summarize_error_slices(
    evaluated_forecasts: pd.DataFrame,
    group_columns: list[str],
) -> pd.DataFrame:
    """Calculate compact MAE, bias, and WAPE diagnostics by requested slices."""
    required_columns = {
        *group_columns,
        "actual_kwh",
        "error_kwh",
        "absolute_error_kwh",
    }
    missing_columns = sorted(required_columns - set(evaluated_forecasts.columns))
    if missing_columns:
        raise ValueError(
            f"Evaluated forecasts are missing diagnostic columns: {missing_columns}"
        )
    if evaluated_forecasts.empty:
        raise ValueError("Evaluated forecasts are empty.")

    rows: list[dict[str, object]] = []
    for group_key, group in evaluated_forecasts.groupby(group_columns, sort=True):
        keys = group_key if isinstance(group_key, tuple) else (group_key,)
        actual_energy = group["actual_kwh"].abs().sum()
        row = dict(zip(group_columns, keys))
        row.update(
            {
                "sample_count": len(group),
                "mae_kwh": group["absolute_error_kwh"].mean(),
                "bias_kwh": group["error_kwh"].mean(),
                "wape_percent": (
                    float("nan")
                    if actual_energy == 0
                    else 100 * group["absolute_error_kwh"].sum() / actual_energy
                ),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _add_local_time_columns(
    evaluated_forecasts: pd.DataFrame,
    prepared_data: pd.DataFrame,
    forecast_config: ForecastConfig,
) -> pd.DataFrame:
    """Attach target-local month and hour for final-test diagnostics."""
    local_timestamp_column = forecast_config.local_timestamp_column
    diagnostic_forecasts = evaluated_forecasts.merge(
        prepared_data[[local_timestamp_column]],
        how="left",
        left_on="forecast_timestamp",
        right_index=True,
        validate="many_to_one",
    )
    if diagnostic_forecasts[local_timestamp_column].isna().any():
        raise ValueError("Some forecast targets are missing local timestamps.")
    local_timestamps = diagnostic_forecasts[local_timestamp_column]
    diagnostic_forecasts["target_local_month"] = local_timestamps.dt.month
    diagnostic_forecasts["target_local_hour"] = local_timestamps.dt.hour
    return diagnostic_forecasts


def _overall_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    """Return one ordered final-test metric row per experiment."""
    return metrics.loc[
        metrics["metric_scope"].eq("overall"),
        [
            "experiment_name",
            "model_name",
            "sample_count",
            "mae_kwh",
            "rmse_kwh",
            "bias_kwh",
            "wape_percent",
        ],
    ].sort_values("mae_kwh", ignore_index=True)


def _baseline_improvements(overall_metrics: pd.DataFrame) -> pd.DataFrame:
    """Calculate the HGB MAE reduction relative to both seasonal baselines."""
    mae = overall_metrics.set_index("experiment_name")["mae_kwh"]
    hgb_mae = mae["hgb_default_final_test_2021"]
    rows = []
    for baseline_name, label in (
        ("daily_naive_final_test_2021", "Daily Naive"),
        ("weekly_naive_final_test_2021", "Weekly Naive"),
    ):
        baseline_mae = mae[baseline_name]
        rows.append(
            {
                "baseline": label,
                "mae_improvement_percent": 100 * (baseline_mae - hgb_mae) / baseline_mae,
            }
        )
    return pd.DataFrame(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen models on the final 2021 forecast test.",
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


if __name__ == "__main__":
    main()
