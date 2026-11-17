"""ההוצאה הלאומית למחקר ופיתוח: CBS's yearly national R&D expenditure release.

The release is a set of Excel tables (לוח 1..12) plus chart-data sheets
(תרשים 1..4). CBS can renumber them between editions, so every table input
(t1..t19, the last three spare slots, all optional) is read with `cbs.grid`
and each table is recognised by its TITLE text (English title lines, which
the sheets print beside the Hebrew), never by its stem:

  sector     NATIONAL EXPENDITURE ... BY OPERATING SECTOR    1996-, current + constant prices
  financing  ... BY FINANCING SECTOR AND OPERATING SECTOR   year blocks (latest years)
  exptype    ... BY OPERATING SECTOR AND TYPE OF EXPENDITURE year blocks
  govtype    EXPENDITURE OF GOVERNMENT MINISTRIES AND ... RESEARCH INSTITUTIONS  1992-
  purchase   ... MINISTRIES ON R&D PURCHASE, BY OPERATING SECTOR             1992-
  transfers  GOVERNMENT MINISTRIES' TRANSFERS FOR R&D, BY OPERATING SECTOR     1992-
  ministries EXPENDITURE OF SELECTED GOVERNMENT MINISTRIES ON R&D           wide, years as columns
  intra      INTRAMURAL EXPENDITURE OF SELECTED GOVERNMENT MINISTRIES        wide
  objective  FINANCING OF R&D BY GOVERNMENT MINISTRIES, BY OBJECTIVE       wide, percent
  npi        EXPENDITURE OF NON-PROFIT INSTITUTIONS ... SCIENTIFIC FIELD    year blocks
  industry   INTRAMURAL EXPENDITURE ON R&D IN SELECTED MANUFACTURING INDUSTRIES  percent
  oecd       ... PER CAPITA AND AS PERCENTAGE OF GDP, SELECTED OECD COUNTRIES
  oecd_avg   Diagram: International Comparison (the only sheet with the OECD average)

Column meanings come from the Hebrew header cells above each column, joined
over the header rows; data rows are found by pattern (a year, or a Hebrew
row label with numbers). The sector table is required (the page's headline);
any other table missing drops its section. A recognised table whose header
labels are gone raises (a human should look at the new layout).
"""
import re
from itertools import pairwise

import pandas as pd
from govlib import cbs, fmt

HEB = re.compile("[א-ת]")
CONST = re.compile(r"(?:במחירי|\bat)\s*((?:19|20)\d\d)")
UNIT_ROW = re.compile(r"מיליוני|אחוזים|NIS|Percentages")
GARBLED = re.compile(r"\d%\.\d")
DIAGRAM = re.compile(r"^Diagram\s*\d", re.IGNORECASE)
SECTORS = ("business", "higher", "gov", "pnp")
SECTOR_HE = {"business": "עסקי", "higher": "השכלה גבוהה", "gov": "ממשלתי",
             "pnp": "מלכ\"רים פרטיים", "abroad": "חו\"ל"}
TYPE_HE = {"labour": "עלות עבודה", "inter": "צריכת ביניים", "capital": "השקעות"}
PRIORITY = ("real", "long", "oecd", "business", "abroad", "labour", "ministries", "gov_abroad",
            "industry", "objective", "intra", "npi", "govtype")
MAX_TOP = 8


# ── locating tables ──────────────────────────────────────────────────────


def _title_text(rows):
    """The English title lines (printed in upper case) from the top of a
    sheet, plus a chart sheet's caption ("Diagram N - ...") wherever it sits."""
    out = []
    for i, r in enumerate(rows):
        for c in r:
            if not c or HEB.search(c):
                continue
            if DIAGRAM.match(c) or (i < 14 and c == c.upper() and re.search("[A-Z]", c)):
                out.append(c)
    return " ".join(out).upper()


def _kind(t):
    if "DIAGRAM" in t:
        return "oecd_avg" if "INTERNATIONAL COMPARISON" in t else None
    if "TABLE" not in t:
        return None
    if "OECD" in t and "GDP" in t:
        return "oecd"
    if "MANUFACTURING INDUSTRIES" in t:
        return "industry"
    if "NON-PROFIT INSTITUTIONS" in t and "SCIENTIFIC FIELD" in t:
        return "npi"
    if "BY OBJECTIVE" in t:
        return "objective"
    if "SELECTED GOVERNMENT MINISTRIES" in t:
        return "intra" if "INTRAMURAL" in t else "ministries"
    if "TRANSFERS" in t and "MINISTRIES" in t:
        return "transfers"
    if "R&D PURCHASE" in t:
        return "purchase"
    if "GOVERNMENT MINISTRIES" in t and "RESEARCH INSTITUTIONS" in t:
        return "govtype"
    if "NATIONAL EXPENDITURE" in t:
        if "FINANCING SECTOR" in t:
            return "financing"
        if "TYPE OF EXPENDITURE" in t:
            return "exptype"
        if "OPERATING SECTOR" in t:
            return "sector"
    return None


def _tables(frames):
    """{kind: rows} over every non-empty table input; the first stem wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        k = _kind(_title_text(rows))
        if k and k not in out:
            out[k] = rows
    return out


# ── generic grid readers ─────────────────────────────────────────────────


def _is_year(c):
    return bool(cbs.YEAR.match(c))


def _heb_cols(rows, start, stop, cols):
    """{col: Hebrew header label} joined over the header rows, skipping unit
    rows (מיליוני ש"ח / אחוזים)."""
    out = {j: [] for j in cols}
    for r in rows[start:stop]:
        if any(UNIT_ROW.search(c) for c in r):
            continue
        for j in cols:
            c = cbs.cell(r, j)
            if c and HEB.search(c):
                out[j].append(c)
    return {j: " ".join(v) for j, v in out.items()}


def _sector_key(label):
    if "סך הכל" in label or "סך כולל" in label:
        return "total"
    if "חו\"ל" in label:
        return "abroad"
    if "עסקי" in label:
        return "business"
    if "השכלה" in label:
        return "higher"
    if "ממשלתי" in label:
        return "gov"
    if "מלכ\"רים" in label:
        return "pnp"
    return None


def _type_key(label):
    if "ביצוע עצמי" in label:
        return "intra_total"
    if "סך כולל" in label:
        return "grand"
    if "סך הכל" in label:
        return "total"
    if "העברות" in label:
        return "transfers"
    if "קניית" in label:
        return "purchase"
    if "עלות" in label and "עבודה" in label:
        return "labour"
    if "צריכת ביניים" in label:
        return "inter"
    if "השקע" in label:
        return "capital"
    return None


def _colmap(rows, start, stop, cols, keyfn, need, name):
    labels = _heb_cols(rows, start, stop, cols)
    m = {}
    for j in sorted(cols):
        k = keyfn(labels[j])
        if k and k not in m:
            m[k] = j
    missing = [k for k in need if k not in m]
    if missing:
        raise ValueError(f"{name}: header labels {missing} not found")
    return m, labels


def _first_year_row(rows, col=0, start=0):
    for i in range(start, len(rows)):
        if _is_year(cbs.cell(rows[i], col)):
            return i
    return None


def _year_series(rows, start, stop, cols):
    """{year: {key: value}} for rows in [start, stop) whose first cell is a year."""
    out = {}
    for i in range(start, stop):
        r = rows[i]
        y = cbs.cell(r, 0)
        if not _is_year(y):
            continue
        vals = {k: cbs.val(r, j) for k, j in cols.items()}
        if all(v is None for v in vals.values()):
            continue
        out.setdefault(int(y), vals)
    return out


def _block_year(r):
    """A year-block marker row: exactly one non-empty cell and it is a year."""
    cells = [c for c in r if c]
    return int(cells[0]) if len(cells) == 1 and _is_year(cells[0]) else None


def _blocks(rows, start, label_col, value_cols):
    """{year: [(label, row)]}: rows labelled in `label_col` (Hebrew) under
    each year-block marker row. A label split over rows is joined."""
    out, year, pending = {}, None, []
    for i in range(start, len(rows)):
        r = rows[i]
        y = _block_year(r)
        if y is not None:
            year, pending = y, []
            out.setdefault(year, [])
            continue
        if year is None:
            continue
        lab = cbs.cell(r, label_col)
        has_num = any(cbs.val(r, j) is not None for j in value_cols)
        if lab and HEB.search(lab):
            pending.append(lab)
        if has_num and pending:
            out[year].append((" ".join(pending), r))
            pending = []
        elif has_num:
            pending = []
    return {y: v for y, v in out.items() if v}


def _wide(rows, name):
    """A table with years as columns: (years, [(label, {year: value})]) for
    its first block (a later "at 2020 prices" block is left out)."""
    h = None
    for i, r in enumerate(rows):
        if sum(1 for c in r if _is_year(c)) >= 3:
            h = i
            break
    if h is None:
        raise ValueError(f"{name}: year header row not found")
    ycols = {j: int(c) for j, c in enumerate(rows[h]) if _is_year(c)}
    label_col = max(ycols) + 1
    out, pending = [], []
    for r in rows[h + 1:]:
        if any(CONST.search(c) for c in r):
            break
        lab = cbs.cell(r, label_col)
        vals = {y: cbs.val(r, j) for j, y in ycols.items()}
        has_num = any(v is not None for v in vals.values())
        if lab and HEB.search(lab):
            pending.append(lab)
            if has_num:
                out.append((" ".join(pending), vals))
                pending = []
        elif has_num:
            pending = []
    years = sorted(ycols.values())
    return years, out


# ── formatting ───────────────────────────────────────────────────────────


def _r1(v):
    return None if v is None else round(v, 1)


def _r2(v):
    return None if v is None else round(v, 2)


def _bn(v):
    """₪ million → ₪ billion, one decimal."""
    return fmt.num_he(v / 1000, 1)


def _mn(v):
    return "" if v is None else fmt.int_he(v)


def _p(v):
    return "" if v is None else fmt.pct_of(v)


def _short_ministry(label):
    s = re.sub(r"\s+", " ", label).strip()
    return s


def _short_industry(label):
    if "מחשבים" in label:
        return "מחשבים, אלקטרוניקה ואופטיקה"
    if "ציוד חשמלי" in label:
        return "ציוד חשמלי, מכונות וכלי תחבורה"
    if "מתכות" in label:
        return "מתכות ומוצרי מתכת"
    if "תרופות" in label or "כימיקלים" in label:
        return "כימיקלים, תרופות ונפט"
    if "מזון" in label:
        return "מזון, משקאות וטבק"
    if "רפואי" in label:
        return "ציוד רפואי ומדעי"
    if "אחרים" in label:
        return "ענפים אחרים"
    return label


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    t = _tables(frames)
    if "sector" not in t:
        raise ValueError("national expenditure by operating sector table not found")
    rel = cbs.latest_release(frames["releases"])

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── 1. national expenditure by operating sector (required) ───────────
    rows = t["sector"]
    y0 = _first_year_row(rows)
    if y0 is None:
        raise ValueError("sector: no year rows")
    last = len(rows[0]) - 1
    smap, _ = _colmap(rows, 0, y0, range(1, last), _sector_key,
                      ("total", "business", "higher", "gov", "pnp"), "sector")
    const_at, base_year = None, None
    for i in range(y0, len(rows)):
        for c in rows[i]:
            m = CONST.search(c)
            if m:
                const_at, base_year = i, int(m.group(1))
                break
        if const_at is not None:
            break
    cur = _year_series(rows, y0, const_at if const_at is not None else len(rows), smap)
    real = _year_series(rows, const_at, len(rows), smap) if const_at is not None else {}
    cy = sorted(cur)
    if not cy:
        raise ValueError("sector: no current-price years")
    ly = cy[-1]
    tot_l = cur[ly]["total"]
    if tot_l is None:
        raise ValueError(f"sector: no total for {ly}")

    kpis["total"] = {"value": round(tot_l / 1000, 1), "display": _bn(tot_l), "tone": "brand"}
    labels["total_kpi"] = f"הוצאה לאומית למו\"פ, מיליארדי ₪ במחירים שוטפים ({ly})"

    ry = sorted(y for y in real if real[y]["total"] is not None)
    flags["real"] = len(ry) >= 2
    charts["trend"] = {"x": [str(y) for y in cy],
                       "cur": [_r1(cur[y]["total"] / 1000) if cur[y]["total"] is not None else None
                               for y in cy],
                       "real": [_r1(real[y]["total"] / 1000) if y in real and real[y]["total"] is not None
                                else None for y in cy],
                       "base": base_year}
    tables["trend"] = [[str(y), _bn(cur[y]["total"]) if cur[y]["total"] is not None else "",
                        _bn(real[y]["total"]) if y in real and real[y]["total"] is not None else ""]
                       for y in reversed(cy)]
    labels["trend_cols"] = ["שנה", "מחירים שוטפים"] + ([f"מחירי {base_year}"] if base_year else [])
    if not base_year:
        tables["trend"] = [r[:2] for r in tables["trend"]]
    labels["trend_note"] = (f"ההוצאה הלאומית למחקר ופיתוח בכל שנה מאז {cy[0]}, במיליארדי ₪: במחירים "
                            f"שוטפים" + (f", ובמחירים קבועים (מחירי {base_year}) שמנטרלים את עליית "
                                         f"המחירים." if base_year else "."))
    labels["trend_aria"] = f"ההוצאה הלאומית למו\"פ, {cy[0]} עד {ly}"

    if flags["real"]:
        rl, rp = ry[-1], ry[-2]
        ch = real[rl]["total"] / real[rp]["total"] - 1
        tone = "ok" if ch > 0.005 else ("danger" if ch <= -0.02 else ("warn" if ch < -0.005 else "brand"))
        kpis["real"] = {"value": round(ch * 100, 1), "display": fmt.signed_pct(ch), "tone": tone}
        labels["real_kpi"] = f"שינוי ריאלי בהוצאה, {rl} לעומת {rp} (מחירי {base_year})"
        # growth bars
        gx, gy = [], []
        for a, b in pairwise(ry):
            if b == a + 1:
                gx.append(str(b))
                gy.append(_r1((real[b]["total"] / real[a]["total"] - 1) * 100))
        charts["growth"] = {"x": gx, "y": gy}
        tables["growth"] = [[x, fmt.signed_pct(v / 100)] for x, v in zip(reversed(gx), reversed(gy))]
        labels["growth_note"] = (f"בכמה אחוזים גדלה או קטנה ההוצאה הלאומית למו\"פ בכל שנה לעומת השנה "
                                 f"הקודמת, במחירים קבועים (מחירי {base_year}).")
        labels["growth_aria"] = f"שינוי ריאלי שנתי בהוצאה הלאומית למו\"פ, {gx[0]} עד {gx[-1]}" if gx else ""
        flags["growth"] = len(gx) >= 3
        # A year whose constant-price change departs from the current-price
        # change by more than 30 points is a break in CBS's deflated series.
        breaks = [b for a, b in pairwise(ry) if b == a + 1 and a in cur and b in cur
                  and cur[a]["total"] and cur[b]["total"]
                  and abs((real[b]["total"] / real[a]["total"]) - (cur[b]["total"] / cur[a]["total"])) > 0.3]
        if breaks:
            labels["growth_break"] = (f"בשנים {fmt.join_he(breaks)} השינוי במחירים קבועים שונה מאוד מהשינוי "
                                      f"במחירים שוטפים" if len(breaks) > 1 else
                                      f"בשנת {breaks[0]} השינוי במחירים קבועים שונה מאוד מהשינוי במחירים "
                                      f"שוטפים") + (", כנראה בגלל שבר בסדרה של הלמ\"ס. יש להתייחס לקפיצה "
                                                    "הזאת בזהירות.")
        # streak of the latest direction
        streak = 1
        sign = ch > 0
        for k in range(len(ry) - 2, 0, -1):
            a, b = ry[k - 1], ry[k]
            if b != a + 1:
                break
            if (real[b]["total"] > real[a]["total"]) == sign:
                streak += 1
            else:
                break
        if abs(ch) >= 0.005:
            word = "עלתה" if ch > 0 else "ירדה"
            txt = (f"ב-{rl} ההוצאה הלאומית למו\"פ במחירים קבועים {word} ב-{fmt.pct(abs(ch))} לעומת {rp}, "
                   f"ל-{_bn(real[rl]['total'])} מיליארד ₪ (במחירי {base_year})")
            if streak >= 2:
                txt += (f". זו השנה {_ordinal(streak)} ברציפות של "
                        + ("עלייה" if ch > 0 else "ירידה"))
            add("real", txt + ".")
        else:
            add("real", f"ב-{rl} ההוצאה הלאומית למו\"פ במחירים קבועים כמעט לא השתנתה לעומת {rp}: "
                        f"{_bn(real[rl]['total'])} מיליארד ₪ (במחירי {base_year}).")
        # long-run
        f0 = ry[0]
        mult = real[rl]["total"] / real[f0]["total"]
        peak = max(ry, key=lambda y: (real[y]["total"], y))
        if mult >= 1.5:
            txt = (f"במחירים קבועים ההוצאה הלאומית למו\"פ גדלה פי {fmt.num_he(mult, 1)} מאז {f0}, "
                   f"מ-{_bn(real[f0]['total'])} ל-{_bn(real[rl]['total'])} מיליארד ₪")
            if peak != rl:
                txt += (f". השיא היה ב-{peak}, עם {_bn(real[peak]['total'])} מיליארד ₪, "
                        f"ומאז ההוצאה ירדה ב-{fmt.pct(1 - real[rl]['total'] / real[peak]['total'])}")
            add("long", txt + ".")
    else:
        flags["growth"] = False

    # sector mix over time (constant prices when present, else current)
    mix_src = real if flags["real"] else cur
    mix_years = sorted(y for y in mix_src if mix_src[y]["total"])
    charts["sector"] = {"x": [str(y) for y in mix_years],
                        "names": [SECTOR_HE[s] for s in SECTORS],
                        "series": [[_r2(mix_src[y][s] / 1000) if mix_src[y][s] is not None else None
                                    for y in mix_years] for s in SECTORS]}
    lc = cur[ly]
    tables["sector"] = [[SECTOR_HE[s], _mn(lc[s]), _p(lc[s] / tot_l * 100) if lc[s] is not None else ""]
                        for s in SECTORS]
    labels["sector_note"] = ("מי מבצע את המחקר והפיתוח: המגזר העסקי, מוסדות להשכלה גבוהה, הממשלה ומלכ\"רים "
                             "פרטיים, במיליארדי ₪"
                             + (f" במחירי {base_year}." if flags["real"] else " במחירים שוטפים."))
    labels["sector_aria"] = f"ההוצאה הלאומית למו\"פ לפי מגזר מבצע, {mix_years[0]} עד {mix_years[-1]}"
    labels["sector_table"] = f"ההוצאה הלאומית למו\"פ לפי מגזר מבצע, {ly} (מיליוני ₪, מחירים שוטפים)"
    if lc["business"] is not None:
        bs = lc["business"] / tot_l
        kpis["business"] = {"value": round(bs * 100, 1), "display": fmt.pct(bs), "tone": "brand"}
        labels["business_kpi"] = f"חלק המגזר העסקי בביצוע המו\"פ ({ly})"
        first = cy[0]
        fb = cur[first]["business"]
        ft = cur[first]["total"]
        if bs >= 0.5 and fb is not None and ft:
            txt = (f"{fmt.pct(bs)} מההוצאה הלאומית למו\"פ ב-{ly} בוצעו במגזר העסקי "
                   f"({_bn(lc['business'])} מיליארד ₪)")
            if abs(bs - fb / ft) >= 0.02:
                txt += f", לעומת {fmt.pct(fb / ft)} ב-{first}"
            if lc["higher"] is not None:
                txt += f". המוסדות להשכלה גבוהה ביצעו {fmt.pct(lc['higher'] / tot_l)}"
            add("business", txt + ".")

    # ── 2. financing sector ──────────────────────────────────────────────
    flags["financing"] = False
    if "financing" in t:
        rows = t["financing"]
        b0 = next((i for i, r in enumerate(rows) if _block_year(r) is not None), None)
        if b0 is None:
            raise ValueError("financing: no year block")
        lastc = len(rows[0]) - 1
        fmap, _ = _colmap(rows, 0, b0, range(1, lastc), _sector_key, ("total", "business"), "financing")
        blocks = _blocks(rows, b0, lastc, list(fmap.values()))
        fin = {}
        for y, items in blocks.items():
            d = {}
            for lab, r in items:
                if "ות\"ת" in lab:
                    key = "pbc"
                elif lab.startswith("מזה"):
                    continue
                else:
                    key = _sector_key(lab)
                if key and key not in d:
                    d[key] = {"total": cbs.val(r, fmap["total"]),
                              "business": cbs.val(r, fmap["business"])}
            if "total" in d and d["total"]["total"]:
                fin[y] = d
        fy = sorted(fin)
        fkeys = [k for k in ("business", "abroad", "gov", "higher", "pnp")
                 if any(k in fin[y] for y in fy)]
        flags["financing"] = bool(fy) and "abroad" in fkeys
        if flags["financing"]:
            def fv(y, k, col="total"):
                return fin[y].get(k, {}).get(col)
            charts["financing"] = {"x": [str(y) for y in fy],
                                   "names": [SECTOR_HE[k] for k in fkeys],
                                   "series": [[_r2(fv(y, k) / 1000) if fv(y, k) is not None else None
                                               for y in fy] for k in fkeys]}
            fl = fy[-1]
            ft = fv(fl, "total")
            tables["financing"] = [[SECTOR_HE[k]] + [_mn(fv(y, k)) for y in fy] for k in fkeys]
            labels["financing_cols"] = ["מגזר מממן"] + [str(y) for y in fy]
            labels["financing_note"] = (f"מי מממן את המחקר והפיתוח בישראל, {fy[0]} עד {fl}, במיליארדי ₪ "
                                        f"במחירים שוטפים. נתוני המימון מתפרסמים בפיגור של שנה לעומת "
                                        f"נתוני הביצוע." if fl < ly else
                                        f"מי מממן את המחקר והפיתוח בישראל, {fy[0]} עד {fl}, במיליארדי ₪ "
                                        f"במחירים שוטפים.")
            labels["financing_aria"] = f"ההוצאה הלאומית למו\"פ לפי מגזר מממן, {fy[0]} עד {fl}"
            ab = fv(fl, "abroad")
            if ab is not None and ft:
                share = ab / ft
                kpis["abroad"] = {"value": round(share * 100, 1), "display": fmt.pct(share), "tone": "info"}
                labels["abroad_kpi"] = f"חלק המימון מחו\"ל בהוצאה הלאומית למו\"פ ({fl})"
                txt = (f"{fmt.pct(share)} מההוצאה הלאומית למו\"פ ב-{fl} מומנו מחו\"ל "
                       f"({_bn(ab)} מיליארד ₪)")
                bb = fv(fl, "abroad", "business")
                bt = fv(fl, "total", "business")
                if bb is not None and bt:
                    txt += f", ובמגזר העסקי {fmt.pct(bb / bt)} מהמו\"פ"
                f0 = fy[0]
                if f0 != fl and fv(f0, "abroad") is not None and fv(f0, "total"):
                    s0 = fv(f0, "abroad") / fv(f0, "total")
                    if abs(share - s0) >= 0.01:
                        txt += (f". ב-{f0} החלק היה {fmt.pct(s0)}")
                add("abroad", txt + ".")

    # ── 3. type of expenditure ───────────────────────────────────────────
    flags["exptype"] = False
    if "exptype" in t:
        rows = t["exptype"]
        b0 = next((i for i, r in enumerate(rows) if _block_year(r) is not None), None)
        if b0 is None:
            raise ValueError("exptype: no year block")
        lastc = len(rows[0]) - 1
        tmap, _ = _colmap(rows, 0, b0, range(1, lastc), _type_key,
                          ("total", "labour", "inter", "capital"), "exptype")
        blocks = _blocks(rows, b0, lastc, list(tmap.values()))
        if blocks:
            ey = max(blocks)
            d = {}
            for lab, r in blocks[ey]:
                if lab.startswith("מזה"):
                    continue
                k = _sector_key(lab)
                if k and k not in d:
                    d[k] = {c: cbs.val(r, j) for c, j in tmap.items()}
            secs = [s for s in SECTORS if s in d and d[s]["total"]]
            flags["exptype"] = "total" in d and bool(d["total"]["total"]) and len(secs) >= 2
            if flags["exptype"]:
                types = ("labour", "inter", "capital")
                cats = secs + ["total"]
                names = [SECTOR_HE[s] for s in secs] + ["סך הכל"]
                charts["exptype"] = {"names": names, "types": [TYPE_HE[x] for x in types],
                                     "series": [[_r1((d[c][x] or 0) / d[c]["total"] * 100) for c in cats]
                                                for x in types]}
                tables["exptype"] = [[nm] + [_mn(d[c][x]) for x in types] + [_mn(d[c]["total"])]
                                     for nm, c in zip(names, cats)]
                labels["exptype_cols"] = ["מגזר מבצע"] + [TYPE_HE[x] for x in types] + ["סך הכל"]
                labels["exptype_note"] = (f"על מה הולך הכסף: עלות עבודה (שכר החוקרים והמפתחים), צריכת ביניים "
                                          f"והשקעות, כאחוז מההוצאה של כל מגזר ב-{ey}.")
                labels["exptype_aria"] = f"ההוצאה למו\"פ לפי סוג הוצאה ומגזר מבצע, {ey}"
                tl = d["total"]
                if tl["labour"]:
                    sh = tl["labour"] / tl["total"]
                    if sh >= 0.5:
                        add("labour", f"{fmt.pct(sh)} מההוצאה הלאומית למו\"פ ב-{ey} היו עלות עבודה, "
                                      f"כלומר שכר החוקרים והמפתחים. ההשקעות היו "
                                      f"{fmt.pct((tl['capital'] or 0) / tl['total'])} בלבד.")

    # ── 4. government ministries by type of expenditure ─────────────────
    flags["govtype"] = False
    if "govtype" in t:
        rows = t["govtype"]
        y0 = _first_year_row(rows)
        if y0 is not None:
            lastc = len(rows[0]) - 1
            gmap, _ = _colmap(rows, 0, y0, range(1, lastc), _type_key,
                              ("transfers", "purchase", "intra_total", "grand"), "govtype")
            gs = _year_series(rows, y0, len(rows), gmap)
            gy = sorted(y for y in gs if gs[y]["grand"] is not None)
            flags["govtype"] = len(gy) >= 3
            if flags["govtype"]:
                parts = ("transfers", "purchase", "intra_total")
                pn = ["העברות לגופים אחרים", "קניית מו\"פ ממגזרים אחרים", "ביצוע עצמי"]
                charts["govtype"] = {"x": [str(y) for y in gy], "names": pn,
                                     "series": [[_r1(gs[y][p]) for y in gy] for p in parts]}
                tables["govtype"] = [[str(y)] + [_mn(gs[y][p]) for p in parts] + [_mn(gs[y]["grand"])]
                                     for y in reversed(gy)]
                labels["govtype_cols"] = ["שנה"] + pn + ["סך הכל"]
                labels["govtype_note"] = (f"הוצאות משרדי הממשלה ומכוני המחקר הממשלתיים למו\"פ, {gy[0]} עד "
                                          f"{gy[-1]}, במיליוני ₪ במחירים שוטפים, לפי האופן שבו הכסף "
                                          f"מוצא: העברות, קניית מו\"פ או מחקר שהמשרדים מבצעים בעצמם "
                                          f"(ללא הוועדה לתכנון ולתקצוב).")
                labels["govtype_aria"] = f"הוצאות משרדי הממשלה למו\"פ לפי סוג הוצאה, {gy[0]} עד {gy[-1]}"
                gl = gy[-1]
                g = gs[gl]
                if (g["transfers"] is not None and g["grand"]
                        and (g["intra_total"] or 0) / g["grand"] < 0.3):
                    add("govtype", f"מתוך {_bn(g['grand'])} מיליארד ₪ שהוציאו משרדי הממשלה על מו\"פ ב-{gl}, "
                                   f"{fmt.pct(g['transfers'] / g['grand'])} הועברו לגופים אחרים, ורק "
                                   f"{fmt.pct((g['intra_total'] or 0) / g['grand'])} מומשו במחקר "
                                   f"שהמשרדים ביצעו בעצמם.")

    # ── 5. ministries' transfers + purchases, by operating sector ────────
    flags["flows"] = False
    flow = {}
    for kind in ("transfers", "purchase"):
        if kind not in t:
            continue
        rows = t[kind]
        y0 = _first_year_row(rows)
        if y0 is None:
            continue
        lastc = len(rows[0]) - 1
        fmap, _ = _colmap(rows, 0, y0, range(1, lastc), _sector_key,
                          ("total", "business", "abroad"), kind)
        flow[kind] = _year_series(rows, y0, len(rows), fmap)
    if flow:
        fkeys = ("business", "higher", "gov", "pnp", "abroad")
        yrs = sorted(set().union(*[set(v) for v in flow.values()]))
        yrs = [y for y in yrs if all(y in v for v in flow.values())]

        def fsum(y, k):
            vals = [flow[kind][y].get(k) for kind in flow]
            vals = [v for v in vals if v is not None]
            return sum(vals) if vals else None

        flags["flows"] = len(yrs) >= 3
        if flags["flows"]:
            both = len(flow) == 2
            charts["flows"] = {"x": [str(y) for y in yrs], "names": [SECTOR_HE[k] for k in fkeys],
                               "series": [[_r1(fsum(y, k)) for y in yrs] for k in fkeys]}
            tables["flows"] = [[str(y)] + [_mn(fsum(y, k)) for k in fkeys] + [_mn(fsum(y, "total"))]
                               for y in reversed(yrs)]
            labels["flows_cols"] = ["שנה"] + [SECTOR_HE[k] for k in fkeys] + ["סך הכל"]
            what = "העברות וקניית מו\"פ" if both else ("העברות" if "transfers" in flow else "קניית מו\"פ")
            labels["flows_note"] = (f"לאן הולך הכסף שמשרדי הממשלה מוציאים מחוץ למשרד ({what}), לפי המגזר "
                                    f"שמבצע את המחקר, {yrs[0]} עד {yrs[-1]}, במיליוני ₪ במחירים שוטפים.")
            labels["flows_aria"] = f"{what} של משרדי הממשלה לפי מגזר מבצע, {yrs[0]} עד {yrs[-1]}"
            yl = yrs[-1]
            tot = fsum(yl, "total")
            ab = fsum(yl, "abroad")
            if tot and ab is not None:
                share = ab / tot
                ref = next((y for y in yrs if y >= yl - 10), yrs[0])
                rt, ra = fsum(ref, "total"), fsum(ref, "abroad")
                if share >= 0.1:
                    txt = (f"{fmt.pct(share)} מהכסף שמשרדי הממשלה העבירו או שילמו למו\"פ מחוץ למשרדים ב-{yl} "
                           f"הלכו לגופים בחו\"ל ({_mn(ab)} מיליון ₪)")
                    if rt and ra is not None and ref != yl and abs(share - ra / rt) >= 0.03:
                        txt += f", לעומת {fmt.pct(ra / rt)} ב-{ref}"
                    add("gov_abroad", txt + ".")

    # ── 6. selected ministries ───────────────────────────────────────────
    flags["ministries"] = False
    if "ministries" in t:
        years, items = _wide(t["ministries"], "ministries")
        tot = next((v for lab, v in items if lab.strip() == "סך הכל"), None)
        mins = [(_short_ministry(lab), v) for lab, v in items if lab.strip() != "סך הכל"]
        years = [y for y in years if any(v.get(y) is not None for _, v in mins)]
        flags["ministries"] = len(years) >= 3 and len(mins) >= 2
        if flags["ministries"]:
            yl = years[-1]
            other = [m for m in mins if "אחרים" in m[0]]
            named = sorted((m for m in mins if "אחרים" not in m[0]),
                           key=lambda m: (-(m[1].get(yl) or 0), m[0]))
            order = named + other
            charts["ministries"] = {"x": [str(y) for y in years], "names": [m[0] for m in order],
                                    "series": [[_r1(m[1].get(y)) for y in years] for m in order]}
            tables["ministries"] = [[str(y)] + [_mn(m[1].get(y)) for m in order]
                                    + ([_mn(tot.get(y))] if tot else []) for y in reversed(years)]
            labels["ministries_cols"] = ["שנה"] + [m[0] for m in order] + (["סך הכל"] if tot else [])
            labels["ministries_note"] = (f"הוצאות משרדי ממשלה נבחרים למו\"פ, {years[0]} עד {yl}, במיליוני ₪ "
                                         f"במחירים שוטפים. פעילויות עברו לאורך השנים בין משרדים, ולכן "
                                         f"יש להיזהר בהשוואה לאורך זמן.")
            labels["ministries_aria"] = f"הוצאות משרדי ממשלה נבחרים למו\"פ, {years[0]} עד {yl}"
            lead = named[0]
            tl = tot.get(yl) if tot else sum(m[1].get(yl) or 0 for m in mins)
            lv = lead[1].get(yl)
            if lv and tl:
                txt = (f"{lead[0]} מוביל את הוצאות הממשלה למו\"פ: {_mn(lv)} מיליון ₪ ב-{yl}, "
                       f"{fmt.pct(lv / tl)} מהוצאות משרדי הממשלה")
                prev = lead[1].get(yl - 1)
                if prev:
                    ch = lv / prev - 1
                    if abs(ch) >= 0.05:
                        txt += (f". ההוצאה של המשרד {'ירדה' if ch < 0 else 'עלתה'} ב-{fmt.pct(abs(ch))} "
                                f"לעומת {yl - 1}")
                add("ministries", txt + ".")

    # ── 7. ministries' intramural R&D (insight only) ────────────────────
    if "intra" in t:
        years, items = _wide(t["intra"], "intra")
        tot = next((v for lab, v in items if lab.strip() == "סך הכל"), None)
        mins = [(_short_ministry(lab), v) for lab, v in items if lab.strip() != "סך הכל"]
        yl = max((y for y in years if tot and tot.get(y)), default=None)
        if yl is not None and mins:
            lead = max(mins, key=lambda m: (m[1].get(yl) or 0, m[0]))
            lv = lead[1].get(yl)
            if lv and lv / tot[yl] >= 0.4:
                add("intra", f"{lead[0]} מבצע בעצמו את רוב המחקר הממשלתי: {_mn(lv)} מתוך {_mn(tot[yl])} "
                             f"מיליון ₪ שמשרדי הממשלה הוציאו ב-{yl} על מו\"פ בביצוע עצמי "
                             f"({fmt.pct(lv / tot[yl])}).")

    # ── 8. objectives (percent) ──────────────────────────────────────────
    flags["objective"] = False
    if "objective" in t:
        years, items = _wide(t["objective"], "objective")
        objs = [(re.sub(r"\s+", " ", lab).strip(), v) for lab, v in items if lab.strip() != "סך הכל"]
        years = [y for y in years if sum(1 for _, v in objs if v.get(y) is not None) >= 3]
        flags["objective"] = len(years) >= 1 and len(objs) >= 3
        if flags["objective"]:
            yl, yf = years[-1], years[0]
            objs.sort(key=lambda o: (-(o[1].get(yl) or 0), o[0]))
            cols = [yf, yl] if yf != yl else [yl]
            charts["objective"] = {"names": [o[0] for o in objs], "years": [str(y) for y in cols],
                                   "series": [[_r1(o[1].get(y)) for o in objs] for y in cols]}
            tables["objective"] = [[o[0]] + [_p(o[1].get(y)) for y in cols] for o in objs]
            labels["objective_cols"] = ["יעד"] + [str(y) for y in cols]
            labels["objective_note"] = ("לאילו מטרות מממנים משרדי הממשלה מו\"פ, באחוזים מהמימון"
                                        + (f": {yf} לעומת {yl}." if yf != yl else f", {yl}."))
            labels["objective_aria"] = f"מימון מו\"פ על ידי משרדי הממשלה לפי יעד, {yl}"
            top2 = objs[:2]
            if len(top2) == 2 and (top2[0][1].get(yl) or 0) + (top2[1][1].get(yl) or 0) >= 50:
                txt = (f"שני יעדים מקבלים את רוב המימון הממשלתי למו\"פ ב-{yl}: {top2[0][0]} "
                       f"({_p(top2[0][1].get(yl))}) ו{top2[1][0]} ({_p(top2[1][1].get(yl))})")
                riser = max(objs, key=lambda o: ((o[1].get(yl) or 0) - (o[1].get(yf) or 0), o[0]))
                rf, rl_ = riser[1].get(yf), riser[1].get(yl)
                if yf != yl and rf is not None and rl_ is not None and rl_ - rf >= 2 and riser not in top2:
                    txt += f". היעד שגדל הכי הרבה: {riser[0]}, מ-{_p(rf)} ב-{yf} ל-{_p(rl_)}"
                add("objective", txt + ".")

    # ── 9. non-profit institutions by scientific field ──────────────────
    flags["npi"] = False
    if "npi" in t:
        rows = t["npi"]
        b0 = next((i for i, r in enumerate(rows) if _block_year(r) is not None), None)
        if b0 is not None:
            lastc = len(rows[0]) - 1
            nmap, _ = _colmap(rows, 0, b0, range(1, lastc), _type_key, ("total",), "npi")
            blocks = _blocks(rows, b0, lastc, list(nmap.values()))
            data = {}
            for y, items in blocks.items():
                for lab, r in items:
                    if lab.strip() == "סך הכל":
                        continue
                    data.setdefault(lab.strip(), {})[y] = cbs.val(r, nmap["total"])
            ny = sorted(blocks)
            fields = sorted(data, key=lambda f: (-(data[f].get(ny[-1]) or 0), f)) if ny else []
            flags["npi"] = len(fields) >= 2
            if flags["npi"]:
                charts["npi"] = {"x": [str(y) for y in ny], "names": fields,
                                 "series": [[_r1(data[f].get(y)) for y in ny] for f in fields]}
                tables["npi"] = [[f] + [_mn(data[f].get(y)) if data[f].get(y) is not None else ""
                                        for y in ny] for f in fields]
                labels["npi_cols"] = ["תחום מדעי"] + [str(y) for y in ny]
                labels["npi_note"] = (f"הוצאות המלכ\"רים (ציבוריים ואחרים) למו\"פ לפי תחום מדעי, {ny[0]} עד "
                                      f"{ny[-1]}, במיליוני ₪, ללא מו\"פ בבתי חולים.")
                labels["npi_aria"] = f"הוצאות מלכ\"רים למו\"פ לפי תחום מדעי, {ny[0]} עד {ny[-1]}"
                yl = ny[-1]
                tot = sum(data[f].get(yl) or 0 for f in fields)
                hs = [f for f in fields if "החברה" in f or "הרוח" in f]
                hv = sum(data[f].get(yl) or 0 for f in hs)
                if tot and len(hs) == 2 and hv / tot >= 0.5:
                    add("npi", f"במלכ\"רים, רוב המו\"פ הוא במדעי החברה והרוח: {fmt.pct(hv / tot)} מהוצאות "
                               f"המלכ\"רים למו\"פ ב-{yl} ({_mn(hv)} מיליון ₪).")

    # ── 10. manufacturing industries (percent) ──────────────────────────
    flags["industry"] = False
    if "industry" in t:
        rows = t["industry"]
        y0 = _first_year_row(rows)
        if y0 is not None:
            lastc = len(rows[0]) - 1
            labs = _heb_cols(rows, 0, y0, range(1, lastc))
            icols = {j: _short_industry(lab) for j, lab in labs.items()
                     if lab and "סך הכל" not in lab}
            if not icols:
                raise ValueError("industry: header labels not found")
            ser = _year_series(rows, y0, len(rows), {nm: j for j, nm in icols.items()})
            iy = sorted(ser)
            flags["industry"] = len(iy) >= 2 and len(icols) >= 3
            if flags["industry"]:
                yl, yf = iy[-1], iy[0]
                inds = sorted(icols.values(), key=lambda n: ("אחרים" in n, -(ser[yl].get(n) or 0), n))
                charts["industry"] = {"x": [str(y) for y in iy], "names": inds,
                                      "series": [[_r1(ser[y].get(n)) for y in iy] for n in inds]}
                tables["industry"] = [[str(y)] + [_p(ser[y].get(n)) for n in inds] for y in reversed(iy)]
                labels["industry_cols"] = ["שנה"] + inds
                labels["industry_note"] = (f"איך מתחלק המו\"פ שתעשיות הייצור מבצעות בעצמן בין הענפים, "
                                           f"{yf} עד {yl}, באחוזים (ללא כרייה וחציבה).")
                labels["industry_aria"] = f"הוצאות לביצוע עצמי של מו\"פ בענפי תעשייה, {yf} עד {yl}"
                lead = inds[0]
                lv, fv0 = ser[yl].get(lead), ser[yf].get(lead)
                if lv is not None and lv >= 40:
                    txt = f"ענף {lead} מבצע {_p(lv)} מהמו\"פ בתעשייה ב-{yl}"
                    if fv0 is not None and abs(lv - fv0) >= 3:
                        txt += f", לעומת {_p(fv0)} ב-{yf}"
                    faller = min((n for n in inds if n != lead and ser[yf].get(n) is not None
                                  and ser[yl].get(n) is not None),
                                 key=lambda n: (ser[yl][n] - ser[yf][n], n), default=None)
                    if faller and ser[yl][faller] - ser[yf][faller] <= -3:
                        txt += (f". חלקו של ענף {faller} ירד מ-{_p(ser[yf][faller])} "
                                f"ל-{_p(ser[yl][faller])}")
                    add("industry", txt + ".")

    # ── 11. OECD comparison ──────────────────────────────────────────────
    flags["oecd"] = False
    avg_gdp, avg_pc = None, None
    if "oecd_avg" in t:
        rows = t["oecd_avg"]
        hrow = next((i for i, r in enumerate(rows) if any("כאחוז מהתמ\"ג" in c for c in r)), None)
        if hrow is not None:
            gcol = cbs.col_after(rows[hrow], "כאחוז מהתמ\"ג", contains=True)
            pcol = cbs.col_after(rows[hrow], "לנפש", contains=True)
            for r in rows[hrow + 1:]:
                if any("OECD" in c and "ממוצע" in c for c in r):
                    avg_gdp, avg_pc = cbs.val(r, gcol), cbs.val(r, pcol)
                    break
    if "oecd" in t:
        rows = t["oecd"]
        h = cbs.row_with(rows, "מו\"פ כאחוז מהתמ\"ג", name="oecd", contains=True)
        gcol = cbs.col_after(rows[h], "כאחוז מהתמ\"ג", contains=True)
        pcol = cbs.col_after(rows[h], "הוצאה למו\"פ לנפש", contains=True)
        year = next((_block_year(r) for r in rows[:h + 1] if _block_year(r) is not None), None)
        lastc = len(rows[0]) - 1
        countries = []
        for r in rows[h + 1:]:
            nm = cbs.cell(r, lastc)
            g = cbs.val(r, gcol)
            if nm and HEB.search(nm) and g is not None:
                countries.append((nm, g, cbs.val(r, pcol)))
        countries.sort(key=lambda c: (-c[1], c[0]))
        isr = next((c for c in countries if c[0] == "ישראל"), None)
        flags["oecd"] = len(countries) >= 5 and isr is not None
        if flags["oecd"]:
            yr = f" ({year})" if year else ""
            charts["oecd"] = {"names": [c[0] for c in countries], "gdp": [c[1] for c in countries],
                              "avg": avg_gdp}
            tables["oecd"] = [[c[0], fmt.pct_of(c[1]), _mn(c[2])] for c in countries]
            labels["oecd_note"] = (f"ההוצאה הלאומית למו\"פ כאחוז מהתוצר המקומי הגולמי (תמ\"ג) בישראל "
                                   f"ובמדינות OECD נבחרות{yr}, לפי נתוני OECD"
                                   + (f". הקו המקווקו: ממוצע OECD ({fmt.pct_of(avg_gdp)})." if avg_gdp else "."))
            labels["oecd_aria"] = f"מו\"פ כאחוז מהתמ\"ג, ישראל ומדינות OECD{yr}"
            labels["oecd_table"] = f"מו\"פ כאחוז מהתמ\"ג והוצאה לנפש לפי מדינה{yr}"
            rank = [c[0] for c in countries].index("ישראל") + 1
            kpis["gdp"] = {"value": round(isr[1], 2), "display": fmt.pct_of(isr[1]),
                           "tone": "ok" if rank == 1 else "brand"}
            labels["gdp_kpi"] = f"מו\"פ כאחוז מהתמ\"ג בישראל{yr}"
            if rank == 1:
                second = countries[1]
                txt = (f"ישראל מובילה את מדינות OECD בהוצאה למו\"פ ביחס לתוצר: {fmt.pct_of(isr[1])} "
                       f"מהתמ\"ג{yr}, פי {fmt.num_he(isr[1] / second[1], 1)} מ{second[0]} שבמקום השני "
                       f"({fmt.pct_of(second[1])})")
                if avg_gdp:
                    txt += f" ופי {fmt.num_he(isr[1] / avg_gdp, 1)} מממוצע OECD ({fmt.pct_of(avg_gdp)})"
                add("oecd", txt + ".")
            else:
                add("oecd", f"ישראל במקום {_ordinal_m(rank)} מבין {len(countries)} המדינות בהשוואה בהוצאה "
                            f"למו\"פ ביחס לתוצר: {fmt.pct_of(isr[1])} מהתמ\"ג{yr}.")
            if isr[2] is not None:
                labels["oecd_pc"] = (f"ההוצאה למו\"פ לנפש בישראל: {fmt.int_he(isr[2])} דולר (בשווי כוח קנייה)"
                                     + (f", לעומת {fmt.int_he(avg_pc)} בממוצע OECD." if avg_pc else "."))

    # ── assemble ─────────────────────────────────────────────────────────
    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    headline = rel.get("HEADLINE") or ""
    if GARBLED.search(headline):
        headline = ""
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": headline,
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}

    real_txt = ""
    if flags["real"]:
        real_txt = f", {_bn(real[ry[-1]]['total'])} מיליארד במחירי {base_year}"
    labels["lede"] = (f"כמה משקיעה ישראל במחקר ופיתוח (מו\"פ), מי מבצע את המחקר ומי מממן אותו. הנתונים "
                      f"מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על ההוצאה הלאומית למו\"פ, "
                      f"ומתעדכנים עם כל הודעה חדשה. ב-{ly} ההוצאה הלאומית למו\"פ הייתה "
                      f"{_bn(tot_l)} מיליארד ₪ במחירים שוטפים{real_txt}.")
    summary = (f"ההוצאה הלאומית למחקר ופיתוח בישראל לפי הלמ\"ס: {_bn(tot_l)} מיליארד ₪ ב-{ly}"
               + (f", {fmt.pct(lc['business'] / tot_l)} ממנה במגזר העסקי" if lc["business"] else "")
               + (f"; {fmt.pct_of(kpis['gdp']['value'])} מהתמ\"ג" if "gdp" in kpis else "") + ".")
    desc = (f"ההוצאה הלאומית למו\"פ בישראל: {_bn(tot_l)} מיליארד ₪ ב-{ly}"
            + (f", שינוי ריאלי של {kpis['real']['display']}" if "real" in kpis else "")
            + (f", {kpis['gdp']['display']} מהתמ\"ג" if "gdp" in kpis else "")
            + ". לפי מגזר, מימון ומשרד.")
    first_year = min([cy[0]] + ([ry[0]] if ry else []))
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_year}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "ההוצאה הלאומית למחקר ופיתוח (מו\"פ) בישראל | הלמ\"ס",
                "description": desc,
                "name": "ההוצאה הלאומית למחקר ופיתוח בישראל",
                "alternate_names": ["הוצאה לאומית למו\"פ", "השקעה במחקר ופיתוח בישראל",
                                    "מו\"פ כאחוז מהתמ\"ג", "ההוצאה הלאומית למחקר ופיתוח אזרחי"],
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


_ORD = {2: "שנייה", 3: "שלישית", 4: "רביעית", 5: "חמישית", 6: "שישית", 7: "שביעית", 8: "שמינית",
        9: "תשיעית", 10: "עשירית"}
_ORD_M = {2: "שני", 3: "שלישי", 4: "רביעי", 5: "חמישי", 6: "שישי", 7: "שביעי", 8: "שמיני",
          9: "תשיעי", 10: "עשירי"}


def _ordinal(n):
    """'ה' + feminine ordinal word; past ten, 'ה-<n>'."""
    return "ה" + _ORD[n] if n in _ORD else f"ה-{n}"


def _ordinal_m(n):
    """'ה' + masculine ordinal word; past ten, 'ה-<n>'."""
    return "ה" + _ORD_M[n] if n in _ORD_M else f"ה-{n}"
