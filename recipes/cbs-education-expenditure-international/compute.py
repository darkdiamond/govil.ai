"""ההוצאה הלאומית לחינוך: השוואה בין-לאומית (CBS's yearly release built on
the OECD's Education at a Glance).

Every edition is a handful of one-year tables ("לוח N") plus chart-data
sheets ("תרשים N") that repeat their numbers. The table NUMBERS MOVE between
editions (the %-of-GDP-by-level table was t1 in 2024 and t2 since 2025), so
every table input (t1..t13, three spare slots, all optional) is read with
`cbs.grid` and each table is found by its TITLE text:

  gdp_level  הוצאה על מוסדות חינוך ... כאחוז מהתוצר   % of GDP by level (incl. pre-primary)
  gdp_np     ההוצאה הלאומית והציבורית ... מהתוצר       national vs public % of GDP
  shares     שיעור יחסי של הוצאה ציבורית ופרטית         public / private shares by level
  per_pupil  הוצאה לחינוך לתלמיד                        $ PPP per student by level
  pub_pupil  הוצאות המגזר הממשלתי לתלמיד               public $ PPP per student

The chart sheets ("תרשים") are skipped: their numbers are the tables'.
Countries are keyed by their English name (the Hebrew spellings vary
between tables). A table that is found but whose header labels are gone
raises; a table missing from an edition drops its section; a recognised
table without an Israel row raises (Israel is what the page is about).
"""
import re

import pandas as pd
from govlib import cbs, fmt

HEB = re.compile("[א-ת]")
EN_NAME = re.compile(r"^[A-Za-z][A-Za-z .,'’()\-]*$")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
TABLE_TITLE = re.compile(r"^לוח\s*\d+")

# English (as CBS prints it) → one Hebrew spelling. Unknown names fall back
# to the table's own Hebrew cell, so a new country still shows up.
EN_ALIAS = {"Netherland": "Netherlands", "Czech Republic": "Czechia",
            "Slovakia": "Slovak Republic", "Republic of Korea": "Korea",
            "Turkey": "Türkiye", "Turkiye": "Türkiye"}
HE = {
    "Israel": "ישראל", "OECD": "ממוצע OECD", "Australia": "אוסטרליה", "Austria": "אוסטריה",
    "Belgium": "בלגיה", "Canada": "קנדה", "Chile": "צ'ילה", "Colombia": "קולומביה",
    "Costa Rica": "קוסטה ריקה", "Czechia": "צ'כיה", "Denmark": "דנמרק", "Estonia": "אסטוניה",
    "Finland": "פינלנד", "France": "צרפת", "Germany": "גרמניה", "Greece": "יוון",
    "Hungary": "הונגריה", "Iceland": "איסלנד", "Ireland": "אירלנד", "Italy": "איטליה",
    "Japan": "יפן", "Korea": "קוריאה הדרומית", "Latvia": "לטביה", "Lithuania": "ליטא",
    "Luxembourg": "לוקסמבורג", "Mexico": "מקסיקו", "Netherlands": "הולנד",
    "New Zealand": "ניו זילנד", "Norway": "נורווגיה", "Poland": "פולין", "Portugal": "פורטוגל",
    "Slovak Republic": "סלובקיה", "Slovenia": "סלובניה", "Spain": "ספרד", "Sweden": "שוודיה",
    "Switzerland": "שווייץ", "Türkiye": "טורקיה", "United Kingdom": "הממלכה המאוחדת",
    "United States": "ארצות הברית",
}
SKIP_EN = ("Thereof", "Source", "Including", "Excluding", "Converted", "Percentages",
           "Dollars", "Central Bureau", "Published", "Table", "TABLE", "not include",
           "the OECD", "for which", "can be", "Total private", "The available")
MIN_COUNTRIES = 3  # a ranking needs at least this many countries beside Israel


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    """The table title: the "לוח N" cell and the Hebrew text of the two rows
    under it (titles wrap). Empty for chart sheets and unknown layouts."""
    for i, r in enumerate(rows[:10]):
        for c in r:
            if TABLE_TITLE.match(c):
                more = [x for rr in rows[i + 1:i + 3] for x in rr if HEB.search(x)]
                return " ".join([c] + more)
    return ""


def _kind(t):
    if not t:
        return None
    if "שיעור יחסי" in t:
        return "shares"
    if "לתלמיד" in t:
        return "pub_pupil" if ("ממשלתי" in t or "ציבורי" in t) else "per_pupil"
    if "הלאומית והציבורית" in t:
        return "gdp_np"
    if "הוצאה על מוסדות חינוך" in t and ("תוצר" in t or 'תמ"ג' in t):
        return "gdp_level"
    return None


def _tables(frames):
    """{kind: rows} over every non-empty table input; first match by stem
    number wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        k = _kind(_title(rows))
        if k and k not in out:
            out[k] = rows
    return out


# ── parsing ──────────────────────────────────────────────────────────────


def _hrow(rows, labels, name):
    """First row holding every label (substring match); raises."""
    for i, r in enumerate(rows):
        if all(any(lab in c for c in r) for lab in labels):
            return i
    raise ValueError(f"{name}: header labels {labels!r} not found")


def _col(row, label, exact=False, start=0):
    return cbs.col_after(row, label, start, contains=not exact)


def _key(en):
    en = en.strip()
    if en.startswith("OECD"):
        return "OECD"
    return EN_ALIAS.get(en, en)


def _countries(rows, start, cols, name):
    """{key: (hebrew, [values])} for the data rows after `start`: a row with
    an English country name outside `cols` and at least one number in them."""
    out = {}
    for r in rows[start:]:
        vals = [cbs.val(r, j) for j in cols]
        if all(v is None for v in vals):
            continue
        en = he = ""
        for j, c in enumerate(r):
            if j in cols or not c:
                continue
            if not en and EN_NAME.match(c) and not c.startswith(SKIP_EN):
                en = c
            elif not he and HEB.search(c):
                he = c
        if not en:
            continue
        k = _key(en)
        if k in out:
            continue
        out[k] = (HE.get(k) or he or en, vals)
    if "Israel" not in out:
        raise ValueError(f"{name}: no Israel row")
    return out


def _year(rows, stop):
    """The data year: a bare year cell above the data, else the last year in
    a title cell ("... 2023")."""
    for r in rows[:stop]:
        for c in r:
            if cbs.YEAR.match(c):
                return int(c)
    for r in rows[:stop]:
        for c in r:
            if c.startswith(("לוח", "Table", "TABLE")):
                ys = YEAR_IN.findall(c)
                if ys:
                    return int(ys[-1])
    return None


def parse_gdp_level(rows):
    h = _hrow(rows, ["Tertiary", "All level"], "gdp_level")
    hr = rows[h]
    cols = [_col(hr, "Primary"), _col(hr, "Tertiary"), _col(hr, "All level")]
    return _year(rows, h), _countries(rows, h + 1, cols, "gdp_level")


def parse_gdp_np(rows):
    h = _hrow(rows, ["ההוצאה הציבורית", "ההוצאה הלאומית"], "gdp_np")
    hr = rows[h]
    cols = [_col(hr, "ההוצאה הציבורית"), _col(hr, "ההוצאה הלאומית")]
    return _year(rows, h), _countries(rows, h + 1, cols, "gdp_np")


def parse_shares(rows):
    g = _hrow(rows, ["Tertiary education", "All level"], "shares")
    gr = rows[g]
    starts = [_col(gr, "Tertiary education"), _col(gr, "Primary"), _col(gr, "All level")]
    hh = _hrow(rows, ["Households", "Public"], "shares")
    for s in starts:
        if cbs.cell(rows[hh], s + 2) != "Households" or cbs.cell(rows[hh], s + 3) != "Public":
            raise ValueError("shares: Households/Public columns moved")
    cols = [s + k for s in starts for k in (1, 2, 3)]  # other private, households, public
    data = _countries(rows, hh + 1, cols, "shares")
    return _year(rows, g), data


def parse_per_pupil(rows):
    h = _hrow(rows, ["Pre-Primary", "Secondary", "Bachelor"], "per_pupil")
    hr = rows[h]
    cols = [_col(hr, "Pre-Primary"), _col(hr, "Primary", exact=True), _col(hr, "Secondary"),
            _col(hr, "Total"), _col(hr, "Bachelor"), _col(hr, "Short-cycle")]
    return _year(rows, h), _countries(rows, h + 1, cols, "per_pupil")


def parse_pub_pupil(rows):
    h = _hrow(rows, ["All levels of education", "Tertiary"], "pub_pupil")
    hr = rows[h]
    cols = [_col(hr, "All levels"), _col(hr, "Primary"), _col(hr, "Tertiary", exact=True)]
    return _year(rows, h), _countries(rows, h + 1, cols, "pub_pupil")


PARSERS = {"gdp_level": parse_gdp_level, "gdp_np": parse_gdp_np, "shares": parse_shares,
           "per_pupil": parse_per_pupil, "pub_pupil": parse_pub_pupil}


# ── helpers ──────────────────────────────────────────────────────────────


def _r(v, d=2):
    return None if v is None else round(v, d)


def _p1(v):
    return "–" if v is None else f"{v:.1f}%"


def _usd(v):
    return "–" if v is None else f"{fmt.int_he(v)}"


def _ranked(data, idx, desc=True):
    """[(key, he, value)] of countries with a value at idx, sorted by value
    (ties by key), OECD average included."""
    items = [(k, he, vals[idx]) for k, (he, vals) in data.items() if vals[idx] is not None]
    return sorted(items, key=lambda t: ((-t[2] if desc else t[2]), t[0]))


def _rank_of(data, idx, key="Israel"):
    """(rank, n) of `key` among the countries (OECD average excluded)."""
    items = [t for t in _ranked(data, idx) if t[0] != "OECD"]
    for i, t in enumerate(items):
        if t[0] == key:
            return i + 1, len(items)
    return None, len(items)


def _v(data, key, idx):
    t = data.get(key)
    return None if t is None else t[1][idx]


def _ratio(a, b):
    return None if a is None or b in (None, 0) else a / b


def _rank_phrase(rank, n, hi="הגבוה ביותר", lo="הנמוך ביותר"):
    """'the highest of N countries' / 'Nth of N'; None with too few countries."""
    if rank is None or n < MIN_COUNTRIES + 1:
        return None
    if rank == 1:
        return f"{hi} מבין {n} המדינות בלוח"
    if rank == n:
        return f"{lo} מבין {n} המדינות בלוח"
    return f"במקום ה-{rank} מבין {n} המדינות בלוח"


def _cmp(a, b, unit_fmt, more="מעל", less="מתחת"):
    """'מעל ממוצע OECD (X)' style phrase."""
    if a is None or b is None:
        return None
    if abs(a - b) / max(abs(b), 1e-9) < 0.02:
        return f"בדומה לממוצע OECD ({unit_fmt(b)})"
    return f"{more if a > b else less} לממוצע OECD ({unit_fmt(b)})"


def _mark(he, key):
    return {"name": he, "hl": "il" if key == "Israel" else ("oecd" if key == "OECD" else "")}


# ── sections ─────────────────────────────────────────────────────────────


def sec_gdp_level(data, year):
    items = _ranked(data, 2)
    labels, prim, tert, rest, total, marks, rows = [], [], [], [], [], [], []
    for k, he, tot in items:
        p, t = data[k][1][0], data[k][1][1]
        r = None if p is None or t is None else max(tot - p - t, 0.0)
        labels.append(he)
        marks.append(_mark(he, k)["hl"])
        prim.append(_r(p))
        tert.append(_r(t))
        rest.append(_r(r))
        total.append(_r(tot))
        rows.append([he, _p1(tot), _p1(p), _p1(t)])
    il, oecd = _v(data, "Israel", 2), _v(data, "OECD", 2)
    rank, n = _rank_of(data, 2)
    lede = None
    if il is not None and oecd is not None:
        lede = (f"ב-{year} הסתכמה ההוצאה על מוסדות חינוך בישראל, בכל דרגי החינוך, ב-{il:.1f}% "
                f"מהתמ\"ג, לעומת {oecd:.1f}% בממוצע מדינות OECD.")
        rp = _rank_phrase(rank, n, "השיעור הגבוה ביותר", "השיעור הנמוך ביותר")
        if rp:
            lede = lede[:-1] + f" ({rp})."
    chart = {"x": labels, "hl": marks, "series": [
        {"name": "יסודי, על-יסודי ומכינות", "data": prim},
        {"name": "חינוך גבוה", "data": tert},
        {"name": "קדם-יסודי ושאר ההוצאה", "data": rest},
    ], "total": total}
    return chart, rows, lede


def sec_gdp_np(data, year):
    items = _ranked(data, 1)
    labels, pub, nat, marks, rows = [], [], [], [], []
    for k, he, n_ in items:
        p = data[k][1][0]
        labels.append(he)
        marks.append(_mark(he, k)["hl"])
        pub.append(_r(p))
        nat.append(_r(n_))
        rows.append([he, _p1(n_), _p1(p), _p1(None if p is None else n_ - p)])
    chart = {"x": labels, "hl": marks, "series": [
        {"name": "ההוצאה הלאומית (כל המקורות)", "data": nat},
        {"name": "ההוצאה הציבורית", "data": pub}]}
    il_n, il_p = _v(data, "Israel", 1), _v(data, "Israel", 0)
    oe_n, oe_p = _v(data, "OECD", 1), _v(data, "OECD", 0)
    lede = None
    if None not in (il_n, il_p, oe_n, oe_p):
        lede = (f"ללא חינוך קדם-יסודי: ההוצאה הלאומית בישראל ב-{year} הייתה {il_n:.1f}% מהתמ\"ג, "
                f"ומתוכה ההוצאה הציבורית {il_p:.1f}%. בממוצע OECD: {oe_n:.1f}% ו-{oe_p:.1f}% בהתאמה.")
    return chart, rows, lede


LEVELS_PP = ["קדם-יסודי", "יסודי", "על-יסודי", "חינוך גבוה (סך הכול)", "תארים אקדמיים",
             "על-תיכוני"]


def sec_per_pupil(data, year):
    il, oe = data["Israel"][1], data.get("OECD", (None, [None] * 6))[1]
    lv = {"x": [], "il": [], "oecd": [], "pct": []}
    lv_rows = []
    for j, name in enumerate(LEVELS_PP):
        if il[j] is None and oe[j] is None:
            continue
        ratio = _ratio(il[j], oe[j])
        lv["x"].append(name)
        lv["il"].append(_r(il[j], 0))
        lv["oecd"].append(_r(oe[j], 0))
        lv["pct"].append(None if ratio is None else round(ratio * 100))
        lv_rows.append([name, _usd(il[j]), _usd(oe[j]),
                        "–" if ratio is None else f"{round(ratio * 100)}%"])
    # ranking per level (the selector): pre-primary, primary, secondary, tertiary total
    metrics = []
    for j in (0, 1, 2, 3):
        items = _ranked(data, j)
        if len([t for t in items if t[0] not in ("Israel", "OECD")]) < MIN_COUNTRIES:
            continue
        metrics.append({"label": LEVELS_PP[j].replace(" (סך הכול)", ""),
                        "x": [t[1] for t in items], "y": [_r(t[2], 0) for t in items],
                        "hl": [_mark(t[1], t[0])["hl"] for t in items]})
    keys = sorted(data, key=lambda k: (k != "Israel", k != "OECD", data[k][0]))
    rank_rows = [[data[k][0]] + [_usd(data[k][1][j]) for j in (0, 1, 2, 3)] for k in keys]
    lede = None
    parts = []
    for j, name in ((1, "ביסודי"), (2, "בעל-יסודי"), (3, "בחינוך הגבוה")):
        ratio = _ratio(il[j], oe[j])
        if ratio is not None:
            parts.append(f"{name} {round(ratio * 100)}%")
    if parts:
        lede = (f"ההוצאה לתלמיד בישראל ב-{year} (בדולרים לפי שווי כוח קנייה) כאחוז מממוצע OECD: "
                + fmt.join_he(parts) + ".")
    return lv, lv_rows, metrics, rank_rows, lede


def sec_shares(data, year):
    # columns per group g (0 tertiary, 1 primary-secondary, 2 all): other, households, public
    def trio(vals, g):
        o, hh, pub = vals[3 * g], vals[3 * g + 1], vals[3 * g + 2]
        if pub is None:
            return None
        rest = max(100.0 - pub - (hh or 0) - (o or 0), 0.0)
        return pub, hh, o, rest

    items = []
    for k, (he, vals) in data.items():
        t = trio(vals, 2)
        if t is not None:
            items.append((k, he, t))
    items.sort(key=lambda x: (-x[2][0], x[0]))
    ch = {"x": [], "hl": [], "pub": [], "hh": [], "oth": [], "intl": []}
    rows = []
    for k, he, (pub, hh, o, rest) in items:
        ch["x"].append(he)
        ch["hl"].append(_mark(he, k)["hl"])
        ch["pub"].append(_r(pub, 1))
        ch["hh"].append(_r(hh, 1))
        ch["oth"].append(_r(o, 1))
        ch["intl"].append(_r(rest, 1))
        rows.append([he, _p1(pub), _p1(hh), _p1(o)])
    lv = {"x": [], "pub": [], "hh": [], "oth": [], "intl": []}
    lv_rows = []
    names = ("חינוך גבוה", "יסודי, על-יסודי ומכינות", "כל דרגי החינוך")
    for g, gname in enumerate(names):
        for key, who in (("Israel", "ישראל"), ("OECD", "OECD")):
            if key not in data:
                continue
            t = trio(data[key][1], g)
            if t is None:
                continue
            pub, hh, o, rest = t
            lv["x"].append(f"{who}: {gname}")
            lv["pub"].append(_r(pub, 1))
            lv["hh"].append(_r(hh, 1))
            lv["oth"].append(_r(o, 1))
            lv["intl"].append(_r(rest, 1))
            lv_rows.append([f"{who}: {gname}", _p1(pub), _p1(hh), _p1(o)])
    il_t = trio(data["Israel"][1], 0)
    oe_t = trio(data["OECD"][1], 0) if "OECD" in data else None
    lede = None
    if il_t and oe_t and il_t[1] is not None and oe_t[1] is not None:
        lede = (f"בחינוך הגבוה מימנו משקי הבית בישראל {il_t[1]:.1f}% מההוצאה ב-{year}, לעומת "
                f"{oe_t[1]:.1f}% בממוצע OECD; המקורות הציבוריים מימנו {il_t[0]:.1f}% "
                f"(OECD: {oe_t[0]:.1f}%).")
    return ch, rows, lv, lv_rows, lede


def sec_pub_pupil(data, year):
    items = _ranked(data, 0)
    ch = {"x": [t[1] for t in items], "y": [_r(t[2], 0) for t in items],
          "hl": [_mark(t[1], t[0])["hl"] for t in items]}
    keys = [t[0] for t in items]
    rows = [[data[k][0], _usd(data[k][1][0]), _usd(data[k][1][1]), _usd(data[k][1][2])]
            for k in keys]
    il, oe = data["Israel"][1], data.get("OECD", (None, [None] * 3))[1]
    lede = None
    r_all, r_t = _ratio(il[0], oe[0]), _ratio(il[2], oe[2])
    if r_all is not None:
        lede = (f"ההוצאה הציבורית לתלמיד בישראל ב-{year} הייתה {fmt.int_he(il[0])} דולר "
                f"({round(r_all * 100)}% מממוצע OECD)")
        if r_t is not None:
            lede += f", ובחינוך הגבוה {fmt.int_he(il[2])} דולר ({round(r_t * 100)}% מהממוצע)"
        lede += "."
    return ch, rows, lede


# ── insights ─────────────────────────────────────────────────────────────


def ins_gdp(t, year):
    if "gdp_level" not in t:
        return None
    d = t["gdp_level"]
    il, oe = _v(d, "Israel", 2), _v(d, "OECD", 2)
    if il is None or oe is None:
        return None
    rank, n = _rank_of(d, 2)
    rp = _rank_phrase(rank, n, "השיעור הגבוה ביותר", "השיעור הנמוך ביותר")
    s = (f"ישראל הוציאה ב-{year} על מוסדות חינוך {il:.1f}% מהתמ\"ג, "
         f"{_cmp(il, oe, lambda v: f'{v:.1f}%')}")
    return s + (f", {rp}." if rp else ".")


def ins_gdp_split(t, year):
    if "gdp_level" not in t:
        return None
    d = t["gdp_level"]
    ilp, oep = _v(d, "Israel", 0), _v(d, "OECD", 0)
    ilt, oet = _v(d, "Israel", 1), _v(d, "OECD", 1)
    if None in (ilp, oep, ilt, oet):
        return None
    if ilp > oep and ilt < oet:
        return (f"היתרון של ישראל בהוצאה כאחוז מהתמ\"ג מרוכז בבתי הספר: {ilp:.1f}% מהתמ\"ג ליסודי "
                f"ולעל-יסודי (OECD: {oep:.1f}%), אבל רק {ilt:.1f}% לחינוך הגבוה (OECD: {oet:.1f}%).")
    if ilp > oep and ilt > oet:
        return (f"ישראל מוציאה מעל ממוצע OECD כאחוז מהתמ\"ג גם על בתי הספר ({ilp:.1f}% לעומת "
                f"{oep:.1f}%) וגם על החינוך הגבוה ({ilt:.1f}% לעומת {oet:.1f}%).")
    return None


def ins_private(t, year):
    if "gdp_np" not in t:
        return None
    d = t["gdp_np"]
    il_n, il_p, oe_n, oe_p = (_v(d, "Israel", 1), _v(d, "Israel", 0), _v(d, "OECD", 1),
                              _v(d, "OECD", 0))
    if None in (il_n, il_p, oe_n, oe_p) or il_n <= 0 or oe_n <= 0:
        return None
    il_s, oe_s = (il_n - il_p) / il_n * 100, (oe_n - oe_p) / oe_n * 100
    word = "גבוה" if il_s > oe_s else "נמוך"
    return (f"ללא קדם-יסודי, {il_s:.1f}% מההוצאה הלאומית לחינוך בישראל אינם ציבוריים "
            f"({il_n - il_p:.1f}% מהתמ\"ג), שיעור {word} מממוצע OECD ({oe_s:.1f}%).")


def ins_pupil_gap(t, year):
    if "per_pupil" not in t:
        return None
    d = t["per_pupil"]
    il, oe = d["Israel"][1], d.get("OECD", (None, [None] * 6))[1]
    rp, rt = _ratio(il[1], oe[1]), _ratio(il[3], oe[3])
    if rp is None or rt is None:
        return None
    if rp >= 0.95 and rt < 0.85:
        return (f"בבית הספר היסודי ההוצאה לתלמיד בישראל ({fmt.int_he(il[1])} דולר) "
                f"{'גבוהה מ' if rp > 1.02 else 'דומה ל'}ממוצע OECD ({fmt.int_he(oe[1])}), "
                f"אבל בחינוך הגבוה היא {round(rt * 100)}% בלבד מהממוצע "
                f"({fmt.int_he(il[3])} לעומת {fmt.int_he(oe[3])} דולר).")
    return (f"ההוצאה לתלמיד בישראל היא {round(rp * 100)}% מממוצע OECD ביסודי "
            f"ו-{round(rt * 100)}% בחינוך הגבוה.")


def ins_preprimary(t, year):
    if "per_pupil" not in t:
        return None
    d = t["per_pupil"]
    il, oe = _v(d, "Israel", 0), _v(d, "OECD", 0)
    r = _ratio(il, oe)
    if r is None or r > 0.9:
        return None
    rank, n = _rank_of(d, 0)
    s = (f"בחינוך הקדם-יסודי ההוצאה לילד בישראל, {fmt.int_he(il)} דולר, היא {round(r * 100)}% "
         f"בלבד מממוצע OECD ({fmt.int_he(oe)} דולר)")
    rp = _rank_phrase(rank, n, "הגבוהה ביותר", "הנמוכה ביותר")
    return s + (f", {rp}." if rp else ".")


def ins_households(t, year):
    if "shares" not in t:
        return None
    d = t["shares"]
    il, oe = d["Israel"][1][1], (d["OECD"][1][1] if "OECD" in d else None)
    if il is None or oe is None or il < oe * 1.2:
        return None
    items = [(k, v[1][1]) for k, v in d.items() if v[1][1] is not None and k != "OECD"]
    items.sort(key=lambda x: (-x[1], x[0]))
    pos = [k for k, _ in items].index("Israel") + 1
    s = (f"משקי הבית בישראל מממנים {il:.1f}% מההוצאה על מוסדות החינוך הגבוה, "
         f"לעומת {oe:.1f}% בממוצע OECD")
    if pos <= 3 and len(items) >= MIN_COUNTRIES + 1:
        s += f" (המקום ה-{pos} מבין {len(items)} המדינות בלוח)"
    return s + "."


def ins_public_share(t, year):
    if "shares" not in t:
        return None
    d = t["shares"]
    il = d["Israel"][1][8]
    oe = d["OECD"][1][8] if "OECD" in d else None
    if il is None or oe is None:
        return None
    return (f"בכל דרגי החינוך יחד, {il:.1f}% מההוצאה על מוסדות חינוך בישראל ממומנים ממקורות "
            f"ציבוריים, {_cmp(il, oe, lambda v: f'{v:.1f}%')}.")


def ins_pub_pupil(t, year):
    if "pub_pupil" not in t:
        return None
    d = t["pub_pupil"]
    il, oe = d["Israel"][1], d.get("OECD", (None, [None] * 3))[1]
    r = _ratio(il[2], oe[2])
    if r is None or r > 0.8:
        return None
    rank, n = _rank_of(d, 2)
    s = (f"ההוצאה הציבורית לסטודנט בישראל, {fmt.int_he(il[2])} דולר, היא {round(r * 100)}% "
         f"מממוצע OECD ({fmt.int_he(oe[2])} דולר)")
    rp = _rank_phrase(rank, n, "הגבוהה ביותר", "הנמוכה ביותר")
    return s + (f", {rp}." if rp else ".")


INSIGHTS = (("gdp", ins_gdp), ("gdp_split", ins_gdp_split), ("pupil_gap", ins_pupil_gap),
            ("preprimary", ins_preprimary), ("households", ins_households),
            ("private", ins_private), ("public_share", ins_public_share),
            ("pub_pupil", ins_pub_pupil))


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    raw = _tables(frames)
    if not raw:
        raise ValueError("no recognised table in the release")
    t, years = {}, {}
    for k, rows in raw.items():
        y, data = PARSERS[k](rows)
        t[k], years[k] = data, y
    ys = [y for y in years.values() if y]
    if not ys:
        raise ValueError("no data year found")
    year = max(ys)
    rel = cbs.latest_release(frames["releases"])
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}

    charts, tables, ledes, flags, yl = {}, {}, {}, {}, {}
    if "gdp_level" in t:
        charts["gdp"], tables["gdp"], ledes["gdp"] = sec_gdp_level(t["gdp_level"], years["gdp_level"])
        flags["gdp"] = len(charts["gdp"]["x"]) > MIN_COUNTRIES
    if "gdp_np" in t:
        charts["np"], tables["np"], ledes["np"] = sec_gdp_np(t["gdp_np"], years["gdp_np"])
        flags["np"] = len(charts["np"]["x"]) > MIN_COUNTRIES
    if "per_pupil" in t:
        lv, lv_rows, metrics, rank_rows, lede = sec_per_pupil(t["per_pupil"], years["per_pupil"])
        charts["pp_lv"], tables["pp_lv"], ledes["pp_lv"] = lv, lv_rows, lede
        flags["pp_lv"] = bool(lv["x"])
        charts["pp_rank"], tables["pp_rank"] = {"metrics": metrics}, rank_rows
        flags["pp_rank"] = bool(metrics)
    if "shares" in t:
        ch, rows, lv, lv_rows, lede = sec_shares(t["shares"], years["shares"])
        charts["sh"], tables["sh"] = ch, rows
        charts["sh_lv"], tables["sh_lv"], ledes["sh_lv"] = lv, lv_rows, lede
        flags["sh"] = len(ch["x"]) > MIN_COUNTRIES
        flags["sh_lv"] = bool(lv["x"])
    if "pub_pupil" in t:
        charts["pub"], tables["pub"], ledes["pub"] = sec_pub_pupil(t["pub_pupil"], years["pub_pupil"])
        flags["pub"] = len(charts["pub"]["x"]) > MIN_COUNTRIES
    for k, y in years.items():
        yl[k] = y if y else year

    insights = []
    for iid, fn in INSIGHTS:
        s = fn(t, yl.get({"gdp": "gdp_level", "gdp_split": "gdp_level", "private": "gdp_np",
                          "pupil_gap": "per_pupil", "preprimary": "per_pupil",
                          "households": "shares", "public_share": "shares",
                          "pub_pupil": "pub_pupil"}[iid], year))
        if s:
            insights.append({"id": iid, "text_he": s})

    # KPIs
    kpis, labels = {}, {}
    if "gdp_level" in t:
        d = t["gdp_level"]
        il, oe = _v(d, "Israel", 2), _v(d, "OECD", 2)
        if il is not None:
            kpis["gdp"] = {"value": _r(il), "display": f"{il:.1f}%",
                           "tone": "info" if oe is not None and il > oe else "brand"}
            labels["gdp_kpi"] = f"ההוצאה על מוסדות חינוך בישראל, אחוז מהתמ\"ג ({yl['gdp_level']})"
        if oe is not None:
            kpis["gdp_oecd"] = {"value": _r(oe), "display": f"{oe:.1f}%", "tone": "brand"}
            labels["gdp_oecd_kpi"] = f"ממוצע OECD, אחוז מהתמ\"ג ({yl['gdp_level']})"
    if "per_pupil" in t:
        d = t["per_pupil"]
        il, oe = _v(d, "Israel", 3), _v(d, "OECD", 3)
        r = _ratio(il, oe)
        if r is not None:
            kpis["tert"] = {"value": round(r * 100), "display": f"{round(r * 100)}%",
                            "tone": "warn" if r < 0.8 else ("ok" if r >= 1 else "brand")}
            labels["tert_kpi"] = ("ההוצאה לסטודנט בחינוך הגבוה בישראל כאחוז מממוצע OECD "
                                  f"({yl['per_pupil']})")
        il1 = _v(d, "Israel", 1)
        if il1 is not None:
            kpis["prim"] = {"value": _r(il1, 0), "display": fmt.int_he(il1), "tone": "brand"}
            labels["prim_kpi"] = f"הוצאה לתלמיד ביסודי בישראל, דולר לפי שווי כוח קנייה ({yl['per_pupil']})"
    if "shares" in t:
        d = t["shares"]
        hh = d["Israel"][1][1]
        oe = d["OECD"][1][1] if "OECD" in d else None
        if hh is not None:
            kpis["hh"] = {"value": _r(hh, 1), "display": f"{hh:.1f}%",
                          "tone": "warn" if oe is not None and hh > oe * 1.2 else "brand"}
            labels["hh_kpi"] = f"חלק משקי הבית במימון החינוך הגבוה בישראל ({yl['shares']})"

    il_gdp = kpis.get("gdp", {}).get("display")
    oe_gdp = kpis.get("gdp_oecd", {}).get("display")
    lede = (f"כמה ישראל מוציאה על חינוך בהשוואה למדינות OECD: ההוצאה על מוסדות חינוך כאחוז "
            f"מהתמ\"ג, ההוצאה לתלמיד בכל שלב חינוך (בדולרים לפי שווי כוח קנייה) ומי מממן אותה. "
            f"הנתונים לשנת {year}, מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) "
            f"המבוססת על שנתון OECD, Education at a Glance.")
    if il_gdp and oe_gdp:
        lede += f" ההוצאה בישראל: {il_gdp} מהתמ\"ג, לעומת {oe_gdp} בממוצע OECD."
    labels["lede"] = lede
    labels["year"] = str(year)

    if il_gdp and oe_gdp:
        summary = (f"ההוצאה הלאומית לחינוך בישראל בהשוואה למדינות OECD בשנת {year}: {il_gdp} מהתמ\"ג "
                   f"לעומת {oe_gdp} בממוצע, הוצאה לתלמיד לפי שלב חינוך ומקורות המימון. מתוך הלמ\"ס.")
        desc = (f"השוואת ההוצאה לחינוך בישראל למדינות OECD ({year}): {il_gdp} מהתמ\"ג לעומת {oe_gdp} "
                f"בממוצע, הוצאה לתלמיד לפי שלב ומי מממן.")
    else:
        summary = (f"ההוצאה הלאומית לחינוך בישראל בהשוואה למדינות OECD בשנת {year}: הוצאה לתלמיד "
                   f"לפי שלב חינוך ומקורות המימון. מתוך הלמ\"ס.")
        desc = (f"השוואת ההוצאה לחינוך בישראל למדינות OECD ({year}): הוצאה לתלמיד לפי שלב חינוך, "
                f"אחוז מהתמ\"ג ומי מממן את מוסדות החינוך.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "rankings",
            "temporal_coverage": str(year),
            "spatial_coverage": "ישראל ומדינות OECD",
            "seo": {
                "title": "ההוצאה לחינוך בישראל מול OECD | השוואה בין-לאומית",
                "description": desc,
                "name": "ההוצאה לחינוך בישראל בהשוואה למדינות OECD",
                "alternate_names": ["ההוצאה הלאומית לחינוך: השוואה בין-לאומית",
                                    "הוצאה לתלמיד בישראל ו-OECD",
                                    "Education at a Glance ישראל"],
            },
        },
        "kpis": kpis,
        "labels": labels,
        "charts": charts,
        "tables": tables,
        "ledes": {k: v for k, v in ledes.items() if v},
        "flags": flags,
        "years": yl,
        "insights": insights,
        "release": release,
    }
