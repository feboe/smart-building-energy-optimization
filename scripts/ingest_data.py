"""Ingest source data into PostgreSQL and recreate analysis views."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_database_config
from src.csv_pipeline import ingest_csv_archive
from src.database import (
    create_analysis_views,
    create_quality_views,
    create_tables,
    open_connection,
)
from src.smard_pipeline import DAY_AHEAD_PRICE, ingest_smard_series

ARCHIVE_PATH = PROJECT_ROOT / "data" / "reduced_data.zip"
RESOLUTION = "1h"
START_DATE = datetime(2021, 1, 1)
END_DATE = datetime(2021, 12, 31, 23)

RUN_CSV_INGEST = True
RUN_SMARD_INGEST = True
CREATE_VIEWS = True


def main() -> None:
    start_time = perf_counter()
    print("Starting data ingestion...")

    if RUN_CSV_INGEST:
        _ingest_csv_data()

    if RUN_SMARD_INGEST:
        _ingest_smard_data()

    if CREATE_VIEWS:
        _create_database_views()

    print(f"Data ingestion finished in {perf_counter() - start_time:.2f} seconds.")


def _ingest_csv_data() -> None:
    if not ARCHIVE_PATH.exists():
        raise FileNotFoundError(
            f"Missing source archive: {ARCHIVE_PATH}. "
            "Raw source data is not included in this repository."
        )

    print(f"Ingesting smart-company CSV archive: {ARCHIVE_PATH}")
    results = ingest_csv_archive(
        resolution=RESOLUTION,
        archive_path=ARCHIVE_PATH,
        start_date=START_DATE,
        end_date=END_DATE,
    )
    _print_csv_summary(results)


def _ingest_smard_data() -> None:
    print("Ingesting SMARD day-ahead prices...")
    result = ingest_smard_series(
        series=DAY_AHEAD_PRICE,
        start_date=START_DATE,
        end_date=END_DATE,
    )
    print(
        "SMARD import complete: "
        f"{result['measurement_row_count']:,} measurement rows inserted, "
        f"{result['processed_chunk_count']:,} chunks processed."
    )


def _create_database_views() -> None:
    print("Creating database tables, quality views, and analysis views...")
    database_config = load_database_config()
    with open_connection(database_config) as connection:
        create_tables(connection)
        create_quality_views(connection)
        create_analysis_views(connection)
    print("Database views are ready.")


def _print_csv_summary(results: dict[str, dict[str, dict[str, int | str]]]) -> None:
    table_count = len(results)
    series_count = sum(len(table_results) for table_results in results.values())
    measurement_row_count = sum(
        int(series_result["measurement_row_count"])
        for table_results in results.values()
        for series_result in table_results.values()
    )

    print(
        "CSV import complete: "
        f"{table_count:,} tables, "
        f"{series_count:,} series, "
        f"{measurement_row_count:,} measurement rows inserted."
    )


if __name__ == "__main__":
    main()
