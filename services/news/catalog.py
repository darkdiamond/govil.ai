"""Dataset titles, slugs and kinds, from the live site's search index (what
the publisher last deployed). Read from the Firebase origin, not the
Cloudflare-fronted domain, so a cached edge copy can't lag. Fails soft: no
catalog just means signals print with ids and demand stays neutral."""
from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)

SITE_ORIGIN = os.environ.get("NEWS_SITE_ORIGIN", "https://govdata-il.web.app")
UA = "Mozilla/5.0 (compatible; govdata-news/1.0)"


def load_catalog(origin: str = SITE_ORIGIN, timeout: float = 30) -> dict[str, dict]:
    """id → {title, page_slug, dataset_kind, organization, tags}."""
    url = f"{origin.rstrip('/')}/data/search-index.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            doc = json.loads(r.read().decode("utf-8"))
    except Exception:
        log.warning("catalog: %s unreadable — signals keep bare ids", url, exc_info=True)
        return {}
    out = {}
    for d in doc.get("datasets") or []:
        org = d.get("organization")
        out[d["id"]] = {
            "title": d.get("title") or "",
            "page_slug": d.get("page_slug") or d["id"],
            "dataset_kind": d.get("dataset_kind"),
            "organization": (org.get("title") if isinstance(org, dict) else org) or "",
            "tags": d.get("tags") or [],
            "metadata_modified": d.get("metadata_modified"),
        }
    return out
