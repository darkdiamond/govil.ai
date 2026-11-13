"""Where articles live.

Firestore `articles/<slug>` (in the separate `news` database): queryable metadata (status, dates, dataset_ids,
signal_keys, tags, headline…) plus `body_json` — blocks, charts, sources and
the fact ledger as one JSON string (Firestore rejects arrays of arrays, which
chart tables are). Rejected drafts go to `article_rejects/<id>` with their
reasons, for tuning. Images go to `gs://<staging>/news/<slug>/` (the publisher
rsyncs `news/` like `datasets/`).

The run's cursor — the end of the render window the last successful live run
covered (a `YYYYmmddTHHMMSSZ` stamp) — is `news_state/cursor` in the same
database: the next run reads everything rendered from there on, whenever it
runs (services/news/run.py `news_window`).

`news_state/daily` records which once-a-day duties a run already attempted on
an Israel date (`digest_attempt` / `floor_attempt`: an ISO date, plus the
run id), so hourly runs try the weekly digest and the floor fill once
(run.py `write_day`). `news_state/lock` is the run lease (services/shared/lease.py).

`news_state/control` `{publish: "live" | "off"}` is the kill switch a deploy
can't reset (`admin publish on|off|status`). A live run publishes only when
both it and the job's NEWS_PUBLISH say live; a missing doc (or field) follows
the env, and a read error counts as off (run.py `_kill_switch`).

`signal_pool/<hash of key>` holds the signals the editor saw but didn't use,
the weekly digest's raw material (digest.py), kept POOL_KEEP_DAYS.

`LocalArticles` mirrors this in a directory, for `run --dry-run --out DIR`.
"""
from __future__ import annotations

import json
import mimetypes
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

ARTICLES, REJECTS, POOL = "articles", "article_rejects", "signal_pool"
POOL_KEEP_DAYS = 14
STATE, CURSOR, DAILY, LOCK, CONTROL = "news_state", "cursor", "daily", "lock", "control"
PUBLISH_MODES = ("live", "off")
LOCK_DOC = f"{STATE}/{LOCK}"
META_FIELDS = ("slug", "status", "headline", "dek", "published_at", "updated_at", "byline",
               "dataset_ids", "tags", "signal_keys", "hero", "run_id", "models", "words",
               "critic_scores", "correction", "kind")
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


def _pool_id(key: str) -> str:
    """Signal keys hold '/' and brackets; a Firestore id can't hold '/'."""
    import hashlib

    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:24]


LIVE_STATUSES = ("published", "corrected")


def published_at(a: dict) -> datetime | None:
    """An article's (or reject's) timestamp as an aware datetime: `published_at`
    (ISO string or datetime), else a reject's `at`; None when unreadable."""
    ts = a.get("published_at") or a.get("at")
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return None
    if not isinstance(ts, datetime):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


NEWS_DATABASE = os.environ.get("NEWS_FIRESTORE_DATABASE", "news")


class FirestoreArticles:
    """Articles live in their own Firestore database (`news`, not the
    default one that holds `sources/`): IAM can't scope a grant to a
    collection, but it can to a database, so the news job — an LLM agent
    reading the open web — can write articles without being able to touch
    the dataset state every page is built from (infra/news-iam.setup.sh)."""

    def __init__(self, *, client=None, project: str | None = None,
                 database: str = NEWS_DATABASE, bucket: str | None = None, prefix: str = "news/"):
        from google.cloud import firestore

        self.db = client or firestore.Client(
            project=project or os.environ.get("FIRESTORE_PROJECT_ID")
            or os.environ.get("GOOGLE_CLOUD_PROJECT"), database=database)
        self.bucket_name, self.prefix = bucket, prefix

    def read_cursor(self) -> str | None:
        """The stamp the last successful live run's window ended at, or None."""
        snap = self.db.collection(STATE).document(CURSOR).get()
        return (snap.to_dict() or {}).get("upto") if snap.exists else None

    def read_publish_flag(self) -> str | None:
        """`news_state/control.publish`, lower-cased, or None when the doc or
        the field is missing (the env decides). Read errors propagate."""
        snap = self.db.collection(STATE).document(CONTROL).get()
        if not snap.exists:
            return None
        value = (snap.to_dict() or {}).get("publish")
        if value is None:
            return None
        return str(value).strip().lower() or None

    def set_publish_flag(self, mode: str) -> None:
        if mode not in PUBLISH_MODES:
            raise ValueError(f"publish flag must be one of {PUBLISH_MODES}, not {mode!r}")
        self.db.collection(STATE).document(CONTROL).set(
            {"publish": mode, "at": datetime.now(UTC)}, merge=True)

    def _transact(self, fn):
        """Run `fn(transaction)` in a Firestore transaction (retried on
        contention). A seam: tests replace it with a fake transaction."""
        from google.cloud import firestore

        return firestore.transactional(fn)(self.db.transaction())

    def advance_cursor(self, upto: str, *, run_id: str) -> bool:
        """Move the cursor to `upto`; never backwards (a slower overlapping
        run must not re-open a window a later one already closed). The read
        and the write are one transaction, so two runs finishing together
        can't interleave a stale read with a write."""
        ref = self.db.collection(STATE).document(CURSOR)

        def _txn(transaction) -> bool:
            snap = ref.get(transaction=transaction)
            current = (snap.to_dict() or {}).get("upto") if snap.exists else None
            if current and current >= upto:
                return False
            transaction.set(ref, {"upto": upto, "run_id": run_id, "at": datetime.now(UTC)})
            return True

        return self._transact(_txn)

    def read_daily(self) -> dict:
        """`news_state/daily`: {"<duty>_attempt": ISO Israel date, ...} ({} when none)."""
        snap = self.db.collection(STATE).document(DAILY).get()
        return (snap.to_dict() or {}) if snap.exists else {}

    def mark_duty(self, duty: str, il_date: str, *, run_id: str) -> None:
        """Record that `duty` ("digest" | "floor") was attempted on `il_date`."""
        self.db.collection(STATE).document(DAILY).set(
            {f"{duty}_attempt": il_date, f"{duty}_run_id": run_id,
             f"{duty}_at": datetime.now(UTC)}, merge=True)

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

    def pool(self, items: list[dict]) -> None:
        """Keep signals the editor saw but didn't use, for the weekly digest
        (`signal_pool/<hash of key>`, the latest sighting wins), and drop
        entries older than POOL_KEEP_DAYS."""
        from google.cloud.firestore_v1.base_query import FieldFilter

        col = self.db.collection(POOL)
        now = datetime.now(UTC)
        for it in items:
            col.document(_pool_id(it["signal"]["key"])).set(it | {"pooled_at": now})
        old = col.where(filter=FieldFilter("pooled_at", "<", now - timedelta(days=POOL_KEEP_DAYS)))
        for d in old.stream():
            d.reference.delete()

    def read_pool(self, days: int = 7) -> list[dict]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        since = datetime.now(UTC) - timedelta(days=days)
        q = self.db.collection(POOL).where(filter=FieldFilter("pooled_at", ">=", since))
        return [x | {"pooled_at": _iso(x.get("pooled_at"))}
                for x in (d.to_dict() or {} for d in q.stream())]

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

    def recent_rejects(self, days: int = 7) -> list[dict]:
        """Rejected drafts of the last `days`: kind, brief, reason (no bodies).
        `at` is stored as an ISO string, so the range compares as text."""
        from google.cloud.firestore_v1.base_query import FieldFilter

        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        q = self.db.collection(REJECTS).where(filter=FieldFilter("at", ">=", since))
        return [{k: x.get(k) for k in ("at", "kind", "brief", "reason")}
                for x in (d.to_dict() or {} for d in q.stream())]

    def set_status(self, slug: str, status: str, *, correction: str | None = None) -> None:
        upd = {"status": status, "updated_at": datetime.now(UTC)}
        if correction:
            upd["correction"] = correction
        self.db.collection(ARTICLES).document(slug).update(upd)

    def iter_published(self):
        from google.cloud.firestore_v1.base_query import FieldFilter

        for d in self.db.collection(ARTICLES).where(
                filter=FieldFilter("status", "in", list(LIVE_STATUSES))).stream():
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

    def pool(self, items: list[dict]) -> None:
        d = self.root / "_pool"
        d.mkdir(exist_ok=True)
        now = datetime.now(UTC).isoformat()
        for it in items:
            (d / f"{_pool_id(it['signal']['key'])}.json").write_text(
                json.dumps(it | {"pooled_at": now}, ensure_ascii=False, default=str), encoding="utf-8")

    def read_pool(self, days: int = 7) -> list[dict]:
        since = datetime.now(UTC) - timedelta(days=days)
        out = []
        for p in sorted((self.root / "_pool").glob("*.json")):
            it = json.loads(p.read_text(encoding="utf-8"))
            if datetime.fromisoformat(it["pooled_at"]) >= since:
                out.append(it)
        return out

    def publish(self, doc: dict, files: dict[str, bytes]) -> None:
        d = self.root / doc["slug"]
        d.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (d / name).write_bytes(data)
        (d / "article.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                                        encoding="utf-8")

    def read_daily(self) -> dict:
        p = self.root / "_state" / "daily.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}

    def mark_duty(self, duty: str, il_date: str, *, run_id: str) -> None:
        d = self.root / "_state"
        d.mkdir(exist_ok=True)
        cur = self.read_daily() | {f"{duty}_attempt": il_date, f"{duty}_run_id": run_id}
        (d / "daily.json").write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")

    def reject(self, doc: dict) -> None:
        d = self.root / "_rejected"
        d.mkdir(exist_ok=True)
        n = len(list(d.glob("*.json"))) + 1
        (d / f"{n:03d}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                                         encoding="utf-8")

    def recent_rejects(self, days: int = 7) -> list[dict]:
        since = datetime.now(UTC) - timedelta(days=days)
        out = []
        for p in sorted((self.root / "_rejected").glob("*.json")):
            x = json.loads(p.read_text(encoding="utf-8"))
            ts = published_at(x)
            if ts and ts >= since:
                out.append({k: x.get(k) for k in ("at", "kind", "brief", "reason")})
        return out
