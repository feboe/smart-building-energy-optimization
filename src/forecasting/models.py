"""Baseline and machine-learning load forecasting models."""

from __future__ import annotations

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import NotFittedError

from src.forecasting.config import ForecastConfig, HGBConfig
from src.forecasting.data import (
    validate_forecast_origins,
    validate_prepared_forecasting_data,
)
from src.forecasting.features import (
    FEATURE_METADATA_COLUMNS,
    MAX_HISTORY_HOURS,
    MODEL_FEATURE_COLUMNS,
    TARGET_FEATURE_COLUMN,
    build_forecast_features,
)

FORECAST_COLUMNS = [
    "forecast_origin",
    "forecast_timestamp",
    "horizon_hours",
    "model_name",
    "prediction_kwh",
]


class DailyNaiveForecaster:
    """Forecast each target timestamp with the load observed 24 hours earlier."""

    model_name = "daily_naive"
    required_history_hours = 24

    def fit(
        self,
        prepared_data: pd.DataFrame,
        training_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> DailyNaiveForecaster:
        """Validate the shared input contract; seasonal naive needs no fitting."""
        config = forecast_config or ForecastConfig()
        validate_prepared_forecasting_data(prepared_data, config)
        validate_forecast_origins(training_origins, prepared_data.index)
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
    required_history_hours = 168

    def fit(
        self,
        prepared_data: pd.DataFrame,
        training_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> WeeklyNaiveForecaster:
        """Validate the shared input contract; seasonal naive needs no fitting."""
        config = forecast_config or ForecastConfig()
        validate_prepared_forecasting_data(prepared_data, config)
        validate_forecast_origins(training_origins, prepared_data.index)
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
    """Apply a fixed seasonal lag using the shared forecast output contract."""
    validate_prepared_forecasting_data(prepared_data, forecast_config)
    origins = validate_forecast_origins(forecast_origins, prepared_data.index)

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


def _validate_forecast_timestamps(
    data_index: pd.DatetimeIndex,
    origin: pd.Timestamp,
    forecast_timestamp: pd.Timestamp,
    source_timestamp: pd.Timestamp,
    seasonal_lag_hours: int,
) -> None:
    """Ensure a seasonal forecast has both its label and lagged observation."""
    if forecast_timestamp not in data_index:
        raise ValueError(
            f"Forecast from {origin.isoformat()} does not have a complete "
            f"forecast horizon; missing target timestamp {forecast_timestamp.isoformat()}."
        )
    if source_timestamp not in data_index:
        raise ValueError(
            f"Forecast from {origin.isoformat()} does not have {seasonal_lag_hours} "
            "hours of historical context; missing source timestamp "
            f"{source_timestamp.isoformat()}."
        )


class HistGradientBoostingLoadForecaster:
    """Direct 24-hour gross-load forecaster using histogram gradient boosting."""

    model_name = "hist_gradient_boosting"
    required_history_hours = MAX_HISTORY_HOURS

    def __init__(self, model_config: HGBConfig | None = None) -> None:
        self.model_config = model_config or HGBConfig()
        self.estimator_: HistGradientBoostingRegressor | None = None

    def fit(
        self,
        prepared_data: pd.DataFrame,
        training_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> HistGradientBoostingLoadForecaster:
        """Build training features and fit the configured HGB estimator."""
        config = forecast_config or ForecastConfig()
        training_features = build_forecast_features(
            prepared_data,
            training_origins,
            include_target=True,
            forecast_config=config,
        )
        self.estimator_ = HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=self.model_config.learning_rate,
            max_iter=self.model_config.max_iter,
            max_leaf_nodes=self.model_config.max_leaf_nodes,
            min_samples_leaf=self.model_config.min_samples_leaf,
            l2_regularization=self.model_config.l2_regularization,
            early_stopping=self.model_config.early_stopping,
            random_state=self.model_config.random_state,
        )
        self.estimator_.fit(
            training_features.loc[:, MODEL_FEATURE_COLUMNS],
            training_features[TARGET_FEATURE_COLUMN],
        )
        return self

    def predict(
        self,
        prepared_data: pd.DataFrame,
        forecast_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> pd.DataFrame:
        """Return nonnegative forecasts in the shared long output format."""
        if self.estimator_ is None:
            raise NotFittedError(
                "This HistGradientBoostingLoadForecaster instance is not fitted yet."
            )

        config = forecast_config or ForecastConfig()
        prediction_features = build_forecast_features(
            prepared_data,
            forecast_origins,
            forecast_config=config,
        )
        predictions = self.estimator_.predict(
            prediction_features.loc[:, MODEL_FEATURE_COLUMNS]
        )
        forecast_df = prediction_features.loc[:, FEATURE_METADATA_COLUMNS].copy()
        forecast_df["model_name"] = self.model_name
        forecast_df["prediction_kwh"] = pd.Series(predictions).clip(lower=0).to_numpy()
        return forecast_df.loc[:, FORECAST_COLUMNS]
