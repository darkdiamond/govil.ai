"""בעלות על דירה: CBS's multi-year release on owned, rented and assisted-living
dwellings, built from the municipal arnona (property tax) registry.

Each edition is a locality table (dwellings, rented dwellings and the rented
share per locality and year, since 2013), a statistical-area table, and a set
of chart sheets ("תרשים N"). CBS renumbers the sheets between editions (the
population-group chart was t10 in 2024 and t9 in 2026), so every table input
(t1..t17, three spare, all optional) is read with `cbs.grid` and recognised
by the text of its title and headers, never by its stem:

  loc       "סמל יישוב" + "סך הכל דירות" + "אחוז דירות בשכירות"   required
  district  tenure by district (בעלות / שכירות / דיור מוגן)
  age       tenure by the holder's age group
  age_trend rented share by age group, one row per year
  group     tenure by population group
  jt        rented share by age in Jerusalem and Tel Aviv-Yafo
  arab      rented share among Arab holders, main localities
  turn_city / turn_age   tenant turnover between the last two years
  public / public_district  public housing, by year and by district
  eu        rented share of households, EU countries (Eurostat)
  building  rented share by building size (older editions only)

A table recognised by its title whose header labels are gone raises (the
layout changed: a human should look). A table missing from an edition drops
its section. Data rows (districts, ages, localities, years) may come and go.
"""
import re

from govlib import cbs, fmt

TABLE_INPUTS = [f"t{i}" for i in range(1, 18)]
YEAR = re.compile(r"^(?:19|20)\d\d$")
FIRST_INT = re.compile(r"\d+")
MIN_CITY_DWELLINGS = 20000
MAX_CITIES = 20


# ---------------------------------------------------------------- helpers

def _r(v, d=2):
    return None if v is None else round(float(v), d)


def _p(v):
    return fmt.pct_of(v)


def _pp(v):
    """Percentage points with a sign (U+2212 minus)."""
    body = f"{abs(v):.1f}"
    if float(body) == 0:
        return body
    return ("+" if v > 0 else fmt.MINUS) + body


def _age_key(label):
    if label.startswith("עד"):
        return (0, label)
    m = FIRST_INT.search(label)
    return (int(m.group()) if m else 999, label)


def _blob(rows, n=16):
    return " ".join(c for r in rows[:n] for c in r if c)


def _classify(rows):
    b = _blob(rows)
    if "סמל יישוב" in b and "סך הכל דירות" in b and "אחוז דירות בשכירות" in b:
        return "loc"
    if "אזור סטטיסטי" in b or "אזורים סטטיסטיים" in b:
        return "stat"
    if "האיחוד האירופי" in b:
        return "eu"
    if "התחלפו שוכרים" in b:
        return "turn_age" if "גיל" in b else "turn_city"
    if "מחזיקים ערבים" in b:
        return "arab"
    if "בירושלים ובתל אביב" in b:
        return "jt"
    if "גרים בשכירות לפי קבוצת גיל" in b:
        return "age_trend"
    if "קבוצת גיל של המחזיק" in b:
        return "age"
    if "קבוצת אוכלוסייה" in b:
        return "group"
    if "הדיור הציבורי" in b and "מחוז" in b:
        return "public_district"
    if "דיור ציבורי" in b:
        return "public"
    if "לפי מחוז" in b:
        return "district"
    if "מספר דירות במבנה" in b:
        return "building"
    if "דירות למגורים" in b:
        return "trend"
    return None


def _header_row(rows, labels, name):
    """First row holding every label (exact match); raises when none does."""
    for i, r in enumerate(rows):
        if all(lab in r for lab in labels):
            return i
    raise ValueError(f"{name}: header labels {labels!r} not found")


def _label_of(row, value_cols):
    """The row's label: its first non-numeric cell outside the value columns
    ("ירושלים", "עד 34", "65+")."""
    for j, c in enumerate(row):
        if j not in value_cols and c and cbs.num(c) is None:
            return c.replace(" -", "-")
    return ""


def _cat_rows(rows, h, cols):
    """Rows after header h: (label, {key: value}) while some value parses."""
    out = []
    vc = set(cols.values())
    for r in rows[h + 1:]:
        vals = {k: cbs.val(r, j) for k, j in cols.items()}
        if all(v is None for v in vals.values()):
            continue
        lab = _label_of(r, vc)
        if not lab:
            continue
        out.append((lab, vals))
    return out


def _col_contains(row, text):
    for j, c in enumerate(row):
        if text in c:
            return j
    return None


# ---------------------------------------------------------------- tables

def _parse_loc(rows):
    h = _header_row(rows, ["סמל יישוב", "יישוב"], "loc")
    head, sub = rows[h], rows[h + 1]
    code_c = head.index("סמל יישוב")
    name_c = head.index("יישוב")
    ycols = [(j, int(c)) for j, c in enumerate(head) if YEAR.match(c)]
    if not ycols:
        raise ValueError("loc: no year columns")
    years = {}
    for k, (j, y) in enumerate(ycols):
        stop = ycols[k + 1][0] if k + 1 < len(ycols) else len(sub)
        m = {}
        for jj in range(j, stop):
            c = cbs.cell(sub, jj)
            if c == "סך הכל דירות":
                m["tot"] = jj
            elif c == "דירות בשכירות":
                m["rent"] = jj
            elif c == "אחוז דירות בשכירות":
                m["pct"] = jj
        if "tot" not in m or "rent" not in m:
            raise ValueError(f"loc: columns for {y} not found")
        years[y] = m
    yrs = sorted(years)

    def rec(r):
        out = {}
        for y in yrs:
            m = years[y]
            tot, rent = cbs.val(r, m["tot"]), cbs.val(r, m["rent"])
            p = cbs.val(r, m["pct"]) if "pct" in m else None
            if p is None and tot and rent is not None:
                p = rent / tot * 100
            out[y] = (tot, rent, p)
        return out

    total = None
    locs = []
    for r in rows[h + 2:]:
        code, name = cbs.cell(r, code_c), cbs.cell(r, name_c)
        if not name:
            continue
        if code.isdigit():
            locs.append((name, int(code), rec(r)))
        elif name == "סך הכל":
            total = rec(r)
    if total is None:
        raise ValueError("loc: national total row not found")
    return yrs, total, locs


def _parse_tenure(rows, name, cat_label=None):
    h = _header_row(rows, ["בעלות", "שכירות"], name)
    head = rows[h]
    cols = {"own": head.index("בעלות"), "rent": head.index("שכירות")}
    j = _col_contains(head, "דיור מוגן")
    if j is not None:
        cols["assisted"] = j
    out = []
    for lab, v in _cat_rows(rows, h, cols):
        if lab in ("סך הכל",) or cat_label and lab == cat_label:
            continue
        if v["own"] is None or v["rent"] is None:
            continue
        out.append({"label": lab, "own": v["own"], "rent": v["rent"],
                    "assisted": v.get("assisted") or 0.0})
    return out


def _parse_two(rows, name, value_label):
    """A label column + one value column whose header contains value_label."""
    for h, r in enumerate(rows):
        j = _col_contains(r, value_label)
        if j is not None and not cbs.cell(r, j).startswith(("תרשים", "לוח")):
            break
    else:
        raise ValueError(f"{name}: header {value_label!r} not found")
    out = []
    for lab, v in _cat_rows(rows, h, {"v": j}):
        if v["v"] is not None:
            out.append((lab, v["v"]))
    return out


def _parse_years(rows, name):
    """A year column + value columns named by the last header row above the
    first year row. Returns (names, [(year, [values])])."""
    yc = cbs.best_col(rows, lambda v: bool(YEAR.match(v)))
    if yc is None:
        raise ValueError(f"{name}: no year rows")
    first = next(i for i, r in enumerate(rows) if YEAR.match(cbs.cell(r, yc)))
    vcols = sorted({j for r in rows[first:] if YEAR.match(cbs.cell(r, yc))
                    for j, c in enumerate(r) if j != yc and cbs.num(c) is not None})
    hdr = None
    for i in range(first - 1, -1, -1):
        if sum(1 for j in vcols if cbs.cell(rows[i], j)) >= len(vcols):
            hdr = rows[i]
            break
    if hdr is None:
        raise ValueError(f"{name}: series header not found")
    names = [cbs.cell(hdr, j) for j in vcols]
    data = {}
    for r in rows[first:]:
        y = cbs.cell(r, yc)
        if YEAR.match(y):
            data[int(y)] = [cbs.val(r, j) for j in vcols]
    return names, sorted(data.items())


# ---------------------------------------------------------------- compute

def compute(frames):
    found = {}
    for key in TABLE_INPUTS:
        df = frames.get(key)
        if df is None or df.empty:
            continue
        rows = cbs.grid(df, key)
        kind = _classify(rows)
        if kind and kind not in found:
            found[kind] = rows
    if "loc" not in found:
        raise ValueError("locality table (סמל יישוב / סך הכל דירות) not found in any input")

    rel = cbs.latest_release(frames["releases"])
    labels, charts, tables, kpis, callouts = {}, {}, {}, {}, {}
    flags = {k: False for k in ("cities", "loclist", "district", "age", "age_trend", "group", "arab",
                                "jt", "turn_city", "turn_age", "public", "public_district", "eu",
                                "building")}
    ins = {}

    # --- national trend + localities
    yrs, total, locs = _parse_loc(found["loc"])
    tr = [(y, total[y]) for y in yrs if total[y][0] and total[y][2] is not None]
    if len(tr) < 2:
        raise ValueError("loc: fewer than two years with a national total")
    y0, (tot0, rent0, p0) = tr[0]
    y1, (tot1, rent1, p1) = tr[-1]
    charts["trend"] = {"x": [str(y) for y, _ in tr],
                       "tot": [_r(v[0] / 1000, 1) for _, v in tr],
                       "pct": [_r(v[2]) for _, v in tr]}
    tables["trend"] = [[str(y), fmt.int_he(v[0]), fmt.int_he(v[1]) if v[1] is not None else "–",
                        fmt.num_he(v[2])] for y, v in tr]
    kpis["dwellings"] = {"value": tot1, "display": fmt.int_he(tot1), "tone": "brand"}
    kpis["rent"] = {"value": round(p1, 1), "display": _p(p1), "tone": "brand"}
    dp = p1 - p0
    kpis["rent_chg"] = {"value": round(dp, 1), "display": _pp(dp),
                        "tone": "info"}
    labels["dwellings_kpi"] = f"דירות למגורים בישראל ({y1})"
    labels["rent_kpi"] = f"אחוז הדירות בשכירות ({y1})"
    labels["rent_chg_kpi"] = f"שינוי באחוז הדירות בשכירות מאז {y0} (נקודות אחוז)"
    labels["trend_aria"] = (f"מספר הדירות למגורים ואחוז הדירות בשכירות, {y0}-{y1}: "
                            f"{fmt.int_he(tot1 / 1000)} אלף דירות ו-{_p(p1)} בשכירות ב-{y1}")
    labels["trend_note"] = (f"מלאי הדירות למגורים (באלפים, עמודות) ואחוז הדירות המושכרות (קו), "
                            f"{y0}-{y1}.")
    growth = (tot1 / tot0 - 1) if tot0 else None
    if abs(dp) >= 0.5:
        word = "עלה" if dp > 0 else "ירד"
        ins["rent_trend"] = (f"אחוז הדירות בשכירות {word} מ-{_p(p0)} ב-{y0} ל-{_p(p1)} ב-{y1} "
                             f"({_pp(dp)} נקודות אחוז). ב-{y1} היו בשכירות "
                             f"{fmt.int_he(rent1)} דירות מתוך {fmt.int_he(tot1)}.")
    if growth is not None and rent0 and rent1 is not None and growth > 0:
        rg = rent1 / rent0 - 1
        if rg > growth * 1.2:
            ins["stock"] = (f"מלאי הדירות גדל ב-{fmt.pct(growth)} בין {y0} ל-{y1}, ומספר הדירות "
                            f"המושכרות גדל ב-{fmt.pct(rg)}: השכירות צמחה מהר יותר מהמלאי.")
        else:
            ins["stock"] = (f"מלאי הדירות למגורים גדל ב-{fmt.pct(growth)} בין {y0} ל-{y1}, "
                            f"מ-{fmt.int_he(tot0)} ל-{fmt.int_he(tot1)} דירות.")

    # localities: the largest ones with a value in the latest year
    last = [(n, c, v[y1]) for n, c, v in locs if v.get(y1) and v[y1][0] and v[y1][2] is not None]
    missing = sum(1 for n, c, v in locs if not (v.get(y1) and v[y1][2] is not None))
    big = sorted((t for t in last if t[2][0] >= MIN_CITY_DWELLINGS),
                 key=lambda t: (-t[2][0], t[1]))[:MAX_CITIES]
    big.sort(key=lambda t: (-t[2][2], t[1]))
    if len(big) >= 3:
        flags["cities"] = True
        first = {n: v.get(y0) for n, c, v in locs}  # names are unique within the table
        charts["cities"] = {
            "y": [n for n, _, _ in big],
            "now": [_r(v[2]) for _, _, v in big],
            "then": [_r(first[n][2]) if first.get(n) and first[n][2] is not None else None
                     for n, _, _ in big]}
        tables["cities"] = [[n, fmt.int_he(v[0]), fmt.num_he(v[2]),
                             fmt.num_he(first[n][2]) if first.get(n) and first[n][2] is not None else "–"]
                            for n, _, v in big]
        labels["cities_cols"] = ["יישוב", f"דירות ({y1})", f"% בשכירות {y1}", f"% בשכירות {y0}"]
        gone = sorted(n for n, c, v in locs
                      if v.get(y1) and (v[y1][0] or 0) >= MIN_CITY_DWELLINGS and v[y1][2] is None)
        labels["cities_note"] = (f"{len(big)} היישובים הגדולים (לפחות {fmt.int_he(MIN_CITY_DWELLINGS)} "
                                 f"דירות), לפי אחוז הדירות בשכירות ב-{y1}, לעומת {y0}."
                                 + (f" אין נתון לשנת {y1} עבור {fmt.join_he(gone)}." if gone else ""))
        labels["cities_aria"] = (f"אחוז הדירות בשכירות ביישובים הגדולים, {y1}: הגבוה ביותר ב{big[0][0]} "
                                 f"({_p(big[0][2][2])})")
        labels["y0"], labels["y1"] = str(y0), str(y1)
        top, low = big[0], big[-1]
        ins["cities"] = (f"מבין היישובים הגדולים, אחוז הדירות בשכירות הגבוה ביותר ב-{y1} היה "
                         f"ב{top[0]} ({_p(top[2][2])}) והנמוך ביותר ב{low[0]} ({_p(low[2][2])}).")
    if last:
        flags["loclist"] = True
        tables["loclist"] = [[n, fmt.int_he(v[0]), fmt.int_he(v[1]) if v[1] is not None else "–",
                              fmt.num_he(v[2])]
                             for n, c, v in sorted(last, key=lambda t: (t[0], t[1]))]
        labels["loclist_cols"] = ["יישוב", f"דירות ({y1})", f"בשכירות ({y1})", "% בשכירות"]
        labels["loclist_note"] = (f"{len(last)} עיריות ומועצות מקומיות, לפי סדר האלף-בית"
                                  + (f". ל-{missing} יישובים אין נתון לשנת {y1}." if missing else "."))

    # --- tenure by district
    if "district" in found:
        rows = _parse_tenure(found["district"], "district")
        nat = next((r for r in rows if "ארצי" in r["label"]), None)
        dist = sorted((r for r in rows if "ארצי" not in r["label"]),
                      key=lambda r: (-r["rent"], r["label"]))
        if len(dist) >= 2:
            flags["district"] = True
            charts["district"] = {"y": [r["label"] for r in dist],
                                  "own": [_r(r["own"]) for r in dist],
                                  "rent": [_r(r["rent"]) for r in dist],
                                  "assisted": [_r(r["assisted"]) for r in dist]}
            tables["district"] = [[r["label"], fmt.num_he(r["own"]), fmt.num_he(r["rent"]),
                                   fmt.num_he(r["assisted"])] for r in dist]
            hi, lo = dist[0], dist[-1]
            labels["district_aria"] = (f"צורת החזקה בדירה לפי מחוז: השכירות הגבוהה ביותר במחוז "
                                       f"{hi['label']} ({_p(hi['rent'])})")
            ins["district"] = (f"במחוז {hi['label']} {_p(hi['rent'])} מהדירות מושכרות, לעומת "
                               f"{_p(lo['rent'])} במחוז {lo['label']}.")
        if nat:
            kpis["own"] = {"value": round(nat["own"], 1), "display": _p(nat["own"]), "tone": "brand"}
            labels["own_kpi"] = "אחוז הדירות בבעלות המחזיקים בהן"

    # --- tenure by age
    if "age" in found:
        rows = sorted(_parse_tenure(found["age"], "age"), key=lambda r: _age_key(r["label"]))
        if len(rows) >= 2:
            flags["age"] = True
            charts["age"] = {"x": [r["label"] for r in rows],
                             "own": [_r(r["own"]) for r in rows],
                             "rent": [_r(r["rent"]) for r in rows],
                             "assisted": [_r(r["assisted"]) for r in rows]}
            tables["age"] = [[r["label"], fmt.num_he(r["own"]), fmt.num_he(r["rent"]),
                              fmt.num_he(r["assisted"])] for r in rows]
            young = rows[0]
            peak = max(rows, key=lambda r: (r["own"], r["label"]))
            labels["age_aria"] = (f"צורת החזקה בדירה לפי גיל המחזיק: בקבוצת הגיל {young['label']} "
                                  f"{_p(young['own'])} בבעלות")
            if peak is not young and peak["own"] - young["own"] >= 10:
                ins["age"] = (f"בקרב מחזיקים בגיל {young['label']} רק {_p(young['own'])} מהדירות "
                              f"בבעלותם, לעומת {_p(peak['own'])} בקבוצת הגיל {peak['label']}.")
            asst = max(rows, key=lambda r: (r["assisted"], r["label"]))
            if asst["assisted"] >= 1:
                callouts["age"] = (f"דיור מוגן בולט בקבוצת הגיל {asst['label']}: "
                                   f"{_p(asst['assisted'])} מהדירות.")

    # --- rented share by age, per year
    if "age_trend" in found:
        names, data = _parse_years(found["age_trend"], "age_trend")
        data = [(y, v) for y, v in data if any(x is not None for x in v)]
        if len(data) >= 2 and names:
            flags["age_trend"] = True
            charts["age_trend"] = {"x": [str(y) for y, _ in data],
                                   "series": [{"name": n, "data": [_r(v[k]) for _, v in data]}
                                              for k, n in enumerate(names)]}
            tables["age_trend"] = [[str(y)] + [fmt.num_he(x) if x is not None else "–" for x in v]
                                   for y, v in data]
            labels["age_trend_cols"] = ["שנה"] + [f"גיל {n}" for n in names]
            ya, yb = data[0][0], data[-1][0]
            labels["age_trend_aria"] = f"אחוז הגרים בשכירות לפי קבוצת גיל, {ya}-{yb}"
            ch = []
            for k, n in enumerate(names):
                a, b = data[0][1][k], data[-1][1][k]
                if a is not None and b is not None:
                    ch.append((n, a, b, b - a))
            rising = [c for c in ch if c[3] >= 2]
            flat = [c for c in ch if abs(c[3]) < 1]
            if rising and flat:
                r, f = rising[0], flat[0]
                ins["age_trend"] = (f"בקבוצת הגיל {r[0]} אחוז הגרים בשכירות עלה מ-{_p(r[1])} ב-{ya} ל-"
                                    f"{_p(r[2])} ב-{yb}, ואילו בקבוצת הגיל {f[0]} הוא נותר כמעט ללא "
                                    f"שינוי ({_p(f[1])} לעומת {_p(f[2])}).")

    # --- population group
    if "group" in found:
        rows = _parse_tenure(found["group"], "group")
        if len(rows) >= 2:
            flags["group"] = True
            charts["group"] = {"y": [r["label"] for r in rows],
                               "own": [_r(r["own"]) for r in rows],
                               "rent": [_r(r["rent"]) for r in rows],
                               "assisted": [_r(r["assisted"]) for r in rows]}
            tables["group"] = [[r["label"], fmt.num_he(r["own"]), fmt.num_he(r["rent"]),
                                fmt.num_he(r["assisted"])] for r in rows]
            labels["group_aria"] = "צורת החזקה בדירה לפי קבוצת אוכלוסייה"
            by = {r["label"]: r for r in rows}
            if "יהודים" in by and "ערבים" in by:
                j, a = by["יהודים"], by["ערבים"]
                ins["group"] = (f"{_p(a['own'])} מהדירות שמחזיקים בהן ערבים הן בבעלות המחזיקים, "
                                f"לעומת {_p(j['own'])} מהדירות שמחזיקים בהן יהודים.")

    # --- Arab holders by locality
    if "arab" in found:
        rows = _parse_two(found["arab"], "arab", "אחוז דירות בשכירות")
        tot = next((v for lab, v in rows if "סך הכל" in lab), None)
        rows = sorted(((lab, v) for lab, v in rows if "סך הכל" not in lab),
                      key=lambda t: (t[1], t[0]))
        if len(rows) >= 3:
            flags["arab"] = True
            charts["arab"] = {"y": [lab for lab, _ in rows], "v": [_r(v) for _, v in rows],
                              "total": _r(tot)}
            tables["arab"] = [[lab, fmt.num_he(v)] for lab, v in rows]
            labels["arab_aria"] = (f"אחוז הדירות בשכירות בקרב מחזיקים ערבים לפי יישוב: מ-{_p(rows[0][1])} "
                                   f"ב{rows[0][0]} עד {_p(rows[-1][1])} ב{rows[-1][0]}")
            labels["arab_note"] = ("אחוז הדירות המושכרות מבין הדירות שמחזיקים בהן ערבים, ביישובים עיקריים"
                                   + (f". בכלל האוכלוסייה הערבית: {_p(tot)}." if tot is not None else "."))
            if rows[-1][1] - rows[0][1] >= 10:
                callouts["arab"] = (f"הפער בין היישובים גדול: {_p(rows[0][1])} ב{rows[0][0]} לעומת "
                                    f"{_p(rows[-1][1])} ב{rows[-1][0]}.")

    # --- Jerusalem vs Tel Aviv by age
    if "jt" in found:
        jrows = found["jt"]
        h = next((i for i, r in enumerate(jrows) if "ירושלים" in r and _col_contains(r, "תל אביב") is not None
                  and not any(c.startswith(("תרשים", "לוח")) for c in r)), None)
        if h is None:
            raise ValueError("jt: header ירושלים / תל אביב not found")
        cj, ct = jrows[h].index("ירושלים"), _col_contains(jrows[h], "תל אביב")
        rows = sorted(((lab, v["j"], v["t"]) for lab, v in _cat_rows(jrows, h, {"j": cj, "t": ct})
                       if v["j"] is not None and v["t"] is not None), key=lambda t: _age_key(t[0]))
        if len(rows) >= 2:
            flags["jt"] = True
            charts["jt"] = {"x": [r[0] for r in rows], "j": [_r(r[1]) for r in rows],
                            "t": [_r(r[2]) for r in rows]}
            tables["jt"] = [[r[0], fmt.num_he(r[1]), fmt.num_he(r[2])] for r in rows]
            labels["jt_aria"] = (f"אחוז הדירות בשכירות לפי גיל המחזיק בירושלים ובתל אביב-יפו: בגיל "
                                 f"{rows[0][0]} {_p(rows[0][1])} ו-{_p(rows[0][2])}")
            y = rows[0]
            if y[2] - y[1] >= 5:
                ins["jt"] = (f"בתל אביב-יפו {_p(y[2])} מהדירות שהמחזיקים בהן בגיל {y[0]} מושכרות, "
                             f"לעומת {_p(y[1])} בירושלים.")

    # --- tenant turnover
    for key, title_word in (("turn_city", "יישוב"), ("turn_age", "גיל")):
        if key not in found:
            continue
        rows = _parse_two(found[key], key, "תחלופ")
        if key == "turn_age":
            rows = sorted(rows, key=lambda t: _age_key(t[0]))
        else:
            rows = sorted(rows, key=lambda t: (-t[1], t[0]))
        if len(rows) >= 2:
            flags[key] = True
            charts[key] = {"y": [lab for lab, _ in rows], "v": [_r(v) for _, v in rows]}
            tables[key] = [[lab, fmt.num_he(v)] for lab, v in rows]
    pair = None
    for r in found.get("turn_city", [])[:12]:
        for c in r:
            m = re.search(r"((?:19|20)\d\d)-((?:19|20)\d\d)", c)
            if m:
                pair = m.group(1), m.group(2)
                break
        if pair:
            break
    if pair is None:
        for r in found.get("turn_age", [])[:12]:
            for c in r:
                m = re.search(r"((?:19|20)\d\d)-((?:19|20)\d\d)", c)
                if m:
                    pair = m.group(1), m.group(2)
                    break
            if pair:
                break
    a, b = (sorted(pair) if pair else ("", ""))
    labels["turn_period"] = f"בין {a} ל-{b}" if pair else "בין השנתיים האחרונות"
    if flags.get("turn_city"):
        c = charts["turn_city"]
        labels["turn_city_aria"] = (f"אחוז הדירות שבהן התחלפו שוכרים, בערים הגדולות: הגבוה ביותר ב{c['y'][0]} "
                                    f"({_p(c['v'][0])})")
        if c["v"][0] >= 1.5 * c["v"][-1]:
            ins["turn_city"] = (f"תחלופת השוכרים {labels['turn_period']} הייתה הגבוהה ביותר ב{c['y'][0]} "
                                f"({_p(c['v'][0])}) והנמוכה ביותר ב{c['y'][-1]} "
                                f"({_p(c['v'][-1])}).")
    if flags.get("turn_age"):
        c = charts["turn_age"]
        labels["turn_age_aria"] = (f"אחוז הדירות שבהן התחלפו שוכרים לפי גיל השוכר: בגיל {c['y'][0]} "
                                   f"{_p(c['v'][0])}")
        if c["v"][0] >= 2 * c["v"][-1]:
            callouts["turn_age"] = (f"שוכרים בגיל {c['y'][0]} מחליפים דירה הרבה יותר: {_p(c['v'][0])}, "
                                    f"לעומת {_p(c['v'][-1])} בגיל {c['y'][-1]}.")

    # --- public housing
    if "public" in found:
        names, data = _parse_years(found["public"], "public")
        idx = {n: k for k, n in enumerate(names)}
        kp = next((k for n, k in idx.items() if n == "דיור ציבורי"), None)
        ka = next((k for n, k in idx.items() if "מוגן" in n), None)
        kt = next((k for n, k in idx.items() if n == "סך הכל"), None)
        if kp is None:
            raise ValueError("public: column דיור ציבורי not found")
        data = [(y, v) for y, v in data if v[kp] is not None]
        if len(data) >= 2:
            flags["public"] = True

            def tot_of(v):
                if kt is not None and v[kt] is not None:
                    return v[kt]
                return v[kp] + (v[ka] or 0 if ka is not None else 0)

            charts["public"] = {"x": [str(y) for y, _ in data],
                                "pub": [_r(v[kp], 1) for _, v in data],
                                "asst": [_r(v[ka], 1) if ka is not None else None for _, v in data]}
            tables["public"] = [[str(y), fmt.num_he(tot_of(v)), fmt.num_he(v[kp]),
                                 fmt.num_he(v[ka]) if ka is not None and v[ka] is not None else "–"]
                                for y, v in data]
            (ya, va), (yb, vb) = data[0], data[-1]
            ta, tb = tot_of(va), tot_of(vb)
            kpis["public"] = {"value": round(tb, 1), "display": fmt.num_he(tb),
                              "tone": "warn" if tb < ta * 0.95 else "brand"}
            labels["public_kpi"] = f"דירות בדיור הציבורי, באלפים ({yb})"
            labels["public_aria"] = (f"דירות בדיור הציבורי, {ya}-{yb}: "
                                     f"{fmt.num_he(tb)} אלף ב-{yb}")
            share = tb * 1000 / tot1 if yb == y1 and tot1 else None
            chg = vb[kp] / va[kp] - 1 if va[kp] else None
            if chg is not None and abs(chg) >= 0.03:
                word = "ירד" if chg < 0 else "עלה"
                ins["public"] = (f"מספר הדירות בדיור הציבורי (ללא דיור מוגן ציבורי) {word} מ-"
                                 f"{fmt.num_he(va[kp])} אלף ב-{ya} ל-{fmt.num_he(vb[kp])} אלף ב-{yb} "
                                 f"({fmt.signed_pct(chg)})"
                                 + (f". כל הדיור הציבורי יחד הוא {fmt.pct(share)} ממלאי הדירות." if share else "."))
    if "public_district" in found:
        rows = _parse_two(found["public_district"], "public_district", "אחוזים")
        rows = sorted(((lab, v) for lab, v in rows if "סך הכל" not in lab), key=lambda t: (-t[1], t[0]))
        if len(rows) >= 2:
            flags["public_district"] = True
            charts["public_district"] = {"y": [lab for lab, _ in rows], "v": [_r(v) for _, v in rows]}
            tables["public_district"] = [[lab, fmt.num_he(v)] for lab, v in rows]
            labels["public_district_aria"] = (f"התפלגות הדיור הציבורי לפי מחוז: {rows[0][0]} "
                                              f"{_p(rows[0][1])}")
            if rows[0][1] >= 25:
                callouts["public_district"] = (f"{_p(rows[0][1])} מדירות הדיור הציבורי נמצאות במחוז "
                                               f"{rows[0][0]}.")

    # --- international
    if "eu" in found:
        erows = found["eu"]
        h = next((i for i, r in enumerate(erows) if _col_contains(r, "שם מדינה (עברית)") is not None), None)
        if h is None:
            raise ValueError("eu: header שם מדינה (עברית) not found")
        cn = _col_contains(erows[h], "שם מדינה (עברית)")
        cv = _col_contains(erows[h], "אחוז")
        if cv is None:
            raise ValueError("eu: value header not found")
        rows = []
        for r in erows[h + 1:]:
            n, v = cbs.cell(r, cn), cbs.val(r, cv)
            if n and v is not None:
                rows.append((n, v))
        rows.sort(key=lambda t: (t[1], t[0]))
        if len(rows) >= 5:
            flags["eu"] = True
            eu_year = None
            for r in erows[:h + 1]:
                for c in r:
                    m = re.search(r"((?:19|20)\d\d)\s*$", c)
                    if m and ("האיחוד" in c or "שכירות" in c):
                        eu_year = m.group(1)
            # Axis labels drop a parenthetical ("האיחוד האירופי (27 מדינות)") so
            # they fit the 375px axis; the table keeps the full name.
            charts["eu"] = {"y": [re.sub(r"\s*\([^)]*\)", "", n).strip() or n for n, _ in rows], "v": [_r(v, 1) for _, v in rows],
                            "isr": [n == "ישראל" for n, _ in rows],
                            "avg": ["האיחוד האירופי" in n or "OECD" in n for n, _ in rows]}
            tables["eu"] = [[n, fmt.num_he(v)] for n, v in rows]
            labels["eu_note"] = ("אחוז משקי הבית המתגוררים בשכירות במדינות אירופה ובישראל, לפי Eurostat"
                                 + (f", {eu_year}." if eu_year else "."))
            labels["eu_aria"] = "אחוז משקי הבית בשכירות במדינות אירופה ובישראל"
            isr = next((t for t in rows if t[0] == "ישראל"), None)
            eu = next((t for t in rows if "האיחוד האירופי" in t[0]), None)
            countries = [t for t in rows if "האיחוד האירופי" not in t[0] and "OECD" not in t[0]]
            if isr and eu:
                rank = sum(1 for t in countries if t[1] > isr[1]) + 1
                rel_word = "נמוך" if isr[1] < eu[1] else "גבוה"
                ins["eu"] = (f"לפי Eurostat, {_p(isr[1])} ממשקי הבית בישראל גרים בשכירות, {rel_word} "
                             f"מהממוצע באיחוד האירופי ({_p(eu[1])}). ישראל במקום ה-{rank} מתוך "
                             f"{len(countries)} המדינות בהשוואה, מהגבוה לנמוך.")

    # --- building size (older editions)
    if "building" in found:
        brows = found["building"]
        h = next((i for i, r in enumerate(brows) if "1-2" in r), None)
        if h is not None and h + 1 < len(brows):
            hdr = [c for c in brows[h] if c]
            vals = [cbs.num(c) for c in brows[h + 1] if c]
            pairs = [(a, v) for a, v in zip(hdr, vals) if v is not None]
            if len(pairs) >= 3:
                flags["building"] = True
                charts["building"] = {"x": [a for a, _ in pairs], "v": [_r(v) for _, v in pairs]}
                tables["building"] = [[a, fmt.num_he(v)] for a, v in pairs]
                labels["building_aria"] = "אחוז הדירות בשכירות לפי מספר הדירות במבנה"

    # --- prose
    release_year = rel["RELEASE_DATE"][:4]
    labels["lede"] = (f"נתוני הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על בעלות על דירה ושכירות בישראל, {y0}-{y1}, "
                      f"מתוך מרשם הדירות והמבנים שמבוסס על נתוני הארנונה של הרשויות המקומיות. ב-{y1} "
                      f"היו בישראל {fmt.int_he(tot1)} דירות למגורים, ו-{_p(p1)} מהן היו בשכירות"
                      + (f"; {_p(kpis['own']['value'])} היו בבעלות המחזיקים בהן." if "own" in kpis else ".")
                      + " בעמוד: בעלות ושכירות לפי מחוז, גיל וקבוצת אוכלוסייה, אחוז השכירות בכל יישוב, "
                      "תחלופת שוכרים, הדיור הציבורי והשוואה לאירופה.")
    labels["release_year"] = release_year

    order = ["rent_trend", "stock", "district", "age", "age_trend", "cities", "group", "jt",
             "turn_city", "public", "eu"]
    insights = [{"id": k, "text_he": ins[k]} for k in order if ins.get(k)]

    summary = (f"בעלות על דירה ושכירות בישראל לפי הלמ\"ס, {y0}-{y1}: {fmt.int_he(tot1)} דירות למגורים, "
               f"{_p(p1)} מהן בשכירות ב-{y1} (לעומת {_p(p0)} ב-{y0}). פילוח לפי מחוז, גיל, יישוב "
               f"ודיור ציבורי.")
    desc = (f"כמה דירות בישראל בבעלות וכמה בשכירות: {_p(p1)} מהדירות מושכרות ({y1}), לעומת {_p(p0)} "
            f"ב-{y0}. אחוז השכירות בכל יישוב, לפי גיל ומחוז.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{y0}/{y1}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "בעלות על דירה ושכירות בישראל | נתוני הלמ\"ס",
                "description": desc,
                "name": "בעלות על דירה בישראל",
                "alternate_names": ["אחוז הדירות בשכירות בישראל", "שיעור בעלות על דירה",
                                    "דירות בשכירות לפי יישוב", "בעלות על דירות - הלמ\"ס"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "callouts": callouts,
        "insights": insights,
        "release": {
            "title": rel["TITLE"],
            "date": rel["RELEASE_DATE"],
            "headline": (rel.get("HEADLINE") or "").strip(),
            "url": rel["PAGE_URL"],
            "pdf": rel.get("REPORT_PDF_URL") or "",
        },
    }
