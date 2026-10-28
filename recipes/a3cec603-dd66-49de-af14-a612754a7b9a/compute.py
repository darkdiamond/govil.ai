"""מבנים ירוקים — buildings certified (or in certification) under Israeli green
building standard SI 5281, as reported by the approved testing labs.

One row per *designation* (a use within a building: residential, education,
offices ...); buildings and projects repeat across rows. Each row carries the
highest certification stage reached (התקשרות → שלב מקדמי → שלב א → שלב ב) and
up to three certificates — preliminary (pre), stage A (design) and stage B
(as-built) — each with a date, score, star rating and energy rating.

"Now" is the latest update date in the file (its data vintage), never the
clock; that year is partial unless it reaches late December. Certificate dates
before MIN_YEAR (placeholder dates such as 1999) or after the vintage are not
charted, and the page says how many. Scores outside (0, 100] and residential
unit counts above UNITS_MAX are treated as entry errors and disclosed.

Locations are buildings, not people: the map shows municipality, street and
use. No contact details exist in the data.
"""
import math

import pandas as pd

TOP_MUNIS = 15
TOP_UNITS = 12
MIN_YEAR = 2005
UNITS_MAX = 2000          # residential units per designation above this = entry error
MIN_PAIRS = 50            # designations with both certificates needed for a pre→B rule
MIN_LAG = 50
NO_STAGE = "ללא שלב"
UNKNOWN = "לא צוין"
OTHER = "אחר"
STAGES = ["התקשרות", "שלב מקדמי", "שלב א", "שלב ב"]
CERTS = [("pre", "תעודה מקדמית"), ("a", "תעודת שלב א"), ("b", "תעודת שלב ב")]
GRADES = ["A+", "A", "B", "C", "D", "E", "F"]
SCORE_EDGES = [50 + 2.5 * i for i in range(13)]  # 50 … 80
LAG_BUCKETS = [(0, 6), (6, 12), (12, 18), (18, 24), (24, 36), (36, 48), (48, None)]
FLOOR_BUCKETS = [(0, 4), (5, 8), (9, 12), (13, 20), (21, 30), (31, None)]
RESIDENTIAL = "מגורים"
MIN_USE = 20              # uses with fewer records are grouped into "אחר" in the mix chart
# Ordinal colour ramp (light → dark) drawn from GOVIL_PALETTE members.
RAMP = ["#b7d2f7", "#6c9fd8", "#0068f5", "#0053c4", "#0b3668", "#0c1f3d"]
NO_STAGE_COLOR = "#c3cfe7"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def n(v):
    return f"{int(v):,}"


def pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def stars_label(s):
    s = int(s)
    if s == 0:
        return "ללא כוכב"
    if s == 1:
        return "כוכב אחד"
    return f"{s} כוכבים"


def iso(label):
    """Wrap a numeric range label in LTR isolates so the RTL canvas keeps "0–6" order."""
    return f"\u2066{label}\u2069"


def ramp(k):
    if k <= 0:
        return []
    if k == 1:
        return [RAMP[2]]
    return [RAMP[round(i * (len(RAMP) - 1) / (k - 1))] for i in range(k)]


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _ordered(present, known):
    """Known codes in their natural order, then any new ones (sorted)."""
    present = set(present)
    return [k for k in known if k in present] + sorted(present - set(known))


def _date(s):
    return pd.to_datetime(s.str.strip(), errors="coerce", format="%d/%m/%Y")


def _prepare(df):
    out = pd.DataFrame({
        "project": df["project_id"].str.strip(),
        "building": df["building_id"].str.strip(),
        "bcount": pd.to_numeric(df["building_count"], errors="coerce"),
        "stage": df["certification_status"].str.strip().replace("", NO_STAGE),
        "final": df["designation_info_status"].str.strip(),
        "muni": df["municipality_name"].str.strip(),
        "use": df["main_use_name"].str.strip().replace("", UNKNOWN),
        "route": df["route"].str.strip().replace("", UNKNOWN),
        "edition": df["standard_name"].str.strip().replace("", UNKNOWN),
        "floors": pd.to_numeric(df["floors_above_ground"], errors="coerce"),
        "units_raw": pd.to_numeric(df["residential_units"], errors="coerce"),
    })
    out.loc[out["muni"].isin(["", "none"]), "muni"] = UNKNOWN
    out.loc[out["floors"] < 0, "floors"] = float("nan")
    ok_units = out["units_raw"].between(0, UNITS_MAX)
    out["units"] = out["units_raw"].where(ok_units)
    out["units_bad"] = out["units_raw"].notna() & ~ok_units
    for s, _ in CERTS:
        out[f"date_{s}"] = _date(df[f"certificate_date_{s}"])
        sc = pd.to_numeric(df[f"certificate_score_{s}"], errors="coerce")
        out[f"score_{s}"] = sc.where((sc > 0) & (sc <= 100))
        st = pd.to_numeric(df[f"certificate_stars_{s}"], errors="coerce")
        out[f"stars_{s}"] = st.where(st.between(0, 5) & (st == st.round()))
        out[f"energy_{s}"] = df[f"certificate_energy_{s}"].str.strip().str.upper()
        out[f"has_{s}"] = df[f"certificate_date_{s}"].str.strip() != ""
    vintage = pd.concat([_date(df[c]) for c in
                         ("designation_info_last_update", "building_info_last_update",
                          "project_general_last_update")])
    return out, vintage.max()


def _bucket(series, buckets, fmt):
    rows = []
    for lo, hi in buckets:
        m = series >= lo
        if hi is not None:
            m &= series < hi if fmt == "lag" else series <= hi
        rows.append(int(m.sum()))
    return rows


def _bucket_labels(buckets, unit):
    return [f"{lo}+{unit}" if hi is None else f"{lo}–{hi}{unit}" for lo, hi in buckets]


# ---------------------------------------------------------------- insights

def insight_munis(munis, total):
    known = munis.drop(UNKNOWN, errors="ignore")
    if known.empty:
        return None
    name, v = known.index[0], int(known.iloc[0])
    if v / total < 0.10:
        return None
    rest = known.iloc[1:3]
    tail = ""
    if len(rest) == 2:
        tail = (f", ואחריה {rest.index[0]} ({n(rest.iloc[0])}) ו{rest.index[1]} "
                f"({n(rest.iloc[1])})")
    return (f"הבנייה הירוקה מרוכזת: {name} לבדה אחראית ל-{pct(v / total)} מהרשומות "
            f"({n(v)}){tail}.")


def insight_use(uses, total, units_total, units_bad):
    name, v = uses.index[0], int(uses.iloc[0])
    if v / total < 0.5:
        return None
    s = f"{pct(v / total)} מהרשומות הן בשימוש {name}"
    if name == RESIDENTIAL and units_total > 0:
        s += f", ובהן {n(units_total)} יחידות דיור"
        if units_bad:
            s += f" (ללא {n(units_bad)} רשומות עם מספר יחידות חריג)"
    return s + "."


def insight_trend(per_year, b_year, last_full):
    if last_full not in per_year.index or (last_full - 1) not in per_year.index:
        return None
    v1, v0 = int(per_year[last_full]), int(per_year[last_full - 1])
    if v0 == 0:
        return None
    chg = v1 / v0 - 1
    rec = ""
    window = per_year[per_year.index <= last_full]
    if len(window) >= 5 and int(window.idxmax()) == last_full:
        rec = " — שנת שיא"
    if abs(chg) < 0.05:
        s = (f"ב-{last_full} הונפקו {n(v1)} תעודות (בכל השלבים), בדומה ל-{last_full - 1} "
             f"({n(v0)}){rec}")
    else:
        word = "עלייה" if chg > 0 else "ירידה"
        s = (f"ב-{last_full} הונפקו {n(v1)} תעודות (בכל השלבים) — {word} של "
             f"{pct(abs(chg))} לעומת {last_full - 1} ({n(v0)}){rec}")
    b1, b0 = int(b_year.get(last_full, 0)), int(b_year.get(last_full - 1, 0))
    if b0 >= 20:
        bc = b1 / b0 - 1
        if abs(bc) < 0.05:
            s += f"; תעודות שלב ב (גמר) לבדן נותרו יציבות ({n(b1)})"
        else:
            s += (f"; תעודות שלב ב (גמר) לבדן {'עלו' if bc > 0 else 'ירדו'} ב-{pct(abs(bc))} "
                  f"ל-{n(b1)}")
    return s + "."


def insight_score(delta):
    if len(delta) < MIN_PAIRS:
        return None
    down = (delta < 0).mean()
    up = (delta > 0).mean()
    if abs(down - up) < 0.10:
        return None
    lo, hi = ("נמוך", "גבוה") if down > up else ("גבוה", "נמוך")
    big, small = (down, up) if down > up else (up, down)
    return (f"בהשוואת ציוני אותם מבנים ({n(len(delta))} עם תעודה מקדמית ותעודת שלב ב): "
            f"ב-{pct(big)} הציון בשלב ב {lo} מהציון המקדמי, ורק ב-{pct(small)} הוא {hi} ממנו.")


def insight_stars(stars_b):
    s = stars_b.dropna()
    if len(s) < MIN_PAIRS:
        return None
    vc = s.value_counts()
    top = vc.sort_index().sort_values(ascending=False, kind="stable")
    lvl, share = top.index[0], top.iloc[0] / len(s)
    if share < 0.5:
        return None
    hi = (s >= 3).mean()
    return (f"דירוג הכוכבים בגמר מרוכז ברמה אחת: {pct(share)} מתעודות שלב ב הן ברמת "
            f"{stars_label(lvl)}, ורק {pct(hi)} זכו לשלושה כוכבים ומעלה.")


def insight_energy(pairs):
    if len(pairs) < MIN_PAIRS:
        return None
    up = int((pairs["d"] < 0).sum())     # lower index = better grade
    same = int((pairs["d"] == 0).sum())
    down = int((pairs["d"] > 0).sum())
    k = len(pairs)
    if up > down:
        lead = f"דירוג האנרגיה משתפר לרוב בין התכנון לביצוע: ב-{pct(up / k)} מהמבנים"
        lead += " הדירוג בתעודת שלב ב גבוה מזה שבתעודה המקדמית"
    elif down > up:
        lead = f"דירוג האנרגיה נשחק לרוב בין התכנון לביצוע: ב-{pct(down / k)} מהמבנים"
        lead += " הדירוג בתעודת שלב ב נמוך מזה שבתעודה המקדמית"
    else:
        return None
    return (f"{lead}, ב-{pct(same / k)} הוא זהה וב-{pct((down if up > down else up) / k)} "
            f"{'ירד' if up > down else 'עלה'} (מתוך {n(k)} מבנים שיש להם את שתי התעודות).")


def insight_lag(lag):
    if len(lag) < MIN_LAG:
        return None
    med = float(lag.median())
    long_share = (lag >= 36).mean()
    return (f"בין תעודת שלב א (תכנון) לתעודת שלב ב (גמר) עוברים בחציון {med:.0f} חודשים; "
            f"ב-{pct(long_share)} מהמבנים — שלוש שנים ויותר (מתוך {n(len(lag))} מבנים עם "
            f"שתי התעודות).")


def insight_final(df):
    fin = int((df["final"] == "פורסם סופי").sum())
    total = len(df)
    if total == 0 or fin == 0:
        return None
    b = int((df["stage"] == "שלב ב").sum())
    return (f"רק {n(fin)} רשומות ({pct(fin / total)}) מסומנות \"פורסם סופי\"; "
            f"השאר מסומנות \"לא סופי\", וגם מבין {n(b)} הרשומות בשלב ב רק "
            f"{pct(fin / b if b else 0)} סומנו כסופיות.")


def insight_projects(proj_size):
    if proj_size.empty:
        return None
    multi = (proj_size > 1).mean()
    if multi < 0.1:
        return None
    big = int(proj_size.max())
    return (f"{pct(multi)} מהפרויקטים כוללים יותר ממבנה אחד, והגדול שבהם מונה {n(big)} מבנים.")


def insight_edition(df):
    """Share of stage-B certificates issued under an edition other than the
    one that dominates the whole file (older editions still finishing)."""
    b = df[df["stage"] == "שלב ב"]
    early = df[df["stage"] != "שלב ב"]
    if len(b) < MIN_PAIRS or early.empty:
        return None
    main = _ranked(df.loc[df["edition"] != UNKNOWN, "edition"])
    if main.empty:
        return None
    cur = main.index[0]
    other_b = (b["edition"] != cur).mean()
    other_e = (early["edition"] != cur).mean()
    if other_b < 0.05 or other_e > other_b / 2:
        return None
    return (f"{pct(other_b)} מתעודות שלב ב ניתנו לפי מהדורות אחרות של התקן, לעומת "
            f"{pct(other_e)} בלבד מהרשומות בשלבים המוקדמים — רוב המבנים שבתהליך נבדקים "
            f"לפי מהדורת {cur}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df, ref = _prepare(frames["main"])
    total = len(df)
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = ref_year - 1 if partial else ref_year

    projects = df["project"].nunique()
    buildings = df["building"].nunique()
    units_total = int(math.fsum(df["units"].dropna().tolist()))
    units_bad = int(df["units_bad"].sum())

    # --- stages (funnel)
    stage_order = _ordered(df["stage"].unique(), STAGES + [NO_STAGE])
    if NO_STAGE in stage_order:
        stage_order = [s for s in stage_order if s != NO_STAGE] + [NO_STAGE]
    known_st = [x for x in stage_order if x != NO_STAGE]
    stage_colors = dict(zip(known_st, ramp(len(known_st))))
    stage_colors[NO_STAGE] = NO_STAGE_COLOR
    stage_counts = df["stage"].value_counts()
    stage_vals = [int(stage_counts.get(s, 0)) for s in stage_order]

    # --- certificates per year
    years_data = {}
    excluded_dates = 0
    for s, _ in CERTS:
        d = df.loc[df[f"has_{s}"], f"date_{s}"]
        ok = d.notna() & (d.dt.year >= MIN_YEAR) & (d <= ref)
        excluded_dates += int((~ok).sum())
        years_data[s] = d[ok].dt.year.astype(int).value_counts()
    all_years = sorted(set().union(*[set(v.index) for v in years_data.values()]))
    years = list(range(all_years[0], ref_year + 1)) if all_years else []
    per_year = pd.Series({y: int(sum(years_data[s].get(y, 0) for s, _ in CERTS)) for y in years},
                         dtype="int64")
    year_labels = [f"{y} (חלקית)" if (partial and y == ref_year) else str(y) for y in years]

    # --- stars & energy per certificate
    star_levels = sorted({int(v) for s, _ in CERTS for v in df[f"stars_{s}"].dropna()})
    grades = _ordered({g for s, _ in CERTS for g in df[f"energy_{s}"] if g}, GRADES)
    stars_rows, energy_rows = [], []
    for s, label in CERTS:
        st = df[f"stars_{s}"].dropna()
        stars_rows.append({"cert": label, "n": len(st),
                           "counts": [int((st == lv).sum()) for lv in star_levels]})
        en = df.loc[df[f"energy_{s}"] != "", f"energy_{s}"]
        energy_rows.append({"cert": label, "n": len(en),
                            "counts": [int((en == g).sum()) for g in grades]})

    def shares(rows):
        return [{"name": r["cert"],
                 "data": [round(c / r["n"] * 100, 1) if r["n"] else 0 for c in r["counts"]]}
                for r in rows]

    # --- scores histogram
    score_labels = (["פחות מ-50"]
                    + [f"{SCORE_EDGES[i]:g}–{SCORE_EDGES[i + 1]:g}" for i in range(len(SCORE_EDGES) - 1)]
                    + [f"{SCORE_EDGES[-1]:g}+"])
    score_rows = []
    zero_scores = 0
    for s, label in CERTS:
        raw = df.loc[df[f"has_{s}"], f"score_{s}"]
        zero_scores += int(raw.isna().sum())
        sc = raw.dropna()
        counts = [int((sc < SCORE_EDGES[0]).sum())]
        for i in range(len(SCORE_EDGES) - 1):
            counts.append(int(((sc >= SCORE_EDGES[i]) & (sc < SCORE_EDGES[i + 1])).sum()))
        counts.append(int((sc >= SCORE_EDGES[-1]).sum()))
        score_rows.append({"cert": label, "n": len(sc), "counts": counts,
                           "median": float(sc.median()) if len(sc) else None})

    # --- pre → B transitions (energy grade and stars); axes = levels seen in the pairs
    both_e = df[(df["energy_pre"] != "") & (df["energy_b"] != "")]
    e_y = [g for g in grades if (both_e["energy_pre"] == g).any()]
    e_x = [g for g in grades if (both_e["energy_b"] == g).any()]
    gi = {g: i for i, g in enumerate(grades)}
    e_pairs = pd.DataFrame({"p": both_e["energy_pre"].map(gi), "b": both_e["energy_b"].map(gi)})
    e_pairs["d"] = e_pairs["b"] - e_pairs["p"]
    e_ct = both_e.groupby(["energy_pre", "energy_b"]).size()
    e_cells = [[xi, yi, int(e_ct.get((yv, xv), 0))]
               for yi, yv in enumerate(e_y) for xi, xv in enumerate(e_x)]
    both_s = df[df["stars_pre"].notna() & df["stars_b"].notna()]
    s_y = sorted({int(v) for v in both_s["stars_pre"]})
    s_x = sorted({int(v) for v in both_s["stars_b"]})
    s_ct = both_s.groupby(["stars_pre", "stars_b"]).size()
    s_cells = [[xi, yi, int(s_ct.get((float(yv), float(xv)), 0))]
               for yi, yv in enumerate(s_y) for xi, xv in enumerate(s_x)]
    s_same = int((both_s["stars_b"] == both_s["stars_pre"]).sum())
    both_sc = df[df["score_pre"].notna() & df["score_b"].notna()]
    sc_delta = both_sc["score_b"] - both_sc["score_pre"]

    # --- lag A → B
    lag = ((df["date_b"] - df["date_a"]).dt.days / 30.4375)
    lag_all = lag.dropna()
    lag_neg = int((lag_all < 0).sum())
    lag = lag_all[lag_all >= 0]
    lag_vals = _bucket(lag, LAG_BUCKETS, "lag")

    # --- municipalities
    munis = _ranked(df["muni"])
    top_m = [m for m in munis.index if m != UNKNOWN][:TOP_MUNIS]
    muni_names = top_m + [OTHER]
    rest_mask = ~df["muni"].isin(top_m)
    by_ms = df.groupby(["muni", "stage"]).size()
    muni_series = []
    for st in stage_order:
        vals = [int(by_ms.get((m, st), 0)) for m in top_m]
        vals.append(int((rest_mask & (df["stage"] == st)).sum()))
        muni_series.append({"name": st, "color": stage_colors[st], "data": vals})
    muni_totals = [int(munis[m]) for m in top_m] + [int(rest_mask.sum())]

    # --- residential units by municipality
    u = df[df["units"].notna() & (df["muni"] != UNKNOWN)].groupby("muni")["units"].sum()
    u = u.sort_index().sort_values(ascending=False, kind="stable").head(TOP_UNITS)
    rec_by_muni = df.groupby("muni").size()

    # --- uses × stage, routes
    uses = _ranked(df["use"])
    use_main = [x for x in uses.index if uses[x] >= MIN_USE and x != UNKNOWN]
    use_small = [x for x in uses.index if x not in use_main]
    use_key = df["use"].where(df["use"].isin(use_main), OTHER)
    use_names = use_main + ([OTHER] if use_small else [])
    use_tot = use_key.value_counts()
    by_us = df.groupby([use_key, "stage"]).size()
    use_counts = {st: [int(by_us.get((x, st), 0)) for x in use_names] for st in stage_order}
    use_series = [{"name": st, "color": stage_colors[st],
                   "data": [round(c / use_tot[x] * 100, 1) for c, x in zip(use_counts[st], use_names)]}
                  for st in stage_order]
    b_share_use = {x: (by_us.get((x, "שלב ב"), 0) / use_tot[x]) for x in use_main}
    routes = _ranked(df["route"])

    # --- floors (residential vs other)
    fl = df[df["floors"].notna()]
    res = fl["use"] == RESIDENTIAL
    floor_labels = _bucket_labels(FLOOR_BUCKETS, "")
    floor_res = _bucket(fl.loc[res, "floors"], FLOOR_BUCKETS, "floors")
    floor_oth = _bucket(fl.loc[~res, "floors"], FLOOR_BUCKETS, "floors")
    res_fl = fl.loc[res, "floors"]
    tall_share = (res_fl > 20).mean() if len(res_fl) else 0
    med_floors = float(res_fl.median()) if len(res_fl) else 0

    # --- projects
    proj_size = df.dropna(subset=["bcount"]).groupby("project")["bcount"].max()

    # --- insights
    rules = [
        ("munis", insight_munis(munis, total)),
        ("use", insight_use(uses, total, units_total, units_bad)),
        ("trend", insight_trend(per_year, years_data["b"], last_full)),
        ("score", insight_score(sc_delta)),
        ("stars", insight_stars(df["stars_b"])),
        ("energy", insight_energy(e_pairs)),
        ("lag", insight_lag(lag)),
        ("final", insight_final(df)),
        ("edition", insight_edition(df)),
        ("projects", insight_projects(proj_size)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # --- KPIs
    b_year = years_data["b"]
    b1, b0 = int(b_year.get(last_full, 0)), int(b_year.get(last_full - 1, 0))
    if b0 and b1 / b0 - 1 >= 0.05:
        b_tone = "ok"
    elif b0 and b1 / b0 - 1 <= -0.05:
        b_tone = "warn"
    else:
        b_tone = "info"
    if b0:
        chg = round((b1 / b0 - 1) * 100)
        b_chg = ("ללא שינוי" if chg == 0
                 else f"{'עלייה' if chg > 0 else 'ירידה'} של {abs(chg)}%") + f" לעומת {last_full - 1}"
    else:
        b_chg = ""
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "projects": {"value": int(projects), "display": n(projects), "tone": "brand"},
        "units": {"value": units_total, "display": n(units_total), "tone": "brand"},
        "b_year": {"value": b1, "display": n(b1), "tone": b_tone},
    }

    stage_b = int(stage_counts.get("שלב ב", 0))
    early = int(stage_counts.get("התקשרות", 0)) + int(stage_counts.get("שלב מקדמי", 0))
    top_year = int(per_year.idxmax()) if len(per_year) else None
    b_med = score_rows[2]["median"]
    pre_med = score_rows[0]["median"]
    top_use_b = max(((x, v) for x, v in b_share_use.items() if uses[x] >= 50),
                    key=lambda t: (t[1], t[0]), default=None)
    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    stage_b_share = stage_b / total if total else 0

    labels = {
        "lede": (f"מאגר המבנים הנבנים לפי תקן הבנייה הירוקה, כפי שדיווחו המעבדות המאושרות: "
                 f"{n(total)} רשומות שימוש ב-{n(buildings)} מבנים ו-{n(projects)} פרויקטים "
                 f"ב-{n(df.loc[df['muni'] != UNKNOWN, 'muni'].nunique())} רשויות. "
                 f"{pct(stage_b_share)} מהרשומות כבר הגיעו לשלב ב (גמר). "
                 f"עדכון אחרון במאגר: {d_he(ref)}."),
        "b_year_kpi": f"תעודות שלב ב שהונפקו ב-{last_full}" + (f" ({b_chg})" if b_chg else ""),
        "stages_note": (f"השלב הגבוה ביותר שאליו הגיעה כל רשומה. {pct(early / total if total else 0)} "
                        f"מהרשומות עדיין בהתקשרות או בשלב המקדמי, ו-{pct(stage_b_share)} השלימו "
                        f"את שלב ב."),
        "stages_aria": (f"תרשים עמודות: רשומות לפי שלב ההתעדה; {n(stage_b)} רשומות בשלב ב "
                        f"מתוך {n(total)}."),
        "stages_caption": "מספר רשומות לפי שלב ההתעדה.",
        "years_note": (f"מספר התעודות שהונפקו בכל שנה, לפי סוג התעודה ותאריך הנפקתה."
                       + (f" שנת השיא: {top_year}." if top_year else "")
                       + (f" {n(excluded_dates)} תאריכים לפני {MIN_YEAR} או אחרי מועד העדכון "
                          f"(שגויים) אינם מוצגים." if excluded_dates else "")
                       + partial_note),
        "years_aria": (f"גרף עמודות: תעודות לפי שנה וסוג תעודה, {years[0] if years else ''} "
                       f"עד {ref_year}."),
        "years_caption": "מספר תעודות לפי שנת הנפקה וסוג תעודה.",
        "stars_note": (f"שיעור התעודות בכל רמת דירוג כוכבים, לפי סוג התעודה. "
                       f"בתעודות שלב ב: {n(stars_rows[2]['n'])} תעודות עם דירוג."),
        "stars_aria": "תרשים עמודות מוערמות: התפלגות דירוג הכוכבים בכל סוג תעודה, באחוזים.",
        "stars_caption": "מספר תעודות לפי סוג תעודה ודירוג כוכבים.",
        "energy_note": (f"דירוג האנרגיה של המבנה כפי שנקבע בכל תעודה ({iso('A+')} הגבוה ביותר). "
                        f"בתעודות שלב ב: {n(energy_rows[2]['n'])} תעודות עם דירוג."),
        "energy_aria": "תרשים עמודות מוערמות: התפלגות דירוג האנרגיה בכל סוג תעודה, באחוזים.",
        "energy_caption": "מספר תעודות לפי סוג תעודה ודירוג אנרגיה.",
        "scores_note": ("שיעור התעודות בכל טווח ציון (נקודות), לפי סוג התעודה."
                        + (f" ציון חציוני: {pre_med:g} בתעודה המקדמית, {b_med:g} בשלב ב."
                           if pre_med is not None and b_med is not None else "")
                        + (f" {n(zero_scores)} תעודות עם ציון 0, חסר או מעל 100 אינן נכללות."
                           if zero_scores else "")),
        "scores_aria": "גרף קווים: התפלגות ציוני התעודות לפי טווח ציון וסוג תעודה, באחוזים.",
        "scores_caption": "מספר תעודות לפי טווח ציון וסוג תעודה.",
        "etrans_note": (f"מבנים שיש להם גם תעודה מקדמית וגם תעודת שלב ב ({n(len(e_pairs))}): "
                        f"הדירוג בתכנון (שורות) מול הדירוג בגמר (עמודות, למעלה)."),
        "etrans_aria": (f"מפת חום: דירוג אנרגיה בתעודה המקדמית מול דירוג בתעודת שלב ב, "
                        f"{n(len(e_pairs))} מבנים."),
        "etrans_caption": "מספר מבנים לפי דירוג אנרגיה מקדמי (שורות) ודירוג בשלב ב (עמודות).",
        "strans_note": (f"מספר הכוכבים בתעודה המקדמית (שורות) מול שלב ב (עמודות), ב-{n(len(both_s))} "
                        f"מבנים עם שתי התעודות; "
                        f"ב-{pct(s_same / len(both_s) if len(both_s) else 0)} מהם הדירוג לא השתנה."),
        "strans_aria": (f"מפת חום: דירוג כוכבים בתעודה המקדמית מול דירוג בתעודת שלב ב, "
                        f"{n(len(both_s))} מבנים."),
        "strans_caption": "מספר מבנים לפי דירוג כוכבים מקדמי (שורות) ודירוג בשלב ב (עמודות).",
        "lag_note": (f"הזמן בחודשים בין תאריך תעודת שלב א לתאריך תעודת שלב ב, ב-{n(len(lag))} "
                     f"מבנים שיש להם את שתיהן."
                     + (f" חציון: {float(lag.median()):.0f} חודשים." if len(lag) else "")
                     + (f" {n(lag_neg)} מבנים שבהם תעודת שלב ב קודמת לשלב א אינם נכללים."
                        if lag_neg else "")),
        "lag_aria": "תרשים עמודות: מבנים לפי משך הזמן בין תעודת שלב א לתעודת שלב ב, בחודשים.",
        "lag_caption": "מספר מבנים לפי משך הזמן בין שלב א לשלב ב.",
        "munis_note": (f"{TOP_MUNIS} הרשויות עם מספר הרשומות הגדול ביותר, לפי שלב ההתעדה; "
                       f"שאר הרשויות ורשומות ללא רשות מקובצות ב\"אחר\"."),
        "munis_aria": (f"תרשים עמודות מוערמות: {TOP_MUNIS} הרשויות המובילות לפי מספר רשומות "
                       f"ושלב התעדה; בראש {top_m[0] if top_m else ''}."),
        "munis_caption": "מספר רשומות לפי רשות ושלב התעדה.",
        "units_note": (f"סך יחידות הדיור ברשומות הבנייה הירוקה, {TOP_UNITS} הרשויות המובילות."
                       + (f" {n(units_bad)} רשומות עם מספר יחידות שלילי או מעל {n(UNITS_MAX)} "
                          f"(שגיאת הזנה) אינן נכללות." if units_bad else "")),
        "units_aria": (f"תרשים עמודות: יחידות דיור לפי רשות, {TOP_UNITS} המובילות; בראש "
                       f"{u.index[0] if len(u) else ''}."),
        "units_caption": "יחידות דיור ומספר רשומות לפי רשות.",
        "uses_note": ("שיעור הרשומות בכל שלב התעדה, לפי השימוש העיקרי (מספרי הרשומות בטבלה)."
                      + (f" שימושים עם פחות מ-{MIN_USE} רשומות מקובצים ב\"אחר\"." if use_small else "")
                      + (f" השיעור הגבוה ביותר של רשומות בשלב ב — {top_use_b[0]} "
                         f"({pct(top_use_b[1])})." if top_use_b else "")),
        "uses_aria": (f"תרשים עמודות מוערמות: התפלגות שלב ההתעדה בכל שימוש עיקרי, באחוזים; "
                      f"השימוש הנפוץ — {uses.index[0]}."),
        "uses_caption": "מספר רשומות לפי שימוש עיקרי ושלב התעדה.",
        "routes_caption": "מספר רשומות לפי מסלול הבנייה.",
        "floors_note": (f"מספר הקומות מעל הקרקע בכל רשומה, מגורים מול שאר השימושים. "
                        f"חציון במגורים: {med_floors:.0f} קומות; {pct(tall_share)} מרשומות המגורים "
                        f"הן מעל עשרים קומות."),
        "floors_aria": "תרשים עמודות מוערמות: רשומות לפי מספר קומות, מגורים ושימושים אחרים.",
        "floors_caption": "מספר רשומות לפי מספר קומות מעל הקרקע.",
        "map_aria": ("מפה אינטראקטיבית של המבנים הירוקים. גרסה נגישה: ראו את הטבלאות בעמוד "
                     "ואת קובץ הנתונים."),
    }
    labels["map_note"] = ("כל נקודה היא רשומת שימוש במבנה; לחיצה מציגה את הרשות, הרחוב, השימוש "
                          "ושלב ההתעדה.")

    charts = {
        "stages": {"names": stage_order, "values": stage_vals,
                   "colors": [stage_colors[x] for x in stage_order]},
        "years": {"x": year_labels,
                  "series": [{"name": label, "data": [int(years_data[s].get(y, 0)) for y in years]}
                             for s, label in CERTS]},
        "stars": {"levels": [stars_label(v) for v in star_levels], "rows": shares(stars_rows),
                  "colors": ramp(len(star_levels))},
        "energy": {"levels": [iso(g) for g in grades], "rows": shares(energy_rows),
                   "colors": list(reversed(ramp(len(grades))))},
        "scores": {"x": [x if x[0] not in "0123456789" else iso(x) for x in score_labels],
                   "series": [{"name": r["cert"],
                               "data": [round(c / r["n"] * 100, 1) if r["n"] else 0
                                        for c in r["counts"]]} for r in score_rows]},
        "etrans": {"x": [iso(g) for g in e_x], "y": [iso(g) for g in e_y], "cells": e_cells,
                   "max": max([c[2] for c in e_cells] or [1])},
        "strans": {"x": [str(v) for v in s_x], "y": [str(v) for v in s_y], "cells": s_cells,
                   "max": max([c[2] for c in s_cells] or [1])},
        "lag": {"names": [iso(x) for x in _bucket_labels(LAG_BUCKETS, "")], "values": lag_vals},
        "munis": {"names": muni_names, "series": muni_series},
        "units": {"names": list(u.index), "values": [int(v) for v in u.values]},
        "uses": {"names": use_names, "series": use_series},
        "floors": {"names": [iso(x) for x in floor_labels],
                   "series": [{"name": RESIDENTIAL, "data": floor_res},
                              {"name": "שימושים אחרים", "data": floor_oth}]},
    }

    tables = {
        "stages": [{"name": s, "count": n(v), "share": pct(v / total if total else 0)}
                   for s, v in zip(stage_order, stage_vals)],
        "certs": [label for _, label in CERTS],
        "years": [{"year": lab, "cells": [n(years_data[s].get(y, 0)) for s, _ in CERTS]}
                  for lab, y in zip(year_labels, years)],
        "stars_head": [stars_label(v) for v in star_levels],
        "stars": [{"label": r["cert"], "cells": [n(c) for c in r["counts"]]} for r in stars_rows],
        "energy_head": grades,
        "energy": [{"label": r["cert"], "cells": [n(c) for c in r["counts"]]} for r in energy_rows],
        "scores": [{"label": lab, "cells": [n(r["counts"][i]) for r in score_rows]}
                   for i, lab in enumerate(score_labels)],
        "etrans_head": e_x,
        "etrans": [{"label": g, "cells": [n(c[2]) for c in e_cells if c[1] == yi]}
                   for yi, g in enumerate(e_y)],
        "strans_head": [stars_label(v) for v in s_x],
        "strans": [{"label": stars_label(v), "cells": [n(c[2]) for c in s_cells if c[1] == yi]}
                   for yi, v in enumerate(s_y)],
        "lag": [{"bucket": b, "count": n(v)} for b, v in zip(_bucket_labels(LAG_BUCKETS, ""), lag_vals)],
        "stage_head": stage_order,
        "munis": [{"name": m, "total": n(muni_totals[i]),
                   "cells": [n(s["data"][i]) for s in muni_series]}
                  for i, m in enumerate(muni_names)],
        "units": [{"name": m, "units": n(v), "records": n(rec_by_muni.get(m, 0))}
                  for m, v in zip(u.index, u.values)],
        "uses": [{"name": x, "total": n(use_tot[x]), "cells": [n(use_counts[st][i]) for st in stage_order]}
                 for i, x in enumerate(use_names)],
        "routes": [{"name": r, "count": n(v), "share": pct(v / total if total else 0)}
                   for r, v in routes.items()],
        "floors": [{"bucket": b, "res": n(floor_res[i]), "oth": n(floor_oth[i])}
                   for i, b in enumerate(floor_labels)],
    }

    first_year = years[0] if years else ref_year
    return {
        "agent_data": {
            "summary_he": (f"מאגר המבנים בבנייה ירוקה לפי ת״י 5281: {n(total)} רשומות ב-{n(buildings)} "
                           f"מבנים, עם שלב ההתעדה, ציון, דירוג כוכבים ודירוג אנרגיה של כל תעודה, "
                           f"ומיקום המבנה."),
            "dataset_kind": "map",
            "suggested_tags": ["בנייה ירוקה", "תקן 5281", "יעילות אנרגטית", "דיור",
                               "תכנון ובנייה", "הגנת הסביבה"],
            "related_ids": ["4d95a5ed-d567-4515-bbfb-517c6c0b859f",
                            "04931a88-336c-4d95-8a13-9dc631c3e2d1"],
            "temporal_coverage": f"{first_year}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
