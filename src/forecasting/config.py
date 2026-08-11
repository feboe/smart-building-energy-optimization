"""Configuration shared by load forecasting modules."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastConfig:
    """Describe the time-series target and forecasting horizon."""

    observation_timestamp_column: str = "observation_timestamp"
    local_timestamp_column: str = "local_timestamp"
    target_column: str = "gross_load_kwh"
    raw_target_column: str = "gross_load_raw_kwh"
    target_quality_column: str = "gross_load_quality_issue"
    imputation_flag_column: str = "gross_load_was_imputed"
    frequency: str = "h"
    horizon_hours: int = 24

    def __post_init__(self) -> None:
        if self.horizon_hours <= 0:
            raise ValueError("horizon_hours must be positive.")
        if not self.frequency:
            raise ValueError("frequency must not be empty.")
