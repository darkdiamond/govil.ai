"""מספרי רישוי של כלי רכב לא פעילים עם קוד דגם — the stock of INACTIVE vehicles.

One row per vehicle whose licence expired more than 13 months before the
export, that is not reported stolen and has no final cancellation (scrapping).
The export is a rolling snapshot, so:

- `tokef_dt` (licence expiry) is the moment the vehicle went inactive. The
  monthly series is NOT a historical lapse rate: vehicles that lapsed long ago
  and were later scrapped have left the register, so older months are thin.
  The page says so.
- The newest expiry month is cut by the 13-month boundary and is almost always
  partial; trend rules use only full months.
- "Now" is never the clock: the latest expiry date in the data is the anchor.

Licence plates and VINs are never shown — everything is aggregated by maker,
model, year, fuel, ownership, colour and pollution group.
"""
import re

import pandas as pd

OTHER = "אחר"
UNKNOWN = "לא צוין"
TOP_BRANDS = 15
TOP_MODELS = 15
TOP_COLORS = 12
BOX_BRANDS = 10
TREND_BAND = 0.05          # ±5% year-on-year counts as "stable"
OLD_AGE = 20               # "בני 20 ומעלה" at lapse
PEAK_RATIO = 1.5           # a production year this many × its neighbours' mean is a spike
RECENT_MONTHS = 24         # "recent lapses" window for the EV rule
MAX_MONTHLY_POINTS = 480   # beyond this the lapse series switches to quarters

FUEL_GROUPS = {
    "בנזין": "בנזין", "דיזל": "דיזל", 'גפמ"': 'גפ"מ', "גז טבעי דחוס": "גז טבעי",
    "חשמל/בנזין": "היברידי", "חשמל/דיזל": "היברידי", "חשמל": "חשמלי",
}
FUEL_ORDER = ["בנזין", "דיזל", 'גפ"מ', "היברידי", "חשמלי", "גז טבעי", OTHER]
ELECTRIFIED = ("היברידי", "חשמלי")
DEGEM = {"P": "רכב פרטי", "M": "רכב מסחרי"}
OWNER_ORDER = ["פרטי", "חברה", "סוחר", "ליסינג", "השכרה"]

# Multi-word brand prefixes in tozeret_nm ("<brand> <plant country>"), and
# spelling variants of the same brand. Anything not listed falls back to the
# first word, so new makers flow through.
BRAND_PREFIXES = [
    ("ב מ וו", "ב.מ.וו"), ("מרצדס בנץ", "מרצדס-בנץ"), ("אלפא רומיאו", "אלפא רומיאו"),
    ("דיימלר קרייזלר", "דיימלר קרייזלר"), ("דימלרקריזלר", "דיימלר קרייזלר"),
    ("גרייט וול", "גרייט וול"), ("בי ווי די", "BYD"), ("אסטון מרטין", "אסטון מרטין"),
    ("מ.ג", "MG"), ("די אס", "DS"), ("לינק אנד קו", "לינק אנד קו"),
    ("פיאט קרייזלר", "פיאט"), ("טויוטה ב מ וו", "טויוטה"), ("האמר ג.מ.", "האמר"),
]
BRAND_ALIASES = {
    "אודי": "אאודי", "דאציה": "דאצ'יה", "לנציה": "לנצ'יה", "גיפ": "ג'יפ",
    "לנדרובר": "לנד רובר", "מרוטי": "סוזוקי", "פיאט/מדייר": "סוזוקי",
}
AGE_BINS = [(0, 4, "עד 4"), (5, 9, "5–9"), (10, 14, "10–14"), (15, 19, "15–19"),
            (20, 24, "20–24"), (25, 999, "25 ומעלה")]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _m_he(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _top_other(series, n):
    vc = _ranked(series)
    top = vc.head(n)
    rest = int(vc.iloc[n:].sum())
    names, values = list(top.index), [int(v) for v in top]
    if rest:
        names.append(OTHER)
        values.append(rest)
    return names, values


def _brand(name):
    s = name.strip()
    if not s:
        return UNKNOWN
    for prefix, brand in BRAND_PREFIXES:
        if s.startswith(prefix):
            return brand
    first = re.split(r"[\s\-_]+", s)[0]
    return BRAND_ALIASES.get(first, first)


def _gershayim(s):
    return re.sub(r'([א-ת])([א-ת])"(?=\s|$)', r"\1״\2", s)


def _bucket(v, bins):
    for lo, hi, label in bins:
        if lo <= v <= hi:
            return label
    return None


def _prepare(df):
    names = df["tozeret_nm"].str.strip()
    brand_map = {n: _brand(n) for n in names.unique()}
    out = pd.DataFrame({
        "brand": names.map(brand_map),
        "degem": df["sug_degem"].str.strip().map(DEGEM).fillna(UNKNOWN),
        "model_key": df["kinuy_mishari"].str.upper().str.replace(r"[\s\-_.]+", "", regex=True),
        "model_raw": df["kinuy_mishari"].str.strip(),
        "year": pd.to_numeric(df["shnat_yitzur"], errors="coerce"),
        "test": pd.to_datetime(df["mivchan_acharon_dt"], errors="coerce", format="%Y-%m-%d"),
        "expiry": pd.to_datetime(df["tokef_dt"], errors="coerce", format="%Y-%m-%d"),
        "owner": df["baalut"].str.strip().replace("", UNKNOWN),
        "color": df["tzeva_rechev"].str.strip().replace("", "לא ידוע"),
        "fuel": df["sug_delek_nm"].str.strip().map(FUEL_GROUPS).fillna(OTHER),
        "pollution": pd.to_numeric(df["kvutzat_zihum"], errors="coerce"),
    })
    out.loc[out["test"].dt.year < 1990, "test"] = pd.NaT   # 1900-01-01 placeholders
    out["age"] = (out["expiry"].dt.year - out["year"]).clip(lower=0)
    out["month"] = out["expiry"].dt.to_period("M")
    return out


def _model_table(df):
    """Top models: brand + normalised trade name (MAZDA 3 == MAZDA3), shown
    with the most common spelling."""
    m = df[df["model_key"] != ""]
    counts = m.groupby(["brand", "model_key"]).size()
    counts = counts.sort_index().sort_values(ascending=False, kind="stable")
    spell = (m.groupby(["brand", "model_key", "model_raw"]).size()
             .reset_index(name="n")
             .sort_values(["brand", "model_key", "n", "model_raw"],
                          ascending=[True, True, False, True], kind="stable")
             .drop_duplicates(["brand", "model_key"])
             .set_index(["brand", "model_key"])["model_raw"])
    rows = []
    for (b, k), n in counts.head(TOP_MODELS).items():
        rows.append({"name": f"{spell[(b, k)]} ({b})", "model": spell[(b, k)], "brand": b, "n": int(n)})
    return rows, len(counts)


def _full_months(df):
    """Monthly counts with the last month dropped when it is cut short (the
    13-month boundary falls inside it)."""
    exp = df["expiry"].dropna()
    last = exp.max()
    counts = df["month"].value_counts()
    months = pd.period_range(df["month"].min(), df["month"].max(), freq="M")
    s = pd.Series([int(counts.get(p, 0)) for p in months], index=months)
    partial = last.day < last.days_in_month
    return s, partial, (s.iloc[:-1] if partial else s)


def insight_trend(full):
    if len(full) < 24:
        return None, None
    cur, prev = int(full.iloc[-12:].sum()), int(full.iloc[-24:-12].sum())
    if prev == 0:
        return None, None
    ch = cur / prev - 1
    span = f"{_m_he(full.index[-12])}–{_m_he(full.index[-1])}"
    if abs(ch) < TREND_BAND:
        text = (f"ב-12 החודשים {span} פג תוקפם של {_int(cur)} כלי רכב שנותרו לא פעילים — "
                f"דומה ל-12 החודשים שקדמו להם ({_int(prev)}).")
    else:
        word = "יותר" if ch > 0 else "פחות"
        text = (f"ב-12 החודשים {span} פג תוקפם של {_int(cur)} כלי רכב שנותרו לא פעילים, "
                f"{_pct(abs(ch))} {word} מאשר ב-12 החודשים שקדמו להם ({_int(prev)}).")
        if ch > 0:
            text += " חלק מהפער נובע מכך שלכלי רכב שתוקפם פג מוקדם יותר היה זמן רב יותר לחזור לכביש או להתבטל סופית."
    return text, ch


def insight_peak(years):
    vc = years.value_counts().sort_index()
    if len(vc) < 5:
        return None
    peak = int(vc.sort_values(ascending=False, kind="stable").index[0])
    nb = [vc.get(peak - 1), vc.get(peak + 1)]
    nb = [int(v) for v in nb if v is not None and not pd.isna(v)]
    if not nb:
        return None
    base = sum(nb) / len(nb)
    n = int(vc[peak])
    if base == 0 or n < PEAK_RATIO * base:
        return None
    return (f"שנתון {peak} בולט במיוחד: {_int(n)} כלי רכב לא פעילים, פי {n / base:.1f} "
            f"מהממוצע של השנתונים הסמוכים לו.")


def insight_age(df):
    a = df["age"].dropna()
    if len(a) < 100:
        return None
    med = int(a.median())
    old = (a >= OLD_AGE).mean()
    return (f"הגיל החציוני של כלי רכב בעת פקיעת הרישוי הוא {med} שנים; "
            f"{_pct(old)} מהם היו בני {OLD_AGE} ומעלה.")


def insight_brand(df):
    vc = _ranked(df["brand"])
    if len(vc) < 3:
        return None
    (b1, n1), (b2, n2), (b3, n3) = list(vc.items())[:3]
    share = n1 / len(df)
    if share < 0.08:
        return None
    lead = ", בפער ניכר," if n1 >= 1.25 * n2 else ""
    return (f"היצרן הנפוץ ביותר{lead} הוא {b1} עם {_int(n1)} כלי רכב לא פעילים ({_pct(share)}), "
            f"לפני {b2} ({_int(n2)}) ו{b3} ({_int(n3)}).")


def insight_model(rows, n):
    if len(rows) < 2:
        return None
    a, b = rows[0], rows[1]
    return (f"הדגם הנפוץ ביותר הוא {a['model']} של {a['brand']} ({_int(a['n'])} כלי רכב, "
            f"{_pct(a['n'] / n)}), ואחריו {b['model']} של {b['brand']} ({_int(b['n'])}).")


def insight_ev(df, recent_from):
    ev = df[df["fuel"].isin(ELECTRIFIED)]
    if len(ev) < 50:
        return None
    ev_recent = (ev["month"] >= recent_from).mean()
    all_recent = (df["month"] >= recent_from).mean()
    text = (f"{_int(len(ev))} כלי רכב חשמליים והיברידיים ({_pct(len(ev) / len(df))}) נמצאים במאגר")
    if ev_recent >= all_recent + 0.1:
        text += (f"; {_pct(ev_recent)} מהם פג תוקפם ב-{RECENT_MONTHS} החודשים האחרונים שבנתונים, "
                 f"לעומת {_pct(all_recent)} מכלל כלי הרכב")
    return text + "."


def insight_owner(df):
    vc = _ranked(df["owner"])
    n = len(df)
    priv = int(vc.get("פרטי", 0))
    dealer = int(vc.get("סוחר", 0))
    company = int(vc.get("חברה", 0))
    if priv / n < 0.5 or dealer + company == 0:
        return None
    return (f"{_pct(priv / n)} מכלי הרכב רשומים בבעלות פרטית; {_int(company)} בבעלות חברה "
            f"ו-{_int(dealer)} ({_pct(dealer / n)}) עדיין רשומים על שם סוחר רכב.")


def insight_test_after(df):
    both = df.dropna(subset=["test", "expiry"])
    after = both[both["test"] > both["expiry"]]
    if len(both) == 0 or len(after) / len(both) < 0.01:
        return None
    return (f"ל-{_int(len(after))} כלי רכב ({_pct(len(after) / len(both))}) נרשמה בדיקת רישוי "
            f"אחרונה אחרי מועד פקיעת הרישוי — ובכל זאת הרישוי לא חודש.")


def insight_pollution(df):
    p = df["pollution"].dropna()
    if len(p) < 100:
        return None
    worst = int(p.max())
    share = (p == worst).mean()
    if share < 0.3:
        return None
    return (f"מבין {_int(len(p))} כלי הרכב שלהם קבוצת זיהום רשומה, {_pct(share)} "
            f"משויכים לקבוצה {worst} — המזהמת ביותר בסולם.")


def compute(frames):
    df = _prepare(frames["vehicles"])
    n = len(df)
    exp = df["expiry"].dropna()
    last_exp, first_exp = exp.max(), exp.min()
    years = df["year"].dropna().astype(int)
    y0, y1 = int(years.min()), int(years.max())

    # ── Lapse timeline (month of licence expiry) ────────────────────────────
    monthly, partial, full = _full_months(df)
    if len(monthly) > MAX_MONTHLY_POINTS:
        q = monthly.groupby(monthly.index.asfreq("Q")).sum()
        lapse = {"x": [f"{p.year} Q{p.quarter}" for p in q.index], "y": [int(v) for v in q],
                 "partial": partial, "unit": "רבעון"}
    else:
        lapse = {"x": [f"{p.year}-{p.month:02d}" for p in monthly.index],
                 "y": [int(v) for v in monthly], "partial": partial, "unit": "חודש"}
    lapse["zoom_start"] = max(0, round(100 - 10 * 12 / max(len(monthly), 1) * 100))
    trend_text, trend_ch = insight_trend(full)
    recent_from = monthly.index[-RECENT_MONTHS] if len(monthly) >= RECENT_MONTHS else monthly.index[0]
    last24 = int(monthly.iloc[-RECENT_MONTHS:].sum())
    peak_m = monthly.sort_index().sort_values(ascending=False, kind="stable")

    # ── Production year × private/commercial ────────────────────────────────
    yv = df.dropna(subset=["year"]).copy()
    yv["year"] = yv["year"].astype(int)
    piv = yv.groupby(["year", "degem"]).size().unstack(fill_value=0).sort_index()
    degem_cols = [c for c in DEGEM.values() if c in piv.columns] + \
                 sorted(c for c in piv.columns if c not in DEGEM.values())
    vintage = {"x": [str(y) for y in piv.index],
               "series": [{"name": c, "data": [int(v) for v in piv[c]]} for c in degem_cols]}
    coh = (yv["year"] // 5 * 5)
    ct = yv.groupby([coh, "degem"]).size().unstack(fill_value=0).sort_index()
    t_vintage = [{"name": f"{c}–{c + 4}", "total": _int(ct.loc[c].sum()),
                  "cols": [_int(ct.loc[c].get(k, 0)) for k in degem_cols]} for c in ct.index]

    # ── Age at lapse ────────────────────────────────────────────────────────
    ages = df["age"].dropna().astype(int)
    age_vc = ages.value_counts().sort_index()
    age_x = list(range(0, int(ages.max()) + 1))
    age_hist = {"x": [str(a) for a in age_x], "y": [int(age_vc.get(a, 0)) for a in age_x]}
    ab = ages.map(lambda a: _bucket(a, AGE_BINS)).value_counts()
    t_age = [{"name": b[2], "count": _int(ab.get(b[2], 0)),
              "share": f"{ab.get(b[2], 0) / max(len(ages), 1) * 100:.1f}"} for b in AGE_BINS]
    med_age = int(ages.median())

    # ── Brands, models ──────────────────────────────────────────────────────
    b_names, b_vals = _top_other(df["brand"], TOP_BRANDS)
    model_rows, n_models = _model_table(df)

    def rank_rows(names, vals, total=n):
        return [{"name": a, "count": _int(b), "share": f"{b / total * 100:.1f}"} for a, b in zip(names, vals)]

    # Age at lapse per leading brand — p5/p25/median/p75/p95.
    box_brands = list(_ranked(df["brand"]).head(BOX_BRANDS).index)
    box, t_box = [], []
    for b in box_brands:
        a = df.loc[df["brand"] == b, "age"].dropna()
        qs = [float(a.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
        box.append([round(v, 1) for v in qs])
        t_box.append({"name": b, "q1": f"{qs[1]:g}", "med": f"{qs[2]:g}", "q3": f"{qs[3]:g}"})
    order = sorted(range(len(box_brands)), key=lambda i: (box[i][2], box[i][1], box_brands[i]))
    box_chart = {"names": [box_brands[i] for i in order], "data": [box[i] for i in order]}
    t_box = [t_box[i] for i in order]
    young = box_chart["names"][0] if box_chart["names"] else ""
    old = box_chart["names"][-1] if box_chart["names"] else ""

    # ── Fuel ────────────────────────────────────────────────────────────────
    fv = df["fuel"].value_counts()
    f_names = [f for f in FUEL_ORDER if fv.get(f, 0)]
    t_fuel = rank_rows(f_names, [int(fv[f]) for f in f_names])
    fuel_bar = {"names": f_names, "values": [int(fv[f]) for f in f_names]}
    ev = df[df["fuel"].isin(ELECTRIFIED)].dropna(subset=["year"])
    ev_y0 = int(ev["year"].min()) if len(ev) else y1
    evp = ev.groupby([ev["year"].astype(int), "fuel"]).size().unstack(fill_value=0)
    ev_years = list(range(ev_y0, y1 + 1))
    evp = evp.reindex(index=ev_years, columns=list(ELECTRIFIED), fill_value=0)
    ev_chart = {"x": [str(y) for y in ev_years],
                "series": [{"name": f, "data": [int(v) for v in evp[f]]} for f in ELECTRIFIED]}
    ev_models, _ = _model_table(df[df["fuel"].isin(ELECTRIFIED)])
    ev_models = ev_models[:5]
    t_ev = [{"name": r["name"], "count": _int(r["n"])} for r in ev_models]
    n_ev = int(df["fuel"].isin(ELECTRIFIED).sum())

    # ── Ownership × private/commercial ─────────────────────────────────────
    ov = _ranked(df["owner"])
    owners = [o for o in OWNER_ORDER if o in ov.index] + [o for o in ov.index if o not in OWNER_ORDER]
    op = df.groupby(["owner", "degem"]).size().unstack(fill_value=0).reindex(index=owners, fill_value=0)
    owner_chart = {"names": owners,
                   "series": [{"name": c, "data": [int(op.loc[o].get(c, 0)) for o in owners]}
                              for c in degem_cols]}
    t_owner = [{"name": o, "count": _int(ov[o]), "share": f"{ov[o] / n * 100:.1f}"} for o in owners]

    # ── Colour, pollution ──────────────────────────────────────────────────
    c_names, c_vals = _top_other(df["color"], TOP_COLORS)
    pol = df["pollution"].dropna().astype(int)
    pol_vc = pol.value_counts()
    pol_x = list(range(int(pol.min()), int(pol.max()) + 1)) if len(pol) else []
    pol_chart = {"x": [str(v) for v in pol_x], "y": [int(pol_vc.get(v, 0)) for v in pol_x]}
    t_pol = [{"name": str(v), "count": _int(pol_vc.get(v, 0)),
              "share": f"{pol_vc.get(v, 0) / max(len(pol), 1) * 100:.1f}"} for v in pol_x]
    pol_years = df.loc[df["pollution"].notna(), "year"].dropna()
    pol_from = int(pol_years.quantile(0.01)) if len(pol_years) else y1

    # ── Insights ───────────────────────────────────────────────────────────
    rules = [
        ("trend", trend_text),
        ("age", insight_age(df)),
        ("brand", insight_brand(df)),
        ("model", insight_model(model_rows, n)),
        ("peak", insight_peak(years)),
        ("ev", insight_ev(df, recent_from)),
        ("owner", insight_owner(df)),
        ("test_after", insight_test_after(df)),
        ("pollution", insight_pollution(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    if trend_ch is None or abs(trend_ch) < TREND_BAND:
        trend_tone, trend_display = "brand", (_pct(trend_ch) if trend_ch is not None else "—")
    else:
        trend_tone = "warn" if trend_ch > 0 else "ok"
        trend_display = ("+" if trend_ch > 0 else "−") + _pct(abs(trend_ch))
    last12 = int(full.iloc[-12:].sum()) if len(full) >= 12 else int(full.sum())
    private_share = (df["degem"] == DEGEM["P"]).mean()

    partial_note = (f" החודש האחרון ({_m_he(monthly.index[-1])}) חלקי — הוא נחתך בגבול 13 החודשים."
                    if partial else "")

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} כלי רכב לא פעילים — שתוקף רישוים פג לפני יותר מ-13 חודשים, "
                           f"לא דווחו כגנובים ולא בוטלו סופית. שנות ייצור {y0}–{y1}; "
                           f"הגיל החציוני בעת פקיעת הרישוי {med_age} שנים, "
                           f"והיצרן הנפוץ ביותר {b_names[0]}."),
            "dataset_kind": "registry",
            "related_ids": [
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "0f16b39a-6016-408d-805d-31f40d5a0990",
                "9b2ac550-d4bf-4da6-a1f2-bcfd57ed5e7f",
                "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                "392abd0a-64f6-4c18-9d56-0111001411e6",
            ],
            "suggested_tags": ["כלי רכב", "רכב לא פעיל", "רישוי רכב", "צי הרכב", "תחבורה"],
            "temporal_coverage": f"{first_exp.year}/{last_exp.year}",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "last12": {"value": last12, "display": _int(last12), "tone": "info"},
            "trend": {"value": round(trend_ch, 4) if trend_ch is not None else None,
                      "display": trend_display, "tone": trend_tone},
            "med_age": {"value": med_age, "display": str(med_age),
                        "tone": "warn" if med_age >= 15 else "brand"},
        },
        "charts": {
            "lapse": lapse,
            "vintage": vintage,
            "age": age_hist,
            "box": box_chart,
            "brands": {"names": b_names, "values": b_vals},
            "models": {"names": [r["name"] for r in model_rows], "values": [r["n"] for r in model_rows]},
            "fuel": fuel_bar,
            "ev": ev_chart,
            "owner": owner_chart,
            "colors": {"names": c_names, "values": c_vals},
            "pollution": pol_chart,
        },
        "tables": {
            "degem_cols": degem_cols,
            "vintage": t_vintage,
            "age": t_age,
            "box": t_box,
            "brands": rank_rows(b_names, b_vals),
            "models": [{"name": r["name"], "count": _int(r["n"]), "share": f"{r['n'] / n * 100:.1f}"}
                       for r in model_rows],
            "fuel": t_fuel,
            "ev": t_ev,
            "owner": t_owner,
            "colors": rank_rows(c_names, c_vals),
            "pollution": t_pol,
        },
        "insights": insights,
        "labels": {
            "lede": (f"המאגר מונה {_int(n)} כלי רכב שתוקף רישוים פג לפני יותר מ-13 חודשים, שאינם "
                     f"מדווחים כגנובים ושלא בוטלו סופית — כלומר רכבים שירדו מהכביש אך רישומם לא בוטל סופית. "
                     f"מועד הפקיעה המאוחר ביותר בנתונים הוא {_d_he(last_exp)}; "
                     f"{_pct(private_share)} מהם רכבים פרטיים והשאר מסחריים."),
            "total_kpi": "כלי רכב לא פעילים",
            "last12_kpi": "פקיעות רישוי ב-12 החודשים המלאים האחרונים",
            "trend_kpi": "שינוי לעומת 12 החודשים שקדמו",
            "age_kpi": "גיל חציוני בעת פקיעת הרישוי (שנים)",
            "lapse_note": (f"מספר כלי הרכב במאגר לפי {lapse['unit']} פקיעת הרישוי. "
                           f"ב-{RECENT_MONTHS} החודשים האחרונים שבנתונים פג תוקפם של {_int(last24)} "
                           f"מהם ({_pct(last24 / n)}); השיא — {_m_he(peak_m.index[0])} "
                           f"({_int(peak_m.iloc[0])}). כלי רכב שפג תוקפם לפני שנים רבות ובינתיים "
                           f"בוטלו סופית כבר אינם במאגר, ולכן החודשים המוקדמים דלילים — זו "
                           f"תמונת המלאי הנוכחי, לא קצב היסטורי.{partial_note}"),
            "lapse_aria": (f"תרשים קו: כלי רכב לא פעילים לפי {lapse['unit']} פקיעת הרישוי, "
                           f"{first_exp.year}–{last_exp.year}."),
            "vintage_note": (f"שנות ייצור {y0}–{y1}. כל עמודה מחולקת לרכב פרטי ומסחרי."),
            "vintage_aria": f"תרשים עמודות: כלי רכב לא פעילים לפי שנת ייצור, {y0}–{y1}.",
            "vintage_caption": "כלי רכב לפי מחזור שנות ייצור (חמש שנים).",
            "age_note": (f"הפרש השנים בין שנת הייצור לשנת פקיעת הרישוי. החציון: {med_age} שנים."),
            "age_aria": "תרשים עמודות: גיל כלי הרכב בעת פקיעת הרישוי.",
            "box_note": (f"{BOX_BRANDS} היצרנים הנפוצים, מסודרים מהצעיר לוותיק. התיבה מציגה את "
                         f"הרבעון התחתון עד העליון, הקו — החציון, והשפמים — אחוזון 5 עד 95. "
                         f"כלי הרכב של {young} יורדים מהכביש הצעירים ביותר, ושל {old} — הוותיקים ביותר."),
            "box_aria": f"תרשים תיבה: גיל בעת פקיעת הרישוי לפי {BOX_BRANDS} היצרנים המובילים.",
            "brands_note": ("שם היצרן מאוחד מכל ארצות המפעל (למשל רנו צרפת, טורקיה וספרד)."),
            "brands_aria": f"תרשים עמודות: {TOP_BRANDS} היצרנים המובילים.",
            "models_note": (f"הכינוי המסחרי של הדגם, מאוחד בין כתיבים שונים ({_int(n_models)} דגמים במאגר)."),
            "models_aria": f"תרשים עמודות: {TOP_MODELS} הדגמים הנפוצים.",
            "fuel_aria": "תרשים עמודות: כלי רכב לא פעילים לפי סוג דלק.",
            "ev_note": (f"{_int(n_ev)} כלי רכב חשמליים והיברידיים, לפי שנת ייצור "
                        f"({ev_y0}–{y1}). היברידי = חשמל/בנזין או חשמל/דיזל."),
            "ev_aria": "תרשים עמודות: כלי רכב חשמליים והיברידיים לא פעילים לפי שנת ייצור.",
            "ev_caption": "הדגמים החשמליים וההיברידיים הנפוצים במאגר.",
            "owner_aria": "תרשים עמודות: כלי רכב לפי סוג הבעלות, פרטי מול מסחרי.",
            "colors_aria": f"תרשים עמודות: {TOP_COLORS} הצבעים הנפוצים.",
            "pollution_note": (f"לכלי רכב שיוצרו מ-{pol_from} ואילך (ל-{_int(len(pol))} מהם רשומה קבוצה). "
                               f"קבוצה {pol_x[0] if pol_x else ''} היא הנקייה ביותר וקבוצה "
                               f"{pol_x[-1] if pol_x else ''} המזהמת ביותר."),
            "pollution_aria": "תרשים עמודות: כלי רכב לפי קבוצת זיהום.",
        },
    }
