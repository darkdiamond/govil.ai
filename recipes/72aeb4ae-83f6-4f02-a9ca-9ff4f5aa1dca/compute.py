"""Groundwater levels in boreholes (מפלסי קידוחים) — Water Authority.

Two files with the same schema (until 2000 / from 2000) are concatenated;
dates arrive either as "YYYY-MM-DD HH:MM:SS" or "DD/MM/YYYY", parsed per
row so a new file in either format flows through. Every number on the page
is computed here. Insight rules return a sentence or None.

The memory footprint matters (over a million rows): the string frame is
reduced once to a compact numeric frame and everything else works on it.
"""
import numpy as np
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

C_ID = "זיהוי קידוח"
C_NAME = "שם"
C_DATE = "תאריך"
C_LVL = "מפלס (מטרים)"
C_PAUSE = "משך הפסקה בשעות"
C_INST = "שם מוסד מודד"
C_DEPTH = "עומק עד פני המים (מטרים)"
C_OIL = "עובי השמן (מטרים)"
C_NOTE = "הערה"

# Pause-duration codes → ordered groups. Unknown codes fall into the last group.
PAUSE_GROUPS = ["עד 10 שעות", "10 עד 24 שעות", "24 עד 72 שעות", "מעל 72 שעות",
                "בזמן שאיבה", "לא ידוע"]
PAUSE_MAP = {
    "עד 1/4 שעה": 0, "1/4-1/2": 0, "1/2-1": 0, "1-3": 0, "3-5": 0, "5-10": 0,
    "10-24": 1, "24-72": 2, "מעל 72 שעות": 3, "בעבודה": 4, "לא ידועה": 5,
}
NO_NOTE = {"", "אין הערות"}

# Depth-to-water bands (metres below the measuring point).
DEPTH_BANDS = [(-np.inf, 0, "מעל פני הקרקע"), (0, 10, "עד 10 מ׳"), (10, 20, "10 עד 20 מ׳"),
               (20, 50, "20 עד 50 מ׳"), (50, 100, "50 עד 100 מ׳"),
               (100, 200, "100 עד 200 מ׳"), (200, np.inf, "מעל 200 מ׳")]

# Per-well change bands over the comparison window (metres).
CHANGE_BANDS = [(-np.inf, -5, "ירידה של מעל 5 מ׳"), (-5, -2, "ירידה של 2 עד 5 מ׳"),
                (-2, -0.5, "ירידה של 0.5 עד 2 מ׳"), (-0.5, 0.5, "יציב (פחות מ-0.5 מ׳)"),
                (0.5, 2, "עלייה של 0.5 עד 2 מ׳"), (2, 5, "עלייה של 2 עד 5 מ׳"),
                (5, np.inf, "עלייה של מעל 5 מ׳")]

MIN_PAIRS = 500        # wells per year-pair for a year to enter the level index
MIN_CMP_WELLS = 30     # wells measured in both comparison years
CMP_SPAN = 10          # comparison window, years
STABLE_M = 0.1         # |median change| below this is "stable"
TOP_N_INST = 5
TOP_N_NOTES = 7


def _int(n):
    return f"{int(round(n)):,}"


def _m(v, digits=2):
    """Signed metres for prose (ASCII sign reads fine inside Hebrew text)."""
    return f"{abs(v):.{digits}f}"


def _signed(v, digits=2):
    """KPI display: U+2212 minus, explicit plus."""
    s = f"{abs(v):.{digits}f}"
    if round(v, digits) > 0:
        return "+" + s
    if round(v, digits) < 0:
        return "−" + s
    return s


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce")


def _prepare(raw):
    d = raw[C_DATE].str.strip()
    dt = pd.to_datetime(d.str.slice(0, 10), errors="coerce", format="%Y-%m-%d")
    dt2 = pd.to_datetime(d, errors="coerce", format="%d/%m/%Y")
    dt = dt.fillna(dt2)
    del dt2, d
    inst_raw = raw[C_INST].str.strip()
    df = pd.DataFrame({
        "id": _num(raw[C_ID]),
        "y": dt.dt.year,
        "m": dt.dt.month,
        "day": dt.dt.day,
        "lvl": _num(raw[C_LVL]),
        "dep": _num(raw[C_DEPTH]),
        "oil": _num(raw[C_OIL]),
        "pause": raw[C_PAUSE].str.strip().map(PAUSE_MAP).fillna(5).astype("int8"),
        "inst": inst_raw.astype("category"),
        "note": raw[C_NOTE].str.strip().astype("category"),
    })
    del dt
    df = df.dropna(subset=["id", "y", "lvl"])
    df["id"] = df["id"].astype("int64")
    df["y"] = df["y"].astype("int32")
    df["m"] = df["m"].astype("int8")
    df["day"] = df["day"].astype("int8")
    return df


def _well_names(raw, ids):
    """Latest-dated name per well id (ties: lexicographically last)."""
    idn = _num(raw[C_ID])
    mask = idn.isin(list(ids))
    sub = pd.DataFrame({"id": idn[mask].astype("int64"),
                        "d": raw.loc[mask, C_DATE].str.strip(),
                        "name": raw.loc[mask, C_NAME].str.strip()})
    d = sub["d"]
    dt = pd.to_datetime(d.str.slice(0, 10), errors="coerce", format="%Y-%m-%d").fillna(
        pd.to_datetime(d, errors="coerce", format="%d/%m/%Y"))
    sub = sub.assign(dt=dt).sort_values(["id", "dt", "name"], kind="stable", na_position="first")
    return sub.groupby("id")["name"].last().to_dict()


def _inst_display(df):
    """Merge spellings that differ only by quote marks (תה"ל / תהל)."""
    counts = df["inst"].value_counts()
    key = {}
    for raw_name in counts.index:
        k = str(raw_name).replace('"', "").replace("״", "").replace("'", "").strip()
        key[raw_name] = k or "לא צוין"
    totals = {}
    best = {}
    for raw_name, n in counts.items():
        if n == 0:
            continue
        k = key[raw_name]
        totals[k] = totals.get(k, 0) + int(n)
        cand = (int(n), str(raw_name))
        if k not in best or (cand[0] > best[k][0]) or (cand[0] == best[k][0] and cand[1] < best[k][1]):
            best[k] = cand
    disp = {raw_name: (best[key[raw_name]][1] if key[raw_name] in best else str(raw_name))
            for raw_name in counts.index}
    return disp


def _last_full_year(yearly_n, months_by_year):
    """Last year with 12 measured months and ≥50% of the prior 3 years' median count."""
    years = list(yearly_n.index)
    if not years:
        return None, False
    last = years[-1]
    prev = yearly_n.loc[[y for y in years if last - 3 <= y < last]]
    ok_months = months_by_year.get(last, 0) >= 12
    ok_count = prev.empty or yearly_n.loc[last] >= 0.5 * float(prev.median())
    if ok_months and ok_count:
        return last, False
    return (years[-2] if len(years) > 1 else last), True


def _decade_label(dec, first_dec, y_max):
    if dec == first_dec:
        return f"עד {dec + 9}"
    return f"{dec}-{min(dec + 9, y_max)}"


def compute(frames):
    raw = frames["levels"]
    df = _prepare(raw)

    n_meas = len(df)
    wells_all = df["id"].nunique()
    y_min, y_max = int(df["y"].min()), int(df["y"].max())

    # ---------------- yearly activity ----------------
    yearly_n = df.groupby("y").size().sort_index()
    yearly_w = df.groupby("y")["id"].nunique().sort_index()
    months_by_year = df.groupby("y")["m"].nunique().to_dict()
    last_full, last_partial = _last_full_year(yearly_n, months_by_year)
    chart_yearly = {"x": [str(y) for y in yearly_n.index],
                    "n": [int(v) for v in yearly_n.values],
                    "w": [int(yearly_w.loc[y]) for y in yearly_n.index]}

    # ---------------- per-well annual medians + level index ----------------
    am = df.groupby(["id", "y"])["lvl"].median().reset_index().sort_values(["id", "y"], kind="stable")
    am["py"] = am.groupby("id")["y"].shift()
    am["pl"] = am.groupby("id")["lvl"].shift()
    pairs = am[(am["y"] - am["py"]) == 1]
    pairs = pairs[pairs["y"] <= last_full]
    yoy = pairs.assign(d=pairs["lvl"] - pairs["pl"]).groupby("y")["d"].agg(["median", "count"]).sort_index()
    yoy = yoy[yoy["count"] >= MIN_PAIRS]
    index_ok = len(yoy) >= 5
    chart_index = None
    wettest = driest = None
    if index_ok:
        med = yoy["median"].round(3)
        cum = med.cumsum().round(3)
        base_year = int(yoy.index[0]) - 1
        chart_index = {"x": [str(y) for y in yoy.index],
                       "d": [float(v) for v in med.values],
                       "cum": [float(v) for v in cum.values],
                       "n": [int(v) for v in yoy["count"].values],
                       "base": base_year}
        mx = med.sort_index().idxmax()
        mn = med.sort_index().idxmin()
        wettest = (int(mx), float(med.loc[mx]), int(yoy.loc[mx, "count"]))
        driest = (int(mn), float(med.loc[mn]), int(yoy.loc[mn, "count"]))
        cum_last = float(cum.iloc[-1])
        yoy_last_year = int(yoy.index[-1])
        cum_low_year = int(cum.sort_index().idxmin())
        cum_low = float(cum.loc[cum_low_year])

    # ---------------- per-well change over the comparison window ----------------
    cmp_base = last_full - CMP_SPAN
    a = am[am["y"] == cmp_base].set_index("id")["lvl"]
    b = am[am["y"] == last_full].set_index("id")["lvl"]
    chg = (b - a).dropna().sort_index()
    cmp_ok = len(chg) >= MIN_CMP_WELLS
    chart_change = None
    if cmp_ok:
        rows = []
        for lo, hi, lab in CHANGE_BANDS:
            n = int(((chg >= lo) & (chg < hi)).sum())
            rows.append({"band": lab, "n": n, "nd": _int(n), "share": _pct(n / len(chg))})
        tone_idx = [0, 0, 0, 1, 2, 2, 2]
        chart_change = {"x": [r["band"] for r in rows], "y": [r["n"] for r in rows],
                        "tone": tone_idx, "rows": rows}
        chg_med = float(chg.median())
        rising = float((chg >= 0.5).mean())
        falling = float((chg < -0.5).mean())

    # ---------------- seasonality ----------------
    g = df.groupby(["id", "y"])["lvl"]
    wy_mean = g.transform("mean")
    wy_n = g.transform("size")
    m_ok = wy_n >= 6
    anom = (df.loc[m_ok, "lvl"] - wy_mean[m_ok]).groupby(df.loc[m_ok, "m"]).median().sort_index()
    anom_n = df.loc[m_ok].groupby(["id", "y"]).ngroups
    del wy_mean, wy_n, g
    season_ok = len(anom) == 12
    chart_season = None
    if season_ok:
        vals = [round(float(anom.loc[m]), 3) for m in range(1, 13)]
        chart_season = {"x": MONTHS_HE, "y": vals,
                        "rows": [{"month": MONTHS_HE[i], "v": f"{vals[i]:+.2f}".replace("-", "−")}
                                 for i in range(12)]}
        peak_m = int(np.argmax(vals))
        low_m = int(np.argmin(vals))
        amp = vals[peak_m] - vals[low_m]

    # ---------------- depth to water, latest measurement per well in last full year ----------------
    lf = df[df["y"] == last_full].sort_values(["id", "m", "day", "dep"], kind="stable")
    latest = lf.groupby("id").tail(1)
    del lf
    dep_rows = []
    for lo, hi, lab in DEPTH_BANDS:
        n = int(((latest["dep"] >= lo) & (latest["dep"] < hi)).sum())
        dep_rows.append({"band": lab, "n": n,
                         "share": _pct(n / len(latest)) if len(latest) else "0.0%"})
    dep_known = latest["dep"].dropna()
    dep_med = float(dep_known.median()) if len(dep_known) else None
    artesian = int((dep_known < 0).sum())
    below_sea = int((latest["lvl"] < 0).sum())
    deepest_dep = float(dep_known.max()) if len(dep_known) else None
    chart_depth = {"x": [r["band"] for r in dep_rows], "y": [r["n"] for r in dep_rows], "rows": dep_rows}
    wells_last = int(latest["id"].nunique())
    del latest

    # ---------------- decades: institutions + pause duration ----------------
    first_dec = max(int(df["y"].min()) // 10 * 10, 1940)
    dec = (df["y"] // 10 * 10).clip(lower=first_dec)
    decades = sorted(dec.unique().tolist())
    dec_labels = [_decade_label(d, first_dec, y_max) for d in decades]

    disp = _inst_display(df)
    inst_d = df["inst"].map(disp).astype(str)
    inst_tot = inst_d.value_counts()
    inst_tot = inst_tot.sort_index().sort_values(ascending=False, kind="stable")
    top_inst = list(inst_tot.index[:TOP_N_INST])
    inst_g = inst_d.where(inst_d.isin(top_inst), "אחר")
    ct = pd.crosstab(dec, inst_g)
    inst_order = top_inst + (["אחר"] if "אחר" in ct.columns else [])
    chart_inst = {"x": dec_labels,
                  "series": [{"name": s, "data": [int(ct.loc[d, s]) if s in ct.columns else 0 for d in decades]}
                             for s in inst_order]}
    inst_rows = [{"dec": dec_labels[i],
                  "cells": [_int(ct.loc[d, s]) if s in ct.columns else "0" for s in inst_order]}
                 for i, d in enumerate(decades)]
    top_inst_name, top_inst_share = inst_tot.index[0], float(inst_tot.iloc[0]) / n_meas
    del inst_d, inst_g

    pt = pd.crosstab(dec, df["pause"])
    pt = pt.reindex(columns=range(len(PAUSE_GROUPS)), fill_value=0)
    pshare = pt.div(pt.sum(axis=1), axis=0)
    chart_pause = {"x": dec_labels,
                   "series": [{"name": PAUSE_GROUPS[k],
                               "data": [round(float(pshare.loc[d, k]) * 100, 1) for d in decades]}
                              for k in range(len(PAUSE_GROUPS))]}
    pause_rows = [{"dec": dec_labels[i], "cells": [_pct(float(pshare.loc[d, k])) for k in range(len(PAUSE_GROUPS))]}
                  for i, d in enumerate(decades)]
    # Reliability over time: share of measurements after >72h vs <10h, first decade with ≥10,000 measurements vs last.
    big = [d for d in decades if pt.loc[d].sum() >= 10000]
    long_first = long_last = short_last = None
    if len(big) >= 2:
        d0, d1 = big[0], big[-1]
        long_first = (dec_labels[decades.index(d0)], float(pshare.loc[d0, 3]))
        long_last = (dec_labels[decades.index(d1)], float(pshare.loc[d1, 3]))
        short_last = float(pshare.loc[d1, 0])
    short_all = float((df["pause"] == 0).mean())

    # ---------------- oil layer ----------------
    oil = df[df["oil"] > 0]
    oil_wells = int(oil["id"].nunique())
    chart_oil = None
    oil_peak = None
    if oil_wells:
        p5 = (oil["y"] // 5 * 5)
        per = oil.groupby(p5)["id"].nunique().sort_index()
        start = int(per.index.min())
        idx5 = list(range(start, int(df["y"].max()) // 5 * 5 + 1, 5))
        per = per.reindex(idx5, fill_value=0)
        chart_oil = {"x": [f"{p}-{p + 4}" for p in idx5], "y": [int(v) for v in per.values],
                     "rows": [{"p": f"{p}-{p + 4}", "n": _int(per.loc[p])} for p in idx5]}
        pk = per.sort_index().idxmax()
        oil_peak = (f"{pk}-{pk + 4}", int(per.loc[pk]))
        oil_last_p = idx5[-1]
        oil_last_n = int(per.iloc[-1])
        oil_max = oil.groupby("id")["oil"].max()
        oil_top_ids = oil_max.sort_index().sort_values(ascending=False, kind="stable").head(8)
    else:
        oil_top_ids = pd.Series(dtype=float)

    # ---------------- notes ----------------
    nv = df["note"].value_counts()
    nv = nv[(nv > 0) & ~nv.index.astype(str).isin(NO_NOTE)]
    note_tot = pd.Series(nv.values, index=nv.index.astype(str)).sort_index().sort_values(
        ascending=False, kind="stable")
    note_rows = []
    for k, v in note_tot.head(TOP_N_NOTES).items():
        note_rows.append({"note": k, "n": int(v), "share": _pct(v / n_meas, 2)})
    rest = int(note_tot.iloc[TOP_N_NOTES:].sum())
    if rest:
        note_rows.append({"note": "הערות אחרות", "n": rest, "share": _pct(rest / n_meas, 2)})
    chart_notes = {"x": [r["note"] for r in note_rows], "y": [r["n"] for r in note_rows]}
    noted_share = float(note_tot.sum()) / n_meas

    # ---------------- long-record wells ----------------
    per_well = df.groupby("id").agg(n=("y", "size"), y0=("y", "min"), y1=("y", "max"))
    per_well = per_well.sort_index().sort_values("n", ascending=False, kind="stable")
    top_w = per_well.head(10)
    span = per_well["y1"] - per_well["y0"]
    long_span = int((span >= 50).sum())
    med_per_well = float(per_well["n"].median())

    need_names = set(top_w.index) | set(oil_top_ids.index)
    names = _well_names(raw, need_names)

    wells_rows = []
    for wid, r in top_w.iterrows():
        s = am[am["id"] == wid].set_index("y")["lvl"].sort_index()
        first5 = s[s.index <= s.index.min() + 4].median()
        last5 = s[s.index >= s.index.max() - 4].median()
        wells_rows.append({"id": str(int(wid)), "name": names.get(wid, ""), "n": _int(r["n"]),
                           "span": f"{int(r['y0'])}-{int(r['y1'])}",
                           "chg": f"{last5 - first5:+.2f}".replace("-", "−")})
    oil_rows = []
    for wid, v in oil_top_ids.items():
        o = oil[oil["id"] == wid]
        oil_rows.append({"id": str(int(wid)), "name": names.get(wid, ""), "max": f"{v:.2f}",
                         "n": _int(len(o)), "span": f"{int(o['y'].min())}-{int(o['y'].max())}"})
    del oil

    # ---------------- KPIs ----------------
    kpis = {
        "measurements": {"value": n_meas, "display": _int(n_meas), "tone": "brand"},
        "wells": {"value": wells_all, "display": _int(wells_all), "tone": "brand"},
        "span": {"value": y_max - y_min, "display": f"{y_min}–{y_max}", "tone": "brand"},
        "wells_last": {"value": wells_last, "display": _int(wells_last), "tone": "brand"},
    }
    if cmp_ok:
        tone = "ok" if chg_med >= STABLE_M else ("danger" if chg_med <= -STABLE_M else "brand")
        kpis["cmp_median"] = {"value": round(chg_med, 2), "display": _signed(chg_med), "tone": tone}
        rtone = "ok" if rising >= 0.5 else ("danger" if falling >= 0.5 else "brand")
        kpis["rising_share"] = {"value": round(rising, 3), "display": _pct(rising), "tone": rtone}
    if index_ok:
        last_d = float(yoy["median"].iloc[-1])  # yoy_last_year vs the year before
        tone = "ok" if last_d >= STABLE_M else ("danger" if last_d <= -STABLE_M else "brand")
        kpis["last_yoy"] = {"value": round(last_d, 2), "display": _signed(last_d), "tone": tone}

    # ---------------- insights ----------------
    def ins_wettest():
        if not wettest or wettest[1] < 0.5:
            return None
        y, v, n = wettest
        return (f"השנה עם העלייה החדה ביותר במפלסים היא {y}: חציון העלייה השנתית היה {_m(v)} מ׳ "
                f"ב-{_int(n)} קידוחים שנמדדו גם ב-{y - 1}.")

    def ins_driest():
        if not driest or driest[1] > -0.3:
            return None
        y, v, n = driest
        return (f"הירידה החדה ביותר נרשמה ב-{y}: חציון הירידה השנתית היה {_m(v)} מ׳ "
                f"ב-{_int(n)} קידוחים שנמדדו גם ב-{y - 1}.")

    def ins_cmp():
        if not cmp_ok:
            return None
        if abs(chg_med) < STABLE_M:
            head = f"בין {cmp_base} ל-{last_full} המפלס החציוני כמעט לא השתנה ({_m(chg_med)} מ׳)"
        else:
            word = "עלה" if chg_med > 0 else "ירד"
            head = f"בין {cmp_base} ל-{last_full} המפלס {word} בחציון של {_m(chg_med)} מ׳"
        return (f"{head} ב-{_int(len(chg))} קידוחים שנמדדו בשתי השנים: ב-{_pct(rising)} מהם המפלס עלה "
                f"ביותר מחצי מטר, וב-{_pct(falling)} ירד ביותר מחצי מטר.")

    def ins_index():
        if not index_ok:
            return None
        base = chart_index["base"]
        if abs(cum_last - cum_low) < 0.5:
            return None
        def pos(v):
            if abs(v) < 0.005:
                return "בגובה נקודת הבסיס"
            return f"{_m(v)} מ׳ {'מעל' if v > 0 else 'מתחת ל'}נקודת הבסיס"
        return (f"מדד השינוי המצטבר (סכום חציוני השינוי השנתי מאז {base}) הגיע לשפל ב-{cum_low_year}, "
                f"{pos(cum_low)}, ועמד ב-{yoy_last_year} על {pos(cum_last)}.")

    def ins_season():
        if not season_ok or amp < 0.1:
            return None
        return (f"מחזור עונתי ברור: המפלס גבוה ביותר ב{MONTHS_HE[peak_m]} ונמוך ביותר ב{MONTHS_HE[low_m]}, "
                f"בפער חציוני של {_m(amp)} מ׳ בין השיא לשפל בתוך השנה.")

    def ins_coverage():
        peak_y = int(yearly_w.sort_index().idxmax())
        peak = int(yearly_w.loc[peak_y])
        now = int(yearly_w.loc[last_full])
        if peak_y == last_full or now > 0.8 * peak:
            return None
        return (f"מספר הקידוחים הנמדדים בשנה ירד מ-{_int(peak)} בשיא ({peak_y}) ל-{_int(now)} ב-{last_full}, "
                f"ירידה של {_pct(1 - now / peak, 0)}.")

    def ins_pause():
        if not long_first or abs(long_last[1] - long_first[1]) < 0.1:
            return None
        word = "עלה" if long_last[1] > long_first[1] else "ירד"
        return (f"שיעור המדידות שנלקחו אחרי הפסקת שאיבה של יותר מ-72 שעות {word} מ-{_pct(long_first[1], 0)} "
                f"בשנים {long_first[0]} ל-{_pct(long_last[1], 0)} בשנים {long_last[0]}; "
                f"רק {_pct(short_last)} מהמדידות האחרונות נלקחו אחרי פחות מ-10 שעות.")

    def ins_oil():
        if not oil_wells or not oil_peak:
            return None
        return (f"ב-{_int(oil_wells)} קידוחים נמדדה שכבת שמן מעל המים. השיא היה בשנים {oil_peak[0]}, "
                f"עם {_int(oil_peak[1])} קידוחים כאלה.")

    def ins_artesian():
        if not len(dep_known):
            return None
        parts = [f"ב-{last_full} עומק המים החציוני היה {_m(dep_med, 1)} מ׳ מתחת לנקודת המדידה"]
        if below_sea:
            parts.append(f"ב-{_int(below_sea)} קידוחים המפלס מתחת לפני הים")
        if artesian:
            parts.append(f"וב-{_int(artesian)} המים עלו מעל פני הקרקע (עומק שלילי)")
        return ", ".join(parts) + "."

    def ins_inst():
        if top_inst_share < 0.4:
            return None
        return (f"הגוף המודד העיקרי, {top_inst_name}, ביצע {_pct(top_inst_share, 0)} מכלל המדידות במאגר "
                f"({_int(inst_tot.iloc[0])}).")

    rules = [("cmp", ins_cmp()), ("wettest", ins_wettest()), ("driest", ins_driest()),
             ("index", ins_index()), ("season", ins_season()), ("coverage", ins_coverage()),
             ("depth", ins_artesian()), ("pause", ins_pause()), ("oil", ins_oil()), ("inst", ins_inst())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---------------- labels / ledes ----------------
    partial_note = (f" השנה {y_max} חלקית (חודשים מדודים: {months_by_year.get(y_max, 0)}) ואינה נכללת בהשוואות."
                    if last_partial else "")
    labels = {
        "lede": (f"המאגר מרכז {_int(n_meas)} מדידות של מפלס מי התהום ב-{_int(wells_all)} קידוחים בישראל, "
                 f"משנת {y_min} ועד {y_max}. לכל מדידה: תאריך, מפלס המים ביחס לפני הים, העומק עד פני המים, "
                 f"משך הפסקת השאיבה לפני המדידה והגוף המודד. ב-{last_full} נמדדו {_int(wells_last)} קידוחים."
                 + partial_note),
        "kpi_measurements": "מדידות מפלס",
        "kpi_wells": "קידוחים במאגר",
        "kpi_span": "טווח השנים",
        "kpi_wells_last": f"קידוחים שנמדדו ב-{last_full}",
        "kpi_cmp_median": f"שינוי חציוני במפלס, {cmp_base}-{last_full} (מ׳)",
        "kpi_rising_share": f"קידוחים שמפלסם עלה ביותר מחצי מטר, {cmp_base}-{last_full}",
        "kpi_last_yoy": (f"שינוי חציוני במפלס ב-{yoy_last_year} לעומת {yoy_last_year - 1} (מ׳)"
                         if index_ok else ""),
        "lookup_title": "איתור קידוח לפי שם או מספר זיהוי ←",
        "lookup_sub": "חיפוש חי בכל המדידות: שם הקידוח, מספר זיהוי, תאריך, גוף מודד והערות",
        "yearly_note": (f"מספר המדידות ומספר הקידוחים שנמדדו בכל שנה, {y_min} עד {y_max}. "
                        f"שיא הקידוחים הנמדדים: {_int(yearly_w.max())} ב-{int(yearly_w.sort_index().idxmax())}."),
        "yearly_aria": (f"גרף עמודות וקו: מדידות וקידוחים נמדדים לפי שנה, {y_min} עד {y_max}. "
                        f"ב-{last_full} נמדדו {_int(yearly_w.loc[last_full])} קידוחים."),
        "season_note": (f"סטיית המפלס בכל חודש מהממוצע השנתי של אותו קידוח, חציון על פני {_int(anom_n)} "
                        f"שנות-קידוח עם שש מדידות לפחות בשנה."),
        "season_aria": (f"גרף עמודות: סטייה עונתית חציונית של המפלס לפי חודש. שיא ב{MONTHS_HE[peak_m]}, "
                        f"שפל ב{MONTHS_HE[low_m]}.") if season_ok else "",
        "season_caption": "סטייה עונתית חציונית של המפלס לפי חודש (מ׳)",
        "depth_note": (f"העומק עד פני המים במדידה האחרונה של כל קידוח שנמדד ב-{last_full} "
                       f"({_int(wells_last)} קידוחים). עומק שלילי: המים מעל נקודת המדידה."),
        "depth_aria": (f"גרף עמודות: התפלגות העומק עד פני המים ב-{last_full}. "
                       f"חציון {_m(dep_med, 1) if dep_med is not None else ''} מ׳."),
        "depth_caption": f"קידוחים לפי עומק עד פני המים, {last_full}",
        "inst_note": (f"מספר המדידות בכל עשור לפי הגוף המודד (חמשת הגופים הגדולים, השאר ב'אחר'). "
                      f"{top_inst_name} ביצע {_pct(top_inst_share, 0)} מהמדידות."),
        "inst_aria": f"גרף עמודות מוערמות: מדידות לפי עשור וגוף מודד. {top_inst_name} מוביל.",
        "inst_caption": "מדידות לפי עשור וגוף מודד",
        "pause_note": ("משך הפסקת השאיבה לפני המדידה, כאחוז מהמדידות בכל עשור. לפי רשות המים, "
                       "יש להתייחס בזהירות למדידות שנלקחו אחרי הפסקה של פחות מ-15 שעות."),
        "pause_aria": (f"גרף עמודות מוערמות באחוזים: משך הפסקת השאיבה לפי עשור. "
                       f"{_pct(short_all)} מכלל המדידות נלקחו אחרי פחות מ-10 שעות."),
        "pause_caption": "משך הפסקת השאיבה לפני המדידה לפי עשור (אחוז מהמדידות)",
        "oil_note": (f"מספר הקידוחים שבהם נמדדה שכבת שמן (דלק) צפה מעל המים, בכל תקופה של חמש שנים. "
                     f"סך הכול {_int(oil_wells)} קידוחים."),
        "oil_aria": (f"גרף עמודות: קידוחים עם שכבת שמן לפי תקופה. שיא ב-{oil_peak[0]} עם {_int(oil_peak[1])} קידוחים."
                     if oil_peak else ""),
        "oil_caption": "קידוחים עם שכבת שמן לפי תקופה של חמש שנים",
        "oil_top_caption": "הקידוחים עם שכבת השמן העבה ביותר שנמדדה",
        "notes_note": (f"הערות המודד שצורפו ל-{_pct(noted_share)} מהמדידות (מדידות ללא הערה אינן מוצגות)."),
        "notes_aria": (f"גרף עמודות: מדידות לפי סוג הערה. המובילה: {note_rows[0]['note']}."
                       if note_rows else ""),
        "notes_caption": "מדידות לפי סוג הערת המודד",
        "wells_note": (f"עשרת הקידוחים עם מספר המדידות הגדול ביותר. חציון המדידות לקידוח: {_int(med_per_well)}; "
                       f"ב-{_int(long_span)} קידוחים רשומות מדידות על פני 50 שנה ומעלה. "
                       "השינוי: חציון חמש השנים האחרונות פחות חציון חמש השנים הראשונות."),
        "wells_caption": "הקידוחים עם מספר המדידות הגדול ביותר",
        "notes_text": ("בסיס הנתונים של המפלסים מתאר את המפלסים בקידוחי מי התהום. יש לקחת בחשבון את זמן "
                       "ההפסקה לפי ביצוע המדידה ולהתייחס בערבון מוגבל למדידות, בהן זמן ההפסקה הוא פחות מ-15 שעות."),
    }
    if index_ok:
        labels["index_note"] = (
            f"העמודות: חציון השינוי במפלס השנתי (חציון המדידות של כל קידוח בשנה) בקידוחים שנמדדו בשנה ובשנה "
            f"שלפניה. הקו: סכום מצטבר של החציונים מאז {chart_index['base']}, מדד גס למצב מי התהום. "
            f"נכללות שנים עם {MIN_PAIRS} קידוחים משווים לפחות" + (f", עד {last_full}." if last_partial else "."))
        labels["index_aria"] = (
            f"גרף עמודות וקו: שינוי שנתי חציוני במפלס ומדד מצטבר, {chart_index['x'][0]} עד {chart_index['x'][-1]}. "
            f"העלייה החדה ביותר ב-{wettest[0]}, הירידה החדה ביותר ב-{driest[0]}.")
    if cmp_ok:
        labels["change_note"] = (
            f"השינוי בחציון המפלס השנתי בין {cmp_base} ל-{last_full}, ב-{_int(len(chg))} קידוחים שנמדדו בשתי השנים. "
            f"חציון: {_m(chg_med)} מ׳ ({'עלייה' if chg_med > 0 else 'ירידה' if chg_med < 0 else 'ללא שינוי'}).")
        labels["change_aria"] = (
            f"גרף עמודות: קידוחים לפי שינוי במפלס בין {cmp_base} ל-{last_full}. "
            f"ב-{_pct(rising)} עלייה של יותר מחצי מטר, ב-{_pct(falling)} ירידה של יותר מחצי מטר.")
        labels["change_caption"] = f"קידוחים לפי שינוי במפלס, {cmp_base}-{last_full}"

    temporal = f"{y_min}/{y_max}"
    summary = (f"איתור מפלס מי תהום לפי קידוח: {_int(n_meas)} מדידות ב-{_int(wells_all)} קידוחים, "
               f"{y_min}-{y_max}. מגמות, עונתיות ועומק המים.")

    return {
        "agent_data": {"summary_he": summary, "dataset_kind": "timeseries",
                       "temporal_coverage": temporal, "spatial_coverage": "ישראל"},
        "kpis": kpis,
        "charts": {"yearly": chart_yearly, "index": chart_index, "change": chart_change,
                   "season": chart_season, "depth": chart_depth, "inst": chart_inst,
                   "pause": chart_pause, "oil": chart_oil, "notes": chart_notes},
        "tables": {"inst_cols": inst_order, "inst": inst_rows, "pause_cols": PAUSE_GROUPS,
                   "pause": pause_rows, "wells": wells_rows, "oil_top": oil_rows,
                   "notes": [{"note": r["note"], "n": _int(r["n"]), "share": r["share"]} for r in note_rows],
                   "depth": [{"band": r["band"], "n": _int(r["n"]), "share": r["share"]} for r in dep_rows]},
        "flags": {"index": index_ok, "change": cmp_ok, "season": season_ok,
                  "oil": bool(chart_oil), "notes": bool(note_rows)},
        "insights": insights,
        "labels": labels,
    }
