"""רכבת ישראל — תכנון מול ביצוע (planned vs operated trips), monthly.

One row per month × train number × origin → destination:
  rishui_all   trips planned (licensed) that month
  rishui_only  planned but NOT operated (cancelled)
  bitzua_only  operated but NOT planned (unplanned extras)
  ahuz_bitzua  (planned − cancelled) / planned × 100 (empty when nothing was planned)
Rates are recomputed from the counts, never averaged from row percentages.

The latest month in the data is often still being filled in; it is flagged
partial when its planned trips fall well below the recent norm, and kept out
of trend comparisons. Gaps in the monthly series are disclosed, not bridged.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
PARTIAL_RATIO = 0.85     # latest month < 85% of the prior-6 median → partial
MIN_STATION_TRIPS = 1000  # station ranking floor over the last 12 months
TOP_N = 12


def mlabel(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def pct(v):
    return f"{v * 100:.1f}%"


def _station(name):
    """The source drops an acronym's gershayim at the END of the name
    ('נתבג"', 'רשלצ משה דיין"'); put it back before the last letter of the
    first word ('נתב"ג', 'רשל"צ משה דיין'). Display only."""
    name = name.strip()
    if not name.endswith('"') or name.count('"') != 1:
        return name
    name = name[:-1].rstrip()
    first, _, rest = name.partition(" ")
    if len(first) < 2:
        return name
    first = f'{first[:-1]}"{first[-1]}'
    return f"{first} {rest}".strip()


def _prepare(df):
    out = pd.DataFrame({
        "y": pd.to_numeric(df["shana"], errors="coerce"),
        "m": pd.to_numeric(df["hodesh"], errors="coerce"),
        "train": df["train_trip_cd"].str.strip(),
        "orig": df["first_train_station_nm"].map(_station),
        "dest": df["last_train_station_nm"].map(_station),
        "plan": pd.to_numeric(df["rishui_all"], errors="coerce").fillna(0),
        "cancel": pd.to_numeric(df["rishui_only"], errors="coerce").fillna(0),
        "extra": pd.to_numeric(df["bitzua_only"], errors="coerce").fillna(0),
    }).dropna(subset=["y", "m"])
    out = out[(out["m"] >= 1) & (out["m"] <= 12)]
    out["p"] = [pd.Period(year=int(a), month=int(b), freq="M") for a, b in zip(out["y"], out["m"])]
    return out


def _monthly(df):
    g = df.groupby("p")[["plan", "cancel", "extra"]].sum().sort_index()
    g["rate"] = (g["plan"] - g["cancel"]) / g["plan"]
    return g


def insight_latest(mon, partial):
    full = mon.iloc[:-1] if partial else mon
    if full.empty:
        return None
    p = full.index[-1]
    r = full.loc[p]
    prev = p - 12
    tail = ""
    if prev in full.index:
        diff = (r["rate"] - full.loc[prev, "rate"]) * 100
        if abs(diff) < 0.3:
            tail = f", בדומה ל{mlabel(prev)} ({pct(full.loc[prev, 'rate'])})"
        else:
            word = "עלייה" if diff > 0 else "ירידה"
            tail = f" — {word} של {abs(diff):.1f} נקודות אחוז לעומת {mlabel(prev)}"
    return (f"ב{mlabel(p)} בוצעו {pct(r['rate'])} מהנסיעות המתוכננות "
            f"({int(r['plan'] - r['cancel']):,} מתוך {int(r['plan']):,}){tail}.")


def insight_worst(mon, partial):
    full = mon.iloc[:-1] if partial else mon
    last24 = full[full.index > full.index[-1] - 24] if len(full) else full
    if len(last24) < 6:
        return None
    p = last24["rate"].idxmin()
    r = last24.loc[p]
    med = last24["rate"].median()
    if med - r["rate"] < 0.02:
        return None
    return (f"החודש החלש ביותר בשנתיים האחרונות היה {mlabel(p)}: בוטלו {int(r['cancel']):,} "
            f"נסיעות ושיעור הביצוע ירד ל-{pct(r['rate'])}, לעומת חציון של {pct(med)}.")


def insight_12m(mon, partial):
    full = mon.iloc[:-1] if partial else mon
    if len(full) < 24:
        return None
    end = full.index[-1]
    cur = full[full.index > end - 12]
    prv = full[(full.index <= end - 12) & (full.index > end - 24)]
    if len(cur) < 10 or len(prv) < 10:
        return None
    rc = 1 - cur["cancel"].sum() / cur["plan"].sum()
    rp = 1 - prv["cancel"].sum() / prv["plan"].sum()
    diff = (rc - rp) * 100
    if abs(diff) < 0.3:
        trend = f"דומה ל-12 החודשים שקדמו להם ({pct(rp)})"
    else:
        trend = f"{'שיפור' if diff > 0 else 'הרעה'} של {abs(diff):.1f} נקודות אחוז לעומת 12 החודשים שקדמו להם"
    return (f"ב-12 החודשים האחרונים בוצעו {pct(rc)} מהנסיעות המתוכננות — {trend}; "
            f"בוטלו בסך הכול {int(cur['cancel'].sum()):,} נסיעות.")


def insight_station(st):
    if st.empty:
        return None
    top = st.iloc[0]
    return (f"בתחנת המוצא {top.name} בוטלו ב-12 החודשים האחרונים {pct(top['crate'])} "
            f"מהנסיעות המתוכננות — השיעור הגבוה ביותר בין התחנות עם "
            f"{MIN_STATION_TRIPS:,} נסיעות מתוכננות לפחות.")


def insight_full(last12):
    tm = last12[last12["plan"] > 0]
    if len(tm) < 100:
        return None
    full = (tm["cancel"] == 0).mean()
    return (f"{pct(full)} מצירופי הרכבת והחודש ב-12 החודשים האחרונים בוצעו במלואם, "
            f"ללא אף נסיעה מבוטלת.")


def insight_gaps(missing):
    if not missing:
        return None
    first, last = missing[0], missing[-1]
    span = f"מ{mlabel(first)} עד {mlabel(last)}" if len(missing) > 1 else mlabel(first)
    return (f"במאגר חסרים {len(missing)} חודשים ({span}); הגרפים מציגים את הפער "
            f"ואינם משלימים אותו.")


def compute(frames):
    df = _prepare(frames["trips"])
    mon = _monthly(df)
    full_range = pd.period_range(mon.index.min(), mon.index.max(), freq="M")
    missing = [p for p in full_range if p not in mon.index]

    prior = mon["plan"].iloc[-7:-1]
    partial = bool(len(prior) >= 3 and mon["plan"].iloc[-1] < PARTIAL_RATIO * prior.median())
    complete = mon.iloc[:-1] if partial else mon
    end = complete.index[-1]
    last12 = df[(df["p"] > end - 12) & (df["p"] <= end)]

    # Monthly series over the full calendar range (None for missing months).
    mon_full = mon.reindex(full_range)
    monthly = {
        "x": [str(p) for p in full_range],
        "rate": [None if pd.isna(v) else round(float(v) * 100, 2) for v in mon_full["rate"]],
        "plan": [None if pd.isna(v) else int(v) for v in mon_full["plan"]],
        "cancel": [None if pd.isna(v) else int(v) for v in mon_full["cancel"]],
        "extra": [None if pd.isna(v) else int(v) for v in mon_full["extra"]],
        "partial": str(mon.index[-1]) if partial else None,
    }

    yearly = complete.groupby(complete.index.year)[["plan", "cancel", "extra"]].sum()
    months_per_year = complete.groupby(complete.index.year).size()
    yearly["rate"] = 1 - yearly["cancel"] / yearly["plan"]
    yearly_chart = {"x": [str(y) for y in yearly.index],
                    "rate": [round(float(v) * 100, 2) for v in yearly["rate"]],
                    "plan": [int(v) for v in yearly["plan"]]}

    season = complete.groupby(complete.index.month)[["plan", "cancel"]].sum()
    season["rate"] = 1 - season["cancel"] / season["plan"]
    season_chart = {"x": [MONTHS_HE[i - 1] for i in season.index],
                    "rate": [round(float(v) * 100, 2) for v in season["rate"]]}

    st = last12.groupby("orig")[["plan", "cancel"]].sum()
    st = st[st["plan"] >= MIN_STATION_TRIPS]
    st["crate"] = st["cancel"] / st["plan"]
    st = st.sort_index().sort_values("crate", ascending=False, kind="stable")
    stations = {"x": st.index[:TOP_N].tolist(),
                "y": [round(float(v) * 100, 2) for v in st["crate"][:TOP_N]]}

    last12 = last12.assign(route=last12["orig"] + " ← " + last12["dest"])
    rt = last12.groupby("route")[["plan", "cancel"]].sum()
    rt = rt.sort_index().sort_values("plan", ascending=False, kind="stable").head(TOP_N)
    routes = {"x": rt.index.tolist(), "plan": [int(v) for v in rt["plan"]],
              "rate": [round((1 - c / p) * 100, 2) if p else None for p, c in zip(rt["plan"], rt["cancel"])]}

    tm = last12[last12["plan"] > 0]
    r = (tm["plan"] - tm["cancel"]) / tm["plan"]
    buckets = [("100%", r >= 1.0), ("95%–99.9%", (r >= 0.95) & (r < 1.0)),
               ("90%–94.9%", (r >= 0.90) & (r < 0.95)), ("50%–89.9%", (r >= 0.5) & (r < 0.9)),
               ("פחות מ-50%", r < 0.5)]
    dist = {"x": [b for b, _ in buckets], "y": [int(mask.sum()) for _, mask in buckets]}

    heat_years = sorted({p.year for p in mon.index})
    heat = {"years": [str(y) for y in heat_years], "months": MONTHS_HE,
            "cells": [[heat_years.index(p.year), p.month - 1, round(float(v) * 100, 1)]
                      for p, v in complete["rate"].items()],
            "min": round(float(complete["rate"].min()) * 100, 1), "max": 100.0}

    rules = [
        ("latest", insight_latest(mon, partial)),
        ("rate12", insight_12m(mon, partial)),
        ("worst", insight_worst(mon, partial)),
        ("station", insight_station(st)),
        ("full", insight_full(last12)),
        ("gaps", insight_gaps(missing)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    c12_rate = 1 - last12["cancel"].sum() / last12["plan"].sum()
    kpis = {
        "rate_last": {"value": float(complete["rate"].iloc[-1]), "display": pct(complete["rate"].iloc[-1])},
        "month_last": {"value": str(end), "display": mlabel(end)},
        "rate12": {"value": float(c12_rate), "display": pct(c12_rate)},
        "cancel12": {"value": int(last12["cancel"].sum()), "display": f"{int(last12['cancel'].sum()):,}"},
        "extra12": {"value": int(last12["extra"].sum()), "display": f"{int(last12['extra'].sum()):,}"},
    }

    p0, p1 = mon.index[0], mon.index[-1]
    partial_note = (f" {mlabel(p1)} מופיע בנתונים חלקית ואינו נכלל בהשוואות." if partial else "")
    labels = {
        "lede": (f"נסיעות הרכבת המתוכננות מול אלה שבוצעו בפועל, לפי מספר רכבת ומסלול, "
                 f"מ{mlabel(p0)} עד {mlabel(p1)} — {len(mon)} חודשים ו-{df['train'].nunique():,} "
                 f"מספרי רכבת.{partial_note}"),
        "monthly_aria": f"גרף: שיעור הביצוע ומספר הנסיעות המתוכננות בכל חודש, {mlabel(p0)} עד {mlabel(p1)}.",
        "cancel_aria": "תרשים עמודות: נסיעות שבוטלו ונסיעות שבוצעו ללא תכנון בכל חודש.",
        "yearly_aria": f"תרשים: שיעור הביצוע והנסיעות המתוכננות בכל שנה, חודשים מלאים בלבד.",
        "season_aria": "תרשים עמודות: שיעור הביצוע לפי חודש בשנה, כל השנים יחד.",
        "stations_aria": f"תרשים עמודות: שיעור הנסיעות שבוטלו לפי תחנת מוצא ב-12 החודשים האחרונים.",
        "routes_aria": f"תרשים עמודות: {TOP_N} המסלולים העמוסים ביותר ב-12 החודשים האחרונים.",
        "dist_aria": "תרשים עמודות: התפלגות צירופי רכבת וחודש לפי שיעור הביצוע, 12 החודשים האחרונים.",
        "heat_aria": "מפת חום: שיעור הביצוע לפי חודש ושנה.",
        "yearly_note": ("שנה שחסרים בה חודשים מחושבת מהחודשים הקיימים בלבד." if missing or partial else
                        "חודשים מלאים בלבד."),
        "stations_note": f"תחנות עם {MIN_STATION_TRIPS:,} נסיעות מתוכננות לפחות ב-12 החודשים האחרונים.",
    }

    tables = {
        "yearly": [{"y": str(y), "rate": f"{r_ * 100:.2f}", "plan": f"{int(pl):,}",
                    "cancel": f"{int(c):,}", "months": f"{int(months_per_year[y])}"}
                   for y, r_, pl, c in zip(yearly.index, yearly["rate"], yearly["plan"], yearly["cancel"])],
        "season": [{"m": x, "rate": f"{v:.2f}"} for x, v in zip(season_chart["x"], season_chart["rate"])],
        "stations": [{"s": s, "rate": f"{v:.2f}"} for s, v in zip(stations["x"], stations["y"])],
        "routes": [{"r": x, "plan": f"{p:,}", "rate": "—" if v is None else f"{v:.2f}"}
                   for x, p, v in zip(routes["x"], routes["plan"], routes["rate"])],
        "dist": [{"b": b, "n": f"{n:,}"} for b, n in zip(dist["x"], dist["y"])],
    }

    return {
        "agent_data": {
            "summary_he": (f"נסיעות רכבת ישראל המתוכננות מול אלה שבוצעו, {mlabel(p0)}–{mlabel(p1)}: "
                           f"ב-12 החודשים האחרונים בוצעו {pct(c12_rate)} מהנסיעות המתוכננות."),
            "dataset_kind": "timeseries",
            "related_ids": ["cdffbed6-8388-4b72-8c74-d36403cc5b83"],
            "suggested_tags": ["רכבת ישראל", "תחבורה ציבורית", "אמינות שירות", "ביטולי נסיעות"],
            "temporal_coverage": f"{p0}/{p1}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"monthly": monthly, "yearly": yearly_chart, "season": season_chart,
                   "stations": stations, "routes": routes, "dist": dist, "heat": heat},
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
