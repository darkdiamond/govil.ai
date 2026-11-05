"""התחלות וגמר בנייה: CBS's quarterly construction release (chapter 04).

Each edition covers a rolling 12 months (the March edition is the calendar
year). Inputs are CBS grid tables from the newest edition:
  t1  dwellings by stage (permits, begun, completed: original / SA / trend;
      under active construction at period end), yearly and quarterly
  t2  dwellings by district and stage, yearly and quarterly
  t3  dwellings in new buildings by storeys and dwellings per building
  t4  dwellings begun by purpose (for sale / subsidized / not for sale) and
      district, for the last three rolling 12-month windows, plus quarters
  t5  dwellings begun after demolition (urban renewal) and dwellings added
      to existing buildings, same layout as t4
  t6  average construction months of completed buildings, by building area
  t7  construction area (thousand sq. m.) by purpose and stage
  t8..t14  the release's chart-data sheets. Their order moves between
      editions, so the not-for-sale-by-purpose sheet is found by its title.
  releases  the edition list (number, date, title, link)

Header labels are looked up by text (govlib.cbs) and raise when missing.
Period rows are found by content: a year, a quarter ("1-3", or "3-1" on the
Hebrew side) or a window ("7 2025 - 6 2026"), read from the cells outside a
table's data columns. A missing data row only shortens a series. Sections
that sit low in a sheet (completed, active) are optional.
"""
import re

import pandas as pd
from govlib import cbs, fmt

QUARTERS = {"1-3": 1, "4-6": 2, "7-9": 3, "10-12": 4,
            "3-1": 1, "6-4": 2, "9-7": 3, "12-10": 4}
WINDOW = re.compile(r"^(\d{1,2})\s*(\d{4})\s*-\s*(\d{1,2})\s*(\d{4})$")
HEB = re.compile(r"[א-ת]")
# Section headers: the English label, or the Hebrew one (an edition printed
# some sections with the Hebrew label only).
STAGES = {"permits": ("CONSTRUCTION PERMITS", "היתרי בנייה"),
          "begun": ("CONSTRUCTION BEGUN", "התחלת בנייה"),
          "completed": ("CONSTRUCTION COMPLETED", "גמר בנייה"),
          "active": ("UNDER ACTIVE CONSTRUCTION", "בבנייה פעילה")}
STAGE_HE = {"permits": "היתרי בנייה", "begun": "התחלות בנייה", "completed": "גמר בנייה"}
CHART_TABLES = ("t8", "t9", "t10", "t11", "t12", "t13", "t14")


# ── generic grid helpers ─────────────────────────────────────────────────


def _labels(r, lo, hi):
    """The non-empty cells of a row outside the data columns lo..hi."""
    return [c for j, c in enumerate(r) if (j < lo or j > hi) and c]


def _period(cells):
    """(year, quarter, window) found in label cells; window = (start, end)
    as ((year, month), (year, month)). The rightmost window label wins
    (an edition once carried a stale copy on the English side)."""
    year = quarter = window = None
    for c in cells:
        if year is None and cbs.YEAR.match(c):
            year = int(c)
        if quarter is None and c in QUARTERS:
            quarter = QUARTERS[c]
        m = WINDOW.match(c)
        if m:
            window = ((int(m.group(2)), int(m.group(1))), (int(m.group(4)), int(m.group(3))))
    return year, quarter, window


def _timeline(rows, start, stop, lo, hi):
    """[(row index, year, quarter or None)] for the year and quarter rows
    in rows[start:stop]; a year carries down to the quarter rows below."""
    out, year = [], None
    for i in range(start, stop):
        y, q, w = _period(_labels(rows[i], lo, hi))
        if w is not None:
            continue
        if y is not None:
            year = y
        if q is not None and year is not None:
            out.append((i, year, q))
        elif y is not None:
            out.append((i, y, None))
    return out


def _sections(rows, marks, name, required=()):
    """{key: (start, stop)} for the section header rows of a sheet. A
    required section that is missing raises; others are left out."""
    starts = {}
    for k, alts in marks.items():
        found = []
        for label in (alts if isinstance(alts, tuple) else (alts,)):
            try:
                found.append(cbs.row_with(rows, label, name=name, contains=True))
            except ValueError:
                pass
        if found:
            starts[k] = min(found)
        elif k in required:
            raise ValueError(f"{name}: section {alts!r} not found")
    order = sorted(starts.items(), key=lambda kv: kv[1])
    return {k: (s, order[n + 1][1] if n + 1 < len(order) else len(rows))
            for n, (k, s) in enumerate(order)}


def _district(cells):
    """Canonical Hebrew district name from a row's or column's labels, or
    "total" for a total row, or None."""
    heb = [c for c in cells if HEB.search(c)]
    if not heb:
        return None
    name = re.sub(r"[\d()]", "", heb[-1]).replace("מחוז ", "").strip()
    if name.startswith(("סך", "סה")):
        return "total"
    if "יהודה" in name:
        return "יהודה ושומרון"
    return name or None


# ── tables ───────────────────────────────────────────────────────────────


def _t1(rows):
    """{stage: {"q": {(y, q): {orig, sa, trend}}, "y": {y: orig}}} for
    permits / begun / completed / active."""
    g = cbs.row_with(rows, "Construction begun", name="t1", contains=True)
    grp = {"active": cbs.col_after(rows[g], "Under active construction", 0, contains=True),
           "completed": cbs.col_after(rows[g], "Construction completed", 0, contains=True),
           "begun": cbs.col_after(rows[g], "Construction begun", 0, contains=True),
           "permits": cbs.col_after(rows[g], "Construction permits", 0, contains=True)}
    h = cbs.row_with(rows, "Original", g, name="t1")
    order = sorted(grp, key=grp.get)
    cols = {}
    for n, k in enumerate(order):
        lo = grp[k]
        hi = grp[order[n + 1]] if n + 1 < len(order) else len(rows[h])
        c = {"orig": cbs.col_after(rows[h], "Original", lo)}
        if k != "active":
            c["trend"] = cbs.col_after(rows[h], "Trend", lo)
            c["sa"] = cbs.col_after(rows[h], "Seasonally", lo)
        if any(j >= hi for j in c.values()):
            raise ValueError(f"t1: {k} columns out of their group")
        cols[k] = c
    lo = min(grp.values())
    hi = max(j for c in cols.values() for j in c.values())
    out = {k: {"q": {}, "y": {}} for k in cols}
    for i, y, q in _timeline(rows, h + 1, len(rows), lo, hi):
        for k, c in cols.items():
            v = {m: cbs.val(rows[i], j) for m, j in c.items()}
            if v["orig"] is None:
                continue
            if q is None:
                out[k]["y"][y] = v["orig"]
            else:
                out[k]["q"][(y, q)] = v
    return out


def _t2(rows):
    """District columns by stage: {stage: {(y, q): {district: v}}} plus
    the district order of the sheet."""
    eng = cbs.row_with(rows, "Jerusalem", name="t2")
    heb = cbs.row_with(rows, "ירושלים", name="t2")
    total = cbs.col_after(rows[eng], "Total", 0, contains=True)
    dcols = {}
    for j, c in enumerate(rows[eng]):
        if not c or "Total" in c or c.startswith("Dwellings") or c == "District":
            continue
        name = _district([cbs.cell(rows[heb], j)])
        if name and name != "total":
            dcols[name] = j
    if len(dcols) < 3:
        raise ValueError("t2: district columns not found")
    cols = dict(dcols, total=total)
    lo, hi = min(cols.values()), max(cols.values())
    secs = _sections(rows, STAGES, "t2", required=("begun",))
    out = {}
    for k, (s, e) in secs.items():
        q, y = {}, {}
        for i, yr, qt in _timeline(rows, s + 1, e, lo, hi):
            v = {d: cbs.val(rows[i], j) for d, j in cols.items()}
            if v["total"] is None:
                continue
            (y.__setitem__(yr, v) if qt is None else q.__setitem__((yr, qt), v))
        out[k] = {"q": q, "y": y}
    return out, list(dcols)


def _windows(rows, cols, name):
    """t4 / t5 layout: rolling-window blocks of district rows, then a
    quarter section. Returns ({window: {district: {measure: v}}},
    {(y, q): {measure: v}}, {y: {measure: v}})."""
    lo, hi = min(cols.values()), max(cols.values())
    try:
        qsec = cbs.row_with(rows, "Quarter", name=name)
    except ValueError:
        qsec = len(rows)
    wins, cur = {}, None
    for i in range(qsec):
        cells = _labels(rows[i], lo, hi)
        _, _, w = _period(cells)
        if w is not None:
            cur = w
            wins[cur] = {}
        if cur is None:
            continue
        d = _district([c for c in cells if not WINDOW.match(c)])
        v = {k: cbs.val(rows[i], j) for k, j in cols.items()}
        if d and any(x is not None for x in v.values()):
            wins[cur][d] = v
    quarters, years = {}, {}
    for i, y, q in _timeline(rows, qsec + 1, len(rows), lo, hi):
        v = {k: cbs.val(rows[i], j) for k, j in cols.items()}
        if all(x is None for x in v.values()):
            continue
        (years.__setitem__(y, v) if q is None else quarters.__setitem__((y, q), v))
    return wins, quarters, years


def _t4(rows):
    h = cbs.row_with(rows, "מזה: בהשכרה", name="t4")
    g = cbs.row_with(rows, "Dwellings built for sale", name="t4", contains=True)
    nfs0 = cbs.col_after(rows[g], "Dwellings built not for sale", 0, contains=True)
    sale0 = cbs.col_after(rows[g], "Dwellings built for sale", 0, contains=True)
    cols = {"comb": cbs.col_after(rows[h], "קומבינציה", nfs0, contains=True),
            "rent": cbs.col_after(rows[h], "בהשכרה", nfs0, contains=True),
            "nfs": cbs.col_after(rows[h], "סך הכל", nfs0),
            "subs": cbs.col_after(rows[h], "בסבסוד ממשלתי", sale0, contains=True),
            "sale": cbs.col_after(rows[h], "סך הכל", sale0)}
    if not cols["subs"] < cols["sale"]:
        raise ValueError("t4: for-sale columns out of order")
    return _windows(rows, cols, "t4")


def _t5(rows):
    h = cbs.row_with(rows, "פינוי בינוי", name="t5", contains=True)
    d = cbs.row_with(rows, "שנהרסו", name="t5", contains=True)
    tama = cbs.col_after(rows[h], "תמ\"א", 0, contains=True)
    renew = cbs.col_after(rows[h], "פינוי בינוי", 0, contains=True)
    cols = {"destroyed": cbs.col_after(rows[d], "שנהרסו", 0, contains=True),
            "tama38": tama, "added": cbs.col_after(rows[h], "סך הכל", tama),
            "renewal": renew, "rebuilt": cbs.col_after(rows[h], "סך הכל", renew)}
    return _windows(rows, cols, "t5")


def _t3(rows):
    """Dwellings begun in new buildings by storeys: ({y: [..]}, {(y,q): [..]},
    labels). Values follow the label order (low to high)."""
    s = cbs.row_with(rows, "Storeys in building", name="t3", contains=True)
    s0 = cbs.col_after(rows[s], "Storeys in building", 0, contains=True)
    lr = cbs.row_with(rows, "Total", s + 1, name="t3", contains=True)
    total = cbs.col_after(rows[lr], "Total", 0, contains=True)
    scols = [j for j in range(s0, total) if rows[lr][j]]
    if len(scols) < 2:
        raise ValueError("t3: storey columns not found")
    scols.reverse()  # the sheet runs high to low
    labels = [rows[lr][j] for j in scols]
    lo = min(cbs.col_after(rows[s], "Dwellings in building", 0, contains=True), s0)
    secs = _sections(rows, STAGES, "t3", required=("begun",))
    out = {}
    for k, (a, b) in secs.items():
        ys, qs = {}, {}
        for i, y, q in _timeline(rows, a + 1, b, lo, total):
            v = [cbs.val(rows[i], j) for j in scols]
            t = cbs.val(rows[i], total)
            if t is None or any(x is None for x in v):
                continue
            (ys.__setitem__(y, (v, t)) if q is None else qs.__setitem__((y, q), (v, t)))
        out[k] = (ys, qs)
    return out, labels


def _area_label(a, b):
    a = a.replace(",", "")
    if a.endswith("-") and b:
        lo = cbs.num(a[:-1])
        hi = cbs.num(b)
        if lo is not None and hi is not None:
            return f"{fmt.int_he(lo)}-{fmt.int_he(hi)}"
    if a.endswith("+"):
        n = cbs.num(a[:-1])
        return f"{fmt.int_he(n)}+" if n is not None else a
    return a


def _t6(rows):
    """Construction months: ({y: total}, {(y,q): total}, {area: months of
    the latest year}, kind) with kind "weighted" or "simple"."""
    a = cbs.row_with(rows, "Building area", name="t6", contains=True)
    a0 = cbs.col_after(rows[a], "Building area", 0, contains=True)
    tr = cbs.row_with(rows, "Total", a + 1, name="t6")
    total = cbs.col_after(rows[tr], "Total", 0)
    acols = [j for j in range(a0, total) if rows[a + 1][j] or rows[tr][j]]
    secs = _sections(rows, {"simple": "Simple average", "weighted": "Weighted average"},
                     "t6", required=("simple",))
    kind = "weighted" if "weighted" in secs else "simple"
    s, e = secs[kind]
    ys, qs, by_area = {}, {}, {}
    for i, y, q in _timeline(rows, s + 1, e, a0, total):
        t = cbs.val(rows[i], total)
        if t is None:
            continue
        if q is None:
            ys[y] = t
            by_area[y] = [(_area_label(cbs.cell(rows[a + 1], j), cbs.cell(rows[tr], j)),
                           cbs.val(rows[i], j)) for j in acols]
        else:
            qs[(y, q)] = t
    return ys, qs, by_area, kind


def _t7(rows):
    """Non-residential construction area by purpose: {stage: {(y,q): {purpose:
    v}}} and the residential / non-residential totals."""
    e = cbs.row_with(rows, "Offices", name="t7")
    h = cbs.row_with(rows, "משרדים", name="t7")
    nonres = cbs.col_after(rows[e], "Non-", 0, contains=True)
    res = cbs.col_after(rows[e], "Resi", 0, contains=True)
    pcols = {}
    for j in range(nonres):
        name = cbs.cell(rows[h], j)
        if name and HEB.search(name) and cbs.cell(rows[e], j):
            pcols[name] = j
    if len(pcols) < 3:
        raise ValueError("t7: purpose columns not found")
    cols = dict(pcols, __nonres=nonres, __res=res)
    # The English header row spans every data column, the total included.
    filled = [j for j, c in enumerate(rows[e]) if c]
    lo, hi = min(filled), max(filled)
    secs = _sections(rows, STAGES, "t7", required=("begun",))
    out = {}
    for k, (s, stop) in secs.items():
        qs = {}
        for i, y, q in _timeline(rows, s + 1, stop, lo, hi):
            if q is None:
                continue
            v = {p: cbs.val(rows[i], j) for p, j in cols.items()}
            if v["__nonres"] is not None:
                qs[(y, q)] = v
        out[k] = qs
    return out, list(pcols)


def _nfs(frames):
    """The chart sheet "dwellings not for sale, by purpose and district",
    wherever it sits this edition: ({district: {purpose: v}}, purposes,
    title) or None."""
    for name in CHART_TABLES:
        df = frames.get(name)
        if df is None or df.empty:
            continue
        rows = cbs.grid(df, name)
        if not any("שאינן למכירה" in c for r in rows[:8] for c in r):
            continue
        title = next(c for r in rows[:8] for c in r if "שאינן למכירה" in c)
        h = cbs.row_with(rows, "מחוז", name=name)
        pcols = {}
        for j, c in enumerate(rows[h]):
            if j and c and HEB.search(c):
                pcols[c.replace("קומבינצייה", "קומבינציה")] = j
        out = {}
        for r in rows[h + 1:]:
            d = _district([cbs.cell(r, 0)])
            v = {p: cbs.val(r, j) for p, j in pcols.items()}
            if d and d != "total" and all(x is not None for x in v.values()):
                out[d] = v
        if out and pcols:
            return out, list(pcols), title
    return None


# ── formatting ───────────────────────────────────────────────────────────


def _n(v):
    return fmt.int_he(v)


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _word(c):
    return "עלייה" if c > 0 else "ירידה"


def _qlabel(t):
    return f"{t[1]}/{t[0]}"


def _qname(t):
    return f"רבעון {t[1]} {t[0]}"


def _qend(t):
    return f"{fmt.MONTHS_HE[t[1] * 3 - 1]} {t[0]}"


def _span(first, last):
    """Window text from its first and last quarter: "יולי 2025 עד יוני 2026"."""
    return f"{fmt.MONTHS_HE[first[1] * 3 - 3]} {first[0]} עד {_qend(last)}"


def _prev(t, n=1):
    y, q = t
    k = y * 4 + (q - 1) - n
    return (k // 4, k % 4 + 1)


def _sum(series, keys, f=lambda v: v):
    vals = [f(series[k]) for k in keys if k in series]
    if len(vals) != len(keys) or any(v is None for v in vals):
        return None
    return sum(vals)


def _tone(c, band=0.02):
    if c is None:
        return "brand"
    return "ok" if c > band else "danger" if c < -band else "warn"


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    t1 = _t1(cbs.grid(frames["t1"], "t1"))
    begun_q = t1["begun"]["q"]
    if len(begun_q) < 8:
        raise ValueError("t1: fewer than eight quarters of construction begun")
    qs = sorted(begun_q)
    last = qs[-1]
    win = [_prev(last, n) for n in range(3, -1, -1)]
    pwin = [_prev(t, 4) for t in win]
    win_text = _span(win[0], win[-1])

    def roll(stage, keys):
        return _sum(t1[stage]["q"], keys, lambda v: v["orig"]) if stage in t1 else None

    starts, starts_p = roll("begun", win), roll("begun", pwin)
    if starts is None:
        raise ValueError("t1: the latest four quarters of construction begun are incomplete")
    comp, comp_p = roll("completed", win), roll("completed", pwin)
    perm, perm_p = roll("permits", win), roll("permits", pwin)
    active_q = t1.get("active", {}).get("q", {})
    active = active_q.get(last, {}).get("orig")
    active_p = active_q.get(_prev(last, 4), {}).get("orig")

    t2, districts = _t2(cbs.grid(frames["t2"], "t2"))
    wins4, _, _ = _t4(cbs.grid(frames["t4"], "t4"))
    wins5, _, _ = _t5(cbs.grid(frames["t5"], "t5"))
    t3, storey_labels = _t3(cbs.grid(frames["t3"], "t3"))
    dur_y, dur_q, dur_area, dur_kind = _t6(cbs.grid(frames["t6"], "t6"))
    t7, purposes = _t7(cbs.grid(frames["t7"], "t7"))
    nfs = _nfs(frames)

    kpis, labels, charts, tables = {}, {}, {}, {}
    flags = dict.fromkeys(("active", "district", "district_active", "purpose", "nfs", "renewal",
                           "storeys", "duration", "by_area", "area"), False)
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── KPIs ─────────────────────────────────────────────────────────────
    sc = _chg(starts, starts_p)
    kpis["starts"] = {"value": round(starts), "display": _n(starts), "tone": _tone(sc)}
    labels["starts_kpi"] = f"דירות שהחלה בנייתן, {win_text}"
    if sc is not None:
        kpis["starts_chg"] = {"value": round(sc, 4), "display": fmt.signed_pct(sc),
                              "tone": _tone(sc)}
        labels["starts_chg_kpi"] = "התחלות בנייה לעומת 12 החודשים הקודמים"
    if comp is not None:
        cc = _chg(comp, comp_p)
        kpis["completed"] = {"value": round(comp), "display": _n(comp), "tone": _tone(cc)}
        labels["completed_kpi"] = "דירות שבנייתן הסתיימה ב-12 החודשים"
    if active is not None:
        kpis["active"] = {"value": round(active), "display": _n(active), "tone": "info"}
        labels["active_kpi"] = f"דירות בבנייה פעילה, סוף {_qend(last)}"
    if perm is not None:
        kpis["permits"] = {"value": round(perm), "display": _n(perm),
                           "tone": _tone(_chg(perm, perm_p))}
        labels["permits_kpi"] = "דירות בהיתרי בנייה ב-12 החודשים"
    dy = sorted(dur_y)
    if dy:
        dc = dur_y[dy[-1]] - dur_y[dy[-2]] if len(dy) >= 2 else None
        kpis["duration"] = {"value": dur_y[dy[-1]], "display": fmt.num_he(dur_y[dy[-1]], 1),
                            "tone": "brand" if dc is None else "warn" if dc > 0.5
                            else "ok" if dc < -0.5 else "brand"}
        labels["duration_kpi"] = f"חודשי בנייה בממוצע לבניין שהושלם ב-{dy[-1]}"

    # ── quarterly series (t1) ────────────────────────────────────────────
    qx = sorted(set(begun_q) | set(t1.get("completed", {}).get("q", {})))

    def series(stage, m):
        s = t1.get(stage, {}).get("q", {})
        return [round(s[t][m]) if t in s and s[t].get(m) is not None else None for t in qx]

    charts["quarterly"] = {"x": [_qlabel(t) for t in qx],
                           "begun": series("begun", "sa"), "completed": series("completed", "sa"),
                           "permits": series("permits", "sa"),
                           "begun_trend": series("begun", "trend"),
                           "completed_trend": series("completed", "trend")}
    years = sorted(t1["begun"]["y"])
    tables["annual"] = [[str(y)] + [_n(t1[k]["y"][y]) if k in t1 and y in t1[k]["y"] else "–"
                                    for k in ("permits", "begun", "completed", "active")]
                        for y in reversed(years)]
    labels["quarterly_note"] = (
        f"כמה דירות קיבלו היתר, כמה התחילו להיבנות וכמה הסתיימו בכל רבעון מאז "
        f"{_qname(qx[0])}, בנתונים מנוכי עונתיות. הקווים המקווקווים הם קו המגמה. "
        f"בטבלה: הסיכום השנתי, ומלאי הדירות בבנייה בסוף כל שנה.")
    labels["quarterly_aria"] = f"היתרים, התחלות וגמר בנייה לפי רבעון, {_qlabel(qx[0])} עד {_qlabel(qx[-1])}"

    if len(active_q) >= 4:
        ax = sorted(active_q)
        charts["active"] = {"x": [_qlabel(t) for t in ax],
                            "y": [round(active_q[t]["orig"]) for t in ax]}
        tables["active"] = [[_qname(t), _n(active_q[t]["orig"]),
                             fmt.signed_pct(c) if (c := _chg(active_q[t]["orig"],
                                                             active_q.get(_prev(t, 4), {}).get("orig")))
                             is not None else "–"]
                            for t in reversed(ax[-8:])]
        peak = max(ax, key=lambda t: (active_q[t]["orig"], t))
        labels["active_note"] = (
            f"מספר הדירות שנמצאות בבנייה פעילה בסוף כל רבעון: דירות שבנייתן התחילה ועוד "
            f"לא הסתיימה (לא כולל בנייה שהופסקה). השיא בתקופה: {_n(active_q[peak]['orig'])} "
            f"דירות, ב{_qname(peak)}.")
        labels["active_aria"] = f"דירות בבנייה פעילה בסוף כל רבעון, {_qlabel(ax[0])} עד {_qlabel(ax[-1])}"
        flags["active"] = True
        first = ax[0]
        c = _chg(active, active_q[first]["orig"]) if active else None
        if active and active_p and c is not None:
            ca = _chg(active, active_p)
            add("active", f"בסוף {_qend(last)} היו {_n(active)} דירות בבנייה פעילה, "
                          f"{_word(ca)} של {fmt.pct(abs(ca))} בשנה"
                          + (" והמספר הגבוה ביותר בנתונים" if peak == last else "")
                          + f". מאז {_qname(first)} {'גדל' if c > 0 else 'קטן'} המלאי ב-{fmt.pct(abs(c))}.")

    # ── districts (t2) ───────────────────────────────────────────────────
    def droll(stage, keys):
        q = t2.get(stage, {}).get("q", {})
        if not all(k in q for k in keys):
            return None
        return {d: sum(q[k][d] or 0 for k in keys) for d in districts + ["total"]}

    # The district window is t2's own latest four quarters (t1's, in a whole
    # edition); a t2 with fewer leaves the district sections out.
    b2 = sorted(t2.get("begun", {}).get("q", {}))
    dlast = b2[-1] if b2 else last
    dwin = [_prev(dlast, n) for n in range(3, -1, -1)]
    dwin_text = _span(dwin[0], dwin[-1])
    d_now = {k: droll(k, dwin) for k in ("permits", "begun", "completed")}
    d_prev = droll("begun", [_prev(t, 4) for t in dwin])
    if d_now["begun"] is not None:
        flags["district"] = True
        dorder = sorted(districts, key=lambda d: (-d_now["begun"][d], d))
    else:
        dorder = list(districts)
    if flags.get("district"):
        stages = [k for k in ("permits", "begun", "completed") if d_now[k] is not None]
        charts["district"] = {"names": dorder, "stages": [STAGE_HE[k] for k in stages],
                              "series": [[round(d_now[k][d]) for d in dorder] for k in stages]}
        tables["district"] = []
        for d in dorder:
            c = _chg(d_now["begun"][d], d_prev[d]) if d_prev else None
            tables["district"].append([d] + [_n(d_now[k][d]) for k in stages]
                                      + [fmt.signed_pct(c) if c is not None else "–"])
        labels["district_cols"] = (["מחוז"] + [STAGE_HE[k] for k in stages]
                                   + ["התחלות: שינוי בשנה"])
        labels["district_note"] = (f"דירות לפי מחוז ושלב בנייה, ב-12 החודשים {dwin_text}. "
                                   f"המחוזות מסודרים לפי מספר התחלות הבנייה.")
        labels["district_aria"] = f"היתרים, התחלות וגמר בנייה לפי מחוז, {dwin_text}"
        tot = d_now["begun"]["total"] or sum(d_now["begun"][d] for d in districts)
        top = dorder[0]
        add("district_top", f"מחוז {top} מוביל בהתחלות הבנייה: {_n(d_now['begun'][top])} דירות ב-12 "
                            f"החודשים, {fmt.pct(d_now['begun'][top] / tot)} מכלל הדירות שהחלה "
                            f"בנייתן." if tot and d_now["begun"][top] / tot >= 0.2 else None)
        if d_prev:
            moves = [(d, _chg(d_now["begun"][d], d_prev[d])) for d in districts
                     if d_prev[d] and d_prev[d] >= 1000]
            moves = [m for m in moves if m[1] is not None and abs(m[1]) >= 0.15]
            if moves:
                d, c = max(moves, key=lambda m: (abs(m[1]), m[0]))
                add("district_move", f"השינוי החד ביותר במחוז {d}: {_n(d_now['begun'][d])} דירות "
                                     f"החלו להיבנות, {_word(c)} של {fmt.pct(abs(c))} לעומת "
                                     f"{_n(d_prev[d])} ב-12 החודשים הקודמים.")

    act_q = t2.get("active", {}).get("q", {})
    if dlast in act_q and _prev(dlast, 4) in act_q:
        a1, a0 = act_q[dlast], act_q[_prev(dlast, 4)]
        aorder = sorted(districts, key=lambda d: (-(a1[d] or 0), d))
        charts["district_active"] = {"names": aorder, "now": [round(a1[d] or 0) for d in aorder],
                                     "prev": [round(a0[d] or 0) for d in aorder],
                                     "now_label": _qend(dlast),
                                     "prev_label": _qend(_prev(dlast, 4))}
        tables["district_active"] = [[d, _n(a1[d] or 0), _n(a0[d] or 0),
                                      fmt.signed_pct(c) if (c := _chg(a1[d], a0[d])) is not None
                                      else "–"] for d in aorder]
        labels["district_active_cols"] = ["מחוז", _qend(dlast), _qend(_prev(dlast, 4)), "שינוי"]
        labels["district_active_note"] = (
            f"כמה דירות היו בבנייה פעילה בכל מחוז בסוף {_qend(dlast)}, לעומת שנה קודם לכן.")
        labels["district_active_aria"] = f"דירות בבנייה פעילה לפי מחוז, {_qend(dlast)} מול {_qend(_prev(dlast, 4))}"
        flags["district_active"] = True

    # ── purpose (t4) ─────────────────────────────────────────────────────
    if wins4:
        w = max(wins4, key=lambda k: k[1])
        rows4 = wins4[w]
        dlist = [d for d in dorder if d in rows4] + sorted(d for d in rows4
                                                            if d not in dorder and d != "total")
        if dlist and "total" in rows4:
            def z(v):
                return v or 0
            charts["purpose"] = {"names": dlist,
                                 "market": [round(z(rows4[d]["sale"]) - z(rows4[d]["subs"]))
                                            for d in dlist],
                                 "subs": [round(z(rows4[d]["subs"])) for d in dlist],
                                 "nfs": [round(z(rows4[d]["nfs"])) for d in dlist]}
            tables["purpose"] = [[d, _n(z(rows4[d]["sale"])), _n(z(rows4[d]["subs"])),
                                  _n(z(rows4[d]["nfs"])), _n(z(rows4[d]["rent"])),
                                  _n(z(rows4[d]["comb"]))] for d in dlist]
            T = rows4["total"]
            tables["purpose"].append(["סך הכל", _n(z(T["sale"])), _n(z(T["subs"])), _n(z(T["nfs"])),
                                      _n(z(T["rent"])), _n(z(T["comb"]))])
            wt = _span((w[0][0], (w[0][1] + 2) // 3), (w[1][0], (w[1][1] + 2) // 3))
            labels["purpose_note"] = (
                f"דירות שהחלה בנייתן ב-12 החודשים {wt}, לפי מטרת הבנייה: למכירה בשוק "
                f"החופשי, למכירה בסבסוד ממשלתי (כמו דירה בהנחה), ולא למכירה (בנייה עצמית, "
                f"השכרה, קומבינציה ועוד).")
            labels["purpose_aria"] = f"התחלות בנייה לפי מטרה ומחוז, {wt}"
            flags["purpose"] = True
            allt = z(T["sale"]) + z(T["nfs"])
            if allt and T["subs"]:
                share = T["subs"] / z(T["sale"]) if T["sale"] else None
                prevw = [k for k in wins4 if k[1] == (w[1][0] - 1, w[1][1])]
                ps = None
                if prevw and "total" in wins4[prevw[0]]:
                    P = wins4[prevw[0]]["total"]
                    ps = P["subs"] / P["sale"] if P.get("sale") and P.get("subs") else None
                if share:
                    add("subsidized", f"{fmt.pct(share)} מהדירות שהחלו להיבנות למכירה "
                                      f"({_n(T['subs'])} מתוך {_n(T['sale'])}) נבנות בסבסוד "
                                      f"ממשלתי"
                                      + (f", לעומת {fmt.pct(ps)} ב-12 החודשים שקדמו להם"
                                         if ps and abs(share - ps) >= 0.02 else "") + ".")
            if allt and T["nfs"]:
                add("not_for_sale", f"{fmt.pct(T['nfs'] / allt)} מהדירות שהחלו להיבנות אינן "
                                    f"מיועדות למכירה: {_n(T['nfs'])} דירות, מהן {_n(z(T['rent']))} "
                                    f"להשכרה ו-{_n(z(T['comb']))} בעסקאות קומבינציה."
                    if T["nfs"] / allt >= 0.2 else None)

    # ── not for sale by purpose (chart sheet) ───────────────────────────
    if nfs:
        nd, npur, _title = nfs
        nlist = [d for d in dorder if d in nd] + sorted(d for d in nd if d not in dorder)
        charts["nfs"] = {"names": nlist, "purposes": npur,
                         "series": [[round(nd[d][p]) for d in nlist] for p in npur]}
        tables["nfs"] = [[d] + [_n(nd[d][p]) for p in npur] for d in nlist]
        labels["nfs_cols"] = ["מחוז"] + npur
        labels["nfs_note"] = ("הדירות שאינן נבנות למכירה, לפי מחוז ומטרה. בנייה עצמית היא "
                              "בעיקר בתים צמודי קרקע ביישובים כפריים; קומבינציה היא עסקה שבה "
                              "בעל הקרקע מקבל דירות בבניין במקום תשלום.")
        labels["nfs_aria"] = "דירות שלא למכירה לפי מטרה ומחוז"
        flags["nfs"] = True
        totals = {p: sum(nd[d][p] for d in nlist) for p in npur}
        topp = max(npur, key=lambda p: (totals[p], p))
        allnfs = sum(totals.values())
        if allnfs:
            lead = {p: max(nlist, key=lambda d: (nd[d][p], d)) for p in npur}
            add("nfs_mix", f"מבין הדירות שלא למכירה, הקבוצה הגדולה היא {topp} "
                           f"({fmt.pct(totals[topp] / allnfs)}), והיא מרוכזת בעיקר במחוז "
                           f"{lead[topp]}.")

    # ── urban renewal (t5) ───────────────────────────────────────────────
    if wins5:
        w = max(wins5, key=lambda k: k[1])
        rows5 = wins5[w]
        rlist = [d for d in dorder if d in rows5]
        if rlist and "total" in rows5:
            T = rows5["total"]
            rorder = sorted(rlist, key=lambda d: (-((rows5[d]["rebuilt"] or 0)
                                                    + (rows5[d]["added"] or 0)), d))
            charts["renewal"] = {"names": rorder,
                                 "rebuilt": [round(rows5[d]["rebuilt"] or 0) for d in rorder],
                                 "added": [round(rows5[d]["added"] or 0) for d in rorder],
                                 "destroyed": [round(rows5[d]["destroyed"] or 0) for d in rorder]}
            tables["renewal"] = [[d, _n(rows5[d]["rebuilt"] or 0), _n(rows5[d]["renewal"] or 0),
                                  _n(rows5[d]["added"] or 0), _n(rows5[d]["tama38"] or 0),
                                  _n(rows5[d]["destroyed"] or 0)] for d in rorder]
            tables["renewal"].append(["סך הכל", _n(T["rebuilt"] or 0), _n(T["renewal"] or 0),
                                      _n(T["added"] or 0), _n(T["tama38"] or 0),
                                      _n(T["destroyed"] or 0)])
            wt = _span((w[0][0], (w[0][1] + 2) // 3), (w[1][0], (w[1][1] + 2) // 3))
            labels["renewal_note"] = (
                f"התחדשות עירונית ב-12 החודשים {wt}: דירות שהחלו להיבנות בבניין חדש במקום "
                f"בניין שנהרס (כולל פינוי בינוי ותמ\"א 38/2), דירות שנוספו לבניינים קיימים "
                f"(בעיקר תמ\"א 38), ומספר הדירות שנהרסו כדי לפנות להן מקום.")
            labels["renewal_aria"] = f"דירות בהתחדשות עירונית לפי מחוז, {wt}"
            flags["renewal"] = True
            ren = (T["rebuilt"] or 0) + (T["added"] or 0)
            wstarts = (wins4.get(w, {}).get("total") or {}) if wins4 else {}
            base = (wstarts.get("sale") or 0) + (wstarts.get("nfs") or 0)
            if ren and base:
                lead = rorder[0]
                lshare = ((rows5[lead]["rebuilt"] or 0) + (rows5[lead]["added"] or 0)) / ren
                add("renewal", f"{_n(ren)} מהדירות שהחלו להיבנות ({fmt.pct(ren / base)}) הן "
                               f"התחדשות עירונית: בניין חדש במקום ישן או תוספת לבניין קיים. "
                               f"{fmt.pct(lshare)} מהן במחוז {lead}.")
            if T["rebuilt"] and T["destroyed"]:
                labels["renewal_ratio"] = (f"על כל דירה שנהרסה נבנות בממוצע "
                                           f"{fmt.num_he(T['rebuilt'] / T['destroyed'], 1)} דירות "
                                           f"בבניין החדש.")

    # ── storeys (t3) ─────────────────────────────────────────────────────
    sy = t3.get("begun", ({}, {}))[0]
    syears = sorted(sy)
    if len(syears) >= 2:
        charts["storeys"] = {"x": [str(y) for y in syears], "labels": storey_labels,
                             "series": [[round(sy[y][0][k] / sy[y][1] * 100, 1) if sy[y][1] else 0
                                         for y in syears] for k in range(len(storey_labels))]}
        tables["storeys"] = [[str(y)] + [_n(v) for v in sy[y][0]] + [_n(sy[y][1])]
                             for y in reversed(syears)]
        labels["storeys_cols"] = ["שנה"] + [f"{s} קומות" for s in storey_labels] + ["סך הכל"]
        labels["storey_names"] = [f"{s} קומות" for s in storey_labels]
        labels["storeys_note"] = ("איך מתחלקות הדירות שהחלו להיבנות בבניינים חדשים לפי גובה "
                                  "הבניין, באחוזים מכל שנה. בטבלה: מספרי הדירות.")
        labels["storeys_aria"] = f"התחלות בנייה לפי מספר קומות בבניין, {syears[0]} עד {syears[-1]}"
        flags["storeys"] = True
        hi0, hi1 = charts["storeys"]["series"][-1][0], charts["storeys"]["series"][-1][-1]
        if abs(hi1 - hi0) >= 3:
            add("highrise", f"{fmt.pct_of(hi1)} מהדירות שהחלו להיבנות ב-{syears[-1]} הן בבניינים "
                            f"של {storey_labels[-1]} קומות, לעומת {fmt.pct_of(hi0)} ב-{syears[0]}.")

    # ── construction time (t6) ───────────────────────────────────────────
    if dur_q:
        dx = sorted(dur_q)
        charts["duration"] = {"x": [_qlabel(t) for t in dx], "y": [dur_q[t] for t in dx]}
        tables["duration"] = [[str(y), fmt.num_he(dur_y[y], 1)] for y in reversed(dy)]
        kind_he = ("ממוצע משוקלל לפי מספר הדירות" if dur_kind == "weighted"
                   else "ממוצע פשוט לבניין")
        labels["duration_note"] = (
            f"כמה חודשים נמשכה הבנייה של בניין מגורים, מהתחלה ועד גמר, לפי הרבעון שבו "
            f"הסתיימה ({kind_he}). לא כולל בתים של דירה או שתיים שלא למכירה.")
        labels["duration_aria"] = f"משך בנייה ממוצע בחודשים, {_qlabel(dx[0])} עד {_qlabel(dx[-1])}"
        flags["duration"] = True
        if len(dy) >= 3:
            c = dur_y[dy[-1]] - dur_y[dy[0]]
            if abs(c) >= 1:
                add("duration", f"משך הבנייה {'התארך' if c > 0 else 'התקצר'}: בניין שבנייתו הסתיימה "
                                f"ב-{dy[-1]} נבנה בממוצע {fmt.num_he(dur_y[dy[-1]], 1)} חודשים, "
                                f"לעומת {fmt.num_he(dur_y[dy[0]], 1)} ב-{dy[0]}.")
    if dy and dur_area.get(dy[-1]):
        ar = [(lab, v) for lab, v in dur_area[dy[-1]] if v is not None]
        if len(ar) >= 3:
            ar.reverse()  # the sheet runs large to small
            charts["by_area"] = {"names": [a for a, _ in ar], "y": [v for _, v in ar]}
            tables["by_area"] = [[a, fmt.num_he(v, 1)] for a, v in ar]
            labels["by_area_note"] = (f"משך הבנייה הממוצע (בחודשים) של בניינים שבנייתם הסתיימה "
                                      f"ב-{dy[-1]}, לפי שטח הבניין במ\"ר: ככל שהבניין גדול "
                                      f"יותר, הבנייה ארוכה יותר.")
            labels["by_area_aria"] = f"משך בנייה ממוצע לפי שטח הבניין, {dy[-1]}"
            flags["by_area"] = True

    # ── non-residential area (t7) ────────────────────────────────────────
    a_now = {}
    for k in ("begun", "completed"):
        q = t7.get(k, {})
        if all(t in q for t in win):
            a_now[k] = {p: sum(q[t][p] or 0 for t in win) for p in purposes + ["__nonres", "__res"]}
    if "begun" in a_now:
        porder = sorted(purposes, key=lambda p: (-a_now["begun"][p], p))
        akeys = [k for k in ("begun", "completed") if k in a_now]
        charts["area"] = {"names": porder, "stages": [STAGE_HE[k] for k in akeys],
                          "series": [[round(a_now[k][p]) for p in porder] for k in akeys]}
        tables["area"] = [[p] + [_n(a_now[k][p]) for k in akeys] for p in porder]
        tables["area"].append(["סך הכל שלא למגורים"] + [_n(a_now[k]["__nonres"]) for k in akeys])
        tables["area"].append(["מגורים"] + [_n(a_now[k]["__res"]) for k in akeys])
        labels["area_cols"] = ["ייעוד"] + [f"{STAGE_HE[k]} (אלפי מ\"ר)" for k in akeys]
        labels["area_note"] = (f"שטח הבנייה שלא למגורים לפי ייעוד, באלפי מ\"ר, ב-12 החודשים "
                               f"{win_text}.")
        labels["area_aria"] = f"שטח בנייה שלא למגורים לפי ייעוד, {win_text}"
        flags["area"] = True
        B = a_now["begun"]
        tot_area = B["__nonres"] + B["__res"]
        if tot_area:
            add("area", f"ב-12 החודשים החלה בנייה של {fmt.num_he(tot_area / 1000, 1)} מיליון מ\"ר, "
                        f"{fmt.pct(B['__res'] / tot_area)} מהם למגורים. מבין השימושים האחרים "
                        f"הגדול ביותר הוא {porder[0]} ({_n(B[porder[0]])} אלף מ\"ר).")

    # ── headline insights ────────────────────────────────────────────────
    if sc is not None:
        insights.insert(0, {"id": "starts", "text_he": (
            f"ב-12 החודשים {win_text} החלה בנייתן של {_n(starts)} דירות, {_word(sc)} של "
            f"{fmt.pct(abs(sc))} לעומת {_n(starts_p)} ב-12 החודשים שקדמו להם.")})
    if comp and starts:
        ratio = starts / comp
        cc = _chg(comp, comp_p)
        text = (f"בנייתן של {_n(comp)} דירות הסתיימה ב-12 החודשים"
                + (f" ({_word(cc)} של {fmt.pct(abs(cc))} בשנה)" if cc is not None
                   and abs(cc) >= 0.02 else "") + ". ")
        if ratio >= 1.1:
            text += (f"על כל דירה שהושלמה התחילו לבנות {fmt.num_he(ratio, 2)} דירות, ולכן "
                     f"מלאי הדירות בבנייה גדל.")
        elif ratio <= 0.9:
            text += "הושלמו יותר דירות משהתחילו לבנות, ולכן מלאי הדירות בבנייה קטן."
        elif cc is None or abs(cc) < 0.02:
            text = None
        if text:
            insights.insert(1, {"id": "gap", "text_he": text})

    # ── text ─────────────────────────────────────────────────────────────
    labels["lede"] = (
        f"כמה דירות מתחילים לבנות בישראל, כמה מסיימים, וכמה נמצאות כרגע בבנייה, לפי רבעון "
        f"ומחוז. הנתונים מתוך ההודעה הרבעונית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על "
        f"התחלות וגמר בנייה, ומתעדכנים עם כל הודעה חדשה. ב-12 החודשים {win_text} החלה "
        f"בנייתן של {_n(starts)} דירות"
        + (f" והסתיימה בנייתן של {_n(comp)}" if comp is not None else "") + ".")
    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "url": latest_rel["PAGE_URL"], "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"התחלות בנייה, גמר בנייה ודירות בבנייה פעילה בישראל, לפי רבעון ומחוז, מנתוני "
               f"הלמ\"ס. ב-12 החודשים {win_text}: {_n(starts)} דירות החלו להיבנות"
               + (f" ({fmt.signed_pct(sc)} בשנה)" if sc is not None else "") + ".")
    desc = (f"כמה דירות התחילו לבנות: {_n(starts)} ב-12 החודשים עד {_qend(last)}"
            + (f", {fmt.signed_pct(sc)} בשנה" if sc is not None else "")
            + ". גמר בנייה, דירות בבנייה ומחוזות.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{qx[0][0]}/{last[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "התחלות וגמר בנייה: דירות לפי רבעון ומחוז | הלמ\"ס",
                "description": desc,
                "name": "התחלות וגמר בנייה של דירות",
                "alternate_names": ["התחלות בנייה", "גמר בנייה", "דירות בבנייה פעילה",
                                    "התחלות בניה למגורים", "היתרי בנייה לדירות"],
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
