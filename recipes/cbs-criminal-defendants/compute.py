"""עומדים לדין במשפטים פליליים: CBS's yearly release on people who stood
trial in criminal cases and received a verdict in a given year.

The release is a set of chart-data sheets ("תרשים N - ..."). Most hold ONE
verdict year; two hold a series of selected years (defendants by residency,
in thousands; Israeli residents by population group, %). The source reads
four editions (`history_releases: 4`), so each table grid stacks several
verdict years. Chart NUMBERS MOVE between editions (the offence table was
chart 2 for 2023 and chart 3 for 2024), so every table input (t1..t13, the
last three spare, all optional) is split by edition and each chart is found
by its TITLE text, never by its stem:

  trend     ... לפי תושבות, שנות פסק דין נבחרות            thousands, by year
  pop       ... לפי קבוצת אוכלוסייה, שנות פסק דין נבחרות    % of residents, by year
  offence   ... לפי תושבות ולפי קבוצת העבירה החמורה ביותר    % by offence group
  minors    קטינים ... קבוצת העבירה                           same, minors
  sex       ... לפי מין, גיל אחריות פלילית ... ותושבות       % men / women
  ses       ... אשכול חברתי-כלכלי של יישוב המגורים           % by cluster
  edu       ... התעודה הגבוהה ביותר                           defendants vs all residents
  edu_off   ... התעודה הגבוהה ביותר, בקבוצות עבירה נבחרות     education by offence
  conv      אחוז המורשעים ...                                 conviction rate by group
  recid     אחוז המועדים ...                                  repeat offenders by group

Single-year sections show the newest edition that has them; the two series
and the conviction / recidivism rates are merged across editions, the newest
edition winning a year two editions share (CBS revises earlier years). A
chart missing from every edition drops its section; a recognised chart with
data rows but without its header labels raises (the layout changed).
"""
import re

import pandas as pd
from govlib import cbs, fmt

STEM = re.compile(r"t\d+[a-z]?")
REL = re.compile(r"(\d+)\s*/\s*(\d{4})")
TITLE = re.compile(r"^תרשים\s*\d+[א-ת]?\s*[-\u2013\u2014]\s*")
VERDICT_YEAR = re.compile(r"שנת פסק דין\s*((?:19|20)\d\d)")
NIQQUD = re.compile(r"[֑-ׇ]")
CLUSTER = re.compile(r"^\d{1,2}\s*-\s*\d{1,2}$")
HEB = re.compile(r"[א-ת]")
# A year-on-year move smaller than this share is "about the same".
FLAT = 0.03
# Rate changes (percentage points) smaller than this are "about the same".
FLAT_PP = 1.0


# ── editions and tables ─────────────────────────────────────────────────


def _rel_key(no):
    m = REL.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _int(v):
    try:
        return int(str(v).strip())
    except ValueError:
        return 0


def _cells(df):
    return sorted((c for c in df.columns if re.fullmatch(r"C\d+", c)), key=lambda c: int(c[1:]))


def _title_at(rows):
    for i, r in enumerate(rows):
        for c in r:
            if TITLE.match(c):
                return i, NIQQUD.sub("", c)
    return None, ""


def _kind(t):
    body = TITLE.sub("", t)
    if "אחוז המורשעים" in t:
        return "conv"
    if "אחוז המועדים" in t:
        return "recid"
    if "התעודה הגבוהה" in t:
        return "edu_off" if "קבוצות עבירה" in t else "edu"
    if "אשכול חברתי" in t:
        return "ses"
    if "לפי מין" in t:
        return "sex"
    if "קבוצת העבירה" in t:
        return "minors" if body.startswith("קטינים") else "offence"
    if "קבוצת אוכלוסייה" in t and "שנות פסק דין" in t:
        return "pop"
    if "לפי תושבות" in t and "שנות פסק דין" in t:
        return "trend"
    return None


def _editions(frames):
    """{release key: {"no", "tables": {kind: (title row, title, rows)}}} over
    every non-empty table input; the first stem (by number) to hold a kind
    in an edition wins."""
    out = {}
    names = sorted((n for n in frames if STEM.fullmatch(n)), key=lambda n: (int(re.sub(r"\D", "", n)), n))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        cols = _cells(df)
        for no in sorted(df["RELEASE_NO"].unique(), key=lambda x: (_rel_key(x), str(x))):
            g = df[df["RELEASE_NO"] == no]
            g = g.assign(_s=g["SHEET_NO"].map(_int), _r=g["ROW"].map(_int))
            g = g.sort_values(["_s", "_r"], kind="stable")
            rows = [[cbs.clean(v) for v in r] for r in g[cols].itertuples(index=False)]
            ti, t = _title_at(rows)
            k = _kind(t) if ti is not None else None
            if not k:
                continue
            ed = out.setdefault(_rel_key(no), {"no": no, "tables": {}})
            if k not in ed["tables"]:
                ed["tables"][k] = (ti, t, rows)
    return out


# ── generic parsing ─────────────────────────────────────────────────────


def _is_num(c):
    return cbs.num(c) is not None


def _is_year(c):
    return bool(cbs.YEAR.match(c))


def _year_row(r):
    vals = [c for c in r[1:] if c]
    return len(vals) >= 2 and all(_is_year(c) for c in vals)


def _matrix(entry, name):
    """(columns [(j, label)], [(row label, {label: value})]) for one chart
    sheet: header rows (text, or a row of years) under the title, data rows
    (any number) below them. None when the sheet has no data rows; raises
    when it has data but no header."""
    ti, _, rows = entry
    first = None
    for i in range(ti + 1, len(rows)):
        r = rows[i]
        if _year_row(r):
            continue
        if any(_is_num(c) for c in r):
            first = i
            break
    if first is None:
        return None
    heads = [rows[i] for i in range(ti + 1, first) if any(c and c != "+" for c in rows[i])]
    if not heads:
        raise ValueError(f"{name}: header row not found")
    width = max(len(r) for r in heads)
    cols = []
    for j in range(width):
        lab = ""
        for h in reversed(heads):
            c = cbs.cell(h, j)
            if c and c != "+":
                lab = c
                break
        if lab:
            cols.append((j, lab))
    data = []
    for i in range(first, len(rows)):
        r = rows[i]
        if not any(_is_num(c) for c in r):
            continue
        lab = cbs.cell(r, 0)
        has_label = bool(lab) and not _is_num(lab) and lab not in cbs.MISSING
        vals = {}
        for j, c in cols:
            if j == 0 and has_label:
                continue
            v = cbs.val(r, j)
            vals[c] = round(v, 1) if v is not None else None
        data.append((lab if has_label else "", vals))
    return cols, data


def _verdict_year(entry):
    m = VERDICT_YEAR.search(entry[1])
    return int(m.group(1)) if m else None


def _need(labels, want, name):
    for w in want:
        if w not in labels:
            raise ValueError(f"{name}: header label {w!r} not found")


def _offence_label(s):
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("חיי אדם גופו", "חיי אדם וגופו")
    if not s.startswith("עבירות"):
        s = "עבירות " + s
    return s


# ── kind parsers ────────────────────────────────────────────────────────


def _series(entry, name, need_total):
    """{row label: {year: value}} for a by-year sheet (trend, pop)."""
    ti, _, rows = entry
    yr = None
    for i in range(ti + 1, len(rows)):
        if _year_row(rows[i]):
            yr = rows[i]
            break
    if yr is None:
        raise ValueError(f"{name}: year header row not found")
    m = _matrix(entry, name)
    if m is None:
        return {}
    years = [(j, int(c)) for j, c in enumerate(yr) if j > 0 and _is_year(c)]
    out = {}
    for i in range(ti + 1, len(rows)):
        r = rows[i]
        lab = cbs.cell(r, 0)
        if not lab or _is_num(lab) or _year_row(r):
            continue
        vals = {y: cbs.val(r, j) for j, y in years if cbs.val(r, j) is not None}
        if vals:
            out[lab] = vals
    if need_total and out and "סך הכל" not in out:
        raise ValueError(f"{name}: row 'סך הכל' not found")
    return out


def _offence(entry, name):
    """[(offence, {"סך הכל", "תושבי ישראל", "אינם תושבי ישראל"})]."""
    m = _matrix(entry, name)
    if m is None:
        return None
    cols, data = m
    _need([c for _, c in cols], ("סך הכל",), name)
    return [(_offence_label(lab), vals) for lab, vals in data if lab]


def _sex(entry):
    m = _matrix(entry, "sex")
    if m is None:
        return None
    cols, data = m
    out = {lab: vals for lab, vals in data if lab}
    _need(list(out), ("גברים", "נשים"), "sex")
    return [c for _, c in cols], out


def _ses(entry):
    """(clusters, {group: {cluster: %}}, {pop group: %} from the older layout)."""
    m = _matrix(entry, "ses")
    if m is None:
        return None
    cols, data = m
    clusters = [c for _, c in cols if CLUSTER.match(c)]
    if len(clusters) < 3:
        raise ValueError("ses: cluster header (1-2, 3-4, ...) not found")
    groups, pop = {}, {}
    for lab, vals in data:
        g = lab or "סך הכל"
        groups.setdefault(g, {c: vals.get(c) for c in clusters})
        if not lab:
            for c in ("יהודים ואחרים", "ערבים"):
                if vals.get(c) is not None:
                    pop[c] = vals[c]
    return clusters, groups, pop


def _edu(entry):
    m = _matrix(entry, "edu")
    if m is None:
        return None
    cols, data = m
    defn = next(((lab, v) for lab, v in data if "עומדים לדין" in lab), None)
    pop = next(((lab, v) for lab, v in data if lab and "עומדים לדין" not in lab), None)
    if defn is None:
        raise ValueError("edu: row 'עומדים לדין' not found")
    labels = [c for j, c in cols if j > 0]
    return labels, defn[1], (pop[1] if pop else {})


def _edu_off(entry):
    m = _matrix(entry, "edu_off")
    if m is None:
        return None
    cols, data = m
    labels = [c for j, c in cols if j > 0]
    _need(labels, ("סך הכל",), "edu_off")
    name = {c: (c if c == "סך הכל" else _offence_label(c)) for c in labels}
    levels = [(lab, {name.get(k, k): v for k, v in vals.items()}) for lab, vals in data if lab]
    return [name[c] for c in labels], levels


def _rates(entry, name):
    """{group: %} for the one-row conviction / recidivism sheets."""
    m = _matrix(entry, name)
    if m is None:
        return None
    cols, data = m
    _need([c for _, c in cols], ("סך הכל",), name)
    if not data:
        return None
    return {k: v for k, v in data[0][1].items() if v is not None}


# ── formatting ──────────────────────────────────────────────────────────


def _k(v):
    """A thousands figure as a whole count: 32.687 → 32687."""
    return round(v * 1000)


def _p(v):
    return "–" if v is None else f"{v:.1f}%"


def _cnt(v):
    return "–" if v is None else f"{_k(v):,}"


def _date(v):
    ts = pd.to_datetime(str(v), errors="coerce", format="%Y-%m-%d")
    return str(v) if pd.isna(ts) else fmt.d_he(ts)


def _change(new, old):
    if not old:
        return None
    return new / old - 1


# ── compute ─────────────────────────────────────────────────────────────


def compute(frames):
    eds = _editions(frames)
    if not eds:
        raise ValueError("no recognised chart in any edition")
    order = sorted(eds)  # oldest → newest

    def newest(kind):
        for key in reversed(order):
            if kind in eds[key]["tables"]:
                return eds[key]["tables"][kind]
        return None

    # ── series merged across editions (newest wins) ──
    trend, pop = {}, {}
    conv, recid = {}, {}
    sex_years, off_years = {}, {}
    for key in order:
        t = eds[key]["tables"]
        if "trend" in t:
            for lab, vals in _series(t["trend"], "trend", True).items():
                for y, v in vals.items():
                    trend.setdefault(lab, {})[y] = v
        if "ses" in t:
            r = _ses(t["ses"])
            y = _verdict_year(t["ses"])
            if r and y and r[2]:
                for g, v in r[2].items():
                    pop.setdefault(g, {})[y] = v
        if "pop" in t:
            for lab, vals in _series(t["pop"], "pop", False).items():
                for y, v in vals.items():
                    pop.setdefault(lab, {})[y] = v
        for kind, store in (("conv", conv), ("recid", recid)):
            if kind in t:
                y = _verdict_year(t[kind])
                r = _rates(t[kind], kind)
                if y and r:
                    store[y] = r
        if "sex" in t:
            y = _verdict_year(t["sex"])
            r = _sex(t["sex"])
            if y and r:
                sex_years[y] = r[1]
        if "offence" in t:
            y = _verdict_year(t["offence"])
            r = _offence(t["offence"], "offence")
            if y and r:
                off_years[y] = {lab: v.get("סך הכל") for lab, v in r}

    total = trend.get("סך הכל", {})
    if not total:
        raise ValueError("trend: no defendants total in any edition")
    years = sorted(total)
    ly = years[-1]
    py = years[-2] if len(years) > 1 else None
    res = trend.get("תושבי ישראל", {})
    nonres = trend.get("אינם תושבי ישראל", {})

    rel = cbs.latest_release(frames["releases"])
    labels, charts, tables, flags, kpis = {}, {}, {}, {}, {}
    ins = {}

    # ── KPIs ──
    kpis["total"] = {"value": _k(total[ly]), "display": f"{_k(total[ly]):,}", "tone": "brand"}
    if py is not None:
        ch = _change(total[ly], total[py])
        tone = "info" if abs(ch) >= FLAT else "brand"
        kpis["change"] = {"value": round(ch * 100, 1), "display": fmt.signed_pct(ch), "tone": tone}
        labels["change_kpi"] = f"שינוי לעומת {py}"
    if nonres.get(ly) is not None:
        sh = nonres[ly] / total[ly]
        kpis["nonres"] = {"value": round(sh * 100, 1), "display": f"{sh * 100:.1f}%", "tone": "brand"}
    cy = max(conv) if conv else None
    if cy is not None and conv[cy].get("סך הכל") is not None:
        kpis["conv"] = {"value": conv[cy]["סך הכל"], "display": f"{conv[cy]['סך הכל']:.1f}%", "tone": "brand"}
        labels["conv_kpi"] = f"מהעומדים לדין הורשעו ({cy})"
    ry = max(recid) if recid else None
    if ry is not None and recid[ry].get("סך הכל") is not None:
        kpis["recid"] = {"value": recid[ry]["סך הכל"], "display": f"{recid[ry]['סך הכל']:.1f}%", "tone": "brand"}
        labels["recid_kpi"] = f"מהעומדים לדין הם מועדים ({ry})"
    labels["total_kpi"] = f"עומדים לדין שקיבלו פסק דין בשנת {ly}"
    labels["nonres_kpi"] = f"מהם אינם תושבי ישראל ({ly})"

    # ── trend ──
    flags["trend"] = True
    charts["trend"] = {
        "x": [str(y) for y in years],
        "res": [_k(res[y]) if res.get(y) is not None else None for y in years],
        "nonres": [_k(nonres[y]) if nonres.get(y) is not None else None for y in years],
        "total": [_k(total[y]) for y in years],
    }
    tables["trend"] = [[str(y), _cnt(res.get(y)), _cnt(nonres.get(y)), _cnt(total[y])] for y in years]
    labels["trend_aria"] = f"עומדים לדין במשפטים פליליים לפי תושבות, שנות פסק דין נבחרות {years[0]}-{ly}"
    labels["years_span"] = f"{years[0]}-{ly}"
    labels["latest_year"] = str(ly)
    s = f"בשנת {ly} עמדו לדין במשפטים פליליים וקיבלו פסק דין {_k(total[ly]):,} איש"
    if py is not None:
        ch = _change(total[ly], total[py])
        if abs(ch) < FLAT:
            s += f", בדומה ל-{py} ({_k(total[py]):,})"
        else:
            s += f", {'עלייה' if ch > 0 else 'ירידה'} של {abs(ch) * 100:.1f}% לעומת {py} ({_k(total[py]):,})"
    if years[0] != py and years[0] != ly:
        s += f". בשנת {years[0]} עמדו לדין {_k(total[years[0]]):,}"
    ins["trend"] = s + "."
    labels["trend_note"] = (f"מספר העומדים לדין שקיבלו פסק דין בכל שנה, תושבי ישראל ומי שאינם תושבי ישראל. "
                            f"השנים בתרשים הן השנים שהלמ\"ס בחרה להציג ({years[0]}-{ly}), ולכן המרווחים ביניהן אינם שווים.")
    if py is not None and nonres.get(ly) is not None and nonres.get(py):
        ch = _change(nonres[ly], nonres[py])
        sh = nonres[ly] / total[ly]
        if abs(ch) >= FLAT:
            ins["nonres"] = (f"{_k(nonres[ly]):,} מהעומדים לדין בשנת {ly} ({sh * 100:.1f}%) אינם תושבי ישראל, "
                             f"{'עלייה' if ch > 0 else 'ירידה'} של {abs(ch) * 100:.1f}% לעומת {_k(nonres[py]):,} בשנת {py}.")
        else:
            ins["nonres"] = f"{_k(nonres[ly]):,} מהעומדים לדין בשנת {ly} ({sh * 100:.1f}%) אינם תושבי ישראל, בדומה ל-{py}."

    # ── population group (residents) ──
    jews, arabs = pop.get("יהודים ואחרים", {}), pop.get("ערבים", {})
    pyears = sorted(set(jews) & set(arabs))
    if len(pyears) >= 2:
        flags["pop"] = True
        charts["popgrp"] = {"x": [str(y) for y in pyears], "jews": [jews[y] for y in pyears],
                         "arabs": [arabs[y] for y in pyears]}
        tables["popgrp"] = [[str(y), _p(jews[y]), _p(arabs[y])] for y in pyears]
        labels["pop_aria"] = f"התפלגות תושבי ישראל העומדים לדין לפי קבוצת אוכלוסייה, {pyears[0]}-{pyears[-1]}"
        a0, a1 = arabs[pyears[0]], arabs[pyears[-1]]
        if abs(a1 - a0) >= FLAT_PP:
            ins["pop"] = (f"בקרב תושבי ישראל שעמדו לדין, חלקם של ערבים היה {a1:.1f}% בשנת {pyears[-1]}, "
                          f"לעומת {a0:.1f}% בשנת {pyears[0]}.")

    # ── offence groups (newest edition) ──
    e = newest("offence")
    off = _offence(e, "offence") if e else None
    if off:
        oy = _verdict_year(e)
        flags["offence"] = True
        off = sorted(off, key=lambda r: (-(r[1].get("סך הכל") or 0), r[0]))
        charts["offence"] = {"x": [r[0] for r in off],
                             "series": [{"name": c, "data": [r[1].get(c) for r in off]}
                                        for c in ("סך הכל", "תושבי ישראל", "אינם תושבי ישראל")]}
        tables["offence"] = [[r[0], _p(r[1].get("סך הכל")), _p(r[1].get("תושבי ישראל")),
                              _p(r[1].get("אינם תושבי ישראל"))] for r in off]
        labels["offence_aria"] = f"עומדים לדין לפי קבוצת העבירה החמורה ביותר ולפי תושבות, {oy}"
        labels["offence_year"] = str(oy)
        top = off[0]
        if len(off) > 1 and (top[1].get("סך הכל") or 0) > (off[1][1].get("סך הכל") or 0):
            s = f"קבוצת העבירה הנפוצה ביותר בשנת {oy} היא {top[0]}: {top[1]['סך הכל']:.1f}% מהעומדים לדין"
            r_, n_ = top[1].get("תושבי ישראל"), top[1].get("אינם תושבי ישראל")
            if r_ is not None and n_ is not None:
                s += f" ({r_:.1f}% מתושבי ישראל ו-{n_:.1f}% ממי שאינם תושבי ישראל)"
            ins["offence"] = s + "."
    # mix across verdict years
    oys = sorted(off_years)
    if len(oys) >= 2 and off:
        cats = [r[0] for r in off]
        flags["off_years"] = True
        charts["off_years"] = {"x": cats, "series": [{"name": str(y), "data": [off_years[y].get(c) for c in cats]} for y in oys]}
        tables["off_years"] = [[c] + [_p(off_years[y].get(c)) for y in oys] for c in cats]
        labels["off_years_cols"] = ["קבוצת עבירה"] + [str(y) for y in oys]
        labels["off_years_aria"] = f"התפלגות העומדים לדין לפי קבוצת עבירה בשנות פסק הדין {oys[0]}-{oys[-1]}"
        moves = []
        for c in cats:
            a, b = off_years[oys[0]].get(c), off_years[oys[-1]].get(c)
            if a is not None and b is not None:
                moves.append((-(abs(b - a)), c, a, b))
        moves.sort()
        if moves and -moves[0][0] >= 3 * FLAT_PP:
            _, c, a, b = moves[0]
            ins["off_years"] = (f"השינוי הגדול ביותר בהרכב העבירות בין {oys[0]} ל-{oys[-1]} הוא ב{c}: "
                                f"{'עלייה' if b > a else 'ירידה'} מ-{a:.1f}% ל-{b:.1f}% מהעומדים לדין.")

    # ── minors ──
    e = newest("minors")
    mi = _offence(e, "minors") if e else None
    if mi:
        my = _verdict_year(e)
        flags["minors"] = True
        mi = sorted(mi, key=lambda r: (-(r[1].get("סך הכל") or 0), r[0]))
        charts["minors"] = {"x": [r[0] for r in mi],
                            "series": [{"name": c, "data": [r[1].get(c) for r in mi]}
                                       for c in ("סך הכל", "תושבי ישראל", "אינם תושבי ישראל")]}
        tables["minors"] = [[r[0], _p(r[1].get("סך הכל")), _p(r[1].get("תושבי ישראל")),
                             _p(r[1].get("אינם תושבי ישראל"))] for r in mi]
        labels["minors_aria"] = f"קטינים העומדים לדין לפי קבוצת העבירה החמורה ביותר ולפי תושבות, {my}"
        labels["minors_year"] = str(my)
        if len(mi) > 1 and (mi[0][1].get("סך הכל") or 0) > (mi[1][1].get("סך הכל") or 0):
            ins["minors"] = (f"בקרב קטינים שעמדו לדין בשנת {my}, קבוצת העבירה הנפוצה ביותר היא "
                             f"{mi[0][0]} ({mi[0][1]['סך הכל']:.1f}%), ואחריה {mi[1][0]} ({mi[1][1]['סך הכל']:.1f}%).")

    # ── sex ──
    e = newest("sex")
    sx = _sex(e) if e else None
    if sx:
        sy = _verdict_year(e)
        cols, by = sx
        groups = [c for c in cols if c not in ("גברים", "נשים")]
        flags["sex"] = True
        charts["sex"] = {"x": groups, "men": [by["גברים"].get(g) for g in groups],
                         "women": [by["נשים"].get(g) for g in groups]}
        tables["sex"] = [[g, _p(by["גברים"].get(g)), _p(by["נשים"].get(g))] for g in groups]
        labels["sex_aria"] = f"עומדים לדין לפי מין, גיל אחריות פלילית ותושבות, {sy}"
        labels["sex_year"] = str(sy)
        w = by["נשים"].get("סך הכל")
        if w is not None:
            s = f"נשים הן {w:.1f}% מהעומדים לדין בשנת {sy}"
            sys_ = sorted(y for y in sex_years if sex_years[y]["נשים"].get("סך הכל") is not None)
            if len(sys_) >= 2 and sys_[0] != sy:
                w0 = sex_years[sys_[0]]["נשים"]["סך הכל"]
                s += f" ({w0:.1f}% בשנת {sys_[0]})"
            ins["sex"] = s + "."

    # ── socio-economic cluster ──
    e = newest("ses")
    se = _ses(e) if e else None
    if se:
        sey = _verdict_year(e)
        clusters, groups, _ = se
        gnames = [g for g in ("סך הכל", "יהודים ואחרים", "ערבים") if g in groups] + \
                 sorted(g for g in groups if g not in ("סך הכל", "יהודים ואחרים", "ערבים"))
        flags["ses"] = True
        charts["ses"] = {"x": clusters, "series": [{"name": g, "data": [groups[g].get(c) for c in clusters]} for g in gnames]}
        tables["ses"] = [[c] + [_p(groups[g].get(c)) for g in gnames] for c in clusters]
        labels["ses_cols"] = ["אשכול"] + gnames
        labels["ses_aria"] = f"תושבי ישראל העומדים לדין לפי אשכול חברתי-כלכלי של יישוב המגורים, {sey}"
        labels["ses_year"] = str(sey)
        tot = groups.get("סך הכל", {})
        low = [tot.get(c) for c in clusters[:2]]
        top = tot.get(clusters[-1])
        lo, hi = clusters[0].split("-")[0].strip(), clusters[1].split("-")[-1].strip()
        if all(v is not None for v in low) and top is not None:
            ins["ses"] = (f"{sum(low):.1f}% מתושבי ישראל שעמדו לדין בשנת {sey} גרים ביישובים באשכולות "
                          f"{lo} עד {hi}, ו-{top:.1f}% ביישובים באשכולות {clusters[-1]}.")

    # ── education ──
    e = newest("edu")
    ed = _edu(e) if e else None
    if ed:
        ey = _verdict_year(e)
        cats, dfn, popu = ed
        flags["edu"] = True
        charts["edu"] = {"x": cats, "series": [{"name": "עומדים לדין", "data": [dfn.get(c) for c in cats]}]
                         + ([{"name": "כלל התושבים", "data": [popu.get(c) for c in cats]}] if popu else [])}
        tables["edu"] = [[c, _p(dfn.get(c)), _p(popu.get(c))] for c in cats]
        labels["edu_aria"] = f"מבוגרים בני 25 עד 69 תושבי ישראל העומדים לדין לפי התעודה הגבוהה ביותר, {ey}"
        labels["edu_year"] = str(ey)
        acad = next((c for c in cats if "תואר אקדמי" in c), None)
        if acad and dfn.get(acad) is not None and popu.get(acad) is not None:
            ins["edu"] = (f"{dfn[acad]:.1f}% מהעומדים לדין בני 25 עד 69 (תושבי ישראל) בשנת {ey} הם בעלי תואר אקדמי, "
                          f"לעומת {popu[acad]:.1f}% מכלל התושבים בגילים אלה.")

    e = newest("edu_off")
    eo = _edu_off(e) if e else None
    if eo:
        eoy = _verdict_year(e)
        cats, levels = eo
        flags["edu_off"] = True
        charts["edu_off"] = {"x": cats, "series": [{"name": lab, "data": [v.get(c) for c in cats]} for lab, v in levels]}
        tables["edu_off"] = [[c] + [_p(v.get(c)) for _, v in levels] for c in cats]
        labels["edu_off_cols"] = ["קבוצת עבירה"] + [lab for lab, _ in levels]
        labels["edu_off_aria"] = f"העומדים לדין בני 25 עד 69 לפי התעודה הגבוהה ביותר בקבוצות עבירה נבחרות, {eoy}"
        labels["edu_off_year"] = str(eoy)

    # ── conviction / recidivism across editions ──
    for kind, store in (("conv", conv), ("recid", recid)):
        if not store:
            continue
        ys = sorted(store)
        groups = []
        for y in ys:
            for g in store[y]:
                if g not in groups:
                    groups.append(g)
        newest_groups = list(store[ys[-1]])
        groups = newest_groups + [g for g in groups if g not in newest_groups]
        flags[kind] = True
        charts[kind] = {"x": groups, "series": [{"name": str(y), "data": [store[y].get(g) for g in groups]} for y in ys]}
        tables[kind] = [[g] + [_p(store[y].get(g)) for y in ys] for g in groups]
        labels[f"{kind}_cols"] = ["קבוצה"] + [str(y) for y in ys]
        labels[f"{kind}_span"] = str(ys[0]) if len(ys) == 1 else f"{ys[0]}-{ys[-1]}"
    if conv:
        ys = sorted(conv)
        c = conv[ys[-1]]
        labels["conv_aria"] = f"אחוז המורשעים בקרב העומדים לדין לפי קבוצה, {labels['conv_span']}"
        if c.get("מבוגרים") is not None and c.get("קטינים") is not None and c.get("סך הכל") is not None:
            ins["conv"] = (f"{c['סך הכל']:.1f}% מהעומדים לדין בשנת {ys[-1]} הורשעו: "
                           f"{c['מבוגרים']:.1f}% מהמבוגרים ו-{c['קטינים']:.1f}% מהקטינים.")
    if recid:
        ys = sorted(recid)
        r = recid[ys[-1]]
        labels["recid_aria"] = f"אחוז המועדים בקרב העומדים לדין לפי קבוצה, {labels['recid_span']}"
        if r.get("סך הכל") is not None:
            s = f"{r['סך הכל']:.1f}% מהעומדים לדין בשנת {ys[-1]} הם מועדים (הורשעו בעבר)"
            if len(ys) >= 2 and recid[ys[0]].get("סך הכל") is not None:
                d = r["סך הכל"] - recid[ys[0]]["סך הכל"]
                if abs(d) >= FLAT_PP:
                    s += f", לעומת {recid[ys[0]]['סך הכל']:.1f}% בשנת {ys[0]}"
                else:
                    s += f", בדומה לשנת {ys[0]}"
            ins["recid"] = s + "."

    order_ins = ["trend", "nonres", "offence", "conv", "recid", "off_years", "minors", "sex", "edu", "pop", "ses"]
    insights = [{"id": k, "text_he": ins[k]} for k in order_ins if ins.get(k)]

    # ── release card ──
    labels["release"] = {
        "title": str(rel.get("TITLE", "")), "date": _date(rel.get("RELEASE_DATE", "")),
        "headline": str(rel.get("HEADLINE", "")).strip().strip("\u200b").strip(),
        "url": str(rel.get("PAGE_URL", "")), "pdf": str(rel.get("REPORT_PDF_URL", "")),
    }

    lede = (f"נתוני הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על האנשים שעמדו לדין במשפט פלילי וקיבלו פסק דין בשנה נתונה: "
            f"{_k(total[ly]):,} איש בשנת {ly}")
    if "conv" in kpis:
        lede += f", מהם {kpis['conv']['display']} הורשעו"
    lede += (". העמוד מציג את מספר הנאשמים לאורך השנים, קבוצות העבירה, גיל, מין, תושבות, השכלה ואשכול חברתי-כלכלי, "
             "ואת אחוז המורשעים והמועדים.")
    labels["lede"] = lede

    summary = f"עומדים לדין במשפטים פליליים לפי נתוני הלמ\"ס: {_k(total[ly]):,} איש קיבלו פסק דין בשנת {ly}"
    if "conv" in kpis:
        summary += f", {kpis['conv']['display']} מהם הורשעו"
    summary += ". קבוצות עבירה, גיל, מין, תושבות והשכלה."
    desc = f"כמה אנשים עומדים לדין בפלילים בישראל: {_k(total[ly]):,} נאשמים קיבלו פסק דין בשנת {ly}"
    if "conv" in kpis:
        desc += f", {kpis['conv']['display']} הורשעו"
    desc += ". לפי עבירה, גיל ומין."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0]}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "עומדים לדין במשפטים פליליים בישראל: נתונים שנתיים",
                "description": desc,
                "name": "עומדים לדין במשפטים פליליים",
                "alternate_names": ["נאשמים במשפטים פליליים", "הועמדו לדין בפלילים",
                                    "סטטיסטיקה של נאשמים ומורשעים", "פסקי דין פליליים לפי שנה"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "flags": flags,
        "labels": labels,
        "insights": insights,
    }
