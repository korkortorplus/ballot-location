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

Main notebook: `map.ipynb` - Visualization of ballot locations on KeplerGL maps

## Data Sources

![Vote Location Data Evolution](assets/vote_location_evolution.svg)

| Source | Description | Coverage | Status |
|--------|-------------|----------|--------|
| Vote62 | Historical ballot data from 21 volunteers | 25,784 addresses, 8,056 verified | Complete |
| [voting-station-locations](https://github.com/heypoom/voting-station-locations) | Poom's advance voting stations (Google Places API) | ~444 locations (0.47%) | Reference |
| [election-station-66](https://github.com/thawirasm-j/election-station-66) | Visa's geocoded dataset (2-step Google API) | 81,427 locations (91.7% success) | Parallel effort |
| **Vote66 (Ours)** | **Multi-source geocoded dataset** | **95,249 locations (100%)** | **Production** |
| Vote69 | Future election data | TBD | Planned |

**Data Locations:**
- Poom's advance voting: `data/poom_ballot_location.csv`
- ECT boundaries: `data/SHP ECT attributes/` ([Thai-ECT-election-map-66](https://github.com/KittapatR/Thai-ECT-election-map-66))
- Vote62 historical: `data/source/vote62/` (DVC)

See [data/DATA_SOURCES.md](data/DATA_SOURCES.md) for complete data documentation.

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
