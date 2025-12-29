# Comparison: Election-Station-66 vs Ballot-Location Project

## 1. DATA SOURCES

| Aspect | Election-Station-66 | Ballot-Location (Ours) |
|--------|---------------------|------------------------|
| **Primary Source** | ECT Station 66 data (single CSV, 81,427 rows) | Multiple sources: Vote62 API + ECT PDFs (95,249 rows) |
| **Data Origin** | Pre-compiled CSV from unknown origin | Direct API extraction + PDF scraping |
| **Reference Data** | `thailand_province_amphoe_tambon.csv` (7,438 rows) | `tambon_DOL_utf8.gpkg` (96MB official DOL boundaries) |
| **Data Freshness** | Static snapshot | Live API + versioned with DVC |
| **Verification** | Community volunteers fill gaps | Cross-validation Vote62 vs ECT |

**Winner: Ballot-Location** - Multi-source verification, live API, official DOL boundaries

---

## 2. DATA CLEANING PROCESS

### Election-Station-66 Cleaning:
```
1. Thai numerals → Arabic (๐-๙ → 0-9)
2. Remove keywords: เต็นท์, ปะรำ, บริเวณ
3. Remove bracketed content: (1), (ก)
4. Normalize whitespace/punctuation
5. Extract district from registrar field
6. Join with admin reference data
7. Build formatted Thai address
```

### Ballot-Location Cleaning:
```
1. Async ETL from Vote62 API (province → amphur → tambon → units)
2. ECT PDF extraction (manual + OCR planned)
3. NER (Named Entity Recognition) for location parsing
4. Cross-reference Vote62 vs ECT data
5. Duplicate detection (the_large_dup.xlsx)
6. Spatial validation (point-in-polygon with tambon boundaries)
7. Quality tracking (cannot_find_tambon_polygon.csv)
```

| Aspect | Election-Station-66 | Ballot-Location |
|--------|---------------------|-----------------|
| **Thai Text Cleaning** | Comprehensive (numerals, keywords, brackets) | Less documented |
| **Address Formatting** | Bangkok vs Province differentiation | Similar approach |
| **Data Validation** | Fuzzy matching with difflib | Spatial polygon matching |
| **Quality Tracking** | Success rate logging | Explicit failure files (cannot_find_tambon_polygon.csv) |
| **Deduplication** | Not documented | Explicit tracking (the_large_dup.xlsx) |

**Winner: Mixed**
- Text cleaning: Election-Station-66 (more thorough Thai normalization)
- Validation: Ballot-Location (spatial polygon validation is more rigorous)

---

## 3. GEOCODING APPROACH

| Aspect | Election-Station-66 | Ballot-Location |
|--------|---------------------|-----------------|
| **Primary API** | Google Places + Geocode (2-step) | Google Maps Geocoding API |
| **Fallback** | None | Nominatim (self-hosted Docker) |
| **Caching** | Temp files, batch checkpoints | Joblib disk cache + SQLite |
| **Rate Limiting** | 600 req/min, 0.1-0.2s delay | Semaphore (4 concurrent) |
| **Batch Strategy** | Configurable start/end rows | 3 fixed batches (1K, 10K, rest) |
| **Cost Optimization** | None documented | Joblib memoization |
| **Success Rate** | 91.7% | Not documented in files |

**Winner: Ballot-Location** - Has Nominatim fallback, better caching, cost-aware

---

## 4. TOOLS & INFRASTRUCTURE

| Aspect | Election-Station-66 | Ballot-Location |
|--------|---------------------|-----------------|
| **Version Control** | Git only | Git + DVC (multi-remote: S3, GDrive, SSH) |
| **Data Storage** | Local CSV files | DVC-managed with 3 remotes |
| **Spatial Libraries** | None (just lat/long) | GeoPandas, Shapely, GPKG |
| **Async Processing** | Sequential with delays | httpx AsyncClient |
| **Visualization** | None | Kepler.gl heatmaps |
| **API Integration** | None | VA_Elect_API (production upload) |
| **Automation** | Manual scripts | justfile commands |
| **Secrets Management** | Hardcoded API key placeholder | 1Password integration |

**Winner: Ballot-Location** - Production-grade infrastructure

---

## 5. SUMMARY: WHICH IS BETTER?

### Election-Station-66 Strengths:
1. **Thai text normalization** - More comprehensive cleaning pipeline
2. **Two-step geocoding** - Places Search validates existence before geocoding
3. **Well-documented success rate** - 91.7% clearly measured
4. **Address formatting** - Bangkok vs Province differentiation well-handled
5. **Simple & focused** - Single purpose, easy to understand

### Ballot-Location Strengths:
1. **Multi-source verification** - Vote62 API + ECT official data
2. **Official boundaries** - DOL GPKG files (96MB) vs simple CSV
3. **Spatial validation** - Point-in-polygon checks
4. **Production infrastructure** - DVC, async, API integration, Kepler.gl
5. **Cost optimization** - Nominatim fallback, Joblib caching
6. **Quality tracking** - Explicit failure/duplicate files
7. **Scalable architecture** - Async processing, multiple batches

---

## 6. RECOMMENDATION: Adopt Best of Both

| Take From Election-Station-66 | Keep From Ballot-Location |
|------------------------------|---------------------------|
| Thai numeral conversion (๐-๙) | Multi-source data verification |
| Keyword removal (เต็นท์, ปะรำ) | DVC infrastructure |
| Bracketed content removal | Nominatim fallback |
| Two-step geocoding (Places → Geocode) | Spatial polygon validation |
| Address format differentiation | Joblib caching |
| Success rate measurement | Kepler.gl visualization |

---

## References

- Election-Station-66 repo: https://github.com/thawirasm-j/election-station-66
- Their methodology notes: `notes_election-station-66.md`
- Their pipeline flowchart: `election-station-66-flow.mmd`
