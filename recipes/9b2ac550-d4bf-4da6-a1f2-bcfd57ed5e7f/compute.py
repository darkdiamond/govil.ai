"""כלי רכב ביבוא אישי — the ACTIVE fleet of personally-imported vehicles.

One row per active vehicle. There is no import date: `moed_aliya_lakvish`
(first road entry) always equals the production year — it is the first
registration anywhere, not arrival in Israel — so the page describes the
fleet's composition, age, origin, fuel and licence status, never an
"imports per year" trend. "Now" is the latest inspection date in the data.
"""
import pandas as pd

OTHER = "אחר"
TOP_COUNTRIES = 10
TOP_MAKERS = 15
TOP_TYPES = 10
HEAT_COUNTRIES = 8
CLASSIC_AGE = 30            # "בני 30 ומעלה"
BIG_ENGINE_CC = 3000
COHORT = 5                  # production-year cohort width for the fuel-shift rule
FUEL_FROM_YEAR = 2000       # first production year on the fuel-mix chart
LICENCE_MONTHS = 12         # licence-expiry chart horizon

FUEL_GROUPS = {
    "בנזין": "בנזין", "דיזל": "דיזל", "חשמל/בנזין": "היברידי",
    "חשמל/דיזל": "היברידי", "חשמל": "חשמלי", 'גפמ"': 'גפ"מ',
}
FUEL_ORDER = ["בנזין", "דיזל", "היברידי", "חשמלי", 'גפ"מ', OTHER]
AGE_BINS = [(0, 5, "עד 5 שנים"), (6, 10, "6–10"), (11, 20, "11–20"),
            (21, 29, "21–29"), (30, 49, "30–49"), (50, 999, "50 ומעלה")]
CC_BINS = [(1, 1599, "עד 1,600"), (1600, 1999, "1,600–1,999"), (2000, 2999, "2,000–2,999"),
           (3000, 3999, "3,000–3,999"), (4000, 4999, "4,000–4,999"), (5000, 99999, "5,000 ומעלה")]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


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


def _bucket(v, bins):
    for lo, hi, label in bins:
        if lo <= v <= hi:
            return label
    return None


def _gershayim(s):
    """The register stores acronyms with the quote at the end ('ארהב"');
    put a real gershayim before the last letter ('ארה״ב')."""
    return s.str.replace(r'([א-ת])([א-ת])"(?=\s|$)', r"\1״\2", regex=True)


def _prepare(df):
    out = pd.DataFrame({
        "maker": _gershayim(df["tozeret_nm"].str.strip()).replace("", "לא צוין"),
        "type": df["sug_rechev_nm"].str.strip().replace("", "לא צוין"),
        "country": _gershayim(df["tozeret_eretz_nm"].str.strip()).replace("", "לא צוין"),
        "fuel_raw": df["sug_delek_nm"].str.strip(),
        "import": df["sug_yevu"].str.strip(),
        "year": pd.to_numeric(df["shnat_yitzur"], errors="coerce"),
        "cc": pd.to_numeric(df["nefach_manoa"], errors="coerce"),
        "test": pd.to_datetime(df["mivchan_acharon_dt"], errors="coerce", format="%Y-%m-%d"),
        "licence": pd.to_datetime(df["tokef_dt"], errors="coerce", format="%Y-%m-%d"),
    })
    out["fuel"] = out["fuel_raw"].map(FUEL_GROUPS).fillna(OTHER)
    out["used"] = out["import"].str.contains("משומש")
    return out


def insight_used(df):
    n, used = len(df), int(df["used"].sum())
    share = used / n
    if share >= 0.5:
        return (f"{_pct(share)} מכלי הרכב ({_int(used)}) יובאו כמשומשים; "
                f"{_int(n - used)} יובאו כחדשים.")
    return f"רוב כלי הרכב ({_pct(1 - share)}) יובאו כחדשים; {_int(used)} יובאו כמשומשים."


def insight_country(df):
    vc = _ranked(df["country"])
    if len(vc) < 2:
        return None
    (c1, n1), (c2, n2) = list(vc.items())[:2]
    return (f"{c1} היא ארץ הייצור הנפוצה ביותר ({_pct(n1 / len(df))}, {_int(n1)} כלי רכב), "
            f"ואחריה {c2} ({_pct(n2 / len(df))}).")


def insight_classic(df, ref_year):
    valid = df.dropna(subset=["year"])
    old = valid[ref_year - valid["year"] >= CLASSIC_AGE]
    if valid.empty or len(old) == 0:
        return None
    share = len(old) / len(valid)
    oldest = int(valid["year"].min())
    return (f"{_int(len(old))} כלי רכב ({_pct(share)}) הם בני {CLASSIC_AGE} שנה ומעלה; "
            f"הוותיק ביותר יוצר ב-{oldest}.")


def insight_fuel_shift(df):
    valid = df.dropna(subset=["year"])
    if valid.empty:
        return None
    last = int(valid["year"].max()) - 1   # latest production year is still filling
    recent = valid[valid["year"].between(last - COHORT + 1, last)]
    prior = valid[valid["year"].between(last - 2 * COHORT + 1, last - COHORT)]
    if len(recent) < 100 or len(prior) < 100:
        return None
    elec = ("היברידי", "חשמלי")
    r = recent["fuel"].isin(elec).mean()
    p = prior["fuel"].isin(elec).mean()
    span_r = f"{last - COHORT + 1}–{last}"
    span_p = f"{last - 2 * COHORT + 1}–{last - COHORT}"
    if abs(r - p) < 0.03:
        return (f"שיעור כלי הרכב החשמליים וההיברידיים דומה בשנתוני {span_r} ({_pct(r)}) "
                f"ובשנתוני {span_p} ({_pct(p)}).")
    word = "עלה" if r > p else "ירד"
    return (f"שיעור כלי הרכב החשמליים וההיברידיים {word} מ-{_pct(p)} בשנתוני {span_p} "
            f"ל-{_pct(r)} בשנתוני {span_r}.")


def insight_maker(df):
    vc = _ranked(df["maker"])
    name, n = vc.index[0], int(vc.iloc[0])
    share = n / len(df)
    if share < 0.08:
        return None
    return f"היצרן הנפוץ ביותר הוא {name}, עם {_int(n)} כלי רכב ({_pct(share)})."


def insight_engine(df):
    cars = df[(df["type"] == "פרטי נוסעים") & (df["cc"] > 0)]
    if len(cars) < 100:
        return None
    big = (cars["cc"] >= BIG_ENGINE_CC).mean()
    med = int(cars["cc"].median())
    return (f"למחצית מכלי הרכב הפרטיים נפח מנוע של {_int(med)} סמ״ק ומעלה, "
            f"ול-{_pct(big)} מהם נפח של {_int(BIG_ENGINE_CC)} סמ״ק ומעלה.")


def insight_licence(df, ref):
    lic = df["licence"].dropna()
    soon = lic[(lic >= ref) & (lic <= ref + pd.Timedelta(days=30))]
    expired = lic[lic < ref]
    if lic.empty:
        return None
    parts = f"תוקף הרישוי של {_int(len(soon))} כלי רכב יפוג ב-30 הימים שאחרי {_d_he(ref)}"
    if len(expired):
        parts += f", ול-{_int(len(expired))} נוספים הוא כבר פג"
    return parts + "."


def compute(frames):
    df = _prepare(frames["vehicles"])
    n = len(df)
    ref = df["test"].max()               # latest inspection = the data's "now"
    ref_year = int(ref.year)
    years = df.dropna(subset=["year"]).copy()
    years["year"] = years["year"].astype(int)
    years["age"] = ref_year - years["year"]

    # Vintage: production year (1970+, earlier pooled) by import type.
    vy = years.copy()
    vy["bucket"] = vy["year"].where(vy["year"] >= 1970, 1969)
    piv = vy.groupby(["bucket", "used"]).size().unstack(fill_value=0).sort_index()
    labels = ["לפני 1970" if y == 1969 else str(y) for y in piv.index]
    vintage = {
        "x": labels,
        "series": [
            {"name": "משומש", "data": [int(v) for v in piv.get(True, pd.Series(0, piv.index))]},
            {"name": "חדש", "data": [int(v) for v in piv.get(False, pd.Series(0, piv.index))]},
        ],
    }
    decade = (years["year"] // 10 * 10).clip(lower=1950)
    dec = years.groupby(decade).agg(total=("used", "size"), used=("used", "sum")).sort_index()
    t_decades = [{"name": ("לפני 1960" if d == 1950 else f"{d}–{d + 9}"),
                  "count": _int(r.total), "used": _int(r.used)} for d, r in dec.iterrows()]

    # Age buckets by import type.
    years["age_b"] = years["age"].map(lambda a: _bucket(a, AGE_BINS))
    ag = years.groupby(["age_b", "used"]).size().unstack(fill_value=0)
    age_labels = [b[2] for b in AGE_BINS]
    ag = ag.reindex(age_labels, fill_value=0)
    age = {"x": age_labels,
           "series": [{"name": "משומש", "data": [int(v) for v in ag.get(True, pd.Series(0, ag.index))]},
                      {"name": "חדש", "data": [int(v) for v in ag.get(False, pd.Series(0, ag.index))]}]}
    t_age = [{"name": b, "used": _int(ag.loc[b].get(True, 0)), "new": _int(ag.loc[b].get(False, 0))}
             for b in age_labels]

    # Rankings.
    c_names, c_vals = _top_other(df["country"], TOP_COUNTRIES)
    m_names, m_vals = _top_other(df["maker"], TOP_MAKERS)
    t_names, t_vals = _top_other(df["type"], TOP_TYPES)

    def rank_rows(names, vals):
        return [{"name": a, "count": _int(b), "share": f"{b / n * 100:.1f}"} for a, b in zip(names, vals)]

    # Fuel mix by production year.
    fy = years[years["year"] >= FUEL_FROM_YEAR]
    fp = fy.groupby(["year", "fuel"]).size().unstack(fill_value=0).sort_index()
    fp = fp.reindex(columns=[f for f in FUEL_ORDER if f in fp.columns])
    fshare = fp.div(fp.sum(axis=1), axis=0) * 100
    fuel_mix = {"x": [str(y) for y in fshare.index],
                "series": [{"name": f, "data": [round(float(v), 1) for v in fshare[f]]}
                           for f in fshare.columns]}
    fuel_tot = _ranked(df["fuel"])
    t_fuel = [{"name": f, "count": _int(v), "share": f"{v / n * 100:.1f}"}
              for f, v in fuel_tot.items()]

    # Engine size, private passenger cars with a combustion engine.
    cars = df[(df["type"] == "פרטי נוסעים") & (df["cc"] > 0)]
    cc_b = cars["cc"].map(lambda v: _bucket(v, CC_BINS))
    cc_counts = cc_b.value_counts().reindex([b[2] for b in CC_BINS], fill_value=0)
    engine = {"names": list(cc_counts.index), "values": [int(v) for v in cc_counts]}
    t_engine = [{"name": a, "count": _int(b), "share": f"{b / max(len(cars), 1) * 100:.1f}"}
                for a, b in zip(engine["names"], engine["values"])]

    # Country × age heatmap (% of each country's vehicles).
    top_c = list(_ranked(years["country"]).head(HEAT_COUNTRIES).index)
    hc = years[years["country"].isin(top_c)]
    hx = hc.groupby(["country", "age_b"]).size().unstack(fill_value=0).reindex(
        index=top_c, columns=age_labels, fill_value=0)
    hpct = hx.div(hx.sum(axis=1), axis=0) * 100
    cells = [[j, i, round(float(hpct.iat[i, j]), 1), int(hx.iat[i, j])]
             for i in range(len(top_c)) for j in range(len(age_labels))]
    heat = {"x": age_labels, "y": top_c, "cells": cells,
            "max": round(float(hpct.values.max()), 1) if len(cells) else 0}

    # Licence expiry over the next LICENCE_MONTHS months.
    lic = df["licence"].dropna()
    start = pd.Timestamp(ref.year, ref.month, 1)
    months = pd.date_range(start, periods=LICENCE_MONTHS, freq="MS")
    lm = lic.dt.to_period("M").value_counts()
    lic_x = [f"{MONTHS_HE[m.month - 1]} {m.year}" for m in months]
    lic_y = [int(lm.get(m.to_period("M"), 0)) for m in months]
    expired = int((lic < ref).sum())
    t_lic = [{"name": a, "count": _int(b)} for a, b in zip(lic_x, lic_y)]

    # Inspection recency.
    tested = df["test"].dropna()
    within_year = int((tested >= ref - pd.DateOffset(years=1)).sum())

    rules = [
        ("used", insight_used(df)),
        ("country", insight_country(df)),
        ("classic", insight_classic(df, ref_year)),
        ("fuel_shift", insight_fuel_shift(df)),
        ("maker", insight_maker(df)),
        ("engine", insight_engine(df)),
        ("licence", insight_licence(df, ref)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    used_n = int(df["used"].sum())
    elec_n = int(df["fuel"].isin(["היברידי", "חשמלי"]).sum())
    med_year = int(years["year"].median())
    y0, y1 = int(years["year"].min()), int(years["year"].max())

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} כלי רכב פעילים שיובאו ביבוא אישי, נכון ל-{_d_he(ref)}: "
                           f"{_pct(used_n / n)} משומשים, שנות ייצור {y0}–{y1}, "
                           f"מ-{df['country'].nunique()} ארצות ייצור."),
            "dataset_kind": "registry",
            "related_ids": [
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "0219b34f-43c7-435b-bdfe-e65e944cde50",
                "392abd0a-64f6-4c18-9d56-0111001411e6",
            ],
            "suggested_tags": ["יבוא אישי", "כלי רכב", "רכב אספנות", "תחבורה"],
            "temporal_coverage": f"{y0}/{y1}",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n)},
            "used": {"value": used_n, "display": _pct(used_n / n)},
            "median_year": {"value": med_year, "display": str(med_year)},
            "electrified": {"value": elec_n, "display": _int(elec_n)},
        },
        "charts": {
            "vintage": vintage,
            "age": age,
            "countries": {"names": c_names, "values": c_vals},
            "makers": {"names": m_names, "values": m_vals},
            "types": {"names": t_names, "values": t_vals},
            "fuel": fuel_mix,
            "engine": engine,
            "heat": heat,
            "licence": {"x": lic_x, "y": lic_y},
        },
        "tables": {
            "decades": t_decades,
            "age": t_age,
            "countries": rank_rows(c_names, c_vals),
            "makers": rank_rows(m_names, m_vals),
            "types": rank_rows(t_names, t_vals),
            "fuel": t_fuel,
            "engine": t_engine,
            "licence": t_lic,
        },
        "insights": insights,
        "labels": {
            "lede": (f"המאגר מונה {_int(n)} כלי רכב פעילים שיובאו ארצה ביבוא אישי, נכון "
                     f"לבדיקת הרישוי האחרונה שנרשמה בו ({_d_he(ref)}). חציון שנת הייצור הוא "
                     f"{med_year}; {_int(within_year)} כלי רכב עברו בדיקה שנתית בשנה האחרונה."),
            "as_of": _d_he(ref),
            "vintage_aria": f"תרשים עמודות: כלי רכב לפי שנת ייצור ({y0}–{y1}), משומש מול חדש.",
            "vintage_note": ("שנת הייצור של כלי הרכב הפעילים. המאגר אינו כולל את מועד היבוא "
                             "לישראל, ולכן זו תמונת הצי הנוכחי — לא קצב יבוא."),
            "decades_caption": "כלי רכב לפי עשור ייצור, סך הכול ומשומשים.",
            "age_aria": "תרשים עמודות: כלי רכב לפי גיל, משומש מול חדש.",
            "countries_aria": f"תרשים עמודות: {TOP_COUNTRIES} ארצות הייצור המובילות.",
            "makers_aria": f"תרשים עמודות: {TOP_MAKERS} היצרנים המובילים.",
            "types_aria": f"תרשים עמודות: {TOP_TYPES} סוגי הרכב הנפוצים.",
            "fuel_aria": f"תרשים שטח: תמהיל סוגי הדלק לפי שנת ייצור, {FUEL_FROM_YEAR} ואילך.",
            "fuel_note": ("היברידי = חשמל/בנזין או חשמל/דיזל. כל עמודה מסתכמת ל-100% "
                          "מכלי הרכב של אותה שנת ייצור."),
            "engine_aria": "תרשים עמודות: נפח מנוע של כלי רכב פרטיים.",
            "engine_note": (f"כלי רכב פרטיים עם נפח מנוע רשום ({_int(len(cars))}); "
                            "כלי רכב חשמליים ללא נפח מנוע אינם נכללים."),
            "heat_aria": f"מפת חום: התפלגות הגילים ב-{HEAT_COUNTRIES} ארצות הייצור המובילות.",
            "licence_aria": f"תרשים עמודות: מספר רישיונות הרכב שתוקפם פג בכל חודש, {LICENCE_MONTHS} חודשים.",
            "licence_note": (f"לפי תאריך תוקף הרישוי. ל-{_int(expired)} כלי רכב תוקף הרישוי כבר פג "
                             f"נכון ל-{_d_he(ref)}."),
        },
    }
