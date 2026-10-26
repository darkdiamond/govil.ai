"""מספרי רישוי של כלי הרכב הציבוריים הפעילים — taxis, minibuses and buses.

One row per vehicle in the public-transport register (taxis, service taxis,
minibuses, urban / intercity / special-transport / tour buses). The export is
a snapshot: older production years are thinned by retirement, and about a
tenth of the rows already carry a cancellation code (deposit, scrapping, total
loss, cancelled before sale) — the page counts every row and shows the status
split separately.

- `sug_rechev_EU_cd` (M1 / M2 / M3) is the EU size class and drives the three
  segments: M1 — taxis (≤8 passenger seats), M2 — minibuses (≤5 t), M3 — buses.
- `tozeret_nm` is a 14-character field "<maker> <plant country>", often
  truncated ("מרצדס בנץ גרמנ"). The plant country is parsed off the end, so a
  maker's plants merge into one brand and the country becomes its own view.
- Seats = `mispar_mekomot` + `mispar_mekomot_leyd_nahag` (seats beside the
  driver); a taxi is 3 + 1.
- Reference date for licence expiry is the latest cancellation date in the
  data (the export's own "as of"), never the clock. Without one, the expiry
  split is omitted.
- Licence plates are never shown — everything is aggregated by segment,
  service type, maker, model, year, seats, colour and status.
"""
import math
import re

import pandas as pd

OTHER = "אחר"
UNKNOWN = "לא צוין"
TOP_TYPES = 12
TOP_BRANDS = 12
TOP_MODELS = 12
TOP_COUNTRIES = 6
TOP_COLORS = 8
TOP_REASONS = 8
BOX_MIN = 50               # service types with ≥ this many vehicles get a box
TABLE_YEARS = 12
SERIES_MIN_SHARE = 0.0025  # year axis starts at the first year with ≥0.25% of rows
YOUNG_YEARS = 5
SHIFT_SPAN = 5             # compare a production year with this many years earlier
SHIFT_PP = 0.05            # ≥5 points counts as a shift
SHIFT_WINDOW = 3           # production years pooled on each side of the comparison
SHIFT_MIN_N = 200          # both years need this many buses
AGE_GAP = 3                # median-year gap between service types worth a sentence
AGE_MIN_N = 200
LEADER_MIN = 0.2           # a maker needs ≥20% of its segment to "lead"
COLOR_MIN = 0.5
EXPIRED_MIN = 20
EXPIRED_OK, EXPIRED_WARN = 0.02, 0.05

SEGMENTS = ["M1", "M2", "M3"]
SEG_NAME = {"M1": "מוניות", "M2": "אוטובוסים זעירים", "M3": "אוטובוסים"}
SEG_DESC = {"M1": "M1 — מוניות", "M2": "M2 — אוטובוסים זעירים", "M3": "M3 — אוטובוסים"}
ACTIVE_CODE = "0"
CHINA = "סין"

# Register spellings with a stray gershayim at the end ("זעצ ...מיוחדות\"").
TYPE_ALIASES = {
    'אוטובוס זעצ הסעות מיוחדות"': "אוטובוס זע״צ הסעות מיוחדות",
}
REASON_ALIASES = {'העברה לרשפ"': "העברה לרש״פ", 'העברה לחול"': "העברה לחו״ל"}

# Plant-country tokens at the end of the maker field. Truncated prefixes are
# matched against FULL_COUNTRIES only when the field is long enough to have
# been cut (see _split_maker); short brand-letter names ("ג'יי איי סי") stay whole.
COUNTRY_TOKENS = {
    "גרמניה": "גרמניה", "שבדיה": "שבדיה", "צ'כיה": "צ'כיה", "יפן": "יפן", "סין": "סין",
    "טורקיה": "טורקיה", "תורכיה": "טורקיה", "טורקי": "טורקיה", "טורק": "טורקיה",
    "קוריאה": "דרום קוריאה", "ד.קוריאה": "דרום קוריאה", "ד.קור": "דרום קוריאה",
    "אנגליה": "בריטניה", "בריטניה": "בריטניה", 'ארהב"': "ארה״ב", "ארהב": "ארה״ב",
    "ספרד": "ספרד", "פולין": "פולין", "צרפת": "צרפת", "איטליה": "איטליה",
    "סלובקיה": "סלובקיה", "הולנד": "הולנד", "רומניה": "רומניה", "קנדה": "קנדה",
    "אוסטריה": "אוסטריה", "הונגריה": "הונגריה", "מקסיקו": "מקסיקו", "בלגיה": "בלגיה",
    "הודו": "הודו", "מרוקו": "מרוקו", "ד.אפ": "דרום אפריקה", "ד.אפריקה": "דרום אפריקה",
}
FULL_COUNTRIES = ["גרמניה", "שבדיה", "צ'כיה", "יפן", "סין", "טורקיה", "תורכיה", "קוריאה",
                  "אנגליה", "ארהב", "ספרד", "פולין", "צרפת", "איטליה", "סלובקיה", "הולנד",
                  "רומניה", "קנדה", "אוסטריה", "הונגריה", "מקסיקו", "בלגיה", "הודו", "מרוקו"]
TRUNC_LEN = 13
BRAND_ALIASES = {
    "דאציה": "דאצ'יה", "ז'ונגטונג": "זונגטונג", "דימלרקריזלר": "דיימלר קרייזלר",
    "ב מ וו": "ב.מ.וו", "בי.מ.סי.": "בי.אם.סי",
}
LATIN_MAKES = {"TOYOTA", "SKODA", "HYUNDAI", "KIA", "BYD", "MERCEDES", "RENAULT",
               "CITROEN", "PEUGEOT", "CHERY", "GEELY", "TESLA", "MG", "SEAT", "FORD"}
# "X עד Y" rather than "X–Y": canvas axis labels in RTL flip a dash range.
SEAT_BINS = [(1, 4, "1 עד 4"), (5, 8, "5 עד 8"), (9, 16, "9 עד 16"), (17, 20, "17 עד 20"),
             (21, 35, "21 עד 35"), (36, 45, "36 עד 45"), (46, 55, "46 עד 55"), (56, 65, "56 עד 65"),
             (66, 9999, "66 ומעלה")]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _gershayim(s):
    return re.sub(r'([א-ת])"(?=[א-ת])', "\\1״", re.sub(r'([א-ת])([א-ת])"(?=\s|$)', r"\1״\2", s))


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


def _split_maker(name):
    """'טויוטה טורקיה' → ('טויוטה', 'טורקיה'); handles truncation and 'ד. קוריאה'."""
    s = name.strip()
    toks = [t for t in re.split(r"[\s\-]+", s) if t]
    country = None
    if len(toks) > 1:
        last = toks[-1]
        if last in COUNTRY_TOKENS:
            country = COUNTRY_TOKENS[last]
        elif len(s) >= TRUNC_LEN and len(last) >= 2:
            hit = next((c for c in FULL_COUNTRIES if c.startswith(last)), None)
            if hit:
                country = COUNTRY_TOKENS[hit]
        if country:
            toks = toks[:-1]
            if len(toks) > 1 and toks[-1] in ("ד.", "ד"):
                toks = toks[:-1]
    brand = " ".join(toks) if toks else UNKNOWN
    return _gershayim(BRAND_ALIASES.get(brand, brand)), country or UNKNOWN


def _family(kinuy):
    s = re.sub(r"\s+", " ", kinuy.strip().upper())
    if not s:
        return ""
    s = re.sub(r"\b([A-Z]{2,})[ \-](\d)\b", r"\1\2", s)   # RAV 4 / RAV-4 → RAV4
    s = re.sub(r"(\d) D\b", r"\1D", s)                     # C200 D → C200D
    toks = s.split(" ")
    if len(toks) > 1 and toks[0] in LATIN_MAKES:
        toks = toks[1:]
    fam = toks[0]
    if len(fam) == 1 and len(toks) > 1:
        fam = f"{fam} {toks[1]}"
    return fam


def _seat_bin(v):
    for lo, hi, label in SEAT_BINS:
        if lo <= v <= hi:
            return label
    return None


def _date_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _prepare(df):
    makers = df["tozeret_nm"].str.strip()
    mk = {n: _split_maker(n) for n in makers.unique()}
    vtype = df["sug_rechev_nm"].str.strip().str.replace(r"\s+", " ", regex=True)
    vtype = vtype.map(lambda v: _gershayim(TYPE_ALIASES.get(v, v.rstrip('"'))) if v else UNKNOWN)
    seg = df["sug_rechev_EU_cd"].str.strip().str.upper().replace("", UNKNOWN)
    seats = (pd.to_numeric(df["mispar_mekomot"], errors="coerce").fillna(0)
             + pd.to_numeric(df["mispar_mekomot_leyd_nahag"], errors="coerce").fillna(0))
    code = df["bitul_cd"].str.strip()
    reason = df["bitul_nm"].str.strip().map(lambda v: _gershayim(REASON_ALIASES.get(v, v)) if v else UNKNOWN)
    kin = df["kinuy_mishari"].map(_family)
    out = pd.DataFrame({
        "brand": makers.map(lambda n: mk[n][0]),
        "country": makers.map(lambda n: mk[n][1]),
        "year": pd.to_numeric(df["shnat_yitzur"], errors="coerce"),
        "seg": seg,
        "vtype": vtype,
        "seats": seats,
        "weight": pd.to_numeric(df["mishkal_kolel"].str.replace(",", ""), errors="coerce"),
        "color": df["tzeva_rechev"].str.strip().replace("", UNKNOWN),
        "active": (code == ACTIVE_CODE) | (code == ""),
        "reason": reason,
        "cancel_dt": pd.to_datetime(df["bitul_dt"].str.strip(), errors="coerce", format="%Y-%m-%d"),
        "tokef": pd.to_datetime(df["tokef_dt"].str.strip(), errors="coerce", format="%Y-%m-%d"),
        "degem": df["degem_nm"].str.strip().str.replace(r"\s+", " ", regex=True),
        "family": kin,
    })
    return out


def _segments(df):
    present = set(df["seg"].unique())
    return [s for s in SEGMENTS if s in present] + sorted(present - set(SEGMENTS))


def _seg_label(s):
    return SEG_DESC.get(s, s)


# ── insight rules ────────────────────────────────────────────────────────────

def insight_segments(seg_counts, n):
    if n == 0 or len(seg_counts) < 2:
        return None
    parts = [f"{SEG_NAME.get(s, s)} — {_int(v)} ({_pct(v / n)})" for s, v in seg_counts]
    return f"הקובץ מונה {_int(n)} כלי רכב ציבוריים: " + "; ".join(parts) + "."


def insight_young(years, y_ref):
    if len(years) < 100:
        return None
    lo = y_ref - YOUNG_YEARS + 1
    share = (years >= lo).mean()
    return (f"הצי צעיר: {_pct(share)} מהכלים יוצרו בשנים \u2066{lo}–{y_ref}\u2069, "
            f"ושנת הייצור החציונית היא {int(years.median())}.")


def insight_age_gap(type_med):
    rows = [r for r in type_med if r["n"] >= AGE_MIN_N]
    if len(rows) < 2:
        return None
    old = min(rows, key=lambda r: (r["med"], r["name"]))
    new = max(rows, key=lambda r: (r["med"], r["name"]))
    if new["med"] - old["med"] < AGE_GAP:
        return None
    return (f"הוותיקים בצי הם כלי הסוג \"{old['name']}\" (שנת ייצור חציונית {old['med']}), "
            f"והחדשים — \"{new['name']}\" ({new['med']}).")


def insight_leader(df, seg_set, label):
    sub = df[df["seg"].isin(seg_set)]
    if len(sub) < 100:
        return None
    vc = _ranked(sub["brand"])
    if len(vc) < 3:
        return None
    (b1, n1), (b2, n2), (b3, n3) = list(vc.items())[:3]
    share = n1 / len(sub)
    if share < LEADER_MIN:
        return None
    return (f"בקרב ה{label} היצרן המוביל הוא {b1}, עם {_int(n1)} כלים ({_pct(share)}), "
            f"לפני {b2} ({_int(n2)}) ו{b3} ({_int(n3)}).")


def _pooled(cn_share, lo, hi):
    rows = [cn_share[y] for y in range(lo, hi + 1) if y in cn_share]
    if len(rows) < hi - lo + 1:
        return None
    n = sum(r["n"] for r in rows)
    cn = sum(r["cn"] for r in rows)
    return {"n": n, "share": cn / n if n else 0.0}


def insight_china(cn_share, y_cmp):
    """Pooled 3-production-year windows, SHIFT_SPAN years apart."""
    w = SHIFT_WINDOW - 1
    cur = _pooled(cn_share, y_cmp - w, y_cmp)
    old = _pooled(cn_share, y_cmp - SHIFT_SPAN - w, y_cmp - SHIFT_SPAN)
    if not cur or not old or cur["n"] < SHIFT_MIN_N or old["n"] < SHIFT_MIN_N:
        return None
    if abs(cur["share"] - old["share"]) < SHIFT_PP:
        return None
    word = "עלה" if cur["share"] > old["share"] else "ירד"
    return (f"חלקם של האוטובוסים (כולל זעירים) מתוצרת סין {word} מ-{_pct(old['share'])} "
            f"מכלי שנות הייצור \u2066{y_cmp - SHIFT_SPAN - w}–{y_cmp - SHIFT_SPAN}\u2069 "
            f"ל-{_pct(cur['share'])} מכלי השנים \u2066{y_cmp - w}–{y_cmp}\u2069.")


def insight_expired(exp):
    if exp is None or exp["n"] < EXPIRED_MIN:
        return None
    return (f"ל-{_int(exp['n'])} כלים שאינם מסומנים כמבוטלים ({_pct(exp['share'])}) "
            f"פג תוקף הרישיון לפני {exp['ref_he']}, התאריך האחרון בנתונים; "
            f"{_int(exp['taxi'])} מהם מוניות.")


def insight_cancelled(df, n):
    canc = df[~df["active"]]
    if n == 0 or len(canc) / n < 0.01:
        return None
    vc = _ranked(canc["reason"])
    r1, c1 = vc.index[0], int(vc.iloc[0])
    taxi = int((canc["seg"] == "M1").sum())
    return (f"{_int(len(canc))} כלים ({_pct(len(canc) / n)}) מסומנים כמבוטלים; הסיבה הנפוצה — "
            f"\"{r1}\" ({_int(c1)}), ו-{_pct(taxi / len(canc))} מהמבוטלים הם מוניות.")


def insight_seats(df):
    total = float(math.fsum(df["seats"].tolist()))
    if total <= 0:
        return None
    bus = float(math.fsum(df.loc[df["seg"] == "M3", "seats"].tolist()))
    return (f"יחד מציעים הכלים {_int(total)} מקומות ישיבה לנוסעים; "
            f"{_pct(bus / total)} מהם באוטובוסים (M3).")


def insight_color(df):
    vc = _ranked(df["color"])
    if not len(vc):
        return None
    c1, n1 = vc.index[0], int(vc.iloc[0])
    share = n1 / len(df)
    if share < COLOR_MIN:
        return None
    taxis = df[df["seg"] == "M1"]
    t_share = (taxis["color"] == c1).mean() if len(taxis) else 0.0
    return (f"{_pct(share)} מהכלים צבועים \"{c1}\" — ובקרב המוניות {_pct(t_share)}.")


# ── compute ──────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["fleet"])
    n = len(df)
    segs = _segments(df)
    yv = df.dropna(subset=["year"]).copy()
    yv["year"] = yv["year"].astype(int)
    years = yv["year"]
    y0, y1 = int(years.min()), int(years.max())

    cdates = df["cancel_dt"].dropna()
    ref = cdates.max() if len(cdates) else None
    partial_year = bool(ref is not None and y1 >= ref.year)
    y_cmp = y1 - 1 if partial_year else y1

    # ── Segments & service types ──────────────────────────────────────────
    sv = _ranked(df["seg"])
    seg_counts = [(s, int(sv.get(s, 0))) for s in segs]
    t_names, t_vals = _top_other(df["vtype"], TOP_TYPES)
    type_stats = df.groupby("vtype").agg(med_seats=("seats", "median"), n=("seats", "size"))
    type_year = yv.groupby("vtype")["year"].median()
    t_types = []
    for name, v in zip(t_names, t_vals):
        if name == OTHER:
            t_types.append({"name": name, "count": _int(v), "share": f"{v / n * 100:.1f}",
                            "seats": "—", "year": "—"})
        else:
            t_types.append({"name": name, "count": _int(v), "share": f"{v / n * 100:.1f}",
                            "seats": _int(type_stats.loc[name, "med_seats"]),
                            "year": str(int(type_year[name])) if name in type_year.index else "—"})
    types_seg = df.groupby("vtype")["seg"].agg(lambda s: _ranked(s).index[0])
    type_colors = [SEGMENTS.index(types_seg[t]) if t in types_seg.index and types_seg[t] in SEGMENTS else 3
                   for t in t_names]

    # ── Production year × segment ─────────────────────────────────────────
    yc = years.value_counts().sort_index()
    start_year = next((int(y) for y, v in yc.items() if v >= SERIES_MIN_SHARE * n), y0)
    piv = yv.groupby(["year", "seg"]).size().unstack(fill_value=0).reindex(columns=segs, fill_value=0)
    axis_years = list(range(start_year, y1 + 1))
    old_mask = piv.index < start_year
    head = piv[old_mask].sum() if old_mask.any() else None
    piv_main = piv.reindex(index=axis_years, fill_value=0)
    x_years = ([f"עד {start_year - 1}"] if head is not None else []) + [str(y) for y in axis_years]
    years_series = []
    for s in segs:
        data = ([int(head[s])] if head is not None else []) + [int(v) for v in piv_main[s]]
        years_series.append({"name": _seg_label(s), "data": data})
    years_chart = {"x": x_years, "series": years_series}
    t_years = []
    if head is not None:
        t_years.append({"name": f"עד {start_year - 1}", "total": _int(head.sum()),
                        "cols": [_int(head[s]) for s in segs]})
    tail_years = axis_years[-TABLE_YEARS:]
    if len(axis_years) > TABLE_YEARS:
        mid = piv_main.loc[axis_years[0]:axis_years[-TABLE_YEARS - 1]].sum()
        t_years.append({"name": f"\u2066{axis_years[0]}–{axis_years[-TABLE_YEARS - 1]}\u2069", "total": _int(mid.sum()),
                        "cols": [_int(mid[s]) for s in segs]})
    for y in tail_years:
        t_years.append({"name": str(y), "total": _int(piv_main.loc[y].sum()),
                        "cols": [_int(piv_main.loc[y, s]) for s in segs]})
    young_share = float((years >= y_cmp - YOUNG_YEARS + 1).mean()) if len(years) else 0.0
    year_med = int(years.median())

    # ── Production year by service type (boxplot) ─────────────────────────
    box_types = [t for t in _ranked(yv["vtype"]).index if int((yv["vtype"] == t).sum()) >= BOX_MIN]
    grouped = {t: g["year"] for t, g in yv.groupby("vtype")}
    box_rows = []
    for t in box_types:
        ys = grouped[t]
        qs = [float(ys.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
        box_rows.append({"name": t, "q": [round(v, 1) for v in qs], "n": int(len(ys)),
                         "med": int(round(qs[2]))})
    box_rows.sort(key=lambda r: (r["q"][2], r["q"][1], r["name"]))
    box_chart = {"names": [r["name"] for r in box_rows], "data": [r["q"] for r in box_rows]}
    t_box = [{"name": r["name"], "q1": f"{r['q'][1]:.0f}", "med": f"{r['q'][2]:.0f}",
              "q3": f"{r['q'][3]:.0f}", "count": _int(r["n"])} for r in box_rows]

    # ── Makers ─────────────────────────────────────────────────────────────
    taxis = df[df["seg"] == "M1"]
    buses = df[df["seg"].isin(["M2", "M3"])]

    def brand_block(sub):
        names, vals = _top_other(sub["brand"], TOP_BRANDS)
        tot = max(len(sub), 1)
        return ({"names": names, "values": vals},
                [{"name": a, "count": _int(b), "share": f"{b / tot * 100:.1f}"} for a, b in zip(names, vals)])

    taxi_brands, t_taxi_brands = brand_block(taxis)
    bus_brands, t_bus_brands = brand_block(buses)
    n_taxi_brands = int(taxis["brand"].nunique())
    n_bus_brands = int(buses["brand"].nunique())

    # ── Models ─────────────────────────────────────────────────────────────
    tm = taxis[taxis["family"] != ""]
    tmv = _ranked(tm["brand"] + " " + tm["family"]).head(TOP_MODELS)
    taxi_models = {"names": list(tmv.index), "values": [int(v) for v in tmv]}
    t_taxi_models = [{"name": k, "count": _int(v), "share": f"{v / max(len(taxis), 1) * 100:.1f}"}
                     for k, v in tmv.items()]
    bm = buses[buses["degem"] != ""]
    bmv = _ranked(bm["brand"] + " " + bm["degem"]).head(TOP_MODELS)
    bus_models = {"names": list(bmv.index), "values": [int(v) for v in bmv]}
    t_bus_models = [{"name": k, "count": _int(v), "share": f"{v / max(len(buses), 1) * 100:.1f}"}
                    for k, v in bmv.items()]
    n_bus_models = int((bm["brand"] + " " + bm["degem"]).nunique())

    # ── Plant country of buses by production year ──────────────────────────
    by = buses.dropna(subset=["year"]).copy()
    by["year"] = by["year"].astype(int)
    top_c = [c for c in _ranked(by["country"]).index if c != UNKNOWN][:TOP_COUNTRIES]
    by["cgroup"] = by["country"].where(by["country"].isin(top_c), OTHER)
    c_order = top_c + ([OTHER] if (by["cgroup"] == OTHER).any() else [])
    cpiv = by.groupby(["year", "cgroup"]).size().unstack(fill_value=0).reindex(columns=c_order, fill_value=0)
    c_years = [y for y in axis_years if y in cpiv.index and cpiv.loc[y].sum() > 0]
    c_series = []
    for c in c_order:
        c_series.append({"name": c, "data": [round(cpiv.loc[y, c] / cpiv.loc[y].sum() * 100, 1) for y in c_years]})
    country_chart = {"x": [str(y) for y in c_years], "series": c_series}
    t_country = [{"name": str(y), "cols": [f"{cpiv.loc[y, c] / cpiv.loc[y].sum() * 100:.1f}" for c in c_order]}
                 for y in c_years[-TABLE_YEARS:]]
    cn_share = {}
    for y in cpiv.index:
        tot = int(cpiv.loc[y].sum())
        cn = int(cpiv.loc[y, CHINA]) if CHINA in cpiv.columns else 0
        cn_share[int(y)] = {"n": tot, "cn": cn, "share": cn / tot if tot else 0.0}
    bus_cn_all = float((buses["country"] == CHINA).mean()) if len(buses) else 0.0

    # ── Seats ──────────────────────────────────────────────────────────────
    sd = df[df["seats"] > 0].copy()
    sd["bin"] = sd["seats"].map(_seat_bin)
    spiv = sd.groupby(["bin", "seg"]).size().unstack(fill_value=0).reindex(
        index=[b[2] for b in SEAT_BINS], columns=segs, fill_value=0)
    seats_chart = {"x": [b[2] for b in SEAT_BINS],
                   "series": [{"name": _seg_label(s), "data": [int(v) for v in spiv[s]]} for s in segs]}
    t_seats = [{"name": b, "cols": [_int(spiv.loc[b, s]) for s in segs]} for b in spiv.index]
    total_seats = int(round(math.fsum(df["seats"].tolist())))
    n_no_seats = int(n - len(sd))
    seg_seats = {s: int(round(math.fsum(df.loc[df["seg"] == s, "seats"].tolist()))) for s in segs}
    seg_seat_med = {s: int(df.loc[df["seg"] == s, "seats"].median()) for s in segs}
    seg_weight_med = {s: int(df.loc[(df["seg"] == s) & (df["weight"] > 0), "weight"].median())
                      if ((df["seg"] == s) & (df["weight"] > 0)).any() else 0 for s in segs}
    t_segs = [{"name": _seg_label(s), "count": _int(dict(seg_counts)[s]),
               "share": f"{dict(seg_counts)[s] / n * 100:.1f}",
               "seats": _int(seg_seats[s]), "seat_med": _int(seg_seat_med[s]),
               "weight": _int(seg_weight_med[s]) if seg_weight_med[s] else "—"} for s in segs]

    # ── Colours ────────────────────────────────────────────────────────────
    col_names, _ = _top_other(df["color"], TOP_COLORS)
    df["cgrp"] = df["color"].where(df["color"].isin(col_names), OTHER)
    colpiv = df.groupby(["cgrp", "seg"]).size().unstack(fill_value=0).reindex(
        index=col_names, columns=segs, fill_value=0)
    colors_chart = {"names": col_names,
                    "series": [{"name": _seg_label(s), "data": [int(v) for v in colpiv[s]]} for s in segs]}
    t_colors = [{"name": c, "cols": [_int(colpiv.loc[c, s]) for s in segs]} for c in col_names]

    # ── Status / cancellation ──────────────────────────────────────────────
    canc = df[~df["active"]]
    r_names, _ = _top_other(canc["reason"], TOP_REASONS)
    cg = canc["reason"].where(canc["reason"].isin(r_names), OTHER)
    rpiv = canc.assign(rg=cg).groupby(["rg", "seg"]).size().unstack(fill_value=0).reindex(
        index=r_names, columns=segs, fill_value=0)
    status_chart = {"names": r_names,
                    "series": [{"name": _seg_label(s), "data": [int(v) for v in rpiv[s]]} for s in segs]}
    t_status = [{"name": r, "cols": [_int(rpiv.loc[r, s]) for s in segs]} for r in r_names]
    n_canc = int(len(canc))
    seg_canc = [{"name": _seg_label(s),
                 "share": f"{(~df.loc[df['seg'] == s, 'active']).mean() * 100:.1f}"} for s in segs]

    # ── Licence validity (non-cancelled) ───────────────────────────────────
    act = df[df["active"] & df["tokef"].notna()]
    tm_ = act["tokef"].dt.to_period("M")
    months = pd.period_range(tm_.min(), tm_.max(), freq="M") if len(tm_) else []
    exp = None
    if ref is not None:
        expired_mask = act["tokef"] < ref
        e_counts = tm_[expired_mask].value_counts()
        v_counts = tm_[~expired_mask].value_counts()
        n_act = int(df["active"].sum())
        n_exp = int(expired_mask.sum())
        exp = {"n": n_exp, "share": n_exp / n_act if n_act else 0.0, "ref_he": _date_he(ref),
               "taxi": int((act.loc[expired_mask, "seg"] == "M1").sum())}
    else:
        e_counts = pd.Series(dtype=int)
        v_counts = tm_.value_counts()
    tokef_chart = {"x": [f"{p.year}-{p.month:02d}" for p in months],
                   "expired": [int(e_counts.get(p, 0)) for p in months],
                   "valid": [int(v_counts.get(p, 0)) for p in months]}
    t_tokef = [{"name": f"{MONTHS_HE[p.month - 1]} {p.year}", "cols": [_int(e_counts.get(p, 0)), _int(v_counts.get(p, 0))]}
               for p in months]
    if ref is not None:
        nxt = pd.period_range(ref.to_period("M") + 1, ref.to_period("M") + 3, freq="M")
        due3 = int(sum(int(v_counts.get(p, 0)) for p in nxt))
    else:
        due3 = 0

    # ── KPIs ───────────────────────────────────────────────────────────────
    if exp is None:
        exp_disp, exp_tone, exp_val = "—", "brand", None
    else:
        exp_disp, exp_val = _pct(exp["share"]), round(exp["share"], 4)
        exp_tone = "ok" if exp["share"] < EXPIRED_OK else ("warn" if exp["share"] < EXPIRED_WARN else "danger")

    # ── Insights ───────────────────────────────────────────────────────────
    type_med = [{"name": t, "med": int(type_year[t]), "n": int((yv["vtype"] == t).sum())}
                for t in type_year.index]
    type_med.sort(key=lambda r: r["name"])
    rules = [
        ("segments", insight_segments(seg_counts, n)),
        ("young", insight_young(years, y_cmp)),
        ("taxi_leader", insight_leader(df, {"M1"}, "מוניות")),
        ("bus_leader", insight_leader(df, {"M2", "M3"}, "אוטובוסים (כולל זעירים)")),
        ("china", insight_china(cn_share, y_cmp)),
        ("age_gap", insight_age_gap(type_med)),
        ("expired", insight_expired(exp)),
        ("cancelled", insight_cancelled(df, n)),
        ("seats", insight_seats(df)),
        ("color", insight_color(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    ref_txt = _date_he(ref) if ref is not None else ""
    partial_note = (f" שנת {y1} עדיין בעיצומה — כלים מתווספים אליה לאורך השנה." if partial_year else "")
    taxi_n = dict(seg_counts).get("M1", 0)

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} כלי רכב ציבוריים — {_int(taxi_n)} מוניות לצד אוטובוסים "
                           f"ואוטובוסים זעירים — שנות ייצור \u2066{y0}–{y1}\u2069. "
                           f"{_pct(young_share)} מהם יוצרו בשנים \u2066{y_cmp - YOUNG_YEARS + 1}–{y_cmp}\u2069, "
                           f"והם מציעים יחד {_int(total_seats)} מקומות ישיבה."),
            "dataset_kind": "registry",
            "related_ids": [
                "27047419-e1fc-4f1d-bb15-7f5f0805d226",
                "1e9d4542-97af-47ac-a780-f2a6b291b1f5",
                "0f16b39a-6016-408d-805d-31f40d5a0990",
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "0219b34f-43c7-435b-bdfe-e65e944cde50",
            ],
            "suggested_tags": ["תחבורה ציבורית", "מוניות", "אוטובוסים", "צי הרכב", "רישוי רכב", "תחבורה"],
            "temporal_coverage": f"{y0}/{y1}",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "seats": {"value": total_seats, "display": _int(total_seats), "tone": "brand"},
            "year": {"value": year_med, "display": str(year_med), "tone": "info"},
            "expired": {"value": exp_val, "display": exp_disp, "tone": exp_tone},
        },
        "charts": {
            "types": {"names": t_names, "values": t_vals, "seg_idx": type_colors},
            "years": years_chart,
            "box": box_chart,
            "taxi_brands": taxi_brands,
            "bus_brands": bus_brands,
            "taxi_models": taxi_models,
            "bus_models": bus_models,
            "country": country_chart,
            "seats": seats_chart,
            "colors": colors_chart,
            "status": status_chart,
            "tokef": tokef_chart,
        },
        "tables": {
            "seg_cols": [_seg_label(s) for s in segs],
            "segs": t_segs,
            "types": t_types,
            "years": t_years,
            "box": t_box,
            "taxi_brands": t_taxi_brands,
            "bus_brands": t_bus_brands,
            "taxi_models": t_taxi_models,
            "bus_models": t_bus_models,
            "country_cols": c_order,
            "country": t_country,
            "seats": t_seats,
            "colors": t_colors,
            "status": t_status,
            "seg_canc": seg_canc,
            "tokef": t_tokef,
        },
        "insights": insights,
        "labels": {
            "lede": (f"המאגר מונה {_int(n)} כלי רכב ציבוריים הרשומים במשרד התחבורה — מוניות, "
                     f"מוניות שירות, אוטובוסים זעירים ואוטובוסים עירוניים, בין-עירוניים, להסעות ולסיורים — "
                     f"שנות ייצור \u2066{y0}–{y1}\u2069. {_int(n_canc)} מהרשומות ({_pct(n_canc / n)}) כבר נושאות "
                     f"סימון ביטול, והן נכללות בספירות ומוצגות בנפרד בפרק מצב הרישום."),
            "total_kpi": "כלי רכב ציבוריים בקובץ",
            "seats_kpi": "מקומות ישיבה לנוסעים",
            "year_kpi": "שנת ייצור חציונית",
            "expired_kpi": (f"מהכלים הלא מבוטלים — רישיון שפג לפני {ref_txt}" if ref is not None
                            else "רישיון שפג תוקפו"),
            "segs_caption": "הצי לפי קטגוריית הגודל: כלים, מקומות ישיבה ומשקל כולל חציוני.",
            "types_note": (f"{_int(df['vtype'].nunique())} סוגי כלים ציבוריים. הצבע מציין את קטגוריית "
                           f"הגודל של רוב הכלים בסוג. מקומות הישיבה כוללים את המושבים שליד הנהג."),
            "types_aria": f"תרשים עמודות: כלי רכב ציבוריים לפי סוג, {len(t_names)} קטגוריות.",
            "years_note": (f"כל עמודה — הכלים משנת ייצור אחת, לפי קטגוריית הגודל. "
                           f"{_pct(young_share)} מהצי יוצרו בשנים \u2066{y_cmp - YOUNG_YEARS + 1}–{y_cmp}\u2069."
                           f"{partial_note}"),
            "years_aria": f"תרשים עמודות מוערם: כלי רכב לפי שנת ייצור וקטגוריה, \u2066{y0}–{y1}\u2069.",
            "years_caption": "כלי רכב לפי שנת ייצור וקטגוריית גודל.",
            "box_note": (f"שנת הייצור בכל סוג שיש בו לפחות {BOX_MIN} כלים, מהוותיק לחדש. "
                         f"התיבה — רבעון תחתון עד עליון, הקו — החציון, השפמים — אחוזון 5 עד 95."),
            "box_aria": f"תרשים תיבה: שנת ייצור לפי סוג כלי, {len(box_rows)} סוגים.",
            "taxi_brands_note": (f"{_int(n_taxi_brands)} יצרנים בין {_int(len(taxis))} המוניות. "
                                 f"מפעלי אותו יצרן בארצות שונות אוחדו."),
            "taxi_brands_aria": f"תרשים עמודות: {TOP_BRANDS} יצרני המוניות המובילים.",
            "bus_brands_note": (f"{_int(n_bus_brands)} יצרנים בין {_int(len(buses))} האוטובוסים והאוטובוסים "
                                f"הזעירים. מפעלי אותו יצרן אוחדו; דיימלר קרייזלר נרשם בנפרד ממרצדס בנץ, כמו במרשם."),
            "bus_brands_aria": f"תרשים עמודות: {TOP_BRANDS} יצרני האוטובוסים המובילים.",
            "taxi_models_note": ("משפחת הדגם לפי הכינוי המסחרי הרשום (המילה הראשונה בו), כך שגרסאות "
                                 "של אותו דגם מאוחדות."),
            "taxi_models_aria": f"תרשים עמודות: {TOP_MODELS} דגמי המוניות הנפוצים.",
            "bus_models_note": (f"קוד הדגם של היצרן ({_int(n_bus_models)} צירופי יצרן ודגם). "
                                f"אותו דגם עשוי להופיע בכמה קודים לפי גרסה."),
            "bus_models_aria": f"תרשים עמודות: {TOP_MODELS} דגמי האוטובוסים הנפוצים.",
            "country_note": (f"ארץ המפעל של האוטובוסים והאוטובוסים הזעירים, כחלק מכלי כל שנת ייצור. "
                             f"בכלל הצי הזה {_pct(bus_cn_all)} מתוצרת סין. ארץ המפעל נגזרת מסיומת שם היצרן "
                             f"במרשם."),
            "country_aria": f"תרשים שטח מוערם: ארץ הייצור של האוטובוסים לפי שנת ייצור, \u2066{c_years[0] if c_years else y0}–{y1}\u2069.",
            "country_caption": f"חלק כל ארץ (%) ב-{min(TABLE_YEARS, len(c_years))} שנות הייצור האחרונות.",
            "seats_note": (f"מקומות הישיבה לנוסעים בכל כלי, כולל המושבים שליד הנהג. חציון: "
                           + "; ".join(f"{SEG_NAME.get(s, s)} {_int(seg_seat_med[s])}" for s in segs)
                           + (f". כלים ללא מספר מקומות רשום, שאינם בתרשים: {_int(n_no_seats)}." if n_no_seats else ".")),
            "seats_aria": "תרשים עמודות מוערם: כלי רכב לפי מספר מקומות ישיבה וקטגוריה.",
            "colors_note": "הצבע הרשום של הכלי, לפי קטגוריית גודל.",
            "colors_aria": f"תרשים עמודות: {len(col_names)} הצבעים הנפוצים לפי קטגוריה.",
            "status_note": (f"{_int(n_canc)} רשומות ({_pct(n_canc / n)}) נושאות סימון ביטול — הפקדת לוחית, "
                            f"פירוק, אובדן גמור, ביטול לפני מכירה ועוד. שיעור המבוטלים: "
                            + "; ".join(f"{r['name']} {r['share']}%" for r in seg_canc) + "."),
            "status_aria": "תרשים עמודות: רשומות מבוטלות לפי סיבת הביטול וקטגוריה.",
            "tokef_note": ((f"מועד פקיעת הרישיון של {_int(len(act))} הכלים שאינם מבוטלים, לפי חודש. "
                            f"באדום — רישיונות שפגו לפני {ref_txt}, התאריך האחרון בנתונים; "
                            f"בשלושת החודשים הבאים ({MONTHS_HE[ref.month % 12]}–{MONTHS_HE[(ref.month + 2) % 12]}) "
                            f"פוקעים עוד {_int(due3)}.") if ref is not None else
                           f"מועד פקיעת הרישיון של {_int(len(act))} הכלים שאינם מבוטלים, לפי חודש."),
            "tokef_aria": "תרשים עמודות: כלי רכב לפי חודש פקיעת הרישיון.",
        },
        "flags": {"expired": exp is not None},
    }
