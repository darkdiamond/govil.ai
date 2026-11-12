"""run_pipeline's hourly-tick gates: QUIET_WINDOW, the job_state/run lease,
AUTHORING_QUEUE_HOURS, RECONCILE_MAX_ATTEMPTS, and the run's duration on the
summary. Every knob unset keeps the old behaviour (the other pipeline tests)."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import pytest

from services.page_builder import pipeline
from services.page_builder.tests.test_pipeline_refresh_modes import (  # noqa: F401
    _due_reconcile,
    _run,
    harness,
)
from services.shared import schedule


def _nothing_happened(h):
    assert h.refresh_kw is None and h.queued == [] and not h.published
    assert h.picked_with is None


# ── the run lease ────────────────────────────────────────────────────────────


def test_scheduled_run_takes_and_releases_the_lease(harness):  # noqa: F811
    s = _run()
    kinds = [c[0] for c in harness.lease_calls]
    assert kinds == ["acquire", "release"]
    acq, rel = harness.lease_calls
    assert acq[1] == rel[1] == "job_state/run" and acq[2] == rel[2]  # same holder
    assert acq[3] == 900.0
    assert s["lease"] == "held" and s["status"] == "idle"


def test_lease_ttl_comes_from_the_env(harness, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RUN_LEASE_TTL_S", "900")
    _run()
    assert harness.lease_calls[0][3] == 900.0


def test_held_lease_skips_the_run_and_exits_zero(harness, monkeypatch, capsys):  # noqa: F811
    harness.lease_free = False
    scanned = []

    class _Scanner:
        def __init__(self, **kw):
            pass

        async def scan(self, **kw):
            scanned.append(kw)

    monkeypatch.setattr(pipeline, "Scanner", _Scanner)
    s = _run()
    assert s["status"] == "skipped_overlap"
    assert s["status"] not in pipeline.FAILED_RUN_STATUSES
    assert scanned == [] and harness.markers == {}
    _nothing_happened(harness)
    # Never acquired, so never released (it isn't ours).
    assert [c[0] for c in harness.lease_calls] == ["acquire"]
    assert "duration_s" in s and "started_at" in s

    # The CLI prints the pipeline_summary line and exits 0.
    monkeypatch.setattr(sys, "argv", ["pipeline", "--mode", "scheduled"])
    pipeline._cli()  # no SystemExit
    out = capsys.readouterr().out.strip().splitlines()
    head = json.loads(out[0])["pipeline_summary"]
    assert head["status"] == "skipped_overlap"


def test_lease_released_when_the_run_raises(harness, monkeypatch):  # noqa: F811
    monkeypatch.delenv("GCS_STAGING_BUCKET")  # PipelineSettings raises
    with pytest.raises(RuntimeError):
        _run()
    assert [c[0] for c in harness.lease_calls] == ["acquire", "release"]


def test_lease_error_runs_without_it_and_logs_an_error(harness, monkeypatch, caplog):  # noqa: F811
    def broken(*a, **kw):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(pipeline.lease, "acquire", broken)
    released = []
    monkeypatch.setattr(pipeline.lease, "release", lambda *a: released.append(a))
    harness.refreshed = ["rec1"]
    with caplog.at_level("ERROR", logger="page_builder.pipeline"):
        s = _run()
    assert s["status"] == "ok" and harness.published
    assert s["lease"] == "error" and released == []
    assert any(r.levelname == "ERROR" and "WITHOUT the lease" in r.getMessage()
               for r in caplog.records)


@pytest.mark.parametrize("kw", [{"mode": "manual"}, {"override_id": "rec1"},
                                {"dry_run": True}])
def test_manual_override_and_dry_runs_take_no_lease(harness, kw):  # noqa: F811
    harness.lease_free = False
    s = _run(**kw)
    assert harness.lease_calls == [] and "lease" not in s
    assert s["status"] != "skipped_overlap"


# ── QUIET_WINDOW ─────────────────────────────────────────────────────────────


def test_quiet_window_skips_before_the_lease(harness, monkeypatch):  # noqa: F811
    monkeypatch.setattr(schedule, "in_quiet_window", lambda *a, **k: True)
    s = _run()
    assert s["status"] == "skipped_quiet" and s["status"] not in pipeline.FAILED_RUN_STATUSES
    assert harness.lease_calls == []
    _nothing_happened(harness)


def test_quiet_window_reads_the_env(harness, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(schedule, "in_quiet_window",
                        lambda name="QUIET_WINDOW", now=None: seen.append(name) or False)
    _run()
    assert seen == ["QUIET_WINDOW"]


@pytest.mark.parametrize("kw", [{"mode": "manual"}, {"override_id": "rec1"}])
def test_manual_and_source_runs_ignore_the_quiet_window(harness, monkeypatch, kw):  # noqa: F811
    monkeypatch.setattr(schedule, "in_quiet_window", lambda *a, **k: True)
    harness.refreshed = ["rec1"]
    s = _run(**kw)
    assert s["status"] == "ok"


# ── AUTHORING_QUEUE_HOURS ────────────────────────────────────────────────────


def test_authoring_queue_skipped_off_hours(harness, monkeypatch):  # noqa: F811
    monkeypatch.setattr(schedule, "due_this_hour", lambda name, now=None: False)
    harness.refreshed = ["rec1"]
    s = _run()
    assert harness.picked_with is None and harness.queued == []
    assert s["authoring_skipped"] == "not_due_this_hour"
    assert s["authoring_queued"] == [] and s["selected_for_authoring"] == []
    assert s["status"] == "ok" and harness.published  # not a failure; publish goes out


def test_authoring_queue_runs_on_listed_hours(harness, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(schedule, "due_this_hour",
                        lambda name, now=None: seen.append(name) or True)
    s = _run()
    assert seen == ["AUTHORING_QUEUE_HOURS"]
    assert harness.queued == [("new1", "new"), ("old1", "legacy_updated")]
    assert "authoring_skipped" not in s


def test_source_run_ignores_the_authoring_gate(harness, monkeypatch):  # noqa: F811
    monkeypatch.setattr(schedule, "due_this_hour", lambda name, now=None: False)
    s = _run(override_id="solo")
    assert harness.queued == [("solo", "new")] and "authoring_skipped" not in s


def test_authoring_gate_end_to_end_with_the_env(harness, monkeypatch):  # noqa: F811
    hour = schedule._il(datetime.now(UTC)).hour
    monkeypatch.setenv("AUTHORING_QUEUE_HOURS", str((hour + 12) % 24))
    _run()
    assert harness.queued == []
    monkeypatch.setenv("AUTHORING_QUEUE_HOURS", f"{(hour + 12) % 24},{hour}")
    _run()
    assert len(harness.queued) == 2


# ── RECONCILE_MAX_ATTEMPTS ───────────────────────────────────────────────────


def _reconcile_with_marker(harness, monkeypatch, outcome):  # noqa: F811
    """A due sweep over a dict-backed job_state/reconcile; returns sweep calls."""
    _due_reconcile(harness, monkeypatch, outcome)
    marker: dict = {}
    store = pipeline.FirestoreStateStore()
    store.get_job_marker = lambda name: dict(marker) if name == "reconcile" else {}
    store.set_job_marker = lambda name, f: marker.update(f) if name == "reconcile" else None
    from services.page_builder import reconcile

    sweeps = []
    real = reconcile.reconcile_sources

    async def counted(store, client, **kw):
        sweeps.append(1)
        return await real(store, client, **kw)

    monkeypatch.setattr(reconcile, "reconcile_sources", counted)
    return sweeps, marker


def test_aborted_sweeps_stop_after_the_attempt_cap(harness, monkeypatch):  # noqa: F811
    sweeps, marker = _reconcile_with_marker(
        harness, monkeypatch, {"checked": 1, "marked_unavailable": [], "recovered": [],
                               "aborted": "too_many_gone"})
    assert _run()["status"] == "reconcile_failed"
    assert _run()["status"] == "reconcile_failed"
    s = _run()  # third run that IL date: no sweep
    assert len(sweeps) == 2 and marker["attempts"] == 2
    assert s["status"] == "idle" and s["reconcile"] is None
    assert "last_date" not in marker


def test_attempt_cap_from_the_env(harness, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RECONCILE_MAX_ATTEMPTS", "1")
    sweeps, _ = _reconcile_with_marker(harness, monkeypatch, RuntimeError("sweep broke"))
    _run()
    _run()
    assert len(sweeps) == 1


def test_successful_sweep_still_ends_sweeps_for_the_day(harness, monkeypatch):  # noqa: F811
    sweeps, marker = _reconcile_with_marker(
        harness, monkeypatch, {"checked": 1, "marked_unavailable": [], "recovered": [],
                               "aborted": None})
    _run()
    _run()
    assert len(sweeps) == 1 and marker["attempts"] == 1 and marker["last_date"]


def test_attempts_reset_on_a_new_date():
    store = _MarkerStore({"attempt_date": "2026-11-01", "attempts": 2})
    sunday = datetime(2026, 11, 8, 6, 0, tzinfo=UTC)
    assert pipeline._claim_reconcile_attempt(store, sunday, 2) is True
    assert store.marker == {"attempt_date": "2026-11-08", "attempts": 1}
    assert pipeline._claim_reconcile_attempt(store, sunday, 2) is True
    assert pipeline._claim_reconcile_attempt(store, sunday, 2) is False


def test_attempt_marker_failure_still_sweeps():
    class Broken:
        def get_job_marker(self, name):
            raise RuntimeError("down")

    assert pipeline._claim_reconcile_attempt(Broken(), datetime.now(UTC), 2) is True


class _MarkerStore:
    def __init__(self, marker):
        self.marker = dict(marker)

    def get_job_marker(self, name):
        return dict(self.marker)

    def set_job_marker(self, name, fields):
        self.marker.update(fields)


# ── duration on the summary ──────────────────────────────────────────────────


@pytest.mark.parametrize("kw", [{}, {"mode": "manual"}, {"dry_run": True},
                                {"override_id": "rec1"}])
def test_summary_has_started_at_and_duration(harness, kw):  # noqa: F811
    s = _run(**kw)
    assert isinstance(s["duration_s"], float) and s["duration_s"] >= 0
    started = datetime.fromisoformat(s["started_at"])
    assert started.tzinfo is not None
    head = json.loads(pipeline.summarize_for_log(s)[0])["pipeline_summary"]
    assert "duration_s" in head and "started_at" in head


def test_skip_statuses_are_not_failures():
    assert pipeline.RunStatus.SKIPPED_OVERLAP not in pipeline.FAILED_RUN_STATUSES
    assert pipeline.RunStatus.SKIPPED_QUIET not in pipeline.FAILED_RUN_STATUSES
