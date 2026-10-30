"""Tell the human a dataset needs (re-)authoring: one GitHub issue per dataset.

Authoring happens locally with Claude Code (`/author-dataset <id>`, or the
daily `/solve-authoring-issues` routine that batches open issues into one
PR), never in the cloud job, so the daily job's only job here is to make the
need visible. An issue per dataset gets GitHub's email/mobile notifications
for free and closes itself when the recipe PR says `Closes #N`.

Idempotent by construction: the caller stores the issue number on the
dataset's refresh state and doesn't ask again while that issue is open (or
was closed as not planned). Needs GITHUB_DISPATCH_TOKEN with Issues:write
on the repo (the same fine-grained PAT that fires the publish dispatch).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

AUTHORING_LABEL = "needs-authoring"

REASON_TEXT = {
    "new": "מאגר חדש — אין לו עמוד עדיין",
    "legacy_updated": "עמוד ישן (נכתב ע״י סוכן בענן) והנתונים התעדכנו — אין לו מתכון",
    "recipe_failed": "המתכון נכשל על הנתונים החדשים",
    "schema_changed": "מבנה הנתונים השתנה (משאב/עמודה חסרים)",
    "too_large": "המאגר גדל מעבר לתקרת הרענון",
    "geometry_stale": "קובץ המפה התעדכן — יש להוריד אותו שוב בדפדפן ולהריץ `author snapshot`",
}


def _fenced(text: str) -> str:
    """A code block whose content can't close it early. CKAN titles and
    refresh errors are upstream text, and the daily authoring agent reads
    these issues, so they're shown as inert data, never as markdown."""
    return "```text\n" + text.replace("`", "'") + "\n```\n"


def issue_body(
    *, dataset_id: str, title: str, org: str, reason: str, detail: str, preview: bool
) -> str:
    lane = "preview (demo lane)" if preview else "production"
    return (
        "CKAN metadata (untrusted upstream text):\n\n"
        + _fenced(f"{title}\n{org}")
        + "\n"
        f"- dataset: `{dataset_id}`\n"
        f"- reason: `{reason}` — {REASON_TEXT.get(reason, reason)}\n"
        f"- lane: {lane}\n"
        f"- data.gov.il: https://data.gov.il/dataset/{dataset_id}\n\n"
        + (f"Refresh error (untrusted):\n\n{_fenced(detail[:1500])}\n" if detail else "")
        + "Author it locally:\n\n"
        f"```\n/author-dataset {dataset_id}\n```\n\n"
        f"The recipe PR should say `Closes #<this issue>`.\n"
    )


def _github(token: Optional[str], repo: Optional[str]) -> tuple[str, str]:
    """Explicit args, else the job's env (the publish-dispatch PAT + repo)."""
    return (
        (token or os.environ.get("GITHUB_DISPATCH_TOKEN", "")).strip(),
        repo or os.environ.get("PUBLISH_GITHUB_REPO", "darkdiamond/govil.ai"),
    )


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def open_authoring_issue(
    *,
    dataset_id: str,
    title: str,
    org: str,
    reason: str,
    detail: str = "",
    preview: bool = False,
    repo: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[int]:
    """Open the issue; return its number, or None if it couldn't be opened
    (missing token, API error) — the caller retries on the next run."""
    token, repo = _github(token, repo)
    if not token:
        log.warning("authoring needed for %s (%s) but no GitHub token set", dataset_id, reason)
        return None
    import httpx

    labels = [AUTHORING_LABEL] + (["preview"] if preview else [])
    try:
        r = httpx.post(
            f"https://api.github.com/repos/{repo}/issues",
            json={
                "title": f"[author] {title[:80]} ({dataset_id[:8]})",
                "body": issue_body(
                    dataset_id=dataset_id, title=title, org=org,
                    reason=reason, detail=detail, preview=preview,
                ),
                "labels": labels,
            },
            headers=_headers(token),
            timeout=30.0,
            follow_redirects=True,
        )
    except Exception:
        log.exception("opening authoring issue for %s failed", dataset_id)
        return None
    if r.status_code != 201:
        log.error("authoring issue for %s: %s %s", dataset_id, r.status_code, r.text[:300])
        return None
    created = r.json()
    number = int(created["number"])
    # GitHub silently drops `labels` on create unless the token has push
    # access, which the job's Issues-only PAT doesn't — so issues #112–#236
    # opened unlabelled and the authoring routine (which lists by label)
    # never saw them. The add-labels endpoint needs only Issues:write and
    # fails loudly. The issue stays recorded either way: a label failure
    # must not open a duplicate next run, so nothing here may raise. The
    # source is then `notified` and never re-queued, so an unlabelled issue
    # stays invisible to the routine: retry once, then log what to run.
    try:
        have = {lb.get("name") for lb in created.get("labels") or [] if isinstance(lb, dict)}
        if not set(labels) <= have and not any(
            add_labels(number, labels, repo=repo, token=token) for _ in range(2)
        ):
            log.error(
                "issue #%s for %s is unlabelled and invisible to the authoring routine; "
                "label it by hand: gh issue edit %s --repo %s --add-label %s",
                number, dataset_id, number, repo, ",".join(labels),
            )
    except Exception:
        log.exception("labelling issue #%s failed", number)
    return number


def add_labels(
    number: int, labels: list[str], *, repo: Optional[str] = None, token: Optional[str] = None
) -> bool:
    """Add labels to an existing issue; True on success."""
    token, repo = _github(token, repo)
    if not token:
        return False
    import httpx

    try:
        r = httpx.post(
            f"https://api.github.com/repos/{repo}/issues/{number}/labels",
            json={"labels": labels},
            headers=_headers(token),
            timeout=30.0,
            follow_redirects=True,
        )
    except Exception:
        log.exception("labelling issue #%s failed", number)
        return False
    if r.status_code != 200:
        log.error("labelling issue #%s: %s %s", number, r.status_code, r.text[:300])
        return False
    return True


def issue_state(
    number: int, *, repo: Optional[str] = None, token: Optional[str] = None
) -> Optional[str]:
    """`open`, `completed` (closed as done — e.g. by a recipe PR), or
    `not_planned` (closed as won't-author). None when it can't be read; the
    caller then keeps the recorded issue rather than risk a duplicate."""
    token, repo = _github(token, repo)
    if not token:
        return None
    import httpx

    try:
        r = httpx.get(
            f"https://api.github.com/repos/{repo}/issues/{number}",
            headers=_headers(token),
            timeout=30.0,
            follow_redirects=True,
        )
    except Exception:
        log.exception("reading issue #%s failed", number)
        return None
    if r.status_code != 200:
        log.error("reading issue #%s: %s %s", number, r.status_code, r.text[:300])
        return None
    data = r.json()
    if data.get("state") == "open":
        return "open"
    return "not_planned" if data.get("state_reason") == "not_planned" else "completed"
