"""Refresh knobs for hourly ticks: REFRESH_STRIKE_MIN_HOURS (escalation needs
elapsed time as well as a strike count) and REFRESH_REPROBE_MIN_HOURS (a
fingerprint-skipped bump isn't re-probed every run). Both default to 0, which
is today's behaviour; the existing tests in test_recipe_refresh.py and
test_map_snapshots.py run with them unset.
"""
from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.page_builder import refresh as rf
from services.page_builder.tests.test_recipe_refresh import (
    DS,
    FIXTURES,
    FakeCkan,
    FakeStore,
    TimeoutCkan,
    _bump,
    _first,
    _LimitedCkan,
    _rows,
    _run,
    _src,
)
from services.shared.firestore import FirestoreStateStore
from services.shared.states import RefreshState, UnchangedReason

T0 = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """test_recipe_refresh's `env`: faked issues + GCS."""
    issues = []
    monkeypatch.setattr(
        "services.page_builder.notify.open_authoring_issue",
        lambda **kw: issues.append(kw) or 77,
    )
    staged: dict[str, bytes] = {}
    return SimpleNamespace(
        tmp=tmp_path, issues=issues, staged=staged,
        write_gcs=lambda data, bucket, rel: staged.__setitem__(rel, data) or rel,
        read_gcs=lambda bucket, rel: staged.get(rel),
    )


@pytest.fixture
def clock(monkeypatch):
    """rf._utcnow, settable: `clock.now = …`."""
    class Clock:
        now = T0
    c = Clock()
    monkeypatch.setattr(rf, "_utcnow", lambda: c.now)
    return c


class KnobStore(FakeStore):
    """FakeStore plus the fields the knobs write (mirrors firestore.py), and a
    count of every state write."""

    def __init__(self, src):
        super().__init__(src)
        self.writes = 0
        self.knob_kwargs: list = []  # strike_since / probed_key as passed

    def mark_refreshed(self, dataset_id, **kw):
        self.writes += 1
        super().mark_refreshed(dataset_id, **kw)
        self._upd(dataset_id, wall_budget_strikes_since=None, transient_strikes_since=None,
                  probed_at=None, probed_metadata_modified=None, probed_key=None)

    def mark_refresh_unchanged(self, dataset_id, *, strike_since=None, probed_key=None, **kw):
        self.writes += 1
        self.knob_kwargs += [strike_since, probed_key]
        super().mark_refresh_unchanged(dataset_id, **kw)
        if kw.get("inputs_hash") is not None:
            self._upd(dataset_id, wall_budget_strikes_since=None, transient_strikes_since=None)
        elif strike_since:
            self._upd(dataset_id, **strike_since)
        if probed_key is not None:
            self._upd(dataset_id, probed_at=rf._utcnow(),
                      probed_metadata_modified=kw["metadata_modified"], probed_key=probed_key)
        if kw["advance_version"]:
            self._upd(dataset_id, probed_at=None, probed_metadata_modified=None, probed_key=None)

    def mark_refresh_failed(self, dataset_id, *, strike_since=None, **kw):
        self.writes += 1
        self.knob_kwargs.append(strike_since)
        super().mark_refresh_failed(dataset_id, **kw)
        if strike_since:
            self._upd(dataset_id, **strike_since)
        self._upd(dataset_id, probed_at=None, probed_metadata_modified=None, probed_key=None)


class CountingCkan(FakeCkan):
    def __init__(self, rows):
        super().__init__(rows)
        self.previews = 0

    def preview(self, rid):
        self.previews += 1
        return super().preview(rid)


def _rendered_then_bumped(env):
    store = KnobStore(_src("2026-10-01"))
    assert _run(env, store, FakeCkan(_rows([2024, 2025])))["refreshed"] == [DS]
    _bump(store, "2026-11-01")
    return store


# ── REFRESH_STRIKE_MIN_HOURS ─────────────────────────────────────────────


def test_preview_strikes_inside_the_window_stay_transient(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_STRIKE_MIN_HOURS", "72")
    store = _rendered_then_bumped(env)
    slow = TimeoutCkan(_rows([2024, 2025]))
    for n in range(1, rf._DEFAULT_TRANSIENT_STRIKES + 1):  # 6 strikes in 6 hours
        clock.now = T0 + timedelta(hours=n - 1)
        o = _first(_run(env, store, slow))
        assert o["reason"] == "fetch_failed", o
        st = store.states[DS]
        assert st["transient_strikes"] == {"preview_unavailable": n}
        assert st["transient_strikes_since"] == {"preview_unavailable": T0}
    assert env.issues == []
    clock.now = T0 + timedelta(hours=72)
    o = _first(_run(env, store, slow))
    assert o["reason"] == "schema_changed" and "7 runs in a row" in o["error"]
    assert len(env.issues) == 1 and env.issues[0]["reason"] == "schema_changed"
    st = store.states[DS]
    assert not st["transient_strikes"] and not st["transient_strikes_since"]


def test_wall_budget_strikes_inside_the_window_stay_transient(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_STRIKE_MIN_HOURS", "72")
    store = KnobStore(_src())
    slow = _LimitedCkan(_rows([2024, 2025]), "wall_budget")
    for n in range(1, rf._DEFAULT_WALL_BUDGET_STRIKES + 1):
        clock.now = T0 + timedelta(hours=n - 1)
        assert _first(_run(env, store, slow))["reason"] == "fetch_failed"
        assert store.states[DS]["wall_budget_strikes"] == n
        assert store.states[DS]["wall_budget_strikes_since"] == T0
    assert env.issues == []
    clock.now = T0 + timedelta(hours=72, minutes=1)
    assert _first(_run(env, store, slow))["reason"] == "too_large"
    assert len(env.issues) == 1
    st = store.states[DS]
    assert st["wall_budget_strikes"] == 0 and st["wall_budget_strikes_since"] is None


def test_strike_window_unset_escalates_on_the_count_and_writes_no_times(env, clock):
    store = _rendered_then_bumped(env)
    slow = TimeoutCkan(_rows([2024, 2025]))
    reasons = [_first(_run(env, store, slow))["reason"]
               for _ in range(rf._DEFAULT_TRANSIENT_STRIKES)]
    assert reasons[-1] == "schema_changed" and set(reasons[:-1]) == {"fetch_failed"}
    assert store.states[DS].get("transient_strikes_since") is None
    assert store.knob_kwargs and set(store.knob_kwargs) == {None}  # today's store calls


def test_a_success_clears_the_streak_and_its_start(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_STRIKE_MIN_HOURS", "72")
    store = _rendered_then_bumped(env)
    rows = _rows([2024, 2025])
    for _ in range(2):
        _run(env, store, TimeoutCkan(rows))
    assert store.states[DS]["transient_strikes_since"] == {"preview_unavailable": T0}
    clock.now = T0 + timedelta(hours=10)
    assert _run(env, store, FakeCkan(rows))["refreshed"] == [DS]
    st = store.states[DS]
    assert st["transient_strikes"] is None and st["transient_strikes_since"] is None
    _bump(store, "2026-11-02")
    _run(env, store, TimeoutCkan(rows))  # a new streak starts now
    assert store.states[DS]["transient_strikes_since"] == {"preview_unavailable": clock.now}


def test_a_fingerprint_skip_prunes_the_preview_streak_start(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_STRIKE_MIN_HOURS", "72")
    monkeypatch.setenv("REFRESH_PRECHECK", "full")
    store = KnobStore(_src("2026-10-01"))
    ckan = FakeCkan(_rows([2024, 2025]))
    _run(env, store, ckan)
    _bump(store, "2026-10-02")
    old = T0 - timedelta(hours=5)
    store.states[DS].update(transient_strikes={"preview_unavailable": 2, "other": 1},
                            transient_strikes_since={"preview_unavailable": old, "other": old})
    assert _first(_run(env, store, ckan))["reason"] == "fingerprint"
    st = store.states[DS]
    assert st["transient_strikes"] == {"other": 1}
    assert st["transient_strikes_since"] == {"other": old}


def test_legacy_streak_without_a_start_waits_out_the_window(clock, monkeypatch):
    """A doc counted before the knob existed: the missing start is 'now'."""
    legacy = RefreshState(transient_strikes={"preview_unavailable": 9}, wall_budget_strikes=9)
    monkeypatch.setenv("REFRESH_STRIKE_MIN_HOURS", "72")
    e, _, transient, since = rf._count_strikes(rf._preview_strike("slow"), legacy, None)
    assert e.reason == "fetch_failed" and transient == {"preview_unavailable": 10}
    assert since == {"transient_strikes_since": {"preview_unavailable": T0}}
    e, strikes, _, since = rf._count_strikes(rf.WallBudgetExceeded("slow"), legacy, None)
    assert e.reason == "fetch_failed" and strikes == 10
    assert since["wall_budget_strikes_since"] == T0
    # The knob off: today's count-only escalation, and no time written.
    monkeypatch.delenv("REFRESH_STRIKE_MIN_HOURS")
    e, _, transient, since = rf._count_strikes(rf._preview_strike("slow"), legacy, None)
    assert e.reason == "schema_changed" and transient == {} and since == {}
    e, strikes, _, since = rf._count_strikes(rf.WallBudgetExceeded("slow"), legacy, None)
    assert e.reason == "too_large" and strikes == 0 and since == {}


def test_a_stale_start_after_a_reset_is_not_reused(clock, monkeypatch):
    monkeypatch.setenv("REFRESH_STRIKE_MIN_HOURS", "72")
    old = T0 - timedelta(days=30)
    st = RefreshState(transient_strikes={"other": 1},
                      transient_strikes_since={"preview_unavailable": old, "other": old},
                      wall_budget_strikes=0, wall_budget_strikes_since=old)
    _, _, _, since = rf._count_strikes(rf._preview_strike("slow"), st, None)
    assert since["transient_strikes_since"] == {"preview_unavailable": T0, "other": old}
    _, strikes, _, since = rf._count_strikes(rf.WallBudgetExceeded("slow"), st, None)
    assert strikes == 1 and since["wall_budget_strikes_since"] == T0


# ── REFRESH_REPROBE_MIN_HOURS ────────────────────────────────────────────


def _fingerprinted(env, monkeypatch, *, recipes=FIXTURES):
    """Rendered, bumped with identical bytes, fingerprint-skipped once."""
    monkeypatch.setenv("REFRESH_PRECHECK", "full")
    store = KnobStore(_src("2026-10-01"))
    ckan = CountingCkan(_rows([2024, 2025]))
    assert _run(env, store, ckan, recipes=recipes)["refreshed"] == [DS]
    _bump(store, "2026-10-02")
    assert _first(_run(env, store, ckan, recipes=recipes))["reason"] == "fingerprint"
    return store, ckan


def test_reprobe_window_skips_with_no_ckan_call_and_no_write(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_REPROBE_MIN_HOURS", "6")
    store, ckan = _fingerprinted(env, monkeypatch)
    st = store.states[DS]
    assert st["probed_at"] == T0 and st["probed_metadata_modified"] == store.src.metadata_modified
    assert st["probed_key"]
    previews, fetches, writes = ckan.previews, ckan.fetches, store.writes
    clock.now = T0 + timedelta(hours=5)
    s = _run(env, store, ckan)
    o = _first(s)
    assert (o["status"], o["reason"]) == ("unchanged", UnchangedReason.RECENTLY_PROBED)
    assert o["precheck"] == {"mode": "full", "skipped": "recently_probed"}
    assert (ckan.previews, ckan.fetches, store.writes) == (previews, fetches, writes)
    assert s["unchanged"] == [DS] and env.issues == []


def test_reprobe_skip_does_not_spend_the_cap():
    out = rf.RefreshOutcome("a", "unchanged", reason=UnchangedReason.RECENTLY_PROBED)
    assert not rf._spends_cap(out)


def test_reprobe_after_the_window(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_REPROBE_MIN_HOURS", "6")
    store, ckan = _fingerprinted(env, monkeypatch)
    previews = ckan.previews
    clock.now = T0 + timedelta(hours=6)
    assert _first(_run(env, store, ckan))["reason"] == "fingerprint"
    assert ckan.previews > previews and store.states[DS]["probed_at"] == clock.now


def test_reprobe_when_the_source_moved(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_REPROBE_MIN_HOURS", "6")
    store, ckan = _fingerprinted(env, monkeypatch)
    previews = ckan.previews
    _bump(store, "2026-10-03")
    assert _first(_run(env, store, ckan))["reason"] == "fingerprint"
    assert ckan.previews > previews
    assert store.states[DS]["probed_metadata_modified"] == store.src.metadata_modified


def test_reprobe_when_the_resources_moved(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_REPROBE_MIN_HOURS", "6")
    store, ckan = _fingerprinted(env, monkeypatch)
    store.src.resources[0]["hash"] = "md5-v2"
    fetches = ckan.fetches
    o = _first(_run(env, store, ckan))
    # A′ moved, so it probed and fetched (today's path); B found the same bytes.
    assert o["reason"] == "inputs_hash" and ckan.fetches == fetches + 1


def test_forced_run_ignores_the_reprobe_window(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_REPROBE_MIN_HOURS", "6")
    store, ckan = _fingerprinted(env, monkeypatch)
    s = _run(env, store, ckan, force=True)
    assert _first(s)["status"] == "refreshed"
    assert store.states[DS]["probed_at"] is None  # the render cleared the probe


def test_max_age_render_ignores_the_reprobe_window(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_REPROBE_MIN_HOURS", "6")
    store, ckan = _fingerprinted(env, monkeypatch)
    store.states[DS]["last_refreshed_at"] = datetime(2020, 1, 1, tzinfo=UTC)
    fetches = ckan.fetches
    # A full render (C then finds the identical page, as today).
    assert _first(_run(env, store, ckan))["reason"] == "content_hash"
    assert ckan.fetches == fetches + 1


def test_edited_recipe_ignores_the_reprobe_window(env, clock, monkeypatch, tmp_path):
    monkeypatch.setenv("REFRESH_REPROBE_MIN_HOURS", "6")
    recipes = tmp_path / "recipes"
    shutil.copytree(FIXTURES / DS, recipes / DS)
    store, ckan = _fingerprinted(env, monkeypatch, recipes=recipes)
    tpl = recipes / DS / "template.html.j2"
    tpl.write_text(tpl.read_text(encoding="utf-8") + "\n<p>שינוי</p>\n", encoding="utf-8")
    assert _first(_run(env, store, ckan, recipes=recipes))["status"] == "refreshed"


def test_a_failure_drops_the_probe(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_REPROBE_MIN_HOURS", "6")
    store, ckan = _fingerprinted(env, monkeypatch)
    clock.now = T0 + timedelta(hours=7)
    _run(env, store, TimeoutCkan(ckan.rows))
    assert store.states[DS]["probed_at"] is None
    previews = ckan.previews
    clock.now = T0 + timedelta(hours=8)
    assert _first(_run(env, store, ckan))["reason"] == "fingerprint"
    assert ckan.previews > previews


def test_reprobe_window_unset_probes_every_run(env, clock, monkeypatch):
    store, ckan = _fingerprinted(env, monkeypatch)
    assert store.states[DS].get("probed_at") is None  # nothing recorded without the knob
    assert set(store.knob_kwargs) == {None}
    previews = ckan.previews
    assert _first(_run(env, store, ckan))["reason"] == "fingerprint"
    assert ckan.previews == previews + 1


def test_reprobe_window_needs_mode_full(env, clock, monkeypatch):
    monkeypatch.setenv("REFRESH_REPROBE_MIN_HOURS", "6")
    store, ckan = _fingerprinted(env, monkeypatch)
    monkeypatch.setenv("REFRESH_PRECHECK", "observe")
    assert _first(_run(env, store, ckan))["status"] == "refreshed"


# ── firestore.py writers ─────────────────────────────────────────────────


def _written(method, **kw) -> dict:
    store = FirestoreStateStore.__new__(FirestoreStateStore)
    store.client = MagicMock()
    getattr(store, method)("ds", **kw)
    ref = store.client.collection.return_value.document.return_value
    payload, merge = ref.set.call_args[0][0], ref.set.call_args[1]["merge"]
    assert merge == list(payload)
    return payload


def test_store_render_clears_strike_starts_and_probe():
    p = _written("mark_refreshed", metadata_modified=None, recipe_version=1,
                 agent_data={}, page_path="p")
    for f in ("wall_budget_strikes_since", "transient_strikes_since",
              "probed_at", "probed_metadata_modified", "probed_key"):
        assert f in p and p[f] is None


def test_store_failure_writes_strike_starts_and_drops_the_probe():
    p = _written("mark_refresh_failed", error="e", reason="fetch_failed", failed_version="v",
                 transient_strikes={"x": 1},
                 strike_since={"transient_strikes_since": {"x": T0}})
    assert p["transient_strikes_since"] == {"x": T0} and p["probed_key"] is None
    p = _written("mark_refresh_failed", error="e", reason="fetch_failed", failed_version="v")
    assert "transient_strikes_since" not in p and "wall_budget_strikes_since" not in p


def test_store_fingerprint_skip_records_the_probe():
    mm = datetime(2026, 11, 1, tzinfo=UTC)
    p = _written("mark_refresh_unchanged", metadata_modified=mm, input_fingerprint="f",
                 reason="fingerprint", advance_version=False, probed_key="k",
                 transient_strikes={}, strike_since={"transient_strikes_since": None})
    assert p["probed_key"] == "k" and p["probed_metadata_modified"] == mm
    assert p["probed_at"] == p["last_unchanged_at"]
    assert "transient_strikes_since" in p and p["transient_strikes_since"] is None
    p = _written("mark_refresh_unchanged", metadata_modified=mm, input_fingerprint="f",
                 reason="fingerprint", advance_version=False)
    assert "probed_at" not in p and "transient_strikes_since" not in p


def test_store_exact_skip_clears_strike_starts_and_probe():
    mm = datetime(2026, 11, 1, tzinfo=UTC)
    p = _written("mark_refresh_unchanged", metadata_modified=mm, input_fingerprint="f",
                 inputs_hash="h", reason="inputs_hash", advance_version=True)
    assert p["transient_strikes_since"] is None and p["wall_budget_strikes_since"] is None
    assert p["probed_at"] is None and p["probed_key"] is None
