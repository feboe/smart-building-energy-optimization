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
        observation_timestamp = base_timestamp
        for row in rows:
            record = {
                "observation_timestamp": observation_timestamp,
                "local_timestamp": observation_timestamp
                .tz_convert("Europe/Berlin")
                .tz_localize(None),
                "resolution": "hour",
                "timestep_hours": 1.0,
                "total_w": 0.0,
                "pv_w": 0.0,
                "chp_w": 0.0,
                "day_ahead_price_eur_per_kwh": 0.1,
            }
            record.update(row)
            pv_generation_w = max(-float(record["pv_w"]), 0.0)
            chp_generation_w = max(-float(record["chp_w"]), 0.0)
            gross_load_w = (
                float(record["total_w"]) + pv_generation_w + chp_generation_w
            )
            record.setdefault("gross_load_raw_w", gross_load_w)
            record.setdefault("gross_load_w", gross_load_w)
            record.setdefault("gross_load_quality_issue", None)
            records.append(record)
            observation_timestamp += pd.Timedelta(hours=record["timestep_hours"])

        return pd.DataFrame(records)

    return _make_analysis_df


@pytest.fixture
def assert_dispatch_physics() -> Callable:
    def _assert_dispatch_physics(dispatch_df: pd.DataFrame, battery) -> None:
        validate_dispatch_results(dispatch_df, battery)

    return _assert_dispatch_physics
