"""map.describe() – H3-indexed spatial summary of map layers."""

from __future__ import annotations

from typing import Any

import h3
from shapely.geometry import shape

from .layers import LayerStore

# Zoom-to-H3-resolution mapping
ZOOM_TO_H3: dict[int, int] = {
    0: 0,
    1: 0,
    2: 1,
    3: 1,
    4: 2,
    5: 2,
    6: 3,
    7: 3,
    8: 4,
    9: 4,
    10: 5,
    11: 5,
    12: 6,
    13: 6,
    14: 7,
    15: 7,
    16: 8,
    17: 8,
    18: 9,
    19: 9,
    20: 10,
}


def _features_in_cell(features: list[dict], cell: str, resolution: int) -> list[dict]:
    """Filter features whose centroid falls in the given H3 cell."""
    result = []
    for f in features:
        g = f.get("geometry")
        if not g:
            continue
        try:
            s = shape(g)
            c = s.centroid
            fcell = h3.latlng_to_cell(c.y, c.x, resolution)
            if fcell == cell:
                result.append(f)
        except Exception:
            continue
    return result


def _summarize_properties(features: list[dict], max_keys: int = 5) -> dict[str, Any]:
    """Summarize property values across features."""
    if not features:
        return {}
    keys: set[str] = set()
    for f in features:
        keys.update(f.get("properties", {}).keys())

    summary: dict[str, Any] = {}
    for key in sorted(keys)[:max_keys]:
        values = [
            f.get("properties", {}).get(key)
            for f in features
            if key in f.get("properties", {})
        ]
        unique = set(str(v) for v in values if v is not None)
        if len(unique) <= 3:
            summary[key] = list(unique)
        else:
            summary[key] = f"{len(unique)} unique values"
    return summary


def _spatial_relation(layer_a: Any, layer_b: Any) -> str:
    """Compute basic spatial relation between two layers."""
    try:
        shapes_a = []
        shapes_b = []
        for f in layer_a.geojson.get("features", [])[:100]:
            g = f.get("geometry")
            if g:
                shapes_a.append(shape(g))
        for f in layer_b.geojson.get("features", [])[:100]:
            g = f.get("geometry")
            if g:
                shapes_b.append(shape(g))

        if not shapes_a or not shapes_b:
            return "unknown"

        from shapely.ops import unary_union

        union_a = unary_union(shapes_a)
        union_b = unary_union(shapes_b)

        if union_a.contains(union_b):
            return "contains"
        if union_b.contains(union_a):
            return "within"
        if union_a.intersects(union_b):
            return "intersects"
        return "disjoint"
    except Exception:
        return "unknown"


def describe(
    store: LayerStore,
    *,
    viewport_only: bool = False,
    viewport_bbox: list[float] | None = None,
    focus: str | None = None,
    relations_to: str | None = None,
    h3_resolution: int | None = None,
    zoom: int | None = None,
) -> str:
    """Build a structured text description of current map state."""
    layers = store.list_all()
    if not layers:
        return "Map is empty. No layers loaded."

    resolution = h3_resolution or ZOOM_TO_H3.get(zoom or 6, 3)

    lines: list[str] = []
    lines.append(f"## Map Description (H3 resolution {resolution})")
    lines.append(f"**Layers:** {len(layers)}")
    lines.append("")

    for layer in layers:
        if not layer.visible:
            continue
        if layer.is_raster:
            lines.append(f"### {layer.name} (raster)")
            lines.append(f"- URL: {layer.raster_url}")
            lines.append("")
            continue

        features = layer.geojson.get("features", [])

        # Viewport filter
        if viewport_only and viewport_bbox:
            w, s, e, n = viewport_bbox
            filtered = []
            for f in features:
                g = f.get("geometry")
                if not g:
                    continue
                try:
                    sh = shape(g)
                    c = sh.centroid
                    if w <= c.x <= e and s <= c.y <= n:
                        filtered.append(f)
                except Exception:
                    continue
            features = filtered

        lines.append(f"### {layer.name} [{layer.id}]")
        lines.append(f"- Type: {layer.geometry_type}, Features: {len(features)}")
        if layer.bbox:
            lines.append(
                f"- Bbox: [{layer.bbox[0]:.4f}, {layer.bbox[1]:.4f}, {layer.bbox[2]:.4f}, {layer.bbox[3]:.4f}]"
            )

        # H3 binning
        cell_counts: dict[str, int] = {}
        for f in features:
            g = f.get("geometry")
            if not g:
                continue
            try:
                s = shape(g)
                c = s.centroid
                cell = h3.latlng_to_cell(c.y, c.x, resolution)
                cell_counts[cell] = cell_counts.get(cell, 0) + 1
            except Exception:
                continue

        if cell_counts:
            lines.append(f"- H3 cells: {len(cell_counts)}")
            top_cells = sorted(cell_counts.items(), key=lambda x: -x[1])[:5]
            for cell, count in top_cells:
                lat, lng = h3.cell_to_latlng(cell)
                lines.append(f"  - {cell} ({lat:.3f}, {lng:.3f}): {count} features")

        # Property summary
        props = _summarize_properties(features)
        if props:
            lines.append("- Properties:")
            for k, v in props.items():
                lines.append(f"  - {k}: {v}")

        # Relations
        if relations_to:
            rel_layer = store.get(relations_to) or store.find_by_name(relations_to)
            if rel_layer and rel_layer.id != layer.id:
                rel = _spatial_relation(layer, rel_layer)
                lines.append(f"- Relation to {rel_layer.name}: {rel}")

        lines.append("")

    return "\n".join(lines)
