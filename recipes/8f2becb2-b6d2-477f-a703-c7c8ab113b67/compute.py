"""ברזי כיבוי אש (הידרנטים) בבאר שבע — one row per hydrant: a WGS84 point, a
working-pressure value (0 = not recorded), a house number (0 = none) and two
date columns that are empty today.

The register carries almost no attributes, so the page is about WHERE the
hydrants are (map, density grid, north-south and west-east bands, spacing to
the nearest neighbour), what the few recorded pressures say, and how complete
the register is.  Every figure is an exact count or a rounded integer computed
from sorted data, so the output does not depend on row order.  The other three
resources (XLSX copy, and the same points in ITM coordinates) are twins.
"""
import math

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)      # drops rows with garbage / far-off coordinates
LON_RANGE = (34.0, 36.0)
GRID_STEP = 0.005             # degrees (~500 m)
MAX_GRID = 40
MAX_BANDS = 10
BAND_SCALE = 100              # bands of 0.01 degree (~1 km)
M_PER_DEG = 111320.0
NN_EDGES = [0, 15, 30, 50, 75, 100, 150, 250]   # metres; last bin open-ended
NN_NEAR = 50                  # "close neighbour" threshold, metres
NN_CHUNK = 400
TOP_PRESSURE = 10             # pressure values shown; the rest become "אחר"
MAP_SERIES = 5                # pressure series on the scatter, the rest "אחר"
MAP_MAX_POINTS = 1200         # skip the pressure scatter above this
BAND_MIN_SHARE = 0.15         # a band must hold this share to be worth a sentence
TOP_CELL_SHARE = 0.10         # "the densest tenth of the squares"
CONC_MIN_SHARE = 0.30         # ...must hold this share to be reported
GEO_CELL_SHARE = 0.25         # recorded pressures cover at most this share of squares
GEO_MIN_RECORDED = 10
DIR_SHARE = 0.75              # north/south lean of recorded pressures
MAP_ZOOM = 12                # initial GovMap zoom (a stray far-off row would otherwise zoom out)
GAP_MIN_SHARE = 0.5           # a column this empty is reported


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _num(v):
    return f"{v:g}"


def _prepare(df):
    out = pd.DataFrame({
        "latf": pd.to_numeric(df["lat"].str.strip(), errors="coerce"),
        "lonf": pd.to_numeric(df["lon"].str.strip(), errors="coerce"),
        "press": pd.to_numeric(df["WorkPressu"].str.strip(), errors="coerce"),
        "house": pd.to_numeric(df["HouseNum"].str.strip(), errors="coerce"),
        "inst": df["InstallDat"].str.strip() != "",
        "edit": df["last_edite"].str.strip() != "",
    })
    ok = out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    out["press"] = out["press"].fillna(0.0)
    out["house"] = out["house"].fillna(0.0)
    out = out.sort_values(["latf", "lonf", "press", "house", "inst", "edit"], kind="stable")
    return out.reset_index(drop=True), n_bad


def _bands(values):
    idx = np.floor(np.asarray(values) * BAND_SCALE + 1e-9).astype(int)
    lo, hi = int(idx.min()), int(idx.max())
    w = max(1, math.ceil((hi - lo + 1) / MAX_BANDS))
    lo = (lo // w) * w
    edges = [(a, a + w, f"{a / BAND_SCALE:.2f}-{(a + w) / BAND_SCALE:.2f}")
             for a in range(lo, hi + 1, w)]
    return edges, idx


def _band_rows(values):
    edges, idx = _bands(values)
    rows = []
    for a, b, label in edges:
        rows.append({"label": label, "n": int(((idx >= a) & (idx < b)).sum())})
    return rows


def _grid(df):
    lat, lon = df["latf"].to_numpy(), df["lonf"].to_numpy()
    step = GRID_STEP
    while (math.ceil((lat.max() - lat.min()) / step) + 1 > MAX_GRID
           or math.ceil((lon.max() - lon.min()) / step) + 1 > MAX_GRID):
        step *= 2
    la0, lo0 = math.floor(lat.min() / step) * step, math.floor(lon.min() / step) * step
    iy = np.floor((lat - la0) / step + 1e-9).astype(int)
    ix = np.floor((lon - lo0) / step + 1e-9).astype(int)
    ny, nx = int(iy.max()) + 1, int(ix.max()) + 1
    counts = np.zeros((ny, nx), dtype=int)
    np.add.at(counts, (iy, ix), 1)
    return {"step": step, "la0": la0, "lo0": lo0, "iy": iy, "ix": ix,
            "ny": ny, "nx": nx, "counts": counts}


def _nn_distances(df):
    """Straight-line distance (m) from each distinct point to its nearest other point."""
    pts = df[["latf", "lonf"]].drop_duplicates().sort_values(["latf", "lonf"], kind="stable")
    n = len(pts)
    if n < 2:
        return np.array([])
    lat0 = math.fsum(pts["latf"].tolist()) / n
    y = (pts["latf"].to_numpy() - lat0) * M_PER_DEG
    x = (pts["lonf"].to_numpy() - pts["lonf"].iloc[0]) * M_PER_DEG * math.cos(math.radians(lat0))
    best = np.empty(n)
    for s in range(0, n, NN_CHUNK):
        e = min(n, s + NN_CHUNK)
        d2 = (x[s:e, None] - x[None, :]) ** 2 + (y[s:e, None] - y[None, :]) ** 2
        d2[np.arange(e - s), np.arange(s, e)] = np.inf
        best[s:e] = np.sqrt(d2.min(axis=1))
    return best


def insight_density(total, cells_n, best_n, step_m):
    if total == 0 or cells_n == 0:
        return None
    return (f"{_int(total)} הברזים פזורים על פני {_int(cells_n)} ריבועים של כ-{_int(step_m)} מטר; "
            f"בריבוע הצפוף ביותר יש {_int(best_n)} ברזים.")


def insight_concentration(top_n, top_share, top_cells, cells_n):
    if cells_n < 10 or top_share < CONC_MIN_SHARE:
        return None
    return (f"{_int(top_cells)} הריבועים הצפופים ביותר, עשירית מהריבועים שיש בהם ברזים, "
            f"מכילים {_pct(top_share)} מכלל הברזים ({_int(top_n)}).")


def insight_band(rows, total, which):
    if total == 0 or len(rows) < 3:
        return None
    top = max(rows, key=lambda r: (r["n"], r["label"]))
    share = top["n"] / total
    if share < BAND_MIN_SHARE:
        return None
    axis = "קו הרוחב" if which == "lat" else "קו האורך"
    lo, hi = top["label"].split("-")
    return (f"הרצועה הצפופה ביותר היא {axis} בין {lo} ל-{hi}: "
            f"{_int(top['n'])} ברזים, {_pct(share)} מהמאגר.")


def insight_spacing(nn):
    if len(nn) < 2:
        return None
    med = int(round(float(np.median(nn))))
    near = float((nn <= NN_NEAR).sum()) / len(nn)
    return (f"המרחק החציוני בקו אווירי מברז לברז הקרוב אליו הוא {_int(med)} מטר, "
            f"ו-{_pct(near)} מהנקודות נמצאות במרחק של עד {_int(NN_NEAR)} מטר מברז אחר.")


def insight_pressure(n_rec, total, top):
    if n_rec == 0 or total == 0:
        return None
    share = n_rec / total
    lead = f"הערך הנפוץ ביותר הוא {top[0]} ({_int(top[1])} ברזים)"
    if share < 0.5:
        return f"רק {_pct(share, 1)} מהברזים ({_int(n_rec)}) כוללים לחץ עבודה מתועד. {lead}."
    return f"ל-{_pct(share, 1)} מהברזים ({_int(n_rec)}) יש לחץ עבודה מתועד. {lead}."


def insight_pressure_geo(n_rec, rec_cells, cells_n, north_share):
    if n_rec < GEO_MIN_RECORDED or cells_n < 10:
        return None
    if rec_cells / cells_n > GEO_CELL_SHARE:
        return None
    text = (f"הברזים עם לחץ מתועד מרוכזים ב-{_int(rec_cells)} ריבועים בלבד מתוך "
            f"{_int(cells_n)} ריבועי העיר שיש בהם ברזים")
    if north_share >= DIR_SHARE:
        text += f", {_pct(north_share)} מהם בחציון הצפוני של המאגר"
    elif north_share <= 1 - DIR_SHARE:
        text += f", {_pct(1 - north_share)} מהם בחציון הדרומי של המאגר"
    return text + "."


def insight_gaps(total, n_noinst, n_noedit):
    if total == 0:
        return None
    if n_noinst == total and n_noedit == total:
        return ("בשום ברז לא מצוין תאריך התקנה או תאריך עדכון אחרון, ולכן המאגר לא מאפשר לראות "
                "מתי הוקם כל ברז או מתי נבדק.")
    parts = []
    if n_noinst / total >= GAP_MIN_SHARE:
        parts.append(f"בלי תאריך התקנה ב-{_pct(n_noinst / total)} מהברזים")
    if n_noedit / total >= GAP_MIN_SHARE:
        parts.append(f"בלי תאריך עדכון אחרון ב-{_pct(n_noedit / total)}")
    if not parts:
        return None
    return "פערים במאגר: " + " ו".join(parts) + "."


def insight_duplicates(n_dup):
    if n_dup <= 0:
        return None
    who = "רשומה אחת נמצאת" if n_dup == 1 else f"{_int(n_dup)} רשומות נמצאות"
    return (f"{who} בדיוק באותן קואורדינטות כמו רשומה אחרת, "
            f"ככל הנראה כפילות; הן נספרות כאן כברזים נפרדים.")


def insight_excluded(n_bad):
    if n_bad <= 0:
        return None
    who = "רשומה אחת" if n_bad == 1 else f"{_int(n_bad)} רשומות"
    return f"{who} עם קואורדינטות מחוץ לאזור הסביר לא נכללה בתרשימי המיקום ובחישובי הצפיפות."


def compute(frames):
    df, n_bad = _prepare(frames["hydrants"])
    total = len(df)
    if total == 0:
        return {"agent_data": {"summary_he": "אין ברזים עם קואורדינטות תקינות.",
                               "dataset_kind": "map", "suggested_tags": ["הידרנטים"],
                               "related_ids": []},
                "kpis": {}, "charts": {}, "insights": [], "labels": {}, "tables": {}}

    # ---- density grid
    g = _grid(df)
    counts, step = g["counts"], g["step"]
    step_m = int(round(step * M_PER_DEG / 50.0) * 50)
    ny, nx = g["ny"], g["nx"]
    xs = [f"{g['lo0'] + i * step:.3f}" for i in range(nx)]
    ys = [f"{g['la0'] + j * step:.3f}" for j in range(ny)]
    cells = [[i, ny - 1 - j, int(counts[j, i])] for j in range(ny) for i in range(nx) if counts[j, i]]
    cells_n = len(cells)
    flat = sorted((int(c) for c in counts[counts > 0]), reverse=True)
    best_n = flat[0]
    top_cells = max(1, int(round(cells_n * TOP_CELL_SHARE)))
    top_n = sum(flat[:top_cells])
    density_chart = {"x": xs, "y": ys[::-1], "cells": cells, "max": best_n}

    # ---- bands
    lat_rows = _band_rows(df["latf"].to_numpy())[::-1]          # north first
    lon_rows = _band_rows(df["lonf"].to_numpy())                # west first
    for rows in (lat_rows, lon_rows):
        for r in rows:
            r["share"] = r["n"] / total
    lat_chart = {"names": [r["label"] for r in lat_rows], "values": [r["n"] for r in lat_rows]}
    lon_chart = {"names": [r["label"] for r in lon_rows], "values": [r["n"] for r in lon_rows]}
    t_lat = [{"name": r["label"], "n": _int(r["n"]), "share": _pct(r["share"], 1)} for r in lat_rows]
    t_lon = [{"name": r["label"], "n": _int(r["n"]), "share": _pct(r["share"], 1)} for r in lon_rows]

    # ---- nearest-neighbour spacing
    nn = _nn_distances(df)
    nn_names, nn_vals = [], []
    if len(nn):
        for i, lo in enumerate(NN_EDGES):
            hi = NN_EDGES[i + 1] if i + 1 < len(NN_EDGES) else None
            m = (nn >= lo) & ((nn < hi) if hi is not None else True)
            nn_names.append(f"{lo}-{hi}" if hi is not None else f"מעל {lo}")
            nn_vals.append(int(m.sum()))
    nn_total = max(len(nn), 1)
    nn_chart = {"names": nn_names, "values": nn_vals}
    t_nn = [{"name": n, "count": _int(v), "share": _pct(v / nn_total, 1)}
            for n, v in zip(nn_names, nn_vals)]
    median_nn = int(round(float(np.median(nn)))) if len(nn) else 0

    # ---- pressure
    rec = df[df["press"] > 0]
    n_rec = len(rec)
    pv = rec["press"].value_counts()
    pairs = sorted(((float(v), int(c)) for v, c in pv.items()), key=lambda r: (-r[1], r[0]))
    shown = pairs[:TOP_PRESSURE]
    rest = sum(c for _, c in pairs[TOP_PRESSURE:])
    p_names = [_num(v) for v, _ in shown] + (["אחר"] if rest else [])
    p_vals = [c for _, c in shown] + ([rest] if rest else [])
    pressure_chart = {"names": p_names, "values": p_vals}
    t_pressure = [{"name": n, "count": _int(v), "share": _pct(v / n_rec, 1)}
                  for n, v in zip(p_names, p_vals)] if n_rec else []
    top_pressure = (_num(pairs[0][0]), pairs[0][1]) if pairs else None

    # pressure scatter: one series per top value
    has_pmap = 0 < n_rec <= MAP_MAX_POINTS
    pmap_series = []
    if has_pmap:
        top_vals = [v for v, _ in pairs[:MAP_SERIES]]
        for v in top_vals:
            sub = rec[rec["press"] == v]
            pmap_series.append({"name": _num(v), "data": [[round(a, 5), round(b, 5)]
                                for a, b in zip(sub["lonf"], sub["latf"])]})
        other = rec[~rec["press"].isin(top_vals)]
        if len(other):
            pmap_series.append({"name": "אחר", "data": [[round(a, 5), round(b, 5)]
                                for a, b in zip(other["lonf"], other["latf"])]})
    rec_cells = len(set(zip(g["iy"][(df["press"] > 0).to_numpy()].tolist(),
                            g["ix"][(df["press"] > 0).to_numpy()].tolist()))) if n_rec else 0
    med_lat = float(np.median(df["latf"].to_numpy()))
    north_share = float((rec["latf"] > med_lat).sum()) / n_rec if n_rec else 0.0

    # ---- completeness
    n_nopress = total - n_rec
    n_nohouse = int((df["house"] <= 0).sum())
    n_noinst = int((~df["inst"]).sum())
    n_noedit = int((~df["edit"]).sum())
    n_dup = total - len(df[["latf", "lonf"]].drop_duplicates())
    quality = [("בלי לחץ עבודה", n_nopress), ("בלי מספר בית", n_nohouse),
               ("בלי תאריך התקנה", n_noinst), ("בלי תאריך עדכון אחרון", n_noedit),
               ("נקודה זהה לברז אחר", n_dup)]
    quality.sort(key=lambda r: (-r[1], r[0]))
    quality_chart = {"names": [n for n, _ in quality], "values": [v for _, v in quality]}
    t_quality = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in quality]

    rules = [
        ("density", insight_density(total, cells_n, best_n, step_m)),
        ("concentration", insight_concentration(top_n, top_n / total, top_cells, cells_n)),
        ("band", insight_band(lat_rows, total, "lat")),
        ("spacing", insight_spacing(nn)),
        ("pressure", insight_pressure(n_rec, total, top_pressure)),
        ("pressure-geo", insight_pressure_geo(n_rec, rec_cells, cells_n, north_share)),
        ("gaps", insight_gaps(total, n_noinst, n_noedit)),
        ("duplicates", insight_duplicates(n_dup)),
        ("excluded", insight_excluded(n_bad)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    rec_share = n_rec / total
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand", "label": "ברזי כיבוי אש במאגר"},
        "spacing": {"value": median_nn, "display": _int(median_nn), "tone": "brand",
                    "label": "חציון המרחק לברז הקרוב ביותר (מטרים, בקו אווירי)"},
        "cells": {"value": cells_n, "display": _int(cells_n), "tone": "brand",
                  "label": f"ריבועים של כ-{_int(step_m)} מטר שיש בהם ברזים"},
        "pressure-share": {"value": rec_share, "display": _pct(rec_share, 1),
                           "tone": "warn" if rec_share < 0.5 else "ok" if rec_share >= 0.9 else "info",
                           "label": "מהברזים עם לחץ עבודה מתועד"},
    }

    bad_note = (" רשומה אחת בלי קואורדינטות סבירות לא נכללה." if n_bad == 1
                else f" {_int(n_bad)} רשומות בלי קואורדינטות סבירות לא נכללו." if n_bad else "")
    labels = {
        "lede": (f"{_int(total)} ברזי כיבוי אש (הידרנטים) בעיר, כל אחד כנקודה על המפה. "
                 f"המאגר כמעט לא נושא מאפיינים נוספים, ולכן העמוד מראה איפה הברזים, כמה הם צפופים, "
                 f"מה ידוע על לחץ העבודה ואילו שדות חסרים.{bad_note}"),
        "map_note": (f"כל {_int(total)} הברזים על המפה. לחצו על אשכול כדי להתקרב, ועל סמן כדי לראות את הפרטים הרשומים."),
        "density_note": (f"מפת חום של צפיפות הברזים בריבועים של כ-{_int(step_m)} מטר. "
                         f"{_int(cells_n)} ריבועים מכילים ברזים; הכהים צפופים יותר."),
        "density_aria": f"מפת חום: צפיפות הברזים ב-{_int(cells_n)} ריבועים.",
        "lat_note": "מספר הברזים בכל רצועה של קו רוחב, מהצפון (למעלה) לדרום.",
        "lat_aria": f"תרשים עמודות אופקי: ברזים ב-{len(lat_rows)} רצועות קו רוחב.",
        "lat_caption": "מספר הברזים לפי רצועת קו רוחב, מצפון לדרום.",
        "lon_note": "מספר הברזים בכל רצועה של קו אורך, מהמערב (למעלה) למזרח.",
        "lon_aria": f"תרשים עמודות אופקי: ברזים ב-{len(lon_rows)} רצועות קו אורך.",
        "lon_caption": "מספר הברזים לפי רצועת קו אורך, ממערב למזרח.",
        "nn_note": (f"לכל נקודה נמדד המרחק בקו אווירי לברז הקרוב אליה (נקודות זהות נספרות פעם אחת). "
                    f"החציון הוא {_int(median_nn)} מטר."),
        "nn_aria": f"תרשים עמודות: התפלגות המרחק לברז הקרוב, {len(nn_names)} טווחים במטרים.",
        "nn_caption": "מספר הנקודות לפי המרחק (במטרים) לברז הקרוב ביותר.",
        "pressure_note": (f"הערכים שמופיעים בשדה לחץ העבודה, בלי הרשומות שבהן הוא 0 (לא מתועד), "
                          f"שהן {_int(n_nopress)} מתוך {_int(total)}. המאגר אינו מציין יחידת מידה."),
        "pressure_aria": f"תרשים עמודות אופקי: {len(p_names)} ערכי לחץ עבודה מתועדים.",
        "pressure_caption": "מספר הברזים לפי ערך לחץ העבודה המתועד.",
        "pmap_note": (f"מיקום {_int(n_rec)} הברזים עם לחץ מתועד, צבע לכל ערך. שאר הברזים לא מסומנים כאן."),
        "pmap_aria": f"תרשים פיזור: מיקום {_int(n_rec)} ברזים עם לחץ עבודה מתועד.",
        "quality_note": "כמה רשומות חסרות כל שדה. ככל שהעמודה קצרה, המאגר מלא יותר בשדה הזה.",
        "quality_aria": f"תרשים עמודות אופקי: {len(quality)} סוגי פערים במאגר.",
        "quality_caption": "מספר הרשומות לפי סוג הפער.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} ברזי כיבוי אש בבאר שבע על מפה, עם צפיפות לפי אזור, "
                           f"מרחק חציוני של {_int(median_nn)} מטר בין ברזים שכנים "
                           f"ולחץ עבודה מתועד ב-{_pct(rec_share, 1)} מהם."),
            "dataset_kind": "map",
            "suggested_tags": ["הידרנטים", "כיבוי אש", "באר שבע", "תשתיות עירוניות", "מים"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["7edbd028-9704-440c-a1b6-a0ed566081bc",
                            "566c2420-1b00-4813-8a75-c6d8750c5ec8",
                            "023b7883-3599-4cb7-adef-1a76ea051cf0",
                            "57a5938f-65cc-48a8-bcfb-8d383e646aaa",
                            "82a30a97-01b0-4281-854c-c7931f3445c0"],
        },
        "kpis": kpis,
        "charts": {"density": density_chart, "lat": lat_chart, "lon": lon_chart,
                   "nn": nn_chart, "pressure": pressure_chart,
                   "pmap": {"series": pmap_series}, "quality": quality_chart},
        "tables": {"lat": t_lat, "lon": t_lon, "nn": t_nn, "pressure": t_pressure,
                   "quality": t_quality},
        "insights": insights,
        "map_view": {"lat": round(med_lat, 4),
                     "lon": round(float(np.median(df["lonf"].to_numpy())), 4),
                     "zoom": MAP_ZOOM},
        "has_nn": bool(nn_vals),
        "has_pressure": bool(n_rec),
        "has_pmap": bool(pmap_series),
        "labels": labels,
    }
