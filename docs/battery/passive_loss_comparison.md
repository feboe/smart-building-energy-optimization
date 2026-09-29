# BESS Passive-Loss Comparison

This experiment compares the standard loss-free run with an otherwise
identical run that adds AC-side auxiliary demand and passive self-discharge.
Their implementation is defined in the shared [battery
model](simulation_methodology.md#battery-model).

## Experiment Setup

Both runs use the shared methodology and the same 2021 15-minute, `1000 kWh`
dynamic grid-charging LP setup with the four-hour terminal value introduced in
the preceding terminal-value comparison. The comparison run adds:

| Passive-loss assumption | Value |
| --- | ---: |
| Constant auxiliary power | 2.5 kW |
| Self-discharge | 1% per 30-day month |

The `2.5 kW` auxiliary load is a sensitivity assumption, not a measured site or
product value. Passive losses are a follow-up sensitivity, not part of either
reference configuration.

## Annual Result

The dynamic grid-charging LP is the main comparison because it is the strongest
operating case and both runs start and finish at 100 kWh SOC.

| Dynamic grid-charging LP | Without passive losses | With passive losses | Change |
| --- | ---: | ---: | ---: |
| Operational savings | 14,142.60 EUR | 9,654.12 EUR | -4,488.48 EUR |
| Grid import | 1,185,831.97 kWh | 1,206,625.37 kWh | +20,793.40 kWh |
| Grid export | 26,849.75 kWh | 25,729.05 kWh | -1,120.70 kWh |
| Approximate full cycles | 175.77 | 175.54 | -0.24 |
| Peak grid import | approximately 500 kW | approximately 500 kW | unchanged |
| Auxiliary consumption | 0 kWh | 21,900 kWh | +21,900 kWh |
| Self-discharge loss | 0 kWh | 37.62 kWh | +37.62 kWh |

Under these assumptions, annual operational savings fall by 31.7%. The battery
continues to follow a very similar dispatch pattern: equivalent cycles and the
grid-import peak barely change.

## Interpretation

The constant auxiliary load causes almost the entire economic effect. Its
21.9 MWh annual demand is several orders of magnitude larger than the 37.6 kWh
self-discharge loss in the main LP case. Part of that load is covered by local
generation, which explains why grid import rises by less than 21.9 MWh while
grid export also declines.

The result does not show that every 1,000 kWh BESS loses exactly 31.7% of its
operating value. It shows that auxiliary consumption can materially change an
economic assessment even when the optimized dispatch and cycle count remain
nearly unchanged.

## Assumption Boundary

Auxiliary power is constant rather than temperature- or state-dependent, and
self-discharge is a constant monthly rate above minimum SOC. Product and site
data should replace both sensitivity assumptions in an investment assessment;
the shared [scope limitations](simulation_methodology.md#scope-and-limitations)
continue to apply.
