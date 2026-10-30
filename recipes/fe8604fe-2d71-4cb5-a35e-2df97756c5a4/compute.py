"""כלי רכב שירדו מהכביש ובסטטוס ביטול סופי: every vehicle whose licence was
finally cancelled (scrapped / written off), one row per vehicle.

The dataset is published as several files that share one schema: a rolling
file for recent years (2017 onward today) plus frozen archive files
(2000-2009, 2010-2016). The recipe concatenates every matching file, so a new
archive split or yearly file flows in automatically.

- `bitul_dt` (cancellation date) drives every time view. "Now" is never the
  clock: the anchor is the latest date in the data that carries a real day's
  volume (a handful of rows are stamped weeks into the future; they are kept
  in the totals and disclosed, but left out of the time charts).
- The anchor's year and month are usually partial. Year-on-year comparisons
  use the same calendar window of the previous year (year to date), and trend
  rules use full years only.
- Plates, VINs and engine numbers are never shown: everything is aggregated
  by year, maker, model, vehicle type, fuel, ownership and colour.
"""
import re

import pandas as pd

OTHER = "אחר"
UNKNOWN = "לא ידוע"
TOP_BRANDS = 15
TOP_MODELS = 15
TOP_COLORS = 12
SHIFT_BRANDS = 7            # top N of each window (union)
TOP_DAYS = 10
WINDOW_YEARS = 5           # early vs recent brand-share windows
TREND_BAND = 0.05          # ±5% counts as "stable"
OUTLIER_BAND = 0.15        # a full year this far from its neighbours' mean stands out
OLD_AGE = 20               # "בני 20 ומעלה" at cancellation
MAX_AGE = 70               # older than this (or negative) = bad production year
MODEL_FILL = 0.75          # trade name filled for at least this share of a year's rows
ANCHOR_MIN_DAY = 10        # a day with at least this many rows counts as real volume
EV_MIN = 10                # electrified series starts at the first year with this many
MAX_MONTHLY_POINTS = 600   # beyond this the monthly series switches to quarters
SEASON_RATIO = 1.15        # busiest / quietest calendar month for the season rule
YTD_MIN_DAYS = 45          # year-to-date comparison needs this many days into the year

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

FUEL_GROUPS = {
    "בנזין": "בנזין", "דיזל": "דיזל", 'גפמ"': "גפ״מ", 'גפ"מ': "גפ״מ",
    "חשמל": "חשמלי", "חשמל/בנזין": "היברידי", "חשמל/דיזל": "היברידי",
    "גז טבעי דחוס": "גז טבעי",
}
FUEL_ORDER = ["בנזין", "דיזל", "גפ״מ", "היברידי", "חשמלי", "גז טבעי", "לא ידוע"]
ELECTRIFIED = ["חשמלי", "היברידי"]

# Vehicle-type families, matched on the start of sug_rechev_nm. First match
# wins; anything unmatched (tractors, work vehicles, ambulances) is "אחר".
TYPE_PREFIXES = [
    ("פרטי", "רכב פרטי"),
    ("מונית", "מוניות"),
    ("אוטובוס", "אוטובוסים"), ("טיולית", "אוטובוסים"),
    ("אופנוע", "אופנועים וקטנועים"), ("קטנוע", "אופנועים וקטנועים"),
    ("תלת אופנוע", "אופנועים וקטנועים"), ("תלת קטנוע", "אופנועים וקטנועים"),
    ("משא", "משא ומסחרי"), ("מרכב אחוד", "משא ומסחרי"),
    ("גרור", "גרורים ונתמכים"), ("נתמך", "גרורים ונתמכים"),
]
TYPE_ORDER = ["רכב פרטי", "משא ומסחרי", "אופנועים וקטנועים", "מוניות",
              "אוטובוסים", "גרורים ונתמכים", OTHER]
OWNER_ORDER = ["פרטי", "חברה", "ליסינג", "השכרה"]

# Multi-word maker prefixes in tozeret_nm ("<maker> <plant country>"), and
# spelling variants of the same maker. Anything not listed falls back to the
# first word, so new makers flow through.
BRAND_PREFIXES = [
    ("ב מ וו", "ב.מ.וו"), ("מרצדס בנץ", "מרצדס-בנץ"), ("דימלר בנץ", "מרצדס-בנץ"),
    ("דימלרקריזלר", "דיימלר קרייזלר"), ("דיימלר קרייזלר", "דיימלר קרייזלר"),
    ("אלפא רומיאו", "אלפא רומיאו"), ("סאן יאנג", "סאן יאנג"),
    ("קואנג יאנג", "קואנג יאנג"), ("מ א ן", "מאן"), ("מ.ג", "MG"), ("מ. ג", "MG"),
    ("בי ווי די", "BYD"), ("ג'י.אמ.סי", "ג'י.אמ.סי"), ("לנד רובר", "לנד רובר"),
    ("גרייט וול", "גרייט וול"), ("אסטון מרטין", "אסטון מרטין"), ("די אס", "DS"),
]
BRAND_ALIASES = {
    "אודי": "אאודי", "דאציה": "דאצ'יה", "לנציה": "לנצ'יה", "גיפ": "ג'יפ",
    "לנדרובר": "לנד רובר", "פיאגיו": "פיאג'ו", "פיאג'יו": "פיאג'ו",
    "ימאהה": "ימהה", "מאזדה": "מזדה",
}
AGE_BINS = [(0, 4, "עד 4"), (5, 9, "5-9"), (10, 14, "10-14"), (15, 19, "15-19"),
            (20, 24, "20-24"), (25, 29, "25-29"), (30, MAX_AGE, "30 ומעלה")]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _vav(word):
    """Hebrew "and" prefix: glued to a Hebrew word, "ו-" before Latin/digits."""
    w = str(word)
    return f"ו{w}" if w[:1] and "\u05d0" <= w[0] <= "\u05ea" else f"ו-{w}"


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
    first = re.split(r"[\s\-_*]+", s)[0]
    return BRAND_ALIASES.get(first, first)


def _vtype(name):
    s = name.strip()
    for prefix, group in TYPE_PREFIXES:
        if s.startswith(prefix):
            return group
    return OTHER


def _gershayim(s):
    return re.sub(r'([א-ת])"([א-ת])', "\\1״\\2", s)


def _map_unique(series, fn):
    u = series.unique()
    return series.map(dict(zip(u, (fn(x) for x in u))))


def _prepare(df):
    out = pd.DataFrame({
        "date": pd.to_datetime(df["bitul_dt"].str.strip(), errors="coerce", format="%Y-%m-%d"),
        "brand": _map_unique(df["tozeret_nm"], _brand),
        "vtype": _map_unique(df["sug_rechev_nm"], _vtype),
        "year_made": pd.to_numeric(df["shnat_yitzur"], errors="coerce"),
        "owner": df["baalut"].str.strip().replace("", UNKNOWN),
        "color": _map_unique(df["tzeva_rechev"], lambda s: s.strip() or UNKNOWN),
        "fuel": _map_unique(df["sug_delek_nm"], lambda s: FUEL_GROUPS.get(s.strip(), "לא ידוע")),
        "model_raw": df["kinuy_mishari"].str.strip(),
    })
    out["model_key"] = out["model_raw"].str.upper().str.replace(r"[\s\-_.]+", "", regex=True)
    out = out.dropna(subset=["date"])
    out["year"] = out["date"].dt.year
    age = out["year"] - out["year_made"]
    out["age"] = age.where((age >= 0) & (age <= MAX_AGE))
    return out


def _anchor(df):
    """Latest date carrying a real day's volume; stray future-dated rows
    beyond it are excluded from time views (and disclosed)."""
    days = df["date"].value_counts()
    real = days[days >= ANCHOR_MIN_DAY]
    return (real.index.max() if len(real) else days.index.max())


def _same_window(ts, year):
    day = min(ts.day, pd.Timestamp(year=year, month=ts.month, day=1).days_in_month)
    return pd.Timestamp(year=year, month=ts.month, day=day)


# ── Insight rules ─────────────────────────────────────────────────────────


def insight_ytd(cur, prev, year, anchor):
    if prev == 0 or anchor.dayofyear < YTD_MIN_DAYS:
        return None, None
    ch = cur / prev - 1
    span = f"מתחילת {year} ועד {anchor.day} ב{MONTHS_HE[anchor.month - 1]}"
    if abs(ch) < TREND_BAND:
        text = (f"{span} בוטלו סופית {_int(cur)} כלי רכב, בדומה לתקופה המקבילה "
                f"ב-{year - 1} ({_int(prev)}).")
    else:
        word = "יותר" if ch > 0 else "פחות"
        text = (f"{span} בוטלו סופית {_int(cur)} כלי רכב, {_pct(abs(ch))} {word} "
                f"מאשר בתקופה המקבילה ב-{year - 1} ({_int(prev)}).")
    return text, ch


def insight_long(full):
    if len(full) < 8:
        return None
    y0, y1 = int(full.index[0]), int(full.index[-1])
    v0, v1 = int(full.iloc[0]), int(full.iloc[-1])
    if v0 == 0:
        return None
    ratio = v1 / v0
    peak_y = int(full.sort_index().sort_values(ascending=False, kind="stable").index[0])
    text = f"ב-{y1} בוטלו סופית {_int(v1)} כלי רכב"
    if ratio >= 1.2:
        text += f", פי {ratio:.1f} מאשר ב-{y0} ({_int(v0)})"
    elif ratio <= 0.8:
        text += f", {_pct(1 - ratio)} פחות מאשר ב-{y0} ({_int(v0)})"
    else:
        text += f", בדומה ל-{y0} ({_int(v0)})"
    if peak_y != y1:
        text += f". שנת השיא בנתונים היא {peak_y} עם {_int(full[peak_y])} ביטולים"
    return text + "."


def insight_outlier_year(full):
    """The full year that departs most from the mean of its two neighbours."""
    if len(full) < 5:
        return None
    best = None
    ys = list(full.index)
    for i in range(1, len(ys) - 1):
        nb = (full.iloc[i - 1] + full.iloc[i + 1]) / 2
        if nb == 0:
            continue
        dev = full.iloc[i] / nb - 1
        if best is None or abs(dev) > abs(best[1]) + 1e-12:
            best = (ys[i], dev, int(full.iloc[i]), int(full.iloc[i - 1]), int(full.iloc[i + 1]))
    if best is None or abs(best[1]) < OUTLIER_BAND:
        return None
    y, dev, v, before, after = best
    if dev < 0:
        return (f"{y} בולטת בירידה חדה: {_int(v)} ביטולים בלבד, {_pct(-dev)} פחות מהממוצע "
                f"של השנים הסמוכות ({_int(before)} ב-{y - 1} ו-{_int(after)} ב-{y + 1}).")
    return (f"{y} בולטת בזינוק: {_int(v)} ביטולים, {_pct(dev)} יותר מהממוצע של השנים "
            f"הסמוכות ({_int(before)} ב-{y - 1} ו-{_int(after)} ב-{y + 1}).")


def insight_age(age_stats, first_full, last_full, old_share):
    if first_full is None or last_full is None or first_full == last_full:
        return None
    m0, m1 = age_stats[first_full]["med"], age_stats[last_full]["med"]
    if m1 > m0:
        trend = f"עלה מ-{m0:g} שנים ב-{first_full} ל-{m1:g} שנים ב-{last_full}"
    elif m1 < m0:
        trend = f"ירד מ-{m0:g} שנים ב-{first_full} ל-{m1:g} שנים ב-{last_full}"
    else:
        trend = f"עמד על {m1:g} שנים גם ב-{first_full} וגם ב-{last_full}"
    return (f"הגיל החציוני של כלי רכב בעת הביטול הסופי {trend}; "
            f"ב-{last_full}, {_pct(old_share)} מכלי הרכב שבוטלו היו בני {OLD_AGE} ומעלה.")


def insight_brand(vc, n):
    if len(vc) < 3:
        return None
    (b1, n1), (b2, n2), (b3, n3) = list(vc.items())[:3]
    if n1 / n < 0.05 or n1 == n2:
        return None
    lead = ", בפער ניכר," if n1 >= 1.15 * n2 else ""
    return (f"היצרן הנפוץ ביותר{lead} בכל השנים הוא {b1} עם {_int(n1)} כלי רכב שבוטלו "
            f"({_pct(n1 / n)}), לפני {b2} ({_int(n2)}) {_vav(b3)} ({_int(n3)}).")


def insight_shift(rows, early_label, recent_label):
    if len(rows) < 3:
        return None
    up = max(rows, key=lambda r: (r["recent"] - r["early"], r["name"]))
    down = min(rows, key=lambda r: (r["recent"] - r["early"], r["name"]))
    gain, loss = up["recent"] - up["early"], down["recent"] - down["early"]
    if gain < 1 or loss > -1:
        return None
    return (f"תמהיל היצרנים השתנה: חלקה של {up['name']} בביטולים עלה מ-{up['early']:.1f}% "
            f"ב-{early_label} ל-{up['recent']:.1f}% ב-{recent_label}, ואילו חלקה של "
            f"{down['name']} ירד מ-{down['early']:.1f}% ל-{down['recent']:.1f}%.")


def insight_model(rows, from_year):
    if len(rows) < 2:
        return None
    a, b = rows[0], rows[1]
    if a["n"] == b["n"]:
        return None
    return (f"מאז {from_year}, הדגם שבוטל סופית הכי הרבה פעמים הוא {a['model']} של {a['brand']} "
            f"({_int(a['n'])} כלי רכב), ואחריו {b['model']} של {b['brand']} ({_int(b['n'])}).")


def insight_ev(ev_by_year, totals, last_full):
    if last_full is None or last_full not in ev_by_year.index:
        return None
    v1 = int(ev_by_year.loc[last_full].sum())
    if v1 < EV_MIN:
        return None
    share = v1 / int(totals[last_full])
    text = (f"ב-{last_full} בוטלו סופית {_int(v1)} כלי רכב חשמליים והיברידיים "
            f"({_pct(share, 2)} מהביטולים)")
    prev = last_full - 1
    if prev in ev_by_year.index:
        v0 = int(ev_by_year.loc[prev].sum())
        if v0 > 0 and v1 >= 1.2 * v0:
            text += f", פי {v1 / v0:.1f} מאשר ב-{prev}"
    return text + "."


def insight_day(top_days, daily):
    if not top_days:
        return None
    d, n = top_days[0]
    same_year = daily[daily.index.year == d.year]
    med = float(same_year.median()) if len(same_year) else 0
    if med <= 0 or n < 3 * med:
        return None
    return (f"היום עם מספר הביטולים הגבוה ביותר הוא {_d_he(d)}: {_int(n)} כלי רכב בוטלו "
            f"ביום אחד, פי {n / med:.0f} מהיום החציוני באותה שנה ({_int(med)}).")


def insight_season(month_share):
    if month_share is None:
        return None
    hi = month_share.sort_index().sort_values(ascending=False, kind="stable")
    top_m, low_m = int(hi.index[0]), int(hi.index[-1])
    if hi.iloc[-1] <= 0 or hi.iloc[0] / hi.iloc[-1] < SEASON_RATIO:
        return None
    return (f"בממוצע על פני השנים המלאות, {MONTHS_HE[top_m - 1]} הוא החודש העמוס ביותר "
            f"({hi.iloc[0] * 100:.1f}% מביטולי השנה) ו{MONTHS_HE[low_m - 1]} השקט ביותר "
            f"({hi.iloc[-1] * 100:.1f}%).")


def insight_types(type_year, first_full, last_full):
    if first_full is None or last_full is None or first_full == last_full:
        return None
    s0 = type_year.loc[first_full] / type_year.loc[first_full].sum()
    s1 = type_year.loc[last_full] / type_year.loc[last_full].sum()
    priv0, priv1 = float(s0.get("רכב פרטי", 0)), float(s1.get("רכב פרטי", 0))
    if priv1 < 0.5:
        return None
    moto = "אופנועים וקטנועים"
    m0, m1 = float(s0.get(moto, 0)), float(s1.get(moto, 0))
    text = (f"רכב פרטי הוא {_pct(priv1)} מהביטולים ב-{last_full} "
            f"(לעומת {_pct(priv0)} ב-{first_full})")
    if abs(m1 - m0) >= 0.01:
        text += f"; חלקם של אופנועים וקטנועים {'עלה' if m1 > m0 else 'ירד'} מ-{_pct(m0)} ל-{_pct(m1)}"
    return text + "."


# ── Builders ──────────────────────────────────────────────────────────────


def _model_rows(df):
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
    return rows


def compute(frames):
    raw = frames["main"]
    df = _prepare(raw)
    n = len(df)
    anchor = _anchor(df)
    stray = int((df["date"] > anchor).sum())
    tv = df[df["date"] <= anchor]                       # rows for time views
    first = tv["date"].min()
    y_first, y_last = int(first.year), int(anchor.year)
    year_partial = not (anchor.month == 12 and anchor.day == 31)
    start_partial = not (first.month == 1 and first.day <= 7)

    # ── Years ───────────────────────────────────────────────────────────
    yc = tv["year"].value_counts()
    years = list(range(y_first, y_last + 1))
    totals = pd.Series([int(yc.get(y, 0)) for y in years], index=years)
    full_years = [y for y in years
                  if not (y == y_last and year_partial) and not (y == y_first and start_partial)]
    full = totals.loc[full_years]
    last_full = full_years[-1] if full_years else None
    first_full = full_years[0] if full_years else None
    yearly = {"x": [str(y) for y in years], "y": [int(v) for v in totals],
              "partial": [bool(y == y_last and year_partial) for y in years]}
    t_yearly = [{"name": str(y) + (" (חלקית)" if y == y_last and year_partial else ""),
                 "count": _int(totals[y])} for y in years]

    # Year to date vs the same window last year.
    ytd_cur = int(((tv["year"] == y_last)).sum())
    prev_end = _same_window(anchor, y_last - 1)
    ytd_prev = int(((tv["date"] >= pd.Timestamp(year=y_last - 1, month=1, day=1))
                    & (tv["date"] <= prev_end)).sum())
    ytd_text, ytd_ch = insight_ytd(ytd_cur, ytd_prev, y_last, anchor)

    # ── Months ──────────────────────────────────────────────────────────
    per = tv["date"].dt.to_period("M")
    mc = per.value_counts()
    months = pd.period_range(per.min(), per.max(), freq="M")
    monthly = pd.Series([int(mc.get(p, 0)) for p in months], index=months)
    month_partial = anchor.day < anchor.days_in_month
    if len(monthly) > MAX_MONTHLY_POINTS:
        q = monthly.groupby(monthly.index.asfreq("Q")).sum()
        series = {"x": [f"{p.year} Q{p.quarter}" for p in q.index], "y": [int(v) for v in q],
                  "unit": "רבעון"}
        roll = q.rolling(4, min_periods=4).mean()
    else:
        series = {"x": [f"{p.year}-{p.month:02d}" for p in monthly.index],
                  "y": [int(v) for v in monthly], "unit": "חודש"}
        roll = monthly.rolling(12, min_periods=12).mean()
    series["avg"] = [None if pd.isna(v) else round(float(v), 1) for v in roll]
    if month_partial:
        series["avg"][-1] = None
    series["zoom_start"] = max(0, round(100 - 10 * 12 / max(len(monthly), 1) * 100))
    full_monthly = monthly.iloc[:-1] if month_partial else monthly
    peak_m = full_monthly.sort_index().sort_values(ascending=False, kind="stable")

    # Month × year heatmap + average calendar-month share over full years.
    heat_cells = []
    for i, y in enumerate(years):
        for m in range(1, 13):
            p = pd.Period(year=y, month=m, freq="M")
            if p < months[0] or p > months[-1]:
                continue
            heat_cells.append([m - 1, i, int(mc.get(p, 0))])
    heat_max = max((c[2] for c in heat_cells), default=0)
    month_share = None
    if full_years:
        fy = tv[tv["year"].isin(full_years)]
        ct = fy.groupby(["year", fy["date"].dt.month]).size().unstack(fill_value=0)
        ct = ct.reindex(columns=range(1, 13), fill_value=0)
        month_share = ct.div(ct.sum(axis=1), axis=0).mean(axis=0)

    # Busiest days.
    daily = tv["date"].value_counts()
    dsort = daily.sort_index().sort_values(ascending=False, kind="stable")
    top_days = [(d, int(v)) for d, v in dsort.head(TOP_DAYS).items()]
    days_chart = {"names": [_d_he(d) for d, _ in top_days], "values": [v for _, v in top_days]}
    t_days = [{"name": _d_he(d), "count": _int(v)} for d, v in top_days]
    med_day_last = float(daily[daily.index.year == (last_full or y_last)].median())

    # ── Age at cancellation ─────────────────────────────────────────────
    ages = tv.dropna(subset=["age"])
    bad_age = int(len(tv) - len(ages))
    g = ages.groupby("year")["age"]
    q = g.quantile([0.25, 0.5, 0.75]).unstack()
    age_stats = {int(y): {"q1": float(q.loc[y, 0.25]), "med": float(q.loc[y, 0.5]),
                          "q3": float(q.loc[y, 0.75])} for y in q.index}
    age_years = [y for y in years if y in age_stats]
    age_trend = {"x": [str(y) for y in age_years],
                 "med": [age_stats[y]["med"] for y in age_years],
                 "q1": [age_stats[y]["q1"] for y in age_years],
                 "band": [round(age_stats[y]["q3"] - age_stats[y]["q1"], 2) for y in age_years],
                 "q3": [age_stats[y]["q3"] for y in age_years]}
    t_age_trend = [{"name": str(y), "q1": f"{age_stats[y]['q1']:g}", "med": f"{age_stats[y]['med']:g}",
                    "q3": f"{age_stats[y]['q3']:g}"} for y in age_years]

    def age_dist(y):
        a = ages.loc[ages["year"] == y, "age"]
        tot = max(len(a), 1)
        return [round(float(((a >= lo) & (a <= hi)).sum()) / tot * 100, 1) for lo, hi, _ in AGE_BINS]

    hist_years = [y for y in [first_full, last_full] if y is not None and y in age_stats]
    hist_years = sorted(set(hist_years))
    age_hist = {"x": [b[2] for b in AGE_BINS],
                "series": [{"name": str(y), "data": age_dist(y)} for y in hist_years]}
    t_age_hist = [{"name": b[2], "cols": [f"{s['data'][i]:.1f}" for s in age_hist["series"]]}
                  for i, b in enumerate(AGE_BINS)]
    ref_year = last_full or y_last
    ref_ages = ages.loc[ages["year"] == ref_year, "age"]
    old_share = float((ref_ages >= OLD_AGE).mean()) if len(ref_ages) else 0.0
    med_age = age_stats.get(ref_year, {"med": float(ages["age"].median())})["med"]

    # ── Vehicle types ───────────────────────────────────────────────────
    type_year = tv.groupby(["year", "vtype"]).size().unstack(fill_value=0).reindex(index=years, fill_value=0)
    tv_names = [t for t in TYPE_ORDER if t in type_year.columns] + \
               sorted(t for t in type_year.columns if t not in TYPE_ORDER)
    type_year = type_year.reindex(columns=tv_names, fill_value=0)
    shares = type_year.div(type_year.sum(axis=1).replace(0, 1), axis=0) * 100
    types_chart = {"x": [str(y) for y in years],
                   "series": [{"name": t, "data": [round(float(v), 2) for v in shares[t]],
                               "counts": [int(v) for v in type_year[t]]} for t in tv_names]}
    tcount = df["vtype"].value_counts()
    t_types = []
    for t in tv_names:
        row = {"name": t, "count": _int(tcount.get(t, 0)),
               "share": f"{tcount.get(t, 0) / n * 100:.1f}"}
        row["first"] = f"{shares.loc[first_full, t]:.1f}" if first_full else ""
        row["last"] = f"{shares.loc[last_full, t]:.1f}" if last_full else ""
        t_types.append(row)

    # ── Makers and models ───────────────────────────────────────────────
    bvc = _ranked(df["brand"])
    b_names, b_vals = _top_other(df["brand"], TOP_BRANDS)
    t_brands = [{"name": a, "count": _int(b), "share": f"{b / n * 100:.1f}"} for a, b in zip(b_names, b_vals)]

    shift_rows, early_label, recent_label = [], "", ""
    if len(full_years) >= 2 * WINDOW_YEARS:
        early_y, recent_y = full_years[:WINDOW_YEARS], full_years[-WINDOW_YEARS:]
        early_label = f"{early_y[0]}-{early_y[-1]}"
        recent_label = f"{recent_y[0]}-{recent_y[-1]}"
        e = _ranked(tv[tv["year"].isin(early_y)]["brand"])
        r = _ranked(tv[tv["year"].isin(recent_y)]["brand"])
        e_tot, r_tot = max(int(e.sum()), 1), max(int(r.sum()), 1)
        picked = list(r.head(SHIFT_BRANDS).index)
        picked += [b for b in e.head(SHIFT_BRANDS).index if b not in picked]
        for b in picked:
            shift_rows.append({"name": b, "early": round(int(e.get(b, 0)) / e_tot * 100, 1),
                               "recent": round(int(r.get(b, 0)) / r_tot * 100, 1)})
        shift_rows.sort(key=lambda x: (-x["recent"], -x["early"], x["name"]))
    shift_chart = {"names": [r["name"] for r in shift_rows],
                   "early": [r["early"] for r in shift_rows],
                   "recent": [r["recent"] for r in shift_rows],
                   "early_label": early_label, "recent_label": recent_label}

    fill = (tv["model_key"] != "").groupby(tv["year"]).mean()
    filled = [int(y) for y, v in fill.sort_index().items() if v >= MODEL_FILL]
    model_from = filled[0] if filled else y_first
    model_rows = _model_rows(tv[tv["year"] >= model_from])
    n_model_rows = int(((tv["year"] >= model_from) & (tv["model_key"] != "")).sum())

    # ── Fuel / electrified ──────────────────────────────────────────────
    fvc = df["fuel"].value_counts()
    f_names = [f for f in FUEL_ORDER if fvc.get(f, 0)]
    t_fuel = [{"name": f, "count": _int(fvc[f]), "share": f"{fvc[f] / n * 100:.2f}"} for f in f_names]
    evdf = tv[tv["fuel"].isin(ELECTRIFIED)]
    ev_by_year = evdf.groupby(["year", "fuel"]).size().unstack(fill_value=0)
    ev_by_year = ev_by_year.reindex(columns=ELECTRIFIED, fill_value=0)
    ev_tot = ev_by_year.sum(axis=1)
    ev_start = [int(y) for y, v in ev_tot.sort_index().items() if v >= EV_MIN]
    ev_years = list(range(ev_start[0], y_last + 1)) if ev_start else []
    evp = ev_by_year.reindex(index=ev_years, fill_value=0)
    ev_chart = {"x": [str(y) + ("*" if y == y_last and year_partial else "") for y in ev_years],
                "series": [{"name": f, "data": [int(v) for v in evp[f]]} for f in ELECTRIFIED]}
    t_ev = [{"name": str(y) + (" (חלקית)" if y == y_last and year_partial else ""),
             "cols": [_int(evp.loc[y, f]) for f in ELECTRIFIED],
             "share": f"{evp.loc[y].sum() / max(int(totals[y]), 1) * 100:.2f}"} for y in ev_years]
    n_ev = int(df["fuel"].isin(ELECTRIFIED).sum())

    # ── Ownership ───────────────────────────────────────────────────────
    ovc = _ranked(df["owner"])
    owners = [o for o in OWNER_ORDER if o in ovc.index] + [o for o in ovc.index if o not in OWNER_ORDER]
    oy = tv.groupby(["year", "owner"]).size().unstack(fill_value=0).reindex(index=years, fill_value=0)
    oy = oy.reindex(columns=owners, fill_value=0)
    osh = oy.div(oy.sum(axis=1).replace(0, 1), axis=0) * 100
    non_private = [o for o in owners if o != "פרטי" and int(ovc.get(o, 0)) >= 100]
    owner_chart = {"x": [str(y) for y in years],
                   "series": [{"name": o, "data": [round(float(v), 2) for v in osh[o]]} for o in non_private]}
    t_owner = [{"name": o, "count": _int(ovc[o]), "share": f"{ovc[o] / n * 100:.1f}"} for o in owners]
    comp_first = float(osh.loc[first_full, "חברה"]) if first_full and "חברה" in osh.columns else None
    comp_last = float(osh.loc[last_full, "חברה"]) if last_full and "חברה" in osh.columns else None

    # ── Colours ─────────────────────────────────────────────────────────
    known = df.loc[df["color"] != UNKNOWN, "color"]
    c_names, c_vals = _top_other(known, TOP_COLORS)
    k_tot = max(len(known), 1)
    t_colors = [{"name": a, "count": _int(b), "share": f"{b / k_tot * 100:.1f}"} for a, b in zip(c_names, c_vals)]
    unknown_colors = n - len(known)

    # ── Insights ────────────────────────────────────────────────────────
    rules = [
        ("ytd", ytd_text),
        ("long", insight_long(full)),
        ("outlier", insight_outlier_year(full)),
        ("age", insight_age(age_stats, first_full, last_full, old_share)),
        ("types", insight_types(type_year, first_full, last_full)),
        ("brand", insight_brand(bvc, n)),
        ("shift", insight_shift(shift_rows, early_label, recent_label)),
        ("model", insight_model(model_rows, model_from)),
        ("ev", insight_ev(ev_by_year, totals, last_full)),
        ("season", insight_season(month_share)),
        ("day", insight_day(top_days, daily)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── KPIs ────────────────────────────────────────────────────────────
    if ytd_ch is None:
        ch_tone, ch_display = "brand", "לא זמין"
    elif abs(ytd_ch) < TREND_BAND:
        ch_tone, ch_display = "brand", ("+" if ytd_ch >= 0 else "−") + _pct(abs(ytd_ch))
    else:
        ch_tone, ch_display = "info", ("+" if ytd_ch > 0 else "−") + _pct(abs(ytd_ch))
    last_full_n = int(totals[last_full]) if last_full else int(totals.iloc[-1])
    anchor_he = _d_he(anchor)
    ytd_label_end = f"{anchor.day} ב{MONTHS_HE[anchor.month - 1]}"

    # ── Labels ──────────────────────────────────────────────────────────
    stray_note = (f" {_int(stray)} רשומות עם תאריך ביטול מאוחר מ-{anchor_he} אינן מוצגות בתרשים."
                  if stray else "")
    partial_note = (f" החודש האחרון ({_m_he(months[-1])}) חלקי: הנתונים מגיעים עד {anchor_he}."
                    if month_partial else "")
    peak_text = (f" החודש העמוס ביותר: {_m_he(peak_m.index[0])} ({_int(peak_m.iloc[0])} ביטולים)."
                 if len(peak_m) else "")
    season_text = ""
    if month_share is not None:
        ms = month_share.sort_index().sort_values(ascending=False, kind="stable")
        season_text = (f" בממוצע על פני {len(full_years)} שנים מלאות, {MONTHS_HE[int(ms.index[0]) - 1]} "
                       f"מרכז {ms.iloc[0] * 100:.1f}% מביטולי השנה ו{MONTHS_HE[int(ms.index[-1]) - 1]} "
                       f"{ms.iloc[-1] * 100:.1f}%.")
    summary = (f"איתור כלי רכב שבוטלו סופית וירדו מהכביש, לפי מספר רכב, יצרן ודגם: "
               f"{_int(n)} רשומות מאז {y_first}, ומהן {_int(last_full_n)} ב-{last_full or y_last}.")
    if len(summary) > 155:
        summary = f"איתור כלי רכב שבוטלו סופית וירדו מהכביש, לפי מספר רכב, יצרן ודגם: {_int(n)} רשומות."
    comp_text = ""
    if comp_first is not None and comp_last is not None:
        comp_text = (f" חלקם של כלי רכב בבעלות חברה עמד על {comp_first:.1f}% ב-{first_full} "
                     f"ועל {comp_last:.1f}% ב-{last_full}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "related_ids": [
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "aef33db6-37c4-4026-82ba-6c1237bd2cf0",
                "9b2ac550-d4bf-4da6-a1f2-bcfd57ed5e7f",
                "0f16b39a-6016-408d-805d-31f40d5a0990",
                "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
            ],
            "suggested_tags": ["כלי רכב", "ביטול רישיון רכב", "גריטת רכב", "רישוי רכב", "תחבורה"],
            "temporal_coverage": f"{y_first}/{y_last}",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "ytd": {"value": ytd_cur, "display": _int(ytd_cur), "tone": "brand"},
            "ytd_change": {"value": round(ytd_ch, 4) if ytd_ch is not None else None,
                           "display": ch_display, "tone": ch_tone},
            "med_age": {"value": med_age, "display": f"{med_age:g}",
                        "tone": "warn" if med_age >= 15 else "brand"},
        },
        "charts": {
            "yearly": yearly,
            "monthly": series,
            "heat": {"months": MONTHS_HE, "years": [str(y) for y in years], "cells": heat_cells,
                     "max": heat_max},
            "age_trend": age_trend,
            "age_hist": age_hist,
            "types": types_chart,
            "brands": {"names": b_names, "values": b_vals},
            "shift": shift_chart,
            "models": {"names": [r["name"] for r in model_rows], "values": [r["n"] for r in model_rows]},
            "ev": ev_chart,
            "owner": owner_chart,
            "colors": {"names": c_names, "values": c_vals},
            "days": days_chart,
        },
        "flags": {"shift": bool(shift_rows), "ev": bool(ev_years), "owner": bool(non_private),
                  "models": len(model_rows) >= 3, "age_hist": bool(hist_years)},
        "tables": {
            "yearly": t_yearly,
            "age_trend": t_age_trend,
            "age_hist_cols": [s["name"] for s in age_hist["series"]],
            "age_hist": t_age_hist,
            "types": t_types,
            "brands": t_brands,
            "shift": [{"name": r["name"], "early": f"{r['early']:.1f}", "recent": f"{r['recent']:.1f}"}
                      for r in shift_rows],
            "models": [{"name": r["name"], "count": _int(r["n"]),
                        "share": f"{r['n'] / max(n_model_rows, 1) * 100:.1f}"} for r in model_rows],
            "fuel": t_fuel,
            "ev_cols": ELECTRIFIED,
            "ev": t_ev,
            "owner": t_owner,
            "colors": t_colors,
            "days": t_days,
        },
        "insights": insights,
        "labels": {
            "lede": (f"המאגר מונה {_int(n)} כלי רכב שירדו מהכביש ורישיונם בוטל ביטול סופי "
                     f"(למשל גריטה או אובדן גמור), מ-{_d_he(first)} ועד {anchor_he}. "
                     f"לכל רכב רשומים תאריך הביטול, היצרן והדגם, סוג הרכב, שנת הייצור, סוג הדלק, "
                     f"הבעלות והצבע. ב-{last_full or y_last} בוטלו סופית {_int(last_full_n)} כלי רכב, "
                     f"ומתחילת {y_last} ועד {ytd_label_end} עוד {_int(ytd_cur)}."),
            "lookup_title": "בדיקה אם רכב בוטל סופית לפי מספר רכב ←",
            "lookup_sub": "חיפוש חי בכל רשומות המאגר: מספר רכב, שם יצרן, שם דגם, כינוי מסחרי ומספר שלדה.",
            "total_kpi": "כלי רכב בסטטוס ביטול סופי",
            "ytd_kpi": f"ביטולים ב-{y_last} (עד {ytd_label_end})",
            "ytd_change_kpi": f"שינוי לעומת התקופה המקבילה ב-{y_last - 1}",
            "age_kpi": f"גיל חציוני בעת הביטול ב-{ref_year} (שנים)",
            "yearly_note": (f"מספר כלי הרכב שבוטלו סופית בכל שנה, {y_first}-{y_last}."
                            + (f" שנת {y_last} חלקית (עד {ytd_label_end}) ומסומנת בצבע שונה." if year_partial else "")),
            "yearly_aria": (f"תרשים עמודות: ביטולים סופיים לפי שנה, {y_first}-{y_last}. "
                            f"ב-{last_full or y_last} בוטלו {_int(last_full_n)} כלי רכב."),
            "monthly_note": (f"ביטולים לפי {series['unit']}, עם ממוצע נע של שנה (הקו הכהה)."
                             f"{peak_text}{partial_note}{stray_note}"),
            "monthly_aria": f"תרשים קו: ביטולים סופיים לפי {series['unit']}, {y_first}-{y_last}.",
            "heat_note": ("כל תא הוא חודש אחד; ככל שהגוון כהה יותר, בוטלו יותר כלי רכב באותו חודש."
                          + season_text),
            "heat_aria": f"מפת חום: ביטולים סופיים לפי חודש ושנה, {y_first}-{y_last}.",
            "age_trend_note": (f"הגיל בעת הביטול = שנת הביטול פחות שנת הייצור. הקו הוא החציון, "
                               f"והרצועה נמתחת מהרבעון התחתון לעליון. ב-{ref_year} החציון "
                               f"{med_age:g} שנים."
                               + (f" לא כולל {_int(bad_age)} רשומות ששנת הייצור שלהן חסרה או לא סבירה."
                                  if bad_age else "")),
            "age_trend_aria": f"תרשים קו: גיל חציוני של כלי רכב בעת הביטול הסופי לפי שנה, {age_trend['x'][0] if age_years else ''}-{age_trend['x'][-1] if age_years else ''}.",
            "age_hist_note": (f"התפלגות הגיל בעת הביטול (באחוזים מביטולי השנה), "
                              + " מול ".join(str(y) for y in hist_years) + "."),
            "age_hist_aria": "תרשים עמודות: התפלגות גיל כלי הרכב בעת הביטול הסופי.",
            "types_note": (f"חלוקת הביטולים בכל שנה לפי משפחת סוג הרכב (באחוזים). "
                           f"משא ומסחרי כולל גם מרכב אחוד (טנדרים ומסחריות קלות)."),
            "types_aria": "תרשים שטח מוערם: תמהיל סוגי הרכב בביטולים לפי שנה.",
            "brands_note": "שם היצרן מאוחד מכל ארצות המפעל (למשל טויוטה יפן, טורקיה ואנגליה).",
            "brands_aria": f"תרשים עמודות: {TOP_BRANDS} היצרנים הנפוצים בביטולים, {b_names[0]} בראש.",
            "shift_note": (f"חלקו של כל יצרן מביטולי התקופה: {early_label} מול {recent_label}. "
                           f"מוצגים {SHIFT_BRANDS} היצרנים המובילים בכל אחת מהתקופות." if shift_rows else ""),
            "shift_aria": (f"תרשים עמודות: חלק היצרנים בביטולים, {early_label} מול {recent_label}."
                           if shift_rows else ""),
            "models_note": (f"הכינוי המסחרי של הדגם, מאוחד בין כתיבים שונים. כלי רכב שבוטלו מ-{model_from} "
                            f"ואילך ({_int(n_model_rows)} רשומות עם כינוי מסחרי); בשנים מוקדמות יותר השדה ריק ברוב הרשומות."),
            "models_aria": f"תרשים עמודות: {TOP_MODELS} הדגמים שבוטלו הכי הרבה מ-{model_from}.",
            "ev_note": (f"{_int(n_ev)} כלי רכב חשמליים והיברידיים בוטלו סופית בסך הכול. "
                        f"היברידי = חשמל/בנזין או חשמל/דיזל."
                        + (f" השנה המסומנת בכוכבית חלקית." if year_partial else "")),
            "ev_aria": "תרשים עמודות: ביטולים סופיים של כלי רכב חשמליים והיברידיים לפי שנה.",
            "fuel_caption": "כלי רכב שבוטלו לפי סוג דלק.",
            "owner_note": ("חלקם של סוגי הבעלות שאינם פרטית מביטולי כל שנה (באחוזים); השאר בבעלות פרטית."
                           + comp_text),
            "owner_aria": "תרשים קו: חלק הביטולים לפי סוג בעלות שאינו פרטי, לפי שנה.",
            "colors_note": (f"הצבעים כפי שנרשמו; גוונים מטאליים מופיעים בנפרד."
                            + (f" לא כולל {_int(unknown_colors)} רשומות שצבען לא ידוע." if unknown_colors else "")),
            "colors_aria": f"תרשים עמודות: {TOP_COLORS} הצבעים הנפוצים בביטולים, {c_names[0] if c_names else ''} בראש.",
            "days_note": (f"{TOP_DAYS} הימים שבהם בוטלו הכי הרבה כלי רכב. ביום חציוני ב-{last_full or y_last} "
                          f"בוטלו {_int(med_day_last)} כלי רכב."),
            "days_aria": (f"תרשים עמודות: {TOP_DAYS} הימים עם מספר הביטולים הגבוה ביותר. "
                          f"בראש {days_chart['names'][0] if top_days else ''}."),
        },
    }
