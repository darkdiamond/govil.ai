"""סקר כוח אדם: CBS's monthly labour force survey release (full edition).

CBS publishes two editions a month for the same reference month: a short
"(נתונים עיקריים)" edition with 3 tables, and a week later the full edition
with 22-26 tables. The short edition's tables 1-3 are the full edition's
tables 3-5, number for number, so source.json follows the full edition only
(its title_regex excludes the short one).

Inputs (grids of the newest full edition):
  t3   persons aged 15+ by labour force characteristics, monthly, original
       data (thousands): population, labour force, employed, temporarily
       absent all week (and those absent for economic reasons), unemployed.
       About 21 months; December editions carry a longer history.
  t6   unemployment rate by age and sex: reference month, previous month and
       the same month a year earlier (original data).
  t13  unemployed and persons not in the labour force by reason for leaving
       their last job, three months side by side (original data).
  t15..t22  the release's chart-data files. Their order is NOT stable: a
       January edition puts three foreign-worker tables first, some months
       leave out the three district charts. Each file is therefore recognised
       by its title (`_role`), never by its number:
         unemp       unemployment rate since 2012: trend, SA, original
         unemp_sex   unemployment rate by sex (SA)
         lfpr_sex    participation rate by sex (SA)
         emp_sex     employment rate by sex, ages 15+ and 25-64 (SA)
         dist_*      participation / employment / unemployment by district
                     (SA, previous and reference month); optional
         industry    employed persons by industry (SA, two months); optional
  releases  the edition list (number, date, headline, link)

Header labels raise when missing (the refresh then keeps the last page and
opens an issue); data rows are found by pattern, so a missing one only
shortens a series.
"""
import re

import pandas as pd
from govlib import cbs, fmt

MONTHS = {m: i for i, m in enumerate(fmt.MONTHS_HE, 1)} | {"מרס": 3}
SLOTS = [f"t{n}" for n in range(15, 23)]
REQUIRED_ROLES = ("unemp", "unemp_sex", "lfpr_sex", "emp_sex")
DIST_ROLES = ("dist_lfpr", "dist_emp", "dist_unemp")
RECENT = 21  # months of t3 shown
FLAT_PP = 0.2  # a change below this (percentage points) is "stable"
VAGUE = ("לא ידוע", "סיבה אחרת")


# ── small helpers ────────────────────────────────────────────────────────


def _month_year(label):
    """`ספטמבר 2026` → (2026, 9); None when the cell is not a month label."""
    m = re.fullmatch(r"(\S+)\s+((?:19|20)\d\d)", cbs.clean(label))
    if not m or m.group(1) not in MONTHS:
        return None
    return int(m.group(2)), MONTHS[m.group(1)]


def _month_word(label):
    """`ספטמבר September` → 9 (the Hebrew month opening the cell)."""
    w = cbs.clean(label).split(" ")[0] if label else ""
    return MONTHS.get(w)


def _hebrew_label(row):
    """The row's last cell with Hebrew letters (CBS puts the Hebrew label on
    the right-hand side of a bilingual table)."""
    for c in reversed(row):
        if re.search("[א-ת]", c):
            return c
    return ""


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0] % 100:02d}"


def _r(v, d=2):
    return None if v is None else round(v, d)


def _pp(v):
    """A change in percentage points, signed with U+2212."""
    s = fmt.num_he(abs(v), 1)
    if s == "0.0":
        return "0.0"
    return ("+" if v > 0 else "−") + s


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _title(rows):
    """The table's Hebrew title cell (`תרשים 5. - …` / `לוח 3 - …`)."""
    for r in rows[:10]:
        for c in r:
            if re.match(r"^(תרשים|לוח|טבלה)\s*\d+", c):
                return re.sub(r"\s+,", ",", c)
    return ""


def _role(rows):
    t = _title(rows)
    if not t.startswith("תרשים"):
        return None
    if "לפי מחוזות" in t:
        if "המשתתפים" in t:
            return "dist_lfpr"
        if "תעסוקה" in t:
            return "dist_emp"
        if "הבלתי מועסקים" in t:
            return "dist_unemp"
        return None
    if re.search(r"מועסקים,\s*לפי ענפי כלכלה", t) and "הנעדרים" not in t:
        return "industry"
    if "אחוז הבלתי מועסקים מכוח העבודה" in t:
        return "unemp_sex" if "לפי מין" in t else ("unemp" if "לפי" not in t else None)
    if "אחוז המשתתפים בכוח העבודה" in t and "לפי מין" in t:
        return "lfpr_sex"
    if "שיעורי תעסוקה" in t and "לפי מין" in t:
        return "emp_sex"
    return None


def _col_starting(row, label, name):
    for j, c in enumerate(row):
        if c.startswith(label):
            return j
    raise ValueError(f"{name}: header label {label!r} not found")


# ── tables ───────────────────────────────────────────────────────────────


def _t3(rows):
    """[(period, {pop, lf, emp, absent, econ, unemp})], oldest first."""
    cols = {}
    for key, label in (("pop", "(2+8)"), ("lf", "(3+7)"), ("emp", "(4+5)"),
                       ("unemp", "Unemployed persons"),
                       ("econ", "Thereof: Absent from work all week")):
        # "Unemployed persons" also opens the broad-measure header (column
        # 11, "Unemployed persons and temporarily absent ..."): match whole.
        if key == "unemp":
            label = "בלתי מועסקים Unemployed persons"
        exact = key == "unemp"
        h = cbs.row_with(rows, label, name="t3", contains=not exact)
        cols[key] = cbs.col_after(rows[h], label, 0, contains=not exact)
    start = cbs.row_with(rows, "Thousands", name="t3", contains=True)
    out = {}
    for r in rows[start + 1:]:
        t = _month_year(cbs.cell(r, 0))
        if t is None:
            continue
        v = {k: cbs.val(r, j) for k, j in cols.items()}
        if v["pop"] and v["lf"] and v["emp"] is not None and v["unemp"] is not None:
            out[t] = v
    if not out:
        raise ValueError("t3: no monthly rows")
    return sorted(out.items())


def _t6(rows):
    """({'total'|'men'|'women': [(age, [cur, prev, year_ago])]}, [periods])."""
    h = next((i for i, r in enumerate(rows)
              if sum(_month_year(c) is not None for c in r) >= 2), None)
    if h is None:
        raise ValueError("t6: month header row not found")
    pcols = [(j, _month_year(c)) for j, c in enumerate(rows[h]) if _month_year(c)]
    blocks = {"סך הכל": "total", "סך הכל גברים": "men", "סך הכל נשים": "women"}
    out, cur = {}, None
    for r in rows[h + 1:]:
        heb = _hebrew_label(r)
        if heb in blocks:
            cur = blocks[heb]
            out[cur] = [("all", [cbs.val(r, j) for j, _ in pcols])]
            continue
        if cur is None:
            continue
        age = cbs.cell(r, 0)
        if re.fullmatch(r"\d+-\d+", age) or re.fullmatch(r"\d+ and over", age):
            out[cur].append((age, [cbs.val(r, j) for j, _ in pcols]))
    if "total" not in out:
        raise ValueError("t6: total block not found")
    for k, items in out.items():
        top = max((int(a.split("-")[1]) for a, _ in items if "-" in a), default=0)
        out[k] = [(a, v) for a, v in items
                  if a == "all" or "-" in a or int(a.split(" ")[0]) > top]
    return out, [p for _, p in pcols]


def _t13(rows):
    """Reasons for leaving the last job (total block, people who stopped in
    the last two years): ([(reason, unemp, notlf)], recent_total, period,
    {reason: total a year earlier})."""
    h = next((i for i, r in enumerate(rows)
              if sum(_month_year(c) is not None for c in r) >= 2), None)
    if h is None:
        raise ValueError("t13: month header row not found")
    pcols = [(j, _month_year(c)) for j, c in enumerate(rows[h]) if _month_year(c)]
    lab = cbs.row_with(rows, "אינם בכוח העבודה", h + 1, name="t13")
    j0, jy = pcols[0][0], pcols[-1][0]
    c_not = cbs.col_after(rows[lab], "אינם בכוח העבודה", j0)
    c_un = cbs.col_after(rows[lab], "בלתי מועסקים", j0)
    c_tot = cbs.col_after(rows[lab], "סך הכל", j0)
    y_tot = cbs.col_after(rows[lab], "סך הכל", jy)
    start = cbs.row_with(rows, "לפי: סיבת הפסקת עבודה", lab, name="t13", contains=True)
    recent = None
    for r in rows[lab:start]:
        if "בשנתיים האחרונות" in _hebrew_label(r):
            recent = cbs.val(r, c_tot)
    out, year_ago = [], {}
    for r in rows[start + 1:]:
        heb = cbs.clean(_hebrew_label(r))
        if heb in ("גברים", "נשים") or cbs.cell(r, 0) in ("Men", "Women"):
            break
        tot = cbs.val(r, c_tot)
        if not heb or tot is None:
            continue
        out.append((heb, cbs.val(r, c_un) or 0.0, cbs.val(r, c_not) or 0.0))
        year_ago[heb] = cbs.val(r, y_tot)
    return out, recent, pcols[0][1], pcols[-1][1], year_ago


def _diagram(rows, labels, name):
    """A monthly chart-data block since 2012: {label: {(y, m): value}}."""
    h = cbs.row_with(rows, labels[0], name=name, contains=True)
    cols = {lab: _col_starting(rows[h], lab, name) for lab in labels}
    out = {}
    for lab, j in cols.items():
        out[lab] = {(y, m): cbs.val(rows[i], j)
                    for i, y, m in cbs.monthly_runs(rows, h + 1, len(rows), j)}
    return out


def _district(rows, name):
    """(names, {month: [values]}) of a district chart, months as 1-12."""
    h = cbs.row_with(rows, "ירושלים", name=name)
    cols = [(j, c) for j, c in enumerate(rows[h]) if c and re.search("[א-ת]", c)]
    out = {}
    for r in rows[h + 1:]:
        m = _month_word(cbs.cell(r, 0))
        if m is None:
            continue
        vals = [cbs.val(r, j) for j, _ in cols]
        if any(v is not None for v in vals):
            out[m] = vals
    return [c for _, c in cols], out


def _industry(rows):
    """[(name, previous, current)] and the two month numbers."""
    h = next((i for i, r in enumerate(rows)
              if sum(_month_word(c) is not None for c in r) >= 2), None)
    if h is None:
        raise ValueError("industry chart: month header row not found")
    mcols = [(j, _month_word(c)) for j, c in enumerate(rows[h]) if _month_word(c)]
    (jp, mp), (jc, mc) = mcols[-2], mcols[-1]
    out = []
    for r in rows[h + 1:]:
        name, cur, prev = cbs.cell(r, 0), cbs.val(r, jc), cbs.val(r, jp)
        if name and re.search("[א-ת]", name) and cur is not None:
            out.append((name, prev, cur))
    return out, mp, mc


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    # ── recognise the chart files by title ───────────────────────────────
    roles = {}
    for s in SLOTS:
        rows = cbs.grid(frames[s], s)
        role = _role(rows)
        if role and role not in roles:
            roles[role] = rows
    missing = [r for r in REQUIRED_ROLES if r not in roles]
    if missing:
        raise ValueError(f"chart files not found in t15-t22: {missing}")

    unemp = _diagram(roles["unemp"], ["Trend", "Seasonally adjusted", "Original"], "unemp")
    usex = _diagram(roles["unemp_sex"], ["Women", "Men"], "unemp_sex")
    lsex = _diagram(roles["lfpr_sex"], ["Women", "Men"], "lfpr_sex")
    esex = _diagram(roles["emp_sex"], ["Women 25-64", "Men 25-64", "Women 15+", "Men 15+"],
                    "emp_sex")
    months = sorted(t for t, v in unemp["Seasonally adjusted"].items() if v is not None)
    if not months:
        raise ValueError("unemp: no seasonally adjusted values")

    t3 = _t3(cbs.grid(frames["t3"], "t3"))
    ages, age_periods = _t6(cbs.grid(frames["t6"], "t6"))
    reasons, recent_stop, r_period, r_year_ago_p, r_year_ago = _t13(cbs.grid(frames["t13"], "t13"))

    lt = t3[-1][0]
    derived = []
    for t, v in t3:
        derived.append({
            "t": t,
            "lfpr": v["lf"] / v["pop"] * 100,
            "emp_rate": v["emp"] / v["pop"] * 100,
            "unemp": v["unemp"] / v["lf"] * 100,
            "broad": ((v["unemp"] + (v["econ"] or 0)) / v["lf"] * 100),
            "emp": v["emp"], "unemp_n": v["unemp"], "econ": v["econ"],
        })
    cur = derived[-1]
    by_t = {d["t"]: d for d in derived}
    yago = by_t.get((lt[0] - 1, lt[1]))

    sa = unemp["Seasonally adjusted"]
    sa_t = months[-1]
    sa_now = sa[sa_t]
    sa_yago = sa.get((sa_t[0] - 1, sa_t[1]))

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    d_un = (sa_now - sa_yago) if sa_yago is not None else None
    kpis["unemp"] = {"value": round(sa_now, 2), "display": fmt.pct_of(sa_now),
                     "tone": "brand" if d_un is None or abs(d_un) < FLAT_PP
                     else ("danger" if d_un > 0 else "ok")}
    labels["unemp_kpi"] = f"שיעור האבטלה, {_mname(sa_t)} (מנוכה עונתיות)"
    kpis["lfpr"] = {"value": round(cur["lfpr"], 2), "display": fmt.pct_of(cur["lfpr"]),
                    "tone": "brand"}
    labels["lfpr_kpi"] = f"שיעור ההשתתפות בכוח העבודה, {_mname(lt)}"
    d_emp = (cur["emp_rate"] - yago["emp_rate"]) if yago else None
    kpis["emp_rate"] = {"value": round(cur["emp_rate"], 2), "display": fmt.pct_of(cur["emp_rate"]),
                        "tone": "brand" if d_emp is None or abs(d_emp) < FLAT_PP
                        else ("ok" if d_emp > 0 else "warn")}
    labels["emp_rate_kpi"] = f"שיעור התעסוקה (מועסקים מכלל בני 15 ומעלה), {_mname(lt)}"
    kpis["employed"] = {"value": round(cur["emp"], 1), "display": fmt.int_he(cur["emp"]),
                        "tone": "brand"}
    labels["employed_kpi"] = f"מועסקים, {_mname(lt)} (אלפים)"
    kpis["unemployed"] = {"value": round(cur["unemp_n"], 1), "display": fmt.int_he(cur["unemp_n"]),
                          "tone": "brand"}
    labels["unemployed_kpi"] = f"בלתי מועסקים, {_mname(lt)} (אלפים)"
    gap = cur["broad"] - cur["unemp"]
    kpis["broad"] = {"value": round(cur["broad"], 2), "display": fmt.pct_of(cur["broad"]),
                     "tone": "warn" if gap >= 1 else "brand"}
    labels["broad_kpi"] = "אבטלה כולל נעדרים מהעבודה מסיבות כלכליות"

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables, flags = {}, {}, {}

    trend, orig = unemp["Trend"], unemp["Original"]
    charts["long"] = {"x": [f"{t[0]}-{t[1]:02d}" for t in months],
                      "trend": [_r(trend.get(t)) for t in months],
                      "sa": [_r(sa.get(t)) for t in months],
                      "orig": [_r(orig.get(t)) for t in months]}
    years = sorted({t[0] for t in months})
    tables["long"] = []
    for y in years:
        vals = [sa.get(t) for t in months if t[0] == y]
        lo = min(v for v in vals if v is not None)
        hi = max(v for v in vals if v is not None)
        tables["long"].append([str(y), fmt.pct_of(_mean(vals)), fmt.pct_of(lo), fmt.pct_of(hi),
                               str(len(vals))])

    rec = derived[-RECENT:]
    charts["recent"] = {"x": [_mshort(d["t"]) for d in rec],
                        "unemp": [_r(d["unemp"]) for d in rec],
                        "broad": [_r(d["broad"]) for d in rec]}
    tables["recent"] = [[_mname(d["t"]), fmt.pct_of(d["lfpr"]), fmt.pct_of(d["emp_rate"]),
                         fmt.pct_of(d["unemp"]), fmt.pct_of(d["broad"]), fmt.int_he(d["emp"])]
                        for d in reversed(rec)]

    def sex_chart(series, keys):
        ts = sorted({t for k in keys for t, v in series[k].items() if v is not None})
        return ts, {"x": [f"{t[0]}-{t[1]:02d}" for t in ts],
                    **{f"s{i}": [_r(series[k].get(t)) for t in ts] for i, k in enumerate(keys)}}

    def yearly(series, keys, ts):
        out = []
        for y in sorted({t[0] for t in ts}):
            out.append([str(y)] + [fmt.pct_of(_mean([series[k].get(t) for t in ts if t[0] == y]))
                                   if _mean([series[k].get(t) for t in ts if t[0] == y]) is not None
                                   else "" for k in keys])
        return out

    ts_us, charts["usex"] = sex_chart(usex, ["Women", "Men"])
    tables["usex"] = yearly(usex, ["Women", "Men"], ts_us)
    ts_ls, charts["lsex"] = sex_chart(lsex, ["Women", "Men"])
    tables["lsex"] = yearly(lsex, ["Women", "Men"], ts_ls)
    ekeys = ["Women 25-64", "Men 25-64", "Women 15+", "Men 15+"]
    ts_es, charts["esex"] = sex_chart(esex, ekeys)
    tables["esex"] = yearly(esex, ekeys, ts_es)

    # ages
    age_rows = [(a, v) for a, v in ages["total"] if a != "all"]
    men = dict(ages.get("men", []))
    women = dict(ages.get("women", []))

    def age_label(a):
        return a.replace(" and over", "+")

    charts["age"] = {"names": [age_label(a) for a, _ in age_rows],
                     "cur": [_r(v[0]) for _, v in age_rows],
                     "yago": [_r(v[-1]) for _, v in age_rows],
                     "cur_label": _mname(age_periods[0]), "yago_label": _mname(age_periods[-1])}

    def pcell(v):
        return fmt.pct_of(v) if v is not None else "–"

    tables["age"] = [[age_label(a), pcell(v[0]), pcell(v[-1]),
                      pcell(men.get(a, [None])[0]), pcell(women.get(a, [None])[0])]
                     for a, v in age_rows]
    labels["age_cols"] = ["גיל", _mname(age_periods[0]), _mname(age_periods[-1]),
                          f"גברים, {_mname(age_periods[0])}", f"נשים, {_mname(age_periods[0])}"]

    # districts (optional: some editions leave the district charts out)
    dist = {}
    for role in DIST_ROLES:
        if role in roles:
            # The district charts are 8-row sheets; a cut-off one (no name
            # row) just leaves the optional section out.
            try:
                names, vals = _district(roles[role], role)
            except ValueError:
                continue
            if vals:
                dist[role] = (names, vals)
    flags["district"] = len(dist) == len(DIST_ROLES)
    if flags["district"]:
        names = dist["dist_unemp"][0]
        # The reference month, else the sheet's last row: a January edition
        # lists December and January, and max() would pick December.
        dmonths = list(dist["dist_unemp"][1])
        dm = lt[1] if lt[1] in dmonths else dmonths[-1]
        same = all(dist[r][0] == names and dm in dist[r][1] for r in DIST_ROLES)
        flags["district"] = same
    if flags["district"]:
        dyear = lt[0] if dm <= lt[1] else lt[0] - 1
        dvals = {r: dist[r][1][dm] for r in DIST_ROLES}
        order = sorted(range(len(names)), key=lambda k: (-(dvals["dist_unemp"][k] or 0), names[k]))
        charts["district"] = {"names": [names[k] for k in order],
                              "unemp": [_r(dvals["dist_unemp"][k]) for k in order],
                              "lfpr": [_r(dvals["dist_lfpr"][k]) for k in order],
                              "emp": [_r(dvals["dist_emp"][k]) for k in order]}
        tables["district"] = [[names[k], pcell(dvals["dist_unemp"][k]),
                               pcell(dvals["dist_lfpr"][k]), pcell(dvals["dist_emp"][k])]
                              for k in order]
        labels["district_month"] = _mname((dyear, dm))

    # industries (optional)
    ind = None
    if "industry" in roles:
        ind, ip, ic = _industry(roles["industry"])
    flags["industry"] = bool(ind)
    if ind:
        iyear = lt[0] if ic <= lt[1] else lt[0] - 1
        ind.sort(key=lambda r: (-r[2], r[0]))
        charts["industry"] = {"names": [r[0] for r in ind], "cur": [round(r[2], 1) for r in ind],
                              "chg": [round(r[2] - r[1], 1) if r[1] is not None else None
                                      for r in ind]}
        tables["industry"] = [[r[0], fmt.num_he(r[2], 1),
                               fmt.num_he(r[1], 1) if r[1] is not None else "–",
                               _pp(r[2] - r[1]) if r[1] is not None else "–"] for r in ind]
        prev_t = (iyear, ip) if ip < ic else (iyear - 1, ip)
        labels["ind_cols"] = ["ענף", _mname((iyear, ic)), _mname(prev_t), "שינוי (אלפים)"]
        labels["industry_month"] = _mname((iyear, ic))
        labels["industry_prev"] = _mname(prev_t)

    # reasons for leaving the last job
    # "Not known" and "other reason" go last: they are not a reason to rank.
    reasons.sort(key=lambda r: (r[0] in VAGUE, -(r[1] + r[2]), r[0]))
    flags["reasons"] = len(reasons) >= 3
    charts["reasons"] = {"names": [r[0] for r in reasons], "unemp": [round(r[1], 1) for r in reasons],
                         "notlf": [round(r[2], 1) for r in reasons]}
    tables["reasons"] = [[r[0], fmt.num_he(r[1], 1), fmt.num_he(r[2], 1),
                          fmt.num_he(r[1] + r[2], 1),
                          fmt.num_he(r_year_ago[r[0]], 1) if r_year_ago.get(r[0]) is not None
                          else "–"] for r in reasons]
    labels["reasons_cols"] = ["סיבה", "בלתי מועסקים", "אינם בכוח העבודה",
                              f"סך הכל, {_mname(r_period)}", f"סך הכל, {_mname(r_year_ago_p)}"]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if sa_yago is not None:
        d = sa_now - sa_yago
        if abs(d) < FLAT_PP:
            how = f"כמעט ללא שינוי לעומת {_mname((sa_t[0] - 1, sa_t[1]))} ({fmt.pct_of(sa_yago)})"
        else:
            how = (f"{'עלייה' if d > 0 else 'ירידה'} של {fmt.num_he(abs(d), 1)} נקודות אחוז "
                   f"לעומת {_mname((sa_t[0] - 1, sa_t[1]))} ({fmt.pct_of(sa_yago)})")
        add("level", f"שיעור האבטלה ב{_mname(sa_t)} עמד על {fmt.pct_of(sa_now)} "
                     f"(נתון מנוכה עונתיות), {how}.")

    tr = [(t, v) for t, v in trend.items() if v is not None]
    if len(tr) >= 36:
        t_hi = max(tr, key=lambda tv: (tv[1], tv[0]))
        t_lo = min(tr, key=lambda tv: (tv[1], tv[0]))
        t_now = max(tr)
        add("long", f"מאז {_mname(min(tr)[0])} נע קו המגמה של האבטלה בין {fmt.pct_of(t_lo[1])} "
                    f"({_mname(t_lo[0])}) ל-{fmt.pct_of(t_hi[1])} ({_mname(t_hi[0])}). "
                    f"ב{_mname(t_now[0])} הוא עמד על {fmt.pct_of(t_now[1])}.")

    peak = max(rec, key=lambda d: (d["broad"] - d["unemp"], d["t"]))
    if peak["broad"] - peak["unemp"] >= 2 and peak["econ"]:
        add("broad", f"כשמוסיפים לבלתי מועסקים את מי שנעדרו מהעבודה כל השבוע מסיבות כלכליות "
                     f"(חופשה ללא תשלום, צמצום או השבתה), האבטלה הרחבה הגיעה ב{_mname(peak['t'])} "
                     f"ל-{fmt.pct_of(peak['broad'])}: {fmt.int_he(peak['econ'])} אלף נעדרים כאלה, "
                     f"מול שיעור אבטלה רגיל של {fmt.pct_of(peak['unemp'])}."
                     + (f" ב{_mname(lt)} השיעור הרחב היה {fmt.pct_of(cur['broad'])}."
                        if peak["t"] != lt else ""))

    lw, lm = lsex["Women"].get(ts_ls[-1]), lsex["Men"].get(ts_ls[-1])
    lw0, lm0 = lsex["Women"].get(ts_ls[0]), lsex["Men"].get(ts_ls[0])
    if None not in (lw, lm, lw0, lm0):
        g, g0 = lm - lw, lm0 - lw0
        trend_w = ("הצטמצם" if g < g0 - 0.5 else "התרחב" if g > g0 + 0.5 else "נשאר דומה")
        add("gender", f"שיעור ההשתתפות בכוח העבודה של גברים ({fmt.pct_of(lm)}) גבוה מזה של "
                      f"נשים ({fmt.pct_of(lw)}) ב-{fmt.num_he(g, 1)} נקודות אחוז "
                      f"({_mname(ts_ls[-1])}, מנוכה עונתיות). מאז {_mname(ts_ls[0])} הפער "
                      f"{trend_w}: אז עמד על {fmt.num_he(g0, 1)} נקודות.")

    ew, em = esex["Women 25-64"].get(ts_es[-1]), esex["Men 25-64"].get(ts_es[-1])
    if ew is not None and em is not None:
        add("prime", f"בגילי העבודה העיקריים (25 עד 64) שיעור התעסוקה גבוה בהרבה: "
                     f"{fmt.pct_of(em)} מהגברים ו-{fmt.pct_of(ew)} מהנשים עובדים "
                     f"({_mname(ts_es[-1])}).")

    av = [(a, v[0]) for a, v in age_rows if v[0] is not None]
    tot_rate = ages["total"][0][1][0]
    if av and tot_rate:
        a_hi = max(av, key=lambda x: (x[1], x[0]))
        if a_hi[1] >= 1.5 * tot_rate:
            add("age", f"האבטלה הגבוהה ביותר היא בקבוצת הגיל {age_label(a_hi[0])}: "
                       f"{fmt.pct_of(a_hi[1])} ב{_mname(age_periods[0])}, פי "
                       f"{fmt.num_he(a_hi[1] / tot_rate, 1)} מהשיעור הכללי "
                       f"({fmt.pct_of(tot_rate)}, נתונים מקוריים).")

    if flags["district"]:
        u = [dvals["dist_unemp"][k] for k in order]
        nm = charts["district"]["names"]
        if u[0] is not None and u[-1] is not None and u[0] - u[-1] >= 0.5:
            add("district", f"לפי מחוז המגורים, האבטלה הגבוהה ביותר ב{labels['district_month']} "
                            f"הייתה במחוז {nm[0]} ({fmt.pct_of(u[0])}) והנמוכה ביותר במחוז "
                            f"{nm[-1]} ({fmt.pct_of(u[-1])}).")

    if ind:
        moves = [r for r in ind if r[1] is not None]
        if moves:
            big = max(moves, key=lambda r: (abs(r[2] - r[1]), r[0]))
            d = big[2] - big[1]
            if abs(d) >= 3:
                add("industry", f"השינוי החודשי הגדול ביותר במספר המועסקים היה בענף {big[0]}: "
                                f"{'עלייה' if d > 0 else 'ירידה'} של {fmt.num_he(abs(d), 1)} אלף "
                                f"בין {labels['industry_prev']} ל{labels['industry_month']} "
                                f"(מנוכה עונתיות).")

    known = [r for r in reasons if r[0] not in VAGUE]
    if known and recent_stop:
        top = known[0]
        add("reasons", f"מבין {fmt.int_he(recent_stop)} אלף בני 15 ומעלה שלא עבדו "
                       f"ב{_mname(r_period)} ועזבו את עבודתם האחרונה בשנתיים האחרונות, הסיבה "
                       f"השכיחה ביותר שצוינה: {top[0]} ({fmt.int_he(top[1] + top[2])} אלף).")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"כמה ישראלים עובדים, כמה מחפשים עבודה ולא מוצאים, ומה ההבדלים בין גברים "
                 f"לנשים, בין קבוצות גיל, בין מחוזות ובין ענפים. הנתונים מתוך ההודעה החודשית "
                 f"של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) על סקר כוח אדם, ומתעדכנים עם כל "
                 f"הודעה חדשה. הנתון האחרון הוא ל{_mname(sa_t)}: שיעור אבטלה של "
                 f"{fmt.pct_of(sa_now)} (מנוכה עונתיות)."),
        "long_note": (f"אחוז הבלתי מועסקים מכוח העבודה בכל חודש מאז {_mname(months[0])}: "
                      f"הנתון המקורי, המנוכה עונתיות וקו המגמה. אפשר לגרור כדי להתמקד בתקופה."),
        "long_aria": f"שיעור האבטלה, {_mname(months[0])} עד {_mname(months[-1])}",
        "long_caption": "שיעור האבטלה לפי שנה (מנוכה עונתיות)",
        "recent_note": (f"שיעור האבטלה בכל חודש מאז {_mname(rec[0]['t'])}, לצד האבטלה הרחבה: "
                        f"בלתי מועסקים יחד עם מי שנעדרו מהעבודה כל השבוע מסיבות כלכליות. "
                        f"בטבלה גם מספר המועסקים. נתונים מקוריים, לא מנוכי עונתיות."),
        "recent_aria": f"אבטלה ומועסקים, {_mname(rec[0]['t'])} עד {_mname(rec[-1]['t'])}",
        "recent_caption": "תכונות כוח העבודה לפי חודש",
        "usex_note": "שיעור האבטלה של נשים ושל גברים בכל חודש, מנוכה עונתיות.",
        "usex_aria": "שיעור האבטלה לפי מין",
        "usex_caption": "שיעור האבטלה לפי מין, ממוצע שנתי",
        "lsex_note": ("אחוז המשתתפים בכוח העבודה (עובדים או מחפשים עבודה) מכלל בני 15 ומעלה, "
                      "לנשים ולגברים, מנוכה עונתיות."),
        "lsex_aria": "שיעור ההשתתפות בכוח העבודה לפי מין",
        "lsex_caption": "שיעור ההשתתפות בכוח העבודה לפי מין, ממוצע שנתי",
        "esex_note": ("אחוז המועסקים מכלל האוכלוסייה, לנשים ולגברים, בגילי העבודה העיקריים "
                      "ובכלל בני 15 ומעלה. מנוכה עונתיות."),
        "esex_aria": "שיעור התעסוקה לפי מין וגיל",
        "esex_caption": "שיעור התעסוקה לפי מין וגיל, ממוצע שנתי",
        "age_note": (f"אחוז הבלתי מועסקים מכוח העבודה בכל קבוצת גיל ב{_mname(age_periods[0])}, "
                     f"מול {_mname(age_periods[-1])}. נתונים מקוריים: בקבוצות קטנות הם "
                     f"תנודתיים מחודש לחודש."),
        "age_aria": f"שיעור האבטלה לפי גיל, {_mname(age_periods[0])}",
        "age_caption": "שיעור האבטלה לפי גיל ומין",
        "reasons_note": (f"בני 15 ומעלה שלא עבדו ב{_mname(r_period)} ועזבו את עבודתם האחרונה "
                         f"בשנתיים האחרונות, לפי הסיבה שבגללה הפסיקו לעבוד (אלפים): מי שמחפשים "
                         f"עבודה (בלתי מועסקים) ומי שאינם בכוח העבודה."),
        "reasons_aria": f"סיבות להפסקת עבודה, {_mname(r_period)}",
        "reasons_caption": "סיבת הפסקת העבודה (אלפים)",
        "esex_series": ["נשים 25-64", "גברים 25-64", "נשים 15+", "גברים 15+"],
        "esex_cols": ["שנה", "נשים 25-64", "גברים 25-64", "נשים 15+", "גברים 15+"],
    })
    if flags["district"]:
        labels.update({
            "district_note": (f"שיעור האבטלה, שיעור ההשתתפות בכוח העבודה ושיעור התעסוקה לפי "
                              f"מחוז המגורים ב{labels['district_month']}, מנוכה עונתיות."),
            "district_aria": f"אבטלה ותעסוקה לפי מחוז, {labels['district_month']}",
            "district_caption": "אבטלה, השתתפות ותעסוקה לפי מחוז",
        })
    if ind:
        labels.update({
            "industry_note": (f"מספר המועסקים בכל ענף כלכלי ב{labels['industry_month']} (אלפים, "
                              f"מנוכה עונתיות), והשינוי לעומת {labels['industry_prev']}."),
            "industry_aria": f"מועסקים לפי ענף, {labels['industry_month']}",
            "industry_caption": "מועסקים לפי ענף כלכלי (אלפים)",
        })

    headline = latest_rel["HEADLINE"] if "%" in latest_rel["HEADLINE"] else ""
    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": headline, "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"שיעור האבטלה, ההשתתפות בכוח העבודה והתעסוקה בישראל, לפי חודש, מין, גיל, "
               f"מחוז וענף, מסקר כוח אדם של הלמ\"ס. ב{_mname(sa_t)}: אבטלה של "
               f"{fmt.pct_of(sa_now)}.")
    desc = (f"מה שיעור האבטלה בישראל: {fmt.pct_of(sa_now)} ב{_mname(sa_t)} (מנוכה עונתיות). "
            f"תעסוקה, השתתפות בכוח העבודה, אבטלה לפי גיל, מין ומחוז.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{months[0][0]}/{sa_t[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "שיעור האבטלה בישראל: סקר כוח אדם חודשי | הלמ\"ס",
                "description": desc,
                "name": "שיעור האבטלה וסקר כוח אדם",
                "alternate_names": ["סקר כוח אדם", "סקר כח אדם", "אחוז האבטלה בישראל",
                                    "שיעור התעסוקה בישראל", "שיעור ההשתתפות בכוח העבודה"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
