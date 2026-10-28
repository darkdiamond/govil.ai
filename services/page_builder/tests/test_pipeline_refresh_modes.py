"""run_pipeline wiring for the recipe-refresh knobs.

REFRESH_ENABLED: recipe'd sources are refreshed (no LLM) and excluded from
every agent track; a refresh alone is enough to publish.
AUTHORING_MODE=local: no agent session runs at all — selected sources are
queued for local authoring instead.
Both default off: with neither set, the pipeline behaves exactly as before.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from services.page_builder import pipeline
from services.page_builder import refresh as rf
from services.shared.firestore import SourceRecord


@pytest.fixture
def harness(monkeypatch):
    h = SimpleNamespace(picked_with=None, built=[], queued=[], published=[], refreshed=[])
    store = SimpleNamespace(reap_stale_pending=lambda **kw: [])
    monkeypatch.setattr(pipeline, "FirestoreStateStore", lambda: store)
    monkeypatch.setattr(pipeline, "StateDB", lambda store: None)
    monkeypatch.setattr(pipeline, "ScannerSettings", lambda: None)

    class _Scanner:
        def __init__(self, **kw):
            pass

        async def scan(self, **kw):
            return SimpleNamespace(datasets_scanned=0, datasets_new=0,
                                   datasets_updated=0, datasets_unchanged=0, errors=[])

    monkeypatch.setattr(pipeline, "Scanner", _Scanner)
    h.selected = [SourceRecord(id="new1", title="n"),
                  SourceRecord(id="old1", title="o", page_path="datasets/old1/")]

    def _pick(store, n, **kw):
        h.picked_with = kw
        return [s for s in h.selected if s.id not in kw.get("exclude_ids", ())]

    monkeypatch.setattr(pipeline.selector, "pick_next", _pick)

    async def _build(src, *a):
        h.built.append(src.id)
        return {"id": src.id, "status": "succeeded"}

    monkeypatch.setattr(pipeline, "_build_one", _build)

    async def _publish(*a, **kw):
        h.published.append(a)
        return "gh"

    monkeypatch.setattr(pipeline, "_trigger_publish_github", _publish)

    repo = SimpleNamespace(list_ids=lambda: ["rec1"])
    monkeypatch.setattr(rf, "recipe_repo_from_env", lambda: repo)

    def _run_refresh(store, repo, **kw):
        assert kw["preview"] is False
        return {"refreshed": list(h.refreshed), "failed": [], "outcomes": []}

    monkeypatch.setattr(rf, "run_refresh", _run_refresh)

    def _queue(store, src, reason, **kw):
        h.queued.append((src.id, reason))
        return 7

    monkeypatch.setattr(rf, "queue_authoring", _queue)
    monkeypatch.setenv("GCS_STAGING_BUCKET", "bkt")
    for k in ("REFRESH_ENABLED", "AUTHORING_MODE", "RECONCILE_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    return h


def _run():
    return asyncio.run(pipeline.run_pipeline())


def test_defaults_unchanged(harness):
    s = _run()
    assert harness.built == ["new1", "old1"]
    assert harness.picked_with["exclude_ids"] == frozenset()
    assert s["refresh"] is None and s["status"] == "ok"


def test_refresh_excludes_recipe_ids_and_alone_publishes(harness, monkeypatch):
    monkeypatch.setenv("REFRESH_ENABLED", "true")
    harness.selected = [SourceRecord(id="rec1", title="r")]
    harness.refreshed = ["rec1"]
    s = _run()
    assert harness.picked_with["exclude_ids"] == frozenset({"rec1"})
    assert harness.built == []
    assert s["status"] == "ok" and harness.published


def test_unreadable_recipe_list_pauses_track2(harness, monkeypatch):
    """Fail closed: an agent rebuild must not overwrite a recipe-owned page
    just because GitHub was unreachable for the listing."""
    monkeypatch.setenv("REFRESH_ENABLED", "true")

    def _boom():
        raise RuntimeError("github down")

    monkeypatch.setattr(rf, "recipe_repo_from_env",
                        lambda: SimpleNamespace(list_ids=_boom))
    _run()
    assert harness.picked_with["reanalyze"] is False


def test_github_repo_lists_and_pins_one_commit(monkeypatch, tmp_path):
    calls = []

    class _R:
        def __init__(self, data=None, content=b""):
            self._data, self.content = data, content

        def json(self):
            return self._data

        def raise_for_status(self):
            pass

    def _get(url, **kw):
        calls.append(url)
        if url.endswith("/commits/main"):
            return _R({"sha": "abc123"})
        if "/git/trees/abc123" in url:
            return _R({"tree": [{"path": "recipes/ds1/recipe.json"},
                                {"path": "recipes/ds1/compute.py"},
                                {"path": "recipes/README.md"},
                                {"path": "services/x.py"}]})
        raise AssertionError(url)

    import httpx
    monkeypatch.setattr(httpx, "get", _get)
    repo = rf.GithubRecipeRepo("o/r", "main")
    assert repo.list_ids() == ["ds1"]
    assert repo._sha == "abc123"


def test_default_recipe_source_is_github_main(monkeypatch):
    monkeypatch.delenv("RECIPES_SOURCE", raising=False)
    monkeypatch.setenv("PUBLISH_GITHUB_REPO", "o/r")
    repo = rf.recipe_repo_from_env()
    assert isinstance(repo, rf.GithubRecipeRepo) and (repo.repo, repo.ref) == ("o/r", "main")


def test_idle_refresh_does_not_publish(harness, monkeypatch):
    monkeypatch.setenv("REFRESH_ENABLED", "true")
    harness.selected = []
    s = _run()
    assert s["status"] == "idle" and not harness.published


def test_local_authoring_queues_instead_of_building(harness, monkeypatch):
    monkeypatch.setenv("AUTHORING_MODE", "local")
    s = _run()
    assert harness.built == []
    assert harness.queued == [("new1", "new"), ("old1", "legacy_updated")]
    assert s["status"] == "idle" and not harness.published


def test_unchanged_refresh_does_not_publish(harness, monkeypatch):
    """REFRESH_PRECHECK: a CKAN bump the precheck proved a no-op leaves the
    live page standing — no publish dispatch for it."""
    monkeypatch.setenv("REFRESH_ENABLED", "true")
    harness.selected = []
    monkeypatch.setattr(
        rf, "run_refresh",
        lambda store, repo, **kw: {"refreshed": [], "unchanged": ["rec1"],
                                   "failed": [], "outcomes": []},
    )
    s = _run()
    assert s["status"] == "idle" and not harness.published
