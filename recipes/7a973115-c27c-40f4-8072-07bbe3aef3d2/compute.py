"""תחנות התחסנות כנגד חצבת — Ministry of Health list of measles vaccination
stations: one row per station, with its operator (health fund / municipality),
target population, city and a free-text opening-hours field.

The list is replaced wholesale as stations open or close and as hours change
(holiday notes, one-off dates), so the recipe treats it as a snapshot: no
time axis, every figure is "in the current list".

The opening-hours text is parsed into a weekly schedule per station
(Sunday–Saturday, minute intervals). One-off dated entries ("5.8 יום ג' …")
are not part of the weekly schedule and are counted separately; stations
whose text yields no weekly hours at all are disclosed.

Operator: when `owner` is empty the operator is inferred from the station
name's first word, using the operator that word maps to on the rows where
`owner` is filled (data-driven; disclosed on the page).

Cities are placed on the map and grouped into districts by a fixed
city-code table (approximate city centres). A city missing from the table
still counts everywhere else; it is left off the map and its district is
"אחר", both disclosed.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
TOP_CITIES = 15
TOP_OPS = 5
EVENING_MIN = 18 * 60          # "evening" = open at or after 18:00 on some day
SLOT = 30                      # heatmap slot, minutes
DAYS = "אבגדהוש"
DAY_NAMES = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
PROFILE_MIN = 3               # operators with fewer scheduled stations are left out of the profile
HOUR_BUCKETS = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, None)]
UNKNOWN_OP = "לא צוין"
OTHER = "אחר"
NAME_ALIASES = {"ככלית": "כללית"}

# city_code -> (district, lat, lng); approximate city centres.
CITY = {
    "3000": ("ירושלים", 31.778, 35.216),
    "2610": ("ירושלים", 31.746, 34.988),
    "1137": ("ירושלים", 31.803, 35.103),
    "4000": ("חיפה", 32.794, 34.990),
    "1247": ("חיפה", 32.462, 35.046),
    "6100": ("תל אביב", 32.084, 34.834),
    "2620": ("תל אביב", 32.058, 34.857),
    "7900": ("מרכז", 32.087, 34.887),
    "7000": ("מרכז", 31.952, 34.896),
    "229": ("מרכז", 32.060, 34.874),
    "1061": ("צפון", 32.713, 35.327),
    "6700": ("צפון", 32.795, 35.531),
    "8000": ("צפון", 32.965, 35.496),
    "2034": ("צפון", 32.981, 35.545),
    "2630": ("דרום", 31.609, 34.771),
    "1034": ("דרום", 31.731, 34.746),
    "70": ("דרום", 31.804, 34.655),
    "246": ("דרום", 31.421, 34.588),
    "3780": ("יהודה ושומרון", 31.697, 35.115),
    "3797": ("יהודה ושומרון", 31.932, 35.043),
    "3815": ("יהודה ושומרון", 31.879, 35.245),
    "3763": ("יהודה ושומרון", 31.870, 35.257),
    "3641": ("יהודה ושומרון", 32.053, 35.293),
    "3765": ("יהודה ושומרון", 32.067, 35.264),
    "3650": ("יהודה ושומרון", 31.655, 35.155),
    "3659": ("יהודה ושומרון", 31.896, 35.250),
    "3563": ("יהודה ושומרון", 31.645, 35.236),
    "3564": ("יהודה ושומרון", 31.957, 35.343),
    "3574": ("יהודה ושומרון", 31.943, 35.223),
    "3576": ("יהודה ושומרון", 31.825, 35.390),
    "3617": ("יהודה ושומרון", 31.957, 35.262),
    "3726": ("יהודה ושומרון", 31.637, 35.240),
    "3788": ("יהודה ושומרון", 31.940, 35.130),
}

# ── opening-hours parser ────────────────────────────────────────────────────
DATE3 = re.compile(r"(?<!\d)\d{1,2}\.\d{1,2}\.\d{2,4}(?!\d)")
DATE2 = re.compile(r"(?<!\d)\d{1,2}\.\d{1,2}(?=\s*יום)")
DOTTIME = re.compile(r"(?<!\d)(\d{1,2})\.(\d{2})(?!\d)")
TOK = re.compile(
    r"(?P<date>@DATE@)"
    r"|(?P<h1>\d{1,3}):(?P<m1>\d{2})\d*\s*-\s*(?:\d{1,2}\s*-\s*)?(?P<h2>\d{1,3}):(?P<m2>\d{2})\d*"
    r"|(?<![א-ת])(?:יום\s*)?(?P<day>[א-ת])\s*'?(?![א-ת])"
)


def _hm(h, m):
    h, m = int(h), int(m)
    if h > 24:
        h = h % 100            # "112:30" typo -> 12:30
    if h > 24 or m > 59:
        return None
    return h * 60 + m


def _merge(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def parse_hours(s):
    """-> ({day_letter: [(start_min, end_min), ...]}, has_dated_entries)."""
    t = (s.replace("\t", " ").replace("׳", "'").replace("’", "'")
         .replace("–", "-").replace("—", "-"))
    t = DATE2.sub(" @DATE@ ", DATE3.sub(" @DATE@ ", t))
    t = DOTTIME.sub(r"\1:\2", t)
    sched, group, has_range, dated, any_date = {}, [], False, False, False
    for mt in TOK.finditer(t):
        if mt.group("date"):
            group, has_range, dated, any_date = [], False, True, True
            continue
        d = mt.group("day")
        if d:
            if d not in DAYS:
                continue
            if has_range:
                group, has_range, dated = [], False, False
            group.append(d)
            continue
        a, b = _hm(mt.group("h1"), mt.group("m1")), _hm(mt.group("h2"), mt.group("m2"))
        has_range = True
        if dated or a is None or b is None or b <= a:
            continue
        for g in group:
            sched.setdefault(g, []).append((a, b))
    return {k: _merge(v) for k, v in sched.items()}, any_date


# ── formatting ──────────────────────────────────────────────────────────────
def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def pct_bare(v, digits=0):
    return f"{v * 100:.{digits}f}%"


def stations(k, prefix=""):
    """'ב-3 תחנות' / 'בתחנה אחת' style count phrase."""
    if k == 1:
        return f"{prefix}תחנה אחת"
    return f"{prefix}-{n(k)} תחנות" if prefix else f"{n(k)} תחנות"


def hhmm(m):
    return f"{m // 60}:{m % 60:02d}"


def bucket_label(lo, hi):
    if hi is None:
        return f"{lo} ומעלה"
    if lo == 0:
        return f"עד {hi}"
    return f"{lo} עד {hi}"


def _median(vals):
    v = sorted(vals)
    if not v:
        return None
    k = len(v)
    return v[k // 2] if k % 2 else (v[k // 2 - 1] + v[k // 2]) / 2


def _ranked(counts):
    """dict -> [(key, count)] by count desc, key asc (total order)."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


# ── preparation ─────────────────────────────────────────────────────────────
def short_op(o):
    """Chart label: drop the generic 'שירותי בריאות' / 'קופת חולים' words."""
    t = re.sub(r"\s+", " ", o.replace("שירותי בריאות", " ").replace("קופת חולים", " ")).strip()
    return t or o


def _first_word(name):
    w = re.split(r"[\s\-–]+", name.strip(), maxsplit=1)[0] if name.strip() else ""
    return NAME_ALIASES.get(w, w)


def _prepare(df):
    out = pd.DataFrame({
        "code": df["station_code"].str.strip(),
        "name": df["station_name"].str.strip(),
        "pop": df["population_name"].str.strip().replace("", "לא צוין"),
        "owner": df["owner"].str.strip(),
        "hours": df["availability_time"],
        "city": df["city"].str.strip().replace("", "לא צוין"),
        "city_code": df["city_code"].str.strip(),
    })
    out["word"] = out["name"].map(_first_word)
    filled = out[out["owner"] != ""]
    word_owner = {}
    for w, g in filled.groupby("word", sort=True):
        vc = g["owner"].value_counts()
        top = sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        word_owner[w] = top
    out["inferred"] = (out["owner"] == "") & out["word"].isin(word_owner)
    out["op"] = out["owner"]
    out.loc[out["inferred"], "op"] = out.loc[out["inferred"], "word"].map(word_owner)
    out["op"] = out["op"].replace("", UNKNOWN_OP)

    parsed = out["hours"].map(parse_hours)
    out["sched"] = parsed.map(lambda p: p[0])
    out["dated"] = parsed.map(lambda p: p[1])
    out["days_open"] = out["sched"].map(len)
    out["weekly_h"] = out["sched"].map(
        lambda s: sum(b - a for iv in s.values() for a, b in iv) / 60)
    out["evening"] = out["sched"].map(
        lambda s: any(b > EVENING_MIN for iv in s.values() for a, b in iv))
    out["friday"] = out["sched"].map(lambda s: "ו" in s)
    out["district"] = out["city_code"].map(lambda c: CITY[c][0] if c in CITY else OTHER)
    return out


# ── insights ────────────────────────────────────────────────────────────────
def insight_cities(city_rank, total):
    if len(city_rank) < 3 or total == 0:
        return None
    (c1, n1), (c2, n2) = city_rank[0], city_rank[1]
    share = (n1 + n2) / total
    if share < 0.25:
        return None
    singles = sum(1 for _, k in city_rank if k == 1)
    tail = f"; ב-{n(singles)} יישובים יש תחנה אחת בלבד" if singles >= 2 else ""
    return (f"{c1} ({n(n1)}) ו{c2} ({n(n2)}) מרכזות יחד {n(n1 + n2)} מתוך {n(total)} התחנות "
            f"({pct(share)}), מתוך {n(len(city_rank))} יישובים ברשימה{tail}.")


def insight_operator(op_rank, total):
    named = [(o, k) for o, k in op_rank if o != UNKNOWN_OP]
    if len(named) < 2 or total == 0:
        return None
    (o1, n1), (o2, n2) = named[0], named[1]
    if n1 / total < 0.3 or n1 - n2 < 5:
        return None
    return (f"{o1} מפעילה {n(n1)} תחנות ({pct(n1 / total)}), ואחריה {o2} עם {n(n2)} "
            f"({pct(n2 / total)}); שתיהן יחד מחזיקות {pct((n1 + n2) / total)} מהתחנות.")


def insight_friday(day_counts):
    week = [day_counts.get(d, 0) for d in "אבגדה"]
    avg = sum(week) / len(week)
    fri = day_counts.get("ו", 0)
    if avg <= 0 or fri / avg >= 0.85:
        return None
    return (f"ביום שישי פתוחות {n(fri)} תחנות בלבד, לעומת ממוצע של {n(round(avg))} "
            f"בימים ראשון עד חמישי — כ-{pct(fri / avg)} מהזמינות של אמצע השבוע.")


def insight_evening(df, scheduled):
    if scheduled == 0:
        return None
    ev = int(df["evening"].sum())
    share = ev / scheduled
    rows = []
    for op, g in df[df["days_open"] > 0].groupby("op", sort=True):
        if op == UNKNOWN_OP or len(g) < 10:
            continue
        rows.append((op, g["evening"].mean()))
    rows.sort(key=lambda r: (-r[1], r[0]))
    gap = ""
    if len(rows) >= 2 and rows[0][1] - rows[-1][1] >= 0.15:
        gap = (f" הפער בין הקופות גדול: ב{rows[0][0]} {pct(rows[0][1])} מהתחנות פתוחות "
               f"בערב, וב{rows[-1][0]} {pct(rows[-1][1])}.")
    return (f"{n(ev)} מתוך {n(scheduled)} התחנות שפורסמו להן שעות ({pct(share)}) פתוחות "
            f"אחרי {hhmm(EVENING_MIN)} לפחות ביום אחד בשבוע.{gap}")


def insight_peak(heat_counts, slots):
    best = None
    for di, d in enumerate(DAYS):
        for si, s in enumerate(slots):
            k = heat_counts.get((d, s), 0)
            if best is None or k > best[0]:
                best = (k, di, s)
    if not best or best[0] == 0:
        return None
    k, di, s = best
    eve = max((heat_counts.get((d, EVENING_MIN), 0) for d in "אבגדה"), default=0)
    return (f"שיא הזמינות ביום {DAY_NAMES[di]} בשעה {hhmm(s)}, עם {n(k)} תחנות פתוחות בו-זמנית; "
            f"בשעה {hhmm(EVENING_MIN)} פתוחות לכל היותר {n(eve)} תחנות ביום חול.")


def insight_district(dist_rank, dist_cities, total):
    if len(dist_rank) < 2 or total == 0:
        return None
    (d1, n1), (d2, n2) = dist_rank[0], dist_rank[1]
    if d1 == OTHER or n1 / total < 0.2:
        return None
    text = (f"מחוז {d1} מוביל עם {n(n1)} תחנות ({pct(n1 / total)}) ב-{n(dist_cities[d1])} יישובים, "
            f"ואחריו {d2 if d2 == OTHER else 'מחוז ' + d2} עם {n(n2)} ({pct(n2 / total)}).")
    spread = sorted(((dist_cities[d], d) for d, _ in dist_rank if d != OTHER), key=lambda r: (-r[0], r[1]))
    if spread and spread[0][1] != d1 and spread[0][0] >= 2 * dist_cities[d1]:
        k_c, d_s = spread[0]
        k_s = dict(dist_rank)[d_s]
        text += (f" הפיזור הרחב ביותר ב{d_s}: {n(k_s)} תחנות ב-{n(k_c)} יישובים שונים.")
    return text


def insight_adults(df, total):
    ad = df[df["pop"] == "מבוגרים"]
    k = len(ad)
    if k < 5 or k / total < 0.05:
        return None
    ops = _ranked(ad["op"].value_counts().to_dict())
    o1, c1 = ops[0]
    lead = f", {n(c1)} מהן של {o1}" if c1 / k >= 0.4 and o1 != UNKNOWN_OP else ""
    return (f"{n(k)} תחנות ({pct(k / total)}) מחסנות מבוגרים בלבד{lead}; "
            f"שאר התחנות מקבלות גם ילדים.")


def insight_inferred(df):
    k = int(df["inferred"].sum())
    if k == 0:
        return None
    ops = _ranked(df[df["inferred"]]["op"].value_counts().to_dict())
    parts = ", ".join(f"{o} ({n(c)})" for o, c in ops)
    return (f"ב-{n(k)} תחנות שדה הגוף המפעיל ריק; הגוף המפעיל זוהה לפי שם התחנה: {parts}.")


# ── compute ─────────────────────────────────────────────────────────────────
def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    sched_df = df[df["days_open"] > 0]
    scheduled = len(sched_df)
    unscheduled = total - scheduled
    dated = int(df["dated"].sum())

    # operators
    op_rank = _ranked(df["op"].value_counts().to_dict())
    ops_order = [o for o, _ in op_rank]
    top_ops = ops_order[:TOP_OPS]

    def op_bucket(o):
        return o if o in top_ops else OTHER
    df["opb"] = df["op"].map(op_bucket)
    opb_order = top_ops + ([OTHER] if (df["opb"] == OTHER).any() else [])
    sched_df = df[df["days_open"] > 0]

    pop_rank = _ranked(df["pop"].value_counts().to_dict())
    pops = [p for p, _ in pop_rank]
    op_pop = df.groupby(["op", "pop"]).size().to_dict()
    chart_owner = {
        "y": [short_op(o) for o in ops_order],
        "series": [{"name": p, "data": [int(op_pop.get((o, p), 0)) for o in ops_order]} for p in pops],
    }
    op_cities = df.groupby("op")["city"].nunique().to_dict()
    op_inf = df.groupby("op")["inferred"].sum().to_dict()
    t_owner = [{"op": o, "count": n(k), "share": pct_bare(k / total), "cities": n(op_cities[o]),
                "inferred": n(op_inf.get(o, 0))} for o, k in op_rank]

    # cities
    city_rank = _ranked(df["city"].value_counts().to_dict())
    top_c = [c for c, _ in city_rank[:TOP_CITIES]]
    rest_c = city_rank[TOP_CITIES:]
    city_op = df.groupby(["city", "opb"]).size().to_dict()
    x_c = top_c + ([f"{OTHER} ({n(len(rest_c))} יישובים)"] if rest_c else [])
    rest_names = {c for c, _ in rest_c}
    series_c = []
    for o in opb_order:
        vals = [int(city_op.get((c, o), 0)) for c in top_c]
        if rest_c:
            vals.append(int(sum(v for (c, oo), v in city_op.items() if oo == o and c in rest_names)))
        series_c.append({"name": short_op(o), "data": vals})
    city_main_op = {}
    for c, g in df.groupby("city", sort=True):
        r = _ranked(g["op"].value_counts().to_dict())
        city_main_op[c] = r[0][0]
    t_city = [{"city": c, "count": n(k), "share": pct_bare(k / total), "op": city_main_op[c]}
              for c, k in city_rank[:TOP_CITIES]]
    if rest_c:
        t_city.append({"city": x_c[-1], "count": n(sum(k for _, k in rest_c)),
                       "share": pct_bare(sum(k for _, k in rest_c) / total), "op": "—"})

    # districts
    dist_rank = _ranked(df["district"].value_counts().to_dict())
    dist_cities = df.groupby("district")["city"].nunique().to_dict()
    dist_op = df.groupby(["district", "opb"]).size().to_dict()
    chart_district = {
        "y": [d for d, _ in dist_rank],
        "series": [{"name": short_op(o), "data": [int(dist_op.get((d, o), 0)) for d, _ in dist_rank]}
                   for o in opb_order],
    }
    t_district = [{"district": d, "count": n(k), "share": pct_bare(k / total),
                   "cities": n(dist_cities[d])} for d, k in dist_rank]

    # map points (per city)
    pts = []
    for c, g in df.groupby(["city_code", "city"], sort=True):
        code, name = c
        if code not in CITY:
            continue
        _, la, ln = CITY[code]
        pts.append([la, ln, int(len(g)), name, CITY[code][0], city_main_op[name]])
    pts.sort(key=lambda p: (-p[2], p[3]))
    on_map = sum(p[2] for p in pts)
    off_map = total - on_map

    # weekday availability
    day_counts = {d: int(sched_df["sched"].map(lambda s, d=d: d in s).sum()) for d in DAYS}
    days_used = [d for d in DAYS if day_counts[d] > 0 or d != "ש"]
    day_op = {}
    for _, r in sched_df[["sched", "opb"]].iterrows():
        for d in r["sched"]:
            day_op[(d, r["opb"])] = day_op.get((d, r["opb"]), 0) + 1
    chart_week = {
        "x": [DAY_NAMES[DAYS.index(d)] for d in days_used],
        "series": [{"name": short_op(o), "data": [int(day_op.get((d, o), 0)) for d in days_used]} for o in opb_order],
    }
    t_week = [{"day": DAY_NAMES[DAYS.index(d)], "count": n(day_counts[d]),
               "share": pct_bare(day_counts[d] / scheduled) if scheduled else "—"} for d in days_used]

    # heatmap: stations open per day × half-hour slot
    all_iv = [(a, b) for s in sched_df["sched"] for iv in s.values() for a, b in iv]
    if all_iv:
        lo = (min(a for a, _ in all_iv) // 60) * 60
        hi = -(-max(b for _, b in all_iv) // 60) * 60
    else:
        lo, hi = 8 * 60, 20 * 60
    slots = list(range(lo, hi, SLOT))
    heat_counts = {}
    for s in sched_df["sched"]:
        for d, iv in s.items():
            for t in slots:
                if any(a <= t < b for a, b in iv):
                    heat_counts[(d, t)] = heat_counts.get((d, t), 0) + 1
    cells = []
    for di, d in enumerate(days_used):
        for si, t in enumerate(slots):
            cells.append([si, di, int(heat_counts.get((d, t), 0))])
    chart_heat = {"x": [hhmm(t) for t in slots], "y": [DAY_NAMES[DAYS.index(d)] for d in days_used],
                  "cells": cells, "max": max([c[2] for c in cells] + [1])}
    t_heat = [{"hour": hhmm(t), "cells": [n(heat_counts.get((d, t), 0)) for d in days_used]}
              for t in slots if t % 60 == 0]

    # weekly hours distribution + days per week
    wh = sched_df["weekly_h"]
    hb = []
    for a, b in HOUR_BUCKETS:
        m = wh >= a
        if b is not None:
            m &= wh < b
        hb.append((bucket_label(a, b), int(m.sum())))
    chart_hours = {"x": [l for l, _ in hb], "y": [k for _, k in hb]}
    t_hours = [{"bucket": l, "count": n(k), "share": pct_bare(k / scheduled) if scheduled else "—"} for l, k in hb]
    dcount = sched_df["days_open"].value_counts().to_dict()
    dmax = max(dcount) if dcount else 0
    chart_days = {"x": [str(i) for i in range(1, dmax + 1)], "y": [int(dcount.get(i, 0)) for i in range(1, dmax + 1)]}
    t_days = [{"days": str(i), "count": n(dcount.get(i, 0))} for i in range(1, dmax + 1)]

    # operator profile
    prof = []
    for o in ops_order:
        g = sched_df[sched_df["op"] == o]
        if len(g) < PROFILE_MIN:
            continue
        prof.append({
            "op": o, "k": len(g),
            "evening": g["evening"].mean(), "friday": g["friday"].mean(),
            "five": (g["days_open"] >= 5).mean(),
            "median_h": _median(g["weekly_h"].tolist()),
        })
    prof_dropped = len(prof) < len([o for o in ops_order if (sched_df["op"] == o).any()])
    chart_profile = {
        "y": [short_op(p["op"]) for p in prof],
        "series": [
            {"name": f"פתוחות אחרי {hhmm(EVENING_MIN)}", "data": [round(p["evening"] * 100, 1) for p in prof]},
            {"name": "פתוחות בשישי", "data": [round(p["friday"] * 100, 1) for p in prof]},
            {"name": "חמישה ימים ומעלה", "data": [round(p["five"] * 100, 1) for p in prof]},
        ],
    }
    t_profile = [{"op": p["op"], "k": n(p["k"]), "median_h": f"{p['median_h']:.1f}",
                  "evening": pct_bare(p["evening"]), "friday": pct_bare(p["friday"]),
                  "five": pct_bare(p["five"])} for p in prof]

    med_h = _median(wh.tolist())
    ev_share = float(sched_df["evening"].mean()) if scheduled else 0.0
    fri_share = float(sched_df["friday"].mean()) if scheduled else 0.0
    n_cities = len(city_rank)
    named_ops = [o for o in ops_order if o != UNKNOWN_OP]

    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "cities": {"value": n_cities, "display": n(n_cities), "tone": "brand"},
        "ops": {"value": len(named_ops), "display": n(len(named_ops)), "tone": "brand"},
        "median_h": {"value": med_h, "display": f"{med_h:.1f}" if med_h is not None else "—", "tone": "info"},
        "evening": {"value": ev_share, "display": pct_bare(ev_share),
                    "tone": "ok" if ev_share >= 0.5 else "warn"},
        "friday": {"value": fri_share, "display": pct_bare(fri_share),
                   "tone": "ok" if fri_share >= 0.5 else "warn"},
    }

    rules = [
        ("cities", insight_cities(city_rank, total)),
        ("operator", insight_operator(op_rank, total)),
        ("district", insight_district(dist_rank, dist_cities, total)),
        ("friday", insight_friday(day_counts)),
        ("evening", insight_evening(df, scheduled)),
        ("peak", insight_peak(heat_counts, slots)),
        ("adults", insight_adults(df, total)),
        ("inferred", insight_inferred(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    (c1, k1) = city_rank[0]
    lead_op = named_ops[0] if named_ops else UNKNOWN_OP
    summary = (f"{n(total)} תחנות התחסנות נגד חצבת ב-{n(n_cities)} יישובים; {c1} מובילה עם {n(k1)} תחנות, "
               f"ו{lead_op} היא הגוף המפעיל הגדול. {pct(ev_share)} מהתחנות פתוחות גם בערב "
               f"ו-{pct(fri_share)} פתוחות בשישי.")

    off_note = (f" {stations(off_map)} ביישובים שאין להם מיקום בטבלת היישובים אינן מוצגות במפה."
                if off_map else "")
    unsched_note = (f" מחוץ לחישוב: {stations(unscheduled)} ללא שעות שבועיות (רק תאריכים בודדים)."
                    if unscheduled else "")
    dated_note = (f" {stations(dated, 'ב')} מופיעים גם מועדים חד-פעמיים לפי תאריך; הם אינם נספרים כאן."
                  if dated else "")
    inferred_k = int(df["inferred"].sum())
    inf_note = (f" {stations(inferred_k, 'ב')} הגוף המפעיל זוהה לפי שם התחנה, כי השדה ריק."
                if inferred_k else "")

    hb_top = max(hb, key=lambda r: r[1]) if hb else ("—", 0)
    labels = {
        "lede": (f"רשימת משרד הבריאות של {n(total)} תחנות שבהן אפשר להתחסן נגד חצבת, ב-{n(n_cities)} יישובים "
                 f"ובהפעלת {n(len(named_ops))} גופים. לכל תחנה מופיעים הגוף המפעיל, אוכלוסיית היעד, הכתובת "
                 f"ושעות הפעילות; את השעות פענחנו ללוח שבועי כדי לבדוק מתי ואיפה אפשר להגיע."),
        "total_kpi": "תחנות התחסנות",
        "cities_kpi": "יישובים",
        "ops_kpi": "גופים מפעילים",
        "median_h_kpi": "חציון שעות פתיחה בשבוע",
        "evening_kpi": f"פתוחות אחרי {hhmm(EVENING_MIN)} לפחות פעם בשבוע",
        "friday_kpi": "פתוחות ביום שישי",
        "owner_note": (f"{op_rank[0][0]} מפעילה {n(op_rank[0][1])} תחנות; הצבע מראה את אוכלוסיית היעד."
                       f"{inf_note}"),
        "owner_aria": f"תרשים עמודות אופקי: מספר התחנות לפי גוף מפעיל ואוכלוסיית יעד, {n(len(ops_order))} גופים",
        "owner_caption": "תחנות ההתחסנות לפי גוף מפעיל",
        "city_note": (f"{n(len(top_c))} היישובים עם הכי הרבה תחנות"
                      + (f", ויתר {n(len(rest_c))} היישובים מקובצים יחד" if rest_c else "")
                      + "; הצבע מראה את הגוף המפעיל."),
        "city_aria": f"תרשים עמודות מוערם: תחנות לפי יישוב וגוף מפעיל, {n(len(x_c))} עמודות",
        "city_caption": "תחנות ההתחסנות לפי יישוב",
        "district_note": (f"שיוך היישובים למחוזות; מחוז {dist_rank[0][0]} מוביל עם {n(dist_rank[0][1])} תחנות."
                          if dist_rank[0][0] != OTHER else "שיוך היישובים למחוזות."),
        "district_aria": f"תרשים עמודות אופקי: תחנות לפי מחוז וגוף מפעיל, {n(len(dist_rank))} מחוזות",
        "district_caption": "תחנות ההתחסנות לפי מחוז",
        "map_note": (f"עיגול לכל יישוב, בגודל לפי מספר התחנות בו (מיקום משוער של מרכז היישוב). "
                     f"לחיצה על עיגול מציגה את מספר התחנות והגוף המפעיל העיקרי.{off_note}"),
        "map_aria": f"מפה: {n(len(pts))} יישובים עם תחנות התחסנות נגד חצבת",
        "week_note": (f"כמה תחנות פתוחות בכל יום בשבוע, לפי הגוף המפעיל.{unsched_note}"),
        "week_aria": f"תרשים עמודות מוערם: תחנות פתוחות לפי יום בשבוע, {n(len(days_used))} ימים",
        "week_caption": "תחנות פתוחות לפי יום בשבוע",
        "heat_note": (f"מספר התחנות הפתוחות בכל חצי שעה, לפי יום. חושב משעות הפעילות שפורסמו לכל תחנה."
                      f"{dated_note}{unsched_note}"),
        "heat_aria": f"מפת חום: תחנות פתוחות לפי יום ושעה, {n(len(slots))} משבצות זמן",
        "heat_caption": "תחנות פתוחות לפי שעה עגולה ויום",
        "hours_note": (f"סך שעות הפתיחה בשבוע לכל תחנה; הקבוצה הגדולה: {hb_top[0]} שעות "
                       f"({n(hb_top[1])} תחנות)."),
        "hours_aria": f"תרשים עמודות: התפלגות שעות הפתיחה השבועיות, {n(len(hb))} קבוצות",
        "hours_caption": "תחנות לפי שעות פתיחה בשבוע",
        "days_note": (f"בכמה ימים בשבוע פתוחה כל תחנה; {n(dcount.get(dmax, 0))} תחנות פתוחות {n(dmax)} ימים."
                      if dmax else "בכמה ימים בשבוע פתוחה כל תחנה."),
        "days_aria": f"תרשים עמודות: תחנות לפי מספר ימי פעילות בשבוע, עד {n(dmax)} ימים",
        "days_caption": "תחנות לפי מספר ימי פעילות בשבוע",
        "profile_note": ("לכל גוף מפעיל: איזה חלק מהתחנות שלו פתוח בערב, בשישי, וחמישה ימים בשבוע או יותר."
                         + (f" גופים עם פחות מ-{n(PROFILE_MIN)} תחנות אינם מוצגים." if prof_dropped else "")),
        "profile_aria": f"תרשים עמודות אופקי: מאפייני זמינות לפי גוף מפעיל, {n(len(prof))} גופים",
        "profile_caption": "זמינות התחנות לפי גוף מפעיל",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["חצבת", "חיסונים", "תחנות התחסנות", "קופות חולים", "שעות פעילות"],
            "related_ids": ["0b940b2a-b465-44f6-98d5-71a7fbae2944", "7a04fc3b-6e20-47a1-970c-3f20f7fcfd3f"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "owner": chart_owner, "city": {"x": x_c, "series": series_c},
            "district": chart_district, "map": {"points": pts},
            "week": chart_week, "heat": chart_heat, "hours": chart_hours,
            "days": chart_days, "profile": chart_profile,
        },
        "flags": {"map": len(pts) > 0},
        "insights": insights,
        "labels": labels,
        "tables": {
            "owner": t_owner, "city": t_city, "district": t_district, "week": t_week,
            "heat_days": [DAY_NAMES[DAYS.index(d)] for d in days_used], "heat": t_heat,
            "hours": t_hours, "days": t_days, "profile": t_profile,
        },
    }
