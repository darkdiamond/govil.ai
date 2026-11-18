"""`raster: true` inputs: a GeoTIFF (or a zip of them) read into a per-file
summary table, plus an optional coarse grid (`raster_grid`). The TIFFs here
are synthetic float32 files written by Pillow with the GeoTIFF tags."""
from __future__ import annotations

import csv
import io
import json
import shutil
import zipfile
from pathlib import Path
from urllib.error import HTTPError

import numpy as np
import pytest
from PIL import Image, TiffImagePlugin, TiffTags

from services.page_builder import geo_snapshot as gs
from services.page_builder import refresh as rf
from services.page_builder.recipe import (
    Recipe,
    RecipeError,
    RecipeInput,
    RecipeManifest,
    resolve_inputs,
)
from services.page_builder.tests.test_map_snapshots import (
    DS,
    FIXTURES,
    GEO_RID,
    MAP_URL,
    FakeFiles,
    _events_ckan,
    _map_resources,
)

ORIGIN = (150_000.0, 700_000.0)  # ITM top-left corner


def _tif(a, *, origin=ORIGIN, px=(100.0, 100.0), nodata: str | None = None,
         georef: bool = True, compression: str | None = None) -> bytes:
    img = Image.fromarray(np.asarray(a, dtype=np.float32))  # float32 → mode "F"
    ifd = TiffImagePlugin.ImageFileDirectory_v2()
    if georef:
        ifd[33550] = (px[0], px[1], 0.0)
        ifd.tagtype[33550] = TiffTags.DOUBLE
        ifd[33922] = (0.0, 0.0, 0.0, origin[0], origin[1], 0.0)
        ifd.tagtype[33922] = TiffTags.DOUBLE
    if nodata is not None:
        ifd[42113] = nodata
        ifd.tagtype[42113] = TiffTags.ASCII
    buf = io.BytesIO()
    img.save(buf, format="TIFF", tiffinfo=ifd, compression=compression)
    return buf.getvalue()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def _grid(h=4, w=6, base=0.0):
    return np.arange(h * w, dtype=float).reshape(h, w) + base


# ── the contract ─────────────────────────────────────────────────────────


def _raster_input(**kw) -> dict:
    return {"name": "geo", "by_id": GEO_RID, "raster": True, **kw}


@pytest.mark.parametrize("bad", [
    {"by_id": None, "by_schema": ["a"], "concat": True},  # needs by_id
    {"map": True},
    {"snapshot": "geo.geojson", "snapshot_of": {"size": 1}},
    {"columns": ["n"]},
    {"concat": True},
    {"raster": False, "raster_grid": 10},                 # grid without raster
    {"raster_grid": 1},
    {"raster_grid": 1001},
])
def test_raster_input_validation(bad):
    spec = {k: v for k, v in {**_raster_input(), **bad}.items() if v is not None}
    with pytest.raises(ValueError):
        RecipeInput.model_validate(spec)


def test_raster_input_resolves_without_datastore():
    m = RecipeManifest.model_validate({
        "dataset_id": DS, "recipe_version": 1, "authored_at": "2026-11-17T00:00:00Z",
        "inputs": [_raster_input(raster_grid=25)],
    })

    def no_preview(rid):
        raise AssertionError("a raster input never previews the datastore")

    assert resolve_inputs(m, _map_resources(), no_preview)["geo"][0]["id"] == GEO_RID
    with pytest.raises(RecipeError) as e:
        resolve_inputs(m, [], no_preview)
    assert e.value.reason == "schema_changed"


# ── the reader ───────────────────────────────────────────────────────────


def test_a_bare_geotiff_summarizes_with_nodata_masked():
    a = _grid()
    a[0, 0] = -9999            # the GDAL_NODATA tag's value
    a[0, 1] = -3.4028235e38    # GDAL's float32 sentinel, no tag needed
    a[0, 2] = np.nan
    header, rows = gs.raster_table(_tif(a, nodata="-9999", compression="tiff_lzw"),
                                   "level_2019.tif")
    assert header == gs.RASTER_COLUMNS
    (row,) = rows
    got = dict(zip(header, row, strict=True))
    valid = a.ravel()[3:]
    assert got["file"] == "level_2019.tif" and got["year"] == "2019"
    assert got["n"] == "21" and got["nodata"] == "3"
    assert float(got["mean"]) == pytest.approx(valid.mean())
    assert got["min"] == "3" and got["max"] == "23"
    assert float(got["p50"]) == pytest.approx(np.percentile(valid, 50))
    assert (got["x0"], got["y0"], got["dx"], got["dy"]) == ("150000", "700000", "100", "100")


def test_a_zip_of_yearly_tiffs_is_one_row_per_file_in_name_order():
    body = _zip({"chloride/cl_2020.tif": _tif(_grid(base=10)),
                 "chloride/cl_1977.tif": _tif(_grid()),
                 "readme.txt": b"x", "__MACOSX/._cl_2020.tif": b"junk"})
    header, rows = gs.raster_table(body, "chloride.zip")
    assert [(r[0], r[1]) for r in rows] == [("cl_1977.tif", "1977"), ("cl_2020.tif", "2020")]
    assert gs.raster_table(body, "chloride.zip") == (header, rows)  # deterministic


def test_a_year_is_left_empty_when_the_name_has_none():
    _, rows = gs.raster_table(_tif(_grid()), "levels.tif")
    assert rows[0][1] == ""


def test_an_all_nodata_tiff_has_blank_stats():
    _, rows = gs.raster_table(_tif(np.full((2, 2), -9999.0), nodata="-9999"), "x_2001.tif")
    assert rows[0][2:10] == ["0", "4", "", "", "", "", "", ""]


@pytest.mark.parametrize("body, match", [
    (b"not a tiff at all", "not a TIFF or a zip"),
    (_zip({"a.txt": b"x"}), "holds no .tif"),
    (_tif(_grid(), georef=False), "no GeoTIFF georeference"),
    (b"II*\0garbage", "not a readable TIFF"),
], ids=["not-tiff", "zip-no-tif", "no-georef", "corrupt"])  # zip bytes embed mtimes
def test_bad_rasters_are_refused_cleanly(body, match):
    with pytest.raises(gs.SnapshotError, match=match):
        gs.raster_table(body, "x.tif")


def test_a_raster_over_the_pixel_cap_is_refused_before_decoding(monkeypatch):
    monkeypatch.setattr(gs, "MAX_RASTER_PIXELS", 10)
    with pytest.raises(gs.SnapshotError, match="pixels, over"):
        gs.raster_table(_tif(_grid()), "x.tif")


def test_a_nodata_value_float32_cant_hold_is_still_masked():
    a = _grid()
    a[0, 0] = -9999.99  # stored as float32(-9999.99) != -9999.99
    _, rows = gs.raster_table(_tif(a, nodata="-9999.99"), "x.tif")
    assert rows[0][2:4] == ["23", "1"]


def test_a_multiband_tiff_is_refused_before_decoding():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="TIFF")
    with pytest.raises(gs.SnapshotError, match="3 bands"):
        gs.raster_table(buf.getvalue(), "x.tif")


def test_a_raster_over_a_cap_is_too_large(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(gs, "MAX_RASTER_PIXELS", 10)
        with pytest.raises(gs.SnapshotTooLarge):
            gs.raster_table(_tif(_grid()), "x.tif")
    with monkeypatch.context() as m:
        m.setattr(gs, "MAX_UNZIPPED_BYTES", 10)
        with pytest.raises(gs.SnapshotTooLarge):
            gs.raster_table(_zip({"a.tif": _tif(_grid())}), "x.zip")


def test_the_grid_adds_block_means_with_wgs84_centres():
    a = _grid(4, 6)
    a[0, 0] = np.nan
    header, rows = gs.raster_table(_tif(a), "lvl_2023.tif", grid=4)
    assert header == ["kind", *gs.RASTER_COLUMNS, "row", "col", "lat", "lon", "value"]
    assert all(len(r) == len(header) for r in rows)
    kinds = [r[0] for r in rows]
    assert kinds == ["summary", "cell", "cell"]  # 4×6 in 4-pixel blocks: 1 row × 2 cols
    cells = [dict(zip(header, r, strict=True)) for r in rows[1:]]
    assert [(c["row"], c["col"]) for c in cells] == [("0", "0"), ("0", "1")]
    assert float(cells[0]["value"]) == pytest.approx(np.nanmean(a[:4, :4]))
    assert float(cells[1]["value"]) == pytest.approx(a[:4, 4:].mean())  # the clipped edge block
    for c in cells:
        assert 34 < float(c["lon"]) < 36 and 30 < float(c["lat"]) < 34 and c["year"] == "2023"
    # The edge block's centre sits half its clipped width in, not half a full block.
    lon0, _ = gs.itm_to_wgs(ORIGIN[0] + 5 * 100, ORIGIN[1] - 2 * 100)
    assert float(cells[1]["lon"]) == pytest.approx(lon0, abs=1e-6)


def test_the_grid_is_capped(monkeypatch):
    monkeypatch.setattr(gs, "MAX_GRID_ROWS", 3)
    with pytest.raises(gs.SnapshotTooLarge, match="grid cells"):
        gs.raster_table(_tif(_grid(10, 10)), "x.tif", grid=2)


# ── through the refresh ──────────────────────────────────────────────────


def _with_raster(tmp_path: Path, **kw) -> Path:
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    m = json.loads((recipes / DS / "recipe.json").read_text())
    m["inputs"].append(_raster_input(**kw))
    (recipes / DS / "recipe.json").write_text(json.dumps(m, ensure_ascii=False))
    return recipes


def test_fetch_inputs_downloads_and_summarizes_the_raster(tmp_path):
    recipe = Recipe.load(_with_raster(tmp_path) / DS)
    preview, fetch = _events_ckan()
    body = _zip({"wl_2022.tif": _tif(_grid()), "wl_2023.tif": _tif(_grid(base=1))})
    resources = _map_resources(url=MAP_URL.replace("layer.zip", "levels.zip"))
    out = rf.fetch_inputs(recipe, resources, tmp_path / "d", preview_fn=preview,
                          fetch_fn=fetch, fetch_file_fn=FakeFiles(body))
    geo = out["geo"][0]
    with open(geo.file, encoding="utf-8") as f:
        header, *rows = list(csv.reader(f))
    assert header == gs.RASTER_COLUMNS and geo.rows == 2 == len(rows)
    assert not list((tmp_path / "d").glob("*.download"))


@pytest.mark.parametrize("files, kw, reason, strike", [
    (FakeFiles(b"garbage"), {}, "schema_changed", None),
    (FakeFiles(_tif(_grid())), {"required_columns": ["band"]}, "schema_changed", None),
    (FakeFiles(error=HTTPError(MAP_URL, 404, "nf", None, None)), {}, "fetch_failed",
     "download_missing"),
])
def test_raster_failures_are_classified(tmp_path, files, kw, reason, strike):
    recipe = Recipe.load(_with_raster(tmp_path, **kw) / DS)
    preview, fetch = _events_ckan()
    with pytest.raises(RecipeError) as e:
        rf.fetch_inputs(recipe, _map_resources(), tmp_path / "d", preview_fn=preview,
                        fetch_fn=fetch, fetch_file_fn=files)
    assert e.value.reason == reason and getattr(e.value, "strike", None) == strike


def test_raster_too_many_grid_cells_is_too_large(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "MAX_GRID_ROWS", 1)
    recipe = Recipe.load(_with_raster(tmp_path, raster_grid=2) / DS)
    preview, fetch = _events_ckan()
    with pytest.raises(RecipeError) as e:
        rf.fetch_inputs(recipe, _map_resources(), tmp_path / "d", preview_fn=preview,
                        fetch_fn=fetch, fetch_file_fn=FakeFiles(_tif(_grid())))
    assert e.value.reason == "too_large"


def test_raster_input_fingerprints_and_identity(tmp_path):
    recipe = Recipe.load(_with_raster(tmp_path) / DS)
    preview, _ = _events_ckan()
    resources = _map_resources()
    resources[0]["hash"] = "md5-events"
    ident = rf.recipe_identity(recipe)
    probe = rf.probe_inputs(recipe, resources, preview)
    fp = rf.input_fingerprint(recipe, probe, ident)
    assert rf.file_fingerprint(recipe, probe, ident) is None  # no md5 for the file
    resources[1]["hash"] = "md5-raster"
    assert rf.file_fingerprint(recipe, probe, ident) is not None
    resources[1]["size"] = 9001
    assert rf.input_fingerprint(recipe, rf.probe_inputs(recipe, resources, preview), ident) != fp
    # geo_snapshot.py (the reader) is folded into the identity, as for a map input.
    plain = Recipe.load(FIXTURES / DS)
    rf._geo_code_hash.cache_clear()
    calls = []
    real = rf._geo_code_hash

    def spy():
        calls.append(1)
        return real()

    try:
        rf._geo_code_hash = spy
        rf.recipe_identity(plain)
        assert calls == []
        rf.recipe_identity(recipe)
        assert calls == [1]
    finally:
        rf._geo_code_hash = real
