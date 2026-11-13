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
import re

from services.shared import github
from services.shared.states import AuthoringReason

log = logging.getLogger(__name__)

AUTHORING_LABEL = "needs-authoring"

REASON_TEXT: dict[AuthoringReason, str] = {
    AuthoringReason.NEW: "מאגר חדש — אין לו עמוד עדיין",
    AuthoringReason.LEGACY_UPDATED: "עמוד ישן (נכתב ע״י סוכן בענן) והנתונים התעדכנו — אין לו מתכון",
    AuthoringReason.RECIPE_FAILED: "המתכון נכשל על הנתונים החדשים",
    AuthoringReason.SCHEMA_CHANGED: "מבנה הנתונים השתנה (משאב/עמודה חסרים)",
    AuthoringReason.TOO_LARGE: "המאגר גדל מעבר לתקרת הרענון",
    AuthoringReason.GEOMETRY_STALE: "קובץ המפה התעדכן — עדיף להחליף את קלט ה-`snapshot` בקלט `map: true` "
                      "(הריצה מורידה אותו בעצמה); אחרת להוריד אותו שוב בדפדפן ולהריץ `author snapshot`",
    AuthoringReason.DOWNLOAD_BLOCKED: "הורדת קובץ המפה נחסמה כמה ריצות ברצף (403 או דף HTML) — "
                        "לבדוק את CKAN_USER_AGENT או לעבור לקלט `snapshot`",
    AuthoringReason.SANDBOX_BROKEN: "סביבת ההרצה של compute נכשלה כמה ריצות ברצף (לא המתכון) — "
                      "לבדוק את אימג' הבילדר (GRPC_ENABLE_FORK_SUPPORT, מסנן הרשת) ולפרוס מחדש",
    AuthoringReason.GSC_TRAFFIC: "עמוד ישן בלי מתכון שמקבל תנועה מחיפוש — הנתונים לא השתנו, ולכן הריצה היומית לא תפתח עליו בקשה",
    AuthoringReason.MAP_AVAILABLE: "למאגר יש קובץ מפה שהריצה יכולה להוריד — יש להוסיף למתכון קלט `map: true`",
}


def _fenced(text: str) -> str:
    """A code block whose content can't close it early. CKAN titles and
    refresh errors are upstream text, and the daily authoring agent reads
    these issues, so they're shown as inert data, never as markdown."""
    return "```text\n" + text.replace("`", "'") + "\n```\n"


_CKAN_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _is_ckan_id(dataset_id: str) -> bool:
    return bool(_CKAN_ID.match(dataset_id))


def issue_title(title: str, dataset_id: str) -> str:
    """`[author] <title> (<id8>)`: the authoring routine finds issues by it.
    A provider id (`cbs-index-cpi`) goes in whole: its first 8 characters
    are shared by several recipes."""
    tag = dataset_id[:8] if _is_ckan_id(dataset_id) else dataset_id
    return f"[author] {title[:80]} ({tag})"


def issue_body(
    *, dataset_id: str, title: str, org: str, reason: str, detail: str,
    detail_caption: str = "Refresh error", source_url: str | None = None,
) -> str:
    # A provider source has no data.gov.il page: link its own, if known.
    if source_url:
        link = f"- source: {source_url}\n\n"
    elif _is_ckan_id(dataset_id):
        link = f"- data.gov.il: https://data.gov.il/dataset/{dataset_id}\n\n"
    else:
        link = "\n"
    return (
        "CKAN metadata (untrusted upstream text):\n\n"
        + _fenced(f"{title}\n{org}")
        + "\n"
        f"- dataset: `{dataset_id}`\n"
        f"- reason: `{reason}` — {REASON_TEXT.get(reason, reason)}\n"
        + link
        + (f"{detail_caption} (untrusted):\n\n{_fenced(detail[:1500])}\n" if detail else "")
        + "Author it locally:\n\n"
        f"```\n/author-dataset {dataset_id}\n```\n\n"
        f"The recipe PR should say `Closes #<this issue>`.\n"
    )


def _github(token: str | None, repo: str | None) -> tuple[str, str]:
    """Explicit args, else the job's env (the publish-dispatch PAT + repo)."""
    return (token or "").strip() or github.token(), repo or github.default_repo()


def open_authoring_issue(
    *,
    dataset_id: str,
    title: str,
    org: str,
    reason: str,
    detail: str = "",
    source_url: str | None = None,
    repo: str | None = None,
    token: str | None = None,
) -> int | None:
    """Open the issue; return its number, or None if it couldn't be opened
    (missing token, API error) — the caller retries on the next run."""
    token, repo = _github(token, repo)
    if not token:
        log.warning("authoring needed for %s (%s) but no GitHub token set", dataset_id, reason)
        return None
    import httpx

    try:
        r = httpx.post(
            f"{github.API}/repos/{repo}/issues",
            json={
                "title": issue_title(title, dataset_id),
                "body": issue_body(
                    dataset_id=dataset_id, title=title, org=org,
                    reason=reason, detail=detail, source_url=source_url,
                ),
                "labels": [AUTHORING_LABEL],
            },
            headers=github.api_headers(token),
            timeout=30.0,
            follow_redirects=True,
        )
    except Exception:
        log.exception("opening authoring issue for %s failed", dataset_id)
        return None
    if r.status_code != 201:
        log.error("authoring issue for %s: %s %s", dataset_id, r.status_code, r.text[:300])
        return None
    # GitHub silently drops `labels` on create unless the token has push
    # access, which the job's Issues-only PAT doesn't, and the add-labels
    # endpoint 403s for it too (2026-10-30). So no label call is made: the
    # authoring routine lists issues by author + the `[author] … (<id8>)`
    # title, labelled or not. `labels` stays in the create payload, where
    # it costs nothing and works if the token ever gains push access.
    return int(r.json()["number"])


def issue_state(
    number: int, *, repo: str | None = None, token: str | None = None
) -> str | None:
    """`open`, `completed` (closed as done, e.g. by a recipe PR),
    `not_planned` (closed as won't-author or as a duplicate), or `gone`
    (deleted: 404/410, so no live issue is left). None when it can't be
    read; the caller then keeps the recorded issue rather than risk a
    duplicate."""
    token, repo = _github(token, repo)
    if not token:
        return None
    import httpx

    try:
        r = httpx.get(
            f"{github.API}/repos/{repo}/issues/{number}",
            headers=github.api_headers(token),
            timeout=30.0,
            follow_redirects=True,
        )
    except Exception:
        log.exception("reading issue #%s failed", number)
        return None
    if r.status_code in (404, 410):
        log.warning("issue #%s is gone (%s)", number, r.status_code)
        return "gone"
    if r.status_code != 200:
        log.error("reading issue #%s: %s %s", number, r.status_code, r.text[:300])
        return None
    data = r.json()
    if data.get("state") == "open":
        return "open"
    if data.get("state_reason") in ("not_planned", "duplicate"):
        return "not_planned"
    return "completed"
