"""Tipat Halav (mother-and-child health stations) quality indicators, Ministry
of Health national program.

Every resource is one indicator (vaccinations, development checks, iron,
breastfeeding, postpartum depression and violence screening, ...). Each row is
a cell of (indicator, year, month, provider, station, socio-economic cluster,
sector, age band, city) with `number_of_cases` (eligible children or mothers,
the denominator) and `number_of_cases_approved` (those for whom the action was
documented, the numerator; empty means none). A rate is always
sum(approved) / sum(cases).

The indicator's identity is its resource name (`_resource_name`): the recipe
fetches only the columns the page reads (5M+ rows), so the long per-row
description columns are not exported.

Cross-sectional views (providers, socio-economic clusters, sector, cities,
age bands) use each indicator's own reference year (its latest full year),
since indicators are published for different years. Trend views use every
year.
"""

import pandas as pd
from govlib import fmt
from govlib.frame import clean

MIN_N = 100           # min eligible cases for a group / provider / city rate
TREND_PP = 2.0        # change (percentage points) that counts as a rise/fall
SES_GAP_PP = 5.0      # low-vs-high cluster gap worth an insight
OWNER_SPREAD_PP = 5.0
CITY_GAP_PP = 3.0
AGE_GAP_PP = 2.0
TOP_CITIES = 15
UNKNOWN = "לא ידוע"
OTHER = "אחר"
SES_LOW = (1, 2)
SES_HIGH = (8, 9, 10)
SECTOR_ORDER = {"יהודי": 0, "ערבי": 1, "מעורב": 2}
# Age bands that are not a real split (the whole population of the measure).
NO_AGE = {"0-120", UNKNOWN, ""}

# Definitions of known indicators (from the dataset's measure_long_description,
# which the recipe doesn't fetch); an unknown indicator shows its name only.
DEFINITIONS = {
    "מתן חיסון MMRV או MMR עד 13 חודשים": "פעוטות שקיבלו מנה אחת של חיסון MMR או MMRV (חצבת, חזרת, אדמת) עד גיל 13 חודשים",
    "איתור דיכאון לאחר לידה": "נשים לאחר לידה שעברו אומדן לאיתור דיכאון",
    "מדידת היקף ראש עד 8 חודשים": "תינוקות שנמדד להם היקף ראש עד גיל 8 חודשים",
    "מתן 4 מנות של חיסון מחומש עד 18 חודשים": "פעוטות שמלאו להם 18 חודשים וקיבלו ארבע מנות של החיסון המחומש",
    "בדיקת התפתחות שפה ותקשורת בגיל 2-3": "ילדים שעברו בדיקת התפתחות בדגש על שפה ותקשורת בגיל שנתיים עד שלוש",
    "תשאול לאלימות": "נשים שנשאלו בתחנה על אלימות כלפיהן",
    "ברזל": "תינוקות שתועד להם מתן תוסף ברזל עד גיל 13 חודשים",
    "ביקור ראשון": "תינוקות שהגיעו לביקור ראשון בטיפת חלב בשבועיים הראשונים לאחר הלידה",
    "מתן חיסון נגד שעלת": "תינוקות ופעוטות שקיבלו חיסון נגד שעלת",
    "מתן הדרכה לשינה בטוחה": "תינוקות שמלאו להם חודשיים והוריהם קיבלו הדרכה למניעת מוות בעריסה (שינה בטוחה)",
    "ביצוע בדיקות התפתחויות עד גיל 6": "ילדים שמלאו להם 6 שנים ובוצעה להם בדיקת התפתחות",
    "הנקה בלעדית": "תינוקות שדווחה לגביהם הנקה בלעדית סביב גיל 4 חודשים",
    "שימור הנקה - בלעדית": "שימור הנקה בלעדית בקרב נשים שהחלו בהנקה בלעדית",
}
OWNER_DISPLAY = {"עיריית ת'א": "עיריית תל אביב", "עיריית ת\"א": "עיריית תל אביב"}


def _p(x):
    return fmt.pct(x)


def _pp(x):
    return round(x * 100, 1) + 0.0


def _gap_txt(pp):
    return f"{abs(pp):.1f}"


def _owner(provider):
    o = provider.split(" - ")[0].strip()
    for pre in ("שרותי בריאות ", "שירותי בריאות "):
        o = o.removeprefix(pre)
    return OWNER_DISPLAY.get(o, o) or UNKNOWN


def _provider_label(provider):
    parts = provider.split(" - ", 1)
    owner = _owner(provider)
    if len(parts) == 1:
        return owner
    return f"{owner}, {parts[1].strip()}"


def _ses(v):
    try:
        k = int(float(v))
    except ValueError:
        return None
    return k if 1 <= k <= 10 else None


def _age_label(s):
    return s.replace(" - ", "-").replace(" +", "+")


def _age_key(label):
    if label.startswith("עד"):
        return -1.0
    t = label.replace("+", "").split("-")[0].strip()
    try:
        return float(t)
    except ValueError:
        return 999.0


def _map_clean(series):
    """`clean` over a large str Series via its unique values (fast)."""
    u = series.unique()
    return series.map({v: clean(v) for v in u})


def _agg(df, keys):
    g = df.groupby(keys, sort=True, observed=True).agg(n=("n", "sum"), a=("a", "sum"))
    g["r"] = g["a"] / g["n"]
    return g


def _prepare(frame):
    df = pd.DataFrame({
        "name": _map_clean(frame["_resource_name"]),
        "year": pd.to_numeric(frame["measurement_year"], errors="coerce"),
        "mon": pd.to_numeric(frame["month"], errors="coerce"),
        "n": pd.to_numeric(frame["number_of_cases"].str.replace(",", ""), errors="coerce"),
        "a": pd.to_numeric(frame["number_of_cases_approved"].str.replace(",", ""),
                           errors="coerce").fillna(0.0),
        "tgt": pd.to_numeric(frame["target"], errors="coerce").fillna(0.0),
        "provider": _map_clean(frame["provider"]),
        "ses_raw": _map_clean(frame["Socio Economic Group"]),
        "sector": _map_clean(frame["sector"]),
        "age": _map_clean(frame["age_range"]),
        "city": _map_clean(frame["station_city"]),
    })
    df = df[df["n"].notna() & (df["n"] > 0) & df["year"].notna() & (df["name"] != "")]
    df = df.copy()
    df["year"] = df["year"].astype(int)
    df["a"] = df[["a", "n"]].min(axis=1)
    sesmap = {v: _ses(v) for v in df["ses_raw"].unique()}
    df["ses"] = df["ses_raw"].map(sesmap)
    df["age"] = df["age"].map({v: _age_label(v) for v in df["age"].unique()})
    df.loc[df["sector"] == "", "sector"] = UNKNOWN
    df.loc[df["provider"] == "", "provider"] = UNKNOWN
    for c in ("name", "provider", "sector", "age", "city"):
        df[c] = df[c].astype("category")
    return df


# ── insight rules ────────────────────────────────────────────────────────

def insight_range(measures):
    if len(measures) < 2:
        return None
    hi, lo = measures[0], measures[-1]
    if hi["rate"] - lo["rate"] < 0.05:
        return None
    return (f"המדד עם שיעור הביצוע הגבוה ביותר הוא {hi['name']}: {_p(hi['rate'])} "
            f"({hi['year_txt']}). הנמוך ביותר הוא {lo['name']}: {_p(lo['rate'])} ({lo['year_txt']}).")


def insight_target(measures):
    with_t = [m for m in measures if m["target"] > 0]
    if not with_t:
        return None
    met = [m for m in with_t if m["rate"] >= m["target"]]
    below = [m for m in with_t if m["rate"] < m["target"]]
    if not below:
        return (f"כל {len(with_t)} המדדים שנקבע להם יעד בשנת המדידה האחרונה שלהם עומדים בו.")
    gaps = sorted(below, key=lambda m: (m["rate"] - m["target"], m["name"]))
    w = gaps[0]
    return (f"{len(met)} מתוך {len(with_t)} המדדים שנקבע להם יעד עומדים בו. הרחוק ביותר מהיעד: "
            f"{w['name']}, {_p(w['rate'])} לעומת יעד של {_p(w['target'])} ({w['year_txt']}).")


def insight_trend(measures):
    best = None
    for m in measures:
        pts = [b for b in m["by_year"] if b["full"]]
        if len(pts) < 2:
            continue
        d = (pts[-1]["rate"] - pts[0]["rate"]) * 100
        key = (-abs(d), m["name"])
        if best is None or key < best[0]:
            best = (key, m, pts[0], pts[-1], d)
    if best is None:
        return None
    _, m, p0, p1, d = best
    if abs(d) < TREND_PP:
        return (f"שיעורי הביצוע יציבים לאורך השנים: באף מדד השינוי בין השנה המלאה הראשונה לאחרונה "
                f"אינו עולה על {TREND_PP:.0f} נקודות אחוז.")
    word = "עלה" if d > 0 else "ירד"
    return (f"השינוי הגדול ביותר לאורך זמן: שיעור {m['name']} {word} מ-{_p(p0['rate'])} ב-{p0['year']} "
            f"ל-{_p(p1['rate'])} ב-{p1['year']} ({_gap_txt(d)} נקודות אחוז).")


def insight_ses(ses_rows):
    gaps = [r for r in ses_rows if r["gap"] is not None]
    if not gaps:
        return None
    lower = [r for r in gaps if r["gap"] >= SES_GAP_PP]
    w = min(gaps, key=lambda r: (-r["gap"], r["name"]))
    if w["gap"] < SES_GAP_PP:
        return None
    return (f"פער חברתי-כלכלי: ב-{len(lower)} מתוך {len(gaps)} המדדים, השיעור בתחנות באשכולות 1-2 "
            f"נמוך ביותר מ-{SES_GAP_PP:.0f} נקודות אחוז מזה שבאשכולות 8-10. הפער הגדול ביותר ב{w['name']}: "
            f"{_p(w['low'])} לעומת {_p(w['high'])}.")


def insight_sector(sector_rows):
    pairs = [r for r in sector_rows if r["j"] is not None and r["ar"] is not None]
    if len(pairs) < 2:
        return None
    ar_hi = [r for r in pairs if r["ar"] > r["j"]]
    j_hi = [r for r in pairs if r["j"] > r["ar"]]
    # Each side is judged by its own share, so ties never count for either.
    if len(ar_hi) / len(pairs) > 0.65:
        w = min(ar_hi, key=lambda r: (r["j"] - r["ar"], r["name"]))
        return (f"בתחנות במגזר הערבי השיעור גבוה מזה שבמגזר היהודי ב-{len(ar_hi)} מתוך {len(pairs)} "
                f"המדדים. הפער הגדול ביותר ב{w['name']}: {_p(w['ar'])} לעומת {_p(w['j'])}.")
    if len(j_hi) / len(pairs) <= 0.65:
        return None
    w = min(j_hi, key=lambda r: (r["ar"] - r["j"], r["name"]))
    return (f"בתחנות במגזר היהודי השיעור גבוה מזה שבמגזר הערבי ב-{len(j_hi)} מתוך {len(pairs)} "
            f"המדדים. הפער הגדול ביותר ב{w['name']}: {_p(w['j'])} לעומת {_p(w['ar'])}.")


def insight_owner(owner_chart):
    best = None
    for j, name in enumerate(owner_chart["measures"]):
        vals = [(owner_chart["rates"][i][j], o) for i, o in enumerate(owner_chart["owners"])
                if owner_chart["rates"][i][j] is not None]
        if len(vals) < 3:
            continue
        hi = min(vals, key=lambda t: (-t[0], t[1]))
        lo = min(vals, key=lambda t: (t[0], t[1]))
        spread = hi[0] - lo[0]
        key = (-spread, name)
        if best is None or key < best[0]:
            best = (key, name, hi, lo, spread)
    if best is None or best[4] < OWNER_SPREAD_PP:
        return None
    _, name, hi, lo, spread = best
    return (f"הפער הגדול ביותר בין גופים מפעילים הוא ב{name}: {hi[1]} עם {fmt.pct_of(hi[0])} "
            f"לעומת {lo[1]} עם {fmt.pct_of(lo[0])}.")


def insight_city(city_rows):
    rows = [r for r in city_rows if r["k"] >= 3]
    if len(rows) < 3:
        return None
    lo = min(rows, key=lambda r: (r["gap"], r["city"]))
    hi = min(rows, key=lambda r: (-r["gap"], r["city"]))
    if lo["gap"] > -CITY_GAP_PP:
        return None
    return (f"מבין {len(city_rows)} הערים עם מספר המקרים הגדול ביותר, ב{lo['city']} השיעור נמוך "
            f"בממוצע ב-{_gap_txt(lo['gap'])} נקודות אחוז מהשיעור הארצי ({lo['below']} מתוך {lo['k']} מדדים "
            f"מתחת לממוצע), ואילו ב{hi['city']} הוא "
            f"{'גבוה' if hi['gap'] > 0 else 'נמוך'} ב-{_gap_txt(hi['gap'])} נקודות אחוז.")


def insight_age(age_series, bands):
    best = None
    for s in age_series:
        vals = [(v, b) for v, b in zip(s["data"], bands) if v is not None]
        if len(vals) < 3:
            continue
        young = vals[0]
        top = min(vals, key=lambda t: (-t[0], t[1]))
        gap = top[0] - young[0]
        key = (-gap, s["name"])
        if best is None or key < best[0]:
            best = (key, s["name"], young, top, gap)
    if best is None or best[4] < AGE_GAP_PP or best[2][1] == best[3][1]:
        return None
    _, name, young, top, gap = best
    return (f"גיל האם: ב{name} השיעור בקבוצת הגיל {young[1]} הוא {fmt.pct_of(young[0])}, "
            f"לעומת {fmt.pct_of(top[0])} בקבוצת הגיל {top[1]}.")


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])

    # ── indicators and their reference years ─────────────────────────────
    by_my = _agg(df, ["name", "year"])
    months = df.groupby(["name", "year"], sort=True, observed=True)["mon"].nunique()
    tg = df.groupby(["name", "year"], sort=True, observed=True)["tgt"].max()
    measures = []
    for name in sorted(by_my.index.get_level_values(0).unique().tolist()):
        sub = by_my.loc[name]
        # An indicator published once a year (no month split in any year) has
        # no partial years: every year it appears in is complete.
        annual = max(int(months.loc[(name, y)]) for y in sub.index) <= 1
        by_year = []
        for y, row in sub.iterrows():
            mcount = int(months.loc[(name, y)])
            by_year.append({"year": int(y), "rate": float(row["r"]), "n": float(row["n"]),
                            "months": mcount, "full": annual or mcount >= 12,
                            "target": float(tg.loc[(name, y)])})
        full = [b for b in by_year if b["full"]]
        ref = full[-1] if (not by_year[-1]["full"] and full) else by_year[-1]
        prev = [b for b in by_year if b["year"] < ref["year"]]
        year_txt = (str(ref["year"]) if ref["full"]
                    else f"{ref['year']}, חלקית: {ref['months']} חודשים")
        measures.append({
            "name": name, "rate": ref["rate"], "n": ref["n"], "ly": ref["year"],
            "target": ref["target"], "year_txt": year_txt, "by_year": by_year,
            "prev": prev[-1] if prev else None, "partial": not ref["full"],
            "years": [b["year"] for b in by_year],
        })
    measures.sort(key=lambda m: (-m["rate"], m["name"]))
    order = [m["name"] for m in measures]
    ref_year = {m["name"]: m["ly"] for m in measures}
    nat = {m["name"]: m["rate"] for m in measures}

    ry = df["name"].map(ref_year).astype(int)
    latest = df[df["year"] == ry]

    # ── KPIs ──────────────────────────────────────────────────────────────
    y0, y1 = int(df["year"].min()), int(df["year"].max())
    ref_n = float(sum(m["n"] for m in measures))
    with_t = [m for m in measures if m["target"] > 0]
    met = [m for m in with_t if m["rate"] >= m["target"]]
    cities_all = sorted(c for c in latest["city"].unique().tolist() if c)
    providers_all = sorted(p for p in latest["provider"].unique().tolist() if p != UNKNOWN)
    kpis = {
        "measures": {"value": len(measures), "display": f"{len(measures):,}", "tone": "brand"},
        "cases": {"value": int(ref_n), "display": fmt.int_he(ref_n), "tone": "brand"},
        "years": {"value": y1 - y0 + 1, "display": f"{y0}–{y1}" if y1 > y0 else f"{y0}",
                  "tone": "brand"},
        "cities": {"value": len(cities_all), "display": f"{len(cities_all):,}", "tone": "brand"},
        "providers": {"value": len(providers_all), "display": f"{len(providers_all):,}",
                      "tone": "brand"},
    }
    if with_t:
        tone = "ok" if len(met) == len(with_t) else ("warn" if met else "danger")
        kpis["met"] = {"value": len(met), "display": f"{len(met)}/{len(with_t)}", "tone": tone}

    # ── scorecard ─────────────────────────────────────────────────────────
    score = []
    score_table = []
    for m in measures:
        status = "none"
        if m["target"] > 0:
            status = "ok" if m["rate"] >= m["target"] else "below"
        chg = None
        if m["prev"] is not None:
            chg = round((m["rate"] - m["prev"]["rate"]) * 100, 1) + 0.0
        score.append({"name": m["name"], "rate": _pp(m["rate"]),
                      "target": _pp(m["target"]) if m["target"] > 0 else None,
                      "status": status, "year": m["year_txt"], "n": int(m["n"]),
                      "chg": chg, "prev_year": m["prev"]["year"] if m["prev"] else None})
        score_table.append({
            "name": m["name"], "def": DEFINITIONS.get(m["name"], ""), "year": m["year_txt"],
            "n": fmt.int_he(m["n"]), "rate": _p(m["rate"]),
            "target": _p(m["target"]) if m["target"] > 0 else "ללא יעד",
            "status": {"ok": "עומד ביעד", "below": "מתחת ליעד", "none": "-"}[status],
            "chg": ("" if chg is None else
                    (("+" if chg > 0 else ("−" if chg < 0 else "")) + f"{abs(chg):.1f}")),
        })

    # ── trend (every year) ────────────────────────────────────────────────
    all_years = sorted(df["year"].unique().tolist())
    trend_series = []
    trend_rows = []
    for m in measures:
        by = {b["year"]: b for b in m["by_year"]}
        trend_series.append({"name": m["name"],
                             "data": [(_pp(by[y]["rate"]) if y in by else None) for y in all_years]})
        trend_rows.append({"name": m["name"], "cells": [
            ("" if y not in by else
             _p(by[y]["rate"]) + ("" if by[y]["full"] else "*")) for y in all_years]})
    any_partial = any(not b["full"] for m in measures for b in m["by_year"])

    # ── operating bodies (owner) × indicator, reference years ─────────────
    lat_own = latest.assign(owner=latest["provider"].map(
        {p: _owner(p) for p in latest["provider"].unique()}).astype(str))
    og = _agg(lat_own, ["owner", "name"])
    owner_tot = lat_own.groupby("owner", sort=True)["n"].sum()
    owners = sorted(owner_tot.index.tolist(), key=lambda o: (-owner_tot[o], o))
    owners = [o for o in owners if o != UNKNOWN]
    owner_rates = []
    for o in owners:
        row = []
        for name in order:
            if (o, name) in og.index and og.loc[(o, name), "n"] >= MIN_N:
                row.append(_pp(og.loc[(o, name), "r"]))
            else:
                row.append(None)
        owner_rates.append(row)
    owner_chart = {"owners": owners, "measures": order, "rates": owner_rates}
    owner_table = [[o] + [("" if v is None else fmt.pct_of(v)) for v in owner_rates[i]]
                   for i, o in enumerate(owners)]

    # ── providers (districts) per indicator, for the selector ─────────────
    pg = _agg(latest, ["name", "provider"])
    prov = {}
    for name in order:
        if name not in pg.index.get_level_values(0):
            prov[name] = {"labels": [], "rates": [], "n": []}
            continue
        s = pg.loc[name]
        s = s[(s["n"] >= MIN_N) & (s.index != UNKNOWN)]
        items = sorted(((_provider_label(p), float(r["r"]), int(r["n"])) for p, r in s.iterrows()),
                       key=lambda t: (-t[1], t[0]))
        prov[name] = {"labels": [t[0] for t in items], "rates": [_pp(t[1]) for t in items],
                      "n": [t[2] for t in items]}
    prov_counts = [len(prov[n]["labels"]) for n in order]

    # ── socio-economic cluster × indicator ────────────────────────────────
    ses_df = latest[latest["ses"].notna()]
    sg = _agg(ses_df.assign(ses=ses_df["ses"].astype(int)), ["name", "ses"])
    ses_levels = sorted({int(k) for k in ses_df["ses"].unique().tolist()})
    ses_cells = []
    ses_rows = []
    ses_table = []
    for j, name in enumerate(order):
        trow = [name]
        for i, k in enumerate(ses_levels):
            if (name, k) in sg.index and sg.loc[(name, k), "n"] >= MIN_N:
                v = _pp(sg.loc[(name, k), "r"])
                ses_cells.append([i, j, v])
                trow.append(fmt.pct_of(v))
            else:
                trow.append("")
        ses_table.append(trow)
        sub = ses_df[ses_df["name"] == name]
        lo = sub[sub["ses"].isin(SES_LOW)]
        hi = sub[sub["ses"].isin(SES_HIGH)]
        if lo["n"].sum() >= MIN_N and hi["n"].sum() >= MIN_N:
            lr = lo["a"].sum() / lo["n"].sum()
            hr = hi["a"].sum() / hi["n"].sum()
            ses_rows.append({"name": name, "low": lr, "high": hr, "gap": (hr - lr) * 100})
    ses_unknown = float(latest.loc[latest["ses"].isna(), "n"].sum())
    ses_unknown_share = ses_unknown / ref_n if ref_n else 0.0
    ses_vals = [c[2] for c in ses_cells]

    # ── sector × indicator ────────────────────────────────────────────────
    secg = _agg(latest, ["name", "sector"])
    sectors = sorted([s for s in latest["sector"].unique().tolist() if s != UNKNOWN],
                     key=lambda s: (SECTOR_ORDER.get(s, 99), s))
    sector_series = []
    for s in sectors:
        data = []
        for name in order:
            if (name, s) in secg.index and secg.loc[(name, s), "n"] >= MIN_N:
                data.append(_pp(secg.loc[(name, s), "r"]))
            else:
                data.append(None)
        sector_series.append({"name": s, "data": data})
    sector_rows = []
    for j, name in enumerate(order):
        vals = {s["name"]: s["data"][j] for s in sector_series}
        sector_rows.append({"name": name,
                            "j": None if vals.get("יהודי") is None else vals["יהודי"] / 100,
                            "ar": None if vals.get("ערבי") is None else vals["ערבי"] / 100})
    sector_table = [[name] + [("" if s["data"][j] is None else fmt.pct_of(s["data"][j]))
                              for s in sector_series] for j, name in enumerate(order)]

    # ── cities: the largest by eligible cases; gap vs national per indicator
    lat_c = latest[latest["city"] != ""]
    city_tot = lat_c.groupby("city", sort=True, observed=True)["n"].sum()
    city_tot = city_tot[city_tot > 0]
    top_cities = sorted(city_tot.index.tolist(), key=lambda c: (-city_tot[c], c))[:TOP_CITIES]
    cg = _agg(lat_c[lat_c["city"].isin(top_cities)], ["city", "name"])
    city_rows = []
    city_matrix = []
    for c in top_cities:
        gaps = []
        row = []
        for name in order:
            if (c, name) in cg.index and cg.loc[(c, name), "n"] >= MIN_N:
                g = (cg.loc[(c, name), "r"] - nat[name]) * 100
                gaps.append(g)
                row.append(round(g, 1) + 0.0)
            else:
                row.append(None)
        city_matrix.append(row)
        if gaps:
            city_rows.append({"city": c, "gap": sum(gaps) / len(gaps), "k": len(gaps),
                              "below": sum(1 for g in gaps if g < 0),
                              "n": float(city_tot[c])})
    city_rows_sorted = sorted(city_rows, key=lambda r: (r["gap"], r["city"]))
    city_chart = {"cities": [r["city"] for r in city_rows_sorted],
                  "gap": [round(r["gap"], 1) + 0.0 for r in city_rows_sorted],
                  "k": [r["k"] for r in city_rows_sorted],
                  "below": [r["below"] for r in city_rows_sorted]}
    city_table = [[r["city"], fmt.int_he(r["n"]),
                   ("+" if r["gap"] > 0 else ("−" if r["gap"] < 0 else "")) + f"{abs(r['gap']):.1f}",
                   f"{r['below']}/{r['k']}"] for r in city_rows_sorted]
    city_heat = []
    for i, c in enumerate(top_cities):
        for j in range(len(order)):
            v = city_matrix[i][j]
            if v is not None:
                city_heat.append([j, i, v])
    city_heat_abs = max([abs(c[2]) for c in city_heat] or [1.0])

    # ── age bands (mothers' measures) ─────────────────────────────────────
    ag = _agg(latest[~latest["age"].isin(NO_AGE)], ["name", "age"])
    bands = sorted({a for (_, a) in ag.index.tolist()}, key=lambda a: (_age_key(a), a))
    age_series = []
    for name in order:
        if name not in ag.index.get_level_values(0):
            continue
        s = ag.loc[name]
        s = s[s["n"] >= MIN_N]
        if len(s) < 3:
            continue
        age_series.append({"name": name,
                           "data": [(_pp(s.loc[b, "r"]) if b in s.index else None) for b in bands]})
    used = [i for i, b in enumerate(bands) if any(s["data"][i] is not None for s in age_series)]
    bands = [bands[i] for i in used]
    for s in age_series:
        s["data"] = [s["data"][i] for i in used]
    age_table = [[s["name"]] + [("" if v is None else fmt.pct_of(v)) for v in s["data"]]
                 for s in age_series]

    # ── insights ──────────────────────────────────────────────────────────
    rules = [
        ("range", insight_range(measures)),
        ("target", insight_target(measures)),
        ("trend", insight_trend(measures)),
        ("ses", insight_ses(ses_rows)),
        ("sector", insight_sector(sector_rows)),
        ("owner", insight_owner(owner_chart)),
        ("city", insight_city(city_rows)),
        ("age", insight_age(age_series, bands)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── labels ────────────────────────────────────────────────────────────
    hi, lo = measures[0], measures[-1]
    latest_year = max(m["ly"] for m in measures)
    labels = {
        "cases_kpi": f"מקרים שנבדקו בשנת המדידה האחרונה של כל מדד (עד {latest_year})",
        "intro_measures": fmt.join_he(order),
        "score_lede": (f"שיעור הביצוע בשנת המדידה האחרונה של כל מדד, מהגבוה לנמוך. "
                       f"בראש: {hi['name']} ({_p(hi['rate'])}); בתחתית: {lo['name']} ({_p(lo['rate'])})."
                       + (f" {len(met)} מתוך {len(with_t)} המדדים שנקבע להם יעד עומדים בו."
                          if with_t else "")),
        "score_aria": (f"תרשים עמודות אופקי: שיעור הביצוע ב-{len(measures)} מדדי טיפות חלב. "
                       f"הגבוה {hi['name']} עם {_p(hi['rate'])}, הנמוך {lo['name']} עם {_p(lo['rate'])}."),
        "trend_lede": (f"שיעור הביצוע של כל מדד בכל שנה שבה פורסם, {y0} עד {y1}. "
                       "חלק מהמדדים פורסמו רק בחלק מהשנים, ולכן הקווים באורכים שונים."),
        "trend_aria": f"גרף קווים: שיעור הביצוע לפי שנה בכל מדד, {y0} עד {y1}.",
        "owner_lede": ("שיעור הביצוע לפי הגוף המפעיל את התחנות: משרד הבריאות, קופות החולים והעיריות "
                       f"(שנת המדידה האחרונה של כל מדד; תאים עם פחות מ-{MIN_N} מקרים הושמטו)."),
        "owner_aria": (f"מפת חום: שיעור הביצוע לפי גוף מפעיל ({len(owners)} גופים) ומדד "
                       f"({len(order)} מדדים)."),
        "prov_lede": ("בחרו מדד כדי להשוות בין מחוזות משרד הבריאות, מחוזות קופות החולים והעיריות. "
                      f"הקו המקווקו הוא השיעור הארצי. מוצגים מחוזות עם {MIN_N} מקרים לפחות."),
        "prov_aria": (f"תרשים עמודות אופקי: שיעור הביצוע לפי מחוז או ספק שירות במדד שנבחר "
                      f"(עד {max(prov_counts or [0])} ספקים)."),
        "ses_lede": ("שיעור הביצוע לפי האשכול החברתי-כלכלי של התחנה, מ-1 (הנמוך) עד 10 (הגבוה). "
                     f"מקרים ללא אשכול ידוע ({_p(ses_unknown_share)} מהמקרים) אינם בתרשים; "
                     f"תאים עם פחות מ-{MIN_N} מקרים הושמטו."),
        "ses_aria": (f"מפת חום: שיעור הביצוע לפי אשכול חברתי-כלכלי ({len(ses_levels)} אשכולות) "
                     f"ומדד ({len(order)} מדדים)."),
        "sector_lede": ("שיעור הביצוע בכל מדד לפי מגזר התחנה. מקרים שהמגזר שלהם לא ידוע אינם בתרשים."),
        "sector_aria": (f"תרשים עמודות מקובצות: שיעור הביצוע לפי מגזר ({fmt.join_he(sectors)}) "
                        f"ב-{len(order)} מדדים."),
        "city_lede": (f"{len(top_cities)} הערים עם מספר המקרים הגדול ביותר. לכל עיר: הפער הממוצע, "
                      "בנקודות אחוז, בין שיעור הביצוע בה לשיעור הארצי של כל מדד "
                      f"(מדדים עם {MIN_N} מקרים לפחות בעיר). שלילי פירושו מתחת לממוצע הארצי."),
        "city_aria": (f"תרשים עמודות אופקי: הפער הממוצע מהשיעור הארצי ב-{len(city_rows)} הערים הגדולות."
                      + (f" הנמוכה {city_rows_sorted[0]['city']}." if city_rows_sorted else "")),
        "cityheat_lede": "אותו פער, לכל עיר ולכל מדד בנפרד: כחול מעל השיעור הארצי, אדום מתחתיו.",
        "cityheat_aria": (f"מפת חום: הפער מהשיעור הארצי לפי עיר ({len(top_cities)} ערים) "
                          f"ומדד ({len(order)} מדדים)."),
        "age_lede": ("במדדים שנמדדים אצל האם (כמו תשאול לאלימות ושימור הנקה) הנתונים מפולחים לפי קבוצת "
                     f"גיל. מוצגים מדדים עם שלוש קבוצות גיל לפחות ו-{MIN_N} מקרים לפחות בכל קבוצה."),
        "age_aria": (f"גרף קווים: שיעור הביצוע לפי קבוצת גיל ב-{len(age_series)} מדדים."),
        "partial_note": "* שנה חלקית (פחות משנים עשר חודשי מדידה)." if any_partial else "",
        "default_measure": order[0],
        "min_n": MIN_N,
    }

    # ── agent_data ────────────────────────────────────────────────────────
    met_txt = (f" {len(met)} מתוך {len(with_t)} המדדים שנקבע להם יעד עומדים בו." if with_t else "")
    summary = (f"{len(measures)} מדדי איכות בטיפות חלב, {y0} עד {y1}: חיסונים, בדיקות התפתחות, "
               f"ברזל, הנקה, ואיתור דיכאון ואלימות אצל אמהות. השיעור הגבוה ביותר ב{hi['name']} "
               f"({_p(hi['rate'])}), הנמוך ביותר ב{lo['name']} ({_p(lo['rate'])}).{met_txt}")
    desc = (f"מדדי איכות בטיפות חלב לפי מחוז, קופה, עיר ומגזר: {len(measures)} מדדים, {y0} עד {y1}. "
            f"שיעור החיסונים, בדיקות ההתפתחות וההנקה מול היעדים.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "temporal_coverage": f"{y0}/{y1}",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "מדדי איכות בטיפות חלב: חיסונים, התפתחות והנקה",
            "description": desc,
            "name": "מדדי איכות בטיפות חלב",
            "alternate_names": [
                "התכנית הלאומית למדדי איכות של משרד הבריאות - טיפות חלב",
                "מדדי איכות טיפת חלב",
                "תחנות לבריאות המשפחה: מדדי איכות",
            ],
        },
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "score": score,
            "trend": {"years": [str(y) for y in all_years], "series": trend_series},
            "owner": owner_chart,
            "prov": {"measures": order, "data": prov,
                     "national": {n: _pp(nat[n]) for n in order}},
            "ses": {"levels": [str(k) for k in ses_levels], "measures": order,
                    "cells": ses_cells,
                    "min": min(ses_vals) if ses_vals else 0.0,
                    "max": max(ses_vals) if ses_vals else 100.0},
            "sector": {"measures": order, "series": sector_series},
            "city": city_chart,
            "cityheat": {"cities": top_cities, "measures": order, "cells": city_heat,
                         "abs": round(city_heat_abs, 1) + 0.0},
            "age": {"bands": bands, "series": age_series},
        },
        "tables": {
            "score": score_table,
            "trend": {"years": [str(y) for y in all_years], "rows": trend_rows},
            "owner": {"cols": ["גוף מפעיל"] + order, "rows": owner_table},
            "ses": {"cols": ["מדד"] + [f"אשכול {k}" for k in ses_levels], "rows": ses_table},
            "sector": {"cols": ["מדד"] + sectors, "rows": sector_table},
            "city": city_table,
            "age": {"cols": ["מדד"] + bands, "rows": age_table},
        },
        "flags": {"has_met": bool(with_t), "age": len(age_series) > 0,
                  "sector": len(sectors) >= 2, "city": len(city_rows) >= 3,
                  "ses": len(ses_cells) > 0},
        "insights": insights,
        "labels": labels,
    }
