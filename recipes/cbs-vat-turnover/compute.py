"""מדדי פדיון לכל ענפי הכלכלה: CBS's monthly VAT-based revenue indices.

Inputs are CBS grid tables from the newest edition of the release. Every
index is at constant 2011 prices, base average 2011 = 100.0, in three
variants: original data, seasonally adjusted and trend. Each table has a
block of annual rows (the last full years) and then monthly rows since
January of the earliest of those years.
  t1   total economy (excl. diamonds): trend % change, trend, SA, original
  t2   agriculture; manufacturing, mining and quarrying
  t3   trade: retail, wholesale + motor vehicles, trade total
  t4   electricity and water; construction; transportation and storage
  t5   accommodation and food; information and communications; finance
  t6   real estate; professional services; administrative services
  t7   education; health and welfare; arts, recreation and other services
  t8   high tech: in services, in manufacturing, total
  releases  the edition list (number, date, headline, link)

Header rows and columns are found by their labels (govlib.cbs) and raise
when missing: each industry is located by its English header label, and its
column block (trend / seasonally adjusted / original) is the one that holds
that label. Period rows are found by content, so a missing one only
shortens a series. "Latest month" is t1's newest month with a trend value.
"""
import re

import pandas as pd
from govlib import cbs, fmt

# (table, English header label, exact match?, key, Hebrew name, group).
# Group "main" is one of the 15 top-level industries of the classification;
# "trade" and "hitech" are the sub-series charted in their own sections.
INDUSTRIES = [
    ("t2", "Agriculture", False, "agri", "חקלאות, ייעור ודיג", "main"),
    ("t2", "Manufacturing, Mining", False, "manuf", "תעשייה, כרייה וחציבה", "main"),
    ("t3", "Total (45-47)", False, "trade", "מסחר סיטוני וקמעוני", "main"),
    ("t3", "Retail trade", False, "retail", "מסחר קמעוני", "trade"),
    ("t3", "Wholesale trade", False, "wholesale", "מסחר סיטוני ומסחר בכלי רכב", "trade"),
    ("t4", "Electricity and water", False, "utilities", "חשמל, מים, ביוב ופסולת", "main"),
    ("t4", "Construction", False, "constr", "בינוי", "main"),
    ("t4", "Transportation, storage", False, "transport", "תחבורה, אחסנה, דואר ובלדרות",
     "main"),
    ("t5", "Accommodation", False, "hosp", "שירותי אירוח ואוכל", "main"),
    ("t5", "Information and", False, "info", "מידע ותקשורת", "main"),
    ("t5", "Financial and", False, "finance", "שירותים פיננסיים וביטוח", "main"),
    ("t6", "Real-estate", False, "realestate", "פעילויות נדל\"ן", "main"),
    ("t6", "Professional, scientific", False, "prof", "שירותים מקצועיים, מדעיים וטכניים",
     "main"),
    ("t6", "Administrative and support", False, "admin", "שירותי ניהול ותמיכה", "main"),
    ("t7", "Education", False, "edu", "חינוך", "main"),
    ("t7", "Human health", False, "health", "בריאות, רווחה וסעד", "main"),
    ("t7", "Arts, entertainment", False, "arts", "אמנות, בידור, פנאי ושירותים אחרים", "main"),
    ("t8", "Total", True, "hitech", "הייטק, סך הכל", "hitech"),
    ("t8", "High tech in services", False, "hitech_srv", "הייטק בענפי השירותים", "hitech"),
    ("t8", "High tech in manufacturing", False, "hitech_mfg", "הייטק בענפי התעשייה",
     "hitech"),
]
TABLES = ("t2", "t3", "t4", "t5", "t6", "t7", "t8")
TREND = re.compile(r"^Trend\d*$")
BASE = re.compile(r"average ((?:19|20)\d\d)")
SEASON_MIN_YEARS = 2


# ── tables ───────────────────────────────────────────────────────────────


def _series(rows, start, cols):
    """{"annual": {year: {var: v}}, "monthly": {(y, m): {var: v}}} for the
    period rows after `start`; cols = {var: column}. Rows without any
    value (the empty months to come) are skipped."""
    out = {"annual": {}, "monthly": {}}
    for i, y, m, end in cbs.periods(rows, start, len(rows)):
        if end:
            continue  # a month range: not used by this release
        v = {k: cbs.val(rows[i], j) for k, j in cols.items()}
        if all(x is None for x in v.values()):
            continue
        if m is None:
            out["annual"][y] = v
        else:
            out["monthly"][(y, m)] = v
    return out


def _t1(rows):
    h = cbs.row_with(rows, "original", name="t1")
    cols = {"trend": cbs.col_after(rows[h], "trend"),
            "sa": cbs.col_after(rows[h], "seasonally"),
            "orig": cbs.col_after(rows[h], "original"),
            "pct": cbs.col_after(rows[h], "trend percent")}
    return _series(rows, h + 1, cols)


def _blocks(rows, name):
    """The (trend, sa, orig) column blocks of an industry table, the row
    their labels sit on, and the row the data starts after."""
    h = cbs.row_with(rows, "Original", name=name)
    orig = [j for j, c in enumerate(rows[h]) if c == "Original"]
    sa = [j for j, c in enumerate(rows[h]) if c == "Seasonally"]
    t = cbs.row_with(rows, "adjusted", h, name=name)
    trend = [j for j, c in enumerate(rows[t]) if TREND.match(c)]
    if not orig or not (len(orig) == len(sa) == len(trend)):
        raise ValueError(f"{name}: trend / seasonally adjusted / original columns don't pair up")
    blocks = []
    for o in orig:
        tr = max((j for j in trend if j < o), default=None)
        s = max((j for j in sa if j < o), default=None)
        if tr is None or s is None:
            raise ValueError(f"{name}: no trend column before original column {o}")
        blocks.append({"trend": tr, "sa": s, "orig": o})
    return blocks, h, t


def _industries(frames):
    out = {}
    for name in TABLES:
        rows = cbs.grid(frames[name], name)
        blocks, h, t = _blocks(rows, name)
        for tbl, label, exact, key, he, group in INDUSTRIES:
            if tbl != name:
                continue
            r = cbs.row_with(rows, label, name=name, contains=not exact)
            if r >= h:
                raise ValueError(f"{name}: label {label!r} is not in the header")
            j = cbs.col_after(rows[r], label, 0, contains=not exact)
            blk = next((b for b in blocks if b["trend"] <= j <= b["orig"]), None)
            if blk is None:
                raise ValueError(f"{name}: no column block under {label!r}")
            s = _series(rows, t + 1, blk)
            out[key] = {"key": key, "name": he, "group": group, **s}
    return out


# ── helpers ──────────────────────────────────────────────────────────────


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _tone(c, band=0.005):
    if c is None:
        return "brand"
    return "ok" if c > band else "danger" if c < -band else "warn"


def _word(c):
    return "עלייה" if c > 0 else "ירידה"


def _r(v, d=1):
    return None if v is None else round(v, d)


def _idx(v):
    return "" if v is None else fmt.num_he(v, 1)


def _spct(c):
    return "" if c is None else fmt.signed_pct(c)


def _ytd(monthly, year, last_m, var="orig"):
    """Sum of `var` for months 1..last_m of `year` and the year before,
    or None when a month is missing in either."""
    cur = [monthly.get((year, m), {}).get(var) for m in range(1, last_m + 1)]
    prev = [monthly.get((year - 1, m), {}).get(var) for m in range(1, last_m + 1)]
    if any(v is None for v in cur + prev):
        return None
    return sum(cur) / sum(prev) - 1


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    tot = _t1(cbs.grid(frames["t1"], "t1"))
    head = cbs.grid(frames["t2"], "t2")
    m = BASE.search(" ".join(c for r in head[:cbs.row_with(head, "Base:", name="t2",
                                                             contains=True) + 1] for c in r))
    if not m:
        raise ValueError("t2: base year label not found")
    base = m.group(1)
    war = next((c for r in head for c in r if "חרבות ברזל" in c), "")
    mon = tot["monthly"]
    months = sorted(t for t, v in mon.items() if v["trend"] is not None)
    if not months:
        raise ValueError("t1: no monthly trend rows")
    lt = months[-1]
    ya = (lt[0] - 1, lt[1])
    last = mon[lt]
    prev_m = months[-2] if len(months) >= 2 else None
    mom = last["pct"] / 100 if last["pct"] is not None else (
        _chg(last["trend"], mon[prev_m]["trend"]) if prev_m else None)
    yoy = _chg(last["trend"], mon.get(ya, {}).get("trend"))
    ytd = _ytd(mon, lt[0], lt[1]) if lt[1] < 12 else None

    ind = _industries(frames)

    def at(key, t, var="trend"):
        return ind[key]["monthly"].get(t, {}).get(var)

    # The industry month: the newest month every industry table reaches
    # (the same month as t1 in a normal edition).
    ends = [max(t for t, v in s["monthly"].items() if v["trend"] is not None)
            for s in ind.values() if any(v["trend"] is not None for v in s["monthly"].values())]
    it = min(ends + [lt])
    iya = (it[0] - 1, it[1])
    main = [k for k, v in ind.items() if v["group"] == "main"]
    rank = []
    for k in main:
        c = _chg(at(k, it), at(k, iya))
        if c is not None:
            rank.append((k, c))
    rank.sort(key=lambda kc: (-kc[1], kc[0]))
    rising = sum(1 for _, c in rank if c > 0)

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["level"] = {"value": round(last["trend"], 1), "display": fmt.num_he(last["trend"], 1),
                     "tone": "brand"}
    labels["level_kpi"] = f"מדד הפדיון בכלל המשק, {_mname(lt)} (מגמה, {base}=100)"
    if mom is not None:
        kpis["mom"] = {"value": round(mom, 4), "display": fmt.signed_pct(mom, 2),
                       "tone": _tone(mom, 0.0005)}
        labels["mom_kpi"] = "שינוי המגמה לעומת החודש הקודם"
    if yoy is not None:
        kpis["yoy"] = {"value": round(yoy, 4), "display": fmt.signed_pct(yoy), "tone": _tone(yoy)}
        labels["yoy_kpi"] = f"שינוי המגמה לעומת {_mname(ya)}"
    if ytd is not None:
        kpis["ytd"] = {"value": round(ytd, 4), "display": fmt.signed_pct(ytd), "tone": _tone(ytd)}
        labels["ytd_kpi"] = (f"פדיון ינואר עד {fmt.MONTHS_HE[lt[1] - 1]} {lt[0]} "
                             f"לעומת התקופה המקבילה ב-{lt[0] - 1}")
    if rank:
        kpis["rising"] = {"value": rising, "display": str(rising),
                          "tone": "ok" if rising * 2 > len(rank) else "warn"}
        labels["rising_kpi"] = f"ענפים שהפדיון בהם עלה בשנה האחרונה, מתוך {len(rank)}"

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables, flags = {}, {}, {}
    ms = sorted(mon)
    charts["total"] = {"x": [_mshort(t) for t in ms],
                       "orig": [_r(mon[t]["orig"]) for t in ms],
                       "sa": [_r(mon[t]["sa"]) for t in ms],
                       "trend": [_r(mon[t]["trend"]) for t in ms]}
    tables["total"] = [[_mname(t), _idx(mon[t]["orig"]), _idx(mon[t]["sa"]),
                        _idx(mon[t]["trend"])] for t in reversed(ms)]

    pm = [t for t in ms if mon[t]["pct"] is not None]
    flags["momentum"] = len(pm) >= 6
    charts["momentum"] = {"x": [_mshort(t) for t in pm],
                          "y": [round(mon[t]["pct"], 2) for t in pm]}
    tables["momentum"] = [[_mname(t), fmt.signed_pct(mon[t]["pct"] / 100, 2)]
                          for t in reversed(pm)]

    first = months[0]
    flags["yoy"] = len(rank) >= 3
    charts["yoy"] = {"names": [ind[k]["name"] for k, _ in rank],
                     "y": [round(c * 100, 1) for _, c in rank],
                     "total": round(yoy * 100, 1) if yoy is not None else None}
    tables["yoy"] = [[ind[k]["name"], _idx(at(k, it)), fmt.signed_pct(c)]
                     for k, c in rank]

    lv = sorted(((k, at(k, it)) for k in main if at(k, it) is not None),
                key=lambda kv: (-kv[1], kv[0]))
    flags["level"] = len(lv) >= 3
    charts["level"] = {"names": [ind[k]["name"] for k, _ in lv],
                       "y": [round(v, 1) for _, v in lv], "total": round(last["trend"], 1)}
    tables["level"] = [[ind[k]["name"], _idx(v), fmt.num_he(v / 100, 1)] for k, v in lv]

    # Annual change heatmap: each full year against the one before, and the
    # months of the latest year so far against the same months a year earlier.
    years = sorted(tot["annual"])
    cols = [(y, f"{y} לעומת {y - 1}") for y in years if y - 1 in tot["annual"]]
    ytd_label = (f"ינו׳-{fmt.MONTHS_SHORT_HE[it[1] - 1]} {it[0]}"
                 if it[1] < 12 and it[0] not in tot["annual"] else None)
    heat_names, heat_cells, heat_rows = [], [], []
    hm_keys = ["__total"] + [k for k, _ in rank]
    for r, k in enumerate(hm_keys):
        src = tot if k == "__total" else ind[k]
        nm = "כלל המשק" if k == "__total" else src["name"]
        row = [nm]
        for c, (y, _) in enumerate(cols):
            ch = _chg(src["annual"].get(y, {}).get("orig"),
                      src["annual"].get(y - 1, {}).get("orig"))
            row.append(_spct(ch))
            if ch is not None:
                heat_cells.append([c, r, round(ch * 100, 1)])
        if ytd_label:
            ch = _ytd(src["monthly"], it[0], it[1])
            row.append(_spct(ch))
            if ch is not None:
                heat_cells.append([len(cols), r, round(ch * 100, 1)])
        heat_names.append(nm)
        heat_rows.append(row)
    heat_cols = [lbl for _, lbl in cols] + ([ytd_label] if ytd_label else [])
    flags["annual"] = len(heat_cols) >= 2 and len(heat_cells) >= 6
    span = max([abs(c[2]) for c in heat_cells] or [1])
    charts["annual"] = {"cols": heat_cols, "names": heat_names, "cells": heat_cells,
                        "max": min(round(span), 30)}
    tables["annual"] = heat_rows
    labels["annual_cols"] = heat_cols

    def group(keys, chart_id):
        keys = [k for k in keys if ind[k]["monthly"]]
        tm = sorted({t for k in keys for t in ind[k]["monthly"]})
        charts[chart_id] = {"x": [_mshort(t) for t in tm],
                            "names": [ind[k]["name"] for k in keys],
                            "series": [[_r(at(k, t)) for t in tm] for k in keys]}
        tables[chart_id] = [[ind[k]["name"], _idx(at(k, first)), _idx(at(k, iya)),
                             _idx(at(k, it)), _spct(_chg(at(k, it), at(k, iya)))]
                            for k in keys]
        flags[chart_id] = len(tm) >= 6
        return keys

    group(["trade", "retail", "wholesale"], "trade")
    group(["hitech", "hitech_srv", "hitech_mfg"], "hitech")

    # Seasonality: original data, month × year, and the average ratio of
    # the original to the seasonally adjusted figure in each calendar month.
    by_year = {}
    for (y, m), v in mon.items():
        if v["orig"] is not None:
            by_year.setdefault(y, {})[m] = v["orig"]
    sy = sorted(by_year)
    charts["seasons"] = {"x": fmt.MONTHS_SHORT_HE, "years": [str(y) for y in sy],
                         "series": [[_r(by_year[y].get(m)) for m in range(1, 13)] for y in sy]}
    tables["seasons"] = [[fmt.MONTHS_HE[m - 1]] + [_idx(by_year[y].get(m)) for y in sy]
                         for m in range(1, 13)]
    labels["season_years"] = [str(y) for y in sy]
    flags["seasons"] = len(sy) >= 2
    factor = {}
    for m in range(1, 13):
        rs = [mon[(y, m)]["orig"] / mon[(y, m)]["sa"] for y in sy
              if (y, m) in mon and mon[(y, m)]["orig"] and mon[(y, m)]["sa"]]
        if len(rs) >= SEASON_MIN_YEARS:
            factor[m] = sum(rs) / len(rs) - 1

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if mom is not None:
        streak = 0
        sign = 1 if mom > 0 else -1
        for t in reversed(pm):
            p = mon[t]["pct"]
            if p * sign > 0:
                streak += 1
            else:
                break
        tail = (f", החודש ה-{streak} ברציפות של {'עלייה' if sign > 0 else 'ירידה'}"
                if streak >= 3 else "")
        add("momentum", f"ב{_mname(lt)} עמד מדד המגמה של הפדיון בכלל המשק על "
                        f"{fmt.num_he(last['trend'], 1)} נקודות, {_word(mom)} של "
                        f"{fmt.pct(abs(mom), 2)} לעומת החודש הקודם{tail}.")
    if yoy is not None:
        add("yoy", f"לעומת {_mname(ya)} {'עלה' if yoy > 0 else 'ירד'} הפדיון בכלל המשק "
                   f"(לפי קו המגמה, במחירים קבועים) ב-{fmt.pct(abs(yoy))}.")
    if ytd is not None:
        add("ytd", f"בחודשים ינואר עד {fmt.MONTHS_HE[lt[1] - 1]} {lt[0]} היה הפדיון בכלל המשק "
                   f"{'גבוה' if ytd > 0 else 'נמוך'} ב-{fmt.pct(abs(ytd))} מאשר באותם חודשים "
                   f"ב-{lt[0] - 1} (נתונים מקוריים, במחירים קבועים).")
    if len(rank) >= 3:
        (k0, c0), (k1, c1) = rank[0], rank[-1]
        low = (f"ובענף {ind[k1]['name']} נרשמה ירידה של {fmt.pct(abs(c1))}" if c1 < 0
               else f"והצמיחה האיטית ביותר בענף {ind[k1]['name']} ({fmt.signed_pct(c1)})")
        if c0 <= 0:
            add("leaders", f"בשנה האחרונה מדד המגמה של הפדיון ירד בכל {len(rank)} ענפי המשק. "
                           f"הירידה הקטנה ביותר בענף {ind[k0]['name']} ({fmt.signed_pct(c0)}), "
                           f"והחדה ביותר בענף {ind[k1]['name']} ({fmt.signed_pct(c1)}).")
        else:
            add("leaders", f"מבין {len(rank)} ענפי המשק, הפדיון צמח הכי מהר בשנה האחרונה בענף "
                           f"{ind[k0]['name']} ({fmt.signed_pct(c0)} במגמה), {low}. "
                           + (f"ב-{rising} ענפים המגמה עלתה." if rising != 1
                              else "רק בענף אחד המגמה עלתה."))
    hs, hm = (_chg(at(k, it), at(k, iya)) for k in ("hitech_srv", "hitech_mfg"))
    if hs is not None and hm is not None and abs(hs - hm) >= 0.05:
        fast, slow = (("hitech_mfg", hm), ("hitech_srv", hs)) if hm > hs else \
            (("hitech_srv", hs), ("hitech_mfg", hm))
        where = {"hitech_mfg": "בענפי התעשייה", "hitech_srv": "בענפי השירותים"}
        add("hitech", f"בהייטק הפער בולט: {where[fast[0]]} הפדיון "
                      f"{'עלה' if fast[1] > 0 else 'ירד'} בשנה ב-{fmt.pct(abs(fast[1]))}, "
                      f"ו{where[slow[0]]} {'עלה' if slow[1] > 0 else 'ירד'} ב-"
                      f"{fmt.pct(abs(slow[1]))}.")
    lv_first = at("hitech_mfg", first)
    if lv_first and at("hitech_mfg", it) and at("hitech_mfg", it) / lv_first >= 1.5:
        add("hitech_long", f"מדד הפדיון של ענפי ההייטק בתעשייה הגיע ל-"
                           f"{fmt.num_he(at('hitech_mfg', it), 1)} נקודות ב{_mname(it)}, פי "
                           f"{fmt.num_he(at('hitech_mfg', it) / lv_first, 1)} מאשר ב"
                           f"{_mname(first)}.")
    rc, wc = (_chg(at(k, it), at(k, iya)) for k in ("retail", "wholesale"))
    if rc is not None and wc is not None:
        add("trade", f"במסחר, הפדיון של המסחר הקמעוני {'עלה' if rc > 0 else 'ירד'} בשנה "
                     f"ב-{fmt.pct(abs(rc))}, ושל המסחר הסיטוני והמסחר בכלי רכב "
                     f"{'עלה' if wc > 0 else 'ירד'} ב-{fmt.pct(abs(wc))}.")
    if len(factor) >= 10:
        hi = max(factor, key=lambda m: (factor[m], -m))
        lo = min(factor, key=lambda m: (factor[m], m))
        if factor[hi] >= 0.03 and factor[lo] <= -0.03:
            add("season", f"לפדיון עונתיות ברורה: ב{fmt.MONTHS_HE[hi - 1]} הוא גבוה בממוצע "
                          f"ב-{fmt.pct(factor[hi])} מהרמה המנוכה עונתיות, וב"
                          f"{fmt.MONTHS_HE[lo - 1]} נמוך ב-{fmt.pct(-factor[lo])}.")
    if len(years) >= 2:
        y1, y0 = years[-1], years[-2]
        c = _chg(tot["annual"][y1]["orig"], tot["annual"][y0]["orig"])
        if c is not None:
            add("annual", f"בשנת {y1} כולה {'עלה' if c > 0 else 'ירד'} הפדיון בכלל המשק "
                          f"ב-{fmt.pct(abs(c))} לעומת {y0}, במחירים קבועים.")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"כמה מוכרים העסקים בישראל, ואיך הפדיון משתנה מחודש לחודש בכל ענף במשק. "
                 f"המדדים מחושבים מדיווחי העסקים למע\"מ ומוצגים במחירים קבועים, כך שהם "
                 f"משקפים שינוי בהיקף הפעילות ולא רק בעליית המחירים. הנתונים מתוך ההודעה "
                 f"החודשית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), ומתעדכנים עם כל הודעה "
                 f"חדשה. הנתון האחרון הוא ל{_mname(lt)}."),
        "total_note": (f"מדד הפדיון בכל ענפי הכלכלה (ללא יהלומים) בכל חודש מאז "
                       f"{_mname(ms[0])}: הנתון המקורי, המנוכה עונתיות וקו המגמה. "
                       f"הבסיס: ממוצע {base} = 100."),
        "total_aria": f"מדד הפדיון בכלל המשק, {_mname(ms[0])} עד {_mname(ms[-1])}",
        "total_caption": "מדד הפדיון בכלל המשק לפי חודש",
        "momentum_note": ("בכמה אחוזים השתנה קו המגמה בכל חודש לעומת החודש שלפניו. "
                          "עמודה ירוקה היא עלייה, אדומה היא ירידה."),
        "momentum_aria": "שינוי חודשי במגמת הפדיון בכלל המשק",
        "momentum_caption": "שינוי חודשי במגמה",
        "yoy_note": (f"השינוי במדד המגמה של כל ענף ב{_mname(it)} לעומת {_mname(iya)}. "
                     f"הקו המקווקו הוא השינוי בכלל המשק."),
        "yoy_aria": f"שינוי שנתי בפדיון לפי ענף, {_mname(it)}",
        "yoy_caption": f"מדד המגמה ושינוי שנתי לפי ענף, {_mname(it)}",
        "level_note": (f"רמת המדד בכל ענף ב{_mname(it)} (קו המגמה). המדד שווה 100 בממוצע "
                       f"של {base}, כך שמדד של 200 פירושו פדיון כפול מאשר ב-{base}, במחירים "
                       f"קבועים. הקו המקווקו הוא כלל המשק."),
        "level_head": f"כמה גדל כל ענף מאז {base}",
        "level_col": f"פי כמה מ-{base}",
        "about_base": (f"המדדים מחושבים מהפדיון (המכירות) שהעסקים מדווחים לרשות המסים "
                       f"במסגרת דיווחי המע\"מ, ומוצגים במחירים קבועים של {base}. כלל המשק "
                       f"לא כולל את ענף היהלומים."),
        "about_war": (f"{war}." if war and not war.endswith(".") else war),
        "level_aria": f"מדד הפדיון לפי ענף, {_mname(it)}",
        "level_caption": f"מדד הפדיון לפי ענף וגידול מאז {base}",
        "annual_note": ("השינוי בפדיון של כל ענף משנה לשנה, לפי הממוצע השנתי של הנתונים "
                        "המקוריים" + (", והחודשים של השנה הנוכחית לעומת אותם חודשים "
                                      "בשנה הקודמת" if ytd_label else "")
                        + ". ירוק הוא עלייה, אדום הוא ירידה."),
        "annual_aria": "שינוי שנתי בפדיון לפי ענף ושנה",
        "annual_caption": "שינוי שנתי בפדיון לפי ענף",
        "trade_note": (f"מדד המגמה של הפדיון במסחר מאז {_mname(first)}: המסחר הקמעוני "
                       f"(חנויות), המסחר הסיטוני יחד עם המסחר בכלי רכב, וסך ענף המסחר."),
        "trade_aria": "מדד הפדיון במסחר הקמעוני והסיטוני",
        "trade_caption": "מדד הפדיון במסחר",
        "hitech_note": (f"מדד המגמה של הפדיון בענפי ההייטק מאז {_mname(first)}: הייטק "
                        f"בענפי השירותים (תוכנה, מחקר ופיתוח, תקשורת), הייטק בענפי התעשייה, "
                        f"וסך ההייטק."),
        "hitech_aria": "מדד הפדיון בענפי ההייטק",
        "hitech_caption": "מדד הפדיון בהייטק",
        "group_cols": ["ענף", _mname(first), _mname(iya), _mname(it), "שינוי שנתי"],
        "seasons_note": ("מדד הפדיון בכלל המשק בכל חודש, שנה מול שנה (נתונים מקוריים). "
                         "החגים, מספר ימי העבודה בחודש והקניות של סוף השנה מזיזים את "
                         "הפדיון מחודש לחודש."),
        "seasons_aria": "מדד הפדיון לפי חודש, שנה מול שנה",
        "seasons_caption": "מדד הפדיון בכלל המשק לפי חודש ושנה",
    })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"מדדי הפדיון החודשיים של ענפי המשק לפי נתוני מע\"מ, מהלמ\"ס. ב{_mname(lt)} "
               f"מדד המגמה בכלל המשק: {fmt.num_he(last['trend'], 1)}"
               + (f" ({fmt.signed_pct(yoy)} בשנה)" if yoy is not None else "") + ".")
    desc = (f"מדד הפדיון בכלל המשק ב{_mname(lt)}: {fmt.num_he(last['trend'], 1)} נקודות"
            + (f", {fmt.signed_pct(yoy)} בשנה" if yoy is not None else "")
            + ". פדיון העסקים לפי ענף, הייטק ומסחר, מנתוני מע\"מ.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{ms[0][0]}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד הפדיון במשק לפי ענף, נתוני מע\"מ | הלמ\"ס",
                "description": desc,
                "name": "מדדי פדיון לפי ענפי הכלכלה",
                "alternate_names": ["מדדי פדיון לכל ענפי הכלכלה על פי נתוני מע\"מ",
                                    "מדד הפדיון במשק", "פדיון העסקים לפי ענף",
                                    "מחזור העסקאות במשק לפי מע\"מ"],
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
