"""Failures that repeat every run escalate: a required resource with no rows,
an export that fails every run, an unexpected exception, a check.py timeout
(test_recipe_refresh.py), a preview the WAF blocks. Also the staging streaks
(a GCS outage behind `unchanged` outcomes) and `by_schema` inputs that don't
wait on a resource that can't be one of their matches."""
from __future__ import annotations

import io
import json
from datetime import timedelta
from types import SimpleNamespace
from urllib import error as urllib_error

import pytest

from services.page_builder import refresh as rf
from services.page_builder.recipe import RecipeManifest
from services.page_builder.tests import test_refresh_hourly as _hourly
from services.page_builder.tests.test_recipe_refresh import (
    DS,
    FakeCkan,
    FakeStore,
    TimeoutCkan,
    _bump,
    _first,
    _rows,
    _run,
    _src,
)
from services.page_builder.tests.test_refresh_hourly import T0, KnobStore, _written
from services.shared.states import OutcomeStatus, RefreshState, StageStep

env = _hourly.env      # fixtures: faked issues + GCS,
clock = _hourly.clock  # and a settable rf._utcnow


class EmptyCkan(FakeCkan):
    """The resource's datastore answers with no rows."""

    def preview(self, rid):
        return {**super().preview(rid), "total": 0}


class NoExport(FakeCkan):
    """The full export fails every run (short, moved during the walk, or CKAN)."""

    def fetch(self, *a, **kw):
        return None


def _rendered_then_bumped(env, store_cls=FakeStore):
    store = store_cls(_src("2026-10-01"))
    assert _run(env, store, FakeCkan(_rows([2024, 2025])))["refreshed"] == [DS]
    _bump(store, "2026-11-01")
    return store


# ── repeat failures escalate ─────────────────────────────────────────────


@pytest.mark.parametrize("ckan_cls, strike, escalated, needle", [
    (EmptyCkan, "no_rows", "schema_changed", "has no rows"),
    (NoExport, "export_failed", "too_large", "full fetch of"),
])
def test_a_fetch_that_fails_every_run_escalates(env, monkeypatch, ckan_cls, strike,
                                                escalated, needle):
    monkeypatch.setenv("REFRESH_TRANSIENT_STRIKES", "3")
    store = _rendered_then_bumped(env)
    staged = dict(env.staged)
    ckan = ckan_cls(_rows([2024, 2025]))
    for n in (1, 2):
        o = _first(_run(env, store, ckan))
        assert o["reason"] == "fetch_failed" and o["retried"] is True  # still retried in-run
        assert store.states[DS]["transient_strikes"] == {strike: n}
    assert env.issues == []
    o = _first(_run(env, store, ckan))
    assert o["reason"] == escalated and "3 runs in a row" in o["error"]
    assert len(env.issues) == 1 and env.issues[0]["reason"] == escalated
    assert needle in env.issues[0]["detail"]  # a metadata-only message reaches the issue
    assert env.staged == staged  # the last-good page stays
    assert _first(_run(env, store, ckan))["reason"] == "up_to_date"  # locked


def test_a_growing_table_still_escalates(env, monkeypatch):
    """The data version moves every run (a table that grows during every
    export): the count must not restart on it."""
    monkeypatch.setenv("REFRESH_TRANSIENT_STRIKES", "3")
    store = _rendered_then_bumped(env)
    ckan = NoExport(_rows([2024, 2025]))
    reasons = []
    for day in (2, 3, 4):
        _bump(store, f"2026-11-0{day}")
        reasons.append(_first(_run(env, store, ckan))["reason"])
    assert reasons == ["fetch_failed", "fetch_failed", "too_large"]


def test_a_crash_that_repeats_escalates_to_recipe_failed(env, monkeypatch):
    monkeypatch.setenv("REFRESH_TRANSIENT_STRIKES", "3")
    store = _rendered_then_bumped(env)

    def boom(*a, **kw):
        raise KeyError("a code path this dataset's data always hits")

    monkeypatch.setattr(rf, "build_page", boom)
    ckan = FakeCkan(_rows([2024, 2025]))
    for n in (1, 2):
        o = _first(_run(env, store, ckan))
        assert o["reason"] == "error" and o["error"].startswith("KeyError")
        assert store.states[DS]["transient_strikes"] == {"error": n}
    o = _first(_run(env, store, ckan))
    assert o["reason"] == "recipe_failed" and "3 runs in a row" in o["error"]
    assert len(env.issues) == 1 and env.issues[0]["reason"] == "recipe_failed"
    assert _first(_run(env, store, ckan))["reason"] == "up_to_date"


def test_a_deploy_or_recipe_edit_restarts_code_scoped_counts(env, monkeypatch):
    monkeypatch.setenv("REFRESH_TRANSIENT_STRIKES", "3")
    store = _rendered_then_bumped(env)
    store.states[DS]["transient_strikes"] = {"download_blocked": 2}
    ckan = NoExport(_rows([2024, 2025]))
    for n in (1, 2):
        _first(_run(env, store, ckan))
        assert store.states[DS]["transient_strikes"] == {"download_blocked": 2,
                                                         "export_failed": n}
    # A builder deploy (or an edited recipe) moves the key's code part: the
    # export count starts over; a WAF count is not the code's to reset.
    monkeypatch.setattr(rf, "_builder_code_hash", lambda: "new-image")
    o = _first(_run(env, store, ckan))
    assert o["reason"] == "fetch_failed" and env.issues == []
    assert store.states[DS]["transient_strikes"] == {"download_blocked": 2, "export_failed": 1}


def test_code_part_of_the_lock_key():
    assert rf._code_part("2026-11-01T00:00:00+00:00|v3|abcd") == "v3|abcd"
    assert rf._code_part("none|v1") == "v1"
    assert rf._code_part(None) is None


def test_crash_strikes_respect_the_strike_window(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_STRIKE_MIN_HOURS", "72")
    monkeypatch.setenv("REFRESH_TRANSIENT_STRIKES", "3")
    store = _rendered_then_bumped(env, KnobStore)

    def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(rf, "build_page", boom)
    ckan = FakeCkan(_rows([2024, 2025]))
    for n in range(1, 6):
        clock.now = T0 + timedelta(hours=n - 1)
        assert _first(_run(env, store, ckan))["reason"] == "error"
        assert store.states[DS]["transient_strikes_since"] == {"error": T0}
    assert env.issues == []
    clock.now = T0 + timedelta(hours=72)
    assert _first(_run(env, store, ckan))["reason"] == "recipe_failed"
    assert len(env.issues) == 1


def test_a_restarted_count_restarts_its_window(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_STRIKE_MIN_HOURS", "72")
    store = _rendered_then_bumped(env, KnobStore)
    ckan = NoExport(_rows([2024, 2025]))
    _run(env, store, ckan)
    assert store.states[DS]["transient_strikes_since"] == {"export_failed": T0}
    monkeypatch.setattr(rf, "_builder_code_hash", lambda: "new-image")
    clock.now = T0 + timedelta(hours=100)
    _run(env, store, ckan)
    st = store.states[DS]
    assert st["transient_strikes"] == {"export_failed": 1}
    assert st["transient_strikes_since"] == {"export_failed": clock.now}


# ── a preview the WAF blocks ─────────────────────────────────────────────


def test_a_blocked_preview_escalates_to_download_blocked(env, monkeypatch):
    monkeypatch.setenv("REFRESH_TRANSIENT_STRIKES", "3")
    store = _rendered_then_bumped(env)
    asked = []
    slow = TimeoutCkan(_rows([2024, 2025]))
    kw = {"preview_blocked_fn": lambda rid: asked.append(rid) or True}
    for n in (1, 2):
        o = _first(_run(env, store, slow, **kw))
        assert o["reason"] == "fetch_failed" and "refused by the edge" in o["error"]
        assert store.states[DS]["transient_strikes"] == {"preview_blocked": n}
    o = _first(_run(env, store, slow, **kw))
    assert o["reason"] == "download_blocked"
    assert len(env.issues) == 1 and env.issues[0]["reason"] == "download_blocked"
    assert "HTTP 403" in env.issues[0]["detail"]
    assert set(asked) == {store.src.resources[0]["id"]}


@pytest.mark.parametrize("blocked_fn", [lambda rid: False, lambda rid: 1 / 0, None])
def test_an_unblocked_preview_failure_stays_preview_unavailable(env, monkeypatch, blocked_fn):
    store = _rendered_then_bumped(env)
    kw = {"preview_blocked_fn": blocked_fn} if blocked_fn else {}
    _run(env, store, TimeoutCkan(_rows([2024, 2025])), **kw)
    assert store.states[DS]["transient_strikes"] == {"preview_unavailable": 1}


def test_an_answered_preview_breaks_a_blocked_run():
    state = RefreshState(transient_strikes={"preview_blocked": 2, "other": 1})
    probe = rf.InputProbe({}, {"r1": {"fields": []}}, lambda rid: None)
    assert rf._strikes_after_probe(state, probe) == {"other": 1}


def _http_error(code, body: bytes):
    return urllib_error.HTTPError("https://data.gov.il/x", code, "x", {}, io.BytesIO(body))


@pytest.mark.parametrize("raised, blocked", [
    (_http_error(403, b"<html>Request blocked</html>"), True),
    (_http_error(403, json.dumps({"success": False, "error": {
        "__type": "Authorization Error", "message": "Access denied"}}).encode()), False),
    (_http_error(500, b"oops"), False),
    (TimeoutError("timed out"), False),
    (None, False),
])
def test_preview_blocked_check(monkeypatch, raised, blocked):
    seen = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen.append((req.full_url, req.get_header("User-agent")))
        if raised is not None:
            raise raised
        return _Resp()

    monkeypatch.setattr(rf.urllib_request, "urlopen", urlopen)
    assert rf._preview_blocked("aaaaaaaa-1") is blocked
    assert "resource_id=aaaaaaaa-1" in seen[0][0] and "limit=0" in seen[0][0]
    assert "govdata-builder" in seen[0][1]


def test_only_ckan_previews_get_the_403_check():
    m = RecipeManifest.model_validate({
        "dataset_id": DS, "recipe_version": 1, "authored_at": "2026-10-24T00:00:00Z",
        "inputs": [{"name": "x", "by_id": "r1"}],
    })
    recipe = SimpleNamespace(manifest=m, dataset_id=DS)
    res = [{"id": "r1", "name": "a", "format": "CSV", "datastore_active": True}]
    # A by_id input with no column check asks no preview here: no network.
    assert rf.probe_inputs(recipe, res)._blocked_fn is rf._preview_blocked
    assert rf.probe_inputs(recipe, res, lambda rid: {})._blocked_fn is None  # a provider's


# ── staging streaks ──────────────────────────────────────────────────────


class _StubRepo:
    def __init__(self, ids):
        self.ids = ids

    def list_ids(self):
        return list(self.ids)

    def load(self, dataset_id, scratch):
        return SimpleNamespace(manifest=SimpleNamespace(heavy=False, recipe_version=1))


class _Store:
    def get_source(self, dataset_id):
        return SimpleNamespace(id=dataset_id, refresh=RefreshState(), title="")


UPLOAD = ("failed", rf.STAGE_FAILED, StageStep.UPLOAD)
STORE = ("failed", rf.STAGE_FAILED, StageStep.STORE)
UNCHANGED = ("unchanged", "content_hash", None)
REFRESHED = ("refreshed", None, None)


def _staging_run(env, monkeypatch, script):
    def fake(src, recipe, **kw):
        status, reason, stage = script[src.id]
        return rf.RefreshOutcome(src.id, OutcomeStatus(status), "forced", reason, stage=stage)

    monkeypatch.setattr(rf, "refresh_one", fake)
    return rf.run_refresh(_Store(), _StubRepo(list(script)), staging_bucket="bkt",
                          force=True, work_root=env.tmp / "work")


def test_upload_failures_between_unchanged_outcomes_stop_the_batch(env, monkeypatch):
    """GCS down, Firestore up: the `unchanged` outcomes between the failed
    uploads write Firestore only, so they can't vouch for GCS."""
    script = dict(zip("abcdefg", [UPLOAD, UNCHANGED, UPLOAD, UNCHANGED, UPLOAD,
                                  REFRESHED, UNCHANGED], strict=True))
    s = _staging_run(env, monkeypatch, script)
    assert s["staging_down"] is True
    assert [o["reason"] for o in s["outcomes"]][5:] == ["staging_down", "staging_down"]


def test_a_successful_upload_resets_the_upload_streak(env, monkeypatch):
    script = dict(zip("abcdef", [UPLOAD, UPLOAD, REFRESHED, UPLOAD, UNCHANGED, UPLOAD],
                      strict=True))
    assert _staging_run(env, monkeypatch, script)["staging_down"] is False


def test_store_failures_between_unchanged_outcomes_keep_going(env, monkeypatch):
    # An `unchanged` outcome did write Firestore: the store is up.
    script = dict(zip("abcdef", [STORE, UNCHANGED, STORE, UNCHANGED, STORE, UNCHANGED],
                      strict=True))
    assert _staging_run(env, monkeypatch, script)["staging_down"] is False


def test_store_clear_hashes():
    p = _written("mark_refresh_failed", error="e", reason="stage_failed", failed_version="v",
                 clear_hashes=True)
    for f in ("input_fingerprint", "file_fingerprint", "inputs_hash",
              "inputs_hash_unordered", "content_hash"):
        assert f in p and p[f] is None
    p = _written("mark_refresh_failed", error="e", reason="stage_failed", failed_version="v")
    assert "content_hash" not in p and "input_fingerprint" not in p


# ── by_schema and a resource that can't match ────────────────────────────


COLS = ["שנה", "סכום"]


def _schema_recipe(*inputs):
    m = RecipeManifest.model_validate({
        "dataset_id": DS, "recipe_version": 1, "authored_at": "2026-10-24T00:00:00Z",
        "inputs": list(inputs) or [{"name": "x", "by_schema": COLS, "concat": True}],
    })
    return SimpleNamespace(manifest=m, dataset_id=DS)


def _res(rid, name, fmt="CSV"):
    return {"id": rid, "name": name, "format": fmt, "datastore_active": True}


def _previews(answers):
    """preview_fn: rid → columns (None = the preview didn't answer)."""
    def fn(rid):
        cols = answers[rid]
        return None if cols is None else {"fields": [{"id": c} for c in cols], "total": 1}
    return fn


YEARS = [_res("r1", "הוצאות 2023"), _res("r2", "הוצאות 2024")]
ANSWERS = {"r1": COLS, "r2": COLS}


def test_a_broken_resource_unlike_every_match_is_ignored():
    res = [*YEARS, _res("r3", "מילון נתונים", "XLSX")]
    probe = rf.probe_inputs(_schema_recipe(), res, _previews({**ANSWERS, "r3": None}))
    assert [r["id"] for r in probe.resolved["x"]] == ["r1", "r2"]
    assert probe.answered()  # an ignored preview doesn't keep a preview streak going


@pytest.mark.parametrize("broken", [
    _res("r3", "מילון נתונים", "CSV"),     # same format as the matches
    _res("r3", "הוצאות 2025", "XLSX"),     # a sibling year in another format
    _res("r3", "", "XLSX"),                # no name to compare
    _res("r3", "מילון נתונים", ""),        # no format to compare
])
def test_a_broken_resource_that_could_match_still_strikes(broken):
    with pytest.raises(rf.StrikeError) as e:
        rf.probe_inputs(_schema_recipe(), [*YEARS, broken], _previews({**ANSWERS, "r3": None}))
    assert e.value.strike == "preview_unavailable"


def test_no_answered_match_means_no_guess():
    res = [_res("r1", "הוצאות 2023"), _res("r3", "מילון נתונים", "XLSX")]
    with pytest.raises(rf.StrikeError):
        rf.probe_inputs(_schema_recipe(), res, _previews({"r1": ["אחר"], "r3": None}))


def test_every_by_schema_input_must_rule_it_out():
    other = ["קוד", "שם"]
    res = [*YEARS, _res("r4", "קודים", "XLSX"), _res("r3", "מילון נתונים", "JSON")]
    recipe = _schema_recipe({"name": "x", "by_schema": COLS, "concat": True},
                            {"name": "codes", "by_schema": other, "pick": "latest"})
    probe = rf.probe_inputs(recipe, res, _previews({**ANSWERS, "r4": other, "r3": None}))
    assert [r["id"] for r in probe.resolved["codes"]] == ["r4"]
    # r3 shares the XLSX format with the `codes` match: it could be one.
    res[3] = _res("r3", "מילון נתונים", "XLSX")
    with pytest.raises(rf.StrikeError):
        rf.probe_inputs(recipe, res, _previews({**ANSWERS, "r4": other, "r3": None}))


def test_a_by_id_inputs_own_resource_is_never_ignored():
    recipe = _schema_recipe({"name": "x", "by_schema": COLS, "concat": True},
                            {"name": "dict", "by_id": "r3", "required_columns": ["a"]})
    res = [*YEARS, _res("r3", "מילון נתונים", "XLSX")]
    with pytest.raises(rf.StrikeError):
        rf.probe_inputs(recipe, res, _previews({**ANSWERS, "r3": None}))


# ── compute's process cap ────────────────────────────────────────────────


@pytest.mark.parametrize("value, expected", [
    (None, 256), ("0", None), ("64", 128), ("1000", 1000), ("junk", 256),
])
def test_compute_process_cap(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("REFRESH_COMPUTE_MAX_PROCS", raising=False)
    else:
        monkeypatch.setenv("REFRESH_COMPUTE_MAX_PROCS", value)
    assert rf._compute_max_procs() == expected
