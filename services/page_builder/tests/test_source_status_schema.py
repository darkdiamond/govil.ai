"""DatasetMeta/ManifestEntry carry the source-availability flag."""
from __future__ import annotations

from datetime import UTC, datetime

from services.page_builder.schema import DatasetMeta, ManifestEntry


def test_dataset_meta_defaults_available():
    m = DatasetMeta(id="x", slug="x", title="t")
    assert m.source_status == "available"
    assert m.unavailable_since is None


def test_dataset_meta_accepts_unavailable():
    ts = datetime(2026, 7, 20, tzinfo=UTC)
    m = DatasetMeta(
        id="x", slug="x", title="t",
        source_status="unavailable", unavailable_since=ts,
    )
    assert m.source_status == "unavailable"
    assert m.unavailable_since == ts


def test_manifest_entry_has_source_status():
    e = ManifestEntry(id="x", slug="x", title="t", source_status="unavailable")
    assert e.source_status == "unavailable"
