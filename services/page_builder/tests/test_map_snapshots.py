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
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from services.page_builder import geo_snapshot as gs
from services.page_builder import refresh as rf
from services.page_builder.agent_contract import (
    DownloadBlocked,
    FetchLimitExceeded,
    FetchOutcome,
    FileOutcome,
)
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


def test_gcs_repo_fetches_snapshot_files(tmp_path):
    recipes = _with_snapshot(tmp_path)

    class Blob:
        def __init__(self, name):
            self.path = recipes / name[len("recipes/"):]

        def exists(self):
            return self.path.is_file()

        def download_to_filename(self, dest):
            shutil.copyfile(self.path, dest)

    repo = rf.GcsRecipeRepo.__new__(rf.GcsRecipeRepo)
    repo._bucket = type("B", (), {"blob": lambda self, n: Blob(n)})()
    repo.prefix = "recipes/"
    assert (repo.load(DS, tmp_path / "scratch").root / "geo.geojson").is_file()
    (recipes / DS / "geo.geojson").unlink()
    with pytest.raises(RecipeError, match=r"missing geo\.geojson"):
        repo.load(DS, tmp_path / "scratch2")


# ── author verify with a snapshot input ──────────────────────────────────


def _rows(n_years=3):
    return [[str(y), str(m), d, str(10 + m)] for y in range(2023, 2023 + n_years)
            for m in range(1, 13) for d in ("צפון", "דרום")]


def _prepared(tmp_path, monkeypatch, geo_size):
    from services.page_builder import author, tags

    monkeypatch.setattr(author, "AUTHORING_ROOT", tmp_path / "authoring")
    monkeypatch.setattr(author, "PREVIEW_OUT_ROOT", tmp_path / "model_test")
    monkeypatch.setattr(author, "runtime_parity_problems", lambda: [])
    monkeypatch.setattr(tags, "PENDING_ROOT", tmp_path / "authoring")
    root = tmp_path / "authoring" / DS
    root.mkdir(parents=True)
    (root / "tags.json").write_text(
        json.dumps(["תחבורה", "תאונות דרכים", "בטיחות בדרכים"], ensure_ascii=False)
    )
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


@pytest.mark.parametrize("prj, crs", [
    ('PROJCS["Israel_TM_Grid",GEOGCS["GCS_Israel"]]', "itm"),
    ('PROJCS["Israel 1993 / Israeli TM Grid"]', "itm"),
    ('GEOGCS["GCS_Israel",DATUM["D_Israel"]]', "wgs84"),     # degrees, not ITM metres
    ('GEOGCS["GCS_WGS_1984"]', "wgs84"),
    ('PROJCS["Palestine_1923_Israel_CS_Grid"]', None),       # old Cassini grid: refused
    ('PROJCS["WGS_1984_UTM_Zone_36N"]', None),
])
def test_detect_crs_from_prj(prj, crs):
    feats = [{"geometry": {"type": "Point", "coordinates": [35.2, 31.7]}}]
    if crs is None:
        with pytest.raises(gs.SnapshotError):
            gs.detect_crs(feats, prj)
    else:
        assert gs.detect_crs(feats, prj) == crs


@pytest.mark.parametrize("cpg, enc", [
    ("", "cp1255"), ("UTF-8", "utf-8"), ("65001", "utf-8"), ("ANSI 1255", "cp1255"), ("1252", "cp1252"),
])
def test_cpg_encoding(cpg, enc):
    assert gs._cpg_encoding(cpg) == enc


def test_converter_refuses_bad_input_cleanly(tmp_path):
    with pytest.raises(gs.SnapshotError, match="unknown codepage"):
        gs._cpg_encoding("klingon")
    with pytest.raises(gs.SnapshotError, match="shape type 31"):
        gs._shp_geometry(struct.pack("<i", 31) + b"\0" * 40)
    (tmp_path / "e.kml").write_bytes(b'<kml><Placemark><Point><coordinates> </coordinates>'
                                     b'</Point></Placemark></kml>')
    with pytest.raises(gs.SnapshotError, match="no coordinates"):
        gs.read_map_file(tmp_path / "e.kml")
    empty = [{"properties": {}, "geometry": {"type": "LineString", "coordinates": []}}]
    with pytest.raises(gs.SnapshotError, match="no points"):
        gs.build_snapshot(empty, crs="wgs84")


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
    # Refused before anything is written: nothing to watch, or a bad input name.
    for kw, fn in (({}, lambda rid: {**res, "size": None}), ({"name": "geo-1"}, lambda rid: res)):
        with pytest.raises(SystemExit, match="can't snapshot"):
            author.snapshot(DS, src, GEO_RID, recipes_root=tmp_path / "other", resource_fn=fn, **kw)
    assert not (tmp_path / "other").exists()


# ── live map inputs (`map: true`) ────────────────────────────────────────

MAP_URL = f"https://e.data.gov.il/dataset/{DS}/resource/{GEO_RID}/download/layer.zip"
SQ = [(200000, 600000), (200000, 601000), (201000, 601000), (201000, 600000), (200000, 600000)]


def _map_input(**kw) -> dict:
    return {"name": "geo", "by_id": GEO_RID, "map": True, **kw}


def _with_map(tmp_path: Path, **kw) -> Path:
    """The fixture recipe plus a live `geo` map input (compute ignores it)."""
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    m = json.loads((recipes / DS / "recipe.json").read_text())
    m["inputs"].append(_map_input(**kw))
    (recipes / DS / "recipe.json").write_text(json.dumps(m, ensure_ascii=False))
    cov = json.loads((recipes / DS / "coverage.json").read_text())
    cov.update({"geo.NAME": "skip: not drawn in this test",
                f"geo.{GEOMETRY_COLUMN}": "skip: not drawn in this test"})
    (recipes / DS / "coverage.json").write_text(json.dumps(cov, ensure_ascii=False))
    return recipes


def _map_resources(**geo) -> list[dict]:
    return [{"id": RID, "name": "events", "datastore_active": True},
            {"id": GEO_RID, "name": "map", "format": "ZIP", "datastore_active": False,
             "size": 9000, "url": MAP_URL, **geo}]


class FakeFiles:
    """`fetch_file_fn`: serves `body`, or raises `error`."""

    def __init__(self, body: bytes = b"", error: Exception | None = None):
        self.body, self.error, self.urls = body, error, []

    def __call__(self, url, dest, *, max_bytes, timeout_s, deadline):
        self.urls.append(url)
        if self.error:
            raise self.error
        dest.write_bytes(self.body)
        return FileOutcome(bytes=len(self.body), sha256="x")


def _events_ckan():
    cols = ["שנה", "חודש", "מחוז", "מספר אירועים"]

    def preview(rid):
        assert rid == RID, "a map input never previews the datastore"
        return {"fields": [{"id": c} for c in cols], "total": 1, "sample_rows": []}

    def fetch(rid, total, dest, **kw):
        with open(dest, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([cols, ["2025", "1", "צפון", "4"]])
        return FetchOutcome(rows=1, bytes=dest.stat().st_size, mode="full")

    return preview, fetch


@pytest.mark.parametrize("bad", [
    {"by_id": None, "by_schema": ["a"], "concat": True},     # map needs by_id
    {"snapshot": "geo.geojson", "snapshot_of": {"size": 1}},  # two ways in
    {"columns": ["a"]},
    {"map": False, "map_max_kb": 100},                         # cap without map
])
def test_map_input_validation(bad):
    spec = {k: v for k, v in {**_map_input(), **bad}.items() if v is not None}
    with pytest.raises(ValueError):
        RecipeInput.model_validate(spec)


def test_map_input_resolves_without_datastore():
    m = RecipeManifest.model_validate({
        "dataset_id": DS, "recipe_version": 1, "authored_at": "2026-10-31T00:00:00Z",
        "inputs": [_map_input()],
    })

    def no_preview(rid):
        raise AssertionError("a map input never previews the datastore")

    assert resolve_inputs(m, _map_resources(), no_preview)["geo"][0]["id"] == GEO_RID
    for resources in ([], _map_resources(url="")):
        with pytest.raises(RecipeError) as e:
            resolve_inputs(m, resources, no_preview)
        assert e.value.reason == "schema_changed"


_KML = ('<kml><Placemark><ExtendedData><Data name="NAME"><value>באר שבע</value></Data>'
        '</ExtendedData><Point><coordinates>34.79,31.25</coordinates></Point>'
        '</Placemark></kml>').encode()
_GEOJSON = json.dumps({"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"NAME": "באר שבע"},
     "geometry": {"type": "Point", "coordinates": [34.79, 31.25]}}]}).encode()


@pytest.mark.parametrize("name, body", [
    ("layer.zip", _shp_zip([SQ], ["באר שבע"])),
    ("x.geojson", _GEOJSON),
    ("download", _KML),  # no telling suffix: sniffed from the bytes
])
def test_fetch_inputs_downloads_and_converts_the_map(tmp_path, name, body):
    recipe = Recipe.load(_with_map(tmp_path) / DS)
    preview, fetch = _events_ckan()
    files = FakeFiles(body)
    resources = _map_resources(url=MAP_URL.replace("layer.zip", name))
    out = rf.fetch_inputs(recipe, resources, tmp_path / "d", preview_fn=preview,
                          fetch_fn=fetch, fetch_file_fn=files)
    geo = out["geo"][0]
    assert geo.rows == 1 and geo.resource_id == GEO_RID and files.urls == [resources[1]["url"]]
    with open(geo.file, encoding="utf-8") as f:
        header, row = list(csv.reader(f))
    assert header == ["NAME", GEOMETRY_COLUMN] and row[0] == "באר שבע"
    geom = json.loads(row[1])
    lon, lat = geom["coordinates"][0][0] if geom["type"] == "Polygon" else geom["coordinates"]
    assert 34 < lon < 36 and 30 < lat < 33                    # ITM reprojected to WGS84
    assert not list((tmp_path / "d").glob("*.download"))      # raw file cleaned up


@pytest.mark.parametrize("files, kw, reason", [
    (FakeFiles(error=DownloadBlocked("HTTP 403")), {}, "fetch_failed"),
    (FakeFiles(error=URLError("dns")), {}, "fetch_failed"),
    (FakeFiles(error=FetchLimitExceeded("bytes", "big")), {}, "too_large"),
    (FakeFiles(error=ValueError("not a data.gov.il file URL")), {}, "schema_changed"),
    (FakeFiles(b"\x00\x01garbage"), {}, "schema_changed"),
    (FakeFiles(b"PK\x03\x04truncated zip"), {}, "schema_changed"),
    (FakeFiles(_shp_zip([SQ], ["א"])), {"required_columns": ["CODE"]}, "schema_changed"),
    (FakeFiles(_shp_zip([SQ] * 200, ["א"] * 200)), {"map_max_kb": 1}, "too_large"),
])
def test_map_download_failures_are_classified(tmp_path, files, kw, reason):
    recipe = Recipe.load(_with_map(tmp_path, **kw) / DS)
    preview, fetch = _events_ckan()
    with pytest.raises(RecipeError) as e:
        rf.fetch_inputs(recipe, _map_resources(), tmp_path / "d", preview_fn=preview,
                        fetch_fn=fetch, fetch_file_fn=files)
    assert e.value.reason == reason, e.value
    assert isinstance(e.value, rf.StrikeError) == isinstance(files.error, DownloadBlocked)


def test_map_input_fingerprints(tmp_path):
    recipe = Recipe.load(_with_map(tmp_path) / DS)
    preview, _ = _events_ckan()
    resources = _map_resources()
    resources[0]["hash"] = "md5-events"
    ident = rf.recipe_identity(recipe)
    probe = rf.probe_inputs(recipe, resources, preview)
    fp = rf.input_fingerprint(recipe, probe, ident)
    # No CKAN md5 for the map file: size alone can't vouch for it → download.
    assert rf.file_fingerprint(recipe, probe, ident) is None
    resources[1]["hash"] = "md5-map"
    assert rf.file_fingerprint(recipe, probe, ident) is not None
    resources[1]["size"] = 9001
    assert rf.input_fingerprint(recipe, rf.probe_inputs(recipe, resources, preview), ident) != fp


# ── live map inputs, end to end through run_refresh ──────────────────────


def _refresh_env(tmp_path, monkeypatch):
    from services.page_builder.tests.test_recipe_refresh import FakeCkan, FakeStore, _rows

    issues = []
    monkeypatch.setattr("services.page_builder.notify.open_authoring_issue",
                        lambda **kw: issues.append(kw) or 77)
    staged: dict = {}
    recipes = _with_map(tmp_path)

    def src(mm):
        return SimpleNamespace(
            id=DS, title="t", organization={"title": "o"}, analysis_status="succeeded",
            metadata_modified=datetime.fromisoformat(mm).replace(tzinfo=timezone.utc),
            resources=[{"id": RID, "name": "events", "format": "CSV", "datastore_active": True,
                        "hash": "md5-v1", "size": 1000}, _map_resources()[1]],
        )

    store = FakeStore(src("2026-10-01"))
    ckan = FakeCkan(_rows([2024, 2025]))

    def run(files):
        return rf.run_refresh(
            store, rf.LocalRecipeRepo(recipes), preview=True, staging_bucket="bkt",
            work_root=tmp_path / "work",
            write_gcs=lambda d, b, r: staged.__setitem__(r, d) or r,
            read_gcs=lambda b, r: staged.get(r),
            preview_fn=ckan.preview, fetch_fn=ckan.fetch, fetch_file_fn=files,
        )

    def state():
        return store.get_refresh_state(DS, preview=True)

    return SimpleNamespace(store=store, src=src, run=run, state=state, issues=issues)


def test_repeated_download_block_escalates_to_an_issue(tmp_path, monkeypatch):
    e = _refresh_env(tmp_path, monkeypatch)
    blocked = FakeFiles(error=DownloadBlocked("HTTP 403"))
    for n in (1, 2):
        s = e.run(blocked)
        assert s["outcomes"][0]["reason"] == "fetch_failed"
        assert e.state()["transient_strikes"] == {"download_blocked": n}
    assert e.issues == []
    s = e.run(blocked)
    assert s["outcomes"][0]["reason"] == "download_blocked"
    assert len(e.issues) == 1 and e.issues[0]["reason"] == "download_blocked"
    assert not e.state()["transient_strikes"]  # a fresh run of tries after the fix


def test_map_download_success_clears_strikes_and_precheck_skips_same_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("REFRESH_PRECHECK", "full")
    e = _refresh_env(tmp_path, monkeypatch)
    e.run(FakeFiles(error=DownloadBlocked("HTTP 403")))
    assert e.state()["transient_strikes"] == {"download_blocked": 1}
    good = FakeFiles(_shp_zip([SQ], ["באר שבע"]))
    s = e.run(good)
    assert s["failed"] == [] and s["outcomes"][0]["status"] == "refreshed"
    assert e.state()["transient_strikes"] is None
    # CKAN bump, same file bytes: no md5, so it downloads again, and B proves it.
    e.store.src = e.src("2026-10-02")
    s = e.run(good)
    assert len(good.urls) == 2
    assert s["outcomes"][0]["status"] == "unchanged"
    assert s["outcomes"][0]["reason"] == "inputs_hash"
    # A real geometry change gets past B (the fixture page doesn't draw it, so C stops it).
    e.store.src = e.src("2026-10-03")
    s = e.run(FakeFiles(_shp_zip([SQ, SQ], ["באר שבע", "דימונה"])))
    assert s["outcomes"][0]["precheck"]["inputs_same"] is False


def test_download_blocked_opens_an_issue():
    from services.page_builder.notify import REASON_TEXT

    assert "download_blocked" in rf.AUTHORING_REASONS and "download_blocked" in REASON_TEXT


# ── fetch_resource_file ──────────────────────────────────────────────────


class _Resp:
    def __init__(self, body: bytes, ctype: str = "application/zip"):
        self._buf, self.headers = io.BytesIO(body), {"Content-Type": ctype}

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen(monkeypatch, behaviour):
    from services.page_builder import agent_contract as ac

    seen = []

    def fake(req, timeout):
        seen.append(req)
        return behaviour(req)

    monkeypatch.setattr(ac.urllib_request, "urlopen", fake)
    return ac, seen


def test_fetch_resource_file_rewrites_host_and_sends_the_ua(tmp_path, monkeypatch):
    import hashlib
    import time

    ac, seen = _urlopen(monkeypatch, lambda req: _Resp(b"PK\x03\x04data"))
    got = ac.fetch_resource_file(MAP_URL, tmp_path / "f", max_bytes=100, timeout_s=5,
                                 deadline=time.monotonic() + 60)
    assert seen[0].full_url.startswith("https://data.gov.il/dataset/")
    assert seen[0].get_header("User-agent") == ac._CKAN_BROWSER_UA
    assert got.bytes == 8 and got.sha256 == hashlib.sha256(b"PK\x03\x04data").hexdigest()
    assert (tmp_path / "f").read_bytes() == b"PK\x03\x04data"


@pytest.mark.parametrize("behaviour, exc", [
    ("html", "DownloadBlocked"), ("html_body", "DownloadBlocked"), ("403", "DownloadBlocked"),
    ("empty", "DownloadBlocked"), ("big", "FetchLimitExceeded"), ("404", "HTTPError"),
])
def test_fetch_resource_file_refuses(tmp_path, monkeypatch, behaviour, exc):
    import time
    from urllib.error import HTTPError

    def b(req):
        if behaviour in ("403", "404"):
            raise HTTPError(req.full_url, int(behaviour), "x", {}, None)
        return {"html": _Resp(b"<p>blocked</p>", "text/html; charset=utf-8"),
                "html_body": _Resp(b"  <!DOCTYPE html><html>", "application/octet-stream"),
                "empty": _Resp(b""),
                "big": _Resp(b"x" * 1000)}[behaviour]

    ac, seen = _urlopen(monkeypatch, b)
    with pytest.raises(Exception) as e:
        ac.fetch_resource_file(MAP_URL, tmp_path / "f", max_bytes=100, timeout_s=5,
                               deadline=time.monotonic() + 60)
    assert type(e.value).__name__ == exc
    assert not (tmp_path / "f").exists()
    assert len(seen) == 1  # 4xx and blocks are not retried


def test_fetch_resource_file_only_fetches_data_gov_il(tmp_path, monkeypatch):
    import time

    ac, seen = _urlopen(monkeypatch, lambda req: _Resp(b"x"))
    for url in ("https://example.com/x.zip", "http://metadata.google.internal/x", ""):
        with pytest.raises(ValueError):
            ac.fetch_resource_file(url, tmp_path / "f", max_bytes=100, timeout_s=5,
                                   deadline=time.monotonic() + 60)
    assert seen == []


def test_parse_map_refuses_a_zip_bomb(monkeypatch):
    monkeypatch.setattr(gs, "MAX_UNZIPPED_BYTES", 1000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.geojson", b" " * 5000)
    with pytest.raises(gs.SnapshotError, match="unzips to more"):
        gs.parse_map(buf.getvalue(), "a.zip")
