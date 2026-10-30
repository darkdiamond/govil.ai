"""מחירים תיאורטיים של מוצרי דלק שאינם בפיקוח (Ministry of Energy).

One long table: one row per (month, product, unit) with the theoretical
(maximum) ex-refinery price that the ministry computes each month. Prices are
in NIS per metric ton or per kilolitre, as the unit column says.

Product names are not stable. In April 2025 the ministry re-labelled most
series (footnote marks "(**)" became "(*)", "במיכליות" became "במכלית", the
diesel sulfur clause was dropped) and stopped publishing the fuel-oil
grades; LPG stopped in January 2024. `canon()` folds those spellings into
one series per (product, unit), with generic rules plus a short alias table;
an unknown new name flows through as its own series.

A "family" is a product without its delivery mode (pipeline / tanker /
by quote). Each family gets one representative series (pipeline, not
by-quote, longest history) used for the unit-free comparisons (index, range
position, monthly-change heatmap, top moves).

"Latest" is the latest month in the data, never the wall clock.
"""
import re

import pandas as pd

MINUS = "−"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

UNIT_ORDER = ["קילו ליטר", "טון מטרי"]
UNIT_SHORT = {"קילו ליטר": "לקו״ל", "טון מטרי": "לטון"}
UNIT_TITLE = {"קילו ליטר": "מוצרים המתומחרים לקילו-ליטר",
              "טון מטרי": "מוצרים המתומחרים לטון מטרי"}

ALIASES = {"סולר להסקה במכלית 0.1% גופרית": "סולר להסקה"}

PIPE, TANK, QUOTE = "בהזרמה", "במכלית", 'ע"פ ציטוט'

MAX_MONTHS_MONTHLY = 240   # beyond this the line charts switch to quarterly means
HEAT_MONTHS = 24
TREND_PCT = 3.0            # |YoY change| below this reads as "stable"
NEAR_PEAK = 0.85           # range position at/above this reads as "near the high"
NEAR_LOW = 0.15
TOP_MOVES = 10
MAX_YEARS_TABLE = 15
MAX_LATEST = 20
MAX_UNITS = 4
SUMMARY_MAX = 155
PARTIAL_SHARE = 0.5


# ── helpers ──────────────────────────────────────────────────────────────

def _norm_space(s):
    return re.sub(r"\s+", " ", s).strip()


def canon(name):
    s = name.replace("״", '"').replace("׳", "'")
    s = re.sub(r"\(\*+\)\d*", " ", s)
    s = s.replace("במיכליות", TANK)
    s = re.sub(r'שתכולת הגופרית בו אינה עולה על [\d.,]+ מ"ג לק"ג', " ", s)
    s = _norm_space(s)
    return ALIASES.get(s, s)


def family_of(c):
    s = c.replace(QUOTE, " ").replace(PIPE, " ").replace(TANK, " ")
    return _norm_space(s)


def is_adjust(c):
    return c.startswith("תוספת") or c.startswith("הפחתה")


def mlabel(m):
    y, mo = m.split("-")
    return f"{MONTHS_HE[int(mo) - 1]} {y}"


def mshort(m):
    y, mo = m.split("-")
    return f"{mo}/{y}"


def fmt_price(v):
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def fmt_signed(v, digits=1, unit="%"):
    s = f"{abs(v):,.{digits}f}{unit}"
    if round(v, digits) > 0:
        return "+" + s
    if round(v, digits) < 0:
        return MINUS + s
    return s


def r2(v):
    return None if v is None or pd.isna(v) else round(float(v), 2)


def pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1.0) * 100.0


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    df = frames["main"].copy()
    df["date"] = pd.to_datetime(df["תאריך"].str.strip().str[:10], format="%Y-%m-%d", errors="coerce")
    df["price"] = pd.to_numeric(df["מחיר"].str.replace(",", "", regex=False).str.strip(), errors="coerce")
    df["name"] = df["מוצר"].map(lambda s: canon(str(s)))
    df["unit"] = df["יחידת מידה"].map(lambda s: _norm_space(str(s)))
    n_raw = len(df)
    df = df[df["date"].notna() & df["price"].notna() & (df["name"] != "") & (df["unit"] != "")]
    n_bad = n_raw - len(df)
    df["month"] = df["date"].dt.strftime("%Y-%m")

    # one value per (series, month): the latest-dated row, then highest price (total order)
    df = df.sort_values(["name", "unit", "month", "date", "price"], kind="mergesort")
    df = df.drop_duplicates(["name", "unit", "month"], keep="last")

    # A last month carrying under half the previous month's series is a
    # partial upload: excluded (disclosed) so live series don't look stopped.
    per_month = df.groupby("month").size().to_dict()
    months = sorted(per_month)
    partial = None
    if len(months) > 2 and per_month[months[-1]] < PARTIAL_SHARE * per_month[months[-2]]:
        partial = months[-1]
        df = df[df["month"] != partial]
        months = months[:-1]
    latest = months[-1]
    first = months[0]
    mi = {m: i for i, m in enumerate(months)}

    # series table
    units_seen = sorted(df["unit"].unique().tolist(),
                        key=lambda u: (UNIT_ORDER.index(u) if u in UNIT_ORDER else 99, u))
    names_per_canon = df.groupby("name")["unit"].nunique().to_dict()
    series = {}
    for (name, unit), g in df.groupby(["name", "unit"], sort=True):
        vals = dict(zip(g["month"], g["price"].astype(float)))
        label = name
        if names_per_canon.get(name, 1) > 1:
            label = f"{name} ({UNIT_SHORT.get(unit, unit)})"
        ms = sorted(vals)
        series[(name, unit)] = {
            "name": name, "unit": unit, "label": label, "family": family_of(name),
            "vals": vals, "first": ms[0], "last": ms[-1], "n": len(ms),
            "adjust": is_adjust(name),
        }
    keys = sorted(series, key=lambda k: (units_seen.index(k[1]), k[0]))
    active = [k for k in keys if series[k]["last"] == latest and not series[k]["adjust"]]

    # family representatives
    fams = {}
    for k in keys:
        s = series[k]
        if s["adjust"]:
            continue
        fams.setdefault((s["family"], s["unit"]), []).append(k)
    # one representative per family across units (kl first): unit-free views
    by_fam = {}
    for (fam, _u), ks in fams.items():
        by_fam.setdefault(fam, []).extend(ks)
    reps = {}
    for fam, ks in by_fam.items():
        reps[fam] = sorted(ks, key=lambda k: (QUOTE in k[0], PIPE not in k[0], units_seen.index(k[1]),
                                              -series[k]["n"], k[0]))[0]
    rep_keys = sorted(reps.values(), key=lambda k: (units_seen.index(k[1]), k[0]))
    rep_active = [k for k in rep_keys if series[k]["last"] == latest]

    def flabel(k):
        s = series[k]
        fam = s["family"]
        return fam

    def val(k, m):
        return series[k]["vals"].get(m)

    def month_shift(m, d):
        y, mo = int(m[:4]), int(m[5:7])
        t = y * 12 + (mo - 1) + d
        return f"{t // 12:04d}-{t % 12 + 1:02d}"

    # ── per-unit line charts ──
    quarterly = len(months) > MAX_MONTHS_MONTHLY
    if quarterly:
        def qkey(m):
            return f"{m[:4]}-Q{(int(m[5:7]) - 1) // 3 + 1}"
        axis = sorted({qkey(m) for m in months})
    else:
        axis = months
    unit_charts = []
    for u in units_seen[:MAX_UNITS]:
        ks = [k for k in keys if k[1] == u and not series[k]["adjust"]]
        if not ks:
            continue
        sers = []
        selected = {}
        for k in ks:
            s = series[k]
            if quarterly:
                buckets = {}
                for m, v in s["vals"].items():
                    buckets.setdefault(qkey(m), []).append(v)
                data = [r2(sum(buckets[a]) / len(buckets[a])) if a in buckets else None for a in axis]
            else:
                data = [r2(s["vals"].get(m)) for m in axis]
            sers.append({"name": s["label"], "data": data})
            selected[s["label"]] = k in reps.values() or not any(
                k2 in reps.values() for k2 in ks)
        last_vals = [(series[k]["vals"][latest], series[k]["label"]) for k in ks if latest in series[k]["vals"]]
        if last_vals:
            hi = sorted(last_vals, key=lambda t: (-t[0], t[1]))[0]
            lede = (f"{len(ks)} סדרות מחיר ביחידה זו, מהן {len(last_vals)} מתפרסמות גם ב{mlabel(latest)}. "
                    f"היקר ביותר החודש: {hi[1]}, {fmt_price(hi[0])} ש״ח {UNIT_SHORT.get(u, u)}.")
        else:
            lede = f"{len(ks)} סדרות מחיר ביחידה זו; אף אחת מהן אינה מתפרסמת עוד ב{mlabel(latest)}."
        lede += " בתחילה מוצגת סדרה אחת לכל מוצר; שאר הסדרות זמינות דרך המקרא."
        if quarterly:
            lede += " הסדרה מוצגת כממוצע רבעוני."
        unit_charts.append({
            "unit": u, "title": UNIT_TITLE.get(u, f"מוצרים ביחידת {u}"),
            "ytitle": f"ש״ח {UNIT_SHORT.get(u, u)}",
            "x": [mshort(m) if not quarterly else m for m in axis],
            "series": sers, "selected": selected, "lede": lede,
            "aria": f"גרף קווים: מחיר תיאורטי חודשי של {len(ks)} סדרות ב{UNIT_TITLE.get(u, u)}, {mlabel(first)} עד {mlabel(latest)}.",
        })

    # ── yearly averages (index + table) ──
    years = sorted({m[:4] for m in months})
    year_counts = {y: sum(1 for m in months if m[:4] == y) for y in years}
    full_n = max(year_counts.values())
    ylabels = [y if year_counts[y] >= full_n or y != years[-1] else f"{y} ({year_counts[y]} ח׳)" for y in years]
    idx_series, table_cols, idx_selected = [], [], {}
    yavg = {}
    for k in rep_keys:
        s = series[k]
        row = {}
        for y in years:
            vs = [v for m, v in s["vals"].items() if m[:4] == y]
            row[y] = sum(vs) / len(vs) if vs else None
        yavg[k] = row
        base_y = next((y for y in years if row[y] is not None), None)
        base = row[base_y]
        idx_selected[flabel(k)] = series[k]["last"] == latest
        idx_series.append({"name": flabel(k),
                           "data": [r2(row[y] / base * 100) if row[y] is not None and base else None for y in years]})
        table_cols.append(flabel(k))
    tyears = years[-MAX_YEARS_TABLE:]
    yrows = [{"year": ylabels[years.index(y)],
              "vals": [fmt_price(yavg[k][y]) if yavg[k][y] is not None else "" for k in rep_keys]}
             for y in tyears]
    # biggest yearly jump among active reps
    jump = None
    for k in rep_active:
        row = yavg[k]
        for a, b in zip(years, years[1:]):
            if row[a] and row[b] and year_counts[b] >= full_n:
                c = pct(row[b], row[a])
                cand = (c, flabel(k), b)
                if jump is None or (c, cand[1], b) > (jump[0], jump[1], jump[2]):
                    jump = cand
    idx_lede = "כל מוצר מוצג ביחס לממוצע השנה הראשונה שבה פורסם (=100), כך שאפשר להשוות מוצרים ביחידות שונות."
    if jump and jump[0] > 0:
        idx_lede += f" הזינוק השנתי החד ביותר: {jump[1]} ב-{jump[2]}, {fmt_signed(jump[0])} בממוצע השנתי."
    if year_counts[years[-1]] < full_n:
        idx_lede += f" שנת {years[-1]} חלקית ({year_counts[years[-1]]} חודשים)."

    # ── latest vs a year ago (all active series) ──
    ago = month_shift(latest, -12)
    lat_rows = []
    for k in active:
        v = val(k, latest)
        p = val(k, ago)
        c = pct(v, p)
        lat_rows.append({"label": series[k]["label"], "unit": UNIT_SHORT.get(k[1], k[1]),
                         "price": v, "prev": p, "chg": c})
    lat_rows.sort(key=lambda r: (-(r["chg"] if r["chg"] is not None else -1e9), r["label"]))
    with_chg = [r for r in lat_rows if r["chg"] is not None]   # all live series: counts, insights
    lat_rows = lat_rows[:MAX_LATEST]                              # chart/table only
    shown_chg = [r for r in lat_rows if r["chg"] is not None]
    yoy_chart = {"names": [r["label"] for r in reversed(shown_chg)],
                 "values": [round(r["chg"], 1) for r in reversed(shown_chg)]}
    yoy_table = [{"label": r["label"], "unit": r["unit"], "price": fmt_price(r["price"]),
                  "prev": fmt_price(r["prev"]) if r["prev"] is not None else "",
                  "chg": fmt_signed(r["chg"]) if r["chg"] is not None else ""} for r in lat_rows]
    ups = sum(1 for r in with_chg if r["chg"] >= TREND_PCT)
    downs = sum(1 for r in with_chg if r["chg"] <= -TREND_PCT)
    if with_chg:
        flat = len(with_chg) - ups - downs
        yoy_lede = (f"מחיר {mlabel(latest)} לעומת {mlabel(ago)}, ב-{len(with_chg)} סדרות: "
                    f"{ups} עלו ביותר מ-{TREND_PCT:.0f}%, {downs} ירדו ביותר מ-{TREND_PCT:.0f}% "
                    f"ו-{flat} השתנו פחות מכך.")
    else:
        yoy_lede = f"אין עדיין נתון של {mlabel(ago)} להשוואה שנתית."

    # ── range position (active reps) ──
    rng = []
    for k in rep_active:
        vs = series[k]["vals"]
        lo_m = sorted(vs, key=lambda m: (vs[m], m))[0]
        hi_m = sorted(vs, key=lambda m: (-vs[m], m))[0]
        lo, hi, cur = vs[lo_m], vs[hi_m], vs[latest]
        posv = (cur - lo) / (hi - lo) if hi > lo else 0.5
        rng.append({"label": flabel(k), "unit": UNIT_SHORT.get(k[1], k[1]), "pos": posv,
                    "lo": lo, "lo_m": lo_m, "hi": hi, "hi_m": hi_m, "cur": cur})
    rng.sort(key=lambda r: (-r["pos"], r["label"]))
    range_chart = {"names": [r["label"] for r in reversed(rng)],
                   "values": [round(r["pos"] * 100, 1) for r in reversed(rng)]}
    range_table = [{"label": r["label"], "unit": r["unit"], "lo": fmt_price(r["lo"]), "lo_m": mshort(r["lo_m"]),
                    "hi": fmt_price(r["hi"]), "hi_m": mshort(r["hi_m"]), "cur": fmt_price(r["cur"]),
                    "pos": f"{r['pos'] * 100:.0f}%"} for r in rng]
    range_lede = (f"0% = המחיר הנמוך ביותר מאז {mlabel(first)}, 100% = הגבוה ביותר. "
                  "הערך מראה היכן נמצא מחיר החודש האחרון בטווח ההיסטורי של כל מוצר.")

    # ── month-over-month heatmap (reps alive in the window) ──
    hm = months[-(HEAT_MONTHS + 1):]
    heat_keys = rep_active if len(hm) > 1 else []
    cells, hmax = [], 0.0
    for yi, k in enumerate(heat_keys):
        for xi, (a, b) in enumerate(zip(hm, hm[1:])):
            c = pct(val(k, b), val(k, a))
            if c is not None:
                cells.append([xi, yi, round(c, 1)])
                hmax = max(hmax, abs(c))
    heat = {"x": [mshort(m) for m in hm[1:]], "y": [flabel(k) for k in heat_keys],
            "cells": cells, "max": round(max(hmax, 1.0), 1)}

    # ── top monthly moves (all reps, all history) ──
    moves = []
    for k in rep_keys:
        for a, b in zip(months, months[1:]):
            c = pct(val(k, b), val(k, a))
            if c is not None:
                moves.append((abs(c), c, flabel(k), b))
    moves.sort(key=lambda t: (-t[0], t[2], t[3]))
    top = moves[:TOP_MOVES]
    moves_chart = {"names": [f"{t[2]}, {mshort(t[3])}" for t in reversed(top)],
                   "values": [round(t[1], 1) for t in reversed(top)]}
    moves_table = [{"label": t[2], "month": mlabel(t[3]), "chg": fmt_signed(t[1])} for t in top]

    # ── diesel − gasoline spread ──
    def find_rep(prefix, unit="קילו ליטר"):
        for k in rep_keys:
            if series[k]["family"].startswith(prefix) and k[1] == unit:
                return k
        return None
    k_dsl = find_rep("סולר לתחבורה")
    k_gas = find_rep("בנזין")
    spread = None
    if k_dsl and k_gas:
        sm = [m for m in months if val(k_dsl, m) is not None and val(k_gas, m) is not None]
        if len(sm) >= 12:
            vals = [val(k_dsl, m) - val(k_gas, m) for m in sm]
            hi_i = sorted(range(len(sm)), key=lambda i: (-vals[i], sm[i]))[0]
            last12 = vals[-12:]
            spread = {"x": [mshort(m) for m in sm], "y": [r2(v) for v in vals],
                      "dsl": flabel(k_dsl), "gas": flabel(k_gas),
                      "avg_all": sum(vals) / len(vals), "avg12": sum(last12) / len(last12),
                      "hi": vals[hi_i], "hi_m": sm[hi_i], "last": vals[-1], "last_m": sm[-1],
                      "neg": sum(1 for v in vals if v < 0), "n": len(vals)}
            spread["lede"] = (f"סולר לתחבורה פחות בנזין 95, ש״ח לקו״ל. ב{mlabel(spread['last_m'])} הפער "
                              f"{fmt_signed(spread['last'], 0, '')} ש״ח; השיא {fmt_price(spread['hi'])} ש״ח ב{mlabel(spread['hi_m'])}. "
                              f"ממוצע כל התקופה: {fmt_signed(spread['avg_all'], 0, '')} ש״ח.")
            spread["aria"] = (f"גרף קווים: הפער בין מחיר הסולר לתחבורה למחיר הבנזין, שיא של {fmt_price(spread['hi'])} "
                              f"ש״ח לקו״ל ב{mlabel(spread['hi_m'])}.")

    # ── by-quote premium (pairs that differ only by "by quote") ──
    quote_series, prem12 = [], []
    for k in keys:
        if QUOTE not in k[0] or series[k]["adjust"]:
            continue
        base_name = _norm_space(k[0].replace(QUOTE, " "))
        bk = (base_name, k[1])
        if bk not in series:
            continue
        cm = [m for m in months if val(k, m) is not None and val(bk, m) is not None]
        if not cm:
            continue
        quote_series.append({"name": series[bk]["label"],
                             "data": [r2(val(k, m) - val(bk, m)) if m in cm else None for m in months]})
        for m in cm[-12:]:
            prem12.append(pct(val(k, m), val(bk, m)))
    quote = None
    if quote_series:
        avgp = sum(prem12) / len(prem12)
        quote = {"x": [mshort(m) for m in months], "series": quote_series, "avg12": avgp,
                 "lede": (f"ההפרש בין המחיר לפי ציטוט קרוסין CIF לבין המחיר המחושב (FOB בתוספת הפרש הסולר). "
                          f"ב-12 החודשים האחרונים של כל סדרה, המחיר לפי ציטוט גבוה בממוצע ב-{avgp:.1f}%."),
                 "aria": f"גרף קווים: הפרש מחיר הקרוסין לפי ציטוט על פני המחיר המחושב, {len(quote_series)} סדרות."}

    # ── sulfur adjustment (fuel oil) ──
    adj_keys = [k for k in keys if series[k]["adjust"]]
    sulfur = None
    if adj_keys:
        am = sorted({m for k in adj_keys for m in series[k]["vals"]})
        sers = [{"name": series[k]["label"], "data": [r2(val(k, m)) for m in am]} for k in adj_keys]
        lastv = [(series[k]["last"], val(k, series[k]["last"])) for k in adj_keys]
        lm = max(t[0] for t in lastv)
        allv = [v for k in adj_keys for v in series[k]["vals"].values()]
        sulfur = {"x": [mshort(m) for m in am], "series": sers,
                  "lede": (f"תוספת או הפחתה במחיר המזוט, בש״ח לטון, על כל 0.1% שינוי בתכולת הגופרית ביחס למזוט התקני. "
                           f"הטווח: {fmt_price(min(allv))} עד {fmt_price(max(allv))} ש״ח."
                           + (f" הפרסום הופסק אחרי {mlabel(lm)}." if lm < latest else "")),
                  "aria": f"גרף קווים: תוספת והפחתה במחיר המזוט לפי תכולת גופרית, {mlabel(am[0])} עד {mlabel(am[-1])}."}

    # ── discontinued series ──
    stopped = [k for k in keys if series[k]["last"] < latest]
    stopped_fams = sorted({(series[k]["family"], series[k]["last"]) for k in stopped},
                          key=lambda t: (t[1], t[0]))

    # ── KPIs ──
    kpis = {}
    labels = {}
    main_k = k_dsl if k_dsl in rep_active else (rep_active[0] if rep_active else None)
    gas_k = k_gas if k_gas in rep_active else None
    if main_k:
        v = val(main_k, latest)
        kpis["main"] = {"value": round(v, 2), "display": fmt_price(v), "tone": "brand"}
        labels["main_kpi"] = f"{flabel(main_k)}, ש״ח {UNIT_SHORT.get(main_k[1], main_k[1])} ({mshort(latest)})"
        c = pct(v, val(main_k, ago))
        if c is not None:
            tone = "danger" if c >= 10 else "warn" if c >= TREND_PCT else "ok" if c <= -TREND_PCT else "brand"
            kpis["main_yoy"] = {"value": round(c, 1), "display": fmt_signed(c), "tone": tone}
            labels["main_yoy_kpi"] = f"שינוי ב{flabel(main_k)} לעומת {mshort(ago)}"
    if gas_k:
        v = val(gas_k, latest)
        kpis["gas"] = {"value": round(v, 2), "display": fmt_price(v), "tone": "brand"}
        labels["gas_kpi"] = f"{flabel(gas_k)}, ש״ח לקו״ל ({mshort(latest)})"
    kpis["active"] = {"value": len(active), "display": f"{len(active):,}", "tone": "brand"}
    labels["active_kpi"] = f"סדרות מחיר שפורסמו ב{mshort(latest)} (מתוך {len(keys)} במאגר)"
    kpis["months"] = {"value": len(months), "display": f"{len(months):,}", "tone": "info"}
    labels["months_kpi"] = f"חודשי מחירים, {mshort(first)} עד {mshort(latest)}"
    if rng:
        top_r = rng[0]
        tone = "danger" if top_r["pos"] >= NEAR_PEAK else "brand"
        kpis["range"] = {"value": round(top_r["pos"] * 100, 1), "display": f"{top_r['pos'] * 100:.0f}%", "tone": tone}
        labels["range_kpi"] = f"מיקום {top_r['label']} בטווח ההיסטורי (100% = שיא)"

    # ── insights ──
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_main():
        if not main_k or "main_yoy" not in kpis:
            return None
        c = kpis["main_yoy"]["value"]
        v, p = val(main_k, latest), val(main_k, ago)
        if abs(c) < TREND_PCT:
            return (f"המחיר התיאורטי של {flabel(main_k)} יציב יחסית: {fmt_price(v)} ש״ח {UNIT_SHORT.get(main_k[1], main_k[1])} "
                    f"ב{mlabel(latest)}, לעומת {fmt_price(p)} ש״ח שנה קודם ({fmt_signed(c)}).")
        word = "עלה" if c > 0 else "ירד"
        return (f"המחיר התיאורטי של {flabel(main_k)} {word} ב-{abs(c):.1f}% בתוך שנה: מ-{fmt_price(p)} ש״ח "
                f"{UNIT_SHORT.get(main_k[1], main_k[1])} ב{mlabel(ago)} ל-{fmt_price(v)} ש״ח ב{mlabel(latest)}.")

    def ins_breadth():
        if len(with_chg) < 3:
            return None
        lead = with_chg[0]
        if ups >= len(with_chg) * 0.75 and lead["chg"] >= TREND_PCT:
            return (f"העלייה רוחבית: {ups} מתוך {len(with_chg)} סדרות המחיר שפורסמו ב{mlabel(latest)} גבוהות ביותר מ-{TREND_PCT:.0f}% "
                    f"משנה קודם. העלייה החדה ביותר: {lead['label']} ({fmt_signed(lead['chg'])}).")
        low = with_chg[-1]
        if downs >= len(with_chg) * 0.75 and low["chg"] <= -TREND_PCT:
            return (f"הירידה רוחבית: {downs} מתוך {len(with_chg)} סדרות המחיר שפורסמו ב{mlabel(latest)} נמוכות ביותר מ-{TREND_PCT:.0f}% "
                    f"משנה קודם. הירידה החדה ביותר: {low['label']} ({fmt_signed(low['chg'])}).")
        if lead["chg"] >= TREND_PCT and low["chg"] <= -TREND_PCT:
            return (f"התמונה מעורבת: {lead['label']} עלה ב-{lead['chg']:.1f}% בשנה האחרונה, בעוד "
                    f"{low['label']} ירד ב-{abs(low['chg']):.1f}%.")
        return None

    def ins_range():
        if not rng:
            return None
        hi_r = [r for r in rng if r["pos"] >= NEAR_PEAK]
        if hi_r:
            r = hi_r[0]
            extra = f" ועוד {len(hi_r) - 1} מוצרים קרובים לשיאם" if len(hi_r) > 1 else ""
            return (f"{r['label']} קרוב לשיא: {fmt_price(r['cur'])} ש״ח {r['unit']} ב{mlabel(latest)}, "
                    f"{r['pos'] * 100:.0f}% מהטווח שבין השפל ({fmt_price(r['lo'])}, {mlabel(r['lo_m'])}) "
                    f"לשיא ({fmt_price(r['hi'])}, {mlabel(r['hi_m'])}){extra}.")
        lo_r = [r for r in rng if r["pos"] <= NEAR_LOW]
        if lo_r:
            r = lo_r[-1]
            return (f"{r['label']} קרוב לשפל: {fmt_price(r['cur'])} ש״ח {r['unit']} ב{mlabel(latest)}, "
                    f"{r['pos'] * 100:.0f}% מהטווח שבין השפל ({mlabel(r['lo_m'])}) לשיא ({fmt_price(r['hi'])}, {mlabel(r['hi_m'])}).")
        return None

    def ins_swing():
        k = k_gas or (rep_keys[0] if rep_keys else None)
        if not k:
            return None
        vs = series[k]["vals"]
        lo_m = sorted(vs, key=lambda m: (vs[m], m))[0]
        hi_m = sorted(vs, key=lambda m: (-vs[m], m))[0]
        if vs[lo_m] <= 0 or vs[hi_m] / vs[lo_m] < 1.5:
            return None
        order = "ועלה עד" if lo_m < hi_m else "אחרי שיא של"
        if lo_m < hi_m:
            return (f"התנודתיות קיצונית: {flabel(k)} צנח ל-{fmt_price(vs[lo_m])} ש״ח {UNIT_SHORT.get(k[1], k[1])} ב{mlabel(lo_m)} "
                    f"{order} {fmt_price(vs[hi_m])} ש״ח ב{mlabel(hi_m)}, פי {vs[hi_m] / vs[lo_m]:.1f}.")
        return (f"התנודתיות קיצונית: {flabel(k)} הגיע ל-{fmt_price(vs[hi_m])} ש״ח {UNIT_SHORT.get(k[1], k[1])} ב{mlabel(hi_m)} "
                f"וצנח ל-{fmt_price(vs[lo_m])} ש״ח ב{mlabel(lo_m)}, פי {vs[hi_m] / vs[lo_m]:.1f} בין השפל לשיא.")

    def ins_spread():
        if not spread:
            return None
        a12, aa = spread["avg12"], spread["avg_all"]
        if abs(a12) < 1:
            return None
        who = "יקר" if a12 > 0 else "זול"
        return (f"סולר לתחבורה {who} מבנזין 95: בממוצע ב-12 החודשים האחרונים הפער {fmt_price(abs(a12))} ש״ח לקו״ל "
                f"(ממוצע כל התקופה {fmt_signed(aa, 0, '')} ש״ח). הפער הגדול ביותר נרשם ב{mlabel(spread['hi_m'])}: {fmt_price(spread['hi'])} ש״ח.")

    def ins_move():
        if not top:
            return None
        t = top[0]
        if t[0] < 10:
            return None
        word = "זינוק" if t[1] > 0 else "צניחה"
        return f"התנודה החודשית החריפה ביותר: {word} של {abs(t[1]):.1f}% ב{t[2]} ב{mlabel(t[3])} לעומת החודש הקודם."

    def ins_stopped():
        if not stopped_fams:
            return None
        fam_names = []
        for f, _ in stopped_fams:
            if f not in fam_names:
                fam_names.append(f)
        mazut = [f for f in fam_names if f.startswith("מזוט")]
        other = [f for f in fam_names if not f.startswith("מזוט") and not is_adjust(f)]
        parts = []
        if mazut:
            lm = max(t[1] for t in stopped_fams if t[0].startswith("מזוט"))
            parts.append(f"{len(mazut)} סוגי מזוט (עד {mlabel(lm)})")
        for f in other[:3]:
            lm = max(t[1] for t in stopped_fams if t[0] == f)
            parts.append(f"{f} (עד {mlabel(lm)})")
        if not parts:
            return None
        head = ("סדרת מחיר אחת אינה מתפרסמת עוד: " if len(stopped) == 1
                else f"{len(stopped)} סדרות מחיר אינן מתפרסמות עוד, בהן ")
        return head + ", ".join(parts) + f". ב{mlabel(latest)} פורסמו {len(active)} סדרות."

    def ins_quote():
        if not quote:
            return None
        a = quote["avg12"]
        if abs(a) < 0.3:
            return None
        word = "גבוה" if a > 0 else "נמוך"
        return (f"לקרוסין (דלק סילוני) מתפרסמים שני מחירים: המחיר לפי ציטוט {word} בממוצע ב-{abs(a):.1f}% "
                f"מהמחיר המחושב, ב-12 החודשים האחרונים של כל סדרה.")

    add("main_yoy", ins_main())
    add("breadth", ins_breadth())
    add("range", ins_range())
    add("swing", ins_swing())
    add("spread", ins_spread())
    add("move", ins_move())
    add("stopped", ins_stopped())
    add("quote", ins_quote())

    # ── summary ──
    summary = "מחירים תיאורטיים מרביים בשער בית הזיקוק לבנזין 95, סולר, קרוסין ונפטא, לפי חודש."
    if main_k:
        extra = f" ב{mlabel(latest)}: {flabel(main_k)} {fmt_price(val(main_k, latest))} ש״ח {UNIT_SHORT.get(main_k[1], main_k[1])}"
        if "main_yoy" in kpis:
            extra += f" ({fmt_signed(kpis['main_yoy']['value'])} בשנה)"
        extra += "."
        if len(summary + extra) <= SUMMARY_MAX:
            summary += extra
    summary = summary[:SUMMARY_MAX]

    labels.update({
        "index_lede": idx_lede,
        "index_aria": f"גרף קווים: ממוצע שנתי של {len(rep_keys)} מוצרים כמדד (השנה הראשונה = 100), {years[0]} עד {years[-1]}.",
        "years_caption": f"ממוצע שנתי של המחיר התיאורטי, ש״ח, {tyears[0]} עד {tyears[-1]}",
        "yoy_lede": yoy_lede,
        "yoy_aria": (f"גרף עמודות: שינוי במחיר של {len(shown_chg)} סדרות בין {mlabel(ago)} ל{mlabel(latest)}"
                     + (f", העלייה הגדולה ביותר ב{with_chg[0]['label']} ({fmt_signed(with_chg[0]['chg'])})." if with_chg else ".")),
        "yoy_head_prev": f"מחיר {mshort(ago)}",
        "yoy_head_cur": f"מחיר {mshort(latest)}",
        "range_lede": range_lede,
        "range_aria": (f"גרף עמודות: מיקום המחיר האחרון בטווח ההיסטורי של {len(rng)} מוצרים"
                       + (f", הגבוה ביותר {rng[0]['label']} ב-{rng[0]['pos'] * 100:.0f}%." if rng else ".")),
        "heat_lede": (f"שינוי חודשי באחוזים, {len(heat['x'])} החודשים האחרונים, סדרה מייצגת לכל מוצר. "
                      "אדום: התייקרות, כחול: הוזלה."),
        "heat_aria": f"מפת חום: שינוי חודשי במחיר של {len(heat['y'])} מוצרים ב-{len(heat['x'])} החודשים האחרונים.",
        "moves_lede": (f"{len(top)} השינויים החודשיים החדים ביותר מאז {mlabel(first)}, בסדרה המייצגת של כל מוצר."
                       if top else ""),
        "moves_aria": (f"גרף עמודות: {len(top)} השינויים החודשיים החדים ביותר, בראשם {top[0][2]} ב{mlabel(top[0][3])} ({fmt_signed(top[0][1])})."
                       if top else "גרף עמודות: השינויים החודשיים החדים ביותר."),
        "notes": ("המחיר המירבי אותו ניתן לגבות במכירת גפ\"מ הינו מחיר הייבוא בהתאם לצו פיקוח על מחירי מצרכים ושירותים "
                  "(מחיר מירבי לגפ\"מ בשער בית זיקוק)(תיקון), התשס\"ח-2008.\n"
                  "החל מחודש אוקטובר 2012, מפורסם באתר הפלאט'ס מחיר קרוסין ע\"ב CIF. לפיכך מפורסמים 2 מחירים:\n"
                  "1. מחיר קרוסין ע\"ב FOB בתוספת הפרש מחיר סולר תחבורה FOB / CIF.\n"
                  "2. מחיר ע\"פ ציטוט."),
        "dropped": " ".join(t for t in [
            f"{n_bad} שורות ללא תאריך או מחיר תקינים לא נכללו." if n_bad else "",
            (f"נתוני {mlabel(partial)} חלקיים ({per_month[partial]} סדרות בלבד) ולכן לא נכללו עד להשלמתם."
             if partial else ""),
        ] if t),
    })

    temporal = f"{first[:4]}/{latest[:4]}"
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["מחירי דלק", "אנרגיה", "בנזין", "סולר", "מחירים תיאורטיים"],
            "related_ids": ["4dd3bb28-a4ef-4ab5-bb57-fd0bd0b79f8f", "b2f22645-5068-487b-82d3-78e3490ef49d",
                            "09f0e9ee-5cef-48f7-84f6-10235e6dd9ed"],
            "temporal_coverage": temporal,
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "units": unit_charts,
            "index": {"x": ylabels, "series": idx_series, "selected": idx_selected},
            "yoy": yoy_chart,
            "range": range_chart,
            "heat": heat,
            "moves": moves_chart,
            "spread": {"x": spread["x"], "y": spread["y"]} if spread else None,
            "quote": {"x": quote["x"], "series": quote["series"]} if quote else None,
            "sulfur": {"x": sulfur["x"], "series": sulfur["series"]} if sulfur else None,
        },
        "tables": {
            "years_cols": table_cols,
            "years": yrows,
            "yoy": yoy_table,
            "range": range_table,
            "moves": moves_table,
        },
        "sections": {
            "spread": {"lede": spread["lede"], "aria": spread["aria"]} if spread else None,
            "quote": {"lede": quote["lede"], "aria": quote["aria"]} if quote else None,
            "sulfur": {"lede": sulfur["lede"], "aria": sulfur["aria"]} if sulfur else None,
        },
        "labels": labels,
        "insights": insights,
    }
