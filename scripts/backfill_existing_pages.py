"""Backfill 3 already-built dataset pages into GCS staging + Firestore.

For each directory under frontend/public/datasets/<id>/:
  1. Upload index.html + content.html + data.json to the staging bucket.
  2. If Firestore has a source doc, stamp it succeeded with the manifest_entry.
     If not, fetch the dataset from CKAN, upsert the full source doc first.

Run: python scripts/backfill_existing_pages.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "govdata-il")
os.environ.setdefault("FIRESTORE_PROJECT_ID", "govdata-il")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from google.cloud import storage

from services.page_builder.schema import ManifestEntry
from services.scanner.client import CKANClient
from services.scanner.config import ScannerSettings
from services.shared.firestore import FirestoreStateStore

STAGING_BUCKET = os.environ.get("GCS_STAGING_BUCKET", "govdata-il-staging")
SOURCE_ROOT = REPO / "frontend/public/datasets"


def _content_type(fname: str) -> str:
    if fname.endswith(".html"):
        return "text/html; charset=utf-8"
    if fname.endswith(".json"):
        return "application/json; charset=utf-8"
    return "application/octet-stream"


def upload_to_staging(dataset_id: str, files: dict[str, bytes]) -> list[str]:
    client = storage.Client()
    bucket = client.bucket(STAGING_BUCKET)
    written: list[str] = []
    for name, body in files.items():
        blob = bucket.blob(f"datasets/{dataset_id}/{name}")
        blob.upload_from_string(body, content_type=_content_type(name))
        written.append(f"gs://{STAGING_BUCKET}/datasets/{dataset_id}/{name}")
    return written


async def ensure_source_doc(store: FirestoreStateStore, dataset_id: str) -> None:
    """Upsert the source doc from CKAN if Firestore doesn't have one yet."""
    if store.get_source(dataset_id) is not None:
        return
    config = ScannerSettings()
    async with CKANClient(config) as client:
        dataset = await client.get_package(dataset_id)
    if dataset is None:
        raise RuntimeError(f"CKAN has no package {dataset_id}")
    store.save_dataset(dataset, change_status="new")


async def backfill_one(store: FirestoreStateStore, source_dir: Path) -> dict:
    dataset_id = source_dir.name
    index_html = (source_dir / "index.html").read_bytes()
    content_html = (source_dir / "content.html").read_bytes()
    data_json_bytes = (source_dir / "data.json").read_bytes()

    entry = ManifestEntry.model_validate_json(data_json_bytes)

    # Make sure a Firestore source doc exists for this id.
    await ensure_source_doc(store, dataset_id)

    written = upload_to_staging(
        dataset_id,
        {
            "index.html": index_html,
            "data.json": data_json_bytes,
            "content.html": content_html,
        },
    )

    store.mark_analysis_succeeded(
        dataset_id,
        page_path=f"datasets/{dataset_id}/",
        manifest_entry=entry.model_dump(mode="json", exclude_none=True),
    )
    return {"id": dataset_id, "title": entry.title, "written": written}


async def main() -> None:
    store = FirestoreStateStore()
    dirs = sorted(p for p in SOURCE_ROOT.iterdir() if p.is_dir())
    if not dirs:
        print("no pre-built pages found in", SOURCE_ROOT)
        return
    print(f"backfilling {len(dirs)} pre-built dataset page(s) → gs://{STAGING_BUCKET} + Firestore")
    for d in dirs:
        result = await backfill_one(store, d)
        print(f"  ✓ {result['id'][:8]} — {result['title']}")
        for w in result["written"]:
            print(f"      {w}")
    stats = store.get_stats()
    print(f"firestore stats now: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
