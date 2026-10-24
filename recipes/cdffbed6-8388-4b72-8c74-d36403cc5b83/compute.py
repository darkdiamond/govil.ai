"""רכבת ישראל — דיוק בתחנות (station punctuality), monthly.

One row per month × station × status, with the number of train stops in
that status: בזמן (on time), איחור (late), and — until the reporting changed —
הקדמה ביציאה (early departure). Shares are computed from the counts.

Two caveats the page discloses rather than hides:
- the early-departure status exists only in the earlier part of the data;
  after it disappears every stop is either on time or late, so on-time shares
  across that boundary are not strictly comparable;
- gaps in the monthly series are shown as gaps.
The latest month is flagged partial when its stop count is well below the
recent norm, and kept out of comparisons.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
ON, LATE, EARLY = "בזמן", "איחור", "הקדמה ביציאה"
PARTIAL_RATIO = 0.85
MIN_STATION_STOPS = 5000   # station ranking floor over the last 12 months
TOP_N = 12
HEAT_STATIONS = 20


def mlabel(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def pct(v):
    return f"{v * 100:.1f}%"


def _station(name):
    """Same source quirk as the planned-vs-operated dataset: an acronym's
    gershayim lands at the end ('נתבג"'); move it before the first word's
    last letter. Display only."""
    name = name.strip()
    if not name.endswith('"') or name.count('"') != 1:
        return name
    name = name[:-1].rstrip()
    first, _, rest = name.partition(" ")
    if len(first) < 2:
        return name
    return f'{first[:-1]}"{first[-1]} {rest}'.strip()


def _prepare(df):
    out = pd.DataFrame({
        "y": pd.to_numeric(df["shana"], errors="coerce"),
        "m": pd.to_numeric(df["hodesh"], errors="coerce"),
        "station": df["train_station_nm"].map(_station),
        "status": df["station_status_nm"].str.strip(),
        "n": pd.to_numeric(df["status_count"], errors="coerce").fillna(0),
    }).dropna(subset=["y", "m"])
    out = out[(out["m"] >= 1) & (out["m"] <= 12) & (out["station"] != "")]
    out["p"] = [pd.Period(year=int(a), month=int(b), freq="M") for a, b in zip(out["y"], out["m"])]
    return out


def _shares(g):
    t = g.sum(axis=1)
    return pd.DataFrame({"total": t,
                         "on": g.get(ON, 0) / t,
                         "late": g.get(LATE, 0) / t,
                         "early": g.get(EARLY, 0) / t})


def insight_latest(mon, end):
    r = mon.loc[end]
    prev = end - 12
    tail = ""
    if prev in mon.index:
        d = (r["on"] - mon.loc[prev, "on"]) * 100
        tail = (f", בדומה ל{mlabel(prev)}" if abs(d) < 0.5 else
                f" — {'שיפור' if d > 0 else 'הרעה'} של {abs(d):.1f} נקודות אחוז לעומת {mlabel(prev)}")
    return f"ב{mlabel(end)} הגיעו {pct(r['on'])} מהעצירות בתחנות בזמן{tail}."


def insight_12m(cur, prv):
    if cur["total"] <= 0 or prv["total"] <= 0:
        return None
    d = (cur["on"] - prv["on"]) * 100
    trend = (f"דומה ל-12 החודשים שקדמו להם ({pct(prv['on'])})" if abs(d) < 0.5 else
             f"{'שיפור' if d > 0 else 'הרעה'} של {abs(d):.1f} נקודות אחוז לעומת 12 החודשים שקדמו להם")
    return f"ב-12 החודשים האחרונים {pct(cur['on'])} מהעצירות היו בזמן — {trend}."


def insight_worst(st):
    if len(st) < 5:
        return None
    w, b = st.iloc[0], st.iloc[-1]
    return (f"בתחנת {w.name} נרשם שיעור האיחורים הגבוה ביותר ב-12 החודשים האחרונים: "
            f"{pct(w['late'])} מהעצירות, לעומת {pct(b['late'])} בתחנת {b.name}, הדייקנית ביותר.")


def insight_improved(chg):
    if chg.empty:
        return None
    best = chg.iloc[0]
    worst = chg.iloc[-1]
    if best["delta"] > -0.01 and worst["delta"] < 0.01:
        return None
    parts = []
    if best["delta"] <= -0.01:
        parts.append(f"שיעור האיחורים ירד הכי הרבה בתחנת {best.name} "
                     f"({pct(best['before'])} ← {pct(best['after'])})")
    if worst["delta"] >= 0.01:
        parts.append(f"ועלה הכי הרבה בתחנת {worst.name} ({pct(worst['before'])} ← {pct(worst['after'])})")
    return "בהשוואה לשנה שקדמה, " + " ".join(parts) + "."


def insight_worst_month(mon, end):
    last24 = mon[mon.index > end - 24]
    last24 = last24[last24.index <= end]
    if len(last24) < 6:
        return None
    p = last24["on"].idxmin()
    med = last24["on"].median()
    if med - last24.loc[p, "on"] < 0.02:
        return None
    return (f"החודש החלש ביותר בשנתיים האחרונות היה {mlabel(p)}: רק {pct(last24.loc[p, 'on'])} "
            f"מהעצירות היו בזמן, לעומת חציון של {pct(med)}.")


def insight_early(mon):
    has = mon[mon["early"] > 0]
    if has.empty:
        return None
    last = has.index.max()
    if last == mon.index.max():
        return None
    return (f"סטטוס \"הקדמה ביציאה\" דווח עד {mlabel(last)} בלבד (בממוצע {pct(has['early'].mean())} "
            f"מהעצירות); מאז כל עצירה מסווגת כבזמן או כאיחור, ולכן שיעורי הדיוק לפני "
            f"ואחרי {last.year + 1} אינם ניתנים להשוואה מלאה.")


def compute(frames):
    df = _prepare(frames["stops"])
    piv = df.pivot_table(index="p", columns="status", values="n", aggfunc="sum").fillna(0).sort_index()
    mon = _shares(piv)
    full_range = pd.period_range(mon.index.min(), mon.index.max(), freq="M")
    missing = [p for p in full_range if p not in mon.index]

    prior = mon["total"].iloc[-7:-1]
    partial = bool(len(prior) >= 3 and mon["total"].iloc[-1] < PARTIAL_RATIO * prior.median())
    complete = mon.iloc[:-1] if partial else mon
    end = complete.index[-1]

    def window(lo, hi):
        w = df[(df["p"] > lo) & (df["p"] <= hi)]
        return w

    cur_w, prv_w = window(end - 12, end), window(end - 24, end - 12)

    def totals(w):
        g = w.groupby("status")["n"].sum()
        t = g.sum()
        return {"total": t, "on": g.get(ON, 0) / t if t else 0, "late": g.get(LATE, 0) / t if t else 0}

    cur, prv = totals(cur_w), totals(prv_w)

    st_piv = cur_w.pivot_table(index="station", columns="status", values="n", aggfunc="sum").fillna(0)
    st = _shares(st_piv)
    st = st[st["total"] >= MIN_STATION_STOPS]
    st = st.sort_index().sort_values("late", ascending=False, kind="stable")

    pv_piv = prv_w.pivot_table(index="station", columns="status", values="n", aggfunc="sum").fillna(0)
    pv = _shares(pv_piv)
    both = st.index.intersection(pv[pv["total"] >= MIN_STATION_STOPS].index)
    chg = pd.DataFrame({"before": pv.loc[both, "late"], "after": st.loc[both, "late"]})
    chg["delta"] = chg["after"] - chg["before"]
    chg = chg.sort_index().sort_values("delta", kind="stable")

    # Charts ------------------------------------------------------------
    mf = mon.reindex(full_range)
    monthly = {"x": [str(p) for p in full_range],
               "on": [None if pd.isna(v) else round(float(v) * 100, 2) for v in mf["on"]],
               "late": [None if pd.isna(v) else round(float(v) * 100, 2) for v in mf["late"]],
               "early": [None if pd.isna(v) else round(float(v) * 100, 2) for v in mf["early"]]}

    yp = piv.loc[complete.index].groupby(complete.index.year).sum()
    ys = _shares(yp)
    yearly = {"x": [str(y) for y in ys.index],
              "on": [round(float(v) * 100, 2) for v in ys["on"]],
              "late": [round(float(v) * 100, 2) for v in ys["late"]],
              "early": [round(float(v) * 100, 2) for v in ys["early"]]}

    sp = piv.loc[complete.index].groupby(complete.index.month).sum()
    ss = _shares(sp)
    season = {"x": [MONTHS_HE[i - 1] for i in ss.index],
              "late": [round(float(v) * 100, 2) for v in ss["late"]]}

    stations = {"x": st.index[:TOP_N].tolist(),
                "late": [round(float(v) * 100, 2) for v in st["late"][:TOP_N]]}
    best = st.sort_values("late", kind="stable").head(TOP_N)
    stations_best = {"x": best.index.tolist(), "late": [round(float(v) * 100, 2) for v in best["late"]]}

    mov = pd.concat([chg.head(TOP_N // 2), chg.tail(TOP_N // 2)])
    mov = mov[~mov.index.duplicated()]
    movers = {"x": mov.index.tolist(),
              "before": [round(float(v) * 100, 2) for v in mov["before"]],
              "after": [round(float(v) * 100, 2) for v in mov["after"]]}

    busiest = cur_w.groupby("station")["n"].sum().sort_index().sort_values(ascending=False, kind="stable")
    hs = busiest.index[:HEAT_STATIONS].tolist()
    months12 = [p for p in pd.period_range(end - 11, end, freq="M")]
    hw = cur_w[cur_w["station"].isin(hs)].pivot_table(index=["station", "p"], columns="status",
                                                       values="n", aggfunc="sum").fillna(0)
    hsh = _shares(hw)
    cells = [[months12.index(p), hs.index(s), round(float(v) * 100, 1)]
             for (s, p), v in hsh["late"].items() if p in months12]
    heat = {"months": [str(p) for p in months12], "stations": hs, "cells": cells,
            "min": round(float(hsh["late"].min()) * 100, 1) if len(hsh) else 0,
            "max": round(float(hsh["late"].max()) * 100, 1) if len(hsh) else 1}

    rules = [
        ("latest", insight_latest(complete, end)),
        ("rate12", insight_12m(cur, prv)),
        ("worst", insight_worst(st)),
        ("movers", insight_improved(chg)),
        ("worst_month", insight_worst_month(complete, end)),
        ("early", insight_early(mon)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    kpis = {
        "on_last": {"value": float(complete.loc[end, "on"]), "display": pct(complete.loc[end, "on"])},
        "month_last": {"value": str(end), "display": mlabel(end)},
        "on12": {"value": float(cur["on"]), "display": pct(cur["on"])},
        "stops12": {"value": int(cur["total"]), "display": f"{int(cur['total']):,}"},
        "stations": {"value": int(df["station"].nunique()), "display": f"{df['station'].nunique()}"},
    }

    p0, p1 = mon.index[0], mon.index[-1]
    gap_note = (f" חסרים במאגר {len(missing)} חודשים (מ{mlabel(missing[0])} עד {mlabel(missing[-1])})."
                if missing else "")
    partial_note = f" {mlabel(p1)} חלקי ואינו נכלל בהשוואות." if partial else ""
    labels = {
        "lede": (f"דיוק רכבת ישראל בכל תחנה: כמה מהעצירות היו בזמן וכמה באיחור, מ{mlabel(p0)} עד "
                 f"{mlabel(p1)}, ב-{df['station'].nunique()} תחנות.{gap_note}{partial_note}"),
        "monthly_aria": f"גרף: אחוז העצירות בזמן, באיחור ובהקדמה בכל חודש, {mlabel(p0)} עד {mlabel(p1)}.",
        "yearly_aria": "תרשים: התפלגות העצירות לפי סטטוס בכל שנה.",
        "season_aria": "תרשים עמודות: שיעור האיחורים לפי חודש בשנה, כל השנים יחד.",
        "stations_aria": f"תרשים עמודות: {TOP_N} התחנות עם שיעור האיחורים הגבוה ביותר ב-12 החודשים האחרונים.",
        "best_aria": f"תרשים עמודות: {TOP_N} התחנות הדייקניות ביותר ב-12 החודשים האחרונים.",
        "movers_aria": "תרשים: שיעור האיחורים בתחנות שהשתנו הכי הרבה, השנה מול השנה הקודמת.",
        "heat_aria": f"מפת חום: שיעור האיחורים ב-{len(hs)} התחנות העמוסות לפי חודש, 12 החודשים האחרונים.",
        "stations_note": f"תחנות עם {MIN_STATION_STOPS:,} עצירות לפחות ב-12 החודשים האחרונים.",
    }

    tables = {
        "yearly": [{"y": x, "on": f"{a:.2f}", "late": f"{b:.2f}", "early": f"{c:.2f}"}
                   for x, a, b, c in zip(yearly["x"], yearly["on"], yearly["late"], yearly["early"])],
        "season": [{"m": x, "late": f"{v:.2f}"} for x, v in zip(season["x"], season["late"])],
        "stations": [{"s": s, "late": f"{v:.2f}"} for s, v in zip(stations["x"], stations["late"])],
        "best": [{"s": s, "late": f"{v:.2f}"} for s, v in zip(stations_best["x"], stations_best["late"])],
        "movers": [{"s": s, "before": f"{a:.2f}", "after": f"{b:.2f}"}
                   for s, a, b in zip(movers["x"], movers["before"], movers["after"])],
    }

    return {
        "agent_data": {
            "summary_he": (f"דיוק רכבת ישראל ב-{df['station'].nunique()} תחנות, {mlabel(p0)}–{mlabel(p1)}: "
                           f"ב-12 החודשים האחרונים {pct(cur['on'])} מהעצירות היו בזמן."),
            "dataset_kind": "timeseries",
            "related_ids": ["63b7bf0b-69eb-4a73-9b98-b9fd2b8a4b5b"],
            "suggested_tags": ["רכבת ישראל", "תחבורה ציבורית", "דיוק", "תחנות רכבת"],
            "temporal_coverage": f"{p0}/{p1}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"monthly": monthly, "yearly": yearly, "season": season, "stations": stations,
                   "best": stations_best, "movers": movers, "heat": heat},
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
