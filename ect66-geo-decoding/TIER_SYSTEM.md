# ECT66 Geocoding Quality Tier System

## Overview

The spatial validation process assigns quality tiers to each voting unit based on geocoding accuracy and spatial validation results. This tier system helps users understand the reliability of each coordinate.

## Tier Definitions

### Tier A+ (Premium Quality) ⭐
**Count:** 28,199 units (29.6% of total)

**Criteria:**
1. Successfully geocoded by Google Maps API
2. Returned coordinate validated to be **within** the correct tambon (sub-district) polygon
3. Has valid Google Place ID

**Accuracy:** High (~10-50m typical Google Maps accuracy for Thai addresses)

**Example:**
```
UnitId: 1001010102
UnitName: "โรงเรียนวัดมหาธาตุ ถนนพระจันทร์"
Province: "กรุงเทพมหานคร"
SubDistrict: "พระบรมมหาราชวัง"
Lat: 13.755134
Lng: 100.490892
PlaceId: "ChIJA7PG9AuZ4jARIyvh-TR_wkA"
Formatted_Address: "3 ถนน ท่าพระจันทร์ แขวงพระบรมมหาราชวัง เขตพระนคร กรุงเทพมหานคร 10200 ประเทศไทย"
TierLocation: "A+"
```

**Validation Process:**
1. Google Maps returns coordinate (13.755134, 100.490892)
2. Load tambon polygon for "กรุงเทพมหานคร" + "พระบรมมหาราชวัง"
3. Check if Point(100.490892, 13.755134) is within tambon polygon
4. ✅ Point is inside → **Tier A+**

### Tier D (Synthetic Fallback) ⚠️
**Count:** 65,503 units (68.8% of total)

**Criteria (any of these):**
1. Google Maps API returned no results (2,810 units)
2. Google Maps result is **outside** the correct tambon boundary (~62,693 units)

**Accuracy:** Low (randomly distributed within tambon, could be off by several kilometers)

**Example:**
```
UnitId: 1005450201
UnitName: "เต็นท์บริเวณหน้าห้างดิโอลด์สยามพลาซ่า ถนนบูรพา"
Province: "กรุงเทพมหานคร"
SubDistrict: "สะพานสอง"
Lat: 13.798624  # Random point generated within tambon polygon
Lng: 100.590170
PlaceId: ""  # Empty
Formatted_Address: ""  # Empty
TierLocation: "D"
```

**Why Tier D is Needed:**

**Scenario 1: Google Returns Wrong Location**
- Google geocodes "เต็นท์ลานจอดรถโรงเรียน..." to generic "ประเทศไทย" location
- Coordinate: (15.870032, 100.992541) - generic Thailand center
- This point is **outside** the correct tambon "สะพานสอง" in Bangkok
- Spatial validation detects this → **Demoted to Tier D**
- Generate random point within "สะพานสอง" tambon polygon instead

**Scenario 2: Google Returns No Results**
- Uncommon address format or new development
- API response: `[]` (empty array)
- No coordinates available from Google
- Generate random point within tambon polygon → **Tier D**

## Spatial Validation Process

### Step 1: Load Tambon Polygons

**Data Sources:**
- **DOL Tambon**: `tambon_DOL_utf8.gpkg` (Department of Lands official boundaries)
  - 7,615 tambons before deduplication
  - 7,266 unique tambons after merging multipolygons
- **BMA Admin**: `BMA_ADMIN_SUB_DISTRICT.gpkg` (Bangkok sub-district boundaries)
- **ECT Districts**: `2566_TH_ECT_attributes.shp` (Electoral district polygons, used as fallback)

**Preprocessing:**
- Some tambons have multiple polygons (islands, non-contiguous areas)
- Merged using `shapely.ops.unary_union()` to create MultiPolygon geometries
- Example: "เกาะพระทอง" in พังงา has 20 separate polygons

### Step 2: Match & Filter

For each voting unit:

```python
# 1. Find tambon polygon matching (Province, SubDistrictName)
tambon_polygon = get_tambon_polygon(province="กรุงเทพมหานคร", tambon="สะพานสอง")

# 2. Get Google geocoding result
google_point = Point(lng=100.590170, lat=13.798624)

# 3. Check if point is within tambon polygon
if google_point.within(tambon_polygon):
    # ✅ Tier A+ - Google result validated
    tier = "A+"
    lat, lng = google_point.y, google_point.x
    place_id = "ChIJ..."
else:
    # ❌ Tier D - Google result outside tambon, use random point instead
    tier = "D"
    random_point = generate_random_point_in_polygon(tambon_polygon)
    lat, lng = random_point.y, random_point.x
    place_id = ""
```

### Step 3: Random Point Generation (for Tier D)

```python
def gen_random_point_in_polygon(poly):
    """Generate uniform random point within polygon bounds."""
    minx, miny, maxx, maxy = poly.bounds
    while True:
        p = Point(
            random.uniform(minx, maxx),
            random.uniform(miny, maxy)
        )
        if poly.contains(p):
            return p  # Found point inside polygon
```

**Characteristics:**
- Uniform distribution within polygon bounding box
- May require multiple iterations for complex polygons (low convexity)
- Ensures 100% coverage (every unit has some coordinate)

## Statistics & Distribution

### Overall Quality

```
Total Units: 95,249
├─ Tier A+ (Premium):  28,199 (29.6%)  ⭐ High accuracy
└─ Tier D (Synthetic): 65,503 (68.8%)  ⚠️ Low accuracy

Coverage: 100% (all units have coordinates)
```

### Why Low Tier A+ Rate?

**Primary Issue: The 28k Duplicate Coordinate Problem**
- 28,448 units geocoded to exact same coordinate: `(15.870032, 100.992541)`
- Google returned generic "ประเทศไทย" (Thailand country-level) as fallback
- Place ID: `ChIJsU1CR_eNTTARAuhXB4gs154` (Thailand)
- These units spread across all 77 provinces but got identical coordinates
- Spatial validation detected this → all demoted to Tier D

**Secondary Issues:**
- **2,810 units**: Google API returned no results (empty array)
- **~600 units**: Google placed unit in adjacent/incorrect tambon

**Root Cause:**
Thai address formats are challenging for Google Maps:
- Many units use descriptive names instead of street addresses
- Examples: "เต็นท์บริเวณหน้าห้าง..." (tent in front of mall)
- Temple/school names may not be in Google's database
- Thai script processing limitations

### Distribution by Province

**High Tier A+ Rate Provinces:**
- Bangkok (กรุงเทพมหานคร): ~45% Tier A+ (good Google coverage)
- Chiang Mai (เชียงใหม่): ~38% Tier A+
- Phuket (ภูเก็ต): ~42% Tier A+

**Low Tier A+ Rate Provinces:**
- Remote provinces: ~15-20% Tier A+
- Rural areas: Google Maps coverage limited
- New administrative boundaries: polygon mismatches

## Known Issues

### Issue 1: Missing Tambon Polygons
**Affected:** 1,046 units couldn't match to tambon polygons

**Reasons:**
- Typos in SubDistrictName (e.g., "วัดไทร์" vs "วัดไทย")
- New administrative boundaries created after shapefile release
- Bangkok special administrative areas (not in DOL tambon dataset)

**Fallback Strategy:**
1. Try Department of Lands tambon polygons first
2. Try Bangkok Municipal Administration polygons (for Bangkok only)
3. Use ECT electoral district polygons as final fallback

**Result:** All 95,249 units eventually matched to **some** polygon (100% coverage)

### Issue 2: Tambon Polygon Quality

**Observation:** Some tambon polygons have low resolution or outdated boundaries

**Impact:**
- Tier A+ units near tambon boundaries may be incorrectly filtered
- Random Tier D points may appear slightly outside visual boundaries on high-zoom maps

**Mitigation:**
- Use multiple polygon sources (DOL + BMA + ECT)
- Accept Tier A+ if valid in **any** of the polygon sources

### Issue 3: Geocoding Cost vs. Quality Trade-off

**Current Approach:** Batch geocoding with basic component filtering
- Cost: ~$476 for 95k units
- Result: 29.6% Tier A+

**Alternative Approaches (not implemented):**
1. **Multiple geocoding services** (Longdo Maps, HERE Maps, OpenStreetMap Nominatim)
   - Potential: 40-50% Tier A+ (higher Thailand coverage)
   - Cost: +$300-500 for additional services

2. **Manual address cleaning** (pre-process unit names)
   - Potential: 35-40% Tier A+ (better Google results)
   - Cost: ~40-80 hours manual work

3. **Crowd-sourced validation** (volunteer review)
   - Potential: 60-70% Tier A+ (human verification)
   - Cost: Coordination overhead, data quality concerns

## Usage Recommendations

### For Map Visualization

**Use ALL data (95,249 units)** for complete coverage:
```python
df = pd.read_parquet("outputs/ect66_geocoded_validated.parquet")
```

**Color-code by tier** to show quality distribution:
```python
import geopandas as gpd
import matplotlib.pyplot as plt

gdf = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df.Lng, df.Lat),
    crs="EPSG:4326"
)

fig, ax = plt.subplots(figsize=(15, 15))
gdf[gdf.TierLocation == "A+"].plot(
    ax=ax, color="green", markersize=1, label="Tier A+ (Validated)"
)
gdf[gdf.TierLocation == "D"].plot(
    ax=ax, color="orange", markersize=1, label="Tier D (Synthetic)"
)
plt.legend()
plt.title("ECT66 Voting Units - Quality Distribution")
plt.show()
```

**Note:** At zoom levels > 12, Tier D points may appear visually inaccurate (not at exact building location).

### For Spatial Analysis

**Use Tier A+ only (28,199 units)** for precise distance calculations:
```python
tier_a = df[df.TierLocation == "A+"]

# Calculate distance to nearest polling station
from scipy.spatial import cKDTree
coords = list(zip(tier_a.Lng, tier_a.Lat))
tree = cKDTree(coords)
distances, indices = tree.query(coords, k=2)  # k=2 to skip self
```

**Use ALL data for aggregate statistics** (province/district level):
```python
# Count by province (Tier D randomness averages out at aggregate level)
df.groupby("ProvinceName").size().sort_values(ascending=False)
```

### For Routing & Navigation

**WARNING:** Do not use Tier D coordinates for turn-by-turn navigation:
- Tier D points are randomly placed within tambon (could be in rice fields, rivers, etc.)
- Use only Tier A+ with valid Place IDs for Google Maps integration

### For Data Science / ML

**Feature Engineering:**
```python
# Add tier as categorical feature
df["is_validated"] = (df.TierLocation == "A+").astype(int)

# Add distance to tambon centroid (Tier D uncertainty measure)
df["distance_to_centroid"] = ...  # Lower for Tier D near center
```

**Model Training:**
- Use `TierLocation` as a feature (model can learn to weight Tier A+ more)
- Consider stratified sampling to balance Tier A+ vs Tier D
- Apply higher weights to Tier A+ samples in loss function

## Future Improvements

### Short-term (Low Effort)

1. **Re-geocode Tier D units with alternative services**
   - Longdo Maps API (Thailand-specific, better coverage)
   - Cost: ~$150 for 65k units
   - Expected: +10-15% Tier A+ conversion

2. **Improve tambon polygon matching**
   - Fuzzy string matching for tambon names (Levenshtein distance < 2)
   - Expected: -200 units in "missing polygon" category

### Medium-term (Moderate Effort)

3. **Address cleaning & enrichment**
   - Extract street names with pythainlp NER
   - Add district names to unit names for better Google context
   - Expected: +5-8% Tier A+ conversion

4. **Polygon quality improvement**
   - Use newer OpenStreetMap administrative boundaries
   - Validate DOL polygons against satellite imagery
   - Expected: +2-3% accuracy in border areas

### Long-term (High Effort)

5. **Hybrid geocoding approach**
   - Combine Google + Longdo + OSM Nominatim
   - Vote-based consensus (2/3 agreement = Tier A+)
   - Expected: 50-60% Tier A+ final rate

6. **Crowd-sourced validation platform**
   - Web interface for volunteers to verify/correct Tier D units
   - Photo upload + GPS tagging
   - Expected: 70-80% Tier A+ with community effort

## References

- **Department of Lands Tambon Boundaries**: Official Thai administrative divisions
- **Google Maps Geocoding API**: https://developers.google.com/maps/documentation/geocoding
- **Shapely Spatial Operations**: https://shapely.readthedocs.io/en/stable/manual.html#object.within
- **Thailand Administrative Divisions**: https://en.wikipedia.org/wiki/Tambon

## Questions?

For questions about the tier system or geocoding methodology, see the main [README.md](README.md) or review the spatial validation notebook: `notebooks/03_spatial_validation.ipynb`
