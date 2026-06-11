"""Offline tests for smart-company CSV ingestion helpers."""

from datetime import datetime
from io import BytesIO
import gzip
from zipfile import ZipFile

import pandas as pd
import pytest

from src.csv_pipeline import extract_measurements, filter_table_for_period, read_csv_table
from src.database import MEASUREMENT_COLUMNS


def _write_csv_archive(
    tmp_path,
    table_name: str,
    csv_text: str,
    resolution: str = "1h",
):
    archive_path = tmp_path / "reduced_data.zip"
    member_path = f"reduced_data/{resolution}/{table_name}.csv.gz"
    compressed_csv = BytesIO()

    with gzip.GzipFile(fileobj=compressed_csv, mode="wb") as gzip_file:
        gzip_file.write(csv_text.encode("utf-8"))

    with ZipFile(archive_path, "w") as archive:
        archive.writestr(member_path, compressed_csv.getvalue())

    return archive_path


def test_read_csv_table_reads_gzipped_archive_member_and_parses_utc_timestamp(
    tmp_path,
) -> None:
    archive_path = _write_csv_archive(
        tmp_path,
        table_name="electricity_P",
        csv_text=(
            "datetime_utc,electricity_P.total\n"
            "2021-01-01T01:00:00Z,20\n"
            "2021-01-01T00:00:00Z,10\n"
        ),
    )

    df = read_csv_table(
        table_name="electricity_P",
        archive_path=archive_path,
    )

    assert df["datetime_utc"].tolist() == [
        pd.Timestamp("2021-01-01T00:00:00Z"),
        pd.Timestamp("2021-01-01T01:00:00Z"),
    ]
    assert df["electricity_P.total"].tolist() == [10, 20]


def test_read_csv_table_rejects_missing_datetime_utc_column(tmp_path) -> None:
    archive_path = _write_csv_archive(
        tmp_path,
        table_name="electricity_P",
        csv_text="electricity_P.total\n10\n",
    )

    with pytest.raises(ValueError, match="datetime_utc"):
        read_csv_table(
            table_name="electricity_P",
            archive_path=archive_path,
        )


def test_filter_table_for_period_treats_naive_dates_as_berlin_local_time() -> None:
    df = pd.DataFrame(
        {
            "datetime_utc": pd.to_datetime(
                [
                    "2020-12-31T22:00:00Z",
                    "2020-12-31T23:00:00Z",
                    "2021-01-01T00:00:00Z",
                    "2021-01-01T01:00:00Z",
                ],
                utc=True,
            ),
            "value": [1, 2, 3, 4],
        }
    )

    filtered_df = filter_table_for_period(
        df,
        start_date=datetime(2021, 1, 1, 0, 0),
        end_date=datetime(2021, 1, 1, 1, 0),
    )

    assert filtered_df["datetime_utc"].tolist() == [
        pd.Timestamp("2020-12-31T23:00:00Z"),
        pd.Timestamp("2021-01-01T00:00:00Z"),
    ]
    assert filtered_df["value"].tolist() == [2, 3]


def test_extract_csv_measurements_outputs_database_shape_and_metadata() -> None:
    df = pd.DataFrame(
        {
            "datetime_utc": pd.to_datetime(
                ["2021-01-01T00:00:00Z", "2021-01-01T01:00:00Z"],
                utc=True,
            ),
            "electricity_P.total": ["12.5", "not-a-number"],
        }
    )

    measurements_df = extract_measurements(
        df=df,
        import_id=7,
        resolution="1h",
        table_name="electricity_P",
        column_name="electricity_P.total",
        region="test_region",
    )

    assert list(measurements_df.columns) == MEASUREMENT_COLUMNS
    assert measurements_df["import_id"].tolist() == [7, 7]
    assert measurements_df["source_system"].tolist() == ["SMART_COMPANY", "SMART_COMPANY"]
    assert measurements_df["source_series_id"].tolist() == [
        "reduced_data/1h/electricity_P.csv.gz:electricity_P.total",
        "reduced_data/1h/electricity_P.csv.gz:electricity_P.total",
    ]
    assert measurements_df["series_name"].tolist() == [
        "electricity_P.electricity_P.total",
        "electricity_P.electricity_P.total",
    ]
    assert measurements_df["category"].tolist() == ["electricity", "electricity"]
    assert measurements_df["region"].tolist() == ["test_region", "test_region"]
    assert measurements_df["resolution"].tolist() == ["hour", "hour"]
    assert measurements_df["unit"].tolist() == ["W", "W"]
    assert measurements_df["observation_timestamp"].tolist() == df[
        "datetime_utc"
    ].tolist()
    assert measurements_df.loc[0, "value"] == pytest.approx(12.5)
    assert pd.isna(measurements_df.loc[1, "value"])
