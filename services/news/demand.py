"""Search demand per dataset page, from Google Search Console.

Last `days` of impressions/clicks per page for sc-domain:govil.ai, mapped to
dataset ids through the catalog's page slugs. The ranking multiplier is
1 + 0.25·log10(1 + impressions): 1.0 with no data, ~1.75 at 1,000
impressions, ~2.0 at 10,000 — demand tips close calls, it can't lift a
non-story over a real one. Fails soft (no access, quota, network) → {}.

Credentials are ADC with `webmasters.readonly`; the job's service account
must be added as a (restricted) user on the Search Console property.
"""
from __future__ import annotations

import logging
import math
import os
from datetime import date, timedelta
from urllib.parse import unquote, urlparse

log = logging.getLogger(__name__)

SITE = os.environ.get("NEWS_GSC_SITE", "sc-domain:govil.ai")
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
ENDPOINT = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
# GSC reports with a ~2-day lag; ending the window there avoids a short last day.
LAG_DAYS = 2


def fetch_page_rows(days: int = 28, *, today: date | None = None, session=None) -> list[dict]:
    """[{page, impressions, clicks}] for the window."""
    from urllib.parse import quote

    end = (today or date.today()) - timedelta(days=LAG_DAYS)
    body = {"startDate": (end - timedelta(days=days - 1)).isoformat(), "endDate": end.isoformat(),
            "dimensions": ["page"], "rowLimit": 25000}
    try:
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            creds, project = google.auth.default(scopes=[SCOPE])
            session = AuthorizedSession(creds)
            if not hasattr(creds, "service_account_email"):
                # User ADC needs a quota project for this API; a service
                # account bills its own project.
                session.headers["x-goog-user-project"] = (
                    os.environ.get("GOOGLE_CLOUD_PROJECT") or project or "govdata-il")
        r = session.post(ENDPOINT.format(site=quote(SITE, safe="")), json=body, timeout=60)
        r.raise_for_status()
        rows = r.json().get("rows") or []
    except Exception:
        log.warning("demand: Search Console unavailable — neutral demand", exc_info=True)
        return []
    return [{"page": row["keys"][0], "impressions": row.get("impressions", 0),
             "clicks": row.get("clicks", 0)} for row in rows]


def dataset_demand(rows: list[dict], catalog: dict[str, dict]) -> dict[str, dict]:
    """id → {impressions, clicks}, summed over every URL of the dataset page."""
    by_slug = {c["page_slug"]: i for i, c in catalog.items()}
    out: dict[str, dict] = {}
    for row in rows:
        parts = [p for p in unquote(urlparse(row["page"]).path).split("/") if p]
        if len(parts) != 2 or parts[0] != "datasets":
            continue
        ds = by_slug.get(parts[1]) or (parts[1] if parts[1] in catalog else None)
        if ds is None:
            continue
        acc = out.setdefault(ds, {"impressions": 0, "clicks": 0})
        acc["impressions"] += row["impressions"]
        acc["clicks"] += row["clicks"]
    return out


def multiplier(impressions: float) -> float:
    return round(1 + 0.25 * math.log10(1 + max(impressions, 0)), 3)
