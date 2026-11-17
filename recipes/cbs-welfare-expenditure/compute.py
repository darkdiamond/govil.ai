"""ההוצאה הלאומית לרווחה: CBS's yearly release on national welfare spending.

The release is six tables ("לוח N - ...") and six chart-data sheets
("תרשים N. ..."). Their order has been stable since 2023, but CBS renumbers
other releases' tables between editions, so every table input (t1..t15, the
last three spare, all optional) is read with `cbs.grid` and recognised by
its title, never by its stem:

  fin_trend   תרשים: ... לפי מגזר מממן, במיליוני ש"ח, 2023-2011   total by financing sector, yearly
  fin_detail  לוח: ... לפי מגזר מממן (no "סוג שירות")            transfers between sectors, latest year
  service     לוח: ... לפי סוג שירות (no "מגזר")                production / transfers per service
  fin_service לוח: ... לפי מגזר מממן ולפי סוג שירות              who finances each service
                                                               (millions, or shares in older editions)
  op_service  לוח: ... לפי מגזר מבצע וסוג שירות (not באחוזים)    who delivers each service
  op_exptype  לוח: ... לפי מגזר מבצע וסוג הוצאה                  labour, operating costs, investment
  real        תרשים: ... במחירים קבועים                          services (excl. transfers), real terms
  op_trend    תרשים: ... לפי מגזר מבצע, במיליוני                  services by operating sector, yearly

The percentage tables and charts (לוח 5, תרשים 1, 3, 5) repeat numbers the
page already shows and are not read. An older edition put several years
in one table as separate sheets: the block whose title names the latest
year is used. `fin_trend` is required; any other missing table drops its
section. A recognised table whose header labels are gone raises.
"""
import re

from govlib import cbs, fmt

TITLE = re.compile(r"^(?:לוח|תרשים)\s*\d+")
HEB = re.compile("[א-ת]")
YEAR4 = re.compile(r"(?:19|20)\d\d")
STAR_YEAR = re.compile(r"^\s*\*\s*((?:19|20)\d\d)\s*$|^\s*((?:19|20)\d\d)\s*\*\s*$")

# Sector keys, display names (financing / operating sectors share them).
SECTOR_NAMES = {
    "gov": "ממשלה",
    "gov_min": "משרדי הממשלה",
    "nii": "ביטוח לאומי",
    "local": "רשויות מקומיות",
    "pub_npo": "מלכ\"רים ציבוריים",
    "priv_npo": "מלכ\"רים פרטיים",
    "business": "עסקים",
    "hh": "משקי בית",
    "abroad": "חו\"ל",
}
SECTOR_PHRASE = {
    "gov": "הממשלה (כולל ביטוח לאומי והרשויות המקומיות)",
    "gov_min": "משרדי הממשלה",
    "nii": "הביטוח הלאומי",
    "local": "הרשויות המקומיות",
    "pub_npo": "המלכ\"רים הציבוריים",
    "priv_npo": "המלכ\"רים הפרטיים",
    "business": "המגזר העסקי",
    "hh": "משקי הבית",
    "abroad": "גורמים בחו\"ל",
}
SECTOR_TO = {
    "gov_min": "למשרדי הממשלה",
    "nii": "לביטוח הלאומי",
    "local": "לרשויות המקומיות",
    "pub_npo": "למלכ\"רים הציבוריים",
    "priv_npo": "למלכ\"רים הפרטיים",
    "business": "למגזר העסקי",
    "hh": "למשקי הבית",
    "abroad": "לגורמים בחו\"ל",
}


def verb(key, masc, fem, plural):
    """The verb form that agrees with a sector phrase."""
    if key == "gov":
        return fem
    if key in ("nii", "business"):
        return masc
    return plural


FIN_TREND_ORDER = ("gov", "pub_npo", "priv_npo", "business", "hh", "abroad")
OP_ORDER = ("gov_min", "nii", "local", "pub_npo", "priv_npo", "business")
DETAIL_ORDER = ("gov_min", "nii", "local", "pub_npo", "priv_npo", "business", "hh", "abroad")
SANKEY_MIN = 100.0  # NIS millions: smaller transfers are left out of the flow chart


def sector_key(cell):
    """The sector a header cell names, or None (a total, a group header)."""
    c = cbs.clean(cell)
    if not c or c.startswith(("מגזר ממשלה", "מגזר הממשלה", "סך", "סה\"כ")):
        return None
    if c.startswith("משרדי ממשלה"):
        return "gov_min"
    if c.startswith("ביטוח לאומי"):
        return "nii"
    if c.startswith("רשויות מקומיות"):
        return "local"
    if c.startswith(("מלכ\"ר ציבורי", "מלכ\"רים ציבוריים")):
        return "pub_npo"
    if c.startswith(("מלכ\"ר פרטי", "מלכ\"רים פרטיים")):
        return "priv_npo"
    if c.startswith("עסקי"):
        return "business"
    if c.startswith("משקי בית"):
        return "hh"
    if c.startswith(("שאר העולם", "חו\"ל")):
        return "abroad"
    if c == "ממשלה" or c.startswith("ממשלה "):
        return "gov"
    return None


def _year(v):
    v = cbs.clean(v)
    return int(v) if cbs.YEAR.match(v) else None


def _title_of(rows, i):
    nxt = rows[i + 1] if i + 1 < len(rows) else []
    return " ".join(c for c in list(rows[i]) + list(nxt) if HEB.search(c) or YEAR4.search(c))


def _blocks(rows):
    """[(title, block rows)] — one per titled table in the grid."""
    starts = [i for i, r in enumerate(rows) if any(TITLE.match(c) for c in r)]
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(rows)
        out.append((_title_of(rows, s), rows[s:e]))
    return out


def _kind(title):
    if title.startswith("לוח"):
        if "סוג הוצאה" in title:
            return "op_exptype"
        if "מגזר מבצע" in title and "סוג שירות" in title:
            return None if "באחוזים" in title else "op_service"
        if "מגזר מממן" in title and "סוג שירות" in title:
            return "fin_service"
        if "מגזר מממן" in title:
            return "fin_detail"
        if "סוג שירות" in title:
            return "service"
        return None
    if title.startswith("תרשים"):
        if "מחירים קבועים" in title:
            return "real"
        if "באחוזים" in title or "סוג שירות" in title:
            return None
        if "מגזר מממן" in title:
            return "fin_trend"
        if "מגזר מבצע" in title:
            return "op_trend"
    return None


def _raw_newest(df):
    """Raw (uncleaned) cells of the newest edition, in sheet and row order —
    the same edition `cbs.grid` reads, for the "*" preliminary marks that
    `cbs.clean` strips."""
    def key(n):
        m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d{4})\s*", str(n))
        return ((int(m.group(2)), int(m.group(1))) if m else (0, 0), str(n))
    latest = df["RELEASE_DATE"].max()
    d = df[df["RELEASE_DATE"] == latest]
    newest = max(d["RELEASE_NO"].unique(), key=key)
    d = d[d["RELEASE_NO"] == newest].sort_values(["SHEET_NO", "ROW"], kind="stable")
    cols = sorted((c for c in d.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))
    return [[str(v) for v in r] for r in d[cols].itertuples(index=False)]


def _tables(frames):
    """{kind: (stem, title, rows, year)} for the tables the page reads."""
    found = {}
    stems = sorted((k for k in frames if re.fullmatch(r"t\d+[a-z]?", k)),
                   key=lambda k: (int(re.sub(r"\D", "", k)), k))
    for stem in stems:
        df = frames[stem]
        if df.empty:
            continue
        rows = cbs.grid(df, stem)
        cands = []
        for title, block in _blocks(rows):
            kind = _kind(title)
            if not kind:
                continue
            years = [int(y) for y in YEAR4.findall(title)]
            cands.append((kind, max(years) if years else 0, title, block))
        for kind in sorted({c[0] for c in cands}):
            best = max((c for c in cands if c[0] == kind), key=lambda c: c[1])
            if kind not in found or best[1] > found[kind][3]:
                found[kind] = (stem, best[2], best[3], best[1])
    return found


def _sector_cols(rows, start, stop):
    """{col: sector key} from the header rows rows[start:stop] (first hit per key)."""
    cols, seen = {}, set()
    for r in rows[start:stop]:
        for j, c in enumerate(r):
            k = sector_key(c)
            if k and k not in seen and j not in cols:
                cols[j] = k
                seen.add(k)
    return cols


def _label_rows(rows, start, label_col):
    """(label, row) for the data rows below a header: rows with a Hebrew label
    and at least one number, stopping at the notes."""
    out = []
    for r in rows[start:]:
        lab = cbs.clean(cbs.cell(r, label_col))
        if lab.startswith(("הערה", "הערות", "מקור")):
            break
        if not HEB.search(lab):
            continue
        if not any(cbs.num(c) is not None for j, c in enumerate(r) if j != label_col):
            continue
        out.append((lab, r))
    return out


def _label(lab):
    """A display label: no "מזה:" lead-in, no "(לנמ"א)" (not elsewhere classified)."""
    lab = re.sub(r"^(?:מזה|מהם)\s*:?\s*", "", lab)
    lab = re.sub(r"\s*\(?ל?נמ\"א\)?", "", lab)
    return re.sub(r"\s+", " ", lab).strip()


def _bn(v, d=1):
    return fmt.num_he(v / 1000, d)


def _p(v, d=1):
    return f"{v:.{d}f}%"


def _date_he(v):
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)", str(v))
    if not m:
        return str(v)
    return f"{int(m.group(3))} ב{fmt.MONTHS_HE[int(m.group(2)) - 1]} {m.group(1)}"


def _chg(a, b):
    return (b - a) / a if a else None


# ── parsers ───────────────────────────────────────────────────────────────
def _fin_trend(rows):
    h = next((i for i, r in enumerate(rows) if any(cbs.clean(c).startswith("שנה") for c in r)), None)
    if h is None:
        raise ValueError("fin_trend: header label 'שנה' not found")
    cols = _sector_cols(rows, h, h + 1)
    if not {"gov", "hh", "business"} <= set(cols.values()):
        raise ValueError("fin_trend: sector header labels not found")
    ycol = cbs.best_col(rows[h + 1:], lambda v: bool(cbs.YEAR.match(v)))
    data = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, ycol)) if ycol is not None else None
        if y is None:
            continue
        vals = {k: cbs.val(r, j) for j, k in cols.items()}
        if all(v is None for v in vals.values()):
            continue
        data[y] = {k: (v or 0.0) for k, v in vals.items()}
    keys = [k for k in FIN_TREND_ORDER if k in cols.values()]
    return data, keys


def _op_trend(rows):
    h = next((i for i, r in enumerate(rows) if sum(1 for c in r if sector_key(c)) >= 3), None)
    if h is None:
        raise ValueError("op_trend: sector header labels not found")
    cols = _sector_cols(rows, h, h + 1)
    ycol = cbs.best_col(rows[h + 1:], lambda v: bool(cbs.YEAR.match(v)))
    data = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, ycol)) if ycol is not None else None
        if y is None:
            continue
        vals = {k: cbs.val(r, j) for j, k in cols.items()}
        if all(v is None for v in vals.values()):
            continue
        data[y] = {k: (v or 0.0) for k, v in vals.items()}
    keys = [k for k in ("gov", "pub_npo", "priv_npo", "business") if k in cols.values()]
    return data, keys


def _real(rows, raw):
    h = next((i for i, r in enumerate(rows) if any(c.startswith("מחירים קבועים") for c in r)), None)
    if h is None:
        raise ValueError("real: header label 'מחירים קבועים' not found")
    vcol = next(j for j, c in enumerate(rows[h]) if c.startswith("מחירים קבועים"))
    ycol = cbs.best_col(rows[h + 1:], lambda v: bool(cbs.YEAR.match(v)), exclude=(vcol,))
    data = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, ycol)) if ycol is not None else None
        v = cbs.val(r, vcol)
        if y is not None and v is not None:
            data[y] = v
    prelim = set()
    for r in raw:
        for c in r:
            m = STAR_YEAR.match(c)
            if m:
                prelim.add(int(m.group(1) or m.group(2)))
    return data, prelim


def _fin_detail(rows):
    h = cbs.row_with(rows, "מגזר מממן", name="fin_detail")
    lab = cbs.col_after(rows[h], "מגזר מממן")
    c_tot = cbs.col_after(rows[h], "סך מימון", 0, contains=True)
    c_prod = cbs.col_after(rows[h], "ייצור שירותים", 0, contains=True)
    c_in = cbs.col_after(rows[h], "העברות ממגזרים אחרים", 0, contains=True)
    sub = rows[h + 1] if h + 1 < len(rows) else []
    c_out = cbs.col_after(sub, "סך העברות למגזרים אחרים", 0, contains=True)
    to = {j: k for j, k in _sector_cols(rows, h + 1, h + 2).items()}
    if "hh" not in to.values():
        raise ValueError("fin_detail: recipient column 'משקי בית' not found")
    grand, secs = None, {}
    for label, r in _label_rows(rows, h + 2, lab):
        rec = {"total": cbs.val(r, c_tot), "prod": cbs.val(r, c_prod), "out": cbs.val(r, c_out),
               "in": cbs.val(r, c_in), "to": {k: cbs.val(r, j) or 0.0 for j, k in to.items()}}
        if label.startswith("סך כולל"):
            grand = rec
            continue
        k = sector_key(label)
        if k and k != "gov" and k not in secs:
            secs[k] = rec
    return grand, secs


def _service(rows):
    h = cbs.row_with(rows, "סוג שירות", name="service")
    lab = cbs.col_after(rows[h], "סוג שירות")
    c_tot = cbs.col_after(rows[h], "סך מימון", 0, contains=True)
    c_prod = cbs.col_after(rows[h], "ייצור שירותים", 0, contains=True)
    c_tr = cbs.col_after(rows[h], "העברות למשקי בית", 0, contains=True)
    grand, items = None, []
    for label, r in _label_rows(rows, h + 1, lab):
        tot = cbs.val(r, c_tot)
        if tot is None:
            continue
        rec = (label, cbs.val(r, c_prod) or 0.0, cbs.val(r, c_tr) or 0.0, tot)
        if label.startswith("סך כולל"):
            grand = rec
        else:
            items.append(rec)
    return grand, items


def _hier(items):
    """Split service rows into top-level rows and the parts of each "- סה"כ" row."""
    tops, parts, skip = [], {}, set()
    for i, it in enumerate(items):
        if i in skip:
            continue
        lab = it[0]
        if "סה\"כ" in lab:
            tot = it[-1]
            acc, sub = 0.0, []
            for k in range(i + 1, min(len(items), i + 8)):
                acc += items[k][-1]
                sub.append(k)
                if abs(acc - tot) <= max(2.0, abs(tot) * 0.005):
                    break
            else:
                sub = []
            parts[i] = sub
            skip.update(sub)
        tops.append(i)
    return tops, parts


def _short(lab):
    return re.sub(r"\s*-\s*סה\"כ\s*$", "", _label(lab)).strip()


def _fin_service(rows, title):
    h = cbs.row_with(rows, "סוג שירות", name="fin_service")
    lab = cbs.col_after(rows[h], "סוג שירות")
    c_tot = cbs.col_after(rows[h], "מימון (נטו)", 0, contains=True)
    cols = _sector_cols(rows, h + 1, h + 2)
    if len(cols) < 5:
        raise ValueError("fin_service: sector header labels not found")
    share_mode = "באחוזים" in title
    out = []
    for label, r in _label_rows(rows, h + 2, lab):
        tot = cbs.val(r, c_tot)
        if not tot:
            continue
        vals = {}
        for j, k in cols.items():
            v = cbs.val(r, j) or 0.0
            vals[k] = v * 100 if share_mode else v / tot * 100
        out.append((label, tot, vals))
    keys = [k for k in DETAIL_ORDER if k in cols.values()]
    return out, keys


def _op_table(rows, label_text, name):
    h = cbs.row_with(rows, label_text, name=name)
    lab = cbs.col_after(rows[h], label_text)
    c_tot = None
    for r in rows[h:h + 4]:
        for j, c in enumerate(r):
            if j != lab and c.startswith("סך כולל"):
                c_tot = j
                break
        if c_tot is not None:
            break
    if c_tot is None:
        raise ValueError(f"{name}: header label 'סך כולל' not found")
    cols = _sector_cols(rows, h, h + 4)
    if not {"business", "priv_npo", "gov_min"} <= set(cols.values()):
        raise ValueError(f"{name}: operating-sector header labels not found")
    grand, out = None, []
    for label, r in _label_rows(rows, h + 1, lab):
        tot = cbs.val(r, c_tot)
        if tot is None:
            continue
        rec = (label, tot, {k: cbs.val(r, j) or 0.0 for j, k in cols.items()})
        if label.startswith("סך כולל"):
            grand = rec
        else:
            out.append(rec)
    keys = [k for k in OP_ORDER if k in cols.values()]
    return grand, out, keys


# ── compute ───────────────────────────────────────────────────────────────
def compute(frames):
    T = _tables(frames)
    if "fin_trend" not in T:
        raise ValueError("no financing-sector chart table (תרשים ... לפי מגזר מממן, במיליוני) in the newest edition")
    rel = cbs.latest_release(frames["releases"])
    kpis, charts, tables, labels, flags, callouts, insights = {}, {}, {}, {}, {}, {}, []

    def add(key, text, callout=None):
        if text:
            insights.append({"id": key, "text_he": text})
            if callout:
                callouts[callout] = text

    # ── total by financing sector, yearly ────────────────────────────────
    ft, fkeys = _fin_trend(T["fin_trend"][2])
    ys = sorted(ft)
    if len(ys) < 2:
        raise ValueError("fin_trend: fewer than 2 years")
    ly = ys[-1]
    tot = {y: sum(ft[y].values()) for y in ys}
    charts["trend"] = {"x": [str(y) for y in ys], "names": [SECTOR_NAMES[k] for k in fkeys],
                       "series": [[round(ft[y][k] / 1000, 2) for y in ys] for k in fkeys],
                       "total": [round(tot[y] / 1000, 2) for y in ys]}
    tables["trend"] = [[str(y), _bn(tot[y])] + [_bn(ft[y][k]) for k in fkeys] for y in ys]
    labels["trend_cols"] = ["שנה", "סך הכול"] + [SECTOR_NAMES[k] for k in fkeys]
    labels["trend_aria"] = f"ההוצאה הלאומית לרווחה לפי מגזר מממן, {ys[0]} עד {ly}, במיליארדי ש\"ח"
    kpis["total"] = {"value": round(tot[ly] / 1000, 1), "display": _bn(tot[ly]), "tone": "brand"}
    labels["total_kpi"] = f"ההוצאה הלאומית לרווחה ב-{ly} (מיליארדי ש\"ח)"
    py = ly - 1 if (ly - 1) in tot else None
    if py is not None:
        g = _chg(tot[py], tot[ly])
        kpis["growth"] = {"value": round(g * 100, 1), "display": fmt.signed_pct(g), "tone": "brand"}
        labels["growth_kpi"] = f"שינוי בהוצאה ב-{ly} לעומת {py} (מחירים שוטפים)"
    first = ys[0]
    mult = tot[ly] / tot[first] if tot[first] else None
    txt = (f"ההוצאה הלאומית לרווחה הסתכמה ב-{ly} ב-{_bn(tot[ly])} מיליארד ש\"ח (במחירים שוטפים, כולל "
           f"העברות למשקי בית)")
    if py is not None:
        g = _chg(tot[py], tot[ly])
        txt += f", {'עלייה' if g > 0 else 'ירידה'} של {fmt.pct(abs(g))} לעומת {py}"
    if mult and len(ys) >= 5:
        txt += f". מאז {first} ההוצאה גדלה פי {mult:.1f}"
    add("trend", txt + ".")
    # The sharpest one-year jump, when it stands out and was partly reversed.
    ch = {y: _chg(tot[y - 1], tot[y]) for y in ys[1:] if (y - 1) in tot}
    if len(ch) >= 4:
        jy = max(ch, key=lambda y: (ch[y], y))
        rest = sorted(v for y, v in ch.items() if y != jy)
        med = rest[len(rest) // 2]
        if ch[jy] >= 0.15 and ch[jy] >= 2 * med and (jy + 1) in ch and ch[jy + 1] < 0:
            gk = "gov" if "gov" in fkeys else None
            t2 = (f"ב-{jy} זינקה ההוצאה ב-{fmt.pct(ch[jy])} בשנה אחת, ובשנה שאחריה ירדה ב-{fmt.pct(abs(ch[jy + 1]))}")
            if gk:
                dg = ft[jy][gk] - ft[jy - 1][gk]
                share = dg / (tot[jy] - tot[jy - 1]) if tot[jy] != tot[jy - 1] else None
                if share is not None and share >= 0.95:
                    t2 += ". כמעט כל הגידול באותה שנה מומן בידי הממשלה"
                elif share is not None and share >= 0.6:
                    t2 += f". {fmt.pct(share, 0)} מהגידול באותה שנה מומנו בידי הממשלה"
            add("jump", t2 + ".", "trend")
    if "gov" in fkeys:
        s0 = ft[first]["gov"] / tot[first] * 100
        s1 = ft[ly]["gov"] / tot[ly] * 100
        kpis["gov"] = {"value": round(s1, 1), "display": _p(s1), "tone": "brand"}
        labels["gov_kpi"] = f"חלק הממשלה במימון ההוצאה ב-{ly}"
        hh1 = ft[ly].get("hh", 0) / tot[ly] * 100
        if abs(s1 - s0) >= 1:
            add("gov_share", f"הממשלה (כולל ביטוח לאומי והרשויות המקומיות) מימנה ב-{ly} {_p(s1)} מההוצאה "
                             f"לרווחה, לעומת {_p(s0)} ב-{first}. משקי הבית מימנו {_p(hh1)}.")
        else:
            add("gov_share", f"הממשלה (כולל ביטוח לאומי והרשויות המקומיות) מימנה ב-{ly} {_p(s1)} מההוצאה "
                             f"לרווחה, כמו ב-{first} בקירוב. משקי הבית מימנו {_p(hh1)}.")
    labels["trend_note"] = (f"סך ההוצאה הלאומית לרווחה בכל שנה מאז {first}, במיליארדי ש\"ח במחירים שוטפים, "
                            f"לפי המגזר שמימן אותה. \"ממשלה\" כולל את משרדי הממשלה, הביטוח הלאומי והרשויות "
                            f"המקומיות. מימון הוא נטו: מה שמגזר הוציא בעצמו ועוד מה שהעביר לאחרים, פחות מה שקיבל.")

    # ── service types ────────────────────────────────────────────────────
    flags["service"] = False
    if "service" in T:
        grand, items = _service(T["service"][2])
        if items:
            tops, parts = _hier(items)
            gt = grand[3] if grand else sum(items[i][3] for i in tops)
            order = sorted(tops, key=lambda i: (-items[i][3], items[i][0]))
            charts["service"] = {"names": [_short(items[i][0]) for i in order],
                                 "prod": [round(items[i][1] / 1000, 2) for i in order],
                                 "trans": [round(items[i][2] / 1000, 2) for i in order]}
            tables["service"] = [[_short(items[i][0]), _bn(items[i][3]), _bn(items[i][1]), _bn(items[i][2]),
                                  _p(items[i][3] / gt * 100)] for i in order]
            labels["service_aria"] = f"ההוצאה הלאומית לרווחה ב-{T['service'][3] or ly} לפי סוג שירות"
            sy = T["service"][3] or ly
            labels["service_year"] = str(sy)
            flags["service"] = True
            lead = order[0]
            lshare = items[lead][3] / gt
            sec = order[1] if len(order) > 1 else None
            t = (f"היעד הגדול ביותר של ההוצאה לרווחה הוא {_short(items[lead][0])}: {_bn(items[lead][3])} "
                 f"מיליארד ש\"ח ב-{sy}, {fmt.pct(lshare)} מהסך")
            if sec is not None:
                t += f". במקום השני: {_short(items[sec][0])}, עם {fmt.pct(items[sec][3] / gt)}"
            add("service", t + ".", "service")
            if grand:
                tr = grand[2] / grand[3]
                kpis["transfers"] = {"value": round(tr * 100, 1), "display": fmt.pct(tr), "tone": "brand"}
                labels["transfers_kpi"] = f"מההוצאה ב-{sy} היא העברות כספיות למשקי בית"
                add("transfers", f"{fmt.pct(tr)} מההוצאה לרווחה ב-{sy} ({_bn(grand[2])} מיליארד ש\"ח) הן העברות "
                                 f"כספיות למשקי בית, כמו קצבאות ופנסיות. רק {_bn(grand[1])} מיליארד ש\"ח הוצאו "
                                 f"על הפעלת שירותים.")
            # Parts of the largest "- סה"כ" group (senior citizens).
            grp = [i for i in tops if parts.get(i)]
            if grp:
                gi = max(grp, key=lambda i: (items[i][3], -i))
                sub = parts[gi]
                gname = _short(items[gi][0])
                flags["parts"] = True
                charts["parts"] = {"names": [_label(items[k][0]) for k in sub],
                                   "values": [round(items[k][3] / 1000, 2) for k in sub]}
                tables["parts"] = [[_label(items[k][0]), _bn(items[k][3]), _p(items[k][3] / items[gi][3] * 100)]
                                   for k in sub]
                labels["parts_title"] = f"ההוצאה על {gname}: פירוט"
                labels["parts_note"] = (f"מה כוללת ההוצאה על {gname} ({_bn(items[gi][3])} מיליארד ש\"ח ב-{sy}): "
                                        f"כל רכיב במיליארדי ש\"ח.")
                labels["parts_aria"] = f"פירוט ההוצאה על {gname} ב-{sy}"
                kpis["parts"] = {"value": round(items[gi][3] / gt * 100, 1),
                                 "display": _p(items[gi][3] / gt * 100), "tone": "brand"}
                labels["parts_kpi"] = f"מההוצאה מיועדת ל{gname}"
                big = max(sub, key=lambda k: (items[k][3], -k))
                add("parts", f"מתוך {_bn(items[gi][3])} מיליארד ש\"ח שהוצאו על {gname}, "
                             f"{_bn(items[big][3])} מיליארד ({fmt.pct(items[big][3] / items[gi][3])}) הם "
                             f"{_label(items[big][0])}.", "parts")
    flags.setdefault("parts", False)

    # ── transfers between sectors (sankey) ───────────────────────────────
    flags["flows"] = False
    if "fin_detail" in T:
        grand, secs = _fin_detail(T["fin_detail"][2])
        dy = T["fin_detail"][3] or ly
        links = []
        for k in DETAIL_ORDER:
            if k not in secs:
                continue
            for t in DETAIL_ORDER:
                v = secs[k]["to"].get(t, 0.0)
                if v >= SANKEY_MIN:
                    links.append((k, t, v))
        if links:
            flags["flows"] = True
            srcs = [k for k in DETAIL_ORDER if any(l[0] == k for l in links)]
            dsts = [k for k in DETAIL_ORDER if any(l[1] == k for l in links)]
            charts["flows"] = {
                "nodes": [{"name": "מ:" + SECTOR_NAMES[k]} for k in srcs] + [{"name": "אל:" + SECTOR_NAMES[k]} for k in dsts],
                "links": [{"source": "מ:" + SECTOR_NAMES[a], "target": "אל:" + SECTOR_NAMES[b],
                           "value": round(v, 0)} for a, b, v in links]}
            tables["flows"] = [[SECTOR_NAMES[a], SECTOR_NAMES[b], fmt.int_he(v)]
                               for a, b, v in sorted(links, key=lambda l: (-l[2], l[0], l[1]))]
            labels["flows_aria"] = f"העברות כספיות בין המגזרים בתחום הרווחה, {dy}"
            labels["flows_note"] = (f"מי מעביר כסף למי בתחום הרווחה ב-{dy}, במיליוני ש\"ח: משמאל המגזר המעביר, "
                                    f"מימין המגזר המקבל. העברות של פחות מ-{int(SANKEY_MIN)} מיליון ש\"ח לא מוצגות.")
            a, b, v = max(links, key=lambda l: (l[2], l[0], l[1]))
            t = (f"ההעברה הגדולה ביותר בתחום הרווחה ב-{dy}: {SECTOR_PHRASE[a]} "
                 f"{verb(a, 'העביר', 'העבירה', 'העבירו')} {SECTOR_TO[b]} "
                 f"{_bn(v)} מיליארד ש\"ח")
            if "nii" in secs and secs["nii"]["in"]:
                frm = [(secs[k]["to"].get("nii", 0.0), k) for k in ("gov_min", "hh") if k in secs]
                frm = [(v, k) for v, k in frm if v >= SANKEY_MIN]
                t += f". הביטוח הלאומי קיבל ממגזרים אחרים {_bn(secs['nii']['in'])} מיליארד ש\"ח"
                if frm:
                    t += ", בהם " + fmt.join_he([f"{_bn(v)} מיליארד מ{SECTOR_PHRASE[k]}" for v, k in frm])
            add("flows", t + ".", "flows")

    # ── who finances each service (heatmap) ──────────────────────────────
    flags["finsvc"] = False
    if "fin_service" in T:
        fs, skeys = _fin_service(T["fin_service"][2], T["fin_service"][1])
        if fs and skeys:
            flags["finsvc"] = True
            fy = T["fin_service"][3] or ly
            names = [_short(l) + (" (סה\"כ)" if "סה\"כ" in l else "") for l, _, _ in fs]
            charts["finsvc"] = {"rows": names, "cols": [SECTOR_NAMES[k] for k in skeys],
                                "cells": [[ci, ri, round(v[k], 1)] for ri, (_, _, v) in enumerate(fs)
                                          for ci, k in enumerate(skeys)]}
            tables["finsvc"] = [[names[i], _bn(t)] + [_p(v[k]) for k in skeys] for i, (l, t, v) in enumerate(fs)]
            labels["finsvc_cols"] = ["סוג שירות", "סך המימון (מיליארדי ש\"ח)"] + [SECTOR_NAMES[k] for k in skeys]
            labels["finsvc_aria"] = f"חלקו של כל מגזר במימון כל סוג שירות רווחה, {fy}, באחוזים"
            labels["finsvc_note"] = (f"מי מממן כל סוג שירות ב-{fy}: חלקו של כל מגזר במימון הנטו, באחוזים "
                                     f"(בכל שורה הסך הוא 100%). ערך שלילי פירושו שהמגזר קיבל יותר משהוציא "
                                     f"על אותו שירות, למשל ביטוח לאומי שגובה דמי ביטוח ומשלם קצבאות.")
            # The service most dependent on non-government money.
            gk = [k for k in ("gov_min", "nii", "local") if k in skeys]
            if gk:
                ng = [(100 - sum(v[k] for k in gk), _label(l), v) for l, t, v in fs
                      if not l.startswith("אחר") and "סה\"כ" not in l]
                if ng:
                    s, name, v = max(ng, key=lambda x: (x[0], x[1]))
                    top = max((k for k in skeys if k not in gk), key=lambda k: (v[k], k))
                    if s >= 50:
                        add("finsvc", f"סוג השירות שהכי פחות נשען על הממשלה הוא {name}: {_p(s)} ממימונו ב-{fy} "
                                      f"הגיעו ממקורות שאינם ממשלתיים, בעיקר מ{SECTOR_PHRASE[top]} "
                                      f"({_p(v[top])}).", "finsvc")

    # ── services excluding transfers: real terms ─────────────────────────
    flags["real"] = False
    if "real" in T:
        rd, prelim = _real(T["real"][2], _raw_newest(frames[T["real"][0]]))
        rys = sorted(rd)
        if len(rys) >= 3:
            flags["real"] = True
            rly = rys[-1]
            charts["real"] = {"x": [str(y) + ("*" if y in prelim else "") for y in rys],
                              "y": [round(rd[y] / 1000, 2) for y in rys],
                              "prelim": [y in prelim for y in rys]}
            tables["real"] = [[str(y) + (" (אומדן מוקדם)" if y in prelim else ""), _bn(rd[y]),
                               fmt.signed_pct(_chg(rd[y - 1], rd[y])) if (y - 1) in rd else ""] for y in rys]
            labels["real_aria"] = f"ההוצאה על שירותי רווחה (ללא העברות) במחירים קבועים, {rys[0]} עד {rly}"
            labels["real_note"] = ("ההוצאה על הפעלת שירותי רווחה בלבד (בלי העברות כספיות למשקי בית), במיליארדי "
                                   "ש\"ח במחירים קבועים, כלומר בניכוי עליית המחירים."
                                   + (f" נתון {max(prelim)} הוא אומדן מוקדם." if prelim & set(rys) else ""))
            if (rly - 1) in rd:
                g = _chg(rd[rly - 1], rd[rly])
                kpis["real"] = {"value": round(g * 100, 1), "display": fmt.signed_pct(g), "tone": "brand"}
                labels["real_kpi"] = (f"שינוי ריאלי בהוצאה על שירותי רווחה, {rly}"
                                      + (" (אומדן מוקדם)" if rly in prelim else ""))
            g_all = _chg(rd[rys[0]], rd[rly])
            dips = [y for y in rys[1:] if (y - 1) in rd and rd[y] < rd[y - 1]]
            t = (f"במחירים קבועים, ההוצאה על שירותי רווחה (ללא העברות) {'גדלה' if g_all > 0 else 'קטנה'} "
                 f"ב-{fmt.pct(abs(g_all), 0)} בין {rys[0]} ל-{rly}")
            if rly in prelim:
                t += " (נתון השנה האחרונה הוא אומדן מוקדם)"
            if dips:
                t += (f". {'השנה היחידה שבה ירדה' if len(dips) == 1 else 'השנים היחידות שבהן ירדה'}: "
                      f"{fmt.join_he([str(y) for y in dips])}")
            add("real", t + ".", "real")

    # ── operating sectors, yearly ────────────────────────────────────────
    flags["optrend"] = False
    if "op_trend" in T:
        od, okeys = _op_trend(T["op_trend"][2])
        oys = sorted(od)
        if len(oys) >= 3 and okeys:
            flags["optrend"] = True
            oly = oys[-1]
            otot = {y: sum(od[y][k] for k in okeys) for y in oys}
            charts["optrend"] = {"x": [str(y) for y in oys], "names": [SECTOR_NAMES[k] for k in okeys],
                                 "series": [[round(od[y][k] / 1000, 2) for y in oys] for k in okeys]}
            tables["optrend"] = [[str(y), _bn(otot[y])] + [_bn(od[y][k]) for k in okeys] for y in oys]
            labels["optrend_cols"] = ["שנה", "סך הכול"] + [SECTOR_NAMES[k] for k in okeys]
            labels["optrend_aria"] = f"ההוצאה על שירותי רווחה לפי מגזר מבצע, {oys[0]} עד {oly}"
            labels["optrend_note"] = ("מי מפעיל בפועל את שירותי הרווחה: ההוצאה על הפעלת השירותים (ללא העברות "
                                      "למשקי בית) לפי המגזר שמבצע אותם, במיליארדי ש\"ח במחירים שוטפים. "
                                      "\"ממשלה\" כולל משרדי ממשלה, ביטוח לאומי ורשויות מקומיות.")
            lead = max(okeys, key=lambda k: (od[oly][k], k))
            ls = od[oly][lead] / otot[oly]
            t = (f"{SECTOR_PHRASE[lead]} {verb(lead, 'מפעיל', 'מפעילה', 'מפעילים')} את החלק הגדול ביותר "
                 f"של שירותי הרווחה: {fmt.pct(ls)} מההוצאה על שירותים ב-{oly} ({_bn(od[oly][lead])} מיליארד ש\"ח)")
            o0 = oys[0]
            if otot[o0] and od[o0][lead]:
                s0 = od[o0][lead] / otot[o0]
                if abs(ls - s0) >= 0.01:
                    t += f", לעומת {fmt.pct(s0)} ב-{o0}"
            add("optrend", t + ".", "optrend")

    # ── who delivers each service ────────────────────────────────────────
    flags["opsvc"] = False
    if "op_service" in T:
        g, rows_, okeys = _op_table(T["op_service"][2], "סוג שירות", "op_service")
        rows_ = [r for r in rows_ if r[1] and r[1] > 0 and "סה\"כ" not in r[0]]
        if rows_ and okeys:
            flags["opsvc"] = True
            sy2 = T["op_service"][3] or ly
            rows_ = sorted(rows_, key=lambda r: (-r[1], r[0]))
            charts["opsvc"] = {"names": [_label(r[0]) for r in rows_],
                               "keys": [SECTOR_NAMES[k] for k in okeys],
                               "series": [[round(r[2][k] / r[1] * 100, 1) for r in rows_] for k in okeys]}
            tables["opsvc"] = [[_label(r[0]), _bn(r[1])] + [_p(r[2][k] / r[1] * 100) for k in okeys] for r in rows_]
            labels["opsvc_cols"] = ["סוג שירות", "סך (מיליארדי ש\"ח)"] + [SECTOR_NAMES[k] for k in okeys]
            labels["opsvc_aria"] = f"חלקו של כל מגזר מבצע בהפעלת כל סוג שירות רווחה, {sy2}"
            labels["opsvc_note"] = (f"מי מפעיל כל סוג שירות ב-{sy2}: חלקו של כל מגזר בהוצאה על הפעלת השירות "
                                    f"(ללא העברות כספיות), באחוזים. קצבאות ופנסיות אינן שירות מופעל ולכן לא מופיעות.")

    # ── type of expenditure ──────────────────────────────────────────────
    flags["cost"] = False
    if "op_exptype" in T:
        g, rows_, okeys = _op_table(T["op_exptype"][2], "סוג הוצאה", "op_exptype")
        leaves = [r for r in rows_ if "סה\"כ" not in r[0]]
        if leaves and okeys:
            flags["cost"] = True
            cy = T["op_exptype"][3] or ly
            charts["cost"] = {"names": [SECTOR_NAMES[k] for k in okeys],
                              "keys": [_label(r[0]) for r in leaves],
                              "series": [[round(r[2][k] / 1000, 2) for k in okeys] for r in leaves]}
            tables["cost"] = [[_label(r[0]), _bn(r[1])] + [_bn(r[2][k]) for k in okeys] for r in leaves]
            labels["cost_cols"] = ["סוג הוצאה", "סך הכול"] + [SECTOR_NAMES[k] for k in okeys]
            labels["cost_aria"] = f"ההוצאה על שירותי רווחה לפי סוג הוצאה ומגזר מבצע, {cy}"
            labels["cost_note"] = (f"על מה מוציאים מפעילי שירותי הרווחה ב-{cy}: שכר, הוצאות תפעול, בלאי והשקעות "
                                   f"בבנייה ובציוד, לפי מגזר מבצע, במיליארדי ש\"ח.")
            wage = next((r for r in leaves if r[0].startswith("שכר")), None)
            gt = g[1] if g else sum(r[1] for r in leaves)
            if wage and gt:
                ws = wage[1] / gt
                per = {k: wage[2][k] / sum(r[2][k] for r in leaves) for k in okeys
                       if sum(r[2][k] for r in leaves) > 0}
                t = f"שכר העובדים הוא {fmt.pct(ws)} מההוצאה על הפעלת שירותי הרווחה ב-{cy} ({_bn(wage[1])} מיליארד ש\"ח)"
                complete = g is not None and abs(sum(r[1] for r in leaves) - g[1]) <= max(2.0, g[1] * 0.01)
                if per and complete:
                    hi = max(per, key=lambda k: (per[k], k))
                    if per[hi] - ws >= 0.05:
                        t += f". אצל {SECTOR_PHRASE[hi]} השכר מגיע ל-{fmt.pct(per[hi])} מההוצאה"
                add("cost", t + ".", "cost")

    # ── summary, SEO ─────────────────────────────────────────────────────
    tr_txt = ""
    if "transfers" in kpis:
        tr_txt = f", ו-{kpis['transfers']['display']} ממנה הן העברות כספיות למשקי בית"
    labels["lede"] = (f"ההוצאה הלאומית לרווחה בישראל הסתכמה ב-{ly} ב-{_bn(tot[ly])} מיליארד ש\"ח{tr_txt}. "
                      f"העמוד מציג את ההוצאה לפי מגזר מממן ומגזר מבצע, לפי סוג שירות ולפי סוג הוצאה, "
                      f"מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס).")
    summary = (f"ההוצאה הלאומית לרווחה בישראל: {_bn(tot[ly])} מיליארד ש\"ח ב-{ly}{tr_txt}. "
               f"נתוני הלמ\"ס לפי מגזר מממן ומבצע וסוג שירות, {first}-{ly}.")
    desc = (f"ההוצאה הלאומית לרווחה ב-{ly}: {_bn(tot[ly])} מיליארד ש\"ח. מי מממן, מי מפעיל ועל מה מוציאים: "
            f"קצבאות, פנסיות, אזרחים ותיקים ואנשים עם מוגבלות, {first}-{ly}.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "temporal_coverage": f"{first}/{ly}",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "ההוצאה הלאומית לרווחה בישראל | נתוני הלמ\"ס",
            "description": desc,
            "name": "ההוצאה הלאומית לרווחה",
            "alternate_names": ["הוצאה לאומית לרווחה", "הוצאות הרווחה בישראל",
                                "National expenditure on welfare"],
        },
    }
    release = {"title": str(rel.get("TITLE") or ""), "date": _date_he(rel["RELEASE_DATE"]),
               "headline": str(rel.get("HEADLINE") or "").strip(),
               "url": str(rel.get("PAGE_URL") or ""), "pdf": str(rel.get("REPORT_PDF_URL") or "")}
    return {"agent_data": agent_data, "kpis": kpis, "charts": charts, "tables": tables,
            "labels": labels, "flags": flags, "callouts": callouts, "insights": insights,
            "release": release}
