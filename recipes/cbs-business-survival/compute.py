"""שרידות ותנועות של עסקים: CBS's yearly business-demography release.

The release is a set of tables whose NUMBERS MAY MOVE between editions, so
every table input (t1..t11, the last three spare, all optional) is read with
`cbs.grid` and each table is recognised by its TITLE text, not by its stem:

  active     עסקים פעילים, לפי ענף ... וקבוצת גודל     t1 in 2024-2026
  jobs       משרות שכיר ... לפי ענף ... (אלפים)        t2
  vat        פתיחות וסגירות (תיקי עוסקי מע"מ)          t3
  births     לידות עסקים והאחוז ... מסך העסקים הפעילים  t4, three years
  district   לידות עסקים, לפי מחוז                      t5, two sheets
  bsize      לידות עסקים, לפי ענף ... וקבוצות גודל      t6
  bjobs      משרות שכיר שנוספו ... לידות עסקים          t7
  survival   אחוז ההישרדות של העסקים שנולדו בשנת ...    t8 (chart data)

Columns are found by header labels; a recognised table whose labels are gone
raises (a human should look). A table missing from an edition drops its
section; `births` and `survival` are required (every edition so far has
them). The survival workbook of 2026 carries two sheets (the previous
edition's numbers and the updated chart): the block whose title names the
latest "עד לשנת" year wins, then the later sheet.
"""
import re

import pandas as pd
from govlib import cbs, fmt

HEB = re.compile("[א-ת]")
YEAR_END = re.compile(r"((?:19|20)\d\d)R?$")
YEAR_ANY = re.compile(r"(?:19|20)\d\d")
SIZE = re.compile(r"^(\d+)(?:-(\d+)|\+)$")

# Short chart labels by keyword (first match wins); the full CBS name stays in
# the tables. Unknown industries keep their full name.
SHORT = (
    ("היי-טק", "היי-טק"),
    ("חקלאות", "חקלאות"),
    ("כרייה", None),  # resolved below: with or without electricity and water
    ("אספקת חשמל", "חשמל, מים ופסולת"),
    ("בינוי", "בינוי"),
    ("מסחר", "מסחר"),
    ("תחבורה", "תחבורה ואחסנה"),
    ("אירוח", "אירוח ואוכל"),
    ("מידע ותקשורת", "מידע ותקשורת"),
    ("פיננסיים", "פיננסים וביטוח"),
    ("נדל", "נדל\"ן"),
    ("מקצועיים", "שירותים מקצועיים"),
    ("ניהול", "ניהול ותמיכה"),
    ("מינהל", "מינהל ציבורי"),
    ("מנהל מקומי", "מינהל ציבורי"),
    ("חינוך", "חינוך"),
    ("בריאות", "בריאות ורווחה"),
    ("אמנות", "אמנות ופנאי"),
    ("שירותים אחרים", "שירותים אחרים"),
)
DISTRICT_FIX = {"תלאביב": "תל אביב", "המרכז": "מרכז", "הצפון": "צפון", "הדרום": "דרום"}
PRIORITY = ("survival", "survival_gap", "births", "vat", "birth_rate", "district",
            "concentration", "self_employed", "bsize", "bjobs", "jobs_lead")
MAX_TOP = 8


def short(name):
    for key, s in SHORT:
        if key in name:
            if key == "כרייה":
                return "תעשייה ואנרגיה" if "חשמל" in name else "תעשייה"
            return s
    return name


def _r1(v):
    return None if v is None else round(v, 1)


def _p(v, d=1):
    return "" if v is None else fmt.pct_of(v, d)


def _n(v):
    return "" if v is None else fmt.int_he(v)


def _heb(c):
    return bool(c) and bool(HEB.search(c))


# ── locating tables ──────────────────────────────────────────────────────


def _kind(rows):
    head = " ".join(c for r in rows[:8] for c in r if c)
    if "אחוז ההישרדות" in head:
        return "survival"
    if "פתיחות וסגירות" in head:
        return "vat"
    if "לידות עסקים" in head:
        if re.search(r"משרות שכיר\S* שנוספו", head):
            return "bjobs"
        if "מחוז" in head:
            return "district"
        if "קבוצות גודל" in head:
            return "bsize"
        if "האחוז" in head:
            return "births"
        return None
    if "עסקים פעילים" in head:
        return "active"
    if "משרות שכיר" in head and "ענף" in head:
        return "jobs"
    return None


def _tables(frames):
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        k = _kind(rows)
        if k and k not in out:
            out[k] = rows
    return out


def _year_cell(rows, start=0, stop=None):
    """The first cell that is a bare year in rows[start:stop]."""
    for r in rows[start:stop]:
        for c in r:
            if cbs.YEAR.match(c):
                return int(c)
    return None


# ── parsers ──────────────────────────────────────────────────────────────


def _industry_rows(rows, start, code_col, label_col, value_col):
    """Industry rows whose label may run over two sheet rows: a row with a
    section code opens an industry, and the row holding the numbers closes
    it (its label continues the name)."""
    out, name = [], None
    for r in rows[start:]:
        code, label = cbs.cell(r, code_col), cbs.cell(r, label_col)
        if code and _heb(label):
            name = label
        elif name is not None and _heb(label):
            name = f"{name} {label}"
        if name is not None and cbs.val(r, value_col) is not None:
            out.append((name, r))
            name = None
    return out


def _active(rows):
    h = cbs.row_with(rows, "ענף כלכלי", name="active")
    lab = cbs.col_after(rows[h], "ענף כלכלי")
    code = cbs.col_after(rows[h], "סדר")
    self_c = cbs.col_after(rows[h], "Self-")
    sizes = [(j, c) for j, c in enumerate(rows[h]) if SIZE.match(c)]
    if len(sizes) < 4:
        raise ValueError("active: size-group header columns not found")
    grand, emp = self_c - 1, self_c + 1
    t = cbs.row_with(rows, "סך הכל", h + 1, name="active")
    tot = {"grand": cbs.val(rows[t], grand), "self": cbs.val(rows[t], self_c),
           "emp": cbs.val(rows[t], emp), "sizes": [cbs.val(rows[t], j) for j, _ in sizes]}
    if None in (tot["grand"], tot["self"], tot["emp"]) or abs(tot["grand"] - tot["self"] - tot["emp"]) > 2:
        raise ValueError("active: total row does not add up (columns moved)")
    inds = []
    for name, r in _industry_rows(rows, t + 1, code, lab, grand):
        inds.append({"name": name, "grand": cbs.val(r, grand), "self": cbs.val(r, self_c),
                     "emp": cbs.val(r, emp)})
    return {"year": _year_cell(rows, 0, h), "total": tot, "sizes": [c for _, c in sizes],
            "industries": inds}


def _jobs(rows):
    h = cbs.row_with(rows, "ענף כלכלי", name="jobs")
    lab = cbs.col_after(rows[h], "ענף כלכלי")
    code = cbs.col_after(rows[h], "סדר")
    cbs.row_with(rows, "אלפים", 0, name="jobs", contains=True)
    sizes = [(j, c) for j, c in enumerate(rows[h]) if SIZE.match(c)]
    if len(sizes) < 4:
        raise ValueError("jobs: size-group header columns not found")
    total_c = sizes[0][0] - 1
    t = cbs.row_with(rows, "סך הכל", h + 1, name="jobs")
    tot = cbs.val(rows[t], total_c)
    svals = [cbs.val(rows[t], j) for j, _ in sizes]
    if tot is None or None in svals or abs(sum(svals) - tot) > max(5, tot * 0.01):
        raise ValueError("jobs: total row does not add up (columns moved)")
    inds = []
    for name, r in _industry_rows(rows, t + 1, code, lab, total_c):
        inds.append({"name": name, "total": cbs.val(r, total_c),
                     "sizes": [cbs.val(r, j) for j, _ in sizes]})
    return {"year": _year_cell(rows, 0, h), "total": tot, "sizes": [c for _, c in sizes],
            "size_vals": svals, "industries": inds}


def _vat(rows):
    h = next((i for i, r in enumerate(rows) if any(c.startswith("פתיחות") for c in r)), None)
    if h is None:
        raise ValueError("vat: header label 'פתיחות' not found")
    years = {}
    for j, c in enumerate(rows[h]):
        if not c.startswith("פתיחות"):
            continue
        m = YEAR_END.match(cbs.cell(rows[h - 1], j)) if h else None
        if not m:
            raise ValueError("vat: year above the openings column not found")
        cl = cbs.col_after(rows[h], "סגירות", j + 1, contains=True)
        net = cbs.col_after(rows[h], "תוספת", j + 1, contains=True)
        years[int(m.group(1))] = (j, cl, net)
    if not years:
        raise ValueError("vat: openings columns not found")
    t = cbs.row_with(rows, "כלל ענפי הכלכלה", h + 1, name="vat")
    code = 0
    lab = cbs.best_col(rows[t + 1:], _heb, exclude=(code,))
    ys = sorted(years)

    def vals(r):
        return {y: tuple(cbs.val(r, j) for j in years[y]) for y in ys}

    inds, hitech = [], None
    for r in rows[t + 1:]:
        name = cbs.cell(r, lab) if lab is not None else ""
        if not cbs.cell(r, code) or not _heb(name):
            continue
        v = vals(r)
        if v[ys[-1]][0] is None:
            continue
        if "היי-טק" in name:
            hitech = {"name": name, "v": v}
        else:
            inds.append({"name": name, "v": v})
    return {"years": ys, "total": vals(rows[t]), "industries": inds, "hitech": hitech}


def _births(rows):
    h = cbs.row_with(rows, "ענף כלכלי", name="births")
    lab = cbs.col_after(rows[h], "ענף כלכלי")
    cols = {}
    for j, c in enumerate(rows[h]):
        if c == "לידות עסקים":
            y = None
            for k in range(h - 1, max(-1, h - 4), -1):
                if cbs.YEAR.match(cbs.cell(rows[k], j)):
                    y = int(cbs.cell(rows[k], j))
                    break
            if y is None:
                raise ValueError("births: year above a births column not found")
            pc = cbs.col_after(rows[h], "אחוז לידות", j + 1, contains=True)
            cols[y] = (j, pc)
    if not cols:
        raise ValueError("births: header label 'לידות עסקים' not found")
    ys = sorted(cols)
    t = cbs.row_with(rows, "כלל ענפי הכלכלה", h + 1, name="births")
    total = {y: (cbs.val(rows[t], cols[y][0]), cbs.val(rows[t], cols[y][1])) for y in ys}
    inds = []
    for r in rows[t + 1:]:
        name = cbs.cell(r, lab)
        if not _heb(name) or cbs.val(r, cols[ys[-1]][0]) is None:
            continue
        inds.append({"name": name,
                     "v": {y: (cbs.val(r, cols[y][0]), cbs.val(r, cols[y][1])) for y in ys}})
    return {"years": ys, "total": total, "industries": inds}


def _district_name(s):
    s = cbs.clean(s)
    if re.fullmatch(r"(?:\S )+\S", s):
        s = s.replace(" ", "")
    return DISTRICT_FIX.get(s, s)


def _district(rows):
    """Per-district totals: each block has a header row with 'אחוז' / 'עסקים'
    / 'לידות' over every district and a Total row under it."""
    out, year = [], None
    i = 0
    while i < len(rows):
        r = rows[i]
        acts = [j for j, c in enumerate(r) if c == "עסקים" and cbs.cell(r, j - 1) == "אחוז"]
        if not acts:
            i += 1
            continue
        names = {}
        for j in acts:
            # The name sits over the block's percent, active or births
            # column (it varies by sheet).
            for k in range(i - 1, max(-1, i - 4), -1):
                hit = next((cbs.cell(rows[k], c) for c in (j, j - 1, j + 1)
                            if _heb(cbs.cell(rows[k], c))), None)
                if hit:
                    names[j] = _district_name(hit)
                    break
            if j not in names:
                raise ValueError("district: district name above a block not found")
        if year is None:
            year = _year_cell(rows, max(0, i - 4), i)
        t = None
        for k in range(i + 1, len(rows)):
            if "Total" in rows[k] or "סך הכל" in rows[k]:
                t = k
                break
            if any(c == "עסקים" for c in rows[k]) and any(c == "אחוז" for c in rows[k]):
                break
        if t is not None:
            for j in acts:
                act, b, pc = cbs.val(rows[t], j), cbs.val(rows[t], j + 1), cbs.val(rows[t], j - 1)
                if act is not None and b is not None:
                    out.append({"name": names[j], "active": act, "births": b, "rate": pc})
        i += 1
    return {"year": year, "rows": out}


def _size_table(rows, kind, first_label, total_label):
    h = cbs.row_with(rows, "ענף כלכלי", name=kind)
    lab = cbs.col_after(rows[h], "ענף כלכלי")
    size_cols = [(j, c.split(" ")[0]) for j, c in enumerate(rows[h])
                 if "משרות שכיר" in c and SIZE.match(c.split(" ")[0])]
    if len(size_cols) < 3 or not size_cols[0][1] == first_label:
        raise ValueError(f"{kind}: size-group header columns not found")
    tot_c = cbs.col_after(rows[h], total_label, contains=True)
    year = None
    for r in rows[:h]:
        for c in r:
            m = re.search(r"בשנת ((?:19|20)\d\d)", c)
            if m and "שנוספו" in c:
                year = int(m.group(1))
    inds, total = [], None
    for r in rows[h + 1:]:
        name = cbs.cell(r, lab)
        if not _heb(name):
            continue
        rec = {"name": name, "total": cbs.val(r, tot_c), "sizes": [cbs.val(r, j) for j, _ in size_cols]}
        if name in ('סה"כ', "סך הכל"):
            total = rec
        elif rec["total"] is not None:
            inds.append(rec)
    return {"year": year, "sizes": [c for _, c in size_cols], "industries": inds, "total": total,
            "h": h, "lab": lab}


def _bsize(rows):
    d = _size_table(rows, "bsize", "1-4", "סך הכל מעסיקים")
    h = d["h"]
    non = cbs.col_after(rows[h], "לא מעסיקים", contains=True)
    for rec in d["industries"] + ([d["total"]] if d["total"] else []):
        r = next(r for r in rows[h + 1:] if cbs.cell(r, d["lab"]) == rec["name"])
        rec["non"] = cbs.val(r, non)
    return d


def _survival_block(rows, s, e, title):
    """One chart-data block: (birth year, activity years, series) or None
    when the block holds no data rows (a sheet cut short)."""
    m_birth = re.search(r"שנולדו בשנת ((?:19|20)\d\d)", title)
    if not m_birth:
        raise ValueError("survival: cohort year not in the title")
    hdr, cols = None, []
    for i in range(s, e):
        cs = [(j, int(YEAR_END.search(c).group(1))) for j, c in enumerate(rows[i])
              if _heb(c) and YEAR_END.search(c)]
        if len(cs) >= 3:
            hdr, cols = i, cs
            break
    if hdr is None:
        return None
    series = []
    for r in rows[hdr + 1:e]:
        label = cbs.cell(r, 0)
        if not _heb(label):
            continue
        name = re.sub(r"\s+[A-Z][A-Z,\- ]*$", "", label).strip()
        vals = [cbs.val(r, j) for j, _ in cols]
        if sum(v is not None for v in vals) >= 2:
            series.append((name, vals))
    if not series:
        return None
    return {"birth": int(m_birth.group(1)), "years": [y for _, y in cols], "series": series}


def _survival(rows):
    """The block whose title names the latest "עד לשנת" year wins, then the
    later sheet; a block without data rows is passed over."""
    starts = [i for i, r in enumerate(rows) if any("אחוז ההישרדות" in c for c in r)]
    if not starts:
        raise ValueError("survival: title not found")
    best = None
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(rows)
        title = next(c for c in rows[s] if "אחוז ההישרדות" in c)
        m_end = re.search(r"עד לשנת ((?:19|20)\d\d)", title)
        blk = _survival_block(rows, s, e, title)
        if blk is None:
            continue
        key = (int(m_end.group(1)) if m_end else 0, n)
        if best is None or key > best[0]:
            best = (key, blk)
    if best is None:
        raise ValueError("survival: activity-year header or series rows not found")
    return best[1]


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    tabs = _tables(frames)
    for need in ("births", "survival"):
        if need not in tabs:
            raise ValueError(f"required table '{need}' not found in any input")
    rel = cbs.latest_release(frames["releases"])

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(i, text):
        if text:
            insights.append({"id": i, "text_he": text})

    # ── survival ─────────────────────────────────────────────────────────
    sv = _survival(tabs["survival"])
    birth, sy = sv["birth"], sv["years"]
    allx = next(((nm, v) for nm, v in sv["series"] if "כלל" in nm), sv["series"][0])
    others = [(nm, v) for nm, v in sv["series"] if nm != allx[0]]
    others.sort(key=lambda nv: (-(nv[1][-1] or 0), nv[0]))
    ordered = [allx] + others
    charts["survival"] = {"x": [str(y) for y in sy],
                          "names": [short(nm) if nm != allx[0] else "כלל ענפי הכלכלה" for nm, _ in ordered],
                          "series": [[_r1(v) for v in vals] for _, vals in ordered]}
    tables["survival"] = [[str(y)] + [_p(vals[k]) for _, vals in ordered] for k, y in enumerate(sy)]
    labels["survival_cols"] = ["שנה"] + charts["survival"]["names"]
    a_vals = allx[1]
    last_k = max(k for k, v in enumerate(a_vals) if v is not None)
    s_last, y_last = a_vals[last_k], sy[last_k]
    labels["survival_note"] = (f"מתוך העסקים שנולדו (התחילו לפעול) בשנת {birth}, איזה אחוז עדיין פעיל בכל שנה "
                               f"שאחריה, עד {y_last}: כלל המשק וענפים נבחרים.")
    labels["survival_aria"] = f"אחוז ההישרדות של העסקים שנולדו בשנת {birth}, {sy[0]} עד {y_last}"
    half = next((k for k, v in enumerate(a_vals) if v is not None and v < 50), None)
    txt = (f"רק {_p(s_last)} מהעסקים שנולדו בשנת {birth} עדיין פעילים בשנת {y_last}"
           + (f". {_p(a_vals[0])} שרדו עד {sy[0]}" if a_vals[0] is not None else ""))
    if half is not None and half > 0:
        txt += f", ובשנת {sy[half]} כבר פחות ממחציתם ({_p(a_vals[half])}) היו פעילים"
    add("survival", txt + ".")
    kpis["survival"] = {"value": s_last, "display": _p(s_last), "tone": "info"}
    labels["survival_kpi"] = f"מהעסקים שנולדו ב-{birth} שרדו עד {y_last}"
    lasts = [(nm, v[-1]) for nm, v in others if v[-1] is not None]
    if len(lasts) >= 2:
        hi, lo = lasts[0], lasts[-1]
        if hi[1] >= 2 * lo[1]:
            add("survival_gap", f"השרידות תלויה מאוד בענף: בשנת {sy[-1]} פעילים עדיין {_p(hi[1])} מהעסקים "
                                f"בענף {short(hi[0])} שנולדו ב-{birth}, לעומת {_p(lo[1])} בלבד בענף {short(lo[0])}.")

    # ── births: total trend + by industry ────────────────────────────────
    bt = _births(tabs["births"])
    bys = bt["years"]
    ly = bys[-1]
    b_last, r_last = bt["total"][ly]
    if b_last is None:
        raise ValueError("births: total of the latest year missing")
    charts["births"] = {"x": [str(y) for y in bys],
                        "births": [bt["total"][y][0] for y in bys],
                        "rate": [_r1(bt["total"][y][1]) for y in bys]}
    tables["births"] = [[str(y), _n(bt["total"][y][0]), _p(bt["total"][y][1])] for y in bys]
    labels["births_aria"] = f"לידות עסקים בישראל, {bys[0]} עד {ly}"
    labels["births_note"] = ("כמה עסקים חדשים נולדו בכל שנה (עסק שדיווח על פעילות בשנה הנוכחית ולא בשנתיים "
                             "שלפניה), ואיזה אחוז הם מכלל העסקים הפעילים.")
    prev = bt["total"][bys[-2]][0] if len(bys) >= 2 else None
    tone = "brand"
    if prev:
        ch = b_last / prev - 1
        tone = "ok" if ch >= 0.02 else ("warn" if ch <= -0.02 else "brand")
        word = "עלייה" if ch >= 0.005 else ("ירידה" if ch <= -0.005 else None)
        txt = f"בשנת {ly} נולדו {fmt.int_he(b_last)} עסקים חדשים"
        if word:
            txt += f", {word} של {fmt.pct(abs(ch))} לעומת {bys[-2]} ({fmt.int_he(prev)})"
        else:
            txt += f", כמעט כמו ב-{bys[-2]} ({fmt.int_he(prev)})"
        if r_last is not None:
            txt += f". הם {_p(r_last)} מכלל העסקים הפעילים"
        add("births", txt + ".")
    kpis["births"] = {"value": b_last, "display": fmt.int_he(b_last), "tone": tone}
    labels["births_kpi"] = f"עסקים חדשים שנולדו ב-{ly}"
    if r_last is not None:
        kpis["birth_rate"] = {"value": r_last, "display": _p(r_last), "tone": "brand"}
        labels["birth_rate_kpi"] = f"שיעור לידות העסקים ב-{ly} (מהעסקים הפעילים)"

    inds = [i for i in bt["industries"] if i["v"][ly][1] is not None]
    inds.sort(key=lambda i: (-i["v"][ly][1], i["name"]))
    flags["rate"] = len(inds) >= 3
    if flags["rate"]:
        charts["rate"] = {"names": [short(i["name"]) for i in inds],
                          "rate": [_r1(i["v"][ly][1]) for i in inds],
                          "births": [i["v"][ly][0] for i in inds],
                          "avg": _r1(r_last)}
        tables["rate"] = [[i["name"], _n(i["v"][ly][0]), _p(i["v"][ly][1])]
                          + ([_p(i["v"][bys[0]][1])] if len(bys) > 1 else []) for i in inds]
        labels["rate_cols"] = (["ענף", f"לידות עסקים {ly}", f"אחוז מהפעילים {ly}"]
                               + ([f"אחוז מהפעילים {bys[0]}"] if len(bys) > 1 else []))
        labels["rate_aria"] = f"שיעור לידות העסקים לפי ענף כלכלי, {ly}"
        labels["rate_note"] = (f"באיזה ענף נפתחים הכי הרבה עסקים חדשים ביחס לגודלו: לידות העסקים בשנת {ly} "
                               f"כאחוז מהעסקים הפעילים בענף.")
        hi, lo = inds[0], inds[-1]
        if hi["v"][ly][1] >= 1.5 * lo["v"][ly][1]:
            add("birth_rate", f"הענף התוסס ביותר הוא {short(hi['name'])}: {_p(hi['v'][ly][1])} מהעסקים בו "
                              f"נולדו בשנת {ly}, לעומת {_p(lo['v'][ly][1])} בלבד בענף {short(lo['name'])}.")
        big = max(inds, key=lambda i: (i["v"][ly][0], i["name"]))
        labels["rate_big"] = (f"במספרים מוחלטים נולדו הכי הרבה עסקים בענף {short(big['name'])}: "
                              f"{fmt.int_he(big['v'][ly][0])} בשנת {ly}.")

    # ── births by district ───────────────────────────────────────────────
    dist = _district(tabs["district"]) if "district" in tabs else {"rows": []}
    drows = sorted([d for d in dist["rows"] if d["rate"] is not None],
                   key=lambda d: (-d["rate"], d["name"]))
    flags["district"] = len(drows) >= 3
    if flags["district"]:
        dy = dist["year"] or ly
        charts["district"] = {"names": [d["name"] for d in drows], "rate": [_r1(d["rate"]) for d in drows],
                              "births": [d["births"] for d in drows], "active": [d["active"] for d in drows]}
        tables["district"] = [[d["name"], _n(d["active"]), _n(d["births"]), _p(d["rate"])] for d in drows]
        labels["district_aria"] = f"לידות עסקים לפי מחוז, {dy}"
        labels["district_note"] = (f"לידות העסקים בשנת {dy} בכל מחוז, כאחוז מהעסקים הפעילים בו. "
                                   f"אזור יהודה והשומרון כולל יישובים ישראליים בלבד.")
        most = max(drows, key=lambda d: (d["active"], d["name"]))
        hi, lo = drows[0], drows[-1]
        if hi["rate"] - lo["rate"] >= 1:
            txt = (f"מחוז {hi['name']} מוביל בקצב פתיחת העסקים: {_p(hi['rate'])} מהעסקים בו נולדו בשנת {dy}, "
                   f"ומחוז {lo['name']} נמוך מכולם עם {_p(lo['rate'])}")
            if most["name"] == lo["name"]:
                txt += f", אף שיש בו הכי הרבה עסקים פעילים ({fmt.int_he(most['active'])})"
            add("district", txt + ".")

    # ── VAT openings and closures ────────────────────────────────────────
    flags["vat"] = "vat" in tabs
    if flags["vat"]:
        vt = _vat(tabs["vat"])
        vy = vt["years"][-1]
        o, c, n = vt["total"][vy]
        if None in (o, c):
            raise ValueError("vat: total of the latest year missing")
        n = n if n is not None else o - c
        kpis["vat_net"] = {"value": n, "display": fmt.int_he(n).replace("-", "−"),
                           "tone": "ok" if n > 0 else "danger"}
        labels["vat_net_kpi"] = f"תוספת נטו של תיקי עוסקים במע\"מ ב-{vy} (פתיחות פחות סגירות)"
        vi = sorted(vt["industries"], key=lambda i: (-(i["v"][vy][0] or 0), i["name"]))
        charts["vat"] = {"names": [short(i["name"]) for i in vi],
                         "open": [i["v"][vy][0] for i in vi], "close": [i["v"][vy][1] for i in vi]}
        tables["vat"] = [[i["name"], _n(i["v"][vy][0]), _n(i["v"][vy][1]), _n(i["v"][vy][2])] for i in vi]
        labels["vat_aria"] = f"פתיחות וסגירות של תיקי עוסקים במע\"מ לפי ענף, {vy}"
        labels["vat_note"] = (f"כמה תיקי עוסקים במע\"מ נפתחו וכמה נסגרו בשנת {vy} בכל ענף, לפי מרשם העסקים. "
                              f"בסך הכל נפתחו {fmt.int_he(o)} תיקים ונסגרו {fmt.int_he(c)}.")
        labels["vat_cols"] = ["ענף", "פתיחות", "סגירות", "תוספת נטו"]
        net_txt = (f"תוספת נטו של {fmt.int_he(n)}" if n > 0 else
                   f"ירידה נטו של {fmt.int_he(-n)}" if n < 0 else "ללא שינוי נטו")
        txt = f"בשנת {vy} נפתחו {fmt.int_he(o)} תיקי עוסקים במע\"מ ונסגרו {fmt.int_he(c)}, {net_txt}"
        if len(vt["years"]) >= 2:
            py = vt["years"][-2]
            pn = vt["total"][py][2]
            if pn:
                if n != pn and n > 0 and pn > 0:
                    txt += f" ({'יותר' if n > pn else 'פחות'} מ-{fmt.int_he(pn)} בשנת {py})"
                elif n != pn:
                    prev = (f"תוספת נטו של {fmt.int_he(pn)}" if pn > 0
                            else f"ירידה נטו של {fmt.int_he(-pn)}")
                    txt += f" (לעומת {prev} בשנת {py})"
        lead = max(vi, key=lambda i: ((i["v"][vy][2] or 0), i["name"]))
        if lead["v"][vy][2] and n > 0:
            txt += f". הענף שגדל הכי הרבה: {short(lead['name'])}, עם {fmt.int_he(lead['v'][vy][2])} תיקים נטו"
        add("vat", txt + ".")
        neg = [i for i in vi if (i["v"][vy][2] or 0) < 0]
        if neg:
            labels["vat_neg"] = (f"בשנת {vy} נסגרו יותר תיקים משנפתחו בענפים: "
                                 + fmt.join_he(short(i["name"]) for i in neg) + ".")

    # ── active businesses + employee jobs ────────────────────────────────
    flags["active"] = "active" in tabs
    if flags["active"]:
        ac = _active(tabs["active"])
        tot = ac["total"]
        ay = ac["year"] or ly
        kpis["active"] = {"value": tot["grand"], "display": fmt.int_he(tot["grand"]), "tone": "brand"}
        labels["active_kpi"] = f"עסקים פעילים בישראל ב-{ay}"
        ai = sorted(ac["industries"], key=lambda i: (-(i["grand"] or 0), i["name"]))
        charts["active"] = {"names": [short(i["name"]) for i in ai],
                            "self": [i["self"] for i in ai], "emp": [i["emp"] for i in ai]}
        tables["active"] = [[i["name"], _n(i["grand"]), _n(i["self"]), _n(i["emp"])] for i in ai]
        labels["active_aria"] = f"עסקים פעילים לפי ענף כלכלי, {ay}"
        labels["active_note"] = (f"{fmt.int_he(tot['grand'])} העסקים הפעילים בשנת {ay} לפי ענף: עצמאים וחברות "
                                 f"בלי שכירים, ועסקים מעסיקים.")
        add("self_employed", f"{fmt.pct(tot['self'] / tot['grand'])} מהעסקים הפעילים בשנת {ay} "
                             f"({fmt.int_he(tot['self'])} מתוך {fmt.int_he(tot['grand'])}) הם עצמאים וחברות "
                             f"שאינם מעסיקים שכירים.")
    flags["size"] = False
    if flags["active"] and "jobs" in tabs:
        jb = _jobs(tabs["jobs"])
        jy = jb["year"] or ly
        kpis["jobs"] = {"value": jb["total"], "display": fmt.num_he(jb["total"] / 1000, 2), "tone": "brand"}
        # Scope of the table (jobs at employers classified by industry and
        # size), which sums slightly below the release headline's total.
        labels["jobs_kpi"] = f"משרות שכיר בפילוח לפי ענף וגודל מעסיק, {jy} (מיליונים)"
        if len(jb["sizes"]) == len(ac["sizes"]) and all(v is not None for v in ac["total"]["sizes"]):
            flags["size"] = True
            emp_n = ac["total"]["sizes"]
            se, sj = sum(emp_n), sum(jb["size_vals"])
            charts["size"] = {"names": jb["sizes"],
                              "emp": [_r1(v / se * 100) for v in emp_n],
                              "jobs": [_r1(v / sj * 100) for v in jb["size_vals"]]}
            tables["size"] = [[s, _n(e), _p(e / se * 100), fmt.num_he(j), _p(j / sj * 100)]
                              for s, e, j in zip(jb["sizes"], emp_n, jb["size_vals"])]
            labels["size_aria"] = f"מעסיקים ומשרות שכיר לפי גודל המעסיק, {jy}"
            labels["size_note"] = ("איך מתחלקים המעסיקים ומשרות השכיר לפי גודל המעסיק (מספר משרות השכיר אצלו): "
                                   "אחוז מכלל המעסיקים לעומת אחוז מכלל המשרות.")
            big_e, big_j = emp_n[-1] / se, jb["size_vals"][-1] / sj
            small_e = emp_n[0] / se
            if big_j >= 0.3:
                add("concentration", f"המשרות מרוכזות אצל מעט מעסיקים גדולים: מעסיקים עם {jb['sizes'][-1]} "
                                     f"משרות שכיר הם {fmt.pct(big_e)} בלבד מהמעסיקים, אבל אצלם "
                                     f"{fmt.pct(big_j)} ממשרות השכיר. "
                                     f"{fmt.pct(small_e, 0)} מהמעסיקים מעסיקים {jb['sizes'][0]} שכירים.")
        ji = sorted([i for i in jb["industries"] if i["total"] is not None],
                    key=lambda i: (-i["total"], i["name"]))
        flags["jobs"] = len(ji) >= 3
        if flags["jobs"]:
            bands = _bands(jb["sizes"])
            charts["jobs"] = {"names": [short(i["name"]) for i in ji], "bands": [b[0] for b in bands],
                              "series": [[_r1(sum(i["sizes"][k] or 0 for k in b[1])) for i in ji] for b in bands]}
            tables["jobs"] = [[i["name"], fmt.num_he(i["total"])]
                              + [fmt.num_he(sum(i["sizes"][k] or 0 for k in b[1])) for b in bands] for i in ji]
            labels["jobs_cols"] = ["ענף", "סך משרות שכיר (אלפים)"] + [f"{b[0]} (אלפים)" for b in bands]
            labels["jobs_aria"] = f"משרות שכיר לפי ענף וגודל המעסיק, {jy}"
            labels["jobs_note"] = f"משרות השכיר בשנת {jy} בכל ענף, באלפים, לפי גודל המעסיק."
            top = ji[0]
            add("jobs_lead", f"הענף עם הכי הרבה משרות שכיר בשנת {jy} הוא {short(top['name'])}: "
                             f"{fmt.num_he(top['total'])} אלף משרות, {fmt.pct(top['total'] / jb['total'])} מכלל המשרות.")
    else:
        flags["jobs"] = False

    # ── births by size and the jobs they added ───────────────────────────
    flags["bsize"] = False
    if "bsize" in tabs:
        bs = _bsize(tabs["bsize"])
        bsy = bs["year"] or ly
        bi = sorted([i for i in bs["industries"] if i.get("non") is not None],
                    key=lambda i: (-((i["total"] or 0) + (i["non"] or 0)), i["name"]))
        flags["bsize"] = len(bi) >= 3
        if flags["bsize"]:
            charts["bsize"] = {"names": [short(i["name"]) for i in bi],
                               "non": [i["non"] for i in bi], "emp": [i["total"] for i in bi]}
            tables["bsize"] = [[i["name"], _n(i["non"]), _n(i["total"])] + [_n(v) for v in i["sizes"]]
                               for i in bi]
            labels["bsize_cols"] = (["ענף", "לא מעסיקים", "מעסיקים"]
                                    + [f"{s} משרות שכיר" for s in bs["sizes"]])
            labels["bsize_aria"] = f"לידות עסקים לפי ענף ולפי האם הם מעסיקים שכירים, {bsy}"
            labels["bsize_note"] = (f"העסקים שנולדו בשנת {bsy} בכל ענף: עסקים בלי שכירים לעומת עסקים מעסיקים. "
                                    f"\"..\" בטבלה: נתון חסוי.")
            t = bs["total"]
            if t and t.get("non") is not None and t["total"] is not None:
                all_b = t["non"] + t["total"]
                add("bsize", f"{fmt.pct(t['non'] / all_b)} מהעסקים שנולדו בשנת {bsy} ({fmt.int_he(t['non'])} "
                             f"מתוך {fmt.int_he(all_b)}) לא העסיקו שכירים. מבין העסקים המעסיקים, "
                             f"{fmt.pct(t['sizes'][0] / t['total'])} פתחו עם {bs['sizes'][0]} משרות שכיר.")
    flags["bjobs"] = False
    if "bjobs" in tabs:
        bj = _size_table(tabs["bjobs"], "bjobs", "1-4", "סך משרות שכיר")
        bjy = bj["year"] or ly
        ji = sorted(bj["industries"], key=lambda i: (-i["total"], i["name"]))
        flags["bjobs"] = len(ji) >= 3
        if flags["bjobs"]:
            charts["bjobs"] = {"names": [short(i["name"]) for i in ji], "jobs": [_r1(i["total"]) for i in ji]}
            tables["bjobs"] = [[i["name"], fmt.num_he(i["total"])]
                               + [fmt.num_he(v) if v is not None else ".." for v in i["sizes"]] for i in ji]
            labels["bjobs_cols"] = ["ענף", "סך משרות שכיר"] + [f"{s} משרות שכיר" for s in bj["sizes"]]
            labels["bjobs_aria"] = f"משרות שכיר שנוספו בזכות עסקים שנולדו בשנת {bjy}, לפי ענף"
            labels["bjobs_note"] = (f"כמה משרות שכיר הוסיפו העסקים שנולדו בשנת {bjy}, בכל ענף (ממוצע המשרות "
                                    f"לאורך השנה).")
            top = ji[0]
            txt = f"העסקים שנולדו בשנת {bjy} הוסיפו"
            if bj["total"] and bj["total"]["total"]:
                txt += f" {fmt.int_he(bj['total']['total'])} משרות שכיר. הכי הרבה"
            else:
                txt += " הכי הרבה משרות שכיר"
            txt += f" בענף {short(top['name'])}: {fmt.int_he(top['total'])}"
            if flags["bsize"]:
                b_top = next((i for i in bi if i["name"] == top["name"]), None)
                if b_top and b_top["total"]:
                    txt += (f", כ-{fmt.num_he(top['total'] / b_top['total'])} משרות לכל עסק מעסיק "
                            f"שנולד בענף")
            add("bjobs", txt + ".")

    # The insight card holds the strongest findings; the rest show as a
    # callout in their own chart section.
    by_id = {i["id"]: i for i in insights}
    top_ins = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top_ins}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    act_txt = (f"{fmt.int_he(kpis['active']['value'])} עסקים פעילים, " if "active" in kpis else "")
    labels["lede"] = (f"כמה עסקים נפתחים ונסגרים בישראל, כמה מהם שורדים לאורך השנים ובאילו ענפים ומחוזות. "
                      f"הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על דמוגרפיה של עסקים, "
                      f"ומתעדכנים עם כל הודעה חדשה. בשנת {ly}: {act_txt}{fmt.int_he(b_last)} לידות עסקים, "
                      f"ורק {_p(s_last)} מהעסקים שנולדו ב-{birth} עדיין פעילים.")
    summary = (f"דמוגרפיה של עסקים בישראל לפי הלמ\"ס: {act_txt}{fmt.int_he(b_last)} עסקים חדשים בשנת {ly} "
               f"ושרידות של {_p(s_last)} לעסקים שנולדו ב-{birth}.")
    desc = (f"כמה עסקים נפתחים ונסגרים בישראל ומה סיכויי השרידות: {fmt.int_he(b_last)} עסקים חדשים ב-{ly}, "
            f"{_p(s_last)} שורדים {y_last - birth} שנים. לפי ענף ומחוז.")
    years_all = [birth, ly] + ([ac["year"]] if flags["active"] and ac["year"] else [])
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{min(years_all)}/{max(years_all)}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "שרידות עסקים בישראל: פתיחות וסגירות של עסקים | הלמ\"ס",
                "description": desc,
                "name": "שרידות ותנועות של עסקים בישראל",
                "alternate_names": ["דמוגרפיה של עסקים", "פתיחת וסגירת עסקים בישראל",
                                    "לידות עסקים בישראל", "עסקים פעילים בישראל",
                                    "כמה עסקים נסגרים בישראל"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top_ins,
        "callouts": callouts,
        "labels": labels,
        "release": release,
        "flags": flags,
    }


def _bands(sizes):
    """Group the size columns into three bands for the jobs chart: small
    (<20 jobs), medium, and the open-ended top group."""
    small, mid, big = [], [], []
    for k, s in enumerate(sizes):
        m = SIZE.match(s)
        lo = int(m.group(1))
        if s.endswith("+"):
            big.append(k)
        elif lo < 20:
            small.append(k)
        else:
            mid.append(k)
    out = []
    if small:
        out.append((f"{sizes[small[0]].split('-')[0]}-{sizes[small[-1]].split('-')[-1]} משרות", small))
    if mid:
        out.append((f"{sizes[mid[0]].split('-')[0]}-{sizes[mid[-1]].split('-')[-1]} משרות", mid))
    if big:
        out.append((f"{sizes[big[0]]} משרות", big))
    return out
