"""תחנות - ספיקות שיא ונפחים שנתיים: the annual peak discharge (m3/s) and the
annual flow volume (million m3) of every stream gauging station of the
Hydrological Service, one row per (station, hydrological year).

Data notes (from profiling, 2026-10):
- Hydrological years run October-September and arrive as "YYYY/YYYY". A
  handful of rows use a short "YY/YY" form that duplicates years the same
  station also has in full form; short years are read as 19YY and a
  (station, year) pair keeps its full-form row. Any remaining duplicate pair
  keeps one row by a total sort, so the result never depends on row order.
- Empty volume / peak = not computed that year. Zero = no flow (a dry year).
- The date column is the day of the annual peak (dd/mm/yyyy); a few dates
  carry a 2-digit year ("0078"), so the peak month is read from the text.
- The station id encodes the drainage basin: all but its last three digits
  are the basin code (the same mapping the daily-volumes recipe uses).

Stations are nested along the same streams and the network changes a lot
over the decades, so national sums are meaningless. The year-to-year series
are INDICES: each station-year's value divided by that station's own
long-term median, and the median of those ratios over the stations measured
that year (100% = a normal year for the typical station).
"""
import math

import pandas as pd

C_ID = "זיהוי תחנה"
C_NAME = "שם תחנה בעברית"
C_YEAR = "שנה הידרולוגית"
C_VOL = "נפח שנתי (מלמ''ק)"
C_Q = "ספיקה מקסימלית (מ''ק/שניה)"
C_DATE = "תאריך המדידה"
C_NOTE = "הערות"

MIN_BASE_YEARS = 10        # station-years a station needs for its own median
MIN_INDEX_STATIONS = 15    # stations a year needs to enter an index
PARTIAL_SHARE = 0.6        # latest year with < 60% of the usual stations = partial
DRY = 0.6                  # volume index below this = a dry year
WET = 1.4                  # volume index at/above this = a wet year
NEAR_LO, NEAR_HI = 0.85, 1.15  # band that reads as "close to normal"
BIG_FLOOD = 2.0            # peak index at/above this = a big flood year
TOP_N = 12                 # rows of the ranking charts
WINDOW = 20                # years per window in the early/recent comparison
WINDOW_MIN = 10            # values a station needs in each window
DUMBBELL_N = 12            # stations shown in the comparison chart
SHIFT = 0.30               # relative change that counts as a decline/rise
LATEST_N = 12              # stations in the latest-year chart

REGIONS = [
    ("מקורות הירדן ועמק החולה", ["30"]),
    ("הכנרת ונחלי הגולן", ["31", "32"]),
    ("עמק הירדן ובקעת הירדן", ["34", "35", "36", "38", "41", "46"]),
    ("הגליל המערבי", ["1", "2", "3", "4", "5", "6", "7"]),
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
WINTER = (12, 1, 2)

NOTE_RULES = [
    ("sewage", "זרימת שפכים, ביוב או קולחין", ["שפכים", "ביוב", "קולחין"]),
    ("dry", "יבש או ללא זרימה", ["יבש", "לא היו זרימות", "ללא זרימה", "לא הייתה זרימה",
                                "לא היתה זרימה", "אין זרימה", "אין גלישה"]),
    ("human", "שאיבה, הטיה או מאגר במעלה הזרם", ["מאגר", "שאיבה", "צריכה", "המוטים",
                                               "הטיה", "שחרור מים", "מחצבה", "ניקוז מי השקייה"]),
    ("inactive", "תחנה לא פעילה", ["לא פעיל"]),
    ("norec", "אין רישום או נתונים בתיק", ["לא נמצא רישום", "אין נתונים", "אין  נתונים",
                                          "לא נמצאו", "אין רישום"]),
    ("quality", "נתון חלקי, משוער או בספק", ["בספק", "אינטרפולציה", "לא מלאים", "לא ניתן",
                                           "בודד", "טכני", "תדירות מדידות נמוכה"]),
    ("base", "זרימת בסיס בלבד", ["זרימת בסיס"]),
    ("hist", "נתון היסטורי מסיכום רב-שנתי", ["רב שנתון", "רב-שנתון", "רב שנתי", "רב-שנתי",
                                             "1990", "תיק של"]),
]
NOTE_OTHER = ("other", "הערה אחרת")

MINUS = "−"


# ── formatting ───────────────────────────────────────────────────────────

def ylab(y):
    return f"{int(y) - 1}/{int(y)}"


def fnum(v, digits=1):
    s = f"{abs(v):,.{digits}f}"
    return (MINUS + s) if v < 0 else s


def pct(r, digits=0):
    return f"{r * 100:,.{digits}f}%"


def r2(v, d=2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), d)


def in_(name):
    return "ב" + (name[1:] if name.startswith("ה") else name)


def region_of(sid):
    try:
        code = str(int(sid) // 1000)
    except (TypeError, ValueError):
        return OTHER_REGION
    return REGION_OF.get(code, OTHER_REGION)


def note_class(s):
    if not s:
        return None
    for key, _label, words in NOTE_RULES:
        if any(w in s for w in words):
            return key
    return NOTE_OTHER[0]


# ── load ─────────────────────────────────────────────────────────────────

def _end_year(s):
    s = str(s).strip()
    parts = s.split("/")
    if len(parts) != 2:
        return None, False
    a, b = parts[0].strip(), parts[1].strip()
    if not (a.isdigit() and b.isdigit()):
        return None, False
    if len(b) == 4:
        return int(b), False
    if len(b) == 2:
        return 1900 + int(b), True
    return None, False


def _month(s):
    parts = str(s).strip().split("/")
    if len(parts) != 3 or not parts[1].strip().isdigit():
        return None
    m = int(parts[1])
    return m if 1 <= m <= 12 else None


def _num(series):
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")


def load(df):
    out = pd.DataFrame({
        "sid": df[C_ID].astype(str).str.strip(),
        "name": df[C_NAME].astype(str).str.strip(),
        "raw_year": df[C_YEAR].astype(str).str.strip(),
        "v": _num(df[C_VOL]),
        "q": _num(df[C_Q]),
        "date": df[C_DATE].astype(str).str.strip(),
        "note": df[C_NOTE].astype(str).str.strip(),
    })
    yrs = out["raw_year"].map(_end_year)
    out["y"] = [t[0] for t in yrs]
    out["short"] = [t[1] for t in yrs]
    bad_year = int(out["y"].isna().sum())
    out = out[out["y"].notna() & (out["sid"] != "")].copy()
    out["y"] = out["y"].astype(int)
    out.loc[out["v"] < 0, "v"] = float("nan")
    out.loc[out["q"] < 0, "q"] = float("nan")
    n0 = len(out)
    out = out.sort_values(["sid", "y", "short", "raw_year", "v", "q", "date", "note", "name"],
                          na_position="last", kind="mergesort")
    out = out.drop_duplicates(["sid", "y"], keep="first").reset_index(drop=True)
    dups = n0 - len(out)
    out["month"] = out["date"].map(_month)
    out["region"] = out["sid"].map(region_of)
    # one display name per station: the name on its latest row
    nm = out.sort_values(["sid", "y"], kind="mergesort").groupby("sid")["name"].last()
    out["name"] = out["sid"].map(nm)
    return out, bad_year, dups


# ── compute ──────────────────────────────────────────────────────────────

def compute(frames):
    df, bad_year, dups = load(frames["main"])
    n_rows = len(df)
    stations = sorted(df["sid"].unique(), key=lambda s: (len(s), s))
    n_st = len(stations)
    names = df.drop_duplicates("sid").set_index("sid")["name"].to_dict()

    first_y, last_y = int(df["y"].min()), int(df["y"].max())
    has = df[df["v"].notna() | df["q"].notna()]

    # network size per year, and the "latest complete" year
    per_year = has.groupby("y")["sid"].nunique().sort_index()
    years_all = list(range(int(per_year.index.min()), int(per_year.index.max()) + 1))
    L = int(per_year.index.max())
    partial_note = None
    prev = per_year[per_year.index < L].tail(5)
    if len(prev) >= 3 and per_year[L] < PARTIAL_SHARE * float(prev.median()):
        partial_note = (f"השנה {ylab(L)} פורסמה חלקית ({per_year[L]:,} תחנות לעומת חציון של "
                        f"{int(prev.median()):,} בשנים שלפניה), ולכן השנה האחרונה בניתוח היא "
                        f"{ylab(int(prev.index.max()))}.")
        L = int(prev.index.max())
    n_latest = int(per_year.get(L, 0))

    # ── station baselines and indices ──
    def baseline(col):
        g = df[df[col].notna()].groupby("sid")[col]
        cnt, med = g.count(), g.median()
        ok = med[(cnt >= MIN_BASE_YEARS) & (med > 0)]
        return ok

    base_q, base_v = baseline("q"), baseline("v")

    def index_series(col, base):
        d = df[df[col].notna() & df["sid"].isin(base.index)].copy()
        d["r"] = d[col] / d["sid"].map(base)
        g = d.groupby("y")["r"]
        med, cnt = g.median(), g.count()
        ok = med[cnt >= MIN_INDEX_STATIONS]
        return ok, cnt, d

    qi, qi_n, qd = index_series("q", base_q)
    vi, vi_n, vd = index_series("v", base_v)
    idx_years = sorted(set(qi.index) | set(vi.index))
    idx_years = [y for y in idx_years if y <= L]
    chart_index = {
        "x": [ylab(y) for y in idx_years],
        "q": [r2(qi[y] * 100, 0) if y in qi.index else None for y in idx_years],
        "v": [r2(vi[y] * 100, 0) if y in vi.index else None for y in idx_years],
        "qn": [int(qi_n.get(y, 0)) for y in idx_years],
        "vn": [int(vi_n.get(y, 0)) for y in idx_years],
        "dry": DRY * 100, "wet": WET * 100, "flood": BIG_FLOOD * 100,
    }
    vi_L = vi[vi.index <= L]
    qi_L = qi[qi.index <= L]

    # ── KPI: record peak ──
    qrows = df[df["q"].notna()].sort_values(["q", "y", "sid"], ascending=[False, True, True],
                                            kind="mergesort")
    rec = qrows.iloc[0] if len(qrows) else None

    # ── chart: record annual peaks (top events) ──
    top_q = qrows.head(TOP_N)
    chart_peaks = {
        "names": [f"{names[s]} ({ylab(y)})" for s, y in zip(top_q["sid"], top_q["y"])],
        "q": [r2(v, 1) for v in top_q["q"]],
        "region": [r for r in top_q["region"]],
    }
    tbl_peaks = [{"name": names[s], "year": ylab(y), "date": d if d else "לא צוין",
                  "q": fnum(q, 1), "region": rg}
                 for s, y, d, q, rg in zip(top_q["sid"], top_q["y"], top_q["date"], top_q["q"],
                                           top_q["region"])]
    peak_regions = top_q["region"].value_counts()
    south_names = {"שקמה, בשור והנגב הצפוני", "מדבר יהודה וים המלח", "הנגב הדרומי והערבה"}
    south_top = int(top_q["region"].isin(south_names).sum())

    # ── chart: month of the annual peak ──
    mq = df[df["q"].notna() & (df["q"] > 0) & df["month"].notna()]
    mc = mq["month"].astype(int).value_counts()
    m_total = int(mc.sum())
    chart_month = {
        "months": [MONTH_HE[m] for m in HYDRO_MONTHS],
        "n": [int(mc.get(m, 0)) for m in HYDRO_MONTHS],
    }
    tbl_month = [{"month": MONTH_HE[m], "n": f"{int(mc.get(m, 0)):,}",
                  "share": pct(mc.get(m, 0) / m_total, 1) if m_total else "0%"}
                 for m in HYDRO_MONTHS]
    winter_share = (sum(int(mc.get(m, 0)) for m in WINTER) / m_total) if m_total else 0
    top_month = max(HYDRO_MONTHS, key=lambda m: (int(mc.get(m, 0)), -HYDRO_MONTHS.index(m))) if m_total else None

    # ── chart: largest flows (median annual volume per station) ──
    vstat = df[df["v"].notna()].groupby("sid")["v"].agg(["median", "count"])
    vstat = vstat[vstat["count"] >= MIN_BASE_YEARS].reset_index()
    vstat = vstat.sort_values(["median", "sid"], ascending=[False, True], kind="mergesort")
    top_v = vstat.head(TOP_N)
    chart_vol = {
        "names": [names[s] for s in top_v["sid"]],
        "v": [r2(v, 1) for v in top_v["median"]],
        "n": [int(c) for c in top_v["count"]],
    }
    tbl_vol = [{"name": names[s], "v": fnum(v, 1), "n": f"{int(c):,}"}
               for s, v, c in zip(top_v["sid"], top_v["median"], top_v["count"])]

    # ── regions ──
    reg_rows = []
    for rg in REGION_ORDER:
        d = df[df["region"] == rg]
        if not len(d):
            continue
        dq = d[d["q"].notna()]
        dv = d[d["v"].notna()]
        st_q = dq.groupby("sid")["q"].median()
        st_v = dv.groupby("sid")["v"].median()
        zero = (dv["v"] == 0).mean() if len(dv) else None
        reg_rows.append({
            "region": rg, "stations": int(d["sid"].nunique()),
            "q": r2(st_q.median(), 1) if len(st_q) else None,
            "v": r2(st_v.median(), 2) if len(st_v) else None,
            "zero": r2(zero * 100, 0) if zero is not None else None,
            "ratio": r2(st_q.median() / st_v.median(), 1) if len(st_q) and len(st_v) and st_v.median() > 0 else None,
        })
    chart_region = {
        "names": [r["region"] for r in reg_rows],
        "stations": [r["stations"] for r in reg_rows],
        "q": [r["q"] for r in reg_rows],
        "zero": [r["zero"] for r in reg_rows],
    }
    tbl_region = [{"region": r["region"], "stations": f"{r['stations']:,}",
                   "q": fnum(r["q"], 1) if r["q"] is not None else "אין",
                   "v": fnum(r["v"], 2) if r["v"] is not None else "אין",
                   "zero": f"{r['zero']:.0f}%" if r["zero"] is not None else "אין"}
                  for r in reg_rows]
    zr = [r for r in reg_rows if r["zero"] is not None and r["stations"] >= 3]
    zr_hi = max(zr, key=lambda r: (r["zero"], r["region"])) if zr else None
    zr_lo = min(zr, key=lambda r: (r["zero"], r["region"])) if zr else None

    # ── scatter: peak vs volume per station (flashiness) ──
    both = pd.DataFrame({"q": df[df["q"].notna()].groupby("sid")["q"].median(),
                         "v": df[df["v"].notna()].groupby("sid")["v"].median(),
                         "nq": df[df["q"].notna()].groupby("sid")["q"].count()}).dropna()
    both = both[(both["q"] > 0) & (both["v"] > 0) & (both["nq"] >= 5)]
    both = both.sort_index()
    sc_series = []
    for rg in REGION_ORDER:
        sub = both[[region_of(s) == rg for s in both.index]]
        if not len(sub):
            continue
        sc_series.append({"name": rg, "data": [[r2(v, 3), r2(q, 2), names[s]]
                                                 for s, v, q in zip(sub.index, sub["v"], sub["q"])]})
    flash = (both["q"] / both["v"]).sort_values(kind="mergesort") if len(both) else pd.Series(dtype=float)
    flash_reg = pd.DataFrame({"f": flash, "rg": [region_of(s) for s in flash.index]})
    flash_by_reg = flash_reg.groupby("rg")["f"].median() if len(flash_reg) else pd.Series(dtype=float)
    flash_by_reg = flash_by_reg[[(flash_reg["rg"] == r).sum() >= 3 for r in flash_by_reg.index]]

    # ── early vs recent windows (annual volume) ──
    r_lo, r_hi = L - WINDOW + 1, L
    e_lo, e_hi = L - 2 * WINDOW + 1, L - WINDOW
    dv = df[df["v"].notna()]
    early = dv[(dv["y"] >= e_lo) & (dv["y"] <= e_hi)].groupby("sid")["v"].agg(["mean", "count"])
    recent = dv[(dv["y"] >= r_lo) & (dv["y"] <= r_hi)].groupby("sid")["v"].agg(["mean", "count"])
    cmp_ = early.join(recent, lsuffix="_e", rsuffix="_r", how="inner")
    cmp_ = cmp_[(cmp_["count_e"] >= WINDOW_MIN) & (cmp_["count_r"] >= WINDOW_MIN) & (cmp_["mean_e"] > 0)]
    cmp_ = cmp_.reset_index().sort_values(["mean_e", "sid"], ascending=[False, True], kind="mergesort")
    cmp_["chg"] = cmp_["mean_r"] / cmp_["mean_e"] - 1
    n_cmp = len(cmp_)
    n_down = int((cmp_["chg"] <= -SHIFT).sum())
    n_up = int((cmp_["chg"] >= SHIFT).sum())
    db = cmp_.head(DUMBBELL_N)
    chart_db = {
        "names": [names[s] for s in db["sid"]],
        "e": [r2(v, 2) for v in db["mean_e"]],
        "r": [r2(v, 2) for v in db["mean_r"]],
        "chg": [r2(c * 100, 0) for c in db["chg"]],
        "el": f"{ylab(e_lo)}-{ylab(e_hi)}", "rl": f"{ylab(r_lo)}-{ylab(r_hi)}", "shift": SHIFT * 100,
    }
    tbl_db = [{"name": names[s], "e": fnum(a, 2), "r": fnum(b, 2),
               "chg": (("+" if c >= 0 else MINUS) + f"{abs(c) * 100:.0f}%")}
              for s, a, b, c in zip(db["sid"], db["mean_e"], db["mean_r"], db["chg"])]

    # ── latest year: stations vs their own median peak ──
    lat = df[(df["y"] == L) & df["q"].notna()].copy()
    lat["base"] = lat["sid"].map(base_q)
    lat = lat.sort_values(["q", "sid"], ascending=[False, True], kind="mergesort").head(LATEST_N)
    chart_latest = {
        "names": list(lat["name"]),
        "q": [r2(v, 1) for v in lat["q"]],
        "base": [r2(v, 1) for v in lat["base"]],
        "dates": [d if d else "לא צוין" for d in lat["date"]],
    }
    tbl_latest = [{"name": n, "q": fnum(q, 1), "date": d if d else "לא צוין",
                   "base": fnum(b, 1) if b == b and b is not None else "אין"}
                  for n, q, d, b in zip(lat["name"], lat["q"], lat["date"], lat["base"])]

    # ── network ──
    net_x = [y for y in years_all if y <= max(per_year.index)]
    vol_y = df[df["v"].notna()].groupby("y")["sid"].nunique()
    q_y = df[df["q"].notna()].groupby("y")["sid"].nunique()
    chart_net = {
        "x": [ylab(y) for y in net_x],
        "v": [int(vol_y.get(y, 0)) for y in net_x],
        "q": [int(q_y.get(y, 0)) for y in net_x],
    }
    peak_y = int(per_year.idxmax()) if len(per_year) else None
    peak_n = int(per_year.max()) if len(per_year) else 0
    long_rec = df[df["v"].notna() | df["q"].notna()].groupby("sid")["y"].nunique()
    longest = long_rec.sort_values(kind="mergesort")
    longest_sid = sorted(long_rec[long_rec == long_rec.max()].index, key=lambda s: (len(s), s))[0] if len(long_rec) else None

    # ── notes ──
    nc = df["note"].map(note_class)
    n_noted = int(nc.notna().sum())
    labels_map = {k: lab for k, lab, _w in NOTE_RULES}
    labels_map[NOTE_OTHER[0]] = NOTE_OTHER[1]
    ncnt = nc.dropna().value_counts()
    note_keys = sorted(ncnt.index, key=lambda k: (-int(ncnt[k]), k))
    chart_notes = {"names": [labels_map[k] for k in note_keys], "n": [int(ncnt[k]) for k in note_keys]}
    tbl_notes = [{"cat": labels_map[k], "n": f"{int(ncnt[k]):,}",
                  "st": f"{int(df[nc == k]['sid'].nunique()):,}"} for k in note_keys]
    sewage_st = int(df[nc == "sewage"]["sid"].nunique())
    sewage_recent = int(df[(nc == "sewage") & (df["y"] >= L - 9)]["sid"].nunique())

    # ── insights ──
    def ins_latest():
        if L not in vi.index:
            return None
        v = float(vi[L])
        if v < DRY:
            word = "שנה שחונה"
        elif v < NEAR_LO:
            word = "שנה מתחת לרגיל"
        elif v >= WET:
            word = "שנה גשומה"
        elif v >= NEAR_HI:
            word = "שנה מעל לרגיל"
        else:
            word = "שנה קרובה לרגיל"
        s = (f"בשנה ההידרולוגית {ylab(L)} הנפח השנתי בתחנה הטיפוסית היה {pct(v)} מהחציון הרב-שנתי "
             f"שלה ({word}, לפי {int(vi_n[L]):,} תחנות")
        if L in qi.index:
            s += f"), וספיקת השיא הייתה {pct(float(qi[L]))} מהרגיל."
        else:
            s += ")."
        return s

    def ins_extremes():
        if len(vi_L) < 10:
            return None
        hi_y = int(vi_L.sort_values(kind="mergesort").index[-1])
        hi = vi_L.max()
        lo_s = vi_L.sort_values(kind="mergesort")
        lo_y, lo = int(lo_s.index[0]), float(lo_s.iloc[0])
        lo_txt = f"{pct(lo)} בלבד" if lo >= 0.005 else "פחות מ-1%, כשרוב התחנות לא זרמו כלל"
        return (f"השנה הגשומה ביותר במדד הנפחים היא {ylab(hi_y)}, עם {pct(float(hi))} מהרגיל בתחנה הטיפוסית; "
                f"השחונה ביותר היא {ylab(lo_y)}, עם {lo_txt}.")

    def ins_record():
        if rec is None:
            return None
        s = (f"ספיקת השיא הגבוהה ביותר במאגר: {fnum(float(rec['q']), 0)} מ\"ק בשנייה "
             f"{in_(rec['name'])} בשנה ההידרולוגית {ylab(int(rec['y']))}")
        if south_top >= TOP_N // 2:
            s += (f". {south_top} מתוך {len(top_q)} אירועי השיא הגדולים נמדדו בנחלי הנגב, "
                  f"הערבה ומדבר יהודה, שבהם רוב השנה אין זרימה כלל.")
        else:
            s += "."
        return s

    def ins_season():
        if not m_total or winter_share < 0.4:
            return None
        return (f"{pct(winter_share)} משיאי הספיקה השנתיים נרשמו בדצמבר עד פברואר; "
                f"החודש השכיח ביותר לשיא הוא {MONTH_HE[top_month]} "
                f"({int(mc.get(top_month, 0)):,} מתוך {m_total:,} שיאים עם תאריך).")

    def ins_trend():
        if n_cmp < 10:
            return None
        if n_down >= 2 * max(n_up, 1) and n_down / n_cmp >= 0.25:
            return (f"ב-{n_down:,} מתוך {n_cmp:,} תחנות עם רצף מדידה ארוך, הנפח השנתי הממוצע "
                    f"ב-{chart_db['rl']} נמוך ביותר מ-{SHIFT * 100:.0f}% מזה של {chart_db['el']}; "
                    f"רק ב-{n_up:,} תחנות הוא עלה בשיעור כזה.")
        if n_up >= 2 * max(n_down, 1) and n_up / n_cmp >= 0.25:
            return (f"ב-{n_up:,} מתוך {n_cmp:,} תחנות עם רצף מדידה ארוך, הנפח השנתי הממוצע "
                    f"ב-{chart_db['rl']} גבוה ביותר מ-{SHIFT * 100:.0f}% מזה של {chart_db['el']}; "
                    f"רק ב-{n_down:,} תחנות הוא ירד בשיעור כזה.")
        return None

    def ins_zero():
        if not zr_hi or not zr_lo or zr_hi["zero"] - zr_lo["zero"] < 20:
            return None
        return (f"{in_(zr_hi['region'])} {zr_hi['zero']:.0f}% מהשנים הנמדדות עברו ללא זרימה כלל, "
                f"לעומת {zr_lo['zero']:.0f}% {in_(zr_lo['region'])}.")

    def ins_giant():
        if len(top_v) < 2:
            return None
        a = top_v.iloc[0]
        return (f"הזרימה השנתית הגדולה ביותר נמדדת {in_(names[a['sid']])}: חציון של "
                f"{fnum(float(a['median']), 0)} מיליון מ\"ק בשנה ({int(a['count']):,} שנות מדידה).")

    def ins_sewage():
        if sewage_st < 3:
            return None
        s = f"ב-{sewage_st:,} תחנות יש הערה על זרימת שפכים, ביוב או קולחין בנחל"
        if sewage_recent:
            s += f", {sewage_recent:,} מהן בעשור האחרון בנתונים"
        return s + "; בשנים כאלה הנפח הנמדד אינו זרימה טבעית בלבד."

    insights = []
    for key, fn in [("latest", ins_latest), ("record", ins_record), ("extremes", ins_extremes),
                    ("trend", ins_trend), ("season", ins_season), ("zero", ins_zero),
                    ("giant", ins_giant), ("sewage", ins_sewage)]:
        t = fn()
        if t:
            insights.append({"id": key, "text_he": t})

    # ── KPIs ──
    def tone_index(v):
        if v is None:
            return "brand"
        if v < DRY:
            return "danger"
        if v < NEAR_LO:
            return "warn"
        if v >= WET:
            return "ok"
        return "info"

    kpis = {
        "stations": {"value": n_st, "display": f"{n_st:,}", "tone": "brand"},
        "span": {"value": last_y - first_y + 1, "display": f"{first_y - 1}–{last_y}", "tone": "brand"},
        "records": {"value": n_rows, "display": f"{n_rows:,}", "tone": "brand"},
        "peak": {"value": r2(float(rec["q"]), 1) if rec is not None else None,
                 "display": fnum(float(rec["q"]), 0) if rec is not None else "אין", "tone": "info"},
    }
    kpi_labels = {
        "stations": "תחנות הידרומטריות במאגר",
        "span": "שנים הידרולוגיות במאגר",
        "records": "רשומות תחנה-שנה",
        "peak": (f"ספיקת השיא הגבוהה ביותר (מ\"ק בשנייה), {rec['name']} {ylab(int(rec['y']))}"
                 if rec is not None else "ספיקת השיא הגבוהה ביותר"),
    }
    kpi_order = ["stations", "span", "records", "peak"]
    if L in vi.index:
        v = float(vi[L])
        kpis["vol_idx"] = {"value": r2(v * 100, 0), "display": pct(v), "tone": tone_index(v)}
        kpi_labels["vol_idx"] = f"נפח שנתי ב-{ylab(L)} באחוזים מהרגיל (תחנה טיפוסית)"
        kpi_order.append("vol_idx")
    if L in qi.index:
        v = float(qi[L])
        kpis["q_idx"] = {"value": r2(v * 100, 0), "display": pct(v), "tone": tone_index(v)}
        kpi_labels["q_idx"] = f"ספיקת השיא ב-{ylab(L)} באחוזים מהרגיל (תחנה טיפוסית)"
        kpi_order.append("q_idx")

    # ── labels ──
    big_floods = [ylab(int(y)) for y in qi_L.sort_values(ascending=False, kind="mergesort").index
                  if qi_L[y] >= BIG_FLOOD][:5]
    labels = {
        "lede": (f"המאגר מרכז, לכל תחנה הידרומטרית בנחלי ישראל ולכל שנה הידרולוגית (אוקטובר עד ספטמבר), "
                 f"את ספיקת השיא השנתית (הספיקה הרגעית הגבוהה ביותר, מ\"ק בשנייה) ואת הנפח השנתי שזרם "
                 f"בתחנה (מיליון מ\"ק). {n_st:,} תחנות, {n_rows:,} רשומות, מהשנה {ylab(first_y)} ועד "
                 f"{ylab(last_y)}. בשנה {ylab(L)} דווחו נתונים מ-{n_latest:,} תחנות."),
        "index_note": (f"לכל תחנה עם {MIN_BASE_YEARS} שנות מדידה לפחות חושב חציון רב-שנתי; כל שנה מוצגת "
                       f"כחציון היחסים בין הערך באותה שנה לחציון של התחנה, על פני התחנות שנמדדו בה "
                       f"(100% = שנה רגילה). מוצגות רק שנים עם {MIN_INDEX_STATIONS} תחנות לפחות במדד. "
                       f"עמודות אדומות: נפח מתחת ל-{DRY * 100:.0f}% מהרגיל; כחול כהה: {WET * 100:.0f}% ומעלה."
                       + (f" שנות השיטפון הבולטות (ספיקת שיא פי {BIG_FLOOD:.0f} ומעלה מהרגיל): "
                          + ", ".join(big_floods) + "." if big_floods else "")),
        "index_aria": (f"גרף עמודות וקו: מדד הנפח השנתי ומדד ספיקת השיא לפי שנה הידרולוגית, "
                       f"{chart_index['x'][0] if chart_index['x'] else ''} עד {chart_index['x'][-1] if chart_index['x'] else ''}."),
        "peaks_note": (f"{len(top_q)} ספיקות השיא השנתיות הגבוהות ביותר בכל המאגר (תחנה ושנה). "
                       f"{south_top} מהן בנחלי הדרום והמדבר."),
        "peaks_aria": (f"גרף עמודות אופקי: {len(top_q)} ספיקות השיא הגבוהות במאגר. "
                       + (f"המובילה: {chart_peaks['names'][0]}, {chart_peaks['q'][0]:,} מ\"ק בשנייה." if len(top_q) else "")),
        "peaks_caption": f"{len(top_q)} ספיקות השיא השנתיות הגבוהות במאגר",
        "month_note": (f"החודש שבו נרשמה ספיקת השיא השנתית, על פני {m_total:,} שיאים עם תאריך "
                       f"(ללא שנים יבשות שבהן השיא אפס). {pct(winter_share)} מהשיאים בדצמבר עד פברואר."),
        "month_aria": (f"גרף עמודות: מספר שיאי הספיקה השנתיים לפי חודש. "
                       + (f"החודש השכיח: {MONTH_HE[top_month]}." if top_month else "")),
        "month_caption": "שיאי הספיקה השנתיים לפי חודש",
        "vol_note": (f"חציון הנפח השנתי של כל תחנה (מיליון מ\"ק), בתחנות עם {MIN_BASE_YEARS} שנות מדידה "
                     f"לפחות. תחנות לאורך אותו נחל (למשל כמה נקודות על הירדן) מופיעות בנפרד."),
        "vol_aria": (f"גרף עמודות אופקי: {len(top_v)} התחנות עם הנפח השנתי החציוני הגדול ביותר. "
                     + (f"בראש: {chart_vol['names'][0]}, {chart_vol['v'][0]:,} מיליון מ\"ק." if len(top_v) else "")),
        "vol_caption": f"{len(top_v)} התחנות עם הנפח השנתי החציוני הגדול",
        "region_note": ("לכל אזור ניקוז: חציון ספיקת השיא של התחנות (כל תחנה לפי החציון שלה), ושיעור "
                        "השנים הנמדדות שבהן הנפח השנתי היה אפס. האזור נגזר מקוד האגן שבמספר התחנה."),
        "region_aria": ("גרף עמודות אופקי: שיעור השנים ללא זרימה וחציון ספיקת השיא לפי אזור ניקוז. "
                        + (f"השיעור הגבוה: {zr_hi['region']}, {zr_hi['zero']:.0f}%." if zr_hi else "")),
        "region_caption": "ספיקת שיא, נפח שנתי ושנים ללא זרימה לפי אזור ניקוז",
        "flash_note": ("כל נקודה היא תחנה: ציר אופקי חציון הנפח השנתי, ציר אנכי חציון ספיקת השיא (שני "
                       "הצירים לוגריתמיים). תחנה גבוהה ושמאלית היא נחל שיטפוני: שיא חד ונפח קטן. "
                       "תחנות עם חמש שנות מדידה לפחות וערכים חיוביים."),
        "flash_aria": (f"תרשים פיזור: ספיקת שיא מול נפח שנתי של {len(both):,} תחנות, צבוע לפי אזור."),
        "db_note": (f"הנפח השנתי הממוצע בתקופה {chart_db['el']} לעומת {chart_db['rl']}, בתחנות עם "
                    f"{WINDOW_MIN} שנות מדידה לפחות בכל תקופה ({n_cmp:,} תחנות; מוצגות {len(db)} "
                    f"עם הנפח הגדול בתקופה הראשונה). ירידה של {SHIFT * 100:.0f}% ומעלה ב-{n_down:,} "
                    f"תחנות, עלייה כזו ב-{n_up:,}."),
        "db_aria": (f"תרשים משקולות: נפח שנתי ממוצע ב-{chart_db['el']} מול {chart_db['rl']} ב-{len(db)} תחנות."),
        "db_caption": f"נפח שנתי ממוצע ב-{chart_db['el']} מול {chart_db['rl']}",
        "latest_title": f"ספיקות השיא בשנה {ylab(L)}",
        "latest_note": (f"{len(lat)} התחנות עם ספיקת השיא הגבוהה ביותר בשנה {ylab(L)}, לצד החציון הרב-שנתי "
                        f"של כל תחנה (כשיש לה {MIN_BASE_YEARS} שנות מדידה לפחות)."
                        + (" " + partial_note if partial_note else "")),
        "latest_aria": (f"גרף עמודות אופקי: ספיקות השיא הגבוהות בשנה {ylab(L)}. "
                        + (f"בראש: {chart_latest['names'][0]}, {chart_latest['q'][0]:,} מ\"ק בשנייה." if len(lat) else "")),
        "latest_caption": f"ספיקות השיא הגבוהות בשנה {ylab(L)}",
        "net_note": (f"מספר התחנות עם נתון נפח שנתי ועם נתון ספיקת שיא בכל שנה. השיא: {peak_n:,} תחנות "
                     f"בשנה {ylab(peak_y) if peak_y else ''}. הרצף הארוך ביותר: "
                     f"{names[longest_sid] if longest_sid else ''}, {int(long_rec.max()) if len(long_rec) else 0:,} שנים."),
        "net_aria": (f"גרף קווים: מספר התחנות המדווחות לפי שנה הידרולוגית, שיא של {peak_n:,} תחנות."),
        "notes_note": (f"{n_noted:,} רשומות ({pct(n_noted / n_rows if n_rows else 0)}) נושאות הערה של השירות "
                       f"ההידרולוגי. ההערות סווגו לפי מילות מפתח; הערה שמתאימה לכמה קבוצות נספרת בראשונה."),
        "notes_aria": (f"גרף עמודות אופקי: רשומות עם הערה לפי סוג ההערה. "
                       + (f"הנפוץ: {chart_notes['names'][0]}." if note_keys else "")),
        "notes_caption": "רשומות עם הערה לפי סוג",
        "dedup_note": (f"{dups:,} רשומות כפולות (אותה תחנה ושנה, בכתיב שנה מקוצר) הושמטו." if dups else ""),
    }

    summary = (f"איתור ספיקת השיא והנפח השנתי של תחנה הידרומטרית לפי שם או מספר תחנה: {n_st:,} תחנות "
               f"בנחלי ישראל, {ylab(first_y)} עד {ylab(last_y)}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["הידרומטריה", "ספיקת שיא", "נפח זרימה", "נחלים", "שיטפונות", "רשות המים"],
            "related_ids": [
                "e81d14bd-a81d-4de4-b1de-d7a0541ace02",
                "15072295-27ab-4939-951b-de462adc0ab0",
                "f72117a6-2b71-43e9-bc81-75c284a4d1e2",
                "096db5d2-dc8b-40c8-9fe7-2b839a435d92",
                "fb522ddd-bd25-4272-abef-eceab9aa268d",
            ],
            "temporal_coverage": f"{first_y - 1}/{last_y}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "kpi_labels": kpi_labels,
        "charts": {
            "index": chart_index, "peaks": chart_peaks, "month": chart_month, "vol": chart_vol,
            "region": chart_region, "flash": {"series": sc_series}, "db": chart_db,
            "latest": chart_latest, "net": chart_net, "notes": chart_notes,
        },
        "tables": {
            "peaks": tbl_peaks, "month": tbl_month, "vol": tbl_vol, "region": tbl_region,
            "db": tbl_db, "latest": tbl_latest, "notes": tbl_notes,
        },
        "flags": {
            "index": len(idx_years) >= 5, "db": len(db) >= 3, "latest": len(lat) >= 3,
            "flash": len(both) >= 10, "notes": len(note_keys) >= 2,
        },
        "insights": insights,
        "labels": labels,
    }
