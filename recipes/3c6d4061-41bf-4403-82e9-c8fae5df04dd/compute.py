"""שכבת שטח השיפוט המוניציפלי: the City of Be'er Sheva's municipal
jurisdiction layer, published as an attribute table (one row per polygon:
area code and name, committee name, perimeter SHAPE_Leng in metres, area
SHAPE_Area in square metres, and a WGS84 centre point). The polygon
geometry itself ships only in the GeoJSON/SHP/KML files.

The layer currently holds a single polygon, the whole city, so the page is
a fact card: area, perimeter, area code, centre point, plus how compact the
boundary is (perimeter against a circle of the same area). Everything is
computed from the rows, so the wording follows when the layer is split
into several units (committees, annexed areas): totals, the largest unit
and a per-unit table switch on from the data.
"""
import math
import re

import pandas as pd

TABLE_CAP = 20
SUMMARY_MAX = 155
# Israel's bounding box (WGS84): a centre point outside it is a bad row,
# and the map only switches on when at least one point is inside.
LAT_RANGE = (29.3, 33.5)
LON_RANGE = (34.2, 35.9)


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _num(s):
    return pd.to_numeric(s.map(lambda v: _clean(v).replace(",", "")), errors="coerce")


def _code(v):
    """'9000' / '9000.0' -> '9000'; anything else stays as published."""
    s = _clean(v)
    m = re.fullmatch(r"(\d+)(?:\.0+)?", s)
    return m.group(1) if m else s


def _km2(m2):
    return f"{m2 / 1e6:,.1f}"


def _km(m):
    return f"{m / 1000:,.1f}"


def _dunam(m2):
    return f"{m2 / 1000:,.0f}"


def _coord(v):
    return f"{v:.3f}°"


def _prepare(df):
    out = pd.DataFrame({
        "code": df["AREA_CODE"].map(_code),
        "name": df["AREA_NAME"].map(_clean),
        "vaad": df["VAAD_NAME"].map(_clean),
        "perim": _num(df["SHAPE_Leng"]),
        "area": _num(df["SHAPE_Area"]),
        "lat": _num(df["lat"]),
        "lon": _num(df["lon"]),
    })
    out = out[(out["area"] > 0) & (out["perim"] > 0)].copy()
    out["label"] = out["vaad"].where(out["vaad"] != "", out["name"])
    out["label"] = out["label"].where(out["label"] != "", "ללא שם")
    out["geo_ok"] = (out["lat"].between(*LAT_RANGE) & out["lon"].between(*LON_RANGE))
    # Every column is a sort key, so the order is total (verify shuffles rows).
    out = out.sort_values(["area", "perim", "code", "label", "lat", "lon"],
                          ascending=[False, False, True, True, True, True], kind="stable")
    return out.reset_index(drop=True)


def _compactness(area, perim):
    """Perimeter divided by the circumference of a circle of the same area
    (1.0 = a circle; larger = a more convoluted boundary)."""
    return perim / (2 * math.sqrt(math.pi * area))


# ---------------------------------------------------------------- insights

def insight_area(df, owner):
    n = len(df)
    if n == 0:
        return None
    total = float(df["area"].sum())
    if n == 1:
        return (f"השכבה מתארת יחידה אחת, תחום השיפוט של {owner}, בשטח של "
                f"{_km2(total)} קמ״ר (כ-{_dunam(total)} דונם).")
    top = df.iloc[0]
    return (f"השכבה מחולקת ל-{n:,} יחידות בשטח כולל של {_km2(total)} קמ״ר "
            f"(כ-{_dunam(total)} דונם); הגדולה שבהן, {top['label']}, משתרעת על "
            f"{_km2(top['area'])} קמ״ר ({top['area'] / total * 100:.0f}% מהשטח).")


def insight_shape(df):
    if df.empty:
        return None
    r = df.iloc[0]
    ratio = _compactness(float(r["area"]), float(r["perim"]))
    if ratio < 1.05:
        return None  # a near-circle says nothing worth a sentence
    circle = 2 * math.sqrt(math.pi * float(r["area"]))
    who = "קו הגבול" if len(df) == 1 else f"קו הגבול של {r['label']}"
    s = (f"{who} ארוך {_km(r['perim'])} ק״מ, פי {ratio:.2f} מהיקפו של עיגול "
         f"באותו שטח ({_km(circle)} ק״מ)")
    if ratio >= 1.3:
        s += ": גבול מפותל ולא קומפקטי"
    return s + "."


def insight_center(df):
    geo = df[df["geo_ok"]]
    if geo.empty:
        return None
    r = geo.iloc[0]
    who = "מרכז תחום השיפוט" if len(df) == 1 else f"מרכז היחידה הגדולה ({r['label']})"
    return (f"{who} נמצא בקו רוחב {_coord(r['lat'])} ובקו אורך {_coord(r['lon'])} "
            "(מערכת WGS84), והוא הנקודה המוצגת במפה.")


def insight_code(df):
    codes = sorted(set(c for c in df["code"] if c))
    if not codes:
        return None
    if len(codes) == 1:
        return (f"קוד האזור של השכבה הוא {codes[0]}; זהו המפתח לחיבור השכבה "
                "לטבלאות אחרות של העירייה.")
    return f"בשכבה {len(codes):,} קודי אזור שונים: {', '.join(codes[:6])}{'…' if len(codes) > 6 else ''}."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    n = int(len(df))
    names = sorted(set(x for x in df["name"] if x))
    owner = names[0] if len(names) == 1 else "העירייה"
    total_area = float(df["area"].sum()) if n else 0.0
    total_perim = float(df["perim"].sum()) if n else 0.0
    codes = sorted(set(c for c in df["code"] if c))

    rules = [
        ("area", insight_area(df, owner)),
        ("shape", insight_shape(df)),
        ("center", insight_center(df)),
        ("code", insight_code(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    kpis = {
        "area": {"value": round(total_area / 1e6, 1), "display": _km2(total_area), "tone": "brand"},
        "perim": {"value": round(total_perim / 1000, 1), "display": _km(total_perim), "tone": "brand"},
        "units": {"value": n, "display": f"{n:,}", "tone": "brand"},
    }
    if len(codes) == 1:
        kpis["code"] = {"value": codes[0], "display": codes[0], "tone": "brand"}
    else:
        kpis["code"] = {"value": len(codes), "display": f"{len(codes):,}", "tone": "brand"}

    rows = []
    for _, r in df.head(TABLE_CAP).iterrows():
        rows.append({
            "label": r["label"],
            "code": r["code"],
            "area_km2": _km2(r["area"]),
            "dunam": _dunam(r["area"]),
            "perim_km": _km(r["perim"]),
            "ratio": f"{_compactness(float(r['area']), float(r['perim'])):.2f}",
            "lat": f"{r['lat']:.5f}" if r["geo_ok"] else "",
            "lon": f"{r['lon']:.5f}" if r["geo_ok"] else "",
        })

    city = re.sub(r"^עיריית\s+", "", owner) if owner != "העירייה" else ""
    where = f"של {owner}" if city else "המוניציפלי"
    # Summed perimeters double-count shared borders, so only a single unit quotes one.
    size = (f"שטח {_km2(total_area)} קמ״ר, היקף {_km(total_perim)} ק״מ" if n == 1
            else f"{n:,} יחידות בשטח {_km2(total_area)} קמ״ר")
    summary = (f"גבול תחום השיפוט {where}: {size} ונקודת מרכז, "
               "כשכבת GIS להורדה ב-CSV, GeoJSON, SHP ו-KML.")
    if len(summary) > SUMMARY_MAX:
        summary = f"גבול תחום השיפוט {where}: {size}."

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "map",
        "suggested_tags": ["גבולות מוניציפליים", "תחום שיפוט", "באר שבע", "GIS"],
        "related_ids": ["82a30a97-01b0-4281-854c-c7931f3445c0",
                        "bdf28cc0-680a-415c-af64-944a58079b2f",
                        "5944b454-751c-4604-94d6-e676d7d34612",
                        "b795e2e0-491e-4040-877e-f3681917f8be"],
        "spatial_coverage": city or "באר שבע",
    }

    n_geo = int(df["geo_ok"].sum())
    labels = {
        "h1_place": city,
        "kpi_area": "שטח השיפוט (קמ״ר)",
        "kpi_perim": "אורך קו הגבול (ק״מ)" if n == 1 else "סך היקפי היחידות (ק״מ)",
        "kpi_code": "קוד אזור (AREA_CODE)" if len(codes) == 1 else "קודי אזור בשכבה",
        "kpi_units": "יחידה בשכבה" if n == 1 else "יחידות בשכבה",
        "map_lede": ("הנקודה מציינת את מרכז תחום השיפוט כפי שרשום במאגר. קו הגבול עצמו "
                     "מופיע בקובצי GeoJSON, SHP ו-KML שבאזור ההורדות."
                     if n_geo == 1 else
                     f"כל נקודה היא מרכז של יחידה בשכבה ({n_geo:,} נקודות). קווי הגבול עצמם "
                     "מופיעים בקובצי GeoJSON, SHP ו-KML שבאזור ההורדות."),
        "map_aria": ("מפה אינטראקטיבית של מרכז תחום השיפוט. גרסה נגישה: ראו את טבלת "
                     "פרטי השכבה בהמשך העמוד."),
        "table_title": "פרטי השכבה" if n == 1 else "היחידות בשכבה",
        "table_lede": ("הערכים כפי שהם רשומים בטבלת המאפיינים של השכבה, מומרים ליחידות נוחות."
                       if n <= TABLE_CAP else
                       f"{TABLE_CAP:,} היחידות הגדולות מתוך {n:,}, לפי שטח."),
        "table_caption": f"פרטי שכבת שטח השיפוט: {n:,} יחידות, שטח, היקף, קוד אזור ונקודת מרכז.",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {},
        "insights": insights,
        "tables": {"units": rows},
        "flags": {"has_map": n_geo > 0, "single": n == 1},
        "labels": labels,
    }
