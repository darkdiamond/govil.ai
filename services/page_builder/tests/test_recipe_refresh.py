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
        self.fetches = 0

    def preview(self, rid):
        return {
            "fields": [{"id": c} for c in self.cols],
            "total": len(self.rows),
            "sample_rows": [dict(zip(self.cols, r, strict=True)) for r in self.rows[:5]],
        }

    def fetch(self, rid, total, dest, **kw):
        assert kw["prefer_sample"] is False and kw["sample_target_rows"] == 0
        self.fetches += 1
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
                       agent_data, page_path, snapshot=None, input_fingerprint=None,
                       inputs_hash=None, content_hash=None, file_fingerprint=None,
                       preview=False):
        self._upd(dataset_id, preview, agent_data=agent_data,
                  recipe_version=recipe_version,
                  refreshed_metadata_modified=metadata_modified,
                  refresh_status="succeeded", refresh_failed_version=None,
                  authoring_status="done", authoring_reason=None, authoring_issue=None,
                  last_snapshot=snapshot, last_refreshed_at=datetime.now(timezone.utc),
                  input_fingerprint=input_fingerprint, inputs_hash=inputs_hash,
                  content_hash=content_hash, file_fingerprint=file_fingerprint)

    def mark_refresh_unchanged(self, dataset_id, *, metadata_modified, input_fingerprint,
                               inputs_hash=None, file_fingerprint=None, reason,
                               advance_version, preview=False):
        kw = {"input_fingerprint": input_fingerprint, "unchanged_reason": reason,
              "file_fingerprint": file_fingerprint}
        if inputs_hash is not None:
            kw["inputs_hash"] = inputs_hash
        if advance_version:
            kw.update(refreshed_metadata_modified=metadata_modified, refresh_status="succeeded",
                      refresh_failed_version=None, authoring_status="done",
                      authoring_reason=None, authoring_issue=None)
        self._upd(dataset_id, preview, **kw)

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
        resources=[{"id": RID, "name": "events", "format": "CSV", "datastore_active": True,
                    "hash": "md5-v1", "size": 1000}],
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

    def read_gcs(bucket, rel):
        return staged.get(rel)

    return SimpleNamespace(tmp=tmp_path, issues=issues, staged=staged,
                           write_gcs=write_gcs, read_gcs=read_gcs)


def _run(env, store, ckan, *, preview=True, recipes=FIXTURES, **kw):
    return rf.run_refresh(
        store, rf.LocalRecipeRepo(recipes), preview=preview, staging_bucket="bkt",
        work_root=env.tmp / "work", write_gcs=env.write_gcs, read_gcs=env.read_gcs,
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


def _flaky_sandbox(monkeypatch, stderr, fail_times):
    """Make the first `fail_times` sandbox runs exit -6 with `stderr`."""
    from services.page_builder import local_sandbox as ls

    real = ls.LocalSandbox.run_code
    calls = {"n": 0}

    def run_code(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            return ls._Execution(
                logs=ls._Logs(stdout="", stderr=stderr),
                error=ls._Error(name="NonZeroExit", value="exit code -6"),
            )
        return real(self, *a, **kw)

    monkeypatch.setattr(ls.LocalSandbox, "run_code", run_code)
    monkeypatch.setattr("services.page_builder.refresh._COMPUTE_SPAWN_BACKOFF_S", 0)
    return calls


GRPC_ABORT = "E1027 ev_epoll1_linux.cc:373] epoll_wait error: Bad file descriptor"


def test_compute_spawn_flake_is_retried(env, monkeypatch):
    calls = _flaky_sandbox(monkeypatch, GRPC_ABORT, fail_times=1)
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])))
    assert s["failed"] == [] and env.issues == []
    assert calls["n"] == 2


def test_compute_spawn_flake_gives_up_after_retry(env, monkeypatch):
    calls = _flaky_sandbox(monkeypatch, GRPC_ABORT, fail_times=99)
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])))
    assert s["outcomes"][0]["reason"] == "recipe_failed"
    assert calls["n"] == 2


def test_bare_sigabrt_is_not_retried(env, monkeypatch):
    calls = _flaky_sandbox(monkeypatch, "Aborted", fail_times=99)
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])))
    assert s["outcomes"][0]["reason"] == "recipe_failed"
    assert calls["n"] == 1


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


def test_percent_conflict_skipped_only_for_recipe_renders(tmp_path):
    """Recipe numbers are recomputed nightly, so a coincidental equal % in
    two different years must not fail a correct refresh — but the agent path
    keeps the rule."""
    from services.page_builder.agent_contract import run_host_check

    body = (
        '<h1>t</h1><section class="card p-5 mb-6"><div class="flex items-center gap-2 mb-3 '
        'text-brand"><img src="/icons/info.svg" alt="" class="w-5 h-5" /><h2>תקציר</h2>'
        "</div><p>ב-2019 השיעור היה 45.2%.</p>" + "<p>" + "מילוי " * 20 + "</p>"
        "<p>ב-2024 השיעור היה 45.2%.</p></section>"
    )
    ad = json.dumps({"summary_he": "x", "dataset_kind": "misc", "suggested_tags": ["a"]})
    run_host_check(body, ad, tmp_path, recipe=True)
    with pytest.raises(RuntimeError, match="PERCENT-CONFLICT"):
        run_host_check(body, ad, tmp_path)


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


def test_em_dash_lint(tmp_path):
    from services.page_builder import author

    D = "\u2014"  # em dash, spelled as an escape so this file stays free of it

    shutil.copytree(FIXTURES / DS, tmp_path / DS)
    recipe = Recipe.load(tmp_path / DS)
    assert author._em_dash_findings(recipe) == []

    c = tmp_path / DS / "compute.py"
    src = (f'"""doc {D} ok"""\n# comment {D} ok\n'
           'MATCH = "\\u2014"  # escaped: the opt-out for matching data\n'
           'ENTITY = "x &mdash; y"\n'
           + c.read_text(encoding="utf-8").replace("אירועים, {word}", f"אירועים {D} {{word}}"))
    c.write_text(src, encoding="utf-8")
    bad_py = next(n for n, line in enumerate(src.splitlines(), 1) if f"אירועים {D} {{word}}" in line)
    t = tmp_path / DS / "template.html.j2"
    base = t.read_text(encoding="utf-8").rstrip("\n")
    tail = (f"{{# note {D} ok #}}<!-- html {D} ok -->\n"
            f"<script>/* block {D} ok\n spans lines */\n"
            f"var ok = 1; // js {D} ok\n"
            f'var s = "a // b {D} c";\n'     # inside a JS string: flagged
            "</script>\n"
            "<p>א &mdash; ב</p>\n")         # entity: flagged
    t.write_text(base + "\n" + tail, encoding="utf-8")
    first = base.count("\n") + 2
    findings = author._em_dash_findings(Recipe.load(tmp_path / DS))
    py = sorted(f for f in findings if f.startswith("EM-DASH: compute.py:"))
    assert py == sorted(f"EM-DASH: compute.py:{n} has an em dash (U+2014) in a string literal"
                        for n in (4, bad_py)), findings
    tpl = sorted(f for f in findings if f.startswith("EM-DASH: template.html.j2:"))
    assert tpl == sorted(f"EM-DASH: template.html.j2:{first + k} has an em dash (U+2014)"
                         for k in (4, 6)), findings


def test_author_verify_requires_fallback_and_coverage(tmp_path, monkeypatch, capsys):
    author = _prepared(tmp_path, monkeypatch, _rows([2023, 2024, 2025]))
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    t = recipes / DS / "template.html.j2"
    # Unmark the districts chart → it has neither a table nor the explorer
    # marker; and a per-chart data.gov.il link is rejected outright.
    t.write_text(t.read_text(encoding="utf-8").replace(
        ' data-fallback="explorer"', "").replace(
        "</h1>", '</h1><p><a href="https://data.gov.il/dataset/x">data.gov.il</a></p>', 1),
        encoding="utf-8")
    cov = recipes / DS / "coverage.json"
    data = json.loads(cov.read_text(encoding="utf-8"))
    del data["events.חודש"]
    data["events.מחוז"] = "chart-nope"
    cov.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    data["events.שנה"] = "chart-yearly, kpi:no_such_kpi"
    data["events.typo"] = "chart-yearly"
    cov.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert author.verify(DS, recipes) == 1
    out = capsys.readouterr().out
    assert "NO-FALLBACK: chart #chart-districts" in out
    assert "SOURCE-LINK: page links to data.gov.il" in out
    assert "events.חודש" in out and "'chart-nope' is not an element id" in out
    assert "'kpi:no_such_kpi': the model has no such KPI" in out
    assert "(typo or stale): events.typo" in out


def _kpi(value, cls="text-brand", ltr=True):
    d = ' dir="ltr"' if ltr else ""
    return f'<div class="text-3xl font-bold {cls} mb-1"{d}>{value}</div>'


@pytest.mark.parametrize("html, problem", [
    (_kpi("1,695", ltr=False), None),            # bare count: no dir needed
    (_kpi("−213.72"), None),
    (_kpi("432.9 מ׳"), None),                    # short magnitude suffix
    (_kpi("45.2%", "text-danger"), None),
    (_kpi("2014–2026", ltr=False), 'needs dir="ltr"'),
    (_kpi("-6.3%"), "minus sign"),
    (_kpi("⁦-213.72⁩ מ'"), "bidi marks"),
    (_kpi("432.9 מיליון ₪"), "carries a unit"),
    (_kpi("1,567", "text-ink"), "colour must be"),
    (_kpi("+0.76%", ltr=False), 'needs dir="ltr"'),       # leading plus flips in RTL
    # Class order and size don't let a value escape the check.
    ('<div class="font-bold text-brand text-4xl">432.9 מיליון ₪</div>', "carries a unit"),
])
def test_kpi_format(html, problem):
    from services.page_builder.recipe import kpi_format_findings

    out = kpi_format_findings(html)
    assert (not out) if problem is None else any(problem in f for f in out), out


def test_kpi_tone_is_validated_at_refresh():
    """A tone outside the palette fails the page model (so the refresh keeps
    the old page) instead of rendering an uncoloured text-<typo> KPI."""
    raw = {"agent_data": {"summary_he": "x", "dataset_kind": "misc", "suggested_tags": ["a"]},
           "kpis": {"k": {"display": "1", "tone": "good"}}}
    m = RecipeManifest.model_validate({
        "dataset_id": DS, "recipe_version": 1, "authored_at": "2026-10-24T00:00:00Z",
        "inputs": [{"name": "x", "by_id": RID}], "min_insights": 0})
    from services.page_builder.recipe import validate_model

    with pytest.raises(RecipeError):
        validate_model(raw, m)
    raw["kpis"]["k"]["tone"] = "danger"
    validate_model(raw, m)


def test_refresh_reports_kpi_format_drift(env, tmp_path):
    """A display that drifts out of house style on new data is reported on
    the snapshot (page still ships), not silently published."""
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    t = recipes / DS / "template.html.j2"
    t.write_text(t.read_text(encoding="utf-8").replace(
        "{{ model.kpis.total.display }}", "{{ model.kpis.total.display }} ₪"), encoding="utf-8")
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), recipes=recipes)
    assert s["refreshed"] == [DS]
    warnings = store.states[(DS, True)]["last_snapshot"]["warnings"]
    assert any("carries a unit" in w for w in warnings)


@pytest.mark.parametrize("line, impure", [
    ('t = pd.Timestamp("today")', True),
    ('pd.to_datetime("now")', True),
    ('os.getenv("X")', True),
    ('Path("lookup.csv").read_text()', True),
    ('pd.read_csv("side.csv")', True),
    ("import requests", True),
    ('rules = [("requests", f(x))]', False),
    ('pd.to_datetime(df["d"], errors="coerce")', False),
])
def test_purity_lint(line, impure):
    from services.page_builder.author import _IMPURE_RE

    assert bool(_IMPURE_RE.search(line)) is impure


def test_fallback_check_rules():
    from services.page_builder.author import _fallback_findings

    tbl = "<details><table><tr><td>x</td></tr></table></details>"
    # A heatmap id is a chart like any other — no "map" exemption.
    assert _fallback_findings('<section><div id="chart-heatmap" role="img"></div></section>')
    # A chart outside any section can't borrow the previous section's table.
    html = f'<section>{tbl}</section><div class="grid"><div id="c2" role="img"></div></div><section></section>'
    assert any("#c2" in f for f in _fallback_findings(html))
    # GovMap containers (no role="img") are not charts.
    assert _fallback_findings('<section><div id="map-main"></div></section>') == []
    assert _fallback_findings(f'<section><div id="c1" role="img"></div>{tbl}</section>') == []
    # A large series opts into the shell's explorer explicitly.
    assert _fallback_findings(
        '<section><div id="c3" role="img" data-fallback="explorer"></div></section>') == []


def test_coverage_requires_unused_resources(tmp_path, monkeypatch, capsys):
    author = _prepared(tmp_path, monkeypatch, _rows([2023, 2024, 2025]))
    m = tmp_path / "authoring" / DS / "data" / "manifest.json"
    man = json.loads(m.read_text())
    man.append({**man[0], "resource_id": "bbbbbbbb-0000-0000-0000-000000000002", "file": None})
    m.write_text(json.dumps(man))
    assert author.verify(DS, FIXTURES) == 1
    assert "resource:bbbbbbbb-0000-0000-0000-000000000002" in capsys.readouterr().out


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


# ── REFRESH_PRECHECK: skip CKAN bumps that changed nothing ───────────────


def _bump(store, mm):
    store.src.metadata_modified = datetime.fromisoformat(mm).replace(tzinfo=timezone.utc)


def _first(s):
    return s["outcomes"][0]


def _with_mode(monkeypatch, mode):
    monkeypatch.setenv("REFRESH_PRECHECK", mode)


def _stage_then_bump_same_rows(env, monkeypatch, mode, **kw):
    """Render once, then CKAN bumps the version with byte-identical data."""
    _with_mode(monkeypatch, mode)
    store = FakeStore(_src("2026-10-01"))
    ckan = FakeCkan(_rows([2024, 2025]))
    s1 = _run(env, store, ckan, preview=False, **kw)
    assert _first(s1)["status"] == "refreshed"
    staged = dict(env.staged)
    _bump(store, "2026-10-02")
    return store, ckan, staged


def test_precheck_off_rerenders_identical_data(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "off")
    s = _run(env, store, ckan, preview=False)
    assert _first(s)["status"] == "refreshed" and ckan.fetches == 2
    assert _first(s)["precheck"] == {}
    st = store.states[(DS, False)]
    assert st["input_fingerprint"] is None and st["content_hash"] is None


def test_precheck_unknown_mode_is_off(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "bogus")
    s = _run(env, store, ckan, preview=False)
    assert _first(s)["status"] == "refreshed" and _first(s)["precheck"] == {}


def test_precheck_observe_reports_agreement_and_never_skips(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "observe")
    # first render had nothing to compare against
    s = _run(env, store, ckan, preview=False)
    o = _first(s)
    assert o["status"] == "refreshed" and ckan.fetches == 2
    assert o["precheck"] == {
        "mode": "observe", "fp_same": True, "inputs_same": True, "content_same": True,
        "fp2_same": True,
    }


def test_precheck_first_run_has_nothing_to_compare(env, monkeypatch):
    _with_mode(monkeypatch, "observe")
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), preview=False)
    pc = _first(s)["precheck"]
    assert pc["fp_same"] is None and pc["inputs_same"] is None and pc["content_same"] is None
    assert pc["fp2_same"] is None
    st = store.states[(DS, False)]
    assert st["input_fingerprint"] and st["inputs_hash"] and st["content_hash"]
    assert st["file_fingerprint"]


def test_precheck_inputs_skips_after_fetch_and_before_compute(env, monkeypatch):
    store, ckan, staged = _stage_then_bump_same_rows(env, monkeypatch, "inputs")
    env.staged.clear()
    s = _run(env, store, ckan, preview=False)
    o = _first(s)
    assert (o["status"], o["reason"]) == ("unchanged", "inputs_hash")
    assert ckan.fetches == 2          # B needs the export…
    assert env.staged == {}           # …but nothing was re-rendered or staged
    assert s["refreshed"] == [] and s["unchanged"] == [DS]
    st = store.states[(DS, False)]
    assert st["refreshed_metadata_modified"] == store.src.metadata_modified
    # the marker advanced, so the next run has nothing to do
    assert _first(_run(env, store, ckan, preview=False))["reason"] == "up_to_date"


def test_precheck_full_skips_on_fingerprint_without_fetching(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "full")
    rendered_mm = store.states[(DS, False)]["refreshed_metadata_modified"]
    env.staged.clear()
    s = _run(env, store, ckan, preview=False)
    o = _first(s)
    assert (o["status"], o["reason"]) == ("unchanged", "fingerprint")
    assert ckan.fetches == 1 and env.staged == {}
    # not proof: the bump stays pending and is re-probed (no fetch) next run
    assert store.states[(DS, False)]["refreshed_metadata_modified"] == rendered_mm
    assert _first(_run(env, store, ckan, preview=False))["reason"] == "fingerprint"
    assert ckan.fetches == 1


def test_precheck_fingerprint_blind_spot_is_bounded_without_new_bumps(env, monkeypatch):
    """A same-count edit A can't see, and CKAN never bumps again: the pending
    bump still re-renders once the page passes the max age."""
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "full")
    edited = FakeCkan(_deep_edit(ckan.rows))
    assert _first(_run(env, store, edited, preview=False))["reason"] == "fingerprint"
    store.states[(DS, False)]["last_refreshed_at"] = datetime(2020, 1, 1, tzinfo=timezone.utc)
    s = _run(env, store, edited, preview=False)        # no new bump
    assert _first(s)["status"] == "refreshed" and edited.fetches == 1


def test_precheck_exact_skip_settles_an_open_authoring_flag(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "inputs")
    store.states[(DS, False)].update(authoring_status="notified", authoring_issue=77,
                                     refresh_failed_version="x", refresh_status="failed")
    assert _first(_run(env, store, ckan, preview=False))["reason"] == "inputs_hash"
    st = store.states[(DS, False)]
    assert st["authoring_status"] == "done" and st["refresh_status"] == "succeeded"


def _deep_edit(rows):
    """Same row count, same first 5 rows, one number changed near the end —
    the edit check A cannot see."""
    out = [list(r) for r in rows]
    out[-2][-1] = str(int(out[-2][-1]) + 100)
    return out


def test_precheck_inputs_mode_catches_what_the_fingerprint_misses(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "inputs")
    edited = FakeCkan(_deep_edit(ckan.rows))
    s = _run(env, store, edited, preview=False)
    o = _first(s)
    assert o["status"] == "refreshed"
    assert o["precheck"]["fp_same"] is True       # A would have skipped…
    assert o["precheck"]["inputs_same"] is False  # …B knows better
    assert o["precheck"]["content_same"] is False


def _reupload(store, md5):
    """A new file upload: CKAN recomputes the resource's md5."""
    store.src.resources = [dict(r, hash=md5) for r in store.src.resources]


def test_precheck_file_fingerprint_catches_what_the_fingerprint_misses(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "observe")
    _reupload(store, "md5-v2")
    o = _first(_run(env, store, FakeCkan(_deep_edit(ckan.rows)), preview=False))
    assert o["status"] == "refreshed"
    assert o["precheck"]["fp_same"] is True       # A is fooled…
    assert o["precheck"]["fp2_same"] is False     # …A′ sees the new file
    assert o["precheck"]["content_same"] is False


def test_precheck_file_fingerprint_survives_identical_reupload(env, monkeypatch):
    """A byte-identical re-upload bumps metadata_modified but not the md5."""
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "observe")
    pc = _first(_run(env, store, ckan, preview=False))["precheck"]
    assert pc["fp2_same"] is True and pc["content_same"] is True


def test_precheck_file_fingerprint_reports_datastore_only_edit(env, monkeypatch, caplog):
    """The datastore changed without a new file (API push, failed reload): A′
    is blind to it, and observe must say so — the rollout gate for A′."""
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "observe")
    with caplog.at_level("WARNING", logger=rf.log.name):
        o = _first(_run(env, store, FakeCkan(_deep_edit(ckan.rows)), preview=False))
    assert o["precheck"]["fp2_same"] is True and o["precheck"]["content_same"] is False
    assert "FALSE-SKIP candidate — fp_same ∧ fp2_same" in caplog.text


def test_precheck_fingerprint_alone_is_not_a_false_skip(env, monkeypatch, caplog):
    """A fooled but A′ not: no mode skips on that, so the gate stays quiet."""
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "observe")
    _reupload(store, "md5-v2")
    with caplog.at_level("WARNING", logger=rf.log.name):
        o = _first(_run(env, store, FakeCkan(_deep_edit(ckan.rows)), preview=False))
    assert o["precheck"]["fp_same"] is True and o["precheck"]["content_same"] is False
    assert "FALSE-SKIP" not in caplog.text


def test_precheck_inputs_skip_seeds_the_file_fingerprint(env, monkeypatch):
    """A source rendered before A′ existed: the first exact skip stores A′, so
    the next bump under `full` skips without fetching."""
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "inputs")
    store.states[(DS, False)]["file_fingerprint"] = None
    assert _first(_run(env, store, ckan, preview=False))["reason"] == "inputs_hash"
    assert store.states[(DS, False)]["file_fingerprint"]
    _with_mode(monkeypatch, "full")
    _bump(store, "2026-10-03")
    assert _first(_run(env, store, ckan, preview=False))["reason"] == "fingerprint"
    assert ckan.fetches == 2


def test_precheck_file_fingerprint_needs_every_hash(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "observe")
    _reupload(store, None)
    o = _first(_run(env, store, ckan, preview=False))
    assert o["status"] == "refreshed" and o["precheck"]["fp2_same"] is None
    assert store.states[(DS, False)]["file_fingerprint"] is None


def test_precheck_full_fetches_when_only_the_file_hash_changed(env, monkeypatch):
    """The ~5/night A false skips: same count, same first rows, new file."""
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "full")
    _reupload(store, "md5-v2")
    edited = FakeCkan(_deep_edit(ckan.rows))
    o = _first(_run(env, store, edited, preview=False))
    assert o["status"] == "refreshed" and edited.fetches == 1
    assert o["precheck"]["fp_same"] is True and o["precheck"]["fp2_same"] is False


def test_precheck_full_without_file_hash_falls_back_to_inputs_hash(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "full")
    _reupload(store, None)
    o = _first(_run(env, store, ckan, preview=False))
    assert (o["status"], o["reason"]) == ("unchanged", "inputs_hash")
    assert ckan.fetches == 2          # no hash → no fingerprint skip; B decided


def test_precheck_full_documents_the_fingerprint_blind_spot(env, monkeypatch):
    """`full` trusts A ∧ A′: a datastore-only same-count edit (file md5
    unchanged) is skipped until the max-age safety net forces a re-render."""
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "full")
    edited = FakeCkan(_deep_edit(ckan.rows))
    assert _first(_run(env, store, edited, preview=False))["reason"] == "fingerprint"
    # …and the safety net: page older than the max age → always re-render
    store.states[(DS, False)]["last_refreshed_at"] = datetime(2020, 1, 1, tzinfo=timezone.utc)
    _bump(store, "2026-10-03")
    s = _run(env, store, edited, preview=False)
    assert _first(s)["status"] == "refreshed" and edited.fetches == 1


def test_precheck_changed_rows_always_refresh(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "full")
    more = FakeCkan(_rows([2024, 2025, 2026]))
    s = _run(env, store, more, preview=False)
    assert _first(s)["status"] == "refreshed" and more.fetches == 1


def test_precheck_never_skips_a_recipe_version_change(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "full")
    store.states[(DS, False)]["recipe_version"] = 0   # recipe moved on
    s = _run(env, store, ckan, preview=False)
    o = _first(s)
    assert o["status"] == "refreshed" and o["trigger"] == "recipe_version"


def test_precheck_never_skips_a_forced_run(env, monkeypatch):
    store, ckan, _ = _stage_then_bump_same_rows(env, monkeypatch, "full")
    s = _run(env, store, ckan, preview=False, force=True)
    assert _first(s)["status"] == "refreshed"


def test_precheck_edited_recipe_without_version_bump_rerenders(env, monkeypatch, tmp_path):
    _with_mode(monkeypatch, "full")
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    store = FakeStore(_src("2026-10-01"))
    ckan = FakeCkan(_rows([2024, 2025]))
    _run(env, store, ckan, preview=False, recipes=recipes)
    t = recipes / DS / "template.html.j2"
    t.write_text(t.read_text() + "\n<!-- edited -->\n")
    _bump(store, "2026-10-02")
    s = _run(env, store, ckan, preview=False, recipes=recipes)
    assert _first(s)["status"] == "refreshed"


def test_unchanged_by_fingerprint_does_not_spend_the_cap():
    mk = rf.RefreshOutcome
    assert not rf._spends_cap(mk("a", "unchanged", reason="fingerprint"))
    assert rf._spends_cap(mk("a", "unchanged", reason="inputs_hash"))
    assert rf._spends_cap(mk("a", "refreshed"))
    assert rf._spends_cap(mk("a", "failed"))
    assert not rf._spends_cap(mk("a", "skipped"))


# ---- queue_authoring: issue dedup -----------------------------------------


@pytest.mark.parametrize("state,reused", [("open", True), ("not_planned", True),
                                          (None, True), ("completed", False)])
def test_queue_authoring_reuses_issue_unless_closed_completed(env, monkeypatch, state, reused):
    """Completed = a recipe PR closed it, so a later need is new work and gets
    its own issue. Open / won't-author / unreadable keep the recorded one."""
    monkeypatch.setattr("services.page_builder.notify.issue_state", lambda n: state)
    store = FakeStore(_src())
    store.states[(DS, False)] = {"authoring_status": "notified", "authoring_issue": 5}
    number = rf.queue_authoring(store, store.src, "recipe_failed")
    st = store.states[(DS, False)]
    assert number == (5 if reused else 77)
    assert st["authoring_issue"] == number and st["authoring_status"] == "notified"
    assert len(env.issues) == (0 if reused else 1)


def test_successful_refresh_clears_the_recorded_issue(env):
    store = FakeStore(_src())
    store.states[(DS, True)] = {"authoring_status": "notified", "authoring_issue": 5}
    assert _run(env, store, FakeCkan(_rows([2024, 2025])))["refreshed"] == [DS]
    assert store.states[(DS, True)]["authoring_issue"] is None


# ---- staging failures -------------------------------------------------------


class _MultiStore(FakeStore):
    """FakeStore over several sources (ids → the same fixture recipe)."""

    def __init__(self, ids):
        super().__init__(_src())
        self.srcs = {i: SimpleNamespace(**{**vars(_src()), "id": i}) for i in ids}

    def get_source(self, dataset_id):
        return self.srcs.get(dataset_id)


def _many_recipes(tmp_path, ids):
    recipes = tmp_path / "recipes"
    for i in ids:
        shutil.copytree(FIXTURES / DS, recipes / i)
        m = recipes / i / "recipe.json"
        m.write_text(m.read_text().replace(DS, i))
    return recipes


def test_staging_failure_fails_one_source_and_the_batch_goes_on(env, tmp_path):
    """An upload error used to escape run_refresh and drop every source after
    it for the night."""
    ids = [f"{n}1111111-2222-3333-4444-555555555555" for n in range(3)]
    store = _MultiStore(ids)

    def write_gcs(data, bucket, rel):
        if ids[0] in rel:
            raise RuntimeError("503 from GCS")
        env.staged[rel] = data
        return f"gs://{bucket}/{rel}"

    env.write_gcs = write_gcs
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), recipes=_many_recipes(tmp_path, ids))
    assert s["failed"] == [ids[0]] and s["refreshed"] == ids[1:]
    assert s["staging_down"] is False
    st = store.states[(ids[0], True)]
    assert st["refresh_reason"] == rf.STAGE_FAILED and env.issues == []
    # Not an authoring verdict: the next run retries it.
    assert rf.needs_refresh(store.srcs[ids[0]], st, rf.LocalRecipeRepo(
        _many_recipes(tmp_path / "again", ids[:1])).load(ids[0], tmp_path / "s")) is not None


def test_consecutive_staging_failures_stop_the_batch(env, tmp_path):
    ids = [f"{n}1111111-2222-3333-4444-555555555555" for n in range(5)]
    store = _MultiStore(ids)

    def write_gcs(data, bucket, rel):
        raise RuntimeError("bucket gone")

    env.write_gcs = write_gcs
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), recipes=_many_recipes(tmp_path, ids))
    assert s["staging_down"] is True
    assert len(s["failed"]) == rf.MAX_CONSECUTIVE_STAGE_FAILURES
    assert [o["reason"] for o in s["outcomes"]][rf.MAX_CONSECUTIVE_STAGE_FAILURES:] == [
        "staging_down"] * (5 - rf.MAX_CONSECUTIVE_STAGE_FAILURES)


def test_failed_firestore_mark_restores_the_last_good_body(env):
    """Upload landed, mark didn't: the staged body must go back to the one
    Firestore's agent_data still describes."""
    store = FakeStore(_src())
    _run(env, store, FakeCkan(_rows([2024, 2025])))
    rel, good = next(iter(env.staged.items()))

    store.src = _src("2026-11-01")

    def boom(*a, **k):
        raise RuntimeError("firestore unavailable")

    store.mark_refreshed = boom
    s = _run(env, store, FakeCkan(_rows([2024, 2025, 2026])))
    assert s["outcomes"][0]["reason"] == rf.STAGE_FAILED
    assert env.staged[rel] == good


def test_unloadable_recipe_queues_authoring(env, tmp_path):
    """With recipes the only page path, a broken recipe on main must surface
    as an issue, not freeze the page silently."""
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    (recipes / DS / "recipe.json").write_text("{not json")
    store = FakeStore(_src())
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), recipes=recipes)
    assert s["outcomes"][0]["reason"] == "recipe_invalid"
    assert s["outcomes"][0]["issue"] == 77 and env.issues[0]["reason"] == "recipe_failed"


def test_queue_error_mid_batch_does_not_stop_the_refresh(env, tmp_path, monkeypatch):
    ids = [f"{n}1111111-2222-3333-4444-555555555555" for n in range(2)]
    store = _MultiStore(ids)
    recipes = _many_recipes(tmp_path, ids)
    (recipes / ids[0] / "recipe.json").write_text("{not json")

    def _boom(*a, **k):
        raise RuntimeError("github down")

    monkeypatch.setattr(rf, "queue_authoring", _boom)
    s = _run(env, store, FakeCkan(_rows([2024, 2025])), recipes=recipes)
    assert s["refreshed"] == [ids[1]]


def test_unreadable_previous_body_does_not_fail_the_render(env):
    store = FakeStore(_src())

    def _boom(bucket, rel):
        raise RuntimeError("403 get")

    env.read_gcs = _boom
    assert _run(env, store, FakeCkan(_rows([2024, 2025])))["refreshed"] == [DS]
