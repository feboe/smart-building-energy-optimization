"""Transform SMARD API payloads into database-ready records."""

from datetime import datetime, timezone

import pandas as pd

from src.smard_catalog import SmardSeries

SOURCE_SYSTEM = "SMARD"
MEASUREMENT_COLUMNS = [
    "import_id",
    "source_system",
    "source_series_id",
    "series_name",
    "category",
    "region",
    "resolution",
    "unit",
    "observation_timestamp",
    "value",
]


def timestamp_ms_to_datetime(timestamp: int) -> datetime:
    """Convert a Unix timestamp in milliseconds to a UTC datetime."""
    return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)


def extract_measurements(
    payload: dict,
    import_id: int,
    series: SmardSeries,
) -> pd.DataFrame:
    """Extract normalized measurement rows from a SMARD payload."""

    if "series" not in payload:
        raise ValueError("Payload does not contain 'series' key")

    df = pd.DataFrame(payload["series"], columns=["timestamp_ms", "value"])
    df["import_id"] = import_id
    df["source_system"] = SOURCE_SYSTEM
    df["source_series_id"] = series.config.smard_filter_id
    df["series_name"] = series.series_name
    df["category"] = series.category
    df["region"] = series.config.region
    df["resolution"] = series.config.resolution
    df["unit"] = series.unit
    df["observation_timestamp"] = df["timestamp_ms"].apply(
        timestamp_ms_to_datetime
    )
    return df[MEASUREMENT_COLUMNS]
