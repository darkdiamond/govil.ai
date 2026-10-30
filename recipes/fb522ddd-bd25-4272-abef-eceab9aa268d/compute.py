"""איכות מי נהר הירדן בגשר הפקק (גשר חורי): water-quality monitoring, 1970 onward.

Data: one long table, one row per (date, parameter, method) measurement at a
single station (שם תחנה). Parameters are coded (NO3, TN-N, TP-P, CL, ...),
units vary per parameter. Two methods: an automatic station and manual
sampling. Rows arrive monthly; the history has gaps (whole years missing).

Data-quality facts this recipe handles (found while authoring):
- Some results >= 1,000 were exported split at the thousands comma: the
  result column holds the thousands digit(s) and the unit column holds
  "<rest>,<unit>" (e.g. result "1", unit "135,MG/L" = 1,135 MG/L). These are
  re-joined; the count is disclosed on the page.
- Zero values cluster in a few years (1979-1984) where they fill missing
  measurements. Zero and negative results are left out of every median and
  percentile (disclosed).
- The NO3 series changes reporting basis: early years carry NO3 as nitrate
  (about 4.43 x the NO3-N value reported on the same dates), later years carry
  values in nitrogen terms (close to TN-N). The basis is detected per year
  from the NO3 / TN-N ratio, and a harmonised "nitrate as nitrogen" series is
  built; the raw series is still shown so the reader can see the break.

Every number below is computed from the data; "latest" is the latest date in
the data, never the clock.
"""
import re

import pandas as pd

COL_STATION = "שם תחנה"
COL_DATE = "תאריך ניטור"
COL_METHOD = "שיטת מדידה"
COL_CODE = "סמל פרמטר"
COL_VAL = "תוצאה"
COL_UNIT = "יחידת מדידה"

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

# Hebrew names for parameter codes (display only; unknown codes fall back to
# the code itself, so new parameters flow through).
NAMES = {
    "NO3": "חנקה",
    "NO3-N": "חנקן חנקתי",
    "NO3N_H": "חנקה כחנקן",
    "NO2": "ניטריט",
    "NO2-N": "חנקן ניטריטי",
    "TN-N": "חנקן כללי",
    "TKN": "חנקן קלדל",
    "DKN": "חנקן קלדל מומס",
    "TDN-N": "חנקן מומס כללי",
    "NH4": "אמוניום",
    "NH4-N": "חנקן אמוניאקלי",
    "NTOT": "חנקן כללי (מדידה נוספת)",
    "TP-P": "זרחן כללי",
    "DP-P": "זרחן מומס",
    "TDP-P": "זרחן מומס כללי",
    "PP-P": "זרחן חלקיקי",
    "PO4": "פוספט",
    "TSS": "מוצקים מרחפים",
    "TURB": "עכירות",
    "CL": "כלוריד",
    "SO4": "סולפט",
    "ALKM": "אלקליניות",
    "CA": "סידן",
    "Mg": "מגנזיום",
    "NA": "נתרן",
    "K": "אשלגן",
    "EC": "מוליכות חשמלית",
    "PHS": "הגבה (pH)",
    "T": "טמפרטורת המים",
    "DO": "חמצן מומס",
    "TOC": "פחמן אורגני כללי",
    "DOC": "פחמן אורגני מומס",
    "FE": "ברזל",
    "SIO2": "סיליקה",
    "HARD": "קשיות",
}
UNITS_HE = {
    "MG/L": "מ״ג לליטר",
    "microgr/L": "מק״ג לליטר",
    "Celsius": "מעלות צלזיוס",
    "UNIT": "יחידות",
    "NTU": "NTU",
}

# Parameters compared "early vs recent" (change chart). Order = display order.
CHANGE_CODES = ["TN-N", "NO3N_H", "TKN", "NH4", "TP-P", "DP-P",
                "CL", "SO4", "ALKM", "CA", "TSS", "TURB"]

NO3_PER_N = 62.004 / 14.007   # nitrate -> nitrogen mass ratio (about 4.43)
MIN_YEAR_N = 12               # min valid values for a yearly median
BASE_YEARS = 10               # "early" window: first N years with data
RECENT_YEARS = 5              # "recent" window: last N years with data
TOP_PARAMS = 15               # parameter-count chart: top N + "אחר"
CHANGE_THRESHOLD = 0.10       # +/-10% = "stable" band for change wording
BIG_CHANGE = 0.20             # a change insight needs at least +/-20%

SPLIT_UNIT = re.compile(r"^(\d[\d.]*),(.+)$")


# ----------------------------------------------------------------- helpers

def name_of(code):
    return NAMES.get(code, code)


def label_of(code):
    """"שם (קוד)", or the bare code when it has no Hebrew name."""
    n = NAMES.get(code)
    return f"{n} ({code})" if n else code


def unit_he(unit):
    return UNITS_HE.get(unit, unit)


def fnum(v):
    """Concentration for prose / tables: precision by magnitude."""
    if v is None:
        return "לא נמדד"
    a = abs(v)
    if a >= 100:
        s = f"{v:,.0f}"
    elif a >= 10:
        s = f"{v:,.1f}"
    elif a >= 1:
        s = f"{v:,.2f}"
    else:
        s = f"{v:,.3f}"
    return s.replace("-", "−")


def rnd(v):
    """Rounded float for chart arrays (or None)."""
    if v is None or pd.isna(v):
        return None
    a = abs(v)
    if a >= 100:
        return round(float(v), 1)
    if a >= 1:
        return round(float(v), 2)
    return round(float(v), 4)


def pct(frac):
    return f"{abs(frac) * 100:.0f}%"


def signed_pct(frac):
    s = f"{frac * 100:+.0f}%"
    return s.replace("-", "−")


def year_runs(years):
    """[1979, 1980, 1981, 1990] -> [(1979, 1981), (1990, 1990)]."""
    runs = []
    for y in sorted(years):
        if runs and y == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], y)
        else:
            runs.append((y, y))
    return runs


def run_text(a, b):
    return str(a) if a == b else f"{a}-{b}"


# ------------------------------------------------------------- preparation

def _prepare(df):
    unit_raw = df[COL_UNIT].astype(str).str.strip()
    val_raw = df[COL_VAL].astype(str).str.strip().str.replace(" ", "", regex=False)
    m = unit_raw.str.extract(SPLIT_UNIT)
    split = m[0].notna() & val_raw.str.fullmatch(r"\d{1,3}")
    joined = (val_raw + m[0].fillna("")).where(split, val_raw)
    joined = joined.str.replace(",", "", regex=False)
    out = pd.DataFrame({
        "d": pd.to_datetime(df[COL_DATE].astype(str).str.slice(0, 10),
                            errors="coerce", format="%Y-%m-%d"),
        "code": df[COL_CODE].astype(str).str.strip(),
        "method": df[COL_METHOD].astype(str).str.strip(),
        "unit": m[1].where(split, unit_raw).fillna(unit_raw).str.strip(),
        "v": pd.to_numeric(joined, errors="coerce"),
        "station": df[COL_STATION].astype(str).str.strip(),
    })
    n_split = int(split.sum())
    out = out[out["d"].notna() & out["v"].notna() & (out["code"] != "")]
    out = out.copy()
    out["y"] = out["d"].dt.year.astype(int)
    out["mo"] = out["d"].dt.month.astype(int)
    return out.reset_index(drop=True), n_split


def _dominant_unit(df):
    g = df.groupby(["code", "unit"]).size().reset_index(name="n")
    g = g.sort_values(["code", "n", "unit"], ascending=[True, False, True])
    return dict(zip(g.drop_duplicates("code")["code"],
                    g.drop_duplicates("code")["unit"]))


def _yearly_median(pos, code):
    s = pos[pos["code"] == code]
    if s.empty:
        return {}
    g = s.groupby("y")["v"].agg(["median", "size"])
    g = g[g["size"] >= MIN_YEAR_N]
    return {int(y): float(v) for y, v in g["median"].items()}


def _harmonised_nitrate(pos):
    """Yearly median of nitrate expressed as nitrogen.

    Per year: NO3-N when it was reported, otherwise NO3 converted by its
    detected basis. Basis: NO3/TN-N ratio > 2.2 -> nitrate (divide by 4.43);
    < 1.5 -> already nitrogen; in between -> unknown (year left empty).
    Returns (series, basis_by_year)."""
    no3n = _yearly_median(pos, "NO3-N")
    no3 = _yearly_median(pos, "NO3")
    tn = _yearly_median(pos, "TN-N")
    series, basis = {}, {}
    for y in sorted(set(no3) | set(no3n)):
        b = None
        if y in no3 and y in tn and tn[y] > 0:
            r = no3[y] / tn[y]
            b = "nitrate" if r > 2.2 else ("nitrogen" if r < 1.5 else None)
        basis[y] = b
        if y in no3n:
            series[y] = no3n[y]
        elif y in no3 and b == "nitrate":
            series[y] = no3[y] / NO3_PER_N
        elif y in no3 and b == "nitrogen":
            series[y] = no3[y]
    return series, basis


def _window_median(series, years):
    vals = [series[y] for y in years if y in series]
    if len(vals) < 2:
        return None
    return float(pd.Series(vals).median())


# ------------------------------------------------------------------ compute

def compute(frames):
    df, n_split = _prepare(frames["main"])
    units = _dominant_unit(df)

    sc = df.groupby("station").size().reset_index(name="n")
    station = sc.sort_values(["n", "station"], ascending=[False, True]).iloc[0]["station"]
    total = int(len(df))
    y0, y1 = int(df["y"].min()), int(df["y"].max())
    last_date = df["d"].max()
    years_present = sorted(int(y) for y in df["y"].unique())
    all_years = list(range(y0, y1 + 1))
    missing = [y for y in all_years if y not in set(years_present)]
    gap_runs = year_runs(missing)
    n_params = int(df["code"].nunique())

    # Partial latest year: fewer months than the median full year.
    months_per_year = df.groupby("y")["mo"].nunique()
    last_months = int(months_per_year.get(y1, 0))
    typical_months = int(months_per_year.median())
    last_partial = last_months < min(12, typical_months)

    # Positive values only for medians (zeros fill missing measurements).
    pos = df[df["v"] > 0]
    n_nonpos = int((df["v"] <= 0).sum())
    zero_share = (df.assign(z=df["v"] <= 0).groupby("y")["z"].mean())
    zero_heavy = [int(y) for y, s in zero_share.items() if s >= 0.25]
    zero_runs = year_runs(zero_heavy)

    # ------------------------------------------------ measurements per year
    meth = (df.groupby(["y", "method"]).size().unstack(fill_value=0)
            .reindex(all_years, fill_value=0))
    methods = sorted(meth.columns.tolist(),
                     key=lambda c: (-int(meth[c].sum()), c))
    years_chart = {
        "x": [f"{y} (חלקית)" if (y == y1 and last_partial) else str(y)
              for y in all_years],
        "series": [{"name": m, "data": [int(v) for v in meth[m].tolist()]}
                   for m in methods],
    }

    # ----------------------------------------------- yearly-median line charts
    def line_chart(codes):
        series = []
        for c in codes:
            s = harmon if c == "NO3N_H" else _yearly_median(pos, c)
            if len([v for v in s.values()]) < 3:
                continue
            series.append({
                "code": "NO3-N" if c == "NO3N_H" else c, "name": name_of(c),
                "data": [rnd(s.get(y)) for y in all_years],
            })
        return {"x": [str(y) for y in all_years], "series": series}

    harmon, basis = _harmonised_nitrate(pos)
    nitrogen = line_chart(["TN-N", "NO3N_H", "TKN"])
    raw_no3 = _yearly_median(pos, "NO3")
    if len(raw_no3) >= 3:
        nitrogen["raw"] = {"name": "חנקה כפי שדווחה (NO3)",
                           "data": [rnd(raw_no3.get(y)) for y in all_years]}
    else:
        nitrogen["raw"] = None
    phos = line_chart(["TP-P", "DP-P", "PP-P"])
    ions = line_chart(["CL", "SO4", "NA", "Mg"])
    solids = line_chart(["TSS", "TURB"])

    # TSS p90 by year (flood intensity)
    tss = pos[pos["code"] == "TSS"]
    if not tss.empty:
        g = tss.groupby("y")["v"].agg(lambda s: s.quantile(0.9) if len(s) >= MIN_YEAR_N else None)
        solids["p90"] = [rnd(g.get(y)) for y in all_years]
    else:
        solids["p90"] = None

    # ------------------------------------------------ seasonality (by month)
    def month_profile(code):
        s = pos[pos["code"] == code]
        if s["mo"].nunique() < 12:
            return None
        g = s.groupby("mo")["v"]
        med = g.median()
        return {
            "median": [rnd(med.get(m)) for m in range(1, 13)],
            "p10": [rnd(g.quantile(0.1).get(m)) for m in range(1, 13)],
            "p90": [rnd(g.quantile(0.9).get(m)) for m in range(1, 13)],
            "n": [int(g.size().get(m, 0)) for m in range(1, 13)],
        }

    season = {"months": MONTHS_HE, "tss": month_profile("TSS"),
              "turb": month_profile("TURB")}
    temp = month_profile("T")
    temp_years = sorted(int(y) for y in pos[pos["code"] == "T"]["y"].unique())

    # ----------------------------------------------------- TSS heatmap
    heat = None
    if not tss.empty:
        hm = tss.groupby(["y", "mo"])["v"].median()
        cells = []
        for (y, mo), v in hm.items():
            cells.append([all_years.index(int(y)), int(mo) - 1, rnd(v)])
        cells.sort(key=lambda c: (c[0], c[1]))
        vmax = float(hm.quantile(0.95)) if len(hm) else 0.0
        heat = {"x": [str(y) for y in all_years], "y": MONTHS_HE,
                "cells": cells, "max": rnd(vmax), "n_cells": len(cells)}

    # ---------------------------------------- early vs recent change chart
    base_years = years_present[:BASE_YEARS]
    recent_years = years_present[-RECENT_YEARS:]
    win_base = run_text(min(base_years), max(base_years))
    win_recent = run_text(min(recent_years), max(recent_years))
    change_rows = []
    for c in CHANGE_CODES:
        s = harmon if c == "NO3N_H" else _yearly_median(pos, c)
        b = _window_median(s, base_years)
        r = _window_median(s, recent_years)
        if b is None or r is None or b <= 0:
            continue
        unit = units.get("NO3-N" if c == "NO3N_H" else c, "")
        bys = [y for y in base_years if y in s]
        rys = [y for y in recent_years if y in s]
        change_rows.append({
            "code": "NO3-N" if c == "NO3N_H" else c,
            "name": name_of(c), "unit": unit_he(unit),
            "base": rnd(b), "recent": rnd(r),
            "base_display": fnum(b), "recent_display": fnum(r),
            "change": round((r - b) / b, 4),
            "change_display": signed_pct((r - b) / b),
            "base_span": run_text(min(bys), max(bys)),
            "recent_span": run_text(min(rys), max(rys)),
        })
    change_chart = {
        "names": [f"{r['name']} ({r['code']})" for r in change_rows],
        "values": [round(r["change"] * 100, 1) for r in change_rows],
    }

    # ------------------------------------------------ chloride by decade
    cl = pos[pos["code"] == "CL"].copy()
    decade = None
    if not cl.empty:
        cl["dec"] = (cl["y"] // 10) * 10
        rows = []
        for dec, g in sorted(cl.groupby("dec"), key=lambda t: t[0]):
            if len(g) < MIN_YEAR_N:
                continue
            q = g["v"].quantile([0, 0.25, 0.5, 0.75, 1.0]).tolist()
            # whiskers at 5th/95th percentiles (extremes stay in the table)
            lo, hi = g["v"].quantile(0.05), g["v"].quantile(0.95)
            rows.append({
                "label": f"שנות ה-{str(int(dec))[-2:]}" if dec < 2000 else f"{int(dec)}-{int(dec) + 9}",
                "box": [rnd(lo), rnd(q[1]), rnd(q[2]), rnd(q[3]), rnd(hi)],
                "n": int(len(g)), "median": fnum(q[2]),
                "p5": fnum(lo), "p95": fnum(hi), "max": fnum(q[4]),
            })
        if len(rows) >= 2:
            decade = {"labels": [r["label"] for r in rows],
                      "boxes": [r["box"] for r in rows], "rows": rows,
                      "unit": unit_he(units.get("CL", ""))}

    # ---------------------------------------------- parameter catalogue
    pc = (df.groupby("code").agg(n=("v", "size"), y_first=("y", "min"),
                                 y_last=("y", "max"))
          .reset_index().sort_values(["n", "code"], ascending=[False, True],
                                     kind="mergesort"))
    top = pc.head(TOP_PARAMS)
    rest = pc.iloc[TOP_PARAMS:]
    params_chart = {
        "names": [label_of(c) for c in top["code"]],
        "values": [int(v) for v in top["n"]],
    }
    params_rows = [{"name": label_of(c), "n": int(n),
                    "unit": unit_he(units.get(c, "")),
                    "span": run_text(int(a), int(b))}
                   for c, n, a, b in zip(top["code"], top["n"], top["y_first"], top["y_last"])]
    if len(rest):
        params_chart["names"].append(f"אחר ({len(rest)} פרמטרים)")
        params_chart["values"].append(int(rest["n"].sum()))
        params_rows.append({"name": f"אחר ({len(rest)} פרמטרים)",
                            "n": int(rest["n"].sum()), "unit": "",
                            "span": run_text(int(rest["y_first"].min()), int(rest["y_last"].max()))})
    params_chart["values"] = list(reversed(params_chart["values"]))
    params_chart["names"] = list(reversed(params_chart["names"]))

    # =============================================================== insights
    def ins_nitrate_basis():
        early = sorted(y for y, b in basis.items() if b == "nitrate")
        late = sorted(y for y, b in basis.items() if b == "nitrogen")
        if not early or not late or min(late) < max(early):
            return None
        y_a, y_b = max(early), min(late)
        tn = _yearly_median(pos, "TN-N")
        if y_a not in raw_no3 or y_b not in raw_no3 or y_a not in tn or y_b not in tn:
            return None
        drop = (raw_no3[y_b] - raw_no3[y_a]) / raw_no3[y_a]
        tn_ch = (tn[y_b] - tn[y_a]) / tn[y_a]
        if drop > -0.5 or abs(tn_ch) > 0.25:
            return None
        return (f"הירידה החדה בחנקה (NO3), מחציון של {fnum(raw_no3[y_a])} מ״ג לליטר ב-{y_a} "
                f"ל-{fnum(raw_no3[y_b])} ב-{y_b}, איננה שיפור באיכות המים: החנקן הכללי (TN-N) "
                f"נע באותן שנים רק מ-{fnum(tn[y_a])} ל-{fnum(tn[y_b])}. היחס בין שני המדדים "
                f"מראה שמ-{y_b} החנקה מדווחת במונחי חנקן ולא כחנקה, ולכן בגרף החנקן "
                f"כל השנים הומרו לאותו בסיס (חלוקה ב-{NO3_PER_N:.2f}).")

    def _change_of(code):
        for r in change_rows:
            if r["code"] == code:
                return r
        return None

    def ins_total_n():
        r = _change_of("TN-N")
        if r is None:
            return None
        ch = r["change"]
        if abs(ch) < CHANGE_THRESHOLD:
            verdict = "כמעט ללא שינוי"
        elif ch > 0:
            verdict = f"עלייה של {pct(ch)}"
        else:
            verdict = f"ירידה של {pct(ch)}"
        return (f"חנקן כללי (TN-N): חציון של {r['recent_display']} מ״ג לליטר בשנים "
                f"{r['recent_span']}, לעומת {r['base_display']} בשנים {r['base_span']}: "
                f"{verdict}.")

    def ins_biggest_change():
        cands = [r for r in change_rows if r["code"] != "TN-N"
                 and abs(r["change"]) >= BIG_CHANGE]
        if not cands:
            return None
        downs = sorted([r for r in cands if r["change"] < 0],
                       key=lambda r: (r["change"], r["code"]))
        ups = sorted([r for r in cands if r["change"] > 0],
                     key=lambda r: (-r["change"], r["code"]))
        def part(kind, r):
            return (f"{kind} הגדולה ביותר נרשמה ב{r['name']} ({r['code']}): מחציון של "
                    f"{r['base_display']} {r['unit']} בשנים {r['base_span']} ל-{r['recent_display']} "
                    f"בשנים {r['recent_span']} ({r['change_display']})")

        parts = []
        if downs:
            parts.append(part("הירידה", downs[0]))
        if ups:
            parts.append(part("העלייה", ups[0]))
        return "; ".join(parts) + "."

    def ins_season():
        p = season["tss"]
        if p is None:
            return None
        med = p["median"]
        if any(v is None for v in med):
            return None
        hi = max(range(12), key=lambda i: (med[i], -i))
        lo = min(range(12), key=lambda i: (med[i], i))
        if med[lo] <= 0 or med[hi] / med[lo] < 1.5:
            return None
        return (f"עונתיות חזקה במוצקים מרחפים: החציון ב{MONTHS_HE[hi]} ({fnum(med[hi])} מ״ג לליטר) "
                f"גבוה פי {med[hi] / med[lo]:.1f} מאשר ב{MONTHS_HE[lo]} ({fnum(med[lo])}), "
                f"ובחודשי השיא נמדדו גם הערכים הקיצוניים (אחוזון 90 של {fnum(p['p90'][hi])}).")

    def ins_temp():
        if temp is None:
            return None
        med = temp["median"]
        if any(v is None for v in med):
            return None
        hi = max(range(12), key=lambda i: (med[i], -i))
        lo = min(range(12), key=lambda i: (med[i], i))
        return (f"טמפרטורת המים נעה בין חציון של {fnum(med[lo])} מעלות ב{MONTHS_HE[lo]} "
                f"ל-{fnum(med[hi])} מעלות ב{MONTHS_HE[hi]} "
                f"({len(temp_years)} שנות מדידה של הטמפרטורה בין {temp_years[0]} ל-{temp_years[-1]}).")

    def ins_gaps():
        if not missing:
            return None
        txt = ", ".join(run_text(a, b) for a, b in gap_runs)
        return (f"ברצף המדידות יש פערים: אין מדידות כלל בשנים {txt} "
                f"({len(missing)} שנים מתוך {len(all_years)}), ולכן הקווים בגרפים נקטעים בהן.")

    def ins_method():
        if len(methods) < 2:
            return None
        auto = [m for m in methods if "אוטומטית" in m]
        if not auto:
            return None
        a = auto[0]
        tot = meth.sum(axis=1)
        share_last = float(meth.loc[y1, a] / tot.loc[y1]) if tot.loc[y1] else None
        manual_only = [y for y in years_present if meth.loc[y, a] == 0]
        runs = [r for r in year_runs(manual_only) if r[1] - r[0] >= 2]
        if share_last is None:
            return None
        s = f"ב-{y1} הגיעו {pct(share_last)} מהמדידות מהתחנה האוטומטית"
        if runs:
            r = max(runs, key=lambda t: (t[1] - t[0], t[0]))
            s += f", לעומת השנים {run_text(*r)} שבהן נרשמו מדידות ידניות בלבד"
        return s + "."

    rules = [
        ("nitrate_basis", ins_nitrate_basis()),
        ("total_n", ins_total_n()),
        ("biggest_change", ins_biggest_change()),
        ("season_tss", ins_season()),
        ("temperature", ins_temp()),
        ("gaps", ins_gaps()),
        ("method", ins_method()),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ================================================================= KPIs
    def change_tone(code, bad_up=True):
        r = _change_of(code)
        if r is None:
            return "brand"
        ch = r["change"] if bad_up else -r["change"]
        if ch > 0.30:
            return "danger"
        if ch > CHANGE_THRESHOLD:
            return "warn"
        if ch < -CHANGE_THRESHOLD:
            return "ok"
        return "brand"

    tn_r = _change_of("TN-N")
    tp_r = _change_of("TP-P")
    kpis = {
        "total": {"value": total, "display": f"{total:,}", "tone": "brand"},
        "span": {"value": f"{y0}-{y1}", "display": f"{y0}–{y1}", "tone": "brand"},
        "params": {"value": n_params, "display": f"{n_params:,}", "tone": "brand"},
        "years": {"value": len(years_present), "display": f"{len(years_present):,}",
                  "tone": "warn" if missing else "ok"},
    }
    kpi_order = ["total", "span", "params", "years"]
    kpi_labels = {
        "total": "מדידות במאגר",
        "span": "טווח השנים",
        "params": "פרמטרים שנמדדו",
        "years": (f"שנים עם מדידות ({len(missing)} שנים חסרות)" if missing
                  else "שנים עם מדידות, ללא פערים"),
    }
    if tn_r:
        kpis["tn"] = {"value": tn_r["recent"], "display": tn_r["recent_display"],
                      "tone": change_tone("TN-N")}
        kpi_labels["tn"] = f"חנקן כללי, חציון {tn_r['recent_span']} (מ״ג לליטר)"
        kpi_order.append("tn")
    if tp_r:
        kpis["tp"] = {"value": tp_r["recent"], "display": tp_r["recent_display"],
                      "tone": change_tone("TP-P")}
        kpi_labels["tp"] = f"זרחן כללי, חציון {tp_r['recent_span']} (מ״ג לליטר)"
        kpi_order.append("tp")

    # ============================================================ labels
    last_he = f"{last_date.day} ב{MONTHS_HE[last_date.month - 1]} {last_date.year}"
    gaps_txt = ", ".join(run_text(a, b) for a, b in gap_runs)
    zero_txt = ", ".join(run_text(a, b) for a, b in zero_runs)
    lede = (f"תוצאות ניטור איכות המים של נהר הירדן בתחנת {station}, "
            f"מקור המים העיקרי של הכנרת. במאגר {total:,} מדידות של {n_params} פרמטרים: "
            f"חנקן וזרחן, מלחים (כלוריד, סולפט), מוצקים מרחפים, עכירות וטמפרטורה, "
            f"מ-{y0} ועד {last_he}. המדידות מגיעות מתחנת ניטור אוטומטית ומדגימות ידניות של חברת מקורות.")
    method_note = (f"החציונים השנתיים מחושבים רק לשנים עם {MIN_YEAR_N} מדידות לפחות של הפרמטר. "
                   f"ערכי אפס ומתחת לאפס ({n_nonpos:,} מדידות"
                   + (f", רובן בשנים {zero_txt}, שבהן הם ממלאים מדידות חסרות" if zero_runs else "")
                   + ") אינם נכללים בחציונים ובאחוזונים.")
    if n_split:
        method_note += (f" ב-{n_split:,} רשומות ערך של אלפים נחתך בייצוא בפסיק האלפים "
                        f"(חלקו נרשם בעמודת היחידה) והוא אוחד מחדש.")

    tn_last = nitrogen["series"][0]["data"][-1] if nitrogen["series"] else None
    labels = {
        "lede": lede,
        "method_note": method_note,
        "years_note": (f"מספר המדידות בכל שנה לפי שיטת המדידה."
                       + (f" אין מדידות בשנים {gaps_txt}." if missing else "")
                       + (f" שנת {y1} חלקית (עד {MONTHS_HE[last_date.month - 1]})." if last_partial else "")),
        "years_aria": (f"גרף עמודות מוערמות: מספר המדידות בכל שנה בין {y0} ל-{y1} לפי שיטת מדידה. "
                       f"סך הכול {total:,} מדידות."),
        "nitrogen_aria": (f"גרף קווים: חציון שנתי של חנקן כללי, חנקה כחנקן וחנקן קלדל, {y0} עד {y1}."
                          + (f" חנקן כללי ב-{y1}: {fnum(tn_last)} מ״ג לליטר." if tn_last is not None else "")),
        "phos_aria": f"גרף קווים: חציון שנתי של זרחן כללי, זרחן מומס וזרחן חלקיקי, {y0} עד {y1}.",
        "ions_aria": f"גרף קווים: חציון שנתי של כלוריד, סולפט, נתרן ומגנזיום, {y0} עד {y1}.",
        "solids_aria": f"גרף קווים: חציון שנתי של מוצקים מרחפים ועכירות, ואחוזון 90 של המוצקים, {y0} עד {y1}.",
        "season_aria": "גרף קווים: חציון המוצקים המרחפים והעכירות לפי חודש בשנה, בכל שנות המדידה.",
        "temp_aria": ("גרף קווים: טמפרטורת המים לפי חודש, חציון וטווח אחוזונים 10 עד 90."
                      if temp else ""),
        "heat_aria": f"מפת חום: חציון המוצקים המרחפים בכל חודש ושנה, {y0} עד {y1}.",
        "change_aria": ("גרף עמודות: שינוי באחוזים בחציון של כל פרמטר, "
                        + (f"{win_recent} לעומת {win_base} (בשנים שבהן כל פרמטר נמדד)."
                           if change_rows else "")),
        "decade_aria": "תרשים קופסה: התפלגות ריכוז הכלוריד בכל עשור.",
        "params_aria": (f"גרף עמודות: מספר המדידות של {min(TOP_PARAMS, len(pc))} הפרמטרים הנמדדים ביותר. "
                        f"המוביל: {params_rows[0]['name']} עם {params_rows[0]['n']:,} מדידות." if params_rows else ""),
        "change_note": ((f"חציון החציונים השנתיים ב-{RECENT_YEARS} שנות המדידה האחרונות "
                         f"({win_recent}) לעומת {BASE_YEARS} השנים הראשונות ({win_base}), "
                         f"בכל פרמטר רק בשנים שבהן נמדד; השנים של כל פרמטר מופיעות בטבלה. "
                         f"חנקה מוצגת כחנקן (NO3-N) בבסיס אחיד.")
                        if change_rows else ""),
        "temp_note": (f"טמפרטורת המים נמדדה ב-{len(temp_years)} שנים בלבד ({temp_years[0]} עד {temp_years[-1]}), "
                      f"ולכן מוצג המחזור העונתי ולא מגמה." if temp else ""),
        "heat_note": (f"חציון המוצקים המרחפים בכל חודש. סקאלת הצבע נעצרת באחוזון 95 של התאים "
                      f"({fnum(heat['max'])} מ״ג לליטר), כך שחודשי שיטפון קיצוניים מופיעים בגוון הכהה ביותר."
                      if heat else ""),
        "decade_note": ("קופסה: רבעון תחתון עד עליון, קו: חציון, שפמים: אחוזונים 5 ו-95. "
                        "הערך המרבי בכל עשור מופיע בטבלה." if decade else ""),
        "nitrogen_note": ("חנקה (NO3) דווחה בשנים הראשונות כחנקה ובשנים המאוחרות במונחי חנקן. "
                          "הקו המאוחד ממיר את כל השנים לחנקן; הקו המקווקו מציג את הערכים כפי שדווחו."
                          if nitrogen.get("raw") and any(b == "nitrogen" for b in basis.values())
                          and any(b == "nitrate" for b in basis.values())
                          else "חציון שנתי של מדדי החנקן."),
    }

    # ======================================================== agent_data
    summary = (f"איכות מי הירדן בגשר הפקק: {total:,} מדידות של {n_params} פרמטרים מ-{y0} עד {y1}. "
               f"חנקן, זרחן, כלוריד, מוצקים מרחפים ועכירות לפי שנה ועונה.")
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "suggested_tags": ["איכות מים", "נהר הירדן", "ניטור", "חנקן", "זרחן", "כנרת"],
        "related_ids": [
            "db8f9bc9-738a-4d83-b3ce-74e8a5f7f844",
            "83aba0a3-dc03-48a4-87eb-74af55b0cc5e",
            "2706952a-a86d-4887-a6a6-6e42d91cba6c",
            "5de14d12-d5d7-475d-ade1-5dbd0ef9d086",
            "f72117a6-2b71-43e9-bc81-75c284a4d1e2",
        ],
        "temporal_coverage": f"{y0}/{y1}",
        "spatial_coverage": "נהר הירדן, גשר הפקק (גשר חורי)",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": kpi_order,
        "kpi_labels": kpi_labels,
        "insights": insights,
        "labels": labels,
        "charts": {
            "years": years_chart,
            "nitrogen": nitrogen,
            "phos": phos,
            "ions": ions,
            "solids": solids,
            "season": season,
            "temp": temp,
            "heat": heat,
            "change": change_chart,
            "decade": decade,
            "params": params_chart,
        },
        "tables": {
            "change": change_rows,
            "season": [{"month": MONTHS_HE[i],
                        "tss": fnum(season["tss"]["median"][i]) if season["tss"] else "לא נמדד",
                        "turb": fnum(season["turb"]["median"][i]) if season["turb"] else "לא נמדד"}
                       for i in range(12)],
            "temp": ([{"month": MONTHS_HE[i], "median": fnum(temp["median"][i]),
                       "p10": fnum(temp["p10"][i]), "p90": fnum(temp["p90"][i]),
                       "n": temp["n"][i]} for i in range(12)] if temp else []),
            "params": params_rows,
        },
        "flags": {
            "phos": len(phos["series"]) > 0,
            "ions": len(ions["series"]) > 0,
            "solids": len(solids["series"]) > 0,
            "season": season["tss"] is not None,
            "turb_season": season["turb"] is not None,
            "temp": temp is not None,
            "heat": heat is not None and heat["n_cells"] > 0,
            "change": len(change_rows) > 0,
            "decade": decade is not None,
        },
    }
