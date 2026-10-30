"""דוח קטלוג מעיינות: the Hydrological Service's catalog of springs in Israel.

Data: one row per spring (a registry, no time series). Coordinates are ITM
(Israel New Grid, metres): the emergence point and, for most measured
springs, a separate measurement point. Elevation is metres above sea level
(negative = below). "תחילת תצפית" is the year observation began.

Spring type ("סוג מעיין") is the monitoring status: measured regularly,
survey spring, or not measured. Known types are ordered first; any new type
flows through after them, and an empty type shows as "לא צוין".

Regions come from the spring id, as on the sibling page (annual volumes,
073cd24f): its leading digits (all but the last three) are the Hydrological
Service drainage-basin code. Known codes map to a broad region; unknown codes
fall into "אזורים אחרים".
"""
import math

import pandas as pd

C_ID = "מספר זיהוי"
C_NAME = "שם מעיין"
C_START = "תחילת תצפית"
C_X = "נביעה X .נ.צ"
C_Y = "נביעה Y .נ.צ"
C_MX = "נ.צ. X מקום מדידה"
C_MY = "נ.צ. Y מקום מדידה"
C_EL = "רום הנביעה"
C_TYPE = "סוג מעיין"
C_AQ = "שם אקויפר"
C_AQ_CODE = "קוד אקויפר"
C_CELL = "שם תא דיווח"
C_CELL_CODE = "קוד תא דיווח"

REGULAR = "נמדד באופן סדיר"
SURVEY = "מעיין סקר"
UNMEASURED = "לא נמדד"
KNOWN_TYPES = [REGULAR, SURVEY, UNMEASURED]
NO_TYPE = "לא צוין"
TYPE_LABEL = {REGULAR: "נמדד באופן סדיר", SURVEY: "מעיין סקר", UNMEASURED: "לא נמדד"}

REGIONS = [
    ("עמק החולה ומקורות הירדן", ["30"]),
    ("הכנרת וסביבתה", ["31", "32"]),
    ("הגליל המערבי", ["1", "2", "4", "5", "7"]),
    ("אגן הקישון", ["8"]),
    ("הכרמל ונחל תנינים", ["10", "12", "13"]),
    ("עמק חרוד, בית שאן ונחל תבור", ["34", "35", "36", "38", "39"]),
    ("הרי השומרון, ירושלים וחברון", ["14", "15", "17", "18", "19", "23"]),
    ("בקעת הירדן ויריחו", ["43", "45", "46"]),
    ("ים המלח", ["48", "58", "59"]),
    ("הנגב והערבה", ["55", "56", "57", "60"]),
]
OTHER_REGION = "אזורים אחרים"
REGION_OF = {code: name for name, codes in REGIONS for code in codes}

OTHER = "אחר"
SUMMARY_WORD = "סיכום"
AQ_TOP = 9            # aquifers shown before an "אחר" bucket
CELL_TOP = 15         # reporting cells shown
BOX_MIN = 5           # elevations an aquifer needs for the boxplot
TABLE_N = 10          # rows in the oldest / lowest / highest tables
ELEV_STEP = 200       # elevation histogram band (m)
LEAD_SHARE = 0.20     # a region/aquifer "leads" only at/above this share
RECENT_MIN = 10       # starts since the recent cutoff needed for the insight
MISSING_SHARE = 0.10  # missing-start-year share worth reporting
OFFSET_BUCKETS = [    # (upper bound in metres, label); distance emergence -> measurement point
    (0, "באותה נקודה"),
    (50, "עד 50 מ׳"),
    (200, "50 עד 200 מ׳"),
    (500, "200 עד 500 מ׳"),
    (1000, "500 מ׳ עד ק״מ"),
    (math.inf, "יותר מק״מ"),
]


def _int(n):
    return f"{int(n):,}"


def _pct(r):
    return f"{r * 100:.0f}%"


def _signed(v):
    v = int(v)
    return f"−{abs(v):,}" if v < 0 else f"{v:,}"


def _elev_text(v):
    v = int(v)
    if v < 0:
        return f"{abs(v):,} מ׳ מתחת לפני הים"
    return f"{v:,} מ׳ מעל פני הים"


def _type_phrase(t, k, n=None):
    share = f" ({_pct(k / n)})" if n else ""
    if t == REGULAR:
        return f"{_int(k)}{share} נמדדים באופן סדיר"
    if t == SURVEY:
        return f"{_int(k)} הם מעיינות סקר"
    if t == UNMEASURED:
        return f"{_int(k)} אינם נמדדים"
    if t == NO_TYPE:
        return f"{_int(k)} ללא סוג רשום"
    return f"{_int(k)} בסטטוס {t}"


def _type_mix(types, counts, n=None):
    """Every status present, known ones first; parts always sum to the total."""
    parts = [_type_phrase(t, int(counts.get(t, 0)), n if t == REGULAR else None)
             for t in types if counts.get(t, 0)]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " ו-" + parts[-1]


def _region(sid):
    sid = sid.strip()
    if len(sid) < 4 or not sid.isdigit():
        return OTHER_REGION
    return REGION_OF.get(sid[:-3], OTHER_REGION)


def _prepare(df):
    df = df.copy()
    for c in [C_ID, C_NAME, C_TYPE, C_AQ, C_CELL]:
        df[c] = df[c].astype(str).str.strip()
    num = lambda c: pd.to_numeric(df[c].astype(str).str.replace(",", "").str.strip(), errors="coerce")
    df["start"] = num(C_START)
    df.loc[(df["start"] < 1800) | (df["start"] > 2200), "start"] = float("nan")
    df["el"] = num(C_EL)
    df["x"], df["y"] = num(C_X), num(C_Y)
    df["mx"], df["my"] = num(C_MX), num(C_MY)
    df["type"] = df[C_TYPE].where(df[C_TYPE] != "", NO_TYPE)
    df["aq"] = df[C_AQ].where(df[C_AQ] != "", NO_TYPE)
    df["cell"] = df[C_CELL].where(df[C_CELL] != "", NO_TYPE)
    df["region"] = df[C_ID].map(_region)
    # "... סיכום" rows are group totals of several outlets (measured together)
    df["summary"] = df[C_NAME].str.contains(SUMMARY_WORD, regex=False)
    df = df[df[C_NAME] != ""]
    # total order for every tie-break downstream
    df = df.sort_values([C_ID, C_NAME], kind="mergesort").reset_index(drop=True)
    return df


def _type_order(df):
    present = set(df["type"])
    extra = sorted(t for t in present if t not in KNOWN_TYPES and t != NO_TYPE)
    order = [t for t in KNOWN_TYPES if t in present] + extra
    if NO_TYPE in present:
        order.append(NO_TYPE)
    return order


def _stack(df, key, cats, types):
    """{cats, series:[{name,data}], totals} counting springs per cat x type."""
    tab = df.groupby([key, "type"]).size()
    series = []
    for t in types:
        series.append({"name": TYPE_LABEL.get(t, t),
                       "data": [int(tab.get((c, t), 0)) for c in cats]})
    totals = [int(sum(s["data"][i] for s in series)) for i in range(len(cats))]
    return {"cats": cats, "series": series, "totals": totals}


def _ranked(counts):
    """Categories by count desc, name asc."""
    return [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _quantile(vals, q):
    vals = sorted(vals)
    pos = (len(vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def compute(frames):
    df = _prepare(frames["main"])
    n = len(df)
    types = _type_order(df)
    type_counts = df["type"].value_counts().to_dict()
    n_reg = int(type_counts.get(REGULAR, 0))

    # ---- type split
    chart_type = {"names": [TYPE_LABEL.get(t, t) for t in types],
                  "values": [int(type_counts.get(t, 0)) for t in types]}
    table_type = [{"name": nm, "n": _int(v), "share": _pct(v / n) if n else "0%"}
                  for nm, v in zip(chart_type["names"], chart_type["values"])]

    # ---- regions
    rc = df["region"].value_counts().to_dict()
    regions = [r for r in _ranked(rc) if r != OTHER_REGION]
    if OTHER_REGION in rc:
        regions.append(OTHER_REGION)
    chart_region = _stack(df, "region", regions, types)
    table_region = [{"name": r, "total": _int(t), "reg": _int(df[(df["region"] == r) & (df["type"] == REGULAR)].shape[0])}
                    for r, t in zip(regions, chart_region["totals"])]

    # ---- aquifers (top N + אחר)
    ac = df["aq"].value_counts().to_dict()
    aq_ranked = [a for a in _ranked(ac) if a != NO_TYPE]
    aq_top = aq_ranked[:AQ_TOP]
    dfa = df.copy()
    dfa["aqb"] = dfa["aq"].where(dfa["aq"].isin(aq_top), OTHER)
    aq_cats = aq_top + ([OTHER] if (dfa["aqb"] == OTHER).any() else [])
    chart_aq = _stack(dfa, "aqb", aq_cats, types)
    aq_other_n = len(aq_ranked) - len(aq_top) + (1 if NO_TYPE in ac else 0)
    table_aq = []
    for a, t in zip(aq_cats, chart_aq["totals"]):
        sub = dfa[dfa["aqb"] == a]
        table_aq.append({"name": a, "total": _int(t),
                         "reg": _int((sub["type"] == REGULAR).sum()),
                         "share": _pct(t / n) if n else "0%"})

    # ---- reporting cells (top N)
    cc = df["cell"].value_counts().to_dict()
    cells = _ranked(cc)[:CELL_TOP]
    chart_cell = _stack(df, "cell", cells, types)
    n_cells = len([c for c in cc if c != NO_TYPE])
    in_top_cells = int(sum(chart_cell["totals"]))
    table_cell = [{"name": c, "total": _int(t)} for c, t in zip(cells, chart_cell["totals"])]

    # ---- observation start by decade
    st = df.dropna(subset=["start"]).copy()
    st["decade"] = (st["start"] // 10 * 10).astype(int)
    chart_decade = None
    table_decade = []
    if len(st):
        decs = list(range(int(st["decade"].min()), int(st["decade"].max()) + 10, 10))
        labels = [f"{d}" for d in decs]
        tab = st.groupby(["decade", "type"]).size()
        series = [{"name": TYPE_LABEL.get(t, t), "data": [int(tab.get((d, t), 0)) for d in decs]} for t in types]
        totals = [int(sum(s["data"][i] for s in series)) for i in range(len(decs))]
        cum, run = [], 0
        for v in totals:
            run += v
            cum.append(run)
        chart_decade = {"cats": [f"שנות ה-{d}" for d in decs],
                        "series": series, "totals": totals, "cum": cum}
        for lab, d, tot, cu in zip(chart_decade["cats"], decs, totals, cum):
            reg = int(tab.get((d, REGULAR), 0))
            table_decade.append({"name": lab, "total": _int(tot), "reg": _int(reg), "cum": _int(cu)})
    n_nostart = int(df["start"].isna().sum())

    # ---- elevation bands
    el = df.dropna(subset=["el"]).copy()
    chart_elev, table_elev = None, []
    if len(el):
        lo = int(math.floor(el["el"].min() / ELEV_STEP) * ELEV_STEP)
        hi = int(math.floor(el["el"].max() / ELEV_STEP) * ELEV_STEP)
        edges = list(range(lo, hi + ELEV_STEP, ELEV_STEP))
        el["band"] = ((el["el"] // ELEV_STEP) * ELEV_STEP).astype(int)
        tab = el.groupby(["band", "type"]).size()
        labels = []
        for e in edges:
            a, b = e, e + ELEV_STEP
            if b <= 0:
                labels.append(f"{abs(b):,} עד {abs(a):,} מתחת לפני הים")
            else:
                labels.append(f"{a:,} עד {b:,}")
        series = [{"name": TYPE_LABEL.get(t, t), "data": [int(tab.get((e, t), 0)) for e in edges]} for t in types]
        totals = [int(sum(s["data"][i] for s in series)) for i in range(len(edges))]
        chart_elev = {"cats": labels, "series": series, "totals": totals,
                      "below": [e + ELEV_STEP <= 0 for e in edges]}
        table_elev = [{"name": lab, "total": _int(t)} for lab, t in zip(labels, totals)]
    n_noel = int(df["el"].isna().sum())

    # ---- elevation by aquifer (boxplot)
    box_rows = []
    for a in aq_ranked:
        v = el.loc[el["aq"] == a, "el"].tolist()
        if len(v) >= BOX_MIN:
            q = [min(v), _quantile(v, 0.25), _quantile(v, 0.5), _quantile(v, 0.75), max(v)]
            box_rows.append((a, len(v), [round(x, 1) for x in q]))
    box_rows.sort(key=lambda r: (-r[2][2], r[0]))
    chart_box = {"cats": [r[0] for r in box_rows], "data": [r[2] for r in box_rows],
                 "n": [r[1] for r in box_rows]}
    table_box = [{"name": a, "n": _int(k), "min": _signed(q[0]), "med": _signed(round(q[2])), "max": _signed(q[4])}
                 for a, k, q in box_rows]
    box_excluded = len([a for a in aq_ranked if a not in chart_box["cats"]])

    # ---- north-south profile (scatter, north up)
    prof = el.dropna(subset=["y"])
    chart_profile = {"series": []}
    for t in types:
        sub = prof[prof["type"] == t]
        chart_profile["series"].append({
            "name": TYPE_LABEL.get(t, t),
            "data": [[int(e), round(y / 1000, 1), nm] for e, y, nm in zip(sub["el"], sub["y"], sub[C_NAME])],
        })

    # ---- measurement point offset
    mp = df.dropna(subset=["x", "y", "mx", "my"]).copy()
    mp["d"] = ((mp["x"] - mp["mx"]) ** 2 + (mp["y"] - mp["my"]) ** 2) ** 0.5
    off_counts = []
    prev = -1.0
    for ub, lab in OFFSET_BUCKETS:
        k = int(((mp["d"] > prev) & (mp["d"] <= ub)).sum()) if ub != 0 else int((mp["d"] == 0).sum())
        off_counts.append(k)
        prev = ub
    chart_offset = {"cats": [lab for _, lab in OFFSET_BUCKETS], "values": off_counts}
    n_mp = len(mp)
    n_nomp = n - n_mp
    table_offset = [{"name": lab, "n": _int(k), "share": _pct(k / n_mp) if n_mp else "0%"}
                    for lab, k in zip(chart_offset["cats"], off_counts)]

    # ---- tables: oldest regularly measured, lowest, highest
    reg_st = df[(df["type"] == REGULAR)].dropna(subset=["start"])
    reg_st = reg_st.sort_values(["start", C_NAME, C_ID], kind="mergesort").head(TABLE_N)
    t_oldest = [{"name": r[C_NAME], "start": str(int(r["start"])), "cell": r["cell"], "aq": r["aq"]}
                for _, r in reg_st.iterrows()]
    eln = el[~el["summary"]]
    low = eln.sort_values(["el", C_NAME, C_ID], kind="mergesort").head(TABLE_N)
    t_low = [{"name": r[C_NAME], "el": _signed(r["el"]), "cell": r["cell"], "type": TYPE_LABEL.get(r["type"], r["type"])}
             for _, r in low.iterrows()]
    high = eln.sort_values(["el", C_NAME, C_ID], ascending=[False, True, True], kind="mergesort").head(TABLE_N)
    t_high = [{"name": r[C_NAME], "el": _signed(r["el"]), "cell": r["cell"], "type": TYPE_LABEL.get(r["type"], r["type"])}
              for _, r in high.iterrows()]

    n_below = int((el["el"] < 0).sum())
    n_summary = int(df["summary"].sum())
    first_year = int(df["start"].min()) if df["start"].notna().any() else None
    last_year = int(df["start"].max()) if df["start"].notna().any() else None

    # ---------------- insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if n and n_reg:
        add("mix", f"מתוך {_int(n)} המעיינות בקטלוג, {_type_mix(types, type_counts, n)}.")

    if n and regions:
        r0 = regions[0]
        k0 = rc[r0]
        if r0 != OTHER_REGION and k0 / n >= LEAD_SHARE:
            txt = f"האזור עם הכי הרבה מעיינות בקטלוג הוא {r0}: {_int(k0)} מעיינות ({_pct(k0 / n)})"
            if len(regions) > 1 and regions[1] != OTHER_REGION:
                txt += f", ואחריו {regions[1]} עם {_int(rc[regions[1]])}"
            add("region", txt + ".")

    if n and aq_ranked:
        a0 = aq_ranked[0]
        k0 = ac[a0]
        if k0 / n >= LEAD_SHARE:
            reg0 = int(((df["aq"] == a0) & (df["type"] == REGULAR)).sum())
            add("aquifer", f"אקויפר {a0} מזין {_int(k0)} מעיינות, {_pct(k0 / n)} מהקטלוג, "
                           f"ומהם {_int(reg0)} נמדדים באופן סדיר.")

    if n_below > 0 and len(el):
        lr = eln.sort_values(["el", C_NAME, C_ID], kind="mergesort").iloc[0]
        below = el[el["el"] < 0]
        rb = below["region"].value_counts()
        rb = sorted(rb.items(), key=lambda kv: (-kv[1], kv[0]))
        txt = f"{_int(n_below)} מעיינות נובעים מתחת לפני הים"
        if lr["el"] < 0:
            ties = int((eln["el"] == lr["el"]).sum())
            if ties > 1:
                txt += (f". הנמוכים שבהם (ללא רשומות סיכום) נמצאים {_elev_text(lr['el'])}: "
                        f"{_int(ties)} נביעות, ביניהן {lr[C_NAME]}")
            else:
                txt += f". הנמוך שבהם (ללא רשומות סיכום), {lr[C_NAME]}, נמצא {_elev_text(lr['el'])}"
        if rb and rb[0][0] != OTHER_REGION and rb[0][1] / n_below >= 0.5:
            txt += f", ו-{_int(rb[0][1])} מהם באזור {rb[0][0]}"
        add("below", txt + ".")

    if len(eln):
        hr = eln.sort_values(["el", C_NAME, C_ID], ascending=[False, True, True], kind="mergesort").iloc[0]
        lr = eln.sort_values(["el", C_NAME, C_ID], kind="mergesort").iloc[0]
        span = int(hr["el"] - lr["el"])
        if span > 0:
            add("highest", f"המעיין הגבוה ביותר בקטלוג הוא {hr[C_NAME]} ({hr['cell']}), "
                           f"{_elev_text(hr['el'])}: הפרש של {_int(span)} מ׳ מהנביעה הנמוכה ביותר.")

    reg_years = df.loc[df["type"] == REGULAR, "start"].dropna()
    if len(reg_years) >= 5:
        med = int(_quantile(reg_years.tolist(), 0.5))
        o = df[df["type"] == REGULAR].dropna(subset=["start"]).sort_values(
            ["start", C_NAME, C_ID], kind="mergesort").iloc[0]
        add("history", f"המדידה הסדירה ותיקה: מחצית מ-{_int(len(reg_years))} המעיינות הנמדדים באופן סדיר "
                       f"שיש להם שנת תחילה נמדדים מאז {med} או קודם. הוותיק ביותר הוא {o[C_NAME]} (מאז {int(o['start'])}).")

    if chart_decade and len(st):
        last_dec = int(st["decade"].max())
        cut = last_dec - 10  # the latest two decades in the data
        rec = st[st["decade"] >= cut]
        if len(rec) >= RECENT_MIN:
            nonreg = int((rec["type"] != REGULAR).sum())
            add("recent", f"מאז {cut} נוספו לקטלוג {_int(len(rec))} מעיינות עם שנת תחילת תצפית "
                          f"({_pct(len(rec) / len(st))} מכל בעלי שנת התחילה), ומהם {_int(nonreg)} אינם נמדדים באופן סדיר.")

    if n_mp:
        same = off_counts[0]
        far = off_counts[-1]
        txt = (f"ב-{_int(same)} מתוך {_int(n_mp)} המעיינות שיש להם נקודת מדידה ({_pct(same / n_mp)}), "
               f"היא זהה לנקודת הנביעה")
        if far:
            txt += f"; ב-{_int(far)} מעיינות היא רחוקה יותר מק״מ"
        add("offset", txt + ".")

    if n and n_nostart / n >= MISSING_SHARE:
        miss = df[df["start"].isna()]["type"].value_counts()
        miss = sorted(miss.items(), key=lambda kv: (-kv[1], kv[0]))
        t0, k0 = miss[0]
        add("missing", f"ל-{_int(n_nostart)} מעיינות ({_pct(n_nostart / n)}) לא רשומה שנת תחילת תצפית, "
                       f"ו-{_int(k0)} מהם בסטטוס {TYPE_LABEL.get(t0, t0)}.")

    # ---------------- KPIs
    kpis = {
        "total": {"value": n, "display": _int(n), "tone": "brand"},
        "regular": {"value": n_reg, "display": _int(n_reg), "tone": "ok" if n and n_reg / n >= 0.25 else "warn"},
        "below": {"value": n_below, "display": _int(n_below), "tone": "info"},
        "first": {"value": first_year or 0, "display": str(first_year) if first_year else "−", "tone": "brand"},
    }
    kpi_labels = {
        "total": "מעיינות בקטלוג",
        "regular": f"נמדדים באופן סדיר ({_pct(n_reg / n) if n else '0%'})",
        "below": "מעיינות מתחת לפני הים",
        "first": "שנת תחילת התצפית הוותיקה ביותר",
    }

    # ---------------- labels
    top_type = chart_type["names"][0] if chart_type["names"] else ""
    labels = {
        "lede": (f"דוח קטלוג המעיינות של השירות ההידרולוגי ברשות המים מונה {_int(n)} מעיינות בישראל: "
                 f"{_type_mix(types, type_counts)}. "
                 f"לכל מעיין רשומים מיקום (נקודת נביעה ונקודת מדידה), רום הנביעה, האקויפר שמזין אותו ותא הדיווח."
                 + (f" הקטלוג כולל גם {_int(n_summary)} רשומות סיכום של קבוצות נביעות שנמדדות יחד." if n_summary else "")),
        "extreme_note": ("רשומות סיכום של קבוצות נביעות אינן בטבלאות." if n_summary else ""),
        "type_note": f"סטטוס המדידה של {_int(n)} המעיינות בקטלוג.",
        "type_aria": "תרשים טבעת: חלוקת המעיינות לפי סוג. " + ", ".join(
            f"{nm} {_int(v)}" for nm, v in zip(chart_type["names"], chart_type["values"])) + ".",
        "type_caption": "מספר המעיינות לפי סוג מעיין",
        "region_note": ("מספר המעיינות בכל אזור, לפי סוג. האזור נגזר ממספר הזיהוי של המעיין (קוד אגן הניקוז)"
                        + (f"; {_int(rc.get(OTHER_REGION, 0))} מעיינות עם קוד אגן אחר מקובצים תחת \"{OTHER_REGION}\"." if rc.get(OTHER_REGION) else ".")),
        "region_aria": f"תרשים עמודות מוערמות: מעיינות לפי אזור וסוג. המוביל: {regions[0] if regions else ''} עם {_int(rc[regions[0]]) if regions else '0'} מעיינות.",
        "region_caption": "מספר המעיינות לפי אזור",
        "aq_note": (f"האקויפר (שכבת מי התהום) שמזין כל מעיין."
                    + (f" {_int(aq_other_n)} אקויפרים קטנים יותר מקובצים תחת \"{OTHER}\"." if OTHER in aq_cats else "")),
        "aq_aria": f"תרשים עמודות מוערמות: מעיינות לפי אקויפר וסוג. המוביל: {aq_cats[0] if aq_cats else ''}.",
        "aq_caption": "מספר המעיינות לפי אקויפר",
        "cell_note": (f"{len(cells)} תאי הדיווח עם הכי הרבה מעיינות, מתוך {_int(n_cells)} תאים; "
                      f"יחד הם כוללים {_int(in_top_cells)} מעיינות ({_pct(in_top_cells / n) if n else '0%'})."),
        "cell_aria": f"תרשים עמודות אופקי: {len(cells)} תאי הדיווח עם הכי הרבה מעיינות. המוביל: {cells[0] if cells else ''}.",
        "cell_caption": "מספר המעיינות בתאי הדיווח המובילים",
        "decade_note": (f"העשור שבו החלה התצפית בכל מעיין, לפי סוג, והקו: המספר המצטבר. "
                        f"{_int(n_nostart)} מעיינות ללא שנת תחילה אינם בתרשים."),
        "decade_aria": (f"תרשים עמודות מוערמות: מעיינות לפי עשור תחילת התצפית, {first_year} עד {last_year}."
                        if first_year else "תרשים עמודות: מעיינות לפי עשור תחילת התצפית."),
        "decade_caption": "מספר המעיינות לפי עשור תחילת התצפית",
        "elev_note": (f"רום הנביעה ברצועות של {ELEV_STEP} מ׳ (במטרים מעל פני הים, אלא אם צוין אחרת). "
                      f"{_int(n_noel)} מעיינות ללא רום רשום אינם בתרשים."),
        "elev_aria": f"תרשים עמודות: מעיינות לפי רום הנביעה. {_int(n_below)} מעיינות מתחת לפני הים.",
        "elev_caption": "מספר המעיינות לפי רצועת רום",
        "box_note": (f"פיזור רום הנביעה (מ׳) בכל אקויפר: הקופסה היא הרבעון האמצעי, הקו הוא החציון, השפמים הם המינימום והמקסימום. "
                     f"מוצגים אקויפרים עם {BOX_MIN} מעיינות לפחות שיש להם רום רשום"
                     + (f" ({_int(box_excluded)} אקויפרים לא עומדים בסף)." if box_excluded else ".")),
        "box_aria": (f"תרשים קופסה: רום הנביעה לפי אקויפר. החציון הגבוה ביותר ב{chart_box['cats'][0]}."
                     if chart_box["cats"] else "תרשים קופסה: רום הנביעה לפי אקויפר."),
        "box_caption": "רום הנביעה לפי אקויפר: מינימום, חציון ומקסימום",
        "profile_note": ("כל נקודה היא מעיין: הציר האנכי הוא קואורדינטת הצפון ברשת ישראל החדשה (ק״מ, צפון למעלה), "
                         "והציר האופקי הוא רום הנביעה (מ׳)."),
        "profile_aria": f"תרשים פיזור: רום הנביעה מול המיקום מצפון לדרום עבור {_int(len(prof))} מעיינות.",
        "offset_note": (f"המרחק בין נקודת הנביעה לנקודת המדידה, עבור {_int(n_mp)} המעיינות שיש להם נקודת מדידה רשומה"
                        + (f" ({_int(n_nomp)} מעיינות בלי נקודת מדידה אינם בתרשים)." if n_nomp else ".")),
        "offset_aria": (f"תרשים עמודות: מרחק נקודת המדידה מנקודת הנביעה. {_int(off_counts[0])} מעיינות נמדדים בנקודת הנביעה עצמה."
                        if n_mp else "תרשים עמודות: מרחק נקודת המדידה מנקודת הנביעה."),
        "offset_caption": "מספר המעיינות לפי מרחק נקודת המדידה מנקודת הנביעה",
        "oldest_caption": "המעיינות הנמדדים באופן סדיר עם התצפית הוותיקה ביותר",
        "low_caption": "המעיינות הנמוכים ביותר לפי רום הנביעה",
        "high_caption": "המעיינות הגבוהים ביותר לפי רום הנביעה",
        "map_aria": f"מפה אינטראקטיבית של {_int(n)} המעיינות בקטלוג. גרסה נגישה: טבלת הנתונים בהמשך העמוד.",
        "top_type": top_type,
    }

    summary = (f"איתור מעיינות בישראל לפי שם, אקויפר או תא דיווח: קטלוג השירות ההידרולוגי מונה {_int(n)} מעיינות, "
               f"מהם {_int(n_reg)} נמדדים באופן סדיר.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["מעיינות", "מים", "הידרולוגיה", "אקויפר", "רשות המים", "מפה"],
            "related_ids": [
                "073cd24f-58b0-4301-b6df-3b09607dfd46",
                "9b0286dd-aaa4-4dc6-9878-9c65abbee66e",
                "25862093-583b-43c4-b637-531645cf3955",
                "5de14d12-d5d7-475d-ade1-5dbd0ef9d086",
                "87514149-a73c-424d-89b4-80d3c9058f7a",
            ],
            "spatial_coverage": "ישראל",
            **({"temporal_coverage": f"{first_year}/{last_year}"} if first_year else {}),
        },
        "kpis": kpis,
        "kpi_labels": kpi_labels,
        "charts": {
            "type": chart_type,
            "region": chart_region,
            "aquifer": chart_aq,
            "cell": chart_cell,
            "decade": chart_decade,
            "elev": chart_elev,
            "box": chart_box,
            "profile": chart_profile,
            "offset": chart_offset,
        },
        "tables": {
            "type": table_type,
            "region": table_region,
            "aquifer": table_aq,
            "cell": table_cell,
            "decade": table_decade,
            "elev": table_elev,
            "box": table_box,
            "offset": table_offset,
            "oldest": t_oldest,
            "low": t_low,
            "high": t_high,
        },
        "flags": {
            "decade": chart_decade is not None,
            "elev": chart_elev is not None,
            "box": len(chart_box["cats"]) >= 2,
            "offset": n_mp > 0,
            "oldest": len(t_oldest) > 0,
        },
        "insights": insights,
        "labels": labels,
    }
