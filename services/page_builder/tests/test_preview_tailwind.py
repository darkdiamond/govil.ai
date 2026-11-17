"""cli.preview: a body staged while nuxt dev runs gets its classes compiled.

Vite watches only the content files that matched Tailwind's glob at the last
CSS compile, so a content.html created after it needs a rescan: stage()
touches a sentinel the server watches from its start (_rescan_tailwind)."""
from __future__ import annotations

import os
import types

import pytest

from services.page_builder import author
from services.page_builder.cli import preview

DS = "00000000-0000-0000-0000-0000000000aa"
OTHER = "00000000-0000-0000-0000-0000000000bb"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(author, "AUTHORING_ROOT", tmp_path / "authoring")
    monkeypatch.setattr(preview, "base_manifest_path", lambda: None)
    return tmp_path / "preview"


def _page(cls: str):
    return types.SimpleNamespace(content_html=f'<div class="{cls}">x</div>',
                                 agent_data={"summary_he": "בדיקה", "dataset_kind": "misc"},
                                 warnings=[])


def _server(monkeypatch, running: bool, root=None) -> list:
    touched = []
    monkeypatch.setattr(preview, "_read_server", lambda root: {"pid": 1, "port": 3100} if running else None)
    monkeypatch.setattr(preview, "_is_ours", lambda info: running)
    real = os.utime
    monkeypatch.setattr(preview.os, "utime", lambda p, *a, **k: (touched.append(p), real(p, *a, **k)))
    if running and root is not None:
        preview._write_sentinel(root)  # as _ensure_server does before starting it
    return touched


def test_new_body_touches_the_sentinel_of_a_running_server(root, monkeypatch):
    touched = _server(monkeypatch, running=True, root=root)
    preview.stage(DS, _page("h-[30rem]"), {}, root=root)
    sentinel = root / "datasets" / preview.RESCAN_SENTINEL
    assert touched == [sentinel] and sentinel.is_file()
    preview.stage(OTHER, _page("h-[31rem]"), {}, root=root)
    assert touched == [sentinel, sentinel]


def test_rewrite_of_a_staged_body_does_not_touch(root, monkeypatch):
    touched = _server(monkeypatch, running=True, root=root)
    preview.stage(DS, _page("h-[30rem]"), {}, root=root)
    preview.stage(DS, _page("h-[32rem]"), {}, root=root)  # a watched file: Vite recompiles
    assert len(touched) == 1


def test_no_server_no_touch(root, monkeypatch):
    touched = _server(monkeypatch, running=False)
    preview.stage(DS, _page("h-[30rem]"), {}, root=root)
    assert touched == []  # the server that starts later compiles every body


def test_sentinel_created_after_the_server_started_warns(root, monkeypatch, capsys):
    touched = _server(monkeypatch, running=True)  # no sentinel: a server older than it
    preview.stage(DS, _page("h-[30rem]"), {}, root=root)
    assert touched == []  # a file no watch list holds: touching it does nothing
    assert (root / "datasets" / preview.RESCAN_SENTINEL).is_file()
    assert "preview stop" in capsys.readouterr().err


def test_sentinel_is_not_a_dataset(root, monkeypatch, capsys):
    _server(monkeypatch, running=True, root=root)
    preview.stage(DS, _page("h-[30rem]"), {}, root=root)
    assert (root / "datasets" / preview.RESCAN_SENTINEL).is_file()
    preview.status(root)
    out = capsys.readouterr().out
    assert DS in out and preview.RESCAN_SENTINEL not in out
    manifest = (root / "data" / "manifest.json").read_text(encoding="utf-8")
    assert DS in manifest and "rescan" not in manifest


def test_sentinel_matches_the_preview_content_glob():
    config = (preview.FRONTEND / "tailwind.config.ts").read_text(encoding="utf-8")
    assert "${PREVIEW_ROOT}/datasets/**/*.html" in config
    assert preview.RESCAN_SENTINEL.endswith(".html")
    assert not preview.RESCAN_SENTINEL.startswith(".")  # globs skip dotfiles
