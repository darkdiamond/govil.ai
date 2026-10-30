"""Related datasets — deterministic, content-based, no API calls.

For each dataset the publisher picks up to `TOP_K` others by

    score = W_TEXT     · text      # TF-IDF cosine over title + summary_he
          + W_TAG      · tags      # IDF-weighted share of the target's tags
          + W_MINISTRY · same_ministry   # tiebreaker only — never enough alone

`text` uses character 4-grams inside each word (with boundary markers), which
matches Hebrew words through their attached prefixes (ו/ה/ב/ל/מ/ש) without a
stemmer; features in more than half the corpus (boilerplate like "מאגר") are
dropped. `tags` sums the IDF of the shared canonical tags over the target's
total, so a rare shared tag counts far more than a generic one.

Selection: candidates exclude the target and unavailable sources; a match
must clear `MIN_SCORE` and `REL_FLOOR` × the best match's score (a page may
get fewer than TOP_K, or none — the relative floor keeps the ministry cap
below from trading a strong pick for a weak one); at most
`MAX_SAME_MINISTRY` picks share the target's ministry while others qualify;
ties break on id, so the output is stable run to run.

CLI (local tuning; reads a published manifest.json + the committed taxonomy):
    python -m services.page_builder.related explain <id> --manifest <path>
    python -m services.page_builder.related sample --manifest <path> [--sample N]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Protocol, Sequence

TOP_K = 5
W_TEXT = 1.0
W_TAG = 0.6
W_MINISTRY = 0.05
MIN_SCORE = 0.25
REL_FLOOR = 0.35
MAX_SAME_MINISTRY = 3
NGRAM = 4
MAX_DF_RATIO = 0.5


class _Entry(Protocol):
    id: str
    title: str
    summary_he: Optional[str]
    organization_slug: Optional[str]
    tags: list[str]
    source_status: str


@dataclass(frozen=True)
class Match:
    id: str
    score: float
    signals: dict[str, float] = field(default_factory=dict)


_WORD = re.compile(r"[א-תa-z0-9]+")


def _features(text: str) -> Counter[str]:
    out: Counter[str] = Counter()
    for word in _WORD.findall(text.lower()):
        padded = f"_{word}_"
        if len(padded) <= NGRAM:
            out[padded] += 1
            continue
        for i in range(len(padded) - NGRAM + 1):
            out[padded[i:i + NGRAM]] += 1
    return out


@dataclass
class _Doc:
    id: str
    ministry: Optional[str]
    tags: frozenset[str]
    vec: dict[str, float]
    candidate: bool


class RelatedIndex:
    """Corpus-wide index; build once per publish, then query every entry."""

    def __init__(self, entries: Iterable[_Entry]):
        entries = list(entries)
        n = max(len(entries), 1)
        raw = {
            e.id: _features(f"{e.title} {e.title} {e.summary_he or ''}")
            for e in entries
        }
        df: Counter[str] = Counter(f for feats in raw.values() for f in feats)
        # df == 1 can't match anything; df > half the corpus is boilerplate.
        keep = {f for f, d in df.items() if 1 < d <= MAX_DF_RATIO * n}
        idf = {f: math.log((n + 1) / (df[f] + 1)) + 1 for f in keep}

        tag_df: Counter[str] = Counter(t for e in entries for t in set(e.tags))
        self._tag_idf = {t: math.log((n + 1) / (d + 1)) + 1 for t, d in tag_df.items()}

        self._docs: dict[str, _Doc] = {}
        self._postings: dict[str, list[tuple[str, float]]] = defaultdict(list)
        self._tag_postings: dict[str, list[str]] = defaultdict(list)
        for e in entries:
            vec = {
                f: (1 + math.log(tf)) * idf[f]
                for f, tf in raw[e.id].items() if f in keep
            }
            norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
            vec = {f: w / norm for f, w in vec.items()}
            candidate = e.source_status != "unavailable"
            doc = _Doc(e.id, e.organization_slug, frozenset(e.tags), vec, candidate)
            self._docs[e.id] = doc
            if candidate:
                for f, w in vec.items():
                    self._postings[f].append((e.id, w))
                for t in doc.tags:
                    self._tag_postings[t].append(e.id)

    def score_all(self, target_id: str) -> list[Match]:
        """Every candidate with a non-zero content signal, best first."""
        target = self._docs[target_id]
        text: dict[str, float] = defaultdict(float)
        for f, w in target.vec.items():
            for cid, cw in self._postings.get(f, ()):
                text[cid] += w * cw
        tag_total = sum(self._tag_idf[t] for t in target.tags) or 1.0
        tag: dict[str, float] = defaultdict(float)
        for t in target.tags:
            for cid in self._tag_postings.get(t, ()):
                tag[cid] += self._tag_idf[t] / tag_total

        out: list[Match] = []
        for cid in set(text) | set(tag):
            if cid == target_id:
                continue
            signals = {}
            if text.get(cid):
                signals["text"] = round(W_TEXT * text[cid], 4)
            if tag.get(cid):
                signals["tags"] = round(W_TAG * tag[cid], 4)
            if target.ministry and self._docs[cid].ministry == target.ministry:
                signals["ministry"] = W_MINISTRY
            out.append(Match(cid, round(sum(signals.values()), 4), signals))
        out.sort(key=lambda m: (-m.score, m.id))
        return out

    def top(self, target_id: str, k: int = TOP_K) -> list[Match]:
        target = self._docs[target_id]
        scored = self.score_all(target_id)
        floor = max(MIN_SCORE, REL_FLOOR * scored[0].score) if scored else MIN_SCORE
        qualified = [m for m in scored if m.score >= floor]
        picked: list[Match] = []
        held: list[Match] = []
        same = 0
        for m in qualified:
            if len(picked) == k:
                break
            if target.ministry and self._docs[m.id].ministry == target.ministry:
                if same >= MAX_SAME_MINISTRY:
                    held.append(m)
                    continue
                same += 1
            picked.append(m)
        # Nothing else cleared the floor: fill from the held same-ministry picks.
        picked.extend(held[: k - len(picked)])
        return picked


def compute_related(entries: Sequence[_Entry], k: int = TOP_K) -> dict[str, list[Match]]:
    index = RelatedIndex(entries)
    return {e.id: index.top(e.id, k) for e in entries}


# ---- dev CLI -------------------------------------------------------------------

@dataclass
class _CliEntry:
    id: str
    title: str
    summary_he: Optional[str]
    organization_slug: Optional[str]
    organization: Optional[str]
    tags: list[str]
    source_status: str
    live_related: list[str]


def _cli_entries(manifest: Path) -> list[_CliEntry]:
    from .tags import Taxonomy, org_drop_names

    datasets = json.loads(manifest.read_text(encoding="utf-8"))["datasets"]
    tax = Taxonomy.load()
    drop = org_drop_names(d.get("organization") for d in datasets)
    return [
        _CliEntry(
            id=d["id"], title=d["title"], summary_he=d.get("summary_he"),
            organization_slug=d.get("organization_slug"), organization=d.get("organization"),
            tags=d.get("tags") or tax.dataset_tags(
                d["id"], suggested=d.get("suggested_tags") or [],
                ckan=d.get("tags_he") or [], drop_names=drop,
            ),
            source_status=d.get("source_status") or "available",
            live_related=d.get("related_ids") or [],
        )
        for d in datasets
    ]


def _cmd_explain(args: argparse.Namespace) -> int:
    entries = _cli_entries(Path(args.manifest))
    by_id = {e.id: e for e in entries}
    index = RelatedIndex(entries)
    t = by_id[args.id]
    print(f"{t.title} — {t.organization} — {t.tags}")
    chosen = {m.id for m in index.top(args.id)}
    for m in index.score_all(args.id)[: args.limit]:
        c = by_id[m.id]
        mark = "*" if m.id in chosen else " "
        print(f" {mark} {m.score:.3f} {m.signals}  {c.title} ({c.organization})")
    return 0


def _cmd_sample(args: argparse.Namespace) -> int:
    entries = _cli_entries(Path(args.manifest))
    by_id = {e.id: e for e in entries}
    related = compute_related(entries)
    counts = Counter(len(v) for v in related.values())
    same = sum(
        1 for e in entries for m in related[e.id]
        if e.organization_slug and by_id[m.id].organization_slug == e.organization_slug
    )
    total = sum(len(v) for v in related.values()) or 1
    print(f"datasets: {len(entries)}  picks per page: {dict(sorted(counts.items()))}")
    print(f"same-ministry share of picks: {same / total:.0%}")
    inbound = Counter(m.id for v in related.values() for m in v)
    print("most-linked:", [(by_id[i].title, n) for i, n in inbound.most_common(5)])
    rng = random.Random(args.seed)
    for e in rng.sample(entries, min(args.sample, len(entries))):
        print(f"\n## {e.title} ({e.organization}) {e.tags}")
        for m in related[e.id]:
            print(f"   new {m.score:.2f} {by_id[m.id].title} ({by_id[m.id].organization})")
        for rid in e.live_related:
            if rid in by_id:
                print(f"   old      {by_id[rid].title} ({by_id[rid].organization})")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m services.page_builder.related")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("explain")
    p.add_argument("id")
    p.add_argument("--manifest", required=True)
    p.add_argument("--limit", type=int, default=10)
    p = sub.add_parser("sample")
    p.add_argument("--manifest", required=True)
    p.add_argument("--sample", type=int, default=12)
    p.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    return {"explain": _cmd_explain, "sample": _cmd_sample}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
