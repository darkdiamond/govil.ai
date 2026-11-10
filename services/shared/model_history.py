"""The page-model history format: one writer (`refresh._stage_model_history`,
after every staged render) and one reader (`services.news.snapshots`).

Objects live at `models/<id>/<UTC ts>.json.gz`, plus a `latest.json.gz` copy
(written second; a reader trusts the newest timestamped object instead). Each
holds a gzipped JSON doc: `dataset_id`, `rendered_at` (the ts), `recipe_version`,
`metadata_modified` and `model` (`history_model` of the page model).
Light at import (stdlib only).
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime

PREFIX = "models"
TS_FORMAT = "%Y%m%dT%H%M%SZ"
LATEST_NAME = "latest.json.gz"
# A value (top-level, or one level inside a top-level dict) whose JSON is
# bigger than this is replaced by a marker in the stored model.
MAX_VALUE_BYTES = 2_000_000

_TS_NAME = re.compile(r"^(\d{8}T\d{6}Z)\.json(?:\.gz)?$")


def history_model(model: dict) -> dict:
    """The page model as kept for history (read by the news job): `tables`
    dropped (row dumps, not series) and any value — top-level, or one level
    inside a top-level dict (a chart, a KPI) — whose JSON tops
    MAX_VALUE_BYTES replaced by a marker, so one outsized value can't bloat
    every snapshot."""

    def capped(v):
        size = len(json.dumps(v, ensure_ascii=False, default=str))
        return v if size <= MAX_VALUE_BYTES else {"__omitted_bytes__": size}

    return {
        k: ({kk: capped(vv) for kk, vv in v.items()} if isinstance(v, dict) else capped(v))
        for k, v in model.items() if k != "tables"
    }


def stamp(now: datetime) -> str:
    """The object timestamp for a render at `now` (UTC)."""
    return now.strftime(TS_FORMAT)


def object_names(dataset_id: str, ts: str) -> tuple[str, str]:
    """(timestamped object, latest copy) for one render, in write order."""
    return (f"{PREFIX}/{dataset_id}/{ts}.json.gz", f"{PREFIX}/{dataset_id}/{LATEST_NAME}")


def ts_of(name: str) -> str | None:
    """The timestamp of a timestamped object's basename (`<ts>.json[.gz]`), else
    None (e.g. latest.json.gz)."""
    m = _TS_NAME.match(name.rsplit("/", 1)[-1])
    return m[1] if m else None


def encode(dataset_id: str, model: dict, *, ts: str, recipe_version: int | None,
           metadata_modified: datetime | None) -> bytes:
    """The stored bytes: deterministic gzip (mtime 0) of sorted-key JSON."""
    return gzip.compress(json.dumps(
        {"dataset_id": dataset_id, "rendered_at": ts, "recipe_version": recipe_version,
         "metadata_modified": metadata_modified.isoformat() if metadata_modified else None,
         "model": history_model(model)},
        ensure_ascii=False, default=str, sort_keys=True,
    ).encode("utf-8"), mtime=0)


def decode(data: bytes) -> dict:
    """A stored doc (gzipped, or plain JSON for local dumps)."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return json.loads(data.decode("utf-8"))
