"""Chronological dataset splits for load forecasting."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ForecastSplit:
    """A named UTC time interval with an inclusive start and exclusive end."""

    name: str
    start: pd.Timestamp
    end: pd.Timestamp

    def __post_init__(self) -> None:
        if self.start.tz is None or str(self.start.tz) != "UTC":
            raise ValueError("Forecast split start must use the UTC timezone.")
        if self.end.tz is None or str(self.end.tz) != "UTC":
            raise ValueError("Forecast split end must use the UTC timezone.")
        if self.start >= self.end:
            raise ValueError("Forecast split start must be before its end.")


TRAINING_SPLIT = ForecastSplit(
    name="training",
    start=pd.Timestamp("2020-01-01T00:00:00Z"),
    end=pd.Timestamp("2020-10-01T00:00:00Z"),
)
VALIDATION_SPLIT = ForecastSplit(
    name="validation",
    start=pd.Timestamp("2020-10-01T00:00:00Z"),
    end=pd.Timestamp("2021-01-01T00:00:00Z"),
)
TEST_SPLIT = ForecastSplit(
    name="test",
    start=pd.Timestamp("2021-01-01T00:00:00Z"),
    end=pd.Timestamp("2022-01-01T00:00:00Z"),
)
DEFAULT_FORECAST_SPLITS = (TRAINING_SPLIT, VALIDATION_SPLIT, TEST_SPLIT)


def select_forecast_split(
    prepared_data: pd.DataFrame,
    forecast_split: ForecastSplit,
) -> pd.DataFrame:
    """Return rows inside a split's half-open UTC time interval."""
    if not isinstance(prepared_data.index, pd.DatetimeIndex):
        raise ValueError("Prepared data must use a UTC DatetimeIndex.")
    if prepared_data.index.tz is None or str(prepared_data.index.tz) != "UTC":
        raise ValueError("Prepared data index must use the UTC timezone.")

    return prepared_data.loc[
        (prepared_data.index >= forecast_split.start)
        & (prepared_data.index < forecast_split.end)
    ].copy()
