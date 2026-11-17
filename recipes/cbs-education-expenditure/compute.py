"""ההוצאה הלאומית לחינוך: CBS's yearly release on national education spending.

The release is a set of tables ("לוח N. ...") and chart sheets ("תרשים N -
..."), and CBS renumbers them between editions (2024: 8 sheets; 2025-2026:
17). So every table input (t1..t20, three of them spare slots, all optional)
is read with `cbs.grid` and recognised by its title AND a header label that
only that table has, never by its stem:

  real     לוח: ... לפי סוג הוצאה + "במחירים קבועים"   2020 prices, by level,
                                                       per capita, yearly change
  finop    לוח: ... מגזר מבצע ומגזר מממן              NIS million by year,
                                                       financing + operating sector
  summary  לוח: ההוצאה הלאומית לחינוך + "מהתוצר"        % of GDP etc., 5 years
  mix      לוח: ... סוג הוצאה ודרג חינוך + "ישיבות"    % of current spending by
           (not "מגזר מממן")                           level, since 1990
  cost     תרשים: ... לפי סוג הוצאה + "עלות עבודה"     labour / purchases / depreciation
  tertiary לוח: הוצאות מוסדות חינוך גבוה               NIS million by institution
  univ     לוח: תקבולים ותשלומים באוניברסיטאות          receipts by source, %

`real` is required (every edition has it). A table found by title whose
header labels are gone raises (the layout changed: a human should look); a
table missing from an edition drops its section.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*[.\-]")
HEB = re.compile("[א-ת]")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
# A year row label: "2019", "R2016", "2025 - GRAND TOTAL", "Grand total - 2025".
YEAR_LABEL = re.compile(r"^(?:R\s*)?((?:19|20)\d\d)\b|\b((?:19|20)\d\d)$")
ACAD = re.compile(r"^((?:19|20)\d\d)/(\d\d)$")
PRIORITY = ("real", "percap", "levels", "gdp", "finop", "mix", "finlevel", "fin_trend",
            "univ", "tertiary", "cost")
MAX_TOP = 8
ORDINAL = {2: "השנה השנייה", 3: "השנה השלישית", 4: "השנה הרביעית", 5: "השנה החמישית",
           6: "השנה השישית", 7: "השנה השביעית", 8: "השנה השמינית", 9: "השנה התשיעית", 10: "השנה העשירית"}
LEVEL_PHRASE = {"pre": "החינוך הקדם-יסודי", "primary": "החינוך היסודי", "secondary": "החינוך העל-יסודי",
                "tertiary": "החינוך הגבוה והעל-תיכוני"}


# ── locating tables ──────────────────────────────────────────────────────


def _titles(rows):
    out = []
    for r in rows[:12]:
        for c in r:
            if TITLE.match(c):
                out.append(c)
    return " ".join(out)


def _has(rows, text, limit=40):
    return any(text in c for r in rows[:limit] for c in r)


def _kind(title, rows):
    if title.startswith("תרשים") or " תרשים" in title:
        if "סוג הוצאה" in title and _has(rows, "עלות עבודה"):
            return "cost"
        return None
    if "מגזר מבצע ומגזר מממן" in title:
        return "finop"
    if "מוסדות חינוך גבוה" in title:
        return "tertiary"
    if "תקבולים ותשלומים באוניברסיטאות" in title:
        return "univ"
    if "לפי סוג הוצאה" in title and _has(rows, "במחירים קבועים"):
        return "real"
    if "ההוצאה הלאומית לחינוך" in title and _has(rows, "מהתוצר"):
        return "summary"
    if "סוג הוצאה ודרג חינוך" in title and _has(rows, "ישיבות") and not _has(rows, "מגזר מממן"):
        return "mix"
    return None


def _tables(frames):
    """{kind: (title, rows)} over every non-empty table input; of two tables
    of one kind, the lower stem wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        t = _titles(rows)
        k = _kind(t, rows)
        if k and k not in out:
            out[k] = (t, rows)
    return out


# ── small helpers ────────────────────────────────────────────────────────


def _year_of(label):
    m = YEAR_LABEL.search(label.strip())
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def _first_data(rows, start=0):
    """Index of the first row whose first cell is a year label and that has
    numbers."""
    for i in range(start, len(rows)):
        r = rows[i]
        if _year_of(cbs.cell(r, 0)) and sum(1 for c in r[1:] if cbs.num(c) is not None) >= 2:
            return i
    raise ValueError("no year data row")


def _headers(rows, a, b):
    """Per-column header text: the cells of rows[a:b] joined top to bottom."""
    width = max((len(r) for r in rows[a:b]), default=0)
    return [" ".join(cbs.cell(r, j) for r in rows[a:b] if cbs.cell(r, j)) for j in range(width)]


def _col(heads, pred, name, lo=0, hi=None):
    hi = len(heads) if hi is None else hi
    for j in range(lo, hi):
        if pred(heads[j]):
            return j
    raise ValueError(f"{name}: header column not found")


def _he_label(r):
    """The row's Hebrew label: its last cell with Hebrew letters."""
    for c in reversed(r):
        if c and HEB.search(c):
            return c
    return ""


def _r1(v):
    return None if v is None else round(v, 1)


def _p(v, d=1):
    return fmt.pct_of(v, d)


def _bn(v):
    """NIS million → NIS billion text, one decimal."""
    return fmt.num_he(v / 1000, 1)


def _chg(a, b):
    return (b - a) / a if a else None


def _dir(f, up="עלתה", down="ירדה"):
    return up if f > 0 else down


# ── parsers ──────────────────────────────────────────────────────────────


def _real(rows):
    """Constant-price table: {year: {...}} levels (NIS million), per-capita
    (NIS), and the published yearly change block {year: {...}}; base year."""
    h = cbs.row_with(rows, "סך כולל", name="real")
    d0 = _first_data(rows, h)
    heads = _headers(rows, h, d0)
    base_m = re.search(r"במחירי\s*((?:19|20)\d\d)", " ".join(heads))
    if not base_m:
        raise ValueError("real: price base year not found")
    cols = {
        "percap": _col(heads, lambda s: "לנפש" in s, "real per capita"),
        "capital": _col(heads, lambda s: "בנכסים" in s, "real capital"),
        "univ": _col(heads, lambda s: "אוניברסיטאות" in s, "real universities"),
        "secondary": _col(heads, lambda s: "על-יסודי" in s, "real secondary"),
        "pre": _col(heads, lambda s: "קדם-יסודי" in s, "real pre-primary"),
        "current": _col(heads, lambda s: "הוצאה שוטפת" in s, "real current"),
        "total": _col(heads, lambda s: "סך כולל" in s, "real grand total"),
    }
    cols["primary"] = _col(heads, lambda s: "יסודי" in s.split() and "קדם-יסודי" not in s
                           and "על-יסודי" not in s, "real primary")
    u = cols["univ"]
    cols["tertiary"] = _col(heads, lambda s: "סך הכל" in s, "real tertiary", lo=u + 1, hi=u + 2)
    # The change block starts at its "שינוי כמותי" header (may be cut off).
    try:
        c0 = cbs.row_with(rows, "שינוי כמותי", start=d0, name="real", contains=True)
    except ValueError:
        c0 = len(rows)

    dups = set()

    def block(a, b):
        out = {}
        for r in rows[a:b]:
            y = _year_of(cbs.cell(r, 0))
            if y is None or cbs.val(r, cols["total"]) is None:
                continue
            if y in out:
                dups.add(y)  # a definition break: the later row is the new definition
            out[y] = {k: cbs.val(r, j) for k, j in cols.items()}
        return out

    lv = block(d0, c0)
    return lv, block(c0, len(rows)), int(base_m.group(1)), (min(dups) if dups else None)


def _finop(rows):
    """Current-price table: {year: {fin: {...}, op: {...}}} in NIS million,
    and the level rows of its latest year."""
    h = cbs.row_with(rows, "מגזר מממן -", name="finop", contains=True)
    fin0 = cbs.col_after(rows[h], "מגזר מממן", 0, contains=True)
    op0 = cbs.col_after(rows[h], "מגזר מבצע", 0, contains=True)
    d0 = _first_data(rows, h)
    heads = _headers(rows, h + 1, d0)

    def classify(lo, hi):
        out = {}
        for j in range(lo, hi):
            s = heads[j] if j < len(heads) else ""
            if "סך הכל" in s:
                k = "total"
            elif "העברות" in s:
                k = "hh_transfers"
            elif "קניות" in s:
                k = "hh_purchases"
            elif "עסקים" in s:
                k = "business"
            elif "פרטיים" in s:
                k = "npish"
            elif "ללא" in s:
                k = "npi"
            elif "רשויות" in s:
                k = "local"
            elif "משרדי ממשלה" in s:
                k = "gov"
            else:
                continue
            out.setdefault(k, j)
        return out

    fin = classify(fin0, op0 if fin0 < op0 else len(heads))
    op = classify(op0, fin0 if op0 < fin0 else len(heads))
    for need in ("total", "gov", "local", "npi"):
        if need not in fin or need not in op:
            raise ValueError(f"finop: column {need!r} not found")
    if "hh_purchases" not in fin or "business" not in op:
        raise ValueError("finop: household / business columns not found")
    years = {}
    for r in rows[d0:]:
        y = _year_of(cbs.cell(r, 0))
        if y is None:
            continue
        if cbs.val(r, fin["total"]) is None or cbs.val(r, op["total"]) is None:
            continue
        years[y] = {"fin": {k: cbs.val(r, j) or 0.0 for k, j in fin.items()},
                    "op": {k: cbs.val(r, j) or 0.0 for k, j in op.items()}}
    # The latest year's current expenditure by level: the labelled rows
    # between "הוצאה שוטפת" and the investment row.
    # A label can run over two rows, with the numbers on either one.
    levels, on, pend = [], False, ""
    for r in rows[d0:]:
        lab = _he_label(r)
        if "הוצאה שוטפת" in lab:
            on = True
            continue
        if "השקעה" in lab:
            break
        if not on:
            continue
        tot = cbs.val(r, fin["total"])
        # A continuation row's English label starts in lower case.
        cont = cbs.cell(r, 0)[:1].islower()
        if tot is None:
            if cont and levels and not pend:
                levels[-1] = (levels[-1][0] + " " + lab, levels[-1][1])
            pend = lab
            continue
        full = (pend + " " + lab).strip() if pend and cont else lab
        pend = ""
        if tot and full:
            levels.append((full, {k: cbs.val(r, j) or 0.0 for k, j in fin.items()}))
    return years, levels


def _summary(rows):
    """{label key: {year: value}} for the 5-year summary table."""
    yr = None
    for i, r in enumerate(rows):
        if sum(1 for c in r[1:] if cbs.YEAR.match(c)) >= 3:
            yr = i
            break
    if yr is None:
        raise ValueError("summary: year header row not found")
    ycols = [(j, int(c)) for j, c in enumerate(rows[yr]) if j > 0 and cbs.YEAR.match(c)]
    want = {"gdp": "מהתוצר המקומי הגולמי", "gov_share": "כלל הוצאותיהן",
            "households": "שכר לימוד וקניות", "public": "הממשלה ומלכ\"ר ממשלתי"}
    out = {}
    for r in rows[yr + 1:]:
        lab = _he_label(r)
        for k, text in want.items():
            if k in out or text not in lab:
                continue
            vals = {y: cbs.val(r, j) for j, y in ycols}
            if any(v is not None for v in vals.values()):
                out[k] = {y: v for y, v in vals.items() if v is not None}
    if "gdp" not in out:
        raise ValueError("summary: GDP share row not found")
    return out


def _mix(rows):
    """{year: {group: share of current expenditure}} from the level table."""
    h = cbs.row_with(rows, "Current expenditure", name="mix")
    a = cbs.col_after(rows[h], "Current expenditure", 0)
    b = cbs.col_after(rows[h], "הוצאה שוטפת", a)
    d0 = _first_data(rows, h)
    heads = _headers(rows, h + 1, d0)
    groups = {}
    for j in range(a, b + 1):
        s = heads[j] if j < len(heads) else ""
        if "קדם-" in s:
            g = "pre"
        elif "על-יסודי" in s or "עיוניים" in s or "מקצועיים" in s:
            g = "secondary"
        elif "גבוהה" in s:
            g = "tertiary"
        elif "יסודי" in s:
            g = "primary"
        else:
            g = "other"
        groups[j] = g
    for need in ("pre", "primary", "secondary", "tertiary"):
        if need not in groups.values():
            raise ValueError(f"mix: level column {need!r} not found")
    out = {}
    for r in rows[d0:]:
        lab = cbs.cell(r, 0)
        if not cbs.YEAR.match(lab):  # whole years only (the 1980s rows are school years)
            continue
        vals = {}
        for j, g in groups.items():
            v = cbs.val(r, j)
            if v is not None:
                vals[g] = vals.get(g, 0.0) + v
        if len(vals) >= 4:
            out[int(lab)] = vals  # a repeated year (2013): the later row, new definition
    return out


def _cost(title, rows):
    out = {}
    total = None
    for r in rows:
        lab = _he_label(r)
        v = cbs.val(r, 1)
        if v is None:
            continue
        if "סה\"כ" in lab:
            total = v
        elif "עלות עבודה" in lab:
            out["labour"] = v
        elif "קניית" in lab or "קניות" in lab:
            out["purchases"] = v
        elif "בלאי" in lab:
            out["depreciation"] = v
    years = [int(y) for y in YEAR_IN.findall(title)]
    return out, total, (years[-1] if years else None)


def _tertiary(rows):
    """[(year, [(label, NIS million)])] of current expenditure per year block."""
    tot = None
    for r in rows[:30]:
        for j, c in enumerate(r):
            if c == "סך הכל":
                tot = j
                break
        if tot is not None:
            break
    if tot is None:
        raise ValueError("tertiary: total column not found")
    blocks, cur, year = [], None, None
    for r in rows:
        nonempty = [c for c in r if c]
        if len(nonempty) == 1 and cbs.YEAR.match(nonempty[0].rstrip("R")):
            year = int(nonempty[0].rstrip("R"))
            cur = {"year": year, "items": [], "in_current": False}
            blocks.append(cur)
            continue
        if cur is None:
            continue
        lab = _he_label(r)
        if "הוצאה שוטפת" in lab:
            cur["in_current"] = True
            cur["current"] = cbs.val(r, tot)
            continue
        if "השקעה" in lab:
            cur["in_current"] = False
            continue
        v = cbs.val(r, tot)
        if cur["in_current"] and v is not None and lab and not lab.endswith(":"):
            cur["items"].append((lab, v))
    return [b for b in blocks if b["items"]]


def _univ(rows):
    """Receipts by source (% of total) per academic year, + total NIS million."""
    h = None
    for i, r in enumerate(rows):
        if sum(1 for c in r if ACAD.match(c)) >= 3:
            h = i
            break
    if h is None:
        raise ValueError("univ: academic-year header not found")
    ycols = [(j, c) for j, c in enumerate(rows[h]) if ACAD.match(c)]
    stop = len(rows)
    for i in range(h + 1, len(rows)):
        if any(c == "תשלומים" for c in rows[i]):
            stop = i
            break
    want = (("tuition", "שכר לימוד"), ("research", "מחקרים"), ("gov", "מהממשלה"),
            ("donations", "תרומות"), ("deficit", "גירעון"))
    out, total, pend = {}, None, ""
    for r in rows[h + 1:stop]:
        has_vals = any(cbs.val(r, j) is not None for j, _ in ycols)
        lab = (pend + " " + _he_label(r)).strip()
        if not has_vals:
            pend = lab if _he_label(r) and not any(cbs.cell(r, j) for j, _ in ycols) else ""
            continue
        pend = ""
        vals = {y: cbs.val(r, j) for j, y in ycols}
        if lab.startswith("סך הכל") and total is None:
            total = vals
            continue
        for k, text in want:
            if k not in out and text in lab:
                out[k] = vals
                break
    if "tuition" not in out or total is None:
        raise ValueError("univ: receipt rows not found")
    order = sorted((y for _, y in ycols), key=lambda s: int(s[:4]))
    return order, out, total


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    T = _tables(frames)
    if "real" not in T:
        raise ValueError("no constant-price table (לפי סוג הוצאה, במחירים קבועים) in the newest edition")
    rel = cbs.latest_release(frames["releases"])
    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(key, text):
        if text:
            insights.append({"id": key, "text_he": text})

    # ── constant prices: total, per capita, levels ───────────────────────
    lv, chg, base, brk = _real(T["real"][1])
    ys = sorted(lv)
    if len(ys) < 3:
        raise ValueError("real: fewer than 3 years")
    ly = ys[-1]
    last = lv[ly]
    labels["base"] = str(base)
    labels["break_year"] = str(brk) if brk else ""
    # Yearly real change: the published block, else from the levels.
    rchg = {}
    for y in ys[1:]:
        if y in chg and chg[y]["total"] is not None:
            rchg[y] = chg[y]["total"] / 100
        elif (y - 1) in lv and lv[y - 1]["total"]:
            rchg[y] = _chg(lv[y - 1]["total"], lv[y]["total"])
    charts["real"] = {"x": [str(y) for y in ys],
                      "total": [round(lv[y]["total"] / 1000, 2) for y in ys],
                      "percap": [lv[y]["percap"] for y in ys]}
    tables["real"] = [[str(y), _bn(lv[y]["total"]),
                       fmt.int_he(lv[y]["percap"]) if lv[y]["percap"] is not None else "",
                       fmt.signed_pct(rchg[y]) if rchg.get(y) is not None else ""] for y in ys]
    labels["real_note"] = (f"ההוצאה הלאומית לחינוך בכל שנה מאז {ys[0]}, במחירים קבועים של {base} "
                           f"(בניכוי עליית המחירים): סך ההוצאה במיליארדי ש\"ח, וההוצאה לנפש בש\"ח.")
    labels["real_aria"] = f"הוצאה לאומית לחינוך במחירי {base}, {ys[0]} עד {ly}"
    labels["real_cols"] = ["שנה", f"סך ההוצאה (מיליארדי ש\"ח, מחירי {base})",
                           f"הוצאה לנפש (ש\"ח, מחירי {base})", "שינוי ריאלי"]
    if last["percap"] is not None:
        kpis["percap"] = {"value": last["percap"], "display": fmt.int_he(last["percap"]), "tone": "brand"}
        labels["percap_kpi"] = f"הוצאה לחינוך לנפש ב-{ly} (ש\"ח, מחירי {base})"
    if rchg.get(ly) is not None:
        f = rchg[ly]
        kpis["realchg"] = {"value": round(f * 100, 1), "display": fmt.signed_pct(f),
                           "tone": "danger" if f <= -0.01 else ("ok" if f >= 0.01 else "brand")}
        labels["realchg_kpi"] = f"שינוי ריאלי בהוצאה הלאומית לחינוך, {ly} לעומת {ly - 1}"
        # Run of declines / rises ending in the latest year.
        run = 0
        for y in reversed(ys[1:]):
            if rchg.get(y) is None or (rchg[y] < 0) != (f < 0) or rchg[y] == 0:
                break
            run += 1
        peak = max(ys, key=lambda y: (lv[y]["total"], y))
        txt = (f"ב-{ly} ההוצאה הלאומית לחינוך {_dir(f)} במונחים ריאליים ב-{fmt.pct(abs(f))} "
               f"והסתכמה ב-{_bn(last['total'])} מיליארד ש\"ח במחירי {base}")
        if run >= 2:
            txt += f", {ORDINAL.get(run, f'השנה ה-{run}')} ברציפות של {'ירידה' if f < 0 else 'עלייה'}"
        if peak != ly and _chg(lv[peak]["total"], last["total"]) <= -0.01:
            txt += f". השיא היה ב-{peak}: {_bn(lv[peak]['total'])} מיליארד ש\"ח"
        add("real", txt + ".")
    pc = [y for y in ys if lv[y]["percap"] is not None]
    if len(pc) >= 3:
        pk = max(pc, key=lambda y: (lv[y]["percap"], y))
        if pk != pc[-1]:
            d = _chg(lv[pk]["percap"], lv[pc[-1]]["percap"])
            if d is not None and d <= -0.02:
                add("percap", f"ההוצאה לחינוך לנפש ירדה מ-{fmt.int_he(lv[pk]['percap'])} ש\"ח ב-{pk} "
                              f"ל-{fmt.int_he(lv[pc[-1]]['percap'])} ש\"ח ב-{pc[-1]} (במחירי {base}), "
                              f"ירידה של {fmt.pct(abs(d))}.")
        else:
            first = pc[0]
            d = _chg(lv[first]["percap"], lv[pk]["percap"])
            if d is not None and d >= 0.02:
                add("percap", f"ההוצאה לחינוך לנפש הגיעה ב-{pk} לשיא של {fmt.int_he(lv[pk]['percap'])} "
                              f"ש\"ח (במחירי {base}), {fmt.pct(d)} יותר מאשר ב-{first}.")

    lev_names = (("pre", "קדם-יסודי"), ("primary", "יסודי"), ("secondary", "על-יסודי"),
                 ("tertiary", "חינוך גבוה ועל-תיכוני"))
    charts["levels"] = {"x": [str(y) for y in ys], "names": [n for _, n in lev_names],
                        "series": [[_r1(lv[y][k] / 1000) if lv[y][k] is not None else None for y in ys]
                                   for k, _ in lev_names]}
    tables["levels"] = [[str(y)] + [_bn(lv[y][k]) if lv[y][k] is not None else "" for k, _ in lev_names]
                        for y in ys]
    labels["levels_cols"] = ["שנה"] + [n for _, n in lev_names]
    labels["levels_note"] = (f"ההוצאה השוטפת על כל דרג חינוך, במיליארדי ש\"ח במחירי {base}. "
                             f"\"חינוך גבוה ועל-תיכוני\" כולל אוניברסיטאות, מכללות ומוסדות על-תיכוניים.")
    labels["levels_aria"] = f"הוצאה שוטפת לחינוך לפי דרג חינוך במחירי {base}, {ys[0]} עד {ly}"
    b = ly - 3 if (ly - 3) in lv else ys[max(0, len(ys) - 4)]
    if b != ly:
        moves = []
        for k, n in lev_names:
            if lv[b][k] and lv[ly][k] is not None:
                moves.append((_chg(lv[b][k], lv[ly][k]), LEVEL_PHRASE[k]))
        if moves:
            lo = min(moves)
            hi = max(moves)
            if lo[0] <= -0.03 and hi[0] >= 0.03:
                add("levels", f"בין {b} ל-{ly} ההוצאה על {lo[1]} ירדה ב-{fmt.pct(abs(lo[0]))} במחירים קבועים, "
                              f"ואילו ההוצאה על {hi[1]} עלתה ב-{fmt.pct(hi[0])}.")
            elif hi[0] >= 0.03:
                add("levels", f"בין {b} ל-{ly} ההוצאה על {hi[1]} עלתה ב-{fmt.pct(hi[0])} במחירים קבועים, "
                              f"יותר מכל דרג אחר.")
            elif lo[0] <= -0.03:
                add("levels", f"בין {b} ל-{ly} ההוצאה על {lo[1]} ירדה ב-{fmt.pct(abs(lo[0]))} במחירים קבועים, "
                              f"יותר מכל דרג אחר.")

    # ── current prices: financing and operating sector ───────────────────
    flags["finop"] = "finop" in T
    fo_ly = None
    if flags["finop"]:
        fo, fo_lv = _finop(T["finop"][1])
        fys = sorted(fo)
        flags["finop"] = len(fys) >= 2
    if flags["finop"]:
        fo_ly = fys[-1]
        tot = fo[fo_ly]["op"]["total"]
        kpis["total"] = {"value": round(tot / 1000, 1), "display": _bn(tot), "tone": "brand"}
        labels["total_kpi"] = f"ההוצאה הלאומית לחינוך ב-{fo_ly} (מיליארדי ש\"ח, מחירים שוטפים)"

        def fshares(y):
            f = fo[y]["fin"]
            t = f["total"]
            return {"gov": f["gov"] / t * 100, "local": f["local"] / t * 100,
                    "hh": (f.get("hh_purchases", 0) + f.get("hh_transfers", 0)) / t * 100,
                    "npi": (f.get("npi", 0) + f.get("npish", 0)) / t * 100}

        fin_names = (("gov", "משרדי הממשלה וביטוח לאומי"), ("local", "רשויות מקומיות"),
                     ("hh", "משקי בית"), ("npi", "מוסדות ללא כוונת רווח"))
        sh = {y: fshares(y) for y in fys}
        charts["fin"] = {"x": [str(y) for y in fys], "names": [n for _, n in fin_names],
                         "series": [[_r1(sh[y][k]) for y in fys] for k, _ in fin_names]}
        tables["fin"] = [[str(y), _bn(fo[y]["fin"]["total"])] + [_p(sh[y][k]) for k, _ in fin_names]
                         for y in fys]
        labels["fin_cols"] = ["שנה", "סך המימון (מיליארדי ש\"ח)"] + [n for _, n in fin_names]
        labels["fin_note"] = ("מי משלם על החינוך: חלקו של כל מגזר במימון ההוצאה הלאומית לחינוך, באחוזים. "
                              "משקי הבית כוללים שכר לימוד ורכישות, בניכוי העברות. מימון של מוסדות ללא כוונת "
                              "רווח הוא נטו, ולכן יכול להיות שלילי.")
        labels["fin_aria"] = f"מימון ההוצאה הלאומית לחינוך לפי מגזר מממן, {fys[0]} עד {fo_ly}"
        f0, f1 = sh[fys[0]], sh[fo_ly]
        dh = f1["hh"] - f0["hh"]
        if abs(dh) >= 1:
            add("fin_trend", f"חלקם של משקי הבית במימון החינוך {_dir(dh, 'עלה', 'ירד')} מ-{_p(f0['hh'])} ב-{fys[0]} "
                             f"ל-{_p(f1['hh'])} ב-{fo_ly}, וחלקם של משרדי הממשלה "
                             f"{_dir(f1['gov'] - f0['gov'], 'עלה', 'ירד')} מ-{_p(f0['gov'])} ל-{_p(f1['gov'])}.")
        else:
            add("fin_trend", f"חלקם של משקי הבית במימון החינוך כמעט לא השתנה: {_p(f0['hh'])} ב-{fys[0]} "
                             f"ו-{_p(f1['hh'])} ב-{fo_ly}.")

        op_names = (("gov", "משרדי הממשלה וביטוח לאומי"), ("local", "רשויות מקומיות"),
                    ("npi", "מלכ\"רים במגזר הממשלתי"), ("business", "עסקים ומשקי בית"),
                    ("npish", "מלכ\"רים פרטיים"))
        op_names = tuple((k, n) for k, n in op_names if k in fo[fo_ly]["op"])
        o0, o1 = fo[fys[0]]["op"], fo[fo_ly]["op"]
        rows_ = sorted(op_names, key=lambda kn: (-o1[kn[0]], kn[1]))
        charts["op"] = {"names": [n for _, n in rows_], "years": [str(fys[0]), str(fo_ly)],
                        "series": [[_r1(o0[k] / o0["total"] * 100) for k, _ in rows_],
                                   [_r1(o1[k] / o1["total"] * 100) for k, _ in rows_]]}
        tables["op"] = [[n, _bn(o1[k]), _p(o1[k] / o1["total"] * 100), _p(o0[k] / o0["total"] * 100)]
                        for k, n in rows_]
        labels["op_cols"] = ["מגזר מבצע", f"מיליארדי ש\"ח, {fo_ly}", f"אחוז, {fo_ly}", f"אחוז, {fys[0]}"]
        labels["op_note"] = (f"מי מפעיל את שירותי החינוך: חלקו של כל מגזר בביצוע ההוצאה, {fys[0]} ו-{fo_ly}. "
                             f"מלכ\"רים במגזר הממשלתי הם בין השאר האוניברסיטאות ובתי ספר שבבעלות רשתות.")
        labels["op_aria"] = f"ההוצאה הלאומית לחינוך לפי מגזר מבצע, {fys[0]} ו-{fo_ly}"
        g_fin = f1["gov"]
        g_op = o1["gov"] / o1["total"] * 100
        if g_fin - g_op >= 10:
            add("finop", f"משרדי הממשלה מממנים {_p(g_fin)} מההוצאה הלאומית לחינוך ({fo_ly}), אבל מבצעים "
                         f"ישירות רק {_p(g_op)} ממנה. השאר עובר לרשויות המקומיות, למלכ\"רים ולגופים אחרים "
                         f"שמפעילים את מוסדות החינוך.")

    # ── summary: GDP share ───────────────────────────────────────────────
    flags["gdp"] = "summary" in T
    if flags["gdp"]:
        sm = _summary(T["summary"][1])
        gy = sorted(sm["gdp"])
        gs = sm.get("gov_share", {})
        charts["gdp"] = {"x": [str(y) for y in gy], "gdp": [sm["gdp"][y] for y in gy],
                         "gov": [gs.get(y) for y in gy] if gs else None}
        tables["gdp"] = [[str(y), _p(sm["gdp"][y])] + ([_p(gs[y]) if y in gs else ""] if gs else [])
                         for y in gy]
        labels["gdp_cols"] = ["שנה", "מהתוצר המקומי הגולמי"] + (
            ["מכלל הוצאות הממשלה והרשויות המקומיות"] if gs else [])
        labels["gdp_note"] = ("ההוצאה הלאומית לחינוך כאחוז מהתוצר המקומי הגולמי, והוצאות הממשלה והרשויות "
                              "המקומיות על חינוך כאחוז מכלל הוצאותיהן, בשנים האחרונות.")
        labels["gdp_aria"] = f"ההוצאה לחינוך כאחוז מהתוצר, {gy[0]} עד {gy[-1]}"
        kpis["gdp"] = {"value": round(sm["gdp"][gy[-1]], 1), "display": _p(sm["gdp"][gy[-1]]), "tone": "brand"}
        labels["gdp_kpi"] = f"ההוצאה הלאומית לחינוך מהתוצר המקומי הגולמי, {gy[-1]}"
        hh = sm.get("households", {})
        if hh:
            hy = max(hh)
            kpis["hh"] = {"value": round(hh[hy], 1), "display": _p(hh[hy]), "tone": "info"}
            labels["hh_kpi"] = f"חלק משקי הבית במימון (שכר לימוד ורכישות), {hy}"
        if len(gy) >= 2:
            g0, g1 = sm["gdp"][gy[0]], sm["gdp"][gy[-1]]
            txt = (f"ההוצאה הלאומית לחינוך הייתה {_p(g1)} מהתוצר ב-{gy[-1]}, "
                   + (f"לעומת {_p(g0)} ב-{gy[0]}" if abs(g1 - g0) >= 0.1 else f"כמו ב-{gy[0]}"))
            if gs and gy[0] in gs and gy[-1] in gs and abs(gs[gy[-1]] - gs[gy[0]]) >= 0.5:
                txt += (f". חלקו של החינוך בהוצאות הממשלה והרשויות המקומיות {_dir(gs[gy[-1]] - gs[gy[0]], 'עלה', 'ירד')} "
                        f"מ-{_p(gs[gy[0]])} ל-{_p(gs[gy[-1]])}")
            add("gdp", txt + ".")

    # ── mix by level over time ───────────────────────────────────────────
    flags["mix"] = "mix" in T
    if flags["mix"]:
        mx = _mix(T["mix"][1])
        my = sorted(mx)
        flags["mix"] = len(my) >= 3
    if flags["mix"]:
        groups = (("pre", "קדם-יסודי"), ("primary", "יסודי"), ("secondary", "על-יסודי"),
                  ("tertiary", "חינוך גבוה ועל-תיכוני"), ("other", "אחר"))
        charts["mix"] = {"x": [str(y) for y in my], "names": [n for _, n in groups],
                         "series": [[_r1(mx[y].get(k)) for y in my] for k, _ in groups]}
        tables["mix"] = [[str(y)] + [_p(mx[y][k]) if k in mx[y] else "" for k, _ in groups]
                         for y in my[::5] + ([my[-1]] if (len(my) - 1) % 5 else [])]
        labels["mix_cols"] = ["שנה"] + [n for _, n in groups]
        labels["mix_note"] = (f"איך מתחלקת ההוצאה השוטפת לחינוך בין הדרגים, בכל שנה מאז {my[0]}, באחוזים. "
                              f"\"אחר\" כולל מינהל כללי, ישיבות, לימודי מבוגרים, ספרי לימוד ושירותי חינוך "
                              f"אחרים. בטבלה שנה אחת מכל חמש.")
        labels["mix_aria"] = f"התפלגות ההוצאה השוטפת לחינוך לפי דרג, {my[0]} עד {my[-1]}"
        a0, a1 = mx[my[0]], mx[my[-1]]
        ch = [(a1[k] - a0[k], k) for k, _ in groups[:4] if k in a0 and k in a1]
        if ch:
            up, dn = max(ch), min(ch)
            if up[0] >= 2 and dn[0] <= -2:
                add("mix", f"חלקו של {LEVEL_PHRASE[up[1]]} בהוצאה השוטפת עלה מ-{_p(a0[up[1]])} ב-{my[0]} "
                           f"ל-{_p(a1[up[1]])} ב-{my[-1]}, וחלקו של {LEVEL_PHRASE[dn[1]]} ירד "
                           f"מ-{_p(a0[dn[1]])} ל-{_p(a1[dn[1]])}.")

    # ── financing by level (latest year, from the financing table) ───────
    fl = []
    if flags["finop"]:
        for lab, f in fo_lv:
            t = f["total"]
            hh = f.get("hh_purchases", 0) + f.get("hh_transfers", 0) + f.get("npish", 0)
            fl.append((lab, (t - hh) / t * 100, hh / t * 100))
    flags["finlevel"] = len(fl) >= 3
    if flags["finlevel"]:
        charts["finlevel"] = {"names": [n for n, _, _ in fl], "pub": [_r1(a) for _, a, _ in fl],
                              "hh": [_r1(b) for _, _, b in fl]}
        tables["finlevel"] = [[n, _p(a), _p(b)] for n, a, b in fl]
        labels["finlevel_note"] = (f"איזה חלק מההוצאה השוטפת על כל דרג מממנים הממשלה, הרשויות המקומיות "
                                   f"והמלכ\"רים, ואיזה חלק משקי הבית ותרומות, {fo_ly}, באחוזים.")
        labels["finlevel_aria"] = f"מימון ההוצאה השוטפת לחינוך לפי דרג, {fo_ly}"
        # Levels proper: not general administration, not textbooks (0% / 100% by definition).
        lv_only = [t for t in fl if not any(w in t[0] for w in ("מנהל", "מינהל", "ספרי"))]
        if len(lv_only) >= 3:
            hi = max(lv_only, key=lambda t: (t[2], t[0]))
            lo = min(lv_only, key=lambda t: (t[2], t[0]))
            if hi[2] - lo[2] >= 20:
                add("finlevel", f"משקי הבית ותרומות מממנים {_p(hi[2])} מההוצאה השוטפת על {hi[0]} ב-{fo_ly}, "
                                f"אבל רק {_p(lo[2])} מההוצאה על {lo[0]}.")

    # ── cost type (chart sheet) ──────────────────────────────────────────
    if "cost" in T:
        cs, ctot, cy = _cost(*T["cost"])
        if "labour" in cs:
            add("cost", f"עלות העבודה היא {_p(cs['labour'])} מההוצאה השוטפת של הממשלה, הרשויות המקומיות "
                        f"והמלכ\"רים על חינוך{' ב-' + str(cy) if cy else ''}"
                        + (f" (מתוך {fmt.num_he(ctot, 1)} מיליארד ש\"ח)" if ctot else "")
                        + (f". קניות סחורות ושירותים: {_p(cs['purchases'])}" if "purchases" in cs else "")
                        + ".")

    # ── tertiary institutions ────────────────────────────────────────────
    flags["tertiary"] = "tertiary" in T
    if flags["tertiary"]:
        tb = _tertiary(T["tertiary"][1])
        flags["tertiary"] = bool(tb) and len(tb[-1]["items"]) >= 3
    if flags["tertiary"]:
        cur = tb[-1]
        prev = {n: v for n, v in tb[-2]["items"]} if len(tb) >= 2 else {}
        items = sorted(cur["items"], key=lambda nv: (-nv[1], nv[0]))
        tsum = sum(v for _, v in items)
        charts["tertiary"] = {"names": [n for n, _ in items], "values": [v for _, v in items]}
        tables["tertiary"] = [[n, fmt.int_he(v), fmt.pct(v / tsum) if tsum else "",
                               fmt.int_he(prev[n]) if n in prev else ""] for n, v in items]
        labels["tertiary_cols"] = ["סוג מוסד", f"מיליוני ש\"ח, {cur['year']}", "חלק",
                                   f"מיליוני ש\"ח, {tb[-2]['year']}" if len(tb) >= 2 else ""]
        if len(tb) < 2:
            labels["tertiary_cols"] = labels["tertiary_cols"][:3]
            tables["tertiary"] = [r[:3] for r in tables["tertiary"]]
        labels["tertiary_note"] = (f"ההוצאה השוטפת של מוסדות החינוך הגבוה והעל-תיכוני לפי סוג מוסד, "
                                   f"{cur['year']}, במיליוני ש\"ח במחירים שוטפים (ללא המגזר העסקי).")
        labels["tertiary_aria"] = f"הוצאות מוסדות חינוך גבוה לפי סוג מוסד, {cur['year']}"
        top = items[0]
        if tsum and top[1] / tsum >= 0.4:
            add("tertiary", f"ל{top[0]} הולכים {fmt.pct(top[1] / tsum)} מההוצאה השוטפת של מוסדות החינוך "
                            f"הגבוה והעל-תיכוני ({fmt.int_he(top[1])} מיליון ש\"ח ב-{cur['year']}).")

    # ── universities: receipts ───────────────────────────────────────────
    flags["univ"] = "univ" in T
    if flags["univ"]:
        uy, us, ut = _univ(T["univ"][1])
        flags["univ"] = len(uy) >= 3
    if flags["univ"]:
        u_names = (("gov", "הממשלה והסוכנות"), ("donations", "תרומות"), ("research", "מחקרים מוזמנים"),
                   ("tuition", "שכר לימוד"))
        u_names = tuple((k, n) for k, n in u_names if k in us)
        charts["univ"] = {"x": uy, "names": [n for _, n in u_names],
                          "series": [[us[k].get(y) for y in uy] for k, _ in u_names]}
        tables["univ"] = [[y, fmt.int_he(ut[y]) if ut.get(y) is not None else ""]
                          + [_p(us[k][y]) if us[k].get(y) is not None else "" for k, _ in u_names]
                          + ([_p(us["deficit"][y]) if us["deficit"].get(y) is not None else ""]
                             if "deficit" in us else [])
                          for y in uy]
        labels["univ_cols"] = (["שנת לימודים", "סך התקבולים (מיליוני ש\"ח)"] + [n for _, n in u_names]
                               + (["גירעון"] if "deficit" in us else []))
        labels["univ_note"] = ("מאין מגיע הכסף של האוניברסיטאות: חלקו של כל מקור מסך התקבולים בכל שנת "
                               "לימודים, באחוזים (העברות שוטפות; בלי העברות הון).")
        labels["univ_aria"] = f"תקבולי האוניברסיטאות לפי מקור, {uy[0]} עד {uy[-1]}"
        t0, t1 = us["tuition"].get(uy[0]), us["tuition"].get(uy[-1])
        if t0 is not None and t1 is not None and abs(t1 - t0) >= 0.5:
            txt = (f"שכר הלימוד מימן {_p(t1)} מתקבולי האוניברסיטאות בשנת הלימודים {uy[-1]}, "
                   f"לעומת {_p(t0)} ב-{uy[0]}")
            if "gov" in us and us["gov"].get(uy[-1]) is not None:
                txt += f". הממשלה והסוכנות היהודית מימנו {_p(us['gov'][uy[-1]])}"
            add("univ", txt + ".")

    # ── insight card + callouts ──────────────────────────────────────────
    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    tot_txt = (f"{_bn(fo[fo_ly]['op']['total'])} מיליארד ש\"ח ב-{fo_ly}" if fo_ly
               else f"{_bn(last['total'])} מיליארד ש\"ח במחירי {base} ב-{ly}")
    gdp_txt = (f", {_p(kpis['gdp']['value'])} מהתוצר" if "gdp" in kpis else "")
    labels["lede"] = (f"כמה מוציאה ישראל על חינוך, על מה ומי משלם. הנתונים מתוך ההודעה השנתית של הלשכה "
                      f"המרכזית לסטטיסטיקה (הלמ\"ס) על ההוצאה הלאומית לחינוך, ומתעדכנים עם כל הודעה חדשה. "
                      f"ההוצאה הלאומית לחינוך הסתכמה ב-{tot_txt}{gdp_txt}.")
    summary = (f"ההוצאה הלאומית לחינוך בישראל לפי הלמ\"ס: {tot_txt}{gdp_txt}, "
               f"והוצאה לנפש של {fmt.int_he(last['percap'] or 0)} ש\"ח במחירי {base}.")
    desc = (f"כמה ישראל מוציאה על חינוך: {tot_txt}{gdp_txt}. "
            f"הוצאה לפי דרג, מי מממן, הוצאה לנפש ואוניברסיטאות.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{min(ys[0], min(my) if flags['mix'] else ys[0])}/{max(ly, fo_ly or ly)}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "ההוצאה הלאומית לחינוך בישראל | נתוני הלמ\"ס",
                "description": desc,
                "name": "ההוצאה הלאומית לחינוך",
                "alternate_names": ["הוצאה לאומית לחינוך", "תקציב החינוך בישראל",
                                    "הוצאה לחינוך לנפש", "ההוצאה על חינוך כאחוז מהתוצר"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top,
        "callouts": callouts,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
