"""גושים shape (המרכז למיפוי ישראל): the national block (גוש) layer.

18,689 sub-block polygons. A national layer of that size can't be drawn as
polygons on a page, so compute reduces each polygon to its centroid and
ships one compact lookup record per sub-block: the page draws them as dots
and finds a block by number. Everything else is aggregated from the
attribute table (status of land settlement, region, sub-district, locality,
area).
"""
import itertools
import json
import math

import pandas as pd
from govlib import fmt, frame

# Lookup record coordinates: 1/SCALE degrees (1e-3°, ~100 m), enough to
# put a dot on a block whose median side is ~500 m.
SCALE = 1000
CHUNK = 44_000          # characters per lookup island (check.py caps a <script> at 51,200)
TOP_LOC = 15
TOP_COUNCIL = 12
SIZE_BINS = [(0, 50), (50, 100), (100, 250), (250, 500), (500, 1000), (1000, 5000), (5000, None)]
NO_REGION = "ללא מחוז"


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _centroid(geom: str):
    """Area-weighted centroid of a Polygon / MultiPolygon's outer rings, in
    degrees (planar: the blocks are small). Falls back to the mean vertex."""
    try:
        g = json.loads(geom)
    except (TypeError, ValueError):
        return None
    t = g.get("type") if isinstance(g, dict) else None
    if t == "Polygon":
        polys = [g.get("coordinates") or []]
    elif t == "MultiPolygon":
        polys = g.get("coordinates") or []
    else:
        return None
    a = cx = cy = 0.0
    pts = []
    for p in polys:
        if not p:
            continue
        ring = p[0]
        pts += ring
        for (x1, y1), (x2, y2) in itertools.pairwise(ring):
            c = x1 * y2 - x2 * y1
            a += c
            cx += (x1 + x2) * c
            cy += (y1 + y2) * c
    if not pts:
        return None
    if abs(a) < 1e-12:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return cx / (3 * a), cy / (3 * a)


def _prepare(df):
    d = pd.DataFrame({
        "num": _num(df["GUSH_NUM"]),
        "sfx": _num(df["GUSH_SUFFI"]).fillna(0),
        "status": frame.clean_series(df["STATUS_TEX"]),
        "loc": frame.clean_series(df["LOCALITY_N"]),
        "council": frame.clean_series(df["REG_MUN_NA"]),
        "county": frame.clean_series(df["COUNTY_NAM"]),
        "region": frame.clean_series(df["REGION_NAM"]),
        "analytic": frame.clean_series(df["IS_ANALITY"]),
        "km2": _num(df["SHAPE_AREA"]) / 1e6,
    })
    d["status"] = d["status"].where(d["status"] != "", "לא צוין")
    d["region"] = d["region"].where(d["region"] != "", NO_REGION)
    c = df["__geometry"].map(_centroid)
    d["lon"] = c.map(lambda v: v[0] if v else math.nan)
    d["lat"] = c.map(lambda v: v[1] if v else math.nan)
    d = d[d["num"].notna()].copy()
    d["num"] = d["num"].astype(int)
    d["sfx"] = d["sfx"].astype(int)
    return d.sort_values(["num", "sfx", "status", "loc", "km2"], kind="stable").reset_index(drop=True)


def _place(r) -> str:
    return r["loc"] or r["council"] or ""


def _lookup(d, statuses):
    """One record per sub-block, sorted by number: "dn,sfx,dx,dy,st,pl",
    numbers and coordinates as deltas from the record before (blocks with
    near numbers lie near each other), empty for 0."""
    places_rank = frame.ranked(d.apply(_place, axis=1))
    places = [p for p in places_rank.index]
    pidx = {p: i for i, p in enumerate(places)}
    sidx = {s: i for i, s in enumerate(statuses)}
    pts = d[d["lon"].notna()]
    ox = math.floor(pts["lon"].min() * SCALE)
    oy = math.floor(pts["lat"].min() * SCALE)
    recs, pn, px, py = [], 0, ox, oy
    for r in pts.to_dict("records"):
        x, y = round(r["lon"] * SCALE), round(r["lat"] * SCALE)
        vals = [r["num"] - pn, r["sfx"], x - px, y - py, sidx[r["status"]], pidx[_place(r)]]
        recs.append(",".join("" if v == 0 else str(v) for v in vals))
        pn, px, py = r["num"], x, y
    chunks, cur, size = [], [], 0
    for rec in recs:
        if cur and size + len(rec) + 1 > CHUNK:
            chunks.append(";".join(cur))
            cur, size = [], 0
        cur.append(rec)
        size += len(rec) + 1
    if cur:
        chunks.append(";".join(cur))
    bounds = [[float(pts["lat"].min()), float(pts["lon"].min())],
              [float(pts["lat"].max()), float(pts["lon"].max())]]
    return {"chunks": chunks, "origin": [ox, oy], "scale": SCALE, "places": places,
            "n": len(recs), "bounds": bounds}


def _size_bins(d):
    dunam = d["km2"] * 1000
    names, counts = [], []
    for lo, hi in SIZE_BINS:
        m = (dunam >= lo) & (dunam < hi) if hi else (dunam >= lo)
        names.append(f"{lo:,}-{hi:,}" if hi else f"{lo:,}+")
        counts.append(int(m.sum()))
    return names, counts


# ── insights ─────────────────────────────────────────────────────────────


def insight_settled(d, top_status):
    if not top_status:
        return None
    m = d["status"] == top_status
    area_share = d.loc[m, "km2"].sum() / d["km2"].sum() if d["km2"].sum() else 0
    count_share = m.mean()
    if count_share < 0.5:
        return None
    return (f"{fmt.pct(count_share)} מתתי-הגושים בשכבה ({fmt.int_he(m.sum())}) בסטטוס \"{top_status}\", "
            f"והם מכסים {fmt.pct(area_share)} משטח הגושים.")


def insight_region_area(reg):
    big = reg[reg["region"] != NO_REGION].sort_values(["km2", "region"], ascending=[False, True])
    if big.empty:
        return None
    r = big.iloc[0]
    a_share, c_share = r["km2"] / reg["km2"].sum(), r["count"] / reg["count"].sum()
    if a_share < c_share * 1.3:
        return None
    return (f"מחוז {r['region']} מחזיק {fmt.pct(a_share)} משטח הגושים אבל רק {fmt.pct(c_share)} "
            f"מתתי-הגושים: גוש חציוני בו משתרע על {fmt.int_he(r['median'] * 1000)} דונם.")


def insight_median_gap(reg):
    big = reg[(reg["count"] >= 100) & (reg["region"] != NO_REGION)].sort_values(["median", "region"])
    if len(big) < 3:
        return None
    lo, hi = big.iloc[0], big.iloc[-1]
    if hi["median"] < lo["median"] * 2:
        return None
    return (f"הגושים במחוז {lo['region']} הקטנים ביותר (חציון {fmt.int_he(lo['median'] * 1000)} דונם), "
            f"ובמחוז {hi['region']} הגדולים ביותר (חציון {fmt.int_he(hi['median'] * 1000)} דונם), "
            f"פי {fmt.num_he(hi['median'] / lo['median'])}.")


def insight_largest(d):
    s = d[d["km2"].notna()].sort_values(["km2", "num", "sfx"], ascending=[False, True, True])
    if s.empty:
        return None
    r = s.iloc[0]
    where = _place(r) or r["county"]
    tail = f" ({where})" if where else ""
    return (f"הגוש הגדול בשכבה הוא גוש {r['num']}{tail}, {fmt.num_he(r['km2'])} קמ״ר, "
            f"פי {fmt.int_he(r['km2'] / d['km2'].median())} מהגוש החציוני.")


def insight_concentrated(d, statuses):
    for s in statuses[1:]:
        m = d["status"] == s
        if m.sum() < 20:
            continue
        top = frame.ranked(d.loc[m, "region"])
        if top.iloc[0] / m.sum() >= 0.8 and top.index[0] != NO_REGION:
            return (f"{fmt.int_he(top.iloc[0])} מתוך {fmt.int_he(m.sum())} תתי-הגושים בסטטוס \"{s}\" "
                    f"נמצאים במחוז {top.index[0]}.")
    return None


def insight_analytic(d):
    reg = d[d["region"] != NO_REGION].groupby("region").agg(
        n=("num", "size"), a=("analytic", lambda s: (s == "1").sum()))
    reg = reg[reg["n"] >= 100]
    if reg.empty or reg["a"].sum() == 0:
        return None
    reg["share"] = reg["a"] / reg["n"]
    reg = reg.reset_index().sort_values(["share", "region"], ascending=[False, True])
    top = reg.iloc[0]
    overall = (d["analytic"] == "1").mean()
    if top["share"] < overall * 1.5:
        return None
    return (f"במחוז {top['region']} {fmt.pct(top['share'])} מתתי-הגושים מסומנים כאנליטיים, "
            f"לעומת {fmt.pct(overall)} בכל השכבה.")


def insight_top_locality(d):
    loc = frame.ranked(d.loc[d["loc"] != "", "loc"])
    if loc.empty or loc.iloc[0] < 20:
        return None
    named = loc[~loc.index.str.contains(r"\(", regex=True)]
    if named.empty:
        return None
    return (f"{named.index[0]} היא היישוב עם הכי הרבה תתי-גושים בשכבה ({fmt.int_he(named.iloc[0])}), "
            f"ואחריה {fmt.join_he(list(named.index[1:3]))}.")


# ── model ────────────────────────────────────────────────────────────────


def compute(frames):
    d = _prepare(frames["geo"])
    n_parts = len(d)
    n_gush = int(d["num"].nunique())
    total_km2 = float(d["km2"].sum())
    statuses = list(frame.ranked(d["status"]).index)
    top_status = statuses[0] if statuses else None

    st = d.groupby("status").agg(count=("num", "size"), km2=("km2", "sum"))
    st = st.loc[statuses]
    reg = d.groupby("region").agg(count=("num", "size"), km2=("km2", "sum"),
                                  median=("km2", "median"), lo=("num", "min"),
                                  hi=("num", "max")).reset_index()
    reg = reg.sort_values(["count", "region"], ascending=[False, True])
    regions = list(reg["region"])
    # Status groups for stacking/colour: the two commonest by name, the rest together.
    groups = statuses[:2] + (["אחר"] if len(statuses) > 2 else [])
    gname = d["status"].where(d["status"].isin(statuses[:2]), "אחר")
    ct = pd.crosstab(d["region"], gname).reindex(index=regions, columns=groups, fill_value=0)

    county = d[d["county"] != ""].groupby("county").agg(
        count=("num", "size"), median=("km2", "median"), lo=("num", "min"), hi=("num", "max"),
        km2=("km2", "sum")).reset_index().sort_values(["count", "county"], ascending=[False, True])
    loc_counts = frame.ranked(d.loc[d["loc"] != "", "loc"])
    loc_names, loc_vals = list(loc_counts.index[:TOP_LOC]), [int(v) for v in loc_counts.iloc[:TOP_LOC]]
    council_counts = frame.ranked(d.loc[d["council"] != "", "council"])
    c_names = list(council_counts.index[:TOP_COUNCIL])
    c_vals = [int(v) for v in council_counts.iloc[:TOP_COUNCIL]]
    size_names, size_counts = _size_bins(d)
    an = d.assign(a=(d["analytic"] == "1")).groupby("region").agg(n=("num", "size"), a=("a", "sum"))
    an = an.reindex(regions)
    an_share = [round(float(a / n * 100), 1) if n else 0.0 for a, n in zip(an["a"], an["n"])]

    lookup = _lookup(d, statuses)
    named_reg = reg[(reg["region"] != NO_REGION) & (reg["count"] >= 100)]
    big_median = (named_reg.sort_values(["median", "region"], ascending=[False, True]).iloc[0]
                  if len(named_reg) else None)
    settled_share = float((d["status"] == top_status).mean()) if top_status else 0.0
    no_loc = int((d["loc"] == "").sum())

    insights = []
    for iid, text in [
        ("settled", insight_settled(d, top_status)),
        ("region_area", insight_region_area(reg)),
        ("median_gap", insight_median_gap(reg)),
        ("largest", insight_largest(d)),
        ("concentrated", insight_concentrated(d, statuses)),
        ("analytic", insight_analytic(d)),
        ("top_locality", insight_top_locality(d)),
    ]:
        if text:
            insights.append({"id": iid, "text_he": text})

    n_regions = int((reg["region"] != NO_REGION).sum())
    summary = (f"שכבת הגושים הארצית של המרכז למיפוי ישראל: {fmt.int_he(n_parts)} תתי-גושים "
               f"({fmt.int_he(n_gush)} מספרי גוש) על {fmt.int_he(total_km2)} קמ״ר, "
               f"{fmt.pct(settled_share, 0)} מהם בסטטוס \"{top_status}\".")
    description = (f"מפת גושים ארצית: איתור גוש לפי מספר, מיקומו במפה, היישוב וסטטוס ההסדר. "
                   f"{fmt.int_he(n_gush)} גושים ב-{n_regions} מחוזות.")
    lede = (f"השכבה של המרכז למיפוי ישראל כוללת {fmt.int_he(n_parts)} תתי-גושים, "
            f"{fmt.int_he(n_gush)} מספרי גוש, על {fmt.int_he(total_km2)} קמ״ר. "
            f"חפשו מספר גוש כדי לראות היכן הוא נמצא, באיזה יישוב או מועצה ובאיזה סטטוס הסדר. "
            f"השכבה כוללת גבולות גושים בלבד, בלי חלקות.")

    def pct_or_dash(x):
        return fmt.pct(x) if total_km2 else "–"

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מפת גושים: איתור גוש לפי מספר, יישוב ומחוז",
                "description": description,
                "name": "מפת גושים (שכבת הגושים הארצית)",
                "alternate_names": ["שכבת הגושים", "גבולות גושים", "מפת גושים ארצית", "גושים shape"],
            },
        },
        "kpis": {
            "gush": {"value": n_gush, "display": fmt.int_he(n_gush), "tone": "brand"},
            "parts": {"value": n_parts, "display": fmt.int_he(n_parts), "tone": "brand"},
            "area": {"value": round(total_km2), "display": fmt.int_he(total_km2), "tone": "brand"},
            "settled": {"value": round(settled_share * 100, 1), "display": fmt.pct(settled_share),
                        "tone": "ok" if settled_share >= 0.5 else "warn"},
        },
        "labels": {
            "lede": lede,
            "settled_kpi": f"מתתי-הגושים בסטטוס \"{top_status}\"",
            "lookup_note": (f"{fmt.int_he(lookup['n'])} תתי-גושים במפה, כל אחד כנקודה במרכזו (דיוק של כ-100 מ׳). "
                            "הקלידו מספר גוש כדי למצוא אותו."),
            "map_aria": f"מפת {fmt.int_he(lookup['n'])} תתי-גושים לפי סטטוס הסדר",
            "status_note": (f"{fmt.int_he(len(statuses))} סטטוסים. \"{top_status}\" הוא {fmt.pct(settled_share)} "
                            f"מתתי-הגושים ו-{pct_or_dash(float(st['km2'].iloc[0]) / total_km2 if total_km2 else 0)} מהשטח."),
            "status_aria": f"מספר תתי-הגושים לפי סטטוס הסדר, {fmt.int_he(len(statuses))} סטטוסים",
            "region_note": f"תתי-גושים לפי מחוז וסטטוס. {fmt.int_he(len(reg))} מחוזות (כולל רשומות ללא מחוז).",
            "region_aria": f"תתי-גושים בכל אחד מ-{fmt.int_he(len(reg))} המחוזות, לפי סטטוס",
            "county_note": "מספר תתי-הגושים בכל נפה, וטווח מספרי הגוש שבה: עוזר לנחש לאיזו נפה שייך גוש.",
            "county_aria": f"תתי-גושים לפי נפה, {fmt.int_he(len(county))} נפות",
            "loc_note": (f"היישובים עם הכי הרבה תתי-גושים. {fmt.int_he(no_loc)} תתי-גושים אינם משויכים "
                         "ליישוב (שטחים פתוחים ומועצות אזוריות)."),
            "loc_aria": f"{fmt.int_he(len(loc_names))} היישובים עם הכי הרבה תתי-גושים",
            "council_note": "תתי-גושים בתחום מועצות אזוריות, לפי מועצה.",
            "council_aria": f"{fmt.int_he(len(c_names))} המועצות האזוריות עם הכי הרבה תתי-גושים",
            "size_note": (f"שטח תת-גוש חציוני: {fmt.int_he(d['km2'].median() * 1000)} דונם. "
                          f"{fmt.pct((d['km2'] < 1).mean())} מתתי-הגושים קטנים מקילומטר רבוע"
                          + (f"; החציון הגבוה ביותר הוא במחוז {big_median['region']} "
                             f"({fmt.int_he(big_median['median'] * 1000)} דונם)." if big_median is not None else ".")),
            "size_aria": "התפלגות שטח תתי-הגושים בדונם",
            "analytic_note": "שיעור תתי-הגושים המסומנים כאנליטיים (IS_ANALITY) בכל מחוז.",
            "analytic_aria": "שיעור הגושים האנליטיים לפי מחוז",
        },
        "charts": {
            "status": {"names": statuses, "values": [int(v) for v in st["count"]]},
            "region": {"names": regions, "groups": groups,
                       "series": [[int(v) for v in ct[g]] for g in groups]},
            "county": {"names": list(county["county"]), "values": [int(v) for v in county["count"]]},
            "loc": {"names": loc_names, "values": loc_vals},
            "council": {"names": c_names, "values": c_vals},
            "size": {"names": size_names, "values": size_counts},
            "analytic": {"names": regions, "values": an_share},
        },
        "tables": {
            "status": [[s, fmt.int_he(r["count"]), fmt.int_he(r["km2"]),
                        fmt.pct(r["count"] / n_parts)] for s, r in st.iterrows()],
            "region": [[r["region"], fmt.int_he(r["count"]), fmt.int_he(r["km2"]),
                        fmt.int_he(r["median"] * 1000)] for r in reg.to_dict("records")],
            "county": [[r["county"], fmt.int_he(r["count"]), f"{r['lo']}-{r['hi']}",
                        fmt.int_he(r["median"] * 1000)] for r in county.to_dict("records")],
            "loc": [[n, fmt.int_he(v)] for n, v in zip(loc_names, loc_vals)],
            "council": [[n, fmt.int_he(v)] for n, v in zip(c_names, c_vals)],
            "size": [[n, fmt.int_he(v), fmt.pct(v / n_parts)] for n, v in zip(size_names, size_counts)],
            "analytic": [[r, fmt.pct_of(v)] for r, v in zip(regions, an_share)],
        },
        "lookup": {**lookup, "statuses": statuses, "groups": groups},
        "insights": insights,
    }
