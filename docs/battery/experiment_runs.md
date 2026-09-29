# BESS Experiment Runbook

This runbook reproduces the published battery experiment chain. Run the
commands from the repository root after completing the project setup in the
[README](../../README.md#quick-start).

The sequence separates the historical hourly reference from later model
extensions:

1. hourly capacity study and Core Reference Case
2. hourly-to-15-minute resolution comparison without terminal value
3. 15-minute terminal-value A/B comparison
4. passive-loss sensitivity on the terminal-value configuration

`--days 365` selects the complete 365-day dataset at each requested resolution.
Summary CSV files and LP audit directories use explicit experiment names so
that results from different stages cannot be confused.

## 1. Core Reference and Capacity Study

This run covers `250`, `500`, `1000`, and `2000 kWh` at hourly resolution. The
`1000 kWh / 500 kW` dynamic grid-charging LP result is the Core Reference Case.
Terminal value and passive losses are disabled.

```bash
python scripts/battery/run_capacity_analysis.py
```

Output:

```text
results/battery/capacity_analysis__hour__2021.csv
```

## 2. Time-Resolution Comparison

This run transfers the terminal-value-free `1000 kWh` reference configuration
from hourly to 15-minute data. Its 15-minute result is the High-Resolution
Comparison Anchor.

```bash
python scripts/battery/run_bess_simulation.py \
  --resolutions hour 15min \
  --capacities-kwh 1000 \
  --days 365 \
  --experiment-name time_resolution__none__hour_15min__1000kwh__2021 \
  --output results/battery/time_resolution__none__hour_15min__1000kwh__2021.csv
```

## 3. Terminal-Value Comparison

First reproduce the 15-minute anchor and export its LP dispatch audits:

```bash
python scripts/battery/run_bess_simulation.py \
  --resolutions 15min \
  --capacities-kwh 1000 \
  --days 365 \
  --experiment-name terminal_value__disabled__15min__1000kwh__2021 \
  --dispatch-dir results/battery/dispatch/terminal_value__disabled__15min__1000kwh__2021 \
  --output results/battery/terminal_value__disabled__15min__1000kwh__2021.csv
```

Then enable the four-hour terminal-value window while keeping every other
setting unchanged:

```bash
python scripts/battery/run_bess_simulation.py \
  --resolutions 15min \
  --capacities-kwh 1000 \
  --days 365 \
  --terminal-value-window-hours 4 \
  --experiment-name terminal_value__4h__15min__1000kwh__2021 \
  --dispatch-dir results/battery/dispatch/terminal_value__4h__15min__1000kwh__2021 \
  --output results/battery/terminal_value__4h__15min__1000kwh__2021.csv
```

The two audit directories are required to reproduce the planned terminal-SOC
comparison.

## 4. Passive-Loss Sensitivity

This run retains the four-hour terminal value and adds `2.5 kW` constant
auxiliary demand plus `1%` self-discharge per 30-day month.

```bash
python scripts/battery/run_bess_simulation.py \
  --resolutions 15min \
  --capacities-kwh 1000 \
  --days 365 \
  --terminal-value-window-hours 4 \
  --standby-power-kw 2.5 \
  --self-discharge-rate-per-month 0.01 \
  --experiment-name passive_losses__2_5kw_1pct__15min__1000kwh__2021 \
  --output results/battery/passive_losses__2_5kw_1pct__15min__1000kwh__2021.csv
```

## Result Interpretation

The [main experiment results](experiment_results.md) describe the Core
Reference Case and capacity study. Separate documents interpret the
[time-resolution](time_resolution_comparison.md),
[terminal-value](terminal_value_comparison.md), and
[passive-loss](passive_loss_comparison.md) comparisons. Shared assumptions and
the dispatch contract remain centralized in the [simulation
methodology](simulation_methodology.md).

Large generated CSV, Parquet, and dispatch artifacts remain ignored by Git.
Only compact documentation assets intended for publication should be added to
the repository.
