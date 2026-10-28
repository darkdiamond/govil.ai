"""תורנות בתי מרקחת — Be'er Sheva weekly pharmacy duty roster.

One row per (pharmacy, duty week). Duty weeks run Sunday to Saturday. The two
date columns are named backwards in about half the rows (the "end" date is
earlier than the "start"), so the week is taken as min/max of the pair. A
re-issued block of the roster repeats earlier weeks; rows are deduplicated on
(pharmacy, week start) and the number removed is disclosed.

"Latest" is the latest week in the data; no clock is read.
"""
import math
from collections import Counter

import pandas as pd

MAX_BRANCHES = 15   # branch axes (timeline / heatmap / lines) are capped
MAX_YEARS = 12      # heatmap columns
MAX_POINTS = 260    # per cumulative line
MAX_TIMELINE = 520  # duty markers on the timeline
MIN_CYCLE_SHARE = 0.6


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _dstr(ts):
    return f"{ts.day:02d}/{ts.month:02d}/{ts.year}"


def _date(s):
    d = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    alt = pd.to_datetime(s, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    return d.fillna(alt)


def _phone(p):
    digits = "".join(ch for ch in p if ch.isdigit())
    if len(digits) == 9 and digits.startswith("7"):
        digits = "0" + digits
    if len(digits) == 10 and digits.startswith("07"):
        return f"{digits[:3]}-{digits[3:]}"
    return p.strip()


def _short_names(names):
    """Drop the leading words shared by every branch name (chart axis labels)."""
    toks = [n.split() for n in names]
    k = 0
    while all(len(t) > k + 1 for t in toks) and len({t[k] for t in toks}) == 1:
        k += 1
    out = [" ".join(t[k:]) for t in toks]
    return out if len(set(out)) == len(out) else list(names)


def _prepare(raw):
    a = _date(raw["shift-start-date"].str.strip())
    b = _date(raw["shift-end-date"].str.strip())
    df = pd.DataFrame({
        "branch": raw["location"].str.strip(),
        "address": raw["address"].str.strip(),
        "phone": raw["phone"].map(_phone),
        "start": pd.concat([a, b], axis=1).min(axis=1),
        "end": pd.concat([a, b], axis=1).max(axis=1),
    })
    df = df[(df["branch"] != "") & df["start"].notna()]
    n_raw = len(df)
    df = df.sort_values(["start", "branch", "address", "phone"], kind="stable")
    df = df.drop_duplicates(["branch", "start"], keep="first").reset_index(drop=True)
    return df, n_raw - len(df)


def _gaps_weeks(df):
    out = []
    for _, g in df.groupby("branch"):
        d = g["start"].sort_values()
        out += [int(x) // 7 for x in d.diff().dropna().dt.days]
    return out


def compute(frames):
    df, n_dupes = _prepare(frames.pop("roster"))
    n = len(df)
    weeks = sorted(df["start"].unique())
    first, last = pd.Timestamp(weeks[0]), pd.Timestamp(weeks[-1])
    last_end = df.loc[df["start"] == last, "end"].max()
    span_weeks = (last - first).days // 7 + 1
    missing = span_weeks - len(weeks)

    counts = df.groupby("branch").agg(
        duties=("start", "size"), first=("start", "min"), last=("start", "max")
    ).reset_index()
    counts = counts.sort_values(["duties", "first", "branch"], ascending=[False, True, True], kind="stable")
    counts = counts.reset_index(drop=True)
    n_branches = len(counts)
    short = dict(zip(counts["branch"], _short_names(list(counts["branch"]))))

    first_rows = df.drop_duplicates("branch", keep="first").set_index("branch")
    first_row = {b: first_rows.loc[b] for b in counts["branch"]}
    variants = df.groupby("branch")["address"].nunique()

    gaps = _gaps_weeks(df)
    gap_c = Counter(gaps)
    cycle, cycle_n = (sorted(gap_c.items(), key=lambda kv: (-kv[1], kv[0]))[0] if gaps else (0, 0))
    cycle_share = cycle_n / len(gaps) if gaps else 0

    top = list(counts["branch"].head(MAX_BRANCHES))
    top_set = set(top)

    # --- charts -------------------------------------------------------------
    by_branch = {"names": [short[b] for b in counts["branch"]], "values": [int(v) for v in counts["duties"]]}
    by_branch["full"] = list(counts["branch"])

    years_all = sorted(df["start"].dt.year.unique())[-MAX_YEARS:]
    wk_per_year = df.drop_duplicates("start").groupby(df["start"].dt.year).size()
    full_year_weeks = 50
    ylabels = []
    for y in years_all:
        partial = int(wk_per_year.get(y, 0)) < full_year_weeks and y in (years_all[0], years_all[-1])
        ylabels.append(f"{y}\n(חלקית)" if partial else str(y))
    by = df.groupby([df["start"].dt.year, "branch"]).size()
    cells = [[xi, yi, int(by.get((y, b), 0))] for yi, b in enumerate(top) for xi, y in enumerate(years_all)]
    heat = {"x": ylabels, "y": [short[b] for b in top], "cells": cells,
            "max": max([c[2] for c in cells] or [1])}

    tl = df[df["branch"].isin(top_set)].tail(MAX_TIMELINE)
    timeline = {"y": [short[b] for b in top], "series": []}
    for b in top:
        g = tl[tl["branch"] == b]
        timeline["series"].append({"name": short[b], "data": [[int(t.timestamp() * 1000), short[b]] for t in g["start"]]})

    wk_idx = pd.Series(range(len(weeks)), index=pd.DatetimeIndex(weeks))
    stride = max(1, math.ceil(len(weeks) / MAX_POINTS))
    sel = list(range(0, len(weeks), stride))
    if sel[-1] != len(weeks) - 1:
        sel.append(len(weeks) - 1)
    cum_series = []
    for b in top:
        g = df[df["branch"] == b]
        c = g.groupby("start").size().reindex(pd.DatetimeIndex(weeks), fill_value=0).cumsum()
        cum_series.append({"name": short[b], "data": [[int(pd.Timestamp(weeks[i]).timestamp() * 1000), int(c.iloc[i])] for i in sel]})
    cumulative = {"series": cum_series}

    # --- insights -----------------------------------------------------------
    def ins_span():
        return (f"הרשימה מכסה {_int(len(weeks))} שבועות תורנות, מ-{_dstr(first)} ועד שבוע שמסתיים ב-{_dstr(last_end)}, "
                f"ב-{_int(n)} שיבוצים של {_int(n_branches)} בתי מרקחת."
                + (f" {_int(n_dupes)} שורות כפולות (אותו בית מרקחת ואותו שבוע) הוסרו." if n_dupes else ""))

    def ins_continuity():
        if len(weeks) < 8:
            return None
        if missing == 0:
            return "אין אף שבוע חסר בין השבוע הראשון לאחרון: בכל שבוע בתקופה רשום לפחות בית מרקחת תורן אחד."
        return f"בתקופה חסרים {_int(missing)} שבועות שאין בהם אף בית מרקחת תורן ברשימה."

    def ins_cycle():
        if len(gaps) < 8 or cycle_share < MIN_CYCLE_SHARE:
            return None
        return (f"בית מרקחת חוזר לתורנות בדרך כלל אחת ל-{_int(cycle)} שבועות ({_pct(cycle_share)} מהמרווחים בין תורנויות "
                f"עוקבות של אותו בית מרקחת): התורנות מתחלפת במחזור קבוע.")

    def ins_equal():
        top_n = int(counts["duties"].max())
        k = int((counts["duties"] == top_n).sum())
        if k < 3:
            return None
        return (f"{_int(k)} מתוך {_int(n_branches)} בתי המרקחת תורנו בדיוק {_int(top_n)} פעמים כל אחד — חלוקת העומס שווה "
                f"בין מי שנכללו ברשימה לכל אורך התקופה.")

    def ins_changes():
        gone = counts[counts["last"] < last - pd.Timedelta(days=7 * 2 * max(cycle, 1))]
        late = counts[counts["first"] > first + pd.Timedelta(days=7 * 2 * max(cycle, 1))]
        if gone.empty and late.empty:
            return None
        parts = []
        for _, r in gone.sort_values(["last", "branch"]).iterrows():
            parts.append(f"{r['branch']} תורן לאחרונה בשבוע שהחל ב-{_dstr(r['last'])}")
        for _, r in late.sort_values(["first", "branch"]).iterrows():
            parts.append(f"{r['branch']} מופיע לראשונה בשבוע שהחל ב-{_dstr(r['first'])}")
        txt = "; ".join(parts) + "."
        ph = {b: set(df.loc[df["branch"] == b, "phone"]) for b in list(gone["branch"]) + list(late["branch"])}
        for g in gone["branch"]:
            for l in late["branch"]:
                if ph[g] & ph[l]:
                    txt += f" ל{g} ול{l} אותו מספר טלפון, ולכן ייתכן שמדובר באותו סניף בשם שונה."
                    break
            else:
                continue
            break
        return "לא כל בתי המרקחת נכללו לאורך כל התקופה: " + txt

    def ins_chain():
        firsts = Counter(b.split()[0] + " " + b.split()[1] if len(b.split()) > 1 else b for b in counts["branch"])
        name, k = sorted(firsts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        if k < max(3, math.ceil(0.8 * n_branches)):
            return None
        who = f"כל {_int(k)} בתי המרקחת התורנים ברשימה" if k == n_branches else f"{_int(k)} מתוך {_int(n_branches)} בתי המרקחת ברשימה"
        return f"{who} נושאים את השם '{name}' — {'הרשימה כולה מסניפי רשת אחת' if k == n_branches else 'רובה המכריע מסניפי רשת אחת'}."

    def ins_drift():
        k = int((variants > 1).sum())
        if k == 0:
            return None
        return (f"ב-{_int(k)} מתוך {_int(n_branches)} בתי המרקחת הכתובת נרשמת בגרסאות שונות בין שורות (למשל מספר בית שמשתנה "
                f"משורה לשורה), ולכן בטבלת הסניפים מופיעה הכתובת מהשורה הראשונה.")

    rules = [("span", ins_span()), ("continuity", ins_continuity()), ("cycle", ins_cycle()),
             ("equal", ins_equal()), ("changes", ins_changes()), ("chain", ins_chain()),
             ("address_drift", ins_drift())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # --- tables -------------------------------------------------------------
    branches = []
    for _, r in counts.iterrows():
        fr = first_row[r["branch"]]
        branches.append({"name": r["branch"], "address": fr["address"], "phone": fr["phone"],
                         "duties": int(r["duties"]), "first": _dstr(r["first"]), "last": _dstr(r["last"])})
    heat_table = {"x": ylabels, "rows": [{"name": short[b], "values": [int(by.get((y, b), 0)) for y in years_all]} for b in top]}

    years_span = f"{first.year}–{last.year}" if first.year != last.year else str(first.year)
    truncated = n_branches > MAX_BRANCHES
    trunc_note = f" מוצגים {_int(MAX_BRANCHES)} בתי המרקחת עם מספר התורנויות הגבוה ביותר." if truncated else ""

    return {
        "agent_data": {
            "summary_he": (f"רשימת תורנות בתי המרקחת בבאר שבע: {_int(len(weeks))} שבועות תורנות בין {_dstr(first)} ל-{_dstr(last_end)}, "
                           f"{_int(n_branches)} בתי מרקחת, כתובות וטלפונים."
                           + (f" מחזור התורנות: אחת ל-{_int(cycle)} שבועות." if cycle_share >= MIN_CYCLE_SHARE else "")),
            "dataset_kind": "timeseries",
            "suggested_tags": ["בתי מרקחת", "תורנות", "בריאות", "באר שבע"],
            "related_ids": [],
            "temporal_coverage": f"{first.year}/{last.year}",
            "spatial_coverage": "באר שבע",
        },
        "kpis": {
            "weeks": {"value": len(weeks), "display": _int(len(weeks)), "tone": "brand"},
            "branches": {"value": n_branches, "display": _int(n_branches), "tone": "brand"},
            "cycle": {"value": int(cycle), "display": _int(cycle), "tone": "brand"},
            "gaps": {"value": int(missing), "display": _int(missing), "tone": "ok" if missing == 0 else "warn"},
            "span": {"value": years_span, "display": years_span, "tone": "info"},
        },
        "charts": {"by_branch": by_branch, "heat": heat, "timeline": timeline, "cumulative": cumulative},
        "tables": {"branches": branches, "heat": heat_table},
        "insights": insights,
        "flags": {"has_cycle": cycle_share >= MIN_CYCLE_SHARE},
        "labels": {
            "lede": (f"רשימת התורנות השבועית של בתי המרקחת בבאר שבע: {_int(n_branches)} בתי מרקחת, "
                     f"{_int(len(weeks))} שבועות, מ-{_dstr(first)} ועד {_dstr(last_end)}. השבוע נמשך מיום ראשון עד שבת."),
            "by_branch_aria": f"תרשים עמודות: מספר התורנויות של כל אחד מ-{_int(n_branches)} בתי המרקחת.",
            "heat_aria": "מפת חום: מספר התורנויות לפי בית מרקחת ושנה.",
            "heat_note": ("מספר התורנויות בכל שנה לפי בית מרקחת. שנה שמסומנת 'חלקית' מכסה רק חלק מהשנה הקלנדרית."
                          + trunc_note),
            "timeline_aria": "תרשים פיזור: שבוע התורנות של כל בית מרקחת לאורך ציר הזמן.",
            "timeline_note": "כל ריבוע הוא שבוע תורנות אחד. הדפוס החוזר הוא מחזור התורנות; בית מרקחת שנעלם או מופיע באמצע התקופה נראה כשורה שנגמרת או מתחילה." + trunc_note,
            "cumulative_aria": "תרשים קווים: מספר התורנויות המצטבר של כל בית מרקחת לאורך הזמן.",
            "cumulative_note": "קווים שעולים בקצב זהה משמעם חלוקת עומס שווה; קו שמתחיל מאוחר או נעצר מוקדם משקף סניף שהצטרף או יצא מהרשימה." + trunc_note,
            "span_label": "תקופה",
        },
    }
