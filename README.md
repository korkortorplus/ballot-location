# ballot-location

crack the location of Thailand ballot location #vote66

## Why?

1. สนับสนุนการทำงานอาสาสมัคร ที่นับคะแนน

## Getting Started

### Prerequisites

- [uv](https://docs.astral.sh/uv/) - Python package manager
- [mise](https://mise.jdx.dev/) - Task runner (optional)
- [DVC](https://dvc.org/) - Data version control

### Installation

```bash
# Install dependencies
uv sync
```

### Pull Data (DVC)

Data is stored on [DagsHub](https://dagshub.com/wasdee/ballot-location). To pull data:

```bash
# Configure DVC credentials (one-time setup)
dvc remote modify origin --local access_key_id <your-dagshub-token>
dvc remote modify origin --local secret_access_key <your-dagshub-token>

# Pull all data
dvc pull
```

**Get your token:** Go to [DagsHub](https://dagshub.com) > Settings > Tokens > Create new token

**Alternative - Pull without account:** Download directly from [DagsHub repo files](https://dagshub.com/wasdee/ballot-location/src/main/data)

```bash
# Download external input data (ECT shapefiles, ballot locations)
mise run download:inputs
```

### Running Notebooks

```bash
uv run jupyter lab
```

### ECT66 Geocoding Pipeline

```bash
cd ect66-geo-decoding

# Run complete pipeline (see ect66-geo-decoding/README.md for details)
uv run jupyter notebook notebooks/01_transform_raw_ect.ipynb
uv run python scripts/batch_geocode.py --batch 1
uv run jupyter notebook notebooks/03_spatial_validation.ipynb

# Final output: outputs/ect66_geocoded_validated.parquet
```

See [ect66-geo-decoding/README.md](ect66-geo-decoding/README.md) for complete pipeline documentation.


## ECT66 Geocoding Pipeline

Our main effort: geocoding **95,249 voting stations** from official ECT data.

**Source Data:** [ECT Official Spreadsheet](https://docs.google.com/spreadsheets/d/19oosGgL5OC7Qdu5RwYDEkqQSsNgkThMS22pEKpz77qc/edit?gid=1984776718#gid=1984776718)

```
ect66-geo-decoding/
├── inputs/
│   └── ect66_raw_voting_units.csv     # 95,249 rows, 30 MB
│
├── notebooks/
│   ├── 01_transform_raw_ect.ipynb     # Transform raw CSV
│   ├── 02_parse_geocoding.ipynb       # Parse Google results
│   ├── 03_spatial_validation.ipynb    # Spatial validation & tier assignment
│   └── 04_quality_assessment.ipynb    # Quality analysis
│
├── scripts/
│   ├── batch_geocode.py               # Google Maps batch geocoding
│   └── upload_to_valalis.py           # Upload to Valalis API
│
├── lib/
│   ├── models.py                      # UnitData, GMapEntry models
│   └── valalis_client.py              # VA_Elect_API async client
│
├── intermediate/
│   ├── ect_cleaned.parquet            # 4.8 MB
│   ├── ect_batch_{1,2,3}.parquet      # 25 MB total
│   └── google_geocoding_raw.parquet   # 18 MB
│
├── outputs/
│   ├── ect66_geocoded_validated.parquet  # FINAL (7.9 MB) ✅
│   └── valalis_upload_response.parquet   # 7.8 MB
│
└── shapefiles/                        # Geographic reference data
    ├── tambon_DOL_utf8.gpkg           # 96 MB
    ├── BMA_ADMIN_SUB_DISTRICT.gpkg    # 1.6 MB
    └── เขตการเลือกตั้ง 66/             # ECT electoral districts
```

## Data Sources

| Source | Description | Coverage | Status |
|--------|-------------|----------|--------|
| **Vote66 (ECT66)** | **Official ECT data with Google geocoding + spatial validation. Quality: 29.6% Tier A+ (validated), 68.8% Tier D (synthetic)** | **95,249 locations (100%)** | **Production** |
| Vote62 | Historical ballot data from 21 volunteers | 25,784 addresses, 8,056 verified | Complete |
| [voting-station-locations](https://github.com/heypoom/voting-station-locations) | Poom's advance voting stations (Google Places API) | ~444 locations (0.47%) | Reference |
| [election-station-66](https://github.com/thawirasm-j/election-station-66) | Visa's geocoded dataset (2-step Google API) | 81,427 locations (91.7% success) | Parallel effort |
| Vote69 | Future election data | TBD | Planned |

**Data Locations:**
- ECT66 geocoded: `ect66-geo-decoding/outputs/ect66_geocoded_validated.parquet` (DVC)
- Poom's advance voting: Downloaded via `mise run download:inputs:poom`
- เขตการเลือกตั้ง 66: `ect66-geo-decoding/shapefiles/เขตการเลือกตั้ง 66/`
- Tambon shapefiles: `ect66-geo-decoding/shapefiles/` (DVC)

See [ect66-geo-decoding/README.md](ect66-geo-decoding/README.md) and [ect66-geo-decoding/TIER_SYSTEM.md](ect66-geo-decoding/TIER_SYSTEM.md) for complete documentation.

## Attempts

1. [Vote62](https://volunteer.vote62.com/apply/reserve-form/) - ถามเอาจากอาสา เลือกหน่วยเลือกตั้ง ผ่าน [เว็ปมหาดไทย](https://boraservices.bora.dopa.go.th/election/enqelection/)
    1. เข้าถึงข้อมูลล่าสุดที่ [voting-station-locations](https://github.com/heypoom/voting-station-locations)
    2. [เว็ปมหาดไทย](https://boraservices.bora.dopa.go.th/election/enqelection/) อยู่หลัง captcha ทำให้ไม่สามารถเข้าถึงได้
2. We Watch - หาเอาจากเว็ปกกต. เช่น <https://www.ect.go.th/phuket/ewt_dl_link.php?nid=506>
3. We Watch - ขอเลขา กกต. แล้วไม่ได้

## Map Visualization

- [Ballot Heatmap](https://kepler.gl/demo/map/dropbox?path=/apps/kepler.gl%20(managed%20by%20uber%20technologies,%20inc.)/keplergl_0a86aemm.json)
- [N Ballot Count](https://kepler.gl/demo/map?mapUrl=https://dl.dropboxusercontent.com/s/l4syuquu1y58gy5/keplergl_pg7bm8g.json)

## Contributing

ใครสนใจ Task ไหนหยิบไปทำได้เลย แล้ว PR มาเลยครับ

มีอะไรทักมาได้เลยครับ ที่ดิส https://discord.gg/nNB8zqhQAW

## License

ข้อมูลทั้งหมดจะเผยแพร่ภายใต้ [ODC-By License](https://opendatacommons.org/licenses/by/1-0/)
