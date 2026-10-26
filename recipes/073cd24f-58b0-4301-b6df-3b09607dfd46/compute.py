"""מעיינות — נפחים שנתיים: annual discharge volume per spring, Hydrological Service.

Data: one row per (spring, hydrological year). Volume is in thousands of
cubic metres (אלמ"ק). Rows with an empty volume are placeholders (the spring
was not measured that year) and carry no data type. Years are "YYYY/YYYY"
(October to September); a year is keyed by its END year here.

The set of measured springs changes a lot over time (under 100 before 1960,
~250 in the 1980s-90s, ~60 in the latest years), so a plain national sum or
average mostly tracks the network, not the water. The page's headline series
is therefore a FLOW INDEX: each spring's volume divided by that spring's own
long-term median, and the median of those ratios across the springs measured
that year. 100% = a normal year for the typical spring.

"Latest" is the latest hydrological year in the data that has enough springs
for the index — never the wall clock.

Regions come from the spring id: its leading digits (all but the last three)
are the Hydrological Service drainage-basin code. Known codes map to a broad
region; unknown codes fall into "אזורים אחרים".
"""
import math
import re

import pandas as pd

C_ID, C_HE, C_HY, C_VOL, C_TYPE = ("מספר זיהוי", "שם עברית", "שנה הידרולוגית",
                                   "נפח שנתי (אלמ''ק)", "סוג נתון")

MIN_BASE_YEARS = 10      # years a spring needs for its own baseline median
MIN_BASE_VOL = 10.0      # baseline median (אלמ"ק) below this: ratio is noise
MIN_INDEX_SPRINGS = 15   # springs a year needs to enter the flow index
DROUGHT = 0.80           # index below this = a dry year
WET = 1.20               # index at/above this = a wet year
MIN_RUN = 3              # consecutive dry years that count as a drought run
EARLY = (1971, 1990)     # long-run comparison: 1970/71 .. 1989/90
LATE_SPAN = 20           # ... against the latest 20 hydrological years
MIN_WINDOW_YEARS = 8     # values a spring needs in each window
MIN_EARLY_VOL = 50.0     # early median (אלמ"ק) to enter the comparison
CHANGE_N = 15            # springs shown in the long-run change chart
LATEST_N = 15            # springs shown in the latest-year chart
MAJOR_N = 6              # small multiples
MAJOR_MIN_YEARS = 30
TOP_N = 15
TABLE_ROWS = 20
RECORD_MIN_YEARS = 20    # history a spring needs for a "record low" claim
DRY_STREAK = 3           # trailing zero measurements that mark a spring as dry
DRY_RECENT = 5           # ... with its last measurement within this many years
MIN_DECADE_OBS = 10      # spring-years a region x decade cell needs
MIN_REGION_LATEST = 3    # baseline springs a region needs in the latest year

# Drainage-basin code (id without its last three digits) -> broad region.
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

YEAR_RE = re.compile(r"^\s*(\d{4})\s*/\s*(\d{4})\s*$")


def hy_label(y):
    return f"{y - 1}/{str(y)[-2:]}"


def pct(r):
    return f"{r * 100:.0f}%"


def signed_pct(r):
    v = round(r * 100)
    if v == 0:
        return "ללא שינוי"
    return f"{'+' if v > 0 else '−'}{abs(v)}%"


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


def num(v):
    return f"{v:,.0f}"


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
        "vol": pd.to_numeric(df[C_VOL].astype(str).str.replace(",", "", regex=False).str.strip(),
                             errors="coerce"),
        "type": df[C_TYPE].astype(str).str.strip(),
    })
    out = out[out["id"] != ""]
    names = (out[out["name"] != ""].groupby("id")["name"].min())
    measured = out.dropna(subset=["vol"])
    bad_year = int(measured["y"].isna().sum())
    m = measured.dropna(subset=["y"]).copy()
    m = m[m["vol"] >= 0]
    m["y"] = m["y"].astype(int)
    # One value per spring-year (stable if CKAN ever duplicates one).
    m = (m.sort_values(["id", "y", "vol", "type"], kind="mergesort")
          .drop_duplicates(["id", "y"], keep="first").reset_index(drop=True))
    m["name"] = m["id"].map(names).fillna(m["id"])
    m["region"] = m["id"].map(lambda i: REGION_OF.get(i[:-3], OTHER_REGION) if len(i) > 3 else OTHER_REGION)
    return out, m, names, bad_year


def _runs(years, flags):
    """Maximal runs of consecutive years where flag is True."""
    runs, cur = [], []
    prev = None
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
    raw, m, names, bad_year = _prepare(frames["main"])
    n_rows = len(raw)
    n_springs = m["id"].nunique()
    n_ids = raw["id"].nunique()
    y_first, y_last_any = int(m["y"].min()), int(m["y"].max())

    # Baselines -----------------------------------------------------------
    base = m.groupby("id")["vol"].agg(["median", "size"])
    base = base[(base["size"] >= MIN_BASE_YEARS) & (base["median"] >= MIN_BASE_VOL)]
    mb = m[m["id"].isin(base.index)].copy()
    mb["base"] = mb["id"].map(base["median"])
    mb["r"] = mb["vol"] / mb["base"]

    idx = mb.groupby("y")["r"].agg(["median", "size"])
    idx = idx[idx["size"] >= MIN_INDEX_SPRINGS].sort_index()
    idx_years = [int(y) for y in idx.index]
    L = idx_years[-1]
    lab_L = hy_label(L)
    idx_L = float(idx.loc[L, "median"])
    later_years = sorted(int(y) for y in m["y"].unique() if y > L)
    later_note = ""
    if later_years:
        n_later = int((m["y"] == later_years[-1]).sum())
        later_note = (f" השנה {hy_label(later_years[-1])} מופיעה בנתונים עם {n_later} מעיינות "
                      f"בלבד ולכן אינה נכללת במדד.")

    measured_per_year = m.groupby("y").size()

    # Chart: flow index ----------------------------------------------------
    chart_index = {
        "x": [hy_label(y) for y in idx_years],
        "y": [round(float(v) * 100, 1) for v in idx["median"]],
        "n": [int(v) for v in idx["size"]],
        "drought": round(DROUGHT * 100), "wet": round(WET * 100),
    }
    table_index = [{"year": hy_label(y), "pct": f"{idx.loc[y, 'median'] * 100:.0f}",
                    "n": f"{int(idx.loc[y, 'size']):,}"} for y in idx_years[-TABLE_ROWS:]]

    # Chart: network by data type ----------------------------------------
    net_years = list(range(y_first, y_last_any + 1))
    tcounts = m.assign(type=m["type"].replace("", "לא צוין")).groupby(["type", "y"]).size()
    types = (m.assign(type=m["type"].replace("", "לא צוין"))["type"].value_counts()
              .rename_axis("t").reset_index(name="c")
              .sort_values(["c", "t"], ascending=[False, True])["t"].tolist())
    chart_network = {
        "x": [hy_label(y) for y in net_years],
        "series": [{"name": t, "data": [int(tcounts.get((t, y), 0)) for y in net_years]}
                   for t in types],
    }
    peak_n = int(measured_per_year.max())
    peak_y = int(min(y for y, v in measured_per_year.items() if v == peak_n))
    n_L = int(measured_per_year.get(L, 0))
    type_tot = {t: int((m["type"].replace("", "לא צוין") == t).sum()) for t in types}

    # Latest year vs own median -----------------------------------------
    latest = mb[mb["y"] == L].sort_values(["base", "id"], ascending=[False, True])
    latest_top = latest.head(LATEST_N)
    chart_latest = {
        "names": latest_top["name"].tolist(),
        "pct": [round(float(r) * 100, 1) for r in latest_top["r"]],
        "vol": [round(float(v), 1) for v in latest_top["vol"]],
        "base": [round(float(v), 1) for v in latest_top["base"]],
    }
    table_latest = [{"name": r["name"], "vol": num(r["vol"]), "base": num(r["base"]),
                     "pct": f"{r['r'] * 100:.0f}"} for _, r in latest_top.iterrows()]

    # Major springs: small multiples --------------------------------------
    major_ids = [i for i in latest["id"].tolist() if base.loc[i, "size"] >= MAJOR_MIN_YEARS][:MAJOR_N]
    by_id = {i: g for i, g in mb[mb["id"].isin(major_ids)].groupby("id")}
    major, table_major = [], []
    for i in major_ids:
        g = by_id[i].set_index("y")["vol"]
        lo_y = min(g.index, key=lambda y: (float(g[y]), y))
        hi_y = max(g.index, key=lambda y: (float(g[y]), -y))
        table_major.append({"name": names.get(i, i), "median": num(base.loc[i, "median"]),
                            "latest": num(g[L]), "min": f"{num(g[lo_y])} ({hy_label(int(lo_y))})",
                            "max": f"{num(g[hi_y])} ({hy_label(int(hi_y))})"})
        ys = list(range(int(g.index.min()), L + 1))
        major.append({"name": names.get(i, i),
                      "x": [hy_label(y) for y in ys],
                      "y": [round(float(g[y]), 1) if y in g.index else None for y in ys],
                      "median": round(float(base.loc[i, "median"]), 1)})

    # Regions x decades -------------------------------------------------
    mb["dec"] = (mb["y"] // 10) * 10
    n_other = int(mb.loc[mb["region"] == OTHER_REGION, "id"].nunique())
    reg = mb[mb["region"] != OTHER_REGION].groupby(["region", "dec"])["r"].agg(["median", "size"])
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
                  "vals": [(f"{reg.loc[(rg, d), 'median'] * 100:.0f}" if (rg, d) in reg.index else "—")
                           for d in decs],
                  "latest": (f"{reg_L.loc[rg, 'median'] * 100:.0f}" if rg in reg_L.index else "—")}
                 for rg in regs],
    }

    # Long-run change: early window vs latest 20 years ---------------------
    late0 = L - LATE_SPAN + 1
    ew = m[(m["y"] >= EARLY[0]) & (m["y"] <= EARLY[1])].groupby("id")["vol"].agg(["median", "size"])
    lw = m[(m["y"] >= late0) & (m["y"] <= L)].groupby("id")["vol"].agg(["median", "size"])
    ch = ew.join(lw, lsuffix="_e", rsuffix="_l", how="inner")
    ch = ch[(ch["size_e"] >= MIN_WINDOW_YEARS) & (ch["size_l"] >= MIN_WINDOW_YEARS)
            & (ch["median_e"] >= MIN_EARLY_VOL)].copy()
    ch["chg"] = ch["median_l"] / ch["median_e"] - 1
    ch["name"] = [names.get(i, i) for i in ch.index]
    ch = ch.reset_index().sort_values(["median_e", "id"], ascending=[False, True])
    ch_top = ch.head(CHANGE_N)
    early_lab = f"{hy_label(EARLY[0])} עד {hy_label(EARLY[1])}"
    late_lab = f"{hy_label(late0)} עד {lab_L}"
    chart_change = {"names": ch_top["name"].tolist(),
                    "pct": [round(float(v) * 100, 1) for v in ch_top["chg"]],
                    "early": [round(float(v), 1) for v in ch_top["median_e"]],
                    "late": [round(float(v), 1) for v in ch_top["median_l"]]}
    table_change = [{"name": r["name"], "early": num(r["median_e"]), "late": num(r["median_l"]),
                     "chg": signed_pct(r["chg"])} for _, r in ch_top.iterrows()]

    # Dry springs -------------------------------------------------------
    zero = m.assign(z=m["vol"] == 0).groupby("y").agg(n=("z", "size"), z=("z", "sum"))
    zero = zero[zero["n"] >= MIN_INDEX_SPRINGS]
    chart_dry = {"x": [hy_label(int(y)) for y in zero.index],
                 "zero": [int(v) for v in zero["z"]],
                 "share": [round(float(z) / float(n) * 100, 1) for z, n in zip(zero["z"], zero["n"])]}
    table_dry = [{"year": hy_label(int(y)), "zero": f"{int(r['z']):,}", "n": f"{int(r['n']):,}"}
                 for y, r in zero.tail(TABLE_ROWS).iterrows()]
    dried = []
    for i, g in m.sort_values(["id", "y"]).groupby("id"):
        vols = g["vol"].tolist()
        ys = g["y"].tolist()
        k = 0
        while k < len(vols) and vols[-1 - k] == 0:
            k += 1
        if k < DRY_STREAK or ys[-1] < y_last_any - DRY_RECENT + 1:
            continue
        flowing = [v for v in vols[:-k] if v > 0]
        if not flowing:
            continue
        before = float(pd.Series(vols[:-k]).median())
        if before < MIN_BASE_VOL:
            continue
        last_flow_y = max(y for y, v in zip(ys, vols) if v > 0)
        dried.append({"id": i, "name": names.get(i, i), "before": before, "k": k,
                      "last_flow": last_flow_y, "since": ys[-k]})
    dried.sort(key=lambda d: (-d["before"], d["id"]))
    table_dried = [{"name": d["name"], "before": num(d["before"]), "last_flow": hy_label(d["last_flow"]),
                    "k": f"{d['k']:,}"} for d in dried[:TABLE_ROWS]]

    # Top springs by median annual volume -------------------------------
    span = m.groupby("id")["y"].agg(["min", "max"])
    top = base.reset_index().sort_values(["median", "id"], ascending=[False, True]).head(TOP_N)
    chart_top = {"names": [names.get(i, i) for i in top["id"]],
                 "y": [round(float(v), 1) for v in top["median"]]}
    table_top = [{"name": names.get(r["id"], r["id"]), "median": num(r["median"]),
                  "n": f"{int(r['size']):,}",
                  "span": f"{hy_label(int(span.loc[r['id'], 'min']))} עד {hy_label(int(span.loc[r['id'], 'max']))}"}
                 for _, r in top.iterrows()]

    # Insights ------------------------------------------------------------
    def ins_latest():
        order = sorted(idx_years, key=lambda y: (float(idx.loc[y, "median"]), y))
        rank_low = order.index(L) + 1
        rank_high = len(order) - rank_low + 1
        head = f"ב-{lab_L} עמדה השפיעה של המעיין הטיפוסי על {pct(idx_L)} מהרגיל שלו ({n_L} מעיינות נמדדו)"
        if rank_low == 1:
            return f"{head} — השנה היבשה ביותר מבין {len(order)} השנים במדד, מאז {hy_label(idx_years[0])}."
        if rank_low <= 5:
            return f"{head} — המקום ה-{rank_low} מבין השנים היבשות ביותר מתוך {len(order)} השנים במדד."
        if rank_high <= 5:
            return f"{head} — המקום ה-{rank_high} מבין השנים השופעות ביותר מתוך {len(order)} השנים במדד."
        word = "מעל" if idx_L > 1 else "מתחת ל"
        return f"{head}, {word}רגיל."

    def ins_drought_run():
        runs = [r for r in _runs(idx_years, [float(idx.loc[y, "median"]) < DROUGHT for y in idx_years])
                if len(r) >= MIN_RUN]
        if not runs:
            return None
        best = max(runs, key=lambda r: (len(r), r[-1]))
        lo_y = min(best, key=lambda y: (float(idx.loc[y, "median"]), y))
        return (f"רצף היובש הארוך ביותר במדד: {len(best)} שנים רצופות, {hy_label(best[0])} עד "
                f"{hy_label(best[-1])}, שבהן השפיעה הטיפוסית הייתה מתחת ל-{pct(DROUGHT)} מהרגיל "
                f"(השפל ברצף: {pct(float(idx.loc[lo_y, 'median']))} ב-{hy_label(lo_y)}).")

    def ins_dry_share():
        recent = idx_years[-LATE_SPAN:]
        earlier = idx_years[:-LATE_SPAN]
        if len(earlier) < LATE_SPAN:
            return None
        dry_r = sum(float(idx.loc[y, "median"]) < DROUGHT for y in recent)
        dry_e = sum(float(idx.loc[y, "median"]) < DROUGHT for y in earlier)
        sr, se = dry_r / len(recent), dry_e / len(earlier)
        if abs(sr - se) < 0.10:
            return None
        word = "יותר" if sr > se else "פחות"
        return (f"ב-{dry_r} מתוך {len(recent)} השנים האחרונות במדד ({hy_label(recent[0])} עד {lab_L}) "
                f"השפיעה הטיפוסית ירדה מתחת ל-{pct(DROUGHT)} מהרגיל — {pct(sr)}, {word} מאשר "
                f"ב-{len(earlier)} השנים שקדמו להן ({pct(se)}).")

    def ins_wettest():
        y = max(idx_years, key=lambda y: (float(idx.loc[y, "median"]), y))
        return (f"השנה השופעת ביותר במדד: {hy_label(y)}, עם {pct(float(idx.loc[y, 'median']))} "
                f"מהרגיל ({int(idx.loc[y, 'size'])} מעיינות).")

    def ins_largest():
        if latest.empty:
            return None
        r = latest.iloc[0]
        series = mb[mb["id"] == r["id"]].sort_values("y")
        prev = series[series["y"] < L]
        if len(prev) < MIN_BASE_YEARS:
            return None
        lower_or_eq = prev[prev["vol"] <= r["vol"]]
        if lower_or_eq.empty:
            tail = f"הנמוך ביותר מאז תחילת המדידה ב-{hy_label(int(prev['y'].min()))}"
        else:
            tail = f"הנמוך ביותר מאז {hy_label(int(lower_or_eq['y'].max()))}"
        if r["r"] >= 1:
            higher = prev[prev["vol"] >= r["vol"]]
            tail = ("הגבוה ביותר מאז תחילת המדידה" if higher.empty
                    else f"הגבוה ביותר מאז {hy_label(int(higher['y'].max()))}")
        return (f"{r['name']}, הגדול במעיינות שנמדדו ב-{lab_L}, הזרים {num(r['vol'])} אלמ״ק — "
                f"{pct(r['r'])} מהחציון הרב-שנתי שלו ({num(r['base'])} אלמ״ק), {tail}.")

    def ins_records():
        hits = []
        for i, g in mb[mb["id"].isin(latest["id"])].groupby("id"):
            prev = g[g["y"] < L]["vol"]
            if len(prev) + 1 < RECORD_MIN_YEARS:
                continue
            cur = float(g[g["y"] == L]["vol"].iloc[0])
            if cur < float(prev.min()):
                hits.append((float(base.loc[i, "median"]), i))
        if not hits:
            return None
        hits.sort(key=lambda t: (-t[0], t[1]))
        nm = ", ".join(names.get(i, i) for _, i in hits[:3])
        return (f"ב-{lab_L} נרשם שפל של כל הזמנים ב-{len(hits)} מעיינות שיש להם לפחות "
                f"{RECORD_MIN_YEARS} שנות מדידה, ביניהם {nm}.")

    def ins_change():
        if len(ch) < 10:
            return None
        dec = int((ch["chg"] < -0.2).sum())
        inc = int((ch["chg"] > 0.2).sum())
        med = float(ch["chg"].median())
        return (f"מתוך {len(ch)} מעיינות שנמדדו גם ב-{early_lab} וגם ב-{late_lab}, ב-{dec} "
                f"({pct(dec / len(ch))}) הנפח החציוני ירד ביותר מ-20%, "
                + ("ובאף אחד מהם לא עלה ביותר מ-20%. " if inc == 0 else
                   f"וב-{inc}{' בלבד' if inc * 2 < dec else ''} עלה ביותר מ-20%. ") +
                f"השינוי החציוני: {signed_pct(med)}.")

    def ins_network():
        if n_L >= 0.5 * peak_n:
            return None
        return (f"רשת המדידה הצטמצמה: בשיאה, ב-{hy_label(peak_y)}, נמדדו {peak_n} מעיינות, "
                f"וב-{lab_L} — {n_L}. לכן סכומים וממוצעים ארציים משקפים בעיקר את הרכב הרשת; "
                f"המדד בעמוד משווה כל מעיין לחציון שלו.")

    def ins_dried():
        if not dried:
            return None
        nm = ", ".join(d["name"] for d in dried[:3])
        return (f"{len(dried)} מעיינות שזרמו בעבר נרשמו בנפח אפס ב-{DRY_STREAK} מדידות רצופות לפחות, "
                f"עד המדידה האחרונה שלהם, ביניהם {nm}.")

    def ins_region():
        if len(reg_L) < 2:
            return None
        s = reg_L.reset_index().sort_values(["median", "region"])
        lo, hi = s.iloc[0], s.iloc[-1]
        if float(hi["median"]) - float(lo["median"]) < 0.2:
            return None
        return (f"הפער האזורי ב-{lab_L}: באזור {lo['region']} השפיעה הטיפוסית הייתה {pct(lo['median'])} "
                f"מהרגיל ({int(lo['size'])} מעיינות), ובאזור {hi['region']} — {pct(hi['median'])} "
                f"({int(hi['size'])} מעיינות).")

    rules = [("latest", ins_latest()), ("largest", ins_largest()), ("records", ins_records()),
             ("region", ins_region()), ("change", ins_change()), ("drought_run", ins_drought_run()),
             ("dry_share", ins_dry_share()), ("wettest", ins_wettest()), ("dried", ins_dried()),
             ("network", ins_network())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # KPIs ------------------------------------------------------------------
    big = latest.iloc[0] if not latest.empty else None
    zero_L = int(((m["y"] == L) & (m["vol"] == 0)).sum())
    kpis = {
        "index": {"value": round(idx_L, 4), "display": pct(idx_L), "tone": kpi_tone(idx_L)},
        "largest": {"value": None if big is None else float(big["vol"]),
                    "display": "—" if big is None else num(big["vol"]),
                    "tone": "brand" if big is None else kpi_tone(float(big["r"]))},
        "dry": {"value": zero_L, "display": f"{zero_L:,}", "tone": "warn" if zero_L > 0 else "ok"},
        "springs": {"value": n_springs, "display": f"{n_springs:,}", "tone": "brand"},
    }
    kpi_labels = {
        "index": f"שפיעת המעיין הטיפוסי ב-{lab_L}, באחוזים מהרגיל שלו",
        "largest": ("" if big is None else
                    f"נפח {big['name']} ב-{lab_L} (אלמ״ק), {pct(big['r'])} מהחציון"),
        "dry": f"מעיינות בנפח אפס ב-{lab_L}, מתוך {n_L} שנמדדו",
        "springs": f"מעיינות עם נתוני נפח, {hy_label(y_first)} עד {hy_label(y_last_any)}",
    }

    # Labels --------------------------------------------------------------
    filt = ""
    if bad_year:
        filt = (" רשומה אחת עם שנה הידרולוגית לא תקינה לא נכללה." if bad_year == 1 else
                f" {bad_year} רשומות עם שנה הידרולוגית לא תקינה לא נכללו.")
    labels = {
        "lede": (f"המאגר מונה {n_ids:,} מעיינות; ל-{n_springs:,} מהם יש נפחי שפיעה שנתיים שמדד השירות ההידרולוגי, "
                 f"מ-{hy_label(y_first)} ועד {lab_L}, באלפי מטרים מעוקבים (אלמ״ק). "
                 f"{len(m):,} מתוך {n_rows:,} השורות במאגר מכילות נפח; השאר הן שנים שבהן המעיין לא נמדד. "
                 f"ב-{lab_L} השפיעה של המעיין הטיפוסי עמדה על {pct(idx_L)} מהרגיל.{filt}"),
        "index_note": (f"לכל מעיין עם {MIN_BASE_YEARS} שנות מדידה לפחות מחושב החציון הרב-שנתי שלו; "
                       f"הנפח בכל שנה מחולק בחציון הזה, והמדד הוא החציון של היחסים בין המעיינות שנמדדו "
                       f"באותה שנה. {pct(1)} = שנה רגילה. נכללות שנים עם {MIN_INDEX_SPRINGS} מעיינות לפחות. "
                       f"אדום: מתחת ל-{pct(DROUGHT)}; כחול כהה: {pct(WET)} ומעלה.{later_note}"),
        "index_aria": (f"תרשים עמודות: מדד השפיעה של המעיין הטיפוסי, {hy_label(idx_years[0])} עד {lab_L}. "
                       f"ב-{lab_L}: {pct(idx_L)} מהרגיל."),
        "index_caption": f"מדד השפיעה ב-{len(table_index)} השנים האחרונות במדד (באחוזים מהרגיל).",
        "network_aria": (f"תרשים עמודות נערמות: מספר המעיינות שנמדדו בכל שנה לפי סוג הנתון. "
                         f"שיא של {peak_n} ב-{hy_label(peak_y)}, {n_L} ב-{lab_L}."),
        "network_note": ("כמה מעיינות נמדדו בכל שנה, ואיך נקבע הנפח: מחושב ממדידות, הערכה, "
                         "או ערך שנלקח מהשנתון הרב-שנתי. "
                         + "; ".join(f"{t}: {c:,} רשומות" for t, c in type_tot.items()) + "."),
        "latest_aria": (f"תרשים עמודות אופקי: הנפח ב-{lab_L} באחוזים מהחציון הרב-שנתי, "
                        f"ב-{len(latest_top)} המעיינות הגדולים שנמדדו בשנה זו."),
        "latest_note": (f"{len(latest_top)} המעיינות הגדולים (לפי החציון הרב-שנתי) מתוך {len(latest)} "
                        f"שנמדדו ב-{lab_L} ויש להם חציון. {pct(1)} = שנה רגילה למעיין."),
        "latest_caption": f"נפח ב-{lab_L} לעומת החציון הרב-שנתי, אלמ״ק.",
        "major_aria": (f"גרפים קטנים: הנפח השנתי של {len(major)} מעיינות גדולים לאורך שנות המדידה, "
                       f"עם קו החציון הרב-שנתי של כל אחד."),
        "major_caption": f"נפח שנתי (אלמ״ק) של {len(major)} מעיינות גדולים: חציון, {lab_L}, שפל ושיא.",
        "region_aria": (f"מפת חום: מדד השפיעה לפי אזור ועשור, {len(regs)} אזורים ו-{len(decs)} עשורים."),
        "region_note": (f"החציון של יחס הנפח לרגיל בכל אזור ועשור (באחוזים). האזור נגזר מקוד האגן שבראש "
                        f"מספר הזיהוי של המעיין. תא נכלל כשיש בו {MIN_DECADE_OBS} שנות-מעיין לפחות. "
                        f"העמודה האחרונה בטבלה: {lab_L}, באזורים עם {MIN_REGION_LATEST} מעיינות לפחות."
                        + ("" if not n_other else " מעיין אחד שקוד האגן שלו לא שויך לאזור אינו מוצג." if n_other == 1
                           else f" {n_other} מעיינות שקוד האגן שלהם לא שויך לאזור אינם מוצגים.")),
        "region_caption": "מדד השפיעה לפי אזור ועשור (באחוזים מהרגיל).",
        "change_aria": (f"תרשים עמודות אופקי: השינוי בנפח החציוני בין {early_lab} לבין {late_lab}, "
                        f"ב-{len(ch_top)} המעיינות הגדולים שנמדדו בשתי התקופות."),
        "change_note": (f"החציון של כל מעיין בשתי תקופות של {LATE_SPAN} שנה: {early_lab} לעומת {late_lab}. "
                        f"נכללים מעיינות עם {MIN_WINDOW_YEARS} מדידות לפחות בכל תקופה; מוצגים {len(ch_top)} "
                        f"הגדולים מתוך {len(ch)}."),
        "change_caption": f"נפח חציוני (אלמ״ק) ב-{early_lab} וב-{late_lab}.",
        "dry_aria": (f"תרשים: מספר המעיינות שנרשם בהם נפח אפס בכל שנה ושיעורם מהמעיינות שנמדדו. "
                     f"ב-{lab_L}: {zero_L}."),
        "dry_note": (f"נכללות שנים עם {MIN_INDEX_SPRINGS} מעיינות נמדדים לפחות. הקו: שיעור המעיינות "
                     f"היבשים מכלל המעיינות שנמדדו באותה שנה."),
        "dry_caption": f"מעיינות בנפח אפס ב-{len(table_dry)} השנים האחרונות.",
        "dried_note": (f"מעיינות שהחציון שלהם לפני היובש היה {num(MIN_BASE_VOL)} אלמ״ק לפחות, "
                       f"ו-{DRY_STREAK} המדידות האחרונות שלהם לפחות נרשמו בנפח אפס "
                       f"(מדידה אחרונה ב-{DRY_RECENT} השנים האחרונות בנתונים). {len(dried)} מעיינות."),
        "dried_caption": "מעיינות שזרמו בעבר ונרשמו לאחרונה בנפח אפס.",
        "top_aria": (f"תרשים עמודות אופקי: {len(top)} המעיינות בעלי הנפח השנתי החציוני הגבוה ביותר."),
        "top_note": (f"חציון הנפח השנתי של כל מעיין לאורך כל שנות המדידה שלו ({MIN_BASE_YEARS} שנים לפחות). "
                     f"רשומות \"סכום\" ו\"סיכום\" הן סך של קבוצת נביעות כפי שפורסם."),
        "top_caption": f"{len(top)} המעיינות בעלי הנפח השנתי החציוני הגבוה ביותר.",
    }

    return {
        "agent_data": {
            "summary_he": (f"נפחי שפיעה שנתיים של {n_springs:,} מעיינות בישראל מ-{hy_label(y_first)} "
                           f"ועד {lab_L}. ב-{lab_L} השפיעה של המעיין הטיפוסי עמדה על {pct(idx_L)} "
                           f"מהרגיל שלו."),
            "dataset_kind": "timeseries",
            "related_ids": [
                "9b0286dd-aaa4-4dc6-9878-9c65abbee66e",
                "25862093-583b-43c4-b637-531645cf3955",
                "a53613b2-f5da-48d1-86d8-1a8094c568af",
                "5de14d12-d5d7-475d-ade1-5dbd0ef9d086",
                "2706952a-a86d-4887-a6a6-6e42d91cba6c",
            ],
            "suggested_tags": ["מעיינות", "משאבי מים", "הידרולוגיה", "בצורת", "שפיעה"],
            "temporal_coverage": f"{y_first - 1}/{L}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_labels": kpi_labels,
        "charts": {
            "index": chart_index, "network": chart_network, "latest": chart_latest,
            "major": major, "region": chart_region, "change": chart_change,
            "dry": chart_dry, "top": chart_top,
        },
        "tables": {
            "index": table_index, "latest": table_latest, "major": table_major, "region": table_region,
            "change": table_change, "dry": table_dry, "dried": table_dried, "top": table_top,
        },
        "flags": {"dried": bool(table_dried), "major": bool(major)},
        "insights": insights,
        "labels": labels,
    }
