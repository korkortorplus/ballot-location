# Infrastructure Spec for ECT69 Geo-Decoding

## Goal

Geocode all ~100k main day voting units for ECT69. Provide the PostGIS backend, spatial reference data, and visualization layer that the agentic geo-decoding pipeline (see `spec/agentic-geo-decoding.md`) operates on.

## Services

### docker-compose additions

Currently only Nominatim exists in `docker-compose.yml`. Add:

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| **postgis** | `postgis/postgis:17-3.5` | 5432 | Primary data store + spatial queries |
| **superset** | `apache/superset:latest` | 8088 | Visualization / human checkpoint dashboards |
| nominatim | `mediagis/nominatim:4.5` | 8080 | Already configured, self-hosted OSM geocoder |

## PostGIS Schema

### Reference data (read-only, loaded once)

#### `ref.electoral_district`
ECT 2569 electoral district boundaries for validation.

**Source:** `/home/ben/ddd/ninyawee/Thai-ECT-election-map/ECT Constituencies/2569/ShapeFile/2569_Election_Constituencies.shp` (74 MB)

```sql
CREATE TABLE ref.electoral_district (
    id SERIAL PRIMARY KEY,
    province_name TEXT,
    district_number INT,
    geom GEOMETRY(MultiPolygon, 4326)
);
-- Load: ogr2ogr or geopandas
```

#### `ref.admin_boundary`
Three-level administrative hierarchy (province → amphoe → tambon) with `ltree` paths for fast ancestor/descendant queries and `parent_id` for direct joins.

**Sources (3 different providers):**

| Level | Source | Rows | name_th field | name_en field |
|-------|--------|------|---------------|---------------|
| 1 (province) | OCHA `tha_admin_boundaries.geojson.zip` → `tha_admin1.geojson` | 77 | `adm1_name1` | `adm1_name` |
| 2 (amphoe) | OCHA `tha_admin2.geojson` (284 MB) | 928 | `adm2_name1` | `adm2_name` |
| 3 (tambon) | DOL `tambon_DOL_utf8.gpkg` (96 MB) | 7616 | `TAM_NAM_T` | — |
| 3 (BMA) | BMA `BMA_ADMIN_SUB_DISTRICT.gpkg` (1.6 MB) | 180 | `SUBDISTR_1` | — |

**Hierarchy wiring:**
- Province ↔ amphoe: joined by OCHA `adm1_pcode` (both sources have it)
- Amphoe ↔ tambon: joined by Thai name (`_prov_name` + `_amphoe_name`) after stripping `อ.`/`กิ่ง อ.` prefixes and applying 21 hand-verified name corrections for old/misspelled amphoe names in the DOL data (see `AMPHOE_NAME_FIXES` in `load_ref_geodata_to_postgis.py`)
- BMA sub-districts: joined to Bangkok amphoe by `DISTRICT_N` matching `name_th` within `adm1_pcode='TH10'`

**ltree path format:**
- Province: `TH10` (adm1_pcode)
- Amphoe: `TH10.TH1001` (adm1_pcode.adm2_pcode)
- Tambon: `TH10.TH1001.t_42` (parent path + auto-generated row id, since tambon has no pcode)

```sql
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

-- Example: all amphoe in Bangkok
SELECT name_th FROM ref.admin_boundary WHERE path <@ 'TH10' AND admin_level = 2;
-- Example: all tambon under a specific amphoe
SELECT name_th FROM ref.admin_boundary WHERE path <@ 'TH10.TH1001' AND admin_level = 3;
```

#### `ref.ect66_geocoded`
ECT66 geocoded results for carry-forward reference.

**Source:** `ect66-geo-decoding/outputs/ect66_geocoded_validated.parquet` (95,249 rows)

```sql
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
```

The trigram index on `unit_name` enables fuzzy matching between ECT69 and ECT66 location names (`pg_trgm` extension).

#### `ref.ect66_raw_responses` (optional)
Raw Google Maps API responses from ECT66 intermediate files, for deeper reference.

**Source:** `ect66-geo-decoding/intermediate/ect_batch_[1-3].parquet` (GMap column contains full API response dicts)

```sql
CREATE TABLE ref.ect66_raw_responses (
    unit_id BIGINT PRIMARY KEY,
    raw_response JSONB           -- full Google Geocoding API response
);
```

### Working data (read-write by agent)

#### `ect69.ballot_unit`
One row per voting unit from the ECT69 CSV. This is the work queue.

**Source:** `ect69-geo-decoding/inputs/ect69-voting-units-20260121.csv` (99,954 rows)

```sql
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
```

#### `ect69.location`
Deduplicated geocoded places. Multiple ballot_units can point to the same location.

```sql
CREATE TABLE ect69.location (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,              -- main place name (e.g. โรงเรียนวัดมหาธาตุ)
    anchor TEXT,                     -- address/road (e.g. ถนนพระจันทร์)
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
```

#### `ect69.sub_location`
Specific spots within a location (hall, building entrance, parking lot).

```sql
CREATE TABLE ect69.sub_location (
    id SERIAL PRIMARY KEY,
    location_id INT NOT NULL REFERENCES ect69.location(id),
    name TEXT NOT NULL,              -- e.g. ศาลา 1, ห้องเรียนฝั่งขวา, ลานจอดรถ
    description TEXT,                -- any extra context
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Agent memory

#### `agent.memory`
Persistent tips/tricks the agent learns, queryable by category.

```sql
CREATE TABLE agent.memory (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,          -- tool name, location type, province, etc.
    tip TEXT NOT NULL,
    learned_from_unit_id INT,        -- which ballot_unit triggered this
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_memory_category ON agent.memory(category);
```

Alternative: keep as text files per category (simpler, agent reads/appends). Decision TBD.

## Data Loading

### Order of operations

```bash
# 1. Start services
docker compose up -d postgis nominatim

# 2. Enable extensions
psql -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
psql -c "CREATE EXTENSION IF NOT EXISTS ltree;"

# 3. Create schemas
psql -c "CREATE SCHEMA IF NOT EXISTS ref;"
psql -c "CREATE SCHEMA IF NOT EXISTS ect69;"
psql -c "CREATE SCHEMA IF NOT EXISTS agent;"

# 4. Load reference data (one-time)
# Electoral districts + admin boundaries (province → amphoe → tambon+BMA with ltree)
uv run python ect69-geo-decoding/scripts/load_ref_geodata_to_postgis.py

# ECT66 geocoded results
uv run python scripts/load_ect66_to_postgis.py

# 5. Load ECT69 input CSV as work queue
uv run python scripts/load_ect69_csv_to_postgis.py
```

Scripts in step 4-5 to be created. They read parquet/CSV with pandas/geopandas and write to PostGIS via SQLAlchemy + GeoAlchemy2.

## Apache Superset

Connects to the PostGIS database. Dashboards for human checkpoints:

| Dashboard | Purpose |
|-----------|---------|
| **Progress overview** | Status distribution (pending/done/manual_review), confidence breakdown, source distribution |
| **Map view** | All geocoded points on a map, colored by confidence/source, filterable by province/amphoe |
| **Manual review queue** | Points tagged `manual_review_needed`, with location_raw text and agent notes |
| **ECT66 vs ECT69 comparison** | Side-by-side of carry-forward points vs new geocodes, delta distances |

## API Keys

Managed via `fnox.toml` (age-encrypted):
- `GMAP_API_KEY` -- Google Maps Geocoding API (5,000/day)
- `GISTDA_SHPERE_API` -- GISTDA Sphere search API (unlimited)

Injected as environment variables into the agent process.

## Network

```
agent process
  ├── PostGIS        (localhost:5432)
  ├── Nominatim      (localhost:8080)
  ├── GISTDA Sphere  (api.sphere.gistda.or.th, internet)
  ├── Google Geocode (maps.googleapis.com, internet)
  └── Interactive Map (localhost:3000, FastAPI + MapLibre GL JS + Playwright)

Superset (localhost:8088) → PostGIS (localhost:5432)
```
