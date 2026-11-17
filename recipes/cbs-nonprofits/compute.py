"""הכנסות והוצאות מלכ"רים: CBS's yearly release on non-profit institutions.

The release is a set of tables ("לוח א - ...") plus chart-data sheets
("תרשים N - ...", which only repeat the tables). CBS renumbers tables between
editions, so every table input (t1..t17, the last three spare slots, all
optional) is read with `cbs.grid` and each table is found by its TITLE text:

  gdp       תוצר של מלכ"רים ושל כלל המשק          NPO GDP vs the economy, by year
  jobs      מספר משרות שכיר במלכ"רים              NPO jobs (thousands) vs the economy
  income    הכנסות שוטפות ... לפי מקור מימון      by year x source, then by field (one year)
  expense   הוצאות שוטפות ... (סוג הוצאה)         by year x type, then by field (one year)
  donors    תרומות מדווחות למס הכנסה              donors / amounts by year and bracket
  people    משרות שכיר ומתנדבים לפי תחום          jobs and volunteers by field (one year)
  wages     תמורה למשרות שכיר וערך ההתנדבות        pay and volunteer value by field
  inc_xh    הכנסות ... ללא קופות חולים ובתי חולים  by year x source
  exp_xh    הוצאות ... ללא קופות חולים ובתי חולים  by year x type

income and expense are required (every edition has them); a missing other
table drops its section. A table found by title whose header labels are gone
raises: the layout changed and a human should look.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^לוח\s*[א-ת0-9]{1,3}\s*-")
HEB = re.compile("[א-ת]")
YEAR_CELL = re.compile(r"^R?((?:19|20)\d\d)R?$")
TITLE_YEAR = re.compile(r"(?:19|20)\d\d")
TOTAL = "סך הכל"
OTHER_SOURCES = ("הכנסות מריבית",)
GOV = "העברות מממשלה"
SALES = "מכירת שירותים"
DON_IL = "תרומות מישראל"
DON_ABROAD = "תרומות מחו\"ל"
# Insight-card order; at most MAX_TOP there, the rest lead their section.
PRIORITY = ("growth", "gov", "donations", "field", "jobs", "volunteers", "concentration",
            "exhealth", "gdp", "reported", "surplus", "field_don", "transfers", "vol_value")
MAX_TOP = 8


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    xh = "ללא קופות חולים" in t
    if "הכנסות שוטפות" in t:
        return "inc_xh" if xh else "income"
    if "הוצאות שוטפות" in t:
        return "exp_xh" if xh else "expense"
    if "תוצר" in t:
        return "gdp"
    if "תרומות מדווחות" in t:
        return "donors"
    if "ערך ההתנדבות" in t or "תמורה למשרות" in t:
        return "wages"
    if "משרות שכיר ומתנדבים" in t:
        return "people"
    if "משרות שכיר" in t:
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
        t = _title(rows)
        k = _kind(t)
        if k and k not in out:
            out[k] = (t, rows, n)
    return out


# ── small helpers ────────────────────────────────────────────────────────


def _year(c):
    m = YEAR_CELL.match(c or "")
    return int(m.group(1)) if m else None


def _title_year(t):
    ys = [int(y) for y in TITLE_YEAR.findall(t)]
    return ys[-1] if ys else None


def _label(c):
    c = c.replace("סינגור", "סנגור")
    return c.strip()


def _is_label(c):
    return bool(c) and bool(HEB.search(c)) and not c.startswith("(")


def _r(v, d=1):
    return None if v is None else round(v, d)


def _bn(v_millions):
    """Millions of NIS → billions, for charts."""
    return None if v_millions is None else round(v_millions / 1000, 2)


def _bn_he(v_millions, d=1):
    return fmt.num_he(v_millions / 1000, d)


def _chg(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b - 1


def _header_row(rows, labels, name):
    """First row holding every label (exact cell match, cleaned)."""
    for i, r in enumerate(rows):
        if all(any(c == lab for c in r) for lab in labels):
            return i
    raise ValueError(f"{name}: header row with {labels!r} not found")


def _provisional(frame, year):
    """True when the raw sheet marks `year` provisional ("*2025")."""
    if frame is None or year is None:
        return False
    y = str(year)
    cells = [c for c in frame.columns if re.fullmatch(r"C\d+", c)]
    for c in cells:
        s = frame[c].astype(str).str.replace(" ", "", regex=False)
        if ((s == "*" + y) | (s == y + "*")).any():
            return True
    return False


# ── table parsers ────────────────────────────────────────────────────────


def _two_col_series(rows, name):
    """t1/t2 layout: year | NPO | whole economy | share."""
    h = _header_row(rows, ["שנה", "מלכ\"רים", "כלל המשק"], name)
    ycol = cbs.col_after(rows[h], "שנה")
    ncol = cbs.col_after(rows[h], "מלכ\"רים")
    ecol = cbs.col_after(rows[h], "כלל המשק")
    out = {}
    for r in rows[h + 1:]:
        y = _year(cbs.cell(r, ycol))
        n, e = cbs.val(r, ncol), cbs.val(r, ecol)
        if y and n is not None and e and y not in out:
            out[y] = {"npo": n, "all": e}
    return out


def _by_source(rows, name):
    """t3/t5 layout. Returns (components, {year: {component: millions}},
    field_year, [(field, millions, {component: pct})])."""
    h = cbs.row_with(rows, "תחום פעילות", name=name)
    ycol = cbs.col_after(rows[h], "שנה")
    comps = [(j, _label(c)) for j, c in enumerate(rows[h])
             if j > ycol and _is_label(c) and c != TOTAL]
    if len(comps) < 3:
        raise ValueError(f"{name}: component header columns not found")
    years = {}
    i = h + 1
    while i < len(rows) and not any("באחוזים" in c for c in rows[i]):
        r = rows[i]
        y = _year(cbs.cell(r, ycol))
        vals = {c: cbs.val(r, j) for j, c in comps}
        if y and y not in years and all(v is not None for v in vals.values()):
            years[y] = vals
        i += 1
    # The field block (one year): after the percent block, rows with a
    # Hebrew label in column 0 and an amount in the year column. Its year is
    # the last bare-year cell before the first field row.
    fyear, fields = None, []
    for r in rows[i + 1:]:
        lab = cbs.cell(r, 0)
        if not fields:
            for c in r[1:]:
                if re.fullmatch(r"(?:19|20)\d\d", c):
                    fyear = int(c)
        if not _is_label(lab) or lab == TOTAL or lab.startswith(TOTAL):
            continue
        amt = cbs.val(r, ycol)
        mix = {c: cbs.val(r, j) for j, c in comps}
        if amt is None or any(v is None for v in mix.values()):
            continue
        fields.append((_label(lab), amt, mix))
    return [c for _, c in comps], years, fyear, fields


def _xh(rows, name):
    """t8/t9 layout: year | total | components, amount block then percents."""
    h = _header_row(rows, ["שנה", TOTAL], name)
    ycol = cbs.col_after(rows[h], "שנה")
    tcol = cbs.col_after(rows[h], TOTAL)
    comps = [(j, _label(c)) for j, c in enumerate(rows[h]) if j > tcol and _is_label(c)]
    if len(comps) < 3:
        raise ValueError(f"{name}: component header columns not found")
    years = {}
    for r in rows[h + 1:]:
        if any("באחוזים" in c for c in r):
            break
        y = _year(cbs.cell(r, ycol))
        vals = {c: cbs.val(r, j) for j, c in comps}
        if y and y not in years and all(v is not None for v in vals.values()):
            years[y] = vals
    return [c for _, c in comps], years


def _donors(rows):
    """t4: reported donations. ({year: {...}}, bracket_year, [(bracket, {...})])."""
    hb = cbs.row_with(rows, "מספר תורמים", name="donors")
    nd = [j for j, c in enumerate(rows[hb]) if c == "מספר תורמים"]
    am = [j for j, c in enumerate(rows[hb]) if c.startswith("סך התרומה")]
    if len(nd) < 3 or len(am) < 3:
        raise ValueError("donors: donor/amount header columns not found")
    ha = hb - 1
    while ha >= 0 and not any(c == "מיחידים" for c in rows[ha]):
        ha -= 1
    if ha < 0 or cbs.cell(rows[ha], nd[1]) != "מיחידים" or cbs.cell(rows[ha], nd[2]) != "מחברות":
        raise ValueError("donors: individuals/companies header not where expected")
    bcol = cbs.col_after(rows[hb], "גובה התרומה")
    keys = (("n", nd[0]), ("amt", am[0]), ("n_ind", nd[1]), ("amt_ind", am[1]),
            ("n_co", nd[2]), ("amt_co", am[2]))
    years, brackets, byear = {}, [], None
    for r in rows[hb + 1:]:
        if any("באחוזים" in c for c in r):
            break
        y = _year(cbs.cell(r, 0))
        b = cbs.cell(r, bcol)
        vals = {k: cbs.val(r, j) for k, j in keys}
        if vals["n"] is None or vals["amt"] is None:
            continue
        if b:
            if y:
                byear = y
            brackets.append((_bracket(b), vals))
        elif y and y not in years:
            years[y] = vals
    return years, byear, brackets


def _bracket(b):
    s = b.replace("₪", "").strip()
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s)


def _people(rows):
    h = cbs.row_with(rows, "מתנדבים", name="people")
    jcol = cbs.col_after(rows[h], "משרות שכיר")
    vcol = cbs.col_after(rows[h], "מתנדבים")
    out = []
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        j, v = cbs.val(r, jcol), cbs.val(r, vcol)
        if _is_label(lab) and j is not None and v is not None:
            out.append((_label(lab), j, v))
    return out


def _wages(rows):
    h = cbs.row_with(rows, "תמורה למשרות שכיר", name="wages")
    pcol = cbs.col_after(rows[h], "תמורה למשרות שכיר")
    vcol = cbs.col_after(rows[h], "התנדבות", contains=True)
    out = []
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        p, v = cbs.val(r, pcol), cbs.val(r, vcol)
        if _is_label(lab) and p is not None and v is not None:
            out.append((_label(lab), p, v))
    return out


def _split_total(items):
    """[(label, ...)] → (total row or None, the field rows)."""
    tot = next((it for it in items if it[0].startswith(TOTAL)), None)
    return tot, [it for it in items if not it[0].startswith(TOTAL)]


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    for k, what in (("income", "הכנסות שוטפות"), ("expense", "הוצאות שוטפות")):
        if k not in tabs:
            raise ValueError(f"{what} table not found in any input")

    inc_comps, inc, inc_fy, inc_fields = _by_source(tabs["income"][1], "income")
    exp_comps, exp, exp_fy, exp_fields = _by_source(tabs["expense"][1], "expense")
    if not inc or not exp:
        raise ValueError("income/expense: no year rows")
    for lab in (GOV, DON_IL, DON_ABROAD):
        if lab not in inc_comps:
            raise ValueError(f"income: column {lab!r} not found")
    if "עלות העבודה" not in exp_comps:
        raise ValueError("expense: column 'עלות העבודה' not found")

    iy = sorted(inc)
    ey = sorted(exp)
    ly = iy[-1]
    inc_tot = {y: sum(inc[y].values()) for y in iy}
    exp_tot = {y: sum(exp[y].values()) for y in ey}
    prov = _provisional(frames.get(tabs["income"][2]), ly)

    gdp = _two_col_series(tabs["gdp"][1], "gdp") if "gdp" in tabs else {}
    jobs = _two_col_series(tabs["jobs"][1], "jobs") if "jobs" in tabs else {}
    donors = _donors(tabs["donors"][1]) if "donors" in tabs else ({}, None, [])
    people = _people(tabs["people"][1]) if "people" in tabs else []
    people_year = _title_year(tabs["people"][0]) if "people" in tabs else None
    wages = _wages(tabs["wages"][1]) if "wages" in tabs else []
    wages_year = _title_year(tabs["wages"][0]) if "wages" in tabs else None
    ixh = _xh(tabs["inc_xh"][1], "inc_xh") if "inc_xh" in tabs else ([], {})
    exh = _xh(tabs["exp_xh"][1], "exp_xh") if "exp_xh" in tabs else ([], {})

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    yl = f"{ly} (זמני)" if prov else str(ly)

    # ── trend: income and expenses ───────────────────────────────────────
    both = sorted(set(iy) | set(ey))
    charts["trend"] = {"x": [str(y) for y in both],
                       "income": [_bn(inc_tot.get(y)) for y in both],
                       "expense": [_bn(exp_tot.get(y)) for y in both]}
    tables["trend"] = [[str(y),
                        fmt.int_he(inc_tot[y]) if y in inc_tot else "–",
                        fmt.int_he(exp_tot[y]) if y in exp_tot else "–",
                        fmt.int_he(inc_tot[y] - exp_tot[y]) if y in inc_tot and y in exp_tot else "–"]
                       for y in reversed(both)]
    kpis["income"] = {"value": round(inc_tot[ly]), "display": _bn_he(inc_tot[ly]), "tone": "brand"}
    labels["income_kpi"] = f"הכנסות שוטפות של המלכ\"רים, מיליארד ₪, {yl}"
    if ly in exp_tot:
        kpis["expense"] = {"value": round(exp_tot[ly]), "display": _bn_he(exp_tot[ly]),
                           "tone": "brand"}
        labels["expense_kpi"] = f"הוצאות שוטפות, מיליארד ₪, {yl}"
    fy = iy[0]
    c_all = _chg(inc_tot[ly], inc_tot[fy])
    c_last = _chg(inc_tot[ly], inc_tot.get(ly - 1))
    if c_all is not None and len(iy) >= 3:
        word = "גדלו" if c_all > 0.02 else ("קטנו" if c_all < -0.02 else "נותרו כמעט ללא שינוי")
        tail = ""
        if c_last is not None and abs(c_last) < 0.0005:
            tail = " בשנה האחרונה ההכנסות כמעט לא השתנו."
        elif c_last is not None:
            tail = (f" בשנה האחרונה {'עלו' if c_last > 0 else 'ירדו'} ההכנסות ב-"
                    f"{fmt.pct(abs(c_last))}.")
        add("growth", f"ההכנסות השוטפות של המלכ\"רים {word} מ-{_bn_he(inc_tot[fy])} מיליארד ₪ "
                      f"ב-{fy} ל-{_bn_he(inc_tot[ly])} מיליארד ₪ ב-{ly}"
                      + (f", {'עלייה' if c_all > 0 else 'ירידה'} של {fmt.pct(abs(c_all), 0)} "
                         f"במחירים שוטפים" if abs(c_all) > 0.02 else "") + "." + tail)
    surplus = {y: inc_tot[y] - exp_tot[y] for y in both if y in inc_tot and y in exp_tot}
    if ly in surplus:
        s = surplus[ly]
        if abs(s) / inc_tot[ly] >= 0.01:
            add("surplus", f"ב-{ly} ההכנסות השוטפות {'עלו על ההוצאות' if s > 0 else 'היו נמוכות מההוצאות'} "
                           f"ב-{_bn_he(abs(s))} מיליארד ₪ ({fmt.pct(abs(s) / inc_tot[ly])} "
                           f"מההכנסות).")
    labels["trend_note"] = (f"הכנסות והוצאות שוטפות של כלל המלכ\"רים, במיליארדי ₪ במחירים שוטפים, "
                            f"{both[0]}-{both[-1]}.")
    labels["trend_aria"] = f"הכנסות והוצאות שוטפות של מלכ\"רים לפי שנה, {both[0]}-{both[-1]}"

    # ── income by source ─────────────────────────────────────────────────
    charts["sources"] = {"x": [str(y) for y in iy], "names": inc_comps,
                         "series": [[_bn(inc[y][c]) for y in iy] for c in inc_comps]}
    labels["sources_cols"] = ["שנה"] + inc_comps + [TOTAL]
    tables["sources"] = [[str(y)] + [fmt.int_he(inc[y][c]) for c in inc_comps]
                         + [fmt.int_he(inc_tot[y])] for y in reversed(iy)]
    gov_sh = inc[ly][GOV] / inc_tot[ly]
    don_sh = (inc[ly][DON_IL] + inc[ly][DON_ABROAD]) / inc_tot[ly]
    kpis["gov"] = {"value": round(gov_sh * 100, 1), "display": fmt.pct(gov_sh),
                   "tone": "info" if gov_sh >= 0.5 else "brand"}
    labels["gov_kpi"] = f"חלק ההעברות מהממשלה בהכנסות, {ly}"
    kpis["donations"] = {"value": round(inc[ly][DON_IL] + inc[ly][DON_ABROAD]),
                         "display": _bn_he(inc[ly][DON_IL] + inc[ly][DON_ABROAD]),
                         "tone": "brand"}
    labels["donations_kpi"] = f"תרומות מישראל ומחו\"ל, מיליארד ₪, {ly}"
    lead = max(inc_comps, key=lambda c: (inc[ly][c], c))
    lead_sh = inc[ly][lead] / inc_tot[ly]
    gov_fy = inc[fy][GOV] / inc_tot[fy]
    if lead == GOV:
        trend = ""
        if abs(gov_sh - gov_fy) >= 0.01 and fy != ly:
            trend = (f", לעומת {fmt.pct(gov_fy)} ב-{fy}")
        add("gov", f"העברות מהממשלה, ממשרדי הממשלה, מהרשויות המקומיות ומהמוסדות הלאומיים, הן "
                   f"מקור ההכנסה הגדול של המלכ\"רים: {fmt.pct(gov_sh)} מההכנסות ב-{ly}{trend}.")
    else:
        add("gov", f"מקור ההכנסה הגדול של המלכ\"רים ב-{ly} הוא {lead}: {fmt.pct(lead_sh)} "
                   f"מההכנסות. העברות מהממשלה היו {fmt.pct(gov_sh)}.")
    don_fy = (inc[fy][DON_IL] + inc[fy][DON_ABROAD]) / inc_tot[fy]
    if fy != ly:
        ab = inc[ly][DON_ABROAD] / (inc[ly][DON_IL] + inc[ly][DON_ABROAD])
        add("donations", f"התרומות מישראל ומחו\"ל הסתכמו ב-{ly} ב-{_bn_he(inc[ly][DON_IL] + inc[ly][DON_ABROAD])} "
                         f"מיליארד ₪, {fmt.pct(don_sh)} מההכנסות"
                         + (f" ({'עלייה' if don_sh > don_fy else 'ירידה'} מ-{fmt.pct(don_fy)} ב-{fy})"
                            if abs(don_sh - don_fy) >= 0.005 else "")
                         + f". {fmt.pct(ab, 0)} מהתרומות הגיעו מחו\"ל.")
    labels["sources_note"] = (f"הכנסות שוטפות של המלכ\"רים לפי מקור מימון, במיליארדי ₪, "
                              f"{iy[0]}-{iy[-1]}.")
    labels["sources_aria"] = f"הכנסות מלכ\"רים לפי מקור מימון ושנה, {iy[0]}-{iy[-1]}"

    # ── fields: income and expenses by field of activity ────────────────
    flags["fields"] = len(inc_fields) >= 3
    if flags["fields"]:
        inc_fsum = sum(a for _, a, _ in inc_fields)
        exp_map = {f: a for f, a, _ in exp_fields}
        order = sorted(inc_fields, key=lambda it: (-it[1], it[0]))
        names = [f for f, _, _ in order]
        charts["fields"] = {"names": names, "income": [_bn(a) for _, a, _ in order],
                            "expense": [_bn(exp_map.get(f)) for f in names]}
        tables["fields"] = [[f, fmt.int_he(a), fmt.pct(a / inc_fsum),
                             fmt.int_he(exp_map[f]) if f in exp_map else "–"]
                            for f, a, _ in order]
        charts["field_mix"] = {"names": names, "comps": inc_comps,
                               "series": [[_r(m[c]) for _, _, m in order] for c in inc_comps]}
        labels["field_mix_cols"] = ["תחום פעילות"] + inc_comps
        tables["field_mix"] = [[f] + [fmt.pct_of(m[c]) for c in inc_comps] for f, _, m in order]
        fyl = inc_fy if inc_fy else ly
        labels["fields_note"] = (f"הכנסות והוצאות שוטפות לפי תחום הפעילות של המלכ\"ר, במיליארדי ₪, "
                                 f"בשנת {fyl}.")
        labels["fields_aria"] = f"הכנסות והוצאות מלכ\"רים לפי תחום פעילות, {fyl}"
        labels["field_mix_note"] = (f"איך כל תחום ממומן: חלק כל מקור מההכנסות השוטפות של התחום, "
                                    f"באחוזים, בשנת {fyl}.")
        labels["field_mix_aria"] = f"מקורות המימון של המלכ\"רים בכל תחום פעילות, {fyl}"
        labels["fields_year"] = str(fyl)
        top_f, top_a, top_m = order[0]
        add("field", f"{top_f} הוא תחום הפעילות הגדול: {fmt.pct(top_a / inc_fsum)} מההכנסות השוטפות "
                     f"של המלכ\"רים ב-{fyl} ({_bn_he(top_a)} מיליארד ₪), ו-{fmt.pct_of(top_m[GOV], 0)} "
                     f"מהכנסותיו הן העברות מהממשלה.")
        dmix = sorted(((m[DON_IL] + m[DON_ABROAD], f) for f, a, m in inc_fields
                       if a / inc_fsum >= 0.01), reverse=True)
        if dmix and dmix[0][0] >= 40:
            add("field_don", f"בתחום {dmix[0][1]} התרומות מישראל ומחו\"ל הן {fmt.pct_of(dmix[0][0], 0)} "
                             f"מההכנסות, החלק הגבוה מבין התחומים, לעומת {fmt.pct(don_sh, 0)} בכלל "
                             f"המלכ\"רים.")

    flags["exp_mix"] = len(exp_fields) >= 3
    if flags["exp_mix"]:
        eorder = sorted(exp_fields, key=lambda it: (-it[1], it[0]))
        charts["exp_mix"] = {"names": [f for f, _, _ in eorder], "comps": exp_comps,
                             "series": [[_r(m[c]) for _, _, m in eorder] for c in exp_comps]}
        labels["exp_mix_cols"] = ["תחום פעילות"] + exp_comps
        tables["exp_mix"] = [[f] + [fmt.pct_of(m[c]) for c in exp_comps] for f, _, m in eorder]
        efy = exp_fy if exp_fy else ly
        labels["exp_mix_note"] = (f"על מה כל תחום מוציא: חלק כל סוג הוצאה מההוצאות השוטפות של התחום, "
                                  f"באחוזים, בשנת {efy}. ערך שלילי (הוצאות מימון) מופיע כפי שפורסם.")
        labels["exp_mix_aria"] = f"הוצאות המלכ\"רים לפי סוג הוצאה בכל תחום פעילות, {efy}"
        tr = "העברות שוטפות"
        if tr in exp_comps:
            t_top = max(eorder, key=lambda it: (it[2][tr], it[0]))
            if t_top[2][tr] >= 40:
                add("transfers", f"בתחום {t_top[0]} {fmt.pct_of(t_top[2][tr], 0)} מההוצאות הן "
                                 f"העברות שוטפות לגופים אחרים, כלומר רוב הכסף עובר הלאה ולא "
                                 f"משמש לפעילות עצמית.")

    # ── expenses by type over years ─────────────────────────────────────
    charts["exp_types"] = {"x": [str(y) for y in ey], "names": exp_comps,
                           "series": [[_bn(exp[y][c]) for y in ey] for c in exp_comps]}
    labels["exp_types_cols"] = ["שנה"] + exp_comps + [TOTAL]
    tables["exp_types"] = [[str(y)] + [fmt.int_he(exp[y][c]) for c in exp_comps]
                           + [fmt.int_he(exp_tot[y])] for y in reversed(ey)]
    eyl = ey[-1]
    labor_sh = exp[eyl]["עלות העבודה"] / exp_tot[eyl]
    big = max(exp_comps, key=lambda c: (exp[eyl][c], c))
    labels["exp_types_note"] = (f"הוצאות שוטפות לפי סוג הוצאה, במיליארדי ₪, {ey[0]}-{ey[-1]}. "
                                f"ב-{eyl} {big} היו {fmt.pct(exp[eyl][big] / exp_tot[eyl])} "
                                f"מההוצאות ועלות העבודה {fmt.pct(labor_sh)}.")
    labels["exp_types_aria"] = f"הוצאות מלכ\"רים לפי סוג הוצאה ושנה, {ey[0]}-{ey[-1]}"

    # ── GDP ──────────────────────────────────────────────────────────────
    flags["gdp"] = len(gdp) >= 2
    if flags["gdp"]:
        gy = sorted(gdp)
        gl = gy[-1]
        share = {y: gdp[y]["npo"] / gdp[y]["all"] * 100 for y in gy}
        charts["gdp"] = {"x": [str(y) for y in gy], "npo": [_bn(gdp[y]["npo"]) for y in gy],
                         "share": [_r(share[y], 2) for y in gy]}
        tables["gdp"] = [[str(y), fmt.int_he(gdp[y]["npo"]), fmt.int_he(gdp[y]["all"]),
                          fmt.pct_of(share[y], 2)] for y in reversed(gy)]
        kpis["gdp_share"] = {"value": round(share[gl], 1), "display": fmt.pct_of(share[gl]),
                             "tone": "brand"}
        labels["gdp_share_kpi"] = f"חלק המלכ\"רים בתוצר המקומי הגולמי, {gl}"
        labels["gdp_note"] = (f"התוצר של המלכ\"רים במיליארדי ₪ שוטפים (עמודות) וחלקו בתוצר של כלל "
                              f"המשק (קו), {gy[0]}-{gl}.")
        labels["gdp_aria"] = f"תוצר המלכ\"רים וחלקו בתוצר המקומי הגולמי, {gy[0]}-{gl}"
        hi = max(gy, key=lambda y: (share[y], -y))
        d = share[gl] - share[gy[0]]
        if abs(d) >= 0.2:
            peak = (f". השיא בתקופה היה ב-{hi}, {fmt.pct_of(share[hi])}"
                    if hi not in (gl, gy[0]) else "")
            why = ("התוצר שלהם צמח לאט יותר משל המשק כולו" if d < 0
                   else "התוצר שלהם צמח מהר יותר משל המשק כולו")
            add("gdp", f"המלכ\"רים הפיקו ב-{gl} {fmt.pct_of(share[gl])} מהתוצר המקומי הגולמי "
                       f"({_bn_he(gdp[gl]['npo'])} מיליארד ₪), {'עלייה' if d > 0 else 'ירידה'} לעומת "
                       f"{fmt.pct_of(share[gy[0]])} ב-{gy[0]}{peak}. {why}.")
        gdp_last = (gl, share[gl])
    else:
        gdp_last = None

    # ── jobs ─────────────────────────────────────────────────────────────
    flags["jobs"] = len(jobs) >= 2
    if flags["jobs"]:
        jy = sorted(jobs)
        jl = jy[-1]
        jsh = {y: jobs[y]["npo"] / jobs[y]["all"] * 100 for y in jy}
        charts["jobs"] = {"x": [str(y) for y in jy], "npo": [_r(jobs[y]["npo"]) for y in jy],
                          "share": [_r(jsh[y]) for y in jy]}
        tables["jobs"] = [[str(y), fmt.int_he(jobs[y]["npo"]), fmt.int_he(jobs[y]["all"]),
                           fmt.pct_of(jsh[y])] for y in reversed(jy)]
        kpis["jobs"] = {"value": round(jobs[jl]["npo"]), "display": fmt.int_he(jobs[jl]["npo"]),
                        "tone": "brand"}
        labels["jobs_kpi"] = f"משרות שכיר במלכ\"רים, אלפים, {jl}"
        labels["jobs_note"] = (f"משרות שכיר במלכ\"רים באלפים (עמודות) וחלקן מכלל משרות השכיר במשק "
                               f"(קו), {jy[0]}-{jl}.")
        labels["jobs_aria"] = f"משרות שכיר במלכ\"רים וחלקן מכלל המשק, {jy[0]}-{jl}"
        if gdp_last and gdp_last[0] == jl and jsh[jl] > gdp_last[1] * 1.5:
            add("jobs", f"ב-{jl} היו במלכ\"רים כ-{fmt.int_he(jobs[jl]['npo'])} אלף משרות שכיר, "
                        f"{fmt.pct_of(jsh[jl])} מכלל משרות השכיר במשק, אף שחלקם בתוצר היה "
                        f"{fmt.pct_of(gdp_last[1])} בלבד: זה מגזר עתיר כוח אדם.")
        else:
            add("jobs", f"ב-{jl} היו במלכ\"רים כ-{fmt.int_he(jobs[jl]['npo'])} אלף משרות שכיר, "
                        f"{fmt.pct_of(jsh[jl])} מכלל משרות השכיר במשק.")

    # ── people: jobs and volunteers by field ────────────────────────────
    p_tot, p_fields = _split_total(people)
    flags["people"] = len(p_fields) >= 3
    if flags["people"]:
        pj = p_tot[1] if p_tot else sum(j for _, j, _ in p_fields)
        pv = p_tot[2] if p_tot else sum(v for _, _, v in p_fields)
        porder = sorted(p_fields, key=lambda it: (-it[1], it[0]))
        charts["people"] = {"names": [f for f, _, _ in porder],
                            "jobs": [_r(j / pj * 100) if pj else None for _, j, _ in porder],
                            "vol": [_r(v / pv * 100) if pv else None for _, _, v in porder]}
        tables["people"] = [[f, fmt.int_he(j), fmt.int_he(v)] for f, j, v in porder]
        pyl = people_year or ly
        kpis["volunteers"] = {"value": round(pv), "display": fmt.int_he(pv), "tone": "brand"}
        labels["volunteers_kpi"] = f"מתנדבים במלכ\"רים, {pyl}"
        labels["people_note"] = (f"איך מתחלקים משרות השכיר ({fmt.int_he(pj)}) והמתנדבים "
                                 f"({fmt.int_he(pv)}) בין תחומי הפעילות, באחוזים, בשנת {pyl}.")
        labels["people_aria"] = f"משרות שכיר ומתנדבים במלכ\"רים לפי תחום פעילות, {pyl}"
        if pv and pj:
            gap = max(porder, key=lambda it: (it[2] / pv - it[1] / pj, it[0]))
            g_v, g_j = gap[2] / pv, gap[1] / pj
            if g_v - g_j >= 0.1:
                add("volunteers", f"ההתנדבות מתרכזת במקום אחר מהעבודה בשכר: בתחום {gap[0]} פעלו "
                                  f"ב-{pyl} {fmt.pct(g_v)} מהמתנדבים במלכ\"רים "
                                  f"({fmt.int_he(gap[2])}), אבל רק {fmt.pct(g_j)} ממשרות השכיר.")

    # ── wages: pay and imputed volunteer value ──────────────────────────
    w_tot, w_fields = _split_total(wages)
    flags["wages"] = len(w_fields) >= 3
    if flags["wages"]:
        worder = sorted(w_fields, key=lambda it: (-(it[1] + it[2]), it[0]))
        charts["wages"] = {"names": [f for f, _, _ in worder],
                           "pay": [_bn(p) for _, p, _ in worder],
                           "vol": [_bn(v) for _, _, v in worder]}
        tables["wages"] = [[f, fmt.int_he(p), fmt.int_he(v), fmt.int_he(p + v)] for f, p, v in worder]
        wp = w_tot[1] if w_tot else sum(p for _, p, _ in w_fields)
        wv = w_tot[2] if w_tot else sum(v for _, _, v in w_fields)
        wyl = wages_year or ly
        labels["wages_note"] = (f"תמורה למשרות שכיר וזקיפה לערך העבודה בהתנדבות לפי תחום, במיליארדי ₪, "
                                f"בשנת {wyl}. בסך הכל {_bn_he(wp)} מיליארד ₪ שכר ו-{_bn_he(wv)} "
                                f"מיליארד ₪ ערך התנדבות.")
        labels["wages_aria"] = f"שכר וערך ההתנדבות במלכ\"רים לפי תחום פעילות, {wyl}"
        if wp:
            add("vol_value", f"הלמ\"ס מעריכה את ערך העבודה בהתנדבות במלכ\"רים ב-{wyl} "
                             f"ב-{_bn_he(wv)} מיליארד ₪, כ-{fmt.pct(wv / wp)} מהשכר ששולם למשרות "
                             f"השכיר ({_bn_he(wp)} מיליארד ₪).")

    # ── excluding health funds and hospitals ────────────────────────────
    xi_comps, xi = ixh
    xe_comps, xe = exh
    flags["exhealth"] = bool(xi) and ly in xi
    if flags["exhealth"]:
        xy = sorted(xi)
        xtot = {y: sum(xi[y].values()) for y in xy}
        # Match ex-health sources to the all-NPO ones by their opening word.
        def _match(c):
            if c in inc_comps:
                return c
            first = c.split()[0]
            hits = [a for a in inc_comps if a.split()[0] == first]
            return hits[0] if len(hits) == 1 else None
        pairs = [(c, _match(c)) for c in xi_comps]
        charts["exhealth"] = {"names": [a or c for c, a in pairs],
                              "all": [_r(inc[ly][a] / inc_tot[ly] * 100) if a else None for c, a in pairs],
                              "xh": [_r(xi[ly][c] / xtot[ly] * 100) for c, _ in pairs],
                              "labels": ["כלל המלכ\"רים", "ללא קופות חולים ובתי חולים"]}
        labels["exhealth_cols"] = ["שנה"] + xi_comps + [TOTAL]
        tables["exhealth"] = [[str(y)] + [fmt.int_he(xi[y][c]) for c in xi_comps]
                              + [fmt.int_he(xtot[y])] for y in reversed(xy)]
        gov_x = next((c for c, a in pairs if a == GOV), None)
        labels["exhealth_note"] = (f"קופות החולים ובתי החולים ממומנים בעיקר מהממשלה ומטים את התמונה. "
                                   f"כך נראה תמהיל ההכנסות בלעדיהם, באחוזים, בשנת {ly}.")
        labels["exhealth_aria"] = f"מקורות ההכנסה של המלכ\"רים עם ובלי קופות חולים ובתי חולים, {ly}"
        if gov_x:
            gx = xi[ly][gov_x] / xtot[ly]
            if gov_sh - gx >= 0.05:
                add("exhealth", f"בלי קופות החולים ובתי החולים, חלק ההעברות מהממשלה בהכנסות המלכ\"רים "
                                f"יורד מ-{fmt.pct(gov_sh)} ל-{fmt.pct(gx)} ב-{ly}, וחלק התרומות "
                                f"עולה ל-{fmt.pct((xi[ly].get(DON_IL, 0) + xi[ly].get(DON_ABROAD, 0)) / xtot[ly])}.")
    flags["exhealth_exp"] = bool(xe)
    if flags["exhealth_exp"]:
        xey = sorted(xe)
        xetot = {y: sum(xe[y].values()) for y in xey}
        labels["exhealth_exp_cols"] = ["שנה"] + xe_comps + [TOTAL]
        tables["exhealth_exp"] = [[str(y)] + [fmt.int_he(xe[y][c]) for c in xe_comps]
                                  + [fmt.int_he(xetot[y])] for y in reversed(xey)]
        xel = xey[-1]
        charts["exhealth_exp"] = {"names": xe_comps,
                                  "values": [_r(xe[xel][c] / xetot[xel] * 100) for c in xe_comps]}
        labels["exhealth_exp_note"] = (f"הוצאות שוטפות של המלכ\"רים ללא קופות חולים ובתי חולים לפי סוג "
                                       f"הוצאה, חלק מהסך באחוזים, בשנת {xel}.")
        labels["exhealth_exp_aria"] = f"הוצאות מלכ\"רים ללא קופות חולים ובתי חולים לפי סוג, {xel}"

    # ── reported donations (tax authority) ──────────────────────────────
    dyears, byear, brackets = donors
    flags["donors"] = len(dyears) >= 2
    if flags["donors"]:
        dy = sorted(dyears)
        dl = dy[-1]
        charts["donors"] = {"x": [str(y) for y in dy],
                            "ind": [_r(dyears[y]["amt_ind"] / 1e6, 2) if dyears[y]["amt_ind"] is not None else None for y in dy],
                            "co": [_r(dyears[y]["amt_co"] / 1e6, 2) if dyears[y]["amt_co"] is not None else None for y in dy],
                            "donors": [round(dyears[y]["n"]) for y in dy]}
        tables["donors"] = [[str(y), fmt.int_he(dyears[y]["n"]), fmt.int_he(dyears[y]["amt"] / 1000),
                             fmt.int_he(dyears[y]["amt_ind"] / 1000) if dyears[y]["amt_ind"] is not None else "–",
                             fmt.int_he(dyears[y]["amt_co"] / 1000) if dyears[y]["amt_co"] is not None else "–"]
                            for y in reversed(dy)]
        labels["donors_note"] = (f"תרומות שדווחו לרשות המסים לצורך זיכוי ממס, במיליארדי ₪, מיחידים "
                                 f"ומחברות, {dy[0]}-{dl}. הנתונים לשנים האחרונות אינם סופיים.")
        labels["donors_aria"] = f"תרומות מדווחות למס הכנסה מיחידים ומחברות, {dy[0]}-{dl}"
        kpis["donors"] = {"value": round(dyears[dl]["n"]), "display": fmt.int_he(dyears[dl]["n"]),
                          "tone": "brand"}
        labels["donors_kpi"] = f"תורמים שדיווחו על תרומה למס הכנסה, {dl}"
        c = _chg(dyears[dl]["amt"], dyears[dy[0]]["amt"])
        cn = _chg(dyears[dl]["n"], dyears[dy[0]]["n"])
        # Only when donors grew much slower than the amount (or fell): the
        # sentence is about the gap between the two.
        if c is not None and cn is not None and c > 0.1 and cn < c / 2:
            if cn >= 0.005:
                dn = f"בעוד מספר התורמים עלה ב-{fmt.pct(cn, 0)} בלבד"
            elif cn <= -0.005:
                dn = f"אף שמספר התורמים ירד ב-{fmt.pct(-cn, 0)}"
            else:
                dn = "בעוד מספר התורמים כמעט לא השתנה"
            add("reported", f"סך התרומות שדווחו למס הכנסה עלה מ-{_bn_he(dyears[dy[0]]['amt'] / 1000, 2)} "
                            f"מיליארד ₪ ב-{dy[0]} ל-{_bn_he(dyears[dl]['amt'] / 1000, 2)} מיליארד ₪ "
                            f"ב-{dl} ({fmt.signed_pct(c, 0)}), {dn}.")
    flags["brackets"] = len(brackets) >= 3
    if flags["brackets"]:
        bn = sum(v["n"] for _, v in brackets)
        ba = sum(v["amt"] for _, v in brackets)
        charts["brackets"] = {"names": [b for b, _ in brackets],
                              "donors": [_r(v["n"] / bn * 100, 2) for _, v in brackets],
                              "amount": [_r(v["amt"] / ba * 100) for _, v in brackets]}
        tables["brackets"] = [[b, fmt.int_he(v["n"]), fmt.pct(v["n"] / bn, 2),
                               fmt.int_he(v["amt"] / 1000), fmt.pct(v["amt"] / ba)]
                              for b, v in brackets]
        byl = byear or (max(dyears) if dyears else ly)
        labels["brackets_note"] = (f"חלקה של כל מדרגת תרומה במספר התורמים ובסכום התרומות שדווחו למס "
                                   f"הכנסה, באחוזים, בשנת {byl}.")
        labels["brackets_aria"] = f"תורמים וסכום התרומות לפי גובה התרומה, {byl}"
        topb, topv = brackets[-1]
        if topv["amt"] / ba >= 0.3:
            add("concentration", f"התרומות מרוכזות בידי מעטים: {fmt.int_he(topv['n'])} תורמים "
                                 f"שתרמו {topb} ₪ ({fmt.pct(topv['n'] / bn, 2)} מהתורמים) נתנו "
                                 f"ב-{byl} {fmt.pct(topv['amt'] / ba)} מסכום התרומות שדווחו למס.")

    # ── release card, summary, SEO ──────────────────────────────────────
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    gov_phrase = ("כמחציתן" if 0.45 <= gov_sh <= 0.55 else f"{fmt.pct(gov_sh, 0)} מהן")
    labels["lede"] = (f"כמה כסף עובר דרך העמותות, החברות לתועלת הציבור וההקדשות בישראל, מאין הוא מגיע "
                      f"ועל מה הוא מוצא. ב-{ly} הסתכמו ההכנסות השוטפות של המלכ\"רים "
                      f"ב-{_bn_he(inc_tot[ly])} מיליארד ₪, {gov_phrase} העברות מהממשלה. הנתונים מתוך "
                      f"ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים עם כל הודעה חדשה.")
    labels["prov_note"] = (f"נתוני {ly} זמניים ונתוני השנים הקודמות מעודכנים, ולכן עשויים להשתנות "
                           f"בהודעה הבאה." if prov else "")

    summary = (f"הכנסות והוצאות של מלכ\"רים בישראל לפי נתוני הלמ\"ס: ב-{ly} הכנסות שוטפות של "
               f"{_bn_he(inc_tot[ly])} מיליארד ₪, {fmt.pct(gov_sh)} מהן מהממשלה ו-{fmt.pct(don_sh)} "
               f"מתרומות.")
    desc = (f"כמה מרוויחות ומוציאות העמותות בישראל: {_bn_he(inc_tot[ly])} מיליארד ₪ הכנסות ב-{ly}, "
            f"{fmt.pct(gov_sh, 0)} מהממשלה. תרומות, שכר ומתנדבים לפי תחום.")
    rank = {k: i for i, k in enumerate(PRIORITY)}
    ordered = sorted(insights, key=lambda it: (rank.get(it["id"], len(PRIORITY)), it["id"]))
    top = ordered[:MAX_TOP]
    callouts = {it["id"]: it["text_he"] for it in ordered[MAX_TOP:]}
    all_years = sorted(set(both) | set(gdp) | set(jobs) | set(dyears))
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{all_years[0]}/{all_years[-1]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "הכנסות והוצאות של עמותות ומלכ\"רים בישראל | הלמ\"ס",
                "description": desc,
                "name": "הכנסות והוצאות מלכ\"רים בישראל",
                "alternate_names": ["הכנסות והוצאות מלכ\"רים", "עמותות בישראל",
                                    "מוסדות ללא כוונת רווח", "המגזר השלישי בישראל",
                                    "תרומות לעמותות"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top,
        "callouts": callouts,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
