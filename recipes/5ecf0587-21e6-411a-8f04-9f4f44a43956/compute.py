"""Jerusalem metropolitan mass-transit plan 2050: the planned network's lines.

The only input is the plan's map file (a `map: true` input: the refresh
downloads the uploaded shapefile on every run and hands compute one row per
line segment, its attributes as strings plus `__geometry`, WGS84 GeoJSON).
Every number on the page comes from those rows; the datastore table of this
dataset is empty.

A line (LINE_ID) can be split into several segments, each with its own
target year (the Beit Shemesh line runs to 2050, its Begin extension to
2060). Counts of lines group by LINE_ID; the timeline works per segment.
"""
import json
import math

import pandas as pd

TYPE_HE = {"lrt": "רכבת קלה", "metro": "מטרו", "brt": "קו אוטובוס מהיר"}

# Hebrew names for the plan's English line names (lower-cased, without the
# "JLM " prefix some segments carry). An unknown name falls back to
# "<type> <LINE_ID>", so a new line still renders in Hebrew.
LINE_HE = {
    "red": "הקו האדום",
    "green": "הקו הירוק",
    "blue": "הקו הכחול",
    "yellow": "הקו הצהוב",
    "purple": "הקו הסגול",
    "orange": "הקו הכתום",
    "brown": "הקו החום",
    "pink": "הקו הוורוד",
    "light green": "הקו הירוק הבהיר",
    "light blue": "הקו התכלת",
    "beit shemesh": "קו ירושלים-בית שמש",
    "givat zeev": "קו גבעת זאב",
    "maale adumim": "קו מעלה אדומים",
    "x_1": "מטרו, קו 1",
    "x_2": "מטרו, קו 2",
    "x_extension1": "מטרו, שלוחה 1",
    "x_extension2": "מטרו, שלוחה 2",
}

TOP_LINES = 20           # bars on the per-line chart (rest → "אחר")
SEGMENT_ROWS = 40        # rows in the segment table
CHUNK_BYTES = 40_000     # each GeoJSON island stays well under 50KB
CHUNK_POINTS = 1_500     # a longer line is split into pieces of this many points


def _km(m):
    return f"{m / 1000:,.1f}"


def _pct(x):
    return f"{x * 100:.0f}%"


def _norm(name):
    n = " ".join(str(name).strip().lower().split())
    if n.startswith("jlm "):
        n = n[4:]
    return n.split(" - ")[0].strip()


def _haversine_m(coords):
    total = 0.0
    for (x1, y1, *_), (x2, y2, *_) in zip(coords, coords[1:]):
        p1, p2 = math.radians(y1), math.radians(y2)
        dp, dl = p2 - p1, math.radians(x2 - x1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * 6_371_000 * math.asin(math.sqrt(min(1.0, a)))
    return total


def _lines_of(geom):
    if not geom:
        return []
    if geom.get("type") == "LineString":
        return [geom.get("coordinates") or []]
    if geom.get("type") == "MultiLineString":
        return geom.get("coordinates") or []
    return []


def _prepare(df):
    rows = []
    for r in df.to_dict("records"):
        try:
            geom = json.loads(r.get("__geometry") or "null")
        except ValueError:
            geom = None
        parts = [p for p in _lines_of(geom) if len(p) >= 2]
        lid = pd.to_numeric(r.get("LINE_ID", ""), errors="coerce")
        year = pd.to_numeric(r.get("YEAR", ""), errors="coerce")
        shape = pd.to_numeric(str(r.get("Shape_Leng", "")).replace(",", ""), errors="coerce")
        if pd.isna(lid) or pd.isna(year) or not parts:
            continue
        # The layer's own length (ITM metres) when it has one, else measured.
        length = float(shape) if not pd.isna(shape) and shape > 0 else sum(map(_haversine_m, parts))
        ttype = str(r.get("TYPE", "")).strip()
        rows.append({
            "lid": int(lid), "year": int(year), "m": length,
            "type_key": ttype.lower(), "type_he": TYPE_HE.get(ttype.lower(), "אחר"),
            "raw_name": str(r.get("LINE_NAME", "")).strip(), "parts": parts,
        })
    # Total order, so shuffled input gives the same model.
    rows.sort(key=lambda s: (s["lid"], s["year"], -s["m"], s["raw_name"], s["type_key"]))
    return rows


def _name_lines(segs):
    """One Hebrew name per LINE_ID (from its longest segment), and a name per
    segment: the line's, plus ", מקטע k" for its second and later segments."""
    by_line = {}
    for s in segs:
        by_line.setdefault(s["lid"], []).append(s)
    names = {}
    for lid, ss in by_line.items():
        main = sorted(ss, key=lambda s: (-s["m"], s["year"], s["raw_name"]))
        names[lid] = LINE_HE.get(_norm(main[0]["raw_name"]), f"{main[0]['type_he']} {lid}")
        for k, s in enumerate(main, 1):
            s["name"] = names[lid] if k == 1 else f"{names[lid]}, מקטע {k}"
    return by_line, names


def _features(segs, type_order):
    """Map features as compact [props, geometry] pairs, chunked into islands
    under CHUNK_BYTES. A line longer than CHUNK_POINTS is split into pieces
    (sharing their end points), so no single feature can outgrow an island."""
    feats = []
    for i, s in enumerate(segs):
        pieces = []
        for part in s["parts"]:
            for a in range(0, len(part) - 1, CHUNK_POINTS):
                pieces.append([[round(x, 5), round(y, 5)] for x, y, *_ in part[a:a + CHUNK_POINTS + 1]])
        for p in pieces:
            feats.append([i, p])
    chunks, cur, size = [], [], 0
    for f in feats:
        n = len(json.dumps(f, separators=(",", ":")))
        if cur and size + n > CHUNK_BYTES:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += n
    if cur:
        chunks.append(cur)
    lons = [pt[0] for f in feats for pt in f[1]]
    lats = [pt[1] for f in feats for pt in f[1]]
    meta = [{"name": s["name"], "type": type_order.index(s["type_he"]), "year": s["year"],
             "km": _km(s["m"])} for s in segs]
    return {"chunks": chunks, "segs": meta, "types": type_order,
            "bounds": [[min(lats), min(lons)], [max(lats), max(lons)]]}


# ── insights ─────────────────────────────────────────────────────────────


def insight_size(n_lines, total_m, by_type):
    parts = [f"{_km(m)} ק״מ {t}" for t, m in by_type]
    if len(parts) > 1:
        mix = ", ".join(parts[:-1]) + " ו-" + parts[-1]
        return f"התוכנית כוללת {n_lines:,} קווים באורך כולל של {_km(total_m)} ק״מ: {mix}."
    return f"התוכנית כוללת {n_lines:,} קווים באורך כולל של {_km(total_m)} ק״מ."


def insight_half(cum, total_m):
    """The year by which half of the planned length is due, if it isn't the first."""
    if len(cum) < 2 or total_m <= 0:
        return None
    for y, m in cum:
        if m >= total_m / 2:
            if y == cum[0][0]:
                return None
            share = m / total_m
            return (f"מחצית מאורך הרשת מתוכננת עד {y}: עד אז {_km(m)} ק״מ, "
                    f"{_pct(share)} מהרשת כולה.")
    return None


def insight_longest(lines, total_m):
    if len(lines) < 2 or total_m <= 0:
        return None
    top, second = lines[0], lines[1]
    if top["m"] <= second["m"] * 1.1:
        return None  # no clear leader
    return (f"הקו הארוך ביותר הוא {top['name']} ({top['type']}), {_km(top['m'])} ק״מ, "
            f"{_pct(top['m'] / total_m)} מאורך הרשת.")


def insight_peak_year(per_year):
    if len(per_year) < 2:
        return None
    ranked = sorted(per_year, key=lambda r: (-r["m"], r["year"]))
    top, second = ranked[0], ranked[1]
    if top["m"] <= second["m"] * 1.2:
        return None
    return (f"שנת היעד {top['year']} מוסיפה לרשת יותר מכל שנה אחרת: {_km(top['m'])} ק״מ "
            f"ב-{top['n']:,} מקטעים.")


def insight_type_years(segs, type_he):
    ss = [s for s in segs if s["type_he"] == type_he]
    if not ss or len(ss) == len(segs):
        return None
    years = sorted({s["year"] for s in ss})
    m = sum(s["m"] for s in ss)
    when = f"כולם לשנת {years[0]}" if len(years) == 1 else f"בשנים {years[0]} עד {years[-1]}"
    return f"מקטעי ה{type_he} ({len(ss):,} מקטעים, {_km(m)} ק״מ) מתוכננים {when}."


def insight_latest(segs):
    last = max(s["year"] for s in segs)
    ss = [s for s in segs if s["year"] == last]
    if len(ss) != 1 or len({s["year"] for s in segs}) < 2:
        return None
    s = ss[0]
    return f"המקטע המאוחר ביותר בתוכנית הוא {s['name']}, {_km(s['m'])} ק״מ, עם שנת יעד {last}."


def compute(frames):
    segs = _prepare(frames["geo"])
    if not segs:
        raise ValueError("no usable line segments in the map file")
    by_line, names = _name_lines(segs)
    total_m = sum(s["m"] for s in segs)

    # Types, longest first (ties by name).
    type_m = {}
    for s in segs:
        type_m[s["type_he"]] = type_m.get(s["type_he"], 0.0) + s["m"]
    type_order = [t for t, _ in sorted(type_m.items(), key=lambda kv: (-kv[1], kv[0]))]
    type_lines = {t: len({s["lid"] for s in segs if s["type_he"] == t}) for t in type_order}
    by_type = [(t, type_m[t]) for t in type_order]

    lines = []
    for lid, ss in by_line.items():
        m = sum(s["m"] for s in ss)
        main = max(ss, key=lambda s: (s["m"], -s["year"]))
        lines.append({"lid": lid, "name": names[lid], "type": main["type_he"], "m": m,
                      "years": sorted({s["year"] for s in ss}), "n": len(ss)})
    lines.sort(key=lambda r: (-r["m"], r["name"], r["lid"]))

    years = sorted({s["year"] for s in segs})
    per_year = []
    for y in years:
        ys = [s for s in segs if s["year"] == y]
        per_year.append({"year": y, "m": sum(s["m"] for s in ys), "n": len(ys),
                         "by_type": {t: sum(s["m"] for s in ys if s["type_he"] == t) for t in type_order}})
    cum, run = [], 0.0
    for r in per_year:
        run += r["m"]
        cum.append((r["year"], run))

    n_lines = len(lines)
    y0, y1 = years[0], years[-1]
    span = f"{y0}–{y1}" if y0 != y1 else str(y0)

    # ── charts ──
    shown, rest = lines[:TOP_LINES], lines[TOP_LINES:]
    chart_lines = {
        "names": [r["name"] for r in shown] + (["אחר"] if rest else []),
        "km": [round(r["m"] / 1000, 1) for r in shown] + ([round(sum(r["m"] for r in rest) / 1000, 1)] if rest else []),
        "type": [type_order.index(r["type"]) for r in shown] + ([-1] if rest else []),
        "years": [" / ".join(str(y) for y in r["years"]) for r in shown] + ([""] if rest else []),
        "types": type_order,
    }
    chart_years = {
        "x": [str(y) for y in years],
        "series": [{"name": t, "data": [round(r["by_type"][t] / 1000, 1) for r in per_year]} for t in type_order],
        "cum": [round(m / 1000, 1) for _, m in cum],
        "n": [r["n"] for r in per_year],
    }
    chart_types = {
        "names": type_order,
        "km": [round(type_m[t] / 1000, 1) for t in type_order],
        "lines": [type_lines[t] for t in type_order],
    }
    timeline = sorted(segs, key=lambda s: (s["year"], -s["m"], s["name"]))
    chart_timeline = {
        "names": [s["name"] for s in timeline],
        "points": [[str(s["year"]), i, round(s["m"] / 1000, 1), type_order.index(s["type_he"])]
                   for i, s in enumerate(timeline)],
        "x": [str(y) for y in years],
        "types": type_order,
        "max_km": round(max(s["m"] for s in segs) / 1000, 1),
    }

    # ── tables ──
    t_lines = [{"name": r["name"], "type": r["type"], "km": _km(r["m"]),
                "years": " / ".join(str(y) for y in r["years"]), "n": f"{r['n']:,}"} for r in shown]
    if rest:
        t_lines.append({"name": f"אחר ({len(rest):,} קווים)", "type": "", "km": _km(sum(r["m"] for r in rest)),
                        "years": "", "n": f"{sum(r['n'] for r in rest):,}"})
    t_years = [{"year": str(r["year"]), "n": f"{r['n']:,}", "km": _km(r["m"]), "cum": _km(c)}
               for r, (_, c) in zip(per_year, cum)]
    t_types = [{"name": t, "km": _km(type_m[t]), "share": _pct(type_m[t] / total_m),
                "lines": f"{type_lines[t]:,}"} for t in type_order]
    seg_sorted = sorted(segs, key=lambda s: (s["year"], s["name"], -s["m"]))
    t_segments = [{"name": s["name"], "type": s["type_he"], "year": str(s["year"]), "km": _km(s["m"])}
                  for s in seg_sorted[:SEGMENT_ROWS]]

    rules = [
        ("size", insight_size(n_lines, total_m, by_type)),
        ("half", insight_half(cum, total_m)),
        ("longest", insight_longest(lines, total_m)),
        ("peak_year", insight_peak_year(per_year)),
    ]
    rules += [(f"type_{i}", insight_type_years(segs, t)) for i, t in enumerate(type_order[1:], 1)]
    rules.append(("latest", insight_latest(segs)))
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    kpis = {
        "total_km": {"value": round(total_m / 1000, 1), "display": _km(total_m), "tone": "brand"},
        "lines": {"value": n_lines, "display": f"{n_lines:,}", "tone": "brand"},
    }
    labels = {
        "kpi_total_km": "אורך הרשת המתוכננת (ק״מ)",
        "kpi_lines": "קווים בתוכנית",
        "kpi_span": "טווח שנות היעד",
    }
    kpi_order = ["total_km", "lines"]
    for i, t in enumerate(type_order[:2]):
        key = f"type_{i}"
        kpis[key] = {"value": round(type_m[t] / 1000, 1), "display": _km(type_m[t]), "tone": "info"}
        labels[f"kpi_{key}"] = f"ק״מ {t} ({type_lines[t]:,} קווים)"
        kpi_order.append(key)
    kpis["span"] = {"value": y1, "display": span, "tone": "brand"}
    kpi_order.append("span")

    mix = ", ".join(f"{t} {_km(m)} ק״מ" for t, m in by_type)
    labels.update({
        "lede": (f"שכבת המפה של התוכנית מתארת {n_lines:,} קווים ב-{len(segs):,} מקטעים, "
                 f"באורך כולל של {_km(total_m)} ק״מ ({mix}), עם שנות יעד בין {y0} ל-{y1}."),
        "map_lede": (f"תוואי {n_lines:,} הקווים על המפה, בצבע לפי סוג. לחיצה על קו מציגה את שמו, "
                     "שנת היעד שלו ואורכו."),
        "map_aria": f"מפת תוואי {n_lines:,} קווי הסעת ההמונים המתוכננים במטרופולין ירושלים",
        "lines_lede": (f"האורך המתוכנן של כל קו, מהארוך לקצר. {lines[0]['name']} מוביל עם "
                       f"{_km(lines[0]['m'])} ק״מ."),
        "lines_aria": f"אורך כל אחד מ-{n_lines:,} הקווים בקילומטרים",
        "years_lede": (f"כמה קילומטרים כל שנת יעד מוסיפה, לפי סוג, והרשת המצטברת: "
                       f"{_km(cum[0][1])} ק״מ עד {y0}, {_km(total_m)} ק״מ עד {y1}."),
        "years_aria": f"קילומטרים לפי שנת יעד ואורך הרשת המצטבר, {y0} עד {y1}",
        "types_lede": "חלוקת אורך הרשת ומספר הקווים לפי סוג המערכת.",
        "types_aria": "אורך הרשת לפי סוג מערכת",
        "timeline_lede": (f"כל מקטע לפי שנת היעד שלו; גודל הנקודה לפי אורך המקטע. "
                          f"{len(segs):,} מקטעים ב-{len(years):,} שנות יעד."),
        "timeline_aria": f"שנת היעד של כל אחד מ-{len(segs):,} המקטעים",
        "segments_lede": (f"{len(segs):,} המקטעים בשכבה"
                          + (f" ({SEGMENT_ROWS:,} הראשונים לפי שנת יעד)" if len(segs) > SEGMENT_ROWS else "")
                          + ", לפי שנת יעד."),
        "segments_caption": "מקטעי הרשת המתוכננת: סוג, שנת יעד ואורך",
    })

    summary = (f"מפת רשת הסעת ההמונים המתוכננת במטרופולין ירושלים ל-2050: {n_lines:,} קווי "
               f"{' ו'.join(type_order)}, {_km(total_m)} ק״מ, שנות יעד {y0} עד {y1}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "temporal_coverage": f"{y0}/{y1}",
            "spatial_coverage": "מטרופולין ירושלים",
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": {
            "map": _features(segs, type_order),
            "lines": chart_lines,
            "years": chart_years,
            "types": chart_types,
            "timeline": chart_timeline,
        },
        "tables": {"lines": t_lines, "years": t_years, "types": t_types, "segments": t_segments},
        "insights": insights,
        "labels": labels,
        "flags": {"types": len(type_order) > 1, "years": len(years) > 1},
    }
