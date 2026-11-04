"""Shared helpers for picking a 'primary' resource on a CKAN dataset.

The agent + scanner + builder all want to anchor on the same resource for
a given dataset (the one most likely to be the actual data file). Keeping
the priority order in one place avoids drift.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

PRIMARY_FORMAT_PRIORITY: tuple[str, ...] = (
    "CSV", "GEOJSON", "JSON", "XLSX", "XML",
)

_FORMAT_RANK = {fmt: i for i, fmt in enumerate(PRIMARY_FORMAT_PRIORITY)}
_NAME_EXT_RE = re.compile(r"\.(csv|xlsx|xls|json|xml|geojson|kml)\s*$")


def _accessor(item: Any, key: str) -> Any:
    """Read `key` from either a dict or a pydantic/dataclass object."""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def pick_primary_resource_id(resources: Sequence[Any]) -> str | None:
    """Return the id of the most agent-friendly resource on a dataset.

    Walks `PRIMARY_FORMAT_PRIORITY` in order; first hit wins. Falls back
    to the first resource. Returns `None` if `resources` is empty.
    Accepts dicts or `.format`/`.id`-bearing objects.
    """
    for fmt in PRIMARY_FORMAT_PRIORITY:
        for r in resources:
            if (_accessor(r, "format") or "").upper() == fmt:
                return _accessor(r, "id")
    if not resources:
        return None
    return _accessor(resources[0], "id")


def _normalized_name(name: str | None, fmt: str | None) -> str:
    """Grouping key for format-duplicate detection.

    CKAN datasets that publish the same table as CSV+XLSX(+JSON) name the
    twins identically up to an extension or a trailing format token
    ("שמות רחובות csv" / "שמות רחובות xlsx"). Strip those, collapse
    separators, lowercase.
    """
    s = (name or "").strip().lower()
    s = _NAME_EXT_RE.sub("", s)
    fmt_l = (fmt or "").strip().lower()
    if fmt_l:
        s = re.sub(rf"[\s\-_]*{re.escape(fmt_l)}\s*$", "", s)
    return re.sub(r"[\s\-_]+", " ", s).strip()


def select_prefetch_resources(resources: Sequence[Any]) -> list[dict]:
    """The datastore-active resources worth prefetching, primary first.

    - keeps only ``datastore_active`` resources (docs/PDF attachments are
      never datastore-ingested, so they drop out here);
    - the dataset's primary resource (``pick_primary_resource_id`` over ALL
      resources) leads when it is datastore-active; the rest follow in CKAN
      order;
    - format duplicates — same normalized name published in several formats
      — collapse to the best format per ``PRIMARY_FORMAT_PRIORITY``.

    Returns plain dicts ``{"id", "name", "format"}``. Accepts dicts or
    ``.format``/``.id``-bearing objects, like ``pick_primary_resource_id``.
    """
    active = [
        {
            "id": _accessor(r, "id"),
            "name": _accessor(r, "name") or "",
            "format": (_accessor(r, "format") or "").upper(),
        }
        for r in (resources or [])
        if _accessor(r, "datastore_active") and _accessor(r, "id")
    ]
    if not active:
        return []

    primary_id = pick_primary_resource_id(resources)
    active.sort(key=lambda r: r["id"] != primary_id)  # stable: primary first

    # Group format twins; keep the best-ranked format per group. An empty
    # normalized name can't prove duplication, so it never groups.
    best: dict[str, dict] = {}
    order: list[str] = []
    for r in active:
        key = _normalized_name(r["name"], r["format"]) or f"id:{r['id']}"
        cur = best.get(key)
        if cur is None:
            best[key] = r
            order.append(key)
        elif cur["id"] != primary_id and (
            _FORMAT_RANK.get(r["format"], len(_FORMAT_RANK))
            < _FORMAT_RANK.get(cur["format"], len(_FORMAT_RANK))
        ):
            best[key] = r
    return [best[k] for k in order]
