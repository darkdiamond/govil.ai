"""ההוצאה הלאומית לבריאות: CBS's yearly national-health-expenditure release.

The release comes in two shapes, and both are in the two-edition window
(`history_releases: 2`):

- a FULL edition (November 2025, 360/2025): Tables 1-12 plus chart sheets;
- a THIN provisional edition (August 2024, 263/2024): one summary table
  ("לוח 1 - הוצאה לאומית לבריאות", years as columns) plus chart sheets.

CBS also renumbers tables between editions, so every stem (t1..t21, t1a,
t2a, t11a; the last three numbers are spare slots) is optional, every
edition of every stem is read with `cbs.grid`, and each table is identified
by its TITLE text, never by its stem:

  ops_cur   לפי מגזר מבצע (מיון חדש), במחירים שוטפים  total, % of GDP, sectors
  ops_real  לפי מגזר מבצע (מיון חדש), במחירי YYYY     real levels + growth
  svc_cur   לפי סוג הוצאה ושירות, במחירים שוטפים       services
  svc_real  לפי סוג הוצאה ושירות, במחירי YYYY          per capita (real)
  fin       לפי מגזר מממן                              financing sources
  meds      אספקה של תרופות                            medicines by supplier
  intl      השוואה בין-לאומית                          OECD comparison
  summary   the thin edition's summary table           % of GDP, growth, financing

The year series that both shapes carry (% of GDP, real growth, per-capita
growth, financing shares) are merged across editions, the newest edition
winning for a year both have. Every other section comes from the newest
edition that has its table, and drops when none does. A table that is
recognised but whose header labels are gone raises (a human should look).
"""
import re
from itertools import pairwise

import pandas as pd
from govlib import cbs, fmt

REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
STEM = re.compile(r"t(\d+)([a-z]?)")
TITLE = re.compile(r"^(לוח|תרשים)\s*\d+")
HEB = re.compile("[א-ת]")
BASE = re.compile(r"במחירי\s+((?:19|20)\d\d)")
ISRAEL = "ישראל"

SERVICES = (("pub", "מרפאות ציבוריות ורפואה מונעת"), ("hosp", "בתי חולים ומחקר"),
            ("dental", "רפואת שיניים"), ("priv", "רופאים פרטיים"),
            ("med", "תרופות וציוד שקנו משקי בית"), ("admin", "מינהל ממשלתי"))
SECTORS = (("market", "יצרני שוק"), ("hmo", "קופות חולים"), ("gov", "ממשלה ורשויות מקומיות"),
           ("npi", "מלכ\"רים פרטיים"))
FIN = (("budget", "תקציב המדינה"), ("tax", "מס בריאות"), ("priv_other", "מימון פרטי אחר"),
       ("oop", "תשלומים ישירים של משקי בית"), ("don", "תרומות מחו\"ל"))
MEDS = (("hmo", "קופות חולים"), ("gov", "ממשלה"), ("npi", "מלכ\"רים פרטיים"), ("bus", "עסקים"))


# ── locating tables ──────────────────────────────────────────────────────


def _rel_key(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _stem_key(name):
    m = STEM.fullmatch(name)
    return (int(m.group(1)), m.group(2)) if m else (10**6, name)


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _head(rows, n=10):
    return " ".join(c for r in rows[:n] for c in r if c)


def _kind(rows):
    t = _title(rows)
    if not t.startswith("לוח"):
        return None
    head = _head(rows)
    if "מיון קודם" in head:
        return None
    if "מגזר מבצע" in head and "סוג הוצאה" not in head:
        if "שוטפים" in head:
            return "ops_cur"
        if BASE.search(head):
            return "ops_real"
    if "סוג הוצאה ושירות" in head and "מגזר מבצע" not in head:
        if "שוטפים" in head:
            return "svc_cur"
        if BASE.search(head):
            return "svc_real"
    if "מגזר מממן" in head:
        return "fin"
    if "אספקה של תרופות" in head:
        return "meds"
    if "השוואה בין-לאומית" in head:
        return "intl"
    if any(c.startswith("ההוצאה הלאומית לבריאות כאחוז") for r in rows for c in r):
        return "summary"
    return None


def _editions(frames):
    """[(release_no, {kind: rows})], newest edition first. Of two stems
    with the same kind in one edition, the lower stem number wins."""
    names = sorted((n for n in frames if STEM.fullmatch(n)), key=_stem_key)
    nos = set()
    for n in names:
        df = frames[n]
        if not df.empty:
            nos.update(str(v) for v in df["RELEASE_NO"].unique())
    out = []
    for no in sorted(nos, key=lambda v: (_rel_key(v), v), reverse=True):
        kinds = {}
        for n in names:
            df = frames[n]
            if df.empty:
                continue
            sub = df[df["RELEASE_NO"].astype(str) == no]
            if sub.empty:
                continue
            rows = cbs.grid(sub, n)
            k = _kind(rows)
            if k and k not in kinds:
                kinds[k] = rows
        out.append((no, kinds))
    return out


# ── table readers ────────────────────────────────────────────────────────


def _years(rows, start, stop):
    """[(row index, year)] for whole-year rows; the first row of a year wins."""
    if start >= stop:
        return []
    seen, out = set(), []
    for i, y, m, _ in cbs.periods(rows, start, stop):
        if m is None and y not in seen:
            seen.add(y)
            out.append((i, y))
    return out


def _cols(row, spec):
    """{key: column} for [(key, label, start_key or None, contains)]."""
    out = {}
    for key, label, after, contains in spec:
        out[key] = cbs.col_after(row, label, out[after] + 1 if after else 0, contains=contains)
    return out


def _low_header(rows, label, start, contains=True):
    """A header that sits low in the sheet: None when gone (verify's 70%
    cut, or a shorter edition) instead of raising."""
    try:
        return cbs.row_with(rows, label, start, contains=contains)
    except ValueError:
        return None


def _base_year(rows):
    m = BASE.search(_head(rows))
    return m.group(1) if m else ""


def read_ops_cur(rows):
    h = cbs.row_with(rows, "Market", name="ops_cur")
    c = _cols(rows[h], [("gdp", "Total national", None, False), ("cons", "Current", None, False),
                        ("market", "Market", None, False), ("npi", "Private", "market", False),
                        ("hmo", "Health", "market", False), ("gov", "Government", "market", True),
                        ("total", "Total", "gov", False)])
    out = {}
    for i, y in _years(rows, h + 1, len(rows)):
        rec = {k: cbs.val(rows[i], j) for k, j in c.items()}
        if rec["total"] is not None:
            out[y] = rec
    return out


def read_ops_real(rows):
    h = cbs.row_with(rows, "Market", name="ops_real")
    c = _cols(rows[h], [("market", "Market", None, False), ("npi", "Private", "market", False),
                        ("hmo", "Health", "market", False), ("gov", "Government", "market", True),
                        ("total", "Total", "gov", False)])
    split = _low_header(rows, "שינוי כמותי", h + 1)
    levels, growth = {}, {}
    for i, y in _years(rows, h + 1, split if split is not None else len(rows)):
        rec = {k: cbs.val(rows[i], j) for k, j in c.items()}
        if rec["total"] is not None:
            levels[y] = rec
    if split is not None:
        for i, y in _years(rows, split + 1, len(rows)):
            v = cbs.val(rows[i], c["total"])
            if v is not None:
                growth[y] = v
    return levels, growth, _base_year(rows)


def read_svc_cur(rows):
    h = cbs.row_with(rows, "Medicines", name="svc_cur", contains=True)
    r = rows[h]
    c = _cols(r, [("med", "Medicines", None, True), ("priv", "Private", "med", False),
                  ("dental", "Dental", "med", False), ("hosp", "Hospitals", "med", False),
                  ("pub", "Public clinics", "med", True), ("admin", "Government", "med", False),
                  ("cur", "Total", "admin", False)])
    cap = cbs.col_after(r, "Total")
    if cap > c["med"]:
        raise ValueError("svc_cur: fixed-capital total not before the services")
    c["cap"] = cap
    out = {}
    for i, y in _years(rows, h + 1, len(rows)):
        rec = {k: cbs.val(rows[i], j) for k, j in c.items()}
        if rec["cur"] is not None:
            out[y] = rec
    return out


def read_svc_real(rows):
    h = cbs.row_with(rows, "National", name="svc_real")
    pc = cbs.col_after(rows[h], "National")
    out = {}
    for i, y in _years(rows, h + 1, len(rows)):
        v = cbs.val(rows[i], pc)
        if v is not None:
            out[y] = v
    return out, _base_year(rows)


def read_fin(rows):
    """Financing shares (0-100): the percent block as published, and for a
    year it lacks (or when its header is gone), shares of the NIS block."""
    h = cbs.row_with(rows, "Donations", name="fin")
    c = _cols(rows[h], [("don", "Donations", None, False), ("oop", "Thereof:", None, False),
                        ("priv", "Total", "oop", False), ("tax", "Health", None, False),
                        ("budget", "Government", None, False), ("grand", "Grand", None, False)])
    stop = _low_header(rows, "Percentages", h + 1, contains=False)
    out = {}
    if stop is not None:  # CBS's own percentages, as published
        for i, y in _years(rows, stop + 1, len(rows)):
            rec = {k: cbs.val(rows[i], j) for k, j in c.items()}
            rec.pop("grand")
            if rec["priv"] is not None:
                out[y] = rec
    for i, y in _years(rows, h + 1, stop if stop is not None else len(rows)):
        rec = {k: cbs.val(rows[i], j) for k, j in c.items()}
        g = rec.pop("grand")
        if not g or y in out:
            continue
        out[y] = {k: None if v is None else v / g * 100 for k, v in rec.items()}
    return out


def read_meds(rows):
    h = cbs.row_with(rows, "Private NPIs", name="meds")
    c = _cols(rows[h], [("bus", "Total", None, False), ("npi", "Private NPIs", None, False),
                        ("gov", "Government", None, False), ("hmo", "Health", None, False),
                        ("grand", "Grand", None, False)])
    out = {}
    for i, y in _years(rows, h + 1, len(rows)):
        rec = {k: cbs.val(rows[i], j) for k, j in c.items()}
        if rec["grand"] is not None:
            out[y] = rec
    return out


def read_intl(rows):
    h = cbs.row_with(rows, "Percentage of", name="intl", contains=True)
    g = cbs.col_after(rows[h], "Percentage of", contains=True)
    y = None
    for i in range(h, len(rows)):
        if sum(1 for v in rows[i] if cbs.YEAR.match(v)) >= 2:
            y = i
            break
    if y is None:
        raise ValueError("intl: year header row not found")
    yr = rows[y]
    pc_cols = sorted(((int(v), j) for j, v in enumerate(yr) if cbs.YEAR.match(v) and j != g),
                     reverse=True)
    if not pc_cols:
        raise ValueError("intl: no per-capita year columns")
    gdp_year = int(yr[g]) if cbs.YEAR.match(cbs.cell(yr, g)) else pc_cols[0][0]
    name_col = cbs.best_col(rows[y + 1:], lambda v: bool(HEB.search(v)))
    if name_col is None:
        return None
    pc_year, pc_j = pc_cols[0]
    old_year, old_j = pc_cols[-1]
    countries = []
    for r in rows[y + 1:]:
        nm = cbs.cell(r, name_col)
        if not HEB.search(nm) or nm.startswith("מקור"):
            continue
        pc, gd = cbs.val(r, pc_j), cbs.val(r, g)
        if pc is None and gd is None:
            continue
        countries.append({"name": nm, "pc": pc, "gdp": gd,
                          "old": cbs.val(r, old_j) if old_j != pc_j else None})
    return {"pc_year": pc_year, "gdp_year": gdp_year, "old_year": old_year,
            "countries": countries}


def read_summary(rows):
    """The thin edition's summary: years across, one series per row."""
    yrow = None
    for i, r in enumerate(rows):
        if sum(1 for v in r if cbs.YEAR.match(v)) >= 5:
            yrow = i
            break
    if yrow is None:
        raise ValueError("summary: year header row not found")
    ycols = {j: int(v) for j, v in enumerate(rows[yrow]) if cbs.YEAR.match(v)}
    series = {}
    for r in rows[yrow + 1:]:
        label = next((c for c in r if HEB.search(c)), "")
        if label.startswith("ההוצאה הלאומית לבריאות כאחוז"):
            key = "gdp"
        elif label.startswith("סך הכל") and "השקעות" in label:
            key = "growth"
        elif label.startswith("הוצאה לאומית לבריאות לנפש"):
            key = "pcg"
        elif label == "מימון פרטי":
            key = "priv"
        elif "תשלומים ישירים" in label:
            key = "oop"
        elif label == "מס בריאות":
            key = "tax"
        elif label.startswith("מימון מתקציב"):
            key = "budget"
        elif label.startswith("תרומות"):
            key = "don"
        else:
            continue
        if key in series:
            continue
        series[key] = {y: v for j, y in ycols.items() if (v := cbs.val(r, j)) is not None}
    if "gdp" not in series:
        raise ValueError("summary: % of GDP row not found")
    return series


# ── small helpers ────────────────────────────────────────────────────────


def _r1(v):
    return None if v is None else round(v, 1)


def _r2(v):
    return None if v is None else round(v, 2)


def _p(v, d=1):
    return "" if v is None else fmt.pct_of(v, d)


def _n1(v):
    return "" if v is None else fmt.num_he(v, 1)


def _bn(v):
    """NIS million → NIS billion, 1 decimal."""
    return None if v is None else round(v / 1000, 1)


def _merge(series_list):
    """Newest first; a year takes the first series that has it. An older
    edition fills gaps inside the newest edition's range but never extends
    it backwards: its edge years are thin and revised, so the series starts
    where the newest edition that carries it starts."""
    out = {}
    floor = None
    for s in series_list:
        ys = [y for y, v in s.items() if v is not None]
        if floor is None and ys:
            floor = min(ys)
        for y in ys:
            if y >= floor:
                out.setdefault(y, s[y])
    return dict(sorted(out.items()))


def _signed(v, d=1):
    """A percent change on 0-100 with U+2212 for minus."""
    return fmt.signed_pct(v / 100, d)


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    eds = _editions(frames)
    if not eds:
        raise ValueError("no edition of any table")

    def newest(kind):
        for no, kinds in eds:
            if kind in kinds:
                return no, kinds[kind]
        return None, None

    # Year series both shapes carry, merged newest-first.
    gdp_s, growth_s, pcg_s, fin_s = [], [], [], []
    pc_levels, pc_base = {}, ""
    for _no, kinds in eds:
        if "ops_cur" in kinds:
            gdp_s.append({y: r["gdp"] for y, r in read_ops_cur(kinds["ops_cur"]).items()})
        if "ops_real" in kinds:
            growth_s.append(read_ops_real(kinds["ops_real"])[1])
        if "svc_real" in kinds:
            lv, base = read_svc_real(kinds["svc_real"])
            yrs = sorted(lv)
            pcg_s.append({y: (lv[y] / lv[p] - 1) * 100 for p, y in pairwise(yrs) if lv[p]})
            if not pc_levels:
                pc_levels, pc_base = lv, base
        if "fin" in kinds:
            fin_s.append(read_fin(kinds["fin"]))
        if "summary" in kinds:
            s = read_summary(kinds["summary"])
            gdp_s.append(s["gdp"])
            growth_s.append(s.get("growth", {}))
            pcg_s.append(s.get("pcg", {}))
            keys = ("budget", "tax", "priv", "oop", "don")
            yrs = set().union(*(s.get(k, {}) for k in keys))
            fin_s.append({y: {k: s.get(k, {}).get(y) for k in keys} for y in yrs})
    gdp = _merge(gdp_s)
    growth = _merge(growth_s)
    pcg = _merge(pcg_s)
    fin, fin_floor = {}, None
    for s in fin_s:
        ys = [y for y, rec in s.items() if rec.get("priv") is not None]
        if fin_floor is None and ys:
            fin_floor = min(ys)
        for y, rec in s.items():
            if y not in fin and y >= (fin_floor or y) and rec.get("priv") is not None:
                fin[y] = rec
    fin = dict(sorted(fin.items()))
    if not gdp:
        raise ValueError("no % of GDP series in any edition")

    _, ops_rows = newest("ops_cur")
    ops = read_ops_cur(ops_rows) if ops_rows else {}
    _, real_rows = newest("ops_real")
    real, _g, real_base = read_ops_real(real_rows) if real_rows else ({}, {}, "")
    _, svc_rows = newest("svc_cur")
    svc = read_svc_cur(svc_rows) if svc_rows else {}
    _, med_rows = newest("meds")
    meds = read_meds(med_rows) if med_rows else {}
    _, intl_rows = newest("intl")
    intl = read_intl(intl_rows) if intl_rows else None

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── % of GDP: public vs private ──────────────────────────────────────
    gy = sorted(gdp)
    ly = gy[-1]
    pub, prv, don = [], [], []
    for y in gy:
        f = fin.get(y)
        pub.append(_r2(gdp[y] * (f["budget"] + f["tax"]) / 100)
                   if f and f["budget"] is not None and f["tax"] is not None else None)
        prv.append(_r2(gdp[y] * f["priv"] / 100) if f else None)
        don.append(_r2(gdp[y] * f["don"] / 100) if f and f["don"] is not None else None)
    flags["split"] = any(v is not None for v in pub)
    charts["gdp"] = {"x": [str(y) for y in gy], "total": [_r2(gdp[y]) for y in gy],
                     "pub": pub, "priv": prv, "don": don}
    tables["gdp"] = [[str(y), _p(gdp[y]), _p(pub[k], 2), _p(prv[k], 2)] for k, y in enumerate(gy)]
    labels["gdp_aria"] = f"ההוצאה הלאומית לבריאות כאחוז מהתמ\"ג, {gy[0]} עד {ly}"
    labels["gdp_note"] = (f"כמה מהתוצר המקומי הגולמי הולך לבריאות בכל שנה מאז {gy[0]}, ואיזה חלק "
                          f"ממנו ממומן מכסף ציבורי (תקציב המדינה ומס בריאות) ואיזה מכסף פרטי.")
    kpis["gdp"] = {"value": round(gdp[ly], 1), "display": fmt.num_he(gdp[ly], 1),
                   "tone": "brand"}
    labels["gdp_kpi"] = f"ההוצאה הלאומית לבריאות כאחוז מהתמ\"ג ({ly})"
    peak_y = max(gy, key=lambda y: (gdp[y], y))
    txt = f"ב-{ly} הסתכמה ההוצאה הלאומית לבריאות ב-{_p(gdp[ly])} מהתמ\"ג"
    if len(gy) >= 5:
        same = round(gdp[gy[0]], 1) == round(gdp[ly], 1)
        txt += (f", כמו ב-{gy[0]}" if same else f", לעומת {_p(gdp[gy[0]])} ב-{gy[0]}")
    if peak_y != ly and gdp[peak_y] - gdp[ly] >= 0.3:
        txt += f". השיא היה ב-{peak_y}, {_p(gdp[peak_y])} מהתמ\"ג"
    add("gdp", txt + ".")

    # ── total and real growth ────────────────────────────────────────────
    flags["total"] = bool(ops)
    flags["growth"] = len(growth) >= 3
    if flags["total"] or flags["growth"]:
        ty = sorted(set(ops) | (set(growth) if flags["growth"] else set()))
        charts["total"] = {"x": [str(y) for y in ty],
                           "total": [_bn(ops[y]["total"]) if y in ops else None for y in ty],
                           "growth": [_r1(growth.get(y)) for y in ty] if flags["growth"] else None}
        tables["total"] = [[str(y), _n1(_bn(ops[y]["total"])) if y in ops else "",
                            _signed(growth[y]) if y in growth else ""] for y in ty]
        labels["total_aria"] = f"ההוצאה הלאומית לבריאות ושיעור הצמיחה הריאלי, {ty[0]} עד {ty[-1]}"
    if ops:
        oy = max(ops)
        tot = ops[oy]["total"]
        kpis["total"] = {"value": round(tot / 1000, 1), "display": fmt.num_he(tot / 1000, 1),
                         "tone": "brand"}
        labels["total_kpi"] = f"ההוצאה הלאומית לבריאות ב-{oy} (מיליארדי ₪, במחירים שוטפים)"
    if flags["growth"]:
        gyy = max(growth)
        gv = growth[gyy]
        kpis["growth"] = {"value": round(gv, 1), "display": _signed(gv),
                          "tone": "ok" if gv > 0 else "danger"}
        labels["growth_kpi"] = f"צמיחה ריאלית של ההוצאה ב-{gyy} (בניכוי מחירים)"
        prior = [growth[y] for y in sorted(growth) if gyy - 10 <= y < gyy]
        if len(prior) >= 6:
            avg = sum(prior) / len(prior)
            verb = "גדלה" if gv >= 0 else "קטנה"
            if abs(gv - avg) < 0.3:
                cmp_ = f"בדומה לממוצע של {_p(avg)} בשנה ב-{len(prior)} השנים שקדמו לה"
            else:
                cmp_ = (f"{'מתחת' if gv < avg else 'מעל'} לממוצע של {_p(avg)} בשנה "
                        f"ב-{len(prior)} השנים שקדמו לה")
            add("growth", f"בניכוי עליית המחירים, ההוצאה הלאומית לבריאות {verb} ב-{_p(abs(gv))} "
                          f"ב-{gyy}, {cmp_}.")
    labels["total_note"] = (
        ("ההוצאה הלאומית לבריאות בכל שנה במיליארדי ₪ במחירים שוטפים (עמודות), "
         "והשינוי הכמותי שלה לעומת השנה הקודמת, בניכוי עליית המחירים (קו).")
        if flags["total"] and flags["growth"] else
        "ההוצאה הלאומית לבריאות בכל שנה, במיליארדי ₪ במחירים שוטפים." if flags["total"] else
        "השינוי הכמותי של ההוצאה הלאומית לבריאות לעומת השנה הקודמת, בניכוי עליית המחירים.")

    # ── financing sources ────────────────────────────────────────────────
    fy = sorted(fin)
    flags["fin"] = len(fy) >= 3
    if flags["fin"]:
        def parts(f):
            oop = f["oop"]
            return {"budget": f["budget"], "tax": f["tax"],
                    "priv_other": None if oop is None else f["priv"] - oop,
                    "oop": oop, "don": f["don"]}
        rows_ = {y: parts(fin[y]) for y in fy}
        charts["fin"] = {"x": [str(y) for y in fy], "names": [n for _, n in FIN],
                         "series": [[_r1(rows_[y][k]) for y in fy] for k, _ in FIN]}
        tables["fin"] = [[str(y)] + [_p(rows_[y][k]) for k, _ in FIN] for y in fy]
        labels["fin_cols"] = ["שנה"] + [n for _, n in FIN]
        labels["fin_aria"] = f"מקורות המימון של ההוצאה הלאומית לבריאות, {fy[0]} עד {fy[-1]}"
        f_last, f_first = fin[fy[-1]], fin[fy[0]]
        prev = fin.get(fy[-2])
        kpis["priv"] = {"value": round(f_last["priv"], 1), "display": fmt.num_he(f_last["priv"], 1) + "%",
                        "tone": ("warn" if prev and f_last["priv"] > prev["priv"] + 0.05 else
                                 "ok" if prev and f_last["priv"] < prev["priv"] - 0.05 else "brand")}
        labels["priv_kpi"] = f"חלק המימון הפרטי בהוצאה ({fy[-1]})"
        if f_last["oop"] is not None and f_first["oop"] is not None:
            d = f_last["oop"] - f_first["oop"]
            trend = ("לעומת" if abs(d) < 0.5 else "ירידה מ-" if d < 0 else "עלייה מ-")
            frm = (f"{trend} {_p(f_first['oop'])} ב-{fy[0]}" if trend == "לעומת"
                   else f"{trend}{_p(f_first['oop'])} ב-{fy[0]}")
            add("oop", f"משקי הבית מממנים מכיסם, בתשלומים ישירים, {_p(f_last['oop'])} מההוצאה "
                       f"הלאומית לבריאות ב-{fy[-1]} ({frm}). המימון הפרטי כולו מגיע ל-"
                       f"{_p(f_last['priv'])}, ותקציב המדינה ומס בריאות מממנים יחד "
                       f"{_p(f_last['budget'] + f_last['tax'])}.")
        labels["fin_note"] = ("מי מממן את ההוצאה הלאומית לבריאות, באחוזים מסך ההוצאה בכל שנה. "
                              "\"תשלומים ישירים\" הם מה שמשקי הבית משלמים מכיסם; \"מימון פרטי אחר\" "
                              "הוא שאר המימון הפרטי.")

    # ── operating sectors, real ──────────────────────────────────────────
    ry = sorted(real)
    flags["sector"] = len(ry) >= 3
    if flags["sector"]:
        charts["sector"] = {"x": [str(y) for y in ry], "names": [n for _, n in SECTORS],
                            "series": [[_bn(real[y][k]) for y in ry] for k, _ in SECTORS]}
        tables["sector"] = [[str(y)] + [_n1(_bn(real[y][k])) for k, _ in SECTORS] for y in ry]
        labels["sector_cols"] = ["שנה"] + [n for _, n in SECTORS]
        labels["sector_aria"] = f"ההוצאה הלאומית לבריאות לפי מגזר מבצע, {ry[0]} עד {ry[-1]}"
        labels["sector_note"] = (f"מי מספק את שירותי הבריאות: ההוצאה לפי המגזר שמבצע אותה, "
                                 f"במיליארדי ₪ במחירי {real_base}. יצרני שוק כוללים גם את בתי "
                                 f"החולים הכלליים.")
        gov = {y: real[y]["gov"] for y in ry if real[y]["gov"] is not None}
        if gov:
            py = max(gov, key=lambda y: (gov[y], y))
            lyr = max(gov)
            drop = (1 - gov[lyr] / gov[py]) * 100 if gov[py] else 0
            if py != lyr and drop >= 15:
                add("gov", f"ההוצאה של הממשלה והרשויות המקומיות כמגזר מבצע הגיעה לשיא ב-{py} "
                           f"({fmt.num_he(gov[py] / 1000, 1)} מיליארד ₪ במחירי {real_base}) וירדה "
                           f"מאז ב-{fmt.pct_of(drop, 0)}, ל-{fmt.num_he(gov[lyr] / 1000, 1)} מיליארד "
                           f"₪ ב-{lyr}.")
        lr = real[ry[-1]]
        if lr["hmo"] and lr["total"] and lr["market"]:
            add("sector", f"קופות החולים מבצעות {_p(lr['hmo'] / lr['total'] * 100)} מההוצאה "
                          f"הלאומית לבריאות ב-{ry[-1]}, ויצרני השוק, כולל בתי החולים הכלליים, "
                          f"{_p(lr['market'] / lr['total'] * 100)}.")

    # ── services ─────────────────────────────────────────────────────────
    sy = sorted(svc)
    flags["service"] = len(sy) >= 3
    if flags["service"]:
        def shares(y):
            cur = svc[y]["cur"]
            return {k: None if svc[y][k] is None or not cur else svc[y][k] / cur * 100
                    for k, _ in SERVICES}
        sh = {y: shares(y) for y in sy}
        charts["service"] = {"x": [str(y) for y in sy], "names": [n for _, n in SERVICES],
                             "series": [[_r1(sh[y][k]) for y in sy] for k, _ in SERVICES]}
        tables["service"] = [[str(y)] + [_p(sh[y][k]) for k, _ in SERVICES]
                             + [_n1(_bn(svc[y]["cur"]))] for y in sy]
        labels["service_cols"] = ["שנה"] + [n for _, n in SERVICES] + ["סך הכל (מיליארדי ₪)"]
        labels["service_aria"] = f"ההוצאה השוטפת לבריאות לפי סוג שירות, {sy[0]} עד {sy[-1]}"
        labels["service_note"] = ("על מה הולכת ההוצאה השוטפת לבריאות: החלק של כל סוג שירות "
                                  "מסך ההוצאה השוטפת בכל שנה (בלי השקעה במבנים ובציוד).")
        last = sh[sy[-1]]
        lead = max((k for k, _ in SERVICES if last[k] is not None), key=lambda k: (last[k], k))
        names = dict(SERVICES)
        txt = (f"הרכיב הגדול בהוצאה השוטפת לבריאות הוא {names[lead]}: {_p(last[lead])} ממנה "
               f"ב-{sy[-1]}")
        y0 = max((y for y in sy if y <= sy[-1] - 10), default=sy[0])
        first = sh[y0]
        moves = [(last[k] - first[k], k) for k, _ in SERVICES
                 if last[k] is not None and first[k] is not None]
        if moves:
            d, k = max(moves)
            if d >= 1 and k != lead:
                txt += (f". החלק של {names[k]} עלה מ-{_p(first[k])} ב-{y0} ל-{_p(last[k])}")
        add("service", txt + ".")

    # ── per capita, real ─────────────────────────────────────────────────
    py_ = sorted(pc_levels)
    flags["percap"] = len(py_) >= 3
    if flags["percap"]:
        charts["percap"] = {"x": [str(y) for y in py_], "values": [round(pc_levels[y]) for y in py_]}
        tables["percap"] = [[str(y), fmt.int_he(pc_levels[y]),
                             _signed(pcg[y]) if y in pcg else ""] for y in py_]
        labels["percap_aria"] = f"ההוצאה הלאומית לבריאות לנפש במחירי {pc_base}, {py_[0]} עד {py_[-1]}"
        labels["percap_note"] = (f"ההוצאה הלאומית לבריאות לכל תושב, בשקלים במחירי {pc_base}, כך "
                                 f"שהשינוי משקף כמות ולא מחיר.")
        lv = pc_levels[py_[-1]]
        kpis["percap"] = {"value": round(lv), "display": fmt.int_he(lv), "tone": "brand"}
        labels["percap_kpi"] = f"הוצאה לבריאות לנפש ב-{py_[-1]} (₪, במחירי {pc_base})"
        y0 = max((y for y in py_ if y <= py_[-1] - 10), default=py_[0])
        if y0 != py_[-1] and pc_levels[y0]:
            ch = (lv / pc_levels[y0] - 1) * 100
            word = "עלייה" if ch >= 0.5 else "ירידה" if ch <= -0.5 else "שינוי זניח"
            tail = f"{word} של {_p(abs(ch))}" if word != "שינוי זניח" else word
            add("percap", f"ההוצאה לבריאות לנפש, במחירי {pc_base}, הגיעה ל-{fmt.int_he(lv)} ₪ "
                          f"ב-{py_[-1]}: {tail} לעומת {fmt.int_he(pc_levels[y0])} ₪ ב-{y0}.")

    # ── medicines ────────────────────────────────────────────────────────
    my = sorted(meds)
    flags["meds"] = len(my) >= 3
    if flags["meds"]:
        charts["meds"] = {"x": [str(y) for y in my], "names": [n for _, n in MEDS],
                          "series": [[_bn(meds[y][k]) for y in my] for k, _ in MEDS]}
        tables["meds"] = [[str(y)] + [_n1(_bn(meds[y][k])) for k, _ in MEDS]
                          + [_n1(_bn(meds[y]["grand"]))] for y in my]
        labels["meds_cols"] = ["שנה"] + [n for _, n in MEDS] + ["סך הכל"]
        labels["meds_aria"] = f"אספקת תרופות וציוד רפואי לפי ספק, {my[0]} עד {my[-1]}"
        labels["meds_note"] = ("כמה תרופות, חומרי רפואה ומכשירים רפואיים סופקו בכל שנה ומי סיפק "
                               "אותם (כולל אספקה כחלק מטיפול), במיליארדי ₪ במחירים שוטפים.")
        m = meds[my[-1]]
        if m["hmo"] and m["grand"]:
            y0 = max((y for y in my if y <= my[-1] - 10), default=my[0])
            txt = (f"קופות החולים סיפקו {_p(m['hmo'] / m['grand'] * 100)} מהתרופות והציוד הרפואי "
                   f"ב-{my[-1]}, מתוך {fmt.num_he(m['grand'] / 1000, 1)} מיליארד ₪")
            g0 = meds[y0]["grand"]
            if y0 != my[-1] and g0:
                txt += f", פי {fmt.num_he(m['grand'] / g0, 1)} מ-{y0}"
            add("meds", txt + ".")

    # ── international ────────────────────────────────────────────────────
    flags["intl"] = bool(intl) and len([c for c in intl["countries"] if c["pc"] is not None]) >= 5
    if flags["intl"]:
        cs = intl["countries"]
        pcs = sorted((c for c in cs if c["pc"] is not None), key=lambda c: (-c["pc"], c["name"]))
        gds = sorted((c for c in cs if c["gdp"] is not None), key=lambda c: (-c["gdp"], c["name"]))
        charts["intl_pc"] = {"names": [c["name"] for c in pcs], "values": [round(c["pc"]) for c in pcs]}
        charts["intl_gdp"] = {"names": [c["name"] for c in gds], "values": [_r1(c["gdp"]) for c in gds]}
        tables["intl_pc"] = [[str(k + 1), c["name"], fmt.int_he(c["pc"])] for k, c in enumerate(pcs)]
        tables["intl_gdp"] = [[str(k + 1), c["name"], _p(c["gdp"])] for k, c in enumerate(gds)]
        labels["intl_pc_aria"] = f"הוצאה שוטפת לבריאות לנפש, השוואה בין-לאומית, {intl['pc_year']}"
        labels["intl_gdp_aria"] = f"הוצאה שוטפת לבריאות כאחוז מהתמ\"ג, השוואה בין-לאומית, {intl['gdp_year']}"
        labels["intl_pc_note"] = (f"ההוצאה השוטפת לבריאות לנפש ב-{intl['pc_year']}, בדולרים במונחי "
                                  f"כוח קנייה (PPP), ב-{len(pcs)} מדינות. ישראל מודגשת.")
        labels["intl_gdp_note"] = (f"ההוצאה השוטפת לבריאות כאחוז מהתמ\"ג ב-{intl['gdp_year']}, "
                                   f"ב-{len(gds)} מדינות. ישראל מודגשת.")
        isr_pc = next((k for k, c in enumerate(pcs) if c["name"] == ISRAEL), None)
        isr_g = next((c for c in gds if c["name"] == ISRAEL), None)
        if isr_pc is not None:
            c = pcs[isr_pc]
            txt = (f"בהשוואה בין-לאומית ל-{intl['pc_year']}, ישראל במקום ה-{isr_pc + 1} מתוך "
                   f"{len(pcs)} מדינות בהוצאה השוטפת לבריאות לנפש ({fmt.int_he(c['pc'])} דולר "
                   f"במונחי כוח קנייה)")
            if isr_g is not None and len(gds) >= 5:
                vals = sorted(x["gdp"] for x in gds)
                n = len(vals)
                med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
                if abs(isr_g["gdp"] - med) >= 0.3:
                    side = "מתחת" if isr_g["gdp"] < med else "מעל"
                    txt += (f", ושיעור ההוצאה שלה מהתמ\"ג, {_p(isr_g['gdp'])}, {side} לחציון "
                            f"המדינות שבהשוואה ({_p(med)})")
            add("intl", txt + ".")

    # ── text ─────────────────────────────────────────────────────────────
    rel = cbs.latest_release(frames["releases"])
    release = {"title": rel["TITLE"], "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(str(rel["RELEASE_DATE"])))}
    lede = (f"כמה ישראל מוציאה על בריאות, מי מממן את ההוצאה ועל מה היא הולכת, לפי ההודעה השנתית "
            f"של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס). הנתונים מתעדכנים עם כל הודעה חדשה. ב-{ly} "
            f"הייתה ההוצאה הלאומית לבריאות {_p(gdp[ly])} מהתמ\"ג")
    if ops and max(ops) == ly:
        lede += f", {fmt.num_he(ops[ly]['total'] / 1000, 1)} מיליארד ₪"
    labels["lede"] = lede + "."
    summary = (f"ההוצאה הלאומית לבריאות בישראל לפי הלמ\"ס: {_p(gdp[ly])} מהתמ\"ג ב-{ly}"
               + (f", {fmt.num_he(ops[max(ops)]['total'] / 1000, 1)} מיליארד ₪ ב-{max(ops)}" if ops else "")
               + (f", {_p(fin[fy[-1]]['priv'])} ממנה במימון פרטי" if fin else "") + ".")
    desc = (f"כמה ישראל מוציאה על בריאות: {_p(gdp[ly])} מהתמ\"ג ב-{ly}"
            + (f", {fmt.int_he(pc_levels[max(pc_levels)])} ₪ לנפש" if pc_levels else "")
            + (f", {_p(fin[fy[-1]]['priv'])} מימון פרטי" if fin else "")
            + ". מימון, שירותים והשוואה ל-OECD.")
    years_all = sorted(set(gy) | set(ops) | set(fin) | set(svc))
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years_all[0]}/{years_all[-1]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "ההוצאה הלאומית לבריאות בישראל | נתוני הלמ\"ס",
                "description": desc,
                "name": "ההוצאה הלאומית לבריאות",
                "alternate_names": ["הוצאה לאומית לבריאות", "ההוצאה על בריאות בישראל",
                                    "הוצאה לבריאות כאחוז מהתמ\"ג", "הוצאה לבריאות לנפש",
                                    "מימון פרטי של הבריאות"],
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
