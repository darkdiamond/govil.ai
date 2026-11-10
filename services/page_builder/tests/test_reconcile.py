"""Reconcile sweep: flips succeeded→unavailable on 403, unavailable→succeeded on alive."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.page_builder import reconcile
from services.shared.firestore import SourceRecord


def _src(sid: str, status: str, rid: str | None = "rid-1") -> SourceRecord:
    resources = [{"id": rid, "format": "CSV", "url": f"https://x/resource/{rid}/download/x.csv"}] if rid else []
    return SourceRecord(id=sid, title="t", analysis_status=status, resources=resources)


@pytest.mark.asyncio
async def test_marks_succeeded_source_unavailable_on_gone():
    store = MagicMock()
    store.iter_publishable_sources.return_value = iter([_src("a", "succeeded")])
    client = MagicMock()
    client.probe_resource = AsyncMock(return_value="gone")
    client.probe_package = AsyncMock(return_value="gone")

    summary = await reconcile.reconcile_sources(store, client)

    store.mark_source_unavailable.assert_called_once_with("a", "reconcile: datastore probe returned gone")
    store.clear_source_unavailable.assert_not_called()
    assert summary["marked_unavailable"] == ["a"]


@pytest.mark.asyncio
async def test_recovers_unavailable_source_on_alive():
    store = MagicMock()
    store.iter_publishable_sources.return_value = iter([_src("b", "unavailable")])
    client = MagicMock()
    client.probe_resource = AsyncMock(return_value="alive")
    client.probe_package = AsyncMock(return_value="alive")

    summary = await reconcile.reconcile_sources(store, client)

    store.clear_source_unavailable.assert_called_once_with("b")
    store.mark_source_unavailable.assert_not_called()
    assert summary["recovered"] == ["b"]


@pytest.mark.asyncio
async def test_unknown_probe_changes_nothing():
    store = MagicMock()
    store.iter_publishable_sources.return_value = iter([_src("c", "succeeded")])
    client = MagicMock()
    client.probe_resource = AsyncMock(return_value="unknown")
    client.probe_package = AsyncMock(return_value="unknown")

    summary = await reconcile.reconcile_sources(store, client)

    store.mark_source_unavailable.assert_not_called()
    store.clear_source_unavailable.assert_not_called()
    assert summary["checked"] == 1


@pytest.mark.asyncio
async def test_already_unavailable_and_still_gone_is_noop():
    store = MagicMock()
    store.iter_publishable_sources.return_value = iter([_src("d", "unavailable")])
    client = MagicMock()
    client.probe_resource = AsyncMock(return_value="gone")
    client.probe_package = AsyncMock(return_value="gone")

    await reconcile.reconcile_sources(store, client)

    store.mark_source_unavailable.assert_not_called()
    store.clear_source_unavailable.assert_not_called()


@pytest.mark.asyncio
async def test_no_primary_resource_falls_back_to_package_probe():
    store = MagicMock()
    store.iter_publishable_sources.return_value = iter([_src("e", "succeeded", rid=None)])
    client = MagicMock()
    client.probe_resource = AsyncMock(return_value="unknown")
    client.probe_package = AsyncMock(return_value="gone")

    await reconcile.reconcile_sources(store, client)

    client.probe_package.assert_awaited_once_with("e")
    store.mark_source_unavailable.assert_called_once()


def _store(sources):
    store = MagicMock()
    store.iter_publishable_sources.return_value = iter(sources)
    return store


@pytest.mark.asyncio
async def test_blocked_probe_changes_nothing_and_skips_the_package_probe():
    store = _store([_src("d", "succeeded")])
    client = MagicMock()
    client.probe_resource = AsyncMock(return_value="blocked")
    client.probe_package = AsyncMock(return_value="gone")

    summary = await reconcile.reconcile_sources(store, client)

    client.probe_package.assert_not_called()
    store.mark_source_unavailable.assert_not_called()
    assert summary["blocked"] == 1 and summary["aborted"] is None


@pytest.mark.asyncio
async def test_too_many_gone_aborts_the_flips_but_keeps_recoveries():
    gone = [_src(f"g{i}", "succeeded", rid=f"rg{i}") for i in range(4)]
    back = _src("r", "unavailable", rid="rr")
    store = _store([*gone, back])
    client = MagicMock()
    client.probe_resource = AsyncMock(side_effect=lambda rid: "alive" if rid == "rr" else "gone")
    client.probe_package = AsyncMock(return_value="unknown")

    summary = await reconcile.reconcile_sources(store, client, max_flips=3)

    store.mark_source_unavailable.assert_not_called()
    store.clear_source_unavailable.assert_called_once_with("r")
    assert summary["aborted"] == "too_many_gone"
    assert summary["marked_unavailable"] == [] and summary["recovered"] == ["r"]


@pytest.mark.asyncio
async def test_flips_up_to_the_cap_apply():
    store = _store([_src(f"g{i}", "succeeded", rid=f"rg{i}") for i in range(3)])
    client = MagicMock()
    client.probe_resource = AsyncMock(return_value="gone")
    client.probe_package = AsyncMock(return_value="gone")

    summary = await reconcile.reconcile_sources(store, client, max_flips=3)

    assert store.mark_source_unavailable.call_count == 3
    assert summary["aborted"] is None


@pytest.mark.asyncio
async def test_many_blocked_probes_abort_the_sweep():
    # A WAF refusing our User-Agent: no flips either way, and the sweep is
    # reported aborted so the run turns red.
    store = _store([_src(f"b{i}", "succeeded", rid=f"rb{i}") for i in range(3)]
                   + [_src("g", "succeeded", rid="rg")])
    client = MagicMock()
    client.probe_resource = AsyncMock(side_effect=lambda rid: "gone" if rid == "rg" else "blocked")
    client.probe_package = AsyncMock(return_value="unknown")

    summary = await reconcile.reconcile_sources(store, client, max_flips=3)

    store.mark_source_unavailable.assert_not_called()
    assert summary["aborted"] == "too_many_blocked" and summary["blocked"] == 3


@pytest.mark.asyncio
async def test_a_raising_probe_counts_as_unknown_and_the_rest_still_apply():
    store = _store([_src("x", "succeeded", rid="rx"), _src("y", "succeeded", rid="ry")])
    client = MagicMock()

    async def probe(rid):
        if rid == "rx":
            raise RuntimeError("boom")
        return "gone"

    client.probe_resource = AsyncMock(side_effect=probe)
    client.probe_package = AsyncMock(return_value="unknown")

    summary = await reconcile.reconcile_sources(store, client)

    store.mark_source_unavailable.assert_called_once_with("y", "reconcile: datastore probe returned gone")
    assert summary["unknown"] == 1


def test_max_flips_env(monkeypatch):
    monkeypatch.setenv("RECONCILE_MAX_FLIPS", "7")
    assert reconcile.max_flips_from_env() == 7
    monkeypatch.setenv("RECONCILE_MAX_FLIPS", "nonsense")
    assert reconcile.max_flips_from_env() == reconcile.DEFAULT_MAX_FLIPS


@pytest.mark.asyncio
async def test_many_raising_probes_abort_the_sweep():
    # A probe bug in bulk must turn the run red, not pass as a quiet sweep.
    store = _store([_src(f"x{i}", "succeeded", rid=f"rx{i}") for i in range(3)])
    client = MagicMock()
    client.probe_resource = AsyncMock(side_effect=RuntimeError("boom"))
    client.probe_package = AsyncMock(return_value="unknown")

    summary = await reconcile.reconcile_sources(store, client, max_flips=3)

    assert summary["aborted"] == "too_many_errors" and summary["errors"] == 3
