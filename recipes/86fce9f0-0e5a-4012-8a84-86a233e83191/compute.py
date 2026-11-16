"""תחנות רכבת קלה (Ministry of Transport GIS layer): existing and planned
light-rail stations across Israel.

One row per station point: its line(s) (LINE, several joined by "_" at an
interchange; "<colour> מקוקו" is a dashed variant of a line), vertical type
(TYPE: surface / underground / elevated), STATUS (existing / planned, as of
the record's last update), the month the record was last updated
(YEARMONTH, YYYYMM), the planning company (COMP), the metropolitan area
(MTR_AREA), the station name and its ITM coordinates (X, Y, metres).

Two inputs:
  - `main`: the datastore table. Every KPI, chart, table and insight reads it.
  - `geo`: the uploaded shapefile (`map: true`), the same points as WGS84,
    for the map only (the map shows points, not merged stations).

Conventions:
  - A line is (metro, line name): "אדום" in Jerusalem and in Tel Aviv are
    different lines. The line chart shows each name as the data spells it
    (a dashed variant on its own); counts of distinct lines and of lines per
    station fold a dashed variant into its full line.
  - A station is a cluster of points in one metro. Two points join when they
    are at most LINK_M apart and serve no line in common (a transfer between
    lines drawn as separate points, sometimes under different names), or
    when their names match after dropping spaces and punctuation and they
    are at most SAME_NAME_M apart (alternative locations of one station).
    Joining is transitive (union-find), so the result doesn't depend on row
    order. Every station count on the page uses these stations.
  - A station's status is "קיימת" when any of its points is; its type is the
    points' common type, or MIXED when they differ.
  - Station spacing is the distance from each station to the nearest other
    station on the same line (ITM is metric), median per line, without the
    points marked tentative in their name.

Insight rules each return a Hebrew sentence or None when the premise does
not hold. Every number comes from the data.
"""
import json
import math
import re

import pandas as pd
from govlib import fmt, frame, geo

UNKNOWN = "לא צוין"
EXISTING = "קיימת"
PLANNED = "מתוכננת"
STATUS_ORDER = [EXISTING, PLANNED]
UNDERGROUND = "תחתית"
MIXED = "משולבת"
TYPE_ORDER = ["עילית", "תחתית", "מוגבהת", MIXED]
TYPE_LABEL = {"עילית": "עילית (במפלס הרחוב)", "תחתית": "תחתית (תת-קרקעית)", "מוגבהת": "מוגבהת",
              MIXED: "משולבת (כמה מפלסים)"}
DASHED = " מקוקו"
METRO_PREFIX = "מטרופולין "
TENTATIVE = "טנטטיבי"

LINK_M = 200                  # points of different lines this close are one station
SAME_NAME_M = 500             # points with the same name this close are one station

# Line colours as the lines are named; an unknown name gets a palette colour.
LINE_COLORS = {
    "אדום": "#d62828", "ירוק": "#2a8c3c", "ירוק בהיר": "#7cb342", "סגול": "#7b2cbf",
    "כחול": "#1d4ed8", "תכלת": "#0ea5e9", "ורוד": "#db2777", "צהוב": "#d4a106",
    "חום": "#8b5a2b", "חום דרומי": "#b7793f", "נופית": "#0b3668",
}
# Lines named after a colour read "הקו האדום"; others (נופית) read "קו נופית".
COLOR_NAMES = set(LINE_COLORS) - {"נופית"}
FALLBACK = ["#0068f5", "#0b3668", "#6c9fd8", "#5b6b7f", "#2f7f9e"]
OTHER_COLOR = "#9aa5b1"
PLURAL = {"קיימת": "קיימות", "מתוכננת": "מתוכננות"}
STATUS_COLORS = {EXISTING: "#198754", PLANNED: "#0068f5"}

MIN_SPACING_STATIONS = 4      # a line needs this many stations for a spacing figure
SPACING_INSIGHT_MIN = 6       # ... and this many for the spacing insight
TOP_LINES = 12                # bars in the line and spacing charts (mobile)
TOP_XFER = 10
TIE_NOTE = " (כולל כל המסלולים שבתיקו במקום האחרון)"
TOP_XFER_MAX = 25             # ties at the cutoff are kept up to this many rows

_NAME_JUNK = re.compile(r"[\s\-‐-―־'\"׳״()_.,]+")


def _metro_short(m):
    return m.removeprefix(METRO_PREFIX)


def _base(line):
    return line.removesuffix(DASHED)


def _line_he(line, in_=False):
    """'הקו האדום' / 'בקו האדום' for a colour-named line, 'קו נופית' /
    'בקו נופית' for any other name."""
    if _base(line) in COLOR_NAMES:
        return f"בקו ה{line}" if in_ else f"הקו ה{line}"
    return f"בקו {line}" if in_ else f"קו {line}"


def _order(values, known):
    present = sorted(set(values))
    return [v for v in known if v in present] + [v for v in present if v not in known]


def _color(name, i):
    return LINE_COLORS.get(_base(name), FALLBACK[i % len(FALLBACK)])


def _norm_name(s):
    return _NAME_JUNK.sub("", s)


def _ym(v):
    n = pd.to_numeric(str(v).strip(), errors="coerce")
    if pd.isna(n):
        return None
    y, m = divmod(int(n), 100)
    if not (1990 <= y <= 2100 and 1 <= m <= 12):
        return None
    return y * 100 + m


def _ym_he(v):
    y, m = divmod(int(v), 100)
    return fmt.month_he(pd.Timestamp(year=y, month=m, day=1))


def _cut(rows, n):
    """The first `n` rows of a list sorted by r["n"] descending, plus every
    row tied with the n-th (a soft cap); all rows when at most one is left."""
    if len(rows) <= n + 1:
        return rows
    k = rows[n - 1]["n"]
    out = [r for r in rows if r["n"] >= k]
    return rows if len(rows) - len(out) <= 1 else out


def _prep(df):
    out = pd.DataFrame({
        "name": frame.clean_series(df["STAT_NAME"]),
        "line": frame.clean_series(df["LINE"]),
        "type": frame.clean_series(df["TYPE"]),
        "status": frame.clean_series(df["STATUS"]),
        "metro": frame.clean_series(df["MTR_AREA"]),
        "comp": frame.clean_series(df["COMP"]),
        "x": frame.num(df["X"]),
        "y": frame.num(df["Y"]),
        "ym": [_ym(v) for v in df["YEARMONTH"]],
    })
    for c in ("name", "line", "type", "status", "metro", "comp"):
        out[c] = out[c].replace("", UNKNOWN)
    out = out.sort_values(["metro", "name", "line", "status", "type", "x", "y"],
                          kind="stable", na_position="last").reset_index(drop=True)
    out["lines"] = [sorted({p.strip() for p in s.split("_") if p.strip()}) if s != UNKNOWN else []
                    for s in out["line"]]
    out["bases"] = [frozenset(_base(ln) for ln in ls) for ls in out["lines"]]
    out["nname"] = [_norm_name(s) for s in out["name"]]
    out["tentative"] = out["name"].str.contains(TENTATIVE, regex=False)
    return out


# ---------------------------------------------------------------- stations

def _cluster(df):
    """Union-find over the points of each metro; returns a station id per row."""
    parent = list(range(len(df)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    cell = float(SAME_NAME_M)
    grid = {}
    recs = df[["metro", "name", "x", "y", "bases", "nname"]].to_dict("records")
    for i, r in enumerate(recs):
        if pd.isna(r["x"]) or pd.isna(r["y"]):
            continue
        grid.setdefault((r["metro"], math.floor(r["x"] / cell), math.floor(r["y"] / cell)), []).append(i)
    same, near_pairs = [], []
    for (metro, cx, cy), members in sorted(grid.items()):
        near = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grid.get((metro, cx + dx, cy + dy), [])]
        for i in members:
            a = recs[i]
            for j in near:
                if j <= i:
                    continue
                b = recs[j]
                d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                named = a["nname"] and a["name"] != UNKNOWN and b["name"] != UNKNOWN
                if d <= SAME_NAME_M and named and a["nname"] == b["nname"]:
                    same.append((i, j))
                elif d <= LINK_M and a["bases"] and b["bases"]:
                    near_pairs.append((round(d, 3), i, j))
    # Same-name points first; then proximity links, nearest first, and only
    # while the two clusters (not just the two points) share no line, so a
    # chain can't fuse two stations of one line through a third point.
    for i, j in sorted(same):
        union(i, j)
    lines = {}
    for k in range(len(recs)):
        lines.setdefault(find(k), set()).update(recs[k]["bases"])
    for _d, i, j in sorted(near_pairs):
        ri, rj = find(i), find(j)
        if ri == rj or lines[ri] & lines[rj]:
            continue
        union(ri, rj)
        lines[find(ri)] = lines[ri] | lines[rj]
    return [find(i) for i in range(len(df))]


def _station_name(names):
    groups = {}
    for n in names:
        groups.setdefault(_norm_name(n), set()).add(n)
    picks = sorted(min(g, key=lambda s: (-len(s), s)) for g in groups.values())
    return " / ".join(picks)


def _stations(df):
    df = df.assign(sid=_cluster(df))
    out = []
    for _sid, g in df.groupby("sid", sort=True):
        statuses = _order(g["status"], STATUS_ORDER)
        types = sorted(set(g["type"]) - {UNKNOWN}) or [UNKNOWN]
        raw = sorted({ln for ls in g["lines"] for ln in ls})
        out.append({
            "metro": g["metro"].iloc[0],
            "name": _station_name(list(g["name"])),
            "status": statuses[0],
            "type": types[0] if len(types) == 1 else MIXED,
            "under": bool((g["type"] == UNDERGROUND).any()),
            "raw": raw,
            "lines": sorted({_base(ln) for ln in raw}),
            "rows": g,
            "points": len(g),
        })
    out.sort(key=lambda s: (s["metro"], s["name"], s["raw"]))
    for idx, s in enumerate(out):
        s["k"] = len(s["lines"])
        s["sid"] = idx
    return out


def _line_status(rows, token, mode):
    """A station's status on one line, read only from the points that serve
    that line alone. STATUS is recorded per point, so a point shared by
    several lines says nothing about any one of them: None when the line
    passes the station only at shared points.

    mode "route": `token` is a route as spelled (a dashed variant is its own
    route), matched against points whose LINE lists it and nothing but
    routes of the same line ("אדום_אדום מקוקו" belongs to both red routes).
    mode "line": `token` is a folded line, matched against points whose
    lines all fold to it (e.g. "אדום_אדום מקוקו" serves only the red line)."""
    if mode == "route":
        b = _base(token)
        own = rows[[token in ls and all(_base(x) == b for x in ls) for ls in rows["lines"]]]
    else:
        own = rows[[b == frozenset({token}) for b in rows["bases"]]]
    if own.empty:
        return None
    return _order(own["status"], STATUS_ORDER)[0]


def _nn_median(pts):
    pts = sorted(set(pts))
    if len(pts) < MIN_SPACING_STATIONS:
        return None
    d = [min(math.hypot(x - a, y - b) for j, (a, b) in enumerate(pts) if j != i)
         for i, (x, y) in enumerate(pts)]
    return float(pd.Series(d).median())


def _lines_table(stations):
    acc = {}
    for s in stations:
        for ln in s["raw"]:
            r = acc.setdefault((s["metro"], ln), {"metro": s["metro"], "line": ln, "n": 0, "existing": 0,
                                                   "planned": 0, "shared": 0, "other": 0, "under": 0, "pts": [],
                                                   "sids": set(), "exist_sids": set()})
            on = s["rows"][[ln in ls for ls in s["rows"]["lines"]]]
            st = _line_status(s["rows"], ln, "route")
            r["n"] += 1
            r["sids"].add(s["sid"])
            r["existing"] += st == EXISTING
            r["planned"] += st == PLANNED
            r["shared"] += st is None
            r["other"] += st not in (EXISTING, PLANNED, None)
            if st == EXISTING:
                r["exist_sids"].add(s["sid"])
            r["under"] += bool((on["type"] == UNDERGROUND).any())
            on = on[~on["tentative"]].dropna(subset=["x", "y"])
            if len(on):
                r["pts"].append((round(float(on["x"].mean()), 1), round(float(on["y"].mean()), 1)))
    rows = sorted(acc.values(), key=lambda r: (-r["n"], r["metro"], r["line"]))
    for i, r in enumerate(rows):
        pts = r.pop("pts")
        r["measured"] = len(set(pts))
        r["spacing"] = _nn_median(pts)
        r["label"] = f"{r['line']} ({_metro_short(r['metro'])})"
        r["color"] = _color(r["line"], i)
        r["dashed"] = r["line"].endswith(DASHED)
    return rows


def _map_section(gdf):
    rows = []
    for r in gdf.to_dict("records"):
        try:
            g = json.loads(r.get("__geometry") or "null")
        except ValueError:
            g = None
        if not g or g.get("type") != "Point":
            continue
        c = g.get("coordinates") or []
        if len(c) < 2:
            continue
        rows.append({
            "name": frame.clean(r.get("STAT_NAME")) or UNKNOWN,
            "line": frame.clean(r.get("LINE")).replace("_", ", ") or UNKNOWN,
            "status": frame.clean(r.get("STATUS")) or UNKNOWN,
            "type": frame.clean(r.get("TYPE")) or UNKNOWN,
            "metro": frame.clean(r.get("MTR_AREA")) or UNKNOWN,
            "lon": float(c[0]), "lat": float(c[1]),
        })
    if not rows:
        return None
    rows.sort(key=lambda x: (x["metro"], x["name"], x["line"], x["status"], x["type"], x["lon"], x["lat"]))
    statuses = _order([x["status"] for x in rows], STATUS_ORDER)
    types = _order([x["type"] for x in rows], TYPE_ORDER)
    metros = sorted({x["metro"] for x in rows})
    org = geo.origin([x["lon"] for x in rows], [x["lat"] for x in rows])
    feats = []
    for x in rows:
        pt = geo.encode([[(x["lon"], x["lat"])]], org, ring=False)[0]
        feats.append([statuses.index(x["status"]), types.index(x["type"]),
                      metros.index(x["metro"]), x["name"], x["line"], pt])

    def bounds(sub):
        return [[round(min(s["lat"] for s in sub), 5), round(min(s["lon"] for s in sub), 5)],
                [round(max(s["lat"] for s in sub), 5), round(max(s["lon"] for s in sub), 5)]]

    by_metro = {m: [x for x in rows if x["metro"] == m] for m in metros}
    zoom = [{"name": _metro_short(m), "bounds": bounds(by_metro[m])}
            for m in sorted(metros, key=lambda k: (-len(by_metro[k]), k))]
    legend = [{"name": f"מסומנת כ{s}" if s in STATUS_ORDER else s,
               "color": STATUS_COLORS.get(s, FALLBACK[i % len(FALLBACK)]),
               "n": f"{sum(1 for x in rows if x['status'] == s):,}"} for i, s in enumerate(statuses)]
    return {
        "chunks": geo.pack(feats), "origin": org, "scale": geo.SCALE,
        "statuses": statuses, "colors": [lg["color"] for lg in legend],
        "types": [TYPE_LABEL.get(t, t) for t in types],
        "under": types.index(UNDERGROUND) if UNDERGROUND in types else -1,
        "metros": metros, "zoom": zoom if len(zoom) > 1 else [],
        "legend": legend, "bounds": bounds(rows), "n": len(rows),
    }


# ---------------------------------------------------------------- insights

def _update_span(df):
    yms = df["ym"].dropna()
    if not len(yms):
        return None
    lo, hi = int(yms.min()), int(yms.max())
    return _ym_he(lo) if lo == hi else f"בין {_ym_he(lo)} ל{_ym_he(hi)}"


def ins_status(stations, df):
    n = len(stations)
    e = sum(s["status"] == EXISTING for s in stations)
    p = sum(s["status"] == PLANNED for s in stations)
    if n == 0 or p == 0:
        return None
    span = _update_span(df)
    tail = (f" הסטטוס הוא כפי שנרשם בעדכון האחרון של הרשומות ({span}), "
            "ולכן תחנות שנפתחו מאז עשויות להופיע עדיין כמתוכננות.") if span else ""
    o = n - e - p
    other = f" {o:,} תחנות נוספות מסומנות בסטטוס אחר." if o > 1 else (" תחנה אחת מסומנת בסטטוס אחר." if o == 1 else "")
    if p == n:
        return f"כל {n:,} התחנות במאגר מסומנות כמתוכננות; אף תחנה אינה מסומנת כקיימת." + tail
    if p / n > 0.5:
        if e == 0:
            body = "ואף תחנה אינה מסומנת כקיימת."
        elif e == 1:
            body = "ותחנה אחת בלבד מסומנת כקיימת."
        else:
            body = f"לעומת {e:,} שמסומנות כקיימות."
        return (f"רוב התחנות במאגר מסומנות כמתוכננות: {p:,} מתוך {n:,} ({fmt.pct(p / n)}), "
                + body + other + tail)
    if e == 0:
        return None
    return (f"{e:,} מתוך {n:,} התחנות במאגר ({fmt.pct(e / n)}) מסומנות כקיימות, "
            f"ו-{p:,} כמתוכננות." + other + tail)


def ins_metro(stations):
    vc = frame.ranked(pd.Series([s["metro"] for s in stations], dtype=str))
    if len(vc) < 2 or vc.iloc[0] == vc.iloc[1]:
        return None
    top, second = vc.index[0], vc.index[1]
    te = sum(s["metro"] == top and s["status"] == EXISTING for s in stations)
    parts = [f"ב{top} מתוכננת הרשת הגדולה ביותר: {int(vc.iloc[0]):,} תחנות"
             + (f", מהן {te:,} מסומנות כקיימות" if te >= 2 else "")
             + f", לעומת {int(vc.iloc[1]):,} ב{second}"]
    zero = [m for m in vc.index if not any(s["metro"] == m and s["status"] == EXISTING for s in stations)]
    if zero and len(zero) < len(vc):
        parts.append(f"ב{fmt.join_he(zero)} אין במאגר אף תחנה שמסומנת כקיימת")
    return ". ".join(parts) + "."


def ins_under(stations):
    u = [s for s in stations if s["under"]]
    n = len(stations)
    if len(u) < 2:
        return None
    vc = frame.ranked(pd.Series([s["metro"] for s in u], dtype=str))
    s = f"רק {len(u):,} מתוך {n:,} התחנות ({fmt.pct(len(u) / n)}) כוללות מפלס תת-קרקעי; כל השאר במפלס הרחוב או מעליו."
    if vc.iloc[0] / len(u) >= 0.6:
        s += f" {int(vc.iloc[0]):,} מהן ב{vc.index[0]}."
    ue = sum(x["status"] == EXISTING for x in u)
    e = sum(x["status"] == EXISTING for x in stations)
    if ue >= 2 and e >= 3:
        s += f" מבין {e:,} התחנות שמסומנות במאגר כקיימות, {ue:,} כוללות מפלס תת-קרקעי."
    return s


def _folded_lines(stations):
    """(metro, line, distinct stations) per folded line, most stations first."""
    acc = {}
    for s in stations:
        for b in s["lines"]:
            acc[(s["metro"], b)] = acc.get((s["metro"], b), 0) + 1
    return sorted([(m, b, c) for (m, b), c in acc.items()], key=lambda t: (-t[2], t[0], t[1]))


def ins_line(stations):
    fl = _folded_lines(stations)
    if len(fl) < 2 or fl[0][2] == fl[1][2]:
        return None
    am, a, an = fl[0]
    second = [t for t in fl[1:] if t[2] == fl[1][2]]
    s = f"הקו עם הכי הרבה תחנות הוא {_line_he(a)} ב{_metro_short(am)}, עם {an:,} תחנות"
    if len(second) == 1:
        s += f", ואחריו {_line_he(second[0][1])} ב{_metro_short(second[0][0])} עם {second[0][2]:,}"
    elif len(second) <= 3:
        s += (", ואחריו " + fmt.join_he([f"{_line_he(b)} ב{_metro_short(m)}" for m, b, _c in second])
              + f" עם {second[0][2]:,} תחנות כל אחד")
    return s + " (קו מקווקו נספר עם הקו המלא באותו צבע)."


def ins_xfer(stations):
    multi = [s for s in stations if s["k"] >= 2]
    if len(multi) < 2:
        return None
    best_k = max(s["k"] for s in stations)
    tied = sorted([s for s in stations if s["k"] == best_k], key=lambda s: (s["metro"], s["name"]))
    n = len(stations)
    out = (f"{len(multi):,} מתוך {n:,} התחנות ({fmt.pct(len(multi) / n)}) "
           f"הן תחנות מעבר שמשרתות שני קווים או יותר.")
    if best_k >= 3 and len(tied) == 1:
        b = tied[0]
        out += (f" הצומת הגדול ביותר הוא {b['name']} ב{_metro_short(b['metro'])}, "
                f"שבו נפגשים {b['k']} קווים ({fmt.join_he(b['lines'])}).")
    elif best_k >= 3 and len(tied) <= 4:
        out += (f" הצמתים הגדולים ביותר, עם {best_k} קווים כל אחד: "
                f"{fmt.join_he([t['name'] + ' (' + _metro_short(t['metro']) + ')' for t in tied])}.")
    elif best_k >= 3:
        out += f" {len(tied):,} מהן משרתות {best_k} קווים, הכי הרבה ברשת."
    return out


def ins_spacing(lines):
    sp = [r for r in lines if r["spacing"] is not None and r["measured"] >= SPACING_INSIGHT_MIN and not r["dashed"]]
    if len(sp) < 3:
        return None
    rnd = {r["label"]: int(round(r["spacing"], -1)) for r in sp}
    lo_v, hi_v = min(rnd.values()), max(rnd.values())
    if hi_v < lo_v * 1.3:
        return None

    def names(v):
        hit = sorted([r for r in sp if rnd[r["label"]] == v], key=lambda r: (r["metro"], r["line"]))
        if len(hit) > 3:
            return None
        return fmt.join_he([f"{_line_he(r['line'], True)} ב{_metro_short(r['metro'])}" for r in hit])

    lo, hi = names(lo_v), names(hi_v)
    if not lo or not hi:
        return None
    return (f"המרווח בין התחנות משתנה בין הקווים (קווים מלאים עם {SPACING_INSIGHT_MIN} תחנות לפחות, "
            f"בלי נקודות טנטטיביות): {lo} התחנה הקרובה נמצאת בחציון כ-{fmt.int_he(lo_v)} מטר משכנתה, "
            f"ו{hi} כ-{fmt.int_he(hi_v)} מטר.")


def ins_update(df):
    d = df.dropna(subset=["ym"])
    if d.empty:
        return None
    last = d.groupby("metro")["ym"].max()
    if len(last) < 2 or last.min() == last.max():
        return None
    old = sorted(last[last == last.min()].index)
    new = sorted(last[last == last.max()].index)
    return (f"הנתונים לא עודכנו באותו מועד: הרשומות של {fmt.join_he(old)} עודכנו לאחרונה ב{_ym_he(last.min())}, "
            f"ושל {fmt.join_he(new)} ב{_ym_he(last.max())}.")


def ins_tentative(df):
    t = df[df["tentative"]]
    if len(t) < 2:
        return None
    names = sorted(t["name"].unique())
    listed = fmt.join_he(names) if len(names) <= 4 else ", ".join(names[:3]) + f" ועוד {len(names) - 3:,} שמות"
    return (f"{len(t):,} נקודות במאגר מסומנות בשם כטנטטיביות, כלומר מיקום התחנה עדיין לא נקבע סופית"
            f" ({listed}).")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prep(frames["main"])
    stations = _stations(df)
    n = len(stations)
    statuses = _order([s["status"] for s in stations], STATUS_ORDER)
    types = _order([s["type"] for s in stations], TYPE_ORDER)
    metro_vc = frame.ranked(pd.Series([s["metro"] for s in stations], dtype=str))
    metros = list(metro_vc.index)
    metro_names = [_metro_short(m) for m in metros]
    n_exist = sum(s["status"] == EXISTING for s in stations)
    n_plan = sum(s["status"] == PLANNED for s in stations)
    n_other = n - n_exist - n_plan
    n_under = sum(s["under"] for s in stations)
    lines = _lines_table(stations)
    base_lines = {(r["metro"], _base(r["line"])) for r in lines}
    n_xfer = sum(1 for s in stations if s["k"] >= 2)
    n_merged = sum(1 for s in stations if s["points"] > 1)

    def count(**kw):
        return sum(all(s[k] == v for k, v in kw.items()) for s in stations)

    # metro × status
    metro_chart = {
        "names": metro_names,
        "series": [{"name": "מסומנות כ" + PLURAL[s] if s in PLURAL else s,
                    "color": STATUS_COLORS.get(s, FALLBACK[i % len(FALLBACK)]),
                    "data": [count(metro=m, status=s) for m in metros]}
                   for i, s in enumerate(statuses)],
    }
    metro_status_rows = [[metro_names[i]] + [f"{s['data'][i]:,}" for s in metro_chart["series"]]
                         + [f"{int(metro_vc[m]):,}"] for i, m in enumerate(metros)]
    metro_rows = []
    for m in metros:
        g = df[df["metro"] == m]
        yms = g["ym"].dropna()
        x, y = g["x"].dropna(), g["y"].dropna()
        span_ns = (y.max() - y.min()) / 1000 if len(y) > 1 else 0.0
        span_ew = (x.max() - x.min()) / 1000 if len(x) > 1 else 0.0
        metro_rows.append([
            _metro_short(m), fmt.join_he(list(frame.ranked(g["comp"]).index)), f"{int(metro_vc[m]):,}",
            f"{sum(1 for bm, _b in base_lines if bm == m):,}",
            fmt.num_he(span_ns, 1), fmt.num_he(span_ew, 1),
            _ym_he(yms.max()) if len(yms) else "–",
        ])

    # lines: chart capped at TOP_LINES + an "אחר" bar; the table lists all
    shown = _cut(lines, TOP_LINES)
    rest = lines[len(shown):]
    lines_chart = {
        "names": [r["label"] for r in shown], "values": [r["n"] for r in shown],
        "existing": [r["existing"] for r in shown], "colors": [r["color"] for r in shown],
        "dashed": [r["dashed"] for r in shown],
    }
    if rest:
        lines_chart["names"].append(f"אחר ({len(rest)} מסלולים)")
        lines_chart["values"].append(len(set().union(*[r["sids"] for r in rest])))
        lines_chart["existing"].append(len(set().union(*[r["exist_sids"] for r in rest])))
        lines_chart["colors"].append(OTHER_COLOR)
        lines_chart["dashed"].append(False)
    any_other = any(r["other"] for r in lines)
    lines_cols = (["מסלול", "מטרופולין", "תחנות", "קיימת (נקודה של המסלול בלבד)", "מתוכננת (נקודה של המסלול בלבד)"]
                  + (["סטטוס אחר (נקודה של המסלול בלבד)"] if any_other else [])
                  + ["רק בנקודה משותפת", "עם מפלס תת-קרקעי"])
    lines_rows = [[r["line"], _metro_short(r["metro"]), f"{r['n']:,}", f"{r['existing']:,}", f"{r['planned']:,}"]
                  + ([f"{r['other']:,}"] if any_other else [])
                  + [f"{r['shared']:,}", f"{r['under']:,}"] for r in lines]

    if n:
        top_c = int(metro_vc.iloc[0])
        tied_m = [_metro_short(m) for m in metros if int(metro_vc[m]) == top_c]
        metro_lede = ("התחנות לפי מטרופולין והסטטוס שנרשם להן. "
                      + (f"ב{tied_m[0]} {top_c:,} תחנות, {fmt.pct(top_c / n)} מהמאגר." if len(tied_m) == 1 else
                         f"{fmt.join_he(['ב' + t for t in tied_m])} {top_c:,} תחנות בכל אחד, "
                         f"{fmt.pct(top_c / n)} מהמאגר לכל מטרופולין."))
    else:
        metro_lede = ""

    # type × metro
    type_chart = {
        "names": [TYPE_LABEL.get(t, t) for t in types],
        "series": [{"name": _metro_short(m), "data": [count(metro=m, type=t) for t in types]} for m in metros],
    }
    type_exist = [count(type=t, status=EXISTING) for t in types]
    type_rows = [[type_chart["names"][i]] + [f"{s['data'][i]:,}" for s in type_chart["series"]]
                 + [f"{type_exist[i]:,}", f"{sum(s['data'][i] for s in type_chart['series']):,}"]
                 for i in range(len(types))]

    # interchanges
    max_k = max([s["k"] for s in stations] + [1])
    ks = list(range(0 if any(s["k"] == 0 for s in stations) else 1, max_k + 1))
    xfer_chart = {
        "names": [f"{k} קווים" if k > 1 else ("קו אחד" if k == 1 else "ללא קו") for k in ks],
        "series": [{"name": _metro_short(m), "data": [count(metro=m, k=k) for k in ks]} for m in metros],
    }
    xfer_rows = [[xfer_chart["names"][i]] + [f"{s['data'][i]:,}" for s in xfer_chart["series"]]
                 + [f"{sum(s['data'][i] for s in xfer_chart['series']):,}"] for i in range(len(ks))]
    multi = sorted([s for s in stations if s["k"] >= 2], key=lambda s: (-s["k"], s["metro"], s["name"]))
    tie_left = 0
    if len(multi) > TOP_XFER:
        cut_k = multi[TOP_XFER - 1]["k"]
        upto = [s for s in multi if s["k"] >= cut_k]
        top_x = upto[:TOP_XFER_MAX]
        tie_left = len(upto) - len(top_x)
    else:
        top_x = multi

    def marked(st):
        per_line = [_line_status(st["rows"], b, "line") for b in st["lines"]]
        if None in per_line or not per_line:
            # Some line reaches the station only at a point shared with other
            # lines, so its own status is unknown; describe the points.
            pts = _order(st["rows"]["status"], STATUS_ORDER)
            all_shared = all(v is None for v in per_line)
            if len(pts) == 1:
                return ((f"נקודה משותפת מסומנת כ{pts[0]}" if st["points"] == 1 else
                         "נקודות משותפות מסומנות כ" + PLURAL.get(pts[0], pts[0])) if all_shared
                        else f"כל הנקודות מסומנות כ{PLURAL.get(pts[0], pts[0])}, "
                             "חלקן משותפות")
            return "קיימת בחלק מהנקודות" if EXISTING in pts else "סטטוסים שונים"
        vals = set(per_line)
        if vals == {EXISTING}:
            return "מסומנת כקיימת"
        if EXISTING in vals:
            return "קיימת בחלק מהקווים"
        if vals == {PLANNED}:
            return "מסומנת כמתוכננת"
        return "מסומנת כ" + ", ".join(_order(vals, STATUS_ORDER))

    top_x_rows = [[s["name"], _metro_short(s["metro"]), f"{s['k']}", ", ".join(s["lines"]), marked(s)]
                  for s in top_x]

    # spacing: chart for the TOP_LINES lines with the most stations, the table for all
    sp_all = sorted([r for r in lines if r["spacing"] is not None], key=lambda r: (r["spacing"], r["label"]))
    big = {r["label"] for r in _cut([r for r in lines if r["spacing"] is not None], TOP_LINES)}
    sp = [r for r in sp_all if r["label"] in big]
    n_sp_excl = len(lines) - len(sp_all)
    spacing_chart = {"names": [r["label"] for r in sp], "values": [int(round(r["spacing"], -1)) for r in sp],
                     "colors": [r["color"] for r in sp]}
    spacing_rows = [[r["label"], f"{r['measured']:,}", fmt.int_he(round(r["spacing"], -1))] for r in sp_all]

    geo_model = _map_section(frames["geo"]) if "geo" in frames else None

    insights = []
    for iid, txt in [("status", ins_status(stations, df)), ("metro", ins_metro(stations)),
                     ("line", ins_line(stations)), ("xfer", ins_xfer(stations)), ("under", ins_under(stations)),
                     ("spacing", ins_spacing(lines)), ("update", ins_update(df)),
                     ("tentative", ins_tentative(df))]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    metros_he = fmt.join_he(["ב" + m for m in metro_names])
    span = _update_span(df)

    rule = (f"תחנה היא נקודה אחת או כמה נקודות סמוכות במאגר: נקודות של קווים שונים במרחק של עד {LINK_M} מטר "
            f"זו מזו, או נקודות באותו שם (בלי להתחשב ברווחים ובמקפים) במרחק של עד {SAME_NAME_M} מטר, "
            "נספרות כתחנה אחת.")
    lede = (f"המאגר של משרד התחבורה ממפה {n:,} תחנות רכבת קלה {metros_he}, על {len(base_lines):,} קווים: "
            + fmt.join_he([f"{n_exist:,} מסומנות כקיימות", f"{n_plan:,} כמתוכננות"]
                          + ([f"{n_other:,} בסטטוס אחר"] if n_other else []))
            + (f", לפי הרשומות שעודכנו לאחרונה {span}" if span else "")
            + ". לכל תחנה רשומים הקו או הקווים שעוברים בה, הסוג (עילית, תת-קרקעית או מוגבהת), הסטטוס והחברה המתכננת. "
            + rule)

    summary = (f"{n:,} תחנות רכבת קלה קיימות ומתוכננות {metros_he}: {n_exist:,} מסומנות כקיימות, "
               f"{n_plan:,} כמתוכננות, על {len(base_lines):,} קווים, מהן {n_xfer:,} תחנות מעבר.")
    desc = (f"מפת תחנות הרכבת הקלה {metros_he}: {n:,} תחנות, {n_exist:,} מסומנות כקיימות ו-{n_plan:,} "
            f"כמתוכננות, לפי קו, סוג ותחנות מעבר.")

    kpis = {
        "total": {"value": n, "display": f"{n:,}", "tone": "brand"},
        "existing": {"value": n_exist, "display": f"{n_exist:,}", "tone": "ok" if n_exist else "warn"},
        "planned": {"value": n_plan, "display": f"{n_plan:,}", "tone": "info"},
        "lines": {"value": len(base_lines), "display": f"{len(base_lines):,}", "tone": "brand"},
        "xfer": {"value": n_xfer, "display": f"{n_xfer:,}", "tone": "brand"},
        "under": {"value": n_under, "display": f"{n_under:,}", "tone": "brand"},
    }

    lead_line = lines[0] if lines else None
    lead_txt = ""
    if lead_line:
        leaders = [r for r in lines if r["n"] == lead_line["n"]]
        names = [f"{_line_he(r['line'])} ב{_metro_short(r['metro'])}" for r in leaders]
        if len(leaders) == 1:
            lead_txt = f"{names[0]} מוביל עם {lead_line['n']:,} תחנות. "
        elif len(leaders) <= 3:
            lead_txt = f"{fmt.join_he(names)} מובילים עם {lead_line['n']:,} תחנות כל אחד. "
    labels = {
        "lede": lede,
        "kpi_total": "תחנות במאגר",
        "kpi_existing": "מסומנות במאגר כקיימות",
        "kpi_planned": "מסומנות במאגר כמתוכננות",
        "kpi_lines": "קווים (בכל המטרופולינים)",
        "kpi_xfer": "תחנות מעבר בין קווים",
        "kpi_under": "תחנות עם מפלס תת-קרקעי",
        "metro_cols": metro_names,
        "status_cols": [s["name"] for s in metro_chart["series"]],
        "metro_lede": metro_lede,
        "metro_aria": "תרשים עמודות: מספר התחנות שמסומנות כקיימות וכמתוכננות בכל מטרופולין",
        "lines_lede": ((f"מספר התחנות בכל מסלול, בצבע הקו. מסלול הוא קו או גרסה מקווקוות של קו, כפי שהם מופיעים במאגר "
                        f"({len(lines):,} מסלולים של {len(base_lines):,} קווים). "
                        + lead_txt
                        + "תחנת מעבר נספרת בכל מסלול שעובר בה. הסטטוס נרשם במאגר לכל נקודה ולא לכל קו, ולכן בטבלה תחנה נספרת "
                        "כקיימת או כמתוכננת במסלול רק לפי נקודה שמשרתת את הקו הזה בלבד (המסלול או גרסה אחרת של אותו קו); "
                        "תחנה שבה המסלול עובר רק בנקודה משותפת לכמה קווים מופיעה בעמודה נפרדת, כך שסכום העמודות שווה "
                        "למספר התחנות."
                        + (f" התרשים מציג את {len(shown):,} המסלולים הגדולים{TIE_NOTE if len(shown) > TOP_LINES else ''} ועמודת \"אחר\" שסופרת כל תחנה בהם פעם אחת, "
                           f"והטבלה את כל {len(lines):,} המסלולים." if rest else ""))
                       if lead_line else ""),
        "lines_aria": "תרשים עמודות אופקי: מספר התחנות בכל מסלול",
        "type_lede": (f"{n_under:,} תחנות ({fmt.pct(n_under / n)}) כוללות מפלס תת-קרקעי, והשאר במפלס הרחוב או מעליו. "
                      "תחנה משולבת מחברת נקודות בכמה מפלסים, למשל רציף תת-קרקעי לצד רציף עילי."
                      if n else ""),
        "type_aria": "תרשים עמודות מוערמות: סוגי התחנות לפי מטרופולין",
        "xfer_lede": (f"כמה קווים עוברים בכל תחנה. {n_xfer:,} מתוך {n:,} התחנות משרתות שני קווים או יותר. "
                      "קו מקווקו נספר יחד עם הקו המלא באותו צבע."
                      + (f" {n_merged:,} תחנות מאחדות כמה נקודות סמוכות במאגר." if n_merged else "")),
        "xfer_aria": "תרשים עמודות: מספר התחנות לפי מספר הקווים שעוברים בהן",
        "top_xfer_caption": (f"מוצגות {len(top_x):,} מתוך {len(multi):,} תחנות המעבר, לפי מספר הקווים"
                             + ((f" ({tie_left:,} תחנות נוספות עם אותו מספר קווים כמו השורה האחרונה לא מוצגות)"
                                 if tie_left else " (כולל כל התחנות שבתיקו במקום האחרון)")
                                if len(top_x) > TOP_XFER else "")
                             + "."),
        "spacing_lede": ("המרחק החציוני מכל תחנה לתחנה הקרובה אליה באותו מסלול, במטרים, בלי נקודות טנטטיביות"
                         + (f" ({n_sp_excl:,} מסלולים עם פחות מ-{MIN_SPACING_STATIONS} תחנות שנמדדו לא נכללו)" if n_sp_excl else "")
                         + ". מרווח קטן מאפיין קו עירוני צפוף, ומרווח גדול קו שמחבר בין שכונות או ערים."
                         + (f" התרשים מציג את {len(sp):,} המסלולים עם הכי הרבה תחנות{TIE_NOTE if len(sp) > TOP_LINES else ''}, והטבלה את כל {len(sp_all):,}."
                            if len(sp) < len(sp_all) else "")),
        "spacing_aria": "תרשים עמודות אופקי: המרווח החציוני בין תחנות בכל מסלול, במטרים",
        "metro_table_lede": ("החברה המתכננת, מספר התחנות והקווים, פריסת הרשת (המרחק בין הנקודות הקיצוניות) "
                             "ומועד העדכון האחרון של הרשומות בכל מטרופולין."),
    }
    if geo_model:
        labels["map_note"] = (f"כל נקודה במפה היא רשומה במאגר ({geo_model['n']:,} נקודות), בצבע לפי הסטטוס שנרשם לה; "
                              "תחנת מעבר יכולה להופיע כמה נקודות סמוכות, ולנקודה תת-קרקעית מסגרת כהה. "
                              "לחיצה על נקודה מציגה את שם התחנה, הקווים, הסוג והמטרופולין."
                              + (" הכפתורים מתמקדים בכל מטרופולין." if geo_model["zoom"] else ""))
        labels["map_aria"] = f"מפת תחנות הרכבת הקלה: {geo_model['n']:,} נקודות, בצבע לפי סטטוס"

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "map",
        "spatial_coverage": fmt.join_he(metro_names),
        "seo": {
            "title": "תחנות הרכבת הקלה: מפת תחנות קיימות ומתוכננות",
            "description": desc,
            "name": "תחנות הרכבת הקלה בישראל",
            "alternate_names": ["תחנות רכבת קלה", "מפת תחנות הרכבת הקלה", "תחנות הרק\"ל",
                                "תחנות הרכבת הקלה בירושלים", "תחנות הרכבת הקלה בגוש דן"],
        },
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": ["total", "existing", "planned", "lines", "xfer", "under"],
        "charts": {"metro": metro_chart, "lines": lines_chart, "type": type_chart,
                   "xfer": xfer_chart, "spacing": spacing_chart, "map": geo_model},
        "lines_cols": lines_cols,
        "tables": {"metro": metro_rows, "metro_status": metro_status_rows, "lines": lines_rows,
                   "type": type_rows, "xfer": xfer_rows, "top_xfer": top_x_rows, "spacing": spacing_rows},
        "flags": {"map": bool(geo_model), "spacing": len(sp) >= 2, "top_xfer": bool(top_x_rows)},
        "insights": insights,
        "labels": labels,
    }
