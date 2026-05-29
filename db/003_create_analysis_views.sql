DROP VIEW IF EXISTS smart_company_analysis;
DROP VIEW IF EXISTS electricity_p_calendar;
DROP VIEW IF EXISTS electricity_p_clean;


CREATE OR REPLACE VIEW electricity_p_clean AS
WITH electricity_p_raw AS (
    SELECT
        source_system,
        observation_timestamp,
        region,
        resolution,
        MAX(value) FILTER (WHERE series_name = 'electricity_P.total') AS total_w,
        MAX(value) FILTER (WHERE series_name = 'electricity_P.PV') AS pv_w_raw,
        MAX(value) FILTER (WHERE series_name = 'electricity_P.CHP') AS chp_w
    FROM measurements
    WHERE source_system = 'SMART_COMPANY'
        AND series_name IN (
            'electricity_P.total',
            'electricity_P.PV',
            'electricity_P.CHP'
        )
    GROUP BY source_system, observation_timestamp, region, resolution
),
electricity_p_cleaned AS (
    SELECT
        source_system,
        observation_timestamp,
        region,
        resolution,
        total_w,
        pv_w_raw,
        CASE
            WHEN pv_w_raw IS NULL THEN NULL
            WHEN pv_w_raw > 0 AND pv_w_raw <= 100 THEN 0
            WHEN pv_w_raw > 100 THEN NULL
            ELSE pv_w_raw
        END AS pv_w,
        chp_w
    FROM electricity_p_raw
),
electricity_p_load AS (
    SELECT
        source_system,
        observation_timestamp,
        region,
        resolution,
        total_w,
        pv_w_raw,
        pv_w,
        chp_w,
        total_w - COALESCE(pv_w, 0) - COALESCE(chp_w, 0) AS gross_load_w
    FROM electricity_p_cleaned
),
day_ahead_prices AS (
    SELECT
        observation_timestamp,
        resolution,
        MAX(value) AS day_ahead_price_eur_per_mwh
    FROM measurements
    WHERE source_system = 'SMARD'
        AND series_name = 'day_ahead_price'
    GROUP BY observation_timestamp, resolution
)
SELECT
    load.source_system,
    load.observation_timestamp,
    load.region,
    load.resolution,
    load.total_w,
    load.pv_w,
    load.chp_w,
    load.gross_load_w,
    load.total_w / 1000 AS grid_energy_kwh,
    load.gross_load_w / 1000 AS gross_load_kwh,
    -load.pv_w / 1000 AS pv_generation_kwh,
    -load.chp_w / 1000 AS chp_generation_kwh,
    prices.day_ahead_price_eur_per_mwh,
    prices.day_ahead_price_eur_per_mwh / 1000 AS day_ahead_price_eur_per_kwh,
    load.pv_w_raw,
    load.pv_w_raw IS NOT NULL AND load.pv_w_raw <> load.pv_w AS pv_w_was_cleaned
FROM electricity_p_load load
LEFT JOIN day_ahead_prices prices
    ON prices.observation_timestamp = load.observation_timestamp
    AND prices.resolution = load.resolution
WHERE load.gross_load_w IS NULL OR load.gross_load_w >= -100;


CREATE OR REPLACE VIEW electricity_p_calendar AS
SELECT
    *,
    observation_timestamp AT TIME ZONE 'Europe/Berlin' AS local_timestamp,
    EXTRACT(YEAR FROM observation_timestamp AT TIME ZONE 'Europe/Berlin')::INT
        AS local_year,
    EXTRACT(MONTH FROM observation_timestamp AT TIME ZONE 'Europe/Berlin')::INT
        AS local_month,
    EXTRACT(DAY FROM observation_timestamp AT TIME ZONE 'Europe/Berlin')::INT
        AS local_day,
    EXTRACT(HOUR FROM observation_timestamp AT TIME ZONE 'Europe/Berlin')::INT
        AS local_hour,
    EXTRACT(ISODOW FROM observation_timestamp AT TIME ZONE 'Europe/Berlin')::INT
        AS local_isodow,
    EXTRACT(ISODOW FROM observation_timestamp AT TIME ZONE 'Europe/Berlin')::INT
        IN (6, 7) AS is_weekend
FROM electricity_p_clean;


CREATE OR REPLACE VIEW smart_company_analysis AS
SELECT
    *
FROM electricity_p_calendar
WHERE local_year = 2021;
