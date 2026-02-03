# Interactive Map Tool Spec

## Purpose

A general-purpose interactive map that an AI agent can use as a tool via the Anthropic Agent SDK. The agent can add/remove layers, request text descriptions of the map state, and capture screenshots when visual reasoning is needed. The human watches the same map live.

## Two-Tier Feedback

| Mode | Cost | Good for | Bad for |
|------|------|----------|---------|
| `map.describe()` | cheap, text only | distances, containment checks, nearby names, fast iteration | road layout, building shape, entrance side |
| `map.screenshot()` | expensive, image tokens | road junctions, building footprints, spatial layout, visual confirmation | everything `describe` already handles |

The agent uses `describe()` as its primary feedback loop -- add a layer, describe, adjust, describe again. It calls `screenshot()` only when it needs to reason about physical geometry that text can't capture (which road does the entrance face? is this a T-junction or a roundabout?).

## H3 Spatial Indexing

All positions are described using [H3](https://h3geo.org/) hexagonal indices instead of raw lat/lng. This gives the agent a discrete, hierarchical spatial vocabulary.

| H3 Resolution | Hex Edge | Use |
|---------------|----------|-----|
| 9 | ~174m | neighborhood level |
| 10 | ~66m | block level |
| 11 | ~25m | parcel level |
| 12 | ~9m | building level |
| 13 | ~3.4m | entrance level |

The `describe()` output uses resolution auto-derived from the current zoom level (see table below). The agent can think in terms of "same hex", "adjacent hex", "3 hexes apart" rather than raw meter distances.

**Zoom → H3 resolution mapping:**

| Zoom Level | H3 Resolution | Rationale |
|------------|---------------|-----------|
| ≤ 14 | 9 (~174m) | neighborhood overview |
| 15 | 9 (~174m) | still coarse navigation |
| 16 | 10 (~66m) | block-level work |
| 17 | 11 (~25m) | parcel-level work |
| 18 | 12 (~9m) | building-level (default zoom) |
| 19 | 12 (~9m) | same as 18 |
| ≥ 20 | 13 (~3.4m) | entrance-level precision |

The resolution is auto-derived; the agent does not need to specify it. An optional `h3_resolution` override is available for edge cases where the agent wants a different resolution than the zoom default.

## Architecture

```
┌──────────────────────────────────────┐
│  Anthropic Agent SDK                  │
│                                       │
│  tools:                               │
│    - map.add_layer(geojson)           │
│    - map.remove_layer(id)             │
│    - map.set_style(id, style)         │
│    - map.set_view(h3, zoom)           │
│    - map.fit_bounds(layer_ids?)       │
│    - map.describe()                   │
│    - map.screenshot(basemap)          │
│    - map.search(query/lat/lng)        │
│    - map.get_features(layer, area)    │
│    - map.measure(op, a, b)            │
└──────────┬────────────────────────────┘
           │ WebSocket (synchronous req/res)
┌──────────▼────────────────────────────┐
│  FastAPI Server (localhost:3000)       │
│  Python WebSocket bridge              │
│                                       │
│  ┌─────────────────────────────────┐  │
│  │  Playwright (headless Chromium) │  │
│  │  ┌───────────────────────────┐  │  │
│  │  │  MapLibre GL JS           │  │  │
│  │  │  - Vector/raster layers   │  │  │
│  │  │  - turf.js (spatial ops)  │  │  │
│  │  └───────────────────────────┘  │  │
│  └─────────────────────────────────┘  │
│                                       │
│  Also serves browser UI for human     │
│  at same localhost:3000               │
└───────────────────────────────────────┘
```

**Tech stack:**
- **MapLibre GL JS**: open-source map renderer, runs in browser
- **Playwright**: headless browser for screenshot capture
- **FastAPI**: Python WebSocket server bridging Agent SDK ↔ browser

**Tile sources:**
- Satellite: ESRI World Imagery (free) or Google (via API key if available)
- Street: OpenStreetMap via MapLibre default style

**WebSocket protocol:**
- All tool calls are synchronous: agent sends request, blocks until response
- `screenshot()` internally waits for all map tiles to finish loading before capture
- `tile_timeout` (default 5s) -- if tiles don't load in time, capture anyway with whatever is rendered
- No explicit `map.ready()` tool needed -- render-wait is built into screenshot

## Layer IDs

Every layer gets a server-assigned **3-character nano ID** (e.g. `"a1b"`, `"x7q"`, `"m3p"`). This is the stable identifier used in all tool calls (`remove_layer`, `toggle_layer`, `get_features`, etc.). The human-readable `name` is separate -- it's the label shown in the layer panel and used in `describe()` output.

Layer names are the canonical identifier for human-readable references (in `describe()` output, `focus` parameter, `feature()` helper). Nano IDs are used only in tool parameters that require `layer_id`.

## Tools

### `map.add_layer`

Add any GeoJSON to the map. Returns a summary object with the assigned ID and layer metadata.

```python
def add_layer(
    geojson: dict,            # any valid GeoJSON (Point, Polygon, FeatureCollection, etc.)
    name: str,                # human-readable label shown in layer panel
    style: dict | None = None # optional style (see Style Schema below)
) -> dict
```

**Return value:**

```json
{
  "id": "a1b",
  "name": "candidate",
  "type": "Point",
  "features": 1,
  "h3": "8c2a100d2929dff",
  "bbox": [100.49, 13.75, 100.49, 13.75]
}
```

For FeatureCollections, `h3` is the centroid of the bounding box, and `features` is the count. This saves the agent a `describe()` call after every add.

**Examples:**

```python
# drop a pin
add_layer(
    geojson={"type": "Point", "coordinates": [100.49, 13.75]},
    name="candidate",
    style={"color": "red", "icon": "pin"}
)
# → {"id": "a1b", "name": "candidate", "type": "Point", "features": 1, "h3": "8c2a100d2929dff", "bbox": [100.49, 13.75, 100.49, 13.75]}

# show a boundary polygon
add_layer(
    geojson=tambon_polygon_geojson,
    name="tambon boundary",
    style={"color": "blue", "fill_opacity": 0.1}
)
# → {"id": "x7q", "name": "tambon boundary", "type": "Polygon", "features": 1, "h3": "892a100d293ffff", "bbox": [100.48, 13.74, 100.50, 13.76]}

# show multiple points at once
add_layer(
    geojson={"type": "FeatureCollection", "features": [...]},
    name="geocode results",
    style={"color": "orange", "radius": 6}
)
# → {"id": "m3p", "name": "geocode results", "type": "FeatureCollection", "features": 5, "h3": "892a100d293ffff", "bbox": [100.48, 13.74, 100.51, 13.77]}
```

### `map.remove_layer`

```python
def remove_layer(layer_id: str) -> None
```

### `map.set_style`

Update the style of an existing layer without re-uploading GeoJSON. Useful for changing marker color, opacity, etc. on large FeatureCollections.

```python
def set_style(
    layer_id: str,            # 3-char nano ID
    style: dict               # style properties to merge (see Style Schema)
) -> None
```

**Example:**
```python
set_style("a1b", {"color": "green", "radius": 8})
```

Only the specified style keys are updated; unspecified keys retain their current values.

### `map.clear_layers`

Remove all user-added layers. Base maps unaffected.

```python
def clear_layers() -> None
```

### `map.set_view`

Pan and zoom the map. Accepts H3 index or lat/lng.

```python
def set_view(
    h3: str | None = None,    # H3 index to center on (any resolution)
    lat: float | None = None,  # alternative: raw lat/lng
    lng: float | None = None,
    zoom: int = 17             # 1 = world, 18 = building level
) -> None
```

### `map.fit_bounds`

Auto-zoom the map to show all specified layers (or all layers if none specified). Saves the agent from manually computing bounding boxes.

```python
def fit_bounds(
    layer_ids: list[str] | None = None,  # layers to fit; None = all layers
    padding: int = 50                     # pixels of padding around bounds
) -> None
```

**Example:**
```python
fit_bounds()                          # zoom to show everything
fit_bounds(layer_ids=["a1b", "x7q"])  # zoom to show just these two layers
```

### `map.describe`

Return a text description of the current map state. Cheap, no rendering needed. This is the agent's primary feedback tool.

```python
def describe(
    viewport_only: bool = True,       # only layers/features intersecting current view bounds
    focus: str | None = None,         # layer name to center relations around
    relations_to: list[str] | None = None,  # only compute relations with these layers
    h3_resolution: int | None = None  # override auto-derived resolution (default: from zoom)
) -> str
```

**Filtering to avoid combinatorial explosion:**
- `viewport_only=True` (default): only describe layers/features intersecting the current view bounds. Set to `False` to get everything.
- `focus`: when set, pairwise relations are computed only between this layer and all others (not all-pairs). E.g. `focus="candidate"` shows candidate↔tambon, candidate↔ect66, but not tambon↔ect66.
- `relations_to`: further restrict which layers appear in pairwise relations. E.g. `focus="candidate", relations_to=["tambon boundary", "ect66 ref"]`.
- When neither `focus` nor `relations_to` is set, pairwise relations are capped to layers within the visible viewport.

**Example output:**

```markdown
## Map State
- **center**: 8c2a100d2929dff (res 12, ~9m hexes)
- **zoom**: 18

## Layers (3 active)

### [a1b] candidate (Point) 🔴
- h3: 8c2a100d2929dff

### [x7q] ect66 ref (Point) 🔵
- h3: 8c2a100d2929dff
- same hex as candidate (< 9m apart)

### [m3p] geocode results (FeatureCollection, 50 features) 🟠
- 50 Point features
- **sample** (first 5):
  - [0] "Lumphini Park" — h3: 8c2a100d2929dff
  - [1] "Wat Pho" — h3: 8c2a100d2801dff
  - [2] "สถานีรถไฟหัวลำโพง" — h3: 8c2a100d28a3dff
  - [3] "Central World" — h3: 8c2a100c5b29dff
  - [4] "Chatuchak Park" — h3: 8c2a10025929dff
- **properties**: name (50 unique), type (school: 23, temple: 15, park: 12)

### [r2d] tambon boundary (Polygon)
- 12 vertices, area ~0.8 km²
- candidate → inside, 342m from nearest edge
- ect66 ref → inside, 340m from nearest edge

## Pairwise Relations
- candidate ↔ ect66 ref: same h3 (res 12), ~3m
- candidate → inside tambon boundary, 342m from edge
```

The describe output is structured so the agent can quickly scan spatial relationships without visual rendering. Key properties:

- **Containment**: which points are inside which polygons
- **Proximity**: H3 distance between point layers (same hex, adjacent, N hexes apart)
- **Edge distance**: how far points are from polygon boundaries
- **Layer summary**: type, vertex count, area for polygons
- **Feature summary** (FeatureCollections): first 5 features with name + H3 position, plus property value distribution for the most common properties

### `map.screenshot`

Capture the current map view as a PNG image. The agent receives this as visual input. Use when text description is not enough -- road layout, building footprints, junction geometry.

```python
def screenshot(
    basemap: str = "satellite",  # "satellite" | "street"
    detail: str = "low"          # "low" (640x480) | "high" (1280x960)
) -> Image
```

Returns a screenshot of the **same viewport** but with the requested base map. The agent can call it twice to get both satellite and street views without moving.

**Detail levels:**
- `"low"` (640x480, default): cheaper image tokens, sufficient for road junctions and general layout
- `"high"` (1280x960): for fine detail like building entrances, sign text, narrow alleys

The agent requests `"high"` only when it needs fine-grained visual detail. Default to `"low"` for cost efficiency.

All user-added layers (markers, polygons) are rendered on top of the base map in the screenshot. The screenshot waits for tiles to load (up to `tile_timeout` of 5s) before capture.

### `map.search`

Lightweight forward/reverse geocode on the map. Backed by self-hosted Nominatim (same instance as the geocoding pipeline).

```python
def search(
    query: str | None = None,     # forward geocode: place name or address
    lat: float | None = None,     # reverse geocode: latitude
    lng: float | None = None,     # reverse geocode: longitude
    bbox: list[float] | None = None  # optional bounding box [west, south, east, north]
) -> dict                         # GeoJSON FeatureCollection of results
```

**Forward geocode:**
```python
search(query="โรงเรียนวัดมหาธาตุ")
# → GeoJSON FeatureCollection with matching results (name, coordinates, type)
```

**Reverse geocode:**
```python
search(lat=13.75, lng=100.49)
# → GeoJSON FeatureCollection of nearby POIs
```

**With bounding box:**
```python
search(query="วัด", bbox=[100.48, 13.74, 100.50, 13.76])
# → results within the specified bounds
```

### `map.get_features`

Query features from a specific layer near a location. Lets the agent inspect individual features without parsing full `describe()` output.

```python
def get_features(
    layer_id: str,                    # which layer to query
    h3: str | None = None,           # H3 index to search near
    bbox: list[float] | None = None, # bounding box [west, south, east, north]
    limit: int = 10                  # max features to return
) -> list[dict]                      # list of GeoJSON features with properties
```

**Example:**
```python
get_features(layer_id="m3p", h3="8c2a100d2929dff", limit=5)
# → [{"type": "Feature", "geometry": {...}, "properties": {"name": "...", ...}}, ...]
```

### `map.measure`

Named spatial measurement tools backed by turf.js. Replaces the previous `map.exec` approach — named operations eliminate hallucination risk on function signatures and prevent arbitrary JS execution in the browser context.

All operations reference features by **layer name** (the `name` passed to `add_layer`). For FeatureCollections, append `[index]` to reference a specific feature (e.g. `"geocode results[3]"`). Without an index, the first feature is used.

```python
def measure(
    op: str,                    # operation name (see table below)
    a: str,                     # first feature reference (layer name or "name[index]")
    b: str | None = None,       # second feature reference (for binary ops)
    params: dict | None = None  # operation-specific parameters
) -> dict
```

**Supported operations:**

| `op` | Description | `a` | `b` | `params` | Returns |
|------|-------------|-----|-----|----------|---------|
| `distance` | Distance between two features | point/geometry | point/geometry | `units` (default `"meters"`) | `{"result": 3.2, "units": "meters"}` |
| `area` | Area of a polygon | polygon | — | — | `{"result": 823400.5, "units": "m²"}` |
| `bearing` | Compass bearing from a to b | point | point | — | `{"result": 45.3, "units": "degrees"}` |
| `buffer` | Buffer around a feature | any geometry | — | `radius`, `units` (default `100`, `"meters"`) | `{"result": <GeoJSON Polygon>}` |
| `centroid` | Centroid of a feature | any geometry | — | — | `{"result": <GeoJSON Point>}` |
| `contains` | Does a contain b? | polygon | point/geometry | — | `{"result": true}` |
| `intersects` | Do a and b intersect? | any geometry | any geometry | — | `{"result": false}` |
| `nearest` | Nearest feature in a FeatureCollection to b | FeatureCollection | point | — | `{"result": <GeoJSON Feature>, "index": 3, "distance_m": 42.1}` |

**Examples:**
```python
# Distance between two features
measure(op="distance", a="candidate", b="ect66 ref")
# → {"result": 3.2, "units": "meters"}

# Area of a polygon feature
measure(op="area", a="tambon boundary")
# → {"result": 823400.5, "units": "m²"}

# Bearing from one point to another
measure(op="bearing", a="candidate", b="ect66 ref")
# → {"result": 45.3, "units": "degrees"}

# Buffer around a point (returns GeoJSON)
measure(op="buffer", a="candidate", params={"radius": 100, "units": "meters"})
# → {"result": {"type": "Polygon", "coordinates": [...]}}

# Check containment
measure(op="contains", a="tambon boundary", b="candidate")
# → {"result": true}

# Find nearest point in a collection
measure(op="nearest", a="geocode results", b="candidate")
# → {"result": {"type": "Feature", ...}, "index": 3, "distance_m": 42.1}

# Access specific feature in a FeatureCollection
measure(op="distance", a="geocode results[3]", b="candidate")
# → {"result": 15.7, "units": "meters"}
```

### `map.add_raster_layer`

Add a raster tile layer (WMS, TMS, XYZ tiles).

```python
def add_raster_layer(
    url: str,                 # tile URL template e.g. "https://.../{z}/{x}/{y}.png"
    name: str,
    type: str = "xyz",        # "xyz" | "wms" | "tms"
    opacity: float = 0.7
) -> str:                     # returns 3-char nano ID
```

### `map.list_layers`

See what's currently on the map.

```python
def list_layers() -> list[dict]
# returns [{"id": "a1b", "name": "candidate", "type": "vector", "visible": true}, ...]
```

### `map.toggle_layer`

Show/hide a layer without removing it.

```python
def toggle_layer(layer_id: str, visible: bool) -> None
```

## Style Schema

Strict enum of allowed style properties. Anything not listed is silently ignored (no error, just not applied).

| Property | Type | Values | Description |
|----------|------|--------|-------------|
| `color` | string | hex (`"#ff0000"`) or named: `red`, `blue`, `green`, `orange`, `gray` | Stroke/marker color |
| `fill_color` | string | same as `color` | Fill color for polygons |
| `fill_opacity` | float | 0.0 - 1.0 | Polygon fill opacity |
| `opacity` | float | 0.0 - 1.0 | Overall layer opacity |
| `radius` | int | 1 - 50 | Circle marker radius in pixels |
| `icon` | string | `pin`, `circle`, `square`, `diamond` | Marker icon shape |
| `weight` | int | 1 - 10 | Line width in pixels |

## Error Contract

All tools return a consistent error shape when an operation fails. The agent can pattern-match on the `"error"` key to detect failures.

```json
{"error": "<category>: <detail>"}
```

**Error categories:**

| Category | Example | When |
|----------|---------|------|
| `layer_not_found` | `{"error": "layer_not_found: zzz"}` | `remove_layer`, `set_style`, `get_features`, `measure` with invalid layer ID |
| `feature_not_found` | `{"error": "feature_not_found: geocode results[99]"}` | `measure` with out-of-range index |
| `invalid_op` | `{"error": "invalid_op: intersect (did you mean: intersects)"}` | `measure` with unknown operation name |
| `invalid_geojson` | `{"error": "invalid_geojson: missing 'type' field"}` | `add_layer` with malformed GeoJSON |
| `search_empty` | `{"error": "search_empty: no results for 'asdfxyz'"}` | `search` with no matches |
| `type_mismatch` | `{"error": "type_mismatch: area requires Polygon, got Point"}` | `measure` with wrong geometry type |

Successful operations that return `None` (like `set_view`, `set_style`, `fit_bounds`) return `{"ok": true}`.

The `"did you mean"` hint in `invalid_op` is generated by fuzzy-matching against the supported operation list, helping the agent self-correct.

## Base Maps

Two built-in base maps, always available, toggled via `screenshot(basemap=...)`:

| Name | Source | Notes |
|------|--------|-------|
| `satellite` | ESRI World Imagery (free) / Google (via API key) | Aerial imagery |
| `street` | OpenStreetMap via MapLibre default style | Road labels, building outlines |

The agent typically uses `describe()` for fast iteration, then `screenshot("satellite")` and `screenshot("street")` when it needs to visually confirm layout.

## Typical Agent Interaction

```
Agent: map.set_view(h3="8c2a100d2929dff", zoom=17)
Agent: map.add_layer(point, "candidate", red)
  → {"id": "a1b", "type": "Point", "features": 1, "h3": "8c2a100d2929dff", ...}
Agent: map.add_layer(polygon, "tambon boundary", blue)
  → {"id": "x7q", "type": "Polygon", "features": 1, ...}
Agent: map.describe()
  → "[a1b] candidate at 8c2a100d2929dff, inside tambon boundary, 342m from edge"
Agent: [adjusts pin based on text feedback]
Agent: map.set_style("a1b", {"color": "green"})       ← style change without re-upload
Agent: map.remove_layer("a1b")
Agent: map.add_layer(new_point, "candidate v2", red)
  → {"id": "k9z", "type": "Point", "features": 1, "h3": "8c2a100d292b1ff", ...}
Agent: map.describe(focus="candidate v2")
  → "[k9z] candidate v2 at 8c2a100d292b1ff, inside tambon boundary, 280m from edge"
Agent: [looks good spatially, now needs visual confirmation]
Agent: map.screenshot("satellite")
  → [sees building footprint, entrance on south side -- low res sufficient]
Agent: map.screenshot("street", detail="high")
  → [sees road name ถนนมหาราช at high res, confirms location]
Agent: map.measure(op="distance", a="candidate v2", b="ect66 ref")
  → {"result": 3.2, "units": "meters"}
Agent: map.fit_bounds()                                ← zoom to show all layers
Agent: [accepts result]
```

## Agent SDK Integration

The map tools are registered as Anthropic Agent SDK tools. The agent calls them like any other tool and receives results in the conversation.

```python
import anthropic

tools = [
    {
        "name": "map.add_layer",
        "description": "Add a GeoJSON layer to the map. Returns {id, name, type, features, h3, bbox}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "geojson": {"type": "object", "description": "Valid GeoJSON geometry or FeatureCollection"},
                "name": {"type": "string", "description": "Label for the layer"},
                "style": {
                    "type": "object",
                    "description": "Optional style. Allowed keys: color, fill_color, fill_opacity, opacity, radius, icon (pin|circle|square|diamond), weight"
                }
            },
            "required": ["geojson", "name"]
        }
    },
    {
        "name": "map.describe",
        "description": "Get a text description of the current map state: layer positions (H3), containment, proximity, edge distances. Cheap alternative to screenshot. Viewport-scoped by default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "viewport_only": {"type": "boolean", "default": True, "description": "Only describe layers/features in current view bounds"},
                "focus": {"type": "string", "description": "Layer name to center pairwise relations around (avoids all-pairs explosion)"},
                "relations_to": {"type": "array", "items": {"type": "string"}, "description": "Only compute relations with these layers"},
                "h3_resolution": {"type": "integer", "description": "Override auto-derived H3 resolution (default: from zoom level)"}
            }
        }
    },
    {
        "name": "map.screenshot",
        "description": "Capture the current map view as an image. Use when you need to visually inspect road layout, building footprints, or junction geometry. Returns a PNG. Waits for tiles to load.",
        "input_schema": {
            "type": "object",
            "properties": {
                "basemap": {"type": "string", "enum": ["satellite", "street"], "default": "satellite"},
                "detail": {"type": "string", "enum": ["low", "high"], "default": "low", "description": "low=640x480 (cheap), high=1280x960 (fine detail)"}
            }
        }
    },
    {
        "name": "map.search",
        "description": "Forward/reverse geocode on the map via self-hosted Nominatim. Forward: pass query string. Reverse: pass lat/lng. Returns GeoJSON FeatureCollection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Place name or address for forward geocode"},
                "lat": {"type": "number", "description": "Latitude for reverse geocode"},
                "lng": {"type": "number", "description": "Longitude for reverse geocode"},
                "bbox": {"type": "array", "items": {"type": "number"}, "description": "Bounding box [west, south, east, north]"}
            }
        }
    },
    {
        "name": "map.get_features",
        "description": "Query features from a layer near a location. Returns list of GeoJSON features with properties.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {"type": "string", "description": "3-char nano ID of the layer to query"},
                "h3": {"type": "string", "description": "H3 index to search near"},
                "bbox": {"type": "array", "items": {"type": "number"}, "description": "Bounding box [west, south, east, north]"},
                "limit": {"type": "integer", "default": 10, "description": "Max features to return"}
            },
            "required": ["layer_id"]
        }
    },
    {
        "name": "map.measure",
        "description": "Spatial measurement between map features. Reference features by layer name; for FeatureCollections use 'name[index]'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["distance", "area", "bearing", "buffer", "centroid", "contains", "intersects", "nearest"], "description": "Measurement operation"},
                "a": {"type": "string", "description": "First feature reference (layer name or 'name[index]')"},
                "b": {"type": "string", "description": "Second feature reference (for binary ops like distance, bearing, contains)"},
                "params": {"type": "object", "description": "Operation-specific params (e.g. {units: 'meters'} for distance, {radius: 100} for buffer)"}
            },
            "required": ["op", "a"]
        }
    },
    {
        "name": "map.set_style",
        "description": "Update the style of an existing layer without re-uploading GeoJSON. Merges with current style.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {"type": "string", "description": "3-char nano ID"},
                "style": {"type": "object", "description": "Style properties to merge (color, fill_color, fill_opacity, opacity, radius, icon, weight)"}
            },
            "required": ["layer_id", "style"]
        }
    },
    {
        "name": "map.fit_bounds",
        "description": "Auto-zoom the map to show all specified layers, or all layers if none specified.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_ids": {"type": "array", "items": {"type": "string"}, "description": "Layer IDs to fit. Omit to fit all layers."},
                "padding": {"type": "integer", "default": 50, "description": "Pixels of padding around bounds"}
            }
        }
    },
    # ... other tools (remove_layer, clear_layers, set_view, add_raster_layer, list_layers, toggle_layer)
]
```

The screenshot is returned as an image content block in the agent conversation, so the LLM sees it natively as a multimodal input. The describe output is returned as text.

## Human Observer

The human opens `localhost:3000` in their browser and sees:
- The live map with all layers the agent has added
- A layer panel showing all active layers with toggle switches
- Real-time updates as the agent adds/removes layers and moves the view
