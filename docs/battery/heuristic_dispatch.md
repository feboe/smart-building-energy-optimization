# Heuristic Dispatch

The heuristic dispatch is the rule-based EMS baseline in this project. It is
designed to be transparent and easy to inspect. It is not meant to be optimal.

The purpose of the heuristic is to answer a practical question:

> How far can a simple, explainable controller get before introducing a
> mathematical optimizer?

The LP optimizer in [`lp_optimization.md`](lp_optimization.md) uses the same
physical battery model and dispatch output contract, but optimizes decisions
with an explicit objective function.

## Shared Dispatch Order

Each hour, the heuristic sees:

- available local surplus after serving load
- remaining demand after local generation
- current battery SOC
- current and near-future dynamic prices
- scenario parameters such as grid-charging permission and grid connection
  limit

The controller follows a fixed order:

1. charge from local surplus when surplus exists
2. decide whether to discharge to serve load
3. decide whether to charge from the grid
4. export leftover surplus
5. import any remaining demand from the grid

This order is simple and physically intuitive. It also means that the heuristic
does not solve a global planning problem. It reacts to rules hour by hour.

## Fixed Surplus-Only Heuristic

In the fixed-price surplus-only scenario, the battery cannot charge from the
grid. It only stores local surplus.

The rules are:

- charge from local surplus whenever surplus is available
- discharge whenever there is remaining demand and usable SOC is available
- export surplus only when the battery cannot absorb more
- import from the grid only after local generation and battery discharge are
  insufficient

This is a strong baseline for self-consumption. Because the import price is
fixed, every avoided grid-import kWh has the same value. There is no reason to
wait for a later high-price hour.

## Dynamic Surplus-Only Heuristic

In the dynamic surplus-only scenario, the battery still cannot charge from the
grid. The difference is discharge timing.

Instead of discharging into every deficit hour, the heuristic compares the
current price with prices in the rolling horizon:

- low-price threshold: 20th percentile of horizon prices
- high-price threshold: 80th percentile of horizon prices

The battery charges from surplus as usual, but it only discharges when the
current price is high relative to the horizon.

This rule tries to reserve stored surplus energy for expensive hours. It is a
simple price-aware strategy, but it can miss opportunities because it uses
thresholds rather than an explicit cost-minimizing objective.

## Dynamic Grid-Charging Heuristic

The grid-charging scenario adds one more option: the battery can charge from the
grid in low-price hours.

The rules are:

- charge from local surplus first
- discharge in high-price hours
- charge from the grid in low-price hours
- do not grid charge and discharge in the same hour
- cap additional grid charging by the grid connection limit
- reserve headroom for expected future surplus in the horizon

The future-surplus reservation is intentionally conservative. If surplus is
expected later in the rolling horizon, the heuristic limits grid charging so
that some battery capacity remains available for local generation.

This protects self-consumption, but it is still a rough rule. It does not model
all possible future discharge before that surplus arrives. The LP optimizer can
make that tradeoff more directly.

## Grid Connection Limit

The grid connection limit applies only to extra grid charging. Natural building
import is never shed in this simplified model.

For example, if the grid connection limit is 500 kW and the building already
needs 350 kWh from the grid in that hour, the heuristic can add at most 150 kWh
of grid charging:

```text
extra_grid_charge_limit = max(grid_connection_limit - natural_deficit, 0)
```

If the natural building deficit already exceeds the connection limit, the model
still imports the natural deficit. It simply prevents additional battery grid
charging in that hour.

## What the Heuristic Shows

The heuristic is useful because it is:

- transparent
- fast
- physically validated
- easy to compare with the LP optimizer

It also creates a fair baseline for a portfolio project. The heuristic captures
the main economic ideas:

- store local surplus
- discharge when energy is valuable
- grid charge only when prices are low
- protect some capacity for future surplus

The comparison with the LP optimizer is not meant to show that the heuristic is
"bad". It shows the value of replacing simple thresholds with an explicit
optimization problem when prices and future constraints matter.

## Limitations

The heuristic has known limitations:

- price thresholds are coarse
- future surplus reservation is conservative
- no explicit objective function is optimized
- no perfect tradeoff between surplus capture, arbitrage, and degradation
- no battery export to grid
- no forecast uncertainty

These limitations are intentional. They keep the heuristic understandable and
make it a useful baseline for the LP model.
