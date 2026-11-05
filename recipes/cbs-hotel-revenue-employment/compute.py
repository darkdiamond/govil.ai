"""פדיון ותעסוקה במלונות תיירות: CBS's quarterly hotel revenue and jobs release.

Inputs are CBS grid tables (one row per sheet row, cells C01..Cnn) from the
newest edition of the release:
  t1  sheet 1: revenue (current prices: tourists in dollars, Israelis and
      total in shekels) and average revenue per person-night, by year,
      year to date, quarter and month (last two years);
      sheet 2: revenue at constant prices by year since 2010, and monthly
      original, seasonally adjusted and trend series since 2022
  t2  jobs and wages: all jobs, employee jobs, jobs through employment
      agencies, average wage, total wage bill (year, year to date, quarter,
      month)
  t3  chart data: monthly revenue from Israelis and from tourists (2019
      and the last few years, millions of shekels)
  t4  chart data: seasonally adjusted and trend revenue from tourists and
      from Israelis, monthly since 2015 (constant prices)
  releases  the edition list (number, date, headline, link)

Header rows are found by their labels and raise when missing, so a
redesigned table fails the refresh as recipe_failed and keeps the last page.
Data rows (years, quarters, months) are found by pattern: a missing one only
shortens a series. Period kinds are told apart by their label: a year alone,
a range from January (year to date), a three-month range (a quarter) or a
single month. The Q4 edition has no "I-XII" row: the full-year row is then
the year to date.
"""
import re

import pandas as pd
from govlib import cbs, fmt

# A trend run must be at least this long to be worth a sentence.
TREND_RUN = 3
# Year-over-year changes inside this band read as "stable" and colour warn.
FLAT = 0.02


# ── period helpers ───────────────────────────────────────────────────────


def _stop_at_change(rows, start):
    """Index of the "% change" block that ends a level block, or len(rows)."""
    return next((i for i in range(start, len(rows)) if any(
        "% change compared" in c for c in rows[i])), len(rows))


def _split(rows, start, stop, cols):
    """Level-block rows by kind: {"years": {y: rec}, "cum": {(y, end): rec},
    "quarters": {(y, q): rec}, "months": {(y, m): rec}}; rec maps each key of
    `cols` to its value. A row whose values are all missing is skipped."""
    out = {"years": {}, "cum": {}, "quarters": {}, "months": {}}
    for i, y, m, end in cbs.periods(rows, start, stop):
        rec = {k: cbs.val(rows[i], j) for k, j in cols.items()}
        if all(v is None for v in rec.values()):
            continue
        if m is None:
            out["years"][y] = rec
        elif end is None:
            out["months"][(y, m)] = rec
        else:
            if m == 1:
                out["cum"][(y, end)] = rec
            if end == m + 2 and m in (1, 4, 7, 10):
                out["quarters"][(y, (m + 2) // 3)] = rec
    return out


def _ytd(blk):
    """(now, prev, (year, end)) for the newest year-to-date period: a
    January range, or a full year (end 12) when the edition has no range
    row. prev is the same months a year earlier, or None."""
    cands = {**{(y, 12): r for y, r in blk["years"].items()}, **blk["cum"]}
    if not cands:
        return None, None, None
    key = max(cands)
    y, end = key
    prev = cands.get((y - 1, end))
    return cands[key], prev, key


# ── tables ───────────────────────────────────────────────────────────────


def _t1_current(rows):
    """Sheet 1: revenue at current prices and average revenue per night."""
    h = cbs.row_with(rows, "מישראלים", name="t1")
    lab = rows[h]
    rev0 = cbs.col_after(rows[cbs.row_with(rows, "Revenue (millions)", name="t1")],
                         "Revenue (millions)", 0)
    cols = {
        "night_tour_usd": cbs.col_after(lab, "מתיירים", 0),
        "night_isr": cbs.col_after(lab, "מישראלים", 0),
    }
    cols["night_tot"] = cbs.col_after(lab, "סך הכל", cols["night_isr"])
    cols["rev_tour_usd"] = cbs.col_after(lab, "מתיירים", rev0)
    cols["rev_isr"] = cbs.col_after(lab, "מישראלים", rev0)
    cols["rev_tot"] = cbs.col_after(lab, "סך הכל", cols["rev_isr"])
    cur = cbs.row_with(rows, "Dollars", h, name="t1")
    for k, want in (("rev_tour_usd", "Dollars"), ("rev_isr", "NIS"), ("night_isr", "NIS"),
                    ("night_tour_usd", "Dollars")):
        if cbs.cell(rows[cur], cols[k]) != want:
            raise ValueError(f"t1: column {k} is not in {want}")
    stop = _stop_at_change(rows, cur)
    return _split(rows, cur + 1, stop, cols)


def _t1_constant(rows):
    """Sheet 2: yearly revenue at constant prices, and the monthly original /
    seasonally adjusted / trend block. Returns (years block, months list,
    price base label)."""
    c = cbs.row_with(rows, "Constant prices", name="t1")
    mrow = cbs.row_with(rows, "Millions", c, name="t1")
    mcol = cbs.col_after(rows[mrow], "Millions", 0)
    # The price base year ("Millions at 2024 prices"), printed under the label.
    base = next((m.group(0) for i in range(mrow, min(mrow + 4, len(rows)))
                 for j in range(mcol, mcol + 3)
                 for m in [re.search(r"(19|20)\d\d", cbs.cell(rows[i], j))] if m), "")
    lab = rows[cbs.row_with(rows, "Israelis", mrow, name="t1")]
    cols = {"isr": cbs.col_after(lab, "Israelis", mcol), "tour": cbs.col_after(lab, "Tourists", mcol),
            "tot": cbs.col_after(lab, "Total", mcol)}
    sa_row = next((i for i in range(mrow, len(rows))
                   if any(v == "Seasonally adjusted" for v in rows[i])), None)
    yearly = _split(rows, mrow + 1, sa_row if sa_row is not None else len(rows), cols)
    months = []
    if sa_row is not None:
        # Optional: the monthly block sits low in sheet 2.
        hdr = rows[sa_row]
        tr_lbl = cbs.col_after(hdr, "Trend", 0)
        sa_lbl = cbs.col_after(hdr, "Seasonally adjusted", 0)
        mill = [j for j, v in enumerate(rows[sa_row + 1]) if v == "Millions"]
        heb = cbs.row_with(rows, "ישראלים", sa_row, name="t1")
        hl = rows[heb]

        def block(at):
            m = next((j for j in mill if j >= at), None)
            if m is None:
                raise ValueError("t1: monthly block without a Millions column")
            return cbs.col_after(hl, "סך הכל", m)

        pct = cbs.col_after(hl, "סך הכל", 0)
        tr, sa = block(tr_lbl), block(sa_lbl)
        orig = block(cbs.col_after(hdr, "Constant prices", sa_lbl))
        for i, y, m, end in cbs.periods(rows, heb + 1, len(rows)):
            if m is None or end:
                continue
            r = rows[i]
            o = cbs.val(r, orig)
            if o is None:
                continue
            months.append({"t": (y, m), "orig": o, "sa": cbs.val(r, sa), "trend": cbs.val(r, tr),
                           "trend_pct": cbs.val(r, pct)})
        months.sort(key=lambda r: r["t"])
    return yearly, months, base


def _t2(rows):
    """Jobs and wages."""
    h = cbs.row_with(rows, "תשלום ממוצע", name="t2")
    cbs.row_with(rows, "All Jobs", name="t2")
    lab = rows[h]
    pay = cbs.col_after(lab, "תשלום ממוצע", 0)
    wage = cbs.col_after(lab, "ממוצע חודשי", 0)
    bill = cbs.col_after(lab, "סך הכל", wage)
    thereof = cbs.col_after(lab, "מזה:", bill)
    cols = {"all": cbs.col_after(lab, "סך הכל", 0), "agency_pay": pay,
            "agency": cbs.col_after(lab, "משרות", pay), "wage": wage, "bill": bill,
            "employee": thereof, "jobs": cbs.col_after(lab, "סך הכל", thereof)}
    th = cbs.row_with(rows, "Thousands", h, name="t2")
    return _split(rows, th + 1, _stop_at_change(rows, th), cols)


def _t3(rows):
    """Monthly revenue from Israelis and from tourists (chart data)."""
    h = cbs.row_with(rows, "פדיון מישראלים", name="t3")
    isr = cbs.col_after(rows[h], "פדיון מישראלים", 0)
    tour = cbs.col_after(rows[h], "פדיון מתיירים", 0)
    out = {}
    for i, y, m, end in cbs.periods(rows, h + 1, len(rows)):
        if m is None or end:
            continue
        a, b = cbs.val(rows[i], isr), cbs.val(rows[i], tour)
        if a is None and b is None:
            continue
        out[(y, m)] = {"isr": a, "tour": b}
    return out


def _t4(rows):
    """Seasonally adjusted and trend revenue from tourists / Israelis."""
    g = cbs.row_with(rows, "ישראלים", name="t4")
    grp = rows[g]
    lab_i = cbs.row_with(rows, "מנוכי עונתיות", g, name="t4")
    lab = rows[lab_i]
    tc, ic = cbs.col_after(grp, "תיירים", 0), cbs.col_after(grp, "ישראלים", 0)
    cols = {"tour_sa": cbs.col_after(lab, "מנוכי עונתיות", tc)}
    cols["tour_tr"] = cbs.col_after(lab, "מגמה", cols["tour_sa"])
    cols["isr_sa"] = cbs.col_after(lab, "מנוכי עונתיות", ic)
    cols["isr_tr"] = cbs.col_after(lab, "מגמה", cols["isr_sa"])
    out = []
    for i, y, m in cbs.monthly_runs(rows, lab_i + 2, len(rows), cols["tour_sa"]):
        out.append({"t": (y, m), **{k: cbs.val(rows[i], j) for k, j in cols.items()}})
    return out


# ── formatting ───────────────────────────────────────────────────────────


def _m(v):
    """Millions of shekels, no decimals: 5,374."""
    return fmt.int_he(v)


def _k(v, digits=1):
    return fmt.num_he(v, digits)


def _o(v, f=None):
    if v is None:
        return ""
    return (f or _m)(v)


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _range(end, year):
    if end == 12:
        return f"שנת {year}"
    if end == 1:
        return f"ינואר {year}"
    return f"ינואר עד {fmt.MONTHS_HE[end - 1]} {year}"


def _qname(t):
    y, q = t
    return f"{fmt.MONTHS_HE[3 * q - 3]} עד {fmt.MONTHS_HE[3 * q - 1]} {y}"


def _qshort(t):
    y, q = t
    return f"{fmt.MONTHS_SHORT_HE[3 * q - 3]}-{fmt.MONTHS_SHORT_HE[3 * q - 1]} {y}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _word(c):
    if abs(c) < 0.005:
        return "יציבות"
    return "עלייה" if c > 0 else "ירידה"


def _tone(c):
    if c is None:
        return "brand"
    return "ok" if c > FLAT else "danger" if c < -FLAT else "warn"


def _share(part, whole):
    if part is None or not whole:
        return None
    return part / whole


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"].copy()
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    t1rows = cbs.grid(frames["t1"], "t1")
    cur = _t1_current(t1rows)
    const, cmonths, price_base = _t1_constant(t1rows)
    jobs = _t2(cbs.grid(frames["t2"], "t2"))
    m3 = _t3(cbs.grid(frames["t3"], "t3"))
    sa = _t4(cbs.grid(frames["t4"], "t4"))

    now, prev, (yy, ye) = _ytd(cur)
    if now is None or now["rev_tot"] is None:
        raise ValueError("t1: no year-to-date revenue row")
    period = _range(ye, yy)
    period_prev = _range(ye, yy - 1)
    rev_chg = _chg(now["rev_tot"], prev["rev_tot"]) if prev else None

    cnow = const["cum"].get((yy, ye)) or (const["years"].get(yy) if ye == 12 else None)
    cprev = const["cum"].get((yy - 1, ye)) or (const["years"].get(yy - 1) if ye == 12 else None)
    real_chg = _chg(cnow["tot"], cprev["tot"]) if cnow and cprev else None

    jnow, jprev, jkey = _ytd(jobs)
    jobs_chg = _chg(jnow["all"], jprev["all"]) if jnow and jprev else None
    wage_chg = _chg(jnow["wage"], jprev["wage"]) if jnow and jprev else None

    tour_nis = (now["rev_tot"] - now["rev_isr"]) if now["rev_isr"] is not None else None
    tour_share = _share(tour_nis, now["rev_tot"])

    quarters = sorted(cur["quarters"])
    lq = quarters[-1] if quarters else None
    lq_rec = cur["quarters"][lq] if lq else None
    lq_prev = cur["quarters"].get((lq[0] - 1, lq[1])) if lq else None
    lq_chg = _chg(lq_rec["rev_tot"], lq_prev["rev_tot"]) if lq_prev else None

    # Full years at constant prices (the newest full year is in "years").
    cyears = sorted((y, r) for y, r in const["years"].items() if r["tot"] is not None)
    if not cyears:
        raise ValueError("t1: no constant-price yearly rows")
    tour_peak = max(cyears, key=lambda yr: (yr[1]["tour"] or 0, yr[0]))
    last_full = cyears[-1]

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["revenue"] = {"value": now["rev_tot"], "display": _m(now["rev_tot"]),
                       "tone": _tone(rev_chg)}
    labels["revenue_kpi"] = f"פדיון המלונות, {period} (מיליוני ₪)"
    if rev_chg is not None:
        kpis["revenue_chg"] = {"value": round(rev_chg, 4), "display": fmt.signed_pct(rev_chg),
                               "tone": _tone(rev_chg)}
        labels["revenue_chg_kpi"] = f"שינוי בפדיון לעומת {period_prev}"
    if real_chg is not None:
        kpis["real_chg"] = {"value": round(real_chg, 4), "display": fmt.signed_pct(real_chg),
                            "tone": _tone(real_chg)}
        labels["real_chg_kpi"] = "שינוי בפדיון במחירים קבועים (ריאלי)"
    if tour_share is not None:
        kpis["tour_share"] = {"value": round(tour_share, 4), "display": fmt.pct(tour_share),
                              "tone": "info"}
        labels["tour_share_kpi"] = f"חלק הפדיון מתיירים, {period}"
    if jnow and jnow["all"] is not None:
        kpis["jobs"] = {"value": jnow["all"], "display": _k(jnow["all"]), "tone": _tone(jobs_chg)}
        labels["jobs_kpi"] = f"משרות במלונות בממוצע לחודש, {_range(jkey[1], jkey[0])} (אלפים)"
    if jnow and jnow["wage"] is not None:
        kpis["wage"] = {"value": jnow["wage"], "display": _k(jnow["wage"]), "tone": "brand"}
        labels["wage_kpi"] = "שכר ממוצע למשרת שכיר בחודש (אלפי ₪)"

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables = {}, {}
    charts["years"] = {"x": [str(y) for y, _ in cyears],
                       "isr": [r["isr"] for _, r in cyears], "tour": [r["tour"] for _, r in cyears],
                       "share": [round(r["tour"] / r["tot"] * 100, 1) if r["tour"] is not None
                                 and r["tot"] else None for _, r in cyears]}
    tables["years"] = [[str(y), _o(r["tot"]), _o(r["isr"]), _o(r["tour"]),
                        fmt.pct(r["tour"] / r["tot"]) if r["tour"] is not None and r["tot"] else ""]
                       for y, r in reversed(cyears)]

    # Monthly revenue by year (t3): one line per year, months on the x-axis.
    m3_years = sorted({t[0] for t in m3})
    charts["monthly"] = {
        "months": list(fmt.MONTHS_SHORT_HE),
        "years": [str(y) for y in m3_years],
        "isr": [[m3.get((y, m), {}).get("isr") for m in range(1, 13)] for y in m3_years],
        "tour": [[m3.get((y, m), {}).get("tour") for m in range(1, 13)] for y in m3_years],
    }
    tables["monthly_isr"] = [[str(y)] + [_o(m3[(y, m)]["isr"]) if (y, m) in m3 else ""
                                         for m in range(1, 13)] for y in m3_years]
    tables["monthly_tour"] = [[str(y)] + [_o(m3[(y, m)]["tour"]) if (y, m) in m3 else ""
                                          for m in range(1, 13)] for y in m3_years]

    if sa:
        charts["sa"] = {"x": [f"{t[0]}-{t[1]:02d}" for t in (r["t"] for r in sa)],
                        **{k: [r[k] for r in sa] for k in ("tour_sa", "tour_tr", "isr_sa", "isr_tr")}}
        tables["sa"] = [[_mname(r["t"]), _o(r["isr_sa"]), _o(r["isr_tr"]), _o(r["tour_sa"]),
                         _o(r["tour_tr"])] for r in reversed(sa)]

    if quarters:
        charts["quarters"] = {
            "x": [_qshort(q) for q in quarters],
            "isr": [cur["quarters"][q]["rev_isr"] for q in quarters],
            "tour": [round(cur["quarters"][q]["rev_tot"] - cur["quarters"][q]["rev_isr"], 1)
                     if cur["quarters"][q]["rev_isr"] is not None
                     and cur["quarters"][q]["rev_tot"] is not None else None for q in quarters],
        }
        tables["quarters"] = []
        for q in reversed(quarters):
            r, p = cur["quarters"][q], cur["quarters"].get((q[0] - 1, q[1]))
            c = _chg(r["rev_tot"], p["rev_tot"]) if p else None
            tables["quarters"].append([_qname(q), _o(r["rev_tot"]), _o(r["rev_isr"]),
                                       _o(r["rev_tour_usd"]),
                                       fmt.signed_pct(c) if c is not None else ""])

    months = sorted(cur["months"])
    if months:
        charts["nights"] = {"x": [_mshort(t) for t in months],
                            "isr": [cur["months"][t]["night_isr"] for t in months],
                            "tot": [cur["months"][t]["night_tot"] for t in months],
                            "tour": [cur["months"][t]["night_tour_usd"] for t in months]}
        tables["nights"] = [[_mname(t), _o(cur["months"][t]["night_isr"], _k),
                             _o(cur["months"][t]["night_tot"], _k),
                             _o(cur["months"][t]["night_tour_usd"], _k)] for t in reversed(months)]

    jmonths = sorted(jobs["months"])
    if jmonths:
        charts["jobs"] = {"x": [_mshort(t) for t in jmonths],
                          "jobs": [jobs["months"][t]["jobs"] for t in jmonths],
                          "agency": [jobs["months"][t]["agency"] for t in jmonths]}
        tables["jobs"] = [[_mname(t), _o(jobs["months"][t]["all"], _k),
                           _o(jobs["months"][t]["jobs"], _k), _o(jobs["months"][t]["agency"], _k)]
                          for t in reversed(jmonths)]
    jyears = sorted(jobs["years"])
    if jyears:
        charts["wages"] = {"x": [str(y) for y in jyears],
                           "wage": [jobs["years"][y]["wage"] for y in jyears],
                           "pay": [jobs["years"][y]["agency_pay"] for y in jyears]}
        tables["wages"] = [[str(y), _o(jobs["years"][y]["wage"], _k),
                            _o(jobs["years"][y]["agency_pay"], _k),
                            _o(jobs["years"][y]["all"], _k),
                            _o(jobs["years"][y]["bill"] / 1000 if jobs["years"][y]["bill"]
                               is not None else None)]
                           for y in reversed(jyears)]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if rev_chg is not None:
        real = (f" במחירים קבועים השינוי הוא {fmt.signed_pct(real_chg)}." if real_chg is not None
                else "")
        add("ytd", f"ב{period} הסתכם פדיון מלונות התיירות ב-{_m(now['rev_tot'])} מיליון ₪, "
                   f"{_word(rev_chg)} של {fmt.pct(abs(rev_chg))} לעומת {period_prev} "
                   f"({_m(prev['rev_tot'])} מיליון ₪).{real}")
    if lq_chg is not None and lq != (yy, 1):
        add("quarter", f"ברבעון האחרון ({_qname(lq)}) הפדיון היה {_m(lq_rec['rev_tot'])} מיליון ₪, "
                       f"{_word(lq_chg)} של {fmt.pct(abs(lq_chg))} לעומת הרבעון המקביל אשתקד.")
    lf_y, lf = last_full
    pk_y, pk = tour_peak
    if pk_y != lf_y and pk["tour"] and lf["tour"] is not None and pk["tot"]:
        drop = lf["tour"] / pk["tour"]
        if drop < 0.8:
            add("tourists", f"הפדיון מתיירים ב-{lf_y} היה {_m(lf['tour'])} מיליון ₪ במחירים "
                            f"קבועים, {fmt.pct(drop, 0)} בלבד מהשיא ב-{pk_y} "
                            f"({_m(pk['tour'])} מיליון ₪). חלק התיירים בפדיון ירד מ-"
                            f"{fmt.pct(pk['tour'] / pk['tot'])} ל-{fmt.pct(lf['tour'] / lf['tot'])}.")
    if pk_y != lf_y and pk["isr"] and lf["isr"] is not None:
        c = _chg(lf["isr"], pk["isr"])
        if c is not None and abs(c) >= 0.1:
            add("israelis", f"הפדיון מישראלים ב-{lf_y} ({_m(lf['isr'])} מיליון ₪ במחירים קבועים) "
                            f"{'גבוה' if c > 0 else 'נמוך'} ב-{fmt.pct(abs(c))} מהפדיון מישראלים ב-{pk_y}"
                            f"{', ומפצה על חלק מהירידה בתיירות' if c > 0 else ''}.")
    if m3:
        best = max(m3.items(), key=lambda kv: ((kv[1]["isr"] or 0) + (kv[1]["tour"] or 0), kv[0]))
        bt, bv = best
        tot = (bv["isr"] or 0) + (bv["tour"] or 0)
        add("record", f"החודש החזק ביותר בנתוני התרשים הוא {_mname(bt)}, עם פדיון של {_m(tot)} "
                      f"מיליון ₪ ({_m(bv['isr'] or 0)} מישראלים ו-{_m(bv['tour'] or 0)} מתיירים).")
    if cmonths:
        run = 0
        last_pct = cmonths[-1]["trend_pct"]
        for r in reversed(cmonths):
            p = r["trend_pct"]
            if p is None or p == 0 or (last_pct is not None and (p > 0) != (last_pct > 0)):
                break
            run += 1
        if run >= TREND_RUN and last_pct is not None:
            add("trend", f"מגמת הפדיון הכולל במחירים קבועים {'עולה' if last_pct > 0 else 'יורדת'} "
                         f"זה {run} חודשים ברציפות, עד {_mname(cmonths[-1]['t'])} "
                         f"(בנתוני המגמה של הלמ\"ס).")
    if jobs_chg is not None and jnow:
        ag = _share(jnow["agency"], jnow["all"])
        add("jobs", f"ב{_range(jkey[1], jkey[0])} הועסקו במלונות {_k(jnow['all'])} אלף משרות "
                    f"בממוצע לחודש, {_word(jobs_chg)} של {fmt.pct(abs(jobs_chg))} לעומת "
                    f"{_range(jkey[1], jkey[0] - 1)}"
                    + (f"; {fmt.pct(ag)} מהן דרך חברות כוח אדם." if ag is not None else "."))
    if wage_chg is not None and jnow and jprev:
        add("wage", f"השכר הממוצע למשרת שכיר במלונות היה {_k(jnow['wage'])} אלף ₪ "
                    f"בחודש ({_range(jkey[1], jkey[0])}), לעומת {_k(jprev['wage'])} אלף ₪ "
                    f"בתקופה המקבילה אשתקד.")

    # ── text ─────────────────────────────────────────────────────────────
    rel_date = pd.Timestamp(latest_rel["RELEASE_DATE"])
    release = {"no": latest_rel["RELEASE_NO"], "date": fmt.d_he(rel_date),
               "title": latest_rel["TITLE"], "headline": latest_rel["HEADLINE"],
               "url": latest_rel["PAGE_URL"], "pdf": latest_rel["REPORT_PDF_URL"]}
    base = price_base or "קבועים"
    labels.update({
        "lede": (f"כמה מכניסים מלונות התיירות בישראל, מישראלים ומתיירים, כמה עובדים בהם וכמה "
                 f"הם משתכרים. הנתונים מתוך ההודעה הרבעונית של הלשכה המרכזית לסטטיסטיקה "
                 f"(הלמ\"ס) ומתעדכנים עם כל הודעה חדשה. הנתון האחרון: פדיון של "
                 f"{_m(now['rev_tot'])} מיליון ₪ ב{period}."),
        "years_note": (f"פדיון המלונות בכל שנה מאז {cyears[0][0]}, מישראלים ומתיירים, במיליוני ₪ "
                       f"במחירי {base} (מנוטרל אינפלציה). הקו מראה את חלק התיירים בפדיון."),
        "years_aria": f"פדיון המלונות לפי שנה, {cyears[0][0]} עד {cyears[-1][0]}",
        "years_caption": f"פדיון המלונות לפי שנה, מיליוני ₪ במחירי {base}",
        "base": base,
    })
    if m3:
        labels.update({
            "monthly_note": (f"הפדיון בכל חודש (מיליוני ₪, מחירים שוטפים), קו לכל שנה: "
                             f"{fmt.join_he(str(y) for y in m3_years)}. "
                             f"אפשר להסתיר שנה בלחיצה על המקרא."),
            "monthly_isr_aria": "פדיון חודשי מישראלים, קו לכל שנה",
            "monthly_tour_aria": "פדיון חודשי מתיירים, קו לכל שנה",
            "monthly_isr_caption": "פדיון מישראלים לפי שנה וחודש (מיליוני ₪)",
            "monthly_tour_caption": "פדיון מתיירים לפי שנה וחודש (מיליוני ₪)",
        })
    if sa:
        labels.update({
            "sa_note": (f"הפדיון מתיירים ומישראלים בכל חודש מאז {_mname(sa[0]['t'])}, מנוכה "
                        f"עונתיות, עם קו המגמה של הלמ\"ס (מיליוני ₪ במחירי {base}). "
                        f"אפשר לגרור כדי להתמקד בתקופה."),
            "sa_aria": f"פדיון מנוכה עונתיות ומגמה, {_mname(sa[0]['t'])} עד {_mname(sa[-1]['t'])}",
            "sa_caption": f"פדיון מנוכה עונתיות ומגמה (מיליוני ₪ במחירי {base})",
        })
    if quarters:
        labels.update({
            "quarters_note": ("הפדיון בכל רבעון במחירים שוטפים, מישראלים ומתיירים. הפדיון מתיירים "
                              "הוא ההפרש בין הפדיון הכולל לפדיון מישראלים."),
            "quarters_aria": f"פדיון לפי רבעון, {_qname(quarters[0])} עד {_qname(quarters[-1])}",
            "quarters_caption": "פדיון לפי רבעון (מיליוני ₪, הפדיון מתיירים במיליוני דולרים)",
        })
    if months:
        labels.update({
            "nights_note": ("כמה משלם בממוצע אורח על לינה אחת: ישראלים ובסך הכול בשקלים, תיירים "
                            "בדולרים (בטבלה)."),
            "nights_aria": f"פדיון ממוצע ללינה, {_mname(months[0])} עד {_mname(months[-1])}",
            "nights_caption": "פדיון ממוצע ללינה לפי חודש",
        })
    if jmonths:
        labels.update({
            "jobs_note": ("משרות במלונות בכל חודש, באלפים: משרות של עובדי המלון ומשרות נוספות "
                          "של עובדים דרך חברות כוח אדם."),
            "jobs_aria": f"משרות במלונות לפי חודש, {_mname(jmonths[0])} עד {_mname(jmonths[-1])}",
            "jobs_caption": "משרות במלונות לפי חודש (אלפים)",
        })
    if jyears:
        labels.update({
            "wages_note": ("השכר הממוצע לחודש למשרת שכיר במלון, והתשלום הממוצע לחודש למשרה דרך "
                           "חברת כוח אדם, באלפי ₪ (מחירים שוטפים)."),
            "wages_aria": f"שכר ממוצע במלונות לפי שנה, {jyears[0]} עד {jyears[-1]}",
            "wages_caption": "שכר ומשרות במלונות לפי שנה",
        })

    summary = (f"פדיון מלונות התיירות בישראל, מישראלים ומתיירים, ומספר המשרות והשכר במלונות, "
               f"מנתוני הלמ\"ס. ב{period} הסתכם הפדיון ב-{_m(now['rev_tot'])} מיליון ₪"
               + (f" ({fmt.signed_pct(rev_chg)} בשנה)" if rev_chg is not None else "") + ".")
    desc = (f"הכנסות מלונות התיירות בישראל: {_m(now['rev_tot'])} מיליון ₪ ב{period}"
            + (f" ({fmt.signed_pct(rev_chg)})" if rev_chg is not None else "")
            + ". פדיון מישראלים ומתיירים, משרות ושכר.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{cyears[0][0]}/{yy}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "פדיון מלונות התיירות בישראל: נתונים רבעוניים | הלמ\"ס",
                "description": desc,
                "name": "פדיון ותעסוקה במלונות תיירות",
                "alternate_names": ["הכנסות בתי המלון בישראל", "פדיון המלונות",
                                    "תעסוקה במלונות", "שכר עובדי מלונות"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"monthly": bool(m3), "sa": bool(sa), "quarters": bool(quarters),
                  "nights": bool(months), "jobs": bool(jmonths), "wages": bool(jyears)},
    }
