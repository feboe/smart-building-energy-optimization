"""Tests for the histogram gradient boosting load forecaster."""

import math

import pandas as pd
import pytest
from sklearn.exceptions import NotFittedError

from src.forecasting.config import HGBConfig
from src.forecasting.features import MAX_HISTORY_HOURS, MODEL_FEATURE_COLUMNS
from src.forecasting.models import FORECAST_COLUMNS, HistGradientBoostingLoadForecaster


def _make_prepared_data(periods: int = 240) -> pd.DataFrame:
    index = pd.date_range("2020-10-17T00:00:00Z", periods=periods, freq="h")
    local_index = index.tz_convert("Europe/Berlin")
    local_isodow = local_index.dayofweek + 1
    return pd.DataFrame(
        {
            "gross_load_kwh": [50 + (position % 48) for position in range(periods)],
            "local_timestamp": local_index,
            "local_hour": local_index.hour,
            "local_isodow": local_isodow,
            "is_weekend": local_isodow.isin([6, 7]),
            "local_month": local_index.month,
        },
        index=index,
    )


def test_hgb_forecaster_requires_fit_before_predicting() -> None:
    prepared_data = _make_prepared_data()
    origins = prepared_data.index[[180]]

    with pytest.raises(NotFittedError, match="not fitted"):
        HistGradientBoostingLoadForecaster().predict(prepared_data, origins)


def test_hgb_forecaster_uses_shared_input_and_output_contract() -> None:
    prepared_data = _make_prepared_data()
    origins = prepared_data.index[[180, 181]]
    forecaster = HistGradientBoostingLoadForecaster()

    assert forecaster.required_history_hours == MAX_HISTORY_HOURS
    assert forecaster.fit(prepared_data, origins) is forecaster
    assert forecaster.estimator_ is not None
    assert forecaster.estimator_.feature_names_in_.tolist() == MODEL_FEATURE_COLUMNS

    forecasts = forecaster.predict(prepared_data, origins)

    assert list(forecasts.columns) == FORECAST_COLUMNS
    assert len(forecasts) == len(origins) * 24
    assert forecasts["model_name"].unique().tolist() == ["hist_gradient_boosting"]
    assert forecasts["horizon_hours"].tolist() == list(range(1, 25)) * len(origins)
    assert forecasts["prediction_kwh"].ge(0).all()
    assert forecasts["prediction_kwh"].map(math.isfinite).all()


def test_hgb_forecaster_uses_injected_model_configuration() -> None:
    prepared_data = _make_prepared_data()
    origins = prepared_data.index[[180, 181]]
    model_config = HGBConfig(
        learning_rate=0.1,
        max_iter=10,
        max_leaf_nodes=7,
        min_samples_leaf=5,
        l2_regularization=0.5,
        random_state=7,
    )

    forecaster = HistGradientBoostingLoadForecaster(model_config).fit(
        prepared_data,
        origins,
    )

    assert forecaster.model_config is model_config
    assert forecaster.estimator_ is not None
    assert forecaster.estimator_.learning_rate == 0.1
    assert forecaster.estimator_.max_iter == 10
    assert forecaster.estimator_.max_leaf_nodes == 7
    assert forecaster.estimator_.min_samples_leaf == 5
    assert forecaster.estimator_.l2_regularization == 0.5
    assert forecaster.estimator_.random_state == 7
