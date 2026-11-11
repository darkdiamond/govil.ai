"""Explainer candidates for the daily floor, deterministic, no LLM.

When a day has no event story (signals.py found nothing worth printing), the
run can still publish one explainer: "what this dataset shows", on a page
people actually search for. Candidates are datasets with a rendered model
(KPIs, insights, series: something to write from), ranked by Search Console
impressions (demand.py) and kept off any dataset an article used in the last
`cooldown_days`, whatever its kind. Registries without time series qualify
(they draw most of the site's search demand); the writer reads their full
tables through `sql`. The editor (`editor.choose_features`) picks the angle.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.shared.states import ArticleKind

from .series import Series, kpi_values
from .store import published_at

MAX_SERIES = 8
MAX_KPIS = 6
MAX_INSIGHTS = 4


def covered(recent: list[dict], *, days: int, now: datetime | None = None) -> set[str]:
    """Datasets any article published in the last `days` drew on."""
    now = now or datetime.now(UTC)
    out: set[str] = set()
    for a in recent:
        ts = published_at(a)
        if ts and now - ts < timedelta(days=days):
            out.update(a.get("dataset_ids") or [])
    return out


def rejected_leads(rejects: list[dict]) -> set[str]:
    """Lead datasets of recently rejected explainers: the ranking is
    deterministic, so without this the same failing story is retried daily."""
    return {(r.get("brief") or {}).get("dataset_ids", [None])[0] for r in rejects
            if r.get("kind") == ArticleKind.FEATURE and (r.get("brief") or {}).get("dataset_ids")}


def _series_brief(s: Series) -> dict:
    p, v = (s.complete or s.points)[-1]
    return {"series_path": s.path, "label": s.label, "freq": s.freq, "points": len(s.points),
            "first": s.points[0][0].label, "latest": {"period": p.label, "value": v}}


def compact(ds: str, *, catalog: dict, models: dict, series: dict, demand: dict | None) -> dict:
    cat = catalog.get(ds) or {}
    model = models.get(ds) or {}
    raw = kpi_values(model)
    kpis = [{"key": k, "display": (v or {}).get("display"), "value": raw.get(k)}
            for k, v in list((model.get("kpis") or {}).items())[:MAX_KPIS] if isinstance(v, dict)]
    return {
        "dataset_id": ds, "dataset": cat.get("title"), "publisher": cat.get("organization"),
        "kind": cat.get("dataset_kind"), "tags": cat.get("tags") or [],
        "data_updated": str(cat.get("metadata_modified") or "")[:10] or None,
        "summary": (model.get("agent_data") or {}).get("summary_he"),
        "impressions_28d": (demand or {}).get("impressions", 0),
        "kpis": kpis,
        "insights_on_page": [i.get("text_he") for i in (model.get("insights") or [])[:MAX_INSIGHTS]
                             if isinstance(i, dict)],
        "series": [_series_brief(s) for s in (series.get(ds) or [])[:MAX_SERIES] if s.points],
    }


def candidates(*, catalog: dict, models: dict, series: dict, demand_by_id: dict,
               recent: list[dict], cooldown_days: int, top: int = 12,
               exclude: set[str] = frozenset(), now: datetime | None = None) -> list[dict]:
    """The `top` explainer candidates, compacted for the editor, strongest
    demand first. `exclude`: datasets to leave out (recently rejected leads)."""
    skip = covered(recent, days=cooldown_days, now=now) | set(exclude)
    pool = []
    for ds, model in models.items():
        if ds in skip or ds not in catalog or not isinstance(model, dict):
            continue
        has_material = bool(model.get("kpis") or model.get("insights") or series.get(ds))
        if not has_material:
            continue
        imp = (demand_by_id.get(ds) or {}).get("impressions", 0)
        pool.append((-imp, ds))
    return [compact(ds, catalog=catalog, models=models, series=series, demand=demand_by_id.get(ds))
            for _, ds in sorted(pool)[:top]]
