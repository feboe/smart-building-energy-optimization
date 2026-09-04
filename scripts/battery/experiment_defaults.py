"""Project assumptions and builders shared by the BESS experiment CLIs."""

from __future__ import annotations

from src.battery.parameters import BatteryParameters, ScenarioParameters
from src.battery.scenarios import (
    make_battery_parameters,
    make_dynamic_surplus_and_grid_charging_scenario,
    make_dynamic_surplus_only_scenario,
    make_fixed_surplus_only_scenario,
)


C_RATE = 0.5
MIN_SOC_FRACTION = 0.10
MAX_SOC_FRACTION = 1.00
ETA_CHARGE = 0.95
ETA_DISCHARGE = 0.95
DEGRADATION_COST_EUR_PER_KWH = 0.03

IMPORT_MARKUP_EUR_PER_KWH = 0.115
EXPORT_PRICE_EUR_PER_KWH = 0.08
HORIZON_HOURS = 24
TERMINAL_VALUE_WINDOW_HOURS = 4.0
GRID_CONNECTION_LIMIT_KW = 500.0
SURPLUS_RESERVE_FRACTION = 1.0


def make_standard_battery(capacity_kwh: float) -> BatteryParameters:
    """Return the project-standard battery for a specified energy capacity."""
    return make_battery_parameters(
        capacity_kwh=capacity_kwh,
        max_charge_power_kw=capacity_kwh * C_RATE,
        max_discharge_power_kw=capacity_kwh * C_RATE,
        min_soc_fraction=MIN_SOC_FRACTION,
        max_soc_fraction=MAX_SOC_FRACTION,
        eta_charge=ETA_CHARGE,
        eta_discharge=ETA_DISCHARGE,
        degradation_cost_eur_per_kwh=DEGRADATION_COST_EUR_PER_KWH,
    )


def make_standard_batteries(capacities_kwh: list[float]) -> list[BatteryParameters]:
    """Resolve capacity inputs to the standard battery parameter objects."""
    return [make_standard_battery(capacity_kwh) for capacity_kwh in capacities_kwh]


def make_standard_scenarios(
    terminal_value_window_hours: float | None = TERMINAL_VALUE_WINDOW_HOURS,
) -> list[ScenarioParameters]:
    """Return the three standard BESS dispatch scenarios."""
    return [
        make_fixed_surplus_only_scenario(
            export_price_eur_per_kwh=EXPORT_PRICE_EUR_PER_KWH,
            import_markup_eur_per_kwh=IMPORT_MARKUP_EUR_PER_KWH,
            horizon_hours=HORIZON_HOURS,
            terminal_value_window_hours=terminal_value_window_hours,
        ),
        make_dynamic_surplus_only_scenario(
            export_price_eur_per_kwh=EXPORT_PRICE_EUR_PER_KWH,
            import_markup_eur_per_kwh=IMPORT_MARKUP_EUR_PER_KWH,
            horizon_hours=HORIZON_HOURS,
            terminal_value_window_hours=terminal_value_window_hours,
        ),
        make_dynamic_surplus_and_grid_charging_scenario(
            export_price_eur_per_kwh=EXPORT_PRICE_EUR_PER_KWH,
            import_markup_eur_per_kwh=IMPORT_MARKUP_EUR_PER_KWH,
            horizon_hours=HORIZON_HOURS,
            terminal_value_window_hours=terminal_value_window_hours,
            surplus_reserve_fraction=SURPLUS_RESERVE_FRACTION,
            grid_connection_limit_kw=GRID_CONNECTION_LIMIT_KW,
        ),
    ]
