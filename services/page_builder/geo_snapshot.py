"""Map file → committed recipe snapshot (`author snapshot`), authoring only.

data.gov.il's CDN refuses scripted downloads of uploaded files, so the
author downloads a dataset's map file once in a browser and this module
turns it into the GeoJSON a `snapshot` input reads (see recipe.py):

  - reads GeoJSON, KML, KMZ, or a zipped ESRI shapefile (.shp + .dbf, with
    .prj/.cpg when present). Pure Python: the builder image has no geo
    libraries and the refresh never needs them; it only reads GeoJSON.
  - reprojects ITM (EPSG:2039, the usual Israeli grid) to WGS84;
  - rounds to 5 decimals (~1 m), simplifies lines and rings
    (Douglas-Peucker) only as far as needed to fit the size target;
  - sorts features, so the same input file always gives the same bytes.
"""
from __future__ import annotations

import io
import itertools
import json
import math
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Optional

DECIMALS = 5
DEFAULT_MAX_BYTES = 150_000
_TOLERANCES = (0.0, 1e-5, 2e-5, 5e-5, 1e-4, 2e-4, 5e-4, 1e-3)


class SnapshotError(ValueError):
    pass


# ── ITM → WGS84 ──────────────────────────────────────────────────────────
# EPSG:2039, GRS80 transverse Mercator. The Israel 1993 → WGS84 datum shift
# is a few metres, below what a page map shows; skipped (as in the recipes
# that convert ITM points, e.g. recipes/d9b1e04c…/compute.py).

_A = 6378137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_K0 = 1.0000067
_LAT0 = math.radians(31.7343936111)
_LON0 = math.radians(35.2045169444)
_FE, _FN = 219529.584, 626907.390


def _meridian(phi: float) -> float:
    e2 = _E2
    return _A * (
        (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
        - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
        + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
        - (35 * e2 ** 3 / 3072) * math.sin(6 * phi)
    )


def itm_to_wgs(x: float, y: float) -> tuple[float, float]:
    """ITM metres → (lon, lat) degrees, GeoJSON order."""
    m = _meridian(_LAT0) + (y - _FN) / _K0
    mu = m / (_A * (1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
        + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
        + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
        + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    )
    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    c1 = _EP2 * c * c
    t1 = t * t
    n1 = _A / math.sqrt(1 - _E2 * s * s)
    r1 = _A * (1 - _E2) / (1 - _E2 * s * s) ** 1.5
    d = (x - _FE) / (n1 * _K0)
    lat = phi1 - (n1 * t / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * _EP2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * _EP2 - 3 * c1 * c1) * d ** 6 / 720
    )
    lon = _LON0 + (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * _EP2 + 24 * t1 * t1) * d ** 5 / 120
    ) / c
    return math.degrees(lon), math.degrees(lat)


# ── geometry walking ─────────────────────────────────────────────────────


def _positions(geom: Optional[dict]):
    """Every [x, y, …] position in a geometry."""
    if not geom:
        return
    if geom["type"] == "GeometryCollection":
        for g in geom.get("geometries") or []:
            yield from _positions(g)
        return
    stack = [geom.get("coordinates")]
    while stack:
        c = stack.pop()
        if c and isinstance(c[0], (int, float)):
            yield c
        elif c:
            stack.extend(c)


def _map_lines(geom: dict, fn) -> dict:
    """Apply `fn(list_of_positions, is_ring)` to every line/ring."""
    t, c = geom["type"], geom.get("coordinates")
    if t == "GeometryCollection":
        return {**geom, "geometries": [_map_lines(g, fn) for g in geom["geometries"]]}
    if t == "Point":
        return {"type": t, "coordinates": fn([c], False)[0]}
    if t == "MultiPoint":
        return {"type": t, "coordinates": fn(c, False)}
    if t == "LineString":
        return {"type": t, "coordinates": fn(c, False)}
    if t == "MultiLineString":
        return {"type": t, "coordinates": [fn(l, False) for l in c]}
    if t == "Polygon":
        return {"type": t, "coordinates": [fn(r, True) for r in c]}
    if t == "MultiPolygon":
        return {"type": t, "coordinates": [[fn(r, True) for r in p] for p in c]}
    raise SnapshotError(f"unsupported geometry type {t!r}")


def detect_crs(features: list[dict], prj: str = "") -> str:
    """'wgs84' or 'itm', from the .prj when there is one, else the numbers.
    A geographic .prj (no PROJCS) is degrees whatever its datum (GCS_Israel
    included: the datum shift is metres). Only the ITM grid is projected;
    the old Israeli Cassini grid and anything else are refused."""
    p = prj.lower()
    if p:
        if "projcs" not in p:
            return "wgs84"
        if "cassini" in p or "palestine" in p or "israel_cs" in p:
            raise SnapshotError("old Israeli Cassini grid (ICS) is not supported; export as ITM or WGS84")
        if "israel_tm" in p or "israeli tm" in p or re.search(r"\bitm\b", p) or "2039" in p:
            return "itm"
        raise SnapshotError(f"unsupported projection in .prj: {prj[:80]}")
    for f in features:
        for x, y, *_ in _positions(f.get("geometry")):
            if abs(x) <= 180 and abs(y) <= 90:
                return "wgs84"
            if 100_000 <= x <= 300_000 and 350_000 <= y <= 1_400_000:
                return "itm"
            raise SnapshotError(f"unknown projection (first position {x}, {y})")
    raise SnapshotError("no coordinates in the file")


def _perp(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p[:2], a[:2], b[:2]
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / math.hypot(dx, dy)


def simplify(points: list, tol: float) -> list:
    """Douglas-Peucker, iterative (rings can have tens of thousands of points)."""
    if tol <= 0 or len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0.0, None
        for k in range(i + 1, j):
            d = _perp(points[k], points[i], points[j])
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(points, keep) if k]


def _clean(points: list, is_ring: bool, tol: float, project) -> list:
    pts = [[round(v, DECIMALS) for v in project(p[0], p[1])] for p in points]
    dedup = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    if not dedup:
        raise SnapshotError("a line or ring with no points")
    out = simplify(dedup, tol)
    if is_ring:
        if out[0] != out[-1]:
            out.append(out[0])
        if len(out) < 4:  # simplified away; keep the ring's own shape
            out = dedup if dedup[0] == dedup[-1] else [*dedup, dedup[0]]
    return out


def build_snapshot(features: list[dict], *, crs: str,
                   max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[bytes, float]:
    """The committed snapshot bytes, and the simplification tolerance used."""
    project = itm_to_wgs if crs == "itm" else (lambda x, y: (x, y))
    for tol in _TOLERANCES:
        out = []
        for f in features:
            geom = f.get("geometry")
            if geom:
                geom = _map_lines(geom, lambda pts, ring, tol=tol: _clean(pts, ring, tol, project))
            out.append({"type": "Feature", "properties": f.get("properties") or {},
                        "geometry": geom})
        out.sort(key=lambda f: json.dumps(f, ensure_ascii=False, sort_keys=True))
        data = json.dumps({"type": "FeatureCollection", "features": out},
                          ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        body = (data + "\n").encode("utf-8")
        if len(body) <= max_bytes:
            return body, tol
    raise SnapshotError(
        f"{len(body):,} bytes even at tolerance {_TOLERANCES[-1]}° (> {max_bytes:,}); "
        "raise --max-kb or aggregate the features"
    )


# ── readers ──────────────────────────────────────────────────────────────


def _read_geojson(data: bytes) -> list[dict]:
    doc = json.loads(data.decode("utf-8-sig"))
    if doc.get("type") == "FeatureCollection":
        return doc.get("features") or []
    if doc.get("type") == "Feature":
        return [doc]
    raise SnapshotError("GeoJSON is neither a FeatureCollection nor a Feature")


def _kml_coords(text: str) -> list:
    return [[float(v) for v in t.split(",")[:2]] for t in (text or "").split()]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _coords_of(el) -> list:
    c = next((c for c in el.iter() if _local(c.tag) == "coordinates"), None)
    pts = _kml_coords(c.text if c is not None else "")
    if not pts:
        raise SnapshotError(f"KML <{_local(el.tag)}> has no coordinates")
    return pts


def _kml_geometry(el) -> Optional[dict]:
    name = _local(el.tag)
    if name == "Point":
        return {"type": "Point", "coordinates": _coords_of(el)[0]}
    if name == "LineString":
        return {"type": "LineString", "coordinates": _coords_of(el)}
    if name == "Polygon":
        outer = [_coords_of(b) for b in el if _local(b.tag) == "outerBoundaryIs"]
        holes = [_coords_of(b) for b in el if _local(b.tag) == "innerBoundaryIs"]
        return {"type": "Polygon", "coordinates": [*outer, *holes]}
    if name == "MultiGeometry":
        parts = [g for g in (_kml_geometry(c) for c in el) if g]
        return {"type": "GeometryCollection", "geometries": parts}
    return None


def _read_kml(data: bytes) -> list[dict]:
    # A downloaded file is untrusted: KML never needs a DTD, and refusing one
    # rules out entity-expansion tricks without a defusedxml dependency.
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise SnapshotError("KML with a DOCTYPE/ENTITY declaration; refusing to parse")
    root = ET.fromstring(data)
    feats = []
    for pm in (e for e in root.iter() if _local(e.tag) == "Placemark"):
        props: dict[str, Any] = {}
        geom = None
        for c in pm:
            t = _local(c.tag)
            if t in ("name", "description") and (c.text or "").strip():
                props[t] = c.text.strip()
            elif t == "ExtendedData":
                for d in c.iter():
                    lt = _local(d.tag)
                    if lt == "SimpleData":
                        props[d.get("name")] = (d.text or "").strip()
                    elif lt == "Data":
                        v = next((x for x in d if _local(x.tag) == "value"), None)
                        props[d.get("name")] = (v.text or "").strip() if v is not None else ""
            else:
                geom = geom or _kml_geometry(c)
        feats.append({"type": "Feature", "properties": props, "geometry": geom})
    return feats


def _ring_area(r: list) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in itertools.pairwise(r))


def _shp_geometry(rec: bytes) -> Optional[dict]:
    (stype,) = struct.unpack("<i", rec[:4])
    if stype == 0:
        return None
    if stype not in (1, 3, 5, 8, 11, 13, 15, 18, 21, 23, 25, 28):  # 31 = MultiPatch
        raise SnapshotError(f"unsupported shapefile shape type {stype}")
    base = stype % 10
    if base == 1:  # Point / PointZ / PointM
        x, y = struct.unpack("<2d", rec[4:20])
        return {"type": "Point", "coordinates": [x, y]}
    if base == 8:  # MultiPoint
        (n,) = struct.unpack("<i", rec[36:40])
        pts = [list(struct.unpack("<2d", rec[40 + 16 * i:56 + 16 * i])) for i in range(n)]
        return {"type": "MultiPoint", "coordinates": pts}
    if base in (3, 5):  # PolyLine / Polygon (+Z/M: trailing arrays ignored)
        nparts, npts = struct.unpack("<2i", rec[36:44])
        starts = list(struct.unpack(f"<{nparts}i", rec[44:44 + 4 * nparts]))
        off = 44 + 4 * nparts
        pts = [list(struct.unpack("<2d", rec[off + 16 * i:off + 16 * i + 16])) for i in range(npts)]
        parts = [pts[s:e] for s, e in zip(starts, [*starts[1:], npts])]
        if base == 3:
            if len(parts) == 1:
                return {"type": "LineString", "coordinates": parts[0]}
            return {"type": "MultiLineString", "coordinates": parts}
        # Shapefile rings: clockwise = outer (negative shoelace), else a hole
        # of the outer ring before it.
        polys: list[list] = []
        for ring in parts:
            if _ring_area(ring) <= 0 or not polys:
                polys.append([ring])
            else:
                polys[-1].append(ring)
        if len(polys) == 1:
            return {"type": "Polygon", "coordinates": polys[0]}
        return {"type": "MultiPolygon", "coordinates": polys}
    raise SnapshotError(f"unsupported shapefile shape type {stype}")


def _dbf_value(raw: bytes, ftype: str, decimals: int, enc: str) -> Any:
    s = raw.decode(enc, errors="replace").strip().strip("\x00")
    if ftype in ("N", "F") and s:
        try:
            return int(s) if decimals == 0 and "." not in s else float(s)
        except ValueError:
            return s
    if ftype == "L":
        return {"T": True, "Y": True, "F": False, "N": False}.get(s.upper()[:1])
    return s


def _read_dbf(data: bytes, enc: str) -> list[dict]:
    nrec, hlen, rlen = struct.unpack("<IHH", data[4:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        d = data[pos:pos + 32]
        name = d[:11].split(b"\x00")[0].decode(enc, errors="replace")
        fields.append((name, chr(d[11]), d[16], d[17]))
        pos += 32
    rows = []
    for i in range(nrec):
        rec = data[hlen + i * rlen: hlen + (i + 1) * rlen]
        if rec[:1] == b"*":
            rows.append(None)  # deleted: keeps .shp/.dbf record numbers aligned
            continue
        off, row = 1, {}
        for name, ftype, length, dec in fields:
            row[name] = _dbf_value(rec[off:off + length], ftype, dec, enc)
            off += length
        rows.append(row)
    return rows


def _cpg_encoding(cpg: str) -> str:
    """The .dbf codec from a .cpg ('UTF-8', '65001', 'ANSI 1255', '1255', …).
    No .cpg: cp1255, what Hebrew ESRI exports default to."""
    import codecs

    raw = cpg.strip().lower() or "cp1255"
    digits = re.sub(r"^(ansi|windows|cp)[ _-]*", "", raw)
    name = "utf-8" if digits in ("65001", "utf8") else f"cp{digits}" if digits.isdigit() else raw
    try:
        return codecs.lookup(name).name
    except LookupError:
        raise SnapshotError(f".cpg names an unknown codepage {cpg.strip()!r}") from None


def _read_shp(shp: bytes, dbf: Optional[bytes], cpg: str) -> list[dict]:
    geoms, pos = [], 100
    while pos + 8 <= len(shp):
        (length,) = struct.unpack(">i", shp[pos + 4:pos + 8])
        geoms.append(_shp_geometry(shp[pos + 8:pos + 8 + 2 * length]))
        pos += 8 + 2 * length
    props = _read_dbf(dbf, _cpg_encoding(cpg)) if dbf else [{} for _ in geoms]
    if len(props) != len(geoms):
        raise SnapshotError(f".shp has {len(geoms)} shapes but .dbf {len(props)} records")
    return [{"type": "Feature", "properties": p, "geometry": g}
            for g, p in zip(geoms, props) if p is not None]


def read_map_file(path: Path) -> tuple[list[dict], str]:
    """(features, prj text) from a GeoJSON / KML / KMZ / zipped shapefile."""
    path = Path(path)
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix in (".geojson", ".json"):
        return _read_geojson(data), ""
    if suffix == ".kml":
        return _read_kml(data), ""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise SnapshotError(f"{path.name}: not GeoJSON, KML, or a zip")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = {n.lower(): n for n in z.namelist() if not n.endswith("/")}

        def one(ext: str) -> Optional[str]:
            hits = sorted(n for n in names if n.endswith(ext))
            if len(hits) > 1:
                raise SnapshotError(f"{path.name}: {len(hits)} {ext} files; extract the one you want")
            return names[hits[0]] if hits else None

        if shp := one(".shp"):
            stem = shp[:-4].lower()
            get = lambda ext: z.read(names[stem + ext]) if stem + ext in names else None
            cpg = (get(".cpg") or b"").decode("ascii", errors="ignore")
            prj = (get(".prj") or b"").decode("utf-8", errors="ignore")
            return _read_shp(z.read(shp), get(".dbf"), cpg), prj
        if kml := one(".kml"):
            return _read_kml(z.read(kml)), ""
        if gj := one(".geojson") or one(".json"):
            return _read_geojson(z.read(gj)), ""
        if kmz := one(".kmz"):  # a KMZ zipped again (data.gov.il does this)
            with zipfile.ZipFile(io.BytesIO(z.read(kmz))) as inner:
                kmls = sorted(n for n in inner.namelist() if n.lower().endswith(".kml"))
                if not kmls:
                    raise SnapshotError(f"{path.name}: the KMZ holds no .kml")
                return _read_kml(inner.read(kmls[0])), ""
    raise SnapshotError(f"{path.name}: no .shp, .kml, .kmz or .geojson inside")
