"""עסקים קולטי קהל בבאר שבע — one row per business record (name, street
address, free-text licensing kind, WGS84 point and a JSON list of the
business's street signs).  The page asks: what kinds of businesses are they
(free-text kinds grouped by keyword), where are they (street ranking, density
grid, rings around the centre, a live map), how heavily are they signed (sign
counts, sign content types) and who stands out (multi-site names).

The CSV resource is NOT read: its `signs` JSON is mangled by CSV quoting and
a few rows are shifted.  The XLSX twin carries the same rows intact.
Order-independent: integer counts, sorted aggregates, fsum for coordinates.
"""
import json
import math
import re

import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
R_KM = 6371.0088
RING_KM = 1
MAX_RINGS = 5
MAX_BANDS = 16
GRID_SCALE = 200
TOP_KINDS = 12
TOP_STREETS = 12
TOP_NAMES = 10
MIN_CAT_FOR_MEAN = 20
MIN_ROWS = 50
SIGN_BUCKETS = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 5), (6, 10), (11, 20)]  # last = over 20
TOP_MIX = 6

NO_KIND = "לא צוין סוג"
OTHER = "אחר"
MISC = "שונות"
TAIL_CATS = (OTHER, MISC, NO_KIND)

# (category, regex over the free-text kind). First match wins.
CAT_RULES = [
    ("רכב ותחבורה", "חניון|תחנת דלק|תחנת תידלוק|מוסך|צמיג|רכב|רחיצת מכוניות|הסעות|הובלת|מוניות|שליחות|מכוניות|מלגזות|מנוע"),
    ("בריאות ורפואה", "מרפא|מעבד|מרקחת|רפוא|בית אבות|שיניים|בית חולים"),
    ("יופי וטיפוח", "מספרה|יופי|קוסמ|ציפורנ|מניקור|פדיקור|קעקוע"),
    ("חינוך והדרכה", "בית ספר|גן ילדים|כיתות|מכללה|מעון|למחול|סדנאות"),
    ("תעשייה ומלאכה", "מפעל|ייצור|יצור|מתפרה|מסגרי|נגרי|מתכת|אלומיניום|דפוס|מרפדי|עץ-|מטוח|מנועים|זגג|שיש|מכבס|מים/|מתקן|קבלן|חומ\"ס|חומרים מסוכנים|שיפוץ"),
    ("אוכל ומשקאות", "מסעדה|קפה|בית אוכל|דוכן אוכל|פאב|משקאות|קיוסק|מזנון|פיצוחים|מאפ|מאפיה|אפיה|עוגות"),
    ("מזון ומכולת", "מכולת|סופר|מינימרקט|מרכול|אטליז|איטליז|ירקן|ירקות|בשר|מזון|תבלינים|דגים"),
    ("מחסנים ואחסנה", "מחסן|אחסנ|מכולה"),
    ("פנאי, אירוח ואירועים", "אולם|קולנוע|כושר|מלון|פנסי|בריכה|קאנטרי|משחקים|בריחה|עינוג|מועדון"),
    ("משרדים ושירותים", "משרד|בנק|ביטוח|עורכי דין|עמותות|דואר|מוקד|שמירה|אבטחה|ממשלה|תחנת כח|מכירות|שירות"),
    ("חנויות ומסחר", "חנות|ביגוד|הנעלה|הלבשה|תכשיט|צעצוע|אלקטרונ|רהיט|חפצי|מוצרי|מכשירי|פרחים|משתלה|חיות|בע\"ח|אופטיקה|צילום|סנדלרי|מטבעות|סלולר|מרכז קניות|כספות|צבעים|חומרי בניין|קדושה|חלקים|מיזוג|בית מטבחים|דוכן אחר|גינון|נשק"),
    (MISC, "שונות"),
]
CAT_RX = [(n, re.compile(p)) for n, p in CAT_RULES]

SIGN_ROTATING = "פרסום מתחלף"
SIGN_SALE = "השכרה ומכירה"
SIGN_OWN = "שם העסק"
SIGN_DECOR = "לוגו ועיצוב"
SIGN_OTHER = "טקסט אחר"
SIGN_ORDER = [SIGN_OWN, SIGN_ROTATING, SIGN_DECOR, SIGN_SALE, SIGN_OTHER]
ROT_RX = re.compile(r"מתחלף|אלקטרוני|מסך|דיגיטל")
SALE_RX = re.compile(r"להשכרה|למכירה|להשכיר")
DECOR_RX = re.compile(r"סככה|ויטרינה|לוגו|סמל|תמונה|דגל|חזית|שלט")
PHONE_RX = re.compile(r"^[\d\s\-+().]+$|\d{2,3}-?\d{7}")
NORM_RX = re.compile(r"[^0-9A-Za-zא-ת]")


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _kind_cat(k):
    if not k:
        return NO_KIND
    for name, rx in CAT_RX:
        if rx.search(k):
            return name
    return OTHER


def _first_kind(k):
    parts = [p.strip() for p in k.split(",") if p.strip()]
    for p in parts:
        if p != MISC:
            return p
    return parts[0] if parts else ""


def _sign_class(text, name_norm):
    if ROT_RX.search(text):
        return SIGN_ROTATING
    if SALE_RX.search(text):
        return SIGN_SALE
    t = NORM_RX.sub("", text)
    if len(t) >= 2 and name_norm and (t in name_norm or name_norm in t):
        return SIGN_OWN
    if DECOR_RX.search(text):
        return SIGN_DECOR
    return SIGN_OTHER


def _parse_signs(s):
    try:
        v = json.loads(s)
    except (ValueError, TypeError):
        return None
    if not isinstance(v, list):
        return None
    return [str((x or {}).get("contents") or "").strip() if isinstance(x, dict) else "" for x in v]


def _prepare(df):
    out = df.copy()
    for c in ("business_name", "full_address", "business_kind"):
        out[c] = out[c].str.strip()
    out["latf"] = pd.to_numeric(out["location_lat"].str.strip(), errors="coerce")
    out["lonf"] = pd.to_numeric(out["location_lng"].str.strip(), errors="coerce")
    out["geo_ok"] = out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
    out["kind1"] = out["business_kind"].map(_first_kind)
    out["cat"] = out["business_kind"].map(_kind_cat)
    out["street"] = out["full_address"].str.replace(r"\s*\d.*$", "", regex=True).str.strip()
    out["has_num"] = out["full_address"].str.contains(r"\d")
    out["name_ok"] = out["business_name"].ne("") & ~out["business_name"].str.contains(PHONE_RX)
    parsed = out["signs"].map(_parse_signs)
    out["signs_ok"] = parsed.notna()
    out["sign_list"] = parsed.map(lambda v: v if v is not None else [])
    out["n_signs"] = out["sign_list"].map(len)
    out = out.sort_values(["business_name", "full_address", "business_kind", "location_lat",
                           "location_lng", "signs"], kind="stable")
    return out.reset_index(drop=True)


def _order_cats(counts):
    """counts: {cat: n} -> list of (cat, n): by size, tail categories last."""
    main = sorted(((k, v) for k, v in counts.items() if k not in TAIL_CATS),
                  key=lambda kv: (-kv[1], kv[0]))
    tail = [(k, counts[k]) for k in TAIL_CATS if k in counts]
    return main + tail


def _bands(values):
    idx = [int(math.floor(v * GRID_SCALE + 1e-9)) for v in values]
    lo, hi = min(idx), max(idx)
    w = max(1, math.ceil((hi - lo + 1) / MAX_BANDS))
    lo = (lo // w) * w
    return idx, lo, hi, w


def _blabel(a):
    return f"{a / GRID_SCALE:.3f}"


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    geo = df[df["geo_ok"]].copy()
    n_geo = len(geo)
    n_nogeo = total - n_geo
    n_unreadable = int((~df["signs_ok"]).sum())

    # ---------- kinds
    cat_counts = {k: int(v) for k, v in df["cat"].value_counts().items()}
    cats = _order_cats(cat_counts)
    typed = total - cat_counts.get(NO_KIND, 0)
    typed_share = typed / total if total else 0.0
    cats_chart = {"names": [k for k, _ in cats], "values": [v for _, v in cats]}
    t_cats = [{"name": k, "count": _int(v), "share": _pct(v / total, 1)} for k, v in cats]

    kc = df[df["kind1"] != ""].groupby("kind1").size()
    kinds = sorted(((k, int(v)) for k, v in kc.items()), key=lambda kv: (-kv[1], kv[0]))[:TOP_KINDS]
    kinds_chart = {"names": [k for k, _ in kinds], "values": [v for _, v in kinds]}
    t_kinds = [{"name": k, "count": _int(v), "share": _pct(v / total, 1)} for k, v in kinds]
    n_kinds = int(kc.shape[0])

    # ---------- streets
    sc = df[df["street"] != ""].groupby("street").size()
    streets_all = sorted(((k, int(v)) for k, v in sc.items()), key=lambda kv: (-kv[1], kv[0]))
    streets = streets_all[:TOP_STREETS]
    street_signs = df.groupby("street")["n_signs"].sum()
    streets_chart = {"names": [k for k, _ in streets], "values": [v for _, v in streets]}
    t_streets = [{"name": k, "count": _int(v), "share": _pct(v / total, 1),
                  "signs": _int(int(street_signs.get(k, 0)))} for k, v in streets]
    n_streets = len(streets_all)

    # ---------- signs
    sizes = sorted(df["n_signs"].tolist())
    n_signs = int(sum(sizes))
    with_signs = int((df["n_signs"] > 0).sum())
    median_signs = (sizes[(total - 1) // 2] + sizes[total // 2]) / 2 if total else 0
    mx_idx = int(df["n_signs"].to_numpy().argmax()) if total else 0
    max_signs = int(df["n_signs"].max()) if total else 0
    b_names, b_vals = [], []
    for lo, hi in SIGN_BUCKETS:
        b_names.append(str(lo) if lo == hi else f"\u200e{lo}-{hi}")
        b_vals.append(int(((df["n_signs"] >= lo) & (df["n_signs"] <= hi)).sum()))
    over = SIGN_BUCKETS[-1][1]
    b_names.append(f"\u200e{over + 1}+")
    b_vals.append(int((df["n_signs"] > over).sum()))
    signs_chart = {"names": b_names, "values": b_vals}
    t_signs = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in zip(b_names, b_vals)]
    # concentration: top decile of businesses by sign count
    k10 = max(1, math.ceil(total * 0.10))
    top_decile_signs = int(sum(sizes[-k10:]))
    decile_share = top_decile_signs / n_signs if n_signs else 0.0

    # sign content classes
    sc_counts = {k: 0 for k in SIGN_ORDER}
    for name, lst in zip(df["business_name"], df["sign_list"]):
        nn = NORM_RX.sub("", name)
        for t in lst:
            sc_counts[_sign_class(t, nn)] += 1
    sc_list = [(k, sc_counts[k]) for k in SIGN_ORDER]
    sc_list.sort(key=lambda kv: (-kv[1], SIGN_ORDER.index(kv[0])))
    sign_types_chart = {"names": [k for k, _ in sc_list], "values": [v for _, v in sc_list]}
    t_sign_types = [{"name": k, "count": _int(v), "share": _pct(v / n_signs, 1) if n_signs else "0%"}
                    for k, v in sc_list]

    # mean signs by category
    mean_rows = []
    for k, g in df[~df["cat"].isin(TAIL_CATS)].groupby("cat"):
        if len(g) >= MIN_CAT_FOR_MEAN:
            mean_rows.append((k, int(g["n_signs"].sum()) / len(g), len(g)))
    mean_rows.sort(key=lambda r: (-r[1], r[0]))
    mean_chart = {"names": [r[0] for r in mean_rows], "values": [round(r[1], 1) for r in mean_rows]}
    t_mean = [{"name": r[0], "mean": f"{r[1]:.1f}", "count": _int(r[2])} for r in mean_rows]
    overall_mean = n_signs / total if total else 0.0

    # ---------- multi-site names
    nm = df[df["name_ok"]].groupby("business_name").agg(rows=("business_name", "size"),
                                                         signs=("n_signs", "sum"))
    names_all = sorted(((k, int(r), int(s)) for k, r, s in zip(nm.index, nm["rows"], nm["signs"])),
                       key=lambda t: (-t[1], -t[2], t[0]))
    multi = [t for t in names_all if t[1] >= 2]
    top_names = multi[:TOP_NAMES]
    names_chart = {"names": [t[0] for t in top_names], "values": [t[1] for t in top_names]}
    t_names = [{"name": t[0], "count": _int(t[1]), "signs": _int(t[2])} for t in top_names]
    n_unique_names = len(names_all)

    # ---------- completeness
    fields = [("סוג עסק", typed), ("כתובת עם מספר בית", int(df["has_num"].sum())),
              ("קואורדינטות תקינות", n_geo), ("שלט אחד לפחות", with_signs)]
    fields_chart = {"names": [n for n, _ in fields], "values": [v for _, v in fields],
                    "pct": [round(v / total * 100, 1) if total else 0 for _, v in fields]}
    t_fields = [{"name": n, "count": _int(v), "share": _pct(v / total, 1)} for n, v in fields]

    # ---------- geometry
    grid_chart = {"x": [], "y": [], "data": [], "max": 0}
    ring_chart = {"rings": [], "series": []}
    map_view = {"center": [31.25, 34.8], "zoom": 12}
    n_placed_zero = int((df["latf"].notna() & df["lonf"].notna() & ~df["geo_ok"]).sum())
    t_ring = []
    top_cell = None
    inner_share = None
    mix_gap = None
    center_km = None
    ns_km = ew_km = 0.0
    if n_geo >= MIN_ROWS:
        lats = geo["latf"].tolist()
        lons = geo["lonf"].tolist()
        lat0 = math.fsum(lats) / n_geo
        kx = math.cos(math.radians(lat0))
        xs = [math.radians(v) * R_KM * kx for v in lons]
        ys = [math.radians(v) * R_KM for v in lats]
        sx, sy = sorted(xs), sorted(ys)
        cx = (sx[(n_geo - 1) // 2] + sx[n_geo // 2]) / 2
        cy = (sy[(n_geo - 1) // 2] + sy[n_geo // 2]) / 2
        map_view = {"center": [round((sorted(lats)[(n_geo - 1) // 2] + sorted(lats)[n_geo // 2]) / 2, 4),
                               round((sorted(lons)[(n_geo - 1) // 2] + sorted(lons)[n_geo // 2]) / 2, 4)],
                    "zoom": 12}
        geo["dist"] = [math.hypot(x - cx, y - cy) for x, y in zip(xs, ys)]
        ns_km = max(ys) - min(ys)
        ew_km = max(xs) - min(xs)
        geo["ring"] = geo["dist"].map(lambda d: min(int(d // RING_KM), MAX_RINGS - 1))
        rcount = [int((geo["ring"] == i).sum()) for i in range(MAX_RINGS)]
        last = max([i for i, c in enumerate(rcount) if c] or [0])
        nr = last + 1
        rnames = [f"עד {(i + 1) * RING_KM}" for i in range(nr)]
        if last == MAX_RINGS - 1:
            rnames[-1] = f"מעל {(MAX_RINGS - 1) * RING_KM}"
        # category mix per ring: top categories overall (excluding tail) + other
        gc = geo["cat"].value_counts()
        top_c = [k for k, _ in sorted(((k, int(v)) for k, v in gc.items() if k not in TAIL_CATS),
                                      key=lambda kv: (-kv[1], kv[0]))[:TOP_MIX]]
        series = []
        t_ring_cols = top_c + ["אחר או לא צוין"]
        for ck in t_ring_cols:
            if ck == "אחר או לא צוין":
                mask = ~geo["cat"].isin(top_c)
            else:
                mask = geo["cat"] == ck
            vals = []
            for i in range(nr):
                rn = rcount[i]
                vals.append(round(int((mask & (geo["ring"] == i)).sum()) / rn * 100, 1) if rn else 0)
            series.append({"name": ck, "data": vals})
        ring_chart = {"rings": rnames, "series": series, "counts": rcount[:nr]}
        t_ring = []
        for ck, s in zip(t_ring_cols, series):
            t_ring.append({"name": ck, "cells": [f"{v:.1f}%" for v in s["data"]]})
        ring_head = rnames
        inner = geo["dist"] < RING_KM
        n_inner = int(inner.sum())
        inner_share = n_inner / n_geo
        # biggest category-share gap, inner vs outer
        n_outer = n_geo - n_inner
        if n_inner >= MIN_ROWS and n_outer >= MIN_ROWS:
            best = None
            for ck in top_c:
                a = int((inner & (geo["cat"] == ck)).sum()) / n_inner
                b = int((~inner & (geo["cat"] == ck)).sum()) / n_outer
                gap = a - b
                if best is None or abs(gap) > abs(best[1]) + 1e-12:
                    best = (ck, gap, a, b)
            mix_gap = best
        # density grid
        ila, la_lo, la_hi, la_w = _bands(lats)
        ilo, lo_lo, lo_hi, lo_w = _bands(lons)
        la_starts = list(range(la_lo, la_hi + 1, la_w))
        lo_starts = list(range(lo_lo, lo_hi + 1, lo_w))
        geo["gy"] = [(a - la_lo) // la_w for a in ila]
        geo["gx"] = [(a - lo_lo) // lo_w for a in ilo]
        cells = geo.groupby(["gx", "gy"]).size()
        heat = sorted([[int(x), int(y), int(c)] for (x, y), c in cells.items()])
        best_cell = sorted(((int(c), int(y), int(x)) for (x, y), c in cells.items()),
                           key=lambda t: (-t[0], t[1], t[2]))[0]
        cell_df = geo[(geo["gx"] == best_cell[2]) & (geo["gy"] == best_cell[1])]
        cs = cell_df[cell_df["street"] != ""].groupby("street").size()
        cell_street = sorted(((k, int(v)) for k, v in cs.items()), key=lambda kv: (-kv[1], kv[0]))
        top_cell = (best_cell[0], cell_street[0][0] if cell_street else "")
        grid_chart = {"x": [_blabel(a) for a in lo_starts], "y": [_blabel(a) for a in la_starts],
                      "data": heat, "max": max(c for _, _, c in heat)}
        cell_km = la_w / GRID_SCALE * math.radians(1) * R_KM
    else:
        ring_head = []
        cell_km = 0.0

    # ---------- insights
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    # 1 category leader
    typed_cats = [(k, v) for k, v in cats if k not in (NO_KIND,)]
    lead_pool = [(k, v) for k, v in cats if k not in TAIL_CATS]
    if len(lead_pool) >= 2 and typed:
        (a, av), (b, bv) = lead_pool[0], lead_pool[1]
        if av / total >= 0.15 and (av - bv) / total >= 0.03:
            add("kinds", f"הקבוצה הגדולה ביותר היא ״{a}״ עם {_int(av)} עסקים ({_pct(av / total, 1)} מכלל הרשומות), "
                         f"לפני ״{b}״ עם {_int(bv)}. הקבוצות נגזרות ממילות מפתח בשדה סוג העסק החופשי.")
    # 2 missing type
    if cat_counts.get(NO_KIND, 0) / max(total, 1) >= 0.10:
        nk = cat_counts[NO_KIND]
        add("untyped", f"ב-{_int(nk)} רשומות ({_pct(nk / total, 1)}) שדה סוג העסק ריק, ולכן הן נספרות בנפרד "
                       f"בכל חלוקה לפי סוג; {_int(n_kinds)} ניסוחים שונים מופיעים בשאר הרשומות.")
    # 3 signs overview
    if total >= MIN_ROWS and n_signs:
        add("signs", f"ל-{_int(with_signs)} מתוך {_int(total)} העסקים יש שלט אחד לפחות, בסך הכול {_int(n_signs)} שלטים; "
                     f"החציון הוא {median_signs:g} שלטים לעסק והמקסימום {_int(max_signs)}.")
    # 4 concentration
    if n_signs and total >= MIN_ROWS and decile_share >= 0.30:
        add("concentration", f"עשירית הרשומות עם הכי הרבה שלטים ({_int(k10)} רשומות) מחזיקה ב-{_pct(decile_share, 1)} "
                             f"מכלל השלטים: מעטים נושאים חלק גדול מהשילוט.")
    # 5 rotating share
    if n_signs and sc_counts[SIGN_ROTATING] / n_signs >= 0.05:
        r = sc_counts[SIGN_ROTATING]
        add("rotating", f"{_int(r)} שלטים ({_pct(r / n_signs, 1)}) מתוארים כפרסום מתחלף או אלקטרוני, "
                        f"לעומת {_int(sc_counts[SIGN_OWN])} ({_pct(sc_counts[SIGN_OWN] / n_signs, 1)}) שהטקסט בהם זהה לשם העסק או כולל אותו.")
    # 6 multi-site name
    if top_names and top_names[0][1] >= 3:
        nme, c, s = top_names[0]
        ties = sum(1 for t in top_names if t[1] == c)
        lead = (f"השם הנפוץ ביותר הוא ״{nme}״ עם {_int(c)} רשומות ו-{_int(s)} שלטים" if ties == 1 else
                f"{_int(ties)} שמות מובילים עם {_int(c)} רשומות כל אחד, ביניהם ״{nme}״")
        add("names", f"{lead}; בסך הכול {_int(len(multi))} שמות מופיעים ביותר מרשומה אחת, מתוך {_int(n_unique_names)} שמות שונים.")
    # 7 street
    if streets_all and total >= MIN_ROWS and streets_all[0][1] / total >= 0.04:
        s0, c0 = streets_all[0]
        top3 = sum(v for _, v in streets_all[:3])
        add("street", f"הרחוב עם הכי הרבה עסקים הוא ״{s0}״ ({_int(c0)} רשומות, {_pct(c0 / total, 1)}); "
                      f"שלושת הרחובות המובילים מחזיקים יחד {_pct(top3 / total, 1)} מהרשומות, מתוך {_int(n_streets)} רחובות.")
    # 8 inner ring
    if inner_share is not None and 0.15 <= inner_share:
        add("center", f"{_pct(inner_share, 1)} מהעסקים עם מיקום תקין נמצאים בטווח {_int(RING_KM)} ק״מ ממרכז הפריסה, "
                      f"והפריסה כולה משתרעת על {ns_km:.1f} ק״מ מצפון לדרום ועל {ew_km:.1f} ק״מ ממערב למזרח.")
    # 9 mix gap
    if mix_gap and abs(mix_gap[1]) >= 0.04:
        ck, gap, a, b = mix_gap
        word = "גבוה" if gap > 0 else "נמוך"
        add("mix", f"״{ck}״ מהווים {_pct(a, 1)} מהעסקים בטווח {_int(RING_KM)} ק״מ מהמרכז לעומת {_pct(b, 1)} מחוצה לו, "
                   f"כלומר חלקם במרכז {word} יותר ב-{abs(gap) * 100:.1f} נקודות אחוז.")
    # 10 densest cell
    if top_cell and top_cell[0] / n_geo >= 0.04:
        tail = f"; הרחוב הנפוץ בתא הוא ״{top_cell[1]}״" if top_cell[1] else ""
        add("grid", f"תא הצפיפות הגבוה ביותר ברשת מכיל {_int(top_cell[0])} עסקים ({_pct(top_cell[0] / n_geo, 1)} "
                    f"מהרשומות עם מיקום){tail}.")
    # 11 highest mean
    if len(mean_rows) >= 2 and overall_mean:
        k, m, n = mean_rows[0]
        if m >= 1.3 * overall_mean:
            add("heavy", f"בקבוצת ״{k}״ ({_int(n)} עסקים) ממוצע של {m:.1f} שלטים לעסק, לעומת {overall_mean:.1f} בכל המאגר.")
    # 12 no sign / data quality
    if n_nogeo or (total - with_signs):
        bits = []
        if total - with_signs:
            bits.append(f"{_int(total - with_signs)} רשומות ללא שלטים ברשימת השלטים")
        if n_nogeo:
            bits.append(f"{_int(n_nogeo)} רשומות ללא קואורדינטות תקינות (אינן מופיעות במפה ובניתוח המרחבי)")
        add("quality", "; ".join(bits) + ".")

    # ---------- KPIs
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand", "label": "עסקים קולטי קהל במאגר"},
        "signs": {"value": n_signs, "display": _int(n_signs), "tone": "brand", "label": "שלטים בסקר השילוט"},
        "typed": {"value": typed_share, "display": _pct(typed_share, 1),
                  "tone": "ok" if typed_share >= 0.9 else "info" if typed_share >= 0.7 else "warn",
                  "label": "מהרשומות עם סוג עסק"},
        "center": {"value": inner_share or 0, "display": _pct(inner_share or 0, 1), "tone": "info",
                   "label": f"בטווח {_int(RING_KM)} ק״מ ממרכז הפריסה"},
    }

    bad = ""
    if n_nogeo:
        bad = f" {_int(n_nogeo)} רשומות בלי קואורדינטות תקינות מופיעות בניתוחים שאינם מרחביים בלבד."
    labels = {
        "lede": (f"{_int(total)} עסקים קולטי קהל בבאר שבע — עסקים שמשלמים אגרת שילוט ונמצאו בסקר השילוט העירוני — "
                 f"עם כתובת, סוג עסק ורשימת השלטים של כל אחד: {_int(n_signs)} שלטים בסך הכול. "
                 f"העמוד מראה מהם סוגי העסקים, היכן הם מרוכזים ואילו עסקים נושאים הכי הרבה שילוט.{bad}"),
        "map_note": ("העסקים על המפה, ממורכזת על מרכז הפריסה. לחצו על סמן כדי לראות את שם העסק, הכתובת והסוג; לחצו על אשכול כדי להתקרב."
                     + (f" {_int(n_placed_zero)} רשומות נושאות קואורדינטות אפס, ולכן הן מופיעות באשכול נפרד הרחק מהעיר." if n_placed_zero else "")),
        "cats_note": (f"סוג העסק נרשם בטקסט חופשי ({_int(n_kinds)} ניסוחים שונים), ולכן הוא קובץ לקבוצות לפי מילות מפתח. "
                      f"רשומות בלי סוג נספרות בנפרד."),
        "cats_aria": f"תרשים עמודות אופקי: מספר העסקים לפי קבוצת סוג, {len(cats)} קבוצות.",
        "cats_caption": "מספר העסקים לפי קבוצת סוג.",
        "kinds_note": f"הניסוחים הנפוצים ביותר בשדה סוג העסק כפי שהם רשומים (הרשום הראשון כשיש כמה), {len(kinds)} המובילים.",
        "kinds_aria": f"תרשים עמודות אופקי: {len(kinds)} ניסוחי סוג העסק הנפוצים.",
        "kinds_caption": "מספר הרשומות לפי ניסוח סוג העסק.",
        "streets_note": (f"הרחוב נלקח מהכתובת בלי מספר הבית. {_int(len(streets))} הרחובות עם הכי הרבה עסקים, "
                         f"מתוך {_int(n_streets)} רחובות."),
        "streets_aria": f"תרשים עמודות אופקי: {len(streets)} הרחובות עם הכי הרבה עסקים.",
        "streets_caption": "הרחובות עם מספר העסקים הגבוה ביותר.",
        "grid_note": (f"צפיפות העסקים בתאי רשת לפי קו רוחב (למעלה צפון) וקו אורך (שמאל מערב). "
                      f"הצבע מציין את מספר העסקים בתא; התא מכסה כ-{cell_km:.1f} ק״מ בצד."),
        "grid_aria": "מפת חום: מספר העסקים בתאי רשת של קו רוחב וקו אורך.",
        "ring_note": (f"הרכב קבוצות הסוג בטבעות של {_int(RING_KM)} ק״מ סביב מרכז הפריסה (חציון קווי הרוחב והאורך), "
                      f"באחוזים מהעסקים בכל טבעת."),
        "ring_aria": f"תרשים עמודות מוערמות: הרכב סוגי העסקים לפי מרחק מהמרכז, {len(ring_chart['rings'])} טבעות.",
        "ring_caption": "אחוז העסקים בכל קבוצת סוג, לפי מרחק מהמרכז (ק״מ).",
        "signs_note": "כמה שלטים רשומים לכל עסק בסקר השילוט.",
        "signs_aria": f"תרשים עמודות: התפלגות מספר השלטים לעסק, {len(b_names)} קבוצות.",
        "signs_caption": "מספר העסקים לפי מספר השלטים.",
        "sign_types_note": (f"סיווג {_int(n_signs)} השלטים לפי הטקסט הרשום בהם: שם העסק עצמו, פרסום מתחלף או אלקטרוני, "
                            f"לוגו ותמונות, שלטי השכרה ומכירה, ואחר."),
        "sign_types_aria": f"תרשים עמודות אופקי: מספר השלטים לפי סוג תוכן, {len(sc_list)} סוגים.",
        "sign_types_caption": "מספר השלטים לפי סוג תוכן.",
        "mean_note": (f"ממוצע השלטים לעסק בקבוצות סוג עם לפחות {_int(MIN_CAT_FOR_MEAN)} עסקים "
                      f"(ללא רשומות בלי סוג, שונות ואחר); הממוצע הכללי הוא {overall_mean:.1f}."),
        "mean_aria": f"תרשים עמודות אופקי: ממוצע השלטים לעסק לפי קבוצת סוג, {len(mean_rows)} קבוצות.",
        "mean_caption": "ממוצע השלטים לעסק לפי קבוצת סוג.",
        "names_note": (f"שמות עסקים שמופיעים ביותר מרשומה אחת (סניפים או כתובות נפרדות), {len(top_names)} המובילים. "
                       f"שמות שהם מספרי טלפון אינם מוצגים."),
        "names_aria": f"תרשים עמודות אופקי: {len(top_names)} השמות עם הכי הרבה רשומות.",
        "names_caption": "השמות עם מספר הרשומות והשלטים הגבוה ביותר.",
        "fields_note": "אחוז הרשומות שבהן כל שדה מלא ותקין.",
        "fields_aria": "תרשים עמודות אופקי: אחוז הרשומות עם סוג עסק, כתובת עם מספר בית, קואורדינטות ושלט.",
        "fields_caption": "מספר ואחוז הרשומות שבהן השדה מלא.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} עסקים קולטי קהל בבאר שבע עם {_int(n_signs)} שלטים; "
                           f"{_pct(typed_share, 1)} מהרשומות עם סוג עסק. מפה, פיזור לפי רחוב ואזור, "
                           f"קבוצות סוג ופירוט השילוט."),
            "dataset_kind": "map",
            "suggested_tags": ["עסקים", "באר שבע", "שילוט", "רישוי עסקים", "כלכלה מקומית", "מפה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["fffada0a-b021-4629-9244-bc5e301f23d5", "82a30a97-01b0-4281-854c-c7931f3445c0",
                            "727e865d-25b1-43ce-9dcb-af297851f87b"],
        },
        "kpis": kpis,
        "charts": {"cats": cats_chart, "kinds": kinds_chart, "streets": streets_chart, "grid": grid_chart,
                   "ring": ring_chart, "signs": signs_chart, "sign_types": sign_types_chart,
                   "mean": mean_chart, "names": names_chart, "fields": fields_chart},
        "tables": {"cats": t_cats, "kinds": t_kinds, "streets": t_streets, "signs": t_signs,
                   "sign_types": t_sign_types, "mean": t_mean, "names": t_names, "fields": t_fields,
                   "ring": t_ring, "ring_head": ring_head},
        "insights": insights,
        "map_view": map_view,
        "has_geo": bool(grid_chart["data"]),
        "has_mean": bool(mean_rows),
        "has_names": bool(top_names),
        "labels": labels,
    }
