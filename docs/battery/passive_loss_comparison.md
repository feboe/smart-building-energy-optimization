# BESS Passive-Loss Comparison

This experiment measures how an always-on auxiliary load and passive battery
self-discharge change the simulated operating value of the BESS. It compares
the established loss-free model with an otherwise identical passive-loss run.

## Loss Model

The auxiliary load is modeled as additional AC-side site demand. Local PV and
CHP generation serve it first; any remaining demand can be supplied by the
battery or grid. Self-discharge reduces usable SOC before each dispatch
decision and is scaled from a 30-day monthly rate to the interval duration.
Charge and discharge efficiencies remain separate throughput-dependent losses.

## Experiment Setup

Both runs use the complete 2021 dataset with 35,040 15-minute intervals. They
share a 1,000 kWh battery, 500 kW charge and discharge limits, a 24-hour rolling
horizon, a four-hour terminal-value window, identical tariffs, 95% directional
efficiencies, and 10% minimum SOC.

The comparison run adds:

| Passive-loss assumption | Value |
| --- | ---: |
| Constant auxiliary power | 2.5 kW |
| Self-discharge | 1% per 30-day month |

The 2.5 kW auxiliary load is a transparent sensitivity assumption, not a
measured site value or a claim about a specific product.

## Annual Result

The dynamic grid-charging LP is the main comparison because it is the strongest
operating case and both runs start and finish at 100 kWh SOC.

| Dynamic grid-charging LP | Without passive losses | With passive losses | Change |
| --- | ---: | ---: | ---: |
| Operational savings | 14,189.07 EUR | 9,702.37 EUR | -4,486.70 EUR |
| Grid import | 1,188,175.44 kWh | 1,208,911.78 kWh | +20,736.34 kWh |
| Grid export | 29,102.01 kWh | 27,907.72 kWh | -1,194.29 kWh |
| Approximate full cycles | 176.62 | 176.53 | -0.08 |
| Peak grid import | approximately 500 kW | approximately 500 kW | unchanged |
| Auxiliary consumption | 0 kWh | 21,900 kWh | +21,900 kWh |
| Self-discharge loss | 0 kWh | 37.80 kWh | +37.80 kWh |

Under these assumptions, annual operational savings fall by 31.6%. The battery
continues to follow a very similar dispatch pattern: equivalent cycles and the
grid-import peak barely change.

## Interpretation

The constant auxiliary load causes almost the entire economic effect. Its
21.9 MWh annual demand is several orders of magnitude larger than the 37.8 kWh
self-discharge loss in the main LP case. Part of that load is covered by local
generation, which explains why grid import rises by less than 21.9 MWh while
grid export also declines.

The result does not show that every 1,000 kWh BESS loses exactly 31.6% of its
operating value. It shows that auxiliary consumption can materially change an
economic assessment even when the optimized dispatch and cycle count remain
nearly unchanged.

## Limitations

- Auxiliary power is constant rather than temperature- or state-dependent.
- The 2.5 kW assumption is generic and should be replaced with product and site
  data for an investment assessment.
- Self-discharge is modeled as a constant monthly rate above minimum SOC.
- Savings exclude purchase, installation, financing, maintenance, and battery
  replacement costs.
