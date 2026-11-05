"""לינות במלונות תיירות: CBS's monthly person-nights-in-tourist-hotels release.

Inputs are CBS grid tables (one row per sheet row, cells C01..Cnn) from the
newest edition of the release:
  t1  person-nights by Israelis and tourists: a yearly block (since 2011,
      plus the year to date for this year and last) and a monthly block
      (since 2019): trend % change, trend, seasonally adjusted, evacuees
      (Oct 2023 to Jun 2025), original data
  releases  the edition list (number, date, headline, link)

The release also ships t2 (chart data: the same monthly original series) and
t3 (an .xls of SA/trend since 2010, missing from the May 2026 edition, which
named it t4). Neither is read: t1 holds everything t2 does, and a recipe that
needs t3 would fail every edition that misnames it.

Header rows are found by their (English) labels and raise when missing, so a
redesigned table fails the refresh as recipe_failed and keeps the last page.
Data rows (years, months) are found by pattern: a missing one only shortens a
series. The SA / trend / evacuee columns are optional. All values are
thousands of person-nights.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TONE_BAND = 0.02
BASE_YEAR = 2019  # the last year before COVID and the war; the series start
TREND_RUN_MIN = 3
SHARE_GAP = 0.05
_RANGE = re.compile(r"^(?:([IVX]+)(?:-([IVX]+))?)?(\d{4})$")
_MONTH = re.compile(r"^(1[0-2]|[1-9])$")


# ── t1 ───────────────────────────────────────────────────────────────────


def _label(v):
    """A period label without footnote marks or spaces: "(*) I-IX 2026" →
    "I-IX2026", "(*)2025" → "2025"."""
    return re.sub(r"[()*\s]", "", v)


def _triple(row, start):
    """Columns of the first Israelis / Tourists / Total run at or after
    `start`."""
    isr = cbs.col_after(row, "Israelis", start)
    tour = cbs.col_after(row, "Tourists", isr)
    tot = cbs.col_after(row, "Total", tour)
    if tot - isr != 2:
        raise ValueError(f"t1: Israelis/Tourists/Total not adjacent at column {isr}")
    return isr, tour, tot


def _yearly(rows, stop):
    """Whole years and year-to-date rows of the top block."""
    t = cbs.row_with(rows, "Thousands", name="t1")
    thou = cbs.col_after(rows[t], "Thousands", 0)
    h = cbs.row_with(rows, "Israelis", t, name="t1")
    isr, tour, tot = _triple(rows[h], thou)
    body = rows[h + 1:stop]
    lcol = cbs.best_col(body, lambda v: bool(_RANGE.match(_label(v))),
                        exclude={isr, tour, tot})
    if lcol is None:
        raise ValueError("t1: no year label column in the yearly block")
    years, ytd = [], []
    for r in body:
        lab = _label(cbs.cell(r, lcol))
        m = _RANGE.match(lab)
        rec = {"isr": cbs.val(r, isr), "tour": cbs.val(r, tour), "tot": cbs.val(r, tot)}
        if not m or rec["tot"] is None:
            continue
        y = int(m.group(3))
        if not m.group(1) and lab == str(y):
            years.append({"year": y, **rec})
        elif m.group(1) in cbs.ROMAN and cbs.ROMAN[m.group(1)] == 1:
            end = cbs.ROMAN.get(m.group(2)) if m.group(2) else 1
            if end:
                ytd.append({"year": y, "end": end, **rec})
    # "(*)2025" (December edition, provisional) also matches the plain form.
    years = sorted({y["year"]: y for y in years}.values(), key=lambda y: y["year"])
    ytd.sort(key=lambda y: y["year"])
    return years, ytd


def _monthly(rows):
    """Monthly rows: original (required), SA / trend / evacuees (optional)."""
    tr_h = cbs.row_with(rows, "Trend", name="t1")
    orig_h = cbs.row_with(rows, "Original data", tr_h, name="t1")
    lab = cbs.row_with(rows, "Israelis", orig_h, name="t1")
    labels = rows[lab]
    orig = _triple(labels, cbs.col_after(rows[orig_h], "Original data", 0))
    cols = {"orig": orig}
    for key, text in (("trend", "Trend"), ("sa", "Seasonally adjusted")):
        try:
            c = _triple(labels, cbs.col_after(rows[tr_h], text, 0))
        except ValueError:
            continue
        if c[0] < orig[0]:
            cols[key] = c
    evac = next((j for j, c in enumerate(labels) if "שפונו" in c), None)
    body = rows[lab + 1:]
    ycol = cbs.best_col(body, lambda v: bool(cbs.YEAR.match(v)))
    mcol = cbs.best_col(body, lambda v: bool(_MONTH.match(v)), exclude={ycol})
    if ycol is None or mcol is None:
        raise ValueError("t1: no year / month column in the monthly block")
    out, year = {}, None
    for r in body:
        if cbs.YEAR.match(cbs.cell(r, ycol)):
            year = int(cbs.cell(r, ycol))
        m = cbs.cell(r, mcol)
        tot = cbs.val(r, orig[2])
        if year is None or not _MONTH.match(m) or tot is None:
            continue
        rec = {"t": (year, int(m)), "isr": cbs.val(r, orig[0]), "tour": cbs.val(r, orig[1]),
               "tot": tot, "evac": cbs.val(r, evac) if evac is not None else None}
        for key in ("trend", "sa"):
            c = cols.get(key)
            rec[key] = cbs.val(r, c[2]) if c else None
            rec[key + "_isr"] = cbs.val(r, c[0]) if c else None
            rec[key + "_tour"] = cbs.val(r, c[1]) if c else None
        out[rec["t"]] = rec
    return [out[t] for t in sorted(out)]


# ── formatting ───────────────────────────────────────────────────────────


def _k(v):
    """Thousands, one decimal: 1,917.6."""
    return fmt.num_he(v, 1)


def _mil(v):
    """Thousands as millions, two decimals: 15,143.4 → 15.14."""
    return fmt.num_he(v / 1000, 2)


def _r(v, d=1):
    return None if v is None else round(v, d)


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _months(end):
    return "ינואר" if end == 1 else f"ינואר עד {fmt.MONTHS_HE[end - 1]}"


def _span(end, year):
    return f"{_months(end)} {year}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _word(c, up="עלייה", down="ירידה"):
    return up if c > 0 else down


def _tone(c, band=TONE_BAND):
    if c is None:
        return "brand"
    return "ok" if c > band else "danger" if c < -band else "warn"


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"].copy()
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    rows = cbs.grid(frames["t1"], "t1")
    monthly = _monthly(rows)
    years, _ = _yearly(rows, cbs.row_with(rows, "Trend", name="t1"))
    if not monthly:
        raise ValueError("t1: no monthly rows")
    if not years:
        raise ValueError("t1: no yearly rows")
    by_t = {m["t"]: m for m in monthly}
    last = monthly[-1]
    lt = last["t"]
    cur_year, end = lt
    prev_t = (cur_year - 1, end)
    prev = by_t.get(prev_t)
    month_chg = _chg(last["tot"], prev["tot"]) if prev else None

    # Year to date, every year of the monthly block, from the months
    # themselves (complete only: a year missing a month is left out).
    ytd = []
    for y in sorted({m["t"][0] for m in monthly}):
        ms = [by_t.get((y, k)) for k in range(1, end + 1)]
        if all(ms):
            ytd.append({"year": y, "isr": sum(m["isr"] or 0 for m in ms),
                        "tour": sum(m["tour"] or 0 for m in ms), "tot": sum(m["tot"] for m in ms)})
    ytd_by = {y["year"]: y for y in ytd}
    ytd_now, ytd_prev = ytd_by.get(cur_year), ytd_by.get(cur_year - 1)
    ytd_chg = _chg(ytd_now["tot"], ytd_prev["tot"]) if ytd_now and ytd_prev else None
    base = ytd_by.get(BASE_YEAR) if BASE_YEAR != cur_year else None
    tour_vs_base = (ytd_now["tour"] / base["tour"]) if ytd_now and base and base["tour"] else None
    tour_share = (ytd_now["tour"] / ytd_now["tot"]) if ytd_now and ytd_now["tot"] else None
    base_share = (base["tour"] / base["tot"]) if base and base["tot"] else None

    # Whole years: drop the current year if the yearly block lists it while
    # the months say it is still running.
    full = [y for y in years if not (y["year"] == cur_year and end < 12)] or years
    # Evacuees' nights (Oct 2023 to Jun 2025) are inside the Israelis'
    # figure; the yearly block doesn't split them out, the months do.
    evac_year = {}
    for m in monthly:
        if m["evac"]:
            evac_year[m["t"][0]] = evac_year.get(m["t"][0], 0.0) + m["evac"]
    for y in full:
        y["evac"] = evac_year.get(y["year"], 0.0)
    peak = max(full, key=lambda y: (y["tot"], y["year"]))
    peak_reg = max(full, key=lambda y: (y["tot"] - y["evac"], y["year"]))

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["month"] = {"value": _r(last["tot"]), "display": _k(last["tot"]),
                     "tone": _tone(month_chg)}
    labels["month_kpi"] = f"לינות במלונות ב{_mname(lt)} (אלפים)"
    if month_chg is not None:
        kpis["month_chg"] = {"value": round(month_chg, 4), "display": fmt.signed_pct(month_chg),
                             "tone": _tone(month_chg)}
        labels["month_chg_kpi"] = f"שינוי לעומת {_mname(prev_t)}"
    if ytd_now:
        kpis["ytd"] = {"value": _r(ytd_now["tot"]), "display": _mil(ytd_now["tot"]),
                       "tone": _tone(ytd_chg)}
        labels["ytd_kpi"] = f"לינות מתחילת השנה, {_span(end, cur_year)} (מיליונים)"
    if ytd_chg is not None:
        kpis["ytd_chg"] = {"value": round(ytd_chg, 4), "display": fmt.signed_pct(ytd_chg),
                           "tone": _tone(ytd_chg)}
        labels["ytd_chg_kpi"] = f"שינוי לעומת התקופה המקבילה ב-{cur_year - 1}"
    if tour_share is not None:
        kpis["tour_share"] = {"value": round(tour_share, 4), "display": fmt.pct(tour_share, 0),
                              "tone": "info"}
        labels["tour_share_kpi"] = "חלק התיירים מהלינות מתחילת השנה"
    if tour_vs_base is not None:
        kpis["tour_base"] = {"value": round(tour_vs_base, 4), "display": fmt.pct(tour_vs_base, 0),
                             "tone": "ok" if tour_vs_base >= 0.9 else "warn"
                             if tour_vs_base >= 0.5 else "danger"}
        labels["tour_base_kpi"] = (f"לינות תיירים מתחילת השנה לעומת התקופה המקבילה "
                                   f"ב-{BASE_YEAR}")

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables, flags = {}, {}, {}

    charts["years"] = {"x": [str(y["year"]) for y in full],
                       "isr": [_r(y["isr"] - y["evac"]) if y["isr"] is not None else None
                               for y in full],
                       "evac": [_r(y["evac"]) if y["evac"] else None for y in full],
                       "tour": [_r(y["tour"]) for y in full]}
    tables["years"] = [[str(y["year"]), _k(y["tot"]),
                        _k(y["isr"]) if y["isr"] is not None else "",
                        _k(y["evac"]) if y["evac"] else "",
                        _k(y["tour"]) if y["tour"] is not None else "",
                        fmt.pct(y["tour"] / y["tot"], 0) if y["tour"] is not None and y["tot"]
                        else ""] for y in full]
    flags["years_evac"] = any(y["evac"] for y in full)
    charts["share"] = {"x": charts["years"]["x"],
                       "y": [round(y["tour"] / y["tot"] * 100, 1)
                             if y["tour"] is not None and y["tot"] else None
                             for y in full]}

    charts["monthly"] = {"x": [f"{m['t'][0]}-{m['t'][1]:02d}" for m in monthly],
                         "isr": [_r(m["isr"]) for m in monthly],
                         "tour": [_r(m["tour"]) for m in monthly]}
    recent = monthly[-13:]
    tables["monthly"] = [[_mname(m["t"]), _k(m["tot"]),
                          _k(m["isr"]) if m["isr"] is not None else "",
                          _k(m["tour"]) if m["tour"] is not None else "",
                          fmt.signed_pct(c) if (c := _chg(m["tot"], (by_t.get(
                              (m["t"][0] - 1, m["t"][1])) or {}).get("tot"))) is not None else ""]
                         for m in reversed(recent)]

    hm_years = sorted({m["t"][0] for m in monthly})
    charts["heat"] = {"years": [str(y) for y in hm_years],
                      "months": list(fmt.MONTHS_SHORT_HE),
                      "cells": [[m["t"][1] - 1, hm_years.index(m["t"][0]), round(m["tot"])]
                                for m in monthly],
                      "max": round(max(m["tot"] for m in monthly))}
    tables["heat"] = [[str(y)] + [_k(by_t[(y, k)]["tot"]) if (y, k) in by_t else ""
                                  for k in range(1, 13)] for y in hm_years]

    charts["ytd"] = {"x": [str(y["year"]) for y in ytd], "isr": [_r(y["isr"]) for y in ytd],
                     "tour": [_r(y["tour"]) for y in ytd]}
    tables["ytd"] = [[str(y["year"]), _k(y["tot"]), _k(y["isr"]), _k(y["tour"]),
                      fmt.signed_pct(c) if (c := _chg(y["tot"], (ytd_by.get(y["year"] - 1) or {})
                                                      .get("tot"))) is not None else ""]
                     for y in ytd]

    sa_rows = [m for m in monthly if m["sa"] is not None or m["trend"] is not None]
    flags["sa"] = len(sa_rows) >= 12
    if flags["sa"]:
        charts["sa"] = {"x": [f"{m['t'][0]}-{m['t'][1]:02d}" for m in sa_rows],
                        "orig": [_r(m["tot"]) for m in sa_rows],
                        "sa": [_r(m["sa"]) for m in sa_rows],
                        "trend": [_r(m["trend"]) for m in sa_rows]}
        tables["sa"] = [[_mname(m["t"]), _k(m["tot"]),
                         _k(m["sa"]) if m["sa"] is not None else "",
                         _k(m["trend"]) if m["trend"] is not None else ""]
                        for m in reversed(sa_rows[-12:])]

    evac = [m for m in monthly if m["evac"]]
    flags["evac"] = len(evac) >= 3
    if flags["evac"]:
        charts["evac"] = {"x": [_mshort(m["t"]) for m in evac],
                          "evac": [_r(m["evac"]) for m in evac],
                          "rest": [_r(m["isr"] - m["evac"]) if m["isr"] is not None else None
                                   for m in evac]}
        tables["evac"] = [[_mname(m["t"]), _k(m["evac"]),
                           _k(m["isr"]) if m["isr"] is not None else "",
                           fmt.pct(m["evac"] / m["isr"], 0) if m["isr"] else ""] for m in evac]
    flags["share"] = sum(v is not None for v in charts["share"]["y"]) >= 3
    tables["share"] = [[x, fmt.pct_of(v, 0)] for x, v in zip(charts["share"]["x"],
                                                             charts["share"]["y"]) if v is not None]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if month_chg is not None:
        add("month", f"ב{_mname(lt)} נרשמו במלונות התיירות {_k(last['tot'])} אלף לינות, "
                     f"{_word(month_chg)} של {fmt.pct(abs(month_chg))} לעומת {_mname(prev_t)} "
                     f"({_k(prev['tot'])} אלף).")
    if ytd_chg is not None:
        parts = []
        for key, name in (("isr", "ישראלים"), ("tour", "תיירים")):
            c = _chg(ytd_now[key], ytd_prev[key])
            if c is not None:
                parts.append(f"{name} {fmt.signed_pct(c)}")
        add("ytd", f"מתחילת השנה ({_span(end, cur_year)}) נרשמו {_mil(ytd_now['tot'])} מיליון "
                   f"לינות, {_word(ytd_chg)} של {fmt.pct(abs(ytd_chg))} לעומת התקופה המקבילה "
                   f"ב-{cur_year - 1}" + (f" ({', '.join(parts)})." if parts else "."))
    if tour_vs_base is not None:
        add("tourists", f"לינות התיירים מחו\"ל מתחילת השנה ({_k(ytd_now['tour'])} אלף) הן "
                        f"{fmt.pct(tour_vs_base, 0)} ממספרן בתקופה המקבילה ב-{BASE_YEAR} "
                        f"({_k(base['tour'])} אלף).")
    if tour_share is not None and base_share is not None and abs(tour_share - base_share) >= SHARE_GAP:
        add("share", f"תיירים מחו\"ל אחראים ל-{fmt.pct(tour_share, 0)} מהלינות מתחילת השנה, "
                     f"לעומת {fmt.pct(base_share, 0)} בתקופה המקבילה ב-{BASE_YEAR}.")
    tr = [m for m in monthly if m["trend"] is not None]
    if len(tr) > TREND_RUN_MIN:
        run, sign = 0, None
        for a, b in zip(reversed(tr[:-1]), reversed(tr)):
            d = b["trend"] - a["trend"]
            s = (d > 0) - (d < 0)
            if s == 0 or (sign is not None and s != sign):
                break
            sign, run = s, run + 1
        if run >= TREND_RUN_MIN:
            add("trend", f"מגמת הלינות של הלמ\"ס {'עולה' if sign > 0 else 'יורדת'} זה {run} "
                         f"חודשים ברציפות, עד {_k(tr[-1]['trend'])} אלף לינות בחודש "
                         f"ב{_mname(tr[-1]['t'])}.")
    last_full = full[-1]
    if peak_reg["year"] != last_full["year"] and last_full["tot"]:
        reg = peak_reg["tot"] - peak_reg["evac"]
        lead = (f"שנת השיא בנתונים היא {peak['year']}, עם {_mil(peak['tot'])} מיליון לינות, "
                f"מהן {_mil(peak['evac'])} מיליון לינות מפונים. בלי המפונים, השיא הוא "
                f"{peak_reg['year']}, עם {_mil(reg)} מיליון."
                if peak["year"] != peak_reg["year"] else
                f"שנת השיא בנתונים היא {peak['year']}, עם {_mil(reg)} מיליון לינות.")
        # Compare like with like: the peak above is without evacuees.
        if last_full["evac"]:
            tail = (f"ב-{last_full['year']} נרשמו {_mil(last_full['tot'])} מיליון, ובלי "
                    f"{_mil(last_full['evac'])} מיליון לינות המפונים "
                    f"{fmt.pct((last_full['tot'] - last_full['evac']) / reg, 0)} מרמת השיא.")
        else:
            tail = (f"ב-{last_full['year']} נרשמו {_mil(last_full['tot'])} מיליון, "
                    f"{fmt.pct(last_full['tot'] / reg, 0)} מרמת השיא.")
        add("peak", f"{lead} {tail}")
    if flags["evac"]:
        tot_evac = sum(m["evac"] for m in evac)
        top = max(evac, key=lambda m: (m["evac"], m["t"]))
        top_share = top["evac"] / top["isr"] if top["isr"] else None
        add("evac", f"מ{_mname(evac[0]['t'])} עד {_mname(evac[-1]['t'])} נרשמו במלונות "
                    f"{_mil(tot_evac)} מיליון לינות של מפונים. בשיא, ב{_mname(top['t'])}, "
                    f"היו אלה {_k(top['evac'])} אלף לינות"
                    + (f", {fmt.pct(top_share, 0)} מלינות הישראלים." if top_share else "."))
    # The busiest month of the latest whole calendar year in the months.
    whole = [y for y in hm_years if all((y, k) in by_t for k in range(1, 13))]
    if whole:
        y = whole[-1]
        top_m = max(range(1, 13), key=lambda k: (by_t[(y, k)]["tot"], -k))
        low_m = min(range(1, 13), key=lambda k: (by_t[(y, k)]["tot"], k))
        add("season", f"ב-{y} החודש העמוס ביותר במלונות היה {fmt.MONTHS_HE[top_m - 1]} "
                      f"({_k(by_t[(y, top_m)]['tot'])} אלף לינות), והשקט ביותר "
                      f"{fmt.MONTHS_HE[low_m - 1]} ({_k(by_t[(y, low_m)]['tot'])} אלף).")

    # ── text ─────────────────────────────────────────────────────────────
    rel_date = pd.Timestamp(latest_rel["RELEASE_DATE"])
    release = {"no": latest_rel["RELEASE_NO"], "date": fmt.d_he(rel_date),
               "title": latest_rel["TITLE"], "headline": latest_rel["HEADLINE"],
               "url": latest_rel["PAGE_URL"], "pdf": latest_rel["REPORT_PDF_URL"]}
    yfirst, ylast = full[0]["year"], full[-1]["year"]
    m0 = monthly[0]["t"]
    labels.update({
        "lede": (f"כמה לילות לנים ישראלים ותיירים מחו\"ל במלונות התיירות בישראל, בכל חודש "
                 f"ובכל שנה. הנתונים מתוך ההודעה החודשית של הלשכה המרכזית לסטטיסטיקה "
                 f"(הלמ\"ס), ומתעדכנים עם כל הודעה חדשה. הנתון האחרון הוא ל{_mname(lt)}: "
                 f"{_k(last['tot'])} אלף לינות."),
        "years_note": (f"לינות במלונות בכל שנה מאז {yfirst}, של ישראלים ושל תיירים"
                       + (", ולינות המפונים בנפרד (הלמ\"ס כוללת אותן בלינות הישראלים)."
                          if flags["years_evac"] else ".")),
        "years_aria": f"לינות במלונות לפי שנה, {yfirst} עד {ylast}",
        "years_caption": "לינות במלונות תיירות לפי שנה (אלפים)",
        "share_note": (f"החלק של תיירים מחו\"ל מכלל הלינות במלונות בכל שנה, {yfirst} עד "
                       f"{ylast}. השאר הן לינות של ישראלים."),
        "share_aria": f"חלק התיירים מהלינות במלונות לפי שנה, {yfirst} עד {ylast}",
        "monthly_note": (f"לינות ישראלים ותיירים בכל חודש מאז {_mname(m0)}. אפשר לגרור כדי "
                         f"להתמקד בתקופה. בטבלה: {len(recent)} החודשים האחרונים."),
        "monthly_aria": f"לינות במלונות לפי חודש, {_mname(m0)} עד {_mname(lt)}",
        "monthly_caption": "לינות במלונות לפי חודש (אלפים)",
        "heat_note": ("סך הלינות בכל חודש, שנה מול שנה: כמה עמוסים המלונות בכל עונה, ואיך "
                      "השפיעו הקורונה והמלחמה. צבע כהה יותר הוא יותר לינות."),
        "heat_aria": f"לינות במלונות לפי שנה וחודש, {hm_years[0]} עד {hm_years[-1]}",
        "heat_caption": "סך הלינות לפי שנה וחודש (אלפים)",
        "ytd_note": (f"לינות מתחילת כל שנה עד {fmt.MONTHS_HE[end - 1]}, באותם חודשים בכל שנה, "
                     f"כדי להשוות את {cur_year} לשנים הקודמות."
                     if end > 1 else
                     f"לינות בחודש ינואר בכל שנה, כדי להשוות את {cur_year} לשנים הקודמות."),
        "ytd_aria": (f"לינות במלונות, {_months(end)}, בכל שנה מ-"
                     f"{ytd[0]['year'] if ytd else cur_year} עד {cur_year}"),
        "ytd_caption": f"לינות {_months(end)} לפי שנה (אלפים)",
        "span": f"{yfirst}-{cur_year}",
    })
    if flags["sa"]:
        labels.update({
            "sa_note": (f"סך הלינות בכל חודש מאז {_mname(sa_rows[0]['t'])}: הנתון המקורי, "
                        f"הנתון המנוכה עונתיות וקו המגמה של הלמ\"ס. בטבלה: 12 החודשים "
                        f"האחרונים."),
            "sa_aria": f"לינות במלונות: מקורי, מנוכה עונתיות ומגמה, {_mname(sa_rows[0]['t'])} "
                       f"עד {_mname(sa_rows[-1]['t'])}",
            "sa_caption": "סך הלינות: מקורי, מנוכה עונתיות ומגמה (אלפים)",
        })
    if flags["evac"]:
        labels.update({
            "evac_note": (f"מאז מלחמת חרבות ברזל שוכנו במלונות תושבים שפונו מבתיהם. הלמ\"ס "
                          f"כוללת את לינותיהם בלינות הישראלים מ{_mname(evac[0]['t'])} עד "
                          f"{_mname(evac[-1]['t'])}, ומפרטת אותן בנפרד."),
            "evac_aria": f"לינות מפונים ושאר הישראלים, {_mname(evac[0]['t'])} עד "
                         f"{_mname(evac[-1]['t'])}",
            "evac_caption": "לינות מפונים במלונות לפי חודש (אלפים)",
        })

    summary = (f"לינות ישראלים ותיירים במלונות התיירות לפי חודש ושנה, מנתוני הלמ\"ס. "
               f"ב{_mname(lt)} נרשמו {_k(last['tot'])} אלף לינות"
               + (f" ({fmt.signed_pct(month_chg)} בשנה)" if month_chg is not None else "")
               + ".")
    desc = (f"כמה לינות נרשמות במלונות בישראל: {_k(last['tot'])} אלף ב{_mname(lt)}"
            + (f", {_mil(ytd_now['tot'])} מיליון מתחילת השנה" if ytd_now else "")
            + ". ישראלים ותיירים, לפי חודש ושנה.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{yfirst}/{cur_year}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "לינות במלונות בישראל: נתונים חודשיים | הלמ\"ס",
                "description": desc,
                "name": "לינות במלונות תיירות בישראל",
                "alternate_names": ["לינות במלונות תיירות", "תפוסת מלונות בישראל",
                                    "לינות תיירים במלונות", "לינות ישראלים במלונות"],
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
