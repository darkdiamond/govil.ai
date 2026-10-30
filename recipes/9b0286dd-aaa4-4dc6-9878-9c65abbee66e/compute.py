"""מעיינות - נפחים חודשיים: monthly discharge volume per spring (Hydrological Service).

Data: one row per (spring, month). Volume is in thousands of cubic metres
(אלמ"ק). An empty volume is a placeholder (the spring was not measured that
month). Months are "MM/YYYY"; the hydrological year runs October to
September and is keyed here by its END year (2024/2025 -> 2025).

The set of measured springs changes a lot over time, so national sums mostly
track the network. The page's headline series is a MONTHLY FLOW INDEX: each
spring-month's volume divided by that spring's own median for the same
calendar month, and the median of those ratios across the springs measured
that month. 100% = a normal month for the typical spring.

Rows whose Hebrew name contains "סיכום"/"סכום" are published totals of a
group of outlets (e.g. the Dan springs). They are excluded from counts,
rankings and the index (their members are listed too), but one may be the
"flagship" series when it is the largest complete record.

"Latest complete hydrological year" = the newest hydrological year whose
September is in the data. "Latest month" = the newest month in the data.
Never the wall clock.
"""
import re

import pandas as pd

C_ID, C_HE, C_EN, C_HY, C_MONTH, C_VOL = (
    "מספר זיהוי", "שם עברית", "שם אנגלית", "שנה הידרולוגית", "חודש שנה",
    "נפח חודשי למעיין (אלמ''ק)")

MIN_BASE_OBS = 10        # observations a spring needs for a same-month baseline
MIN_BASE_VOL = 1.0       # baseline median (אלמ"ק) below this: ratio is noise
MIN_INDEX_SPRINGS = 15   # springs a month needs to enter the flow index
DRY = 0.80               # index below this = a dry month
WET = 1.20               # index at/above this = a wet month
MIN_DRY_RUN = 3          # trailing dry months worth an insight
ZOOM_MONTHS = 240        # index chart opens on the latest 20 years
MIN_COMPLETE_YEARS = 10  # complete hydro years for a flagship / profile spring
MIN_PEAK_YEARS = 5       # complete hydro years for the peak-month census
TOP_N = 15
SEASON_N = 6
DRY_YEARS = 20           # rows of the dry-months chart/table
SUM_RE = re.compile(r"סיכום|סכום")

# Hydrological month order: October .. September.
HYDRO_MONTHS = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
MONTH_HE = {1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל", 5: "מאי", 6: "יוני",
            7: "יולי", 8: "אוגוסט", 9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר", 12: "דצמבר"}
HM_LABELS = [MONTH_HE[mo] for mo in HYDRO_MONTHS]
MONTH_RE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{4})\s*$")


def hy_label(y):
    return f"{y - 1}/{str(y)[-2:]}"


def pct(r):
    return f"{r * 100:.0f}%"


def num(v):
    return f"{v:,.0f}"


def tone(r):
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
    s = " ".join(str(s).split())
    return s.replace("( ", "(").replace(" )", ")")


def _parse_month(s):
    m = MONTH_RE.match(str(s))
    if not m:
        return None
    mo, y = int(m.group(1)), int(m.group(2))
    if not 1 <= mo <= 12:
        return None
    return y * 12 + (mo - 1)


def mlabel(k):
    return f"{MONTH_HE[k % 12 + 1]} {k // 12}"


def mshort(k):
    return f"{k % 12 + 1:02d}/{k // 12}"


def _prepare(df):
    out = pd.DataFrame({
        "id": df[C_ID].astype(str).str.strip(),
        "name": df[C_HE].astype(str).map(_clean_name),
        "k": df[C_MONTH].astype(str).map(_parse_month),
        "vol": pd.to_numeric(df[C_VOL].astype(str).str.replace(",", "", regex=False).str.strip(),
                             errors="coerce"),
    })
    out = out[out["id"] != ""]
    names = out[out["name"] != ""].groupby("id")["name"].min()
    measured = out.dropna(subset=["vol"])
    bad = int(measured["k"].isna().sum())
    m = measured.dropna(subset=["k"]).copy()
    m = m[m["vol"] >= 0]
    m["k"] = m["k"].astype(int)
    m = (m.sort_values(["id", "k", "vol"], kind="mergesort")
          .drop_duplicates(["id", "k"], keep="first").reset_index(drop=True))
    m["name"] = m["id"].map(names).fillna(m["id"])
    m["mo"] = m["k"] % 12 + 1
    m["cy"] = m["k"] // 12
    m["y"] = m["cy"] + (m["mo"] >= 10).astype(int)          # hydro end year
    m["hm"] = m["mo"].map({mo: i for i, mo in enumerate(HYDRO_MONTHS)})
    m["is_sum"] = m["name"].map(lambda s: bool(SUM_RE.search(s)))
    return out, m, names, bad


def _runs_tail(flags):
    n = 0
    for f in reversed(flags):
        if not f:
            break
        n += 1
    return n


def compute(frames):
    raw, m_all, names, bad = _prepare(frames["main"])
    n_rows = len(raw)
    sum_ids = sorted(i for i, nm in names.items() if SUM_RE.search(nm))
    m = m_all[~m_all["is_sum"]].copy()                      # individual springs
    n_ids = len(set(raw["id"]) - set(sum_ids))
    n_springs = int(m["id"].nunique())
    k_first, k_last = int(m_all["k"].min()), int(m_all["k"].max())
    y_first = int(m_all["y"].min())
    last_mo = k_last % 12 + 1
    y_last = int(m_all["y"].max())
    L = y_last if last_mo == 9 else y_last - 1               # latest complete hydro year
    partial = None if L == y_last else y_last
    lab_L = hy_label(L)

    # Same-calendar-month baselines --------------------------------------
    base = m.groupby(["id", "mo"])["vol"].agg(["median", "size"])
    base = base[(base["size"] >= MIN_BASE_OBS) & (base["median"] >= MIN_BASE_VOL)]
    mb = m.join(base.rename(columns={"median": "base", "size": "bn"}), on=["id", "mo"], how="inner")
    mb["r"] = mb["vol"] / mb["base"]
    idx = mb.groupby("k")["r"].agg(["median", "size"])
    idx = idx[idx["size"] >= MIN_INDEX_SPRINGS].sort_index()
    idx_ks = [int(k) for k in idx.index]
    roll = idx["median"].rolling(12, min_periods=12).median()
    chart_index = {
        "x": [mshort(k) for k in idx_ks],
        "y": [round(float(v) * 100, 1) for v in idx["median"]],
        "roll": [None if pd.isna(v) else round(float(v) * 100, 1) for v in roll],
        "n": [int(v) for v in idx["size"]],
        "dry": round(DRY * 100), "wet": round(WET * 100),
        "zoom": max(0, round((1 - ZOOM_MONTHS / max(len(idx_ks), 1)) * 100, 1)),
    }
    K = idx_ks[-1]
    idx_K = float(idx.loc[K, "median"])

    # Measured-in-latest-month counts --------------------------------------
    m_last = m[m["k"] == k_last]
    n_last = int(len(m_last))
    zero_last = int((m_last["vol"] == 0).sum())

    # Complete hydro years per series (incl. published totals) ------------
    cnt = m_all.groupby(["id", "y"]).size()
    full = cnt[cnt == 12].reset_index()[["id", "y"]]
    ann = (m_all.merge(full, on=["id", "y"]).groupby(["id", "y"])["vol"].sum().rename("ann")
           .reset_index())
    ann_base = ann[ann["y"] < L].groupby("id")["ann"].agg(["median", "size"])
    ann_base = ann_base[ann_base["size"] >= MIN_COMPLETE_YEARS]
    ann_L = ann[ann["y"] == L].set_index("id")["ann"]

    # Flagship ---------------------------------------------------------------
    cand = ann_base[ann_base.index.isin(ann_L.index)].reset_index()
    cand = cand.sort_values(["median", "id"], ascending=[False, True])
    flag = None
    if len(cand):
        fid = cand.iloc[0]["id"]
        fname = names.get(fid, fid)
        f_med = float(cand.iloc[0]["median"])
        f_L = float(ann_L[fid])
        f_ann = ann[ann["id"] == fid].set_index("y")["ann"].sort_index()
        fm = m_all[m_all["id"] == fid]
        prev = fm[fm["y"] < L]
        band = []
        for i, mo in enumerate(HYDRO_MONTHS):
            s = prev.loc[prev["mo"] == mo, "vol"]
            cur = fm.loc[(fm["y"] == L) & (fm["mo"] == mo), "vol"]
            pre = fm.loc[(fm["y"] == L - 1) & (fm["mo"] == mo), "vol"]
            band.append({
                "p10": round(float(s.quantile(0.1)), 1) if len(s) else None,
                "med": round(float(s.median()), 1) if len(s) else None,
                "p90": round(float(s.quantile(0.9)), 1) if len(s) else None,
                "cur": round(float(cur.iloc[0]), 1) if len(cur) else None,
                "pre": round(float(pre.iloc[0]), 1) if len(pre) else None,
            })
        below_p10 = sum(1 for b in band if b["cur"] is not None and b["p10"] is not None
                        and b["cur"] < b["p10"])
        # heatmap: hydro year x hydro month
        hy = sorted(int(y) for y in fm["y"].unique())
        cells = [[int(r.hm), hy.index(int(r.y)), round(float(r.vol), 1)]
                 for r in fm.sort_values(["y", "hm"]).itertuples()]
        lower = f_ann[(f_ann.index < L) & (f_ann <= f_L)]
        flag = {
            "id": fid, "name": fname, "median": f_med, "L": f_L, "r": f_L / f_med,
            "n_years": int(cand.iloc[0]["size"]),
            "first": int(f_ann.index.min()),
            "lowest_since": int(lower.index.max()) if len(lower) else None,
            "band": band, "below_p10": below_p10, "years": hy, "cells": cells,
            "vmax": round(float(fm["vol"].quantile(0.98)), 1),
        }

    # Latest year vs normal, by month (comparable springs) ------------------
    full_L = set(full.loc[full["y"] == L, "id"]) - set(sum_ids)
    cmp = mb[(mb["y"] == L) & (mb["id"].isin(full_L))]
    ok_ids = cmp.groupby("id").size()
    ok_ids = sorted(ok_ids[ok_ids == 12].index)
    cmp = cmp[cmp["id"].isin(ok_ids)]
    by_hm = cmp.groupby("hm")[["vol", "base"]].sum()
    chart_lvn = {
        "x": HM_LABELS,
        "cur": [round(float(by_hm.loc[i, "vol"]), 1) if i in by_hm.index else None for i in range(12)],
        "norm": [round(float(by_hm.loc[i, "base"]), 1) if i in by_hm.index else None for i in range(12)],
        "n": len(ok_ids),
    }
    lvn_tot = float(by_hm["vol"].sum()) if len(by_hm) else 0.0
    lvn_norm = float(by_hm["base"].sum()) if len(by_hm) else 0.0
    table_lvn = [{"m": HM_LABELS[i], "cur": num(by_hm.loc[i, "vol"]), "norm": num(by_hm.loc[i, "base"]),
                  "pct": pct(by_hm.loc[i, "vol"] / by_hm.loc[i, "base"]) if by_hm.loc[i, "base"] > 0 else "אין נתון"}
                 for i in range(12) if i in by_hm.index]

    # Top springs in L --------------------------------------------------------
    ind_base = ann[(ann["y"] < L)].groupby("id")["ann"].agg(["median", "size"])
    ind_base = ind_base[ind_base["size"] >= MIN_PEAK_YEARS]
    topL = ann_L[ann_L.index.isin(full_L)].rename("vol").reset_index()
    topL = topL.sort_values(["vol", "id"], ascending=[False, True])
    total_L = float(topL["vol"].sum())
    top = topL.head(TOP_N)
    chart_top = {
        "names": [names.get(i, i) for i in top["id"]],
        "vol": [round(float(v), 1) for v in top["vol"]],
        "med": [round(float(ind_base.loc[i, "median"]), 1) if i in ind_base.index else None
                for i in top["id"]],
    }
    table_top = [{"name": names.get(r.id, r.id), "vol": num(r.vol),
                  "med": num(ind_base.loc[r.id, "median"]) if r.id in ind_base.index else "אין נתון",
                  "pct": pct(r.vol / ind_base.loc[r.id, "median"])
                  if r.id in ind_base.index and ind_base.loc[r.id, "median"] > 0 else "אין נתון"}
                 for r in top.itertuples()]

    # Seasonal profiles --------------------------------------------------------
    ind_full = full[~full["id"].isin(sum_ids)]
    mf = m.merge(ind_full, on=["id", "y"])
    mf = mf.merge(ann[["id", "y", "ann"]], on=["id", "y"])
    mf = mf[mf["ann"] > 0]
    mf["share"] = mf["vol"] / mf["ann"]
    prof = mf.groupby(["id", "hm"])["share"].median().unstack("hm")
    nyrs = mf.groupby("id")["y"].nunique()
    medann = ann[~ann["id"].isin(sum_ids)].groupby("id")["ann"].median()
    peak_ids = [i for i in prof.index if nyrs[i] >= MIN_PEAK_YEARS and medann.get(i, 0) >= 12 * MIN_BASE_VOL]
    peak_of = {}
    for i in sorted(peak_ids):
        row = prof.loc[i].reindex(range(12)).fillna(0).tolist()
        peak_of[i] = max(range(12), key=lambda h: (row[h], -h))
    peak_counts = [sum(1 for v in peak_of.values() if v == h) for h in range(12)]
    n_peak = len(peak_of)
    # amplitude: wettest / driest median share (steady vs flashy)
    season_ids = [i for i in cand["id"].tolist() if i not in sum_ids
                  and i in prof.index and nyrs[i] >= MIN_COMPLETE_YEARS][:SEASON_N]
    chart_season = {"x": HM_LABELS, "series": []}
    table_season = []
    for i in season_ids:
        row = prof.loc[i].reindex(range(12)).fillna(0).tolist()
        tot = sum(row) or 1.0
        sh = [round(v / tot * 100, 1) for v in row]
        chart_season["series"].append({"name": names.get(i, i), "data": sh})
        pk = max(range(12), key=lambda h: (sh[h], -h))
        lo = min(range(12), key=lambda h: (sh[h], h))
        table_season.append({"name": names.get(i, i), "peak": f"{HM_LABELS[pk]} ({sh[pk]:.1f}%)",
                             "low": f"{HM_LABELS[lo]} ({sh[lo]:.1f}%)",
                             "ratio": f"{sh[pk] / sh[lo]:.1f}" if sh[lo] > 0 else "אין נתון"})

    # Dry spring-months by hydro year ---------------------------------------
    yy = m.groupby("y").agg(n=("vol", "size"), z=("vol", lambda s: int((s == 0).sum())),
                            springs=("id", "nunique"))
    zs = m[m["vol"] == 0].groupby("y")["id"].nunique()
    yy["zs"] = zs.reindex(yy.index).fillna(0).astype(int)
    yy = yy[(yy["springs"] >= MIN_INDEX_SPRINGS) & (yy.index <= L)].tail(DRY_YEARS)
    chart_dry = {"x": [hy_label(int(y)) for y in yy.index],
                 "zs": [int(v) for v in yy["zs"]],
                 "share": [round(float(z) / float(n) * 100, 1) for z, n in zip(yy["z"], yy["n"])]}
    table_dry = [{"year": hy_label(int(y)), "springs": f"{int(r['springs']):,}", "zs": f"{int(r['zs']):,}",
                  "share": f"{r['z'] / r['n'] * 100:.1f}%"} for y, r in yy.iterrows()]
    dry_all_L = sorted(i for i, g in m[m["y"] == L].groupby("id")
                       if len(g) == 12 and (g["vol"] == 0).all())

    # Insights -------------------------------------------------------------
    def ins_month():
        same = [k for k in idx_ks if k % 12 == K % 12]
        if len(same) < 10:
            return None
        order = sorted(same, key=lambda k: (float(idx.loc[k, "median"]), -k))
        rank_low = order.index(K) + 1
        head = (f"ב{mlabel(K)} עמדה השפיעה של המעיין הטיפוסי על {pct(idx_K)} מהרגיל שלו לחודש זה "
                f"({int(idx.loc[K, 'size'])} מעיינות)")
        if rank_low == 1:
            return f"{head}, הנמוכה ביותר ל{MONTH_HE[K % 12 + 1]} מבין {len(same)} השנים במדד."
        if rank_low <= 3:
            return f"{head}, המקום ה-{rank_low} מבין החודשים היבשים ביותר ל{MONTH_HE[K % 12 + 1]} מתוך {len(same)} שנים."
        higher = [k for k in same if k < K and float(idx.loc[k, "median"]) <= idx_K]
        if idx_K < 1 and higher:
            return f"{head}, הנמוכה ביותר ל{MONTH_HE[K % 12 + 1]} מאז {max(higher) // 12}."
        return f"{head}."

    def ins_run():
        flags = [float(idx.loc[k, "median"]) < DRY for k in idx_ks]
        n = _runs_tail(flags)
        if n < MIN_DRY_RUN:
            return None
        k0 = idx_ks[len(idx_ks) - n]
        return (f"זה {n} חודשים ברציפות, מ{mlabel(k0)} ועד {mlabel(K)}, שהשפיעה הטיפוסית נמוכה "
                f"מ-{pct(DRY)} מהרגיל.")

    def ins_flag():
        if not flag:
            return None
        if flag["r"] < 1:
            tail = (f"הנמוך ביותר מאז {hy_label(flag['lowest_since'])}" if flag["lowest_since"]
                    else f"השנה הנמוכה ביותר מאז תחילת הרשומה ב-{hy_label(flag['first'])}")
        else:
            tail = "מעל החציון"
        return (f"{flag['name']}: {num(flag['L'])} אלמ״ק ב-{lab_L}, {pct(flag['r'])} מהחציון השנתי "
                f"({num(flag['median'])} אלמ״ק, {flag['n_years']} שנים מלאות), {tail}.")

    def ins_band():
        if not flag or flag["below_p10"] < 3:
            return None
        return (f"ב-{flag['below_p10']} מתוך 12 חודשי {lab_L} השפיעה של {flag['name']} הייתה נמוכה "
                f"מהעשירון התחתון של אותו חודש בשנים הקודמות.")

    def ins_lvn():
        if len(ok_ids) < 10 or lvn_norm <= 0:
            return None
        rat = (by_hm["vol"] / by_hm["base"]).where(by_hm["base"] > 0)
        worst = min(rat.dropna().index, key=lambda h: (float(rat[h]), h))
        return (f"{len(ok_ids)} מעיינות שנמדדו בכל חודשי {lab_L} ויש להם חציון רב-שנתי לכל חודש הזרימו יחד {num(lvn_tot)} אלמ״ק, "
                f"{pct(lvn_tot / lvn_norm)} מסכום החציונים החודשיים שלהם. הפער הגדול ביותר "
                f"ב{HM_LABELS[worst]}: {pct(float(rat[worst]))} מהרגיל.")

    def ins_peak():
        if n_peak < 20:
            return None
        h = max(range(12), key=lambda i: (peak_counts[i], -i))
        sh = peak_counts[h] / n_peak
        if sh < 0.2:
            return None
        spring_win = sum(peak_counts[i] for i in range(4, 8))   # Feb..May
        return (f"השיא העונתי: ב-{peak_counts[h]} מתוך {n_peak} מעיינות ({pct(sh)}) החודש השופע ביותר "
                f"הוא {HM_LABELS[h]}; {spring_win} ({pct(spring_win / n_peak)}) מגיעים לשיא בין פברואר למאי.")

    def ins_top():
        if len(topL) < 10 or total_L <= 0:
            return None
        t3 = topL.head(3)
        s3 = float(t3["vol"].sum()) / total_L
        nm = ", ".join(names.get(i, i) for i in t3["id"])
        return (f"ריכוזיות: שלושת המעיינות הגדולים ב-{lab_L} ({nm}) הזרימו {pct(s3)} מהנפח של "
                f"{len(topL)} המעיינות שנמדדו בכל חודשי השנה.")

    def ins_dry():
        if not len(yy) or int(yy.index[-1]) != L:
            return None
        r = yy.loc[L]
        if int(r["zs"]) == 0:
            return None
        tail = (f", ו-{len(dry_all_L)} מהם יבשים בכל שנים-עשר החודשים" if dry_all_L else "")
        return (f"ב-{lab_L} נרשם נפח אפס בחודש אחד לפחות ב-{int(r['zs'])} מתוך {int(r['springs'])} "
                f"מעיינות שנמדדו{tail}.")

    rules = [("month", ins_month()), ("run", ins_run()), ("flagship", ins_flag()), ("band", ins_band()),
             ("lvn", ins_lvn()), ("peak", ins_peak()), ("top", ins_top()), ("dry", ins_dry())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # KPIs -------------------------------------------------------------------
    kpis = {
        "index": {"value": round(idx_K, 4), "display": pct(idx_K), "tone": tone(idx_K)},
        "flagship": ({"value": round(flag["r"], 4), "display": pct(flag["r"]), "tone": tone(flag["r"])}
                     if flag else {"value": n_springs, "display": f"{n_springs:,}", "tone": "brand"}),
        "measured": {"value": n_last, "display": f"{n_last:,}", "tone": "brand"},
        "zero": {"value": zero_last, "display": f"{zero_last:,}", "tone": "warn" if zero_last else "ok"},
    }
    kpi_labels = {
        "index": f"שפיעת המעיין הטיפוסי ב{mlabel(K)}, באחוזים מהרגיל לחודש זה",
        "flagship": (f"נפח {flag['name']} ב-{lab_L}, באחוזים מהחציון השנתי" if flag else
                     "מעיינות עם נתוני נפח"),
        "measured": f"מעיינות שנמדדו ב{mlabel(k_last)}",
        "zero": f"מתוכם בנפח אפס (יבשים) ב{mlabel(k_last)}",
    }

    filt = ""
    if bad:
        filt = f" {bad:,} רשומות עם חודש לא תקין לא נכללו."
    partial_note = ""
    if partial:
        n_mo = int(m_all.loc[m_all["y"] == partial, "k"].nunique())
        partial_note = (f" השנה {hy_label(partial)} חלקית בנתונים ({n_mo} חודשים) ולכן ההשוואות השנתיות "
                        f"נעשות ל-{lab_L}.")
    sums_note = (f"{len(sum_ids)} רשומות \"סיכום\" (סך של קבוצת נביעות, למשל {names.get(sum_ids[0], sum_ids[0])}) "
                 f"אינן נספרות כמעיינות נפרדים ואינן נכללות במדד ובדירוגים." if sum_ids else "")

    labels = {
        "lede": (f"נפחי השפיעה החודשיים של מעיינות ישראל, כפי שמודד השירות ההידרולוגי ברשות המים: "
                 f"{n_ids:,} מעיינות במאגר, ול-{n_springs:,} מהם יש לפחות מדידה חודשית אחת, "
                 f"מ{mlabel(k_first)} ועד {mlabel(k_last)}. הנפחים באלפי מטרים מעוקבים (אלמ״ק); "
                 f"השנה ההידרולוגית נמשכת מאוקטובר עד ספטמבר. {len(m_all):,} מתוך {n_rows:,} השורות "
                 f"מכילות נפח, והשאר הן חודשים שבהם המעיין לא נמדד. {sums_note}{partial_note}{filt}"),
        "index_note": (f"לכל מעיין ולכל חודש בשנה מחושב החציון הרב-שנתי (לפחות {MIN_BASE_OBS} מדידות). "
                       f"הנפח בכל חודש מחולק בחציון של אותו חודש, והמדד הוא החציון של היחסים בין המעיינות "
                       f"שנמדדו. {pct(1)} = חודש רגיל. נכללים חודשים עם {MIN_INDEX_SPRINGS} מעיינות לפחות. "
                       f"הקו הכהה: חציון נע של שנים-עשר חודשים. נקודה אדומה: חודש שחון, מתחת ל-{pct(DRY)}."),
        "index_aria": (f"תרשים קו: מדד השפיעה החודשי של המעיין הטיפוסי, {mlabel(idx_ks[0])} עד {mlabel(K)}. "
                       f"בחודש האחרון: {pct(idx_K)} מהרגיל."),
        "lvn_note": (f"{len(ok_ids)} מעיינות שנמדדו בכל חודשי {lab_L} ויש להם חציון לכל חודש: סכום הנפח "
                     f"שלהם בכל חודש לעומת סכום החציונים הרב-שנתיים של אותו חודש."),
        "lvn_aria": (f"תרשים עמודות: נפח חודשי ב-{lab_L} לעומת הרגיל, {len(ok_ids)} מעיינות. "
                     f"סך השנה: {pct(lvn_tot / lvn_norm) if lvn_norm > 0 else 'אין נתון'} מהרגיל."),
        "lvn_caption": f"נפח חודשי (אלמ״ק) ב-{lab_L} לעומת סכום החציונים.",
        "top_note": (f"{len(top)} המעיינות בעלי הנפח הגדול ביותר ב-{lab_L}, מתוך {len(topL)} שנמדדו בכל "
                     f"חודשי השנה. הנקודה: החציון השנתי של המעיין בשנים קודמות ({MIN_PEAK_YEARS} שנים מלאות לפחות)."),
        "top_aria": f"תרשים עמודות אופקי: {len(top)} המעיינות הגדולים ב-{lab_L} והחציון השנתי שלהם.",
        "top_caption": f"נפח שנתי ב-{lab_L} וחציון רב-שנתי (אלמ״ק).",
        "season_note": (f"איזה חלק מהנפח השנתי זורם בכל חודש, ב-{len(season_ids)} המעיינות הגדולים "
                        f"(חציון על פני השנים המלאות, מנורמל לסך של {pct(1)})."),
        "season_aria": f"תרשים קווים: חלוקת הנפח השנתי לפי חודש ב-{len(season_ids)} מעיינות גדולים.",
        "season_caption": "החודש השופע והחודש הדל ביותר, והיחס ביניהם.",
        "peak_note": (f"{n_peak} מעיינות עם {MIN_PEAK_YEARS} שנים מלאות לפחות, לפי החודש שבו זורם "
                      f"החלק הגדול ביותר מהנפח השנתי."),
        "peak_aria": f"תרשים עמודות: מספר המעיינות לפי חודש השיא העונתי, {n_peak} מעיינות.",
        "peak_caption": "מספר המעיינות לפי חודש השיא.",
        "dry_note": (f"{len(yy)} השנים ההידרולוגיות האחרונות: מספר המעיינות שנרשם בהם נפח אפס בחודש "
                     f"אחד לפחות, ושיעור חודשי-המעיין היבשים מכלל המדידות."),
        "dry_aria": f"תרשים: מעיינות עם חודש יבש ושיעור החודשים היבשים, {len(yy)} שנים.",
        "dry_caption": "מעיינות עם חודש יבש לפי שנה הידרולוגית.",
    }
    if flag:
        labels.update({
            "band_title": f"{flag['name']}: {lab_L} לעומת טווח השנים",
            "band_note": (f"הנפח החודשי של {flag['name']} (אלמ״ק), הסדרה המלאה הגדולה במאגר. הרצועה: "
                          f"בין העשירון התחתון לעליון של כל חודש בשנים שקדמו ל-{lab_L}."),
            "band_aria": (f"תרשים: נפח חודשי של {flag['name']} ב-{lab_L} ובשנה שקדמה, מול החציון "
                          f"והטווח הרב-שנתי."),
            "band_caption": f"{flag['name']}: נפח חודשי ב-{lab_L} מול החציון ורצועת העשירונים (אלמ״ק).",
            "heat_title": f"{flag['name']}: כל החודשים מאז {hy_label(flag['years'][0])}",
            "heat_note": "כל משבצת היא חודש אחד; צבע כהה = שפיעה גבוהה. השורות: שנים הידרולוגיות.",
            "heat_aria": (f"מפת חום: נפח חודשי של {flag['name']} לפי שנה הידרולוגית וחודש, "
                          f"{len(flag['years'])} שנים."),
        })

    chart_band = None
    table_band = []
    chart_heat = None
    if flag:
        chart_band = {"x": HM_LABELS, "cur_name": lab_L, "pre_name": hy_label(L - 1),
                      "p10": [b["p10"] for b in flag["band"]], "p90": [b["p90"] for b in flag["band"]],
                      "med": [b["med"] for b in flag["band"]], "cur": [b["cur"] for b in flag["band"]],
                      "pre": [b["pre"] for b in flag["band"]]}
        table_band = [{"m": HM_LABELS[i], "cur": num(b["cur"]) if b["cur"] is not None else "אין נתון",
                       "med": num(b["med"]) if b["med"] is not None else "אין נתון",
                       "rng": (f"{num(b['p10'])} עד {num(b['p90'])}" if b["p10"] is not None else "אין נתון")}
                      for i, b in enumerate(flag["band"])]
        chart_heat = {"x": HM_LABELS, "y": [hy_label(y) for y in flag["years"]], "cells": flag["cells"],
                      "vmax": flag["vmax"]}

    summary = (f"נפחי שפיעה חודשיים של {n_springs:,} מעיינות בישראל עד {mlabel(k_last)}. "
               f"ב{mlabel(K)} זרם המעיין הטיפוסי {pct(idx_K)} מהרגיל לחודש זה.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "related_ids": [
                "073cd24f-58b0-4301-b6df-3b09607dfd46",
                "25862093-583b-43c4-b637-531645cf3955",
                "a53613b2-f5da-48d1-86d8-1a8094c568af",
                "5de14d12-d5d7-475d-ade1-5dbd0ef9d086",
                "2706952a-a86d-4887-a6a6-6e42d91cba6c",
            ],
            "suggested_tags": ["מעיינות", "שפיעה", "הידרולוגיה", "משאבי מים", "בצורת", "עונתיות"],
            "temporal_coverage": f"{k_first // 12}/{k_last // 12}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_labels": kpi_labels,
        "charts": {"index": chart_index, "lvn": chart_lvn, "top": chart_top, "season": chart_season,
                   "peak": {"x": HM_LABELS, "y": peak_counts}, "dry": chart_dry,
                   "band": chart_band, "heat": chart_heat},
        "tables": {"lvn": table_lvn, "top": table_top, "season": table_season,
                   "peak": [{"m": HM_LABELS[i], "n": f"{peak_counts[i]:,}"} for i in range(12)],
                   "dry": table_dry, "band": table_band},
        "flags": {"flagship": bool(flag), "season": bool(season_ids), "lvn": len(ok_ids) > 0,
                  "top": len(top) > 0},
        "insights": insights,
        "labels": labels,
    }
