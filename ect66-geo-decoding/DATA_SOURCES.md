# Data Sources

This document tracks all input data files for the ballot-location project.


## Geographic Data

### Shapefiles & GeoPackages

All shapefiles are located in the `shapefiles/` directory and are DVC tracked.

| File | Description | Size | DVC Tracked |
|------|-------------|------|-------------|
| `shapefiles/tambon_DOL_utf8.gpkg` | DOL tambon GeoPackage (UTF-8) - Department of Lands tambon boundaries | 96 MB | Yes |
| `shapefiles/BMA_ADMIN_SUB_DISTRICT.gpkg` | Bangkok sub-district boundaries | 1.6 MB | Yes |
| `shapefiles/เขตการเลือกตั้ง 66/` | ECT electoral district boundaries from [Thai-ECT-election-map-66](https://github.com/KittapatR/Thai-ECT-election-map-66) | - | No |


## Community Correction Data

### WeCheck Voting Station Corrections

| File | Description | Format | Rows | DVC |
|------|-------------|--------|------|-----|
| `wecheck_corrections.csv` | Community-sourced location corrections | CSV | 1,061 | No |

**Source**: WeCheck crowdsourcing platform
**Collection Date**: 13 May 2023
**Processing Status**: v2.1.0 integrated 2 validated corrections

**Content**:
- **Validated coordinates**: 2 rows (Edited=TRUE)
- **Corrected names only**: 254 rows (requires geocoding)
- **Pending verification**: 805 rows

**Data Quality Tiers**:
- High confidence: 2 rows (manually verified, coordinates provided)
- Medium confidence: 254 rows (corrected names, need geocoding)
- Low confidence: 805 rows (pending community verification)

**Privacy**:
- PII (phone numbers) removed during processing
- Original file excluded from git (see .gitignore)

**Integration**:
- Applied via: `scripts/apply_wecheck_corrections.py`
- Adds `CorrectionSource` column to track provenance
- Tier D → A+ promotion for validated corrections
- See CHANGELOG v2.1.0 for details


## Data License

All data is released under [ODC-By License](https://opendatacommons.org/licenses/by/1-0/).
