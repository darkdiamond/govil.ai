"""מחירים מחושבים לפי צו הפיקוח (מחירים מרביים למוצרי נפט בשער בית זיקוק).

Ministry of Energy. One long table: one row per (month, product, unit) with
the price the ministry computes each month under the price-control order as
amended on 1.4.2025 (from 1.4.2028 the series is to be renamed "theoretical
prices"). Prices are NIS per kilolitre or per metric ton, as the unit column
says. Kerosene is published in both units, and in four delivery variants
(pipeline / tanker, computed / "by quote").

A series is (product name, unit). A "family" is the product without its
delivery mode; each family gets one representative series (pipeline, not by
quote, kilolitre first, longest history) for the unit-free views (index,
range position, heatmap, top moves). Names are lightly normalised (footnote
marks, "במיכליות" → "במכלית") so a relabelled series continues; an unknown new
product flows through as its own series and family.

"Latest" is the latest month in the data, never the wall clock. Months are
keyed YYYY-MM (some months are dated the 2nd or 3rd).
"""
import itertools
import re

import pandas as pd
from govlib import fmt

MINUS = fmt.MINUS
MONTHS_HE = fmt.MONTHS_HE

UNIT_ORDER = ["קילו ליטר", "טון מטרי"]
UNIT_SHORT = {"קילו ליטר": "לקו״ל", "טון מטרי": "לטון"}
UNIT_TITLE = {"קילו ליטר": "מוצרים המתומחרים לקילו-ליטר",
              "טון מטרי": "מוצרים המתומחרים לטון מטרי"}
FAMILY_SHORT = {"בנזין 95 אוקטן נטול עופרת": "בנזין 95"}

PIPE, TANK, QUOTE = "בהזרמה", "במכלית", 'ע"פ ציטוט'
KL = "קילו ליטר"

MAX_MONTHS_MONTHLY = 240   # beyond this the line charts switch to quarterly means
HEAT_MONTHS = 24
TREND_PCT = 3.0            # |change| below this reads as "stable" (year over year)
MOM_PCT = 1.0              # |change| below this reads as "stable" (month over month)
BIG_MOVE = 10.0            # a monthly move at/above this is worth an insight
NEAR_PEAK = 0.85
NEAR_LOW = 0.15
FIXED_SPREAD_PP = 0.05     # a ratio that moves less than this (pp) is "fixed"
TOP_MOVES = 10
MAX_LATEST = 20
MAX_UNITS = 4
SUMMARY_MAX = 155
PARTIAL_SHARE = 0.5

NOTES = ("מחירים מחושבים: מחירים לפי שיטת החישוב שנקבעה בצו כנוסחו לאחר התיקון מיום 1.4.25. "
         "החל מיום 1.4.28 ייקראו בשם \"מחירים תיאורטיים\".")


# ── helpers ──────────────────────────────────────────────────────────────

def _norm_space(s):
    return re.sub(r"\s+", " ", s).strip()


def canon(name):
    s = name.replace("״", '"').replace("׳", "'")
    s = re.sub(r"\(\*+\)\d*", " ", s)
    s = s.replace("במיכליות", TANK)
    return _norm_space(s)


def family_of(c):
    s = c.replace(QUOTE, " ").replace(PIPE, " ").replace(TANK, " ")
    return _norm_space(s)


def fshort(fam):
    return FAMILY_SHORT.get(fam, fam)


def mlabel(m):
    y, mo = m.split("-")
    return f"{MONTHS_HE[int(mo) - 1]} {y}"


def mshort(m):
    y, mo = m.split("-")
    return f"{mo}/{y}"


def month_shift(m, d):
    y, mo = int(m[:4]), int(m[5:7])
    t = y * 12 + (mo - 1) + d
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def month_pairs(months):
    """Consecutive calendar-month pairs only: a gap in the upload is not a monthly move."""
    return [(a, b) for a, b in itertools.pairwise(months) if month_shift(a, 1) == b]


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
    df = df[df["date"].notna() & df["price"].notna() & (df["price"] > 0)
            & (df["name"] != "") & (df["unit"] != "")].copy()
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
    latest, first = months[-1], months[0]
    prev = months[-2] if len(months) > 1 else None
    ago = month_shift(latest, -12)

    # ── series ──
    units_seen = sorted(df["unit"].unique().tolist(),
                        key=lambda u: (UNIT_ORDER.index(u) if u in UNIT_ORDER else 99, u))
    units_per_name = df.groupby("name")["unit"].nunique().to_dict()
    series = {}
    for (name, unit), g in df.groupby(["name", "unit"], sort=True):
        vals = dict(zip(g["month"], g["price"].astype(float)))
        label = name
        if units_per_name.get(name, 1) > 1:
            label = f"{name} ({UNIT_SHORT.get(unit, unit)})"
        ms = sorted(vals)
        series[(name, unit)] = {"name": name, "unit": unit, "label": label, "family": family_of(name),
                                "vals": vals, "first": ms[0], "last": ms[-1], "n": len(ms)}
    keys = sorted(series, key=lambda k: (units_seen.index(k[1]), k[0]))
    active = [k for k in keys if series[k]["last"] == latest]

    def val(k, m):
        return series[k]["vals"].get(m) if k else None

    # family representatives
    by_fam = {}
    for k in keys:
        by_fam.setdefault(series[k]["family"], []).append(k)
    reps = {}
    for fam, ks in by_fam.items():
        reps[fam] = min(ks, key=lambda k: (QUOTE in k[0], PIPE not in k[0], units_seen.index(k[1]),
                                              -series[k]["n"], k[0]))
    rep_keys = sorted(reps.values(), key=lambda k: (units_seen.index(k[1]), series[k]["family"]))
    rep_active = [k for k in rep_keys if series[k]["last"] == latest]

    def flabel(k):
        return fshort(series[k]["family"])

    def ushort(k):
        return UNIT_SHORT.get(k[1], k[1])

    def find_rep(prefix):
        for k in rep_keys:
            if series[k]["family"].startswith(prefix) and k[1] == KL:
                return k
        return None

    k_dsl = find_rep("סולר לתחבורה")
    k_gas = find_rep("בנזין")
    k_heat = find_rep("סולר להסקה")

    # ── per-unit line charts ──
    quarterly = len(months) > MAX_MONTHS_MONTHLY

    def qkey(m):
        return f"{m[:4]}-Q{(int(m[5:7]) - 1) // 3 + 1}"

    axis = sorted({qkey(m) for m in months}) if quarterly else months
    xlabels = axis if quarterly else [mshort(m) for m in axis]

    def series_on_axis(vals):
        if not quarterly:
            return [r2(vals.get(m)) for m in axis]
        buckets = {}
        for m, v in vals.items():
            buckets.setdefault(qkey(m), []).append(v)
        return [r2(sum(buckets[a]) / len(buckets[a])) if a in buckets else None for a in axis]

    unit_charts = []
    for u in units_seen[:MAX_UNITS]:
        ks = [k for k in keys if k[1] == u]
        sers, selected = [], {}
        for k in ks:
            sers.append({"name": series[k]["label"], "data": series_on_axis(series[k]["vals"])})
            selected[series[k]["label"]] = (k in reps.values()) or not any(k2 in reps.values() for k2 in ks)
        last_vals = sorted([(val(k, latest), series[k]["label"]) for k in ks if val(k, latest) is not None],
                           key=lambda t: (-t[0], t[1]))
        if last_vals:
            hi, lo = last_vals[0], last_vals[-1]
            lede = (f"{len(ks)} סדרות מחיר ביחידה זו. ב{mlabel(latest)} היקרה ביותר: {hi[1]}, "
                    f"{fmt_price(hi[0])} ש״ח {UNIT_SHORT.get(u, u)}")
            if len(last_vals) > 1:
                lede += f"; הזולה ביותר: {lo[1]}, {fmt_price(lo[0])} ש״ח."
            else:
                lede += "."
        else:
            lede = f"{len(ks)} סדרות מחיר ביחידה זו; אף אחת מהן אינה מתפרסמת ב{mlabel(latest)}."
        if len(ks) > len([k for k in ks if k in reps.values()]):
            lede += " בתחילה מוצגת סדרה אחת לכל מוצר; שאר הסדרות זמינות דרך המקרא."
        if quarterly:
            lede += " הסדרה מוצגת כממוצע רבעוני."
        unit_charts.append({
            "title": UNIT_TITLE.get(u, f"מוצרים ביחידת {u}"),
            "ytitle": f"ש״ח {UNIT_SHORT.get(u, u)}",
            "x": xlabels, "series": sers, "selected": selected, "lede": lede,
            "aria": (f"גרף קווים: מחיר מחושב חודשי של {len(ks)} סדרות, {UNIT_TITLE.get(u, u)}, "
                     f"{mlabel(first)} עד {mlabel(latest)}."),
        })

    # ── index: first month = 100 (family reps) ──
    idx_series, since = [], []
    for k in rep_keys:
        vs = series[k]["vals"]
        base_m = series[k]["first"]
        base = vs[base_m]
        data = series_on_axis({m: v / base * 100 for m, v in vs.items()})
        idx_series.append({"name": flabel(k), "data": data})
        if series[k]["last"] == latest:
            since.append((pct(vs[latest], base), flabel(k), base_m))
    since.sort(key=lambda t: (-t[0], t[1]))
    idx_lede = ("כל מוצר מוצג ביחס למחירו בחודש הראשון שבו פורסם (=100), כך שאפשר להשוות מוצרים "
                "ביחידות שונות.")
    if len(since) >= 2:
        hi_s, lo_s = since[0], since[-1]
        since_w = f"מאז {mlabel(first)}" if all(t[2] == first for t in since) else "מאז תחילת הפרסום"
        idx_lede += (f" {since_w} התייקר הכי הרבה {hi_s[1]} ({fmt_signed(hi_s[0])}), "
                     f"והכי מעט {lo_s[1]} ({fmt_signed(lo_s[0])}).")

    # ── latest month: vs previous month and vs a year ago (all active series) ──
    lat_rows = []
    for k in active:
        v = val(k, latest)
        lat_rows.append({"label": series[k]["label"], "unit": ushort(k), "price": v,
                         "prev": val(k, prev) if prev else None, "ago": val(k, ago),
                         "mom": pct(v, val(k, prev)) if prev else None, "yoy": pct(v, val(k, ago))})
    lat_rows.sort(key=lambda r: (r["yoy"] is None,
                                 -(r["yoy"] if r["yoy"] is not None else
                                   (r["mom"] if r["mom"] is not None else -1e9)), r["label"]))
    with_yoy = [r for r in lat_rows if r["yoy"] is not None]
    with_mom = [r for r in lat_rows if r["mom"] is not None]
    shown = lat_rows[:MAX_LATEST]
    has_yoy = any(r["yoy"] is not None for r in shown)
    has_mom = any(r["mom"] is not None for r in shown)
    change_chart = {
        "names": [r["label"] for r in reversed(shown)],
        "mom": [r2(r["mom"]) if r["mom"] is not None else None for r in reversed(shown)] if has_mom else None,
        "yoy": [r2(r["yoy"]) if r["yoy"] is not None else None for r in reversed(shown)] if has_yoy else None,
        "mom_name": f"לעומת {mshort(prev)}" if prev else "",
        "yoy_name": f"לעומת {mshort(ago)}",
    }
    change_table = [{"label": r["label"], "unit": r["unit"], "price": fmt_price(r["price"]),
                     "mom": fmt_signed(r["mom"]) if r["mom"] is not None else "",
                     "yoy": fmt_signed(r["yoy"]) if r["yoy"] is not None else ""} for r in shown]
    ups = sum(1 for r in with_yoy if r["yoy"] >= TREND_PCT)
    downs = sum(1 for r in with_yoy if r["yoy"] <= -TREND_PCT)
    m_ups = sum(1 for r in with_mom if r["mom"] >= MOM_PCT)
    m_downs = sum(1 for r in with_mom if r["mom"] <= -MOM_PCT)
    parts = []
    if with_mom:
        parts.append(f"לעומת {mlabel(prev)}: {m_ups} סדרות התייקרו ביותר מ-{MOM_PCT:.0f}% "
                     f"ו-{m_downs} הוזלו ביותר מ-{MOM_PCT:.0f}%.")
    if with_yoy:
        parts.append(f"לעומת {mlabel(ago)}: {ups} התייקרו ביותר מ-{TREND_PCT:.0f}% "
                     f"ו-{downs} הוזלו ביותר מ-{TREND_PCT:.0f}%.")
    else:
        parts.append(f"אין עדיין נתון של {mlabel(ago)} להשוואה שנתית.")
    change_lede = f"מחיר {mlabel(latest)} ב-{len(lat_rows)} סדרות המחיר שפורסמו בו. " + " ".join(parts)

    # ── range position (active reps) ──
    rng = []
    for k in rep_active:
        vs = series[k]["vals"]
        if len(vs) < 2:
            continue
        lo_m = min(vs, key=lambda m: (vs[m], m))
        hi_m = min(vs, key=lambda m: (-vs[m], m))
        lo, hi, cur = vs[lo_m], vs[hi_m], vs[latest]
        posv = (cur - lo) / (hi - lo) if hi > lo else 0.5
        rng.append({"label": flabel(k), "unit": ushort(k), "pos": posv,
                    "lo": lo, "lo_m": lo_m, "hi": hi, "hi_m": hi_m, "cur": cur})
    rng.sort(key=lambda r: (-r["pos"], r["label"]))
    range_chart = {"names": [r["label"] for r in reversed(rng)],
                   "values": [round(r["pos"] * 100, 1) for r in reversed(rng)]}
    range_table = [{"label": r["label"], "unit": r["unit"], "lo": fmt_price(r["lo"]), "lo_m": mshort(r["lo_m"]),
                    "hi": fmt_price(r["hi"]), "hi_m": mshort(r["hi_m"]), "cur": fmt_price(r["cur"]),
                    "pos": f"{r['pos'] * 100:.0f}%"} for r in rng]
    at_peak = [r for r in rng if r["cur"] >= r["hi"]]
    full_hist = all(series[k]["first"] == first for k in rep_active)
    range_lede = (f"0% = המחיר הנמוך ביותר {f'מאז {mlabel(first)}' if full_hist else 'מאז תחילת הפרסום'}, "
                  f"100% = הגבוה ביותר. "
                  f"הערך מראה היכן נמצא מחיר {mlabel(latest)} בטווח של כל מוצר.")
    if at_peak:
        range_lede += f" {len(at_peak)} מתוך {len(rng)} המוצרים נמצאים החודש בשיא התקופה."

    # ── month-over-month heatmap (reps alive in the window) ──
    hm = months[-(HEAT_MONTHS + 1):]
    heat_keys = rep_active if len(hm) > 1 else []
    cells, hmax = [], 0.0
    for yi, k in enumerate(heat_keys):
        for xi, (a, b) in enumerate(itertools.pairwise(hm)):
            c = pct(val(k, b), val(k, a)) if month_shift(a, 1) == b else None
            if c is not None:
                cells.append([xi, yi, round(c, 1)])
                hmax = max(hmax, abs(c))
    heat = {"x": [mshort(m) for m in hm[1:]], "y": [flabel(k) for k in heat_keys],
            "cells": cells, "max": round(max(hmax, 1.0), 1)}
    up_cells = sum(1 for c in cells if c[2] > 0)

    # ── top monthly moves (reps, all history) ──
    moves = []
    for k in rep_keys:
        for a, b in month_pairs(months):
            c = pct(val(k, b), val(k, a))
            if c is not None:
                moves.append((abs(c), c, flabel(k), b))
    moves.sort(key=lambda t: (-t[0], t[2], t[3]))
    top = moves[:TOP_MOVES]
    moves_chart = {"names": [f"{t[2]}, {mshort(t[3])}" for t in reversed(top)],
                   "values": [round(t[1], 1) for t in reversed(top)]}
    moves_table = [{"label": t[2], "month": mlabel(t[3]), "chg": fmt_signed(t[1])} for t in top]
    # months where every rep moved the same way by at least BIG_MOVE
    shock = None
    for a, b in month_pairs(months):
        cs = [pct(val(k, b), val(k, a)) for k in rep_keys]
        cs = [c for c in cs if c is not None]
        if len(cs) >= 3 and (all(c >= BIG_MOVE for c in cs) or all(c <= -BIG_MOVE for c in cs)):
            avg = sum(cs) / len(cs)
            if shock is None or abs(avg) > abs(shock[1]):
                shock = (b, avg, min(cs), max(cs), len(cs))

    # ── diesel − gasoline spread ──
    spread = None
    if k_dsl and k_gas:
        sm = [m for m in months if val(k_dsl, m) is not None and val(k_gas, m) is not None]
        if len(sm) >= 3:
            vals = [val(k_dsl, m) - val(k_gas, m) for m in sm]
            hi_i = min(range(len(sm)), key=lambda i: (-vals[i], sm[i]))
            lo_i = min(range(len(sm)), key=lambda i: (vals[i], sm[i]))
            spread = {"x": [mshort(m) for m in sm], "y": [r2(v) for v in vals],
                      "first": vals[0], "first_m": sm[0], "last": vals[-1], "last_m": sm[-1],
                      "hi": vals[hi_i], "hi_m": sm[hi_i], "lo": vals[lo_i], "lo_m": sm[lo_i],
                      "avg": sum(vals) / len(vals)}
            mode = " (סדרות בהזרמה)" if PIPE in k_dsl[0] and PIPE in k_gas[0] else ""
            spread["lede"] = (f"מחיר הסולר לתחבורה פחות מחיר בנזין 95, ש״ח לקו״ל{mode}. "
                              f"ב{mlabel(spread['last_m'])} הפער {fmt_signed(spread['last'], 0, '')} ש״ח; "
                              f"הגבוה ביותר {fmt_signed(spread['hi'], 0, '')} ש״ח ב{mlabel(spread['hi_m'])}, "
                              f"הנמוך ביותר {fmt_signed(spread['lo'], 0, '')} ש״ח ב{mlabel(spread['lo_m'])}.")
            spread["aria"] = (f"גרף קווים: הפער בין מחיר הסולר לתחבורה למחיר בנזין 95, {mlabel(sm[0])} עד "
                              f"{mlabel(sm[-1])}, הגבוה ביותר {fmt_price(spread['hi'])} ש״ח לקו״ל ב{mlabel(spread['hi_m'])}.")

    # ── relations between series, in % (tanker vs pipeline, by quote, heating vs transport) ──
    rels = []

    def add_rel(kind, label, ka, kb, fam=None):
        cm = [m for m in months if val(ka, m) is not None and val(kb, m) is not None]
        if len(cm) < 2:
            return
        vs = [pct(val(ka, m), val(kb, m)) for m in cm]
        vm = dict(zip(cm, vs))
        rels.append({"kind": kind, "label": label, "fam": fam, "n": len(cm),
                     "data": [r2(vm.get(m)) for m in months],
                     "min": min(vs), "max": max(vs), "avg": sum(vs) / len(vs),
                     "last": vs[-1], "last_m": cm[-1]})

    for fam in sorted(by_fam):
        ks = [k for k in by_fam[fam] if k[1] == KL and QUOTE not in k[0]]
        kp = next((k for k in ks if PIPE in k[0]), None)
        kt = next((k for k in ks if TANK in k[0]), None)
        if kp and kt:
            add_rel("tank", f"{fshort(fam)}: במכלית מול בהזרמה", kt, kp, fam)
    for fam in sorted(by_fam):
        ks = [k for k in by_fam[fam] if k[1] == KL]
        kq = next((k for k in ks if QUOTE in k[0] and PIPE in k[0]), None)
        kb = next((k for k in ks if QUOTE not in k[0] and PIPE in k[0]), None)
        if kq and kb:
            add_rel("quote", f"{fshort(fam)}: לפי ציטוט מול מחושב", kq, kb, fam)
    if k_heat and k_dsl:
        add_rel("heat", "סולר להסקה מול סולר לתחבורה", k_heat, k_dsl)
    rel_chart = {"x": [mshort(m) for m in months],
                 "series": [{"name": r["label"], "data": r["data"]} for r in rels]} if rels else None
    rel_table = [{"label": r["label"], "min": fmt_signed(r["min"], 2), "avg": fmt_signed(r["avg"], 2),
                  "max": fmt_signed(r["max"], 2), "last": fmt_signed(r["last"], 2)} for r in rels]
    fixed = [r for r in rels if r["max"] - r["min"] < FIXED_SPREAD_PP]
    rel_lede = ("ההפרש באחוזים בין סדרות מחיר קרובות: מכלית מול הזרמה של אותו מוצר, מחיר לפי ציטוט מול "
                "המחיר המחושב, וסולר להסקה מול סולר לתחבורה. ערך שלילי: הסדרה הראשונה זולה יותר.")
    if fixed:
        rel_lede += f" {len(fixed)} מתוך {len(rels)} ההפרשים קבועים לאורך כל התקופה."

    # ── KPIs ──
    kpis, labels = {}, {}
    main_k = k_dsl if k_dsl in rep_active else (rep_active[0] if rep_active else None)
    gas_k = k_gas if (k_gas in rep_active and k_gas != main_k) else None
    if main_k:
        v = val(main_k, latest)
        kpis["main"] = {"value": round(v, 2), "display": fmt_price(v), "tone": "brand"}
        labels["main_kpi"] = f"{flabel(main_k)}, ש״ח {ushort(main_k)} ({mshort(latest)})"
        c = pct(v, val(main_k, ago))
        if c is not None:
            tone = "danger" if c >= 10 else "warn" if c >= TREND_PCT else "ok" if c <= -TREND_PCT else "brand"
            kpis["main_yoy"] = {"value": round(c, 1), "display": fmt_signed(c), "tone": tone}
            labels["main_yoy_kpi"] = f"שינוי ב{flabel(main_k)} לעומת {mshort(ago)}"
    if gas_k:
        v = val(gas_k, latest)
        kpis["gas"] = {"value": round(v, 2), "display": fmt_price(v), "tone": "brand"}
        labels["gas_kpi"] = f"{flabel(gas_k)}, ש״ח {ushort(gas_k)} ({mshort(latest)})"
        c = pct(v, val(gas_k, prev)) if prev else None
        if c is not None:
            tone = "danger" if c >= 5 else "warn" if c >= MOM_PCT else "ok" if c <= -MOM_PCT else "brand"
            kpis["gas_mom"] = {"value": round(c, 1), "display": fmt_signed(c), "tone": tone}
            labels["gas_mom_kpi"] = f"שינוי ב{flabel(gas_k)} לעומת {mshort(prev)}"
    if rng:
        top_r = rng[0]
        tone = "danger" if top_r["pos"] >= NEAR_PEAK else "brand"
        kpis["range"] = {"value": round(top_r["pos"] * 100, 1), "display": f"{top_r['pos'] * 100:.0f}%", "tone": tone}
        labels["range_kpi"] = f"מיקום {top_r['label']} בטווח {f'מאז {mshort(first)}' if full_hist else 'מאז תחילת הפרסום'} (100% = שיא)"
    kpis["months"] = {"value": len(months), "display": f"{len(months):,}", "tone": "info"}
    labels["months_kpi"] = f"חודשי מחירים, {mshort(first)} עד {mshort(latest)}, {len(active)} סדרות"

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
        u = ushort(main_k)
        if abs(c) < TREND_PCT:
            return (f"המחיר המחושב של {flabel(main_k)} יציב יחסית לפני שנה: {fmt_price(v)} ש״ח {u} "
                    f"ב{mlabel(latest)}, לעומת {fmt_price(p)} ש״ח ב{mlabel(ago)} ({fmt_signed(c)}).")
        word = "עלה" if c > 0 else "ירד"
        return (f"המחיר המחושב של {flabel(main_k)} {word} ב-{abs(c):.1f}% בתוך שנה: מ-{fmt_price(p)} ש״ח "
                f"{u} ב{mlabel(ago)} ל-{fmt_price(v)} ש״ח ב{mlabel(latest)}.")

    def ins_mom():
        if len(with_mom) < 3:
            return None
        lead, low = with_mom_sorted[0], with_mom_sorted[-1]
        if m_ups >= len(with_mom) * 0.75 and lead["mom"] >= MOM_PCT:
            return (f"ב{mlabel(latest)} התייקרו {m_ups} מתוך {len(with_mom)} סדרות המחיר ביותר מ-{MOM_PCT:.0f}% "
                    f"לעומת {mlabel(prev)}; החדה ביותר: {lead['label']} ({fmt_signed(lead['mom'])}).")
        if m_downs >= len(with_mom) * 0.75 and low["mom"] <= -MOM_PCT:
            return (f"ב{mlabel(latest)} הוזלו {m_downs} מתוך {len(with_mom)} סדרות המחיר ביותר מ-{MOM_PCT:.0f}% "
                    f"לעומת {mlabel(prev)}; החדה ביותר: {low['label']} ({fmt_signed(low['mom'])}).")
        if lead["mom"] >= MOM_PCT and low["mom"] <= -MOM_PCT:
            return (f"החודש האחרון מעורב: {lead['label']} התייקר ב-{lead['mom']:.1f}% לעומת {mlabel(prev)}, "
                    f"בעוד {low['label']} הוזל ב-{abs(low['mom']):.1f}%.")
        return None

    with_mom_sorted = sorted(with_mom, key=lambda r: (-r["mom"], r["label"]))

    def ins_range():
        if not rng:
            return None
        if at_peak:
            names = [r["label"] for r in at_peak]
            if len(names) == 1:
                r = at_peak[0]
                return (f"{r['label']} בשיא התקופה: {fmt_price(r['cur'])} ש״ח {r['unit']} ב{mlabel(latest)}, "
                        f"לעומת שפל של {fmt_price(r['lo'])} ש״ח ב{mlabel(r['lo_m'])}.")
            return (f"{len(names)} מוצרים בשיא המחיר מאז {mlabel(first)}: {fmt.join_he(names)}.")
        hi_r = [r for r in rng if r["pos"] >= NEAR_PEAK]
        if hi_r:
            r = hi_r[0]
            return (f"{r['label']} קרוב לשיא: {fmt_price(r['cur'])} ש״ח {r['unit']} ב{mlabel(latest)}, "
                    f"{r['pos'] * 100:.0f}% מהטווח שבין השפל ({fmt_price(r['lo'])}, {mlabel(r['lo_m'])}) "
                    f"לשיא ({fmt_price(r['hi'])}, {mlabel(r['hi_m'])}).")
        lo_r = [r for r in rng if r["pos"] <= NEAR_LOW]
        if lo_r:
            r = lo_r[-1]
            return (f"{r['label']} קרוב לשפל: {fmt_price(r['cur'])} ש״ח {r['unit']} ב{mlabel(latest)}, "
                    f"{r['pos'] * 100:.0f}% מהטווח שבין השפל ({mlabel(r['lo_m'])}) לשיא "
                    f"({fmt_price(r['hi'])}, {mlabel(r['hi_m'])}).")
        return None

    def ins_shock():
        if shock:
            m, avg, lo, hi, n = shock
            word = "זינקו" if avg > 0 else "צנחו"
            who = f"כל {n} המוצרים" if n == len(rep_keys) else f"{n} המוצרים שפורסמו בשני החודשים"
            return (f"ב{mlabel(m)} {word} מחירי {who} בבת אחת, ב-{min(abs(lo), abs(hi)):.0f}% עד "
                    f"{max(abs(lo), abs(hi)):.0f}% לעומת החודש הקודם (ממוצע {fmt_signed(avg)}).")
        if top and top[0][0] >= BIG_MOVE:
            t = top[0]
            word = "זינוק" if t[1] > 0 else "צניחה"
            return f"התנודה החודשית החריפה ביותר: {word} של {abs(t[1]):.1f}% ב{t[2]} ב{mlabel(t[3])} לעומת החודש הקודם."
        return None

    def ins_spread():
        if not spread:
            return None
        a, b = spread["first"], spread["last"]
        if abs(b) < 1:
            return None
        who = "יקר" if b > 0 else "זול"
        txt = (f"סולר לתחבורה {who} מבנזין 95 ב-{fmt.int_he(abs(b))} ש״ח לקו״ל ב{mlabel(spread['last_m'])}")
        if abs(b - a) >= 50 or a * b < 0:
            if a * b > 0:
                dirw = "התרחב" if abs(b) > abs(a) else "הצטמצם"
                txt += f"; ב{mlabel(spread['first_m'])} הפער היה {fmt.int_he(abs(a))} ש״ח, כלומר הוא {dirw} מאז."
            else:
                txt += f"; ב{mlabel(spread['first_m'])} הפער היה בכיוון ההפוך ({fmt_signed(a, 0, '')} ש״ח)."
            return txt
        else:
            txt += f", בדומה ל{mlabel(spread['first_m'])} ({fmt_signed(a, 0, '')} ש״ח)."
        return txt

    def ins_fixed():
        tanks = [r for r in fixed if r["kind"] == "tank"]
        if not tanks:
            return None
        bits = [f"{r['label'].split(':')[0]} ב-{abs(r['avg']):.2f}%" for r in tanks]
        word = "זול" if all(r["avg"] < 0 for r in tanks) else "שונה"
        ns = {r["n"] for r in tanks}
        span = f"בכל {len(months)} החודשים" if ns == {len(months)} else "בכל החודשים שבהם פורסמו שתי הסדרות"
        return (f"המחיר במכלית {word} בשיעור קבוע מהמחיר בהזרמה {span}: "
                f"{fmt.join_he(bits)}.")

    def ins_quote():
        qs = [r for r in rels if r["kind"] == "quote"]
        if not qs:
            return None
        r = qs[0]
        if abs(r["avg"]) < 0.3:
            return None
        word = "גבוה" if r["avg"] > 0 else "נמוך"
        return (f"ל{fshort(r['fam'])} מתפרסמים שני מחירים: המחיר לפי ציטוט {word} מהמחיר המחושב בממוצע "
                f"ב-{abs(r['avg']):.1f}%, בטווח של {fmt_signed(r['min'])} עד {fmt_signed(r['max'])}.")

    def ins_heat():
        hs = [r for r in rels if r["kind"] == "heat"]
        if not hs:
            return None
        r = hs[0]
        if r["max"] < 0 and abs(r["avg"]) >= 0.5:
            span = "בכל החודשים" if r["n"] == len(months) else f"בכל {r['n']} החודשים שבהם פורסמו שתי הסדרות"
            return (f"סולר להסקה זול מסולר לתחבורה {span}, בממוצע ב-{abs(r['avg']):.1f}% "
                    f"(בין {abs(r['max']):.1f}% ל-{abs(r['min']):.1f}%).")
        return None

    add("main_yoy", ins_main())
    add("shock", ins_shock())
    add("mom", ins_mom())
    add("range", ins_range())
    add("spread", ins_spread())
    add("fixed", ins_fixed())
    add("quote", ins_quote())
    add("heat", ins_heat())

    # ── summary (meta description) ──
    summary = "מחירים מחושבים מרביים בשער בית הזיקוק לבנזין 95, סולר, קרוסין ונפטא, לפי חודש."
    if main_k:
        extra = f" ב{mlabel(latest)}: {flabel(main_k)} {fmt_price(val(main_k, latest))} ש״ח {ushort(main_k)}"
        if "main_yoy" in kpis:
            extra += f" ({fmt_signed(kpis['main_yoy']['value'])} בשנה)"
        extra += "."
        if len(summary + extra) <= SUMMARY_MAX:
            summary += extra
    summary = summary[:SUMMARY_MAX]

    labels.update({
        "index_lede": idx_lede,
        "index_aria": (f"גרף קווים: מחיר {len(rep_keys)} מוצרים כמדד (החודש הראשון = 100), "
                       f"{mlabel(first)} עד {mlabel(latest)}."),
        "change_lede": change_lede,
        "change_aria": (f"גרף עמודות: שינוי במחיר {len(shown)} סדרות ב{mlabel(latest)}"
                        + (f", לעומת {mlabel(prev)} ולעומת {mlabel(ago)}." if prev else ".")),
        "change_head_mom": f"שינוי לעומת {mshort(prev)}" if prev else "שינוי חודשי",
        "change_head_yoy": f"שינוי לעומת {mshort(ago)}",
        "change_head_price": f"מחיר {mshort(latest)}",
        "range_lede": range_lede,
        "range_aria": (f"גרף עמודות: מיקום מחיר {mlabel(latest)} בטווח של {len(rng)} מוצרים"
                       + (f", הגבוה ביותר {rng[0]['label']} ב-{rng[0]['pos'] * 100:.0f}%." if rng else ".")),
        "heat_lede": (f"שינוי חודשי באחוזים, {len(heat['x'])} החודשים האחרונים, סדרה מייצגת לכל מוצר. "
                      f"אדום: התייקרות, כחול: הוזלה. {up_cells} מתוך {len(cells)} התאים הם התייקרות."),
        "heat_aria": f"מפת חום: שינוי חודשי במחיר של {len(heat['y'])} מוצרים ב-{len(heat['x'])} החודשים האחרונים.",
        "moves_lede": (f"{len(top)} השינויים החודשיים החדים ביותר מאז {mlabel(first)}, בסדרה המייצגת של כל מוצר."
                       if top else ""),
        "moves_aria": (f"גרף עמודות: {len(top)} השינויים החודשיים החדים ביותר, בראשם {top[0][2]} ב{mlabel(top[0][3])} "
                       f"({fmt_signed(top[0][1])})." if top else "גרף עמודות: השינויים החודשיים החדים ביותר."),
        "rel_lede": rel_lede,
        "rel_aria": f"גרף קווים: הפרש באחוזים בין {len(rels)} זוגות של סדרות מחיר, {mlabel(first)} עד {mlabel(latest)}.",
        "notes": NOTES,
        "dropped": " ".join(t for t in [
            f"{n_bad} שורות ללא תאריך או מחיר תקינים לא נכללו." if n_bad else "",
            (f"נתוני {mlabel(partial)} חלקיים ({per_month[partial]} סדרות בלבד) ולכן לא נכללו עד להשלמתם."
             if partial else ""),
        ] if t),
    })

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first}/{latest}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "units": unit_charts,
            "index": {"x": xlabels, "series": idx_series},
            "change": change_chart,
            "range": range_chart,
            "heat": heat,
            "moves": moves_chart,
            "spread": {"x": spread["x"], "y": spread["y"]} if spread else None,
            "rel": rel_chart,
        },
        "tables": {
            "change": change_table,
            "range": range_table,
            "moves": moves_table,
            "rel": rel_table,
        },
        "sections": {
            "spread": {"lede": spread["lede"], "aria": spread["aria"]} if spread else None,
        },
        "labels": labels,
        "insights": insights,
    }
