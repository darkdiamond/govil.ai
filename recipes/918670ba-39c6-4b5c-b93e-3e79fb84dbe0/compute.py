"""מפל"ס (Israel PRTR), multi-year table: one row per site x reporting year x
medium x pollutant, plus one placeholder row per site-year-medium with no
pollutant. Site-year facts (sector, district, the four waste-transfer totals)
repeat on every row of a site-year, so they are de-duplicated on
MisparAtarSvivatiAndShnatDivuach before summing.

Units (per the PRTR reporting regulations): KamutPlita is kg per year; the
waste totals are tonnes per year. A quantity cell may instead hold "פליטה /
הזרמה נמוכה מכמות הסף" (below the reporting threshold, no amount).

A handful of rows arrive with shifted columns (a stray comma in the export);
they fail the site-id / site-year key check and are dropped, and the page
says how many.

Reporting year Y is filed during Y+1, so a newly published year can be
partial: if its site count is under 80% of the median of the three years
before it, trend rules use the previous year ("ref year") and the charts
label the latest year as partial.
"""

import pandas as pd

KG_PER_TONNE = 1000.0
KG_PER_MT = 1e9

# Headline air pollutants by PRTR pollutant code (names come from the data).
CO2 = "019"
SOX = "095"
CH4 = "069"
AIR_KEY = ["076", "095", "081", "078", "020"]  # NOx SOx PM10 NMVOC CO

MEDIA_ORDER = ["אוויר", "שפכים", "ים", "מקור מים", "קרקע"]
MEDIA_LABEL = {
    "אוויר": "אוויר",
    "שפכים": "שפכים (העברה למט\"ש)",
    "ים": "ים",
    "מקור מים": "מקור מים",
    "קרקע": "קרקע",
}

WASTE = [
    ("SachTipulPsoletMesukenet", "פסולת מסוכנת לטיפול"),
    ("SachSilukPsoletMesukenet", "פסולת מסוכנת לסילוק"),
    ("SachTipulPsoletLoMesukenet", "פסולת לא מסוכנת לטיפול"),
    ("SachSilukPsoletLoMesukenet", "פסולת לא מסוכנת לסילוק"),
]

METHOD_ORDER = ["מדידה", "חישוב, מודל או מקדם", "הערכה הנדסית", "לא צוין"]


def _num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce")


def _fmt(v, d=0):
    return f"{v:,.{d}f}"


def _signed_pct(p, d=1):
    s = f"{abs(p) * 100:.{d}f}%"
    return ("−" + s) if p < 0 else ("+" + s if p > 0 else s)


def _ranked(series, n=None):
    """Series → list of (key, value) sorted by value desc, key asc."""
    items = sorted(series.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return items[:n] if n else items


def _method_family(s):
    s = s.strip()
    if not s or s in ("בחר", "לא"):
        return "לא צוין"
    if s.startswith("מדיד") or "ניטור" in s or "נטור" in s or "דיגום" in s or s.startswith("דיג"):
        return "מדידה"
    if s.startswith("הערכ"):
        return "הערכה הנדסית"
    if any(k in s for k in ("מקדם", "מודל", "מחשב", "מאזן", "חישוב")) or s.startswith("מח"):
        return "חישוב, מודל או מקדם"
    return "לא צוין"


def _media(values):
    known = [m for m in MEDIA_ORDER if m in values]
    return known + sorted(v for v in values if v not in MEDIA_ORDER)


# ── preparation ──────────────────────────────────────────────────────────


def _prepare(raw):
    df = raw.copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    ok = (
        df["MisparAtarSvivati"].str.fullmatch(r"\d+")
        & df["ShnatDivuach"].str.fullmatch(r"\d{4}")
        & (df["MisparAtarSvivatiAndShnatDivuach"] == df["MisparAtarSvivati"] + "-" + df["ShnatDivuach"])
    )
    dropped = int((~ok).sum())
    df = df[ok].copy()
    df["year"] = df["ShnatDivuach"].astype(int)
    df["kg"] = _num(df["KamutPlita"])
    df["kg_fail"] = _num(df["KamutPlitaBeTeunot"])
    df["below"] = df["KamutPlita"].str.contains("נמוכה מכמות הסף", regex=False)
    df["has_pol"] = df["KodMezahem"].str.fullmatch(r"\d{3}")
    df["reported"] = df["has_pol"] & df["kg"].notna()
    df["sector"] = df["AnafAtarSvivati"].where(df["AnafAtarSvivati"] != "", "לא צוין")
    df["district"] = df["MachozAtarSvivati"].where(df["MachozAtarSvivati"] != "", "לא צוין")
    df["activity"] = df["TchumPeilutAtarSvivati"].where(df["TchumPeilutAtarSvivati"] != "", "לא צוין")
    # Some years ship the pollutant-group column empty; every pollutant code
    # maps to one group, so fill it from the years that carry it.
    g = df[df["has_pol"] & (df["KvutzatMezahamim"] != "")]
    gc = g.groupby(["KodMezahem", "KvutzatMezahamim"]).size().reset_index(name="n")
    gc = gc.sort_values(["KodMezahem", "n", "KvutzatMezahamim"], ascending=[True, False, True])
    code_group = dict(zip(gc.drop_duplicates("KodMezahem")["KodMezahem"], gc.drop_duplicates("KodMezahem")["KvutzatMezahamim"]))
    df["group"] = df["KodMezahem"].map(code_group).fillna("ללא סיווג קבוצה")
    df["method"] = df["ShahamPlita"].map(_method_family)
    return df, dropped


def _site_years(df):
    sy = df.sort_values(["MisparAtarSvivatiAndShnatDivuach", "ShemAtarSvivatiMenifa", "sector", "district"])
    sy = sy.drop_duplicates("MisparAtarSvivatiAndShnatDivuach").copy()
    for col, _ in WASTE:
        sy[col] = _num(sy[col]).fillna(0).clip(lower=0)
    sy["waste_total"] = sy[[c for c, _ in WASTE]].sum(axis=1)
    return sy


def _pollutant_names(df):
    p = df[df["has_pol"] & (df["MezahemBeplita"] != "")]
    cnt = p.groupby(["KodMezahem", "MezahemBeplita"]).size().reset_index(name="n")
    cnt = cnt.sort_values(["KodMezahem", "n", "MezahemBeplita"], ascending=[True, False, True])
    return dict(zip(cnt.drop_duplicates("KodMezahem")["KodMezahem"], cnt.drop_duplicates("KodMezahem")["MezahemBeplita"]))


def _site_name(sy):
    s = sy.sort_values(["MisparAtarSvivati", "year", "ShemAtarSvivatiMenifa"])
    s = s[s["ShemAtarSvivatiMenifa"] != ""].drop_duplicates("MisparAtarSvivati", keep="last")
    return dict(zip(s["MisparAtarSvivati"], s["ShemAtarSvivatiMenifa"]))


# ── main ─────────────────────────────────────────────────────────────────


def compute(frames):
    df, dropped = _prepare(frames["main"])
    sy = _site_years(df)
    names = _pollutant_names(df)
    site_name = _site_name(sy)

    years = sorted(sy["year"].unique().tolist())
    y0, y_last = years[0], years[-1]
    sites_by_year = sy.groupby("year")["MisparAtarSvivati"].nunique()
    sites_list = [int(sites_by_year.get(y, 0)) for y in years]

    partial = False
    if len(years) >= 4:
        prev = sorted(sites_list[-4:-1])
        med = prev[1]
        partial = sites_list[-1] < 0.8 * med
    ref = years[-2] if partial else y_last
    ylab = [f"{y} (חלקי)" if (partial and y == y_last) else str(y) for y in years]

    air = df[(df["SugPlita"] == "אוויר") & df["reported"]]

    # ── CO2 by sector per year ──
    co2 = air[air["KodMezahem"] == CO2]
    co2_year = co2.groupby("year")["kg"].sum()
    co2_list = [round(float(co2_year.get(y, 0.0)) / KG_PER_MT, 2) for y in years]
    sec_tot = co2.groupby("sector")["kg"].sum()
    top_secs = [k for k, _ in _ranked(sec_tot, 4)]
    co2_series = []
    for s in top_secs:
        g = co2[co2["sector"] == s].groupby("year")["kg"].sum()
        co2_series.append({"name": s, "data": [round(float(g.get(y, 0.0)) / KG_PER_MT, 3) for y in years]})
    other = co2[~co2["sector"].isin(top_secs)].groupby("year")["kg"].sum()
    if len(sec_tot) > len(top_secs):
        co2_series.append({"name": "אחר", "data": [round(float(other.get(y, 0.0)) / KG_PER_MT, 3) for y in years]})

    co2_0 = float(co2_year.get(y0, 0.0))
    co2_ref = float(co2_year.get(ref, 0.0))

    # ── key air pollutants, tonnes and index ──
    air_series, air_rows = [], []
    for code in AIR_KEY:
        g = air[air["KodMezahem"] == code].groupby("year")["kg"].sum()
        t = [round(float(g.get(y, 0.0)) / KG_PER_TONNE, 1) for y in years]
        base = t[0]
        if base <= 0 or (g > 0).sum() < max(2, len(years) // 2):
            continue
        nm = names.get(code, code)
        idx = [round(v / base * 100, 1) for v in t]
        air_series.append({"name": nm, "tonnes": t, "index": idx})
        r = t[years.index(ref)]
        air_rows.append({"name": nm, "first": _fmt(base), "ref": _fmt(r), "chg": _signed_pct(r / base - 1)})

    # ── top CO2 emitters (ref year) ──
    co2r = co2[co2["year"] == ref]
    by_site = co2r.groupby("MisparAtarSvivati")["kg"].sum()
    top_sites = _ranked(by_site, 10)
    co2_top = {
        "names": [site_name.get(k, k) for k, _ in top_sites],
        "values": [round(v / KG_PER_MT * 1000, 1) for _, v in top_sites],  # thousand tonnes
    }

    # ── sector / district / activity (ref year) ──
    syr = sy[sy["year"] == ref]
    n_ref_sites = int(syr["MisparAtarSvivati"].nunique())
    co2_sec_ref = co2r.groupby("sector")["kg"].sum()
    sec_sites = syr.groupby("sector")["MisparAtarSvivati"].nunique()
    sector = {"names": [], "sites": [], "co2": []}
    for k, v in _ranked(sec_sites):
        sector["names"].append(k)
        sector["sites"].append(int(v))
        sector["co2"].append(round(float(co2_sec_ref.get(k, 0.0)) / KG_PER_MT * 1000, 1))
    co2_dist_ref = co2r.groupby("district")["kg"].sum()
    dist_sites = syr.groupby("district")["MisparAtarSvivati"].nunique()
    district = {"names": [], "sites": [], "co2": []}
    for k, v in _ranked(dist_sites):
        district["names"].append(k)
        district["sites"].append(int(v))
        district["co2"].append(round(float(co2_dist_ref.get(k, 0.0)) / KG_PER_MT * 1000, 1))
    act = _ranked(syr.groupby("activity")["MisparAtarSvivati"].nunique())
    act_n = 12
    activity = {"names": [k for k, _ in act[:act_n]], "values": [int(v) for _, v in act[:act_n]]}
    act_other = int(sum(v for _, v in act[act_n:]))
    if act_other:
        activity["names"].append("אחר")
        activity["values"].append(act_other)

    # ── reports by medium per year ──
    rep = df[df["reported"]]
    media = _media(set(df.loc[df["has_pol"], "SugPlita"]) - {""})
    med_series = []
    for m in media:
        g = rep[rep["SugPlita"] == m].groupby("year").size()
        med_series.append({"name": MEDIA_LABEL.get(m, m), "data": [int(g.get(y, 0)) for y in years]})
    med_rows = [{"year": ylab[i], "vals": [s["data"][i] for s in med_series]} for i in range(len(years))]

    # ── medium x pollutant group heatmap (ref year) ──
    repr_ = rep[rep["year"] == ref]
    grp_tot = repr_.groupby("group").size()
    groups = [k for k, _ in _ranked(grp_tot)]
    cells, heat_rows, heat_max = [], [], 0
    for gi, g in enumerate(groups):
        row = []
        for mi, m in enumerate(media):
            n = int(((repr_["group"] == g) & (repr_["SugPlita"] == m)).sum())
            cells.append([mi, gi, n])
            row.append(n)
            heat_max = max(heat_max, n)
        heat_rows.append({"name": g, "vals": row})
    heat = {"x": [MEDIA_LABEL.get(m, m) for m in media], "y": groups, "cells": cells, "max": heat_max}

    # ── top pollutants to sea and to wastewater (ref year, tonnes) ──
    def top_pol(medium, n=10):
        g = repr_[repr_["SugPlita"] == medium].groupby("KodMezahem")["kg"].sum()
        g = g[g > 0]
        r = _ranked(g, n)
        return {"names": [names.get(k, k) for k, _ in r], "values": [round(v / KG_PER_TONNE, 1) for _, v in r]}

    sea = top_pol("ים")
    sewer = top_pol("שפכים")

    # ── waste per year ──
    waste_series = []
    for col, label in WASTE:
        g = sy.groupby("year")[col].sum()
        waste_series.append({"name": label, "data": [round(float(g.get(y, 0.0)) / 1000, 1) for y in years]})
    waste_total = [round(sum(s["data"][i] for s in waste_series), 1) for i in range(len(years))]
    wt = _ranked(syr.groupby("MisparAtarSvivati")["waste_total"].sum(), 10)
    waste_top = {"names": [site_name.get(k, k) for k, _ in wt], "values": [round(v / 1000, 1) for _, v in wt]}

    # ── determination method by medium (ref year, numeric reports) ──
    meth = {"media": [MEDIA_LABEL.get(m, m) for m in media], "series": []}
    tot_m = [int((repr_["SugPlita"] == m).sum()) for m in media]
    for fam in METHOD_ORDER:
        vals = []
        for mi, m in enumerate(media):
            n = int(((repr_["SugPlita"] == m) & (repr_["method"] == fam)).sum())
            vals.append(round(n / tot_m[mi] * 100, 1) if tot_m[mi] else 0.0)
        meth["series"].append({"name": fam, "data": vals})
    meth_rows = [{"name": meth["media"][i], "vals": [s["data"][i] for s in meth["series"]], "n": tot_m[i]}
                 for i in range(len(media))]

    # ── insights ──
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    s0 = sites_list[0]
    s_ref = int(sites_by_year.get(ref, 0))

    def ins_co2_trend():
        if ref == y0 or co2_0 <= 0:
            return None
        ch = co2_ref / co2_0 - 1
        if abs(ch) < 0.05:
            return (f"פליטת הפחמן הדו-חמצני של המפעלים המדווחים יציבה יחסית: {_fmt(co2_0 / KG_PER_MT, 1)} מיליון טון ב-{y0} "
                    f"ו-{_fmt(co2_ref / KG_PER_MT, 1)} מיליון טון ב-{ref}.")
        word = "ירדה" if ch < 0 else "עלתה"
        txt = (f"פליטת הפחמן הדו-חמצני של המפעלים המדווחים {word} מ-{_fmt(co2_0 / KG_PER_MT, 1)} מיליון טון ב-{y0} "
               f"ל-{_fmt(co2_ref / KG_PER_MT, 1)} מיליון טון ב-{ref} ({_fmt(abs(ch) * 100, 1)}%)")
        if ch < 0 and s_ref > s0:
            txt += f", אף שמספר המפעלים המדווחים גדל מ-{_fmt(s0)} ל-{_fmt(s_ref)}"
        return txt + "."

    def ins_co2_yoy():
        i = years.index(ref)
        if i == 0:
            return None
        prev_y = years[i - 1]
        pv = float(co2_year.get(prev_y, 0.0))
        if pv <= 0:
            return None
        ch = co2_ref / pv - 1
        if abs(ch) < 0.03:
            return None
        word = "ירידה" if ch < 0 else "עלייה"
        return (f"ב-{ref} נרשמה {word} של {_fmt(abs(ch) * 100, 1)}% בפליטת הפחמן הדו-חמצני לעומת {prev_y} "
                f"({_fmt(co2_ref / KG_PER_MT, 2)} לעומת {_fmt(pv / KG_PER_MT, 2)} מיליון טון).")

    def ins_sox():
        g = air[air["KodMezahem"] == SOX].groupby("year")["kg"].sum()
        a, b = float(g.get(y0, 0.0)), float(g.get(ref, 0.0))
        if ref == y0 or a <= 0:
            return None
        ch = b / a - 1
        if abs(ch) < 0.1:
            return None
        nm = names.get(SOX, "תחמוצות גופרית")
        word = "צנחה" if ch <= -0.5 else ("ירדה" if ch < 0 else "עלתה")
        return (f"פליטת {nm} {word} ב-{_fmt(abs(ch) * 100, 1)}%: מ-{_fmt(a / KG_PER_TONNE)} טון ב-{y0} "
                f"ל-{_fmt(b / KG_PER_TONNE)} טון ב-{ref}.")

    def ins_sector():
        tot = float(co2_sec_ref.sum())
        if tot <= 0:
            return None
        k, v = _ranked(co2_sec_ref, 1)[0]
        sh = v / tot
        if sh < 0.4:
            return None
        n = int(sec_sites.get(k, 0))
        return (f"ענף {k} אחראי ל-{_fmt(sh * 100, 1)}% מפליטת הפחמן הדו-חמצני המדווחת ב-{ref}, "
                f"אף שהוא כולל רק {_fmt(n)} מתוך {_fmt(n_ref_sites)} המפעלים המדווחים.")

    def ins_top_site():
        tot = float(by_site.sum())
        if tot <= 0 or len(top_sites) < 3:
            return None
        k, v = top_sites[0]
        top3 = sum(x for _, x in top_sites[:3]) / tot
        return (f"הפולט הגדול ביותר של פחמן דו-חמצני ב-{ref} הוא {site_name.get(k, k)} "
                f"({_fmt(v / KG_PER_MT, 2)} מיליון טון, {_fmt(v / tot * 100, 1)}% מהסך). "
                f"שלושת הגדולים אחראים יחד ל-{_fmt(top3 * 100, 1)}%.")

    def ins_methane():
        m = air[air["KodMezahem"] == CH4]
        g = m.groupby("year")["kg"].sum()
        a, b = float(g.get(y0, 0.0)), float(g.get(ref, 0.0))
        if ref == y0 or a <= 0 or b <= 0:
            return None
        ch = b / a - 1
        if abs(ch) < 0.2:
            return None
        bs = m[m["year"] == ref].groupby("MisparAtarSvivati")["kg"].sum()
        k, v = _ranked(bs, 1)[0]
        nm = names.get(CH4, "מתאן")
        txt = (f"פליטת ה{nm} המדווחת " + (f"גדלה פי {_fmt(b / a, 1)}" if ch >= 1 else (f"עלתה ב-{_fmt(ch * 100, 1)}%" if ch > 0 else f"ירדה ב-{_fmt(abs(ch) * 100, 1)}%"))
               + f": מ-{_fmt(a / KG_PER_TONNE)} טון ב-{y0} ל-{_fmt(b / KG_PER_TONNE)} טון ב-{ref}. ")
        return txt + f"הפולט הגדול ב-{ref}: {site_name.get(k, k)} ({_fmt(v / b * 100, 1)}% מהסך)."

    def ins_below():
        a = df[(df["year"] == ref) & (df["SugPlita"] == "אוויר") & df["has_pol"]]
        if len(a) < 50:
            return None
        sh = float(a["below"].mean())
        if sh < 0.2:
            return None
        return (f"{_fmt(sh * 100, 1)}% מדיווחי הפליטה לאוויר ב-{ref} ({_fmt(int(a['below'].sum()))} מתוך {_fmt(len(a))}) "
                "סומנו כפליטה נמוכה מכמות הסף, ולכן אינם כוללים כמות.")

    def ins_waste():
        if ref == y0:
            return None
        col, label = WASTE[3]
        g = sy.groupby("year")[col].sum()
        a, b = float(g.get(y0, 0.0)), float(g.get(ref, 0.0))
        if a <= 0:
            return None
        ch = b / a - 1
        if abs(ch) < 0.1:
            return None
        word = "גדלה" if ch > 0 else "קטנה"
        return (f"כמות הפסולת הלא מסוכנת שהמפעלים העבירו לסילוק {word} ב-{_fmt(abs(ch) * 100, 1)}%: "
                f"מ-{_fmt(a / 1000)} אלף טון ב-{y0} ל-{_fmt(b / 1000)} אלף טון ב-{ref}.")

    def ins_district():
        if not district["names"] or n_ref_sites == 0:
            return None
        k, n = district["names"][0], district["sites"][0]
        sh = n / n_ref_sites
        if sh < 0.25 or (len(district["sites"]) > 1 and district["sites"][1] == n):
            return None
        txt = f"מחוז {k} מוביל במספר המפעלים המדווחים ב-{ref}: {_fmt(n)} מתוך {_fmt(n_ref_sites)} ({_fmt(sh * 100, 1)}%)"
        ctot = sum(district["co2"])
        if ctot > 0:
            ci = max(range(len(district["co2"])), key=lambda i: (district["co2"][i], -i))
            if district["names"][ci] != k:
                txt += f", אך את רוב הפחמן הדו-חמצני פולטים מפעלי מחוז {district['names'][ci]} ({_fmt(district['co2'][ci] / ctot * 100, 1)}%)"
        return txt + "."

    def ins_malfunction():
        f = df[(df["year"] == ref) & df["has_pol"] & (df["kg_fail"] > 0)]
        n = int(f["MisparAtarSvivati"].nunique())
        if n == 0:
            return None
        return (f"{_fmt(n)} מפעלים דיווחו ב-{ref} על פליטה או הזרמה של מזהמים בעת תקלה "
                f"({_fmt(len(f))} דיווחים).")

    def ins_measured():
        a = repr_[repr_["SugPlita"] == "אוויר"]
        if len(a) < 50:
            return None
        sh = float((a["method"] == "מדידה").mean())
        return (f"רק {_fmt(sh * 100, 1)}% מכמויות הפליטה לאוויר שדווחו ב-{ref} נקבעו במדידה; "
                "השאר חושבו במודל, במקדם פליטה או בהערכה הנדסית.") if sh < 0.5 else (
                f"{_fmt(sh * 100, 1)}% מכמויות הפליטה לאוויר שדווחו ב-{ref} נקבעו במדידה או בניטור.")

    add("co2_trend", ins_co2_trend())
    add("sox", ins_sox())
    add("sector", ins_sector())
    add("top_site", ins_top_site())
    add("co2_yoy", ins_co2_yoy())
    add("methane", ins_methane())
    add("waste", ins_waste())
    add("district", ins_district())
    add("below", ins_below())
    add("measured", ins_measured())
    add("malfunction", ins_malfunction())

    # ── KPIs ──
    co2_ch = (co2_ref / co2_0 - 1) if co2_0 > 0 else 0.0
    sox_g = air[air["KodMezahem"] == SOX].groupby("year")["kg"].sum()
    sox_a, sox_b = float(sox_g.get(y0, 0.0)), float(sox_g.get(ref, 0.0))
    sox_ch = (sox_b / sox_a - 1) if sox_a > 0 else 0.0

    def tone_change(ch, good_down=True):
        if ch <= -0.05:
            return "ok" if good_down else "danger"
        if ch >= 0.05:
            return "danger" if good_down else "ok"
        return "brand"

    waste_ref = waste_total[years.index(ref)]
    kpis = {
        "sites": {"value": s_ref, "display": _fmt(s_ref), "tone": "brand"},
        "years": {"value": len(years), "display": f"{y0}–{y_last}", "tone": "brand"},
        "co2": {"value": round(co2_ref / KG_PER_MT, 2), "display": _fmt(co2_ref / KG_PER_MT, 1), "tone": "brand"},
        "co2_change": {"value": round(co2_ch * 100, 1), "display": _signed_pct(co2_ch), "tone": tone_change(co2_ch)},
        "sox_change": {"value": round(sox_ch * 100, 1), "display": _signed_pct(sox_ch), "tone": tone_change(sox_ch)},
        "waste": {"value": waste_ref, "display": _fmt(waste_ref), "tone": "brand"},
    }

    if s_ref == s0:
        sites_trend = f"מספר המפעלים שדיווחו למפל\"ס לא השתנה: {_fmt(s_ref)} ב-{y0} וב-{ref}. "
    else:
        sites_trend = (f"מספר המפעלים שדיווחו למפל\"ס {'עלה' if s_ref > s0 else 'ירד'} "
                       f"מ-{_fmt(s0)} ב-{y0} ל-{_fmt(s_ref)} ב-{ref}. ")
    labels = {
        "sites_kpi": f"מפעלים שדיווחו על {ref}",
        "years_kpi": f"שנות דיווח ({len(years)} שנים)",
        "co2_kpi": f"פליטת פחמן דו-חמצני ב-{ref} (מיליון טון)",
        "co2_change_kpi": f"שינוי בפליטת פחמן דו-חמצני, {y0} עד {ref}",
        "sox_change_kpi": f"שינוי בפליטת תחמוצות גופרית, {y0} עד {ref}",
        "waste_kpi": f"פסולת שהועברה לטיפול או לסילוק ב-{ref} (אלפי טון)",
        "ref": str(ref),
        "y0": str(y0),
        "partial_note": (f"שנת {y_last} מסומנת כחלקית: דיווחו עליה {_fmt(sites_list[-1])} מפעלים בלבד, "
                         f"ולכן ההשוואות בעמוד מתייחסות לשנת {ref}.") if partial else "",
        "dropped_note": (f"{_fmt(dropped)} שורות שבהן העמודות מוסטות (שגיאת ייצוא) לא נכללו בניתוח.") if dropped else "",
        "sites_lede": (sites_trend +
                       f"השיא: {_fmt(max(sites_list))} מפעלים ב-{years[sites_list.index(max(sites_list))]}."),
        "sites_aria": f"גרף עמודות: מספר המפעלים המדווחים בכל שנה, {y0} עד {y_last}. ב-{ref} דיווחו {_fmt(s_ref)} מפעלים.",
        "co2_lede": (f"סך הפחמן הדו-חמצני שדווח: {_fmt(co2_0 / KG_PER_MT, 1)} מיליון טון ב-{y0} ו-{_fmt(co2_ref / KG_PER_MT, 1)} מיליון טון ב-{ref}, "
                     f"מחולק לפי ענף המפעל."),
        "co2_aria": f"גרף עמודות מוערמות: פליטת פחמן דו-חמצני לפי ענף ושנה, במיליוני טון. ב-{ref}: {_fmt(co2_ref / KG_PER_MT, 1)} מיליון טון.",
        "air_lede": (f"מדד לפי שנת {y0} = 100 למזהמי אוויר מרכזיים; מעבר עם העכבר על נקודה מציג את הכמות בטונות. "
                     f"הטבלה משווה את {y0} ל-{ref}."),
        "air_aria": f"גרף קווים: מדד פליטה של מזהמי אוויר מרכזיים, {y0} עד {y_last}, כאשר {y0} שווה מאה.",
        "co2_top_lede": f"עשרת המפעלים שדיווחו על הפליטה הגדולה ביותר של פחמן דו-חמצני ב-{ref}, באלפי טון.",
        "co2_top_aria": (f"גרף עמודות אופקי: עשרת הפולטים הגדולים של פחמן דו-חמצני ב-{ref}. "
                         f"במקום הראשון {co2_top['names'][0] if co2_top['names'] else ''}."),
        "sector_lede": f"מספר המפעלים המדווחים בכל ענף ב-{ref}, לצד פליטת הפחמן הדו-חמצני של הענף (אלפי טון).",
        "sector_aria": f"גרף עמודות: מפעלים מדווחים לפי ענף ב-{ref}. הענף הגדול: {sector['names'][0] if sector['names'] else ''}.",
        "district_lede": f"פריסת המפעלים המדווחים ב-{ref} לפי מחוז של המשרד להגנת הסביבה, ופליטת הפחמן הדו-חמצני בכל מחוז.",
        "district_aria": f"גרף עמודות: מפעלים מדווחים לפי מחוז ב-{ref}. המחוז המוביל: {district['names'][0] if district['names'] else ''}.",
        "activity_lede": f"תחומי הפעילות שבהם דיווחו הכי הרבה מפעלים ב-{ref} (תחומים מעבר ל-{act_n} הראשונים מקובצים ב\"אחר\").",
        "activity_aria": f"גרף עמודות אופקי: מפעלים מדווחים לפי תחום פעילות ב-{ref}. התחום המוביל: {activity['names'][0] if activity['names'] else ''}.",
        "media_lede": (f"מספר הדיווחים שכללו כמות (מעל הסף) לפי אפיק הפליטה. ב-{ref}: "
                       + ", ".join(f"{s['name']} {_fmt(s['data'][years.index(ref)])}" for s in med_series) + "."),
        "media_aria": f"גרף עמודות מוערמות: דיווחי כמות לפי אפיק פליטה ושנה, {y0} עד {y_last}.",
        "heat_lede": f"איזה סוג מזהמים מדווח לכל אפיק: מספר הדיווחים שכללו כמות ב-{ref}, לפי קבוצת מזהמים ואפיק.",
        "heat_aria": f"מפת חום: דיווחי כמות לפי קבוצת מזהמים ואפיק פליטה ב-{ref}.",
        "sea_lede": f"המזהמים שהוזרמו לים בכמות הגדולה ביותר ב-{ref}, בטונות.",
        "sea_aria": f"גרף עמודות אופקי: עשרת המזהמים שהוזרמו לים בכמות הגדולה ביותר ב-{ref}.",
        "sewer_lede": f"המזהמים שהועברו בשפכים למתקני טיהור בכמות הגדולה ביותר ב-{ref}, בטונות.",
        "sewer_aria": f"גרף עמודות אופקי: עשרת המזהמים שהועברו בשפכים בכמות הגדולה ביותר ב-{ref}.",
        "waste_lede": (f"סך הפסולת שהמפעלים העבירו לטיפול (מיחזור והשבה) או לסילוק (הטמנה ושריפה): "
                       f"{_fmt(waste_total[0])} אלף טון ב-{y0} ו-{_fmt(waste_ref)} אלף טון ב-{ref}."),
        "waste_aria": f"גרף עמודות מוערמות: העברות פסולת לפי סוג ויעד, באלפי טון, {y0} עד {y_last}.",
        "waste_top_lede": f"עשרת המפעלים שהעבירו את כמות הפסולת הגדולה ביותר ב-{ref}, באלפי טון (כל סוגי הפסולת).",
        "waste_top_aria": (f"גרף עמודות אופקי: עשרת המפעלים שהעבירו הכי הרבה פסולת ב-{ref}. "
                           f"במקום הראשון {waste_top['names'][0] if waste_top['names'] else ''}."),
        "method_lede": f"איך נקבעה הכמות המדווחת: שיעור הדיווחים שנמדדו, חושבו או הוערכו, לפי אפיק, ב-{ref}.",
        "method_aria": f"גרף עמודות מוערמות באחוזים: שיטת קביעת הכמות לפי אפיק פליטה ב-{ref}.",
        "map_aria": f"מפה אינטראקטיבית של המפעלים שדיווחו על {y_last}. גרסה נגישה: עיון בנתונים מתחת לעמוד.",
        "map_lede": f"מיקום המפעלים שדיווחו על שנת {y_last}. לחיצה על נקודה מציגה את שם המפעל, החברה, היישוב והענף.",
    }

    summary = (f"איתור דיווחי מפעלים על פליטת מזהמים לאוויר, למים ולקרקע ועל העברת פסולת, {y0}-{y_last}. "
               f"ב-{ref} דיווחו {_fmt(s_ref)} מפעלים על {_fmt(co2_ref / KG_PER_MT, 1)} מיליון טון פחמן דו-חמצני.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["זיהום אוויר", "פליטות", "פסולת", "תעשייה", "מפעלים", "שפכים"],
            "related_ids": [
                "5fc5c912-4fa5-4474-93c1-326e505e22cf",
                "04931a88-336c-4d95-8a13-9dc631c3e2d1",
                "422ff747-a1ee-4e8d-b515-43417f0d80d8",
                "780f8522-db2b-4147-b2ac-554aafaf1c1a",
                "2a4a9360-ebb1-470a-bb88-d2ba942bf561",
            ],
            "temporal_coverage": f"{y0}/{y_last}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "insights": insights,
        "labels": labels,
        "map": {"year": str(y_last)},
        "charts": {
            "sites": {"x": ylab, "y": sites_list},
            "co2": {"x": ylab, "series": co2_series, "total": co2_list},
            "air": {"x": ylab, "series": air_series},
            "co2_top": co2_top,
            "sector": sector,
            "district": district,
            "activity": activity,
            "media": {"x": ylab, "series": med_series},
            "heat": heat,
            "sea": sea,
            "sewer": sewer,
            "waste": {"x": ylab, "series": waste_series, "total": waste_total},
            "waste_top": waste_top,
            "method": meth,
        },
        "tables": {
            "air": air_rows,
            "media": med_rows,
            "heat": heat_rows,
            "method": meth_rows,
            "years": [{"year": ylab[i], "sites": sites_list[i], "co2": co2_list[i], "waste": waste_total[i]}
                      for i in range(len(years))],
        },
    }
