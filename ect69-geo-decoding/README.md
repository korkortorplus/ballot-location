# ECT69 Geo-Decoding Pipeline

ETL pipeline to extract geocoding contributions from [PPLEThai/election-station-66](https://github.com/PPLEThai/election-station-66) and classify them as manual (human) or scripted (automated batch).

## Overview

This pipeline:
1. Extracts commit history from a local git clone
2. Parses CSV changes to identify coordinate updates
3. Classifies each commit as "manual" or "scripted" based on:
   - Number of rows changed
   - Commit message patterns
   - Time gaps between commits
4. Builds a final dataset with source attribution

## Quick Start

```bash
# Run the ETL
uv run python ect69-geo-decoding/scripts/extract_pr_contributions.py \
    --source-repo ~/ddd/ninyawee/election-station-66
```

## Directory Structure

```
ect69-geo-decoding/
├── intermediate/
│   ├── commits_metadata.parquet   # Commit metadata with classification
│   └── row_changes.parquet        # Row-level change history
├── outputs/
│   └── station66_with_source.parquet  # Final dataset with attribution
├── scripts/
│   └── extract_pr_contributions.py    # Main ETL script
├── lib/
│   ├── git_utils.py               # Git subprocess utilities
│   └── models.py                  # Pydantic data models
└── README.md
```

## Classification Logic

| Type | Criteria |
|------|----------|
| **Scripted** | Message matches "Add latitude/longitude for rows X-Y", or >100 rows changed, or <30s between commits |
| **Manual** | Thai location name in message, ≤50 rows, >5min gap between commits |
| **Uncertain** | Doesn't clearly match either pattern |

## Output Schema

`outputs/station66_with_source.parquet`:

| Column | Type | Description |
|--------|------|-------------|
| province_number | int | Province code |
| province | str | Province name (Thai) |
| registrar_code | int | Registrar code |
| registrar | str | Registrar name |
| subdis_code | int | Subdistrict code |
| subdistrict | str | Subdistrict name |
| electorate | int | Electorate number |
| location | str | Polling station location |
| latitude | float | Latitude (WGS84) |
| longitude | float | Longitude (WGS84) |
| has_coords | bool | Whether coordinates exist |
| source_commit | str | Commit hash that last added/updated coords |
| source_author | str | Author who last added/updated coords |
| source_classification | str | "manual", "scripted", or "none" |
| source_timestamp | int | Unix timestamp of source commit |

## Results Summary

From starting commit `1be4945dce44986c64a1b6ee2fb627b39104b2c0`:

- **137 total commits** (118 non-merge)
- **Commit classification**:
  - Scripted: 83 commits
  - Manual: 27 commits
  - Uncertain: 7 commits
- **91,361 row changes** tracked
- **81,427 rows** in final output (99.997% with coordinates)

## Data Source

- **Repository**: `~/ddd/ninyawee/election-station-66`
- **Starting commit**: `1be4945dce44986c64a1b6ee2fb627b39104b2c0`
- **Main file**: `station66_distinct_clean.csv`
