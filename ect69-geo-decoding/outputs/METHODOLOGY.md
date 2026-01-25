# ECT69 Early Voting Geocoding — Methodology

## Pipeline Overview

```
inputs/vote69_early_voting_เลือกตั้งล่วงหน้า.csv
    ↓ Entity extraction (parse Thai location strings)
inputs/vote69_early_voting_entities.csv
    ↓ Google Geocoding API
intermediate/early_voting_geocoded_raw.parquet
    ↓ Spatial validation (point-in-polygon)
intermediate/early_voting_validated.parquet
    ↓ Merge back to source
outputs/*_geo_decoded.csv
```

## Step 0: Entity Extraction (Unit Name Processing)

**Script:** `scripts/extract_entities_glm.py`

Raw location strings (`สถานที่เลือกตั้งกลาง`) are parsed into structured components before geocoding. This step produces `inputs/vote69_early_voting_entities.csv`.

### Output Schema

| Field | Description |
|-------|-------------|
| `location_name` | Core venue name (used for geocoding) |
| `location_type` | Classified venue type |
| `area_prefix` | Leading descriptor (บริเวณ, เต็นท์, ลานจอดรถ, etc.) |
| `buildings` | Building names (supports multiple) |
| `floor` | Floor level (ชั้น 1, ชั้นล่าง, etc.) |
| `extra_info` | Parenthetical details |
| `subdistrict` | แขวง (BKK) / ตำบล (province) |
| `district` | เขต (BKK) / อำเภอ (province) |
| `original` | Original raw text (join key) |
| `geocode_query` | Final query string sent to Google |

### Location Types

| Type | Thai Keywords | Frequency |
|------|---------------|-----------|
| `assembly_hall` | หอประชุม | 45% |
| `school` | โรงเรียน | 24% |
| `temple` | วัด | 11% |
| `dome` | โดม | 9% |
| `government_office` | สำนักงาน, ที่ว่าการ | 7% |
| `university` | มหาวิทยาลัย | 3% |
| `mall` | ศูนย์การค้า | <1% |
| `sports_center` | ศูนย์กีฬา, โรงยิม | <1% |
| `other` | — | — |

### Parsing Rules

1. **Administrative suffix extraction** — Parse แขวง/ตำบล (subdistrict) and เขต/อำเภอ (district) from end of string.
2. **Multiple buildings** — Split on `และ`, `กับ`, or `,` when multiple buildings are listed.
3. **Parenthetical information** — Extract `(ฝั่ง...)` direction, `(ซอย...)` soi reference, `(ชั่วคราว)` temporary markers, `(alias)` nicknames.
4. **Floor extraction** — Extract `ชั้น {N}` or `ชั้นล่าง`.
5. **Area prefix removal** — Strip leading descriptors (บริเวณ, เต็นท์บริเวณ, ลานจอดรถ, etc.) to get the core place name.

### Examples

| Raw Input | → `geocode_query` |
|-----------|-------------------|
| บริเวณสำนักงานเขตพระนคร แขวงวัดสามพระยา | สำนักงานเขตพระนคร |
| เต็นท์ลานจอดรถโลตัสพระราม 3 (ฝั่งถนนนราธิวาสฯ) แขวงช่องนนทรี | โลตัสพระราม 3 |
| อาคารกีฬาเวสน์ 1 และ อาคารกีฬาเวสน์ 2 ศูนย์เยาวชนฯ (ไทย-ญี่ปุ่น) | ศูนย์เยาวชนกรุงเทพมหานคร (ไทย-ญี่ปุ่น) |
| ห้องพระราม 2 ฮอลล์ ชั้น 4 ศูนย์การค้าเซ็นทรัลพลาซา พระราม 2 | ศูนย์การค้าเซ็นทรัลพลาซา พระราม 2 |
| หอประชุมโรงเรียนคลองท่อมราษฎร์รังสรรค์ อำเภอคลองท่อม | โรงเรียนคลองท่อมราษฎร์รังสรรค์ |

### Geocoding Priority

The `geocode_query` is constructed to maximize geocoding accuracy:
- Use `location_name` as the primary query
- Pass `subdistrict` and `district` as component hints (not in the query string)
- Fallback: use the full raw string if parsing fails

## Step 1: Geocoding

**Script:** `scripts/geocode_early_voting.py`

Each location is geocoded via the Google Maps Geocoding API with component filtering:

| Parameter | Source Column | Google Component |
|-----------|--------------|------------------|
| `street_address` | `geocode_query` | Main query |
| `subdistrict` | `subdistrict` | `sublocality_level_2` |
| `district` | `district` | `sublocality_level_1` |
| `country` | hardcoded "TH" | `country` |

- Results are cached locally (joblib in `.cache/`) to avoid redundant API calls on re-runs.
- The `geocode_query` column was pre-processed from raw location names by extracting the core place name (e.g., "บริเวณสำนักงานเขตพระนคร แขวงวัดสามพระยา" → "สำนักงานเขตพระนคร").

## Step 2: Spatial Validation

**Notebook:** `notebooks/01_spatial_validation.ipynb`

Each geocoded point is validated against its expected **ECT 2569 constituency polygon** using a point-in-polygon test.

**Boundary source:** `Thai-ECT-election-map/ECT Constituencies/2569/ShapeFile/2569_Election_Constituencies.shp` (400 constituencies, matched by `P_name` + `CONS_no`)

**Logic:**
1. For each location, find the constituency polygon matching its `จังหวัด` + `เขตเลือกตั้ง`.
2. If the Google geocoded point falls **within** the constituency polygon → `within_boundary = True`.
3. If the Google API returned multiple candidates, pick the first one that passes the boundary check.
4. If no candidate passes → `within_boundary = False` (coordinates are still from Google, just flagged).

## Output Columns

| Column | Type | Description |
|--------|------|-------------|
| `Latitude` | float | Latitude (WGS84) |
| `Longitude` | float | Longitude (WGS84) |
| `PlaceId` | str | Google Maps Place ID |
| `FormattedAddress` | str | Google's formatted address string |
| `geocoded` | bool | Google Geocoding API returned at least one result |
| `within_boundary` | bool | The geocoded point falls within the expected constituency polygon |

## Interpreting the Flags

| `geocoded` | `within_boundary` | Interpretation |
|:---:|:---:|---|
| True | True | High confidence — Google found it and it's in the right area |
| True | False | Needs review — Google found a location but it's outside the expected constituency (could be a boundary edge case or geocoding error) |
| False | False | No result — Google couldn't geocode this query |

## Coverage

**เลือกตั้งล่วงหน้า (424 locations):**
- geocoded: 424/424 (100%)
- within_boundary: 373/424 (88%)

**ประชามตินอกเขต (50 locations):**
- Matched to entities: 23/50 (46%)
- The 27 unmatched have different location names from the entities file and were not geocoded in this pass.
