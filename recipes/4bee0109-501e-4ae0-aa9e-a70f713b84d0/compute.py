"""Existing public-transport priority lanes (נת"צים): Ministry of Transport GIS layer.

One row per lane segment: type, local and traffic authority, road/street,
start/end points (ITM), operating hours per day type, permitted users,
physical separation, paint, enforcement, start date and last change.

Two inputs: `main` (the datastore attribute table) drives every chart of
attributes; `geo` (the uploaded shapefile, one row per segment with its
line as WGS84 GeoJSON in `__geometry`) drives the line map, the north-south
profile and the measured lengths. Both carry the same 1,008 rows; each
section reads one input only, so they stay self-consistent.

Every number on the page comes from here. Attribute lengths are the LENGT
column (metres); map lengths are measured on the geometry. Insight rules each return a sentence or None; a rule whose premise
no longer holds in the data drops out rather than asserting something false.
"""
import itertools
import json
import math
import re

import pandas as pd
from govlib import geo

UNKNOWN = "לא צוין"

# Short glossary for the known lane-type codes (ordering/explanation only;
# an unknown type still flows through, just without an explanation).
TYPE_INFO = {
    'נת"צ ימני': "נתיב בצד ימין של הכביש",
    'נת"צ שמאלי': "נתיב בצד שמאל או במרכז הכביש",
    'נת"צ נגדי': "נתיב בכיוון הפוך לתנועה הכללית",
    'מת"צ': "מסלול נפרד לתחבורה ציבורית",
    'רת"צ': "רחוב המיועד לתחבורה ציבורית בלבד",
    'שות"צ': "שול דרך המשמש את התחבורה הציבורית",
    "העדפה בצמתים": "קדימות לתחבורה הציבורית בצומת",
}

# Who else may use the lane (yes/no columns), in a fixed display order.
USERS = [
    ("OTHERBUSES", "אוטובוסים שאינם בקו סדיר"),
    ("TAXI", "מוניות"),
    ("BRT", "מסלול תחבורה ציבורית מהירה"),
    ("SERVLINES", "מוניות שירות"),
    ("PARKING", "חניה בנתיב"),
    ("MOTORCYCLE", "אופנועים"),
    ("LIGHTRAIL", "משותף עם הרכבת הקלה"),
    ("DISABLED", "רכב נכים"),
    ("EV", "רכב חשמלי"),
    ("AV", "רכב אוטונומי"),
    ("VAN", "רכב הסעות"),
]

DAYS = [
    ("WK", "ימי חול", [("FRHR_WK_F", "TOHR_WK_F"), ("FRHR_WK_2_F", "TOHR_WK_2_F")]),
    ("FRI", "שישי", [("FRHR_FRI_F", "TOHR_FRI_F"), ("FRHR_FRI_2_F", "TOHR_FRI_2_F")]),
    ("SAT", "שבת", [("FRHR_SAT_F", "TOHR_SAT_F")]),
]

LEN_BINS = [(0, 100, "עד 100 מ'"), (100, 250, "100-250 מ'"), (250, 500, "250-500 מ'"),
            (500, 1000, "0.5-1 ק\"מ"), (1000, 2000, "1-2 ק\"מ"), (2000, 5000, "2-5 ק\"מ"),
            (5000, float("inf"), "מעל 5 ק\"מ")]

TOP_AUTH = 12
TOP_TRAF = 10
TOP_ROADS = 10
YEARS_SHOWN = 15


def _int(n):
    return f"{round(n):,}"


def _km(m):
    return f"{m / 1000:,.1f}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _clean(s):
    # The export doubles every quote mark (נת""צ); fold back to one.
    return s.astype(str).str.replace('""', '"', regex=False).str.strip()


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")


def _prepare(df):
    df = df.copy()
    for c in ["PTLNAME", "PTLTYPE", "AUTHORITY", "TRAFAUTH", "STREETNAME", "ROADNAME",
              "URBANTYPE", "STATUS", "OPTYPE", "PAINT", "DIVISION", "ENFORCMENT",
              "STARTDATE", "LASTCHANGE", "PTLCODE"] + [c for c, _ in USERS]:
        df[c] = _clean(df[c])
    df["len"] = _num(df["LENGT"]).fillna(0).clip(lower=0)
    for c in ["PTLTYPE", "AUTHORITY", "TRAFAUTH", "URBANTYPE", "OPTYPE", "PAINT",
              "DIVISION", "ENFORCMENT"]:
        df[c] = df[c].where(df[c] != "", UNKNOWN)
    df["nl"] = _num(df["NUMLANES"])
    df["nother"] = _num(df["NUMLOTHER"])
    df["hov"] = _num(df["HOV"])
    df["hot"] = _num(df["HOT"])
    df["start_year"] = df["STARTDATE"].map(_year)
    lc = pd.to_datetime(df["LASTCHANGE"].str[:10], errors="coerce", format="%Y-%m-%d")
    df["change_year"] = lc.dt.year
    for _, _, wins in DAYS:
        for a, b in wins:
            df[a] = _num(df[a])
            df[b] = _num(df[b])
    return df


def _year(s):
    m = re.search(r"(?<!\d)((?:19|20)\d\d)(?!\d)", s or "")
    return int(m.group(1)) if m else None


def _windows(row, wins):
    out = []
    for a, b in wins:
        f, t = row[a], row[b]
        if pd.isna(f) or pd.isna(t) or f < 0 or f >= 24 or t < 0 or t > 24:
            continue
        if t == 0:
            t = 24.0
        if t == f:
            continue
        if t > f:
            out.append((f, t))
        else:  # wraps past midnight
            out.append((f, 24.0))
            out.append((0.0, t))
    return out


def _active_hours(df, wins):
    """Per row: set of whole hours (0-23) whose midpoint falls inside a window."""
    res = []
    for _, row in df[[c for w in wins for c in w]].iterrows():
        ws = _windows(row, wins)
        res.append(frozenset(h for h in range(24) if any(f <= h + 0.5 < t for f, t in ws)))
    return res


def _ranked(series):
    """Total, deterministic order: value desc, then label asc."""
    return series.sort_index().sort_values(ascending=False, kind="stable")


def _top_other(ranked, n, other_label):
    if len(ranked) <= n + 1:
        return list(ranked.index), [float(v) for v in ranked]
    names = list(ranked.index[:n]) + [other_label]
    vals = [float(v) for v in ranked.iloc[:n]] + [float(ranked.iloc[n:].sum())]
    return names, vals


# ---------------------------------------------------------------- insights

def insight_auth_lead(by_auth, total_m):
    if by_auth.empty or total_m <= 0:
        return None
    named = by_auth[by_auth.index != UNKNOWN]
    if named.empty:
        return None
    name, v = named.index[0], named.iloc[0]
    share = v / total_m
    if share < 0.15:
        return None
    top3 = named.iloc[:3]
    if len(top3) < 3:
        return f"{name} מובילה עם {_km(v)} ק\"מ של נתיבי העדפה, {_pct(share)} מכלל האורך."
    return (f"{name} מובילה עם {_km(v)} ק\"מ של נתיבי העדפה ({_pct(share)} מכלל האורך). "
            f"שלוש הרשויות המובילות ({', '.join(top3.index)}) מחזיקות יחד "
            f"{_pct(top3.sum() / total_m)} מהאורך.")


def insight_type_mix(by_type_m, by_type_n, total_m):
    if by_type_m.empty or total_m <= 0:
        return None
    name, v = by_type_m.index[0], by_type_m.iloc[0]
    share = v / total_m
    if share < 0.3:
        return None
    return (f"הסוג הנפוץ ביותר הוא {name}: {_int(by_type_n[name])} מקטעים "
            f"באורך {_km(v)} ק\"מ, {_pct(share)} מכלל האורך.")


def insight_national(nat_m, total_m, nat_names):
    if total_m <= 0 or not nat_names:
        return None
    share = nat_m / total_m
    if share < 0.1:
        return None
    return (f"{_pct(share)} מאורך הנתיבים ({_km(nat_m)} ק\"מ) מנוהל בידי גופים "
            f"שאינם רשות מקומית, בראשם {', '.join(nat_names[:3])}.")


def insight_hours(day_stats):
    wk, sat = day_stats.get("WK"), day_stats.get("SAT")
    if not wk or not sat or wk["total_m"] <= 0:
        return None
    s24 = wk["m24"] / wk["total_m"]
    sat_share = sat["active_m"] / sat["total_m"]
    if s24 < 0.05:
        return None
    return (f"{_pct(s24)} מאורך הנתיבים פועלים כנתיב העדפה כל שעות היממה בימי חול; "
            f"בשבת פעילים {_pct(sat_share)} מהאורך ({_km(sat['active_m'])} ק\"מ).")


def insight_enforcement(df):
    known = df[df["ENFORCMENT"] != UNKNOWN]
    n = len(df)
    if n == 0 or len(known) < max(20, 0.2 * n):
        return None
    cam = known["ENFORCMENT"].str.contains("מצלמה", regex=False)
    share = cam.mean()
    return (f"מבין {_int(len(known))} המקטעים שאופן האכיפה בהם מתועד, "
            f"{_pct(share)} נאכפים במצלמה ({_int(cam.sum())} מקטעים); "
            f"ב-{_int(n - len(known))} מקטעים נוספים האכיפה לא צוינה.")


def insight_paint(df):
    painted = df[df["PAINT"].str.startswith("קיימת")]
    if len(painted) < 20:
        return None
    bad = painted["PAINT"].str.contains("לא תקינה", regex=False)
    share = bad.mean()
    if share < 0.1:
        return None
    return (f"ב-{_pct(share)} מהמקטעים שיש בהם צביעה ({_int(bad.sum())} מתוך "
            f"{_int(len(painted))}) הצביעה מסומנת כלא תקינה.")


def insight_cancel(df):
    canc = df[df["STATUS"].str.contains("יבוטל", regex=False)]
    if canc.empty:
        return None
    by = _ranked(canc.groupby("AUTHORITY").size())
    lead = by.index[0]
    tail = f", מהם {_int(by.iloc[0])} ב{lead}" if by.iloc[0] / len(canc) >= 0.5 and lead != UNKNOWN else ""
    return (f"{_int(len(canc))} מקטעים באורך {_km(canc['len'].sum())} ק\"מ מסומנים "
            f"כקיימים אך צפויים להתבטל בעתיד{tail}.")


def insight_start(df):
    sy = df.dropna(subset=["start_year"])
    if len(sy) < 20:
        return None
    by = sy.groupby("start_year")["len"].sum().sort_index()
    by = by.sort_values(ascending=False, kind="stable")
    y, v = int(by.index[0]), by.iloc[0]
    return (f"לפי תאריך ההפעלה (ידוע ל-{_int(len(sy))} מתוך {_int(len(df))} מקטעים), "
            f"השנה עם הכי הרבה נתיבים חדשים היא {y}: {_km(v)} ק\"מ.")


# ---------------------------------------------------------------- geometry (geo input)

SIMPLIFY_M = (2.0, 4.0, 8.0, 16.0)   # display-only Douglas-Peucker tolerances (metres), finest first;
MAP_BUDGET = 200_000                 # the finest one whose islands fit this many characters
                                     # (as rendered by | tojson) is used.
                                     # Lengths are always measured on the full line.
CHUNK_POINTS = 1_500      # a longer line is split into pieces of this many points
BAND_WIDTHS = (10, 20, 25, 50, 100)   # latitude band widths, in 0.01 degrees
MAX_BANDS = 20
KM_PER_DEG_LAT = 111.2
ZOOM_TOP = 4


def _haversine_m(a, b):
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(min(1.0, h)))


def _lines_of(geom):
    if not isinstance(geom, dict):
        return []
    if geom.get("type") == "LineString":
        parts = [geom.get("coordinates") or []]
    elif geom.get("type") == "MultiLineString":
        parts = geom.get("coordinates") or []
    else:
        return []
    out = []
    for p in parts:
        pts = [(float(c[0]), float(c[1])) for c in p if isinstance(c, list) and len(c) >= 2]
        if len(pts) >= 2:
            out.append(pts)
    return out


def _hours_text(r):
    wins = []
    for a, b in (("FRHR_WK", "TOHR_WK"), ("FRHR_WK_2", "TOHR_WK_2")):
        f, t = str(r.get(a, "")).strip(), str(r.get(b, "")).strip()
        if not f or not t:
            continue
        if (f in ("00:00", "0:00") and t in ("24:00", "00:00", "23:59")) or f == t:
            return "כל היממה"
        wins.append(f"{f}-{t}")
    return ", ".join(wins) if wins else UNKNOWN


def _geo_prepare(df):
    rows = []
    for r in df.to_dict("records"):
        try:
            geom = json.loads(r.get("__geometry") or "null")
        except ValueError:
            geom = None
        parts = _lines_of(geom)
        rec = {
            "code": str(r.get("PTLCODE", "")).strip(),
            "seg": str(r.get("PTLSEG", "")).strip(),
            "name": str(r.get("PTLNAME", "")).replace('""', '"').strip(),
            "dir": str(r.get("PTLDIR", "")).strip(),
            "type": str(r.get("PTLTYPE", "")).replace('""', '"').strip() or UNKNOWN,
            "auth": str(r.get("AUTHORITY", "")).replace('""', '"').strip() or UNKNOWN,
            "hours": _hours_text(r),
            "declared": pd.to_numeric(str(r.get("LENGT", "")).replace(",", "").strip(), errors="coerce"),
            "parts": parts,
            "gkey": r.get("__geometry") or "",
        }
        rec["m"] = sum(_haversine_m(a, b) for p in parts for a, b in itertools.pairwise(p))
        rows.append(rec)
    code_num = lambda s: (0, float(s), s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else (1, 0.0, s)
    rows.sort(key=lambda x: (code_num(x["code"]), code_num(x["seg"]), x["name"], x["dir"],
                             x["type"], x["auth"], x["gkey"]))
    return rows


def _bounds(parts_list):
    xs = [x for parts in parts_list for p in parts for x, _ in p]
    ys = [y for parts in parts_list for p in parts for _, y in p]
    if not xs:
        return None
    return [[round(min(ys), 5), round(min(xs), 5)], [round(max(ys), 5), round(max(xs), 5)]]


def _lat_bands(drawn):
    """km per latitude band (by each line piece's midpoint), narrowest width
    in BAND_WIDTHS that leaves at most MAX_BANDS non-empty bands."""
    pieces = []
    for s in drawn:
        for p in s["parts"]:
            for a, b in itertools.pairwise(p):
                pieces.append(((a[1] + b[1]) / 2, _haversine_m(a, b), s["auth"]))
    for w in BAND_WIDTHS:
        acc = {}
        for lat, m, auth in pieces:
            k = math.floor(lat * 100 / w)
            d = acc.setdefault(k, {"m": 0.0, "auth": {}})
            d["m"] += m
            d["auth"][auth] = d["auth"].get(auth, 0.0) + m
        if len(acc) <= MAX_BANDS or w == BAND_WIDTHS[-1]:
            break
    bands = []
    for k in sorted(acc, reverse=True):   # north first
        d = acc[k]
        named = {a: v for a, v in d["auth"].items() if a != UNKNOWN} or d["auth"]
        lead = min(named.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        lo = k * w / 100
        bands.append({"lo": lo, "hi": lo + w / 100, "m": d["m"], "lead": lead})
    return bands, w / 100


def insight_extent(drawn):
    if len(drawn) < 2:
        return None
    north = max(drawn, key=lambda s: (max(y for p in s["parts"] for _, y in p), s["name"]))
    south = min(drawn, key=lambda s: (min(y for p in s["parts"] for _, y in p), s["name"]))
    n_lat = max(y for p in north["parts"] for _, y in p)
    s_lat = min(y for p in south["parts"] for _, y in p)
    span = (n_lat - s_lat) * KM_PER_DEG_LAT
    if north["auth"] == south["auth"] or span < 50 or UNKNOWN in (north["auth"], south["auth"]):
        return None
    return (f"על המפה, נתיבי ההעדפה נפרשים מ{north['auth']} בצפון ועד {south['auth']} בדרום, "
            f"מרחק צפון-דרום של כ-{_int(span)} ק\"מ.")


def _deg(v, width):
    return f"{v:.1f}" if round(width * 100) % 10 == 0 else f"{v:.2f}"


def insight_band(bands, width, total_m):
    if len(bands) < 3 or total_m <= 0:
        return None
    ranked = sorted(bands, key=lambda b: (-b["m"], -b["lo"]))
    top = ranked[0]
    share = top["m"] / total_m
    if share < 0.15:
        return None
    top3 = sum(b["m"] for b in ranked[:3]) / total_m
    return (f"{_pct(share)} מאורך הקווים שבמפה ({_km(top['m'])} ק\"מ) עוברים ברצועת רוחב אחת "
            f"של כ-{_int(width * KM_PER_DEG_LAT)} ק\"מ, בין קו רוחב {_deg(top['lo'], width)} ל-{_deg(top['hi'], width)} "
            f"(אזור {top['lead']}); שלוש הרצועות הצפופות ביותר מחזיקות {_pct(top3)} מהאורך.")


def _geo_section(df):
    rows = _geo_prepare(df)
    drawn = [s for s in rows if s["parts"] and s["m"] > 0]
    missing = len(rows) - len(drawn)
    total_m = sum(s["m"] for s in drawn)

    by_type = {}
    for s in drawn:
        d = by_type.setdefault(s["type"], [0.0, 0])
        d[0] += s["m"]
        d[1] += 1
    types = [t for t, _ in sorted(by_type.items(), key=lambda kv: (-kv[1][0], kv[0]))]
    by_auth = {}
    for s in drawn:
        by_auth.setdefault(s["auth"], []).append(s)
    auths = sorted(by_auth, key=lambda a: (-sum(s["m"] for s in by_auth[a]), a))

    hours = sorted({s["hours"] for s in drawn})
    # Display geometry: govlib.geo integers (1e-5 degree), each line restarting
    # from one origin at the south-west corner of everything drawn.
    org = geo.origin([x for s in drawn for p in s["parts"] for x, _ in p],
                     [y for s in drawn for p in s["parts"] for _, y in p]) if drawn else [0, 0]
    for tol in SIMPLIFY_M:
        tol_u = tol / 1.1           # metres -> 1e-5 degree units (~1.1 m north-south)
        feats = []
        for s in drawn:
            meta = [types.index(s["type"]), auths.index(s["auth"]), _km(s["m"]), s["name"],
                    hours.index(s["hours"])]
            for p in s["parts"]:
                simp = geo.simplify(geo.quantize(p), tol_u, ring=False)
                for a in range(0, len(simp) - 1, CHUNK_POINTS):
                    piece = [(x / geo.SCALE, y / geo.SCALE) for x, y in simp[a:a + CHUNK_POINTS + 1]]
                    feats.append(meta + [geo.encode([piece], org, ring=False)[0]])
        if geo.rendered_len(feats) <= MAP_BUDGET:
            break
    chunks = geo.pack(feats)

    zoom = []
    for a in [a for a in auths if a != UNKNOWN][:ZOOM_TOP]:
        zoom.append({"name": a, "bounds": _bounds([s["parts"] for s in by_auth[a]])})
    legend = [{"name": t, "km": _km(by_type[t][0]), "count": _int(by_type[t][1])} for t in types]

    bands, width = _lat_bands(drawn)
    band_rows = [{"name": f"{b['lead']} {_deg(b['lo'], width)}°",
                  "range": f"{_deg(b['lo'], width)} עד {_deg(b['hi'], width)}",
                  "lead": b["lead"], "km": _km(b["m"]),
                  "share": _pct(b["m"] / total_m) if total_m else "0.0%"} for b in bands]

    declared = [s["declared"] for s in drawn if not pd.isna(s["declared"]) and s["declared"] > 0]
    decl_m = float(sum(declared))
    dev = [abs(s["m"] / s["declared"] - 1) for s in drawn
           if not pd.isna(s["declared"]) and s["declared"] > 0]
    far = sum(1 for d in dev if d > 0.1)
    if decl_m > 0 and len(declared) == len(drawn):
        match = (f" האורך הנמדד על הקווים, {_km(total_m)} ק\"מ, שונה ב-{_pct(abs(total_m / decl_m - 1))} "
                 f"מהאורך המוצהר במאגר ({_km(decl_m)} ק\"מ)"
                 + (f"; ב-{_int(far)} מקטעים ההפרש עולה על 10%." if far else
                    "; בכל מקטע ההפרש קטן מ-10%."))
    else:
        match = f" האורך הנמדד על הקווים: {_km(total_m)} ק\"מ."
    note = (f"{_int(len(drawn))} מקטעים מצוירים כקווים, בצבע לפי סוג הנתיב. לחיצה על קו מציגה את שם "
            f"המקטע, הרשות ושעות הפעילות בימי חול; הכפתורים מתמקדים ב-{_int(len(zoom))} הרשויות עם "
            f"האורך הרב ביותר." + match
            + (f" {_int(missing)} מקטעים ללא קו במפה אינם מצוירים." if missing else ""))
    lead_band = max(bands, key=lambda b: (b["m"], b["lo"])) if bands else None
    lat_note = (f"אורך הקווים במפה לפי רצועות רוחב של {_deg(width, width)} מעלות (כ-{_int(width * KM_PER_DEG_LAT)} ק\"מ), "
                f"מצפון לדרום. כל רצועה נקראת על שם הרשות עם האורך הרב ביותר בה וקו הרוחב הדרומי שלה."
                + (f" הצפופה ביותר: {lead_band['lead']} ({_km(lead_band['m'])} ק\"מ)." if lead_band else ""))
    model = {
        "map": {"chunks": chunks, "origin": org, "scale": geo.SCALE, "types": types, "auths": auths, "hours": hours, "legend": legend,
                "zoom": zoom, "bounds": _bounds([s["parts"] for s in drawn])},
        "lat": {"names": [r["name"] for r in band_rows], "values": [round(b["m"] / 1000, 2) for b in bands],
                "ranges": [r["range"] for r in band_rows]},
    }
    labels = {
        "map_note": note,
        "map_aria": (f"מפה אינטראקטיבית של {_int(len(drawn))} מקטעי נתיבי העדפה, קווים בצבע לפי סוג. "
                     f"גרסה נגישה: טבלת הנתונים מתחת לעמוד."),
        "lat_note": lat_note,
        "lat_aria": ("תרשים עמודות: ק\"מ של נתיבי העדפה במפה לפי רצועת קו רוחב, מצפון לדרום."
                     + (f" הצפופה ביותר: {lead_band['lead']}." if lead_band else "")),
    }
    insights = [("extent", insight_extent(drawn)), ("band", insight_band(bands, width, total_m))]
    return model, {"lat": band_rows}, labels, insights, bool(drawn), len(bands) >= 2


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    n = len(df)
    total_m = float(df["len"].sum())

    # --- types × urban/interurban
    by_type_m = _ranked(df.groupby("PTLTYPE")["len"].sum())
    by_type_n = df.groupby("PTLTYPE").size()
    urb_vals = _ranked(df.groupby("URBANTYPE")["len"].sum())
    urb_names = list(urb_vals.index)
    types = list(by_type_m.index)
    piv = df.pivot_table(index="PTLTYPE", columns="URBANTYPE", values="len",
                         aggfunc="sum", fill_value=0)
    type_series = [{"name": u, "data": [round(float(piv.at[t, u]) / 1000, 2) if u in piv.columns else 0
                                        for t in types]} for u in urb_names]
    type_rows = [{"name": t, "info": TYPE_INFO.get(t, ""), "count": _int(by_type_n[t]),
                  "km": _km(by_type_m[t]), "share": _pct(by_type_m[t] / total_m) if total_m else "0.0%",
                  "cells": [_km(piv.at[t, u]) if u in piv.columns else "0.0" for u in urb_names]}
                 for t in types]

    # --- local authorities
    by_auth = _ranked(df.groupby("AUTHORITY")["len"].sum())
    auth_n = df.groupby("AUTHORITY").size()
    a_names, a_vals = _top_other(by_auth, TOP_AUTH, "רשויות אחרות")
    auth_rows = []
    for nm, v in zip(a_names, a_vals):
        cnt = auth_n[nm] if nm in auth_n.index else int(auth_n[~auth_n.index.isin(a_names)].sum())
        auth_rows.append({"name": nm, "count": _int(cnt), "km": _km(v),
                          "share": _pct(v / total_m) if total_m else "0.0%"})
    n_auth = int(df.loc[df["AUTHORITY"] != UNKNOWN, "AUTHORITY"].nunique())

    # --- traffic authorities; "national" = a body that never appears as a local authority
    local_set = set(df["AUTHORITY"])
    by_traf = _ranked(df.groupby("TRAFAUTH")["len"].sum())
    t_names, t_vals = _top_other(by_traf, TOP_TRAF, "גופים אחרים")
    nat = [t for t in by_traf.index if t not in local_set and t != UNKNOWN]
    nat_m = float(by_traf[nat].sum()) if nat else 0.0
    traf_rows = [{"name": nm, "km": _km(v), "share": _pct(v / total_m) if total_m else "0.0%",
                  "kind": "גוף ארצי או ייעודי" if nm in nat else ("" if nm == "גופים אחרים" else "רשות מקומית")}
                 for nm, v in zip(t_names, t_vals)]

    # --- roads (interurban numbers) and streets
    roads = df[df["ROADNAME"] != ""]
    by_road = _ranked(roads.groupby("ROADNAME")["len"].sum())
    r_top = by_road.iloc[:TOP_ROADS]
    road_rows = [{"name": f"כביש {r}", "km": _km(v), "count": _int((roads["ROADNAME"] == r).sum())}
                 for r, v in r_top.items()]
    streets = df[df["STREETNAME"] != ""]
    by_street = _ranked(streets.groupby("STREETNAME")["len"].sum())
    s_top = by_street.iloc[:TOP_ROADS]
    street_auth = (streets.groupby(["STREETNAME", "AUTHORITY"])["len"].sum().reset_index()
                   .sort_values(["STREETNAME", "len", "AUTHORITY"], ascending=[True, False, True],
                                kind="stable").drop_duplicates("STREETNAME").set_index("STREETNAME")["AUTHORITY"])
    street_rows = [{"name": s, "auth": street_auth.get(s, UNKNOWN), "km": _km(v)} for s, v in s_top.items()]

    # --- operating hours
    day_stats, hour_series = {}, []
    for key, label, wins in DAYS:
        hrs = _active_hours(df, wins)
        lens = list(df["len"])
        per_h = [sum(l for l, s in zip(lens, hrs) if h in s) for h in range(24)]
        m24 = sum(l for l, s in zip(lens, hrs) if len(s) == 24)
        active_m = sum(l for l, s in zip(lens, hrs) if s)
        day_stats[key] = {"label": label, "per_h": per_h, "m24": m24, "active_m": active_m,
                          "total_m": total_m, "n_active": sum(1 for s in hrs if s)}
        hour_series.append({"name": label, "data": [round(v / 1000, 1) for v in per_h]})
    hour_labels = [f"{h:02d}:00" for h in range(24)]
    hour_rows = [{"h": hour_labels[h], "cells": [_km(day_stats[k]["per_h"][h]) for k, _, _ in DAYS]}
                 for h in range(24)]
    wk = day_stats["WK"]
    share24 = wk["m24"] / total_m if total_m else 0.0
    sat_share = day_stats["SAT"]["active_m"] / total_m if total_m else 0.0
    peak_wk_h = max(range(24), key=lambda h: (wk["per_h"][h], -h))
    low_wk_h = min(range(24), key=lambda h: (wk["per_h"][h], h))
    by_op = _ranked(df.groupby("OPTYPE")["len"].sum())
    op_rows = [{"name": o, "km": _km(v), "count": _int((df["OPTYPE"] == o).sum())} for o, v in by_op.items()]

    # --- permitted users
    users = []
    for col, label in USERS:
        yes = df[col] == "כן"
        users.append({"name": label, "km": float(df.loc[yes, "len"].sum()), "count": int(yes.sum())})
    users.sort(key=lambda u: (-u["km"], u["name"]))
    user_rows = [{"name": u["name"], "count": _int(u["count"]), "km": _km(u["km"]),
                  "share": _pct(u["km"] / total_m) if total_m else "0.0%"} for u in users]

    # --- infrastructure: paint, separation, enforcement (km shares)
    infra = {}
    infra_rows = []
    for col, title in [("PAINT", "צביעת הנתיב"), ("DIVISION", "הפרדה מהתנועה הכללית"),
                       ("ENFORCMENT", "אכיפה")]:
        s = _ranked(df.groupby(col)["len"].sum())
        names, vals = _top_other(s, 5, "אחר")
        infra[col] = {"title": title, "items": [{"name": nm, "value": round(v / 1000, 2)}
                                                for nm, v in zip(names, vals)]}
        for nm, v in zip(names, vals):
            infra_rows.append({"group": title, "name": nm, "km": _km(v),
                               "share": _pct(v / total_m) if total_m else "0.0%"})
    known_enf = df[df["ENFORCMENT"] != UNKNOWN]
    cam_m = float(known_enf.loc[known_enf["ENFORCMENT"].str.contains("מצלמה", regex=False), "len"].sum())
    cam_share = cam_m / float(known_enf["len"].sum()) if len(known_enf) and known_enf["len"].sum() else 0.0

    # --- lanes alongside
    def lane_label(v):
        if pd.isna(v):
            return UNKNOWN
        return f"{int(v)} נתיבים" if v != 1 else "נתיב אחד"
    df["other_lbl"] = df["nother"].map(lane_label)
    lane_order = sorted(df["nother"].dropna().astype(int).unique())
    lane_names = [lane_label(v) for v in lane_order] + ([UNKNOWN] if df["nother"].isna().any() else [])
    lane_m = df.groupby("other_lbl")["len"].sum()
    lane_n = df.groupby("other_lbl").size()
    lane_rows = [{"name": nm, "count": _int(lane_n.get(nm, 0)), "km": _km(lane_m.get(nm, 0)),
                  "share": _pct(lane_m.get(nm, 0) / total_m) if total_m else "0.0%"} for nm in lane_names]
    two_bus = int((df["nl"] >= 2).sum())
    hov_n = int(df["hov"].notna().sum())
    hot_n = int(df["hot"].notna().sum())
    hov_min = int(df["hov"].min()) if hov_n else 0
    hov_max = int(df["hov"].max()) if hov_n else 0
    main_other = lane_m.drop(UNKNOWN, errors="ignore")
    main_other = _ranked(main_other) if not main_other.empty else main_other

    # --- segment length distribution
    bin_counts, bin_km = [], []
    for lo, hi, _ in LEN_BINS:
        sel = (df["len"] >= lo) & (df["len"] < hi)
        bin_counts.append(int(sel.sum()))
        bin_km.append(float(df.loc[sel, "len"].sum()))
    len_rows = [{"name": lbl, "count": _int(c), "km": _km(k)}
                for (_, _, lbl), c, k in zip(LEN_BINS, bin_counts, bin_km)]
    longest = df.sort_values(["len", "PTLNAME"], ascending=[False, True], kind="stable").head(8)
    long_rows = [{"name": r["PTLNAME"], "type": r["PTLTYPE"], "auth": r["AUTHORITY"], "km": _km(r["len"])}
                 for _, r in longest.iterrows()]
    median_m = float(df["len"].median()) if n else 0.0
    long_share = (sum(bin_km[-2:]) / total_m) if total_m else 0.0
    long_n = sum(bin_counts[-2:])

    # --- timeline: start year vs last-change year
    sy = df.dropna(subset=["start_year"])
    cyy = df.dropna(subset=["change_year"])
    years = sorted(set(sy["start_year"].astype(int)) | set(cyy["change_year"].astype(int)))
    time_x, time_start, time_change, time_rows = [], [], [], []
    if years:
        y_last = years[-1]
        cut = y_last - YEARS_SHOWN + 1
        groups = []
        if years[0] < cut:
            groups.append((f"עד {cut - 1}", lambda y, c=cut: y < c))
        for y in range(max(years[0], cut), y_last + 1):
            groups.append((str(y), lambda yy, y=y: yy == y))
        for lbl, pred in groups:
            ms = sy["start_year"].astype(int).map(pred)
            mc = cyy["change_year"].astype(int).map(pred)
            ns, nc = int(ms.sum()), int(mc.sum())
            km_s = float(sy.loc[ms, "len"].sum())
            time_x.append(lbl)
            time_start.append(ns)
            time_change.append(nc)
            time_rows.append({"year": lbl, "started": _int(ns), "started_km": _km(km_s), "changed": _int(nc)})
    start_known = len(sy)
    start_min = int(sy["start_year"].min()) if start_known else None
    change_max = int(cyy["change_year"].max()) if len(cyy) else None

    # --- KPIs
    corridors = int(df.loc[df["PTLCODE"] != "", "PTLCODE"].nunique())
    canc = df[df["STATUS"].str.contains("יבוטל", regex=False)]
    kpis = {
        "km": {"value": round(total_m / 1000, 1), "display": _km(total_m), "tone": "brand"},
        "segments": {"value": n, "display": _int(n), "tone": "brand"},
        "corridors": {"value": corridors, "display": _int(corridors), "tone": "brand"},
        "authorities": {"value": n_auth, "display": _int(n_auth), "tone": "brand"},
        "share24": {"value": round(share24, 4), "display": _pct(share24), "tone": "info"},
        "sat": {"value": round(sat_share, 4), "display": _pct(sat_share),
                "tone": "ok" if sat_share >= 0.5 else "warn"},
        "camera": {"value": round(cam_share, 4), "display": _pct(cam_share),
                   "tone": "ok" if cam_share >= 0.5 else "warn"},
        "cancel": {"value": len(canc), "display": _int(len(canc)),
                   "tone": "warn" if len(canc) else "ok"},
    }

    # --- insights
    rules = [
        ("auth_lead", insight_auth_lead(by_auth, total_m)),
        ("type_mix", insight_type_mix(by_type_m, by_type_n, total_m)),
        ("national", insight_national(nat_m, total_m, [t for t in by_traf.index if t in nat])),
        ("hours", insight_hours(day_stats)),
        ("enforcement", insight_enforcement(df)),
        ("paint", insight_paint(df)),
        ("cancel", insight_cancel(df)),
        ("start", insight_start(df)),
    ]
    geo_model, geo_tables, geo_labels, geo_rules, has_map, has_lat = _geo_section(frames["geo"])
    rules += geo_rules
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    lead_auth = by_auth[by_auth.index != UNKNOWN]
    lead_type = by_type_m.index[0] if len(by_type_m) else UNKNOWN
    summary = (f"מפת נת\"צים ונתיבי העדפה לתחבורה ציבורית בישראל, עם איתור לפי רחוב, כביש או רשות: "
               f"{_int(n)} מקטעים באורך {_km(total_m)} ק\"מ ב-{_int(n_auth)} רשויות.")

    urb_share = {u: (float(urb_vals[u]) / total_m if total_m else 0.0) for u in urb_names}
    labels = {
        **geo_labels,
        "lede": (f"השכבה הארצית של משרד התחבורה מתעדת {_int(n)} מקטעים של נתיבי העדפה לתחבורה "
                 f"ציבורית: נת\"צים, מת\"צים, רחובות תחבורה ציבורית והעדפה בצמתים, באורך כולל של "
                 f"{_km(total_m)} ק\"מ ב-{_int(n_auth)} רשויות מקומיות. לכל מקטע מפורטים סוג הנתיב, "
                 f"הגוף האחראי, שעות הפעילות בימי חול, שישי ושבת, מי עוד רשאי לנסוע בו, "
                 f"ואופן ההפרדה והאכיפה."),
        "km_kpi": "אורך כולל (ק\"מ)",
        "segments_kpi": "מקטעי נתיב",
        "corridors_kpi": "צירים (קודי נת\"צ)",
        "authorities_kpi": "רשויות מקומיות",
        "share24_kpi": "מהאורך פעיל כל היממה בימי חול",
        "sat_kpi": "מהאורך פעיל גם בשבת",
        "camera_kpi": "מהאורך עם אכיפה מתועדת נאכף במצלמה",
        "cancel_kpi": "מקטעים שצפויים להתבטל",
        "types_note": (f"{lead_type} הוא הסוג הנפוץ ביותר ({_pct(by_type_m.iloc[0] / total_m) if total_m and len(by_type_m) else '0.0%'} "
                       f"מהאורך). העמודות מפוצלות לפי סוג הדרך: "
                       + ", ".join(f"{u} {_pct(urb_share[u])}" for u in urb_names) + " מהאורך."),
        "types_aria": (f"תרשים עמודות מוערמות: אורך נתיבי ההעדפה בק\"מ לפי סוג הנתיב וסוג הדרך. "
                       f"הסוג המוביל: {lead_type}."),
        "auth_note": (f"נתיבי העדפה ב-{_int(n_auth)} רשויות מקומיות; מוצגות "
                      f"{TOP_AUTH if len(by_auth) > TOP_AUTH + 1 else len(by_auth)} הרשויות עם האורך הרב ביותר"
                      + (", והשאר מקובצות" if len(by_auth) > TOP_AUTH + 1 else "") + "."
                      + (f" מקטעים ללא רשות מסומנים \"{UNKNOWN}\"." if UNKNOWN in by_auth.index else "")),
        "auth_aria": (f"תרשים עמודות: אורך נתיבי ההעדפה בק\"מ לפי רשות מקומית. "
                      f"המובילה: {lead_auth.index[0]} עם {_km(lead_auth.iloc[0])} ק\"מ." if len(lead_auth) else
                      "תרשים עמודות: אורך נתיבי ההעדפה לפי רשות מקומית."),
        "traf_note": (f"רשות התמרור האחראית על הנתיב אינה תמיד הרשות המקומית: {_pct(nat_m / total_m) if total_m else '0.0%'} "
                      f"מהאורך באחריות גופים ארציים או ייעודיים (בגוון כהה בתרשים), "
                      f"השאר באחריות רשויות מקומיות."),
        "traf_aria": (f"תרשים עמודות: אורך נתיבי ההעדפה לפי רשות תמרור. "
                      f"{by_traf.index[0]} מובילה עם {_km(by_traf.iloc[0])} ק\"מ." if len(by_traf) else
                      "תרשים עמודות: אורך נתיבי ההעדפה לפי רשות תמרור."),
        "roads_note": (f"{_km(roads['len'].sum())} ק\"מ ({_pct(roads['len'].sum() / total_m) if total_m else '0.0%'}) "
                       f"נמצאים על כבישים ממוספרים; מוצגים {len(r_top)} הכבישים עם האורך הרב ביותר."),
        "roads_aria": (f"תרשים עמודות: אורך נתיבי ההעדפה לפי מספר כביש. המוביל: כביש {by_road.index[0]} "
                       f"עם {_km(by_road.iloc[0])} ק\"מ." if len(by_road) else "תרשים עמודות: אורך לפי כביש."),
        "streets_note": (f"הרחובות והדרכים עם האורך הרב ביותר של נתיבי העדפה, לפי שם הרחוב או הדרך "
                         f"(מתוך {_int(len(by_street))} שמות במאגר)."),
        "streets_aria": (f"תרשים עמודות: אורך נתיבי ההעדפה לפי רחוב. המוביל: {by_street.index[0]} "
                         f"עם {_km(by_street.iloc[0])} ק\"מ." if len(by_street) else "תרשים עמודות: אורך לפי רחוב."),
        "hours_note": (f"אורך הנתיבים הפעילים כנתיב העדפה בכל שעה. בימי חול השיא בשעה {hour_labels[peak_wk_h]} "
                       f"({_km(wk['per_h'][peak_wk_h])} ק\"מ) והשפל בשעה {hour_labels[low_wk_h]} "
                       f"({_km(wk['per_h'][low_wk_h])} ק\"מ). מקטע שלא צוינו לו שעות ביום מסוים נספר כלא פעיל באותו יום."),
        "hours_aria": (f"גרף קווים: ק\"מ של נתיבי העדפה פעילים לפי שעה ביום חול, שישי ושבת. "
                       f"{_pct(share24)} מהאורך פעיל כל היממה בימי חול."),
        "users_note": (f"שיעור האורך שבו רשאים לנסוע גם כלי רכב נוספים מלבד אוטובוסים בקווים סדירים, "
                       f"או שקיים בו מאפיין מיוחד. "
                       f"הנפוץ ביותר: {users[0]['name']} ({_pct(users[0]['km'] / total_m) if total_m else '0.0%'} מהאורך)."
                       if users else ""),
        "users_aria": (f"תרשים עמודות: שיעור אורך הנתיבים לפי משתמשים מורשים. המוביל: {users[0]['name']}."
                       if users else "תרשים עמודות: משתמשים מורשים."),
        "infra_note": (f"פילוח האורך לפי צביעה, הפרדה פיזית ואכיפה. מתוך האורך שבו האכיפה מתועדת, "
                       f"{_pct(cam_share)} נאכף במצלמה. ערכים חסרים מסומנים \"{UNKNOWN}\"."),
        "infra_aria": "שלושה תרשימי טבעת: אורך הנתיבים לפי מצב הצביעה, סוג ההפרדה ואופן האכיפה.",
        "lanes_note": ("כמה נתיבי תנועה כללית נותרים לצד נתיב ההעדפה. "
                       + (f"הנפוץ: {main_other.index[0]} ({_pct(main_other.iloc[0] / total_m) if total_m else '0.0%'} מהאורך). "
                          if len(main_other) else "")
                       + f"ב-{_int(two_bus)} מקטעים יש שני נתיבי העדפה"
                       + (f", וב-{_int(hov_n)} מקטעים הנתיב פתוח גם לרכב רב תפוסה ({hov_min}-{hov_max} נוסעים לפחות)"
                          if hov_n else "")
                       + ((f"; {_int(hot_n)} מקטעים מוגדרים כנתיב אגרה" if hot_n > 1 else "; מקטע אחד מוגדר כנתיב אגרה")
                          if hot_n else "") + "."),
        "lanes_aria": ("תרשים עמודות: אורך הנתיבים לפי מספר נתיבי התנועה הכללית לצדם. "
                       + (f"הנפוץ: {main_other.index[0]}." if len(main_other) else "")),
        "length_note": (f"חציון אורך מקטע: {_int(median_m)} מ'. {_int(long_n)} המקטעים שאורכם מעל 2 ק\"מ "
                        f"מהווים {_pct(long_share)} מכלל האורך."),
        "length_aria": (f"תרשים עמודות: מספר המקטעים לפי טווח אורך. חציון {_int(median_m)} מטרים."),
        "time_note": (f"תאריך הפעלה ידוע ל-{_int(start_known)} מתוך {_int(n)} מקטעים ({_pct(start_known / n) if n else '0.0%'}); "
                      f"תאריך העדכון האחרון קיים לכל מקטע."
                      + (f" השנים {time_x[0]} מקובצות לעמודה אחת." if time_x and time_x[0].startswith("עד") else "")),
        "time_aria": ("תרשים עמודות: מספר המקטעים לפי שנת הפעלה ולפי שנת עדכון אחרון"
                      + (f", עד {time_x[-1]}." if time_x else ".")),
    }

    temporal = f"{start_min}/{change_max}" if start_min and change_max else None
    agent_data = {
        "summary_he": summary,
        "dataset_kind": "map",
        "spatial_coverage": "ישראל",
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    nat_flags = [nm in nat for nm in t_names]
    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "types": {"names": types, "series": type_series},
            "auth": {"names": a_names, "values": [round(v / 1000, 2) for v in a_vals]},
            "traf": {"names": t_names, "values": [round(v / 1000, 2) for v in t_vals], "national": nat_flags},
            "roads": {"names": [f"כביש {r}" for r in r_top.index], "values": [round(v / 1000, 2) for v in r_top]},
            "streets": {"names": list(s_top.index), "values": [round(v / 1000, 2) for v in s_top]},
            "hours": {"x": hour_labels, "series": hour_series},
            "users": {"names": [u["name"] for u in users],
                      "values": [round(u["km"] / total_m * 100, 1) if total_m else 0 for u in users]},
            "infra": [infra["PAINT"], infra["DIVISION"], infra["ENFORCMENT"]],
            "lanes": {"names": lane_names,
                      "values": [round(float(lane_m.get(nm, 0)) / 1000, 2) for nm in lane_names]},
            "length": {"names": [b[2] for b in LEN_BINS], "values": bin_counts},
            "time": {"x": time_x, "started": time_start, "changed": time_change},
            **geo_model,
        },
        "tables": {
            "types": type_rows, "types_head": urb_names,
            "auth": auth_rows, "traf": traf_rows, "roads": road_rows, "streets": street_rows,
            "hours": hour_rows, "hours_head": [lbl for _, lbl, _ in DAYS], "op": op_rows,
            "users": user_rows, "infra": infra_rows, "lanes": lane_rows,
            "length": len_rows, "longest": long_rows, "time": time_rows,
            **geo_tables,
        },
        "flags": {"roads": bool(len(by_road)), "streets": bool(len(by_street)), "time": bool(time_x),
                  "map": has_map, "lat": has_lat},
        "insights": insights,
        "labels": labels,
    }
