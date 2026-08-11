"""Machine-learning load forecasting models."""

from __future__ import annotations

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import NotFittedError

from src.forecasting.baselines import FORECAST_COLUMNS
from src.forecasting.config import ForecastConfig
from src.forecasting.features import (
    FEATURE_METADATA_COLUMNS,
    MODEL_FEATURE_COLUMNS,
    TARGET_FEATURE_COLUMN,
    build_forecast_features,
)


class HistGradientBoostingLoadForecaster:
    """Direct 24-hour gross-load forecaster using histogram gradient boosting."""

    model_name = "hist_gradient_boosting"

    def __init__(self) -> None:
        self.estimator_: HistGradientBoostingRegressor | None = None

    def fit(
        self,
        prepared_data: pd.DataFrame,
        training_origins: pd.DatetimeIndex,
        forecast_config: ForecastConfig | None = None,
    ) -> HistGradientBoostingLoadForecaster:
        """Build training features and fit the fixed HGB configuration."""
        config = forecast_config or ForecastConfig()
        training_features = build_forecast_features(
            prepared_data,
            training_origins,
            include_target=True,
            forecast_config=config,
        )
        self.estimator_ = HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.05,
            max_iter=300,
            max_leaf_nodes=15,
            min_samples_leaf=20,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=42,
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
