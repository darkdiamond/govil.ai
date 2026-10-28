"""מפלס ים המלח — monthly Dead Sea level since 1976.

One row per survey (about monthly; a few months carry two readings), level in
metres below sea level (negative). "Now" is the latest survey in the data.
The level has fallen almost every year; the page tracks the pace of that
decline, its seasonality and the rare wet years that interrupted it.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
RECENT_MONTHS = 36          # window of the "recent" chart
STEP_M = 5                  # milestone spacing (metres)
TOLERANCE_DAYS = 45         # a reading counts for "12 months ago" if this close
LRI, PDI = "⁦", "⁩"


def m(v):
    return f"{LRI}{v:.2f}{PDI}"


def cm(v):
    return f"{abs(v) * 100:,.0f}"


def kv(v, digits=2, signed=False):
    """A KPI value: bare number, real minus sign (U+2212), no bidi marks —
    the value box is dir=ltr and the unit lives in the label."""
    s = f"{v:+,.{digits}f}" if signed else f"{v:,.{digits}f}"
    return s.replace("-", "−")


def signed_cm(v):
    sign = "+" if v > 0 else "-" if v < 0 else ""
    return f"{LRI}{sign}{cm(v)}{PDI} ס״מ"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _prepare(df):
    out = pd.DataFrame({
        "d": pd.to_datetime(df["תאריך מדידה"], format="%d/%m/%Y", errors="coerce"),
        "lvl": pd.to_numeric(df["מפלס"], errors="coerce"),
    }).dropna()
    out = out.groupby("d", as_index=False)["lvl"].mean().sort_values("d")
    return out.reset_index(drop=True)


def _on_or_before(df, when, tol=TOLERANCE_DAYS):
    s = df[df["d"] <= when]
    if s.empty or (when - s.iloc[-1]["d"]).days > tol:
        return None
    return s.iloc[-1]


def _annual_change(df):
    """Change over each complete calendar year: the year-end level (latest
    reading on or before 31 Dec, within TOLERANCE_DAYS — surveys often close
    the year on 30 Nov) minus the previous year-end level."""
    ends = {}
    for y in sorted(df["d"].dt.year.unique()):
        row = _on_or_before(df, pd.Timestamp(year=int(y), month=12, day=31))
        if row is not None:
            ends[int(y)] = float(row["lvl"])
    return [(y, ends[y] - ends[y - 1]) for y in sorted(ends) if (y - 1) in ends]


def _milestones(df):
    """First date the level fell below each whole STEP_M-metre mark."""
    top, bottom = df["lvl"].iloc[0], df["lvl"].min()
    marks = []
    mark = -(int(-top // STEP_M) + 1) * STEP_M  # first whole mark below the start
    while mark >= bottom:
        hit = df[df["lvl"] <= mark]
        marks.append((mark, hit.iloc[0]["d"]))
        mark -= STEP_M
    return marks


def insight_now(df, last):
    prev = _on_or_before(df, last["d"] - pd.Timedelta(days=365))
    if prev is None:
        return None
    delta = last["lvl"] - prev["lvl"]
    word = "ירד" if delta < 0 else "עלה"
    return (f"נכון ל-{d_he(last['d'])} מפלס ים המלח עומד על {m(last['lvl'])} מ' — "
            f"ב-12 החודשים האחרונים הוא {word} ב-{cm(delta)} ס״מ.")


def insight_pace(annual):
    if len(annual) < 15:
        return None
    recent = annual[-10:]
    early = annual[:10]
    r = sum(v for _, v in recent) / len(recent)
    e = sum(v for _, v in early) / len(early)
    if abs(r) < 0.01 or abs(e) < 0.01:
        return None
    ratio = r / e
    span_r = f"{recent[0][0]}–{recent[-1][0]}"
    span_e = f"{early[0][0]}–{early[-1][0]}"
    if ratio > 1.15:
        verb = f"מהיר פי {ratio:.1f} מאשר"
    elif ratio < 0.87:
        verb = "איטי יותר מאשר"
    else:
        verb = "דומה לקצב של"
    return (f"בשנים {span_r} ירד המפלס בממוצע {cm(r)} ס״מ בשנה — {verb} "
            f"השנים {span_e} ({cm(e)} ס״מ בשנה).")


def insight_rises(annual):
    ups = [(y, v) for y, v in annual if v > 0]
    if not ups:
        return (f"בכל {len(annual)} השנים המלאות במאגר ירד המפלס — אף שנה לא הסתיימה "
                f"במפלס גבוה מקודמתה.")
    y, v = max(ups, key=lambda t: (t[1], t[0]))
    last_up = ups[-1][0]
    tail = "" if last_up == y else f", והאחרונה ב-{last_up}"
    return (f"רק ב-{len(ups)} מתוך {len(annual)} השנים המלאות עלה המפלס לאורך השנה; "
            f"העלייה הגדולה ביותר נרשמה ב-{y} (+{cm(v)} ס״מ){tail}.")


def insight_season(season):
    rising = [MONTHS_HE[i] for i, v in enumerate(season) if v is not None and v > 0]
    worst = min(((v, i) for i, v in enumerate(season) if v is not None), default=None)
    if worst is None:
        return None
    w = MONTHS_HE[worst[1]]
    if rising:
        months = ", ".join(f"ב{r}" for r in rising)
        return (f"בממוצע המפלס עולה רק {months}, ויורד בשאר השנה — הירידה החודשית "
                f"הממוצעת החזקה ביותר היא ב{w} ({cm(worst[0])} ס״מ).")
    return (f"בממוצע המפלס יורד בכל חודשי השנה; הירידה החודשית החזקה ביותר היא "
            f"ב{w} ({cm(worst[0])} ס״מ).")


def insight_milestones(marks):
    if len(marks) < 3:
        return None
    gaps = [(marks[i][0], (marks[i][1] - marks[i - 1][1]).days / 365.25)
            for i in range(1, len(marks))]
    first_mark, first_gap = gaps[0]
    last_mark, last_gap = gaps[-1]
    head = (f"הירידה מ-{m(first_mark + STEP_M)} ל-{m(first_mark)} מ' נמשכה כ-{first_gap:.1f} שנים, "
            f"והירידה האחרונה של {STEP_M} מטרים, אל {m(last_mark)} מ', נמשכה כ-{last_gap:.1f} שנים")
    if last_gap < first_gap * 0.8:
        return head + " — הירידה הואצה."
    if last_gap > first_gap * 1.2:
        return head + " — הירידה הואטה."
    return head + " — קצב דומה."


def insight_total(df, last):
    first = df.iloc[0]
    years = (last["d"] - first["d"]).days / 365.25
    return (f"מאז {d_he(first['d'])} ירד המפלס ב-{abs(last['lvl'] - first['lvl']):.2f} מטרים "
            f"(מ-{m(first['lvl'])} ל-{m(last['lvl'])} מ') — כ-{cm((last['lvl'] - first['lvl']) / years)} "
            f"ס״מ בשנה בממוצע לאורך {years:.0f} שנה.")


def compute(frames):
    df = _prepare(frames["levels"])
    last, first = df.iloc[-1], df.iloc[0]
    annual = _annual_change(df)
    marks = _milestones(df)

    # Monthly series (one value per calendar month).
    monthly = df.set_index("d")["lvl"].resample("MS").mean().dropna()
    history = {"x": [d.strftime("%Y-%m") for d in monthly.index],
               "y": [round(float(v), 2) for v in monthly]}
    recent_m = monthly[monthly.index > monthly.index.max() - pd.DateOffset(months=RECENT_MONTHS)]
    recent = {"x": [d.strftime("%Y-%m") for d in recent_m.index],
              "y": [round(float(v), 2) for v in recent_m]}

    annual_chart = {"x": [str(y) for y, _ in annual],
                    "y": [round(v * 100) for _, v in annual]}

    # Decade pace: mean annual change per decade (complete years only).
    dec = {}
    for y, v in annual:
        dec.setdefault(y // 10 * 10, []).append(v)
    decades = {"x": [f"{d}–{d + 9}" for d in sorted(dec)],
               "y": [round(sum(v) / len(v) * 100, 1) for d, v in sorted(dec.items())],
               "n": [len(dec[d]) for d in sorted(dec)]}

    # Seasonality: mean month-over-month change by calendar month (cm).
    mchg = monthly.diff().dropna()
    by_month = mchg.groupby(mchg.index.month).mean()
    season_vals = [round(float(by_month.get(i)) * 100, 1) if i in by_month.index else None
                   for i in range(1, 13)]
    season = {"x": MONTHS_HE, "y": season_vals}

    miles = {
        "x": [f"{mk:.0f}" for mk, _ in marks],
        "dates": [d.strftime("%Y-%m") for _, d in marks],
        "gap": [None] + [round((marks[i][1] - marks[i - 1][1]).days / 365.25, 1)
                         for i in range(1, len(marks))],
    }

    heat_years = sorted({d.year for d in monthly.index})
    heat = {
        "years": [str(y) for y in heat_years],
        "months": MONTHS_HE,
        "cells": [[heat_years.index(d.year), d.month - 1, round(float(v), 2)]
                  for d, v in monthly.items()],
        "min": round(float(monthly.min()), 2),
        "max": round(float(monthly.max()), 2),
    }

    season_m = [s / 100 if s is not None else None for s in season_vals]
    rules = [
        ("now", insight_now(df, last)),
        ("pace", insight_pace(annual)),
        ("rises", insight_rises(annual)),
        ("season", insight_season(season_m)),
        ("milestones", insight_milestones(marks)),
        ("total", insight_total(df, last)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    d12 = _on_or_before(df, last["d"] - pd.Timedelta(days=365))
    recent10 = annual[-10:]
    rate10 = sum(v for _, v in recent10) / len(recent10) if recent10 else None
    change12 = None if d12 is None else float(last["lvl"] - d12["lvl"])
    rate_all = sum(v for _, v in annual) / len(annual) if annual else None
    total_change = float(last["lvl"] - first["lvl"])
    # Level: red at (within 5 cm of) the record low, amber while still
    # falling over 12 months, green once the year-on-year change is a rise.
    if last["lvl"] <= df["lvl"].min() + 0.05:
        level_tone = "danger"
    elif change12 is not None and change12 < 0:
        level_tone = "warn"
    else:
        level_tone = "ok"
    # 12-month change and decade pace: a rise is green; a fall is amber,
    # red when the recent pace is 10+ cm/yr faster than the long-run mean.
    d12_tone = ("brand" if change12 is None or abs(change12) < 0.01
                else "ok" if change12 > 0 else "danger")
    if rate10 is None:
        rate_tone = "brand"
    elif rate10 >= 0:
        rate_tone = "ok"
    elif rate_all is not None and rate10 < rate_all - 0.10:
        rate_tone = "danger"
    else:
        rate_tone = "warn"
    kpis = {
        "level": {"value": float(last["lvl"]), "display": kv(last["lvl"]), "tone": level_tone},
        "as_of": {"value": last["d"].strftime("%Y-%m-%d"), "display": d_he(last["d"])},
        "d12": {"value": change12,
                "display": "—" if change12 is None else kv(change12 * 100, 0, signed=True),
                "tone": d12_tone},
        "rate10": {"value": rate10,
                   "display": "—" if rate10 is None else kv(rate10 * 100, 0, signed=True),
                   "tone": rate_tone},
        "total": {"value": total_change, "display": kv(total_change, signed=True),
                  "tone": "danger" if total_change < 0 else "ok"},
    }

    y0, y1 = int(first["d"].year), int(last["d"].year)
    span10 = f"{recent10[0][0]}–{recent10[-1][0]}" if recent10 else ""
    labels = {
        "lede": (f"מדידות מפלס ים המלח מ-{d_he(first['d'])} ועד {d_he(last['d'])} — "
                 f"{len(df):,} מדידות, כמעט אחת לחודש. המדידה האחרונה: {m(last['lvl'])} מ'."),
        "rate10_label": f"ס״מ לשנה — קצב ממוצע {span10}",
        "total_label": f"מטר — שינוי מאז {y0}",
        "level_kpi": f"מטר — מפלס אחרון, {d_he(last['d'])}",
        "history_aria": f"גרף קו: מפלס ים המלח החודשי, {y0} עד {y1}.",
        "recent_aria": f"גרף קו: מפלס ים המלח ב-{len(recent_m)} החודשים האחרונים.",
        "annual_aria": f"תרשים עמודות: שינוי המפלס בכל אחת מ-{len(annual)} השנים המלאות, בס״מ.",
        "annual_note": "שנה מלאה = שנה עם מדידה בדצמבר; השינוי מחושב מדצמבר לדצמבר.",
        "decades_aria": f"תרשים עמודות: הירידה השנתית הממוצעת בכל עשור, בס״מ.",
        "season_aria": "תרשים עמודות: השינוי החודשי הממוצע במפלס לפי חודש בשנה, בס״מ.",
        "miles_aria": (f"תרשים עמודות: מספר השנים שנדרשו לכל ירידה של {STEP_M} מטרים "
                       f"במפלס, מ-{len(marks)} סימני דרך."),
        "heat_aria": f"מפת חום: מפלס ים המלח לפי חודש ושנה, {y0} עד {y1}.",
        "annual_table_caption": "שינוי המפלס בשנים המלאות האחרונות, בס״מ.",
    }

    annual_table = [{"year": str(y), "chg": f"{round(v * 100):+d}"} for y, v in annual[-20:]]
    decade_table = [{"dec": x, "avg": f"{v:+.1f}", "n": f"{n}"}
                    for x, v, n in zip(decades["x"], decades["y"], decades["n"])]
    season_table = [{"m": MONTHS_HE[i], "v": "—" if v is None else f"{v:+.1f}"}
                    for i, v in enumerate(season_vals)]
    miles_table = [{"mark": f"{LRI}{mk:.0f}{PDI}", "date": d.strftime("%m/%Y"),
                    "gap": "—" if g is None else f"{g:.1f}"}
                   for (mk, d), g in zip(marks, miles["gap"])]

    return {
        "agent_data": {
            "summary_he": (f"מפלס ים המלח החודשי מ-{y0} ועד {d_he(last['d'])}: המפלס האחרון "
                           f"{m(last['lvl'])} מ', ירידה של {abs(last['lvl'] - first['lvl']):.1f} "
                           f"מטרים מאז תחילת המדידות במאגר."),
            "dataset_kind": "timeseries",
            "related_ids": ["2706952a-a86d-4887-a6a6-6e42d91cba6c"],
            "suggested_tags": ["ים המלח", "מפלס מים", "הידרולוגיה", "משאבי מים"],
            "temporal_coverage": f"{first['d'].strftime('%Y-%m-%d')}/{last['d'].strftime('%Y-%m-%d')}",
            "spatial_coverage": "ים המלח",
        },
        "kpis": kpis,
        "charts": {"history": history, "recent": recent, "annual": annual_chart,
                   "decades": decades, "season": season, "miles": miles, "heat": heat},
        "tables": {"annual": annual_table, "decades": decade_table,
                   "season": season_table, "miles": miles_table},
        "insights": insights,
        "labels": labels,
    }
