"""ניטור נחלים: raw chemical monitoring results, 1995 onward.

One row per sample: station code + name, stream group (`נחל/קבוצה`), sample
date, the lab, and ~80 parameter columns. Most parameter columns are sparse
(heavy metals, oils, sulfate were measured only for a few years), so the page
works with the parameters that run through the record:

- organic load: BOD, COD, TOC
- nutrients: NH4, TKN, total N, NO3, NO2, total P
- solids: TSS (105°C)
- bacteria: fecal coliforms (cfu/100 ml)
- salinity: chloride
- field readings (pH, temperature, dissolved oxygen, EC), which stop in the
  2010s; their section states the span computed from the data.

Dates arrive in three shapes: "YYYY-MM-DD HH:MM:SS", an Excel serial
("45746.0") and "DD/MM/YY". All three are parsed; a row with no parsable date
still counts in the station / stream totals but not in any by-year view.

Concentrations span orders of magnitude, so charts use medians on a log axis.
"Recent" is always relative to the newest year in the data, never the clock:
recent5 = the last 5 calendar years, prior5 = the 5 before that, recent10 =
both. Long-term change compares each stream's first 5 sampled years for a
parameter with recent5 (only when the two windows don't overlap).

Station mix differs between years (stations were added and dropped), so the
trend views show per-point sample counts and the insights quote them.
"""
import math

import pandas as pd

STREAM = "נחל/קבוצה"
CODE = "קוד מקווה מים"
NAME = "שם תחנה"
DATE = "תאריך"
LAB = "מעבדה"

# (key, column, Hebrew label, short label, unit)
PARAMS = [
    ("bod", "BODt (mg/l)", "צריכת חמצן ביוכימית (BOD)", "BOD", "מ״ג/ל׳"),
    ("nh4", "NH4 (mg/l)", "אמוניום (NH4)", "אמוניום", "מ״ג/ל׳"),
    ("fcoli", "Fcoli (cfu/100 ml)", "קוליפורמים צואתיים", "קוליפורמים צואתיים", "מושבות ל-100 מ״ל"),
    ("ptot", "Ptot (mg/l)", "זרחן כללי", "זרחן כללי", "מ״ג/ל׳"),
    ("ntot", "Ntot (mg/l)", "חנקן כללי", "חנקן כללי", "מ״ג/ל׳"),
    ("tkn", "TKN (mg/l)", "חנקן קלדל (TKN)", "TKN", "מ״ג/ל׳"),
    ("no3", "NO3 (mg/l)", "חנקה (NO3)", "חנקה", "מ״ג/ל׳"),
    ("no2", "NO2 (mg/l)", "חנקית (NO2)", "חנקית", "מ״ג/ל׳"),
    ("cod", "CODt (mg/l)", "צריכת חמצן כימית (COD)", "COD", "מ״ג/ל׳"),
    ("toc", "Toc (mg/l)", "פחמן אורגני כולל (TOC)", "TOC", "מ״ג/ל׳"),
    ("tss", "TSS105 (mg/l)", "מוצקים מרחפים (TSS)", "מוצקים מרחפים", "מ״ג/ל׳"),
    ("cl", "Cl (mg/l)", "כלוריד (מליחות)", "כלוריד", "מ״ג/ל׳"),
]
PKEY = {p[0]: p for p in PARAMS}
BOX_PARAMS = ["bod", "nh4", "fcoli", "ptot"]
STATION_PARAMS = ["bod", "nh4", "fcoli", "ptot", "cl"]
SEASON_PARAMS = ["fcoli", "bod", "nh4", "cl"]

# field readings: (key, column, label, unit)
FIELD = [
    ("ph", "pH", "חומציות (pH)", ""),
    ("temp", "Temp (°C)", "טמפרטורה", "°C"),
    ("do", "Do (mg/l)", "חמצן מומס", "מ״ג/ל׳"),
    ("doxsat", "Doxsat (%)", "רוויית חמצן", "%"),
    ("ec", "Ec (Mmho/cm)", "מוליכות חשמלית", "mS/cm"),
]
EC_MAX = 100          # EC above this is in µS/cm, not mS/cm: excluded (disclosed)
LOW_DO_SAT = 50       # dissolved-oxygen saturation below 50% = oxygen-poor water

WINDOW = 5            # years per comparison window
MIN_N = 3             # min samples per stream/station in a window to quote a median
STATION_MIN_N = 3
STATION_TOP = 15
CHANGE_BAND = 0.25    # |change| below 25% = "no clear change"
GAP_RATIO = 3.0       # a stream ≥3× another's median is a clear gap
SEASON_RATIO = 1.5    # autumn ≥1.5× spring (or the reverse) = clear seasonal gap
WORSEN_RATIO = 1.5    # recent5 ≥1.5× prior5 = deterioration
LOW_DO_SHARE = 0.2
FLOOR_SHARE = 0.03    # the most common value in the bottom decile, when it holds
                      # ≥3% of all readings, is a reporting floor ("below detection")
DROP_SHARE = 0.6      # latest full year below 60% of the peak year's count
SPRING_MONTHS = {2, 3, 4, 5, 6, 7}   # February-July; August-January = autumn


# ── helpers ──────────────────────────────────────────────────────────────

def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")


def _parse_dates(s):
    s = s.astype(str).str.strip()
    out = pd.to_datetime(s, errors="coerce", format="%Y-%m-%d %H:%M:%S")
    miss = out.isna()
    if miss.any():
        alt = pd.to_datetime(s[miss], errors="coerce", format="%Y-%m-%d")
        out[miss] = alt
    miss = out.isna()
    if miss.any():
        alt = pd.to_datetime(s[miss], errors="coerce", format="%d/%m/%y")
        out[miss] = alt
    miss = out.isna()
    if miss.any():
        alt = pd.to_datetime(s[miss], errors="coerce", format="%d/%m/%Y")
        out[miss] = alt
    miss = out.isna()
    if miss.any():
        serial = pd.to_numeric(s[miss], errors="coerce")
        ok = serial.between(20000, 80000)
        conv = pd.to_datetime("1899-12-30") + pd.to_timedelta(serial.where(ok).round(), unit="D")
        out[miss] = conv
    return out


def _sig(v, digits=4):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    v = float(v)
    if v == 0:
        return 0.0
    mag = int(math.floor(math.log10(abs(v))))
    return round(v, max(0, digits - 1 - mag))


def _fmt(v):
    """Human number: 1,801 / 23.6 / 0.78 / 0.035."""
    if v is None:
        return "-"
    v = float(v)
    a = abs(v)
    if a >= 100:
        s = f"{v:,.0f}"
    elif a >= 10:
        s = f"{v:,.1f}"
    elif a >= 1:
        s = f"{v:.2f}"
    elif a == 0:
        s = "0"
    else:
        s = f"{_sig(v, 2):g}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _pct(x):
    return f"{x * 100:.0f}%"


def _median(s):
    s = s.dropna()
    if not len(s):
        return None
    return float(s.median())


def _pos_median(s):
    m = _median(s)
    return m if m is not None and m > 0 else None


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    vav = "ו-" if last[:1].isdigit() or last[:1].isascii() and last[:1].isalpha() else "ו"
    return ", ".join(items[:-1]) + " " + vav + last


def _bstream(name):
    """'ירדן עליון' -> 'בירדן עליון', 'נחל אילון' -> 'בנחל אילון'."""
    return "ב" + name


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    df = frames["main"].copy()
    for c in (STREAM, CODE, NAME, DATE, LAB):
        df[c] = df[c].astype(str).str.strip()
    df = df[(df[STREAM] != "") & (df[NAME] != "")].copy()
    df["_date"] = _parse_dates(df[DATE])
    df["_y"] = df["_date"].dt.year
    df["_m"] = df["_date"].dt.month
    for key, col, *_ in PARAMS:
        df[key] = _num(df[col])
    for key, col, *_ in FIELD:
        df[key] = _num(df[col])
    df.loc[df["ec"] > EC_MAX, "ec"] = float("nan")

    # Reporting floor per parameter: labs log "below detection" as the
    # smallest reportable value (NO2 0.001 in 88 rows, COD 35, ...). A
    # median sitting on that floor is not a measured level, so the change
    # view and the change/gap insights treat it as unknown; zero and
    # negative entries are dropped from those medians too.
    floors = {}
    for key, *_ in PARAMS:
        v = df[key][df[key] > 0]
        if not len(v):
            continue
        low = v[v <= v.quantile(0.1)]
        vc = low.value_counts()
        f = max(vc.index, key=lambda x: (int(vc[x]), -float(x)))
        if int(vc[f]) >= FLOOR_SHARE * len(v):
            floors[key] = float(f)

    def qmed(s, key):
        m = _median(s[s > 0])
        if m is None or (key in floors and m <= floors[key]):
            return None
        return m
    # station key: code when present, else name
    df["_st"] = df[CODE].where(df[CODE] != "", df[NAME])

    n_total = len(df)
    dated = df[df["_y"].notna()].copy()
    dated["_y"] = dated["_y"].astype(int)
    dated["_m"] = dated["_m"].astype(int)
    y_min, y_max = int(dated["_y"].min()), int(dated["_y"].max())
    recent5 = (y_max - WINDOW + 1, y_max)
    prior5 = (y_max - 2 * WINDOW + 1, y_max - WINDOW)
    recent10 = (prior5[0], y_max)
    years = list(range(y_min, y_max + 1))

    # streams ordered by sample count, then name
    sc = df.groupby(STREAM).size().reset_index(name="n")
    sc = sc.sort_values(["n", STREAM], ascending=[False, True], kind="mergesort")
    streams = sc[STREAM].tolist()

    # station labels: most frequent name per station key, tie → alphabetical
    nm = df.groupby(["_st", NAME]).size().reset_index(name="n")
    nm = nm.sort_values(["_st", "n", NAME], ascending=[True, False, True], kind="mergesort")
    st_name = nm.drop_duplicates("_st").set_index("_st")[NAME].to_dict()
    sm = df.groupby(["_st", STREAM]).size().reset_index(name="n")
    sm = sm.sort_values(["_st", "n", STREAM], ascending=[True, False, True], kind="mergesort")
    st_stream = sm.drop_duplicates("_st").set_index("_st")[STREAM].to_dict()
    st_n = df.groupby("_st").size().to_dict()
    n_stations = len(st_name)

    def win(frame, w):
        return frame[(frame["_y"] >= w[0]) & (frame["_y"] <= w[1])]

    # ── samples by year × stream ──
    yc = dated.groupby(["_y", STREAM]).size()
    by_year = {"years": years, "series": [
        {"name": s, "data": [int(yc.get((y, s), 0)) for y in years]} for s in streams]}
    year_tot = dated.groupby("_y").size()
    year_rows = [{"year": y, "total": int(year_tot.get(y, 0)),
                  "by": [int(yc.get((y, s), 0)) for s in streams]} for y in years]

    # ── yearly medians per param × stream (trend) ──
    trend = {}
    for key, col, label, short, unit in PARAMS:
        g = dated[dated[key].notna()].groupby(["_y", STREAM])[key]
        med = g.median()
        cnt = g.size()
        ser = []
        for s in streams:
            vals, ns = [], []
            for y in years:
                m = med.get((y, s))
                v = _sig(m) if m is not None and not pd.isna(m) and m > 0 else None
                vals.append(v)
                ns.append(int(cnt.get((y, s), 0)))
            ser.append({"name": s, "data": vals, "n": ns})
        trend[key] = {"label": label, "unit": unit, "series": ser}
    param_opts = [{"key": p[0], "label": p[2], "unit": p[4]} for p in PARAMS]

    # ── long-term change: first 5 sampled years vs recent5 ──
    change = {}       # (stream, key) -> dict
    for key, *_ in PARAMS:
        sub = dated[dated[key].notna()]
        for s in streams:
            ss = sub[sub[STREAM] == s]
            if not len(ss):
                continue
            yrs = sorted(ss["_y"].unique())
            first = yrs[:WINDOW]
            if not first or first[-1] >= recent5[0]:
                continue
            early = ss[ss["_y"].isin(first)][key]
            rec = win(ss, recent5)[key]
            if len(early) < MIN_N or len(rec) < MIN_N:
                continue
            e, r = qmed(early, key), qmed(rec, key)
            if e is None or r is None:
                continue
            change[(s, key)] = {"early": e, "recent": r, "e_from": int(first[0]),
                                "e_to": int(first[-1]), "ne": int(len(early)),
                                "nr": int(len(rec)), "ratio": r / e}
    heat_params = [k for k, *_ in PARAMS if any((s, k) in change for s in streams)]
    heat_streams = [s for s in streams if any((s, k) in change for k in heat_params)]
    heat_cells = []
    for xi, k in enumerate(heat_params):
        for yi, s in enumerate(heat_streams):
            c = change.get((s, k))
            if not c:
                continue
            lr = math.log2(c["ratio"])
            heat_cells.append([xi, yi, round(max(-3.0, min(3.0, lr)), 3),
                               round((c["ratio"] - 1) * 100), _fmt(c["early"]), _fmt(c["recent"]),
                               f"{c['e_from']}-{c['e_to']}", c["ne"], c["nr"]])
    change_rows = []
    for k in heat_params:
        cells = []
        for s in heat_streams:
            c = change.get((s, k))
            cells.append(None if not c else {
                "early": _fmt(c["early"]), "recent": _fmt(c["recent"]),
                "pct": f"{(c['ratio'] - 1) * 100:+.0f}%".replace("-", "−"),
                "span": f"{c['e_from']}-{c['e_to']}"})
        change_rows.append({"label": PKEY[k][2], "unit": PKEY[k][4], "cells": cells})
    change_chart = {"params": [PKEY[k][3] for k in heat_params], "streams": heat_streams,
                    "cells": heat_cells}

    # ── distributions, recent10, per stream ──
    rec10 = win(dated, recent10)
    box = {}
    box_rows = []
    for k in BOX_PARAMS:
        names, data, ns = [], [], []
        for s in streams:
            v = rec10[(rec10[STREAM] == s) & (rec10[k] > 0)][k]
            if len(v) < MIN_N:
                continue
            q = v.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).tolist()
            names.append(s)
            data.append([_sig(x) for x in q])
            ns.append(int(len(v)))
            box_rows.append({"param": PKEY[k][3], "unit": PKEY[k][4], "stream": s, "n": int(len(v)),
                             "q": [_fmt(x) for x in q]})
        box[k] = {"label": PKEY[k][2], "unit": PKEY[k][4], "names": names, "data": data, "n": ns}

    # ── stations, recent10 ──
    st_rows = []
    for st, g in rec10.groupby("_st"):
        row = {"name": st_name[st], "stream": st_stream[st]}
        okay = False
        for k in STATION_PARAMS:
            v = g[k].dropna()
            m = _pos_median(v) if len(v) >= STATION_MIN_N else None
            row[k] = _sig(m) if m is not None else None
            row[k + "_n"] = int(len(v))
            okay = okay or m is not None
        if okay:
            st_rows.append(row)
    stations = {}
    for k in STATION_PARAMS:
        rows = [r for r in st_rows if r[k] is not None]
        rows.sort(key=lambda r: (-r[k], r["name"]))
        rows = rows[:STATION_TOP]
        stations[k] = {"label": PKEY[k][2], "unit": PKEY[k][4],
                       "names": [r["name"] for r in rows], "streams": [r["stream"] for r in rows],
                       "values": [r[k] for r in rows], "n": [r[k + "_n"] for r in rows]}
    st_table_rows = sorted([r for r in st_rows if r["bod"] is not None],
                           key=lambda r: (-r["bod"], r["name"]))[:STATION_TOP]
    st_table = [{"name": r["name"], "stream": r["stream"], "n": r["bod_n"],
                 "vals": [_fmt(r[k]) for k in STATION_PARAMS]} for r in st_table_rows]
    station_opts = [{"key": k, "label": PKEY[k][2], "unit": PKEY[k][4]} for k in STATION_PARAMS]

    # ── seasons (all years) ──
    dated["_season"] = dated["_m"].map(lambda m: "spring" if m in SPRING_MONTHS else "autumn")
    season = {}
    season_rows = []
    for k in SEASON_PARAMS:
        names, sp, au, nsp, nau = [], [], [], [], []
        for s in streams:
            g = dated[(dated[STREAM] == s) & dated[k].notna()]
            a = g[g["_season"] == "spring"][k]
            b = g[g["_season"] == "autumn"][k]
            if len(a) < MIN_N or len(b) < MIN_N:
                continue
            ma, mb = _pos_median(a), _pos_median(b)
            if ma is None or mb is None:
                continue
            names.append(s)
            sp.append(_sig(ma))
            au.append(_sig(mb))
            nsp.append(int(len(a)))
            nau.append(int(len(b)))
            season_rows.append({"param": PKEY[k][3], "unit": PKEY[k][4], "stream": s,
                                "spring": _fmt(ma), "autumn": _fmt(mb),
                                "ns": int(len(a)), "na": int(len(b))})
        season[k] = {"label": PKEY[k][2], "unit": PKEY[k][4], "names": names,
                     "spring": sp, "autumn": au, "ns": nsp, "na": nau}
    season_opts = [{"key": k, "label": PKEY[k][2], "unit": PKEY[k][4]} for k in SEASON_PARAMS]
    month_n = dated.groupby("_m").size()
    spring_n = int(sum(int(month_n.get(m, 0)) for m in SPRING_MONTHS))
    autumn_n = int(len(dated) - spring_n)

    # ── station × year heatmap of BOD medians (coverage + load) ──
    st_order = sorted(st_name.keys(), key=lambda st: (streams.index(st_stream[st]), st_name[st], st))
    hm_y = [st_name[st] for st in st_order]
    hm_streams = [st_stream[st] for st in st_order]
    bodg = dated.groupby(["_st", "_y"])
    cnt_all = bodg.size()
    bod_med = dated[dated["bod"].notna()].groupby(["_st", "_y"])["bod"].median()
    hm_cells = []
    for (st, y), n in cnt_all.items():
        m = bod_med.get((st, y))
        v = _sig(m) if m is not None and not pd.isna(m) and m > 0 else None
        hm_cells.append([years.index(int(y)), st_order.index(st),
                         None if v is None else round(math.log10(v), 3), int(n),
                         None if v is None else _fmt(v)])
    hm_cells.sort(key=lambda c: (c[1], c[0]))
    bod_vals = [c[2] for c in hm_cells if c[2] is not None]
    heatmap = {"years": [str(y) for y in years], "stations": hm_y, "streams": hm_streams,
               "cells": hm_cells,
               "min": math.floor(min(bod_vals) * 2) / 2 if bod_vals else 0,
               "max": math.ceil(max(bod_vals) * 2) / 2 if bod_vals else 1}

    # ── field readings ──
    field_any = dated[dated[[f[0] for f in FIELD]].notna().any(axis=1)]
    field = None
    field_rows = []
    if len(field_any):
        fy0, fy1 = int(field_any["_y"].min()), int(field_any["_y"].max())
        names, data, ns, low_share = [], [], [], []
        for s in streams:
            v = dated[(dated[STREAM] == s) & dated["doxsat"].notna()]["doxsat"]
            row = {"stream": s, "vals": []}
            for fk, *_ in FIELD:
                fv = dated[(dated[STREAM] == s)][fk].dropna()
                row["vals"].append(_fmt(_median(fv)) if len(fv) >= MIN_N else "-")
            if len(v) >= MIN_N:
                q = v.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).tolist()
                names.append(s)
                data.append([_sig(x) for x in q])
                ns.append(int(len(v)))
                ls = float((v < LOW_DO_SAT).mean())
                low_share.append(round(ls, 4))
                row["low"] = _pct(ls)
                row["n"] = int(len(v))
            else:
                row["low"] = "-"
                row["n"] = int(len(v))
            if any(x != "-" for x in row["vals"]):
                field_rows.append(row)
        if names:
            field = {"names": names, "data": data, "n": ns, "low_share": low_share,
                     "span": f"{fy0}-{fy1}", "y0": fy0, "y1": fy1}

    # ── labs ──
    lab = dated[dated[LAB] != ""]
    lab_info = None
    if len(lab):
        lc = lab.groupby(LAB).size().reset_index(name="n")
        lc = lc.sort_values(["n", LAB], ascending=[False, True], kind="mergesort")
        top_lab, top_n = lc.iloc[0][LAB], int(lc.iloc[0]["n"])
        ly = lab[lab[LAB] == top_lab].groupby("_y").size()
        tot_y = dated.groupby("_y").size()
        # start of the lab's final unbroken run of majority years, ending at
        # the newest year (years with no samples at all don't break the run)
        since = None
        for y in reversed(years):
            if not tot_y.get(y, 0):
                continue
            if ly.get(y, 0) / tot_y.get(y, 1) > 0.5:
                since = y
            else:
                break
        run = lab[lab["_y"] >= since] if since is not None else lab.iloc[0:0]
        run_share = float((run[LAB] == top_lab).mean()) if len(run) else 0.0
        lab_info = {"name": top_lab, "since": since, "share": run_share, "n_labs": int(len(lc))}

    # ── KPIs ──
    latest_n = int(year_tot.get(y_max, 0))
    pk = year_tot.reset_index(name="n").sort_values(["n", "_y"], ascending=[False, True], kind="mergesort")
    peak_year, peak_n = int(pk.iloc[0]["_y"]), int(pk.iloc[0]["n"])
    latest_months = set(dated[dated["_y"] == y_max]["_m"].tolist())
    # the autumn round runs August-January, so January samples close the
    # previous season: a year with no August-December sample is partial
    latest_partial = all(m in SPRING_MONTHS or m == 1 for m in latest_months)
    latest_has_spring = any(m in SPRING_MONTHS for m in latest_months)
    latest_has_jan = 1 in latest_months

    rec5 = win(dated, recent5)
    bod_rec = []
    for s in streams:
        v = rec5[(rec5[STREAM] == s)]["bod"].dropna()
        if len(v) >= MIN_N:
            # a median on the reporting floor is kept as "≤ floor": valid on
            # the clean side, and flagged so the ratio reads as a lower bound
            m = _median(v[v > 0])
            if m is not None:
                at_floor = "bod" in floors and m <= floors["bod"]
                bod_rec.append((s, floors["bod"] if at_floor else m, int(len(v)), at_floor))
    kpis = {
        "samples": {"value": n_total, "display": f"{n_total:,}", "tone": "brand"},
        "stations": {"value": n_stations, "display": f"{n_stations:,}", "tone": "brand"},
        "span": {"value": y_max - y_min + 1, "display": f"{y_min}–{y_max}", "tone": "brand"},
        "latest": {"value": latest_n, "display": f"{latest_n:,}",
                   "tone": "warn" if latest_partial else "brand"},
    }
    labels = {}
    if len(bod_rec) >= 2:
        hi = max(bod_rec, key=lambda t: (t[1], t[0]))
        lo = min(bod_rec, key=lambda t: (t[1], t[0]))
        def disp(t):
            return ("≤" if t[3] else "") + _fmt(t[1])

        def lbl(t):
            return (f"חציון BOD {_bstream(t[0])}, {recent5[0]}-{recent5[1]} (מ״ג/ל׳"
                    + (", מתחת לסף הגילוי)" if t[3] else ")"))
        kpis["bod_hi"] = {"value": _sig(hi[1]), "display": disp(hi),
                          "tone": "danger" if not hi[3] and hi[1] / lo[1] >= GAP_RATIO else "warn"}
        kpis["bod_lo"] = {"value": _sig(lo[1]), "display": disp(lo), "tone": "ok"}
        labels["bod_hi_kpi"] = lbl(hi)
        labels["bod_lo_kpi"] = lbl(lo)

    # ── insights ──
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # 1. coverage
    top_st = sorted(st_n.items(), key=lambda t: (-t[1], st_name[t[0]]))[0]
    add("coverage",
        f"המאגר כולל {n_total:,} דגימות מ-{n_stations} תחנות ב-{len(streams)} נחלים וקטעי נחל "
        f"({_join(streams)}), בין {y_min} ל-{y_max}. התחנה שנדגמה הכי הרבה היא "
        f"{st_name[top_st[0]]} {_bstream(st_stream[top_st[0]])}, עם {top_st[1]:,} דגימות.")

    # 2. long-term BOD/NH4 change per stream
    def change_text(key):
        down, up, flat = [], [], []
        for s in streams:
            c = change.get((s, key))
            if not c:
                continue
            pct = (c["ratio"] - 1)
            item = (f"{_bstream(s)} מ-{_fmt(c['early'])} ל-{_fmt(c['recent'])} מ״ג/ל׳ "
                    f"({_pct(abs(pct))})")
            if pct <= -CHANGE_BAND:
                down.append(item)
            elif pct >= CHANGE_BAND:
                up.append(item)
            else:
                flat.append(s)
        if not down and not up:
            return None
        parts = []
        lbl = PKEY[key][3]
        if down:
            parts.append(f"ירד {_join(down)}")
        if up:
            parts.append(f"עלה {_join(up)}")
        txt = (f"חציון {lbl} בחמש השנים הראשונות של הניטור בכל נחל לעומת {recent5[0]}-{recent5[1]}: "
               + "; ".join(parts) + ".")
        if flat:
            txt += f" ללא שינוי ברור {_join(_bstream(s) for s in flat)}."
        return txt

    add("bod_change", change_text("bod"))

    # 3. gap between streams, recent5 BOD
    if len(bod_rec) >= 2:
        hi = max(bod_rec, key=lambda t: (t[1], t[0]))
        lo = min(bod_rec, key=lambda t: (t[1], t[0]))
        if not hi[3] and hi[1] / lo[1] >= GAP_RATIO:
            if lo[3]:
                ratio = f"לפחות פי {hi[1] / lo[1]:,.0f}"
                lo_txt = f"מתחת לסף הגילוי, ≤{_fmt(lo[1])} מ״ג/ל׳"
            else:
                ratio = f"פי {hi[1] / lo[1]:,.0f}"
                lo_txt = f"{_fmt(lo[1])} מ״ג/ל׳"
            add("gap",
                f"בשנים {recent5[0]}-{recent5[1]} חציון ה-BOD {_bstream(hi[0])} ({_fmt(hi[1])} מ״ג/ל׳, "
                f"{hi[2]} דגימות) גבוה {ratio} מזה {_bstream(lo[0])} "
                f"({lo_txt}, {lo[2]} דגימות): עומס אורגני גבוה בהרבה.")

    # 4. deterioration: recent5 vs prior5 NH4/BOD
    worse = []
    overall_med = {k: float(dated[k].median()) for k in ("nh4", "bod")}
    for key in ("nh4", "bod"):
        for s in streams:
            ss = dated[(dated[STREAM] == s) & dated[key].notna()]
            a, b = win(ss, prior5), win(ss, recent5)
            if len(a) < MIN_N or len(b) < MIN_N:
                continue
            mb = qmed(b[key], key)          # recent at the floor: not a deterioration
            ma = _median(a[key][a[key] > 0])
            if ma is None or mb is None:
                continue
            below = key in floors and ma <= floors[key]
            if below:
                ma = floors[key]            # rise from below detection: compare to the floor
            # the recent level must also be high for this parameter (above
            # its all-record median), so a move at the detection limit
            # (0.05 → 0.1) is not called a deterioration
            if mb / ma >= WORSEN_RATIO and mb > overall_med[key]:
                worse.append((s, key, ma, mb, int(len(a)), int(len(b)), int(b["_st"].nunique()), below))
    if worse:
        worse.sort(key=lambda t: (-(t[3] / t[2]), t[0], t[1]))
        s, key, ma, mb, na, nb, nst, below = worse[0]
        frm = (f"מתחת לסף הגילוי (≤{_fmt(ma)} מ״ג/ל׳)" if below else f"{_fmt(ma)} מ״ג/ל׳")
        txt = (f"החמרה {_bstream(s)}: חציון {PKEY[key][3]} עלה מ{'' if below else '-'}{frm} ב-{prior5[0]}-{prior5[1]} "
               f"({na} דגימות) ל-{_fmt(mb)} מ״ג/ל׳ ב-{recent5[0]}-{recent5[1]} ({nb} דגימות ב-{nst} תחנות).")
        if nb * 2 < na:
            txt += " מספר הדגימות ירד בחדות, ולכן הנתון רגיש לבחירת התחנות שנדגמו."
        add("worse", txt)

    # 5. salinity
    cl_rec = []
    for s in streams:
        v = rec10[rec10[STREAM] == s]["cl"].dropna()
        if len(v) >= MIN_N:
            m = _pos_median(v)
            if m is not None:
                cl_rec.append((s, m))
    if len(cl_rec) >= 2:
        hi = max(cl_rec, key=lambda t: (t[1], t[0]))
        others = sorted([t for t in cl_rec if t[0] != hi[0]], key=lambda t: (-t[1], t[0]))
        if hi[1] / others[0][1] >= GAP_RATIO:
            add("salinity",
                f"{hi[0]} מלוח בהרבה מהשאר: חציון הכלוריד בו בשנים {recent10[0]}-{recent10[1]} הוא "
                f"{_fmt(hi[1])} מ״ג/ל׳, לעומת {_join(f'{_fmt(m)} {_bstream(s)}' for s, m in others)}.")

    # 6. seasonal bacteria
    sz = season.get("fcoli")
    if sz and sz["names"]:
        hits = []
        for i, s in enumerate(sz["names"]):
            r = sz["autumn"][i] / sz["spring"][i]
            if r >= SEASON_RATIO:
                hits.append((s, r))
        if hits and len(hits) * 2 >= len(sz["names"]):
            hits.sort(key=lambda t: (-t[1], t[0]))
            add("season",
                f"ריכוז הקוליפורמים הצואתיים גבוה בסתיו מאשר באביב ב-{len(hits)} מתוך {len(sz['names'])} נחלים; "
                f"הפער הגדול ביותר {_bstream(hits[0][0])} (חציון סתיו גבוה פי {hits[0][1]:.1f} מחציון אביב).")

    # 7. oxygen
    if field:
        j = max(range(len(field["names"])), key=lambda i: (field["low_share"][i], field["names"][i]))
        if field["low_share"][j] >= LOW_DO_SHARE:
            add("oxygen",
                f"במדידות השדה ({field['span']}), {_pct(field['low_share'][j])} מהדגימות "
                f"{_bstream(field['names'][j])} הראו רוויית חמצן מתחת ל-{LOW_DO_SAT}%, סימן למים דלי חמצן.")

    # 8. sampling volume
    full_years = [y for y in years if y != y_max or not latest_partial]
    if full_years:
        ly = full_years[-1]
        ln = int(year_tot.get(ly, 0))
        if ln < peak_n * DROP_SHARE and ly != peak_year:
            add("volume",
                f"היקף הדיגום ירד: {ln:,} דגימות ב-{ly}, לעומת שיא של {peak_n:,} ב-{peak_year}.")
    if latest_partial:
        if latest_has_spring and latest_has_jan:
            held = "סבב האביב ודגימות ינואר של סבב הסתיו הקודם"
        elif latest_has_spring:
            held = "סבב האביב בלבד"
        else:
            held = "דגימות ינואר בלבד, סוף סבב הסתיו הקודם"
        missing = (f"סבב הסתיו של {y_max} טרם פורסם" if latest_has_spring
                   else f"סבבי האביב והסתיו של {y_max} טרם פורסמו")
        n_txt = "דגימה אחת" if latest_n == 1 else f"{latest_n:,} דגימות"
        add("partial", f"נתוני {y_max} חלקיים ({n_txt}): יש בהם {held}, ו{missing}.")

    # 9. lab
    if lab_info and lab_info["since"] is not None and lab_info["since"] < y_max:
        txt = f"מאז {lab_info['since']} רוב הדגימות בכל שנה נבדקו במעבדת {lab_info['name']}"
        if lab_info["n_labs"] > 1:
            txt += (f" ({lab_info['share'] * 100:.1f}% מהדגימות בשנים אלה "
                    f"שצוינה להן מעבדה)")
        add("lab", txt + ".")

    # ── summary / labels ──
    stream_list = _join(streams)
    summary = (f"תוצאות ניטור איכות מים בנחלים: {n_total:,} דגימות ב-{n_stations} תחנות, "
               f"{y_min}-{y_max}. BOD, אמוניום, זרחן, חיידקים ומליחות לפי נחל ותחנה.")
    if len(summary) > 155:
        summary = f"ניטור איכות מים בנחלים: {n_total:,} דגימות ב-{n_stations} תחנות, {y_min}-{y_max}."

    labels.update({
        "h1": "ניטור נחלים: תוצאות בדיקות איכות המים",
        "lede": (f"תוצאות הדיגום הכימי של המשרד להגנת הסביבה ב{stream_list}, "
                 f"מ-{y_min} עד {y_max}. כל דגימה כוללת עד עשרות פרמטרים; העמוד מתמקד באלה שנמדדו לאורך רוב התקופה."),
        "latest_kpi": f"דגימות ב-{y_max}" + (" (נתונים חלקיים)" if latest_partial else ""),
        "span_kpi": "טווח שנות הדיגום",
        "years_lede": f"בשנת השיא {peak_year} נאספו {peak_n:,} דגימות; ב-{y_max} נאספו {latest_n:,}.",
        "years_aria": (f"גרף עמודות מוערם: מספר הדגימות בכל שנה לפי נחל, {y_min}-{y_max}. "
                       f"שיא של {peak_n:,} דגימות ב-{peak_year}."),
        "trend_aria": (f"גרף קווים: חציון שנתי של הפרמטר הנבחר בכל נחל, {y_min}-{y_max}, בציר לוגריתמי."),
        "trend_lede": ("חציון שנתי לכל נחל, בציר לוגריתמי (כל קו רשת פי עשרה). בחרו פרמטר מהרשימה; "
                       "בריחוף מוצג גם מספר הדגימות בכל נקודה. שנים מעטות דגימות רגישות לבחירת התחנות."),
        "change_aria": (f"מפת חום: שינוי בחציון כל פרמטר בכל נחל בין חמש שנות הניטור הראשונות "
                        f"לשנים {recent5[0]}-{recent5[1]}. ירוק מסמן ירידה ואדום עלייה."),
        "change_lede": (f"השוואת החציון בחמש השנים הראשונות שבהן נמדד כל פרמטר בכל נחל לחציון {recent5[0]}-{recent5[1]}. "
                        f"מוצג רק כשבכל חלון יש לפחות {MIN_N} דגימות והחלונות אינם חופפים. ערכי אפס אינם נכללים, "
                        f"וחציון שיושב על סף הדיווח של המעבדה (מתחת לסף הגילוי) אינו מוצג."),
        "box_lede": (f"פיזור הערכים בשנים {recent10[0]}-{recent10[1]}: הקופסה מסמנת את הרבעון האמצעי, "
                     f"והשפם את אחוזונים 5 עד 95 (ציר לוגריתמי, נחלים עם {MIN_N} דגימות לפחות)."),
        "stations_lede": (f"{STATION_TOP} התחנות עם החציון הגבוה ביותר בשנים {recent10[0]}-{recent10[1]} "
                          f"(תחנות עם {STATION_MIN_N} דגימות לפחות של הפרמטר)."),
        "stations_aria": (f"גרף עמודות אופקי: התחנות עם חציון הפרמטר הנבחר הגבוה ביותר, "
                          f"{recent10[0]}-{recent10[1]}."),
        "season_lede": (f"חציון כל הדגימות לפי עונה: אביב (פברואר עד יולי, {spring_n:,} דגימות) "
                        f"מול סתיו (אוגוסט עד ינואר, {autumn_n:,} דגימות), {y_min}-{y_max}."),
        "season_aria": ("גרף עמודות: חציון הפרמטר הנבחר באביב ובסתיו בכל נחל, בציר לוגריתמי."),
        "heat_lede": ("כל משבצת היא שנה בתחנה שנדגמה; הצבע הוא חציון ה-BOD באותה שנה (כהה יותר = עומס גבוה יותר), "
                      "משבצת אפורה פירושה דגימה ללא מדידת BOD, ומשבצת ריקה פירושה שלא נדגמה. התחנות מקובצות לפי נחל."),
        "heat_aria": (f"מפת חום: חציון BOD לפי תחנה ושנה, {n_stations} תחנות, {y_min}-{y_max}."),
        "table_recent": f"{recent10[0]}-{recent10[1]}",
        "p_lo": "אחוזון 5",
        "p_hi": "אחוזון 95",
        "recent5": f"{recent5[0]}-{recent5[1]}",
        "ec_note": f"ערכי מוליכות מעל {EC_MAX} נרשמו כנראה ביחידות אחרות ואינם נכללים.",
    })
    if field:
        labels["field_lede"] = (f"מדידות השדה (חומציות, טמפרטורה, חמצן מומס ומוליכות) נרשמו בשנים "
                                f"{field['span']}. הגרף מציג את פיזור רוויית החמצן; קו האדום מסמן {LOW_DO_SAT}%.")
        labels["field_aria"] = (f"גרף קופסה: פיזור רוויית החמצן בכל נחל, {field['span']}.")
        labels["low_do"] = f"{LOW_DO_SAT}%"
        labels["low_do_col"] = f"מתחת ל-{LOW_DO_SAT}% רוויה"
    for k in BOX_PARAMS:
        b = box[k]
        if b["names"]:
            j = max(range(len(b["names"])), key=lambda i: (b["data"][i][2], b["names"][i]))
            labels[f"box_{k}_aria"] = (f"גרף קופסה: פיזור {b['label']} בכל נחל, {recent10[0]}-{recent10[1]}. "
                                       f"החציון הגבוה {_bstream(b['names'][j])}, {_fmt(b['data'][j][2])} {b['unit']}.")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "temporal_coverage": f"{y_min}/{y_max}",
        "spatial_coverage": stream_list,
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "by_year": by_year,
            "trend": trend,
            "change": change_chart,
            "box": box,
            "stations": stations,
            "season": season,
            "heatmap": heatmap,
            "field": field,
            "field_threshold": LOW_DO_SAT,
        },
        "opts": {"trend": param_opts, "stations": station_opts, "season": season_opts},
        "tables": {
            "years": year_rows,
            "change": change_rows,
            "box": box_rows,
            "stations": st_table,
            "station_cols": [PKEY[k][3] for k in STATION_PARAMS],
            "season": season_rows,
            "field": field_rows,
            "field_cols": [f[2] + (f" ({f[3]})" if f[3] else "") for f in FIELD],
        },
        "streams": streams,
        "has_bod_kpis": "bod_hi" in kpis,
        "insights": insights,
        "labels": labels,
    }
