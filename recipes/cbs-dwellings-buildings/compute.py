"""דירות ומבנים בישראל: CBS's yearly dwellings-and-buildings press release.

The release is built on the dwellings and buildings register (fed once a
year by the local authorities' property-tax billing systems). The newest
edition already carries a 2012-onward series per locality, so one edition
is read (history_releases 1).

CBS renumbers the tables between editions (the 2024 edition had six chart
tables, the 2025 one put the per-locality series in t1 and the charts in
t5-t9, the 2026 one in t6-t10), so every table resource is read and each
sheet is recognised by its header text, never by its stem. A subject whose
sheet is gone drops its section; a recognised sheet whose labels are gone
raises.

Sheets read:
  loc       dwellings per locality, one column per year (+ national row)
  sizes     buildings per locality by dwellings in the building (counts)
  districts population and dwellings per district (shares)
  ratio     population per dwelling in localities of 50,000+
  regional  dwellings per locality inside each regional council
Sheets left to the downloads (the same figures as above, or too granular):
the yearly-change sheet, the statistical-area table, the big-city percent
table and the chart extracts of the size table.
"""
import re
from itertools import pairwise

from govlib import cbs, fmt

YEAR = re.compile(r"(?:19|20)\d\d")
BUCKET = re.compile(r"^(\d+)\s*-\s*(\d+)$")
OPEN_BUCKET = re.compile(r"^(\d+)\s*\+$")
CODE = re.compile(r"^\d+$")
HEB = re.compile(r"[א-ת]")
TOP_N = 15
GROWTH_MIN = 5000  # dwellings in the first year, for the growth ranking
MIN_SECTIONS = 3


# ── reading ──────────────────────────────────────────────────────────────


def _rel_key(no):
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d{4})\s*", str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _sheets(frames):
    """[(input name, sheet no, rows)] of the newest edition across every
    table input, rows as lists of cleaned cells (index j = column C(j+1))."""
    tables = {k: v for k, v in frames.items() if k != "releases" and not v.empty}
    if not tables:
        raise ValueError("no table input has rows")
    best = None
    for df in tables.values():
        for d, n in df[["RELEASE_DATE", "RELEASE_NO"]].drop_duplicates().itertuples(index=False):
            k = (str(d), _rel_key(n), str(n))
            best = k if best is None or k > best else best
    out = []
    for name in sorted(tables, key=lambda s: (int(re.sub(r"\D", "", s) or 0), s)):
        df = tables[name]
        df = df[(df["RELEASE_DATE"] == best[0]) & (df["RELEASE_NO"] == best[2])]
        if df.empty:
            continue
        cols = sorted((c for c in df.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))
        for sheet, g in sorted(df.groupby("SHEET_NO"), key=lambda t: str(t[0])):
            g = g.sort_values("ROW", kind="stable")
            rows = [[cbs.clean(v) for v in r] for r in g[cols].itertuples(index=False)]
            out.append((name, str(sheet), rows))
    return out


def _find(rows, labels, contains=False, limit=None):
    """First row index holding every label (exact or substring), or None."""
    stop = len(rows) if limit is None else min(len(rows), limit)
    for i in range(stop):
        r = rows[i]
        if all(any((lab in c) if contains else (c == lab) for c in r) for lab in labels):
            return i
    return None


def _col(row, label, contains=False):
    for j, c in enumerate(row):
        if (label in c) if contains else (c == label):
            return j
    raise ValueError(f"header label {label!r} not found")


def _note_row(rows, stop):
    """CBS's '*הערה: …' line above a table (the '*' is stripped)."""
    for r in rows[:stop]:
        cells = [c for c in r if c]
        if len(cells) == 1 and cells[0].startswith("הערה"):
            return cells[0].split(":", 1)[-1].strip()
    return None


def _city(name):
    """CBS writes "תל אביב -יפו" in one table and "תל אביב-יפו" in another."""
    return re.sub(r"\s*-\s*", "-", " ".join(name.split()))


def parse_loc(rows):
    hi = _find(rows, ["שם יישוב"], limit=12)
    if hi is None:
        return None
    best, yr = -1, None
    for i in range(hi, min(hi + 3, len(rows))):
        n = sum(1 for c in rows[i] if re.fullmatch(r"(?:19|20)\d\d", c))
        if n > best:
            best, yr = n, i
    if best < 5:
        return None  # the one-year change sheet
    name_c = _col(rows[hi], "שם יישוב")
    code_c = next((j for j, c in enumerate(rows[hi]) if c == "סמל יישוב"), None)
    years = {j: int(c) for j, c in enumerate(rows[yr]) if re.fullmatch(r"(?:19|20)\d\d", c)}
    note_c = None
    for i in range(hi, yr + 1):
        for j, c in enumerate(rows[i]):
            if c == "הערות":
                note_c = j
    national, locs = None, []
    for r in rows[yr + 1:]:
        name = cbs.cell(r, name_c)
        vals = {y: cbs.val(r, j) for j, y in years.items()}
        vals = {y: v for y, v in vals.items() if v is not None}
        if not name or not vals:
            continue
        if re.match(r"^כלל[\s\-]?ארצי", name):
            national = vals
        elif "סך הכל" in name or not HEB.search(name):
            continue
        elif code_c is None or CODE.match(cbs.cell(r, code_c)):
            locs.append({"name": _city(name), "vals": vals,
                         "note": cbs.cell(r, note_c) if note_c is not None else ""})
    return {"years": sorted(years.values()), "national": national, "locs": locs,
            "note": _note_row(rows, hi)}


def _bucket(label):
    m = BUCKET.match(label)
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        return (a, f"{a}-{b}")
    m = OPEN_BUCKET.match(label)
    if m:
        return (int(m.group(1)), f"{m.group(1)}+")
    return None


def parse_sizes(rows):
    hi = _find(rows, ["מספר מבנים לפי גודל מבנה"], contains=True, limit=12)
    if hi is None:
        return None
    if hi + 1 >= len(rows):
        raise ValueError("sizes: bucket header row missing")
    start = _col(rows[hi], "מספר מבנים לפי גודל מבנה", contains=True)
    sub = rows[hi + 1]
    buckets = []
    j = start
    while j < len(sub) and _bucket(sub[j]):
        buckets.append((j, _bucket(sub[j])))
        j += 1
    if len(buckets) < 3:
        raise ValueError("sizes: building-size buckets not found")
    name_c, code_c = _col(rows[hi], "שם יישוב"), _col(rows[hi], "סמל יישוב")
    dw_c = _col(rows[hi], "סך הכל דירות")
    buckets.sort(key=lambda t: t[1][0])
    locs = []
    for r in rows[hi + 2:]:
        if not CODE.match(cbs.cell(r, code_c)) or not cbs.cell(r, name_c):
            continue
        counts = [cbs.val(r, j) or 0.0 for j, _ in buckets]
        dw = cbs.val(r, dw_c)
        if sum(counts) <= 0 or dw is None:
            continue
        locs.append({"name": _city(cbs.cell(r, name_c)), "counts": counts, "dw": dw})
    return {"labels": [b[1][1] for b in buckets], "locs": locs}


def parse_districts(rows):
    hi = _find(rows, ["אחוז מסך הדירות"], contains=True, limit=12)
    if hi is None:
        return None
    h = rows[hi]
    pop_s = _col(h, "אחוז מסך האוכלוסייה", contains=True)
    dw_s = _col(h, "אחוז מסך הדירות", contains=True)
    pop_c = next((j for j, c in enumerate(h) if "אוכלוסייה" in c and j != pop_s), None)
    dw_c = _col(h, "מספר דירות", contains=True)
    if pop_c is None:
        raise ValueError("districts: population column not found")
    out = []
    for r in rows[hi + 1:]:
        lab = cbs.cell(r, 0)
        if not lab.startswith(("מחוז", "אזור")):
            continue
        vals = [cbs.val(r, j) for j in (pop_c, pop_s, dw_c, dw_s)]
        if None in vals:
            continue
        out.append({"name": lab, "pop": vals[0], "pop_s": vals[1], "dw": vals[2], "dw_s": vals[3]})
    # The population column can be older than the dwellings ("סוף 2023").
    m = re.search(r"(?:(?:סוף|אמצע)\s+(?:\S+\s+)?)?(?:19|20)\d\d", h[pop_c])
    return {"rows": out, "pop_when": m.group() if m else ""}


def parse_ratio(rows):
    hi = _find(rows, ["יחס אוכלוסייה לדירות"], contains=True, limit=12)
    if hi is None:
        return None
    h = rows[hi]
    name_c = _col(h, "שם יישוב")
    dw_c = _col(h, "מספר דירות", contains=True)
    pop_c = _col(h, "אוכלוסייה", contains=True)
    ratio_c = _col(h, "יחס אוכלוסייה לדירות")
    m = re.search(r"\(([^)]*)\)", h[pop_c])
    pop_when = m.group(1) if m else None
    cities, avg = [], {}
    for r in rows[hi + 1:]:
        name = cbs.cell(r, name_c)
        ratio = cbs.val(r, ratio_c)
        if not name or ratio is None or not HEB.search(name):
            continue
        if name.startswith("ממוצע"):
            avg["national" if "ארצי" in name else "big"] = ratio
            continue
        cities.append({"name": _city(name), "ratio": ratio, "dw": cbs.val(r, dw_c),
                       "pop": cbs.val(r, pop_c)})
    return {"cities": cities, "avg": avg, "pop_when": pop_when}


def parse_regional(rows):
    hi = _find(rows, ["שם מועצה אזורית", "שם יישוב"], limit=14)
    if hi is None:
        return None
    h = rows[hi]
    cname_c = _col(h, "שם מועצה אזורית")
    lcode_c = _col(h, "סמל יישוב")
    years = {}
    for i in (hi, hi + 1):
        if i >= len(rows):
            continue
        for j, c in enumerate(rows[i]):
            m = YEAR.search(c)
            if j > lcode_c and m and ("דירות" in c or re.fullmatch(r"(?:19|20)\d\d", c)):
                years[j] = int(m.group(0))
    if not years:
        raise ValueError("regional: year columns not found")
    councils, cur = {}, None
    hidden = 0
    last = max(years.values())
    for r in rows[hi + 1:]:
        if cbs.cell(r, cname_c):
            cur = re.sub(r"^מועצה אזורית\s+", "", cbs.cell(r, cname_c))
        if cur is None or not CODE.match(cbs.cell(r, lcode_c)):
            continue
        c = councils.setdefault(cur, {"n": 0, "vals": {}})
        c["n"] += 1
        for j, y in years.items():
            v = cbs.val(r, j)
            if v is None:
                hidden += y == last
                continue
            c["vals"][y] = c["vals"].get(y, 0.0) + v
    return {"years": sorted(set(years.values())), "councils": councils, "hidden": hidden}


PARSERS = [("loc", parse_loc), ("sizes", parse_sizes), ("districts", parse_districts),
           ("ratio", parse_ratio), ("regional", parse_regional)]


# ── helpers ──────────────────────────────────────────────────────────────


def _i(v):
    return fmt.int_he(v)


def _date_he(iso):
    y, m, d = (int(x) for x in iso[:10].split("-"))
    return f"{d} ב{fmt.MONTHS_HE[m - 1]} {y}"


def _p1(v):
    """0-100 value to one decimal (a model number, not a string)."""
    return round(float(v), 1)


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    subj, locs = {}, []
    for _name, _sheet, rows in _sheets(frames):
        for key, parse in PARSERS:
            if key in subj:
                continue
            got = parse(rows)
            if got is None:
                continue
            if key == "loc":
                locs.append(got)  # the 2025 edition split it over two sheets
            else:
                subj[key] = got
            break
    if not locs:
        raise ValueError("the per-locality dwellings table was not found in any input")
    with_nat = [lc for lc in locs if lc["national"]]
    if not with_nat:
        raise ValueError("loc: national row 'כלל ארצי' not found")
    subj["loc"] = with_nat[0]

    kpis, charts, tables, flags, ledes, labels, ins = {}, {}, {}, {}, {}, {}, {}

    # ── national trend ──
    loc = subj["loc"]
    nat = loc["national"]
    ys = sorted(nat)
    y1, y0, first = ys[-1], (ys[-2] if len(ys) > 1 else None), ys[0]
    total = nat[y1]
    kpis["total"] = {"value": round(total), "display": _i(total), "tone": "brand"}
    labels["total_kpi"] = f"דירות למגורים בישראל, {y1}"
    added = {y: nat[y] - nat[p] for p, y in pairwise(ys)}
    if y0 is not None:
        chg = total / nat[y0] - 1
        kpis["yoy"] = {"value": round(chg * 100, 2), "display": fmt.signed_pct(chg),
                       "tone": "ok" if chg > 0 else "warn"}
        labels["yoy_kpi"] = f"שינוי במספר הדירות לעומת {y0}"
        kpis["added"] = {"value": round(added[y1]), "display": _i(added[y1]), "tone": "brand"}
        labels["added_kpi"] = f"דירות שנוספו למלאי ב-{y1}"
    if first != y1:
        g = total / nat[first] - 1
        kpis["growth"] = {"value": round(g * 100, 1), "display": fmt.signed_pct(g), "tone": "info"}
        labels["growth_kpi"] = f"גידול במלאי הדירות מאז {first}"
    if len(ys) >= 3:
        flags["trend"] = True
        charts["trend"] = {"x": [str(y) for y in ys], "total": [round(nat[y]) for y in ys],
                           "added": [None] + [round(added[y]) for y in ys[1:]]}
        tables["trend"] = [[str(y), _i(nat[y]), _i(added[y]) if y in added else "–"] for y in ys]
        labels["trend_note"] = f"סך הדירות למגורים בכל היישובים, {first}-{y1}, ומספר הדירות שנוספו בכל שנה"
        prev = [added[y] for y in ys[1:-1]]
        if len(prev) >= 3:
            avg = sum(prev) / len(prev)
            ratio = added[y1] / avg
            word = ("יותר מ" if ratio > 1.05 else "פחות מ" if ratio < 0.95 else "בדומה ל")
            ins["pace"] = (f"ב-{y1} נוספו למלאי {_i(added[y1])} דירות, {word}ממוצע של {_i(avg)} "
                           f"דירות בשנה ב-{ys[1]}-{ys[-2]}. מאז {first} גדל מלאי הדירות "
                           f"ב-{fmt.pct(total / nat[first] - 1)}, מ-{_i(nat[first])} ל-{_i(total)}.")
            ledes["trend"] = ins["pace"]

    # ── localities: largest, growth, lookup table ──
    cur = [lc for lc in loc["locs"] if y1 in lc["vals"]]
    cur.sort(key=lambda lc: (-lc["vals"][y1], lc["name"]))
    if len(cur) >= 5:
        top = cur[:TOP_N]
        flags["top"] = True
        charts["top"] = {"x": [lc["name"] for lc in top], "y": [round(lc["vals"][y1]) for lc in top]}
        tables["top"] = [[lc["name"], _i(lc["vals"][y1]), fmt.pct(lc["vals"][y1] / total)] for lc in top]
        labels["top_note"] = f"{len(top)} היישובים עם מספר הדירות הגדול ביותר, {y1}"
        lead = top[0]
        top5 = sum(lc["vals"][y1] for lc in cur[:5])
        ins["concentration"] = (f"היישוב עם מלאי הדירות הגדול ביותר הוא {lead['name']}: "
                                f"{_i(lead['vals'][y1])} דירות, {fmt.pct(lead['vals'][y1] / total)} "
                                f"מכלל הדירות בישראל. בחמשת היישובים הגדולים יחד יש "
                                f"{fmt.pct(top5 / total)} מהדירות.")
        ledes["top"] = ins["concentration"]
        flags["lookup"] = True
        prev_y = y0
        tables["lookup"] = []
        for lc in sorted(cur, key=lambda lc: lc["name"]):
            v = lc["vals"][y1]
            p = lc["vals"].get(prev_y) if prev_y else None
            ch = fmt.signed_pct(v / p - 1) if p else "–"
            tables["lookup"].append([lc["name"], _i(v), _i(p) if p else "–", ch])
        labels["lookup_cols"] = ["יישוב", f"דירות {y1}", f"דירות {prev_y}" if prev_y else "שנה קודמת",
                                 "שינוי"]
        labels["lookup_note"] = (f"מספר הדירות למגורים ב-{len(cur)} העיריות והמועצות המקומיות, "
                                 f"לפי שם היישוב")

    grow = [lc for lc in cur if not lc["note"] and lc["vals"].get(first, 0) >= GROWTH_MIN]
    excluded = sum(1 for lc in cur if lc["note"] and lc["vals"].get(first, 0) >= GROWTH_MIN)
    if first != y1 and len(grow) >= 5:
        for lc in grow:
            lc["g"] = lc["vals"][y1] / lc["vals"][first] - 1
        grow.sort(key=lambda lc: (-lc["g"], lc["name"]))
        gt = grow[:TOP_N]
        flags["growth"] = True
        charts["growth"] = {"x": [lc["name"] for lc in gt], "y": [round(lc["g"] * 100, 1) for lc in gt],
                            "national": round((total / nat[first] - 1) * 100, 1)}
        tables["growth"] = [[lc["name"], _i(lc["vals"][first]), _i(lc["vals"][y1]), fmt.pct(lc["g"])]
                            for lc in gt]
        labels["growth_cols"] = ["יישוב", f"דירות {first}", f"דירות {y1}", "גידול"]
        ex = (f" לא נכללו {excluded} יישובים שהלמ\"ס ציינה בהם שינוי בהגדרות, בספק הנתונים או "
              f"תהליך מיוחד.") if excluded else ""
        labels["growth_note"] = (f"אחוז הגידול במספר הדירות בין {first} ל-{y1}, ביישובים שהיו בהם "
                                 f"לפחות {_i(GROWTH_MIN)} דירות ב-{first}.{ex}")
        a = gt[0]
        ins["growth"] = (f"מבין היישובים שהיו בהם לפחות {_i(GROWTH_MIN)} דירות ב-{first}, מלאי הדירות "
                         f"גדל הכי מהר ב{a['name']}: מ-{_i(a['vals'][first])} ל-{_i(a['vals'][y1])} "
                         f"(גידול של {fmt.pct(a['g'])}, לעומת {fmt.pct(total / nat[first] - 1)} בכלל הארץ).")
        ledes["growth"] = ins["growth"]
    labels["cbs_note"] = loc["note"] or ""

    # ── districts ──
    dist = subj.get("districts")
    if dist and len(dist["rows"]) >= 3:
        rows = sorted(dist["rows"], key=lambda r: (-r["dw"], r["name"]))
        flags["districts"] = True
        charts["districts"] = {"x": [r["name"] for r in rows], "pop": [_p1(r["pop_s"]) for r in rows],
                               "dw": [_p1(r["dw_s"]) for r in rows]}
        tables["districts"] = [[r["name"], fmt.pct_of(r["pop_s"]), _i(r["dw"] * 1000), fmt.pct_of(r["dw_s"]),
                                fmt.num_he(r["pop"] / r["dw"], 2)] for r in rows]
        hi_ = max(rows, key=lambda r: (r["dw_s"] - r["pop_s"], r["name"]))
        lo_ = min(rows, key=lambda r: (r["dw_s"] - r["pop_s"], r["name"]))
        w = dist.get("pop_when") or ""
        pw = f" (אוכלוסייה ב{'-' if w[:1].isdigit() else ''}{w})" if w else ""
        if hi_["dw_s"] - hi_["pop_s"] >= 1 and lo_["pop_s"] - lo_["dw_s"] >= 1:
            ins["districts"] = (f"ב{hi_['name']} נמצאות {fmt.pct_of(hi_['dw_s'])} מהדירות אך רק "
                                f"{fmt.pct_of(hi_['pop_s'])} מהאוכלוסייה, וב{lo_['name']} להפך: "
                                f"{fmt.pct_of(lo_['dw_s'])} מהדירות לעומת {fmt.pct_of(lo_['pop_s'])} "
                                f"מהאוכלוסייה{pw}. כך יוצא שבממוצע מתגוררים "
                                f"{fmt.num_he(hi_['pop'] / hi_['dw'], 1)} נפשות בדירה ב{hi_['name']} "
                                f"ו-{fmt.num_he(lo_['pop'] / lo_['dw'], 1)} ב{lo_['name']}.")
            ledes["districts"] = ins["districts"]

    # ── persons per dwelling in big localities ──
    rat = subj.get("ratio")
    if rat and len(rat["cities"]) >= 5:
        cs = sorted(rat["cities"], key=lambda c: (-c["ratio"], c["name"]))
        flags["ratio"] = True
        nat_r = rat["avg"].get("national")
        charts["ratio"] = {"x": [c["name"] for c in cs], "y": [round(c["ratio"], 2) for c in cs],
                           "national": round(nat_r, 2) if nat_r else None}
        tables["ratio"] = [[c["name"], _i(c["dw"]) if c["dw"] else "–", _i(c["pop"]) if c["pop"] else "–",
                            fmt.num_he(c["ratio"], 2)] for c in cs]
        when = f" ({rat['pop_when']})" if rat["pop_when"] else ""
        labels["ratio_cols"] = ["יישוב", "דירות", f"אוכלוסייה{when}", "נפשות לדירה"]
        labels["ratio_note"] = (f"מספר התושבים לכל דירה למגורים ב-{len(cs)} היישובים המונים "
                                f"50 אלף תושבים ויותר")
        if nat_r:
            kpis["ppd"] = {"value": round(nat_r, 2), "display": fmt.num_he(nat_r, 2), "tone": "info"}
            labels["ppd_kpi"] = "נפשות לדירה בממוצע ארצי"
        a, b = cs[0], cs[-1]
        if a["ratio"] >= 1.5 * b["ratio"]:
            tail = f", לעומת {fmt.num_he(nat_r, 1)} בממוצע הארצי" if nat_r else ""
            ins["ratio"] = (f"היחס בין התושבים לדירות גבוה במיוחד ב{a['name']}: "
                            f"{fmt.num_he(a['ratio'], 1)} נפשות לדירה, פי {fmt.num_he(a['ratio'] / b['ratio'], 1)} "
                            f"מ{b['name']} ({fmt.num_he(b['ratio'], 1)}){tail}.")
            ledes["ratio"] = ins["ratio"]

    # ── building size ──
    sz = subj.get("sizes")
    if sz and len(sz["locs"]) >= 5:
        lab = sz["labels"]
        tot = [sum(lc["counts"][k] for lc in sz["locs"]) for k in range(len(lab))]
        nb = sum(tot)
        flags["sizes"] = True
        charts["sizes"] = {"x": lab, "y": [round(v) for v in tot],
                           "share": [round(v / nb * 100, 1) for v in tot]}
        tables["sizes"] = [[f"{lb} דירות", _i(v), fmt.pct(v / nb)] for lb, v in zip(lab, tot)]
        labels["sizes_note"] = (f"מבנים למגורים לפי מספר הדירות במבנה, ב-{len(sz['locs'])} יישובים "
                                f"שבהם רוב הדירות משויכות למבנה, {y1}")
        kpis["small"] = {"value": round(tot[0] / nb * 100, 1), "display": fmt.pct(tot[0] / nb), "tone": "brand"}
        labels["small_kpi"] = f"מהמבנים הם בני {lab[0]} דירות"
        ins["sizes"] = (f"{fmt.pct(tot[0] / nb)} מהמבנים למגורים ({_i(tot[0])} מתוך {_i(nb)}) הם בתים "
                        f"של {lab[0]} דירות, ורק {fmt.pct(tot[-1] / nb)} הם בניינים של {lab[-1]} דירות.")
        ledes["sizes"] = ins["sizes"]
        big = sorted(sz["locs"], key=lambda lc: (-lc["dw"], lc["name"]))[:TOP_N]
        flags["size_cities"] = True
        series = []
        for k, lb in enumerate(lab):
            series.append({"name": f"{lb} דירות",
                           "data": [round(lc["counts"][k] / sum(lc["counts"]) * 100, 1) for lc in big]})
        charts["size_cities"] = {"x": [lc["name"] for lc in big], "series": series}
        tables["size_cities"] = [[lc["name"], _i(sum(lc["counts"]))]
                                 + [fmt.pct(c / sum(lc["counts"])) for c in lc["counts"]] for lc in big]
        labels["size_cols"] = ["יישוב", "מבנים"] + [f"{lb}" for lb in lab]
        labels["size_cities_note"] = (f"התפלגות המבנים לפי מספר הדירות במבנה, ב-{len(big)} היישובים "
                                      f"הגדולים בלוח (לפי מספר הדירות)")
        tall = max(big, key=lambda lc: (lc["counts"][-1] / sum(lc["counts"]), lc["name"]))
        low = min(big, key=lambda lc: (lc["counts"][0] / sum(lc["counts"]), lc["name"]))
        hi_small = max(big, key=lambda lc: (lc["counts"][0] / sum(lc["counts"]), lc["name"]))
        ins["size_cities"] = (f"בין היישובים הגדולים, ב{hi_small['name']} "
                              f"{fmt.pct(hi_small['counts'][0] / sum(hi_small['counts']))} מהמבנים הם בני "
                              f"{lab[0]} דירות, וב{low['name']} רק "
                              f"{fmt.pct(low['counts'][0] / sum(low['counts']))}. שיעור הבניינים של {lab[-1]} "
                              f"דירות הגבוה ביותר הוא ב{tall['name']}: "
                              f"{fmt.pct(tall['counts'][-1] / sum(tall['counts']))}.")
        ledes["size_cities"] = ins["size_cities"]

    # ── regional councils ──
    reg = subj.get("regional")
    if reg:
        ly = max(reg["years"])
        cs = [(n, c) for n, c in reg["councils"].items() if c["vals"].get(ly)]
        cs.sort(key=lambda t: (-t[1]["vals"][ly], t[0]))
        if len(cs) >= 5:
            top = cs[:TOP_N]
            fy = min(reg["years"])
            flags["regional"] = True
            charts["regional"] = {"x": [n for n, _ in top], "y": [round(c["vals"][ly]) for _, c in top]}
            tables["regional"] = [[n, str(c["n"]), _i(c["vals"][ly]),
                                   _i(c["vals"][fy]) if c["vals"].get(fy) else "–"] for n, c in top]
            labels["regional_cols"] = ["מועצה אזורית", "יישובים", f"דירות {ly}", f"דירות {fy}"]
            hid = (f" {_i(reg['hidden'])} יישובים קטנים שהנתונים שלהם אינם מתפרסמים לא נספרו."
                   if reg["hidden"] else "")
            labels["regional_note"] = (f"סכום הדירות ביישובי כל מועצה אזורית ב-{ly}. מוצגות {len(top)} "
                                       f"המועצות הגדולות מתוך {len(cs)}.{hid}")
            n0, c0 = top[0]
            ins["regional"] = (f"מבין {len(cs)} המועצות האזוריות, במועצה האזורית {n0} מספר הדירות הגדול "
                               f"ביותר: {_i(c0['vals'][ly])} דירות ב-{c0['n']} יישובים ({ly}).")
            ledes["regional"] = ins["regional"]

    sections = sum(1 for k in ("trend", "top", "growth", "districts", "ratio", "sizes", "regional")
                   if flags.get(k))
    if sections < MIN_SECTIONS:
        raise ValueError(f"only {sections} sections recognised")

    order = ["pace", "concentration", "growth", "districts", "ratio", "sizes", "size_cities", "regional"]
    insights = [{"id": k, "text_he": ins[k]} for k in order if ins.get(k)]

    release = {"title": str(rel["TITLE"]), "date": _date_he(str(rel["RELEASE_DATE"])),
               "headline": str(rel.get("HEADLINE") or ""), "url": str(rel["PAGE_URL"]),
               "pdf": str(rel.get("REPORT_PDF_URL") or "")}

    labels["lede"] = (f"מלאי הדירות למגורים בישראל לפי מרשם הדירות והמבנים של הלשכה המרכזית "
                      f"לסטטיסטיקה (הלמ\"ס), שנבנה מנתוני הארנונה של הרשויות המקומיות. ב-{y1} נרשמו "
                      f"{_i(total)} דירות למגורים. בעמוד: מספר הדירות בכל יישוב מאז {first}, "
                      f"היישובים שבהם המלאי גדל הכי מהר, היחס בין תושבים לדירות, גודל הבניינים "
                      f"והדירות במועצות האזוריות. זהו מלאי הדירות הקיים, לא בנייה חדשה או עסקאות.")
    summary = (f"מלאי הדירות למגורים בישראל לפי הלמ\"ס: {_i(total)} דירות ב-{y1}, "
               f"מספר הדירות בכל יישוב מאז {first}, נפשות לדירה וגודל הבניינים.")
    desc = (f"כמה דירות יש בכל יישוב בישראל? {_i(total)} דירות למגורים ב-{y1} "
            f"(גידול של {fmt.pct(total / nat[first] - 1)} מאז {first}), לפי יישוב, מחוז וגודל בניין.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "temporal_coverage": f"{first}/{y1}",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "דירות ומבנים בישראל: מספר הדירות בכל יישוב",
            "description": desc,
            "name": "דירות ומבנים בישראל",
            "alternate_names": ["מלאי הדירות בישראל", "מספר הדירות לפי יישוב",
                                "מרשם דירות ומבנים", "כמה דירות יש בישראל"],
        },
    }
    return {"agent_data": agent_data, "kpis": kpis, "charts": charts, "tables": tables,
            "insights": insights, "flags": flags, "ledes": ledes, "labels": labels,
            "release": release}
