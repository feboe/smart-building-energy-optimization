"""Integration checks for direct multi-resolution BESS simulations."""

from scripts.battery.run_bess_simulation import run_bess_simulation, select_time_window


def test_resolution_comparison_contains_all_standard_methods(
    make_analysis_df,
) -> None:
    hourly_df = make_analysis_df(
        [
            {"total_w": -50_000, "pv_w": -100_000},
            {"total_w": 50_000, "day_ahead_price_eur_per_kwh": 0.5},
        ]
    )
    quarter_hour_df = make_analysis_df(
        [
            {
                "resolution": "15min",
                "timestep_hours": 0.25,
                "total_w": -50_000,
                "pv_w": -100_000,
            },
            {
                "resolution": "15min",
                "timestep_hours": 0.25,
                "total_w": 50_000,
                "day_ahead_price_eur_per_kwh": 0.5,
            },
        ]
    )

    result_df = run_bess_simulation(
        {"hour": hourly_df, "15min": quarter_hour_df},
        capacities_kwh=[1000],
        run_timestamp="2021-01-01T00:00:00+00:00",
        max_workers=1,
    )

    assert len(result_df) == 16
    assert set(result_df["resolution"]) == {"hour", "15min"}
    assert set(result_df["timestep_hours"]) == {0.25, 1.0}
    assert set(result_df["method"]) == {"baseline", "heuristic", "lp_optimization"}
    assert set(result_df["experiment_name"]) == {"bess_simulation"}
    assert set(result_df["terminal_value_window_hours"]) == {4.0}
    assert result_df.loc[
        result_df["method"] == "lp_optimization", "terminal_value_applied"
    ].all()
    assert not result_df.loc[
        result_df["method"] != "lp_optimization", "terminal_value_applied"
    ].any()
    assert list(result_df.columns).index("capacity_kwh") < list(result_df.columns).index(
        "max_charge_power_kw"
    )
    assert list(result_df.columns).index("max_charge_power_kw") < list(
        result_df.columns
    ).index("max_discharge_power_kw")
    assert list(result_df.columns).index("max_discharge_power_kw") < list(
        result_df.columns
    ).index("charge_c_rate")
    assert list(result_df.columns).index("charge_c_rate") < list(result_df.columns).index(
        "discharge_c_rate"
    )
    bess_rows = result_df[result_df["method"] != "baseline"]
    baseline_rows = result_df[result_df["method"] == "baseline"]
    assert set(bess_rows["max_charge_power_kw"]) == {500.0}
    assert set(bess_rows["max_discharge_power_kw"]) == {500.0}
    assert set(bess_rows["charge_c_rate"]) == {0.5}
    assert set(bess_rows["discharge_c_rate"]) == {0.5}
    assert baseline_rows["max_charge_power_kw"].isna().all()
    assert baseline_rows["max_discharge_power_kw"].isna().all()
    assert baseline_rows["charge_c_rate"].isna().all()
    assert baseline_rows["discharge_c_rate"].isna().all()
    hourly_result = result_df[result_df["resolution"] == "hour"]
    quarter_hour_result = result_df[result_df["resolution"] == "15min"]
    assert set(hourly_result["analysis_start_utc"]) == {"2021-01-01T00:00:00+00:00"}
    assert set(hourly_result["analysis_end_utc_exclusive"]) == {
        "2021-01-01T02:00:00+00:00"
    }
    assert set(hourly_result["simulation_rows"]) == {2}
    assert set(quarter_hour_result["analysis_end_utc_exclusive"]) == {
        "2021-01-01T00:30:00+00:00"
    }
    assert set(quarter_hour_result["simulation_rows"]) == {2}


def test_select_time_window_uses_a_common_half_open_period(make_analysis_df) -> None:
    analysis_df = make_analysis_df([{} for _ in range(8)])

    selected_df = select_time_window(
        analysis_df,
        start="2021-01-01T02:00:00Z",
        end="2021-01-01T05:00:00Z",
        days=7,
    )

    assert len(selected_df) == 3
    assert selected_df["observation_timestamp"].iloc[0].hour == 2
