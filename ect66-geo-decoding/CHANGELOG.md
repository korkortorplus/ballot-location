# Changelog

All notable changes to the ECT66 geocoding pipeline and data files are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [2.1.0] - 2025-12-30 - WeCheck Community Corrections Integration

### 🎯 Overview
Integrated community-sourced voting station corrections from the WeCheck platform. Applied 2 validated corrections and established infrastructure for future crowd-sourced improvements.

### Added

**Scripts:**
- `scripts/clean_wecheck_data.py` - Prepare WeCheck CSV (remove PII, English filename)
- `scripts/apply_wecheck_corrections.py` - Apply community corrections with validation
  - CLI with `--dry-run` for safety
  - Automatic backup creation
  - Comprehensive reporting (TXT + JSON)
  - Coordinate validation against tambon polygons

**Data Sources:**
- `inputs/wecheck_corrections.csv` - Community corrections (1,061 reports from 13 May 2023)
  - 2 validated corrections (Edited=TRUE with coordinates)
  - 254 name corrections (pending geocoding)
  - PII removed from original export

**Schema Additions:**
- `CorrectionSource` (str) - Data provenance: "Google" | "WeCheck" | "Synthetic"
- `UnitNameOriginal` (str) - Preserves original name before WeCheck update

**Documentation:**
- Updated DATA_SOURCES.md with WeCheck dataset details
- Updated .gitignore to exclude Thai-named WeCheck file (contains PII)

### Changed

**Data Quality:**
- Applied 2 WeCheck coordinate corrections:
  - UnitId 2101010915: Tier D → A+ (Community validated in ระยอง)
  - UnitId 1028350131: Tier A+ improved (Community refined coordinates)
- Tier A+ count: 29,746 → 29,748 (+0.002%)
- Tier D count: 65,503 → 65,501

**Files:**
- `inputs/WeCheck รายงานหน่วยเลือกตั้งที่ไม่ถูก.csv` → `inputs/wecheck_corrections.csv`
  (English filename, PII removed)

### Tier Distribution (v2.1.0)
- Tier A+: 29,748 units (31.2%)
  - Google validated: 29,746
  - Community validated: 2
- Tier D: 65,501 units (68.8%)

### Future Work
- 254 WeCheck corrections with names only (need re-geocoding)
- Estimated cost: $1.27 to geocode remaining corrections
- Potential quality improvement: +0.13% if successful

### Technical Details
- Pipeline integration: New Step 3.5 (after spatial validation)
- Validation: Tambon polygon intersection + Thailand bounds check
- Safety: Automatic backup before modifications
- Backward compatible: Can read with old code (new columns nullable)

---

## [2.0.0] - 2025-12-29 - Professionalization & Parquet Migration

### 🎯 Overview
Major refactoring to professionalize the codebase: separated concerns, migrated to Parquet-only format, and added comprehensive documentation.

### Added

**Code Organization:**
- `lib/models.py` - Data models extracted from DTO.py (UnitData, GMapEntry, UnitColor)
- `lib/valalis_client.py` - Async API client extracted from DTO.py (VA_Elect_API)
- `lib/__init__.py` - Package initialization
- `scripts/batch_geocode.py` - Refactored geocoder.py with argparse CLI
- `scripts/upload_to_valalis.py` - Upload script extracted from DTO.py with argparse CLI

**Documentation:**
- `README.md` - Comprehensive pipeline documentation with usage guide, schema, and troubleshooting (10 KB)
- `TIER_SYSTEM.md` - Detailed explanation of quality tier system (A+/D), validation process, and recommendations (12 KB)
- `.env.example` - Environment variables template for API keys
- `CHANGELOG.md` - This file tracking data and code changes

**Data Files (Parquet format):**
- `outputs/ect66_geocoded_validated.parquet` - Final validated dataset with Tier A+/D (7.5 MB, 95,249 rows)
  - **Source:** Converted from `intermediate/ect_geofilterd.pkl`
  - **Script:** Manual Python conversion (2025-12-29)
  - **Changes:** Dropped geometry columns (Point objects), kept Lat/Lng as floats
  - **Schema:** ProvinceId, ProvinceName, DivisionNumber, UnitId, Lat, Lng, PlaceId, TierLocation, etc.

- `intermediate/google_geocoding_raw.parquet` - Raw Google Maps geocoding results (17 MB, 95,249 rows)
  - **Source:** Converted from `outputs/ect_gpd.pkl`
  - **Script:** Manual Python conversion (2025-12-29)
  - **Changes:** Dropped GMapObjs list column, kept Lat/Lng/PlaceId

- `outputs/valalis_upload_response.parquet` - Valalis API upload response mapping (7.4 MB, 95,249 rows)
  - **Source:** Converted from `outputs/ect_api_result.pkl`
  - **Script:** Manual Python conversion (2025-12-29)
  - **Changes:** Parsed feature properties from nested API response

**DVC Tracking:**
- `outputs/ect66_geocoded_validated.parquet.dvc`
- `intermediate/google_geocoding_raw.parquet.dvc`
- `outputs/valalis_upload_response.parquet.dvc`

### Changed

**File Renames:**
- `02_transform_ect.ipynb` → `notebooks/01_transform_raw_ect.ipynb`
- `05_monitoring_ect_batches.ipynb` → `notebooks/02_parse_geocoding.ipynb`
- `03_fix_ect_locations.ipynb` → `notebooks/03_spatial_validation.ipynb`
- `04_monitoring_ect_quality.ipynb` → `notebooks/04_quality_assessment.ipynb`
- `inputs/หน่วยเลือกตั้ง 66 ทั่วประเทศ.csv` → `inputs/ect66_raw_voting_units.csv` (Thai → English filename)
- `intermediate/ect.parquet` → `intermediate/ect_cleaned.parquet` (clarify purpose)

**Data Migration:**
- Copied `../../datasets/outputs/ballot_complete.csv` → `outputs/ect66_complete.csv` (consolidate data locally)

**Code Improvements:**
- `scripts/batch_geocode.py`: Added argparse CLI with `--batch` flag (replaces manual function calls)
- `scripts/upload_to_valalis.py`: Added argparse CLI with `--batch-size` flag (replaces hardcoded value)
- All scripts: Updated file paths to new directory structure
- All scripts: Comprehensive docstrings with usage examples

### Removed

**Deprecated Code:**
- `DTO.py` - Split into lib/models.py + lib/valalis_client.py + scripts/upload_to_valalis.py
- `geocoder.py` - Replaced by scripts/batch_geocode.py

**Pickle Files (converted to Parquet):**
- `intermediate/ect_geofilterd.pkl` (37 MB) - Replaced by `outputs/ect66_geocoded_validated.parquet` (7.5 MB)
- `outputs/ect_gpd.pkl` (130 MB) - Replaced by `intermediate/google_geocoding_raw.parquet` (17 MB)
- `outputs/ect_api_result.pkl` (68 MB) - Replaced by `outputs/valalis_upload_response.parquet` (7.4 MB)

**Deprecated Data:**
- `../../datasets/outputs/ballot_complete_clean.csv.gz` - NER processing removed, file no longer useful
- `../../datasets/outputs/ballot_complete_clean.csv.gz.dvc` - Corresponding DVC file

**Old DVC References:**
- `outputs/ect_gpd.pkl.dvc`
- `intermediate/ect_geofilterd.pkl.dvc`
- `outputs/ect_api_result.pkl.dvc`

### Data Quality Notes

**Final Dataset Statistics (ect66_geocoded_validated.parquet):**
- Total units: 95,249
- Tier A+ (validated): 28,199 (29.6%)
- Tier D (synthetic): 65,503 (68.8%)
- Coverage: 100%

**Storage Savings:**
- Before: ~235 MB (Pickle + CSV + Parquet duplicates)
- After: ~31.7 MB (Parquet only)
- Reduction: 86% (203.3 MB saved)

### Migration Guide

**For Users Updating from v1.x:**

1. **Update imports in your code:**
   ```python
   # Old
   from DTO import UnitData, VA_Elect_API

   # New
   from lib.models import UnitData
   from lib.valalis_client import VA_Elect_API
   ```

2. **Update file paths:**
   ```python
   # Old
   df = pd.read_pickle("data/ect/ect_geofilterd.pkl")

   # New
   df = pd.read_parquet("outputs/ect66_geocoded_validated.parquet")
   ```

3. **Update script usage:**
   ```bash
   # Old - geocoder.py (manual batch selection in code)
   # Edit geocoder.py to uncomment run_batch1()
   python geocoder.py

   # New - CLI with argparse
   uv run python scripts/batch_geocode.py --batch 1
   uv run python scripts/batch_geocode.py --batch 2
   uv run python scripts/batch_geocode.py --batch 3
   ```

4. **Note on geometry column:**
   - Parquet files do NOT include Shapely Point geometry column
   - Use `geopandas.points_from_xy(df.Lng, df.Lat)` to recreate geometry if needed
   - Geometry was excluded to ensure Parquet compatibility

### Script Run History

This section tracks when data processing scripts were executed.

#### Initial Pipeline Run (Original Data)
- **Date:** 2023-05-XX (estimated)
- **Scripts:**
  - `02_transform_ect.ipynb` - Created `intermediate/ect.parquet`
  - `geocoder.py` - Batch 1, 2, 3 (created `ect_batch_*.pkl/csv/parquet`)
  - `05_monitoring_ect_batches.ipynb` - Created `ect_gpd.pkl`
  - `03_fix_ect_locations.ipynb` - Created `ect_geofilterd.pkl`
  - `DTO.py` - Uploaded to Valalis, created `ect_api_result.pkl`

#### Professionalization Migration (This Release)
- **Date:** 2025-12-29
- **Actions:**
  - Pickle → Parquet conversion (manual Python script)
  - File renames (bash mv commands)
  - Code refactoring (split DTO.py, refactor geocoder.py)
  - **No geocoding re-run** - reused cached results from `.cache/`
  - **No API calls** - conversions only

#### Next Scheduled Runs

**When to re-run the full pipeline:**
- [ ] When ECT releases updated voting unit data (annual)
- [ ] When tambon boundaries change (check DOL updates)
- [ ] When improving geocoding quality (new API services)

**Partial re-runs:**
- Re-run Step 3 (spatial validation) only if:
  - New tambon polygon data available
  - Tier quality threshold changes
- Re-run Step 5 (Valalis upload) only if:
  - Valalis collection needs refresh
  - Unit colors/statuses need updating

---

## [1.0.0] - 2023-05-XX - Initial Pipeline

### Added
- Original geocoding pipeline with Google Maps API
- Spatial validation using tambon polygons
- Valalis API upload capability
- Tier quality system (A+/D)

### Data Created
- `ect_geofilterd.pkl` - Final validated dataset (Pickle format)
- `ect_gpd.pkl` - Google geocoding results (Pickle format)
- `ect_api_result.pkl` - Valalis upload responses (Pickle format)
- `ballot_complete.csv` - Complete dataset export (CSV format)
- `ballot_complete_clean.csv.gz` - With NER tags (CSV gzipped)

### Statistics (Original)
- Total units geocoded: 95,249
- Google Maps API cost: ~$476 USD
- Processing time: ~6-8 hours (including manual confirmations)

---

## Future Planned Changes

### [2.1.0] - TBD - Improve Geocoding Quality
- [ ] Add Longdo Maps API as secondary geocoder
- [ ] Implement fuzzy tambon name matching
- [ ] Re-geocode Tier D units with alternative services
- **Expected impact:** +10-15% Tier A+ conversion

### [2.2.0] - TBD - Polygon Quality Improvements
- [ ] Update to newer OpenStreetMap boundaries
- [ ] Validate DOL polygons against satellite imagery
- [ ] Add Bangkok special administrative areas
- **Expected impact:** +2-3% accuracy in border areas

### [3.0.0] - TBD - Full Re-geocoding for ECT67
- [ ] Process ECT67 election data when available
- [ ] Implement learnings from ECT66 pipeline
- [ ] Consider hybrid geocoding approach (multi-service voting)

---

## Notes

### Versioning Scheme
- **Major (X.0.0)**: Breaking changes to data schema or file formats
- **Minor (x.X.0)**: New features, non-breaking data updates
- **Patch (x.x.X)**: Bug fixes, documentation updates

### Data Lineage

```
Raw ECT CSV (95,249 units)
  ↓ 01_transform_raw_ect.ipynb
intermediate/ect_cleaned.parquet (95,249 rows)
  ↓ scripts/batch_geocode.py --batch 1,2,3
intermediate/ect_batch_*.parquet (3 files)
  ↓ 02_parse_geocoding.ipynb
intermediate/google_geocoding_raw.parquet (95,249 rows, raw Google results)
  ↓ 03_spatial_validation.ipynb
outputs/ect66_geocoded_validated.parquet (95,249 rows, FINAL with Tier A+/D)
  ↓ scripts/upload_to_valalis.py
outputs/valalis_upload_response.parquet (95,249 rows, API responses)
```

### DVC Remote Sync Status

**Current remotes:**
- `bucket` (default): Cloudflare R2 S3 at `s3://open-source/ballot-location`
- `gdrive`: Google Drive at `gdrive://root/OpenSource/ballot-location/`
- `vedas`: SSH at `ssh://vedas/mnt/moon/open-source/ballot-location`

**Last sync:** 2025-12-29 (new Parquet files added, Pickle files removed)

---

## Contact

For questions about data changes or pipeline updates:
- Review the [README.md](README.md) for usage guide
- Review the [TIER_SYSTEM.md](TIER_SYSTEM.md) for quality details
- Check notebooks for implementation details
