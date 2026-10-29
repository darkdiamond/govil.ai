"""פנקס הקבלנים הרשומים — the Registrar of Contractors (משרד הבינוי והשיכון).

One row per (contractor × branch) registration (~24k rows, ~18k contractors).
A contractor (MISPAR_KABLAN) holds one registration per branch (ענף) it may
work in; each registration carries a classification (סיווג ק/1–5) and group
(קבוצה א/ב/ג) that together fix the financial ceiling per single job (HEKEF,
thousands of ₪; "ב.מ." = unlimited), the recognised-contractor status for
government works, and the basis of registration (manager's qualifications vs.
employing professionals). Restrictions (suspended / frozen licence, no new
jobs) are appended to the branch description after a dash.

Contractors are businesses (companies and sole traders); naming is limited to
the multi-branch leaders ranking. Registry numbers, ID numbers, phones,
e-mails, street addresses and the qualifying-person column never reach the
page.

"Now" is the latest registration / classification date in the file (its data
vintage), never the wall clock; that calendar year is partial.
"""
import math

import numpy as np
import pandas as pd

SIVUG_ORDER = ["ק", "1", "2", "3", "4", "5"]
GROUP_ORDER = ["א", "ב", "ג"]
TOP_BRANCHES = 12
HEAT_BRANCHES = 12
TOP_TOWNS = 15
TOP_LEADERS = 10
MONTHS = 24
MIN_BRANCH_ROWS = 200  # branches smaller than this are left out of share rankings
BREADTH_BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 9), (10, None)]
AGE_BUCKETS = [(0, 1), (1, 3), (3, 5), (5, 10), (10, 20), (20, None)]  # years
TIERS = [("סיווג ק–1", {"ק", "1"}), ("סיווג 2–4", {"2", "3", "4"}), ("סיווג 5", {"5"})]
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _norm(s):
    return s.str.replace(r"\s+", " ", regex=True).str.strip()


def _restriction(suffix):
    if not suffix:
        return ""
    if "מותלה" in suffix:
        return "רישיון מותלה"
    if "הקפאת" in suffix:
        return "רישיון מוקפא"
    if "עבודות חדשות" in suffix:
        return "אסור בעבודות חדשות"
    if any(w in suffix for w in ("רשאי", "בלבד", "מגבל")):
        return "הגבלת תחום בתוך הענף"
    return ""  # a dash in a branch name that isn't a restriction


def _sivug_order(values):
    known = [s for s in SIVUG_ORDER if s in values]
    return known + sorted(v for v in values if v not in SIVUG_ORDER)


def _vc(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _prepare(raw):
    desc = _norm(raw["TEUR_ANAF"])
    parts = desc.str.split(r"\s[-–]\s?", n=1, regex=True)
    base = parts.str[0].str.strip()
    suffix = parts.str[1].fillna("").str.strip()
    df = pd.DataFrame({
        "kablan": raw["MISPAR_KABLAN"].str.strip(),
        "corp": raw["MISPAR_YESHUT"].str.strip() != "",
        "name": _norm(raw["SHEM_YESHUT"]).str.replace("~", '"', regex=False),
        "town": _norm(raw["SHEM_YISHUV"]),
        "first": pd.to_datetime(raw["TAARICH_KABLAN"].str.strip().str[:10],
                                format="%Y-%m-%d", errors="coerce"),
        "sug_date": pd.to_datetime(raw["TARICH_SUG"].str.strip(), format="%d-%m-%Y",
                                   errors="coerce"),
        "code": raw["KOD_ANAF"].str.strip(),
        "base": base,
        "restr": suffix.map(_restriction),
        "sivug": raw["SIVUG"].str.strip(),
        "group": raw["KVUTZA"].str.strip(),
        "hekef": raw["HEKEF"].str.strip(),
        "rec": raw["KABLAN_MUKAR"].str.strip().str.startswith("מוכר"),
        "staff": raw["HEARA"].str.contains("עובדים", regex=False),
    })
    df = df[df["kablan"] != ""].copy()
    # Branch label: the most common clean description per code (restriction
    # suffixes stripped); new codes flow through with their own description.
    lab = (df.groupby(["code", "base"]).size().reset_index(name="c")
           .sort_values(["code", "c", "base"], ascending=[True, False, True]))
    labels = lab.drop_duplicates("code").set_index("code")["base"]
    df["branch"] = df["code"].map(labels).replace("", "ענף לא מתואר")
    return df


def _contractors(df):
    s = df.sort_values(["kablan", "name", "town"])
    g = s.groupby("kablan", sort=True)
    rank = df["sivug"].map({k: i for i, k in enumerate(SIVUG_ORDER)}).fillna(-1)
    c = pd.DataFrame({
        "name": g["name"].first(),
        "town": g["town"].first(),
        "corp": g["corp"].max(),
        "first": g["first"].min(),
        "branches": g.size(),
        "top": rank.groupby(df["kablan"]).max(),
        "n5": (df["sivug"] == "5").groupby(df["kablan"]).sum(),
        "rec": g["rec"].max(),
    })
    c["top_sivug"] = c["top"].map(lambda i: SIVUG_ORDER[int(i)] if i >= 0 else "אחר")
    return c


def _bucket(lo, hi, unit=""):
    if hi is None:
        return f"{lo}+{unit}"
    if lo == hi:
        return f"{lo}{unit}"
    return f"{lo}–{hi}{unit}"


# ── insights ─────────────────────────────────────────────────────────────


def insight_concentration(df, bvc):
    if len(bvc) < 4:
        return None
    top3 = bvc.head(3)
    share = top3.sum() / len(df)
    if share < 0.4:
        return None
    names = ", ".join(top3.index[:2]) + " ו" + top3.index[2]
    return (f"שלושה ענפים — {names} — מרכזים {pct(share)} מכלל הרישומים "
            f"({n(top3.sum())} מתוך {n(len(df))}); בפנקס {n(len(bvc))} ענפים בסך הכול.")


def insight_ladder(df, c):
    entry = df["sivug"].isin(["ק", "1"]).mean()
    five = int((c["n5"] > 0).sum())
    if entry < 0.5:
        return None
    return (f"{pct(entry)} מהרישומים הם בסיווגים הנמוכים (ק ו-1), המגבילים את היקף העבודה הבודדת; "
            f"רק {n(five)} קבלנים ({pct(five / len(c))}) מחזיקים בסיווג 5 — ללא הגבלת היקף — "
            f"לפחות בענף אחד.")


def insight_growth(c, now, partial):
    y = c["first"].dt.year
    last = now.year - 1 if partial else now.year
    a, b = int((y == last).sum()), int((y == last - 1).sum())
    if b < 100:
        return None
    ch = (a - b) / b
    trend = ("בדומה לשנה שקדמה לה" if abs(ch) < 0.03
             else f"{'עלייה' if ch > 0 else 'ירידה'} של {pct(abs(ch))} לעומת {last - 1} ({n(b)})")
    vc = y[y <= last].value_counts().sort_index()
    peak = int(vc.sort_values(ascending=False, kind="stable").index[0])
    tail = " זו שנת השיא בפנקס." if peak == last else f" שנת השיא: {peak} ({n(vc[peak])})."
    return f"ב-{last} נרשמו לראשונה {n(a)} קבלנים — {trend}.{tail}"


def _ytd(c, now):
    """New contractors from 1 Jan to `now`, and in the same window a year earlier."""
    start, prev_start = pd.Timestamp(now.year, 1, 1), pd.Timestamp(now.year - 1, 1, 1)
    try:
        prev_end = now.replace(year=now.year - 1)
    except ValueError:
        prev_end = now.replace(year=now.year - 1, day=28)
    a = int(((c["first"] >= start) & (c["first"] <= now)).sum())
    b = int(((c["first"] >= prev_start) & (c["first"] <= prev_end)).sum())
    return a, b


def _latest(df):
    """Data vintage: the latest day carrying at least 3 registration or
    classification dates, so one mistyped future date can't move it."""
    days = pd.concat([df["first"], df["sug_date"]]).dropna().dt.normalize()
    vc = days.value_counts()
    solid = vc[vc >= 3]
    return solid.index.max() if len(solid) else days.max()


def insight_ytd(c, now):
    a, b = _ytd(c, now)
    if b < 100:
        return None
    ch = (a - b) / b
    word = ("כמעט ללא שינוי" if abs(ch) < 0.03
            else f"{'עלייה' if ch > 0 else 'ירידה'} של {pct(abs(ch))}")
    return (f"מתחילת {now.year} ועד {d_he(now)} נרשמו {n(a)} קבלנים חדשים, לעומת {n(b)} "
            f"באותה תקופה אשתקד — {word}.")


def insight_recognised(df, c):
    k = int(c["rec"].sum())
    if k == 0:
        return None
    s5 = df.loc[df["sivug"] == "5", "rec"].mean() if (df["sivug"] == "5").any() else None
    s1 = df.loc[df["sivug"] == "1", "rec"].mean() if (df["sivug"] == "1").any() else None
    tail = ""
    if s5 is not None and s1 is not None and s5 > s1:
        tail = (f" ההכרה נפוצה ככל שהסיווג גבוה: {pct(s5)} מהרישומים בסיווג 5, "
                f"לעומת {pct(s1)} בסיווג 1.")
    return (f"{n(k)} קבלנים ({pct(k / len(c))}) הם 'קבלנים מוכרים' — רשאים להשתתף במכרזי "
            f"עבודות ממשלתיות — לפחות בענף אחד.{tail}")


def insight_breadth(c):
    single = (c["branches"] == 1).mean()
    lead = c.sort_values(["branches", "n5", "name"], ascending=[False, False, True])
    top = lead.iloc[0]
    if top["branches"] < 5 or (len(lead) > 1 and lead.iloc[1]["branches"] == top["branches"]):
        return (f"{pct(single)} מהקבלנים רשומים בענף אחד בלבד; "
                f"{n((c['branches'] >= 3).sum())} רשומים בשלושה ענפים או יותר.")
    return (f"{pct(single)} מהקבלנים רשומים בענף אחד בלבד; הרחב ביותר, {top['name']}, "
            f"רשום ב-{n(top['branches'])} ענפים, מהם {n(top['n5'])} בסיווג 5.")


def insight_town(c):
    vc = _vc(c.loc[c["town"] != "", "town"])
    if len(vc) < 10:
        return None
    top10 = vc.head(10).sum() / vc.sum()
    return (f"{vc.index[0]} מובילה עם {n(vc.iloc[0])} קבלנים ({pct(vc.iloc[0] / vc.sum())}), "
            f"אחריה {vc.index[1]} ({n(vc.iloc[1])}); עשרת היישובים המובילים מרכזים "
            f"{pct(top10)} מהקבלנים, הפזורים ב-{n(len(vc))} יישובים.")


def insight_staff(df, bvc):
    big = [b for b in bvc.index if bvc[b] >= MIN_BRANCH_ROWS]
    if len(big) < 3:
        return None
    sh = df[df["branch"].isin(big)].groupby("branch")["staff"].mean()
    sh = sh.sort_index().sort_values(ascending=False, kind="stable")
    overall = df["staff"].mean()
    if overall >= 0.5 or sh.iloc[0] - sh.iloc[-1] < 0.1:
        return None
    return (f"רוב הרישומים מבוססים על כישורי המנהל; רק {pct(overall)} נשענים על העסקת עובדים "
            f"מקצועיים. בענף {sh.index[0]} השיעור גבוה בהרבה — {pct(sh.iloc[0])}, "
            f"ובענף {sh.index[-1]} — {pct(sh.iloc[-1])} בלבד (ענפים עם "
            f"{n(MIN_BRANCH_ROWS)} רישומים לפחות).")


def insight_restrictions(df):
    r = df[df["restr"] != ""]
    if r.empty:
        return None
    vc = _vc(r["restr"])
    parts = ", ".join(f"{k}: {n(v)}" for k, v in vc.items())
    return (f"{n(len(r))} רישומים ({n(r['kablan'].nunique())} קבלנים) נושאים הגבלה בפנקס — "
            f"{parts}.")


def insight_corp(df):
    by = df.groupby("sivug")["corp"].mean()
    if "5" not in by or "1" not in by or by["5"] - by["1"] < 0.2:
        return None
    return (f"ככל שהסיווג עולה, כך גובר משקלם של התאגידים: {pct(by['5'])} מהרישומים בסיווג 5 "
            f"שייכים לחברות או שותפויות, לעומת {pct(by['1'])} בסיווג 1"
            + (" — שם רוב הרשומים עוסקים יחידים." if by["1"] < 0.5 else "."))


# ── charts ───────────────────────────────────────────────────────────────


def _bar(items):
    return {"names": [k for k, _ in items], "values": [v for _, v in items]}


def compute(frames):
    df = _prepare(frames.pop("main"))
    c = _contractors(df)
    now = _latest(df)
    partial = not (now.month == 12 and now.day >= 31)
    sivugs = _sivug_order(set(df["sivug"]))
    bvc = _vc(df["branch"])

    # 1. branches × sivug (registrations)
    top_b = list(bvc.index[:TOP_BRANCHES])
    rest_b = df[~df["branch"].isin(top_b)]
    bs = df.groupby(["branch", "sivug"]).size()
    rs = rest_b.groupby("sivug").size()
    names = top_b + (["שאר הענפים"] if len(rest_b) else [])
    branches = {
        "names": names,
        "series": [{"name": f"סיווג {s}",
                    "data": [int(bs.get((b, s), 0)) for b in top_b]
                    + ([int(rs.get(s, 0))] if len(rest_b) else [])} for s in sivugs],
        "values": [int(bvc[b]) for b in top_b] + ([len(rest_b)] if len(rest_b) else []),
        "unl": [round(float(bs.get((b, "5"), 0)) / int(bvc[b]) * 100, 1) for b in top_b]
        + ([round(float(rs.get("5", 0)) / len(rest_b) * 100, 1)] if len(rest_b) else []),
    }

    # 2. classification ladder (sivug × group) + ceilings
    groups = [g for g in GROUP_ORDER if (df["group"] == g).any()]
    groups += sorted(set(df["group"]) - set(GROUP_ORDER))
    sg = df.groupby(["sivug", "group"]).size()
    hk = (df.groupby(["sivug", "group", "hekef"]).size().reset_index(name="c")
          .sort_values(["sivug", "group", "c", "hekef"], ascending=[True, True, False, True])
          .drop_duplicates(["sivug", "group"]).set_index(["sivug", "group"])["hekef"])
    ladder_rows = []
    for s in sivugs:
        for g in groups:
            cnt = int(sg.get((s, g), 0))
            if not cnt:
                continue
            h = hk.get((s, g), "")
            num = pd.to_numeric(h.replace(",", ""), errors="coerce")
            ceiling = "ללא הגבלה" if h == "ב.מ." else (n(num) if pd.notna(num) else "—")
            ladder_rows.append({"sivug": s, "group": g, "ceiling": ceiling, "count": cnt})
    ladder = {"x": [f"סיווג {s}" for s in sivugs],
              "series": [{"name": f"קבוצה {g}", "data": [int(sg.get((s, g), 0)) for s in sivugs]}
                         for g in groups]}

    # 3. heatmap: share of each branch's registrations per sivug
    heat_b = list(bvc.index[:HEAT_BRANCHES])
    cells = []
    for yi, b in enumerate(heat_b):
        tot = int(bvc[b])
        for xi, s in enumerate(sivugs):
            cnt = int(bs.get((b, s), 0))
            cells.append([xi, yi, round(cnt / tot * 100, 1), cnt])
    heat = {"x": list(sivugs), "y": heat_b, "cells": cells,
            "max": max([v[2] for v in cells] + [1])}

    # 4. new contractors per year (contractor level, by first registration)
    cy = c["first"].dt.year.dropna().astype(int)
    years = list(range(int(cy.min()), now.year + 1))
    yvc = cy.value_counts()
    by_year = {"x": [str(v) for v in years], "y": [int(yvc.get(v, 0)) for v in years],
               "partial": partial}
    day_vc = c["first"].dropna().dt.normalize().value_counts().sort_index()
    day_vc = day_vc.sort_values(ascending=False, kind="stable")
    bulk = None
    if len(day_vc) and day_vc.iloc[0] >= 0.015 * len(c):
        bulk = {"date": f"{day_vc.index[0].day}.{day_vc.index[0].month}.{day_vc.index[0].year}",
                "count": n(day_vc.iloc[0])}

    # 5. last 24 months
    months = pd.period_range(end=now.to_period("M"), periods=MONTHS, freq="M")
    pm = c["first"].dropna().dt.to_period("M").value_counts()
    monthly = {"x": [f"{p.month:02d}/{p.year}" for p in months], "y": [int(pm.get(p, 0)) for p in months]}

    # 6. age of the current classification, by tier
    age = ((now - df["sug_date"]).dt.days / 365.25).clip(lower=0)
    n_nodate = int(df["sug_date"].isna().sum())
    age_names = [_bucket(lo, hi, "") for lo, hi in AGE_BUCKETS]
    age_series = []
    for tname, tset in TIERS:
        m = df["sivug"].isin(tset)
        row = []
        for lo, hi in AGE_BUCKETS:
            sel = m & (age >= lo) & ((age < hi) if hi is not None else True)
            row.append(int(sel.sum()))
        age_series.append({"name": tname, "data": row})
    age_tot = [sum(s["data"][i] for s in age_series) for i in range(len(AGE_BUCKETS))]
    sug_age = {"names": age_names, "series": age_series, "values": age_tot}
    recent_share = age_tot[0] / max(sum(age_tot), 1)

    # 7. towns (contractor level)
    tvc = _vc(c.loc[c["town"] != "", "town"])
    towns = _bar([(k, int(v)) for k, v in tvc.head(TOP_TOWNS).items()])
    towns_rest = (len(tvc) - TOP_TOWNS, int(tvc.iloc[TOP_TOWNS:].sum())) if len(tvc) > TOP_TOWNS else None

    # 8. recognised share per sivug
    rec_by = df.groupby("sivug")["rec"].mean()
    rec_s = [s for s in sivugs if s != "ק"]
    recognised = {"names": [f"סיווג {s}" for s in rec_s],
                  "values": [round(float(rec_by.get(s, 0)) * 100, 1) for s in rec_s]}

    # 9. basis: employing professionals, per big branch
    big = [b for b in bvc.index if bvc[b] >= MIN_BRANCH_ROWS]
    st = df[df["branch"].isin(big)].groupby("branch")["staff"].mean()
    st = st.sort_index().sort_values(ascending=False, kind="stable")
    staff = {"names": list(st.index), "values": [round(float(v) * 100, 1) for v in st.values]}

    # 10. breadth: branches per contractor
    breadth = _bar([(_bucket(lo, hi), int(((c["branches"] >= lo) &
                     ((c["branches"] <= hi) if hi is not None else True)).sum()))
                    for lo, hi in BREADTH_BUCKETS])

    # 11. multi-branch leaders (named businesses)
    lead = c.sort_values(["branches", "n5", "name"], ascending=[False, False, True]).head(TOP_LEADERS)
    lead = lead[lead["branches"] >= 3]
    leaders = {"names": list(lead["name"]),
               "n5": [int(v) for v in lead["n5"]],
               "other": [int(a - b) for a, b in zip(lead["branches"], lead["n5"])],
               "values": [int(v) for v in lead["branches"]]}

    # 12. corporation share per sivug
    corp_by = df.groupby("sivug")["corp"].mean()
    corp = {"names": [f"סיווג {s}" for s in sivugs],
            "values": [round(float(corp_by.get(s, 0)) * 100, 1) for s in sivugs]}

    # 13. seniority by top classification (contractor level)
    sen = (now - c["first"]).dt.days / 365.25
    box_names, box_data, box_rows = [], [], []
    for s in [x for x in SIVUG_ORDER if x in sivugs] + ["אחר"]:
        v = np.sort(sen[c["top_sivug"] == s].dropna().to_numpy())
        if len(v) < 10:
            continue
        q = [round(float(np.percentile(v, p)), 1) for p in (5, 25, 50, 75, 95)]
        label = "סיווג אחר" if s == "אחר" else f"סיווג {s}"
        box_names.append(label)
        box_data.append(q)
        box_rows.append({"name": label, "count": int(len(v)), "q1": q[1], "med": q[2], "q3": q[3]})
    seniority = {"names": box_names, "data": box_data, "rows": box_rows}

    # restrictions table
    rr = df[df["restr"] != ""]
    restr_rows = []
    for k, v in _vc(rr["restr"]).items():
        sub = rr[rr["restr"] == k]
        restr_rows.append({"name": k, "count": int(v), "contractors": int(sub["kablan"].nunique()),
                           "branches": int(sub["branch"].nunique())})

    rules = [
        ("concentration", insight_concentration(df, bvc)),
        ("ladder", insight_ladder(df, c)),
        ("growth", insight_growth(c, now, partial)),
        ("ytd", insight_ytd(c, now)),
        ("recognised", insight_recognised(df, c)),
        ("breadth", insight_breadth(c)),
        ("town", insight_town(c)),
        ("staff", insight_staff(df, bvc)),
        ("corp", insight_corp(df)),
        ("restrictions", insight_restrictions(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # KPIs
    ytd, ytd_prev = _ytd(c, now)
    ch = (ytd - ytd_prev) / ytd_prev if ytd_prev else 0
    ytd_tone = "brand" if not ytd_prev or abs(ch) < 0.03 else ("ok" if ch > 0 else "warn")
    unl = int((c["n5"] > 0).sum())
    rec_n = int(c["rec"].sum())
    n_restr = int(len(rr))
    mean_br = math.fsum(c["branches"].astype(float)) / len(c)
    first_year = int(cy.min())
    top_label = f"סיווג {SIVUG_ORDER[-1]}"

    return {
        "agent_data": {
            "summary_he": (f"בדיקת קבלן רשום בפנקס הקבלנים לפי שם, מספר קבלן או יישוב: {n(len(c))} קבלנים "
                           f"ב-{n(len(bvc))} ענפי עבודה, עם סיווג, היקף כספי מותר והכרה ממשלתית. "
                           f"מעודכן עד {d_he(now)}."),
            "dataset_kind": "registry",
            "suggested_tags": ["קבלנים", "פנקס הקבלנים", "בנייה", "סיווג קבלנים", "תשתיות"],
            "related_ids": ["bddf37d6-5300-4179-bc0b-f2577fbc3a30",
                            "2fe07949-9538-4891-9de7-50a352bcbd80",
                            "c0beab05-9061-4dad-868c-40142260d35f",
                            "688d7791-b596-4b64-a307-113e8258b12a",
                            "246d949c-a253-4811-8a11-41a137d3d613"],
            "temporal_coverage": f"{first_year}/{now.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "contractors": {"value": len(c), "display": n(len(c)), "tone": "brand"},
            "registrations": {"value": len(df), "display": n(len(df)), "tone": "brand"},
            "branches": {"value": len(bvc), "display": n(len(bvc)), "tone": "brand"},
            "unlimited": {"value": unl, "display": n(unl), "tone": "info"},
            "recognised": {"value": rec_n, "display": n(rec_n), "tone": "info"},
            # New contractors this year vs the same window last year: growth of
            # the registry is good news, a ≥3% fall is a caution.
            "ytd": {"value": ytd, "display": n(ytd), "tone": ytd_tone},
            "restricted": {"value": n_restr, "display": n(n_restr),
                           "tone": "warn" if n_restr else "ok"},
        },
        "charts": {
            "branches": branches,
            "ladder": ladder,
            "heat": heat,
            "by_year": by_year,
            "monthly": monthly,
            "sug_age": sug_age,
            "towns": towns,
            "recognised": recognised,
            "staff": staff,
            "breadth": breadth,
            "leaders": leaders,
            "corp": corp,
            "seniority": seniority,
        },
        "tables": {"ladder": ladder_rows, "restrictions": restr_rows},
        "flags": {"leaders": len(leaders["names"]) >= 3, "restrictions": bool(restr_rows),
                  "seniority": len(box_names) >= 2},
        "insights": insights,
        "labels": {
            "lede": (f"{n(len(c))} קבלנים רשומים בפנקס, ב-{n(len(df))} רישומים — רישום אחד לכל ענף "
                     f"שבו הקבלן מורשה לעבוד, בממוצע {mean_br:.2f} ענפים לקבלן. לכל רישום סיווג "
                     f"(ק, 1–5) וקבוצה (א–ג) הקובעים את ההיקף הכספי המרבי לעבודה בודדת. "
                     f"העדכון האחרון בקובץ: {d_he(now)}."),
            "year": str(now.year),
            "top": top_label,
            "in_top": f"ב{top_label}",
            "top_note": (f"הסיווג והקבוצה קובעים את ההיקף הכספי המרבי לעבודה בודדת; "
                         f"ב{top_label} אין הגבלה."),
            "ytd_kpi": f"קבלנים חדשים מתחילת {now.year}",
            "branches_note": (f"{TOP_BRANCHES} הענפים הגדולים לפי מספר רישומים, צבועים לפי סיווג; "
                              f"שאר {n(max(len(bvc) - TOP_BRANCHES, 0))} הענפים מאוחדים."),
            "branches_aria": f"גרף עמודות מוערמות: רישומים ב-{TOP_BRANCHES} הענפים הגדולים לפי סיווג.",
            "ladder_aria": "גרף עמודות מוערמות: רישומים לפי סיווג וקבוצה.",
            "heat_aria": f"מפת חום: התפלגות הסיווג בכל אחד מ-{HEAT_BRANCHES} הענפים הגדולים, באחוזים.",
            "by_year_note": (f"קבלנים לפי שנת הרישום הראשון בפנקס. השנה {now.year} חלקית — עד {d_he(now)}."
                             + (f" ב-{bulk['date']} נרשמו {bulk['count']} קבלנים ביום אחד — "
                                f"מועד רישום מרוכז." if bulk else "")),
            "by_year_aria": f"גרף עמודות: קבלנים חדשים לפי שנה, {first_year}–{now.year}.",
            "monthly_aria": f"גרף עמודות: קבלנים חדשים בכל חודש, {MONTHS} החודשים האחרונים.",
            "sug_age_note": (f"כמה זמן עבר מאז נקבע הסיווג הנוכחי של כל רישום (עד {d_he(now)}). "
                             f"{pct(recent_share)} מהרישומים סווגו או עודכנו בשנה האחרונה."
                             + (f" {n(n_nodate)} רישומים ללא תאריך סיווג אינם נכללים." if n_nodate else "")),
            "sug_age_aria": "גרף עמודות מוערמות: רישומים לפי ותק הסיווג הנוכחי, בשנים, לפי דרגת סיווג.",
            "towns_note": ("לפי היישוב הרשום של הקבלן."
                           + (f" בשאר {n(towns_rest[0])} היישובים רשומים עוד {n(towns_rest[1])} קבלנים."
                              if towns_rest else "")),
            "towns_aria": f"תרשים עמודות: {TOP_TOWNS} היישובים עם מספר הקבלנים הגבוה ביותר.",
            "recognised_aria": "תרשים עמודות: שיעור הרישומים של קבלנים מוכרים בכל סיווג.",
            "staff_note": (f"שיעור הרישומים שנעשו על סמך העסקת עובדים מקצועיים (ולא כישורי המנהל), "
                           f"בענפים עם {n(MIN_BRANCH_ROWS)} רישומים לפחות."),
            "staff_aria": "תרשים עמודות: שיעור הרישום על סמך עובדים מקצועיים לפי ענף.",
            "breadth_aria": "תרשים עמודות: קבלנים לפי מספר הענפים שבהם הם רשומים.",
            "leaders_note": (f"{TOP_LEADERS} הקבלנים הרשומים במספר הענפים הגדול ביותר; "
                             f"החלק הכהה — ענפים בסיווג 5."),
            "leaders_aria": "גרף עמודות מוערמות: הקבלנים הרשומים במספר הענפים הגדול ביותר.",
            "corp_aria": "תרשים עמודות: שיעור הרישומים של תאגידים בכל סיווג.",
            "seniority_aria": "תרשים קופסה: ותק הקבלנים בפנקס בשנים, לפי הסיווג הגבוה שלהם.",
            "seniority_note": (f"שנים מאז הרישום הראשון בפנקס, לפי הסיווג הגבוה ביותר של הקבלן; "
                               f"הקופסה — הרבעון התחתון עד העליון, הקווים — אחוזונים חמישי ותשעים וחמישה."),
            "restrictions_note": (f"הגבלות הרשומות בתיאור הענף: {n(n_restr)} רישומים "
                                  f"({pct(n_restr / len(df), 2)} מהפנקס)."),
        },
    }
