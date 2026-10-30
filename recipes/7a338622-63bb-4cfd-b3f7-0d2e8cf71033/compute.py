"""מספרי רישוי של כלי רכב פרטיים ומסחריים: the ACTIVE car register.

One row per active private car (production year 1996+) or light commercial
vehicle (up to 3,500 kg, production year 1998+). About 4.2M rows, so the
recipe fetches only the columns it reads (recipe.json `columns`).

- It is a snapshot of the live register: every "by year" view counts
  vehicles that are STILL ACTIVE, so older production years are thinned by
  scrapping. The page says so.
- `moed_aliya_lakvish` ("YYYY-M") is the month of first road entry. It is
  empty for most pre-2009 vehicles; the monthly series starts at the first
  year that carries a meaningful share of the fleet.
- The newest road-entry month is treated as possibly partial (the export can
  land mid-month). Trend rules use only the months before it. "Now" is never
  the clock: the reference date is the first day of the newest road-entry
  month, and licence expiry is measured against it.
- `tozeret_nm` is "<maker> <plant country>", the country often truncated
  ("גרמנ", "ד.קוריא"). It is split into a brand and a country; an
  ambiguous or missing country is shown as "לא צוין".
- Licence plates and VINs are never fetched or shown.
"""
import math
import re

import pandas as pd

OTHER = "אחר"
UNKNOWN = "לא צוין"
TOP_BRANDS = 15
TOP_MODELS = 15
TOP_COUNTRIES = 12
MIX_COUNTRIES = 6
TOP_COLORS_RAW = 12
TABLE_YEARS = 12          # year-by-year fallback tables show the latest N production years
SERIES_MIN_SHARE = 0.005  # monthly / mix series start at the first year with >=0.5% of the fleet
TREND_BAND = 0.05         # +-5% year on year counts as "no clear change"
SHIFT_PP = 0.05           # a share moving >=5 points over the comparison span
SPAN = 5                  # compare the latest production year with this many years earlier
MAX_MONTHLY_POINTS = 480  # beyond this the road-entry series switches to quarters
SEASON_RATIO = 1.25       # a month this many x the 1/12 average is a clear peak
EXPIRED_WARN = 0.05       # expired-licence share at/above this is shown as a caution
SAFETY_MIN_COVER = 0.5    # safety-level views use production years with >=50% of rows rated
SAFETY_HIGH = 6           # "high" safety-equipment level (scale 0-8)
CLEAN_MAX = 4             # pollution groups 1-4 = cleanest
DIRTY_GROUP = 15          # the most polluting group

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

DEGEM = {"P": "פרטי", "M": "מסחרי"}
EV = "חשמלי"
HYBRID = "היברידי בנזין"
FUEL_MAP = {
    "בנזין": "בנזין",
    "דיזל": "דיזל",
    "חשמל": EV,
    "חשמל/בנזין": HYBRID,
    "חשמל/דיזל": "היברידי דיזל",
    'גפמ"': "גפ״מ",
    "גפמ": "גפ״מ",
}
FUEL_ORDER = ["בנזין", "דיזל", HYBRID, EV, "היברידי דיזל", "גפ״מ"]
OWNER_ORDER = ["פרטי", "ליסינג", "חברה", "השכרה", "סוחר"]

# Plant countries as the register spells them (often truncated). A trailing
# token is a country when it is a prefix of exactly one of these.
COUNTRIES = {
    "יפן": "יפן", "צ'כיה": "צ'כיה", "טורקיה": "טורקיה", "תורכיה": "טורקיה",
    "קוריאה": "דרום קוריאה", "סין": "סין", "ספרד": "ספרד", "צרפת": "צרפת",
    "אנגליה": "אנגליה", "סלובקיה": "סלובקיה", "גרמניה": "גרמניה",
    "הונגריה": "הונגריה", "תאילנד": "תאילנד", "ארהב": "ארה״ב", "הודו": "הודו",
    "מקסיקו": "מקסיקו", "רומניה": "רומניה", "בלגיה": "בלגיה", "פולין": "פולין",
    "פורטוגל": "פורטוגל", "קנדה": "קנדה", "איטליה": "איטליה", "שבדיה": "שבדיה",
    "מרוקו": "מרוקו", "הולנד": "הולנד", "סלובניה": "סלובניה", "אוסטריה": "אוסטריה",
    "אפריקה": "דרום אפריקה", "סרביה": "סרביה", "פינלנד": "פינלנד",
    "רוסיה": "רוסיה", "ישראל": "ישראל", "ארגנטינה": "ארגנטינה",
}
# Whole maker entries whose last word is not a country (or looks like one).
MAKER_OVERRIDES = {
    "לינק אנד קו": ("לינק אנד קו", UNKNOWN),
    "מרוטי סוזוקי": ("סוזוקי", "הודו"),
    "סוזוקי-מרוטי": ("סוזוקי", "הודו"),
}
BRAND_ALIASES = {
    "אודי": "אאודי", "דאציה": "דאצ'יה", "לנציה": "לנצ'יה", "גיפ": "ג'יפ",
    "ג'יפ אוונג'ר": "ג'יפ", "ג'י.אם.סי": "ג'י.אמ.סי", "דימלרקריזלר": "דיימלר קרייזלר",
    "האמר ג.מ.": "האמר", "סמארט ג'.מ.ב.ה": "סמארט", "פיאט/מדייר סוז": "פיאט",
    "ניאו רכב": "ניאו",
}

# Colour families: the family whose keyword appears EARLIEST in the colour
# name wins ("אפור כחול מטלי" is grey, "כחול פנינה" blue). Unmatched names
# flow to "אחר".
COLOR_FAMILIES = [
    ("לבן", ["לבן", "שנהב", "שן פיל", "קרם"], "#f4f4f2"),
    ("כסוף", ["כסף", "כסוף", "פלטינה"], "#c0c6cf"),
    ("אפור", ["אפור", "פלדה"], "#7a8491"),
    ("שחור", ["שחור"], "#1f2328"),
    ("כחול", ["כחול", "תכלת", "טורקיז", "אקווה"], "#2f6db5"),
    ("אדום", ["אדום", "בורדו", "יין", "ורוד", "רוז"], "#c2363b"),
    ("חום ובז׳", ["בז", "חום", "קפה", "ברונזה", "סהרה", "נחושת", "זהב", "זהוב"], "#a07850"),
    ("ירוק", ["ירוק", "ירקרק", "זית"], "#3f8a4f"),
    ("צהוב וכתום", ["צהוב", "כתום", "מנדרינה", "חרדל"], "#e8b02a"),
    ("סגול", ["סגול", "חציל"], "#6b4c9a"),
]
COLOR_OTHER_HEX = "#d9dee6"


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _vav(word):
    """Hebrew "and" prefix: glued to a Hebrew word, "ו-" before Latin/digits."""
    w = str(word)
    return f"ו{w}" if w[:1] and "\u05d0" <= w[0] <= "\u05ea" else f"ו-{w}"


def _pct_floor(x):
    return "פחות מ-0.1%" if x < 0.001 else _pct(x)


def _ranked(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _top_other(series, n):
    vc = _ranked(series)
    top = vc.head(n)
    rest = int(vc.iloc[n:].sum())
    names, values = [str(x) for x in top.index], [int(v) for v in top]
    if rest:
        names.append(OTHER)
        values.append(rest)
    return names, values


def _rank_rows(names, values, total):
    return [{"name": nm, "count": _int(v), "share": f"{v / total * 100:.1f}" if total else "0.0"}
            for nm, v in zip(names, values)]


def _country_of(token):
    t = token.replace('"', "").rstrip(".'")
    if t.startswith("ד."):
        t = t[2:]
    if len(t) < 2:
        return None
    hits = {v for k, v in COUNTRIES.items() if k.startswith(t)}
    if len(hits) == 1:
        return hits.pop()
    if hits:
        return UNKNOWN  # ambiguous truncation ("סלוב", "פו"): a country, but which is unclear
    return None


def _split_maker(name):
    s = name.strip()
    if s in MAKER_OVERRIDES:
        return MAKER_OVERRIDES[s]
    toks = [t for t in re.split(r"[\s_\-]+", s) if t]
    country = UNKNOWN
    if len(toks) > 1:
        c = _country_of(toks[-1])
        if c is not None:
            country = c
            toks = toks[:-1]
            if len(toks) > 1 and toks[-1] in ("ד.", "ד"):
                toks = toks[:-1]
    brand = " ".join(toks) or UNKNOWN
    return BRAND_ALIASES.get(brand, brand), country


def _color_family(name):
    best = None
    for i, (fam, keys, _hex) in enumerate(COLOR_FAMILIES):
        for k in keys:
            p = name.find(k)
            if p >= 0 and (best is None or (p, i) < best[:2]):
                best = (p, i, fam)
    return best[2] if best else OTHER


def _umap(series, fn):
    """Apply `fn` once per distinct value. The result shares one object per
    value instead of allocating a new string per row: on 4M rows that is the
    difference between ~35MB and ~400MB per column."""
    return series.map({u: fn(u) for u in series.unique()})


def _road_month(v):
    t = pd.to_datetime(v.strip() + "-1", errors="coerce", format="%Y-%m-%d")
    return t


def _day(v):
    return pd.to_datetime(v.strip(), errors="coerce", format="%Y-%m-%d")


def _prepare(df):
    mk = {n: _split_maker(n) for n in df["tozeret_nm"].unique()}
    road = pd.to_datetime(_umap(df["moed_aliya_lakvish"], _road_month))
    return pd.DataFrame({
        "degem": _umap(df["sug_degem"], lambda v: DEGEM.get(v.strip(), UNKNOWN)),
        "brand": df["tozeret_nm"].map({k: v[0] for k, v in mk.items()}),
        "country": df["tozeret_nm"].map({k: v[1] for k, v in mk.items()}),
        "model_name": _umap(df["kinuy_mishari"], lambda v: re.sub(r"\s+", " ", v.strip())),
        "year": pd.to_numeric(_umap(df["shnat_yitzur"], lambda v: v.strip()), errors="coerce"),
        "fuel": _umap(df["sug_delek_nm"], lambda v: FUEL_MAP.get(v.strip(), v.strip() or UNKNOWN)),
        "owner": _umap(df["baalut"], lambda v: v.strip() or UNKNOWN),
        "color": _umap(df["tzeva_rechev"], lambda v: v.strip() or UNKNOWN),
        "color_fam": _umap(df["tzeva_rechev"], lambda v: _color_family(v.strip())),
        "road": road.dt.to_period("M"),
        "tokef": pd.to_datetime(_umap(df["tokef_dt"], _day)),
        "zihum": pd.to_numeric(_umap(df["kvutzat_zihum"], lambda v: v.strip()), errors="coerce"),
        "safety": pd.to_numeric(_umap(df["ramat_eivzur_betihuty"], lambda v: v.strip()), errors="coerce"),
    })


def _ordered(present, order):
    present = set(present)
    return [c for c in order if c in present] + sorted(present - set(order))


def _share_series(df, col, cats, years):
    """{cat: [share% per year]} and {year: {cat: share}} over production years."""
    ct = df.groupby(["year", col]).size().unstack(fill_value=0).reindex(index=years, columns=cats, fill_value=0)
    tot = ct.sum(axis=1)
    shares = {}
    series = []
    for c in cats:
        vals = []
        for y in years:
            v = float(ct.loc[y, c] / tot.loc[y]) if tot.loc[y] else 0.0
            shares.setdefault(y, {})[c] = v
            vals.append(round(v * 100, 1))
        series.append({"name": c, "data": vals})
    return series, shares, ct


def yv_road_gap(df):
    """Newest production year in which most vehicles carry no road-entry month."""
    y = pd.to_numeric(df["year"], errors="coerce")
    miss = df["road"].isna().groupby(y).mean()
    gap = [int(k) for k, v in miss.items() if v > 0.5 and k >= 0]
    return max(gap) if gap else None


def _share_table(shares, cats, years):
    return [{"name": str(y), "cols": [f"{shares[y][c] * 100:.1f}" for c in cats]} for y in years]


# ── insight rules ────────────────────────────────────────────────────────────

def insight_ytd(ytd):
    if ytd is None:
        return None
    cur, prev, ch = ytd["cur"], ytd["prev"], ytd["ch"]
    if abs(ch) < TREND_BAND:
        return (f"ב{ytd['span']} עלו לכביש {_int(cur)} כלי רכב שעדיין פעילים, בדומה לתקופה המקבילה "
                f"ב-{ytd['prev_label']} ({_int(prev)}). {ytd['partial_note']}")
    word = "יותר" if ch > 0 else "פחות"
    return (f"ב{ytd['span']} עלו לכביש {_int(cur)} כלי רכב שעדיין פעילים, {_pct(abs(ch))} {word} "
            f"מאשר בתקופה המקבילה ב-{ytd['prev_label']} ({_int(prev)}). {ytd['partial_note']}")


def insight_ev(fuel_shares, y1):
    cur = fuel_shares.get(y1, {})
    old = fuel_shares.get(y1 - SPAN, {})
    if not cur or not old:
        return None
    e1, e0 = cur.get(EV, 0.0), old.get(EV, 0.0)
    h1, h0 = cur.get(HYBRID, 0.0), old.get(HYBRID, 0.0)
    if e1 + h1 < e0 + h0 + SHIFT_PP:
        return None
    return (f"מכלי שנת ייצור {y1}, {_pct(e1)} חשמליים ו-{_pct(h1)} היברידיים (בנזין-חשמל), "
            f"לעומת {_pct(e0)} ו-{_pct(h0)} בשנת ייצור {y1 - SPAN}.")


def insight_brand(df):
    vc = _ranked(df["brand"])
    if len(vc) < 3:
        return None
    (b1, n1), (b2, n2), (b3, n3) = list(vc.items())[:3]
    n = len(df)
    if n1 / n < 0.05:
        return None
    return (f"היצרן הנפוץ ביותר הוא {b1} עם {_int(n1)} כלי רכב ({_pct(n1 / n)}), לפני {b2} ({_int(n2)}) "
            f"{_vav(b3)} ({_int(n3)}). שלושתם יחד הם {_pct((n1 + n2 + n3) / n)} מהצי הפעיל.")


def insight_country(country_shares, y1, top_country_all):
    cur = country_shares.get(y1, {})
    old = country_shares.get(y1 - SPAN, {})
    if not cur or not old:
        return None
    gains = sorted(((cur.get(c, 0.0) - old.get(c, 0.0), c) for c in cur if c not in (UNKNOWN, OTHER)),
                   key=lambda t: (-t[0], t[1]))
    if not gains or gains[0][0] < SHIFT_PP:
        return None
    g, c = gains[0]
    text = (f"{c} היא ארץ הייצור שחלקה גדל יותר מכול: {_pct(cur[c])} מכלי שנת ייצור {y1} שארץ ייצורם מצוינת, "
            f"לעומת {_pct(old.get(c, 0.0))} בשנת ייצור {y1 - SPAN}.")
    if top_country_all and top_country_all[0] != c:
        text += f" בצי כולו מובילה עדיין {top_country_all[0]} ({_pct(top_country_all[1])})."
    return text


def insight_lease(owner_shares, y1, owner_all, n):
    cur = owner_shares.get(y1, {})
    if not cur:
        return None
    lease = cur.get("ליסינג", 0.0)
    rent = cur.get("השכרה", 0.0)
    comp = cur.get("חברה", 0.0)
    biz = lease + rent + comp
    if biz < 0.1:
        return None
    priv_all = owner_all.get("פרטי", 0) / n if n else 0.0
    return (f"מכלי שנת ייצור {y1}, {_pct(biz)} רשומים על שם חברת ליסינג, חברת השכרה או חברה "
            f"(ליסינג לבדו {_pct(lease)}). בצי כולו {_pct(priv_all)} בבעלות פרטית.")


def insight_season(season):
    if season is None:
        return None
    hi, lo = season["hi"], season["lo"]
    if hi[1] < SEASON_RATIO / 12:
        return None
    return (f"בשנים {season['y0']}-{season['y1']} עלו לכביש בממוצע {_pct(hi[1])} מכלי הרכב של כל שנה "
            f"ב{MONTHS_HE[hi[0] - 1]}, לעומת {_pct(lo[1])} בלבד ב{MONTHS_HE[lo[0] - 1]}.")


def insight_color(fam_all, fam_new, y1, n, n_new):
    if not n or not n_new:
        return None
    top = sorted(fam_all.items(), key=lambda t: (-t[1], t[0]))
    if not top or top[0][0] == OTHER:
        return None
    f, v = top[0]
    share = v / n
    if share < 0.2:
        return None
    new_share = fam_new.get(f, 0) / n_new
    return (f"{f} הוא צבע הרכב הנפוץ בישראל: {_pct(share)} מהצי הפעיל, "
            f"ו-{_pct(new_share)} מכלי שנת ייצור {y1}.")


def insight_expired(expired, n, ref_label):
    if not n or expired <= 0:
        return None
    share = expired / n
    if share < 0.01:
        return None
    return (f"ל-{_int(expired)} כלי רכב ({_pct(share)}) רשום תוקף רישיון שפג לפני {ref_label}, "
            f"אף שהם עדיין מופיעים במאגר כלי הרכב הפעילים.")


def insight_pollution(z_new, z_old, y1, y0):
    if not z_new or not z_old:
        return None
    clean1, dirty1 = z_new
    clean0, dirty0 = z_old
    if clean1 < clean0 + SHIFT_PP:
        return None
    return (f"בקבוצות זיהום האוויר הנקיות (1 עד {CLEAN_MAX}) נמצאים {_pct(clean1)} מכלי שנת ייצור {y1} "
            f"שקיבלו דירוג, לעומת {_pct(clean0)} בשנת ייצור {y0}. בקבוצה {DIRTY_GROUP}, המזהמת ביותר, "
            f"{_pct(dirty1)} לעומת {_pct(dirty0)}.")


def insight_safety(safe_high, years):
    if len(years) < 3:
        return None
    y0, y1 = years[0], years[-1]
    h0, h1 = safe_high[y0], safe_high[y1]
    if h1 < h0 + SHIFT_PP:
        return None
    return (f"רמת אבזור בטיחותי {SAFETY_HIGH} ומעלה (מתוך 8) יש ל-{_pct(h1)} מכלי שנת ייצור {y1} "
            f"שקיבלו דירוג, לעומת {_pct_floor(h0)} בשנת ייצור {y0}.")


def insight_commercial(degem_counts, n):
    m = degem_counts.get("מסחרי", 0)
    if not n or m < 1000:
        return None
    return (f"{_int(m)} מכלי הרכב במאגר ({_pct(m / n)}) רשומים כמסחריים עד 3,500 ק״ג, "
            f"והשאר ({_int(n - m)}) פרטיים.")


# ── compute ──────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["fleet"])
    frames.clear()
    n = len(df)
    # Rows without a parseable production year are left out of the by-year views.
    df["year"] = df["year"].fillna(-1).astype(int)
    yv = df[df["year"] >= 0] if (df["year"] < 0).any() else df
    y_min, y1 = int(yv["year"].min()), int(yv["year"].max())
    all_years = list(range(y_min, y1 + 1))
    yc_all = yv["year"].value_counts()
    mix_start = next((y for y in all_years if yc_all.get(y, 0) >= SERIES_MIN_SHARE * n), y_min)
    mix_years = [y for y in all_years if y >= mix_start]
    # Insights compare the newest production year with enough cars: at a year
    # rollover the newest year may hold only a few dozen early arrivals.
    y_ins = next((y for y in reversed(all_years) if yc_all.get(y, 0) >= max(1000, SERIES_MIN_SHARE * n)), y1)
    partial_year = (f" שנת ייצור {y1} עדיין חלקית ({_int(yc_all.get(y1, 0))} כלי רכב)."
                    if y_ins < y1 else "")
    tbl_years = mix_years[-TABLE_YEARS:]

    # ── First road entry, by month ─────────────────────────────────────────
    rd = df["road"].dropna()
    ryc = rd.dt.year.value_counts().sort_index()
    start_year = next((int(y) for y, v in ryc.items() if v >= SERIES_MIN_SHARE * n), int(ryc.index.min()))
    rs = rd[rd.dt.year >= start_year]
    last_m = rs.max()
    ref_label = f"{MONTHS_HE[last_m.month - 1]} {last_m.year}"
    ref_ts = last_m.to_timestamp()
    months = pd.period_range(pd.Period(f"{start_year}-01", freq="M"), last_m, freq="M")
    mc = rs.value_counts()
    monthly = pd.Series([int(mc.get(p, 0)) for p in months], index=months)
    n_no_road = int(n - len(rd))
    n_before = int(len(rd) - len(rs))
    no_road_by_year = yv_road_gap(df)
    if len(monthly) > MAX_MONTHLY_POINTS:
        q = monthly.groupby(monthly.index.asfreq("Q")).sum()
        road_chart = {"x": [f"{p.year} Q{p.quarter}" for p in q.index], "y": [int(v) for v in q]}
    else:
        road_chart = {"x": [f"{p.year}-{p.month:02d}" for p in monthly.index], "y": [int(v) for v in monthly]}
    road_chart["zoom_start"] = max(0, round(100 - 8 * 12 / max(len(monthly), 1) * 100))
    full = monthly.iloc[:-1]

    ytd = None
    last_full = last_m - 1
    ly, k = last_full.year, last_full.month
    cur_months = [p for p in full.index if p.year == ly and p.month <= k]
    prev_months = [p for p in full.index if p.year == ly - 1 and p.month <= k]
    if len(cur_months) == k and len(prev_months) == k:
        cur, prev = int(full[cur_months].sum()), int(full[prev_months].sum())
        if prev > 0:
            span = f"{MONTHS_HE[0]} עד {MONTHS_HE[k - 1]} {ly}" if k > 1 else f"{MONTHS_HE[0]} {ly}"
            ytd = {"cur": cur, "prev": prev, "ch": cur / prev - 1, "span": span, "prev_label": str(ly - 1),
                   "partial_note": f"{ref_label}, החודש האחרון בנתונים, לא נכלל כי ייתכן שהוא חלקי."}

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

    # Last 12 complete months of road entries: the "new cars" window.
    win = list(full.index[-12:])
    new_mask = df["road"].isin(win)
    n_win = int(new_mask.sum())
    win_label = (f"{MONTHS_HE[win[0].month - 1]} {win[0].year} עד {MONTHS_HE[win[-1].month - 1]} {win[-1].year}"
                 if win else "")
    win_fuel = _ranked(df.loc[new_mask, "fuel"]) if n_win else pd.Series(dtype=int)
    ev_win = int(win_fuel.get(EV, 0)) if n_win else 0
    ev_win_share = ev_win / n_win if n_win else 0.0

    # ── Production year × private/commercial ───────────────────────────────
    degems = _ordered(yv["degem"].unique(), ["פרטי", "מסחרי"])
    piv = yv.groupby(["year", "degem"]).size().unstack(fill_value=0).reindex(
        index=all_years, columns=degems, fill_value=0)
    years_chart = {"x": [str(y) for y in all_years],
                   "series": [{"name": c, "data": [int(v) for v in piv[c]]} for c in degems]}
    coh = yv["year"].map(lambda y: (y // 5) * 5)
    ct = yv.groupby([coh, "degem"]).size().unstack(fill_value=0).reindex(columns=degems, fill_value=0).sort_index()
    t_years = [{"name": f"{max(c, y_min)}-{min(c + 4, y1)}" if min(c + 4, y1) > max(c, y_min) else str(max(c, y_min)),
                "total": _int(ct.loc[c].sum()), "cols": [_int(ct.loc[c, d]) for d in degems]} for c in ct.index]
    degem_counts = {k2: int(v) for k2, v in df["degem"].value_counts().items()}
    med_year = int(yv["year"].median())
    ref_year = last_m.year
    med_age = ref_year - med_year

    # ── Fuel mix by production year ────────────────────────────────────────
    fuels = _ordered(df["fuel"].unique(), FUEL_ORDER)
    fuel_series, fuel_shares, _ = _share_series(yv, "fuel", fuels, mix_years)
    fuel_chart = {"x": [str(y) for y in mix_years], "series": fuel_series}
    t_fuel = _share_table(fuel_shares, fuels, tbl_years)
    fuel_all = _ranked(df["fuel"])
    t_fuel_all = _rank_rows([str(x) for x in fuel_all.index], [int(v) for v in fuel_all], n)

    # ── Brands and models ──────────────────────────────────────────────────
    b_names, b_vals = _top_other(df["brand"], TOP_BRANDS)
    brands_chart = {"names": b_names, "values": b_vals}
    t_brands = _rank_rows(b_names, b_vals, n)
    named = df["model_name"] != ""
    mg = df.loc[named].groupby(["brand", "model_name"]).size()
    mg.index = [f"{b} {m}" for b, m in mg.index]
    mvc = mg.sort_index().sort_values(ascending=False, kind="stable").head(TOP_MODELS)
    models_chart = {"names": [str(x) for x in mvc.index], "values": [int(v) for v in mvc]}
    t_models = _rank_rows(models_chart["names"], models_chart["values"], n)
    n_models = int(len(mg))

    # ── Plant country ──────────────────────────────────────────────────────
    known = df.loc[df["country"] != UNKNOWN, "country"]
    c_names, c_vals = _top_other(known, TOP_COUNTRIES)
    n_unk_country = int(n - len(known))
    countries_chart = {"names": c_names, "values": c_vals}
    t_countries = _rank_rows(c_names, c_vals, n)
    cvc = _ranked(known)
    top_country_all = (str(cvc.index[0]), int(cvc.iloc[0]) / n) if len(cvc) else None
    kmask = yv["country"] != UNKNOWN
    mix_c = [str(c) for c in _ranked(yv.loc[kmask & (yv["year"] >= y1 - SPAN), "country"]).head(MIX_COUNTRIES).index]
    yk = pd.DataFrame({"year": yv.loc[kmask, "year"],
                       "cgrp": yv.loc[kmask, "country"].where(yv.loc[kmask, "country"].isin(mix_c), OTHER)})
    cats_c = mix_c + ([OTHER] if (yk["cgrp"] == OTHER).any() else [])
    cmix_series, country_shares, _ = _share_series(yk, "cgrp", cats_c, mix_years)
    cmix_chart = {"x": [str(y) for y in mix_years], "series": cmix_series}
    t_cmix = _share_table(country_shares, cats_c, tbl_years)

    # ── Ownership ──────────────────────────────────────────────────────────
    owners = _ordered(df["owner"].unique(), OWNER_ORDER)
    owner_all = {k2: int(v) for k2, v in df["owner"].value_counts().items()}
    owner_chart = {"names": owners, "values": [owner_all.get(o, 0) for o in owners]}
    t_owner = _rank_rows(owners, owner_chart["values"], n)
    omix_series, owner_shares, _ = _share_series(yv, "owner", owners, tbl_years)
    omix_chart = {"x": [str(y) for y in tbl_years], "series": omix_series}
    t_omix = _share_table(owner_shares, owners, tbl_years)

    # ── Colours ────────────────────────────────────────────────────────────
    fam_hex = {f: h for f, _k, h in COLOR_FAMILIES}
    fam_vc = df["color_fam"].value_counts()
    fam_all = {str(k2): int(v) for k2, v in fam_vc.items()}
    fams = sorted(fam_all, key=lambda f: (f == OTHER, -fam_all[f], f))
    colors_chart = {"data": [{"name": f, "value": fam_all[f],
                              "itemStyle": {"color": fam_hex.get(f, COLOR_OTHER_HEX)}} for f in fams]}
    t_colors = _rank_rows(fams, [fam_all[f] for f in fams], n)
    craw_n, craw_v = _top_other(df["color"], TOP_COLORS_RAW)
    t_colors_raw = _rank_rows(craw_n, craw_v, n)
    newest = yv[yv["year"] == y_ins]
    fam_new = {str(k2): int(v) for k2, v in newest["color_fam"].value_counts().items()}
    n_colors = int(df["color"].nunique())

    # ── Licence validity ───────────────────────────────────────────────────
    tk = df["tokef"].dropna()
    expired = int((tk < ref_ts).sum())
    tq = tk.dt.to_period("Q")
    qvc = tq.value_counts().sort_index()
    q_lo, q_hi = qvc.index.min(), qvc.index.max()
    qs = pd.period_range(q_lo, q_hi, freq="Q")
    ref_q = last_m.asfreq("Q")
    tokef_chart = {"x": [f"{p.year} Q{p.quarter}" for p in qs], "y": [int(qvc.get(p, 0)) for p in qs],
                   "ref": [p < ref_q for p in qs]}
    t_tokef = [{"name": f"{p.year} Q{p.quarter}", "count": _int(qvc.get(p, 0)),
                "share": f"{qvc.get(p, 0) / len(tk) * 100:.1f}" if len(tk) else "0.0"} for p in qs]
    expired_share = expired / n if n else 0.0

    # ── Pollution group ────────────────────────────────────────────────────
    z = df["zihum"]
    zr = z.dropna().astype(int)
    z_groups = sorted(zr.unique().tolist())
    zvc = zr.value_counts()
    n_z_missing = int(z.isna().sum())
    n_z_missing_ev = int((z.isna() & (df["fuel"] == EV)).sum())
    zihum_chart = {"x": [str(g) for g in z_groups], "y": [int(zvc.get(g, 0)) for g in z_groups]}
    t_zihum = _rank_rows([str(g) for g in z_groups], zihum_chart["y"], max(len(zr), 1))

    def zsplit(year):
        s = yv.loc[yv["year"] == year, "zihum"].dropna()
        if len(s) < 1000:
            return None
        return ((s <= CLEAN_MAX).mean(), (s == DIRTY_GROUP).mean())

    z_old_year = max(y_ins - 2 * SPAN, y_min)
    z_new, z_old = zsplit(y_ins), zsplit(z_old_year)

    # ── Safety equipment level ─────────────────────────────────────────────
    cover = yv.groupby("year")["safety"].apply(lambda s: s.notna().mean())
    s_years = [y for y in all_years if cover.get(y, 0.0) >= SAFETY_MIN_COVER]
    safety_chart = None
    t_safety = []
    safe_high = {}
    if s_years:
        sv = yv[yv["year"].isin(s_years)].dropna(subset=["safety"])
        sv = sv.assign(lvl=sv["safety"].astype(int))
        levels = sorted(sv["lvl"].unique().tolist())
        sct = sv.groupby(["year", "lvl"]).size().unstack(fill_value=0).reindex(
            index=s_years, columns=levels, fill_value=0)
        stot = sct.sum(axis=1)
        safety_chart = {"x": [str(y) for y in s_years],
                        "series": [{"name": f"רמה {lv}",
                                    "data": [round(float(sct.loc[y, lv] / stot.loc[y] * 100), 1) if stot.loc[y] else 0.0
                                             for y in s_years]} for lv in levels]}
        for y in s_years:
            safe_high[y] = float(sct.loc[y, [lv for lv in levels if lv >= SAFETY_HIGH]].sum() / stot.loc[y]) \
                if stot.loc[y] else 0.0
        means = (sv.groupby("year")["lvl"].mean()).reindex(s_years)
        t_safety = [{"name": str(y), "count": _int(stot.loc[y]), "cover": f"{cover[y] * 100:.1f}",
                     "mean": f"{means.loc[y]:.1f}", "high": f"{safe_high[y] * 100:.1f}"} for y in s_years]
    n_safety = int(df["safety"].notna().sum())

    # ── Insights ───────────────────────────────────────────────────────────
    rules = [
        ("ytd", insight_ytd(ytd)),
        ("ev", insight_ev(fuel_shares, y_ins)),
        ("brand", insight_brand(df)),
        ("country", insight_country(country_shares, y_ins, top_country_all)),
        ("lease", insight_lease(owner_shares, y_ins, owner_all, n)),
        ("season", insight_season(season)),
        ("color", insight_color(fam_all, fam_new, y_ins, n, len(newest))),
        ("expired", insight_expired(expired, n, ref_label)),
        ("pollution", insight_pollution(z_new, z_old, y_ins, z_old_year)),
        ("safety", insight_safety(safe_high, [y for y in s_years if y <= y_ins])),
        ("commercial", insight_commercial(degem_counts, n)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ── KPIs ───────────────────────────────────────────────────────────────
    ev_tone = "ok" if ev_win_share >= 0.1 else "info"
    exp_tone = "warn" if expired_share >= EXPIRED_WARN else "brand"

    summary = (f"בדיקת רכב לפי מספר רישוי: חיפוש יצרן, דגם, שנת ייצור, צבע ותוקף רישיון ב-{_int(n)} "
               f"כלי רכב פרטיים ומסחריים פעילים, עם ניתוח הצי.")

    b1 = b_names[0] if b_names else ""
    lede = (f"המאגר של משרד התחבורה כולל {_int(n)} כלי רכב פעילים: {_int(degem_counts.get('פרטי', 0))} פרטיים "
            f"משנת ייצור {y_min} ואילך ו-{_int(degem_counts.get('מסחרי', 0))} מסחריים עד 3,500 ק״ג. "
            f"לכל רכב רשומים מספר הרישוי, היצרן והדגם, שנת הייצור, סוג הדלק, הצבע, הבעלות ותוקף הרישיון. "
            f"שנת הייצור החציונית היא {med_year}, והיצרן הנפוץ ביותר הוא {b1}. "
            f"הנתונים מתעדכנים מדי יום, עד {ref_label}.")

    no_road_note = (f" (המועד חסר לרוב כלי הרכב משנות ייצור {no_road_by_year} ומטה)"
                    if no_road_by_year else "")
    heat_peak = (f"{MONTHS_HE[season['hi'][0] - 1]} בולט כחודש השיא. "
                 if season and season["hi"][1] >= SEASON_RATIO / 12 else "")
    labels = {
        "lede": lede,
        "total_kpi": "כלי רכב פעילים במאגר",
        "ev_kpi": f"חשמליים מתוך הרכבים שעלו לכביש ב-12 החודשים {win_label}",
        "age_kpi": f"גיל חציוני של הצי (שנים, לפי שנת ייצור, נכון ל-{ref_year})",
        "exp_kpi": f"רישיון שתוקפו פג לפני {ref_label}",
        "road_note": (f"מספר כלי הרכב שעלו לכביש בכל חודש מ-{start_year} ועדיין פעילים. השנים המוקדמות "
                      f"מדוללות בשל גריטה, והחודש האחרון ({ref_label}) עשוי להיות חלקי. {_int(n_no_road)} כלי רכב "
                      f"ללא מועד עלייה לכביש{no_road_note} ו-{_int(n_before)} שעלו לפני {start_year} "
                      f"אינם בגרף."),
        "road_aria": f"גרף קווי: כלי רכב שעלו לכביש לפי חודש, {start_year} עד {ref_label}",
        "heat_note": (f"כל תא הוא חודש בשנה; צבע כהה יותר הוא יותר כלי רכב שעלו לכביש. "
                      f"{heat_peak}{ref_label} עשוי להיות חלקי."),
        "heat_aria": f"מפת חום: כלי רכב שעלו לכביש לפי חודש ושנה, {start_year} עד {last_m.year}",
        "years_note": (f"כלי הרכב הפעילים לפי שנת ייצור. השנים הוותיקות קטנות כי רכבים ישנים יוצאים מהכביש; "
                       f"מחצית הצי יוצרה ב-{med_year} או אחריה."),
        "years_aria": f"גרף עמודות מוערם: כלי רכב פעילים לפי שנת ייצור, פרטי ומסחרי, {y_min} עד {y1}",
        "years_caption": "כלי רכב פעילים לפי חמש שנות ייצור, פרטי ומסחרי",
        "fuel_note": (f"חלקו של כל סוג דלק מכלי כל שנת ייצור, מ-{mix_start} (שנים קודמות קטנות מ-"
                      f"{_pct(SERIES_MIN_SHARE)} מהצי ואינן בגרף).{partial_year}"),
        "fuel_aria": f"גרף שטח מוערם: תמהיל סוגי הדלק לפי שנת ייצור, {mix_start} עד {y1}",
        "fuel_caption": f"שיעור סוגי הדלק (%) לפי שנת ייצור, {tbl_years[0]} עד {tbl_years[-1]}",
        "fuel_all_caption": "סוגי הדלק בצי כולו",
        "brands_note": f"{TOP_BRANDS} היצרנים הגדולים בצי הפעיל; ארץ המפעל אוחדה תחת שם היצרן.",
        "brands_aria": f"גרף עמודות: {TOP_BRANDS} היצרנים המובילים לפי מספר כלי רכב פעילים",
        "models_note": (f"{TOP_MODELS} הדגמים הנפוצים לפי הכינוי המסחרי, מתוך {_int(n_models)} צירופי יצרן "
                        f"ודגם. גרסאות שונות של אותו דגם (למשל האצ'בק והיברידי) נספרות בנפרד."),
        "models_aria": f"גרף עמודות: {TOP_MODELS} הדגמים הנפוצים בצי הפעיל",
        "countries_note": (f"ארץ המפעל לפי שם היצרן ברשומה. ל-{_int(n_unk_country)} כלי רכב ארץ הייצור "
                           f"אינה מצוינת או קטועה באופן שאינו חד-משמעי, והם אינם בגרף."),
        "countries_aria": f"גרף עמודות: {TOP_COUNTRIES} ארצות הייצור המובילות",
        "cmix_note": (f"חלקן של {len(mix_c)} ארצות הייצור המובילות בשנים {y1 - SPAN}-{y1} מכלי כל שנת ייצור, "
                      f"מ-{mix_start} (ללא כלי רכב שארץ הייצור שלהם לא צוינה)."),
        "cmix_aria": f"גרף קווים: חלק ארצות הייצור לפי שנת ייצור, {mix_start} עד {y1}",
        "cmix_caption": f"שיעור ארצות הייצור (%) לפי שנת ייצור, {tbl_years[0]} עד {tbl_years[-1]}",
        "owner_aria": "גרף עמודות: כלי רכב לפי סוג הבעלות",
        "omix_note": f"סוג הבעלות הנוכחי לפי שנת ייצור, {tbl_years[0]} עד {tbl_years[-1]}.",
        "omix_aria": f"גרף עמודות מוערם: סוג הבעלות לפי שנת ייצור, {tbl_years[0]} עד {tbl_years[-1]}",
        "omix_caption": f"שיעור סוגי הבעלות (%) לפי שנת ייצור, {tbl_years[0]} עד {tbl_years[-1]}",
        "colors_note": (f"{_int(n_colors)} שמות צבע שונים במאגר קובצו למשפחות לפי המילה הראשונה המזהה "
                        f"צבע בשם (למשל \"אפור כחול מטלי\" נספר כאפור)."),
        "colors_aria": "תרשים טבעת: כלי רכב לפי משפחת צבע",
        "colors_raw_caption": f"{TOP_COLORS_RAW} שמות הצבע הנפוצים כפי שנרשמו",
        "tokef_note": (f"מתי פג תוקף רישיון הרכב, לפי רבעון. העמודות המודגשות בצבע אזהרה הן רבעונים שהסתיימו או החלו "
                       f"לפני {ref_label}, החודש האחרון בנתונים."),
        "tokef_aria": "גרף עמודות: כלי רכב לפי רבעון פקיעת תוקף הרישיון",
        "zihum_note": (f"קבוצת זיהום האוויר מ-1 (הנקייה ביותר) עד {DIRTY_GROUP} (המזהמת ביותר). ל-{_int(n_z_missing)} "
                       f"כלי רכב לא רשומה קבוצה, מהם {_int(n_z_missing_ev)} חשמליים; הם אינם בגרף."),
        "zihum_aria": f"גרף עמודות: כלי רכב לפי קבוצת זיהום אוויר, 1 עד {DIRTY_GROUP}",
        "safety_note": (f"רמת האבזור הבטיחותי (0 עד 8, גבוה יותר הוא יותר מערכות סיוע) רשומה ל-{_int(n_safety)} "
                        f"כלי רכב. הגרף מציג את שנות הייצור שבהן לפחות {_pct(SAFETY_MIN_COVER, 0)} מהרכבים "
                        f"קיבלו דירוג, כשיעור מהמדורגים."),
        "safety_aria": "גרף עמודות מוערם: התפלגות רמת האבזור הבטיחותי לפי שנת ייצור",
        "safety_caption": "רמת האבזור הבטיחותי לפי שנת ייצור",
        "safety_high_head": f"רמה {SAFETY_HIGH} ומעלה (%)",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["רכב", "רישוי רכב", "מספר רישוי", "רכב חשמלי", "צי רכב", "תחבורה"],
            "related_ids": [
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "0f16b39a-6016-408d-805d-31f40d5a0990",
                "392abd0a-64f6-4c18-9d56-0111001411e6",
                "11369651-1c70-4d8f-8090-ee49354a7c52",
                "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
            ],
            "temporal_coverage": f"{y_min}/{y1}",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "ev": {"value": round(ev_win_share, 4), "display": _pct(ev_win_share), "tone": ev_tone},
            "age": {"value": med_age, "display": _int(med_age), "tone": "brand"},
            "expired": {"value": round(expired_share, 4), "display": _pct(expired_share), "tone": exp_tone},
        },
        "charts": {
            "road": road_chart,
            "heat": heat_chart,
            "years": years_chart,
            "fuel": fuel_chart,
            "brands": brands_chart,
            "models": models_chart,
            "countries": countries_chart,
            "cmix": cmix_chart,
            "owner": owner_chart,
            "omix": omix_chart,
            "colors": colors_chart,
            "tokef": tokef_chart,
            "zihum": zihum_chart,
            "safety": safety_chart,
        },
        "tables": {
            "degem_cols": degems,
            "years": t_years,
            "fuel_cols": fuels,
            "fuel": t_fuel,
            "fuel_all": t_fuel_all,
            "brands": t_brands,
            "models": t_models,
            "countries": t_countries,
            "cmix_cols": cats_c,
            "cmix": t_cmix,
            "owner": t_owner,
            "owner_cols": owners,
            "omix": t_omix,
            "colors": t_colors,
            "colors_raw": t_colors_raw,
            "tokef": t_tokef,
            "zihum": t_zihum,
            "safety": t_safety,
        },
        "flags": {"safety": safety_chart is not None},
        "insights": insights,
        "labels": labels,
    }
