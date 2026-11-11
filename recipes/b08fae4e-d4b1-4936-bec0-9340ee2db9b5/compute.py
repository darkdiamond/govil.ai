"""בתי דיור לגיל הזהב: one row per sheltered-housing building for elderly
people eligible through the Ministry of Construction and Housing and the
Ministry of Aliyah and Integration. Columns: managing company, locality
(CBS code + name), building name, street address, postal code, number of
housing units, ITM X/Y and WGS84 longitude/latitude.

The page asks: who manages the homes (homes vs. units per company, and how
big each company's homes are), where they are (localities by units, the
company mix in the leading localities, how concentrated the stock is, a live
map), how big a home is (size bands, the largest homes) and how complete the
records are (postal codes).

Order-independent: integer sums, medians, sorts with full tie-breaks.
"""
import math
import re
import statistics

from govlib import fmt

LAT_RANGE = (29.0, 33.5)
LON_RANGE = (34.0, 36.0)
TOP_CITIES = 12
TOP_COMPANIES = 6
TOP_HOMES = 10
MIX_CITIES = 8
MIX_COMPANIES = 4
BOX_MIN = 3  # a company needs this many homes for a size box
LEAD_SHARE = 0.30  # a "leader" holds at least this share of units
TOP5_HEAVY = 0.40  # top-5 localities above this share = concentrated
SIZE_BANDS = [(0, 50), (50, 75), (75, 100), (100, 150), (150, 200), (200, 300), (300, None)]
OTHER = "אחר"


def _clean(s):
    s = str(s).replace("״", '"').replace("׳", "'")
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\s*-\s*", "-", s)


def _num(s):
    try:
        v = float(str(s).replace(",", "").strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _med(v):
    """A median for display: whole numbers bare, otherwise one decimal."""
    return fmt.int_he(v) if v == int(v) else fmt.num_he(v, 1)


def _band_label(lo, hi):
    if hi is None:
        return f"{lo}+"
    if lo == 0:
        return f"עד {hi - 1}"
    return f"{lo}-{hi - 1}"


def _rank(d, key_vals):
    """dict name -> tuple; sort by the given value tuple desc, then name."""
    return sorted(d, key=lambda k: tuple(-v for v in key_vals(k)) + (k,))


def compute(frames):
    df = frames["main"]
    n_rows = len(df)
    companies = [_clean(v) or "לא צוין" for v in df["CompanyName"].tolist()]
    cities = [_clean(v) or "לא צוין" for v in df["CityName"].tolist()]
    codes = [str(v).strip() for v in df["CityCode"].tolist()]
    homes = [_clean(v) for v in df["HomeName"].tolist()]
    addrs = [_clean(v) for v in df["Address"].tolist()]
    zips = [str(v).strip() for v in df["Zip"].tolist()]
    units_raw = [_num(v) for v in df["HousingUnits"].tolist()]
    units = [math.floor(u + 0.5) if u is not None and u > 0 else None for u in units_raw]
    lats = [_num(v) for v in df["Latitude"].tolist()]
    lons = [_num(v) for v in df["Longitude"].tolist()]

    valid_units = [u for u in units if u is not None]
    n_units_ok = len(valid_units)
    n_units_bad = n_rows - n_units_ok
    total_units = sum(valid_units)
    median_units = statistics.median(valid_units) if valid_units else 0

    geo = [la is not None and lo is not None and LAT_RANGE[0] <= la <= LAT_RANGE[1]
           and LON_RANGE[0] <= lo <= LON_RANGE[1] for la, lo in zip(lats, lons)]
    n_geo = sum(geo)
    zip_ok = [bool(re.fullmatch(r"\d{5,7}", z)) and int(z) > 0 for z in zips]
    n_zip_missing = n_rows - sum(zip_ok)
    n_addr_missing = sum(1 for a in addrs if not a)
    n_name_missing = sum(1 for h in homes if not h)

    # ---------- by company
    comp = {}
    for c, u in zip(companies, units):
        e = comp.setdefault(c, {"homes": 0, "units": 0, "sizes": []})
        e["homes"] += 1
        if u is not None:
            e["units"] += u
            e["sizes"].append(u)
    comp_order = _rank(comp, lambda k: (comp[k]["units"], comp[k]["homes"]))
    n_companies = len(comp)
    comp_rows = []
    for c in comp_order:
        e = comp[c]
        med = statistics.median(e["sizes"]) if e["sizes"] else 0
        comp_rows.append({
            "name": c, "homes": e["homes"], "units": e["units"], "median": med,
            "unit_share": e["units"] / total_units if total_units else 0.0,
            "home_share": e["homes"] / n_rows if n_rows else 0.0,
        })
    # chart: top companies + other
    head = comp_rows[:TOP_COMPANIES]
    rest = comp_rows[TOP_COMPANIES:]
    ch_comp = {
        "names": [r["name"] for r in head],
        "homes": [r["homes"] for r in head],
        "units": [r["units"] for r in head],
    }
    if len(rest) == 1:
        ch_comp["names"].append(rest[0]["name"])
        ch_comp["homes"].append(rest[0]["homes"])
        ch_comp["units"].append(rest[0]["units"])
    elif rest:
        ch_comp["names"].append(OTHER)
        ch_comp["homes"].append(sum(r["homes"] for r in rest))
        ch_comp["units"].append(sum(r["units"] for r in rest))
    tbl_comp = [[r["name"], fmt.int_he(r["homes"]), fmt.int_he(r["units"]),
                 fmt.pct(r["unit_share"]), _med(r["median"])] for r in comp_rows]

    # boxplot of home sizes per company (companies with >= BOX_MIN homes)
    box_names, box_data, box_tbl = [], [], []
    for r in comp_rows:
        s = sorted(comp[r["name"]]["sizes"])
        if len(s) < BOX_MIN:
            continue
        q = statistics.quantiles(s, n=4, method="inclusive")
        five = [s[0], q[0], q[1], q[2], s[-1]]
        five = [round(v, 1) for v in five]
        box_names.append(r["name"])
        box_data.append(five)
        box_tbl.append([r["name"], fmt.int_he(len(s)), fmt.int_he(s[0]), _med(q[1]), fmt.int_he(s[-1])])
    box_skipped = [r["name"] for r in comp_rows if len(comp[r["name"]]["sizes"]) < BOX_MIN]

    # ---------- by locality (grouped by CBS code when present, else name)
    city_key = [cd if cd and cd != "0" else nm for cd, nm in zip(codes, cities)]
    names_by_key = {}
    for k, nm in zip(city_key, cities):
        names_by_key.setdefault(k, {})
        names_by_key[k][nm] = names_by_key[k].get(nm, 0) + 1
    key_name = {k: min(v.items(), key=lambda kv: (-kv[1], kv[0]))[0] for k, v in names_by_key.items()}
    city = {}
    for k, c, u in zip(city_key, companies, units):
        nm = key_name[k]
        e = city.setdefault(nm, {"homes": 0, "units": 0, "comp": {}})
        e["homes"] += 1
        if u is not None:
            e["units"] += u
            e["comp"][c] = e["comp"].get(c, 0) + u
    city_order = _rank(city, lambda k: (city[k]["units"], city[k]["homes"]))
    n_cities = len(city)
    single_home_cities = sum(1 for k in city if city[k]["homes"] == 1)

    top_c = city_order[:TOP_CITIES]
    rest_c = city_order[TOP_CITIES:]
    ch_city = {"names": list(top_c), "units": [city[k]["units"] for k in top_c],
               "homes": [city[k]["homes"] for k in top_c]}
    if len(rest_c) == 1:
        ch_city["names"].append(rest_c[0])
        ch_city["units"].append(city[rest_c[0]]["units"])
        ch_city["homes"].append(city[rest_c[0]]["homes"])
    elif rest_c:
        ch_city["names"].append(f"{OTHER} ({fmt.int_he(len(rest_c))} יישובים)")
        ch_city["units"].append(sum(city[k]["units"] for k in rest_c))
        ch_city["homes"].append(sum(city[k]["homes"] for k in rest_c))
    tbl_city = [[n, fmt.int_he(h), fmt.int_he(u)] for n, u, h in
                zip(ch_city["names"], ch_city["units"], ch_city["homes"])]

    # company mix in the leading localities (stacked units)
    mix_cities = city_order[:MIX_CITIES]
    mix_comps = [r["name"] for r in comp_rows[:MIX_COMPANIES]]
    has_other_comp = n_companies > MIX_COMPANIES
    mix_series = []
    for c in mix_comps:
        mix_series.append({"name": c, "data": [city[k]["comp"].get(c, 0) for k in mix_cities]})
    if has_other_comp:
        mix_series.append({"name": OTHER, "other": True, "data": [
            sum(v for cc, v in city[k]["comp"].items() if cc not in mix_comps) for k in mix_cities]})
    ch_mix = {"cities": list(mix_cities), "series": mix_series}
    tbl_mix = []
    for i, k in enumerate(mix_cities):
        tbl_mix.append([k] + [fmt.int_he(s["data"][i]) for s in mix_series])
    mix_cols = ["יישוב"] + [s["name"] for s in mix_series]
    single_company_top = [k for k in mix_cities if sum(1 for v in city[k]["comp"].values() if v > 0) == 1]

    # concentration: cumulative share of units over localities ranked by units
    cum, run = [], 0
    for k in city_order:
        run += city[k]["units"]
        cum.append(round(run / total_units * 100, 1) if total_units else 0.0)
    ch_pareto = {"x": list(range(1, n_cities + 1)), "names": list(city_order), "cum": cum}
    top5_share = (sum(city[k]["units"] for k in city_order[:5]) / total_units) if total_units else 0.0
    half_n, run = n_cities, 0
    for i, k in enumerate(city_order):
        run += city[k]["units"]
        if run * 2 >= total_units:
            half_n = i + 1
            break
    pareto_marks = []
    for n in (1, 5, 10, 20):
        if n <= n_cities:
            pareto_marks.append([fmt.int_he(n), fmt.pct_of(cum[n - 1])])
    if n_cities not in (1, 5, 10, 20):
        pareto_marks.append([fmt.int_he(n_cities), fmt.pct_of(cum[-1])])

    # ---------- size bands
    band_labels, band_counts, band_units = [], [], []
    for lo, hi in SIZE_BANDS:
        sel = [u for u in valid_units if u >= lo and (hi is None or u < hi)]
        band_labels.append(_band_label(lo, hi))
        band_counts.append(len(sel))
        band_units.append(sum(sel))
    tbl_bands = [[lab, fmt.int_he(c), fmt.pct(c / n_units_ok) if n_units_ok else "–", fmt.int_he(u)]
                 for lab, c, u in zip(band_labels, band_counts, band_units)]
    modal_band = max(range(len(band_labels)), key=lambda i: (band_counts[i], -i))

    # ---------- largest homes
    recs = [(u, h, ci, co) for u, h, ci, co in zip(units, homes, cities, companies) if u is not None]
    recs.sort(key=lambda r: (-r[0], r[2], r[1], r[3]))
    top_h = recs[:TOP_HOMES]
    ch_homes = {"names": [f"{h} ({ci})" for _, h, ci, _ in top_h], "units": [u for u, _, _, _ in top_h],
                "company": [co for _, _, _, co in top_h]}
    tbl_homes = [[f"{h}", ci, co, fmt.int_he(u)] for u, h, ci, co in top_h]

    # ---------- map extent (north/south ends)
    geo_recs = [(la, ci) for la, ci, g in zip(lats, cities, geo) if g]
    south = min(geo_recs, key=lambda r: (r[0], r[1])) if geo_recs else None
    north = max(geo_recs, key=lambda r: (r[0], r[1])) if geo_recs else None
    if geo_recs:
        lat_c = statistics.median([la for la, _ in geo_recs])
        lon_c = statistics.median([lo for lo, g in zip(lons, geo) if g])
        map_view = {"center": [round(lat_c, 4), round(lon_c, 4)], "zoom": 7}
    else:
        map_view = {"center": [31.5, 34.9], "zoom": 7}

    # ---------- insights
    insights = []
    top_comp = comp_rows[0] if comp_rows else None
    by_homes = sorted(comp_rows, key=lambda r: (-r["homes"], -r["units"], r["name"]))
    if top_comp and top_comp["unit_share"] >= LEAD_SHARE and n_companies >= 2:
        s = (f"{top_comp['name']} מנהלת את מלאי היחידות הגדול ביותר: {fmt.int_he(top_comp['units'])} "
             f"יחידות דיור ({fmt.pct(top_comp['unit_share'])}) ב-{fmt.int_he(top_comp['homes'])} בתים.")
        hl = by_homes[0]
        if hl["name"] != top_comp["name"] and hl["homes"] > top_comp["homes"]:
            if hl["median"] < top_comp["median"]:
                s += (f" {hl['name']} מנהלת יותר בתים ({fmt.int_he(hl['homes'])}), אבל קטנים יותר: "
                      f"חציון של {_med(hl['median'])} יחידות לבית לעומת {_med(top_comp['median'])}.")
            else:
                s += f" {hl['name']} מנהלת יותר בתים ({fmt.int_he(hl['homes'])})."
        insights.append({"id": "company", "text_he": s})

    if city_order and n_cities >= 3:
        c1 = city_order[0]
        share1 = city[c1]["units"] / total_units if total_units else 0
        s = (f"{c1} מובילה במספר יחידות הדיור: {fmt.int_he(city[c1]['units'])} יחידות "
             f"({fmt.pct(share1)}) ב-{fmt.int_he(city[c1]['homes'])} בתים.")
        hc = min(city, key=lambda k: (-city[k]["homes"], -city[k]["units"], k))
        if hc != c1 and city[hc]["homes"] > city[c1]["homes"]:
            s += (f" ב{hc} יש יותר בתים ({fmt.int_he(city[hc]['homes'])}), "
                  f"אך {fmt.int_he(city[hc]['units'])} יחידות בלבד.")
        insights.append({"id": "city", "text_he": s})

    if n_cities >= 10:
        word = "מרוכז יחסית" if top5_share >= TOP5_HEAVY else "מפוזר"
        s = (f"המלאי {word}: חמשת היישובים המובילים מחזיקים {fmt.pct(top5_share)} מיחידות הדיור, "
             f"ומחצית מהיחידות נמצאות ב-{fmt.int_he(half_n)} יישובים מתוך {fmt.int_he(n_cities)}.")
        if single_home_cities:
            s += f" ב-{fmt.int_he(single_home_cities)} יישובים יש בית דיור אחד בלבד."
        insights.append({"id": "spread", "text_he": s})

    if recs and median_units:
        u, h, ci, co = recs[0]
        ratio = u / median_units
        if ratio >= 2:
            insights.append({"id": "largest", "text_he": (
                f"הבית הגדול ביותר הוא {h} ב{ci} ({co}) עם {fmt.int_he(u)} יחידות, "
                f"פי {fmt.num_he(ratio)} מהחציון ({_med(median_units)} יחידות לבית).")})

    if n_units_ok >= 10:
        mb = modal_band
        share_mb = band_counts[mb] / n_units_ok
        small = band_counts[0]
        s = (f"טווח הגודל הנפוץ ביותר הוא {band_labels[mb]} יחידות לבית "
             f"({fmt.int_he(band_counts[mb])} בתים, {fmt.pct(share_mb)}).")
        big = sum(c for (lo, _), c in zip(SIZE_BANDS, band_counts) if lo >= 200)
        if big:
            s += f" {fmt.int_he(big)} בתים מונים 200 יחידות ומעלה"
            s += f", ו-{fmt.int_he(small)} פחות מ-50." if small else "."
        insights.append({"id": "size", "text_he": s})

    if south and north and south[1] != north[1]:
        insights.append({"id": "extent", "text_he": (
            f"הבתים פרוסים ב-{fmt.int_he(n_cities)} יישובים, מ{south[1]} בדרום ועד {north[1]} בצפון.")})

    if n_rows and n_zip_missing / n_rows >= 0.05:
        insights.append({"id": "zip", "text_he": (
            f"ל-{fmt.int_he(n_zip_missing)} בתים ({fmt.pct(n_zip_missing / n_rows)}) אין מיקוד ברשומה; "
            f"השם, הכתובת והקואורדינטות מלאים {'בכל הרשומות' if not (n_addr_missing or n_name_missing) and n_geo == n_rows else 'ברוב הרשומות'}.")})

    if n_units_bad:
        insights.append({"id": "units_missing", "text_he": (
            f"ל-{fmt.int_he(n_units_bad)} רשומות אין מספר יחידות תקין, והן אינן נכללות בסכומי היחידות.")})

    # ---------- kpis
    kpis = {
        "homes": {"value": n_rows, "display": fmt.int_he(n_rows), "tone": "brand"},
        "units": {"value": total_units, "display": fmt.int_he(total_units), "tone": "brand"},
        "cities": {"value": n_cities, "display": fmt.int_he(n_cities), "tone": "brand"},
        "median": {"value": median_units, "display": _med(median_units), "tone": "info"},
        "companies": {"value": n_companies, "display": fmt.int_he(n_companies), "tone": "brand"},
    }

    # ---------- labels
    listed = [r["name"] for r in comp_rows[:TOP_COMPANIES]]
    if n_companies > len(listed):
        comp_names_he = f"{', '.join(listed)} ועוד {fmt.int_he(n_companies - len(listed))}"
    else:
        comp_names_he = fmt.join_he(listed)
    lede = (f"המאגר מפרט {fmt.int_he(n_rows)} בתי דיור לגיל הזהב, ובהם {fmt.int_he(total_units)} יחידות דיור "
            f"ב-{fmt.int_he(n_cities)} יישובים. הבתים מיועדים לאכלוס זכאי משרד הבינוי והשיכון ומשרד העלייה והקליטה, "
            f"ומנוהלים בידי {fmt.int_he(n_companies)} חברות: {comp_names_he}.")
    labels = {
        "lede": lede,
        "comp_note": ("מספר הבתים ומספר יחידות הדיור שכל חברה מנהלת. "
                      + (f"{top_comp['name']} מחזיקה {fmt.pct(top_comp['unit_share'])} מהיחידות." if top_comp else "")),
        "comp_aria": ("גרף עמודות: בתים ויחידות דיור לפי חברה מנהלת. "
                      + (f"{top_comp['name']} מובילה עם {fmt.int_he(top_comp['units'])} יחידות." if top_comp else "")),
        "comp_caption": "בתים ויחידות דיור לפי חברה מנהלת",
        "box_note": ("פיזור מספר היחידות בבית אצל כל חברה (מינימום, רבעון, חציון, רבעון עליון, מקסימום). "
                     + (f"לא מוצגות חברות עם פחות מ-{fmt.int_he(BOX_MIN)} בתים: {fmt.join_he(box_skipped)}." if box_skipped else "")),
        "box_aria": (f"תרשים קופסה: גודל הבתים ביחידות דיור לפי חברה, {fmt.int_he(len(box_names))} חברות."),
        "box_caption": "גודל הבתים לפי חברה מנהלת",
        "city_note": ("היישובים לפי מספר יחידות הדיור, עם מספר הבתים בכל יישוב"
                      + (f"; {fmt.int_he(len(rest_c))} היישובים הנותרים מקובצים." if len(rest_c) > 1 else ".")),
        "city_aria": ("גרף עמודות אופקי: יחידות דיור לפי יישוב. "
                      + (f"{city_order[0]} מובילה עם {fmt.int_he(city[city_order[0]]['units'])} יחידות." if city_order else "")),
        "city_caption": "יחידות דיור ובתים לפי יישוב",
        "mix_note": (f"איזו חברה מנהלת את היחידות ב-{fmt.int_he(len(mix_cities))} היישובים המובילים."
                     + (f" ב{fmt.join_he(single_company_top)} כל היחידות בניהול חברה אחת." if single_company_top else "")),
        "mix_aria": (f"גרף עמודות מוערמות: יחידות דיור לפי חברה מנהלת ב-{fmt.int_he(len(mix_cities))} היישובים המובילים."),
        "mix_caption": "יחידות דיור לפי חברה ביישובים המובילים",
        "pareto_note": (f"השיעור המצטבר של יחידות הדיור כשהיישובים מסודרים מהגדול לקטן: "
                        f"מחצית מהיחידות נמצאות ב-{fmt.int_he(half_n)} יישובים."),
        "pareto_aria": (f"גרף קו: שיעור מצטבר של יחידות הדיור לפי מספר היישובים. "
                        f"חמשת הראשונים מחזיקים {fmt.pct(top5_share)}."),
        "pareto_caption": "שיעור מצטבר של יחידות הדיור לפי מספר יישובים",
        "bands_note": (f"כמה בתים יש בכל טווח גודל, וכמה יחידות הם מחזיקים יחד. החציון הוא "
                       f"{_med(median_units)} יחידות לבית."),
        "bands_aria": (f"היסטוגרמה: מספר הבתים לפי טווח גודל. הטווח הנפוץ {band_labels[modal_band]} יחידות "
                       f"עם {fmt.int_he(band_counts[modal_band])} בתים."),
        "bands_caption": "בתים לפי טווח גודל ביחידות דיור",
        "homes_note": f"{fmt.int_he(len(top_h))} הבתים עם מספר יחידות הדיור הגדול ביותר.",
        "homes_aria": ("גרף עמודות אופקי: הבתים הגדולים ביותר. "
                       + (f"{top_h[0][1]} ב{top_h[0][2]} עם {fmt.int_he(top_h[0][0])} יחידות." if top_h else "")),
        "homes_caption": "הבתים הגדולים ביותר לפי יחידות דיור",
        "map_note": (f"כל נקודה היא בית דיור; לחיצה מציגה את שם הבית, החברה המנהלת, הכתובת ומספר היחידות. "
                     f"{fmt.int_he(n_geo)} מתוך {fmt.int_he(n_rows)} הבתים ממוקמים במפה."),
        "map_aria": "מפה אינטראקטיבית של בתי הדיור לגיל הזהב. גרסה נגישה: ראו את טבלת הנתונים מתחת לעמוד.",
        "kpi_homes": "בתי דיור",
        "kpi_units": "יחידות דיור",
        "kpi_cities": "יישובים",
        "kpi_median": "יחידות לבית (חציון)",
        "kpi_companies": "חברות מנהלות",
    }

    desc = (f"איתור בית דיור לגיל הזהב לפי יישוב, שם או חברה מנהלת: {fmt.int_he(n_rows)} בתים "
            f"עם {fmt.int_he(total_units)} יחידות דיור ב-{fmt.int_he(n_cities)} יישובים, במפה ובטבלה.")
    summary = (f"{fmt.int_he(n_rows)} בתי דיור לגיל הזהב עם {fmt.int_he(total_units)} יחידות דיור "
               f"ב-{fmt.int_he(n_cities)} יישובים, בניהול {fmt.int_he(n_companies)} חברות"
               + (f"; {top_comp['name']} מחזיקה {fmt.pct(top_comp['unit_share'])} מהיחידות." if top_comp else "."))

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "בתי דיור לגיל הזהב: רשימה ומפה לפי יישוב",
                "description": desc,
                "name": "בתי דיור לגיל הזהב",
                "alternate_names": ["בתי דיור", "בתי דיור לקשישים", "הוסטלים לעולים קשישים",
                                    "דיור ציבורי לגיל הזהב", "בתי דיור עמידר ועמיגור"],
            },
        },
        "kpis": kpis,
        "charts": {
            "comp": ch_comp, "box": {"names": box_names, "data": box_data},
            "city": ch_city, "mix": ch_mix, "pareto": ch_pareto,
            "bands": {"labels": band_labels, "counts": band_counts, "units": band_units},
            "homes": ch_homes,
        },
        "tables": {
            "comp": tbl_comp, "box": box_tbl, "city": tbl_city, "mix": tbl_mix, "mix_cols": mix_cols,
            "pareto": pareto_marks, "bands": tbl_bands, "homes": tbl_homes,
        },
        "flags": {"box": len(box_names) >= 2, "mix": len(mix_cities) >= 3 and n_companies >= 2,
                  "pareto": n_cities >= 5, "map": n_geo > 0},
        "map_view": map_view,
        "insights": insights,
        "labels": labels,
    }
