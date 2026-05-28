"""Catalog of SMARD series used by the analysis pipeline."""

from dataclasses import dataclass
from src.smard_client import SmardConfig


@dataclass(frozen=True)
class SmardSeries:
    """Metadata and API configuration for one SMARD series."""

    series_name: str
    display_name: str
    category: str
    config: SmardConfig
    unit: str = "MWh"


DEFAULT_REGION = "DE-LU"
DEFAULT_RESOLUTION = "hour"


DAY_AHEAD_PRICE = SmardSeries(
    series_name="day_ahead_price",
    display_name="Day-ahead price",
    category="market_price",
    config=SmardConfig(
        smard_filter_id="4169",
        region=DEFAULT_REGION,
        resolution="hour",
    ),
    unit="EUR/MWh",
)
