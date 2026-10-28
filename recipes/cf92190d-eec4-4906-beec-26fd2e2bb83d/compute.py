"""מאגר החלטות בית הדין לעררים — decisions of the appeals tribunals under the
Entry into Israel Law (asylum, family unification, detention, residency…).

One row per decision: request number, case number, tribunal, judge, date,
request type and subject. The data names no appellant. Judges are named
(decision-makers in a public capacity); case and request numbers are
identifiers of individuals' cases and never appear on the page.

"Now" is the latest decision date in the data; the current year is partial,
so year-over-year rules compare the last two full years.
"""
import pandas as pd

TOP_TYPES = 10
TOP_JUDGES = 15
HEAT_TOPICS = 10
MONTHS = 24
CASE_BINS = [0, 1, 2, 3, 5, 10, float("inf")]
CASE_LABELS = ["1", "2", "3", "4–5", "6–10", "מעל 10"]
INTERIM = {"בקשה לסעד זמני", "בקשה לצו ביניים"}
MAIN = "בקשה ראשית"


def _int(n):
    return f"{int(n):,}"


def _swing_tone(cur, prev, threshold=0.10):
    """KPI colour for a directionless count: info on a big year-over-year swing."""
    if not prev:
        return "brand"
    return "info" if abs(cur - prev) / prev >= threshold else "brand"


def _pct(x):
    return f"{x * 100:.1f}%"


def _vc(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _top(vc, n, other="אחר"):
    head = [(k, int(v)) for k, v in vc.head(n).items()]
    rest = int(vc.iloc[n:].sum())
    if rest:
        head.append((other, rest))
    return head


def _prepare(df):
    out = pd.DataFrame({
        "case": df["מספר תיק"].str.strip(),
        "court": df["בית דין"].str.strip(),
        "judge": df["שם דיין"].str.strip(),
        "date": pd.to_datetime(df["תאריך החלטה"], format="%d/%m/%Y", errors="coerce"),
        "rtype": df["סוג בקשה"].str.strip(),
        "topic": df["נושא"].str.strip(),
    })
    return out.dropna(subset=["date"])


def insight_volume(df, now):
    full, prev = now.year - 1, now.year - 2
    y = df["date"].dt.year
    a, b = int((y == full).sum()), int((y == prev).sum())
    vc = y.value_counts()
    peak = int(vc.idxmax())
    if b < 50:
        return None
    ch = (a - b) / b
    trend = ("בדומה לשנה הקודמת" if abs(ch) < 0.03
             else f"{'עלייה' if ch > 0 else 'ירידה'} של {_pct(abs(ch))} לעומת {prev} ({_int(b)})")
    tail = (f" שנת השיא הייתה {peak} עם {_int(vc.max())} החלטות." if peak != full else
            f" זו שנת השיא במאגר.")
    return f"ב-{full} ניתנו {_int(a)} החלטות — {trend}.{tail}"


def insight_topic(df):
    vc = _vc(df["topic"])
    share = vc.iloc[0] / len(df)
    return (f"הנושא הנפוץ ביותר בכלל ההחלטות הוא '{vc.index[0]}' ({_pct(share)}), ואחריו "
            f"'{vc.index[1]}' ({_pct(vc.iloc[1] / len(df))}).")


def insight_topic_now(df, now):
    full = now.year - 1
    recent = df[df["date"].dt.year == full]
    if len(recent) < 200:
        return None
    vc_now = _vc(recent["topic"])
    vc_all = _vc(df["topic"])
    lead = vc_now.index[0]
    if lead == vc_all.index[0]:
        return (f"גם ב-{full} '{lead}' הוא הנושא המוביל, עם {_pct(vc_now.iloc[0] / len(recent))} "
                f"מההחלטות.")
    return (f"ב-{full} הנושא המוביל הוא '{lead}' ({_pct(vc_now.iloc[0] / len(recent))} מההחלטות), "
            f"לעומת '{vc_all.index[0]}' שמוביל לאורך כל התקופה.")


def insight_court(df):
    vc = _vc(df["court"])
    return (f"{vc.index[0]} נתן {_pct(vc.iloc[0] / len(df))} מכלל ההחלטות ({_int(vc.iloc[0])}); "
            f"{vc.index[1]} — {_pct(vc.iloc[1] / len(df))}.")


def insight_judge(df, now):
    recent = df[(df["date"] > now - pd.Timedelta(days=365)) & (df["judge"] != "")]
    if len(recent) < 200:
        return None
    vc = _vc(recent["judge"])
    return (f"בשנה האחרונה נתנו {_int(vc.size)} דיינים החלטות; הדיין עם מספר ההחלטות הגבוה "
            f"ביותר הוא {vc.index[0]} ({_int(vc.iloc[0])}, {_pct(vc.iloc[0] / len(recent))}).")


def insight_requests(df):
    main = int((df["rtype"] == MAIN).sum())
    interim = int(df["rtype"].isin(INTERIM).sum())
    return (f"{_pct(main / len(df))} מההחלטות ניתנו בבקשות ראשיות (בערר עצמו), ו-{_pct(interim / len(df))} "
            f"בבקשות לסעד זמני או לצו ביניים.")


def insight_cases(per_case):
    multi = int((per_case >= 3).sum())
    return (f"בתיקים נרשמו בממוצע {per_case.mean():.1f} החלטות; ב-{_pct(multi / len(per_case))} "
            f"מהתיקים ({_int(multi)}) ניתנו שלוש החלטות או יותר.")


def compute(frames):
    df = _prepare(frames["decisions"])
    now = df["date"].max()
    years = sorted(df["date"].dt.year.unique())
    y = df["date"].dt.year

    courts = list(_vc(df["court"]).index)
    by_yc = df.groupby([y, "court"]).size()
    yearly = {"x": [str(v) for v in years],
              "series": [{"name": c, "data": [int(by_yc.get((v, c), 0)) for v in years]} for c in courts],
              "total": [int((y == v).sum()) for v in years]}

    topics = [(k, int(v)) for k, v in _vc(df["topic"]).items()]
    heat_topics = [k for k, _ in topics[:HEAT_TOPICS]]
    cells = []
    for i, v in enumerate(years):
        tot = int((y == v).sum())
        sub = df[y == v]["topic"].value_counts()
        for j, t in enumerate(heat_topics):
            c = int(sub.get(t, 0))
            if tot and c:
                cells.append([i, j, round(c / tot * 100, 1), c])
    heat = {"x": [str(v) for v in years], "y": heat_topics, "cells": cells,
            "max": max((c[2] for c in cells), default=0)}

    rtypes = _top(_vc(df["rtype"].replace("", "לא צוין")), TOP_TYPES)
    judges = _top(_vc(df.loc[df["judge"] != "", "judge"]), TOP_JUDGES, "שאר הדיינים")
    recent = df[(df["date"] > now - pd.Timedelta(days=365)) & (df["judge"] != "")]
    judges_recent = _top(_vc(recent["judge"]), TOP_JUDGES, "שאר הדיינים")

    months = pd.period_range(end=now.to_period("M"), periods=MONTHS, freq="M")
    pm = df["date"].dt.to_period("M").value_counts()
    monthly = {"x": [str(p) for p in months], "y": [int(pm.get(p, 0)) for p in months]}

    per_case = df.groupby("case").size()
    cb = pd.cut(per_case, CASE_BINS, labels=CASE_LABELS).value_counts()
    cases = {"names": CASE_LABELS, "values": [int(cb.get(l, 0)) for l in CASE_LABELS]}

    ct = df.groupby(["court", "topic"]).size()
    court_topic = {"courts": courts, "topics": heat_topics,
                   "rows": [[round(int(ct.get((c, t), 0)) / max(int((df["court"] == c).sum()), 1) * 100, 1)
                             for t in heat_topics] for c in courts]}

    rules = [
        ("volume", insight_volume(df, now)),
        ("topic", insight_topic(df)),
        ("topic_now", insight_topic_now(df, now)),
        ("court", insight_court(df)),
        ("judge", insight_judge(df, now)),
        ("request_mix", insight_requests(df)),
        ("cases", insight_cases(per_case)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]
    now_he = f"{now.day}/{now.month}/{now.year}"
    full = now.year - 1

    def bar(items):
        return {"names": [k for k, _ in items], "values": [v for _, v in items]}

    return {
        "agent_data": {
            "summary_he": (f"החלטות בתי הדין לעררים לפי חוק הכניסה לישראל: {_int(len(df))} החלטות "
                           f"ב-{_int(per_case.size)} תיקים, {years[0]}–{years[-1]}, לפי נושא, בית דין "
                           f"ודיין. מעודכן עד {now_he}."),
            "dataset_kind": "timeseries",
            "related_ids": [],
            "suggested_tags": ["בתי דין לעררים", "הגירה", "מבקשי מקלט", "איחוד משפחות"],
            "temporal_coverage": f"{df['date'].min().strftime('%Y-%m-%d')}/{now.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "decisions": {"value": len(df), "display": _int(len(df)), "tone": "brand"},
            "cases": {"value": int(per_case.size), "display": _int(per_case.size), "tone": "brand"},
            # Caseload has no good/bad direction; a swing of ≥10% vs the
            # year before is flagged as notable (info).
            "last_year": {"value": int((y == full).sum()), "display": _int((y == full).sum()),
                          "tone": _swing_tone(int((y == full).sum()), int((y == full - 1).sum()))},
            "judges": {"value": int(recent["judge"].nunique()),
                       "display": _int(recent["judge"].nunique()), "tone": "brand"},
        },
        "charts": {
            "yearly": yearly,
            "topics": bar(topics),
            "heat": heat,
            "rtypes": bar(rtypes),
            "judges": bar(judges),
            "judges_recent": bar(judges_recent),
            "monthly": monthly,
            "cases": cases,
            "court_topic": court_topic,
        },
        "insights": insights,
        "labels": {
            "lede": (f"{_int(len(df))} החלטות של בתי הדין לעררים בענייני כניסה לישראל, מעמד ומקלט, "
                     f"מ-{years[0]} ועד {now_he}. המאגר אינו כולל את שמות העוררים."),
            "full_year": str(full),
            "yearly_aria": f"גרף עמודות מוערמות: החלטות לפי שנה ובית דין, {years[0]}–{years[-1]}.",
            "yearly_note": f"השנה האחרונה ({years[-1]}) חלקית — עד {now_he}.",
            "topics_aria": f"תרשים עמודות: ההחלטות לפי נושא, {len(topics)} נושאים.",
            "heat_aria": "מפת חום: חלקו של כל נושא מסך ההחלטות בכל שנה, באחוזים.",
            "rtypes_aria": f"תרשים עמודות: ההחלטות לפי סוג הבקשה, {TOP_TYPES} הנפוצים.",
            "judges_aria": f"תרשים עמודות: {TOP_JUDGES} הדיינים עם מספר ההחלטות הגבוה ביותר בכל התקופה.",
            "judges_recent_aria": "תרשים עמודות: הדיינים לפי מספר ההחלטות ב-12 החודשים האחרונים.",
            "judges_note": (f"ל-{_int((df['judge'] == '').sum())} החלטות לא צוין דיין והן אינן נספרות."),
            "monthly_aria": f"גרף עמודות: מספר ההחלטות בכל חודש, {MONTHS} החודשים האחרונים.",
            "cases_aria": "תרשים עמודות: התיקים לפי מספר ההחלטות שניתנו בהם.",
            "court_topic_aria": "תרשים עמודות מוערמות: התפלגות הנושאים בכל בית דין, באחוזים.",
        },
    }
