"""A provider error that repeats every run (a CBS table gone from the newest
edition) escalates to a needs-authoring issue after REFRESH_TRANSIENT_STRIKES
runs, like the refresh's own strikes: the refresh never runs for a dataset
whose sync fails, so nothing else would open one."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.page_builder import pipeline
from services.providers import sync
from services.providers.tests.sync_helpers import FakeStore, make_repo
from services.providers.tests.test_providers import (  # noqa: F401  (boi is a fixture)
    BR_CSV,
    FakeResp,
    _source,
    boi,
)
from services.shared.firestore import FirestoreStateStore


def _run(boi, store, repo):  # noqa: F811
    boi.clear_cache()
    boi._healthy = None  # a new run asks the healthcheck again
    return sync.sync_provider_sources(store, repo, providers={"boi_sdmx": boi})


@pytest.fixture
def synced(boi, tmp_path):  # noqa: F811
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    repo = make_repo(tmp_path, {"boi-a": _source().model_dump()})
    store = FakeStore()
    assert _run(boi, store, repo)["synced"] == ["boi-a"]
    del boi.answers["/BR/1.0/"]  # from now on the series 404s: a provider error
    return SimpleNamespace(repo=repo, store=store)


def test_repeated_provider_errors_escalate_once(boi, synced, monkeypatch):  # noqa: F811
    monkeypatch.setenv("REFRESH_TRANSIENT_STRIKES", "3")
    for n in (1, 2):
        s = _run(boi, synced.store, synced.repo)
        assert [f["reason"] for f in s["failed"]] == ["provider_error"]
        assert s["escalated"] == []
        assert synced.store.docs["boi-a"]["provider_sync_strikes"] == n
    s = _run(boi, synced.store, synced.repo)
    assert [e["id"] for e in s["escalated"]] == ["boi-a"]
    assert s["escalated"][0]["strikes"] == 3 and s["escalated"][0]["error"]
    doc = synced.store.docs["boi-a"]
    assert doc["provider_sync_strikes"] is None and doc["provider_sync_strikes_since"] is None
    # The page stays last-good: the doc's data is untouched.
    assert doc["record_count"] == 3


def test_a_full_sync_ends_the_run_of_errors(boi, synced, monkeypatch):  # noqa: F811
    monkeypatch.setenv("REFRESH_TRANSIENT_STRIKES", "3")
    for _ in (1, 2):
        _run(boi, synced.store, synced.repo)
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    assert _run(boi, synced.store, synced.repo)["synced"] == ["boi-a"]
    assert synced.store.docs["boi-a"]["provider_sync_strikes"] is None
    del boi.answers["/BR/1.0/"]
    s = _run(boi, synced.store, synced.repo)
    assert s["escalated"] == [] and synced.store.docs["boi-a"]["provider_sync_strikes"] == 1


def test_errors_inside_the_strike_window_wait(boi, synced, monkeypatch):  # noqa: F811
    monkeypatch.setenv("REFRESH_STRIKE_MIN_HOURS", "72")
    doc = synced.store.docs["boi-a"]
    recent = datetime.now(UTC) - timedelta(hours=1)
    doc.update(provider_sync_strikes=5, provider_sync_strikes_since=recent)
    s = _run(boi, synced.store, synced.repo)
    assert s["escalated"] == []
    assert doc["provider_sync_strikes"] == 6 and doc["provider_sync_strikes_since"] == recent
    doc["provider_sync_strikes_since"] = datetime.now(UTC) - timedelta(hours=73)
    assert [e["id"] for e in _run(boi, synced.store, synced.repo)["escalated"]] == ["boi-a"]


def test_a_dataset_never_synced_is_not_counted(boi, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("REFRESH_TRANSIENT_STRIKES", "1")
    repo = make_repo(tmp_path, {"boi-a": _source().model_dump()})
    store = FakeStore()
    s = _run(boi, store, repo)  # BR 404s from the start
    assert s["failed"] and s["escalated"] == [] and store.docs == {}


def test_a_failing_counter_never_costs_the_sync(boi, synced, monkeypatch):  # noqa: F811
    def boom(*a, **kw):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(synced.store, "set_provider_sync_strikes", boom)
    s = _run(boi, synced.store, synced.repo)
    assert [f["reason"] for f in s["failed"]] == ["provider_error"] and s["escalated"] == []


def test_store_writes_the_strikes_with_update():
    store = FirestoreStateStore.__new__(FirestoreStateStore)
    store.client = MagicMock()
    t = datetime(2026, 11, 13, tzinfo=UTC)
    store.set_provider_sync_strikes("ds", 2, t)
    ref = store.client.collection.return_value.document.return_value
    ref.update.assert_called_once_with({"provider_sync_strikes": 2,
                                        "provider_sync_strikes_since": t})
    store.set_provider_sync_strikes("ds", 0, t)
    assert ref.update.call_args[0][0] == {"provider_sync_strikes": None,
                                          "provider_sync_strikes_since": None}
    ref.set.assert_not_called()


def test_pipeline_opens_the_issue_through_queue_authoring(monkeypatch):
    from services.page_builder.tests.test_recipe_refresh import (
        FakeStore as RefreshStore,
    )
    from services.page_builder.tests.test_recipe_refresh import _src

    issues = []
    monkeypatch.setattr("services.page_builder.notify.open_authoring_issue",
                        lambda **kw: issues.append(kw) or 41)
    src = _src()
    store = RefreshStore(src)
    escalated = [{"id": src.id, "strikes": 6, "error": "t5: no t5.xlsx/.xls in folder"},
                 {"id": "gone", "strikes": 6, "error": "x"}]  # no doc: skipped
    pipeline.queue_provider_escalations(store, escalated)
    assert escalated[0]["issue"] == 41 and "issue" not in escalated[1]
    assert len(issues) == 1 and issues[0]["reason"] == "schema_changed"
    assert issues[0]["detail"].startswith("provider sync failed 6 runs in a row")
    assert store.states[src.id]["authoring_issue"] == 41
    # Again next time: the open issue is reused, not duplicated.
    monkeypatch.setattr("services.page_builder.notify.issue_state", lambda n: "open")
    pipeline.queue_provider_escalations(store, [dict(escalated[0])])
    assert len(issues) == 1
