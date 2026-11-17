"""ההוצאה הלאומית לתרבות, לבידור ולספורט: CBS's yearly release.

The release is a set of Excel tables ("לוח N.") and chart-data sheets
("תרשים N -"). CBS renumbers and drops them between editions (the 2023 and
2024 editions carried only tables 1-2 plus four chart sheets), so every
table is found by its Hebrew title, never by its stem, and a table the
newest edition lacks drops its section. A recognised table whose header
labels are gone raises.

Cells are read by label: column meaning from the English header text joined
down the column, row meaning from the English label in the first column
(two-line labels are joined), year blocks from a row that holds only a year.
"""
import itertools
import re

import pandas as pd
from govlib import cbs, fmt

STEMS = [f"t{i}" for i in range(1, 16)]
HEB = re.compile(r"[א-ת]")
TITLE = re.compile(r"^(לוח|תרשים) ?\d+")

# Table kinds, by words of the Hebrew title (first rows of the sheet).
KINDS = [
    ("act_year", "לוח", ["לפי סוג הוצאה ופעילות"], []),
    ("fin_year", "לוח", ["ומימונה"], []),
    ("oper_real", "לוח", ["לפי מגזר מבצע", "במחירים קבועים"], []),
    ("act_oper", "לוח", ["לפי סוג פעילות", "ומגזר מבצע"], []),
    ("business", "לוח", ["שסופקו על ידי"], []),
    ("gov_npi", "לוח", ["הוצאה של המגזר הממשלתי"], []),
    ("act_fin", "לוח", ["ומגזר מממן"], ["הרכב מימון"]),
    ("gdp", "תרשים", ["כאחוז מהתמ"], []),
    ("per_capita", "תרשים", ["לנפש"], []),
]

# Column keys of the activity × year table (table 1), by English header text.
ACT_YEAR_COLS = [("GDP", "gdp"), ("General administration", "admin"), ("Gambling", "gambling"),
                 ("Environmental", "environment"), ("Sports", "sports"), ("Socio", "socio"),
                 ("Radio", "radio"), ("Music", "music"), ("heritage", "heritage"),
                 ("Fixed", "investment"), ("Grand", "grand"), ("Total", "current_total")]
ACT_YEAR_ACTS = ["sports", "socio", "music", "radio", "heritage", "environment", "gambling", "admin"]

# Row keys (lower-case English label) shared by the activity cross tables.
ROW_KEYS = [("grand total", "grand"), ("current expenditure", "current"),
            ("current consumption", "current"), ("consumption of fixed", "depreciation"),
            ("fixed capital", "investment"), ("cultural heritage", "heritage"),
            ("literature", "literature"), ("music", "music"), ("visual", "visual"),
            ("cinema", "cinema"), ("radio", "radio"), ("socio", "socio"), ("sports", "sports"),
            ("computers", "computers"), ("environmental", "environment"), ("gambling", "gambling"),
            ("general administration", "admin"), ("labour", "labour"),
            ("current purchases", "purchases"), ("sales to households", "sales"),
            ("buildings", "buildings"), ("machinery", "machinery"),
            ("total - nis", "amount"), ("percentages", "type_share")]
AGG_ROWS = {"grand", "current", "investment", "amount", "type_share", "total"}

SECTOR_HE = {"business": "מגזר עסקי", "npi_private": "מלכ\"רים פרטיים", "npi_gov": "מלכ\"רים ממשלתיים",
             "npi": "מלכ\"רים", "local": "רשויות מקומיות", "gov": "ממשלה ומוסדות לאומיים",
             "households": "משקי בית"}
# verb "cover" and "their" agreeing with each sector's name
SECTOR_COVER = {"business": ("מכסה", "שלו"), "local": ("מכסות", "שלהן")}


# ── grid helpers ─────────────────────────────────────────────────────────


def _is_num(v):
    return cbs.num(v) is not None and not HEB.search(v)


def _segments(rows):
    """Split a grid at its title rows ("לוח 1." / "TABLE 1." on a new sheet)."""
    segs, cur = [], []
    for r in rows:
        if any(TITLE.match(c) for c in r) and cur and any(any(TITLE.match(c) for c in x) for x in cur):
            segs.append(cur)
            cur = []
        cur.append(r)
    if cur:
        segs.append(cur)
    return segs


def _title_text(rows):
    head = rows[:9]
    return " | ".join(c for r in head for c in r if c)


def _title_kind(rows):
    titles = [c for r in rows[:9] for c in r if TITLE.match(c)]
    if not titles:
        return None
    text = _title_text(rows)
    for kind, word, need, avoid in KINDS:
        if titles[0].startswith(word) and all(n in text for n in need) and not any(a in text for a in avoid):
            return kind
    return None


def _tables(frames):
    """{kind: (stem, rows)} for the newest edition, first stem wins."""
    found = {}
    for stem in STEMS:
        df = frames.get(stem)
        if df is None or df.empty:
            continue
        rows = cbs.grid(df, stem)
        kind = _title_kind(rows)
        if kind and kind not in found:
            found[kind] = (stem, rows)
    return found


def _col_text(rows, j):
    return " ".join(cbs.cell(r, j) for r in rows if cbs.cell(r, j))


def _col_map(head, keys, width):
    """{key: column index} from header rows, by the first key each column's
    joined text contains (keys in priority order)."""
    out = {}
    for j in range(1, width):
        t = _col_text(head, j)
        for needle, key in keys:
            if needle in t:
                out.setdefault(key, j)
                break
    return out


def _heb_label(head, j):
    parts = [cbs.cell(r, j) for r in head if HEB.search(cbs.cell(r, j))]
    s = " ".join(p for p in parts if p != "מזה:")
    return re.sub(r"\s*-\s+", "-", s).strip(" ,")


def _year_of(v):
    v = cbs.clean(v)
    return int(v) if cbs.YEAR.match(v) else None


def _year_marker(r):
    cells = [c for c in r if c]
    return _year_of(cells[0]) if len(cells) == 1 else None


def _row_key(eng):
    e = eng.lower()
    for needle, key in ROW_KEYS:
        if needle in e:
            return key
    if e.strip() == "total":
        return "total"
    return e.strip()


def _width(rows):
    return max((len(r) for r in rows), default=0)


# ── table parsers ────────────────────────────────────────────────────────


def _act_year(rows):
    """Table 1: {"nominal"|"real": {year: {col: value}}}, {col: Hebrew label}."""
    out = {"nominal": {}, "real": {}}
    labels = {}
    width = _width(rows)
    for seg in _segments(rows):
        ycol = cbs.best_col(seg, lambda v: bool(cbs.YEAR.match(v)))
        if ycol is None:
            continue
        first = next((i for i, r in enumerate(seg) if _year_of(cbs.cell(r, ycol))), len(seg))
        head = seg[:first]
        cols = _col_map(head, ACT_YEAR_COLS, width)
        if not cols:
            continue
        for k, j in cols.items():
            labels.setdefault(k, _heb_label(head, j))
        mode = None
        for r in seg:
            y = _year_of(cbs.cell(r, ycol))
            if y is None:
                text = " ".join(r)
                if "current prices" in text or "במחירים שוטפים" in text:
                    mode = "nominal"
                elif re.search(r"at \d{4} prices|במחירי \d{4}", text):
                    mode = "real"
                elif "שינוי" in text or "Percentage" in text or "אחוזים" in text:
                    mode = None
                continue
            if mode is None:
                continue
            vals = {k: cbs.val(r, j) for k, j in cols.items()}
            if vals.get("grand") is None:
                continue
            out[mode].setdefault(y, vals)
    if not out["nominal"]:
        raise ValueError("act_year: no nominal (current prices) year rows")
    for need in ("grand", "current_total"):
        if need not in next(iter(out["nominal"].values())):
            raise ValueError(f"act_year: column {need} not found")
    return out, labels


def _year_series(rows):
    """Chart-data sheet: {year: value} from the year column and the most
    numeric other column."""
    ycol = cbs.best_col(rows, lambda v: bool(cbs.YEAR.match(v)))
    if ycol is None:
        raise ValueError("chart data: no year column")
    vcol = cbs.best_col([r for r in rows if _year_of(cbs.cell(r, ycol))],
                        lambda v: _is_num(v), exclude={ycol})
    if vcol is None:
        raise ValueError("chart data: no value column")
    out = {}
    for r in rows:
        y = _year_of(cbs.cell(r, ycol))
        v = cbs.val(r, vcol)
        if y is not None and v is not None:
            out.setdefault(y, v)
    return out


OPER_COLS = [("Business", "business"), ("Non-profit", "npi"), ("Local", "local"),
             ("Government", "gov"), ("total", "total")]


def _oper_real(rows):
    """Table 3: {year: {sector: value}} at constant prices (levels only)."""
    ycol = cbs.best_col(rows, lambda v: bool(cbs.YEAR.match(v)))
    if ycol is None:
        raise ValueError("oper_real: no year column")
    first = next(i for i, r in enumerate(rows) if _year_of(cbs.cell(r, ycol)))
    cols = _col_map(rows[:first], OPER_COLS, _width(rows))
    for need in ("business", "npi", "local", "gov", "total"):
        if need not in cols:
            raise ValueError(f"oper_real: column {need} not found")
    base = re.search(r"במחירי (\d{4})", _title_text(rows[:first + 1]) + " " + " ".join(
        c for r in rows[:first] for c in r))
    out = {}
    for r in rows[first:]:
        if any("שינוי" in c or "change" in c for c in r):
            break
        y = _year_of(cbs.cell(r, ycol))
        if y is None:
            continue
        vals = {k: cbs.val(r, j) for k, j in cols.items()}
        if vals["total"] is not None:
            out[y] = vals
    return out, (base.group(1) if base else None)


FIN_COLS = [("Non-profit", "npi"), ("Local", "local"), ("Government", "gov"),
            ("Households", "households"), ("Grand total", "total")]


def _fin_year(rows):
    """Table 2: {year: {financing sector: value}} (financing side only)."""
    h = cbs.row_with(rows, "Financing sector", name="fin_year", contains=True)
    op = cbs.col_after(rows[h], "Operating sector", contains=True)
    ycol = cbs.best_col(rows, lambda v: bool(cbs.YEAR.match(v)))
    first = next(i for i, r in enumerate(rows) if i > h and _year_of(cbs.cell(r, ycol)))
    cols = {k: j for k, j in _col_map(rows[h:first], FIN_COLS, op).items()}
    for need in ("npi", "local", "gov", "households", "total"):
        if need not in cols:
            raise ValueError(f"fin_year: column {need} not found")
    out = {}
    for r in rows[first:]:
        y = _year_of(cbs.cell(r, ycol))
        if y is None:
            if any(c and not _is_num(c) for c in r):
                break
            continue
        vals = {k: cbs.val(r, j) for k, j in cols.items()}
        if vals["total"]:
            out[y] = vals
    return out


def _cross(rows, colkeys, need):
    """A year-blocked cross table (activity × sector): {year: {rowkey:
    {colkey: value}}} and {rowkey: Hebrew label}."""
    width = _width(rows)
    hdr_end = next((i for i, r in enumerate(rows) if _year_marker(r)), None)
    if hdr_end is None:
        raise ValueError("cross table: no year block")
    cols = _col_map(rows[:hdr_end], colkeys, width)
    for k in need:
        if k not in cols:
            raise ValueError(f"cross table: column {k} not found")
    out, labels = {}, {}
    year, eng, heb = None, "", ""
    for r in rows[hdr_end:]:
        y = _year_marker(r)
        if y:
            year, eng, heb = y, "", ""
            out.setdefault(year, {})
            continue
        nums = [cbs.val(r, j) for j in cols.values()]
        has_num = any(cbs.cell(r, j) and (_is_num(cbs.cell(r, j)) or cbs.cell(r, j) in cbs.MISSING)
                      for j in cols.values())
        e = cbs.cell(r, 0) if not _is_num(cbs.cell(r, 0)) else ""
        last = next((c for c in reversed(r) if c), "")
        hpart = last if HEB.search(last) else ""
        if not has_num:
            eng = (eng + " " + e).strip()
            heb = (heb + " " + hpart).strip()
            continue
        label_e = (eng + " " + e).strip()
        label_h = re.sub(r"\s*-\s+", "-", (heb + " " + hpart).strip())
        eng, heb = "", ""
        if year is None or not label_e or all(v is None for v in nums):
            continue
        key = _row_key(label_e)
        if key in out[year]:
            continue
        out[year][key] = {k: cbs.val(r, j) for k, j in cols.items()}
        labels.setdefault(key, label_h.replace("פחות: ", "") or label_e)
    out = {y: v for y, v in out.items() if v}
    if not out:
        raise ValueError("cross table: no data rows")
    return out, labels


ACT_OPER_COLS = [("Private", "npi_private"), ("Business", "business"), ("Non-profit", "npi_gov"),
                 ("Local", "local"), ("Government", "gov"), ("Total", "total")]
ACT_FIN_COLS = [("Households", "households"), ("Non-profit", "npi"), ("Local", "local"),
                ("Government", "gov"), ("Total", "total")]
BUS_COLS = [("Services", "services"), ("Other", "other"), ("Durable", "durable"), ("Total", "total")]
GOV_COLS = [("Private", "npi_private"), ("Non-profit", "npi_gov"), ("Local", "local"),
            ("Government", "gov"), ("Total", "total")]


# ── formatting ───────────────────────────────────────────────────────────


def _bn(v):
    return fmt.num_he(v / 1000, 1)


def _m(v):
    return fmt.int_he(v)


def _r1(v):
    return None if v is None else round(float(v), 1)


def _r3(v):
    return None if v is None else round(float(v), 3)


def _sp(v100):
    """Signed percent from a 0-100 change."""
    return fmt.signed_pct(v100 / 100)


def _acts_sorted(d, keys):
    return sorted(keys, key=lambda k: (-(d.get(k) or 0), k))


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "act_year" not in tabs:
        raise ValueError("table 'לפי סוג הוצאה ופעילות' (national expenditure by activity) not found")

    ay, ay_labels = _act_year(tabs["act_year"][1])
    nom = ay["nominal"]
    years = sorted(nom)
    ly = years[-1]
    last = nom[ly]
    acts = [k for k in ACT_YEAR_ACTS if k in last]

    raw = frames[tabs["act_year"][0]]
    cells = raw[[c for c in raw.columns if re.fullmatch(r"C\d+", c)]].astype(str).values.ravel()
    provisional = any(re.fullmatch(rf"\s*\*?\s*{ly}\s*\*?\s*", c) and "*" in c for c in cells)
    ly_txt = f"{ly}" + (" (ארעי)" if provisional else "")

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    # ── totals: nominal + real ──────────────────────────────────────────
    grand = last["grand"]
    kpis["total"] = {"value": round(grand, 1), "display": _bn(grand), "tone": "brand"}
    labels["total_kpi"] = f"ההוצאה הלאומית לתרבות, לבידור ולספורט ב-{ly} (מיליארדי ש\"ח)"

    real, base = {}, None
    if "oper_real" in tabs:
        oper, base = _oper_real(tabs["oper_real"][1])
        real = {y: v["total"] for y, v in oper.items()}
    else:
        oper = {}
    if not real and ay["real"]:
        real = {y: v["grand"] for y, v in ay["real"].items()}
    ry = sorted(real)
    if len(ry) >= 2:
        flags["real"] = True
        chg = (real[ry[-1]] / real[ry[-2]] - 1) * 100
        kpis["real_change"] = {"value": round(chg, 2), "display": _sp(chg),
                               "tone": "ok" if chg >= 1 else ("danger" if chg <= -3 else
                                                              ("warn" if chg < 0 else "info"))}
        labels["real_change_kpi"] = f"שינוי ריאלי בהוצאה, {ry[-1]} לעומת {ry[-2]}"
        charts["real"] = {"x": [str(y) for y in ry], "y": [round(real[y]) for y in ry],
                          "nominal": [round(nom[y]["grand"]) if y in nom else None for y in ry]}
        tables["real"] = [[str(y), _m(real[y]), _m(nom[y]["grand"]) if y in nom else "–"]
                          for y in reversed(ry)]
        labels["real_base"] = base or ""
        labels["real_note"] = (f"ההוצאה הלאומית לתרבות, לבידור ולספורט בכל שנה מאז {ry[0]}, "
                               f"במחירים קבועים{' של ' + base if base else ''} (כלומר בניכוי עליית "
                               f"המחירים) ובמחירים שוטפים, במיליוני ש\"ח.")
        labels["real_aria"] = f"ההוצאה הלאומית לתרבות, לבידור ולספורט במחירים קבועים, {ry[0]} עד {ry[-1]}"
        labels["real_series"] = f"במחירי {base}" if base else "במחירים קבועים"
        # deepest fall
        yoy = [(y, (real[y] / real[p] - 1) * 100) for p, y in itertools.pairwise(ry)]
        worst = min(yoy, key=lambda t: (t[1], t[0]))
        if worst[1] <= -5:
            nxt = next((c for y, c in yoy if y == worst[0] + 1), None)
            s = (f"השנה הקשה ביותר בסדרה הייתה {worst[0]}: ההוצאה הלאומית לתרבות, לבידור ולספורט "
                 f"ירדה ריאלית ב-{fmt.num_he(-worst[1], 1)}%")
            if nxt is not None and nxt > 0:
                s += f", ובשנה שאחריה זינקה ב-{fmt.num_he(nxt, 1)}%"
            insights.append({"id": "worst", "text_he": s + "."})
        if worst[0] - 1 in real and ry[-1] > worst[0] + 1:
            pre = worst[0] - 1
            d = (real[ry[-1]] / real[pre] - 1) * 100
            if worst[1] <= -5 and abs(d) >= 1:
                insights.append({"id": "recovery", "text_he": (
                    f"במחירים קבועים, ההוצאה ב-{ly_txt} {'גבוהה' if d > 0 else 'נמוכה'} "
                    f"ב-{fmt.num_he(abs(d), 1)}% מזו של {pre}, השנה שלפני הירידה.")})

    # ── share of GDP ────────────────────────────────────────────────────
    gdp = _year_series(tabs["gdp"][1]) if "gdp" in tabs else {}
    if not gdp:
        gdp = {y: v["gdp"] for y, v in nom.items() if v.get("gdp") is not None}
    gy = sorted(gdp)
    if gy:
        g_last = gdp[gy[-1]]
        kpis["gdp"] = {"value": round(g_last, 2), "display": fmt.pct_of(g_last, 1), "tone": "info"}
        labels["gdp_kpi"] = f"ההוצאה כאחוז מהתמ\"ג ב-{gy[-1]}"
    if len(gy) >= 5:
        flags["gdp"] = True
        charts["gdp"] = {"x": [str(y) for y in gy], "y": [_r3(gdp[y]) for y in gy]}
        tables["gdp"] = [[str(y), fmt.pct_of(gdp[y], 2)] for y in reversed(gy)]
        peak = max(gy, key=lambda y: (gdp[y], -y))
        low = min(gy, key=lambda y: (gdp[y], y))
        labels["gdp_note"] = (f"איזה חלק מהתוצר המקומי הגולמי (תמ\"ג) הוצא על תרבות, בידור וספורט, "
                              f"בכל שנה מאז {gy[0]}.")
        labels["gdp_aria"] = f"ההוצאה לתרבות, לבידור ולספורט כאחוז מהתמ\"ג, {gy[0]} עד {gy[-1]}"
        if peak != gy[-1] and gdp[peak] - g_last >= 0.2:
            insights.append({"id": "gdp", "text_he": (
                f"ההוצאה לתרבות, לבידור ולספורט היא {fmt.pct_of(g_last, 2)} מהתמ\"ג ב-{gy[-1]}, "
                f"מתחת לשיא של {fmt.pct_of(gdp[peak], 2)} ב-{peak}"
                + (f"; השפל היה {fmt.pct_of(gdp[low], 2)} ב-{low}." if low not in (peak, gy[-1]) else "."))})

    # ── per capita ──────────────────────────────────────────────────────
    pc = _year_series(tabs["per_capita"][1]) if "per_capita" in tabs else {}
    py = sorted(pc)
    if len(py) >= 5:
        flags["pc"] = True
        charts["pc"] = {"x": [str(y) for y in py], "y": [_r1(pc[y]) for y in py]}
        tables["pc"] = [[str(y), _sp(pc[y])] for y in reversed(py)]
        labels["pc_note"] = (f"בכמה השתנתה ההוצאה לנפש, במחירים קבועים, בכל שנה לעומת השנה "
                             f"שלפניה, {py[0]} עד {py[-1]}. עמודה אדומה היא ירידה.")
        labels["pc_aria"] = f"שינוי שנתי בהוצאה לנפש לתרבות, לבידור ולספורט, {py[0]} עד {py[-1]}"
        recent = py[-5:]
        downs = [y for y in recent if pc[y] < 0]
        v = pc[py[-1]]
        s = (f"ההוצאה לנפש במחירים קבועים {'עלתה' if v > 0 else 'ירדה'} ב-{fmt.num_he(abs(v), 1)}% "
             f"ב-{py[-1]}") if abs(v) >= 0.05 else f"ההוצאה לנפש במחירים קבועים כמעט לא השתנתה ב-{py[-1]}"
        if len(downs) >= 2:
            s += f"; ב-{len(downs)} מתוך {len(recent)} השנים האחרונות ({recent[0]} עד {recent[-1]}) היא ירדה."
        else:
            s += "."
        insights.append({"id": "pc", "text_he": s})

    # ── activity mix over time (table 1, current prices) ────────────────
    charts["mix"] = {"x": [str(y) for y in years],
                     "names": [ay_labels.get(k, k) for k in acts],
                     "series": [[_r1(nom[y].get(k)) for y in years] for k in acts]}
    flags["mix"] = len(years) >= 3
    labels["mix_note"] = (f"ההוצאה השוטפת לפי תחום, במיליוני ש\"ח במחירים שוטפים, {years[0]} עד {ly}. "
                          f"לחיצה על שם תחום במקרא מסתירה או מציגה אותו.")
    labels["mix_aria"] = f"ההוצאה השוטפת לתרבות, לבידור ולספורט לפי תחום, {years[0]} עד {ly}"
    tables["mix_cols"] = ["שנה"] + [ay_labels.get(k, k) for k in acts]
    tables["mix"] = [[str(y)] + [_m(nom[y][k]) if nom[y].get(k) is not None else "–" for k in acts]
                     for y in reversed(years)]

    # share shift, first year vs latest
    fy = years[0]

    def share(y, k):
        tot = nom[y].get("current_total")
        v = nom[y].get(k)
        return v / tot * 100 if tot and v is not None else None

    shift = [(k, share(fy, k), share(ly, k)) for k in acts if share(fy, k) is not None and share(ly, k) is not None]
    shift.sort(key=lambda t: (-t[2], t[0]))
    if fy != ly and shift:
        flags["shift"] = True
        charts["shift"] = {"names": [ay_labels.get(k, k) for k, _, _ in shift],
                           "first": [_r1(a) for _, a, _ in shift], "last": [_r1(b) for _, _, b in shift],
                           "fy": str(fy), "ly": str(ly)}
        tables["shift"] = [[ay_labels.get(k, k), fmt.pct_of(a), fmt.pct_of(b)] for k, a, b in shift]
        labels["shift_cols"] = ["תחום", str(fy), str(ly)]
        labels["shift_note"] = (f"חלקו של כל תחום בהוצאה השוטפת ב-{fy} וב-{ly}. חלקים באחוזים "
                                f"אינם מושפעים מעליית המחירים, ולכן מראים איך השתנה תמהיל ההוצאה.")
        labels["shift_aria"] = f"חלק כל תחום בהוצאה השוטפת, {fy} מול {ly}"
        gain = max(shift, key=lambda t: (t[2] - t[1], t[0]))
        loss = min(shift, key=lambda t: (t[2] - t[1], t[0]))
        if gain[2] - gain[1] >= 2:
            s = (f"תחום {ay_labels.get(gain[0])} גדל מ-{fmt.pct_of(gain[1])} מההוצאה השוטפת ב-{fy} "
                 f"ל-{fmt.pct_of(gain[2])} ב-{ly}")
            if loss[1] - loss[2] >= 2:
                s += (f", ואילו {ay_labels.get(loss[0])} ירד מ-{fmt.pct_of(loss[1])} "
                      f"ל-{fmt.pct_of(loss[2])}")
            insights.append({"id": "shift", "text_he": s + "."})

    # investment
    inv = [(y, nom[y].get("investment")) for y in years if nom[y].get("investment") is not None]
    if len(inv) >= 3:
        flags["inv"] = True
        charts["inv"] = {"x": [str(y) for y, _ in inv], "y": [_r1(v) for _, v in inv]}
        tables["inv"] = [[str(y), _m(v), fmt.pct_of(v / nom[y]["grand"] * 100)] for y, v in reversed(inv)]
        labels["inv_note"] = (f"ההשקעה בנכסים קבועים (מבנים, אולמות, מתקני ספורט וציוד) בכל שנה, "
                              f"במיליוני ש\"ח במחירים שוטפים, {inv[0][0]} עד {inv[-1][0]}.")
        labels["inv_aria"] = f"השקעה בנכסים קבועים לתרבות, לבידור ולספורט, {inv[0][0]} עד {inv[-1][0]}"

    # ── activity detail, latest year (table 4) ──────────────────────────
    detail_year = None
    if "act_oper" in tabs:
        ao, ao_labels = _cross(tabs["act_oper"][1], ACT_OPER_COLS,
                               ["business", "npi_private", "npi_gov", "local", "gov", "total"])
        detail_year = max(ao)
        blk = ao[detail_year]
        items = [k for k in blk if k not in AGG_ROWS and blk[k].get("total")]
        items = _acts_sorted({k: blk[k]["total"] for k in items}, items)
        cur_tot = blk.get("current", {}).get("total") or sum(blk[k]["total"] for k in items)
        if items:
            flags["acts"] = True
            charts["acts"] = {"names": [ao_labels[k] for k in items],
                              "values": [_r1(blk[k]["total"]) for k in items]}
            tables["acts"] = [[ao_labels[k], _m(blk[k]["total"]), fmt.pct_of(blk[k]["total"] / cur_tot * 100)]
                              for k in items]
            labels["acts_note"] = (f"ההוצאה השוטפת ב-{detail_year} לפי תחום פעילות, במיליוני ש\"ח, "
                                   f"בפירוט של {len(items)} תחומים.")
            labels["acts_aria"] = f"ההוצאה השוטפת לתרבות, לבידור ולספורט לפי תחום, {detail_year}"
            top = items[0]
            sh = blk[top]["total"] / cur_tot * 100
            if sh >= 15:
                s = (f"התחום הגדול ביותר הוא {ao_labels[top]}: {_bn(blk[top]['total'])} מיליארד ש\"ח "
                     f"ב-{detail_year}, {fmt.pct_of(sh)} מההוצאה השוטפת")
                if len(items) > 1:
                    s += (f". אחריו {ao_labels[items[1]]} "
                          f"({_bn(blk[items[1]]['total'])} מיליארד ש\"ח)")
                insights.append({"id": "top_act", "text_he": s + "."})
            # who provides
            secs = ["business", "npi_private", "npi_gov", "local", "gov"]
            charts["oper_act"] = {"names": [ao_labels[k] for k in items],
                                  "sectors": [SECTOR_HE[s] for s in secs],
                                  "series": [[_r1(blk[k].get(s) or 0) for k in items] for s in secs]}
            tables["oper_act"] = [[ao_labels[k]] + [_m(blk[k][s]) if blk[k].get(s) else "–" for s in secs]
                                  for k in items]
            labels["oper_act_cols"] = ["תחום"] + [SECTOR_HE[s] for s in secs]
            labels["oper_act_note"] = (f"מי מספק את השירות או המוצר בכל תחום ב-{detail_year} (המגזר המבצע), "
                                       f"במיליוני ש\"ח.")
            labels["oper_act_aria"] = f"ההוצאה השוטפת לפי תחום ומגזר מבצע, {detail_year}"
            g = blk.get("grand")
            if g and g.get("business") and g.get("total"):
                bsh = g["business"] / g["total"] * 100
                local_top = max(items, key=lambda k: ((blk[k].get("local") or 0), k))
                insights.append({"id": "business", "text_he": (
                    f"המגזר העסקי מספק {fmt.pct_of(bsh)} מכל ההוצאה ב-{detail_year} "
                    f"({_bn(g['business'])} מיליארד ש\"ח). הרשויות המקומיות פעילות בעיקר "
                    f"בתחום {ao_labels[local_top]}.")})

    # ── who pays (table 7) ──────────────────────────────────────────────
    hh_share = None
    if "act_fin" in tabs:
        af, af_labels = _cross(tabs["act_fin"][1], ACT_FIN_COLS, ["households", "local", "gov", "total"])
        fy7 = max(af)
        blk = af[fy7]
        items = [k for k in blk if k not in AGG_ROWS and k != "admin" and (blk[k].get("total") or 0) > 0
                 and blk[k].get("households") is not None]
        pays = []
        for k in items:
            t = blk[k]["total"]
            hh = max(blk[k].get("households") or 0, 0)
            pub = max(blk[k].get("local") or 0, 0) + max(blk[k].get("gov") or 0, 0)
            pays.append((k, hh / t * 100, pub / t * 100))
        pays.sort(key=lambda t: (-t[1], t[0]))
        if pays:
            flags["pays"] = True
            charts["pays"] = {"names": [af_labels[k] for k, _, _ in pays],
                              "hh": [_r1(a) for _, a, _ in pays], "pub": [_r1(b) for _, _, b in pays]}
            tables["pays"] = [[af_labels[k], fmt.pct_of(a), fmt.pct_of(b)] for k, a, b in pays]
            labels["pays_note"] = (f"איזה חלק מההוצאה בכל תחום ב-{fy7} מומן בידי משקי הבית (קנייה, "
                                   f"כרטיסים, מנויים), ואיזה חלק בידי הממשלה והרשויות המקומיות. "
                                   f"ניהול כללי ופעולות לא מסווגות אינם מוצגים.")
            labels["pays_aria"] = f"חלק משקי הבית והמגזר הציבורי במימון כל תחום, {fy7}"
            pubtop = max(pays, key=lambda t: (t[2], t[0]))
            if 20 <= pubtop[2] <= 100 and pays[0][1] <= 100:
                insights.append({"id": "public", "text_he": (
                    f"התחום שהמגזר הציבורי מממן בחלק הגדול ביותר הוא {af_labels[pubtop[0]]}: "
                    f"{fmt.pct_of(pubtop[2])} ממנו מומנו ב-{fy7} בידי הממשלה והרשויות המקומיות, "
                    f"לעומת {fmt.pct_of(pays[0][1])} שמשקי הבית מימנו בתחום {af_labels[pays[0][0]]}.")})
        g = blk.get("grand")
        if g and g.get("total") and g.get("households") is not None:
            hh_share = g["households"] / g["total"] * 100

    # ── financing over time (table 2) ───────────────────────────────────
    if "fin_year" in tabs:
        fin = _fin_year(tabs["fin_year"][1])
        fyrs = sorted(fin)
        if len(fyrs) >= 3:
            flags["fin"] = True
            ks = ["households", "local", "gov"]
            charts["fin"] = {"x": [str(y) for y in fyrs], "names": [SECTOR_HE[k] for k in ks],
                             "series": [[_r1(fin[y][k] / fin[y]["total"] * 100) for y in fyrs] for k in ks]}
            tables["fin"] = [[str(y)] + [fmt.pct_of(fin[y][k] / fin[y]["total"] * 100) for k in ks]
                             + [_m(fin[y]["total"])] for y in reversed(fyrs)]
            labels["fin_cols"] = ["שנה"] + [SECTOR_HE[k] for k in ks] + ["סך המימון (מיליוני ש\"ח)"]
            labels["fin_note"] = (f"חלקו של כל מגזר מממן בהוצאה הלאומית לתרבות, לבידור ולספורט, "
                                  f"{fyrs[0]} עד {fyrs[-1]}. המלכ\"רים, שחלקם קטן ולעתים שלילי "
                                  f"(העברות נטו), אינם מוצגים.")
            labels["fin_aria"] = f"מימון ההוצאה הלאומית לתרבות לפי מגזר מממן, {fyrs[0]} עד {fyrs[-1]}"
            lf = fin[fyrs[-1]]
            if hh_share is None:
                hh_share = lf["households"] / lf["total"] * 100
            h0 = fin[fyrs[0]]["households"] / fin[fyrs[0]]["total"] * 100
            h1 = lf["households"] / lf["total"] * 100
            if abs(h1 - h0) >= 1:
                insights.append({"id": "households", "text_he": (
                    f"משקי הבית מימנו {fmt.pct_of(h1)} מההוצאה הלאומית לתרבות, לבידור ולספורט "
                    f"ב-{fyrs[-1]}, לעומת {fmt.pct_of(h0)} ב-{fyrs[0]}; חלק הרשויות המקומיות "
                    f"{fmt.pct_of(lf['local'] / lf['total'] * 100)} וחלק הממשלה "
                    f"{fmt.pct_of(lf['gov'] / lf['total'] * 100)}.")})
    if hh_share is not None:
        kpis["households"] = {"value": round(hh_share, 1), "display": fmt.pct_of(hh_share), "tone": "brand"}
        labels["households_kpi"] = "חלק משקי הבית במימון ההוצאה"

    # ── operating sector, real (table 3) ────────────────────────────────
    if oper and len(oper) >= 3:
        oy = sorted(oper)
        ks = ["business", "npi", "local", "gov"]
        flags["oper"] = True
        charts["oper"] = {"x": [str(y) for y in oy], "names": [SECTOR_HE[k] for k in ks],
                          "series": [[round(oper[y][k]) if oper[y][k] is not None else None for y in oy]
                                     for k in ks]}
        tables["oper"] = [[str(y)] + [_m(oper[y][k]) if oper[y][k] is not None else "–" for k in ks]
                          for y in reversed(oy)]
        labels["oper_cols"] = ["שנה"] + [SECTOR_HE[k] for k in ks]
        labels["oper_note"] = (f"ההוצאה לפי המגזר המבצע (מי סיפק את השירות או המוצר), במיליוני ש\"ח "
                               f"במחירים קבועים{' של ' + base if base else ''}, {oy[0]} עד {oy[-1]}.")
        labels["oper_aria"] = f"ההוצאה לתרבות, לבידור ולספורט לפי מגזר מבצע, {oy[0]} עד {oy[-1]}"
        a, b = oper[oy[0]], oper[oy[-1]]
        grow = {k: b[k] / a[k] for k in ks if a.get(k) and b.get(k)}
        if grow:
            fast = max(grow, key=lambda k: (grow[k], k))
            insights.append({"id": "oper", "text_he": (
                f"במחירים קבועים, ההוצאה הכוללת גדלה פי {fmt.num_he(b['total'] / a['total'], 1)} "
                f"בין {oy[0]} ל-{oy[-1]}; הצמיחה המהירה ביותר הייתה אצל "
                f"{SECTOR_HE[fast]} (פי {fmt.num_he(grow[fast], 1)}).")})

    # ── business sector: goods vs services (table 5) ────────────────────
    if "business" in tabs:
        bz, bz_labels = _cross(tabs["business"][1], BUS_COLS, ["services", "other", "durable", "total"])
        by = max(bz)
        blk = bz[by]
        amt = blk.get("amount")
        items = [k for k in blk if k not in AGG_ROWS]
        if amt and items and amt.get("total"):
            items = sorted(items, key=lambda k: (-(blk[k].get("total") or 0), k))
            types = ["services", "other", "durable"]
            type_he = {"services": "שירותים", "other": "מוצרים אחרים", "durable": "מוצרים בני-קיימה"}
            flags["bus"] = True
            charts["bus"] = {"types": [type_he[t] for t in types], "names": [bz_labels[k] for k in items],
                             "series": [[_r1(blk[k].get(t) or 0) for t in types] for k in items],
                             "amounts": [_r1(amt.get(t)) for t in types]}
            tables["bus"] = [[bz_labels[k]] + [fmt.pct_of(blk[k].get(t) or 0) for t in types] for k in items]
            labels["bus_cols"] = ["תחום"] + [type_he[t] for t in types]
            labels["bus_note"] = (f"על מה הוציאו בשנת {by} על מוצרים ושירותים שסיפק המגזר העסקי "
                                  f"({_bn(amt['total'])} מיליארד ש\"ח): לכל סוג (שירותים, מוצרים "
                                  f"בני-קיימה ומוצרים אחרים) חלקו של כל תחום באחוזים.")
            labels["bus_aria"] = f"הוצאה על מוצרים ושירותים מהמגזר העסקי לפי תחום, {by}"
            dur = max(items, key=lambda k: ((blk[k].get("durable") or 0), k))
            if (blk[dur].get("durable") or 0) >= 40:
                insights.append({"id": "durable", "text_he": (
                    f"{fmt.pct_of(blk[dur]['durable'])} מההוצאה על מוצרים בני-קיימה לפנאי ב-{by} "
                    f"הם {bz_labels[dur]}; בשירותים מוביל תחום "
                    f"{bz_labels[max(items, key=lambda k: ((blk[k].get('services') or 0), k))]}.")})

    # ── government and NPI cost structure (table 6) ─────────────────────
    if "gov_npi" in tabs:
        gv, gv_labels = _cross(tabs["gov_npi"][1], GOV_COLS, ["npi_private", "npi_gov", "local", "gov"])
        gy6 = max(gv)
        blk = gv[gy6]
        comps = [k for k in ["labour", "purchases", "depreciation", "sales"] if k in blk]
        secs = ["npi_private", "npi_gov", "local", "gov"]
        if len(comps) >= 3:
            flags["cost"] = True
            charts["cost"] = {"sectors": [SECTOR_HE[s] for s in secs], "names": [gv_labels[k] for k in comps],
                              "series": [[_r1(blk[k].get(s) or 0) for s in secs] for k in comps]}
            tables["cost"] = [[SECTOR_HE[s]] + [_m(blk[k][s]) if blk[k].get(s) is not None else "–" for k in comps]
                              for s in secs]
            labels["cost_cols"] = ["מגזר"] + [gv_labels[k] for k in comps]
            labels["cost_note"] = (f"ממה מורכבת ההוצאה של הממשלה, הרשויות המקומיות והמלכ\"רים על שירותי "
                                   f"תרבות, בידור וספורט ב-{gy6}, במיליוני ש\"ח: עלות העבודה, הקניות "
                                   f"השוטפות והבלאי, מול ההכנסות ממכירות למשקי בית.")
            labels["cost_aria"] = f"מבנה ההוצאה של הממשלה, הרשויות והמלכ\"רים על תרבות, {gy6}"
            if "sales" in blk and all(k in blk for k in ["labour", "purchases"]):
                rec = []
                for s in secs:
                    cost = sum(blk[k].get(s) or 0 for k in ["labour", "purchases", "depreciation"] if k in blk)
                    if cost > 0 and blk["sales"].get(s) is not None:
                        rec.append((s, blk["sales"][s] / cost * 100))
                if rec:
                    hi = max(rec, key=lambda t: (t[1], t[0]))
                    if hi[1] >= 20:
                        verb, their = SECTOR_COVER.get(hi[0], ("מכסים", "שלהם"))
                        insights.append({"id": "sales", "text_he": (
                            f"{SECTOR_HE[hi[0]]} {verb} {fmt.pct_of(hi[1])} מעלויות השירותים {their} "
                            f"ב-{gy6} ממכירות למשקי בית (כרטיסים, דמי מנוי ושכר לימוד), השיעור הגבוה "
                            f"ביותר מבין {len(rec)} המגזרים.")})

    # ── text ────────────────────────────────────────────────────────────
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    g_txt = f", {fmt.pct_of(gdp[gy[-1]], 1)} מהתמ\"ג" if gy and gy[-1] == ly else ""
    labels["lede"] = (f"כמה מוציאים בישראל על תרבות, בידור וספורט, על מה ומי משלם: משקי הבית, "
                      f"הממשלה, הרשויות המקומיות והמלכ\"רים. הנתונים מתוך ההודעה השנתית של הלשכה "
                      f"המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. ההוצאה הלאומית "
                      f"ב-{ly_txt}: {_bn(grand)} מיליארד ש\"ח{g_txt}.")
    labels["provisional"] = (f"נתוני {ly} ארעיים ועשויים להתעדכן בהודעה הבאה." if provisional else "")
    summary = (f"ההוצאה הלאומית לתרבות, לבידור ולספורט בישראל לפי הלמ\"ס: {_bn(grand)} מיליארד ש\"ח "
               f"ב-{ly}{g_txt}, לפי תחום (ספורט, מוזיקה, טלוויזיה, אינטרנט) ולפי מי שמממן.")
    desc = (f"כמה מוציאה ישראל על תרבות, בידור וספורט: {_bn(grand)} מיליארד ש\"ח ב-{ly}{g_txt}. "
            f"לפי תחום, מגזר ומי משלם, מאז {years[0] if not ry else min(ry[0], years[0])}.")
    tc_start = min([years[0]] + ry[:1] + gy[:1])
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{tc_start}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "הוצאה לאומית לתרבות, לבידור ולספורט | הלמ\"ס",
                "description": desc,
                "name": "ההוצאה הלאומית לתרבות, לבידור ולספורט",
                "alternate_names": ["הוצאה על תרבות בישראל", "תקציב התרבות והספורט",
                                    "ההוצאה על ספורט ופנאי בישראל", "הוצאה לאומית לתרבות"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
        "release": release,
    }
