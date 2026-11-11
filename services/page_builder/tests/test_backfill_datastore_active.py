"""backfill_datastore_active CLI: dry run unless --write (store and CKAN faked)."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from services.page_builder import backfill_datastore_active as bf


class _Store:
    def __init__(self):
        self.writes = []

    def iter_succeeded_sources(self):
        yield SimpleNamespace(id="ds-1", title="t", resources=[{"id": "r1"}])

    def set_resource_datastore_flags(self, source_id, flags):
        self.writes.append((source_id, flags))
        return True


class _Ckan:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_package(self, package_id):
        return SimpleNamespace(resources=[SimpleNamespace(id="r1", datastore_active=True)])


@pytest.fixture
def store(monkeypatch):
    s = _Store()
    monkeypatch.setattr(bf, "FirestoreStateStore", lambda: s)
    monkeypatch.setattr(bf, "CKANClient", _Ckan)
    return s


def _run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["backfill_datastore_active", *args])
    bf._cli()


def test_no_flag_does_not_write(monkeypatch, store):
    _run_cli(monkeypatch)
    assert store.writes == []


def test_dry_run_flag_does_not_write(monkeypatch, store):
    _run_cli(monkeypatch, "--dry-run")
    assert store.writes == []


def test_write_flag_writes(monkeypatch, store):
    _run_cli(monkeypatch, "--write")
    assert store.writes == [("ds-1", {"r1": True})]
