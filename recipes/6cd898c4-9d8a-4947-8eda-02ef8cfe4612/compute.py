"""רמזורים באר שבע — one row per traffic light: WGS84 position plus the
number printed on the signal (blank for about a quarter of the rows).

The number identifies a junction, not a single signal: all the lights that
share a number sit within a few tens of metres of each other.  The page
therefore groups lights into junctions two ways: by number (documented ones)
and by proximity (single-linkage, LINK_M metres) so that unnumbered lights
form junctions too.  The CSV, XLSX and ITM resources are twins of one table;
only the CSV is read.

Rows whose coordinates are not finite numbers inside Israel's bounding box
(the export carries one "Infinity" row) are excluded and disclosed.
Order-independent: rows are sorted first; integer counts, medians, fsum.
"""
import math

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
R_KM = 6371.0088
LINK_M = 40
RING_KM = 2
MAX_RINGS = 8
CORE_KM = 5
MAX_BANDS = 16
SIZE_CAP = 6
SPAN_BIN_M = 10
SPAN_BINS = 6
SP_BIN_M = 100
SP_BINS = 10
MIN_GROUP = 10
FAR_RATIO = 2
GRID_MIN_SHARE = 0.05
COMPACT_M = 30
COMPACT_SHARE = 0.8
BAND_WIDTHS = [10, 25, 50, 100, 250, 500, 1000, 5000]
MAX_NUM_BANDS = 16
CHUNK = 400


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _prepare(df):
    out = pd.DataFrame({
        "latf": pd.to_numeric(df["lat"].str.strip(), errors="coerce"),
        "lonf": pd.to_numeric(df["lon"].str.strip(), errors="coerce"),
        "num": pd.to_numeric(df["LightNumbe"].str.strip(), errors="coerce"),
    })
    ok = out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    out.loc[~np.isfinite(out["num"]) | (out["num"] <= 0) | (out["num"] % 1 != 0), "num"] = np.nan
    out = out.sort_values(["latf", "lonf", "num"], kind="stable", na_position="last")
    return out.reset_index(drop=True), n_bad


def _link(x, y, thr):
    """Single-linkage components (union-find); returns a label array whose
    labels are the lowest member index (deterministic on a sorted frame)."""
    n = len(x)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for s in range(0, n, CHUNK):
        e = min(n, s + CHUNK)
        d = np.hypot(x[s:e, None] - x[None, :], y[s:e, None] - y[None, :])
        ii, jj = np.where(d <= thr)
        for i, j in zip((ii + s).tolist(), jj.tolist()):
            if i < j:
                ri, rj = find(i), find(j)
                if ri != rj:
                    if ri < rj:
                        parent[rj] = ri
                    else:
                        parent[ri] = rj
    return np.array([find(i) for i in range(n)])


def _nearest(x, y):
    n = len(x)
    out = np.full(n, np.inf)
    if n < 2:
        return out
    for s in range(0, n, CHUNK):
        e = min(n, s + CHUNK)
        d = np.hypot(x[s:e, None] - x[None, :], y[s:e, None] - y[None, :])
        d[np.arange(e - s), np.arange(s, e)] = np.inf
        out[s:e] = d.min(axis=1)
    return out


def _bands(values, scale=100):
    idx = np.floor(np.asarray(values) * scale + 1e-9).astype(int)
    lo, hi = int(idx.min()), int(idx.max())
    w = max(1, math.ceil((hi - lo + 1) / MAX_BANDS))
    lo = (lo // w) * w
    return idx, lo, hi, w


def _label(a, scale=100):
    return f"{a / scale:.2f}"


def _short(names):
    """'עד 100' -> '100', 'מעל 900' -> '900+' (LTR-safe) for crowded chart axes."""
    out = []
    for n in names:
        num = n.split()[-1]
        out.append(f"\u202a{num}+\u202c" if n.startswith("מעל") else num)
    return out


# ---------------------------------------------------------------- insights
def insight_numbered(n_num, total):
    if not total:
        return None
    un = total - n_num
    return (f"{_int(n_num)} מתוך {_int(total)} הרמזורים ({_pct(n_num / total, 1)}) נושאים מספר רמזור; "
            f"{_int(un)} נרשמו במאגר עם מיקום בלבד, בלי מספר.")


def insight_heads(per_num):
    if len(per_num) < MIN_GROUP:
        return None
    vc = per_num.value_counts()
    top = sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    mx = int(per_num.max())
    tail = ""
    if mx > top[0]:
        names = sorted(int(k) for k in per_num[per_num == mx].index)
        tail = (f"; הכי הרבה רמזורים תחת מספר אחד: {_int(mx)}, "
                f"במספר {', '.join(str(v) for v in names[:3])}")
    return (f"המספר מזהה צומת ולא רמזור בודד: ב-{_int(top[1])} מתוך {_int(len(per_num))} המספרים "
            f"השונים מופיעים בדיוק {_int(top[0])} רמזורים{tail}.")


def insight_distance(dn, du):
    if len(dn) < MIN_GROUP or len(du) < MIN_GROUP:
        return None
    mn, mu = float(np.median(dn)), float(np.median(du))
    if mu < FAR_RATIO * max(mn, 0.1):
        return None
    return (f"הרמזורים ללא מספר מרוחקים יותר: המרחק החציוני שלהם ממרכז הפריסה הוא {mu:.1f} ק״מ, "
            f"לעומת {mn:.1f} ק״מ ברמזורים הממוספרים.")


def insight_junctions(n_j, n_j_un, n_sing):
    if n_j < MIN_GROUP:
        return None
    return (f"בקירוב {_int(n_j)} צמתים (קבוצות רמזורים שמרחקן עד {_int(LINK_M)} מטרים זה מזה); "
            f"ב-{_int(n_j_un)} מהם אין אף רמזור ממוספר. {_int(n_sing)} צמתים מורכבים מרמזור בודד.")


def insight_spacing(sp):
    if len(sp) < MIN_GROUP:
        return None
    med = float(np.median(sp))
    near = float((sp <= 200).mean())
    return (f"המרחק החציוני בין מרכז צומת למרכז הצומת הקרוב אליו הוא {_int(round(med))} מטרים; "
            f"ל-{_pct(near)} מהצמתים יש צומת אחר במרחק של עד {_int(200)} מטרים.")


def insight_footprint(spans):
    if len(spans) < MIN_GROUP:
        return None
    share = float((spans <= COMPACT_M).mean())
    if share < COMPACT_SHARE:
        return None
    return (f"צומת הוא אתר קומפקטי: ב-{_pct(share)} מ-{_int(len(spans))} הצמתים שבהם יותר מרמזור אחד "
            f"המרחק בין הרמזורים הרחוקים ביותר הוא עד {_int(COMPACT_M)} מטרים.")


def insight_gaps(used, top, unused):
    if top < MIN_GROUP or unused <= 0:
        return None
    return (f"המספרים בשימוש מגיעים עד {_int(top)}, אבל רק {_int(used)} מהם מופיעים במאגר; "
            f"{_int(unused)} מספרים בטווח לא משויכים לאף רמזור.")


def insight_mixed(n_mixed, n_un_in_mixed):
    if not n_mixed:
        return None
    return (f"ב-{_int(n_mixed)} צמתים יש רמזורים ממוספרים לצד רמזורים בלי מספר "
            f"({_int(n_un_in_mixed)} רמזורים) — כנראה שהמספר חסר ברשומות אלה.")


def insight_grid(n_top, core_n, lat_l, lon_l, cell_km):
    if core_n < MIN_GROUP or n_top / core_n < GRID_MIN_SHARE:
        return None
    return (f"בליבת העיר (עד {_int(CORE_KM)} ק״מ מהמרכז) תא הצפיפות הגבוה ביותר, בקו רוחב {lat_l} "
            f"וקו אורך {lon_l}, מכיל {_int(n_top)} רמזורים — {_pct(n_top / core_n, 1)} מליבת העיר.")


# ----------------------------------------------------------------- compute
def compute(frames):
    df, n_bad = _prepare(frames["main"])
    total = len(df)
    if total < 2:
        return {"agent_data": {"summary_he": "אין רשומות עם מיקום תקין", "dataset_kind": "map"},
                "kpis": {}, "charts": {}, "insights": []}

    lat0 = (df["latf"].min() + df["latf"].max()) / 2
    k = math.cos(math.radians(lat0))
    x = np.radians(df["lonf"].to_numpy()) * R_KM * k * 1000.0
    y = np.radians(df["latf"].to_numpy()) * R_KM * 1000.0
    has_num = df["num"].notna().to_numpy()
    n_num = int(has_num.sum())

    # ---- distance from centre, numbered vs not
    cx, cy = float(np.median(x)), float(np.median(y))
    dist_km = np.hypot(x - cx, y - cy) / 1000.0
    rb = np.minimum((dist_km // RING_KM).astype(int), MAX_RINGS - 1)
    rn = [int(((rb == i) & has_num).sum()) for i in range(MAX_RINGS)]
    ru = [int(((rb == i) & ~has_num).sum()) for i in range(MAX_RINGS)]
    last = max([i for i in range(MAX_RINGS) if rn[i] + ru[i]] or [0])
    rn, ru = rn[: last + 1], ru[: last + 1]
    rnames = [f"עד {(i + 1) * RING_KM}" for i in range(len(rn))]
    if last == MAX_RINGS - 1:
        rnames[-1] = f"מעל {(MAX_RINGS - 1) * RING_KM}"
    radial = {"names": _short(rnames), "numbered": rn, "unnumbered": ru}
    t_radial = [{"name": n, "numbered": _int(a), "unnumbered": _int(b), "total": _int(a + b)}
                for n, a, b in zip(rnames, rn, ru)]

    # ---- junctions by proximity
    lab = _link(x, y, LINK_M)
    cl = pd.DataFrame({"lab": lab, "x": x, "y": y, "num": df["num"].to_numpy(), "has": has_num})
    groups = []
    for _, g in cl.groupby("lab", sort=True):
        gx, gy = g["x"].to_numpy(), g["y"].to_numpy()
        span = 0.0
        if len(g) > 1:
            span = float(np.hypot(gx[:, None] - gx[None, :], gy[:, None] - gy[None, :]).max())
        groups.append({"n": len(g), "named": int(g["has"].sum()),
                       "cx": math.fsum(gx.tolist()) / len(g), "cy": math.fsum(gy.tolist()) / len(g),
                       "span": span})
    gdf = pd.DataFrame(groups)
    n_j = len(gdf)
    n_j_un = int((gdf["named"] == 0).sum())
    mixed = gdf[(gdf["named"] > 0) & (gdf["named"] < gdf["n"])]
    n_mixed = len(mixed)
    n_un_in_mixed = int((mixed["n"] - mixed["named"]).sum())
    n_sing = int((gdf["n"] == 1).sum())

    # sizes
    sz = np.minimum(gdf["n"].to_numpy(), SIZE_CAP)
    snames = [str(i) for i in range(1, SIZE_CAP)] + [f"{SIZE_CAP} ומעלה"]
    svals = [int((sz == i).sum()) for i in range(1, SIZE_CAP + 1)]
    while len(svals) > 1 and svals[-1] == 0:
        svals.pop()
        snames.pop()
    if len(svals) == SIZE_CAP and svals[-1]:
        pass
    sizes = {"names": snames, "values": svals}
    t_sizes = [{"name": n, "count": _int(v), "share": _pct(v / n_j, 1)}
               for n, v in zip(snames, svals)]
    modal = sorted(zip(svals, snames), key=lambda t: (-t[0], t[1]))[0]

    # spacing between junction centres
    gx = gdf["cx"].to_numpy()
    gy = gdf["cy"].to_numpy()
    nn = _nearest(gx, gy)
    nn = nn[np.isfinite(nn)]
    if len(nn):
        nb = np.minimum((nn // SP_BIN_M).astype(int), SP_BINS - 1)
        sp_vals = [int((nb == i).sum()) for i in range(SP_BINS)]
        sp_names = [f"עד {(i + 1) * SP_BIN_M}" for i in range(SP_BINS - 1)] + [f"מעל {(SP_BINS - 1) * SP_BIN_M}"]
        while len(sp_vals) > 1 and sp_vals[-1] == 0 and sp_vals[-2] == 0:
            sp_vals.pop()
            sp_names.pop()
        if len(sp_vals) < SP_BINS and sp_names:
            sp_names[-1] = sp_names[-1]
    else:
        sp_vals, sp_names = [], []
    spacing = {"names": _short(sp_names), "values": sp_vals}
    t_spacing = [{"name": n, "count": _int(v), "share": _pct(v / len(nn), 1)}
                 for n, v in zip(sp_names, sp_vals)] if len(nn) else []
    med_sp = float(np.median(nn)) if len(nn) else 0.0

    # footprint of multi-light junctions
    spans = gdf.loc[gdf["n"] > 1, "span"].to_numpy()
    if len(spans):
        pb = np.minimum((spans // SPAN_BIN_M).astype(int), SPAN_BINS - 1)
        pv = [int((pb == i).sum()) for i in range(SPAN_BINS)]
        pn = [f"עד {(i + 1) * SPAN_BIN_M}" for i in range(SPAN_BINS - 1)] + [f"מעל {(SPAN_BINS - 1) * SPAN_BIN_M}"]
        while len(pv) > 1 and pv[-1] == 0 and pv[-2] == 0:
            pv.pop()
            pn.pop()
    else:
        pv, pn = [], []
    span_chart = {"names": _short(pn), "values": pv}
    t_span = [{"name": n, "count": _int(v), "share": _pct(v / len(spans), 1)}
              for n, v in zip(pn, pv)] if len(spans) else []

    # ---- numbers
    nums = df.loc[has_num, "num"].astype(int)
    per_num = nums.value_counts().sort_index()
    used = int(len(per_num))
    top_num = int(nums.max()) if used else 0
    unused = top_num - used if used else 0
    nb_chart = {"names": [], "used": [], "gap": []}
    t_nb = []
    if used:
        w = next((w for w in BAND_WIDTHS if math.ceil(top_num / w) <= MAX_NUM_BANDS), BAND_WIDTHS[-1])
        nbands = math.ceil(top_num / w)
        band = ((per_num.index.to_numpy() - 1) // w).astype(int)
        for b in range(nbands):
            lo, hi = b * w + 1, min((b + 1) * w, top_num)
            u = int((band == b).sum())
            nb_chart["names"].append(f"‎{lo}-{hi}")
            nb_chart["used"].append(u)
            nb_chart["gap"].append(hi - lo + 1 - u)
        t_nb = [{"name": n, "used": _int(u), "gap": _int(g)}
                for n, u, g in zip(nb_chart["names"], nb_chart["used"], nb_chart["gap"])]

    # ---- density grid (core of the city only)
    core = dist_km <= CORE_KM
    core_n = int(core.sum())
    grid = {"x": [], "y": [], "data": [], "max": 0}
    top_cell = (0, "", "")
    cell_km = 0.0
    if core_n >= 2:
        ila, la_lo, la_hi, la_w = _bands(df["latf"].to_numpy()[core])
        ilo, lo_lo, lo_hi, lo_w = _bands(df["lonf"].to_numpy()[core])
        la_starts = list(range(la_lo, la_hi + 1, la_w))
        lo_starts = list(range(lo_lo, lo_hi + 1, lo_w))
        ya = (ila - la_lo) // la_w
        xa = (ilo - lo_lo) // lo_w
        cells = {}
        for xi, yi in zip(xa.tolist(), ya.tolist()):
            cells[(xi, yi)] = cells.get((xi, yi), 0) + 1
        heat = sorted([[xi, yi, c] for (xi, yi), c in cells.items()])
        best = sorted(cells.items(), key=lambda kv: (-kv[1], kv[0][1], kv[0][0]))[0]
        top_cell = (best[1], _label(la_starts[best[0][1]]), _label(lo_starts[best[0][0]]))
        grid = {"x": [_label(a) for a in lo_starts], "y": [_label(a) for a in la_starts],
                "data": heat, "max": max(c for _, _, c in heat)}
        cell_km = la_w * 0.01 * math.radians(1) * R_KM

    dn, du = dist_km[has_num], dist_km[~has_num]
    rules = [
        ("numbered", insight_numbered(n_num, total)),
        ("heads", insight_heads(per_num)),
        ("junctions", insight_junctions(n_j, n_j_un, n_sing)),
        ("distance", insight_distance(dn, du)),
        ("spacing", insight_spacing(nn)),
        ("footprint", insight_footprint(spans)),
        ("gaps", insight_gaps(used, top_num, unused)),
        ("mixed", insight_mixed(n_mixed, n_un_in_mixed)),
        ("grid", insight_grid(top_cell[0], core_n, top_cell[1], top_cell[2], cell_km)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    num_share = n_num / total
    kpis = {
        "heads": {"value": total, "display": _int(total), "tone": "brand", "label": "רמזורים עם מיקום תקין"},
        "junctions": {"value": n_j, "display": _int(n_j), "tone": "brand",
                      "label": f"צמתים משוערים (רמזורים במרחק עד {_int(LINK_M)} מטרים)"},
        "numbered": {"value": num_share, "display": _pct(num_share, 1),
                     "tone": "ok" if num_share >= 0.9 else "info" if num_share >= 0.6 else "warn",
                     "label": "מהרמזורים עם מספר רמזור"},
        "spacing": {"value": med_sp, "display": _int(round(med_sp)), "tone": "brand",
                    "label": "מרחק חציוני לצומת הקרוב ביותר (מטרים)"},
    }

    n_un = total - n_num
    far_un = int(((dist_km > CORE_KM) & ~has_num).sum())
    far_note = (f" {_pct(far_un / n_un)} מהם מרוחקים יותר מ-{_int(CORE_KM)} ק״מ ממרכז הפריסה."
                if n_un and far_un / n_un >= 0.5 else "")
    bad_note = (f" {_int(n_bad)} רשומות בלי קואורדינטות תקינות לא נכללו בניתוח." if n_bad else "")
    labels = {
        "lede": (f"{_int(total)} רמזורים של עיריית באר שבע, כל אחד עם קו רוחב וקו אורך, ולרובם גם המספר "
                 f"שמודבק על הרמזור בשטח. המספר מזהה צומת: כל הרמזורים של אותו צומת חולקים אותו, ולכן "
                 f"אפשר לקבץ אותם ל-{_int(n_j)} צמתים בקירוב. {_int(total - n_num)} רמזורים נרשמו בלי מספר, "
                 f"{far_note}{bad_note}"),
        "map_note": (f"כל הרמזורים על המפה. לחצו על סמן כדי לראות את מספר הרמזור; "
                     f"לחצו על אשכול כדי להתקרב."),
        "radial_note": (f"הערכים בציר הם הגבול העליון של כל טבעת, בק״מ. מרחק קו אווירי מכל רמזור למרכז הפריסה (חציון קווי הרוחב והאורך), בטבעות של "
                        f"{_int(RING_KM)} ק״מ. הצבע מפריד בין רמזורים עם מספר לרמזורים בלי."),
        "radial_aria": f"תרשים עמודות מוערם: מספר הרמזורים לפי מרחק מהמרכז ולפי קיום מספר, {len(rnames)} טבעות.",
        "radial_caption": "מספר הרמזורים לפי מרחק מהמרכז (ק״מ) ולפי קיום מספר.",
        "sizes_note": (f"כמה רמזורים יש בכל צומת (קבוצה של רמזורים במרחק עד {_int(LINK_M)} מטרים אחד "
                       f"מהשני). הערך הנפוץ הוא {modal[1]} רמזורים בצומת."),
        "sizes_aria": f"תרשים עמודות: מספר הצמתים לפי מספר הרמזורים בכל צומת, {len(snames)} קבוצות.",
        "sizes_caption": "מספר הצמתים לפי מספר הרמזורים בכל צומת.",
        "span_note": (f"הערכים בציר הם הגבול העליון של כל קבוצה, במטרים. המרחק הגדול ביותר בין שני רמזורים באותו צומת, בצמתים עם יותר מרמזור אחד "
                      f"({_int(len(spans))} צמתים), בקבוצות של {_int(SPAN_BIN_M)} מטרים."),
        "span_aria": f"תרשים עמודות: התפלגות רוחב הצומת במטרים, {len(pn)} קבוצות.",
        "span_caption": "מספר הצמתים לפי המרחק בין הרמזורים הרחוקים ביותר בצומת (מטרים).",
        "spacing_note": (f"הערכים בציר הם הגבול העליון של כל קבוצה, במטרים. מרחק קו אווירי ממרכז כל צומת למרכז הצומת הקרוב אליו, בקבוצות של "
                         f"{_int(SP_BIN_M)} מטרים."),
        "spacing_aria": f"תרשים עמודות: התפלגות המרחק בין צמתים סמוכים, {len(sp_names)} קבוצות.",
        "spacing_caption": "מספר הצמתים לפי המרחק לצומת הקרוב ביותר (מטרים).",
        "numbers_note": (f"מספרי הרמזורים בשימוש מול מספרים בטווח שאין להם אף רמזור במאגר. "
                         f"{_int(used)} מספרים שונים מתוך טווח של עד {_int(top_num)}."),
        "numbers_aria": f"תרשים עמודות מוערם: מספרים בשימוש ומספרים חסרים לפי טווחי מספור, {len(nb_chart['names'])} טווחים.",
        "numbers_caption": "מספרים בשימוש ומספרים חסרים בכל טווח מספור.",
        "grid_note": (f"צפיפות הרמזורים בתאי רשת בליבת העיר ({_int(core_n)} רמזורים בטווח "
                      f"{_int(CORE_KM)} ק״מ ממרכז הפריסה), לפי קו רוחב (למעלה צפון) וקו אורך (שמאל מערב). "
                      f"התא מכסה כ-{cell_km:.1f} ק״מ בצד."),
        "grid_aria": "מפת חום: מספר הרמזורים בתאי רשת של קו רוחב וקו אורך בליבת העיר.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} רמזורים בבאר שבע, בקירוב {_int(n_j)} צמתים; "
                           f"{_pct(num_share, 1)} מהרמזורים ממוספרים והמספר מזהה צומת. "
                           f"מפה, צפיפות בליבת העיר, מרחקים בין צמתים ופערי מספור."),
            "dataset_kind": "map",
            "suggested_tags": ["רמזורים", "תחבורה", "באר שבע", "צמתים", "מפה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["7edbd028-9704-440c-a1b6-a0ed566081bc",
                            "bdf28cc0-680a-415c-af64-944a58079b2f",
                            "209fad5c-de35-49c4-a6f4-164a0c79632c",
                            "001c72e3-cead-42ac-ac5c-17287aabf285",
                            "82a30a97-01b0-4281-854c-c7931f3445c0"],
        },
        "kpis": kpis,
        "charts": {"radial": radial, "sizes": sizes, "span": span_chart, "spacing": spacing,
                   "numbers": nb_chart, "grid": grid},
        "tables": {"radial": t_radial, "sizes": t_sizes, "span": t_span, "spacing": t_spacing,
                   "numbers": t_nb},
        "insights": insights,
        "has_span": bool(len(spans)),
        "has_spacing": bool(len(nn)),
        "has_numbers": bool(used),
        "has_grid": bool(grid["data"]),
        "labels": labels,
    }
