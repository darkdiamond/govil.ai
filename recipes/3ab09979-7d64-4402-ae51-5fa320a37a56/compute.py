"""עיצומים כספיים למעסיקים — financial sanctions for labour-law violations.

One row per (decision × violated law); `final_sanction_amount` is the
sanction for that violation, so a decision's total is the sum of its rows
(verified at authoring: rows of one decision carry different amounts per
law). A decision = employer + decision date. Rows with no amount are counted
as violations but contribute nothing to sums; the page says so.

"Now" is the latest decision date in the data — the ministry publishes with
a lag, so windows end there, not at today's date.

Rankings of employers name only corporate bodies: a 9-digit registration
number starting with 5 (companies 51/52, non-profits 58, partnerships 55 …).
Rows without one may be sole traders and are never named.
"""
import re

import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
LAW_FAMILIES = [  # multi-label: a row may cite several laws
    ("הגנת השכר", r"הגנת השכר"),
    ("שכר מינימום", r"שכר מינימום"),
    ("פנסיה חובה", r"פנסיה"),
    ("שעות עבודה ומנוחה", r"שעות עבודה"),
    ("עבודת נשים", r"עבודת נשים"),
    ("עבודת הנוער", r"עבודת הנוער"),
    ("הודעה לעובד", r"הודעה לעובד"),
    ("חופשה שנתית", r"חופשה שנתית"),
    ("דמי מחלה", r"דמי מחלה"),
    ("עובדים זרים", r"עובדים זרים"),
    ("שוויון הזדמנויות", r"שוויון"),
]
OTHER = "אחר"
REASONS = {"פניה": "פנייה", "יזום/מודיעין": "יזום", "מודיעין": "יזום", "": "לא צוין"}
CORP_NUMBER_RE = re.compile(r"^5\d{8}$")
BUCKETS = [(0, 25_000), (25_000, 50_000), (50_000, 100_000), (100_000, 250_000),
           (250_000, 1_000_000), (1_000_000, None)]
TOP_N = 12
LAG_DAYS = 182


def _int(n):
    return f"{int(round(n)):,}"


def ils(v):
    """Shekel amount, compact for prose."""
    v = float(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:,.1f} מיליון ₪"
    return f"{v:,.0f} ₪"


def _pct(x):
    return f"{x * 100:.0f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _city(s):
    return re.sub(r"\s*-\s*", " - ", s.strip())


def _families(text):
    hits = [name for name, rx in LAW_FAMILIES if re.search(rx, text)]
    return hits or [OTHER]


def _prepare(df):
    out = pd.DataFrame({
        "employer": df["employer_name"].str.strip(),
        "emp_no": df["employer_number"].str.strip(),
        "d": pd.to_datetime(df["decision_date"].str.strip(), errors="coerce").dt.normalize(),
        "industry": df["industry"].str.strip().replace("", "לא צוין"),
        "amt": pd.to_numeric(df["final_sanction_amount"].str.replace(",", "").str.strip(),
                             errors="coerce"),
        "reason": df["reason_of_review"].str.strip().map(lambda r: REASONS.get(r, r)),
        "law": df["law"].str.strip(),
        "city": df["city"].map(_city),
        "appeal": df["appeal"].str.strip(),
    })
    out = out.dropna(subset=["d"])
    out["decision"] = out["employer"] + "|" + out["d"].dt.strftime("%Y-%m-%d")
    # Total order over every column: per-decision "first" values (industry,
    # appeal, city…) must not depend on CKAN row order.
    return out.sort_values(list(out.columns), kind="stable").reset_index(drop=True)


def _top(series, n=TOP_N):
    s = series.sort_index().sort_values(ascending=False, kind="stable")
    return s.head(n)


def settled_year(last):
    """Latest calendar year that ended at least LAG_DAYS before the newest
    decision. Decisions are published with a lag and backfilled (at authoring
    the last months held 1–4 decisions vs ~30 normally), so a trailing
    window would report a collapse that is only missing data."""
    y = last.year - 1
    while pd.Timestamp(year=y, month=12, day=31) > last - pd.Timedelta(days=LAG_DAYS):
        y -= 1
    return y


def insight_trend(dec, last):
    y = settled_year(last)
    cur = dec[dec["d"].dt.year == y]
    prev = dec[dec["d"].dt.year == y - 1]
    if len(prev) == 0 or len(cur) == 0:
        return None
    ch = (len(cur) - len(prev)) / len(prev)
    if abs(ch) < 0.05:
        trend = "כמעט ללא שינוי במספר ההחלטות"
    else:
        trend = f"{'עלייה' if ch > 0 else 'ירידה'} של {abs(ch) * 100:.0f}% במספר ההחלטות"
    return (f"ב-{y} הוטלו עיצומים ב-{_int(len(cur))} החלטות בסך {ils(cur['total'].sum())} — "
            f"{trend} לעומת {y - 1} ({_int(len(prev))} החלטות, {ils(prev['total'].sum())}).")


def insight_law(fam_counts, n_rows):
    if fam_counts.empty:
        return None
    name, n = fam_counts.index[0], fam_counts.iloc[0]
    if name == OTHER:
        return None
    second = (f"; אחריו {fam_counts.index[1]} ({_pct(fam_counts.iloc[1] / n_rows)})"
              if len(fam_counts) > 1 and fam_counts.index[1] != OTHER else "")
    return f"החוק שהופר בתדירות הגבוהה ביותר: {name} — {_pct(n / n_rows)} מההפרות{second}."


def insight_industry(rows):
    by = _top(rows.groupby("industry")["amt"].sum(), 3)
    total = rows["amt"].sum()
    if by.empty or total <= 0:
        return None
    share = by.iloc[0] / total
    if share < 0.08:
        return None
    return (f"ענף {by.index[0]} ספג את הסכום הגבוה ביותר: {ils(by.iloc[0])} "
            f"({_pct(share)} מסך העיצומים).")


def insight_size(dec):
    paid = dec[dec["total"] > 0]
    if len(paid) < 20:
        return None
    med = paid["total"].median()
    big = int((paid["total"] >= 250_000).sum())
    top = paid.loc[paid["total"].idxmax()]
    return (f"חציון העיצום להחלטה הוא {ils(med)}; {_int(big)} החלטות הסתכמו ב-250 אלף ₪ "
            f"ומעלה, והגבוהה שבהן — {ils(top['total'])} (ענף {top['industry']}, "
            f"{top['d'].year}).")


def insight_reason(dec):
    shares = dec["reason"].value_counts(normalize=True)
    if shares.empty:
        return None
    ini, cmp_ = shares.get("יזום", 0), shares.get("תלונה", 0) + shares.get("פנייה", 0)
    if ini >= cmp_:
        return (f"רוב ההחלטות ({_pct(ini)}) נבעו מבדיקה יזומה של המשרד; "
                f"{_pct(cmp_)} מתלונה או פנייה של עובד.")
    return (f"רוב ההחלטות ({_pct(cmp_)}) נבעו מתלונה או פנייה של עובד; "
            f"{_pct(ini)} מבדיקה יזומה של המשרד.")


def insight_appeals(dec):
    known = dec[dec["appeal"] != ""]
    if len(known) < 30:
        return None
    appealed = known[known["appeal"].str.startswith("כן")]
    rejected = appealed["appeal"].str.contains("נדחתה").sum()
    if len(appealed) == 0:
        return f"באף אחת מ-{_int(len(known))} ההחלטות עם מידע על ערעור לא הוגשה בקשה לביטול."
    return (f"ב-{_pct(len(appealed) / len(known))} מההחלטות שיש לגביהן מידע הוגשה בקשה לביטול או "
            f"הפחתה; {_int(rejected)} מתוך {_int(len(appealed))} בקשות נדחו.")


def compute(frames):
    rows = _prepare(frames["sanctions"])
    last, first = rows["d"].max(), rows["d"].min()
    no_amt = int(rows["amt"].isna().sum())
    rows["amt"] = rows["amt"].fillna(0.0)

    dec = (rows.groupby("decision", sort=True)
           .agg(d=("d", "first"), total=("amt", "sum"), industry=("industry", "first"),
                reason=("reason", "first"), appeal=("appeal", "first"),
                employer=("employer", "first"), emp_no=("emp_no", "first"),
                city=("city", "first"))
           .reset_index())

    years = list(range(int(first.year), int(last.year) + 1))
    by_year_n = dec.groupby(dec["d"].dt.year).size()
    by_year_amt = dec.groupby(dec["d"].dt.year)["total"].sum()
    yearly = {
        "years": [str(y) for y in years],
        "decisions": [int(by_year_n.get(y, 0)) for y in years],
        "millions": [round(float(by_year_amt.get(y, 0)) / 1e6, 2) for y in years],
    }

    fam_rows = rows.assign(fam=rows["law"].map(_families)).explode("fam")
    fam_counts = _top(fam_rows["fam"].value_counts(), 20)
    fam_amt = fam_rows.groupby("fam")["amt"].sum()
    laws = {"names": list(fam_counts.index), "values": [int(v) for v in fam_counts]}

    ind_amt = _top(rows.groupby("industry")["amt"].sum())
    ind_n = dec.groupby("industry").size()
    industries = {
        "names": list(ind_amt.index),
        "millions": [round(float(v) / 1e6, 2) for v in ind_amt],
        "decisions": [int(ind_n.get(i, 0)) for i in ind_amt.index],
    }

    reasons_order = ["יזום", "פנייה", "תלונה", "לא צוין"]
    extra = sorted(set(dec["reason"]) - set(reasons_order))
    reasons_order = [r for r in reasons_order + extra if (dec["reason"] == r).any()]
    by_reason = dec.groupby([dec["d"].dt.year, "reason"]).size()
    reasons = {
        "years": [str(y) for y in years],
        "series": [{"name": r, "data": [int(by_reason.get((y, r), 0)) for y in years]}
                   for r in reasons_order],
    }

    paid = dec[dec["total"] > 0]
    labels_b, counts_b = [], []
    for lo, hi in BUCKETS:
        sel = paid["total"] >= lo if hi is None else (paid["total"] >= lo) & (paid["total"] < hi)
        labels_b.append(f"{lo / 1000:,.0f} אלף ומעלה" if hi is None
                        else f"{lo / 1000:,.0f}–{hi / 1000:,.0f} אלף")
        counts_b.append(int(sel.sum()))
    buckets = {"names": labels_b, "values": counts_b}

    corp = dec[dec["emp_no"].str.match(CORP_NUMBER_RE)]
    top_emp = _top(corp.groupby("employer")["total"].sum(), 10)
    employers = {"names": list(top_emp.index),
                 "millions": [round(float(v) / 1e6, 2) for v in top_emp]}

    cities_s = _top(dec.loc[dec["city"] != "", "city"].value_counts())
    cities = {"names": list(cities_s.index), "values": [int(v) for v in cities_s]}

    rules = [
        ("trend", insight_trend(dec, last)),
        ("law", insight_law(fam_counts, len(rows))),
        ("industry", insight_industry(rows)),
        ("size", insight_size(dec)),
        ("reason", insight_reason(dec)),
        ("appeals", insight_appeals(dec)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    total = rows["amt"].sum()
    kpis = {
        "total": {"value": float(total), "display": ils(total)},
        "decisions": {"value": len(dec), "display": _int(len(dec))},
        "employers": {"value": int(dec["employer"].nunique()),
                      "display": _int(dec["employer"].nunique())},
        "median": {"value": float(paid["total"].median()) if len(paid) else None,
                   "display": ils(paid["total"].median()) if len(paid) else "—"},
    }

    y0, y1 = int(first.year), int(last.year)
    year_table = [{"year": y, "n": _int(n), "amt": ils(a * 1e6)}
                  for y, n, a in zip(yearly["years"], yearly["decisions"], yearly["millions"])]
    labels = {
        "lede": (f"{kpis['decisions']['display']} החלטות על עיצום כספי שהטיל משרד העבודה על "
                 f"{kpis['employers']['display']} מעסיקים בגין הפרת חוקי עבודה, מ-{d_he(first)} ועד "
                 f"{d_he(last)}, בסך כולל של {kpis['total']['display']}."),
        "amount_note": (f"סכום העיצום הוא הסכום הסופי שנרשם לכל הפרה; {_int(no_amt)} הפרות "
                        f"נרשמו ללא סכום ואינן נכללות בסכומים." if no_amt else
                        "סכום העיצום הוא הסכום הסופי שנרשם לכל הפרה."),
        "yearly_aria": (f"תרשים משולב: מספר ההחלטות (עמודות) וסך העיצומים במיליוני ₪ (קו) "
                        f"לפי שנה, {y0} עד {y1}."),
        "laws_aria": "תרשים עמודות אופקי: מספר ההפרות לפי החוק שהופר.",
        "ind_aria": f"תרשים עמודות אופקי: סך העיצומים ב-{len(industries['names'])} הענפים המובילים.",
        "reasons_aria": f"תרשים עמודות מוערמות: החלטות לפי מקור הבדיקה ושנה, {y0} עד {y1}.",
        "buckets_aria": "תרשים עמודות: התפלגות ההחלטות לפי גובה העיצום הכולל.",
        "emp_aria": f"תרשים עמודות אופקי: {len(employers['names'])} התאגידים עם סך העיצומים הגבוה ביותר.",
        "emp_note": ("תאגידים בלבד (מספר רישום בן 9 ספרות המתחיל ב-5: חברות, עמותות, שותפויות). "
                     "מעסיקים שאינם תאגיד אינם מדורגים."),
        "cities_aria": f"תרשים עמודות אופקי: {len(cities['names'])} היישובים עם מספר ההחלטות הגבוה ביותר.",
        "partial": (f"ההחלטה האחרונה במאגר מ-{d_he(last)}. ההחלטות מתפרסמות באיחור ומתווספות "
                    f"בדיעבד, ולכן השנים שאחרי {settled_year(last)} עדיין חלקיות ועשויות לגדול."),
        "year_caption": f"מספר החלטות וסך עיצומים לפי שנה, {y0} עד {y1}.",
        "multi_law_note": "החלטה אחת עשויה לכלול הפרות של כמה חוקים — כל הפרה נספרת.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{kpis['decisions']['display']} החלטות על עיצומים כספיים למעסיקים בגין "
                           f"הפרת חוקי עבודה, {y0}–{y1}, בסך {kpis['total']['display']} — לפי חוק, "
                           f"ענף, שנה ומקור הבדיקה."),
            "dataset_kind": "registry",
            "suggested_tags": ["זכויות עובדים", "אכיפה", "עיצומים כספיים", "שכר מינימום", "משרד העבודה"],
            "temporal_coverage": f"{first.strftime('%Y-%m-%d')}/{last.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "yearly": yearly,
            "laws": laws,
            "industries": industries,
            "reasons": reasons,
            "buckets": buckets,
            "employers": employers,
            "cities": cities,
        },
        "tables": {"years": year_table},
        "insights": insights,
        "labels": labels,
    }
