"""מספר המשרות הפנויות: CBS's monthly job-vacancy survey release.

Each edition (published monthly, titled by its rolling 3-month window)
carries seven chart-data tables, each a monthly series since 2019:
  t1  total job vacancies: original, seasonally adjusted, trend
  t2  job-vacancy rate (% of jobs): original, SA, trend
  t3  vacancies in manufacturing, mining, electricity and water: SA, trend
  t4  vacancies in construction: SA, trend
  t5  vacancies in trade: SA, trend
  t6  vacancies in services: SA, trend
  t7  vacancies by business size (employee jobs: 5-9, 10-49, 50-99, 100+),
      original data
  releases  the edition list (number, date, headline, link)

Header rows and columns are found by their Hebrew labels and raise when
missing. The trend column is optional: CBS skipped trend estimates in the
editions that followed the 2026 war ("שאגת הארי"), so an empty or missing
trend only leaves its line empty. Month rows are counted from each year's
first row (govlib.cbs.monthly_runs), so a cut-off table only shortens a
series. "Latest month" is t1's newest seasonally adjusted month.
"""
import re

import pandas as pd
from govlib import cbs, fmt

SECTORS = [  # (input, keyword its title must carry, page name)
    ("t3", "תעשייה", "תעשייה, כרייה, חשמל ומים"),
    ("t4", "בינוי", "בינוי"),
    ("t5", "מסחר", "מסחר"),
    ("t6", "שירותים", "שירותים"),
]
SIZE_RX = re.compile(r"^(\d+)(?:-(\d+)|\+)$")
BASE_YEAR = 2019  # the survey's pre-COVID year, first in the tables
FLAT = 0.02  # a change under 2% reads as "stable"


# ── tables ───────────────────────────────────────────────────────────────


def _title(rows, name):
    """The Hebrew chart title (the cell starting with "תרשים")."""
    for r in rows[:10]:
        for c in r:
            if c.startswith("תרשים"):
                return c
    raise ValueError(f"{name}: chart title not found")


def _series(rows, name, orig=True):
    """[{t: (y, m), orig?, sa, trend}] from a chart table with Hebrew
    headers "אומדן לסדרה מקורית" / "מנוכי עונתיות" / "מגמה"."""
    h = cbs.row_with(rows, "מנוכי עונתיות", name=name, contains=True)
    sa = cbs.col_after(rows[h], "מנוכי עונתיות", 0, contains=True)
    try:
        trend = cbs.col_after(rows[h], "מגמה", 0)
    except ValueError:
        trend = None  # no trend estimates in this edition
    oc = cbs.col_after(rows[h], "מקורית", 0, contains=True) if orig else None
    out = []
    for i, y, m in cbs.monthly_runs(rows, h + 1, len(rows), sa):
        rec = {"t": (y, m), "sa": cbs.val(rows[i], sa),
               "trend": cbs.val(rows[i], trend) if trend is not None else None}
        if orig:
            rec["orig"] = cbs.val(rows[i], oc)
        out.append(rec)
    return out


def _sizes(rows, name="t7"):
    """(size labels, [{t, values}]) from the by-size table, original data."""
    h = next((i for i, r in enumerate(rows)
              if sum(bool(SIZE_RX.match(c)) for c in r) >= 2), None)
    if h is None:
        raise ValueError(f"{name}: size-group header row not found")
    cols = [(j, c) for j, c in enumerate(rows[h]) if SIZE_RX.match(c)]
    cols.sort(key=lambda jc: (int(SIZE_RX.match(jc[1]).group(1)), jc[0]))
    out = []
    for i, y, m in cbs.monthly_runs(rows, h + 1, len(rows), cols[0][0]):
        vals = [cbs.val(rows[i], j) for j, _ in cols]
        if all(v is not None for v in vals):
            out.append({"t": (y, m), "v": vals})
    return [c for _, c in cols], out


# ── formatting ───────────────────────────────────────────────────────────


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mkey(t):
    return f"{t[0]}-{t[1]:02d}"


def _size_he(label):
    m = SIZE_RX.match(label)
    if m.group(2):
        return f"{m.group(1)}-{m.group(2)} משרות"
    return f"{m.group(1)} משרות ומעלה"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _dir(c, up="עלייה", down="ירידה"):
    return up if c > 0 else down


def _r(v, d=0):
    if v is None:
        return None
    return round(v, d) if d else round(v)


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    total = [r for r in _series(cbs.grid(frames["t1"], "t1"), "t1") if r["sa"] is not None]
    rate = [r for r in _series(cbs.grid(frames["t2"], "t2"), "t2") if r["sa"] is not None]
    if not total:
        raise ValueError("t1: no seasonally adjusted months")
    tot = {r["t"]: r for r in total}
    rt = {r["t"]: r for r in rate}
    lt = total[-1]["t"]
    last = tot[lt]
    prev_m = total[-2] if len(total) >= 2 else None
    year_ago = tot.get((lt[0] - 1, lt[1]))
    last_rate = rt.get(lt)
    yago_rate = rt.get((lt[0] - 1, lt[1]))

    sectors = []
    for name, kw, label in SECTORS:
        rows = cbs.grid(frames[name], name)
        if kw not in _title(rows, name):
            raise ValueError(f"{name}: title no longer mentions {kw!r}")
        s = {r["t"]: r for r in _series(rows, name, orig=False) if r["sa"] is not None}
        sectors.append({"id": name, "name": label, "s": s})
    size_labels, size_rows = _sizes(cbs.grid(frames["t7"], "t7"))

    yoy = _chg(last["sa"], year_ago["sa"] if year_ago else None)
    mom = _chg(last["sa"], prev_m["sa"] if prev_m else None)
    base = [r for r in total if r["t"][0] == BASE_YEAR]
    base_avg = _mean([r["sa"] for r in base]) if len(base) == 12 else None
    vs_base = _chg(last["sa"], base_avg)

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["total"] = {"value": round(last["sa"]), "display": fmt.int_he(last["sa"]),
                     "tone": "brand"}
    labels["total_kpi"] = f"משרות פנויות, {_mname(lt)} (מנוכה עונתיות)"
    if last_rate:
        kpis["rate"] = {"value": round(last_rate["sa"], 2),
                        "display": fmt.pct_of(last_rate["sa"], 1), "tone": "info"}
        labels["rate_kpi"] = "שיעור המשרות הפנויות מכלל המשרות"
    if yoy is not None:
        kpis["yoy"] = {"value": round(yoy, 4), "display": fmt.signed_pct(yoy),
                       "tone": "ok" if yoy > FLAT else "warn" if yoy < -FLAT else "brand"}
        labels["yoy_kpi"] = f"שינוי לעומת {_mname((lt[0] - 1, lt[1]))}"
    if vs_base is not None:
        kpis["base"] = {"value": round(vs_base, 4), "display": fmt.signed_pct(vs_base),
                        "tone": "info"}
        labels["base_kpi"] = f"לעומת הממוצע של {BASE_YEAR}, לפני הקורונה"

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables, flags = {}, {}, {}
    charts["total"] = {"x": [_mkey(r["t"]) for r in total],
                       "orig": [_r(r["orig"]) for r in total],
                       "sa": [_r(r["sa"]) for r in total],
                       "trend": [_r(r["trend"]) for r in total]}
    years = sorted({r["t"][0] for r in total})
    tables["total"] = []
    for y in reversed(years):
        ms = [r for r in total if r["t"][0] == y]
        tables["total"].append([str(y), fmt.int_he(_mean([r["orig"] for r in ms])),
                                fmt.int_he(_mean([r["sa"] for r in ms])), str(len(ms))])
    flags["trend"] = any(r["trend"] is not None for r in total)

    flags["rate"] = bool(rate)
    if rate:
        charts["rate"] = {"x": [_mkey(r["t"]) for r in rate],
                          "orig": [_r(r["orig"], 2) for r in rate],
                          "sa": [_r(r["sa"], 2) for r in rate],
                          "trend": [_r(r["trend"], 2) for r in rate]}
        tables["rate"] = []
        for y in sorted({r["t"][0] for r in rate}, reverse=True):
            ms = [r["sa"] for r in rate if r["t"][0] == y]
            tables["rate"].append([str(y), fmt.pct_of(_mean(ms), 2),
                                   fmt.pct_of(min(ms), 2), fmt.pct_of(max(ms), 2)])

    # month × year heatmap of the original count (seasonality)
    hm = [[m - 1, years.index(r["t"][0]), _r(r["orig"])]
          for r in total if r["orig"] is not None for m in [r["t"][1]]]
    flags["season"] = len(years) >= 3 and len(hm) >= 24
    if flags["season"]:
        charts["season"] = {"months": fmt.MONTHS_SHORT_HE, "years": [str(y) for y in years],
                            "cells": hm,
                            "min": min(c[2] for c in hm), "max": max(c[2] for c in hm)}
        by_ym = {r["t"]: r["orig"] for r in total}
        tables["season"] = [[fmt.MONTHS_HE[m - 1]]
                            + [fmt.int_he(by_ym[(y, m)]) if by_ym.get((y, m)) is not None
                               else "–" for y in years] for m in range(1, 13)]
        labels["season_years"] = [str(y) for y in years]

    # sectors: SA over time (stacked), latest month and change
    months = [r["t"] for r in total]
    flags["sectors"] = all(lt in s["s"] for s in sectors)
    if flags["sectors"]:
        sec_months = [t for t in months if all(t in s["s"] for s in sectors)]
        charts["sectors"] = {"x": [_mkey(t) for t in sec_months],
                             "names": [s["name"] for s in sectors],
                             "series": [[_r(s["s"][t]["sa"]) for t in sec_months]
                                        for s in sectors]}
        sec_sum = sum(s["s"][lt]["sa"] for s in sectors)
        tables["sectors"] = []
        sec_stats = []
        for s in sectors:
            v = s["s"][lt]["sa"]
            ya = s["s"].get((lt[0] - 1, lt[1]))
            b = [s["s"][(BASE_YEAR, m)]["sa"] for m in range(1, 13) if (BASE_YEAR, m) in s["s"]]
            bavg = _mean(b) if len(b) == 12 else None
            c_y = _chg(v, ya["sa"] if ya else None)
            c_b = _chg(v, bavg)
            sec_stats.append({"name": s["name"], "v": v, "share": v / sec_sum,
                              "yoy": c_y, "base": c_b, "bavg": bavg})
            tables["sectors"].append([s["name"], fmt.int_he(v), fmt.pct(v / sec_sum),
                                      fmt.signed_pct(c_y) if c_y is not None else "–",
                                      fmt.signed_pct(c_b) if c_b is not None else "–"])
        # growth since the base year: index, base-year average = 100
        flags["index"] = all(st["bavg"] for st in sec_stats)
        if flags["index"]:
            charts["index"] = {"x": charts["sectors"]["x"],
                               "names": [s["name"] for s in sectors],
                               "series": [[_r(s["s"][t]["sa"] / st["bavg"] * 100, 1)
                                           for t in sec_months]
                                          for s, st in zip(sectors, sec_stats, strict=True)]}
            recent = sec_months[-12:]
            tables["index"] = []
            for s, st in zip(sectors, sec_stats, strict=True):
                r12 = _mean([s["s"][t]["sa"] for t in recent])
                tables["index"].append([s["name"], fmt.int_he(st["bavg"]), fmt.int_he(r12),
                                        fmt.signed_pct(_chg(r12, st["bavg"]))])
    else:
        flags["index"] = False
        sec_stats = []

    # business size: original data, annual averages and the latest month
    flags["size"] = bool(size_rows)
    if size_rows:
        sy = sorted({r["t"][0] for r in size_rows})
        avg = {y: [_mean([r["v"][k] for r in size_rows if r["t"][0] == y])
                   for k in range(len(size_labels))] for y in sy}
        nmon = {y: sum(1 for r in size_rows if r["t"][0] == y) for y in sy}
        charts["size"] = {"years": [str(y) for y in sy],
                          "names": [_size_he(c) for c in size_labels],
                          "series": [[_r(avg[y][k]) for y in sy]
                                     for k in range(len(size_labels))]}
        tables["size"] = [[str(y)] + [fmt.int_he(v) for v in avg[y]] + [str(nmon[y])]
                          for y in reversed(sy)]
        labels["size_cols"] = [_size_he(c) for c in size_labels]
        size_last = size_rows[-1]
        s_tot = sum(size_last["v"])
        charts["size_mix"] = [{"name": _size_he(c), "value": _r(v)}
                              for c, v in zip(size_labels, size_last["v"], strict=True)]
        size_ya = next((r for r in size_rows
                        if r["t"] == (size_last["t"][0] - 1, size_last["t"][1])), None)
        tables["size_mix"] = []
        for k, c in enumerate(size_labels):
            v = size_last["v"][k]
            c_y = _chg(v, size_ya["v"][k] if size_ya else None)
            tables["size_mix"].append([_size_he(c), fmt.int_he(v), fmt.pct(v / s_tot),
                                       fmt.signed_pct(c_y) if c_y is not None else "–"])

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if yoy is not None:
        s = (f"ב{_mname(lt)} היו בישראל {fmt.int_he(last['sa'])} משרות פנויות (מנוכה עונתיות)")
        if last_rate:
            s += f", {fmt.pct_of(last_rate['sa'], 1)} מכלל המשרות במשק"
        if abs(yoy) < FLAT:
            s += f". המספר כמעט זהה לזה של {_mname((lt[0] - 1, lt[1]))}"
        else:
            s += f". זו {_dir(yoy)} של {fmt.pct(abs(yoy))} לעומת {_mname((lt[0] - 1, lt[1]))}"
        if last_rate and yago_rate:
            s += f" (אז {fmt.pct_of(yago_rate['sa'], 1)})"
        add("yoy", s + ".")
    if mom is not None and abs(mom) >= FLAT:
        add("mom", f"לעומת {_mname(prev_m['t'])} {'עלה' if mom > 0 else 'ירד'} מספר המשרות "
                   f"הפנויות ב-{fmt.pct(abs(mom))} (מנוכה עונתיות), מ-{fmt.int_he(prev_m['sa'])} "
                   f"ל-{fmt.int_he(last['sa'])}.")

    if len(total) >= 24:
        peak = max(total, key=lambda r: (r["sa"], r["t"]))
        low = min(total, key=lambda r: (r["sa"], r["t"]))
        if low["t"] != lt and peak["t"] != low["t"]:
            gap = _chg(last["sa"], peak["sa"])
            s = (f"השפל בסדרה המנוכה עונתיות היה ב{_mname(low['t'])}: {fmt.int_he(low['sa'])} משרות פנויות "
                 f"בלבד. השיא נרשם ב{_mname(peak['t'])}, {fmt.int_he(peak['sa'])} משרות")
            if peak["t"] == lt:
                s += ", וזה גם החודש האחרון בנתונים."
            else:
                s += f", והחודש האחרון נמוך ממנו ב-{fmt.pct(abs(gap))}."
            add("extremes", s)
    if vs_base is not None and abs(vs_base) >= FLAT:
        add("base", f"מספר המשרות הפנויות ב{_mname(lt)} {'גבוה' if vs_base > 0 else 'נמוך'} "
                    f"ב-{fmt.pct(abs(vs_base))} מהממוצע החודשי בשנת {BASE_YEAR}, לפני "
                    f"הקורונה ({fmt.int_he(base_avg)} משרות, מנוכה עונתיות).")

    # Six calendar months back, by date: the trend column can have gaps
    # (CBS skipped trend estimates in some editions).
    t6 = (lt[0], lt[1] - 6) if lt[1] > 6 else (lt[0] - 1, lt[1] + 6)
    tr6 = tot.get(t6)
    if last["trend"] is not None and tr6 is not None and tr6["trend"] is not None:
        c = _chg(last["trend"], tr6["trend"])
        if c is not None:
            word = ("יציבה" if abs(c) < FLAT else "עולה" if c > 0 else "יורדת")
            add("trend", f"קו המגמה, שמנטרל תנודות חד-פעמיות, מראה מגמה {word}: "
                         f"{fmt.signed_pct(c)} בחצי השנה שבין {_mname(t6)} "
                         f"ל{_mname(lt)}.")
    if sec_stats:
        big = max(sec_stats, key=lambda s: (s["share"], s["name"]))
        add("sector_share", f"{fmt.pct(big['share'])} מהמשרות הפנויות ב{_mname(lt)} היו "
                            f"בענפי ה{big['name']} ({fmt.int_he(big['v'])} משרות, מנוכה "
                            f"עונתיות)."
            if big["share"] >= 0.4 else None)
        grown = [s for s in sec_stats if s["base"] is not None]
        if len(grown) >= 2:
            grown.sort(key=lambda s: (-s["base"], s["name"]))
            hi, lo = grown[0], grown[-1]
            if hi["base"] - lo["base"] >= 0.1:
                add("sector_growth",
                    f"לעומת {BASE_YEAR}, הביקוש לעובדים גדל יותר מכול בענפי ה{hi['name']}: "
                    f"{fmt.signed_pct(hi['base'])} במשרות הפנויות, לעומת "
                    f"{fmt.signed_pct(lo['base'])} בענפי ה{lo['name']}.")
        moves = [s for s in sec_stats if s["yoy"] is not None]
        if moves:
            m = max(moves, key=lambda s: (abs(s["yoy"]), s["name"]))
            if abs(m["yoy"]) >= 0.1:
                add("sector_yoy", f"השינוי השנתי החד ביותר הוא בענפי ה{m['name']}: "
                                  f"{_dir(m['yoy'])} של {fmt.pct(abs(m['yoy']))} במשרות "
                                  f"הפנויות לעומת {_mname((lt[0] - 1, lt[1]))}.")
    if size_rows:
        k_big = max(range(len(size_labels)), key=lambda k: (size_last["v"][k], -k))
        share = size_last["v"][k_big] / s_tot
        if share >= 0.3:
            add("size", f"{fmt.pct(share)} מהמשרות הפנויות ב{_mname(size_last['t'])} היו "
                        f"בעסקים של {_size_he(size_labels[k_big])} (נתון מקורי).")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"כמה משרות פנויות יש בישראל, איזה חלק מכלל המשרות הן מהוות, ובאילו ענפים "
                 f"המעסיקים מחפשים עובדים. הנתונים מסקר המשרות הפנויות של הלשכה המרכזית "
                 f"לסטטיסטיקה (הלמ\"ס), שמתפרסם מדי חודש, ומתעדכנים עם כל הודעה חדשה. "
                 f"החודש האחרון בנתונים הוא {_mname(lt)}: {fmt.int_he(last['sa'])} משרות "
                 f"פנויות, מנוכה עונתיות."),
        "total_note": (f"מספר המשרות הפנויות בכל חודש מאז {_mname(total[0]['t'])}: האומדן "
                       f"המקורי, הנתון המנוכה עונתיות"
                       + (" וקו המגמה" if flags["trend"] else "")
                       + ". אפשר לגרור כדי להתמקד בתקופה."),
        "total_aria": f"משרות פנויות לפי חודש, {_mname(total[0]['t'])} עד {_mname(lt)}",
        "total_caption": "משרות פנויות, ממוצע חודשי לפי שנה",
        "sectors_note": ("המשרות הפנויות בארבע קבוצות הענפים, מנוכה עונתיות, זו על גבי זו. "
                         "בטבלה: החודש האחרון, החלק מהסך, השינוי בשנה והשינוי לעומת "
                         f"הממוצע של {BASE_YEAR}."),
        "sectors_aria": "משרות פנויות לפי קבוצת ענפים לאורך זמן",
        "sectors_caption": f"משרות פנויות לפי קבוצת ענפים, {_mname(lt)}",
        "index_note": (f"כמה גדל הביקוש לעובדים בכל קבוצת ענפים: המשרות הפנויות ביחס לממוצע "
                       f"החודשי של {BASE_YEAR}, שמוצג כ-100. קו מעל 100 פירושו יותר משרות "
                       f"פנויות מאשר לפני הקורונה."),
        "index_aria": f"מדד המשרות הפנויות לפי קבוצת ענפים, {BASE_YEAR} = 100",
        "index_caption": f"שינוי לעומת הממוצע של {BASE_YEAR}, לפי קבוצת ענפים",
        "base_year": str(BASE_YEAR),
    })
    if rate:
        labels.update({
            "rate_note": ("שיעור המשרות הפנויות: המשרות הפנויות כאחוז מכלל המשרות (המאוישות "
                          "והפנויות). שיעור גבוה מעיד על שוק עבודה הדוק, שבו למעסיקים קשה "
                          "יותר למצוא עובדים."),
            "rate_aria": f"שיעור המשרות הפנויות לפי חודש, {_mname(rate[0]['t'])} עד "
                         f"{_mname(rate[-1]['t'])}",
            "rate_caption": "שיעור המשרות הפנויות לפי שנה, מנוכה עונתיות",
        })
    if flags["season"]:
        labels.update({
            "season_note": ("האומדן המקורי (לא מנוכה עונתיות) בכל חודש ושנה. צבע כהה יותר "
                            "פירושו יותר משרות פנויות. כך רואים גם את העונתיות וגם את "
                            "השבר של הקורונה ושל המלחמות."),
            "season_aria": "משרות פנויות לפי חודש ושנה, מפת חום",
            "season_caption": "משרות פנויות לפי חודש ושנה, אומדן מקורי",
        })
    if size_rows:
        labels.update({
            "size_note": ("המשרות הפנויות לפי גודל העסק (מספר משרות השכיר בו), ממוצע חודשי "
                          "לכל שנה, נתון מקורי. השנה האחרונה חלקית."
                          if nmon[sy[-1]] < 12 else
                          "המשרות הפנויות לפי גודל העסק (מספר משרות השכיר בו), ממוצע "
                          "חודשי לכל שנה, נתון מקורי."),
            "size_aria": "משרות פנויות לפי גודל העסק ושנה",
            "size_caption": "משרות פנויות לפי גודל העסק, ממוצע חודשי",
            "size_mix_note": (f"החלוקה ב{_mname(size_last['t'])} לפי גודל העסק, והשינוי לעומת "
                              f"אותו חודש בשנה הקודמת."),
            "size_mix_aria": f"משרות פנויות לפי גודל העסק, {_mname(size_last['t'])}",
            "size_mix_caption": f"משרות פנויות לפי גודל העסק, {_mname(size_last['t'])}",
        })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = (f"מספר המשרות הפנויות בישראל לפי חודש, ענף וגודל עסק, מסקר המשרות הפנויות של "
               f"הלמ\"ס. ב{_mname(lt)}: {fmt.int_he(last['sa'])} משרות פנויות"
               + (f", {fmt.pct_of(last_rate['sa'], 1)} מכלל המשרות" if last_rate else "")
               + ".")
    desc = (f"כמה משרות פנויות יש בישראל: {fmt.int_he(last['sa'])} ב{_mname(lt)}"
            + (f" ({fmt.signed_pct(yoy)} בשנה)" if yoy is not None else "")
            + ". שיעור המשרות הפנויות, לפי ענף וגודל עסק.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{total[0]['t'][0]}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "מספר המשרות הפנויות בישראל: נתון חודשי | הלמ\"ס",
                "description": desc,
                "name": "מספר המשרות הפנויות בישראל",
                "alternate_names": ["סקר משרות פנויות", "שיעור המשרות הפנויות",
                                    "משרות פנויות לפי ענף", "ביקוש לעובדים בישראל"],
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
