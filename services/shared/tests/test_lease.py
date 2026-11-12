"""services/shared/lease: acquire / held / expired takeover / re-acquire /
release only by the holder. Runs on a fake Firestore client; the same cases
run against the emulator when FIRESTORE_EMULATOR_HOST is set."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from services.shared import lease

T0 = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _Ref:
    def __init__(self, docs, path):
        self.docs, self.path = docs, path

    def get(self, transaction=None):
        return _Snap(self.docs.get(self.path))


class _Txn:
    def set(self, ref, data):
        ref.docs[ref.path] = dict(data)

    def delete(self, ref):
        ref.docs.pop(ref.path, None)


class _Client:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def document(self, path):
        return _Ref(self.docs, path)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(lease, "_run_in_transaction", lambda client, fn: fn(_Txn()))
    return _Client()


def _emulator_client():
    from google.cloud import firestore
    return firestore.Client(project=os.environ.get("FIRESTORE_PROJECT_ID", "local-dev"))


def _clients(request):
    if request.param == "fake":
        return request.getfixturevalue("fake"), "job_state/run"
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        pytest.skip("needs the Firestore emulator (FIRESTORE_EMULATOR_HOST)")
    return _emulator_client(), f"lease_test/{uuid.uuid4().hex}"


@pytest.fixture(params=["fake", "emulator"])
def client_and_path(request):
    return _clients(request)


def _holder(client, path):
    if isinstance(client, _Client):
        return (client.docs.get(path) or {}).get("holder")
    snap = client.document(path).get()
    return (snap.to_dict() or {}).get("holder") if snap.exists else None


def test_acquire_when_free(client_and_path):
    client, path = client_and_path
    assert lease.acquire(client, path, "a", 60, now=T0) is True
    assert _holder(client, path) == "a"


def test_live_lease_of_another_holder_blocks(client_and_path):
    client, path = client_and_path
    assert lease.acquire(client, path, "a", 60, now=T0)
    assert lease.acquire(client, path, "b", 60, now=T0 + timedelta(seconds=59)) is False
    assert _holder(client, path) == "a"


def test_expired_lease_is_taken_over(client_and_path):
    client, path = client_and_path
    assert lease.acquire(client, path, "a", 60, now=T0)
    assert lease.acquire(client, path, "b", 60, now=T0 + timedelta(seconds=60)) is True
    assert _holder(client, path) == "b"


def test_holder_re_acquires_and_extends(client_and_path):
    client, path = client_and_path
    assert lease.acquire(client, path, "a", 60, now=T0)
    assert lease.acquire(client, path, "a", 60, now=T0 + timedelta(seconds=30)) is True
    # Extended to T0+90s: still live for another holder at T0+80s.
    assert lease.acquire(client, path, "b", 60, now=T0 + timedelta(seconds=80)) is False


def test_release_only_by_the_holder(client_and_path):
    client, path = client_and_path
    assert lease.acquire(client, path, "a", 60, now=T0)
    lease.release(client, path, "b")  # not the holder: no-op
    assert _holder(client, path) == "a"
    lease.release(client, path, "a")
    assert _holder(client, path) is None
    assert lease.acquire(client, path, "b", 60, now=T0) is True


def test_release_of_a_missing_doc_is_quiet(client_and_path):
    client, path = client_and_path
    lease.release(client, path, "a")
    assert _holder(client, path) is None


def test_naive_expiry_reads_as_utc(fake):
    fake.docs["job_state/run"] = {"holder": "a",
                                  "expires_at": (T0 + timedelta(seconds=10)).replace(tzinfo=None)}
    assert lease.acquire(fake, "job_state/run", "b", 60, now=T0) is False
