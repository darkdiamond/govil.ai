"""מדד אמון הצרכנים: CBS's monthly consumer confidence release.

Inputs are CBS grid tables from the newest edition of the release:
  t1  the index and its four balances (chart 1 and 1a). Each sheet has a
      header row naming the index and the four balances, annual averages
      ("ממוצע 2011" ...) for the early years, then monthly rows (year on the
      first month of a year, Hebrew month names). Sheet 1 averages part of
      2023 ("ממוצע ינואר-ספטמבר"), sheet 1a lists every 2023 month.
  t2  the index in selected OECD countries, latest month (chart 2)
  t3  the relative index (base period = 100): annual averages, then monthly
      rows where only every third month is named (chart 3). A second print
      block to its left repeats older months; it is not read.
  releases  the edition list (number, date, title, links)

The index is the mean of the four balances; a balance is the share of
positive answers minus the share of negative ones, so it runs from -100 to
+100. Header labels are found by text (govlib.cbs, raising when missing);
period rows by pattern, so a missing one only shortens a series.
"""
import re

import pandas as pd
from govlib import cbs, fmt

MONTHS = {m: i for i, m in enumerate(fmt.MONTHS_HE, 1)} | {"מרס": 3}
INDEX_LABEL = "מדד אמון הצרכנים"
# (key, header text the column contains, short Hebrew name)
PARTS = (
    ("past", "שחל במצב הכלכלי של משק הבית", "מצב משק הבית בשנה האחרונה"),
    ("home", "הצפוי במצב הכלכלי של משק הבית", "מצב משק הבית בשנה הקרובה"),
    ("country", "הצפוי במצב הכלכלי במדינה", "מצב המדינה בשנה הקרובה"),
    ("buy", "רכישות גדולות", "רכישות גדולות בשנה הקרובה"),
)
ANNUAL = re.compile(r"^ממוצע (\d{4})$")
BASE = 100.0  # the relative index's base period, by definition
MOVE = 0.5    # points: a smaller monthly move reads as "about unchanged"
GAP = 5.0     # points: personal vs national outlook gap worth a sentence
LOOKBACK = 6  # months: "highest since" needs at least this many months back


# ── tables ───────────────────────────────────────────────────────────────


def _t1(rows):
    """(monthly {(y, m): {index, parts...}}, annual {y: {...}}) from every
    sheet. The first sheet that lists a month wins."""
    heads = [i for i, r in enumerate(rows) if INDEX_LABEL in r]
    if not heads:
        raise ValueError(f"t1: header label {INDEX_LABEL!r} not found")
    monthly, annual = {}, {}
    for n, h in enumerate(heads):
        hdr = rows[h]
        cols = {"index": cbs.col_after(hdr, INDEX_LABEL, 0)}
        for key, label, _ in PARTS:
            cols[key] = cbs.col_after(hdr, label, 0, contains=True)
        stop = heads[n + 1] if n + 1 < len(heads) else len(rows)
        body = rows[h + 1:stop]
        lcol = cbs.best_col(body, lambda v: v in MONTHS or bool(ANNUAL.match(v)))
        ycol = cbs.best_col(body, lambda v: bool(cbs.YEAR.match(v)), exclude={lcol})
        if lcol is None:
            raise ValueError("t1: no month column")
        year = None
        for r in body:
            if ycol is not None and cbs.YEAR.match(cbs.cell(r, ycol)):
                year = int(cbs.cell(r, ycol))
            rec = {k: cbs.val(r, j) for k, j in cols.items()}
            if rec["index"] is None:
                continue
            label = cbs.cell(r, lcol)
            a = ANNUAL.match(label)
            if a:
                annual.setdefault(int(a.group(1)), rec)
            elif label in MONTHS and year is not None:
                monthly.setdefault((year, MONTHS[label]), rec)
    return monthly, annual


def _t2(rows):
    """(period label, [(country, value)]) from the OECD comparison table."""
    h = cbs.row_with(rows, "מדינה", name="t2")
    ncol = cbs.col_after(rows[h], "מדינה", 0)
    vcol = next((j for j in range(len(rows[h])) if j != ncol and rows[h][j]), None)
    if vcol is None:
        raise ValueError("t2: period column not found")
    out = []
    for r in rows[h + 1:]:
        name, v = cbs.cell(r, ncol), cbs.val(r, vcol)
        if name and v is not None and re.search("[א-ת]", name):
            out.append((name, v))
    return re.sub(r"\s*-\s*", " ", rows[h][vcol]), out


def _t3(rows):
    """(annual {y: v}, monthly {(y, m): v}, base text) of the relative index.
    Monthly rows carry the year on a year's first month and a month name on
    every third month: months are counted from the year row and checked
    against the names."""
    h = cbs.row_with(rows, "שנה", name="t3")  # the column-header row
    hdr = rows[h]
    vcol = cbs.col_after(hdr, "מדד אמון הצרכנים היחסי", 0, contains=True)
    ycol = cbs.col_after(hdr, "שנה", 0)
    mcol = cbs.col_after(hdr, "חודש", 0)
    base = next((c for r in rows[:h] for c in r if "= 100" in c), "")
    annual, monthly = {}, {}
    year, month = None, 0
    for r in rows[h + 1:]:
        v = cbs.val(r, vcol)
        if v is None:
            continue
        y, label = cbs.cell(r, ycol), cbs.cell(r, mcol)
        a = ANNUAL.match(label)
        if a:
            annual.setdefault(int(a.group(1)), v)
            continue
        if cbs.YEAR.match(y):
            year, month = int(y), 1
        elif year is not None:
            month += 1
        else:
            continue
        if label in MONTHS and MONTHS[label] != month:
            raise ValueError(f"t3: month {label} on month {month} of {year}")
        if month > 12:
            raise ValueError(f"t3: more than 12 months in {year}")
        monthly.setdefault((year, month), v)
    return annual, monthly, base


# ── formatting ───────────────────────────────────────────────────────────


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _n(v, digits=1):
    """A level, minus as U+2212: -12.739 → '−12.7'."""
    s = fmt.num_he(abs(v), digits)
    return (fmt.MINUS + s) if round(v, digits) < 0 else s


def _s(v, digits=1):
    """A change in points with its sign: '+4.6', '−2.0', '0.0'."""
    s = fmt.num_he(abs(v), digits)
    if float(s) == 0:
        return s
    return ("+" if v > 0 else fmt.MINUS) + s


def _iso(s):
    return fmt.isolate(s)


def _r(v, digits=2):
    return None if v is None else round(v, digits)


def _tone(c, band=1.0):
    if c is None:
        return "brand"
    return "ok" if c >= band else "danger" if c <= -band else "warn"


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    monthly, annual = _t1(cbs.grid(frames["t1"], "t1"))
    if not monthly:
        raise ValueError("t1: no monthly rows")
    months = sorted(monthly)
    lt = months[-1]
    last = monthly[lt]
    prev_t = (lt[0], lt[1] - 1) if lt[1] > 1 else (lt[0] - 1, 12)
    prev = monthly.get(prev_t)
    yago_t = (lt[0] - 1, lt[1])
    yago = monthly.get(yago_t)
    mom = last["index"] - prev["index"] if prev else None
    yoy = last["index"] - yago["index"] if yago else None

    # Annual averages: CBS's own rows, then the mean of a full year's months.
    computed_years = []
    for y in sorted({t[0] for t in months}):
        if y in annual:
            continue
        recs = [monthly[(y, m)] for m in range(1, 13) if (y, m) in monthly]
        if len(recs) == 12:
            annual[y] = {k: (sum(r[k] for r in recs) / 12
                             if all(r[k] is not None for r in recs) else None)
                         for k in recs[0]}
            computed_years.append(y)
    years = sorted(annual)

    oecd_period, oecd = _t2(cbs.grid(frames["t2"], "t2"))
    rel_annual, rel_monthly, rel_base = _t3(cbs.grid(frames["t3"], "t3"))

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["index"] = {"value": _r(last["index"]), "display": _n(last["index"]),
                     "tone": _tone(yoy if yoy is not None else mom)}
    labels["index_kpi"] = f"מדד אמון הצרכנים, {_mname(lt)}"
    if mom is not None:
        kpis["mom"] = {"value": _r(mom), "display": _s(mom), "tone": _tone(mom)}
        labels["mom_kpi"] = f"שינוי בנקודות לעומת {_mname(prev_t)}"
    if yoy is not None:
        kpis["yoy"] = {"value": _r(yoy), "display": _s(yoy), "tone": _tone(yoy)}
        labels["yoy_kpi"] = f"שינוי בנקודות לעומת {_mname(yago_t)}"
    rel_last_t = max(rel_monthly) if rel_monthly else None
    if rel_last_t:
        rv = rel_monthly[rel_last_t]
        kpis["relative"] = {"value": _r(rv), "display": fmt.num_he(rv, 1),
                            "tone": "ok" if rv >= BASE else "warn"}
        labels["relative_kpi"] = f"המדד היחסי, {_mname(rel_last_t)} (תקופת הבסיס = {fmt.int_he(BASE)})"
    countries = [(n, v) for n, v in oecd if "גוש" not in n]
    isr = next((v for n, v in countries if n == "ישראל"), None)
    if isr is not None and len(countries) >= 3:
        rank = 1 + sum(1 for n, v in countries if n != "ישראל" and v > isr)
        kpis["rank"] = {"value": rank, "display": str(rank), "tone": "info"}
        labels["rank_kpi"] = (f"מקומה של ישראל מבין {len(countries)} מדינות OECD בלוח "
                              f"(מקום ראשון = האמון הגבוה ביותר)")
    else:
        rank = None

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables = {}, {}
    charts["monthly"] = {"x": [_mshort(t) for t in months],
                         "y": [_r(monthly[t]["index"]) for t in months]}
    tables["monthly"] = [[_mname(t), _n(monthly[t]["index"]),
                          _s(monthly[t]["index"] - monthly[p]["index"])
                          if (p := ((t[0], t[1] - 1) if t[1] > 1 else (t[0] - 1, 12))) in monthly
                          else ""]
                         for t in reversed(months)]

    part_names = [p[2] for p in PARTS]
    have_yago = yago is not None and all(yago[k] is not None for k, _, _ in PARTS)
    charts["latest"] = {"names": part_names + ["המדד (ממוצע הארבעה)"],
                        "now": [_r(last[k]) for k, _, _ in PARTS] + [_r(last["index"])],
                        "ago": ([_r(yago[k]) for k, _, _ in PARTS] + [_r(yago["index"])]
                                if have_yago else None),
                        "now_name": _mname(lt), "ago_name": _mname(yago_t)}
    tables["latest"] = [[name, _n(last[k]) if last[k] is not None else "",
                         _n(yago[k]) if have_yago else "",
                         _s(last[k] - yago[k]) if have_yago and last[k] is not None else ""]
                        for (k, _, _), name in zip(PARTS, part_names)]
    tables["latest"].append(["המדד (ממוצע הארבעה)", _n(last["index"]),
                             _n(yago["index"]) if yago else "",
                             _s(yoy) if yoy is not None else ""])

    charts["parts"] = {"x": [_mshort(t) for t in months], "names": part_names,
                       "series": [[_r(monthly[t][k]) for t in months] for k, _, _ in PARTS]}
    tables["parts"] = [[_mname(t)] + [_n(monthly[t][k]) if monthly[t][k] is not None else ""
                                      for k, _, _ in PARTS] for t in reversed(months)]

    charts["annual"] = {"x": [str(y) for y in years],
                        "y": [_r(annual[y]["index"]) for y in years]}
    tables["annual"] = [[str(y) + (" *" if y in computed_years else "")]
                        + [_n(annual[y][k]) if annual[y].get(k) is not None else ""
                           for k in ["index"] + [p[0] for p in PARTS]] for y in years]

    rel_x, rel_y = [], []
    for y in sorted(rel_annual):
        if not rel_monthly or y < min(rel_monthly)[0]:
            rel_x.append(str(y))
            rel_y.append(_r(rel_annual[y]))
    for t in sorted(rel_monthly):
        rel_x.append(_mshort(t))
        rel_y.append(_r(rel_monthly[t]))
    charts["relative"] = {"x": rel_x, "y": rel_y, "base": BASE}
    tables["relative"] = [[x, fmt.num_he(v, 1)] for x, v in zip(rel_x, rel_y)][::-1]

    oecd_sorted = sorted(oecd, key=lambda nv: (-nv[1], nv[0]))
    charts["oecd"] = {"names": [n for n, _ in oecd_sorted],
                      "values": [v for _, v in oecd_sorted]}
    tables["oecd"] = [[n, _n(v)] for n, v in oecd_sorted]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if mom is not None:
        if abs(mom) < MOVE:
            move = f"כמעט ללא שינוי לעומת {_mname(prev_t)}"
        else:
            move = (f"{'עלייה' if mom > 0 else 'ירידה'} של {fmt.num_he(abs(mom), 1)} נקודות "
                    f"לעומת {_mname(prev_t)}")
        add("mom", f"ב{_mname(lt)} עמד מדד אמון הצרכנים על {_iso(_n(last['index']))}, {move}"
                   + (f", ו{'עלייה' if yoy > 0 else 'ירידה'} של {fmt.num_he(abs(yoy), 1)} "
                      f"נקודות לעומת {_mname(yago_t)}." if yoy is not None and abs(yoy) >= MOVE
                      else "."))

    # Highest / lowest since: the latest month against every earlier month.
    earlier = months[:-1]
    if len(earlier) >= LOOKBACK and mom is not None and abs(mom) >= MOVE:
        up = mom > 0
        v = last["index"]
        beat = [t for t in earlier if (monthly[t]["index"] >= v if up else monthly[t]["index"] <= v)]
        if not beat:
            add("record", f"זו הרמה {'הגבוהה' if up else 'הנמוכה'} ביותר של המדד בכל החודשים "
                          f"שבלוח, מאז {_mname(months[0])}.")
        else:
            since = beat[-1]
            gap = (lt[0] - since[0]) * 12 + lt[1] - since[1]
            if gap > LOOKBACK:
                add("record", f"זו הרמה {'הגבוהה' if up else 'הנמוכה'} ביותר של המדד מאז "
                              f"{_mname(since)} ({_iso(_n(monthly[since]['index']))}).")

    vals = [(last[k], name) for (k, _, _), name in zip(PARTS, part_names) if last[k] is not None]
    if len(vals) == len(PARTS):
        hi = max(vals, key=lambda x: (x[0], x[1]))
        lo = min(vals, key=lambda x: (x[0], x[1]))
        pos = [nm for v, nm in vals if v > 0]
        tail = ""
        if len(pos) == 1:
            tail = " וזה המאזן החיובי היחיד מבין הארבעה"
        elif not pos:
            tail = ", ובכל הארבעה רוב המשיבים שליליים"
        add("parts", f"מבין ארבעת המרכיבים, הפסימי ביותר ב{_mname(lt)} הוא {lo[1]} "
                     f"({_iso(_n(lo[0]))}), והאופטימי ביותר הוא {hi[1]} "
                     f"({_iso(_n(hi[0]))}){tail}.")

    if last["home"] is not None and last["country"] is not None:
        gap = last["home"] - last["country"]
        if abs(gap) >= GAP:
            if gap > 0:
                add("gap", f"הציבור אופטימי יותר לגבי מצבו הכלכלי שלו מאשר לגבי מצב המדינה: "
                           f"הציפייה לשנה הקרובה למשק הבית עומדת על {_iso(_n(last['home']))}, "
                           f"ולמדינה על {_iso(_n(last['country']))}, פער של "
                           f"{fmt.num_he(gap, 1)} נקודות.")
            else:
                add("gap", f"הציבור פסימי יותר לגבי מצבו הכלכלי שלו מאשר לגבי מצב המדינה: "
                           f"הציפייה לשנה הקרובה למשק הבית עומדת על {_iso(_n(last['home']))}, "
                           f"ולמדינה על {_iso(_n(last['country']))}.")

    if len(years) >= 3:
        ly, py = years[-1], years[-2]
        a, b = annual[ly]["index"], annual[py]["index"]
        best = max(years, key=lambda y: (annual[y]["index"], -y))
        worst = min(years, key=lambda y: (annual[y]["index"], y))
        add("annual", f"הממוצע השנתי של המדד ב-{ly} היה {_iso(_n(a))}, לעומת {_iso(_n(b))} "
                      f"ב-{py}. מאז {years[0]}, השנה האופטימית ביותר הייתה {best} "
                      f"({_iso(_n(annual[best]['index']))}) והפסימית ביותר {worst} "
                      f"({_iso(_n(annual[worst]['index']))}).")

    if rel_last_t and rel_annual:
        rv = rel_monthly[rel_last_t]
        low_y = min(rel_annual, key=lambda y: (rel_annual[y], y))
        side = "מעל " if rv >= BASE else "מתחת ל"
        add("relative", f"במדד היחסי, שבו תקופת הבסיס שווה {fmt.int_he(BASE)}, הערך ב"
                        f"{_mname(rel_last_t)} הוא {fmt.num_he(rv, 1)}: {side}רמת האמון של "
                        f"תקופת הבסיס, ולעומת {fmt.num_he(rel_annual[low_y], 1)} בממוצע "
                        f"{low_y}, השנה הנמוכה ביותר בלוח.")

    if rank is not None:
        euro = next((v for n, v in oecd if "גוש האירו" in n), None)
        add("oecd", f"בהשוואה בין-לאומית ({oecd_period}), ישראל במקום {rank} מבין "
                    f"{len(countries)} מדינות OECD בלוח, עם {_iso(_n(isr))}"
                    + (f", {'מעל ' if isr > euro else 'מתחת ל'}ממוצע גוש האירו "
                       f"({_iso(_n(euro))})" if euro is not None and euro != isr else "") + ".")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"עד כמה הציבור בישראל אופטימי לגבי מצבו הכלכלי ומצב המשק. מדד אמון "
                 f"הצרכנים של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) נבנה מסקר חודשי של משקי "
                 f"בית, ומתעדכן עם כל הודעה חדשה. ב{_mname(lt)} עמד המדד על "
                 f"{_iso(_n(last['index']))}, בסולם שבין מינוס {fmt.int_he(100)} "
                 f"(כולם פסימיים) לפלוס {fmt.int_he(100)} (כולם אופטימיים)."),
        "monthly_note": (f"ערך המדד בכל חודש מאז {_mname(months[0])}. ערך שלילי פירושו שיותר "
                         f"משיבים צופים הרעה מאשר שיפור."),
        "monthly_aria": f"מדד אמון הצרכנים לפי חודש, {_mname(months[0])} עד {_mname(lt)}",
        "monthly_caption": "מדד אמון הצרכנים לפי חודש",
        "latest_note": (f"ארבע השאלות שמהן בנוי המדד: המאזן בכל אחת ב{_mname(lt)}"
                        + (f", לעומת {_mname(yago_t)}." if have_yago else ".")
                        + " מאזן הוא אחוז התשובות החיוביות פחות אחוז התשובות השליליות."),
        "latest_aria": f"מרכיבי מדד אמון הצרכנים, {_mname(lt)}",
        "latest_caption": "מאזני מרכיבי המדד",
        "parts_note": (f"ארבעת המאזנים בכל חודש מאז {_mname(months[0])}. אפשר להסתיר מרכיב "
                       f"בלחיצה על המקרא."),
        "parts_aria": f"מאזני מרכיבי המדד לפי חודש, {_mname(months[0])} עד {_mname(lt)}",
        "parts_caption": "מאזני מרכיבי המדד לפי חודש",
        "annual_note": (f"הממוצע השנתי של המדד מאז {years[0]}"
                        + (f". לשנים {fmt.join_he([str(y) for y in computed_years])} הממוצע "
                           f"מחושב כאן מנתוני החודשים (מסומן בכוכבית בטבלה)."
                           if len(computed_years) > 1 else
                           f". לשנת {computed_years[0]} הממוצע מחושב כאן מנתוני החודשים "
                           f"(מסומן בכוכבית בטבלה)." if computed_years else ".")),
        "annual_aria": f"ממוצע שנתי של מדד אמון הצרכנים, {years[0]} עד {years[-1]}",
        "annual_caption": "ממוצע שנתי של המדד ומרכיביו",
        "relative_note": ("המדד היחסי מציג את אותו מדד ביחס לתקופת בסיס"
                          + (f" ({rel_base})" if rel_base else "")
                          + ": ערך מעל הקו המקווקו פירושו אמון גבוה מזה של תקופת הבסיס. "
                            "השנים הראשונות מוצגות כממוצע שנתי, ואחריהן כל חודש."),
        "relative_aria": "מדד אמון הצרכנים היחסי לאורך השנים",
        "relative_caption": "מדד אמון הצרכנים היחסי",
        "oecd_note": (f"מדד אמון הצרכנים במדינות OECD נבחרות, {oecd_period}, לפי נתוני "
                      f"OECD. ישראל מודגשת."),
        "oecd_aria": f"מדד אמון הצרכנים במדינות OECD, {oecd_period}",
        "oecd_caption": "מדד אמון הצרכנים לפי מדינה",
    })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "url": latest_rel["PAGE_URL"], "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"מדד אמון הצרכנים של הלמ\"ס ומרכיביו לפי חודש, ממוצע שנתי והשוואה "
               f"למדינות OECD. ב{_mname(lt)}: {_n(last['index'])}"
               + (f" ({_s(mom)} נקודות בחודש)" if mom is not None else "") + ".")
    desc = (f"מדד אמון הצרכנים בישראל: {_n(last['index'])} ב{_mname(lt)}"
            + (f", {_s(mom)} נקודות מהחודש הקודם" if mom is not None else "")
            + ". ארבעת מרכיבי המדד, ממוצע שנתי והשוואה ל-OECD.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0] if years else months[0][0]}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מדד אמון הצרכנים: נתון חודשי עדכני | הלמ\"ס",
                "description": desc,
                "name": "מדד אמון הצרכנים",
                "alternate_names": ["מדד אמון הצרכנים בישראל", "אמון הצרכנים",
                                    "סקר אמון הצרכנים", "מדד אמון הצרכנים היחסי"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"latest": True, "annual": len(years) >= 2,
                  "relative": len(rel_x) >= 2, "oecd": len(oecd) >= 3},
    }
