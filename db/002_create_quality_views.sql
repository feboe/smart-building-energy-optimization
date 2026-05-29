DROP VIEW IF EXISTS missing_hourly_measurements;
DROP VIEW IF EXISTS electricity_p_quality_issues;
DROP VIEW IF EXISTS electricity_p_quality;
DROP VIEW IF EXISTS measurement_quality_issues;


CREATE OR REPLACE VIEW measurement_quality_issues AS
SELECT *
FROM (
    SELECT
        id,
        import_id,
        source_system,
        source_series_id,
        series_name,
        category,
        region,
        resolution,
        unit,
        observation_timestamp,
        value,
        CASE
            WHEN value IS NULL
                AND (
                    series_name <> 'electricity_P.PV'
                    OR observation_timestamp >= TIMESTAMPTZ '2019-06-28 22:00:00+00'
                )
                THEN 'missing_value'
            WHEN series_name = 'electricity_P.PV' AND value > 100 THEN 'positive_pv_warning'
            WHEN series_name = 'electricity_P.CHP' AND value > 0 THEN 'positive_chp_warning'
            ELSE NULL
        END AS quality_issue
    FROM measurements
) quality_rows
WHERE quality_issue IS NOT NULL;


CREATE OR REPLACE VIEW electricity_p_quality AS
SELECT
    *,
    CASE
        WHEN gross_load_w < -100 THEN 'negative_gross_load'
        ELSE NULL
    END AS quality_issue
FROM (
    SELECT
        source_system,
        observation_timestamp,
        region,
        resolution,
        MAX(value) FILTER (WHERE series_name = 'electricity_P.total') AS total_w,
        MAX(value) FILTER (WHERE series_name = 'electricity_P.PV') AS pv_w,
        MAX(value) FILTER (WHERE series_name = 'electricity_P.CHP') AS chp_w,
        MAX(value) FILTER (WHERE series_name = 'electricity_P.total')
        - COALESCE(MAX(value) FILTER (WHERE series_name = 'electricity_P.PV'), 0)
        - COALESCE(MAX(value) FILTER (WHERE series_name = 'electricity_P.CHP'), 0)
        AS gross_load_w
    FROM measurements
    WHERE source_system = 'SMART_COMPANY'
        AND series_name IN (
            'electricity_P.total',
            'electricity_P.PV',
            'electricity_P.CHP'
        )
    GROUP BY source_system, observation_timestamp, region, resolution
) electricity_rows
WHERE gross_load_w < -100;

CREATE OR REPLACE VIEW missing_hourly_measurements AS
WITH hourly_series AS (
    SELECT
        source_system,
        source_series_id,
        series_name,
        category,
        region,
        resolution,
        unit,
        MIN(observation_timestamp) AS first_observation_timestamp,
        MAX(observation_timestamp) AS last_observation_timestamp
    FROM measurements
    WHERE resolution = 'hour'
    GROUP BY
        source_system,
        source_series_id,
        series_name,
        category,
        region,
        resolution,
        unit
),
expected AS (
    SELECT
        s.source_system,
        s.source_series_id,
        s.series_name,
        s.category,
        s.region,
        s.resolution,
        s.unit,
        s.first_observation_timestamp,
        s.last_observation_timestamp,
        h.observation_timestamp
    FROM hourly_series s
    CROSS JOIN LATERAL generate_series(
        s.first_observation_timestamp,
        s.last_observation_timestamp,
        INTERVAL '1 hour'
    ) AS h(observation_timestamp)
)
SELECT
    e.source_system,
    e.source_series_id,
    e.series_name,
    e.category,
    e.region,
    e.resolution,
    e.unit,
    e.observation_timestamp,
    e.first_observation_timestamp,
    e.last_observation_timestamp
FROM expected e
LEFT JOIN measurements m
    ON m.source_system = e.source_system
    AND m.source_series_id = e.source_series_id
    AND m.region = e.region
    AND m.resolution = e.resolution
    AND m.observation_timestamp = e.observation_timestamp
WHERE m.id IS NULL;
