"""Map file → WGS84 GeoJSON, for `map` inputs and `author snapshot`.

The refresh downloads a `map` input's uploaded file (see recipe.py) and
converts it here on every run; `author snapshot` does the same once, for a
file a browser downloaded, and commits the result for a `snapshot` input:

  - reads GeoJSON, KML, KMZ, or a zipped ESRI shapefile (.shp + .dbf, with
    .prj/.cpg when present). Pure Python: the builder image has no geo
    libraries. A downloaded file is untrusted: no DTDs, a cap on what a zip
    may inflate to, every geometry checked before it is walked, and
    `load_map` turns any malformed input into a SnapshotError;
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
from array import array
from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DECIMALS = 5
DEFAULT_MAX_BYTES = 150_000
# A downloaded zip is untrusted: refuse to inflate more than this.
MAX_UNZIPPED_BYTES = 200_000_000
_TOLERANCES = (0.0, 1e-5, 2e-5, 5e-5, 1e-4, 2e-4, 5e-4, 1e-3)


class SnapshotError(ValueError):
    pass


class SnapshotTooLarge(SnapshotError):
    """The geometry doesn't fit the size target even fully simplified."""


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


def _positions(geom: dict | None):
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
        if not isinstance(c, list) or not c:
            continue  # only lists nest; a string here would recurse forever
        if isinstance(c[0], (int, float)):
            yield c
        else:
            stack.extend(c)


# Geometry collections nest at most this deep; real files use one or two levels.
MAX_COLLECTION_DEPTH = 16


def _too_nested() -> SnapshotError:
    return SnapshotError(f"geometry collections nested more than {MAX_COLLECTION_DEPTH} deep")


def _map_lines(geom: dict, fn, depth: int = 0) -> dict:
    """Apply `fn(list_of_positions, is_ring)` to every line/ring."""
    t, c = geom["type"], geom.get("coordinates")
    if t == "GeometryCollection":
        if depth >= MAX_COLLECTION_DEPTH:
            raise _too_nested()
        return {**geom, "geometries": [_map_lines(g, fn, depth + 1) for g in geom["geometries"]]}
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


class _Line:
    """One line or ring as `_clean` sees it before simplifying (projected,
    rounded, de-duplicated), held compactly for a big layer: coordinates in
    two arrays (lists when a GeoJSON gave integers, which stay integers in
    the output), each point's JSON length, and, once `_rank` has run, each
    point's level: how many steps of `_TOLERANCES` keep it."""
    __slots__ = ("closed", "lens", "lvl", "ring", "xs", "ys")

    def __init__(self, xs: list, ys: list, ring: bool):
        floats = all(type(v) is float for v in xs) and all(type(v) is float for v in ys)
        self.xs = array("d", xs) if floats else xs
        self.ys = array("d", ys) if floats else ys
        try:
            self.lens = array("B", [len(repr(x)) + len(repr(y)) + 3 for x, y in zip(xs, ys)])
        except OverflowError:  # over 255 chars: a huge integer, not a real position
            raise SnapshotError(f"a position too long to be a coordinate ({str(xs[0])[:20]}…)") from None
        self.lvl: array | None = None
        self.ring = ring
        self.closed = xs[0] == xs[-1] and ys[0] == ys[-1]

    def nbytes(self, step: int) -> int:
        """Bytes of the line's JSON list at `_TOLERANCES[step]`."""
        n, total = len(self.lens), sum(self.lens)
        k, size = n, total
        if step:
            k = size = 0
            for ln, lv in zip(self.lens, self.lvl):
                if lv >= step:
                    k += 1
                    size += ln
        if self.ring:
            if not self.closed:
                k, size = k + 1, size + self.lens[0]
            if k < 4:  # simplified away: `_clean` keeps the ring's own shape
                k = n + (not self.closed)
                size = total + (0 if self.closed else self.lens[0])
        return 2 + size + k - 1

    def points(self, step: int) -> list:
        """The line exactly as `_clean` returns it at `_TOLERANCES[step]`."""
        pts = zip(self.xs, self.ys)
        if step:
            out = [[x, y] for (x, y), lv in zip(pts, self.lvl) if lv >= step]
        else:
            out = [[x, y] for x, y in pts]
        if self.ring:
            if out[0] != out[-1]:
                out.append(out[0])
            if len(out) < 4:  # simplified away: the ring's own shape, closed
                out = [[x, y] for x, y in zip(self.xs, self.ys)]
                if out[0] != out[-1]:
                    out.append(out[0])
        return out


_POSITIVE = _TOLERANCES[1:]
_TOP = len(_TOLERANCES) - 1


def _rank(line: _Line) -> None:
    """Set `line.lvl` so that `simplify(points, _TOLERANCES[s])` keeps point
    i iff lvl[i] >= s (s >= 1). Douglas-Peucker splits a line at the same
    points whatever the tolerance, and a split survives tolerance t only
    while it and every split above it are farther than t, so one pass ranks
    every point for every step. The split search and the distance arithmetic
    are `simplify`'s and `_perp`'s, operation for operation, so the kept
    points are the same bit for bit."""
    xs, ys = line.xs, line.ys
    n = len(xs)
    lvl = array("B", bytes(n))
    lvl[0] = lvl[-1] = _TOP
    floor = _POSITIVE[0]
    hypot = math.hypot
    stack = [(0, n - 1, _TOP)]
    while stack:
        i, j, cap = stack.pop()
        x1, y1, x2, y2 = xs[i], ys[i], xs[j], ys[j]
        dx, dy = x2 - x1, y2 - y1
        best, idx = 0.0, None
        if dx == 0 and dy == 0:
            for k in range(i + 1, j):
                d = hypot(xs[k] - x1, ys[k] - y1)
                if d > best:
                    best, idx = d, k
        else:
            a, b, h = x2 * y1, y2 * x1, hypot(dx, dy)
            for k in range(i + 1, j):
                d = abs(dy * xs[k] - dx * ys[k] + a - b) / h
                if d > best:
                    best, idx = d, k
        if idx is not None and best > floor:
            lv = min(cap, bisect_left(_POSITIVE, best))
            lvl[idx] = lv
            stack += [(i, idx, lv), (idx, j, lv)]
    line.lvl = lvl


def _prepare_line(points: list, is_ring: bool, project) -> list | _Line:
    """`_clean` up to the simplification: a plain list when no tolerance can
    change it (under 3 points), else a `_Line`."""
    xs: list = []
    ys: list = []
    for p in points:
        x, y = project(p[0], p[1])
        x, y = round(x, DECIMALS), round(y, DECIMALS)
        if xs and x == xs[-1] and y == ys[-1]:
            continue
        xs.append(x)
        ys.append(y)
    if not xs:
        raise SnapshotError("a line or ring with no points")
    if len(xs) >= 3:
        return _Line(xs, ys, is_ring)
    out = [[x, y] for x, y in zip(xs, ys)]
    if is_ring and out[0] != out[-1]:
        out.append(out[0])
    return out


def _fill(o: Any, fn) -> Any:
    """A geometry template with each `_Line` replaced by `fn(line)`."""
    if type(o) is _Line:
        return fn(o)
    if type(o) is dict:
        return {k: _fill(v, fn) for k, v in o.items()}
    if type(o) is list:
        return [_fill(v, fn) for v in o]
    return o


def _lines(o: Any) -> Iterator[_Line]:
    if type(o) is _Line:
        yield o
    elif type(o) is dict:
        for v in o.values():
            yield from _lines(v)
    elif type(o) is list:
        for v in o:
            yield from _lines(v)


def _dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass
class Simplified:
    """A converted layer: what `build_snapshot` writes, before serializing.
    `features` holds (properties, geometry JSON) per feature, in snapshot
    order, each as a parse of the snapshot body gives it back: properties
    with sorted keys, geometry "null" when there is none."""
    features: list[tuple[dict, str]]
    tol: float
    nbytes: int  # len(build_snapshot(...)[0])


def simplify_features(features: Iterable[dict], *, crs: str,
                      max_bytes: int = DEFAULT_MAX_BYTES) -> Simplified:
    """The snapshot `build_snapshot` writes, unserialized: WGS84, rounded,
    lines and rings simplified (Douglas-Peucker) at the smallest step of
    `_TOLERANCES` whose output fits `max_bytes`, features sorted.

    Peak memory stays near the converted size. `features` is read once (give
    it `iter_map`'s stream and the raw features never all exist), each line
    is held as arrays, and the step is picked from exact byte counts (one
    ranking pass, `_rank`) instead of serializing the layer once per step."""
    project = itm_to_wgs if crs == "itm" else (lambda x, y: (x, y))
    recs: list = []  # (properties, geometry template)
    lines: list[_Line] = []
    size0 = len('{"features":[],"type":"FeatureCollection"}\n')
    for f in features:
        pj = _dumps(f.get("properties") or {})
        props = json.loads(pj)  # as a parse of the body gives them back; pj is their text
        geom = f.get("geometry")
        if geom:
            try:
                geom = _map_lines(geom, lambda pts, ring: _prepare_line(pts, ring, project))
            except SnapshotError:
                raise
            except (KeyError, TypeError, ValueError, IndexError) as e:  # a geometry no check stopped
                raise SnapshotError(f"malformed geometry ({type(e).__name__}: {e})") from None
        own = list(_lines(geom))
        lines += own
        skeleton = f'{{"geometry":{_dumps(_fill(geom, lambda _: []))},"properties":{pj},"type":"Feature"}}'
        size0 += len(skeleton.encode("utf-8")) + sum(ln.nbytes(0) - 2 for ln in own)
        recs.append((props, geom))
    size0 += max(len(recs) - 1, 0)  # the commas between features
    step, size = 0, size0
    if size > max_bytes:
        for ln in lines:
            _rank(ln)
        base = sum(ln.nbytes(0) for ln in lines)
        for step in range(1, len(_TOLERANCES)):
            size = size0 - base + sum(ln.nbytes(step) for ln in lines)
            if size <= max_bytes:
                break
        else:
            raise SnapshotTooLarge(
                f"{size:,} bytes even at tolerance {_TOLERANCES[-1]}° (> {max_bytes:,}); "
                "raise --max-kb or aggregate the features"
            )
    out = []
    for i, (props, geom) in enumerate(recs):
        recs[i] = None  # free each feature's arrays once it is written
        g = _fill(geom, lambda ln: ln.points(step))
        key = json.dumps({"type": "Feature", "properties": props, "geometry": g},
                         ensure_ascii=False, sort_keys=True)
        out.append((key, props, _dumps(g)))
    out.sort(key=lambda r: r[0])
    return Simplified([(p, g) for _, p, g in out], _TOLERANCES[step], size)


def build_snapshot(features: Iterable[dict], *, crs: str,
                   max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[bytes, float]:
    """The committed snapshot bytes, and the simplification tolerance used
    (see `simplify_features`)."""
    s = simplify_features(features, crs=crs, max_bytes=max_bytes)
    body = ",".join(f'{{"geometry":{g},"properties":{_dumps(p)},"type":"Feature"}}'
                    for p, g in s.features)
    return f'{{"features":[{body}],"type":"FeatureCollection"}}\n'.encode(), s.tol


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


def _kml_geometry(el, depth: int = 0) -> dict | None:
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
        if depth >= MAX_COLLECTION_DEPTH:
            raise _too_nested()
        parts = [g for g in (_kml_geometry(c, depth + 1) for c in el) if g]
        return {"type": "GeometryCollection", "geometries": parts}
    return None


class _NoDoctype(ET.TreeBuilder):
    """A tree builder that refuses a DOCTYPE as the parser meets it, whatever
    the file's encoding (the byte check below only sees ASCII spellings)."""

    def doctype(self, name, pubid, system):
        raise SnapshotError("KML with a DOCTYPE/ENTITY declaration; refusing to parse")


def _read_kml(data: bytes) -> list[dict]:
    # A downloaded file is untrusted: KML never needs a DTD, and refusing one
    # rules out entity-expansion tricks without a defusedxml dependency.
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise SnapshotError("KML with a DOCTYPE/ENTITY declaration; refusing to parse")
    parser = ET.XMLParser(target=_NoDoctype())
    parser.feed(data)
    root = parser.close()
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


def _shp_geometry(rec: bytes) -> dict | None:
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
    # The header's count is untrusted: never iterate past the bytes present.
    nrec = min(nrec, max(0, len(data) - hlen) // max(rlen, 1))
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


def _iter_shp(shp: io.BufferedIOBase, dbf: bytes | None, cpg: str) -> Iterator[dict]:
    """A shapefile's features, record by record from the .shp stream."""
    props = _read_dbf(dbf, _cpg_encoding(cpg)) if dbf else None
    shp.read(100)  # the file header
    n = 0
    while len(head := shp.read(8)) == 8:
        (length,) = struct.unpack(">i", head[4:8])
        if length < 0:
            raise SnapshotError(f".shp record {n + 1} has a negative length")
        geom = _shp_geometry(shp.read(2 * length))
        n += 1
        if props is None:
            yield {"type": "Feature", "properties": {}, "geometry": geom}
        elif n <= len(props) and props[n - 1] is not None:  # None: deleted in the .dbf
            yield {"type": "Feature", "properties": props[n - 1], "geometry": geom}
    if props is not None and len(props) != n:
        raise SnapshotError(f".shp has {n} shapes but .dbf {len(props)} records")


def read_map_file(path: Path) -> tuple[list[dict], str]:
    """(features, prj text) from a GeoJSON / KML / KMZ / zipped shapefile."""
    path = Path(path)
    return read_map_bytes(path.read_bytes(), path.name)


_DEPTH = {"Point": 0, "MultiPoint": 1, "LineString": 1,
          "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}


def _check_coords(c: Any, depth: int) -> None:
    if depth == 0:
        if (not isinstance(c, list) or len(c) < 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           and math.isfinite(v) for v in c[:2])):
            raise SnapshotError(f"bad position {str(c)[:40]}")
        return
    if not isinstance(c, list):
        raise SnapshotError(f"bad coordinates {str(c)[:40]}")
    for x in c:
        _check_coords(x, depth - 1)


def _check_geometry(geom: Any, depth: int = 0) -> None:
    """The shape `build_snapshot` and `detect_crs` rely on: a known type with
    numeric positions nested to that type's depth (or no geometry)."""
    if geom is None:
        return
    if not isinstance(geom, dict):
        raise SnapshotError("a geometry that is not an object")
    t = geom.get("type")
    if t == "GeometryCollection":
        parts = geom.get("geometries")
        if not isinstance(parts, list):
            raise SnapshotError(f"bad geometries {str(parts)[:40]}")
        if depth >= MAX_COLLECTION_DEPTH:
            raise _too_nested()
        for g in parts:
            if not isinstance(g, dict):
                raise SnapshotError("a collection member that is not an object")
            _check_geometry(g, depth + 1)
        return
    if t not in _DEPTH:
        raise SnapshotError(f"unsupported geometry type {t!r}")
    _check_coords(geom.get("coordinates"), _DEPTH[t])


def _malformed(name: str, e: Exception) -> SnapshotError:
    return SnapshotError(f"{name}: malformed map file ({type(e).__name__}: {e})")


def _checked(feats: Iterator, name: str) -> Iterator[dict]:
    """Each feature checked before it's handed on; any reader failure while
    streaming is a SnapshotError."""
    try:
        for f in feats:
            if not isinstance(f, dict):
                raise SnapshotError("a feature that is not an object")
            _check_geometry(f.get("geometry"))
            yield f
    except (SnapshotError, MemoryError):
        raise
    except Exception as e:  # untrusted bytes: every reader failure is the data's  # noqa: BLE001
        raise _malformed(name, e) from None


def iter_map(src: bytes | Path, name: str) -> tuple[Iterator[dict], str]:
    """(features, crs) from a downloaded file (its bytes, or its path), for
    `map` inputs, the features as a one-pass stream (see `read_map_stream`).
    The file is untrusted: every geometry is checked before anything walks
    it, and any failure of any reader, now or while iterating, is a
    SnapshotError, never a struct/zip/XML/zlib exception from deep inside one."""
    try:
        raw, prj = read_map_stream(src, name)
    except (SnapshotError, MemoryError):
        raise
    except Exception as e:  # noqa: BLE001
        raise _malformed(name, e) from None
    feats = _checked(raw, name)
    if prj:
        return feats, detect_crs([], prj)
    head = []  # up to the first feature with a position: the CRS is read off it
    for f in feats:
        head.append(f)
        if next(_positions(f.get("geometry")), None) is not None:
            break
    return itertools.chain(head, feats), detect_crs(head, "")


def load_map(data: bytes, name: str) -> tuple[list[dict], str]:
    """(features, crs) from a downloaded file's bytes (see `iter_map`)."""
    feats, crs = iter_map(data, name)
    return list(feats), crs


def summary(feats: list[dict]) -> dict:
    """What an author needs to know about a map file: size, geometry types,
    property names (capped: they are publisher-written text)."""
    types = sorted(Counter((f.get("geometry") or {}).get("type") or "none" for f in feats).items())
    cols = list(dict.fromkeys(k for f in feats for k in (f.get("properties") or {})))
    return {"features": len(feats), "geometry_types": dict(types),
            "columns": [str(c)[:60] for c in cols[:40]]}


def _sniff(src: bytes | Path, name: str) -> str:
    """'.geojson' / '.kml' / '.zip' from the name, else from the bytes (a
    downloaded file's name comes from its URL and can be anything)."""
    suffix = Path(name).suffix.lower()
    if suffix in (".geojson", ".json", ".kml"):
        return suffix
    if zipfile.is_zipfile(io.BytesIO(src) if isinstance(src, bytes) else src):
        return ".zip"
    if isinstance(src, bytes):
        head = src[:64]
    else:
        with open(src, "rb") as f:
            head = f.read(64)
    head = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"{"):
        return ".geojson"
    if head.startswith(b"<"):
        return ".kml"
    raise SnapshotError(f"{name}: not GeoJSON, KML, or a zip")


def _check_unzipped(z: zipfile.ZipFile, name: str) -> None:
    if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED_BYTES:
        raise SnapshotError(f"{name}: unzips to more than {MAX_UNZIPPED_BYTES:,} bytes")


def read_map_bytes(data: bytes, name: str) -> tuple[list[dict], str]:
    """(features, prj text) from a file's bytes; `name` hints the format."""
    feats, prj = read_map_stream(data, name)
    return list(feats), prj


def _drain(feats: list) -> Iterator[dict]:
    """A parsed file's features, each let go of once it's been read."""
    for i in range(len(feats)):
        f, feats[i] = feats[i], None
        yield f


def _shp_stream(z: zipfile.ZipFile, member: str, dbf: bytes | None, cpg: str) -> Iterator[dict]:
    try:
        with z.open(member) as f:
            yield from _iter_shp(f, dbf, cpg)
    finally:
        z.close()


def read_map_stream(src: bytes | Path, name: str) -> tuple[Iterator[dict], str]:
    """(features, prj text) from a file's bytes or path; `name` hints the
    format. The features are a one-pass stream: a zipped shapefile is read
    record by record straight from the zip (from disk, given a path), and a
    parsed GeoJSON or KML hands each feature over and lets go of it, so a
    consumer that converts as it goes never holds the whole raw layer."""
    suffix = _sniff(src, name)
    if suffix in (".geojson", ".json", ".kml"):
        data = src if isinstance(src, bytes) else Path(src).read_bytes()
        return _drain(_read_kml(data) if suffix == ".kml" else _read_geojson(data)), ""
    z = zipfile.ZipFile(io.BytesIO(src) if isinstance(src, bytes) else src)
    try:
        _check_unzipped(z, name)
        names = {n.lower(): n for n in z.namelist() if not n.endswith("/")}

        def one(ext: str) -> str | None:
            hits = sorted(n for n in names if n.endswith(ext))
            if len(hits) > 1:
                raise SnapshotError(f"{name}: {len(hits)} {ext} files; extract the one you want")
            return names[hits[0]] if hits else None

        if shp := one(".shp"):
            stem = shp[:-4].lower()
            get = lambda ext: z.read(names[stem + ext]) if stem + ext in names else None
            cpg = (get(".cpg") or b"").decode("ascii", errors="ignore")
            prj = (get(".prj") or b"").decode("utf-8", errors="ignore")
            return _shp_stream(z, shp, get(".dbf"), cpg), prj  # it closes the zip
        with z:
            if kml := one(".kml"):
                return _drain(_read_kml(z.read(kml))), ""
            if gj := one(".geojson") or one(".json"):
                return _drain(_read_geojson(z.read(gj))), ""
            if kmz := one(".kmz"):  # a KMZ zipped again (data.gov.il does this)
                with zipfile.ZipFile(io.BytesIO(z.read(kmz))) as inner:
                    _check_unzipped(inner, name)
                    kmls = sorted(n for n in inner.namelist() if n.lower().endswith(".kml"))
                    if not kmls:
                        raise SnapshotError(f"{name}: the KMZ holds no .kml")
                    return _drain(_read_kml(inner.read(kmls[0]))), ""
    except BaseException:
        z.close()
        raise
    raise SnapshotError(f"{name}: no .shp, .kml, .kmz or .geojson inside")
