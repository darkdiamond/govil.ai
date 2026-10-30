"""Map snapshots: a committed GeoJSON read as a recipe input (recipe.py), the
staleness guard against its CKAN resource, the remote recipe loaders, and the
authoring converter (geo_snapshot.py + `author snapshot`)."""
from __future__ import annotations

import csv
import io
import json
import shutil
import struct
import zipfile
from pathlib import Path

import pytest

from services.page_builder import geo_snapshot as gs
from services.page_builder import refresh as rf
from services.page_builder.agent_contract import FetchOutcome
from services.page_builder.recipe import (
    GEOMETRY_COLUMN,
    Recipe,
    RecipeError,
    RecipeInput,
    RecipeManifest,
    resolve_inputs,
    snapshot_table,
)

FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
DS = "11111111-2222-3333-4444-555555555555"
RID = "aaaaaaaa-0000-0000-0000-000000000001"
GEO_RID = "cccccccc-0000-0000-0000-000000000003"

FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"שם": "קו א", "len": 12.5, "year": 2040},
     "geometry": {"type": "LineString", "coordinates": [[35.2, 31.7], [35.21, 31.71]]}},
    {"type": "Feature", "properties": {"שם": "קו ב", "len": None, "year": 2050},
     "geometry": {"type": "LineString", "coordinates": [[35.22, 31.75], [35.23, 31.76]]}},
    {"type": "Feature", "properties": {"שם": "קו ג", "len": 3, "year": 2050},
     "geometry": None},
]}


def _snap_input(**kw) -> dict:
    return {"name": "geo", "by_id": GEO_RID, "snapshot": "geo.geojson",
            "snapshot_of": {"size": 1000}, **kw}


def _with_snapshot(tmp_path: Path, snapshot_of: dict | None = None) -> Path:
    """The fixture recipe plus a `geo` snapshot input (compute ignores it)."""
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    m = json.loads((recipes / DS / "recipe.json").read_text())
    m["inputs"].append(_snap_input(snapshot_of=snapshot_of or {"size": 1000}))
    (recipes / DS / "recipe.json").write_text(json.dumps(m, ensure_ascii=False))
    (recipes / DS / "geo.geojson").write_text(json.dumps(FC, ensure_ascii=False))
    cov = json.loads((recipes / DS / "coverage.json").read_text())
    cov.update({"geo.שם": "skip: not drawn in this test", "geo.len": "skip: not drawn in this test", "geo.year": "skip: not drawn in this test",
                f"geo.{GEOMETRY_COLUMN}": "skip: not drawn in this test"})
    (recipes / DS / "coverage.json").write_text(json.dumps(cov, ensure_ascii=False))
    return recipes


# ── contract ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [
    {"snapshot_of": None},                       # snapshot without its facts
    {"snapshot": "../x.geojson"},                # not a plain file name
    {"snapshot": "Geo.GEOJSON"},
    {"columns": ["a"]},
    {"concat": True},
    {"snapshot_of": {"last_modified": "x"}},     # nothing comparable
])
def test_snapshot_input_validation(bad):
    spec = {k: v for k, v in {**_snap_input(), **bad}.items() if v is not None}
    with pytest.raises(ValueError):
        RecipeInput.model_validate(spec)


def test_snapshot_input_valid_and_listed():
    inp = RecipeInput.model_validate(_snap_input())
    assert inp.snapshot == "geo.geojson" and inp.snapshot_of.size == 1000


def test_recipe_load_requires_the_snapshot_file(tmp_path):
    recipes = _with_snapshot(tmp_path)
    assert Recipe.load(recipes / DS).files[-1] == "geo.geojson"
    (recipes / DS / "geo.geojson").unlink()
    with pytest.raises(RecipeError, match="missing snapshot"):
        Recipe.load(recipes / DS)


def test_recipe_identity_covers_the_snapshot(tmp_path):
    recipes = _with_snapshot(tmp_path)
    before = rf.recipe_identity(Recipe.load(recipes / DS))
    (recipes / DS / "geo.geojson").write_text(json.dumps({**FC, "features": FC["features"][:1]}))
    assert rf.recipe_identity(Recipe.load(recipes / DS)) != before


# ── snapshot → table ─────────────────────────────────────────────────────


def test_snapshot_table_rows(tmp_path):
    p = tmp_path / "g.geojson"
    p.write_text(json.dumps(FC, ensure_ascii=False))
    header, rows = snapshot_table(p)
    assert header == ["שם", "len", "year", GEOMETRY_COLUMN]
    assert rows[0][:3] == ["קו א", "12.5", "2040"]
    assert rows[1][1] == "" and rows[2][3] == ""          # null property, null geometry
    assert json.loads(rows[0][3])["type"] == "LineString"
    assert snapshot_table(p) == (header, rows)


def test_snapshot_table_rejects_garbage(tmp_path):
    p = tmp_path / "g.geojson"
    p.write_text('{"type": "Feature"}')
    with pytest.raises(RecipeError, match="FeatureCollection"):
        snapshot_table(p)


# ── staleness guard ──────────────────────────────────────────────────────


def _manifest(snapshot_of: dict) -> RecipeManifest:
    return RecipeManifest.model_validate({
        "dataset_id": DS, "recipe_version": 1, "authored_at": "2026-10-30T00:00:00Z",
        "inputs": [_snap_input(snapshot_of=snapshot_of)],
    })


@pytest.mark.parametrize("snap, res, stale", [
    ({"size": 1000}, {"size": 1000}, False),
    ({"size": 1000}, {"size": 1001}, True),
    ({"size": 1000, "hash": "aa"}, {"size": 5, "hash": "aa"}, False),   # hash wins over size
    ({"size": 1000, "hash": "aa"}, {"size": 1000, "hash": "bb"}, True),
    ({"size": 1000, "hash": "aa"}, {"size": 1000, "hash": ""}, False),  # CKAN lost the hash: size
    ({"size": 1000}, {}, False),                                        # nothing to compare: logged
    ({"size": 1000}, None, True),                                       # resource gone
])
def test_snapshot_staleness(snap, res, stale):
    resources = [] if res is None else [{"id": GEO_RID, "datastore_active": False, **res}]

    def no_preview(rid):
        raise AssertionError("a snapshot input never previews the datastore")

    if stale:
        with pytest.raises(RecipeError) as e:
            resolve_inputs(_manifest(snap), resources, no_preview)
        assert e.value.reason == "geometry_stale"
    else:
        assert resolve_inputs(_manifest(snap), resources, no_preview)["geo"][0]["id"] == GEO_RID


def test_geometry_stale_opens_an_issue():
    from services.page_builder.notify import REASON_TEXT

    assert "geometry_stale" in rf.AUTHORING_REASONS and "geometry_stale" in REASON_TEXT


# ── refresh fetch + fingerprints ─────────────────────────────────────────


def test_fetch_inputs_writes_snapshot_without_ckan(tmp_path):
    recipes = _with_snapshot(tmp_path)
    recipe = Recipe.load(recipes / DS)
    rows = [["2025", "1", "צפון", "4"]]
    resources = [{"id": RID, "name": "events", "datastore_active": True},
                 {"id": GEO_RID, "name": "map", "datastore_active": False, "size": 1000}]
    cols = ["שנה", "חודש", "מחוז", "מספר אירועים"]

    def preview(rid):
        assert rid == RID, "snapshot resource must not be previewed"
        return {"fields": [{"id": c} for c in cols], "total": 1, "sample_rows": []}

    def fetch(rid, total, dest, **kw):
        assert rid == RID
        with open(dest, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([cols, *rows])
        return FetchOutcome(rows=1, bytes=dest.stat().st_size, mode="full")

    out = rf.fetch_inputs(recipe, resources, tmp_path / "d", preview_fn=preview, fetch_fn=fetch,
                          snapshot_rows=lambda r: r[:2])
    geo = out["geo"][0]
    assert geo.rows == 2 and geo.resource_id == GEO_RID
    with open(geo.file, encoding="utf-8") as f:
        assert next(csv.reader(f))[-1] == GEOMETRY_COLUMN

    probe = rf.probe_inputs(recipe, resources, preview)
    ident = rf.recipe_identity(recipe)
    assert rf.input_fingerprint(recipe, probe, ident)
    # The events resource has no CKAN hash → A′ None; the snapshot never forces None.
    assert rf.file_fingerprint(recipe, probe, ident) is None
    resources[0]["hash"] = "md5"
    assert rf.file_fingerprint(recipe, probe, ident) is not None


def test_github_repo_fetches_snapshot_files(tmp_path, monkeypatch):
    recipes = _with_snapshot(tmp_path)
    repo = rf.GithubRecipeRepo("o/r")
    repo._sha = "abc"
    fetched = []

    def get(url, **kw):
        name = url.rsplit("/", 1)[-1]
        fetched.append(name)
        return type("R", (), {"content": (recipes / DS / name).read_bytes()})()

    monkeypatch.setattr(repo, "_get", get)
    recipe = repo.load(DS, tmp_path / "scratch")
    assert fetched[-1] == "geo.geojson" and (recipe.root / "geo.geojson").is_file()


# ── author verify with a snapshot input ──────────────────────────────────


def _rows(n_years=3):
    return [[str(y), str(m), d, str(10 + m)] for y in range(2023, 2023 + n_years)
            for m in range(1, 13) for d in ("צפון", "דרום")]


def _prepared(tmp_path, monkeypatch, geo_size):
    from services.page_builder import author

    monkeypatch.setattr(author, "AUTHORING_ROOT", tmp_path / "authoring")
    monkeypatch.setattr(author, "PREVIEW_OUT_ROOT", tmp_path / "model_test")
    root = tmp_path / "authoring" / DS
    (root / "data").mkdir(parents=True)
    cols = ["שנה", "חודש", "מחוז", "מספר אירועים"]
    with open(root / "data" / "1.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([cols, *_rows()])
    (root / "data" / "manifest.json").write_text(json.dumps([{
        "resource_id": RID, "name": "events", "format": "CSV", "fields": cols,
        "field_types": {}, "total": 72, "file": "1.csv", "rows": 72,
    }]))
    (root / "source.json").write_text(json.dumps({"resources": [
        {"id": RID, "datastore_active": True},
        {"id": GEO_RID, "format": "ZIP", "datastore_active": False, "size": geo_size},
    ]}))
    return author


@pytest.mark.parametrize("geo_size, code", [(1000, 0), (2000, 1)])
def test_author_verify_runs_snapshot_inputs(tmp_path, monkeypatch, capsys, geo_size, code):
    author = _prepared(tmp_path, monkeypatch, geo_size)
    rc = author.verify(DS, _with_snapshot(tmp_path))
    out = capsys.readouterr().out
    assert rc == code, out
    if code:
        assert "geometry_stale" in out


# ── converter ────────────────────────────────────────────────────────────


def test_itm_origin_maps_to_its_geographic_origin():
    lon, lat = gs.itm_to_wgs(219529.584, 626907.390)
    assert lon == pytest.approx(35.2045169444, abs=1e-6)
    assert lat == pytest.approx(31.7343936111, abs=1e-6)


def _shp_zip(rings_itm: list[list[tuple[float, float]]], names: list[str]) -> bytes:
    """A minimal polygon shapefile (+ cp1255 .dbf, .prj), one ring per record."""
    recs = b""
    for i, ring in enumerate(rings_itm, 1):
        pts = b"".join(struct.pack("<2d", x, y) for x, y in ring)
        body = struct.pack("<i4d2ii", 5, 0, 0, 0, 0, 1, len(ring), 0) + pts
        recs += struct.pack(">2i", i, len(body) // 2) + body
    shp = struct.pack(">i", 9994) + b"\0" * 20 + struct.pack(">i", (100 + len(recs)) // 2) \
        + struct.pack("<2i", 1000, 5) + b"\0" * 64 + recs
    field = b"NAME".ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([20, 0]) + b"\0" * 14
    hlen = 32 + 32 + 1
    dbf = struct.pack("<B3BIHH", 3, 26, 10, 30, len(names), hlen, 21) + b"\0" * 20 + field + b"\r"
    for n in names:
        dbf += b" " + n.encode("cp1255").ljust(20, b" ")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("layer.shp", shp)
        z.writestr("layer.dbf", dbf)
        z.writestr("layer.prj", 'PROJCS["Israel_TM_Grid",GEOGCS["GCS_Israel"]]')
    return buf.getvalue()


def test_shapefile_zip_to_snapshot(tmp_path):
    sq = [(200000, 600000), (200000, 601000), (201000, 601000), (201000, 600000), (200000, 600000)]
    zp = tmp_path / "layer.zip"
    zp.write_bytes(_shp_zip([sq], ["באר שבע"]))
    feats, prj = gs.read_map_file(zp)
    assert gs.detect_crs(feats, prj) == "itm"
    assert feats[0]["properties"] == {"NAME": "באר שבע"}
    body, tol = gs.build_snapshot(feats, crs="itm")
    doc = json.loads(body)
    ring = doc["features"][0]["geometry"]["coordinates"][0]
    assert doc["features"][0]["geometry"]["type"] == "Polygon" and ring[0] == ring[-1]
    assert all(34 < x < 36 and 30 < y < 33 for x, y in ring)
    assert gs.build_snapshot(feats, crs="itm") == (body, tol)


def test_kml_and_nested_kmz(tmp_path):
    kml = ('<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           '<Placemark><name>קו 1</name><ExtendedData><SchemaData>'
           '<SimpleData name="TYPE">רכבת קלה</SimpleData></SchemaData></ExtendedData>'
           '<LineString><coordinates>35.2,31.7,0 35.21,31.71,0</coordinates></LineString>'
           '</Placemark></Document></kml>').encode()
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("doc.kml", kml)
    outer = tmp_path / "x_kmz.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("x.kmz", inner.getvalue())
    feats, _ = gs.read_map_file(outer)
    assert feats[0]["properties"] == {"name": "קו 1", "TYPE": "רכבת קלה"}
    assert feats[0]["geometry"]["coordinates"] == [[35.2, 31.7], [35.21, 31.71]]
    (tmp_path / "evil.kml").write_bytes(b'<!DOCTYPE x [<!ENTITY a "b">]><kml/>')
    with pytest.raises(gs.SnapshotError):
        gs.read_map_file(tmp_path / "evil.kml")


def test_simplify_shrinks_only_as_needed():
    line = [[35 + i / 1000, 31 + (i % 2) / 1e6] for i in range(2000)]  # zig-zag below 1 m
    feats = [{"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": line}}]
    full, tol0 = gs.build_snapshot(feats, crs="wgs84", max_bytes=10_000_000)
    small, tol = gs.build_snapshot(feats, crs="wgs84", max_bytes=2_000)
    assert tol0 == 0.0 and tol > 0 and len(small) < 2_000 < len(full)
    with pytest.raises(gs.SnapshotError):
        gs.build_snapshot(feats * 400, crs="wgs84", max_bytes=100)


def test_author_snapshot_cli(tmp_path, capsys):
    from services.page_builder import author

    src = tmp_path / "in.geojson"
    src.write_text(json.dumps(FC, ensure_ascii=False))
    res = {"id": GEO_RID, "package_id": DS, "size": src.stat().st_size, "hash": "",
           "last_modified": "2026-10-25T01:11:11"}
    assert author.snapshot(DS, src, GEO_RID, recipes_root=tmp_path / "recipes",
                           resource_fn=lambda rid: res) == 0
    snippet = json.loads(capsys.readouterr().out)
    assert snippet["snapshot"] == "geo.geojson" and snippet["snapshot_of"]["size"] == res["size"]
    assert "hash" not in snippet["snapshot_of"]
    RecipeInput.model_validate(snippet)
    with pytest.raises(SystemExit, match="belongs to dataset"):
        author.snapshot(DS, src, GEO_RID, recipes_root=tmp_path / "recipes",
                        resource_fn=lambda rid: {**res, "package_id": "other"})
