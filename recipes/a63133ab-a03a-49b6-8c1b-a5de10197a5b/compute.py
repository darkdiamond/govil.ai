"""IMS meteorological archive: station registry, daily temperature and
weather phenomena, monthly rain, desert totalizer gauges and solar radiation.

Every number on the page comes from here. The archive mixes stations that
opened and closed over 180 years, so national series are built from
per-station anomalies against each station's own 1991-2020 normal, never
from raw averages over a changing station set. Insight rules each return a
sentence or None when their premise does not hold in the data.
"""
import numpy as np
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
# Rain season (שנת גשם) runs August to July, per the IMS documentation.
SEASON_MONTHS = [8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7]
WET_MONTHS = [10, 11, 12, 1, 2, 3, 4]

STATION_TYPES = {"1": "תחנות אקלים", "2": "תחנות גשם", "4": "תחנות קרינה",
                 "5": "תחנות התאדות"}
PHENOMENA = [("rpr_thunder", "רעמים"), ("rpr_hail", "ברד"), ("rpr_fog", "ערפל"),
             ("rpr_frost", "כפור"), ("rpr_sand_storm", "סופת חול"), ("rpr_snow", "שלג")]
RAD_HOURS = [f"rad_{h:02d}" for h in range(4, 18)]
GLOBAL_RAD = "15"

BASE_FIRST, BASE_LAST = 1991, 2020        # temperature normal (calendar years)
RAIN_BASE_FIRST, RAIN_BASE_LAST = 1990, 2019  # rain normal: seasons 1990/91-2019/20
MIN_DAYS = 330          # a complete station-year of daily temperature
MIN_BASE_YEARS = 15     # temperature: complete years inside the normal
MIN_RAIN_BASE = 20      # rain: complete seasons inside the normal
MIN_STATIONS = 5        # national anomaly: stations per year
MIN_RAIN_STATIONS = 20  # national rain index: stations per season
MIN_TOTALIZERS = 10     # desert totalizers: gauges per year
DRY_PCT, WET_PCT = 80, 120  # rain season colouring and wording
HOT_C = 35.0
WINDOW_YEARS = 10       # climatology / radiation window
CLIMATE_ROWS = 12
TOP_N = 10
MINUS = "−"


# ---------------------------------------------------------------- helpers
def _int(n):
    return f"{int(round(n)):,}"


def _signed(v, nd=1):
    r = round(v, nd)
    s = f"{abs(r):.{nd}f}"
    return ("+" + s) if r > 0 else (MINUS + s) if r < 0 else s


def _num(v, nd=1):
    s = f"{abs(v):,.{nd}f}"
    return (MINUS + s) if v < 0 and round(abs(v), nd) else s


def _season(y):
    return f"{int(y)}/{(int(y) + 1) % 100:02d}"


def _clean(s):
    return s.astype(str).str.strip()


def _station_names(st):
    names = {}
    for num, name in zip(st["stn_num"], st["name"]):
        names.setdefault(num, name)
    return names


def _name(names, num):
    return names.get(num) or f"תחנה {num}"


def _date_he(ts):
    return f"{ts.day}.{ts.month}.{ts.year}"


# ---------------------------------------------------------------- stations
def _prep_stations(df):
    st = df.copy()
    for c in ["stn_num", "stn_type", "stn_name_heb", "stn_auto", "date_close"]:
        st[c] = _clean(st[c])
    st["name"] = st["stn_name_heb"].str.replace(r"\s+", " ", regex=True)
    st["lat"] = pd.to_numeric(st["stn_lat"], errors="coerce")
    st["hgt"] = pd.to_numeric(st["stn_hgt"], errors="coerce")
    st["open"] = pd.to_datetime(st["date_open"].str.strip(), errors="coerce", format="%Y-%m-%d")
    st["close"] = pd.to_datetime(st["date_close"], errors="coerce", format="%Y-%m-%d")
    st["web_last"] = pd.to_datetime(st["date_web_last"].str.strip(), errors="coerce", format="%Y-%m")
    st = st[st["stn_num"] != ""]
    st = st.sort_values(["stn_num", "stn_type", "name"], kind="stable")
    st = st.drop_duplicates(["stn_num", "stn_type"]).reset_index(drop=True)
    st["active"] = st["date_close"] == ""
    return st


def network_series(st):
    last_year = int(max(st["web_last"].dt.year.max(), st["close"].dt.year.max(),
                        st["open"].dt.year.max()))
    ok = st.dropna(subset=["open"])
    first_year = int(ok["open"].dt.year.min())
    years = list(range(first_year, last_year + 1))
    o = ok["open"].dt.year.to_numpy()
    c = ok["close"].dt.year.fillna(last_year).to_numpy()
    types = sorted(ok["stn_type"].unique(), key=lambda t: (t not in STATION_TYPES, t))
    series = []
    yr = np.array(years)[:, None]
    for t in types:
        m = (ok["stn_type"] == t).to_numpy()
        counts = ((o[m][None, :] <= yr) & (c[m][None, :] >= yr)).sum(axis=1)
        series.append({"name": STATION_TYPES.get(t, f"סוג {t}"), "data": [int(v) for v in counts]})
    totals = [sum(s["data"][i] for s in series) for i in range(len(years))]
    return {"x": [str(y) for y in years], "series": series, "totals": totals}


def elevation_bins(st):
    a = st[st["active"]].dropna(subset=["hgt"])
    if a.empty:
        return None
    lo = (a["hgt"] // 100 * 100).astype(int)
    counts = lo.value_counts().sort_index()
    rng = range(int(counts.index.min()), int(counts.index.max()) + 1, 100)
    rows = [{"label": f"{_num(b, 0)} עד {_num(b + 99, 0)}", "count": int(counts.get(b, 0))}
            for b in rng]
    low = a.sort_values(["hgt", "name"], kind="stable").iloc[0]
    high = a.sort_values(["hgt", "name"], ascending=[False, True], kind="stable").iloc[0]
    return {"x": [r["label"] for r in rows], "y": [r["count"] for r in rows], "rows": rows,
            "low": {"name": low["name"], "hgt": int(low["hgt"])},
            "high": {"name": high["name"], "hgt": int(high["hgt"])}, "n": int(len(a))}


# ---------------------------------------------------------------- daily
def _prep_daily(df):
    d = pd.DataFrame({"stn": _clean(df["stn_num"])})
    d["dt"] = pd.to_datetime(df["time_obs"].str.strip(), errors="coerce", format="%Y-%m-%d")
    d["tx"] = pd.to_numeric(df["tmp_air_max"], errors="coerce")
    d["tn"] = pd.to_numeric(df["tmp_air_min"], errors="coerce")
    for col, _ in PHENOMENA:
        d[col] = pd.to_numeric(df[col], errors="coerce")
    d = d.dropna(subset=["dt"])
    d = d[d["stn"] != ""]
    d["y"] = d["dt"].dt.year
    d["m"] = d["dt"].dt.month
    return d


def last_complete_year(dates):
    mx = dates.max()
    return int(mx.year) if (mx.month == 12 and mx.day == 31) else int(mx.year) - 1


def temp_anomalies(d, t_last):
    g = d.groupby(["stn", "y"]).agg(nx=("tx", "count"), mx=("tx", "mean"),
                                    nn=("tn", "count"), mn=("tn", "mean"),
                                    hot=("hot", "sum")).reset_index()
    # The in-progress year can pass MIN_DAYS before December is in; cut it.
    g = g[(g["nx"] >= MIN_DAYS) & (g["nn"] >= MIN_DAYS) & (g["y"] <= t_last)]
    b = g[(g["y"] >= BASE_FIRST) & (g["y"] <= BASE_LAST)]
    base = b.groupby("stn").agg(k=("y", "count"), bx=("mx", "mean"), bn=("mn", "mean"),
                                bh=("hot", "mean"))
    base = base[base["k"] >= MIN_BASE_YEARS]
    g = g.merge(base, left_on="stn", right_index=True)
    g["ax"] = g["mx"] - g["bx"]
    g["an"] = g["mn"] - g["bn"]
    g["ah"] = g["hot"] - g["bh"]
    yr = g.groupby("y").agg(n=("stn", "count"), ax=("ax", "mean"), an=("an", "mean"),
                            ah=("ah", "mean")).sort_index()
    yr = yr[yr["n"] >= MIN_STATIONS]
    return yr, int(len(base))


def climatology(d, st, window):
    y0, y1 = window
    w = d[(d["y"] >= y0) & (d["y"] <= y1)]
    full = w.groupby(["stn", "y"])["tx"].count()
    full = full[full >= MIN_DAYS].reset_index().groupby("stn").size()
    need = max(1, int(round((y1 - y0 + 1) * 0.8)))
    elig = sorted(full[full >= need].index)
    lat = st.drop_duplicates("stn_num").set_index("stn_num")["lat"]
    names = _station_names(st)
    cand = pd.DataFrame({"stn": elig})
    cand["lat"] = cand["stn"].map(lat)
    cand = cand.dropna(subset=["lat"]).sort_values(["lat", "stn"], kind="stable").reset_index(drop=True)
    if len(cand) < 3:
        return None
    idx = sorted(set(int(round(i)) for i in np.linspace(0, len(cand) - 1, min(CLIMATE_ROWS, len(cand)))))
    pick = cand.iloc[idx]
    mm = (w[w["stn"].isin(pick["stn"])].groupby(["stn", "m"])["tx"].mean())
    rows, cells, table = [], [], []
    for yi, s in enumerate(pick["stn"]):  # south first: ECharts draws the first category at the bottom
        vals = []
        for mi in range(1, 13):
            v = mm.get((s, mi))
            v = None if v is None or pd.isna(v) else round(float(v), 1)
            vals.append(v)
            if v is not None:
                cells.append([mi - 1, yi, v])
        rows.append(_name(names, s))
        table.append({"name": _name(names, s), "vals": vals})
    vmin = min(c[2] for c in cells)
    vmax = max(c[2] for c in cells)
    return {"rows": rows, "months": MONTHS_HE, "cells": cells, "table": table[::-1],
            "min": float(np.floor(vmin)), "max": float(np.ceil(vmax)),
            "n_eligible": int(len(cand))}


def records(d, names, col, hottest):
    v = d.dropna(subset=[col])
    v = v.sort_values([col, "dt", "stn"], ascending=[not hottest, True, True], kind="stable")
    v = v.drop_duplicates("stn").head(TOP_N)
    return [{"name": _name(names, s), "value": round(float(t), 1), "date": _date_he(dt)}
            for s, t, dt in zip(v["stn"], v[col], v["dt"])]


def phenomena(d):
    rows, cells, table = [], [], []
    vmax = 0.0
    for yi, (col, label) in enumerate(PHENOMENA):
        rep = d.dropna(subset=[col])
        if rep.empty:
            continue
        g = rep.groupby("m")[col].agg(["count", "sum"])
        vals = []
        for mi in range(1, 13):
            if mi in g.index and g.loc[mi, "count"] > 0:
                p = round(float(g.loc[mi, "sum"] / g.loc[mi, "count"] * 100), 2)
            else:
                p = None
            vals.append(p)
            if p is not None:
                cells.append([mi - 1, len(rows), p, int(g.loc[mi, "count"])])
                vmax = max(vmax, p)
        rows.append(label)
        total_rep = int(g["count"].sum())
        total_yes = int(g["sum"].sum())
        table.append({"name": label, "vals": vals, "days": total_yes, "reports": total_rep,
                      "peak": MONTHS_HE[int(g["sum"].div(g["count"]).idxmax()) - 1]})
    if not rows:
        return None
    return {"rows": rows, "months": MONTHS_HE, "cells": cells, "table": table,
            "max": float(np.ceil(vmax))}


# ---------------------------------------------------------------- rain
def _prep_rain(df):
    r = pd.DataFrame({"stn": _clean(df["stn_num"])})
    r["dt"] = pd.to_datetime(df["time_obs"].str.strip(), errors="coerce", format="%Y-%m")
    r["rain"] = pd.to_numeric(df["rain_ttl"], errors="coerce")
    r["days"] = pd.to_numeric(df["rain_days_num"], errors="coerce")
    r["maxv"] = pd.to_numeric(df["rain_max_val"], errors="coerce")
    r["maxd"] = pd.to_numeric(df["rain_max_day"], errors="coerce")
    r["maxc"] = _clean(df["rain_max_code"])
    r = r.dropna(subset=["dt"])
    r = r[r["stn"] != ""]
    r["y"] = r["dt"].dt.year
    r["m"] = r["dt"].dt.month
    r["season"] = np.where(r["m"] >= 8, r["y"], r["y"] - 1)
    return r


def rain_seasons(r):
    wet = r[r["m"].isin(WET_MONTHS)].dropna(subset=["rain"])
    kw = wet.groupby(["stn", "season"])["m"].nunique()
    tot = r.dropna(subset=["rain"]).groupby(["stn", "season"])["rain"].sum()
    s = pd.DataFrame({"tot": tot}).join(kw.rename("kw"), how="inner")
    s = s[s["kw"] == len(WET_MONTHS)].reset_index()
    b = s[(s["season"] >= RAIN_BASE_FIRST) & (s["season"] <= RAIN_BASE_LAST)]
    base = b.groupby("stn").agg(k=("tot", "count"), norm=("tot", "mean"))
    base = base[(base["k"] >= MIN_RAIN_BASE) & (base["norm"] > 0)]
    f = s.merge(base, left_on="stn", right_index=True)
    f["pct"] = f["tot"] / f["norm"] * 100
    idx = f.groupby("season").agg(n=("stn", "count"), med=("pct", "median")).sort_index()
    idx = idx[idx["n"] >= MIN_RAIN_STATIONS]
    return idx, base


def rain_months(r, base):
    b = r[r["stn"].isin(base.index) & (r["season"] >= RAIN_BASE_FIRST)
          & (r["season"] <= RAIN_BASE_LAST)]
    tot = b.groupby("m")["rain"].sum()
    days = b.groupby("m")["days"].mean()
    allr = tot.sum()
    if not allr:
        return None
    rows = []
    for mi in SEASON_MONTHS:
        rows.append({"label": MONTHS_HE[mi - 1],
                     "share": round(float(tot.get(mi, 0) / allr * 100), 1),
                     "days": round(float(days.get(mi, 0) if pd.notna(days.get(mi, np.nan)) else 0), 1)})
    return rows


def rain_gradient(base, st):
    info = st.drop_duplicates("stn_num").set_index("stn_num")
    g = base.join(info[["lat", "hgt", "name"]], how="inner").dropna(subset=["lat"])
    g = g.sort_values(["lat", "norm"], kind="stable")
    pts = [[round(float(la), 3), round(float(n), 0), nm, int(h) if pd.notna(h) else None]
           for la, n, nm, h in zip(g["lat"], g["norm"], g["name"], g["hgt"])]
    wet = g.sort_values(["norm", "name"], ascending=[False, True], kind="stable").iloc[0]
    dry = g.sort_values(["norm", "name"], kind="stable").iloc[0]
    corr = float(np.corrcoef(g["lat"], g["norm"])[0, 1]) if len(g) >= 10 else None
    return {"points": pts, "n": int(len(g)),
            "wet": {"name": wet["name"], "mm": float(wet["norm"])},
            "dry": {"name": dry["name"], "mm": float(dry["norm"])}, "corr": corr}


def rain_max_records(r, names):
    v = r[(r["maxc"] == "0")].dropna(subset=["maxv"])
    v = v.sort_values(["maxv", "dt", "stn"], ascending=[False, True, True], kind="stable")
    v = v.drop_duplicates("stn").head(TOP_N)
    out = []
    for s, val, dt, day in zip(v["stn"], v["maxv"], v["dt"], v["maxd"]):
        date = (f"{int(day)}.{dt.month}.{dt.year}" if pd.notna(day) and 1 <= day <= 31
                else f"{MONTHS_HE[dt.month - 1]} {dt.year}")
        out.append({"name": _name(names, s), "value": round(float(val), 1), "date": date})
    return out


def totalizers(df):
    t = pd.DataFrame({"stn": _clean(df["stn_num"])})
    t["year"] = pd.to_numeric(df["time_obs"], errors="coerce")
    t["rain"] = pd.to_numeric(df["rain_ttl"], errors="coerce")
    t = t.dropna(subset=["year", "rain"])
    g = t.groupby("year").agg(n=("rain", "count"), med=("rain", "median")).sort_index()
    g = g[g["n"] >= MIN_TOTALIZERS]
    if len(g) < 3:
        return None
    return {"x": [str(int(y)) for y in g.index], "y": [round(float(v), 1) for v in g["med"]],
            "n": [int(v) for v in g["n"]], "overall": round(float(g["med"].median()), 1),
            "stations": int(t["stn"].nunique())}


# ---------------------------------------------------------------- radiation
def _prep_radiation(df):
    r = pd.DataFrame({"stn": _clean(df["stn_num"]), "type": _clean(df["rad_type"])})
    r["dt"] = pd.to_datetime(df["time_obs"].str.strip(), errors="coerce", format="%Y-%m-%d")
    for h in RAD_HOURS:
        r[h] = pd.to_numeric(df[h], errors="coerce")
    r = r.dropna(subset=["dt"])
    r = r[(r["type"] == GLOBAL_RAD) & (r["stn"] != "")]
    r["y"] = r["dt"].dt.year
    r["m"] = r["dt"].dt.month
    r["kwh"] = r[RAD_HOURS].sum(axis=1, min_count=len(RAD_HOURS)) / 1000
    return r


def radiation(r, names):
    if r.empty:
        return None
    y1 = last_complete_year(r["dt"])
    y0 = y1 - WINDOW_YEARS + 1
    w = r[(r["y"] >= y0) & (r["y"] <= y1)]
    full = w.dropna(subset=["kwh"])
    counts = full.groupby("stn")["kwh"].count()
    keep = sorted(counts[counts >= 3 * 365].index)
    if not keep:
        return None
    full = full[full["stn"].isin(keep)]
    mm = full.groupby(["stn", "m"])["kwh"].mean()
    avg = full.groupby("stn")["kwh"].mean()
    order = sorted(keep, key=lambda s: (-round(float(avg[s]), 3), _name(names, s)))
    series = [{"name": _name(names, s),
               "data": [round(float(mm.get((s, mi), np.nan)), 2) if pd.notna(mm.get((s, mi), np.nan)) else None
                        for mi in range(1, 13)]} for s in order]
    allm = full.groupby("m")["kwh"].mean()
    hours = w[w["stn"].isin(keep)].groupby("m")[RAD_HOURS].mean()
    cells = []
    for mi in range(1, 13):
        for hi, h in enumerate(RAD_HOURS):
            v = hours[h].get(mi, np.nan) if mi in hours.index else np.nan
            if pd.notna(v):
                cells.append([hi, mi - 1, int(round(float(v)))])
    hour_labels = [f"{int(h[4:]) - 1}-{int(h[4:])}" for h in RAD_HOURS]
    peak = max(cells, key=lambda c: (c[2], -c[1], -c[0])) if cells else None
    return {"window": [y0, y1], "months": MONTHS_HE, "series": series,
            "avg": {_name(names, s): round(float(avg[s]), 2) for s in order},
            "all_month": {int(k): round(float(v), 2) for k, v in allm.items()},
            "hours": hour_labels, "cells": cells,
            "hmax": int(max(c[2] for c in cells)) if cells else 0,
            "peak": ({"hour": hour_labels[peak[0]], "month": MONTHS_HE[peak[1]], "w": peak[2]}
                     if peak else None)}


# ---------------------------------------------------------------- insights
def insight_warming(yr):
    if len(yr) < 15:
        return None
    last = yr.tail(WINDOW_YEARS)
    v = float(last["ax"].mean())
    y0, y1 = int(last.index.min()), int(last.index.max())
    if abs(v) < 0.2:
        return (f"בשנים {y0}-{y1} טמפרטורת המקסימום השנתית נותרה קרובה לממוצע "
                f"{BASE_FIRST}-{BASE_LAST} (חריגה ממוצעת של {_signed(v, 2)}°).")
    word = "גבוהה" if v > 0 else "נמוכה"
    warm = int((last["ax"] > 0).sum())
    return (f"בשנים {y0}-{y1} הייתה טמפרטורת המקסימום הממוצעת {word} ב-{abs(v):.2f}° "
            f"מהנורמה של {BASE_FIRST}-{BASE_LAST}; {warm} מתוך {len(last)} השנים היו חמות מהנורמה.")


def insight_warmest(yr):
    if len(yr) < 15:
        return None
    top = yr.sort_values(["ax"], ascending=False, kind="stable").head(3)
    recent_from = int(yr.index.max()) - WINDOW_YEARS + 1
    k = int((top.index >= recent_from).sum())
    if k < 2:
        return None
    ys = [f"{int(y)} ({_signed(float(a), 2)}°)" for y, a in top["ax"].items()]
    return (f"שלוש השנים החמות ביותר בסדרה: {ys[0]}, {ys[1]} ו-{ys[2]}; "
            f"{k} מהן ב-{WINDOW_YEARS} השנים האחרונות.")


def insight_hot_days(yr):
    if len(yr) < 15:
        return None
    last = yr.tail(WINDOW_YEARS)
    v = float(last["ah"].mean())
    if abs(v) < 1:
        return None
    word = "יותר" if v > 0 else "פחות"
    return (f"בשנים {int(last.index.min())}-{int(last.index.max())} נמדדו בממוצע בכל תחנה "
            f"{abs(v):.1f} ימים {word} עם מקסימום של {HOT_C:.0f}° ומעלה, לעומת הנורמה של "
            f"{BASE_FIRST}-{BASE_LAST}.")


def insight_rain_last(idx):
    if idx.empty:
        return None
    s = int(idx.index.max())
    p = float(idx.loc[s, "med"])
    n = int(idx.loc[s, "n"])
    if p < DRY_PCT:
        state = "עונה שחונה"
    elif p > WET_PCT:
        state = "עונה גשומה מהרגיל"
    else:
        state = "עונה קרובה לממוצע"
    return (f"עונת הגשמים {_season(s)} הייתה {state}: {p:.0f}% מהממוצע הרב-שנתי "
            f"(חציון של {n:,} תחנות עם עונה מלאה).")


def insight_rain_extremes(idx):
    if len(idx) < 20:
        return None
    srt = idx.sort_values(["med"], kind="stable")
    dry, wet = srt.index[0], srt.index[-1]
    return (f"בסדרה של {len(idx)} עונות, העונה השחונה ביותר הייתה {_season(dry)} "
            f"({srt.loc[dry, 'med']:.0f}% מהממוצע) והגשומה ביותר {_season(wet)} "
            f"({srt.loc[wet, 'med']:.0f}%).")


def insight_rain_months(rows):
    if not rows:
        return None
    top = sorted(rows, key=lambda r: (-r["share"], SEASON_MONTHS.index(MONTHS_HE.index(r["label"]) + 1)))
    three = top[:3]
    share = sum(r["share"] for r in three)
    if share < 50:
        return None
    names = ", ".join(r["label"] for r in three)
    return (f"{share:.0f}% מגשם השנה יורדים בשלושה חודשים בלבד ({names}); "
            f"{top[0]['label']} הוא החודש הגשום ביותר עם {top[0]['share']:.1f}% מהכמות השנתית.")


def insight_gradient(g):
    if not g or g["n"] < 10 or g["dry"]["mm"] <= 0:
        return None
    ratio = g["wet"]["mm"] / g["dry"]["mm"]
    if ratio < 3:
        return None
    return (f"פערי הגשם בין צפון לדרום עצומים: בתחנה {g['wet']['name']} יורדים בממוצע "
            f"{g['wet']['mm']:,.0f} מ\"מ בעונה, ובתחנה {g['dry']['name']} {g['dry']['mm']:,.0f} מ\"מ בלבד "
            f"(פי {ratio:,.0f}).")


def insight_heat_record(hot, cold):
    if not hot or not cold:
        return None
    h, c = hot[0], cold[0]
    return (f"הטמפרטורה הגבוהה ביותר בארכיון היומי: {_num(h['value'])}° ב{h['name']} ({h['date']}); "
            f"הנמוכה ביותר: {_num(c['value'])}° ב{c['name']} ({c['date']}).")


def insight_radiation(rad):
    if not rad or len(rad["all_month"]) < 12:
        return None
    am = rad["all_month"]
    hi = max(am, key=lambda k: (am[k], -k))
    lo = min(am, key=lambda k: (am[k], k))
    if am[lo] <= 0:
        return None
    return (f"קרינת השמש הגלובלית היומית ב{MONTHS_HE[hi - 1]} ({am[hi]:.1f} קוט\"ש למ\"ר) "
            f"גבוהה פי {am[hi] / am[lo]:.1f} מזו של {MONTHS_HE[lo - 1]} ({am[lo]:.1f}), "
            f"בממוצע תחנות הקרינה בשנים {rad['window'][0]}-{rad['window'][1]}.")


def insight_network(st, net):
    a = st[st["active"]]
    if a.empty:
        return None
    peak_i = int(np.argmax(net["totals"]))
    auto = int(a.loc[a["stn_auto"] == "1", "stn_num"].nunique())
    return (f"מתוך {st['stn_num'].nunique():,} תחנות שפעלו אי פעם, {a['stn_num'].nunique():,} פעילות כיום ({auto:,} מהן אוטומטיות); "
            f"שיא הרשת נרשם ב-{net['x'][peak_i]} עם {net['totals'][peak_i]:,} תחנות פעילות.")


def insight_phenomena(ph):
    if not ph:
        return None
    t = {r["name"]: r for r in ph["table"]}
    parts = [f"{n} ב{t[n]['peak']}" for n in ["רעמים", "ברד", "שלג", "סופת חול"] if n in t]
    if len(parts) < 2:
        return None
    return "שיא השכיחות של תופעות מזג האוויר לפי חודש: " + ", ".join(parts) + "."


def insight_totalizers(tz):
    if not tz:
        return None
    i = int(np.argmin(tz["y"]))
    return (f"במדי הגשם המאוגרים שבנגב ובערבה החציון השנתי הנמוך ביותר נרשם ב-{tz['x'][i]} "
            f"({tz['y'][i]:.1f} מ\"מ), לעומת חציון רב-שנתי של {tz['overall']:.1f} מ\"מ.")


# ---------------------------------------------------------------- compute
def compute(frames):
    st = _prep_stations(frames["stations"])
    names = _station_names(st)

    d = _prep_daily(frames["daily"])
    d["hot"] = (d["tx"] >= HOT_C).astype(int)
    t_last = last_complete_year(d["dt"])
    yr, n_base = temp_anomalies(d, t_last)
    clim = climatology(d, st, (t_last - WINDOW_YEARS + 1, t_last))
    hot = records(d, names, "tx", True)
    cold = records(d, names, "tn", False)
    ph = phenomena(d)
    d_first, d_last = d["dt"].min(), d["dt"].max()
    n_daily_st = int(d["stn"].nunique())
    del d

    r = _prep_rain(frames["rain_monthly"])
    ridx, rbase = rain_seasons(r)
    rmonths = rain_months(r, rbase)
    grad = rain_gradient(rbase, st) if len(rbase) else None
    rmax = rain_max_records(r, names)
    r_first_year = int(r["y"].min())
    del r

    tz = totalizers(frames["totalizers"])
    rad = radiation(_prep_radiation(frames["radiation"]), names)
    net = network_series(st)
    elev = elevation_bins(st)

    # ---- KPIs
    # A station number can appear once per station type; count stations, not rows.
    n_stations = int(st["stn_num"].nunique())
    n_active = int(st.loc[st["active"], "stn_num"].nunique())
    first_year = int(st["open"].dt.year.min())
    last_year = int(net["x"][-1])
    kpis = {
        "stations": {"value": n_stations, "display": _int(n_stations), "tone": "brand"},
        "active": {"value": n_active, "display": _int(n_active), "tone": "brand"},
        "span": {"value": [first_year, last_year], "display": f"{first_year}–{last_year}",
                 "tone": "info"},
    }
    if hot:
        kpis["hottest"] = {"value": hot[0]["value"], "display": _num(hot[0]["value"]),
                           "tone": "danger"}
    if cold:
        kpis["coldest"] = {"value": cold[0]["value"], "display": _num(cold[0]["value"]),
                           "tone": "info"}
    if len(yr):
        la = float(yr["ax"].iloc[-1])
        kpis["anomaly"] = {"value": round(la, 2), "display": _signed(la, 2),
                           "tone": "danger" if la >= 0.5 else "warn" if la > 0 else "ok"}
    if len(ridx):
        lp = float(ridx["med"].iloc[-1])
        kpis["rain"] = {"value": round(lp, 1), "display": f"{lp:.0f}%",
                        "tone": "danger" if lp < DRY_PCT else "warn" if lp < 95 else "ok" if lp > 110 else "brand"}
    if rmax:
        kpis["rain_max"] = {"value": rmax[0]["value"], "display": _num(rmax[0]["value"]),
                            "tone": "brand"}

    # ---- insights
    rules = [
        ("warming", insight_warming(yr)),
        ("warmest", insight_warmest(yr)),
        ("hot_days", insight_hot_days(yr)),
        ("rain_last", insight_rain_last(ridx)),
        ("rain_extremes", insight_rain_extremes(ridx)),
        ("rain_months", insight_rain_months(rmonths)),
        ("gradient", insight_gradient(grad)),
        ("heat_record", insight_heat_record(hot, cold)),
        ("radiation", insight_radiation(rad)),
        ("network", insight_network(st, net)),
        ("phenomena", insight_phenomena(ph)),
        ("totalizers", insight_totalizers(tz)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- charts
    charts = {"network": net}
    labels = {}
    peak_i = int(np.argmax(net["totals"]))
    labels["network_aria"] = (f"תרשים שטח מוערם: מספר התחנות הפעילות בכל שנה לפי סוג תחנה, "
                              f"{net['x'][0]} עד {net['x'][-1]}. השיא ב-{net['x'][peak_i]} עם "
                              f"{net['totals'][peak_i]:,} תחנות.")
    labels["network_lede"] = (f"תחנה נספרת כפעילה בכל שנה שבין שנת פתיחתה לשנת סגירתה. "
                              f"כיום פעילות {n_active:,} תחנות, לעומת שיא של "
                              f"{net['totals'][peak_i]:,} ב-{net['x'][peak_i]}.")
    if elev:
        charts["elevation"] = elev
        labels["elevation_aria"] = (f"היסטוגרמה: גובה {elev['n']:,} התחנות הפעילות מעל פני הים, "
                                    f"מ-{_num(elev['low']['hgt'], 0)} מ' ב{elev['low']['name']} "
                                    f"עד {_num(elev['high']['hgt'], 0)} מ' ב{elev['high']['name']}.")
        labels["elevation_lede"] = (f"התחנה הנמוכה ביותר שפעילה כיום היא {elev['low']['name']} "
                                    f"({_num(elev['low']['hgt'], 0)} מ'), והגבוהה ביותר "
                                    f"{elev['high']['name']} ({_num(elev['high']['hgt'], 0)} מ').")
    if len(yr) >= 3:
        charts["anomaly"] = {"x": [str(int(y)) for y in yr.index],
                             "max": [round(float(v), 2) for v in yr["ax"]],
                             "min": [round(float(v), 2) for v in yr["an"]],
                             "n": [int(v) for v in yr["n"]],
                             "hot": [round(float(v), 1) for v in yr["ah"]]}
        warmest_y = int(yr["ax"].idxmax())
        labels["anomaly_aria"] = (f"תרשים עמודות וקו: חריגת טמפרטורת המקסימום והמינימום השנתית "
                                  f"מהנורמה של {BASE_FIRST}-{BASE_LAST}, {int(yr.index.min())} עד "
                                  f"{int(yr.index.max())}. השנה החמה ביותר: {warmest_y} "
                                  f"({_signed(float(yr['ax'].max()), 2)}°).")
        labels["anomaly_note"] = (f"ממוצע החריגות של {n_base:,} תחנות שלכל אחת מהן לפחות "
                                  f"{MIN_BASE_YEARS} שנים מלאות בתקופת הנורמה; שנה מלאה היא שנה עם "
                                  f"{MIN_DAYS} ימי מדידה לפחות, ומוצגות רק שנים עם {MIN_STATIONS} "
                                  f"תחנות לפחות (לכן השנה האחרונה, החלקית, אינה מוצגת).")
        labels["hot_aria"] = (f"תרשים עמודות: ההפרש במספר הימים עם מקסימום של {HOT_C:.0f}° ומעלה "
                              f"לתחנה, לעומת הנורמה של {BASE_FIRST}-{BASE_LAST}, "
                              f"{int(yr.index.min())} עד {int(yr.index.max())}.")
        labels["hot_title"] = f"ימים חמים ({HOT_C:.0f}° ומעלה) לעומת הנורמה"
        labels["hot_note"] = (f"לכל תחנה: מספר הימים בשנה עם טמפרטורת מקסימום של {HOT_C:.0f}° "
                              f"ומעלה פחות הממוצע שלה ב-{BASE_FIRST}-{BASE_LAST}; מוצג הממוצע על "
                              f"פני התחנות (אותן תחנות ושנים כמו בתרשים החריגות).")
    if clim:
        charts["climate"] = clim
        labels["climate_aria"] = (f"מפת חום: טמפרטורת המקסימום הממוצעת בכל חודש ב-{len(clim['rows'])} "
                                  f"תחנות מצפון לדרום, {t_last - WINDOW_YEARS + 1} עד {t_last}.")
        labels["climate_note"] = (f"ממוצע טמפרטורת המקסימום היומית לפי חודש, {t_last - WINDOW_YEARS + 1}-"
                                  f"{t_last}. נבחרו {len(clim['rows'])} תחנות בפריסה שווה לפי קו רוחב "
                                  f"מתוך {clim['n_eligible']:,} תחנות עם רוב השנים מלאות בתקופה; "
                                  f"השורות מסודרות מצפון (למעלה) לדרום.")
    if hot and cold:
        charts["hot"] = {"names": [h["name"] for h in hot], "values": [h["value"] for h in hot],
                         "dates": [h["date"] for h in hot]}
        charts["cold"] = {"names": [c["name"] for c in cold], "values": [c["value"] for c in cold],
                          "dates": [c["date"] for c in cold]}
        labels["hot_rec_aria"] = (f"תרשים עמודות: {len(hot)} התחנות עם טמפרטורת המקסימום הגבוהה "
                                  f"ביותר שנמדדה בהן. השיא: {_num(hot[0]['value'])}° ב{hot[0]['name']}.")
        labels["cold_rec_aria"] = (f"תרשים עמודות: {len(cold)} התחנות עם טמפרטורת המינימום הנמוכה "
                                   f"ביותר שנמדדה בהן. השיא: {_num(cold[0]['value'])}° ב{cold[0]['name']}.")
        labels["records_lede"] = (f"שיא אחד לכל תחנה, מתוך נתוני הטמפרטורה היומיים של {n_daily_st:,} "
                                  f"תחנות, {d_first.year}-{d_last.year}.")
    if ph:
        charts["phenomena"] = ph
        labels["phen_aria"] = (f"מפת חום: אחוז הימים שבהם דווחה כל תופעת מזג אוויר, לפי חודש, "
                               f"מתוך ימי הדיווח בתחנות המאוישות.")
        labels["phen_note"] = ("אחוז הימים עם התופעה מתוך הימים שבהם התחנה דיווחה על התופעה "
                               "(דיווח קיים בעיקר בתחנות מאוישות, שמספרן ירד עם השנים).")
    if len(ridx):
        charts["rain_index"] = {"x": [_season(s) for s in ridx.index],
                                "y": [round(float(v), 1) for v in ridx["med"]],
                                "n": [int(v) for v in ridx["n"]], "dry": DRY_PCT, "wet": WET_PCT}
        labels["rain_index_aria"] = (f"תרשים עמודות: כמות הגשם בכל עונה באחוזים מהממוצע הרב-שנתי, "
                                     f"{_season(ridx.index.min())} עד {_season(ridx.index.max())}. "
                                     f"העונה האחרונה: {float(ridx['med'].iloc[-1]):.0f}%.")
        labels["rain_index_note"] = (f"לכל תחנה: כמות העונה (אוגוסט עד יולי) חלקי הממוצע שלה בעונות "
                                     f"{_season(RAIN_BASE_FIRST)}-{_season(RAIN_BASE_LAST)}; מוצג החציון "
                                     f"על פני {len(rbase):,} תחנות. נכללות רק עונות מלאות (כל החודשים "
                                     f"אוקטובר עד אפריל נמדדו), ורק עונות עם {MIN_RAIN_STATIONS} "
                                     f"תחנות לפחות. עמודה אדומה: עונה שחונה (פחות מ-{DRY_PCT}% "
                                     f"מהממוצע); ירוקה: עונה גשומה (יותר מ-{WET_PCT}%).")
    if rmonths:
        charts["rain_months"] = {"x": [m["label"] for m in rmonths],
                                 "share": [m["share"] for m in rmonths],
                                 "days": [m["days"] for m in rmonths], "rows": rmonths}
        peak = max(rmonths, key=lambda m: m["share"])
        labels["rain_months_aria"] = (f"תרשים עמודות וקו: חלקו של כל חודש בגשם השנתי וממוצע ימי "
                                      f"הגשם בחודש. החודש הגשום ביותר: {peak['label']} "
                                      f"({peak['share']:.1f}%).")
        labels["rain_months_note"] = (f"{len(rbase):,} תחנות, עונות {_season(RAIN_BASE_FIRST)}-"
                                      f"{_season(RAIN_BASE_LAST)}.")
    if grad:
        charts["gradient"] = grad
        corr_txt = (f" מקדם המתאם בין קו הרוחב לכמות הגשם: {grad['corr']:.2f}."
                    if grad["corr"] is not None else "")
        labels["gradient_aria"] = (f"תרשים פיזור: כמות הגשם השנתית הממוצעת ב-{grad['n']:,} תחנות "
                                   f"לפי קו הרוחב שלהן.{corr_txt}")
        labels["gradient_lede"] = (f"כל נקודה היא תחנה: הממוצע העונתי שלה בעונות "
                                   f"{_season(RAIN_BASE_FIRST)}-{_season(RAIN_BASE_LAST)}. "
                                   f"מ-{grad['dry']['mm']:,.0f} מ\"מ ב{grad['dry']['name']} ועד "
                                   f"{grad['wet']['mm']:,.0f} מ\"מ ב{grad['wet']['name']}.{corr_txt}")
    if rmax:
        charts["rain_max"] = {"names": [x["name"] for x in rmax], "values": [x["value"] for x in rmax],
                              "dates": [x["date"] for x in rmax], "rows": rmax}
        labels["rain_max_aria"] = (f"תרשים עמודות: {len(rmax)} כמויות הגשם היומיות הגבוהות ביותר, "
                                   f"אחת לכל תחנה. השיא: {_num(rmax[0]['value'])} מ\"מ "
                                   f"ב{rmax[0]['name']} ({rmax[0]['date']}).")
        labels["rain_max_note"] = (f"הכמות היומית המרבית בכל חודש, מתוך קובץ הגשם החודשי "
                                   f"({r_first_year} ואילך); מדידות רגילות בלבד, ללא ערכים "
                                   f"מבויינים או מצטברים.")
    if tz:
        charts["totalizers"] = tz
        labels["tz_aria"] = (f"תרשים עמודות: חציון כמות הגשם השנתית במדי הגשם המאוגרים בנגב "
                             f"ובערבה, {tz['x'][0]} עד {tz['x'][-1]}.")
        labels["tz_note"] = (f"{tz['stations']:,} אוגרי גשם, הנמדדים פעם בעונה באזורים מרוחקים; "
                             f"מוצגות שנים עם {MIN_TOTALIZERS} אוגרים לפחות. הקו המקווקו: החציון "
                             f"הרב-שנתי ({tz['overall']:.1f} מ\"מ).")
    if rad:
        charts["radiation"] = rad
        top = rad["series"][0]["name"]
        labels["rad_aria"] = (f"תרשים קווים: קרינת שמש גלובלית יומית ממוצעת בכל חודש ב-"
                              f"{len(rad['series'])} תחנות קרינה, {rad['window'][0]} עד "
                              f"{rad['window'][1]}. הממוצע השנתי הגבוה ביותר: {top} "
                              f"({rad['avg'][top]:.2f}).")
        labels["rad_note"] = (f"קוט\"ש למ\"ר ליום, {rad['window'][0]}-{rad['window'][1]}; ימים "
                              f"עם כל שעות האור נמדדו, ותחנות עם שלוש שנות מדידה לפחות בתקופה.")
        if rad["peak"]:
            labels["rad_hour_aria"] = (f"מפת חום: קרינה גלובלית ממוצעת (וואט למ\"ר) לפי שעה ביום "
                                       f"וחודש. השיא: {rad['peak']['w']:,} וואט למ\"ר ב{rad['peak']['month']}, "
                                       f"בשעות {rad['peak']['hour']} (UTC).")

    span_txt = f"{first_year}-{last_year}"
    summary = (f"ארכיון מזג האוויר של השירות המטאורולוגי: טמפרטורה, גשם וקרינה מ-{n_stations:,} "
               f"תחנות ({n_active:,} פעילות), {span_txt}. איתור תחנה ונתונים יומיים.")
    if len(summary) > 155:
        summary = (f"ארכיון מזג האוויר של השירות המטאורולוגי: טמפרטורה, גשם וקרינה מ-{n_stations:,} "
                   f"תחנות, {span_txt}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["מזג אוויר", "אקלים", "טמפרטורה", "גשם", "קרינת שמש",
                               "תחנות מטאורולוגיות"],
            "related_ids": ["2f46af1f-9b38-4268-a358-9e69d48bd072",
                            "5e325710-b00f-42cb-ad8c-807eb7d8daec",
                            "d1034fa8-9a8b-4e36-840b-d1af51522d82",
                            "5dd3e67a-17b9-42ab-a3b5-125c3bb6b046"],
            "temporal_coverage": f"{first_year}/{last_year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "labels": labels,
    }
