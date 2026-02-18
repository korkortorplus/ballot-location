"""JSON-RPC dispatcher and 15 tool handlers."""

from __future__ import annotations

import json
import logging
from typing import Any

import h3
import httpx

from .browser import HeadlessBrowser
from .describe import describe
from .layers import LayerStore

logger = logging.getLogger("map_tool.handlers")


class Dispatcher:
    """Routes JSON-RPC method calls to handler functions."""

    def __init__(
        self,
        store: LayerStore,
        browser: HeadlessBrowser,
        broadcast: Any,  # async callable(msg: dict)
    ) -> None:
        self.store = store
        self.browser = browser
        self.broadcast = broadcast
        self._methods: dict[str, Any] = {
            "map.add_layer": self.add_layer,
            "map.remove_layer": self.remove_layer,
            "map.set_style": self.set_style,
            "map.clear_layers": self.clear_layers,
            "map.list_layers": self.list_layers,
            "map.toggle_layer": self.toggle_layer,
            "map.set_view": self.set_view,
            "map.fit_bounds": self.fit_bounds,
            "map.screenshot": self.screenshot,
            "map.search": self.search,
            "map.describe": self.describe,
            "map.measure": self.measure,
            "map.get_features": self.get_features,
            "map.add_raster_layer": self.add_raster_layer,
        }

    async def dispatch(self, raw: str) -> str:
        """Parse JSON-RPC request, call handler, return JSON-RPC response."""
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            return _error_response(None, -32700, "Parse error")

        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {})

        handler = self._methods.get(method)
        if not handler:
            return _error_response(req_id, -32601, f"Unknown method: {method}")

        try:
            result = await handler(params)
            return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})
        except Exception as e:
            logger.exception("Handler error for %s", method)
            return _error_response(req_id, -32000, str(e))

    # ---- Tool handlers ----

    async def add_layer(self, params: dict) -> dict:
        geojson = params.get("geojson")
        if not geojson:
            raise ValueError("geojson is required")
        name = params.get("name")
        style = params.get("style")
        layer = self.store.add(geojson, name=name, style=style)
        browser_data = self.store.serialize_for_browser(layer)
        await self.broadcast({"type": "layer_added", "layer": browser_data})
        return self.store.serialize_layer(layer)

    async def remove_layer(self, params: dict) -> dict:
        layer_id = params.get("layer_id", "")
        ok = self.store.remove(layer_id)
        if ok:
            await self.broadcast({"type": "layer_removed", "layer_id": layer_id})
        return {"removed": ok, "layer_id": layer_id}

    async def set_style(self, params: dict) -> dict:
        layer_id = params.get("layer_id", "")
        style = params.get("style", {})
        layer = self.store.set_style(layer_id, style)
        if not layer:
            raise ValueError(f"Layer {layer_id} not found")
        browser_data = self.store.serialize_for_browser(layer)
        await self.broadcast({"type": "layer_updated", "layer": browser_data})
        return self.store.serialize_layer(layer)

    async def clear_layers(self, params: dict) -> dict:
        count = self.store.clear()
        await self.broadcast({"type": "clear_layers"})
        return {"cleared": count}

    async def list_layers(self, params: dict) -> list[dict]:
        return [self.store.serialize_layer(ly) for ly in self.store.list_all()]

    async def toggle_layer(self, params: dict) -> dict:
        layer_id = params.get("layer_id", "")
        layer = self.store.toggle(layer_id)
        if not layer:
            raise ValueError(f"Layer {layer_id} not found")
        browser_data = self.store.serialize_for_browser(layer)
        await self.broadcast({"type": "layer_updated", "layer": browser_data})
        return {"layer_id": layer_id, "visible": layer.visible}

    async def set_view(self, params: dict) -> dict:
        h3_cell = params.get("h3")
        lat = params.get("lat")
        lng = params.get("lng")
        zoom = params.get("zoom")

        center = None
        if h3_cell:
            clat, clng = h3.cell_to_latlng(h3_cell)
            center = [clng, clat]
            if zoom is None:
                res = h3.get_resolution(h3_cell)
                # Rough mapping: res 0->2, 4->8, 7->13, 10->16
                zoom = min(2 + res * 1.5, 18)
        elif lat is not None and lng is not None:
            center = [lng, lat]

        view: dict[str, Any] = {}
        if center:
            view["center"] = center
        if zoom is not None:
            view["zoom"] = zoom

        await self.broadcast({"type": "set_view", "view": view})
        return {"view": view}

    async def fit_bounds(self, params: dict) -> dict:
        layer_ids = params.get("layer_ids")
        bbox = self.store.combined_bbox(layer_ids)
        if not bbox:
            raise ValueError("No layers with bounding boxes found")
        await self.broadcast({"type": "fit_bounds", "bounds": bbox})
        return {"bounds": bbox}

    async def screenshot(self, params: dict) -> dict:
        detail = params.get("detail", "high")
        basemap = params.get("basemap")
        if detail == "low":
            w, h = 640, 480
        else:
            w, h = 1280, 960

        b64 = await self.browser.screenshot(width=w, height=h, basemap=basemap)
        return {"image": b64, "width": w, "height": h, "format": "png"}

    async def search(self, params: dict) -> dict:
        query = params.get("query")
        lat = params.get("lat")
        lng = params.get("lng")

        async with httpx.AsyncClient(timeout=10) as client:
            if query:
                # Forward geocode
                resp = await client.get(
                    "http://localhost:8080/search",
                    params={"q": query, "format": "geojson", "limit": 5},
                )
            elif lat is not None and lng is not None:
                # Reverse geocode
                resp = await client.get(
                    "http://localhost:8080/reverse",
                    params={"lat": lat, "lon": lng, "format": "geojson"},
                )
            else:
                raise ValueError("Provide query (forward) or lat+lng (reverse)")

            resp.raise_for_status()
            return resp.json()

    async def describe(self, params: dict) -> dict:
        text = describe(
            self.store,
            viewport_only=params.get("viewport_only", False),
            viewport_bbox=params.get("viewport_bbox"),
            focus=params.get("focus"),
            relations_to=params.get("relations_to"),
            h3_resolution=params.get("h3_resolution"),
            zoom=params.get("zoom"),
        )
        return {"description": text}

    async def measure(self, params: dict) -> dict:
        op = params.get("op")
        if not op:
            raise ValueError("op is required")

        supported = [
            "distance",
            "area",
            "bearing",
            "buffer",
            "centroid",
            "contains",
            "intersects",
            "nearest",
        ]
        if op not in supported:
            raise ValueError(f"Unsupported op: {op}. Supported: {supported}")

        # Resolve layer references to GeoJSON
        a_ref = params.get("a")
        b_ref = params.get("b")

        a_geojson = self._resolve_feature_ref(a_ref) if a_ref else None
        b_geojson = self._resolve_feature_ref(b_ref) if b_ref else None

        # Build turf.js expression
        expr = self._build_turf_expr(op, a_geojson, b_geojson, params)
        result = await self.browser.evaluate_js(expr)
        return {"op": op, "result": result}

    async def get_features(self, params: dict) -> dict:
        layer_id = params.get("layer_id")
        h3_cell = params.get("h3")
        bbox = params.get("bbox")
        limit = params.get("limit", 100)

        layer = None
        if layer_id:
            layer = self.store.get(layer_id) or self.store.find_by_name(layer_id)
        if not layer:
            raise ValueError(f"Layer not found: {layer_id}")

        features = layer.geojson.get("features", [])

        from shapely.geometry import shape, box

        if h3_cell:
            res = h3.get_resolution(h3_cell)
            filtered = []
            for f in features:
                g = f.get("geometry")
                if not g:
                    continue
                try:
                    s = shape(g)
                    c = s.centroid
                    cell = h3.latlng_to_cell(c.y, c.x, res)
                    if cell == h3_cell:
                        filtered.append(f)
                except Exception:
                    continue
            features = filtered
        elif bbox:
            w, s_val, e, n = bbox
            bbox_poly = box(w, s_val, e, n)
            filtered = []
            for f in features:
                g = f.get("geometry")
                if not g:
                    continue
                try:
                    s = shape(g)
                    if s.intersects(bbox_poly):
                        filtered.append(f)
                except Exception:
                    continue
            features = filtered

        return {
            "layer_id": layer.id,
            "total": len(features),
            "features": features[:limit],
        }

    async def add_raster_layer(self, params: dict) -> dict:
        url = params.get("url")
        if not url:
            raise ValueError("url is required")
        name = params.get("name")
        bounds = params.get("bounds")
        layer = self.store.add_raster(url, name=name, bounds=bounds)
        browser_data = self.store.serialize_for_browser(layer)
        await self.broadcast({"type": "layer_added", "layer": browser_data})
        return self.store.serialize_layer(layer)

    # ---- Helpers ----

    def _resolve_feature_ref(self, ref: str) -> str:
        """Resolve 'layer_name' or 'layer_name[0]' to GeoJSON string."""
        idx = None
        name = ref
        if "[" in ref and ref.endswith("]"):
            name, idx_str = ref.rstrip("]").split("[", 1)
            try:
                idx = int(idx_str)
            except ValueError:
                pass

        layer = self.store.get(name) or self.store.find_by_name(name)
        if not layer:
            raise ValueError(f"Layer not found: {name}")

        if idx is not None:
            features = layer.geojson.get("features", [])
            if 0 <= idx < len(features):
                return json.dumps(features[idx])
            raise ValueError(f"Feature index {idx} out of range for {name}")

        return json.dumps(layer.geojson)

    def _build_turf_expr(
        self, op: str, a: str | None, b: str | None, params: dict
    ) -> str:
        """Build a turf.js expression string to evaluate in the browser."""
        if op == "distance":
            return f"turf.distance(turf.centroid({a}), turf.centroid({b}), {{units: '{params.get('units', 'kilometers')}'}})"
        if op == "area":
            return f"turf.area({a})"
        if op == "bearing":
            return f"turf.bearing(turf.centroid({a}), turf.centroid({b}))"
        if op == "buffer":
            radius = params.get("radius", 1)
            units = params.get("units", "kilometers")
            return f"turf.buffer({a}, {radius}, {{units: '{units}'}})"
        if op == "centroid":
            return f"turf.centroid({a}).geometry.coordinates"
        if op == "contains":
            return f"turf.booleanContains({a}, {b})"
        if op == "intersects":
            return f"turf.booleanIntersects({a}, {b})"
        if op == "nearest":
            return f"turf.nearestPoint(turf.centroid({a}), {b}).geometry.coordinates"
        raise ValueError(f"Unknown op: {op}")


def _error_response(req_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
    )
