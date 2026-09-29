"""Tests for the pipeline's restricted-source gate in _build_one.

A ResourceRestrictedError out of run_production_session (raised by the CKAN
prefetch before any agent session runs) must park the source as `restricted`
— not `failed` — so it doesn't consume the failed-retry budget or trigger a
publish.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from services.page_builder import pipeline
from services.page_builder.agent_contract import ResourceRestrictedError
from services.shared.firestore import SourceRecord


def _run_build_one(monkeypatch, *, raises):
    src = SourceRecord(id="fa475dcc", title="מאגר", resources=[{"id": "r1", "url": "u"}])
    store = MagicMock()

    def _session(**_kwargs):
        raise raises

    monkeypatch.setattr(pipeline, "run_production_session", _session)
    sem = asyncio.Semaphore(1)
    # A fresh, unset abort event: these cases are per-source outcomes, not
    # the batch-wide account abort (see test_account_limit_pipeline.py).
    abort = asyncio.Event()
    return (
        asyncio.run(pipeline._build_one(src, "staging-bucket", store, sem, abort)),
        store,
    )


def test_restricted_error_parks_source_not_failed(monkeypatch):
    result, store = _run_build_one(
        monkeypatch, raises=ResourceRestrictedError("CKAN datastore 403 for r1")
    )
    assert result["status"] == "restricted"
    store.mark_analysis_restricted.assert_called_once()
    store.mark_analysis_failed.assert_not_called()


def test_generic_error_still_marks_failed(monkeypatch):
    result, store = _run_build_one(monkeypatch, raises=RuntimeError("model flake"))
    assert result["status"] == "failed"
    store.mark_analysis_failed.assert_called_once()
    store.mark_analysis_restricted.assert_not_called()


def _run_published(monkeypatch, *, raises):
    src = SourceRecord(
        id="pub1", title="מאגר", resources=[{"id": "r1", "url": "u"}],
        analysis_status="succeeded", page_path="datasets/pub1/",
    )
    store = MagicMock()

    def _session(**_kwargs):
        raise raises

    monkeypatch.setattr(pipeline, "run_production_session", _session)
    result = asyncio.run(
        pipeline._build_one(src, "b", store, asyncio.Semaphore(1), asyncio.Event())
    )
    return result, store


def test_failed_rebuild_of_published_page_keeps_it_publishable(monkeypatch):
    result, store = _run_published(monkeypatch, raises=RuntimeError("flake"))
    assert result["status"] == "failed"
    store.mark_reanalysis_failed.assert_called_once()
    store.mark_analysis_failed.assert_not_called()


def test_restricted_rebuild_of_published_page_preserves_it(monkeypatch):
    result, store = _run_published(
        monkeypatch, raises=ResourceRestrictedError("403")
    )
    assert result["status"] == "restricted"
    store.mark_source_unavailable.assert_called_once()
    store.mark_analysis_restricted.assert_not_called()
