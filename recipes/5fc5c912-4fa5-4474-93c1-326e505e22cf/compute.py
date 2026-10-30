"""מפל"ס (PRTR): facilities reporting to the pollutant release and transfer register.

One row per environmental site per reporting year. Every number on the page is
computed here; insight rules return a Hebrew sentence or None when their premise
does not hold in the data.
"""

import pandas as pd

HAZ_T = "SachTipulPsoletMesukenet"      # hazardous waste sent to treatment (tons)
HAZ_D = "SachSilukPsoletMesukenet"      # hazardous waste sent to disposal (tons)
NON_T = "SachTipulPsoletLoMesukenet"    # non-hazardous waste sent to treatment (tons)
NON_D = "SachSilukPsoletLoMesukenet"    # non-hazardous waste sent to disposal (tons)
WASTE = [HAZ_T, HAZ_D, NON_T, NON_D]

MISSING = {"", "(חסר)", "0", "-"}
TOP_N = 12
SECTOR_N = 8


def _fmt(v):
    return f"{int(round(v)):,}"


def _pct(v, d=1):
    return f"{v * 100:.{d}f}%"


def _clean(s):
    return s.astype(str).str.replace(r"\s+", " ", regex=True).str.strip()


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def _ranked(series):
    """Counts/sums sorted desc with a name tie-break (row-order independent)."""
    s = series.sort_index()
    return s.sort_values(ascending=False, kind="stable")


def _prepare(df):
    df = df.copy()
    key_year = df["MisparAtarSvivatiAndShnatDivuach"].astype(str).str.extract(r"-(\d{4})\s*$")[0]
    year_col = df["ShnatDivuach"].astype(str).str.strip()
    # A well-formed row has a four-digit ShnatDivuach that matches the key's year.
    # Rows whose columns are shifted (the year cell holds a date) are excluded.
    ok = year_col.str.fullmatch(r"\d{4}") & (year_col == key_year)
    bad = int((~ok).sum())
    df = df[ok].copy()
    df["year"] = df["ShnatDivuach"].astype(str).str.strip().astype(int)
    df["site"] = _clean(df["MisparAtarSvivati"])
    df["site_name"] = _clean(df["ShemAtarSvivatiMenifa"])
    df["company"] = _clean(df["ShemTaagidShutfut"])
    df["company_id"] = _clean(df["MisparTaagidShutfutMenifa"])
    df["sector"] = _clean(df["AnafAtarSvivati"]).replace("", "לא צוין")
    df["field"] = _clean(df["TchumPeilutAtarSvivati"]).replace("", "לא צוין")
    df["district"] = _clean(df["MachozAtarSvivati"]).replace("", "לא צוין")
    df["authority"] = _clean(df["RashutMekomitAtarSvivati"]).replace("", "לא צוין")
    df["ww_type"] = _clean(df["SugTipulBeshfachim"])
    df["ww_dest"] = _clean(df["YaadHashfachim"])
    for c in WASTE:
        v = _num(df[c])
        df[c] = v.where(v >= 0)
    df["has_waste"] = df[WASTE].notna().all(axis=1)
    df["sub"] = pd.to_datetime(df["TaarichDivuahBefoal"].astype(str).str.strip(),
                               format="%d/%m/%Y", errors="coerce")
    df = df[df["site"] != ""]
    return df, bad


def _cap(series, n, other_label):
    s = _ranked(series)
    if len(s) <= n:
        return s
    head = s.iloc[:n - 1]
    rest = s.iloc[n - 1:].sum()
    return pd.concat([head, pd.Series({other_label: rest})])


def _dest_group(v):
    if 'מט"ש' in v or "מט״ש" in v or "מט''ש" in v:
        return 'מתקן טיהור שפכים (מט"ש)'
    if v.startswith("מאגר"):
        return "מאגר"
    return v


# ---------------------------------------------------------------- insights

def insight_treat_share(share_by_year, years_full):
    ys = [y for y in years_full if share_by_year.get(y) is not None]
    if len(ys) < 3:
        return None
    y0, y1 = ys[0], ys[-1]
    a, b = share_by_year[y0], share_by_year[y1]
    diff = b - a
    if abs(diff) < 0.05:
        return (f"שיעור הפסולת המסוכנת שנשלחה לטיפול (ולא לסילוק) יציב יחסית: "
                f"{_pct(a)} ב-{y0} ו-{_pct(b)} ב-{y1}.")
    word = "עלה" if diff > 0 else "ירד"
    return (f"שיעור הפסולת המסוכנת שהמפעלים העבירו לטיפול ולא לסילוק {word} "
            f"מ-{_pct(a)} ב-{y0} ל-{_pct(b)} ב-{y1}.")


def insight_haz_disposal(haz_d, years_full):
    vals = {y: haz_d[y] for y in years_full if y in haz_d}
    if len(vals) < 3:
        return None
    peak_y = max(sorted(vals), key=lambda y: vals[y])
    last_y = max(vals)
    if peak_y == last_y or vals[peak_y] <= 0:
        return None
    drop = 1 - vals[last_y] / vals[peak_y]
    if drop < 0.15:
        return None
    return (f"כמות הפסולת המסוכנת שהועברה לסילוק ירדה ב-{_pct(drop, 0)}: "
            f"מ-{_fmt(vals[peak_y])} טון בשנת השיא {peak_y} ל-{_fmt(vals[last_y])} טון ב-{last_y}.")


def insight_nonhaz(non_total, years_full):
    vals = {y: non_total[y] for y in years_full if y in non_total}
    if len(vals) < 3:
        return None
    y0, y1 = min(vals), max(vals)
    if vals[y0] <= 0:
        return None
    ch = vals[y1] / vals[y0] - 1
    if abs(ch) < 0.1:
        return None
    word = "גדלה" if ch > 0 else "קטנה"
    return (f"כמות הפסולת שאינה מסוכנת שהמפעלים העבירו {word} ב-{_pct(abs(ch), 0)} "
            f"בין {y0} ל-{y1}: מ-{vals[y0] / 1e6:.1f} ל-{vals[y1] / 1e6:.1f} מיליון טון בשנה.")


def insight_sector_gap(sector_rows):
    best = None
    for r in sector_rows:
        if r["site_share"] >= 0.1 and r["haz_share"] < r["site_share"] / 3:
            gap = r["site_share"] - r["haz_share"]
            if best is None or gap > best[0]:
                best = (gap, r)
    if not best:
        return None
    r = best[1]
    if r["haz_share"] < 0.001:
        tail = "אך פחות מ-0.1% מהפסולת המסוכנת שהועברה."
    else:
        tail = f"אך רק {_pct(r['haz_share'])} מהפסולת המסוכנת שהועברה."
    return f"ענף {r['name']} מהווה {_pct(r['site_share'])} מהאתרים המדווחים ב-{r['year']}, {tail}"


def insight_concentration(top_share, n_top, n_with, year):
    if top_share is None or top_share < 0.4:
        return None
    return (f"הפסולת המסוכנת מרוכזת: {n_top} האתרים המובילים אחראים ל-{_pct(top_share, 0)} "
            f"מכלל הפסולת המסוכנת שהועברה ב-{year}, מתוך {n_with:,} אתרים שדיווחו על פסולת כזו.")


def insight_spike(df_ok, years_full):
    """Peak year of hazardous treatment, if one site drives a big part of it."""
    g = df_ok[df_ok["year"].isin(years_full)].groupby("year")[HAZ_T].sum().sort_index()
    if len(g) < 3:
        return None
    peak_y = int(g.idxmax())
    rest = g.drop(peak_y)
    if rest.median() <= 0 or g[peak_y] < 1.3 * rest.median():
        return None
    sub = df_ok[df_ok["year"] == peak_y].sort_values(["site"], kind="stable")
    by_site = _ranked(sub.groupby("site_name")[HAZ_T].sum())
    if by_site.empty or g[peak_y] <= 0:
        return None
    name, v = by_site.index[0], by_site.iloc[0]
    share = v / g[peak_y]
    if share < 0.3:
        return None
    return (f"שנת {peak_y} בולטת בשיא של {_fmt(g[peak_y])} טון פסולת מסוכנת לטיפול; "
            f"{_pct(share, 0)} מהם דווחו על ידי אתר אחד, {name}.")


def insight_panel(site_years, n_years, y0, y1, n_sites):
    if n_years < 4:
        return None
    full = int((site_years == n_years).sum())
    if full == 0:
        return None
    return (f"{full:,} מתוך {n_sites:,} האתרים שדיווחו אי פעם הגישו דיווח בכל {n_years} "
            f"השנים מ-{y0} עד {y1}.")


def insight_district(dist, year):
    total = dist.sum()
    if total == 0 or len(dist) < 2:
        return None
    a, b = dist.index[0], dist.index[1]
    sa, sb = dist.iloc[0] / total, dist.iloc[1] / total
    if sa < 0.25:
        return None
    return (f"מחוז {a} מוביל ב-{year} עם {int(dist.iloc[0]):,} אתרים ({_pct(sa, 0)}), "
            f"ואחריו מחוז {b} עם {int(dist.iloc[1]):,} ({_pct(sb, 0)}).")


def insight_partial(partial, latest, n_latest, ref, n_ref):
    if not partial:
        return None
    return (f"הדיווחים על {latest} עדיין מתקבלים: עד כה הוגשו {n_latest:,} דיווחים, "
            f"לעומת {n_ref:,} על {ref}. הפילוחים בעמוד מתייחסים לשנת {ref}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df, bad = _prepare(frames["sites"])
    years = sorted(int(y) for y in df["year"].unique())
    y0, latest = years[0], years[-1]
    sites_per_year = df.groupby("year")["site"].nunique().sort_index()

    # Partial latest year: far fewer reports than the previous full years.
    partial = False
    if len(years) >= 3:
        prev = sites_per_year.loc[years[-4:-1]].median()
        partial = sites_per_year[latest] < 0.8 * prev
    ref = years[-2] if partial else latest
    years_full = [y for y in years if y <= ref]
    R = df[df["year"] == ref]
    n_ref = int(R["site"].nunique())

    # ---- yearly sites, new entrants, drop-outs
    seen = set()
    by_year_sets = {y: set(df.loc[df["year"] == y, "site"]) for y in years}
    new_s, gone_s = [], []
    for i, y in enumerate(years):
        s = by_year_sets[y]
        new_s.append(None if i == 0 else len(s - seen))
        if i == 0 or (partial and y == latest):
            gone_s.append(None)
        else:
            gone_s.append(len(by_year_sets[years[i - 1]] - s))
        seen |= s
    yr_labels = [str(y) for y in years]
    chart_years = {"x": yr_labels, "sites": [int(sites_per_year[y]) for y in years],
                   "new": new_s, "gone": gone_s}
    tbl_years = [{"year": str(y), "sites": f"{int(sites_per_year[y]):,}",
                  "new": "" if n is None else f"{n:,}", "gone": "" if g is None else f"{g:,}"}
                 for y, n, g in zip(years, new_s, gone_s)]
    site_years = df[df["year"].isin(years_full)].groupby("site")["year"].nunique()
    n_sites_all = int(df["site"].nunique())

    # ---- waste by year
    W = df[df["has_waste"]]
    wy = W.groupby("year")[WASTE].sum().sort_index()
    no_waste = int((~df["has_waste"]).sum())
    share_by_year = {}
    haz, non = [], []
    tbl_waste = []
    for y in years:
        if y in wy.index:
            r = wy.loc[y]
            ht, hd, nt, nd = (float(r[c]) for c in WASTE)
        else:
            ht = hd = nt = nd = 0.0
        hs = ht / (ht + hd) if ht + hd > 0 else None
        ns = nt / (nt + nd) if nt + nd > 0 else None
        share_by_year[y] = hs
        haz.append([round(ht), round(hd), None if hs is None else round(hs * 100, 1)])
        non.append([round(nt), round(nd), None if ns is None else round(ns * 100, 1)])
        tbl_waste.append({"year": str(y), "ht": _fmt(ht), "hd": _fmt(hd), "hs": "" if hs is None else _pct(hs),
                          "nt": _fmt(nt), "nd": _fmt(nd), "ns": "" if ns is None else _pct(ns)})
    chart_haz = {"x": yr_labels, "treat": [h[0] for h in haz], "disp": [h[1] for h in haz],
                 "share": [h[2] for h in haz]}
    chart_non = {"x": yr_labels, "treat": [h[0] for h in non], "disp": [h[1] for h in non],
                 "share": [h[2] for h in non]}

    # ---- sectors in ref year
    RW = R[R["has_waste"]]
    sec_sites = _ranked(R.groupby("sector")["site"].nunique())
    sec_haz = RW.groupby("sector")[[HAZ_T, HAZ_D]].sum().sum(axis=1)
    sec_non = RW.groupby("sector")[[NON_T, NON_D]].sum().sum(axis=1)
    tot_haz = float(sec_haz.sum())
    tot_non = float(sec_non.sum())
    sector_rows = []
    for name, cnt in sec_sites.items():
        h = float(sec_haz.get(name, 0.0))
        nn = float(sec_non.get(name, 0.0))
        sector_rows.append({
            "name": name, "year": ref, "sites": int(cnt),
            "site_share": cnt / n_ref if n_ref else 0.0,
            "haz": h, "haz_share": h / tot_haz if tot_haz else 0.0,
            "non": nn, "non_share": nn / tot_non if tot_non else 0.0,
        })
    chart_sector = {
        "names": [r["name"] for r in sector_rows],
        "sites": [round(r["site_share"] * 100, 1) for r in sector_rows],
        "haz": [round(r["haz_share"] * 100, 1) for r in sector_rows],
        "non": [round(r["non_share"] * 100, 1) for r in sector_rows],
    }
    tbl_sector = [{"name": r["name"], "sites": f"{r['sites']:,}", "site_share": _pct(r["site_share"]),
                   "haz": _fmt(r["haz"]), "haz_share": _pct(r["haz_share"]),
                   "non": _fmt(r["non"]), "non_share": _pct(r["non_share"])} for r in sector_rows]

    # ---- sector trend (sites per sector per year, top sectors overall)
    sec_all = _ranked(df.groupby("sector")["site"].nunique())
    keep = list(sec_all.index[:SECTOR_N - 1]) if len(sec_all) > SECTOR_N else list(sec_all.index)
    other_label = "ענפים נוספים"
    dd = df.assign(sec2=df["sector"].where(df["sector"].isin(keep), other_label))
    st = dd.groupby(["year", "sec2"])["site"].nunique().unstack(fill_value=0)
    cols = keep + ([other_label] if other_label in st.columns else [])
    st = st.reindex(index=years, columns=cols, fill_value=0)
    chart_sector_trend = {"x": yr_labels,
                          "series": [{"name": c, "data": [int(v) for v in st[c]]} for c in cols]}
    tbl_sector_trend = {"cols": cols,
                        "rows": [{"year": str(y), "vals": [f"{int(st.loc[y, c]):,}" for c in cols]}
                                 for y in years]}

    # ---- activity field (ref year)
    fld = _cap(R.groupby("field")["site"].nunique(), TOP_N, "תחומים נוספים")
    chart_field = {"names": list(fld.index), "values": [int(v) for v in fld.values]}
    tbl_field = [{"name": k, "count": f"{int(v):,}", "share": _pct(v / n_ref)} for k, v in fld.items()]

    # ---- districts + heat (ref year)
    dist = _ranked(R.groupby("district")["site"].nunique())
    chart_dist = {"names": list(dist.index), "values": [int(v) for v in dist.values]}
    tbl_dist = [{"name": k, "count": f"{int(v):,}", "share": _pct(v / n_ref)} for k, v in dist.items()]
    heat_secs = list(sec_sites.index)
    heat_d = list(dist.index)
    hx = R.groupby(["district", "sector"])["site"].nunique()
    cells = []
    for xi, dname in enumerate(heat_d):
        for yi, sname in enumerate(heat_secs):
            cells.append([xi, yi, int(hx.get((dname, sname), 0))])
    chart_heat = {"districts": heat_d, "sectors": heat_secs, "cells": cells,
                  "max": max([c[2] for c in cells] + [1])}

    # ---- local authorities (ref year)
    auth = _ranked(R.groupby("authority")["site"].nunique()).iloc[:TOP_N]
    chart_auth = {"names": list(auth.index), "values": [int(v) for v in auth.values]}
    tbl_auth = [{"name": k, "count": f"{int(v):,}", "share": _pct(v / n_ref)} for k, v in auth.items()]

    # ---- companies (ref year), unnamed excluded
    RC = R[~R["company"].isin(MISSING)]
    n_comp = int(R.loc[~R["company_id"].isin(MISSING), "company_id"].nunique())
    comp = _ranked(RC.groupby("company")["site"].nunique()).iloc[:10]
    chart_comp = {"names": list(comp.index), "values": [int(v) for v in comp.values]}
    tbl_comp = [{"name": k, "count": f"{int(v):,}"} for k, v in comp.items()]
    n_unnamed = int(R.loc[R["company"].isin(MISSING), "site"].nunique())

    # ---- top sites by waste (ref year)
    RW2 = RW.assign(nm=RW["site_name"].where(RW["site_name"] != "", RW["company"]))
    sh = _ranked(RW2.groupby("nm")[[HAZ_T, HAZ_D]].sum().sum(axis=1))
    sh = sh[sh > 0]
    sn = _ranked(RW2.groupby("nm")[[NON_T, NON_D]].sum().sum(axis=1))
    sn = sn[sn > 0]
    top_h, top_n = sh.iloc[:10], sn.iloc[:10]
    chart_top_haz = {"names": list(top_h.index), "values": [round(float(v)) for v in top_h.values]}
    chart_top_non = {"names": list(top_n.index), "values": [round(float(v)) for v in top_n.values]}
    tbl_top_haz = [{"name": k, "tons": _fmt(v), "share": _pct(v / tot_haz) if tot_haz else ""}
                   for k, v in top_h.items()]
    tbl_top_non = [{"name": k, "tons": _fmt(v), "share": _pct(v / tot_non) if tot_non else ""}
                   for k, v in top_n.items()]
    top_haz_share = float(top_h.sum()) / tot_haz if tot_haz else None

    # ---- wastewater (ref year)
    wt = R[~R["ww_type"].isin(MISSING)]
    wtype = _cap(wt.groupby("ww_type")["site"].nunique(), 6, "סוגים נוספים")
    chart_wtype = {"names": list(wtype.index), "values": [int(v) for v in wtype.values]}
    tbl_wtype = [{"name": k, "count": f"{int(v):,}"} for k, v in wtype.items()]
    wd = R[~R["ww_dest"].isin(MISSING)].assign(g=lambda x: x["ww_dest"].map(_dest_group))
    wdest = _cap(wd.groupby("g")["site"].nunique(), 6, "יעדים נוספים")
    chart_wdest = {"names": list(wdest.index), "values": [int(v) for v in wdest.values]}
    tbl_wdest = [{"name": k, "count": f"{int(v):,}"} for k, v in wdest.items()]
    n_ww_known = int(wt["site"].nunique())

    # ---- submission timing (days after the reporting year's end)
    S = df.dropna(subset=["sub"]).copy()
    S["lag"] = (S["sub"] - pd.to_datetime(S["year"].astype(str) + "-12-31")).dt.days
    lag_med, lag_share, tbl_lag = [], [], []
    for y in years:
        s = S.loc[S["year"] == y, "lag"]
        if s.empty:
            lag_med.append(None)
            lag_share.append(None)
            tbl_lag.append({"year": str(y), "med": "", "share": ""})
            continue
        m = int(round(float(s.median())))
        sh_ = float((s <= 120).mean())
        lag_med.append(m)
        lag_share.append(round(sh_ * 100, 1))
        tbl_lag.append({"year": str(y), "med": f"{m:,}", "share": _pct(sh_)})
    chart_lag = {"x": yr_labels, "med": lag_med, "share": lag_share}

    # ---- KPIs
    ht_r, hd_r, nt_r, nd_r = (float(wy.loc[ref, c]) if ref in wy.index else 0.0 for c in WASTE)
    haz_r = ht_r + hd_r
    non_r = nt_r + nd_r
    share_r = share_by_year.get(ref)
    first_share = next((share_by_year[y] for y in years_full if share_by_year.get(y) is not None), None)
    tone_share = "brand"
    if share_r is not None and first_share is not None:
        if share_r - first_share >= 0.05:
            tone_share = "ok"
        elif first_share - share_r >= 0.05:
            tone_share = "danger"
    kpis = {
        "sites_ref": {"value": n_ref, "display": f"{n_ref:,}", "tone": "brand",
                      "label": f"אתרים שדיווחו על שנת {ref}"},
        "sites_all": {"value": n_sites_all, "display": f"{n_sites_all:,}", "tone": "info",
                      "label": f"אתרים שדיווחו לפחות פעם אחת ({y0} עד {latest})"},
        "companies": {"value": n_comp, "display": f"{n_comp:,}", "tone": "brand",
                      "label": f"חברות ותאגידים מדווחים ({ref})"},
        "haz": {"value": round(haz_r), "display": f"{haz_r / 1000:,.1f}", "tone": "brand",
                "label": f"פסולת מסוכנת שהועברה ב-{ref} (אלף טון)"},
        "non": {"value": round(non_r), "display": f"{non_r / 1e6:,.1f}", "tone": "brand",
                "label": f"פסולת שאינה מסוכנת שהועברה ב-{ref} (מיליון טון)"},
        "treat_share": {"value": None if share_r is None else round(share_r * 100, 1),
                        "display": "" if share_r is None else _pct(share_r), "tone": tone_share,
                        "label": f"מהפסולת המסוכנת נשלחה לטיפול ולא לסילוק ({ref})"},
    }
    kpi_order = ["sites_ref", "sites_all", "companies", "haz", "non", "treat_share"]
    if share_r is None:
        kpi_order.remove("treat_share")

    # ---- insights
    haz_d_by_year = {int(y): float(v) for y, v in wy[HAZ_D].items()}
    non_tot_by_year = {int(y): float(v) for y, v in (wy[NON_T] + wy[NON_D]).items()}
    n_haz_sites = int((RW[[HAZ_T, HAZ_D]].sum(axis=1) > 0).groupby(RW["site"]).any().sum())
    rules = [
        ("partial", insight_partial(partial, latest, int(sites_per_year[latest]), ref, n_ref)),
        ("treat_share", insight_treat_share(share_by_year, years_full)),
        ("haz_disposal", insight_haz_disposal(haz_d_by_year, years_full)),
        ("nonhaz", insight_nonhaz(non_tot_by_year, years_full)),
        ("sector_gap", insight_sector_gap(sector_rows)),
        ("concentration", insight_concentration(top_haz_share, len(top_h), n_haz_sites, ref)),
        ("spike", insight_spike(W, years_full)),
        ("panel", insight_panel(site_years, len(years_full), y0, ref, n_sites_all)),
        ("district", insight_district(dist, ref)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- labels / ledes
    lead_sec = sector_rows[0] if sector_rows else None
    lede = (f"מרשם הפליטות וההעברות לסביבה (מפל\"ס) מרכז את הדיווחים השנתיים שהמפעלים מגישים "
            f"למשרד להגנת הסביבה לפי חוק הגנת הסביבה (פליטות והעברות לסביבה). המאגר כולל "
            f"{len(df):,} דיווחים של {n_sites_all:,} אתרים על השנים {y0} עד {latest}: ענף, תחום "
            f"פעילות, מיקום, טיפול בשפכים וכמויות הפסולת המסוכנת ושאינה מסוכנת שהועברו לטיפול או לסילוק.")
    method_parts = []
    if bad:
        method_parts.append(f"{bad:,} רשומות שעמודותיהן מוזזות (שנת הדיווח מכילה תאריך) הוחרגו מכל החישובים.")
    if no_waste:
        method_parts.append(f"{no_waste:,} דיווחים ללא נתוני פסולת אינם נכללים בסיכומי הפסולת.")
    method_parts.append("כמויות הפסולת בטון, כפי שדווחו על ידי המפעלים עצמם.")

    yr_peak = max(years, key=lambda y: (sites_per_year[y], -y))
    total_new = sum(n for n in new_s if n)
    labels = {
        "lede": lede,
        "method_note": " ".join(method_parts),
        "map_note": (f"מיקומי {n_ref:,} האתרים שדיווחו על שנת {ref}. לחיצה על נקודה מציגה את שם האתר, "
                     f"החברה, תחום הפעילות והיישוב."),
        "map_aria": f"מפה אינטראקטיבית של האתרים שדיווחו למפל\"ס על שנת {ref}. גרסה נגישה: טבלת הנתונים בתחתית העמוד.",
        "years_lede": (f"מספר האתרים המדווחים נע בין {int(sites_per_year.min()):,} ל-{int(sites_per_year.max()):,} "
                       f"בשנה, עם שיא של {int(sites_per_year[yr_peak]):,} ב-{yr_peak}. מאז {y0} הצטרפו "
                       f"{total_new:,} אתרים חדשים."),
        "years_aria": (f"גרף עמודות: אתרים מדווחים לפי שנה, {y0} עד {latest}, עם אתרים חדשים ואתרים שלא דיווחו "
                       f"לעומת השנה הקודמת. ב-{ref} דיווחו {n_ref:,} אתרים."),
        "years_caption": "אתרים מדווחים, חדשים ושלא דיווחו לפי שנה",
        "haz_lede": ("" if share_r is None else
                     f"ב-{ref} דווח על {_fmt(haz_r)} טון פסולת מסוכנת שהועברה מהמפעלים, "
                     f"מהם {_pct(share_r)} לטיפול (מחזור, השבה או טיפול אחר) והשאר לסילוק."),
        "haz_aria": (f"גרף עמודות מוערמות: פסולת מסוכנת שהועברה לטיפול ולסילוק לפי שנה, בטון, עם קו שיעור "
                     f"הטיפול. ב-{ref}: {_fmt(haz_r)} טון."),
        "non_lede": (f"ב-{ref} דווח על {non_r / 1e6:,.1f} מיליון טון פסולת שאינה מסוכנת, "
                     f"מהם {_pct(nt_r / non_r) if non_r else '0%'} לטיפול."),
        "non_aria": (f"גרף עמודות מוערמות: פסולת שאינה מסוכנת שהועברה לטיפול ולסילוק לפי שנה, בטון. "
                     f"ב-{ref}: {_fmt(non_r)} טון."),
        "waste_caption": "פסולת מסוכנת ושאינה מסוכנת שהועברה לפי שנה, בטון",
        "sector_lede": ("" if not lead_sec else
                        f"ענף {lead_sec['name']} הוא הגדול במספר האתרים ב-{ref} ({_pct(lead_sec['site_share'])}). "
                        f"התרשים משווה את חלקו של כל ענף באתרים, בפסולת המסוכנת ובפסולת שאינה מסוכנת."),
        "sector_aria": (f"גרף עמודות: חלקו של כל ענף מתוך האתרים, הפסולת המסוכנת והפסולת שאינה מסוכנת ב-{ref}."
                        + ("" if not lead_sec else f" הענף הגדול: {lead_sec['name']}.")),
        "sector_caption": f"ענפים לפי אתרים ופסולת שהועברה, {ref}",
        "trend_aria": f"גרף שטח מוערם: אתרים מדווחים לפי ענף ושנה, {y0} עד {latest}.",
        "trend_caption": "אתרים מדווחים לפי ענף ושנה",
        "field_aria": (f"גרף עמודות אופקי: תחומי הפעילות הנפוצים ב-{ref}." +
                       ("" if fld.empty else f" המוביל: {fld.index[0]} עם {int(fld.iloc[0]):,} אתרים.")),
        "field_caption": f"אתרים לפי תחום פעילות, {ref}",
        "dist_aria": (f"גרף עמודות: אתרים מדווחים לפי מחוז ב-{ref}." +
                      ("" if dist.empty else f" המוביל: {dist.index[0]} עם {int(dist.iloc[0]):,} אתרים.")),
        "dist_caption": f"אתרים לפי מחוז, {ref}",
        "heat_aria": f"מפת חום: מספר האתרים לפי מחוז וענף ב-{ref}.",
        "auth_aria": (f"גרף עמודות אופקי: הרשויות המקומיות עם מספר האתרים המדווחים הגבוה ביותר ב-{ref}." +
                      ("" if auth.empty else f" המובילה: {auth.index[0]} עם {int(auth.iloc[0]):,} אתרים.")),
        "auth_caption": f"רשויות מקומיות מובילות לפי מספר אתרים, {ref}",
        "comp_lede": (f"{n_comp:,} חברות ותאגידים דיווחו על {n_ref:,} אתרים ב-{ref}. "
                      + ("" if comp.empty else f"{comp.index[0]} מפעילה את מספר האתרים הגדול ביותר ({int(comp.iloc[0]):,}).")
                      + ("" if not n_unnamed else f" {n_unnamed:,} אתרים ללא שם חברה אינם בדירוג.")),
        "comp_aria": (f"גרף עמודות אופקי: החברות עם מספר האתרים המדווחים הגבוה ביותר ב-{ref}." +
                      ("" if comp.empty else f" המובילה: {comp.index[0]}.")),
        "comp_caption": f"חברות לפי מספר אתרים מדווחים, {ref}",
        "top_haz_aria": (f"גרף עמודות אופקי: האתרים שהעבירו את כמות הפסולת המסוכנת הגדולה ביותר ב-{ref}, בטון." +
                         ("" if top_h.empty else f" המוביל: {top_h.index[0]}.")),
        "top_haz_caption": f"אתרים מובילים בפסולת מסוכנת שהועברה, {ref}",
        "top_non_aria": (f"גרף עמודות אופקי: האתרים שהעבירו את כמות הפסולת שאינה מסוכנת הגדולה ביותר ב-{ref}, בטון." +
                         ("" if top_n.empty else f" המוביל: {top_n.index[0]}.")),
        "top_non_caption": f"אתרים מובילים בפסולת שאינה מסוכנת שהועברה, {ref}",
        "top_lede": ("" if top_haz_share is None else
                     f"עשרת האתרים המובילים אחראים ל-{_pct(top_haz_share, 0)} מהפסולת המסוכנת שהועברה ב-{ref}."),
        "ww_lede": (f"{n_ww_known:,} מתוך {n_ref:,} האתרים ציינו ב-{ref} את סוג הטיפול בשפכים שלהם. "
                    f"אתרים בלי ערך או עם הערך (חסר) אינם בתרשימים."),
        "wtype_aria": f"גרף עמודות: אתרים לפי סוג הטיפול בשפכים ב-{ref}.",
        "wtype_caption": f"אתרים לפי סוג טיפול בשפכים, {ref}",
        "wdest_aria": f"גרף עמודות: אתרים לפי יעד השפכים ב-{ref}.",
        "wdest_caption": f"אתרים לפי יעד השפכים, {ref}",
        "lag_lede": ("" if lag_med[years.index(ref)] is None else
                     f"דיווח על שנת {ref} הוגש בחציון {lag_med[years.index(ref)]:,} ימים אחרי סוף השנה, "
                     f"ו-{lag_share[years.index(ref)]:.1f}% מהדיווחים הוגשו עד סוף אפריל."),
        "lag_aria": "גרף עמודות וקו: חציון הימים מסוף שנת הדיווח ועד הגשת הדיווח, ושיעור הדיווחים שהוגשו עד סוף אפריל, לפי שנה.",
        "lag_caption": "מועד הגשת הדיווחים לפי שנה",
        "ref_year": str(ref),
    }

    summary = (f"איתור מפעלים במפל\"ס לפי שם, חברה או יישוב: {n_ref:,} אתרים דיווחו על {ref}, "
               f"ו-{n_sites_all:,} מאז {y0}, עם נתוני פסולת מסוכנת ושפכים.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["מפל\"ס", "מרשם פליטות", "מפעלים", "פסולת מסוכנת", "שפכים", "הגנת הסביבה"],
            "related_ids": [
                "04931a88-336c-4d95-8a13-9dc631c3e2d1",
                "892135f3-cf6b-400a-8876-bfc80f3c9143",
                "5bf900d4-819a-4991-8c5a-4566e1a4af24",
                "7f1a7496-c3d9-498f-ade2-2ebb8e602916",
            ],
            "temporal_coverage": f"{y0}/{latest}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": {
            "years": chart_years, "haz": chart_haz, "non": chart_non,
            "sector": chart_sector, "sector_trend": chart_sector_trend,
            "field": chart_field, "dist": chart_dist, "heat": chart_heat,
            "auth": chart_auth, "comp": chart_comp,
            "top_haz": chart_top_haz, "top_non": chart_top_non,
            "wtype": chart_wtype, "wdest": chart_wdest, "lag": chart_lag,
        },
        "tables": {
            "years": tbl_years, "waste": tbl_waste, "sector": tbl_sector,
            "sector_trend": tbl_sector_trend, "field": tbl_field, "dist": tbl_dist,
            "auth": tbl_auth, "comp": tbl_comp, "top_haz": tbl_top_haz, "top_non": tbl_top_non,
            "wtype": tbl_wtype, "wdest": tbl_wdest, "lag": tbl_lag,
        },
        "flags": {
            "ww": bool(len(wtype)) and bool(len(wdest)),
            "top": bool(len(top_h)) and bool(len(top_n)),
            "comp": bool(len(comp)),
        },
        "insights": insights,
        "labels": labels,
    }
