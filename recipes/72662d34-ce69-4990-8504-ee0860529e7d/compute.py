"""רופאים וטרינרים בישראל — the Ministry of Agriculture register of licensed vets.

One row per licence (~3.8k): licence type, licence number, last/first name,
licence date and up to three recognised specialties, each with the year it
was recognised. The whole register is republished on each update, so the page
is a snapshot; "now" is the latest licence date in the register (its data
vintage), never the wall clock. That year is partial unless the date reaches
late December.

Licence numbers are individual identifiers and never reach the page. Names are
used only in aggregate (most common surnames / first names), as on the CPA and
notary pages. Rows without a parseable licence date (an upstream placeholder
record) are excluded and disclosed.

Older licences carry a year only — recorded as 1 January. The year from which
real day-level dates begin is detected from the data (`_precise_from`), and the
month/day views use only those years.

Specialty names are truncated at 30 characters upstream and carry doubled
spaces; they are normalised to a display name (known truncations completed,
typos fixed; unknown names pass through) and grouped into fields with a
fallback "אחר" for names not in the map.
"""
import re

import pandas as pd

TOP_SPECS = 12
TOP_NAMES = 15
TOP_DAYS = 10
HEAT_YEARS = 15
DECADE_FROM = 1960
BIG_DAY = 10
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
GAP_BUCKETS = [("לפני הרישיון", None, -1), ("0–4", 0, 4), ("5–9", 5, 9), ("10–14", 10, 14),
               ("15–19", 15, 19), ("20 ומעלה", 20, None)]

SPEC_FIX = {
    "מיקרוביולוגיה קלינית (וירולוגי": "וירולוגיה קלינית",
    "מיקרוביולוגיה קלינית (בקטריולו": "בקטריולוגיה קלינית",
    "מיקרוביולוגיה קלינית (בקטריול.": "בקטריולוגיה קלינית",
    "מיקרוביולוגיה קלינית (פרזיטולו": "פרזיטולוגיה קלינית",
    "מיקרוביולוגיה(מיקולוגיה)": "מיקולוגיה קלינית",
    "רפואה פנימית של חיות בית קטנו": "רפואה פנימית של חיות בית קטנות",
    "התנהגות חיות בית קטנות- לצרכי": "התנהגות חיות בית קטנות",
    "מדעי הרפואה באפידמיולוגי": "מדעי הרפואה באפידמיולוגיה",
    "דטרמולגיה": "דרמטולוגיה",
    "טיפול נימרץ": "טיפול נמרץ",
    "רביה ויילוד": "רבייה וילוד",
}
PUBLIC, FARM, CLINIC, LAB, WILD, OTHER = (
    "בריאות הציבור ומזון", "חיות משק", "רפואה קלינית", "מעבדה ומדעי יסוד",
    "חיות בר ורווחה", "אחר")
FAMILY_ORDER = [CLINIC, PUBLIC, FARM, LAB, WILD, OTHER]
# Index into window.GOVIL_PALETTE, picked so neighbouring fields stay distinct.
FAMILY_CI = {CLINIC: 0, PUBLIC: 1, FARM: 2, LAB: 6, WILD: 5, OTHER: 7}
FAMILY = {
    "בריאות ציבור וטרינרית": PUBLIC, "היגיינה של מזון": PUBLIC, "בטיחות מזון": PUBLIC,
    "מדעי הרפואה באפידמיולוגיה": PUBLIC, "רפואה וטרינרית טרופית": PUBLIC,
    "אקולוגיה וטרינרית": PUBLIC,
    "רפואת עופות": FARM, "רפואת בקר": FARM, "רפואת צאן": FARM, "רפואת דגים": FARM,
    "רפואת חזירים": FARM, "רפואת דבורים": FARM, "רפואת חיות פרווה": FARM,
    "מחלות עטין": FARM, "רבייה וילוד": FARM, "רפואת סוסים": FARM,
    "קליני": CLINIC, "כירורגיה": CLINIC, "רפואה פנימית של חיות בית קטנות": CLINIC,
    "רפואת כלבים וחתולים": CLINIC, "הדמיה": CLINIC, "רדיולוגיה": CLINIC,
    "הרדמה וטרינרית": CLINIC, "טיפול נמרץ": CLINIC, "נוירולוגיה ונוירוכירורגיה": CLINIC,
    "אופטלמולוגיה וטרינרית": CLINIC, "דרמטולוגיה": CLINIC, "קרדיולוגיה": CLINIC,
    "אונקולוגיה וטרינרית": CLINIC, "רפואת שיניים של חיות בית קטנות": CLINIC,
    "התנהגות חיות בית קטנות": CLINIC, "רפואת ציפורי נוי": CLINIC,
    "רפואת חיות מעבדה": LAB, "פתולוגיה": LAB, "פתולוגיה קלינית": LAB,
    "טוקסיקולוגיה וטרינרית": LAB, "פיזיולוגיה": LAB, "פרמקולוגיה קלינית": LAB,
    "אנטומיה": LAB, "אימונולוגיה ואלרגולוגיה": LAB, "וירולוגיה קלינית": LAB,
    "בקטריולוגיה קלינית": LAB, "פרזיטולוגיה קלינית": LAB, "מיקולוגיה קלינית": LAB,
    "רפואת חיות בר וחיות גני חיות": WILD, "רווחת בעלי חיים": WILD,
}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _spec_name(s):
    s = re.sub(r"\s+", " ", s.strip())
    return SPEC_FIX.get(s, s)


def _family(s):
    if s in FAMILY:
        return FAMILY[s]
    if s.startswith("מיקרוביולוגיה"):
        return LAB
    return OTHER


def _ranked(s):
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _prepare(raw):
    df = pd.DataFrame({
        "row": range(len(raw)),
        "type": raw["סוג_רשיון"].str.strip().replace("", "לא ידוע").values,
        "first": raw["שם_פרטי"].str.strip().values,
        "last": raw["שם_משפחה"].str.strip().values,
        "date": pd.to_datetime(raw["תאריך_רשיון"].str.strip(), errors="coerce",
                               format="%d/%m/%Y").values,
    })
    specs = []
    for k in ("1", "2", "3"):
        s = pd.DataFrame({
            "row": range(len(raw)),
            "spec": raw[f"מומחיות_{k}"].map(_spec_name).values,
            "year": pd.to_numeric(raw[f"שנת_מומחיות_{k}"].str.strip(), errors="coerce").values,
        })
        specs.append(s[s["spec"] != ""])
    sp = pd.concat(specs, ignore_index=True)
    # One vet listing the same specialty twice counts once.
    sp = (sp.sort_values(["row", "spec", "year"], na_position="last")
          .drop_duplicates(["row", "spec"]).reset_index(drop=True))
    sp["family"] = sp["spec"].map(_family)
    return df, sp


def _precise_from(dated):
    """First year after the last year (≥10 licences) whose dates are mostly 1 January."""
    jan1 = (dated["date"].dt.month == 1) & (dated["date"].dt.day == 1)
    g = pd.DataFrame({"y": dated["year"], "j": jan1}).groupby("y")["j"].agg(["size", "mean"])
    coarse = g[(g["size"] >= 10) & (g["mean"] >= 0.5)]
    if coarse.empty:
        return int(g.index.min())
    return int(coarse.index.max()) + 1


# ---------------------------------------------------------------- insights

def insight_peak(per_year, last_full):
    full = per_year[per_year.index <= last_full]
    if len(full) < 10 or last_full not in full.index:
        return None
    peak = int(full.idxmax())
    pv, lv = int(full[peak]), int(full[last_full])
    prev = int(full.get(last_full - 1, 0))
    if peak == last_full:
        tail = ""
        if prev:
            ch = lv / prev - 1
            tail = (f", {pct(abs(ch) * 100, 0)} {'יותר' if ch > 0 else 'פחות'} מב-{last_full - 1} ({n(prev)})"
                    if round(abs(ch) * 100) else f", ללא שינוי לעומת {last_full - 1}")
        return f"{last_full} היא שנת השיא ברישוי וטרינרים: {n(lv)} רישיונות חדשים{tail}."
    drop = 1 - lv / pv
    if abs(drop) < 0.1:
        return (f"שנת השיא ברישוי הייתה {peak} ({n(pv)} רישיונות); ב-{last_full} ניתנו "
                f"{n(lv)} — קרוב לשיא.")
    return (f"שנת השיא ברישוי הייתה {peak}, עם {n(pv)} רישיונות חדשים; ב-{last_full} ניתנו "
            f"{n(lv)} — {pct(drop * 100, 0)} פחות מהשיא.")


def insight_ytd(dated, ref, partial):
    if not partial:
        return None
    y = ref.year
    cur = dated[dated["year"] == y]
    md = (dated["date"].dt.month * 100 + dated["date"].dt.day) <= (ref.month * 100 + ref.day)
    prev = dated[(dated["year"] == y - 1) & md]
    full_prev = int((dated["year"] == y - 1).sum())
    if len(prev) < 20:
        return None
    c, p = len(cur), len(prev)
    chg = c / p - 1
    if abs(chg) < 0.05:
        trend = f"בדומה לתקופה המקבילה ב-{y - 1} ({n(p)})"
    else:
        trend = (f"{pct(abs(chg) * 100, 0)} {'יותר' if chg > 0 else 'פחות'} מבתקופה המקבילה "
                 f"ב-{y - 1} ({n(p)}, מתוך {n(full_prev)} בכל השנה)")
    return f"מתחילת {y} ועד {d_he(ref)} ניתנו {n(c)} רישיונות חדשים — {trend}."


def insight_decades(dec_counts, last_full):
    full = [d for d in dec_counts.index if d >= DECADE_FROM and d + 9 <= last_full]
    if len(full) < 2:
        return None
    a, b = full[-1], full[-2]
    va, vb = int(dec_counts[a]), int(dec_counts[b])
    if vb == 0:
        return None
    ch = va / vb - 1
    if abs(ch) < 0.05:
        return (f"בשנות ה-{a} ניתנו {n(va)} רישיונות — בדומה לשנות ה-{b} ({n(vb)}).")
    return (f"בשנות ה-{a} ניתנו {n(va)} רישיונות, {'עלייה' if ch > 0 else 'ירידה'} של "
            f"{pct(abs(ch) * 100, 0)} לעומת שנות ה-{b} ({n(vb)}).")


def insight_season(month_counts, pf, last):
    tot = int(month_counts.sum())
    if tot < 200:
        return None
    top = _ranked(month_counts).head(2)
    share = top.sum() / tot
    if share < 0.3:
        return None
    (m1, v1), (m2, v2) = list(top.items())
    return (f"הרישוי מרוכז בעונות: מאז {pf} ניתנו {pct(share * 100, 0)} מהרישיונות בחודשים "
            f"{MONTHS_HE[m1 - 1]} ({n(v1)}) ו{MONTHS_HE[m2 - 1]} ({n(v2)}), לעומת "
            f"{pct(200 / 12, 0)} אילו היו מתפזרים שווה בין החודשים.")


def insight_batch(day_counts, pf):
    tot = int(day_counts.sum())
    if tot < 200 or day_counts.empty:
        return None
    day, v = day_counts.index[0], int(day_counts.iloc[0])
    big = day_counts[day_counts >= BIG_DAY]
    if v < BIG_DAY:
        return None
    return (f"רישיונות ניתנים במקבצים: ב-{d_he(day)} לבדו קיבלו {n(v)} וטרינרים רישיון. "
            f"מאז {pf}, {pct(big.sum() / tot * 100, 0)} מהרישיונות ניתנו ב-{n(len(big))} ימים "
            f"שבכל אחד מהם ניתנו {BIG_DAY} רישיונות ומעלה, מתוך {n(len(day_counts))} ימי רישוי.")


def insight_specialists(n_spec, n_multi, total, spec_counts):
    if total == 0 or n_spec == 0 or spec_counts.empty:
        return None
    lead, lv = spec_counts.index[0], int(spec_counts.iloc[0])
    s = (f"ל-{n(n_spec)} וטרינרים ({pct(n_spec / total * 100)}) רשומה מומחיות מוכרת"
         + (f", ול-{n(n_multi)} מהם יותר ממומחיות אחת" if n_multi else ""))
    if len(spec_counts) > 1 and lv >= 1.5 * int(spec_counts.iloc[1]):
        s += (f". המומחיות הנפוצה ביותר היא {lead}, עם {n(lv)} בעלי מומחיות "
              f"({pct(lv / int(spec_counts.sum()) * 100, 0)} מכלל המומחיות הרשומות)")
    return s + "."


def insight_shift(fam_dec, last_full):
    decs = [d for d in fam_dec.index if d + 9 <= last_full and fam_dec.loc[d].sum() >= 30]
    if len(decs) < 2:
        return None
    a, b = decs[-1], decs[0]
    sa = fam_dec.loc[a] / fam_dec.loc[a].sum()
    sb = fam_dec.loc[b] / fam_dec.loc[b].sum()
    la = _ranked(sa).index[0]
    lb = _ranked(sb).index[0]
    if la != lb:
        return (f"מוקד ההתמחות השתנה: בשנות ה-{b} התחום המוביל בהכרה במומחיות היה {lb} "
                f"({pct(sb[lb] * 100, 0)} מהמומחיות שהוכרו), ובשנות ה-{a} — {la} "
                f"({pct(sa[la] * 100, 0)}).")
    diff = (sa - sb)
    mover = _ranked(diff.abs()).index[0]
    if abs(diff[mover]) < 0.1:
        return None
    return (f"{la} מוביל בהכרה במומחיות גם בשנות ה-{b} וגם בשנות ה-{a}; חלקו של התחום "
            f"{mover} {'עלה' if diff[mover] > 0 else 'ירד'} מ-{pct(sb[mover] * 100, 0)} "
            f"ל-{pct(sa[mover] * 100, 0)}.")


def insight_gap(gaps):
    g = gaps.dropna()
    if len(g) < 50:
        return None
    s = (f"עד להכרה במומחיות עוברות בחציון {int(g.median())} שנים מקבלת הרישיון; "
         f"{pct((g >= 15).mean() * 100, 0)} מהמומחיות הוכרו 15 שנה ומעלה לאחר הרישוי")
    neg = int((g < 0).sum())
    if neg:
        s += f", ו-{n(neg)} הוכרו עוד לפני קבלת הרישיון בישראל"
    return s + "."


def insight_precision(dated, pf):
    pre = dated[dated["year"] < pf]
    if len(pre) < 50:
        return None
    j = ((pre["date"].dt.month == 1) & (pre["date"].dt.day == 1)).mean()
    return (f"ברישיונות שניתנו לפני {pf} רשומה בפועל רק שנת הרישוי: {pct(j * 100, 0)} מהם "
            f"מתוארכים ל-1 בינואר. לכן התפלגות החודשים והימים בעמוד זה מבוססת על "
            f"הרישיונות מ-{pf} ואילך.")


def insight_surname(surnames, total):
    if len(surnames) < 2:
        return None
    (a, va), (b, vb) = list(surnames.items())[:2]
    if va < 1.3 * vb:
        return None
    return (f"שם המשפחה הנפוץ ביותר במרשם הוא {a} ({n(va)} וטרינרים, "
            f"{pct(va / total * 100)}), ואחריו {b} ({n(vb)}).")


def insight_types(type_counts):
    if len(type_counts) < 2:
        return None
    parts = [f"{t} — {n(v)}" for t, v in type_counts.items()]
    return "סוגי הרישיון במרשם: " + "; ".join(parts) + "."


def insight_missing(n_missing, total_rows):
    if n_missing == 0:
        return None
    word = "רשומה אחת" if n_missing == 1 else f"{n(n_missing)} רשומות"
    return (f"{word} במאגר ללא תאריך רישיון תקין ({pct(n_missing / total_rows * 100)}) אינן נכללות "
            f"בעמוד זה." if n_missing > 1 else
            f"{word} במאגר ללא תאריך רישיון תקין אינה נכללת בעמוד זה.")


def _bucket(v):
    for lab, lo, hi in GAP_BUCKETS:
        if (lo is None or v >= lo) and (hi is None or v <= hi):
            return lab
    return GAP_BUCKETS[-1][0]


def _dec_label(d):
    return f"לפני {DECADE_FROM}" if d < DECADE_FROM else f"שנות ה-{d}"


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["vets"]
    df_all, sp_all = _prepare(raw)
    total_rows = len(df_all)
    df = df_all.dropna(subset=["date"]).copy()
    n_missing = total_rows - len(df)
    df["year"] = df["date"].dt.year.astype(int)
    valid_rows = set(df["row"])
    sp = sp_all[sp_all["row"].isin(valid_rows)].copy()
    total = len(df)

    ref = df["date"].max()
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = ref_year - 1 if partial else ref_year
    first_year = int(df["year"].min())
    pf = _precise_from(df)

    type_counts = _ranked(df["type"].value_counts())
    sole_type = type_counts.index[0] if len(type_counts) == 1 else None

    # Specialty per vet.
    spec_rows = sp.groupby("row").size()
    has_spec = df["row"].map(spec_rows).fillna(0).astype(int)
    df["nspec"] = has_spec.values
    n_spec = int((df["nspec"] > 0).sum())
    n_multi = int((df["nspec"] > 1).sum())

    # Licences per year, split by specialty.
    years = list(range(first_year, ref_year + 1))
    with_s = df[df["nspec"] > 0].groupby("year").size().reindex(years, fill_value=0)
    without = df[df["nspec"] == 0].groupby("year").size().reindex(years, fill_value=0)
    per_year = (with_s + without)
    per_year.index = per_year.index.astype(int)

    # Decades.
    dec = (df["year"] // 10 * 10)
    dec = dec.where(dec >= DECADE_FROM, DECADE_FROM - 10)
    dec_counts = dec.value_counts().sort_index()
    dec_spec = df[df["nspec"] > 0].groupby(dec[df["nspec"] > 0]).size().reindex(dec_counts.index, fill_value=0)
    decs = list(dec_counts.index)
    dec_labels = [_dec_label(d) for d in decs]

    # Year-to-date cumulative: ref year vs the two before it.
    cum_series = []
    for y in [ref_year, ref_year - 1, ref_year - 2]:
        sub = df[df["year"] == y]
        if sub.empty and y != ref_year:
            continue
        mc = sub.groupby(sub["date"].dt.month).size().reindex(range(1, 13), fill_value=0).cumsum()
        data = [int(v) for v in mc.values]
        if y == ref_year:
            data = [v if i + 1 <= ref.month else None for i, v in enumerate(data)]
        cum_series.append({"name": str(y), "data": data})

    # Precise-date views (years ≥ pf).
    pdf = df[df["year"] >= pf]
    months = pdf.groupby(pdf["date"].dt.month).size().reindex(range(1, 13), fill_value=0)
    day_counts = _ranked(pdf.groupby("date").size())
    top_days = day_counts.head(TOP_DAYS)
    hy = list(range(max(pf, ref_year - HEAT_YEARS + 1), ref_year + 1))
    hd = pdf[pdf["year"].isin(hy)]
    hm = hd.groupby([hd["year"], hd["date"].dt.month]).size()
    cells = []
    for yi, y in enumerate(hy):
        for m in range(1, 13):
            if y == ref_year and m > ref.month:
                continue
            cells.append([m - 1, yi, int(hm.get((y, m), 0))])

    # Specialties.
    spec_counts = _ranked(sp["spec"].value_counts())
    top_specs = list(spec_counts.head(TOP_SPECS).index)
    other_specs = spec_counts.iloc[TOP_SPECS:]
    spec_names = top_specs + (["אחר"] if len(other_specs) else [])
    spec_vals = [int(spec_counts[s]) for s in top_specs] + ([int(other_specs.sum())] if len(other_specs) else [])
    spec_fams = [_family(s) for s in top_specs] + ([OTHER] if len(other_specs) else [])
    fam_counts = sp["family"].value_counts()
    fams = [f for f in FAMILY_ORDER if f in fam_counts.index]

    # Specialty recognitions by decade of recognition, by field.
    spy = sp[(sp["year"] >= 1900) & (sp["year"] <= ref_year)].copy()
    spy["dec"] = (spy["year"].astype(int) // 10 * 10)
    fam_dec = (spy.groupby(["dec", "family"]).size().unstack(fill_value=0)
               .reindex(columns=fams, fill_value=0).sort_index())
    fdecs = list(fam_dec.index)

    # Licence → specialty gap.
    lic_year = df.set_index("row")["year"]
    spy["gap"] = spy["year"] - spy["row"].map(lic_year)
    gaps = spy["gap"]
    gap_b = gaps.dropna().map(_bucket).value_counts().reindex([b[0] for b in GAP_BUCKETS], fill_value=0)

    # Spec share by licence decade.
    spec_share = [round(float(dec_spec[d] / dec_counts[d] * 100), 1) if dec_counts[d] else 0 for d in decs]

    surnames = _ranked(df.loc[df["last"] != "", "last"].value_counts())
    recent = df[(df["first"] != "") & (df["year"] >= ref_year - 9)]
    firsts = _ranked(recent["first"].value_counts())

    charts = {
        "years": {"x": [str(y) for y in years],
                  "with": [int(v) for v in with_s.values],
                  "without": [int(v) for v in without.values],
                  "zoom_from": years.index(1980) if 1980 in years else 0},
        "decades": {"x": dec_labels, "values": [int(dec_counts[d]) for d in decs],
                    "share": spec_share},
        "cumulative": {"x": MONTHS_SHORT, "series": cum_series},
        "months": {"x": MONTHS_SHORT, "values": [int(v) for v in months.values]},
        "heat": {"x": MONTHS_SHORT, "y": [str(y) for y in hy], "cells": cells,
                 "max": max([c[2] for c in cells] or [1])},
        "days": {"names": [d_he(d) for d in top_days.index],
                 "values": [int(v) for v in top_days.values]},
        "specshare": {"names": ["ללא מומחיות רשומה", "מומחיות אחת", "שתי מומחיות ומעלה"],
                      "values": [total - n_spec, n_spec - n_multi, n_multi],
                      "colors": ["#c3cfe7", "#0068f5", "#0b3668"]},
        "specs": {"names": spec_names,
                  "series": [{"name": f, "ci": FAMILY_CI[f],
                              "data": [v if fam == f else "-" for v, fam in zip(spec_vals, spec_fams)]}
                             for f in [x for x in FAMILY_ORDER if x in spec_fams]]},
        "families": {"x": [f"שנות ה-{d}" for d in fdecs],
                     "series": [{"name": f, "ci": FAMILY_CI[f],
                                 "data": [int(fam_dec.loc[d, f]) for d in fdecs]} for f in fams]},
        "gap": {"names": list(gap_b.index), "values": [int(v) for v in gap_b.values]},
        "surnames": {"names": list(surnames.head(TOP_NAMES).index),
                     "values": [int(v) for v in surnames.head(TOP_NAMES).values]},
        "firsts": {"names": list(firsts.head(TOP_NAMES).index),
                   "values": [int(v) for v in firsts.head(TOP_NAMES).values]},
    }

    rules = [
        ("peak", insight_peak(per_year, last_full)),
        ("ytd", insight_ytd(df, ref, partial)),
        ("decades", insight_decades(dec_counts, last_full)),
        ("season", insight_season(months, pf, ref_year)),
        ("batch", insight_batch(day_counts, pf)),
        ("specialists", insight_specialists(n_spec, n_multi, total, spec_counts)),
        ("shift", insight_shift(fam_dec, last_full)),
        ("gap", insight_gap(gaps)),
        ("precision", insight_precision(df, pf)),
        ("surname", insight_surname(surnames, total)),
        ("types", insight_types(type_counts)),
        ("missing", insight_missing(n_missing, total_rows)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    lf = int(per_year.get(last_full, 0))
    lp = int(per_year.get(last_full - 1, 0))
    chg = (lf / lp - 1) if lp else 0
    new_tone = "ok" if chg >= 0.05 else ("warn" if chg <= -0.05 else "brand")
    ytd = int(per_year.get(ref_year, 0))
    if not lp:
        chg_txt = ""
    elif round(abs(chg) * 100) == 0:
        chg_txt = f", ללא שינוי לעומת {last_full - 1}"
    else:
        chg_txt = f", {'עלייה' if chg > 0 else 'ירידה'} של {abs(chg) * 100:.0f}% לעומת {last_full - 1}"
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "new": {"value": lf, "display": n(lf), "tone": new_tone},
        "specialists": {"value": n_spec, "display": n(n_spec), "tone": "info"},
        "fields": {"value": int(spec_counts.size), "display": n(spec_counts.size), "tone": "brand"},
    }

    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    type_note = f" כל הרישיונות במאגר הם מסוג \"{sole_type}\"." if sole_type else ""
    labels = {
        "lede": (f"מרשם הרופאים הווטרינרים בעלי רישיון של משרד החקלאות: {n(total)} וטרינרים, "
                 f"מהם {n(n_spec)} בעלי מומחיות מוכרת ב-{n(spec_counts.size)} תחומים. הרישיון "
                 f"המוקדם במאגר ניתן ב-{first_year}, והאחרון ב-{d_he(ref)}.{type_note}"),
        "total_kpi": "וטרינרים רשומים",
        "new_kpi": f"רישיונות חדשים ב-{last_full}{chg_txt}",
        "spec_kpi": f"בעלי מומחיות מוכרת ({n_spec / total * 100:.1f}% מהרשומים)",
        "fields_kpi": "תחומי מומחיות",
        "years_note": (f"רישיונות שניתנו בכל שנה, לפי האם לבעל הרישיון רשומה כיום מומחיות. "
                       f"ניתן לגלול ולהגדיל את טווח השנים; ברירת המחדל מוצגת מ-{years[charts['years']['zoom_from']]}."
                       f"{partial_note}"),
        "years_aria": (f"גרף עמודות מוערמות: רישיונות וטרינרים לפי שנה, {first_year} עד {ref_year}; "
                       f"שיא ב-{int(per_year[per_year.index <= last_full].idxmax())}."),
        "decades_note": ("מספר הרישיונות לפי עשור הרישוי, ושיעור בעלי המומחיות בכל מחזור. "
                         "במחזורים האחרונים השיעור נמוך גם משום שהכרה במומחיות מגיעה שנים אחרי הרישוי."
                         + (f" רישיונות מלפני {DECADE_FROM} מקובצים יחד." if decs and decs[0] < DECADE_FROM else "")
                         + (f" העשור האחרון חלקי, עד {ref_year}." if decs[-1] + 9 > ref_year else "")),
        "decades_aria": f"גרף עמודות וקו: רישיונות לפי עשור ושיעור בעלי מומחיות, {dec_labels[0]} עד {dec_labels[-1]}.",
        "decades_caption": "רישיונות ושיעור בעלי מומחיות, לפי עשור הרישוי.",
        "cum_note": (f"מספר הרישיונות המצטבר מתחילת השנה, {ref_year} לעומת השנתיים שקדמו לה. "
                     f"הקפיצות משקפות ימי רישוי מרוכזים."
                     + (f" נתוני {ref_year} עד {d_he(ref)}." if partial else "")),
        "cum_aria": f"גרף קווים: רישיונות מצטברים לפי חודש, {cum_series[-1]['name']} עד {ref_year}.",
        "cum_caption": "רישיונות מצטברים מתחילת השנה, לפי חודש.",
        "months_note": f"סך הרישיונות שניתנו בכל חודש, {pf}–{ref_year} (לפני {pf} רשומה רק שנת הרישוי).",
        "months_aria": f"תרשים עמודות: רישיונות לפי חודש בשנה, {pf} עד {ref_year}.",
        "months_caption": "רישיונות לפי חודש.",
        "heat_note": f"מספר הרישיונות בכל חודש, {hy[0]}–{ref_year}.",
        "heat_aria": f"מפת חום: רישיונות לפי חודש ושנה, {hy[0]} עד {ref_year}.",
        "days_note": f"{TOP_DAYS} הימים שבהם ניתנו הכי הרבה רישיונות, {pf}–{ref_year}.",
        "days_aria": (f"תרשים עמודות אופקי: {TOP_DAYS} ימי הרישוי הגדולים — "
                      f"{d_he(top_days.index[0])} בראש עם {n(top_days.iloc[0])} רישיונות."),
        "days_caption": "ימי הרישוי הגדולים ומספר הרישיונות בכל אחד.",
        "specshare_note": "כמה מהווטרינרים הרשומים מחזיקים במומחיות מוכרת אחת או יותר.",
        "specshare_aria": f"תרשים טבעת: {n(n_spec)} מתוך {n(total)} וטרינרים בעלי מומחיות.",
        "specshare_caption": "וטרינרים לפי מספר המומחיות הרשומות.",
        "specs_note": (f"{TOP_SPECS} המומחיות הנפוצות, לפי תחום"
                       + (f"; {n(len(other_specs))} מומחיות נוספות מקובצות ב\"אחר\"." if len(other_specs) else ".")
                       + " שמות שנקטעו במקור הושלמו; תחומי המיקרוביולוגיה הקלינית מוצגים בשם תת־התחום."),
        "specs_aria": (f"תרשים עמודות אופקי: המומחיות הנפוצות — {spec_counts.index[0]} בראש עם "
                       f"{n(spec_counts.iloc[0])} בעלי מומחיות."),
        "specs_caption": "מספר בעלי מומחיות לפי מומחיות ותחום.",
        "families_note": "מומחיות שהוכרו בכל עשור, לפי שנת ההכרה ותחום המומחיות."
                         + (" העשור האחרון חלקי." if fdecs and fdecs[-1] + 9 > ref_year else ""),
        "families_aria": "גרף עמודות מוערמות: הכרה במומחיות לפי עשור ותחום.",
        "families_caption": "מספר מומחיות שהוכרו, לפי עשור ותחום.",
        "gap_note": "השנים שחלפו משנת קבלת הרישיון ועד שנת ההכרה בכל מומחיות.",
        "gap_aria": (f"תרשים עמודות: הזמן מרישוי להכרה במומחיות, חציון "
                     f"{int(gaps.dropna().median()) if gaps.notna().any() else 0} שנים."),
        "gap_caption": "מספר מומחיות לפי השנים שחלפו מהרישוי.",
        "surnames_note": f"{TOP_NAMES} שמות המשפחה הנפוצים בכלל המרשם.",
        "surnames_aria": f"תרשים עמודות אופקי: {TOP_NAMES} שמות המשפחה הנפוצים — {surnames.index[0]} בראש.",
        "surnames_caption": "מספר וטרינרים לפי שם משפחה.",
        "firsts_note": f"{TOP_NAMES} השמות הפרטיים הנפוצים בקרב מי שקיבלו רישיון ב-{ref_year - 9}–{ref_year}.",
        "firsts_aria": f"תרשים עמודות אופקי: {TOP_NAMES} השמות הפרטיים הנפוצים בקרב בעלי רישיון מ-{ref_year - 9}.",
        "firsts_caption": "מספר וטרינרים לפי שם פרטי.",
    }
    tables = {
        "decades": [{"name": lab, "count": n(dec_counts[d]), "share": f"{s:.1f}%"}
                    for d, lab, s in zip(decs, dec_labels, spec_share)],
        "cumulative": [{"month": MONTHS_SHORT[i],
                        "vals": [("—" if s["data"][i] is None else n(s["data"][i])) for s in cum_series]}
                       for i in range(12)],
        "cum_cols": [s["name"] for s in cum_series],
        "months": [{"month": MONTHS_HE[i], "count": n(v)} for i, v in enumerate(months.values)],
        "days": [{"day": d_he(d), "count": n(v)} for d, v in top_days.items()],
        "specshare": [{"name": nm, "count": n(v), "share": f"{v / total * 100:.1f}%"}
                      for nm, v in zip(charts["specshare"]["names"], charts["specshare"]["values"])],
        "specs": [{"name": s, "family": f, "count": n(v)}
                  for s, f, v in zip(spec_names, spec_fams, spec_vals)],
        "fam_cols": fams,
        "families": [{"name": f"שנות ה-{d}", "vals": [n(fam_dec.loc[d, f]) for f in fams]} for d in fdecs],
        "gap": [{"name": k, "count": n(v)} for k, v in gap_b.items()],
        "surnames": [{"name": k, "count": n(v)} for k, v in surnames.head(TOP_NAMES).items()],
        "firsts": [{"name": k, "count": n(v)} for k, v in firsts.head(TOP_NAMES).items()],
    }

    return {
        "agent_data": {
            "summary_he": (f"מרשם הרופאים הווטרינרים בישראל: {n(total)} בעלי רישיון, מהם {n(n_spec)} "
                           f"בעלי מומחיות מוכרת — תאריך הרישוי ותחומי המומחיות, מ-{first_year} ועד {ref_year}."),
            "dataset_kind": "registry",
            "related_ids": ["c27919df-83d8-4aba-8297-f307fa1737fd",
                            "a25e63f2-4f22-4eff-a696-e7c6d20c9e27",
                            "b4c32de1-627c-4b93-8d20-e58f6d44f733",
                            "28954732-da33-48d0-b22c-1c0c279aadca",
                            "83cdc927-2bcf-4db2-b9d6-9f674cd52222"],
            "suggested_tags": ["וטרינרים", "רישוי מקצועי", "מומחיות וטרינרית",
                               "בריאות בעלי חיים", "משרד החקלאות"],
            "temporal_coverage": f"{first_year}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"partial": partial},
    }
