"""Tell the human a dataset needs (re-)authoring: one GitHub issue per dataset.

Authoring happens locally with Claude Code (`/author-dataset <id>`), never in
the cloud, so the nightly job's only job here is to make the need visible.
An issue per dataset gets GitHub's email/mobile notifications for free and
closes itself when the recipe PR says `Closes #N`.

Idempotent by construction: the caller stores the issue number on the
dataset's refresh state and never asks again while one is recorded.
Needs GITHUB_DISPATCH_TOKEN with Issues:write on the repo (the same
fine-grained PAT that fires the publish dispatch).
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
}


def issue_body(
    *, dataset_id: str, title: str, org: str, reason: str, detail: str, preview: bool
) -> str:
    lane = "preview (demo lane)" if preview else "production"
    return (
        f"**{title}**\n"
        f"{org}\n\n"
        f"- dataset: `{dataset_id}`\n"
        f"- reason: `{reason}` — {REASON_TEXT.get(reason, reason)}\n"
        f"- lane: {lane}\n"
        f"- data.gov.il: https://data.gov.il/dataset/{dataset_id}\n\n"
        + (f"```\n{detail[:1500]}\n```\n\n" if detail else "")
        + "Author it locally:\n\n"
        f"```\n/author-dataset {dataset_id}\n```\n\n"
        f"The recipe PR should say `Closes #<this issue>`.\n"
    )


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
    token = (token or os.environ.get("GITHUB_DISPATCH_TOKEN", "")).strip()
    repo = repo or os.environ.get("PUBLISH_GITHUB_REPO", "darkdiamond/govil.ai")
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
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
            follow_redirects=True,
        )
    except Exception:
        log.exception("opening authoring issue for %s failed", dataset_id)
        return None
    if r.status_code != 201:
        log.error("authoring issue for %s: %s %s", dataset_id, r.status_code, r.text[:300])
        return None
    return int(r.json()["number"])
