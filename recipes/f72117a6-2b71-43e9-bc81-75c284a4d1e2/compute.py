"""Instantaneous discharge at hydrometric stations (hydrograph), Water Authority.

One row per discharge reading: station, timestamp, discharge (m3/s), flow
type (flood / normal / sewage / other) and data type (measured /
reconstructed). The dataset is split into one CSV per period of
hydrological years; all of them are concatenated.

Readings are logged irregularly (dense during a flood, sparse at steady
flow), so row counts are not a hydrological measure. The page therefore
works with:
  - station annual peaks (max discharge per station per hydrological year),
  - station-days (a station that logged a flow type on a calendar day),
  - active stations (stations with any reading in a hydrological year).

A hydrological year runs October to September and is named by the year it
ends in (October 2023 to September 2024 = 2024).

Every number on the page comes from here. Insight rules return a sentence
or None; a rule whose premise doesn't hold drops out.
"""
import numpy as np
import pandas as pd

C_NAME = "שם תחנה"
C_TIME = "זמן מדידת ספיקה"
C_Q = "ספיקה (מ''ק/שנייה)"
C_FLOW = "סוג זרימה"
C_KIND = "סוג נתון"
C_REC = "סוג רשומה"

# Record types: segment end sorts before an interior point before a segment
# start at the same timestamp; the interval after a segment end is a gap.
REC_ORDER = {"סיום קטע": 0, "נקודה פנימית": 1, "התחלת קטע": 2}
REC_END = 0

# Hydrological-year month order (October first) and Hebrew names.
HY_MONTHS = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
MONTH_HE = {1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל", 5: "מאי", 6: "יוני",
            7: "יולי", 8: "אוגוסט", 9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר",
            12: "דצמבר"}

# Flow types: known codes mapped to display labels; anything else -> "other".
FLOW_LABEL = {"גאות": "שיטפון (גאות)", "תקין": "זרימה רגילה", "ביוב": "ביוב"}
FLOW_ORDER = ["שיטפון (גאות)", "זרימה רגילה", "ביוב", "אחר"]
DRY = "אפיק יבש (ספיקה אפס)"
TIME_ORDER = ["שיטפון (גאות)", "זרימה רגילה", DRY, "ביוב", "אחר"]
NORMAL = "זרימה רגילה"
FLOOD = "שיטפון (גאות)"
SEWAGE = "ביוב"

KIND_LABEL = {"מדודים": "נמדד", "משוחזרים": "משוחזר"}
RECON_CODE = "משוחזרים"

TOP_N = 15          # station rankings
LATEST_N = 12       # latest-year comparison
HEAT_YEARS = 30     # heatmap window
STORM_N = 10        # synoptic storm days
SEW_YEARS = 5       # window for the sewage station ranking
MIN_HIST_YEARS = 5  # prior years needed for a station's historical median
WET_MIN_STATIONS = 30  # stations with a peak needed to rank a year


# ── formatting ───────────────────────────────────────────────────────────

def _int(v):
    return f"{int(round(v)):,}"


def _q(v):
    """Discharge display: magnitude-dependent precision."""
    v = float(v)
    if v >= 100:
        return f"{v:,.0f}"
    if v >= 10:
        return f"{v:,.1f}"
    return f"{v:,.2f}"


def _qr(v):
    """Discharge rounded for chart data (keeps blocks small)."""
    v = float(v)
    if v >= 100:
        return round(v, 1)
    return round(v, 3)


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _date(ts):
    return f"{ts.day}.{ts.month}.{ts.year}"


def _clean_name(s):
    s = s.replace("''", "״").replace('"', "״").replace(";", " ")
    return " ".join(s.split())


# ── preparation ──────────────────────────────────────────────────────────

def _prepare(df):
    # Categoricals first: the raw frame has millions of repeated strings.
    names_raw = df[C_NAME].astype("category")
    cleaned = np.array([_clean_name(c) for c in names_raw.cat.categories] + [""], dtype=object)
    codes = names_raw.cat.codes.to_numpy()  # -1 never occurs (no NaN), mapped to "" anyway
    name = cleaned[codes]
    q = pd.to_numeric(df[C_Q].str.replace(",", "", regex=False), errors="coerce").to_numpy()
    t = pd.to_datetime(df[C_TIME], format="%d/%m/%Y %H:%M:%S", errors="coerce").to_numpy()
    flow_raw = df[C_FLOW].astype("category")
    flow_map = {c: FLOW_LABEL.get(c.strip(), "אחר") for c in flow_raw.cat.categories}
    flow_lbl = np.array([flow_map[c] for c in flow_raw.cat.categories] + ["אחר"], dtype=object)
    flow = pd.Categorical(flow_lbl[flow_raw.cat.codes.to_numpy()], categories=FLOW_ORDER)
    kind_raw = df[C_KIND].astype("category")
    recon_cats = {c for c in kind_raw.cat.categories if c.strip() == RECON_CODE}
    recon = kind_raw.isin(recon_cats).to_numpy()
    rec_raw = df[C_REC].astype("category")
    rec_lbl = np.array([REC_ORDER.get(c.strip(), 1) for c in rec_raw.cat.categories] + [1], dtype=np.int8)
    rec = rec_lbl[rec_raw.cat.codes.to_numpy()]
    keep = (name != "") & ~np.isnan(q) & ~pd.isna(t) & (np.nan_to_num(q, nan=-1.0) >= 0)
    out = pd.DataFrame({
        "name": pd.Categorical(name[keep]),
        "q": q[keep],
        "t": t[keep],
        "flow": flow[keep],
        "recon": recon[keep],
        "rec": rec[keep],
    })
    tt = out["t"].dt
    out["hy"] = (tt.year + (tt.month >= 10)).astype(np.int16)
    return out


def _durations(d):
    """Station-time per reading, in days, with its flow class.

    Readings are sorted by station, time, record type (segment end before
    a start at the same instant), then flow and discharge for a total order.
    A normal-flow interval whose two ends both read zero is classed as a
    dry riverbed."""
    name_c = d["name"].cat.codes.to_numpy()
    t = d["t"].to_numpy()
    flow_c = d["flow"].cat.codes.to_numpy()
    q = d["q"].to_numpy()
    rec = d["rec"].to_numpy()
    order = np.lexsort((q, flow_c, rec, t, name_c))
    name_c, t, flow_c, q, rec = name_c[order], t[order], flow_c[order], q[order], rec[order]
    hy = d["hy"].to_numpy()[order]
    same_next = np.zeros(len(t), dtype=bool)
    same_next[:-1] = name_c[1:] == name_c[:-1]
    next_t = np.empty_like(t)
    next_t[:-1] = t[1:]
    next_t[-1] = t[-1]
    next_q = np.zeros(len(q))
    next_q[:-1] = q[1:]
    uy = np.unique(hy)
    ends = pd.to_datetime([f"{int(y)}-10-01" for y in uy]).to_numpy()
    hy_end = ends[np.searchsorted(uy, hy)]
    end = np.minimum(next_t, hy_end)
    days = (end - t) / np.timedelta64(1, "D")
    days = np.where(same_next & (rec != REC_END), np.maximum(days, 0.0), 0.0)
    labels = np.array(FLOW_ORDER, dtype=object)[flow_c]
    dry = (labels == NORMAL) & (q == 0) & (next_q == 0) & same_next
    labels = np.where(dry, DRY, labels)
    out = pd.DataFrame({
        "name": np.array(d["name"].cat.categories, dtype=object)[name_c],
        "hy": hy,
        "cls": pd.Categorical(labels, categories=TIME_ORDER),
        "days": days,
    })
    return out[out["days"] > 0]


def _annual_peaks(d):
    """One row per (station, hydrological year): the year's maximum reading.
    Ties resolved deterministically: earliest time, then flow/kind labels."""
    s = d[["name", "hy", "q", "t", "recon"]].copy()
    s["name_s"] = s["name"].astype(str)
    s = s.sort_values(["name_s", "hy", "q", "t", "recon"],
                      ascending=[True, True, False, True, True], kind="mergesort")
    s = s.drop_duplicates(["name_s", "hy"], keep="first")
    return s.drop(columns=["name"]).rename(columns={"name_s": "name"}).reset_index(drop=True)


# ── insight rules ────────────────────────────────────────────────────────

def insight_record(rec):
    if rec is None:
        return None
    note = " (ערך משוחזר)" if rec["recon"] else ""
    return (f"הספיקה הרגעית הגבוהה ביותר במאגר: {_q(rec['q'])} מ״ק/שנייה בתחנת "
            f"{rec['name']}, ב-{_date(rec['t'])}{note}.")


def insight_latest(latest_rows, latest_hy):
    rows = [r for r in latest_rows if r["median"] is not None]
    if len(rows) < 5:
        return None
    above = [r for r in rows if r["peak"] > r["median"]]
    share = len(above) / len(rows)
    top = max(rows, key=lambda r: (r["peak"] / r["median"] if r["median"] > 0 else 0, r["name"]))
    if share >= 0.6:
        lead = "ברוב התחנות"
    elif share <= 0.4:
        lead = "במיעוט מהתחנות"
    else:
        lead = "בכמחצית מהתחנות"
    text = (f"בשנה ההידרולוגית {latest_hy} השיא השנתי {lead} עלה על החציון ההיסטורי שלהן: "
            f"{len(above):,} מתוך {len(rows):,} תחנות עם היסטוריה של {MIN_HIST_YEARS} שנים לפחות.")
    if top["median"] > 0 and top["peak"] / top["median"] >= 2:
        text += (f" החריגה הבולטת: {top['name']}, {_q(top['peak'])} מ״ק/שנייה לעומת חציון של "
                 f"{_q(top['median'])}.")
    return text


def insight_season(month_counts):
    total = sum(month_counts.values())
    if total < 20:
        return None
    winter = sum(month_counts.get(m, 0) for m in (12, 1, 2))
    share = winter / total
    peak_m = max(sorted(month_counts), key=lambda m: month_counts[m])
    if share < 0.4:
        return None
    return (f"{_pct(share)} מהשיאים השנתיים בתחנות נרשמו בדצמבר עד פברואר; "
            f"החודש השכיח ביותר לשיא השנתי הוא {MONTH_HE[peak_m]} ({month_counts[peak_m]:,} שיאים).")


def insight_network(active, partial):
    """`active` covers complete hydrological years only; `partial` is
    (year, stations) for a newer, still-partial year, or None."""
    if len(active) < 10:
        return None
    peak_y = int(active.idxmax())
    peak_v = int(active.max())
    last_y = int(active.index[-1])
    last_v = int(active.iloc[-1])
    first_y = int(active.index[0])
    if last_v >= peak_v * 0.9:
        tail = f"ובשנת {last_y} פעלו {last_v:,} תחנות, קרוב לשיא."
    else:
        tail = (f"ומאז ירד מספרן: בשנת {last_y} פעלו {last_v:,} תחנות "
                f"({_pct((peak_v - last_v) / peak_v, 0)} פחות).")
    first_v = int(active.iloc[0])
    if first_v <= 3:
        start = "מתחנה אחת" if first_v == 1 else f"מ-{first_v:,} תחנות"
        head = f"רשת המדידה גדלה {start} ב-{first_y} לשיא של {peak_v:,} תחנות פעילות בשנת {peak_y}, "
    else:
        head = f"שיא התחנות הפעילות היה {peak_v:,} בשנת {peak_y}, "
    text = head + tail
    if partial:
        text += (f" השנה ההידרולוגית {partial[0]} חלקית בנתונים ({partial[1]:,} תחנות עד כה) "
                 f"ולא נכללה בהשוואה.")
    return text


def insight_sewage(flow_share, years):
    """Sewage share of station-days, latest 5 years vs the 5 years a decade earlier."""
    if len(years) < 15 or SEWAGE not in flow_share:
        return None
    s = flow_share[SEWAGE]
    recent = years[-5:]
    earlier = [y for y in years if recent[0] - 10 <= y <= recent[-1] - 10]
    if len(earlier) < 3:
        return None
    r = float(np.mean([s[y] for y in recent]))
    e = float(np.mean([s[y] for y in earlier]))
    if r < 0.02:
        return None
    diff = r - e
    if abs(diff) < 0.02:
        verb = "דומה ל"
    elif diff > 0:
        verb = "עלייה לעומת "
    else:
        verb = "ירידה לעומת "
    return (f"זרימת ביוב: בשנים {recent[0]}-{recent[-1]} היא היוותה בממוצע {_pct(r)} מזמן המדידה בתחנות, "
            f"{verb}{_pct(e)} בשנים {earlier[0]}-{earlier[-1]}.")


def insight_sewage_stations(sew_days, st_tot, sew_from, hy_max):
    """Stations where sewage was most of the measured time in the window."""
    big = [n for n in sew_days.index if st_tot[n] >= 365 and sew_days[n] / st_tot[n] >= 0.5]
    if not big:
        return None
    lead = big[0]
    share = sew_days[lead] / st_tot[lead]
    many = "תחנה אחת" if len(big) == 1 else f"{len(big):,} תחנות"
    return (f"ב-{many} זרימת הביוב היוותה יותר ממחצית זמן המדידה בשנים {sew_from}-{hy_max}; "
            f"הבולטת היא {lead}, עם ביוב ב-{_pct(share)} מהזמן.")


def insight_storm(storms):
    if not storms or storms[0]["n"] < 5:
        return None
    s = storms[0]
    return (f"היום שבו נרשמו הכי הרבה שיאים שנתיים בבת אחת: {s['date']}, עם {s['n']:,} תחנות "
            f"שהגיעו בו לשיא השנה שלהן.")


def insight_wettest(ap_year):
    """Year with the highest median station annual peak, among years with
    at least WET_MIN_STATIONS stations (a handful of early stations is not
    a national picture; the sentence says so)."""
    ok = ap_year[ap_year["size"] >= WET_MIN_STATIONS]
    if len(ok) < 10:
        return None
    med = ok["median"]
    y = int(med.sort_index().idxmax())
    overall = float(med.median())
    if overall <= 0 or med.max() < overall * 1.5:
        return None
    return (f"השנה ההידרולוגית החזקה ביותר בשיטפונות היא {y}: החציון של השיאים השנתיים בתחנות הגיע ל-"
            f"{_q(med.max())} מ״ק/שנייה, פי {med.max() / overall:.1f} מהחציון הרב-שנתי ({_q(overall)}). "
            f"נבחנו רק שנים עם {WET_MIN_STATIONS} תחנות לפחות ({ok.index.min()}-{ok.index.max()}).")


def insight_recon(recon_share, n_recon_peaks, n_top):
    if recon_share < 0.005:
        return None
    text = f"{_pct(recon_share)} מהקריאות במאגר מסומנות כמשוחזרות ולא כנמדדות"
    if n_recon_peaks:
        text += f", ובהן {n_recon_peaks:,} מתוך {n_top:,} שיאי התחנות הגבוהים בדירוג"
    return text + "."


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    raw = frames["flow"]
    n_rows_raw = len(raw)
    d = _prepare(raw)
    del raw
    n_rows = len(d)

    stations_all = int(d["name"].nunique())
    hy_min, hy_max = int(d["hy"].min()), int(d["hy"].max())

    # Latest hydrological year: complete if readings reach September.
    last_t = d.loc[d["hy"] == hy_max, "t"].max()
    latest_partial = not (last_t.month == 9)
    latest_full = hy_max - 1 if latest_partial else hy_max

    # Active stations per year.
    active = d.groupby("hy")["name"].nunique().sort_index()
    active = active.reindex(range(hy_min, hy_max + 1), fill_value=0)
    # Network figures use complete years only; a partial newest year would
    # read as a collapse of the network.
    active_full = active.loc[:latest_full]
    partial = (hy_max, int(active.iloc[-1])) if latest_partial else None
    partial_lbl = " (חלקית)" if latest_partial else ""

    # Station annual peaks.
    ap = _annual_peaks(d)
    ap_pos = ap[ap["q"] > 0]
    ap_year = ap_pos.groupby("hy")["q"].agg(["max", "median", "size"]).sort_index()
    ap_year = ap_year.reindex(range(hy_min, hy_max + 1))

    # All-time station record peaks.
    rec = ap.sort_values(["q", "t", "name"], ascending=[False, True, True], kind="mergesort")
    rec = rec.drop_duplicates("name", keep="first").reset_index(drop=True)
    top = rec.head(TOP_N)
    record = None
    if len(rec) and rec.iloc[0]["q"] > 0:
        r0 = rec.iloc[0]
        record = {"name": r0["name"], "q": float(r0["q"]), "t": r0["t"], "recon": bool(r0["recon"])}

    # Seasonality of annual peaks.
    month_counts = ap_pos.groupby(ap_pos["t"].dt.month).size()
    month_counts = {int(m): int(v) for m, v in month_counts.items()}
    season_total = sum(month_counts.values())

    # Synoptic storm days: most station annual peaks on one calendar day.
    pk_day = ap_pos["t"].dt.normalize()
    storm_ct = pk_day.value_counts()
    storm_df = pd.DataFrame({"day": storm_ct.index, "n": storm_ct.to_numpy()})
    storm_df = storm_df.sort_values(["n", "day"], ascending=[False, True], kind="mergesort").head(STORM_N)
    storms = []
    for day, n in zip(storm_df["day"], storm_df["n"]):
        sub = ap_pos[pk_day == day]
        mx = sub.sort_values(["q", "name"], ascending=[False, True], kind="mergesort").iloc[0]
        storms.append({"date": _date(day), "n": int(n), "max_q": _q(mx["q"]), "max_name": mx["name"],
                       "q": _qr(mx["q"])})

    # Station-time by flow type: each reading's flow type holds until the
    # station's next reading (capped at the end of its hydrological year);
    # the interval after a segment end is a gap and counts for nothing.
    dur = _durations(d)
    st_year = dur.groupby(["hy", "cls"], observed=False)["days"].sum().unstack(fill_value=0.0)
    st_year = st_year.reindex(index=range(hy_min, hy_max + 1), columns=TIME_ORDER, fill_value=0.0)
    totals = st_year.sum(axis=1)
    years_with = [int(y) for y in st_year.index if totals[y] > 0]
    flow_share = {f: {int(y): (float(st_year.at[y, f]) / float(totals[y]) if totals[y] else 0.0)
                      for y in st_year.index} for f in TIME_ORDER}

    # Sewage time per station over the last SEW_YEARS hydrological years.
    # Window ends at the latest complete year (a partial year would skew shares).
    sew_from = latest_full - SEW_YEARS + 1
    recent = dur[(dur["hy"] >= sew_from) & (dur["hy"] <= latest_full)]
    st_tot = recent.groupby("name")["days"].sum()
    sew_days = recent[recent["cls"] == SEWAGE].groupby("name")["days"].sum()
    sew_days = sew_days[sew_days >= 1].sort_index().sort_values(ascending=False, kind="mergesort")
    sew_top = sew_days.head(TOP_N)
    sew_share = {n: float(sew_days[n]) / float(st_tot[n]) for n in sew_top.index}
    n_sew_stations = int(len(sew_days))
    n_sew_ever = int(dur.loc[dur["cls"] == SEWAGE, "name"].nunique())

    # Heatmap: stations with flood flow, last HEAT_YEARS years x month.
    heat_years = list(range(max(hy_min, hy_max - HEAT_YEARS + 1), hy_max + 1))
    fm = d.loc[(d["flow"] == FLOOD) & (d["hy"] >= heat_years[0]), ["name", "hy", "t"]]
    fm = pd.DataFrame({"name": fm["name"].cat.codes, "hy": fm["hy"], "month": fm["t"].dt.month})
    fm = fm.drop_duplicates(["name", "hy", "month"])
    heat_ct = fm.groupby(["hy", "month"]).size()
    heat_cells = []
    heat_max = 0
    for yi, y in enumerate(heat_years):
        for mi, m in enumerate(HY_MONTHS):
            v = int(heat_ct.get((y, m), 0))
            heat_max = max(heat_max, v)
            heat_cells.append([mi, yi, v])

    # Latest full year vs each station's historical median annual peak.
    latest_rows = []
    lap = ap[ap["hy"] == latest_full].sort_values(["q", "name"], ascending=[False, True], kind="mergesort")
    hist = ap[ap["hy"] < latest_full]
    hist_med = hist.groupby("name")["q"].median()
    hist_n = hist.groupby("name").size()
    for name, q in zip(lap["name"], lap["q"]):
        n_h = int(hist_n.get(name, 0))
        med = float(hist_med[name]) if n_h >= MIN_HIST_YEARS else None
        latest_rows.append({"name": name, "peak": float(q), "median": med})
    n_active_latest = int(len(lap))

    # Longest records.
    span = ap.groupby("name").agg(first=("hy", "min"), last=("hy", "max"), years=("hy", "nunique"))
    span = span.reset_index().sort_values(["years", "first", "name"], ascending=[False, True, True],
                                          kind="mergesort")
    long_top = span.head(TOP_N)
    n_current = int((span["last"] >= latest_full).sum())

    # Decades summary.
    dec_rows = []
    d_dec = (d["hy"] // 10 * 10)
    rec_by_dec = d.groupby(d_dec)["recon"].mean()
    for dec in sorted(set(int(x) for x in d_dec.unique())):
        ys = [y for y in range(dec, dec + 10) if hy_min <= y <= hy_max]
        a = active.loc[ys]
        a = a[a > 0]
        apd = ap_pos[(ap_pos["hy"] >= dec) & (ap_pos["hy"] < dec + 10)]
        if apd.empty:
            continue
        mx = apd.sort_values(["q", "t", "name"], ascending=[False, True, True], kind="mergesort").iloc[0]
        dec_rows.append({
            "decade": f"{max(dec, hy_min)}-{min(dec + 9, hy_max)}",
            "active": f"{a.mean():,.0f}" if len(a) else "0",
            "max_q": _q(mx["q"]),
            "max_name": mx["name"],
            "recon": _pct(float(rec_by_dec[dec])),
        })

    recon_share = float(d["recon"].mean())
    n_recon_top = int(top["recon"].sum())


    rules = [
        ("record", insight_record(record)),
        ("latest", insight_latest(latest_rows, latest_full)),
        ("season", insight_season(month_counts)),
        ("storm", insight_storm(storms)),
        ("wettest", insight_wettest(ap_year.dropna())),
        ("network", insight_network(active_full[active_full > 0], partial)),
        ("sewage", insight_sewage(flow_share, [y for y in years_with if y <= latest_full])),
        ("sewage_stations", insight_sewage_stations(sew_days, st_tot, sew_from, latest_full)),
        ("recon", insight_recon(recon_share, n_recon_top, len(top))),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── charts ──────────────────────────────────────────────────────────
    network = {"x": [str(int(y)) for y in active_full.index], "y": [int(v) for v in active_full]}
    peaks_chart = {
        "x": [str(y) + (partial_lbl if y == hy_max else "") for y in ap_year.index],
        "max": [None if pd.isna(v) else _qr(v) for v in ap_year["max"]],
        "median": [None if pd.isna(v) else _qr(v) for v in ap_year["median"]],
    }
    records_chart = {
        "names": [n for n in top["name"]],
        "values": [_qr(v) for v in top["q"]],
        "dates": [_date(t) for t in top["t"]],
        "recon": [bool(r) for r in top["recon"]],
    }
    season_chart = {
        "months": [MONTH_HE[m] for m in HY_MONTHS],
        "values": [month_counts.get(m, 0) for m in HY_MONTHS],
        "winter": [m in (12, 1, 2) for m in HY_MONTHS],
    }
    heat_chart = {
        "months": [MONTH_HE[m] for m in HY_MONTHS],
        "years": [str(y) for y in heat_years],
        "cells": heat_cells,
        "max": max(heat_max, 1),
    }
    flow_chart = {
        "x": [str(y) + (partial_lbl if y == hy_max else "") for y in years_with],
        "series": [{"name": f, "data": [round(flow_share[f][y] * 100, 1) for y in years_with]}
                   for f in TIME_ORDER],
    }
    sewage_chart = {
        "names": [n for n in sew_top.index],
        "values": [int(round(v)) for v in sew_top],
        "share": [round(sew_share[n] * 100, 1) for n in sew_top.index],
    }
    latest_cmp = [r for r in latest_rows if r["median"] is not None][:LATEST_N]
    latest_chart = {
        "names": [r["name"] for r in latest_cmp],
        "peak": [_qr(r["peak"]) for r in latest_cmp],
        "median": [_qr(r["median"]) for r in latest_cmp],
    }
    long_chart = {
        "names": [n for n in long_top["name"]],
        "years": [int(v) for v in long_top["years"]],
        "first": [int(v) for v in long_top["first"]],
        "last": [int(v) for v in long_top["last"]],
    }
    storms_chart = {"dates": [s["date"] for s in storms], "n": [s["n"] for s in storms]}

    # ── KPIs ────────────────────────────────────────────────────────────
    active_latest = int(active_full.iloc[-1])
    peak_active = int(active_full.max())
    peak_active_y = int(active_full.idxmax())
    partial_txt = (f" השנה ההידרולוגית {hy_max} חלקית בנתונים ({partial[1]:,} תחנות עד כה) ואינה מוצגת."
                   if partial else "")
    kpis = {
        "stations": {"value": stations_all, "display": _int(stations_all), "tone": "brand"},
        "span": {"value": [hy_min, hy_max], "display": f"{hy_min}–{hy_max}", "tone": "brand"},
        "active": {"value": active_latest, "display": _int(active_latest),
                   "tone": "ok" if active_latest >= peak_active * 0.9 else "warn"},
        "record": {"value": record["q"] if record else 0, "display": _q(record["q"]) if record else "0",
                   "tone": "danger"},
    }

    latest_top = latest_cmp[0] if latest_cmp else None
    record_text = (f"{record['name']}, {_date(record['t'])}" if record else "")
    summary = (f"ספיקה רגעית והידרוגרף לפי תחנה הידרומטרית ונחל: {stations_all:,} תחנות, {hy_min}-{hy_max}. "
               f"שיטפונות, שיאי זרימה וזרימת ביוב. השיא: {_q(record['q']) if record else '0'} מ״ק/שנייה.")

    winter_share = (sum(month_counts.get(m, 0) for m in (12, 1, 2)) / season_total) if season_total else 0

    labels = {
        "lede": (f"המאגר מתעד את הספיקה הרגעית, כמות המים שעוברת בחתך הנחל בכל שנייה, "
                 f"ב-{stations_all:,} תחנות הידרומטריות של רשות המים בשנים ההידרולוגיות {hy_min}-{hy_max}. "
                 f"מהקריאות נבנה ההידרוגרף של כל נחל: עליית המים בשיטפון, השיא והירידה. "
                 f"בעמוד מוצגים השיאים, העונתיות, אירועי הסערה הגדולים ושיעור זרימת הביוב, "
                 f"על בסיס {n_rows:,} קריאות."),
        "kpi_stations": "תחנות הידרומטריות במאגר",
        "kpi_span": "שנים הידרולוגיות במאגר",
        "kpi_active": f"תחנות פעילות בשנה ההידרולוגית {latest_full}",
        "kpi_record": f"שיא ספיקה רגעית, מ״ק/שנייה ({record_text})",
        "network_lede": (f"מספר התחנות שרשמו קריאה כלשהי בכל שנה הידרולוגית. השיא: {peak_active:,} תחנות "
                         f"בשנת {peak_active_y}; בשנת {latest_full} פעלו {active_latest:,}.{partial_txt}"),
        "network_aria": (f"גרף עמודות: מספר התחנות הפעילות בכל שנה הידרולוגית, {hy_min} עד {latest_full}. "
                         f"השיא {peak_active:,} תחנות בשנת {peak_active_y}."),
        "peaks_lede": (f"לכל תחנה נלקחה הספיקה הגבוהה ביותר בשנה. הקו העליון הוא השיא הגבוה בכל הרשת, "
                       f"והתחתון הוא החציון של השיאים בתחנות, מדד לעוצמת השנה. ציר לוגריתמי."),
        "peaks_aria": (f"גרף קווים בציר לוגריתמי: השיא הארצי והחציון של השיאים השנתיים בתחנות, "
                       f"{hy_min} עד {hy_max}."),
        "records_lede": (f"הספיקה הרגעית הגבוהה ביותר שנרשמה בכל תחנה, {len(top):,} התחנות המובילות. "
                         f"ערכים משוחזרים מסומנים בטבלה."),
        "records_aria": (f"תרשים עמודות אופקי: {len(top):,} התחנות עם הספיקה הרגעית הגבוהה ביותר. "
                         + (f"המובילה {record['name']} עם {_q(record['q'])} מ״ק/שנייה." if record else "")),
        "season_lede": (f"באיזה חודש הגיעה כל תחנה לשיא השנתי שלה ({season_total:,} שיאים שנתיים). "
                        f"{_pct(winter_share)} מהם בדצמבר עד פברואר."),
        "season_aria": (f"תרשים עמודות: מספר השיאים השנתיים בתחנות לפי חודש, מאוקטובר עד ספטמבר. "
                        f"{_pct(winter_share)} מהשיאים בדצמבר עד פברואר."),
        "heat_lede": (f"מספר התחנות שרשמו זרימת שיטפון (גאות) בכל חודש, ב-{len(heat_years):,} השנים ההידרולוגיות "
                      f"האחרונות ({heat_years[0]}-{heat_years[-1]}). גוון כהה יותר = יותר תחנות בשיטפון."),
        "heat_aria": (f"מפת חום: מספר התחנות עם זרימת שיטפון לפי חודש ושנה הידרולוגית, "
                      f"{heat_years[0]} עד {heat_years[-1]}."),
        "storms_lede": ("הימים שבהם הכי הרבה תחנות הגיעו לשיא השנתי שלהן באותו יום: "
                        "סערות שהציפו נחלים רבים בבת אחת."),
        "storms_aria": ("תרשים עמודות: הימים עם מספר השיאים השנתיים הגבוה ביותר בתחנות. "
                        + (f"המוביל {storms[0]['date']} עם {storms[0]['n']:,} תחנות." if storms else "")),
        "flow_lede": ("איזה חלק מזמן המדידה בתחנות היה שיטפון, זרימה רגילה, אפיק יבש או זרימת ביוב. "
                      "כל קריאה מייצגת את הזמן עד הקריאה הבאה באותה תחנה, כך שהמדד אינו מושפע "
                      "מתדירות הקריאות, שגדלה בזמן שיטפון. פערים בין קטעי מדידה אינם נספרים."),
        "flow_aria": (f"גרף שטח מוערם באחוזים: חלוקת זמן המדידה בתחנות לפי סוג זרימה, "
                      f"{years_with[0] if years_with else hy_min} עד {hy_max}."),
        "sewage_lede": (f"ב-{n_sew_ever:,} תחנות נרשמה זרימת ביוב לאורך השנים, וב-{n_sew_stations:,} מהן "
                        f"בשנים {sew_from}-{latest_full}. אלה {len(sew_top):,} התחנות עם הכי הרבה ימי זרימת ביוב "
                        f"בתקופה זו, והשיעור מזמן המדידה בתחנה."),
        "sewage_aria": (f"תרשים עמודות אופקי: התחנות עם מספר ימי זרימת הביוב הגבוה ביותר, {sew_from} עד {latest_full}. "
                        + (f"המובילה {sew_top.index[0]} עם {int(round(sew_top.iloc[0])):,} ימים."
                           if len(sew_top) else "")),
        "latest_lede": (f"השיא בשנה ההידרולוגית {latest_full} ({n_active_latest:,} תחנות פעילות) לעומת החציון "
                        f"של השיאים השנתיים באותה תחנה בשנים הקודמות. מוצגות {len(latest_cmp):,} התחנות עם השיא "
                        f"הגבוה ביותר בשנה, מבין תחנות עם {MIN_HIST_YEARS} שנות היסטוריה לפחות."),
        "latest_aria": (f"תרשים עמודות כפול: השיא בשנה ההידרולוגית {latest_full} מול החציון ההיסטורי, "
                        f"{len(latest_cmp):,} תחנות."
                        + (f" המובילה {latest_top['name']} עם {_q(latest_top['peak'])} מ״ק/שנייה."
                           if latest_top else "")),
        "long_lede": (f"התחנות עם מספר השנים ההידרולוגיות הרב ביותר שבהן נרשמו קריאות. "
                      f"{n_current:,} תחנות רשמו קריאות גם בשנת {latest_full}."),
        "long_aria": ("תרשים עמודות אופקי: התחנות עם רצף המדידה הארוך ביותר. "
                      + (f"המובילה {long_top.iloc[0]['name']} עם {int(long_top.iloc[0]['years']):,} שנים."
                         if len(long_top) else "")),
        "decades_caption": "סיכום לפי עשור: תחנות פעילות בממוצע, השיא הגבוה ושיעור הקריאות המשוחזרות.",
        "records_caption": "התחנות עם הספיקה הרגעית הגבוהה ביותר: ספיקה, תאריך וסוג נתון.",
        "season_caption": "מספר השיאים השנתיים בתחנות לפי חודש.",
        "storms_caption": "הימים עם מספר השיאים השנתיים הגבוה ביותר בתחנות.",
        "sewage_caption": f"התחנות עם מספר ימי זרימת הביוב הגבוה ביותר, {sew_from} עד {latest_full}.",
        "latest_caption": f"השיא בשנה ההידרולוגית {latest_full} מול החציון ההיסטורי לפי תחנה.",
        "long_caption": "התחנות עם רצף המדידה הארוך ביותר.",
        "latest_series": f"שיא {latest_full}",
    }

    tables = {
        "decades": dec_rows,
        "records": [{"name": n, "q": _q(q), "date": _date(t), "kind": "משוחזר" if r else "נמדד"}
                    for n, q, t, r in zip(top["name"], top["q"], top["t"], top["recon"])],
        "season": [{"month": MONTH_HE[m], "n": f"{month_counts.get(m, 0):,}",
                    "share": _pct(month_counts.get(m, 0) / season_total) if season_total else "0.0%"}
                   for m in HY_MONTHS],
        "storms": [{"date": s["date"], "n": f"{s['n']:,}", "max_name": s["max_name"], "max_q": s["max_q"]}
                   for s in storms],
        "sewage": [{"name": n, "days": f"{int(round(v)):,}", "share": _pct(sew_share[n])}
                   for n, v in sew_top.items()],
        "latest": [{"name": r["name"], "peak": _q(r["peak"]), "median": _q(r["median"]),
                    "ratio": f"{r['peak'] / r['median']:.1f}" if r["median"] > 0 else "-"}
                   for r in latest_cmp],
        "long": [{"name": r["name"], "years": f"{int(r['years']):,}", "first": str(int(r["first"])),
                  "last": str(int(r["last"]))} for _, r in long_top.iterrows()],
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["הידרומטריה", "ספיקת נחלים", "שיטפונות", "הידרוגרף", "נחלים", "ביוב בנחלים"],
            "related_ids": [
                "d16214ba-56b3-417d-9342-6a144f215b9b",
                "e81d14bd-a81d-4de4-b1de-d7a0541ace02",
                "15072295-27ab-4939-951b-de462adc0ab0",
                "096db5d2-dc8b-40c8-9fe7-2b839a435d92",
                "db8f9bc9-738a-4d83-b3ce-74e8a5f7f844",
            ],
            "temporal_coverage": f"{hy_min - 1}/{hy_max}",  # hydro years run Oct (hy - 1) to Sep (hy)
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "network": network,
            "peaks": peaks_chart,
            "records": records_chart,
            "season": season_chart,
            "heat": heat_chart,
            "storms": storms_chart,
            "flow": flow_chart,
            "sewage": sewage_chart,
            "latest": latest_chart,
            "long": long_chart,
        },
        "flags": {
            "latest": len(latest_cmp) >= 3,
            "sewage": len(sew_top) >= 3,
            "storms": len(storms) >= 3,
        },
        "insights": insights,
        "labels": labels,
        "tables": tables,
        "meta": {"rows_raw": n_rows_raw},
    }
