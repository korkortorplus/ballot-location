"""In-memory layer store – single source of truth for all map layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import h3
from nanoid import generate as nanoid
from shapely.geometry import shape

NANO_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
NANO_SIZE = 3

# Palette for auto-assigning colors to layers
PALETTE = [
    "#e6194b",
    "#3cb44b",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#42d4f4",
    "#f032e6",
    "#bfef45",
    "#fabed4",
    "#469990",
    "#dcbeff",
    "#9A6324",
    "#800000",
    "#aaffc3",
    "#808000",
    "#ffd8b1",
    "#000075",
    "#a9a9a9",
]


def _geometry_type(geojson: dict) -> str:
    """Determine dominant geometry type from a GeoJSON object."""
    features = geojson.get("features", [])
    if not features:
        return "unknown"
    types: set[str] = set()
    for f in features:
        g = f.get("geometry")
        if g:
            types.add(g["type"])
    if types & {"Polygon", "MultiPolygon"}:
        return "polygon"
    if types & {"LineString", "MultiLineString"}:
        return "line"
    return "point"


def _compute_bbox(geojson: dict) -> list[float] | None:
    """Compute [west, south, east, north] bounding box."""
    coords: list[tuple[float, float]] = []
    for f in geojson.get("features", []):
        g = f.get("geometry")
        if not g:
            continue
        try:
            s = shape(g)
            b = s.bounds  # (minx, miny, maxx, maxy)
            coords.append((b[0], b[1]))
            coords.append((b[2], b[3]))
        except Exception:
            continue
    if not coords:
        return None
    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return [min(lngs), min(lats), max(lngs), max(lats)]


def _compute_h3_cells(geojson: dict, resolution: int = 4) -> list[str]:
    """Compute H3 cell indexes covering the features."""
    cells: set[str] = set()
    for f in geojson.get("features", []):
        g = f.get("geometry")
        if not g:
            continue
        gtype = g["type"]
        if gtype == "Point":
            lat, lng = g["coordinates"][1], g["coordinates"][0]
            cells.add(h3.latlng_to_cell(lat, lng, resolution))
        elif gtype in ("Polygon", "MultiPolygon"):
            try:
                s = shape(g)
                centroid = s.centroid
                cells.add(h3.latlng_to_cell(centroid.y, centroid.x, resolution))
            except Exception:
                pass
        elif gtype in ("LineString", "MultiLineString"):
            try:
                s = shape(g)
                centroid = s.centroid
                cells.add(h3.latlng_to_cell(centroid.y, centroid.x, resolution))
            except Exception:
                pass
    return sorted(cells)


@dataclass
class Layer:
    id: str
    name: str
    geojson: dict
    geometry_type: str
    bbox: list[float] | None
    h3_cells: list[str]
    feature_count: int
    visible: bool = True
    style: dict = field(default_factory=dict)
    is_raster: bool = False
    raster_url: str | None = None


class LayerStore:
    """Thread-safe in-memory store for map layers."""

    def __init__(self) -> None:
        self._layers: dict[str, Layer] = {}
        self._color_idx = 0

    def _next_color(self) -> str:
        c = PALETTE[self._color_idx % len(PALETTE)]
        self._color_idx += 1
        return c

    def add(
        self,
        geojson: dict,
        name: str | None = None,
        style: dict | None = None,
    ) -> Layer:
        layer_id = nanoid(NANO_ALPHABET, NANO_SIZE)
        while layer_id in self._layers:
            layer_id = nanoid(NANO_ALPHABET, NANO_SIZE)

        # Normalize to FeatureCollection
        if geojson.get("type") == "Feature":
            geojson = {"type": "FeatureCollection", "features": [geojson]}
        elif geojson.get("type") not in ("FeatureCollection",):
            # Bare geometry
            geojson = {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": geojson, "properties": {}}
                ],
            }

        geo_type = _geometry_type(geojson)
        bbox = _compute_bbox(geojson)
        h3_cells = _compute_h3_cells(geojson)
        feature_count = len(geojson.get("features", []))

        default_color = self._next_color()
        default_style: dict[str, Any] = {}
        if geo_type == "point":
            default_style = {
                "circle-radius": 6,
                "circle-color": default_color,
                "circle-opacity": 0.8,
            }
        elif geo_type == "line":
            default_style = {
                "line-color": default_color,
                "line-width": 3,
                "line-opacity": 0.8,
            }
        elif geo_type == "polygon":
            default_style = {
                "fill-color": default_color,
                "fill-opacity": 0.4,
                "line-color": default_color,
                "line-width": 1,
            }

        if style:
            default_style.update(style)

        layer = Layer(
            id=layer_id,
            name=name or f"layer-{layer_id}",
            geojson=geojson,
            geometry_type=geo_type,
            bbox=bbox,
            h3_cells=h3_cells,
            feature_count=feature_count,
            style=default_style,
        )
        self._layers[layer_id] = layer
        return layer

    def add_raster(
        self, url: str, name: str | None = None, bounds: list[float] | None = None
    ) -> Layer:
        layer_id = nanoid(NANO_ALPHABET, NANO_SIZE)
        while layer_id in self._layers:
            layer_id = nanoid(NANO_ALPHABET, NANO_SIZE)
        layer = Layer(
            id=layer_id,
            name=name or f"raster-{layer_id}",
            geojson={"type": "FeatureCollection", "features": []},
            geometry_type="raster",
            bbox=bounds,
            h3_cells=[],
            feature_count=0,
            is_raster=True,
            raster_url=url,
        )
        self._layers[layer_id] = layer
        return layer

    def remove(self, layer_id: str) -> bool:
        return self._layers.pop(layer_id, None) is not None

    def get(self, layer_id: str) -> Layer | None:
        return self._layers.get(layer_id)

    def find_by_name(self, name: str) -> Layer | None:
        for layer in self._layers.values():
            if layer.name == name:
                return layer
        return None

    def list_all(self) -> list[Layer]:
        return list(self._layers.values())

    def clear(self) -> int:
        count = len(self._layers)
        self._layers.clear()
        self._color_idx = 0
        return count

    def set_style(self, layer_id: str, style: dict) -> Layer | None:
        layer = self._layers.get(layer_id)
        if layer:
            layer.style.update(style)
        return layer

    def toggle(self, layer_id: str) -> Layer | None:
        layer = self._layers.get(layer_id)
        if layer:
            layer.visible = not layer.visible
        return layer

    def combined_bbox(self, layer_ids: list[str] | None = None) -> list[float] | None:
        layers = (
            [self._layers[lid] for lid in layer_ids if lid in self._layers]
            if layer_ids
            else list(self._layers.values())
        )
        bboxes = [ly.bbox for ly in layers if ly.bbox]
        if not bboxes:
            return None
        return [
            min(b[0] for b in bboxes),
            min(b[1] for b in bboxes),
            max(b[2] for b in bboxes),
            max(b[3] for b in bboxes),
        ]

    def serialize_layer(self, layer: Layer) -> dict:
        """Return layer metadata (without full GeoJSON) for the agent."""
        return {
            "id": layer.id,
            "name": layer.name,
            "geometry_type": layer.geometry_type,
            "feature_count": layer.feature_count,
            "bbox": layer.bbox,
            "h3_cells": layer.h3_cells,
            "visible": layer.visible,
            "style": layer.style,
            "is_raster": layer.is_raster,
        }

    def serialize_for_browser(self, layer: Layer) -> dict:
        """Return full layer data for the browser to render."""
        d = self.serialize_layer(layer)
        if layer.is_raster:
            d["raster_url"] = layer.raster_url
        else:
            d["geojson"] = layer.geojson
        return d
