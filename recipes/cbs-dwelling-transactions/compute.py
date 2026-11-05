"""דירות בעסקאות נדל"ן: CBS's monthly release on dwellings sold.

Inputs are CBS grid tables from the newest edition of the release:
  t1   dwellings sold per month (and per full year): second-hand, new, total,
       each as original / seasonally adjusted / trend, plus the new dwellings
       sold under government subsidy ("מחיר למשתכן" and its successors).
       Monthly rows since January of the year before last.
  t2   new dwellings still for sale at month end (original / SA / trend) and
       months of supply, same months as t1.
  t4..t8  the release's chart-data sheets. Their order moved between
       editions (2025: a by-district table sat in t4 and the charts started at
       t5; some editions have four charts, not five), so each sheet is
       identified by its title, not by its stem:
         sales trend since 2016 (total / new / second-hand)       required
         new dwellings for sale by district, latest month          required
         new dwellings for sale in the big cities, latest month    required
         new dwellings for sale, trend since 2019                  optional
         dwellings sold in the last six months (original)          unused, t1 has it
  releases  the edition list (number, date, headline, link)

Header rows and columns are found by their labels and raise when missing;
data rows (months, districts, cities) are found by pattern, so a missing one
only shortens a series. Months in these sheets are arabic numerals (1-12),
not the roman numerals govlib.cbs.periods reads, hence the local `_months`.
"""
import pandas as pd
from govlib import cbs, fmt

TABLES = ("t4", "t5", "t6", "t7", "t8")
MONTH_VALUES = {str(m): m for m in range(1, 13)}


# ── grid helpers ─────────────────────────────────────────────────────────


def _find(row, pred, start=0, what="label"):
    for j in range(max(0, start), len(row)):
        if row[j] and pred(row[j]):
            return j
    raise ValueError(f"header {what} not found after column {start}")


def _row(rows, pred, start=0, what="label"):
    for i in range(max(0, start), len(rows)):
        if any(c and pred(c) for c in rows[i]):
            return i
    raise ValueError(f"header row {what} not found")


def _months(rows, start, stop=None):
    """[(row index, year, month or None)] for rows[start:stop]: the year
    column holds the most 4-digit years (carried down), the month column the
    most whole numbers 1-12. A year with no month is a full-year row."""
    stop = len(rows) if stop is None else stop
    body = rows[start:stop]
    ycol = cbs.best_col(body, lambda v: bool(cbs.YEAR.match(v)))
    if ycol is None:
        raise ValueError("no year column")
    mcol = cbs.best_col(body, lambda v: v in MONTH_VALUES, exclude={ycol})
    out, year = [], None
    for i in range(start, stop):
        r = rows[i]
        y = cbs.cell(r, ycol)
        m = cbs.cell(r, mcol) if mcol is not None else ""
        if cbs.YEAR.match(y):
            year = int(y)
        if year is None:
            continue
        if m in MONTH_VALUES:
            out.append((i, year, MONTH_VALUES[m]))
        elif not m and cbs.YEAR.match(y):
            out.append((i, year, None))
    return out


def _title(rows):
    """The chart title ("תרשים 2 - …") of a chart-data sheet, or ""."""
    for r in rows[:12]:
        for c in r:
            if c.startswith(("תרשים", "לוח")):
                return c
    return ""


def _kind(title):
    if "שנותרו למכירה" in title:
        if "מחוז" in title:
            return "district"
        if "בערים" in title or "ערים" in title:
            return "cities"
        if "מגמה" in title:
            return "stock_trend"
        return None
    if "שנמכרו" in title:
        return "sales_trend" if "מגמה" in title else "recent"
    return None


# ── tables ───────────────────────────────────────────────────────────────


def _t1(rows):
    """{"months": {(y, m): rec}, "years": {y: rec}}; rec holds
    {group: {"orig", "sa", "trend"}} for second/new/total plus "sub"."""
    g = _row(rows, lambda c: "ממשלתי" in c, what="government-subsidy group")
    grp = rows[g]
    sub = _find(grp, lambda c: "ממשלתי" in c, what="government-subsidy column")
    labels = {
        "second": _find(grp, lambda c: "יד שנייה" in c or "יד שניה" in c, what="second-hand group"),
        "new": _find(grp, lambda c: "חדשות" in c and "ממשלתי" not in c and "א" <= c[0] <= "ת",
                     what="new-dwellings group"),
        "total": _find(grp, lambda c: c.startswith(("סה\"כ", "סך")), what="total group"),
    }
    mrow = _row(rows, lambda c: "מקוריים" in c, g, what="measure row (מקוריים)")
    meas = rows[mrow]
    starts = sorted(j for j, c in enumerate(meas) if c.startswith("Trend"))
    if len(starts) < 3:
        raise ValueError("t1: fewer than three measure blocks")
    cols = {}
    for key, lab in labels.items():
        # the block whose span holds the group's label
        s = max((j for j in starts if j <= lab), default=None)
        if s is None:
            raise ValueError(f"t1: no measure block for {key}")
        cols[key] = {"trend": _find(meas, lambda c: c.startswith("מגמה"), s, "מגמה"),
                     "sa": _find(meas, lambda c: "מנוכי עונתיות" in c, s, "מנוכי עונתיות"),
                     "orig": _find(meas, lambda c: "מקוריים" in c, s, "מקוריים")}
    months, years = {}, {}
    for i, y, m in _months(rows, mrow + 1):
        r = rows[i]
        rec = {k: {q: cbs.val(r, j) for q, j in c.items()} for k, c in cols.items()}
        rec["sub"] = cbs.val(r, sub)
        if rec["total"]["orig"] is None:
            continue
        (years if m is None else months)[y if m is None else (y, m)] = rec
    if not months:
        raise ValueError("t1: no monthly rows")
    return {"months": months, "years": years}


def _t2(rows):
    h = _row(rows, lambda c: "חודשי היצע" in c, what="months of supply")
    supply = _find(rows[h], lambda c: "חודשי היצע" in c, what="months of supply")
    mrow = _row(rows, lambda c: "מקוריים" in c, h, what="measure row (מקוריים)")
    meas = rows[mrow]
    cols = {"trend": _find(meas, lambda c: c.startswith("מגמה"), what="מגמה"),
            "sa": _find(meas, lambda c: "מנוכי עונתיות" in c, what="מנוכי עונתיות"),
            "orig": _find(meas, lambda c: "מקוריים" in c, what="מקוריים")}
    out = {}
    for i, y, m in _months(rows, mrow + 1):
        if m is None:
            continue
        rec = {k: cbs.val(rows[i], j) for k, j in cols.items()}
        rec["supply"] = cbs.val(rows[i], supply)
        if rec["orig"] is not None or rec["trend"] is not None:
            out[(y, m)] = rec
    return out


def _sales_trend(rows):
    h = _row(rows, lambda c: c == "סך הכל", what="סך הכל")
    hdr = rows[h]
    cols = {"total": _find(hdr, lambda c: c == "סך הכל", what="סך הכל"),
            "new": _find(hdr, lambda c: c.startswith("דירות חדשות"), what="דירות חדשות"),
            "second": _find(hdr, lambda c: "יד שנייה" in c or "יד שניה" in c, what="יד שנייה")}
    out = {}
    for i, y, m in _months(rows, h + 1):
        if m is None:
            continue
        rec = {k: cbs.val(rows[i], j) for k, j in cols.items()}
        if rec["total"] is not None:
            out[(y, m)] = rec
    return out


def _stock_trend(rows):
    h = _row(rows, lambda c: "מגמה" in c and not c.startswith("תרשים"), what="נתוני מגמה")
    col = _find(rows[h], lambda c: "מגמה" in c, what="נתוני מגמה")
    out = {}
    for i, y, m in _months(rows, h + 1):
        v = cbs.val(rows[i], col)
        if m is not None and v is not None:
            out[(y, m)] = v
    return out


def _named(rows, header_pred, what):
    """[(name, value)] under a two-column header (name, count)."""
    h = _row(rows, header_pred, what=what)
    vcol = _find(rows[h], header_pred, what=what)
    ncol = 0 if vcol != 0 else 1
    out = []
    for r in rows[h + 1:]:
        name, v = cbs.cell(r, ncol), cbs.val(r, vcol)
        if not name or v is None or not any("א" <= ch <= "ת" for ch in name):
            continue
        out.append((name, v))
    return out


def _district_name(n):
    n = n.strip()
    n = n.removeprefix("מחוז ")
    return {"צפון": "הצפון", "דרום": "הדרום", "מרכז": "המרכז"}.get(n, n)


# ── formatting ───────────────────────────────────────────────────────────


def _dl(n):
    """"מחוז תל אביב", but "אזור יהודה והשומרון" as is."""
    return n if n.startswith("אזור") else f"מחוז {n}"


def _n(v):
    return fmt.int_he(v)


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _word(c):
    return "עלייה" if c > 0 else "ירידה"


def _more(c):
    return "יותר" if c > 0 else "פחות"


def _r(v):
    return None if v is None else round(v)


def _sum(recs, path):
    vals = [path(r) for r in recs]
    return sum(vals) if vals and all(v is not None for v in vals) else None


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"], kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    t1 = _t1(cbs.grid(frames["t1"], "t1"))
    t2 = _t2(cbs.grid(frames["t2"], "t2"))
    found = {}
    for name in TABLES:
        rows = cbs.grid(frames[name], name)
        k = _kind(_title(rows))
        if k and k not in found:
            found[k] = rows
    for k in ("sales_trend", "district", "cities"):
        if k not in found:
            raise ValueError(f"chart sheet {k!r} not found in {', '.join(TABLES)}")
    trend = _sales_trend(found["sales_trend"])
    stock_t = _stock_trend(found["stock_trend"]) if "stock_trend" in found else {}
    districts = _named(found["district"], lambda c: c == "נותרו למכירה", "נותרו למכירה")
    cities = _named(found["cities"], lambda c: "שנותרו למכירה" in c and not c.startswith("תרשים"),
                    "סך דירות שנותרו למכירה")
    if not districts or not cities:
        raise ValueError("district or city chart has no rows")

    months = t1["months"]
    mt = sorted(months)
    lt = mt[-1]
    last = months[lt]
    ly = (lt[0] - 1, lt[1])
    prev = months.get(ly)

    def new_plain(r):
        n, s = r["new"]["orig"], r["sub"]
        return None if n is None else n - (s or 0)

    # ── year to date: January .. latest month, this year and last ──────
    ytd_now = [months[(lt[0], m)] for m in range(1, lt[1] + 1) if (lt[0], m) in months]
    ytd_then = [months[(lt[0] - 1, m)] for m in range(1, lt[1] + 1) if (lt[0] - 1, m) in months]
    ytd_ok = len(ytd_now) == lt[1] and len(ytd_then) == lt[1]
    parts = {"total": lambda r: r["total"]["orig"], "second": lambda r: r["second"]["orig"],
             "new": lambda r: r["new"]["orig"], "sub": lambda r: r["sub"],
             "plain": new_plain}
    ytd = {k: (_sum(ytd_now, f), _sum(ytd_then, f)) for k, f in parts.items()} if ytd_ok else {}

    # ── stock: t2 by month, extended back with the trend chart sheet ─────
    st_months = sorted(t2)
    st_last_t = st_months[-1] if st_months else None
    st_last = t2[st_last_t] if st_last_t else None
    stock_series = dict(stock_t)
    for t, rec in t2.items():
        if rec["trend"] is not None:
            stock_series[t] = rec["trend"]

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    yoy = _chg(last["total"]["orig"], prev["total"]["orig"] if prev else None)
    kpis["sold"] = {"value": round(last["total"]["orig"]), "display": _n(last["total"]["orig"]),
                    "tone": "brand"}
    labels["sold_kpi"] = f"דירות שנמכרו ב{_mname(lt)}"
    if yoy is not None:
        kpis["yoy"] = {"value": round(yoy, 4), "display": fmt.signed_pct(yoy),
                       "tone": "ok" if yoy > 0.02 else "danger" if yoy < -0.02 else "warn"}
        labels["yoy_kpi"] = f"שינוי לעומת {_mname(ly)}"
    if ytd and ytd["new"][0] and ytd["sub"][0] is not None:
        share = ytd["sub"][0] / ytd["new"][0]
        kpis["sub"] = {"value": round(share, 4), "display": fmt.pct(share), "tone": "info"}
        labels["sub_kpi"] = f"מהדירות החדשות שנמכרו ב-{lt[0]} נמכרו בסבסוד ממשלתי"
    if st_last and st_last["orig"] is not None:
        st_prev = t2.get((st_last_t[0] - 1, st_last_t[1]))
        c = _chg(st_last["orig"], st_prev["orig"] if st_prev else None)
        kpis["stock"] = {"value": round(st_last["orig"]), "display": _n(st_last["orig"]),
                         "tone": "brand" if c is None else "warn" if c > 0.02 else
                         "ok" if c < -0.02 else "brand"}
        labels["stock_kpi"] = f"דירות חדשות שנותרו למכירה, סוף {_mname(st_last_t)}"
    if st_last and st_last["supply"] is not None:
        sp_prev = t2.get((st_last_t[0] - 1, st_last_t[1]))
        c = _chg(st_last["supply"], sp_prev["supply"] if sp_prev else None)
        kpis["supply"] = {"value": round(st_last["supply"], 1),
                          "display": fmt.num_he(st_last["supply"], 1),
                          "tone": "brand" if c is None else "warn" if c > 0.05 else
                          "ok" if c < -0.05 else "brand"}
        labels["supply_kpi"] = "חודשי היצע: כמה חודשים יימכר המלאי בקצב הנוכחי"

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables = {}, {}
    charts["monthly"] = {
        "x": [_mshort(t) for t in mt],
        "second": [_r(months[t]["second"]["orig"]) for t in mt],
        "plain": [_r(new_plain(months[t])) for t in mt],
        "sub": [_r(months[t]["sub"]) for t in mt],
        "trend": [_r(months[t]["total"]["trend"]) for t in mt],
    }
    tables["monthly"] = [[_mname(t), _n(months[t]["total"]["orig"]),
                          _n(months[t]["second"]["orig"]) if months[t]["second"]["orig"] is not None else "",
                          _n(months[t]["new"]["orig"]) if months[t]["new"]["orig"] is not None else "",
                          _n(months[t]["sub"]) if months[t]["sub"] is not None else "",
                          _n(months[t]["total"]["trend"]) if months[t]["total"]["trend"] is not None else ""]
                         for t in reversed(mt)]

    if ytd:
        names = [("second", "יד שנייה"), ("plain", "חדשות ללא סבסוד"), ("sub", "חדשות בסבסוד ממשלתי"),
                 ("total", "סך הכל")]
        names = [(k, n) for k, n in names if ytd[k][0] is not None and ytd[k][1] is not None]
        charts["ytd"] = {"names": [n for _, n in names], "years": [str(lt[0] - 1), str(lt[0])],
                         "then": [round(ytd[k][1]) for k, _ in names],
                         "now": [round(ytd[k][0]) for k, _ in names]}
        tables["ytd"] = [[n, _n(ytd[k][1]), _n(ytd[k][0]),
                          fmt.signed_pct(_chg(ytd[k][0], ytd[k][1])) if ytd[k][1] else ""]
                         for k, n in names]
    years = t1["years"]
    tables["years"] = [[str(y), _n(years[y]["total"]["orig"]),
                        _n(years[y]["second"]["orig"]) if years[y]["second"]["orig"] is not None else "",
                        _n(years[y]["new"]["orig"]) if years[y]["new"]["orig"] is not None else "",
                        _n(years[y]["sub"]) if years[y]["sub"] is not None else ""]
                       for y in sorted(years)]

    tt = sorted(trend)
    charts["trend"] = {"x": [f"{t[0]}-{t[1]:02d}" for t in tt],
                       "total": [_r(trend[t]["total"]) for t in tt],
                       "new": [_r(trend[t]["new"]) for t in tt],
                       "second": [_r(trend[t]["second"]) for t in tt]}
    tables["trend"] = []
    for y in sorted({t[0] for t in tt}):
        recs = [trend[t] for t in tt if t[0] == y]
        avg = {k: sum(r[k] for r in recs if r[k] is not None) / max(1, sum(r[k] is not None for r in recs))
               for k in ("total", "new", "second")}
        tables["trend"].append([str(y), _n(avg["total"]), _n(avg["new"]), _n(avg["second"]),
                                str(len(recs))])

    # subsidy share of new dwellings, by year (from monthly rows)
    sub_years = []
    for y in sorted({t[0] for t in mt}):
        recs = [months[t] for t in mt if t[0] == y]
        s, n = _sum(recs, lambda r: r["sub"]), _sum(recs, lambda r: r["new"]["orig"])
        if s is not None and n:
            sub_years.append((y, s, n, len(recs)))
    charts["sub"] = {"x": [_mshort(t) for t in mt],
                     "sub": [_r(months[t]["sub"]) for t in mt],
                     "share": [round(months[t]["sub"] / months[t]["new"]["orig"] * 100, 1)
                               if months[t]["sub"] is not None and months[t]["new"]["orig"] else None
                               for t in mt]}
    tables["sub"] = [[str(y), _n(s), _n(n), fmt.pct(s / n), str(k)] for y, s, n, k in sub_years]

    sk = sorted(stock_series)
    supply_by = {t: r["supply"] for t, r in t2.items() if r["supply"] is not None}
    charts["stock"] = {"x": [f"{t[0]}-{t[1]:02d}" for t in sk],
                       "stock": [_r(stock_series[t]) for t in sk],
                       "supply": [supply_by.get(t) for t in sk]}
    tables["stock"] = []
    for y in sorted({t[0] for t in sk}):
        end = max(t for t in sk if t[0] == y)
        tables["stock"].append([_mname(end), _n(stock_series[end]),
                                fmt.num_he(supply_by[end], 1) if end in supply_by else ""])

    districts = sorted(((_district_name(n), v) for n, v in districts), key=lambda d: (-d[1], d[0]))
    d_sum = sum(v for _, v in districts)
    charts["district"] = {"names": [n for n, _ in districts], "values": [round(v) for _, v in districts]}
    tables["district"] = [[n, _n(v), fmt.pct(v / d_sum) if d_sum else ""] for n, v in districts]

    cities = sorted(((n.replace(" -", "-").strip(), v) for n, v in cities), key=lambda d: (-d[1], d[0]))
    charts["cities"] = {"names": [n for n, _ in cities], "values": [round(v) for _, v in cities]}
    tables["cities"] = [[n, _n(v)] for n, v in cities]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    sec, new, sub = last["second"]["orig"], last["new"]["orig"], last["sub"]
    if sec is not None and new is not None:
        add("latest", f"ב{_mname(lt)} נמכרו {_n(last['total']['orig'])} דירות: {_n(sec)} דירות יד שנייה "
                      f"ו-{_n(new)} דירות חדשות"
                      + (f", מהן {_n(sub)} בסבסוד ממשלתי" if sub else "")
                      + (f". זו {_word(yoy)} של {fmt.pct(abs(yoy))} לעומת {_mname(ly)}" if yoy else "")
                      + ".")
    tr6 = (lt[0] - (1 if lt[1] <= 6 else 0), (lt[1] - 6 - 1) % 12 + 1)
    a, b = last["total"]["trend"], months.get(tr6, {}).get("total", {}).get("trend")
    if a and b:
        c = a / b - 1
        state = ("עולה" if c > 0.02 else "יורד" if c < -0.02 else "יציב")
        add("trend", f"לפי נתוני המגמה (בניכוי עונתיות ותנודות מקריות), קצב המכירות {state}: "
                     f"{_n(a)} דירות בחודש ב{_mname(lt)}, לעומת {_n(b)} ב{_mname(tr6)}"
                     + (f" ({fmt.signed_pct(c)})" if state != "יציב" else "") + ".")
    if ytd and ytd["total"][1]:
        c = _chg(*ytd["total"])
        span = (f"ינואר עד {fmt.MONTHS_HE[lt[1] - 1]}" if lt[1] > 1 else "ינואר")
        nc = _chg(*ytd["new"]) if ytd["new"][1] else None
        sc = _chg(*ytd["second"]) if ytd["second"][1] else None
        add("ytd", f"מתחילת {lt[0]} ({span}) נמכרו {_n(ytd['total'][0])} דירות, "
                   f"{fmt.pct(abs(c))} {_more(c)} מאשר באותם חודשים ב-{lt[0] - 1}"
                   + (f" (דירות חדשות: {fmt.signed_pct(nc)}, יד שנייה: {fmt.signed_pct(sc)})"
                      if nc is not None and sc is not None else "") + ".")
    if ytd and ytd["new"][0] and ytd["new"][1] and ytd["sub"][0] is not None and ytd["sub"][1] is not None:
        s_now, s_then = ytd["sub"][0] / ytd["new"][0], ytd["sub"][1] / ytd["new"][1]
        if abs(s_now - s_then) >= 0.02:
            add("sub", f"דירות בסבסוד ממשלתי הן {fmt.pct(s_now)} מהדירות החדשות שנמכרו מתחילת {lt[0]}, "
                       f"לעומת {fmt.pct(s_then)} באותם חודשים ב-{lt[0] - 1}.")
    if tt and len(tt) >= 60:
        peak = max(tt, key=lambda t: (trend[t]["total"], t))
        cur = trend[tt[-1]]["total"]
        if peak != tt[-1] and cur < trend[peak]["total"] * 0.9:
            add("peak", f"קצב המכירות (מגמה) נמוך ב-{fmt.pct(1 - cur / trend[peak]['total'])} מהשיא של "
                        f"{_mname(peak)}, אז נמכרו כ-{_n(trend[peak]['total'])} דירות בחודש.")
    if st_last and st_last["orig"] is not None:
        st_prev = t2.get((st_last_t[0] - 1, st_last_t[1]))
        c = _chg(st_last["orig"], st_prev["orig"] if st_prev else None)
        add("stock", f"בסוף {_mname(st_last_t)} נותרו למכירה {_n(st_last['orig'])} דירות חדשות"
                     + (f", {_word(c)} של {fmt.pct(abs(c))} בשנה" if c is not None and abs(c) >= 0.005 else "")
                     + (f". בקצב המכירות הנוכחי יידרשו כ-{fmt.num_he(st_last['supply'], 1)} חודשים כדי למכור את כולן"
                        if st_last["supply"] is not None else "") + ".")
    if len(districts) >= 3 and d_sum:
        (n1, v1), (n2, v2) = districts[0], districts[1]
        add("district", f"רוב המלאי מרוכז במרכז הארץ: {_dl(n1)} ({fmt.pct(v1 / d_sum)}) ו{_dl(n2)} "
                        f"({fmt.pct(v2 / d_sum)}) מחזיקים יחד {fmt.pct((v1 + v2) / d_sum)} מהדירות "
                        f"החדשות שנותרו למכירה." if (v1 + v2) / d_sum > 0.5 and
                        {n1, n2} <= {"תל אביב", "המרכז"} else
                        f"{_dl(n1)} מחזיק את המלאי הגדול ביותר של דירות חדשות שנותרו למכירה: "
                        f"{_n(v1)} דירות, {fmt.pct(v1 / d_sum)} מהמלאי.")
    if len(cities) >= 2:
        (c1, v1), (c2, v2) = cities[0], cities[1]
        add("cities", f"בין הערים הגדולות, הכי הרבה דירות חדשות למכירה יש ב{c1} ({_n(v1)}) "
                      f"וב{c2} ({_n(v2)}).")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"כמה דירות נמכרות בישראל בכל חודש, כמה מהן חדשות וכמה יד שנייה, כמה נמכרו "
                 f"בסבסוד ממשלתי (כמו מחיר למשתכן), וכמה דירות חדשות עדיין מחכות לקונים. הנתונים "
                 f"מתוך ההודעה החודשית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה "
                 f"חדשה. הנתון האחרון הוא ל{_mname(lt)}: {_n(last['total']['orig'])} דירות שנמכרו."),
        "monthly_note": (f"מספר הדירות שנמכרו בכל חודש מאז {_mname(mt[0])} (נתונים מקוריים), לפי "
                         f"סוג הדירה, והקו הוא נתוני המגמה של סך המכירות."),
        "monthly_aria": f"דירות שנמכרו לפי חודש וסוג, {_mname(mt[0])} עד {_mname(lt)}",
        "monthly_caption": "דירות שנמכרו לפי חודש",
        "years_caption": "דירות שנמכרו בשנים מלאות",
        "trend_note": (f"נתוני המגמה של מספר הדירות שנמכרו בחודש מאז {_mname(tt[0])}: סך הכל, "
                       f"דירות חדשות ודירות יד שנייה. אפשר לגרור כדי להתמקד בתקופה."),
        "trend_aria": f"מגמת מכירות הדירות, {_mname(tt[0])} עד {_mname(tt[-1])}",
        "trend_caption": "מגמת המכירות, ממוצע חודשי לפי שנה",
        "sub_note": ("כמה דירות חדשות נמכרו בכל חודש במסגרת תוכניות דיור בסבסוד ממשלתי, ואיזה "
                     "חלק הן מכלל הדירות החדשות שנמכרו באותו חודש."),
        "sub_aria": f"דירות בסבסוד ממשלתי לפי חודש, {_mname(mt[0])} עד {_mname(lt)}",
        "sub_caption": "דירות בסבסוד ממשלתי לפי שנה",
        "district_note": (f"דירות חדשות שנותרו למכירה בסוף החודש האחרון בנתונים, לפי מחוז, "
                          f"מתוך {_n(d_sum)} דירות."),
        "district_aria": "דירות חדשות שנותרו למכירה לפי מחוז",
        "district_caption": "דירות חדשות שנותרו למכירה לפי מחוז",
        "cities_note": "דירות חדשות שנותרו למכירה בערים המונות יותר ממאה אלף תושבים.",
        "cities_aria": "דירות חדשות שנותרו למכירה בערים הגדולות",
        "cities_caption": "דירות חדשות שנותרו למכירה לפי עיר",
    })
    if ytd:
        labels.update({
            "ytd_note": (f"סך הדירות שנמכרו מינואר עד {fmt.MONTHS_HE[lt[1] - 1]}, {lt[0]} מול "
                         f"אותם חודשים ב-{lt[0] - 1}, לפי סוג הדירה."),
            "ytd_aria": f"דירות שנמכרו מתחילת השנה, {lt[0]} מול {lt[0] - 1}",
            "ytd_caption": f"דירות שנמכרו מינואר עד {fmt.MONTHS_HE[lt[1] - 1]}",
            "ytd_then": str(lt[0] - 1), "ytd_now": str(lt[0]),
        })
    if sk:
        labels.update({
            "stock_note": (f"מספר הדירות החדשות שנותרו למכירה בסוף כל חודש (נתוני מגמה) מאז "
                           f"{_mname(sk[0])}, וחודשי ההיצע: כמה חודשים יידרשו למכור את כולן "
                           f"בקצב המכירות של אותו חודש."),
            "stock_aria": f"דירות חדשות שנותרו למכירה, {_mname(sk[0])} עד {_mname(sk[-1])}",
            "stock_caption": "דירות חדשות שנותרו למכירה בסוף כל שנה",
        })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"מספר הדירות שנמכרו בישראל בכל חודש, חדשות ויד שנייה, ומלאי הדירות החדשות "
               f"שנותרו למכירה, מנתוני הלמ\"ס. ב{_mname(lt)} נמכרו {_n(last['total']['orig'])} דירות"
               + (f" ({fmt.signed_pct(yoy)} בשנה)" if yoy is not None else "") + ".")
    desc = (f"כמה דירות נמכרו החודש: {_n(last['total']['orig'])} ב{_mname(lt)}"
            + (f", {fmt.signed_pct(yoy)} בשנה" if yoy is not None else "")
            + (f". {_n(st_last['orig'])} דירות חדשות למכירה" if st_last and st_last["orig"] is not None
               else "") + ", לפי מחוז ועיר.")
    first_year = min([t[0] for t in tt] + [mt[0][0]])
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_year}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "עסקאות נדל\"ן: כמה דירות נמכרו החודש | הלמ\"ס",
                "description": desc,
                "name": "דירות שנמכרו בעסקאות נדל\"ן",
                "alternate_names": ["דירות בעסקאות נדל\"ן", "מספר עסקאות הנדל\"ן בישראל",
                                    "מכירות דירות חדשות", "דירות חדשות שנותרו למכירה",
                                    "מכירות דירות בסבסוד ממשלתי"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"ytd": bool(ytd), "years": bool(years), "stock": len(sk) >= 2,
                  "sub": bool(sub_years)},
    }
