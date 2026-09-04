"""Build self-contained, time-resolved audit data for LP BESS dispatches."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pandas as pd

from src.battery.data import prepare_simulation_data
from src.battery.dispatch import max_charge_input_kwh, max_discharge_to_load_kwh
from src.battery.metrics import fixed_import_price
from src.battery.parameters import (
    FIXED_SURPLUS_ONLY,
    BatteryParameters,
    ScenarioParameters,
)


@dataclass(frozen=True)
class AuditExportConfig:
    """A prepared destination for immutable LP audit datasets.

    Construction is deliberately separated from experiment execution: a
    multi-resolution experiment validates its shared directory exactly once,
    before it starts any worker process.
    """

    dispatch_dir: Path


def create_audit_export_config(dispatch_dir: Path | None) -> AuditExportConfig | None:
    """Create an empty export directory and return its export configuration."""
    if dispatch_dir is None:
        return None
    directory = Path(dispatch_dir)
    if directory.exists():
        if not directory.is_dir():
            raise ValueError(f"dispatch_dir is not a directory: {directory}")
        if any(directory.iterdir()):
            raise ValueError(
                "dispatch_dir must be new or empty to prevent overwriting "
                f"existing exports: {directory}"
            )
    else:
        directory.mkdir(parents=True)
    return AuditExportConfig(dispatch_dir=directory)


def dispatch_export_path(
    audit_export: AuditExportConfig,
    resolution: str,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
) -> Path:
    """Return the collision-safe filename for one LP audit dataset."""
    filename = (
        f"lp_optimization__{resolution}__{battery.capacity_kwh:g}kwh"
        f"__{scenario.name}.parquet"
    )
    output_path = audit_export.dispatch_dir / filename
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite dispatch export: {output_path}")
    return output_path


def write_audit_parquet_atomically(audit_df: pd.DataFrame, output_path: Path) -> None:
    """Publish a Parquet audit dataset without exposing a partial file."""
    temporary_path = output_path.with_name(
        f".{output_path.stem}.{os.getpid()}.{uuid4().hex}.tmp.parquet"
    )
    try:
        audit_df.to_parquet(temporary_path, engine="pyarrow", index=False)
        # Linking publishes atomically and refuses a collision created by another
        # worker after the earlier existence check.
        os.link(temporary_path, output_path)
    except FileExistsError as exc:
        raise FileExistsError(
            f"Refusing to overwrite dispatch export: {output_path}"
        ) from exc
    except ImportError as exc:
        raise RuntimeError(
            "Parquet export requires pyarrow; install requirements.txt first."
        ) from exc
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def format_export_path(path: Path, project_root: Path) -> str:
    """Return a portable project-relative path when possible."""
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def build_lp_audit_dataframe(
    analysis_df: pd.DataFrame,
    dispatch_df: pd.DataFrame,
    battery: BatteryParameters,
    scenario: ScenarioParameters,
    run_timestamp: str,
) -> pd.DataFrame:
    """Return one self-contained audit row per executed LP decision.

    ``dispatch_df`` must have been produced with horizon diagnostics enabled.
    The function is intentionally separate from the optimizer: audit columns
    observe the executed result, never participate in the LP objective.
    """
    required_diagnostics = {
        "planning_horizon_steps",
        "planning_horizon_end_timestamp",
        "planned_terminal_soc_kwh",
    }
    missing_diagnostics = sorted(required_diagnostics - set(dispatch_df.columns))
    if missing_diagnostics:
        raise ValueError(
            "Dispatch diagnostics are required for an audit export: "
            f"{missing_diagnostics}"
        )

    prepared_df = prepare_simulation_data(analysis_df, scenario).reset_index(drop=True)
    dispatch = dispatch_df.reset_index(drop=True).copy()
    if len(prepared_df) != len(dispatch):
        raise ValueError("analysis_df and dispatch_df must have the same row count.")
    if not prepared_df["observation_timestamp"].equals(dispatch["observation_timestamp"]):
        raise ValueError("analysis_df and dispatch_df timestamps must match.")

    timestep_hours = dispatch["timestep_hours"].astype(float)
    fixed_price = fixed_import_price(prepared_df, scenario)
    if scenario.dispatch_strategy == FIXED_SURPLUS_ONLY:
        used_import_price = pd.Series(fixed_price, index=dispatch.index, dtype=float)
        price_model = "fixed"
    else:
        used_import_price = prepared_df["dynamic_import_price_eur_per_kwh"].astype(float)
        price_model = "dynamic"

    baseline_import_kwh = prepared_df["grid_import_kwh"].astype(float)
    baseline_export_kwh = prepared_df["grid_export_kwh"].astype(float)
    grid_import_kwh = dispatch["grid_import_kwh"].astype(float)
    grid_export_kwh = dispatch["grid_export_kwh"].astype(float)
    discharge_kwh = dispatch["discharge_to_load_kwh"].astype(float)
    battery_charge_kwh = dispatch["battery_charge_kwh"].astype(float)

    grid_import_cost_eur = grid_import_kwh * used_import_price
    grid_export_revenue_eur = grid_export_kwh * scenario.export_price_eur_per_kwh
    degradation_cost_eur = discharge_kwh * battery.degradation_cost_eur_per_kwh
    electricity_net_cost_eur = grid_import_cost_eur - grid_export_revenue_eur
    net_cost_eur = electricity_net_cost_eur + degradation_cost_eur
    baseline_net_cost_eur = (
        baseline_import_kwh * used_import_price
        - baseline_export_kwh * scenario.export_price_eur_per_kwh
    )

    charge_input_available_kwh = pd.Series(
        [
            max_charge_input_kwh(float(soc), battery, float(dt))
            for soc, dt in zip(dispatch["soc_start_kwh"], timestep_hours)
        ],
        index=dispatch.index,
        dtype=float,
    )
    discharge_available_kwh = pd.Series(
        [
            max_discharge_to_load_kwh(float(soc), battery, float(dt))
            for soc, dt in zip(dispatch["soc_start_kwh"], timestep_hours)
        ],
        index=dispatch.index,
        dtype=float,
    )
    charge_power_limit_kwh = battery.max_charge_power_kw * timestep_hours
    discharge_power_limit_kwh = battery.max_discharge_power_kw * timestep_hours
    if scenario.grid_connection_limit_kw is None:
        grid_connection_headroom_kwh = pd.Series(math.nan, index=dispatch.index)
    else:
        grid_connection_headroom_kwh = (
            scenario.grid_connection_limit_kw * timestep_hours - grid_import_kwh
        ).clip(lower=0)

    audit = pd.DataFrame(
        {
            "run_timestamp": run_timestamp,
            "observation_timestamp": prepared_df["observation_timestamp"],
            "local_timestamp": prepared_df["local_timestamp"],
            "resolution": prepared_df["resolution"],
            "timestep_hours": timestep_hours,
            "method": "lp_optimization",
            "scenario": scenario.name,
            "dispatch_strategy": scenario.dispatch_strategy,
            "price_model": price_model,
            "gross_load_kw": prepared_df["gross_load_kw"],
            "gross_load_kwh": prepared_df["gross_load_kwh"],
            "pv_generation_kw": prepared_df["pv_generation_kw"],
            "pv_generation_kwh": prepared_df["pv_generation_kwh"],
            "chp_generation_kw": prepared_df["chp_generation_kw"],
            "chp_generation_kwh": prepared_df["chp_generation_kwh"],
            "local_generation_kw": prepared_df["local_generation_kw"],
            "local_generation_kwh": prepared_df["local_generation_kwh"],
            "available_surplus_kwh": prepared_df["available_surplus_kwh"],
            "available_surplus_kw": prepared_df["available_surplus_kwh"]
            / timestep_hours,
            "demand_after_generation_kwh": prepared_df[
                "demand_after_generation_kwh"
            ],
            "demand_after_generation_kw": prepared_df[
                "demand_after_generation_kwh"
            ]
            / timestep_hours,
            "day_ahead_price_eur_per_kwh": prepared_df[
                "day_ahead_price_eur_per_kwh"
            ],
            "import_markup_eur_per_kwh": scenario.import_markup_eur_per_kwh,
            "dynamic_import_price_eur_per_kwh": prepared_df[
                "dynamic_import_price_eur_per_kwh"
            ],
            "fixed_import_price_eur_per_kwh": fixed_price,
            "used_import_price_eur_per_kwh": used_import_price,
            "export_price_eur_per_kwh": scenario.export_price_eur_per_kwh,
            "capacity_kwh": battery.capacity_kwh,
            "max_charge_power_kw": battery.max_charge_power_kw,
            "max_discharge_power_kw": battery.max_discharge_power_kw,
            "charge_c_rate": battery.charge_c_rate,
            "discharge_c_rate": battery.discharge_c_rate,
            "min_soc_kwh": battery.min_soc_kwh,
            "max_soc_kwh": battery.max_soc_kwh,
            "min_soc_fraction": battery.min_soc_fraction,
            "max_soc_fraction": battery.max_soc_fraction,
            "eta_charge": battery.eta_charge,
            "eta_discharge": battery.eta_discharge,
            "degradation_cost_eur_per_kwh": battery.degradation_cost_eur_per_kwh,
            "grid_connection_limit_kw": scenario.grid_connection_limit_kw,
            "planning_horizon_hours": scenario.horizon_hours,
            "terminal_value_window_hours": scenario.terminal_value_window_hours,
            "surplus_reserve_fraction": scenario.surplus_reserve_fraction,
            "low_price_quantile": scenario.low_price_quantile,
            "high_price_quantile": scenario.high_price_quantile,
            "charge_from_surplus_kwh": dispatch["charge_from_surplus_kwh"],
            "charge_from_grid_kwh": dispatch["charge_from_grid_kwh"],
            "battery_charge_kwh": battery_charge_kwh,
            "discharge_to_load_kwh": discharge_kwh,
            "grid_import_kwh": grid_import_kwh,
            "grid_export_kwh": grid_export_kwh,
            "charge_from_surplus_kw": dispatch["charge_from_surplus_kwh"] / timestep_hours,
            "charge_from_grid_kw": dispatch["charge_from_grid_kwh"] / timestep_hours,
            "battery_charge_kw": battery_charge_kwh / timestep_hours,
            "discharge_to_load_kw": discharge_kwh / timestep_hours,
            "grid_import_kw": grid_import_kwh / timestep_hours,
            "grid_export_kw": grid_export_kwh / timestep_hours,
            "soc_start_kwh": dispatch["soc_start_kwh"],
            "soc_end_kwh": dispatch["soc_end_kwh"],
            "soc_start_pct": dispatch["soc_start_kwh"] / battery.capacity_kwh * 100,
            "soc_end_pct": dispatch["soc_end_kwh"] / battery.capacity_kwh * 100,
            "grid_import_cost_eur": grid_import_cost_eur,
            "grid_export_revenue_eur": grid_export_revenue_eur,
            "battery_degradation_cost_eur": degradation_cost_eur,
            "electricity_net_cost_eur": electricity_net_cost_eur,
            "net_cost_eur": net_cost_eur,
            "baseline_grid_import_kwh": baseline_import_kwh,
            "baseline_grid_export_kwh": baseline_export_kwh,
            "baseline_grid_import_cost_eur": baseline_import_kwh * used_import_price,
            "baseline_grid_export_revenue_eur": (
                baseline_export_kwh * scenario.export_price_eur_per_kwh
            ),
            "baseline_net_cost_eur": baseline_net_cost_eur,
            "cost_savings_eur": baseline_net_cost_eur - net_cost_eur,
            "available_charge_input_kwh_before": charge_input_available_kwh,
            "available_discharge_to_load_kwh_before": discharge_available_kwh,
            "remaining_charge_power_headroom_kwh": (
                charge_power_limit_kwh - battery_charge_kwh
            ).clip(lower=0),
            "remaining_discharge_power_headroom_kwh": (
                discharge_power_limit_kwh - discharge_kwh
            ).clip(lower=0),
            "remaining_soc_charge_headroom_kwh": battery.max_soc_kwh
            - dispatch["soc_end_kwh"],
            "remaining_soc_discharge_headroom_kwh": dispatch["soc_end_kwh"]
            - battery.min_soc_kwh,
            "remaining_grid_connection_headroom_kwh": grid_connection_headroom_kwh,
        }
    )
    audit["remaining_soc_charge_headroom_kwh"] = audit[
        "remaining_soc_charge_headroom_kwh"
    ].clip(lower=0)
    audit["remaining_soc_discharge_headroom_kwh"] = audit[
        "remaining_soc_discharge_headroom_kwh"
    ].clip(lower=0)
    diagnostic_columns = [
        "planning_horizon_steps",
        "planning_horizon_duration_hours",
        "planning_horizon_end_timestamp",
        "solver_status",
        "terminal_reference_price_eur_per_kwh",
        "terminal_value_eur_per_kwh_soc",
        "planned_terminal_soc_kwh",
        "planned_terminal_usable_soc_kwh",
        "planned_terminal_value_eur",
        "horizon_operating_cost_eur",
        "horizon_terminal_credit_eur",
        "horizon_objective_eur",
    ]
    return pd.concat([audit, dispatch[diagnostic_columns]], axis=1)
