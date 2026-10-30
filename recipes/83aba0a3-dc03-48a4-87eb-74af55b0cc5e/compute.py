"""נתוני כלוריד בכנרת: weekly chloride (mg/L) at Kinneret station A, 1 m depth, since 1969.

One row per sampling date. Sampling was weekly in 1969-70 and from 1986 on,
fortnightly in between, so yearly figures are means (not sums) and sample
counts are shown alongside. "Now" is the latest sample in the data, never
the wall clock. Only the latest calendar year can be partial; it is labelled
and kept out of the year-over-year rules.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
UNITS_HE = {"MG/L": "מ״ג לליטר"}
RECENT_DAYS = 730      # sample-level window for the "recent" chart
WINDOW_DAYS = 365      # trailing window for the year-over-year KPI
MIN_WINDOW_SAMPLES = 10
TABLE_ROWS = 20
BIN = 10               # mg/L histogram bin width
STABLE_PCT = 2.0       # |change| below this % reads as "stable"


def n0(v):
    return f"{v:,.0f}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def signed(v, digits=1):
    s = f"{abs(v):,.{digits}f}"
    return ("+" if v > 0 else "−" if v < 0 else "") + s


def _mode(series, default=""):
    s = series.astype(str).str.strip()
    s = s[s != ""]
    if s.empty:
        return default
    vc = s.value_counts()
    top = vc[vc == vc.max()].index
    return sorted(top)[0]


def _prepare(df):
    raw = df["תאריך ניטור"].astype(str).str.strip()
    d = pd.to_datetime(raw, format="%d/%m/%Y", errors="coerce")
    alt = pd.to_datetime(raw, format="%Y-%m-%d", errors="coerce")
    d = d.fillna(alt)
    v = pd.to_numeric(df["תוצאה"].astype(str).str.replace(",", "", regex=False).str.strip(),
                      errors="coerce")
    out = pd.DataFrame({"d": d.dt.normalize(), "v": v}).dropna()
    out = out[out["v"] > 0]
    # One value per date (if a date is ever duplicated, take the mean).
    out = out.groupby("d", as_index=False)["v"].mean().sort_values("d").reset_index(drop=True)
    out["y"] = out["d"].dt.year
    out["m"] = out["d"].dt.month
    return out


def _window_mean(df, end, days):
    s = df[(df["d"] > end - pd.Timedelta(days=days)) & (df["d"] <= end)]
    if len(s) < MIN_WINDOW_SAMPLES:
        return None, len(s)
    return float(s["v"].mean()), len(s)


# ---------------------------------------------------------------- insights

def insight_latest(df, last, month_mean, pct_below):
    mm = month_mean.get(int(last["m"]))
    if mm is None:
        return None
    diff = (last["v"] - mm) / mm * 100
    if abs(diff) < STABLE_PCT:
        rel = f"קרוב לממוצע ארוך הטווח של חודש {MONTHS_HE[last['m'] - 1]} ({n0(mm)})"
    else:
        word = "גבוה" if diff > 0 else "נמוך"
        rel = (f"{word} ב-{abs(diff):.1f}% מהממוצע ארוך הטווח של חודש "
               f"{MONTHS_HE[last['m'] - 1]} ({n0(mm)})")
    return (f"בדגימה האחרונה ({d_he(last['d'])}) נמדדו {n0(last['v'])} מ״ג כלוריד לליטר, {rel}. "
            f"הערך גבוה מ-{pct_below:.0f}% מכלל {n0(len(df))} הדגימות במאגר.")


def insight_year_change(cur, prev, n_cur, n_prev):
    if cur is None or prev is None:
        return None
    pct = (cur - prev) / prev * 100
    if abs(pct) < STABLE_PCT:
        return (f"הריכוז יציב: ממוצע השנה האחרונה ({n0(cur)} מ״ג לליטר, {n_cur} דגימות) "
                f"כמעט זהה לממוצע השנה שקדמה לה ({n0(prev)}).")
    word = "עלה" if pct > 0 else "ירד"
    return (f"ממוצע הכלוריד בשנה האחרונה ({n0(cur)} מ״ג לליטר, {n_cur} דגימות) {word} "
            f"ב-{abs(pct):.1f}% לעומת השנה שקדמה לה ({n0(prev)} מ״ג לליטר, {n_prev} דגימות).")


def insight_peak(annual_full, cur):
    if len(annual_full) < 5 or cur is None:
        return None
    hi_y = int(annual_full["mean"].idxmax())
    lo_y = int(annual_full["mean"].idxmin())
    hi, lo = float(annual_full.loc[hi_y, "mean"]), float(annual_full.loc[lo_y, "mean"])
    gap = (cur - hi) / hi * 100
    if gap >= STABLE_PCT:
        tail = (f"ממוצע השנה האחרונה ({n0(cur)} מ״ג לליטר) גבוה ב-{gap:.1f}% "
                f"מהשיא השנתי הקודם.")
    elif gap > -STABLE_PCT:
        tail = "ממוצע השנה האחרונה קרוב לשיא הזה."
    else:
        tail = f"ממוצע השנה האחרונה נמוך ממנו ב-{abs(gap):.1f}%."
    return (f"הממוצע השנתי הגבוה ביותר נרשם ב-{hi_y} ({n0(hi)} מ״ג לליטר) והנמוך ביותר "
            f"ב-{lo_y} ({n0(lo)}). {tail}")


def insight_decades(dec):
    full = [r for r in dec if r["full"]]
    if len(full) < 2:
        return None
    a, b = full[0], full[-1]
    pct = (b["mean"] - a["mean"]) / a["mean"] * 100
    lo = min(full, key=lambda r: (r["mean"], r["start"]))
    if abs(pct) < STABLE_PCT:
        head = f"הממוצע בשנים {b['label']} ({n0(b['mean'])}) דומה לזה של {a['label']} ({n0(a['mean'])})"
    else:
        word = "גבוה" if pct > 0 else "נמוך"
        head = (f"הממוצע בשנים {b['label']} ({n0(b['mean'])} מ״ג לליטר) {word} ב-{abs(pct):.1f}% "
                f"מזה של {a['label']} ({n0(a['mean'])})")
    tail = ""
    if lo is not a and lo is not b:
        tail = f"; העשור המליח פחות היה {lo['label']} ({n0(lo['mean'])})"
    return head + tail + "."


def insight_season(month_mean):
    if len(month_mean) < 12:
        return None
    hi = max(month_mean, key=lambda k: (month_mean[k], -k))
    lo = min(month_mean, key=lambda k: (month_mean[k], k))
    amp = month_mean[hi] - month_mean[lo]
    if amp / month_mean[lo] * 100 < STABLE_PCT:
        return None
    return (f"יש מחזור עונתי: הריכוז הממוצע הגבוה ביותר בחודש {MONTHS_HE[hi - 1]} "
            f"({n0(month_mean[hi])}) והנמוך ביותר ב{MONTHS_HE[lo - 1]} ({n0(month_mean[lo])}), "
            f"הפרש של כ-{n0(amp)} מ״ג לליטר.")


def insight_swing(yoy):
    if len(yoy) < 5:
        return None
    drop = min(yoy, key=lambda r: (r[2], r[1]))
    rise = max(yoy, key=lambda r: (r[2], -r[1]))
    parts = []
    if drop[2] < 0:
        parts.append(f"הירידה השנתית החדה ביותר בממוצע הייתה בין {drop[0]} ל-{drop[1]} "
                     f"({n0(abs(drop[2]))} מ״ג לליטר)")
    if rise[2] > 0:
        parts.append(f"העלייה החדה ביותר בין {rise[0]} ל-{rise[1]} ({n0(rise[2])})")
    if not parts:
        return None
    return "; ".join(parts) + "."


# ---------------------------------------------------------------- compute

def compute(frames):
    src = frames["main"]
    df = _prepare(src)
    last, first = df.iloc[-1], df.iloc[0]
    y0, y1 = int(first["y"]), int(last["y"])
    station = _mode(src["שם תחנה"], "כנרת")
    depth = _mode(src["עומק הדגימה במטרים"], "")
    unit_raw = _mode(src["יחידת מדידה"], "MG/L")
    unit_he = UNITS_HE.get(unit_raw.upper(), unit_raw)

    # Years: only the latest calendar year can be partial.
    annual = df.groupby("y")["v"].agg(["mean", "min", "max", "count"])
    months_in = df.groupby("y")["m"].nunique()
    last_partial = int(last["m"]) < 12 or int(months_in.loc[y1]) < 12
    full_years = [int(y) for y in annual.index if not (last_partial and int(y) == y1)]
    annual_full = annual.loc[full_years]

    month_mean = {int(k): float(v) for k, v in df.groupby("m")["v"].mean().items()}
    pct_below = float((df["v"] < last["v"]).mean() * 100)

    cur, n_cur = _window_mean(df, last["d"], WINDOW_DAYS)
    prev, n_prev = _window_mean(df, last["d"] - pd.Timedelta(days=WINDOW_DAYS), WINDOW_DAYS)

    # ---- charts
    monthly = df.set_index("d")["v"].resample("MS").mean()
    roll = monthly.rolling(12, min_periods=9).mean()
    mon = monthly.dropna()
    history = {
        "x": [d.strftime("%Y-%m") for d in mon.index],
        "y": [round(float(v), 1) for v in mon],
        "roll": [None if pd.isna(roll.loc[d]) else round(float(roll.loc[d]), 1) for d in mon.index],
    }

    rec = df[df["d"] > last["d"] - pd.Timedelta(days=RECENT_DAYS)]
    lt_mean = float(df["v"].mean())
    recent = {"x": [d.strftime("%Y-%m-%d") for d in rec["d"]],
              "y": [round(float(v), 1) for v in rec["v"]],
              "mean": round(lt_mean, 1)}

    annual_chart = {
        "x": [str(int(y)) for y in annual.index],
        "mean": [round(float(v), 1) for v in annual["mean"]],
        "min": [round(float(v), 1) for v in annual["min"]],
        "max": [round(float(v), 1) for v in annual["max"]],
        "n": [int(v) for v in annual["count"]],
        "partial": str(y1) if last_partial else "",
    }

    yoy = []
    for a, b in zip(full_years, full_years[1:]):
        if b == a + 1:
            yoy.append((a, b, float(annual.loc[b, "mean"] - annual.loc[a, "mean"])))
    yoy_chart = {"x": [str(b) for _, b, _ in yoy], "y": [round(v, 1) for _, _, v in yoy]}

    # Decades (box plot): label = actual year span of data inside the decade.
    dec_rows = []
    for dec, g in df.groupby(df["y"] // 10 * 10):
        ys = sorted(set(int(v) for v in g["y"]))
        span_full = [y for y in ys if y in full_years]
        q = g["v"].quantile([0, 0.25, 0.5, 0.75, 1.0]).tolist()
        label = f"{ys[0]}-{ys[-1]}" if ys[0] != ys[-1] else str(ys[0])
        dec_rows.append({"start": int(dec), "label": label, "mean": float(g["v"].mean()),
                         "box": [round(float(x), 1) for x in q], "n": int(len(g)),
                         "full": len(span_full) == 10})
    decades = {"x": [r["label"] for r in dec_rows], "box": [r["box"] for r in dec_rows],
               "mean": [round(r["mean"], 1) for r in dec_rows]}

    # Seasonal profile: long-term monthly mean vs the two latest complete years.
    mm_y = df.groupby(["y", "m"])["v"].mean()
    complete = [y for y in full_years if int(months_in.loc[y]) == 12]
    season_years = complete[-2:]
    season = {
        "months": MONTHS_HE,
        "mean": [round(month_mean[m], 1) if m in month_mean else None for m in range(1, 13)],
        "series": [{"name": str(y),
                    "data": [round(float(mm_y[(y, m)]), 1) if (y, m) in mm_y.index else None
                             for m in range(1, 13)]} for y in season_years],
        "mean_label": f"ממוצע {y0}-{y1}",
    }

    heat_years = list(range(y0, y1 + 1))
    heat = {
        "years": [str(y) for y in heat_years],
        "months": MONTHS_HE,
        "cells": [[heat_years.index(d.year), d.month - 1, round(float(v), 1)] for d, v in mon.items()],
        "min": round(float(mon.min()), 0),
        "max": round(float(mon.max()), 0),
    }

    lo_bin = int(df["v"].min() // BIN * BIN)
    hi_bin = int(df["v"].max() // BIN * BIN)
    bins = list(range(lo_bin, hi_bin + BIN, BIN))
    counts = [int(((df["v"] >= b) & (df["v"] < b + BIN)).sum()) for b in bins]
    last_bin = int(last["v"] // BIN * BIN)
    hist = {"x": [f"{b}-{b + BIN - 1}" for b in bins], "y": counts,
            "hl": bins.index(last_bin) if last_bin in bins else -1}

    # ---- tables (<= TABLE_ROWS rows each)
    t_annual = [{"year": str(int(y)) + (" (חלקית)" if last_partial and int(y) == y1 else ""),
                 "mean": n0(r["mean"]), "min": n0(r["min"]), "max": n0(r["max"]),
                 "n": str(int(r["count"]))}
                for y, r in annual.tail(TABLE_ROWS).iloc[::-1].iterrows()]
    t_yoy = [{"pair": f"{a}-{b}", "delta": signed(v)} for a, b, v in yoy[-TABLE_ROWS:][::-1]]
    t_dec = [{"label": r["label"], "mean": n0(r["mean"]), "min": n0(r["box"][0]),
              "med": n0(r["box"][2]), "max": n0(r["box"][4]), "n": n0(r["n"])} for r in dec_rows]
    t_season = [{"month": MONTHS_HE[m - 1],
                 "mean": n0(month_mean[m]) if m in month_mean else "",
                 "vals": [n0(mm_y[(y, m)]) if (y, m) in mm_y.index else "" for y in season_years]}
                for m in range(1, 13)]
    t_hist = [{"bin": x, "n": str(c)} for x, c in zip(hist["x"], counts)]
    t_recent = [{"date": d_he(r["d"]), "v": n0(r["v"])}
                for _, r in df.tail(TABLE_ROWS).iloc[::-1].iterrows()]

    # ---- insights
    rules = [
        ("latest", insight_latest(df, last, month_mean, pct_below)),
        ("year_change", insight_year_change(cur, prev, n_cur, n_prev)),
        ("peak", insight_peak(annual_full, cur)),
        ("decades", insight_decades(dec_rows)),
        ("season", insight_season(month_mean)),
        ("swing", insight_swing(yoy)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs (higher chloride = saltier = worse)
    p50, p75, p90 = (float(df["v"].quantile(q)) for q in (0.5, 0.75, 0.9))
    v = float(last["v"])
    latest_tone = "danger" if v >= p90 else "warn" if v >= p75 else "ok" if v <= p50 else "brand"
    chg = None if (cur is None or prev is None) else (cur - prev) / prev * 100
    chg_tone = ("brand" if chg is None or abs(chg) < STABLE_PCT
                else "warn" if chg > 0 else "ok")
    peak_y = int(annual_full["mean"].idxmax()) if len(annual_full) else y1
    kpis = {
        "latest": {"value": v, "display": n0(v), "tone": latest_tone},
        "change": {"value": chg, "display": "–" if chg is None else signed(chg) + "%",
                   "tone": chg_tone},
        "lt_mean": {"value": round(lt_mean, 1), "display": n0(lt_mean), "tone": "brand"},
        "peak": {"value": float(annual_full["mean"].max()) if len(annual_full) else None,
                 "display": n0(annual_full["mean"].max()) if len(annual_full) else "–",
                 "tone": "info"},
        "span": {"value": f"{y0}/{y1}", "display": f"{y0}–{y1}"},
    }
    as_of = f"{last['d'].day}.{last['d'].month}.{last['d'].year}"
    kpi_labels = {
        "latest": f"כלוריד בדגימה האחרונה, {unit_he} ({as_of})",
        "change": "שינוי בממוצע השנה האחרונה לעומת השנה שלפניה",
        "lt_mean": f"ממוצע ארוך טווח {y0}-{y1}, {unit_he}",
        "peak": f"הממוצע השנתי הגבוה ביותר ({peak_y}), {unit_he}",
    }

    depth_txt = f" בעומק {depth} מטר" if depth else ""
    partial_note = (f"שנת {y1} חלקית (דגימות עד {d_he(last['d'])}) ומסומנת בהתאם; "
                    f"היא אינה נכללת בהשוואות בין שנים." if last_partial else "")
    labels = {
        "lede": (f"ריכוז הכלוריד (מדד למליחות המים) בכנרת, מתוך הדיגום השבועי בתחנה {station}"
                 f"{depth_txt}: {n0(len(df))} דגימות מ-{d_he(first['d'])} ועד {d_he(last['d'])}. "
                 f"הדגימה האחרונה: {n0(v)} {unit_he}."),
        "partial_note": partial_note,
        "recent_aria": f"גרף קו: כל הדגימות בשנתיים האחרונות עד {d_he(last['d'])}, לעומת הממוצע ארוך הטווח.",
        "history_aria": f"גרף קו: ממוצע חודשי וממוצע נע שנתי של ריכוז הכלוריד בכנרת, {y0} עד {y1}.",
        "annual_aria": f"גרף: ממוצע, מינימום ומקסימום ריכוז הכלוריד בכל שנה, {y0} עד {y1}.",
        "yoy_aria": "תרשים עמודות: השינוי בממוצע השנתי של ריכוז הכלוריד לעומת השנה הקודמת.",
        "dec_aria": f"תרשים קופסה: התפלגות הדגימות בכל עשור, {y0} עד {y1}.",
        "season_aria": "גרף קווים: ממוצע הכלוריד לפי חודש בשנה, ממוצע רב-שנתי לעומת השנים המלאות האחרונות.",
        "heat_aria": f"מפת חום: ממוצע חודשי של ריכוז הכלוריד לפי חודש ושנה, {y0} עד {y1}.",
        "hist_aria": f"היסטוגרמה: מספר הדגימות בכל טווח ריכוז, ברווחים של {BIN} {unit_he}.",
        "hist_note": (f"מספר הדגימות בכל טווח של {BIN} {unit_he} לאורך כל התקופה. העמודה המודגשת "
                      f"היא הטווח של הדגימה האחרונה."),
        "unit": unit_he,
        "season_cols": [str(y) for y in season_years],
        "recent_caption": f"{len(t_recent)} הדגימות האחרונות.",
        "annual_caption": f"ממוצע, מינימום ומקסימום ב-{len(t_annual)} השנים האחרונות ({unit_he}).",
        "yoy_caption": f"השינוי בממוצע השנתי ב-{len(t_yoy)} הזוגות האחרונים של שנים מלאות ({unit_he}).",
    }

    return {
        "agent_data": {
            "summary_he": (f"ריכוז הכלוריד (מליחות) בכנרת: דיגום שבועי מ-{y0}, {n0(len(df))} דגימות. "
                           f"הדגימה האחרונה ({as_of}): {n0(v)} {unit_he}; "
                           f"ממוצע ארוך טווח {n0(lt_mean)}."),
            "dataset_kind": "timeseries",
            "suggested_tags": ["כנרת", "איכות מים", "כלוריד", "מליחות", "ניטור"],
            "related_ids": [
                "2706952a-a86d-4887-a6a6-6e42d91cba6c",
                "db8f9bc9-738a-4d83-b3ce-74e8a5f7f844",
                "5de14d12-d5d7-475d-ade1-5dbd0ef9d086",
            ],
            "temporal_coverage": f"{first['d'].strftime('%Y-%m-%d')}/{last['d'].strftime('%Y-%m-%d')}",
            "spatial_coverage": "כנרת",
        },
        "kpis": kpis,
        "kpi_labels": kpi_labels,
        "charts": {"recent": recent, "history": history, "annual": annual_chart,
                   "yoy": yoy_chart, "decades": decades, "season": season,
                   "heat": heat, "hist": hist},
        "tables": {"annual": t_annual, "yoy": t_yoy, "decades": t_dec, "season": t_season,
                   "hist": t_hist, "recent": t_recent},
        "insights": insights,
        "labels": labels,
    }
