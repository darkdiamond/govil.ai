"""פדיון (מכירות) של רשתות השיווק: CBS's monthly chain-store sales release.

Inputs are CBS grid tables (one row per sheet row, cells C01..Cnn) from the
newest edition of the release:
  t1  total sales value index of chain stores (excluding fuel, including
      food), constant prices, base 2020 = 100: trend, seasonally adjusted
      and original index with the month-on-month % change, monthly
  t2  the same for the food chains only
  releases  the edition list (number, date, headline, link)

Both tables run monthly from the December before their first full year to
the latest (provisional) month. Header labels (Trend, Seasonally adjusted,
Original data, Index) are found by text and raise when missing, so a
redesigned table fails the refresh as recipe_failed and keeps the last page.
Month rows are found by pattern: a missing one only shortens a series.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TREND_BAND = 0.01      # annualized trend change within ±1% reads as stable
GAP_POINTS = 5.0       # total vs food gap (index points) worth an insight
YOY_BAND = 0.005       # a year-on-year change within ±0.5% reads as unchanged


# ── tables ───────────────────────────────────────────────────────────────


def _series(rows, name):
    """Monthly rows: [{t: (year, month), trend, trend_pct, sa, sa_pct, orig, orig_pct}]."""
    h = cbs.row_with(rows, "Seasonally adjusted", name=name)
    head = rows[h]
    trend_c = cbs.col_after(head, "Trend", 0)
    sa_c = cbs.col_after(head, "Seasonally adjusted", 0)
    orig_c = cbs.col_after(head, "Original data", 0)
    sub_i = cbs.row_with(rows, "Index", h + 1, name=name)
    sub = rows[sub_i]
    cols = {}
    for key, start in (("trend", trend_c), ("sa", sa_c), ("orig", orig_c)):
        cols[key + "_pct"] = cbs.col_after(sub, "% Change", start)
        cols[key] = cbs.col_after(sub, "Index", start)
    if not (cols["trend"] < cols["sa"] < cols["orig"] or cols["trend"] > cols["sa"] > cols["orig"]):
        raise ValueError(f"{name}: Index columns out of block order: {cols}")
    stop = next((i for i in range(sub_i + 1, len(rows)) if any(
        "Provisional" in c or "Percentage change" in c for c in rows[i])), len(rows))
    out = {}
    for i, y, m, end in cbs.periods(rows, sub_i + 1, stop):
        if m is None or end:
            continue
        r = rows[i]
        rec = {k: cbs.val(r, j) for k, j in cols.items()}
        if rec["orig"] is None:
            continue
        out[(y, m)] = {"t": (y, m), **rec}
    return [out[t] for t in sorted(out)]


def _base(rows, name):
    """The index base year from the title block ("BASE: 2020 = 100.0")."""
    for r in rows:
        for c in r:
            m = re.match(r"^BASE:\s*((?:19|20)\d\d)\s*=\s*100", c)
            if m:
                return int(m.group(1))
    raise ValueError(f"{name}: base-year label (BASE: …) not found")


# ── formatting ───────────────────────────────────────────────────────────


def _i(v):
    """An index value, one decimal: 126.6."""
    return fmt.num_he(v, 1) if v is not None else ""


def _p(v):
    """A % change already in percent (CBS's columns): +1.2%."""
    return fmt.signed_pct(v / 100) if v is not None else ""


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _word(c, band, up="עלייה", down="ירידה"):
    if abs(c) < band:
        return None
    return up if c > 0 else down


def _tone(c, band=0.01):
    if c is None:
        return "brand"
    return "ok" if c > band else "danger" if c < -band else "warn"


def _by_t(series):
    return {s["t"]: s for s in series}


def _yoy(series):
    """[(t, change)] of the original index against the same month a year earlier."""
    bt = _by_t(series)
    out = []
    for s in series:
        prev = bt.get((s["t"][0] - 1, s["t"][1]))
        c = _chg(s["orig"], prev["orig"]) if prev else None
        if c is not None:
            out.append((s["t"], c))
    return out


def _annualized(series, k=3):
    """The trend's change over the last k months, at an annual rate."""
    if len(series) <= k:
        return None
    a, b = series[-1]["trend"], series[-1 - k]["trend"]
    if a is None or not b:
        return None
    return (a / b) ** (12 / k) - 1


def _year_avgs(series):
    """{year: (mean original index, months)}."""
    acc = {}
    for s in series:
        acc.setdefault(s["t"][0], []).append(s["orig"])
    return {y: (sum(v) / len(v), len(v)) for y, v in acc.items()}


def _ytd(series):
    """(year, last month, avg this year, avg same months last year) or None."""
    last = series[-1]["t"]
    bt = _by_t(series)
    now = [bt[(last[0], m)]["orig"] for m in range(1, last[1] + 1) if (last[0], m) in bt]
    prev = [bt[(last[0] - 1, m)]["orig"] for m in range(1, last[1] + 1) if (last[0] - 1, m) in bt]
    if len(now) != last[1] or len(prev) != last[1]:
        return None
    return last[0], last[1], sum(now) / len(now), sum(prev) / len(prev)


def _range(end, year):
    if end == 1:
        return f"ינואר {year}"
    return f"ינואר עד {fmt.MONTHS_HE[end - 1]} {year}"


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"].copy()
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    g1, g2 = cbs.grid(frames["t1"], "t1"), cbs.grid(frames["t2"], "t2")
    total, food = _series(g1, "t1"), _series(g2, "t2")
    base = _base(g1, "t1")
    if _base(g2, "t2") != base:
        raise ValueError("t1 and t2 have different index bases")
    if len(total) < 2:
        raise ValueError("t1: fewer than two monthly rows")
    if len(food) < 2:
        raise ValueError("t2: fewer than two monthly rows")

    last, flast = total[-1], food[-1]
    lt = last["t"]
    food_bt = _by_t(food)
    yoy_t, yoy_f = _yoy(total), _yoy(food)
    yoy_t_last = yoy_t[-1] if yoy_t and yoy_t[-1][0] == lt else None
    yoy_f_last = yoy_f[-1] if yoy_f and yoy_f[-1][0] == flast["t"] else None
    ann = _annualized(total)
    ann_f = _annualized(food)

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["sa"] = {"value": round(last["sa"] if last["sa"] is not None else last["orig"], 1),
                  "display": _i(last["sa"] if last["sa"] is not None else last["orig"]),
                  "tone": "brand"}
    labels["sa_kpi"] = (f"מדד הפדיון של רשתות השיווק ב{_mname(lt)}, "
                        + ("מנוכה עונתיות" if last["sa"] is not None else "נתון מקורי")
                        + f" ({base} = 100)")
    if yoy_t_last:
        c = yoy_t_last[1]
        kpis["yoy"] = {"value": round(c, 4), "display": fmt.signed_pct(c), "tone": _tone(c)}
        labels["yoy_kpi"] = f"סך הרשתות: שינוי לעומת {_mname((lt[0] - 1, lt[1]))}"
    if yoy_f_last:
        c = yoy_f_last[1]
        kpis["yoy_food"] = {"value": round(c, 4), "display": fmt.signed_pct(c), "tone": _tone(c)}
        labels["yoy_food_kpi"] = (f"רשתות המזון: {_mname(flast['t'])} לעומת "
                                  f"{_mname((flast['t'][0] - 1, flast['t'][1]))}")
    if ann is not None:
        kpis["ann"] = {"value": round(ann, 4), "display": fmt.signed_pct(ann),
                       "tone": _tone(ann, TREND_BAND)}
        labels["ann_kpi"] = (f"קצב המגמה בשלושת החודשים עד {_mname(lt)}, "
                             f"בחישוב שנתי")

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables = {}, {}
    for key, s in (("total", total), ("food", food)):
        charts[key] = {"x": [_mshort(m["t"]) for m in s],
                       "orig": [m["orig"] for m in s], "sa": [m["sa"] for m in s],
                       "trend": [m["trend"] for m in s]}
        tables[key] = [[_mname(m["t"]), _i(m["orig"]), _i(m["sa"]), _p(m["sa_pct"]),
                        _i(m["trend"])] for m in reversed(s)]

    both = [m for m in total if m["t"] in food_bt]
    charts["compare"] = {"x": [_mshort(m["t"]) for m in both],
                         "total": [m["trend"] for m in both],
                         "food": [food_bt[m["t"]]["trend"] for m in both]}
    ya_t, ya_f = _year_avgs(total), _year_avgs(food)
    years = sorted(set(ya_t) & set(ya_f))
    tables["compare"] = [[str(y) + ("" if ya_t[y][1] == 12 else f" ({ya_t[y][1]} חודשים)"),
                          _i(ya_t[y][0]), _i(ya_f[y][0]), fmt.num_he(ya_t[y][0] - ya_f[y][0], 1)]
                         for y in years]

    yf = dict(yoy_f)
    yoy_rows = [(t, c, yf.get(t)) for t, c in yoy_t]
    charts["yoy"] = {"x": [_mshort(r[0]) for r in yoy_rows],
                     "total": [round(r[1] * 100, 1) for r in yoy_rows],
                     "food": [round(r[2] * 100, 1) if r[2] is not None else None
                              for r in yoy_rows]}
    tables["yoy"] = [[_mname(r[0]), fmt.signed_pct(r[1]),
                      fmt.signed_pct(r[2]) if r[2] is not None else ""]
                     for r in reversed(yoy_rows)]

    # Month × year (original index, total): seasonality. Years with ≥ 3 months.
    bt = _by_t(total)
    season_years = [y for y in sorted({m["t"][0] for m in total})
                    if sum(1 for m in total if m["t"][0] == y) >= 3]
    season = len(season_years) >= 2
    if season:
        charts["seasons"] = {
            "x": list(fmt.MONTHS_SHORT_HE),
            "years": [str(y) for y in season_years],
            "series": [[bt[(y, m)]["orig"] if (y, m) in bt else None for m in range(1, 13)]
                       for y in season_years],
        }
        tables["seasons"] = [[fmt.MONTHS_HE[m - 1]] + [_i(bt[(y, m)]["orig"]) if (y, m) in bt
                                                       else "" for y in season_years]
                             for m in range(1, 13)]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if yoy_t_last:
        c = yoy_t_last[1]
        prev = bt[(lt[0] - 1, lt[1])]["orig"]
        w = _word(c, YOY_BAND)
        add("yoy", (f"ב{_mname(lt)} עמד מדד הפדיון של רשתות השיווק (במחירים קבועים) על "
                    f"{_i(last['orig'])} נקודות, "
                    + (f"{w} של {fmt.pct(abs(c))} לעומת {_mname((lt[0] - 1, lt[1]))} "
                       f"({_i(prev)})." if w else
                       f"כמעט ללא שינוי לעומת {_mname((lt[0] - 1, lt[1]))} ({_i(prev)}).")))
    if yoy_f_last and yoy_t_last and yoy_f_last[0] == yoy_t_last[0]:
        cf, ct = yoy_f_last[1], yoy_t_last[1]
        if abs(cf - ct) >= 0.01:
            add("food", f"ברשתות המזון השינוי באותו חודש היה {fmt.signed_pct(cf)}, "
                        f"{'יותר' if cf > ct else 'פחות'} מבסך הרשתות ({fmt.signed_pct(ct)}).")
    if ann is not None:
        w = _word(ann, TREND_BAND, "עולה", "יורדת")
        add("trend", (f"מגמת הפדיון של רשתות השיווק {w}: בשלושת החודשים עד {_mname(lt)} "
                      f"השתנה קו המגמה בקצב שנתי של {fmt.signed_pct(ann)}"
                      if w else
                      f"מגמת הפדיון של רשתות השיווק כמעט יציבה: בשלושת החודשים עד "
                      f"{_mname(lt)} השתנה קו המגמה בקצב שנתי של {fmt.signed_pct(ann)}")
            + (f" (ברשתות המזון: {fmt.signed_pct(ann_f)})." if ann_f is not None else "."))
    yt = _ytd(total)
    if yt:
        y, end, now, prev = yt
        c = now / prev - 1
        w = _word(c, YOY_BAND)
        if w:
            add("ytd", f"מתחילת השנה ({_range(end, y)}) גבוה מדד הפדיון בממוצע ב-"
                       f"{fmt.pct(c)} מאשר באותם חודשים ב-{y - 1}." if c > 0 else
                       f"מתחילת השנה ({_range(end, y)}) נמוך מדד הפדיון בממוצע ב-"
                       f"{fmt.pct(abs(c))} מאשר באותם חודשים ב-{y - 1}.")
    full = [y for y in years if ya_t[y][1] == 12]
    if len(full) >= 2:
        a, b = full[-1], full[-2]
        c = ya_t[a][0] / ya_t[b][0] - 1
        cf = ya_f[a][0] / ya_f[b][0] - 1 if ya_f[a][1] == 12 and ya_f[b][1] == 12 else None
        add("annual", f"בשנת {a} {'עלה' if c > 0 else 'ירד'} מדד הפדיון הממוצע ב-"
                      f"{fmt.pct(abs(c))} לעומת {b}"
                      + (f", וברשתות המזון {fmt.signed_pct(cf)}" if cf is not None else "")
                      + ".")
    if last["trend"] is not None and flast["t"] == lt and flast["trend"] is not None:
        gap = last["trend"] - flast["trend"]
        if abs(gap) >= GAP_POINTS:
            hi, lo = (("סך הרשתות", "רשתות המזון") if gap > 0 else
                      ("רשתות המזון", "סך הרשתות"))
            add("gap", f"ביחס לממוצע {base} (100 נקודות) {hi} צמחו יותר מ{lo}: "
                       f"מדד המגמה ב{_mname(lt)} עומד על {_i(max(last['trend'], flast['trend']))} "
                       f"לעומת {_i(min(last['trend'], flast['trend']))}. "
                       + ("כלומר, הרשתות שאינן רשתות מזון צמחו מהר יותר."
                          if gap > 0 else ""))
    window = total[-12:]
    if len(window) == 12:
        hi = max(window, key=lambda m: (m["orig"], m["t"]))
        lo = min(window, key=lambda m: (m["orig"], m["t"]))
        if hi["orig"] and lo["orig"] and hi["orig"] / lo["orig"] - 1 >= 0.1:
            add("season", f"ב-12 החודשים האחרונים החודש החזק ביותר היה {_mname(hi['t'])} "
                          f"({_i(hi['orig'])}) והחלש ביותר {_mname(lo['t'])} ({_i(lo['orig'])}), "
                          f"פער של {fmt.pct(hi['orig'] / lo['orig'] - 1)} בנתון המקורי.")

    # ── text ─────────────────────────────────────────────────────────────
    rel_date = pd.Timestamp(latest_rel["RELEASE_DATE"])
    release = {"no": latest_rel["RELEASE_NO"], "date": fmt.d_he(rel_date),
               "title": latest_rel["TITLE"], "headline": latest_rel["HEADLINE"],
               "url": latest_rel["PAGE_URL"], "pdf": latest_rel["REPORT_PDF_URL"]}
    first = total[0]["t"]
    labels.update({
        "lede": (f"כמה מוכרות רשתות השיווק בישראל, חודש אחרי חודש: מדד הפדיון של הרשתות "
                 f"(ללא דלק, כולל מזון) ומדד רשתות המזון לבדן, במחירים קבועים, כך שעליית "
                 f"מחירים לא נספרת כגידול במכירות. הנתונים מתוך ההודעה החודשית של הלשכה "
                 f"המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. "
                 f"הנתון האחרון הוא ל{_mname(lt)}."),
        "total_note": (f"מדד הפדיון של כלל רשתות השיווק מאז {_mname(first)}: הנתון המקורי "
                       f"(עמודות), הנתון המנוכה עונתיות וקו המגמה של הלמ\"ס. "
                       f"ממוצע {base} = 100."),
        "total_aria": f"מדד הפדיון של רשתות השיווק, {_mname(first)} עד {_mname(lt)}",
        "total_caption": "מדד הפדיון של רשתות השיווק לפי חודש, במחירים קבועים",
        "food_note": (f"אותו מדד לרשתות המתמחות במזון בלבד, מאז {_mname(food[0]['t'])}. "
                      f"ממוצע {base} = 100."),
        "food_aria": (f"מדד הפדיון של רשתות המזון, {_mname(food[0]['t'])} עד "
                      f"{_mname(flast['t'])}"),
        "food_caption": "מדד הפדיון של רשתות המזון לפי חודש, במחירים קבועים",
        "compare_note": (f"שני המדדים מחושבים לאותו בסיס (ממוצע {base} = 100), ולכן אפשר להשוות "
                         "ביניהם ישירות. בתרשים: קווי המגמה. בטבלה: ממוצע הנתון המקורי בכל שנה."),
        "compare_aria": "קווי המגמה של סך רשתות השיווק ושל רשתות המזון",
        "compare_caption": "ממוצע שנתי של מדד הפדיון, סך הרשתות מול רשתות המזון",
        "yoy_note": ("השינוי בנתון המקורי לעומת אותו חודש בשנה הקודמת. ההשוואה לאותו חודש "
                     "מנטרלת את העונתיות, אבל חגים שזזים בין החודשים (פסח, ראש השנה) "
                     "עדיין משפיעים עליה."),
        "yoy_aria": "שינוי שנתי במדד הפדיון, סך הרשתות ורשתות המזון",
        "yoy_caption": "שינוי לעומת אותו חודש בשנה הקודמת",
        "seasons_note": ("הנתון המקורי של סך הרשתות, קו לכל שנה. כך רואים את דפוס העונות "
                         "ומשווים כל חודש לאותו חודש בשנים הקודמות."),
        "seasons_aria": "מדד הפדיון של רשתות השיווק לפי חודש, קו לכל שנה",
        "seasons_caption": "מדד הפדיון של רשתות השיווק לפי חודש ושנה (נתון מקורי)",
        "season_years": [str(y) for y in season_years],
    })

    summary = (f"מדד הפדיון (המכירות) של רשתות השיווק ושל רשתות המזון בישראל, במחירים "
               f"קבועים, מנתוני הלמ\"ס. ב{_mname(lt)} עמד המדד על {_i(last['orig'])}"
               + (f" ({fmt.signed_pct(yoy_t_last[1])} בשנה)" if yoy_t_last else "")
               + ".")
    desc = (f"כמה מוכרות רשתות השיווק: מדד הפדיון ב{_mname(lt)} "
            + (f"{fmt.signed_pct(yoy_t_last[1])} לעומת שנה קודם" if yoy_t_last
               else f"{_i(last['orig'])}")
            + (f", רשתות המזון {fmt.signed_pct(yoy_f_last[1])}" if yoy_f_last else "")
            + ". נתונים חודשיים במחירים קבועים.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first[0]}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "פדיון רשתות השיווק: מדד מכירות חודשי | הלמ\"ס",
                "description": desc,
                "name": "פדיון (מכירות) של רשתות השיווק",
                "alternate_names": ["מכירות רשתות השיווק", "מדד פדיון רשתות השיווק",
                                    "מכירות רשתות המזון", "פדיון רשתות המזון"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"seasons": season, "yoy": bool(yoy_rows)},
    }
