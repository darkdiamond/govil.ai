"""נפחים יומיים וספיקה יומית ממוצעת בתחנות: daily flow at the Hydrological
Service's stream gauging stations.

Data: one row per (station, day). Daily volume in cubic metres; the daily mean
discharge column is volume / 86,400 rounded to two decimals, so the recipe
derives discharge from the volume instead of fetching it twice. An empty volume
means the station did not record that day. The history is split into period
files (until 1960, 1960-1980, ..., 2020 onwards). The 1960-1980 file spells
its volume column "מטר קוב" instead of "מ''ק", so it is a separate input
(`early`); both inputs are `by_schema` + `concat`, so a new period file with
either spelling flows in.

Hydrological years run October to September; a year is keyed by its END year
here and labelled "YYYY/YYYY" as in the data.

The set of gauged stations changes a lot over time (1 in 1944, ~125 in 2015,
~110 now), and stations are nested along the same streams (the Jordan is
gauged at several points), so a national SUM of volumes is meaningless. The
headline series is a FLOW INDEX: each station's annual volume divided by that
station's own long-term median, and the median of those ratios across the
stations measured that year. 100% = a normal year for the typical station.

A station-year counts ("complete") only with >= MIN_DAYS recorded days, so a
partially published latest year never enters the index or the rankings.

Regions come from the station id: all but its last three digits are the
Hydrological Service drainage-basin code. Known codes map to a broad region;
unknown codes fall into "אזורים אחרים".
"""
import math

import numpy as np
import pandas as pd

C_ID = "זיהוי תחנה הידרומטרית"
C_NAME = "שם תחנה הידרומטרית"
C_DATE = "תאריך"
C_VOL = "נפח יומי (מ''ק)"
C_VOL_EARLY = "נפח יומי (מטר קוב)"

MIN_DAYS = 330            # recorded days for a complete station-year
MIN_BASE_YEARS = 10       # complete years a station needs for its own median
MIN_BASE_VOL = 10_000.0   # baseline median (m3/yr) below this: ratio is noise
MIN_INDEX_STATIONS = 10   # stations a year needs to enter the flow index
DRY = 0.80                # index below this = a dry year
VERY_DRY = 0.50
WET = 1.20                # index at/above this = a wet year
MIN_RUN = 3               # consecutive dry years that count as a drought run
HEAT_STATIONS = 20        # rows of the station x year heatmap
LATEST_TOP = 12           # stations in the latest-year ranking
PEAK_TOP = 10             # stations in the record-peak ranking
FLAG_MIN_YEARS = 20       # complete years the flagship station needs
RECENT_SPAN = 10          # flagship: latest N complete years vs earlier ones
TREND_MIN = 0.10          # relative change that counts as a shift
MIN_REGION_LATEST = 3     # baseline stations a region needs in the latest year
EPHEMERAL = 0.10          # flow on < 10% of recorded days
PERENNIAL = 0.90          # flow on >= 90% of recorded days
WINTER_MONTHS = (12, 1, 2, 3)
SUMMER_MONTHS = (6, 7, 8, 9)
SUMMER_GAP = 0.05         # perennial minus ephemeral summer share that counts

REGIONS = [
    ("מקורות הירדן ועמק החולה", ["30"]),
    ("הכנרת ונחלי הגולן", ["31", "32"]),
    ("עמק הירדן ובקעת הירדן", ["34", "35", "38", "41", "46"]),
    ("הגליל המערבי", ["2", "4", "5", "6", "7"]),
    ("הקישון ועמק יזרעאל", ["8", "9"]),
    ("הכרמל ונחל תנינים", ["10", "11", "12", "13"]),
    ("השרון: חדרה ואלכסנדר", ["14", "15"]),
    ("הירקון והאיילון", ["17"]),
    ("שורק ולכיש", ["18", "19"]),
    ("שקמה, בשור והנגב הצפוני", ["21", "23", "25"]),
    ("מדבר יהודה וים המלח", ["48"]),
    ("הנגב הדרומי והערבה", ["55", "56", "57", "58", "59", "60"]),
]
OTHER_REGION = "אזורים אחרים"
REGION_OF = {code: name for name, codes in REGIONS for code in codes}
REGION_ORDER = [name for name, _ in REGIONS] + [OTHER_REGION]

HYDRO_MONTHS = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
MONTH_HE = {1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל", 5: "מאי", 6: "יוני",
            7: "יולי", 8: "אוגוסט", 9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר",
            12: "דצמבר"}
CLASS_NAMES = {"perennial": "זורמות כמעט תמיד", "intermittent": "זרימה עונתית",
               "ephemeral": "אכזבים (זרימה נדירה)"}
CLASS_ORDER = ["perennial", "intermittent", "ephemeral"]

MINUS = "−"


# ── formatting ───────────────────────────────────────────────────────────

def ylab(y):
    return f"{int(y) - 1}/{int(y)}"


def mcm(v, digits=1):
    """m3 -> million m3, formatted."""
    return f"{v / 1e6:,.{digits}f}"


def pct(r, digits=0):
    return f"{r * 100:,.{digits}f}%"


def times(r):
    return f"פי {r:,.1f}"


def r2(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 2)


def in_(name):
    """Hebrew 'in <name>': ב + name, absorbing a leading definite ה."""
    return "ב" + (name[1:] if name.startswith("ה") else name)


def region_of(sid):
    s = str(sid)
    if len(s) <= 3:
        return OTHER_REGION
    return REGION_OF.get(s[:-3], OTHER_REGION)


# ── load ─────────────────────────────────────────────────────────────────

def _compact(df, vol_col):
    """String frame -> (sid, date, volume) with dates parsed once per value."""
    if df is None or len(df) == 0:
        return pd.DataFrame({"sid": pd.Series(dtype=str), "dt": pd.Series(dtype="datetime64[ns]"),
                             "v": pd.Series(dtype=float)}), pd.DataFrame(columns=["sid", "name"])
    sid = df[C_ID].astype(str).str.strip()
    dates = df[C_DATE].astype(str).str.strip().astype("category")
    parsed = pd.to_datetime(pd.Series(dates.cat.categories), format="%d/%m/%Y", errors="coerce")
    codes = dates.cat.codes.to_numpy()
    dt = parsed.to_numpy()[np.where(codes >= 0, codes, 0)]
    dt = np.where(codes >= 0, dt, np.datetime64("NaT"))
    v = pd.to_numeric(df[vol_col].astype(str).str.replace(",", "", regex=False).str.strip(),
                      errors="coerce")
    out = pd.DataFrame({"sid": sid.to_numpy(), "dt": dt, "v": v.to_numpy()})
    names = pd.DataFrame({"sid": sid.to_numpy(), "name": df[C_NAME].astype(str).str.strip().to_numpy()})
    names = names.value_counts().reset_index(name="n")
    return out, names


def load(frames):
    parts, names = [], []
    for key, col in (("main", C_VOL), ("early", C_VOL_EARLY)):
        df = frames.get(key)
        if df is None:
            continue
        p, n = _compact(df, col)
        parts.append(p)
        names.append(n)
    d = pd.concat(parts, ignore_index=True)
    d = d[d["sid"].str.fullmatch(r"\d+") & d["dt"].notna()]
    d.loc[d["v"] < 0, "v"] = np.nan
    # A day published twice (overlapping period files): keep the recorded value.
    d = d.sort_values(["sid", "dt", "v"], na_position="first", kind="mergesort")
    d = d.drop_duplicates(["sid", "dt"], keep="last").reset_index(drop=True)
    d["y"] = d["dt"].dt.year + (d["dt"].dt.month >= 10).astype(int)
    d["m"] = d["dt"].dt.month

    nm = pd.concat(names, ignore_index=True).groupby(["sid", "name"], as_index=False)["n"].sum()
    nm = nm[nm["name"] != ""].sort_values(["sid", "n", "name"], ascending=[True, False, True])
    name_of = dict(zip(nm.drop_duplicates("sid")["sid"], nm.drop_duplicates("sid")["name"]))
    return d, name_of


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    d, name_of = load(frames)
    nm = lambda s: name_of.get(s, f"תחנה {s}")  # noqa: E731

    n_rows = int(len(d))
    stations_all = sorted(d["sid"].unique().tolist(), key=int)
    n_stations = len(stations_all)
    rec = d[d["v"].notna()]
    n_missing = int(d["v"].isna().sum())

    # station x hydrological year
    rec_flow = (rec["v"] > 0)
    sy = rec.groupby(["sid", "y"], sort=True).agg(nv=("v", "size"), vol=("v", "sum")).reset_index()
    sy["complete"] = sy["nv"] >= MIN_DAYS
    comp = sy[sy["complete"]].copy()

    first_y, last_y = int(rec["y"].min()), int(rec["y"].max())
    last_date = rec["dt"].max()
    last_days = int(rec.loc[rec["y"] == last_y, "dt"].dt.normalize().nunique())
    last_partial = not (last_date.month == 9 and last_date.day >= 30)

    # baselines and ratios
    ny = comp.groupby("sid")["y"].transform("size")
    comp["med"] = comp.groupby("sid")["vol"].transform("median")
    base = comp[(ny >= MIN_BASE_YEARS) & (comp["med"] >= MIN_BASE_VOL)].copy()
    base["r"] = base["vol"] / base["med"]
    idx = base.groupby("y").agg(n=("r", "size"), med=("r", "median"),
                                above=("r", lambda s: float((s > 1).mean()))).reset_index()
    idx = idx[idx["n"] >= MIN_INDEX_STATIONS].sort_values("y").reset_index(drop=True)
    if idx.empty:
        raise ValueError("no year has enough stations for the flow index")
    L = int(idx["y"].iloc[-1])
    lab_L = ylab(L)
    iL = float(idx["med"].iloc[-1])
    nL = int(idx["n"].iloc[-1])
    aboveL = float(idx["above"].iloc[-1])

    def year_class(v):
        if v < VERY_DRY:
            return "שחונה מאוד"
        if v < DRY:
            return "שחונה"
        if v >= WET:
            return "גשומה"
        return "קרובה לרגיל"

    # ── chart: flow index ──
    chart_index = {"x": [ylab(y) for y in idx["y"]], "y": [round(float(v) * 100, 1) for v in idx["med"]],
                   "n": [int(v) for v in idx["n"]], "above": [round(float(v) * 100, 1) for v in idx["above"]],
                   "dry": DRY * 100, "wet": WET * 100}

    # ── chart: network ──
    act = rec.groupby("y")["sid"].nunique()
    full = comp.groupby("y")["sid"].nunique()
    yrs = list(range(first_y, last_y + 1))
    chart_network = {"x": [ylab(y) for y in yrs],
                     "complete": [int(full.get(y, 0)) for y in yrs],
                     "partial": [int(act.get(y, 0)) - int(full.get(y, 0)) for y in yrs],
                     "last_partial": bool(last_partial)}
    peak_net_y = int(act.sort_index().idxmax())
    peak_net = int(act.max())
    active_last = int(act.get(last_y, 0))

    # ── heatmap: long-record stations ──
    inL = set(base.loc[base["y"] == L, "sid"])
    rec_len = base.groupby("sid")["y"].size()
    cand = sorted([s for s in inL], key=lambda s: (-int(rec_len[s]), int(s)))[:HEAT_STATIONS]
    cand = sorted(cand, key=lambda s: (REGION_ORDER.index(region_of(s)), int(s)))
    hb = base[base["sid"].isin(cand)]
    heat_years = list(range(int(hb["y"].min()), L + 1)) if len(hb) else []
    yi = {y: i for i, y in enumerate(heat_years)}
    si = {s: i for i, s in enumerate(cand)}
    cells = [[yi[int(y)], si[s], int(round(float(r) * 100))]
             for s, y, r in zip(hb["sid"], hb["y"], hb["r"]) if int(y) in yi]
    cells.sort()
    chart_heat = {"years": [ylab(y) for y in heat_years], "stations": [nm(s) for s in cand], "cells": cells}

    # ── flagship: largest typical annual flow, long record, measured in L ──
    flag_pool = comp[comp["sid"].isin(inL)].groupby("sid").agg(ny=("y", "size"), med=("vol", "median"))
    flag_pool = flag_pool[flag_pool["ny"] >= FLAG_MIN_YEARS].reset_index()
    flag = None
    if len(flag_pool):
        flag_pool = flag_pool.sort_values(["med", "sid"], ascending=[False, True])
        fs = flag_pool["sid"].iloc[0]
        fy = comp[comp["sid"] == fs].sort_values("y")
        fmed = float(fy["vol"].median())
        fl = float(fy.loc[fy["y"] == L, "vol"].iloc[0])
        lo = fy.sort_values(["vol", "y"]).iloc[0]
        hi = fy.sort_values(["vol", "y"], ascending=[False, True]).iloc[0]
        years_f = list(range(int(fy["y"].min()), int(fy["y"].max()) + 1))
        vmap = dict(zip(fy["y"].astype(int), fy["vol"]))
        recent = fy[fy["y"] > L - RECENT_SPAN]
        earlier = fy[fy["y"] <= L - RECENT_SPAN]
        flag = {
            "sid": fs, "name": nm(fs), "median": fmed, "latest": fl, "lo": lo, "hi": hi,
            "x": [ylab(y) for y in years_f],
            "y": [round(float(vmap[y]) / 1e6, 2) if y in vmap else None for y in years_f],
            "recent_mean": float(recent["vol"].mean()) if len(recent) >= RECENT_SPAN - 2 else None,
            "earlier_mean": float(earlier["vol"].mean()) if len(earlier) >= RECENT_SPAN else None,
            "n_years": int(len(fy)),
        }
        # daily hydrograph of the latest year vs the station's typical day
        fd = rec[(rec["sid"] == fs)].copy()
        start = pd.to_datetime((fd["y"] - 1).astype(str) + "-10-01")
        fd["doy"] = (fd["dt"] - start).dt.days
        good_years = set(fy["y"].astype(int))
        typ = fd[fd["y"].isin(good_years)].groupby("doy")["v"].median()
        cur = fd[fd["y"] == L].set_index("doy")["v"]
        n_days = 365 if (pd.Timestamp(f"{L}-10-01") - pd.Timestamp(f"{L - 1}-10-01")).days == 365 else 366
        day0 = pd.Timestamp(f"{L - 1}-10-01")
        days = [day0 + pd.Timedelta(days=i) for i in range(n_days)]
        chart_daily = {
            "x": [f"{t.day:02d}/{t.month:02d}" for t in days],
            "cur": [r2(cur.get(i, np.nan) / 86400) for i in range(n_days)],
            "typ": [r2(typ.get(i, np.nan) / 86400) for i in range(n_days)],
        }
        cur_max_i = int(cur.idxmax()) if cur.notna().any() else None
        flag["cur_peak"] = (days[cur_max_i], float(cur.max()) / 86400) if cur_max_i is not None and cur_max_i < n_days else None
        chart_flag = {"x": flag["x"], "y": flag["y"], "median": round(fmed / 1e6, 2), "name": flag["name"],
                      "lo": ylab(lo["y"]), "hi": ylab(hi["y"])}
    else:
        chart_daily = None
        chart_flag = None

    # ── latest year ranking ──
    cL = comp[comp["y"] == L].sort_values(["vol", "sid"], ascending=[False, True]).head(LATEST_TOP)
    medmap = comp.groupby("sid")["vol"].median()
    nymap = comp.groupby("sid")["y"].size()
    latest_rows = []
    for s, v in zip(cL["sid"], cL["vol"]):
        b = float(medmap[s]) if int(nymap[s]) >= MIN_BASE_YEARS else None
        latest_rows.append({"name": nm(s), "vol": round(float(v) / 1e6, 2),
                            "base": round(b / 1e6, 2) if b else None,
                            "pct": round(float(v) / b * 100) if b and b > 0 else None})
    chart_latest = {"names": [r["name"] for r in latest_rows], "vol": [r["vol"] for r in latest_rows],
                    "base": [r["base"] for r in latest_rows], "pct": [r["pct"] for r in latest_rows]}

    # ── regions in the latest year ──
    bL = base[base["y"] == L].copy()
    bL["region"] = bL["sid"].map(region_of)
    reg = bL[bL["region"] != OTHER_REGION].groupby("region")["r"].agg(["median", "size"]).reset_index()
    reg = reg[reg["size"] >= MIN_REGION_LATEST].sort_values(["median", "region"], ascending=[False, True])
    chart_region = {"names": reg["region"].tolist(), "pct": [round(float(v) * 100, 1) for v in reg["median"]],
                    "n": [int(v) for v in reg["size"]]}
    n_other_L = int((bL["region"] == OTHER_REGION).sum())

    # ── flow regime (share of recorded days with flow) ──
    flowdays = rec_flow.groupby(rec["sid"]).mean()
    ndays = rec.groupby("sid").size()
    reg_st = flowdays[ndays >= 365]

    def cls(f):
        if f < EPHEMERAL:
            return "ephemeral"
        if f >= PERENNIAL:
            return "perennial"
        return "intermittent"

    activeL = sorted(set(comp.loc[comp["y"] == L, "sid"]), key=int)
    fdL = reg_st.reindex(activeL).dropna()
    bins = [round(i / 10, 1) for i in range(11)]
    hist = [0] * 10
    for f in fdL:
        hist[min(int(math.floor(f * 10 + 1e-9)), 9)] += 1
    chart_regime = {"bins": [f"{i * 10}-{(i + 1) * 10}%" for i in range(10)], "n": hist}
    del bins
    class_L = {c: int(sum(1 for f in fdL if cls(f) == c)) for c in CLASS_ORDER}

    # ── seasonality by regime class ──
    cy = comp[["sid", "y"]]
    mrec = rec.merge(cy, on=["sid", "y"], how="inner")
    sm = mrec.groupby(["sid", "m"])["v"].sum().unstack(fill_value=0.0)
    tot = sm.sum(axis=1)
    sm = sm[tot > 0]
    share = sm.div(sm.sum(axis=1), axis=0)
    share = share.reindex(columns=HYDRO_MONTHS, fill_value=0.0)
    share["cls"] = [cls(float(reg_st.get(s, np.nan))) if s in reg_st.index else None for s in share.index]
    share = share[share["cls"].notna()]
    season_series, season_n, winter, summer = [], {}, {}, {}
    for c in CLASS_ORDER:
        sub = share[share["cls"] == c]
        if len(sub) < 3:
            continue
        m = sub[HYDRO_MONTHS].mean()
        season_series.append({"name": CLASS_NAMES[c], "data": [round(float(m[k]) * 100, 1) for k in HYDRO_MONTHS]})
        season_n[c] = int(len(sub))
        winter[c] = float(sum(m[k] for k in WINTER_MONTHS))
        summer[c] = float(sum(m[k] for k in SUMMER_MONTHS))
    chart_season = {"months": [MONTH_HE[k] for k in HYDRO_MONTHS], "series": season_series}

    # ── record daily discharge per station ──
    pk = rec.sort_values(["sid", "v", "dt"], ascending=[True, False, True]).drop_duplicates("sid")
    pk = pk.sort_values(["v", "sid"], ascending=[False, True]).head(PEAK_TOP)
    peak_rows = [{"name": nm(s), "date": f"{t.day:02d}/{t.month:02d}/{t.year}", "q": round(float(v) / 86400, 1)}
                 for s, t, v in zip(pk["sid"], pk["dt"], pk["v"])]
    chart_peak = {"names": [r["name"] for r in peak_rows], "dates": [r["date"] for r in peak_rows],
                  "q": [r["q"] for r in peak_rows]}
    top_peak = peak_rows[0]

    # ── insights ──
    ins = []

    def ins_latest():
        rank_dry = int((idx["med"] < iL).sum()) + 1
        n = len(idx)
        prev = idx[idx["y"] < L]
        tail = ""
        if iL >= WET:
            hit = prev[prev["med"] >= iL]
            if len(hit) and L - int(hit["y"].iloc[-1]) >= 5:
                tail = f" זו השנה הגשומה ביותר מאז {ylab(int(hit['y'].iloc[-1]))}."
            elif not len(hit):
                tail = " זו השנה הגשומה ביותר בתיעוד."
        elif iL < DRY:
            hit = prev[prev["med"] <= iL]
            if len(hit) and L - int(hit["y"].iloc[-1]) >= 5:
                tail = f" זו השנה השחונה ביותר מאז {ylab(int(hit['y'].iloc[-1]))}."
            elif not len(hit):
                tail = " זו השנה השחונה ביותר בתיעוד."
        return (f"בשנה ההידרולוגית {lab_L} זרמה תחנה טיפוסית {pct(iL)} מהנפח הרגיל שלה, שנה "
                f"{year_class(iL)} (במקום ה-{rank_dry} מתוך {n} שנים במדד, מהשחונה לגשומה). "
                f"{round(aboveL * nL)} מתוך {nL} התחנות במדד רשמו נפח מעל החציון הרב-שנתי שלהן.{tail}")

    def ins_extremes():
        if len(idx) < 10:
            return None
        w = idx.sort_values(["med", "y"], ascending=[False, True]).iloc[0]
        dr = idx.sort_values(["med", "y"]).iloc[0]
        return (f"השנה הגשומה ביותר במדד היא {ylab(int(w['y']))}: תחנה טיפוסית הזרימה {times(float(w['med']))} "
                f"מהרגיל. השחונה ביותר היא {ylab(int(dr['y']))}, עם {pct(float(dr['med']))} בלבד מהרגיל.")

    def ins_drought_run():
        best, cur, start, prev_y = (0, None, None), 0, None, None
        for y, v in zip(idx["y"].astype(int), idx["med"]):
            if v < DRY:
                if cur and prev_y is not None and y == prev_y + 1:
                    cur += 1
                else:
                    start, cur = y, 1
                if cur > best[0]:
                    best = (cur, start, y)
            else:
                cur = 0
            prev_y = y
        if best[0] < MIN_RUN:
            return None
        n_dry = int((idx["med"] < DRY).sum())
        return (f"רצף השנים השחונות הארוך ביותר נמשך {best[0]} שנים ברציפות, מ-{ylab(best[1])} עד {ylab(best[2])}. "
                f"בסך הכול {n_dry} מתוך {len(idx)} השנים במדד היו שחונות (מתחת ל-{pct(DRY)} מהרגיל).")

    def ins_flagship():
        if not flag:
            return None
        r = flag["latest"] / flag["median"] if flag["median"] > 0 else None
        if r is None:
            return None
        s = (f"בתחנת {flag['name']}, התחנה עם הזרימה השנתית הטיפוסית הגדולה ביותר ברשת, נמדדו ב-{lab_L} "
             f"{mcm(flag['latest'])} מיליון מ\"ק, {pct(r)} מהחציון הרב-שנתי ({mcm(flag['median'])} מיליון מ\"ק).")
        if flag["recent_mean"] and flag["earlier_mean"]:
            ch = flag["recent_mean"] / flag["earlier_mean"] - 1
            if abs(ch) >= TREND_MIN:
                word = "נמוך" if ch < 0 else "גבוה"
                s += (f" הממוצע ב-{RECENT_SPAN} השנים האחרונות {word} ב-{pct(abs(ch))} מהממוצע בשנים שקדמו להן "
                      f"({mcm(flag['recent_mean'])} לעומת {mcm(flag['earlier_mean'])} מיליון מ\"ק).")
            else:
                s += f" הממוצע ב-{RECENT_SPAN} השנים האחרונות דומה לממוצע בשנים שקדמו להן."
        s += f" השפל בתיעוד: {ylab(int(flag['lo']['y']))} ({mcm(float(flag['lo']['vol']))} מיליון מ\"ק)."
        return s

    def ins_regime():
        n = len(fdL)
        if n < 10:
            return None
        e, p = class_L["ephemeral"], class_L["perennial"]
        if e == 0 and p == 0:
            return None
        return (f"מתוך {n} התחנות שנמדדו בשנה מלאה ב-{lab_L}, ב-{e} ({pct(e / n)}) הנחל זרם לאורך שנות "
                f"המדידה בפחות מעשירית מהימים (אכזבים), ורק ב-{p} ({pct(p / n)}) הוא זרם ב-{pct(PERENNIAL)} "
                f"מהימים או יותר.")

    def ins_season():
        if "ephemeral" not in summer or "perennial" not in summer:
            return None
        se, sp = summer["ephemeral"], summer["perennial"]
        if sp - se < SUMMER_GAP or sp < 2 * se:
            return None
        return (f"בנחלים שזורמים כמעט תמיד עובר ביוני עד ספטמבר {pct(sp)} מהנפח השנתי, ובאכזבים רק {pct(se)}: "
                f"באכזבים {pct(winter['ephemeral'])} מהנפח מגיע בדצמבר עד מרץ, בשיטפונות חורף קצרים.")

    def ins_peak():
        return (f"הספיקה היומית הממוצעת הגבוהה ביותר בתיעוד נמדדה בתחנת {top_peak['name']} ב-{top_peak['date']}: "
                f"{top_peak['q']:,.1f} מ\"ק בשנייה.")

    def ins_region():
        if len(reg) < 3:
            return None
        hi_, lo_ = reg.iloc[0], reg.iloc[-1]
        if float(lo_["median"]) <= 0 or float(hi_["median"]) / float(lo_["median"]) < 1.5:
            return None
        return (f"הפער האזורי ב-{lab_L}: {in_(hi_['region'])} זרמה תחנה טיפוסית {pct(float(hi_['median']))} מהרגיל "
                f"({int(hi_['size'])} תחנות), ו{in_(lo_['region'])} רק {pct(float(lo_['median']))} "
                f"({int(lo_['size'])} תחנות).")

    def ins_network():
        if active_last <= 0:
            return None
        n0 = int(act.get(first_y, 0))
        start_txt = "מתחנה אחת" if n0 == 1 else f"מ-{n0} תחנות"
        s = (f"רשת המדידה גדלה {start_txt} ב-{ylab(first_y)} לשיא של {peak_net} תחנות ב-{ylab(peak_net_y)}; "
             f"ב-{ylab(last_y)} נמדדו {active_last} תחנות.")
        if last_partial:
            s += f" השנה {ylab(last_y)} חלקית בנתונים ({last_days} ימים)."
        return s

    for key, fn in (("latest", ins_latest), ("extremes", ins_extremes), ("flagship", ins_flagship),
                    ("drought_run", ins_drought_run), ("region", ins_region), ("regime", ins_regime),
                    ("season", ins_season), ("peak", ins_peak), ("network", ins_network)):
        t = fn()
        if t:
            ins.append({"id": key, "text_he": t})

    # ── KPIs ──
    def tone_ratio(r):
        if r < VERY_DRY:
            return "danger"
        if r < DRY:
            return "warn"
        if r >= WET:
            return "ok"
        return "brand"

    kpis = {
        "index": {"value": round(iL * 100, 1), "display": f"{iL * 100:.0f}%", "tone": tone_ratio(iL)},
        "stations": {"value": n_stations, "display": f"{n_stations:,}", "tone": "brand"},
        "active": {"value": active_last, "display": f"{active_last:,}", "tone": "warn" if last_partial else "brand"},
        "span": {"value": last_y - first_y + 1, "display": f"{first_y - 1}–{last_y}", "tone": "info"},
        "peak": {"value": top_peak["q"], "display": f"{top_peak['q']:,.1f}", "tone": "brand"},
    }
    if flag:
        rf = flag["latest"] / flag["median"] if flag["median"] > 0 else 1.0
        kpis["flag"] = {"value": round(flag["latest"] / 1e6, 1), "display": mcm(flag["latest"]),
                        "tone": tone_ratio(rf)}

    kpi_labels = {
        "index": f"מדד הזרימה ב-{lab_L} (100% = שנה רגילה)",
        "flag": f"נפח שנתי בתחנת {flag['name']} ב-{lab_L} (מיליון מ\"ק)" if flag else "",
        "stations": "תחנות הידרומטריות במאגר",
        "active": f"תחנות שנמדדו ב-{ylab(last_y)}" + (" (שנה חלקית)" if last_partial else ""),
        "span": f"תקופת המדידה ({last_y - first_y + 1} שנים הידרולוגיות)",
        "peak": f"ספיקה יומית ממוצעת שיא (מ\"ק/שנייה), {top_peak['name']}",
    }
    kpi_order = ["index", "flag", "stations", "active", "span", "peak"] if flag else \
        ["index", "stations", "active", "span", "peak"]

    # ── labels ──
    summary = (f"איתור נתוני ספיקה ונפח זרימה יומיים לפי תחנה הידרומטרית: {n_stations} תחנות בנחלי ישראל, "
               f"{first_y - 1} עד {last_y}. ב-{lab_L} זרמה תחנה טיפוסית {pct(iL)} מהרגיל.")
    if len(summary) > 155:
        summary = (f"ספיקה ונפח זרימה יומיים ב-{n_stations} תחנות הידרומטריות בנחלי ישראל. "
                   f"ב-{lab_L} זרמה תחנה טיפוסית {pct(iL)} מהרגיל.")

    lede = (f"המאגר של השירות ההידרולוגי ברשות המים מתעד {n_rows:,} רשומות יומיות ב-{n_stations} תחנות "
            f"הידרומטריות לאורך הנחלים, מ-{ylab(first_y)} ועד {ylab(last_y)}: נפח הזרימה היומי (מ\"ק) והספיקה "
            f"היומית הממוצעת (מ\"ק בשנייה), שחושבו ממדידות רום המים ועקומי כיול. העמוד מסכם את השנים הגשומות "
            f"והשחונות, את התחנות הגדולות, את עונתיות הזרימה ואת שיאי השיטפונות.")
    if n_missing:
        lede += f" ב-{n_missing:,} ימים לא נרשם נפח, והם אינם נכללים בחישובים."

    labels = {
        "lede": lede,
        "index_note": (f"לכל תחנה עם {MIN_BASE_YEARS} שנים מלאות לפחות (שנה מלאה: {MIN_DAYS} ימי מדידה ומעלה) "
                       f"מחושב החציון הרב-שנתי שלה, והנפח בכל שנה מבוטא באחוזים ממנו. המדד הוא החציון של "
                       f"האחוזים בין התחנות שנמדדו באותה שנה (שנים עם {MIN_INDEX_STATIONS} תחנות לפחות). "
                       f"אדום: שנה שחונה (מתחת ל-{pct(DRY)}); כחול כהה: שנה גשומה ({pct(WET)} ומעלה). "
                       f"ב-{lab_L}: {pct(iL)} מהרגיל."),
        "index_aria": (f"גרף עמודות: מדד הזרימה השנתי ב-{len(idx)} שנים הידרולוגיות, {ylab(int(idx['y'].iloc[0]))} "
                       f"עד {lab_L}. ב-{lab_L} המדד עמד על {pct(iL)} מהרגיל."),
        "heat_note": (f"{len(cand)} התחנות עם הרצף הארוך ביותר של שנים מלאות שנמדדו גם ב-{lab_L}, מסודרות לפי "
                      f"אזור. כל משבצת: הנפח השנתי באחוזים מהחציון של אותה תחנה. משבצת ריקה: שנה חסרה או חלקית."),
        "heat_aria": (f"מפת חום: נפח שנתי באחוזים מהרגיל ב-{len(cand)} תחנות לאורך {len(heat_years)} שנים הידרולוגיות."),
        "network_note": (f"מספר התחנות שנמדדו בכל שנה הידרולוגית: בשנה מלאה ({MIN_DAYS} ימים ומעלה) או חלקית. "
                         f"השיא: {peak_net} תחנות ב-{ylab(peak_net_y)}."
                         + (f" השנה האחרונה, {ylab(last_y)}, חלקית ({last_days} ימים)." if last_partial else "")),
        "network_aria": (f"גרף עמודות מוערמות: מספר התחנות שנמדדו בכל שנה, מ-{ylab(first_y)} עד {ylab(last_y)}. "
                         f"שיא של {peak_net} תחנות ב-{ylab(peak_net_y)}."),
        "latest_note": (f"{len(latest_rows)} התחנות עם הנפח השנתי הגדול ביותר ב-{lab_L} (מיליון מ\"ק), לצד החציון "
                        f"הרב-שנתי של כל תחנה. תחנות לאורך אותו נחל נמדדות כל אחת בנפרד, ולכן אין לחבר ביניהן."),
        "latest_aria": (f"גרף עמודות: {len(latest_rows)} התחנות עם הנפח השנתי הגדול ביותר ב-{lab_L}, בראשן "
                        f"{latest_rows[0]['name']} עם {latest_rows[0]['vol']:,.1f} מיליון מ\"ק." if latest_rows else ""),
        "latest_caption": f"הנפח השנתי ב-{lab_L} והחציון הרב-שנתי, במיליון מ\"ק.",
        "region_note": (f"החציון של הנפח באחוזים מהרגיל בין התחנות של כל אזור ב-{lab_L} (אזורים עם "
                        f"{MIN_REGION_LATEST} תחנות לפחות במדד). האזור נגזר מקוד האגן שבמספר התחנה."
                        + (f" {n_other_L} תחנות שקוד האגן שלהן אינו ממופה לא נכללו." if n_other_L else "")),
        "region_aria": (f"גרף עמודות: מדד הזרימה לפי אזור ב-{lab_L}, {len(reg)} אזורים." +
                        (f" הגבוה: {reg['region'].iloc[0]}, {pct(float(reg['median'].iloc[0]))}." if len(reg) else "")),
        "region_caption": f"מדד הזרימה לפי אזור ב-{lab_L}.",
        "regime_note": (f"לכל אחת מ-{len(fdL)} התחנות שנמדדו בשנה מלאה ב-{lab_L}: שיעור הימים עם זרימה (נפח גדול "
                        f"מאפס) מכלל ימי המדידה שלה לאורך כל השנים, ולא רק בשנה האחרונה. תחנות שנמדדו פחות משנה לא נכללו."),
        "regime_aria": (f"היסטוגרמה: {len(fdL)} תחנות לפי שיעור הימים עם זרימה. {class_L['ephemeral']} תחנות "
                        f"זרמו לאורך שנות המדידה בפחות מעשירית מהימים."),
        "regime_caption": "מספר התחנות לפי שיעור הימים עם זרימה.",
        "season_note": (f"החלק של כל חודש בנפח השנתי, בממוצע בין התחנות של כל סוג (שנים מלאות בלבד). זורמות כמעט "
                        f"תמיד: זרימה ב-{pct(PERENNIAL)} מהימים ומעלה; אכזבים: בפחות מ-{pct(EPHEMERAL)} מהימים. "
                        + ", ".join(f"{CLASS_NAMES[c]}: {season_n[c]} תחנות" for c in CLASS_ORDER if c in season_n)
                        + "."),
        "season_aria": (f"גרף קווים: חלק כל חודש בנפח השנתי לפי סוג הנחל. באכזבים {pct(winter.get('ephemeral', 0))} "
                        f"מהנפח עובר בדצמבר עד מרץ." if "ephemeral" in winter else
                        "גרף קווים: חלק כל חודש בנפח השנתי לפי סוג הנחל."),
        "season_caption": "חלק כל חודש בנפח השנתי (באחוזים), לפי סוג הנחל.",
        "peak_note": (f"{len(peak_rows)} התחנות עם הספיקה היומית הממוצעת הגבוהה ביותר שנמדדה בהן, ויום השיא של כל "
                      f"אחת. ספיקה יומית ממוצעת היא הנפח היומי חלקי מספר השניות ביממה; שיא רגעי של שיטפון גבוה ממנה."),
        "peak_aria": (f"גרף עמודות: שיא הספיקה היומית הממוצעת ב-{len(peak_rows)} תחנות, בראשן {top_peak['name']} "
                      f"עם {top_peak['q']:,.1f} מ\"ק בשנייה."),
        "peak_caption": "שיא הספיקה היומית הממוצעת בכל תחנה (מ\"ק בשנייה) ויום השיא.",
    }
    if flag:
        rf = flag["latest"] / flag["median"] if flag["median"] > 0 else 1.0
        labels.update({
            "flag_title": f"{flag['name']}: הנפח השנתי לאורך השנים",
            "flag_note": (f"התחנה עם החציון השנתי הגדול ביותר מבין התחנות עם {FLAG_MIN_YEARS} שנים מלאות לפחות "
                          f"שנמדדו ב-{lab_L} ({flag['n_years']} שנים מלאות). הקו המקווקו: החציון, "
                          f"{mcm(flag['median'])} מיליון מ\"ק. שנה חסרה או חלקית מוצגת כרווח."),
            "flag_aria": (f"גרף עמודות: הנפח השנתי בתחנת {flag['name']}, במיליון מ\"ק. ב-{lab_L}: {mcm(flag['latest'])}, "
                          f"{pct(rf)} מהחציון."),
            "daily_title": f"{flag['name']}: ספיקה יומית ב-{lab_L} לעומת יום טיפוסי",
            "daily_note": (f"הספיקה היומית הממוצעת (מ\"ק בשנייה) בכל יום של {lab_L}, לעומת החציון של אותו יום "
                           f"בשנה ההידרולוגית בכל השנים המלאות בתחנה."
                           + (f" שיא השנה: {flag['cur_peak'][1]:,.1f} מ\"ק בשנייה ב-"
                              f"{flag['cur_peak'][0].day:02d}/{flag['cur_peak'][0].month:02d}/{flag['cur_peak'][0].year}."
                              if flag.get("cur_peak") else "")),
            "daily_aria": (f"גרף קווים: ספיקה יומית בתחנת {flag['name']} לאורך {lab_L}, לצד החציון הרב-שנתי לכל יום."),
        })

    tables = {
        "latest": latest_rows,
        "region": [{"region": r, "pct": f"{p:.0f}%", "n": n} for r, p, n in
                   zip(chart_region["names"], chart_region["pct"], chart_region["n"])],
        "regime": [{"bin": b, "n": n} for b, n in zip(chart_regime["bins"], chart_regime["n"])],
        "season": [{"month": mo, "vals": [f"{s['data'][i]:.1f}%" for s in season_series]}
                   for i, mo in enumerate(chart_season["months"])],
        "season_cols": [s["name"] for s in season_series],
        "peak": peak_rows,
    }

    flags = {"flag": flag is not None, "region": len(reg) >= 2, "season": len(season_series) >= 2,
             "partial": bool(last_partial)}

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "suggested_tags": ["נחלים", "ספיקה", "הידרומטריה", "זרימה", "שיטפונות", "רשות המים"],
        "related_ids": ["d16214ba-56b3-417d-9342-6a144f215b9b", "15072295-27ab-4939-951b-de462adc0ab0",
                        "f72117a6-2b71-43e9-bc81-75c284a4d1e2", "096db5d2-dc8b-40c8-9fe7-2b839a435d92",
                        "87514149-a73c-424d-89b4-80d3c9058f7a"],
        "temporal_coverage": f"{first_y - 1}/{last_y}",
        "spatial_coverage": "ישראל",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": kpi_order,
        "kpi_labels": kpi_labels,
        "charts": {"index": chart_index, "network": chart_network, "heat": chart_heat, "flag": chart_flag,
                   "daily": chart_daily, "latest": chart_latest, "region": chart_region,
                   "regime": chart_regime, "season": chart_season, "peak": chart_peak},
        "insights": ins,
        "labels": labels,
        "tables": tables,
        "flags": flags,
    }
