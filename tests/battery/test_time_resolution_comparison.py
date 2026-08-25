"""Integration checks for the short time-resolution comparison runner."""

from scripts.run_time_resolution_comparison import (
    run_time_resolution_comparison,
    select_time_window,
)


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

    result_df = run_time_resolution_comparison(
        {"hour": hourly_df, "15min": quarter_hour_df},
        capacities_kwh=[1000],
        run_timestamp="2021-01-01T00:00:00+00:00",
        max_workers=1,
    )

    assert len(result_df) == 16
    assert set(result_df["resolution"]) == {"hour", "15min"}
    assert set(result_df["timestep_hours"]) == {0.25, 1.0}
    assert set(result_df["method"]) == {"baseline", "heuristic", "lp_optimization"}
    assert set(result_df["experiment_name"]) == {"time_resolution_comparison"}


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
