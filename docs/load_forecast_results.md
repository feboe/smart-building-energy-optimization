# Load Forecast Results

This document records the first load-forecast validation before the final 2021
test. It compares seasonal-naive baselines with a histogram gradient boosting
(HGB) model for hourly reconstructed gross load.

## Validation Setup

All forecasts use a 24-hour rolling horizon. The validation window is October
through December 2020, comprising 2,184 forecast origins and 52,416 forecast
rows per model. Daily Naive and Weekly Naive use the observed load from 24 and
168 hours earlier, respectively.

The HGB model uses the fixed initial configuration and leakage-safe load and
calendar features, including Hessian public holidays, bridge days, and the
observed annual company Christmas shutdown from 24 December through 2 January.
It was evaluated with two training windows:

| Training window | Trainable origins | Purpose |
|---|---:|---|
| January 2020 to September 2020 | 6,552 | Reference HGB run |
| 2019 H2 to September 2020 | 10,850 | Extended-history HGB run |

The extended window starts on 29 June 2019 local time, the first timestamp at
which PV, CHP, and total-load observations are complete. The 2021 data remains
outside training and model selection.

## Results

| Model | Training window | MAE | RMSE | Bias | WAPE |
|---|---|---:|---:|---:|---:|
| HGB | 2019 H2 to September 2020 | 22.10 kWh | 32.03 kWh | -0.06 kWh | 7.91% |
| HGB | January 2020 to September 2020 | 25.61 kWh | 38.03 kWh | +12.97 kWh | 9.16% |
| Weekly Naive | Seasonal naive | 36.81 kWh | 49.64 kWh | +6.47 kWh | 13.17% |
| Daily Naive | Seasonal naive | 42.10 kWh | 67.35 kWh | +1.66 kWh | 15.06% |

Adding 2019 H2 reduces HGB MAE by 13.7% and WAPE by 1.26 percentage points
relative to the reference HGB run. It also removes the material positive bias.
The added history supplies examples of autumn, Christmas, holidays, and bridge
days that are absent from the 2020-only target labels.

The Christmas-shutdown feature was evaluated as a controlled addition to the
extended-history HGB. It improves MAE from 22.74 kWh to 22.10 kWh, WAPE from
8.14% to 7.91%, and RMSE from 33.42 kWh to 32.03 kWh. The feature is derived
only from the target's local calendar date and is available at every forecast
origin.

## Decision

Use the extended 2019 H2 to September 2020 window for the next forecasting
experiments. Keep the 2021 test set untouched until feature and model choices
are fixed. The comparison and error diagnostics can be reproduced in
`notebooks/load_forecast_baselines.ipynb`.
