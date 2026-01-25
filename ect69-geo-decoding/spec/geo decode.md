# ECT69 Geo Decoding Spec

## Input Files

- `ect69-geo-decoding/inputs/vote69_early_voting_ประชามตินอกเขต.csv`
- `ect69-geo-decoding/inputs/vote69_early_voting_เลือกตั้งล่วงหน้า.csv`
- `ect69-geo-decoding/inputs/vote69_early_voting_entities.csv`

## Output Files

- `ect69-geo-decoding/outputs/geo_decoded/vote69_early_voting_ประชามตินอกเขต_geo_decoded.csv`
- `ect69-geo-decoding/outputs/geo_decoded/vote69_early_voting_เลือกตั้งล่วงหน้า_geo_decoded.csv`

---

## Pipeline

### Step 1: Geocoding

Use Google API to convert addresses → coordinates. Add location hints (จังหวัด, อำเภอ) for better accuracy.

### Step 2: Validation & Flagging

Cross-check coordinates against administrative boundaries:

1. **Province-level:** `/home/ben/ddd/ninyawee/landmap/web/static/data/tha_admin2.geojson`
2. **Constituency-level:** `/home/ben/ddd/ninyawee/Thai-ECT-election-map/ECT Constituencies/2569/ShapeFiles`
   - Validate: จังหวัด, เขตเลือกตั้ง, สถานที่เลือกตั้งกลาง

---

## API Selection: Geocoding vs Text Search (Place API)

### The Problem with Geocoding API

Geocoding API can return **wrong locations** even with correct input.

**Example failure:**
> Searching "ศาลาประชาคมที่ว่าการอำเภอสทิงพระ สงขลา"
> → Geocoding returned: ศาลาประชาคมที่ว่าการอำเภอ**เชียรใหญ่ นครศรีธรรมราช** ❌

But searching the **exact same text** in Google Maps manually → **correct location** ✅

### Why?

Google Maps uses **Text Search / Place API** which matches against Google's POI database.
Geocoding API parses the text as an address string, which fails for Thai place names.

### Recommendation: Use Text Search (Place API)

| API | Accuracy | Cost per 100k |
|-----|----------|---------------|
| Geocoding API | Lower (address parsing) | ~$450 |
| Text Search (Place API) | Higher (POI matching) | ~$3,040 |

**Cost difference: ~6.7x more expensive**, but significantly better results for Thai venue names.

### Trade-off Decision

- If budget allows → **Text Search** for much better accuracy
- If budget constrained → Geocoding + aggressive validation + manual fixes
