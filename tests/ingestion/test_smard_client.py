"""Tests for SMARD chart-data URL helpers."""

from src.smard_client import SmardConfig, build_index_url, build_payload_url


def test_smard_client_builds_index_and_payload_urls() -> None:
    config = SmardConfig(
        smard_filter_id="4169",
        region="DE-LU",
        resolution="hour",
    )

    assert (
        build_index_url(config)
        == "https://www.smard.de/app/chart_data/4169/DE-LU/index_hour.json"
    )
    assert (
        build_payload_url(config, 1_609_459_200_000)
        == "https://www.smard.de/app/chart_data/4169/DE-LU/"
        "4169_DE-LU_hour_1609459200000.json"
    )
