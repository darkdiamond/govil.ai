"""Recipe contract + deterministic refresh, end to end on a fixture recipe.

compute() runs for real (LocalSandbox subprocess, pandas) and the rendered
page goes through the real sanitizer + check.py — only CKAN, GCS and
Firestore are faked.
"""
from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.page_builder import refresh as rf
from services.page_builder.agent_contract import FetchOutcome
from services.page_builder.recipe import (
    Recipe,
    RecipeError,
    RecipeManifest,
    lint_template,
    render_template,
)

FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
DS = "11111111-2222-3333-4444-555555555555"
RID = "aaaaaaaa-0000-0000-0000-000000000001"
COLS = ["שנה", "חודש", "מחוז", "מספר אירועים"]


def _rows(years, *, north=10, south=5, center=20):
    out = []
    for y in years:
        for m in range(1, 13):
            bump = 7 if m == 8 else 0
            out += [
                [str(y), str(m), "צפון", str(north + bump + (y - years[0]))],
                [str(y), str(m), "דרום", str(south)],
                [str(y), str(m), "מרכז", str(center + bump)],
            ]
    return out


class FakeCkan:
    def __init__(self, rows, cols=COLS):
        self.rows, self.cols = rows, cols

    def preview(self, rid):
        return {"fields": [{"id": c} for c in self.cols], "total": len(self.rows)}

    def fetch(self, rid, total, dest, **kw):
        assert kw["prefer_sample"] is False and kw["sample_target_rows"] == 0
        with open(dest, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(self.cols)
            w.writerows(self.rows)
        return FetchOutcome(rows=len(self.rows), bytes=dest.stat().st_size, mode="full")


class FakeStore:
    def __init__(self, src):
        self.src = src
        self.states: dict[tuple[str, bool], dict] = {}

    def get_source(self, dataset_id):
        return self.src if dataset_id == self.src.id else None

    def get_refresh_state(self, dataset_id, *, preview=False):
        return dict(self.states.get((dataset_id, preview), {}))

    def _upd(self, dataset_id, preview, **kw):
        self.states.setdefault((dataset_id, preview), {}).update(kw)

    def mark_refreshed(self, dataset_id, *, metadata_modified, recipe_version,
                       agent_data, page_path, snapshot=None, preview=False):
        self._upd(dataset_id, preview, agent_data=agent_data,
                  recipe_version=recipe_version,
                  refreshed_metadata_modified=metadata_modified,
                  refresh_status="succeeded", refresh_failed_version=None,
                  last_snapshot=snapshot)

    def mark_refresh_failed(self, dataset_id, *, error, reason, failed_version, preview=False):
        self._upd(dataset_id, preview, refresh_status="failed", refresh_error=error,
                  refresh_reason=reason, refresh_failed_version=failed_version)

    def mark_authoring_needed(self, dataset_id, reason, *, preview=False):
        self._upd(dataset_id, preview, authoring_status="needed", authoring_reason=reason)

    def set_authoring_issue(self, dataset_id, number, *, preview=False):
        self._upd(dataset_id, preview, authoring_status="notified", authoring_issue=number)


def _src(mm="2026-10-01"):
    return SimpleNamespace(
        id=DS, title="אירועים", organization={"title": "משרד"},
        metadata_modified=datetime.fromisoformat(mm).replace(tzinfo=timezone.utc),
        analysis_status="succeeded",
        resources=[{"id": RID, "name": "events", "format": "CSV", "datastore_active": True}],
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    issues = []
    monkeypatch.setattr(
        "services.page_builder.notify.open_authoring_issue",
        lambda **kw: issues.append(kw) or 77,
    )
    staged: dict[str, bytes] = {}

    def write_gcs(data, bucket, rel):
        staged[rel] = data
        return f"gs://{bucket}/{rel}"

    return SimpleNamespace(tmp=tmp_path, issues=issues, staged=staged, write_gcs=write_gcs)


def _run(env, store, ckan, *, preview=True, recipes=FIXTURES, **kw):
    return rf.run_refresh(
        store, rf.LocalRecipeRepo(recipes), preview=preview, staging_bucket="bkt",
        work_root=env.tmp / "work", write_gcs=env.write_gcs,
        preview_fn=ckan.preview, fetch_fn=ckan.fetch, **kw,
    )


# ── contract ─────────────────────────────────────────────────────────────


def test_fixture_recipe_loads():
    r = Recipe.load(FIXTURES / DS)
    assert r.manifest.inputs[0].by_id == RID


def test_manifest_requires_one_selector():
    with pytest.raises(ValueError):
        RecipeManifest.model_validate({
            "dataset_id": DS, "recipe_version": 1, "authored_at": "2026-10-24T00:00:00Z",
            "inputs": [{"name": "x", "by_id": RID, "by_schema": ["a"], "concat": True}],
        })
    with pytest.raises(ValueError):
        RecipeManifest.model_validate({
            "dataset_id": DS, "recipe_version": 1, "authored_at": "2026-10-24T00:00:00Z",
            "inputs": [{"name": "x", "by_schema": ["a"]}],  # concat missing
        })


def test_fixture_template_is_lint_clean():
    src = (FIXTURES / DS / "template.html.j2").read_text(encoding="utf-8")
    assert lint_template(src) == []


@pytest.mark.parametrize("bad, needle", [
    ("<p>נרשמו 1,695 אירועים</p>", "1,695"),
    ('<div aria-label="שיא ב-2019"></div>', "aria-label"),
    ("<script>var v = [1, 2, 3, 4, 5];</script>", "literal data array"),
])
def test_lint_flags_frozen_numbers(bad, needle):
    findings = lint_template(bad)
    assert findings and needle in findings[0]


def test_lint_allowlist():
    assert lint_template("<p>שירות 24/7</p>", allow=["24/7"]) == []


def test_tojson_keeps_order_and_hebrew():
    out = render_template("{{ model.m | tojson }}", {"m": {"צפון": 1, "אלף": 2}})
    assert out == '{"צפון": 1, "אלף": 2}'


def test_render_strict_undefined():
    with pytest.raises(RecipeError):
        render_template("{{ model.kpis.missing.display }}", {"kpis": {}})


# ── refresh ──────────────────────────────────────────────────────────────


def test_refresh_renders_valid_page_and_insights_follow_data(env):
    store = FakeStore(_src())
    s1 = _run(env, store, FakeCkan(_rows([2024, 2025])))
    assert s1["refreshed"] == [DS], s1
    html1 = env.staged[f"preview/datasets/{DS}/content.html"].decode()
    assert "עלייה" in html1  # צפון grows every year → total rises
    assert "{{" not in html1 and "model." not in html1

    # New CKAN version: the north collapses. Same recipe, no LLM — the
    # trend insight must flip its wording and the KPI must move.
    store.src = _src("2026-11-01")
    v2 = _rows([2024, 2025]) + _rows([2026], north=1, south=1, center=1)
    s2 = _run(env, store, FakeCkan(v2))
    assert s2["refreshed"] == [DS], s2
    html2 = env.staged[f"preview/datasets/{DS}/content.html"].decode()
    assert "ירידה" in html2 and "עלייה" not in html2
    out = s2["outcomes"][0]
    assert out["changes"]["kpis_changed"]["total"][0] != out["changes"]["kpis_changed"]["total"][1]
    assert out["changes"]["insights_removed"]


def test_preview_target_never_writes_prod_state(env):
    store = FakeStore(_src())
    _run(env, store, FakeCkan(_rows([2024, 2025])))
    assert (DS, True) in store.states and (DS, False) not in store.states
    assert all(k.startswith("preview/") for k in env.staged)


def test_prod_target_stages_live_path(env):
    store = FakeStore(_src())
    _run(env, store, FakeCkan(_rows([2024, 2025])), preview=False)
    assert f"datasets/{DS}/content.html" in env.staged
    assert store.states[(DS, False)]["refresh_status"] == "succeeded"


def test_up_to_date_is_skipped(env):
    store = FakeStore(_src())
    ckan = FakeCkan(_rows([2024, 2025]))
    _run(env, store, ckan)
    s = _run(env, store, ckan)
    assert s["refreshed"] == [] and s["outcomes"][0]["reason"] == "up_to_date"


def test_schema_change_keeps_page_and_opens_issue_once(env):
    store = FakeStore(_src())
    _run(env, store, FakeCkan(_rows([2024, 2025])))
    staged_before = dict(env.staged)

    store.src = _src("2026-11-01")
    renamed = [c if c != "מחוז" else "אזור" for c in COLS]
    s = _run(env, store, FakeCkan(_rows([2024, 2025]), cols=renamed))
    assert s["failed"] == [DS]
    assert s["outcomes"][0]["reason"] == "schema_changed"
    assert env.staged == staged_before  # last-good page untouched
    assert len(env.issues) == 1 and env.issues[0]["reason"] == "schema_changed"

    # Same data + same recipe → not retried (deterministic failure), no 2nd issue.
    s = _run(env, store, FakeCkan(_rows([2024, 2025]), cols=renamed))
    assert s["outcomes"][0]["reason"] == "up_to_date"
    assert len(env.issues) == 1


def test_too_few_insights_fails(env, tmp_path):
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    m = recipes / DS / "recipe.json"
    m.write_text(m.read_text().replace('"min_insights": 2', '"min_insights": 5'))
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), recipes=recipes)
    assert s["failed"] == [DS] and "min_insights" in s["outcomes"][0]["error"]


def test_compute_crash_is_a_recipe_failure(env, tmp_path):
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    (recipes / DS / "compute.py").write_text("def compute(frames):\n    raise ValueError('boom')\n")
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), recipes=recipes)
    assert s["outcomes"][0]["reason"] == "recipe_failed"
    assert "boom" in s["outcomes"][0]["error"]


def test_over_cap_is_too_large(env, monkeypatch):
    monkeypatch.setenv("REFRESH_MAX_RECORDS", "10")
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])))
    assert s["outcomes"][0]["reason"] == "too_large"


def test_new_recipe_version_rerenders(env, tmp_path):
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    store = FakeStore(_src())
    ckan = FakeCkan(_rows([2024, 2025]))
    _run(env, store, ckan, recipes=recipes)
    m = recipes / DS / "recipe.json"
    m.write_text(m.read_text().replace('"recipe_version": 1', '"recipe_version": 2'))
    s = _run(env, store, ckan, recipes=recipes)
    assert s["outcomes"][0]["trigger"] == "recipe_version"


def test_unavailable_source_is_not_refreshed(env):
    src = _src()
    src.analysis_status = "unavailable"
    s = _run(env, FakeStore(src), FakeCkan(_rows([2024, 2025])))
    assert s["refreshed"] == []


# ── author verify ────────────────────────────────────────────────────────


def _prepared(tmp_path, monkeypatch, rows):
    from services.page_builder import author

    monkeypatch.setattr(author, "AUTHORING_ROOT", tmp_path / "authoring")
    monkeypatch.setattr(author, "PREVIEW_OUT_ROOT", tmp_path / "model_test")
    data = tmp_path / "authoring" / DS / "data"
    data.mkdir(parents=True)
    with open(data / "1.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(rows)
    (data / "manifest.json").write_text(json.dumps([{
        "resource_id": RID, "name": "events", "format": "CSV", "fields": COLS,
        "field_types": {}, "total": len(rows), "file": "1.csv", "rows": len(rows),
    }]))
    return author


def test_author_verify_passes_fixture(tmp_path, monkeypatch, capsys):
    author = _prepared(tmp_path, monkeypatch, _rows([2023, 2024, 2025]))
    assert author.verify(DS, FIXTURES) == 0, capsys.readouterr().out
    out = tmp_path / "model_test" / DS
    assert (out / "content.html").is_file() and (out / "agent_data.json").is_file()


def test_author_verify_rejects_order_dependent_recipe(tmp_path, monkeypatch, capsys):
    author = _prepared(tmp_path, monkeypatch, _rows([2023, 2024, 2025]))
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    c = recipes / DS / "compute.py"
    # "latest" = last CKAN row: correct only while CKAN keeps insertion order.
    c.write_text(c.read_text().replace(
        '"display": f"{y_min}–{y_max}"',
        '"display": str(frames["events"].iloc[-1]["חודש"])',
    ))
    assert author.verify(DS, recipes) == 1
    assert "ORDER-DEPENDENT" in capsys.readouterr().out
