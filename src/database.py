"""Database access helpers for schema setup and data ingestion."""

import psycopg
from pathlib import Path
from psycopg.types.json import Jsonb
from src.config import DatabaseConfig
import pandas as pd
from src.transform_smard import MEASUREMENT_COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def open_connection(config: DatabaseConfig) -> psycopg.Connection:
    """Open a PostgreSQL connection from a database configuration."""
    return psycopg.connect(
        dbname=config.database,
        user=config.user,
        password=config.password,
        host=config.host,
        port=config.port,
    )


def execute_sql_file(connection: psycopg.Connection, sql_file_path: Path) -> None:
    """Execute a SQL file inside the provided connection and commit it."""
    with open(sql_file_path, "r", encoding="utf-8") as file:
        sql_text = file.read()

    with connection.cursor() as cursor:
        cursor.execute(sql_text)
    connection.commit()


def create_tables(connection: psycopg.Connection) -> None:
    """Create the base database tables if they do not already exist."""
    sql_file_path = PROJECT_ROOT / "db" / "001_create_tables.sql"
    execute_sql_file(connection, sql_file_path)


def insert_import(
    connection: psycopg.Connection,
    source_system: str,
    import_name: str,
    source_path: str | None,
    resolution: str | None,
    metadata: dict,
) -> int:
    """Insert one import metadata row and return its database id."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO imports (
                source_system,
                import_name,
                source_path,
                resolution,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                source_system,
                import_name,
                source_path,
                resolution,
                Jsonb(metadata),
            ),
        )
        inserted_row = cursor.fetchone()

    connection.commit()

    if inserted_row is None:
        raise ValueError("Could not insert import row.")

    return inserted_row[0]


def insert_measurements(
    connection: psycopg.Connection, measurements_df: pd.DataFrame
) -> int:
    """Insert normalized measurements and return the number of inserted rows."""
    cols = MEASUREMENT_COLUMNS
    records = [
        tuple(None if pd.isna(v) else v for v in row)
        for row in measurements_df[cols].itertuples(index=False, name=None)
    ]

    if not records:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO measurements (
                import_id,
                source_system,
                source_series_id,
                series_name,
                category,
                region,
                resolution,
                unit,
                observation_timestamp,
                value
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                source_system,
                source_series_id,
                region,
                resolution,
                observation_timestamp
            )
            DO NOTHING;
            """,
            records,
        )
        inserted_row_count = cursor.rowcount
    connection.commit()
    return inserted_row_count
