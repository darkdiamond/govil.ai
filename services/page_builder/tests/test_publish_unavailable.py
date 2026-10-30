"""Publisher preserves unavailable pages and stamps the flag into data.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from services.shared.firestore import SourceRecord
from services.page_builder import publish


def _src(sid: str, status: str, since: datetime | None) -> SourceRecord:
    return SourceRecord(
        id=sid,
        title="מאגר",
        slug="magar",
        organization={"name": "labor", "title": "משרד העבודה"},
        tags=["א"],
        resources=[{"id": "rid-1", "format": "CSV",
                    "url": "https://data.gov.il/dataset/x/resource/rid-1/download/x.csv"}],
        record_count=10,
        metadata_modified=datetime(2026, 5, 1, tzinfo=timezone.utc),
        analysis_status=status,
        unavailable_since=since,
        agent_data={"summary_he": "ס", "dataset_kind": "registry", "related_ids": [], "version": 1},
    )


def test_unavailable_source_is_published_with_flag(tmp_path: Path, monkeypatch):
    since = datetime(2026, 7, 20, tzinfo=timezone.utc)
    records = [
        _src("alive-1", "succeeded", None),
        _src("dead-1", "unavailable", since),
    ]
    store = MagicMock()
    store.iter_publishable_sources.return_value = iter(records)

    publish.publish(out_root=tmp_path, store=store)

    dead = json.loads((tmp_path / "datasets" / "dead-1" / "data.json").read_text())
    assert dead["source_status"] == "unavailable"
    assert dead["unavailable_since"].startswith("2026-07-20")

    alive = json.loads((tmp_path / "datasets" / "alive-1" / "data.json").read_text())
    assert alive["source_status"] == "available"
    assert "unavailable_since" not in alive  # exclude_none drops it
