"""Batch-level fallout of an account-level provider rejection.

The 2026-08-11 outage did two kinds of damage the unit-level fast-fail
alone doesn't undo:

  1. every source it touched was marked `failed` and had `failed_attempts`
     incremented — 29 ended up parked at >=3, unreachable by the selector
     even after the key was restored;
  2. the run still exited 0, so 18 dead days looked green.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from services.page_builder import pipeline
from services.page_builder.agent_runner import AccountLimitError
from services.shared.firestore import SourceRecord


def _src(sid: str, status: str = "never") -> SourceRecord:
    return SourceRecord(id=sid, title=f"t-{sid}", analysis_status=status)


def _run_one(src, store, abort, monkeypatch, exc):
    def _boom(**kwargs):
        raise exc

    monkeypatch.setattr(pipeline, "run_production_session", _boom)
    return asyncio.run(
        pipeline._build_one(src, "bucket", store, asyncio.Semaphore(1), abort)
    )


# --- the source must not be punished for the account's problem ------------


def test_account_limit_does_not_touch_failed_attempts(monkeypatch):
    store = MagicMock()
    res = _run_one(
        _src("s1"), store, asyncio.Event(), monkeypatch,
        AccountLimitError("Key limit exceeded (total limit)"),
    )

    assert res["status"] == "aborted"
    store.mark_analysis_failed.assert_not_called()
    store.revert_analysis_pending.assert_called_once()


def test_revert_restores_the_previous_status_not_never(monkeypatch):
    """A Track-2 rebuild of an already-published source must keep its page:
    downgrading `succeeded` to `never` would drop it from the next publish."""
    store = MagicMock()
    _run_one(
        _src("s2", status="succeeded"), store, asyncio.Event(), monkeypatch,
        AccountLimitError("Key limit exceeded"),
    )

    assert store.revert_analysis_pending.call_args.args[1] == "succeeded"


def test_ordinary_failure_still_counts_against_the_source(monkeypatch):
    """The retry budget must keep working for real per-dataset failures."""
    store = MagicMock()
    res = _run_one(
        _src("s3"), store, asyncio.Event(), monkeypatch,
        RuntimeError("all 3 attempts failed: self-check failed"),
    )

    assert res["status"] == "failed"
    store.mark_analysis_failed.assert_called_once()
    store.revert_analysis_pending.assert_not_called()


# --- and the rest of the batch must not repeat the doomed call ------------


def test_account_limit_sets_the_batch_abort_flag(monkeypatch):
    abort = asyncio.Event()
    _run_one(_src("s4"), MagicMock(), abort, monkeypatch, AccountLimitError("x"))
    assert abort.is_set()


def test_queued_sources_skip_once_aborted(monkeypatch):
    """No Firestore write at all for a source that never ran."""
    store = MagicMock()
    abort = asyncio.Event()
    abort.set()

    called = {"n": 0}

    def _never(**kwargs):
        called["n"] += 1

    monkeypatch.setattr(pipeline, "run_production_session", _never)
    res = asyncio.run(
        pipeline._build_one(_src("s5"), "b", store, asyncio.Semaphore(1), abort)
    )

    assert res["status"] == "skipped"
    assert called["n"] == 0
    store.mark_analysis_pending.assert_not_called()
    store.mark_analysis_failed.assert_not_called()


# --- a dead run has to be loud -------------------------------------------


def test_dead_run_statuses_exit_non_zero():
    assert "all_failed" in pipeline.FAILED_RUN_STATUSES
    assert "aborted" in pipeline.FAILED_RUN_STATUSES


def test_idle_is_not_a_failure():
    """Nothing new to build is a healthy day, not a red execution."""
    assert "idle" not in pipeline.FAILED_RUN_STATUSES
    assert "ok" not in pipeline.FAILED_RUN_STATUSES


@pytest.mark.parametrize("status,expect_exit", [
    ("ok", False), ("idle", False), ("dry_run", False),
    ("all_failed", True), ("aborted", True),
])
def test_cli_exit_code_matches_run_outcome(status, expect_exit, monkeypatch, capsys):
    def _fake_run(coro, *a, **k):
        coro.close()  # we never await it; closing keeps pytest warning-free
        return {"status": status}

    monkeypatch.setattr(pipeline.asyncio, "run", _fake_run)
    monkeypatch.setattr("sys.argv", ["pipeline"])

    if expect_exit:
        with pytest.raises(SystemExit) as ei:
            pipeline._cli()
        assert ei.value.code == 1
    else:
        pipeline._cli()
    assert status in capsys.readouterr().out


# --- recovery: which status an outage casualty goes back to ---------------


def test_reset_plan_restores_published_sources_to_succeeded():
    """`succeeded` is the ONLY status the publisher emits, so a previously
    published source must go back to it — anything else deletes a live page.
    """
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "_reset_script",
        Path(__file__).resolve().parents[3] / "scripts"
        / "reset_account_limit_failures.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.plan_reset({"page_path": "datasets/x/"}) == "succeeded"
    assert mod.plan_reset({"last_analyzed_at": "2026-07-12"}) == "succeeded"
    assert mod.plan_reset({}) == "never"
