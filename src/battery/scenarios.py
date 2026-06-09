"""Scenario factories for BESS simulations."""

from src.battery.parameters import BatteryParameters, ScenarioParameters


def make_battery_parameters(
    capacity_kwh: float = 1000,
    c_rate: float = 0.5,
    min_soc_fraction: float = 0.10,
    max_soc_fraction: float = 1.00,
    eta_charge: float = 0.95,
    eta_discharge: float = 0.95,
) -> BatteryParameters:
    """Build battery parameters with project defaults."""
    return BatteryParameters(
        capacity_kwh=capacity_kwh,
        c_rate=c_rate,
        min_soc_fraction=min_soc_fraction,
        max_soc_fraction=max_soc_fraction,
        eta_charge=eta_charge,
        eta_discharge=eta_discharge,
    )


def make_surplus_only_scenario(
    export_price_eur_per_kwh: float = 0.0,
    import_markup_eur_per_kwh: float = 0.0,
    horizon_hours: int = 24,
) -> ScenarioParameters:
    """Build the surplus-only BESS scenario."""
    return ScenarioParameters(
        name="surplus_only",
        allow_grid_charging=False,
        horizon_hours=horizon_hours,
        import_markup_eur_per_kwh=import_markup_eur_per_kwh,
        export_price_eur_per_kwh=export_price_eur_per_kwh,
    )


def make_surplus_and_grid_charging_scenario(
    export_price_eur_per_kwh: float = 0.0,
    import_markup_eur_per_kwh: float = 0.0,
    horizon_hours: int = 24,
) -> ScenarioParameters:
    """Build the surplus plus grid-charging BESS scenario."""
    return ScenarioParameters(
        name="surplus_and_grid_charging",
        allow_grid_charging=True,
        horizon_hours=horizon_hours,
        import_markup_eur_per_kwh=import_markup_eur_per_kwh,
        export_price_eur_per_kwh=export_price_eur_per_kwh,
    )

