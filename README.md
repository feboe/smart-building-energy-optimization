# Plan

## Cases

1. Surplus-only BESS

    - battery can only charge from local surplus
    - battery discharges to reduce grid import
    - compare fixed-price vs dynamic-price cost outcomes
    - this mostly test self consumption value

2. Surplus + grid-charging BESS

    - battery can charge from local surplus and from grid
    - discharges in expensive/import hours
    - this tests dynamic-price arbitrage plus self-consumption

3. For each compare:

    - heuristic dispatch
    - optimization dispatch
    - different battery sizes
    - different export prices

## Assumptions

- rolling optimization
  - +24h horizon
  - hourly decision making for the next 24h
  - perfect foresight as optimal baseline

- prices
  - dynamic import price = day-ahead price + assumed import markup
  - fixed import price = mean(dynamic import price)
  - ficed export price = scenario variable

- battery
  - capacity_kwh: [250, 500, 1000, 2000]
  - c_rate: 0.5 or 1.0
  - min_soc = 10%
  - max_soc = 100%
  - eta_charge = 0.95
  - eta_discharge = 0.95
  - only discharges to load
  - ignore wear and tear costs

## Problem Formulation

1. Decision Variables

    - charge battery from grid (kWh)
    - charge battery from surplus (kWh)
    - discharge battery to load (kWh)
    - export to grid (kWh)
    - import from grid (kWh)
    - soc (kWh)

2. Constraints

    - generation pv + generation chp + grid import + battery discharge = total load + battery charge + grid export
    - battery soc cant be lower than 10% or higher than 100% of capacity (kWh)
    - enable grid charge for different cases (charge from grid = 0)
    - charge from surplus cant be higher than surplus (charge from surplus <= surplus)

3. Objectives

    - minimize effective cost per load (net annual cost/total building load)

## Heuristic

- charge battery from surplus as highest priority
- discharge battery if price is 75th percentile of known forecast prices
- charge battery from grid if price is 25th percentile of known forecast prices (only in second scenario)
- only do grid export if storage is at 100%
- indirect optimization of costs with rules

## Neglected

- battery can only discharge or charge as a hard constraint
