"""Fire and Rescue Israel: events by district, month, domain and scenario.

Two inputs carry the same table under two schemas: `eng` (2012 to 2022 Q3,
English column names) and `heb` (2022 Q4 on, Hebrew column names). Each new
quarter arrives as a new resource and is picked up by `by_schema`. Rows are
pre-aggregated counts (`מספר אירועים`) per year, month, district, domain
(תחום), type (מתאר), scenario (תרחיש) and location, so every figure is a sum
of that column, never a row count.
"""
import calendar
import re

import pandas as pd
from govlib import fmt, frame

ENG = {
    "EventYear": "y", "EventMonth": "m", "District": "dist", "EventAreaDesc": "dom",
    "EventTypeDesc": "typ", "EventScenarioDesc": "scen", "GeneralAddress": "loc",
    "EventsNum": "n",
}
HEB = {
    "שנה": "y", "EventMonth": "m", "מחוז": "dist", "תחום": "dom", "מתאר": "typ",
    "תרחיש": "scen", "מיקום": "loc", "מספר אירועים": "n",
}
NO_ADDRESS = "ללא כתובת"
# A location that is a road or junction, not a locality.
ROAD_RE = re.compile(r"^(כביש|צומת|מחלף|כיכר|דרך)\b")
SEASON_YEARS = 5
GROWTH_SPAN = 5
TREND_EPS = 0.03
DIP_RATIO = 0.5


def _norm(s: pd.Series) -> pd.Series:
    """One spelling per label: the files mix geresh styles (חומ'ס / חומ"ס,
    גפ''מ) and spacing around slashes."""
    s = frame.clean_series(s)
    s = s.str.replace("''", '"', regex=False)
    s = s.str.replace(r"'(?=[א-ת](?![א-ת]))", '"', regex=True)
    s = s.str.replace(r"\s*/\s*", " / ", regex=True)
    return s


def _load(frames):
    parts = []
    for name, cols in (("eng", ENG), ("heb", HEB)):
        f = frames.get(name)
        if f is None or not len(f):
            continue
        f = f[list(cols)].rename(columns=cols)
        parts.append(f)
    d = pd.concat(parts, ignore_index=True)
    d["n"] = frame.num(d["n"])
    d["y"] = pd.to_numeric(frame.clean_series(d["y"]), errors="coerce")
    d["m"] = pd.to_numeric(frame.clean_series(d["m"]), errors="coerce")
    d = d[d["n"].notna() & (d["n"] > 0) & d["y"].between(1990, 2100) & d["m"].between(1, 12)].copy()
    d["y"] = d["y"].astype(int)
    d["m"] = d["m"].astype(int)
    for c in ("dist", "dom", "typ", "scen", "loc"):
        d[c] = _norm(d[c])
    d.loc[d["dist"] == "", "dist"] = "לא צוין"
    d.loc[d["dom"] == "", "dom"] = "לא צוין"
    d.loc[d["typ"] == "", "typ"] = "לא צוין"
    d.loc[d["scen"] == "", "scen"] = "לא צוין"
    return d


def _rank(s: pd.Series) -> pd.Series:
    """Sum series ordered by value desc, ties by label."""
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _i(v):
    return round(float(v))


def _pct1(v):
    return round(float(v) * 100, 1)


def compute(frames):
    d = _load(frames)
    total_all = float(d["n"].sum())

    months_in = d.groupby("y")["m"].nunique()
    years = sorted(int(y) for y in months_in.index)

    # Dip months: far below the median of the 12 months before them. Stated
    # as numbers only (no cause is claimed); the year still counts.
    ym = d.groupby(["y", "m"])["n"].sum()
    seq = [(y, m, float(ym[(y, m)])) for y in years for m in range(1, 13) if (y, m) in ym.index]
    dips = []
    for i in range(12, len(seq) - 1):  # the newest month may be partly loaded
        base = float(pd.Series([v for _, _, v in seq[i - 12:i]]).median())
        if base > 0 and seq[i][2] < DIP_RATIO * base:
            dips.append((seq[i][0], seq[i][1], seq[i][2], base))

    complete = [y for y in years if months_in[y] == 12]
    if not complete:
        raise ValueError("no complete year in the data")
    ly = complete[-1]
    py = ly - 1 if (ly - 1) in complete else None
    partial = years[-1] if months_in[years[-1]] < 12 else None
    p_months = sorted(int(m) for m in d.loc[d["y"] == partial, "m"].unique()) if partial else []
    first = years[0]

    yearly = d.groupby("y")["n"].sum()
    ly_df = d[d["y"] == ly]
    ly_total = float(yearly[ly])
    py_total = float(yearly[py]) if py else None

    # ── domains ───────────────────────────────────────────────────────────
    dom_rank = _rank(d.groupby("dom")["n"].sum())
    dom_labels, _ = frame.top_other(dom_rank, 4)
    keep_dom = [x for x in dom_labels if x != frame.OTHER]
    d["dom_g"] = d["dom"].where(d["dom"].isin(keep_dom), frame.OTHER)
    ly_df = d[d["y"] == ly]
    top_dom = str(_rank(ly_df.groupby("dom")["n"].sum()).index[0])

    def ylabel(y):
        return f"{y} (חלקית)" if months_in[y] < 12 else str(y)

    by_y_dom = d.pivot_table(index="y", columns="dom_g", values="n", aggfunc="sum").fillna(0)
    chart_years = {
        "x": [ylabel(y) for y in years],
        "partial": [bool(months_in[y] < 12) for y in years],
        "series": [{"name": g, "data": [_i(by_y_dom.at[y, g]) if g in by_y_dom.columns else 0 for y in years]}
                   for g in dom_labels],
        "total": [_i(yearly[y]) for y in years],
    }
    tbl_years = [[ylabel(y), fmt.int_he(yearly[y])]
                 + [fmt.int_he(by_y_dom.at[y, g]) if g in by_y_dom.columns else "0" for g in dom_labels]
                 for y in reversed(years)]

    # ── month x year heatmap ─────────────────────────────────────────────
    cells = []
    for yi, y in enumerate(years):
        for m in range(1, 13):
            if (y, m) in ym.index:
                cells.append([m - 1, yi, _i(ym[(y, m)])])
    heat = {"x": fmt.MONTHS_SHORT_HE, "y": [str(y) for y in years], "cells": cells,
            "max": max(c[2] for c in cells)}

    # Peak month overall
    peak_ym = max(seq, key=lambda t: (t[2], t[0], t[1]))

    # ── seasonality: top domain·type combos, mean per calendar month ─────
    season_years = complete[-SEASON_YEARS:]
    sd = d[d["y"].isin(season_years)].copy()
    sd["combo"] = sd["dom"] + " · " + sd["typ"]
    combo_rank = _rank(d[d["y"] == ly].assign(combo=lambda x: x["dom"] + " · " + x["typ"])
                       .groupby("combo")["n"].sum())
    combos = [str(c) for c in combo_rank.index[:5]]
    cm = sd[sd["combo"].isin(combos)].groupby(["combo", "m"])["n"].sum() / len(season_years)
    season = {"x": fmt.MONTHS_SHORT_HE, "series": []}
    season_best = None
    for c in combos:
        vals = [round(float(cm.get((c, m), 0.0)), 1) for m in range(1, 13)]
        season["series"].append({"name": c, "data": vals})
        lo, hi = min(vals), max(vals)
        if lo > 0 and sum(vals) / 12 >= 100:
            ratio = hi / lo
            if season_best is None or ratio > season_best[0]:
                season_best = (ratio, c, vals.index(hi), hi, vals.index(lo), lo)
    tbl_season = [[fmt.MONTHS_HE[m]] + [fmt.int_he(s["data"][m]) for s in season["series"]] for m in range(12)]
    if len(season_years) == 1:
        season_span = str(season_years[0])
    elif season_years[-1] - season_years[0] == len(season_years) - 1:
        season_span = f"{season_years[0]}-{season_years[-1]}"
    else:
        season_span = fmt.join_he(season_years)

    # ── top domain broken down by type, per year ─────────────────────────
    td = d[d["dom"] == top_dom]
    typ_rank = _rank(td.groupby("typ")["n"].sum())
    typ_labels, _ = frame.top_other(typ_rank, 4)
    keep_typ = [x for x in typ_labels if x != frame.OTHER]
    td = td.assign(typ_g=td["typ"].where(td["typ"].isin(keep_typ), frame.OTHER))
    tt = td.pivot_table(index="y", columns="typ_g", values="n", aggfunc="sum").fillna(0)
    chart_types = {
        "x": [str(y) for y in complete],
        "series": [{"name": t, "data": [_i(tt.at[y, t]) if (y in tt.index and t in tt.columns) else 0
                                        for y in complete]} for t in typ_labels],
    }
    tbl_types = [[str(y)] + [fmt.int_he(tt.at[y, t]) if (y in tt.index and t in tt.columns) else "0"
                             for t in typ_labels] for y in reversed(complete)]

    # ── districts ────────────────────────────────────────────────────────
    dist_ly = _rank(ly_df.groupby("dist")["n"].sum())
    dists = [str(x) for x in dist_ly.index if x != "לא צוין"]
    dy = d[d["y"].isin(complete)].pivot_table(index="y", columns="dist", values="n", aggfunc="sum").fillna(0)
    chart_dist_years = {
        "x": [str(y) for y in complete],
        "series": [{"name": s, "data": [_i(dy.at[y, s]) if s in dy.columns else 0 for y in complete]}
                   for s in dists],
    }
    tbl_dist_years = [[str(y)] + [fmt.int_he(dy.at[y, s]) if s in dy.columns else "0" for s in dists]
                      for y in reversed(complete)]

    dd = ly_df.pivot_table(index="dist", columns="dom_g", values="n", aggfunc="sum").fillna(0)
    chart_dist_mix = {"x": dists, "series": []}
    for g in dom_labels:
        vals = []
        for s in dists:
            tot = float(dd.loc[s].sum()) if s in dd.index else 0.0
            v = float(dd.at[s, g]) if (s in dd.index and g in dd.columns) else 0.0
            vals.append(round(v / tot * 100, 1) if tot else 0.0)
        chart_dist_mix["series"].append({"name": g, "data": vals})
    tbl_dist_mix = [[s, fmt.int_he(dist_ly[s]), fmt.pct(dist_ly[s] / ly_total)]
                    + [fmt.pct_of(sr["data"][i]) for sr in chart_dist_mix["series"]]
                    for i, s in enumerate(dists)]

    base_y = ly - GROWTH_SPAN if (ly - GROWTH_SPAN) in complete else (complete[0] if complete[0] < ly else None)
    growth = None
    if base_y is not None:
        rows = []
        for s in dists:
            b = float(dy.at[base_y, s]) if s in dy.columns else 0.0
            a = float(dy.at[ly, s]) if s in dy.columns else 0.0
            if b > 0:
                rows.append((s, b, a, (a - b) / b))
        rows.sort(key=lambda r: (-r[3], r[0]))
        if rows:
            growth = {
                "base": base_y,
                "x": [r[0] for r in rows],
                "pct": [_pct1(r[3]) for r in rows],
                "rows": [[r[0], fmt.int_he(r[1]), fmt.int_he(r[2]), fmt.signed_pct(r[3])] for r in rows],
            }
            b_tot = float(dy.loc[base_y].sum())
            growth["total_pct"] = (ly_total - b_tot) / b_tot if b_tot else None

    # ── scenarios (latest complete year) ─────────────────────────────────
    scen_ly = _rank(ly_df.groupby("scen")["n"].sum())
    scen_ly = scen_ly[scen_ly.index != "לא צוין"]
    scen_dom = (ly_df.groupby(["scen", "dom"])["n"].sum().reset_index()
                .sort_values(["scen", "n", "dom"], ascending=[True, False, True], kind="stable")
                .drop_duplicates("scen").set_index("scen")["dom"])
    scen_py = d[d["y"] == py].groupby("scen")["n"].sum() if py else pd.Series(dtype=float)
    top_sc = scen_ly.iloc[:12]
    chart_scen = {"x": [str(s) for s in top_sc.index], "y": [_i(v) for v in top_sc],
                  "dom": [str(scen_dom.get(s, "")) for s in top_sc.index]}
    tbl_scen = []
    chart_scen["ch"] = []
    for s, v in top_sc.items():
        p = float(scen_py.get(s, 0.0))
        ch = fmt.signed_pct((v - p) / p) if p >= 50 else "–"
        chart_scen["ch"].append(ch if p >= 50 else None)
        tbl_scen.append([str(s), str(scen_dom.get(s, "")), fmt.int_he(v), fmt.pct(v / ly_total), ch])

    mover = None
    if py:
        both = pd.DataFrame({"a": scen_ly, "b": scen_py}).fillna(0)
        both["diff"] = both["a"] - both["b"]
        both = both.sort_index().sort_values("diff", ascending=False, kind="stable")
        if len(both):
            s = str(both.index[0])
            a, b = float(both.iloc[0]["a"]), float(both.iloc[0]["b"])
            if b >= 100 and a - b >= 0.01 * ly_total and (a - b) / b >= 0.2:
                mover = (s, a, b)

    # ── event types inside each domain (latest complete year) ───────────
    dom_ly = _rank(ly_df.groupby("dom")["n"].sum())
    dl_labels, _ = frame.top_other(dom_ly, 4)
    dl_keep = [x for x in dl_labels if x != frame.OTHER]
    panels, tbl_dom_types, dom_type_leads = [], [], []
    for g in dl_labels:
        sub = ly_df[ly_df["dom"].isin(dl_keep) == (g != frame.OTHER)]
        if g != frame.OTHER:
            sub = sub[sub["dom"] == g]
        tot = float(sub["n"].sum())
        if tot <= 0:
            continue
        sc = _rank(sub.groupby("scen")["n"].sum())
        lab, val = frame.top_other(sc, 5)
        title = g if g != frame.OTHER else f"תחומים אחרים ({fmt.join_he(sorted(set(sub['dom'])))})"
        panels.append({"name": title, "total": f"{fmt.int_he(tot)} אירועים", "x": lab, "y": [_i(v) for v in val],
                       "share": [_pct1(v / tot) for v in val]})
        for k, v in zip(lab, val, strict=True):
            tbl_dom_types.append([title, k, fmt.int_he(v), fmt.pct(v / tot)])
        named = [(k, v) for k, v in zip(lab, val, strict=True) if k not in (frame.OTHER, "לא צוין")]
        if g != frame.OTHER and named:
            dom_type_leads.append((g, named[0][0], float(named[0][1]) / tot))

    # ── localities (latest complete year) ────────────────────────────────
    lc = ly_df[(ly_df["loc"] != "") & (ly_df["loc"] != NO_ADDRESS) & ~ly_df["loc"].str.match(ROAD_RE)]
    loc_ly = _rank(lc.groupby("loc")["n"].sum())
    top_loc = loc_ly.iloc[:15]
    no_addr = float(ly_df.loc[ly_df["loc"].isin(["", NO_ADDRESS]), "n"].sum())
    roads = float(ly_df.loc[ly_df["loc"].str.match(ROAD_RE), "n"].sum())
    loc_py = (d[(d["y"] == py)].groupby("loc")["n"].sum() if py else pd.Series(dtype=float))
    chart_loc = {"x": [str(s) for s in top_loc.index], "y": [_i(v) for v in top_loc]}
    tbl_loc = []
    for s, v in top_loc.items():
        p = float(loc_py.get(s, 0.0))
        tbl_loc.append([str(s), fmt.int_he(v), fmt.pct(v / ly_total),
                        fmt.signed_pct((v - p) / p) if p >= 50 else "–"])

    # ── year to date (partial year) ──────────────────────────────────────
    ytd = None
    if partial and p_months:
        k = len(p_months)
        rows = []
        for y in years:
            sub = d[(d["y"] == y) & d["m"].isin(p_months)]
            if sub["m"].nunique() == k:
                rows.append((y, float(sub["n"].sum())))
        if len(rows) >= 2:
            span = (fmt.MONTHS_HE[p_months[0] - 1] if k == 1
                    else f"{fmt.MONTHS_HE[p_months[0] - 1]} עד {fmt.MONTHS_HE[p_months[-1] - 1]}")
            ytd = {"span": span, "k": k, "x": [str(r[0]) for r in rows], "y": [_i(r[1]) for r in rows],
                   "rows": [[str(r[0]), fmt.int_he(r[1])] for r in reversed(rows)]}
            prev = [r for r in rows if r[0] == partial - 1]
            ytd["cur"] = rows[-1][1]
            ytd["prev"] = prev[0][1] if prev else None
            ytd["record"] = rows[-1][1] >= max(r[1] for r in rows)

    # ── KPIs ─────────────────────────────────────────────────────────────
    days = 366 if calendar.isleap(ly) else 365
    top_dom_ly = float(ly_df.loc[ly_df["dom"] == top_dom, "n"].sum())
    kpis = {
        "ly_total": {"value": _i(ly_total), "display": fmt.int_he(ly_total), "tone": "brand"},
        "per_day": {"value": round(ly_total / days, 1), "display": fmt.int_he(ly_total / days), "tone": "brand"},
        "all_total": {"value": _i(total_all), "display": fmt.int_he(total_all), "tone": "brand"},
        "span": {"value": years[-1] - first, "display": f"{first}–{years[-1]}", "tone": "brand"},
        "top_dom_share": {"value": _pct1(top_dom_ly / ly_total), "display": fmt.pct(top_dom_ly / ly_total),
                          "tone": "info"},
        "top_dist_share": {"value": _pct1(dist_ly.iloc[0] / ly_total),
                           "display": fmt.pct(dist_ly.iloc[0] / ly_total), "tone": "brand"},
    }
    if py_total:
        ch = (ly_total - py_total) / py_total
        kpis["yoy"] = {"value": _pct1(ch), "display": fmt.signed_pct(ch),
                       "tone": "warn" if ch > 0.05 else ("ok" if ch < -0.05 else "brand")}
    if ytd and ytd["prev"]:
        ch = (ytd["cur"] - ytd["prev"]) / ytd["prev"]
        kpis["ytd"] = {"value": _pct1(ch), "display": fmt.signed_pct(ch),
                       "tone": "warn" if ch > 0.05 else ("ok" if ch < -0.05 else "brand")}

    # ── partial-data wording ─────────────────────────────────────────────
    dip_parts = []
    for y in sorted({t[0] for t in dips}):
        dip_parts.append(f"{fmt.join_he([fmt.MONTHS_HE[t[1] - 1] for t in dips if t[0] == y])} {y}")
    dip_months = fmt.join_he(dip_parts)

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def i_trend():
        if not py_total:
            return None
        ch = (ly_total - py_total) / py_total
        word = ("עלייה" if ch > TREND_EPS else "ירידה" if ch < -TREND_EPS else "יציבות")
        s = (f"ב-{ly} טיפלו כבאות והצלה ב-{fmt.int_he(ly_total)} אירועים, {word} של "
             f"{fmt.pct(abs(ch))} לעומת {py} ({fmt.int_he(py_total)})."
             if word != "יציבות" else
             f"ב-{ly} טיפלו כבאות והצלה ב-{fmt.int_he(ly_total)} אירועים, כמעט כמו ב-{py} "
             f"({fmt.int_he(py_total)}, שינוי של {fmt.signed_pct(ch)}).")
        c0 = complete[0]
        if c0 <= ly - 5 and yearly[c0] > 0:
            r = ly_total / float(yearly[c0])
            if r >= 1.2:
                s += f" זה פי {fmt.num_he(r)} ממספר האירועים ב-{c0} ({fmt.int_he(yearly[c0])})."
            elif r <= 0.85:
                s += f" זה {fmt.pct(1 - r)} פחות מאשר ב-{c0} ({fmt.int_he(yearly[c0])})."
        return s

    def i_ytd():
        if not ytd or not ytd["prev"]:
            return None
        ch = (ytd["cur"] - ytd["prev"]) / ytd["prev"]
        s = (f"נתוני {partial} חלקיים ({ytd['span']}): {fmt.int_he(ytd['cur'])} אירועים, "
             f"{fmt.signed_pct(ch)} לעומת אותם חודשים ב-{partial - 1} ({fmt.int_he(ytd['prev'])})")
        if ytd["record"] and len(ytd["y"]) >= 3:
            s += f", המספר הגבוה ביותר לתקופה זו בכל השנים מאז {ytd['x'][0]}"
        return s + "."

    def i_domain():
        share = float(ly_df.loc[ly_df["dom"] == top_dom, "n"].sum()) / ly_total
        if share < 0.3:
            return None
        sub = _rank(ly_df[ly_df["dom"] == top_dom].groupby("typ")["n"].sum())
        tot = float(sub.sum())
        s = f"התחום \"{top_dom}\" הוא המרכזי: {fmt.pct(share)} מהאירועים ב-{ly}"
        if len(sub) >= 2 and tot:
            s += (f". מתוכם {fmt.pct(sub.iloc[0] / tot)} מסוג \"{sub.index[0]}\" "
                  f"ו-{fmt.pct(sub.iloc[1] / tot)} מסוג \"{sub.index[1]}\"")
        return s + "."

    def i_district():
        if len(dist_ly) < 2:
            return None
        lead, v = str(dist_ly.index[0]), float(dist_ly.iloc[0])
        s = f"מחוז {lead} רשם את מספר האירועים הגבוה ביותר ב-{ly}: {fmt.int_he(v)} ({fmt.pct(v / ly_total)} מהכלל)"
        if growth and len(growth["x"]) >= 3:
            g0, p0 = growth["x"][0], growth["pct"][0]
            gl, pl = growth["x"][-1], growth["pct"][-1]
            if p0 - pl >= 15 and p0 > 0:
                s += (f". בין {growth['base']} ל-{ly} גדל מספר האירועים מהר ביותר במחוז {g0} "
                      f"({fmt.signed_pct(p0 / 100)})")
                if pl < 0:
                    s += f", ובמחוז {gl} הוא ירד ({fmt.signed_pct(pl / 100)})"
                else:
                    s += f" ולאט ביותר במחוז {gl} ({fmt.signed_pct(pl / 100)})"
        return s + "."

    def i_season():
        if not season_best or season_best[0] < 1.5:
            return None
        ratio, c, hi_m, hi, lo_m, lo = season_best
        return (f"עונתיות חדה באירועי \"{c}\": בממוצע {fmt.int_he(hi)} אירועים ב{fmt.MONTHS_HE[hi_m]} "
                f"לעומת {fmt.int_he(lo)} ב{fmt.MONTHS_HE[lo_m]}, פי {fmt.num_he(ratio)} "
                f"(ממוצע {season_span}).")

    def i_mover():
        if not mover:
            return None
        s, a, b = mover
        return (f"התרחיש שגדל יותר מכל תרחיש אחר ב-{ly}: \"{s}\", {fmt.int_he(a)} אירועים לעומת "
                f"{fmt.int_he(b)} ב-{py} ({fmt.signed_pct((a - b) / b)}).")

    def i_dip():
        if not dips:
            return None
        v = sum(t[2] for t in dips)
        base = sum(t[3] for t in dips)
        if len(dips) == 1:
            return (f"ב{dip_months} נרשמו {fmt.int_he(v)} אירועים, {fmt.pct(v / base, 0)} "
                    f"מהחציון החודשי של שנים-עשר החודשים שקדמו לו ({fmt.int_he(base)}).")
        return (f"ב{dip_months} נרשמו יחד {fmt.int_he(v)} אירועים, {fmt.pct(v / base, 0)} "
                f"מהחציון החודשי של שנים-עשר החודשים שקדמו לכל אחד מהם "
                f"({fmt.int_he(base / len(dips))} בחודש בממוצע).")

    def i_loc():
        if len(top_loc) < 3:
            return None
        n3 = float(top_loc.iloc[:3].sum())
        return (f"היישובים עם מספר האירועים הגבוה ביותר ב-{ly}: "
                f"{fmt.join_he([f'{k} ({fmt.int_he(v)})' for k, v in top_loc.iloc[:3].items()])}, "
                f"יחד {fmt.pct(n3 / ly_total)} מכלל האירועים.")

    add("trend", i_trend())
    add("ytd", i_ytd())
    add("domain", i_domain())
    add("district", i_district())
    add("season", i_season())
    add("mover", i_mover())
    add("dip", i_dip())
    add("loc", i_loc())

    # ── text ─────────────────────────────────────────────────────────────
    yoy_txt = ""
    if py_total:
        yoy_txt = f" ({fmt.signed_pct((ly_total - py_total) / py_total)} לעומת {py})"
    lede = (f"כמה אירועים טיפלו כבאות והצלה לישראל בכל חודש, מחוז ותחום, מ-{first} ועד "
            f"{fmt.MONTHS_HE[seq[-1][1] - 1]} {seq[-1][0]}: {fmt.int_he(total_all)} אירועים בסך הכל. "
            f"ב-{ly} נרשמו {fmt.int_he(ly_total)} אירועים{yoy_txt}, כ-{fmt.int_he(ly_total / days)} ביום. "
            f"התחומים: {fmt.join_he(keep_dom)}.")
    summary = (f"אירועי כבאות והצלה בישראל לפי שנה, חודש, מחוז, תחום ותרחיש, {first} עד {years[-1]}: "
               f"{fmt.int_he(ly_total)} אירועים ב-{ly}{yoy_txt}, "
               f"{fmt.pct(float(ly_df.loc[ly_df['dom'] == top_dom, 'n'].sum()) / ly_total, 0)} מהם {top_dom}.")
    desc = (f"כמה שריפות, חילוצים ואירועי חומ\"ס היו בכל מחוז ויישוב: "
            f"{fmt.int_he(ly_total)} אירועי כבאות והצלה ב-{ly}{yoy_txt}. נתונים חודשיים מ-{first}.")

    peak_txt = f"{fmt.MONTHS_HE[peak_ym[1] - 1]} {peak_ym[0]}"
    labels = {
        "lede": lede,
        "kpi_ly_total": f"אירועים ב-{ly}",
        "kpi_yoy": f"שינוי ב-{ly} לעומת {py}" if py else "",
        "kpi_ytd": (f"שינוי ב-{partial} ({ytd['span']}) לעומת אותה תקופה ב-{partial - 1}"
                    if ytd and ytd["prev"] else ""),
        "kpi_per_day": f"אירועים ביום בממוצע ב-{ly}",
        "kpi_top_dom": f"חלק תחום \"{top_dom}\" מכלל האירועים ב-{ly}",
        "kpi_top_dist": f"חלק מחוז {dist_ly.index[0]} מהאירועים ב-{ly}",
        "kpi_all": f"אירועים מאז {first}",
        "kpi_span": "שנות נתונים",
        "years_note": (f"מספר האירועים בכל שנה לפי תחום. השנה החלשה והחזקה בסדרה: "
                       f"{min(complete, key=lambda y: (yearly[y], y))} ({fmt.int_he(min(yearly[y] for y in complete))}) ו-"
                       f"{max(complete, key=lambda y: (yearly[y], -y))} ({fmt.int_he(max(yearly[y] for y in complete))})"
                       + (f". {partial} מכילה רק {len(p_months)} חודשים." if partial else ".")),
        "years_aria": (f"גרף עמודות מוערמות: אירועי כבאות והצלה לפי שנה ותחום, {first} עד {years[-1]}. "
                       f"ב-{ly} נרשמו {fmt.int_he(ly_total)} אירועים."),
        "years_caption": f"אירועים לפי שנה ותחום, {first} עד {years[-1]}",
        "heat_note": (f"כל משבצת היא חודש אחד. החודש העמוס ביותר בסדרה: {peak_txt} "
                      f"עם {fmt.int_he(peak_ym[2])} אירועים. המספרים במשבצות הם באלפי אירועים."),
        "heat_aria": (f"מפת חום של מספר האירועים לפי חודש ושנה, {first} עד {years[-1]}. "
                      f"השיא: {peak_txt}, {fmt.int_he(peak_ym[2])} אירועים."),
        "season_note": (f"ממוצע האירועים בכל חודש בשנה, {season_span}, לחמשת צירופי התחום והסוג "
                        f"הנפוצים ב-{ly}."),
        "season_aria": (f"גרף קווים: ממוצע אירועים לפי חודש בשנה לחמשת סוגי האירועים הנפוצים, {season_span}."),
        "season_caption": f"ממוצע אירועים לפי חודש וסוג, {season_span}",
        "types_head": f"אירועי {top_dom} לפי סוג",
        "types_note": (f"התחום הגדול ביותר, {top_dom}, מפוצל לפי מתאר האירוע בכל שנה מלאה, {complete[0]} עד {ly}."
                       + (f" {partial} אינה מוצגת כי נתוניה חלקיים." if partial else "")),
        "types_aria": f"גרף שטח מוערם: אירועי {top_dom} לפי סוג ושנה, {complete[0]} עד {ly}.",
        "types_caption": f"אירועי {top_dom} לפי סוג ושנה",
        "dist_note": (f"מספר האירועים בכל מחוז בשנים המלאות {complete[0]} עד {ly}. "
                      f"מוצגים המחוזות שרשמו אירועים ב-{ly}."),
        "dist_aria": (f"גרף קווים: אירועים לפי מחוז ושנה. ב-{ly} הוביל מחוז {dist_ly.index[0]} "
                      f"עם {fmt.int_he(dist_ly.iloc[0])} אירועים."),
        "dist_caption": f"אירועים לפי מחוז ושנה, {complete[0]} עד {ly}",
        "mix_note": f"התפלגות האירועים בכל מחוז לפי תחום ב-{ly} (אחוז מאירועי המחוז).",
        "mix_aria": f"גרף עמודות 100%: תמהיל התחומים בכל מחוז ב-{ly}.",
        "mix_caption": f"אירועים ותמהיל תחומים לפי מחוז, {ly}",
        "growth_note": (f"השינוי במספר האירועים בכל מחוז בין {growth['base']} ל-{ly}"
                        + (f". בכלל הארץ: {fmt.signed_pct(growth['total_pct'])}." if growth.get("total_pct") is not None else ".")
                        if growth else ""),
        "growth_aria": (f"גרף עמודות: שינוי באחוזים במספר האירועים לפי מחוז, {growth['base']} מול {ly}."
                        if growth else ""),
        "growth_caption": (f"אירועים לפי מחוז, {growth['base']} מול {ly}" if growth else ""),
        "growth_head": (f"קצב הגידול לפי מחוז, {growth['base']} מול {ly}" if growth else ""),
        "scen_note": (f"שנים-עשר התרחישים הנפוצים ב-{ly}. סיווג התרחישים השתנה במהלך השנים, "
                      f"ולכן השינוי מוצג רק לעומת {py}." if py else
                      f"שנים-עשר התרחישים הנפוצים ב-{ly}."),
        "scen_aria": (f"גרף עמודות אופקי: התרחישים הנפוצים ב-{ly}. בראש: {chart_scen['x'][0]} עם "
                      f"{fmt.int_he(chart_scen['y'][0])} אירועים." if chart_scen["x"] else ""),
        "scen_caption": f"התרחישים הנפוצים ב-{ly}",
        "domtypes_note": (f"חמשת התרחישים הנפוצים בכל תחום ב-{ly}, והשאר מקובצים ב\"אחר\". "
                           + " ".join(f"בתחום \"{g}\" מוביל \"{k}\" ({fmt.pct(sh)} מאירועי התחום)."
                                      for g, k, sh in dom_type_leads[:3])),
        "domtypes_aria": (f"גרפי עמודות אופקיים: התרחישים הנפוצים בכל תחום ב-{ly}."),
        "domtypes_caption": f"התרחישים הנפוצים בכל תחום, {ly}",
        "loc_note": (f"היישובים שבהם נרשמו הכי הרבה אירועים ב-{ly}. לא נכללו "
                     f"{fmt.int_he(no_addr)} אירועים ללא כתובת ו-{fmt.int_he(roads)} אירועים בכבישים ובצמתים. "
                     f"המספרים מוחלטים ואינם מנורמלים לגודל האוכלוסייה."),
        "loc_aria": (f"גרף עמודות אופקי: היישובים עם הכי הרבה אירועי כבאות והצלה ב-{ly}. בראש: "
                     f"{chart_loc['x'][0]} עם {fmt.int_he(chart_loc['y'][0])} אירועים." if chart_loc["x"] else ""),
        "loc_caption": f"היישובים עם הכי הרבה אירועים ב-{ly}",
        "ytd_head": (f"{partial} עד כה: {ytd['span']} בכל שנה" if ytd else ""),
        "ytd_note": (f"נתוני {partial} חלקיים, ולכן הם מושווים לאותם חודשים ({ytd['span']}) בשנים קודמות."
                     if ytd else ""),
        "ytd_aria": (f"גרף עמודות: אירועים ב{ytd['span']} בכל שנה, {ytd['x'][0]} עד {partial}." if ytd else ""),
        "ytd_caption": (f"אירועים ב{ytd['span']} לפי שנה" if ytd else ""),
    }

    tables = {
        "years": tbl_years, "years_cols": ["שנה", "סך הכל"] + dom_labels,
        "season": tbl_season, "season_cols": ["חודש"] + combos,
        "types": tbl_types, "types_cols": ["שנה"] + typ_labels,
        "dist_years": tbl_dist_years, "dist_years_cols": ["שנה"] + dists,
        "dist_mix": tbl_dist_mix,
        "dist_mix_cols": ["מחוז", "אירועים", "מכלל הארץ"] + [f"{g} (%)" for g in dom_labels],
        "scen": tbl_scen, "loc": tbl_loc, "dom_types": tbl_dom_types,
        "growth": growth["rows"] if growth else [],
        "growth_cols": ["מחוז", str(growth["base"]), str(ly), "שינוי"] if growth else [],
        "ytd": ytd["rows"] if ytd else [],
    }

    charts = {
        "years": chart_years, "heat": heat, "season": season, "types": chart_types,
        "dist_years": chart_dist_years, "dist_mix": chart_dist_mix,
        "growth": {"x": growth["x"], "pct": growth["pct"]} if growth else None,
        "scen": chart_scen, "loc": chart_loc, "dom_types": panels,
        "ytd": {"x": ytd["x"], "y": ytd["y"]} if ytd else None,
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first}/{years[-1]}",
            "spatial_coverage": "ישראל, לפי מחוזות כבאות והצלה",
            "seo": {
                "title": "סטטיסטיקת שריפות ואירועי כבאות והצלה לפי מחוז",
                "description": desc,
                "name": "אירועי כבאות והצלה לפי מחוז",
                "alternate_names": [
                    "אירועים לפי מחוז",
                    "נתוני שריפות בישראל",
                    "מספר שריפות בשנה",
                    "סטטיסטיקה כבאות והצלה",
                    "אירועי כיבוי אש וחילוץ",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {
            "yoy": "yoy" in kpis, "ytd": "ytd" in kpis,
            "growth": bool(growth), "ytd_chart": bool(ytd),
            "scen": bool(chart_scen["x"]), "loc": bool(chart_loc["x"]), "dom_types": bool(panels),
        },
    }
