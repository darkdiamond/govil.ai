"""PROVIDER_<KEY>_SYNC_HOURS: a provider synced only at the listed Israel-time
hours. Unset = every run (today)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.providers import sync
from services.providers.tests.sync_helpers import FakeStore, make_repo
from services.providers.tests.test_providers import (  # noqa: F401  (boi is a fixture)
    BR_CSV,
    FakeResp,
    _source,
    boi,
)
from services.shared import schedule

NOON_IL = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)  # 12:00 in Israel (UTC+2)


@pytest.fixture
def at_noon(monkeypatch):
    monkeypatch.setattr(sync, "due_this_hour",
                        lambda name: schedule.due_this_hour(name, now=NOON_IL))


def _synced_once(boi, tmp_path):  # noqa: F811
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    repo = make_repo(tmp_path, {"boi-a": _source().model_dump()})
    store = FakeStore()
    assert sync.sync_provider_sources(store, repo, providers={"boi_sdmx": boi})["synced"] == ["boi-a"]
    boi.clear_cache()
    boi._healthy = None  # a new run asks the healthcheck again
    boi.calls.clear()
    return repo, store


def test_gated_provider_makes_no_call_and_leaves_its_docs(boi, tmp_path, monkeypatch, at_noon):  # noqa: F811
    repo, store = _synced_once(boi, tmp_path)
    before = {k: dict(v) for k, v in store.docs.items()}
    monkeypatch.setenv("PROVIDER_BOI_SDMX_SYNC_HOURS", "6,18")
    s = sync.sync_provider_sources(store, repo, providers={"boi_sdmx": boi})
    assert s["skipped"] == [{"id": "boi-a", "reason": "provider_gated:boi_sdmx"}]
    assert s["synced"] == [] and s["failed"] == []
    assert boi.calls == [] and boi._healthy is None  # not even the healthcheck
    assert store.docs == before


def test_due_hour_syncs(boi, tmp_path, monkeypatch, at_noon):  # noqa: F811
    repo, store = _synced_once(boi, tmp_path)
    monkeypatch.setenv("PROVIDER_BOI_SDMX_SYNC_HOURS", "6,12,18")
    s = sync.sync_provider_sources(store, repo, providers={"boi_sdmx": boi})
    assert s["synced"] == ["boi-a"] and boi.calls


def test_unset_syncs_every_run(boi, tmp_path, monkeypatch, at_noon):  # noqa: F811
    repo, store = _synced_once(boi, tmp_path)
    monkeypatch.delenv("PROVIDER_BOI_SDMX_SYNC_HOURS", raising=False)
    s = sync.sync_provider_sources(store, repo, providers={"boi_sdmx": boi})
    assert s["synced"] == ["boi-a"] and s["skipped"] == [] and boi.calls


def test_a_chosen_source_run_ignores_the_gate(boi, tmp_path, monkeypatch, at_noon):  # noqa: F811
    repo, store = _synced_once(boi, tmp_path)
    monkeypatch.setenv("PROVIDER_BOI_SDMX_SYNC_HOURS", "6")
    s = sync.sync_provider_sources(store, repo, providers={"boi_sdmx": boi}, only_ids=["boi-a"])
    assert s["synced"] == ["boi-a"] and boi.calls
