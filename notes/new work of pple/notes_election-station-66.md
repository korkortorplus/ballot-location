# Election Station 66 - Data Cleaning Notes

## Project Overview
This project aims to geocode (find lat/long coordinates) for Thailand's election polling stations (หน่วยเลือกตั้ง) for the 2566 (2023) election. The goal is to create Open Data for election maps and analysis.

## Data Files
| File | Description |
|------|-------------|
| `station66_distinct_clean.csv` | Main election station data (~81,427 rows) |
| `thailand_province_amphoe_tambon.csv` | Reference data for Thai administrative divisions |
| `station66_distinct_clean_super.csv` | Cleaned version after text processing |

## Data Schema
| Field | Description |
|-------|-------------|
| `provinceNumber` | Province code (e.g., 10 = Bangkok) |
| `province` | Province name (Thai) |
| `registrar_code` | Registrar office code |
| `registrar` | Registrar office name |
| `subdis_code` | Subdistrict code |
| `subdistrict` | Subdistrict name (ตำบล/แขวง) |
| `electorate` | Electoral district number |
| `location` | Polling station location description |
| `latitude` | Latitude coordinate |
| `longitude` | Longitude coordinate |

---

## Data Cleaning Process

### 1. Thai Number Conversion
Convert Thai numerals to Arabic numerals:
```python
thai_numbers = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
df["location"] = df["location"].str.translate(thai_numbers)
```

### 2. Remove Unwanted Keywords
Remove common Thai words that add noise to geocoding:
- `เต็นท์` / `เต้นท์` (tent)
- `ปะรำ` (canopy/pavilion)
- `บริเวณ` (area/vicinity)

### 3. Clean Bracketed Content
- Remove numbered parentheses: `(1)`, `(2)`, etc.
- Remove Thai character parentheses: `(ก)`, `(ข)`, etc.

### 4. Normalize Whitespace
- Remove double/multiple spaces
- Normalize spaces around parentheses
- Clean spaces around hyphens

### 5. Extract District from Registrar
Create `proposed_district` by removing prefixes from `registrar`:
- `ท้องถิ่น`, `เทศบาล`, `อำเภอ`, `ตำบล`, `เขต`, `แขวง`

---

## Data Enrichment Process

### 1. Join with Administrative Reference Data
Merge election data with Thailand administrative divisions data:
- Match on: `subdistrict`, `proposed_district`, `province`
- Fallback: Match on `subdistrict` and `province` only
- Get English names and PCODE identifiers

### 2. Build Full Address for Geocoding
Construct proper Thai address format:
```python
# For Bangkok
address = f"{location} แขวง{subdistrict} เขต{ADM2_TH} {province} ประเทศไทย"

# For other provinces
address = f"{location} ตำบล{subdistrict} อำเภอ{ADM2_TH} จังหวัด{province} ประเทศไทย"
```

---

## Geocoding Process

### 1. Google Places Text Search API
Get `place_id` from address text:
```python
base_url = "https://places.googleapis.com/v1/places:searchText"
# Returns place_id like "ChIJsQW2s6CZ4jARKCwV_40G50c"
```

### 2. Google Geocode API
Get lat/long from place_id:
```python
base_url = f"https://geocode.googleapis.com/v4beta/geocode/places/{place_id}"
# Returns latitude/longitude coordinates
```

### 3. Batch Processing
- Process in chunks (~40,000 rows per chunk)
- Respect rate limits (600 requests/minute)
- Handle API errors (503, 500) gracefully
- Save progress incrementally

### 4. Results
- Success rate: ~91.7%
- Failed requests: ~8.3% (usually due to ambiguous locations)

---

## Validation Approaches

### 1. Address Component Matching
Compare geocoded address components with expected values:
- Province (ADM1) matching
- District (ADM2) matching
- Subdistrict (ADM3) matching

### 2. Distance Validation
Use Haversine formula to check if geocoded point is reasonable distance from expected area centroid.

---

## Key Insights

1. **Thai text normalization is critical** - Thai numerals, special characters, and common words must be cleaned before geocoding

2. **Address format matters** - Using proper Thai address format (ตำบล/แขวง, อำเภอ/เขต) significantly improves geocoding accuracy

3. **Two-step geocoding** - First get place_id via text search, then get coordinates via geocode API provides better results than direct geocoding

4. **Batch processing with checkpoints** - Essential for processing 80,000+ records with API rate limits and potential failures

5. **Reference data enrichment** - Joining with administrative boundary data enables validation and provides English names
