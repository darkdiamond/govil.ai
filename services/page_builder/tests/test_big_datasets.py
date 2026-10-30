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
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from services.page_builder import agent_contract
from services.page_builder import refresh as rf
from services.page_builder.recipe import (
    Recipe,
    RecipeError,
    RecipeManifest,
    resolve_inputs,
)
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
    env,  # noqa: F401  (fixture)
)


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
         "last_modified": datetime(2021, 11, 10, tzinfo=timezone.utc)},
        {"id": "r-new", "name": "נכון ליום 2026", "format": "CSV", "datastore_active": True,
         "last_modified": "2026-09-06T06:14:33"},  # naive ISO string: read as UTC
        {"id": "r-none", "name": "ללא תאריך", "format": "CSV", "datastore_active": True,
         "last_modified": None},
        {"id": "r-other", "name": "אחר", "format": "CSV", "datastore_active": True,
         "last_modified": datetime(2027, 1, 1, tzinfo=timezone.utc)},
    ]


def test_latest_picks_newest_matching_snapshot():
    m = _manifest([{"name": "main", "by_schema": ["a"], "pick": "latest"}])
    fields = {"r-old": ["a", "b"], "r-new": ["a", "b"], "r-none": ["a"], "r-other": ["z"]}
    out = resolve_inputs(m, _snapshots(), fields.get)
    # r-other is newer but doesn't match the schema.
    assert [r["id"] for r in out["main"]] == ["r-new"]


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

    monkeypatch.setattr(agent_contract.urllib_request, "urlopen", fake)
    fields, _ = agent_contract._fetch_page("rid", 0, 10, 5.0, ["b", "a"])
    assert seen["fields"] == ["b", "a"] and fields == ["b", "a"]
    seen.clear()
    agent_contract._fetch_page("rid", 0, 10, 5.0)
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
        get_source=lambda i: SimpleNamespace(id=i, title=""),
        get_refresh_state=lambda i, preview=False: {},
    )
    s = rf.run_refresh(store, rf.LocalRecipeRepo(recipes), preview=True,
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
        get_source=lambda i: SimpleNamespace(id=i, title=""),
        get_refresh_state=lambda i, preview=False: {},
    )
    s = rf.run_refresh(store, rf.LocalRecipeRepo(recipes), preview=True, cap=1,
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

    monkeypatch.setattr(agent_contract.urllib_request, "urlopen", fake)
    agent_contract._fetch_page("rid", 0, 10, 5.0, ['סכום, ש"ח', "שנה"])
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
