"""Publisher — writes all per-dataset and aggregated frontend artifacts.

One process, one source of truth: the Firestore `sources/<id>` document.
For every source with `analysis_status == "succeeded"` OR "unavailable" we
emit (unavailable sources keep their preserved snapshot page):

    <out_root>/datasets/<id>/data.json        — DatasetMeta (scanner facts)
    <out_root>/datasets/<id>/agent_data.json  — AgentData (agent judgments)

…and a single aggregated:

    <out_root>/data/manifest.json             — merged ManifestEntry list

`content.html` is not the publisher's concern — it's rsynced from GCS
staging by the surrounding Cloud Build step.

Every run also recomputes each dataset's canonical tags (tags.py, from the
committed taxonomy/), the tag index + legacy tag redirects, and the
related-dataset scoring (related.py) over the whole corpus, so the manifest
always agrees with itself.

CLI:
    python -m services.page_builder.publish --from-firestore \
        --out frontend/public/
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from services.shared.firestore import FirestoreStateStore, SourceRecord
from services.shared.resources import pick_primary_resource_id
from services.shared.slug import hebrew_slugify

from .related import compute_related
from .schema import (
    AgentData,
    DatasetMeta,
    Manifest,
    ManifestEntry,
    ResourceEntry,
    SourceInfo,
    TagIndexEntry,
    TopicEntry,
)
from .tags import Taxonomy, build_tag_index, org_drop_names, tag_redirects

log = logging.getLogger(__name__)


# ---- record assembly --------------------------------------------------------

def _resources_from_source(src: SourceRecord) -> list[ResourceEntry]:
    return [
        ResourceEntry(
            url=r["url"],
            format=(r.get("format") or "").upper(),
            name=r.get("name"),
            size_bytes=r.get("size"),
            description=r.get("description"),
            id=r.get("id"),
            datastore_active=r.get("datastore_active"),
        )
        for r in src.resources
        if r.get("url")
    ]


def _formats_from_resources(resources: Iterable[ResourceEntry]) -> list[str]:
    seen: set[str] = set()
    for r in resources:
        f = (r.format or "").upper()
        if f:
            seen.add(f)
    return sorted(seen)


def dataset_meta_from_source(src: SourceRecord) -> DatasetMeta:
    """Build the scanner-derived `data.json` shape from a Firestore source doc."""
    resources = _resources_from_source(src)
    # Pass `analyzed_metadata_modified` through verbatim. Legacy sources
    # (analyzed before the pipeline started snapshotting it) leave this
    # None — the frontend then falls back to `last_analyzed_at` for the
    # "המידע נכון ל-" display and suppresses the "מקור עודכן מאז" icon,
    # since we have no honest snapshot to compare against.
    return DatasetMeta(
        id=src.id,
        slug=src.slug or src.id,
        title=src.title,
        organization=(src.organization or {}).get("title") or None,
        organization_slug=(src.organization or {}).get("name") or None,
        tags_he=list(src.tags or []),
        primary_resource_id=pick_primary_resource_id(src.resources),
        formats=_formats_from_resources(resources),
        metadata_modified=src.metadata_modified,
        license=src.license_title,
        record_count=src.record_count,
        resources=resources,
        notes=src.notes,
        last_analyzed_at=src.last_analyzed_at,
        analyzed_metadata_modified=src.analyzed_metadata_modified,
        source_status=(
            "unavailable" if src.analysis_status == "unavailable" else "available"
        ),
        unavailable_since=src.unavailable_since,
        source=_source_info(src),
        page_slug_suffix=src.page_slug_suffix,
    )


def _source_info(src: SourceRecord) -> Optional[SourceInfo]:
    """The credit block of a provider source (services/providers); None for
    CKAN. A malformed one is dropped, not fatal: the page then falls back to
    the shell's defaults rather than failing the whole publish."""
    if not src.provider or not src.presentation:
        return None
    try:
        return SourceInfo.model_validate(
            {**src.presentation, "provider": src.provider, "source_url": src.source_url}
        )
    except Exception as e:
        log.warning("malformed presentation for %s: %s", src.id, e)
        return None


def agent_data_from_source(src: SourceRecord) -> Optional[AgentData]:
    """Validate and return `AgentData`, or None if the source has none yet."""
    if not src.agent_data:
        return None
    try:
        return AgentData.model_validate(src.agent_data)
    except Exception as e:
        log.warning("malformed agent_data for %s: %s", src.id, e)
        return None


_TAG_URL_UNSAFE = re.compile(r"[\s/?#&]+")


def _build_tag_slugs(entries: Iterable[ManifestEntry]) -> dict[str, str]:
    """Map each Hebrew tag in any entry's `tags_he` or `suggested_tags`
    to a URL-safe slug that keeps the Hebrew characters.

    Whitespace runs and URL-reserved chars (`/?#&`) collapse to `-`. The
    output is decoded Unicode (no percent-encoding) — Nitro writes those
    as native Unicode directory names during `nuxt generate`, and the
    link side encodes for the wire. Iterates in sorted order so the
    output is stable across runs; on slug collision appends a short
    sha1 suffix to disambiguate deterministically.
    """
    all_tags = sorted({
        t
        for e in entries
        for t in (e.tags_he or []) + (e.suggested_tags or [])
    })
    seen: dict[str, str] = {}        # url-slug -> the Hebrew tag that owns it
    out: dict[str, str] = {}
    for tag in all_tags:
        slug = _TAG_URL_UNSAFE.sub("-", tag).strip("-")
        if not slug:
            slug = hashlib.sha1(tag.encode("utf-8")).hexdigest()[:8]
        if slug in seen and seen[slug] != tag:
            digest = hashlib.sha1(tag.encode("utf-8")).hexdigest()[:6]
            slug = f"{slug}-{digest}"
        seen[slug] = tag
        out[tag] = slug
    return out


def _build_page_slugs(metas: dict[str, DatasetMeta]) -> dict[str, str]:
    """Map each dataset id to its URL segment for /datasets/<page_slug>/.

    The segment is the Hebrew title slug + a slice of the CKAN id, e.g.
    `רישיונות-עסק-0b3e1f2a`. Keeping a slice of the (globally unique) id
    makes the slug unique with trivial reverse resolution. The id slice
    starts at the first UUID group (8 hex chars); on the astronomically
    unlikely collision (same title slug AND same id prefix) we widen the
    slice deterministically. Iterates in sorted id order so the output is
    stable across runs.
    """
    seen: dict[str, str] = {}        # page_slug -> the id that owns it
    out: dict[str, str] = {}
    for sid in sorted(metas):
        base = hebrew_slugify(metas[sid].title)
        # A provider source names its own readable suffix (unique within its
        # id prefix, so only a cross-provider title clash can collide — then
        # the full id, which is globally unique).
        own = metas[sid].page_slug_suffix
        if own:
            slug = f"{base}-{own}" if base else sid
            if slug in seen and seen[slug] != sid:
                slug = f"{base}-{sid}" if base else sid
            seen[slug] = sid
            out[sid] = slug
            continue
        compact = sid.replace("-", "")
        n = 8
        while True:
            suffix = compact[:n] or sid
            slug = f"{base}-{suffix}" if base else suffix
            if slug not in seen or seen[slug] == sid:
                break
            n += 4
            if n > len(compact):       # exhausted — fall back to the full id
                slug = f"{base}-{sid}" if base else sid
                break
        seen[slug] = sid
        out[sid] = slug
    return out


def _merged_entry(
    meta: DatasetMeta,
    agent: Optional[AgentData],
    tags: list[str],
) -> ManifestEntry:
    return ManifestEntry(
        **meta.model_dump(),
        summary_he=agent.summary_he if agent else None,
        dataset_kind=agent.dataset_kind if agent else None,
        temporal_coverage=agent.temporal_coverage if agent else None,
        spatial_coverage=agent.spatial_coverage if agent else None,
        suggested_tags=list(agent.suggested_tags) if agent else [],
        tags=tags,
    )


# ---- file writes ------------------------------------------------------------

def _write_json(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _write_dataset_meta(out_root: Path, meta: DatasetMeta) -> Path:
    target = out_root / "datasets" / meta.id / "data.json"
    body = meta.model_dump_json(exclude_none=True, indent=2).encode("utf-8")
    _write_json(target, body)
    return target


def _write_agent_data(out_root: Path, dataset_id: str, agent: AgentData) -> Path:
    target = out_root / "datasets" / dataset_id / "agent_data.json"
    body = agent.model_dump_json(exclude_none=True, indent=2).encode("utf-8")
    _write_json(target, body)
    return target


# Field set must stay in sync with frontend/types/manifest.ts::SlimEntry —
# it has to cover every list-page consumer: DatasetCard, useFacets, the
# HeaderSearch Fuse keys, utils/insights.ts, the kind/ministry/tag filters,
# buildDatasetLdSummary (collection JSON-LD) and the Hero count/date.
_SEARCH_INDEX_FIELDS = {
    "id",
    "page_slug",
    "title",
    "organization",
    "organization_slug",
    "summary_he",
    "dataset_kind",
    "formats",
    "tags_he",
    "suggested_tags",
    "tags",
    "record_count",
    "spatial_coverage",
    "license",
    "metadata_modified",
    "last_analyzed_at",
    "source_status",
    "unavailable_since",
}


def _write_search_index(out_root: Path, manifest: Manifest) -> Path:
    """Slim, runtime-fetchable projection of the manifest (~⅙ the size).

    The full manifest.json never ships to browsers — list/search pages
    `$fetch` this index on demand instead (frontend/utils/search-index.ts),
    and dataset pages resolve related/tag data server-side at prerender.
    Compact separators: this file is fetched at runtime, so bytes matter.
    """
    target = out_root / "data" / "search-index.json"
    body = manifest.model_dump_json(
        exclude_none=True,
        include={
            "version": True,
            "generated_at": True,
            "tag_slugs": True,
            "tag_index": {"__all__": {"slug", "topic", "count"}},
            "topics": {"__all__": {"id", "label_he"}},
            "datasets": {"__all__": _SEARCH_INDEX_FIELDS},
        },
    ).encode("utf-8")
    _write_json(target, body)
    return target


def _write_manifest(out_root: Path, manifest: Manifest) -> Path:
    target = out_root / "data" / "manifest.json"
    body = manifest.model_dump_json(exclude_none=True, indent=2).encode("utf-8")
    _write_json(target, body)
    return target


# ---- top-level orchestration ------------------------------------------------

def publish(
    out_root: Path,
    *,
    store: Optional[FirestoreStateStore] = None,
    taxonomy: Optional[Taxonomy] = None,
) -> dict:
    """Emit data.json + agent_data.json for each succeeded or unavailable
    source (unavailable sources keep their preserved snapshot page) and the
    merged manifest.json. Returns a small summary dict.
    """
    store = store or FirestoreStateStore()
    # A broken vocabulary/assignment file raises here: tests/CI guard it, and
    # publishing pages with silently-wrong tags is worse than a failed run.
    taxonomy = taxonomy or Taxonomy.load()

    sources: list[SourceRecord] = list(store.iter_publishable_sources())
    log.info("publish: %d publishable source(s) (succeeded + unavailable)", len(sources))

    metas: dict[str, DatasetMeta] = {}
    agents: dict[str, Optional[AgentData]] = {}
    for src in sources:
        metas[src.id] = dataset_meta_from_source(src)
        agents[src.id] = agent_data_from_source(src)

    # Assign the URL slug for each dataset now that every meta is loaded —
    # uniqueness is computed over the whole corpus. Flows into the manifest
    # entries (via meta.model_dump) and data.json below.
    page_slugs = _build_page_slugs(metas)
    for sid, slug in page_slugs.items():
        metas[sid].page_slug = slug

    # Canonical tags per dataset: the curated assignment, else the fallback
    # (recipe suggested_tags ∪ CKAN tags through the alias index).
    drop_names = org_drop_names(m.organization for m in metas.values())
    entries: dict[str, ManifestEntry] = {}
    for sid, meta in metas.items():
        agent = agents[sid]
        tags = taxonomy.dataset_tags(
            sid,
            suggested=agent.suggested_tags if agent else [],
            ckan=meta.tags_he,
            drop_names=drop_names,
        )
        entries[sid] = _merged_entry(meta, agent, tags)

    related = compute_related(list(entries.values()))

    written_meta = 0
    written_agent = 0
    for sid, entry in entries.items():
        _write_dataset_meta(out_root, metas[sid])
        written_meta += 1
        if agents[sid] is not None:
            _write_agent_data(out_root, sid, agents[sid])
            written_agent += 1
        entry.related_ids = [m.id for m in related[sid]]

    final_entries = sorted(
        entries.values(),
        key=lambda e: (e.metadata_modified or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )
    tag_index = build_tag_index(final_entries, taxonomy)
    raw_tags = {t for e in final_entries for t in (*e.tags_he, *e.suggested_tags)}
    manifest = Manifest(
        generated_at=datetime.now(timezone.utc),
        datasets=final_entries,
        tag_slugs=_build_tag_slugs(final_entries),
        tag_index={t: TagIndexEntry(**v) for t, v in tag_index.items()},
        topics=[TopicEntry(**vars(t)) for t in taxonomy.topics.values()],
        tag_redirects=tag_redirects(raw_tags, taxonomy, tag_index, drop_names),
    )
    manifest_path = _write_manifest(out_root, manifest)
    search_index_path = _write_search_index(out_root, manifest)
    log.info(
        "publish: wrote manifest=%s search_index=%s data.json=%d agent_data.json=%d",
        manifest_path, search_index_path, written_meta, written_agent,
    )
    return {
        "manifest_path": str(manifest_path),
        "search_index_path": str(search_index_path),
        "datasets": len(final_entries),
        "wrote_data_json": written_meta,
        "wrote_agent_data_json": written_agent,
    }


# ---- CLI --------------------------------------------------------------------

def _cli() -> None:
    p = argparse.ArgumentParser(description="Emit per-dataset + manifest artifacts from Firestore.")
    p.add_argument(
        "--from-firestore",
        action="store_true",
        help="Source from the Firestore `sources` collection (the only mode supported).",
    )
    p.add_argument(
        "--out",
        required=True,
        help="Output root (e.g. frontend/public). Writes data/manifest.json and datasets/<id>/{data,agent_data}.json.",
    )
    args = p.parse_args()

    if not args.from_firestore:
        p.error("only --from-firestore is supported")

    summary = publish(Path(args.out))
    import json
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _cli()
