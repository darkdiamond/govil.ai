"""סחר החוץ של ישראל: CBS's monthly goods imports/exports release.

Inputs are CBS grid tables from the newest edition of the release. Values are
million ₪ (the even-numbered tables), except t1, the dollar twin of t2, read
only to compare growth in dollars and shekels:
  t2   trade balance: imports, exports, deficit (total and excl. ships,
       aircraft and diamonds); two full years, year to date and about 13
       months; seasonally adjusted and trend sections below
  t1   the same in million $
  t4   imports by use: consumer goods, raw materials, investment goods,
       fuels, diamonds, ships and aircraft
  t6   exports by group: manufacturing, agriculture, diamonds
  t8   consumer-goods imports by commodity group
  t10  raw-material imports by commodity group
  t12  investment-goods imports by commodity group
  t14  agricultural exports by crop
  t18  manufacturing exports by industry and technological intensity (latest
       month, year to date and two full years, each against a year earlier)
  t20  manufacturing exports by technological intensity, monthly
  releases  the edition list (number, date, headline, link)

Header labels (the English side) are looked up by text and raise when
missing, so a redesigned table fails the refresh as recipe_failed and keeps
the last page. Period rows are found by content; the seasonally adjusted and
trend sections sit low in t2 and are optional.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TOP_INDUSTRIES = 12
_RANGE = re.compile(r"^([IVX]+)\s*-\s*([IVX]+)$")
_LATIN = re.compile("[A-Za-z]")
_HEB = re.compile("[א-ת]")


# ── grid helpers ─────────────────────────────────────────────────────────


def _norm(rows):
    """Rows with month ranges written `I - IX` closed up to `I-IX`, the form
    cbs.periods reads."""
    return [[_RANGE.sub(r"\1-\2", c) for c in r] for r in rows]


def _header(rows, name):
    """(index of the 'Original data' row, English header text per column).
    The header block runs from below the unit line ('Million NIS') to the
    'Original data' row; a column's text is its English cells joined."""
    u = cbs.row_with(rows, "Million", name=name, contains=True)
    h = cbs.row_with(rows, "Original data", u, name=name, contains=True)
    width = max(len(r) for r in rows)
    comps = [" ".join(cbs.cell(r, j) for r in rows[u + 1:h] if _LATIN.search(cbs.cell(r, j)))
             for j in range(width)]
    return h, comps


def _col(comps, pred, name, label, start=0, unique=True):
    """The column whose header text satisfies `pred` (the first at or after
    `start`, or the only one when `unique`). Raises when there is none, or
    more than one when one is required."""
    hits = [j for j in range(start, len(comps)) if comps[j] and pred(comps[j])]
    if not hits or (unique and len(hits) > 1):
        raise ValueError(f"{name}: header label {label!r} "
                         + ("not found" if not hits else f"matches {len(hits)} columns"))
    return hits[0]


def _has(needle):
    return lambda c: needle in c


def _eq(needle):
    return lambda c: c == needle


def _cols(comps, spec, name):
    return {k: _col(comps, _has(n) if isinstance(n, str) else n[1], name,
                    n if isinstance(n, str) else n[0])
            for k, n in spec.items()}


def _section_end(rows, start):
    for i in range(start + 1, len(rows)):
        if any("Seasonally adjusted" in c or "Trend data" in c for c in rows[i]):
            return i
    return len(rows)


def _read(rows, start, stop, cols):
    """{'annual': {year: v}, 'ytd': {(year, end): v}, 'months': {(y, m): v}}
    for the period rows in rows[start:stop]; v = {key: value}."""
    out = {"annual": {}, "ytd": {}, "months": {}}
    nrows = _norm(rows)
    for i, y, m, end in cbs.periods(nrows, start, stop):
        v = {k: cbs.val(rows[i], j) for k, j in cols.items()}
        if all(x is None for x in v.values()):
            continue
        if m is None:
            out["annual"][y] = v
        elif end:
            if m == 1:
                out["ytd"][(y, end)] = v
        else:
            out["months"][(y, m)] = v
    return out


def _table(frames, key, spec):
    rows = cbs.grid(frames[key], key)
    h, comps = _header(rows, key)
    cols = spec(comps) if callable(spec) else _cols(comps, spec, key)
    return rows, h, _read(rows, h + 1, _section_end(rows, h), cols)


def _optional_section(rows, h, label, cols):
    try:
        s = cbs.row_with(rows, label, h + 1, contains=True)
    except ValueError:
        return {}
    return _read(rows, s + 1, _section_end(rows, s), cols)["months"]


def _ytd_of(data, y, m, key=None):
    """Year-to-date values for months 1..m of year y: the range row, or for
    January the month itself, or for December the full year."""
    v = data["ytd"].get((y, m))
    if v is None and m == 1:
        v = data["months"].get((y, 1))
    if v is None and m == 12:
        v = data["annual"].get(y)
    if v is None:
        return None
    return v if key is None else v.get(key)


# ── table readers ────────────────────────────────────────────────────────


def _balance_cols(comps, name):
    """t1/t2: group columns (deficit, exports, imports) then, after each,
    the 'Total' column and the 'excl. ships, aircraft and diamonds' one."""
    dcol = _col(comps, _has("Trade deficit"), name, "Trade deficit")
    ecol = _col(comps, _has("Exports Thereof"), name, "Exports Thereof")
    icol = _col(comps, lambda c: c.startswith("Imports"), name, "Imports")
    total = _eq("Total")
    excl = lambda c: c.rstrip().endswith("diamonds")
    return {
        "ratio": _col(comps, _has("% of imports"), name, "% of imports"),
        "deficit": _col(comps, total, name, "Total", dcol, unique=False),
        "deficit_x": _col(comps, excl, name, "excl. ... diamonds", dcol, unique=False),
        "exports": _col(comps, total, name, "Total", ecol, unique=False),
        "exports_x": ecol,
        "imports": _col(comps, total, name, "Total", icol, unique=False),
        "imports_x": _col(comps, excl, name, "excl. ... diamonds", icol, unique=False),
    }


IMPORT_USES = {  # key: (English header, Hebrew label), in stacking order
    "raw": ("Raw materials", "חומרי גלם"),
    "consumer": ("Consumer goods", "מוצרי צריכה"),
    "investment": ("Investment goods", "מוצרי השקעה"),
    "fuels": (("Fuels", _eq("Fuels")), "חומרי אנרגיה"),
    "diamonds": ("Diamonds", "יהלומים"),
    "ships": ("Ships and aircraft", "אוניות ומטוסים"),
}
EXPORT_GROUPS = {
    "manufacturing": ("Manufacturing", "תעשייה, כרייה וחציבה"),
    "agriculture": ("Agriculture", "חקלאות, ייעור ודיג"),
    "wholesale": ("Wholesale of diamonds", "מסחר סיטוני ביהלומים"),
    "working": ("Working of diamonds", "עיבוד יהלומים"),
    "total": (("Total", _eq("Total")), "סך הכל"),
}
CONSUMER = {
    "medicines": ("Medicines", "תרופות"),
    "food": ("Food and beverages", "מזון ומשקאות"),
    "clothing": ("Clothing and footwear", "הלבשה והנעלה"),
    "household": ("utensils", "כלי בית"),
    "nondurable_other": ("Non-durable goods Other", "מוצרים לצריכה שוטפת, אחר"),
    "furniture": ("Furniture and electrical", "ריהוט ומוצרי חשמל ביתיים"),
    "transport": (("Transport equipment", _eq("Transport equipment")), "כלי תחבורה"),
    "durable_other": (("Durable goods Other", _eq("Durable goods Other")),
                      "מוצרים בני קיימה, אחר"),
    "total": (("Grand total", _eq("Grand total")), "סך הכל"),
}
RAW = {
    "machine": ("machine and electronics", "לתעשיות מכונות ואלקטרוניקה"),
    "chemicals": ("Chemicals", "כימיקלים"),
    "food": ("Raw food", "מוצרי מזון גולמיים"),
    "iron": ("Iron and steel", "ברזל ופלדה"),
    "rubber": ("Rubber and plastics", "גומי ופלסטיקה"),
    "nonferrous": ("Non-ferrous", "מתכות אל ברזליות"),
    "agriculture": ("For agriculture", "לחקלאות"),
    "wood": ("Wood", "עץ ומוצריו"),
    "paper": ("For paper", "לתעשיות נייר"),
    "fabrics": ("Fabrics", "בדים וחוטים"),
    "precious": ("Precious metals", "מתכות יקרות"),
    "other": ("excluding diamonds and fuels Other", "אחר"),
    "fuels": (("Fuels", _eq("Fuels")), "חומרי אנרגיה"),
    "diamonds": (("Diamonds", _eq("Diamonds")), "יהלומים"),
    "total": (("Grand total", _eq("Grand total")), "סך הכל"),
}
INVESTMENT = {
    "machinery": ("Machinery and equipment", "מכונות וציוד"),
    "cars": ("Passenger cars", "מכוניות נוסעים לצרכים עסקיים"),
    "trucks": ("Trucks", "משאיות, טנדרים ואוטובוסים"),
    "ships": ("Ships and aircraft", "אוניות ומטוסים"),
    "other": ("Transport equipment Other", "כלי תחבורה אחרים"),
    "total": (("Grand total", _eq("Grand total")), "סך הכל"),
}
AGRI = {
    "fruits": ("other fruits", "פירות (ללא הדרים)"),
    "citrus": ("citrus", "הדרים"),
    "crops": ("non-perennial crops", "ירקות וגידולי שדה"),
    "flowers": ("flowers", "פרחים"),
    "animals": ("Fishing", "דיג ובעלי חיים"),
    "other": ("Agricultural exports n.e.c.", "יצוא חקלאי אחר"),
}
TECH = {  # high first
    "high": (("High Technology Industries", _eq("High Technology Industries")), "עילית"),
    "mhigh": (("Medium - high", _has("Medium - high")), "מעורבת-עילית"),
    "mlow": (("Medium - low", _has("Medium - low")), "מעורבת-מסורתית"),
    "low": (("Low Technology Industries", _eq("Low Technology Industries")), "מסורתית"),
}


def _spec(groups):
    return {k: v[0] for k, v in groups.items()}


def _by_industry(rows, name):
    """t18: [{name, level, total, values: {period key: value}}] and the
    period keys ('month', 'month_prev', 'ytd', 'ytd_prev', 'year', 'year_prev')
    with their (year, month or end) labels."""
    hr = cbs.row_with(rows, "Industry", name=name)
    yr = hr + 1
    ycols = [j for j, c in enumerate(rows[yr]) if cbs.YEAR.match(c)]
    if len(ycols) < 4:
        raise ValueError(f"{name}: year header row not found")
    groups, cur = [], []
    for j in ycols:
        if cur and int(rows[yr][j]) < int(rows[yr][cur[-1]]) and cbs.cell(rows[hr], j) == "":
            cur.append(j)
        else:
            if cur:
                groups.append(cur)
            cur = [j]
    groups.append(cur)
    norm = _norm([rows[hr]])[0]
    kinds, seen = {}, set()
    for g in groups:
        lab = next((norm[j] for j in g if norm[j]), "")
        pm = cbs.PERIOD.match(lab)
        if not lab:
            kind = "year"
        elif pm and pm.group(2):
            kind = "ytd"
        elif pm and lab in seen:
            kind = "ytd"  # a January edition: month and year to date are both "I"
        elif pm:
            kind = "month"
        else:
            continue
        seen.add(lab)
        if kind in kinds or len(g) < 2:
            continue
        end = cbs.ROMAN.get(pm.group(2) or pm.group(1)) if pm else None
        kinds[kind] = {"cols": g[:2], "years": [int(rows[yr][j]) for j in g[:2]], "end": end}
    if "ytd" not in kinds and "month" in kinds and kinds["month"]["end"] == 1:
        kinds["ytd"] = kinds["month"]
    # A December edition has no I-XII group: the full year is the year to date.
    if ("ytd" not in kinds and "month" in kinds and kinds["month"]["end"] == 12
            and "year" in kinds and kinds["year"]["years"] == kinds["month"]["years"]):
        kinds["ytd"] = kinds["year"]
    if "ytd" not in kinds:
        raise ValueError(f"{name}: year-to-date columns not found")
    body = rows[yr + 1:]
    hcol = cbs.best_col(body, lambda v: bool(_HEB.search(v)))
    if hcol is None:
        raise ValueError(f"{name}: Hebrew industry column not found")
    yc = kinds["ytd"]["cols"][0]
    out, level, total = [], None, None
    for r in body:
        label = cbs.cell(r, hcol)
        if not label or cbs.val(r, yc) is None:
            continue
        vals = {}
        for k, d in kinds.items():
            vals[k] = cbs.val(r, d["cols"][0])
            vals[k + "_prev"] = cbs.val(r, d["cols"][1])
        if label.startswith("סך הכל"):
            total = {"name": label, "values": vals}
        elif label.startswith("תעשיות טכנולוגיה"):
            level = label
            out.append({"name": label, "level": None, "values": vals})
        else:
            out.append({"name": label, "level": level, "values": vals})
    if total is None:
        raise ValueError(f"{name}: total row not found")
    return out, total, kinds


# ── formatting ───────────────────────────────────────────────────────────


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _ytd_name(y, m):
    if m == 1:
        return f"ינואר {y}"
    return f"ינואר עד {fmt.MONTHS_HE[m - 1]} {y}"


def _ytd_short(y, m):
    if m == 1:
        return f"{fmt.MONTHS_SHORT_HE[0]} {y}"
    return f"{fmt.MONTHS_SHORT_HE[0]}-{fmt.MONTHS_SHORT_HE[m - 1]} {y}"


def _bn(v, d=1):
    """Million ₪ → billions, as text ("" for a missing value)."""
    return "" if v is None else fmt.num_he(v / 1000, d)


def _bnr(v, d=2):
    return None if v is None else round(v / 1000, d)


def _mn(v):
    return "" if v is None else fmt.int_he(v)


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _sp(c):
    return "" if c is None else fmt.signed_pct(c)


def _word(c, up="עלייה", down="ירידה"):
    return up if c > 0 else down


def _short_industry(name):
    s = re.sub(r"\(.*", "", name).strip().rstrip(",")
    s = re.sub(r",\s*(פרט|כולל)\b.*", "", s)
    s = re.sub(r"^(ייצור|תעשיית)\s+", "", s)
    return s if len(s) <= 34 else s[:33].rstrip() + "…"


def _ytd_rows(data, groups, keys, y, m):
    """[(key, label, this ytd, last ytd, change)] for the group keys."""
    out = []
    for k in keys:
        a, b = _ytd_of(data, y, m, k), _ytd_of(data, y - 1, m, k)
        if a is None:
            continue
        out.append((k, groups[k][1], a, b, _chg(a, b)))
    return out


def _bars(rows):
    """Chart arrays for a this-vs-last year-to-date bar chart, largest
    first (the template sets the category axis to `inverse`)."""
    rows = sorted(rows, key=lambda r: (-r[2], r[0]))
    return {"names": [r[1] for r in rows], "now": [round(r[2], 1) for r in rows],
            "prev": [round(r[3], 1) if r[3] is not None else None for r in rows]}


def _bars_table(rows, total=None):
    rows = sorted(rows, key=lambda r: (-r[2], r[0]))
    return [[r[1], _mn(r[2]), _mn(r[3]), _sp(r[4]),
             fmt.pct(r[2] / total) if total else ""] for r in rows]


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    t2_rows, t2_h, bal = _table(frames, "t2", lambda c: _balance_cols(c, "t2"))
    _, _, usd = _table(frames, "t1", lambda c: _balance_cols(c, "t1"))
    if not bal["months"]:
        raise ValueError("t2: no monthly rows")
    months = sorted(bal["months"])
    lt = months[-1]
    y, m = lt
    last = bal["months"][lt]
    prev = bal["months"].get((y - 1, m))
    if last["exports"] is None or last["imports"] is None:
        raise ValueError("t2: latest month has no exports/imports")
    bcols = _balance_cols(_header(t2_rows, "t2")[1], "t2")
    sa_cols = {k: bcols[k] for k in ("exports_x", "imports_x", "deficit_x")}
    sa = _optional_section(t2_rows, t2_h, "Seasonally adjusted", sa_cols)
    trend = _optional_section(t2_rows, t2_h, "Trend data", sa_cols)

    _, _, uses = _table(frames, "t4", _spec(IMPORT_USES))
    _, _, exg = _table(frames, "t6", _spec(EXPORT_GROUPS))
    _, _, cons = _table(frames, "t8", _spec(CONSUMER))
    _, _, raw = _table(frames, "t10", _spec(RAW))
    _, _, inv = _table(frames, "t12", _spec(INVESTMENT))
    _, _, agri = _table(frames, "t14", _spec(AGRI))
    _, _, tech_m = _table(frames, "t20", _spec(TECH))
    inds, ind_total, _ = _by_industry(cbs.grid(frames["t18"], "t18"), "t18")

    ytd_now = _ytd_of(bal, y, m)
    ytd_prev = _ytd_of(bal, y - 1, m)
    ytd_label, ytd_prev_label = _ytd_name(y, m), _ytd_name(y - 1, m)

    def deficit_word(v):
        return "גירעון" if v >= 0 else "עודף"

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    exp_chg = _chg(last["exports"], prev and prev["exports"])
    kpis["exports"] = {"value": round(last["exports"] / 1000, 1), "display": _bn(last["exports"]),
                       "tone": "brand" if exp_chg is None else
                       "ok" if exp_chg > 0.01 else "danger" if exp_chg < -0.01 else "warn"}
    labels["exports_kpi"] = f"יצוא סחורות, {_mname(lt)} (מיליארד ₪)"
    kpis["imports"] = {"value": round(last["imports"] / 1000, 1), "display": _bn(last["imports"]),
                       "tone": "info"}
    labels["imports_kpi"] = f"יבוא סחורות, {_mname(lt)} (מיליארד ₪)"
    if last["deficit"] is not None:
        d0 = prev["deficit"] if prev else None
        dt = "brand" if d0 is None else "warn" if last["deficit"] > d0 else "ok"
        kpis["deficit"] = {"value": round(last["deficit"] / 1000, 1),
                           "display": fmt.num_he(abs(last["deficit"]) / 1000, 1), "tone": dt}
        labels["deficit_kpi"] = f"{deficit_word(last['deficit'])} מסחרי, {_mname(lt)} (מיליארד ₪)"
    ytd_def_chg = None
    if ytd_now and ytd_now["deficit"] is not None:
        ytd_def_chg = _chg(ytd_now["deficit"], ytd_prev and ytd_prev["deficit"])
        kpis["ytd_deficit"] = {"value": round(ytd_now["deficit"] / 1000, 1),
                               "display": fmt.num_he(abs(ytd_now["deficit"]) / 1000, 1),
                               "tone": "brand" if ytd_def_chg is None else
                               "warn" if ytd_def_chg > 0.02 else "ok" if ytd_def_chg < -0.02
                               else "brand"}
        labels["ytd_deficit_kpi"] = (f"{deficit_word(ytd_now['deficit'])} מסחרי מתחילת השנה, "
                                     f"{ytd_label} (מיליארד ₪)")
    if ytd_now and ytd_now["ratio"] is not None:
        r0 = ytd_prev["ratio"] if ytd_prev else None
        kpis["ratio"] = {"value": round(ytd_now["ratio"], 1),
                         "display": fmt.pct_of(ytd_now["ratio"]),
                         "tone": "brand" if r0 is None else "warn" if ytd_now["ratio"] < r0 - 1
                         else "ok" if ytd_now["ratio"] > r0 + 1 else "brand"}
        labels["ratio_kpi"] = ("היצוא כאחוז מהיבוא מתחילת השנה (ללא אוניות, מטוסים "
                               "ויהלומים)")

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables, flags = {}, {}, {}
    charts["monthly"] = {"x": [_mshort(t) for t in months],
                         "exports": [_bnr(bal["months"][t]["exports"]) for t in months],
                         "imports": [_bnr(bal["months"][t]["imports"]) for t in months],
                         "deficit": [_bnr(bal["months"][t]["deficit"]) for t in months]}
    tables["monthly"] = [[_mname(t), _bn(v["imports"], 2), _bn(v["exports"], 2),
                          _bn(v["deficit"], 2) if v["deficit"] is not None else ""]
                         for t in reversed(months) for v in [bal["months"][t]]]

    periods = [(str(yy), bal["annual"][yy], usd["annual"].get(yy)) for yy in sorted(bal["annual"])]
    for yy in (y - 1, y):
        v = _ytd_of(bal, yy, m)
        if v and m != 12:
            periods.append((_ytd_short(yy, m), v, _ytd_of(usd, yy, m)))
    charts["periods"] = {"x": [p[0] for p in periods],
                         "exports": [_bnr(p[1]["exports"], 1) for p in periods],
                         "imports": [_bnr(p[1]["imports"], 1) for p in periods],
                         "deficit": [_bnr(p[1]["deficit"], 1) for p in periods]}
    tables["periods"] = [[p[0], _bn(p[1]["imports"]), _bn(p[1]["exports"]), _bn(p[1]["deficit"]),
                          _bn(p[2]["imports"]) if p[2] else "",
                          _bn(p[2]["exports"]) if p[2] else ""] for p in periods]

    sa_m = sorted(t for t in sa if sa[t]["exports_x"] is not None)
    flags["sa"] = len(sa_m) >= 6
    if flags["sa"]:
        charts["sa"] = {"x": [_mshort(t) for t in sa_m],
                        "exports": [_bnr(sa[t]["exports_x"]) for t in sa_m],
                        "imports": [_bnr(sa[t]["imports_x"]) for t in sa_m],
                        "exports_trend": [_bnr(trend.get(t, {}).get("exports_x")) for t in sa_m],
                        "imports_trend": [_bnr(trend.get(t, {}).get("imports_x")) for t in sa_m]}
        # CBS publishes no trend for imports excl. ships, aircraft and diamonds
        # (only excl. fuels too): leave the series and column out when empty.
        imp_trend = any(v is not None for v in charts["sa"]["imports_trend"])
        if not imp_trend:
            del charts["sa"]["imports_trend"]
        tables["sa"] = [[_mname(t), _bn(sa[t]["imports_x"], 2) if sa[t]["imports_x"] else "",
                         _bn(sa[t]["exports_x"], 2)]
                        + ([_bn(trend[t]["imports_x"], 2) if trend.get(t, {}).get("imports_x")
                            else ""] if imp_trend else [])
                        + [_bn(trend[t]["exports_x"], 2) if trend.get(t, {}).get("exports_x")
                           else ""]
                        for t in reversed(sa_m)]
        labels["sa_cols"] = (["חודש", "יבוא, מנוכה עונתיות", "יצוא, מנוכה עונתיות"]
                             + (["יבוא, מגמה"] if imp_trend else []) + ["יצוא, מגמה"])

    um = sorted(uses["months"])
    use_keys = list(IMPORT_USES)
    charts["uses"] = {"x": [_mshort(t) for t in um],
                      "series": [{"name": IMPORT_USES[k][1],
                                  "data": [_bnr(uses["months"][t][k]) for t in um]}
                                 for k in use_keys]}
    use_rows = _ytd_rows(uses, IMPORT_USES, use_keys, y, m)
    use_total = sum(r[2] for r in use_rows)
    tables["uses"] = _bars_table(use_rows, use_total)

    cons_keys = [k for k in CONSUMER if k != "total"]
    cons_rows = _ytd_rows(cons, CONSUMER, cons_keys, y, m)
    cons_total = _ytd_of(cons, y, m, "total")
    charts["consumer"] = _bars(cons_rows)
    tables["consumer"] = _bars_table(cons_rows, cons_total)

    raw_keys = [k for k in RAW if k != "total"]
    raw_rows = _ytd_rows(raw, RAW, raw_keys, y, m)
    raw_total = _ytd_of(raw, y, m, "total")
    charts["raw"] = _bars(raw_rows)
    tables["raw"] = _bars_table(raw_rows, raw_total)

    inv_keys = [k for k in INVESTMENT if k != "total"]
    inv_rows = _ytd_rows(inv, INVESTMENT, inv_keys, y, m)
    inv_total = _ytd_of(inv, y, m, "total")
    charts["investment"] = _bars(inv_rows)
    tables["investment"] = _bars_table(inv_rows, inv_total)

    tm = sorted(tech_m["months"])
    charts["tech"] = {"x": [_mshort(t) for t in tm],
                      "series": [{"name": TECH[k][1],
                                  "data": [_bnr(tech_m["months"][t][k]) for t in tm]}
                                 for k in TECH]}
    levels = [r for r in inds if r["level"] is None]
    ind_tot_ytd = ind_total["values"]["ytd"]
    tables["tech"] = [[r["name"], _mn(r["values"]["ytd"]), _mn(r["values"]["ytd_prev"]),
                       _sp(_chg(r["values"]["ytd"], r["values"]["ytd_prev"])),
                       fmt.pct(r["values"]["ytd"] / ind_tot_ytd) if ind_tot_ytd else ""]
                      for r in levels]

    industries = [r for r in inds if r["level"] is not None and r["values"]["ytd"]]
    industries.sort(key=lambda r: (-r["values"]["ytd"], r["name"]))
    top = industries[:TOP_INDUSTRIES]
    ind_rows = [(r["name"], _short_industry(r["name"]), r["values"]["ytd"],
                 r["values"]["ytd_prev"], _chg(r["values"]["ytd"], r["values"]["ytd_prev"]))
                for r in top]
    charts["industries"] = _bars(ind_rows)
    tables["industries"] = [[r[1], _mn(r[2]), _mn(r[3]), _sp(r[4]),
                             fmt.pct(r[2] / ind_tot_ytd) if ind_tot_ytd else ""]
                            for r in ind_rows]

    em = sorted(t for t in exg["months"] if exg["months"][t]["total"] is not None)
    dia = {t: (exg["months"][t]["wholesale"] or 0) + (exg["months"][t]["working"] or 0)
           for t in em}
    charts["diamonds"] = {"x": [_mshort(t) for t in em],
                          "exports": [_bnr(dia[t]) for t in em],
                          "imports": [_bnr(uses["months"].get(t, {}).get("diamonds")) for t in em],
                          "share": [round(dia[t] / exg["months"][t]["total"] * 100, 1)
                                    if exg["months"][t]["total"] else None for t in em]}
    tables["diamonds"] = [[_mname(t), _mn(dia[t]),
                           _mn(uses["months"].get(t, {}).get("diamonds")),
                           fmt.pct(dia[t] / exg["months"][t]["total"])
                           if exg["months"][t]["total"] else ""] for t in reversed(em)]

    def dia_share(v):
        if not v or not v.get("total"):
            return None
        return ((v.get("wholesale") or 0) + (v.get("working") or 0)) / v["total"]

    dia_periods = [(str(yy), exg["annual"][yy]) for yy in sorted(exg["annual"])]
    for yy in (y - 1, y):
        v = _ytd_of(exg, yy, m)
        if v and m != 12:
            dia_periods.append((_ytd_name(yy, m), v))
    tables["diamond_periods"] = [[p[0], _mn((p[1]["wholesale"] or 0) + (p[1]["working"] or 0)),
                                  fmt.pct(dia_share(p[1])) if dia_share(p[1]) is not None else ""]
                                 for p in dia_periods]

    am = sorted(agri["months"])
    flags["agri"] = len(am) >= 6
    if flags["agri"]:
        charts["agri"] = {"x": [_mshort(t) for t in am],
                          "series": [{"name": AGRI[k][1],
                                      "data": [round(agri["months"][t][k] or 0, 1) for t in am]}
                                     for k in AGRI]}
        tables["agri"] = [[_mname(t)] + [_mn(agri["months"][t][k]) for k in AGRI]
                          for t in reversed(am)]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if last["deficit"] is not None and last["deficit"] > 0:
        s = (f"ב{_mname(lt)} יובאו לישראל סחורות בשווי {_bn(last['imports'])} מיליארד ₪ "
             f"ויוצאו סחורות בשווי {_bn(last['exports'])} מיליארד ₪: גירעון מסחרי של "
             f"{_bn(last['deficit'])} מיליארד ₪.")
        if prev and prev["deficit"]:
            c = _chg(last["deficit"], prev["deficit"])
            if c is not None and abs(c) >= 0.02:
                s += (f" הגירעון {'גדול' if c > 0 else 'קטן'} ב-{fmt.pct(abs(c))} מאשר "
                      f"ב{_mname((y - 1, m))}.")
        add("month", s)
    if ytd_now and ytd_prev and m != 12:
        ce = _chg(ytd_now["exports"], ytd_prev["exports"])
        ci = _chg(ytd_now["imports"], ytd_prev["imports"])
        if ce is not None and ci is not None and abs(ce) >= 0.005 and abs(ci) >= 0.005:
            s = (f"ב{_ytd_name(y, m)} היצוא {'עלה' if ce > 0 else 'ירד'} ב-"
                 f"{fmt.pct(abs(ce))} והיבוא {'עלה' if ci > 0 else 'ירד'} ב-{fmt.pct(abs(ci))} "
                 f"לעומת התקופה המקבילה ב-{y - 1}")
            if ytd_def_chg is not None and (ytd_now["deficit"] or 0) > 0 and abs(ytd_def_chg) >= 0.02:
                s += (f", והגירעון {'התרחב' if ytd_def_chg > 0 else 'הצטמצם'} ב-"
                      f"{fmt.pct(abs(ytd_def_chg))} ל-{_bn(ytd_now['deficit'])} מיליארד ₪")
            add("ytd", s + ".")
    u_now, u_prev = _ytd_of(usd, y, m), _ytd_of(usd, y - 1, m)
    if ytd_now and ytd_prev and u_now and u_prev and m != 12:
        ce_s = _chg(ytd_now["exports"], ytd_prev["exports"])
        ce_d = _chg(u_now["exports"], u_prev["exports"])
        rate_now = ytd_now["imports"] / u_now["imports"] if u_now["imports"] else None
        rate_prev = ytd_prev["imports"] / u_prev["imports"] if u_prev["imports"] else None
        if (ce_s is not None and ce_d is not None and rate_now and rate_prev
                and abs(ce_d - ce_s) >= 0.03):
            add("currency", f"במונחי דולר היצוא מתחילת השנה {_word(ce_d, 'עלה', 'ירד')} ב-"
                            f"{fmt.pct(abs(ce_d))}, ובשקלים {_word(ce_s, 'עלה', 'ירד')} ב-"
                            f"{fmt.pct(abs(ce_s))}. הפער נובע משער החליפין: השער הממוצע הגלום "
                            f"בנתוני היבוא {'ירד' if rate_now < rate_prev else 'עלה'} מ-"
                            f"{fmt.num_he(rate_prev, 2)} ₪ לדולר בתקופה המקבילה אשתקד ל-"
                            f"{fmt.num_he(rate_now, 2)} ₪ לדולר השנה.")
    movers = [r for r in use_rows if r[4] is not None and use_total and r[2] / use_total >= 0.05]
    if movers:
        mv = max(movers, key=lambda r: (abs(r[4]), r[0]))
        if abs(mv[4]) >= 0.1:
            add("uses", f"מבין סוגי היבוא, השינוי הגדול ביותר מתחילת השנה הוא ב{mv[1]}: "
                        f"{_word(mv[4])} של {fmt.pct(abs(mv[4]))}, ל-{_bn(mv[2])} מיליארד ₪ "
                        f"({fmt.pct(mv[2] / use_total)} מהיבוא).")
    if cons_total:
        cm = [r for r in cons_rows if r[4] is not None and r[2] / cons_total >= 0.05]
        if cm:
            top_c = max(cm, key=lambda r: (r[4], r[0]))
            if top_c[4] >= 0.08:
                add("consumer", f"ביבוא מוצרי הצריכה בולט הגידול ב{top_c[1]}: "
                                f"{fmt.pct(top_c[4])} יותר מאשר בתקופה המקבילה אשתקד "
                                f"({_bn(top_c[2])} מיליארד ₪ מתחילת השנה).")
    high = next((r for r in levels if "עילית" in r["name"] and "מעורבת" not in r["name"]), None)
    if high and ind_tot_ytd and high["values"]["ytd"]:
        sh = high["values"]["ytd"] / ind_tot_ytd
        p = ind_total["values"]["ytd_prev"]
        sh0 = high["values"]["ytd_prev"] / p if p and high["values"]["ytd_prev"] else None
        s = (f"תעשיות הטכנולוגיה העילית סיפקו {fmt.pct(sh)} מהיצוא התעשייתי (ללא יהלומים) "
             f"מתחילת השנה")
        if sh0 is not None and abs(sh - sh0) >= 0.005:
            s += f", לעומת {fmt.pct(sh0)} בתקופה המקבילה אשתקד"
        if top:
            s += (f". הענף הגדול ביותר: {_short_industry(top[0]['name'])}, "
                  f"{fmt.pct(top[0]['values']['ytd'] / ind_tot_ytd)} מהיצוא התעשייתי")
        add("tech", s + ".")
    shares = [(p[0], dia_share(p[1])) for p in dia_periods if dia_share(p[1]) is not None]
    if len(shares) >= 2:
        (p_old, s_old), (p_new, s_new) = shares[0], shares[-1]
        if abs(s_new - s_old) >= 0.005:
            add("diamonds", f"משקל היהלומים ביצוא הסחורות {'ירד' if s_new < s_old else 'עלה'} "
                            f"מ-{fmt.pct(s_old)} ב{'שנת ' if p_old.isdigit() else ''}{p_old} ל-"
                            f"{fmt.pct(s_new)} ב{'שנת ' if p_new.isdigit() else ''}{p_new}.")
    if flags["agri"]:
        cit = [(t, agri["months"][t]["citrus"] or 0) for t in am]
        tot_c = sum(v for _, v in cit)
        if tot_c > 0:
            best = sorted(cit, key=lambda tv: (-tv[1], tv[0]))[:3]
            sh3 = sum(v for _, v in best) / tot_c
            if sh3 >= 0.5:
                add("citrus", f"יצוא ההדרים עונתי מאוד: {fmt.pct(sh3)} מיצוא ההדרים ב-{len(cit)} "
                              f"החודשים שבנתונים נעשה בשלושה חודשים בלבד ("
                              + fmt.join_he([_mname(t) for t, _ in sorted(best)]) + ").")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"כמה סחורות ישראל מייבאת ומייצאת בכל חודש, מה גודל הגירעון המסחרי, "
                 f"מה מייבאים (חומרי גלם, מוצרי צריכה, מוצרי השקעה ואנרגיה) ומה מייצאים "
                 f"(לפי ענף ולפי רמה טכנולוגית). הנתונים מתוך ההודעה החודשית של הלשכה המרכזית "
                 f"לסטטיסטיקה (הלמ\"ס) על סחר החוץ בסחורות, ומתעדכנים עם כל הודעה חדשה. "
                 f"הנתון האחרון הוא ל{_mname(lt)}. הסכומים בשקלים במחירים שוטפים."),
        "monthly_note": (f"היבוא והיצוא של סחורות בכל חודש מאז {_mname(months[0])}, ומעליהם "
                         f"הגירעון המסחרי (היבוא פחות היצוא), במיליארדי ₪."),
        "monthly_aria": f"יבוא, יצוא וגירעון מסחרי לפי חודש, {_mname(months[0])} עד {_mname(lt)}",
        "monthly_caption": "יבוא, יצוא וגירעון לפי חודש (מיליארד ₪)",
        "periods_note": ("השנים המלאות האחרונות, ומתחילת השנה מול התקופה המקבילה אשתקד. "
                         "בטבלה גם הסכומים בדולרים, כי שינוי בשער החליפין משנה את התמונה."),
        "periods_aria": "יבוא, יצוא וגירעון לפי שנה ומתחילת השנה",
        "periods_caption": "יבוא, יצוא וגירעון לפי תקופה (מיליארד ₪ ומיליארד $)",
        "uses_note": ("היבוא בכל חודש לפי ייעוד הסחורה, במיליארדי ₪. בטבלה: הסכום מתחילת "
                      "השנה מול התקופה המקבילה אשתקד."),
        "uses_aria": "יבוא לפי סוג שימוש, לפי חודש",
        "uses_caption": f"יבוא לפי שימוש, {ytd_label} (מיליון ₪)",
        "consumer_note": (f"יבוא מוצרי צריכה לפי קבוצת סחורות, {ytd_label} מול "
                          f"{ytd_prev_label}, במיליוני ₪."),
        "consumer_aria": "יבוא מוצרי צריכה לפי קבוצה, מתחילת השנה",
        "consumer_caption": f"יבוא מוצרי צריכה, {ytd_label} (מיליון ₪)",
        "raw_note": (f"יבוא חומרי גלם ותשומות לייצור לפי קבוצה, כולל יהלומים וחומרי אנרגיה, "
                     f"{ytd_label} מול {ytd_prev_label}, במיליוני ₪."),
        "raw_aria": "יבוא חומרי גלם לפי קבוצה, מתחילת השנה",
        "raw_caption": f"יבוא חומרי גלם, {ytd_label} (מיליון ₪)",
        "investment_note": (f"יבוא מוצרי השקעה (מכונות, ציוד וכלי תחבורה לעסקים), {ytd_label} "
                            f"מול {ytd_prev_label}, במיליוני ₪."),
        "investment_aria": "יבוא מוצרי השקעה לפי קבוצה, מתחילת השנה",
        "investment_caption": f"יבוא מוצרי השקעה, {ytd_label} (מיליון ₪)",
        "tech_note": ("היצוא התעשייתי (ללא יהלומים) בכל חודש לפי העוצמה הטכנולוגית של הענף, "
                      "במיליארדי ₪. בטבלה: מתחילת השנה מול התקופה המקבילה אשתקד."),
        "tech_aria": "יצוא תעשייתי לפי עוצמה טכנולוגית, לפי חודש",
        "tech_caption": f"יצוא תעשייתי לפי עוצמה טכנולוגית, {ytd_label} (מיליון ₪)",
        "industries_note": (f"{len(top)} ענפי התעשייה עם היצוא הגדול ביותר, {ytd_label} מול "
                            f"{ytd_prev_label}, במיליוני ₪."),
        "industries_aria": "יצוא תעשייתי לפי ענף, מתחילת השנה",
        "industries_caption": f"יצוא תעשייתי לפי ענף, {ytd_label} (מיליון ₪)",
        "diamonds_note": ("יצוא יהלומים (מסחר סיטוני ועיבוד) ויבוא יהלומים (גולמיים ומעובדים, נטו) "
                          "בכל חודש, במיליארדי ₪, והחלק של היהלומים מכלל יצוא הסחורות."),
        "diamonds_aria": "יצוא ויבוא יהלומים לפי חודש",
        "diamonds_caption": "יהלומים לפי חודש (מיליון ₪)",
        "diamond_periods_caption": "יצוא יהלומים וחלקו מהיצוא, לפי תקופה (מיליון ₪)",
        "ytd_col": _ytd_short(y, m), "ytd_prev_col": _ytd_short(y - 1, m),
        "agri_cols": [AGRI[k][1] for k in AGRI],
    })
    if flags["sa"]:
        labels.update({
            "sa_note": ("יבוא ויצוא ללא אוניות, מטוסים ויהלומים, שתנודותיהם גדולות: נתון מנוכה "
                        "עונתיות וקו המגמה של הלמ\"ס, במיליארדי ₪. כך רואים את הכיוון בלי "
                        "רעש של חודש בודד."),
            "sa_aria": f"יבוא ויצוא מנוכי עונתיות ומגמה, {_mname(sa_m[0])} עד {_mname(sa_m[-1])}",
            "sa_caption": "יבוא ויצוא ללא אוניות, מטוסים ויהלומים (מיליארד ₪)",
        })
    if flags["agri"]:
        labels.update({
            "agri_note": "היצוא החקלאי בכל חודש לפי סוג הגידול, במיליוני ₪.",
            "agri_aria": "יצוא חקלאי לפי סוג גידול, לפי חודש",
            "agri_caption": "יצוא חקלאי לפי חודש וסוג (מיליון ₪)",
        })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    dword = deficit_word(last["deficit"] if last["deficit"] is not None else 0)
    summary = (f"יבוא ויצוא של סחורות והגירעון המסחרי של ישראל, לפי חודש, סוג סחורה וענף, "
               f"מנתוני הלמ\"ס. ב{_mname(lt)}: יצוא של {_bn(last['exports'])} מיליארד ₪ ויבוא של "
               f"{_bn(last['imports'])} מיליארד ₪.")
    desc = (f"היבוא והיצוא של ישראל: ב{_mname(lt)} {dword} מסחרי של "
            f"{_bn(abs(last['deficit'] or 0))} מיליארד ₪. יבוא לפי סוג, יצוא לפי ענף, יהלומים.")
    first_year = min([yy for yy in bal["annual"]] + [months[0][0]])
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_year}/{y}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "סחר החוץ של ישראל: יבוא, יצוא וגירעון מסחרי | הלמ\"ס",
                "description": desc,
                "name": "סחר החוץ של ישראל: יבוא ויצוא של סחורות",
                "alternate_names": ["הגירעון המסחרי של ישראל", "יבוא ויצוא סחורות",
                                    "מאזן הסחר של ישראל", "היצוא הישראלי", "נתוני סחר חוץ"],
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
