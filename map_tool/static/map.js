// Map Tool – browser-side map + WebSocket sync
(function () {
  "use strict";

  const BASEMAPS = {
    street: "https://tiles.openfreemap.org/styles/bright",
    satellite:
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  };

  // Thailand center
  const map = new maplibregl.Map({
    container: "map",
    style: BASEMAPS.street,
    center: [100.5, 13.75],
    zoom: 6,
  });

  const layerState = {}; // id -> {name, geojson, style, visible, geometry_type, feature_count, is_raster, raster_url}
  let currentPopup = null;

  // ---- Status bar ----
  const statusEl = document.getElementById("status-bar");
  function setStatus(msg) {
    statusEl.textContent = msg;
  }

  // ---- Map ready signals ----
  window.__mapReady = false;
  window.__mapIdle = false;

  map.on("load", () => {
    window.__mapReady = true;
    connectWS();
  });

  map.on("idle", () => {
    window.__mapIdle = true;
  });
  map.on("movestart", () => {
    window.__mapIdle = false;
  });

  // ---- Basemap switch (for screenshot tool) ----
  window.__setBasemap = function (name) {
    if (name === "satellite") {
      // For satellite, add a raster source underneath
      if (!map.getSource("satellite-tiles")) {
        map.addSource("satellite-tiles", {
          type: "raster",
          tiles: [BASEMAPS.satellite],
          tileSize: 256,
          maxzoom: 18,
        });
        map.addLayer(
          { id: "satellite-layer", type: "raster", source: "satellite-tiles" },
          map.getStyle().layers[0]?.id
        );
      }
      map.setLayoutProperty("satellite-layer", "visibility", "visible");
    } else {
      if (map.getLayer("satellite-layer")) {
        map.setLayoutProperty("satellite-layer", "visibility", "none");
      }
    }
  };

  // ---- WebSocket ----
  let ws = null;
  function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws/browser`);

    ws.onopen = () => setStatus("Connected");
    ws.onclose = () => {
      setStatus("Disconnected – reconnecting...");
      setTimeout(connectWS, 2000);
    };
    ws.onerror = () => ws.close();

    ws.onmessage = (evt) => {
      let msg;
      try {
        msg = JSON.parse(evt.data);
      } catch {
        return;
      }
      handleServerMsg(msg);
    };
  }

  function handleServerMsg(msg) {
    switch (msg.type) {
      case "sync":
        // Full state sync
        for (const layer of msg.layers || []) {
          addLayerToMap(layer);
        }
        if (msg.view) applyView(msg.view);
        refreshPanel();
        break;
      case "layer_added":
        addLayerToMap(msg.layer);
        refreshPanel();
        break;
      case "layer_removed":
        removeLayerFromMap(msg.layer_id);
        refreshPanel();
        break;
      case "layer_updated":
        removeLayerFromMap(msg.layer.id);
        addLayerToMap(msg.layer);
        refreshPanel();
        break;
      case "set_view":
        applyView(msg.view);
        break;
      case "fit_bounds":
        if (msg.bounds) {
          map.fitBounds(
            [
              [msg.bounds[0], msg.bounds[1]],
              [msg.bounds[2], msg.bounds[3]],
            ],
            { padding: 40, maxZoom: 16 }
          );
        }
        break;
      case "clear_layers":
        clearAllLayers();
        refreshPanel();
        break;
    }
  }

  function applyView(view) {
    const opts = {};
    if (view.center) opts.center = view.center;
    if (view.zoom != null) opts.zoom = view.zoom;
    if (Object.keys(opts).length) map.flyTo({ ...opts, duration: 1000 });
  }

  // ---- Layer rendering ----
  function addLayerToMap(layer) {
    layerState[layer.id] = layer;
    const srcId = `src-${layer.id}`;

    if (layer.is_raster && layer.raster_url) {
      if (!map.getSource(srcId)) {
        map.addSource(srcId, {
          type: "raster",
          tiles: [layer.raster_url],
          tileSize: 256,
        });
      }
      if (!map.getLayer(layer.id)) {
        map.addLayer({
          id: layer.id,
          type: "raster",
          source: srcId,
          layout: { visibility: layer.visible ? "visible" : "none" },
        });
      }
      return;
    }

    if (!map.getSource(srcId)) {
      map.addSource(srcId, { type: "geojson", data: layer.geojson });
    }

    const style = layer.style || {};
    const gtype = layer.geometry_type;

    if (gtype === "point") {
      if (!map.getLayer(layer.id)) {
        map.addLayer({
          id: layer.id,
          type: "circle",
          source: srcId,
          paint: {
            "circle-radius": style["circle-radius"] || 6,
            "circle-color": style["circle-color"] || "#e6194b",
            "circle-opacity": style["circle-opacity"] || 0.8,
          },
          layout: { visibility: layer.visible ? "visible" : "none" },
        });
      }
    } else if (gtype === "line") {
      if (!map.getLayer(layer.id)) {
        map.addLayer({
          id: layer.id,
          type: "line",
          source: srcId,
          paint: {
            "line-color": style["line-color"] || "#4363d8",
            "line-width": style["line-width"] || 3,
            "line-opacity": style["line-opacity"] || 0.8,
          },
          layout: { visibility: layer.visible ? "visible" : "none" },
        });
      }
    } else if (gtype === "polygon") {
      const fillId = `${layer.id}-fill`;
      const lineId = `${layer.id}-outline`;
      if (!map.getLayer(fillId)) {
        map.addLayer({
          id: fillId,
          type: "fill",
          source: srcId,
          paint: {
            "fill-color": style["fill-color"] || "#088",
            "fill-opacity": style["fill-opacity"] || 0.4,
          },
          layout: { visibility: layer.visible ? "visible" : "none" },
        });
      }
      if (!map.getLayer(lineId)) {
        map.addLayer({
          id: lineId,
          type: "line",
          source: srcId,
          paint: {
            "line-color": style["line-color"] || "#088",
            "line-width": style["line-width"] || 1,
          },
          layout: { visibility: layer.visible ? "visible" : "none" },
        });
      }
    }

    // Click popup
    const clickLayerId = gtype === "polygon" ? `${layer.id}-fill` : layer.id;
    map.on("click", clickLayerId, (e) => {
      if (!e.features || !e.features.length) return;
      const props = e.features[0].properties;
      let html = '<table class="popup-table">';
      for (const [k, v] of Object.entries(props)) {
        html += `<tr><td>${k}</td><td>${v}</td></tr>`;
      }
      html += "</table>";

      if (currentPopup) currentPopup.remove();
      currentPopup = new maplibregl.Popup({ maxWidth: "300px" })
        .setLngLat(e.lngLat)
        .setHTML(html)
        .addTo(map);
    });

    // Cursor
    map.on("mouseenter", clickLayerId, () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", clickLayerId, () => {
      map.getCanvas().style.cursor = "";
    });
  }

  function removeLayerFromMap(layerId) {
    const layer = layerState[layerId];
    if (!layer) return;

    const gtype = layer.geometry_type;
    const srcId = `src-${layerId}`;

    if (gtype === "polygon") {
      if (map.getLayer(`${layerId}-fill`)) map.removeLayer(`${layerId}-fill`);
      if (map.getLayer(`${layerId}-outline`)) map.removeLayer(`${layerId}-outline`);
    } else {
      if (map.getLayer(layerId)) map.removeLayer(layerId);
    }
    if (map.getSource(srcId)) map.removeSource(srcId);
    delete layerState[layerId];
  }

  function clearAllLayers() {
    for (const id of Object.keys(layerState)) {
      removeLayerFromMap(id);
    }
  }

  // ---- Layer panel ----
  function refreshPanel() {
    const list = document.getElementById("layer-list");
    const countEl = document.getElementById("layer-count");
    const layers = Object.values(layerState);
    countEl.textContent = layers.length;

    list.innerHTML = "";
    for (const layer of layers) {
      const item = document.createElement("div");
      item.className = "layer-item";

      const color = document.createElement("div");
      color.className = "layer-color";
      color.style.background =
        layer.style?.["circle-color"] ||
        layer.style?.["fill-color"] ||
        layer.style?.["line-color"] ||
        "#888";

      const name = document.createElement("div");
      name.className = "layer-name";
      name.textContent = layer.name;
      name.title = `${layer.name} [${layer.id}]`;

      const count = document.createElement("div");
      count.className = "layer-count";
      count.textContent = layer.is_raster ? "raster" : layer.feature_count;

      const eyeBtn = document.createElement("button");
      eyeBtn.className = `layer-btn${layer.visible ? "" : " hidden"}`;
      eyeBtn.textContent = layer.visible ? "👁" : "👁‍🗨";
      eyeBtn.title = "Toggle visibility";
      eyeBtn.onclick = () => toggleLayerVisibility(layer.id);

      const removeBtn = document.createElement("button");
      removeBtn.className = "layer-btn";
      removeBtn.textContent = "✕";
      removeBtn.title = "Remove layer";
      removeBtn.onclick = () => requestRemoveLayer(layer.id);

      item.append(color, name, count, eyeBtn, removeBtn);
      list.appendChild(item);
    }
  }

  function toggleLayerVisibility(layerId) {
    const layer = layerState[layerId];
    if (!layer) return;
    layer.visible = !layer.visible;
    const vis = layer.visible ? "visible" : "none";

    if (layer.geometry_type === "polygon") {
      if (map.getLayer(`${layerId}-fill`)) map.setLayoutProperty(`${layerId}-fill`, "visibility", vis);
      if (map.getLayer(`${layerId}-outline`)) map.setLayoutProperty(`${layerId}-outline`, "visibility", vis);
    } else {
      if (map.getLayer(layerId)) map.setLayoutProperty(layerId, "visibility", vis);
    }
    refreshPanel();

    // Notify server
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "toggle", layer_id: layerId }));
    }
  }

  function requestRemoveLayer(layerId) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "remove", layer_id: layerId }));
    }
  }

  // Expose for Playwright evaluate
  window.__getLayerState = () => layerState;
  window.__getMap = () => map;
})();
