# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Thailand ballot location mapping project for election 2566 (Vote66). Aggregates voting station location data from various sources and visualizes it on maps using KeplerGL.

## Development Environment

- **Python**: Use `uv` for package management (not pip/python directly)
  - Run Python: `uv run python`
  - Sync dependencies: `uv sync`
- **Task runner**: mise (see `mise.toml` for available tasks)
- **Linting**: `ruff check . --fix`

## Key Commands

```bash
# Install dependencies
uv sync

# Setup git hooks (do this after first clone)
mise run setup:hooks

# Run Jupyter notebooks
uv run jupyter lab

# Download external input data
mise run download:inputs

# DVC data operations
dvc pull                    # Pull data from remote
mise run dvc-push           # Push data to remote (requires 1Password)

# Run pre-commit hooks manually
uv run pre-commit run --all-files
```

## Git Hooks

### Pre-commit Framework

This project uses [pre-commit](https://pre-commit.com/) to prevent accidentally committing large files to git.

**Installation:**
```bash
mise run setup:hooks
```

**What it does:**
- Blocks files >5MB from being committed to git (use DVC instead)
- Checks for merge conflicts and case conflicts
- Runs Ruff linter and formatter on Python files
- Validates YAML and TOML files

**If the hook blocks your commit:**
1. Remove from staging: `git reset HEAD <file>`
2. Track with DVC: `dvc add <file>`
3. Commit the .dvc metadata: `git add <file>.dvc .gitignore && git commit`

See docs/DVC_WORKFLOW.md for detailed DVC workflow.

## Data Architecture

### Data Sources
- **ECT shapefiles**: Electoral district boundaries from Thai-ECT-election-map-66
- **Ballot locations**: Geocoded voting stations from heypoom/voting-station-locations
- **Vote62 data**: Historical ballot data in SQLite/Parquet (DVC tracked)

### DVC Remotes
Data is managed with DVC on DagsHub S3 (`https://dagshub.com/wasdee/ballot-location.s3`)

### Directory Structure
- `ect66-geo-decoding/` - Main geocoding pipeline (self-contained)
  - `inputs/` - Raw ECT CSV data
  - `intermediate/` - Processing artifacts (Parquet)
  - `outputs/` - Final production data (Parquet)
  - `notebooks/` - Analysis & ETL notebooks
  - `scripts/` - Executable Python scripts
  - `lib/` - Reusable Python modules
  - `shapefiles/` - Geographic data (tambon polygons)
- `notes/` - Documentation and analysis notes

## Primary Notebooks

- `ect66-geo-decoding/notebooks/01_transform_raw_ect.ipynb` - Transform raw CSV
- `ect66-geo-decoding/notebooks/02_parse_geocoding.ipynb` - Parse Google results
- `ect66-geo-decoding/notebooks/03_spatial_validation.ipynb` - Spatial validation & tier assignment
- `ect66-geo-decoding/notebooks/04_quality_assessment.ipynb` - Quality analysis

See `ect66-geo-decoding/README.md` for complete pipeline documentation.

## ECT66 Geocoding Pipeline

The main effort: geocoding **95,249 voting stations** from official ECT data.

**Final Output:** `ect66-geo-decoding/outputs/ect66_geocoded_validated.parquet`
- **Coverage:** 100% (all 95,249 units have coordinates)
- **Tier A+ (29.6%):** Google geocoded + validated within correct tambon
- **Tier D (68.8%):** Random point generated within tambon (Google failed)

**Key Scripts:**
- `uv run python ect66-geo-decoding/scripts/batch_geocode.py --batch 1|2|3` - Batch geocoding
- `uv run python ect66-geo-decoding/scripts/upload_to_valalis.py` - Upload to Valalis API

See `ect66-geo-decoding/README.md` for detailed pipeline documentation.

## Key Libraries

- `geopandas` - Geospatial data handling
- `keplergl` - Map visualization
- `pythainlp` - Thai NLP for text processing
- `pyarrow` - Parquet file support
- `httpx` - Async HTTP client
- `pydantic` - Data validation
- `joblib` - Caching for geocoding
