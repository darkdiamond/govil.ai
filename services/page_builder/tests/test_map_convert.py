"""The map conversion's memory-lean path (geo_snapshot.simplify_features +
iter_map) must give exactly what the old one gave: a refresh precheck hashes
the table compute reads, so a byte of drift re-renders every map recipe.
`_reference` is the old build_snapshot, kept here as the oracle."""
from __future__ import annotations

import csv
import io
import json
import random
import struct
import zipfile

import pytest

from services.page_builder import geo_snapshot as gs
from services.page_builder import refresh as rf
from services.page_builder.agent_contract import FileOutcome
from services.page_builder.recipe import RecipeError, RecipeInput, feature_table


def _reference(features, *, crs, max_bytes=gs.DEFAULT_MAX_BYTES):
    """The pre-2026-11 build_snapshot: re-serialize the layer per tolerance."""
    project = gs.itm_to_wgs if crs == "itm" else (lambda x, y: (x, y))
    for tol in gs._TOLERANCES:
        out = []
        for f in features:
            geom = f.get("geometry")
            if geom:
                geom = gs._map_lines(geom, lambda pts, ring, tol=tol: gs._clean(pts, ring, tol, project))
            out.append({"type": "Feature", "properties": f.get("properties") or {},
                        "geometry": geom})
        out.sort(key=lambda f: json.dumps(f, ensure_ascii=False, sort_keys=True))
        data = json.dumps({"type": "FeatureCollection", "features": out},
                          ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        body = (data + "\n").encode("utf-8")
        if len(body) <= max_bytes:
            return body, tol
    raise gs.SnapshotTooLarge(f"{len(body):,} bytes")


def _wiggle(rng, n, x0, y0, step, ring):
    pts = [[x0 + i * step + rng.uniform(-step, step) * rng.random() ** 3,
            y0 + rng.uniform(-step, step) * 5] for i in range(n)]
    if rng.random() < 0.3 and n > 2:
        pts.insert(rng.randrange(1, n), list(pts[0]))  # a repeat to de-duplicate
    if ring:
        pts.append(list(pts[0]) if rng.random() < 0.8 else pts[-1])
    return pts


def _geom(rng, kind, x0, y0, step):
    xo, yo = x0 + rng.random() * step * 500, y0 + rng.random() * step * 500
    n = rng.choice([1, 2, 3, 4, 5, 30, 400])

    def line(ring=False):
        return _wiggle(rng, n, xo, yo, step, ring)

    if kind == "Point":
        return {"type": "Point", "coordinates": [xo, yo]}
    if kind in ("MultiPoint", "LineString"):
        return {"type": kind, "coordinates": line()}
    if kind == "MultiLineString":
        return {"type": kind, "coordinates": [line(), line()]}
    if kind == "Polygon":
        return {"type": kind, "coordinates": [line(True), line(True)]}
    if kind == "MultiPolygon":
        return {"type": kind, "coordinates": [[line(True)], [line(True)]]}
    if kind == "GeometryCollection":
        return {"type": kind, "bbox": [1, 2],
                "geometries": [{"type": "LineString", "coordinates": line()},
                               {"type": "Point", "coordinates": [xo, yo]}]}
    return None


def _layer(seed: int, *, itm: bool) -> list[dict]:
    rng = random.Random(seed)
    if itm:
        x0, y0, step = 180_000.0, 600_000.0, 40.0
    else:
        x0, y0, step = 35.0, 31.5, 0.0004
    feats = []
    for _ in range(rng.randint(5, 40)):
        kind = rng.choice(["Point", "MultiPoint", "LineString", "MultiLineString",
                           "Polygon", "MultiPolygon", "GeometryCollection", None])
        geom = _geom(rng, kind, x0, y0, step)
        props = {"name": f"שם {rng.randint(0, 5)}", "n": rng.choice([1, 2.5, None, True, 1e20]),
                 "z": rng.randint(0, 3), "a": [1, {"b": "ג"}]}
        if rng.random() < 0.2:
            props = {}
        feats.append({"type": "Feature", "properties": props, "geometry": geom})
    if not itm and seed % 3 == 0:  # integer degrees stay integers
        feats.append({"type": "Feature", "properties": {"int": 1},
                      "geometry": {"type": "LineString", "coordinates": [[35, 31], [35, 32], [36, 32]]}})
    return feats


@pytest.mark.parametrize("seed", range(12))
def test_same_bytes_as_the_reference_at_every_tolerance(seed):
    itm = seed % 2 == 0
    feats = _layer(seed, itm=itm)
    crs = "itm" if itm else "wgs84"
    full, _ = _reference(feats, crs=crs, max_bytes=10**9)
    # A cap at, just under and between every size the ladder produces.
    sizes = sorted({len(_reference(feats, crs=crs, max_bytes=cap)[0])
                    for cap in (len(full), len(full) * 3 // 4, len(full) // 2, len(full) // 4,
                                len(full) // 8, len(full) // 16)
                    if _fits(feats, crs, cap)})
    for cap in [10**9, *sizes, *(s - 1 for s in sizes)]:
        try:
            want = _reference(feats, crs=crs, max_bytes=cap)
        except gs.SnapshotTooLarge:
            with pytest.raises(gs.SnapshotTooLarge):
                gs.build_snapshot(feats, crs=crs, max_bytes=cap)
            continue
        got = gs.build_snapshot(feats, crs=crs, max_bytes=cap)
        assert got == want, cap
        s = gs.simplify_features(iter(feats), crs=crs, max_bytes=cap)
        assert s.nbytes == len(want[0]) and s.tol == want[1]


def _fits(feats, crs, cap):
    try:
        _reference(feats, crs=crs, max_bytes=cap)
        return True
    except gs.SnapshotTooLarge:
        return False


def test_simplified_features_are_what_a_parse_of_the_body_gives():
    feats = _layer(4, itm=True)
    body, _ = _reference(feats, crs="itm", max_bytes=10**9)
    s = gs.simplify_features(feats, crs="itm", max_bytes=10**9)
    doc = {"type": "FeatureCollection",
           "features": [{"properties": p, "geometry": None if g == "null" else g}
                        for p, g in s.features]}
    assert feature_table(doc, "x") == feature_table(json.loads(body), "x")


def test_too_large_reports_the_coarsest_size():
    line = [[35 + i / 1000, 31 + (i % 2) / 10] for i in range(500)]
    feats = [{"properties": {}, "geometry": {"type": "LineString", "coordinates": line}}]
    with pytest.raises(gs.SnapshotTooLarge) as want:
        _reference(feats, crs="wgs84", max_bytes=100)
    with pytest.raises(gs.SnapshotTooLarge, match="even at tolerance") as got:
        gs.build_snapshot(feats, crs="wgs84", max_bytes=100)
    assert str(got.value).split(" bytes")[0] == str(want.value).split(" bytes")[0]


def _shp(records: list[bytes]) -> bytes:
    recs = b"".join(struct.pack(">2i", i, len(b) // 2) + b for i, b in enumerate(records, 1))
    return (struct.pack(">i", 9994) + b"\0" * 20 + struct.pack(">i", (100 + len(recs)) // 2)
            + struct.pack("<2i", 1000, 5) + b"\0" * 64 + recs)


def _poly(ring) -> bytes:
    pts = b"".join(struct.pack("<2d", x, y) for x, y in ring)
    return struct.pack("<i4d2ii", 5, 0, 0, 0, 0, 1, len(ring), 0) + pts


def _dbf(names: list[str]) -> bytes:
    field = b"NAME".ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([20, 0]) + b"\0" * 14
    out = struct.pack("<B3BIHH", 3, 26, 10, 30, len(names), 65, 21) + b"\0" * 20 + field + b"\r"
    return out + b"".join(b" " + n.encode("cp1255").ljust(20, b" ") for n in names)


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def _square(x, y, d=1000.0):
    return [(x, y), (x, y + d), (x + d, y + d), (x + d, y), (x, y)]


def test_iter_map_streams_a_shapefile_from_disk(tmp_path):
    rings = [_square(200_000 + i * 2000, 600_000) for i in range(5)]
    data = _zip({"l.shp": _shp([_poly(r) for r in rings]), "l.dbf": _dbf([f"גוש {i}" for i in range(5)]),
                 "l.prj": b'PROJCS["Israel_TM_Grid"]'})
    path = tmp_path / "l.zip"
    path.write_bytes(data)
    feats, crs = gs.iter_map(path, "l.zip")
    assert crs == "itm" and not isinstance(feats, list)
    assert list(feats) == gs.load_map(data, "l.zip")[0] == gs.read_map_bytes(data, "l.zip")[0]
    assert gs.build_snapshot(gs.iter_map(path, "l.zip")[0], crs="itm") == \
        _reference(gs.load_map(data, "l.zip")[0], crs="itm")


def test_iter_map_without_prj_reads_the_crs_off_the_first_position(tmp_path):
    data = _zip({"l.shp": _shp([struct.pack("<i", 0), _poly(_square(200_000, 600_000))]),
                 "l.dbf": _dbf(["empty", "x"])})
    feats, crs = gs.iter_map(data, "l.zip")
    assert crs == "itm"
    assert [f["properties"]["NAME"] for f in feats] == ["empty", "x"]  # the peeked one kept


@pytest.mark.parametrize("files, match", [
    ({"l.shp": _shp([_poly(_square(200_000, 600_000))] * 2), "l.dbf": _dbf(["a"])},
     "2 shapes but .dbf 1"),
    ({"l.shp": _shp([_poly(_square(200_000, 600_000))]), "l.dbf": _dbf(["a", "b"])},
     "1 shapes but .dbf 2"),
    ({"l.shp": _shp([]) + struct.pack(">2i", 1, -4)}, "negative length"),
    ({"l.shp": _shp([struct.pack("<i", 31) + b"\0" * 40])}, "shape type 31"),
    ({"l.shp": _shp([_poly(_square(200_000, 600_000))[:2] + b""])}, "malformed"),
])
def test_streamed_shapefile_failures_are_snapshot_errors(files, match):
    feats, _ = gs.iter_map(_zip({**files, "l.prj": b'PROJCS["Israel_TM_Grid"]'}), "l.zip")
    with pytest.raises(gs.SnapshotError, match=match):
        list(feats)


def test_geojson_stream_lets_go_of_each_raw_feature():
    raw = [{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [35, 31]}}
           for _ in range(3)]
    it = gs._drain(raw)
    next(it)
    assert raw[0] is None and raw[1] is not None


def test_fetch_map_converts_from_the_file_and_removes_it(tmp_path):
    data = _zip({"l.shp": _shp([_poly(_square(200_000 + i * 3000, 600_000)) for i in range(3)]),
                 "l.dbf": _dbf(["a", "b", "c"]), "l.prj": b'PROJCS["Israel_TM_Grid"]'})
    seen = []

    def files(url, dest, **kw):
        dest.write_bytes(data)
        seen.append(dest)
        return FileOutcome(bytes=len(data), sha256="x")

    inp = RecipeInput(name="geo", by_id="r" * 36, map=True)
    res = {"id": inp.by_id, "url": "https://data.gov.il/x/l.zip"}
    fetched, n = rf._fetch_map(inp, res, tmp_path, files, max_bytes=10**8, deadline=10**12,
                               transform=lambda r: r)
    assert n == len(data) and fetched.rows == 3 and not seen[0].exists()
    header, rows = feature_table(json.loads(_reference(gs.load_map(data, "l.zip")[0], crs="itm")[0]), "x")
    with open(fetched.file, encoding="utf-8", newline="") as f:
        assert list(csv.reader(f)) == [header, *rows]  # what the old path wrote

    bad = _zip({"l.shp": _shp([struct.pack("<i", 31) + b"\0" * 40])})

    def bad_files(url, dest, **kw):
        dest.write_bytes(bad)
        seen.append(dest)
        return FileOutcome(bytes=len(bad), sha256="x")

    with pytest.raises(RecipeError) as e:
        rf._fetch_map(inp, res, tmp_path, bad_files, max_bytes=10**8, deadline=10**12,
                      transform=lambda r: r)
    assert e.value.reason == "schema_changed" and not seen[-1].exists()


@pytest.mark.parametrize("exc", [
    rf.FetchLimitExceeded("bytes", "over the cap"),
    ValueError("not a data.gov.il URL"),
])
def test_fetch_map_removes_a_partial_download_whatever_failed(tmp_path, exc):
    seen = []

    def files(url, dest, **kw):
        dest.write_bytes(b"PK partial")
        seen.append(dest)
        raise exc

    inp = RecipeInput(name="geo", by_id="r" * 36, map=True)
    res = {"id": inp.by_id, "url": "https://data.gov.il/x/l.zip"}
    with pytest.raises(RecipeError):
        rf._fetch_map(inp, res, tmp_path, files, max_bytes=10**8, deadline=10**12,
                      transform=lambda r: r)
    assert not seen[0].exists()


def test_a_huge_integer_position_is_the_datas_error_not_a_crash():
    feats = [{"type": "Feature", "properties": {},
              "geometry": {"type": "LineString", "coordinates": [[35, 31], [10**300, 31], [35.1, 31]]}}]
    with pytest.raises(gs.SnapshotError, match="too long"):
        gs.simplify_features(feats, crs="wgs84")
