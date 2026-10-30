"""מעיינות - ספיקה מדודה: instantaneous discharge measurements (litres/second) of
springs, Hydrological Service (Water Authority).

Data: one row per measurement (spring id, date dd/mm/yyyy, hydrological year
"YYYY/YYYY" running October to September, discharge in L/s, method). A year is
keyed by its END year here (2024/2025 -> 2025).

Rows whose method is "ללא מדידה" (no measurement) carry a placeholder value
(mostly 0) and are excluded from every flow statistic (disclosed on the page);
they are still counted in the methods chart.

The set of measured springs changes a lot over time, so national sums or
averages track the network, not the water. The headline series is a FLOW
INDEX: for each spring and hydrological year, the mean of that year's
measurements (years with at least MIN_YEAR_OBS measurements), divided by the
spring's own long-term median of those yearly means; the index is the median
of the ratios across springs measured that year. 100% = a normal year for the
typical spring.

"Latest" is the latest hydrological year in the data whose measurements reach
late summer (a year that stops earlier is partial and is left out of the
index, disclosed), never the wall clock.

Regions come from the spring id: its leading digits (all but the last three)
are the Hydrological Service drainage-basin code. Known codes map to a broad
region; unknown codes fall into "אזורים אחרים".
"""
import re

import pandas as pd

C_ID, C_HE, C_HY, C_DATE, C_Q, C_METHOD = (
    "מספר זיהוי", "שם עברית", "שנה הידרולוגית", "תאריך מדידת ספיקה",
    "ספיקה (ליטר/שניה)", "שיטת מדידה")

NO_MEAS = "ללא מדידה"
NO_METHOD = "לא צוין"
OTHER_METHODS = "שיטות נוספות"

MIN_YEAR_OBS = 4         # measurements a spring-year needs to enter the index
MIN_BASE_YEARS = 10      # qualifying years a spring needs for its own baseline
MIN_BASE_Q = 5.0         # baseline median (L/s) below this: ratio is noise
MIN_INDEX_SPRINGS = 15   # springs a year needs to enter the index
FULL_YEAR_MONTH = 11     # hydrological month (Oct=1) the latest year must reach (August)
DROUGHT = 0.80
WET = 1.20
MIN_RUN = 3
RECENT_SPAN = 20
LATEST_N = 15
MAJOR_N = 6
MAJOR_MIN_YEARS = 30
TOP_N = 15
TOP_MIN_OBS = 20
TABLE_ROWS = 20
RECORD_MIN_YEARS = 20
METHOD_N = 7
MIN_DECADE_OBS = 10      # spring-years a region x decade cell needs
MIN_REGION_LATEST = 3
MIN_DECADE_MEAS = 50     # measurements a decade needs in the methods chart
SEASON_GAP = 0.20        # peak-trough gap (in ratio units) worth an insight

REGIONS = [
    ("עמק החולה ומקורות הירדן", ["30"]),
    ("הכנרת וסביבתה", ["31", "32"]),
    ("הגליל המערבי", ["1", "2", "4", "5", "7"]),
    ("אגן הקישון", ["8"]),
    ("הכרמל ונחל תנינים", ["10", "12", "13"]),
    ("עמק חרוד, בית שאן ונחל תבור", ["34", "35", "36", "38", "39"]),
    ("הרי השומרון, ירושלים וחברון", ["14", "15", "17", "18", "19", "23"]),
    ("בקעת הירדן ויריחו", ["43", "45", "46"]),
    ("ים המלח", ["48", "58", "59"]),
    ("הנגב והערבה", ["55", "56", "57", "60"]),
]
OTHER_REGION = "אזורים אחרים"
REGION_OF = {code: name for name, codes in REGIONS for code in codes}
REGION_ORDER = [name for name, _ in REGIONS] + [OTHER_REGION]

# Hydrological month order: October first.
HY_MONTHS = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
MONTH_HE = {1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל", 5: "מאי", 6: "יוני",
            7: "יולי", 8: "אוגוסט", 9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר", 12: "דצמבר"}

# Published group totals ("סכום ..." / "... סיכום") sum several springs that
# also appear on their own; they are excluded from every spring-level statistic.
SUM_RE = re.compile(r"סיכום|סכום")

YEAR_RE = re.compile(r"^\s*(\d{4})\s*/\s*(\d{4})\s*$")


def hy_label(y):
    return f"{y - 1}/{str(y)[-2:]}"


def pct(r):
    return f"{r * 100:.0f}%"


def num(v):
    if v >= 100:
        return f"{v:,.0f}"
    if v >= 10:
        return f"{v:,.1f}".rstrip("0").rstrip(".")
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def kpi_tone(r):
    if r is None:
        return "brand"
    if r < 0.7:
        return "danger"
    if r < 0.9:
        return "warn"
    if r > 1.1:
        return "ok"
    return "brand"


def _clean_name(s):
    s = " ".join(s.split())
    return s.replace("( ", "(").replace(" )", ")")


def _end_year(s):
    m = YEAR_RE.match(s)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return b if b == a + 1 else None


def _prepare(df):
    out = pd.DataFrame({
        "id": df[C_ID].astype(str).str.strip(),
        "name": df[C_HE].astype(str).map(_clean_name),
        "y": df[C_HY].astype(str).map(_end_year),
        "d": pd.to_datetime(df[C_DATE].astype(str).str.strip(), format="%d/%m/%Y", errors="coerce"),
        "q": pd.to_numeric(df[C_Q].astype(str).str.replace(",", "", regex=False).str.strip(),
                           errors="coerce"),
        "method": df[C_METHOD].astype(str).str.strip().replace("", NO_METHOD),
    })
    out = out[out["id"] != ""].copy()
    names = out[out["name"] != ""].groupby("id")["name"].min()
    valid = out.dropna(subset=["y", "d", "q"]).copy()
    valid = valid[valid["q"] >= 0]
    bad = len(out) - len(valid)
    valid["y"] = valid["y"].astype(int)
    valid["month"] = valid["d"].dt.month.astype(int)
    valid["hm"] = valid["month"].map(lambda mo: HY_MONTHS.index(mo) + 1)
    valid = valid.sort_values(["id", "d", "q", "method"], kind="mergesort").reset_index(drop=True)
    valid["name"] = valid["id"].map(names).fillna(valid["id"])
    valid["region"] = valid["id"].map(
        lambda i: REGION_OF.get(i[:-3], OTHER_REGION) if len(i) > 3 else OTHER_REGION)
    sum_ids = sorted(i for i, nm in names.items() if SUM_RE.search(nm))
    n_sum_rows = int(valid["id"].isin(sum_ids).sum())
    valid = valid[~valid["id"].isin(sum_ids)].reset_index(drop=True)
    meas = valid[valid["method"] != NO_MEAS].copy()
    return out, valid, meas, names, bad, sum_ids, n_sum_rows


def _runs(years, flags):
    runs, cur, prev = [], [], None
    for y, f in zip(years, flags):
        if f and cur and prev is not None and y == prev + 1:
            cur.append(y)
        elif f:
            if cur:
                runs.append(cur)
            cur = [y]
        else:
            if cur:
                runs.append(cur)
            cur = []
        prev = y
    if cur:
        runs.append(cur)
    return runs


def compute(frames):
    raw, valid, meas, names, bad, sum_ids, n_sum_rows = _prepare(frames["main"])
    n_rows = len(raw)
    n_nomeas = int((valid["method"] == NO_MEAS).sum())
    n_springs = int(meas["id"].nunique())
    d_first, d_last = meas["d"].min(), meas["d"].max()
    y_first, y_last = int(meas["y"].min()), int(meas["y"].max())

    # Partial latest year: measurements must reach late summer.
    last_hm = meas.groupby("y")["hm"].max()
    full_years = sorted(int(y) for y, v in last_hm.items() if v >= FULL_YEAR_MONTH)
    # The newest year when its measurements stop before late summer: labelled
    # on the network chart and left out of the dry-springs chart (the dry
    # season is not in it yet), so neither reads as a decline.
    y_partial = y_last if y_last not in full_years else None

    def ylab_p(y):
        return hy_label(y) + (" (חלקית)" if y == y_partial else "")

    # Spring-year means and baselines ---------------------------------------
    sy = meas.groupby(["id", "y"])["q"].agg(["mean", "size"]).reset_index()
    sy = sy[sy["size"] >= MIN_YEAR_OBS]
    sy = sy[sy["y"].isin(full_years)]
    base = sy.groupby("id")["mean"].agg(["median", "size"])
    base = base[(base["size"] >= MIN_BASE_YEARS) & (base["median"] >= MIN_BASE_Q)]
    sb = sy[sy["id"].isin(base.index)].copy()
    sb["base"] = sb["id"].map(base["median"])
    sb["r"] = sb["mean"] / sb["base"]
    sb["name"] = sb["id"].map(names).fillna(sb["id"])
    sb["region"] = sb["id"].map(
        lambda i: REGION_OF.get(i[:-3], OTHER_REGION) if len(i) > 3 else OTHER_REGION)

    idx = sb.groupby("y")["r"].agg(["median", "size"])
    idx = idx[idx["size"] >= MIN_INDEX_SPRINGS].sort_index()
    idx_years = [int(y) for y in idx.index]
    L = idx_years[-1]
    lab_L = hy_label(L)
    idx_L = float(idx.loc[L, "median"])
    partial_note = ""
    if y_partial is not None:
        mo = MONTH_HE[HY_MONTHS[int(last_hm[y_partial]) - 1]]
        partial_note = (f" השנה {hy_label(y_partial)} חלקית (המדידות בה מגיעות עד {mo}) "
                        f"ולכן אינה נכללת במדד.")

    chart_index = {
        "x": [hy_label(y) for y in idx_years],
        "y": [round(float(v) * 100, 1) for v in idx["median"]],
        "n": [int(v) for v in idx["size"]],
        "drought": round(DROUGHT * 100), "wet": round(WET * 100),
    }
    table_index = [{"year": hy_label(y), "pct": f"{idx.loc[y, 'median'] * 100:.0f}",
                    "n": f"{int(idx.loc[y, 'size']):,}"} for y in idx_years[-TABLE_ROWS:]]

    # Network: measurements and springs per year ----------------------------
    net = meas.groupby("y").agg(n=("q", "size"), s=("id", "nunique"))
    net_years = list(range(y_first, y_last + 1))
    chart_network = {
        "x": [ylab_p(y) for y in net_years],
        "n": [int(net["n"].get(y, 0)) for y in net_years],
        "s": [int(net["s"].get(y, 0)) for y in net_years],
    }
    table_network = [{"year": ylab_p(y), "n": f"{int(net['n'].get(y, 0)):,}",
                      "s": f"{int(net['s'].get(y, 0)):,}"} for y in net_years[-TABLE_ROWS:]]
    peak_s = int(net["s"].max())
    peak_y = int(min(y for y, v in net["s"].items() if v == peak_s))
    s_L = int(net["s"].get(L, 0))
    n_L = int(net["n"].get(L, 0))

    # Latest year vs own median --------------------------------------------
    latest = sb[sb["y"] == L].sort_values(["base", "id"], ascending=[False, True])
    latest_top = latest.head(LATEST_N)
    chart_latest = {
        "names": latest_top["name"].tolist(),
        "pct": [round(float(r) * 100, 1) for r in latest_top["r"]],
        "q": [round(float(v), 1) for v in latest_top["mean"]],
        "base": [round(float(v), 1) for v in latest_top["base"]],
    }
    table_latest = [{"name": r["name"], "q": num(r["mean"]), "base": num(r["base"]),
                     "pct": f"{r['r'] * 100:.0f}"} for _, r in latest_top.iterrows()]

    # Major springs: small multiples ----------------------------------------
    major_ids = [i for i in latest["id"].tolist() if base.loc[i, "size"] >= MAJOR_MIN_YEARS][:MAJOR_N]
    major, table_major = [], []
    for i in major_ids:
        g = sb[sb["id"] == i].set_index("y")["mean"]
        lo_y = min(g.index, key=lambda y: (float(g[y]), y))
        hi_y = max(g.index, key=lambda y: (float(g[y]), -y))
        nm = names.get(i, i)
        table_major.append({"name": nm, "median": num(base.loc[i, "median"]), "latest": num(g[L]),
                            "min": f"{num(g[lo_y])} ({hy_label(int(lo_y))})",
                            "max": f"{num(g[hi_y])} ({hy_label(int(hi_y))})"})
        ys = list(range(int(g.index.min()), L + 1))
        major.append({"name": nm, "x": [hy_label(y) for y in ys],
                      "y": [round(float(g[y]), 1) if y in g.index else None for y in ys],
                      "median": round(float(base.loc[i, "median"]), 1)})

    # Seasonality: ratio of each measurement to its spring's baseline -----------
    mb = meas[meas["id"].isin(base.index)].copy()
    mb["r"] = mb["q"] / mb["id"].map(base["median"])
    season = mb.groupby("hm")["r"].quantile([0.25, 0.5, 0.75]).unstack()
    season_n = mb.groupby("hm").size()
    hms = [h for h in range(1, 13) if h in season.index]
    chart_season = {
        "x": [MONTH_HE[HY_MONTHS[h - 1]] for h in hms],
        "p25": [round(float(season.loc[h, 0.25]) * 100, 1) for h in hms],
        "p50": [round(float(season.loc[h, 0.5]) * 100, 1) for h in hms],
        "p75": [round(float(season.loc[h, 0.75]) * 100, 1) for h in hms],
    }
    table_season = [{"month": MONTH_HE[HY_MONTHS[h - 1]],
                     "p50": f"{season.loc[h, 0.5] * 100:.0f}",
                     "band": f"{season.loc[h, 0.25] * 100:.0f} עד {season.loc[h, 0.75] * 100:.0f}",
                     "n": f"{int(season_n[h]):,}"} for h in hms]
    s_peak = max(hms, key=lambda h: (float(season.loc[h, 0.5]), -h))
    s_low = min(hms, key=lambda h: (float(season.loc[h, 0.5]), h))

    # Regions x decades ----------------------------------------------------
    sb["dec"] = (sb["y"] // 10) * 10
    n_other = int(sb.loc[sb["region"] == OTHER_REGION, "id"].nunique())
    reg = sb[sb["region"] != OTHER_REGION].groupby(["region", "dec"])["r"].agg(["median", "size"])
    reg = reg[reg["size"] >= MIN_DECADE_OBS]
    decs = sorted(int(d) for d in reg.index.get_level_values(1).unique())
    regs = [r for r in REGION_ORDER if r in set(reg.index.get_level_values(0))]
    cells = [[decs.index(int(d)), regs.index(rg), round(float(row["median"]) * 100), int(row["size"])]
             for (rg, d), row in reg.iterrows()]
    cells.sort(key=lambda c: (c[1], c[0]))
    reg_L = latest[latest["region"] != OTHER_REGION].groupby("region")["r"].agg(["median", "size"])
    reg_L = reg_L[reg_L["size"] >= MIN_REGION_LATEST]
    chart_region = {"decades": [f"עשור {d}" for d in decs], "regions": regs, "cells": cells}
    table_region = {
        "cols": [str(d) for d in decs],
        "rows": [{"region": rg,
                  "vals": [(f"{reg.loc[(rg, d), 'median'] * 100:.0f}" if (rg, d) in reg.index else "")
                           for d in decs],
                  "latest": (f"{reg_L.loc[rg, 'median'] * 100:.0f}" if rg in reg_L.index else "")}
                 for rg in regs],
    }

    # Dry springs: spring-years with a zero measurement ----------------------
    zy = meas.groupby(["id", "y"])["q"].min().reset_index()
    zy["z"] = zy["q"] == 0
    zero = zy.groupby("y").agg(n=("z", "size"), z=("z", "sum"))
    zero = zero[(zero["n"] >= MIN_INDEX_SPRINGS) & zero.index.isin(full_years)]
    zero["share"] = zero["z"] / zero["n"]
    chart_zero = {"x": [hy_label(int(y)) for y in zero.index],
                  "z": [int(v) for v in zero["z"]],
                  "share": [round(float(v) * 100, 1) for v in zero["share"]]}
    table_zero = [{"year": hy_label(int(y)), "z": f"{int(r['z']):,}", "n": f"{int(r['n']):,}",
                   "share": f"{r['share'] * 100:.0f}"} for y, r in zero.tail(TABLE_ROWS).iterrows()]

    # Methods by decade -----------------------------------------------------
    vm = valid.copy()
    vm["dec"] = (vm["y"] // 10) * 10
    mcount = (vm["method"].value_counts().rename_axis("m").reset_index(name="c")
              .sort_values(["c", "m"], ascending=[False, True]))
    keep = mcount["m"].tolist()[:METHOD_N]
    vm["mg"] = vm["method"].where(vm["method"].isin(keep), OTHER_METHODS)
    groups = keep + ([OTHER_METHODS] if len(mcount) > METHOD_N else [])
    dtot = vm.groupby("dec").size()
    mdecs = sorted(int(d) for d, v in dtot.items() if v >= MIN_DECADE_MEAS)
    mct = vm.groupby(["dec", "mg"]).size()
    chart_methods = {
        "x": [f"עשור {d}" for d in mdecs],
        "series": [{"name": g, "data": [round(float(mct.get((d, g), 0)) / float(dtot[d]) * 100, 1)
                                        for d in mdecs]} for g in groups],
    }
    table_methods = {
        "cols": groups,
        "rows": [{"dec": str(d), "n": f"{int(dtot[d]):,}",
                  "vals": [f"{mct.get((d, g), 0) / dtot[d] * 100:.0f}" for g in groups]} for d in mdecs],
    }
    mL = valid[valid["y"] == L]["method"].value_counts()
    mL = mL.rename_axis("m").reset_index(name="c").sort_values(["c", "m"], ascending=[False, True])

    # Top springs by median measured discharge --------------------------------
    sp = meas.groupby("id").agg(med=("q", "median"), n=("q", "size"), y0=("y", "min"), y1=("y", "max"))
    sp = sp[sp["n"] >= TOP_MIN_OBS].reset_index().sort_values(["med", "id"], ascending=[False, True])
    top = sp.head(TOP_N)
    chart_top = {"names": [names.get(i, i) for i in top["id"]],
                 "y": [round(float(v), 2) for v in top["med"]]}
    table_top = [{"name": names.get(r["id"], r["id"]), "med": num(r["med"]), "n": f"{int(r['n']):,}",
                  "span": f"{hy_label(int(r['y0']))} עד {hy_label(int(r['y1']))}"}
                 for _, r in top.iterrows()]

    # Insights --------------------------------------------------------------
    def ins_latest():
        order = sorted(idx_years, key=lambda y: (float(idx.loc[y, "median"]), y))
        rank_low = order.index(L) + 1
        rank_high = len(order) - rank_low + 1
        head = (f"ב-{lab_L} עמדה הספיקה של המעיין הטיפוסי על {pct(idx_L)} מהרגיל שלו "
                f"({int(idx.loc[L, 'size'])} מעיינות במדד)")
        if rank_low == 1:
            return f"{head}: השנה היבשה ביותר מבין {len(order)} השנים במדד, מאז {hy_label(idx_years[0])}."
        if rank_low <= 5:
            return f"{head}: המקום ה-{rank_low} מבין השנים היבשות ביותר, מתוך {len(order)} שנים במדד."
        if rank_high <= 5:
            return f"{head}: המקום ה-{rank_high} מבין השנים השופעות ביותר, מתוך {len(order)} שנים במדד."
        if abs(idx_L - 1) < 0.05:
            return f"{head}, קרוב לרגיל."
        return f"{head}, {'מעל' if idx_L > 1 else 'מתחת ל'}רגיל."

    def ins_largest():
        if latest.empty:
            return None
        r = latest.iloc[0]
        prev = sb[(sb["id"] == r["id"]) & (sb["y"] < L)]
        if len(prev) < MIN_BASE_YEARS:
            return None
        if r["r"] >= 1:
            higher = prev[prev["mean"] >= r["mean"]]
            tail = ("הגבוה ביותר מאז תחילת המדידה" if higher.empty
                    else f"הגבוה ביותר מאז {hy_label(int(higher['y'].max()))}")
        else:
            lower = prev[prev["mean"] <= r["mean"]]
            tail = (f"הנמוך ביותר מאז תחילת המדידה ב-{hy_label(int(prev['y'].min()))}" if lower.empty
                    else f"הנמוך ביותר מאז {hy_label(int(lower['y'].max()))}")
        return (f"{r['name']}, הגדול במעיינות שנמדדו ב-{lab_L}, נמדד בממוצע ב-{num(r['mean'])} ליטר "
                f"לשנייה: {pct(r['r'])} מהחציון הרב-שנתי שלו ({num(r['base'])} ליטר לשנייה), {tail}.")

    def ins_records():
        hits = []
        for i, g in sb[sb["id"].isin(latest["id"])].groupby("id"):
            prev = g[g["y"] < L]["mean"]
            if len(prev) + 1 < RECORD_MIN_YEARS:
                continue
            cur = float(g[g["y"] == L]["mean"].iloc[0])
            if cur < float(prev.min()):
                hits.append((float(base.loc[i, "median"]), i))
        if not hits:
            return None
        hits.sort(key=lambda t: (-t[0], t[1]))
        nm = ", ".join(names.get(i, i) for _, i in hits[:3])
        return (f"ב-{lab_L} נרשמה הספיקה השנתית הממוצעת הנמוכה ביותר אי פעם ב-{len(hits)} מעיינות "
                f"שיש להם {RECORD_MIN_YEARS} שנות מדידה לפחות, ביניהם {nm}.")

    def ins_drought_run():
        runs = [r for r in _runs(idx_years, [float(idx.loc[y, "median"]) < DROUGHT for y in idx_years])
                if len(r) >= MIN_RUN]
        if not runs:
            return None
        best = max(runs, key=lambda r: (len(r), r[-1]))
        lo_y = min(best, key=lambda y: (float(idx.loc[y, "median"]), y))
        return (f"רצף היובש הארוך ביותר במדד: {len(best)} שנים רצופות, {hy_label(best[0])} עד "
                f"{hy_label(best[-1])}, שבהן הספיקה הטיפוסית הייתה מתחת ל-{pct(DROUGHT)} מהרגיל "
                f"(השפל ברצף: {pct(float(idx.loc[lo_y, 'median']))} ב-{hy_label(lo_y)}).")

    def ins_dry_share():
        recent, earlier = idx_years[-RECENT_SPAN:], idx_years[:-RECENT_SPAN]
        if len(earlier) < RECENT_SPAN:
            return None
        dr = sum(float(idx.loc[y, "median"]) < DROUGHT for y in recent)
        de = sum(float(idx.loc[y, "median"]) < DROUGHT for y in earlier)
        sr, se = dr / len(recent), de / len(earlier)
        if abs(sr - se) < 0.10:
            return None
        return (f"ב-{dr} מתוך {len(recent)} השנים האחרונות במדד ({hy_label(recent[0])} עד {lab_L}) "
                f"הספיקה הטיפוסית ירדה מתחת ל-{pct(DROUGHT)} מהרגיל, כלומר {pct(sr)} מהשנים, "
                f"{'יותר' if sr > se else 'פחות'} מאשר ב-{len(earlier)} השנים שקדמו להן ({pct(se)}).")

    def ins_season():
        hi, lo = float(season.loc[s_peak, 0.5]), float(season.loc[s_low, 0.5])
        if hi - lo < SEASON_GAP:
            return None
        return (f"מחזור עונתי: המדידות ב{MONTH_HE[HY_MONTHS[s_peak - 1]]} עומדות בחציון על {pct(hi)} "
                f"מהספיקה הרגילה של המעיין, ואילו ב{MONTH_HE[HY_MONTHS[s_low - 1]]} על {pct(lo)} בלבד"
                + (", בסוף עונת היובש." if HY_MONTHS[s_low - 1] in (8, 9, 10, 11) else "."))

    def ins_zero():
        if L not in zero.index or len(zero) < RECENT_SPAN:
            return None
        sL = float(zero.loc[L, "share"])
        med = float(zero["share"].median())
        if abs(sL - med) < 0.05:
            return None
        return (f"ב-{lab_L} נמצאו יבשים (ספיקה אפס) לפחות פעם אחת {int(zero.loc[L, 'z'])} מתוך "
                f"{int(zero.loc[L, 'n'])} המעיינות שנמדדו ({pct(sL)}), "
                f"{'יותר' if sL > med else 'פחות'} מהשיעור החציוני לאורך השנים ({pct(med)}).")

    def ins_methods():
        if mL.empty:
            return None
        top_m, c = mL.iloc[0]["m"], int(mL.iloc[0]["c"])
        share = c / int(mL["c"].sum())
        if share < 0.3:
            return None
        hist = float((valid["method"] == top_m).mean())
        return (f"שיטת המדידה הנפוצה ב-{lab_L}: {top_m}, ב-{pct(share)} מהמדידות "
                f"(לעומת {pct(hist)} מכלל המדידות במאגר).")

    def ins_network():
        if s_L >= 0.6 * peak_s:
            return None
        return (f"רשת המדידה הצטמצמה: בשיאה, ב-{hy_label(peak_y)}, נמדדו {peak_s} מעיינות, "
                f"וב-{lab_L} {s_L} מעיינות ({n_L:,} מדידות). לכן המדד בעמוד משווה כל מעיין לרגיל שלו "
                f"ולא סוכם ספיקות ארצי.")

    def ins_region():
        if len(reg_L) < 2:
            return None
        s = reg_L.reset_index().sort_values(["median", "region"])
        lo, hi = s.iloc[0], s.iloc[-1]
        if float(hi["median"]) - float(lo["median"]) < 0.2:
            return None
        return (f"הפער האזורי ב-{lab_L}: באזור {lo['region']} הספיקה הטיפוסית הייתה {pct(lo['median'])} "
                f"מהרגיל ({int(lo['size'])} מעיינות), ובאזור {hi['region']} {pct(hi['median'])} "
                f"({int(hi['size'])} מעיינות).")

    rules = [("latest", ins_latest()), ("largest", ins_largest()), ("records", ins_records()),
             ("region", ins_region()), ("drought_run", ins_drought_run()), ("dry_share", ins_dry_share()),
             ("season", ins_season()), ("zero", ins_zero()), ("methods", ins_methods()),
             ("network", ins_network())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # KPIs ------------------------------------------------------------------
    big = latest.iloc[0] if not latest.empty else None
    kpis = {
        "index": {"value": round(idx_L, 4), "display": pct(idx_L), "tone": kpi_tone(idx_L)},
        "largest": {"value": None if big is None else round(float(big["mean"]), 2),
                    "display": "" if big is None else num(big["mean"]),
                    "tone": "brand" if big is None else kpi_tone(float(big["r"]))},
        "active": {"value": s_L, "display": f"{s_L:,}",
                   "tone": "warn" if s_L < 0.6 * peak_s else "brand"},
        "measurements": {"value": len(meas), "display": f"{len(meas):,}", "tone": "brand"},
    }
    kpi_labels = {
        "index": f"ספיקת המעיין הטיפוסי ב-{lab_L}, באחוזים מהרגיל שלו",
        "largest": ("" if big is None else
                    f"{big['name']}: ספיקה ממוצעת ב-{lab_L} (ליטר לשנייה), {pct(big['r'])} מהחציון"),
        "active": f"מעיינות שנמדדו ב-{lab_L} (בשיא, ב-{hy_label(peak_y)}: {peak_s})",
        "measurements": f"מדידות ספיקה של {n_springs:,} מעיינות, {d_first.year} עד {d_last.year}",
    }

    filt = ""
    if bad:
        filt = (" רשומה אחת עם תאריך, שנה או ספיקה לא תקינים לא נכללה." if bad == 1 else
                f" {bad:,} רשומות עם תאריך, שנה או ספיקה לא תקינים לא נכללו.")
    nomeas = (f" {n_nomeas:,} רשומות מסומנות \"{NO_MEAS}\" ואינן נכללות בחישובי הספיקה."
              if n_nomeas else "")
    sums = ""
    if sum_ids:
        sums = (f" {len(sum_ids)} רשומות סיכום של קבוצות נביעות (כגון {names.get(sum_ids[0], sum_ids[0])}), "
                f"{n_sum_rows:,} שורות, אינן נכללות כדי לא לספור את אותם מים פעמיים." if len(sum_ids) > 1 else
                f" רשומת סיכום אחת של קבוצת נביעות ({names.get(sum_ids[0], sum_ids[0])}) אינה נכללת "
                f"כדי לא לספור את אותם מים פעמיים.")
    labels = {
        "lede": (f"השירות ההידרולוגי ברשות המים מודד את הספיקה (ליטר לשנייה) של מעיינות ברחבי הארץ. "
                 f"המאגר כולל {len(meas):,} מדידות של {n_springs:,} מעיינות, מ-{d_first.year} ועד "
                 f"{d_last.strftime('%d.%m.%Y')}. ב-{lab_L} הספיקה של המעיין הטיפוסי עמדה על {pct(idx_L)} "
                 f"מהרגיל שלו.{nomeas}{sums}{filt}"),
        "index_note": (f"לכל מעיין ולכל שנה הידרולוגית (אוקטובר עד ספטמבר) עם {MIN_YEAR_OBS} מדידות לפחות "
                       f"מחושב ממוצע הספיקה. לכל מעיין עם {MIN_BASE_YEARS} שנים כאלה וחציון של "
                       f"{num(MIN_BASE_Q)} ליטר לשנייה לפחות, הממוצע מחולק בחציון הרב-שנתי שלו; המדד הוא "
                       f"החציון של היחסים בין המעיינות שנמדדו באותה שנה. {pct(1)} = שנה רגילה. נכללות שנים "
                       f"עם {MIN_INDEX_SPRINGS} מעיינות לפחות. אדום: מתחת ל-{pct(DROUGHT)}; כחול כהה: "
                       f"{pct(WET)} ומעלה.{partial_note}"),
        "index_aria": (f"תרשים עמודות: מדד הספיקה של המעיין הטיפוסי, {hy_label(idx_years[0])} עד {lab_L}. "
                       f"ב-{lab_L}: {pct(idx_L)} מהרגיל."),
        "index_caption": f"מדד הספיקה ב-{len(table_index)} השנים האחרונות במדד (באחוזים מהרגיל).",
        "latest_note": (f"{len(latest_top)} המעיינות הגדולים (לפי החציון הרב-שנתי) מתוך {len(latest)} "
                        f"שנכללו במדד ב-{lab_L}: ממוצע הספיקה בשנה זו באחוזים מהחציון של המעיין. "
                        f"{pct(1)} = שנה רגילה."),
        "latest_aria": (f"תרשים עמודות אופקי: הספיקה הממוצעת ב-{lab_L} באחוזים מהחציון הרב-שנתי, "
                        f"ב-{len(latest_top)} המעיינות הגדולים."),
        "latest_caption": f"ספיקה ממוצעת ב-{lab_L} לעומת החציון הרב-שנתי, ליטר לשנייה.",
        "major_note": (f"ממוצע הספיקה השנתי (ליטר לשנייה) של {len(major)} המעיינות הגדולים שנמדדו "
                       f"ב-{lab_L} ויש להם {MAJOR_MIN_YEARS} שנות מדידה לפחות, כל אחד בסולם משלו. "
                       f"הקו המקווקו: החציון הרב-שנתי."),
        "major_aria": "גרף ספיקה שנתית ממוצעת לאורך שנות המדידה, עם קו החציון הרב-שנתי:",
        "major_caption": f"ספיקה שנתית ממוצעת (ליטר לשנייה): חציון, {lab_L}, שפל ושיא.",
        "season_note": (f"כל מדידה מחולקת בספיקה הרגילה של המעיין שלה (החציון הרב-שנתי), ולכל חודש מוצג "
                        f"החציון של היחסים, עם טווח הרבעונים (הרבע התחתון עד הרבע העליון). מבוסס על "
                        f"{len(mb):,} מדידות של {mb['id'].nunique():,} מעיינות."),
        "season_aria": (f"תרשים קווי: ספיקה חודשית באחוזים מהרגיל, אוקטובר עד ספטמבר. שיא "
                        f"ב{MONTH_HE[HY_MONTHS[s_peak - 1]]}, שפל ב{MONTH_HE[HY_MONTHS[s_low - 1]]}."),
        "season_caption": "ספיקה לפי חודש, באחוזים מהספיקה הרגילה של המעיין.",
        "region_note": (f"החציון של יחס הספיקה השנתית לרגיל בכל אזור ועשור (באחוזים). האזור נגזר מקוד האגן "
                        f"שבראש מספר הזיהוי של המעיין. תא נכלל כשיש בו {MIN_DECADE_OBS} שנות-מעיין לפחות. "
                        f"העמודה האחרונה בטבלה: {lab_L}, באזורים עם {MIN_REGION_LATEST} מעיינות לפחות."
                        + ("" if not n_other else
                           " מעיין אחד שקוד האגן שלו לא שויך לאזור אינו מוצג." if n_other == 1 else
                           f" {n_other} מעיינות שקוד האגן שלהם לא שויך לאזור אינם מוצגים.")),
        "region_aria": f"מפת חום: מדד הספיקה לפי אזור ועשור, {len(regs)} אזורים ו-{len(decs)} עשורים.",
        "region_caption": "מדד הספיקה לפי אזור ועשור (באחוזים מהרגיל).",
        "zero_note": (f"מעיינות שלפחות מדידה אחת שלהם באותה שנה הייתה ספיקה אפס (המעיין יבש), ושיעורם "
                      f"מכלל המעיינות שנמדדו. נכללות שנים עם {MIN_INDEX_SPRINGS} מעיינות נמדדים לפחות."
                      + (f" השנה {hy_label(y_partial)} חלקית ואינה מוצגת." if y_partial is not None else "")),
        "zero_aria": (f"תרשים: מספר המעיינות שנמצאו יבשים בכל שנה ושיעורם מהמעיינות שנמדדו, "
                      f"{chart_zero['x'][0]} עד {chart_zero['x'][-1]}."),
        "zero_caption": f"מעיינות שנמצאו יבשים ב-{len(table_zero)} השנים האחרונות.",
        "methods_note": (f"חלקה של כל שיטת מדידה מכלל הרשומות בכל עשור (עשורים עם {MIN_DECADE_MEAS} רשומות "
                         f"לפחות). {len(groups)} קבוצות: השיטות הנפוצות במאגר, והשאר יחד."),
        "methods_aria": f"תרשים עמודות נערמות: שיטות המדידה לפי עשור, {len(mdecs)} עשורים.",
        "methods_caption": "שיטות המדידה לפי עשור (באחוזים מהרשומות).",
        "network_note": ("כמה מדידות נערכו בכל שנה הידרולוגית, ובכמה מעיינות. ירידה במספר המעיינות "
                         "משקפת שינוי ברשת המדידה, לא בהכרח במים."),
        "network_aria": (f"תרשים: מספר המדידות והמעיינות שנמדדו בכל שנה הידרולוגית, {hy_label(y_first)} "
                         f"עד {hy_label(y_last)}. שיא של {peak_s} מעיינות ב-{hy_label(peak_y)}."),
        "network_caption": f"מדידות ומעיינות ב-{len(table_network)} השנים האחרונות.",
        "top_note": (f"החציון של כל המדידות של המעיין (מעיינות עם {TOP_MIN_OBS} מדידות לפחות), בסולם "
                     f"לוגריתמי. רשומות הסיכום של קבוצות נביעות אינן נכללות."),
        "top_aria": f"תרשים עמודות אופקי: {len(top)} המעיינות בעלי הספיקה החציונית הגבוהה ביותר.",
        "top_caption": f"{len(top)} המעיינות בעלי הספיקה החציונית הגבוהה ביותר (ליטר לשנייה).",
    }

    big_txt = "" if big is None else f" {big['name']}: {num(big['mean'])} ל׳/ש׳."
    summary = (f"ספיקות מדודות של {n_springs:,} מעיינות, {d_first.year} עד {d_last.year}. "
               f"ב-{lab_L} המעיין הטיפוסי זרם ב-{pct(idx_L)} מהרגיל.{big_txt}")
    if len(summary) > 155:
        summary = (f"ספיקות מדודות של {n_springs:,} מעיינות, {d_first.year} עד {d_last.year}. "
                   f"ב-{lab_L} המעיין הטיפוסי זרם ב-{pct(idx_L)} מהרגיל.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "related_ids": [
                "9b0286dd-aaa4-4dc6-9878-9c65abbee66e",
                "073cd24f-58b0-4301-b6df-3b09607dfd46",
                "a53613b2-f5da-48d1-86d8-1a8094c568af",
                "5de14d12-d5d7-475d-ade1-5dbd0ef9d086",
                "f72117a6-2b71-43e9-bc81-75c284a4d1e2",
            ],
            "suggested_tags": ["מעיינות", "ספיקה", "הידרולוגיה", "משאבי מים", "בצורת"],
            "temporal_coverage": f"{d_first.year}/{d_last.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_labels": kpi_labels,
        "charts": {
            "index": chart_index, "network": chart_network, "latest": chart_latest, "major": major,
            "season": chart_season, "region": chart_region, "zero": chart_zero,
            "methods": chart_methods, "top": chart_top,
        },
        "tables": {
            "index": table_index, "network": table_network, "latest": table_latest,
            "major": table_major, "season": table_season, "region": table_region,
            "zero": table_zero, "methods": table_methods, "top": table_top,
        },
        "flags": {"major": bool(major), "largest": big is not None},
        "insights": insights,
        "labels": labels,
    }
