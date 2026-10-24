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
# Detail fields (headcount, reductions, appeals) are filled only from the year
# the publication format changed (2023 at authoring). The detail views cover
# the years from the first one where at least this share of rows is filled.
DETAIL_FILL = 0.8
# Reduction grounds (regulation 1 of the sanctions-reduction rules), multi-label.
REDUCTIONS = [
    ("עבר נקי (5 שנים ללא הפרה)", r"1\(א\)\(1\)|לא הפר"),
    ("הפסקת ההפרה לפני פניית מפקח", r"1\(א\)\(2\)|הפסיק את ההפרה"),
    ("צעדים למניעת הישנות", r"1\(א\)\(3\)|נקט פעולות|נקט בפעולות"),
    ("מחזור עסקאות נמוך", r"מחזור|1א\s*-|1א\("),
    ("נסיבות אישיות חריגות", r"1\(א\)\(5\)|נסיבות אישיות"),
]
NO_REDUCTION = "ללא הפחתה"
SIZE_BUCKETS = [(1, 5, "1–5"), (6, 20, "6–20"), (21, 50, "21–50"),
                (51, 250, "51–250"), (251, None, "251 ומעלה")]
# Ordered, first match wins: "טרם התקבלה החלטה" (pending) contains "התקבלה",
# and "התקבלה חלקית" contains it too — both must be tested before it.
OUTCOMES = [("טרם הוחלט", r"טרם"), ("נדחתה", r"נדחת"), ("התקבלה חלקית", r"חלקית"),
            ("התקבלה", r"התקבלה")]


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
        "court": df["court_appeal"].str.strip(),
        "employees": pd.to_numeric(df["employees_general_number"].str.replace(",", "")
                                   .str.strip(), errors="coerce"),
        "reduction": df["financial_sanction_reduction"].str.strip(),
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


def detail_start(rows):
    """First year from which the detail fields are consistently filled, or
    None if no year reaches DETAIL_FILL."""
    filled = (rows["appeal"] != "").groupby(rows["d"].dt.year).mean().sort_index()
    # The run of well-filled years that reaches the latest year: a stray
    # early year with a few filled rows must not pull the window back.
    start = None
    for y in reversed(list(filled.index)):
        if filled[y] < DETAIL_FILL:
            break
        start = int(y)
    return start


def outcome_of(text):
    if not text.startswith("כן"):
        return None
    for name, rx in OUTCOMES:
        if re.search(rx, text):
            return name
    return "אחר"


def size_bucket(n):
    if pd.isna(n) or n < 1:
        return None
    for lo, hi, label in SIZE_BUCKETS:
        if n >= lo and (hi is None or n <= hi):
            return label
    return None


def insight_reductions(detail_dec, start):
    known = detail_dec[detail_dec["red_known"]]
    if len(known) < 50:
        return None
    reduced = known[known["reduced"]]
    share = len(reduced) / len(known)
    counts = {name: int(known[name].sum()) for name, _ in REDUCTIONS}
    top = max(counts, key=lambda k: (counts[k], k))
    if not reduced.empty and counts[top] > 0:
        return (f"מאז {start} קיבלו {_pct(share)} מההחלטות הפחתה בעיצום; הנימוק הנפוץ: "
                f"{top} ({_int(counts[top])} החלטות).")
    return f"מאז {start} כמעט לא ניתנו הפחתות בעיצום ({_pct(share)} מההחלטות)."


def insight_employer_size(detail_dec, start):
    known = detail_dec.dropna(subset=["size"])
    if len(known) < 50:
        return None
    small = known["size"].isin(["1–5", "6–20"]).mean()
    if small >= 0.5:
        return (f"מאז {start}, {_pct(small)} מההחלטות הוטלו על מעסיקים עם עד 20 עובדים — "
                "האכיפה פוגשת בעיקר עסקים קטנים.")
    return f"מאז {start}, {_pct(1 - small)} מההחלטות הוטלו על מעסיקים עם יותר מ-20 עובדים."


def compute(frames):
    rows = _prepare(frames["sanctions"])
    last, first = rows["d"].max(), rows["d"].min()
    no_amt = int(rows["amt"].isna().sum())
    rows["amt"] = rows["amt"].fillna(0.0)

    dec = (rows.groupby("decision", sort=True)
           # appeal/court: "max" — rows are sorted by every column, so "first"
           # would pick "" whenever one row of a decision left it empty.
           .agg(d=("d", "first"), total=("amt", "sum"), industry=("industry", "first"),
                reason=("reason", "first"), appeal=("appeal", "max"),
                court=("court", "max"), employees=("employees", "max"),
                employer=("employer", "first"), emp_no=("emp_no", "first"),
                city=("city", "first"))
           .reset_index())

    # Detail views: decisions from the first consistently-filled year.
    start = detail_start(rows)
    red_rows = rows.assign(red_text=rows["reduction"])
    for name, rx in REDUCTIONS:
        red_rows[name] = red_rows["red_text"].str.contains(rx)
    red_dec = red_rows.groupby("decision").agg(
        red_known=("red_text", lambda s: bool((s != "").any())),
        **{name: (name, "any") for name, _ in REDUCTIONS},
    )
    dec = dec.join(red_dec, on="decision")
    dec["reduced"] = dec[[n for n, _ in REDUCTIONS]].any(axis=1)
    dec["size"] = dec["employees"].map(size_bucket)
    detail = dec[dec["d"].dt.year >= start] if start is not None else dec.iloc[0:0]

    known_red = detail[detail["red_known"]]
    reductions = {
        "names": [n for n, _ in REDUCTIONS] + [NO_REDUCTION],
        "values": [int(known_red[n].sum()) for n, _ in REDUCTIONS]
                  + [int((~known_red["reduced"]).sum())],
        "base": len(known_red),
    }

    sized = detail.dropna(subset=["size"])
    size_order = [label for _, _, label in SIZE_BUCKETS]
    by_size_n = sized.groupby("size").size()
    by_size_med = sized[sized["total"] > 0].groupby("size")["total"].median()
    sizes = {
        "names": size_order,
        "decisions": [int(by_size_n.get(s, 0)) for s in size_order],
        "median": [int(round(float(by_size_med.get(s, 0)))) if s in by_size_med.index else 0
                   for s in size_order],
    }

    outcome_names = [n for n, _ in OUTCOMES] + ["אחר"]
    req = detail["appeal"].map(outcome_of).dropna()
    crt = detail["court"].map(outcome_of).dropna()
    appeals = {
        "stages": ["בקשה לביטול או הפחתה", "ערעור לבית הדין לעבודה"],
        "series": [{"name": o, "data": [int((req == o).sum()), int((crt == o).sum())]}
                   for o in outcome_names if (req == o).any() or (crt == o).any()],
        "asked": int(len(req)),
        "court": int(len(crt)),
        "base": int((detail["appeal"] != "").sum()),
    }

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
        ("reductions", insight_reductions(detail, start)),
        ("employer_size", insight_employer_size(detail, start)),
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
        "detail_note": (f"מאז {start} המאגר מפרט לכל החלטה את מספר העובדים, נימוקי ההפחתה "
                        f"ובקשות הביטול; בהחלטות מוקדמות יותר שדות אלה כמעט ריקים, ולכן "
                        f"הגרפים בחלק זה מתייחסים ל-{_int(len(detail))} ההחלטות מ-{start} ואילך."
                        if start is not None else ""),
        "red_aria": (f"תרשים עמודות אופקי: מספר ההחלטות לפי נימוק ההפחתה בעיצום, מתוך "
                     f"{_int(reductions['base'])} החלטות עם מידע על הפחתה."),
        "red_note": ("החלטה אחת עשויה לקבל הפחתה מכמה נימוקים — כל נימוק נספר. "
                     f"בסיס: {_int(reductions['base'])} החלטות."),
        "size_aria": ("תרשים משולב: מספר ההחלטות (עמודות) וחציון העיצום להחלטה (קו) לפי "
                      "מספר העובדים אצל המעסיק."),
        "size_note": (f"{_int(len(sized))} החלטות שבהן צוין מספר העובדים. חציון העיצום "
                      "מחושב על החלטות עם סכום."),
        "appeals_aria": (f"תרשים עמודות מוערמות: תוצאות {_int(appeals['asked'])} בקשות לביטול "
                         f"או הפחתה ו-{_int(appeals['court'])} ערעורים לבית הדין."),
        "appeals_note": (f"מתוך {_int(appeals['base'])} החלטות עם מידע: "
                         f"{_int(appeals['asked'])} בקשות לביטול או הפחתה, "
                         f"{_int(appeals['court'])} ערעורים לבית הדין לעבודה."),
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
            "reductions": reductions,
            "sizes": sizes,
            "appeals": appeals,
        },
        "flags": {"detail": start is not None and len(detail) >= 50},
        "tables": {
            "years": year_table,
            "laws": [{"name": n, "v": _int(v)} for n, v in zip(laws["names"], laws["values"])],
            "buckets": [{"name": n, "v": _int(v)}
                        for n, v in zip(buckets["names"], buckets["values"])],
            "industries": [{"name": n, "amt": ils(a * 1e6), "n": _int(c)}
                           for n, a, c in zip(industries["names"], industries["millions"],
                                              industries["decisions"])],
            "reasons": {
                "cols": [s["name"] for s in reasons["series"]],
                "rows": [{"year": y, "vals": [_int(s["data"][i]) for s in reasons["series"]]}
                         for i, y in enumerate(reasons["years"])],
            },
            "employers": [{"name": n, "v": ils(m * 1e6)}
                          for n, m in zip(employers["names"], employers["millions"])],
            "cities": [{"name": n, "v": _int(v)} for n, v in zip(cities["names"], cities["values"])],
            "reductions": [{"name": n, "v": _int(v)}
                           for n, v in zip(reductions["names"], reductions["values"])],
            "sizes": [{"name": n, "n": _int(c), "med": ils(md) if md else "—"}
                      for n, c, md in zip(sizes["names"], sizes["decisions"], sizes["median"])],
            "appeals": {
                "cols": appeals["stages"],
                "rows": [{"year": s["name"], "vals": [_int(v) for v in s["data"]]}
                         for s in appeals["series"]],
            },
        },
        "insights": insights,
        "labels": labels,
    }
