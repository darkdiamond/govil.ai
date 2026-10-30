"""רשימת תחנות הדלק הציבוריות כולל מידע גאוגרפי (משרד האנרגיה) — map page.

One row per public fuel station: `מס_מינהל_הדלק` (the Fuel Administration's
station number, an identifier), `חברה` (fuel company, or "אחר \\ עצמאי"),
`שם_תחנה`, `כתובת` (free-text address), `רשות_מקומית` (local authority; messy
spellings, "מ.א" prefixes), ITM `X`/`Y` and WGS84 `נ.צ. אורך`/`נ.צ. רוחב`.

The sister dataset "מאגר תחנות הדלק" carries the same stations without
coordinates; its page covers the company / authority statistics. This page
is geographic: a live GovMap of every station, stations by latitude band
(north to south, each band labelled by its leading authority), company mix
in three broad zones (cut by latitude, thresholds disclosed), distance from
each station to its nearest neighbour (haversine on the WGS84 columns), the
most isolated stations, and a data-quality list of stations that sit far
from the other stations of their listed authority.

Growth: the file is a snapshot replaced in place. Band width is picked from
the latitude span so the band chart stays <= MAX_BANDS rows; company series
are top-N + "אחר"; the nearest-neighbour pass is O(n^2) on numpy, which is
fine for a few thousand stations; tables are capped.
"""
import re

import numpy as np
import pandas as pd

LAT_MIN, LAT_MAX = 29.3, 33.5     # sanity box for Israel (WGS84)
LON_MIN, LON_MAX = 34.2, 35.95
NORTH_LAT = 32.5                  # zone cut: north of this latitude
SOUTH_LAT = 31.5                  # zone cut: south of this latitude
MAX_BANDS = 20
BAND_STEPS = [0.25, 0.5, 1.0]
TOP_ZONE_CO = 6                   # companies kept as zone-chart rows
TOP_ISO = 10
NN_BUCKETS = [(0, 0.1), (0.1, 0.3), (0.3, 0.5), (0.5, 1), (1, 2), (2, 5), (5, 10), (10, None)]
PAIR_KM = 0.3                     # "a neighbour across the road / same junction"
SUSPECT_MIN_STATIONS = 4          # authority needs this many mapped stations
SUSPECT_KM = 15                   # far from its authority's centre ...
SUSPECT_RATIO = 8                 # ... and this many times the authority's typical spread
TOP_SUSPECT = 12
ZONE_GAP = 0.10                   # a company's zone share must differ by this from the overall

INDEPENDENT = "עצמאי / אחר"
OTHER = "אחר"
ZONES = ["צפון", "מרכז", "דרום"]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def km(v):
    return f"{v:,.1f}"


def clean(s):
    return " ".join(str(s).replace("\xa0", " ").split())


def key_of(s):
    return re.sub(r"[\s\-־–'׳\"״.]", "", s)


def display_map(series):
    df = pd.DataFrame({"raw": series, "key": series.map(key_of)})
    counts = df.groupby(["key", "raw"]).size().reset_index(name="c")
    counts = counts.sort_values(["key", "c", "raw"], ascending=[True, False, True], kind="mergesort")
    best = counts.drop_duplicates("key").set_index("key")["raw"]
    return df["key"].map(best)


def auth_clean(s):
    s = clean(s)
    return re.sub(r"^מ\.?\s*א\.?\s+", "", s)


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ו" + items[-1]


def haversine(la1, lo1, la2, lo2):
    la1, lo1, la2, lo2 = map(np.radians, (la1, lo1, la2, lo2))
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def zone_of(lat):
    if lat >= NORTH_LAT:
        return "צפון"
    if lat < SOUTH_LAT:
        return "דרום"
    return "מרכז"


def _prepare(df):
    out = pd.DataFrame({
        "num": df["מס_מינהל_הדלק"].map(clean),
        "co_raw": df["חברה"].map(clean),
        "name": df["שם_תחנה"].map(clean),
        "auth_raw": df["רשות_מקומית"].map(auth_clean),
        "lat": pd.to_numeric(df["נ.צ. רוחב"].map(clean), errors="coerce"),
        "lon": pd.to_numeric(df["נ.צ. אורך"].map(clean), errors="coerce"),
    })
    out = out[(out["name"] != "") | (out["auth_raw"] != "")].copy()
    out["co_raw"] = out["co_raw"].where(out["co_raw"] != "", "לא צוין")
    out["auth_raw"] = out["auth_raw"].where(out["auth_raw"] != "", "לא צוין")
    out["company"] = display_map(out["co_raw"]).map(lambda s: INDEPENDENT if "עצמאי" in s else s)
    out["auth"] = display_map(out["auth_raw"])
    out["num_n"] = pd.to_numeric(out["num"], errors="coerce")
    out = out.sort_values(["num_n", "num", "name", "auth", "company", "lat", "lon"],
                          kind="mergesort", na_position="last").reset_index(drop=True)
    out["ok"] = out["lat"].between(LAT_MIN, LAT_MAX) & out["lon"].between(LON_MIN, LON_MAX)
    return out


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    geo = df[df["ok"]].reset_index(drop=True)
    n_geo = len(geo)
    n_bad = total - n_geo

    # ---- nearest neighbour (km) ----------------------------------------
    la, lo = geo["lat"].to_numpy(float), geo["lon"].to_numpy(float)
    D = haversine(la[:, None], lo[:, None], la[None, :], lo[None, :])
    np.fill_diagonal(D, np.inf)
    nn_idx = D.argmin(axis=1) if n_geo > 1 else np.zeros(n_geo, dtype=int)
    nn = D[np.arange(n_geo), nn_idx] if n_geo > 1 else np.full(n_geo, np.nan)
    geo["nn"] = nn
    geo["nn_co"] = geo["company"].to_numpy()[nn_idx] if n_geo > 1 else ""
    geo["zone"] = geo["lat"].map(zone_of)

    # ---- suspect locations (far from the rest of their authority) -------
    geo["suspect"] = False
    geo["auth_km"] = np.nan
    for a, g in geo.groupby("auth", sort=True):
        if len(g) < SUSPECT_MIN_STATIONS:
            continue
        d = haversine(g["lat"].to_numpy(float), g["lon"].to_numpy(float),
                      float(g["lat"].median()), float(g["lon"].median()))
        spread = max(float(np.median(d)), 1.0)
        flag = (d > SUSPECT_KM) & (d > SUSPECT_RATIO * spread)
        geo.loc[g.index, "auth_km"] = d
        geo.loc[g.index, "suspect"] = flag
    sus = geo[geo["suspect"]].sort_values(["auth_km", "num_n", "name"], ascending=[False, True, True],
                                          kind="mergesort")
    n_sus = len(sus)
    tbl_sus = [[r.name, r.company, r.auth, km(r.auth_km)] for r in sus.head(TOP_SUSPECT).itertuples()]

    # ---- chart: stations by latitude band (north to south) --------------
    lat_lo, lat_hi = float(geo["lat"].min()), float(geo["lat"].max())
    step = BAND_STEPS[-1]
    for s in BAND_STEPS:
        if (np.floor(lat_hi / s) - np.floor(lat_lo / s) + 1) <= MAX_BANDS:
            step = s
            break
    b_idx = np.floor(geo["lat"] / step).astype(int)
    geo["band"] = b_idx
    bands = list(range(int(b_idx.max()), int(b_idx.min()) - 1, -1))
    band_rows = []
    for b in bands:
        g = geo[geo["band"] == b]
        lo_b, hi_b = b * step, (b + 1) * step
        lead = ""
        if len(g):
            vc = g["auth"].value_counts()
            vc = sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))
            lead = vc[0][0]
        band_rows.append({"label": f"{lo_b:.2f}-{hi_b:.2f}", "lead": lead, "count": int(len(g)),
                          "zone": zone_of(lo_b)})
    chart_lat = {"names": [f"{r['label']}°" + (f" ({r['lead']})" if r["lead"] else "") for r in band_rows],
                 "values": [r["count"] for r in band_rows],
                 "zones": [r["zone"] for r in band_rows]}
    tbl_lat = [[f"{r['label']}°", r["lead"] or "-", n(r["count"])] for r in band_rows]
    peak = max(band_rows, key=lambda r: (r["count"], r["label"]))

    # ---- zones ----------------------------------------------------------
    zc = geo["zone"].value_counts()
    zone_counts = {z: int(zc.get(z, 0)) for z in ZONES}
    co_rank = sorted(geo["company"].value_counts().items(), key=lambda kv: (-kv[1], kv[0]))
    zone_cos = [k for k, _ in co_rank[:TOP_ZONE_CO]]
    grp = geo["company"].where(geo["company"].isin(zone_cos), OTHER)
    rows_order = zone_cos + ([OTHER] if (grp == OTHER).any() else [])
    ct = pd.crosstab(grp, geo["zone"]).reindex(index=rows_order, columns=ZONES, fill_value=0)
    zone_series = []
    for z in ZONES:
        cnt = [int(ct.loc[c, z]) for c in rows_order]
        shr = [round(x / max(int(ct.loc[c].sum()), 1) * 100, 1) for c, x in zip(rows_order, cnt)]
        zone_series.append({"name": z, "share": shr, "count": cnt})
    all_share = [round(zone_counts[z] / max(n_geo, 1) * 100, 1) for z in ZONES]
    chart_zone = {"names": ["כל התחנות"] + rows_order,
                  "series": [{"name": s["name"], "share": [all_share[i]] + s["share"],
                              "count": [zone_counts[s["name"]]] + s["count"]}
                             for i, s in enumerate(zone_series)]}
    tbl_zone = [["כל התחנות"] + [pct(zone_counts[z] / max(n_geo, 1), 0) for z in ZONES] + [n(n_geo)]]
    tbl_zone += [[c] + [pct(ct.loc[c, z] / max(int(ct.loc[c].sum()), 1), 0) for z in ZONES]
                 + [n(ct.loc[c].sum())] for c in rows_order]

    # ---- chart: nearest-neighbour distance distribution ------------------
    nn_names, nn_vals = [], []
    for lo_k, hi_k in NN_BUCKETS:
        if hi_k is None:
            sel = geo["nn"] >= lo_k
            nn_names.append(f"{lo_k:g}+ ק״מ")
        else:
            sel = (geo["nn"] >= lo_k) & (geo["nn"] < hi_k)
            nn_names.append(f"{lo_k:g}-{hi_k:g} ק״מ")
        nn_vals.append(int(sel.sum()))
    chart_nn = {"names": nn_names, "values": nn_vals}
    tbl_nn = [[k, n(v), pct(v / max(n_geo, 1))] for k, v in zip(nn_names, nn_vals)]
    med_nn = float(np.median(geo["nn"])) if n_geo > 1 else 0.0
    zone_med = {z: float(geo.loc[geo["zone"] == z, "nn"].median()) for z in ZONES
                if (geo["zone"] == z).sum() >= 10}

    # ---- chart: most isolated stations ----------------------------------
    iso = geo[~geo["suspect"]].sort_values(["nn", "num_n", "name"], ascending=[False, True, True],
                                           kind="mergesort").head(TOP_ISO)
    chart_iso = {"names": [f"{r.name} ({r.company})" for r in iso.itertuples()],
                 "values": [round(float(r.nn), 1) for r in iso.itertuples()]}
    tbl_iso = [[r.name, r.company, r.auth, km(r.nn)] for r in iso.itertuples()]

    # ---- pairs ----------------------------------------------------------
    close = geo[geo["nn"] < PAIR_KM]
    n_close = len(close)
    close_rival = int((close["company"] != close["nn_co"]).sum())

    # ---- KPIs -----------------------------------------------------------
    max_iso = float(iso["nn"].iloc[0]) if len(iso) else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "mapped": {"value": n_geo, "display": n(n_geo), "tone": "ok" if n_bad == 0 else "info"},
        "median": {"value": round(med_nn, 2), "display": f"{med_nn:.2f}", "tone": "info"},
        "south": {"value": round(zone_counts["דרום"] / max(n_geo, 1) * 100, 1),
                  "display": pct(zone_counts["דרום"] / max(n_geo, 1), 0), "tone": "brand"},
    }

    # ---- insights -------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_zones():
        if n_geo < 20:
            return None
        parts = [f"{z} {n(zone_counts[z])} ({pct(zone_counts[z] / n_geo)})" for z in ZONES]
        return ("חלוקת התחנות לפי אזור (לפי קו רוחב): " + ", ".join(parts)
                + f". רצועת קו הרוחב הצפופה ביותר היא {peak['label']}°, סביב {peak['lead']}, "
                  f"עם {n(peak['count'])} תחנות.")
    add("zones", ins_zones())

    def ins_nn():
        if n_geo < 20:
            return None
        within1 = int((geo["nn"] < 1).sum())
        s = (f"לתחנה טיפוסית יש תחנה אחרת במרחק {med_nn:.2f} ק״מ (חציון), "
             f"ול-{n(within1)} תחנות ({pct(within1 / n_geo)}) יש שכנה בטווח של פחות מקילומטר")
        if "דרום" in zone_med and "מרכז" in zone_med and zone_med["דרום"] > 1.5 * zone_med["מרכז"]:
            s += (f". בדרום המרחק החציוני גדול יותר: {zone_med['דרום']:.2f} ק״מ, "
                  f"לעומת {zone_med['מרכז']:.2f} ק״מ במרכז")
        return s + "."
    add("nn", ins_nn())

    def ins_iso():
        if len(iso) < 3:
            return None
        r = iso.iloc[0]
        r2 = iso.iloc[1]
        return (f"התחנה המבודדת ביותר היא {r['name']} ({r['company']}, {r['auth']}): "
                f"{km(r['nn'])} ק״מ עד התחנה הקרובה. אחריה {r2['name']} עם {km(r2['nn'])} ק״מ.")
    add("iso", ins_iso())

    def ins_pairs():
        if n_close < 20:
            return None
        return (f"{n(n_close)} תחנות ({pct(n_close / n_geo)}) עומדות פחות מ-{int(PAIR_KM * 1000)} מטר "
                f"מתחנה אחרת, בדרך כלל באותו צומת או משני צדי הכביש; ב-{pct(close_rival / n_close, 0)} "
                f"מהמקרים השכנה הקרובה שייכת לחברה אחרת.")
    add("pairs", ins_pairs())

    def ins_co_zone():
        best = None
        for c in zone_cos:
            tot_c = int(ct.loc[c].sum())
            if tot_c < 20:
                continue
            for z in ZONES:
                d = ct.loc[c, z] / tot_c - zone_counts[z] / n_geo
                cand = (abs(d), d, c, z, ct.loc[c, z] / tot_c)
                if best is None or (cand[0], cand[2], cand[3]) > (best[0], best[2], best[3]):
                    best = cand
        if not best or best[0] < ZONE_GAP:
            return None
        _, d, c, z, sh = best
        if c == INDEPENDENT:
            word = "בולטות" if d > 0 else "מעטות"
            head = f"התחנות העצמאיות {word} ב{z}: {pct(sh, 0)} מהן נמצאות שם"
        else:
            word = "בולטת" if d > 0 else "חלשה"
            head = f"{c} {word} ב{z}: {pct(sh, 0)} מהתחנות שלה נמצאות שם"
        return f"{head}, לעומת {pct(zone_counts[z] / n_geo, 0)} מכלל התחנות."
    add("cozone", ins_co_zone())

    def ins_sus():
        if n_sus == 0 and n_bad == 0:
            return None
        parts = []
        if n_sus:
            r = sus.iloc[0]
            lead_s = "תחנה אחת ממוקמת" if n_sus == 1 else f"{n(n_sus)} תחנות ממוקמות"
            parts.append(f"{lead_s} על המפה במרחק של יותר מ-{n(SUSPECT_KM)} ק״מ משאר התחנות "
                         f"של הרשות הרשומה (למשל {r['name']}, {km(r['auth_km'])} ק״מ ממרכז {r['auth']}); "
                         f"ייתכן שהקואורדינטות או שם הרשות שגויים")
        if n_bad:
            parts.append("לתחנה אחת אין קואורדינטות תקינות והיא אינה מופיעה על המפה" if n_bad == 1 else
                         f"ל-{n(n_bad)} תחנות אין קואורדינטות תקינות והן אינן מופיעות על המפה")
        return ". ".join(parts) + "."
    add("quality", ins_sus())

    # ---- labels ---------------------------------------------------------
    labels = {
        "lede": (f"כמה תחנות דלק יש בישראל, ואיפה הן נמצאות? ברשימת תחנות הדלק הציבוריות של משרד "
                 f"האנרגיה רשומות {n(total)} תחנות, ול-{n(n_geo)} מהן יש קואורדינטות, כך שאפשר למצוא על המפה "
                 f"את התחנה הקרובה, לראות לאיזו חברה היא שייכת ומה הכתובת שלה."),
        "twin": ("פילוח מפורט לפי חברת דלק, עיר וסוג מיקום מופיע במאגר המקביל, מאגר תחנות הדלק."),
        "kpi_total": "תחנות דלק ציבוריות ברשימה",
        "kpi_mapped": "תחנות עם מיקום על המפה",
        "kpi_median": "ק״מ, מרחק חציוני לתחנה הקרובה",
        "kpi_south": f"מהתחנות בדרום (מתחת לקו רוחב {SOUTH_LAT:g}°)",
        "map_note": ("כל תחנה מסומנת לפי הקואורדינטות שבנתונים. התקרבו כדי לפרק את הקבוצות, "
                     "ולחצו על תחנה לפרטים: חברה, כתובת ורשות מקומית."
                     + (f" {n(n_bad)} תחנות ללא קואורדינטות תקינות אינן מוצגות." if n_bad else "")),
        "map_aria": (f"מפה אינטראקטיבית של {n(n_geo)} תחנות הדלק הציבוריות בישראל. "
                     "גרסה נגישה: ראו את טבלת הנתונים בהמשך העמוד."),
        "lat_note": (f"מספר התחנות בכל רצועת קו רוחב של {step:g}°, מהצפון (למעלה) לדרום. "
                     f"בסוגריים: הרשות עם הכי הרבה תחנות ברצועה. הצפופה ביותר: {peak['label']}° "
                     f"({n(peak['count'])} תחנות)."),
        "lat_aria": (f"גרף עמודות אופקי: תחנות דלק לפי רצועת קו רוחב מצפון לדרום. "
                     f"השיא: {peak['label']}° סביב {peak['lead']} עם {n(peak['count'])} תחנות."),
        "lat_cap": "תחנות דלק לפי רצועת קו רוחב",
        "zone_note": (f"האזורים מוגדרים לפי קו רוחב בלבד: צפון מעל {NORTH_LAT:g}°, דרום מתחת ל-{SOUTH_LAT:g}°, "
                      f"והשאר מרכז. השורה העליונה מציגה את כלל התחנות להשוואה."),
        "zone_aria": (f"גרף עמודות מוערמות: חלוקת התחנות של כל חברה בין צפון, מרכז ודרום. "
                      f"בכלל התחנות: {all_share[0]}% בצפון, {all_share[1]}% במרכז, {all_share[2]}% בדרום."),
        "zone_cap": "חלוקת התחנות לפי חברה ואזור (אחוזים)",
        "nn_note": (f"לכל תחנה חושב המרחק בקו אווירי לתחנה הקרובה אליה. החציון: {med_nn:.2f} ק״מ."),
        "nn_aria": (f"גרף עמודות: התפלגות המרחק מכל תחנה לתחנה הקרובה. החציון {med_nn:.2f} ק״מ."),
        "nn_cap": "תחנות לפי מרחק לתחנה הקרובה",
        "iso_note": (f"{n(len(iso))} התחנות שהמרחק מהן לתחנה הקרובה הוא הגדול ביותר, בקו אווירי."
                     + (f" לא כולל {n(n_sus)} תחנות שמיקומן אינו תואם את הרשות הרשומה." if n_sus else "")),
        "iso_aria": (f"גרף עמודות אופקי: התחנות המבודדות ביותר. הראשונה: {chart_iso['names'][0]}, "
                     f"{chart_iso['values'][0]} ק״מ מהתחנה הקרובה." if chart_iso["names"]
                     else "גרף עמודות: התחנות המבודדות ביותר."),
        "iso_cap": "התחנות המבודדות ביותר: מרחק לתחנה הקרובה בק״מ",
        "sus_note": (f"תחנות שמיקומן על המפה רחוק מיותר מ-{n(SUSPECT_KM)} ק״מ ממרכז שאר התחנות של הרשות "
                     f"הרשומה, ופי {n(SUSPECT_RATIO)} לפחות מהפיזור הרגיל של תחנות הרשות "
                     f"(ברשויות עם {n(SUSPECT_MIN_STATIONS)} תחנות לפחות). לפני שנוסעים, כדאי לוודא את הכתובת."),
        "sus_cap": "תחנות שמיקומן רחוק מהרשות הרשומה",
    }

    summary = (f"מפת תחנות הדלק בישראל: איתור תחנה קרובה לפי שם, חברה, כתובת או רשות. "
               f"{n(n_geo)} תחנות ציבוריות עם מיקום על המפה.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["תחנות דלק", "מפה", "דלק", "חברות דלק", "מידע גאוגרפי", "אנרגיה"],
            "related_ids": ["09f0e9ee-5cef-48f7-84f6-10235e6dd9ed",
                            "4dd3bb28-a4ef-4ab5-bb57-fd0bd0b79f8f",
                            "61dc38b6-803e-476e-a1ac-0679c354b2ef",
                            "b2f22645-5068-487b-82d3-78e3490ef49d"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": ["total", "mapped", "median", "south"],
        "charts": {"lat": chart_lat, "zone": chart_zone, "nn": chart_nn, "iso": chart_iso},
        "tables": {
            "lat": {"head": ["קו רוחב", "רשות מובילה", "תחנות"], "rows": tbl_lat},
            "zone": {"head": ["חברה"] + ZONES + ["תחנות"], "rows": tbl_zone},
            "nn": {"head": ["מרחק לתחנה הקרובה", "תחנות", "שיעור"], "rows": tbl_nn},
            "iso": {"head": ["תחנה", "חברה", "רשות", "ק״מ לתחנה הקרובה"], "rows": tbl_iso},
            "sus": {"head": ["תחנה", "חברה", "רשות רשומה", "ק״מ ממרכז הרשות"], "rows": tbl_sus},
        },
        "flags": {"iso": len(iso) >= 3, "sus": n_sus > 0},
        "links": {"twin": "/datasets/09f0e9ee-5cef-48f7-84f6-10235e6dd9ed/"},
        "insights": insights,
        "labels": labels,
    }
