# Kepler.gl Data Format Conventions

Documentation for preparing data files for Kepler.gl visualization.

## Supported File Formats

According to [Kepler.gl documentation](https://docs.kepler.gl/docs/user-guides/b-kepler-gl-workflow/a-add-data-to-the-map#supported-file-formats):

- **CSV** - with header rows and multiple columns
- **GeoJSON** - Feature or FeatureCollection objects
- **GeoArrow** - Binary data format for visualization
- **Kepler.gl JSON** - Maps exported from Kepler.gl

**Note:** Parquet is not officially documented, but works in practice when loaded via pandas/geopandas.

## Coordinate System Requirements

**CRITICAL:** Kepler.gl only supports **WGS84 (EPSG:4326)** coordinate reference system.

- Use geographic coordinate reference system with WGS84 datum
- Longitude and latitude units must be decimal degrees
- Latitude range: -90 to 90
- Longitude range: -180 to 180

**Do NOT use Web Mercator (EPSG:3857)** - despite documentation mentioning it, the data must be in WGS84.

## Parquet File Format for Point Data

### Required Columns

For automatic point layer detection, use these column names:

```python
'latitude'   # float64, decimal degrees
'longitude'  # float64, decimal degrees
```

### Recommended Schema

```python
import pyarrow as pa

schema = pa.schema([
    ('id', pa.int32()),              # Unique identifier
    ('name', pa.string()),           # Display name
    ('latitude', pa.float64()),      # Y coordinate (decimal degrees)
    ('longitude', pa.float64()),     # X coordinate (decimal degrees)
    ('category', pa.string()),       # Categorical data
    ('value', pa.int32()),           # Numeric data
    ('timestamp', pa.timestamp('ms')) # Time data (optional)
])
```

### Data Types

Kepler.gl auto-detects these data types:

- `boolean` - for binary flags
- `date` / `timestamp` - for temporal data
- `geojson` - for embedded geometries
- `integer` - for counts, IDs
- `real` (float) - for measurements
- `string` - for labels, categories

### Example: Creating Parquet File

```python
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Sample data
data = {
    'ballot_id': [1, 2, 3],
    'name': ['Location A', 'Location B', 'Location C'],
    'province': ['Province 1', 'Province 2', 'Province 3'],
    'latitude': [13.7563, 13.7465, 13.7367],
    'longitude': [100.5018, 100.5342, 100.5226],
    'status': ['OPERATIONAL', 'OPERATIONAL', 'CLOSED'],
    'capacity': [500, 450, 600]
}

df = pd.DataFrame(data)

# Define schema
schema = pa.schema([
    ('ballot_id', pa.int32()),
    ('name', pa.string()),
    ('province', pa.string()),
    ('latitude', pa.float64()),
    ('longitude', pa.float64()),
    ('status', pa.string()),
    ('capacity', pa.int32())
])

# Write to Parquet
table = pa.Table.from_pandas(df, schema=schema)
pq.write_table(
    table,
    'output.parquet',
    compression='snappy',
    write_statistics=True
)
```

## Loading Parquet into Kepler.gl

### Option 1: Direct pandas DataFrame

```python
import pandas as pd
from keplergl import KeplerGl

df = pd.read_parquet('data.parquet')
map1 = KeplerGl(height=600)
map1.add_data(data=df, name='My Data')
map1
```

### Option 2: GeoDataFrame with Geometry

```python
import pandas as pd
import geopandas as gpd
from keplergl import KeplerGl

df = pd.read_parquet('data.parquet')
gdf = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df.longitude, df.latitude),
    crs='EPSG:4326'
)
map2 = KeplerGl(height=600)
map2.add_data(data=gdf, name='My Data')
map2
```

## CSV Format Conventions

For CSV files, Kepler.gl supports column naming patterns:

- `<name>_latitude` and `<name>_longitude` - for point layers
- Automatically detects data types from content
- First row must contain headers

## Polygon Data (GeoJSON/Shapefile)

For polygon/multipolygon data (like electoral districts):

```python
import geopandas as gpd
from keplergl import KeplerGl

regions = gpd.read_file('regions.shp')
# Ensure CRS is WGS84
regions = regions.to_crs('EPSG:4326')

map3 = KeplerGl(height=600)
map3.add_data(data=regions, name='Regions')
map3
```

## Best Practices

1. **Always use WGS84 (EPSG:4326)** for coordinates
2. **Use float64** for latitude/longitude precision
3. **Name columns** `latitude` and `longitude` for auto-detection
4. **Include meaningful attributes** for filtering/coloring
5. **Add temporal data** (timestamp) for time-series visualization
6. **Keep file sizes reasonable** - Kepler.gl is client-side, large files may be slow
7. **Use compression** (snappy/gzip) for Parquet files

## Troubleshooting

### Points not appearing
- Verify coordinates are in decimal degrees, not radians
- Check latitude is Y (-90 to 90) and longitude is X (-180 to 180)
- Ensure CRS is EPSG:4326, not EPSG:3857

### Data not loading
- Check column names match expected patterns
- Verify data types are supported
- Ensure no NaN/null values in coordinate columns

### Performance issues
- Reduce number of rows (< 100k recommended)
- Simplify polygon geometries
- Use Parquet instead of CSV for large datasets

## References

- [Kepler.gl Data Format Documentation](https://docs.kepler.gl/docs/user-guides/b-kepler-gl-workflow/a-add-data-to-the-map#supported-file-formats)
- [Kepler.gl Jupyter Documentation](https://docs.kepler.gl/docs/keplergl-jupyter)
- Project test files: `test_ballot_kepler.parquet`, `test_kepler_data.py`
