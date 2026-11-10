"""GitHub REST settings shared by the builder job, the news job and the
authoring tools: the repo, the PAT, the request headers, and the publish
workflow dispatch. Light at import (httpx is imported on use)."""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

DEFAULT_REPO = "darkdiamond/govil.ai"
API = "https://api.github.com"


def default_repo() -> str:
    """`PUBLISH_GITHUB_REPO`, else this repo."""
    return os.environ.get("PUBLISH_GITHUB_REPO", "").strip() or DEFAULT_REPO


def token() -> str:
    """`GITHUB_DISPATCH_TOKEN` (the job's fine-grained PAT), or ""."""
    return os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()


def api_headers(tok: str | None = None) -> dict[str, str]:
    """REST v3 headers, with a bearer token when one is given."""
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def dispatch_workflow(repo: str, workflow: str, ref: str) -> str | None:
    """Fire a workflow_dispatch (blocking). Returns a synthetic marker for the
    run summary (the API answers 204 with no run id), or None when there is no
    token or GitHub answers anything but 204. A transport error (timeout, DNS,
    TLS) raises httpx's exception: callers that must not fail wrap the call.

    Needs GITHUB_DISPATCH_TOKEN with Actions:write on `repo`.
    """
    tok = token()
    if not tok:
        log.error("workflow dispatch needs GITHUB_DISPATCH_TOKEN, which is not set")
        return None
    import httpx

    # follow_redirects: GitHub answers a renamed repo with a 307 that
    # preserves the POST method + body. Without this a repo rename
    # silently breaks the daily publish dispatch (govdata→govil.ai did
    # exactly that — 307 → logged failure, pages built but not deployed).
    r = httpx.post(
        f"{API}/repos/{repo}/actions/workflows/{workflow}/dispatches",
        json={"ref": ref},
        headers=api_headers(tok),
        timeout=30.0,
        follow_redirects=True,
    )
    if r.status_code != 204:
        log.error("github workflow_dispatch failed: %s %s", r.status_code, r.text[:300])
        return None
    return f"gh-actions:{repo}/{workflow}@{ref}"
