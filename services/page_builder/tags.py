"""Tag vocabulary — the single place tags are normalized, mapped and paged.

Two committed files under `taxonomy/` drive every tag the site shows:

    taxonomy/tags.json          — the vocabulary: topics, canonical tags (with
                                  aliases, optional intro/slug) and a drop list
    taxonomy/dataset-tags.json  — the curated assignment: dataset id → 3–6
                                  canonical tags

A dataset's displayed tags are its curated assignment when it has one, else
a fallback: its recipe's `suggested_tags` ∪ CKAN `tags_he`, each normalized
and mapped through the alias index (drop list and ministry names removed).
The fallback only covers a dataset between scan and authoring — authoring
adds the dataset's line to dataset-tags.json.

Only tags carried by ≥ `TAG_PAGE_MIN` datasets get a /tags/<slug>/ page
(`build_tag_index`); the rest render as plain chips. `tag_redirects` maps
every URL the old raw-tag scheme produced to its canonical page, when it has one.

Dev CLI (local curation only):
    python -m services.page_builder.tags suggest --manifest <manifest.json>
    python -m services.page_builder.tags report  --manifest <manifest.json>

Authoring (writes taxonomy/dataset-tags.json, validated against the vocabulary):
    python -m services.page_builder.tags assign <id> <tag> [<tag> ...]
    python -m services.page_builder.tags assign --from-pending <id> [<id> ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Protocol, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_DIR = REPO_ROOT / "taxonomy"
VOCAB_PATH = TAXONOMY_DIR / "tags.json"
ASSIGNMENTS_PATH = TAXONOMY_DIR / "dataset-tags.json"

MIN_ASSIGNED = 3
MAX_ASSIGNED = 6
MAX_DISPLAY = 8
RELATED_TAGS = 8


def tag_page_min() -> int:
    return int(os.environ.get("TAG_PAGE_MIN", "3"))


class TaxonomyError(ValueError):
    """The committed vocabulary or assignment file is inconsistent."""


# ---- normalization -----------------------------------------------------------

_GERSHAYIM = str.maketrans({"״": '"', "”": '"', "“": '"', "׳": "'", "’": "'", "‘": "'"})
_SEPARATORS = re.compile(r"[\s\-_‐-―]+")


def normalize(raw: str) -> str:
    """Mechanical normal form: NFC, unified quote marks, `-`/`_`/whitespace
    runs → one space, trimmed, Latin lowercased (Hebrew has no case)."""
    s = unicodedata.normalize("NFC", raw or "").translate(_GERSHAYIM)
    s = _SEPARATORS.sub(" ", s).strip()
    return s.lower()


_URL_UNSAFE = re.compile(r"[\s/?#&%]+")


def _slugify(name: str) -> str:
    # Quote marks (אג"ח) are dropped rather than dashed: they'd need escaping
    # in every href and directory name.
    return _URL_UNSAFE.sub("-", normalize(name).replace('"', "").replace("'", "")).strip("-")


# ---- vocabulary --------------------------------------------------------------

@dataclass(frozen=True)
class Topic:
    id: str
    label_he: str
    intro_he: str = ""


@dataclass(frozen=True)
class TagDef:
    name: str
    topic: Optional[str] = None
    aliases: tuple[str, ...] = ()
    intro_he: str = ""
    slug: str = ""


@dataclass
class Taxonomy:
    topics: dict[str, Topic] = field(default_factory=dict)
    tags: dict[str, TagDef] = field(default_factory=dict)
    drop: frozenset[str] = frozenset()
    assignments: dict[str, list[str]] = field(default_factory=dict)
    _alias: dict[str, str] = field(default_factory=dict, repr=False)
    _slugs: dict[str, str] = field(default_factory=dict, repr=False)

    # -- construction --

    @classmethod
    def from_dicts(cls, vocab: dict, assignments: Optional[dict] = None) -> "Taxonomy":
        topics = {
            t["id"]: Topic(t["id"], t["label_he"], t.get("intro_he", ""))
            for t in vocab.get("topics", [])
        }
        tags: dict[str, TagDef] = {}
        for name, spec in (vocab.get("tags") or {}).items():
            spec = spec or {}
            if name != normalize(name):
                raise TaxonomyError(f"canonical tag {name!r} is not in normal form {normalize(name)!r}")
            topic = spec.get("topic")
            if topic is not None and topic not in topics:
                raise TaxonomyError(f"tag {name!r} references unknown topic {topic!r}")
            tags[name] = TagDef(
                name=name,
                topic=topic,
                aliases=tuple(spec.get("aliases") or ()),
                intro_he=spec.get("intro_he", ""),
                slug=spec.get("slug", ""),
            )
        drop = frozenset(normalize(d) for d in vocab.get("drop") or ())

        alias: dict[str, str] = {}
        for name, tdef in tags.items():
            for form in (name, *tdef.aliases):
                key = normalize(form)
                if key in drop:
                    raise TaxonomyError(f"{form!r} is both a tag/alias of {name!r} and dropped")
                owner = alias.get(key)
                if owner is not None and owner != name:
                    raise TaxonomyError(f"{form!r} is claimed by both {owner!r} and {name!r}")
                alias[key] = name

        slugs: dict[str, str] = {}
        seen: dict[str, str] = {}
        for name, tdef in tags.items():
            slug = tdef.slug or _slugify(name)
            if not slug:
                raise TaxonomyError(f"tag {name!r} has an empty slug")
            if slug in seen:
                raise TaxonomyError(f"tags {seen[slug]!r} and {name!r} share slug {slug!r}")
            seen[slug] = name
            slugs[name] = slug

        tax = cls(topics=topics, tags=tags, drop=drop, _alias=alias, _slugs=slugs)
        for sid, assigned in (assignments or {}).items():
            unknown = [t for t in assigned if t not in tags]
            if unknown:
                raise TaxonomyError(f"{sid}: assigned tags not in the vocabulary: {unknown}")
            if len(set(assigned)) != len(assigned):
                raise TaxonomyError(f"{sid}: duplicate assigned tags")
            tax.assignments[sid] = list(assigned)
        return tax

    @classmethod
    def load(
        cls,
        vocab_path: Optional[Path] = None,
        assignments_path: Optional[Path] = None,
    ) -> "Taxonomy":
        # Resolved at call time (not as defaults) so tests can repoint them.
        vocab_path = vocab_path or VOCAB_PATH
        assignments_path = assignments_path or ASSIGNMENTS_PATH
        vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
        assignments = (
            json.loads(assignments_path.read_text(encoding="utf-8"))
            if assignments_path.exists() else {}
        )
        return cls.from_dicts(vocab, assignments)

    # -- lookups --

    def resolve(self, raw: str, drop_names: frozenset[str] = frozenset()) -> Optional[str]:
        """Canonical name for one raw tag; None when it's empty or dropped.
        A tag outside the vocabulary passes through in normal form."""
        key = normalize(raw)
        if not key or key in self.drop or key in drop_names:
            return None
        return self._alias.get(key, key)

    def canonicalize(
        self, raw_tags: Iterable[str], drop_names: frozenset[str] = frozenset(),
    ) -> list[str]:
        out: list[str] = []
        for raw in raw_tags:
            tag = self.resolve(raw, drop_names)
            if tag and tag not in out:
                out.append(tag)
        return out

    def slug(self, tag: str) -> str:
        return self._slugs.get(tag) or _slugify(tag)

    def topic_of(self, tag: str) -> Optional[str]:
        tdef = self.tags.get(tag)
        return tdef.topic if tdef else None

    def dataset_tags(
        self,
        dataset_id: str,
        *,
        suggested: Sequence[str] = (),
        ckan: Sequence[str] = (),
        drop_names: frozenset[str] = frozenset(),
    ) -> list[str]:
        """Display tags for one dataset: curated assignment, else fallback."""
        curated = self.assignments.get(dataset_id)
        if curated:
            return list(curated)
        return self.canonicalize([*suggested, *ckan], drop_names)[:MAX_DISPLAY]


def org_drop_names(org_titles: Iterable[Optional[str]]) -> frozenset[str]:
    """Ministry/organization titles in normal form — a tag that just repeats
    the publisher's name is dropped (its /ministries/ hub covers it)."""
    return frozenset(normalize(t) for t in org_titles if t)


# ---- tag index + redirects -----------------------------------------------------

class _Tagged(Protocol):
    id: str
    tags: list[str]
    organization_slug: Optional[str]


def build_tag_index(
    entries: Iterable[_Tagged], taxonomy: Taxonomy, min_datasets: Optional[int] = None,
) -> dict[str, dict]:
    """Per paged tag (≥ min_datasets carriers): slug, topic, count, ministry
    breakdown and the top co-occurring paged tags. Insertion order is count
    DESC, then name, so consumers can render it as-is."""
    min_datasets = tag_page_min() if min_datasets is None else min_datasets
    entries = list(entries)
    counts: Counter[str] = Counter(t for e in entries for t in set(e.tags))
    paged = {t for t, n in counts.items() if n >= min_datasets}

    ministries: dict[str, Counter[str]] = defaultdict(Counter)
    co: dict[str, Counter[str]] = defaultdict(Counter)
    for e in entries:
        mine = [t for t in dict.fromkeys(e.tags) if t in paged]
        for t in mine:
            if e.organization_slug:
                ministries[t][e.organization_slug] += 1
            for other in mine:
                if other != t:
                    co[t][other] += 1

    index: dict[str, dict] = {}
    for tag in sorted(paged, key=lambda t: (-counts[t], t)):
        related = sorted(co[tag].items(), key=lambda kv: (-kv[1], kv[0]))[:RELATED_TAGS]
        tdef = taxonomy.tags.get(tag)
        index[tag] = {
            "slug": taxonomy.slug(tag),
            "topic": taxonomy.topic_of(tag),
            "count": counts[tag],
            "intro_he": (tdef.intro_he if tdef else "") or None,
            "ministries": dict(sorted(ministries[tag].items(), key=lambda kv: (-kv[1], kv[0]))),
            "related": [t for t, _ in related],
        }
    return index


_LEGACY_URL_UNSAFE = re.compile(r"[\s/?#&]+")
# Firebase Hosting `source` glob syntax.
_GLOB_META = re.compile(r"[*:{}!?\\\[\]]")


def legacy_tag_slug_map(raw_tags: Iterable[str]) -> dict[str, str]:
    """The pre-taxonomy slug scheme, kept verbatim (hash suffixes included)
    so `tag_redirects` can point every URL it ever produced somewhere."""
    seen: dict[str, str] = {}
    out: dict[str, str] = {}
    for tag in sorted(set(raw_tags)):
        slug = _LEGACY_URL_UNSAFE.sub("-", tag).strip("-")
        if not slug:
            slug = hashlib.sha1(tag.encode("utf-8")).hexdigest()[:8]
        if slug in seen and seen[slug] != tag:
            digest = hashlib.sha1(tag.encode("utf-8")).hexdigest()[:6]
            slug = f"{slug}-{digest}"
        seen[slug] = tag
        out[tag] = slug
    return out


def tag_redirects(
    raw_tags: Iterable[str],
    taxonomy: Taxonomy,
    tag_index: dict[str, dict],
    drop_names: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Legacy slug → `/tags/<slug>/`, for every legacy URL whose tag now
    lives on a different canonical page (a merged variant or alias).

    Legacy slugs that are still a live page are omitted, and so are tags
    with no page any more (dropped, or under TAG_PAGE_MIN): redirecting a
    gone page to an index is a soft-404 search engines penalise, so those
    are left to 404.

    Segments become Firebase redirect `source` patterns, and the raw tags
    come from CKAN: one carrying glob syntax (`*`, `:name`, `{a,b}`, …)
    could capture live URLs, so such segments are never emitted."""
    live = {v["slug"] for v in tag_index.values()}
    out: dict[str, str] = {}
    for raw, old in legacy_tag_slug_map(raw_tags).items():
        if old in live or _GLOB_META.search(old):
            continue
        tag = taxonomy.resolve(raw, drop_names)
        if tag in tag_index:
            out[old] = f"/tags/{tag_index[tag]['slug']}/"
    return dict(sorted(out.items()))


# ---- dev CLI -------------------------------------------------------------------

_HEB_PREFIX = re.compile(r"^ה(?=[א-ת]{3,})")
_HEB_PLURAL = re.compile(r"(ים|ות)$")


def _cluster_key(tag: str) -> str:
    words = []
    for w in normalize(tag).split():
        w = _HEB_PREFIX.sub("", w)
        if len(w) > 4:
            w = _HEB_PLURAL.sub("", w)
        if len(w) > 3 and w.endswith("ה"):
            w = w[:-1]
        words.append(w)
    return " ".join(words)


def _load_manifest(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["datasets"]


def _raw_counts(datasets: list[dict]) -> Counter[str]:
    return Counter(
        t for d in datasets
        for t in set((d.get("tags_he") or []) + (d.get("suggested_tags") or []))
    )


def _cmd_suggest(args: argparse.Namespace) -> int:
    datasets = _load_manifest(Path(args.manifest))
    counts = _raw_counts(datasets)
    groups: dict[str, list[str]] = defaultdict(list)
    for tag in counts:
        groups[_cluster_key(tag)].append(tag)
    multi = sorted(
        (g for g in groups.values() if len(g) > 1),
        key=lambda g: -sum(counts[t] for t in g),
    )
    print(f"# {len(counts)} raw tags → {len(groups)} clusters; {len(multi)} with variants\n")
    for g in multi:
        print("  " + " | ".join(f"{t} ({counts[t]})" for t in sorted(g, key=lambda t: -counts[t])))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    datasets = _load_manifest(Path(args.manifest))
    tax = Taxonomy.load()
    drop_names = org_drop_names(d.get("organization") for d in datasets)

    @dataclass
    class _E:
        id: str
        tags: list[str]
        organization_slug: Optional[str]

    entries = [
        _E(d["id"], tax.dataset_tags(
            d["id"], suggested=d.get("suggested_tags") or [],
            ckan=d.get("tags_he") or [], drop_names=drop_names,
        ), d.get("organization_slug"))
        for d in datasets
    ]
    index = build_tag_index(entries, tax)
    curated = sum(1 for d in datasets if d["id"] in tax.assignments)
    counts = Counter(t for e in entries for t in e.tags)
    raw = _raw_counts(datasets)
    redirects = tag_redirects(raw, tax, index, drop_names)
    print(f"datasets: {len(datasets)}  curated: {curated}  fallback: {len(datasets) - curated}")
    print(f"vocabulary: {len(tax.tags)} tags in {len(tax.topics)} topics, {len(tax.drop)} dropped")
    print(f"displayed tags: {len(counts)} distinct; singletons: {sum(1 for n in counts.values() if n == 1)}")
    print(f"paged tags (≥{tag_page_min()}): {len(index)}; no topic: "
          f"{[t for t, v in index.items() if not v['topic']]}")
    one_ministry = [t for t, v in index.items() if v["count"] >= 5 and
                    max(v["ministries"].values(), default=0) / v["count"] >= 0.9]
    print(f"paged tags ≥90% one ministry (count≥5): {len(one_ministry)} {one_ministry[:30]}")
    unused = sorted(t for t in tax.tags if t not in counts)
    print(f"vocabulary tags never displayed: {len(unused)} {unused[:40]}")
    print(f"legacy raw tags: {len(raw)}; redirects to a canonical page: {len(redirects)}")
    missing = [d["id"] for d in datasets if d["id"] not in tax.assignments]
    if args.verbose and missing:
        print("not curated:", *missing, sep="\n  ")
    return 0


PENDING_ROOT = REPO_ROOT / "tmp" / "authoring"


def pending_tags_path(dataset_id: str) -> Path:
    """Where an authoring run parks a dataset's tags until they're merged into
    dataset-tags.json (parallel authors never write the shared file)."""
    return PENDING_ROOT / dataset_id / "tags.json"


def validate_assignment(taxonomy: Taxonomy, tags: Sequence[str]) -> list[str]:
    problems = []
    if not MIN_ASSIGNED <= len(tags) <= MAX_ASSIGNED:
        problems.append(f"{len(tags)} tags; use {MIN_ASSIGNED}–{MAX_ASSIGNED}")
    if len(set(tags)) != len(tags):
        problems.append("duplicate tags")
    for t in tags:
        if t not in taxonomy.tags:
            hint = taxonomy.resolve(t)
            problems.append(
                f"{t!r} is not a canonical tag" + (f" (use {hint!r})" if hint in taxonomy.tags else "")
            )
    return problems


def write_assignments(assignments: dict[str, list[str]], path: Optional[Path] = None) -> None:
    (path or ASSIGNMENTS_PATH).write_text(
        json.dumps(dict(sorted(assignments.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _cmd_assign(args: argparse.Namespace) -> int:
    tax = Taxonomy.load()
    updates: dict[str, list[str]] = {}
    if args.from_pending:
        for sid in args.ids:
            p = pending_tags_path(sid)
            if not p.is_file():
                print(f"{sid}: no {p}", file=sys.stderr)
                return 1
            updates[sid] = json.loads(p.read_text(encoding="utf-8"))
    else:
        if len(args.ids) < 2:
            print("usage: assign <id> <tag> [<tag> ...]  |  assign --from-pending <id> ...",
                  file=sys.stderr)
            return 2
        updates[args.ids[0]] = args.ids[1:]
    bad = {sid: validate_assignment(tax, tags) for sid, tags in updates.items()}
    bad = {k: v for k, v in bad.items() if v}
    for sid, problems in bad.items():
        print(f"{sid}: " + "; ".join(problems), file=sys.stderr)
    if bad:
        return 1
    raw = json.loads(ASSIGNMENTS_PATH.read_text(encoding="utf-8")) if ASSIGNMENTS_PATH.exists() else {}
    raw.update(updates)
    write_assignments(raw)
    for sid, tags in updates.items():
        print(f"{sid}: {tags}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m services.page_builder.tags")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("suggest", "report"):
        p = sub.add_parser(name)
        p.add_argument("--manifest", required=True, help="a manifest.json to read")
        p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("assign", help="validate + write a dataset's tags into dataset-tags.json")
    p.add_argument("--from-pending", action="store_true",
                   help="read each id's tags from tmp/authoring/<id>/tags.json")
    p.add_argument("ids", nargs="+", help="<id> <tag>... or, with --from-pending, <id>...")
    args = ap.parse_args(argv)
    return {"suggest": _cmd_suggest, "report": _cmd_report, "assign": _cmd_assign}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
