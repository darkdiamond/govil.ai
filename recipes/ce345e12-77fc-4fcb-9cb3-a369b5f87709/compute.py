"""Metrofan: the planned bicycle-path network of the Haifa metropolitan core.

The only input is the layer's shapefile (a `map: true` input: the refresh
downloads it every run and hands compute one row per path segment, its
attributes as strings plus `__geometry`, WGS84 GeoJSON). The datastore CSV
carries the same attribute table, so the map file alone feeds the page.

Units: a segment (one row), a route (segments sharing ID: one route can be
split into many short pieces), a hierarchy level (TYPE: ראשי, מטרופוליני,
מזין, מקומי) and a status (STATUS: קיים / מתוכנן). Lengths are LENGT, in
metres (ITM), when it agrees with the geometry; otherwise the measured length.
"""
import itertools
import json

import pandas as pd
from govlib import fmt, geo

# Known hierarchy and status orders; unknown values follow, longest first.
TYPE_ORDER = ["ראשי", "מטרופוליני", "מזין", "מקומי"]
STATUS_EXISTING = "קיים"
STATUS_PLANNED = "מתוכנן"
UNKNOWN = "לא צוין"

TOP_ROUTES = 15
TOP_STREETS = 12
TOP_CITIES = 10
CHUNK_POINTS = 1_500
MAP_BUDGET = 260_000           # rendered chars of all map islands together
SIMPLIFY_M = [0, 2, 5, 10, 20, 40]
LEN_BINS = [0, 250, 500, 1000, 1500, 2000, 3000, 5000]   # metres
BUILT_MIN_M = 2000             # an authority needs this much plan for its built share
ONLY_SHARE = 0.25              # below this share a sentence says "רק"
# A route's state from its segments' statuses.
ROUTE_STATES = ["קיים", "קיים בחלקו", "מתוכנן", "סטטוס אחר"]


def _s(v):
    return " ".join(str(v or "").split())


def _km(m, digits=1):
    return fmt.num_he(m / 1000, digits)


def _lines_of(geom):
    if not isinstance(geom, dict):
        return []
    if geom.get("type") == "LineString":
        return [geom.get("coordinates") or []]
    if geom.get("type") == "MultiLineString":
        return geom.get("coordinates") or []
    if geom.get("type") == "GeometryCollection":
        return [p for g in geom.get("geometries") or [] for p in _lines_of(g)]
    return []


def _measured(parts):
    total = 0.0
    for p in parts:
        for a, b in itertools.pairwise(p):
            total += geo.haversine_km(a[1], a[0], b[1], b[0]) * 1000
    return total


def _prepare(df):
    rows = []
    for r in df.to_dict("records"):
        try:
            g = json.loads(r.get("__geometry") or "null")
        except ValueError:
            g = None
        parts = [[(float(x), float(y)) for x, y, *_ in p] for p in _lines_of(g)]
        parts = [p for p in parts if len(p) >= 2]
        decl = pd.to_numeric(_s(r.get("LENGT")).replace(",", ""), errors="coerce")
        if pd.isna(decl):
            decl = pd.to_numeric(_s(r.get("Shape_Leng")).replace(",", ""), errors="coerce")
        meas = _measured(parts)
        # The declared length when the geometry confirms it (a re-export in
        # another unit falls back to the measured one).
        if not pd.isna(decl) and decl > 0 and (meas <= 0 or 0.8 <= decl / meas <= 1.25):
            m = float(decl)
        else:
            m = meas
        if m <= 0:
            continue
        rid = _s(r.get("ID")) or f"o{_s(r.get('OBJECTID'))}"
        rows.append({
            "rid": rid,
            "city": _s(r.get("CITY")) or UNKNOWN,
            "start": _s(r.get("START_")),
            "dest": _s(r.get("DESTNATION")),
            "street": _s(r.get("STREET")),
            "type": _s(r.get("TYPE")) or UNKNOWN,
            "status": _s(r.get("STATUS")) or UNKNOWN,
            "m": m,
            "parts": parts,
            "key": r.get("__geometry") or "",
        })
    rows.sort(key=lambda x: (x["rid"], x["city"], x["type"], x["status"], x["start"], x["dest"],
                             x["street"], x["m"], x["key"]))
    return rows


def _order(sums, known):
    present = [k for k in known if k in sums]
    rest = sorted((k for k in sums if k not in known), key=lambda k: (-sums[k], k))
    return present + rest


def _sum_by(rows, key):
    out = {}
    for x in rows:
        out[x[key]] = out.get(x[key], 0.0) + x["m"]
    return out


def _rank(d):
    return sorted(d, key=lambda k: (-d[k], k))


def _bounds(parts_list):
    """[[s, w], [n, e]] of every point; None when there is none."""
    lons = [pt[0] for parts in parts_list for p in parts for pt in p]
    lats = [pt[1] for parts in parts_list for p in parts for pt in p]
    if not lons:
        return None
    return [[round(min(lats), 5), round(min(lons), 5)], [round(max(lats), 5), round(max(lons), 5)]]


def _routes(rows):
    by = {}
    for x in rows:
        by.setdefault(x["rid"], []).append(x)
    out = []
    for rid, ss in by.items():
        main = min(ss, key=lambda s: (-s["m"], s["key"]))
        m = sum(s["m"] for s in ss)
        ex = sum(s["m"] for s in ss if s["status"] == STATUS_EXISTING)
        if ex >= m * 0.999:
            state = 0
        elif ex > 0:
            state = 1
        elif all(s["status"] == STATUS_PLANNED for s in ss):
            state = 2
        else:
            state = 3
        if main["start"] and main["dest"] and main["start"] != main["dest"]:
            name = f"{main['start']} - {main['dest']}"
        elif main["street"]:
            name = main["street"]
        elif main["start"]:
            name = main["start"]
        else:
            name = f"מסלול {rid} ב{main['city']}"
        out.append({"rid": rid, "name": name, "city": main["city"], "type": main["type"],
                    "street": main["street"], "m": m, "ex": ex, "n": len(ss), "state": state})
    out.sort(key=lambda r: (-r["m"], r["name"], r["rid"]))
    return out


def _map(rows, types, statuses, cities):
    """Map model for the segments that carry geometry; None when none does."""
    rows = [x for x in rows if x["parts"]]
    if not rows:
        return None
    org = geo.origin([pt[0] for x in rows for p in x["parts"] for pt in p],
                     [pt[1] for x in rows for p in x["parts"] for pt in p])
    for tol in SIMPLIFY_M:
        tol_u = tol / 1.1
        feats = []
        for x in rows:
            meta = [types.index(x["type"]), statuses.index(x["status"]), cities.index(x["city"]),
                    x["start"], x["dest"], x["street"], _km(x["m"], 2)]
            for p in x["parts"]:
                simp = geo.simplify(geo.quantize(p), tol_u, ring=False)
                if len(simp) < 2:
                    simp = geo.quantize([p[0], p[-1]])
                    if len(simp) < 2:
                        continue
                for a in range(0, len(simp) - 1, CHUNK_POINTS):
                    piece = [(px / geo.SCALE, py / geo.SCALE) for px, py in simp[a:a + CHUNK_POINTS + 1]]
                    feats.append(meta + [geo.encode([piece], org, ring=False)[0]])
        if geo.rendered_len(feats) <= MAP_BUDGET:
            break
    if not feats:
        return None
    by_city = {}
    for x in rows:
        by_city.setdefault(x["city"], []).append(x["parts"])
    city_m = _sum_by(rows, "city")
    zoom = [{"name": c, "bounds": _bounds(by_city[c])} for c in _rank(city_m)[:TOP_CITIES]]
    zoom = [z for z in zoom if z["bounds"]]
    return {"chunks": geo.pack(feats), "origin": org, "scale": geo.SCALE, "types": types,
            "statuses": statuses, "cities": cities,
            "existing": statuses.index(STATUS_EXISTING) if STATUS_EXISTING in statuses else -1,
            "zoom": zoom if len(zoom) > 1 else [],
            "bounds": _bounds([x["parts"] for x in rows]), "drawn": len(rows)}


# ── insights ─────────────────────────────────────────────────────────────


def _rest_he(total, ex, planned):
    """How the non-existing length splits: all planned, or planned + other."""
    other = total - ex - planned
    if other <= total * 1e-6:
        return "והשאר מתוכנן"
    return f"{_km(planned)} ק״מ מתוכננים ו-{_km(other)} ק״מ בסטטוס אחר"


def insight_size(total, ex, planned, n_routes, n_cities):
    if total <= 0:
        return None
    head = f"השכבה ממפה {n_routes:,} מסלולי אופניים באורך {_km(total)} ק״מ ב-{n_cities:,} רשויות"
    if ex <= 0:
        if planned >= total * 0.999999:
            return head + ", וכולם מסומנים כמתוכננים."
        return head + f". אף מקטע אינו מסומן כקיים: {_rest_he(total, ex, planned)}."
    only = "רק " if ex / total < ONLY_SHARE else ""
    return (head + f". {only}{_km(ex)} ק״מ ({fmt.pct(ex / total)}) מסומנים כקיימים, "
            f"{_rest_he(total, ex, planned)}.")


def insight_multiplier(total, ex):
    if ex <= 0 or total / ex < 1.5:
        return None
    return (f"אם התכנית תמומש במלואה, אורך הרשת יגדל פי {total / ex:,.1f}: "
            f"מ-{_km(ex)} ק״מ שבילים קיימים ל-{_km(total)} ק״מ.")


def insight_city_lead(city_m, total):
    order = _rank(city_m)
    if len(order) < 2 or total <= 0:
        return None
    a, b = order[0], order[1]
    if city_m[a] < city_m[b] * 1.3:
        return None
    return (f"{a} מחזיקה את החלק הגדול ברשת: {_km(city_m[a])} ק״מ, {fmt.pct(city_m[a] / total)} "
            f"מהאורך הכולל, פי {city_m[a] / city_m[b]:,.1f} מ{b} שבמקום השני.")


def insight_city_built(city_m, city_ex):
    eligible = [c for c in city_m if city_m[c] >= BUILT_MIN_M]
    if len(eligible) < 3:
        return None
    share = {c: city_ex.get(c, 0.0) / city_m[c] for c in eligible}
    best = min(eligible, key=lambda c: (-share[c], c))
    if share[best] <= 0:
        return None
    none = sorted(c for c in eligible if share[c] == 0)
    s = (f"{best} מתקדמת ביותר: {fmt.pct(share[best])} מהשבילים שתוכננו בה כבר קיימים "
         f"({_km(city_ex[best])} מתוך {_km(city_m[best])} ק״מ).")
    if none:
        s += f" ב{fmt.join_he(none)} אין עדיין אף מקטע קיים."
    return s


def insight_hierarchy(type_m, types, total):
    if len(types) < 2 or total <= 0:
        return None
    top = _rank(type_m)[0]
    share = type_m[top] / total
    if share < 0.3:
        return None
    return (f"רמת השביל {top} היא הגדולה ברשת: {_km(type_m[top])} ק״מ, {fmt.pct(share)} מהאורך. "
            f"שאר הרמות: " + ", ".join(f"{t} {_km(type_m[t])} ק״מ" for t in types if t != top) + ".")


def insight_type_built(type_m, type_ex):
    eligible = [t for t in type_m if type_m[t] >= BUILT_MIN_M]
    if len(eligible) < 2:
        return None
    share = {t: type_ex.get(t, 0.0) / type_m[t] for t in eligible}
    order = sorted(eligible, key=lambda t: (-share[t], t))
    hi, lo = order[0], order[-1]
    if share[hi] <= 0 or share[hi] - share[lo] < 0.05:
        return None
    return (f"שיעור השבילים הקיימים גבוה ביותר ברמת {hi}, {fmt.pct(share[hi])}, "
            f"ונמוך ביותר ברמת {lo}, {fmt.pct(share[lo])}.")


def insight_longest(routes, total):
    if len(routes) < 2 or total <= 0:
        return None
    r = routes[0]
    if r["m"] < routes[1]["m"] * 1.05:
        return None
    state = ROUTE_STATES[r["state"]]
    return (f"המסלול הארוך ביותר הוא {r['name']} ({r['city']}): {_km(r['m'])} ק״מ, "
            f"שביל {r['type']}, {state}.")


def insight_short(routes):
    if len(routes) < 10:
        return None
    lengths = sorted(r["m"] for r in routes)
    med = lengths[len(lengths) // 2] if len(lengths) % 2 else (lengths[len(lengths) // 2 - 1] + lengths[len(lengths) // 2]) / 2
    under = sum(1 for v in lengths if v < 1000)
    share = under / len(lengths)
    tail = f"{under:,} מתוך {len(lengths):,} המסלולים ({fmt.pct(share)}) קצרים מקילומטר"
    if share > 0.5:
        return f"רוב המסלולים קצרים: אורך חציוני של {fmt.int_he(med)} מטר, ו-{tail}."
    return f"אורך המסלול החציוני הוא {fmt.int_he(med)} מטר, ו-{tail}."


def compute(frames):
    rows = _prepare(frames["geo"])
    if not rows:
        raise ValueError("no usable path segments in the map file")
    total = sum(x["m"] for x in rows)
    ex_rows = [x for x in rows if x["status"] == STATUS_EXISTING]
    ex = sum(x["m"] for x in ex_rows)

    type_m = _sum_by(rows, "type")
    types = _order(type_m, TYPE_ORDER)
    status_m = _sum_by(rows, "status")
    statuses = _order(status_m, [STATUS_EXISTING, STATUS_PLANNED])
    planned = status_m.get(STATUS_PLANNED, 0.0)
    city_m = _sum_by(rows, "city")
    cities = _rank(city_m)
    city_ex = _sum_by(ex_rows, "city")
    type_ex = _sum_by(ex_rows, "type")
    routes = _routes(rows)
    n_routes = len(routes)

    # ── charts ──
    def stacked(keys, key):
        return [{"name": s, "data": [round(sum(x["m"] for x in rows if x[key] == k and x["status"] == s) / 1000, 2)
                                     for k in keys]} for s in statuses]

    chart_cities = {"names": cities, "series": stacked(cities, "city")}
    share_cities = [c for c in cities if city_m[c] >= BUILT_MIN_M]
    chart_built = {"names": share_cities,
                   "pct": [round(city_ex.get(c, 0.0) / city_m[c] * 100, 1) for c in share_cities],
                   "km": [round(city_m[c] / 1000, 1) for c in share_cities]}
    chart_types = {"names": types, "series": stacked(types, "type"),
                   "pct": [round(type_ex.get(t, 0.0) / type_m[t] * 100, 1) for t in types]}
    ct_m = {}
    for x in rows:
        ct_m[(x["city"], x["type"])] = ct_m.get((x["city"], x["type"]), 0.0) + x["m"]
    heat = [[j, i, round(ct_m[(c, t)] / 1000, 1)]
            for i, c in enumerate(cities) for j, t in enumerate(types) if ct_m.get((c, t), 0.0) > 0]
    chart_heat = {"x": types, "y": cities, "cells": heat, "max": max(h[2] for h in heat)}

    bins = LEN_BINS + [float("inf")]
    bin_labels = []
    for a, b in itertools.pairwise(bins):
        bin_labels.append(f"{a:,}+" if b == float("inf") else f"{a:,}-{b:,}")
    hist = [{"name": t, "data": [sum(1 for r in routes if r["type"] == t and a <= r["m"] < b)
                                 for a, b in itertools.pairwise(bins)]} for t in types]
    chart_hist = {"x": bin_labels, "series": hist,
                  "totals": [sum(s["data"][i] for s in hist) for i in range(len(bin_labels))]}

    top = routes[:TOP_ROUTES]
    chart_routes = {"names": [r["name"] for r in top], "km": [round(r["m"] / 1000, 2) for r in top],
                    "type": [r["type"] for r in top], "city": [r["city"] for r in top],
                    "state": [r["state"] for r in top], "states": ROUTE_STATES}
    route_legend = [{"i": k, "name": n} for k, n in enumerate(ROUTE_STATES) if k in chart_routes["state"]]

    # Streets keyed by (street, city): same-named streets in two authorities stay apart.
    street_m, street_ex = {}, {}
    for x in rows:
        if x["street"]:
            k = (x["street"], x["city"])
            street_m[k] = street_m.get(k, 0.0) + x["m"]
            if x["status"] == STATUS_EXISTING:
                street_ex[k] = street_ex.get(k, 0.0) + x["m"]
    streets = _rank(street_m)[:TOP_STREETS]
    chart_streets = {"names": [f"{st}, {c}" for st, c in streets],
                     "series": [{"name": STATUS_EXISTING, "data": [round(street_ex.get(k, 0.0) / 1000, 2) for k in streets]},
                                {"name": "לא קיים", "data": [round((street_m[k] - street_ex.get(k, 0.0)) / 1000, 2) for k in streets]}]}
    named_m = sum(street_m.values())

    # ── tables ──
    t_cities = [[c, _km(city_m[c]), _km(city_ex.get(c, 0.0)), fmt.pct(city_ex.get(c, 0.0) / city_m[c]),
                 f"{sum(1 for x in rows if x['city'] == c):,}"] for c in cities]
    t_types = [[t, _km(type_m[t]), _km(type_ex.get(t, 0.0)), fmt.pct(type_m[t] / total),
                f"{sum(1 for r in routes if r['type'] == t):,}"] for t in types]
    t_heat = [[c] + [_km(ct_m.get((c, t), 0.0)) for t in types] for c in cities]
    t_hist = [[bin_labels[i]] + [f"{s['data'][i]:,}" for s in hist] + [f"{chart_hist['totals'][i]:,}"]
              for i in range(len(bin_labels))]
    t_routes = [[r["name"], r["city"], r["type"], _km(r["m"], 2), ROUTE_STATES[r["state"]]] for r in top]
    t_streets = [[st, c, _km(street_m[(st, c)], 2), _km(street_ex.get((st, c), 0.0), 2)] for st, c in streets]
    t_built = [[c, f"{chart_built['pct'][i]:.1f}%", _km(city_m[c])] for i, c in enumerate(share_cities)]

    rules = [
        ("size", insight_size(total, ex, planned, n_routes, len(cities))),
        ("multiplier", insight_multiplier(total, ex)),
        ("city_lead", insight_city_lead(city_m, total)),
        ("city_built", insight_city_built(city_m, city_ex)),
        ("hierarchy", insight_hierarchy(type_m, types, total)),
        ("type_built", insight_type_built(type_m, type_ex)),
        ("longest", insight_longest(routes, total)),
        ("short", insight_short(routes)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    ex_share = ex / total
    kpis = {
        "total": {"value": round(total / 1000, 1), "display": _km(total), "tone": "brand"},
        "existing": {"value": round(ex / 1000, 1), "display": _km(ex), "tone": "ok"},
        "planned": {"value": round(planned / 1000, 1), "display": _km(planned), "tone": "info"},
        "share": {"value": round(ex_share * 100, 1), "display": fmt.pct(ex_share),
                  "tone": "warn" if ex_share < 0.25 else ("info" if ex_share < 0.5 else "ok")},
        "routes": {"value": n_routes, "display": f"{n_routes:,}", "tone": "brand"},
        "cities": {"value": len(cities), "display": f"{len(cities):,}", "tone": "brand"},
    }
    kpi_order = ["total", "existing", "planned", "share", "routes", "cities"]

    lead = cities[0]
    map_model = _map(rows, types, statuses, cities)
    drawn = map_model["drawn"] if map_model else 0
    named_share = named_m / total
    labels = {
        "kpi_total": "אורך הרשת המתוכננת (ק״מ)",
        "kpi_existing": "שבילים קיימים (ק״מ)",
        "kpi_planned": "שבילים מתוכננים (ק״מ)",
        "kpi_share": "שיעור הרשת שכבר קיים",
        "kpi_routes": "מסלולים בתכנית",
        "kpi_cities": "רשויות מקומיות",
        "lede": (f"מטרופן היא תכנית האב של משרד התחבורה לרשת שבילי אופניים בגלעין מטרופולין חיפה. "
                 f"השכבה כוללת {len(rows):,} מקטעים ב-{n_routes:,} מסלולים, באורך כולל של {_km(total)} ק״מ "
                 f"ב-{len(cities):,} רשויות, מהם {_km(ex)} ק״מ ({fmt.pct(ex_share)}) קיימים "
                 f"ו-{_km(planned)} ק״מ מתוכננים."),
        "map_note": ((f"כל {drawn:,} מקטעי השבילים" if drawn == len(rows)
                      else f"{drawn:,} מתוך {len(rows):,} מקטעי השבילים (לשאר אין תוואי בקובץ המפה)") + ", בצבע לפי רמת השביל. קו רציף ועבה מסמן שביל קיים, "
                     "קו מקווקו שביל מתוכנן. לחיצה על מקטע מציגה את הרשות, נקודות המוצא והיעד, הרחוב והאורך."
                     + (" הכפתורים מתמקדים בכל רשות." if len(cities) > 1 else "")),
        "map_aria": f"מפת {drawn:,} מקטעי שבילי האופניים בתכנית מטרופן, מטרופולין חיפה",
        "cities_lede": (f"אורך השבילים בכל רשות, קיים מול מתוכנן. {lead} מובילה עם {_km(city_m[lead])} ק״מ "
                        f"({fmt.pct(city_m[lead] / total)} מהרשת)."),
        "cities_aria": "אורך שבילי האופניים לפי רשות מקומית, קיים ומתוכנן, בקילומטרים",
        "built_lede": (f"איזה חלק מהשבילים שתוכננו בכל רשות כבר קיים בשטח (רשויות עם {_km(BUILT_MIN_M, 0)} "
                       "ק״מ ומעלה בתכנית)."),
        "built_aria": "שיעור השבילים הקיימים מתוך המתוכננים בכל רשות",
        "types_lede": (f"אורך הרשת בכל אחת מ-{len(types):,} רמות השביל בתכנית ({fmt.join_he(types)}), "
                       "ושיעור הקיים בכל רמה."),
        "types_aria": "אורך הרשת לפי רמת שביל, קיים ומתוכנן, בקילומטרים",
        "heat_lede": f"כמה קילומטרים מכל רמת שביל מתוכננים בכל רשות. {len(cities):,} רשויות, {len(types):,} רמות.",
        "heat_aria": "מפת חום של אורך השבילים לפי רשות ורמת שביל",
        "hist_lede": (f"התפלגות אורך {n_routes:,} המסלולים במטרים (מסלול הוא קבוצת מקטעים עם אותו מזהה), "
                      "לפי רמת השביל."),
        "hist_aria": "מספר המסלולים לפי טווח אורך ורמת שביל",
        "routes_lede": (f"{len(top):,} המסלולים הארוכים בתכנית, לפי נקודות המוצא והיעד שלהם "
                        "(או הרחוב, כשאין להם מוצא ויעד). צבע העמודה מסמן אם המסלול קיים, קיים בחלקו או לא."),
        "routes_aria": f"{len(top):,} מסלולי האופניים הארוכים בתכנית, בקילומטרים",
        "streets_lede": (f"הרחובות שלאורכם מתוכננים הכי הרבה שבילים, כל רחוב לפי הרשות שבה הוא עובר. "
                         f"{'רק ' if named_share < 0.5 else ''}{fmt.pct(named_share)} "
                         "מאורך הרשת משויך לשם רחוב, והשאר רשום בשכבה בלי שם רחוב."),
        "streets_aria": "הרחובות עם אורך שבילי האופניים הגדול ביותר, בקילומטרים",
    }

    summary = (f"תכנית מטרופן לשבילי אופניים במטרופולין חיפה: {n_routes:,} מסלולים, {_km(total)} ק״מ "
               f"ב-{len(cities):,} רשויות, מהם {fmt.pct(ex_share)} קיימים.")
    description = (f"מפת שבילי האופניים המתוכננים בחיפה, בקריות, בנשר ובטירת כרמל: {_km(total)} ק״מ, "
                   f"{fmt.pct(ex_share)} מהם כבר קיימים.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "spatial_coverage": "גלעין מטרופולין חיפה: " + ", ".join(cities[:6]),
            "seo": {
                "title": "מפת שבילי אופניים בחיפה והקריות | מטרופן",
                "description": description,
                "name": "מטרופן: רשת שבילי האופניים במטרופולין חיפה",
                "alternate_names": ["מטרופן", "שבילי אופניים חיפה", "תכנית אב לשבילי אופניים מטרופולין חיפה",
                                    "שבילי אופניים בקריות"],
            },
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": {
            "map": map_model,
            "cities": chart_cities,
            "built": chart_built,
            "types": chart_types,
            "heat": chart_heat,
            "hist": chart_hist,
            "routes": chart_routes,
            "streets": chart_streets,
        },
        "route_legend": route_legend,
        "tables": {"cities": t_cities, "types": t_types, "heat": t_heat, "hist": t_hist,
                   "routes": t_routes, "streets": t_streets, "built": t_built},
        "insights": insights,
        "labels": labels,
        "flags": {"map": map_model is not None, "types": len(types) > 1, "streets": len(streets) >= 3, "heat": len(types) > 1 and len(cities) > 1,
                  "built": ex > 0 and len(share_cities) > 1},
    }
