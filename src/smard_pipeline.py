"""Ingestion flow for loading selected SMARD series into PostgreSQL."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import load_database_config
from src.database import (
    create_tables,
    insert_import,
    insert_measurements,
    open_connection,
)
from src.smard_catalog import SmardSeries
from src.smard_client import build_index_url, get_payload, get_timestamps
from src.transform_smard import (
    SOURCE_SYSTEM,
    extract_measurements,
    timestamp_ms_to_datetime,
)

LOCAL_TIMEZONE = ZoneInfo("Europe/Berlin")


def normalize_datetime_to_utc(value: datetime) -> datetime:
    """Normalize a naive or aware datetime to UTC for API and database filtering."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TIMEZONE)

    return value.astimezone(timezone.utc)


def filter_chunk_timestamps(
    available_timestamps: list[int],
    start_date: datetime,
    end_date: datetime | None = None,
) -> list[int]:
    """Select SMARD payload chunks that overlap the requested time range."""
    start_utc = normalize_datetime_to_utc(start_date)
    end_utc = normalize_datetime_to_utc(end_date) if end_date is not None else None

    if end_utc is not None and end_utc < start_utc:
        raise ValueError("end_date must be greater than or equal to start_date.")

    sorted_timestamps = sorted(available_timestamps)
    selected_timestamps: list[int] = []

    for index, timestamp_ms in enumerate(sorted_timestamps):
        chunk_start = timestamp_ms_to_datetime(timestamp_ms)
        next_chunk_start = None

        if index + 1 < len(sorted_timestamps):
            next_chunk_start = timestamp_ms_to_datetime(sorted_timestamps[index + 1])

        overlaps_start = next_chunk_start is None or next_chunk_start > start_utc
        overlaps_end = end_utc is None or chunk_start <= end_utc

        if overlaps_start and overlaps_end:
            selected_timestamps.append(timestamp_ms)

    return selected_timestamps


def filter_measurements_for_period(
    measurements_df: pd.DataFrame,
    start_date: datetime,
    end_date: datetime | None = None,
) -> pd.DataFrame:
    """Filter normalized measurements to the requested inclusive time range."""
    start_utc = normalize_datetime_to_utc(start_date)
    mask = measurements_df["observation_timestamp"] >= start_utc

    if end_date is not None:
        end_utc = normalize_datetime_to_utc(end_date)
        mask &= measurements_df["observation_timestamp"] <= end_utc

    return measurements_df.loc[mask].reset_index(drop=True)


def build_import_metadata(
    series: SmardSeries,
    start_date: datetime,
    end_date: datetime | None,
    selected_timestamps: list[int],
) -> dict:
    """Build compact provenance metadata for one SMARD import."""
    start_utc = normalize_datetime_to_utc(start_date)
    end_utc = normalize_datetime_to_utc(end_date) if end_date is not None else None

    return {
        "filter_id": series.config.smard_filter_id,
        "display_name": series.display_name,
        "category": series.category,
        "region": series.config.region,
        "resolution": series.config.resolution,
        "unit": series.unit,
        "requested_start": start_utc.isoformat(),
        "requested_end": end_utc.isoformat() if end_utc is not None else None,
        "selected_chunk_count": len(selected_timestamps),
        "selected_chunk_timestamps_ms": selected_timestamps,
    }


def ingest_smard_series(
    series: SmardSeries,
    start_date: datetime,
    end_date: datetime | None = None,
) -> dict[str, int]:
    """Fetch, transform, and insert one SMARD series for a time range."""
    database_config = load_database_config()
    available_timestamps = get_timestamps(series.config)
    selected_timestamps = filter_chunk_timestamps(
        available_timestamps=available_timestamps,
        start_date=start_date,
        end_date=end_date,
    )

    processed_chunk_count = 0
    measurement_row_count = 0

    with open_connection(database_config) as connection:
        create_tables(connection)
        import_id = insert_import(
            connection=connection,
            source_system=SOURCE_SYSTEM,
            import_name=series.series_name,
            source_path=build_index_url(series.config),
            resolution=series.config.resolution,
            metadata=build_import_metadata(
                series=series,
                start_date=start_date,
                end_date=end_date,
                selected_timestamps=selected_timestamps,
            ),
        )

        for timestamp_ms in selected_timestamps:
            payload = get_payload(series.config, timestamp_ms)

            measurements_df = extract_measurements(
                payload=payload,
                import_id=import_id,
                series=series,
            )
            filtered_measurements_df = filter_measurements_for_period(
                measurements_df=measurements_df,
                start_date=start_date,
                end_date=end_date,
            )

            if not filtered_measurements_df.empty:
                inserted_row_count = insert_measurements(
                    connection,
                    filtered_measurements_df,
                )
                measurement_row_count += inserted_row_count

            processed_chunk_count += 1

    return {
        "import_id": import_id,
        "processed_chunk_count": processed_chunk_count,
        "measurement_row_count": measurement_row_count,
        "selected_chunk_count": len(selected_timestamps),
    }


def ingest_smard_series_batch(
    series_batch: dict[str, SmardSeries],
    start_date: datetime,
    end_date: datetime | None = None,
) -> dict[str, dict[str, int]]:
    """Ingest a mapping of SMARD series and collect per-series load counts."""
    results = {}

    for series_name, series in series_batch.items():
        results[series_name] = ingest_smard_series(
            series=series,
            start_date=start_date,
            end_date=end_date,
        )

    return results
