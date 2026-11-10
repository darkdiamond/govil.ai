"""The status StrEnums store as plain strings, and RefreshState reads a doc.

The encoding tests run everywhere (the Firestore wire encoder, no server). The
round trip runs against the emulator when FIRESTORE_EMULATOR_HOST is set:
  gcloud emulators firestore start --host-port=localhost:8080 &
  FIRESTORE_EMULATOR_HOST=localhost:8080 pytest services/shared/tests/test_states.py
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from google.cloud.firestore_v1 import _helpers

from services.shared.firestore import FirestoreStateStore, SourceRecord
from services.shared.states import (
    AnalysisStatus,
    AuthoringStatus,
    FailReason,
    RefreshState,
    RefreshStatus,
    RunStatus,
)


def test_enum_members_are_their_strings():
    assert FailReason.TOO_LARGE == "too_large" and f"{RunStatus.SCAN_FAILED}" == "scan_failed"
    assert "recipe_failed" in frozenset({FailReason.RECIPE_FAILED})
    assert json.dumps({"s": RunStatus.OK}) == '{"s": "ok"}'


def _written(method, **kw) -> dict:
    store = FirestoreStateStore.__new__(FirestoreStateStore)
    store.client = MagicMock()
    getattr(store, method)("ds", **kw)
    ref = store.client.collection.return_value.document.return_value
    return ref.set.call_args[0][0]


def test_state_writers_encode_statuses_as_plain_strings():
    ok = _written("mark_refreshed", metadata_modified=None, recipe_version=1,
                  agent_data={}, page_path="p")
    failed = _written("mark_refresh_failed", error="e", reason=FailReason.SCHEMA_CHANGED,
                      failed_version="v")
    for payload, field, value in ((ok, "refresh_status", "succeeded"),
                                  (ok, "authoring_status", "done"),
                                  (ok, "analysis_status", "succeeded"),
                                  (failed, "refresh_status", "failed"),
                                  (failed, "refresh_reason", "schema_changed")):
        encoded = _helpers.encode_value(payload[field])
        assert type(encoded).pb(encoded).WhichOneof("value_type") == "string_value", field
        assert encoded.string_value == value


def test_refresh_state_from_dict_ignores_other_fields():
    st = RefreshState.from_dict({"refresh_status": "failed", "wall_budget_strikes": 2,
                                 "title": "x", "resources": []})
    assert st.refresh_status == "failed" and st.wall_budget_strikes == 2
    assert st.content_hash is None and RefreshState.from_dict(None) == RefreshState()


def test_source_record_carries_its_refresh_state():
    doc = MagicMock(id="ds")
    doc.to_dict.return_value = {"title": "t", "content_hash": "abc", "recipe_version": 3}
    src = SourceRecord.from_doc(doc)
    assert src.refresh.content_hash == "abc" and src.refresh.recipe_version == 3


@pytest.mark.skipif(not os.environ.get("FIRESTORE_EMULATOR_HOST"),
                    reason="needs the Firestore emulator (FIRESTORE_EMULATOR_HOST)")
def test_emulator_round_trip_reads_back_plain_strings():
    store = FirestoreStateStore(project_id="local-test")
    ds = f"test-{uuid.uuid4().hex[:12]}"
    ref = store.client.collection("sources").document(ds)
    try:
        mm = datetime(2026, 11, 1, tzinfo=UTC)
        store.mark_refreshed(ds, metadata_modified=mm, recipe_version=2,
                             agent_data={"summary_he": "x"}, page_path="p", content_hash="h")
        raw = ref.get().to_dict()
        assert raw["refresh_status"] == "succeeded" and type(raw["refresh_status"]) is str
        assert type(raw["authoring_status"]) is str and raw["authoring_status"] == "done"
        assert raw["analysis_status"] == AnalysisStatus.SUCCEEDED
        store.mark_refresh_failed(ds, error="boom", reason=FailReason.TOO_LARGE,
                                  failed_version="v1")
        store.set_authoring_issue(ds, 12)
        src = store.get_source(ds)
        assert type(src.refresh.refresh_reason) is str
        assert src.refresh.refresh_reason == "too_large"
        assert src.refresh.refresh_status == RefreshStatus.FAILED
        assert src.refresh.authoring_status == AuthoringStatus.NOTIFIED
        assert src.refresh.authoring_issue == 12 and src.refresh.content_hash == "h"
        assert src.refresh.refreshed_metadata_modified == mm
        assert src.refresh == RefreshState.from_dict(store.get_refresh_state(ds))
    finally:
        ref.delete()
