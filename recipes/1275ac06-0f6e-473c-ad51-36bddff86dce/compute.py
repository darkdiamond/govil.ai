"""מבני חינוך בבאר שבע — one row per educational building: institution name,
type (kindergarten / school / secondary / other), a free-text address, an
optional former name and a WGS84 point.

Everything on the page is derived from those columns: the mix of types, how
the buildings are spread over the city (a grid, distance rings from the
median point, latitude bands), how far each kindergarten is from the nearest
school, how many names repeat, and how complete the address / former-name
fields are.  Order-independent: counts, medians and sorted aggregates only.
Institution names are public facilities, not personal data.
"""
import math

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
R_KM = 6371.0088
TOP_TYPES = 6
GAN, SCHOOL, OTHER = "גנים", "בתי ספר", "אחר"
GROUPS = [GAN, SCHOOL, OTHER]
MAX_BANDS = 12              # grid / latitude bands (widened as the city grows)
RING_M = 500                # distance ring width
RING_COUNT = 8              # last ring is open-ended
NEAR_BIN_M = 100
NEAR_BINS = 8               # last bin open-ended
NEAR_SHARE_M = 300
TOP_NAMES = 10
LEAD_SHARE = 0.5
ISOLATED_RATIO = 3
RENAMED_MIN = 0.05
ADDRESS_GAP_MIN = 0.10
DENSE_MIN_SHARE = 0.06
RING_GAP_RATIO = 1.25


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _group(t):
    if "גן" in t:
        return GAN
    if "בית ספר" in t or "יסוד" in t:
        return SCHOOL
    return OTHER


def _prepare(df):
    out = df.copy()
    out["name"] = out["Institutio"].str.strip()
    out["type"] = out["type"].str.strip()
    out["addr"] = out["ADDRESS"].str.strip()
    out["old"] = out["oldName"].str.strip()
    out["latf"] = pd.to_numeric(out["lat"].str.strip(), errors="coerce")
    out["lonf"] = pd.to_numeric(out["lon"].str.strip(), errors="coerce")
    ok = (out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
          & (out["name"] != ""))
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    out["type"] = out["type"].where(out["type"] != "", "לא צוין")
    out["group"] = out["type"].map(_group)
    out = out.sort_values(["type", "name", "latf", "lonf", "addr", "old"], kind="stable")
    return out.reset_index(drop=True), n_bad


def _xy_km(lat, lon, lat0):
    k = math.cos(math.radians(lat0))
    return np.radians(lon) * R_KM * k, np.radians(lat) * R_KM


def _nearest_m(x1, y1, x2, y2, same=False):
    """Distance in metres from each point of set 1 to its nearest point of set 2."""
    n = len(x1)
    out = np.full(n, np.inf)
    if len(x2) == 0 or (same and n < 2):
        return out
    for s in range(0, n, 400):
        e = min(n, s + 400)
        d = np.hypot(x1[s:e, None] - x2[None, :], y1[s:e, None] - y2[None, :])
        if same:
            d[np.arange(e - s), np.arange(s, e)] = np.inf
        out[s:e] = d.min(axis=1)
    return out * 1000


def _band_index(values):
    """Integer 0.01-degree index per value, widened so there are <= MAX_BANDS."""
    idx = np.floor(np.asarray(values) * 100 + 1e-9).astype(int)
    lo, hi = int(idx.min()), int(idx.max())
    w = max(1, math.ceil((hi - lo + 1) / MAX_BANDS))
    lo = (lo // w) * w
    return idx, lo, hi, w


def _band_label(a, w):
    return f"{a / 100:.2f}-{(a + w) / 100:.2f}"


def insight_leader(types, total):
    if len(types) < 2:
        return None
    a, b = types.iloc[0], types.iloc[1]
    if a / total < LEAD_SHARE:
        return None
    return (f"הסוג הנפוץ ביותר הוא {types.index[0]}: {_int(a)} מבנים "
            f"({_pct(a / total, 1)} מהמאגר), לעומת {_int(b)} בסוג {types.index[1]}.")


def insight_ratio(n_gan, n_school):
    if n_gan == 0 or n_school == 0:
        return None
    return (f"על כל בית ספר או מוסד על-יסודי יש בממוצע {n_gan / n_school:.1f} גני ילדים "
            f"({_int(n_gan)} גנים מול {_int(n_school)} בתי ספר ומוסדות על-יסודיים).")


def insight_center(med_by_group):
    g, s = med_by_group.get(GAN), med_by_group.get(SCHOOL)
    if g is None or s is None or min(g, s) <= 0:
        return None
    if max(g, s) < RING_GAP_RATIO * min(g, s):
        return None
    if g > s:
        return (f"בתי הספר קרובים יותר למרכז העיר: מרחק חציוני של {_int(s)} מטרים ממרכז הכובד "
                f"של המבנים, לעומת {_int(g)} מטרים בגני הילדים.")
    return (f"גני הילדים קרובים יותר למרכז העיר: מרחק חציוני של {_int(g)} מטרים ממרכז הכובד "
            f"של המבנים, לעומת {_int(s)} מטרים בבתי הספר.")


def insight_nearest(nn_gan):
    f = nn_gan[np.isfinite(nn_gan)]
    if len(f) == 0:
        return None
    return (f"מרחק חציוני של {_int(round(float(np.median(f))))} מטרים מגן ילדים לבית הספר "
            f"הקרוב אליו; ל-{_pct(float((f <= NEAR_SHARE_M).mean()))} מהגנים יש בית ספר "
            f"ברדיוס של {_int(NEAR_SHARE_M)} מטרים.")


def insight_isolated(gans, nn_gan):
    f = np.isfinite(nn_gan)
    if not f.any():
        return None
    med = float(np.median(nn_gan[f]))
    i = int(np.argmax(np.where(f, nn_gan, -1)))
    if med <= 0 or nn_gan[i] < ISOLATED_RATIO * med:
        return None
    return (f"הגן הרחוק ביותר מבית ספר הוא {gans['name'].iloc[i]}: בית הספר הקרוב אליו נמצא "
            f"במרחק של {_int(round(float(nn_gan[i])))} מטרים, פי {nn_gan[i] / med:.1f} מהחציון.")


def insight_names(df):
    by = df.groupby("name")["group"].agg(lambda s: set(s))
    both = sorted(n for n, g in by.items() if GAN in g and SCHOOL in g)
    if len(both) < 3:
        return None
    return (f"{_int(len(both))} שמות משותפים גם לגן ילדים וגם לבית ספר, כנראה מוסדות באותו "
            f"קמפוס או באותה שכונה; למשל {both[0]} ו-{both[1]}.")


def insight_renamed(df):
    n = int((df["old"] != "").sum())
    share = n / len(df)
    if share < RENAMED_MIN:
        return None
    g = int(((df["old"] != "") & (df["group"] == GAN)).sum())
    return (f"ל-{_int(n)} מבנים ({_pct(share, 1)}) רשום שם קודם; "
            f"{_int(g)} מהם גני ילדים.")


def insight_address(df):
    n = int((df["addr"] == "").sum())
    share = n / len(df)
    if share < ADDRESS_GAP_MIN:
        return None
    return (f"ב-{_int(n)} מבנים ({_pct(share, 1)}) שדה הכתובת ריק; "
            f"המיקום המדויק נשען על הקואורדינטות.")


def insight_dense(cell_best, total):
    if cell_best is None or cell_best[0] / total < DENSE_MIN_SHARE:
        return None
    c, lab_lat, lab_lon = cell_best
    return (f"הריבוע הצפוף ביותר במפה (קו רוחב {lab_lat}, קו אורך {lab_lon}) מכיל "
            f"{_int(c)} מבנים — {_pct(c / total, 1)} מהמאגר.")


def insight_extent(ns_km, ew_km):
    return f"המבנים פרוסים על פני {ns_km:.1f} ק״מ מצפון לדרום ו-{ew_km:.1f} ק״מ ממערב למזרח."


def compute(frames):
    df, n_bad = _prepare(frames["buildings"])
    total = len(df)
    lat0 = (float(df["latf"].min()) + float(df["latf"].max())) / 2
    x, y = _xy_km(df["latf"].to_numpy(), df["lonf"].to_numpy(), lat0)
    grp = df["group"].to_numpy()

    # ---- type mix
    vc = df["type"].value_counts()
    types = vc.sort_index().sort_values(ascending=False, kind="stable")
    top = types.head(TOP_TYPES)
    rest = int(types.iloc[TOP_TYPES:].sum())
    tnames = list(top.index) + (["אחר"] if rest else [])
    tvals = [int(v) for v in top] + ([rest] if rest else [])
    t_type = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)}
              for n, v in zip(tnames, tvals)]
    n_gan = int((grp == GAN).sum())
    n_school = int((grp == SCHOOL).sum())

    # ---- distance rings from the median point
    cx, cy = float(np.median(x)), float(np.median(y))
    dist_c = np.hypot(x - cx, y - cy) * 1000
    ring = np.minimum((dist_c // RING_M).astype(int), RING_COUNT - 1)
    ring_max = int(ring.max())
    rn = ring_max + 1
    rnames = [f"{i * RING_M}-{(i + 1) * RING_M}" for i in range(rn - 1)]
    rnames.append(f"מעל {(rn - 1) * RING_M}" if rn == RING_COUNT else f"{(rn - 1) * RING_M}-{rn * RING_M}")
    rings = {g: [int(((ring == i) & (grp == g)).sum()) for i in range(rn)] for g in GROUPS}
    ring_groups = [g for g in GROUPS if sum(rings[g])]
    t_rings = [{"name": rnames[i], "cells": [_int(rings[g][i]) for g in ring_groups],
                "total": _int(sum(rings[g][i] for g in ring_groups))} for i in range(rn)]
    med_by_group = {}
    for g in GROUPS:
        m = grp == g
        if m.any():
            med_by_group[g] = int(round(float(np.median(dist_c[m]))))
    med_all = int(round(float(np.median(dist_c))))

    # ---- nearest school for each kindergarten
    gm, sm = grp == GAN, grp == SCHOOL
    gans = df[gm].reset_index(drop=True)
    nn_gan = _nearest_m(x[gm], y[gm], x[sm], y[sm])
    fin = nn_gan[np.isfinite(nn_gan)]
    if len(fin):
        b = np.minimum((fin // NEAR_BIN_M).astype(int), NEAR_BINS - 1)
        counts = [int((b == i).sum()) for i in range(NEAR_BINS)]
        nmax = max(i for i, c in enumerate(counts) if c) + 1
        counts = counts[:nmax]
        nnames = [f"{i * NEAR_BIN_M}-{(i + 1) * NEAR_BIN_M}" for i in range(nmax)]
        if nmax == NEAR_BINS:
            nnames[-1] = f"מעל {(NEAR_BINS - 1) * NEAR_BIN_M}"
    else:
        counts, nnames = [], []
    t_near = [{"name": n, "count": _int(v), "share": _pct(v / len(fin), 1)}
              for n, v in zip(nnames, counts)] if len(fin) else []
    med_near = int(round(float(np.median(fin)))) if len(fin) else 0

    # ---- heat grid (0.01-degree cells) + latitude bands by group
    lat_i, lat_lo, lat_hi, lat_w = _band_index(df["latf"].to_numpy())
    lon_i, lon_lo, lon_hi, lon_w = _band_index(df["lonf"].to_numpy())
    lat_starts = list(range(lat_lo, lat_hi + 1, lat_w))[::-1]     # north first
    lon_starts = list(range(lon_lo, lon_hi + 1, lon_w))
    lat_cell = (lat_i - lat_lo) // lat_w
    lon_cell = (lon_i - lon_lo) // lon_w
    n_lat, n_lon = len(lat_starts), len(lon_starts)
    cells, best = [], None
    for ly in range(n_lat):                 # ly: 0 = southernmost
        for lx in range(n_lon):
            c = int(((lat_cell == ly) & (lon_cell == lx)).sum())
            if c:
                row = n_lat - 1 - ly         # north first on the y axis
                cells.append([lx, row, c])
                lab = (c, -ly, -lx)
                if best is None or lab > best[0]:
                    best = (lab, c, _band_label(lat_lo + ly * lat_w, lat_w),
                            _band_label(lon_lo + lx * lon_w, lon_w))
    heat = {"x": [_band_label(a, lon_w) for a in lon_starts],
            "y": [_band_label(a, lat_w) for a in lat_starts],
            "cells": cells, "max": max(c[2] for c in cells)}
    cell_best = (best[1], best[2], best[3]) if best else None
    bands = {g: [int(((lat_cell == (n_lat - 1 - i)) & (grp == g)).sum()) for i in range(n_lat)]
             for g in GROUPS}
    band_groups = [g for g in GROUPS if sum(bands[g])]
    t_bands = [{"name": heat["y"][i], "cells": [_int(bands[g][i]) for g in band_groups],
                "total": _int(sum(bands[g][i] for g in band_groups))} for i in range(n_lat)]

    # ---- repeated names
    nc = df["name"].value_counts()
    nc = nc[nc >= 2]
    nc = nc.sort_index().sort_values(ascending=False, kind="stable").head(TOP_NAMES)
    names_chart = {"names": list(nc.index), "values": [int(v) for v in nc]}
    t_names = [{"name": n, "count": _int(v)} for n, v in zip(nc.index, nc)]
    n_repeat = int((df["name"].value_counts() >= 2).sum())

    # ---- field completeness by group
    fields_groups = [g for g in GROUPS if (grp == g).any()]
    addr_share, old_share = [], []
    for g in fields_groups:
        m = (df["group"] == g)
        addr_share.append(round(float((df.loc[m, "addr"] != "").mean()) * 100, 1))
        old_share.append(round(float((df.loc[m, "old"] != "").mean()) * 100, 1))
    fields = {"groups": fields_groups, "addr": addr_share, "old": old_share}
    t_fields = [{"name": g, "count": _int((df["group"] == g).sum()),
                 "addr": f"{a:.1f}%", "old": f"{o:.1f}%"}
                for g, a, o in zip(fields_groups, addr_share, old_share)]

    ns_km = float((y.max() - y.min()))
    ew_km = float(x.max() - x.min())
    n_old = int((df["old"] != "").sum())

    rules = [
        ("leader", insight_leader(types, total)),
        ("ratio", insight_ratio(n_gan, n_school)),
        ("center", insight_center(med_by_group)),
        ("nearest", insight_nearest(nn_gan)),
        ("isolated", insight_isolated(gans, nn_gan)),
        ("names", insight_names(df)),
        ("renamed", insight_renamed(df)),
        ("address", insight_address(df)),
        ("dense", insight_dense(cell_best, total)),
        ("extent", insight_extent(ns_km, ew_km) if total > 1 else None),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    near_tone = "brand"
    if len(fin):
        near_tone = "ok" if med_near <= NEAR_SHARE_M else "warn"
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand",
                  "label": "מבני חינוך במאגר"},
        "gardens": {"value": n_gan, "display": _int(n_gan), "tone": "brand",
                    "label": "גני ילדים"},
        "schools": {"value": n_school, "display": _int(n_school), "tone": "brand",
                    "label": "בתי ספר ומוסדות על-יסודיים"},
        "renamed": {"value": n_old, "display": _int(n_old), "tone": "info",
                    "label": "מבנים עם שם קודם"},
    }
    kpis_order = ["total", "gardens", "schools", "renamed"]
    if len(fin):
        kpis["nearest"] = {"value": med_near, "display": _int(med_near), "tone": near_tone,
                           "label": "מרחק חציוני מגן ילדים לבית הספר הקרוב (מטרים)"}
        kpis_order = ["total", "gardens", "schools", "nearest"]

    bad_note = (f" {_int(n_bad)} רשומות בלי שם או בלי קואורדינטות תקינות לא נכללו."
                if n_bad else "")
    labels = {
        "lede": (f"{_int(total)} מבנים המשמשים לחינוך הפורמלי בבאר שבע: "
                 f"{_int(n_gan)} גני ילדים, {_int(n_school)} בתי ספר ומוסדות על-יסודיים "
                 f"ו-{_int(total - n_gan - n_school)} מבנים מסוגים אחרים, כל אחד עם שם, סוג ונקודת "
                 f"מיקום. המאגר מפורסם בכמה קבצים (CSV ו-Excel, קואורדינטות גאוגרפיות או ITM) "
                 f"שמכילים את אותן הרשומות.{bad_note}"),
        "map_note": (f"{_int(total)} המבנים על המפה. לחצו על סמן כדי לראות את שם המוסד; "
                     f"לחצו על אשכול כדי להתקרב."),
        "type_note": "מספר המבנים בכל סוג מוסד כפי שהוא רשום במאגר.",
        "type_aria": f"תרשים עמודות אופקי: מספר המבנים לפי סוג, {len(tnames)} סוגים.",
        "type_caption": "מספר המבנים לפי סוג מוסד.",
        "heat_note": ("מפת חום של צפיפות המבנים: כל ריבוע הוא רצועת קו רוחב וקו אורך "
                      "(בערך קילומטר על קילומטר); ככל שהצבע כהה יותר יש בו יותר מבנים. "
                      "צפון למעלה, מערב משמאל."),
        "heat_aria": (f"מפת חום: מספר מבנים לפי {_int(n_lat)} רצועות קו רוחב ו-{_int(n_lon)} "
                      f"רצועות קו אורך."),
        "rings_note": (f"מספר המבנים לפי המרחק ממרכז הכובד של כל המבנים (חציון הקואורדינטות), "
                       f"בטבעות של {_int(RING_M)} מטרים, בפילוח לגנים, בתי ספר וסוגים אחרים. "
                       f"המרחק החציוני הכולל הוא {_int(med_all)} מטרים."),
        "rings_aria": f"תרשים עמודות מוערם: מבנים לפי מרחק ממרכז, {len(rnames)} טבעות.",
        "rings_caption": "מספר המבנים לפי מרחק ממרכז (מטרים), לפי קבוצה.",
        "near_note": (f"מרחק קו אווירי מכל גן ילדים לבית הספר או המוסד העל-יסודי הקרוב אליו, "
                      f"בקבוצות של {_int(NEAR_BIN_M)} מטרים."),
        "near_aria": f"תרשים עמודות: התפלגות המרחק מגן לבית ספר, {len(nnames)} קבוצות.",
        "near_caption": "מספר גני הילדים לפי המרחק לבית הספר הקרוב (מטרים).",
        "bands_note": "מספר המבנים בכל רצועת קו רוחב, מהצפון (למעלה) לדרום, לפי סוג.",
        "bands_aria": f"תרשים עמודות אופקי מוערם: מבנים לפי {_int(n_lat)} רצועות קו רוחב.",
        "bands_caption": "מספר המבנים לפי רצועת קו רוחב, לפי קבוצה.",
        "names_note": (f"שמות מוסדות שמופיעים יותר מפעם אחת במאגר — לרוב גן ובית ספר באותו קמפוס, "
                       f"או שני גנים עם אותו שם. סך הכול {_int(n_repeat)} שמות חוזרים."),
        "names_aria": f"תרשים עמודות אופקי: השמות החוזרים הנפוצים ביותר, {len(nc)} שמות.",
        "names_caption": "מספר המבנים לכל שם חוזר.",
        "fields_note": ("שיעור המבנים שבהם מולאו שדה הכתובת ושדה השם הקודם, לפי קבוצה. "
                        "הכתובת היא טקסט חופשי ולא אחיד."),
        "fields_aria": f"תרשים עמודות מקובצות: שיעור כתובת ושם קודם ב-{len(fields_groups)} קבוצות.",
        "fields_caption": "אחוז המבנים עם כתובת ועם שם קודם, לפי קבוצה.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} מבני חינוך בבאר שבע — {_int(n_gan)} גני ילדים ו-"
                           f"{_int(n_school)} בתי ספר ומוסדות על-יסודיים — עם מפה, פיזור גאוגרפי "
                           f"ומרחק חציוני של {_int(med_near)} מטרים מגן לבית הספר הקרוב."
                           if len(fin) else
                           f"{_int(total)} מבני חינוך בבאר שבע עם מפה ופיזור גאוגרפי."),
            "dataset_kind": "map",
            "suggested_tags": ["חינוך", "באר שבע", "גני ילדים", "בתי ספר", "מפה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe",
                            "3c6d4061-41bf-4403-82e9-c8fae5df04dd",
                            "d25f8679-13bc-4082-bf6e-6156e1d2df60",
                            "566c2420-1b00-4813-8a75-c6d8750c5ec8",
                            "b795e2e0-491e-4040-877e-f3681917f8be"],
        },
        "kpis": kpis,
        "kpis_order": kpis_order,
        "charts": {
            "type": {"names": tnames, "values": tvals},
            "heat": heat,
            "rings": {"names": rnames, "groups": ring_groups,
                      "series": [rings[g] for g in ring_groups]},
            "near": {"names": nnames, "values": counts},
            "bands": {"names": heat["y"], "groups": band_groups,
                      "series": [bands[g] for g in band_groups]},
            "names": names_chart,
            "fields": fields,
        },
        "tables": {"type": t_type, "rings": t_rings, "near": t_near, "bands": t_bands,
                   "names": t_names, "fields": t_fields},
        "table_heads": {"rings": ring_groups, "bands": band_groups},
        "insights": insights,
        "has_near": bool(len(fin)),
        "has_names": bool(len(nc)),
        "labels": labels,
    }
