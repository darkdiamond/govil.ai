"""Article charts: the writer names series or facts, this module fills in the
data — so a chart can only show values that exist in our datasets.

    line: series refs {dataset_id, series_path, name, from?} → x = the union of
          their periods (one frequency), y = each series' values (None gaps)
    bar:  bars [{label, fact}] → the facts' values

Output is a chart dict the frontend wraps with `GovEcharts.option` (palette,
Rubik, RTL tooltip): {id, type, title, unit, option, table, dataset_ids}.
`table` is the same data as rows (noscript/accessibility fallback).
"""
from __future__ import annotations

from .ledger import Ledger
from .series import Series

MAX_SERIES = 4
MAX_POINTS = 240
MAX_BARS = 16


class ChartError(ValueError):
    pass


def _scale(values: list[float]) -> bool:
    """VAXIS-BASELINE rule (agent/system-prompt.md): don't pin zero into the
    axis when the data lives far from it."""
    vs = [v for v in values if v is not None]
    if not vs:
        return False
    lo, hi = min(vs), max(vs)
    span = hi - lo
    return span > 0 and min(abs(lo), abs(hi)) > 4 * span


def resolve(spec: dict, series_by_ds: dict[str, list[Series]], ledger: Ledger) -> dict:
    cid = str(spec.get("id") or "")
    kind = spec.get("type")
    title = str(spec.get("title") or "").strip()
    unit = str(spec.get("unit") or "").strip()
    if not cid or not title:
        raise ChartError("a chart needs an id and a title")
    if kind == "line":
        refs = spec.get("series") or []
        if not 1 <= len(refs) <= MAX_SERIES:
            raise ChartError(f"chart {cid}: 1–{MAX_SERIES} series")
        picked: list[tuple[str, Series, str | None]] = []
        for r in refs:
            s = next((x for x in series_by_ds.get(r.get("dataset_id"), [])
                      if x.path == r.get("series_path")), None)
            if s is None:
                raise ChartError(f"chart {cid}: no series {r.get('series_path')!r} in {r.get('dataset_id')}")
            picked.append((str(r.get("name") or s.label or s.path), s, r.get("from")))
        freqs = {s.freq for _, s, _ in picked}
        if len(freqs) != 1:
            raise ChartError(f"chart {cid}: series of different frequencies")
        by_label: dict[str, object] = {}
        data = []
        for _, s, frm in picked:
            pts = s.complete
            if frm:
                start = next((p.start for p, _ in pts if p.label == frm), None)
                if start is None:
                    raise ChartError(f"chart {cid}: period {frm!r} not in {s.path}")
                pts = [(p, v) for p, v in pts if p.start >= start]
            pts = pts[-MAX_POINTS:]
            for p, _ in pts:
                by_label[p.label] = p.start
            data.append({p.label: v for p, v in pts})
        x = sorted(by_label, key=by_label.get)
        series = [{"type": "line", "name": name, "showSymbol": len(x) <= 36,
                   "data": [d.get(lbl) for lbl in x], "connectNulls": False}
                  for (name, _, _), d in zip(picked, data, strict=True)]
        allv = [v for s in series for v in s["data"]]
        option = {"xAxis": {"type": "category", "data": x},
                  "yAxis": {"type": "value", "scale": _scale(allv), "name": unit},
                  "series": series, "tooltip": {"trigger": "axis"}}
        if len(series) > 1:
            option["legend"] = {"top": 0}
        table = [["", *[s["name"] for s in series]]] + [
            [lbl, *[s["data"][i] for s in series]] for i, lbl in enumerate(x)]
        dsids = sorted({s.dataset_id for _, s, _ in picked})
    elif kind == "bar":
        bars = spec.get("bars") or []
        if not 1 <= len(bars) <= MAX_BARS:
            raise ChartError(f"chart {cid}: 1–{MAX_BARS} bars")
        labels, vals, dsids = [], [], set()
        for b in bars:
            f = ledger.facts.get(b.get("fact"))
            if f is None:
                raise ChartError(f"chart {cid}: unknown fact {b.get('fact')}")
            labels.append(str(b.get("label") or f.label))
            vals.append(f.value)
            if f.dataset_id:
                dsids.add(f.dataset_id)
        option = {"xAxis": {"type": "category", "data": labels},
                  "yAxis": {"type": "value", "scale": _scale(vals), "name": unit},
                  "series": [{"type": "bar", "data": vals}], "tooltip": {"trigger": "axis"}}
        table = [["", unit or title]] + [[lbl, v] for lbl, v in zip(labels, vals, strict=True)]
        dsids = sorted(dsids)
    else:
        raise ChartError(f"chart {cid}: type must be line or bar")
    return {"id": cid, "type": kind, "title": title, "unit": unit, "option": option,
            "table": table, "dataset_ids": dsids}


def main_series(spec: dict, series_by_ds: dict[str, list[Series]]) -> list[float]:
    """The first line series' values — for the chart-card hero fallback."""
    for r in spec.get("series") or []:
        for s in series_by_ds.get(r.get("dataset_id"), []):
            if s.path == r.get("series_path"):
                return [v for _, v in s.complete[-60:]]
    return []
