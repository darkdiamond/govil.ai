"""מספרי רישוי של כלי רכב דו גלגליים — the ACTIVE two-wheeler fleet.

One row per active motorcycle / scooter / tricycle / micro-car. The export is
a snapshot of the live register, so every "by year" view counts vehicles that
are STILL ACTIVE: older production years are thinned by scrapping and the
page says so.

- `moed_aliya_lakvish` ("YYYY-M") is the month of first road entry. Its year
  equals the production year in the data, so it adds month granularity to the
  production year. The series starts at the first year that carries a
  meaningful share of the fleet (older entries are a sparse tail).
- The newest month is treated as possibly partial (the export can land
  mid-month); trend rules use only the months before it, compared with the
  same months a year earlier. "Now" is never the clock.
- `hespek` is horsepower. The category code `sug_rechev_EU_cd` (L1/L2/L3)
  splits the fleet by power ceiling; the page shows each class's ceiling as
  computed from the data.
- Licence plates, VINs and engine numbers are never shown — everything is
  aggregated by maker, model code, year, class, power, fuel and ownership.
"""
import math
import re

import pandas as pd

OTHER = "אחר"
UNKNOWN = "לא צוין"
TOP_BRANDS = 15
TOP_MODELS = 15
TOP_COUNTRIES = 12
BOX_BRANDS = 10
MIX_BRANDS = 6
TABLE_YEARS = 12           # year-by-year fallback tables show the latest N years
SERIES_MIN_SHARE = 0.0025  # monthly series starts at the first year with ≥0.25% of the fleet
TREND_BAND = 0.05          # ±5% year-on-year counts as "no clear change"
SHIFT_PP = 0.05            # a class share moving ≥5 points over the comparison span
EV_SPAN = 5                # compare the latest production year with this many years earlier
YOUNG_YEARS = 5            # "built in the last N production years"
MAX_MONTHLY_POINTS = 480   # beyond this the road-entry series switches to quarters
SEASON_RATIO = 1.25        # a month this many × the 1/12 average is a clear peak

ELECTRIC = "חשמלי"
PETROL = "בנזין"
FUEL_MAP = {"בנזין": PETROL, "חשמל": ELECTRIC}

# Manufacturer entries that the register renamed (same model families under a
# new maker code from 2024) or spells two ways. Everything else falls back to
# the name with the plant country stripped, so new makers flow through.
BRAND_ALIASES = {
    "ימהה": "ימאהה",
    "קואנג יאנג": "קימקו",
    "אס ווי אמ": "סאן יאנג", "אס ווי אם": "סאן יאנג", "אס ווי אם וויא": "סאן יאנג",
    "הסקוורנה": "הוסקוורנה", "הוסקוורנאה": "הוסקוורנה",
    "קי.טי.אמ": "קי.טי.אם", "קי טי אם": "קי.טי.אם", "קיי טי אם": "קי.טי.אם",
    "גאסגאס": "גאס גאס", "רויאל אנפלד": "רויאל אנפילד", "טריומף": "טריאומף",
    "יאדאה": "יאדה", "קן אמ": "קן אם", "ואלנטי": "ולנטי",
}
# Plant-country spellings that appear (often truncated) at the end of maker names.
COUNTRY_TOKENS = [
    "ויאטנם", "וייטנאם", "וייטאנם", "ויטנאם", "וויאטנם", "טיוואן", "טאיוון", "טאיוואן",
    "אנגליה", "קוריאה", "ד.קוריאה", "ד.קור", "קורי", 'ארהב"', "אינדונזיה", "שבדיה",
    "מקסיקו", "קנדה", "טורקיה", "צ'כיה", "רוסיה", "הולנד", "פולין", "אוקראינה",
    "ברזיל", "ישראל", "גרמניה", "בריטניה",
]
COUNTRY_ALIASES = {"ויטנאם": "וייטנאם", "וייטאנם": "וייטנאם", "קוריאה הדרומית": "דרום קוריאה"}
ORIGIN_ALIASES = {"ביס לנהיגה": "בי״ס לנהיגה", "יוש-עזה": "יו״ש-עזה"}
CLASS_ORDER = ["L1", "L2", "L3", "L7"]
CLASS_DESC = {"L1": "קל", "L2": "בינוני", "L3": "כבד", "L7": "רכב זעיר"}
CC_BINS = [(1, 50, "עד 50"), (51, 125, "\u206651–125\u2069"), (126, 250, "\u2066126–250\u2069"),
           (251, 400, "\u2066251–400\u2069"), (401, 600, "\u2066401–600\u2069"), (601, 900, "\u2066601–900\u2069"),
           (901, 1200, "\u2066901–1,200\u2069"), (1201, 99999, "מעל 1,200")]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _m_he(p):
    return f"{MONTHS_HE[p.month - 1]} {p.year}"


def _num(v):
    return f"{v:,.1f}".rstrip("0").rstrip(".")


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


def _brand(name, countries):
    s = re.sub(r"[._]\s*סין$", "", name.strip())
    toks = [t for t in re.split(r"[\s_]+", s) if t]
    while len(toks) > 1:
        t = toks[-1].strip(".")
        if len(t) >= 3 and any(c.startswith(t) or t.startswith(c) for c in countries):
            toks = toks[:-1]
            if len(toks) > 1 and toks[-1] in ("ד.", "ד"):
                toks = toks[:-1]
            continue
        break
    b = " ".join(toks)
    if not b:
        return UNKNOWN
    return _gershayim(BRAND_ALIASES.get(b, b))


def _origin(v):
    s = v.strip()
    if not s:
        return ""
    key = s.replace('"', "")
    return ORIGIN_ALIASES.get(key, _gershayim(s))


def _bin_cc(v):
    for lo, hi, label in CC_BINS:
        if lo <= v <= hi:
            return label
    return None


def _prepare(df):
    raw_country = df["tozeret_eretz_nm"].str.strip()
    countries = set(raw_country.unique()) - {""}
    countries |= set(COUNTRY_TOKENS)
    names = df["tozeret_nm"].str.strip()
    brand_map = {n: _brand(n, countries) for n in names.unique()}
    road = pd.to_datetime(df["moed_aliya_lakvish"].str.strip() + "-1",
                          errors="coerce", format="%Y-%m-%d")
    cc = pd.to_numeric(df["nefach_manoa"].str.replace(",", ""), errors="coerce")
    hp = pd.to_numeric(df["hespek"].str.replace(",", ""), errors="coerce")
    # A handful of rows carry the engine volume in the power field (998 "hp"
    # on a 998 cc bike): drop those, and non-positive values.
    hp = hp.where((hp > 0) & ~((hp > 200) & (hp == cc)))
    cls = df["sug_rechev_EU_cd"].str.strip().str.upper().replace("", UNKNOWN)
    model_code = df["degem_nm"].str.strip().str.replace(r"\s+", " ", regex=True)
    out = pd.DataFrame({
        "brand": names.map(brand_map),
        "country": raw_country.map(lambda c: COUNTRY_ALIASES.get(c, _gershayim(c)) if c else UNKNOWN),
        "year": pd.to_numeric(df["shnat_yitzur"], errors="coerce"),
        "road": road.dt.to_period("M"),
        "cc": cc,
        "hp": hp,
        "cls": cls,
        "fuel": df["sug_delek_nm"].str.strip().map(FUEL_MAP).fillna("לא ידוע"),
        "vtype": df["sug_rechev_nm"].str.strip().replace("", UNKNOWN),
        "owner": df["baalut"].str.strip().replace("", UNKNOWN),
        "origin": df["mkoriut_nm"].map(_origin),
        "model_code": model_code,
    })
    out["model"] = out["brand"] + " " + out["model_code"]
    return out


def _classes(df):
    present = set(df["cls"].unique())
    return [c for c in CLASS_ORDER if c in present] + sorted(present - set(CLASS_ORDER))


def _class_label(c):
    d = CLASS_DESC.get(c)
    return f"{c} ({d})" if d else c


# ── insight rules ────────────────────────────────────────────────────────────

def insight_ytd(ytd):
    if ytd is None:
        return None
    cur, prev, ch, span, prev_label = ytd["cur"], ytd["prev"], ytd["ch"], ytd["span"], ytd["prev_label"]
    if abs(ch) < TREND_BAND:
        return (f"ב{span} עלו לכביש {_int(cur)} כלי רכב דו-גלגליים שעדיין פעילים — "
                f"דומה לתקופה המקבילה ב-{prev_label} ({_int(prev)}).")
    word = "יותר" if ch > 0 else "פחות"
    return (f"ב{span} עלו לכביש {_int(cur)} כלי רכב דו-גלגליים שעדיין פעילים, "
            f"{_pct(abs(ch))} {word} מאשר בתקופה המקבילה ב-{prev_label} ({_int(prev)}).")


def insight_young(df, y1):
    y = df["year"].dropna()
    if len(y) < 100:
        return None
    lo = y1 - YOUNG_YEARS + 1
    share = (y >= lo).mean()
    med = int(y.median())
    return f"{_pct(share)} מהצי הפעיל יוצרו בשנים \u2066{lo}–{y1}\u2069, ושנת הייצור החציונית היא {med}."


def insight_ev(ev_by_year, y1, top_ev_brand):
    cur = ev_by_year.get(y1)
    old = ev_by_year.get(y1 - EV_SPAN)
    if not cur or not old or cur["n"] < 100 or old["n"] < 100:
        return None
    if cur["share"] < old["share"] + 0.01:
        return None
    text = (f"חלקם של כלי הרכב החשמליים עלה מ-{_pct(old['share'])} מכלי שנת ייצור {y1 - EV_SPAN} "
            f"ל-{_pct(cur['share'])} משנת ייצור {y1} ({_int(cur['ev'])} כלים)")
    if top_ev_brand:
        text += f"; היצרן החשמלי הנפוץ ביותר בצי הוא {top_ev_brand[0]} ({_int(top_ev_brand[1])})"
    return text + "."


def insight_shift(share_by_year, y1, cls):
    cur = share_by_year.get(y1, {}).get(cls)
    old = share_by_year.get(y1 - EV_SPAN, {}).get(cls)
    if cur is None or old is None or abs(cur - old) < SHIFT_PP:
        return None
    word = "עלה" if cur > old else "ירד"
    return (f"חלקם של הכלים בקטגוריה {_class_label(cls)} {word} מ-{_pct(old)} מכלי שנת ייצור "
            f"{y1 - EV_SPAN} ל-{_pct(cur)} משנת ייצור {y1}.")


def insight_brand(df):
    vc = _ranked(df["brand"])
    if len(vc) < 3:
        return None
    (b1, n1), (b2, n2), (b3, n3) = list(vc.items())[:3]
    share = n1 / len(df)
    if share < 0.08:
        return None
    top3 = (n1 + n2 + n3) / len(df)
    return (f"היצרן הנפוץ ביותר הוא {b1} עם {_int(n1)} כלים ({_pct(share)}), לפני {b2} ({_int(n2)}) "
            f"ו{b3} ({_int(n3)}); שלושתם יחד — {_pct(top3)} מהצי.")


def insight_country(df):
    vc = _ranked(df.loc[df["country"] != UNKNOWN, "country"])
    if len(vc) < 3:
        return None
    top = list(vc.items())[:3]
    share = sum(v for _, v in top) / len(df)
    if share < 0.4:
        return None
    parts = ", ".join(f"{c} ({_int(v)})" for c, v in top)
    return f"{_pct(share)} מהצי יוצרו בשלוש ארצות: {parts}."


def insight_power(df, ceilings):
    l3 = df[df["cls"] == "L3"]
    if len(l3) < 100 or "L2" not in ceilings:
        return None
    med = l3["hp"].median()
    if pd.isna(med):
        return None
    return (f"{_pct(len(l3) / len(df))} מהצי ({_int(len(l3))} כלים) הם בקטגוריה L3, מעל "
            f"{_num(ceilings['L2'])} כ״ס; ההספק החציוני בה {_num(med)} כ״ס.")


def insight_season(season):
    if season is None:
        return None
    hi, lo = season["hi"], season["lo"]
    if hi[1] < SEASON_RATIO / 12:
        return None
    return (f"בשנים \u2066{season['y0']}–{season['y1']}\u2069 עלו לכביש בממוצע {_pct(hi[1])} מכלי כל שנה "
            f"ב{MONTHS_HE[hi[0] - 1]}, לעומת {_pct(lo[1])} בלבד ב{MONTHS_HE[lo[0] - 1]}.")


def insight_owner(df):
    vc = _ranked(df["owner"])
    n = len(df)
    priv = int(vc.get("פרטי", 0))
    company = int(vc.get("חברה", 0))
    dealer = int(vc.get("סוחר", 0))
    if priv / n < 0.5 or company + dealer == 0:
        return None
    return (f"{_pct(priv / n)} מהכלים בבעלות פרטית; {_int(company)} רשומים על שם חברה "
            f"ו-{_int(dealer)} על שם סוחר.")


def insight_origin(origin_rows, n):
    if len(origin_rows) < 3:
        return None
    total = sum(r["n"] for r in origin_rows)
    parts = ", ".join(f"{r['name']} ({_int(r['n'])})" for r in origin_rows[:3])
    return (f"ל-{_int(total)} כלים ({_pct(total / n)}) רשומה מקוריות מיוחדת; "
            f"הנפוצות: {parts}.")


# ── compute ──────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["fleet"])
    n = len(df)
    years = df["year"].dropna().astype(int)
    y0, y1 = int(years.min()), int(years.max())
    classes = _classes(df)

    # ── First road entry, by month ─────────────────────────────────────────
    rd = df["road"].dropna()
    yc = rd.dt.year.value_counts().sort_index()
    start_year = next((int(y) for y, v in yc.items() if v >= SERIES_MIN_SHARE * n), int(yc.index.min()))
    rs = rd[rd.dt.year >= start_year]
    last_m = rs.max()
    months = pd.period_range(pd.Period(f"{start_year}-01", freq="M"), last_m, freq="M")
    mc = rs.value_counts()
    monthly = pd.Series([int(mc.get(p, 0)) for p in months], index=months)
    n_series = int(monthly.sum())
    n_tail = int(len(rd) - n_series)
    n_no_road = int(n - len(rd))
    if len(monthly) > MAX_MONTHLY_POINTS:
        q = monthly.groupby(monthly.index.asfreq("Q")).sum()
        road_chart = {"x": [f"{p.year} Q{p.quarter}" for p in q.index], "y": [int(v) for v in q], "unit": "רבעון"}
    else:
        road_chart = {"x": [f"{p.year}-{p.month:02d}" for p in monthly.index],
                      "y": [int(v) for v in monthly], "unit": "חודש"}
    road_chart["zoom_start"] = max(0, round(100 - 8 * 12 / max(len(monthly), 1) * 100))
    full = monthly.iloc[:-1]   # newest month may be partial
    peak_sorted = full.sort_index().sort_values(ascending=False, kind="stable")
    peak_m = peak_sorted.index[0] if len(peak_sorted) else last_m

    # Year-to-date vs the same months a year earlier (excluding the newest month).
    ytd = None
    last_full = last_m - 1
    ly = last_full.year
    k = last_full.month
    cur_months = [p for p in full.index if p.year == ly and p.month <= k]
    prev_months = [p for p in full.index if p.year == ly - 1 and p.month <= k]
    if len(cur_months) == k and len(prev_months) == k:
        cur, prev = int(full[cur_months].sum()), int(full[prev_months].sum())
        if prev > 0:
            span = (f"{MONTHS_HE[0]}–{MONTHS_HE[k - 1]} {ly}" if k > 1 else f"{MONTHS_HE[0]} {ly}")
            ytd = {"cur": cur, "prev": prev, "ch": cur / prev - 1, "span": span,
                   "prev_label": str(ly - 1)}

    # Month × year heatmap (counts) + seasonality over complete years.
    heat_years = list(range(start_year, last_m.year + 1))
    heat = []
    for yi, yy in enumerate(heat_years):
        for mi in range(12):
            p = pd.Period(f"{yy}-{mi + 1:02d}", freq="M")
            if p <= last_m:
                heat.append([mi, yi, int(monthly.get(p, 0))])
    heat_chart = {"years": [str(y) for y in heat_years], "months": MONTHS_HE, "data": heat,
                  "max": max((c[2] for c in heat), default=0)}
    complete = [yy for yy in heat_years if pd.Period(f"{yy}-12", freq="M") < last_m]
    season = None
    if len(complete) >= 3:
        shares = []
        for yy in complete:
            vals = [int(monthly.get(pd.Period(f"{yy}-{m:02d}", freq="M"), 0)) for m in range(1, 13)]
            tot = sum(vals)
            if tot:
                shares.append([v / tot for v in vals])
        if shares:
            avg = [math.fsum(s[i] for s in shares) / len(shares) for i in range(12)]
            order = sorted(range(12), key=lambda i: (-avg[i], i))
            season = {"hi": (order[0] + 1, avg[order[0]]), "lo": (order[-1] + 1, avg[order[-1]]),
                      "y0": complete[0], "y1": complete[-1]}

    # ── Production year × class ────────────────────────────────────────────
    yv = df.dropna(subset=["year"]).copy()
    yv["year"] = yv["year"].astype(int)
    piv = yv.groupby(["year", "cls"]).size().unstack(fill_value=0)
    all_years = list(range(y0, y1 + 1))
    piv = piv.reindex(index=all_years, columns=classes, fill_value=0)
    years_chart = {"x": [str(y) for y in all_years],
                   "series": [{"name": _class_label(c), "data": [int(v) for v in piv[c]]} for c in classes]}
    coh = yv["year"].map(lambda y: 1985 if y < 1990 else y // 5 * 5)
    ct = yv.groupby([coh, "cls"]).size().unstack(fill_value=0).reindex(columns=classes, fill_value=0).sort_index()
    t_years = [{"name": (f"עד {c + 4}" if c < 1990 else f"\u2066{c}–{min(c + 4, y1)}\u2069"),
                "total": _int(ct.loc[c].sum()),
                "cols": [_int(ct.loc[c, k]) for k in classes]} for c in ct.index]

    # Class share by production year (from the series start).
    mix_years = [y for y in all_years if y >= start_year]
    share_by_year = {}
    mix_series = []
    for c in classes:
        data = []
        for y in mix_years:
            tot = int(piv.loc[y].sum())
            v = piv.loc[y, c] / tot if tot else 0.0
            share_by_year.setdefault(y, {})[c] = v
            data.append(round(v * 100, 1))
        mix_series.append({"name": _class_label(c), "data": data})
    class_mix = {"x": [str(y) for y in mix_years], "series": mix_series}
    t_mix = [{"name": str(y), "cols": [f"{share_by_year[y][c] * 100:.1f}" for c in classes]}
             for y in mix_years[-TABLE_YEARS:]]

    # Class summary: size, power ceiling, typical engine.
    ceilings = {}
    t_classes = []
    for c in classes:
        sub = df[df["cls"] == c]
        h = sub["hp"].dropna()
        cv = sub.loc[sub["cc"] > 10, "cc"]
        if len(h):
            ceilings[c] = float(h.max())
        t_classes.append({
            "name": _class_label(c), "count": _int(len(sub)), "share": f"{len(sub) / n * 100:.1f}",
            "hp_med": _num(h.median()) if len(h) else "—",
            "hp_rng": f"\u2066{_num(h.quantile(0.01))}–{_num(h.quantile(0.99))}\u2069" if len(h) else "—",
            "cc_med": _int(cv.median()) if len(cv) else "—",
        })

    # ── Electric ───────────────────────────────────────────────────────────
    ev_years = mix_years
    ev_counts = yv[yv["fuel"] == ELECTRIC].groupby("year").size()
    tot_counts = yv.groupby("year").size()
    ev_by_year = {}
    for y in ev_years:
        tot = int(tot_counts.get(y, 0))
        e = int(ev_counts.get(y, 0))
        ev_by_year[y] = {"n": tot, "ev": e, "share": e / tot if tot else 0.0}
    ev_chart = {"x": [str(y) for y in ev_years],
                "ev": [ev_by_year[y]["ev"] for y in ev_years],
                "share": [round(ev_by_year[y]["share"] * 100, 2) for y in ev_years]}
    t_ev = [{"name": str(y), "count": _int(ev_by_year[y]["ev"]), "share": f"{ev_by_year[y]['share'] * 100:.1f}"}
            for y in ev_years[-TABLE_YEARS:]]
    n_ev = int((df["fuel"] == ELECTRIC).sum())
    ev_brands = _ranked(df.loc[df["fuel"] == ELECTRIC, "brand"])
    top_ev_brand = (ev_brands.index[0], int(ev_brands.iloc[0])) if len(ev_brands) else None

    # ── Brands, models, countries ──────────────────────────────────────────
    b_names, b_vals = _top_other(df["brand"], TOP_BRANDS)
    n_brands = int(df["brand"].nunique())

    def rank_rows(names, vals, total=n):
        return [{"name": a, "count": _int(b), "share": f"{b / total * 100:.1f}"} for a, b in zip(names, vals)]

    mix_brands = list(_ranked(df["brand"]).head(MIX_BRANDS).index)
    by_yb = yv.groupby(["year", "brand"]).size()
    brand_mix_series = []
    bm_share = {}
    for b in mix_brands:
        data = []
        for y in mix_years:
            tot = int(tot_counts.get(y, 0))
            v = int(by_yb.get((y, b), 0)) / tot if tot else 0.0
            bm_share[(y, b)] = v
            data.append(round(v * 100, 1))
        brand_mix_series.append({"name": b, "data": data})
    brand_mix = {"x": [str(y) for y in mix_years], "series": brand_mix_series}
    t_bmix = [{"name": str(y), "cols": [f"{bm_share[(y, b)] * 100:.1f}" for b in mix_brands]}
              for y in mix_years[-TABLE_YEARS:]]

    mv = _ranked(df.loc[df["model_code"] != "", "model"]).head(TOP_MODELS)
    model_rows = [{"name": k, "count": _int(v), "share": f"{v / n * 100:.1f}"} for k, v in mv.items()]
    models_chart = {"names": list(mv.index), "values": [int(v) for v in mv]}
    n_models = int(df.loc[df["model_code"] != "", "model"].nunique())

    c_names, c_vals = _top_other(df["country"], TOP_COUNTRIES)

    # ── Engine volume ──────────────────────────────────────────────────────
    cc_pos = df.loc[df["cc"] > 0, "cc"]
    cb = cc_pos.map(_bin_cc).value_counts()
    cc_labels = [b[2] for b in CC_BINS]
    cc_chart = {"names": cc_labels, "values": [int(cb.get(b, 0)) for b in cc_labels]}
    t_cc = rank_rows(cc_labels, cc_chart["values"], total=max(len(cc_pos), 1))
    n_cc_zero = int(n - len(cc_pos))
    cc_zero_ev = int(((df["cc"].fillna(0) <= 0) & (df["fuel"] == ELECTRIC)).sum())
    cc_med = int(cc_pos.median()) if len(cc_pos) else 0
    cc_mode = int(cc_pos.value_counts().sort_index().sort_values(ascending=False, kind="stable").index[0]) if len(cc_pos) else 0

    # ── Power by leading brand ─────────────────────────────────────────────
    box_brands = list(_ranked(df["brand"]).head(BOX_BRANDS).index)
    box, t_box = [], []
    for b in box_brands:
        h = df.loc[df["brand"] == b, "hp"].dropna()
        if len(h) == 0:
            qs = [0.0] * 5
        else:
            qs = [float(h.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
        box.append([round(v, 1) for v in qs])
        t_box.append({"name": b, "q1": _num(qs[1]), "med": _num(qs[2]), "q3": _num(qs[3])})
    order = sorted(range(len(box_brands)), key=lambda i: (box[i][2], box[i][1], box_brands[i]))
    box_chart = {"names": [box_brands[i] for i in order], "data": [box[i] for i in order]}
    t_box = [t_box[i] for i in order]
    hp_all = df["hp"].dropna()
    hp_med = float(hp_all.median()) if len(hp_all) else 0.0

    # ── Vehicle type, ownership, origin ────────────────────────────────────
    tv = _ranked(df["vtype"])
    t_types = rank_rows(list(tv.index), [int(v) for v in tv])
    ov = _ranked(df["owner"])
    owner_chart = {"names": list(ov.index), "values": [int(v) for v in ov]}
    t_owner = rank_rows(list(ov.index), [int(v) for v in ov])
    orv = _ranked(df.loc[df["origin"] != "", "origin"])
    origin_rows = [{"name": k, "n": int(v)} for k, v in orv.items()]
    t_origin = rank_rows([r["name"] for r in origin_rows], [r["n"] for r in origin_rows])

    # ── KPIs ───────────────────────────────────────────────────────────────
    if ytd is None:
        ytd_tone, ytd_display = "brand", "—"
    else:
        r = round(ytd["ch"] * 100, 1)
        if r == 0:
            ytd_display = "ללא שינוי"
        else:
            ytd_display = ("+" if r > 0 else "−") + f"{abs(r):.1f}%"
        ytd_tone = "brand" if abs(ytd["ch"]) < TREND_BAND else ("info" if ytd["ch"] > 0 else "warn")
    ev_cur = ev_by_year.get(y1, {"share": 0.0, "ev": 0})
    ev_prev = ev_by_year.get(y1 - 1)
    ev_tone = "ok" if ev_prev and ev_cur["share"] >= ev_prev["share"] + 0.005 else "brand"
    young_share = (years >= y1 - YOUNG_YEARS + 1).mean() if len(years) else 0.0

    # ── Insights ───────────────────────────────────────────────────────────
    shift_cls = None
    if y1 in share_by_year and (y1 - EV_SPAN) in share_by_year:
        deltas = sorted(((abs(share_by_year[y1][c] - share_by_year[y1 - EV_SPAN][c]), c) for c in classes),
                        key=lambda t: (-t[0], t[1]))
        shift_cls = deltas[0][1] if deltas else None
    rules = [
        ("ytd", insight_ytd(ytd)),
        ("young", insight_young(df, y1)),
        ("ev", insight_ev(ev_by_year, y1, top_ev_brand)),
        ("class_shift", insight_shift(share_by_year, y1, shift_cls) if shift_cls else None),
        ("brand", insight_brand(df)),
        ("country", insight_country(df)),
        ("power", insight_power(df, ceilings)),
        ("season", insight_season(season)),
        ("owner", insight_owner(df)),
        ("origin", insight_origin(origin_rows, n)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    ceil_parts = [f"{c} — עד {_num(ceilings[c])} כ״ס" for c in ("L1", "L2") if c in ceilings]
    ceil_text = "; ".join(ceil_parts)
    partial_note = f" החודש האחרון בנתונים ({_m_he(last_m)}) עשוי להיות חלקי."
    tail_note = (f" {_int(n_tail)} כלים ותיקים יותר (מלפני {start_year}) אינם בתרשים." if n_tail else "")

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} כלי רכב דו-גלגליים פעילים — אופנועים, קטנועים ותלת-אופנועים — "
                           f"מ-{_int(n_brands)} יצרנים, שנות ייצור \u2066{y0}–{y1}\u2069. "
                           f"{_pct(young_share)} מהם יוצרו ב-{YOUNG_YEARS} השנים האחרונות שבנתונים, "
                           f"והחשמליים הם {_pct(ev_cur['share'])} מכלי שנת {y1}."),
            "dataset_kind": "registry",
            "related_ids": [
                "aef33db6-37c4-4026-82ba-6c1237bd2cf0",
                "9b2ac550-d4bf-4da6-a1f2-bcfd57ed5e7f",
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                "35c791ca-8db2-4657-8c6f-eb092147a6bb",
            ],
            "suggested_tags": ["אופנועים", "רכב דו-גלגלי", "קטנועים", "צי הרכב", "רכב חשמלי", "תחבורה"],
            "temporal_coverage": f"{y0}/{y1}",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "ytd": {"value": round(ytd["ch"], 4) if ytd else None, "display": ytd_display, "tone": ytd_tone},
            "ev": {"value": round(ev_cur["share"], 4), "display": _pct(ev_cur["share"]), "tone": ev_tone},
            "hp": {"value": round(hp_med, 1), "display": _num(hp_med), "tone": "brand"},
        },
        "charts": {
            "road": road_chart,
            "heat": heat_chart,
            "years": years_chart,
            "class_mix": class_mix,
            "ev": ev_chart,
            "brands": {"names": b_names, "values": b_vals},
            "brand_mix": brand_mix,
            "models": models_chart,
            "countries": {"names": c_names, "values": c_vals},
            "cc": cc_chart,
            "box": box_chart,
            "owner": owner_chart,
        },
        "tables": {
            "class_cols": [_class_label(c) for c in classes],
            "years": t_years,
            "mix": t_mix,
            "classes": t_classes,
            "ev": t_ev,
            "brands": rank_rows(b_names, b_vals),
            "bmix_cols": mix_brands,
            "bmix": t_bmix,
            "models": model_rows,
            "countries": rank_rows(c_names, c_vals),
            "cc": t_cc,
            "box": t_box,
            "types": t_types,
            "owner": t_owner,
            "origin": t_origin,
        },
        "insights": insights,
        "labels": {
            "lede": (f"המאגר מונה {_int(n)} כלי רכב דו-גלגליים פעילים הרשומים במשרד התחבורה: "
                     f"אופנועים, קטנועים, תלת-אופנועים ורכבים זעירים, שנות ייצור \u2066{y0}–{y1}\u2069. "
                     f"זו תמונת הצי הפעיל היום — כלים שנגרעו מהמרשם אינם בו, ולכן שנים ותיקות "
                     f"מיוצגות חלקית."),
            "total_kpi": "כלי רכב דו-גלגליים פעילים",
            "ytd_kpi": (f"עלייה לכביש ב{ytd['span']} לעומת {ytd['prev_label']}" if ytd
                        else "שינוי בעלייה לכביש לעומת השנה הקודמת"),
            "ev_kpi": f"חלק החשמליים מכלי שנת ייצור {y1}",
            "hp_kpi": "הספק חציוני (כוח סוס)",
            "road_note": (f"מספר הכלים הפעילים לפי {road_chart['unit']} העלייה לכביש, מ-{start_year}. "
                          f"השיא — {_m_he(peak_m)} ({_int(peak_sorted.iloc[0]) if len(peak_sorted) else 0} כלים). "
                          f"שנת העלייה לכביש זהה בנתונים לשנת הייצור.{tail_note}{partial_note}"),
            "road_aria": f"תרשים קו: כלי רכב דו-גלגליים פעילים לפי {road_chart['unit']} עלייה לכביש, \u2066{start_year}–{last_m.year}\u2069.",
            "heat_note": ("כל תא — מספר הכלים הפעילים שעלו לכביש באותו חודש. "
                          + (f"בשנים \u2066{season['y0']}–{season['y1']}\u2069 החודש החזק בממוצע הוא "
                             f"{MONTHS_HE[season['hi'][0] - 1]} והחלש — {MONTHS_HE[season['lo'][0] - 1]}."
                             if season else "")),
            "heat_aria": f"מפת חום: עלייה לכביש לפי חודש ושנה, \u2066{start_year}–{last_m.year}\u2069.",
            "years_note": (f"שנות ייצור \u2066{y0}–{y1}\u2069, כל עמודה מחולקת לפי קטגוריית הכלי. "
                           f"{_pct(young_share)} מהצי יוצרו ב-{YOUNG_YEARS} השנים האחרונות שבנתונים."),
            "years_aria": f"תרשים עמודות: כלי רכב פעילים לפי שנת ייצור וקטגוריה, \u2066{y0}–{y1}\u2069.",
            "years_caption": "כלי רכב לפי מחזור שנות ייצור וקטגוריה.",
            "mix_note": (f"חלקה של כל קטגוריה מכלי כל שנת ייצור, \u2066{start_year}–{y1}\u2069. "
                         f"הקטגוריה נקבעת לפי ההספק: {ceil_text}; L3 — מעליהן."),
            "mix_aria": f"תרשים שטח מוערם: חלק כל קטגוריה מכלי שנת הייצור, \u2066{start_year}–{y1}\u2069.",
            "mix_caption": f"חלק כל קטגוריה (%) ב-{min(TABLE_YEARS, len(mix_years))} שנות הייצור האחרונות.",
            "classes_caption": "הקטגוריות: מספר כלים, הספק ונפח מנוע (טווח ההספק — אחוזון 1 עד 99).",
            "classes_rng_head": "טווח הספק (כ״ס)",
            "ev_note": (f"{_int(n_ev)} כלי רכב חשמליים בצי. העמודות — מספר החשמליים בכל שנת ייצור; "
                        f"הקו — חלקם מכלל כלי אותה שנה."),
            "ev_aria": f"תרשים משולב: כלי רכב חשמליים וחלקם לפי שנת ייצור, \u2066{start_year}–{y1}\u2069.",
            "ev_caption": f"חשמליים לפי שנת ייצור, {min(TABLE_YEARS, len(ev_years))} השנים האחרונות.",
            "brands_note": (f"{_int(n_brands)} יצרנים בצי. שם היצרן מאוחד מכל ארצות המפעל, "
                            f"ושמות יצרן שהוחלפו במרשם לאותן משפחות דגמים אוחדו (קואנג יאנג עם קימקו, "
                            f"אס ווי אם עם סאן יאנג)."),
            "brands_aria": f"תרשים עמודות: {TOP_BRANDS} היצרנים המובילים.",
            "bmix_note": (f"חלקם של {MIX_BRANDS} היצרנים הגדולים מכלי כל שנת ייצור, \u2066{start_year}–{y1}\u2069. "
                          f"לחיצה על שם יצרן במקרא מסתירה אותו."),
            "bmix_aria": f"תרשים קו: חלקם של {MIX_BRANDS} היצרנים הגדולים לפי שנת ייצור.",
            "bmix_caption": f"חלק היצרן (%) ב-{min(TABLE_YEARS, len(mix_years))} שנות הייצור האחרונות.",
            "models_note": (f"קוד הדגם כפי שנרשם אצל היצרן ({_int(n_models)} צירופי יצרן ודגם בצי). "
                            f"אותו דגם מסחרי עשוי להופיע בכמה קודים לפי שנה וגרסה."),
            "models_aria": f"תרשים עמודות: {TOP_MODELS} קודי הדגם הנפוצים.",
            "countries_note": "ארץ המפעל שבו יוצר הכלי — לא ארץ המותג.",
            "countries_aria": f"תרשים עמודות: {TOP_COUNTRIES} ארצות הייצור המובילות.",
            "cc_note": (f"נפח המנוע בסמ״ק. החציון {_int(cc_med)} סמ״ק, והנפח הנפוץ ביותר — {_int(cc_mode)}. "
                        f"{_int(n_cc_zero)} כלים ללא נפח רשום אינם בתרשים ({_int(cc_zero_ev)} מהם חשמליים)."),
            "cc_aria": "תרשים עמודות: כלי רכב לפי טווח נפח מנוע.",
            "box_note": (f"{BOX_BRANDS} היצרנים הנפוצים, מסודרים מההספק הנמוך לגבוה. התיבה — הרבעון התחתון "
                         f"עד העליון, הקו — החציון, השפמים — אחוזון 5 עד 95. "
                         f"ההספק החציוני בכלל הצי {_num(hp_med)} כ״ס."),
            "box_aria": f"תרשים תיבה: הספק בכוח סוס לפי {BOX_BRANDS} היצרנים המובילים.",
            "types_caption": "כלי רכב לפי סוג.",
            "owner_aria": "תרשים עמודות: כלי רכב לפי סוג הבעלות.",
            "origin_caption": "כלי רכב לפי מקוריות רשומה.",
            "origin_note": (f"מקוריות רשומה רק ל-{_int(sum(r['n'] for r in origin_rows))} כלים; "
                            f"לשאר השדה ריק." if origin_rows else "לא רשומה מקוריות לאף כלי."),
        },
        "flags": {"origin": bool(origin_rows), "no_road": n_no_road},
    }
