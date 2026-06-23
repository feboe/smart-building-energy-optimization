# LP Optimization

The LP optimizer is the mathematical benchmark for the BESS dispatch problem.
It uses the same physical battery assumptions as the heuristic, but replaces
rule-based decisions with an explicit cost-minimization problem.

The model is not intended to be a full production EMS. It is a compact linear
program that shows how battery dispatch can be formulated mathematically for
dynamic electricity prices.

## Rolling Horizon

The optimizer uses a rolling horizon. At each simulation hour, it:

1. reads the current battery SOC
2. builds an optimization problem for the next horizon, usually 24 hours
3. solves the horizon with perfect foresight
4. executes only the first-hour decision
5. updates SOC and moves to the next hour

This is similar in spirit to model predictive control. The model can see the
future inside the horizon, but it does not commit to the full future plan. It
re-optimizes every hour.

Near the end of the dataset, the horizon is allowed to be shorter than the
configured horizon length.

## Notation

Let $t \in T$ index the hours in one optimization horizon.

Input parameters:

- $l_t$: demand after local generation in hour $t$
- $a_t$: available local surplus in hour $t$
- $p_t$: dynamic import price in EUR/kWh
- $p^{exp}$: export price in EUR/kWh
- $c^{deg}$: degradation cost per discharged kWh
- $\eta^{ch}$: charge efficiency
- $\eta^{dis}$: discharge efficiency
- $P^{ch}$: maximum battery charge power per hour
- $P^{dis}$: maximum battery discharge power per hour
- $S^{min}$ and $S^{max}$: minimum and maximum SOC
- $S_0$: SOC at the start of the horizon

Decision variables:

- $c^{sur}_t$: charge from local surplus
- $c^{grid}_t$: charge from the grid
- $d_t$: discharge to local load
- $g^{imp}_t$: grid import
- $g^{exp}_t$: grid export
- $s_t$: battery SOC at the end of hour $t$

All flow variables are nonnegative.

## Objective Function

The optimizer minimizes net operating cost over the horizon:

$$
\min \sum_{t \in T}
\left(
p_t g^{imp}_t
{}- p^{exp} g^{exp}_t
{}+ c^{deg} d_t
\right)
$$

The first term is grid import cost. The second term subtracts export revenue.
The third term adds the simple degradation proxy for discharged battery energy.

For the fixed-price scenario, $p_t$ is replaced by the fixed import price. For
dynamic scenarios, $p_t$ is the hourly dynamic import price.

## Energy Balance Constraints

The model separates deficit and surplus hours using precomputed inputs:

- $l_t$ is the load not covered by local generation
- $a_t$ is the local surplus after serving load

Remaining demand can be supplied by grid import or battery discharge:

$$
g^{imp}_t + d_t = l_t + c^{grid}_t
$$

This equation also accounts for grid charging. If the battery charges from the
grid, grid import increases by the same amount.

Local surplus is either stored in the battery or exported:

$$
g^{exp}_t = a_t - c^{sur}_t
$$

The battery never exports stored energy to the grid in this project. Export is
only leftover local surplus.

## Battery Constraints

Charging from surplus cannot exceed available surplus:

$$
0 \le c^{sur}_t \le a_t
$$

Discharge cannot exceed remaining local demand:

$$
0 \le d_t \le l_t
$$

Charge and discharge are limited by battery power:

$$
c^{sur}_t + c^{grid}_t \le P^{ch}
$$

$$
d_t \le P^{dis}
$$

SOC evolves with charge and discharge efficiency:

$$
s_t =
s_{t-1}
+ \eta^{ch}(c^{sur}_t + c^{grid}_t)
- \frac{d_t}{\eta^{dis}}
$$

For the first hour of the horizon, $s_{t-1}$ is the current simulation SOC
$S_0$.

SOC must stay within the battery limits:

$$
S^{min} \le s_t \le S^{max}
$$

## Scenario Switches

In surplus-only scenarios, grid charging is disabled:

$$
c^{grid}_t = 0
$$

In the dynamic grid-charging scenario, grid charging is allowed but capped by
the spare grid connection capacity after natural building demand:

$$
0 \le c^{grid}_t \le \max(P^{grid} - l_t, 0)
$$

Here $P^{grid}$ is the grid connection limit. The model does not shed natural
building demand if $l_t$ is already above the limit. It only prevents extra
battery charging from increasing import further.

## Why This Is an LP

All decision variables are continuous energy quantities. That is natural for an
hourly battery model: a battery can charge 12.4 kWh or discharge 3.7 kWh in an
hour.

The model does not include a binary charge/discharge mode variable. Adding that
would turn the problem into a mixed-integer linear program (MILP). A MILP could
forbid simultaneous charge and discharge directly, but it would be slower and
less useful as a first LP learning project.

Instead, the model relies on efficiency losses and degradation cost to make
unnecessary charge/discharge loops uneconomic. The final dispatch output is
also validated by the shared physical validator. If a future version requires
strict operating modes inside the optimization itself, a MILP formulation would
be the next step.

## Interpretation

The LP optimizer is best understood as a benchmark:

- it uses the same data and battery assumptions as the heuristic
- it makes decisions with an explicit objective
- it can trade off surplus capture, price arbitrage, degradation, and SOC
  constraints
- it is still simplified by perfect foresight and hourly resolution

This makes it suitable for comparing rule-based EMS behavior against a
mathematical optimization approach in a clear portfolio project.
