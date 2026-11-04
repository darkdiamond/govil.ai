"""Tests for ChangeDetector.detect_status.

The restricted→UPDATED branch is the load-bearing case: a source parked as
`restricted` (datastore 403) self-heals only if the scanner re-saves it when it
reappears in CKAN search. An unchanged metadata_modified would normally be
UNCHANGED and skip the save entirely, so the detector forces UPDATED for a
restricted stored doc — which makes save_dataset reset it back to `never`.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from services.scanner.detector import ChangeDetector
from services.scanner.models import DatasetStatus

MOD = datetime(2026, 5, 1, tzinfo=UTC)


def _ds(metadata_modified):
    return SimpleNamespace(id="abc-123", metadata_modified=metadata_modified)


def _detector(scan_state):
    db = MagicMock()
    db.get_scan_state.return_value = scan_state
    return ChangeDetector(db)


def test_new_when_no_stored_doc():
    assert _detector((None, None)).detect_status(_ds(MOD)) == DatasetStatus.NEW


def test_restricted_forces_updated_even_when_mtime_unchanged():
    d = _detector((MOD, "restricted"))
    assert d.detect_status(_ds(MOD)) == DatasetStatus.UPDATED


def test_unchanged_when_succeeded_and_mtime_equal():
    d = _detector((MOD, "succeeded"))
    assert d.detect_status(_ds(MOD)) == DatasetStatus.UNCHANGED


def test_updated_when_mtime_advanced():
    d = _detector((MOD, "succeeded"))
    later = datetime(2026, 5, 2, tzinfo=UTC)
    assert d.detect_status(_ds(later)) == DatasetStatus.UPDATED


def test_force_overrides_to_updated():
    d = _detector((MOD, "succeeded"))
    assert d.detect_status(_ds(MOD), force=True) == DatasetStatus.UPDATED
