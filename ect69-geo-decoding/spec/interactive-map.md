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
│    - map.set_view(h3, zoom)           │
│    - map.describe()                   │
│    - map.screenshot(basemap)          │
│    - map.search(query/lat/lng)        │
│    - map.get_features(layer, area)    │
│    - map.exec(expression)             │
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

The `feature()` helper in `map.exec` accepts either the nano ID or the human-readable name.

## Tools

### `map.add_layer`

Add any GeoJSON to the map. Returns a 3-char nano ID.

```python
def add_layer(
    geojson: dict,            # any valid GeoJSON (Point, Polygon, FeatureCollection, etc.)
    name: str,                # human-readable label shown in layer panel
    style: dict | None = None # optional style (see Style Schema below)
) -> str:                     # returns 3-char nano ID (e.g. "a1b")
```

**Examples:**

```python
# drop a pin
add_layer(
    geojson={"type": "Point", "coordinates": [100.49, 13.75]},
    name="candidate",
    style={"color": "red", "icon": "pin"}
)
# → "a1b"

# show a boundary polygon
add_layer(
    geojson=tambon_polygon_geojson,
    name="tambon boundary",
    style={"color": "blue", "fill_opacity": 0.1}
)
# → "x7q"

# show multiple points at once
add_layer(
    geojson={"type": "FeatureCollection", "features": [...]},
    name="geocode results",
    style={"color": "orange", "radius": 6}
)
# → "m3p"
```

### `map.remove_layer`

```python
def remove_layer(layer_id: str) -> bool
```

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

### [m3p] tambon boundary (Polygon)
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

### `map.exec`

Run a spatial expression and return the result. Uses turf.js (client-side in Playwright) for exact measurements and spatial operations. More flexible than a bespoke measure tool -- the agent can compute distance, area, bearing, buffer, centroid, etc.

```python
def exec(
    expression: str  # JavaScript expression using turf.js and feature() helper
) -> dict           # result of the expression (JSON-serializable)
```

**Examples:**
```python
# Distance between two features
exec("turf.distance(feature('candidate').geometry, feature('ect66_ref').geometry, {units: 'meters'})")
# → {"result": 3.2}

# Area of a polygon feature
exec("turf.area(feature('tambon_boundary').geometry)")
# → {"result": 823400.5}

# Bearing from one point to another
exec("turf.bearing(feature('candidate').geometry, feature('ect66_ref').geometry)")
# → {"result": 45.3}

# Buffer around a point (returns GeoJSON)
exec("turf.buffer(feature('candidate').geometry, 100, {units: 'meters'})")
# → {"result": {"type": "Polygon", "coordinates": [...]}}
```

The `feature(name)` helper returns the first GeoJSON Feature from the named layer. For FeatureCollections, use `feature(name, index)` to access a specific feature by index.

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
Agent: map.add_layer(point, "candidate", red)        → "a1b"
Agent: map.add_layer(polygon, "tambon boundary", blue) → "x7q"
Agent: map.describe()
  → "[a1b] candidate at 8c2a100d2929dff, inside tambon boundary, 342m from edge"
Agent: [adjusts pin based on text feedback]
Agent: map.remove_layer("a1b")
Agent: map.add_layer(new_point, "candidate v2", red)  → "k9z"
Agent: map.describe(focus="candidate v2")
  → "[k9z] candidate v2 at 8c2a100d292b1ff, adjacent hex to candidate, inside tambon boundary, 280m from edge"
Agent: [looks good spatially, now needs visual confirmation]
Agent: map.screenshot("satellite")
  → [sees building footprint, entrance on south side -- low res sufficient]
Agent: map.screenshot("street", detail="high")
  → [sees road name ถนนมหาราช at high res, confirms location]
Agent: map.exec("turf.distance(feature('candidate v2').geometry, feature('ect66 ref').geometry, {units: 'meters'})")
  → {"result": 3.2}
Agent: [accepts result]
```

## Agent SDK Integration

The map tools are registered as Anthropic Agent SDK tools. The agent calls them like any other tool and receives results in the conversation.

```python
import anthropic

tools = [
    {
        "name": "map.add_layer",
        "description": "Add a GeoJSON layer (points, polygons, lines) to the interactive map.",
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
        "name": "map.exec",
        "description": "Run a turf.js spatial expression and return the result. Use feature('name') to reference a GeoJSON feature from a layer. Supports distance, area, bearing, buffer, centroid, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "JavaScript expression using turf.js and feature() helper"}
            },
            "required": ["expression"]
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
