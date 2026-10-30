"""Spring water-quality measurements (Hydrological Service, Water Authority).

Long format: one row per (spring, sampling date, parameter) with a numeric
result. The page profiles sampling effort over time, salinity (chloride),
nitrate against the drinking-water limit and its long-term change, spring
temperature, the dominant anion (water type), seasonality and labs.
All windows are relative to the latest hydrological year in the data.
"""

from __future__ import annotations

import pandas as pd

ID = "מספר זיהוי"
NAME = "שם עברית"
LAB = "שם מעבדה"
HYEAR = "שנה הידרולוגית"
DATE = "תאריך דגימה"
PARAM = "סמל פרמטר"
RESULT = "תוצאה"
UNIT = "יחידת מדידה"

# Domain constants (not data): Israeli drinking-water nitrate limit (mg/L).
NITRATE_LIMIT = 70
RECENT_YEARS = 10          # recent window, in hydrological years
EARLY_GAP = 35             # early window: hydrological years <= latest - EARLY_GAP
MIN_SAMPLES = 3            # min samples per spring in the recent window for rankings
MIN_PAIR = 2               # min samples per period for the early-vs-recent comparison
CHANGE_TH = 0.20           # +-20% counts as a rise / fall
TOP_N = 15
TOP_PARAMS = 12
MULTI_N = 6
THERMAL_C = 30
SALINE_CL = 1000        # mg/L chloride: clearly brackish spring water

PARAM_HE = {
    "CL": "כלוריד", "NO3": "חנקה", "T": "טמפרטורה", "PHFD": "pH בשדה",
    "EC": "מוליכות חשמלית", "HCO3": "ביקרבונט", "Mg": "מגנזיום", "CA": "סידן",
    "NA": "נתרן", "SO4": "סולפט", "K": "אשלגן", "ECFD": "מוליכות בשדה",
    "DO": "חמצן מומס", "TURB": "עכירות", "BR": "ברומיד", "HARD": "קשיות",
    "ORP": "פוטנציאל חמצון-חיזור", "B": "בורון", "SR": "סטרונציום",
    "F": "פלואוריד", "FE": "ברזל", "MN": "מנגן", "LI": "ליתיום",
    "TOC": "פחמן אורגני כולל", "PO4": "פוספט", "AS": "ארסן",
}
UNIT_HE = {
    "MG/L": "מ״ג/ל", "Celsius": "°C", "mS/cm": "mS/cm", "UNIT": "יחידות pH",
    "microgr/L": "מק״ג/ל", "NTU": "NTU", "mV": "mV",
}
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
# Anion equivalent weights (g/eq) for a meq/L water-type split.
ANION_EQ = {"HCO3": 61.02, "CL": 35.45, "SO4": 48.03}
ANION_HE = {"HCO3": "ביקרבונט", "CL": "כלוריד", "SO4": "סולפט"}
NO3_BANDS = [(0, 10, "פחות מ-10"), (10, 25, "10 עד 25"), (25, 50, "25 עד 50"),
             (50, NITRATE_LIMIT, f"50 עד {NITRATE_LIMIT}"),
             (NITRATE_LIMIT, float("inf"), f"מעל {NITRATE_LIMIT}")]
T_BANDS = [(-1e9, 16, "פחות מ-16"), (16, 18, "16 עד 18"), (18, 20, "18 עד 20"),
           (20, 22, "20 עד 22"), (22, 24, "22 עד 24"), (24, 26, "24 עד 26"),
           (26, 30, "26 עד 30"), (30, 40, "30 עד 40"), (40, 1e9, "40 ומעלה")]


def _i(v) -> str:
    return f"{int(round(v)):,}"


def _n(v, d=1) -> str:
    s = f"{v:,.{d}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _pct(x) -> str:
    return f"{x * 100:.1f}%"


def _hy_label(y: int) -> str:
    return f"{y - 1}/{y}"


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    d = pd.DataFrame({
        "sid": df[ID].astype(str).str.strip(),
        "name": df[NAME].astype(str).str.strip(),
        "lab": df[LAB].astype(str).str.strip(),
        "param": df[PARAM].astype(str).str.strip(),
        "unit": df[UNIT].astype(str).str.strip(),
        "dstr": df[DATE].astype(str).str.strip(),
    })
    d["v"] = pd.to_numeric(df[RESULT].astype(str).str.replace(",", "", regex=False).str.strip(),
                           errors="coerce")
    d["date"] = pd.to_datetime(d["dstr"], format="%d/%m/%Y %H:%M", errors="coerce")
    hy = pd.to_numeric(df[HYEAR].astype(str).str.strip().str[-4:], errors="coerce")
    # Hydrological year runs Oct-Sep, named by its end year.
    from_date = d["date"].dt.year + (d["date"].dt.month >= 10).astype("float")
    d["hy"] = hy.fillna(from_date)
    d = d[d["sid"] != ""]
    d = d[d["hy"].notna()].copy()
    d["hy"] = d["hy"].astype(int)
    d.loc[d["name"] == "", "name"] = d["sid"]
    return d


def _labels_for(d: pd.DataFrame) -> dict:
    names = (d[["sid", "name"]].drop_duplicates()
             .sort_values(["sid", "name"]).drop_duplicates("sid"))
    dup = names["name"].duplicated(keep=False)
    names.loc[dup, "name"] = names.loc[dup, "name"] + " (" + names.loc[dup, "sid"] + ")"
    return dict(zip(names["sid"], names["name"]))


def _spring_stats(sub: pd.DataFrame) -> pd.DataFrame:
    g = sub.groupby("sid")["v"].agg(med="median", cnt="count", mx="max").reset_index()
    return g


def compute(frames):
    raw = frames["main"]
    d = _prep(raw)
    lab_of = _labels_for(d)
    num = d[d["v"].notna()]

    max_hy = int(d["hy"].max())
    min_hy = int(d["hy"].min())
    recent_from = max_hy - RECENT_YEARS + 1
    early_to = max_hy - EARLY_GAP
    recent_lbl = f"{_hy_label(recent_from)} עד {_hy_label(max_hy)}"
    n_rows = len(d)
    n_springs = d["sid"].nunique()
    last_date = d["date"].max()
    first_date = d["date"].min()

    insights = []
    labels = {}
    tables = {}
    charts = {}
    flags = {}

    # ---- 1. Sampling effort per hydrological year -------------------------
    by_y = d.groupby("hy").agg(rows=("v", "size"), springs=("sid", "nunique"))
    years = list(range(min_hy, max_hy + 1))
    by_y = by_y.reindex(years, fill_value=0)
    charts["yearly"] = {
        "x": [_hy_label(y) for y in years],
        "rows": [int(v) for v in by_y["rows"]],
        "springs": [int(v) for v in by_y["springs"]],
    }
    peak_y = int(by_y["rows"].idxmax())
    prev5 = by_y.loc[max(min_hy, max_hy - 5):max_hy - 1, "rows"]
    prev5 = prev5[prev5 > 0]
    latest_rows = int(by_y.loc[max_hy, "rows"])
    partial = bool(len(prev5) >= 3 and latest_rows < 0.5 * float(prev5.median()))
    labels["yearly_aria"] = (
        f"גרף עמודות וקו: מספר המדידות ומספר המעיינות שנדגמו בכל שנה הידרולוגית, "
        f"{_hy_label(min_hy)} עד {_hy_label(max_hy)}. השיא בשנת {_hy_label(peak_y)} "
        f"עם {_i(by_y.loc[peak_y, 'rows'])} מדידות.")
    rec = by_y.loc[recent_from:max_hy]
    labels["yearly_lede"] = (
        f"בעשור האחרון ({recent_lbl}) נדגמו בממוצע {_i(rec['springs'].mean())} מעיינות "
        f"ונרשמו {_i(rec['rows'].mean())} מדידות בשנה. "
        f"בשנת {_hy_label(max_hy)} נדגמו {_i(by_y.loc[max_hy, 'springs'])} מעיינות"
        + (" (השנה נראית חלקית)." if partial else "."))

    top_spring = d.groupby("sid").size().reset_index(name="n").sort_values(
        ["n", "sid"], ascending=[False, True]).iloc[0]
    insights.append({"id": "coverage", "text_he": (
        f"המאגר מכיל {_i(n_rows)} מדידות מ-{_i(n_springs)} מעיינות, מ-{first_date.year} ועד "
        f"{last_date.strftime('%d.%m.%Y')}. המעיין הנדגם ביותר הוא {lab_of[top_spring['sid']]} "
        f"עם {_i(top_spring['n'])} מדידות.")})

    # ---- 2. Parameter mix ------------------------------------------------
    pc = d.groupby("param").agg(n=("v", "size"), unit=("unit", lambda s: s.value_counts().sort_index().idxmax()),
                                springs=("sid", "nunique")).reset_index()
    pc = pc.sort_values(["n", "param"], ascending=[False, True])
    top = pc.head(TOP_PARAMS)
    rest = pc.iloc[TOP_PARAMS:]
    p_rows = [{"name": PARAM_HE.get(r.param, r.param), "code": r.param, "n": int(r.n),
               "springs": int(r.springs), "unit": UNIT_HE.get(r.unit, r.unit)}
              for r in top.itertuples()]
    if len(rest):
        p_rows.append({"name": f"אחר ({_i(len(rest))} פרמטרים)", "code": "", "n": int(rest["n"].sum()),
                       "springs": int(d[d["param"].isin(rest["param"])]["sid"].nunique()), "unit": ""})
    charts["params"] = {"names": [r["name"] for r in p_rows], "values": [r["n"] for r in p_rows]}
    tables["params"] = p_rows
    n_params = len(pc)
    lead = p_rows[0]
    labels["params_aria"] = (
        f"גרף עמודות אופקי: מספר המדידות לפי פרמטר. הפרמטר הנמדד ביותר הוא {lead['name']} "
        f"עם {_i(lead['n'])} מדידות.")
    labels["params_lede"] = (
        f"במאגר {_i(n_params)} פרמטרים שונים. {lead['name']} לבדו מהווה "
        f"{_pct(lead['n'] / n_rows)} מהמדידות; היונים הראשיים, הטמפרטורה וה-pH משלימים את התמונה, "
        f"ומתכות ומזהמים אורגניים נבדקו רק במקרים בודדים.")

    # ---- 3. Chloride (salinity) ranking, recent window -------------------
    cl = num[num["param"] == "CL"]
    cl_r = _spring_stats(cl[cl["hy"] >= recent_from])
    cl_r = cl_r[cl_r["cnt"] >= MIN_SAMPLES].sort_values(["med", "sid"], ascending=[False, True])
    cl_all_med = float(cl[cl["hy"] >= recent_from]["v"].median()) if len(cl) else float("nan")
    flags["chloride"] = len(cl_r) >= 3
    if flags["chloride"]:
        t = cl_r.head(TOP_N)
        rows = [{"name": lab_of[r.sid], "median": float(r.med), "n": int(r.cnt),
                 "median_d": _i(r.med)} for r in t.itertuples()]
        charts["chloride"] = {"names": [r["name"] for r in rows], "values": [r["median"] for r in rows]}
        tables["chloride"] = rows
        labels["chloride_aria"] = (
            f"גרף עמודות אופקי בסולם לוגריתמי: {len(rows)} המעיינות המליחים ביותר לפי חציון הכלוריד "
            f"בשנים {recent_lbl}. בראש: {rows[0]['name']} עם {rows[0]['median_d']} מ״ג/ל.")
        labels["chloride_lede"] = (
            f"חציון ריכוז הכלוריד בכל מעיין בשנים {recent_lbl}, למעיינות עם {MIN_SAMPLES} דגימות "
            f"לפחות ({_i(len(cl_r))} מעיינות). החציון של כל דגימות הכלוריד בתקופה: "
            f"{_i(cl_all_med)} מ״ג/ל. הציר לוגריתמי כי הטווח משתרע על כמה סדרי גודל.")
        ratio = rows[0]["median"] / cl_all_med if cl_all_med else 0
        n_over_1000 = int((cl_r["med"] > SALINE_CL).sum())
        insights.append({"id": "salinity", "text_he": (
            f"המעיין המליח ביותר בעשור האחרון הוא {rows[0]['name']}: חציון כלוריד של "
            f"{rows[0]['median_d']} מ״ג/ל, פי {_n(ratio, 0)} מהחציון הכללי ({_i(cl_all_med)} מ״ג/ל). "
            f"{_i(n_over_1000)} מתוך {_i(len(cl_r))} מעיינות עם {MIN_SAMPLES} דגימות לפחות "
            f"עוברים {_i(SALINE_CL)} מ״ג/ל.")})

    # ---- 4. Nitrate vs the drinking-water limit ---------------------------
    no3 = num[num["param"] == "NO3"]
    no3_r = _spring_stats(no3[no3["hy"] >= recent_from])
    no3_r = no3_r[no3_r["cnt"] >= MIN_SAMPLES].sort_values(["med", "sid"], ascending=[False, True])
    flags["nitrate"] = len(no3_r) >= 3
    over_share = 0.0
    if flags["nitrate"]:
        bands = []
        m = no3_r["med"]
        for lo, hi, lbl in NO3_BANDS:
            # Bands are [lo, hi), except the band ending at the limit includes it
            # and the top band is strictly above the limit.
            if lo >= NITRATE_LIMIT:
                c = int((m > lo).sum())
            elif hi == NITRATE_LIMIT:
                c = int(((m >= lo) & (m <= hi)).sum())
            else:
                c = int(((m >= lo) & (m < hi)).sum())
            bands.append({"label": lbl, "n": c, "over": lo >= NITRATE_LIMIT})
        charts["no3_bands"] = {"names": [b["label"] for b in bands], "values": [b["n"] for b in bands],
                               "over": [b["over"] for b in bands]}
        tables["no3_bands"] = bands
        n_over = int((no3_r["med"] > NITRATE_LIMIT).sum())
        over_share = n_over / len(no3_r)
        t = no3_r.head(TOP_N)
        rows = [{"name": lab_of[r.sid], "median": float(r.med), "max": float(r.mx),
                 "n": int(r.cnt), "median_d": _i(r.med), "max_d": _i(r.mx),
                 "over": bool(r.med > NITRATE_LIMIT)} for r in t.itertuples()]
        charts["no3_top"] = {"names": [r["name"] for r in rows], "values": [r["median"] for r in rows],
                             "over": [r["over"] for r in rows], "limit": NITRATE_LIMIT}
        tables["no3_top"] = rows
        labels["no3_bands_aria"] = (
            f"גרף עמודות: התפלגות {_i(len(no3_r))} מעיינות לפי חציון ריכוז החנקה בשנים {recent_lbl}. "
            f"{_i(n_over)} מעיינות מעל תקן מי השתייה ({NITRATE_LIMIT} מ״ג/ל).")
        labels["no3_top_aria"] = (
            f"גרף עמודות אופקי: {len(rows)} המעיינות עם חציון החנקה הגבוה ביותר בשנים {recent_lbl}, "
            f"עם קו התקן ב-{NITRATE_LIMIT} מ״ג/ל. בראש: {rows[0]['name']} עם {rows[0]['median_d']} מ״ג/ל.")
        labels["no3_lede"] = (
            f"חציון ריכוז החנקה (NO3) בכל מעיין בשנים {recent_lbl}, למעיינות עם {MIN_SAMPLES} דגימות לפחות "
            f"({_i(len(no3_r))} מעיינות), מול תקן מי השתייה בישראל: {NITRATE_LIMIT} מ״ג/ל. "
            f"מים בעלי חנקה גבוהה מעידים בדרך כלל על חלחול דשנים, שפכים או זבל בעלי חיים.")
        if n_over:
            insights.append({"id": "nitrate_limit", "text_he": (
                f"ב-{_i(n_over)} מתוך {_i(len(no3_r))} מעיינות ({_pct(over_share)}) חציון החנקה בשנים "
                f"{recent_lbl} עולה על תקן מי השתייה ({NITRATE_LIMIT} מ״ג/ל). הגבוה ביותר: "
                f"{rows[0]['name']} עם {rows[0]['median_d']} מ״ג/ל.")})
        else:
            insights.append({"id": "nitrate_limit", "text_he": (
                f"באף אחד מ-{_i(len(no3_r))} המעיינות שנדגמו {MIN_SAMPLES} פעמים לפחות בשנים {recent_lbl} "
                f"חציון החנקה אינו עולה על תקן מי השתייה ({NITRATE_LIMIT} מ״ג/ל).")})

    # ---- 5. Nitrate then vs now (dumbbell) --------------------------------
    flags["no3_change"] = False
    n_up = n_down = n_pair = 0
    if len(no3):
        e = _spring_stats(no3[no3["hy"] <= early_to])
        r = _spring_stats(no3[no3["hy"] >= recent_from])
        j = e[e["cnt"] >= MIN_PAIR].merge(r[r["cnt"] >= MIN_PAIR], on="sid", suffixes=("_e", "_r"))
        n_pair = len(j)
        if n_pair >= 5:
            flags["no3_change"] = True
            j["delta"] = j["med_r"] - j["med_e"]
            up = j["med_r"] > j["med_e"] * (1 + CHANGE_TH)
            down = j["med_r"] < j["med_e"] * (1 - CHANGE_TH)
            n_up, n_down = int(up.sum()), int(down.sum())
            js = j.sort_values(["delta", "sid"], ascending=[False, True]).head(TOP_N)
            rows = [{"name": lab_of[x.sid], "early": float(x.med_e), "recent": float(x.med_r),
                     "early_d": _i(x.med_e), "recent_d": _i(x.med_r),
                     "delta_d": ("+" if x.delta >= 0 else "−") + _i(abs(x.delta))} for x in js.itertuples()]
            charts["no3_change"] = {"names": [x["name"] for x in rows], "early": [x["early"] for x in rows],
                                    "recent": [x["recent"] for x in rows], "limit": NITRATE_LIMIT}
            tables["no3_change"] = rows
            early_lbl = f"עד {_hy_label(early_to)}"
            labels["no3_change_early"] = f"חציון {early_lbl}"
            labels["no3_change_recent"] = f"חציון {recent_lbl}"
            med_delta = float(j["delta"].median())
            labels["no3_change_aria"] = (
                f"תרשים משקולות: חציון החנקה {early_lbl} לעומת {recent_lbl}, ב-{len(rows)} המעיינות "
                f"שבהם העלייה הגדולה ביותר. בראש: {rows[0]['name']}, מ-{rows[0]['early_d']} ל-{rows[0]['recent_d']} מ״ג/ל.")
            labels["no3_change_lede"] = (
                f"השוואה בין חציון החנקה בשנים {early_lbl} לחציון בשנים {recent_lbl}, ב-{_i(n_pair)} מעיינות "
                f"שנדגמו {MIN_PAIR} פעמים לפחות בכל תקופה. מוצגים {len(rows)} המעיינות עם העלייה הגדולה ביותר "
                f"(במ״ג/ל). שינוי החציון האופייני: {('+' if med_delta >= 0 else '−')}{_n(abs(med_delta))} מ״ג/ל.")
            if n_up > n_down and n_up / n_pair >= 0.4:
                insights.append({"id": "nitrate_rise", "text_he": (
                    f"החנקה במעיינות עלתה לאורך עשורים: ב-{_i(n_up)} מתוך {_i(n_pair)} מעיינות "
                    f"({_pct(n_up / n_pair)}) החציון בשנים {recent_lbl} גבוה ביותר מ-{_i(CHANGE_TH * 100)}% "
                    f"מהחציון בשנים {early_lbl}, ורק ב-{_i(n_down)} הוא ירד באותו שיעור. "
                    f"העלייה החדה ביותר: {rows[0]['name']} ({rows[0]['early_d']} ל-{rows[0]['recent_d']} מ״ג/ל).")})
            elif n_down > n_up and n_down / n_pair >= 0.4:
                insights.append({"id": "nitrate_rise", "text_he": (
                    f"החנקה במעיינות ירדה לאורך עשורים: ב-{_i(n_down)} מתוך {_i(n_pair)} מעיינות החציון בשנים "
                    f"{recent_lbl} נמוך ביותר מ-{_i(CHANGE_TH * 100)}% מהחציון בשנים {early_lbl}.")})

    # ---- 6. Chloride long-term, most-sampled springs ----------------------
    flags["multi"] = False
    if len(cl):
        yrs = cl.groupby("sid")["hy"].nunique().reset_index(name="ny")
        yrs = yrs[yrs["ny"] >= 10].sort_values(["ny", "sid"], ascending=[False, True]).head(MULTI_N)
        panels = []
        n_rise = 0
        for s in yrs["sid"]:
            ss = cl[cl["sid"] == s].groupby("hy")["v"].median()
            y0, y1 = int(ss.index.min()), int(ss.index.max())
            xs = list(range(y0, y1 + 1))
            ser = ss.reindex(xs)
            first10 = float(ss[ss.index < y0 + 10].median())
            last10 = float(ss[ss.index > y1 - 10].median())
            ch = (last10 - first10) / first10 if first10 else 0.0
            if ch > CHANGE_TH:
                n_rise += 1
            word = "עלייה" if ch > CHANGE_TH else ("ירידה" if ch < -CHANGE_TH else "יציבות יחסית")
            panels.append({
                "id": f"chart-cl-{len(panels) + 1}",
                "name": lab_of[s],
                "x": [str(y) for y in xs],
                "y": [None if pd.isna(v) else float(v) for v in ser],
                "note": (f"{word}: חציון {_i(first10)} מ״ג/ל בעשור הראשון ({y0} עד {y0 + 9}), "
                         f"{_i(last10)} מ״ג/ל בעשור האחרון ({y1 - 9} עד {y1})."),
                "aria": (f"גרף קו: חציון הכלוריד השנתי במעיין {lab_of[s]}, {y0} עד {y1}. "
                         f"{word} מ-{_i(first10)} ל-{_i(last10)} מ״ג/ל."),
            })
        if len(panels) >= 2:
            flags["multi"] = True
            charts["multi"] = panels
            labels["multi_lede"] = (
                f"חציון הכלוריד השנתי ב-{len(panels)} המעיינות עם רצף המדידות הארוך ביותר, כל אחד בסולם משלו "
                f"(השנה לפי השנה ההידרולוגית; שנים ללא דגימה מופיעות כרווח).")
            if n_rise >= 2:
                insights.append({"id": "chloride_trend", "text_he": (
                    f"ב-{_i(n_rise)} מתוך {len(panels)} המעיינות עם הרצף הארוך ביותר חציון הכלוריד בעשור האחרון "
                    f"גבוה ביותר מ-{_i(CHANGE_TH * 100)}% מהעשור הראשון למדידה, סימן להמלחה מתמשכת.")})

    # ---- 7. Temperature --------------------------------------------------
    tt = num[(num["param"] == "T") & (num["v"] > 0)]
    tmed = tt.groupby("sid")["v"].median().reset_index(name="med")
    flags["temp"] = len(tmed) >= 5
    if flags["temp"]:
        bands = []
        for lo, hi, lbl in T_BANDS:
            c = int(((tmed["med"] >= lo) & (tmed["med"] < hi)).sum())
            bands.append({"label": lbl, "n": c, "hot": lo >= THERMAL_C})
        charts["temp"] = {"names": [b["label"] for b in bands], "values": [b["n"] for b in bands],
                          "hot": [b["hot"] for b in bands]}
        tables["temp"] = bands
        hot = tmed.sort_values(["med", "sid"], ascending=[False, True])
        n_hot = int((tmed["med"] >= THERMAL_C).sum())
        mode = max(bands, key=lambda b: b["n"])
        top3 = [f"{lab_of[r.sid]} ({_n(r.med)}°)" for r in hot.head(3).itertuples()]
        labels["temp_aria"] = (
            f"היסטוגרמה: התפלגות {_i(len(tmed))} מעיינות לפי חציון טמפרטורת המים. "
            f"הקבוצה הגדולה: {mode['label']} מעלות, עם {_i(mode['n'])} מעיינות.")
        labels["temp_lede"] = (
            f"חציון הטמפרטורה בכל מעיין לאורך כל שנות המדידה ({_i(len(tmed))} מעיינות; מדידות של 0 מעלות "
            f"ומטה הושמטו). רוב המעיינות נובעים בטמפרטורה קרובה לממוצע השנתי של האוויר; המעיינות החמים "
            f"(מ-{THERMAL_C} מעלות) מסומנים באדום.")
        insights.append({"id": "thermal", "text_he": (
            f"{_i(n_hot)} מעיינות חמים (חציון של {THERMAL_C} מעלות ומעלה). החמים ביותר: "
            + ", ".join(top3) + ". רוב המעיינות נעים סביב "
            f"{_n(float(tmed['med'].median()))} מעלות.")})

    # ---- 8. Water type: dominant anion (meq/L) ---------------------------
    ions = num[num["param"].isin(list(ANION_EQ))]
    flags["anions"] = False
    n_type = {}
    if len(ions):
        pv = ions.pivot_table(index=["sid", "dstr"], columns="param", values="v", aggfunc="first")
        if all(c in pv.columns for c in ANION_EQ):
            pv = pv.dropna(subset=list(ANION_EQ))
            for c, eq in ANION_EQ.items():
                pv[c] = pv[c] / eq
            pv = pv[(pv[list(ANION_EQ)].sum(axis=1)) > 0]
            sm = pv[list(ANION_EQ)].groupby(level="sid").median()
            cnt = pv.groupby(level="sid").size()
            sm = sm[cnt.reindex(sm.index) >= MIN_SAMPLES]
            if len(sm) >= 5:
                flags["anions"] = True
                shares = sm.div(sm.sum(axis=1), axis=0)
                dom = shares.idxmax(axis=1)
                for c in ANION_EQ:
                    n_type[c] = int((dom == c).sum())
                pick = cnt.reindex(sm.index).reset_index(name="n").sort_values(
                    ["n", "sid"], ascending=[False, True]).head(12)["sid"]
                order = list(ANION_EQ)
                rows = []
                for s in pick:
                    sh = shares.loc[s]
                    rows.append({"name": lab_of[s], "shares": [round(float(sh[c]) * 100, 1) for c in order],
                                 "dom": ANION_HE[dom.loc[s]]})
                rows.sort(key=lambda r: (-r["shares"][0], r["name"]))
                charts["anions"] = {"names": [r["name"] for r in rows],
                                    "series": [{"name": ANION_HE[c], "data": [r["shares"][k] for r in rows]}
                                               for k, c in enumerate(order)]}
                tables["anions"] = rows
                tables["anion_types"] = [{"name": ANION_HE[c], "n": n_type[c]} for c in order]
                labels["anions_aria"] = (
                    f"גרף עמודות מוערמות 100%: הרכב האניונים העיקריים ב-{len(rows)} המעיינות שנדגמו הכי הרבה. "
                    f"{_i(n_type['HCO3'])} מתוך {_i(len(sm))} מעיינות הם מטיפוס ביקרבונטי.")
                labels["anions_lede"] = (
                    f"חלקו של כל אניון (ביקרבונט, כלוריד, סולפט) מסך האניונים במילי-אקוויוולנטים, לפי חציון הדגימות "
                    f"שבהן נמדדו שלושתם. מתוך {_i(len(sm))} מעיינות עם {MIN_SAMPLES} דגימות כאלה לפחות: "
                    f"{_i(n_type['HCO3'])} ביקרבונטיים (מים מתוקים טיפוסיים של אקוויפר גיר ודולומיט), "
                    f"{_i(n_type['CL'])} כלורידיים (מים מליחים) ו-{_i(n_type['SO4'])} סולפטיים.")
                tot = len(sm)
                insights.append({"id": "water_type", "text_he": (
                    f"לפי הרכב האניונים, {_i(n_type['HCO3'])} מתוך {_i(tot)} מעיינות ({_pct(n_type['HCO3'] / tot)}) "
                    f"הם מטיפוס ביקרבונטי ו-{_i(n_type['CL'])} ({_pct(n_type['CL'] / tot)}) מטיפוס כלורידי, "
                    f"שבו הכלוריד הוא היון השולט.")})

    # ---- 9. Seasonality of sampling --------------------------------------
    ev = d.drop_duplicates(["sid", "dstr"])
    ev = ev[ev["date"].notna()]
    mc = ev["date"].dt.month.value_counts().reindex(range(1, 13), fill_value=0)
    charts["months"] = {"names": MONTHS_HE, "values": [int(v) for v in mc]}
    tables["months"] = [{"name": MONTHS_HE[m - 1], "n": int(mc[m])} for m in range(1, 13)]
    top2 = mc.sort_values(ascending=False, kind="mergesort").head(2)
    share2 = float(top2.sum()) / float(mc.sum()) if mc.sum() else 0.0
    m1, m2 = MONTHS_HE[int(top2.index[0]) - 1], MONTHS_HE[int(top2.index[1]) - 1]
    labels["months_aria"] = (
        f"גרף עמודות: מספר אירועי הדיגום לפי חודש בשנה. {m1} ו{m2} מרכזים {_pct(share2)} מהדיגומים.")
    labels["months_lede"] = (
        f"אירוע דיגום הוא ביקור במעיין בתאריך אחד ({_i(len(ev))} אירועים בסך הכול). {m1} ו{m2} מרכזים "
        f"{_pct(share2)} מהם.")
    if share2 >= 0.4:
        insights.append({"id": "season", "text_he": (
            f"הדיגום מרוכז בשני מסעות בשנה: {m1} ו{m2} מרכזים {_pct(share2)} מ-{_i(len(ev))} אירועי הדיגום, "
            f"כך שרוב הנתונים משקפים את מצב המעיינות בשני המועדים האלה.")})

    # ---- 10. Labs ---------------------------------------------------------
    lc = d.groupby("lab").size().reset_index(name="n").sort_values(["n", "lab"], ascending=[False, True])
    lc["lab"] = lc["lab"].replace("", "לא צוין")
    charts["labs"] = {"names": lc["lab"].tolist(), "values": [int(v) for v in lc["n"]]}
    tables["labs"] = [{"name": r.lab, "n": int(r.n), "share": _pct(r.n / n_rows)} for r in lc.itertuples()]
    labels["labs_aria"] = (
        f"גרף טבעת: חלוקת המדידות לפי מעבדה. {lc.iloc[0]['lab']} ביצעה {_pct(lc.iloc[0]['n'] / n_rows)} מהמדידות.")

    # ---- KPIs -----------------------------------------------------------
    kpis = {
        "rows": {"value": n_rows, "display": _i(n_rows), "tone": "brand"},
        "springs": {"value": n_springs, "display": _i(n_springs), "tone": "brand"},
        "span": {"value": f"{first_date.year}-{last_date.year}",
                 "display": f"{first_date.year}–{last_date.year}", "tone": "brand"},
        "latest": {"value": int(by_y.loc[max_hy, "springs"]),
                   "display": _i(by_y.loc[max_hy, "springs"]), "tone": "warn" if partial else "info"},
    }
    kpi_labels = {
        "rows": "מדידות במאגר",
        "springs": "מעיינות שנדגמו",
        "span": "טווח שנות המדידה",
        "latest": f"מעיינות שנדגמו בשנה ההידרולוגית {_hy_label(max_hy)}" + (" (חלקית)" if partial else ""),
    }
    order = ["rows", "springs", "span", "latest"]
    if flags["nitrate"]:
        tone = "danger" if over_share >= 0.1 else ("warn" if over_share > 0 else "ok")
        kpis["no3_over"] = {"value": round(over_share * 100, 1), "display": _pct(over_share), "tone": tone}
        kpi_labels["no3_over"] = f"מעיינות מעל תקן החנקה ({NITRATE_LIMIT} מ״ג/ל), {recent_lbl}"
        order.append("no3_over")
    if flags["no3_change"]:
        sh = n_up / n_pair
        kpis["no3_up"] = {"value": round(sh * 100, 1), "display": _pct(sh),
                          "tone": "warn" if sh >= 0.5 else "brand"}
        kpi_labels["no3_up"] = f"מעיינות שבהם החנקה עלתה ביותר מ-{_i(CHANGE_TH * 100)}% מאז {_hy_label(early_to)}"
        order.append("no3_up")

    span_he = f"{first_date.year} עד {last_date.year}"
    summary = (f"איכות מים ב-{_i(n_springs)} מעיינות בישראל: כלוריד, חנקה, טמפרטורה ויונים ראשיים. "
               f"{_i(n_rows)} מדידות של השירות ההידרולוגי, {span_he}.")
    if len(summary) > 155:
        summary = f"איכות מים ב-{_i(n_springs)} מעיינות בישראל: {_i(n_rows)} מדידות, {span_he}."

    labels["lede"] = (
        f"השירות ההידרולוגי של רשות המים דוגם מעיינות ברחבי הארץ ובודק בהם מליחות (כלוריד), חנקה, "
        f"טמפרטורה, מוליכות, pH ויונים ראשיים. המאגר כולל {_i(n_rows)} תוצאות מעבדה ושדה מ-{_i(n_springs)} "
        f"מעיינות, מ-{first_date.year} ועד {last_date.strftime('%d.%m.%Y')}. בעמוד: מגמות הדיגום, המעיינות "
        f"המליחים ביותר, חנקה מול תקן מי השתייה והשינוי בה לאורך עשורים, טמפרטורה, טיפוס המים ועונתיות הדיגום.")
    labels["nitrate_limit"] = f"{NITRATE_LIMIT}"

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["איכות מים", "מעיינות", "חנקה", "מליחות", "הידרולוגיה", "רשות המים"],
            "related_ids": [
                "a53613b2-f5da-48d1-86d8-1a8094c568af",
                "25862093-583b-43c4-b637-531645cf3955",
                "9b0286dd-aaa4-4dc6-9878-9c65abbee66e",
                "db8f9bc9-738a-4d83-b3ce-74e8a5f7f844",
                "2b2882aa-5258-4ef4-bcb2-9747dbb62890",
            ],
            "temporal_coverage": f"{first_date.year}/{last_date.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_labels": kpi_labels,
        "kpi_order": order,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
    }
