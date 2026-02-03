# Agentic Geo-Decoding for ECT69 Main Day Voting Units

## Overview

An AI agent geocodes ~100k Thai voting station locations one row at a time. The agent reads raw location text, reasons about clues in the name, tries multiple geocoding services, visually confirms on an interactive map, and saves results to PostGIS. Every action is transparent -- the human can see each tool call, parameter, and the agent's reasoning.

Each row gets a fresh context. The agent works autonomously within a compute budget per row, deciding when a result is "good enough" or when to give up.

## Data Model (PostGIS)

Three separate entities, allowing independent reference at UI/UX level:

| Entity | Description | Example |
|--------|-------------|---------|
| **ballot_unit** | The voting unit row (province, district, tambon, unit number) | เขตพระนคร หน่วย 1 |
| **location** | The geocoded place (main name + anchor/address) | โรงเรียนวัดมหาธาตุ ถนนพระจันทร์ |
| **sub_location** | A specific spot within a location (building, hall, entrance) | ศาลา 1, ห้องเรียนฝั่งขวา |

One location can serve multiple ballot units. One location can have multiple sub-locations. See `spec/infra.md` for PostGIS schema and supporting spatial data (admin boundaries, electoral districts, ECT66 results).

## Per-Row Agent Loop

The agent processes **1 row at a time**, fresh context each time. Steps:

### Step 0: Load Row + Context

- Read the current row from PostGIS (or CSV)
- `read_memory` for tips relevant to this location type / province / tool
- Fetch adjacent rows (same tambon) to see if grouping helps
- **Check ECT66 first**: if the same or very similar location was geocoded in ECT66 with good confidence, carry forward that coordinate as the starting answer

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

This step is primarily for **fine-tuning the pin location**. The agent uses the map as a human would: pan, zoom, inspect satellite imagery, identify roads, plot boundaries, and building/parcel entrances, then re-point for better accuracy.

Every time the agent places a guess, the **map view updates in real-time** showing:
- The candidate point(s) on satellite + street map
- The tambon/amphoe boundary polygon
- ECT66 reference point (if exists)

The agent **visually inspects** the surroundings — road layout, parcel shapes, building entrances — and iteratively adjusts the pin (e.g., "the school entrance is on the south side of the road, shift pin there").

The map change triggers a function that **injects a message back into the agent chat** with:
- Whether the point falls within the correct tambon boundary
- Whether the point falls within the correct electoral district
- Distance to ECT66 reference point (if any)
- Nearby POI names from the map tile

This injected metadata serves as **guardrails** (preventing drift into the wrong tambon/district) while the visual map provides the fine-grained spatial cues for precise placement.

The agent reads this context and decides whether to accept, adjust, or re-try.

### Step 4: Rationalize and Decide

The agent applies spatial checks:
- **Boundary check**: does the point fall within the correct tambon? amphoe? electoral district?
- **Sanity check**: is the point on land? (not in a river/sea)

**Confidence assessment**: the agent rates its own confidence based on:
- Source quality (Google > GISTDA > Nominatim > centroid fallback)
- Boundary validation pass/fail
- Whether the place name was found verbatim vs inferred
- Visual confirmation from map context

The agent decides: accept, re-try with different strategy, or give up and tag for manual review.

### Step 5: Save Results + Journey Log

Whether successful or not, the agent saves to PostGIS:

**On success:**
- Coordinates (lat, lon)
- Source service used
- Confidence tag (high / medium / low)
- Link to location entity (create or reuse existing)
- Link to sub_location entity if applicable

**Always:**
- The full reasoning trail: which tools were called, with what parameters, what came back
- Tags: `ect66_carryforward`, `gistda_hit`, `nominatim_hit`, `google_hit`, `boundary_validated`, `manual_review_needed`
- Free-text notes from the agent (e.g. "place is a tent in a parking lot, geocoded to the parent school instead")

## Agent Tools

| Tool | Description | Triggers |
|------|-------------|----------|
| `get_row` | Fetch current row + N adjacent rows from PostGIS/CSV | Step 0 |
| `get_ect66_reference` | Look up ECT66 geocode for same/similar location | Step 0 |
| `geocode_gistda` | GISTDA Sphere keyword search (unlimited) | Step 2 |
| `geocode_nominatim` | Self-hosted Nominatim free-form search (unlimited) | Step 2 |
| `geocode_google` | Google Geocoding API (5,000/day quota) | Step 2, fallback |
| `place_on_map` | Place a candidate point on the interactive map. Triggers boundary check + context injection back to chat | Step 3 |
| `query_postgis` | Spatial query: point-in-polygon, nearest neighbor, boundary lookup | Steps 3-4 |
| `save_result` | Write geocode result + metadata to PostGIS | Step 5 |
| `read_memory` | Read tips/tricks text file for a specific tool or location type | Step 0 |
| `write_memory` | Append a tip/trick learned during this row's processing | Step 5 |

## Compute Budget

Per row:
- **Max tool calls**: 10 (configurable)
- **Timeout**: TBD (wall clock per row)
- The agent decides when to stop: if it feels the result is correct, or is the best available given the data, it stops early
- If budget exhausted without a good result, save with `manual_review_needed` tag and move on

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
- The map updating in real-time with each candidate point
- The final confidence assessment and tags
