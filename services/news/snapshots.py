"""Read the page-model history the builder writes
(`refresh._stage_model_history`): models/<id>/<UTC ts>.json.gz, plus a
latest.json.gz copy that this reader does not trust (it is written second and
can lag on a partial failure) — the newest timestamped object is the latest.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger(__name__)

_TS_NAME = re.compile(r"^(\d{8}T\d{6}Z)\.json(?:\.gz)?$")


@dataclass
class Snapshot:
    dataset_id: str
    rendered_at: str | None
    recipe_version: int | None
    metadata_modified: str | None
    model: dict

    @property
    def data_as_of(self) -> date | None:
        """The day the data describes: its CKAN/provider version, else the render."""
        for v in (self.metadata_modified, self.rendered_at):
            if not v:
                continue
            try:
                return datetime.fromisoformat(v).date()
            except ValueError:
                try:
                    return datetime.strptime(v, "%Y%m%dT%H%M%SZ").date()
                except ValueError:
                    continue
        return None

    @classmethod
    def from_doc(cls, dataset_id: str, doc: dict) -> Snapshot:
        if "model" in doc and isinstance(doc["model"], dict):
            return cls(doc.get("dataset_id") or dataset_id, doc.get("rendered_at"),
                       doc.get("recipe_version"), doc.get("metadata_modified"), doc["model"])
        return cls(dataset_id, None, None, None, doc)  # a bare model (local dumps)


def _decode(data: bytes) -> dict:
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return json.loads(data.decode("utf-8"))


class GcsSnapshots:
    def __init__(self, bucket: str, prefix: str = "models/"):
        from google.cloud import storage

        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)
        self.prefix = prefix if prefix.endswith("/") else prefix + "/"

    def ids(self) -> list[str]:
        it = self._client.list_blobs(self._bucket, prefix=self.prefix, delimiter="/")
        for _ in it:  # prefixes fill in as the pages are consumed
            pass
        return sorted(p[len(self.prefix):].rstrip("/") for p in it.prefixes)

    def names(self, dataset_id: str) -> list[tuple[str, str]]:
        """(timestamp, object name) of every snapshot, newest first."""
        out = []
        for b in self._client.list_blobs(self._bucket, prefix=f"{self.prefix}{dataset_id}/"):
            if m := _TS_NAME.match(b.name.rsplit("/", 1)[-1]):
                out.append((m[1], b.name))
        return sorted(out, reverse=True)

    def load(self, dataset_id: str, ref: str) -> Snapshot:
        return Snapshot.from_doc(dataset_id, _decode(self._bucket.blob(ref).download_as_bytes()))


class LocalSnapshots:
    """A directory of `<id>.json` (a snapshot doc or a bare model) and/or
    `<id>/<ts>.json[.gz]` — for development and tests."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def ids(self) -> list[str]:
        out = {p.stem for p in self.root.glob("*.json")}
        out |= {p.name for p in self.root.iterdir() if p.is_dir()}
        return sorted(out)

    def names(self, dataset_id: str) -> list[tuple[str, str]]:
        d = self.root / dataset_id
        if d.is_dir():
            return sorted(((m[1], str(p)) for p in d.iterdir() if (m := _TS_NAME.match(p.name))),
                          reverse=True)
        f = self.root / f"{dataset_id}.json"
        return [("", str(f))] if f.is_file() else []  # a bare dump: no timestamp

    def load(self, dataset_id: str, ref: str) -> Snapshot:
        return Snapshot.from_doc(dataset_id, _decode(Path(ref).read_bytes()))


def latest_and_baseline(store, dataset_id: str,
                        cutoff: str | None) -> tuple[Snapshot | None, Snapshot | None, bool]:
    """(latest snapshot, the one to diff it against, rendered since cutoff).

    The baseline is the newest snapshot rendered before `cutoff` (the last
    news run, as a `YYYYmmddTHHMMSSZ` stamp): everything that appeared after
    it is new to the news job, however many renders that took. With no
    cutoff it is simply the previous render. A latest snapshot older than
    the cutoff means nothing re-rendered since the last run: it is still
    returned (as context for cross-dataset links) with `False`, and no
    baseline. No baseline otherwise → signals fall back to date freshness."""
    names = store.names(dataset_id)
    if not names:
        return None, None, False
    latest = store.load(dataset_id, names[0][1])
    latest_ts = names[0][0]
    if cutoff and latest_ts and latest_ts < cutoff:
        return latest, None, False
    if cutoff:
        base = next((ref for ts, ref in names[1:] if ts and ts < cutoff), None)
    else:
        base = names[1][1] if len(names) > 1 else None
    return latest, (store.load(dataset_id, base) if base else None), True
