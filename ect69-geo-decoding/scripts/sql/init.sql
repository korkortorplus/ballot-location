-- ECT69 Geo-Decoding: PostGIS initialization
-- Runs automatically on first container start via /docker-entrypoint-initdb.d/

-- Extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS ltree;

-- Schemas
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS ect69;

-- =============================================================================
-- Reference data (read-only, loaded once)
-- =============================================================================

CREATE TABLE ref.electoral_district (
    id SERIAL PRIMARY KEY,
    province_name TEXT,
    district_number INT,
    geom GEOMETRY(MultiPolygon, 4326)
);

CREATE TABLE ref.admin_boundary (
    id SERIAL PRIMARY KEY,
    admin_level INT,           -- 1=province, 2=amphoe, 3=tambon
    name_th TEXT,
    name_en TEXT,
    parent_id INT REFERENCES ref.admin_boundary(id),
    path LTREE,                -- e.g. 'TH10', 'TH10.TH1001', 'TH10.TH1001.t_123'
    geom GEOMETRY(MultiPolygon, 4326)
);
CREATE INDEX idx_admin_boundary_geom ON ref.admin_boundary USING GIST(geom);
CREATE INDEX idx_admin_boundary_level_name ON ref.admin_boundary(admin_level, name_th);
CREATE INDEX idx_admin_boundary_path ON ref.admin_boundary USING GIST(path);

CREATE TABLE ref.ect66_geocoded (
    unit_id BIGINT PRIMARY KEY,    -- e.g. 1001010101
    province_name TEXT,
    district_name TEXT,
    sub_district_name TEXT,
    unit_number INT,
    unit_name TEXT,                 -- original location text
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    geom GEOMETRY(Point, 4326),
    formatted_address TEXT,
    place_id TEXT,                  -- Google Place ID
    tier_location TEXT,             -- A+, D, etc.
    correction_source TEXT          -- Google, Random, etc.
);
CREATE INDEX idx_ect66_geom ON ref.ect66_geocoded USING GIST(geom);
CREATE INDEX idx_ect66_unit_name ON ref.ect66_geocoded USING gin(unit_name gin_trgm_ops);

CREATE TABLE ref.ect66_raw_responses (
    unit_id BIGINT PRIMARY KEY,
    raw_response JSONB           -- full Google Geocoding API response
);

-- =============================================================================
-- Working data (read-write by agent)
-- =============================================================================

CREATE TABLE ect69.location (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,              -- main place name
    anchor TEXT,                     -- address/road
    full_text TEXT,                  -- reconstructed full description

    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    geom GEOMETRY(Point, 4326),

    geocode_source TEXT,             -- ect66 | gistda | nominatim | google
    geocode_address TEXT,            -- address returned by geocoding service
    geocode_place_id TEXT,           -- Google Place ID if applicable

    -- Validation results
    in_correct_tambon BOOLEAN,
    in_correct_amphoe BOOLEAN,
    in_correct_electoral_district BOOLEAN,

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_location_geom ON ect69.location USING GIST(geom);
CREATE INDEX idx_location_name ON ect69.location USING gin(name gin_trgm_ops);

CREATE TABLE ect69.sub_location (
    id SERIAL PRIMARY KEY,
    location_id INT NOT NULL REFERENCES ect69.location(id),
    name TEXT NOT NULL,              -- e.g. ศาลา 1, ห้องเรียนฝั่งขวา
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE ect69.ballot_unit (
    id SERIAL PRIMARY KEY,
    province TEXT NOT NULL,         -- จังหวัด
    electoral_district INT,         -- เขตเลือกตั้ง
    amphoe TEXT,                    -- อำเภอ
    registry TEXT,                  -- สำนักทะเบียน
    tambon TEXT,                    -- ตำบล
    unit_number INT,                -- หน่วยเลือกตั้ง
    location_raw TEXT,              -- สถานที่เลือกตั้ง (original, with #)

    -- Resolved references (filled by agent)
    location_id INT REFERENCES ect69.location(id),
    sub_location_id INT REFERENCES ect69.sub_location(id),

    -- Agent metadata
    status TEXT DEFAULT 'pending',  -- pending | processing | done | manual_review
    confidence TEXT,                -- high | medium | low
    agent_notes TEXT,
    tags TEXT[],                    -- e.g. {'ect66_carryforward', 'boundary_validated'}
    tool_calls_used INT,
    journey_log JSONB,              -- full reasoning trail

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_ballot_unit_status ON ect69.ballot_unit(status);
CREATE INDEX idx_ballot_unit_tambon ON ect69.ballot_unit(province, amphoe, tambon);
