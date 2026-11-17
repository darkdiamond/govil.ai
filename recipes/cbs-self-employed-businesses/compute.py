"""עסקים של עצמאים: CBS's yearly "self-employed business demography" release.

The release is a set of Excel tables ("לוח N") and chart-data sheets
("תרשים N"), and their stems MOVE between editions (the 2021 edition had an
education table at t5, so every chart sat one stem later). So every table
input (t1..t24, all optional; three spare stems past the newest edition's
t21) is read edition by edition, and each table is found by its TITLE text:

  l1      לוח: ... מין בעל העסק, ענף כלכלי        counts + women's share by
                                                  industry, employers or not
  l2      לוח: ... קבוצת אוכלוסייה ... ענף כלכלי  Jewish / Arab / other share
  l4      לוח: ... גיל ... ענף כלכלי              age groups + average age
  size    תרשים: בהשוואה לכלל העסקים              employee-size mix vs all
  b_sex   תרשים: ... לידות ... לפי מין             births vs active, by sex
  b_pop   תרשים: ... לידות ... קבוצת אוכלוסייה     births vs active, by group
  b_mar   תרשים: ... לידות ... מצב משפחתי          births vs active, marital
                                                  status, and the births count
  age_ind תרשים: ענפים ... קבוצת גיל (no sex/group) age groups, active vs births

`history_releases` is 4, so l1 (and l4, b_mar) give a yearly series, one
point per edition. The current edition is the newest one whose l1 is found.
A title that is found but whose header labels are gone raises (the layout
changed: a human should look). A table missing from an edition, or data rows
cut short, drops that section.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+")
HEB = re.compile("[א-ת]")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
CODE = re.compile(r"^[A-U](?:\s*[,\-]\s*[A-U])*$")
RELEASE = re.compile(r"(\d+)\s*/\s*(\d{4})")
SIZE = re.compile(r"^\+?(\d+)(?:-(\d+))?\+?$")
# The number must be the one CBS calls self-employed businesses: "עצמאים"
# right after it (an optional "(כ-68%)" and "הם עסקים של" in between).
HEADLINE = re.compile(r"מתוך ([\d,]+) העסקים הפעילים בשנת (\d{4}), ([\d,]+)"
                      r"\s*(?:\([^)]*\))?\s*(?:הם|היו)?\s*(?:עסקים של\s*)?עצמאים")
# Insight card: at most MAX_TOP, by priority; the rest lead their section.
MAX_TOP = 8

# Short industry names for chart axes, by CBS section code; an unknown code
# falls back to the name up to its first comma or semicolon.
SHORT = {
    "A": "חקלאות", "B,C": "תעשייה וכרייה", "D,E": "חשמל, מים ופסולת", "F": "בינוי",
    "G": "מסחר ותיקון רכב", "H": "תחבורה ואחסנה", "I": "אירוח ואוכל", "J": "מידע ותקשורת",
    "K": "פיננסים וביטוח", "L": "נדל\"ן", "M": "שירותים מקצועיים", "N": "ניהול ותמיכה",
    "P": "חינוך", "Q": "בריאות ורווחה", "R": "אמנות ופנאי", "O,S-U": "שירותים אחרים",
}
SEXES = ("גברים", "נשים")
GROUPS = ("יהודים", "ערבים", "אחרים")
MARITAL = ("רווקים", "נשואים", "גרושים", "אלמנים")
BIG_INDUSTRY = 1000  # growth ranking only over industries this large in the first year


# ── locating tables ──────────────────────────────────────────────────────


def _rkey(no):
    m = RELEASE.search(str(no))
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    lauach = t.startswith("לוח")
    if lauach and "ענף" in t:
        if "מין בעל העסק" in t:
            return "l1"
        if "קבוצת אוכלוסייה" in t:
            return "l2"
        if "גיל" in t:
            return "l4"
        return None
    if lauach:
        return None
    if "בהשוואה לכלל העסקים" in t:
        return "size"
    if "לידות" in t and "ענפים" not in t:
        if "לפי מין" in t:
            return "b_sex"
        if "קבוצת אוכלוסייה" in t:
            return "b_pop"
        if "מצב משפחתי" in t:
            return "b_mar"
    if "ענפים" in t and "קבוצת גיל" in t and "מין" not in t and "אוכלוסייה" not in t:
        return "age_ind"
    return None


def _editions(frames):
    """{release_no: {kind: rows}}, first match by stem number wins."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        for rel in sorted(df["RELEASE_NO"].unique(), key=lambda r: (_rkey(r), str(r))):
            rows = cbs.grid(df[df["RELEASE_NO"] == rel], n)
            k = _kind(_title(rows))
            if k and k not in out.setdefault(rel, {}):
                out[rel][k] = rows
    return out


# ── small helpers ────────────────────────────────────────────────────────


def _cols(row, label, contains=False):
    return [j for j, c in enumerate(row) if ((label in c) if contains else (c == label))]


def _pct100(values):
    """Shares on 0-100 whatever scale the sheet used (fractions or percents)."""
    vals = [v for v in values if v is not None]
    if vals and max(vals) <= 1.0001:
        return [None if v is None else v * 100 for v in values]
    return list(values)


def _r1(v):
    return None if v is None else round(v, 1)


def _p(v, d=1):
    return "" if v is None else fmt.pct_of(v, d)


def _industry_rows(rows, start):
    """[(code, name, row)] after `start`: a section code in column 0 and a
    Hebrew name in column 1."""
    out = []
    for r in rows[start:]:
        code = re.sub(r"\s+", "", cbs.cell(r, 0))
        name = cbs.cell(r, 1)
        if CODE.match(code) and HEB.search(name):
            out.append((code, name, r))
    return out


def _short(code, name):
    if code in SHORT:
        return SHORT[code]
    return re.split(r"[,;]", name)[0].strip()


def _size_label(c):
    """'4-1' / '1-4 משרות שכיר' → '1-4', '+20' → '20+', None otherwise."""
    m = SIZE.match(c.replace(" משרות שכיר", "").strip())
    if not m:
        return None
    a, b = int(m.group(1)), m.group(2)
    if b is None:
        return f"{a}+"
    lo, hi = sorted((a, int(b)))
    return f"{lo}-{hi}"


def _total_row(rows, start):
    for r in rows[start:]:
        if cbs.cell(r, 0) == "סך הכל":
            return r
    return None


# ── table parsers ────────────────────────────────────────────────────────


def _l1(rows):
    """{'total', 'emp', 'non': {count, women}} + industries + employer sizes."""
    h = cbs.row_with(rows, "בבעלות נשים", name="l1")
    tots = _cols(rows[h], "סך הכל")
    if len(tots) < 3:
        raise ValueError("l1: three 'סך הכל' columns not found")
    bh = next((i for i in range(h, -1, -1) if any(c.startswith("לא מעסיקים") for c in rows[i])), None)
    if bh is None:
        raise ValueError("l1: 'לא מעסיקים' block header not found")
    blocks = {}
    for j, c in enumerate(rows[bh]):
        if not c:
            continue
        if c.startswith("לא מעסיקים"):
            blocks["non"] = j
        elif c.startswith("מעסיקים"):
            blocks["emp"] = j
        elif c.startswith("סך"):
            blocks["total"] = j
    if set(blocks) != {"total", "emp", "non"} or sorted(blocks.values()) != tots[:3]:
        raise ValueError("l1: block headers don't line up with the 'סך הכל' columns")
    wcol = {b: cbs.col_after(rows[h], "בבעלות נשים", j) for b, j in blocks.items()}
    tr = _total_row(rows, h + 1)
    if tr is None:
        raise ValueError("l1: 'סך הכל' total row not found")

    def block(r):
        return {b: {"count": cbs.val(r, j), "women": cbs.val(r, wcol[b])} for b, j in blocks.items()}

    total = block(tr)
    if total["total"]["count"] is None:
        raise ValueError("l1: no total count")
    inds = [(code, name, block(r)) for code, name, r in _industry_rows(rows, h + 1)]
    sizes = []
    for r in rows[h + 1:]:
        lab = _size_label(cbs.cell(r, 0))
        v = cbs.val(r, blocks["emp"])
        if lab and v is not None:
            sizes.append((lab, v))
    return total, inds, sizes


def _l2(rows):
    h = cbs.row_with(rows, "בבעלות ערבים", name="l2")
    tots = _cols(rows[h], "סך הכל")
    if len(tots) < 3:
        raise ValueError("l2: three 'סך הכל' columns not found")
    cols = {g: [cbs.col_after(rows[h], f"בבעלות {g}", t) for t in tots[:3]] for g in GROUPS}

    def block(r, k):
        return [cbs.val(r, cols[g][k]) for g in GROUPS]

    tr = _total_row(rows, h + 1)
    if tr is None:
        raise ValueError("l2: 'סך הכל' total row not found")
    total = {b: block(tr, k) for k, b in enumerate(("total", "emp", "non"))}
    inds = [(code, name, cbs.val(r, tots[0]), block(r, 0)) for code, name, r in _industry_rows(rows, h + 1)]
    return total, inds


def _l4(rows):
    h = next((i for i, r in enumerate(rows)
              if any("גיל ממוצע" in c for c in r) and "סך הכל" in r), None)
    if h is None:
        raise ValueError("l4: 'גיל ממוצע' header not found")
    avg = _cols(rows[h], "גיל ממוצע", contains=True)
    tots = _cols(rows[h], "סך הכל")
    if not avg or not tots or tots[0] > avg[0]:
        raise ValueError("l4: 'סך הכל' / 'גיל ממוצע' columns not found")
    groups = [(j, rows[h][j]) for j in range(tots[0] + 1, avg[0]) if rows[h][j]]
    tr = _total_row(rows, h + 1)
    if tr is None:
        raise ValueError("l4: 'סך הכל' total row not found")
    blocks = []
    for k, a in enumerate(avg[:3]):
        t = max((j for j in tots if j < a), default=None)
        n = len(groups)
        shares = _pct100([cbs.val(tr, t + 1 + i) for i in range(n)]) if t is not None and n else []
        blocks.append({"avg": cbs.val(tr, a), "shares": shares})
    inds = []
    for code, name, r in _industry_rows(rows, h + 1):
        v = cbs.val(r, avg[0])
        if v is not None:
            sh = _pct100([cbs.val(r, j) for j, _ in groups])
            inds.append((code, name, v, sh))
    return [g for _, g in groups], blocks, inds


def _size(rows):
    h = next((i for i, r in enumerate(rows) if "כלל העסקים" in r), None)
    if h is None:
        _check_cut(rows, "size: 'כלל העסקים' header")
        return []
    ca = cbs.col_after(rows[h], "כלל העסקים", 0)
    cs = cbs.col_after(rows[h], "עצמא", 0, contains=True)
    out = []
    for r in rows[h + 1:]:
        raw = cbs.cell(r, min(ca, cs) - 1)
        a, s = cbs.val(r, ca), cbs.val(r, cs)
        if not raw or a is None or s is None:
            continue
        lab = "ללא שכירים" if raw.startswith(("לא", "ללא")) else _size_label(raw)
        if lab:
            out.append((lab, s, a))
    if len(out) < 2:
        return []
    ss = _pct100([s for _, s, _ in out])
    aa = _pct100([a for _, _, a in out])
    return [(lab, ss[i], aa[i]) for i, (lab, _, _) in enumerate(out)]


def _check_cut(rows, what):
    """A header label is gone. Raise when the table still has numbers (its
    layout changed); a table cut short before its numbers just drops."""
    if any(cbs.num(c) is not None for r in rows for c in r):
        raise ValueError(f"{what} not found")


def _pairs_inline(rows, labels, name):
    """Each label on its own row, twice (active block, births block), its
    value in the next cell."""
    out = {}
    for r in rows:
        for lab in labels:
            js = _cols(r, lab)
            if len(js) >= 2 and lab not in out:
                a, b = cbs.val(r, js[0] + 1), cbs.val(r, js[1] + 1)
                if a is not None and b is not None:
                    out[lab] = (a, b)
    if len(out) < len(labels):
        return None
    return _scaled(out, labels)


def _pairs_header(rows, labels, name):
    """The labels across one header row, twice; the values in a row below."""
    h = next((i for i, r in enumerate(rows) if all(len(_cols(r, lab)) >= 2 for lab in labels)), None)
    if h is None:
        _check_cut(rows, f"{name}: header row with {labels} twice")
        return None
    ca = {lab: _cols(rows[h], lab)[0] for lab in labels}
    cb = {lab: _cols(rows[h], lab)[1] for lab in labels}
    for r in rows[h + 1:h + 4]:
        a = {lab: cbs.val(r, ca[lab]) for lab in labels}
        b = {lab: cbs.val(r, cb[lab]) for lab in labels}
        if all(v is not None for v in a.values()) and all(v is not None for v in b.values()):
            return _scaled({lab: (a[lab], b[lab]) for lab in labels}, labels)
    return None


def _scaled(pairs, labels):
    a = _pct100([pairs[lab][0] for lab in labels])
    b = _pct100([pairs[lab][1] for lab in labels])
    return {lab: (a[i], b[i]) for i, lab in enumerate(labels)}


def _births_count(rows):
    """The count under the 'לידות עסקים' cell of the marital-status chart."""
    for i, r in enumerate(rows):
        for j, c in enumerate(r):
            if c.startswith("לידות עסקים"):
                for r2 in rows[i + 1:i + 6]:
                    v = cbs.val(r2, j)
                    if v is not None and v > 100:
                        return v
                return None
    return None


def _age_ind(rows):
    """{'active': shares, 'births': shares} of the all-industries row, plus
    the age-group labels, from the blocks headed by an '18-34' row."""
    heads = [i for i, r in enumerate(rows) if "18-34" in r]
    if not heads:
        _check_cut(rows, "age_ind: '18-34' header")
        return None
    out, labels = {}, None
    for h in heads:
        j0 = rows[h].index("18-34")
        labs = []
        for c in rows[h][j0:]:
            if not c:
                break
            labs.append(c)
        births = any("לידות" in c for r in rows[max(0, h - 3):h] for c in r)
        kind = "births" if births else "active"
        if kind in out:
            continue
        for r in rows[h + 1:]:
            if "18-34" in r:
                break
            if any(c == 'סה"כ' or "סך הענפים" in c for c in r):
                vals = [cbs.val(r, j0 + k) for k in range(len(labs))]
                if all(v is not None for v in vals):
                    out[kind] = _pct100(vals)
                    labels = labels or labs
                break
    if "active" not in out or "births" not in out:
        return None
    return labels, out


# ── compute ──────────────────────────────────────────────────────────────


def _chg_word(c):
    """'עלייה של 2.1%' / 'ירידה של …', or 'ללא שינוי' when it rounds to zero."""
    if abs(c) < 0.0005:
        return "ללא שינוי"
    return f"{'עלייה' if c > 0 else 'ירידה'} של {fmt.pct(abs(c))}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def compute(frames):
    eds = _editions(frames)
    hist_rel = sorted((r for r in eds if "l1" in eds[r]), key=lambda r: (_rkey(r), str(r)))
    if not hist_rel:
        raise ValueError("table 1 (עסקים פעילים לפי מין בעל העסק וענף) not found in any edition")
    cur_rel = hist_rel[-1]
    cur = eds[cur_rel]
    year_of = {}
    for r in hist_rel:
        ys = [int(y) for y in YEAR_IN.findall(_title(eds[r]["l1"]))]
        if not ys:
            raise ValueError(f"l1 of {r}: no year in the title")
        year_of[r] = ys[-1]
    # One point per data year; a later edition wins a repeated year.
    by_year = {}
    for r in hist_rel:
        by_year[year_of[r]] = r
    years = sorted(by_year)
    ly = year_of[cur_rel]

    l1 = {y: _l1(eds[by_year[y]]["l1"]) for y in years}
    total, inds, sizes = l1[ly]
    l4h = {y: _l4(eds[by_year[y]]["l4"]) for y in years if "l4" in eds[by_year[y]]}
    births_h = {}
    for y in years:
        rr = eds[by_year[y]].get("b_mar")
        if rr is not None:
            b = _births_count(rr)
            if b is not None:
                births_h[y] = b

    rel_df = frames["releases"]
    match = rel_df[rel_df["RELEASE_NO"] == cur_rel]
    rel = match.iloc[0].to_dict() if len(match) else cbs.latest_release(rel_df)

    kpis, labels, charts, tables, flags, callouts = {}, {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    n_tot = total["total"]["count"]
    n_emp = total["emp"]["count"]
    n_non = total["non"]["count"]
    w_tot = total["total"]["women"]

    # ── trend ────────────────────────────────────────────────────────────
    tr = {y: l1[y][0] for y in years}
    charts["trend"] = {"x": [str(y) for y in years],
                       "emp": [tr[y]["emp"]["count"] for y in years],
                       "non": [tr[y]["non"]["count"] for y in years]}
    avg_h = {y: l4h[y][1][0]["avg"] for y in l4h if l4h[y][1] and l4h[y][1][0]["avg"] is not None}
    tables["trend"] = [[str(y), fmt.int_he(tr[y]["total"]["count"]),
                        fmt.int_he(tr[y]["emp"]["count"]) if tr[y]["emp"]["count"] is not None else "",
                        fmt.int_he(tr[y]["non"]["count"]) if tr[y]["non"]["count"] is not None else "",
                        _p(tr[y]["total"]["women"]),
                        fmt.int_he(births_h[y]) if y in births_h else "",
                        fmt.num_he(avg_h[y], 1) if y in avg_h else ""]
                       for y in reversed(years)]
    labels["trend_note"] = (f"מספר העסקים הפעילים של עצמאים בכל שנה, {years[0]} עד {ly}, "
                            f"לפי עסקים שמעסיקים שכירים ועסקים שאינם מעסיקים."
                            if len(years) > 1 else
                            f"מספר העסקים הפעילים של עצמאים ב-{ly}, לפי עסקים שמעסיקים שכירים "
                            f"ועסקים שאינם מעסיקים.")
    labels["trend_aria"] = f"עסקים פעילים של עצמאים לפי שנה, {years[0]} עד {ly}"

    prev_y = years[-2] if len(years) >= 2 else None
    c_prev = _chg(n_tot, tr[prev_y]["total"]["count"]) if prev_y else None
    kpis["total"] = {"value": int(n_tot), "display": fmt.int_he(n_tot), "tone": "brand"}
    labels["total_kpi"] = f"עסקים פעילים של עצמאים, {ly}"
    if c_prev is not None:
        kpis["change"] = {"value": round(c_prev * 100, 1), "display": fmt.signed_pct(c_prev),
                          "tone": "ok" if c_prev >= 0.005 else "danger" if c_prev <= -0.005 else "brand"}
        labels["change_kpi"] = f"שינוי במספר העסקים לעומת {prev_y}"
        first = years[0]
        c_first = _chg(n_tot, tr[first]["total"]["count"])
        txt = (f"ב-{ly} פעלו בישראל {fmt.int_he(n_tot)} עסקים של עצמאים, "
               f"{_chg_word(c_prev)} לעומת {prev_y}")
        if first != prev_y and c_first is not None:
            txt += (f" ו{_chg_word(c_first)} לעומת "
                    f"{first} ({fmt.int_he(tr[first]['total']['count'])} עסקים)")
        add("trend", txt + ".")
    if n_non is not None and n_tot:
        s_non = n_non / n_tot
        kpis["non"] = {"value": round(s_non * 100, 1), "display": fmt.pct(s_non), "tone": "brand"}
        labels["non_kpi"] = f"מהעסקים אינם מעסיקים שכירים, {ly}"
        if prev_y and n_emp is not None:
            pe, pn = tr[prev_y]["emp"]["count"], tr[prev_y]["non"]["count"]
            ce, cn = _chg(n_emp, pe), _chg(n_non, pn)
            if ce is not None and cn is not None and ce * cn < 0 and abs(ce) >= 0.005 and abs(cn) >= 0.005:
                add("emp", f"{fmt.pct(s_non)} מהעסקים של עצמאים אינם מעסיקים שכירים. ב-{ly} מספר "
                           f"העסקים המעסיקים {'עלה' if ce > 0 else 'ירד'} ב-{fmt.pct(abs(ce))} "
                           f"(ל-{fmt.int_he(n_emp)}), ואילו מספר העסקים שאינם מעסיקים "
                           f"{'עלה' if cn > 0 else 'ירד'} ב-{fmt.pct(abs(cn))} (ל-{fmt.int_he(n_non)}).")
    if w_tot is not None:
        kpis["women"] = {"value": round(w_tot, 1), "display": _p(w_tot), "tone": "info"}
        labels["women_kpi"] = f"מהעסקים בבעלות נשים, {ly}"
    if births_h.get(ly) is not None:
        b = births_h[ly]
        bp = births_h.get(prev_y) if prev_y else None
        cb = _chg(b, bp)
        kpis["births"] = {"value": int(b), "display": fmt.int_he(b),
                          "tone": "warn" if cb is not None and cb <= -0.05 else "brand"}
        labels["births_kpi"] = f"עסקים חדשים של עצמאים (לידות עסקים), {ly}"
    l4c = l4h.get(ly)
    if l4c and l4c[1] and l4c[1][0]["avg"] is not None:
        kpis["age"] = {"value": round(l4c[1][0]["avg"], 1), "display": fmt.num_he(l4c[1][0]["avg"], 1),
                       "tone": "brand"}
        labels["age_kpi"] = f"גיל ממוצע של בעל העסק, {ly}"

    # ── births ───────────────────────────────────────────────────────────
    by = [y for y in years if y in births_h]
    flags["births"] = len(by) >= 2
    if flags["births"]:
        rate = [births_h[y] / tr[y]["total"]["count"] * 100 for y in by]
        charts["births"] = {"x": [str(y) for y in by], "births": [int(births_h[y]) for y in by],
                            "rate": [round(v, 2) for v in rate]}
        tables["births"] = [[str(y), fmt.int_he(births_h[y]), fmt.pct_of(rate[i])]
                            for i, y in reversed(list(enumerate(by)))]
        labels["births_note"] = (f"עסקים חדשים של עצמאים שנפתחו בכל שנה (לידות עסקים), "
                                 f"{by[0]} עד {by[-1]}, ושיעורם מתוך העסקים הפעילים באותה שנה.")
        labels["births_aria"] = f"לידות עסקים של עצמאים לפי שנה, {by[0]} עד {by[-1]}"
        peak = max(by, key=lambda y: (births_h[y], y))
        last = by[-1]
        if last == ly:
            txt = (f"ב-{ly} נפתחו {fmt.int_he(births_h[ly])} עסקים חדשים של עצמאים, "
                   f"{fmt.pct_of(rate[-1])} ממספר העסקים הפעילים")
            if peak != last and births_h[peak] > births_h[last] * 1.05:
                txt += (f". זה פחות מהשיא בתקופה, {fmt.int_he(births_h[peak])} עסקים חדשים "
                        f"ב-{peak}")
            add("births", txt + ".")

    # ── industries ───────────────────────────────────────────────────────
    ind_ok = [(c, n, b) for c, n, b in inds if b["total"]["count"] is not None]
    flags["industry"] = len(ind_ok) >= 3
    if flags["industry"]:
        srt = sorted(ind_ok, key=lambda x: (-x[2]["total"]["count"], x[0]))
        charts["industry"] = {"names": [_short(c, n) for c, n, _ in srt],
                              "emp": [b["emp"]["count"] for _, _, b in srt],
                              "non": [b["non"]["count"] for _, _, b in srt]}
        tables["industry"] = [[n, fmt.int_he(b["total"]["count"]),
                               fmt.pct_of(b["total"]["count"] / n_tot * 100),
                               fmt.int_he(b["emp"]["count"]) if b["emp"]["count"] is not None else "",
                               fmt.int_he(b["non"]["count"]) if b["non"]["count"] is not None else ""]
                              for c, n, b in srt]
        labels["industry_note"] = (f"מספר העסקים הפעילים של עצמאים בכל ענף כלכלי ב-{ly}, "
                                   f"לפי עסקים מעסיקים ולא מעסיקים.")
        labels["industry_aria"] = f"עסקים של עצמאים לפי ענף כלכלי, {ly}"
        _, top_n, top_b = srt[0]
        second = srt[1]
        add("industry", f"הענף הגדול ביותר הוא {top_n}: {fmt.int_he(top_b['total']['count'])} עסקים, "
                        f"{fmt.pct(top_b['total']['count'] / n_tot)} מכלל העסקים של עצמאים. אחריו "
                        f"{second[1]}, עם {fmt.int_he(second[2]['total']['count'])} עסקים.")
        # employers' share by industry: who employs the most
        emp_share = [(c, n, b["emp"]["count"] / b["total"]["count"] * 100) for c, n, b in ind_ok
                     if b["emp"]["count"] is not None and b["total"]["count"] >= BIG_INDUSTRY]
        if len(emp_share) >= 3 and n_emp is not None:
            hi = max(emp_share, key=lambda x: (x[2], x[0]))
            lo = min(emp_share, key=lambda x: (x[2], x[0]))
            overall = n_emp / n_tot * 100
            if hi[2] - lo[2] >= 20:
                add("employers", f"רק {fmt.pct_of(overall)} מהעסקים של עצמאים מעסיקים שכירים, אבל "
                                 f"השיעור משתנה מאוד בין הענפים: {fmt.pct_of(hi[2])} בענף {_short(*hi[:2])} "
                                 f"לעומת {fmt.pct_of(lo[2])} בענף {_short(*lo[:2])}.")

    # ── industry growth since the first year ─────────────────────────────
    flags["growth"] = False
    if len(years) >= 2 and flags["industry"]:
        y0 = years[0]
        base = {c: b["total"]["count"] for c, _, b in l1[y0][1] if b["total"]["count"]}
        rows_g = []
        for c, n, b in ind_ok:
            if c in base and base[c] >= BIG_INDUSTRY:
                rows_g.append((c, n, base[c], b["total"]["count"], b["total"]["count"] / base[c] - 1))
        if len(rows_g) >= 3:
            flags["growth"] = True
            rows_g.sort(key=lambda x: (-x[4], x[0]))
            charts["growth"] = {"names": [_short(c, n) for c, n, *_ in rows_g],
                                "values": [round(g * 100, 1) for *_, g in rows_g]}
            tables["growth"] = [[n, fmt.int_he(a), fmt.int_he(z), fmt.signed_pct(g)]
                                for c, n, a, z, g in rows_g]
            labels["growth_cols"] = ["ענף", str(y0), str(ly), "שינוי"]
            labels["growth_note"] = (f"השינוי באחוזים במספר העסקים של עצמאים בכל ענף, מ-{y0} עד {ly}. "
                                     f"ענפים עם פחות מ-{fmt.int_he(BIG_INDUSTRY)} עסקים ב-{y0} אינם מוצגים.")
            labels["growth_aria"] = f"שינוי במספר העסקים של עצמאים לפי ענף, {y0} עד {ly}"
            g_all = _chg(n_tot, tr[y0]["total"]["count"])
            top, bot = rows_g[0], rows_g[-1]
            if g_all is not None and top[4] - g_all >= 0.05:
                txt = (f"מ-{y0} עד {ly} גדל ענף {_short(top[0], top[1])} יותר מכל ענף אחר: "
                       f"{fmt.signed_pct(top[4])}, לעומת {fmt.signed_pct(g_all)} בכלל העסקים")
                if bot[4] < 0:
                    txt += f". בענף {_short(bot[0], bot[1])} מספר העסקים ירד ({fmt.signed_pct(bot[4])})"
                add("growth", txt + ".")

    # ── women ────────────────────────────────────────────────────────────
    ind_w = [(c, n, b["total"]["women"]) for c, n, b in ind_ok if b["total"]["women"] is not None]
    flags["women"] = len(ind_w) >= 3 and w_tot is not None
    if flags["women"]:
        ws = sorted(ind_w, key=lambda x: (-x[2], x[0]))
        charts["women"] = {"names": [_short(c, n) for c, n, _ in ws], "values": [_r1(v) for *_, v in ws],
                           "overall": _r1(w_tot)}
        tables["women"] = [[n, _p(v), _p(100 - v)] for c, n, v in ws]
        labels["women_note"] = (f"החלק של עסקים בבעלות נשים בכל ענף ב-{ly}. הקו המקווקו: "
                                f"כלל העסקים ({_p(w_tot)}).")
        labels["women_aria"] = f"עסקים של עצמאים בבעלות נשים לפי ענף, {ly}"
        top, bot = ws[0], ws[-1]
        maj = [x for x in ws if x[2] >= 50.5]
        txt = f"{_p(w_tot)} מהעסקים של עצמאים בבעלות נשים. "
        if maj:
            txt += (f"נשים הן רוב בעלי העסקים ב{fmt.join_he(['ענף ' + _short(c, n) for c, n, _ in maj])}"
                    f" (בראש: {_short(top[0], top[1])}, {_p(top[2])})")
        else:
            txt += f"השיעור הגבוה ביותר בענף {_short(top[0], top[1])}: {_p(top[2])}"
        txt += f", והנמוך ביותר בענף {_short(bot[0], bot[1])}: {_p(bot[2])}."
        add("women", txt)
        we, wn = total["emp"]["women"], total["non"]["women"]
        w0 = tr[years[0]]["total"]["women"]
        if we is not None and wn is not None and wn - we >= 3:
            txt = (f"בעסקים שאינם מעסיקים שכירים {_p(wn)} מהבעלים הן נשים, לעומת {_p(we)} בלבד "
                   f"בעסקים המעסיקים")
            if len(years) >= 2 and w0 is not None and abs(w_tot - w0) >= 0.5:
                txt += (f". חלקן של הנשים בכלל העסקים {'עלה' if w_tot > w0 else 'ירד'} מ-{_p(w0)} "
                        f"ב-{years[0]} ל-{_p(w_tot)} ב-{ly}")
            add("women_emp", txt + ".")

    # ── size vs all businesses ───────────────────────────────────────────
    size = _size(cur["size"]) if "size" in cur else []
    flags["size"] = len(size) >= 2
    if flags["size"]:
        charts["size"] = {"names": [lab for lab, _, _ in size], "self": [_r1(s) for _, s, _ in size],
                          "all": [_r1(a) for _, _, a in size]}
        cnt = dict(sizes)
        if n_non is not None:
            cnt["ללא שכירים"] = n_non
        tables["size"] = [[lab, fmt.int_he(cnt[lab]) if lab in cnt else "", _p(s), _p(a)]
                          for lab, s, a in size]
        labels["size_note"] = (f"איך מתחלקים העסקים לפי מספר משרות השכיר שהם מעסיקים ב-{ly}: עסקים של "
                               f"עצמאים לעומת כלל העסקים במשק, באחוזים.")
        labels["size_aria"] = f"עסקים של עצמאים וכלל העסקים לפי קבוצת גודל, {ly}"
        none = next((x for x in size if x[0] == "ללא שכירים"), None)
        big = size[-1]
        if none and none[1] - none[2] >= 5:
            add("size", f"{_p(none[1])} מהעסקים של עצמאים אינם מעסיקים שכירים, לעומת {_p(none[2])} "
                        f"מכלל העסקים במשק. רק {_p(big[1], 2)} מהם מעסיקים {big[0]} משרות שכיר, לעומת "
                        f"{_p(big[2])} מכלל העסקים.")

    # ── population group ─────────────────────────────────────────────────
    flags["pop"] = False
    pop_total = None
    if "l2" in cur:
        pop_total, pop_inds = _l2(cur["l2"])
        pi = [(c, n, v) for c, n, cnt, v in pop_inds if cnt is not None and v[1] is not None]
        flags["pop"] = len(pi) >= 3
        if flags["pop"]:
            ps = sorted(pi, key=lambda x: (-x[2][1], x[0]))
            charts["pop"] = {"names": [_short(c, n) for c, n, _ in ps],
                             "series": [[_r1(v[k]) for *_, v in ps] for k in range(len(GROUPS))],
                             "groups": list(GROUPS)}
            tables["pop"] = [[n] + [_p(x) for x in v] for c, n, v in ps]
            labels["pop_note"] = (f"החלק של בעלי עסקים יהודים, ערבים ואחרים בכל ענף ב-{ly}, באחוזים. "
                                  f"ענפים שבהם הלמ\"ס לא פרסמה את הפילוח מטעמי חיסיון אינם מוצגים.")
            labels["pop_aria"] = f"עסקים של עצמאים לפי קבוצת אוכלוסייה וענף, {ly}"
            ta = pop_total["total"][1]
            ea, na = pop_total["emp"][1], pop_total["non"][1]
            top = ps[0]
            if ta is not None and ea is not None and na is not None and ea - na >= 5:
                add("pop", f"בעלי עסקים ערבים הם {_p(ta)} מהעסקים של עצמאים, אבל {_p(ea)} מהעסקים "
                           f"המעסיקים שכירים (לעומת {_p(na)} מהלא מעסיקים). השיעור הגבוה ביותר בענף "
                           f"{_short(top[0], top[1])}: {_p(top[2][1])}.")

    # ── age ──────────────────────────────────────────────────────────────
    flags["age"] = False
    flags["age_ind"] = False
    if l4c:
        groups, blocks, a_inds = l4c
        if len(groups) >= 3 and len(blocks) >= 3 and all(len(b["shares"]) == len(groups) for b in blocks[:3]):
            flags["age"] = True
            charts["age"] = {"groups": groups, "emp": [_r1(v) for v in blocks[1]["shares"]],
                             "non": [_r1(v) for v in blocks[2]["shares"]],
                             "all": [_r1(v) for v in blocks[0]["shares"]]}
            tables["age"] = [[g, _p(blocks[0]["shares"][i]), _p(blocks[1]["shares"][i]),
                              _p(blocks[2]["shares"][i])] for i, g in enumerate(groups)]
            labels["age_note"] = (f"התפלגות בעלי העסקים לפי גיל ב-{ly}, בעסקים מעסיקים ובעסקים שאינם "
                                  f"מעסיקים שכירים, באחוזים.")
            labels["age_aria"] = f"עסקים של עצמאים לפי גיל בעל העסק, {ly}"
            old = next((i for i, g in enumerate(groups) if g.endswith("+")), None)
            if old is not None and blocks[0]["shares"][old] is not None and blocks[0]["avg"] is not None:
                add("age", f"הגיל הממוצע של בעל עסק עצמאי הוא {fmt.num_he(blocks[0]['avg'], 1)}, "
                           f"ו-{_p(blocks[0]['shares'][old])} מבעלי העסקים בני {groups[old]}.")
        ai = [(c, n, v, sh) for c, n, v, sh in a_inds if v is not None]
        if len(ai) >= 3:
            flags["age_ind"] = True
            asrt = sorted(ai, key=lambda x: (-x[2], x[0]))
            charts["age_ind"] = {"names": [_short(c, n) for c, n, *_ in asrt],
                                 "values": [round(v, 1) for _, _, v, _ in asrt],
                                 "overall": round(blocks[0]["avg"], 1) if blocks and blocks[0]["avg"] else None}
            tables["age_ind"] = [[n, fmt.num_he(v, 1)] for c, n, v, _ in asrt]
            labels["age_ind_note"] = f"הגיל הממוצע של בעלי העסקים בכל ענף ב-{ly}."
            labels["age_ind_aria"] = f"גיל ממוצע של בעל העסק לפי ענף, {ly}"
            o, y_ = asrt[0], asrt[-1]
            old = next((i for i, g in enumerate(groups) if g.endswith("+")), None)
            if o[2] - y_[2] >= 8:
                txt = (f"הענף המבוגר ביותר הוא {_short(o[0], o[1])}: גיל ממוצע {fmt.num_he(o[2], 1)}")
                if old is not None and len(o[3]) > old and o[3][old] is not None and o[3][old] >= 25:
                    txt += f", ו-{_p(o[3][old])} מבעלי העסקים בו בני {groups[old]}"
                txt += f". הצעיר ביותר: {_short(y_[0], y_[1])}, גיל ממוצע {fmt.num_he(y_[2], 1)}."
                add("age_ind", txt)

    # ── who opens a business: births vs active ───────────────────────────
    cmp_rows = []
    if "b_sex" in cur:
        p = _pairs_inline(cur["b_sex"], SEXES, "b_sex")
        if p:
            cmp_rows += [("מין", lab, *p[lab]) for lab in SEXES]
    if "b_pop" in cur:
        p = _pairs_header(cur["b_pop"], GROUPS, "b_pop")
        if p:
            cmp_rows += [("קבוצת אוכלוסייה", lab, *p[lab]) for lab in GROUPS]
    age_b = _age_ind(cur["age_ind"]) if "age_ind" in cur else None
    if age_b:
        labs, ab = age_b
        cmp_rows += [("גיל", f"בני {lab}", ab["active"][i], ab["births"][i]) for i, lab in enumerate(labs)]
    if "b_mar" in cur:
        p = _pairs_header(cur["b_mar"], MARITAL, "b_mar")
        if p:
            cmp_rows += [("מצב משפחתי", lab, *p[lab]) for lab in MARITAL]
    flags["births_cmp"] = len(cmp_rows) >= 4
    if flags["births_cmp"]:
        charts["births_cmp"] = {"names": [lab for _, lab, _, _ in cmp_rows],
                                "active": [_r1(a) for *_, a, _ in cmp_rows],
                                "births": [_r1(b) for *_, b in cmp_rows]}
        tables["births_cmp"] = [[f"{g}: {lab}", _p(a), _p(b)] for g, lab, a, b in cmp_rows]
        labels["births_cmp_note"] = (f"מי פותח עסק חדש: החלק של כל קבוצה מבין העסקים החדשים (לידות עסקים) "
                                     f"ב-{ly}, לעומת חלקה מבין כל העסקים הפעילים, באחוזים.")
        labels["births_cmp_aria"] = f"עסקים פעילים ולידות עסקים של עצמאים לפי מאפייני בעל העסק, {ly}"
        if age_b:
            labs, ab = age_b
            ya, yb = ab["active"][0], ab["births"][0]
            if yb - ya >= 5:
                txt = (f"העסקים החדשים צעירים בהרבה: {_p(yb)} מבעלי העסקים שנפתחו ב-{ly} בני {labs[0]}, "
                       f"לעומת {_p(ya)} מכלל בעלי העסקים")
                ar = next((r for r in cmp_rows if r[1] == "ערבים"), None)
                if ar and ar[3] - ar[2] >= 3:
                    txt += (f". גם בעלי עסקים ערבים בולטים יותר בין החדשים: {_p(ar[3])} מהעסקים החדשים, "
                            f"לעומת {_p(ar[2])} מכלל העסקים")
                add("births_cmp", txt + ".")

    # ── headline (only some editions carry one) ──────────────────────────
    hl = str(rel.get("HEADLINE") or "").strip()
    m = HEADLINE.search(hl)
    if m:
        all_b, hy, se = int(m.group(1).replace(",", "")), int(m.group(2)), int(m.group(3).replace(",", ""))
        # Cross-check against the table's own total before quoting it.
        if all_b and hy == ly and se < all_b and abs(se - n_tot) <= max(50, n_tot * 0.01):
            add("share_all", f"לפי הלמ\"ס, {fmt.int_he(se)} מתוך {fmt.int_he(all_b)} העסקים הפעילים "
                             f"במשק ב-{ly} ({fmt.pct(se / all_b, 0)}) הם עסקים של עצמאים.")

    # ── text ─────────────────────────────────────────────────────────────
    labels["lede"] = (f"כמה עסקים של עצמאים פועלים בישראל, באילו ענפים, ומי בעליהם: לפי נתוני "
                      f"הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) פעלו ב-{ly} {fmt.int_he(n_tot)} עסקים של "
                      f"עצמאים."
                      + (f" {fmt.pct(n_non / n_tot)} מהם אינם מעסיקים שכירים." if n_non is not None else "")
                      + " הנתונים מתעדכנים בכל שנה עם פרסום ההודעה הבאה.")
    rno = str(rel.get("RELEASE_NO") or "")
    rdate = str(rel.get("RELEASE_DATE") or "")
    release = {"title": str(rel.get("TITLE") or ""),
               "date": fmt.d_he(pd.Timestamp(rdate)) if rdate else "", "no": rno,
               "url": str(rel.get("PAGE_URL") or ""), "pdf": str(rel.get("REPORT_PDF_URL") or "")}

    summary = (f"עסקים של עצמאים בישראל לפי נתוני הלמ\"ס: {fmt.int_he(n_tot)} עסקים פעילים ב-{ly}"
               + (f", {fmt.pct(n_non / n_tot, 0)} מהם ללא שכירים" if n_non is not None else "")
               + (f" ו-{_p(w_tot, 0)} בבעלות נשים" if w_tot is not None else "")
               + ". פילוח לפי ענף, מין, גיל וקבוצת אוכלוסייה של בעל העסק, ועסקים חדשים.")
    desc = (f"כמה עסקים של עצמאים יש בישראל: {fmt.int_he(n_tot)} עסקים פעילים ב-{ly}, "
            f"לפי ענף, מין, גיל ומגזר של בעל העסק. נתוני הלמ\"ס.")

    if len(insights) < 3:
        raise ValueError(f"only {len(insights)} insights")
    # Card order: the headline facts first.
    order = ["trend", "share_all", "emp", "industry", "growth", "births", "births_cmp", "women",
             "women_emp", "size", "pop", "employers", "age", "age_ind"]
    insights.sort(key=lambda i: (order.index(i["id"]) if i["id"] in order else len(order), i["id"]))
    callouts = {i["id"]: i["text_he"] for i in insights[MAX_TOP:]}
    insights = insights[:MAX_TOP]

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries" if len(years) > 1 else "misc",
            "temporal_coverage": f"{years[0]}/{ly}" if len(years) > 1 else str(ly),
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "עסקים של עצמאים בישראל: נתוני הלמ\"ס",
                "description": desc,
                "name": "עסקים של עצמאים בישראל",
                "alternate_names": ["דמוגרפיה של עסקים של עצמאים", "עצמאים בישראל",
                                    "מספר העצמאים בישראל"],
            },
        },
        "kpis": kpis,
        "labels": labels,
        "charts": charts,
        "tables": tables,
        "flags": flags,
        "callouts": callouts,
        "insights": insights,
        "release": release,
        "year": ly,
    }
