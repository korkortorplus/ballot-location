# Agentic Geo-Decoding for ECT69 Main Day Voting Units

## Overview

An AI agent geocodes ~100k Thai voting station locations one row at a time. The agent reads raw location text, reasons about clues in the name, tries multiple geocoding services, visually confirms on an interactive map, and saves results to PostGIS. Every action is transparent -- the human can see each tool call, parameter, and the agent's reasoning.

Each row gets a fresh context. The agent works autonomously within a compute budget per row, deciding when a result is "good enough" or when to give up.

Built on the **Anthropic Agent SDK**. See also:
- `spec/infra.md` -- PostGIS schema, docker services, data loading, Superset dashboards
- `spec/interactive-map.md` -- generic map tool (add/remove layers, describe via H3, screenshot)

## Data Model (PostGIS)

Three separate entities, allowing independent reference at UI/UX level:

| Entity | Description | Example |
|--------|-------------|---------|
| **`ect69.ballot_unit`** | The voting unit row (province, district, tambon, unit number) | เขตพระนคร หน่วย 1 |
| **`ect69.location`** | The geocoded place (main name + anchor/address) | โรงเรียนวัดมหาธาตุ ถนนพระจันทร์ |
| **`ect69.sub_location`** | A specific spot within a location (building, hall, entrance) | ศาลา 1, ห้องเรียนฝั่งขวา |

One location can serve multiple ballot units. One location can have multiple sub-locations. Full table definitions in `spec/infra.md`.

Reference data available in PostGIS (`ref.*` schema):
- `ref.ect66_geocoded` -- 95,249 ECT66 results with trigram index for fuzzy name matching
- `ref.admin_boundary` -- tambon/amphoe/province polygons for boundary validation
- `ref.electoral_district` -- ECT 2569 electoral district polygons

## Per-Row Agent Loop

The agent processes **1 row at a time**, fresh context each time. Steps:

### Step 0: Load Row + Context

- Read the current row from `ect69.ballot_unit` (status = `pending`)
- `read_memory` for tips relevant to this location type / province / tool
- Fetch adjacent rows (same tambon) to see if grouping helps
- **Check ECT66 first**: query `ref.ect66_geocoded` using trigram similarity on location name. If a match exists with tier A+, carry forward that coordinate as the starting answer

### Step 1: Read and Understand the Location Name

The agent parses the raw `สถานที่เลือกตั้ง` field itself (no separate rule-based preprocessing). It identifies:

- **Construction type**: เต็นท์, ศาลา, อาคาร, โดม (temporary vs permanent structure)
- **Main location name**: the actual place to geocode (e.g. `โรงเรียนวัดมหาธาตุ`)
- **Anchor/address**: street name, soi, landmark after `#` or in description
- **Sub-location**: `(ศาลา 1)`, `(ห้องเรียนฝั่งขวา)` -- not useful for geocoding, saved separately
- **Relocation note**: `(ย้ายมาจาก...)` -- historical, saved as metadata
- **Direction/hint**: `ตรงข้าม...`, `ใกล้...`, `ฝั่ง...` -- secondary geocoding clue
- **Unit sequence**: `(1)`, `(2)` -- same physical location, multiple units

**Grouping**: if adjacent rows share the same main location (e.g. `เต็นท์บริเวณโรงเรียนศาลาคู้(1)#` through `(3)#`), the agent recognizes they map to one geocode and processes them together.

**Pick richest variant**: when multiple rows describe the same place, pick the one with the most clues:
```
มหาวิทยาลัยเทคโนโลยีราชมงคลกรุงเทพ พระนครใต้#
มหาวิทยาลัยเทคโนโลยีราชมงคลกรุงเทพ พระนครใต้#(หน้าหอการค้า)
→ use the second one, "หน้าหอการค้า" is an extra geocoding clue
```

### Step 2: Geocode Using Fallback Chain

Ordered by preference (unlimited APIs first, quota-limited last):

| Priority | Service | Quota | Notes |
|----------|---------|-------|-------|
| 1 | **ECT66 carry-forward** | n/a | Same/similar location with good coords from last election |
| 2 | **GISTDA Sphere + OSM Nominatim** | unlimited | Combined ~17% hit rate, non-overlapping coverage (see `scripts/geocode_combined.py`) |
| 3 | **Google Geocoding API** | 5,000/day | For hard cases where free APIs fail |

Each service tries multiple query strategies:
- Raw location name
- Cleaned name (prefixes stripped)
- Cleaned name + tambon
- Cleaned name + amphoe

**Clue-based reasoning**: the agent doesn't just try the name -- it decomposes:
```
เต็นท์บริเวณริมคลองคูเมืองเดิม ถนนอัษฎางค์ #ตรงข้าม บริษัท นัฐพงษ์เซลส์แอนด์เซอร์วิส จำกัด
→ geocode "ริมคลองคูเมืองเดิม ถนนอัษฎางค์" (the area)
→ geocode "บริษัท นัฐพงษ์เซลส์แอนด์เซอร์วิส จำกัด" (the landmark across the street)
→ if both return results, pick a point near the intersection
→ if only one returns, use it with lower confidence
```

**Sub-location awareness**: many names are sub-locations that will never geocode directly. The agent recognizes this and geocodes the parent:
```
หอประชุมอำเภอกุมภวาปี → geocode "ที่ว่าการอำเภอกุมภวาปี" (the district office)
ศาลาหน้าอาคาร โรงเรียนวัดราชบพิธ → geocode "โรงเรียนวัดราชบพิธ" (the school)
```

### Step 3: Visual Confirm on Interactive Map (Fine-tuning Loop)

Uses the generic map tool defined in `spec/interactive-map.md`. The agent interacts with the map through two feedback tiers:

1. **`map.describe()`** (cheap, text) -- returns H3-indexed positions, containment checks (point inside tambon polygon?), pairwise distances between layers. Used for fast spatial iteration.
2. **`map.screenshot(basemap)`** (expensive, image) -- captures satellite or street view as PNG. Used when the agent needs to see road layout, building footprints, junction geometry, or entrance placement.

Typical flow:
```
Agent: map.clear_layers()
Agent: map.set_view(h3="8c2a100d2929dff", zoom=17)
Agent: map.add_layer(candidate_point, "candidate", style=red)
Agent: map.add_layer(tambon_polygon, "tambon boundary", style=blue)
Agent: map.add_layer(ect66_point, "ect66 ref", style=blue)  # if exists
Agent: map.describe()
  → "candidate at 8c2a100d2929dff, inside tambon boundary, 342m from edge,
     same hex as ect66 ref (< 9m)"
Agent: [spatial checks pass, but needs to verify building entrance]
Agent: map.screenshot("satellite")
  → [sees building footprint, entrance on south side of road]
Agent: [adjusts pin to entrance]
Agent: map.add_layer(adjusted_point, "candidate v2", style=red)
Agent: map.describe(focus="candidate v2")
  → "candidate v2 at 8d2a100d2929c7f, inside tambon boundary, 338m from edge"
Agent: [accepts]
```

The agent loads boundary polygons from PostGIS (`ref.admin_boundary`, `ref.electoral_district`) as GeoJSON layers onto the map. The `map.describe()` response automatically computes containment and distance for all active layers -- this replaces the need for separate boundary-check tools.

The human watches the same map live at `localhost:3000`, seeing every layer add/remove and pin adjustment in real-time.

### Step 4: Rationalize and Decide

The agent applies spatial checks (already available from `map.describe()` output):
- **Boundary check**: does the point fall within the correct tambon? amphoe? electoral district?
- **Sanity check**: is the point on land? (not in a river/sea)

**Confidence assessment**: the agent rates its own confidence based on:
- Source quality (Google > GISTDA > Nominatim > centroid fallback)
- Boundary validation pass/fail
- Whether the place name was found verbatim vs inferred
- Visual confirmation from map screenshot

The agent decides: accept, re-try with different strategy, or give up and tag for manual review.

### Step 5: Save Results + Journey Log

Whether successful or not, the agent saves to PostGIS (see `spec/infra.md` for table schemas):

**On success:**
- Create or reuse `ect69.location` (name, anchor, coordinates, geocode source)
- Create `ect69.sub_location` if applicable
- Update `ect69.ballot_unit` with `location_id`, `sub_location_id`, status = `done`

**Always (on `ect69.ballot_unit`):**
- `confidence`: high / medium / low
- `tags[]`: `ect66_carryforward`, `gistda_hit`, `nominatim_hit`, `google_hit`, `boundary_validated`, `manual_review_needed`
- `journey_log` (JSONB): full reasoning trail -- which tools were called, with what parameters, what came back
- `agent_notes`: free-text (e.g. "place is a tent in a parking lot, geocoded to the parent school instead")
- `tool_calls_used`: count against budget

## Agent Tools

### Domain tools

| Tool | Description | Step |
|------|-------------|------|
| `get_row` | Fetch current row + N adjacent rows from `ect69.ballot_unit` | 0 |
| `get_ect66_reference` | Fuzzy-match location name against `ref.ect66_geocoded` (trigram similarity) | 0 |
| `geocode_gistda` | GISTDA Sphere keyword search (unlimited) | 2 |
| `geocode_nominatim` | Self-hosted Nominatim free-form search (unlimited) | 2 |
| `geocode_google` | Google Geocoding API (5,000/day quota) | 2 |
| `query_postgis` | Run spatial SQL against PostGIS (e.g. fetch tambon polygon as GeoJSON) | 0-4 |
| `save_result` | Write to `ect69.location`, `ect69.sub_location`, update `ect69.ballot_unit` | 5 |
| `read_memory` | Read tips/tricks text file for a specific tool or location type | 0 |
| `write_memory` | Append a tip/trick learned during this row's processing | 5 |

### Map tools (from `spec/interactive-map.md`)

| Tool | Description | Step |
|------|-------------|------|
| `map.add_layer` | Add any GeoJSON (points, polygons, lines) to the map | 3 |
| `map.remove_layer` | Remove a layer by ID | 3 |
| `map.clear_layers` | Remove all user layers | 3 |
| `map.set_view` | Pan/zoom, accepts H3 index or lat/lng | 3 |
| `map.describe` | Text description of map state: H3 positions, containment, distances. Viewport-scoped by default, with `focus`/`relations_to` filtering | 3-4 |
| `map.screenshot` | Capture PNG of current view (satellite or street basemap, low/high detail) | 3 |
| `map.search` | Forward/reverse geocode via self-hosted Nominatim. Returns GeoJSON FeatureCollection | 2-3 |
| `map.get_features` | Query features from a layer near a location (by H3 or bbox) | 3-4 |
| `map.exec` | Run turf.js spatial expression (distance, area, bearing, buffer, etc.) | 3-4 |
| `map.add_raster_layer` | Add WMS/TMS/XYZ tile layer | 3 |
| `map.list_layers` | List all active layers | 3 |
| `map.toggle_layer` | Show/hide a layer | 3 |

## Compute Budget

Per row:
- **Max tool calls**: 10 (configurable)
- **Timeout**: TBD (wall clock per row)
- The agent decides when to stop: if it feels the result is correct, or is the best available given the data, it stops early
- If budget exhausted without a good result, save with `manual_review_needed` tag and move on
- `map.describe()` is cheap and should be preferred over `map.screenshot()` when spatial text is sufficient

## Memory

Text files stored per tool/category. The agent reads relevant memory at the start of each row and appends new learnings at the end.

Examples of things the agent might learn and save:
- "GISTDA returns good results for วัด (temples) but fails on เต็นท์ (tents)"
- "For Bangkok, appending ถนน + road name to the query improves GISTDA hit rate"
- "Nominatim handles English transliterated names better than GISTDA"
- "หอประชุมอำเภอ always means it's inside ที่ว่าการอำเภอ"
- "Google Geocode works well for สวน (parks) that other services miss"

This accumulates over time, making the agent smarter as it processes more rows. If the agent finds itself calling a tool multiple times with poor results, it should write a memory note about what didn't work.

## Transparency

The agent must be fully transparent. The human observer sees:
- Every tool call name and parameters
- Every API response (or summary)
- The agent's reasoning for each decision
- The map updating in real-time at `localhost:3000` with each layer change
- The final confidence assessment and tags

Progress is trackable via Superset dashboards (see `spec/infra.md`): status distribution, confidence breakdown, manual review queue.
