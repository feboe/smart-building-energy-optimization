"""Scenario factories for BESS simulations."""

from src.battery.parameters import (
    DYNAMIC_SURPLUS_GRID_CHARGING,
    DYNAMIC_SURPLUS_ONLY,
    FIXED_SURPLUS_ONLY,
    BatteryParameters,
    ScenarioParameters,
)


def make_battery_parameters(
    capacity_kwh: float = 1000,
    c_rate: float = 0.5,
    min_soc_fraction: float = 0.10,
    max_soc_fraction: float = 1.00,
    eta_charge: float = 0.95,
    eta_discharge: float = 0.95,
    degradation_cost_eur_per_kwh: float = 0.0,
) -> BatteryParameters:
    """Build battery parameters with project defaults."""
    return BatteryParameters(
        capacity_kwh=capacity_kwh,
        c_rate=c_rate,
        min_soc_fraction=min_soc_fraction,
        max_soc_fraction=max_soc_fraction,
        eta_charge=eta_charge,
        eta_discharge=eta_discharge,
        degradation_cost_eur_per_kwh=degradation_cost_eur_per_kwh,
    )


def make_fixed_surplus_only_scenario(
    export_price_eur_per_kwh: float = 0.0,
    import_markup_eur_per_kwh: float = 0.0,
    horizon_hours: int = 24,
    grid_connection_limit_kw: float | None = None,
) -> ScenarioParameters:
    """Build the fixed-price surplus-only BESS scenario."""
    return ScenarioParameters(
        name="fixed_surplus_only",
        dispatch_strategy=FIXED_SURPLUS_ONLY,
        horizon_hours=horizon_hours,
        import_markup_eur_per_kwh=import_markup_eur_per_kwh,
        export_price_eur_per_kwh=export_price_eur_per_kwh,
        grid_connection_limit_kw=grid_connection_limit_kw,
    )


def make_dynamic_surplus_only_scenario(
    export_price_eur_per_kwh: float = 0.0,
    import_markup_eur_per_kwh: float = 0.0,
    horizon_hours: int = 24,
    grid_connection_limit_kw: float | None = None,
) -> ScenarioParameters:
    """Build the dynamic-price surplus-only BESS scenario."""
    return ScenarioParameters(
        name="dynamic_surplus_only",
        dispatch_strategy=DYNAMIC_SURPLUS_ONLY,
        horizon_hours=horizon_hours,
        import_markup_eur_per_kwh=import_markup_eur_per_kwh,
        export_price_eur_per_kwh=export_price_eur_per_kwh,
        grid_connection_limit_kw=grid_connection_limit_kw,
    )


def make_dynamic_surplus_and_grid_charging_scenario(
    export_price_eur_per_kwh: float = 0.0,
    import_markup_eur_per_kwh: float = 0.0,
    horizon_hours: int = 24,
    surplus_reserve_fraction: float = 1.0,
    grid_connection_limit_kw: float | None = 500.0,
) -> ScenarioParameters:
    """Build the dynamic-price surplus plus grid-charging BESS scenario."""
    return ScenarioParameters(
        name="dynamic_surplus_grid_charging",
        dispatch_strategy=DYNAMIC_SURPLUS_GRID_CHARGING,
        horizon_hours=horizon_hours,
        import_markup_eur_per_kwh=import_markup_eur_per_kwh,
        export_price_eur_per_kwh=export_price_eur_per_kwh,
        surplus_reserve_fraction=surplus_reserve_fraction,
        grid_connection_limit_kw=grid_connection_limit_kw,
    )
