# Agentic Geo-Decoding for ECT69 Main Day Voting Units

## Overview

Geocode ~100k Thai voting station locations using a pipeline of deterministic code steps + AI reasoning for the hard cases. No interactive map — validation is done programmatically with PostGIS spatial queries and assertion checks.

The pipeline processes locations in bulk (not one-by-one), grouping identical locations first, then matching against ECT66 reference data, and only invoking AI for the subset that can't be resolved automatically.

Built on the **Anthropic Agent SDK**. See also:
- `spec/infra.md` — PostGIS schema, docker services, data loading, Superset dashboards

## Data Model (PostGIS)

Three separate entities, allowing independent reference at UI/UX level:

| Entity | Description | Example |
|--------|-------------|---------|
| **`ect69.ballot_unit`** | The voting unit row (province, district, tambon, unit number) | เขตพระนคร หน่วย 1 |
| **`ect69.location`** | The geocoded place (main name + anchor/address) | โรงเรียนวัดมหาธาตุ ถนนพระจันทร์ |
| **`ect69.sub_location`** | A specific spot within a location (building, hall, entrance) | ศาลา 1, ห้องเรียนฝั่งขวา |

One location can serve multiple ballot units. One location can have multiple sub-locations. Full table definitions in `spec/infra.md`.

Reference data available in PostGIS (`ref.*` schema):
- `ref.ect66_geocoded` — 95,249 ECT66 results with trigram index for fuzzy name matching
- `ref.admin_boundary` — tambon/amphoe/province polygons for boundary validation
- `ref.electoral_district` — ECT 2569 electoral district polygons

## Pipeline Steps

### Step 1: Group

Deduplicate the ~100k ballot units into ~80k unique locations. Multiple ballot units share the same physical place (e.g. units 1-5 at the same school).

**Input:** `ect69.ballot_unit` (99,954 rows)
**Output:** `ect69.location` candidates (~80,927 unique `location_id` groups)

Already done by `clean_main_voting_units.py`:
- Parses raw `สถานที่เลือกตั้ง` field into `location_main`, `location_extra`, `sublocation`, `direction`, etc.
- Generates `location_id` (hash of normalized location text)
- Groups `(1)`, `(2)`, `(3)` suffixes as same location

**What's left:**
- Load grouped locations into `ect69.location` (name, anchor, full_text)
- Link each `ect69.ballot_unit` to its `ect69.location` via `location_id`
- Create `ect69.sub_location` entries where applicable (ศาลา 1, ห้องเรียน, etc.)

### Step 2: Identify — match against ECT66

For each unique location, fuzzy-match against `ref.ect66_geocoded` using trigram similarity on location name. This is the highest-quality source — many locations are unchanged between elections.

```sql
-- Find best ECT66 match for each ECT69 location
SELECT e69.id, e69.name,
       e66.unit_name AS ect66_name,
       e66.lat, e66.lng, e66.tier_location,
       similarity(e69.name, e66.unit_name) AS sim
FROM ect69.location e69
CROSS JOIN LATERAL (
    SELECT * FROM ref.ect66_geocoded e66
    WHERE e66.sub_district_name = e69.tambon  -- same tambon
    ORDER BY e69.name <-> e66.unit_name       -- trigram distance
    LIMIT 1
) e66
WHERE similarity(e69.name, e66.unit_name) > 0.3;
```

**Classification:**

| Match Quality | Criteria | Action |
|---------------|----------|--------|
| **Exact** | `similarity >= 0.8` AND ECT66 tier A+ | Carry forward coords directly |
| **Strong** | `similarity >= 0.6` AND ECT66 tier A+ | Carry forward, flag for spot-check |
| **Weak** | `similarity >= 0.3` | Use as reference point, still needs geocoding |
| **No match** | `similarity < 0.3` or no result | New location, needs full geocoding |

### Step 3: Validate — assert spatial soundness

Run a batch of spatial assertions against all locations that have coordinates (from ECT66 carry-forward or from geocoding services).

**Assertion set:**

| # | Assertion | SQL/Logic | Severity |
|---|-----------|-----------|----------|
| A1 | Point inside correct tambon | `ST_Contains(tambon.geom, location.geom)` | FAIL → reject |
| A2 | Point inside correct amphoe | `ST_Contains(amphoe.geom, location.geom)` | FAIL → reject |
| A3 | Point inside correct electoral district | `ST_Contains(ed.geom, location.geom)` | WARN → flag |
| A4 | Point on land (not water) | Distance to nearest land polygon > 0 or reverse geocode check | WARN → flag |
| A5 | Not a duplicate (>50m from another location in same tambon with different name) | Pairwise distance check | INFO → log |
| A6 | Reasonable distance from tambon centroid | `ST_Distance(location.geom, ST_Centroid(tambon.geom)) < 20km` | WARN → flag |

```sql
-- Example: A1 — point inside correct tambon
UPDATE ect69.location loc
SET in_correct_tambon = ST_Contains(
    (SELECT geom FROM ref.admin_boundary ab
     WHERE ab.admin_level = 3 AND ab.name_th = loc.tambon),
    loc.geom
);
```

Locations that **fail A1 or A2** are rejected back to the geocoding queue. Locations that pass all assertions are marked `status = 'done'`.

### Step 4: AI breakdown — plan for hard cases

For locations that couldn't be resolved (no ECT66 match, free API miss, or assertion failure), use an AI agent to reason about the location name and produce a geocoding plan.

**Input:** One location row at a time (or small batches of related locations in same tambon).

The agent reads:
- The raw location text and parsed fields
- What geocoding was already attempted and failed
- The tambon/amphoe context (centroid, boundary polygon)
- Adjacent locations in the same tambon that were successfully geocoded
- `read_memory` tips from previous runs

The agent produces a **plan** — a structured set of geocoding attempts to try:

```json
{
  "location_id": "abc123",
  "raw_text": "เต็นท์บริเวณริมคลองคูเมืองเดิม ถนนอัษฎางค์ #ตรงข้าม บริษัท นัฐพงษ์เซลส์แอนด์เซอร์วิส จำกัด",
  "reasoning": "This is a tent near a canal on Atsadang Road, opposite a company. Strategy: first anchor to the road, then pinpoint via the business name, finally snap to the road-side.",
  "plan": [
    {"step": "anchor", "query": "ถนนอัษฎางค์", "service": "overpass", "why": "get road geometry + admin boundary context first"},
    {"step": "pinpoint", "query": "บริษัท นัฐพงษ์เซลส์แอนด์เซอร์วิส ถนนอัษฎางค์", "service": "nominatim", "why": "specific business name + road, free API first"},
    {"step": "pinpoint_fallback_1", "query": "บริษัท นัฐพงษ์เซลส์แอนด์เซอร์วิส ถนนอัษฎางค์ เขตพระนคร", "service": "google_geocode", "why": "Google Geocoding API with bounds bias (tambon bbox) if Nominatim misses"},
    {"step": "pinpoint_fallback_2", "query": "บริษัท นัฐพงษ์เซลส์แอนด์เซอร์วิส ถนนอัษฎางค์", "service": "google_textsearch", "why": "Google Places Text Search (New) if geocode returns nothing — use locationRestriction (hard) to enforce tambon bbox"},
    {"step": "snap", "action": "snap_to_road_side", "why": "project pinpoint result onto nearest road-side of ถนนอัษฎางค์ (the tent is along the road, not at the business)"}
  ],
  "google_constraints": {
    "google_geocode": {
      "bounds": "tambon พระบรมมหาราชวัง bounding box (soft bias — prefers results in this area)"
    },
    "google_textsearch": {
      "note": "locationBias OR locationRestriction, not both",
      "locationRestriction": "tambon พระบรมมหาราชวัง bounding box (hard — reject results outside)",
      "alt_locationBias": "circle centered on road anchor, radius 500m (soft — use when tambon bbox is too tight)"
    }
  },
  "assertions": [
    {"check": "distance_to_road", "query": "way['name'='ถนนอัษฎางค์']", "service": "overpass", "op": "<", "value_m": 500},
    {"check": "distance_to_feature", "query": "way['waterway'='canal']['name'~'คูเมืองเดิม']", "service": "overpass", "op": "<", "value_m": 200},
    {"check": "contains", "query": "SELECT ST_Contains(geom, ST_SetSRID(ST_Point($lng,$lat),4326)) FROM ref.admin_boundary WHERE name_th='พระบรมมหาราชวัง' AND admin_level=3", "service": "postgis", "expect": true},
    {"check": "snap_distance", "action": "ST_Distance(result, nearest_point_on_road)", "op": "<", "value_m": 30, "why": "result should be on the road-side"}
  ]
}
```

**Geocoding strategy (ordered):**
1. **Nominatim geocode** — free, try first with the best query the agent can construct
2. **Google Geocoding API** — if Nominatim misses. Use `bounds` (soft bias to tambon bbox)
3. **Google Places text search** — if geocode returns nothing useful. Use `locationRestriction` (hard tambon bbox) or `locationBias` (soft circle)
4. **Road anchor + snap** — use Overpass to get road geometry, then snap the pinpoint to the tangential road-side when the location is along a road (เต็นท์, ศาลาริมถนน, etc.)

**Query construction tips:**
- **Geocode (Nominatim / Google)**: keep the place name **short and specific** — just the core name, strip sub-locations and admin levels. E.g. query `นัฐพงษ์เซลส์แอนด์เซอร์วิส` not the full raw text. Geocoders work best with concise input + spatial constraints.
- **Text search (Google Places)**: do the opposite — include **everything**: sub-location, road name, admin level, landmarks. Text search is fuzzy and benefits from more context. E.g. `บริษัท นัฐพงษ์เซลส์แอนด์เซอร์วิส ถนนอัษฎางค์ เขตพระนคร กรุงเทพ`

**Result selection:**
- Both geocode and text search may return **multiple candidates**. The agent must pick the best one by running assertions against each candidate and selecting the one that passes the most checks (especially boundary containment and proximity to anchor).
- Never blindly take the first result — always evaluate the full list.

**Key behaviors:**
- **Decompose** multi-part names: separate the main place from landmarks, roads, and directional clues
- **Recognize sub-locations**: `หอประชุมอำเภอกุมภวาปี` → geocode `ที่ว่าการอำเภอกุมภวาปี` (the parent district office)
- **Pick richest variant**: when multiple ballot units describe the same place, use the one with the most geocoding clues
- **Max out Google constraints**: always set `bounds` (geocode) or `locationRestriction`/`locationBias` (text search) to keep results within the correct area
- **Custom assertions**: the agent generates location-specific executable assertions beyond the standard set

### Step 5: Execute plans + re-validate

Run the AI-generated plans through the geocoding services:

```python
for plan in ai_plans:
    for attempt in plan["plan"]:
        result = geocode(attempt["query"], service=attempt["service"])
        if result:
            # Run standard assertions (A1-A6)
            # Run custom assertions from the plan
            # If all pass → accept
            # If standard pass but custom fail → accept with lower confidence
            break
    else:
        # All attempts failed → mark for manual review
```

The agent then **reviews** the results with the plan's custom assertions and the standard spatial checks. It decides:
- **Accept** (all assertions pass)
- **Accept with lower confidence** (standard assertions pass, some custom assertions fail)
- **Reject** (standard assertions fail) → tag `manual_review_needed`

## Agent Tools

### Domain tools

| Tool | Description | Step |
|------|-------------|------|
| `get_pending_locations` | Fetch batch of unresolved locations from `ect69.location` | 4 |
| `get_ect66_reference` | Fuzzy-match location name against `ref.ect66_geocoded` (trigram similarity) | 2 |
| `get_context` | Fetch adjacent locations in same tambon (successful ones as reference) | 4 |
| `geocode_nominatim` | Self-hosted Nominatim free-form search (unlimited, try first) | 5 |
| `geocode_google` | Google Geocoding API with locationBias/locationRestriction (quota, fallback) | 5 |
| `search_google_places` | Google Places API text search with soft/hard area constraints (quota, last resort) | 5 |
| `query_overpass` | Self-hosted Overpass API for OSM features — road geometry, POIs (unlimited) | 4, 5 |
| `query_postgis` | Run spatial SQL against PostGIS (e.g. assertion checks, fetch boundaries) | 3, 5 |
| `save_result` | Write coordinates + metadata to `ect69.location`, update `ect69.ballot_unit` | 5 |
| `read_memory` | Read tips/tricks text file for a specific tool or location type | 4 |
| `write_memory` | Append a tip/trick learned during processing | 5 |

### No map tools

This spec intentionally omits the interactive map. Spatial validation is done via PostGIS assertions (Step 3) and the agent's custom assertions (Step 4). Visual confirmation is not required — the assertion framework catches boundary violations programmatically.

If a future iteration needs visual confirmation for edge cases, see `spec/interactive-map.md`.

## Expected Volume Breakdown

Based on ECT66 data and free API hit rates:

| Category | Est. Count | % | Resolution |
|----------|-----------|---|------------|
| ECT66 exact match (sim ≥ 0.8, tier A+) | ~55,000 | ~68% | Auto carry-forward |
| ECT66 strong match (sim ≥ 0.6, tier A+) | ~8,000 | ~10% | Auto carry-forward + spot-check |
| Free API hit (Nominatim) | ~5,000 | ~6% | Auto with assertion validation |
| AI-planned → free API | ~5,000 | ~6% | Agent plans, free APIs execute |
| AI-planned → Google API | ~3,000 | ~4% | Agent plans, Google executes |
| Manual review | ~5,000 | ~6% | Human intervention |

## Compute Budget

- **Steps 1-3**: Pure code, no LLM calls. Run as batch SQL/Python.
- **Step 4**: ~1 LLM call per unresolved location (~13k locations). The agent sees a batch of context and produces plans.
- **Step 5**: Geocoding API calls + assertion checks (code, no LLM). LLM only for final review of ambiguous results.
- **Google API budget**: 5,000/day. At ~3,000 needed, completable in 1 day.

## Memory

Text files stored per tool/category. The agent reads relevant memory at the start of each batch and appends new learnings at the end.

Examples of things the agent might learn and save:
- "Nominatim handles English transliterated names well"
- "หอประชุมอำเภอ always means it's inside ที่ว่าการอำเภอ"
- "Google Geocode works well for สวน (parks) that other services miss"

## Save Results

Whether successful or not, save to PostGIS (see `spec/infra.md` for table schemas):

**On success:**
- Update `ect69.location` with coordinates, geocode source, assertion results
- Update linked `ect69.ballot_unit` rows with status = `done`

**Always (on `ect69.ballot_unit`):**
- `confidence`: high / medium / low
- `tags[]`: `ect66_carryforward`, `ect66_strong_match`, `nominatim_hit`, `google_hit`, `boundary_validated`, `manual_review_needed`
- `journey_log` (JSONB): what was tried, what worked, what failed
- `agent_notes`: free-text reasoning (only for AI-planned locations)

## Transparency

Progress is trackable via Superset dashboards (see `spec/infra.md`):
- Status distribution (pending / done / manual_review)
- Confidence breakdown
- Source distribution (ECT66 / Nominatim / Google)
- Assertion pass/fail rates
- Manual review queue
