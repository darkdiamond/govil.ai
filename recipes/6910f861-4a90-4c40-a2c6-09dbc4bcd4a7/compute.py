"""Public EV charging stations (Ministry of Transport GIS layer).

Two inputs: `main` is the live datastore attribute table (one row per
charging site: operator, name, address, number of charging points split
fast/slow); `geo` is the committed snapshot of the same layer's shapefile
(one point per site). Every count comes from `main`; `geo` only gives each
site its location, joined on OBJECTID. Sites without a location are counted
everywhere except the map and the regional/distance views, and the page says
how many.

Every number on the page is computed here. Insight rules return a sentence
or None when their premise does not hold.
"""
import json
import math

import numpy as np
import pandas as pd

TOP_OPS = 10          # operator bar charts: top N + "אחר"
HEAT_OPS = 8          # operator x region heatmap rows
HUBS_N = 10           # largest sites list
FAST_SHARE_MIN_POINTS = 50   # operators shown in the fast-share chart
MAP_CHUNK_BYTES = 38000      # per <script type="application/json"> island

# Latitude bands, south to north. A fixed geographic convention (not data):
# each band is named after the main areas it crosses.
REGIONS = [
    (None, 30.6, "אילת והערבה"),
    (30.6, 31.4, "הנגב"),
    (31.4, 31.9, "ירושלים, השפלה ואשדוד-אשקלון"),
    (31.9, 32.45, "גוש דן, השרון והמרכז"),
    (32.45, 32.9, "חיפה, העמקים והכרמל"),
    (32.9, None, "הגליל העליון והגולן"),
]

SIZE_BINS = [(1, 1, "נקודה אחת"), (2, 2, "2 נקודות"), (3, 4, "3-4 נקודות"),
             (5, 8, "5-8 נקודות"), (9, 16, "9-16 נקודות"), (17, None, "17 נקודות ומעלה")]

DIST_BINS = [(0, 1, "עד 1 ק\"מ"), (1, 2, "1-2 ק\"מ"), (2, 5, "2-5 ק\"מ"),
             (5, 10, "5-10 ק\"מ"), (10, 20, "10-20 ק\"מ"), (20, None, "מעל 20 ק\"מ")]

SITE_TYPES = [("slow", "טעינה רגילה בלבד"), ("mixed", "רגילה ומהירה"), ("fast", "מהירה בלבד")]


def _i(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _clean(s):
    return " ".join(str(s).replace(" ", " ").split())


# ── preparation ──────────────────────────────────────────────────────────


def _prepare(main, geo):
    df = pd.DataFrame({
        "oid": pd.to_numeric(main["OBJECTID"], errors="coerce"),
        "op": main["op"].map(_clean),
        "name": main["name"].map(_clean),
        "addr": main["Address"].map(_clean),
        "fast": pd.to_numeric(main["cnt_fast"], errors="coerce"),
        "slow": pd.to_numeric(main["cnt_slow"], errors="coerce"),
        "count": pd.to_numeric(main["count"], errors="coerce"),
    })
    df["fast"] = df["fast"].fillna(0).clip(lower=0)
    df["slow"] = df["slow"].fillna(0).clip(lower=0)
    # `count` is the published total; fall back to fast+slow when missing.
    df["pts"] = df["count"].where(df["count"].notna(), df["fast"] + df["slow"])
    df = df[df["pts"] > 0].copy()
    df.loc[df["op"].isin(["", "undefined", "Undefined"]), "op"] = "לא צוין"
    for c in ["fast", "slow", "pts"]:
        df[c] = df[c].astype(int)
    bad = df["addr"].str.lower().isin(["", "undefined", "undefined undefined"])
    df.loc[bad, "addr"] = ""

    locs = {}
    for oid, g in zip(geo["OBJECTID"], geo["__geometry"]):
        o = pd.to_numeric(oid, errors="coerce")
        if pd.isna(o):
            continue
        try:
            gj = json.loads(g)
        except (TypeError, ValueError):
            continue
        if not isinstance(gj, dict) or gj.get("type") != "Point":
            continue
        c = gj.get("coordinates") or []
        if len(c) < 2:
            continue
        lng, lat = float(c[0]), float(c[1])
        if not (29.0 < lat < 33.6 and 34.0 < lng < 36.0):
            continue
        key = int(o)
        if key not in locs or (lat, lng) < locs[key]:
            locs[key] = (lat, lng)
    df["lat"] = df["oid"].map(lambda o: locs.get(int(o), (np.nan, np.nan))[0] if pd.notna(o) else np.nan)
    df["lng"] = df["oid"].map(lambda o: locs.get(int(o), (np.nan, np.nan))[1] if pd.notna(o) else np.nan)
    df["type"] = np.where(df["fast"] == 0, "slow", np.where(df["slow"] == 0, "fast", "mixed"))
    df = df.sort_values(["oid", "op", "name", "addr", "pts"], kind="mergesort").reset_index(drop=True)
    return df


def _region(lat):
    for lo, hi, name in REGIONS:
        if (lo is None or lat >= lo) and (hi is None or lat < hi):
            return name
    return REGIONS[-1][2]


def _haversine_min(lat1, lng1, lat2, lng2):
    """Distance (km) from each point in set 1 to its nearest point in set 2."""
    r = 6371.0
    p1, p2 = np.radians(lat1)[:, None], np.radians(lat2)[None, :]
    dphi = p2 - p1
    dl = np.radians(lng2)[None, :] - np.radians(lng1)[:, None]
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    d = 2 * r * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return d.min(axis=1)


# ── insight rules ────────────────────────────────────────────────────────


def insight_concentration(ops, total_pts):
    if len(ops) < 4 or total_pts == 0:
        return None
    top = ops.iloc[0]
    top3 = ops["pts"].iloc[:3].sum() / total_pts
    if top3 < 0.4:
        return None
    names = ", ".join(ops.index[:3])
    return (f"השוק מרוכז: שלוש המפעילות הגדולות ({names}) מחזיקות {_pct(top3)} מנקודות הטעינה. "
            f"{ops.index[0]} לבדה מפעילה {_i(top['pts'])} נקודות ב-{_i(top['sites'])} אתרים "
            f"({_pct(top['pts'] / total_pts)}).")


def insight_fast_gap(ops):
    big = ops[ops["pts"] >= 100]
    if len(big) < 3:
        return None
    s = pd.DataFrame({"op": big.index, "fs": (big["fast"] / big["pts"]).to_numpy()})
    s = s.sort_values(["fs", "op"], kind="mergesort")
    lo_name, lo = s.iloc[0]["op"], s.iloc[0]["fs"]
    hi_name, hi = s.iloc[-1]["op"], s.iloc[-1]["fs"]
    if hi - lo < 0.10:
        return None
    return (f"שיעור הטעינה המהירה שונה מאוד בין המפעילות: אצל {hi_name} {_pct(hi)} מהנקודות מהירות, "
            f"ואצל {lo_name} רק {_pct(lo)} (מפעילות עם 100 נקודות לפחות).")


def insight_region(reg, located_pts):
    if reg.empty or located_pts == 0:
        return None
    lead = reg.sort_values(["pts", "name"], ascending=[False, True], kind="mergesort").iloc[0]
    share = lead["pts"] / located_pts
    if share < 0.25:
        return None
    small = reg[reg["sites"] >= 20]
    tail = ""
    if len(small) >= 2:
        fs = small.assign(fs=small["fast"] / small["pts"]).sort_values(["fs", "name"], kind="mergesort")
        lo, hi = fs.iloc[0], fs.iloc[-1]
        if hi["fs"] - lo["fs"] >= 0.08:
            tail = (f" שיעור הנקודות המהירות הגבוה ביותר נמצא באזור {hi['name']} ({_pct(hi['fs'])}), "
                    f"והנמוך ביותר באזור {lo['name']} ({_pct(lo['fs'])}).")
    return (f"באזור {lead['name']} מרוכזות {_i(lead['pts'])} נקודות טעינה, "
            f"{_pct(share)} מהנקודות שמיקומן ידוע.{tail}")


def insight_nearest_fast(dist_df):
    if len(dist_df) < 10:
        return None
    near = (dist_df["d"] <= 5).mean()
    far = dist_df.sort_values(["d", "name"], ascending=[False, True], kind="mergesort").iloc[0]
    s = (f"ל-{_pct(near)} מהאתרים שיש בהם טעינה רגילה בלבד יש אתר עם טעינה מהירה במרחק של עד 5 ק\"מ "
         f"בקו אווירי.")
    if far["d"] >= 15:
        s += (f" האתר המרוחק ביותר מטעינה מהירה הוא {far['name']} ({far['op']}), "
              f"כ-{far['d']:.0f} ק\"מ מהאתר המהיר הקרוב.")
    return s


def insight_hub(df):
    if len(df) < 5:
        return None
    med = df["pts"].median()
    top = df.sort_values(["pts", "oid"], ascending=[False, True], kind="mergesort").iloc[0]
    if top["pts"] < 3 * max(med, 1):
        return None
    fast = f", מהן {_i(top['fast'])} מהירות" if top["fast"] > 0 else ", כולן לטעינה רגילה"
    return (f"האתר הגדול ביותר הוא {top['name']} ({top['op']}) עם {_i(top['pts'])} נקודות טעינה{fast}. "
            f"באתר טיפוסי (חציון) יש {_i(med)} נקודות.")


def insight_small_sites(df):
    if len(df) < 5:
        return None
    small = (df["pts"] <= 2).mean()
    if small < 0.4:
        return None
    return f"רוב הרשת מבוזרת: ב-{_pct(small)} מהאתרים יש לכל היותר שתי נקודות טעינה."


def insight_fast_only(df):
    fo = df[df["type"] == "fast"]
    if len(fo) < 10:
        return None
    by = fo.groupby("op").size().reset_index(name="n").sort_values(["n", "op"], ascending=[False, True], kind="mergesort")
    lead = by.iloc[0]
    if lead["n"] / len(fo) < 0.25:
        return f"{_i(len(fo))} אתרים מציעים טעינה מהירה בלבד, ללא נקודות רגילות."
    return (f"{_i(len(fo))} אתרים מציעים טעינה מהירה בלבד, ללא נקודות רגילות; "
            f"{lead['op']} מפעילה {_i(lead['n'])} מהם.")


def insight_long_tail(ops, total_pts):
    small = ops[ops["sites"] < 20]
    if len(small) < 3 or total_pts == 0:
        return None
    return (f"{_i(len(small))} מפעילות קטנות (פחות מ-20 אתרים כל אחת) מחזיקות יחד "
            f"{_pct(small['pts'].sum() / total_pts)} מנקודות הטעינה.")


# ── main ─────────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["main"], frames["geo"])
    n_sites = len(df)
    total_pts = int(df["pts"].sum())
    total_fast = int(df["fast"].sum())
    total_slow = int(df["slow"].sum())
    fast_share = total_fast / total_pts if total_pts else 0.0

    ops = (df.groupby("op").agg(sites=("pts", "size"), pts=("pts", "sum"), fast=("fast", "sum"),
                                slow=("slow", "sum"))
           .reset_index().sort_values(["pts", "sites", "op"], ascending=[False, False, True], kind="mergesort")
           .set_index("op"))
    n_ops = len(ops)
    top3_share = ops["pts"].iloc[:3].sum() / total_pts if total_pts else 0.0

    loc = df.dropna(subset=["lat", "lng"]).copy()
    n_unlocated = n_sites - len(loc)
    loc["region"] = loc["lat"].map(_region)
    located_pts = int(loc["pts"].sum())

    labels, charts, tables, flags, kpis = {}, {}, {}, {}, {}

    # ── operators (top N + אחר) ──
    head = ops.iloc[:TOP_OPS]
    rest = ops.iloc[TOP_OPS:]
    op_names = list(head.index)
    op_sites = [int(v) for v in head["sites"]]
    op_pts = [int(v) for v in head["pts"]]
    op_fast = [int(v) for v in head["fast"]]
    op_slow = [int(v) for v in head["slow"]]
    if len(rest):
        op_names.append(f"אחר ({len(rest)} מפעילות)")
        op_sites.append(int(rest["sites"].sum()))
        op_pts.append(int(rest["pts"].sum()))
        op_fast.append(int(rest["fast"].sum()))
        op_slow.append(int(rest["slow"].sum()))
    charts["ops"] = {"names": op_names, "sites": op_sites, "pts": op_pts, "fast": op_fast, "slow": op_slow}
    tables["ops"] = [{"name": n, "sites": _i(s), "pts": _i(p), "share": _pct(p / total_pts),
                      "fast": _i(f)} for n, s, p, f in zip(op_names, op_sites, op_pts, op_fast)]
    lead_op = ops.index[0]
    labels["ops_lede"] = (f"{_i(n_ops)} חברות מפעילות. {lead_op} מובילה עם {_i(ops.iloc[0]['pts'])} נקודות "
                          f"ב-{_i(ops.iloc[0]['sites'])} אתרים; שלוש הגדולות מחזיקות {_pct(top3_share)} מהנקודות.")
    labels["ops_aria"] = (f"גרף עמודות אופקי: נקודות טעינה לפי מפעילה, רגילות ומהירות. "
                          f"{lead_op} מובילה עם {_i(ops.iloc[0]['pts'])} נקודות.")

    # ── fast share per operator ──
    fs = ops[ops["pts"] >= FAST_SHARE_MIN_POINTS].copy()
    fs["share"] = fs["fast"] / fs["pts"]
    fs = fs.reset_index().sort_values(["share", "op"], ascending=[False, True], kind="mergesort")
    flags["fastshare"] = len(fs) >= 3
    if flags["fastshare"]:
        charts["fastshare"] = {"names": list(fs["op"]), "share": [round(float(v) * 100, 1) for v in fs["share"]],
                               "fast": [int(v) for v in fs["fast"]], "pts": [int(v) for v in fs["pts"]],
                               "avg": round(fast_share * 100, 1)}
        tables["fastshare"] = [{"name": r.op, "share": _pct(r.share), "fast": _i(r.fast), "pts": _i(r.pts)}
                               for r in fs.itertuples()]
        labels["fastshare_lede"] = (f"בממוצע {_pct(fast_share)} מנקודות הטעינה מהירות. "
                                    f"הגבוהה ביותר: {fs.iloc[0]['op']} ({_pct(fs.iloc[0]['share'])}); "
                                    f"הנמוכה ביותר: {fs.iloc[-1]['op']} ({_pct(fs.iloc[-1]['share'])}).")
        labels["fastshare_aria"] = (f"גרף עמודות: שיעור הנקודות המהירות לפי מפעילה. "
                                    f"{fs.iloc[0]['op']} בראש עם {_pct(fs.iloc[0]['share'])}.")
        labels["fastshare_title"] = f"שיעור הטעינה המהירה לפי מפעילה (מפעילות עם {FAST_SHARE_MIN_POINTS} נקודות לפחות)"

    # ── regions ──
    reg_rows = []
    for _, _, name in REGIONS:
        g = loc[loc["region"] == name]
        if g.empty:
            continue
        types = g["type"].value_counts()
        reg_rows.append({"name": name, "sites": len(g), "pts": int(g["pts"].sum()), "fast": int(g["fast"].sum()),
                         "slow": int(g["slow"].sum()),
                         **{t: int(types.get(t, 0)) for t, _ in SITE_TYPES}})
    reg = pd.DataFrame(reg_rows)
    flags["regions"] = len(reg) >= 2
    if flags["regions"]:
        charts["regions"] = {"names": list(reg["name"]), "fast": list(map(int, reg["fast"])),
                             "slow": list(map(int, reg["slow"])), "sites": list(map(int, reg["sites"]))}
        tables["regions"] = [{"name": r["name"], "sites": _i(r["sites"]), "pts": _i(r["pts"]),
                              "fast": _i(r["fast"]), "fs": _pct(r["fast"] / r["pts"])} for r in reg_rows]
        lead = reg.sort_values(["pts", "name"], ascending=[False, True], kind="mergesort").iloc[0]
        labels["regions_lede"] = (f"האזור הצפוף ביותר: {lead['name']}, עם {_i(lead['pts'])} נקודות "
                                  f"ב-{_i(lead['sites'])} אתרים ({_pct(lead['pts'] / located_pts)} מהנקודות שמיקומן ידוע).")
        labels["regions_aria"] = (f"גרף עמודות מוערמות: נקודות טעינה רגילות ומהירות לפי אזור, מדרום לצפון. "
                                  f"{lead['name']} מוביל עם {_i(lead['pts'])} נקודות.")
        charts["types"] = {"names": list(reg["name"]), "labels": [l for _, l in SITE_TYPES],
                           "series": [[round(r[t] / r["sites"] * 100, 1) for r in reg_rows] for t, _ in SITE_TYPES],
                           "counts": [[int(r[t]) for r in reg_rows] for t, _ in SITE_TYPES]}
        tables["types"] = [{"name": r["name"], **{t: f"{_i(r[t])} ({_pct(r[t] / r['sites'])})" for t, _ in SITE_TYPES}}
                           for r in reg_rows]
        tot_types = df["type"].value_counts()
        labels["types_lede"] = (f"ברוב האתרים ({_pct(tot_types.get('slow', 0) / n_sites)}) יש טעינה רגילה בלבד; "
                                f"{_i(tot_types.get('mixed', 0))} אתרים משלבים רגילה ומהירה, "
                                f"ו-{_i(tot_types.get('fast', 0))} מציעים מהירה בלבד.")
        labels["types_aria"] = (f"גרף עמודות מוערמות של 100%: סוג האתר לפי אזור. "
                                f"{_pct(tot_types.get('slow', 0) / n_sites)} מכלל האתרים בטעינה רגילה בלבד.")

        # operator x region heatmap (points)
        hops = list(ops.index[:HEAT_OPS])
        cells, hrows = [], []
        regs = list(reg["name"])
        hmax = 0
        for yi, op in enumerate(hops):
            row = {"name": op}
            g = loc[loc["op"] == op]
            for xi, rn in enumerate(regs):
                v = int(g.loc[g["region"] == rn, "pts"].sum())
                cells.append([xi, yi, v])
                row[f"r{xi}"] = _i(v)
                hmax = max(hmax, v)
            hrows.append(row)
        charts["heat"] = {"x": regs, "y": hops, "cells": cells, "max": hmax}
        tables["heat"] = hrows
        tables["heat_heads"] = ["מפעילה", *regs]
        tables["heat_keys"] = ["name", *[f"r{i}" for i in range(len(regs))]]
        # who leads each region
        leaders = []
        for rn in regs:
            g = loc[loc["region"] == rn].groupby("op")["pts"].sum().reset_index()
            g = g.sort_values(["pts", "op"], ascending=[False, True], kind="mergesort")
            leaders.append(f"{rn}: {g.iloc[0]['op']}")
        labels["heat_lede"] = (f"נקודות הטעינה של {_i(len(hops))} המפעילות הגדולות בכל אזור. "
                               f"המפעילה המובילה בכל אזור: " + "; ".join(leaders) + ".")
        labels["heat_aria"] = (f"מפת חום: נקודות טעינה לפי מפעילה ואזור. "
                               f"הערך הגבוה ביותר הוא {_i(hmax)} נקודות.")

    # ── distance to nearest fast charger ──
    fast_loc = loc[loc["fast"] > 0]
    slow_loc = loc[loc["fast"] == 0]
    flags["dist"] = len(fast_loc) >= 2 and len(slow_loc) >= 10
    dist_df = pd.DataFrame(columns=["d", "name", "op"])
    if flags["dist"]:
        d = _haversine_min(slow_loc["lat"].to_numpy(), slow_loc["lng"].to_numpy(),
                           fast_loc["lat"].to_numpy(), fast_loc["lng"].to_numpy())
        dist_df = pd.DataFrame({"d": np.round(d, 3), "name": slow_loc["name"].to_numpy(),
                                "op": slow_loc["op"].to_numpy(), "region": slow_loc["region"].to_numpy()})
        counts = []
        for lo, hi, _ in DIST_BINS:
            m = (dist_df["d"] >= lo) & ((dist_df["d"] < hi) if hi is not None else True)
            counts.append(int(m.sum()))
        charts["dist"] = {"labels": [l for _, _, l in DIST_BINS], "n": counts}
        tables["dist"] = [{"name": l, "n": _i(c), "share": _pct(c / len(dist_df))}
                          for (_, _, l), c in zip(DIST_BINS, counts)]
        med = float(dist_df["d"].median())
        labels["dist_lede"] = (f"לכל אחד מ-{_i(len(dist_df))} האתרים שיש בהם טעינה רגילה בלבד חושב המרחק בקו אווירי "
                               f"לאתר הקרוב ביותר עם טעינה מהירה. המרחק החציוני: {med:.1f} ק\"מ.")
        labels["dist_aria"] = (f"גרף עמודות: התפלגות המרחק מאתר עם טעינה רגילה בלבד לטעינה מהירה הקרובה. "
                               f"החציון {med:.1f} ק\"מ.")
        # median by region
        rm = dist_df.groupby("region")["d"].median()
        reg_order = [n for _, _, n in REGIONS if n in rm.index]
        charts["dist_reg"] = {"names": reg_order, "med": [round(float(rm[n]), 1) for n in reg_order]}

    # ── site size distribution ──
    size_counts = []
    for lo, hi, _ in SIZE_BINS:
        m = (df["pts"] >= lo) & ((df["pts"] <= hi) if hi is not None else True)
        size_counts.append(int(m.sum()))
    charts["size"] = {"labels": [l for _, _, l in SIZE_BINS], "n": size_counts}
    tables["size"] = [{"name": l, "n": _i(c), "share": _pct(c / n_sites)} for (_, _, l), c in zip(SIZE_BINS, size_counts)]
    med_pts = float(df["pts"].median())
    labels["size_lede"] = (f"באתר החציוני יש {med_pts:g} נקודות טעינה; "
                           f"{_pct((df['pts'] <= 2).mean())} מהאתרים קטנים (עד שתי נקודות), "
                           f"ורק {_i((df['pts'] >= 17).sum())} אתרים מונים 17 נקודות ומעלה.")
    labels["size_aria"] = (f"גרף עמודות: מספר האתרים לפי מספר נקודות הטעינה באתר. "
                           f"החציון {med_pts:g} נקודות.")

    # ── largest hubs ──
    hubs = df.sort_values(["pts", "fast", "oid"], ascending=[False, False, True], kind="mergesort").head(HUBS_N)
    charts["hubs"] = {"names": [f"{n} ({o})" for n, o in zip(hubs["name"], hubs["op"])],
                      "fast": list(map(int, hubs["fast"])), "slow": list(map(int, hubs["slow"]))}
    tables["hubs"] = [{"name": r.name, "op": r.op, "addr": r.addr or "לא צוינה", "pts": _i(r.pts), "fast": _i(r.fast)}
                      for r in hubs.itertuples()]
    labels["hubs_lede"] = (f"עשרת האתרים הגדולים מחזיקים {_i(hubs['pts'].sum())} נקודות, "
                           f"{_pct(hubs['pts'].sum() / total_pts)} מכלל הנקודות. הגדול שבהם: "
                           f"{hubs.iloc[0]['name']} ({_i(hubs.iloc[0]['pts'])} נקודות).")
    labels["hubs_aria"] = (f"גרף עמודות אופקי: עשרת אתרי הטעינה הגדולים. "
                           f"בראש {hubs.iloc[0]['name']} עם {_i(hubs.iloc[0]['pts'])} נקודות.")
    labels["hubs_n"] = _i(len(hubs))

    # ── fast hubs: most fast points ──
    fh = df[df["fast"] > 0].sort_values(["fast", "pts", "oid"], ascending=[False, False, True], kind="mergesort").head(HUBS_N)
    flags["fasthubs"] = len(fh) >= 3
    if flags["fasthubs"]:
        charts["fasthubs"] = {"names": [f"{n} ({o})" for n, o in zip(fh["name"], fh["op"])],
                              "fast": list(map(int, fh["fast"]))}
        tables["fasthubs"] = [{"name": r.name, "op": r.op, "addr": r.addr or "לא צוינה", "fast": _i(r.fast),
                               "pts": _i(r.pts)} for r in fh.itertuples()]
        labels["fasthubs_lede"] = (f"האתר עם הכי הרבה נקודות מהירות: {fh.iloc[0]['name']} ({fh.iloc[0]['op']}), "
                                   f"{_i(fh.iloc[0]['fast'])} נקודות מהירות. "
                                   f"{_i(len(df[df['fast'] > 0]))} אתרים בסך הכול מציעים טעינה מהירה.")
        labels["fasthubs_aria"] = (f"גרף עמודות אופקי: האתרים עם מספר הנקודות המהירות הגבוה ביותר. "
                                   f"בראש {fh.iloc[0]['name']} עם {_i(fh.iloc[0]['fast'])}.")

    # ── map ──
    flags["map"] = len(loc) > 0
    if flags["map"]:
        op_list = sorted(loc["op"].unique())
        op_idx = {o: i for i, o in enumerate(op_list)}
        pts = []
        for r in loc.sort_values(["lat", "lng", "oid"], kind="mergesort").itertuples():
            pts.append([round(float(r.lat), 5), round(float(r.lng), 5), int(r.fast), int(r.slow),
                        r.name, op_idx[r.op], r.addr])
        chunks, cur, size = [], [], 2
        for p in pts:
            b = len(json.dumps(p, ensure_ascii=True)) + 1
            if cur and size + b > MAP_CHUNK_BYTES:
                chunks.append(cur)
                cur, size = [], 2
            cur.append(p)
            size += b
        if cur:
            chunks.append(cur)
        charts["map"] = {"chunks": chunks, "ops": op_list,
                         "bounds": [[round(float(loc["lat"].min()), 4), round(float(loc["lng"].min()), 4)],
                                    [round(float(loc["lat"].max()), 4), round(float(loc["lng"].max()), 4)]]}
        miss = f" {_i(n_unlocated)} אתרים ללא מיקום בשכבה אינם מוצגים." if n_unlocated else ""
        labels["map_lede"] = (f"{_i(len(loc))} אתרי טעינה. נקודה כחולה כהה: יש באתר טעינה מהירה "
                              f"({_i(len(fast_loc))} אתרים); כחולה בהירה: טעינה רגילה בלבד. "
                              f"לחיצה על אתר מציגה את שמו, המפעילה, הכתובת ומספר הנקודות.{miss}")
        labels["map_aria"] = (f"מפה אינטראקטיבית של {_i(len(loc))} אתרי טעינה לרכב חשמלי. "
                              f"גרסה נגישה: ראו את טבלת הנתונים למטה.")
    labels["unlocated_note"] = (f" ({_i(n_unlocated)} אתרים ללא מיקום אינם נכללים)" if n_unlocated else "")

    # ── KPIs ──
    kpis["sites"] = {"value": n_sites, "display": _i(n_sites), "tone": "brand"}
    kpis["points"] = {"value": total_pts, "display": _i(total_pts), "tone": "brand"}
    kpis["fast_share"] = {"value": round(float(fast_share) * 100, 1), "display": _pct(fast_share),
                          "tone": "ok" if fast_share >= 0.3 else ("info" if fast_share >= 0.15 else "warn")}
    kpis["operators"] = {"value": n_ops, "display": _i(n_ops), "tone": "brand"}
    kpis["top3"] = {"value": round(float(top3_share) * 100, 1), "display": _pct(top3_share),
                    "tone": "warn" if top3_share >= 0.6 else "info"}
    kpi_order = ["sites", "points", "fast_share", "operators", "top3"]
    labels["kpi_sites"] = "אתרי טעינה ציבוריים"
    labels["kpi_points"] = "נקודות טעינה (עמדות)"
    labels["kpi_fast_share"] = f"נקודות טעינה מהירה ({_i(total_fast)} נקודות)"
    labels["kpi_operators"] = "חברות מפעילות"
    labels["kpi_top3"] = "נתח שלוש המפעילות הגדולות מהנקודות"
    if flags["dist"]:
        med = float(dist_df["d"].median())
        kpis["near_fast"] = {"value": round(med, 1), "display": f"{med:.1f}",
                             "tone": "ok" if med <= 3 else ("info" if med <= 8 else "warn")}
        kpi_order.append("near_fast")
        labels["kpi_near_fast"] = "מרחק חציוני (ק\"מ) מאתר רגיל לטעינה מהירה"

    # ── insights ──
    rules = [
        ("concentration", insight_concentration(ops, total_pts)),
        ("fast_gap", insight_fast_gap(ops)),
        ("region", insight_region(reg, located_pts) if flags["regions"] else None),
        ("nearest_fast", insight_nearest_fast(dist_df) if flags["dist"] else None),
        ("hub", insight_hub(df)),
        ("small_sites", insight_small_sites(df)),
        ("fast_only", insight_fast_only(df)),
        ("long_tail", insight_long_tail(ops, total_pts)),
    ]
    insights = [{"id": k, "text_he": t} for k, t in rules if t]

    labels["lede"] = (f"המאגר של משרד התחבורה מפרט {_i(n_sites)} אתרי טעינה ציבוריים לרכב חשמלי ובהם "
                      f"{_i(total_pts)} נקודות טעינה ({_i(total_fast)} מהירות ו-{_i(total_slow)} רגילות), "
                      f"שמפעילות {_i(n_ops)} חברות.")

    summary = (f"איתור עמדות טעינה לרכב חשמלי במפה: {_i(n_sites)} אתרים ו-{_i(total_pts)} נקודות טעינה, "
               f"{_pct(fast_share)} מהירות, לפי מפעילה ואזור.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
    }
