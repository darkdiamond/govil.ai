"""כלי רכב מעל 3 וחצי טון וכלי רכב חסרי קוד דגם — the heavy / no-model-code register.

One row per ACTIVE vehicle that has no model code in the type register:
trailers and semi-trailers, trucks, tractors (incl. quad bikes registered as
T-category tractors), buses, work vehicles, light commercials and a vintage
tail of private cars. The export is a snapshot, so every "by year" view
counts vehicles that are still active.

- `kvutzat_sug_rechev` (vehicle group) is the backbone dimension; groups
  below MIN_GROUP rows are folded into "אחר" in per-group charts.
- `moed_aliya_lakvish` ("YYYY-M") is the month of first road entry; it is
  recorded only from the late 2000s (the series starts at the first year
  where most vehicles carry it) and its year equals the production year.
- Production years thin sharply after the register's peak year: newer
  vehicles mostly get a model code and so are not in this dataset. The page
  says so; no trend rule reads that drop as a market trend.
- Weights are kilograms; 0 means "not recorded" and is excluded.
- Licence plates, VINs and engine serial numbers are never shown —
  everything is aggregated by group, category, maker, model, year, fuel,
  drive layout, weight, engine and seats.
"""
import math
import re

import pandas as pd

OTHER = "אחר"
UNKNOWN = "לא ידוע"
MIN_GROUP = 100            # groups below this many rows fold into "אחר" in per-group charts
TOP_MAKERS = 15
TOP_MODELS = 15
TOP_COUNTRIES = 12
TOP_ENGINES = 10
TOP_DRIVES = 6
ROAD_COVERAGE = 0.8        # road-entry series starts at the first year where ≥80% of vehicles carry the month
MAX_MONTHLY_POINTS = 480   # beyond this the road-entry series switches to quarters
SEASON_RATIO = 1.25        # a month this many × the 1/12 average is a clear peak
SEASON_MIN_YEAR = 500      # a year counts toward seasonality only with this many road entries
CLIFF_RATIO = 0.4          # years after the peak averaging below 40% of the peak = a sharp drop
VINTAGE_GAP = 15           # a group whose median year is this much older than the register's
LEAD_SHARE = 0.2
COUNTRY_GROUP_SHARE = 0.5
PETROL_SHARE = 0.25
AXLE_SHARE = 0.1
HEAVY_KG = 3500            # the dataset's title threshold (3.5 tonnes)
RECENT_YEARS = 5           # "recent production years" window for the electric-bus rule

PETROL = "בנזין"
ELECTRIC = "חשמל"
FUEL_ALIASES = {'גפמ"': "גפ״מ"}
COUNTRY_ALIASES = {"תורקיה": "טורקיה", "ד. קוריאה": "דרום קוריאה", "קוריאה הדרומית": "דרום קוריאה",
                   "": UNKNOWN}
COUNTRY_TOKENS = ["אנגליה", "קוריאה", "סין", "ישראל", 'ארהב"']
# Maker names the register spells two ways, or truncates.
BRAND_ALIASES = {
    "פולאריס": "פולריס",
    "דימלרקריזלר אר": "דיימלר קרייזלר", "דימלרקריזלר ספ": "דיימלר קרייזלר",
    "דימלרקריזלר": "דיימלר קרייזלר",
    "קיה ד.": "קיה", "אלפא רומיאו אי": "אלפא רומיאו",
    "עצמי": "בנייה עצמית",
    "ניו": "ניו הולנד",
}
# Display labels for the register's vehicle groups (unknown groups show as-is).
GROUP_LABELS = {"גרור נתמך": "גרורים", "משא": "רכב משא", "טרקטור": "טרקטורים", "מסחרי": "רכב מסחרי",
                "אוטובוס": "אוטובוסים", "פרטי": "רכב פרטי", "רכב עבודה": "רכבי עבודה", "מונית": "מוניות"}
COMPANY_SUFFIXES = {"בעמ", 'בעמ"', "בע״מ"}
EU_FAMILY = {"M": "נוסעים", "N": "משא", "O": "גרורים", "T": "טרקטורים"}
SEAT_BINS = [(1, 19, "עד 19"), (20, 29, "20 עד 29"), (30, 39, "30 עד 39"),
             (40, 49, "40 עד 49"), (50, 999, "50 ומעלה")]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _m_he(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def _gershayim(s):
    return re.sub(r'([א-ת])([א-ת])"(?=\s|$)', r"\1״\2", s)


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _top_other(series, n):
    vc = _ranked(series)
    top = vc.head(n)
    rest = int(vc.iloc[n:].sum())
    names, values = list(top.index), [int(v) for v in top]
    if rest:
        names.append(OTHER)
        values.append(rest)
    return names, values


def _brand(name, own_country, countries):
    s = re.sub(r"[._]\s*סין$", "", name.strip())
    toks = [t for t in re.split(r"[\s_\-]+", s) if t]
    if len(toks) > 1 and toks[-1] in COMPANY_SUFFIXES:
        toks = toks[:-1]
    while len(toks) > 1:
        t = toks[-1].strip(".'\"")
        hit = len(t) >= 3 and any(c.startswith(t) or t.startswith(c) for c in countries)
        # Truncated two-letter tails ("סי", "אי") only when they start the row's own country.
        hit = hit or (len(t) == 2 and own_country.startswith(t))
        if not hit:
            break
        toks = toks[:-1]
    b = " ".join(toks).strip()
    if not b:
        return UNKNOWN
    return _gershayim(BRAND_ALIASES.get(b, b))


def _country(c):
    c = c.strip()
    c = COUNTRY_ALIASES.get(c, c)
    return _gershayim(c) if c else UNKNOWN


def _seat_bin(v):
    for lo, hi, label in SEAT_BINS:
        if lo <= v <= hi:
            return label
    return None


def _axles(drive):
    m = re.match(r"^(\d+)X(\d+)$", drive)
    return int(m.group(1)) // 2 if m else None


def _num(col):
    return pd.to_numeric(col.str.replace(",", "").str.strip(), errors="coerce")


def _prepare(df):
    raw_country = df["tozeret_eretz_nm"].str.strip()
    countries = (set(raw_country.unique()) - {""}) | set(COUNTRY_TOKENS)
    names = df["tozeret_nm"].str.strip()
    pairs = pd.DataFrame({"n": names, "c": raw_country}).drop_duplicates()
    pairs = pairs.sort_values(["n", "c"], kind="stable")
    brand_map = {}
    for n, c in zip(pairs["n"], pairs["c"]):
        if n not in brand_map or (not brand_map[n][1] and c):
            brand_map[n] = (_brand(n, c, countries), c)
    road = pd.to_datetime(df["moed_aliya_lakvish"].str.strip() + "-1", errors="coerce", format="%Y-%m-%d")
    fuel = df["sug_delek_nm"].str.strip()
    out = pd.DataFrame({
        "group": df["kvutzat_sug_rechev"].str.strip().map(lambda g: GROUP_LABELS.get(g, g) if g else UNKNOWN),
        "eu": df["tkina_EU"].str.strip().str.upper().replace("", UNKNOWN),
        "year": _num(df["shnat_yitzur"]),
        "brand": names.map(lambda n: brand_map[n][0]),
        "country": raw_country.map(_country),
        "fuel": fuel.map(lambda f: FUEL_ALIASES.get(f, f) if f else ""),
        "gross": _num(df["mishkal_kolel"]),
        "own": _num(df["mishkal_azmi"]),
        "payload": _num(df["mishkal_mitan_harama"]),
        "cc": _num(df["nefach_manoa"]),
        "drive": df["hanaa_nm"].str.strip().str.upper(),
        "road": road.dt.to_period("M"),
        "seats": _num(df["mispar_mekomot"]),
        "tow": df["grira_nm"].str.strip(),
        "model_code": df["degem_nm"].str.strip().str.replace(r"\s+", " ", regex=True),
        "engine": df["degem_manoa"].str.strip().str.replace(r"\s+", " ", regex=True).str.upper(),
    })
    out.loc[out["year"] <= 0, "year"] = float("nan")
    for c in ("gross", "own", "payload", "cc", "seats"):
        out.loc[out[c] <= 0, c] = float("nan")
    out.loc[out["gross"] >= 99999, "gross"] = float("nan")   # unknown-weight placeholder
    out["model"] = out["brand"] + " " + out["model_code"]
    return out


def _q(s, q):
    return float(s.quantile(q)) if len(s) else 0.0


# ── insight rules ────────────────────────────────────────────────────────────

def insight_leader(groups, n):
    if len(groups) < 2:
        return None
    (g1, n1), (g2, n2) = groups[0], groups[1]
    if n1 / n < LEAD_SHARE:
        return None
    return (f"{g1} הם הקבוצה הגדולה במאגר — {_int(n1)} כלי רכב ({_pct(n1 / n)}), "
            f"לפני {g2} ({_int(n2)}, {_pct(n2 / n)}).")


def insight_cliff(cliff):
    if cliff is None:
        return None
    return (f"שנת הייצור הנפוצה במאגר היא {cliff['peak']} ({_int(cliff['peak_n'])} כלי רכב), "
            f"ומיד אחריה המספר צונח: משנות הייצור {cliff['y_from']} עד {cliff['y_to']} רשומים יחד "
            f"{_int(cliff['after_n'])} בלבד — בממוצע {_int(cliff['after_avg'])} לשנה. "
            f"הירידה משקפת את היקף המאגר, ולא בהכרח את מכירות כלי הרכב.")


def insight_vintage(med_years, overall_med):
    if not med_years:
        return None
    g, med, cnt = sorted(med_years, key=lambda t: (t[1], t[0]))[0]
    if overall_med - med < VINTAGE_GAP:
        return None
    return (f"{_int(cnt)} כלי הרכב בקבוצת {g} ותיקים במיוחד: שנת הייצור החציונית שלהם {int(med)}, "
            f"לעומת {int(overall_med)} בכלל המאגר.")


def insight_country(df, n):
    vc = _ranked(df.loc[df["country"] != UNKNOWN, "country"])
    if len(vc) < 2:
        return None
    c1, n1 = vc.index[0], int(vc.iloc[0])
    sub = _ranked(df.loc[df["country"] == c1, "group"])
    g1, gn = sub.index[0], int(sub.iloc[0])
    if gn / n1 < COUNTRY_GROUP_SHARE:
        return None
    return (f"{c1} היא ארץ הייצור הנפוצה — {_int(n1)} כלי רכב ({_pct(n1 / n)}), "
            f"ו-{_pct(gn / n1)} מהם {g1}.")


def insight_electric(df):
    ev = df[df["fuel"] == ELECTRIC]
    if len(ev) < 50:
        return None
    vc = _ranked(ev["group"])
    g1, n1 = vc.index[0], int(vc.iloc[0])
    if n1 / len(ev) < 0.4:
        return None
    gsub = df[(df["group"] == g1) & df["year"].notna()]
    if not len(gsub):
        return None
    y1 = int(gsub["year"].max())
    lo = y1 - RECENT_YEARS + 1
    rec = gsub[gsub["year"] >= lo]
    share = (rec["fuel"] == ELECTRIC).mean() if len(rec) else 0.0
    if share < 0.01:
        return None
    return (f"במאגר {_int(len(ev))} כלי רכב חשמליים, {_int(n1)} מהם ({_pct(n1 / len(ev))}) בקבוצת "
            f"{g1}; מכלי הקבוצה משנות הייצור {lo} עד {y1} שבמאגר, {_pct(share)} חשמליים.")


def insight_petrol(df, group_name):
    sub = df[(df["group"] == group_name) & (df["fuel"] != "")]
    if len(sub) < 500:
        return None
    pet = sub[sub["fuel"] == PETROL]
    share = len(pet) / len(sub)
    if share < PETROL_SHARE:
        return None
    vc = _ranked(pet["brand"]).head(3)
    makers = ", ".join(f"{b} ({_int(v)})" for b, v in vc.items())
    return (f"{_pct(share)} מכלי הרכב בקבוצת {group_name} מונעים בבנזין ({_int(len(pet))} כלים); "
            f"היצרנים הנפוצים ביניהם: {makers}.")


def insight_axles(df, group_name):
    sub = df[df["group"] == group_name]
    ax = sub["drive"].map(_axles).dropna()
    if len(ax) < 500:
        return None
    multi = (ax >= 3).mean()
    if multi < AXLE_SHARE:
        return None
    four = (ax >= 4).mean()
    return (f"{_pct(multi)} מכלי הרכב בקבוצת {group_name} שתצורת ההנעה שלהם רשומה הם בעלי שלושה סרנים "
            f"או יותר, ו-{_pct(four)} — ארבעה ומעלה.")


def insight_seats(seat_rows, n_bus, med):
    if n_bus < 300 or not seat_rows:
        return None
    big = seat_rows[-1]
    small = seat_rows[0]
    return (f"מספר המקומות החציוני באוטובוס הוא {int(med)}; {_pct(big['n'] / n_bus)} מהאוטובוסים "
            f"עם {big['label']} מקומות ו-{_pct(small['n'] / n_bus)} עם {small['label']}.")


def insight_payload(pay_med):
    if len(pay_med) < 2:
        return None
    hi = max(pay_med, key=lambda t: (t[1], t[0]))
    lo = min(pay_med, key=lambda t: (t[1], t[0]))
    if hi[1] - lo[1] < 0.15:
        return None
    return (f"כושר ההעמסה החציוני הוא {_pct(hi[1], 0)} מהמשקל הכולל ב{hi[0]}, "
            f"לעומת {_pct(lo[1], 0)} בלבד ב{lo[0]}.")


def insight_season(season):
    if season is None or season["hi"][1] < SEASON_RATIO / 12:
        return None
    hi, lo = season["hi"], season["lo"]
    return (f"בשנים {season['y0']} עד {season['y1']} עלו לכביש בממוצע {_pct(hi[1])} מכלי כל שנה "
            f"ב{MONTHS_HE[hi[0] - 1]}, לעומת {_pct(lo[1])} ב{MONTHS_HE[lo[0] - 1]}.")


def insight_heavy(df):
    w = df[df["gross"].notna()]
    if len(w) < 1000:
        return None
    heavy = w["gross"] > HEAVY_KG
    share = heavy.mean()
    light = _ranked(w.loc[~heavy, "group"])
    if len(light) < 2 or share >= 0.95:
        return None
    (l1, n1), (l2, n2) = list(light.items())[:2]
    return (f"ל-{_pct(share)} מהכלים שמשקלם רשום משקל כולל מעל {_int(HEAVY_KG)} ק״ג; "
            f"בין הקלים יותר בולטים {l1} ({_int(n1)}) ו{l2} ({_int(n2)}).")


# ── compute ──────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])
    n = len(df)
    years = df["year"].dropna().astype(int)
    y0, y1 = int(years.min()), int(years.max())

    # ── Groups ─────────────────────────────────────────────────────────────
    gvc = _ranked(df["group"])
    groups_all = [(g, int(v)) for g, v in gvc.items()]
    big_groups = [g for g, v in groups_all if v >= MIN_GROUP]
    df["g"] = df["group"].where(df["group"].isin(big_groups), OTHER)
    g_order = big_groups + ([OTHER] if (df["g"] == OTHER).any() else [])
    n_small = int((df["g"] == OTHER).sum())
    small_names = [g for g, v in groups_all if v < MIN_GROUP]

    # Sunburst: group → EU category.
    sb = []
    ge = df.groupby(["group", "eu"]).size()
    for g, v in groups_all:
        kids = ge.loc[g].sort_index().sort_values(ascending=False, kind="stable")
        sb.append({"name": g, "value": v,
                   "children": [{"name": e, "value": int(c)} for e, c in kids.items()]})
    t_groups = []
    for g, v in groups_all:
        kids = ge.loc[g].sort_index().sort_values(ascending=False, kind="stable")
        cats = ", ".join(f"{e} ({_int(c)})" for e, c in kids.items())
        t_groups.append({"name": g, "count": _int(v), "share": f"{v / n * 100:.1f}", "cats": cats})
    eu_vc = _ranked(df["eu"])
    fam = df["eu"].str[0].map(EU_FAMILY).fillna(OTHER)
    fam_vc = _ranked(fam)
    fam_text = ", ".join(f"{k} — {_int(v)}" for k, v in fam_vc.items())

    # ── Road entry by month ───────────────────────────────────────────────
    rd_year = df["road"].dropna().dt.year
    has = df["road"].notna().groupby(df["year"])
    cov = pd.DataFrame({"cov": has.mean(), "n": has.size()}).sort_index()
    # Start at the earliest year from which every (non-trivial) later year carries the month.
    start_year = int(rd_year.max())
    for y, r in cov.sort_index(ascending=False).iterrows():
        if r["n"] < 50:
            continue
        if r["cov"] < ROAD_COVERAGE:
            break
        start_year = int(y)
    rs = df.loc[df["road"].notna() & (rd_year.reindex(df.index) >= start_year), "road"]
    last_m = rs.max()
    months = pd.period_range(pd.Period(f"{start_year}-01", freq="M"), last_m, freq="M")
    mc = rs.value_counts()
    monthly = pd.Series([int(mc.get(p, 0)) for p in months], index=months)
    if len(monthly) > MAX_MONTHLY_POINTS:
        q = monthly.groupby(monthly.index.asfreq("Q")).sum()
        road_chart = {"x": [f"{p.year} Q{p.quarter}" for p in q.index], "y": [int(v) for v in q], "unit": "רבעון"}
    else:
        road_chart = {"x": [f"{p.year}-{p.month:02d}" for p in monthly.index],
                      "y": [int(v) for v in monthly], "unit": "חודש"}
    peak_sorted = monthly.sort_index().sort_values(ascending=False, kind="stable")
    peak_m = peak_sorted.index[0]
    n_road = int(df["road"].notna().sum())
    n_road_series = int(monthly.sum())
    complete = [yy for yy in range(start_year, last_m.year + 1)
                if pd.Period(f"{yy}-12", freq="M") < last_m]
    season = None
    shares, used = [], []
    for yy in complete:
        vals = [int(monthly.get(pd.Period(f"{yy}-{m:02d}", freq="M"), 0)) for m in range(1, 13)]
        tot = sum(vals)
        if tot >= SEASON_MIN_YEAR:
            shares.append([v / tot for v in vals])
            used.append(yy)
    if len(shares) >= 3:
        avg = [math.fsum(s[i] for s in shares) / len(shares) for i in range(12)]
        order = sorted(range(12), key=lambda i: (-avg[i], i))
        season = {"hi": (order[0] + 1, avg[order[0]]), "lo": (order[-1] + 1, avg[order[-1]]),
                  "y0": used[0], "y1": used[-1]}
        season_chart = {"names": MONTHS_HE, "values": [round(a * 100, 2) for a in avg]}
    else:
        season_chart = None

    # ── Production year × group ───────────────────────────────────────────
    yv = df.dropna(subset=["year"]).copy()
    yv["year"] = yv["year"].astype(int)
    all_years = list(range(y0, y1 + 1))
    piv = yv.groupby(["year", "g"]).size().unstack(fill_value=0).reindex(index=all_years, columns=g_order, fill_value=0)
    years_chart = {"x": [str(y) for y in all_years],
                   "series": [{"name": g, "data": [int(v) for v in piv[g]]} for g in g_order]}
    years_chart["zoom"] = max(0, round(100 - 45 / max(len(all_years), 1) * 100))
    coh = yv["year"].map(lambda y: 1979 if y < 1980 else y // 5 * 5)
    ct = yv.groupby([coh, "g"]).size().unstack(fill_value=0).reindex(columns=g_order, fill_value=0).sort_index()
    t_years = [{"name": (f"עד {c}" if c == 1979 else f"{c} עד {min(c + 4, y1)}"),
                "total": _int(ct.loc[c].sum()), "cols": [_int(ct.loc[c, k]) for k in g_order]}
               for c in ct.index]
    yc = yv.groupby("year").size().reindex(all_years, fill_value=0)
    peak_year = int(yc.sort_index().sort_values(ascending=False, kind="stable").index[0])
    after = yc[(yc.index > peak_year) & (yc.index < y1)]   # the newest year may be partial
    cliff = None
    if len(after) >= 3 and int(yc[peak_year]) >= 1000:
        avg_after = after.mean()
        nxt = int(yc.get(peak_year + 1, 0))
        if avg_after < CLIFF_RATIO * yc[peak_year] and nxt < yc[peak_year]:
            # The drop starts at the first year after the peak below half the peak.
            first = next((y for y in after.index if yc[y] < 0.5 * yc[peak_year]), int(after.index[0]))
            tail = yc[(yc.index >= first)]
            cliff = {"peak": peak_year, "peak_n": int(yc[peak_year]), "y_from": int(first), "y_to": y1,
                     "after_n": int(tail.sum()), "after_avg": round(float(tail.mean()))}

    # Age by group (boxplot of production year).
    box_years, t_age, med_years = [], [], []
    for g in big_groups:
        s = yv.loc[yv["group"] == g, "year"]
        qs = [_q(s, q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
        box_years.append([round(v) for v in qs])
        med_years.append((g, float(s.median()), int(len(s))))
        t_age.append({"name": g, "q1": str(round(qs[1])), "med": str(round(qs[2])), "q3": str(round(qs[3]))})
    overall_med = float(years.median())
    age_order = sorted(range(len(big_groups)), key=lambda i: (box_years[i][2], box_years[i][1], big_groups[i]))
    age_chart = {"names": [big_groups[i] for i in age_order], "data": [box_years[i] for i in age_order]}
    t_age = [t_age[i] for i in age_order]

    # ── Fuel by group (powered vehicles only) ──────────────────────────────
    fv = df[df["fuel"] != ""]
    fuels = list(_ranked(fv["fuel"]).index)
    fuel_main = fuels[:5]
    fv_f = fv["fuel"].where(fv["fuel"].isin(fuel_main), OTHER)
    fuel_cols = fuel_main + ([OTHER] if (fv_f == OTHER).any() else [])
    f_groups = [g for g in g_order if (fv["g"] == g).sum() >= MIN_GROUP]
    fp = fv.assign(f=fv_f).groupby(["g", "f"]).size().unstack(fill_value=0).reindex(index=f_groups, columns=fuel_cols, fill_value=0)
    fuel_chart = {"names": f_groups,
                  "series": [{"name": f, "data": [round(fp.loc[g, f] / fp.loc[g].sum() * 100, 1) for g in f_groups]}
                             for f in fuel_cols]}
    t_fuel = [{"name": g, "cols": [_int(fp.loc[g, f]) for f in fuel_cols]} for g in f_groups]
    n_no_fuel = int(n - len(fv))
    no_fuel_groups = _ranked(df.loc[df["fuel"] == "", "group"])
    no_fuel_top = no_fuel_groups.index[0] if len(no_fuel_groups) else ""
    n_ev = int((df["fuel"] == ELECTRIC).sum())

    # ── Makers, models, countries, engines ─────────────────────────────────
    top_makers = list(_ranked(df["brand"]).head(TOP_MAKERS).index)
    bm = df[df["brand"].isin(top_makers)].groupby(["brand", "g"]).size().unstack(fill_value=0)
    bm = bm.reindex(index=top_makers, columns=g_order, fill_value=0)
    m_groups = [g for g in g_order if bm[g].sum() > 0]
    makers_chart = {"names": top_makers,
                    "series": [{"name": g, "data": [int(bm.loc[b, g]) for b in top_makers]} for g in m_groups]}
    t_makers = [{"name": b, "count": _int(bm.loc[b].sum()), "share": f"{bm.loc[b].sum() / n * 100:.1f}",
                 "main": _ranked(df.loc[df["brand"] == b, "group"]).index[0]} for b in top_makers]
    n_brands = int(df["brand"].nunique())
    top15_share = bm.values.sum() / n

    mv = _ranked(df.loc[df["model_code"] != "", "model"]).head(TOP_MODELS)
    models_chart = {"names": list(mv.index), "values": [int(v) for v in mv]}
    model_groups = df[df["model"].isin(mv.index)].groupby("model")["group"].agg(lambda s: _ranked(s).index[0])
    t_models = [{"name": k, "count": _int(v), "main": model_groups[k]} for k, v in mv.items()]
    n_models = int(df.loc[df["model_code"] != "", "model"].nunique())

    ev_ = df[df["engine"] != ""]
    env = _ranked(ev_["engine"]).head(TOP_ENGINES)
    eng_brand = ev_[ev_["engine"].isin(env.index)].groupby("engine")["brand"].agg(lambda s: _ranked(s).index[0])
    t_engines = [{"name": k, "count": _int(v), "main": eng_brand[k]} for k, v in env.items()]
    n_engine = int(len(ev_))

    top_c = list(_ranked(df["country"]).head(TOP_COUNTRIES).index)
    cvals = df["country"].where(df["country"].isin(top_c), OTHER)
    c_order = top_c + ([OTHER] if (cvals == OTHER).any() else [])
    cg = df.assign(c=cvals).groupby(["c", "g"]).size().unstack(fill_value=0).reindex(index=c_order, columns=g_order, fill_value=0)
    countries_chart = {"names": c_order,
                       "series": [{"name": g, "data": [int(cg.loc[c, g]) for c in c_order]} for g in g_order if cg[g].sum() > 0]}
    t_countries = [{"name": c, "count": _int(cg.loc[c].sum()), "share": f"{cg.loc[c].sum() / n * 100:.1f}"} for c in c_order]

    # ── Payload as a share of gross weight ─────────────────────────────────
    pw = df[df["gross"].notna() & df["payload"].notna() & (df["payload"] < df["gross"])].copy()
    pw["ratio"] = pw["payload"] / pw["gross"]
    pay_box, t_pay, pay_med = [], [], []
    pay_groups = [g for g in big_groups if (pw["group"] == g).sum() >= MIN_GROUP]
    for g in pay_groups:
        s = pw.loc[pw["group"] == g, "ratio"]
        qs = [_q(s, q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
        pay_box.append([round(v * 100, 1) for v in qs])
        pay_med.append((g, qs[2]))
        t_pay.append({"name": g, "n": _int(len(s)), "q1": f"{qs[1] * 100:.0f}", "med": f"{qs[2] * 100:.0f}",
                      "q3": f"{qs[3] * 100:.0f}"})
    p_order = sorted(range(len(pay_groups)), key=lambda i: (pay_box[i][2], pay_box[i][1], pay_groups[i]))
    payload_chart = {"names": [pay_groups[i] for i in p_order], "data": [pay_box[i] for i in p_order]}
    t_pay = [t_pay[i] for i in p_order]
    n_pay = int(len(pw))

    # ── Drive layout (powered groups) ──────────────────────────────────────
    dv = df[df["drive"].str.match(r"^\d+X\d+$")]
    top_d = list(_ranked(dv["drive"]).head(TOP_DRIVES).index)
    dvals = dv["drive"].where(dv["drive"].isin(top_d), OTHER)
    d_cols = top_d + ([OTHER] if (dvals == OTHER).any() else [])
    d_groups = [g for g in g_order if (dv["g"] == g).sum() >= MIN_GROUP]
    dp = dv.assign(d=dvals).groupby(["g", "d"]).size().unstack(fill_value=0).reindex(index=d_groups, columns=d_cols, fill_value=0)
    drive_chart = {"names": d_groups,
                   "series": [{"name": d, "data": [round(dp.loc[g, d] / dp.loc[g].sum() * 100, 1) for g in d_groups]}
                              for d in d_cols]}
    t_drive = [{"name": g, "cols": [_int(dp.loc[g, d]) for d in d_cols]} for g in d_groups]
    n_drive_unknown = int(n - len(dv))
    du = _ranked(df.loc[~df.index.isin(dv.index), "group"])
    drive_unknown_top = du.index[0] if len(du) else ""
    truck_group = GROUP_LABELS["משא"] if GROUP_LABELS["משא"] in big_groups else None

    # ── Engine volume by group ─────────────────────────────────────────────
    cv = df[df["cc"].notna() & (df["cc"] >= 50) & (df["cc"] <= 30000)]
    # Groups where the engine volume is recorded for at least half the vehicles (trailers have none).
    gsize = df.groupby("group").size()
    cc_groups = [g for g in big_groups
                 if (cv["group"] == g).sum() >= MIN_GROUP and (cv["group"] == g).sum() >= 0.5 * gsize[g]]
    cc_box, t_cc = [], []
    for g in cc_groups:
        s = cv.loc[cv["group"] == g, "cc"]
        qs = [_q(s, q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
        cc_box.append([round(v) for v in qs])
        t_cc.append({"name": g, "n": _int(len(s)), "q1": _int(round(qs[1])), "med": _int(round(qs[2])),
                     "q3": _int(round(qs[3]))})
    c_order2 = sorted(range(len(cc_groups)), key=lambda i: (cc_box[i][2], cc_box[i][1], cc_groups[i]))
    cc_chart = {"names": [cc_groups[i] for i in c_order2], "data": [cc_box[i] for i in c_order2]}
    t_cc = [t_cc[i] for i in c_order2]
    cc_skipped = [g for g in big_groups if g not in cc_groups]
    n_cc_out = int(n - len(cv))

    # ── Bus seats ──────────────────────────────────────────────────────────
    bus_group = GROUP_LABELS["אוטובוס"] if GROUP_LABELS["אוטובוס"] in big_groups else None
    seat_rows, seats_chart, bus_med, n_bus_seats = [], None, 0, 0
    if bus_group:
        bs = df.loc[(df["group"] == bus_group) & df["seats"].notna(), "seats"]
        n_bus_seats = int(len(bs))
        if n_bus_seats:
            bins = bs.map(_seat_bin).value_counts()
            seat_rows = [{"label": b[2], "n": int(bins.get(b[2], 0))} for b in SEAT_BINS]
            seats_chart = {"names": [r["label"] for r in seat_rows], "values": [r["n"] for r in seat_rows]}
            bus_med = float(bs.median())
    t_seats = [{"name": r["label"], "count": _int(r["n"]), "share": f"{r['n'] / max(n_bus_seats, 1) * 100:.1f}"}
               for r in seat_rows]

    # ── Group profile table ────────────────────────────────────────────────
    t_profile = []
    for g in big_groups:
        s = df[df["group"] == g]
        hook = (s["tow"] != "אין וו גרירה") & (s["tow"] != "")
        t_profile.append({
            "name": g, "count": _int(len(s)),
            "year": str(int(s["year"].median())) if s["year"].notna().any() else "—",
            "gross": _int(s["gross"].median()) if s["gross"].notna().any() else "—",
            "own": _int(s["own"].median()) if s["own"].notna().any() else "—",
            "payload": _int(s["payload"].median()) if s["payload"].notna().any() else "—",
            "tow": f"{hook.mean() * 100:.0f}",
        })
    tow_any = ((df["tow"] != "אין וו גרירה") & (df["tow"] != "")).mean()

    # ── KPIs ───────────────────────────────────────────────────────────────
    g_known = df["gross"].dropna()
    heavy_share = float((g_known > HEAVY_KG).mean()) if len(g_known) else 0.0
    recent = df[df["year"] >= y1 - RECENT_YEARS + 1]
    recent_p = recent[recent["fuel"] != ""]
    ev_recent = float((recent_p["fuel"] == ELECTRIC).mean()) if len(recent_p) else 0.0
    old_p = df[(df["year"] < y1 - RECENT_YEARS + 1) & (df["fuel"] != "")]
    ev_old = float((old_p["fuel"] == ELECTRIC).mean()) if len(old_p) else 0.0
    ev_tone = "ok" if ev_recent >= ev_old + 0.01 else "brand"
    med_tone = "warn" if y1 - overall_med >= 15 else "brand"

    # ── Insights ───────────────────────────────────────────────────────────
    tractor = GROUP_LABELS["טרקטור"] if GROUP_LABELS["טרקטור"] in big_groups else None
    rules = [
        ("leader", insight_leader(groups_all, n)),
        ("cliff", insight_cliff(cliff)),
        ("vintage", insight_vintage(med_years, overall_med)),
        ("country", insight_country(df, n)),
        ("electric", insight_electric(df)),
        ("petrol", insight_petrol(df, tractor) if tractor else None),
        ("axles", insight_axles(df, truck_group) if truck_group else None),
        ("seats", insight_seats(seat_rows, n_bus_seats, bus_med) if bus_group else None),
        ("payload", insight_payload(pay_med)),
        ("season", insight_season(season)),
        ("heavy", insight_heavy(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    small_note = (f" קבוצות קטנות ({', '.join(small_names)} — {_int(n_small)} כלים) מאוחדות תחת \"{OTHER}\"."
                  if small_names else "")

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} כלי רכב פעילים מעל 3.5 טון וכלי רכב חסרי קוד דגם — גרורים, משאיות, "
                           f"טרקטורים, אוטובוסים, רכבי עבודה ורכב מסחרי ופרטי ותיק — שנות ייצור {y0} עד {y1}. "
                           f"הקבוצה הגדולה: {groups_all[0][0]} ({_pct(groups_all[0][1] / n)}); "
                           f"ל-{_pct(heavy_share)} מהם משקל כולל מעל {_int(HEAVY_KG)} ק״ג."),
            "dataset_kind": "registry",
            "related_ids": [
                "5877dcf0-1895-4f35-b87b-c85a0b286318",
                "0219b34f-43c7-435b-bdfe-e65e944cde50",
                "45e317cf-7bb1-4535-b8cf-be5e79ea341f",
                "0f16b39a-6016-408d-805d-31f40d5a0990",
                "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
            ],
            "suggested_tags": ["רכב כבד", "משאיות", "אוטובוסים", "גרורים", "טרקטורים", "צי הרכב", "תחבורה"],
            "temporal_coverage": f"{y0}/{y1}",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "heavy": {"value": round(heavy_share, 4), "display": _pct(heavy_share), "tone": "info"},
            "median_year": {"value": int(overall_med), "display": str(int(overall_med)), "tone": med_tone},
            "ev": {"value": n_ev, "display": _int(n_ev), "tone": ev_tone},
        },
        "charts": {
            "groups": sb,
            "road": road_chart,
            "season": season_chart,
            "years": years_chart,
            "age": age_chart,
            "fuel": fuel_chart,
            "makers": makers_chart,
            "models": models_chart,
            "countries": countries_chart,
            "payload": payload_chart,
            "drive": drive_chart,
            "cc": cc_chart,
            "seats": seats_chart,
        },
        "tables": {
            "groups": t_groups,
            "g_cols": g_order,
            "years": t_years,
            "age": t_age,
            "fuel_cols": fuel_cols,
            "fuel": t_fuel,
            "makers": t_makers,
            "models": t_models,
            "engines": t_engines,
            "countries": t_countries,
            "payload": t_pay,
            "drive_cols": d_cols,
            "drive": t_drive,
            "cc": t_cc,
            "seats": t_seats,
            "season": ([{"name": m, "share": f"{v:.1f}"} for m, v in zip(MONTHS_HE, season_chart["values"])]
                       if season_chart else []),
            "profile": t_profile,
        },
        "insights": insights,
        "labels": {
            "title": "כלי רכב מעל 3 וחצי טון וכלי רכב חסרי קוד דגם",
            "lede": (f"המאגר מונה {_int(n)} כלי רכב פעילים במשרד התחבורה — כלי רכב כבדים וכלי רכב חסרי "
                     f"קוד דגם: גרורים, משאיות, טרקטורים, אוטובוסים, רכבי עבודה, ולצידם רכב מסחרי ופרטי "
                     f"ותיק. שנות הייצור {y0} עד {y1}. זו תמונת הצי הפעיל — כלים שנגרעו אינם בו — "
                     f"ולכן שנים ותיקות מיוצגות חלקית."),
            "total_kpi": "כלי רכב פעילים במאגר",
            "heavy_kpi": f"משקל כולל מעל {_int(HEAVY_KG)} ק״ג (מהכלים שמשקלם רשום)",
            "median_year_kpi": "שנת ייצור חציונית",
            "ev_kpi": "כלי רכב חשמליים",
            "groups_note": (f"{len(groups_all)} קבוצות סוג רכב ו-{len(eu_vc)} קטגוריות תקינה אירופית. "
                            f"הטבעת הפנימית — קבוצת הסוג, החיצונית — קטגוריית התקינה. "
                            f"לפי משפחת התקינה: {fam_text}."),
            "groups_aria": f"תרשים שמש: {_int(n)} כלי רכב לפי קבוצת סוג וקטגוריית תקינה אירופית.",
            "road_note": (f"מספר הכלים הפעילים לפי {road_chart['unit']} העלייה לכביש, מ-{start_year} "
                          f"(מאז רוב הכלים נושאים את השדה; {_int(n_road_series)} מתוך {_int(n_road)} "
                          f"הכלים שמועד העלייה שלהם רשום). שנת העלייה לכביש זהה בנתונים לשנת הייצור. השיא — {_m_he(peak_m)} "
                          f"({_int(peak_sorted.iloc[0])} כלים). החודש האחרון ({_m_he(last_m)}) עשוי להיות חלקי."),
            "road_aria": f"תרשים קו: כלי רכב פעילים לפי {road_chart['unit']} עלייה לכביש, {start_year} עד {last_m.year}.",
            "season_note": ((f"החלק הממוצע של כל חודש מהעליות לכביש בשנה, בשנים {season['y0']} עד {season['y1']} "
                             f"(שנים מלאות עם {_int(SEASON_MIN_YEAR)} עליות לפחות).") if season else ""),
            "season_aria": "תרשים עמודות: חלק כל חודש מהעליות לכביש בשנה.",
            "years_note": (f"כל עמודה — שנת ייצור, מחולקת לפי קבוצת הסוג. השיא בשנת {peak_year} "
                           f"({_int(yc[peak_year])} כלים). מספר הכלים משנות הייצור המאוחרות משקף את היקף המאגר, "
                           f"ולא בהכרח את המכירות.{small_note}"),
            "years_aria": f"תרשים עמודות מוערם: כלי רכב לפי שנת ייצור וקבוצת סוג, {y0} עד {y1}.",
            "years_caption": "כלי רכב לפי מחזור שנות ייצור וקבוצת סוג.",
            "age_note": (f"שנת הייצור בכל קבוצה: התיבה — הרבעון התחתון עד העליון, הקו — החציון, "
                         f"השפמים — אחוזון 5 עד 95. החציון בכלל המאגר: {int(overall_med)}."),
            "age_aria": "תרשים תיבה: שנת ייצור לפי קבוצת סוג.",
            "fuel_note": (f"תמהיל הדלק בכל קבוצה (באחוזים). ל-{_int(n_no_fuel)} כלים לא רשום סוג דלק — "
                          f"בעיקר {no_fuel_top} ({_int(no_fuel_groups.iloc[0]) if len(no_fuel_groups) else 0})."),
            "fuel_aria": "תרשים עמודות 100%: סוג הדלק לפי קבוצת סוג.",
            "fuel_caption": "כלי רכב לפי קבוצת סוג וסוג דלק.",
            "makers_note": (f"{_int(n_brands)} יצרנים במאגר; {TOP_MAKERS} המובילים מחזיקים {_pct(top15_share)} "
                            f"מהכלים. שם היצרן מאוחד מכל ארצות המפעל (למשל וולבו שבדיה ובלגיה), וכל עמודה "
                            f"מחולקת לפי קבוצת הסוג — יצרני גרורים מקומיים לצד יצרני משאיות וטרקטורים."),
            "makers_aria": f"תרשים עמודות מוערם: {TOP_MAKERS} היצרנים המובילים לפי קבוצת סוג.",
            "models_note": (f"שם הדגם כפי שנרשם ({_int(n_models)} צירופי יצרן ודגם). "
                            f"אותו דגם עשוי להופיע בכמה כתיבים."),
            "models_aria": f"תרשים עמודות: {TOP_MODELS} הדגמים הנפוצים.",
            "engines_caption": (f"{TOP_ENGINES} דגמי המנוע הנפוצים ({_int(n_engine)} כלים עם דגם מנוע רשום) "
                                f"והיצרן הנפוץ אצל כל אחד."),
            "countries_note": "ארץ המפעל שבו יוצר הכלי, מחולקת לפי קבוצת הסוג.",
            "countries_aria": f"תרשים עמודות מוערם: {TOP_COUNTRIES} ארצות הייצור המובילות לפי קבוצת סוג.",
            "payload_note": (f"כושר ההעמסה (משקל מטען מותר) כאחוז מהמשקל הכולל, לכל קבוצה. "
                             f"מבוסס על {_int(n_pay)} כלים שגם המשקל הכולל וגם כושר ההעמסה שלהם רשומים. "
                             f"התיבה — רבעון תחתון עד עליון, השפמים — אחוזון 5 עד 95."),
            "payload_aria": "תרשים תיבה: כושר העמסה כאחוז מהמשקל הכולל לפי קבוצת סוג.",
            "drive_note": (f"תצורת ההנעה: מספר נקודות הגלגל × מספר המונעות מהן — כל שתי נקודות הן סרן אחד. "
                           f"ל-{_int(n_drive_unknown)} כלים — בעיקר {drive_unknown_top} — התצורה אינה ידועה "
                           f"או שאין להם הנעה."),
            "drive_aria": "תרשים עמודות 100%: תצורת ההנעה לפי קבוצת סוג.",
            "drive_caption": "כלי רכב לפי קבוצת סוג ותצורת הנעה.",
            "cc_note": (f"נפח המנוע בסמ״ק לכל קבוצה (התיבה — רבעון תחתון עד עליון, השפמים — אחוזון 5 עד 95). "
                        f"{_int(n_cc_out)} כלים ללא נפח רשום אינם בתרשים, וכן קבוצות שלרובן לא רשום נפח"
                        + (f" ({', '.join(cc_skipped)})." if cc_skipped else ".")),
            "cc_aria": "תרשים תיבה: נפח מנוע לפי קבוצת סוג.",
            "seats_note": (f"מספר המקומות הרשום ב-{_int(n_bus_seats)} אוטובוסים. "
                           + (f"החציון: {int(bus_med)} מקומות." if n_bus_seats else "")),
            "seats_aria": "תרשים עמודות: אוטובוסים לפי מספר מקומות.",
            "profile_caption": (f"פרופיל לכל קבוצה: חציונים של שנת ייצור ומשקלים (ק״ג), ושיעור הכלים עם וו גרירה "
                                f"(בכלל המאגר: {_pct(tow_any, 0)})."),
        },
        "flags": {"season": season_chart is not None, "seats": seats_chart is not None},
    }
