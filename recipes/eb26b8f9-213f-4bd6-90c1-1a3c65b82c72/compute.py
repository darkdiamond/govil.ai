"""Bus line ridership (נסועה בקווי אוטובוס), Ministry of Transport.

One row per route direction (RouteID + RouteDirection) per quarter; the
dataset adds a file per year and the files use different column sets
(time-of-day columns in Hebrew in newer files, in English in older ones,
missing in some). Everything is aggregated here; the latest quarter in the
data is the page's reference period.
"""
import re

import pandas as pd

ORDINAL = {1: "הראשון", 2: "השני", 3: "השלישי", 4: "הרביעי"}
METRO_NAMES = {"י-ם": "ירושלים"}
DAY_MAP = {"ימי חול": "ימי חול", "WorkDay": "ימי חול", "שישי": "שישי", "Friday": "שישי",
           "שבת": "שבת", "Saturday": "שבת"}
DAY_ORDER = ["ימי חול", "שישי", "שבת"]
BAND_RE = re.compile(r"^(ימי חול|שישי|שבת|WorkDay|Friday|Saturday) - (\d\d):(\d\d)-(\d\d):(\d\d)$")
OCC_BINS = [(None, 5, "עד 5"), (5, 10, "5 עד 10"), (10, 20, "10 עד 20"), (20, 40, "20 עד 40"), (40, None, "מעל 40")]
PRIORITY_ORDER = {"גבוהה מאד": 0, "גבוהה": 1, "בינונית": 2, "נמוכה": 3, "נמוכה מאד": 4}
UNSET = "לא צוין"


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def _fmt(v):
    return f"{int(round(v)):,}"


def _pct(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def _signed_pct(v):
    s = f"{abs(v) * 100:.1f}%"
    return ("+" if v > 0 else "−" if v < 0 else "") + s


def _millions(v):
    return f"{v / 1e6:.1f}"


def _per_label(y, q):
    return f"ר׳{q} {y}"


def _per_prose(y, q):
    return f"ברבעון {ORDINAL.get(q, str(q))} של {y}"


def _per_noun(y, q):
    return f"הרבעון {ORDINAL.get(q, str(q))} של {y}"


def _clean(s):
    return s.fillna("").astype(str).str.strip()


def _route_label(r):
    o, dst = r["OriginCityName"], r["DestinationCityName"]
    place = o if (o == dst or not dst) else f"{o} ← {dst}"
    return f"קו {r['RouteName']}, {place}" if place else f"קו {r['RouteName']}"


def _dedupe_labels(df):
    labels = df.apply(_route_label, axis=1).tolist()
    dirs = df["RouteDirection"].tolist()
    agencies = df["AgencyName"].tolist()
    seen = {}
    for lab in labels:
        seen[lab] = seen.get(lab, 0) + 1
    out = []
    for lab, dr, ag in zip(labels, dirs, agencies):
        out.append(f"{lab} ({ag}, כיוון {dr})" if seen[lab] > 1 else lab)
    return out


def _share_table(df, col, top_n):
    tot_n = len(df)
    tot_p = df["wp"].sum()
    g = df.assign(_k=df[col].replace("", UNSET)).groupby("_k").agg(n=("wp", "size"), p=("wp", "sum")).reset_index()
    g = g.sort_values(["p", "n", "_k"], ascending=[False, False, True], kind="mergesort").reset_index(drop=True)
    if len(g) > top_n:
        head = g.iloc[: top_n - 1]
        rest = g.iloc[top_n - 1:]
        g = pd.concat([head, pd.DataFrame([{"_k": "אחר", "n": rest["n"].sum(), "p": rest["p"].sum()}])],
                      ignore_index=True)
    rows = []
    for _, r in g.iterrows():
        rows.append({"name": r["_k"], "n": int(r["n"]), "p": float(r["p"]),
                     "sn": r["n"] / tot_n if tot_n else 0.0, "sp": r["p"] / tot_p if tot_p else 0.0})
    return rows


def compute(frames):
    df = frames["main"].copy()
    for c in df.columns:
        df[c] = _clean(df[c])
    df["y"] = pd.to_numeric(df["year"].str.extract(r"(\d{4})")[0], errors="coerce")
    df["q"] = pd.to_numeric(df["Q"].str.extract(r"([1-4])")[0], errors="coerce")
    df = df[df["y"].notna() & df["q"].notna()].copy()
    df["y"] = df["y"].astype(int)
    df["q"] = df["q"].astype(int)
    df["wp"] = _num(df["WeeklyPassengers"])
    df["rides"] = _num(df["WeekyRides"])
    df["km"] = _num(df["WeeklyKM"])
    df["dp"] = _num(df["DailyPassengers"])
    df["dr"] = _num(df["DailyRides(Tuesday)"])
    df["occ"] = _num(df["AVGCommutersPerRide(Weekly)"])
    df["speed"] = _num(df["AverageSpeed"]) if "AverageSpeed" in df else float("nan")
    df["cost"] = _num(df["OperatingCostPerPassenger"]) if "OperatingCostPerPassenger" in df else float("nan")
    df["length"] = _num(df["RouteLength"])
    df["stations"] = _num(df["StationsInRoute"])
    df["metro"] = df["Metropolin"].map(lambda v: METRO_NAMES.get(v, v) or UNSET)
    df["key"] = df["RouteID"] + "|" + df["RouteDirection"]

    all_periods = sorted({(int(a), int(b)) for a, b in zip(df["y"], df["q"])})
    # A quarter published only in part (far fewer route rows than usual) would
    # read as a collapse in ridership: the page then stops at the last full one.
    counts = df.groupby(["y", "q"]).size()
    med_rows = float(counts.median())
    full = [p for p in all_periods if counts[p] >= 0.8 * med_rows]
    ref = full[-1] if full else all_periods[-1]
    partial = [p for p in all_periods if p > ref]
    periods = [p for p in all_periods if p <= ref]
    df = df[[(a, b) <= ref for a, b in zip(df["y"], df["q"])]].copy()
    ly, lq = periods[-1]
    lat = df[(df["y"] == ly) & (df["q"] == lq)].copy()

    # comparator: same quarter in the latest earlier year that has it, else the previous quarter
    same_q = [p for p in periods if p[1] == lq and p[0] < ly]
    comp = same_q[-1] if same_q else (periods[-2] if len(periods) > 1 else None)
    comp_same_q = bool(same_q)
    prev = df[(df["y"] == comp[0]) & (df["q"] == comp[1])].copy() if comp else None

    lat_prose = _per_prose(ly, lq)
    lat_noun = _per_noun(ly, lq)
    comp_prose = _per_prose(*comp) if comp else ""
    comp_noun = _per_noun(*comp) if comp else ""

    # ---- quarterly trend -------------------------------------------------
    tr = df.groupby(["y", "q"]).agg(wp=("wp", "sum"), rides=("rides", "sum"), km=("km", "sum"),
                                    dp=("dp", "sum"), dr=("dr", "sum"), rows=("wp", "size"),
                                    routes=("RouteID", "nunique")).reset_index()
    tr = tr.sort_values(["y", "q"]).reset_index(drop=True)
    trend = {"x": [_per_label(a, b) for a, b in zip(tr["y"], tr["q"])],
             "pax": [round(float(v)) for v in tr["wp"]],
             "rides": [round(float(v)) for v in tr["rides"]],
             "zoom_start": max(0, len(tr) - 16)}
    trend_rows = []
    for _, r in tr.iloc[-16:].iloc[::-1].iterrows():
        trend_rows.append({"per": _per_label(r["y"], r["q"]), "pax": _fmt(r["wp"]), "rides": _fmt(r["rides"]),
                           "occ": f"{r['wp'] / r['rides']:.1f}" if r["rides"] else "",
                           "km": _fmt(r["km"]), "pkm": f"{r['wp'] / r['km']:.2f}" if r["km"] else "",
                           "dp": _fmt(r["dp"]), "dr": _fmt(r["dr"]), "rows": _fmt(r["rows"])})

    tot_wp = float(lat["wp"].sum())
    tot_rides = float(lat["rides"].sum())
    n_rows = len(lat)
    n_routes = int(lat["RouteID"].nunique())
    avg_occ = tot_wp / tot_rides if tot_rides else 0.0
    comp_wp = float(prev["wp"].sum()) if prev is not None else None
    chg = (tot_wp / comp_wp - 1) if comp_wp else None

    # ---- metropolin --------------------------------------------------------
    mg = lat.groupby("metro").agg(p=("wp", "sum"), n=("wp", "size")).reset_index()
    if prev is not None:
        pg = prev.groupby("metro")["wp"].sum()
        mg["c"] = mg["metro"].map(pg)
    else:
        mg["c"] = float("nan")
    mg = mg.sort_values(["p", "metro"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    metro = {"y": mg["metro"].tolist(), "latest": [round(float(v)) for v in mg["p"]],
             "comp": [None if pd.isna(v) else round(float(v)) for v in mg["c"]],
             "latest_name": _per_label(ly, lq), "comp_name": _per_label(*comp) if comp else ""}
    metro_rows = []
    for _, r in mg.iterrows():
        ch = (r["p"] / r["c"] - 1) if (not pd.isna(r["c"]) and r["c"] > 0) else None
        metro_rows.append({"metro": r["metro"], "n": _fmt(r["n"]), "pax": _fmt(r["p"]),
                           "share": _pct(r["p"] / tot_wp) if tot_wp else "",
                           "comp": "" if pd.isna(r["c"]) else _fmt(r["c"]),
                           "chg": "" if ch is None else _signed_pct(ch), "_ch": ch})

    # ---- operators & clusters -------------------------------------------------
    def top_group(col, n_top):
        g = lat.assign(_k=lat[col].replace("", UNSET)).groupby("_k").agg(p=("wp", "sum"), n=("wp", "size")).reset_index()
        g = g.sort_values(["p", "_k"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
        rest = g.iloc[n_top:]
        g = g.iloc[:n_top]
        rows = [{"name": r["_k"], "p": float(r["p"]), "n": int(r["n"])} for _, r in g.iterrows()]
        other = {"name": "אחר", "p": float(rest["p"].sum()), "n": int(rest["n"].sum()), "k": len(rest)} if len(rest) else None
        return rows, other, len(g) + len(rest)

    ag_rows, ag_other, n_agencies = top_group("AgencyName", 10)
    cl_rows, cl_other, n_clusters = top_group("ClusterName", 12)

    def bar_payload(rows, other):
        items = rows + ([other] if other else [])
        return {"y": [r["name"] for r in items], "v": [round(r["p"]) for r in items],
                "share": [round(r["p"] / tot_wp * 100, 1) if tot_wp else 0 for r in items]}

    def table_rows(rows, other):
        items = rows + ([other] if other else [])
        return [{"name": r["name"] if "k" not in r else f"אחר ({r['k']:,})", "pax": _fmt(r["p"]),
                 "share": _pct(r["p"] / tot_wp) if tot_wp else "", "n": _fmt(r["n"])} for r in items]

    # ---- top routes ----------------------------------------------------------
    tl = lat[lat["wp"].notna()].sort_values(["wp", "key"], ascending=[False, True], kind="mergesort").head(15).copy()
    tl["label"] = _dedupe_labels(tl)
    top_routes = {"y": tl["label"].tolist(), "v": [round(float(v)) for v in tl["wp"]]}
    top_rows = [{"label": r["label"], "agency": r["AgencyName"], "metro": r["metro"], "pax": _fmt(r["wp"]),
                 "rides": _fmt(r["rides"]), "occ": "" if pd.isna(r["occ"]) else f"{r['occ']:.1f}"}
                for _, r in tl.iterrows()]

    # ---- movers vs comparator ----------------------------------------------------
    movers = None
    mover_rows = []
    new_keys = gone_keys = 0
    new_pax = 0.0
    if prev is not None:
        a = lat[["key", "wp", "RouteName", "OriginCityName", "DestinationCityName", "RouteDirection", "AgencyName"]]
        b = prev[["key", "wp"]].rename(columns={"wp": "wp_c"})
        j = a.merge(b, on="key", how="inner")
        j = j[j["wp"].notna() & j["wp_c"].notna() & (j["wp_c"] >= 1000)].copy()
        j["d"] = j["wp"] - j["wp_c"]
        new_set = set(lat["key"]) - set(prev["key"])
        new_keys = len(new_set)
        gone_keys = len(set(prev["key"]) - set(lat["key"]))
        new_pax = float(lat[lat["key"].isin(new_set)]["wp"].sum())
        up = j[j["d"] > 0].sort_values(["d", "key"], ascending=[False, True], kind="mergesort").head(8)
        dn = j[j["d"] < 0].sort_values(["d", "key"], ascending=[True, True], kind="mergesort").head(8)
        both = pd.concat([up, dn.iloc[::-1]], ignore_index=True)
        if len(both):
            both["label"] = _dedupe_labels(both)
            movers = {"y": both["label"].tolist()[::-1], "v": [round(float(v)) for v in both["d"]][::-1]}
            for _, r in both.iterrows():
                mover_rows.append({"label": r["label"], "agency": r["AgencyName"], "comp": _fmt(r["wp_c"]),
                                   "latest": _fmt(r["wp"]),
                                   "d": ("+" if r["d"] > 0 else "−") + _fmt(abs(r["d"])),
                                   "pct": _signed_pct(r["d"] / r["wp_c"])})

    # ---- mix (small multiples) ----------------------------------------------------
    mix_dims = [("RouteType", "סוג קו", 5), ("ServiceType", "סוג שירות", 6), ("RouteParticular", "ייעוד הקו", 6),
                ("BusSize", "גודל רכב", 6), ("BusType", "סוג אוטובוס", 5)]
    mix = []
    mix_rows = []
    for col, title, n_top in mix_dims:
        rows = _share_table(lat, col, n_top)
        mix.append({"id": f"chart-mix-{len(mix) + 1}", "title": title,
                    "x": [r["name"] for r in rows],
                    "sn": [round(r["sn"] * 100, 1) for r in rows], "sp": [round(r["sp"] * 100, 1) for r in rows]})
        for r in rows:
            mix_rows.append({"dim": title, "name": r["name"], "n": _fmt(r["n"]), "sn": _pct(r["sn"]),
                             "pax": _fmt(r["p"]), "sp": _pct(r["sp"])})
    bus_rows = _share_table(lat, "BusSize", 6)

    # ---- occupancy buckets ----------------------------------------------------------
    oc = lat[lat["occ"].notna()]
    occ_rides_tot = float(oc["rides"].sum())
    occ_pax_tot = float(oc["wp"].sum())
    occ_rows = []
    occ_chart = {"x": [], "n": [], "rides": [], "pax": []}
    for lo, hi, lab in OCC_BINS:
        m = pd.Series(True, index=oc.index)
        if lo is not None:
            m &= oc["occ"] > lo
        if hi is not None:
            m &= oc["occ"] <= hi
        s = oc[m]
        sr = float(s["rides"].sum()) / occ_rides_tot if occ_rides_tot else 0.0
        sp = float(s["wp"].sum()) / occ_pax_tot if occ_pax_tot else 0.0
        occ_chart["x"].append(lab)
        occ_chart["n"].append(int(len(s)))
        occ_chart["rides"].append(round(sr * 100, 1))
        occ_chart["pax"].append(round(sp * 100, 1))
        occ_rows.append({"bucket": lab, "n": _fmt(len(s)), "sn": _pct(len(s) / len(oc)) if len(oc) else "",
                         "rides": _pct(sr), "pax": _pct(sp)})
    low_n = occ_chart["n"][0]
    low_share = low_n / len(oc) if len(oc) else 0.0
    low_rides = occ_chart["rides"][0] / 100
    low_pax = occ_chart["pax"][0] / 100
    occ_threshold = OCC_BINS[0][1]

    # ---- time of day heatmap --------------------------------------------------------
    band_cols = [c for c in df.columns if BAND_RE.match(c)]
    heat = None
    heat_rows = []
    heat_per = None
    sat_day = None
    if band_cols:
        for (py, pq) in reversed(periods):
            sub = df[(df["y"] == py) & (df["q"] == pq)]
            vals = sub[band_cols].apply(_num)
            if vals.notna().any().any():
                heat_per = (py, pq)
                break
    if heat_per is not None:
        bands = {}
        for c in band_cols:
            m = BAND_RE.match(c)
            day = DAY_MAP[m.group(1)]
            band = f"{m.group(2)}:{m.group(3)}-{m.group(4)}:{m.group(5)}"
            bands.setdefault((day, band), []).append(c)
        band_labels = sorted({b for _, b in bands})
        cells = []
        table = {d: {} for d in DAY_ORDER}
        for (day, band), cols in sorted(bands.items()):
            v = sub[cols].apply(_num).max(axis=1)
            act = int(v.notna().sum())
            med = float(v.median()) if act else 0.0
            cells.append([band_labels.index(band), DAY_ORDER.index(day), act, round(med, 1)])
            table[day][band] = (act, med)
        cells.sort()
        heat = {"x": band_labels, "y": DAY_ORDER, "cells": cells, "max": max(c[2] for c in cells) if cells else 1}
        for d in DAY_ORDER:
            heat_rows.append({"day": d, "cells": [f"{table[d][b][0]:,}" if b in table[d] else "" for b in band_labels]})
        # Saturday daytime vs weekday morning
        def hour(b):
            return int(b[:2])
        wk = [(table["ימי חול"][b][0], b) for b in band_labels if b in table["ימי חול"]]
        sat = [(table["שבת"][b][0], b) for b in band_labels if b in table["שבת"] and 6 <= hour(b) < 15]
        if wk and sat:
            wk_max = max(wk, key=lambda t: (t[0], t[1]))
            sat_max = max(sat, key=lambda t: (t[0], t[1]))
            sat_day = {"wk": wk_max, "sat": sat_max}

    # ---- speed and cost by metropolin ----------------------------------------------
    sc = None
    sc_rows = []
    sc_per = None
    for (py, pq) in reversed(periods):
        sub2 = df[(df["y"] == py) & (df["q"] == pq) & df["speed"].notna()]
        if len(sub2):
            sc_per = (py, pq)
            break
    if sc_per is not None:
        s = sub2[sub2["rides"].notna()]
        g = s.assign(sw=s["speed"] * s["rides"]).groupby("metro").agg(sw=("sw", "sum"), r=("rides", "sum"),
                                                                      cost=("cost", "median"), n=("speed", "size")).reset_index()
        g["sp"] = g["sw"] / g["r"]
        g = g.sort_values(["sp", "metro"], ascending=[True, True], kind="mergesort").reset_index(drop=True)
        sc = {"y": g["metro"].tolist(), "speed": [round(float(v), 1) for v in g["sp"]],
              "cost": [None if pd.isna(v) else round(float(v), 1) for v in g["cost"]]}
        for _, r in g.iterrows():
            sc_rows.append({"metro": r["metro"], "n": _fmt(r["n"]), "speed": f"{r['sp']:.1f}",
                            "cost": "" if pd.isna(r["cost"]) else f"{r['cost']:.1f}"})
        sc_overall = float((s["speed"] * s["rides"]).sum() / s["rides"].sum()) if s["rides"].sum() else None
    else:
        sc_overall = None

    # ---- profile by route type (table) --------------------------------------------
    prof_rows = []
    pg2 = lat.assign(_k=lat["RouteType"].replace("", UNSET))
    for k, s in sorted(pg2.groupby("_k"), key=lambda kv: (-kv[1]["wp"].sum(), kv[0])):
        sp = s[s["speed"].notna() & s["rides"].notna()]
        wsp = (sp["speed"] * sp["rides"]).sum() / sp["rides"].sum() if sp["rides"].sum() else None
        prof_rows.append({"type": k, "n": _fmt(len(s)),
                          "len": "" if s["length"].isna().all() else f"{s['length'].median():.1f}",
                          "st": "" if s["stations"].isna().all() else f"{s['stations'].median():.0f}",
                          "speed": "" if wsp is None else f"{wsp:.1f}",
                          "cost": "" if s["cost"].isna().all() else f"{s['cost'].median():.1f}",
                          "occ": f"{s['wp'].sum() / s['rides'].sum():.1f}" if s["rides"].sum() else ""})

    # ---- ministry review flags -------------------------------------------------------
    review = None
    review_rows = []
    add_counts = []
    if "המלצה" in lat.columns and (lat["המלצה"] != "").any():
        fl = lat[lat["המלצה"] != ""].copy()

        def prio(v):
            m = re.search(r"בעדיפות (.+)$", v)
            return m.group(1).strip() if m else v
        fl["prio"] = fl["המלצה"].map(prio)
        g = fl.groupby("prio").agg(n=("wp", "size"), p=("wp", "sum"), r=("rides", "sum"), occ=("occ", "median")).reset_index()
        g["o"] = g["prio"].map(lambda v: PRIORITY_ORDER.get(v, 9))
        g = g.sort_values(["o", "prio"], kind="mergesort").reset_index(drop=True)
        review = {"x": [f"עדיפות {v}" if v in PRIORITY_ORDER else v for v in g["prio"]],
                  "n": [int(v) for v in g["n"]], "total": int(len(fl)), "pax": float(fl["wp"].sum()),
                  "rides": float(fl["rides"].sum())}
        for (_, r), lab in zip(g.iterrows(), review["x"]):
            review_rows.append({"prio": lab, "n": _fmt(r["n"]), "pax": _fmt(r["p"]), "rides": _fmt(r["r"]),
                                "occ": "" if pd.isna(r["occ"]) else f"{r['occ']:.1f}"})
        if "דרוג הוספה" in lat.columns:
            ad = _num(lat["דרוג הוספה"])
            for lvl in sorted({int(v) for v in ad.dropna() if v > 0}):
                add_counts.append((lvl, int((ad == lvl).sum())))

    # ---- unique localities / new routes ----------------------------------------------
    uniq_locs = set()
    uniq_rows = 0
    if "UniqueLocations" in lat.columns:
        for v in lat["UniqueLocations"]:
            if v:
                uniq_rows += 1
                uniq_locs.update(p.strip() for p in v.split(",") if p.strip())
    months = _num(lat["OperationSince"].str.extract(r"(\d+)")[0].fillna(""))
    new_ops = int(months.notna().sum())
    new_ops_pax = float(lat.loc[months.notna(), "wp"].sum())
    new_ops_max = int(months.max()) if new_ops else 0

    # ---- insights ------------------------------------------------------------------
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    if chg is not None:
        basis = "באותו רבעון" if comp_same_q else "ברבעון הקודם בנתונים"
        if chg >= 0.02:
            word = f"עלייה של {_pct(chg)}"
        elif chg <= -0.02:
            word = f"ירידה של {_pct(-chg)}"
        else:
            word = f"יציבות (שינוי של {_signed_pct(chg)})"
        add("trend", f"{lat_prose} נרשמו {_fmt(tot_wp)} עליות בשבוע בקווי האוטובוס, {word} לעומת "
                     f"{_fmt(comp_wp)} {comp_prose} ({basis}).")
    if len(tr) >= 3:
        pk = tr.sort_values(["wp", "y", "q"], ascending=[False, False, False], kind="mergesort").iloc[0]
        if (int(pk["y"]), int(pk["q"])) == (ly, lq):
            add("peak", f"{lat_noun} הוא שיא הנסועה בכל {len(tr)} הרבעונים שבנתונים.")
        else:
            gap = tot_wp / pk["wp"] - 1
            add("peak", f"שיא הנסועה בנתונים נרשם {_per_prose(int(pk['y']), int(pk['q']))}: {_fmt(pk['wp'])} עליות בשבוע. "
                        f"הרבעון האחרון נמוך ממנו ב-{_pct(-gap)}.")
    if len(mg) >= 2 and tot_wp:
        a1, a2 = mg.iloc[0], mg.iloc[1]
        s1 = a1["p"] / tot_wp
        if s1 >= 0.15:
            add("metro", f"מטרופולין {a1['metro']} מוביל עם {_pct(s1)} מהעליות השבועיות ({_fmt(a1['p'])}), "
                         f"ואחריו {a2['metro']} עם {_pct(a2['p'] / tot_wp)}.")
    if len(ag_rows) >= 3 and tot_wp:
        s1 = ag_rows[0]["p"] / tot_wp
        s3 = sum(r["p"] for r in ag_rows[:3]) / tot_wp
        if s1 >= 0.1:
            add("agency", f"{ag_rows[0]['name']} היא המפעילה הגדולה ({_pct(s1)} מהעליות). שלוש המפעילות הגדולות, "
                          f"{ag_rows[0]['name']}, {ag_rows[1]['name']} ו{ag_rows[2]['name']}, מסיעות יחד {_pct(s3)} "
                          f"מתוך {n_agencies:,} מפעילות.")
    if low_share >= 0.05:
        add("low_occ", f"{_fmt(low_n)} כיווני קו ({_pct(low_share)}) מסיעים בממוצע עד {occ_threshold} נוסעים לנסיעה. "
                       f"הם מבצעים {_pct(low_rides)} מהנסיעות השבועיות אך מסיעים רק {_pct(low_pax)} מהנוסעים.")
    if bus_rows:
        cand = [r for r in bus_rows if r["sn"] >= 0.01 and r["name"] not in (UNSET, "אחר", "לא מוגדר")]
        cand = sorted(cand, key=lambda r: (-(r["sp"] / r["sn"]), r["name"]))
        if cand and cand[0]["sp"] / cand[0]["sn"] >= 2:
            r = cand[0]
            add("bus_size", f"קווי {r['name']} הם {_pct(r['sn'])} מכיווני הקו, אך מסיעים {_pct(r['sp'])} מהעליות השבועיות.")
    if len(tl):
        r = tl.iloc[0]
        add("top_route", f"הקו העמוס ביותר {lat_prose} הוא {tl['label'].iloc[0]} של {r['AgencyName']}, "
                         f"עם {_fmt(r['wp'])} עליות בשבוע.")
    if sat_day:
        (wn, wb), (sn, sb) = sat_day["wk"], sat_day["sat"]
        if wn and sn / wn <= 0.25:
            add("shabbat", f"בשבת בשעות היום פועלים מעט קווים: בשעות {sb} פעלו {_fmt(sn)} כיווני קו, "
                           f"לעומת {_fmt(wn)} בשעות {wb} בימי חול.")
    if review and n_rows:
        add("review", f"בנתונים מסומנים {_fmt(review['total'])} כיווני קו ({_pct(review['total'] / n_rows)}) "
                      f"בהמלצה לבחון ביטול, דילול או שינוי. יחד הם מסיעים רק {_pct(review['pax'] / tot_wp)} מהעליות השבועיות.")
    if new_ops >= 10 and tot_wp:
        add("new_ops", f"{_fmt(new_ops)} כיווני קו החלו לפעול ב-{new_ops_max} החודשים האחרונים, "
                       f"ומסיעים {_fmt(new_ops_pax)} עליות בשבוע ({_pct(new_ops_pax / tot_wp)}).")
    insights = insights[:9]

    # ---- KPIs ----------------------------------------------------------------------
    kpis = {
        "pax": {"value": round(tot_wp), "display": _millions(tot_wp), "tone": "brand"},
        "rides": {"value": round(tot_rides), "display": _fmt(tot_rides), "tone": "brand"},
        "routes": {"value": n_rows, "display": _fmt(n_rows), "tone": "brand"},
        "occ": {"value": round(avg_occ, 1), "display": f"{avg_occ:.1f}", "tone": "info"},
        "low": {"value": round(low_share * 100, 1), "display": _pct(low_share),
                "tone": "warn" if low_share >= 0.15 else "brand"},
    }
    if chg is not None:
        kpis["chg"] = {"value": round(chg * 100, 1), "display": _signed_pct(chg),
                       "tone": "ok" if chg >= 0.02 else "danger" if chg <= -0.02 else "brand"}

    span = f"{periods[0][0]}/{ly}" if periods[0][0] != ly else str(ly)
    summary = (f"נסועה בקווי אוטובוס: מספר הנוסעים בכל קו, לפי מפעיל ומטרופולין. {lat_prose} נרשמו "
               f"{_millions(tot_wp)} מיליון עליות בשבוע ב-{_fmt(n_rows)} כיווני קו.")

    big_metro = metro_rows[0]["metro"] if metro_rows else ""
    labels = {
        "lede": (f"מערכת המסלקה של הרשות הארצית לתחבורה ציבורית סופרת כל תיקוף כרטיס באוטובוס. {lat_prose} "
                 f"עלו נוסעים {_fmt(tot_wp)} פעמים בשבוע ל-{_fmt(n_rows)} כיווני קו ({_fmt(n_routes)} קווים) של "
                 f"{n_agencies:,} מפעילות, ב-{_fmt(tot_rides)} נסיעות שבועיות. הנתונים מתפרסמים לפי רבעון, "
                 f"ויש בהם {len(periods)} רבעונים מ{_per_noun(*periods[0])} ועד {lat_noun}."
                 + (f" נתוני {_per_noun(*partial[-1])} פורסמו חלקית ({_fmt(counts[partial[-1]])} כיווני קו) "
                    "ולכן אינם נכללים בעמוד." if partial else "")),
        "pax_kpi": f"עליות בשבוע, מיליונים ({_per_label(ly, lq)})",
        "chg_kpi": f"שינוי לעומת {_per_label(*comp)}" if comp else "",
        "rides_kpi": "נסיעות אוטובוס בשבוע",
        "routes_kpi": f"כיווני קו פעילים ({_fmt(n_routes)} קווים)",
        "occ_kpi": "נוסעים בממוצע לנסיעה",
        "low_kpi": f"כיווני קו עם עד {occ_threshold} נוסעים לנסיעה",
        "trend_note": (f"סך העליות השבועיות (עמודות) ומספר הנסיעות השבועיות (קו) בכל רבעון שפורסם. "
                       f"הנתונים אינם רציפים: רבעונים שלא פורסמו חסרים בציר. ממוצע הנוסעים לנסיעה "
                       f"{lat_prose}: {avg_occ:.1f}."),
        "trend_aria": f"עליות ונסיעות שבועיות לפי רבעון, {len(periods)} רבעונים",
        "metro_note": (f"עליות שבועיות לפי מטרופולין {lat_prose}"
                       + (f", לעומת {comp_noun}." if comp else ".")
                       + (f" {big_metro} מוביל עם {metro_rows[0]['share']} מהעליות." if metro_rows else "")),
        "metro_aria": f"עליות שבועיות לפי מטרופולין, {len(metro_rows)} מטרופולינים",
        "agency_note": (f"{len(ag_rows)} המפעילות עם מספר העליות הגדול ביותר {lat_prose}"
                        + (f", ושאר {ag_other['k']:,} המפעילות מקובצות תחת אחר." if ag_other else ".")),
        "agency_aria": f"עליות שבועיות לפי מפעילה, {len(ag_rows)} המובילות",
        "cluster_note": (f"אשכול הוא קבוצת קווים שהמדינה מפעילה במכרז אחד. {len(cl_rows)} האשכולות הגדולים "
                         f"מתוך {n_clusters:,}" + (", והשאר תחת אחר." if cl_other else ".")),
        "cluster_aria": f"עליות שבועיות לפי אשכול, {len(cl_rows)} הגדולים",
        "top_note": (f"{len(tl)} כיווני הקו עם מספר העליות השבועי הגבוה ביותר {lat_prose}. "
                     "כל כיוון נסיעה של קו נספר בנפרד."),
        "top_aria": f"{len(tl)} כיווני הקו העמוסים ביותר",
        "movers_note": (f"השינוי בעליות השבועיות בין {comp_noun} לבין {lat_noun}, בכיווני קו שפעלו בשני הרבעונים "
                        f"ושהסיעו לפחות {_fmt(1000)} עליות בשבוע ברבעון ההשוואה. "
                        f"{_fmt(new_keys)} כיווני קו חדשים ({_fmt(new_pax)} עליות בשבוע) ו-{_fmt(gone_keys)} "
                        f"שלא הופיעו שוב אינם בתרשים.") if comp else "",
        "movers_aria": "כיווני הקו עם העלייה והירידה הגדולות בעליות השבועיות",
        "mix_note": (f"לכל מאפיין: חלקו במספר כיווני הקו לעומת חלקו בעליות השבועיות {lat_prose}. "
                     "פער בין שתי העמודות מראה היכן מרוכזים הנוסעים."),
        "occ_note": (f"כיווני הקו לפי ממוצע הנוסעים לנסיעה {lat_prose}, וחלקם בנסיעות ובעליות. "
                     f"{_pct(low_share)} מכיווני הקו מסיעים בממוצע עד {occ_threshold} נוסעים לנסיעה."),
        "occ_aria": "התפלגות כיווני הקו לפי ממוצע נוסעים לנסיעה",
        "heat_note": ("" if heat_per is None else
                      f"מספר כיווני הקו שפעלו בכל חלון שעות {_per_prose(*heat_per)}, בימי חול, בשישי ובשבת. "
                      "המעבר על תא מציג גם את חציון הנוסעים לנסיעה בחלון. חלון הלילה של שבת הוא ליל שישי."),
        "heat_aria": "מפת חום של כיווני קו פעילים לפי יום וחלון שעות",
        "sc_note": ("" if sc_per is None else
                    f"מהירות נסיעה ממוצעת (משוקללת במספר הנסיעות) וחציון עלות התפעול לנוסע לפי מטרופולין, "
                    f"{_per_prose(*sc_per)}."
                    + (f" המהירות הממוצעת בכל הארץ: {sc_overall:.1f} קמ״ש." if sc_overall else "")),
        "speed_aria": "מהירות נסיעה ממוצעת לפי מטרופולין",
        "cost_aria": "חציון עלות תפעול לנוסע לפי מטרופולין",
        "prof_note": f"מאפייני הקווים לפי סוג קו, {lat_prose}. אורך, מספר תחנות ועלות הם חציונים.",
        "review_note": ("" if not review else
                        f"בנתוני {lat_noun} מסומנים {_fmt(review['total'])} כיווני קו בהמלצה לבחון ביטול, דילול "
                        f"או שינוי, לפי עדיפות. הם מבצעים {_fmt(review['rides'])} נסיעות בשבוע ומסיעים "
                        f"{_fmt(review['pax'])} עליות."
                        + (" בנוסף דורגו לתגבור: " + ", ".join(f"{c:,} כיווני קו בדרגה {lv}" for lv, c in add_counts) + "."
                           if add_counts else "")
                        + (f" {_fmt(uniq_rows)} כיווני קו מסומנים כמשרתים יישובים ייחודיים לקו ({len(uniq_locs):,} יישובים)."
                           if uniq_rows else "")),
        "review_aria": "כיווני קו שסומנו לבחינה לפי עדיפות",
        "lat_label": _per_label(ly, lq),
        "comp_label": _per_label(*comp) if comp else "",
    }

    flags = {"chg": chg is not None, "movers": movers is not None, "heat": heat is not None,
             "sc": sc is not None, "review": review is not None, "metro_comp": comp is not None}

    return {
        "agent_data": {"summary_he": summary, "dataset_kind": "timeseries", "temporal_coverage": span,
                       "spatial_coverage": "ישראל"},
        "kpis": kpis,
        "charts": {"trend": trend, "metro": metro, "agency": bar_payload(ag_rows, ag_other),
                   "cluster": bar_payload(cl_rows, cl_other), "top": top_routes, "movers": movers,
                   "mix": mix, "occ": occ_chart, "heat": heat, "sc": sc, "review": review and {"x": review["x"], "n": review["n"]}},
        "insights": insights,
        "labels": labels,
        "flags": flags,
        "tables": {"trend": trend_rows, "metro": [{k: v for k, v in r.items() if k != "_ch"} for r in metro_rows],
                   "agency": table_rows(ag_rows, ag_other), "cluster": table_rows(cl_rows, cl_other),
                   "top": top_rows, "movers": mover_rows, "mix": mix_rows, "occ": occ_rows,
                   "heat_bands": heat["x"] if heat else [], "heat": heat_rows, "sc": sc_rows, "prof": prof_rows,
                   "review": review_rows},
    }
