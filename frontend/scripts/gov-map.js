// gov-map.js — paginated, clustered Leaflet map fed by a CKAN
// (data.gov.il) datastore_search resource. Pre-loaded by the Nuxt
// dataset shell (see frontend/utils/dataset-libs.ts), so agent-emitted
// content.html can call window.GovMap.create({...}) without inlining
// thousands of marker coordinates as a JS array literal.
//
// Why this exists: pre-GovMap, map pages baked the entire point set into
// HTML as a JS literal — 226KB on b2370286 (קרקעות מזוהמות), 63KB on
// 5944b454 (עצים בבאר שבע). Tailwind JIT scanned the junk and the parse
// cost on first paint was meaningful on mobile. GovMap fetches the same
// rows live from the same CKAN endpoint on browser load.
//
// CORS: data.gov.il responds with permissive CORS for plain GETs to
// /api/3/action/. We do not set custom headers and do not send
// credentials, so no preflight is issued.
//
// Projections: many CKAN datasets store coordinates in Israeli
// Transverse Mercator (ITM, EPSG:2039) rather than WGS84 lat/lng. Pass
// `projection: 'itm'` and the lib applies the inverse transform inline,
// including the Israel 1993 -> WGS84 datum shift (without it points land
// ~78 m to the south-west). Accuracy is ~1-2 m inside Israel's bounding
// box — far below marker rendering scale.
//
// Safety: popup rendering is structured (descriptors {field, label} →
// textContent only), so untrusted CKAN values cannot inject markup.
(function () {
  "use strict";

  // Leaflet 1.9's default attribution prefix embeds a flag icon. Replace
  // it for every map on the page — GovMap's and any body calling L.map
  // directly — since this file loads after leaflet.js and before the
  // body's inline scripts. Tile-layer credits (OSM) are unaffected.
  if (window.L && L.Control && L.Control.Attribution) {
    L.Control.Attribution.prototype.options.prefix =
      '<a href="https://leafletjs.com" title="A JavaScript library for interactive maps">Leaflet</a>';
  }

  // EPSG:2039 (Israeli Transverse Mercator) inverse transform parameters.
  // Source: EPSG database. Snyder/USGS Bulletin 1532 standard TM inverse,
  // GRS80 ellipsoid (the Israeli 1993 datum is GRS80-based).
  var ITM_A = 6378137;
  var ITM_F = 1 / 298.257222101;
  var ITM_E2 = 2 * ITM_F - ITM_F * ITM_F;
  var ITM_E4 = ITM_E2 * ITM_E2;
  var ITM_E6 = ITM_E2 * ITM_E4;
  var ITM_K0 = 1.0000067;
  var ITM_LAT0 = (31.7343936111 * Math.PI) / 180;
  var ITM_LNG0 = (35.2045169444 * Math.PI) / 180;
  var ITM_FE = 219529.584;
  var ITM_FN = 626907.39;
  var ITM_M0 = (function () {
    var lat = ITM_LAT0;
    return (
      ITM_A *
      ((1 - ITM_E2 / 4 - (3 * ITM_E4) / 64 - (5 * ITM_E6) / 256) * lat -
        ((3 * ITM_E2) / 8 + (3 * ITM_E4) / 32 + (45 * ITM_E6) / 1024) *
          Math.sin(2 * lat) +
        ((15 * ITM_E4) / 256 + (45 * ITM_E6) / 1024) * Math.sin(4 * lat) -
        ((35 * ITM_E6) / 3072) * Math.sin(6 * lat))
    );
  })();

  // Datum shift: the TM inverse above yields geodetic coords on the Israel
  // 1993 datum (GRS80). OSM/WGS84 tiles need a Helmert transform to WGS84 —
  // skipping it leaves every point ~78 m to the south-west. Params are the
  // PROJ +towgs84 7-parameter (Position Vector) set for EPSG:2039.
  var DATUM_TX = -24.0024,
    DATUM_TY = -17.1032,
    DATUM_TZ = -17.1032; // metres
  var DATUM_RX = -0.33077,
    DATUM_RY = -1.85269,
    DATUM_RZ = 1.66902; // arc-sec
  var DATUM_DS = 5.4262; // ppm
  var DATUM_ARC = Math.PI / 180 / 3600;
  var WGS84_F = 1 / 298.257223563;
  var WGS84_E2 = 2 * WGS84_F - WGS84_F * WGS84_F;

  // geodetic (rad, h=0 on GRS80) -> WGS84 [lat, lng] in degrees
  function israel93ToWgs84(latRad, lngRad) {
    var sin = Math.sin(latRad),
      cos = Math.cos(latRad);
    var N = ITM_A / Math.sqrt(1 - ITM_E2 * sin * sin);
    var X = N * cos * Math.cos(lngRad);
    var Y = N * cos * Math.sin(lngRad);
    var Z = N * (1 - ITM_E2) * sin;
    var rx = DATUM_RX * DATUM_ARC,
      ry = DATUM_RY * DATUM_ARC,
      rz = DATUM_RZ * DATUM_ARC;
    var s = 1 + DATUM_DS * 1e-6;
    var Xp = DATUM_TX + s * (X - rz * Y + ry * Z);
    var Yp = DATUM_TY + s * (rz * X + Y - rx * Z);
    var Zp = DATUM_TZ + s * (-ry * X + rx * Y + Z);
    var lng = Math.atan2(Yp, Xp);
    var p = Math.sqrt(Xp * Xp + Yp * Yp);
    var lat = Math.atan2(Zp, p * (1 - WGS84_E2));
    for (var i = 0; i < 5; i++) {
      var s2 = Math.sin(lat);
      var Nw = ITM_A / Math.sqrt(1 - WGS84_E2 * s2 * s2);
      var h = p / Math.cos(lat) - Nw;
      lat = Math.atan2(Zp, p * (1 - (WGS84_E2 * Nw) / (Nw + h)));
    }
    return [(lat * 180) / Math.PI, (lng * 180) / Math.PI];
  }

  function itmToWgs84(easting, northing) {
    var Mp = ITM_M0 + (northing - ITM_FN) / ITM_K0;
    var ep = (1 - Math.sqrt(1 - ITM_E2)) / (1 + Math.sqrt(1 - ITM_E2));
    var mu =
      Mp / (ITM_A * (1 - ITM_E2 / 4 - (3 * ITM_E4) / 64 - (5 * ITM_E6) / 256));
    var phi1 =
      mu +
      ((3 * ep) / 2 - (27 * Math.pow(ep, 3)) / 32) * Math.sin(2 * mu) +
      ((21 * ep * ep) / 16 - (55 * Math.pow(ep, 4)) / 32) * Math.sin(4 * mu) +
      ((151 * Math.pow(ep, 3)) / 96) * Math.sin(6 * mu) +
      ((1097 * Math.pow(ep, 4)) / 512) * Math.sin(8 * mu);
    var sinPhi1 = Math.sin(phi1);
    var cosPhi1 = Math.cos(phi1);
    var tanPhi1 = sinPhi1 / cosPhi1;
    var ep2 = ITM_E2 / (1 - ITM_E2);
    var C1 = ep2 * cosPhi1 * cosPhi1;
    var T1 = tanPhi1 * tanPhi1;
    var N1 = ITM_A / Math.sqrt(1 - ITM_E2 * sinPhi1 * sinPhi1);
    var R1 =
      (ITM_A * (1 - ITM_E2)) / Math.pow(1 - ITM_E2 * sinPhi1 * sinPhi1, 1.5);
    var D = (easting - ITM_FE) / (N1 * ITM_K0);
    var D2 = D * D,
      D3 = D2 * D,
      D4 = D3 * D,
      D5 = D4 * D,
      D6 = D5 * D;
    var lat =
      phi1 -
      ((N1 * tanPhi1) / R1) *
        (D2 / 2 -
          ((5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep2) * D4) / 24 +
          ((61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * ep2 - 3 * C1 * C1) *
            D6) /
            720);
    var lng =
      ITM_LNG0 +
      (D -
        ((1 + 2 * T1 + C1) * D3) / 6 +
        ((5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * ep2 + 24 * T1 * T1) * D5) /
          120) /
        cosPhi1;
    return israel93ToWgs84(lat, lng);
  }

  function ensureStyles() {
    if (document.getElementById("gov-map-styles")) return;
    var style = document.createElement("style");
    style.id = "gov-map-styles";
    style.textContent =
      ".gov-map-wrap{position:relative;width:100%;border-radius:.5rem;overflow:hidden}" +
      ".gov-map-wrap .leaflet-container{width:100%;height:100%;font-family:Rubik,sans-serif}" +
      ".gov-map-skel{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:linear-gradient(90deg,#f1f7ff 0%,#e7eef9 50%,#f1f7ff 100%);background-size:200% 100%;animation:gov-map-pulse 1.4s ease-in-out infinite;color:#6c757d;font-size:.85rem;z-index:401}" +
      ".gov-map-state{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:1rem;color:#6c757d;font-size:.9rem;background:#f1f7ff;z-index:401}" +
      ".gov-map-state[data-kind=error]{color:#dc3545}" +
      ".gov-map-note{position:absolute;top:8px;right:8px;z-index:402;background:rgba(255,255,255,.92);color:#0c3058;font-size:.72rem;line-height:1.3;padding:.2rem .5rem;border-radius:.4rem;box-shadow:0 1px 3px rgba(11,54,104,.15);pointer-events:none;direction:rtl}" +
      ".gov-map-popup{font-family:Rubik,sans-serif;font-size:.85rem;color:#0c3058;direction:rtl;text-align:right;line-height:1.5;min-width:180px;max-width:260px}" +
      ".gov-map-popup-title{font-weight:600;color:#0b3668;margin:0 0 .35rem;font-size:.95rem}" +
      ".gov-map-popup-row{margin:0;padding:.1rem 0;display:flex;gap:.4rem}" +
      ".gov-map-popup-row dt{flex:0 0 auto;color:#6c757d;font-weight:500;margin:0}" +
      ".gov-map-popup-row dd{flex:1 1 auto;margin:0;color:#0c3058}" +
      "@keyframes gov-map-pulse{0%{background-position:100% 0}100%{background-position:-100% 0}}";
    document.head.appendChild(style);
  }

  function resolveEl(target) {
    if (typeof target === "string") return document.querySelector(target);
    if (target instanceof Element) return target;
    return null;
  }

  function fetchPage(opts) {
    var params = new URLSearchParams();
    params.set("resource_id", opts.resourceId);
    if (opts.fields && opts.fields.length)
      params.set("fields", opts.fields.join(","));
    if (opts.filters) params.set("filters", JSON.stringify(opts.filters));
    if (opts.q) params.set("q", String(opts.q));
    params.set("limit", String(opts.limit));
    if (opts.offset) params.set("offset", String(opts.offset));
    params.set("include_total", "true");
    var url =
      "https://data.gov.il/api/3/action/datastore_search?" + params.toString();
    return fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error("http " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (!data || !data.success || !data.result)
          throw new Error("ckan reject");
        return {
          records: data.result.records || [],
          total: data.result.total || 0,
        };
      });
  }

  function isFiniteNum(v) {
    if (v === null || v === undefined || v === "") return false;
    var n = Number(v);
    return isFinite(n);
  }

  function looksWgs84(lat, lng) {
    // Israel: ~29.5–33.5 lat, ~34.2–35.9 lng. Generous bounding box.
    return (
      lat > -90 &&
      lat < 90 &&
      lng > -180 &&
      lng < 180 &&
      Math.abs(lat) < 90 &&
      Math.abs(lng) < 200 &&
      !(lat > 100000 || lng > 100000)
    );
  }

  function pointFromRecord(record, latField, lngField, projection) {
    var rawLat = record[latField];
    var rawLng = record[lngField];
    if (!isFiniteNum(rawLat) || !isFiniteNum(rawLng)) return null;
    var a = Number(rawLat);
    var b = Number(rawLng);
    if (projection === "itm") {
      // Convention: latField holds northing (Y), lngField holds easting (X).
      // ITM eastings are roughly 100k–280k, northings 380k–780k. Sanity-check.
      if (a < 100000 || b < 100000) return null;
      var converted = itmToWgs84(b, a);
      if (!isFinite(converted[0]) || !isFinite(converted[1])) return null;
      return converted;
    }
    if (!looksWgs84(a, b)) return null;
    return [a, b];
  }

  function makePopup(record, popupFields, titleField) {
    var div = document.createElement("div");
    div.className = "gov-map-popup";
    if (titleField && record[titleField] != null && record[titleField] !== "") {
      var h = document.createElement("p");
      h.className = "gov-map-popup-title";
      h.textContent = String(record[titleField]);
      div.appendChild(h);
    }
    var dl = document.createElement("dl");
    dl.style.margin = "0";
    var rendered = 0;
    for (var i = 0; i < popupFields.length; i++) {
      var spec = popupFields[i];
      var field = typeof spec === "string" ? spec : spec.field;
      if (titleField && field === titleField) continue;
      var label = typeof spec === "string" ? field : spec.label || field;
      var value = record[field];
      if (value === null || value === undefined || value === "") continue;
      var row = document.createElement("div");
      row.className = "gov-map-popup-row";
      var dt = document.createElement("dt");
      dt.textContent = String(label);
      var dd = document.createElement("dd");
      dd.textContent = String(value);
      row.appendChild(dt);
      row.appendChild(dd);
      dl.appendChild(row);
      rendered++;
    }
    if (rendered) div.appendChild(dl);
    return div;
  }

  function create(config) {
    if (!config) {
      console.warn("[GovMap] missing config");
      return;
    }
    var container = resolveEl(config.container);
    if (!container) {
      console.warn("[GovMap] container not found", config.container);
      return;
    }
    if (!config.resourceId) {
      console.warn("[GovMap] resourceId is required");
      return;
    }
    if (!config.latField || !config.lngField) {
      console.warn("[GovMap] latField + lngField required");
      return;
    }
    if (typeof window === "undefined" || !window.L) {
      console.warn("[GovMap] Leaflet not loaded — aborting");
      return;
    }

    var L = window.L;
    var projection = config.projection === "itm" ? "itm" : "wgs84";
    var latField = String(config.latField);
    var lngField = String(config.lngField);
    var popupFields = Array.isArray(config.popupFields)
      ? config.popupFields.slice()
      : [];
    var popupTitleField = config.popupTitleField || null;
    var cluster = config.cluster !== false;
    var fitBounds = config.fitBounds !== false;
    // Default cap is effectively min(record_count, 50000): the fetch loop
    // below stops at res.total, so a 50000 default fetches the entire point
    // set for all but the 3 gov.il layers that exceed 50k (roads 128k,
    // מפל"ס 160k, trees 60k). Those get the first 50k + an honest "showing
    // X of Y" note. Override with config.totalCap when a page needs more.
    var totalCap = Math.max(50, Number(config.totalCap) || 50000);
    var pageSize = Math.max(
      100,
      Math.min(totalCap, Number(config.pageSize) || 1000)
    );
    var initialView = config.initialView || { center: [31.5, 35.0], zoom: 7 };
    var tileUrl =
      config.tileUrl || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
    var tileAttribution =
      config.tileAttribution ||
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
    var maxZoom = Number(config.maxZoom) || 18;
    var fields =
      config.fields && config.fields.length ? config.fields.slice() : null;
    if (fields) {
      // Always include the geometry + popup-bound columns so we can render.
      function ensureField(f) {
        if (f && fields.indexOf(f) === -1) fields.push(f);
      }
      ensureField(latField);
      ensureField(lngField);
      if (popupTitleField) ensureField(popupTitleField);
      for (var pi = 0; pi < popupFields.length; pi++) {
        var pf = popupFields[pi];
        ensureField(typeof pf === "string" ? pf : pf.field);
      }
    }

    ensureStyles();

    while (container.firstChild) container.removeChild(container.firstChild);
    container.classList.add("gov-map-wrap");

    var skel = document.createElement("div");
    skel.className = "gov-map-skel";
    skel.textContent = "טוען מפה...";
    container.appendChild(skel);

    var map = L.map(container, {
      center: initialView.center,
      zoom: initialView.zoom,
      preferCanvas: true,
    });
    L.tileLayer(tileUrl, {
      attribution: tileAttribution,
      maxZoom: maxZoom,
    }).addTo(map);

    function showState(kind, message) {
      var existing = container.querySelector(".gov-map-state");
      if (existing) existing.parentNode.removeChild(existing);
      var box = document.createElement("div");
      box.className = "gov-map-state";
      box.setAttribute("data-kind", kind);
      box.textContent = message;
      container.appendChild(box);
    }

    function clearSkeleton() {
      if (skel && skel.parentNode) skel.parentNode.removeChild(skel);
    }

    var layer =
      cluster && typeof L.markerClusterGroup === "function"
        ? L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 60 })
        : L.layerGroup();
    layer.addTo(map);

    var loaded = 0;
    var rendered = 0;
    var datasetTotal = 0;
    var bounds = L.latLngBounds([]);

    function showCapNote(shown, total) {
      var note = document.createElement("div");
      note.className = "gov-map-note";
      note.textContent =
        "מוצגות " +
        shown.toLocaleString("he-IL") +
        " מתוך " +
        total.toLocaleString("he-IL") +
        " נקודות";
      container.appendChild(note);
    }

    function ingestBatch(records) {
      var batchMarkers = [];
      for (var i = 0; i < records.length; i++) {
        var r = records[i];
        var pt = pointFromRecord(r, latField, lngField, projection);
        if (!pt) continue;
        var marker = L.circleMarker(pt, {
          radius: 5,
          color: "#0068f5",
          weight: 1,
          fillColor: "#0068f5",
          fillOpacity: 0.65,
        });
        if (popupFields.length || popupTitleField) {
          var popup = makePopup(r, popupFields, popupTitleField);
          marker.bindPopup(popup, { closeButton: true, maxWidth: 280 });
        }
        batchMarkers.push(marker);
        bounds.extend(pt);
      }
      if (batchMarkers.length) {
        if (typeof layer.addLayers === "function")
          layer.addLayers(batchMarkers);
        else
          for (var j = 0; j < batchMarkers.length; j++)
            batchMarkers[j].addTo(layer);
      }
      rendered += batchMarkers.length;
    }

    function loadAll() {
      var offset = 0;
      function step() {
        var batchLimit = Math.min(pageSize, totalCap - loaded);
        if (batchLimit <= 0) return finish();
        return fetchPage({
          resourceId: config.resourceId,
          fields: fields,
          filters: config.filters,
          q: config.q,
          limit: batchLimit,
          offset: offset,
        }).then(function (res) {
          ingestBatch(res.records);
          loaded += res.records.length;
          offset += res.records.length;
          if (res.total && !datasetTotal) datasetTotal = res.total;
          var done =
            res.records.length < batchLimit ||
            loaded >= totalCap ||
            (res.total && offset >= res.total);
          if (done) return finish();
          return step();
        });
      }
      function finish() {
        clearSkeleton();
        if (rendered === 0) {
          showState("empty", "לא נמצאו רשומות עם קואורדינטות תקינות.");
          return;
        }
        if (fitBounds && bounds.isValid()) {
          map.fitBounds(bounds, { padding: [24, 24], maxZoom: 16 });
        }
        // Capped: fetched fewer rows than the dataset holds — disclose it.
        if (datasetTotal && loaded < datasetTotal) {
          showCapNote(rendered, datasetTotal);
        }
      }
      return step();
    }

    loadAll().catch(function (err) {
      console.warn("[GovMap] fetch failed", err);
      clearSkeleton();
      if (rendered === 0) {
        showState("error", "לא ניתן לטעון את המפה כעת. ננסה שוב מאוחר יותר.");
      }
    });

    // Bridge container resize → map resize (orientation, sidebar reflow).
    var ro;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(function () {
        map.invalidateSize();
      });
      ro.observe(container);
    }

    return {
      map: map,
      layer: layer,
      destroy: function () {
        if (ro) ro.disconnect();
        map.remove();
      },
    };
  }

  window.GovMap = { create: create };
})();
