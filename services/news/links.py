"""Cross-dataset context for signals: did a linked dataset move with it?

Edges come from `links.json` (curated economic chains: rate → mortgages →
housing, visitors → hotel nights, …) plus datasets sharing ≥ 2 specific
canonical tags (taxonomy/dataset-tags.json). For a signal on dataset A and
each neighbour B, every B series is compared with the signal's series on
their changes (12-month for monthly, one step for yearly/quarterly), at each
lag in the edge's range; the best |r| over enough overlap is attached when it
clears MIN_R. A correlation is a lead for the writer, never a causal claim.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .series import Series, period_index
from .signals import Signal

LINKS_PATH = Path(__file__).with_name("links.json")
DATASET_TAGS = Path(__file__).resolve().parents[2] / "taxonomy" / "dataset-tags.json"
MIN_R = 0.5
MIN_OVERLAP = {"M": 24, "Q": 12, "Y": 8}
TAG_SHARED_MIN = 2
TAG_MAX_DATASETS = 40          # tags this common ("כלכלה") say nothing specific
TAG_LAG = (0, 3)


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    lag_months: tuple[int, int]
    why_he: str
    source: str               # curated | tags


def load_edges(dataset_ids: set[str], *, links_path: Path = LINKS_PATH,
               tags_path: Path | None = DATASET_TAGS) -> list[Edge]:
    """Curated edges plus shared-tag edges, among `dataset_ids` only."""
    edges = []
    for e in json.loads(links_path.read_text(encoding="utf-8"))["edges"]:
        if e["a"] in dataset_ids and e["b"] in dataset_ids:
            edges.append(Edge(e["a"], e["b"], tuple(e["lag_months"]), e["why_he"], "curated"))
    if tags_path and tags_path.is_file():
        tags = {k: set(v) for k, v in json.loads(tags_path.read_text(encoding="utf-8")).items()
                if k in dataset_ids}
        common = Counter(t for ts in tags.values() for t in ts)
        specific = {k: {t for t in ts if common[t] <= TAG_MAX_DATASETS} for k, ts in tags.items()}
        have = {(e.a, e.b) for e in edges} | {(e.b, e.a) for e in edges}
        ids = sorted(specific)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                shared = specific[a] & specific[b]
                if len(shared) >= TAG_SHARED_MIN and (a, b) not in have:
                    edges.append(Edge(a, b, TAG_LAG, "תגיות משותפות: " + ", ".join(sorted(shared)),
                                      "tags"))
    return edges


def _calendar(s: Series) -> tuple[str, dict[int, float]] | None:
    """The series on a monthly (or its own Q/Y) index: daily/weekly averaged
    to months, step/event series carried forward to each month's end."""
    if s.freq in ("M", "Q", "Y"):
        return s.freq, {period_index(p): v for p, v in s.complete}
    if s.freq in ("D", "W"):
        acc: dict[int, list[float]] = {}
        for p, v in s.complete:
            acc.setdefault(p.start.year * 12 + p.start.month - 1, []).append(v)
        return "M", {k: sum(v) / len(v) for k, v in acc.items()}
    if s.freq == "E":
        out, pts = {}, s.points
        for i, (p, v) in enumerate(pts):
            start = p.start.year * 12 + p.start.month - 1
            end = (pts[i + 1][0].start.year * 12 + pts[i + 1][0].start.month - 1
                   if i + 1 < len(pts) else start + 1)
            for m in range(start, max(end, start + 1)):
                out[m] = v
        return "M", out
    return None


def _changes(freq: str, cal: dict[int, float]) -> dict[int, float]:
    step = 12 if freq == "M" else 1
    return {k: v - cal[k - step] for k, v in cal.items() if k - step in cal}


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)


def best_link(sa: Series, sb_list: list[Series], lag_months: tuple[int, int],
              a_leads: bool) -> dict | None:
    """Best-correlated series of B against `sa`, over the edge's lags."""
    ca = _calendar(sa)
    if ca is None:
        return None
    best = None
    for sb in sb_list:
        cb = _calendar(sb)
        if cb is None or cb[0] != ca[0]:
            continue
        freq = ca[0]
        xa, xb = _changes(freq, ca[1]), _changes(freq, cb[1])
        unit = {"M": 1, "Q": 3, "Y": 12}[freq]
        lags = sorted({round(m / unit) for m in range(lag_months[0], lag_months[1] + 1)})
        for lag in lags:
            shift = lag if a_leads else -lag
            keys = [k for k in xa if k + shift in xb]
            if len(keys) < MIN_OVERLAP[freq]:
                continue
            r = _pearson([xa[k] for k in keys], [xb[k + shift] for k in keys])
            if r is not None and abs(r) >= MIN_R and (best is None or abs(r) > abs(best["r"])):
                best = {"dataset_id": sb.dataset_id, "series_path": sb.path, "label": sb.label,
                        "lag": lag, "lag_unit": freq, "r": round(r, 3), "n": len(keys)}
    return best


def attach_links(signals: list[Signal], series_by_dataset: dict[str, list[Series]],
                 edges: list[Edge]) -> None:
    """Fill each signal's `links` (in place) with its correlated neighbours."""
    by_path = {(s.dataset_id, s.path): s for ss in series_by_dataset.values() for s in ss}
    for sig in signals:
        sa = by_path.get((sig.dataset_id, sig.series_path))
        if sa is None:
            continue
        for e in edges:
            if sig.dataset_id not in (e.a, e.b):
                continue
            other = e.b if e.a == sig.dataset_id else e.a
            link = best_link(sa, series_by_dataset.get(other, []), e.lag_months,
                             a_leads=(e.a == sig.dataset_id))
            if link:
                sig.links.append(link | {"why_he": e.why_he, "source": e.source})
