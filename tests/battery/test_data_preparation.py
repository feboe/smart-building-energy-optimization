"""Tests for canonical BESS input preparation."""

import math

import pytest

from src.battery.data import prepare_simulation_data
from src.battery.scenarios import make_fixed_surplus_only_scenario


def test_prepare_simulation_data_reconstructs_canonical_energy_columns(
    make_analysis_df,
) -> None:
    analysis_df = make_analysis_df(
        [
            {
                "total_w": 100_000,
                "pv_w": 0,
                "chp_w": 0,
            },
            {
                "total_w": 50_000,
                "pv_w": -20_000,
                "chp_w": -30_000,
            },
            {
                "total_w": -25_000,
                "pv_w": -75_000,
                "chp_w": 0,
            },
            {
                "total_w": 100_000,
                "pv_w": 2_000,
                "chp_w": 3_000,
            },
        ]
    )

    prepared_df = prepare_simulation_data(
        analysis_df,
        make_fixed_surplus_only_scenario(),
    )

    assert prepared_df["grid_energy_kwh"].tolist() == pytest.approx(
        [100.0, 50.0, -25.0, 100.0]
    )
    assert prepared_df["pv_generation_kwh"].tolist() == pytest.approx(
        [0.0, 20.0, 75.0, 0.0]
    )
    assert prepared_df["chp_generation_kwh"].tolist() == pytest.approx(
        [0.0, 30.0, 0.0, 0.0]
    )
    assert prepared_df["gross_load_kwh"].tolist() == pytest.approx(
        [100.0, 100.0, 50.0, 100.0]
    )
    assert prepared_df["grid_import_kwh"].tolist() == pytest.approx(
        [100.0, 50.0, 0.0, 100.0]
    )
    assert prepared_df["grid_export_kwh"].tolist() == pytest.approx([0.0, 0.0, 25.0, 0.0])


def test_prepare_simulation_data_applies_import_markup(make_analysis_df) -> None:
    analysis_df = make_analysis_df(
        [{"total_w": 100_000, "day_ahead_price_eur_per_kwh": 0.10}]
    )
    scenario = make_fixed_surplus_only_scenario(import_markup_eur_per_kwh=0.05)

    prepared_df = prepare_simulation_data(analysis_df, scenario)

    assert prepared_df.loc[0, "dynamic_import_price_eur_per_kwh"] == pytest.approx(0.15)


def test_prepare_simulation_data_scales_energy_by_timestep(make_analysis_df) -> None:
    analysis_df = make_analysis_df(
        [
            {
                "resolution": "15min",
                "timestep_hours": 0.25,
                "total_w": 100_000,
                "pv_w": -20_000,
                "chp_w": -30_000,
            }
        ]
    )

    prepared_df = prepare_simulation_data(
        analysis_df,
        make_fixed_surplus_only_scenario(),
    )

    assert prepared_df.loc[0, "grid_energy_kwh"] == pytest.approx(25.0)
    assert prepared_df.loc[0, "pv_generation_kwh"] == pytest.approx(5.0)
    assert prepared_df.loc[0, "chp_generation_kwh"] == pytest.approx(7.5)
    assert prepared_df.loc[0, "gross_load_kwh"] == pytest.approx(37.5)


def test_prepare_simulation_data_interpolates_flagged_gross_load_and_grid_flow(
    make_analysis_df,
) -> None:
    analysis_df = make_analysis_df(
        [
            {"total_w": 100_000, "pv_w": -20_000},
            {
                "total_w": -10_000,
                "gross_load_raw_w": -10_000,
                "gross_load_w": math.nan,
                "gross_load_quality_issue": "negative_gross_load",
            },
            {"total_w": 140_000, "pv_w": -20_000},
        ]
    )

    prepared_df = prepare_simulation_data(
        analysis_df,
        make_fixed_surplus_only_scenario(),
    )

    assert prepared_df.loc[1, "gross_load_raw_w"] == pytest.approx(-10_000)
    assert prepared_df.loc[1, "gross_load_w"] == pytest.approx(140_000)
    assert bool(prepared_df.loc[1, "gross_load_was_imputed"])
    assert prepared_df.loc[1, "grid_power_raw_kw"] == pytest.approx(-10.0)
    assert prepared_df.loc[1, "grid_power_kw"] == pytest.approx(140.0)
    assert prepared_df.loc[1, "grid_import_kwh"] == pytest.approx(140.0)
    assert prepared_df.loc[1, "grid_export_kwh"] == pytest.approx(0.0)


def test_prepare_simulation_data_rejects_unflagged_missing_gross_load(
    make_analysis_df,
) -> None:
    analysis_df = make_analysis_df(
        [{"gross_load_w": math.nan, "gross_load_quality_issue": None}]
    )

    with pytest.raises(ValueError, match="quality flags are inconsistent"):
        prepare_simulation_data(
            analysis_df,
            make_fixed_surplus_only_scenario(),
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("total_w", math.nan),
        ("pv_w", math.inf),
        ("chp_w", -math.inf),
        ("day_ahead_price_eur_per_kwh", "not-a-number"),
    ],
)
def test_prepare_simulation_data_rejects_invalid_numeric_values(
    make_analysis_df,
    column,
    value,
) -> None:
    analysis_df = make_analysis_df([{"total_w": 100_000}])
    if isinstance(value, str):
        analysis_df[column] = analysis_df[column].astype(object)
    analysis_df.loc[0, column] = value

    with pytest.raises(ValueError):
        prepare_simulation_data(
            analysis_df,
            make_fixed_surplus_only_scenario(),
        )


def test_prepare_simulation_data_rejects_missing_required_columns(
    make_analysis_df,
) -> None:
    analysis_df = make_analysis_df([{"total_w": 100_000}]).drop(columns=["total_w"])

    with pytest.raises(ValueError):
        prepare_simulation_data(
            analysis_df,
            make_fixed_surplus_only_scenario(),
        )
