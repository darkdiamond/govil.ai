"""run_pipeline wiring: recipe-only daily run.

Recipe'd sources are refreshed (no LLM) and a refresh is what publishes;
every new or changed source without a recipe is queued for authoring (an
issue), never built. No recipe list → nothing refreshed or queued, and the
run fails loudly.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from services.page_builder import pipeline
from services.page_builder import refresh as rf
from services.shared.firestore import SourceRecord


@pytest.fixture
def harness(monkeypatch):
    h = SimpleNamespace(picked_with=None, queued=[], published=[], refreshed=[],
                        refresh_kw=None)
    h.sources = {"rec1": SourceRecord(id="rec1", title="r", page_path="datasets/rec1/"),
                 "solo": SourceRecord(id="solo", title="s")}
    store = SimpleNamespace(reap_stale_pending=lambda **kw: [],
                            get_source=lambda i: h.sources.get(i))
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
    h.selected = [(SourceRecord(id="new1", title="n"), "new"),
                  (SourceRecord(id="old1", title="o", page_path="datasets/old1/"),
                   "legacy_updated")]

    def _pick(store, n, **kw):
        h.picked_with = kw
        return [(s, r) for s, r in h.selected if s.id not in kw.get("exclude_ids", ())]

    monkeypatch.setattr(pipeline.selector, "pick_authoring_candidates", _pick)

    async def _publish(*a, **kw):
        h.published.append(a)
        return "gh"

    monkeypatch.setattr(pipeline, "_trigger_publish_github", _publish)

    repo = SimpleNamespace(list_ids=lambda: ["rec1"])
    monkeypatch.setattr(rf, "recipe_repo_from_env", lambda: repo)

    def _run_refresh(store, repo, **kw):
        assert kw["preview"] is False
        h.refresh_kw = kw
        return {"refreshed": list(h.refreshed), "failed": [], "outcomes": []}

    monkeypatch.setattr(rf, "run_refresh", _run_refresh)

    def _queue(store, src, reason, **kw):
        h.queued.append((src.id, reason))
        return 7

    monkeypatch.setattr(rf, "queue_authoring", _queue)
    monkeypatch.setenv("GCS_STAGING_BUCKET", "bkt")
    for k in ("RECONCILE_ENABLED", "AUTHORING_NOTIFY_CAP"):
        monkeypatch.delenv(k, raising=False)
    return h


def _run(**kw):
    return asyncio.run(pipeline.run_pipeline(**kw))


def test_queues_sources_without_recipe_and_never_builds(harness):
    s = _run()
    assert harness.picked_with["exclude_ids"] == frozenset({"rec1"})
    assert harness.queued == [("new1", "new"), ("old1", "legacy_updated")]
    assert [q["issue"] for q in s["authoring_queued"]] == [7, 7]
    # Queueing alone changes no page: nothing to publish.
    assert s["status"] == "idle" and not harness.published


def test_refresh_alone_publishes(harness):
    harness.selected = []
    harness.refreshed = ["rec1"]
    s = _run()
    assert harness.refresh_kw["only_ids"] is None
    assert s["status"] == "ok" and harness.published


def test_unreadable_recipe_list_fails_the_run(harness, monkeypatch):
    """Without the recipe list every recipe'd source would look recipe-less
    and get a needs-authoring issue — so nothing may be queued."""
    def _boom():
        raise RuntimeError("github down")

    monkeypatch.setattr(rf, "recipe_repo_from_env",
                        lambda: SimpleNamespace(list_ids=_boom))
    s = _run()
    assert s["status"] in pipeline.FAILED_RUN_STATUSES
    assert harness.queued == [] and harness.refresh_kw is None and not harness.published


def test_override_with_recipe_refreshes_only_it(harness):
    harness.refreshed = ["rec1"]
    s = _run(override_id="rec1")
    assert harness.refresh_kw["only_ids"] == ["rec1"]
    assert harness.refresh_kw["force"] is True  # "render it now", even if up to date
    assert harness.picked_with is None and harness.queued == []
    assert s["status"] == "ok"


def test_override_without_recipe_queues_it(harness):
    s = _run(override_id="solo")
    assert harness.refresh_kw is None
    assert harness.queued == [("solo", "new")]
    assert s["status"] == "idle"


def test_override_never_queues_a_source_without_readable_data(harness):
    harness.sources["solo"] = SourceRecord(id="solo", title="s", analysis_status="restricted")
    s = _run(override_id="solo")
    assert harness.queued == [] and s["status"] == "idle"


def test_dry_run_lists_queue_but_touches_nothing(harness):
    s = _run(dry_run=True)
    assert s["selected_for_authoring"] == ["new1", "old1"]
    assert harness.queued == [] and harness.refresh_kw is None
    assert s["status"] == "dry_run"


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


def test_unchanged_refresh_does_not_publish(harness, monkeypatch):
    """REFRESH_PRECHECK: a CKAN bump the precheck proved a no-op leaves the
    live page standing — no publish dispatch for it."""
    harness.selected = []
    monkeypatch.setattr(
        rf, "run_refresh",
        lambda store, repo, **kw: {"refreshed": [], "unchanged": ["rec1"],
                                   "failed": [], "outcomes": []},
    )
    s = _run()
    assert s["status"] == "idle" and not harness.published


def test_staging_down_fails_the_run_but_still_queues_and_publishes(harness, monkeypatch):
    harness.refreshed = ["rec1"]
    monkeypatch.setattr(
        rf, "run_refresh",
        lambda store, repo, **kw: {"refreshed": ["rec1"], "failed": ["x"],
                                   "staging_down": True, "outcomes": []},
    )
    s = _run()
    assert s["status"] == "refresh_failed" and s["status"] in pipeline.FAILED_RUN_STATUSES
    assert harness.queued and harness.published


def test_refresh_crash_fails_the_run(harness, monkeypatch):
    def _boom(store, repo, **kw):
        raise RuntimeError("bug")

    monkeypatch.setattr(rf, "run_refresh", _boom)
    s = _run()
    assert s["status"] == "refresh_failed" and harness.queued


def test_queue_failure_still_publishes_and_goes_red(harness, monkeypatch):
    """Nothing between the refresh and the publish dispatch may cost the
    publish: refreshed pages reach the site even if the queue breaks."""
    harness.refreshed = ["rec1"]

    def _boom(store, src, reason, **kw):
        if src.id == "new1":
            raise RuntimeError("firestore deadline")
        harness.queued.append((src.id, reason))
        return 7

    monkeypatch.setattr(rf, "queue_authoring", _boom)
    s = _run()
    assert harness.published and harness.queued == [("old1", "legacy_updated")]
    assert s["status"] == "authoring_failed" and s["status"] in pipeline.FAILED_RUN_STATUSES


def test_selector_failure_does_not_block_the_refresh(harness, monkeypatch):
    harness.refreshed = ["rec1"]

    def _boom(store, n, **kw):
        raise RuntimeError("missing index")

    monkeypatch.setattr(pipeline.selector, "pick_authoring_candidates", _boom)
    s = _run()
    assert harness.refresh_kw is not None and harness.published
    assert s["status"] == "authoring_failed"


def _outcome(i, status, reason=None, **kw):
    return dict(rf.RefreshOutcome(i, status, reason=reason, **kw).__dict__)


def test_summary_log_is_compact_and_drops_up_to_date():
    summary = {
        "mode": "scheduled", "status": "ok", "build_id": "gh",
        "authoring_queued": [{"id": "new1", "reason": "new", "issue": 7}],
        "refresh": {
            "refreshed": ["a"], "unchanged": ["b"], "failed": ["c"],
            "outcomes": [_outcome("a", "refreshed", insights=["תובנה"]),
                         _outcome("b", "unchanged", "content_hash"),
                         _outcome("c", "failed", "schema_changed", error="boom", issue=9)]
                        + [_outcome(f"u{i}", "skipped", "up_to_date") for i in range(300)],
        },
    }
    lines = pipeline.summarize_for_log(summary)
    assert len(lines) == 4 and all("\n" not in ln for ln in lines)
    head = json.loads(lines[0])["pipeline_summary"]
    assert head["status"] == "ok" and head["authoring_queued"][0]["issue"] == 7
    assert "outcomes" not in head["refresh"]
    assert head["refresh"]["counts"] == {
        "failed:schema_changed": 1, "refreshed": 1,
        "skipped:up_to_date": 300, "unchanged:content_hash": 1,
    }
    outs = [json.loads(ln)["refresh_outcome"] for ln in lines[1:]]
    assert [o["id"] for o in outs] == ["a", "b", "c"]
    assert outs[2]["issue"] == 9 and "kpis" not in outs[0]   # empty fields dropped
    assert "תובנה" in lines[1]                               # readable, not \u-escaped
    assert summary["refresh"]["outcomes"]                      # input untouched


def test_summary_log_without_a_refresh():
    lines = pipeline.summarize_for_log({"status": "refresh_unavailable", "refresh": None})
    assert [json.loads(ln) for ln in lines] == [
        {"pipeline_summary": {"status": "refresh_unavailable", "refresh": None}}
    ]
