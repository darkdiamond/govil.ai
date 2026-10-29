"""יישובים בישראל: קובץ היישובים של הלמ"ס (one file per year).

Each resource is a full yearly snapshot of the CBS localities register: one
row per locality code (סמל יישוב) with its district, sub-district, municipal
status (city / local council / regional council), settlement form code,
population split, founding year, elevation and ITM coordinates. The files
2018 onward share the three columns the input selects on (name, code, year);
everything else drifts between years (district names appear in 2021, the
population columns carry the year in their name, 2023 adds foreigners and
marks values provisional). So compute() resolves every column per year by
name prefix instead of hard-coding it.

The page leads with the LATEST year (registry lookup). Change over time uses
all years, and growth rates use only the longest run of years with the same
population definition: the 2023 file is the first to count foreigners
separately inside the total, so 2018-2022 is one run and 2023 starts another.
A new yearly file flows in through by_schema; once the 2023+ run is longer it
becomes the growth window automatically.

Settlement-form codes are grouped into broad CBS families (urban, moshav,
kibbutz, community, ...). The grouping is by code range, checked against the
named localities in the data; an unknown code falls into "אחר".
"""
import math
import re

import pandas as pd

YEAR, CODE, NAME = "שנה", "סמל יישוב", "שם יישוב"
SUMMARY_MAX = 155
TOP_N = 15
GROWTH_MIN_POP = 5000
SMALL_POP = 1000
MAP_CHUNK = 700

FORM_ORDER = [
    "עירוני",
    "מושב",
    "קיבוץ",
    "יישוב קהילתי",
    "כפרי אחר",
    "מוסדי",
    "כפר ערבי",
    "שבט בדואי",
    "ללא אוכלוסייה (שטח, אזור תעשייה)",
    "אחר",
]

SIZE_BANDS = [
    (0, 100, "עד 99"),
    (100, 500, "100 עד 499"),
    (500, 1000, "500 עד 999"),
    (1000, 2000, "1,000 עד 1,999"),
    (2000, 5000, "2,000 עד 4,999"),
    (5000, 10000, "5,000 עד 9,999"),
    (10000, 20000, "10,000 עד 19,999"),
    (20000, 50000, "20,000 עד 49,999"),
    (50000, 100000, "50,000 עד 99,999"),
    (100000, 200000, "100,000 עד 199,999"),
    (200000, None, "200,000 ומעלה"),
]


# ---------------------------------------------------------------- helpers

def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _disp_name(s):
    """CBS marks some names with a footnote '*'; drop it for display."""
    return _clean(str(s).replace("*", ""))


def _num(s):
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce"
    )


def _i(v):
    return f"{int(round(v)):,}"


def _pct(v, d=1):
    return f"{v * 100:.{d}f}%"


def _signed_pct(v, d=1):
    s = f"{abs(v) * 100:.{d}f}%"
    if round(abs(v) * 100, d) == 0:
        return s
    return ("+" if v > 0 else "−") + s


def _chg(v, d=1):
    """'גידול של 5.2%' / 'ירידה של 1.0%' / 'ללא שינוי'."""
    if round(abs(v) * 100, d) == 0:
        return "ללא שינוי"
    return f"{'גידול' if v > 0 else 'ירידה'} של {abs(v) * 100:.{d}f}%"


def _dist(n):
    """'מחוז הצפון', but 'אזור יהודה ושומרון' as is."""
    return n if n.startswith("אזור") else f"מחוז {n}"


def _col(df, prefix, exclude=()):
    """First column (sorted) starting with `prefix` that has data in df."""
    for c in sorted(df.columns):
        if c.startswith(prefix) and not any(c.startswith(x) for x in exclude):
            if (df[c].astype(str).str.strip() != "").any():
                return c
    return None


def _form_bucket(code):
    if code is None or (isinstance(code, float) and math.isnan(code)):
        return "אחר"
    c = int(code)
    if c in (191, 192) or c in (310, 320):
        return "מושב"
    if c in (193, 330):
        return "קיבוץ"
    if 100 <= c < 300:
        return "עירוני"
    if c == 370:
        return "יישוב קהילתי"
    if c == 350:
        return "כפרי אחר"
    if c == 340:
        return "מוסדי"
    if c in (440, 450):
        return "כפר ערבי"
    if c == 460:
        return "שבט בדואי"
    if 500 <= c < 600:
        return "ללא אוכלוסייה (שטח, אזור תעשייה)"
    return "אחר"


def _muni_kind(name):
    n = _clean(name)
    if n == "עירייה":
        return "עירייה"
    if n == "מועצה מקומית":
        return "מועצה מקומית"
    if n.startswith("מועצה אזורית"):
        return "מועצה אזורית"
    if "חסר" in n or n == "":
        return "ללא מעמד מוניציפלי"
    return "אחר"


# ITM (EPSG:2039, GRS80 transverse Mercator) -> geographic. The Israel 1993
# -> WGS84 datum shift is a few metres, far below marker scale; skipped.
_A = 6378137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_K0 = 1.0000067
_LAT0 = math.radians(31.7343936111)
_LON0 = math.radians(35.2045169444)
_FE, _FN = 219529.584, 626907.390


def _meridian(phi):
    e2 = _E2
    return _A * (
        (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
        - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
        + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
        - (35 * e2 ** 3 / 3072) * math.sin(6 * phi)
    )


def _itm_to_wgs(x, y):
    m = _meridian(_LAT0) + (y - _FN) / _K0
    mu = m / (_A * (1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
        + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
        + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
        + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    )
    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    c1 = _EP2 * c * c
    t1 = t * t
    n1 = _A / math.sqrt(1 - _E2 * s * s)
    r1 = _A * (1 - _E2) / (1 - _E2 * s * s) ** 1.5
    d = (x - _FE) / (n1 * _K0)
    lat = phi1 - (n1 * t / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * _EP2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * _EP2 - 3 * c1 * c1) * d ** 6 / 720
    )
    lon = _LON0 + (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * _EP2 + 24 * t1 * t1) * d ** 5 / 120
    ) / c
    return math.degrees(lat), math.degrees(lon)


def _decode_xy(raw):
    """CBS packs ITM as 'XXXXXXYYYYYY' (metres) or 'XXXXXYYYYY' (tens of metres)."""
    s = re.sub(r"\D", "", str(raw))
    if len(s) == 12:
        x, y = int(s[:6]), int(s[6:])
    elif len(s) == 10:
        x, y = int(s[:5]) * 10, int(s[5:]) * 10
    else:
        return None
    if not (100000 <= x <= 300000 and 350000 <= y <= 820000):
        return None
    return x, y


# ---------------------------------------------------------------- per-year frames

def _district_map(df):
    """Learn district code -> name from rows that carry both."""
    m = {}
    if "שם מחוז" not in df.columns or "סמל מחוז" not in df.columns:
        return m
    d = df[(df["שם מחוז"].str.strip() != "") & (df["סמל מחוז"].str.strip() != "")]
    pairs = d.groupby(["סמל מחוז", "שם מחוז"]).size().reset_index(name="n")
    pairs = pairs.sort_values(["סמל מחוז", "n", "שם מחוז"], ascending=[True, False, True])
    for _, r in pairs.drop_duplicates("סמל מחוז").iterrows():
        m[_clean(r["סמל מחוז"])] = _clean(r["שם מחוז"])
    return m


def _year_frame(sub, dmap):
    """Standardise one year's rows (columns resolved by prefix)."""
    sub = sub.loc[:, [c for c in sub.columns if (sub[c].astype(str).str.strip() != "").any()]]
    sub = sub.sort_values([CODE, NAME], kind="stable").drop_duplicates(CODE)
    out = pd.DataFrame({"code": sub[CODE].map(_clean), "name": sub[NAME].map(_disp_name)})
    total_col = _col(sub, "סך הכל אוכלוסייה")
    if total_col is None:
        raise ValueError("population column (סך הכל אוכלוסייה …) missing in a yearly file")
    out["pop"] = _num(sub[total_col]).fillna(0)
    jo = _col(sub, "יהודים ואחרים")
    ar = _col(sub, "ערבים")
    fo = _col(sub, "זרים")
    out["jo"] = _num(sub[jo]).fillna(0) if jo else 0.0
    out["arab"] = _num(sub[ar]).fillna(0) if ar else 0.0
    out["foreign"] = _num(sub[fo]).fillna(0) if fo else 0.0
    if "שם מחוז" in sub.columns:
        dist = sub["שם מחוז"].map(_clean)
    else:
        dcol = "סמל מחוז" if "סמל מחוז" in sub.columns else ("מחוז" if "מחוז" in sub.columns else None)
        dist = sub[dcol].map(lambda v: dmap.get(_clean(v), "")) if dcol else pd.Series("", index=sub.index)
    out["district"] = dist.replace("", "לא ידוע")
    return out.reset_index(drop=True), sub.reset_index(drop=True), {
        "has_foreign": fo is not None,
        "provisional": "ארעי" in total_col,
    }


def _runs(years, key):
    """Longest run of consecutive (in list order) years with the same key."""
    best, cur = [], []
    for y in years:
        if cur and key[y] == key[cur[-1]]:
            cur.append(y)
        else:
            cur = [y]
        if len(cur) > len(best) or (len(cur) == len(best) and cur[-1] > (best[-1] if best else -1)):
            best = list(cur)
    return best


# ---------------------------------------------------------------- compute

def compute(frames):
    df = frames["files"].fillna("").astype(str)
    df[YEAR] = df[YEAR].str.strip()
    df["_y"] = pd.to_numeric(df[YEAR].str.replace(".0", "", regex=False), errors="coerce")
    df = df[df["_y"].notna() & (df[CODE].str.strip() != "")]
    dmap = _district_map(df)

    yfr, raw, meta = {}, {}, {}
    for y in sorted(int(v) for v in df["_y"].unique()):
        sub = df[df["_y"] == y]
        yfr[y], raw[y], meta[y] = _year_frame(sub, dmap)
    all_years = sorted(yfr)
    latest = all_years[-1]
    # A yearly file lists every locality; a much shorter one is partial.
    full_n = max(len(f) for f in yfr.values())
    partial = [y for y in all_years if len(yfr[y]) < 0.9 * full_n]
    years = [y for y in all_years if y not in partial]
    if latest not in years:
        years.append(latest)
        years.sort()

    L = yfr[latest].copy()
    R = raw[latest]
    for need in ("שם מחוז", "שם נפה", "שם מעמד מונציפאלי"):
        if need not in R.columns:
            raise ValueError(f"latest file lacks {need}")
    L["nafa"] = R["שם נפה"].map(_clean).replace("", "לא ידוע")
    L["muni"] = R["שם מעמד מונציפאלי"].map(_clean)
    L["muni_kind"] = L["muni"].map(_muni_kind)
    form_col = _col(R, "צורת יישוב")
    L["form"] = (_num(R[form_col]) if form_col else pd.Series(float("nan"), index=R.index)).map(_form_bucket)
    found_col = _col(R, "שנת ייסוד")
    L["founded_raw"] = R[found_col].map(_clean) if found_col else ""
    L["founded"] = _num(L["founded_raw"]) if found_col else float("nan")
    elev_col = _col(R, "גובה")
    L["elev"] = _num(R[elev_col]) if elev_col else float("nan")
    xy_col = _col(R, "קואורדינטות")
    L["xy"] = R[xy_col].map(_decode_xy) if xy_col else None
    clu_col = _col(R, "אשכול רשויות")
    L["cluster"] = R[clu_col].map(_clean) if clu_col else ""
    lmeta = meta[latest]

    pop_rows = L[L["pop"] > 0]
    n_entries, n_pop = len(L), len(pop_rows)
    total = float(pop_rows["pop"].sum())
    if n_pop == 0 or total <= 0:
        raise ValueError("latest file has no population")
    prov = " (ארעי)" if lmeta["provisional"] else ""

    labels, charts, tables, flags = {}, {}, {}, {}
    insights = []

    # ---------- national series by year
    yr_tot = [float(yfr[y]["pop"].sum()) for y in years]
    yr_n = [int((yfr[y]["pop"] > 0).sum()) for y in years]
    run = _runs(years, {y: meta[y]["has_foreign"] for y in years})
    has_growth = len(run) >= 2
    first_foreign = next((y for y in years if meta[y]["has_foreign"]), None)
    def_break = first_foreign if first_foreign is not None and first_foreign != years[0] else None
    charts["years"] = {
        "x": [str(y) for y in years],
        "y": [int(v) for v in yr_tot],
        "n": yr_n,
        "break": str(def_break) if def_break else None,
    }
    tables["years"] = [
        {"year": str(y), "pop": _i(t), "n": f"{n:,}", "note": ("כולל זרים" if meta[y]["has_foreign"] else "") + (" (ארעי)" if meta[y]["provisional"] else "")}
        for y, t, n in zip(years, yr_tot, yr_n)
    ]
    flags["years"] = len(years) >= 2
    lede = f"סך האוכלוסייה הרשומה ביישובים בכל קובץ שנתי, {years[0]}-{years[-1]}."
    if def_break:
        lede += (f" מקובץ {def_break} הסך כולל גם זרים, המופיעים בעמודה נפרדת,"
                 " ולכן הקפיצה בשנה זו נובעת בחלקה משינוי ההגדרה.")
    if partial:
        lede += " קבצים חלקיים לא נכללו: " + ", ".join(str(p) for p in partial) + "."
    labels["years_lede"] = lede
    labels["years_aria"] = (f"גרף עמודות: אוכלוסיית היישובים לפי שנת הקובץ, {years[0]}-{years[-1]}. "
                            f"בשנת {latest}: {_i(total)} תושבים.")

    # growth window
    if has_growth:
        g0, g1 = run[0], run[-1]
        A, B = yfr[g0], yfr[g1]
        t0, t1 = float(A["pop"].sum()), float(B["pop"].sum())
        nat_growth = (t1 - t0) / t0 if t0 else 0.0
        labels["growth_window"] = f"{g0}-{g1}"
    # ---------- KPIs
    kpis = {
        "entries": {"value": n_entries, "display": f"{n_entries:,}", "tone": "brand"},
        "populated": {"value": n_pop, "display": f"{n_pop:,}", "tone": "brand"},
        "population": {"value": int(total), "display": _i(total), "tone": "brand"},
    }
    kpi_labels = {
        "entries": f"רשומות בקובץ {latest} (יישובים ושטחים)",
        "populated": f"יישובים עם אוכלוסייה ב-{latest}",
        "population": f"תושבים ביישובים, {latest}{prov}",
    }
    order = ["entries", "populated", "population"]
    if has_growth:
        kpis["growth"] = {"value": round(nat_growth * 100, 2), "display": _signed_pct(nat_growth),
                          "tone": "ok" if nat_growth > 0 else ("danger" if nat_growth < 0 else "brand")}
        kpi_labels["growth"] = f"שינוי באוכלוסייה {g0}-{g1}"
        order.append("growth")
    n_city = int((L["muni_kind"] == "עירייה").sum())
    rc = L[L["muni_kind"] == "מועצה אזורית"]
    n_rc = int(rc["muni"].nunique())
    kpis["cities"] = {"value": n_city, "display": f"{n_city:,}", "tone": "brand"}
    kpi_labels["cities"] = "עיריות"
    kpis["councils"] = {"value": n_rc, "display": f"{n_rc:,}", "tone": "brand"}
    kpi_labels["councils"] = "מועצות אזוריות"
    order += ["cities", "councils"]
    for k, v in kpi_labels.items():
        labels["kpi_" + k] = v

    # ---------- districts (latest)
    dg = pop_rows.groupby("district").agg(pop=("pop", "sum"), n=("code", "size")).reset_index()
    dg = dg.sort_values(["pop", "district"], ascending=[False, True], kind="stable")
    charts["district"] = {"names": dg["district"].tolist(), "pop": [int(v) for v in dg["pop"]],
                          "n": [int(v) for v in dg["n"]]}
    tables["district"] = [{"name": r.district, "pop": _i(r.pop), "share": _pct(r.pop / total), "n": f"{int(r.n):,}"}
                          for r in dg.itertuples()]
    top_d = dg.iloc[0]
    labels["district_lede"] = (f"{_dist(top_d.district)} הוא המאוכלס ביותר: {_i(top_d["pop"])} תושבים "
                               f"({_pct(top_d["pop"] / total)}) ב-{int(top_d.n):,} יישובים. "
                               f"אחריו {_dist(dg.iloc[1].district)} עם {_pct(dg.iloc[1]["pop"] / total)}.")
    labels["district_aria"] = (f"גרף עמודות: תושבים לפי מחוז, {latest}. המאוכלס ביותר: {top_d.district}, "
                               f"{_i(top_d["pop"])} תושבים.")

    # ---------- district growth (run)
    flags["dgrowth"] = False
    if has_growth:
        da = A.groupby("district")["pop"].sum()
        db = B.groupby("district")["pop"].sum()
        rows = []
        for d in sorted(set(da.index) | set(db.index)):
            a, b = float(da.get(d, 0)), float(db.get(d, 0))
            if a > 0 and d != "לא ידוע":
                rows.append((d, a, b, (b - a) / a))
        rows.sort(key=lambda r: (-r[3], r[0]))
        if len(rows) >= 2:
            flags["dgrowth"] = True
            charts["dgrowth"] = {"names": [r[0] for r in rows], "g": [round(r[3] * 100, 2) for r in rows],
                                 "nat": round(nat_growth * 100, 2)}
            tables["dgrowth"] = [{"name": r[0], "a": _i(r[1]), "b": _i(r[2]), "g": _signed_pct(r[3])} for r in rows]
            labels["dgrowth_lede"] = (f"שינוי האוכלוסייה בכל מחוז בין {g0} ל-{g1}, שנים שבהן הגדרת האוכלוסייה בקובץ זהה. "
                                      f"הממוצע הארצי: {_signed_pct(nat_growth)}.")
            labels["dgrowth_aria"] = (f"גרף עמודות: שינוי באוכלוסייה לפי מחוז, {g0}-{g1}. הגידול המהיר ביותר: "
                                      f"{rows[0][0]}, {_signed_pct(rows[0][3])}.")
            hi, lo = rows[0], rows[-1]
            if hi[3] - lo[3] >= 0.01:
                insights.append({"id": "district_growth", "text_he": (
                    f"בין {g0} ל-{g1} נרשם ב{_dist(hi[0])} השינוי הגבוה ביותר באוכלוסייה ({_chg(hi[3])}), "
                    f"וב{_dist(lo[0])} הנמוך ביותר ({_chg(lo[3])}); בכל הארץ: {_chg(nat_growth)}.")})

    # ---------- composition by district (latest)
    comp = pop_rows.groupby("district")[["jo", "arab", "foreign"]].sum()
    comp = comp.loc[[d for d in charts["district"]["names"] if d in comp.index]]
    flags["foreign"] = bool(lmeta["has_foreign"])
    charts["comp"] = {
        "names": comp.index.tolist(),
        "jo": [int(v) for v in comp["jo"]],
        "arab": [int(v) for v in comp["arab"]],
        "foreign": [int(v) for v in comp["foreign"]],
    }
    tables["comp"] = []
    for d, r in comp.iterrows():
        s = r["jo"] + r["arab"] + r["foreign"]
        tables["comp"].append({"name": d, "jo": _pct(r["jo"] / s) if s else "", "arab": _pct(r["arab"] / s) if s else "",
                               "foreign": _pct(r["foreign"] / s) if s else ""})
    jo_t, ar_t, fo_t = float(pop_rows["jo"].sum()), float(pop_rows["arab"].sum()), float(pop_rows["foreign"].sum())
    comp_t = jo_t + ar_t + fo_t
    if comp_t > 0:
        arab_share_d = (comp["arab"] / comp.sum(axis=1)).sort_values(ascending=False)
        labels["comp_lede"] = (f"ביישובים בכל הארץ: יהודים ואחרים {_pct(jo_t / comp_t)}, ערבים {_pct(ar_t / comp_t)}"
                               + (f", זרים {_pct(fo_t / comp_t)}" if flags["foreign"] else "")
                               + f". שיעור הערבים הגבוה ביותר: {_dist(arab_share_d.index[0])} ({_pct(arab_share_d.iloc[0])}).")
        labels["comp_aria"] = (f"גרף עמודות מוערמות: הרכב האוכלוסייה לפי מחוז, {latest}. שיעור הערבים הגבוה ביותר ב"
                               f"{_dist(arab_share_d.index[0])}, {_pct(arab_share_d.iloc[0])}.")
    flags["comp"] = comp_t > 0
    if flags["foreign"] and fo_t > 0:
        fr = pop_rows[pop_rows["pop"] >= 500].copy()
        fr["fs"] = fr["foreign"] / fr["pop"]
        fr = fr.sort_values(["fs", "code"], ascending=[False, True], kind="stable")
        lead = fr.iloc[0] if len(fr) else None
        first = def_break == latest
        txt = (f"{'לראשונה, קובץ ' + str(latest) + ' מפריד' if first else 'קובץ ' + str(latest) + ' מפריד'} זרים מתוך סך האוכלוסייה: "
               f"{_i(fo_t)} ({_pct(fo_t / total)} מהתושבים).")
        if lead is not None and lead["fs"] >= 0.2:
            txt += f" השיעור הגבוה ביותר ביישוב של 500 תושבים ומעלה: {lead['name']} ({_pct(lead['fs'])})."
        insights.append({"id": "foreign", "text_he": txt})

    # ---------- settlement form
    fg = L.groupby("form").agg(n=("code", "size"), pop=("pop", "sum")).reindex(FORM_ORDER).dropna(how="all").fillna(0)
    fg = fg[fg["n"] > 0]
    charts["form"] = {"names": fg.index.tolist(), "n": [int(v) for v in fg["n"]],
                      "share": [round(v / total * 100, 2) for v in fg["pop"]]}
    tables["form"] = [{"name": k, "n": f"{int(r.n):,}", "pop": _i(r["pop"]), "share": _pct(r["pop"] / total)} for k, r in fg.iterrows()]
    big_form = fg["n"].drop(labels=["ללא אוכלוסייה (שטח, אזור תעשייה)"], errors="ignore").sort_values(ascending=False)
    urban = fg.loc["עירוני"] if "עירוני" in fg.index else None
    if urban is not None:
        labels["form_lede"] = (f"{int(urban.n):,} יישובים עירוניים ({_pct(urban.n / n_entries)} מהרשומות) מרכזים "
                               f"{_pct(urban["pop"] / total)} מהאוכלוסייה. הצורה הנפוצה ביותר במספר יישובים: {big_form.index[0]} "
                               f"({int(big_form.iloc[0]):,}).")
    else:
        labels["form_lede"] = f"הצורה הנפוצה ביותר במספר יישובים: {big_form.index[0]} ({int(big_form.iloc[0]):,})."
    labels["form_aria"] = f"גרף עמודות: מספר יישובים ושיעור מהאוכלוסייה לפי צורת יישוב, {latest}."
    if urban is not None and "מושב" in fg.index and "קיבוץ" in fg.index:
        rural_n = fg.loc["מושב"].n + fg.loc["קיבוץ"].n
        rural_p = fg.loc["מושב"]["pop"] + fg.loc["קיבוץ"]["pop"]
        if rural_n > urban.n:
            insights.append({"id": "rural", "text_he": (
                f"מושבים וקיבוצים הם {int(rural_n):,} יישובים, יותר מהיישובים העירוניים ({int(urban.n):,}), "
                f"אבל גרים בהם רק {_pct(rural_p / total)} מהתושבים, לעומת {_pct(urban["pop"] / total)} ביישובים העירוניים.")})

    # ---------- municipal status
    mg = L.groupby("muni_kind").agg(n=("code", "size"), pop=("pop", "sum"))
    m_order = [k for k in ["עירייה", "מועצה מקומית", "מועצה אזורית", "ללא מעמד מוניציפלי", "אחר"] if k in mg.index]
    mg = mg.loc[m_order]
    charts["muni"] = {"names": m_order, "n": [int(v) for v in mg["n"]], "pop": [int(v) for v in mg["pop"]]}
    tables["muni"] = [{"name": k, "n": f"{int(r.n):,}", "pop": _i(r["pop"]), "share": _pct(r["pop"] / total)} for k, r in mg.iterrows()]
    rc_pop = float(mg.loc["מועצה אזורית"]["pop"]) if "מועצה אזורית" in mg.index else 0.0
    rc_n = int(mg.loc["מועצה אזורית"].n) if "מועצה אזורית" in mg.index else 0
    labels["muni_lede"] = (f"{n_city:,} עיריות ו-{int(mg.loc['מועצה מקומית'].n) if 'מועצה מקומית' in mg.index else 0:,} מועצות מקומיות "
                           f"בקובץ. {rc_n:,} רשומות שייכות ל-{n_rc:,} מועצות אזוריות, "
                           f"ובהן {_pct(rc_pop / total)} מהתושבים.")
    labels["muni_aria"] = f"גרף עמודות: יישובים ותושבים לפי מעמד מוניציפלי, {latest}."

    # ---------- regional councils
    flags["councils"] = n_rc > 0
    if n_rc:
        rg = rc.groupby("muni").agg(n=("code", "size"), pop=("pop", "sum")).reset_index()
        rg["short"] = rg["muni"].str.replace("מועצה אזורית ", "", regex=False)
        rg = rg.sort_values(["n", "pop", "muni"], ascending=[False, False, True], kind="stable").head(TOP_N)
        charts["councils"] = {"names": rg["short"].tolist(), "n": [int(v) for v in rg["n"]], "pop": [int(v) for v in rg["pop"]]}
        tables["councils"] = [{"name": r.short, "n": f"{int(r.n):,}", "pop": _i(r.pop)} for r in rg.itertuples()]
        t = rg.iloc[0]
        labels["councils_lede"] = (f"{min(TOP_N, n_rc)} המועצות האזוריות עם מספר הרשומות הגדול ביותר בקובץ {latest}. "
                                   f"בראש: {t.short}, עם {int(t.n):,} רשומות ו-{_i(t["pop"])} תושבים.")
        labels["councils_aria"] = (f"גרף עמודות: מועצות אזוריות לפי מספר יישובים, {latest}. בראש: {t.short} "
                                   f"עם {int(t.n):,} רשומות.")
        rgall = rc.groupby("muni").agg(pop=("pop", "sum")).reset_index().sort_values(["pop", "muni"], ascending=[False, True])
        rp = rgall.iloc[0]
        insights.append({"id": "councils", "text_he": (
            f"בקובץ {n_rc:,} מועצות אזוריות. ב{t.short} הכי הרבה רשומות ({int(t.n):,}), "
            f"והמאוכלסת ביותר היא {rp.muni.replace('מועצה אזורית ', '')} עם {_i(rp['pop'])} תושבים.")})

    # ---------- local-authority clusters (only when named, not coded)
    cl = L[L["cluster"] != ""]
    named = len(cl) and not cl["cluster"].str.fullmatch(r"[\d.]+").all()
    flags["clusters"] = False
    if named:
        cl = cl[~cl["cluster"].str.fullmatch(r"[\d.]+")]
        member = cl[~cl["cluster"].str.startswith("ללא")]
        if len(member):
            cg = member.groupby("cluster").agg(n=("code", "size"), pop=("pop", "sum")).reset_index()
            cg["short"] = cg["cluster"].str.replace("אשכול רשויות ", "", regex=False).str.replace("אשכול ", "", regex=False)
            cg = cg.sort_values(["pop", "cluster"], ascending=[False, True], kind="stable")
            flags["clusters"] = True
            charts["clusters"] = {"names": cg["short"].tolist(), "pop": [int(v) for v in cg["pop"]], "n": [int(v) for v in cg["n"]]}
            tables["clusters"] = [{"name": r.cluster, "n": f"{int(r.n):,}", "pop": _i(r.pop)} for r in cg.itertuples()]
            none_n = int((cl["cluster"].str.startswith("ללא")).sum())
            labels["clusters_lede"] = (f"אשכולות רשויות מקומיות הם איגודים אזוריים של רשויות. {len(cg)} אשכולות מופיעים בקובץ, "
                                       f"ו-{len(member):,} רשומות משויכות לאחד מהם; {none_n:,} ללא שיוך לאשכול.")
            labels["clusters_aria"] = (f"גרף עמודות: תושבים לפי אשכול רשויות מקומיות, {latest}. הגדול ביותר: "
                                       f"{cg.iloc[0].short}.")

    # ---------- size distribution
    pops = pop_rows["pop"]
    sz = []
    for lo, hi, lab in SIZE_BANDS:
        m = (pops >= lo) & (pops < hi) if hi else (pops >= lo)
        sz.append((lab, int(m.sum()), float(pops[m].sum())))
    while sz and sz[-1][1] == 0:
        sz.pop()
    charts["size"] = {"names": [s[0] for s in sz], "n": [s[1] for s in sz], "share": [round(s[2] / total * 100, 2) for s in sz]}
    tables["size"] = [{"name": s[0], "n": f"{s[1]:,}", "share": _pct(s[2] / total)} for s in sz]
    small = pop_rows[pop_rows["pop"] < SMALL_POP]
    labels["size_lede"] = (f"{len(small):,} מתוך {n_pop:,} היישובים ({_pct(len(small) / n_pop)}) מונים פחות מ-{SMALL_POP:,} "
                           f"תושבים. החציון: {_i(pops.median())} תושבים ליישוב.")
    labels["size_aria"] = f"היסטוגרמה: מספר יישובים לפי גודל אוכלוסייה, {latest}. חציון {_i(pops.median())} תושבים."
    if len(small) / n_pop >= 0.3:
        insights.append({"id": "small", "text_he": (
            f"{len(small):,} יישובים ({_pct(len(small) / n_pop)}) מונים פחות מ-{SMALL_POP:,} תושבים, "
            f"אך יחד גרים בהם רק {_pct(small['pop'].sum() / total)} מהאוכלוסייה.")})

    # ---------- largest localities
    top = pop_rows.sort_values(["pop", "code"], ascending=[False, True], kind="stable").head(TOP_N)
    charts["top"] = {"names": top["name"].tolist(), "pop": [int(v) for v in top["pop"]]}
    tables["top"] = [{"name": r.name, "code": r.code, "district": r.district, "pop": _i(r.pop)} for r in top.itertuples()]
    top10 = top.head(10)
    share10 = float(top10["pop"].sum()) / total
    labels["top_lede"] = (f"היישוב הגדול ביותר: {top.iloc[0]['name']}, עם {_i(top.iloc[0]['pop'])} תושבים "
                          f"({_pct(top.iloc[0]['pop'] / total)}). עשרת הגדולים יחד: {_pct(share10)} מהאוכלוסייה.")
    labels["top_aria"] = (f"גרף עמודות: {len(top)} היישובים הגדולים, {latest}. הגדול ביותר: {top.iloc[0]['name']}, "
                          f"{_i(top.iloc[0]['pop'])} תושבים.")
    insights.append({"id": "concentration", "text_he": (
        f"עשרת היישובים הגדולים, מ{top10.iloc[0]['name']} ועד {top10.iloc[-1]['name']}, מרכזים {_pct(share10)} "
        f"מתושבי {n_pop:,} היישובים בקובץ {latest}.")})

    # ---------- fastest-growing localities (run)
    flags["growers"] = False
    if has_growth:
        g = B[["code", "name", "district", "pop"]].merge(A[["code", "pop"]], on="code", suffixes=("", "_0"))
        g = g[(g["pop_0"] >= GROWTH_MIN_POP)]
        g["g"] = (g["pop"] - g["pop_0"]) / g["pop_0"]
        gs = g.sort_values(["g", "code"], ascending=[False, True], kind="stable").head(TOP_N)
        if len(gs) >= 3:
            flags["growers"] = True
            charts["growers"] = {"names": gs["name"].tolist(), "g": [round(v * 100, 2) for v in gs["g"]],
                                 "nat": round(nat_growth * 100, 2)}
            tables["growers"] = [{"name": r.name, "district": r.district, "a": _i(r.pop_0), "b": _i(r.pop), "g": _signed_pct(r.g)}
                                 for r in gs.itertuples()]
            f = gs.iloc[0]
            labels["growers_lede"] = (f"היישובים שגדלו בשיעור הגבוה ביותר בין {g0} ל-{g1}, מבין {len(g):,} היישובים שמנו "
                                      f"{GROWTH_MIN_POP:,} תושבים ומעלה ב-{g0}. הממוצע הארצי: {_signed_pct(nat_growth)}.")
            labels["growers_aria"] = (f"גרף עמודות: היישובים שגדלו הכי מהר, {g0}-{g1}. בראש: {f['name']}, {_signed_pct(f['g'])}.")
            insights.append({"id": "growers", "text_he": (
                f"הגידול המהיר ביותר בין היישובים של {GROWTH_MIN_POP:,} תושבים ומעלה: {f['name']}, "
                f"מ-{_i(f['pop_0'])} ל-{_i(f['pop'])} תושבים בין {g0} ל-{g1} ({_signed_pct(f['g'])}).")})
            absg = g.assign(d=g["pop"] - g["pop_0"]).sort_values(["d", "code"], ascending=[False, True], kind="stable")
            ag = absg.iloc[0]
            if ag["code"] != f["code"] and ag["d"] > 0:
                insights.append({"id": "abs_growth", "text_he": (
                    f"במספרים מוחלטים, היישוב שהוסיף הכי הרבה תושבים בין {g0} ל-{g1}: {ag['name']}, "
                    f"עוד {_i(ag['d'])} תושבים ({_signed_pct(ag['g'])}).")})

    # ---------- founding decade
    fd = L[L["founded"].notna() & (L["founded"] >= 1000)]
    old_n = int((L["founded_raw"] == "ותיק").sum())
    flags["founded"] = len(fd) >= 20
    if flags["founded"]:
        dec = (fd["founded"] // 10 * 10).astype(int)
        lo_dec = 1900
        lab = dec.map(lambda d: "לפני 1900" if d < lo_dec else f"{d}-{d + 9}")
        key = dec.map(lambda d: lo_dec - 10 if d < lo_dec else d)
        fc = pd.DataFrame({"k": key, "lab": lab.where(dec >= lo_dec, "לפני 1900")}).groupby(["k", "lab"]).size().reset_index(name="n")
        fc = fc.sort_values("k")
        charts["founded"] = {"names": fc["lab"].tolist(), "n": [int(v) for v in fc["n"]]}
        tables["founded"] = [{"name": r.lab, "n": f"{int(r.n):,}"} for r in fc.itertuples()]
        peak = fc.sort_values(["n", "k"], ascending=[False, True]).iloc[0]
        labels["founded_lede"] = (f"שנת ייסוד ידועה ל-{len(fd):,} רשומות. העשור עם הכי הרבה יישובים שנוסדו: {peak.lab} "
                                  f"({int(peak.n):,} יישובים, {_pct(peak.n / len(fd))})."
                                  + (f" עוד {old_n:,} רשומות מסומנות כ\"ותיק\", בלי שנה." if old_n else ""))
        labels["founded_aria"] = f"גרף עמודות: יישובים לפי עשור ייסוד. השיא: {peak.lab}, {int(peak.n):,} יישובים."
        if peak.n / len(fd) >= 0.15:
            insights.append({"id": "founded", "text_he": (
                f"{int(peak.n):,} יישובים ({_pct(peak.n / len(fd))} מאלה ששנת ייסודם ידועה) נוסדו בעשור {peak.lab}, "
                f"יותר מבכל עשור אחר.")})

    # ---------- elevation
    ev = L[L["elev"].notna() & (L["pop"] > 0)]
    flags["elev"] = len(ev) >= 20
    if flags["elev"]:
        e = ev["elev"]
        step = 100
        lo_b = int(math.floor(e.min() / step) * step)
        hi_b = int(math.floor(e.max() / step) * step)
        if (hi_b - lo_b) / step > 18:
            step = 200
            lo_b = int(math.floor(e.min() / step) * step)
            hi_b = int(math.floor(e.max() / step) * step)
        names, ns = [], []
        for b in range(lo_b, hi_b + step, step):
            m = (e >= b) & (e < b + step)
            if b < 0:
                names.append(f"{-(b + step) + 1}-{-b} מתחת לים")
            else:
                names.append(f"{b}-{b + step - 1}")
            ns.append(int(m.sum()))
        charts["elev"] = {"names": names, "n": ns}
        tables["elev"] = [{"name": a, "n": f"{b:,}"} for a, b in zip(names, ns)]
        lowr = ev.sort_values(["elev", "code"], kind="stable").iloc[0]
        highr = ev.sort_values(["elev", "code"], ascending=[False, True], kind="stable").iloc[0]
        below = int((e < 0).sum())

        def _h(v):
            return f"{_i(abs(v))} מ' {'מתחת לפני הים' if v < 0 else 'מעל פני הים'}"

        labels["elev_lede"] = (f"גובה ממוצע של {len(ev):,} יישובים מיושבים, בגושים של {step} מ'. "
                               f"{below:,} יישובים נמצאים מתחת לפני הים.")
        labels["elev_aria"] = (f"היסטוגרמה: יישובים לפי גובה ממוצע. הנמוך ביותר: {lowr['name']}, {_h(lowr['elev'])}; "
                               f"הגבוה ביותר: {highr['name']}, {_h(highr['elev'])}.")
        insights.append({"id": "elevation", "text_he": (
            f"היישוב הנמוך ביותר בקובץ הוא {lowr['name']} ({_h(lowr['elev'])}), והגבוה ביותר {highr['name']} "
            f"({_h(highr['elev'])}).")})

    # ---------- register changes vs previous file
    flags["changes"] = False
    if len(years) >= 2:
        prev = years[-2]
        P = yfr[prev]
        pc, lc = set(P["code"]), set(L["code"])
        new = L[L["code"].isin(lc - pc)].sort_values(["pop", "code"], ascending=[False, True], kind="stable")
        gone = P[P["code"].isin(pc - lc)].sort_values(["name", "code"], kind="stable")
        mm = L[["code", "name"]].merge(P[["code", "name"]], on="code", suffixes=("", "_p"))
        ren = mm[mm["name"] != mm["name_p"]].sort_values(["name", "code"], kind="stable")
        if len(new) or len(gone) or len(ren):
            flags["changes"] = True
            tables["new"] = [{"name": r.name, "code": r.code, "muni": r.muni, "pop": _i(r.pop) if r.pop > 0 else "ללא"}
                             for r in new.head(20).itertuples()]
            tables["gone"] = [{"name": r.name, "code": r.code} for r in gone.head(20).itertuples()]
            tables["ren"] = [{"old": r.name_p, "new": r.name, "code": r.code} for r in ren.head(20).itertuples()]
            labels["changes_lede"] = (f"השוואה בין קובץ {prev} לקובץ {latest} לפי סמל יישוב: {len(new):,} סמלים חדשים, "
                                      f"{len(gone):,} סמלים שירדו מהקובץ ו-{len(ren):,} יישובים ששמם השתנה.")
            labels["new_caption"] = f"סמלי יישוב חדשים בקובץ {latest}"
            labels["gone_caption"] = f"סמלי יישוב שהופיעו בקובץ {prev} ולא בקובץ {latest}"
            labels["ren_caption"] = f"יישובים ששמם השתנה בין {prev} ל-{latest}"
            if len(new):
                names = ", ".join(new["name"].head(3).tolist())
                insights.append({"id": "new", "text_he": (
                    f"בקובץ {latest} נוספו {len(new):,} סמלי יישוב שלא הופיעו ב-{prev}, ביניהם {names}"
                    + (f"; {len(ren):,} יישובים שינו את שמם." if len(ren) else "."))})
        # over the whole span
        first_y = years[0]
        span_new = len(lc - set(yfr[first_y]["code"]))
        labels["span_new"] = (f"מאז קובץ {first_y} נוספו לרשימה {span_new:,} סמלי יישוב." if span_new and first_y != prev else "")

    # ---------- map
    pts = []
    dist_names = sorted(pop_rows["district"].unique().tolist())
    muni_names = sorted(pop_rows["muni"].unique().tolist())
    nafa_names = sorted(pop_rows["nafa"].unique().tolist())
    ni = {n: i for i, n in enumerate(nafa_names)}
    di = {n: i for i, n in enumerate(dist_names)}
    mi = {n: i for i, n in enumerate(muni_names)}
    for r in pop_rows.sort_values(["pop", "code"], ascending=[False, True], kind="stable").itertuples():
        if r.xy is None or (isinstance(r.xy, float)):
            continue
        lat, lon = _itm_to_wgs(*r.xy)
        pts.append([round(lat, 4), round(lon, 4), int(r.pop), r.name, int(r.code) if r.code.isdigit() else r.code,
                    di[r.district], mi[r.muni], ni[r.nafa]])
    flags["map"] = len(pts) >= 20
    if flags["map"]:
        charts["map"] = {"chunks": [pts[i:i + MAP_CHUNK] for i in range(0, len(pts), MAP_CHUNK)],
                         "max": max(p[2] for p in pts), "districts": dist_names, "munis": muni_names, "nafot": nafa_names,
                         "bounds": [[min(p[0] for p in pts), min(p[1] for p in pts)],
                                    [max(p[0] for p in pts), max(p[1] for p in pts)]]}
        labels["map_lede"] = (f"{len(pts):,} יישובים מיושבים לפי הקואורדינטות בקובץ {latest}; גודל העיגול לפי מספר התושבים. "
                              f"לחיצה על עיגול מציגה את סמל היישוב, המחוז, המועצה והאוכלוסייה.")
        labels["map_aria"] = (f"מפה אינטראקטיבית של {len(pts):,} יישובים בישראל לפי אוכלוסייה. גרסה נגישה: עיון בנתונים בתחתית העמוד.")

    # ---------- summary + agent_data
    summary = (f"איתור יישוב בישראל לפי שם או סמל יישוב: מחוז, נפה, מועצה ואוכלוסייה. "
               f"{n_pop:,} יישובים ו-{_i(total)} תושבים בקובץ {latest}.")
    if len(summary) > SUMMARY_MAX:
        summary = f"איתור יישוב לפי שם או סמל יישוב: מחוז, מועצה ואוכלוסייה. {n_pop:,} יישובים בקובץ {latest}."
    labels["lede"] = (f"קובץ היישובים של הלשכה המרכזית לסטטיסטיקה הוא הרשימה הרשמית של יישובי ישראל וסמליהם. "
                      f"הקובץ העדכני, {latest}{prov}, כולל {n_entries:,} רשומות: {n_pop:,} יישובים עם אוכלוסייה "
                      f"ועוד {n_entries - n_pop:,} שטחים, אזורי תעשייה ויישובים ללא נתוני אוכלוסייה. "
                      f"במאגר {len(all_years):,} קבצים שנתיים ברי השוואה, {all_years[0]}-{latest}.")

    insights.insert(0, {"id": "scale", "text_he": (
        f"בקובץ היישובים {latest} רשומים {n_pop:,} יישובים מיושבים ובהם {_i(total)} תושבים{prov}, "
        f"ב-{dg['district'].nunique():,} מחוזות.")})

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["יישובים", "סמל יישוב", "מחוזות", "מועצות אזוריות", "אוכלוסייה", "למ\"ס"],
            "related_ids": ["3bd97fde-6cc3-456d-ab63-1caad16b2b6a", "08645753-6d8b-4bb3-be0f-9cec2cd7557a", "6b729165-dc9c-49b3-afc6-eceabd8fef70"],
            "temporal_coverage": f"{all_years[0]}/{latest}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": order,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
        "latest": str(latest),
    }
