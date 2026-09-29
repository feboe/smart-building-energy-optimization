# BESS Experiment Results

This document summarizes the 2021 battery energy storage system (BESS)
experiments. It compares a transparent heuristic controller with a
rolling-horizon linear program (LP), then examines how the results change with
battery capacity.

The physical model and economic assumptions are described in
[`simulation_methodology.md`](simulation_methodology.md). The
controller details are documented in
[`heuristic_dispatch.md`](heuristic_dispatch.md) and
[`lp_optimization.md`](lp_optimization.md).

These are simulated annual operating outcomes, not an investment assessment.

## Result Basis

The main study uses the complete hourly 2021 dataset and tests `250`, `500`,
`1000`, and `2000 kWh` batteries with heuristic and LP control. It covers fixed
surplus-only, dynamic surplus-only, and dynamic grid-charging operation. Its
`1000 kWh / 500 kW` dynamic grid-charging LP case is the **Core Reference
Case**: it has no terminal value and no passive losses. It is a comparison
anchor within the capacity study, not an economically optimal size. Shared
battery, tariff, metering, and validation assumptions are defined once in the
[simulation methodology](simulation_methodology.md).

Savings are measured against the matching no-battery price case: fixed-price
dispatch uses the fixed-price baseline, while both dynamic scenarios use the
dynamic-price baseline.

Later documents test one extension at a time: the [time-resolution
comparison](time_resolution_comparison.md) transfers the core reference case
to 15-minute data, the [terminal-value comparison](terminal_value_comparison.md)
adds terminal SOC valuation to that high-resolution anchor, and the
[passive-loss comparison](passive_loss_comparison.md) adds auxiliary demand and
self-discharge to the terminal-value configuration.

## Baseline Site Characteristics

Before adding a battery, the reconstructed site has:

| Metric | Baseline value |
|---|---:|
| Annual grid import | 1.24 GWh |
| Annual grid export | 102 MWh |
| Peak grid import | 450 kW |
| Local-generation self-consumption | 92.0% |
| Fixed-price annual net cost | 255.0k EUR |
| Dynamic-price annual net cost | 263.7k EUR |

The site already consumes most of its local PV and CHP generation directly.
Only about 8% is exported, so a surplus-only battery starts with a relatively
limited energy pool. This is why grid charging and price timing become
important for additional operating value.

## Strategy Comparison

![Annual operational savings by dispatch strategy for a 1000 kWh BESS](assets/strategy_comparison_1000kwh.png)

The `1000 kWh` case provides a representative comparison between dispatch
strategies.

| Method | Scenario | Annual operational savings | Surplus captured | Equivalent cycles | Runtime |
|---|---|---:|---:|---:|---:|
| Heuristic | Fixed surplus-only | 6.5k EUR | 75.6% | 69.9 | 0.4 s |
| LP | Fixed surplus-only | 6.5k EUR | 75.5% | 69.8 | 1.5 min |
| Heuristic | Dynamic surplus-only | 5.8k EUR | 67.5% | 62.4 | 4.4 s |
| LP | Dynamic surplus-only | 6.5k EUR | 74.7% | 69.1 | 1.6 min |
| Heuristic | Dynamic grid-charging | 9.4k EUR | 66.1% | 200.6 | 4.8 s |
| LP | Dynamic grid-charging | 13.3k EUR | 74.5% | 169.6 | 1.6 min |

All savings exclude BESS investment cost.

In fixed surplus-only operation, the heuristic is already effectively optimal:
it stores available surplus and uses it against later demand. The LP produces
almost the same result because there is little economic timing complexity when
every avoided import kWh has the same value. Small differences can remain from
rolling-horizon decisions and horizon-end effects.

Dynamic surplus-only dispatch gives the LP a modest advantage. At `1000 kWh`,
the LP improves annual operating savings by about `0.7k EUR` because it can
reserve stored surplus for more valuable deficit hours.

The largest controller difference appears when grid charging is enabled. The
LP improves annual operating savings by about `3.9k EUR` over the heuristic at
`1000 kWh`. It jointly considers charging cost, future demand, future surplus,
SOC, degradation, efficiency losses, and grid headroom rather than reacting to
price thresholds alone.

## Why The LP Creates More Arbitrage Value

The `1000 kWh` dynamic grid-charging case illustrates that buying at the lowest
average price is not sufficient for good arbitrage.

| Method | Average grid-charge price | Average discharge-hour price | Adjusted spread |
|---|---:|---:|---:|
| Heuristic | 0.185 EUR/kWh | 0.248 EUR/kWh | 0.012 EUR/kWh |
| LP | 0.209 EUR/kWh | 0.282 EUR/kWh | 0.021 EUR/kWh |

The heuristic grid-charges only when the current price falls below the rolling
20th-percentile threshold, so it purchases energy at a lower average price.
However, it discharges whenever the price crosses the rolling 80th-percentile
threshold and usable SOC is available. A locally high price can still be
moderate compared with a more expensive hour later in the horizon.

The LP sometimes accepts a higher charging price because it can see that the
stored energy will displace substantially more expensive imports later. It also
cycles less: about `170` equivalent cycles instead of `201` for the heuristic.
The resulting charge-discharge timing is more selective and produces roughly
twice the efficiency- and degradation-adjusted price spread.

The spread is an explanatory proxy. The dispatch output does not trace whether
each discharged kWh originally came from local surplus or grid charging.

## Capacity Sensitivity

![Annual operational savings by battery capacity](assets/capacity_sensitivity.png)

Dynamic grid charging with LP optimization produces the highest annual
operating savings at every tested capacity.

| Capacity | Annual operational savings | Additional savings | Marginal value of added capacity |
|---:|---:|---:|---:|
| 250 kWh | 5.1k EUR | - | - |
| 500 kWh | 8.6k EUR | 3.6k EUR | 14.2 EUR/kWh-year |
| 1000 kWh | 13.3k EUR | 4.7k EUR | 9.4 EUR/kWh-year |
| 2000 kWh | 17.6k EUR | 4.2k EUR | 4.2 EUR/kWh-year |

Total savings continue to increase, but the value of each additional installed
kWh declines sharply. Moving from `1000` to `2000 kWh` adds twice as much
capacity as the previous step while producing less additional annual savings.

The `2000 kWh` result is therefore useful as an upper sensitivity case. It does
not establish that this capacity is economically optimal because the experiment
does not include installed cost, financing, maintenance, replacement, or
project lifetime.

## Battery Utilization

![Surplus capture and equivalent cycles by battery capacity](assets/capacity_utilization.png)

For LP dynamic grid charging, increasing capacity raises the share of local
surplus captured from `32%` at `250 kWh` to `88%` at `2000 kWh`. At the same
time, equivalent annual cycles fall from about `243` to `114`.

This combination explains the diminishing returns:

- small batteries cannot absorb all available surplus, but their installed
  capacity is used frequently
- larger batteries capture more surplus and provide more scheduling freedom
- the additional capacity spends more time unused and cycles less often

The reported `soc_range_utilization` is `1.0` for every tested BESS run because
each battery reaches both ends of its usable SOC range at least once during the
year. That confirms full range access, but it is not a useful measure of how
intensively the battery is used. Equivalent cycles, throughput, and surplus
capture are more informative annual utilization metrics.

## 48-Hour Dispatch Example

![Heuristic and LP dispatch during a selected 48-hour period](assets/dispatch_rollout_48h.png)

The rollout shows the `1000 kWh` dynamic grid-charging case from October 6,
2021 at 03:00 through October 8, 2021 at 02:00. The reproducibly selected window
contains surplus, demand, grid charging, and discharge for both controllers.

The panels show:

1. remaining site demand above zero and available local surplus below zero
2. dynamic import price with the heuristic's rolling low/high thresholds
3. battery dispatch, where positive values are discharge and negative values
   are charging
4. usable battery SOC, normalized between the configured minimum and maximum

The heuristic reacts when prices cross its percentile thresholds. It can
therefore discharge at a price that is high relative to the current window but
still lower than a later price spike. The LP evaluates the economic value of
the complete horizon, so it can preserve energy for more valuable hours or
charge outside the heuristic's strict low-price classification when that
improves total horizon cost.

The chart is an explanatory example, not the basis of the annual conclusion.
Annual metrics aggregate all 8,760 simulated hours.

## Runtime Tradeoff

The heuristic completes a full annual scenario in approximately `0.4-4.8`
seconds, depending on whether price thresholds and future-surplus calculations
are required.

In the reported four-worker rerun, each hourly LP job took approximately
`1.5-1.6` minutes.
The model itself is small, but rolling hourly control builds and solves a new LP
for every one of the 8,760 simulation hours. Parallel experiment execution
reduces total wall-clock time across independent runs, but it does not reduce
the computational cost of an individual annual LP simulation.

This is an important engineering tradeoff: the LP provides a useful optimality
benchmark and better dynamic scheduling, while the heuristic is much cheaper
to execute and easier to explain.

## Validation and Scope

All reported runs pass the shared physical dispatch validator. The enforced
energy balances, SOC and power limits, price and metering rules, and full scope
limitations are documented in the [simulation
methodology](simulation_methodology.md#dispatch-contract). The separate
[time-resolution comparison](time_resolution_comparison.md), [terminal-value
comparison](terminal_value_comparison.md), and [passive-loss
comparison](passive_loss_comparison.md) quantify three important modeling
sensitivities.

## Main Conclusions

1. The site already self-consumes about `92%` of local generation, limiting the
   opportunity for surplus-only storage.
2. A simple heuristic is sufficient for fixed-price surplus-only dispatch; LP
   optimization adds little value in that case.
3. LP optimization is most valuable when grid charging and dynamic prices add
   real intertemporal tradeoffs.
4. Larger batteries increase savings and surplus capture, but utilization and
   marginal value decline with capacity.
5. The `1000 kWh` LP grid-charging case offers a strong operational result in
   this comparison, but economic sizing requires investment and lifetime-cost
   assumptions that are outside this experiment.
