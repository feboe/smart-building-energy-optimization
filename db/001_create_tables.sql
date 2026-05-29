CREATE TABLE IF NOT EXISTS imports (
    id BIGSERIAL PRIMARY KEY,
    source_system TEXT NOT NULL,
    import_name TEXT NOT NULL,
    source_path TEXT,
    resolution TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_system, import_name, resolution)
);

CREATE TABLE IF NOT EXISTS measurements (
    id BIGSERIAL PRIMARY KEY,
    import_id BIGINT NOT NULL REFERENCES imports(id) ON DELETE RESTRICT,
    source_system TEXT NOT NULL,
    source_series_id TEXT NOT NULL,
    series_name TEXT NOT NULL,
    category TEXT NOT NULL,
    region TEXT NOT NULL,
    resolution TEXT NOT NULL,
    unit TEXT NOT NULL,
    observation_timestamp TIMESTAMPTZ NOT NULL,
    value NUMERIC,
    UNIQUE (
        source_system,
        source_series_id,
        region,
        resolution,
        observation_timestamp
    )
);

CREATE INDEX IF NOT EXISTS idx_imports_source
    ON imports (source_system, import_name, imported_at);

CREATE INDEX IF NOT EXISTS idx_measurements_import_id
    ON measurements (import_id);

CREATE INDEX IF NOT EXISTS idx_measurements_observation_timestamp
    ON measurements (observation_timestamp);

CREATE INDEX IF NOT EXISTS idx_measurements_analysis
    ON measurements (category, series_name, region, resolution, observation_timestamp);
