# BESS Simulation Methodology

This document describes the first version of the battery energy storage system
(BESS) simulation for the smart company energy data. The goal is to compare a
no-battery baseline with simple battery dispatch strategies before introducing
mathematical optimization.

## Data Basis

The first simulation uses the `smart_company_analysis` view for the local
calendar year 2021.

Relevant input columns:

- `gross_load_kwh`: building demand
- `pv_generation_kwh`: clipped positive PV generation
- `chp_generation_kwh`: clipped positive CHP generation
- `grid_import_kwh`: baseline grid import without battery
- `grid_export_kwh`: baseline grid export without battery
- `day_ahead_price_eur_per_kwh`: dynamic market price signal
- `local_timestamp`, `local_month`, `local_hour`, `local_isodow`

Raw signed values are used upstream to reconstruct building demand. The battery
simulation uses the clipped nonnegative generation and grid-flow columns because
they represent physical generation, import, and export flows.

## Scenarios

### Baseline: No BESS

- No battery is used.
- Baseline grid import and export come directly from `smart_company_analysis`.
- The baseline is evaluated under both dynamic and fixed import pricing.
- This case is the reference for all BESS scenarios.

### 1. Surplus-Only BESS

- Battery can only charge from local surplus.
- Battery discharges to reduce grid import.
- Grid charging is disabled.
- This scenario mainly measures self-consumption value.
- The surplus-only case is evaluated under both fixed and dynamic import
  pricing.
- Fixed-price surplus-only dispatch uses its own simple heuristic because every
  avoided grid-import kWh has the same value.

### 2. Surplus + Grid-Charging BESS

- Battery can charge from local surplus and from the grid.
- Grid charging is allowed in low-price hours.
- Battery discharges to reduce grid import in high-price/import hours.
- This scenario measures self-consumption plus dynamic-price arbitrage.
- The grid-charging case is evaluated only under dynamic import pricing.
- Fixed-price grid charging is excluded from the main analysis because buying
  grid energy and later using it at the same fixed price only adds storage
  losses. It can be used as a sanity check, but not as a meaningful target case.

The scenario structure follows the economic logic of the price models. With a
fixed import price, the battery creates value by increasing local
self-consumption. Charging from the grid only becomes meaningful when import
prices vary over time.

Target comparison structure:

| Case | Fixed price | Dynamic price |
| --- | --- | --- |
| No BESS baseline | yes | yes |
| Surplus-only BESS | yes | yes |
| Surplus + grid-charging BESS | no | yes |

For the active BESS cases, the project compares:

- heuristic dispatch
- LP optimization dispatch
- multiple battery capacities
- multiple export-price assumptions

## Price Assumptions

The model separates market prices, import markup, and export compensation:

- `dynamic_import_price = day_ahead_price + import_markup`
- `fixed_import_price = mean(dynamic_import_price)`
- `export_price = scenario parameter`

In the first version, no additional import markup or export compensation is
included:

- `import_markup = 0`
- `export_price = 0`

Later sensitivity runs can test fixed export prices such as 4, 6, or 8 ct/kWh.

## Battery Assumptions

The first simulation uses the following battery parameter set:

- `capacity_kwh`: `[250, 500, 1000, 2000]`
- `c_rate`: `0.5` or `1.0`
- `max_charge_power_kw = capacity_kwh * c_rate`
- `max_discharge_power_kw = capacity_kwh * c_rate`
- `min_soc = 10% * capacity_kwh`
- `max_soc = 100% * capacity_kwh`
- `eta_charge = 0.95`
- `eta_discharge = 0.95`
- battery only discharges to load

The following effects are neglected in version 1:

- battery degradation
- cycle costs
- forecast error
- export from battery to grid
- hard binary charge/discharge mode

The first LP model may allow simultaneous charge and discharge in theory. With
efficiency losses this should usually be uneconomic. If simultaneous charge and
discharge becomes material in later optimization results, a MILP formulation can
be introduced.

## Rolling Optimization

The optimization uses a rolling 24-hour horizon with hourly control.

At each hour, the controller reads the current state of charge, builds a
24-hour plan using known or assumed future load, generation, and prices,
executes only the first-hour decision, and then advances by one hour.

Version 1 assumes perfect foresight as an idealized benchmark.

## LP Model Foundation

Decision variables per hour:

- `charge_from_surplus_kwh`
- `charge_from_grid_kwh`
- `discharge_to_load_kwh`
- `grid_import_kwh`
- `grid_export_kwh`
- `soc_kwh`

Core hourly balance:

```text
pv_generation
+ chp_generation
+ grid_import
+ battery_discharge_to_load
=
building_load
+ battery_charge
+ grid_export
```

with:

```text
battery_charge = charge_from_surplus + charge_from_grid
```

Important constraints:

- SOC stays between minimum and maximum capacity.
- Charge and discharge are limited by power limits.
- `charge_from_surplus <= available_surplus`.
- In the surplus-only case: `charge_from_grid = 0`.
- Battery discharge only serves load.

The optimization objective minimizes net electricity cost. The effective cost
per load kWh is calculated after optimization:

```text
effective_cost_per_load_kwh = net_cost / total_building_load_kwh
```

## Heuristic Baseline

### Fixed-Price Surplus-Only Heuristic

Because the fixed import price is constant, the battery does not need a price
signal. The fixed-price surplus-only heuristic follows these rules:

- charge from surplus first
- discharge to serve load whenever there is a deficit and usable SOC is
  available
- never charge from the grid
- export remaining surplus only when the battery is full or charge power is
  limited

### Dynamic-Price Heuristic

The dynamic-price heuristic uses rolling-horizon price thresholds:

- charge from surplus first
- discharge when price is greater than or equal to the 75th percentile of known
  horizon prices
- charge from grid when price is less than or equal to the 25th percentile of
  known horizon prices, only in the grid-charging scenario
- export remaining surplus only when the battery is full or charge power is
  limited

The percentile thresholds are calculated from the known rolling horizon, not
from the full year.

## Evaluation Metrics

Primary metric:

- effective net cost per building load kWh

Additional metrics:

- total net electricity cost
- total grid import
- total grid export
- battery throughput
- approximate cycles
- self-consumption increase
- peak grid import
