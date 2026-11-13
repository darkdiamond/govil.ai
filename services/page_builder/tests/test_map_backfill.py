"""map_backfill: which datasets get an issue, a comment, or nothing."""
from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.page_builder import map_backfill as mb
from services.page_builder.recipe import Recipe

FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
DS = "11111111-2222-3333-4444-555555555555"
GEO = "cccccccc-0000-0000-0000-000000000003"


def _map(types: dict, error: str = "") -> mb.MapFile:
    return mb.MapFile(GEO, "layer", "ZIP", features=sum(types.values()),
                      geometry_types=types, crs="itm", columns=["NAME"], error=error)


def _recipe(tmp_path, *, template_extra: str = "", inputs_extra: list | None = None) -> Recipe:
    root = tmp_path / "recipes" / DS
    shutil.copytree(FIXTURES / DS, root)
    if template_extra:
        t = root / "template.html.j2"
        t.write_text(t.read_text(encoding="utf-8") + template_extra, encoding="utf-8")
    if inputs_extra:
        m = json.loads((root / "recipe.json").read_text())
        m["inputs"] += inputs_extra
        (root / "recipe.json").write_text(json.dumps(m, ensure_ascii=False))
    return Recipe.load(root)


def _cand(*maps) -> mb.Candidate:
    return mb.Candidate(SimpleNamespace(id=DS, title="t"), list(maps))


def test_recipe_without_a_map_gets_an_issue(tmp_path):
    c = _cand(_map({"LineString": 3}))
    mb.classify(c, _recipe(tmp_path), open_issue=None)
    assert c.kind == "issue" and "no map" in c.why


@pytest.mark.parametrize("types, kind", [
    ({"Point": 9}, "mapped"),              # its map already shows the points
    ({"Polygon": 2}, "issue"),             # points on the page, shapes in the file
])
def test_recipe_with_a_point_map(tmp_path, types, kind):
    r = _recipe(tmp_path, template_extra='<div id="map-x"></div>')
    c = _cand(_map(types))
    mb.classify(c, r, open_issue=None)
    assert c.kind == kind


def test_recipe_already_reading_the_file_is_mapped(tmp_path):
    r = _recipe(tmp_path, inputs_extra=[{"name": "geo", "by_id": GEO, "map": True}])
    c = _cand(_map({"LineString": 3}))
    mb.classify(c, r, open_issue=None)
    assert c.kind == "mapped"


def test_recipe_with_an_open_issue_gets_a_comment(tmp_path):
    c = _cand(_map({"LineString": 3}))
    mb.classify(c, _recipe(tmp_path), open_issue=301)
    assert c.kind == "comment" and c.issue == 301 and "no map" in c.why


def test_no_recipe_routes_by_open_issue():
    c = _cand(_map({"LineString": 3}))
    mb.classify(c, None, open_issue=226)
    assert c.kind == "comment" and c.issue == 226
    c = _cand(_map({"LineString": 3}))
    mb.classify(c, None, open_issue=None)
    assert c.kind == "no_recipe"


def test_all_files_failed_is_failed():
    c = _cand(_map({}, error="DownloadBlocked: HTTP 403"))
    mb.classify(c, None, open_issue=226)
    assert c.kind == "failed" and "403" in c.why


def test_open_refuses_past_the_cap():
    cands = [_cand(_map({"LineString": 1})) for _ in range(3)]
    for c in cands:
        c.kind = "issue"
    with pytest.raises(SystemExit, match="--max-new"):
        mb.open_all(store=None, cands=cands, max_new=2)


def test_open_records_each_issue_like_queue_authoring():
    calls = []
    store = SimpleNamespace(
        mark_authoring_needed=lambda i, r: calls.append(("needed", i, r)),
        set_authoring_issue=lambda i, n: calls.append(("notified", i, n)),
    )
    c = _cand(_map({"LineString": 1}))
    c.kind = "issue"
    done = mb.open_all(store, [c], max_new=5, open_issue=lambda c: 401)
    assert done["opened"] == [(DS, 401)]
    assert calls == [("needed", DS, "map_available"), ("notified", DS, 401)]


def test_open_keeps_going_after_one_failure():
    calls = []
    store = SimpleNamespace(
        mark_authoring_needed=lambda i, r: calls.append(i),
        set_authoring_issue=lambda i, n: None,
    )
    a, b = _cand(_map({"LineString": 1})), _cand(_map({"LineString": 1}))
    b.src = SimpleNamespace(id="22222222-0000-0000-0000-000000000000", title="t2")
    a.kind = b.kind = "issue"

    def flaky(c):
        if c is a:
            raise ValueError("gh issue create printed no issue URL")
        return 7

    done = mb.open_all(store, [a, b], max_new=5, open_issue=flaky)
    assert done["opened"] == [(b.src.id, 7)]
    assert done["errors"][0][0] == DS and calls == [b.src.id]


def test_open_issue_uses_the_job_title_and_parses_the_url(monkeypatch):
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(stdout="https://github.com/darkdiamond/govil.ai/issues/512\n")

    monkeypatch.setattr(mb.subprocess, "run", run)
    c = _cand(_map({"LineString": 3}))
    c.src = SimpleNamespace(id=DS, title="דרכים", organization={"title": "משרד"})
    assert mb._open_issue(c) == 512
    cmd = seen["cmd"]
    assert cmd[cmd.index("--title") + 1] == f"[author] דרכים ({DS[:8]})"
    body = cmd[cmd.index("--body") + 1]
    assert "`map_available`" in body and "Map files (untrusted)" in body
    assert "Refresh error" not in body
    monkeypatch.setattr(mb.subprocess, "run", lambda cmd, **kw: SimpleNamespace(stdout="oops"))
    with pytest.raises(ValueError, match="no issue URL"):
        mb._open_issue(c)


def test_declined_issues_are_never_asked_again(tmp_path, monkeypatch):
    src = SimpleNamespace(
        id=DS, title="t", provider=None, analysis_status="succeeded",
        metadata_modified=datetime(2026, 10, 1, tzinfo=UTC),
        resources=[{"id": GEO, "format": "ZIP", "datastore_active": False, "url": "x"}],
    )
    monkeypatch.setattr(mb, "_iter_sources", lambda store: iter([src]))

    def no_download(res, dest):
        raise AssertionError("a declined dataset is never downloaded")

    out = mb.find_candidates(None, floor=datetime(2025, 1, 1, tzinfo=UTC),
                             recipes_root=tmp_path, issues={}, declined={DS[:8]},
                             download=no_download)
    assert [c.kind for c in out] == ["declined"]


def test_detail_lists_only_downloadable_files():
    c = _cand(_map({"LineString": 3}), _map({}, error="SnapshotError: x"))
    text = mb.detail_text(c)
    assert "LineString" in text and "SnapshotError" not in text


def _gh(monkeypatch, body: str, comments: list[str]):
    """Fake `gh`: `issue view` answers with `body` + `comments`; every call is recorded."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "view"]:
            return SimpleNamespace(stdout=json.dumps(
                {"body": body, "comments": [{"body": b} for b in comments]}))
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(mb.subprocess, "run", run)
    return calls


def _commented(calls) -> list:
    return [c for c in calls if c[:3] == ["gh", "issue", "comment"]]


def test_comment_posts_once_then_a_rerun_finds_it(monkeypatch):
    c = _cand(_map({"LineString": 3}))
    c.kind, c.issue = "comment", 41
    calls = _gh(monkeypatch, "an old recipe_failed issue", [])
    done = mb.open_all(None, [c], max_new=0)
    assert done["commented"] == [(DS, 41)] and len(_commented(calls)) == 1
    posted = _commented(calls)[0]
    posted_body = posted[posted.index("--body") + 1]

    calls = _gh(monkeypatch, "an old recipe_failed issue", [posted_body])
    done = mb.open_all(None, [c], max_new=0)
    assert done["already"] == [(DS, 41)] and done["commented"] == []
    assert _commented(calls) == []


def test_an_issue_body_with_the_map_details_gets_no_comment(monkeypatch):
    c = _cand(_map({"LineString": 3}))
    c.kind, c.issue = "comment", 41
    calls = _gh(monkeypatch, mb.detail_text(c).replace("`", "'"), [])
    assert mb.open_all(None, [c], max_new=0)["already"] == [(DS, 41)]
    assert _commented(calls) == []


def test_a_new_map_file_is_still_announced(monkeypatch):
    old, new = _map({"LineString": 3}), _map({"Polygon": 2})
    new.resource_id = "dddddddd-0000-0000-0000-000000000004"
    c = _cand(old, new)
    c.kind, c.issue = "comment", 41
    calls = _gh(monkeypatch, "", [f"earlier comment naming '{GEO}'"])
    assert mb.open_all(None, [c], max_new=0)["commented"] == [(DS, 41)]
    assert len(_commented(calls)) == 1
