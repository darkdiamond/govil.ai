"""דמוגרפיה של מעסיקים: CBS's yearly release of salaried-job and employer
estimates by district and industry.

The release is a handful of small tables ("לוח א - …", "תרשים 1 - …"), and
CBS renumbers them between editions (the employers-by-district table was t10
in the 2022 edition, t6 since; the 2023 edition had openings by industry and
a Tel Aviv / Jerusalem chart the 2024 edition dropped). So every table input
(t1..t12, all optional, three spare stems) is read with `cbs.grid`, and each
table is recognised by its TITLE text, never by its stem:

  jobs_ind   משרות שכיר … לפי ענף כלכלי        thousands, one column per year
  emp_ind    מעסיקים פעילים לפי ענף כלכלי       count, one column per year
  jobs_dist  משרות שכיר … לפי מחוז              thousands, one column per year
  emp_dist   מעסיקים פעילים לפי מחוז            count, one column per year
  chains     רשתות ארציות                      chains, branches, jobs per industry
  open       פתיחות סניפים (rows = districts)   count, one column per year
  close      סגירות / סניפים שנסגרו (districts) count, one column per year

Cross tabs (industry × district, in percent; the 2022 edition only) and the
by-industry openings/closings are not read. A recognised table whose header
is gone raises; a table missing from an edition drops its section. The
district tables are required: they are what the page is about.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^(?:לוח|תרשים)\s+[א-ת\d]{1,3}\s*[-–:.]\s*(.+)$")
YEAR_CELL = re.compile(r"^(?:שנת\s*)?((?:19|20)\d\d)$")
HEB = re.compile(r"[א-ת]")
TOTALS = ("סך הכל", "סה\"כ", "סכום כולל", "סך כולל")
DISTRICT_WORDS = ("המרכז", "תל אביב", "הצפון", "הדרום", "חיפה", "ירושלים")
MAX_TOP = 8
FLAT = 0.001  # |change| below 0.1% reads as "almost unchanged"


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    """(row index, title text) of the table's title, or None."""
    for i, r in enumerate(rows[:10]):
        for c in r:
            m = TITLE.match(c)
            if m:
                return i, m.group(1).strip()
    return None


def _is_district(label):
    return any(w in label for w in DISTRICT_WORDS) or "יהודה" in label or "איו\"ש" in label


def _kind(t):
    if "רשתות ארציות" in t or "רשת ארצית" in t:
        return "chains"
    if "פתיחות סניפים" in t:
        return "open"
    if "סגירות סניפים" in t or ("סניפ" in t and "נסגרו" in t):
        return "close"
    if "אחוזים" in t and "ענף" in t and "מחוז" in t:
        return None  # industry × district cross tab (shares)
    if "משרות שכיר" in t:
        if "לפי ענף" in t and "מחוז" not in t:
            return "jobs_ind"
        if "לפי מחוז" in t and "ענף" not in t:
            return "jobs_dist"
    if "מעסיקים" in t:
        if "לפי ענף" in t and "מחוז" not in t:
            return "emp_ind"
        if "לפי מחוז" in t and "ענף" not in t:
            return "emp_dist"
    return None


def _tables(frames):
    """{kind: (title, title row, rows, stem)} over every non-empty table
    input. Inputs are visited in stem order; the first table of a kind wins,
    except openings/closings, kept as a list (one edition had them both by
    industry and by district under near-identical titles)."""
    out = {}
    names = sorted((n for n in frames if re.fullmatch(r"t\d+", n)), key=lambda n: int(n[1:]))
    for n in names:
        df = frames[n]
        if df.empty:
            continue
        rows = cbs.grid(df, n)
        found = _title(rows)
        if not found:
            continue
        ti, title = found
        kind = _kind(title)
        if kind in ("open", "close"):
            out.setdefault(kind, []).append((title, ti, rows, n))
        elif kind and kind not in out:
            out[kind] = (title, ti, rows, n)
    return out


# ── parsing ──────────────────────────────────────────────────────────────


def _note(label):
    """A footnote or source line under a table, not a category row."""
    return label.startswith(("[", "(", "מקור", "הערה")) or len(label) > 70


def _year_table(rows, ti, name):
    """A table with one row per category and one column per year.
    Returns {"years", "items": [(label, {year: value})], "total": {year: value} | None}."""
    h = None
    ycols = []
    for i in range(ti + 1, len(rows)):
        cols = []
        for j, c in enumerate(rows[i]):
            m = YEAR_CELL.match(c)
            if m:
                cols.append((j, int(m.group(1))))
        if len(cols) >= 2:
            h, ycols = i, cols
            break
    if h is None:
        raise ValueError(f"{name}: year header row not found")
    years = sorted({y for _, y in ycols})
    items, total = [], None
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        if not HEB.search(lab) or _note(lab):
            continue
        vals = {y: cbs.val(r, j) for j, y in ycols}
        if all(v is None for v in vals.values()):
            continue
        if lab in TOTALS:
            total = vals
        else:
            items.append((lab, vals))
    items.sort(key=lambda kv: kv[0])
    return {"years": years, "items": items, "total": total}


def _chains(rows, ti, name):
    h = cbs.row_with(rows, "סניפים", ti + 1, name, contains=True)
    hr = rows[h]

    def col(pred, label):
        for j, c in enumerate(hr):
            if c and pred(c):
                return j
        raise ValueError(f"{name}: header label {label!r} not found")

    c_n = col(lambda c: "עסקים" in c and "רשת" in c, "סך עסקים שהינם רשת ארצית")
    c_br = col(lambda c: "סניפים" in c, "סך סניפים")
    c_cj = col(lambda c: "משרות שכיר ברשת" in c and "אחוז" not in c, "משרות שכיר ברשתות ארציות")
    c_tj = col(lambda c: c.startswith("סך משרות שכיר") and "רשת" not in c, "סך משרות שכיר")
    items, total = [], None
    for r in rows[h + 1:]:
        lab = cbs.cell(r, 0)
        if not HEB.search(lab) or _note(lab):
            continue
        rec = {"n": cbs.val(r, c_n), "branches": cbs.val(r, c_br),
               "chain_jobs": cbs.val(r, c_cj), "jobs": cbs.val(r, c_tj)}
        if rec["chain_jobs"] is None or not rec["jobs"]:
            continue
        if lab in TOTALS:
            total = rec
        else:
            items.append((lab, rec))
    items.sort(key=lambda kv: kv[0])
    return {"items": items, "total": total}


# ── formatting ───────────────────────────────────────────────────────────


def _r(v, d=1):
    return None if v is None else round(float(v), d)


def _chg(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b - 1


def _place(label):
    """'המרכז' → 'מחוז המרכז'; 'אזור יהודה והשומרון' stays."""
    return label if label.startswith(("אזור", "מחוז")) else f"מחוז {label}"


def _in_place(label):
    """'במחוז המרכז' / 'באזור יהודה והשומרון'."""
    return "ב" + _place(label)


def _k(v):
    """Thousands of jobs as text: 1113.67 → '1,113.7 אלף'."""
    return f"{fmt.num_he(v, 1)} אלף"


def _sp(c):
    return fmt.signed_pct(c)


def _kpi(value, display, tone="brand"):
    return {"value": value, "display": display, "tone": tone}


def _tone(c):
    if c is None or abs(c) < FLAT:
        return "brand"
    return "ok" if c > 0 else "danger"


def _dir(c, up, down, flat):
    if abs(c) < FLAT:
        return flat
    return up if c > 0 else down


def _thousands(title, tab):
    """Jobs tables are printed in thousands; a table printed in units is
    scaled to thousands. Decided by magnitude, not by the title's wording:
    Israel's employee jobs are in the millions, so a total above 100,000
    can only be units (thousands would read as 100 million jobs)."""
    if tab["total"]:
        mag = max((v for v in tab["total"].values() if v is not None), default=0)
    else:
        mag = max((sum(v.get(y) or 0 for _, v in tab["items"]) for y in tab["years"]), default=0)
    if mag <= 100_000:
        return tab

    def scale(d):
        return {y: (None if v is None else v / 1000) for y, v in d.items()}

    return {"years": tab["years"], "items": [(k, scale(v)) for k, v in tab["items"]],
            "total": scale(tab["total"]) if tab["total"] else None}


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    for k in ("jobs_dist", "emp_dist"):
        if k not in tabs:
            raise ValueError(f"{k}: district table not found in any table input")

    jd_t, jd_i, jd_rows, _ = tabs["jobs_dist"]
    jobs_d = _thousands(jd_t, _year_table(jd_rows, jd_i, "jobs_dist"))
    _, ed_i, ed_rows, _ = tabs["emp_dist"]
    emp_d = _year_table(ed_rows, ed_i, "emp_dist")
    if not jobs_d["items"] or not emp_d["items"]:
        raise ValueError("district tables: no district rows")

    jobs_i = emp_i = chains = opn = cls = None
    if "jobs_ind" in tabs:
        t, i, rows, _ = tabs["jobs_ind"]
        jobs_i = _thousands(t, _year_table(rows, i, "jobs_ind"))
    if "emp_ind" in tabs:
        t, i, rows, _ = tabs["emp_ind"]
        emp_i = _year_table(rows, i, "emp_ind")
    if "chains" in tabs:
        t, i, rows, _ = tabs["chains"]
        chains = _chains(rows, i, "chains")
        m = re.search(r"((?:19|20)\d\d)\s*$", t)
        chains["year"] = m.group(1) if m else None
    for key in ("open", "close"):
        for _, i, rows, stem in tabs.get(key, []):
            tab = _year_table(rows, i, f"{key} ({stem})")
            # by district only: the by-industry variant is not read
            if sum(_is_district(k) for k, _ in tab["items"]) >= max(2, len(tab["items"]) // 2):
                if key == "open":
                    opn = tab
                else:
                    cls = tab
                break

    ly = jobs_d["years"][-1]
    fy = jobs_d["years"][0]
    ely = emp_d["years"][-1]
    efy = emp_d["years"][0]

    kpis, labels, charts, tables, flags = {}, {}, {}, {}, {}
    found = {}  # insight id → text

    # ── national totals ──────────────────────────────────────────────────
    jt = jobs_d["total"] or (jobs_i["total"] if jobs_i else None)
    et = emp_d["total"] or (emp_i["total"] if emp_i else None)
    nat_years = sorted(y for y in jobs_d["years"] if jt and et and jt.get(y) is not None
                       and et.get(y) is not None)
    flags["trend"] = len(nat_years) >= 2
    if jt and jt.get(ly) is not None:
        kpis["jobs"] = _kpi(_r(jt[ly]), fmt.num_he(jt[ly], 1))
        labels["jobs_kpi"] = f"משרות שכיר (אלפים), {ly}"
        c = _chg(jt.get(ly), jt.get(ly - 1))
        if c is not None:
            kpis["jobs_chg"] = _kpi(_r(c * 100, 2), _sp(c), _tone(c))
            labels["jobs_chg_kpi"] = f"שינוי במשרות השכיר, {ly - 1}-{ly}"
    if et and et.get(ely) is not None:
        kpis["emp"] = _kpi(round(et[ely]), fmt.int_he(et[ely]))
        labels["emp_kpi"] = f"מעסיקים פעילים, {ely}"
        c = _chg(et.get(ely), et.get(ely - 1))
        if c is not None:
            kpis["emp_chg"] = _kpi(_r(c * 100, 2), _sp(c), _tone(c))
            labels["emp_chg_kpi"] = f"שינוי במספר המעסיקים, {ely - 1}-{ely}"
    if flags["trend"]:
        charts["trend"] = {"x": [str(y) for y in nat_years],
                           "jobs": [_r(jt[y]) for y in nat_years],
                           "emp": [round(et[y]) for y in nat_years]}
        tables["trend"] = [[str(y), fmt.num_he(jt[y], 1), fmt.int_he(et[y])] for y in nat_years]
        y0, y1 = nat_years[0], nat_years[-1]
        cj, ce = _chg(jt[y1], jt[y0]), _chg(et[y1], et[y0])
        labels["trend_note"] = (f"בין {y0} ל-{y1} {_dir(cj, 'עלה', 'ירד', 'כמעט לא השתנה')} מספר משרות "
                                f"השכיר ב-{fmt.pct(abs(cj))}, ומספר המעסיקים הפעילים "
                                f"{_dir(ce, 'עלה', 'ירד', 'כמעט לא השתנה')} ב-{fmt.pct(abs(ce))}.")
        labels["trend_aria"] = f"משרות שכיר ומעסיקים פעילים בישראל, {y0}-{y1}"
        found["nat_long"] = (f"מ-{y0} עד {y1} {_dir(cj, 'גדל', 'קטן', 'נותר יציב')} מספר משרות השכיר "
                             f"מ-{_k(jt[y0])} ל-{_k(jt[y1])} ({_sp(cj)}), ומספר המעסיקים הפעילים "
                             f"{_dir(ce, 'גדל', 'קטן', 'נותר יציב')} מ-{fmt.int_he(et[y0])} "
                             f"ל-{fmt.int_he(et[y1])} ({_sp(ce)}).")
        if len(nat_years) >= 2 and nat_years[-2] == y1 - 1:
            cj1, ce1 = _chg(jt[y1], jt[y1 - 1]), _chg(et[y1], et[y1 - 1])
            if (cj1 > 0) != (ce1 > 0) and abs(cj1) >= FLAT and abs(ce1) >= FLAT:
                found["nat_dir"] = (f"ב-{y1} {'עלה' if cj1 > 0 else 'ירד'} מספר משרות השכיר "
                                    f"ב-{fmt.pct(abs(cj1))}, ל-{_k(jt[y1])}, ואילו מספר המעסיקים "
                                    f"הפעילים {'עלה' if ce1 > 0 else 'ירד'} ב-{fmt.pct(abs(ce1))}, "
                                    f"ל-{fmt.int_he(et[y1])}.")
            else:
                found["nat_dir"] = (f"ב-{y1} מספר משרות השכיר "
                                    f"{_dir(cj1, 'עלה', 'ירד', 'כמעט לא השתנה')} "
                                    f"({_sp(cj1)}, {_k(jt[y1])}) ומספר המעסיקים הפעילים "
                                    f"{_dir(ce1, 'עלה', 'ירד', 'כמעט לא השתנה')} "
                                    f"({_sp(ce1)}, {fmt.int_he(et[y1])}).")

    # ── jobs by district ─────────────────────────────────────────────────
    jd = [(k, v) for k, v in jobs_d["items"] if v.get(ly) is not None]
    jd.sort(key=lambda kv: (-kv[1][ly], kv[0]))
    dyears = jobs_d["years"]
    charts["jobs_dist"] = {"names": [k for k, _ in jd], "years": [str(y) for y in dyears],
                           "series": [[_r(v.get(y)) for _, v in jd] for y in dyears]}
    tables["jobs_dist"] = [[k] + [fmt.num_he(v[y], 1) if v.get(y) is not None else "–" for y in dyears]
                           for k, v in jd]
    labels["dist_cols"] = ["מחוז"] + [str(y) for y in dyears]
    labels["jobs_dist_aria"] = f"משרות שכיר באלפים לפי מחוז, {fy}-{ly}"
    total_ly = jt.get(ly) if jt else None
    lead, lv = jd[0][0], jd[0][1][ly]
    if total_ly:
        labels["jobs_dist_note"] = (f"ב-{ly} רוכזו {fmt.pct(lv / total_ly)} ממשרות השכיר {_in_place(lead)}. "
                                    f"הנתונים באלפי משרות.")
        if len(jd) >= 2:
            found["dist_lead"] = (f"{_place(lead)} הוא הגדול במשרות השכיר: {_k(lv)} משרות ב-{ly}, "
                                  f"{fmt.pct(lv / total_ly)} מכלל המשרות, לפני {_place(jd[1][0])} "
                                  f"({_k(jd[1][1][ly])}).")
    else:
        labels["jobs_dist_note"] = f"הגדול ב-{ly} הוא {_place(lead)}. הנתונים באלפי משרות."

    # last-year change by district
    moves = [(k, _chg(v.get(ly), v.get(ly - 1))) for k, v in jd]
    moves = [(k, c) for k, c in moves if c is not None]
    if moves:
        down = min(moves, key=lambda kc: (kc[1], kc[0]))
        up = max(moves, key=lambda kc: (kc[1], kc[0]))
        dn = f"הירידה החדה ביותר במשרות השכיר {_in_place(down[0])} ({_sp(down[1])})"
        upt = f"העלייה הגדולה ביותר {_in_place(up[0])} ({_sp(up[1])})"
        if down[1] <= -0.01 and up[1] >= 0.01:
            found["dist_move"] = f"ב-{ly} נרשמה {dn}, ו{upt}."
        elif down[1] <= -0.01:
            found["dist_move"] = f"ב-{ly} נרשמה {dn}."
        elif up[1] >= 0.01:
            found["dist_move"] = f"ב-{ly} נרשמה {upt.replace('ביותר', 'ביותר במשרות השכיר', 1)}."

    # ── employers by district ────────────────────────────────────────────
    ed = [(k, v) for k, v in emp_d["items"] if v.get(ely) is not None]
    ed.sort(key=lambda kv: (-kv[1][ely], kv[0]))
    eyears = emp_d["years"]
    charts["emp_dist"] = {"names": [k for k, _ in ed], "years": [str(y) for y in eyears],
                          "series": [[None if v.get(y) is None else round(v[y]) for _, v in ed]
                                     for y in eyears]}
    tables["emp_dist"] = [[k] + [fmt.int_he(v[y]) if v.get(y) is not None else "–" for y in eyears]
                          for k, v in ed]
    labels["emp_cols"] = ["מחוז"] + [str(y) for y in eyears]
    labels["emp_dist_aria"] = f"מעסיקים פעילים לפי מחוז, {efy}-{ely}"
    e_total = et.get(ely) if et else None
    labels["emp_dist_note"] = (f"ב-{ely} פעלו {fmt.int_he(ed[0][1][ely])} מעסיקים {_in_place(ed[0][0])}"
                               + (f", {fmt.pct(ed[0][1][ely] / e_total)} מכלל המעסיקים" if e_total else "")
                               + ".")

    # ── employer size and growth by district ─────────────────────────────
    emp_map = dict(emp_d["items"])
    common_y = ly if ly == ely else min(ly, ely)
    size = []
    for k, v in jobs_d["items"]:
        e = emp_map.get(k, {}).get(common_y)
        j = v.get(common_y)
        if e and j is not None:
            size.append((k, j * 1000 / e))
    size.sort(key=lambda kv: (-kv[1], kv[0]))
    flags["size"] = len(size) >= 3
    if flags["size"]:
        charts["size"] = {"names": [k for k, _ in size], "values": [_r(s) for _, s in size]}
        nat = (jt[common_y] * 1000 / et[common_y]) if jt and et and jt.get(common_y) is not None \
            and et.get(common_y) else None
        charts["size"]["national"] = _r(nat)
        tables["size"] = [[k, fmt.num_he(s, 1)] for k, s in size]
        labels["size_aria"] = f"משרות שכיר למעסיק לפי מחוז, {common_y}"
        labels["size_note"] = (f"מספר משרות השכיר חלקי מספר המעסיקים הפעילים בכל מחוז ב-{common_y}"
                               + (f". הממוצע הארצי: {fmt.num_he(nat, 1)} משרות למעסיק." if nat else "."))
        big, small = size[0], size[-1]
        if small[1] > 0 and big[1] / small[1] >= 1.15:
            found["size"] = (f"המעסיקים {_in_place(big[0])} גדולים יותר: {fmt.num_he(big[1], 1)} משרות "
                             f"שכיר למעסיק ב-{common_y}, לעומת {fmt.num_he(small[1], 1)} {_in_place(small[0])}"
                             + (f" ו-{fmt.num_he(nat, 1)} בממוצע הארצי." if nat else "."))

    gy0 = max(fy, efy)
    gy1 = min(ly, ely)
    growth = []
    for k, v in jobs_d["items"]:
        e = emp_map.get(k, {})
        cj, ce = _chg(v.get(gy1), v.get(gy0)), _chg(e.get(gy1), e.get(gy0))
        if cj is not None and ce is not None:
            growth.append((k, cj, ce))
    growth.sort(key=lambda r: (-r[1], r[0]))
    flags["growth"] = gy1 > gy0 and len(growth) >= 3
    if flags["growth"]:
        charts["growth"] = {"names": [g[0] for g in growth],
                            "jobs": [_r(g[1] * 100) for g in growth],
                            "emp": [_r(g[2] * 100) for g in growth]}
        tables["growth"] = [[g[0], _sp(g[1]), _sp(g[2])] for g in growth]
        labels["growth_cols"] = ["מחוז", "משרות שכיר", "מעסיקים פעילים"]
        labels["growth_aria"] = f"שינוי במשרות השכיר ובמספר המעסיקים לפי מחוז, {gy0}-{gy1}"
        labels["growth_head"] = f"צמיחה לפי מחוז, {gy0}-{gy1}"
        fast = growth[0]
        labels["growth_note"] = (f"השינוי באחוזים בין {gy0} ל-{gy1}. משרות השכיר גדלו בקצב המהיר ביותר "
                                 f"{_in_place(fast[0])} ({_sp(fast[1])})." if fast[1] > 0 else
                                 f"השינוי באחוזים בין {gy0} ל-{gy1}.")

    # ── industries ───────────────────────────────────────────────────────
    flags["jobs_ind"] = bool(jobs_i and jobs_i["items"])
    if flags["jobs_ind"]:
        iy = jobs_i["years"][-1]
        ji = [(k, v) for k, v in jobs_i["items"] if v.get(iy) is not None]
        ji.sort(key=lambda kv: (-kv[1][iy], kv[0]))
        chg = [(k, _chg(v.get(iy), v.get(iy - 1))) for k, v in ji]
        charts["jobs_ind"] = {"names": [k for k, _ in ji], "values": [_r(v[iy]) for _, v in ji],
                              "chg": [None if c is None else _r(c * 100) for _, c in chg]}
        tables["jobs_ind"] = [[k, fmt.num_he(v[iy], 1),
                               fmt.num_he(v[iy - 1], 1) if v.get(iy - 1) is not None else "–",
                               _sp(c) if c is not None else "–"] for (k, v), (_, c) in zip(ji, chg)]
        labels["jobs_ind_cols"] = ["ענף", str(iy), str(iy - 1), "שינוי"]
        labels["jobs_ind_aria"] = f"משרות שכיר באלפים לפי ענף כלכלי, {iy}"
        tot = jobs_i["total"].get(iy) if jobs_i["total"] else None
        labels["jobs_ind_note"] = (f"משרות שכיר באלפים ב-{iy}. הענף הגדול: {ji[0][0]} ({_k(ji[0][1][iy])}"
                                   + (f", {fmt.pct(ji[0][1][iy] / tot)} מכלל המשרות" if tot else "") + ").")
        cc = [(k, c) for k, c in chg if c is not None]
        flags["ind_chg"] = len(cc) >= 3
        if flags["ind_chg"]:
            cc.sort(key=lambda kc: (kc[1], kc[0]))
            charts["ind_chg"] = {"names": [k for k, _ in cc], "values": [_r(c * 100) for _, c in cc]}
            labels["ind_chg_aria"] = f"שינוי במשרות השכיר לפי ענף כלכלי, {iy - 1}-{iy}"
            labels["ind_chg_head"] = f"השינוי במשרות השכיר לפי ענף, {iy - 1}-{iy}"
            n_up = sum(c >= FLAT for _, c in cc)
            n_dn = sum(c <= -FLAT for _, c in cc)
            labels["ind_chg_note"] = (f"ב-{iy} גדל מספר המשרות ב-{n_up} ענפים וקטן ב-{n_dn} "
                                      f"(מתוך {len(cc)}).")
            down, up = cc[0], cc[-1]
            if down[1] <= -0.02 and up[1] >= 0.02:
                found["ind_move"] = (f"ב-{iy} נרשמה הירידה החדה ביותר במשרות השכיר בענף {down[0]} "
                                     f"({_sp(down[1])}), והעלייה הגדולה ביותר בענף {up[0]} ({_sp(up[1])}).")
            elif down[1] <= -0.02:
                found["ind_move"] = (f"ב-{iy} נרשמה הירידה החדה ביותר במשרות השכיר בענף {down[0]} "
                                     f"({_sp(down[1])}).")
            elif up[1] >= 0.02:
                found["ind_move"] = (f"ב-{iy} נרשמה העלייה הגדולה ביותר במשרות השכיר בענף {up[0]} "
                                     f"({_sp(up[1])}).")
    else:
        flags["ind_chg"] = False

    flags["emp_ind"] = bool(emp_i and emp_i["items"])
    if flags["emp_ind"]:
        iy = emp_i["years"][-1]
        ei = [(k, v) for k, v in emp_i["items"] if v.get(iy) is not None]
        ei.sort(key=lambda kv: (-kv[1][iy], kv[0]))
        chg = [_chg(v.get(iy), v.get(iy - 1)) for _, v in ei]
        charts["emp_ind"] = {"names": [k for k, _ in ei], "values": [round(v[iy]) for _, v in ei],
                             "chg": [None if c is None else _r(c * 100) for c in chg]}
        tables["emp_ind"] = [[k, fmt.int_he(v[iy]),
                              fmt.int_he(v[iy - 1]) if v.get(iy - 1) is not None else "–",
                              _sp(c) if c is not None else "–"] for (k, v), c in zip(ei, chg)]
        labels["emp_ind_cols"] = ["ענף", str(iy), str(iy - 1), "שינוי"]
        labels["emp_ind_aria"] = f"מעסיקים פעילים לפי ענף כלכלי, {iy}"
        tot = emp_i["total"].get(iy) if emp_i["total"] else None
        labels["emp_ind_note"] = f"מספר המעסיקים הפעילים בכל ענף ב-{iy}."
        if tot and len(ei) >= 2:
            top2 = ei[0][1][iy] + ei[1][1][iy]
            found["emp_ind"] = (f"בענף {ei[0][0]} פעלו ב-{iy} {fmt.int_he(ei[0][1][iy])} מעסיקים, "
                                f"{fmt.pct(ei[0][1][iy] / tot)} מכלל המעסיקים. יחד עם ענף {ei[1][0]} "
                                f"({fmt.int_he(ei[1][1][iy])}) הם {fmt.pct(top2 / tot)} מהמעסיקים.")

    # ── national chains ──────────────────────────────────────────────────
    flags["chains"] = bool(chains and len(chains["items"]) >= 3)
    if flags["chains"]:
        cy = chains["year"]
        ci = sorted(chains["items"], key=lambda kv: (-kv[1]["chain_jobs"] / kv[1]["jobs"], kv[0]))
        charts["chains"] = {"names": [k for k, _ in ci],
                            "values": [_r(r["chain_jobs"] / r["jobs"] * 100) for _, r in ci],
                            "branches": [None if r["branches"] is None else round(r["branches"]) for _, r in ci]}
        tables["chains"] = [[k, fmt.int_he(r["n"]) if r["n"] is not None else "–",
                             fmt.int_he(r["branches"]) if r["branches"] is not None else "–",
                             fmt.num_he(r["chain_jobs"] / 1000, 1),
                             fmt.pct(r["chain_jobs"] / r["jobs"])] for k, r in ci]
        yr = f", {cy}" if cy else ""
        labels["chains_aria"] = f"שיעור משרות השכיר ברשתות ארציות לפי ענף{yr}"
        ct = chains["total"]
        if ct:
            kpis["chains"] = _kpi(_r(ct["chain_jobs"] / ct["jobs"] * 100), fmt.pct(ct["chain_jobs"] / ct["jobs"]))
            labels["chains_kpi"] = f"ממשרות השכיר ברשתות ארציות{yr}"
            labels["chains_note"] = ((f"ב-{cy} " if cy else "")
                                     + f"פעלו {fmt.int_he(ct['n'])} רשתות ארציות עם "
                                     f"{fmt.int_he(ct['branches'])} סניפים, ובהן "
                                     f"{_k(ct['chain_jobs'] / 1000)} משרות שכיר.")
        else:
            labels["chains_note"] = "שיעור משרות השכיר בעסקים שהם רשתות ארציות, בכל ענף."
        hi, lo = ci[0], ci[-1]
        sh_hi = hi[1]["chain_jobs"] / hi[1]["jobs"]
        sh_lo = lo[1]["chain_jobs"] / lo[1]["jobs"]
        if sh_hi - sh_lo >= 0.2:
            found["chains"] = (f"בענף {hi[0]} היו " + (f"ב-{cy} " if cy else "")
                               + f"{fmt.pct(sh_hi)} ממשרות השכיר ברשתות ארציות, "
                               f"לעומת {fmt.pct(sh_lo)} בלבד בענף {lo[0]}"
                               + (f". בכלל המשק: {fmt.pct(ct['chain_jobs'] / ct['jobs'])}." if ct else "."))

    # ── branch openings and closings ─────────────────────────────────────
    flags["branches"] = bool(opn or cls)
    if flags["branches"]:
        names = sorted({k for t in (opn, cls) if t for k, _ in t["items"]})
        series = []
        for kind, tab, word in (("open", opn, "פתיחות"), ("close", cls, "סגירות")):
            if not tab:
                continue
            dm = dict(tab["items"])
            for y in tab["years"]:
                series.append({"name": f"{word} {y}", "kind": kind,
                               "data": [None if dm.get(n, {}).get(y) is None else round(dm[n][y])
                                        for n in names]})
        charts["branches"] = {"names": names, "series": series}
        labels["branch_cols"] = ["מחוז"] + [s["name"] for s in series]
        tables["branches"] = [[n] + [fmt.int_he(s["data"][i]) if s["data"][i] is not None else "–"
                                     for s in series] for i, n in enumerate(names)]
        labels["branches_aria"] = "פתיחות וסגירות של סניפים לפי מחוז"
        notes = []
        for tab, word in ((opn, "נפתחו"), (cls, "נסגרו")):
            if tab and tab["total"]:
                y = max(y for y in tab["years"] if tab["total"].get(y) is not None)
                notes.append(f"ב-{y} {word} {fmt.int_he(tab['total'][y])} סניפים")
        labels["branches_note"] = ("; ".join(notes) + "." if notes else
                                   "מספר הסניפים שנפתחו ונסגרו בכל מחוז.")
        if opn and cls and opn["total"] and cls["total"]:
            common = sorted(y for y in opn["years"] if y in cls["years"]
                            and opn["total"].get(y) is not None and cls["total"].get(y) is not None)
            if common:
                y = common[-1]
                o, c = opn["total"][y], cls["total"][y]
                if c and abs(o / c - 1) >= 0.05:
                    found["branches"] = (f"ב-{y} נפתחו {fmt.int_he(o)} סניפים ונסגרו {fmt.int_he(c)}: "
                                         + (f"{fmt.int_he(o - c)} סניפים יותר נפתחו מאשר נסגרו."
                                            if o > c else
                                            f"{fmt.int_he(c - o)} סניפים יותר נסגרו מאשר נפתחו."))
        if opn:
            oy = opn["years"][-1]
            om = [(k, _chg(v.get(oy), v.get(oy - 1))) for k, v in opn["items"]]
            om = [(k, c) for k, c in om if c is not None]
            if om:
                k, c = max(om, key=lambda kc: (abs(kc[1]), kc[0]))
                if abs(c) >= 0.1:
                    found["open_move"] = (f"פתיחות הסניפים {_in_place(k)} "
                                          f"{'עלו' if c > 0 else 'ירדו'} ב-{oy} ב-{fmt.pct(abs(c))}, "
                                          f"השינוי החד ביותר בין המחוזות.")

        extra = [found[k] for k in ("branches", "open_move") if found.get(k)]
        if extra:
            labels["branches_note"] += " " + " ".join(extra)

    # ── insights, KPIs order ─────────────────────────────────────────────
    order = ("nat_dir", "dist_lead", "dist_move", "nat_long", "ind_move", "size", "chains",
             "emp_ind", "branches", "open_move")
    insights = [{"id": k, "text_he": found[k]} for k in order if found.get(k)][:MAX_TOP]

    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}

    n_d = len(jd)
    labels["lede"] = (f"כמה משרות שכיר וכמה מעסיקים יש בכל מחוז בישראל, באילו ענפים הם פועלים, "
                      "וכמה מהמשרות נמצאות ברשתות ארציות. אומדני \"דמוגרפיה של מעסיקים\" של הלשכה "
                      f"המרכזית לסטטיסטיקה (הלמ\"ס), לפי {n_d} מחוזות, מתעדכנים פעם בשנה. הנתון האחרון "
                      f"הוא לשנת {ly}"
                      + (f": {_k(total_ly)} משרות שכיר" if total_ly else "")
                      + (f" ו-{fmt.int_he(e_total)} מעסיקים פעילים" if e_total and ely == ly else "")
                      + ".")
    summary = ("משרות שכיר ומעסיקים פעילים בישראל לפי מחוז וענף כלכלי, לפי אומדני הלמ\"ס"
               + (f": ב-{ly} היו {_k(total_ly)} משרות שכיר" if total_ly else f", {fy}-{ly}")
               + (f" ו-{fmt.int_he(e_total)} מעסיקים" if e_total and ely == ly else "")
               + f". המחוז הגדול: {_place(lead)}"
               + (f", ו-{fmt.pct(chains['total']['chain_jobs'] / chains['total']['jobs'])} מהמשרות "
                  f"ברשתות ארציות." if flags["chains"] and chains["total"] else "."))
    desc = (f"כמה משרות שכיר ומעסיקים יש בכל מחוז ובכל ענף: אומדני הלמ\"ס לשנים {fy}-{ly}"
            + (f", {_k(total_ly)} משרות ב-{ly}" if total_ly else "")
            + f", המוביל {_place(lead)}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{min(fy, efy)}/{max(ly, ely)}",
            "spatial_coverage": "ישראל, לפי מחוזות",
            "seo": {
                "title": "משרות שכיר ומעסיקים לפי מחוז וענף | הלמ\"ס",
                "description": desc,
                "name": "משרות שכיר ומעסיקים לפי מחוז וענף כלכלי",
                "alternate_names": ["דמוגרפיה של מעסיקים", "מספר המעסיקים בישראל",
                                    "מספר משרות השכיר לפי מחוז",
                                    "אומדני משרות שכיר בפילוח גאוגרפי"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "insights": insights,
        "release": release,
        "flags": flags,
    }
