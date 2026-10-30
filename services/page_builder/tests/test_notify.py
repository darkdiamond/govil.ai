"""notify.open_authoring_issue: labels survive a token without push access."""
from __future__ import annotations

from types import SimpleNamespace

import httpx

from services.page_builder import notify


def _resp(status, body):
    return SimpleNamespace(status_code=status, json=lambda: body, text=str(body))


def _open(monkeypatch, create_labels):
    calls = []

    def post(url, json, **kw):
        calls.append((url, json))
        if url.endswith("/issues"):
            return _resp(201, {"number": 5, "labels": [{"name": n} for n in create_labels]})
        return _resp(200, [{"name": n} for n in json["labels"]])

    monkeypatch.setattr(httpx, "post", post)
    n = notify.open_authoring_issue(
        dataset_id="abc", title="t", org="o", reason="new", preview=True,
        repo="o/r", token="tok",
    )
    return n, calls


def test_dropped_labels_are_added_explicitly(monkeypatch):
    n, calls = _open(monkeypatch, create_labels=[])
    assert n == 5
    assert calls[1] == (
        "https://api.github.com/repos/o/r/issues/5/labels",
        {"labels": ["needs-authoring", "preview"]},
    )


def test_no_extra_call_when_create_kept_labels(monkeypatch):
    n, calls = _open(monkeypatch, create_labels=["needs-authoring", "preview"])
    assert n == 5 and len(calls) == 1


def test_label_failure_still_returns_issue(monkeypatch):
    calls = []

    def post(url, json, **kw):
        calls.append(url)
        if url.endswith("/issues"):
            return _resp(201, {"number": 9, "labels": []})
        return _resp(403, {"message": "Resource not accessible"})

    monkeypatch.setattr(httpx, "post", post)
    assert notify.open_authoring_issue(
        dataset_id="abc", title="t", org="o", reason="new", repo="o/r", token="tok"
    ) == 9
    # one create + two label attempts
    assert calls.count("https://api.github.com/repos/o/r/issues/9/labels") == 2


def test_label_retry_succeeds_on_second_attempt(monkeypatch):
    attempts = []

    def post(url, json, **kw):
        if url.endswith("/issues"):
            return _resp(201, {"number": 3, "labels": []})
        attempts.append(url)
        return _resp(502 if len(attempts) == 1 else 200, [])

    monkeypatch.setattr(httpx, "post", post)
    assert notify.open_authoring_issue(
        dataset_id="abc", title="t", org="o", reason="new", repo="o/r", token="tok"
    ) == 3
    assert len(attempts) == 2


def test_partial_labels_on_create_are_completed(monkeypatch):
    n, calls = _open(monkeypatch, create_labels=["needs-authoring"])
    assert n == 5 and len(calls) == 2
