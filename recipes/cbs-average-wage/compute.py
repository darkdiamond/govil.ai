"""השכר הממוצע במשק: CBS's monthly average-wage release.

Inputs are CBS grid tables from the newest edition of the release:
  t1   employee jobs, total wages and average wage (current and constant
       prices), for all jobs (incl. foreign workers) and for Israelis, in
       three sections: original, seasonally adjusted, trend. Annual rows
       (I-XII) for the last full years, monthly rows for about 18 months.
  t8   average wage (Israelis, current prices) by month, one column a year
  t9   average wage by industry, latest month
  t10  average wage at constant prices since 2017: original, SA, trend
  t11  employee jobs by industry, latest month (thousands)
  t12  employee jobs since 2017 (millions): original, SA, trend
  t13  high-tech: average wage and jobs by industry, latest month
  releases  the edition list (number, date, headline, link)

Header rows and columns are found by their labels (govlib.cbs) and raise
when missing; data rows are found by pattern, so a missing one only shortens
a series. "Latest month" is t1's newest original-data row.
"""
import re

import pandas as pd
from govlib import cbs, fmt

MONTHS = {m: i for i, m in enumerate(fmt.MONTHS_HE, 1)} | {"מרס": 3}
TOTAL_NAMES = ("סך הכל", "סה\"כ")
RECENT_MONTHS = 18


# ── tables ───────────────────────────────────────────────────────────────


def _t1(rows):
    """{section: {block: [(period, {measure: value})]}} with sections
    orig/sa/trend, blocks total/israelis, measures jobs/bill/wage/real.
    period = (year, month) for a month, (year, None) for an I-XII row."""
    btot = cbs.row_with(rows, "Total (Incl.", name="t1", contains=True)
    blocks = {"total": cbs.col_after(rows[btot], "Total (Incl.", 0, contains=True),
              "israelis": cbs.col_after(rows[btot], "Jobs of Israelis", 0)}
    mrow = cbs.row_with(rows, "במחירים קבועים", btot, name="t1", contains=True)
    cols = {}
    for b, start in blocks.items():
        cols[b] = {"jobs": cbs.col_after(rows[mrow], "משרות שכיר", start, contains=True),
                   "bill": cbs.col_after(rows[mrow], "סך שכר", start, contains=True),
                   "wage": cbs.col_after(rows[mrow], "במחירים שוטפים", start, contains=True),
                   "real": cbs.col_after(rows[mrow], "במחירים קבועים", start, contains=True)}
    marks = {"orig": "Original data", "sa": "Seasonally adjusted data", "trend": "Trend data"}
    # Original data is required. The SA and trend sections sit at the bottom
    # of the sheet; one that is missing leaves its lines empty.
    starts = {"orig": cbs.row_with(rows, marks["orig"], mrow, name="t1")}
    for k in ("sa", "trend"):
        try:
            starts[k] = cbs.row_with(rows, marks[k], mrow, name="t1")
        except ValueError:
            pass
    order = sorted(starts.items(), key=lambda kv: kv[1])
    out = {"sa": {"total": [], "israelis": []}, "trend": {"total": [], "israelis": []}}
    for n, (sec, s) in enumerate(order):
        stop = order[n + 1][1] if n + 1 < len(order) else len(rows)
        recs = {"total": [], "israelis": []}
        for i, y, m, end in cbs.periods(rows, s + 1, stop):
            if m is not None and end and not (m == 1 and end == 12):
                continue  # a part-year range
            period = (y, None) if (m is None or end) else (y, m)
            for b, lst in recs.items():
                v = {k: cbs.val(rows[i], j) for k, j in cols[b].items()}
                if v["wage"] is not None:
                    lst.append((period, v))
        for lst in recs.values():
            lst.sort(key=lambda r: (r[0][0], r[0][1] or 0))
        out[sec] = recs
    return out


def _named_values(rows, ncols, name="t"):
    """Chart-data rows: a Hebrew name in column 0 and numbers after it.
    Returns [(name, [values])] and the total row (or None)."""
    items, total = [], None
    for r in rows:
        label = cbs.cell(r, 0)
        vals = [cbs.val(r, j) for j in range(1, ncols + 1)]
        if not label or vals[0] is None or not re.search("[א-ת]", label):
            continue
        if label in TOTAL_NAMES or label.startswith("סה\"כ"):
            total = (label, vals)
        else:
            items.append((label, vals))
    if not items:
        raise ValueError(f"{name}: no named rows")
    return items, total


def _t8(rows):
    """{year: {month: wage}} from the month × year chart table."""
    yrow = next((i for i, r in enumerate(rows)
                 if sum(bool(cbs.YEAR.match(c)) for c in r) >= 2), None)
    if yrow is None:
        raise ValueError("t8: year header row not found")
    ycols = {j: int(c) for j, c in enumerate(rows[yrow]) if cbs.YEAR.match(c)}
    out = {y: {} for y in ycols.values()}
    for r in rows[yrow + 1:]:
        m = MONTHS.get(cbs.cell(r, 0))
        if m is None:
            continue
        for j, y in ycols.items():
            v = cbs.val(r, j)
            if v is not None:
                out[y][m] = v
    return {y: v for y, v in out.items() if v}


def _series3(rows, name):
    """A monthly chart table with original / SA / trend columns."""
    h = cbs.row_with(rows, "Original data", name=name, contains=True)
    orig = cbs.col_after(rows[h], "Original data", 0, contains=True)
    sa = cbs.col_after(rows[h], "Seasonally adjusted", 0, contains=True)
    trend = cbs.col_after(rows[h], "Trend", 0, contains=True)
    return [{"t": (y, m), "orig": cbs.val(rows[i], orig), "sa": cbs.val(rows[i], sa),
             "trend": cbs.val(rows[i], trend)}
            for i, y, m in cbs.monthly_runs(rows, h + 1, len(rows), orig)]


def _t13(rows):
    h = cbs.row_with(rows, "משרות שכיר", name="t13")  # the column-header row
    wage = cbs.col_after(rows[h], "שכר ממוצע למשרת שכיר", 0)
    jobs = cbs.col_after(rows[h], "משרות שכיר", 0)
    out, total = [], None
    for r in rows[h + 1:]:
        label, w, n = cbs.cell(r, 0), cbs.val(r, wage), cbs.val(r, jobs)
        if not label or w is None:
            continue
        if "הייטק" in label and label.startswith("סה"):
            total = {"name": label, "wage": w, "jobs": n}
        else:
            out.append({"name": label, "wage": w, "jobs": n})
    return out, total


# ── formatting ───────────────────────────────────────────────────────────


def _ils(v):
    return fmt.int_he(v)


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _word(c):
    return "עלייה" if c > 0 else "ירידה"


def _tone(c, band=0.005):
    if c is None:
        return "brand"
    return "ok" if c > band else "danger" if c < -band else "warn"


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    t1 = _t1(cbs.grid(frames["t1"], "t1"))
    months = {"orig": [r for r in t1["orig"]["total"] if r[0][1] is not None]}
    if not months["orig"]:
        raise ValueError("t1: no monthly original-data rows")
    years = [r for r in t1["orig"]["total"] if r[0][1] is None]
    by_t = dict(months["orig"])
    lt, last = months["orig"][-1]
    prev = by_t.get((lt[0] - 1, lt[1]))
    nominal = _chg(last["wage"], prev["wage"] if prev else None)
    real = _chg(last["real"], prev["real"] if prev else None)
    jobs_chg = _chg(last["jobs"], prev["jobs"] if prev else None)

    by_year = _t8(cbs.grid(frames["t8"], "t8"))
    ind_wage, ind_total = _named_values(cbs.grid(frames["t9"], "t9"), 1, "t9")
    ind_jobs, _ = _named_values(cbs.grid(frames["t11"], "t11"), 1, "t11")
    real_s = [r for r in _series3(cbs.grid(frames["t10"], "t10"), "t10") if r["orig"] is not None]
    jobs_s = [r for r in _series3(cbs.grid(frames["t12"], "t12"), "t12") if r["orig"] is not None]
    hitech, hitech_total = _t13(cbs.grid(frames["t13"], "t13"))

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["wage"] = {"value": round(last["wage"]), "display": _ils(last["wage"]),
                    "tone": _tone(real)}
    labels["wage_kpi"] = f"שכר ממוצע למשרת שכיר, {_mname(lt)} (₪, ברוטו)"
    if nominal is not None:
        kpis["nominal"] = {"value": round(nominal, 4), "display": fmt.signed_pct(nominal),
                           "tone": _tone(nominal)}
        labels["nominal_kpi"] = f"שינוי לעומת {_mname((lt[0] - 1, lt[1]))}"
    if real is not None:
        kpis["real"] = {"value": round(real, 4), "display": fmt.signed_pct(real),
                        "tone": _tone(real)}
        labels["real_kpi"] = "השינוי הריאלי (בניכוי עליית המחירים)"
    if last["jobs"] is not None:
        kpis["jobs"] = {"value": round(last["jobs"], 1), "display": fmt.num_he(last["jobs"], 1),
                        "tone": "brand"}
        labels["jobs_kpi"] = f"משרות שכיר, {_mname(lt)} (אלפים, כולל עובדים זרים)"
    if hitech_total:
        kpis["hitech"] = {"value": round(hitech_total["wage"]),
                          "display": _ils(hitech_total["wage"]), "tone": "info"}
        labels["hitech_kpi"] = "שכר ממוצע בהייטק (₪)"

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables = {}, {}
    rec = {s: {p: v for p, v in t1[s]["total"] if p[1] is not None}
           for s in ("orig", "sa", "trend")}
    rt = sorted(rec["orig"])[-RECENT_MONTHS:]
    charts["recent"] = {"x": [_mshort(t) for t in rt],
                        "orig": [round(rec["orig"][t]["wage"]) for t in rt],
                        "sa": [round(rec["sa"][t]["wage"]) if t in rec["sa"] else None
                               for t in rt],
                        "trend": [round(rec["trend"][t]["wage"]) if t in rec["trend"] else None
                                  for t in rt]}
    tables["recent"] = [[_mname(t), _ils(rec["orig"][t]["wage"]),
                         _ils(rec["sa"][t]["wage"]) if t in rec["sa"] else "",
                         _ils(rec["trend"][t]["wage"]) if t in rec["trend"] else "",
                         _ils(rec["orig"][t]["real"]) if rec["orig"][t]["real"] else ""]
                        for t in reversed(rt)]

    if real_s:
        charts["real"] = {"x": [f"{r['t'][0]}-{r['t'][1]:02d}" for r in real_s],
                          "sa": [round(r["sa"]) if r["sa"] else None for r in real_s],
                          "trend": [round(r["trend"]) if r["trend"] else None for r in real_s]}
        ys = sorted({r["t"][0] for r in real_s})
        tables["real"] = []
        for y in ys:
            vals = [r["orig"] for r in real_s if r["t"][0] == y]
            tables["real"].append([str(y), _ils(_mean(vals)), str(len(vals))])

    if by_year:
        ys = sorted(by_year)
        charts["seasons"] = {"x": fmt.MONTHS_SHORT_HE, "years": [str(y) for y in ys],
                             "series": [[round(by_year[y][m]) if m in by_year[y] else None
                                         for m in range(1, 13)] for y in ys]}
        tables["seasons"] = [[fmt.MONTHS_HE[m - 1]] + [_ils(by_year[y][m]) if m in by_year[y]
                                                       else "" for y in ys]
                             for m in range(1, 13)]
        labels["season_years"] = [str(y) for y in ys]

    wage_by = {n: v[0] for n, v in ind_wage}
    jobs_by = {n: v[0] for n, v in ind_jobs}
    ind = sorted(wage_by, key=lambda n: (-wage_by[n], n))
    total_wage = ind_total[1][0] if ind_total else last["wage"]
    charts["industry"] = {"names": ind, "wage": [round(wage_by[n]) for n in ind],
                          "total": round(total_wage)}
    tables["industry"] = [[n, _ils(wage_by[n]),
                           fmt.signed_pct(wage_by[n] / total_wage - 1, 0)
                           if total_wage else ""] for n in ind]
    both = [n for n in ind if n in jobs_by]
    bill = {n: wage_by[n] * jobs_by[n] for n in both}
    bill_sum = sum(bill.values())
    charts["scatter"] = [{"name": n, "value": [round(jobs_by[n], 1), round(wage_by[n])]}
                         for n in both]
    by_jobs = sorted(both, key=lambda n: (-jobs_by[n], n))
    tables["scatter"] = [[n, fmt.num_he(jobs_by[n], 1), _ils(wage_by[n]),
                          fmt.pct(bill[n] / bill_sum) if bill_sum else ""] for n in by_jobs]

    if jobs_s:
        charts["jobs"] = {"x": [f"{r['t'][0]}-{r['t'][1]:02d}" for r in jobs_s],
                          "sa": [round(r["sa"] * 1000, 1) if r["sa"] else None for r in jobs_s],
                          "trend": [round(r["trend"] * 1000, 1) if r["trend"] else None
                                    for r in jobs_s]}
        tables["jobs"] = []
        for y in sorted({r["t"][0] for r in jobs_s}):
            vals = [r["orig"] for r in jobs_s if r["t"][0] == y]
            tables["jobs"].append([str(y), fmt.num_he(_mean(vals) * 1000, 1), str(len(vals))])

    hitech.sort(key=lambda h: (-h["wage"], h["name"]))
    charts["hitech"] = {"names": [h["name"] for h in hitech],
                        "wage": [round(h["wage"]) for h in hitech],
                        "jobs": [h["jobs"] for h in hitech]}
    tables["hitech"] = [[h["name"], _ils(h["wage"]),
                         fmt.num_he(h["jobs"], 1) if h["jobs"] is not None else ""]
                        for h in hitech]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if nominal is not None and real is not None:
        add("yoy", f"ב{_mname(lt)} השכר הממוצע למשרת שכיר היה {_ils(last['wage'])} ₪, "
                   f"{_word(nominal)} של {fmt.pct(abs(nominal))} לעומת {_mname((lt[0] - 1, lt[1]))}. "
                   f"בניכוי עליית המחירים (במחירים קבועים) זו {_word(real)} של "
                   f"{fmt.pct(abs(real))}.")
    if len(years) >= 2:
        (y1, a), (y0, b) = years[-1], years[-2]
        c = _chg(a["wage"], b["wage"])
        cr = _chg(a["real"], b["real"])
        if c is not None and cr is not None:
            add("annual", f"השכר הממוצע בשנת {y1[0]} כולה היה {_ils(a['wage'])} ₪ לחודש, "
                          f"{_word(c)} של {fmt.pct(abs(c))} לעומת {y0[0]} "
                          f"({fmt.signed_pct(cr)} במחירים קבועים).")
    if len(ind) >= 2 and wage_by[ind[-1]]:
        ratio = wage_by[ind[0]] / wage_by[ind[-1]]
        if ratio >= 1.5:
            add("gap", f"הפער בין הענפים גדול: ב{ind[0]} השכר הממוצע {_ils(wage_by[ind[0]])} ₪, "
                       f"פי {fmt.num_he(ratio, 1)} מאשר ב{ind[-1]} ({_ils(wage_by[ind[-1]])} ₪).")
    if hitech_total and total_wage:
        isr = rec["orig"].get(lt)
        isr_jobs = dict(t1["orig"]["israelis"]).get(lt, {}).get("jobs") if isr else None
        share = (hitech_total["jobs"] / isr_jobs) if isr_jobs and hitech_total["jobs"] else None
        add("hitech", f"בהייטק השכר הממוצע {_ils(hitech_total['wage'])} ₪, פי "
                      f"{fmt.num_he(hitech_total['wage'] / total_wage, 1)} מהממוצע לעובדים ישראלים"
                      + (f". ההייטק מעסיק {fmt.num_he(hitech_total['jobs'], 1)} אלף משרות, "
                         f"{fmt.pct(share)} ממשרות הישראלים" if share else "") + ".")
    if bill_sum and by_jobs:
        big = by_jobs[0]
        top_bill = max(both, key=lambda n: (bill[n], n))
        add("bill", f"הענף עם הכי הרבה משרות הוא {big} ({fmt.num_he(jobs_by[big], 1)} אלף), "
                    f"אבל הכי הרבה שכר משולם ב{top_bill}: {fmt.pct(bill[top_bill] / bill_sum)} "
                    f"מסך השכר בענפים." if big != top_bill else None)
    if len(real_s) >= 25 and real_s[-1]["trend"] and real_s[0]["trend"]:
        first, lastr = real_s[0], real_s[-1]
        c = _chg(lastr["trend"], first["trend"])
        add("real_long", f"מאז {_mname(first['t'])} עלה השכר הממוצע במחירים קבועים "
                         f"(לפי קו המגמה) ב-{fmt.pct(c)}." if c and c > 0 else
                         f"מאז {_mname(first['t'])} ירד השכר הממוצע במחירים קבועים "
                         f"(לפי קו המגמה) ב-{fmt.pct(abs(c))}." if c else None)
    if jobs_chg is not None and abs(jobs_chg) >= 0.005:
        add("jobs", f"מספר משרות השכיר ב{_mname(lt)}: {fmt.num_he(last['jobs'], 1)} אלף, "
                    f"{_word(jobs_chg)} של {fmt.pct(abs(jobs_chg))} בשנה.")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"כמה מרוויח שכיר בישראל בממוצע, איך השכר משתנה מחודש לחודש ומשנה לשנה, "
                 f"ומה הפערים בין ענפי המשק. הנתונים מתוך ההודעה החודשית של הלשכה "
                 f"המרכזית לסטטיסטיקה (הלמ\"ס), ומתעדכנים עם כל הודעה חדשה. הנתון האחרון "
                 f"הוא ל{_mname(lt)}: {_ils(last['wage'])} ₪ ברוטו למשרת שכיר."),
        "recent_note": (f"השכר הממוצע בכל חודש מאז {_mname(rt[0])}, במחירים שוטפים: הנתון "
                        f"המקורי, המנוכה עונתיות וקו המגמה. כולל משרות של עובדים זרים."),
        "recent_aria": f"שכר ממוצע חודשי, {_mname(rt[0])} עד {_mname(rt[-1])}",
        "recent_caption": "שכר ממוצע למשרת שכיר לפי חודש (₪)",
        "industry_note": (f"השכר הממוצע למשרת שכיר בכל ענף כלכלי, עובדים ישראלים. הקו המקווקו "
                          f"הוא הממוצע לכל העובדים הישראלים: {_ils(total_wage)} ₪."),
        "industry_aria": "שכר ממוצע לפי ענף כלכלי",
        "industry_caption": "שכר ממוצע לפי ענף (₪)",
        "scatter_note": ("כל נקודה היא ענף: כמה משרות יש בו וכמה משלמים בו בממוצע. בטבלה "
                         "גם החלק של כל ענף מסך השכר ששולם."),
        "scatter_aria": "משרות שכיר מול שכר ממוצע לפי ענף",
        "scatter_caption": "משרות, שכר ממוצע וחלק מסך השכר לפי ענף",
        "hitech_note": "השכר הממוצע ומספר המשרות בענפי ההייטק, עובדים ישראלים.",
        "hitech_aria": "שכר ממוצע בענפי ההייטק",
        "hitech_caption": "הייטק: שכר ממוצע ומשרות לפי ענף",
    })
    if real_s:
        labels.update({
            "real_note": (f"השכר הממוצע במחירים קבועים (כלומר בניכוי עליית המחירים) מאז "
                          f"{_mname(real_s[0]['t'])}: נתון מנוכה עונתיות וקו מגמה. אפשר "
                          f"לגרור כדי להתמקד בתקופה."),
            "real_aria": f"שכר ממוצע ריאלי, {_mname(real_s[0]['t'])} עד {_mname(real_s[-1]['t'])}",
            "real_caption": "שכר ממוצע במחירים קבועים, ממוצע שנתי (₪)",
        })
    if jobs_s:
        labels.update({
            "jobs_note": (f"מספר משרות השכיר של עובדים ישראלים בכל חודש מאז "
                          f"{_mname(jobs_s[0]['t'])}, באלפים: מנוכה עונתיות וקו מגמה."),
            "jobs_aria": f"משרות שכיר, {_mname(jobs_s[0]['t'])} עד {_mname(jobs_s[-1]['t'])}",
            "jobs_caption": "משרות שכיר, ממוצע שנתי (אלפים)",
        })
    if by_year:
        labels.update({
            "seasons_note": ("השכר הממוצע בכל חודש, שנה מול שנה, במחירים שוטפים. השכר עולה "
                             "בחודשים שבהם משולמים מענקים והפרשים."),
            "seasons_aria": "שכר ממוצע לפי חודש, שנה מול שנה",
            "seasons_caption": "שכר ממוצע לפי חודש ושנה (₪)",
        })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"השכר הממוצע ברוטו למשרת שכיר בישראל, לפי חודש וענף, מנתוני הלמ\"ס. "
               f"ב{_mname(lt)}: {_ils(last['wage'])} ₪"
               + (f" ({fmt.signed_pct(nominal)} בשנה)" if nominal is not None else "") + ".")
    desc = (f"מה השכר הממוצע במשק: {_ils(last['wage'])} ₪ ברוטו ב{_mname(lt)}"
            + (f", {fmt.signed_pct(nominal)} בשנה" if nominal is not None else "")
            + ". שכר ממוצע לפי ענף, הייטק ושכר ריאלי.")
    first_year = min([r["t"][0] for r in real_s] or [lt[0]])
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_year}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "השכר הממוצע במשק: נתון חודשי עדכני | הלמ\"ס",
                "description": desc,
                "name": "השכר הממוצע במשק",
                "alternate_names": ["השכר הממוצע ברוטו למשרת שכיר", "שכר ממוצע בישראל",
                                    "השכר הממוצע בהייטק", "שכר ממוצע לפי ענף"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"real": bool(real_s), "jobs": bool(jobs_s), "seasons": bool(by_year),
                  "hitech": bool(hitech), "scatter": len(both) >= 3},
    }
