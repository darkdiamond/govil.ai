"""רשימת בעלי הכשרות בבריאות הסביבה — Ministry of Health register of
environmental-health certifications.

One row per certification (~14k): training-type code, family/first name,
certificate number, date received and validity date. The whole list is
republished on each update and holds only currently valid certifications, so
the page is a snapshot.

"Now" is never the wall clock. The reference date (`as_of`) is the latest
receipt date that is not after the earliest validity date in the list: every
listed certification is valid at publication, so publication falls on or
before the earliest expiry, and the latest certification granted by then marks
the data's vintage. A handful of receipt dates lie years in the future (typos)
and some sit at 1900 or in the 1930s (placeholders); receipts before MIN_YEAR
or after `as_of` are excluded from the date views and disclosed.

The training type is published as a numeric code only, with no name. The page
labels each code with the letter prefix most of its certificate numbers carry
(computed from the data); certificate numbers themselves never reach the page.

Names are used only to group certifications of one person (family + first
name). Namesakes merge, so holder counts are an approximation and the page
says so. No individual is named on the page.
"""
import re

import pandas as pd

MIN_YEAR = 1990
TOP_STACK = 6
MAX_TYPES = 15
HEAT_YEARS = 12
TREND_YEARS = 5
TOP_PAIRS = 10
TOP_DAYS = 10
WINDOW_MONTHS = 12
SENIORITY = [("פחות מ-3 שנים", 0, 3), ("3 עד 10 שנים", 3, 10),
             ("10 עד 20 שנים", 10, 20), ("20 שנה ומעלה", 20, None)]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
PREFIX_RE = re.compile(r"^\s*([A-Za-z]+)")


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _code_key(c):
    return (0, int(c), c) if c.isdigit() else (1, 0, c)


def _prepare(raw):
    df = pd.DataFrame({
        "code": raw["training_name"].astype(str).str.strip(),
        "family": raw["family_name"].astype(str).str.strip(),
        "first": raw["first_name"].astype(str).str.strip(),
        "cert": raw["certified_number"].astype(str),
        "recv": pd.to_datetime(raw["received_date"].astype(str).str.strip(),
                               format="%d/%m/%Y", errors="coerce"),
        "valid": pd.to_datetime(raw["validity_date"].astype(str).str.strip(),
                                format="%d/%m/%Y", errors="coerce"),
    })
    df.loc[df["code"] == "", "code"] = "לא צוין"
    df["prefix"] = df["cert"].str.extract(PREFIX_RE)[0].str.upper()
    df["person"] = df["family"] + "|" + df["first"]
    df.loc[(df["family"] == "") & (df["first"] == ""), "person"] = ""
    return df


def _prefixes(df):
    """Dominant certificate-number prefix per code (≥2 letters, ≥50% of prefixed rows)."""
    out = {}
    p = df[df["prefix"].notna() & (df["prefix"].str.len() >= 2)]
    for code, g in p.groupby("code"):
        vc = g["prefix"].value_counts()
        vc = vc.sort_index().sort_values(ascending=False, kind="mergesort")
        if vc.iloc[0] / len(g) >= 0.5:
            out[code] = vc.index[0]
    return out


def _as_of(df):
    vmin = df["valid"].min()
    recv = df["recv"].dropna()
    if pd.notna(vmin) and (recv <= vmin).any():
        return recv[recv <= vmin].max()
    return recv.max()


def _ranked(s):
    """Counts sorted desc with a total tie-break on the index key."""
    s = s.sort_index(key=lambda idx: idx.map(lambda c: str(_code_key(str(c)))))
    return s.sort_values(ascending=False, kind="mergesort")


# ── insight rules ───────────────────────────────────────────────────────────

def insight_leader(type_counts, label, total):
    if len(type_counts) < 2:
        return None
    top, second = type_counts.index[0], type_counts.index[1]
    share = type_counts.iloc[0] / total
    if share < 0.15:
        return None
    lead3 = type_counts.iloc[:3].sum() / total
    return (f"ההכשרה הנפוצה היא {label(top)} עם {n(type_counts.iloc[0])} רשומות ({pct(share)}), "
            f"ואחריה {label(second)} עם {n(type_counts.iloc[1])}; שלוש ההכשרות הגדולות מחזיקות "
            f"{pct(lead3)} מכלל {n(total)} הרשומות.")


def insight_trend(per_year, last_full):
    yrs = [y for y in per_year.index if y <= last_full]
    if len(yrs) < TREND_YEARS * 2:
        return None
    recent = [y for y in yrs if y > last_full - TREND_YEARS]
    before = [y for y in yrs if last_full - 2 * TREND_YEARS < y <= last_full - TREND_YEARS]
    if len(recent) < TREND_YEARS or len(before) < TREND_YEARS:
        return None
    a = sum(int(per_year.get(y, 0)) for y in recent) / TREND_YEARS
    b = sum(int(per_year.get(y, 0)) for y in before) / TREND_YEARS
    if b <= 0:
        return None
    ratio = a / b
    full = per_year[per_year.index <= last_full]
    peak = int(full.sort_index().idxmax())
    span_a = f"{recent[0]} עד {recent[-1]}"
    span_b = f"{before[0]} עד {before[-1]}"
    if ratio >= 1.25:
        what = f"פי {ratio:.1f} מהממוצע ב-{span_b} ({n(round(b))} בשנה)"
        head = "קצב ההסמכה עלה"
    elif ratio <= 0.8:
        what = f"ירידה של {(1 - ratio) * 100:.0f}% לעומת {span_b} ({n(round(b))} בשנה)"
        head = "קצב ההסמכה ירד"
    else:
        what = f"בדומה לממוצע ב-{span_b} ({n(round(b))} בשנה)"
        head = "קצב ההסמכה יציב"
    return (f"{head}: בשנים {span_a} נרשמו בממוצע {n(round(a))} הכשרות בשנה, {what}. "
            f"שנת השיא היא {peak} עם {n(full[peak])} הכשרות (לפי תאריך הקבלה של הכשרות שעדיין בתוקף).")


def insight_window(n_window, total_dated, as_of, end):
    if total_dated == 0 or n_window == 0:
        return None
    share = n_window / total_dated
    tone = "גל חידושים משמעותי" if share >= 0.15 else "חידושים צפויים"
    return (f"{tone}: {n(n_window)} הכשרות ({pct(share)} מאלה שיש להן תאריך תוקף) "
            f"פגות בתוך {WINDOW_MONTHS} חודשים ממועד הייחוס ({d_he(as_of)}), עד {d_he(end)}.")


def insight_expiry_peak(exp_year, as_of_year, total_dated):
    later = exp_year[exp_year.index > as_of_year]
    if later.empty or total_dated == 0:
        return None
    later = later.sort_index()
    peak = int(later.idxmax())
    share = later[peak] / total_dated
    if share < 0.1:
        return None
    return (f"שנת הפקיעה העמוסה היא {peak}: {n(later[peak])} הכשרות ({pct(share)}) "
            f"יפוגו בה אם לא יחודשו.")


def insight_no_validity(df, label):
    miss = df[df["valid"].isna()]
    if miss.empty:
        return None
    by = _ranked(miss.groupby("code").size())
    full_codes = [c for c in by.index if by[c] == int((df["code"] == c).sum())]
    if full_codes:
        names = " ו".join([", ".join(label(c) for c in full_codes[:-1]), label(full_codes[-1])]
                          ) if len(full_codes) > 1 else label(full_codes[0])
        rest = int(len(miss) - sum(int(by[c]) for c in full_codes))
        extra = f", ועוד {n(rest)} רשומות בהכשרות אחרות" if rest else ""
        return (f"ל-{n(len(miss))} רשומות לא רשום תאריך תוקף: כל רשומות {names}{extra} — "
                f"הכשרות שמופיעות ברשימה ללא מועד פקיעה.")
    return f"ל-{n(len(miss))} רשומות ({pct(len(miss) / len(df))}) לא רשום תאריך תוקף."


def insight_multi(per_person, pair_counts, label):
    if per_person.empty:
        return None
    multi = int((per_person >= 2).sum())
    share = multi / len(per_person)
    if share < 0.05:
        return None
    pair_txt = ""
    if pair_counts:
        (a, b), v = pair_counts[0]
        pair_txt = f" הצירוף השכיח: {label(a)} יחד עם {label(b)} ({n(v)} בעלי הכשרה)."
    return (f"{n(multi)} בעלי הכשרות ({pct(share)}) מחזיקים בשני סוגי הכשרה או יותר (לפי צירוף שם), "
            f"ו-{n(int((per_person >= 3).sum()))} בשלושה ומעלה.{pair_txt}")


def insight_seniority(sen_share, label, counts):
    elig = [c for c in sen_share if counts.get(c, 0) >= 50]
    if len(elig) < 3:
        return None
    newest = sorted(elig, key=lambda c: (-sen_share[c][0], _code_key(c)))[0]
    oldest = sorted(elig, key=lambda c: (-(sen_share[c][2] + sen_share[c][3]), _code_key(c)))[0]
    if newest == oldest or sen_share[newest][0] < 0.3:
        return None
    return (f"{label(newest)} היא ההכשרה הצעירה: {pct(sen_share[newest][0], 0)} מבעליה הוסמכו בשלוש "
            f"השנים האחרונות. ב{label(oldest)} הוותק הגבוה ביותר — "
            f"{pct(sen_share[oldest][2] + sen_share[oldest][3], 0)} הוסמכו לפני עשור ויותר.")


def insight_batches(day_counts, since, total_since):
    if day_counts.empty or total_since < 100:
        return None
    top = day_counts.iloc[:TOP_DAYS]
    share = top.sum() / total_since
    if share < 0.2:
        return None
    return (f"ההסמכה מתבצעת במחזורים: {TOP_DAYS} הימים העמוסים מאז {since} מרכזים "
            f"{n(top.sum())} הכשרות ({pct(share)} מההכשרות בתקופה); ב-{d_he(top.index[0])} לבדו "
            f"נרשמו {n(top.iloc[0])}.")


def insight_quality(n_early, n_future, earliest):
    if n_early + n_future == 0:
        return None
    parts = []
    if n_early:
        parts.append(f"{n(n_early)} לפני {MIN_YEAR} (המוקדם: {earliest})")
    if n_future:
        parts.append(f"{n(n_future)} אחרי מועד הייחוס")
    return (f"ל-{n(n_early + n_future)} רשומות תאריך קבלה שאינו סביר — {' ו-'.join(parts)}; "
            f"הן נספרות בסיכומים אך לא בתרשימים לפי מועד הקבלה.")


# ── compute ─────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    prefixes = _prefixes(df)

    def label(c):
        return f"הכשרה {c} ({prefixes[c]})" if c in prefixes else f"הכשרה {c}"

    def short(c):
        return f"{c} · {prefixes[c]}" if c in prefixes else str(c)

    type_counts = _ranked(df.groupby("code").size())
    codes_all = list(type_counts.index)
    if len(codes_all) > MAX_TYPES:
        main_codes = codes_all[:MAX_TYPES - 1]
    else:
        main_codes = codes_all
    OTHER = "אחר"
    df["grp"] = df["code"].where(df["code"].isin(main_codes), OTHER)
    groups = main_codes + ([OTHER] if len(main_codes) < len(codes_all) else [])

    def glabel(g):
        return "סוגים אחרים" if g == OTHER else short(g)

    as_of = _as_of(df)
    as_of_year = int(as_of.year)
    partial = not (as_of.month == 12 and as_of.day >= 15)
    last_full = as_of_year - 1 if partial else as_of_year

    ok_date = df["recv"].notna() & (df["recv"].dt.year >= MIN_YEAR) & (df["recv"] <= as_of)
    n_bad = int((~ok_date).sum())
    early = df["recv"].notna() & (df["recv"].dt.year < MIN_YEAR)
    n_early = int(early.sum())
    n_future = int((df["recv"] > as_of).sum())
    earliest = d_he(df.loc[early, "recv"].min()) if n_early else ""
    dated = df[ok_date].copy()
    dated["year"] = dated["recv"].dt.year.astype(int)
    first_year = int(dated["year"].min())

    # people (namesakes merge)
    ppl = df[df["person"] != ""]
    per_person = ppl.groupby("person")["code"].nunique()
    holders = int(per_person.size)

    # ── chart: types
    tbl_types = []
    for c in codes_all:
        g = df[df["code"] == c]
        gv = g["valid"].dropna()
        tbl_types.append({
            "code": c, "prefix": prefixes.get(c, "—"), "count": n(len(g)),
            "share": pct(len(g) / total),
            "holders": n(g.loc[g["person"] != "", "person"].nunique()),
            "first": str(int(dated.loc[dated["code"] == c, "year"].min())) if (dated["code"] == c).any() else "—",
        })
    charts = {"types": {"names": [short(c) for c in codes_all][::-1],
                        "values": [int(type_counts[c]) for c in codes_all][::-1]}}

    # ── chart: years stacked by top types
    per_year = dated.groupby("year").size()
    years = list(range(first_year, as_of_year + 1))
    stack_codes = codes_all[:TOP_STACK]
    dated["sg"] = dated["code"].where(dated["code"].isin(stack_codes), OTHER)
    yc = dated.groupby(["year", "sg"]).size()
    stack_names = stack_codes + ([OTHER] if len(codes_all) > TOP_STACK else [])
    zoom_from = max(0, years.index(max(first_year, as_of_year - 20)))
    charts["years"] = {
        "x": [str(y) for y in years],
        "zoom_from": zoom_from,
        "series": [{"name": glabel(s), "data": [int(yc.get((y, s), 0)) for y in years]} for s in stack_names],
        "partial_idx": len(years) - 1 if partial else -1,
    }

    # ── chart: heat month × year
    hy = [y for y in years if y > as_of_year - HEAT_YEARS]
    mc = dated[dated["year"].isin(hy)].groupby([dated["year"], dated["recv"].dt.month]).size()
    cells = []
    for yi, y in enumerate(hy):
        for m in range(1, 13):
            if y == as_of_year and m > as_of.month:
                continue
            cells.append([m - 1, yi, int(mc.get((y, m), 0))])
    charts["heat"] = {"x": MONTHS_SHORT, "y": [str(y) for y in hy], "cells": cells,
                      "max": max([c[2] for c in cells] + [1])}

    # cohort days
    since = last_full - TREND_YEARS + 1
    recent_dated = dated[dated["year"] >= since]
    day_counts = recent_dated.groupby(recent_dated["recv"].dt.normalize()).size()
    day_counts = day_counts.sort_index().sort_values(ascending=False, kind="mergesort")

    # ── chart: expiry by year
    vd = df[df["valid"].notna()]
    total_dated = len(vd)
    exp_year = vd.groupby(vd["valid"].dt.year.astype(int)).size().sort_index()
    charts["expiry"] = {"x": [str(y) for y in exp_year.index], "values": [int(v) for v in exp_year.values],
                        "as_of_idx": [i for i, y in enumerate(exp_year.index) if y == as_of_year]}

    # ── chart: upcoming 12-month window by month, stacked by top types
    win_end = (as_of + pd.DateOffset(months=WINDOW_MONTHS))
    months = pd.period_range(as_of.to_period("M"), periods=WINDOW_MONTHS + 1, freq="M")
    vw = vd[(vd["valid"] > as_of) & (vd["valid"] <= win_end)].copy()
    n_window = len(vw)
    vw["per"] = vw["valid"].dt.to_period("M")
    vw["sg"] = vw["code"].where(vw["code"].isin(stack_codes), OTHER)
    wc = vw.groupby(["per", "sg"]).size()
    wtot = vw.groupby("per").size()
    mlabels = [f"{MONTHS_SHORT[p.month - 1]} {p.year}" for p in months]
    charts["window"] = {
        "x": mlabels,
        "series": [{"name": glabel(s), "data": [int(wc.get((p, s), 0)) for p in months]} for s in stack_names],
    }
    tbl_window = [{"month": lab, "count": n(int(wtot.get(p, 0)))} for p, lab in zip(months, mlabels)]

    # ── chart: seniority per type (100%)
    dated["age"] = (as_of - dated["recv"]).dt.days / 365.25
    sen_share, sen_rows = {}, []
    sen_series = [[] for _ in SENIORITY]
    for g in groups:
        sub = dated.loc[dated["grp"] == g, "age"]
        k = len(sub)
        shares = []
        for i, (_, lo, hi) in enumerate(SENIORITY):
            m = (sub >= lo) & ((sub < hi) if hi is not None else True)
            v = int(m.sum())
            s = v / k if k else 0.0
            shares.append(s)
            sen_series[i].append(round(s * 100, 1))
        sen_share[g] = shares
        med = float(sub.median()) if k else float("nan")
        sen_rows.append({"name": glabel(g), "count": n(k),
                         "vals": [pct(s, 0) for s in shares],
                         "median": f"{med:.1f}" if k else "—"})
    charts["seniority"] = {"names": [glabel(g) for g in groups],
                           "series": [{"name": SENIORITY[i][0], "data": sen_series[i]} for i in range(len(SENIORITY))]}

    # ── chart: types per holder
    dist = per_person.value_counts().sort_index()
    buckets = []
    for k in range(1, 5):
        buckets.append((f"{k}", int(dist.get(k, 0))))
    buckets.append(("5 ומעלה", int(dist[dist.index >= 5].sum())))
    charts["multi"] = {"names": [b[0] for b in buckets], "values": [b[1] for b in buckets]}
    tbl_multi = [{"name": b[0], "count": n(b[1]), "share": pct(b[1] / holders) if holders else "—"} for b in buckets]

    # ── chart: co-occurrence of types among multi-type holders
    pc = ppl[["person", "grp"]].drop_duplicates()
    multi_people = per_person[per_person >= 2].index
    pc = pc[pc["person"].isin(multi_people)]
    pair = pc.merge(pc, on="person")
    gi = {g: i for i, g in enumerate(groups)}
    pair = pair[pair["grp_x"].map(gi) < pair["grp_y"].map(gi)]
    pcnt = pair.groupby(["grp_x", "grp_y"]).size()
    pairs_sorted = sorted(((k, int(v)) for k, v in pcnt.items()),
                          key=lambda kv: (-kv[1], gi[kv[0][0]], gi[kv[0][1]]))
    co_cells = []
    for (a, b), v in pairs_sorted:
        co_cells.append([gi[a], gi[b], v])
        co_cells.append([gi[b], gi[a], v])
    co_cells.sort(key=lambda c: (c[0], c[1]))
    charts["pairs"] = {"names": [glabel(g) for g in groups], "cells": co_cells,
                       "max": max([c[2] for c in co_cells] + [1])}
    tbl_pairs = [{"a": glabel(a), "b": glabel(b), "count": n(v)} for (a, b), v in pairs_sorted[:TOP_PAIRS]]

    # ── KPIs
    lf_count = int(per_year.get(last_full, 0))
    prev = int(per_year.get(last_full - 1, 0))
    chg = (lf_count - prev) / prev if prev else 0.0
    if prev and round(abs(chg) * 100) == 0:
        chg_txt = f", ללא שינוי לעומת {last_full - 1}"
    elif prev:
        chg_txt = f", {'עלייה' if chg > 0 else 'ירידה'} של {abs(chg) * 100:.0f}% לעומת {last_full - 1}"
    else:
        chg_txt = ""
    new_tone = "ok" if chg >= 0.1 else ("warn" if chg <= -0.2 else "brand")
    win_share = n_window / total_dated if total_dated else 0.0
    win_tone = "warn" if win_share >= 0.15 else "info"
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "holders": {"value": holders, "display": n(holders), "tone": "brand"},
        "new": {"value": lf_count, "display": n(lf_count), "tone": new_tone},
        "window": {"value": n_window, "display": n(n_window), "tone": win_tone},
    }

    # ── insights
    pair_counts = [((a, b), v) for (a, b), v in pairs_sorted if a != OTHER and b != OTHER]
    rules = [
        ("leader", insight_leader(type_counts, label, total)),
        ("trend", insight_trend(per_year, last_full)),
        ("window", insight_window(n_window, total_dated, as_of, win_end)),
        ("expiry_peak", insight_expiry_peak(exp_year, as_of_year, total_dated)),
        ("multi", insight_multi(per_person, pair_counts, label)),
        ("seniority", insight_seniority({g: s for g, s in sen_share.items() if g != OTHER}, label,
                                        {c: int(type_counts[c]) for c in codes_all})),
        ("batches", insight_batches(day_counts, since, len(recent_dated))),
        ("no_validity", insight_no_validity(df, label)),
        ("quality", insight_quality(n_early, n_future, earliest)),
    ]
    insights = [{"id": k, "text_he": t} for k, t in rules if t]

    pref_note = ("סוג ההכשרה מפורסם במאגר כקוד מספרי בלבד, ללא שם; לצד כל קוד מוצגת הקידומת "
                 "האופיינית למספרי התעודה שלו.")
    partial_note = f" {as_of_year} — שנה חלקית, עד {d_he(as_of)}." if partial else ""
    bad_note = (f" לא נכללו {n(n_bad)} רשומות שתאריך הקבלה שלהן אינו סביר." if n_bad else "")
    approx = "בעלי הכשרות מזוהים לפי צירוף שם משפחה ושם פרטי, כך שבעלי שם זהה נספרים כאדם אחד."
    no_valid = total - total_dated
    labels = {
        "lede": (f"רשימת ההכשרות בתוקף בתחום בריאות הסביבה של משרד הבריאות: {n(total)} הכשרות "
                 f"ב-{n(len(codes_all))} סוגים, של כ-{n(holders)} בעלי הכשרות. מועד הייחוס של הנתונים — "
                 f"ההכשרה האחרונה שניתנה לפני מועד הפקיעה המוקדם ברשימה — הוא {d_he(as_of)}. {pref_note}"),
        "total_kpi": "הכשרות בתוקף",
        "holders_kpi": "בעלי הכשרות (לפי צירוף שם)",
        "new_kpi": f"הכשרות שניתנו ב-{last_full}{chg_txt}",
        "window_kpi": f"פגות בתוך {WINDOW_MONTHS} חודשים ({pct(win_share)} מבעלות תאריך תוקף)",
        "types_note": f"מספר ההכשרות בתוקף לפי קוד ההכשרה. {pref_note}",
        "types_aria": (f"תרשים עמודות אופקי: הכשרות לפי סוג — {label(codes_all[0])} בראש עם "
                       f"{n(type_counts.iloc[0])} רשומות."),
        "types_caption": "הכשרות בתוקף לפי סוג ההכשרה.",
        "years_note": (f"הכשרות בתוקף לפי שנת הקבלה, ב-{TOP_STACK} הסוגים הגדולים והשאר מקובצים. "
                       f"הרשימה כוללת רק הכשרות שעדיין בתוקף, לכן שנים מוקדמות מיוצגות רק במי שחידש "
                       f"את ההכשרה.{partial_note}{bad_note}"),
        "years_aria": (f"גרף עמודות מוערמות: הכשרות לפי שנת קבלה, {first_year} עד {as_of_year}; "
                       f"שיא ב-{int(per_year[per_year.index <= last_full].sort_index().idxmax())}."),
        "heat_note": (f"מספר ההכשרות שהתקבלו בכל חודש, {hy[0]} עד {as_of_year}. התאים הכהים "
                      f"הם מחזורי הסמכה — ההכשרות ניתנות בקבוצות, לא באופן רציף."),
        "heat_aria": f"מפת חום: הכשרות לפי חודש ושנת קבלה, {hy[0]} עד {as_of_year}.",
        "expiry_note": ("הכשרות לפי שנת פקיעת התוקף."
                        + (f" שנת מועד הייחוס, {as_of_year}, מודגשת — הכשרות שיפוגו בה בחודשים הקרובים."
                           if as_of_year in exp_year.index else "")
                        + (f" {n(no_valid)} רשומות ללא תאריך תוקף אינן מוצגות." if no_valid else "")),
        "expiry_aria": (f"תרשים עמודות: הכשרות לפי שנת פקיעה, {exp_year.index[0]} עד {exp_year.index[-1]}."
                        if len(exp_year) else "תרשים עמודות: הכשרות לפי שנת פקיעה."),
        "expiry_caption": "הכשרות לפי שנת פקיעת התוקף.",
        "window_note": (f"הכשרות שתוקפן פג בכל חודש, מ-{d_he(as_of)} ועד {d_he(win_end)} — "
                        f"{n(n_window)} בסך הכול, לפי סוג."),
        "window_aria": f"גרף עמודות מוערמות: הכשרות שתוקפן פג בכל חודש ב-{WINDOW_MONTHS} החודשים שאחרי מועד הייחוס.",
        "window_caption": "הכשרות שתוקפן פג לפי חודש.",
        "seniority_note": (f"ותק ההכשרה — הזמן מתאריך הקבלה ועד מועד הייחוס — בכל סוג. "
                           f"סוג צעיר נפתח או התרחב לאחרונה; סוג ותיק מוחזק בעיקר על ידי מי שחידשו."),
        "seniority_aria": "גרף עמודות מוערמות באחוזים: ותק ההכשרה לפי סוג.",
        "seniority_caption": "ותק ההכשרה לפי סוג (שיעור מההכשרות, וחציון בשנים).",
        "multi_note": f"בכמה סוגי הכשרה שונים מחזיק כל בעל הכשרה. {approx}",
        "multi_aria": (f"תרשים עמודות: בעלי הכשרות לפי מספר סוגי ההכשרה — "
                       f"{n(buckets[0][1])} מחזיקים בסוג אחד."),
        "multi_caption": "בעלי הכשרות לפי מספר סוגי ההכשרה.",
        "pairs_note": (f"כמה בעלי הכשרות מחזיקים בכל צירוף של שני סוגים — אילו הכשרות נלמדות יחד. {approx}"),
        "pairs_aria": "מפת חום: מספר בעלי הכשרות המחזיקים בכל זוג סוגי הכשרה.",
        "pairs_caption": "זוגות סוגי ההכשרה הנפוצים.",
    }
    tables = {"types": tbl_types, "window": tbl_window, "seniority": sen_rows,
              "sen_cols": [s[0] for s in SENIORITY], "multi": tbl_multi, "pairs": tbl_pairs,
              "expiry": [{"year": str(y), "count": n(v), "share": pct(v / total_dated)}
                         for y, v in exp_year.items()]}

    return {
        "agent_data": {
            "summary_he": (f"רשימת ההכשרות בתוקף בבריאות הסביבה של משרד הבריאות: {n(total)} הכשרות "
                           f"ב-{n(len(codes_all))} סוגים, של כ-{n(holders)} בעלי הכשרות; "
                           f"{n(n_window)} מהן פגות בתוך {WINDOW_MONTHS} חודשים ממועד הייחוס."),
            "dataset_kind": "registry",
            "related_ids": ["7a6cbf55-8178-4d40-8613-a38909c7e96f",
                            "2721d62d-d0da-45fd-93ac-5e7809849222",
                            "54601127-7b82-4bd7-ad80-271a802fdeeb",
                            "5a5aa50a-58b4-40e7-98d7-4630d76947d5",
                            "b87ef422-0355-4490-9506-d502b71e9b10"],
            "suggested_tags": ["בריאות הסביבה", "הכשרות מקצועיות", "רישוי מקצועי",
                               "משרד הבריאות", "תעודות הסמכה"],
            "temporal_coverage": f"{first_year}/{as_of.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"partial": partial, "has_window": n_window > 0, "has_pairs": len(co_cells) > 0},
    }
