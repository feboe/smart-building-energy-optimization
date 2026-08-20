"""Configuration shared by load forecasting modules."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ForecastSplit:
    """A named UTC time interval with an inclusive start and exclusive end."""

    name: str
    start: pd.Timestamp
    end: pd.Timestamp

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Forecast split name must not be empty.")
        if self.start.tz is None or str(self.start.tz) != "UTC":
            raise ValueError("Forecast split start must use the UTC timezone.")
        if self.end.tz is None or str(self.end.tz) != "UTC":
            raise ValueError("Forecast split end must use the UTC timezone.")
        if self.start >= self.end:
            raise ValueError("Forecast split start must be before its end.")


@dataclass(frozen=True)
class ForecastExperimentConfig:
    """Name the chronological splits used by one forecast evaluation."""

    name: str
    training_split: ForecastSplit
    evaluation_split: ForecastSplit

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Forecast experiment name must not be empty.")
        # Overlapping labels would let training observe the evaluation period.
        if self.training_split.end > self.evaluation_split.start:
            raise ValueError(
                "Forecast training split must end before or when the evaluation "
                "split starts."
            )


@dataclass(frozen=True)
class ForecastConfig:
    """Describe the time-series target and forecasting horizon."""

    observation_timestamp_column: str = "observation_timestamp"
    local_timestamp_column: str = "local_timestamp"
    target_column: str = "gross_load_kwh"
    raw_target_column: str = "gross_load_raw_kwh"
    target_quality_column: str = "gross_load_quality_issue"
    imputation_flag_column: str = "gross_load_was_imputed"
    holiday_country: str = "DE"
    holiday_subdivision: str = "HE"
    frequency: str = "h"
    horizon_hours: int = 24

    def __post_init__(self) -> None:
        if self.horizon_hours <= 0:
            raise ValueError("horizon_hours must be positive.")
        if not self.frequency:
            raise ValueError("frequency must not be empty.")
        if not self.holiday_country:
            raise ValueError("holiday_country must not be empty.")
        if not self.holiday_subdivision:
            raise ValueError("holiday_subdivision must not be empty.")


@dataclass(frozen=True)
class HGBConfig:
    """Hyperparameters for the histogram gradient boosting forecaster."""

    learning_rate: float = 0.05
    max_iter: int = 300
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 20
    l2_regularization: float = 1.0
    early_stopping: bool = False
    random_state: int = 42

    def __post_init__(self) -> None:
        if self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive.")
        if self.max_iter <= 0:
            raise ValueError("max_iter must be positive.")
        if self.max_leaf_nodes <= 1:
            raise ValueError("max_leaf_nodes must be greater than one.")
        if self.min_samples_leaf <= 0:
            raise ValueError("min_samples_leaf must be positive.")
        if self.l2_regularization < 0:
            raise ValueError("l2_regularization must not be negative.")
