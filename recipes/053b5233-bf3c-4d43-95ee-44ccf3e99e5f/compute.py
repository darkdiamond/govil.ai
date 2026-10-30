"""עיצומים כספיים על ליקויי בטיחות: financial sanctions the Ministry of Labour
imposed for workplace-safety violations (mostly construction sites).

One row = one sanction for one violation (`number` is the sanction id). The
`sum` column is the statutory amount; it follows a fixed tariff that is
indexed every year, so amounts are compared to the year's most common
("typical") amount rather than to fixed shekel buckets.

Objection flow: `commissionersdecision` (free text, normalised to rejected /
reduced / cancelled) and `sumafterdecision`; a few cases go on to a committee
(`committeedecision`, `sumaftercommittee`). The "final amount" of a row is the
latest stage's amount.

"Now" is the latest sanction date in the data. Sanctions are published in
batches and back-filled, so trend rules use the latest settled calendar year.

Rankings name only corporate bodies (9-digit registration number starting with
5). Rows with no such number (often "מבצע פרטי", a private builder) are only
aggregated.
"""
import re

import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
OTHER = "אחר"
# Ordered: first match wins. Training records mention "עבודה בגובה" and
# "מנהל עבודה", so training is tested before both.
THEMES = [
    ("עגורני צריח", r"עגורן"),
    ("בדיקת שרשרות ואביזרי הרמה", r"שרשרות|אבזרי הרמה|אביזרי הרמה"),
    ("בדיקת מכונות הרמה", r"מכונת הרמה|מכונת ההרמה|מלגזה|פיגום ממוכן"),
    ("אי קיום צו בטיחות", r"צו בטיחות|צו הבטיחות"),
    ("אי קיום צו שיפור", r"צו שיפור"),
    ("הדרכת עובדים ופנקס הדרכה", r"הדרכה|מדריך|הודרך"),
    ("הודעה למפקח על מנהל עבודה", r"מנהל העבודה|מנהל עבודה"),
    ("עבודה בגובה", r"בגובה|סולם|סולמות|גידור|נפילה"),
]
DECISIONS = [  # normalised commissioner / committee decision, first match wins
    ("ביטול", r"ביט"),
    ("הפחתה", r"הפח"),
    ("דחייה", r"דחי|נדח|^חייה$"),
    ("נמחק", r"נמחק"),
]
NO_DECISION = "ללא החלטת ממונה"
CORP_RE = re.compile(r"^5\d{8}$")
LAG_DAYS = 182
# Typical-tariff tiers: amount / the year's most common amount.
TIERS = [("נמוך מהתעריף הרגיל", 0.0, 0.8),
         ("תעריף רגיל", 0.8, 1.5),
         ("פי 1.5 ומעלה", 1.5, None)]
COUNT_BUCKETS = [(1, 1, "עיצום אחד"), (2, 2, "שניים"), (3, 5, "3 עד 5"),
                 (6, 10, "6 עד 10"), (11, None, "11 ומעלה")]
TOP_N = 10
TARIFF_BAND = 0.15


def _int(n):
    return f"{int(round(n)):,}"


def ils(v):
    v = float(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:,.1f} מיליון ₪"
    return f"{v:,.0f} ₪"


def _pct(x):
    return f"{x * 100:.0f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _num(s):
    return pd.to_numeric(s.str.replace(",", "").str.strip(), errors="coerce")


def _theme(text):
    for name, rx in THEMES:
        if re.search(rx, text):
            return name
    return OTHER


def _decision(text):
    t = text.strip()
    if not t:
        return ""
    for name, rx in DECISIONS:
        if re.search(rx, t):
            return name
    return ""


def _valid_dates(d):
    """Drop typos far in the future: the latest date is invalid while it is
    more than a year after the next-latest distinct date (e.g. 2055)."""
    d = d.where(d.dt.year >= 2000)
    uniq = sorted(d.dropna().unique())
    while len(uniq) > 1 and (uniq[-1] - uniq[-2]) > pd.Timedelta(days=366):
        d = d.where(d != uniq[-1])
        uniq = uniq[:-1]
    return d


def _prepare(df):
    raw_d = pd.to_datetime(df["date"].str.strip().str[:10], errors="coerce", format="%Y-%m-%d")
    out = pd.DataFrame({
        "sid": df["number"].str.strip(),
        "name": df["companyname"].str.replace(r"\s+", " ", regex=True).str.strip(),
        "hp": df["hpnumber"].str.strip(),
        "d": _valid_dates(raw_d),
        "clause": df["volationclause"].str.replace(r"\s+", " ", regex=True).str.strip(),
        "amt": _num(df["sum"]),
        "dec": df["commissionersdecision"].map(_decision),
        "after": _num(df["sumafterdecision"]),
        "red_reason": df["reasonforreduction"].str.replace(r"\s+", "", regex=True),
        "red_pct": _num(df["reductionpercentage"]),
        "com": df["committeedecision"].map(_decision),
        "after_com": _num(df["sumaftercommittee"]),
    })
    out["theme"] = out["clause"].map(_theme)
    out["corp"] = out["hp"].str.match(CORP_RE)
    return out.sort_values(list(out.columns), kind="stable").reset_index(drop=True)


def _final_amount(r):
    amt = r["amt"] if pd.notna(r["amt"]) else 0.0
    if r["com"] == "ביטול":
        return 0.0
    if r["com"] in ("הפחתה", "דחייה") and pd.notna(r["after_com"]):
        return float(r["after_com"])
    if r["dec"] == "ביטול":
        return 0.0
    if r["dec"] == "הפחתה":
        if pd.notna(r["after"]):
            return float(r["after"])
        if pd.notna(r["red_pct"]) and 0 < r["red_pct"] < 1:
            return amt * (1 - r["red_pct"])
    return float(amt)


def _cut(amt, after, stated):
    """Reduction share actually applied (1 - after/amount), rounded to the
    nearest 5%; the stated percentage only when the amounts are missing (the
    stated column has typos such as 0.025 next to a 40% cut)."""
    r = None
    if pd.notna(amt) and amt > 0 and pd.notna(after):
        r = 1 - after / amt
    elif pd.notna(stated):
        r = stated
    if r is None or not (0 < r < 1):
        return None
    r = round(r * 20) / 20
    return r if 0 < r < 1 else None


def _top(series, n=TOP_N):
    s = series.sort_index().sort_values(ascending=False, kind="stable")
    return s.head(n)


def _mode(s):
    vc = s.value_counts().sort_index()
    return float(vc.idxmax()) if len(vc) else None


def typical_tariffs(amt, yr, years):
    """The regular (full) tariff per year. A year's plain mode can land on a
    lower statutory tier (2019 at authoring: 32 rows at the ~57% tier vs 29
    at the full one), so the tariff is chained: anchor on the year with most
    rows, then each neighbouring year takes its most common amount within
    TARIFF_BAND of the adjacent year's tariff (annual indexation is a few %)."""
    pos = amt > 0
    counts = yr[pos].value_counts()
    if counts.empty:
        return {y: None for y in years}
    anchor = int(counts.sort_index().sort_values(ascending=False, kind="stable").index[0])
    out = {anchor: _mode(amt[pos & (yr == anchor)])}

    def walk(seq, prev):
        for y in seq:
            a = amt[pos & (yr == y)]
            if prev is not None:
                a = a[(a >= prev * (1 - TARIFF_BAND)) & (a <= prev * (1 + TARIFF_BAND))]
            m = _mode(a)
            out[y] = m
            prev = m if m is not None else prev
    walk([y for y in years if y > anchor], out[anchor])
    walk([y for y in reversed(years) if y < anchor], out[anchor])
    return out


def settled_year(last):
    y = last.year - 1
    while pd.Timestamp(year=y, month=12, day=31) > last - pd.Timedelta(days=LAG_DAYS):
        y -= 1
    return y


def _tier(ratio):
    if pd.isna(ratio):
        return None
    for name, lo, hi in TIERS:
        if ratio >= lo and (hi is None or ratio < hi):
            return name
    return None


# ---------------------------------------------------------------- insights

def insight_trend(rows, last):
    y = settled_year(last)
    yrs = rows["d"].dt.year
    cur, prev = rows[yrs == y], rows[yrs == y - 1]
    if len(cur) == 0 or len(prev) == 0:
        return None
    ch = (len(cur) - len(prev)) / len(prev)
    if abs(ch) < 0.05:
        trend = "כמעט ללא שינוי במספר העיצומים"
    else:
        trend = f"{'עלייה' if ch > 0 else 'ירידה'} של {abs(ch) * 100:.0f}% במספר העיצומים"
    return (f"ב-{y} הוטלו {_int(len(cur))} עיצומים בסך {ils(cur['amt'].sum())}: "
            f"{trend} לעומת {y - 1} ({_int(len(prev))} עיצומים, {ils(prev['amt'].sum())}).")


def insight_theme(theme_counts, n):
    if theme_counts.empty or n == 0:
        return None
    name, c = theme_counts.index[0], int(theme_counts.iloc[0])
    if name == OTHER or c / n < 0.2:
        return None
    second = ""
    if len(theme_counts) > 1 and theme_counts.index[1] != OTHER:
        second = (f"; אחריה {theme_counts.index[1]} "
                  f"({_pct(theme_counts.iloc[1] / n)})")
    return (f"הליקוי הנפוץ ביותר: {name}, {_int(c)} עיצומים שהם {_pct(c / n)} "
            f"מכלל העיצומים{second}.")


def insight_tariff(tariff):
    ys, ms = tariff["years"], tariff["typical"]
    pairs = [(y, m) for y, m in zip(ys, ms) if m]
    if len(pairs) < 3:
        return None
    (y0, m0), (y1, m1) = pairs[0], pairs[-1]
    if m0 <= 0:
        return None
    ch = (m1 - m0) / m0
    if abs(ch) < 0.03:
        return f"התעריף הנפוץ של עיצום כמעט לא השתנה בין {y0} ל-{y1} ({ils(m1)})."
    word = "עלה" if ch > 0 else "ירד"
    return (f"התעריף הנפוץ של עיצום בודד {word} מ-{ils(m0)} ב-{y0} ל-{ils(m1)} "
            f"ב-{y1} ({abs(ch) * 100:.0f}%); הסכומים מתעדכנים מדי שנה.")


def insight_double(rows):
    dbl = rows[rows["tier"] == TIERS[2][0]]
    known = rows["tier"].notna().sum()
    if known < 100 or len(dbl) < 20:
        return None
    corp_share = dbl["corp"].mean()
    tail = (f", {_pct(corp_share)} מהם לתאגידים" if corp_share >= 0.5 else "")
    return (f"{_int(len(dbl))} עיצומים ({_pct(len(dbl) / known)}) הוטלו בסכום של לפחות "
            f"פי 1.5 מהתעריף הנפוץ באותה שנה{tail}.")


def insight_objections(rows, outcome_counts):
    decided = sum(outcome_counts.values())
    if decided < 50:
        return None
    red, can = outcome_counts.get("הפחתה", 0), outcome_counts.get("ביטול", 0)
    rej = outcome_counts.get("דחייה", 0)
    return (f"ל-{_int(decided)} עיצומים ({_pct(decided / len(rows))}) נרשמה החלטת ממונה: "
            f"{_pct(rej / decided)} נדחו, {_pct(red / decided)} הופחתו ו-{_pct(can / decided)} "
            f"בוטלו.")


def insight_reduction(rows):
    red = rows[(rows["dec"] == "הפחתה") & rows["cut"].notna()]
    if len(red) < 30:
        return None
    pct = red["cut"]
    top = _top(pct.value_counts(), 2)
    if top.empty:
        return None
    reasons = red["red_reason"].str.extract(r"(1[א]?\([א-ת]\)\(\d\))")[0].dropna()
    reason = ""
    if len(reasons) and reasons.value_counts().iloc[0] / len(red) >= 0.5:
        code = reasons.value_counts().sort_index().sort_values(
            ascending=False, kind="stable").index[0]
        reason = f" רוב ההפחתות נומקו בתקנה {code} לתקנות ההפחתה."
    lead = f"{top.index[0] * 100:.0f}%"
    second = (f", ואחריו {top.index[1] * 100:.0f}% ({_int(top.iloc[1])})"
              if len(top) > 1 else "")
    return (f"שיעור ההפחתה הנפוץ הוא {lead} ({_int(top.iloc[0])} עיצומים){second}."
            f"{reason}")


def insight_repeat(rows, top_corp):
    corp = rows[rows["corp"]]
    if len(corp) < 100 or top_corp.empty:
        return None
    per = corp.groupby("hp").size()
    rep = per[per >= 5]
    if len(rep) == 0:
        return None
    share = per[per >= 5].sum() / len(corp)
    return (f"{_int(len(rep))} תאגידים ספגו 5 עיצומים ומעלה כל אחד, ויחד הם אחראים ל-"
            f"{_pct(share)} מעיצומי התאגידים. בראש הרשימה {top_corp.index[0]} "
            f"עם {_int(top_corp.iloc[0])} עיצומים.")


def insight_private(rows):
    n = len(rows)
    priv = int((~rows["corp"]).sum())
    if n == 0 or priv / n < 0.03:
        return None
    named_private = rows.loc[~rows["corp"], "name"].str.contains("פרטי").mean()
    tail = (f"; {_pct(named_private)} מהם רשומים כמבצע בנייה פרטי" if named_private >= 0.2 else "")
    return (f"{_int(priv)} עיצומים ({_pct(priv / n)}) הוטלו על מי שאינו תאגיד רשום{tail}.")


def insight_committee(rows):
    com = rows[rows["com"] != ""]
    if len(com) < 10:
        return None
    rej = int((com["com"] == "דחייה").sum())
    return (f"{_int(len(com))} עיצומים הגיעו גם להחלטת ועדה לאחר החלטת הממונה; "
            f"ב-{_int(rej)} מהם הוועדה דחתה את הבקשה.")


# ---------------------------------------------------------------- compute

def compute(frames):
    rows = _prepare(frames["main"])
    bad_date = int(rows["d"].isna().sum())
    rows = rows.dropna(subset=["d"]).reset_index(drop=True)
    first, last = rows["d"].min(), rows["d"].max()
    y0, y1 = int(first.year), int(last.year)
    years = list(range(y0, y1 + 1))
    yr = rows["d"].dt.year
    rows["final"] = rows.apply(_final_amount, axis=1)
    rows["cut"] = [_cut(a, f, p) for a, f, p in zip(rows["amt"], rows["after"], rows["red_pct"])]
    no_amt = int(rows["amt"].isna().sum())
    rows["amt"] = rows["amt"].fillna(0.0)

    # Typical tariff per year, and each row's tier against it.
    typical = typical_tariffs(rows["amt"], yr, years)
    rows["ratio"] = [a / typical[y] if typical.get(y) and a > 0 else None
                     for a, y in zip(rows["amt"], yr)]
    rows["tier"] = rows["ratio"].map(_tier)

    # --- yearly
    by_n, by_amt = rows.groupby(yr).size(), rows.groupby(yr)["amt"].sum()
    yearly = {"years": [str(y) for y in years],
              "count": [int(by_n.get(y, 0)) for y in years],
              "millions": [round(float(by_amt.get(y, 0)) / 1e6, 2) for y in years]}

    # --- month x year heatmap
    mc = rows.groupby([yr, rows["d"].dt.month]).size()
    cells = [[m - 1, i, int(mc.get((y, m), 0))] for i, y in enumerate(years)
             for m in range(1, 13)
             if not (y == y1 and m > last.month)]
    heat = {"months": MONTHS_SHORT, "years": [str(y) for y in years], "cells": cells,
            "max": int(mc.max()) if len(mc) else 1}

    # --- themes
    theme_counts = _top(rows["theme"].value_counts(), 20)
    theme_amt = rows.groupby("theme")["amt"].sum()
    themes = {"names": list(theme_counts.index),
              "values": [int(v) for v in theme_counts],
              "millions": [round(float(theme_amt.get(t, 0)) / 1e6, 2) for t in theme_counts.index]}
    ty = rows.groupby([yr, "theme"]).size()
    theme_year = {
        "years": [str(y) for y in years],
        "series": [{"name": t,
                    "data": [round(100 * ty.get((y, t), 0) / by_n.get(y, 1), 1)
                             if by_n.get(y, 0) else 0 for y in years]}
                   for t in theme_counts.index],
    }

    # --- tariff
    tier_names = [t for t, _, _ in TIERS]
    tc = rows.groupby([yr, "tier"]).size()
    tariff = {"years": [str(y) for y in years],
              "typical": [int(typical[y]) if typical.get(y) else None for y in years],
              "series": [{"name": t, "data": [int(tc.get((y, t), 0)) for y in years]}
                         for t in tier_names]}

    # --- entity type per year
    ent_names = ["תאגיד רשום", "מבצע פרטי או ללא מספר תאגיד"]
    ec = rows.groupby([yr, rows["corp"]]).size()
    entity = {"years": [str(y) for y in years],
              "series": [{"name": ent_names[0], "data": [int(ec.get((y, True), 0)) for y in years]},
                         {"name": ent_names[1], "data": [int(ec.get((y, False), 0)) for y in years]}]}

    # --- commissioner decisions per year
    out_names = ["דחייה", "הפחתה", "ביטול"]
    dc = rows.groupby([yr, "dec"]).size()
    outcome_counts = {o: int((rows["dec"] == o).sum()) for o in out_names}
    objections = {"years": [str(y) for y in years],
                  "series": [{"name": o, "data": [int(dc.get((y, o), 0)) for y in years]}
                             for o in out_names]
                  + [{"name": NO_DECISION,
                      "data": [int(by_n.get(y, 0)) - sum(int(dc.get((y, o), 0)) for o in out_names)
                               for y in years]}]}

    # --- reduction percentage distribution
    red = rows[(rows["dec"] == "הפחתה") & rows["cut"].notna()]
    rp = red["cut"].value_counts().sort_index()
    rp_main = rp[rp >= 3]
    rest = int(rp[rp < 3].sum())
    reduction = {"names": [f"{v * 100:g}%" for v in rp_main.index] + ([OTHER] if rest else []),
                 "values": [int(v) for v in rp_main] + ([rest] if rest else []),
                 "base": int(len(red))}

    # --- corporations
    corp = rows[rows["corp"]]
    # Display name per registration number: its most frequent spelling.
    nm = (corp.groupby(["hp", "name"]).size().reset_index(name="c")
          .sort_values(["hp", "c", "name"], ascending=[True, False, True], kind="stable")
          .drop_duplicates("hp").set_index("hp")["name"])
    per_corp = corp.groupby("hp").size()
    top_hp = _top(per_corp)
    corp_amt = corp.groupby("hp")["amt"].sum()
    top_corp = pd.Series([int(v) for v in top_hp.values], index=[nm[h] for h in top_hp.index])
    companies = {"names": list(top_corp.index), "values": [int(v) for v in top_corp],
                 "millions": [round(float(corp_amt[h]) / 1e6, 2) for h in top_hp.index]}
    rep_counts = []
    for lo, hi, label in COUNT_BUCKETS:
        sel = per_corp >= lo if hi is None else (per_corp >= lo) & (per_corp <= hi)
        rep_counts.append(int(sel.sum()))
    repeat = {"names": [b[2] for b in COUNT_BUCKETS], "values": rep_counts}

    # --- insights
    rules = [
        ("trend", insight_trend(rows, last)),
        ("theme", insight_theme(theme_counts, len(rows))),
        ("tariff", insight_tariff(tariff)),
        ("objections", insight_objections(rows, outcome_counts)),
        ("reduction", insight_reduction(rows)),
        ("repeat", insight_repeat(rows, top_corp)),
        ("double", insight_double(rows)),
        ("private", insight_private(rows)),
        ("committee", insight_committee(rows)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # --- KPIs
    total, final_total = float(rows["amt"].sum()), float(rows["final"].sum())
    sy = settled_year(last)
    sy_n = int((yr == sy).sum())
    sy_prev = int((yr == sy - 1).sum())
    sy_tone = "brand"
    if sy_prev:
        ch = (sy_n - sy_prev) / sy_prev
        sy_tone = "warn" if ch >= 0.10 else "info" if ch <= -0.10 else "brand"
    cut = 1 - final_total / total if total else 0
    n_corp = int(per_corp.size)
    kpis = {
        "count": {"value": len(rows), "display": _int(len(rows)), "tone": "brand",
                  "label": f"עיצומים, {y0} עד {y1}"},
        "total": {"value": total, "display": f"{total / 1e6:,.1f}", "tone": "brand",
                  "label": "סך העיצומים שהוטלו (מיליוני ₪)"},
        "settled": {"value": sy_n, "display": _int(sy_n), "tone": sy_tone,
                    "label": f"עיצומים ב-{sy}" + (f" (לעומת {_int(sy_prev)} ב-{sy - 1})"
                                                   if sy_prev else "")},
        "corps": {"value": n_corp, "display": _int(n_corp), "tone": "brand",
                  "label": "תאגידים שנקנסו"},
        "final": {"value": final_total, "display": f"{final_total / 1e6:,.1f}",
                  "tone": "info" if cut >= 0.05 else "brand",
                  "label": (f"סכום לאחר החלטות ממונה וועדה (מיליוני ₪, הפחתה של {_pct(cut)})")},
        "typical": {"value": tariff["typical"][-1],
                    "display": _int(tariff["typical"][-1]) if tariff["typical"][-1] else "0",
                    "tone": "brand", "label": f"התעריף הנפוץ לעיצום ב-{y1} (₪)"},
    }

    theme_tbl = {"cols": [s["name"] for s in theme_year["series"]],
                 "rows": [{"year": y, "vals": [f"{s['data'][i]:g}%" for s in theme_year["series"]]}
                          for i, y in enumerate(theme_year["years"])]}
    labels = {
        "lede": (f"{_int(len(rows))} עיצומים כספיים שהטיל משרד העבודה בגין ליקויי בטיחות, "
                 f"רובם באתרי בנייה, מ-{d_he(first)} ועד {d_he(last)}, בסך כולל של {ils(total)}. "
                 f"העיצומים הוטלו על {_int(n_corp)} תאגידים ועל מבצעי בנייה פרטיים."),
        "data_note": " ".join(x for x in [
            (f"רשומות עם תאריך חסר או שגוי ({_int(bad_date)}) אינן נכללות בעמוד." if bad_date else ""),
            (f"רשומות ללא סכום ({_int(no_amt)}) נספרות כעיצום אך אינן נכללות בסכומים."
             if no_amt else ""),
        ] if x),
        "partial": (f"העיצום האחרון במאגר מ-{d_he(last)}. העיצומים מתפרסמים במנות ומתווספים "
                    f"בדיעבד, ולכן השנים שאחרי {sy} עדיין חלקיות."),
        "yearly_aria": f"תרשים משולב: מספר העיצומים (עמודות) וסכומם במיליוני ₪ (קו) לפי שנה, {y0} עד {y1}.",
        "heat_aria": f"מפת חום: מספר העיצומים לפי חודש ושנה, {y0} עד {y1}.",
        "themes_aria": f"תרשים עמודות אופקי: מספר העיצומים לפי סוג הליקוי, {len(themes['names'])} סוגים.",
        "theme_year_aria": f"תרשים עמודות מוערמות: שיעור כל סוג ליקוי מתוך העיצומים בכל שנה, {y0} עד {y1}.",
        "tariff_aria": (f"תרשים משולב: מספר העיצומים לפי דרגת סכום (עמודות מוערמות) והתעריף "
                        f"הנפוץ בשקלים (קו) לפי שנה, {y0} עד {y1}."),
        "entity_aria": f"תרשים עמודות מוערמות: עיצומים על תאגידים ועל מבצעים פרטיים לפי שנה, {y0} עד {y1}.",
        "obj_aria": f"תרשים עמודות מוערמות: החלטות הממונה על העיצומים לפי שנה, {y0} עד {y1}.",
        "red_aria": f"תרשים עמודות: מספר העיצומים לפי שיעור ההפחתה, מתוך {_int(reduction['base'])} הפחתות.",
        "comp_aria": f"תרשים עמודות אופקי: {len(companies['names'])} התאגידים עם מספר העיצומים הגבוה ביותר.",
        "repeat_aria": f"תרשים עמודות: מספר התאגידים לפי כמות העיצומים שספגו, מתוך {_int(n_corp)} תאגידים.",
        "tariff_note": (f"סכום העיצום נקבע לפי תעריף קבוע לכל סוג הפרה ומתעדכן מדי שנה. "
                        f"כל עיצום מסווג לפי היחס בינו לבין הסכום הנפוץ באותה שנה."),
        "theme_note": "סוג הליקוי נגזר מנוסח סעיף ההפרה; נוסחים שונים של אותו סעיף אוחדו.",
        "obj_note": (f"{_int(sum(outcome_counts.values()))} עיצומים שלגביהם נרשמה החלטת ממונה "
                     f"(דחייה, הפחתה או ביטול)."),
        "red_note": f"שיעור ההפחתה שנרשם ל-{_int(reduction['base'])} עיצומים שהופחתו.",
        "comp_note": ("תאגידים בלבד (מספר רישום בן 9 ספרות המתחיל ב-5), לפי מספר הרישום. "
                      "מבצעים פרטיים אינם מדורגים."),
        "repeat_note": f"התפלגות {_int(n_corp)} התאגידים לפי מספר העיצומים שהוטלו על כל אחד.",
        "entity_note": "תאגיד רשום הוא רשומה עם מספר תאגיד בן 9 ספרות המתחיל ב-5.",
    }
    return {
        "agent_data": {
            "summary_he": (f"איתור עיצומים כספיים על ליקויי בטיחות לפי שם חברה או ח.פ.: "
                           f"{_int(len(rows))} עיצומים בסך {total / 1e6:,.1f} מיליון ₪, {y0} עד {y1}."),
            "dataset_kind": "registry",
            "suggested_tags": ["עיצומים כספיים", "בטיחות בעבודה", "אתרי בנייה",
                               "עבודה בגובה", "אכיפה", "משרד העבודה"],
            "related_ids": ["3ab09979-7d64-4402-ae51-5fa320a37a56",
                            "c0beab05-9061-4dad-868c-40142260d35f",
                            "2fe07949-9538-4891-9de7-50a352bcbd80",
                            "bddf37d6-5300-4179-bc0b-f2577fbc3a30",
                            "7d475608-8609-407e-b535-72a72e24b375"],
            "temporal_coverage": f"{first.strftime('%Y-%m-%d')}/{last.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "yearly": yearly, "heat": heat, "themes": themes, "theme_year": theme_year,
            "tariff": tariff, "entity": entity, "objections": objections,
            "reduction": reduction, "companies": companies, "repeat": repeat,
        },
        "flags": {"reduction": reduction["base"] >= 20},
        "tables": {
            "years": [{"year": y, "n": _int(c), "amt": ils(m * 1e6)}
                      for y, c, m in zip(yearly["years"], yearly["count"], yearly["millions"])],
            "themes": [{"name": n, "n": _int(v), "amt": ils(m * 1e6)}
                       for n, v, m in zip(themes["names"], themes["values"], themes["millions"])],
            "theme_year": theme_tbl,
            "tariff": [{"year": y, "typ": ils(t) if t else "",
                        "vals": [_int(s["data"][i]) for s in tariff["series"]]}
                       for i, (y, t) in enumerate(zip(tariff["years"], tariff["typical"]))],
            "tier_cols": tier_names,
            "entity": {"cols": [s["name"] for s in entity["series"]],
                       "rows": [{"year": y, "vals": [_int(s["data"][i]) for s in entity["series"]]}
                                for i, y in enumerate(entity["years"])]},
            "objections": {"cols": [s["name"] for s in objections["series"]],
                           "rows": [{"year": y,
                                     "vals": [_int(s["data"][i]) for s in objections["series"]]}
                                    for i, y in enumerate(objections["years"])]},
            "reduction": [{"name": n, "v": _int(v)}
                          for n, v in zip(reduction["names"], reduction["values"])],
            "companies": [{"name": n, "n": _int(v), "amt": ils(m * 1e6)}
                          for n, v, m in zip(companies["names"], companies["values"],
                                             companies["millions"])],
            "repeat": [{"name": n, "v": _int(v)} for n, v in zip(repeat["names"], repeat["values"])],
        },
        "insights": insights,
        "labels": labels,
    }
