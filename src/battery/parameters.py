"""Shared parameter objects for BESS simulations."""

from dataclasses import dataclass

FIXED_SURPLUS_ONLY = "fixed_surplus_only"
DYNAMIC_SURPLUS_ONLY = "dynamic_surplus_only"
DYNAMIC_SURPLUS_GRID_CHARGING = "dynamic_surplus_grid_charging"

VALID_DISPATCH_STRATEGIES = {
    FIXED_SURPLUS_ONLY,
    DYNAMIC_SURPLUS_ONLY,
    DYNAMIC_SURPLUS_GRID_CHARGING,
}


@dataclass(frozen=True)
class BatteryParameters:
    """Physical battery assumptions for hourly simulations."""

    capacity_kwh: float
    c_rate: float
    min_soc_fraction: float = 0.10
    max_soc_fraction: float = 1.00
    eta_charge: float = 0.95
    eta_discharge: float = 0.95

    def __post_init__(self) -> None:
        if self.capacity_kwh <= 0:
            raise ValueError("capacity_kwh must be greater than zero.")
        if self.c_rate <= 0:
            raise ValueError("c_rate must be greater than zero.")
        if not 0 <= self.min_soc_fraction <= self.max_soc_fraction <= 1:
            raise ValueError(
                "SOC fractions must satisfy 0 <= min <= max <= 1."
            )
        if not 0 < self.eta_charge <= 1:
            raise ValueError("eta_charge must satisfy 0 < eta_charge <= 1.")
        if not 0 < self.eta_discharge <= 1:
            raise ValueError(
                "eta_discharge must satisfy 0 < eta_discharge <= 1."
            )

    @property
    def max_charge_power_kw(self) -> float:
        """Maximum charging power in kW."""
        return self.capacity_kwh * self.c_rate

    @property
    def max_discharge_power_kw(self) -> float:
        """Maximum discharging power in kW."""
        return self.capacity_kwh * self.c_rate

    @property
    def min_soc_kwh(self) -> float:
        """Minimum usable state of charge in kWh."""
        return self.capacity_kwh * self.min_soc_fraction

    @property
    def max_soc_kwh(self) -> float:
        """Maximum state of charge in kWh."""
        return self.capacity_kwh * self.max_soc_fraction


@dataclass(frozen=True)
class ScenarioParameters:
    """Economic and control assumptions for one simulation scenario."""

    name: str
    dispatch_strategy: str
    horizon_hours: int = 24
    import_markup_eur_per_kwh: float = 0.0
    export_price_eur_per_kwh: float = 0.0
    low_price_quantile: float = 0.25
    high_price_quantile: float = 0.75
    fixed_import_price_eur_per_kwh: float | None = None
    surplus_reserve_fraction: float = 1.0

    def __post_init__(self) -> None:
        if self.dispatch_strategy not in VALID_DISPATCH_STRATEGIES:
            raise ValueError(
                "dispatch_strategy must be one of "
                f"{sorted(VALID_DISPATCH_STRATEGIES)}."
            )
        if self.horizon_hours <= 0:
            raise ValueError("horizon_hours must be greater than zero.")
        if not 0 <= self.low_price_quantile <= 1:
            raise ValueError("low_price_quantile must be between 0 and 1.")
        if not 0 <= self.high_price_quantile <= 1:
            raise ValueError("high_price_quantile must be between 0 and 1.")
        if self.low_price_quantile > self.high_price_quantile:
            raise ValueError(
                "low_price_quantile must be lower than or equal to "
                "high_price_quantile."
            )
        if not 0 <= self.surplus_reserve_fraction <= 1:
            raise ValueError("surplus_reserve_fraction must be between 0 and 1.")
