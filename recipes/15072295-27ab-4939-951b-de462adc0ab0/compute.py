"""תחנות - ספיקות שיא היסטוריות: the all-time instantaneous peak discharge
(m3/s) at each hydrometric stream station of the Hydrological Service (Water
Authority), active and closed stations alike.

Data: one row per station record (station id, Hebrew/English name, group id,
hydrological year "YYYY/YYYY" running October to September, date dd/mm/yyyy,
peak discharge, water stage at the peak, free-text note). A station whose
record was equalled in a later flood appears twice with the same value; it is
one station but two record EVENTS.

- Station-level views (top stations, regions, distribution, streams) keep
  one row per station: its highest value, dated by its latest occurrence.
- Event-level views (decades, months, floods, record age) use every row.

Regions come from the station id: its leading digits (all but the last three)
are the Hydrological Service drainage-basin code. Known codes map to a broad
region; unknown codes fall into "אזורים אחרים".

The stream is the part of the Hebrew station name before the first hyphen.

"Latest" is the latest hydrological year in the data, never the wall clock.
"""
import re

import pandas as pd

C_ID, C_HE, C_EN, C_GRP, C_HY, C_DATE, C_Q, C_STAGE, C_NOTE = (
    "זיהוי תחנה", "שם תחנה בעברית", "שם תחנה באנגלית", "מספר קבוצה",
    "שנה הידרולוגית", "תאריך המדידה", "ספיקת שיא היסטורית (מ''ק/שניה)",
    "רום המים (מ')", "הערות")

TOP_N = 15
STREAM_N = 12
STORM_N = 12
STORM_GAP_DAYS = 2      # record dates this close belong to one flood event
STORM_SPAN_DAYS = 5     # ... as long as the event spans no more than this
STORM_MIN = 3           # stations a flood needs to be worth an insight
RECENT_YEARS = 10       # "recent" = within the last N hydrological years in the data
OLD_YEAR = 1970         # records from hydrological years ending before this are "old"
WINTER_MONTHS = (12, 1, 2)
AUTUMN_MONTHS = (10, 11)
SEASON_GAP = 0.15       # autumn-share gap (south vs north) worth an insight
REGION_RATIO = 2.0      # median-peak ratio between regions worth an insight
MIN_REGION_STATIONS = 5
BIG_PEAK = 500.0        # m3/s; "very large flood" threshold

REGIONS = [
    ("גליל, עמקים וכרמל", list(range(1, 14))),
    ("השרון, המרכז והשפלה", list(range(14, 20)) + [50]),
    ("הנגב המערבי (בשור ושקמה)", list(range(20, 30))),
    ("אגן הירדן והכנרת", list(range(30, 40))),
    ("בקעת הירדן וים המלח", list(range(40, 50))),
    ("הנגב ההררי, הערבה ואילת", list(range(51, 70))),
]
OTHER_REGION = "אזורים אחרים"
REGION_OF = {code: name for name, codes in REGIONS for code in codes}
REGION_ORDER = [name for name, _ in REGIONS] + [OTHER_REGION]
ARID = {"בקעת הירדן וים המלח", "הנגב ההררי, הערבה ואילת", "הנגב המערבי (בשור ושקמה)"}

HY_MONTHS = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
MONTH_HE = {1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל", 5: "מאי", 6: "יוני",
            7: "יולי", 8: "אוגוסט", 9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר", 12: "דצמבר"}

AGE_BINS = [(0, 5, "פחות מ-5 שנים"), (5, 15, "5 עד 14 שנים"), (15, 30, "15 עד 29 שנים"),
            (30, 50, "30 עד 49 שנים"), (50, 10 ** 6, "50 שנים ויותר")]
Q_BINS = [(0, 10, "עד 10"), (10, 50, "10 עד 50"), (50, 100, "50 עד 100"),
          (100, 250, "100 עד 250"), (250, 500, "250 עד 500"),
          (500, 1000, "500 עד 1,000"), (1000, float("inf"), "1,000 ומעלה")]

YEAR_RE = re.compile(r"^\s*(\d{4})\s*/\s*(\d{4})\s*$")


def num(v):
    if v >= 100:
        return f"{v:,.0f}"
    if v >= 10:
        return f"{v:,.1f}".rstrip("0").rstrip(".")
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def r1(v):
    return round(float(v), 2)


def pct(x):
    return f"{x * 100:.0f}%"


def hy_label(y):
    return f"{y - 1}/{str(y)[-2:]}"


def fmt_date(d):
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def clean_name(s):
    s = " ".join(str(s).replace("''", "״").split())
    return s.replace("( ", "(").replace(" )", ")")


def stream_of(name):
    part = re.split(r"\s*-\s*", name, maxsplit=1)[0]
    return " ".join(part.split()) or name


def region_of(sid):
    s = str(sid).strip()
    if not s.isdigit() or len(s) < 4:
        return OTHER_REGION
    return REGION_OF.get(int(s[:-3]), OTHER_REGION)


def end_year(s, d):
    m = YEAR_RE.match(str(s))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b == a + 1:
            return b
    if pd.isna(d):
        return None
    return d.year + 1 if d.month >= 10 else d.year


def prepare(df):
    d = pd.to_datetime(df[C_DATE].astype(str).str.strip(), format="%d/%m/%Y", errors="coerce")
    out = pd.DataFrame({
        "id": df[C_ID].astype(str).str.strip(),
        "name": df[C_HE].map(clean_name),
        "d": d,
        "q": pd.to_numeric(df[C_Q].astype(str).str.replace(",", "", regex=False).str.strip(),
                           errors="coerce"),
        "stage": pd.to_numeric(df[C_STAGE].astype(str).str.replace(",", "", regex=False).str.strip(),
                               errors="coerce"),
    })
    out["y"] = [end_year(s, dd) for s, dd in zip(df[C_HY], d)]
    out = out[(out["id"] != "") & out["q"].notna() & (out["q"] > 0)].copy()
    out["region"] = out["id"].map(region_of)
    out["stream"] = out["name"].map(stream_of)
    out["month"] = out["d"].dt.month
    out = out.sort_values(["id", "q", "d", "name", "stage"], ascending=[True, False, False, True, True],
                          na_position="last", kind="mergesort").reset_index(drop=True)
    return out


def stations_of(ev):
    """One row per station: its highest value, dated by its latest occurrence."""
    top = ev.groupby("id", sort=True)["q"].transform("max")
    best = ev[ev["q"] == top]
    best = best.sort_values(["id", "d", "name"], ascending=[True, False, True],
                            na_position="last", kind="mergesort")
    st = best.drop_duplicates("id", keep="first").copy()
    st["n_events"] = st["id"].map(best.groupby("id").size())
    return st.sort_values(["q", "id"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def floods_of(ev):
    """Cluster record dates no more than STORM_GAP_DAYS apart into flood events."""
    dated = ev[ev["d"].notna()].sort_values(["d", "id"], kind="mergesort")
    events, cur, last = [], [], None
    for row in dated.itertuples(index=False):
        if last is not None and ((row.d - last).days > STORM_GAP_DAYS
                                 or (row.d - cur[0].d).days > STORM_SPAN_DAYS):
            events.append(cur)
            cur = []
        cur.append(row)
        last = row.d
    if cur:
        events.append(cur)
    out = []
    for rows in events:
        ids = sorted({r.id for r in rows})
        start, end = rows[0].d, rows[-1].d
        if start == end:
            label = fmt_date(start)
        elif start.month == end.month and start.year == end.year:
            label = f"{start.day:02d}-{end.day:02d}/{start.month:02d}/{start.year}"
        else:
            label = f"{fmt_date(start)} עד {fmt_date(end)}"
        byq = sorted(rows, key=lambda r: (-r.q, r.id))
        regions = sorted({r.region for r in rows}, key=REGION_ORDER.index)
        out.append({"label": label, "start": start, "n": len(ids), "max_q": float(byq[0].q),
                    "max_name": byq[0].name, "names": [r.name for r in byq],
                    "regions": regions})
    out.sort(key=lambda e: (-e["n"], -e["max_q"], e["start"]))
    return out


def compute(frames):
    ev = prepare(frames["main"])
    st = stations_of(ev)
    n_st = len(st)
    max_y = int(ev["y"].dropna().max())
    min_y = int(ev["y"].dropna().min())
    d_min, d_max = ev["d"].min(), ev["d"].max()

    regions_present = [r for r in REGION_ORDER if (st["region"] == r).any()]

    # --- top stations -------------------------------------------------------
    top = st.head(TOP_N)
    chart_top = {
        "names": top["name"].tolist(),
        "y": [r1(v) for v in top["q"]],
        "region": top["region"].tolist(),
        "date": [fmt_date(d) if pd.notna(d) else "" for d in top["d"]],
    }
    tab_top = [{"name": r.name, "q": num(r.q), "date": fmt_date(r.d) if pd.notna(r.d) else "לא ידוע",
                "stage": num(r.stage) if pd.notna(r.stage) else "לא צוין", "region": r.region}
               for r in top.itertuples(index=False)]

    # --- regions (boxplot) --------------------------------------------------
    box, reg_rows, reg_stats = [], [], {}
    for reg in regions_present:
        s = st[st["region"] == reg]
        q = s["q"].sort_values().to_numpy()
        qs = [float(pd.Series(q).quantile(p)) for p in (0, 0.25, 0.5, 0.75, 1)]
        box.append([r1(v) for v in qs])
        lead = s.iloc[0]
        reg_stats[reg] = {"n": len(s), "median": qs[2], "max": qs[4], "lead": lead["name"]}
        reg_rows.append({"region": reg, "n": f"{len(s):,}", "median": num(qs[2]),
                         "max": num(qs[4]), "lead": lead["name"]})
    chart_region = {"regions": regions_present, "box": box,
                    "n": [reg_stats[r]["n"] for r in regions_present]}

    # --- distribution -------------------------------------------------------
    dist_counts = [int(((st["q"] >= lo) & (st["q"] < hi)).sum()) for lo, hi, _ in Q_BINS]
    chart_dist = {"x": [lab for _, _, lab in Q_BINS], "y": dist_counts}
    tab_dist = [{"bin": lab, "n": f"{c:,}", "share": pct(c / n_st)}
                for (_, _, lab), c in zip(Q_BINS, dist_counts)]

    # --- decades (events) ---------------------------------------------------
    evy = ev[ev["y"].notna()].copy()
    evy["dec"] = (evy["y"].astype(int) // 10) * 10
    decs = list(range(int(evy["dec"].min()), int(evy["dec"].max()) + 1, 10))
    dec_series = []
    for reg in regions_present:
        cnt = evy[evy["region"] == reg].groupby("dec").size()
        dec_series.append({"name": reg, "data": [int(cnt.get(dd, 0)) for dd in decs]})
    dec_tot = evy.groupby("dec").size()
    chart_dec = {"x": [f"{dd}-{dd + 9}" for dd in decs], "series": dec_series}
    tab_dec = [{"dec": f"{dd}-{dd + 9}", "n": f"{int(dec_tot.get(dd, 0)):,}"} for dd in decs]

    # --- months (events) ----------------------------------------------------
    evm = ev[ev["month"].notna()].copy()
    evm["month"] = evm["month"].astype(int)
    mon_series = []
    for reg in regions_present:
        cnt = evm[evm["region"] == reg].groupby("month").size()
        mon_series.append({"name": reg, "data": [int(cnt.get(m, 0)) for m in HY_MONTHS]})
    mon_tot = evm.groupby("month").size()
    n_m = len(evm)
    chart_mon = {"x": [MONTH_HE[m] for m in HY_MONTHS], "series": mon_series}
    tab_mon = [{"month": MONTH_HE[m], "n": f"{int(mon_tot.get(m, 0)):,}",
                "share": pct(int(mon_tot.get(m, 0)) / n_m) if n_m else "0%"} for m in HY_MONTHS]

    # --- floods -------------------------------------------------------------
    floods = floods_of(ev)
    multi = [f for f in floods if f["n"] >= 2][:STORM_N]
    multi_sorted = sorted(multi, key=lambda f: f["start"])
    chart_storm = {"x": [f["label"] for f in multi_sorted], "y": [f["n"] for f in multi_sorted],
                   "maxq": [r1(f["max_q"]) for f in multi_sorted],
                   "lead": [f["max_name"] for f in multi_sorted]}
    tab_storm = [{"label": f["label"], "n": f"{f['n']:,}", "maxq": num(f["max_q"]),
                  "lead": f["max_name"], "regions": "; ".join(f["regions"])} for f in multi_sorted]

    # --- record age (events, by latest occurrence per station) ---------------
    sty = st[st["y"].notna()].copy()
    sty["age"] = max_y - sty["y"].astype(int)
    age_counts = [int(((sty["age"] >= lo) & (sty["age"] < hi)).sum()) for lo, hi, _ in AGE_BINS]
    chart_age = {"x": [lab for _, _, lab in AGE_BINS], "y": age_counts}
    tab_age = [{"bin": lab, "n": f"{c:,}", "share": pct(c / len(sty)) if len(sty) else "0%"}
               for (_, _, lab), c in zip(AGE_BINS, age_counts)]

    # --- streams --------------------------------------------------------------
    sg = st.groupby("stream", sort=True).agg(max_q=("q", "max"), n=("id", "size")).reset_index()
    sg = sg.sort_values(["max_q", "n", "stream"], ascending=[False, False, True], kind="mergesort")
    top_streams = sg.head(STREAM_N)
    chart_streams = {"names": top_streams["stream"].tolist(), "y": [r1(v) for v in top_streams["max_q"]],
                     "n": [int(v) for v in top_streams["n"]]}
    tab_streams = [{"stream": r.stream, "q": num(r.max_q), "n": f"{int(r.n):,}"}
                   for r in top_streams.itertuples(index=False)]
    n_streams = int(sg.shape[0])

    # --- scatter (stations) ---------------------------------------------------
    sc = st[st["d"].notna()].sort_values(["d", "id"], kind="mergesort")
    chart_scatter = {"series": [{"name": reg, "data": [
        [round(r.d.year + (r.d.dayofyear - 1) / 366, 3), r1(r.q), r.name, fmt_date(r.d)]
        for r in sc[sc["region"] == reg].itertuples(index=False)]} for reg in regions_present]}

    # --- KPIs -----------------------------------------------------------------
    lead = st.iloc[0]
    med = float(st["q"].median())
    recent = st[st["y"].notna() & (st["y"] > max_y - RECENT_YEARS)]
    n_recent = len(recent)
    recent_share = n_recent / n_st if n_st else 0
    kpis = {
        "stations": {"value": n_st, "display": f"{n_st:,}", "tone": "brand"},
        "max": {"value": r1(lead["q"]), "display": num(lead["q"]), "tone": "danger"},
        "median": {"value": r1(med), "display": num(med), "tone": "brand"},
        "recent": {"value": n_recent, "display": f"{n_recent:,}",
                   "tone": "warn" if recent_share >= 0.25 else "info"},
    }
    if pd.notna(d_min) and pd.notna(d_max):
        span = f"{d_min.year}–{d_max.year}"
    else:
        span = f"{min_y}–{max_y}"
    kpis["span"] = {"value": span, "display": span, "tone": "brand"}

    # --- insights -------------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_leader():
        if n_st < 2:
            return None
        second = st.iloc[1]
        ratio = lead["q"] / med if med > 0 else None
        when = f" ב-{fmt_date(lead['d'])}" if pd.notna(lead["d"]) else ""
        s = (f"ספיקת השיא הגבוהה ביותר במאגר נמדדה בתחנת {lead['name']}{when}: "
             f"{num(lead['q'])} מ״ק לשנייה")
        if ratio:
            s += f", פי {ratio:,.0f} מהחציון של כלל התחנות ({num(med)} מ״ק לשנייה)"
        return s + f". במקום השני: {second['name']} עם {num(second['q'])} מ״ק לשנייה."

    def ins_storm():
        if not floods or floods[0]["n"] < STORM_MIN:
            return None
        f = floods[0]
        regs = " ו".join(f["regions"]) if len(f["regions"]) <= 2 else f"{len(f['regions'])} אזורים"
        return (f"השיטפון שקבע הכי הרבה שיאים: {f['label']}, שבו נמדדה ספיקת השיא ההיסטורית של "
                f"{f['n']:,} תחנות ({regs}). הגבוהה שבהן: {f['max_name']}, {num(f['max_q'])} מ״ק לשנייה.")

    def ins_season():
        if n_m < 20:
            return None
        win = int(evm["month"].isin(WINTER_MONTHS).sum())
        arid = evm[evm["region"].isin(ARID)]
        wet = evm[~evm["region"].isin(ARID) & (evm["region"] != OTHER_REGION)]
        s = f"{pct(win / n_m)} משיאי הספיקה נמדדו בדצמבר עד פברואר."
        if len(arid) >= 10 and len(wet) >= 10:
            a = arid["month"].isin(AUTUMN_MONTHS).mean()
            w = wet["month"].isin(AUTUMN_MONTHS).mean()
            if a - w >= SEASON_GAP:
                s += (f" בנגב, בערבה ובבקעת הירדן השיטפונות מוקדמים יותר: {pct(a)} מהשיאים שם נמדדו "
                      f"באוקטובר ובנובמבר, לעומת {pct(w)} בצפון ובמרכז.")
        return s

    def ins_recent():
        if n_recent == 0:
            return None
        newest = st[st["d"].notna()].sort_values(["d", "q", "id"], ascending=[False, False, True],
                                                 kind="mergesort")
        s = (f"{n_recent:,} תחנות ({pct(recent_share)}) קבעו את שיא הספיקה שלהן ב-{RECENT_YEARS} השנים "
             f"ההידרולוגיות האחרונות במאגר ({hy_label(max_y - RECENT_YEARS + 1)} עד {hy_label(max_y)})")
        if len(newest):
            nw = newest.iloc[0]
            s += f". השיא החדש ביותר: {nw['name']}, {num(nw['q'])} מ״ק לשנייה ב-{fmt_date(nw['d'])}"
        return s + "."

    def ins_old():
        old = sty[sty["y"] < OLD_YEAR]
        if len(old) == 0:
            return None
        o = old.sort_values(["y", "d", "id"], kind="mergesort").iloc[0]
        when = fmt_date(o["d"]) if pd.notna(o["d"]) else hy_label(int(o["y"]))
        return (f"שיאים של {len(old):,} תחנות לא נשברו מאז לפני {OLD_YEAR}. הוותיק שבהם: "
                f"{o['name']}, {num(o['q'])} מ״ק לשנייה ב-{when}.")

    def ins_region():
        cand = [(r, s) for r, s in reg_stats.items() if s["n"] >= MIN_REGION_STATIONS and r != OTHER_REGION]
        if len(cand) < 2:
            return None
        cand.sort(key=lambda t: (-t[1]["median"], t[0]))
        hi, lo = cand[0], cand[-1]
        if lo[1]["median"] <= 0 or hi[1]["median"] / lo[1]["median"] < REGION_RATIO:
            return None
        return (f"חציון ספיקות השיא הגבוה ביותר הוא באזור {hi[0]}: {num(hi[1]['median'])} מ״ק לשנייה, "
                f"פי {hi[1]['median'] / lo[1]['median']:,.1f} מאזור {lo[0]} ({num(lo[1]['median'])} מ״ק לשנייה; "
                f"אזורים עם {MIN_REGION_STATIONS} תחנות לפחות).")

    def ins_big():
        big = int((st["q"] >= BIG_PEAK).sum())
        if big == 0:
            return None
        arid_big = int(((st["q"] >= BIG_PEAK) & st["region"].isin(ARID)).sum())
        s = f"{big:,} תחנות ({pct(big / n_st)}) רשמו ספיקת שיא של {num(BIG_PEAK)} מ״ק לשנייה ומעלה"
        if arid_big / big >= 0.5:
            s += f", {arid_big:,} מהן בנחלי הנגב, הערבה וים המלח"
        return s + "."

    add("leader", ins_leader())
    add("storm", ins_storm())
    add("season", ins_season())
    add("recent", ins_recent())
    add("old", ins_old())
    add("region", ins_region())
    add("big", ins_big())

    # --- labels ---------------------------------------------------------------
    f0 = floods[0] if floods else None
    top_dec = max(decs, key=lambda dd: (int(dec_tot.get(dd, 0)), -dd))
    top_mon = max(HY_MONTHS, key=lambda m: (int(mon_tot.get(m, 0)), -HY_MONTHS.index(m)))
    n_dup = int((st["n_events"] > 1).sum())
    age_mode = max(range(len(AGE_BINS)), key=lambda i: (age_counts[i], -i))
    dist_mode = max(range(len(Q_BINS)), key=lambda i: (dist_counts[i], -i))
    lead_when = fmt_date(lead["d"]) if pd.notna(lead["d"]) else ""

    labels = {
        "lede": (f"ספיקת השיא ההיסטורית (הספיקה הרגעית המרבית שנמדדה אי פעם) של {n_st:,} תחנות "
                 f"הידרומטריות בנחלי ישראל, פעילות ושאינן פעילות, לפי השירות ההידרולוגי של רשות המים. "
                 f"השיאים נמדדו בין {hy_label(min_y)} ל-{hy_label(max_y)}. "
                 f"הגבוה שבהם: {lead['name']}, {num(lead['q'])} מ״ק לשנייה."),
        "kpi_stations": "תחנות הידרומטריות במאגר",
        "kpi_max": f"ספיקת השיא הגבוהה ביותר, מ״ק לשנייה ({lead['name']})",
        "kpi_median": "חציון ספיקות השיא, מ״ק לשנייה",
        "kpi_recent": f"תחנות שקבעו שיא ב-{RECENT_YEARS} השנים האחרונות במאגר",
        "kpi_span": "טווח שנות השיאים",
        "top_note": (f"{len(top):,} התחנות עם ספיקת השיא הגבוהה ביותר. בראש: {lead['name']} "
                     f"({num(lead['q'])} מ״ק לשנייה{', ' + lead_when if lead_when else ''})."),
        "top_aria": (f"גרף עמודות אופקי: {len(top):,} התחנות עם ספיקת השיא הגבוהה ביותר. "
                     f"בראש {lead['name']} עם {num(lead['q'])} מ״ק לשנייה."),
        "region_note": (f"פיזור ספיקות השיא של התחנות בכל אזור ניקוז (ציר לוגריתמי): הקופסה מסמנת את הרבעון "
                        f"התחתון עד העליון, הקו את החציון. האזור נגזר מקוד האגן שבמספר התחנה."),
        "region_aria": (f"תרשים קופסה: פיזור ספיקות השיא לפי {len(regions_present):,} אזורי ניקוז, בציר לוגריתמי."),
        "dist_note": (f"מספר התחנות לפי טווח ספיקת השיא. הטווח הנפוץ: {Q_BINS[dist_mode][2]} מ״ק לשנייה "
                      f"({dist_counts[dist_mode]:,} תחנות)."),
        "dist_aria": (f"גרף עמודות: התפלגות {n_st:,} תחנות לפי טווח ספיקת השיא. "
                      f"הטווח הנפוץ {Q_BINS[dist_mode][2]} מ״ק לשנייה."),
        "dec_note": (f"מתי נקבעו השיאים, לפי עשור השנה ההידרולוגית ואזור. העשור עם הכי הרבה שיאים: "
                     f"{top_dec}-{top_dec + 9} ({int(dec_tot.get(top_dec, 0)):,} שיאים). "
                     + (f"{n_dup:,} תחנות שבהן השיא הושווה בשיטפון מאוחר נספרות פעמיים." if n_dup else "")),
        "dec_aria": (f"גרף עמודות מוערם: מספר שיאי הספיקה לפי עשור ואזור. "
                     f"השיא בעשור {top_dec}-{top_dec + 9}."),
        "mon_note": (f"החודש שבו נמדד השיא, לפי סדר השנה ההידרולוגית (אוקטובר עד ספטמבר). "
                     f"החודש הבולט: {MONTH_HE[top_mon]} ({int(mon_tot.get(top_mon, 0)):,} שיאים)."),
        "mon_aria": (f"גרף עמודות מוערם: שיאי ספיקה לפי חודש ואזור. החודש הבולט {MONTH_HE[top_mon]}."),
        "storm_note": (f"אירועי שיטפון שבהם נקבעו שיאים בכמה תחנות יחד (תאריכים במרחק של עד "
                       f"{STORM_GAP_DAYS} ימים זה מזה, בטווח של עד {STORM_SPAN_DAYS} ימים, נחשבים אירוע אחד; מוצגים עד {STORM_N} האירועים הגדולים, "
                       f"לפי סדר כרונולוגי)."
                       + (f" הגדול שבהם: {f0['label']}, עם {f0['n']:,} תחנות." if f0 and f0["n"] >= 2 else "")),
        "storm_aria": (f"גרף עמודות: מספר התחנות שקבעו שיא בכל אירוע שיטפון."
                       + (f" הגדול {f0['label']} עם {f0['n']:,} תחנות." if f0 and f0["n"] >= 2 else "")),
        "age_note": (f"כמה זמן עומד השיא של כל תחנה, ביחס לשנה ההידרולוגית האחרונה במאגר "
                     f"({hy_label(max_y)}). הקבוצה הגדולה: {AGE_BINS[age_mode][2]} "
                     f"({age_counts[age_mode]:,} תחנות)."),
        "age_aria": (f"גרף עמודות: התחנות לפי גיל השיא. הקבוצה הגדולה {AGE_BINS[age_mode][2]}."),
        "streams_note": (f"ספיקת השיא הגבוהה ביותר בכל נחל ({n_streams:,} נחלים במאגר; הנחל נגזר משם התחנה). "
                         f"מוצגים {len(top_streams):,} הנחלים המובילים."),
        "streams_aria": (f"גרף עמודות אופקי: {len(top_streams):,} הנחלים עם ספיקת השיא הגבוהה ביותר. "
                         f"בראש {top_streams.iloc[0]['stream']}."),
        "scatter_note": ("כל נקודה היא תחנה: מועד השיא שלה וגודלו (ציר לוגריתמי). לחיצה על שם אזור "
                         "במקרא מסתירה או מציגה אותו."),
        "scatter_aria": (f"תרשים פיזור: ספיקת השיא של {len(sc):,} תחנות לפי מועד השיא, בצבע לפי אזור."),
    }

    summary = (f"איתור ספיקת השיא ההיסטורית של תחנה הידרומטרית בנחלי ישראל לפי שם או מספר תחנה: "
               f"{n_st:,} תחנות, {hy_label(min_y)} עד {hy_label(max_y)}. "
               f"השיא: {lead['stream']}, {num(lead['q'])} מ״ק לשנייה.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            "suggested_tags": ["הידרומטריה", "ספיקה", "שיטפונות", "נחלים", "תחנות מדידה"],
            "related_ids": [
                "d16214ba-56b3-417d-9342-6a144f215b9b",
                "f72117a6-2b71-43e9-bc81-75c284a4d1e2",
                "e81d14bd-a81d-4de4-b1de-d7a0541ace02",
                "096db5d2-dc8b-40c8-9fe7-2b839a435d92",
                "87514149-a73c-424d-89b4-80d3c9058f7a",
            ],
            "temporal_coverage": f"{min_y - 1}/{max_y}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "top": chart_top, "region": chart_region, "dist": chart_dist, "dec": chart_dec,
            "mon": chart_mon, "storm": chart_storm, "age": chart_age, "streams": chart_streams,
            "scatter": chart_scatter,
        },
        "tables": {
            "top": tab_top, "region": reg_rows, "dist": tab_dist, "dec": tab_dec, "mon": tab_mon,
            "storm": tab_storm, "age": tab_age, "streams": tab_streams,
        },
        "flags": {"storm": len(multi) > 0},
        "insights": insights,
        "labels": labels,
    }
