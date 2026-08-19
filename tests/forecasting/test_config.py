"""Tests for forecasting configuration."""

import pandas as pd
import pytest

from src.forecasting.config import (
    ForecastConfig,
    ForecastExperimentConfig,
    ForecastSplit,
    HGBConfig,
)


def test_forecast_config_has_load_forecasting_defaults() -> None:
    config = ForecastConfig()

    assert config.target_column == "gross_load_kwh"
    assert config.holiday_country == "DE"
    assert config.holiday_subdivision == "HE"
    assert config.frequency == "h"
    assert config.horizon_hours == 24


def test_forecast_config_rejects_nonpositive_horizon() -> None:
    with pytest.raises(ValueError, match="horizon_hours"):
        ForecastConfig(horizon_hours=0)


@pytest.mark.parametrize(
    ("option", "value"),
    [("holiday_country", ""), ("holiday_subdivision", "")],
)
def test_forecast_config_rejects_empty_holiday_configuration(
    option: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match=option):
        ForecastConfig(**{option: value})


def test_hgb_config_has_reproducible_defaults() -> None:
    config = HGBConfig()

    assert config.learning_rate == 0.05
    assert config.max_iter == 300
    assert config.random_state == 42


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("learning_rate", 0),
        ("max_iter", 0),
        ("max_leaf_nodes", 1),
        ("min_samples_leaf", 0),
        ("l2_regularization", -1),
    ],
)
def test_hgb_config_rejects_invalid_hyperparameters(
    option: str,
    value: float,
) -> None:
    with pytest.raises(ValueError, match=option):
        HGBConfig(**{option: value})


def test_forecast_experiment_config_groups_named_splits() -> None:
    training_split = ForecastSplit(
        "training",
        pd.Timestamp("2020-01-01T00:00:00Z"),
        pd.Timestamp("2020-10-01T00:00:00Z"),
    )
    evaluation_split = ForecastSplit(
        "validation",
        pd.Timestamp("2020-10-01T00:00:00Z"),
        pd.Timestamp("2021-01-01T00:00:00Z"),
    )

    experiment = ForecastExperimentConfig(
        name="hgb_validation",
        training_split=training_split,
        evaluation_split=evaluation_split,
    )

    assert experiment.training_split is training_split
    assert experiment.evaluation_split is evaluation_split


def test_forecast_experiment_config_rejects_overlapping_splits() -> None:
    training_split = ForecastSplit(
        "training",
        pd.Timestamp("2020-01-01T00:00:00Z"),
        pd.Timestamp("2020-10-02T00:00:00Z"),
    )
    evaluation_split = ForecastSplit(
        "validation",
        pd.Timestamp("2020-10-01T00:00:00Z"),
        pd.Timestamp("2021-01-01T00:00:00Z"),
    )

    with pytest.raises(ValueError, match="training split must end"):
        ForecastExperimentConfig(
            name="leaky_evaluation",
            training_split=training_split,
            evaluation_split=evaluation_split,
        )
