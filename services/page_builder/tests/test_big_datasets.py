"""Big-dataset levers in the recipe contract: `columns` (fetch fewer
columns), `pick: "latest"` (read only the newest snapshot resource) and
`limits` (per-recipe caps; such "heavy" recipes run last, under a compute
memory guard)."""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from services.page_builder import ckan_export
from services.page_builder import refresh as rf
from services.page_builder.recipe import (
    PreviewUnavailable,
    Recipe,
    RecipeError,
    RecipeManifest,
    resolve_inputs,
)
from services.page_builder.tests import test_recipe_refresh
from services.page_builder.tests.test_recipe_refresh import (
    COLS,
    DS,
    FIXTURES,
    RID,
    FakeCkan,
    FakeStore,
    _rows,
    _run,
    _src,
)
from services.shared.fetch_types import FetchLimitExceeded, FetchOutcome
from services.shared.states import RefreshState

env = test_recipe_refresh.env  # the shared fixture, registered in this module too


def _manifest(inputs, **kw):
    return RecipeManifest.model_validate({
        "dataset_id": DS, "recipe_version": 1, "authored_at": "2026-10-30T00:00:00Z",
        "inputs": inputs, **kw,
    })


def _fixture_copy(tmp_path, mutate):
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    m = recipes / DS / "recipe.json"
    data = json.loads(m.read_text(encoding="utf-8"))
    mutate(data)
    m.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return recipes


# ── contract ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("inp", [
    {"name": "x", "by_id": RID, "pick": "latest"},                       # latest needs by_schema
    {"name": "x", "by_schema": ["a"], "concat": True, "pick": "latest"},  # latest reads one file
    {"name": "x", "by_id": RID, "required_columns": ["a", "b"], "columns": ["a"]},
    {"name": "x", "by_id": RID, "columns": ["a", "a"]},
    {"name": "x", "by_id": RID, "columns": []},
])
def test_invalid_inputs_are_rejected(inp):
    with pytest.raises(ValueError):
        _manifest([inp])


def test_latest_by_schema_needs_no_concat():
    m = _manifest([{"name": "x", "by_schema": ["a"], "pick": "latest"}])
    assert m.inputs[0].pick == "latest" and not m.heavy


@pytest.mark.parametrize("limits", [{"max_records": 0}, {"max_records": 10**9}, {"bogus": 1}])
def test_limits_are_bounded(limits):
    with pytest.raises(ValueError):
        _manifest([{"name": "x", "by_id": RID}], limits=limits)


def test_limits_make_a_recipe_heavy():
    assert _manifest([{"name": "x", "by_id": RID}], limits={"max_records": 3_000_000}).heavy


# ── pick: latest ─────────────────────────────────────────────────────────


def _snapshots():
    return [
        {"id": "r-old", "name": "נכון ליום 2021", "format": "CSV", "datastore_active": True,
         "last_modified": datetime(2021, 11, 10, tzinfo=UTC)},
        {"id": "r-new", "name": "נכון ליום 2026", "format": "CSV", "datastore_active": True,
         "last_modified": "2026-09-06T06:14:33"},  # naive ISO string: read as UTC
        {"id": "r-none", "name": "ללא תאריך", "format": "CSV", "datastore_active": True,
         "last_modified": None},
        {"id": "r-other", "name": "אחר", "format": "CSV", "datastore_active": True,
         "last_modified": datetime(2027, 1, 1, tzinfo=UTC)},
    ]


def test_latest_picks_newest_matching_snapshot():
    m = _manifest([{"name": "main", "by_schema": ["a"], "pick": "latest"}])
    fields = {"r-old": ["a", "b"], "r-new": ["a", "b"], "r-none": ["a"], "r-other": ["z"]}
    out = resolve_inputs(m, _snapshots(), fields.get)
    # r-other is newer but doesn't match the schema.
    assert [r["id"] for r in out["main"]] == ["r-new"]


@pytest.mark.parametrize("how", [{"concat": True}, {"pick": "latest"}])
def test_by_schema_resolves_to_the_full_resource(how):
    """The export downloads the input's file by its url, and check A′ reads its
    CKAN hash: a schema match must carry them, as a by_id input does."""
    inp = {"name": "main", "by_schema": ["a"], **how}
    res = [{"id": "r1", "name": "x", "format": "csv", "datastore_active": True,
            "url": "https://data.gov.il/dataset/d/resource/r1/download/r1.csv",
            "hash": "md5", "size": 123}]
    out = resolve_inputs(_manifest([inp]), res, lambda rid: ["a"])
    assert out["main"][0] is res[0]


def test_latest_ties_keep_ckan_order():
    m = _manifest([{"name": "main", "by_schema": ["a"], "pick": "latest"}])
    res = [{"id": i, "name": i, "format": "CSV", "datastore_active": True} for i in ("p", "q")]
    out = resolve_inputs(m, res, lambda rid: ["a"])
    assert [r["id"] for r in out["main"]] == ["p"]


def test_latest_snapshot_missing_a_column_is_schema_changed():
    m = _manifest([{"name": "main", "by_schema": ["a"], "pick": "latest",
                    "required_columns": ["b"]}])
    fields = {"r-old": ["a", "b"], "r-new": ["a"], "r-none": ["a", "b"], "r-other": ["z"]}
    with pytest.raises(RecipeError) as e:
        resolve_inputs(m, _snapshots(), fields.get)
    assert e.value.reason == "schema_changed"


# ── columns ──────────────────────────────────────────────────────────────


def test_fetch_page_sends_fields(monkeypatch):
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"success": True, "result": {
                "fields": [{"id": "b"}, {"id": "a"}], "records": [{"b": 1, "a": 2}],
            }}).encode()

    def fake(req, timeout=None):
        seen.update(parse_qs(urlparse(req.full_url).query))
        return _Resp()

    monkeypatch.setattr(ckan_export.urllib_request, "urlopen", fake)
    fields, _ = ckan_export._fetch_page("rid", 0, 10, 5.0, ["b", "a"])
    assert seen["fields"] == ["b", "a"] and fields == ["b", "a"]
    seen.clear()
    ckan_export._fetch_page("rid", 0, 10, 5.0)
    assert "fields" not in seen


def test_columns_reach_the_fetcher_and_compute_sees_only_them(env, tmp_path):
    # FakeCkan ignores `fields` (like a provider fetcher), so the host-side
    # projection is what trims the extra column.
    cols = [*COLS, "עמודה רחבה"]
    rows = [[*r, "x" * 50] for r in _rows([2024, 2025])]
    recipes = _fixture_copy(tmp_path, lambda d: d["inputs"][0].update(columns=list(reversed(COLS))))
    recipe = Recipe.load(recipes / DS)
    ckan = FakeCkan(rows, cols)
    seen = []
    orig = ckan.fetch

    def fetch(rid, total, dest, **kw):
        seen.append(kw.get("fields"))
        return orig(rid, total, dest, **kw)

    inputs = rf.fetch_inputs(recipe, _src().resources, tmp_path / "data",
                             preview_fn=ckan.preview, fetch_fn=fetch)
    assert seen == [list(reversed(COLS))]
    with open(inputs["events"][0].file, encoding="utf-8", newline="") as f:
        got = list(csv.reader(f))
    assert got[0] == list(reversed(COLS))
    assert got[1] == list(reversed(rows[0][:4]))
    # And the page still renders end to end from the projected frame.
    store = FakeStore(_src())
    s = _run(env, store, ckan, recipes=recipes)
    assert s["refreshed"] == [DS]


@pytest.mark.parametrize("env_value, want", [(None, rf._DEFAULT_FILE_MAX_BYTES), ("123", 123)])
def test_the_file_download_cap_reaches_the_fetcher(tmp_path, monkeypatch, env_value, want):
    if env_value is None:
        monkeypatch.delenv("REFRESH_FILE_MAX_BYTES", raising=False)
    else:
        monkeypatch.setenv("REFRESH_FILE_MAX_BYTES", env_value)
    recipe = Recipe.load(_fixture_copy(tmp_path, lambda d: None) / DS)
    ckan = FakeCkan(_rows([2024, 2025]))
    seen = []

    def fetch(rid, total, dest, **kw):
        seen.append(kw.get("file_max_bytes"))
        return ckan.fetch(rid, total, dest, **kw)

    rf.fetch_inputs(recipe, _src().resources, tmp_path / "data",
                    preview_fn=ckan.preview, fetch_fn=fetch)
    assert seen == [want]


def test_column_listed_but_gone_is_schema_changed(env, tmp_path):
    recipes = _fixture_copy(tmp_path, lambda d: d["inputs"][0].update(columns=[*COLS, "נעלמה"]))
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), recipes=recipes)
    assert s["outcomes"][0]["reason"] == "schema_changed"


# ── limits ───────────────────────────────────────────────────────────────


def test_recipe_limits_override_env_caps(env, tmp_path, monkeypatch):
    monkeypatch.setenv("REFRESH_MAX_RECORDS", "10")
    recipes = _fixture_copy(tmp_path, lambda d: d.update(limits={"max_records": 1000}))
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), recipes=recipes)
    assert s["refreshed"] == [DS]


def test_recipe_limits_can_also_tighten(env, tmp_path):
    recipes = _fixture_copy(tmp_path, lambda d: d.update(limits={"max_records": 10}))
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), recipes=recipes)
    assert s["outcomes"][0]["reason"] == "too_large"


def test_heavy_recipes_run_last(tmp_path, monkeypatch):
    ids = ["00000000-0000-0000-0000-00000000000a", "00000000-0000-0000-0000-00000000000b",
           "00000000-0000-0000-0000-00000000000c"]
    recipes = tmp_path / "recipes"
    for i in ids:
        shutil.copytree(FIXTURES / DS, recipes / i)
        m = recipes / i / "recipe.json"
        d = json.loads(m.read_text(encoding="utf-8"))
        d["dataset_id"] = i
        if i.endswith("a"):
            d["limits"] = {"max_records": 3_000_000}
        m.write_text(json.dumps(d), encoding="utf-8")
    order = []
    monkeypatch.setattr(rf, "refresh_one", lambda src, recipe, **kw: (
        order.append(src.id) or rf.RefreshOutcome(src.id, "refreshed")
    ))
    store = SimpleNamespace(
        get_source=lambda i: SimpleNamespace(id=i, title="", refresh=RefreshState()),
    )
    s = rf.run_refresh(store, rf.LocalRecipeRepo(recipes),
                       staging_bucket="bkt", work_root=tmp_path / "w", force=True)
    assert order == [ids[1], ids[2], ids[0]]
    assert s["refreshed"] == order


def test_heavy_recipes_respect_the_cap(tmp_path, monkeypatch):
    ids = ["00000000-0000-0000-0000-00000000000a", "00000000-0000-0000-0000-00000000000b"]
    recipes = tmp_path / "recipes"
    for i in ids:
        shutil.copytree(FIXTURES / DS, recipes / i)
        m = recipes / i / "recipe.json"
        d = json.loads(m.read_text(encoding="utf-8"))
        d["dataset_id"] = i
        if i.endswith("a"):
            d["limits"] = {"max_records": 3_000_000}
        m.write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setattr(rf, "refresh_one", lambda src, recipe, **kw: rf.RefreshOutcome(
        src.id, "refreshed"))
    store = SimpleNamespace(
        get_source=lambda i: SimpleNamespace(id=i, title="", refresh=RefreshState()),
    )
    s = rf.run_refresh(store, rf.LocalRecipeRepo(recipes), cap=1,
                       staging_bucket="bkt", work_root=tmp_path / "w", force=True)
    assert s["refreshed"] == [ids[1]]
    assert s["outcomes"][1] == {**s["outcomes"][1], "id": ids[0], "reason": "cap"}


# ── memory guard ─────────────────────────────────────────────────────────


def _guard(monkeypatch, limits=None, env_mb=None):
    if env_mb is not None:
        monkeypatch.setenv("REFRESH_COMPUTE_MEMORY_MB", str(env_mb))
    m = _manifest([{"name": "x", "by_id": RID}], **({"limits": limits} if limits else {}))
    return rf._memory_guard(SimpleNamespace(manifest=m))


def test_memory_guard_cap_sources(monkeypatch):
    assert f"({3072 * 2**20}, " in _guard(monkeypatch)
    assert f"({512 * 2**20}, " in _guard(monkeypatch, env_mb=512)
    assert f"({6000 * 2**20}, " in _guard(monkeypatch, {"compute_memory_mb": 6000}, env_mb=512)
    off = _guard(monkeypatch, env_mb=0)
    assert "RLIMIT_DATA" not in off and "oom_score_adj" in off


def test_memory_guard_turns_overuse_into_memory_error(monkeypatch):
    code = _guard(monkeypatch, env_mb=256) + (
        "import os\n"
        "print(open('/proc/self/oom_score_adj').read().strip())\n"
        "try:\n"
        "    b = bytearray(512 * 1024 * 1024)\n"
        "    print('allocated')\n"
        "except MemoryError:\n"
        "    print('MemoryError')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False,
                         timeout=60).stdout.split()
    assert out == ["1000", "MemoryError"]


# ── review follow-ups ────────────────────────────────────────────────────


def test_id_is_not_a_fetchable_column():
    with pytest.raises(ValueError):
        _manifest([{"name": "x", "by_id": RID, "columns": ["_id", "a"]}])


def test_empty_limits_are_not_heavy():
    assert not _manifest([{"name": "x", "by_id": RID}], limits={}).heavy


def test_fields_with_commas_are_sent_as_repeated_params(monkeypatch):
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"success": True, "result": {"fields": [], "records": []}}).encode()

    def fake(req, timeout=None):
        seen.update(parse_qs(urlparse(req.full_url).query))
        return _Resp()

    monkeypatch.setattr(ckan_export.urllib_request, "urlopen", fake)
    ckan_export._fetch_page("rid", 0, 10, 5.0, ['סכום, ש"ח', "שנה"])
    assert seen["fields"] == ['סכום, ש"ח', "שנה"]


def test_max_bytes_limit_is_not_clipped_by_the_default_total(tmp_path, monkeypatch):
    monkeypatch.setenv("REFRESH_TOTAL_BYTES", "100")
    recipes = _fixture_copy(tmp_path, lambda d: d.update(limits={"max_bytes": 5000}))
    recipe = Recipe.load(recipes / DS)
    ckan = FakeCkan(_rows([2024]))
    caps = []
    orig = ckan.fetch

    def fetch(rid, total, dest, **kw):
        caps.append(kw["max_bytes"])
        return orig(rid, total, dest, **kw)

    rf.fetch_inputs(recipe, _src().resources, tmp_path / "d",
                    preview_fn=ckan.preview, fetch_fn=fetch)
    assert caps == [5000]


def test_projection_of_an_export_missing_a_column_is_schema_changed(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(RecipeError) as e:
        rf._project_csv(f, ["b", "c"])
    assert e.value.reason == "schema_changed"
    rf._project_csv(f, ["b"])
    assert f.read_text(encoding="utf-8").splitlines() == ["b", "2"]


def test_coverage_flags_a_used_column_that_is_never_fetched(tmp_path):
    from services.page_builder import author

    recipes = _fixture_copy(tmp_path, lambda d: d["inputs"][0].update(
        columns=COLS[:3], required_columns=COLS[:3]))
    recipe = Recipe.load(recipes / DS)
    (recipes / DS / author.COVERAGE_FILENAME).write_text(json.dumps(
        {f"events.{c}": "skip: not shown on this page" for c in COLS[:3]}
        | {f"events.{COLS[3]}": "kpi:total"}, ensure_ascii=False), encoding="utf-8")
    manifest = [{"resource_id": RID, "fields": COLS}]
    inputs = {"events": [rf.FetchedInput(tmp_path / "x.csv", RID, "events", 1)]}
    problems, _ = author._coverage_findings(recipe, inputs, manifest, "", {"kpis": {}})
    assert any("never fetched" in p for p in problems)


# ── author verify mirrors the byte caps ──────────────────────────────────


def _local_ckan(tmp_path, **entry):
    from services.page_builder import author

    (tmp_path / "1.csv").write_text("a,b\n" + "1,xxxxxxxxxx\n" * 50, encoding="utf-8")
    m = {"resource_id": "r1", "fields": ["a", "b"], "total": 50, "file": "1.csv", **entry}
    return author._LocalCkan(tmp_path, [m])


def test_local_ckan_measures_the_cap_on_projected_columns(tmp_path):
    lc = _local_ckan(tmp_path)
    dest = tmp_path / "out.csv"
    # All columns: ~600 bytes, over 300. Only `a` (what prod exports): ~100.
    with pytest.raises(FetchLimitExceeded):
        lc.fetch("r1", 50, dest, max_bytes=300)
    assert not dest.exists()
    out = lc.fetch("r1", 50, dest, max_bytes=300, fields=["a"])
    assert out.rows == 50 and dest.read_text().splitlines()[0] == "a"


def test_local_ckan_replays_a_prepare_skip(tmp_path):
    lc = _local_ckan(tmp_path, file=None, skipped="bytes")
    with pytest.raises(FetchLimitExceeded) as e:
        lc.fetch("r1", 50, tmp_path / "out.csv", max_bytes=10**6)
    assert e.value.limit == "bytes"


def test_brief_names_the_byte_cap_skip(tmp_path):
    from services.page_builder import author

    facts = {"id": DS, "title": "t", "organization": {}, "notes": "", "metadata_modified": "x"}
    m = {"resource_id": "r1", "name": "n", "format": "CSV", "field_types": {},
         "total": 9, "file": None, "rows": 0, "skipped": "bytes"}
    brief = author._brief(facts, [m], [], {"data": tmp_path})
    assert "over the byte cap" in brief and "REFRESH_MAX_RECORDS" not in brief


@pytest.mark.parametrize("fields", [
    # r-new (the newest match) didn't answer: picking r-old would be a guess.
    {"r-old": ["a"], "r-new": None, "r-none": ["a"], "r-other": ["z"]},
    # Nothing answered: not "no resource has columns".
    {},
])
def test_by_schema_with_a_missing_preview_is_transient(fields):
    m = _manifest([{"name": "main", "by_schema": ["a"], "pick": "latest"}])
    with pytest.raises(PreviewUnavailable) as e:
        resolve_inputs(m, _snapshots(), fields.get)
    assert e.value.reason == "fetch_failed"


def test_by_id_with_a_missing_preview_is_transient():
    m = _manifest([{"name": "x", "by_id": RID, "required_columns": ["a"]}])
    res = [{"id": RID, "name": "x", "format": "CSV", "datastore_active": True}]
    with pytest.raises(PreviewUnavailable):
        resolve_inputs(m, res, lambda rid: None)


# ── author prepare follows the committed recipe's limits + columns ───────


def _prepare_env(tmp_path, monkeypatch, mutate):
    """prepare() against a fake CKAN + store, with recipes/<DS> mutated."""
    from services.page_builder import author
    from services.shared import firestore

    recipes = _fixture_copy(tmp_path, mutate)
    monkeypatch.setattr(author, "RECIPES_ROOT", recipes)
    monkeypatch.setattr(author, "AUTHORING_ROOT", tmp_path / "authoring")
    src = SimpleNamespace(
        **vars(_src()), slug="events", notes="", tags=[], update_frequency=None,
        license_title=None, record_count=36, page_path=None, agent_data=None,
    )
    store = SimpleNamespace(get_source=lambda _id: src, list_org_sources=lambda *a, **k: [])
    monkeypatch.setattr(firestore, "FirestoreStateStore", lambda: store)
    monkeypatch.setattr(ckan_export, "fetch_resource_preview",
                        lambda rid: {"total": 36, "fields": [{"id": c} for c in COLS]})
    calls = []

    def export(rid, total, dest, **kw):
        calls.append(kw)
        # Like the uploaded-file path: every column, whatever `fields` asked.
        with open(dest, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(COLS)
            w.writerows(_rows([2023]))
        return FetchOutcome(rows=12 * 3, bytes=dest.stat().st_size)

    monkeypatch.setattr(ckan_export, "fetch_resource_export", export)
    return author, calls


def test_prepare_reads_the_recipes_limits_and_columns(tmp_path, monkeypatch):
    def heavy(d):
        d["limits"] = {"max_records": 100, "max_bytes": 12345, "wall_budget_s": 2000}
        d["inputs"][0].update(required_columns=["שנה", "מחוז"], columns=["שנה", "מחוז"])

    monkeypatch.setenv("REFRESH_MAX_RECORDS", "5")  # the env alone would skip it
    author, calls = _prepare_env(tmp_path, monkeypatch, heavy)
    author.prepare(DS)
    data = tmp_path / "authoring" / DS / "data"
    [m] = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    assert m["rows"] == 36 and m["columns"] == ["שנה", "מחוז"]
    assert m["fields"] == COLS  # the preview's full list, for coverage
    [kw] = calls
    assert kw["fields"] == ["שנה", "מחוז"] and kw["max_bytes"] == 12345
    assert (data / m["file"]).read_text(encoding="utf-8").splitlines()[0] == "שנה,מחוז"
    brief = (tmp_path / "authoring" / DS / "BRIEF.md").read_text(encoding="utf-8")
    assert "only the recipe's `columns` (2 of 4)" in brief


def test_prepare_exports_every_column_when_an_input_reads_them_all(tmp_path, monkeypatch):
    def drifted(d):  # a column the preview no longer has: verify reports it, not prepare
        d["inputs"][0].update(required_columns=["שנה"], columns=["שנה", "עמודה שנעלמה"])

    author, calls = _prepare_env(tmp_path, monkeypatch, drifted)
    author.prepare(DS)
    assert calls[0]["fields"] is None
    assert calls[0]["max_bytes"] == rf._DEFAULT_MAX_BYTES

    author, calls = _prepare_env(tmp_path / "b", monkeypatch, lambda d: None)  # no `columns`
    author.prepare(DS)
    assert calls[0]["fields"] is None


def test_local_ckan_replays_a_failed_preview(tmp_path):
    lc = _local_ckan(tmp_path, preview_failed=True)
    assert lc.preview("r1") is None  # verify sees "no preview", as the refresh would


def test_prepare_all_columns_overrides_the_recipes_columns(tmp_path, monkeypatch):
    def narrow(d):
        d["inputs"][0].update(required_columns=["שנה"], columns=["שנה"])

    author, calls = _prepare_env(tmp_path, monkeypatch, narrow)
    author.prepare(DS, all_columns=True)
    assert calls[0]["fields"] is None


def test_local_ckan_says_to_reprepare_when_columns_grew(tmp_path):
    lc = _local_ckan(tmp_path, columns=["a", "b"])
    with pytest.raises(RecipeError, match="re-run `author prepare`"):
        lc.fetch("r1", 50, tmp_path / "out.csv", max_bytes=10**6, fields=["a", "c"])


# ── optional provider resources ──────────────────────────────────────────


@pytest.mark.parametrize("optional", [False, True])
def test_empty_resource_fails_unless_its_provider_marks_it_optional(tmp_path, optional):
    """A CBS table resource with `optional` may be empty by design (no edition
    has that table); any other empty resource is still a fetch failure."""
    recipe = Recipe.load(_fixture_copy(tmp_path, lambda d: None) / DS)
    ckan = FakeCkan([])
    resources = [dict(r, params={"optional": True} if optional else {})
                 for r in _src().resources]
    if not optional:
        with pytest.raises(RecipeError, match="has no rows") as e:
            rf.fetch_inputs(recipe, resources, tmp_path / "d",
                            preview_fn=ckan.preview, fetch_fn=ckan.fetch)
        assert e.value.reason == "fetch_failed"
        return
    out = rf.fetch_inputs(recipe, resources, tmp_path / "d",
                          preview_fn=ckan.preview, fetch_fn=ckan.fetch)
    (part,) = out["events"]
    assert part.rows == 0
    with open(part.file, encoding="utf-8", newline="") as f:
        assert list(csv.reader(f)) == [COLS]


# ── author verify resolves inputs against the refresh's resource list ────

_RA, _RB, _RC = (f"{c * 8}-0000-0000-0000-000000000000" for c in "abc")
_PROD_RESOURCES = [
    {"id": _RA, "name": "a", "format": "XLSX", "datastore_active": True},
    {"id": _RC, "name": "c", "format": "CSV", "datastore_active": False},
    {"id": _RB, "name": "b", "format": "CSV", "datastore_active": True},
]


def _verify_layout(tmp_path, monkeypatch, source, manifest, inputs):
    from services.page_builder import author

    recipes = _fixture_copy(tmp_path, lambda d: d.update(inputs=inputs))
    monkeypatch.setattr(author, "AUTHORING_ROOT", tmp_path / "authoring")
    data = tmp_path / "authoring" / DS / "data"
    data.mkdir(parents=True)
    (data / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if source is not None:
        (tmp_path / "authoring" / DS / "source.json").write_text(json.dumps(source), encoding="utf-8")
    return author, recipes, data


@pytest.mark.parametrize("order", [[0, 1, 2], [2, 1, 0]])
def test_verify_resolves_inputs_in_prod_order(tmp_path, monkeypatch, order):
    prod = [_PROD_RESOURCES[i] for i in order]
    manifest = [{"resource_id": r["id"], "name": r["name"], "format": r["format"],
                 "fields": COLS, "field_types": {}, "total": 1, "file": None, "rows": 0}
                for r in sorted((r for r in prod if r["datastore_active"]), key=lambda r: r["id"])]
    author, recipes, _ = _verify_layout(
        tmp_path, monkeypatch, {"resources": prod}, manifest,
        [{"name": "events", "by_schema": COLS, "concat": True}],
    )
    recipe, _, resources = author.load_local(DS, recipes)
    got = [r["id"] for r in resolve_inputs(recipe.manifest, resources, lambda rid: COLS)["events"]]
    want = [r["id"] for r in resolve_inputs(recipe.manifest, prod, lambda rid: COLS)["events"]]
    assert got == want
    assert got == ([_RA, _RB] if order == [0, 1, 2] else [_RB, _RA])


def test_verify_without_a_source_list_falls_back_to_the_manifest(tmp_path, monkeypatch, capsys):
    manifest = [{"resource_id": RID, "name": "events", "format": "CSV", "fields": COLS,
                 "field_types": {}, "total": 1, "file": None, "rows": 0}]
    author, recipes, _ = _verify_layout(
        tmp_path, monkeypatch, None, manifest,
        [{"name": "events", "by_id": RID, "required_columns": COLS}],
    )
    _, _, resources = author.load_local(DS, recipes)
    assert [r["id"] for r in resources] == [RID]
    assert "has no resource list" in capsys.readouterr().err


def test_verify_accepts_an_empty_optional_provider_table(tmp_path, monkeypatch):
    res = {"id": RID, "name": "table 3", "format": "CSV", "datastore_active": False,
           "params": {"optional": True}}
    manifest = [{"resource_id": RID, "name": "table 3", "format": "CSV", "fields": COLS,
                 "field_types": {}, "total": 0, "file": "1.csv", "rows": 0}]
    author, recipes, data = _verify_layout(
        tmp_path, monkeypatch, {"provider": "cbs_releases", "resources": [res]}, manifest,
        [{"name": "events", "by_id": RID, "required_columns": COLS}],
    )
    with open(data / "1.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(COLS)
    recipe, manifest, resources = author.load_local(DS, recipes)
    assert resources[0]["params"] == {"optional": True} and resources[0]["datastore_active"]
    ckan = author._LocalCkan(data, manifest)
    out = rf.fetch_inputs(recipe, resources, tmp_path / "work",
                          preview_fn=ckan.preview, fetch_fn=ckan.fetch)
    (part,) = out["events"]
    assert part.rows == 0
