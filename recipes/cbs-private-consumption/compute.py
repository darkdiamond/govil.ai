"""ההוצאה לצריכה פרטית: CBS's yearly private-consumption release.

The release is a set of chart-data sheets ("תרשים N - ..."). CBS can
renumber them between editions, so every table input (t1..t10, the last three
spare slots, all optional) is read with `cbs.grid` and each chart is found by
its TITLE text, never by its stem:

  percap    ההוצאה לצריכה פרטית לנפש, במחירי YYYY   per capita, constant prices, by year
  decades   השינוי הכמותי ... ממוצע לתקופה           average yearly growth per decade
  mixnow    ... לפי סוג, במחירים שוטפים, YYYY        shares by type, one year
  mix       ... לפי סוג, במחירי YYYY                 shares by type, selected years
  supply    ... מייצור מקומי ומיבוא                  domestic vs imported share
  personal  ... יבוא טובין אישי                      personal goods imports (million NIS)
  intl      ... השוואה בין-לאומית                   growth rate by country, one year

percap is required (every edition has it). The others drop their section
when missing; a table found by title whose header labels are gone raises.
Shares and growth rates arrive either as fractions (0.233) or as percents
(23.3) depending on the sheet; `_to_pct` settles each table by its values.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:תרשים|לוח)\s*\d+[א-ת]?\s*-\s*")
HEB = re.compile("[א-תA-Za-z]")
BASE = re.compile(r"במחירי\s+((?:19|20)\d\d)")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
RANGE = re.compile(r"^((?:19|20)\d\d)\s*-\s*((?:19|20)\d\d)$")
HEADLINE = re.compile(r"בשנת\s+((?:19|20)\d\d)\s+ל-\s*([\d,.]+)\s+מיליארד ש\"ח,\s*שהם\s+([\d.]+)%\s+מהתוצר")
NOISE = ("מקור", "הלשכה המרכזית", "פורסם", "Central Bureau", "Published")
ISRAEL = "ישראל"
PRIORITY = ("percap", "decades", "durables", "long", "intl", "mixnow", "mix", "personal",
            "supply")


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for i, r in enumerate(rows):
        for c in r:
            if TITLE.match(c):
                return i, c
    return -1, ""


def _kind(t):
    if "השוואה בין" in t:
        return "intl"
    if "טובין אישי" in t:
        return "personal"
    if "ייצור מקומי" in t and "יבוא" in t:
        return "supply"
    if "השינוי הכמותי" in t or "ממוצע לתקופה" in t:
        return "decades"
    if "לפי סוג" in t:
        return "mixnow" if "שוטפים" in t else "mix"
    if "לנפש" in t and "במחירי" in t:
        return "percap"
    return None


def _tables(frames):
    """{kind: (title row index, title, rows)}; the lowest stem wins a tie."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        i, t = _title(rows)
        k = _kind(t)
        if k and k not in out:
            out[k] = (i, TITLE.sub("", t).strip(), rows)
    return out


# ── small helpers ────────────────────────────────────────────────────────


def _is_label(c):
    return bool(c) and bool(HEB.search(c)) and not any(c.startswith(n) for n in NOISE)


def _to_pct(vals, frac_max):
    """Values as percents: the sheet stores fractions when every |value|
    is at most frac_max."""
    vals = [v for v in vals if v is not None]
    if vals and max(abs(v) for v in vals) <= frac_max:
        return 100.0
    return 1.0


def _r(v, d=1):
    return None if v is None else round(v, d)


def _chg(a, b):
    """b over a, as a fraction; None when a is missing or zero."""
    if a in (None, 0) or b is None:
        return None
    return b / a - 1


def _base(title):
    m = BASE.search(title)
    return m.group(1) if m else None


def _title_year(title):
    ys = YEAR_IN.findall(title)
    return ys[-1] if ys else None


def _dir(v, up="עלייה", down="ירידה"):
    return up if v > 0 else down


# ── per-table readers ────────────────────────────────────────────────────


def _percap(t):
    _, title, rows = t
    h = cbs.row_with(rows, "סך הכל", name="percap")
    tot = cbs.col_after(rows[h], "סך הכל")
    dur = cbs.col_after(rows[h], "מוצרים בני קיימה")
    non = cbs.col_after(rows[h], "ללא מוצרים בני קיימה")
    ycol = cbs.best_col(rows[h + 1:], lambda v: bool(cbs.YEAR.match(v)))
    if ycol is None:
        raise ValueError("percap: no year column")
    by = {}
    for r in rows[h + 1:]:
        y = cbs.cell(r, ycol)
        if not cbs.YEAR.match(y):
            continue
        v = cbs.val(r, tot)
        if v is not None:
            by[int(y)] = (v, cbs.val(r, dur), cbs.val(r, non))
    if len(by) < 2:
        raise ValueError("percap: fewer than two years")
    return title, by


def _decades(t):
    i0, title, rows = t
    out = []
    for r in rows[i0 + 1:]:
        j = next((j for j, c in enumerate(r) if RANGE.match(c)), None)
        if j is None:
            continue
        v = next((cbs.num(c) for k, c in enumerate(r) if k != j and cbs.num(c) is not None), None)
        if v is not None:
            m = RANGE.match(r[j])
            out.append((int(m.group(1)), int(m.group(2)), v))
    if not out:
        return None
    out.sort()
    s = _to_pct([v for _, _, v in out], 0.25)
    return title, [(a, b, v * s) for a, b, v in out]


def _labelled(t, frac_sum):
    """Rows of (Hebrew label, value) after the title: one share each."""
    i0, title, rows = t
    out = []
    for r in rows[i0 + 1:]:
        lab = next((c for c in r if _is_label(c)), None)
        v = next((cbs.num(c) for c in r if cbs.num(c) is not None and not cbs.YEAR.match(c)), None)
        if lab and v is not None:
            out.append((lab, v))
    if len(out) < 2:
        return None
    s = 100.0 if sum(v for _, v in out) <= frac_sum else 1.0
    return title, [(lab, v * s) for lab, v in out]


def _year_cols(t, frac_max):
    """A table with a header row of Hebrew labels and one row per year."""
    i0, title, rows = t
    ycol = cbs.best_col(rows[i0 + 1:], lambda v: bool(cbs.YEAR.match(v)))
    if ycol is None:
        raise ValueError(f"{title}: no year column")
    h = next((i for i in range(i0 + 1, len(rows))
              if sum(1 for j, c in enumerate(rows[i]) if j != ycol and _is_label(c)) >= 2), None)
    if h is None:
        raise ValueError(f"{title}: header row not found")
    cols = [(j, c) for j, c in enumerate(rows[h]) if j != ycol and _is_label(c)]
    data = []
    for r in rows[h + 1:]:
        y = cbs.cell(r, ycol)
        if cbs.YEAR.match(y):
            vals = [cbs.val(r, j) for j, _ in cols]
            if any(v is not None for v in vals):
                data.append((int(y), vals))
    if not data:
        return None
    data.sort()
    s = _to_pct([v for _, vs in data for v in vs], frac_max)
    return title, [c for _, c in cols], [(y, [None if v is None else v * s for v in vs])
                                          for y, vs in data]


def _personal(t):
    i0, title, rows = t
    h = cbs.row_with(rows, "שנה", start=i0 + 1, name="personal")
    ycol = cbs.col_after(rows[h], "שנה")
    out = []
    for r in rows[h + 1:]:
        y = cbs.cell(r, ycol)
        if not cbs.YEAR.match(y):
            continue
        v = next((cbs.num(c) for k, c in enumerate(r) if k != ycol and cbs.num(c) is not None), None)
        if v is not None:
            out.append((int(y), v))
    if len(out) < 2:
        return None
    out.sort()
    return title, out


def _intl(t):
    i0, title, rows = t
    h = cbs.row_with(rows, "מדינה", start=i0 + 1, name="intl")
    lc = cbs.col_after(rows[h], "מדינה")
    vc = cbs.col_after(rows[h], "גידול", contains=True)
    out = []
    for r in rows[h + 1:]:
        lab = cbs.cell(r, lc)
        v = cbs.val(r, vc)
        if _is_label(lab) and v is not None:
            out.append((lab, v))
    if len(out) < 3:
        return None
    s = _to_pct([v for _, v in out], 0.3)
    return title, [(lab, v * s) for lab, v in out]


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames: dict[str, pd.DataFrame]) -> dict:
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "percap" not in tabs:
        raise ValueError("per-capita consumption chart not found in any table")

    kpis, charts, tables, labels, flags, insights = {}, {}, {}, {}, {}, []

    def add(key, text):
        if text:
            insights.append({"id": key, "text_he": text})

    # ── headline: total and share of GDP ─────────────────────────────────
    hm = HEADLINE.search(rel.get("HEADLINE") or "")
    hl_year = None
    if hm:
        hl_year = hm.group(1)
        total_bn = float(hm.group(2).replace(",", ""))
        gdp = float(hm.group(3))
        kpis["total"] = {"value": total_bn, "display": fmt.num_he(total_bn), "tone": "brand"}
        labels["total_kpi"] = f"ההוצאה לצריכה פרטית ב-{hl_year} (מיליארד ש\"ח, מחירים שוטפים)"
        kpis["gdp"] = {"value": gdp, "display": fmt.pct_of(gdp), "tone": "info"}
        labels["gdp_kpi"] = f"חלק הצריכה הפרטית בתוצר המקומי הגולמי, {hl_year}"

    # ── per capita ───────────────────────────────────────────────────────
    p_title, by = _percap(tabs["percap"])
    years = sorted(by)
    ly, py = years[-1], years[-2]
    fy = years[0]
    base = _base(p_title)
    base_txt = f"במחירי {base}" if base else "במחירים קבועים"
    tot = [by[y][0] for y in years]
    dur = [by[y][1] for y in years]
    non = [by[y][2] for y in years]
    yoy = [None] + [_chg(tot[k - 1], tot[k]) for k in range(1, len(years))]
    dyoy = [None] + [_chg(dur[k - 1], dur[k]) for k in range(1, len(years))]
    charts["percap"] = {"x": [str(y) for y in years], "total": [_r(v, 0) for v in tot],
                        "non": [_r(v, 0) for v in non], "dur": [_r(v, 0) for v in dur]}
    tables["percap"] = [[str(y), fmt.int_he(by[y][0]),
                         fmt.int_he(by[y][2]) if by[y][2] is not None else "",
                         fmt.int_he(by[y][1]) if by[y][1] is not None else ""] for y in reversed(years)]
    labels["percap_cols"] = ["שנה", "סך הכל", "ללא מוצרים בני קיימה", "מוצרים בני קיימה"]
    labels["percap_note"] = (f"ההוצאה לצריכה פרטית לנפש בשקלים {base_txt}, בכל שנה מ-{fy} עד {ly}. "
                             f"מחירים קבועים מנטרלים את האינפלציה, כך שהקו מראה שינוי בכמות.")
    labels["percap_aria"] = f"ההוצאה לצריכה פרטית לנפש {base_txt}, {fy} עד {ly}"
    charts["yoy"] = {"x": [str(y) for y in years[1:]],
                     "total": [_r(v * 100 if v is not None else None) for v in yoy[1:]],
                     "dur": [_r(v * 100 if v is not None else None) for v in dyoy[1:]]}
    tables["yoy"] = [[str(years[k]), fmt.signed_pct(yoy[k]) if yoy[k] is not None else "",
                      fmt.signed_pct(dyoy[k]) if dyoy[k] is not None else ""]
                     for k in range(len(years) - 1, 0, -1)][:20]
    labels["yoy_note"] = (f"השינוי השנתי בהוצאה לנפש {base_txt}: סך הכל לעומת מוצרים בני קיימה "
                          f"(רכב, מכשירי חשמל, ריהוט), שמגיבים חזק יותר לתנודות. בטבלה עשרים השנים האחרונות.")
    labels["yoy_aria"] = f"שיעור השינוי השנתי בהוצאה לצריכה פרטית לנפש, {years[1]} עד {ly}"

    kpis["percap"] = {"value": round(tot[-1]), "display": fmt.int_he(tot[-1]), "tone": "brand"}
    labels["percap_kpi"] = f"הוצאה לצריכה פרטית לנפש ב-{ly} (ש\"ח {base_txt})"
    g = yoy[-1]
    if g is not None:
        tone = "ok" if g >= 0.005 else ("danger" if g <= -0.005 else "brand")
        kpis["percap_chg"] = {"value": round(g * 100, 2), "display": fmt.signed_pct(g), "tone": tone}
        labels["percap_chg_kpi"] = f"שינוי בהוצאה לנפש במחירים קבועים, {ly} לעומת {py}"
        gp = yoy[-2]
        txt = (f"ההוצאה לצריכה פרטית לנפש במחירים קבועים {'עלתה' if g > 0 else 'ירדה'} ב-{fmt.pct(abs(g))} "
               f"ב-{ly} והגיעה ל-{fmt.int_he(tot[-1])} ש\"ח {base_txt}")
        if gp is not None and abs(g) >= 0.0005 and abs(gp) >= 0.0005:
            same = (g > 0) == (gp > 0)
            txt += (f", אחרי {_dir(gp)} של {fmt.pct(abs(gp))} ב-{py}" if not same
                    else f", בהמשך ל{_dir(gp)} של {fmt.pct(abs(gp))} ב-{py}")
        add("percap", txt + ".")
    if len(years) >= 10 and tot[0]:
        ratio = tot[-1] / tot[0]
        if ratio >= 1.1:
            peak = max(years, key=lambda y: (by[y][0], y))
            txt = (f"מ-{fy} עד {ly} גדלה ההוצאה לנפש במחירים קבועים ב-{fmt.pct(ratio - 1, 0)}, "
                   f"מ-{fmt.int_he(tot[0])} ל-{fmt.int_he(tot[-1])} ש\"ח")
            if peak != ly:
                txt += f". השיא היה ב-{peak}, {fmt.int_he(by[peak][0])} ש\"ח לנפש"
            add("long", txt + ".")
    dg, dgp = dyoy[-1], dyoy[-2]
    if dg is not None and dur[-1] is not None and abs(dg) >= 0.03:
        verb = (("קפצה" if dg >= 0.05 else "עלתה") if dg > 0
                else ("צנחה" if dg <= -0.05 else "ירדה"))
        txt = (f"ההוצאה לנפש על מוצרים בני קיימה {verb} ב-{fmt.pct(abs(dg))} "
               f"ב-{ly}")
        if dgp is not None and abs(dgp) >= 0.03 and (dgp > 0) != (dg > 0):
            txt += f", אחרי {_dir(dgp)} של {fmt.pct(abs(dgp))} ב-{py}"
        if g is not None:
            txt += (f". סך ההוצאה לנפש {'עלה' if g > 0 else 'ירד'} באותה שנה ב-{fmt.pct(abs(g))}"
                    if abs(g) >= 0.0005 else ". סך ההוצאה לנפש כמעט לא השתנה באותה שנה")
        add("durables", txt + ".")

    # ── decades ──────────────────────────────────────────────────────────
    dec = _decades(tabs["decades"]) if "decades" in tabs else None
    flags["decades"] = bool(dec) and len(dec[1]) >= 2
    if flags["decades"]:
        rows_ = dec[1]
        names = [f"{a}-{b}" for a, b, _ in rows_]
        charts["decades"] = {"x": names, "y": [_r(v, 2) for _, _, v in rows_]}
        tables["decades"] = [[n, fmt.pct_of(v)] for n, (_, _, v) in zip(names, rows_)]
        labels["decades_note"] = (f"כמה גדלה ההוצאה לצריכה פרטית לנפש בכל שנה בממוצע, לפי תקופה, "
                                  f"מ-{rows_[0][0]} עד {rows_[-1][1]}. שינוי כמותי, בניכוי עליית המחירים.")
        labels["decades_aria"] = "שיעור הגידול השנתי הממוצע בהוצאה לצריכה פרטית לנפש, לפי תקופה"
        last, prev = rows_[-1], rows_[-2]
        best = max(rows_, key=lambda r: (r[2], -r[0]))
        txt = (f"בשנים {last[0]}-{last[1]} גדלה ההוצאה לנפש ב-{fmt.pct_of(last[2])} לשנה בממוצע, "
               f"לעומת {fmt.pct_of(prev[2])} בשנים {prev[0]}-{prev[1]}")
        if best is not last:
            txt += f". הקצב המהיר ביותר נרשם בשנים {best[0]}-{best[1]}: {fmt.pct_of(best[2])} לשנה"
        add("decades", txt + ".")

    # ── mix now (current prices) ─────────────────────────────────────────
    mn = _labelled(tabs["mixnow"], 1.5) if "mixnow" in tabs else None
    flags["mixnow"] = bool(mn)
    if flags["mixnow"]:
        m_title, items = mn
        items = sorted(items, key=lambda kv: (-kv[1], kv[0]))
        my = _title_year(m_title)
        charts["mixnow"] = {"names": [k for k, _ in items], "values": [_r(v) for _, v in items]}
        tables["mixnow"] = [[k, fmt.pct_of(v)] for k, v in items]
        yr = f" ב-{my}" if my else ""
        labels["mixnow_note"] = (f"איך מתחלקת ההוצאה לצריכה של משקי הבית בשוק המקומי{yr}, לפי סוג, "
                                 f"במחירים שוטפים, באחוזים.")
        labels["mixnow_aria"] = f"התפלגות ההוצאה לצריכה לפי סוג{yr}"
        a, b = items[0], items[1]
        if a[1] - b[1] >= 1:
            add("mixnow", f"הרכיב הגדול בהוצאה לצריכה{yr} הוא {a[0]}: {fmt.pct_of(a[1])} מההוצאה "
                          f"בשוק המקומי, ואחריו {b[0]} עם {fmt.pct_of(b[1])}.")

    # ── mix over time (constant prices) ──────────────────────────────────
    mx = _year_cols(tabs["mix"], 1.5) if "mix" in tabs else None
    flags["mix"] = bool(mx) and len(mx[2]) >= 2
    if flags["mix"]:
        x_title, cats, data = mx
        last_vals = data[-1][1]
        order = sorted(range(len(cats)), key=lambda k: (-(last_vals[k] or 0), cats[k]))
        xs = [str(y) for y, _ in data]
        charts["mix"] = {"x": xs, "cats": [cats[k] for k in order],
                         "series": [[_r(vs[k]) for _, vs in data] for k in order]}
        tables["mix"] = [[str(y)] + [fmt.pct_of(vs[k]) if vs[k] is not None else "" for k in order]
                         for y, vs in data]
        labels["mix_cols"] = ["שנה"] + [cats[k] for k in order]
        xb = _base(x_title)
        labels["mix_note"] = (f"התפלגות ההוצאה לצריכה בשוק המקומי לפי סוג בשנים נבחרות, "
                              f"{'במחירי ' + xb if xb else 'במחירים קבועים'}, באחוזים.")
        labels["mix_aria"] = f"התפלגות ההוצאה לצריכה לפי סוג, {xs[0]} עד {xs[-1]}"
        y0, v0 = data[0]
        y1, v1 = data[-1]
        diffs = [(cats[k], v0[k], v1[k]) for k in range(len(cats)) if v0[k] is not None and v1[k] is not None]
        if diffs:
            up = max(diffs, key=lambda d: (d[2] - d[1], d[0]))
            dn = min(diffs, key=lambda d: (d[2] - d[1], d[0]))
            parts = []
            if up[2] - up[1] >= 1:
                parts.append(f"החלק של {up[0]} עלה מ-{fmt.pct_of(up[1])} ב-{y0} ל-{fmt.pct_of(up[2])} ב-{y1}")
            if dn[1] - dn[2] >= 1:
                when = "" if parts else f" ב-{y0}"
                parts.append(f"החלק של {dn[0]} ירד מ-{fmt.pct_of(dn[1])}{when} ל-{fmt.pct_of(dn[2])}"
                             + ("" if parts else f" ב-{y1}"))
            if parts:
                add("mix", "במחירים קבועים, " + ", ו".join(parts) + ".")

    # ── domestic vs imports ──────────────────────────────────────────────
    sp = _year_cols(tabs["supply"], 1.5) if "supply" in tabs else None
    s_data = []
    if sp:
        _, s_cats, s_data = sp
        imp = next((k for k, c in enumerate(s_cats) if "יבוא" in c), None)
        dom = next((k for k, c in enumerate(s_cats) if "מקומי" in c), None)
        if imp is None or dom is None:
            raise ValueError("supply: labels יבוא / ייצור מקומי not found")
        s_data = [(y, vs) for y, vs in s_data if vs[imp] is not None and vs[dom] is not None]
    flags["supply"] = bool(sp) and len(s_data) >= 2
    if flags["supply"]:
        xs = [str(y) for y, _ in s_data]
        charts["supply"] = {"x": xs, "dom": [_r(vs[dom]) for _, vs in s_data],
                            "imp": [_r(vs[imp]) for _, vs in s_data]}
        tables["supply"] = [[str(y), fmt.pct_of(vs[dom]), fmt.pct_of(vs[imp])] for y, vs in s_data]
        labels["supply_note"] = ("איזה חלק מההוצאה לצריכה פרטית הולך למוצרים ושירותים מייצור מקומי "
                                 "ואיזה ליבוא, בשנים נבחרות, במחירים שוטפים.")
        labels["supply_aria"] = f"ההוצאה לצריכה פרטית מייצור מקומי ומיבוא, {xs[0]} עד {xs[-1]}"
        (y0, a0), (y1, a1) = s_data[0], s_data[-1]
        kpis["imports"] = {"value": round(a1[imp], 1), "display": fmt.pct_of(a1[imp]), "tone": "brand"}
        labels["imports_kpi"] = f"חלק היבוא בהוצאה לצריכה פרטית, {y1}"
        d = a1[imp] - a0[imp]
        if abs(d) >= 0.5:
            tail = ("עלייה בחלקו על חשבון הייצור המקומי" if d > 0
                    else "הייצור המקומי הגדיל את חלקו")
            add("supply", f"היבוא היה {fmt.pct_of(a1[imp])} מההוצאה לצריכה פרטית ב-{y1}, לעומת "
                          f"{fmt.pct_of(a0[imp])} ב-{y0}: {tail}.")

    # ── personal goods imports ───────────────────────────────────────────
    pe = _personal(tabs["personal"]) if "personal" in tabs else None
    flags["personal"] = bool(pe)
    if flags["personal"]:
        pe_title, pts = pe
        pb = _base(pe_title)
        pb_txt = f"במחירי {pb}" if pb else "במחירים קבועים"
        charts["personal"] = {"x": [str(y) for y, _ in pts], "y": [_r(v, 0) for _, v in pts]}
        tables["personal"] = [[str(y), fmt.int_he(v),
                               fmt.signed_pct(_chg(pts[k - 1][1], v)) if k and _chg(pts[k - 1][1], v) is not None else ""]
                              for k, (y, v) in enumerate(pts)][::-1][:20]
        labels["personal_note"] = (f"יבוא טובין אישי: קניות של ישראלים באתרי אינטרנט בחו\"ל בכרטיסי אשראי, "
                                   f"במיליוני ש\"ח {pb_txt}, מ-{pts[0][0]} עד {pts[-1][0]}.")
        labels["personal_aria"] = f"ההוצאה על יבוא טובין אישי {pb_txt}, {pts[0][0]} עד {pts[-1][0]}"
        (y0, v0), (y1, v1) = pts[0], pts[-1]
        kpis["personal"] = {"value": round(v1), "display": fmt.int_he(v1), "tone": "info"}
        labels["personal_kpi"] = f"יבוא טובין אישי ב-{y1} (מיליוני ש\"ח {pb_txt})"
        c = _chg(pts[-2][1], v1)
        if v0 and c is not None:
            txt = (f"הקניות של ישראלים באתרים בחו\"ל (יבוא טובין אישי) הגיעו ב-{y1} ל-{fmt.int_he(v1)} "
                   f"מיליון ש\"ח {pb_txt}, {_dir(c)} של {fmt.pct(abs(c))} בשנה אחת")
            if v1 / v0 >= 2:
                txt += f", ופי {fmt.num_he(v1 / v0)} מאשר ב-{y0}"
            add("personal", txt + ".")

    # ── international comparison ─────────────────────────────────────────
    it = _intl(tabs["intl"]) if "intl" in tabs else None
    flags["intl"] = bool(it)
    if flags["intl"]:
        i_title, pairs = it
        iy = _title_year(i_title)
        pairs = sorted(pairs, key=lambda kv: (-kv[1], kv[0]))
        charts["intl"] = {"names": [k for k, _ in pairs], "values": [_r(v, 2) for _, v in pairs],
                          "focus": ISRAEL}
        tables["intl"] = [[k, fmt.signed_pct(v / 100)] for k, v in pairs]
        per = "לנפש " if "לנפש" in i_title else ""
        yr = f" ב-{iy}" if iy else ""
        labels["intl_note"] = (f"שיעור הגידול של ההוצאה לצריכה פרטית {per}במחירים קבועים{yr}, "
                               f"ישראל מול מדינות OECD. מקור הנתונים: OECD, כפי שהביאה הלמ\"ס.")
        labels["intl_aria"] = f"שיעור הגידול של ההוצאה לצריכה פרטית {per}לפי מדינה{yr}"
        countries = [(k, v) for k, v in pairs if "OECD" not in k]
        rank = next((n for n, (k, _) in enumerate(countries, 1) if k == ISRAEL), None)
        if rank:
            iv = dict(countries)[ISRAEL]
            n = len(countries)
            if rank == 1:
                txt = f"ישראל רשמה{yr} את הגידול המהיר ביותר בהוצאה לצריכה פרטית {per}מבין {n} המדינות בהשוואה"
            elif rank <= 3:
                txt = f"ישראל במקום ה-{rank} מבין {n} המדינות בהשוואה בגידול ההוצאה לצריכה פרטית {per}{yr}"
            elif rank > n - 3:
                txt = f"ישראל בין המדינות עם הגידול האיטי ביותר בהוצאה לצריכה פרטית {per}{yr}: מקום {rank} מתוך {n}"
            else:
                txt = f"ישראל במקום ה-{rank} מבין {n} המדינות בהשוואה בגידול ההוצאה לצריכה פרטית {per}{yr}"
            txt += f" ({fmt.signed_pct(iv / 100)})"
            oecd = next((v for k, v in pairs if "OECD" in k), None)
            if oecd is not None:
                txt += f", לעומת ממוצע OECD של {fmt.signed_pct(oecd / 100)}"
            add("intl", txt + ".")

    # ── text ─────────────────────────────────────────────────────────────
    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id]
    release = {"title": rel["TITLE"], "headline": rel["HEADLINE"], "url": rel["PAGE_URL"],
               "pdf": rel["REPORT_PDF_URL"], "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    lede = ("כמה מוציאים משקי הבית בישראל על צריכה, על מה הכסף הולך, כמה ממנו ליבוא ואיך ישראל "
            "נראית מול מדינות OECD. הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) "
            "ומתעדכנים עם כל הודעה חדשה.")
    if hm:
        lede += (f" ב-{hl_year} הגיעה ההוצאה לצריכה פרטית ל-{fmt.num_he(total_bn)} מיליארד ש\"ח, "
                 f"{fmt.pct_of(gdp)} מהתוצר.")
    lede += f" ההוצאה לנפש ב-{ly}: {fmt.int_he(tot[-1])} ש\"ח {base_txt}."
    labels["lede"] = lede

    summary = (f"ההוצאה לצריכה פרטית בישראל לפי הלמ\"ס: {fmt.int_he(tot[-1])} ש\"ח לנפש ב-{ly} {base_txt}"
               + (f", {fmt.signed_pct(g)} לעומת {py}" if g is not None else "")
               + (f"; סך ההוצאה {fmt.num_he(total_bn)} מיליארד ש\"ח" if hm else "") + ".")
    desc = (f"כמה מוציאים משקי הבית בישראל: {fmt.int_he(tot[-1])} ש\"ח לנפש ב-{ly}"
            + (f", {fmt.num_he(total_bn)} מיליארד ש\"ח בסך הכל" if hm else "")
            + ". הוצאה לפי סוג, יבוא וקניות מחו\"ל.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{fy}/{ly}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "ההוצאה לצריכה פרטית בישראל: לנפש ולפי סוג | הלמ\"ס",
                "description": desc,
                "name": "ההוצאה לצריכה פרטית בישראל",
                "alternate_names": ["צריכה פרטית בישראל", "הוצאה לצריכה פרטית לנפש",
                                    "הוצאות משקי הבית על צריכה", "יבוא טובין אישי"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": top,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
