"""Tests for explicit BESS charge and discharge power limits."""

import math

import pytest

from src.battery.dispatch import validate_dispatch_results
from src.battery.heuristic import run_heuristic_dispatch
from src.battery.optimization import run_optimized_dispatch
from src.battery.parameters import BatteryParameters
from src.battery.scenarios import (
    make_battery_parameters,
    make_fixed_surplus_only_scenario,
)


def test_battery_parameters_require_capacity_and_directional_power_limits() -> None:
    with pytest.raises(TypeError):
        BatteryParameters(capacity_kwh=1000)
    with pytest.raises(TypeError):
        make_battery_parameters(capacity_kwh=1000)
    with pytest.raises(TypeError):
        make_battery_parameters(
            capacity_kwh=1000,
            max_charge_power_kw=500,
            max_discharge_power_kw=500,
            c_rate=0.5,
        )


def test_asymmetric_explicit_power_derives_directional_c_rates() -> None:
    battery = make_battery_parameters(
        capacity_kwh=1000,
        max_charge_power_kw=250,
        max_discharge_power_kw=500,
    )

    assert battery.max_charge_power_kw == pytest.approx(250.0)
    assert battery.max_discharge_power_kw == pytest.approx(500.0)
    assert battery.charge_c_rate == pytest.approx(0.25)
    assert battery.discharge_c_rate == pytest.approx(0.5)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"capacity_kwh": 0}, "capacity_kwh"),
        ({"capacity_kwh": math.inf}, "capacity_kwh"),
        ({"max_charge_power_kw": 0}, "max_charge_power_kw"),
        ({"max_charge_power_kw": math.nan}, "max_charge_power_kw"),
        ({"max_charge_power_kw": None}, "max_charge_power_kw"),
        ({"max_discharge_power_kw": 0}, "max_discharge_power_kw"),
        ({"max_discharge_power_kw": math.inf}, "max_discharge_power_kw"),
    ],
)
def test_battery_power_configuration_rejects_invalid_values(
    kwargs: dict[str, float | None],
    message: str,
) -> None:
    configured = {
        "capacity_kwh": 100,
        "max_charge_power_kw": 50,
        "max_discharge_power_kw": 50,
    }
    configured.update(kwargs)

    with pytest.raises(ValueError, match=message):
        make_battery_parameters(**configured)


@pytest.mark.parametrize("dispatch", [run_heuristic_dispatch, run_optimized_dispatch])
@pytest.mark.parametrize(
    ("timestep_hours", "resolution"),
    [(1.0, "hour"), (0.25, "15min")],
)
def test_dispatches_respect_asymmetric_directional_power_limits(
    make_analysis_df,
    dispatch,
    timestep_hours: float,
    resolution: str,
) -> None:
    battery = make_battery_parameters(
        capacity_kwh=100,
        max_charge_power_kw=25,
        max_discharge_power_kw=50,
        min_soc_fraction=0.0,
        eta_charge=1.0,
        eta_discharge=1.0,
    )
    scenario = make_fixed_surplus_only_scenario(horizon_hours=2)
    power_w = 100_000 / timestep_hours
    charge_dispatch = dispatch(
        make_analysis_df(
            [
                {
                    "resolution": resolution,
                    "timestep_hours": timestep_hours,
                    "total_w": -power_w,
                    "pv_w": -2 * power_w,
                },
                {
                    "resolution": resolution,
                    "timestep_hours": timestep_hours,
                    "total_w": power_w,
                },
            ]
        ),
        battery,
        scenario,
    )
    discharge_dispatch = dispatch(
        make_analysis_df(
            [
                {
                    "resolution": resolution,
                    "timestep_hours": timestep_hours,
                    "total_w": power_w,
                }
            ]
        ),
        battery,
        scenario,
        initial_soc_kwh=battery.max_soc_kwh,
    )

    assert charge_dispatch.loc[0, "battery_charge_kwh"] == pytest.approx(
        25 * timestep_hours
    )
    assert discharge_dispatch.loc[0, "discharge_to_load_kwh"] == pytest.approx(
        50 * timestep_hours
    )
    validate_dispatch_results(charge_dispatch, battery)
    validate_dispatch_results(discharge_dispatch, battery)


def test_validator_applies_asymmetric_directional_power_limits(
    make_analysis_df,
) -> None:
    timestep_hours = 0.25
    resolution = "15min"
    battery = make_battery_parameters(
        capacity_kwh=100,
        max_charge_power_kw=25,
        max_discharge_power_kw=50,
        min_soc_fraction=0.0,
        eta_charge=1.0,
        eta_discharge=1.0,
    )
    scenario = make_fixed_surplus_only_scenario(horizon_hours=2)
    power_w = 100_000 / timestep_hours
    dispatch_df = run_heuristic_dispatch(
        make_analysis_df(
            [
                {
                    "resolution": resolution,
                    "timestep_hours": timestep_hours,
                    "total_w": -power_w,
                    "pv_w": -2 * power_w,
                },
                {
                    "resolution": resolution,
                    "timestep_hours": timestep_hours,
                    "total_w": power_w,
                },
            ]
        ),
        battery,
        scenario,
    )

    excessive_charge = dispatch_df.copy()
    excessive_charge.loc[0, "battery_charge_kwh"] = 25 * timestep_hours + 1
    excessive_charge.loc[0, "charge_from_surplus_kwh"] = 25 * timestep_hours + 1
    with pytest.raises(ValueError, match="charge exceeds"):
        validate_dispatch_results(excessive_charge, battery)

    excessive_discharge = dispatch_df.copy()
    excessive_discharge.loc[1, "discharge_to_load_kwh"] = 50 * timestep_hours + 1
    with pytest.raises(ValueError, match="discharge exceeds"):
        validate_dispatch_results(excessive_discharge, battery)
