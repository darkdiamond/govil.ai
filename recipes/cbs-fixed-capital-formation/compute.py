"""השקעה גולמית מקומית בנכסים קבועים בענפי המשק: CBS's yearly release.

The release's Excel tables are found by their TITLE text, never by stem
(CBS renumbers tables between editions; t1..t17 are all optional inputs):

  main   לוח: השקעה ... בנכסים קבועים, לפי ענף כלכלי   by industry and asset (required)
  infra  לוח: השקעה ... בתשתיות                      infrastructure by sector
  gov    לוח: ... של המגזר הממשלתי                    general government
  mach   לוח: השקעה במכונות ובציוד ... ענף היעוד והמקור  machinery, domestic vs imported
  mfg    לוח: השקעות ענף התעשייה במכונות ובציוד מיבוא   by technology intensity
  ict    לוח: ... טכנולוגיות המידע (ICT)              ICT investment by industry

The "תרשים" sheets are chart data derived from these tables and are not read.

Each table has a current-prices block and a chained-prices block (NIS
million). Real growth and the implicit price change are computed here from
those two blocks (chained ratio = CBS's quantity change), so the page does
not depend on the percent-change blocks lower in each sheet.

The main table's multi-row header is a print layout whose labels do not sit
over their data columns. Industries are found by label, each industry's
total by the "סך"/"סך הכל" sub-header after its label, and its machinery and
construction columns by the accounting identity machinery + construction =
total. The sum of all parts must equal the grand total, or compute raises.
"""
import re

import pandas as pd
from govlib import cbs, fmt

HEB = re.compile("[א-ת]")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
TRAIL_NOTE = re.compile(r"\s+\d$")

# Industry labels in the main table's header (contains-match) → display name.
INDUSTRIES = (
    ("trade", "מסחר ושירותים", "מסחר ושירותים"),
    ("info", "מידע ותקשורת", "מידע ותקשורת"),
    ("transport", "תחבורה, אחסנה", "תחבורה ואחסנה"),
    ("elec", "חשמל", "חשמל ומים"),
    ("constr", "בינוי", "בינוי"),
    ("mfg", "תעשייה", "תעשייה וכרייה"),
    ("agri", "חקלאות", "חקלאות"),
)
ICT_NAMES = (("מסחר", "מסחר ושירותים"), ("מידע", "מידע ותקשורת"), ("תחבורה", "תחבורה ואחסנה"),
             ("חשמל", "חשמל, מים וביוב"), ("תעשייה", "תעשייה, כרייה וחציבה"))


# ── locating tables ──────────────────────────────────────────────────────


def _head_text(rows, n=8):
    return " ".join(c for r in rows[:n] for c in r if c)


def _kind(t):
    if "לוח" not in t:
        return None  # a "תרשים" chart-data sheet
    if "טכנולוגיות המידע" in t:
        return "ict"
    if "בתשתיות" in t:
        return "infra"
    if "המגזר הממשלתי" in t:
        return "gov"
    if "מיבוא" in t and "התעשייה" in t:
        return "mfg"
    if "במכונות ובציוד" in t:
        return "mach"
    if "בנכסים קבועים" in t and "ענף כלכלי" in t:
        return "main"
    return None


def _tables(frames):
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+[a-z]?", n)),
                   key=lambda n: (int(re.sub(r"\D", "", n)), n))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        k = _kind(_head_text(rows))
        if k and k not in out:
            out[k] = (n, rows)
    return out


# ── blocks ───────────────────────────────────────────────────────────────


def _blocks(rows, start, name):
    """{'cur': {year: row}, 'chn': {year: row}, 'base': '2020'} from the
    current-prices and chained-prices blocks after row `start`."""
    i_cur = cbs.row_with(rows, "שוטפים", start, name, contains=True)
    i_chn = cbs.row_with(rows, "משורשרים", i_cur + 1, name, contains=True)
    base = next((m.group(0) for c in rows[i_chn] for m in [YEAR_IN.search(c)] if m), None)
    if base is None:
        raise ValueError(f"{name}: chained base year not found")
    stops = [i for i in range(i_chn + 1, len(rows))
             if any("כמותי" in c or "מחירים נגזר" in c or "באחוזים" in c for c in rows[i])]
    end = stops[0] if stops else len(rows)
    return {"cur": _year_rows(rows, i_cur + 1, i_chn), "chn": _year_rows(rows, i_chn + 1, end),
            "base": base}


def _year_rows(rows, a, b):
    out = {}
    for r in rows[a:b]:
        y = cbs.cell(r, 0)
        if cbs.YEAR.match(y) and any(cbs.val(r, j) is not None for j in range(1, len(r))):
            out[int(y)] = r
    return out


def _labels_row(row):
    """{col: label} for the Hebrew labels in a header row (footnote digit off)."""
    return {j: TRAIL_NOTE.sub("", c) for j, c in enumerate(row) if c and HEB.search(c)}


# ── formatting ───────────────────────────────────────────────────────────


def _bn(v, d=1):
    return None if v is None else round(v / 1000, d)


def _bn_he(v, d=1):
    return fmt.num_he(v / 1000, d)


def _r1(v):
    return None if v is None else round(v, 1)


def _growth(chn, y):
    a, b = chn.get(y - 1), chn.get(y)
    if a is None or b is None or a <= 0:
        return None
    return b / a - 1


def _p_or_dash(f):
    return "–" if f is None else fmt.signed_pct(f)


# ── the main table ───────────────────────────────────────────────────────


def _main(rows, name):
    h = cbs.row_with(rows, "סך כולל", 0, name)
    top = rows[h]
    sub_i = next((i for i in range(h + 1, min(h + 8, len(rows)))
                  if sum(1 for c in rows[i] if c.startswith("מכונות")) >= 5), None)
    if sub_i is None:
        raise ValueError(f"{name}: machinery sub-header not found")
    sub = rows[sub_i]
    grand = cbs.col_after(top, "סך כולל")
    ip = cbs.col_after(top, "מוצרי", contains=True)
    ships = cbs.col_after(sub, "אניות", contains=True)
    land = cbs.col_after(sub, "יבשתיים", contains=True)
    lab = {k: cbs.col_after(top, needle, contains=True) for k, needle, _ in INDUSTRIES}
    totals = [j for j, c in enumerate(sub) if c in ("סך", "סך הכל") and j < grand]
    blocks = _blocks(rows, sub_i, name)
    cur, chn = blocks["cur"], blocks["chn"]
    if not cur:
        raise ValueError(f"{name}: no current-price rows")
    years = sorted(cur)
    ly = years[-1]

    cols = {}
    used = set()
    for k, _, _ in INDUSTRIES:
        if k == "constr":
            j = lab[k]
            if not sub[j].startswith("מכונות"):
                raise ValueError(f"{name}: construction industry column is not machinery")
            cols[k] = {"total": j, "mach": j, "cons": None}
            continue
        t = min((j for j in totals if j >= lab[k] and j not in used), default=None)
        if t is None:
            raise ValueError(f"{name}: total column for {k} not found")
        used.add(t)
        cand = [j for j in range(max(lab[k] - 1, land + 1), t)
                if j not in totals and j not in (ip, ships, land, lab["constr"])]
        pairs = []
        for ai, a in enumerate(cand):
            for b in cand[ai + 1:]:
                ok = True
                for y in years:
                    va, vb, vt = cbs.val(cur[y], a), cbs.val(cur[y], b), cbs.val(cur[y], t)
                    if va is None or vb is None or vt is None or abs(va + vb - vt) > 1:
                        ok = False
                        break
                if ok:
                    pairs.append((a, b))
        if len(pairs) != 1:
            raise ValueError(f"{name}: machinery/construction split for {k} is ambiguous")
        a, b = pairs[0]
        if not (sub[b].startswith("בנייה") or cbs.cell(sub, b - 1).startswith("בנייה")):
            raise ValueError(f"{name}: construction column for {k} has no label")
        cols[k] = {"total": t, "mach": a, "cons": b}

    def v(r, j):
        return cbs.val(r, j)

    # Identity: the parts add up to the grand total in the latest year.
    r = cur[ly]
    parts = v(r, ip) + v(r, ships) + v(r, land) + sum(v(r, c["total"]) for c in cols.values())
    if abs(parts - v(r, grand)) > 2:
        raise ValueError(f"{name}: parts ({parts:.0f}) do not add up to the grand total")

    def series(block, j):
        return {y: v(block[y], j) for y in sorted(block) if v(block[y], j) is not None}

    out = {"years": years, "ly": ly, "base": blocks["base"],
           "total_cur": series(cur, grand), "total_chn": series(chn, grand),
           "ip_cur": series(cur, ip), "ships_cur": series(cur, ships), "land_cur": series(cur, land),
           "ind": {}}
    for k, _, label in INDUSTRIES:
        c = cols[k]
        out["ind"][k] = {
            "name": label,
            "cur": series(cur, c["total"]), "chn": series(chn, c["total"]),
            "mach": series(cur, c["mach"]),
            "cons": series(cur, c["cons"]) if c["cons"] is not None else {},
        }
    return out


# ── other tables ─────────────────────────────────────────────────────────


def _labelled_table(rows, name):
    """Infrastructure / government: one header row with Hebrew labels ending
    in "סך כולל", then current and chained blocks."""
    h = cbs.row_with(rows, "סך כולל", 0, name)
    labels = _labels_row(rows[h])
    grand = cbs.col_after(rows[h], "סך כולל")
    blocks = _blocks(rows, h + 1, name)
    comps = [(j, labels[j]) for j in sorted(labels) if j != grand and j > 0]
    if not comps or not blocks["cur"]:
        raise ValueError(f"{name}: no components")
    return {"comps": comps, "grand": grand, **blocks}


def _mach(rows, name, main):
    """Machinery by destination industry: (domestic, import, total) triplets.
    The industry labels sit in one header row in the triplets' order (not
    over their columns), ending with "כלל הענפים"."""
    h = next((i for i, r in enumerate(rows) if sum(1 for c in r if c == "יצור") >= 4), None)
    if h is None:
        raise ValueError(f"{name}: domestic/import header not found")
    trip = []
    for j, c in enumerate(rows[h]):
        if c == "יצור":
            if cbs.cell(rows[h], j + 1) != "יבוא" or not cbs.cell(rows[h], j + 2).startswith("סך"):
                raise ValueError(f"{name}: triplet at column {j} is not domestic/import/total")
            trip.append(j)
    li = cbs.row_with(rows[:h], "כלל הענפים", 0, name, contains=True)
    names = [c for c in rows[li] if c and HEB.search(c)]
    if len(names) != len(trip):
        raise ValueError(f"{name}: {len(names)} industry labels for {len(trip)} triplets")
    keys = []
    for nm in names:
        k = "all" if "כלל הענפים" in nm else next((k for k, needle, _ in INDUSTRIES if needle in nm), None)
        if k is None or k in keys:
            raise ValueError(f"{name}: industry label {nm!r} not recognised")
        keys.append(k)
    if "all" not in keys:
        raise ValueError(f"{name}: all-industries column not found")
    blocks = _blocks(rows, h + 1, name)
    cur = blocks["cur"]
    if max(cur) != main["ly"]:
        return None
    return {k: {y: (cbs.val(r, j), cbs.val(r, j + 1), cbs.val(r, j + 2)) for y, r in sorted(cur.items())}
            for k, j in zip(keys, trip)}


def _mfg(rows, name):
    h = next((i for i, r in enumerate(rows) if sum(1 for c in r if cbs.YEAR.match(c)) >= 2), None)
    if h is None:
        raise ValueError(f"{name}: year header not found")
    vh = cbs.row_with(rows, "ש\"ח", h, name, contains=True)
    vcol = next(j for j, c in enumerate(rows[vh]) if "ש\"ח" in c)
    ycols = [(j, int(c)) for j, c in enumerate(rows[h]) if cbs.YEAR.match(c)]
    vyear = next((y for j, y in ycols if j == vcol), None)
    chg = [(j, y) for j, y in ycols if j != vcol]
    if vyear is None or not chg:
        raise ValueError(f"{name}: value/change columns not found")
    lcol = cbs.best_col(rows[vh + 1:], lambda c: bool(HEB.search(c)))
    items = []
    for r in rows[vh + 1:]:
        label = TRAIL_NOTE.sub("", cbs.cell(r, lcol))
        val = cbs.val(r, vcol)
        if not label or val is None:
            continue
        items.append({"label": label, "value": val, "chg": {y: cbs.val(r, j) for j, y in chg}})
    return {"year": vyear, "chg_years": [y for _, y in chg], "items": items}


def _ict(rows, name):
    h = cbs.row_with(rows, "סך כולל", 0, name)
    grand = cbs.col_after(rows[h], "סך כולל")
    stop = cbs.row_with(rows, "שוטפים", h, name, contains=True)
    parts = {}
    for r in rows[h + 1:stop]:
        for j, c in enumerate(r):
            if c and HEB.search(c) and 0 < j < grand:
                parts.setdefault(j, []).append(c)
    blocks = _blocks(rows, h + 1, name)
    comps = []
    for j in sorted(parts):
        full = " ".join(parts[j])
        short = next((s for needle, s in ICT_NAMES if needle in full), full)
        comps.append((j, short))
    if not comps:
        raise ValueError(f"{name}: no ICT industries")
    return {"comps": comps, "grand": grand, **blocks}


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    tabs = _tables(frames)
    if "main" not in tabs:
        raise ValueError("main table (investment by industry) not found")
    m = _main(tabs["main"][1], tabs["main"][0])
    rel = cbs.latest_release(frames["releases"])
    ly, years, base = m["ly"], m["years"], m["base"]
    y0 = years[0]
    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    tc, tq = m["total_cur"], m["total_chn"]
    g = {y: _growth(tq, y) for y in years}
    defl = {y: (tc[y] / tq[y]) for y in years if y in tc and tq.get(y)}
    pchg = {y: (defl[y] / defl[y - 1] - 1) if y - 1 in defl and y in defl else None for y in years}

    # ── KPIs ──
    kpis["total"] = {"value": round(tc[ly]), "display": _bn_he(tc[ly]), "tone": "brand"}
    labels["total_kpi"] = f"השקעה בנכסים קבועים בענפי המשק, {ly} (מיליארד ש\"ח, מחירים שוטפים)"
    gl = g.get(ly)
    if gl is not None:
        kpis["growth"] = {"value": round(gl * 100, 1), "display": fmt.signed_pct(gl),
                          "tone": "ok" if gl >= 0.02 else ("danger" if gl <= -0.02 else "warn")}
        labels["growth_kpi"] = f"שינוי ריאלי בהשקעה, {ly} לעומת {ly - 1}"
    ip_share = m["ip_cur"][ly] / tc[ly]
    kpis["ip"] = {"value": round(ip_share * 100, 1), "display": fmt.pct(ip_share), "tone": "info"}
    labels["ip_kpi"] = f"חלק מוצרי הקניין הרוחני (מו\"פ ותוכנה) מההשקעה, {ly}"

    # ── total over time ──
    charts["total"] = {"x": [str(y) for y in years], "chn": [_bn(tq.get(y)) for y in years],
                       "cur": [_bn(tc.get(y)) for y in years],
                       "g": [_r1(g[y] * 100) if g[y] is not None else None for y in years]}
    tables["total"] = [[str(y), _bn_he(tc[y]), _bn_he(tq[y]) if y in tq else "–", _p_or_dash(g[y]),
                        _p_or_dash(pchg[y])] for y in reversed(years)]
    labels["base"] = base
    labels["total_cols"] = ["שנה", "מחירים שוטפים", f"במחירי {base}", "שינוי ריאלי", "שינוי מחירים"]
    labels["total_note"] = (f"סך ההשקעה בנכסים קבועים בענפי המשק (ללא דיור) בכל שנה מאז {y0}, "
                            f"במיליארדי ש\"ח במחירי {base} (העמודות), והשינוי הריאלי לעומת השנה "
                            f"הקודמת (הקו).")
    labels["total_aria"] = f"השקעה בנכסים קבועים בענפי המשק, {y0} עד {ly}"
    gs = [(y, g[y]) for y in years if g[y] is not None]
    if gl is not None:
        rec = max(tq, key=lambda y: (tq[y], y))
        txt = (f"ב-{ly} הסתכמו ההשקעות בנכסים קבועים בענפי המשק ב-{_bn_he(tc[ly])} מיליארד ש\"ח, "
               f"{'עלייה' if gl > 0 else 'ירידה'} ריאלית של {fmt.pct(abs(gl))} לעומת {ly - 1}")
        if rec == ly:
            txt += f". זו הרמה הגבוהה ביותר במחירים קבועים מאז תחילת הסדרה ב-{min(tq)}"
        add("total", txt + ".")
    if len(gs) >= 5:
        lo = min(gs, key=lambda t: (t[1], t[0]))
        hi = max(gs, key=lambda t: (t[1], -t[0]))
        if lo[1] < 0:
            add("swing", f"הקפיצה הריאלית החדה ביותר בתקופה הייתה ב-{hi[0]} ({fmt.signed_pct(hi[1])}), "
                         f"והירידה החדה ביותר ב-{lo[0]} ({fmt.signed_pct(lo[1])}).")
    if y0 in tq and ly in tq and ly - y0 >= 5:
        cagr = (tq[ly] / tq[y0]) ** (1 / (ly - y0)) - 1
        labels["cagr"] = (f"מ-{y0} עד {ly} גדלה ההשקעה הריאלית פי {fmt.num_he(tq[ly] / tq[y0], 2)}, "
                          f"קצב ממוצע של {fmt.pct(cagr)} בשנה.")

    # ── asset mix ──
    mach_sum = {y: sum(d["mach"].get(y) or 0 for d in m["ind"].values()) for y in years}
    cons_sum = {y: sum(d["cons"].get(y) or 0 for d in m["ind"].values()) for y in years}
    trn = {y: (m["ships_cur"].get(y) or 0) + (m["land_cur"].get(y) or 0) for y in years}
    assets = [("ip", "מוצרי קניין רוחני", m["ip_cur"]), ("cons", "בנייה (לא למגורים)", cons_sum),
              ("mach", "מכונות וציוד", mach_sum), ("trn", "כלי תחבורה", trn)]
    charts["assets"] = {"x": [str(y) for y in years], "names": [a[1] for a in assets],
                        "series": [[_r1(s.get(y, 0) / tc[y] * 100) for y in years] for _, _, s in assets],
                        "bn": [[_bn(s.get(y, 0)) for y in years] for _, _, s in assets]}
    tables["assets"] = [[str(y)] + [f"{_bn_he(s.get(y, 0))} ({fmt.pct(s.get(y, 0) / tc[y])})"
                                    for _, _, s in assets] for y in reversed(years)]
    labels["assets_cols"] = ["שנה"] + [a[1] for a in assets]
    labels["assets_note"] = ("איך מתחלקת ההשקעה בין סוגי הנכסים: מחקר ופיתוח ותוכנה, מבנים ועבודות "
                             "בנייה, מכונות וציוד וכלי תחבורה. אחוזים מסך ההשקעה במחירים שוטפים; "
                             "בטבלה גם מיליארדי ש\"ח.")
    labels["assets_aria"] = f"השקעה לפי סוג נכס, {y0} עד {ly}"
    ip0 = m["ip_cur"][y0] / tc[y0]
    if ip_share - ip0 >= 0.03:
        add("ip", f"מוצרי הקניין הרוחני (מחקר ופיתוח, תוכנה וחיפושי גז ונפט) הם {fmt.pct(ip_share)} "
                  f"מההשקעה ב-{ly}, לעומת {fmt.pct(ip0)} ב-{y0}: {_bn_he(m['ip_cur'][ly])} מיליארד ש\"ח.")
    elif ip_share >= 0.25:
        add("ip", f"מוצרי הקניין הרוחני (מחקר ופיתוח, תוכנה וחיפושי גז ונפט) הם {fmt.pct(ip_share)} "
                  f"מההשקעה ב-{ly}: {_bn_he(m['ip_cur'][ly])} מיליארד ש\"ח.")

    # ── by industry, latest year ──
    ind = m["ind"]
    order = sorted(ind, key=lambda k: (-(ind[k]["cur"].get(ly) or 0), k))
    charts["industry"] = {"names": [ind[k]["name"] for k in order],
                          "mach": [_bn(ind[k]["mach"].get(ly), 2) for k in order],
                          "cons": [_bn(ind[k]["cons"].get(ly), 2) if ind[k]["cons"] else 0 for k in order]}
    ind_tot = sum(ind[k]["cur"].get(ly) or 0 for k in ind)
    tables["industry"] = [[ind[k]["name"], _bn_he(ind[k]["mach"].get(ly) or 0),
                           _bn_he(ind[k]["cons"].get(ly)) if ind[k]["cons"] else "–",
                           _bn_he(ind[k]["cur"][ly]), fmt.pct(ind[k]["cur"][ly] / ind_tot),
                           _p_or_dash(_growth(ind[k]["chn"], ly))] for k in order]
    labels["industry_cols"] = ["ענף", "מכונות וציוד", "בנייה", "סך הכל", "חלק", f"שינוי ריאלי ב-{ly}"]
    labels["industry_note"] = (f"ההשקעה בבנייה ובמכונות וציוד לפי הענף המשקיע ב-{ly}, במיליארדי ש\"ח "
                               f"(מחירים שוטפים). מוצרי הקניין הרוחני וכלי התחבורה לא מסווגים לענפים "
                               f"ואינם כלולים כאן: יחד {_bn_he(tc[ly] - ind_tot)} מיליארד ש\"ח.")
    labels["industry_aria"] = f"השקעה בבנייה ובציוד לפי ענף, {ly}"
    lead = order[0]
    lead_sh = ind[lead]["cur"][ly] / ind_tot
    if lead_sh >= 0.3:
        txt = (f"ענף {ind[lead]['name']} מוביל את ההשקעה בבנייה ובציוד: {_bn_he(ind[lead]['cur'][ly])} "
               f"מיליארד ש\"ח ב-{ly}, {fmt.pct(lead_sh)} מהסך")
        s0 = ind[lead]["cur"].get(y0)
        tot0 = sum(ind[k]["cur"].get(y0) or 0 for k in ind)
        if s0 and tot0 and abs(lead_sh - s0 / tot0) >= 0.03:
            txt += f", לעומת {fmt.pct(s0 / tot0)} ב-{y0}"
        add("lead", txt + ".")

    # ── industry real growth ──
    gi = {k: (_growth(ind[k]["chn"], ly - 1), _growth(ind[k]["chn"], ly)) for k in ind}
    gi = {k: v for k, v in gi.items() if v[1] is not None}
    flags["indgrowth"] = len(gi) >= 3
    if flags["indgrowth"]:
        gorder = sorted(gi, key=lambda k: (-gi[k][1], k))
        charts["indgrowth"] = {"names": [ind[k]["name"] for k in gorder],
                               "prev": [_r1(gi[k][0] * 100) if gi[k][0] is not None else None for k in gorder],
                               "last": [_r1(gi[k][1] * 100) for k in gorder],
                               "py": str(ly - 1), "ly": str(ly)}
        tables["indgrowth"] = [[ind[k]["name"], _p_or_dash(gi[k][0]), fmt.signed_pct(gi[k][1])] for k in gorder]
        labels["indgrowth_cols"] = ["ענף", str(ly - 1), str(ly)]
        labels["indgrowth_note"] = (f"השינוי הכמותי (במחירים קבועים) בהשקעה של כל ענף לעומת השנה "
                                    f"הקודמת, ב-{ly - 1} וב-{ly}.")
        labels["indgrowth_aria"] = f"שינוי ריאלי בהשקעה לפי ענף, {ly - 1} ו-{ly}"
        up = [k for k in gorder if gi[k][1] >= 0.1]
        dn = [k for k in gorder if gi[k][1] <= -0.03]
        if up:
            txt = (f"הזינוק הגדול ב-{ly} היה בענף {ind[gorder[0]]['name']}: {fmt.signed_pct(gi[gorder[0]][1])} "
                   f"במחירים קבועים")
            if dn:
                w = gorder[-1]
                txt += f". בענף {ind[w]['name']} ההשקעה ירדה ב-{fmt.pct(abs(gi[w][1]))}"
            add("indgrowth", txt + ".")

    # ── industry trends (chained) ──
    tyears = [y for y in years if y in tq]
    charts["trend"] = {"x": [str(y) for y in tyears], "names": [ind[k]["name"] for k in order],
                       "series": [[_bn(ind[k]["chn"].get(y), 2) for y in tyears] for k in order]}
    tables["trend"] = [[str(y)] + [_bn_he(ind[k]["chn"][y]) if y in ind[k]["chn"] else "–" for k in order]
                       for y in reversed(tyears)]
    labels["trend_cols"] = ["שנה"] + [ind[k]["name"] for k in order]
    labels["trend_note"] = (f"ההשקעה של כל ענף בבנייה ובציוד לאורך השנים, במיליארדי ש\"ח במחירי {base}. "
                            f"לחיצה על שם ענף במקרא מסתירה אותו.")
    labels["trend_aria"] = f"השקעה לפי ענף במחירים קבועים, {tyears[0]} עד {tyears[-1]}"

    # ── infrastructure ──
    flags["infra"] = False
    if "infra" in tabs:
        t = _labelled_table(tabs["infra"][1], tabs["infra"][0])
        cur, chn = t["cur"], t["chn"]
        iy = sorted(y for y in chn if y in cur)
        if len(iy) >= 3:
            flags["infra"] = True
            gcol = t["grand"]
            comps = sorted(t["comps"], key=lambda jc: (-(cbs.val(cur[iy[-1]], jc[0]) or 0), jc[1]))
            charts["infra"] = {"x": [str(y) for y in iy], "names": [c for _, c in comps],
                               "series": [[_bn(cbs.val(chn[y], j), 2) for y in iy] for j, _ in comps]}
            tables["infra"] = [[str(y)] + [_bn_he(cbs.val(cur[y], j) or 0) for j, _ in comps]
                               + [_bn_he(cbs.val(cur[y], gcol))] for y in reversed(iy)]
            labels["infra_cols"] = ["שנה"] + [c for _, c in comps] + ["סך הכל"]
            labels["infra_note"] = (f"השקעה בתשתיות תחבורה, אנרגיה, מים, תקשורת ופיתוח מראש, במיליארדי "
                                    f"ש\"ח במחירי {t['base']} (בגרף). בטבלה: מחירים שוטפים.")
            labels["infra_aria"] = f"השקעה בתשתיות לפי תחום, {iy[0]} עד {iy[-1]}"
            iq = {y: cbs.val(chn[y], gcol) for y in iy}
            il = iy[-1]
            kpis["infra"] = {"value": round(cbs.val(cur[il], gcol)), "display": _bn_he(cbs.val(cur[il], gcol)),
                             "tone": "brand"}
            labels["infra_kpi"] = f"השקעה בתשתיות, {il} (מיליארד ש\"ח)"
            ig = _growth(iq, il)
            topc = comps[0]
            tsh = (cbs.val(cur[il], topc[0]) or 0) / cbs.val(cur[il], gcol)
            if ig is not None:
                add("infra", f"ההשקעה בתשתיות הגיעה ל-{_bn_he(cbs.val(cur[il], gcol))} מיליארד ש\"ח ב-{il}, "
                             f"{'עלייה' if ig > 0 else 'ירידה'} ריאלית של {fmt.pct(abs(ig))}. "
                             f"תשתיות {topc[1]} הן {fmt.pct(tsh)} ממנה.")

    # ── general government ──
    flags["gov"] = False
    if "gov" in tabs:
        t = _labelled_table(tabs["gov"][1], tabs["gov"][0])
        cur, chn = t["cur"], t["chn"]
        gy = sorted(cur)
        if len(gy) >= 3:
            flags["gov"] = True
            gcol = t["grand"]
            comps = t["comps"]
            charts["gov"] = {"x": [str(y) for y in gy], "names": [c for _, c in comps],
                             "series": [[_bn(cbs.val(cur[y], j), 2) for y in gy] for j, _ in comps]}
            gq = {y: cbs.val(chn[y], gcol) for y in chn}
            tables["gov"] = [[str(y)] + [_bn_he(cbs.val(cur[y], j) or 0) for j, _ in comps]
                             + [_bn_he(cbs.val(cur[y], gcol)), _p_or_dash(_growth(gq, y))] for y in reversed(gy)]
            labels["gov_cols"] = ["שנה"] + [c for _, c in comps] + ["סך הכל", "שינוי ריאלי"]
            labels["gov_note"] = ("השקעת המגזר הממשלתי (הממשלה, הרשויות המקומיות והמוסדות הציבוריים) "
                                  "בנכסים קבועים, במיליארדי ש\"ח במחירים שוטפים.")
            labels["gov_aria"] = f"השקעת המגזר הממשלתי, {gy[0]} עד {gy[-1]}"
            gl2 = gy[-1]
            gg = _growth(gq, gl2)
            kpis["gov"] = {"value": round(cbs.val(cur[gl2], gcol)), "display": _bn_he(cbs.val(cur[gl2], gcol)),
                           "tone": "brand"}
            labels["gov_kpi"] = f"השקעת המגזר הממשלתי, {gl2} (מיליארד ש\"ח)"
            g5 = gl2 - 5
            if gg is not None and g5 in gq and gq[g5]:
                add("gov", f"המגזר הממשלתי השקיע {_bn_he(cbs.val(cur[gl2], gcol))} מיליארד ש\"ח ב-{gl2}: "
                           f"{'עלייה' if gg > 0 else 'ירידה'} ריאלית של {fmt.pct(abs(gg))} לעומת {gl2 - 1} "
                           f"ו-{fmt.pct(abs(gq[gl2] / gq[g5] - 1))} {'יותר' if gq[gl2] >= gq[g5] else 'פחות'} "
                           f"במחירים קבועים מאשר ב-{g5}.")

    # ── machinery: domestic vs imported ──
    flags["mach"] = False
    if "mach" in tabs:
        mc = _mach(tabs["mach"][1], tabs["mach"][0], m)
        if mc:
            flags["mach"] = True
            my = sorted(mc["all"])
            first, last = my[0], my[-1]

            def ish(k, y):
                d = mc[k].get(y)
                return d[1] / d[2] if d and d[1] is not None and d[2] else None

            keys = sorted((k for k in mc if k != "all"), key=lambda k: (-(ish(k, last) or 0), k))
            names = [ind[k]["name"] for k in keys] + ["כלל הענפים"]
            keys = keys + ["all"]
            charts["mach"] = {"names": names, "y0": str(first), "y1": str(last),
                              "a": [_r1(ish(k, first) * 100) if ish(k, first) is not None else None for k in keys],
                              "b": [_r1(ish(k, last) * 100) if ish(k, last) is not None else None for k in keys]}
            tables["mach"] = [[nm, _bn_he(mc[k][last][0] or 0), _bn_he(mc[k][last][1] or 0),
                               fmt.pct(ish(k, last)) if ish(k, last) is not None else "–",
                               fmt.pct(ish(k, first)) if ish(k, first) is not None else "–"]
                              for nm, k in zip(names, keys)]
            labels["mach_cols"] = ["ענף", "ייצור מקומי", "יבוא", f"חלק היבוא {last}", f"חלק היבוא {first}"]
            labels["mach_note"] = (f"איזה חלק מהמכונות והציוד שכל ענף השקיע בהם יובא מחו\"ל, {first} "
                                   f"לעומת {last}. בטבלה: מיליארדי ש\"ח ב-{last}, מחירים שוטפים.")
            labels["mach_aria"] = f"חלק היבוא בהשקעה במכונות ובציוד לפי ענף, {first} ו-{last}"
            a_last = ish("all", last)
            if a_last is not None and a_last >= 0.5:
                a_first = ish("all", first)
                tail = (f"שיעור דומה לזה של {first} ({fmt.pct(a_first)})" if abs(a_last - a_first) < 0.02
                        else f"לעומת {fmt.pct(a_first)} ב-{first}")
                add("mach", f"{fmt.pct(a_last)} מההשקעה במכונות ובציוד ב-{last} הייתה בציוד מיובא "
                            f"({_bn_he(mc['all'][last][1])} מיליארד ש\"ח), {tail}.")

    # ── manufacturing imported machinery by technology ──
    flags["mfg"] = False
    if "mfg" in tabs:
        mf = _mfg(tabs["mfg"][1], tabs["mfg"][0])
        groups = [it for it in mf["items"] if it["label"].startswith("ענפי טכנולוגיה")]
        total = next((it for it in mf["items"] if it["label"].startswith("סה\"כ")), None)
        if len(groups) >= 2 and total:
            flags["mfg"] = True
            cy = mf["chg_years"][-1]
            groups.sort(key=lambda it: (-it["value"], it["label"]))
            charts["mfg"] = {"names": [it["label"].replace("ענפי ", "") for it in groups],
                             "values": [_r1(it["value"]) for it in groups],
                             "chg": [_r1(it["chg"].get(cy)) for it in groups]}
            tables["mfg"] = [[it["label"], fmt.int_he(it["value"])]
                             + [fmt.signed_pct(it["chg"][y] / 100) if it["chg"].get(y) is not None else "–"
                                for y in mf["chg_years"]] for it in mf["items"]]
            labels["mfg_cols"] = ["ענף", f"מיליוני ש\"ח, {mf['year']}"] + [f"שינוי כמותי {y}"
                                                                           for y in mf["chg_years"]]
            labels["mfg_note"] = (f"השקעות ענף התעשייה במכונות ובציוד מיבוא ב-{mf['year']}, לפי עוצמה "
                                  f"טכנולוגית: מיליוני ש\"ח (העמודות) והשינוי הכמותי ב-{cy} (בתווית).")
            labels["mfg_aria"] = f"השקעת התעשייה במכונות מיבוא לפי עוצמה טכנולוגית, {mf['year']}"
            hi = groups[0]
            sh = hi["value"] / total["value"]
            if sh >= 0.3:
                txt = (f"{hi['label']} השקיעו {fmt.int_he(hi['value'])} מיליון ש\"ח "
                       f"במכונות ובציוד מיבוא ב-{mf['year']}, {fmt.pct(sh)} מהשקעת התעשייה כולה")
                c = hi["chg"].get(cy)
                if c is not None:
                    txt += f" (שינוי כמותי של {fmt.signed_pct(c / 100)})"
                add("mfg", txt + ".")

    # ── ICT ──
    flags["ict"] = False
    if "ict" in tabs:
        t = _ict(tabs["ict"][1], tabs["ict"][0])
        chn, cur = t["chn"], t["cur"]
        cy_ = sorted(chn)
        if len(cy_) >= 3:
            flags["ict"] = True
            gcol = t["grand"]
            comps = sorted(t["comps"], key=lambda jc: (-(cbs.val(chn[cy_[-1]], jc[0]) or 0), jc[1]))
            charts["ict"] = {"x": [str(y) for y in cy_], "names": [c for _, c in comps],
                             "series": [[_bn(cbs.val(chn[y], j), 2) for y in cy_] for j, _ in comps],
                             "total": [_bn(cbs.val(chn[y], gcol), 2) for y in cy_]}
            iq = {y: cbs.val(chn[y], gcol) for y in cy_}
            tables["ict"] = [[str(y), _bn_he(cbs.val(cur[y], gcol)) if y in cur else "–", _bn_he(iq[y]),
                              _p_or_dash(_growth(iq, y))] for y in reversed(cy_)]
            labels["ict_cols"] = ["שנה", "מחירים שוטפים", f"במחירי {t['base']}", "שינוי ריאלי"]
            labels["ict_note"] = (f"השקעה גולמית בענפי טכנולוגיות המידע והתקשורת (ICT), לא כולל תוכנה, "
                                  f"במיליארדי ש\"ח במחירי {t['base']}. הענפים בגרף הם חלק מהסך, לא כולו.")
            labels["ict_aria"] = f"השקעה בענפי ICT, {cy_[0]} עד {cy_[-1]}"
            a, b = cy_[0], cy_[-1]
            ratio = iq[b] / iq[a]
            ig = _growth(iq, b)
            if ratio >= 1.3 and ig is not None:
                add("ict", f"ההשקעה בענפי טכנולוגיות המידע והתקשורת גדלה פי {fmt.num_he(ratio, 1)} במחירים "
                           f"קבועים מ-{a} עד {b}, וב-{b} לבדה {fmt.signed_pct(ig)}.")

    # ── text ──
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["lede"] = (f"כמה משקיעים ענפי המשק בישראל במבנים, במכונות וציוד, בכלי תחבורה ובמחקר ופיתוח "
                      f"ותוכנה, ובאילו ענפים. הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה "
                      f"(הלמ\"ס) על ההשקעה הגולמית המקומית בנכסים קבועים, ללא השקעה בדיור, ומתעדכנים עם "
                      f"כל הודעה חדשה. ב-{ly}: {_bn_he(tc[ly])} מיליארד ש\"ח"
                      + (f", {'עלייה' if gl > 0 else 'ירידה'} ריאלית של {fmt.pct(abs(gl))}" if gl is not None else "")
                      + ".")
    summary = (f"השקעה גולמית בנכסים קבועים בענפי המשק לפי נתוני הלמ\"ס: {_bn_he(tc[ly])} מיליארד ש\"ח "
               f"ב-{ly}" + (f" ({fmt.signed_pct(gl)} ריאלית)" if gl is not None else "")
               + f", מהם {fmt.pct(ip_share)} במחקר ופיתוח ותוכנה. פילוח לפי ענף, סוג נכס, תשתיות ו-ICT.")
    desc = (f"השקעות בענפי המשק בישראל לפי ענף וסוג נכס: {_bn_he(tc[ly])} מיליארד ש\"ח ב-{ly}"
            + (f", {fmt.signed_pct(gl)} ריאלית" if gl is not None else "")
            + ". תשתיות, מכונות וציוד, מו\"פ ותוכנה.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{y0}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "השקעות בנכסים קבועים בענפי המשק | הלמ\"ס",
                "description": desc,
                "name": "השקעה גולמית בנכסים קבועים בענפי המשק",
                "alternate_names": ["השקעה גולמית מקומית בנכסים קבועים", "השקעות בענפי המשק",
                                    "השקעה בתשתיות בישראל", "השקעה במכונות וציוד",
                                    "השקעות בנכסים קבועים לפי ענף כלכלי"],
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
