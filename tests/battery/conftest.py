"""Shared helpers for synthetic BESS tests."""

from collections.abc import Callable

import pandas as pd
import pytest

from src.battery.dispatch import validate_dispatch_results


@pytest.fixture
def make_analysis_df() -> Callable[[list[dict]], pd.DataFrame]:
    def _make_analysis_df(rows: list[dict]) -> pd.DataFrame:
        base_timestamp = pd.Timestamp("2021-01-01 00:00:00", tz="UTC")
        records = []
        for offset, row in enumerate(rows):
            record = {
                "observation_timestamp": base_timestamp + pd.Timedelta(hours=offset),
                "local_timestamp": (
                    base_timestamp + pd.Timedelta(hours=offset)
                ).tz_convert("Europe/Berlin").tz_localize(None),
                "total_w": 0.0,
                "pv_w": 0.0,
                "chp_w": 0.0,
                "day_ahead_price_eur_per_kwh": 0.1,
            }
            record.update(row)
            records.append(record)

        return pd.DataFrame(records)

    return _make_analysis_df


@pytest.fixture
def assert_dispatch_physics() -> Callable:
    def _assert_dispatch_physics(dispatch_df: pd.DataFrame, battery) -> None:
        validate_dispatch_results(dispatch_df, battery)

    return _assert_dispatch_physics
