"""Water Authority hydrometric stations: water-quality samples (major ions).

One long table: one row per (station, sample date, parameter). Every number
on the page is computed here from the data. Insight rules return a sentence
or None when their premise does not hold.
"""
import pandas as pd

SIGN_COL = "סימן גדול/קטן"

# Hebrew names for known parameter codes (fallback: the dataset's own short
# description + code, so a new parameter still flows through).
PARAM_HE = {
    "CL": "כלוריד", "NO3": "חנקה", "CA": "סידן", "HCO3": "ביקרבונט",
    "MG": "מגנזיום", "SO4": "סולפט", "K": "אשלגן", "NA": "נתרן",
    "BR": "ברומיד", "SILT": "סחופת (מוצקים מרחפים)", "EC": "מוליכות חשמלית",
    "TDS": "מוצקים מומסים", "PHFD": "חומציות (שדה)", "HARD": "קשיות",
    "B": "בורון", "T": "טמפרטורה", "ECFD": "מוליכות חשמלית (שדה)",
    "DO": "חמצן מומס", "ORP": "פוטנציאל חמצון-חיזור", "SR": "סטרונציום",
    "TN-N": "חנקן כללי", "TOC": "פחמן אורגני כללי", "PO4": "פוספט",
    "F": "פלואוריד", "TURB": "עכירות", "NO2": "ניטריט",
}
UNIT_HE = {
    "MG/L": "מ״ג/ל", "MS/CM": "מילי-סימנס/ס״מ", "UNIT": "יחידות",
    "CELSIUS": "מעלות צלזיוס", "MV": "מילי-וולט", "MICROGR/L": "מיקרוגרם/ל",
    "NTU": "יחידות עכירות",
}
MAJOR_IONS = ["CA", "MG", "NA", "K", "HCO3", "SO4", "CL", "NO3"]
MONTHS_HYDRO = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
MONTHS_HE = {1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל", 5: "מאי", 6: "יוני",
             7: "יולי", 8: "אוגוסט", 9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר",
             12: "דצמבר"}
NO3_BANDS = [(-1e9, 10, "עד 10"), (10, 25, "10 עד 25"), (25, 50, "25 עד 50"),
             (50, 70, "50 עד 70"), (70, 1e12, "מעל 70")]

TOP_PARAMS = 12
TOP_STREAMS = 12
TOP_STATIONS = 15
TOP_SALTY = 15
TREND_STATIONS = 5
HEAT_STATIONS = 12
RECENT_YEARS = 10      # window (hydrological years) for "current" chloride
MIN_RECENT_CL = 5      # min chloride samples per station inside the window
MIN_DECADE_CL = 3      # min chloride samples per station-decade for the trend
MIN_TREND_DECADES = 4  # long-record stations must span this many decades
MIN_NO3_DECADE = 30    # min nitrate samples for a decade to enter the band chart
ACTIVE_YEARS = 2       # sampled in the last N hydrological years = "active"


def _i(n):
    return f"{int(round(n)):,}"


def _n(v, d=1):
    return f"{v:,.{d}f}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _clean_name(s):
    return " ".join(s.replace("''", "״").replace('"', "״").split())


def _prepare(df):
    out = pd.DataFrame({
        "sid": df["מספר זיהוי"].str.strip(),
        "name": df["שם עברית"].map(_clean_name),
        "lab": df["מעבדה"].str.strip(),
        "hy_raw": df["שנה הידרולוגית"].str.strip(),
        "date": pd.to_datetime(df["תאריך דגימה"].str.strip(),
                               format="%d/%m/%Y %H:%M", errors="coerce"),
        "sign": df[SIGN_COL].str.strip(),
        "value": pd.to_numeric(df["תוצאה"].str.replace(",", "").str.strip(),
                               errors="coerce"),
        "param": df["סמל פרמטר"].str.strip(),
        "pkey": df["סמל פרמטר"].str.strip().str.upper(),
        "desc": df["תאור מקוצר"].str.strip(),
        "unit": df["יחידת מידה"].str.strip(),
    })
    out = out[(out["sid"] != "") & (out["param"] != "")]
    out = out.dropna(subset=["date"])
    # Hydrological year = Oct..Sep, labelled by its end year (the column's
    # "1954/1955" format). Derived from the date so a blank label still works.
    out["hy"] = (out["date"].dt.year + (out["date"].dt.month >= 10)).astype(int)
    out["day"] = out["date"].dt.normalize()
    out["month"] = out["date"].dt.month.astype(int)
    out["decade"] = (out["date"].dt.year // 10 * 10).astype(int)
    out["stream"] = out["name"].str.split("-").str[0].str.strip()
    out.loc[out["stream"] == "", "stream"] = out["name"]
    return out


def _hy_label(y):
    return f"{y - 1}/{y}"


_LAST_YEAR = [None]


def _dec_label(d):
    # A decade still in progress ends at the data's last year, not at d+9.
    end = d + 9
    if _LAST_YEAR[0] is not None and _LAST_YEAR[0] < end:
        end = _LAST_YEAR[0]
    return f"{d}-{end}" if end > d else f"{d}"


def _mode(s):
    vc = s.value_counts()
    top = vc[vc == vc.max()].index
    return sorted(top)[0]


def _param_name(pkey, desc):
    if pkey in PARAM_HE:
        return PARAM_HE[pkey]
    return f"{desc} ({pkey})" if desc else pkey


def _unit_name(u):
    return UNIT_HE.get(u.upper(), u)


def _top_with_other(series, n):
    s = series.sort_index().sort_values(ascending=False, kind="stable")
    head = s.iloc[:n]
    rest = int(s.iloc[n:].sum())
    names, vals = [str(k) for k in head.index], [int(v) for v in head]
    return names, vals, rest


def compute(frames):
    df = _prepare(frames["samples"])
    total = int(len(df))

    # ── stations ────────────────────────────────────────────────────────
    st_name = df.groupby("sid")["name"].agg(_mode)
    st = df.groupby("sid").agg(n=("value", "size"), first=("hy", "min"),
                               last=("hy", "max"), events=("day", "nunique"))
    st["name"] = st_name
    n_stations = int(len(st))
    max_hy, min_hy = int(df["hy"].max()), int(df["hy"].min())
    first_year, last_year = int(df["date"].dt.year.min()), int(df["date"].dt.year.max())
    last_date = df["date"].max()
    _LAST_YEAR[0] = last_year
    active = st[st["last"] > max_hy - ACTIVE_YEARS]
    n_active = int(len(active))

    events = df[["sid", "day"]].drop_duplicates()
    n_events = int(len(events))

    # ── per hydrological year, stacked by lab ───────────────────────────
    by_hy = df.groupby("hy").size().sort_index()
    years = list(range(min_hy, max_hy + 1))
    labs = (df.groupby("lab").size().sort_index()
            .sort_values(ascending=False, kind="stable"))
    lab_series = []
    for lab in labs.index:
        c = df[df["lab"] == lab].groupby("hy").size()
        lab_series.append({"name": lab if lab else "לא צוין",
                           "data": [int(c.get(y, 0)) for y in years]})
    hy_counts = [int(by_hy.get(y, 0)) for y in years]
    peak_hy = int(by_hy.sort_index().idxmax())
    latest_n = int(by_hy.get(max_hy, 0))
    # A hydrological year ends in September. If the newest sample is earlier
    # than September, the latest year is still partial in the data: label it
    # so, and run the year-over-year comparison on the latest COMPLETE year.
    last_month = int(df["date"].max().month)
    latest_partial = last_month != 9
    cmp_hy = max_hy - 1 if latest_partial else max_hy
    cmp_n = int(by_hy.get(cmp_hy, 0))
    prev = [int(by_hy.get(y, 0)) for y in range(cmp_hy - 5, cmp_hy) if y >= min_hy]
    prev_med = float(pd.Series(prev).median()) if prev else 0.0
    dec_tot = df.groupby("decade").size().sort_index()

    # ── parameters ──────────────────────────────────────────────────────
    pg = df.groupby("pkey").agg(n=("value", "size"), st=("sid", "nunique"),
                                desc=("desc", _mode), unit=("unit", _mode))
    pg = pg.sort_index().sort_values("n", ascending=False, kind="stable")
    n_params = int(len(pg))
    ptop = pg.iloc[:TOP_PARAMS]
    params_rest = int(pg["n"].iloc[TOP_PARAMS:].sum())
    params_chart = {
        "names": [_param_name(k, r.desc) for k, r in ptop.iterrows()],
        "values": [int(v) for v in ptop["n"]],
        "other": params_rest,
        "other_count": int(max(len(pg) - TOP_PARAMS, 0)),
    }
    params_table = [{"code": k, "name": _param_name(k, r.desc),
                     "unit": _unit_name(r.unit), "n": int(r.n), "st": int(r.st)}
                    for k, r in ptop.iterrows()]

    # ── streams ─────────────────────────────────────────────────────────
    sg = df.groupby("stream").agg(n=("value", "size"), st=("sid", "nunique"))
    sg = sg.sort_index().sort_values("n", ascending=False, kind="stable")
    n_streams = int(len(sg))
    stop = sg.iloc[:TOP_STREAMS]
    streams_chart = {"names": [str(k) for k in stop.index],
                     "values": [int(v) for v in stop["n"]],
                     "stations": [int(v) for v in stop["st"]],
                     "other": int(sg["n"].iloc[TOP_STREAMS:].sum()),
                     "other_count": int(max(len(sg) - TOP_STREAMS, 0))}

    # ── top stations ────────────────────────────────────────────────────
    stt = st.reset_index().sort_values(["n", "sid"], ascending=[False, True],
                                       kind="stable").iloc[:TOP_STATIONS]
    stations_table = [{"sid": r.sid, "name": r.name, "n": int(r.n),
                       "events": int(r.events),
                       "span": f"{int(r.first)}-{int(r.last)}"}
                      for r in stt.itertuples()]
    stations_chart = {"names": [r["name"] for r in stations_table],
                      "values": [r["n"] for r in stations_table],
                      "events": [r["events"] for r in stations_table]}

    # ── station activity: decade of last sample ─────────────────────────
    last_dec = (st["last"] // 10 * 10).astype(int)
    ld = last_dec.value_counts().sort_index()
    activity = {"x": [_dec_label(int(d)) for d in ld.index],
                "y": [int(v) for v in ld]}

    # ── sampling month (hydrological order) ─────────────────────────────
    ev_m = events.assign(month=events["day"].dt.month).groupby("month").size()
    months = {"x": [MONTHS_HE[m] for m in MONTHS_HYDRO],
              "y": [int(ev_m.get(m, 0)) for m in MONTHS_HYDRO]}
    wet = sum(int(ev_m.get(m, 0)) for m in (12, 1, 2, 3))
    peak_month = MONTHS_HE[int(ev_m.sort_index().idxmax())] if len(ev_m) else ""

    # ── chloride: recent salinity ranking ───────────────────────────────
    cl = df[(df["pkey"] == "CL") & df["value"].notna()]
    rec = cl[cl["hy"] > max_hy - RECENT_YEARS]
    rg = rec.groupby("sid")["value"].agg(["median", "size"])
    rg = rg[rg["size"] >= MIN_RECENT_CL]
    rg["name"] = st_name.reindex(rg.index)
    rg = rg.reset_index().sort_values(["median", "sid"], ascending=[False, True],
                                      kind="stable")
    salty = rg.iloc[:TOP_SALTY]
    salty_table = [{"name": r.name, "median": round(float(r.median), 1),
                    "n": int(r.size)} for r in salty.itertuples()]
    n_ranked = int(len(rg))
    overall_med = float(rg["median"].median()) if n_ranked else 0.0
    n_over_1000 = int((rg["median"] >= 1000).sum())

    # ── chloride: long-record stations by decade ────────────────────────
    cd = cl.groupby(["sid", "decade"])["value"].agg(["median", "size"]).reset_index()
    cd = cd[cd["size"] >= MIN_DECADE_CL]
    span = cd.groupby("sid")["decade"].nunique()
    cl_n = cl.groupby("sid").size()
    long_ids = [s for s in span[span >= MIN_TREND_DECADES].index]
    long_ids = sorted(long_ids, key=lambda s: (-int(cl_n[s]), s))[:TREND_STATIONS]
    trend_decades = sorted(cd[cd["sid"].isin(long_ids)]["decade"].unique().tolist())
    trend_series, trend_change = [], []
    for s in long_ids:
        sub = cd[cd["sid"] == s].set_index("decade")["median"]
        trend_series.append({"name": str(st_name[s]),
                             "data": [round(float(sub[d]), 1) if d in sub.index else None
                                      for d in trend_decades]})
        sub = sub.sort_index()
        trend_change.append((s, int(sub.index[0]), float(sub.iloc[0]),
                             int(sub.index[-1]), float(sub.iloc[-1])))
    trend_rows = [{"decade": _dec_label(int(d)),
                   "vals": [ser["data"][i] for ser in trend_series]}
                  for i, d in enumerate(trend_decades)]

    # ── nitrate bands by decade ─────────────────────────────────────────
    no3 = df[(df["pkey"] == "NO3") & df["value"].notna()]
    nd = no3.groupby("decade").size().sort_index()
    no3_decs = [int(d) for d in nd.index if nd[d] >= MIN_NO3_DECADE]
    no3_series = []
    for lo, hi, lab in NO3_BANDS:
        row = []
        for d in no3_decs:
            sub = no3[no3["decade"] == d]["value"]
            row.append(round(float(((sub > lo) & (sub <= hi)).mean() * 100), 1))
        no3_series.append({"name": lab, "data": row})
    no3_rows = [{"decade": _dec_label(d), "n": int(nd[d]),
                 "vals": [ser["data"][i] for ser in no3_series]}
                for i, d in enumerate(no3_decs)]
    high_share = {d: float((no3[no3["decade"] == d]["value"] > 50).mean())
                  for d in no3_decs}

    # ── major-ion heatmap (recent window) ───────────────────────────────
    ions_present = [p for p in MAJOR_IONS if p in set(df["pkey"])]
    ion = df[df["pkey"].isin(ions_present) & df["value"].notna()
             & (df["hy"] > max_hy - RECENT_YEARS)]
    ion_counts = ion.groupby("sid").size()
    heat_ids = sorted(ion_counts.index, key=lambda s: (-int(ion_counts[s]), s))[:HEAT_STATIONS]
    med = ion[ion["sid"].isin(heat_ids)].groupby(["sid", "pkey"])["value"].median()
    col_max = {p: float(med.xs(p, level="pkey").max()) if p in med.index.get_level_values("pkey") else 0.0
               for p in ions_present}
    cells, heat_rows = [], []
    for yi, s in enumerate(heat_ids):
        vals = []
        for xi, p in enumerate(ions_present):
            v = med.get((s, p))
            if v is None or pd.isna(v):
                vals.append(None)
                continue
            v = round(float(v), 1)
            vals.append(v)
            norm = round(v / col_max[p], 3) if col_max[p] > 0 else 0.0
            cells.append([xi, yi, norm, v])
        heat_rows.append({"name": str(st_name[s]), "vals": vals})
    heat = {"x": [PARAM_HE.get(p, p) for p in ions_present],
            "y": [r["name"] for r in heat_rows], "cells": cells}

    # ── censored values ─────────────────────────────────────────────────
    below = df[df["sign"] == "<"]
    n_below = int(len(below))
    below_top = below.groupby("pkey").size().sort_index().sort_values(
        ascending=False, kind="stable")

    # ── insights ────────────────────────────────────────────────────────
    ins = []

    def add(i, t):
        if t:
            ins.append({"id": i, "text_he": t})

    # volume over time
    t = None
    if len(dec_tot) >= 2:
        dmax = int(dec_tot.sort_index().idxmax())
        share = dec_tot[dmax] / total
        t = (f"בעשור {_dec_label(dmax)} נרשמו {_i(dec_tot[dmax])} מדידות "
             f"({_pct(share)} מכלל המאגר), יותר מבכל עשור אחר, והשנה "
             f"ההידרולוגית העמוסה ביותר היא {_hy_label(peak_hy)} עם "
             f"{_i(by_hy[peak_hy])} מדידות.")
    add("volume", t)

    # latest complete hydrological year vs the five before it
    t = None
    if prev_med > 0 and len(prev) == 5 and cmp_hy >= min_hy:
        ratio = cmp_n / prev_med
        which = ("האחרונה השלמה במאגר" if latest_partial
                 else "האחרונה במאגר")
        if ratio < 0.7:
            t = (f"בשנה ההידרולוגית {which} ({_hy_label(cmp_hy)}) נרשמו "
                 f"{_i(cmp_n)} מדידות בלבד, לעומת חציון של {_i(prev_med)} "
                 f"בחמש השנים שקדמו לה.")
        elif ratio > 1.3:
            t = (f"בשנה ההידרולוגית {which} ({_hy_label(cmp_hy)}) נרשמו "
                 f"{_i(cmp_n)} מדידות, יותר מחציון של {_i(prev_med)} "
                 f"בחמש השנים שקדמו לה.")
        if t and latest_partial:
            t += (f" השנה {_hy_label(max_hy)} חלקית במאגר (עד {MONTHS_HE[last_month]}), "
                  f"עם {_i(latest_n)} מדידות עד כה.")
    add("latest", t)

    # chloride is the backbone parameter
    t = None
    if "CL" in pg.index and pg.index[0] == "CL":
        t = (f"כלוריד הוא הפרמטר הנמדד ביותר: {_i(pg.loc['CL', 'n'])} מדידות "
             f"({_pct(pg.loc['CL', 'n'] / total)}) ב-{_i(pg.loc['CL', 'st'])} "
             f"תחנות, מתוך {_i(n_params)} פרמטרים במאגר.")
    add("chloride_backbone", t)

    # saltiest station
    t = None
    if n_ranked >= 5 and overall_med > 0:
        top = rg.iloc[0]
        ratio = top["median"] / overall_med
        if ratio >= 3:
            t = (f"התחנה המלוחה ביותר בעשר השנים ההידרולוגיות האחרונות היא "
                 f"{top['name']}, עם כלוריד חציוני של {_n(top['median'])} מ״ג/ל, "
                 f"פי {_n(ratio)} מהחציון של {_i(n_ranked)} התחנות שנבדקו "
                 f"({_n(overall_med)} מ״ג/ל)")
            t += (f"; ב-{_i(n_over_1000)} תחנות החציון הוא {_i(1000)} מ״ג/ל ומעלה."
                  if n_over_1000 >= 2 else ".")
    add("saltiest", t)

    # biggest long-term chloride shift
    t = None
    best = None
    for s, d0, v0, d1, v1 in trend_change:
        if v0 > 0 and d1 > d0:
            ch = (v1 - v0) / v0
            if abs(ch) >= 0.3 and (best is None or abs(ch) > abs(best[1])):
                best = (s, ch, d0, v0, d1, v1)
    if best:
        s, ch, d0, v0, d1, v1 = best
        word = "עלה" if ch > 0 else "ירד"
        t = (f"בתחנה {st_name[s]} {word} הכלוריד החציוני מ-{_n(v0)} מ״ג/ל "
             f"בעשור {_dec_label(d0)} ל-{_n(v1)} מ״ג/ל בעשור {_dec_label(d1)} "
             f"({'+' if ch > 0 else '−'}{_pct(abs(ch), 0)}), השינוי הגדול ביותר "
             f"בין {_i(len(trend_change))} התחנות בעלות הרצף הארוך ביותר.")
    add("cl_shift", t)

    # nitrate high-band share, first vs last qualifying decade
    t = None
    if len(no3_decs) >= 2:
        d0, d1 = no3_decs[0], no3_decs[-1]
        a, b = high_share[d0], high_share[d1]
        if abs(a - b) >= 0.01:
            word = "ירד" if b < a else "עלה"
            t = (f"שיעור דגימות החנקה מעל {_i(50)} מ״ג/ל {word} מ-{_pct(a)} "
                 f"בעשור {_dec_label(d0)} ל-{_pct(b)} בעשור {_dec_label(d1)}.")
        else:
            t = (f"שיעור דגימות החנקה מעל {_i(50)} מ״ג/ל נותר יציב, כ-{_pct(b)}, "
                 f"בין העשור {_dec_label(d0)} לעשור {_dec_label(d1)}.")
    add("nitrate", t)

    # stream concentration
    t = None
    if n_streams >= 3:
        lead = sg.index[0]
        share = sg["n"].iloc[0] / total
        if share >= 0.15:
            t = (f"ב-{_i(sg['st'].iloc[0])} התחנות של {lead} נרשמו {_pct(share)} "
                 f"מהמדידות ({_i(sg['n'].iloc[0])}), יותר מבכל נחל אחר.")
    add("stream", t)

    # active stations
    t = None
    if n_stations >= 5:
        t = (f"{_i(n_active)} מתוך {_i(n_stations)} התחנות נדגמו בשתי השנים "
             f"ההידרולוגיות האחרונות במאגר ({_hy_label(max_hy - 1)} ו-{_hy_label(max_hy)}); "
             f"בשאר לא נרשמה דגימה מאז.")
    add("active", t)

    # censored values
    t = None
    if n_below >= 10 and len(below_top):
        p = below_top.index[0]
        lead_word = "רובן" if below_top.iloc[0] / n_below > 0.5 else "הנפוץ ביניהן"
        t = (f"{_i(n_below)} תוצאות ({_pct(n_below / total)}) מסומנות כקטנות מסף "
             f"הגילוי; {lead_word}: {_param_name(p, '')} ({_i(below_top.iloc[0])}). "
             f"הגרפים משתמשים בערך המדווח.")
    add("censored", t)

    # ── KPIs ────────────────────────────────────────────────────────────
    latest_tone = ("warn" if not latest_partial and prev_med > 0
                   and latest_n < 0.5 * prev_med else "brand")
    active_share = n_active / n_stations if n_stations else 0
    kpis = {
        "total": {"value": total, "display": _i(total), "tone": "brand"},
        "stations": {"value": n_stations, "display": _i(n_stations), "tone": "brand"},
        "params": {"value": n_params, "display": _i(n_params), "tone": "brand"},
        "span": {"value": [first_year, last_year],
                 "display": f"{first_year}–{last_year}", "tone": "brand"},
        "active": {"value": n_active, "display": _i(n_active),
                   "tone": "info" if active_share >= 0.3 else "warn"},
        "latest": {"value": latest_n, "display": _i(latest_n), "tone": latest_tone},
        "events": {"value": n_events, "display": _i(n_events), "tone": "brand"},
        "cl_median": {"value": round(overall_med, 1), "display": _n(overall_med),
                      "tone": "brand"},
    }

    last_date_he = last_date.strftime("%d.%m.%Y")
    summary = (f"תוצאות דיגום איכות מים בנחלים לפי תחנה ופרמטר (כלוריד, חנקה, יונים "
               f"ראשיים): {_i(total)} מדידות ב-{_i(n_stations)} תחנות הידרומטריות, "
               f"{first_year} עד {last_year}.")

    labels = {
        "lede": (f"השירות ההידרולוגי של רשות המים דוגם מי שיטפונות וזרימות בסיס בנחלים "
                 f"ובוחן את הרכבם הכימי. המאגר כולל {_i(total)} תוצאות מ-{_i(n_events)} "
                 f"אירועי דיגום ב-{_i(n_stations)} תחנות על {_i(n_streams)} נחלים ואתרים, "
                 f"מ-{first_year} ועד {last_date_he}."),
        "latest_kpi": (f"מדידות בשנה ההידרולוגית {_hy_label(max_hy)}"
                       + (f" (חלקית, עד {MONTHS_HE[last_month]})" if latest_partial else "")),
        "active_kpi": f"תחנות שנדגמו ב-{_hy_label(max_hy - 1)} או ב-{_hy_label(max_hy)}",
        "cl_kpi": (f"חציון הכלוריד בתחנות, מ״ג/ל ({_hy_label(max_hy - RECENT_YEARS + 1)} "
                   f"עד {_hy_label(max_hy)})"),
        "years_note": (f"מספר תוצאות המדידה בכל שנה הידרולוגית (אוקטובר עד ספטמבר), "
                       f"לפי מעבדה. השיא: {_hy_label(peak_hy)} עם {_i(by_hy[peak_hy])} מדידות."),
        "years_aria": (f"גרף עמודות מוערמות: מדידות לפי שנה הידרולוגית ומעבדה, "
                       f"{_hy_label(min_hy)} עד {_hy_label(max_hy)}. השיא ב-{_hy_label(peak_hy)} "
                       f"עם {_i(by_hy[peak_hy])} מדידות."),
        "params_note": (f"{_i(TOP_PARAMS)} הפרמטרים הנמדדים ביותר מתוך {_i(n_params)}"
                        + (f"; {_i(params_chart['other_count'])} פרמטרים נוספים "
                           f"({_i(params_rest)} מדידות) מקובצים תחת ״אחר״." if params_rest else ".")),
        "params_aria": (f"תרשים עמודות אופקי: מספר המדידות לפי פרמטר. המוביל: "
                        f"{params_chart['names'][0]} עם {_i(params_chart['values'][0])} מדידות."),
        "streams_note": (f"הנחל נגזר מהחלק הראשון בשם התחנה. {_i(TOP_STREAMS)} הנחלים "
                         f"המובילים מתוך {_i(n_streams)}"
                         + (f"; {_i(streams_chart['other_count'])} נוספים ({_i(streams_chart['other'])} "
                            f"מדידות) תחת ״אחר״." if streams_chart["other"] else ".")),
        "streams_aria": (f"תרשים עמודות אופקי: מדידות לפי נחל. המוביל: "
                         f"{streams_chart['names'][0]} עם {_i(streams_chart['values'][0])} מדידות."),
        "stations_note": (f"{_i(TOP_STATIONS)} התחנות עם מספר תוצאות המדידה הגבוה ביותר, "
                          f"עם מספר אירועי הדיגום (תאריכים) וטווח השנים ההידרולוגיות."),
        "stations_aria": (f"תרשים עמודות אופקי: {_i(TOP_STATIONS)} התחנות עם הכי הרבה מדידות. "
                          f"המובילה: {stations_chart['names'][0]} עם {_i(stations_chart['values'][0])}."),
        "activity_note": (f"מספר התחנות לפי העשור שבו נדגמו לאחרונה. {_i(n_active)} תחנות "
                          f"נדגמו בשתי השנים ההידרולוגיות האחרונות."),
        "activity_aria": (f"תרשים עמודות: תחנות לפי עשור הדיגום האחרון. "
                          f"{_i(activity['y'][-1])} תחנות נדגמו לאחרונה בעשור {activity['x'][-1]}."),
        "months_note": (f"אירועי דיגום (תחנה ותאריך) לפי חודש, בסדר השנה ההידרולוגית. "
                        f"דצמבר עד מרץ מרכזים {_pct(wet / n_events if n_events else 0)} "
                        f"מהאירועים, והחודש העמוס הוא {peak_month}."),
        "months_aria": (f"תרשים עמודות: אירועי דיגום לפי חודש. החודש העמוס ביותר: {peak_month}."),
        "salty_note": (f"כלוריד חציוני בכל תחנה בעשר השנים ההידרולוגיות האחרונות במאגר "
                       f"({_hy_label(max_hy - RECENT_YEARS + 1)} עד {_hy_label(max_hy)}), "
                       f"רק תחנות עם {_i(MIN_RECENT_CL)} דגימות כלוריד לפחות "
                       f"({_i(n_ranked)} תחנות). מוצגות {_i(len(salty_table))} המלוחות ביותר."),
        "salty_aria": ((f"תרשים עמודות אופקי: כלוריד חציוני בתחנות המלוחות ביותר. "
                        f"הגבוה: {salty_table[0]['name']} עם {_n(salty_table[0]['median'])} מ״ג/ל.")
                       if salty_table else "תרשים עמודות: כלוריד חציוני לפי תחנה."),
        "trend_note": (f"כלוריד חציוני לפי עשור ב-{_i(len(trend_series))} התחנות עם רצף "
                       f"מדידות הכלוריד הארוך ביותר (לפחות {_i(MIN_TREND_DECADES)} עשורים, "
                       f"ועשור נספר רק עם {_i(MIN_DECADE_CL)} דגימות לפחות). ציר לוגריתמי."),
        "trend_aria": (f"גרף קווים: כלוריד חציוני לפי עשור ב-{_i(len(trend_series))} תחנות "
                       f"ותיקות, ציר לוגריתמי."),
        "no3_note": (f"התפלגות דגימות החנקה לפי טווחי ריכוז (מ״ג/ל) בכל עשור עם "
                     f"{_i(MIN_NO3_DECADE)} דגימות לפחות."),
        "no3_aria": (f"תרשים עמודות מוערמות 100%: דגימות חנקה לפי טווח ריכוז ועשור, "
                     f"{no3_rows[0]['decade']} עד {no3_rows[-1]['decade']}."
                     if no3_rows else "תרשים עמודות: דגימות חנקה לפי טווח ריכוז."),
        "heat_note": (f"ריכוז חציוני (מ״ג/ל) של היונים הראשיים ב-{_i(len(heat_rows))} התחנות "
                      f"שנדגמו הכי הרבה בעשר השנים ההידרולוגיות האחרונות. הצבע יחסי לערך הגבוה "
                      f"בכל עמודה, והמספר הוא הריכוז עצמו."),
        "heat_aria": (f"מפת חום: ריכוז חציוני של {_i(len(ions_present))} יונים ראשיים "
                      f"ב-{_i(len(heat_rows))} תחנות."),
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["איכות מים", "נחלים", "הידרולוגיה", "כלוריד",
                               "חנקה", "רשות המים"],
            "related_ids": [
                "fb522ddd-bd25-4272-abef-eceab9aa268d",
                "5de14d12-d5d7-475d-ade1-5dbd0ef9d086",
                "d16214ba-56b3-417d-9342-6a144f215b9b",
                "096db5d2-dc8b-40c8-9fe7-2b839a435d92",
                "2b2882aa-5258-4ef4-bcb2-9747dbb62890",
            ],
            "temporal_coverage": f"{first_year}/{last_year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "years": {"x": [_hy_label(y) for y in years], "series": lab_series,
                      "total": hy_counts},
            "params": params_chart,
            "streams": streams_chart,
            "stations": stations_chart,
            "activity": activity,
            "months": months,
            "salty": {"names": [r["name"] for r in salty_table],
                      "values": [r["median"] for r in salty_table],
                      "counts": [r["n"] for r in salty_table]},
            "trend": {"x": [_dec_label(d) for d in trend_decades],
                      "series": trend_series},
            "no3": {"x": [r["decade"] for r in no3_rows], "series": no3_series,
                    "counts": [r["n"] for r in no3_rows]},
            "heat": heat,
        },
        "tables": {
            "params": params_table,
            "streams": [{"name": n, "n": v, "st": s} for n, v, s in
                        zip(streams_chart["names"], streams_chart["values"],
                            streams_chart["stations"])],
            "stations": stations_table,
            "activity": [{"dec": x, "n": y} for x, y in zip(activity["x"], activity["y"])],
            "months": [{"m": x, "n": y} for x, y in zip(months["x"], months["y"])],
            "salty": salty_table,
            "trend": {"names": [s["name"] for s in trend_series], "rows": trend_rows},
            "no3": {"bands": [b[2] for b in NO3_BANDS], "rows": no3_rows},
            "heat": {"ions": heat["x"], "rows": heat_rows},
        },
        "flags": {
            "salty": bool(salty_table),
            "trend": len(trend_series) >= 2 and len(trend_decades) >= 2,
            "no3": len(no3_rows) >= 2,
            "heat": len(heat_rows) >= 3 and len(ions_present) >= 3,
        },
        "insights": ins,
        "labels": labels,
    }
