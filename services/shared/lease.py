"""A run lease in one Firestore document, so two job executions never overlap.

`acquire(client, "job_state/run", holder, ttl_s)` takes the lease in a
transaction when nobody holds it, the holder's lease expired, or `holder`
already holds it (a re-acquire extends it); otherwise it answers False.
`release` clears it only if `holder` still holds it. The doc holds `holder`,
`expires_at` and `acquired_at`.

Import-light (the shared-layer rule): google-cloud-firestore is imported
inside the functions that need it.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _aware(dt):
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _live_other(data: dict | None, holder: str, now: datetime) -> bool:
    """Whether `data` is a lease another holder still holds at `now`."""
    if not data:
        return False
    current = data.get("holder")
    expires = _aware(data.get("expires_at"))
    if not current or current == holder:
        return False
    return isinstance(expires, datetime) and expires > now


def _run_in_transaction(client, fn):
    """Run `fn(transaction)` in a Firestore transaction (retried on contention).
    A seam: tests replace it to run `fn` against a fake transaction."""
    from google.cloud import firestore

    return firestore.transactional(fn)(client.transaction())


def acquire(client, doc_path: str, holder: str, ttl_s: float,
            now: datetime | None = None) -> bool:
    """Take (or extend) the lease at `doc_path` for `holder` for `ttl_s`
    seconds. True when there was no lease, it had expired, or `holder`
    already held it; False while another holder's lease is live. Firestore
    errors propagate."""
    now = _aware(now) or datetime.now(UTC)
    ref = client.document(doc_path)

    def _txn(transaction) -> bool:
        snap = ref.get(transaction=transaction)
        data = snap.to_dict() if snap.exists else None
        if _live_other(data, holder, now):
            return False
        transaction.set(ref, {"holder": holder, "acquired_at": now,
                              "expires_at": now + timedelta(seconds=ttl_s)})
        return True

    return _run_in_transaction(client, _txn)


def release(client, doc_path: str, holder: str) -> None:
    """Clear the lease if `holder` still holds it. A missing doc, or another
    holder's lease, is left as is."""
    ref = client.document(doc_path)

    def _txn(transaction) -> None:
        snap = ref.get(transaction=transaction)
        if snap.exists and (snap.to_dict() or {}).get("holder") == holder:
            transaction.delete(ref)

    _run_in_transaction(client, _txn)


class Heartbeat:
    """Keeps a lease alive while its holder works: a daemon thread re-acquires
    (extends) it every `interval_s` (default a third of `ttl_s`). So the TTL
    can be short: a run that is killed without releasing (task timeout, OOM)
    blocks the next ticks for at most `ttl_s`, not for a whole run's length.
    A failed or refused renewal is logged and retried at the next beat; the
    work goes on (stopping it midway would be worse than a rare overlap)."""

    def __init__(self, client, doc_path: str, holder: str, ttl_s: float,
                 interval_s: float | None = None):
        import threading

        self._args = (client, doc_path, holder, ttl_s)
        self._interval = interval_s if interval_s is not None else max(1.0, ttl_s / 3)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, name="lease-heartbeat", daemon=True)

    def _beat(self) -> None:
        import logging

        log = logging.getLogger("shared.lease")
        client, doc_path, holder, ttl_s = self._args
        while not self._stop.wait(self._interval):
            try:
                if not acquire(client, doc_path, holder, ttl_s):
                    log.error("lease %s: renewal refused, another holder took it "
                              "(this run was too slow to renew)", doc_path)
            except Exception:
                log.exception("lease %s: renewal failed; retrying at the next beat", doc_path)

    def start(self) -> Heartbeat:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=10)
