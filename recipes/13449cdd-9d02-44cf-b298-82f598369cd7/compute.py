"""מאגר החלטות בתי הדין למשמורת — decisions of the custody-review tribunals
(judicial review of the detention of foreign nationals held under the Entry
into Israel Law / the Prevention of Infiltration Law).

One row per decision: holder number, decision date, country of origin, the
tribunal member who decided, and a link to the decision document.

SENSITIVE: the people under review are in custody. The holder number is used
ONLY to aggregate (decisions per person, gaps between successive reviews of
the same person) — it never appears on the page, nor does any per-person
figure (the per-person distribution is binned with an open top bucket).
The document links are skipped (the documents name the person). Tribunal
members act in a public capacity and are named.

"Now" is the latest decision date in the data (the upstream export lags the
CKAN update date), never the wall clock. The year of that date is partial
unless it reaches late December, so year-over-year rules compare the last
two full years.
"""
import pandas as pd

TREND_FROM = 2006            # earlier years hold a few dozen stray records
TOP_COUNTRIES = 15
MIX_ALLTIME = 6              # all-time leaders kept as their own series …
MIX_RECENT = 4               # … plus the last full year's leaders
HEAT_COUNTRIES = 12
TOP_JUDGES = 15
HEAT_JUDGES = 20
REPEAT_COUNTRIES = 12
REPEAT_MIN_PERSONS = 1000
COHORT_MIN_PERSONS = 100
MISSING_ID = "0"
GAP_SHARE = 0.1
GAP_MIN_MEDIAN = 100
GAP_LIST = 6
PER_PERSON_BINS = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 10), (11, 20), (21, None)]
GAP_BINS = [(0, 0), (1, 7), (8, 21), (22, 35), (36, 60), (61, 180), (181, None)]
UNKNOWN = {"לא ידוע", "אירופה לא ידוע", "אפריקה לא ידוע", "דרום אמריקה"}
# Same country spelled two ways in the source (an older and a newer
# spelling); merged so a country isn't split across two bars.
ALIASES = {
    "גיאורגיה": "גרוזיה",
    "בילורוסיה": "בלארוס",
    "בלרוס": "בלארוס",
    "טוניס": "תוניסיה",
    "סעודיה": "ערב הסעודית",
    "הרפ הדומיניקנית": "הרפובליקה הדומיניקנית",
    "רפובליקה דומיניקנית": "הרפובליקה הדומיניקנית",
    "בורמה": "מיאנמר (בורמה)",
    "קונגו קינשאסה": "קונגו, רפ. דמוק.",
}
LRI, PDI = "⁦", "⁩"
RLM = "\u200f"   # makes a mixed digits+Hebrew axis label read right-to-left on the LTR chart canvas
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _month_he(p):
    y, m = p.split("-")
    return f"{MONTHS_HE[int(m) - 1]} {y}"


def _vc(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _top(vc, k, other="אחר"):
    items = [(name, int(v)) for name, v in vc.head(k).items()]
    rest = int(vc.iloc[k:].sum())
    if rest:
        items.append((other, rest))
    return items


def _bin_label(lo, hi, zero=None):
    # Hebrew words instead of "8–21" / "21+": a bare numeric range is
    # bidi-reversed on an RTL chart axis.
    if lo == 0 and hi == 0 and zero:
        return zero
    if hi is None:
        return f"{RLM}{lo} ומעלה"
    return f"{lo}" if lo == hi else f"{RLM}{lo} עד {hi}"


def _bin(series, bins):
    out = []
    for lo, hi in bins:
        m = series >= lo
        if hi is not None:
            m &= series <= hi
        out.append(int(m.sum()))
    return out


def _prepare(df):
    country = df["מדינה"].str.strip().replace(ALIASES).replace("", "לא ידוע")
    out = pd.DataFrame({
        "pid": df["מספר מוחזק או אסיר"].str.strip(),
        "date": pd.to_datetime(df["תאריך החלטה"].str.strip(), format="%d/%m/%Y", errors="coerce"),
        "country": country,
        "judge": df["שם דיין"].str.strip(),
    })
    out = out.dropna(subset=["date"])
    out["year"] = out["date"].dt.year.astype(int)
    return out


def _persons(df):
    """Per held person (valid holder number): decision count and the
    person's most frequent country (ties → alphabetical)."""
    p = df[(df["pid"] != MISSING_ID) & (df["pid"] != "")]
    cnt = p.groupby("pid").size()
    first = p.groupby("pid")["date"].min()
    cc = (p.groupby(["pid", "country"]).size().reset_index(name="k")
            .sort_values(["pid", "k", "country"], ascending=[True, False, True], kind="stable")
            .drop_duplicates("pid").set_index("pid")["country"])
    per = pd.DataFrame({"n": cnt, "first": first, "country": cc})
    s = p.sort_values(["pid", "date"], kind="stable")
    gaps = s.groupby("pid")["date"].diff().dt.days.dropna()
    return per, gaps, len(df) - len(p)


# ── insight rules ──────────────────────────────────────────────────────────

def insight_volume(per_year, full):
    if full not in per_year.index or (full - 1) not in per_year.index:
        return None
    a, b = int(per_year[full]), int(per_year[full - 1])
    if b < 100:
        return None
    ch = (a - b) / b
    trend = (f"בדומה ל-{full - 1} ({n(b)})" if abs(ch) < 0.03
             else f"{'עלייה' if ch > 0 else 'ירידה'} של {pct(abs(ch))} לעומת {full - 1} ({n(b)})")
    return f"ב-{full} ניתנו {n(a)} החלטות משמורת — {trend}."


def insight_peak(per_year, full):
    win = per_year[(per_year.index >= TREND_FROM) & (per_year.index <= full)]
    if win.empty or full not in win.index:
        return None
    peak = int(win.idxmax())
    pv, fv = int(win.max()), int(win[full])
    if peak == full:
        return f"{full} היא שנת השיא במאגר, עם {n(fv)} החלטות."
    drop = 1 - fv / pv
    if drop < 0.5:
        return None
    return (f"שנת השיא הייתה {peak} עם {n(pv)} החלטות; ב-{full} ניתנו {n(fv)} — "
            f"{pct(drop)} פחות מאשר בשיא.")


def insight_countries(df, full):
    all_vc = _vc(df["country"])
    recent = df[df["year"] == full]
    if len(recent) < 300 or len(all_vc) < 2:
        return None
    rec_vc = _vc(recent["country"])
    top2 = (all_vc.iloc[0] + all_vc.iloc[1]) / len(df)
    lead_now, lead_all = rec_vc.index[0], all_vc.index[0]
    head = (f"לאורך כל התקופה {lead_all} ו{all_vc.index[1]} הן מדינות המוצא המובילות "
            f"({pct(top2)} מההחלטות יחד)")
    if lead_now == lead_all:
        return (head + f"; גם ב-{full} {lead_now} מובילה, עם {pct(rec_vc.iloc[0] / len(recent))} "
                f"מההחלטות.")
    old_share = int(rec_vc.get(lead_all, 0)) / len(recent)
    return (head + f". ב-{full} מובילה דווקא {lead_now} ({pct(rec_vc.iloc[0] / len(recent))}), "
            f"ו{lead_all} ירדה ל-{pct(old_share)} מההחלטות.")


def insight_judges(df, ref):
    recent = df[(df["date"] > ref - pd.Timedelta(days=365)) & (df["judge"] != "")]
    if len(recent) < 300:
        return None
    vc = _vc(recent["judge"])
    top3 = vc.head(3).sum() / len(recent)
    return (f"ב-12 החודשים האחרונים שבמאגר נתנו {n(vc.size)} דיינים החלטות; הדיין עם מספר "
            f"ההחלטות הגבוה ביותר הוא {vc.index[0]} ({n(vc.iloc[0])}, {pct(vc.iloc[0] / len(recent))}), "
            f"ושלושת הראשונים נתנו יחד {pct(top3)} מההחלטות.")


def insight_repeat(per):
    if len(per) < 500:
        return None
    multi = (per["n"] > 1).mean()
    many = (per["n"] > 5).mean()
    return (f"{pct(1 - multi)} מהמוחזקים מופיעים במאגר בהחלטה אחת בלבד; "
            f"{pct(multi)} עברו יותר מביקורת אחת, ו-{pct(many)} — יותר מחמש.")


def insight_gap(gaps):
    if len(gaps) < 500:
        return None
    med = int(gaps.median())
    month = ((gaps >= 22) & (gaps <= 35)).mean()
    s = (f"החציון של הזמן בין שתי החלטות עוקבות בעניינו של אותו מוחזק הוא {n(med)} ימים")
    if month >= 0.2:
        s += (f"; {pct(month)} מהמרווחים הם בני {GAP_BINS[3][0]} עד {GAP_BINS[3][1]} ימים — "
              f"דפוס של ביקורת תקופתית חודשית.")
    else:
        s += "."
    return s


def insight_country_repeat(rows):
    if len(rows) < 2:
        return None
    hi = max(rows, key=lambda r: (r["mean"], r["country"]))
    lo = min(rows, key=lambda r: (r["mean"], r["country"]))
    if lo["mean"] <= 0 or hi["mean"] / lo["mean"] < 2:
        return None
    return (f"מספר הביקורות למוחזק משתנה מאוד לפי מדינת המוצא: מוחזקים מ{hi['country']} עברו "
            f"בממוצע {hi['mean']:.1f} החלטות (ל-{pct(hi['multi'])} יותר מאחת), לעומת "
            f"{lo['mean']:.1f} בלבד בקרב מוחזקים מ{lo['country']} "
            f"(מבין מדינות עם {n(REPEAT_MIN_PERSONS)} מוחזקים לפחות).")


# ── model ──────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["decisions"])
    total = len(df)
    ref = df["date"].max()
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    full = ref_year - 1 if partial else ref_year
    early = int((df["year"] < TREND_FROM).sum())

    per_year = df.groupby("year").size()
    tr = df[df["year"] >= TREND_FROM]
    years = sorted(int(v) for v in tr["year"].unique())
    py_persons = (tr[tr["pid"] != MISSING_ID].groupby("year")["pid"].nunique())
    yearly = {"x": [str(y) for y in years],
              "decisions": [int(per_year.get(y, 0)) for y in years],
              "persons": [int(py_persons.get(y, 0)) for y in years]}

    months = pd.period_range(start=pd.Period(f"{TREND_FROM}-01", "M"),
                             end=ref.to_period("M"), freq="M")
    pm = tr["date"].dt.to_period("M").value_counts()
    monthly = {"x": [str(p) for p in months], "y": [int(pm.get(p, 0)) for p in months]}
    # Recording gaps: a month (not the last, possibly partial one) with under
    # GAP_SHARE of the centred 13-month median, where that median is material.
    ms = pd.Series(monthly["y"], index=monthly["x"], dtype=float)
    med = ms.rolling(13, center=True, min_periods=7).median()
    gap_months = [m for m in ms.index[:-1]
                  if med[m] >= GAP_MIN_MEDIAN and ms[m] < GAP_SHARE * med[m]]

    # countries
    cvc = _vc(df["country"])
    known = cvc[[c not in UNKNOWN for c in cvc.index]]
    countries = _top(cvc, TOP_COUNTRIES, "שאר המדינות")
    rec = tr[tr["year"] == full]
    mix_names = list(known.head(MIX_ALLTIME).index)
    rec_known = [c for c in _vc(rec["country"]).index if c not in UNKNOWN][:MIX_RECENT]
    mix_names += [c for c in rec_known if c not in mix_names]
    by_yc = tr.groupby(["year", "country"]).size()
    tot_y = tr.groupby("year").size()
    mix_series = []
    for c in mix_names:
        mix_series.append({"name": c, "data": [round(int(by_yc.get((y, c), 0)) / int(tot_y[y]) * 100, 1)
                                               for y in years]})
    other = [round(100 - sum(s["data"][i] for s in mix_series), 1) for i in range(len(years))]
    mix_series.append({"name": "אחר", "data": [max(v, 0.0) for v in other]})
    mix = {"x": [str(y) for y in years], "series": mix_series}

    heat_c = list(known.head(HEAT_COUNTRIES).index)
    cheat_cells = []
    for xi, y in enumerate(years):
        for yi, c in enumerate(heat_c):
            v = int(by_yc.get((y, c), 0))
            if v:
                cheat_cells.append([xi, yi, v])
    cheat = {"x": [str(y) for y in years], "y": heat_c, "cells": cheat_cells,
             "max": max((c[2] for c in cheat_cells), default=1)}

    # judges
    jdf = df[df["judge"] != ""]
    jvc = _vc(jdf["judge"])
    judges = _top(jvc, TOP_JUDGES, "שאר הדיינים")
    recent = jdf[jdf["date"] > ref - pd.Timedelta(days=365)]
    judges_recent = _top(_vc(recent["judge"]), TOP_JUDGES, "שאר הדיינים")
    heat_j = list(jvc.head(HEAT_JUDGES).index)
    jt = jdf[jdf["year"] >= TREND_FROM]
    by_yj = jt.groupby(["year", "judge"]).size()
    jheat_cells = []
    for xi, y in enumerate(years):
        for yi, j in enumerate(heat_j):
            v = int(by_yj.get((y, j), 0))
            if v:
                jheat_cells.append([xi, yi, v])
    jheat = {"x": [str(y) for y in years], "y": heat_j, "cells": jheat_cells,
             "max": max((c[2] for c in jheat_cells), default=1)}
    judges_per_year = jt.groupby("year")["judge"].nunique()
    judges_full = int(judges_per_year.get(full, 0))

    # per person
    per, gaps, no_id = _persons(df)
    pp_labels = [_bin_label(lo, hi) for lo, hi in PER_PERSON_BINS]
    pp_vals = _bin(per["n"], PER_PERSON_BINS)
    gap_labels = [_bin_label(lo, hi, "באותו יום") for lo, hi in GAP_BINS]
    gap_vals = _bin(gaps, GAP_BINS)

    rep_rows = []
    pc = per.groupby("country")
    stats = pd.DataFrame({"persons": pc.size(), "mean": pc["n"].mean(),
                          "multi": pc["n"].apply(lambda s: float((s > 1).mean()))})
    stats = stats[(stats["persons"] >= REPEAT_MIN_PERSONS) & ~stats.index.isin(list(UNKNOWN))]
    stats = stats.reset_index().sort_values(["persons", "country"], ascending=[False, True],
                                            kind="stable").head(REPEAT_COUNTRIES)
    for _, r in stats.iterrows():
        rep_rows.append({"country": r["country"], "persons": int(r["persons"]),
                         "mean": round(float(r["mean"]), 2), "multi": float(r["multi"])})
    repeat_chart = {"names": [r["country"] for r in rep_rows],
                    "mean": [round(r["mean"], 2) for r in rep_rows],
                    "multi": [round(r["multi"] * 100, 1) for r in rep_rows]}

    per["fy"] = per["first"].dt.year.astype(int)
    cg = per[per["fy"] >= TREND_FROM].groupby("fy")
    coh = pd.DataFrame({"persons": cg.size(), "mean": cg["n"].mean(),
                        "multi": cg["n"].apply(lambda s: float((s > 1).mean()))})
    coh = coh[coh["persons"] >= COHORT_MIN_PERSONS].sort_index()
    cohort = {"x": [str(int(y)) for y in coh.index],
              "mean": [round(float(v), 2) for v in coh["mean"]],
              "multi": [round(float(v) * 100, 1) for v in coh["multi"]]}

    rules = [
        ("volume", insight_volume(per_year, full)),
        ("peak", insight_peak(per_year, full)),
        ("countries", insight_countries(tr, full)),
        ("judges", insight_judges(df, ref)),
        ("repeat", insight_repeat(per)),
        ("gap", insight_gap(gaps)),
        ("country_repeat", insight_country_repeat(rep_rows)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    full_v = int(per_year.get(full, 0))
    prev_v = int(per_year.get(full - 1, 0))
    # Caseload has no good/bad direction; a swing of ≥10% vs the year
    # before is flagged as notable context (info).
    last_tone = "info" if prev_v and abs(full_v - prev_v) / prev_v >= 0.10 else "brand"
    multi_share = float((per["n"] > 1).mean()) if len(per) else 0.0

    kpis = {
        "decisions": {"value": total, "display": n(total), "tone": "brand"},
        "persons": {"value": int(len(per)), "display": n(len(per)), "tone": "brand"},
        "last_year": {"value": full_v, "display": n(full_v), "tone": last_tone},
        "multi": {"value": round(multi_share * 100, 1), "display": f"{multi_share * 100:.1f}%",
                  "tone": "info"},
    }

    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    early_note = (f" {n(early)} החלטות מתוארכות לפני {TREND_FROM} ואינן מוצגות בגרף." if early else "")
    first_year = int(df["year"].min())
    labels = {
        "lede": (f"{n(total)} החלטות של בתי הדין לביקורת משמורת — הדנים בחוקיות החזקתם במשמורת "
                 f"של שוהים שלא כדין ומסתננים — בעניינם של {n(len(per))} מוחזקים, רובן מ-{TREND_FROM} ועד "
                 f"{d_he(ref)}. הדף מציג נתונים מצרפיים בלבד: לפי שנה, מדינת מוצא, דיין ומספר "
                 f"הביקורות לאדם, ללא פרטים מזהים של המוחזקים."),
        "last_year_kpi": f"החלטות ב-{full}",
        "persons_kpi": "מוחזקים שונים (לפי מספר מוחזק)",
        "multi_kpi": "מהמוחזקים עברו יותר מביקורת אחת",
        "yearly_note": (f"מספר ההחלטות בכל שנה, ומספר המוחזקים השונים שבעניינם ניתנה החלטה באותה "
                        f"שנה.{partial_note}{early_note}"),
        "yearly_aria": (f"גרף עמודות וקו: החלטות ומוחזקים שונים לפי שנה, {years[0]}–{years[-1]}. "
                        f"השיא ב-{int(per_year[per_year.index >= TREND_FROM].idxmax())}."),
        "yearly_caption": f"החלטות ומוחזקים שונים לפי שנה, {years[0]}–{years[-1]}.",
        "monthly_note": (f"מספר ההחלטות בכל חודש, מינואר {TREND_FROM} ועד {MONTHS_HE[ref.month - 1]} "
                         f"{ref_year}. ניתן להתמקד בטווח בעזרת הסרגל שמתחת לגרף."),
        "monthly_gaps": (f"בחודשים {', '.join(_month_he(m) for m in gap_months[:GAP_LIST])}{' ועוד' if len(gap_months) > GAP_LIST else ''} נרשמו מעט מאוד "
                         f"החלטות לעומת החודשים שסביבם — ככל הנראה פער ברישום ולא ירידה בפעילות."
                         if gap_months else ""),
        "monthly_aria": f"גרף קו: החלטות לפי חודש, {TREND_FROM}–{ref_year}, עם בורר טווח.",
        "mix_note": (f"חלקה של כל מדינת מוצא מסך ההחלטות בכל שנה, באחוזים — {MIX_ALLTIME} המדינות "
                     f"המובילות לאורך כל התקופה ועד {MIX_RECENT} המובילות ב-{full}; שאר המדינות "
                     f"מקובצות ב'אחר'."),
        "mix_aria": "גרף שטח מוערם: חלקן של מדינות המוצא המובילות בהחלטות בכל שנה, באחוזים.",
        "countries_note": (f"{n(len(known))} מדינות מוצא (אחרי איחוד שמות כפולים של אותה מדינה); "
                           f"{n(int(cvc[[c in UNKNOWN for c in cvc.index]].sum()))} החלטות "
                           f"ללא מדינה ידועה."),
        "countries_aria": f"תרשים עמודות: {TOP_COUNTRIES} מדינות המוצא עם מספר ההחלטות הגבוה ביותר.",
        "countries_caption": f"מספר ההחלטות לפי מדינת מוצא, {TOP_COUNTRIES} המובילות ושאר המדינות.",
        "cheat_aria": f"מפת חום: מספר ההחלטות לפי שנה ב-{HEAT_COUNTRIES} מדינות המוצא המובילות.",
        "cheat_note": f"מספר ההחלטות בכל שנה, ב-{HEAT_COUNTRIES} מדינות המוצא המובילות לאורך כל התקופה.",
        "judges_aria": f"תרשים עמודות: {TOP_JUDGES} הדיינים עם מספר ההחלטות הגבוה ביותר בכל התקופה.",
        "judges_caption": f"מספר ההחלטות לפי דיין, {TOP_JUDGES} המובילים ושאר הדיינים, כל התקופה.",
        "judges_recent_aria": "תרשים עמודות: הדיינים לפי מספר ההחלטות ב-12 החודשים האחרונים שבמאגר.",
        "judges_recent_caption": "מספר ההחלטות לפי דיין ב-12 החודשים האחרונים שבמאגר.",
        "judges_recent_note": (f"עד {d_he(ref)}; {n(recent['judge'].nunique())} דיינים נתנו החלטות "
                               f"בתקופה זו."),
        "jheat_note": (f"מספר ההחלטות של כל אחד מ-{HEAT_JUDGES} הדיינים הפעילים ביותר בכל שנה — "
                       f"מראה את תקופות הכהונה. ב-{full} פעלו {n(judges_full)} דיינים."),
        "jheat_aria": f"מפת חום: החלטות לפי דיין ({HEAT_JUDGES} המובילים) ושנה.",
        "pp_note": (f"מספר ההחלטות שניתנו בעניינו של כל מוחזק לאורך כל התקופה. "
                    f"{n(no_id)} החלטות ללא מספר מוחזק (רשומות כאפס) אינן נכללות."),
        "pp_aria": "תרשים עמודות: מוחזקים לפי מספר ההחלטות שניתנו בעניינם.",
        "pp_caption": "מספר המוחזקים לפי מספר ההחלטות בעניינם.",
        "gap_note": ("הזמן שחלף בין החלטה להחלטה הבאה בעניינו של אותו מוחזק, בימים. "
                     "מרווחים ארוכים במיוחד עשויים לשקף משמורת חוזרת ולא ביקורת רצופה."),
        "gap_aria": "תרשים עמודות: מרווחי הזמן בין החלטות עוקבות באותו מוחזק, בימים.",
        "gap_caption": "מספר המרווחים בין החלטות עוקבות לפי משך בימים.",
        "repeat_note": (f"ממוצע ההחלטות למוחזק ושיעור המוחזקים שעברו יותר מביקורת אחת, ב-"
                        f"{REPEAT_COUNTRIES} מדינות המוצא עם מספר המוחזקים הגבוה ביותר "
                        f"({n(REPEAT_MIN_PERSONS)} לפחות). כל מוחזק משויך למדינה השכיחה ברשומותיו."),
        "repeat_aria": "תרשים עמודות: ממוצע ההחלטות למוחזק לפי מדינת מוצא.",
        "repeat_caption": "מוחזקים, ממוצע החלטות למוחזק ושיעור המוחזקים עם יותר מהחלטה אחת, לפי מדינת מוצא.",
        "cohort_note": (f"לפי שנת ההחלטה הראשונה של כל מוחזק (שנים עם {n(COHORT_MIN_PERSONS)} מוחזקים "
                        f"לפחות): ממוצע ההחלטות למוחזק ושיעור מי שעברו יותר מביקורת אחת. "
                        f"בשנים האחרונות המספרים עשויים עוד לעלות — חלק מהביקורות טרם התקיימו."),
        "cohort_aria": "גרף קווים: ממוצע ההחלטות למוחזק ושיעור המוחזקים עם ביקורת חוזרת, לפי שנת ההחלטה הראשונה.",
        "cohort_caption": "ממוצע החלטות ושיעור ביקורת חוזרת לפי שנת ההחלטה הראשונה.",
        "notes": "המאגר מכיל את החלטות בתי הדין למשמורת",
    }

    tables = {
        "yearly": [{"year": str(y), "d": n(a), "p": n(b)}
                   for y, a, b in zip(years, yearly["decisions"], yearly["persons"])],
        "countries": [{"name": k, "count": n(v)} for k, v in countries],
        "judges": [{"name": k, "count": n(v)} for k, v in judges],
        "judges_recent": [{"name": k, "count": n(v)} for k, v in judges_recent],
        "pp": [{"bin": k, "count": n(v)} for k, v in zip(pp_labels, pp_vals)],
        "gap": [{"bin": k, "count": n(v)} for k, v in zip(gap_labels, gap_vals)],
        "repeat": [{"country": r["country"], "persons": n(r["persons"]), "mean": f"{r['mean']:.2f}",
                    "multi": f"{r['multi'] * 100:.1f}%"} for r in rep_rows],
        "cohort": [{"year": x, "mean": f"{m:.2f}", "multi": f"{s:.1f}%"}
                   for x, m, s in zip(cohort["x"], cohort["mean"], cohort["multi"])],
    }

    def bar(items):
        return {"names": [k for k, _ in items], "values": [v for _, v in items]}

    return {
        "agent_data": {
            "summary_he": (f"החלטות בתי הדין לביקורת משמורת של משרד המשפטים: {n(total)} החלטות "
                           f"בעניינם של {n(len(per))} מוחזקים, {first_year}–{ref_year}, לפי שנה, "
                           f"מדינת מוצא ודיין. מעודכן עד {ref.day}/{ref.month}/{ref.year}."),
            "dataset_kind": "timeseries",
            "related_ids": ["cf92190d-eec4-4906-beec-26fd2e2bb83d",
                            "176f2727-476e-440e-bc8d-5d3461ea0e76"],
            "suggested_tags": ["בתי דין למשמורת", "משמורת", "הגירה", "מבקשי מקלט",
                               "שוהים שלא כדין", "משרד המשפטים"],
            "temporal_coverage": f"{df['date'].min().strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "yearly": yearly,
            "monthly": monthly,
            "mix": mix,
            "countries": bar(countries),
            "cheat": cheat,
            "judges": bar(judges),
            "judges_recent": bar(judges_recent),
            "jheat": jheat,
            "pp": {"names": pp_labels, "values": pp_vals},
            "gap": {"names": gap_labels, "values": gap_vals},
            "repeat": repeat_chart,
            "cohort": cohort,
        },
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
