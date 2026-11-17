"""תיקופי נסיעות בתחבורה ציבורית: CBS's yearly release on Rav-Kav validations.

The 2026 edition is a set of chart-data sheets ("תרשים N - ..."); the first
edition (2025) was a set of print tables ("לוח N - ...") with a different
layout. Sheet numbers move between editions, so every table input (t1..t12,
three spare slots, all optional) is read with `cbs.grid` and each chart is
found by its TITLE text, never by its stem:

  year     אוטובוסים בקווים קבועים, YYYY-YYYY   bus validations per year
  month    אוטובוסים ... לפי חודש                month × year
  hour     אוטובוסים לפי שעות ביום               hour × year
  dow      אוטובוסים ... לפי ימי השבוע           % per weekday, per year
  profile  אוטובוסים ... לפי פרופיל נוסע         profile × year
  city     אוטובוסים ... בערים הגדולות           % per large city
  lrt_hour רכבת הקלה בירושלים לפי שעות ביום      hour × year (Jerusalem LRT)
  carmel   כרמלית                                per year
  modes    בתחבורה הציבורית לפי פרופיל נוסע      mode × profile, latest year

Only chart-format titles ("תרשים") are recognised. The bus-per-year chart is
required (no page without it). A recognised chart whose header labels are
gone while its data rows remain raises; a chart missing from the edition
(or one cut down to its title) drops its section.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TITLE = re.compile(r"^תרשים\s*\d+[א-ת]?\s*-\s*")
YEAR_IN = re.compile(r"(?:19|20)\d\d")
HOUR = re.compile(r"^(\d{1,2}):\d\d\s*-\s*\d{1,2}:\d\d$")
HEB = re.compile("[א-ת]")
DAYS = ("ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת")
OTHER_PROFILE = ("אחר ולא ידוע",)
OTHER_CITY = "יתר היישובים"
TOTAL = 'סה"כ'
MILLION = 1_000_000
# Insight-card order; at most MAX_TOP there, the others show in their section.
PRIORITY = ("year", "hour_peak", "city", "profile", "modes_total", "month_drop", "dow", "lrt_year",
            "modes_profile", "carmel", "shape", "month_range", "hour_night")
MAX_TOP = 8


# ── locating tables ──────────────────────────────────────────────────────


def _title(rows):
    for r in rows:
        for c in r:
            if TITLE.match(c):
                return c
    return ""


def _kind(t):
    if not t:
        return None
    if "כרמלית" in t and "שעות" not in t and "ימי" not in t:
        return "carmel"
    if "רכבת הקלה בירושלים" in t and "שעות" in t:
        return "lrt_hour"
    if "פרופיל" in t and "תחבורה הציבורית" in t and "אוטובוס" not in t:
        return "modes"
    if "אוטובוס" not in t:
        return None
    if "חודש" in t:
        return "month"
    if "שעות" in t:
        return "hour"
    if "ימי השבוע" in t:
        return "dow"
    if "פרופיל" in t:
        return "profile"
    if "ערים" in t:
        return "city"
    return "year"


def _tables(frames):
    """{kind: (title, rows)} over every non-empty table input; the lowest
    stem wins a duplicate kind."""
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
            out[k] = (t, rows)
    return out


# ── helpers ──────────────────────────────────────────────────────────────


def _scale(title):
    if "אלפים" in title:
        return 1_000
    return MILLION  # "מיליונים", and the unit-less hour chart of the LRT


def _numeric_rows(rows, start=0):
    return [r for r in rows[start:] if sum(1 for c in r if cbs.num(c) is not None) >= 2]


def _header(rows, pred, name):
    """First row where `pred(row)`; None when the table has no data rows
    either (cut down to its title), raise when data rows are there."""
    for i, r in enumerate(rows):
        if pred(r):
            return i
    if _numeric_rows(rows):
        raise ValueError(f"{name}: header row not found")
    return None


def _year_cols(row):
    return [(j, int(c)) for j, c in enumerate(row) if cbs.YEAR.match(c)]


def _years_row(rows, need, name):
    return _header(rows, lambda r: len(_year_cols(r)) >= need, name)


def _m(v, d=1):
    """Absolute count → millions, rounded, for charts."""
    return None if v is None else round(v / MILLION, d)


def _mil(v, d=1):
    return fmt.num_he(v / MILLION, d)


def _chg(new, old):
    return (new - old) / old if old else None


def _thousands(v):
    """Carmelit counts: thousands below a million, millions above."""
    return f"{fmt.num_he(v / MILLION, 2)} מיליון" if v >= MILLION else f"{fmt.int_he(v / 1000)} אלף"


def _hour_label(h):
    return f"{h:02d}:00"


# ── parsers ──────────────────────────────────────────────────────────────


def _two_col_years(title, rows, name):
    """שנה | value rows → {year: count}."""
    s = _scale(title)
    out = {}
    for r in rows:
        y = cbs.cell(r, 0)
        if cbs.YEAR.match(y) and cbs.val(r, 1) is not None:
            out[int(y)] = cbs.val(r, 1) * s
    if not out and _numeric_rows(rows):
        raise ValueError(f"{name}: no year rows")
    return out


def _month(title, rows):
    h = _years_row(rows, 2, "month")
    if h is None:
        return [], {}
    s = _scale(title)
    ycols = _year_cols(rows[h])
    out = {}
    for r in rows[h + 1:]:
        m = cbs.ROMAN.get(cbs.cell(r, 0))
        if not m:
            continue
        for j, y in ycols:
            v = cbs.val(r, j)
            if v is not None:
                out[(y, m)] = v * s
    return [y for _, y in ycols], out


def _hours(title, rows, name):
    h = _years_row(rows, 1, name)
    if h is None:
        return [], {}
    s = _scale(title)
    ycols = _year_cols(rows[h])
    out = {}
    for r in rows[h + 1:]:
        mm = HOUR.match(cbs.cell(r, 0))
        if not mm:
            continue
        hr = int(mm.group(1))
        for j, y in ycols:
            v = cbs.val(r, j)
            if v is not None:
                out[(y, hr)] = v * s
    return [y for _, y in ycols], out


def _dow(rows):
    """Blocks of weekday columns, each under a 'שנת YYYY' heading."""
    h = _header(rows, lambda r: sum(1 for c in r if c in DAYS) >= 5, "dow")
    if h is None:
        return {}
    heads = []
    for r in rows[:h]:
        for j, c in enumerate(r):
            ys = YEAR_IN.findall(c)
            if ys and "שנת" in c:
                heads.append((j, int(ys[-1])))
    if not heads:
        raise ValueError("dow: year headings not found")
    heads.sort()
    data = next((r for r in rows[h + 1:] if sum(1 for c in r if cbs.num(c) is not None) >= 5), None)
    if data is None:
        return {}
    out = {}
    for k, (j0, y) in enumerate(heads):
        j1 = heads[k + 1][0] if k + 1 < len(heads) else len(rows[h])
        vals = {}
        for j in range(j0, j1):
            d = cbs.cell(rows[h], j)
            v = cbs.val(data, j)
            if d in DAYS and v is not None:
                vals[d] = v
        if len(vals) == len(DAYS):
            out[y] = vals
    return out


def _profile(title, rows):
    h = _header(rows, lambda r: cbs.cell(r, 0) == "שנה" and sum(1 for c in r if HEB.search(c)) >= 4,
                "profile")
    if h is None:
        return [], {}
    s = _scale(title)
    cats = [(j, c) for j, c in enumerate(rows[h]) if j > 0 and c and HEB.search(c)]
    out = {}
    for r in rows[h + 1:]:
        y = cbs.cell(r, 0)
        if not cbs.YEAR.match(y):
            continue
        vals = {c: (cbs.val(r, j) or 0.0) * s for j, c in cats}
        if any(vals.values()):
            out[int(y)] = vals
    return [c for _, c in cats], out


def _city(title, rows):
    h = _header(rows, lambda r: sum(1 for c in r if c and HEB.search(c) and not TITLE.match(c)) >= 5
                and not any(cbs.num(c) is not None for c in r), "city")
    if h is None:
        return {}, None
    data = next((r for r in rows[h + 1:] if sum(1 for c in r if cbs.num(c) is not None) >= 5), None)
    if data is None:
        return {}, None
    out = {}
    for j, c in enumerate(rows[h]):
        v = cbs.val(data, j)
        if c and v is not None:
            out[c] = v
    ys = YEAR_IN.findall(title)
    return out, (int(ys[-1]) if ys else None)


def _modes(title, rows):
    h = _header(rows, lambda r: TOTAL in r and sum(1 for c in r if HEB.search(c)) >= 4, "modes")
    if h is None:
        return [], {}, None
    tot = cbs.col_after(rows[h], TOTAL)
    cats = [(j, c) for j, c in enumerate(rows[h]) if c and HEB.search(c) and j != tot]
    out = {}
    for r in rows[h + 1:]:
        label = cbs.cell(r, 0)
        if not label or not HEB.search(label):
            break  # the percent block's heading ends the absolute block
        total = cbs.val(r, tot)
        if total:
            out[label] = {"total": total, "cats": {c: cbs.val(r, j) or 0.0 for j, c in cats}}
    ys = YEAR_IN.findall(title)
    return [c for _, c in cats], out, (int(ys[-1]) if ys else None)


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = cbs.latest_release(frames["releases"])
    tabs = _tables(frames)
    if "year" not in tabs:
        raise ValueError("bus validations per year chart not found in the newest edition")

    kpis, labels, charts, tables, flags, insights = {}, {}, {}, {}, {}, []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # ── per year (bus) ───────────────────────────────────────────────────
    years_map = _two_col_years(*tabs["year"], "year")
    m_years, monthly = _month(*tabs["month"]) if "month" in tabs else ([], {})
    derived = []
    for y in m_years:
        if y not in years_map and all((y, m) in monthly for m in range(1, 13)):
            years_map[y] = sum(monthly[(y, m)] for m in range(1, 13))
            derived.append(y)
    yrs = sorted(years_map)
    if not yrs:
        raise ValueError("year: no bus validations")
    ly, fy = yrs[-1], yrs[0]
    last = years_map[ly]
    charts["year"] = {"x": [str(y) for y in yrs], "y": [_m(years_map[y]) for y in yrs]}
    tables["year"] = [[str(y), _mil(years_map[y])] for y in yrs]
    kpis["bus"] = {"value": round(last / MILLION, 1), "display": _mil(last), "tone": "brand"}
    labels["bus_kpi"] = f"תיקופים באוטובוסים בקווים קבועים ב-{ly} (מיליונים)"
    labels["year_note"] = (f"מספר התיקופים באוטובוסים בקווים קבועים בכל שנה, {fy} עד {ly}, במיליונים"
                           + (f". נתוני {fmt.join_he(derived)} הם סכום הנתונים החודשיים." if derived else "."))
    labels["year_aria"] = f"תיקופי נסיעות באוטובוסים לפי שנה, {fy} עד {ly}"
    if len(yrs) >= 2:
        py = yrs[-2]
        c = _chg(last, years_map[py])
        kpis["yoy"] = {"value": round(c * 100, 1), "display": fmt.signed_pct(c),
                       "tone": "ok" if c >= 0.01 else ("danger" if c <= -0.05 else "warn" if c < 0 else "brand")}
        labels["yoy_kpi"] = f"שינוי במספר התיקופים באוטובוסים, {ly} לעומת {py}"
        base = next((y for y in yrs if y not in derived), fy) if len(yrs) >= 3 else fy
        txt = f"ב-{ly} נרשמו {_mil(last)} מיליון תיקופים באוטובוסים בקווים קבועים, "
        if abs(c) < 0.005:
            txt += f"כמעט ללא שינוי לעומת {py}"
        else:
            txt += f"{'עלייה' if c > 0 else 'ירידה'} של {fmt.pct(abs(c))} לעומת {py}"
        if base != py and years_map[base]:
            cb = _chg(last, years_map[base])
            txt += (f", ו{'עלייה' if cb > 0 else 'ירידה'} של {fmt.pct(abs(cb))} לעומת {base} "
                    f"({_mil(years_map[base])} מיליון)")
        add("year", txt + ".")
        if base != py and years_map[base]:
            cb = _chg(last, years_map[base])
            kpis["growth"] = {"value": round(cb * 100, 1), "display": fmt.signed_pct(cb),
                              "tone": "ok" if cb >= 0.05 else ("danger" if cb <= -0.05 else "brand")}
            labels["growth_kpi"] = f"שינוי במספר התיקופים באוטובוסים, {ly} לעומת {base}"

    # ── month × year ─────────────────────────────────────────────────────
    flags["month"] = len({y for y, _ in monthly}) >= 2
    if flags["month"]:
        my = sorted({y for y, _ in monthly})
        months = sorted({m for _, m in monthly})
        cells = [[mi, yi, _m(monthly[(y, m)])] for yi, y in enumerate(my) for mi, m in enumerate(months)
                 if (y, m) in monthly]
        charts["month"] = {"x": [fmt.MONTHS_SHORT_HE[m - 1] for m in months], "y": [str(y) for y in my],
                           "cells": cells,
                           "min": min(c[2] for c in cells), "max": max(c[2] for c in cells)}
        tables["month"] = [[fmt.MONTHS_HE[m - 1]] + [_mil(monthly[(y, m)]) if (y, m) in monthly else "–"
                                                     for y in my] for m in months]
        labels["month_cols"] = ["חודש"] + [str(y) for y in my]
        labels["month_note"] = (f"תיקופים באוטובוסים בקווים קבועים בכל חודש, {my[0]} עד {my[-1]}, במיליונים. "
                                f"צבע כהה יותר הוא חודש עמוס יותר.")
        labels["month_aria"] = f"תיקופי נסיעות באוטובוסים לפי חודש ושנה, {my[0]} עד {my[-1]}"
        lo_key = min(monthly, key=lambda k: (monthly[k], k))
        hi_key = max(monthly, key=lambda k: (monthly[k], k))
        add("month_range", f"החודש העמוס ביותר בטבלה הוא {fmt.MONTHS_HE[hi_key[1] - 1]} {hi_key[0]}, עם "
                           f"{_mil(monthly[hi_key])} מיליון תיקופים, והשקט ביותר {fmt.MONTHS_HE[lo_key[1] - 1]} "
                           f"{lo_key[0]}, עם {_mil(monthly[lo_key])} מיליון.")
        # The latest year's sharpest drop against the same month a year before.
        if len(my) >= 2:
            a, b = my[-1], my[-2]
            drops = [(monthly[(a, m)] / monthly[(b, m)] - 1, m) for m in months
                     if (a, m) in monthly and (b, m) in monthly and monthly[(b, m)]]
            if drops:
                d, m = min(drops)
                if d <= -0.15:
                    add("month_drop", f"ב{fmt.MONTHS_HE[m - 1]} {a} נרשמו {_mil(monthly[(a, m)])} מיליון "
                                      f"תיקופים באוטובוסים, {fmt.pct(-d, 0)} פחות מאשר ב{fmt.MONTHS_HE[m - 1]} "
                                      f"{b} ({_mil(monthly[(b, m)])} מיליון): הירידה החדה ביותר ב-{a} "
                                      f"לעומת אותו חודש בשנה הקודמת.")

    # ── hour of day ──────────────────────────────────────────────────────
    h_years, hours = _hours(*tabs["hour"], "hour") if "hour" in tabs else ([], {})
    l_years, lrt = _hours(*tabs["lrt_hour"], "lrt_hour") if "lrt_hour" in tabs else ([], {})
    hr_list = sorted({h for _, h in hours})
    flags["hour"] = len(hr_list) >= 6 and bool(h_years)
    full_day = list(range(24))
    if flags["hour"]:
        hy = [y for y in h_years if any((y, h) in hours for h in hr_list)]
        charts["hour"] = {"x": [_hour_label(h) for h in hr_list], "years": [str(y) for y in hy],
                          "series": [[_m(hours.get((y, h)), 2) for h in hr_list] for y in hy]}
        tables["hour"] = [[_hour_label(h)] + [_mil(hours[(y, h)], 2) if (y, h) in hours else "–" for y in hy]
                          for h in hr_list]
        labels["hour_cols"] = ["שעה"] + [str(y) for y in hy]
        labels["hour_note"] = (f"תיקופים באוטובוסים בכל שעה ביממה, מצטבר על פני השנה, {hy[0]} עד {hy[-1]}, "
                               f"במיליונים.")
        labels["hour_aria"] = f"תיקופי נסיעות באוטובוסים לפי שעה ביממה, {hy[0]} עד {hy[-1]}"
        hl = hy[-1]
        day = {h: hours[(hl, h)] for h in full_day if (hl, h) in hours}
        if len(day) == 24:
            tot = sum(day.values())
            peak = max(day, key=lambda h: (day[h], -h))
            kpis["peak"] = {"value": peak, "display": _hour_label(peak), "tone": "info"}
            labels["peak_kpi"] = f"שעת השיא באוטובוסים ב-{hl} ({fmt.pct(day[peak] / tot)} מהתיקופים)"
            morn = max(range(5, 11), key=lambda h: (day[h], -h))
            aft = max(range(11, 18), key=lambda h: (day[h], -h))
            if day[aft] > day[morn]:
                txt = (f"שעת השיא באוטובוסים אינה בבוקר: ב-{hl} נרשמו בשעה {_hour_label(aft)} "
                       f"{_mil(day[aft])} מיליון תיקופים, יותר מבשעת השיא של הבוקר, {_hour_label(morn)} "
                       f"({_mil(day[morn])} מיליון).")
            else:
                txt = (f"שעת השיא באוטובוסים ב-{hl} היא {_hour_label(morn)}, עם {_mil(day[morn])} מיליון "
                       f"תיקופים, ואחריה {_hour_label(aft)} עם {_mil(day[aft])} מיליון.")
            add("hour_peak", txt)
            night = sum(day[h] for h in range(5))
            add("hour_night", f"בין {_hour_label(0)} ל-{_hour_label(5)} נרשמו ב-{hl} רק {fmt.pct(night / tot)} "
                              f"מהתיקופים באוטובוסים, ובשעות {_hour_label(7)} עד {_hour_label(18)} "
                              f"{fmt.pct(sum(day[h] for h in range(7, 18)) / tot)}.")

    # ── hour shape: bus vs Jerusalem LRT, latest common year ─────────────
    common = [y for y in h_years if y in l_years
              and all((y, h) in hours and (y, h) in lrt for h in full_day)]
    flags["shape"] = bool(common)
    if flags["shape"]:
        yc = common[-1]
        bt = sum(hours[(yc, h)] for h in full_day)
        lt = sum(lrt[(yc, h)] for h in full_day)
        bs = [round(hours[(yc, h)] / bt * 100, 2) for h in full_day]
        ls = [round(lrt[(yc, h)] / lt * 100, 2) for h in full_day]
        charts["shape"] = {"x": [_hour_label(h) for h in full_day], "bus": bs, "lrt": ls}
        tables["shape"] = [[_hour_label(h), fmt.pct_of(bs[h]), fmt.pct_of(ls[h])] for h in full_day]
        labels["shape_note"] = (f"איזה חלק מתיקופי היממה נרשם בכל שעה ב-{yc}: אוטובוסים לעומת הרכבת הקלה "
                                f"בירושלים. כך אפשר להשוות את צורת היום בין שני אמצעים בגודל שונה מאוד.")
        labels["shape_aria"] = f"התפלגות התיקופים לפי שעה, אוטובוסים ורכבת קלה בירושלים, {yc}"
        bp = max(full_day, key=lambda h: (bs[h], -h))
        lp = max(full_day, key=lambda h: (ls[h], -h))
        if bp != lp:
            add("shape", f"ברכבת הקלה בירושלים שעת השיא ב-{yc} היא {_hour_label(lp)} ({fmt.pct_of(ls[lp])} "
                         f"מתיקופי היממה), ובאוטובוסים {_hour_label(bp)} ({fmt.pct_of(bs[bp])}).")

    # ── Jerusalem LRT per year (sum of its hours) ────────────────────────
    lrt_years = [y for y in l_years if all((y, h) in lrt for h in full_day)]
    flags["lrt_year"] = len(lrt_years) >= 2
    if flags["lrt_year"]:
        ltot = {y: sum(lrt[(y, h)] for h in full_day) for y in lrt_years}
        a, b = lrt_years[-1], lrt_years[-2]
        c = _chg(ltot[a], ltot[b])
        peak_y = max(ltot, key=lambda y: (ltot[y], y))
        charts["lrt_year"] = {"x": [str(y) for y in lrt_years], "y": [_m(ltot[y], 2) for y in lrt_years]}
        tables["lrt_year"] = [[str(y), _mil(ltot[y], 2)] for y in lrt_years]
        labels["lrt_year_note"] = (f"סך התיקופים ברכבת הקלה בירושלים בכל שנה, {lrt_years[0]} עד {a}, במיליונים "
                                   f"(סכום התיקופים בכל שעות היממה).")
        labels["lrt_year_aria"] = f"תיקופי נסיעות ברכבת הקלה בירושלים לפי שנה, {lrt_years[0]} עד {a}"
        if c is not None and abs(c) >= 0.03:
            txt = (f"ברכבת הקלה בירושלים נרשמו ב-{a} {_mil(ltot[a])} מיליון תיקופים, "
                   f"{'עלייה' if c > 0 else 'ירידה'} של {fmt.pct(abs(c))} לעומת {b}")
            if peak_y not in (a, b):
                txt += f" ופחות מבשנת השיא {peak_y} ({_mil(ltot[peak_y])} מיליון)"
            add("lrt_year", txt + ".")

    # ── day of week ──────────────────────────────────────────────────────
    dow = _dow(tabs["dow"][1]) if "dow" in tabs else {}
    flags["dow"] = bool(dow)
    if flags["dow"]:
        dy = sorted(dow)
        charts["dow"] = {"x": list(DAYS), "years": [str(y) for y in dy],
                         "series": [[round(dow[y][d], 1) for d in DAYS] for y in dy]}
        tables["dow"] = [[d] + [fmt.pct_of(dow[y][d]) for y in dy] for d in DAYS]
        labels["dow_cols"] = ["יום"] + [str(y) for y in dy]
        labels["dow_note"] = (f"איזה חלק מתיקופי השבוע באוטובוסים בקווים קבועים נרשם בכל יום, "
                              f"{fmt.join_he([str(y) for y in dy])}.")
        labels["dow_aria"] = "התפלגות התיקופים באוטובוסים לפי יום בשבוע"
        yl = dy[-1]
        wk = [dow[yl][d] for d in DAYS[:5]]
        avg = sum(wk) / len(wk)
        sat, fri = dow[yl]["שבת"], dow[yl]["שישי"]
        if sat and avg:
            add("dow", f"בימים ראשון עד חמישי נרשמים כ-{fmt.pct_of(avg)} מתיקופי השבוע באוטובוסים בכל יום "
                       f"(נתוני {yl}), ביום שישי {fmt.pct_of(fri)} ובשבת {fmt.pct_of(sat)}: "
                       f"יום חול ממוצע עמוס פי {fmt.num_he(avg / sat)} משבת.")

    # ── passenger profile ────────────────────────────────────────────────
    p_cats, prof = _profile(*tabs["profile"]) if "profile" in tabs else ([], {})
    flags["profile"] = len(prof) >= 2 and len(p_cats) >= 3
    if flags["profile"]:
        py_ = sorted(prof)
        pl, pf = py_[-1], py_[0]
        order = sorted([c for c in p_cats if c not in OTHER_PROFILE], key=lambda c: (-prof[pl][c], c))
        order += [c for c in p_cats if c in OTHER_PROFILE]
        charts["profile"] = {"x": [str(y) for y in py_], "cats": order,
                             "series": [[_m(prof[y][c], 2) for y in py_] for c in order]}
        tables["profile"] = [[str(y)] + [_mil(prof[y][c]) for c in order] for y in py_]
        labels["profile_cols"] = ["שנה"] + order
        labels["profile_note"] = (f"תיקופים באוטובוסים בקווים קבועים לפי פרופיל הנוסע שעל הכרטיס, {pf} עד {pl}, "
                                  f"במיליונים.")
        labels["profile_aria"] = f"תיקופי נסיעות באוטובוסים לפי פרופיל נוסע, {pf} עד {pl}"
        tl, tf = sum(prof[pl].values()), sum(prof[pf].values())
        named = [c for c in p_cats if c not in OTHER_PROFILE]
        if tl and tf and len(named) >= 2:
            sh = {c: (prof[pf][c] / tf, prof[pl][c] / tl) for c in named}
            up = max(named, key=lambda c: (sh[c][1] - sh[c][0], c))
            dn = min(named, key=lambda c: (sh[c][1] - sh[c][0], c))
            if sh[up][1] - sh[up][0] >= 0.05 and sh[dn][0] - sh[dn][1] >= 0.05:
                add("profile", f"חלקם של תיקופי פרופיל \"{up}\" באוטובוסים עלה מ-{fmt.pct(sh[up][0])} ב-{pf} "
                               f"ל-{fmt.pct(sh[up][1])} ב-{pl}, ואילו חלקם של תיקופי \"{dn}\" ירד "
                               f"מ-{fmt.pct(sh[dn][0])} ל-{fmt.pct(sh[dn][1])}.")

    # ── large cities ─────────────────────────────────────────────────────
    city, cy = _city(*tabs["city"]) if "city" in tabs else ({}, None)
    named_c = sorted([(c, v) for c, v in city.items() if c != OTHER_CITY], key=lambda kv: (-kv[1], kv[0]))
    flags["city"] = len(named_c) >= 3
    if flags["city"]:
        rest = city.get(OTHER_CITY)
        charts["city"] = {"names": [c for c, _ in named_c], "values": [round(v, 1) for _, v in named_c]}
        tables["city"] = [[c, fmt.pct_of(v)] for c, v in named_c] + (
            [[OTHER_CITY, fmt.pct_of(rest)]] if rest is not None else [])
        yr = f" ב-{cy}" if cy else ""
        labels["city_note"] = (f"איזה חלק מתיקופי האוטובוסים בקווים קבועים{yr} נרשם בכל אחת מ-{len(named_c)} "
                               f"הערים הגדולות (שבהן 100,000 תושבים ויותר), באחוזים"
                               + (f". שאר היישובים יחד: {fmt.pct_of(rest)}." if rest is not None else "."))
        labels["city_aria"] = f"התפלגות תיקופי האוטובוסים לפי עיר{yr}"
        (c1, v1), (c2, v2) = named_c[0], named_c[1]
        big = sum(v for _, v in named_c)
        txt = f"{c1} מובילה עם {fmt.pct_of(v1)} מתיקופי האוטובוסים{yr}"
        if v2 and v1 / v2 >= 1.5:
            txt += f", פי {fmt.num_he(v1 / v2)} מ{c2} ({fmt.pct_of(v2)})"
        else:
            txt += f", ואחריה {c2} עם {fmt.pct_of(v2)}"
        txt += f". {len(named_c)} הערים הגדולות יחד מרכזות {fmt.pct_of(big)} מהתיקופים."
        add("city", txt)

    # ── modes and their profiles (latest year) ───────────────────────────
    m_cats, modes, my_ = _modes(*tabs["modes"]) if "modes" in tabs else ([], {}, None)
    flags["modes"] = len(modes) >= 2
    if flags["modes"]:
        mord = sorted(modes, key=lambda k: (-modes[k]["total"], k))
        yr = f" ב-{my_}" if my_ else ""
        allt = sum(modes[k]["total"] for k in mord)
        corder = [c for c in m_cats if c not in OTHER_PROFILE] + [c for c in m_cats if c in OTHER_PROFILE]
        share = {k: {c: modes[k]["cats"][c] / modes[k]["total"] * 100 for c in corder} for k in mord}
        charts["modes"] = {"names": mord, "cats": corder,
                           "series": [[round(share[k][c], 1) for k in mord] for c in corder]}
        charts["mode_tot"] = {"names": mord, "values": [_m(modes[k]["total"], 2) for k in mord]}
        tables["modes"] = [[k, _mil(modes[k]["total"], 2)] + [fmt.pct_of(share[k][c]) for c in corder]
                           for k in mord]
        labels["modes_cols"] = ["אמצעי תחבורה", "תיקופים (מיליונים)"] + corder
        labels["modes_note"] = (f"כמה תיקופים נרשמו{yr} בכל אמצעי תחבורה ציבורית שבהודעה, ואיך הם מתחלקים לפי "
                                f"פרופיל הנוסע, באחוזים מתיקופי אותו אמצעי.")
        labels["modes_aria"] = f"תיקופים לפי אמצעי תחבורה ופרופיל נוסע{yr}"
        labels["mode_tot_aria"] = f"סך התיקופים לפי אמצעי תחבורה{yr}"
        kpis["all_modes"] = {"value": round(allt / MILLION, 1), "display": _mil(allt), "tone": "brand"}
        labels["all_modes_kpi"] = f"תיקופים בכל אמצעי התחבורה שבהודעה{yr} (מיליונים)"
        rail = [k for k in mord if "רק\"ל" in k or "רכבת קלה" in k]
        if rail:
            rt = sum(modes[k]["total"] for k in rail)
            kpis["lrt"] = {"value": round(rt / MILLION, 1), "display": _mil(rt), "tone": "brand"}
            labels["lrt_kpi"] = f"תיקופים ברכבות הקלות{yr} (מיליונים)"
        top = mord[0]
        add("modes_total", f"{top} הם {fmt.pct(modes[top]['total'] / allt)} מתיקופי התחבורה הציבורית שבהודעה{yr} "
                           f"({_mil(modes[top]['total'])} מיליון מתוך {_mil(allt)} מיליון). אחריהם "
                           + fmt.join_he([f"{k} ({_mil(modes[k]['total'], 2)} מיליון)" for k in mord[1:3]]) + ".")
        named_p = [c for c in corder if c not in OTHER_PROFILE and c != "לא מוגדר"]
        if named_p:
            spread = {c: max(share[k][c] for k in mord) - min(share[k][c] for k in mord) for c in named_p}
            c = max(named_p, key=lambda x: (spread[x], x))
            hi = max(mord, key=lambda k: (share[k][c], k))
            lo = min(mord, key=lambda k: (share[k][c], k))
            if spread[c] >= 10:
                add("modes_profile", f"הפער הגדול ביותר בין אמצעי התחבורה הוא בפרופיל \"{c}\": "
                                     f"{fmt.pct_of(share[hi][c])} מהתיקופים ב{hi}{yr}, לעומת "
                                     f"{fmt.pct_of(share[lo][c])} ב{lo}.")

    # ── Carmelit ─────────────────────────────────────────────────────────
    carmel = _two_col_years(*tabs["carmel"], "carmel") if "carmel" in tabs else {}
    cyrs = sorted(carmel)
    flags["carmel"] = len(cyrs) >= 2
    if flags["carmel"]:
        charts["carmel"] = {"x": [str(y) for y in cyrs], "y": [round(carmel[y] / 1000) for y in cyrs]}
        tables["carmel"] = [[str(y), fmt.int_he(carmel[y] / 1000)] for y in cyrs]
        labels["carmel_note"] = f"תיקופים בכרמלית בחיפה בכל שנה, {cyrs[0]} עד {cyrs[-1]}, באלפים."
        labels["carmel_aria"] = f"תיקופי נסיעות בכרמלית לפי שנה, {cyrs[0]} עד {cyrs[-1]}"
        a = cyrs[-1]
        pk = max(cyrs, key=lambda y: (carmel[y], y))
        if pk != a:
            add("carmel", f"בכרמלית נרשמו ב-{a} {_thousands(carmel[a])} תיקופים, "
                          f"{fmt.pct(1 - carmel[a] / carmel[pk])} פחות מבשנת השיא {pk} "
                          f"({_thousands(carmel[pk])}).")
        else:
            add("carmel", f"בכרמלית נרשמו ב-{a} {_thousands(carmel[a])} תיקופים, "
                          f"המספר הגבוה ביותר מאז {cyrs[0]}.")

    by_id = {i["id"]: i for i in insights}
    top = [by_id[k] for k in PRIORITY if k in by_id][:MAX_TOP]
    top_ids = {i["id"] for i in top}
    callouts = {i["id"]: i["text_he"] for i in insights if i["id"] not in top_ids}

    # ── text ─────────────────────────────────────────────────────────────
    release = {"no": rel["RELEASE_NO"], "title": rel["TITLE"], "headline": rel["HEADLINE"],
               "url": rel["PAGE_URL"], "pdf": rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(rel["RELEASE_DATE"]))}
    labels["lede"] = (f"כמה נוסעים עולים לתחבורה הציבורית בישראל, מתי ואיפה, לפי תיקופי כרטיס רב-קו ואמצעי "
                      f"תשלום אחרים. הנתונים מתוך ההודעה השנתית של הלשכה המרכזית לסטטיסטיקה (הלמ\"ס) ומתעדכנים "
                      f"עם כל הודעה חדשה. ב-{ly} נרשמו באוטובוסים בקווים קבועים {_mil(last)} מיליון תיקופים.")
    summary = (f"תיקופי נסיעות בתחבורה הציבורית לפי נתוני הלמ\"ס: {_mil(last)} מיליון תיקופים באוטובוסים ב-{ly}, "
               f"לפי חודש, שעה, יום בשבוע, עיר ופרופיל נוסע, וגם ברכבות הקלות ובכרמלית.")
    desc = (f"כמה נוסעים בתחבורה הציבורית: {_mil(last)} מיליון תיקופי רב-קו באוטובוסים ב-{ly}, "
            f"לפי שעה, יום, חודש, עיר ופרופיל נוסע. נתוני הלמ\"ס.")
    t_years = yrs + cyrs
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{min(t_years)}/{max(t_years)}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "תיקופי רב-קו: נוסעים בתחבורה ציבורית | הלמ\"ס",
                "description": desc,
                "name": "תיקופי נסיעות בתחבורה ציבורית",
                "alternate_names": ["תיקופי רב-קו", "מספר הנוסעים בתחבורה הציבורית",
                                    "נוסעים באוטובוסים בישראל", "תיקופים באוטובוסים וברכבת הקלה"],
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
