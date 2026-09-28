# BESS Terminal-Value Comparison

This experiment isolates the terminal-value treatment in the rolling-horizon
LP. Its purpose is to test whether assigning a value to stored energy beyond
the current planning window produces a more plausible executed dispatch.

## Experiment Setup

Both runs use identical assumptions:

- complete 2021 data at 15-minute resolution
- 1000 kWh capacity and 500 kW charge/discharge power
- dynamic surplus and grid charging
- 24-hour rolling horizon with perfect foresight inside the horizon
- identical SOC limits, efficiencies, degradation cost, prices, and grid limit
- a single grid connection point that disallows simultaneous import and export

The only difference is the horizon treatment. The reference run assigns no
value to terminal SOC. The comparison run values usable terminal SOC from the
time-weighted mean all-in import price over the final four horizon hours.

## Annual Result

Both runs start and finish at the technical minimum of 100 kWh. Their realised
costs therefore have the same annual boundary inventory and can be compared
directly.

| Dynamic grid-charging LP | Without terminal value | With terminal value | Change |
| --- | ---: | ---: | ---: |
| Operational savings | 14,112.79 EUR | 14,142.60 EUR | +29.82 EUR |
| Grid import | 1,186,003.73 kWh | 1,185,831.97 kWh | -171.76 kWh |
| Approximate full cycles | 176.54 | 175.77 | -0.76 |
| Peak grid import | approximately 500 kW | approximately 500 kW | unchanged |

The terminal value changes a directly executed energy flow in 802 of 35,040
intervals, or 2.29%: surplus charging changes in 441 intervals, grid charging
in 58, and discharge in 303. The resulting executed SOC differs in 5,342
intervals; considering either flows or SOC, the dispatch state differs in 5,467
intervals (15.60%). Its annual cost effect remains small.

## Planned Horizon End State

![Distribution of planned terminal usable SOC with and without a terminal value](assets/terminal_value_soc_comparison.png)

The chart groups the planned usable SOC at the end of every rolling horizon; it
does not show the realised SOC at the currently executed interval. Without a
terminal value, all 35,040 horizon solves plan to end at the technical minimum.
With the four-hour terminal value, 13,715 horizons (39.14%) plan to carry usable
energy beyond that minimum. The distribution also shows how large that planned
carry-over is, instead of selecting a single period with an unusually large SOC
difference.

This is the direct mechanism the experiment is intended to test. The terminal
value is derived from the mean all-in price over hours 20 to 24 of each rolling
horizon, as described in the [LP model](lp_optimization.md#terminal-energy-value).

## Interpretation

The terminal value is not booked as revenue in the reported KPIs. The observed
29.82 EUR improvement is a change in realised operating cost with identical
annual start and end SOC, rather than a fictional terminal credit.

The main result is therefore methodological: terminal valuation counteracts the
artificial incentive to finish each finite planning horizon at minimum SOC. The
planning diagnostic shows that the terminal state changes as intended, while
the executed-flow count and annual KPIs show that this does not translate into
a large operational or financial effect. The annual peak is unchanged, and the
small annual cost change is why this feature should be presented as a model
correction rather than a new source of large savings.

The fixed-price case is not used for the headline comparison because its runs
finish with different SOC inventories. Comparing their raw annual costs would
mix dispatch performance with the value of energy remaining in the battery.
