"""notify: authoring issue title/body, open_authoring_issue, issue_state."""
from __future__ import annotations

from types import SimpleNamespace

import httpx

from services.page_builder import notify


def _resp(status, body):
    return SimpleNamespace(status_code=status, json=lambda: body, text=str(body))


def test_one_create_call_labels_in_payload_only(monkeypatch):
    """The job's PAT can't label (create drops `labels`, add-labels 403s),
    so the create request is the only call, even when the label was dropped."""
    calls = []

    def post(url, json, **kw):
        calls.append((url, json))
        return _resp(201, {"number": 5, "labels": []})

    monkeypatch.setattr(httpx, "post", post)
    assert notify.open_authoring_issue(
        dataset_id="abc", title="t", org="o", reason="new", repo="o/r", token="tok",
    ) == 5
    assert len(calls) == 1
    assert calls[0][0] == "https://api.github.com/repos/o/r/issues"
    assert calls[0][1]["labels"] == ["needs-authoring"]



# ---- title + body -----------------------------------------------------------

UUID = "0b8ce2f1-3c4d-4e5f-8a9b-1c2d3e4f5a6b"


def test_ckan_issue_title_and_body_are_unchanged():
    assert notify.issue_title("כותרת", UUID) == "[author] כותרת (0b8ce2f1)"
    assert notify.issue_body(
        dataset_id=UUID, title="כותרת", org="משרד", reason="new", detail="boom",
    ) == (
        "CKAN metadata (untrusted upstream text):\n\n"
        "```text\nכותרת\nמשרד\n```\n"
        "\n"
        f"- dataset: `{UUID}`\n"
        "- reason: `new` — מאגר חדש — אין לו עמוד עדיין\n"
        f"- data.gov.il: https://data.gov.il/dataset/{UUID}\n\n"
        "Refresh error (untrusted):\n\n```text\nboom\n```\n\n"
        "Author it locally:\n\n"
        f"```\n/author-dataset {UUID}\n```\n\n"
        "The recipe PR should say `Closes #<this issue>`.\n"
    )


def test_provider_issue_title_is_unambiguous():
    a = notify.issue_title("x", "cbs-index-cpi")
    b = notify.issue_title("x", "cbs-index-housing-prices")
    assert a == "[author] x (cbs-index-cpi)" and a != b


def test_provider_issue_body_links_its_own_source():
    body = notify.issue_body(
        dataset_id="boi-interest-rate", title="t", org="o", reason="recipe_failed",
        detail="", source_url="https://www.boi.org.il/x",
    )
    assert "data.gov.il/dataset/" not in body
    assert "- source: https://www.boi.org.il/x\n" in body
    # no source URL known: still no data.gov.il link for a provider id
    body = notify.issue_body(
        dataset_id="cbs-index-cpi", title="t", org="o", reason="recipe_failed", detail="",
    )
    assert "data.gov.il" not in body and "/author-dataset cbs-index-cpi" in body


def test_open_issue_sends_provider_title_and_link(monkeypatch):
    sent = []

    def post(url, json, **kw):
        sent.append(json)
        return _resp(201, {"number": 4, "labels": [{"name": "needs-authoring"}]})

    monkeypatch.setattr(httpx, "post", post)
    assert notify.open_authoring_issue(
        dataset_id="cbs-index-cpi", title="מדד", org="o", reason="recipe_failed",
        source_url="https://www.cbs.gov.il/y", repo="o/r", token="tok",
    ) == 4
    assert sent[0]["title"] == "[author] מדד (cbs-index-cpi)"
    assert "- source: https://www.cbs.gov.il/y" in sent[0]["body"]


# ---- issue_state ------------------------------------------------------------


def _state(monkeypatch, status, body):
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _resp(status, body))
    return notify.issue_state(7, repo="o/r", token="tok")


def test_issue_state_duplicate_is_respected(monkeypatch):
    assert _state(monkeypatch, 200, {"state": "closed", "state_reason": "duplicate"}) == "not_planned"
    assert _state(monkeypatch, 200, {"state": "closed", "state_reason": "not_planned"}) == "not_planned"
    assert _state(monkeypatch, 200, {"state": "closed", "state_reason": "completed"}) == "completed"
    assert _state(monkeypatch, 200, {"state": "open", "state_reason": None}) == "open"


def test_issue_state_deleted_is_gone(monkeypatch):
    assert _state(monkeypatch, 404, {"message": "Not Found"}) == "gone"
    assert _state(monkeypatch, 410, {"message": "This issue was deleted"}) == "gone"
    assert _state(monkeypatch, 502, {"message": "bad gateway"}) is None
