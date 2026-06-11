# BESS Simulation Methodology

This document explains the battery energy storage system (BESS) simulation used
in this project. The goal is to compare three levels of energy management:

- a no-battery baseline
- a transparent rule-based heuristic
- a rolling-horizon linear optimization model

The project is intentionally educational. It is not meant to be production EMS
software. The focus is to build a physically consistent simulation foundation,
then show how a mathematical optimizer can improve dispatch decisions under
dynamic electricity prices.

The heuristic controller is described in
[`heuristic_dispatch.md`](heuristic_dispatch.md). The linear optimization model
is described in [`lp_optimization.md`](lp_optimization.md).

## Energy Convention

The simulation uses hourly energy values. Power values from the analysis data
are converted to kWh per hour.

The source data contains signed net grid power and signed local generation
signals. The BESS model reconstructs a clean hourly energy balance from those
signals:

```text
grid_energy_kwh = total_w / 1000
pv_generation_kwh = max(-pv_w / 1000, 0)
chp_generation_kwh = max(-chp_w / 1000, 0)
local_generation_kwh = pv_generation_kwh + chp_generation_kwh
gross_load_kwh = grid_energy_kwh + local_generation_kwh
grid_import_kwh = max(grid_energy_kwh, 0)
grid_export_kwh = max(-grid_energy_kwh, 0)
```

With this convention, negative PV or CHP power is treated as usable local
generation. Small positive PV or CHP auxiliary consumption remains part of the
building load through the signed net grid value.

The battery-facing quantities are:

- `available_surplus_kwh`: local generation left after serving load
- `demand_after_generation_kwh`: load left after local generation
- `dynamic_import_price_eur_per_kwh`: day-ahead price plus import markup

This gives the dispatch algorithms a simple view of each hour: either there is
local surplus to store/export, or there is remaining demand to serve from the
battery/grid.

## Price Model

The simulation uses a simplified operating-cost model, not a full electricity
tariff. Hourly SMARD day-ahead prices are converted to EUR/kWh and then a fixed
import markup is added:

```text
dynamic_import_price_eur_per_kwh =
    day_ahead_price_eur_per_kwh + import_markup_eur_per_kwh
```

In the current experiment script, the markup is `0.115 EUR/kWh`. This is meant
to approximate non-energy components of an industrial import price, such as
network charges, levies, taxes, and supplier margin.

The fixed-price scenario uses one constant import price derived from the
dynamic import-price series. Exported surplus is valued with a fixed export
price, currently `0.08 EUR/kWh`. Battery wear is represented by a simple
throughput cost, currently `0.03 EUR` per discharged kWh.

These assumptions are intentionally coarse but suitable for comparing dispatch
strategies. They should be read as 2021-style portfolio assumptions, not as a
site-specific tariff model, EEG settlement model, or full battery lifetime-cost
calculation.

## Battery Model

The battery is modeled with a small set of physical assumptions:

- energy capacity in kWh
- minimum and maximum state of charge (SOC)
- charge and discharge efficiency
- C-rate based charge and discharge power limits
- optional degradation proxy based on discharged throughput

The maximum charge and discharge power are derived from capacity and C-rate:

```text
max_charge_power_kw = capacity_kwh * c_rate
max_discharge_power_kw = capacity_kwh * c_rate
```

The SOC balance is:

```text
soc_end =
    soc_start
    + battery_charge_kwh * eta_charge
    - discharge_to_load_kwh / eta_discharge
```

The battery only discharges to serve local load. It does not export stored
energy to the grid. Grid export is therefore only leftover local surplus after
the battery has charged from surplus.

The degradation model is deliberately simple:

```text
battery_degradation_cost =
    battery_discharge_throughput_kwh * degradation_cost_eur_per_kwh
```

This is not a detailed aging model. It is a cost proxy that discourages
unnecessary cycling and makes price arbitrage more realistic.

## Compared Scenarios

### No-Battery Baseline

The baseline uses the reconstructed grid import and export without a battery.
It is evaluated under both fixed and dynamic import prices. This is the
reference for all BESS scenarios.

### Fixed Surplus-Only BESS

The battery can only charge from local surplus. It discharges to reduce grid
import whenever there is remaining demand. Grid charging is disabled.

This case mainly measures the value of increasing self-consumption when every
avoided grid-import kWh has the same fixed value.

### Dynamic Surplus-Only BESS

The battery still charges only from local surplus, but discharge timing uses a
dynamic price signal. The battery is held for high-price hours instead of
discharging into every deficit hour.

This case shows how price-aware dispatch can change the value of the same local
surplus energy.

### Dynamic Surplus and Grid-Charging BESS

The battery can charge from local surplus and from the grid. Grid charging is
only meaningful when prices vary over time: the battery can buy energy in low
price hours and use it to reduce import in high price hours.

This scenario combines self-consumption with price arbitrage. It also includes
a grid connection limit that caps extra grid charging when the building already
has natural grid demand.

## Dispatch Contract

Both the heuristic and the LP optimizer return the same dispatch dataframe. This
keeps metric calculation and validation independent of the control method.

Important dispatch flows are:

- `charge_from_surplus_kwh`
- `charge_from_grid_kwh`
- `battery_charge_kwh`
- `discharge_to_load_kwh`
- `grid_import_kwh`
- `grid_export_kwh`
- `soc_start_kwh`
- `soc_end_kwh`

The shared validator enforces the physical contract:

- required columns are present
- flows are finite and nonnegative
- SOC stays within bounds
- battery charge equals its surplus and grid components
- charge and discharge power limits are respected
- the battery cannot charge from more surplus than available
- the battery cannot discharge more than remaining demand
- no simultaneous charge and discharge appears in the final dispatch output
- grid export equals leftover local surplus
- hourly energy balance and SOC balance are consistent

This validation layer is useful because it checks both the simple heuristic and
the optimization output against the same physical rules.

## Evaluation Metrics

The main economic metric is net cost:

```text
net_cost =
    grid_import_cost
    - grid_export_revenue
    + battery_degradation_cost
```

The project also reports:

- effective cost per building load kWh
- cost savings compared with the no-battery baseline
- total grid import and export
- charge and discharge throughput
- approximate full cycles
- peak grid import
- self-consumption ratio and improvement

Additional utilization metrics help explain whether a battery size is useful:

- `soc_range_utilization`: how much of the usable SOC range is used
- `surplus_capture_ratio`: share of available surplus stored by the battery
- `grid_charge_share`: share of battery charging that came from the grid

Dynamic price timing metrics help explain grid charging:

- average grid charging price
- average battery discharge price
- efficiency and degradation adjusted arbitrage spread

The arbitrage spread is only a proxy. The dispatch output does not track
whether a discharged kWh originally came from surplus or from grid charging.

## Scope and Limitations

The model is intentionally simplified:

- hourly timestep only
- no forecast error
- no quarter-hour market products
- no battery export to grid
- no detailed battery degradation model
- no load shedding
- no reactive power or voltage constraints
- no hard binary charge/discharge mode in the LP formulation

The LP optimizer uses perfect foresight inside each rolling horizon. That makes
it a useful benchmark for learning and comparison, but not a complete
representation of a real operational EMS.

The value of the project is the clean comparison: a physically validated
baseline, a transparent heuristic, and a mathematical optimization benchmark
that all operate on the same dispatch contract.
