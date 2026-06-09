"""Shared helpers for synthetic BESS tests."""

from collections.abc import Callable

import pandas as pd
import pytest


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
        tolerance = 1e-6
        nonnegative_columns = [
            "charge_from_surplus_kwh",
            "charge_from_grid_kwh",
            "battery_charge_kwh",
            "discharge_to_load_kwh",
            "grid_import_kwh",
            "grid_export_kwh",
        ]
        assert (dispatch_df[nonnegative_columns] >= -tolerance).all().all()

        energy_balance_error = (
            dispatch_df["local_generation_kwh"]
            + dispatch_df["grid_import_kwh"]
            + dispatch_df["discharge_to_load_kwh"]
            - dispatch_df["gross_load_kwh"]
            - dispatch_df["charge_from_surplus_kwh"]
            - dispatch_df["charge_from_grid_kwh"]
            - dispatch_df["grid_export_kwh"]
        ).abs()
        assert (energy_balance_error <= tolerance).all()

        soc_balance_error = (
            dispatch_df["soc_start_kwh"]
            + dispatch_df["battery_charge_kwh"] * battery.eta_charge
            - dispatch_df["discharge_to_load_kwh"] / battery.eta_discharge
            - dispatch_df["soc_end_kwh"]
        ).abs()
        assert (soc_balance_error <= tolerance).all()

        assert (
            dispatch_df["soc_start_kwh"] >= battery.min_soc_kwh - tolerance
        ).all()
        assert (
            dispatch_df["soc_end_kwh"] >= battery.min_soc_kwh - tolerance
        ).all()
        assert (
            dispatch_df["soc_start_kwh"] <= battery.max_soc_kwh + tolerance
        ).all()
        assert (
            dispatch_df["soc_end_kwh"] <= battery.max_soc_kwh + tolerance
        ).all()

        assert (
            dispatch_df["battery_charge_kwh"]
            <= battery.max_charge_power_kw + tolerance
        ).all()
        assert (
            dispatch_df["discharge_to_load_kwh"]
            <= battery.max_discharge_power_kw + tolerance
        ).all()
        assert (
            dispatch_df["charge_from_surplus_kwh"]
            <= dispatch_df["available_surplus_kwh"] + tolerance
        ).all()
        assert (
            dispatch_df["discharge_to_load_kwh"]
            <= dispatch_df["demand_after_generation_kwh"] + tolerance
        ).all()

        simultaneous = (
            dispatch_df["battery_charge_kwh"] > tolerance
        ) & (dispatch_df["discharge_to_load_kwh"] > tolerance)
        assert not simultaneous.any()

        export_without_surplus = (
            dispatch_df["grid_export_kwh"]
            - dispatch_df["available_surplus_kwh"]
            + dispatch_df["charge_from_surplus_kwh"]
        ).abs()
        assert (export_without_surplus <= tolerance).all()

    return _assert_dispatch_physics
