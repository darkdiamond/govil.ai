"""Tests for services.page_builder.publish.

Mocks FirestoreStateStore so we never touch the network. Verifies the
three artifact contracts:
  - data.json holds DatasetMeta-shaped fields (license/resources etc.)
  - agent_data.json holds AgentData-shaped fields when agent_data exists
  - agent_data.json is *absent* for sources with no agent_data
  - manifest.json is the merged shape and includes both
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from services.shared.firestore import SourceRecord

from services.page_builder import publish


def _src(*, dataset_id: str, with_agent: bool, **overrides) -> SourceRecord:
    base = SourceRecord(
        id=dataset_id,
        title=overrides.get("title", "מאגר לדוגמה"),
        slug=overrides.get("slug", "magar-dugma"),
        organization={"name": "ministry-of-justice", "title": "משרד המשפטים"},
        license_title="Creative Commons Attribution",
        tags=["א", "ב"],
        resources=[
            {
                "id": "rid-1",
                "name": "main",
                "format": "CSV",
                "url": "https://data.gov.il/dataset/x/resource/rid-1/download/x.csv",
                "size": 1024,
                "description": None,
            }
        ],
        record_count=42,
        metadata_modified=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        analysis_status="succeeded",
    )
    if with_agent:
        base.agent_data = {
            "summary_he": "סיכום של המאגר",
            "dataset_kind": "registry",
            "related_ids": [],
            "version": 1,
        }
    return base


def _store_mock(records: list[SourceRecord]) -> MagicMock:
    store = MagicMock()
    store.iter_succeeded_sources.return_value = iter(records)
    store.iter_publishable_sources.return_value = iter(records)
    return store


def test_publish_writes_data_json_for_every_source(tmp_path: Path, monkeypatch):
    records = [
        _src(dataset_id="aaa-with-agent", with_agent=True),
        _src(dataset_id="bbb-no-agent",   with_agent=False),
    ]
    store = _store_mock(records)

    summary = publish.publish(tmp_path, store=store)

    assert summary["wrote_data_json"] == 2
    assert summary["wrote_agent_data_json"] == 1

    a_data = json.loads((tmp_path / "datasets/aaa-with-agent/data.json").read_text())
    assert a_data["id"] == "aaa-with-agent"
    assert a_data["license"] == "Creative Commons Attribution"
    assert a_data["record_count"] == 42
    assert len(a_data["resources"]) == 1
    assert a_data["primary_resource_id"] == "rid-1"
    assert a_data["formats"] == ["CSV"]
    assert "summary_he" not in a_data, "scanner data.json must not carry agent fields"
    assert "dataset_kind" not in a_data

    b_data = json.loads((tmp_path / "datasets/bbb-no-agent/data.json").read_text())
    assert b_data["id"] == "bbb-no-agent"
    assert b_data["license"] == "Creative Commons Attribution"


def test_publish_skips_agent_data_when_missing(tmp_path: Path, monkeypatch):
    records = [_src(dataset_id="bbb", with_agent=False)]
    store = _store_mock(records)

    publish.publish(tmp_path, store=store)

    agent_path = tmp_path / "datasets/bbb/agent_data.json"
    assert not agent_path.exists(), "agent_data.json must not be written when no agent_data"


def test_publish_writes_agent_data_when_present(tmp_path: Path, monkeypatch):
    records = [_src(dataset_id="aaa", with_agent=True)]
    store = _store_mock(records)

    publish.publish(tmp_path, store=store)

    agent = json.loads((tmp_path / "datasets/aaa/agent_data.json").read_text())
    assert agent["summary_he"] == "סיכום של המאגר"
    assert agent["dataset_kind"] == "registry"
    # Agent file must NOT carry scanner fields.
    assert "license" not in agent
    assert "resources" not in agent


def test_manifest_merges_scanner_and_agent_fields(tmp_path: Path, monkeypatch):
    records = [
        _src(dataset_id="aaa", with_agent=True),
        _src(dataset_id="bbb", with_agent=False),
    ]
    store = _store_mock(records)

    publish.publish(tmp_path, store=store)

    manifest = json.loads((tmp_path / "data/manifest.json").read_text())
    by_id = {d["id"]: d for d in manifest["datasets"]}

    a = by_id["aaa"]
    assert a["license"] == "Creative Commons Attribution"
    assert a["summary_he"] == "סיכום של המאגר"
    assert a["dataset_kind"] == "registry"
    assert a["resources"], "manifest entry should keep resources"

    b = by_id["bbb"]
    assert b["license"] == "Creative Commons Attribution"
    assert "summary_he" not in b or b.get("summary_he") is None
    assert "dataset_kind" not in b or b.get("dataset_kind") is None


def test_publish_passes_resource_id_and_datastore_active(tmp_path: Path, monkeypatch):
    """Resource id + datastore_active flow from the Firestore doc into
    data.json (they drive the shell's DatasetExplorer); legacy resources
    without the flag omit the key entirely (exclude_none) so the frontend
    can tell "unknown" apart from an authoritative False."""
    src = _src(dataset_id="flags", with_agent=False)
    src.resources = [
        {
            "id": "rid-active",
            "name": "main",
            "format": "CSV",
            "url": "https://data.gov.il/dataset/x/resource/rid-active/download/x.csv",
            "size": 1024,
            "description": None,
            "datastore_active": True,
        },
        {
            "id": "rid-flat-file",
            "name": "pdf",
            "format": "PDF",
            "url": "https://data.gov.il/dataset/x/resource/rid-flat-file/download/x.pdf",
            "size": 2048,
            "description": None,
            "datastore_active": False,
        },
        {
            # Legacy shape — ingested before the scanner captured the flag.
            "id": "rid-legacy",
            "name": "old",
            "format": "XLSX",
            "url": "https://data.gov.il/dataset/x/resource/rid-legacy/download/x.xlsx",
            "size": 4096,
            "description": None,
        },
    ]
    store = _store_mock([src])

    publish.publish(tmp_path, store=store)

    data = json.loads((tmp_path / "datasets/flags/data.json").read_text())
    by_id = {r.get("id"): r for r in data["resources"]}
    assert by_id["rid-active"]["datastore_active"] is True
    assert by_id["rid-flat-file"]["datastore_active"] is False
    assert "datastore_active" not in by_id["rid-legacy"]


def test_publish_writes_page_slug(tmp_path: Path, monkeypatch):
    """page_slug = Hebrew title slug + id slice, written to data.json and
    carried into the manifest entry."""
    src = _src(dataset_id="0b3e1f2a-9c4d-4e5f", with_agent=True, title="רישיונות עסק")
    store = _store_mock([src])

    publish.publish(tmp_path, store=store)

    data = json.loads(
        (tmp_path / "datasets/0b3e1f2a-9c4d-4e5f/data.json").read_text()
    )
    assert data["page_slug"] == "רישיונות-עסק-0b3e1f2a"

    manifest = json.loads((tmp_path / "data/manifest.json").read_text())
    entry = next(d for d in manifest["datasets"] if d["id"] == "0b3e1f2a-9c4d-4e5f")
    assert entry["page_slug"] == "רישיונות-עסק-0b3e1f2a"

    # And it's in the slim search index (list/search pages build links from it).
    index = json.loads((tmp_path / "data/search-index.json").read_text())
    assert index["datasets"][0]["page_slug"] == "רישיונות-עסק-0b3e1f2a"


def test_page_slugs_unique_even_with_identical_titles(tmp_path: Path, monkeypatch):
    """Two datasets with the same title still get distinct page_slugs because
    the id slice disambiguates them."""
    records = [
        _src(dataset_id="11111111-aaaa", with_agent=False, title="טבלת נתונים"),
        _src(dataset_id="22222222-bbbb", with_agent=False, title="טבלת נתונים"),
    ]
    store = _store_mock(records)

    publish.publish(tmp_path, store=store)

    manifest = json.loads((tmp_path / "data/manifest.json").read_text())
    slugs = [d["page_slug"] for d in manifest["datasets"]]
    assert len(slugs) == len(set(slugs)), "page_slug collision"
    assert all(s.startswith("טבלת-נתונים-") for s in slugs)


def test_publish_propagates_captured_analyzed_metadata_modified(
    tmp_path: Path, monkeypatch
):
    """When the source doc carries a real snapshot, it flows verbatim to
    data.json + manifest.json."""
    src = _src(dataset_id="captured", with_agent=True)
    src.last_analyzed_at = datetime(2026, 4, 25, tzinfo=timezone.utc)
    src.analyzed_metadata_modified = datetime(2026, 4, 20, tzinfo=timezone.utc)
    store = _store_mock([src])

    publish.publish(tmp_path, store=store)

    data = json.loads((tmp_path / "datasets/captured/data.json").read_text())
    assert data["analyzed_metadata_modified"].startswith("2026-04-20")
    # Live source date is preserved separately so the frontend can detect
    # "מקור עודכן מאז" by comparing the two.
    assert data["metadata_modified"].startswith("2026-04-24")

    manifest = json.loads((tmp_path / "data/manifest.json").read_text())
    entry = next(d for d in manifest["datasets"] if d["id"] == "captured")
    assert entry["analyzed_metadata_modified"].startswith("2026-04-20")


def test_publish_passes_through_null_snapshot_for_legacy_sources(
    tmp_path: Path, monkeypatch
):
    """Legacy sources (analyzed_metadata_modified=None on the Firestore doc)
    flow through with no synthesized snapshot. The frontend falls back to
    last_analyzed_at for display and suppresses the "updated since analysis"
    icon — we don't have an honest snapshot to compare against."""

    legacy = _src(dataset_id="legacy", with_agent=True)
    legacy.metadata_modified = datetime(2026, 5, 1, tzinfo=timezone.utc)
    legacy.last_analyzed_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
    legacy.analyzed_metadata_modified = None

    store = _store_mock([legacy])
    publish.publish(tmp_path, store=store)

    data = json.loads((tmp_path / "datasets/legacy/data.json").read_text())
    # exclude_none=True drops the field entirely when there's no snapshot
    assert "analyzed_metadata_modified" not in data
    assert data["metadata_modified"].startswith("2026-05-01")
    assert data["last_analyzed_at"].startswith("2026-04-01")

    manifest = json.loads((tmp_path / "data/manifest.json").read_text())
    entry = next(d for d in manifest["datasets"] if d["id"] == "legacy")
    assert "analyzed_metadata_modified" not in entry


def test_manifest_carries_tags_index_redirects_and_related(tmp_path: Path):
    """Curated tags win over the fallback, the tag index pages only tags with
    ≥ min datasets, legacy raw-tag URLs redirect, and related_ids are the
    publisher's own picks (recipe related_ids are ignored)."""
    from services.page_builder.tags import Taxonomy

    tax = Taxonomy.from_dicts(
        {"topics": [{"id": "water", "label_he": "מים"}],
         "tags": {"מים": {"topic": "water"}, "קידוחים": {"topic": "water", "aliases": ["קידוח"]}}},
        {"w1": ["מים", "קידוחים"], "w2": ["מים", "קידוחים"]},
    )
    w1 = _src(dataset_id="w1", with_agent=True, title="איכות מים בקידוחים")
    w2 = _src(dataset_id="w2", with_agent=True, title="מפלסי מים בקידוחים")
    w3 = _src(dataset_id="w3", with_agent=True, title="נתוני קידוח ישנים")
    for s in (w1, w2, w3):
        s.tags = ["קידוח"]
    w1.agent_data["related_ids"] = ["w3"]
    store = _store_mock([w1, w2, w3])

    publish.publish(tmp_path, store=store, taxonomy=tax)

    manifest = json.loads((tmp_path / "data/manifest.json").read_text())
    by_id = {d["id"]: d for d in manifest["datasets"]}
    assert by_id["w1"]["tags"] == ["מים", "קידוחים"]
    assert by_id["w3"]["tags"] == ["קידוחים"]              # fallback via alias
    assert by_id["w1"]["tags_he"] == ["קידוח"]             # raw kept
    assert "embedding" not in by_id["w1"]
    assert manifest["tag_index"]["קידוחים"]["count"] == 3
    assert manifest["tag_index"]["קידוחים"]["slug"] == "קידוחים"
    assert manifest["topics"] == [{"id": "water", "label_he": "מים", "intro_he": ""}]
    assert manifest["tag_redirects"]["קידוח"] == "/tags/קידוחים/"
    assert by_id["w1"]["related_ids"][0] == "w2"            # content, not the recipe pick

    index = json.loads((tmp_path / "data/search-index.json").read_text())
    assert index["tag_index"]["קידוחים"] == manifest["tag_index"]["קידוחים"]
    assert index["topics"] == manifest["topics"]
    assert index["datasets"][0]["tags"]
