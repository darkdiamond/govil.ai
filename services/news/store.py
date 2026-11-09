"""Where articles live.

Firestore `articles/<slug>`: queryable metadata (status, dates, dataset_ids,
signal_keys, tags, headline…) plus `body_json` — blocks, charts, sources and
the fact ledger as one JSON string (Firestore rejects arrays of arrays, which
chart tables are). Rejected drafts go to `article_rejects/<id>` with their
reasons, for tuning. Images go to `gs://<staging>/news/<slug>/` (the publisher
rsyncs `news/` like `datasets/`).

`LocalArticles` mirrors this in a directory, for `run --dry-run --out DIR`.
"""
from __future__ import annotations

import json
import mimetypes
from datetime import UTC, datetime, timedelta
from pathlib import Path

ARTICLES, REJECTS = "articles", "article_rejects"
META_FIELDS = ("slug", "status", "headline", "dek", "published_at", "updated_at", "byline",
               "dataset_ids", "tags", "signal_keys", "hero", "run_id", "models", "words",
               "critic_scores", "correction")
BODY_FIELDS = ("blocks", "charts", "sources", "ledger")


def split(doc: dict) -> dict:
    """An article doc → its Firestore shape."""
    out = {k: doc[k] for k in META_FIELDS if k in doc}
    out["body_json"] = json.dumps({k: doc.get(k) for k in BODY_FIELDS}, ensure_ascii=False, default=str)
    return out


def join(stored: dict) -> dict:
    out = {k: v for k, v in stored.items() if k != "body_json"}
    out.update(json.loads(stored.get("body_json") or "{}"))
    return out


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


class FirestoreArticles:
    def __init__(self, *, client=None, bucket: str | None = None, prefix: str = "news/"):
        from google.cloud import firestore

        self.db = client or firestore.Client()
        self.bucket_name, self.prefix = bucket, prefix

    def recent(self, days: int = 90) -> list[dict]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        since = datetime.now(UTC) - timedelta(days=days)
        q = self.db.collection(ARTICLES).where(filter=FieldFilter("published_at", ">=", since))
        out = []
        for d in q.stream():
            x = d.to_dict() or {}
            x.pop("body_json", None)
            x["published_at"] = _iso(x.get("published_at"))
            out.append(x)
        return sorted(out, key=lambda a: str(a.get("published_at")), reverse=True)

    def slug_taken(self, slug: str) -> bool:
        return self.db.collection(ARTICLES).document(slug).get().exists

    def publish(self, doc: dict, files: dict[str, bytes]) -> None:
        if files:
            if not self.bucket_name:
                raise RuntimeError("no staging bucket for article images")
            from google.cloud import storage

            bucket = storage.Client().bucket(self.bucket_name)
            for name, data in files.items():
                blob = bucket.blob(f"{self.prefix}{doc['slug']}/{name}")
                blob.upload_from_string(data, content_type=mimetypes.guess_type(name)[0]
                                        or "application/octet-stream")
        stored = split(doc)
        for k in ("published_at", "updated_at"):
            if isinstance(stored.get(k), str):
                stored[k] = datetime.fromisoformat(stored[k])
        self.db.collection(ARTICLES).document(doc["slug"]).set(stored)

    def reject(self, doc: dict) -> None:
        self.db.collection(REJECTS).add(json.loads(json.dumps(doc, ensure_ascii=False, default=str)))

    def set_status(self, slug: str, status: str, *, correction: str | None = None) -> None:
        upd = {"status": status, "updated_at": datetime.now(UTC)}
        if correction:
            upd["correction"] = correction
        self.db.collection(ARTICLES).document(slug).update(upd)

    def iter_published(self):
        from google.cloud.firestore_v1.base_query import FieldFilter

        for d in self.db.collection(ARTICLES).where(
                filter=FieldFilter("status", "in", ["published", "corrected"])).stream():
            x = join(d.to_dict() or {})
            x["published_at"], x["updated_at"] = _iso(x.get("published_at")), _iso(x.get("updated_at"))
            yield x


class LocalArticles:
    def __init__(self, root: Path, *, seed: list[dict] | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._seed = seed or []   # e.g. prod's recent articles, read-only, for cooldown in a dry run

    def recent(self, days: int = 90) -> list[dict]:
        out = list(self._seed)
        for p in sorted(self.root.glob("*/article.json")):
            out.append(json.loads(p.read_text(encoding="utf-8")))
        return out

    def slug_taken(self, slug: str) -> bool:
        return (self.root / slug / "article.json").exists() or any(a.get("slug") == slug for a in self._seed)

    def publish(self, doc: dict, files: dict[str, bytes]) -> None:
        d = self.root / doc["slug"]
        d.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (d / name).write_bytes(data)
        (d / "article.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                                        encoding="utf-8")

    def reject(self, doc: dict) -> None:
        d = self.root / "_rejected"
        d.mkdir(exist_ok=True)
        n = len(list(d.glob("*.json"))) + 1
        (d / f"{n:03d}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                                         encoding="utf-8")
