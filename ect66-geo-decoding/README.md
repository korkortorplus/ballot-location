# ECT66 Geocoding Pipeline

Geocodes 95,249 voting units for Thailand's 2566 (2023) election using Google Maps API with spatial validation against tambon (sub-district) polygons.

## Overview

This pipeline transforms raw Electoral Commission of Thailand (ECT) voting station data into geocoded, spatially-validated coordinates suitable for mapping and analysis.

**Key Features:**
- Google Maps API geocoding with component filtering for Thai addresses
- Spatial validation using Department of Lands tambon boundaries
- Quality tier system (A+/D) to indicate geocoding reliability
- Batch processing to manage API quotas
- Parquet-based data format for efficiency

## Data Flow

```
[Raw CSV 95k units] → [Transform] → [Geocode 3 batches] → [Spatial Validate] → [FINAL Parquet]
     30 MB               4.8 MB            25 MB total            ~10 MB              7.5 MB
```

## Pipeline Steps

### Step 1: Transform Raw ECT Data
**Notebook:** `notebooks/01_transform_raw_ect.ipynb`

- **Input:** `inputs/ect66_raw_voting_units.csv` (95,249 rows)
- **Process:**
  - Strip whitespace from unit names
  - TitleCase column names
  - Basic data cleaning
- **Output:** `intermediate/ect_cleaned.parquet` (4.8 MB)

### Step 2: Batch Geocode with Google Maps
**Script:** `scripts/batch_geocode.py`

- **Input:** `intermediate/ect_cleaned.parquet`
- **Process:**
  - Batch 1 (rows 0-1k): Testing batch with 1,000 units
  - Batch 2 (rows 1k-10k): Medium volume with 9,000 units
  - Batch 3 (rows 10k+): High volume with ~85,249 remaining units
  - Uses joblib caching in `.cache/` to avoid redundant API calls
  - Component filtering: province + tambon for better Thai address accuracy
- **Output:**
  - `intermediate/ect_batch_1.parquet`
  - `intermediate/ect_batch_2.parquet`
  - `intermediate/ect_batch_3.parquet`
  - `intermediate/google_geocoding_raw.parquet` (combined, 16.8 MB)

**Run with:**
```bash
uv run python scripts/batch_geocode.py --batch 1
uv run python scripts/batch_geocode.py --batch 2
uv run python scripts/batch_geocode.py --batch 3
```

### Step 3: Spatial Validation & Tier Assignment
**Notebook:** `notebooks/03_spatial_validation.ipynb`

- **Input:**
  - Google geocoding results
  - `shapefiles/tambon_DOL_utf8.gpkg` (Department of Lands tambon polygons)
  - `shapefiles/BMA_ADMIN_SUB_DISTRICT.gpkg` (Bangkok sub-districts)
  - `shapefiles/เขตการเลือกตั้ง 66/2566_TH_ECT_attributes.shp` (ECT electoral districts)
- **Process:**
  - Load tambon/district shapefiles
  - Filter Google results: keep only points within correct tambon polygon
  - Generate random points within tambon for unmatched units
  - Assign quality tiers (see [TIER_SYSTEM.md](TIER_SYSTEM.md))
- **Output:** `outputs/ect66_geocoded_validated.parquet` ✅ **FINAL** (7.5 MB)

**Quality Results:**
- **Tier A+ (28,199 units, 29.6%)**: Google geocoded + validated within correct tambon
- **Tier D (65,503 units, 68.8%)**: Random point generated within tambon (Google failed or outside bounds)
- **Coverage: 100%** - All 95,249 units have coordinates

### Step 4: Quality Assessment
**Notebook:** `notebooks/04_quality_assessment.ipynb`

- Analyze coordinate duplicates (28k duplicates before validation)
- Visualize on maps with CartoDB basemap
- Generate quality reports
- Identify problematic geocoding results

### Step 5: Upload to Valalis API (Optional)
**Script:** `scripts/upload_to_valalis.py`

- **Input:** `outputs/ect66_geocoded_validated.parquet`
- **Process:**
  - Delete all existing units from Valalis collection
  - Upload in batches (default: 200 units/batch)
  - Async upload with concurrency limit (4 simultaneous requests)
  - Save API response mapping
- **Output:** `outputs/valalis_upload_response.parquet` (7.4 MB)

**Run with:**
```bash
uv run python scripts/upload_to_valalis.py --batch-size 200
```

## Output Schema

### ect66_geocoded_validated.parquet (FINAL OUTPUT)

| Column | Type | Description |
|--------|------|-------------|
| ProvinceId | int | Province code (10 = Bangkok, etc.) |
| ProvinceName | str | Full province name (Thai) with "จังหวัด" prefix |
| DivisionNumber | int | Electoral district number |
| DistrictName | str | Amphoe/district name (Thai) |
| SubDistrictName | str | Tambon/sub-district name (Thai) |
| UnitId | int | Unique voting unit ID (10-digit) |
| UnitNumber | int | Unit number within tambon |
| UnitName | str | Voting station name/address (Thai) |
| Lat | float | Latitude (WGS84, EPSG:4326) |
| Lng | float | Longitude (WGS84, EPSG:4326) |
| PlaceId | str | Google Place ID (empty string for Tier D) |
| Formatted_Address | str | Google formatted address (empty for Tier D) |
| **TierLocation** | **str** | **Quality tier: "A+" or "D"** |

## Prerequisites

### Environment Variables
Create a `.env` file (see `.env.example`):
```bash
# Google Maps API Key (for scripts/batch_geocode.py)
GMAP_API_KEY=your_google_maps_api_key_here

# Valalis API Key (for scripts/upload_to_valalis.py, optional)
VA_DB_API_KEY=your_valalis_api_key_here
```

### Required Shapefiles
These files are included in the `shapefiles/` directory (DVC tracked):
- `shapefiles/tambon_DOL_utf8.gpkg` (DOL tambon boundaries, 96 MB)
- `shapefiles/BMA_ADMIN_SUB_DISTRICT.gpkg` (Bangkok, 1.6 MB)
- `shapefiles/เขตการเลือกตั้ง 66/` (ECT electoral districts shapefile)

## Installation

```bash
# Install dependencies (from project root)
uv sync

# Copy environment template
cd ect66-geo-decoding
cp .env.example .env
# Edit .env and add your GMAP_API_KEY
```

## Usage

### Complete Pipeline

```bash
cd ect66-geo-decoding

# Step 1: Transform raw data
uv run jupyter notebook notebooks/01_transform_raw_ect.ipynb
# Execute all cells

# Step 2: Batch geocode (interactive, requires manual confirmation between batches)
uv run python scripts/batch_geocode.py --batch 1
# Press Enter to continue...
uv run python scripts/batch_geocode.py --batch 2
# Press Enter to continue...
uv run python scripts/batch_geocode.py --batch 3

# Step 3: Spatial validation & tier assignment
uv run jupyter notebook notebooks/03_spatial_validation.ipynb
# Execute all cells

# Step 4 (optional): Quality assessment
uv run jupyter notebook notebooks/04_quality_assessment.ipynb

# Step 5 (optional): Upload to Valalis
uv run python scripts/upload_to_valalis.py --batch-size 200
```

### Quick Access to Final Output

```python
import pandas as pd

# Load final validated data
df = pd.read_parquet("outputs/ect66_geocoded_validated.parquet")

# Filter by quality tier
tier_a = df[df.TierLocation == "A+"]  # High quality (28,199 units)
tier_d = df[df.TierLocation == "D"]   # Synthetic (65,503 units)

# Basic statistics
print(f"Total units: {len(df):,}")
print(f"Tier A+: {len(tier_a):,} ({len(tier_a)/len(df)*100:.1f}%)")
print(f"Tier D: {len(tier_d):,} ({len(tier_d)/len(df)*100:.1f}%)")
```

## Quality Tier System

See [TIER_SYSTEM.md](TIER_SYSTEM.md) for detailed explanation of the A+/D tier system.

**Quick Summary:**
- **Tier A+ (Premium)**: Geocoded by Google Maps + validated to be within correct tambon polygon
- **Tier D (Fallback)**: Random point generated within tambon polygon (Google failed or was incorrect)

## Architecture

```
ect66-geo-decoding/
├── lib/                  # Reusable Python modules
│   ├── models.py         # UnitData, GMapEntry, UnitColor
│   └── valalis_client.py # VA_Elect_API (async HTTP client)
├── scripts/              # Executable scripts
│   ├── batch_geocode.py  # Google Maps batch geocoding
│   └── upload_to_valalis.py # Upload to Valalis API
├── notebooks/            # Analysis & ETL notebooks
│   ├── 01_transform_raw_ect.ipynb
│   ├── 02_parse_geocoding.ipynb
│   ├── 03_spatial_validation.ipynb
│   └── 04_quality_assessment.ipynb
├── inputs/               # Raw source data (30 MB)
├── intermediate/         # Processing artifacts (Parquet only, 25 MB total)
├── outputs/              # Final production data (Parquet only, 15 MB total)
└── shapefiles/           # Geographic reference data (96+ MB, DVC tracked)
```

## Key Dependencies

- **googlemaps**: Google Maps API client for geocoding
- **geopandas**: Spatial data operations and polygon validation
- **httpx**: Async HTTP for Valalis API
- **pydantic**: Data validation (UnitData model)
- **joblib**: Geocoding cache management
- **pandas**: Data processing
- **pyarrow**: Parquet file support

## Known Issues

### The 28k Duplicate Coordinate Problem
**Issue:** In raw Google geocoding results (`intermediate/google_geocoding_raw.parquet`), 28,448 units have identical coordinates at (15.870032, 100.992541) - Google's fallback for "ประเทศไทย" (Thailand).

**Resolution:** Spatial validation (Step 3) demotes these to Tier D and generates proper random points within the correct tambon polygons.

### Missing Tambon Polygons
**Issue:** 1,046 units couldn't find matching tambon polygons (typos in names, new administrative boundaries).

**Fallback:** Uses ECT electoral district polygons instead. All 95,249 units eventually matched to some polygon.

## Cost Estimation

### Google Maps API Costs
- **Geocoding API**: $5.00 per 1,000 requests
- **Total requests**: 95,249 units
- **Estimated cost**: ~$476.25

**Note:** Joblib caching in `.cache/` directory saves results, so re-running the pipeline doesn't incur additional API costs.

## Troubleshooting

### "GMAP_API_KEY not found"
- Ensure `.env` file exists with `GMAP_API_KEY=...`
- Check you're in the `ect66-geo-decoding/` directory

### "ect_cleaned.parquet not found"
- Run Step 1 (01_transform_raw_ect.ipynb) first

### Geocoding is slow
- Expected: ~95k units takes several hours depending on batch size
- Check `.cache/` directory for cached results
- Monitor Google Cloud Console for API quota usage

### Import errors for lib modules
- Ensure `lib/__init__.py` exists
- Check Python path includes parent directory

## License

Data released under [ODC-By License](https://opendatacommons.org/licenses/by/1-0/).

## References

- **ECT Electoral Districts**: [Thai-ECT-election-map-66](https://github.com/KittapatR/Thai-ECT-election-map-66)
- **Valalis API**: https://b-2.i-bitz.world
- **Google Maps Geocoding**: https://developers.google.com/maps/documentation/geocoding
