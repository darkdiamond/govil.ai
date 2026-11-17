"""תושבים זרים בישראל: CBS's yearly release on foreign residents at year end.

The release is a set of chart-data sheets ("תרשים N - ..."). Their numbers
and even their subjects move between editions (the 2023 edition charted
Jewish students and tourists without a valid permit; the 2024 edition
charted workers by sex, industry and locality). Each edition holds one year,
so source.json keeps the last 2 editions (`history_releases: 2`), and every
table input (t1..t7, the last three spare, all optional) is split by
edition and matched by its TITLE text, never by its stem:

  cit       ... לפי ארץ אזרחות             workers by citizenship
  ind       ... לפי ענף העסקה              workers by industry (thousands)
  loc       ... ענף העסקה ויישובים עיקריים  workers by locality x industry
  sex       ... לפי מין ומדינות עיקריות     men/women share per citizenship
  ov_year   תיירים ללא רישיון ... שנת הכניסה  tourists without a permit by entry year
  ov_age    תיירים ללא רישיון ... גיל ומין   the same by age and sex
  students  ... סטודנטים ...                students and family by age and sex

For each subject the newest edition that has it wins; an older edition only
feeds the year-on-year comparison (cit, ind) or a subject the newest edition
dropped (shown with its own year). A title found whose header labels are gone
raises. Worker counts are kept in thousands (the 2024 sheets are in
thousands, the 2023 citizenship sheet in persons: a total under 2,000 means
thousands, checked against a contradicting unit cell and against the other
subject's total for the same year).
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*-\s*")
REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
YEAR_IN = re.compile(r"(?:בשנת|בסוף שנת)\s*((?:19|20)\d\d)")
HEB = re.compile("[א-ת]")
AGE = re.compile(r"^(\d+)\s*-+\s*(\d+)$|^(\d+)\s*\+$")
TOTALS = ("סך הכל", "סה\"כ", "סה''כ", "Total", "סהכ")
OTHER = ("שאר ארצות", "אחרים", "אחר", "שאר")
FIX = {"חלקאות": "חקלאות", "שאר": "אחר"}
SPARE = re.compile(r"t\d+")
MAX_INSIGHTS = 8


# ── locating tables ──────────────────────────────────────────────────────


def _rkey(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _editions(df):
    """[(release key, RELEASE_NO, rows)] of one table input, rows as cleaned
    cells in sheet/row order."""
    if df.empty:
        return []
    cols = sorted((c for c in df.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))
    out = []
    for no in sorted(df["RELEASE_NO"].unique(), key=lambda n: (_rkey(n), str(n))):
        part = df[df["RELEASE_NO"] == no].sort_values(["SHEET_NO", "ROW"], kind="stable")
        rows = [[cbs.clean(v) for v in r] for r in part[cols].itertuples(index=False)]
        out.append((_rkey(no), str(no), rows))
    return out


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return TITLE.sub("", c)
    return ""


def _kind(t):
    if "סטודנטים" in t:
        return "students"
    if "ללא רישיון" in t:
        if "שנת הכניסה" in t:
            return "ov_year"
        if "גיל" in t:
            return "ov_age"
        return None
    if "ארץ אזרחות" in t:
        return "cit"
    if "ענף העסקה" in t:
        return "loc" if "יישוב" in t else "ind"
    if "לפי מין" in t and "מדינות" in t:
        return "sex"
    return None


def _ref_year(title, rel_no, rel_titles):
    m = YEAR_IN.search(title)
    if m:
        return int(m.group(1))
    m = YEAR_IN.search(rel_titles.get(rel_no, ""))
    if m:
        return int(m.group(1))
    return _rkey(rel_no)[0] - 1


def _tables(frames, rel_titles):
    """{kind: [(release key, year, title, rows), ...] newest first}."""
    found = {}
    names = sorted((n for n in frames if SPARE.fullmatch(n)), key=lambda n: int(n[1:]))
    for n in names:
        for key, no, rows in _editions(frames[n]):
            t = _title(rows)
            k = _kind(t)
            if not k:
                continue
            found.setdefault(k, {})
            if key not in found[k]:
                found[k][key] = (key, _ref_year(t, no, rel_titles), t, rows)
    return {k: sorted(v.values(), key=lambda e: e[0], reverse=True) for k, v in found.items()}


# ── readers ──────────────────────────────────────────────────────────────


def _is_total(label):
    return label in TOTALS or label.replace(" ", "") in ("סה\"כ", "סךהכל")


def _label(r):
    return FIX.get(cbs.cell(r, 0), cbs.cell(r, 0))


def _single(rows, name):
    """A label/value chart: [(label, value)], total. Thousands kept as
    thousands; a sheet in persons (total >= 2,000) is divided by 1,000."""
    items, total = [], None
    for r in rows:
        lab = _label(r)
        v = cbs.val(r, 1)
        if not lab or v is None or not HEB.search(lab) or TITLE.match(lab):
            continue
        if _is_total(lab):
            total = v if total is None else total
            continue
        items.append((lab, v))
    if not items:
        return [], None
    if total is None:
        total = sum(v for _, v in items)
    # The unit is not reliably labelled (the 2023 citizenship sheet in persons
    # has no unit cell; the 2023 tourists sheet says "באלפים" over persons), so
    # magnitude decides: some 100k-200k workers read as ~100-200 in thousands
    # or ~100,000-200,000 in persons, far from the 2,000 cut either way. A unit
    # cell that contradicts the magnitude raises, and `_check_units` compares
    # sheets of the same year.
    marked = any(c in ("אלפים", "באלפים") for r in rows for c in r)
    if total >= 2000:
        if marked:
            raise ValueError(f"{name}: sheet says thousands but its total is {total}")
        items = [(lab, v / 1000) for lab, v in items]
        total = total / 1000
    return items, total


def _check_units(cit, ind):
    """Citizenship and industry totals of one year must agree (both in
    thousands); a unit misread shows up as a 1,000x gap."""
    for y, _items, t in cit:
        for y2, _i2, t2 in ind:
            if y == y2 and t and t2 and abs(t / t2 - 1) > 0.05:
                raise ValueError(f"{y}: citizenship total {t} vs industry total {t2} (thousands)")


def _header(rows, labels, name):
    """(row index, {label: column}) of the first row holding every label."""
    for i, r in enumerate(rows):
        cols = {}
        for lab in labels:
            for j, c in enumerate(r):
                if c == lab:
                    cols[lab] = j
                    break
        if len(cols) == len(labels):
            return i, cols
    raise ValueError(f"{name}: header {labels!r} not found")


def _sex(rows):
    """[(country, men share, women share)] on 0-1, the total row first."""
    h, cols = _header(rows, ("גברים", "נשים"), "sex")
    out = []
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        m, w = cbs.val(r, cols["גברים"]), cbs.val(r, cols["נשים"])
        if not lab or m is None or w is None:
            continue
        s = m + w
        if s <= 0:
            continue
        out.append(("סך הכל" if _is_total(lab) else lab, m / s, w / s))
    return out


def _loc(rows):
    """(industries, [(locality, [values...])], totals) in thousands."""
    h = None
    for i, r in enumerate(rows):
        if "סיעוד" in r and "בנייה" in r:
            h = i
            break
    if h is None:
        raise ValueError("loc: industry header (סיעוד, בנייה) not found")
    head = rows[h]
    ind = [(j, FIX.get(c, c)) for j, c in enumerate(head) if j > 0 and c and HEB.search(c)]
    out, totals = [], None
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        vals = [cbs.val(r, j) for j, _ in ind]
        if not lab or all(v is None for v in vals):
            continue
        vals = [v or 0.0 for v in vals]
        if _is_total(lab):
            totals = vals
            continue
        out.append((lab, vals))
    return [n for _, n in ind], out, totals


def _age_key(lab):
    m = AGE.match(lab)
    if not m:
        return None
    if m.group(3):
        return (int(m.group(3)), f"{int(m.group(3))}+")
    return (int(m.group(1)), f"{int(m.group(1))}-{int(m.group(2))}")


def _pyramid(rows, name):
    """[(age label, men, women)] ascending by age, persons."""
    for i, r in enumerate(rows):
        jm = next((j for j, c in enumerate(r) if c in ("זכרים", "גברים")), None)
        jw = next((j for j, c in enumerate(r) if c in ("נקבות", "נשים")), None)
        if jm is not None and jw is not None:
            break
    else:
        raise ValueError(f"{name}: sex header (זכרים/נקבות) not found")
    out = []
    for r in rows[i + 1:]:
        k = _age_key(cbs.cell(r, 0))
        m, w = cbs.val(r, jm), cbs.val(r, jw)
        if k is None or m is None or w is None:
            continue
        out.append((k[0], k[1], abs(m), abs(w)))
    out.sort()
    return [(lab, m, w) for _, lab, m, w in out]


def _by_year(rows):
    """[(entry year, persons)] ascending."""
    out = {}
    for r in rows:
        y = cbs.cell(r, 0)
        v = cbs.val(r, 1)
        if cbs.YEAR.match(y) and v is not None:
            out[int(y)] = v
    tot = sum(out.values())
    if out and tot < 2000:
        out = {y: v * 1000 for y, v in out.items()}
    return sorted(out.items())


# ── formatting ───────────────────────────────────────────────────────────


def _k(v):
    """Thousands with one decimal: 35.561 → '35.6'."""
    return fmt.num_he(v, 1)


def _r(v, d=3):
    return None if v is None else round(v, d)


def _chg(new, old):
    return None if not old else new / old - 1


def _thousand(v):
    return f"{_k(v)} אלף"


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    rels = frames["releases"]
    rel_titles = {str(n): str(t) for n, t in zip(rels["RELEASE_NO"], rels["TITLE"])}
    tabs = _tables(frames, rel_titles)
    if "cit" not in tabs and "ind" not in tabs:
        raise ValueError("neither the citizenship nor the industry chart was found in any edition")

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    ins = {}

    # ── workers by citizenship ───────────────────────────────────────────
    cit = []
    for _key, year, _t, rows in tabs.get("cit", []):
        items, total = _single(rows, "cit")
        if items:
            cit.append((year, items, total))
    ind = []
    for _key, year, _t, rows in tabs.get("ind", []):
        items, total = _single(rows, "ind")
        if items:
            ind.append((year, items, total))

    _check_units(cit, ind)
    head = cit[0] if cit else ind[0]
    wyear, wtotal = head[0], head[2]
    kpis["workers"] = {"value": round(wtotal * 1000), "display": _k(wtotal), "tone": "brand"}
    labels["workers_kpi"] = f"תושבים זרים עם רישיון עבודה, {wyear} (אלפים)"

    # Year-on-year total from the same subject in two editions.
    series = cit if len(cit) >= 2 and cit[1][0] < cit[0][0] else ind
    prev_total = None
    if len(series) >= 2 and series[1][0] < series[0][0]:
        y1, t1 = series[0][0], series[0][2]
        y0, t0 = series[1][0], series[1][2]
        c = _chg(t1, t0)
        prev_total = (y0, t0)
        if c is not None:
            kpis["change"] = {"value": round(c * 100, 1),
                              "display": fmt.signed_pct(c),
                              "tone": "info"}
            labels["change_kpi"] = f"שינוי במספר העובדים מחו\"ל, {y0} עד {y1}"
            word = "עלה" if c > 0.02 else "ירד" if c < -0.02 else "נותר כמעט ללא שינוי"
            if abs(c) > 0.02:
                ins["growth"] = (f"מספר התושבים הזרים המחזיקים ברישיון עבודה {word} מ-{_thousand(t0)} "
                                 f"ב-{y0} ל-{_thousand(t1)} ב-{y1} ({fmt.signed_pct(c)}).")
            else:
                ins["growth"] = (f"מספר התושבים הזרים המחזיקים ברישיון עבודה {word}: "
                                 f"{_thousand(t0)} ב-{y0} ו-{_thousand(t1)} ב-{y1}.")

    flags["cit"] = bool(cit)
    if cit:
        year, items, total = cit[0]
        prev = cit[1] if len(cit) >= 2 and cit[1][0] < year else None
        pmap = dict(prev[1]) if prev else {}
        named = [(n, v) for n, v in items if n not in OTHER]
        other = [(n, v) for n, v in items if n in OTHER]
        named.sort(key=lambda kv: (-kv[1], kv[0]))
        order = named + other
        charts["cit"] = {"names": [n for n, _ in order],
                         "cur": [_r(v) for _, v in order],
                         "prev": [_r(pmap.get(n)) for n, _ in order] if prev else None,
                         "year": str(year), "prev_year": str(prev[0]) if prev else None}
        cols = ["ארץ אזרחות", f"{year} (אלפים)", "חלק מהסך"]
        if prev:
            cols.insert(2, f"{prev[0]} (אלפים)")
        rows = []
        for n, v in order:
            r = [n, _k(v)]
            if prev:
                r.append(_k(pmap[n]) if n in pmap else "–")
            r.append(fmt.pct(v / total) if total else "–")
            rows.append(r)
        rows.append(["סך הכל", _k(total)] + ([_k(prev[2])] if prev else []) + ["100.0%"])
        tables["cit"] = rows
        labels["cit_cols"] = cols
        labels["cit_note"] = (f"תושבים זרים המחזיקים ברישיון עבודה ב-{year}, לפי ארץ האזרחות, באלפים"
                              + (f", לצד {prev[0]}." if prev else "."))
        labels["cit_aria"] = f"עובדים מחו\"ל לפי ארץ אזרחות, {year}"
        if named:
            top, tv = named[0]
            kpis["top"] = {"value": round(tv / total * 100, 1), "display": fmt.pct(tv / total),
                           "tone": "brand"}
            labels["top_kpi"] = f"חלק העובדים מ{top}, {year}"
            top3 = named[:3]
            if len(top3) == 3 and total:
                s3 = sum(v for _, v in top3)
                ins["countries"] = (f"ב-{year} הגיעו {fmt.pct(s3 / total)} מהעובדים משלוש ארצות: "
                                    f"{fmt.join_he([n for n, _ in top3])}. בראש הרשימה {top} "
                                    f"עם {_thousand(tv)} ({fmt.pct(tv / total)}).")
        if prev:
            moves = [(n, v - pmap[n], v, pmap[n]) for n, v in named if n in pmap]
            if moves:
                n, d, v, p = max(moves, key=lambda m: (m[1], m[0]))
                if d > 0 and p > 0:
                    ins["cit_growth"] = (f"הגידול הגדול ביותר בין {prev[0]} ל-{year} נרשם בקרב "
                                         f"העובדים מ{n}: מ-{_thousand(p)} ל-{_thousand(v)} "
                                         f"({fmt.signed_pct(v / p - 1)}).")

    # ── workers by industry ──────────────────────────────────────────────
    flags["ind"] = bool(ind)
    if ind:
        year, items, total = ind[0]
        prev = ind[1] if len(ind) >= 2 and ind[1][0] < year else None
        pmap = dict(prev[1]) if prev else {}
        order = sorted(items, key=lambda kv: (kv[0] in OTHER, -kv[1], kv[0]))
        charts["ind"] = {"names": [n for n, _ in order], "cur": [_r(v) for _, v in order],
                         "prev": [_r(pmap.get(n)) for n, _ in order] if prev else None,
                         "year": str(year), "prev_year": str(prev[0]) if prev else None}
        cols = ["ענף", f"{year} (אלפים)"] + ([f"{prev[0]} (אלפים)"] if prev else []) + ["חלק מהסך"]
        trows = []
        for n, v in order:
            r = [n, _k(v)]
            if prev:
                r.append(_k(pmap[n]) if n in pmap else "–")
            r.append(fmt.pct(v / total) if total else "–")
            trows.append(r)
        tables["ind"] = trows
        labels["ind_cols"] = cols
        labels["ind_note"] = (f"תושבים זרים המחזיקים ברישיון עבודה ב-{year}, לפי ענף ההעסקה, באלפים"
                              + (f", לצד {prev[0]}." if prev else "."))
        labels["ind_aria"] = f"עובדים מחו\"ל לפי ענף העסקה, {year}"
        lead, lv = order[0]
        if total and lv / total >= 0.25:
            ins["ind_lead"] = (f"{lead} הוא הענף הגדול ביותר: {_thousand(lv)} עובדים ב-{year}, "
                               f"{fmt.pct(lv / total)} מכלל המחזיקים ברישיון עבודה.")
        if prev:
            moves = [(n, v / pmap[n] - 1, v, pmap[n]) for n, v in items
                     if n in pmap and pmap[n] >= 1 and n not in OTHER]
            if moves:
                n, c, v, p = max(moves, key=lambda m: (m[1], m[0]))
                if c > 0.1:
                    ins["ind_growth"] = (f"מספר העובדים בענף ה{n} גדל מ-{_thousand(p)} ב-{prev[0]} "
                                         f"ל-{_thousand(v)} ב-{year} ({fmt.signed_pct(c)}), "
                                         f"הגידול היחסי הגדול ביותר מבין הענפים.")

    # ── sex by citizenship ───────────────────────────────────────────────
    sex = None
    if "sex" in tabs:
        _key, year, _t, rows = tabs["sex"][0]
        sx = _sex(rows)
        if sx:
            sex = (year, sx)
    flags["sex"] = bool(sex)
    if sex:
        year, sx = sex
        tot = next((s for s in sx if s[0] == "סך הכל"), None)
        ctry = [s for s in sx if s[0] != "סך הכל"]
        order = ([tot] if tot else []) + ctry
        charts["sex"] = {"names": [s[0] for s in order],
                         "men": [round(s[1] * 100, 1) for s in order],
                         "women": [round(s[2] * 100, 1) for s in order]}
        tables["sex"] = [[s[0], fmt.pct(s[1]), fmt.pct(s[2])] for s in order]
        labels["sex_note"] = (f"חלקם של הגברים ושל הנשים בקרב התושבים הזרים המחזיקים ברישיון "
                              f"עבודה ב-{year}, לפי ארץ האזרחות (ארצות עיקריות).")
        labels["sex_aria"] = f"עובדים מחו\"ל לפי מין וארץ אזרחות, {year}"
        if tot:
            kpis["women"] = {"value": round(tot[2] * 100, 1), "display": fmt.pct(tot[2]),
                             "tone": "brand"}
            labels["women_kpi"] = f"חלק הנשים בקרב העובדים מחו\"ל, {year}"
        # Contrast among the larger countries: the citizenship chart's named
        # countries when there is one, else the first half of the list.
        big = set()
        if cit:
            big = {n for n, v in cit[0][1] if n not in OTHER and cit[0][2] and v / cit[0][2] >= 0.03}
        pool = [s for s in ctry if s[0] in big] if big else ctry[: max(3, len(ctry) // 2)]
        if len(pool) >= 3:
            fw = max(pool, key=lambda s: (s[2], s[0]))
            mm = max(pool, key=lambda s: (s[1], s[0]))
            if fw[2] >= 0.6 and mm[1] >= 0.6 and fw[0] != mm[0]:
                ins["sex"] = (f"הרכב המין שונה מאוד בין הארצות: בקרב העובדים מ{fw[0]} "
                              f"{fmt.pct(fw[2])} נשים, ובקרב העובדים מ{mm[0]} "
                              f"{fmt.pct(mm[1])} גברים ({year}).")

    # ── localities x industry ────────────────────────────────────────────
    loc = None
    if "loc" in tabs:
        _key, year, _t, rows = tabs["loc"][0]
        inds, locs, ltot = _loc(rows)
        if locs:
            loc = (year, inds, locs, ltot)
    flags["loc"] = bool(loc)
    if loc:
        year, inds, locs, ltot = loc
        locs = sorted(((re.sub(r"\s*-\s*", "-", n), v) for n, v in locs),
                      key=lambda kv: (-sum(kv[1]), kv[0]))
        charts["loc"] = {"names": [n for n, _ in locs], "inds": inds,
                         "series": [[_r(v[k]) for _, v in locs] for k in range(len(inds))]}
        tables["loc"] = [[n] + [_k(x) for x in v] + [_k(sum(v))] for n, v in locs]
        labels["loc_cols"] = ["יישוב"] + inds + ["סך הכל"]
        labels["loc_note"] = (f"היישובים שבהם גרים הכי הרבה תושבים זרים המחזיקים ברישיון עבודה "
                              f"ב-{year}, לפי ענף ההעסקה, באלפים.")
        labels["loc_aria"] = f"עובדים מחו\"ל ביישובים עיקריים לפי ענף, {year}"
        n0, v0 = locs[0]
        gt = sum(ltot) if ltot else None
        s0 = f" ({fmt.pct(sum(v0) / gt)} מכלל העובדים)" if gt else ""
        txt = f"מבין היישובים, הכי הרבה עובדים מחו\"ל גרים ב{n0}: {_thousand(sum(v0))} ב-{year}{s0}."
        if "בנייה" in inds:
            kb = inds.index("בנייה")
            cand = [(v[kb] / sum(v), n, v) for n, v in locs[:10] if sum(v) > 0]
            if cand:
                sh, n1, _v1 = max(cand, key=lambda c: (c[0], c[1]))
                if sh >= 0.5:
                    txt += (f" ב{n1} רוב העובדים מחו\"ל מועסקים בבנייה ({fmt.pct(sh)}).")
        ins["loc"] = txt

    # ── tourists without a valid permit ──────────────────────────────────
    ovy = None
    if "ov_year" in tabs:
        _key, year, _t, rows = tabs["ov_year"][0]
        by = _by_year(rows)
        if by:
            ovy = (year, by)
    flags["ov_year"] = bool(ovy)
    if ovy:
        year, by = ovy
        tot = sum(v for _, v in by)
        charts["ov_year"] = {"x": [str(y) for y, _ in by], "y": [round(v) for _, v in by]}
        tables["ov_year"] = [[str(y), fmt.int_he(v), fmt.pct(v / tot)] for y, v in by]
        labels["ov_year_note"] = (f"תיירים שנכנסו לישראל מ-{by[0][0]} ונשארו בה ללא רישיון בתוקף "
                                  f"בסוף {year}, לפי שנת הכניסה.")
        labels["ov_year_aria"] = f"תיירים ללא רישיון בתוקף בסוף {year} לפי שנת כניסה"
        kpis["overstay"] = {"value": round(tot), "display": fmt.int_he(tot), "tone": "brand"}
        labels["overstay_kpi"] = f"תיירים ללא רישיון בתוקף, סוף {year}"
        if len(by) >= 4:
            last2 = by[-2:]
            s2 = sum(v for _, v in last2)
            ins["ov_year"] = (f"בסוף {year} שהו בישראל {fmt.int_he(tot)} תיירים ללא רישיון בתוקף "
                              f"שנכנסו אליה מ-{by[0][0]}. {fmt.pct(s2 / tot)} מהם נכנסו ב-"
                              f"{last2[0][0]} או ב-{last2[1][0]}.")

    ova = None
    if "ov_age" in tabs:
        _key, year, _t, rows = tabs["ov_age"][0]
        p = _pyramid(rows, "ov_age")
        if p:
            ova = (year, p)
    flags["ov_age"] = bool(ova)
    if ova:
        year, p = ova
        charts["ov_age"] = {"ages": [a for a, _, _ in p], "men": [round(m) for _, m, _ in p],
                            "women": [round(w) for _, _, w in p]}
        tables["ov_age"] = [[a, fmt.int_he(m), fmt.int_he(w)] for a, m, w in p]
        labels["ov_age_note"] = f"תיירים ללא רישיון בתוקף בסוף {year}, לפי קבוצת גיל ומין."
        labels["ov_age_aria"] = f"פירמידת גיל של תיירים ללא רישיון בתוקף, {year}"
        tm = sum(m for _, m, _ in p)
        tw = sum(w for _, _, w in p)
        old = sum(m + w for a, m, w in p if int(re.match(r"\d+", a).group()) >= 45)
        if tm + tw:
            ins["ov_age"] = (f"בקרב התיירים ללא רישיון בתוקף בסוף {year}, {fmt.pct(tw / (tm + tw))} "
                             f"נשים, ו-{fmt.pct(old / (tm + tw))} בני 45 ומעלה.")

    stu = None
    if "students" in tabs:
        _key, year, _t, rows = tabs["students"][0]
        p = _pyramid(rows, "students")
        if p:
            stu = (year, p)
    flags["students"] = bool(stu)
    if stu:
        year, p = stu
        charts["students"] = {"ages": [a for a, _, _ in p], "men": [round(m) for _, m, _ in p],
                              "women": [round(w) for _, _, w in p]}
        tables["students"] = [[a, fmt.int_he(m), fmt.int_he(w)] for a, m, w in p]
        tot = sum(m + w for _, m, w in p)
        labels["students_note"] = (f"תושבים זרים שהם סטודנטים יהודים ובני משפחותיהם, לפי קבוצת גיל "
                                   f"ומין ({year}).")
        labels["students_aria"] = f"פירמידת גיל של סטודנטים יהודים זרים ובני משפחותיהם, {year}"
        kpis["students"] = {"value": round(tot), "display": fmt.int_he(tot), "tone": "brand"}
        labels["students_kpi"] = f"סטודנטים יהודים זרים ובני משפחותיהם, {year}"
        kids = sum(m + w for a, m, w in p if int(re.match(r"\d+", a).group()) < 5)
        young = sum(m + w for a, m, w in p if 20 <= int(re.match(r"\d+", a).group()) < 30)
        if tot:
            ins["students"] = (f"בקרב {fmt.int_he(tot)} הסטודנטים היהודים הזרים ובני משפחותיהם "
                               f"({year}), {fmt.pct(young / tot)} בני 20-29 ו-{fmt.pct(kids / tot)} "
                               f"ילדים עד גיל 4.")

    # ── insights, in reading order ───────────────────────────────────────
    order = ("growth", "countries", "ind_lead", "ind_growth", "cit_growth", "sex", "loc",
             "ov_year", "ov_age", "students")
    insights = [{"id": k, "text_he": ins[k]} for k in order if ins.get(k)][:MAX_INSIGHTS]
    shown = {i["id"] for i in insights}
    # Findings past the insight card go under their own chart instead.
    callouts = {k: v for k, v in ins.items() if v and k not in shown}

    # ── text ─────────────────────────────────────────────────────────────
    rel_title = str(rel.get("TITLE") or "")
    lede = (f"לפי הלשכה המרכזית לסטטיסטיקה (הלמ\"ס), ב-{wyear} החזיקו {_thousand(wtotal)} "
            f"תושבים זרים ברישיון עבודה בישראל")
    if prev_total:
        lede += f", לעומת {_thousand(prev_total[1])} ב-{prev_total[0]}"
    lede += ". הנתונים מתוך ההודעה השנתית לתקשורת על התושבים הזרים בישראל"
    parts = []
    if flags["cit"]:
        parts.append("ארץ אזרחות")
    if flags["ind"]:
        parts.append("ענף העסקה")
    if flags["sex"]:
        parts.append("מין")
    if flags["loc"]:
        parts.append("יישוב מגורים")
    lede += (f", לפי {fmt.join_he(parts)}." if parts else ".")
    if flags["ov_year"]:
        lede += " ההודעות כוללות גם נתונים על תיירים שנשארו בישראל ללא רישיון בתוקף."
    labels["lede"] = lede

    all_years = sorted({e[1] for v in tabs.values() for e in v})
    summary = (f"עובדים זרים ותושבים זרים בישראל לפי נתוני הלמ\"ס: {_thousand(wtotal)} מחזיקי "
               f"רישיון עבודה ב-{wyear}")
    if cit and charts["cit"]["names"]:
        summary += f", בראשם עובדים מ{charts['cit']['names'][0]}"
    summary += ". פילוח לפי ארץ, ענף, מין ויישוב."
    desc = (f"כמה עובדים זרים יש בישראל? {_thousand(wtotal)} תושבים זרים עם רישיון עבודה ב-{wyear}, "
            f"לפי ארץ אזרחות, ענף העסקה ויישוב. נתוני הלמ\"ס.")

    release = {
        "title": rel_title,
        "date": fmt.d_he(pd.Timestamp(str(rel["RELEASE_DATE"]))),
        "headline": str(rel.get("HEADLINE") or "").strip(),
        "url": str(rel.get("PAGE_URL") or ""),
        "pdf": str(rel.get("REPORT_PDF_URL") or ""),
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "misc",
            "temporal_coverage": (f"{all_years[0]}/{all_years[-1]}" if len(all_years) > 1
                                  else str(all_years[0])),
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "עובדים זרים בישראל: לפי ארץ, ענף ויישוב | הלמ\"ס",
                "description": desc,
                "name": "תושבים זרים בישראל",
                "alternate_names": ["עובדים זרים בישראל", "עובדים מחו\"ל", "תושבים זרים בסוף השנה",
                                    "מספר העובדים הזרים בישראל"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
        "callouts": callouts,
        "release": release,
    }
