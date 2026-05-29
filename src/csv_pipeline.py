"""Ingestion flow for loading smart-company CSV time series into PostgreSQL."""

from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile
from zoneinfo import ZoneInfo
import gzip

import pandas as pd

from src.config import load_database_config
from src.database import (
    MEASUREMENT_COLUMNS,
    create_tables,
    insert_import,
    insert_measurements,
    open_connection,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARCHIVE_PATH = PROJECT_ROOT / "data" / "reduced_data.zip"
SOURCE_SYSTEM = "SMART_COMPANY"
DEFAULT_REGION = "smart_company_building"
LOCAL_TIMEZONE = ZoneInfo("Europe/Berlin")

WEATHER_UNITS = {
    "WeatherStation.Weather.Igm": "W/m2",
    "WeatherStation.Weather.Ta": "degC",
}
RESOLUTION_UNITS = {
    "1h": "hour",
}


def normalize_datetime_to_utc(value: datetime) -> datetime:
    """Normalize a naive or aware datetime to UTC for filtering."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TIMEZONE)

    return value.astimezone(timezone.utc)


def normalize_resolution(resolution: str) -> str:
    """Normalize source archive resolution names for database storage."""
    return RESOLUTION_UNITS.get(resolution, resolution)


def build_member_path(resolution: str, table_name: str) -> str:
    """Build the archive member path for a CSV table."""
    return f"reduced_data/{resolution}/{table_name}.csv.gz"


def list_csv_tables(
    archive_path: Path = DEFAULT_ARCHIVE_PATH,
    resolution: str | None = None,
) -> list[str]:
    """List available CSV table names in the archive."""
    with ZipFile(archive_path) as archive:
        members = [member for member in archive.namelist() if member.endswith(".csv.gz")]

    if resolution is not None:
        prefix = f"reduced_data/{resolution}/"
        members = [member for member in members if member.startswith(prefix)]

    return sorted({Path(member).name.removesuffix(".csv.gz") for member in members})


def read_csv_table(
    table_name: str,
    resolution: str = "1h",
    archive_path: Path = DEFAULT_ARCHIVE_PATH,
) -> pd.DataFrame:
    """Read one CSV table from the archive and parse UTC timestamps."""
    member = build_member_path(resolution=resolution, table_name=table_name)

    with ZipFile(archive_path) as archive:
        if member not in archive.namelist():
            raise FileNotFoundError(f"{member} was not found in {archive_path}.")

        with archive.open(member) as zipped_file:
            with gzip.open(zipped_file, mode="rt", encoding="utf-8") as csv_file:
                df = pd.read_csv(csv_file)

    if "datetime_utc" not in df.columns:
        raise ValueError(f"{member} does not contain a datetime_utc column.")

    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True)
    return df.sort_values("datetime_utc").reset_index(drop=True)


def infer_category(table_name: str) -> str:
    """Infer the analysis category from a table name."""
    if table_name == "weather":
        return "weather"

    return table_name.split("_", 1)[0]


def infer_unit(table_name: str, column_name: str) -> str:
    """Infer the physical unit from the CSV table and column."""
    if table_name == "weather":
        return WEATHER_UNITS.get(column_name, "unknown")

    if table_name.endswith("_P"):
        return "W"

    if table_name.endswith("_W"):
        return "kWh"

    return "unknown"


def build_series_name(table_name: str, column_name: str) -> str:
    """Build a readable internal series name."""
    if table_name == "weather":
        return f"weather.{column_name.rsplit('.', 1)[-1]}"

    return f"{table_name}.{column_name}"


def build_source_series_id(
    resolution: str,
    table_name: str,
    column_name: str,
) -> str:
    """Build a stable source-level series identifier."""
    return f"{build_member_path(resolution, table_name)}:{column_name}"


def filter_table_for_period(
    df: pd.DataFrame,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> pd.DataFrame:
    """Filter a parsed CSV table to the requested inclusive time range."""
    mask = pd.Series(True, index=df.index)

    if start_date is not None:
        mask &= df["datetime_utc"] >= normalize_datetime_to_utc(start_date)

    if end_date is not None:
        mask &= df["datetime_utc"] <= normalize_datetime_to_utc(end_date)

    return df.loc[mask].reset_index(drop=True)


def build_import_metadata(
    archive_path: Path,
    resolution: str,
    table_name: str,
    column_name: str,
    df: pd.DataFrame,
) -> dict:
    """Build compact provenance metadata for one CSV series import."""
    return {
        "archive_path": str(archive_path),
        "archive_member": build_member_path(resolution, table_name),
        "table_name": table_name,
        "column_name": column_name,
        "row_count": len(df),
        "columns": list(df.columns),
    }


def extract_measurements(
    df: pd.DataFrame,
    import_id: int,
    resolution: str,
    table_name: str,
    column_name: str,
    region: str = DEFAULT_REGION,
) -> pd.DataFrame:
    """Build normalized measurement rows for one CSV column."""
    if column_name not in df.columns:
        raise ValueError(f"{column_name} is not present in {table_name}.")

    db_resolution = normalize_resolution(resolution)
    measurements_df = pd.DataFrame(
        {
            "import_id": import_id,
            "source_system": SOURCE_SYSTEM,
            "source_series_id": build_source_series_id(
                resolution=resolution,
                table_name=table_name,
                column_name=column_name,
            ),
            "series_name": build_series_name(
                table_name=table_name,
                column_name=column_name,
            ),
            "category": infer_category(table_name),
            "region": region,
            "resolution": db_resolution,
            "unit": infer_unit(table_name=table_name, column_name=column_name),
            "observation_timestamp": df["datetime_utc"],
            "value": pd.to_numeric(df[column_name], errors="coerce"),
        }
    )
    return measurements_df[MEASUREMENT_COLUMNS]


def _ingest_series_frame(
    connection,
    df: pd.DataFrame,
    table_name: str,
    column_name: str,
    resolution: str,
    archive_path: Path,
    region: str,
) -> dict[str, int | str]:
    """Insert one already-loaded CSV column as a measurement series."""
    series_name = build_series_name(table_name=table_name, column_name=column_name)
    db_resolution = normalize_resolution(resolution)
    import_id = insert_import(
        connection=connection,
        source_system=SOURCE_SYSTEM,
        import_name=series_name,
        source_path=str(archive_path),
        resolution=db_resolution,
        metadata=build_import_metadata(
            archive_path=archive_path,
            resolution=resolution,
            table_name=table_name,
            column_name=column_name,
            df=df,
        ),
    )
    measurements_df = extract_measurements(
        df=df,
        import_id=import_id,
        resolution=resolution,
        table_name=table_name,
        column_name=column_name,
        region=region,
    )
    inserted_row_count = insert_measurements(connection, measurements_df)

    return {
        "import_id": import_id,
        "series_name": series_name,
        "measurement_row_count": inserted_row_count,
        "input_row_count": len(df),
    }


def ingest_csv_series(
    table_name: str,
    column_name: str,
    resolution: str = "1h",
    archive_path: Path = DEFAULT_ARCHIVE_PATH,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    region: str = DEFAULT_REGION,
) -> dict[str, int | str]:
    """Ingest one CSV column as one measurement series."""
    df = read_csv_table(
        table_name=table_name,
        resolution=resolution,
        archive_path=archive_path,
    )
    df = filter_table_for_period(
        df=df,
        start_date=start_date,
        end_date=end_date,
    )
    database_config = load_database_config()

    with open_connection(database_config) as connection:
        create_tables(connection)
        return _ingest_series_frame(
            connection=connection,
            df=df,
            table_name=table_name,
            column_name=column_name,
            resolution=resolution,
            archive_path=archive_path,
            region=region,
        )


def ingest_csv_table(
    table_name: str,
    columns: list[str] | None = None,
    resolution: str = "1h",
    archive_path: Path = DEFAULT_ARCHIVE_PATH,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    region: str = DEFAULT_REGION,
) -> dict[str, dict[str, int | str]]:
    """Ingest all or selected value columns from one CSV table."""
    df = read_csv_table(
        table_name=table_name,
        resolution=resolution,
        archive_path=archive_path,
    )
    value_columns = [column for column in df.columns if column != "datetime_utc"]

    if columns is not None:
        missing_columns = sorted(set(columns) - set(value_columns))
        if missing_columns:
            raise ValueError(f"Missing columns in {table_name}: {missing_columns}")
        value_columns = columns

    df = filter_table_for_period(
        df=df,
        start_date=start_date,
        end_date=end_date,
    )
    database_config = load_database_config()
    results = {}
    with open_connection(database_config) as connection:
        create_tables(connection)
        for column_name in value_columns:
            results[column_name] = _ingest_series_frame(
                connection=connection,
                df=df,
                table_name=table_name,
                column_name=column_name,
                resolution=resolution,
                archive_path=archive_path,
                region=region,
            )

    return results


def ingest_csv_archive(
    resolution: str = "1h",
    archive_path: Path = DEFAULT_ARCHIVE_PATH,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    region: str = DEFAULT_REGION,
) -> dict[str, dict[str, dict[str, int | str]]]:
    """Ingest all CSV tables for one archive resolution."""
    results = {}
    for table_name in list_csv_tables(
        archive_path=archive_path,
        resolution=resolution,
    ):
        results[table_name] = ingest_csv_table(
            table_name=table_name,
            resolution=resolution,
            archive_path=archive_path,
            start_date=start_date,
            end_date=end_date,
            region=region,
        )

    return results
