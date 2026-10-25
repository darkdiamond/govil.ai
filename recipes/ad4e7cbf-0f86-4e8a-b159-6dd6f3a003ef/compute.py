"""מאגר שומות מכריעות — decisions of decisive / advisory appraisers (MoJ).

One row per published decision (~31.6k, appended daily). Decisive
appraisers are public decision-makers and are named; the private parties
(owners, developers) in `appraisal_header` are never quoted — the header is
used only for an aggregate "is the party a corporation" heuristic. Block /
plot numbers identify specific parcels and are not used.

"Now" is the latest decision / publication date in the data, never the wall
clock. The latest decision year is partial unless it reaches late December;
recent months are also undercounted because decisions are published with a
delay (disclosed on the page).
"""
import re

import pandas as pd

TOP_COMMITTEES = 15
HEAT_COMMITTEES = 12
TOP_APPRAISERS = 15
COHORT_WIDTH = 3          # years per appraiser cohort band
LAG_RECENT_YEARS = 3      # full years used for the lag distribution
LAG_BUCKETS = [(0, 30), (31, 90), (91, 180), (181, 365), (366, 730), (731, None)]
LAG_OK_DAYS, LAG_WARN_DAYS = 90, 180
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
TYPE_ORDER = ["היטל השבחה", "תביעת פיצויים", "תיק הפקעות"]
APPRAISER_TYPE_ORDER = ["שמאי מכריע", "שמאי מייעץ"]
# Party text sits between "בעניין" and "נ' ועדה" in the header.
PARTY_RE = re.compile(r"בעניין\s+(?:היטל השבחה\s+|תביעת פיצויים\s+|תביעה לפיצויים\s+)?(.*?)\s+נ'?\s+ועד")
CORP_RE = re.compile(r"בע[\"'״]*\s?מ|בעמ|חברה|חברת|שותפות|יזמות|נכסים|השקעות|עמותה|אגודה|"
                     r"בני[י]?ה|קבוצת|\(\d{4}\)")


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _norm_name(s):
    """Fold spelling variants of one appraiser: nickname in parens / after a dash."""
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\s[–-]\s?\S+$", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _prepare(df):
    out = pd.DataFrame({
        "type": df["appraisal_type"].str.strip().replace("", "לא צוין"),
        "atype": df["appraiser_type"].str.strip().replace("", "לא צוין"),
        "committee": df["committee"].str.strip().replace("", "לא צוין"),
        "raw_appraiser": df["decisive_appraiser"].str.strip(),
        "dec": pd.to_datetime(df["decision_date"].str.strip(), errors="coerce",
                              format="%d/%m/%Y %H:%M"),
        "pub": pd.to_datetime(df["publicity_date"].str.strip(), errors="coerce",
                              format="%d/%m/%Y %H:%M"),
    })
    out["appraiser"] = out["raw_appraiser"].map(_norm_name).replace("", "לא צוין")
    party = df["appraisal_header"].str.extract(PARTY_RE, expand=False)
    out["has_party"] = party.notna()
    out["corp"] = party.fillna("").str.contains(CORP_RE)
    out = out.dropna(subset=["dec"]).copy()
    out["year"] = out["dec"].dt.year.astype(int)
    out["lag"] = (out["pub"] - out["dec"]).dt.days
    return out


def _sorted_counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _top(counts, k):
    top = counts.head(k)
    other = int(counts.iloc[k:].sum())
    names = list(top.index) + (["אחר"] if other else [])
    vals = [int(v) for v in top.values] + ([other] if other else [])
    return names, vals


def _year_label(y, ref_year, partial):
    return f"{y} (חלקית)" if (partial and y == ref_year) else str(y)


# ── insight rules ───────────────────────────────────────────────────────
def insight_types(types, total):
    lead, v = types.index[0], int(types.iloc[0])
    share = v / total
    if share < 0.5:
        return None
    rest = [f"{k} ({n(c)})" for k, c in types.iloc[1:].items()]
    s = f"{lead} הוא הנושא של {pct(share * 100)} מההכרעות ({n(v)})"
    return s + (f"; השאר: {', '.join(rest)}." if rest else ".")


def insight_committees(comms, total):
    if len(comms) < 3:
        return None
    (c1, v1), (c2, v2), (c3, v3) = list(comms.head(3).items())
    if v1 / total < 0.1:
        return None
    gap = "בפער ניכר " if v1 >= 2 * v2 else ""
    return (f"הוועדה המקומית {c1} מובילה {gap}עם {n(v1)} הכרעות ({pct(v1 / total * 100)} מהמאגר), "
            f"לפני {c2} ({n(v2)}) ו{c3} ({n(v3)}).")


def insight_trend(per_year, first_full, last_full):
    if last_full - first_full < 3 or last_full not in per_year.index:
        return None
    v1, v0 = int(per_year[last_full]), int(per_year.get(last_full - 1, 0))
    vf = int(per_year[first_full])
    if v0 == 0 or vf == 0:
        return None
    chg = v1 / v0 - 1
    full = per_year[(per_year.index >= first_full) & (per_year.index <= last_full)]
    record = " — שנת שיא" if full.idxmax() == last_full else ""
    if abs(chg) < 0.03:
        s = f"ב-{last_full} ניתנו {n(v1)} הכרעות, בדומה ל-{last_full - 1} ({n(v0)}){record}."
    else:
        word = "יותר" if chg > 0 else "פחות"
        s = (f"ב-{last_full} ניתנו {n(v1)} הכרעות — {pct(abs(chg) * 100)} {word} "
             f"מאשר ב-{last_full - 1}{record}.")
    ratio = v1 / vf
    if ratio >= 1.5:
        s += f" זהו פי {ratio:.1f} לעומת {first_full}, השנה המלאה הראשונה במאגר ({n(vf)})."
    return s


def insight_ytd(df, ref_pub):
    """Published-to-date this year vs the same window a year earlier (by publication date)."""
    y = ref_pub.year
    if ref_pub.month == 12 and ref_pub.day >= 24:
        return None
    start0 = pd.Timestamp(year=y - 1, month=1, day=1)
    try:
        end0 = ref_pub.replace(year=y - 1)
    except ValueError:
        end0 = ref_pub.replace(year=y - 1, day=28)
    cur = int(((df["pub"] >= pd.Timestamp(year=y, month=1, day=1)) & (df["pub"] <= ref_pub)).sum())
    prev = int(((df["pub"] >= start0) & (df["pub"] <= end0)).sum())
    if prev < 100 or (df["pub"] < start0).sum() == 0:
        return None
    chg = cur / prev - 1
    when = f"מתחילת {y} ועד {d_he(ref_pub)}"
    if abs(chg) < 0.05:
        return f"{when} פורסמו {n(cur)} הכרעות — בדומה לתקופה המקבילה ב-{y - 1} ({n(prev)})."
    word = "עלייה" if chg > 0 else "ירידה"
    return (f"{when} פורסמו {n(cur)} הכרעות, {word} של {pct(abs(chg) * 100)} לעומת התקופה "
            f"המקבילה ב-{y - 1} ({n(prev)}).")


def insight_lag(lag_med, base_year, last_full):
    """Baseline is the first full year after the database went live — earlier
    decisions were back-filled at launch, so their lag is not a publishing pace."""
    if base_year is None or base_year not in lag_med.index or last_full not in lag_med.index:
        return None
    a, b = float(lag_med[base_year]), float(lag_med[last_full])
    if a <= 0:
        return None
    if b <= a * 0.7:
        return (f"הפרסום מהיר יותר: חציון הזמן מהכרעה ועד פרסומה במאגר ירד מ-{n(a)} ימים בהכרעות "
                f"{base_year} ל-{n(b)} ימים בהכרעות {last_full}.")
    if b >= a * 1.3:
        return (f"הפרסום איטי יותר: חציון הזמן מהכרעה ועד פרסומה במאגר עלה מ-{n(a)} ימים בהכרעות "
                f"{base_year} ל-{n(b)} ימים בהכרעות {last_full}.")
    return None


def insight_appraisers(df, apprs, last_full):
    total = len(df)
    top3 = apprs.head(3)
    share3 = top3.sum() / total
    names = ", ".join(top3.index)
    act = df[df["year"] == last_full]
    n_act = act["appraiser"].nunique()
    per = df.groupby("appraiser")["committee"].nunique()
    med_comm = int(per.median())
    if n_act == 0:
        return None
    return (f"{n(apprs.size)} שמאים חתומים על ההכרעות במאגר, {n(n_act)} מהם פעלו ב-{last_full}. "
            f"שלושת המובילים ({names}) אחראים יחד ל-{pct(share3 * 100)} מההכרעות. "
            f"שמאי טיפוסי הכריע בתיקים של {n(med_comm)} ועדות מקומיות שונות.")


def insight_cohorts(df, last_full, cohort_of):
    act = df[df["year"] == last_full]
    if act.empty:
        return None
    first = df.groupby("appraiser")["year"].min()
    recent_cut = last_full - 5
    new = first[first > recent_cut].index
    share = act["appraiser"].isin(new).mean()
    first_y = int(df["year"].min()) + 1
    old = act["appraiser"].isin(first[first <= first_y].index).mean()
    if share < 0.25:
        return None
    k_old = int((first <= first_y).sum())
    if k_old and old == 0:
        tail = f"; אף אחד מ-{n(k_old)} השמאים שהחלו להכריע עד {first_y} לא הכריע באותה שנה."
    elif k_old:
        tail = f", ו-{pct(old * 100)} בידי שמאים שהחלו להכריע עד {first_y}."
    else:
        tail = "."
    return (f"{pct(share * 100)} מההכרעות ב-{last_full} ניתנו בידי שמאים שהחלו להכריע אחרי "
            f"{recent_cut}" + tail)


def insight_season(season, n_years):
    if n_years < 3:
        return None
    vals = pd.Series(season)
    mean = vals.mean()
    low2 = vals.sort_values(kind="stable").index[:2]
    if vals[low2].max() > mean * 0.92:
        return None
    hi = int(vals.idxmax())
    names = " ו".join(MONTHS_HE[m - 1] for m in sorted(low2))
    holidays = " (תקופת החגים)" if set(low2) == {9, 10} else ""
    return (f"החודשים החלשים בשנה הם {names}{holidays}: בממוצע {n(vals[low2].mean())} הכרעות לחודש, "
            f"לעומת {n(vals[hi])} ב{MONTHS_HE[hi - 1]}, החודש העמוס ביותר ({n_years} שנים מלאות).")


def insight_corp(corp_year, first_full, last_full):
    if first_full not in corp_year.index or last_full not in corp_year.index:
        return None
    a, b = corp_year[first_full], corp_year[last_full]
    if abs(b - a) < 0.03:
        return None
    word = "עלה" if b > a else "ירד"
    return (f"שיעור ההכרעות שבהן הצד שמול הוועדה הוא תאגיד (חברה, שותפות וכדומה, לפי שמו) "
            f"{word} מ-{pct(a * 100)} ב-{first_full} ל-{pct(b * 100)} ב-{last_full}.")


def compute(frames):
    raw = frames["decisions"]
    df = _prepare(raw)
    total = len(df)
    ref = df["dec"].max()
    ref_pub = df["pub"].max()
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = ref_year - 1 if partial else ref_year
    first_dec = df["dec"].min()
    min_year = int(first_dec.year)
    first_full = min_year if (first_dec.month == 1 and first_dec.day <= 7) else min_year + 1
    years = list(range(min_year, ref_year + 1))
    ylabels = [_year_label(y, ref_year, partial) for y in years]

    types = _sorted_counts(df["type"])
    type_names = [t for t in TYPE_ORDER if t in types.index] + \
                 [t for t in types.index if t not in TYPE_ORDER]
    comms = _sorted_counts(df["committee"])
    apprs = _sorted_counts(df["appraiser"])
    per_year = df.groupby("year").size().reindex(years, fill_value=0)

    # 1. per year by type
    by_type = df.groupby(["year", "type"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    years_chart = {"x": ylabels,
                   "series": [{"name": t, "data": [int(v) for v in by_type[t]]} for t in type_names]}
    years_table = [{"year": ylabels[i], "cells": [n(by_type[t].iloc[i]) for t in type_names],
                    "total": n(per_year.iloc[i])} for i in range(len(years))]

    # 2. monthly series (every month from first to last, zeros filled)
    ym = df["dec"].dt.to_period("M")
    months = pd.period_range(ym.min(), ym.max(), freq="M")
    monthly = ym.value_counts().reindex(months, fill_value=0)
    roll = monthly.rolling(12).mean()
    monthly_chart = {"x": [f"{p.year}-{p.month:02d}" for p in months],
                     "y": [int(v) for v in monthly],
                     "roll": [None if pd.isna(v) else round(float(v), 1) for v in roll]}

    # 3. seasonality: mean per calendar month over full years
    full = df[(df["year"] >= first_full) & (df["year"] <= last_full)]
    n_full_years = last_full - first_full + 1
    season = {}
    for m in range(1, 13):
        season[m] = float((full["dec"].dt.month == m).sum()) / max(n_full_years, 1)
    season_chart = {"x": MONTHS_HE, "y": [round(season[m], 1) for m in range(1, 13)]}

    # 4. committees
    c_names, c_vals = _top(comms, TOP_COMMITTEES)
    # 5. committees x year heatmap
    heat_c = list(comms.head(HEAT_COMMITTEES).index)
    cy = df[df["committee"].isin(heat_c)].groupby(["committee", "year"]).size()
    cells = [[xi, yi, int(cy.get((c, y), 0))] for yi, c in enumerate(heat_c) for xi, y in enumerate(years)]
    heat_chart = {"x": ylabels, "y": heat_c, "cells": cells,
                  "max": max([c[2] for c in cells] or [1])}

    # 6. appraisers
    a_names = list(apprs.head(TOP_APPRAISERS).index)
    a_vals = [int(apprs[a]) for a in a_names]
    agrp = df.groupby("appraiser").agg(first=("year", "min"), last=("year", "max"),
                                       ncomm=("committee", "nunique"))
    appr_table = [{"name": a, "count": n(apprs[a]),
                   "years": f"{int(agrp.loc[a, 'first'])}–{int(agrp.loc[a, 'last'])}",
                   "ncomm": n(agrp.loc[a, "ncomm"])} for a in a_names]
    merged_variants = int(df["raw_appraiser"].nunique() - df["appraiser"].nunique())

    # 7. cohorts: decisions per year by the appraiser's first-decision band
    def cohort_of(y):
        lo = min_year + ((y - min_year) // COHORT_WIDTH) * COHORT_WIDTH
        return f"{lo}–{lo + COHORT_WIDTH - 1}"
    df["cohort"] = df["appraiser"].map(agrp["first"]).map(cohort_of)
    cohort_names = sorted(df["cohort"].unique())
    coh = df.groupby(["year", "cohort"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    cohort_chart = {"x": ylabels, "series": [{"name": f"החלו {c}", "data": [int(v) for v in coh[c]]}
                                             for c in cohort_names]}
    cohort_sizes = df.groupby("cohort")["appraiser"].nunique()
    cohort_table = [{"cohort": c, "appraisers": n(cohort_sizes[c]),
                     "decisions": n((df["cohort"] == c).sum())} for c in cohort_names]

    # 8. active appraisers per year + decisions per appraiser
    active = df.groupby("year")["appraiser"].nunique().reindex(years, fill_value=0)
    per_appr = [round(float(per_year[y] / active[y]), 1) if active[y] else None for y in years]
    active_chart = {"x": ylabels, "active": [int(v) for v in active], "per": per_appr}
    active_table = [{"year": ylabels[i], "active": n(active.iloc[i]),
                     "per": "—" if per_appr[i] is None else f"{per_appr[i]:.1f}"}
                    for i in range(len(years))]

    # 9. publication lag by decision year (negative lags = data errors, excluded)
    lg = df[df["lag"].notna() & (df["lag"] >= 0)]
    neg = int((df["lag"] < 0).sum())
    lag_med = lg.groupby("year")["lag"].median()
    first_pub = df["pub"].min()
    base_year = int(first_pub.year) + 1
    if base_year > last_full - 3:
        base_year = None
    lag_p75 = lg.groupby("year")["lag"].quantile(0.75)
    lag_years = [y for y in years if y in lag_med.index]
    chart_lag_years = [y for y in lag_years if base_year is None or y >= base_year]
    lag_chart = {"x": [_year_label(y, ref_year, partial) for y in chart_lag_years],
                 "med": [int(round(lag_med[y])) for y in chart_lag_years],
                 "p75": [int(round(lag_p75[y])) for y in chart_lag_years]}
    lag_table = [{"year": _year_label(y, ref_year, partial), "med": n(round(lag_med[y])),
                  "p75": n(round(lag_p75[y]))} for y in lag_years]

    # 10. lag distribution, recent full years
    lag_from = max(first_full, last_full - LAG_RECENT_YEARS + 1)
    rec = lg[(lg["year"] >= lag_from) & (lg["year"] <= last_full)]["lag"]
    lag_rows = []
    for lo, hi in LAG_BUCKETS:
        m = rec >= lo
        if hi is not None:
            m &= rec <= hi
        lbl = f"{lo}+ ימים" if hi is None else f"{lo}–{hi} ימים"
        c = int(m.sum())
        lag_rows.append({"bucket": lbl, "count": c,
                         "share": (c / len(rec) * 100) if len(rec) else 0.0})
    lagdist_chart = {"x": [r["bucket"] for r in lag_rows], "y": [r["count"] for r in lag_rows]}

    # 11. compensation claims / expropriations by appraiser type
    minor = df[df["type"] != TYPE_ORDER[0]]
    atypes = [t for t in APPRAISER_TYPE_ORDER if t in set(df["atype"])] + \
             sorted(t for t in set(df["atype"]) if t not in APPRAISER_TYPE_ORDER)
    mt = minor.groupby(["year", "type"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    minor_types = [t for t in type_names if t in mt.columns]
    claims_chart = {"x": ylabels, "series": [{"name": t, "data": [int(v) for v in mt[t]]}
                                             for t in minor_types]}
    claims_table = [{"year": ylabels[i], "cells": [n(mt[t].iloc[i]) for t in minor_types]}
                    for i in range(len(years))]
    xt = df.groupby(["type", "atype"]).size()
    xtab = [{"type": t, "cells": [n(xt.get((t, a), 0)) for a in atypes]} for t in type_names]
    advisory = int((df["atype"] == "שמאי מייעץ").sum())

    # 12. corporate-party share by year
    pp = df[df["has_party"]]
    corp_year = pp.groupby("year")["corp"].mean()
    corp_cnt = pp.groupby("year").size()
    corp_years = [y for y in years if y in corp_year.index and corp_cnt[y] >= 50]
    corp_chart = {"x": [_year_label(y, ref_year, partial) for y in corp_years],
                  "y": [round(float(corp_year[y] * 100), 1) for y in corp_years]}
    corp_table = [{"year": _year_label(y, ref_year, partial),
                   "share": f"{corp_year[y] * 100:.1f}%", "n": n(corp_cnt[y])} for y in corp_years]
    parsed_share = df["has_party"].mean() * 100

    # KPIs
    lf_n = int(per_year.get(last_full, 0))
    prev_n = int(per_year.get(last_full - 1, 0))
    full_series = per_year[(per_year.index >= first_full) & (per_year.index <= last_full)]
    is_record = len(full_series) > 0 and full_series.idxmax() == last_full
    lf_tone = "info" if is_record else "brand"
    med_lf = float(lag_med[last_full]) if last_full in lag_med.index else None
    if med_lf is None:
        lag_tone = "brand"
    else:
        lag_tone = "ok" if med_lf <= LAG_OK_DAYS else ("warn" if med_lf <= LAG_WARN_DAYS else "danger")
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "last_full": {"value": lf_n, "display": n(lf_n), "tone": lf_tone},
        "active": {"value": int(active.get(last_full, 0)), "display": n(active.get(last_full, 0)),
                   "tone": "brand"},
        "lag": {"value": med_lf, "display": "—" if med_lf is None else n(round(med_lf)),
                "tone": lag_tone},
    }

    rules = [
        ("types", insight_types(types, total)),
        ("trend", insight_trend(per_year, first_full, last_full)),
        ("ytd", insight_ytd(df, ref_pub)),
        ("committees", insight_committees(comms, total)),
        ("appraisers", insight_appraisers(df, apprs, last_full)),
        ("cohorts", insight_cohorts(df, last_full, cohort_of)),
        ("lag", insight_lag(lag_med, base_year, last_full)),
        ("season", insight_season(season, n_full_years)),
        ("corp", insight_corp(corp_year, first_full, last_full)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    partial_note = (f" {ref_year} חלקית — ההכרעה האחרונה במאגר מ-{d_he(ref)}." if partial else "")
    lag_recent_med = int(rec.median()) if len(rec) else 0
    within90 = sum(r["share"] for r in lag_rows[:2])
    rec_lag_lf = med_lf if med_lf is not None else 0
    labels = {
        "lede": (f"הכרעות של שמאים מכריעים ושמאים מייעצים בסכסוכי שומה בין בעלי מקרקעין לוועדות "
                 f"התכנון המקומיות — בעיקר בהיטל השבחה. המאגר כולל {n(total)} הכרעות מ-{d_he(first_dec)} "
                 f"ועד {d_he(ref)}, ב-{n(comms.size)} ועדות מקומיות ובחתימת {n(apprs.size)} שמאים. "
                 f"הפרסום האחרון במאגר: {d_he(ref_pub)}."),
        "last_full_kpi": f"הכרעות ב-{last_full}" + (f" (שנת שיא)" if is_record else f" ({n(prev_n)} ב-{last_full - 1})"),
        "active_kpi": f"שמאים שהכריעו ב-{last_full}",
        "lag_kpi": f"חציון ימים מהכרעה לפרסום (הכרעות {last_full})",
        "years_note": (f"מספר ההכרעות לפי שנת ההחלטה וסוג השומה. השנה הראשונה במאגר ({min_year}) "
                       f"חלקית.{partial_note}"),
        "years_aria": (f"גרף עמודות מוערמות: הכרעות לפי שנה וסוג שומה, {min_year} עד {ref_year}; "
                       f"ב-{last_full} ניתנו {n(lf_n)} הכרעות."),
        "years_caption": f"מספר הכרעות לפי שנה וסוג שומה, {min_year}–{ref_year}.",
        "monthly_note": (f"הכרעות לפי חודש ההחלטה, עם ממוצע נע של שנים־עשר חודשים. הכרעות מתפרסמות "
                         f"באיחור (חציון של {n(round(rec_lag_lf))} ימים ב-{last_full}), ולכן החודשים "
                         f"האחרונים חסרים בחלקם ויתמלאו עם הפרסומים הבאים."),
        "monthly_aria": (f"גרף קווים: הכרעות לפי חודש מ-{monthly_chart['x'][0]} עד "
                         f"{monthly_chart['x'][-1]}, עם ממוצע נע שנתי."),
        "season_note": (f"ממוצע ההכרעות לחודש, לפי חודש בשנה, בשנים המלאות {first_full}–{last_full}."),
        "season_aria": f"גרף עמודות: ממוצע הכרעות לפי חודש בשנה, {first_full}–{last_full}.",
        "season_caption": f"ממוצע הכרעות לחודש, {first_full}–{last_full}.",
        "comm_aria": (f"תרשים עמודות: {TOP_COMMITTEES} הוועדות המקומיות עם מספר ההכרעות הגבוה ביותר; "
                      f"בראש {comms.index[0]} עם {n(comms.iloc[0])}."),
        "comm_caption": f"מספר הכרעות לפי ועדה מקומית ({TOP_COMMITTEES} המובילות ואחר).",
        "comm_note": (f"{TOP_COMMITTEES} הוועדות המקומיות עם מספר ההכרעות הגבוה ביותר. "
                      + (f"שאר {n(comms.size - TOP_COMMITTEES)} הוועדות ריכזו יחד "
                         f"{n(comms.iloc[TOP_COMMITTEES:].sum())} הכרעות "
                         f"({pct(comms.iloc[TOP_COMMITTEES:].sum() / total * 100)}) ומופיעות בטבלה כ״אחר״."
                         if comms.size > TOP_COMMITTEES else "")),
        "heat_note": f"מספר ההכרעות בכל שנה ב-{HEAT_COMMITTEES} הוועדות המקומיות הגדולות במאגר.",
        "heat_aria": f"מפת חום: הכרעות לפי ועדה מקומית ({HEAT_COMMITTEES} הגדולות) ושנה.",
        "appr_note": ("השמאים שחתומים על מספר ההכרעות הגבוה ביותר, עם שנות הפעילות במאגר ומספר "
                      "הוועדות המקומיות שבהן הכריעו."
                      + (" כתיבים שונים של שם אותו שמאי אוחדו." if merged_variants else "")),
        "appr_aria": (f"תרשים עמודות: {TOP_APPRAISERS} השמאים עם מספר ההכרעות הגבוה ביותר; "
                      f"בראש {apprs.index[0]} עם {n(apprs.iloc[0])}."),
        "appr_caption": f"{TOP_APPRAISERS} השמאים המובילים: הכרעות, שנות פעילות ומספר ועדות.",
        "cohort_note": (f"הכרעות בכל שנה לפי המחזור של השמאי — תקופה של {COHORT_WIDTH} שנים שבה "
                        f"ניתנה ההכרעה הראשונה שלו במאגר. רואים כך כיצד מחזורי מינוי חדשים מחליפים את הקודמים."),
        "cohort_aria": f"גרף עמודות מוערמות: הכרעות לפי שנה ולפי מחזור השמאים, {min_year}–{ref_year}.",
        "cohort_caption": "מחזורי שמאים: מספר שמאים ומספר הכרעות בכל מחזור.",
        "active_note": "מספר השמאים שנתנו לפחות הכרעה אחת בשנה, וממוצע ההכרעות לשמאי פעיל.",
        "active_aria": (f"גרף משולב: שמאים פעילים וממוצע הכרעות לשמאי לפי שנה; ב-{last_full} "
                        f"פעלו {n(active.get(last_full, 0))} שמאים."),
        "active_caption": "שמאים פעילים וממוצע הכרעות לשמאי, לפי שנה.",
        "lag_note": ("ימים מתאריך ההכרעה ועד פרסומה במאגר, לפי שנת ההכרעה: חציון ורבעון עליון. "
                     f"הפרסום הראשון במאגר הוא מ-{d_he(first_pub)}; הכרעות קודמות הועלו אז למפרע, "
                     f"ולכן הזמנים בשנים המוקדמות ארוכים"
                     + (f" — הגרף מתחיל ב-{base_year} והטבלה כוללת את כל השנים. " if base_year else ". ")
                     + 
                     "בשנים האחרונות חלק מההכרעות טרם פורסמו, כך שהערכים בהן עשויים לעלות מעט."
                     + (f" {n(neg)} רשומות שבהן תאריך הפרסום קודם לתאריך ההכרעה אינן נכללות." if neg else "")),
        "lag_aria": (f"גרף קווים: חציון ורבעון עליון של ימים מהכרעה לפרסום לפי שנה; "
                     f"החציון ב-{last_full}: {n(round(rec_lag_lf))} ימים."),
        "lag_caption": "ימים מהכרעה לפרסום לפי שנת ההכרעה: חציון ורבעון עליון.",
        "lagdist_note": (f"התפלגות זמן הפרסום בהכרעות {lag_from}–{last_full}: חציון של "
                         f"{n(lag_recent_med)} ימים, ו-{pct(within90)} פורסמו בתוך תשעים יום."),
        "lagdist_aria": f"תרשים עמודות: הכרעות {lag_from}–{last_full} לפי זמן מהכרעה לפרסום.",
        "lagdist_caption": f"הכרעות {lag_from}–{last_full} לפי זמן מהכרעה לפרסום.",
        "claims_note": (f"תביעות פיצויים (ירידת ערך בשל תכנית) ותיקי הפקעות — כ-{pct((total - int(types.get(TYPE_ORDER[0], 0))) / total * 100)} "
                        f"מההכרעות. {n(advisory)} הכרעות ניתנו בידי שמאי מייעץ, שממונה מטעם ועדת הערר."),
        "claims_aria": f"גרף עמודות מוערמות: תביעות פיצויים ותיקי הפקעות לפי שנה, {min_year}–{ref_year}.",
        "claims_caption": "תביעות פיצויים ותיקי הפקעות לפי שנה.",
        "xtab_caption": "הכרעות לפי סוג שומה וסוג השמאי.",
        "corp_note": (f"שיעור ההכרעות שבהן שם הצד שמול הוועדה מעיד על תאגיד (בע״מ, חברה, שותפות, "
                      f"יזמות וכדומה). זיהוי לפי מילים בכותרת ההכרעה — הערכה בלבד; הכותרת ניתנת "
                      f"לפענוח ב-{pct(parsed_share)} מההכרעות. שנים עם פחות מחמישים הכרעות אינן מוצגות."),
        "corp_aria": "גרף קווים: שיעור ההכרעות שבהן הצד שמול הוועדה הוא תאגיד, לפי שנה.",
        "corp_caption": "שיעור ההכרעות מול תאגיד ומספר ההכרעות שנבדקו, לפי שנה.",
    }
    tables = {
        "type_names": type_names,
        "years": years_table,
        "season": [{"month": MONTHS_HE[m - 1], "avg": f"{season[m]:.1f}"} for m in range(1, 13)],
        "committees": [{"name": k, "count": n(v)} for k, v in zip(c_names, c_vals)],
        "appraisers": appr_table,
        "cohorts": cohort_table,
        "active": active_table,
        "lag": lag_table,
        "lagdist": [{"bucket": r["bucket"], "count": n(r["count"]), "share": f"{r['share']:.1f}%"}
                    for r in lag_rows],
        "minor_types": minor_types,
        "claims": claims_table,
        "atypes": atypes,
        "xtab": xtab,
        "corp": corp_table,
    }
    charts = {
        "years": years_chart, "monthly": monthly_chart, "season": season_chart,
        "committees": {"names": list(comms.head(TOP_COMMITTEES).index),
                       "values": [int(v) for v in comms.head(TOP_COMMITTEES).values]},
        "heat": heat_chart,
        "appraisers": {"names": a_names, "values": a_vals},
        "cohorts": cohort_chart, "active": active_chart, "lag": lag_chart,
        "lagdist": lagdist_chart, "claims": claims_chart, "corp": corp_chart,
    }

    return {
        "agent_data": {
            "summary_he": (f"מאגר הכרעות השמאים המכריעים והמייעצים של משרד המשפטים: {n(total)} "
                           f"הכרעות {min_year}–{ref_year} בהיטלי השבחה, תביעות פיצויים והפקעות, "
                           f"לפי ועדה מקומית, שמאי, ומועדי ההכרעה והפרסום."),
            "dataset_kind": "timeseries",
            "related_ids": ["83372c35-23ce-4ddf-829f-1067b5ef3409", "669b2652-f75b-4de3-8e6b-0dfa17accef5"],
            "suggested_tags": ["שמאות מקרקעין", "היטל השבחה", "שמאי מכריע", "ועדות תכנון",
                               "תביעות פיצויים", "משרד המשפטים"],
            "temporal_coverage": f"{first_dec.strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
