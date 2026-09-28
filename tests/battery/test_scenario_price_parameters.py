"""Validation tests for ScenarioParameters price inputs."""

import math

import pytest

from src.battery.parameters import FIXED_SURPLUS_ONLY, ScenarioParameters


def _scenario(**overrides: object) -> ScenarioParameters:
    return ScenarioParameters(
        name="price_validation",
        dispatch_strategy=FIXED_SURPLUS_ONLY,
        **overrides,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("export_price_eur_per_kwh", -0.01),
        ("export_price_eur_per_kwh", "not-a-number"),
        ("export_price_eur_per_kwh", math.nan),
        ("export_price_eur_per_kwh", math.inf),
        ("fixed_import_price_eur_per_kwh", -0.01),
        ("fixed_import_price_eur_per_kwh", "not-a-number"),
        ("fixed_import_price_eur_per_kwh", math.nan),
        ("fixed_import_price_eur_per_kwh", -math.inf),
    ],
)
def test_scenario_rejects_invalid_nonnegative_price_fields(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError, match=field):
        _scenario(**{field: value})


@pytest.mark.parametrize("value", ["not-a-number", math.nan, math.inf])
def test_scenario_rejects_nonnumeric_or_nonfinite_import_markup(value: object) -> None:
    with pytest.raises(ValueError, match="import_markup_eur_per_kwh"):
        _scenario(import_markup_eur_per_kwh=value)


def test_scenario_allows_negative_finite_import_markup() -> None:
    scenario = _scenario(import_markup_eur_per_kwh=-0.05)

    assert scenario.import_markup_eur_per_kwh == pytest.approx(-0.05)


def test_scenario_allows_zero_export_and_fixed_import_prices() -> None:
    scenario = _scenario(
        export_price_eur_per_kwh=0.0,
        fixed_import_price_eur_per_kwh=0.0,
    )

    assert scenario.export_price_eur_per_kwh == pytest.approx(0.0)
    assert scenario.fixed_import_price_eur_per_kwh == pytest.approx(0.0)
