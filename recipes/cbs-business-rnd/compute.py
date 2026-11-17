"""ההוצאה למחקר ופיתוח במגזר העסקי: CBS's yearly business R&D release.

The release has two kinds of sheets: numbered tables ("לוח N. ...", each
published twice: the data year and the revised year before it) and
chart-data sheets ("תרשים N - ..."). CBS RENUMBERS the sheets between
editions (the GDP-share chart was t16 in 2025 and t17 in 2026; districts
t29, t30, t27), so every table input (t1..t36, the last three spare, all
optional) is read with `cbs.grid`, one sheet at a time, and each subject is
found by its TITLE, never by its stem:

  exp       לוח: הוצאות והשקעות בחברות העוסקות במו"פ   by year (latest + revised)
  jobs      לוח: משרות בחברות העוסקות במו"פ             by year
  sales     לוח: הכנסות ממכירות, יצוא ומכירות מו"פ       by year
  fields    לוח: ... לפי תחומי פעילות                    latest year
  fin       לוח: מימון סך ההוצאה למו"פ                   latest year
  ind       לוח: הוצאות והשקעות למו"פ, לפי ענף כלכלי      latest year
  indjobs   לוח: משרות ... לפי ענף כלכלי                 latest year
  real      תרשים: ... (במחירי 2017)                     yearly series
  gdp       תרשים: ... תמ"ג (not OECD)                   yearly series
  district  תרשים: עלות העבודה ... לפי מחוז
  rtype     תרשים: ... לפי סוג מחקר
  tech      תרשים: ... לפי סוג טכנולוגיה
  oecd      תרשים: ... תמ"ג במדינות OECD
  staff     תרשים: ... לכל 100,000 ... בכוח העבודה

A subject missing from an edition drops its section; a recognised sheet
whose header labels are gone raises (the layout changed: a human should
look). Only the latest `exp` table is required.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:לוח|תרשים)\s*\d+[א-ת]?\s*[.\-:–]?\s*")
HEB = re.compile("[א-ת]")
YEAR_R = re.compile(r"^((?:19|20)\d\d)\s*(R?)$")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
NOTE = re.compile(r"^(?:\(\d+\)|\.\.|-|\*|טעויות)")
SIZE = re.compile(r"^\+?\d+(?:\s*-\s*\d+)?\+?$")
PRIORITY = ("growth", "real", "gdp", "foreign", "big", "software", "women", "fin",
            "centres", "ai", "dev", "district", "sales", "staff")
MAX_TOP = 8

CATS = (
    ("total", "סך כל המגזר העסקי"),
    ("hi", "תעשייה עילית"),
    ("midhi", "תעשייה מעורבת-עילית"),
    ("low", "תעשייה מסורתית ומעורבת-מסורתית"),
    ("soft", "תכנות, ייעוץ מחשבים ושירותי מידע"),
    ("sci", "מחקר מדעי ופיתוח"),
    ("isr", "חברות בבעלות ישראלית"),
    ("frn", "חברות בבעלות זרה"),
    ("ctr", "מרכזי מו\"פ"),
    ("start", "חברות הזנק"),
)
CAT_NAME = dict(CATS)
TYPE_KEYS = ("isr", "frn", "ctr", "start")
IND_KEYS = ("hi", "midhi", "low", "soft", "sci")


# ── reading sheets ───────────────────────────────────────────────────────


def _norm(v):
    return (v.replace("''", '"').replace("״", '"').replace("׳׳", '"')
            .replace("\u200f", "").replace("\u200e", "").strip())


def _sheets(df, name):
    """[(title, rows)] for each sheet of the newest edition of one input."""
    if df.empty:
        return []
    out = []
    for s in sorted(df["SHEET_NO"].unique()):
        rows = [[_norm(c) for c in r] for r in cbs.grid(df[df["SHEET_NO"] == s], name)]
        title, at = "", None
        for i, r in enumerate(rows):
            for c in r:
                if TITLE.match(c) and HEB.search(c):
                    title, at = c, i
                    break
            if title:
                break
        if title:
            out.append((title, rows[at:]))
    return out


def _kind(t):
    body = TITLE.sub("", t)
    if t.startswith("לוח"):
        if "לפי תחומי פעילות" in body:
            return "fields"
        if body.startswith("מימון סך ההוצאה"):
            return "fin"
        if body.startswith("הוצאות והשקעות למו\"פ") and "לפי ענף" in body:
            return "ind"
        if body.startswith("משרות") and "לפי ענף" in body:
            return "indjobs"
        if body.startswith("הוצאות והשקעות בחברות העוסקות"):
            return "exp"
        if body.startswith("משרות בחברות העוסקות"):
            return "jobs"
        if body.startswith("הכנסות ממכירות"):
            return "sales"
        return None
    if "OECD" in body:
        if "תמ\"ג" in body:
            return "oecd"
        if "100,000" in body and "כוח העבודה" in body:
            return "staff"
        return None
    if "במחירי" in body and "מו\"פ פנימי" in body and "תמ\"ג" not in body:
        return "real"
    if "תמ\"ג" in body and "מו\"פ פנימי" in body:
        return "gdp"
    if "עלות" in body and "לפי מחוז" in body:
        return "district"
    if "לפי סוג מחקר" in body:
        return "rtype"
    if "לפי סוג טכנולוגיה" in body:
        return "tech"
    return None


def _tables(frames):
    """{kind: [(title, rows), ...]} in stem order."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        for title, rows in _sheets(frames[n], n):
            k = _kind(title)
            if k:
                out.setdefault(k, []).append((title, rows))
    return out


def _year_of(rows, stop):
    """The table's data year from the cells above its first data row:
    (2024, False) or (2023, True) for "2023R"."""
    for r in rows[:stop]:
        for c in r:
            m = YEAR_R.match(c)
            if m:
                return int(m.group(1)), bool(m.group(2))
    raise ValueError("table year not found")


def _latest(tlist):
    """The newest data year's (title, rows) of a table CBS prints once per
    year (the data year and the revised year before it)."""
    def key(tr):
        rows = tr[1]
        stop = next((i for i, r in enumerate(rows) if any(_is_total(c) for c in r)), len(rows))
        try:
            y, rev = _year_of(rows, stop)
        except ValueError:
            return (0, False)
        return (y, rev)
    return max(tlist, key=key)


def _hcol(rows, stop, label, start=1, exact=False):
    """First column (≥ start) whose header cell above row `stop` holds
    `label`. Raises when no header cell does."""
    best = None
    for r in rows[:stop]:
        for j in range(start, len(r)):
            c = r[j]
            if TITLE.match(c):
                continue
            if (c == label) if exact else (label in c):
                if best is None or j < best:
                    best = j
                break
    if best is None:
        raise ValueError(f"header label {label!r} not found")
    return best


def _first_row(rows, pred, start=0):
    for i in range(start, len(rows)):
        if pred(cbs.cell(rows[i], 0)):
            return i
    return None


def _is_total(lbl):
    return lbl.startswith(("סך כל המגזר העסקי", "סך המגזר העסקי"))


def _cat(lbl):
    if _is_total(lbl):
        return "total"
    if lbl == "עילית":
        return "hi"
    if lbl == "מעורבת-עילית":
        return "midhi"
    if lbl.startswith("מעורבת-מסורתית"):
        return "low"
    if "תכנות וייעוץ" in lbl:
        return "soft"
    if "מחקר מדעי" in lbl:
        return "sci"
    if lbl == "ישראלית":
        return "isr"
    if lbl == "זרה":
        return "frn"
    if lbl == "מרכזי מו\"פ":
        return "ctr"
    if lbl == "חברות הזנק":
        return "start"
    if SIZE.match(lbl):
        nums = sorted(int(x) for x in re.findall(r"\d+", lbl))
        return f"size:{nums[-1]}"
    return None


def _size_label(lbl):
    nums = sorted(int(x) for x in re.findall(r"\d+", lbl))
    return f"{nums[0]}-{nums[1]}" if len(nums) == 2 else f"{nums[0]}+"


def _cat_rows(rows, start):
    """{cat: row} for the category rows from `start` on (first wins), and
    the size labels in order."""
    out, sizes = {}, []
    for r in rows[start:]:
        lbl = cbs.cell(r, 0)
        k = _cat(lbl)
        if k and k not in out:
            out[k] = r
            if k.startswith("size:"):
                sizes.append((int(k[5:]), _size_label(lbl)))
    return out, sorted(sizes)


def _by_year(tlist, cols_spec):
    """Parse each (title, rows) of a by-year table into
    {year: {"rev": bool, "cats": {cat: {col: value}}, "sizes": [...]}}."""
    out = {}
    for _title, rows in tlist:
        t0 = _first_row(rows, _is_total)
        if t0 is None:
            raise ValueError(f"{_title}: total row not found")
        year, rev = _year_of(rows, t0)
        cols = {k: _hcol(rows, t0, lbl) for k, lbl in cols_spec.items()}
        cats, sizes = _cat_rows(rows, t0)
        parsed = {c: {k: cbs.val(r, j) for k, j in cols.items()} for c, r in cats.items()}
        prev = out.get(year)
        if prev is None or (rev and not prev["rev"]):
            out[year] = {"rev": rev, "cats": parsed, "sizes": sizes}
    return out


# ── formatting helpers ───────────────────────────────────────────────────


def _bn(v):
    """₪ millions → '147.8' (billions)."""
    return fmt.num_he(v / 1000, 1)


def _r(v, d=1):
    return None if v is None else round(v, d)


def _share(a, b):
    return a / b if a is not None and b else None


def _t(v, d=1):
    """Table cell: a number or an en dash placeholder."""
    return "–" if v is None else fmt.num_he(v, d)


def _short(lbl, n=28):
    """An axis label: whole when short, else cut at a word boundary + "…"
    (the full name is in the table under the chart)."""
    if len(lbl) <= n:
        return lbl
    cut = lbl[:n].rsplit(" ", 1)[0].rstrip(" ,")
    return cut + "…"


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    T = _tables(frames)
    rel = cbs.latest_release(frames["releases"])
    kpis, charts, tables, labels, insights = {}, {}, {}, {}, []
    flags = {"women": False, "finint": False}

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── expenditure (required) ───────────────────────────────────────────
    if "exp" not in T:
        raise ValueError("expenditure table (הוצאות והשקעות בחברות העוסקות במו\"פ) not found")
    exp = _by_year(T["exp"], {
        "total": "סך ההוצאות למו\"פ", "internal": "מו\"פ פנימי", "labour": "עלות עבודה",
        "onsite": "תשלום לגורמי חוץ", "other": "הוצאות אחרות",
        "capital": "השקעות בנכסים קבועים", "external": "מו\"פ חיצוני",
        "fte_cost": "עלות העבודה למשרה מלאה"})
    ys = sorted(exp)
    Y = ys[-1]
    PY = ys[-2] if len(ys) > 1 else None
    E = exp[Y]["cats"]
    if "total" not in E or E["total"]["total"] is None:
        raise ValueError("expenditure total missing")
    tot = E["total"]
    EP = exp[PY]["cats"] if PY else {}
    ptot = EP.get("total", {}).get("total")

    kpis["total"] = {"value": round(tot["total"]), "display": _bn(tot["total"]), "tone": "brand"}
    labels["total_kpi"] = f"ההוצאה הכוללת למו\"פ ב-{Y} (מיליארד ₪)"
    if ptot:
        ch = tot["total"] / ptot - 1
        kpis["change"] = {"value": round(ch * 1000) / 10, "display": fmt.signed_pct(ch),
                          "tone": "ok" if ch >= 0.01 else ("danger" if ch <= -0.01 else "brand")}
        labels["change_kpi"] = f"שינוי לעומת {PY} (מחירים שוטפים)"
        if abs(ch) >= 0.01:
            word = "עלייה" if ch > 0 else "ירידה"
            add("growth", f"ההוצאה הכוללת למו\"פ במגזר העסקי הגיעה ל-{_bn(tot['total'])} מיליארד ₪ "
                          f"ב-{Y}, {word} של {fmt.pct(abs(ch))} לעומת {PY} "
                          f"({_bn(ptot)} מיליארד ₪, במחירים שוטפים).")
        else:
            add("growth", f"ההוצאה הכוללת למו\"פ במגזר העסקי נותרה כמעט ללא שינוי: "
                          f"{_bn(tot['total'])} מיליארד ₪ ב-{Y} לעומת {_bn(ptot)} ב-{PY}.")
    if tot["fte_cost"] is not None:
        kpis["fte"] = {"value": round(tot["fte_cost"]), "display": fmt.int_he(tot["fte_cost"]),
                       "tone": "brand"}
        labels["fte_kpi"] = f"עלות עבודה שנתית למשרה מלאה במו\"פ, {Y} (אלפי ₪)"

    # composition of the expenditure
    parts = [("עלות עבודה", tot["labour"]), ("תשלומים לגורמי חוץ במפעל", tot["onsite"]),
             ("הוצאות שוטפות אחרות (תקורה וחומרים)", tot["other"]),
             ("השקעות בנכסים קבועים למו\"פ", tot["capital"]), ("מו\"פ חיצוני (רכישה מגורמים אחרים)", tot["external"])]
    parts = [(n, v) for n, v in parts if v is not None]
    flags["structure"] = len(parts) >= 3
    if flags["structure"]:
        charts["structure"] = {"names": [n for n, _ in parts], "values": [_r(v / 1000, 2) for _, v in parts]}
        tables["structure"] = [[n, _bn(v), fmt.pct(v / tot["total"])] for n, v in parts]
        labels["structure_aria"] = f"ההוצאה למו\"פ במגזר העסקי לפי סוג הוצאה, {Y}"
        labels["structure_note"] = (f"לאן הולך הכסף: ההוצאה הכוללת למו\"פ ב-{Y} לפי סוג ההוצאה, "
                                    f"במיליארדי ₪ במחירים שוטפים.")
        if tot["labour"]:
            labels["structure_lede"] = (f"עלות העבודה היא {fmt.pct(tot['labour'] / tot['total'])} "
                                        f"מכל ההוצאה למו\"פ: המו\"פ בישראל הוא בעיקר שכר של אנשים.")

    # company types: Israeli / foreign / R&D centres / start-ups
    types = [k for k in TYPE_KEYS if k in E and E[k]["total"] is not None]
    flags["types"] = len(types) >= 2
    if flags["types"]:
        charts["types"] = {"names": [CAT_NAME[k] for k in types],
                           "cur": [_r(E[k]["total"] / 1000, 2) for k in types],
                           "prev": [_r(EP[k]["total"] / 1000, 2) if k in EP and EP[k]["total"] is not None
                                    else None for k in types] if PY else None,
                           "y": str(Y), "py": str(PY) if PY else ""}
        tables["types"] = [[CAT_NAME[k], _bn(E[k]["total"]),
                            fmt.pct(E[k]["total"] / tot["total"]),
                            _t(E[k]["fte_cost"], 0)]
                           + ([_bn(EP[k]["total"]) if k in EP and EP[k]["total"] is not None else "–"]
                              if PY else [])
                           for k in types]
        labels["types_cols"] = (["סוג חברה", f"הוצאה ב-{Y} (מיליארד ₪)", "חלק מסך ההוצאה",
                                 "עלות עבודה למשרה מלאה (אלפי ₪)"]
                                + ([f"הוצאה ב-{PY} (מיליארד ₪)"] if PY else []))
        labels["types_aria"] = f"ההוצאה למו\"פ לפי סוג חברה, {PY} ו-{Y}" if PY else f"ההוצאה למו\"פ לפי סוג חברה, {Y}"
        labels["types_note"] = ("ההוצאה למו\"פ לפי בעלות על החברה (ישראלית או זרה), ושתי קבוצות "
                                "מיוחדות: מרכזי מו\"פ של חברות זרות וחברות הזנק. הקבוצות חופפות "
                                "חלקית, ולכן אינן מסתכמות לסך הכול.")
        if "frn" in E and E["frn"]["total"] is not None:
            s = E["frn"]["total"] / tot["total"]
            if s >= 0.3:
                txt = (f"חברות בבעלות זרה הוציאו {_bn(E['frn']['total'])} מיליארד ₪ על מו\"פ ב-{Y}, "
                       f"{fmt.pct(s)} מכל ההוצאה במגזר העסקי")
                if "ctr" in E and E["ctr"]["total"] is not None:
                    txt += (f". מרכזי המו\"פ של חברות זרות לבדם הוציאו "
                            f"{_bn(E['ctr']['total'])} מיליארד ₪")
                add("foreign", txt + ".")
        if all(k in E and E[k]["fte_cost"] is not None for k in ("ctr", "start")):
            a, b = E["ctr"]["fte_cost"], E["start"]["fte_cost"]
            if a > b * 1.2:
                add("centres", f"משרה מלאה במו\"פ במרכז מו\"פ של חברה זרה עלתה ב-{Y} "
                               f"{fmt.int_he(a)} אלף ₪ בשנה בממוצע, לעומת {fmt.int_he(b)} אלף ₪ "
                               f"בחברת הזנק ({fmt.int_he(tot['fte_cost'])} אלף ₪ בכל המגזר העסקי).")

    # company size
    sizes = exp[Y]["sizes"]
    sz = [(k, lbl) for k, lbl in sizes if E.get(f"size:{k}", {}).get("total") is not None]
    flags["size"] = len(sz) >= 3
    if flags["size"]:
        charts["size"] = {"names": [lbl for _, lbl in sz],
                          "values": [_r(E[f"size:{k}"]["total"] / 1000, 2) for k, _ in sz],
                          "fte": [_r(E[f"size:{k}"]["fte_cost"], 0) for k, _ in sz]}
        tables["size"] = [[lbl, _bn(E[f"size:{k}"]["total"]),
                           fmt.pct(E[f"size:{k}"]["total"] / tot["total"]),
                           _t(E[f"size:{k}"]["fte_cost"], 0)] for k, lbl in sz]
        labels["size_aria"] = f"ההוצאה למו\"פ לפי גודל החברה (מספר משרות), {Y}"
        labels["size_note"] = (f"ההוצאה למו\"פ ב-{Y} לפי גודל החברה, במספר המשרות בחברה כולה, "
                               f"ועלות העבודה הממוצעת למשרה מלאה במו\"פ בכל קבוצה.")
        big_k, big_l = sz[-1]
        s = E[f"size:{big_k}"]["total"] / tot["total"]
        if s >= 0.3:
            txt = (f"החברות הגדולות ביותר ({big_l} משרות) אחראיות ל-{fmt.pct(s)} מההוצאה למו\"פ "
                   f"במגזר העסקי ב-{Y}")
            big_c = E[f"size:{big_k}"]["fte_cost"]
            small_c = E[f"size:{sz[0][0]}"]["fte_cost"]
            if big_c is not None and small_c is not None and big_c > small_c:
                txt += (f", והעלות הממוצעת של משרה מלאה במו\"פ אצלן "
                        f"({_t(big_c, 0)} אלף ₪) גבוהה מזו של החברות "
                        f"הקטנות ({sz[0][1]} משרות, {_t(small_c, 0)} אלף ₪)")
            add("big", txt + ".")

    # ── real series (2017 prices) ───────────────────────────────────────
    flags["real"] = False
    if "real" in T:
        _title, rows = T["real"][0]
        pts = {}
        for r in rows[1:]:
            m = YEAR_R.match(cbs.cell(r, 0))
            v = cbs.val(r, 1)
            if not m or v is None:
                continue
            y, rv = int(m.group(1)), bool(m.group(2))
            if y not in pts or rv:
                pts[y] = v
        yr = sorted(pts)
        if len(yr) >= 3:
            flags["real"] = True
            base = YEAR_IN.findall(TITLE.sub("", _title))
            base = base[0] if base else ""
            charts["real"] = {"x": [str(y) for y in yr], "y": [_r(pts[y] / 1000, 2) for y in yr]}
            tables["real"] = [[str(y), _bn(pts[y])] for y in yr]
            labels["real_aria"] = f"ההוצאה למו\"פ פנימי במגזר העסקי במחירים קבועים, {yr[0]}-{yr[-1]}"
            labels["real_note"] = (f"ההוצאה למו\"פ פנימי (המו\"פ שהחברות מבצעות בעצמן) במחירים "
                                   f"קבועים של {base}, במיליארדי ₪: הצמיחה האמיתית, בניכוי עליית המחירים."
                                   if base else
                                   "ההוצאה למו\"פ פנימי במחירים קבועים, במיליארדי ₪.")
            labels["real_col"] = f"מיליארד ₪, במחירי {base}" if base else "מיליארד ₪, מחירים קבועים"
            g = pts[yr[-1]] / pts[yr[0]] - 1
            last = pts[yr[-1]] / pts[yr[-2]] - 1
            if abs(g) >= 0.05:
                word = "גדלה" if g > 0 else "קטנה"
                txt = (f"במחירים קבועים ההוצאה למו\"פ פנימי במגזר העסקי {word} ב-{fmt.pct(abs(g), 0)} "
                       f"בין {yr[0]} ל-{yr[-1]}")
                if abs(last) >= 0.005:
                    txt += (f"; בשנה האחרונה ({yr[-1]}) {'עלתה' if last > 0 else 'ירדה'} ב-"
                            f"{fmt.pct(abs(last))}")
                add("real", txt + ".")

    # ── share of GDP ─────────────────────────────────────────────────────
    flags["gdp"] = False
    gdp_last = None
    if "gdp" in T:
        _title, rows = T["gdp"][0]
        d0 = _first_row(rows, lambda c: bool(YEAR_R.match(c)), 1)
        if d0 is None:
            raise ValueError(f"{_title}: no year rows")
        c_share = _hcol(rows, d0, "מתוך התמ\"ג")
        c_rd = _hcol(rows, d0, "הוצאה למו\"פ פנימי")
        if c_rd == c_share:
            raise ValueError(f"{_title}: R&D column not found")
        pts = {}
        for r in rows[d0:]:
            m = YEAR_R.match(cbs.cell(r, 0))
            sh, rd = cbs.val(r, c_share), cbs.val(r, c_rd)
            if not m or sh is None:
                continue
            pts[int(m.group(1))] = (sh, rd)
        # fraction vs percent: decided once for the whole sheet
        if pts and max(sh for sh, _ in pts.values()) <= 1:
            pts = {y: (sh * 100, rd) for y, (sh, rd) in pts.items()}
        yg = sorted(pts)
        if len(yg) >= 3:
            flags["gdp"] = True
            gdp_last = (yg[-1], pts[yg[-1]][0])
            charts["gdp"] = {"x": [str(y) for y in yg], "share": [_r(pts[y][0], 2) for y in yg],
                             "rd": [_r(pts[y][1] / 1000, 1) if pts[y][1] is not None else None for y in yg]}
            tables["gdp"] = [[str(y), fmt.pct_of(pts[y][0]), _bn(pts[y][1]) if pts[y][1] is not None else "–"]
                             for y in yg]
            labels["gdp_aria"] = f"ההוצאה למו\"פ פנימי במגזר העסקי כאחוז מהתמ\"ג, {yg[0]}-{yg[-1]}"
            labels["gdp_note"] = ("ההוצאה למו\"פ פנימי במגזר העסקי כאחוז מהתוצר המקומי הגולמי (קו), "
                                  "וההוצאה עצמה במיליארדי ₪ במחירים שוטפים (עמודות).")
            kpis["gdp"] = {"value": _r(gdp_last[1], 2), "display": fmt.pct_of(gdp_last[1]), "tone": "info"}
            labels["gdp_kpi"] = f"מו\"פ פנימי במגזר העסקי מתוך התמ\"ג, {gdp_last[0]}"

    # ── OECD comparison ──────────────────────────────────────────────────
    flags["oecd"] = False
    oecd_avg = None
    if "oecd" in T:
        _title, rows = T["oecd"][0]
        vals = []
        for r in rows[1:]:
            lbl, v = cbs.cell(r, 0), cbs.val(r, 1)
            if lbl and v is not None and (HEB.search(lbl) or lbl == "OECD"):
                vals.append((lbl, v))
        if vals and max(v for _, v in vals) <= 1:
            vals = [(n, v * 100) for n, v in vals]
        isr = [v for n, v in vals if n.startswith("ישראל")]
        if len(vals) >= 5 and isr:
            flags["oecd"] = True
            vals.sort(key=lambda nv: (nv[1], nv[0]))
            yrs = YEAR_IN.findall(TITLE.sub("", _title))
            oy = yrs[-1] if yrs else ""
            charts["oecd"] = {"names": [n for n, _ in vals], "values": [_r(v, 2) for _, v in vals]}
            tables["oecd"] = [[n, fmt.pct_of(v)] for n, v in reversed(vals)]
            labels["oecd_aria"] = f"הוצאה למו\"פ במגזר העסקי כאחוז מהתמ\"ג במדינות OECD, {oy}"
            labels["oecd_note"] = (f"ההוצאה למו\"פ במגזר העסקי כאחוז מהתמ\"ג בישראל ובמדינות OECD "
                                   f"נבחרות{', ' + oy if oy else ''}, כפי שהלמ\"ס מציגה בהודעה.")
            avg = [v for n, v in vals if n == "OECD"]
            oecd_avg = avg[0] if avg else None
            others = [(n, v) for n, v in vals if not n.startswith("ישראל") and n not in ("OECD",)
                      and "האיחוד" not in n]
            top_other = max(others, key=lambda nv: (nv[1], nv[0])) if others else None
            if isr[0] >= max(v for _, v in vals):
                txt = (f"ישראל מובילה את ההשוואה הבין-לאומית{' (' + oy + ')' if oy else ''}: "
                       f"{fmt.pct_of(isr[0])} מהתמ\"ג הוצאו על מו\"פ במגזר העסקי")
                if oecd_avg:
                    txt += f", פי {fmt.num_he(isr[0] / oecd_avg, 1)} מממוצע ה-OECD ({fmt.pct_of(oecd_avg)})"
                if top_other:
                    txt += f". הבאה אחריה: {top_other[0]} ({fmt.pct_of(top_other[1])})"
                add("gdp", txt + ".")
    if "gdp" not in {i["id"] for i in insights} and gdp_last:
        add("gdp", f"ההוצאה למו\"פ פנימי במגזר העסקי הגיעה ב-{gdp_last[0]} ל-{fmt.pct_of(gdp_last[1])} "
                   f"מהתוצר המקומי הגולמי.")

    # ── R&D staff per 100,000 in the labour force ────────────────────────
    flags["staff"] = False
    if "staff" in T:
        _title, rows = T["staff"][0]
        hdr_end = None
        for i in range(1, len(rows)):
            if any("חוקרים" in c for c in rows[i]):
                hdr_end = i + 1
                break
        if hdr_end is None:
            raise ValueError(f"{_title}: researchers header not found")
        c_name = _hcol(rows, hdr_end, "מדינה", start=0, exact=True)
        c_res = _hcol(rows, hdr_end, "חוקרים", start=c_name + 1)
        c_oth = _hcol(rows, hdr_end, "שאר עובדי", start=c_name + 1)
        pts = []
        for r in rows[hdr_end:]:
            n, a, b = cbs.cell(r, c_name), cbs.val(r, c_res), cbs.val(r, c_oth)
            if n and HEB.search(n) and a is not None and b is not None:
                pts.append((n, a, b))
        if len(pts) >= 5 and any(n.startswith("ישראל") for n, _, _ in pts):
            flags["staff"] = True
            pts.sort(key=lambda p: (p[1] + p[2], p[0]))
            yrs = YEAR_IN.findall(TITLE.sub("", _title))
            sy = yrs[-1] if yrs else ""
            charts["staff"] = {"names": [p[0] for p in pts], "res": [_r(p[1], 0) for p in pts],
                               "oth": [_r(p[2], 0) for p in pts]}
            tables["staff"] = [[p[0], fmt.int_he(p[1]), fmt.int_he(p[2]), fmt.int_he(p[1] + p[2])]
                               for p in reversed(pts)]
            labels["staff_aria"] = f"חוקרים ועובדי מו\"פ אחרים במגזר העסקי לכל 100,000 בכוח העבודה, {sy}"
            labels["staff_note"] = ("כמה עובדים במו\"פ במגזר העסקי על כל 100,000 משתתפים בכוח העבודה: "
                                    "חוקרים, ושאר עובדי המו\"פ (טכנאים ואנשי תמיכה)"
                                    + (f", {sy}." if sy else "."))
            isr = next(p for p in pts if p[0].startswith("ישראל"))
            rest = [p for p in pts if not p[0].startswith("ישראל")]
            second = max(rest, key=lambda p: (p[1] + p[2], p[0]))
            if isr[1] + isr[2] > second[1] + second[2]:
                add("staff", f"בישראל {fmt.int_he(isr[1] + isr[2])} עובדי מו\"פ במגזר העסקי לכל 100,000 "
                             f"משתתפים בכוח העבודה, יותר מכל מדינה אחרת בהשוואה (במקום השני: "
                             f"{second[0]}, {fmt.int_he(second[1] + second[2])}).")

    # ── jobs ─────────────────────────────────────────────────────────────
    flags["jobs"] = False
    if "jobs" in T:
        jobs = _by_year(T["jobs"], {"companies": "משרות בחברות העוסקות במו\"פ", "rd": "משרות במו\"פ",
                                    "phd": "תואר שלישי", "ba": "תואר ראשון", "tech": "הנדסאים",
                                    "oth": "מועסקים אחרים", "women": "משרות נשים"})
        jy = sorted(jobs)
        J = jobs[jy[-1]]["cats"]
        jt = J.get("total")
        if jt and jt["rd"] is not None:
            JY = jy[-1]
            kpis["jobs"] = {"value": _r(jt["rd"], 1), "display": fmt.num_he(jt["rd"], 1), "tone": "brand"}
            labels["jobs_kpi"] = f"משרות במו\"פ במגזר העסקי, {JY} (אלפים)"
            ed = [("תואר שלישי ומעלה", jt["phd"]), ("תואר ראשון ושני (כולל מהנדסים)", jt["ba"]),
                  ("הנדסאים וטכנאים", jt["tech"]), ("מועסקים אחרים", jt["oth"])]
            ed = [(n, v) for n, v in ed if v is not None]
            if len(ed) >= 3:
                flags["jobs"] = True
                charts["jobs"] = {"names": [n for n, _ in ed], "values": [_r(v, 2) for _, v in ed]}
                tables["jobs"] = [[n, fmt.num_he(v, 1), fmt.pct(v / jt["rd"])] for n, v in ed]
                labels["jobs_aria"] = f"משרות במו\"פ במגזר העסקי לפי השכלה, {JY}"
                labels["jobs_note"] = (f"{fmt.num_he(jt['rd'], 1)} אלף משרות במו\"פ ב-{JY}, מתוך "
                                       f"{fmt.num_he(jt['companies'], 1)} אלף משרות בכל החברות העוסקות במו\"פ, "
                                       f"לפי השכלת העובדים (באלפים)." if jt["companies"] else
                                       f"משרות במו\"פ ב-{JY} לפי השכלת העובדים, באלפים.")
            # women by category
            wrows = [(CAT_NAME[k], J[k]["women"] / J[k]["rd"]) for k in ("total",) + TYPE_KEYS + IND_KEYS
                     if k in J and J[k]["women"] is not None and J[k]["rd"]]
            flags["women"] = len(wrows) >= 4
            if jt["women"] is not None:
                ws = jt["women"] / jt["rd"]
                kpis["women"] = {"value": _r(ws * 100, 1), "display": fmt.pct(ws),
                                 "tone": "warn" if ws < 0.3 else "brand"}
                labels["women_kpi"] = f"חלק הנשים במשרות המו\"פ, {JY}"
                txt = (f"נשים מחזיקות {fmt.pct(ws)} ממשרות המו\"פ במגזר העסקי ({fmt.num_he(jt['women'], 1)} "
                       f"אלף מתוך {fmt.num_he(jt['rd'], 1)} אלף ב-{JY})")
                if flags["women"]:
                    lo = min(wrows[1:], key=lambda w: (w[1], w[0]))
                    hi = max(wrows[1:], key=lambda w: (w[1], w[0]))
                    if hi[1] - lo[1] >= 0.05:
                        txt += f". הכי הרבה ב{hi[0]} ({fmt.pct(hi[1])}), הכי מעט ב{lo[0]} ({fmt.pct(lo[1])})"
                add("women", txt + ".")
            if flags["women"]:
                charts["women"] = {"names": [n for n, _ in wrows], "values": [_r(v * 100, 1) for _, v in wrows]}
                tables["women"] = [[n, fmt.pct(v)] for n, v in wrows]
                labels["women_aria"] = f"חלק הנשים במשרות המו\"פ לפי סוג חברה וענף, {JY}"

    # ── activity fields ─────────────────────────────────────────────────
    flags["fields"] = False
    if "fields" in T:
        _title, rows = _latest(T["fields"])
        t0 = _first_row(rows, _is_total)
        if t0 is None:
            raise ValueError(f"{_title}: total row not found")
        fy, _ = _year_of(rows, t0)
        c_tot = _hcol(rows, t0, "סך הכל", exact=True)
        ftot = cbs.val(rows[t0], c_tot)
        items = []
        for r in rows[t0 + 1:]:
            lbl, v = cbs.cell(r, 0), cbs.val(r, c_tot)
            if not lbl or NOTE.match(lbl) or v is None:
                continue
            items.append((lbl, v))
        other = [(n, v) for n, v in items if n.startswith("תחומים אחרים")]
        named = sorted([(n, v) for n, v in items if not n.startswith("תחומים אחרים")],
                       key=lambda nv: (-nv[1], nv[0]))
        if len(named) >= 3 and ftot:
            flags["fields"] = True
            bars = named + other
            charts["fields"] = {"names": [_short(n) for n, _ in bars], "values": [_r(v / 1000, 2) for _, v in bars],
                                "other": bool(other)}
            tables["fields"] = [[n, _bn(v), fmt.pct(v / ftot)] for n, v in bars]
            labels["fields_aria"] = f"הוצאות שוטפות למו\"פ פנימי לפי תחום הפעילות, {fy}"
            labels["fields_note"] = (f"על מה עובדים: ההוצאות השוטפות למו\"פ פנימי ב-{fy} לפי תחום הפעילות "
                                     f"של המו\"פ (לא לפי הענף של החברה), במיליארדי ₪.")
            n0, v0 = named[0]
            if v0 / ftot >= 0.3:
                txt = f"{n0} הוא תחום המו\"פ הגדול ביותר: {fmt.pct(v0 / ftot)} מההוצאות השוטפות למו\"פ פנימי ב-{fy}"
                if len(named) > 1:
                    txt += f", ואחריו {named[1][0]} ({fmt.pct(named[1][1] / ftot)})"
                add("software", txt + ".")

    # ── industries ──────────────────────────────────────────────────────
    flags["ind"] = False
    if "ind" in T:
        _title, rows = _latest(T["ind"])
        hdr = None
        for i, r in enumerate(rows):
            if any(_is_total(c) for c in r):
                hdr = i
                break
        if hdr is None:
            raise ValueError(f"{_title}: total row not found")
        iy, _ = _year_of(rows, hdr)
        c_name = _hcol(rows, hdr, "ענף כלכלי", start=0)
        c_code = _hcol(rows, hdr, "סמל", start=0, exact=True)
        c_int = _hcol(rows, hdr, "מו\"פ פנימי", exact=True)
        c_iia = _hcol(rows, hdr, "מימון מרשות החדשנות")
        ijobs = {}
        if "indjobs" in T:
            _tj, jr = _latest(T["indjobs"])
            jh = None
            for i, r in enumerate(jr):
                if any(_is_total(c) for c in r):
                    jh = i
                    break
            if jh is None:
                raise ValueError(f"{_tj}: total row not found")
            jn = _hcol(jr, jh, "ענף כלכלי", start=0)
            jc = _hcol(jr, jh, "מספר משרות במו\"פ")
            for r in jr[jh + 1:]:
                n = cbs.cell(r, jn)
                if n and cbs.val(r, jc) is not None:
                    ijobs.setdefault(n, cbs.val(r, jc))
        items = []
        for r in rows[hdr + 1:]:
            n, code = cbs.cell(r, c_name), cbs.cell(r, c_code)
            if not n or not HEB.search(n) or "סך הכל" in n or code.startswith("מזה"):
                continue
            v = cbs.val(r, c_int)
            if v is None:
                continue
            items.append((n, v, cbs.val(r, c_iia), ijobs.get(n)))
        if len(items) >= 4:
            flags["ind"] = True
            items.sort(key=lambda it: (it[0].startswith("ענפים אחרים"), -it[1], it[0]))
            itot = cbs.val(rows[hdr], c_int)
            charts["ind"] = {"names": [_short(it[0], 34) for it in items],
                             "values": [_r(it[1] / 1000, 2) for it in items]}
            tables["ind"] = [[it[0], _bn(it[1]), fmt.pct(it[1] / itot) if itot else "–",
                              _t(it[3], 1), _t(it[2], 0)] for it in items]
            labels["ind_aria"] = f"ההוצאה למו\"פ פנימי לפי ענף כלכלי, {iy}"
            labels["ind_note"] = (f"ההוצאה למו\"פ פנימי ב-{iy} לפי הענף הכלכלי של החברה, במיליארדי ₪. "
                                  f"ענפים שהנתון שלהם חסוי או לא אמין (טעות דגימה גבוהה) אינם מוצגים.")

    # ── financing ───────────────────────────────────────────────────────
    flags["fin"] = False
    if "fin" in T:
        _title, rows = _latest(T["fin"])
        t0 = _first_row(rows, _is_total)
        if t0 is None:
            raise ValueError(f"{_title}: total row not found")
        fy, _ = _year_of(rows, t0)
        c_ext = _hcol(rows, t0, "סך כל המימון מגורמים חיצוניים")
        c_pe = _hcol(rows, t0, "מהון פרטי")
        c_vc = _hcol(rows, t0, "הון סיכון")
        c_gov = _hcol(rows, t0, "סך כל המימון ממקורות ממשלתיים")
        c_iia = _hcol(rows, t0, "רשות החדשנות")
        c_int = _hcol(rows, t0, "סך כל המימון מגורמים פנימיים")
        c_grp = _hcol(rows, t0, "מקבוצת החברות")
        c_own = _hcol(rows, t0, "ממקורות עצמיים")
        c_all = _hcol(rows, t0, "סך כל המימון של פעילות")
        tr = rows[t0]
        v = {k: cbs.val(tr, c) for k, c in (("ext", c_ext), ("pe", c_pe), ("vc", c_vc), ("gov", c_gov),
                                             ("iia", c_iia), ("int", c_int), ("grp", c_grp),
                                             ("own", c_own), ("all", c_all))}
        if all(x is not None for x in v.values()) and v["all"]:
            flags["fin"] = True
            src = [("מקבוצת החברות שהחברה שייכת אליה", v["grp"]), ("ממקורות עצמיים של החברה", v["own"]),
                   ("מקרנות הון סיכון", v["vc"]), ("מהון פרטי (בעלים ואנג'לים)", v["pe"]),
                   ("ממקורות חיצוניים פרטיים אחרים", v["ext"] - v["pe"] - v["vc"]),
                   ("מרשות החדשנות", v["iia"]), ("ממקורות ממשלתיים ובין-לאומיים אחרים", v["gov"] - v["iia"])]
            src = [(n, x) for n, x in src if x >= 0]
            charts["fin"] = {"names": [n for n, _ in src], "values": [_r(x / 1000, 2) for _, x in src]}
            tables["fin"] = [[n, _bn(x), fmt.pct(x / v["all"])] for n, x in src]
            labels["fin_aria"] = f"מקורות המימון של ההוצאה למו\"פ במגזר העסקי, {fy}"
            labels["fin_note"] = (f"מי מממן את המו\"פ: סך ההוצאה למו\"פ ב-{fy} לפי מקור המימון, "
                                  f"במיליארדי ₪. \"מקורות חיצוניים פרטיים אחרים\" ו\"מקורות ממשלתיים "
                                  f"ובין-לאומיים אחרים\" הם היתרה אחרי הסעיפים שהלמ\"ס מפרטת.")
            add("fin", f"{fmt.pct(v['int'] / v['all'], 0)} מההוצאה למו\"פ במגזר העסקי ב-{fy} מומנו מתוך החברות "
                       f"עצמן או מקבוצת החברות שלהן. קרנות הון סיכון מימנו {fmt.pct(v['vc'] / v['all'])}, "
                       f"ורשות החדשנות {fmt.pct(v['iia'] / v['all'])}.")
            # internal share by company type (always published)
            cats, _s = _cat_rows(rows, t0)
            irows = [(CAT_NAME[k], cbs.val(cats[k], c_int) / cbs.val(cats[k], c_all))
                     for k in TYPE_KEYS + IND_KEYS
                     if k in cats and cbs.val(cats[k], c_int) is not None and cbs.val(cats[k], c_all)]
            flags["finint"] = len(irows) >= 3
            if flags["finint"]:
                charts["finint"] = {"names": [n for n, _ in irows], "values": [_r(x * 100, 1) for _, x in irows]}
                tables["finint"] = [[n, fmt.pct(x)] for n, x in irows]
                labels["finint_aria"] = f"חלק המימון הפנימי בהוצאה למו\"פ לפי סוג חברה וענף, {fy}"

    # ── sales of R&D ────────────────────────────────────────────────────
    flags["sales"] = False
    if "sales" in T:
        sales = _by_year(T["sales"], {"sales": "הכנסות ממכירות", "export": "מזה: יצוא",
                                      "rd": "מזה: סך כל ההכנסות ממכירות מו\"פ",
                                      "rdx": "מזה: הכנסות ממכירות מו\"פ ליצוא"})
        sy = sorted(sales)
        S = sales[sy[-1]]["cats"]
        st = S.get("total")
        keys = [k for k in IND_KEYS + ("isr", "frn", "ctr") if k in S and S[k]["rd"] is not None]
        if st and st["rd"] and len(keys) >= 3:
            flags["sales"] = True
            SY = sy[-1]
            charts["sales"] = {"names": [CAT_NAME[k] for k in keys],
                               "rd": [_r(S[k]["rd"] / 1000, 2) for k in keys],
                               "rdx": [_r(S[k]["rdx"] / 1000, 2) if S[k]["rdx"] is not None else None
                                       for k in keys]}
            tables["sales"] = [[CAT_NAME[k], _t(S[k]["sales"] / 1000 if S[k]["sales"] is not None else None),
                                _t(S[k]["export"] / 1000 if S[k]["export"] is not None else None),
                                _bn(S[k]["rd"]),
                                _t(S[k]["rdx"] / 1000 if S[k]["rdx"] is not None else None)] for k in keys]
            labels["sales_aria"] = f"הכנסות ממכירות מו\"פ לפי ענף וסוג חברה, {SY}"
            labels["sales_note"] = (f"חלק מהחברות מוכרות את המו\"פ עצמו, לרוב לחברת האם בחו\"ל. ההכנסות "
                                    f"ממכירות מו\"פ ב-{SY} ומתוכן מכירות לחו\"ל, במיליארדי ₪. הקבוצות "
                                    f"חופפות חלקית.")
            if "ctr" in S and S["ctr"]["rd"]:
                s = S["ctr"]["rd"] / st["rd"]
                if s >= 0.4:
                    add("sales", f"מרכזי המו\"פ של חברות זרות מכרו ב-{SY} מו\"פ ב-{_bn(S['ctr']['rd'])} "
                                 f"מיליארד ₪, {fmt.pct(s, 0)} מכל ההכנסות ממכירות מו\"פ במגזר העסקי "
                                 f"({_bn(st['rd'])} מיליארד ₪).")

    # ── district labour cost ────────────────────────────────────────────
    flags["district"] = False
    if "district" in T:
        _title, rows = T["district"][0]
        pts, nat = [], None
        for r in rows[1:]:
            n, v = cbs.cell(r, 0), cbs.val(r, 1)
            if not n or v is None or not HEB.search(n):
                continue
            if "בכל הארץ" in n or "סך" in n:
                nat = v
            else:
                pts.append((n, v))
        if len(pts) >= 3:
            flags["district"] = True
            dy = YEAR_IN.findall(TITLE.sub("", _title))
            dy = dy[0] if dy else ""
            pts.sort(key=lambda p: (-p[1], p[0]))
            charts["district"] = {"names": [p[0] for p in pts], "values": [_r(p[1], 0) for p in pts],
                                  "nat": _r(nat, 0)}
            tables["district"] = [[p[0], fmt.int_he(p[1])] for p in pts] + (
                [["בכל הארץ", fmt.int_he(nat)]] if nat is not None else [])
            labels["district_aria"] = f"עלות העבודה השנתית למשרה מלאה במו\"פ לפי מחוז{', ' + dy if dy else ''}"
            labels["district_note"] = ("עלות העבודה השנתית הממוצעת למשרה מלאה במו\"פ לפי המחוז, באלפי ₪"
                                       + (f", {dy}." if dy else "."))
            hi, lo = pts[0], pts[-1]
            if hi[1] - lo[1] >= 50:
                add("district", f"משרת מו\"פ יקרה במיוחד במחוז {hi[0]}: {fmt.int_he(hi[1])} אלף ₪ בשנה בממוצע, "
                                f"לעומת {fmt.int_he(lo[1])} אלף ₪ במחוז {lo[0]}"
                                + (f" ו-{fmt.int_he(nat)} אלף ₪ בכל הארץ." if nat is not None else "."))

    # ── research type ───────────────────────────────────────────────────
    flags["rtype"] = False
    if "rtype" in T:
        _title, rows = T["rtype"][0]
        hi_ = None
        for i, r in enumerate(rows):
            if any("מחקר בסיסי" in c for c in r):
                hi_ = i
                break
        if hi_ is None:
            raise ValueError(f"{_title}: research-type header not found")
        cb = cbs.col_after(rows[hi_], "מחקר בסיסי", contains=True)
        ca = cbs.col_after(rows[hi_], "מחקר יישומי", contains=True)
        cd = cbs.col_after(rows[hi_], "פיתוח", contains=True)
        pts = []
        for r in rows[hi_ + 1:]:
            n = cbs.cell(r, 0)
            b, a, d = cbs.val(r, cb), cbs.val(r, ca), cbs.val(r, cd)
            if (n and HEB.search(n) and None not in (b, a, d) and 0.98 <= b + a + d <= 1.02
                    and n not in [p[0] for p in pts]):
                pts.append((n, b, a, d))
        if len(pts) >= 2:
            flags["rtype"] = True
            ry = YEAR_IN.findall(TITLE.sub("", _title))
            ry = ry[0] if ry else ""
            charts["rtype"] = {"names": [p[0] for p in pts], "basic": [_r(p[1] * 100) for p in pts],
                               "applied": [_r(p[2] * 100) for p in pts], "dev": [_r(p[3] * 100) for p in pts]}
            tables["rtype"] = [[p[0], fmt.pct(p[1]), fmt.pct(p[2]), fmt.pct(p[3])] for p in pts]
            labels["rtype_aria"] = f"הוצאות שוטפות למו\"פ פנימי לפי סוג המחקר וסוג החברה{', ' + ry if ry else ''}"
            tot_r = [p for p in pts if _is_total(p[0])]
            if tot_r and tot_r[0][3] >= 0.5:
                p = tot_r[0]
                add("dev", f"{fmt.pct(p[3], 0)} מההוצאות השוטפות למו\"פ במגזר העסקי הן פעילות פיתוח, "
                           f"{fmt.pct(p[2])} מחקר יישומי ורק {fmt.pct(p[1])} מחקר בסיסי"
                           + (f" ({ry})." if ry else "."))

    # ── technology type ─────────────────────────────────────────────────
    flags["tech"] = False
    if "tech" in T:
        _title, rows = T["tech"][0]
        hi_ = None
        for i, r in enumerate(rows):
            if any("בינה מלאכותית" in c for c in r):
                hi_ = i
                break
        if hi_ is None:
            raise ValueError(f"{_title}: technology header not found")
        hrow = rows[hi_]
        tcols = [(j, c) for j, c in enumerate(hrow) if j > 0 and c and HEB.search(c)]
        pts = []
        for r in rows[hi_ + 1:]:
            n = cbs.cell(r, 0)
            vs = [cbs.val(r, j) for j, _ in tcols]
            if not n or not HEB.search(n) or None in vs or not (0.98 <= sum(vs) <= 1.02):
                continue
            if n not in [p[0] for p in pts]:
                pts.append((n, vs))
        if len(pts) >= 2 and len(tcols) >= 3:
            flags["tech"] = True
            ty = YEAR_IN.findall(TITLE.sub("", _title))
            ty = ty[0] if ty else ""
            names_t = [c for _, c in tcols]
            # named technologies first, the catch-alls ("אחרת", "לא ידוע") last
            order = sorted(range(len(names_t)),
                           key=lambda k: (("אחר" in names_t[k]) or ("לא ידוע" in names_t[k]),
                                          -pts[0][1][k], names_t[k]))
            charts["tech"] = {"rows": [_short(p[0], 26) for p in pts], "techs": [names_t[k] for k in order],
                              "series": [[_r(p[1][k] * 100) for p in pts] for k in order]}
            tables["tech"] = [[p[0]] + [fmt.pct(p[1][k]) for k in order] for p in pts]
            labels["tech_cols"] = ["ענף"] + [names_t[k] for k in order]
            labels["tech_aria"] = f"הוצאות שוטפות למו\"פ פנימי לפי סוג טכנולוגיה וענף{', ' + ty if ty else ''}"
            ai = [k for k in range(len(names_t)) if "בינה מלאכותית" in names_t[k]]
            if ai:
                k = ai[0]
                p0 = pts[0]
                lead = max(pts[1:], key=lambda p: (p[1][k], p[0])) if len(pts) > 1 else None
                txt = (f"בינה מלאכותית היא {fmt.pct(p0[1][k])} מההוצאות השוטפות למו\"פ ב{p0[0]}"
                       + (f" ({ty})" if ty else ""))
                if lead and lead[1][k] > p0[1][k]:
                    txt += f", ובענף {lead[0]} {fmt.pct(lead[1][k])}"
                add("ai", txt + ".")

    # ── insight card + callouts ──────────────────────────────────────────
    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    jobs_txt = (f", ובחברות העוסקות במו\"פ הועסקו {fmt.num_he(kpis['jobs']['value'], 1)} אלף משרות במו\"פ"
                if "jobs" in kpis else "")
    labels["lede"] = (f"כמה משקיעות החברות בישראל במחקר ופיתוח (מו\"פ), באילו ענפים ותחומים, מי מממן את "
                      f"זה וכמה אנשים עובדים בו. הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה "
                      f"(הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. בשנת {Y} הוציא המגזר העסקי "
                      f"{_bn(tot['total'])} מיליארד ₪ על מו\"פ{jobs_txt}.")
    labels["year"] = str(Y)

    spans = [y for y in ([int(charts["real"]["x"][0])] if flags["real"] else [])
             + ([int(charts["gdp"]["x"][0])] if flags["gdp"] else [])] or [Y]
    summary = (f"ההוצאה למחקר ופיתוח במגזר העסקי בישראל לפי הלמ\"ס: {_bn(tot['total'])} מיליארד ₪ ב-{Y}"
               + (f", {fmt.pct_of(gdp_last[1])} מהתמ\"ג" if gdp_last else "")
               + (f", {fmt.num_he(kpis['jobs']['value'], 1)} אלף משרות במו\"פ" if "jobs" in kpis else "")
               + ". לפי ענף, סוג חברה, מקור מימון והשוואה ל-OECD.")
    desc = (f"כמה מוציאות החברות בישראל על מו\"פ: {_bn(tot['total'])} מיליארד ₪ ב-{Y}"
            + (f", {fmt.pct_of(gdp_last[1])} מהתמ\"ג" if gdp_last else "")
            + ". לפי ענף, חברות זרות והזנק, מימון ועובדים.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "misc",
            "temporal_coverage": f"{min(spans)}/{Y}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "הוצאה למו\"פ במגזר העסקי בישראל | נתוני הלמ\"ס",
                "description": desc,
                "name": "ההוצאה למחקר ופיתוח במגזר העסקי",
                "alternate_names": ["מו\"פ במגזר העסקי", "השקעה במחקר ופיתוח בחברות בישראל",
                                    "הוצאה למו\"פ כאחוז מהתמ\"ג", "עובדי מו\"פ בישראל",
                                    "מרכזי מו\"פ של חברות זרות"],
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
