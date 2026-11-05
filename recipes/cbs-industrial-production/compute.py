"""מדד הייצור התעשייתי: CBS's monthly industrial-production release.

Inputs are CBS grid tables from the newest edition of the release:
  t1   production, manufacturing incl. mining and quarrying: original, SA and
       trend index with % change, the last ~27 months (the headline series)
  t2   the same for manufacturing alone
  t3   manufacturing excluding high technology
  t7   actual work hours (same layout as t1)
  t13  revenue from local sales, t14 revenue from exports (constant prices)
  t15  production index since 2021: SA and trend (chart data)
  t16  employee jobs index since 2021: SA and trend (chart data)
  t17  production by technology intensity, trend (chart data)
  t18  jobs, t19 local sales, t20 exports by technology intensity (trend)
  releases  the edition list (number, date, headline, link)

Header rows and columns are found by their labels (govlib.cbs) and raise
when missing; period rows are found by pattern, so a missing one only
shortens a series. "Latest month" is t1's newest row with an SA index.
"""
import pandas as pd
from govlib import cbs, fmt

# Technology-intensity groups, in CBS order (high → low). Header cells hold
# Hebrew and English together ("מעורבת-עלית medium-high").
TECH = [("high", "עילית"), ("mhigh", "מעורבת-עילית"),
        ("mlow", "מעורבת-מסורתית"), ("low", "מסורתית")]
TRIPLE = {"orig": "Original data", "sa": "Seasonally adjusted", "trend": "Trend"}
RECENT_FLAT = 0.01  # |change| under 1% reads as "stable"


# ── tables ───────────────────────────────────────────────────────────────


def _triple(rows, name):
    """A t1-style table: original / SA / trend sections, each with a
    '% Change' and an 'Index' column. Returns {(y, m): {orig, sa, trend,
    orig_pct, sa_pct, trend_pct}} for monthly rows."""
    h = cbs.row_with(rows, TRIPLE["orig"], name=name)
    sub = cbs.row_with(rows, "Index", h + 1, name=name)
    cols = {}
    for k, label in TRIPLE.items():
        s = cbs.col_after(rows[h], label, 0, contains=True)
        cols[k] = cbs.col_after(rows[sub], "Index", s)
        cols[k + "_pct"] = cbs.col_after(rows[sub], "% Change", s)
    out = {}
    for i, y, m, end in cbs.periods(rows, sub + 1, len(rows)):
        if m is None or end:
            continue
        v = {k: cbs.val(rows[i], j) for k, j in cols.items()}
        if v["sa"] is not None or v["orig"] is not None:
            out[(y, m)] = v
    if not out:
        raise ValueError(f"{name}: no monthly rows")
    return out


def _chart_series(rows, name, labels):
    """A chart-data table: a header row naming the series, then year /
    roman-month rows. labels: {key: predicate(cell)}. Returns
    {key: {(y, m): value}}."""
    h = None
    for i, r in enumerate(rows):
        if all(any(p(c) for c in r) for p in labels.values()):
            h = i
            break
    if h is None:
        raise ValueError(f"{name}: series header row not found")
    cols = {k: next(j for j, c in enumerate(rows[h]) if p(c)) for k, p in labels.items()}
    out = {k: {} for k in labels}
    for i, y, m, end in cbs.periods(rows, h + 1, len(rows)):
        if m is None or end:
            continue
        for k, j in cols.items():
            v = cbs.val(rows[i], j)
            if v is not None:
                out[k][(y, m)] = v
    return out


def _low(c):
    return c.lower()


TECH_PRED = {
    "high": lambda c: "high" in _low(c) and "medium" not in _low(c),
    "mhigh": lambda c: "medium-high" in _low(c).replace(" ", ""),
    "mlow": lambda c: "medium-low" in _low(c).replace(" ", ""),
    "low": lambda c: "low" in _low(c) and "medium" not in _low(c),
}
SA_TREND_PRED = {
    "sa": lambda c: "seasonally adjusted" in _low(c),
    "trend": lambda c: "trend" in _low(c),
}


# ── helpers ──────────────────────────────────────────────────────────────


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _ym(t):
    return f"{t[0]}-{t[1]:02d}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _yoy(series, t):
    """12-month change at month t of a {(y, m): v} series, or None."""
    return _chg(series.get(t), series.get((t[0] - 1, t[1])))


def _tone(c, band=0.005):
    if c is None:
        return "brand"
    return "ok" if c > band else "danger" if c < -band else "warn"


def _dir(c, up="עלייה", down="ירידה"):
    return up if c > 0 else down


def _moved(c, fem=False):
    """'עלה ב-5.1%' / 'ירד ב-5.1%' / 'לא השתנה' (feminine with fem)."""
    if round(abs(c) * 1000) == 0:
        return "לא השתנתה" if fem else "לא השתנה"
    verb = ("עלתה" if fem else "עלה") if c > 0 else ("ירדה" if fem else "ירד")
    return f"{verb} ב-{fmt.pct(abs(c))}"


def _idx(v):
    return fmt.num_he(v, 1)


def _r1(v):
    return None if v is None else round(v, 1)


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _yearly(series):
    """[(year, mean, months)] of a {(y, m): v} series."""
    out = []
    for y in sorted({t[0] for t in series}):
        vals = [v for t, v in series.items() if t[0] == y]
        out.append((y, _mean(vals), len(vals)))
    return out


def _base_year(rows):
    """'BASE: 2023 = 100.0' → '2023', or None."""
    for r in rows[:12]:
        for c in r:
            if c.upper().startswith("BASE"):
                for tok in c.replace("=", " ").replace(":", " ").split():
                    if cbs.YEAR.match(tok):
                        return tok
    return None


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    g1 = cbs.grid(frames["t1"], "t1")
    base = _base_year(g1)
    t1 = _triple(g1, "t1")
    t2 = _triple(cbs.grid(frames["t2"], "t2"), "t2")
    t3 = _triple(cbs.grid(frames["t3"], "t3"), "t3")
    t7 = _triple(cbs.grid(frames["t7"], "t7"), "t7")
    t13 = _triple(cbs.grid(frames["t13"], "t13"), "t13")
    t14 = _triple(cbs.grid(frames["t14"], "t14"), "t14")
    long_p = _chart_series(cbs.grid(frames["t15"], "t15"), "t15", SA_TREND_PRED)
    long_j = _chart_series(cbs.grid(frames["t16"], "t16"), "t16", SA_TREND_PRED)
    tech = {k: _chart_series(cbs.grid(frames[k], k), k, TECH_PRED)
            for k in ("t17", "t18", "t19", "t20")}

    months = sorted(t for t, v in t1.items() if v["sa"] is not None)
    if not months:
        raise ValueError("t1: no seasonally adjusted rows")
    lt = months[-1]
    last = t1[lt]

    def col(tbl, k):
        return {t: v[k] for t, v in tbl.items() if v[k] is not None}

    orig1, trend1 = col(t1, "orig"), col(t1, "trend")
    mom = last["sa_pct"]
    yoy_orig = _yoy(orig1, lt)
    yoy_trend = _yoy(trend1, lt)
    lp_trend = long_p["trend"]
    lp_sa = long_p["sa"]
    lpt = max(lp_trend) if lp_trend else None

    tech_lt = {k: max(s["high"]) if s["high"] else None for k, s in tech.items()}
    hi_yoy = _yoy(tech["t17"]["high"], tech_lt["t17"]) if tech_lt["t17"] else None

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["index"] = {"value": round(last["sa"], 1), "display": _idx(last["sa"]),
                     "tone": _tone(yoy_trend)}
    labels["index_kpi"] = (f"מדד הייצור התעשייתי, {_mname(lt)} (מנוכה עונתיות"
                           + (f", {base}=100" if base else "") + ")")
    if mom is not None:
        kpis["mom"] = {"value": mom, "display": fmt.signed_pct(mom / 100),
                       "tone": _tone(mom / 100)}
        labels["mom_kpi"] = "שינוי לעומת החודש הקודם (מנוכה עונתיות)"
    if yoy_orig is not None:
        kpis["yoy"] = {"value": round(yoy_orig, 4), "display": fmt.signed_pct(yoy_orig),
                       "tone": _tone(yoy_orig)}
        labels["yoy_kpi"] = f"שינוי לעומת {_mname((lt[0] - 1, lt[1]))} (נתון מקורי)"
    if yoy_trend is not None:
        kpis["trend"] = {"value": round(yoy_trend, 4), "display": fmt.signed_pct(yoy_trend),
                         "tone": _tone(yoy_trend)}
        labels["trend_kpi"] = "שינוי במגמה ב-12 החודשים האחרונים"
    if hi_yoy is not None:
        kpis["hitech"] = {"value": round(hi_yoy, 4), "display": fmt.signed_pct(hi_yoy),
                          "tone": "info"}
        labels["hitech_kpi"] = "טכנולוגיה עילית: שינוי במגמה בשנה"

    charts, tables, flags = {}, {}, {}

    # ── 1. recent months (t1) ────────────────────────────────────────────
    rt = sorted(t1)
    charts["recent"] = {"x": [_mshort(t) for t in rt],
                        "orig": [_r1(t1[t]["orig"]) for t in rt],
                        "sa": [_r1(t1[t]["sa"]) for t in rt],
                        "trend": [_r1(t1[t]["trend"]) for t in rt]}

    def _c(v):
        return "" if v is None else _idx(v)

    def _p(v):
        return "" if v is None else fmt.signed_pct(v / 100)

    tables["recent"] = [[_mname(t), _c(t1[t]["orig"]), _c(t1[t]["sa"]), _p(t1[t]["sa_pct"]),
                         _c(t1[t]["trend"])] for t in reversed(rt)]

    # ── 2. long run (t15) ────────────────────────────────────────────────
    lx = sorted(set(lp_sa) | set(lp_trend))
    flags["long"] = len(lx) >= 13
    if flags["long"]:
        charts["long"] = {"x": [_ym(t) for t in lx],
                          "sa": [_r1(lp_sa.get(t)) for t in lx],
                          "trend": [_r1(lp_trend.get(t)) for t in lx]}
        tables["long"] = [[str(y), _c(a), str(n)] for y, a, n in _yearly(lp_sa)]

    # ── 3. production by technology intensity (t17) + 6 jobs (t18) + 9 exports (t20)
    def tech_chart(key):
        s = tech[key]
        x = sorted(set().union(*[set(v) for v in s.values()]))
        if len(x) < 13:
            return None, None
        ch = {"x": [_ym(t) for t in x], "names": [he for _, he in TECH],
              "series": [[_r1(s[k].get(t)) for t in x] for k, _ in TECH]}
        tb = []
        for k, he in TECH:
            if not s[k]:
                continue
            t = max(s[k])
            first = min(s[k])
            tb.append([he, _c(s[k][t]), fmt.signed_pct(_yoy(s[k], t)) if _yoy(s[k], t) is not None
                       else "", fmt.signed_pct(_chg(s[k][t], s[k][first]))])
        return ch, tb

    for key, cid in (("t17", "tech"), ("t18", "techjobs"), ("t20", "techexp")):
        ch, tb = tech_chart(key)
        flags[cid] = ch is not None
        if ch:
            charts[cid], tables[cid] = ch, tb

    def first_month(key):
        s = tech[key]
        firsts = [min(v) for v in s.values() if v]
        return min(firsts) if firsts else None

    # ── 4. manufacturing with and without high tech (t2, t3) ─────────────
    tr2, tr3 = col(t2, "trend"), col(t3, "trend")
    ex = sorted(set(tr2) & set(tr3))
    flags["excl"] = len(ex) >= 13
    if flags["excl"]:
        charts["excl"] = {"x": [_mshort(t) for t in ex],
                          "all": [_r1(tr2[t]) for t in ex], "excl": [_r1(tr3[t]) for t in ex]}
        tables["excl"] = [[_mname(t), _c(tr2[t]), _c(tr3[t])] for t in reversed(ex)]

    # ── 5. production, jobs, hours (t15, t16, t7) ────────────────────────
    lj_trend = long_j["trend"]
    hours = col(t7, "trend")
    px = sorted(set(lp_trend) | set(lj_trend))
    flags["inputs"] = len(px) >= 13
    if flags["inputs"]:
        charts["inputs"] = {"x": [_ym(t) for t in px],
                            "prod": [_r1(lp_trend.get(t)) for t in px],
                            "jobs": [_r1(lj_trend.get(t)) for t in px],
                            "hours": [_r1(hours.get(t)) for t in px]}
        yp, yj, yh = ({y: a for y, a, _ in _yearly(s)} for s in (lp_trend, lj_trend, hours))
        tables["inputs"] = [[str(y), _c(yp.get(y)), _c(yj.get(y)), _c(yh.get(y))]
                            for y in sorted(set(yp) | set(yj))]

    # ── 7. local sales vs exports (t13, t14) ─────────────────────────────
    loc, exp = col(t13, "trend"), col(t14, "trend")
    lsa, esa = col(t13, "sa"), col(t14, "sa")
    mx = sorted(set(loc) | set(exp))
    flags["market"] = len(mx) >= 13
    if flags["market"]:
        charts["market"] = {"x": [_mshort(t) for t in mx],
                            "loc": [_r1(loc.get(t)) for t in mx],
                            "exp": [_r1(exp.get(t)) for t in mx],
                            "loc_sa": [_r1(lsa.get(t)) for t in mx],
                            "exp_sa": [_r1(esa.get(t)) for t in mx]}
        tables["market"] = [[_mname(t), _c(lsa.get(t)), _c(loc.get(t)), _c(esa.get(t)),
                             _c(exp.get(t))] for t in reversed(mx)]

    # ── 8. 12-month trend change by group × measure (t17-t20) ────────────
    measures = [("t17", "ייצור"), ("t18", "משרות שכיר"), ("t19", "פדיון מקומי"),
                ("t20", "יצוא")]
    grid = {}
    for key, _ in measures:
        for k, _he in TECH:
            s = tech[key][k]
            grid[(key, k)] = _yoy(s, max(s)) if s else None
    flags["matrix"] = sum(v is not None for v in grid.values()) >= 4
    if flags["matrix"]:
        charts["matrix"] = {
            "groups": [he for _, he in TECH], "measures": [m for _, m in measures],
            "series": [[None if grid[(key, k)] is None else round(grid[(key, k)] * 100, 1)
                        for k, _ in TECH] for key, _ in measures]}
        tables["matrix"] = [[he] + [fmt.signed_pct(grid[(key, k)]) if grid[(key, k)] is not None
                                    else "" for key, _ in measures] for k, he in TECH]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if mom is not None and yoy_orig is not None:
        add("latest", f"ב{_mname(lt)} עמד מדד הייצור התעשייתי (מנוכה עונתיות) על "
                      f"{_idx(last['sa'])}, {_dir(mom)} של {fmt.pct_of(abs(mom))} לעומת החודש "
                      f"הקודם. בנתונים המקוריים זו {_dir(yoy_orig)} של {fmt.pct(abs(yoy_orig))} "
                      f"לעומת {_mname((lt[0] - 1, lt[1]))}.")
    if yoy_trend is not None:
        if abs(yoy_trend) < RECENT_FLAT:
            add("trend", f"קו המגמה של הייצור התעשייתי כמעט לא השתנה בשנה האחרונה "
                         f"({fmt.signed_pct(yoy_trend)} מ{_mname((lt[0] - 1, lt[1]))} עד "
                         f"{_mname(lt)}).")
        else:
            add("trend", f"לפי קו המגמה, הייצור התעשייתי {'עלה' if yoy_trend > 0 else 'ירד'} "
                         f"ב-{fmt.pct(abs(yoy_trend))} בשנה האחרונה, מ-"
                         f"{_idx(trend1[(lt[0] - 1, lt[1])])} ב{_mname((lt[0] - 1, lt[1]))} ל-"
                         f"{_idx(trend1[lt])} ב{_mname(lt)}.")
    if flags["excl"]:
        t_end, t_start = ex[-1], (ex[-1][0] - 1, ex[-1][1])
        a, b = _chg(tr2.get(t_end), tr2.get(t_start)), _chg(tr3.get(t_end), tr3.get(t_start))
        if a is not None and b is not None and abs(a - b) >= 0.02:
            head = ("הצמיחה נשענת על ענפי הטכנולוגיה העילית" if a > b and a > 0 else
                    "ענפי הטכנולוגיה העילית ריככו את הירידה" if a > b else
                    "ענפי הטכנולוגיה העילית מושכים את התעשייה למטה")
            add("excl", f"{head}: בשנה עד {_mname(t_end)} מגמת הייצור בתעשייה כולה "
                        f"{_moved(a, True)}, ובלי ענפי הטכנולוגיה העילית {_moved(b, True)}.")
    if flags["matrix"]:
        prod = [(grid[("t17", k)], he) for k, he in TECH if grid[("t17", k)] is not None]
        if len(prod) >= 2:
            prod.sort(key=lambda p: (-p[0], p[1]))
            (hv, hn), (lv, ln) = prod[0], prod[-1]
            if hv - lv >= 0.03:
                add("tech", f"בשנה האחרונה הייצור בענפי הטכנולוגיה ה{hn} {_moved(hv)} (לפי "
                            f"המגמה), ובענפי הטכנולוגיה ה{ln} {_moved(lv)}.")
    if flags["market"]:
        t_end = max(set(loc) & set(exp)) if set(loc) & set(exp) else None
        if t_end:
            a, b = _yoy(exp, t_end), _yoy(loc, t_end)
            if a is not None and b is not None and abs(a - b) >= 0.02:
                add("market", f"בשנה עד {_mname(t_end)} היצוא התעשייתי (במחירים קבועים, לפי "
                              f"קו המגמה) {_moved(a)}, והמכירות לשוק המקומי "
                              f"{_moved(b).replace('עלה', 'עלו').replace('ירד', 'ירדו').replace('לא השתנה', 'לא השתנו')}.")
    if flags["inputs"]:
        common = sorted(set(lp_trend) & set(lj_trend))
        if len(common) >= 13:
            t0, t9 = common[0], common[-1]
            p, j = _chg(lp_trend[t9], lp_trend[t0]), _chg(lj_trend[t9], lj_trend[t0])
            if p is not None and j is not None and abs(p - j) >= 0.03:
                add("inputs", f"מאז {_mname(t0)} הייצור התעשייתי (לפי המגמה) {_moved(p)}, "
                              f"ומספר משרות השכיר בתעשייה {_moved(j)}: "
                              + ("יותר ייצור לכל משרה." if p > j else "פחות ייצור לכל משרה."))
    if lp_trend and len(lp_trend) >= 25:
        peak_t = max(lp_trend, key=lambda t: (lp_trend[t], t))
        if peak_t == lpt:
            add("peak", f"קו המגמה של הייצור התעשייתי ב{_mname(lpt)} ({_idx(lp_trend[lpt])}) "
                        f"הוא השיא מאז {_mname(min(lp_trend))}.")

    # ── text ─────────────────────────────────────────────────────────────
    base_txt = f" (בסיס: {base}=100)" if base else ""
    labels.update({
        "lede": (f"כמה מייצרת התעשייה הישראלית, איך הייצור משתנה מחודש לחודש, ואילו ענפים "
                 f"מושכים אותו: מדד הייצור התעשייתי של ענפי התעשייה, הכרייה והחציבה, לצד "
                 f"משרות השכיר, שעות העבודה, המכירות לשוק המקומי והיצוא. הנתונים מתוך ההודעה "
                 f"החודשית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), ומתעדכנים עם כל הודעה חדשה. "
                 f"הנתון האחרון הוא ל{_mname(lt)}: מדד של {_idx(last['sa'])}{base_txt}."),
        "recent_note": (f"מדד הייצור התעשייתי (תעשייה, כרייה וחציבה) בכל חודש מאז "
                        f"{_mname(rt[0])}: הנתון המקורי, המנוכה עונתיות וקו המגמה{base_txt}."),
        "recent_aria": f"מדד הייצור התעשייתי, {_mname(rt[0])} עד {_mname(rt[-1])}",
        "recent_caption": "מדד הייצור התעשייתי לפי חודש",
    })
    if flags["long"]:
        labels.update({
            "long_note": (f"המדד המנוכה עונתיות וקו המגמה מאז {_mname(lx[0])}. אפשר לגרור כדי "
                          f"להתמקד בתקופה."),
            "long_aria": f"מדד הייצור התעשייתי, {_mname(lx[0])} עד {_mname(lx[-1])}",
            "long_caption": "מדד הייצור התעשייתי המנוכה עונתיות, ממוצע שנתי",
        })
    for cid, key, what in (("tech", "t17", "מדד הייצור"), ("techjobs", "t18", "מדד משרות השכיר"),
                           ("techexp", "t20", "מדד היצוא (במחירים קבועים)")):
        if flags[cid]:
            fm = first_month(key)
            labels[cid + "_note"] = (f"{what} בתעשייה לפי עוצמה טכנולוגית של הענף, קו המגמה מאז "
                                     f"{_mname(fm)}. לחיצה על שם קבוצה מסתירה או מציגה אותה.")
            labels[cid + "_aria"] = f"{what} לפי עוצמה טכנולוגית מאז {_mname(fm)}"
            labels[cid + "_caption"] = f"{what} לפי עוצמה טכנולוגית: ערך אחרון ושינוי"
            labels[cid + "_since"] = f"שינוי מאז {_mname(fm)}"
    if flags["excl"]:
        labels.update({
            "excl_note": ("קו המגמה של הייצור בענפי התעשייה (ללא כרייה וחציבה), כולם ובלי ענפי "
                          "הטכנולוגיה העילית. הפער בין הקווים הוא תרומת ההייטק התעשייתי."),
            "excl_aria": f"ייצור תעשייתי עם ובלי טכנולוגיה עילית, {_mname(ex[0])} עד "
                         f"{_mname(ex[-1])}",
            "excl_caption": "מדד הייצור בתעשייה, מגמה: כולל ובלי טכנולוגיה עילית",
        })
    if flags["inputs"]:
        labels.update({
            "inputs_note": ("קווי המגמה של הייצור, משרות השכיר ושעות העבודה בפועל בתעשייה, "
                            "כרייה וחציבה. כשהייצור עולה מהר מהמשרות, כל משרה מייצרת יותר. "
                            "שעות העבודה מתפרסמות רק לחודשים האחרונים."),
            "inputs_aria": f"ייצור, משרות ושעות עבודה בתעשייה מאז {_mname(px[0])}",
            "inputs_caption": "ייצור, משרות ושעות עבודה, ממוצע שנתי של המגמה",
        })
    if flags["market"]:
        labels.update({
            "market_note": ("הפדיון ממכירות לשוק המקומי ומיצוא, במחירים קבועים: קו המגמה "
                            "(עבה) והנתון המנוכה עונתיות (דק)."),
            "market_aria": f"מכירות לשוק המקומי מול יצוא, {_mname(mx[0])} עד {_mname(mx[-1])}",
            "market_caption": "מדד הפדיון לשוק המקומי וליצוא לפי חודש",
        })
    if flags["matrix"]:
        labels.update({
            "matrix_note": ("השינוי בשנה האחרונה בקו המגמה של כל מדד, לכל קבוצת עוצמה "
                            "טכנולוגית: האם הענפים גדלים בייצור, בעובדים, בשוק המקומי וביצוא."),
            "matrix_aria": "שינוי שנתי בייצור, משרות, פדיון מקומי ויצוא לפי עוצמה טכנולוגית",
            "matrix_caption": "שינוי ב-12 חודשים לפי עוצמה טכנולוגית ומדד",
        })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"מדד הייצור התעשייתי בישראל לפי חודש ועוצמה טכנולוגית, מנתוני הלמ\"ס. "
               f"ב{_mname(lt)}: {_idx(last['sa'])}"
               + (f" ({fmt.signed_pct(yoy_trend)} במגמה השנתית)" if yoy_trend is not None else "")
               + ".")
    desc = (f"מדד הייצור התעשייתי ב{_mname(lt)}: {_idx(last['sa'])}"
            + (f", {fmt.signed_pct(yoy_trend)} במגמה בשנה" if yoy_trend is not None else "")
            + ". ייצור לפי עוצמה טכנולוגית, יצוא, משרות ושעות עבודה בתעשייה.")
    first_year = min([t[0] for t in lx] or [rt[0][0]])
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_year}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד הייצור התעשייתי: נתון חודשי עדכני | הלמ\"ס",
                "description": desc,
                "name": "מדד הייצור התעשייתי",
                "alternate_names": ["הייצור התעשייתי של ענפי התעשייה, הכרייה והחציבה",
                                    "מדד התעשייה", "ייצור תעשייתי בישראל",
                                    "מדדי תעשייה לפי עוצמה טכנולוגית"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
