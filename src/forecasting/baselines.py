"""Seasonal-naive load forecasting models."""

from typing import Protocol, Self

import pandas as pd

from src.forecasting.config import ForecastConfig

FORECAST_COLUMNS = [
    "forecast_origin",
    "forecast_timestamp",
    "horizon_hours",
    "model_name",
    "prediction_kwh",
]


class ForecastModel(Protocol):
    """Common interface implemented by baseline and future ML forecasters."""

    model_name: str

    def fit(self, training_data: pd.DataFrame) -> Self:
        """Validate or train the model using data available before evaluation."""

    def predict(
        self,
        prepared_data: pd.DataFrame,
        forecast_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> pd.DataFrame:
        """Return forecasts in the canonical long output format."""


class DailyNaiveForecaster:
    """Forecast each target timestamp with the load observed 24 hours earlier."""

    model_name = "daily_naive"

    def fit(self, training_data: pd.DataFrame) -> Self:
        """Validate the shared input contract; seasonal naive needs no fitting."""
        _validate_prepared_data(training_data, ForecastConfig())
        return self

    def predict(
        self,
        prepared_data: pd.DataFrame,
        forecast_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> pd.DataFrame:
        """Generate one 24-hour forecast for every requested origin."""
        config = forecast_config or ForecastConfig()
        return _seasonal_naive_forecast(
            prepared_data=prepared_data,
            forecast_origins=forecast_origins,
            forecast_config=config,
            model_name=self.model_name,
            seasonal_lag_hours=24,
        )


class WeeklyNaiveForecaster:
    """Forecast each target timestamp with the load observed 168 hours earlier."""

    model_name = "weekly_naive"

    def fit(self, training_data: pd.DataFrame) -> Self:
        """Validate the shared input contract; seasonal naive needs no fitting."""
        _validate_prepared_data(training_data, ForecastConfig())
        return self

    def predict(
        self,
        prepared_data: pd.DataFrame,
        forecast_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> pd.DataFrame:
        """Generate one 24-hour forecast for every requested origin."""
        config = forecast_config or ForecastConfig()
        return _seasonal_naive_forecast(
            prepared_data=prepared_data,
            forecast_origins=forecast_origins,
            forecast_config=config,
            model_name=self.model_name,
            seasonal_lag_hours=168,
        )


def _seasonal_naive_forecast(
    prepared_data: pd.DataFrame,
    forecast_origins: pd.DatetimeIndex,
    forecast_config: ForecastConfig,
    model_name: str,
    seasonal_lag_hours: int,
) -> pd.DataFrame:
    _validate_prepared_data(prepared_data, forecast_config)
    origins = _validate_forecast_origins(forecast_origins, prepared_data.index)

    target_column = forecast_config.target_column
    forecast_rows: list[dict[str, object]] = []
    for origin in origins:
        for horizon_hours in range(1, forecast_config.horizon_hours + 1):
            forecast_timestamp = origin + pd.Timedelta(hours=horizon_hours)
            source_timestamp = forecast_timestamp - pd.Timedelta(hours=seasonal_lag_hours)
            _validate_forecast_timestamps(
                prepared_data.index,
                origin,
                forecast_timestamp,
                source_timestamp,
                seasonal_lag_hours,
            )

            prediction = prepared_data.at[source_timestamp, target_column]
            if pd.isna(prediction):
                raise ValueError(
                    f"{model_name} cannot forecast from {origin.isoformat()}: "
                    f"the source target at {source_timestamp.isoformat()} is missing."
                )

            forecast_rows.append(
                {
                    "forecast_origin": origin,
                    "forecast_timestamp": forecast_timestamp,
                    "horizon_hours": horizon_hours,
                    "model_name": model_name,
                    "prediction_kwh": float(prediction),
                }
            )

    return pd.DataFrame(forecast_rows, columns=FORECAST_COLUMNS)


def _validate_prepared_data(
    prepared_data: pd.DataFrame,
    forecast_config: ForecastConfig,
) -> None:
    if forecast_config.target_column not in prepared_data.columns:
        raise ValueError(
            f"Prepared data is missing target column {forecast_config.target_column!r}."
        )
    if prepared_data.empty:
        raise ValueError("Prepared data is empty.")
    if not isinstance(prepared_data.index, pd.DatetimeIndex):
        raise ValueError("Prepared data must use a UTC DatetimeIndex.")
    if prepared_data.index.tz is None or str(prepared_data.index.tz) != "UTC":
        raise ValueError("Prepared data index must use the UTC timezone.")
    if prepared_data.index.has_duplicates:
        raise ValueError("Prepared data index must not contain duplicate timestamps.")
    if not prepared_data.index.is_monotonic_increasing:
        raise ValueError("Prepared data index must be sorted in ascending order.")

    expected_index = pd.date_range(
        start=prepared_data.index.min(),
        end=prepared_data.index.max(),
        freq=forecast_config.frequency,
        tz="UTC",
    )
    if not prepared_data.index.equals(expected_index):
        raise ValueError(
            "Prepared data index must be continuous at the forecast frequency."
        )


def _validate_forecast_origins(
    forecast_origins: pd.DatetimeIndex,
    data_index: pd.DatetimeIndex,
) -> pd.DatetimeIndex:
    if not isinstance(forecast_origins, pd.DatetimeIndex):
        raise ValueError("forecast_origins must be a UTC DatetimeIndex.")
    if forecast_origins.empty:
        raise ValueError("forecast_origins must not be empty.")
    if forecast_origins.tz is None or str(forecast_origins.tz) != "UTC":
        raise ValueError("forecast_origins must use the UTC timezone.")
    if forecast_origins.has_duplicates:
        raise ValueError("forecast_origins must not contain duplicate timestamps.")
    if not forecast_origins.is_monotonic_increasing:
        raise ValueError("forecast_origins must be sorted in ascending order.")

    unknown_origins = forecast_origins.difference(data_index)
    if not unknown_origins.empty:
        examples = ", ".join(timestamp.isoformat() for timestamp in unknown_origins[:3])
        raise ValueError(f"forecast_origins are not present in prepared data: {examples}")
    return forecast_origins


def _validate_forecast_timestamps(
    data_index: pd.DatetimeIndex,
    origin: pd.Timestamp,
    forecast_timestamp: pd.Timestamp,
    source_timestamp: pd.Timestamp,
    seasonal_lag_hours: int,
) -> None:
    if forecast_timestamp not in data_index:
        raise ValueError(
            f"Forecast from {origin.isoformat()} does not have a complete "
            f"forecast horizon; missing target timestamp {forecast_timestamp.isoformat()}."
        )
    if source_timestamp not in data_index:
        raise ValueError(
            f"Forecast from {origin.isoformat()} does not have {seasonal_lag_hours} "
            f"hours of historical context; missing source timestamp "
            f"{source_timestamp.isoformat()}."
        )
