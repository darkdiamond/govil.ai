"""אתרי טבע עירוני (באר שבע) — one row per surveyed nature site: a free-text
description (MainFeatur) and a WGS84 point.  The description is classified
into a handful of site types by an ordered keyword lexicon (first match wins,
fallback "אחר"), named species are counted by keyword, and the points are
spread over latitude/longitude bands and a coarse grid.

Order-independent: counts, medians and sorted / fsum aggregates only.
"""
import math
import re

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
R_KM = 6371.0088
TOP_SPECIES = 14
MIN_SPECIES = 3            # a species needs this many sites to be charted
MAX_BANDS = 12
GRID_DEG = 0.02            # ~2 km cell
MAX_GRID = 8               # cells per axis, widened if the span grows
TOP_PATCHES = 8
MIN_PATCHES = 4
LEAD_MARGIN = 0.05
TOP_SHARE = 0.5
SHIFT_MIN_KM = 1.0
SHIFT_MIN_SITES = 15
HOT_SHARE = 0.10
OTHER_MAX_SHARE = 0.5      # lede notes unclassified share only if it is big

W = r"(?<![א-ת])[ובהלשמכ]{0,2}"   # Hebrew word start, tolerating prefix letters

# Ordered: the first category whose pattern matches the description wins.
CATEGORIES = [
    ("מים ובורות", re.compile(
        W + r"(מאגור|בור(?![א-ת])|בורות|באר(?! שבע)(?![א-ת])|בריכ|שלולית|אגם|מעביר(ים)? מים|"
        r"גב(ים|י מים)|נקז|זרימ|סכר|נקודת שחרור|פתחי ניקוז)")),
    ("מורשת ושרידים", re.compile(
        W + r"(ארכיאולוג|שרידי|תל(?![א-ת])|מוצב|תעלות|תעלה|ביזנט|חווה ביזנטית|חרבת|אנדרטה|מבנה|"
        r"טרא?סה|טרסות|חלקות בעל|דרך עתיקה|כבשן|בור סיד|גשר|מסילת|בית ארבעת|גינה קהילתית|"
        r"מגדלים פיסוליים|מטוס|גל אבנים|מעגל אבנים|חפירה|חפירות|הוקם|מחפורת|קיר מלאכותי|"
        r"מבתר|גדר חיה)")),
    ("בעלי חיים ומחילות", re.compile(
        W + r"(קינון|קינון|מקנן|קן(?![א-ת])|מאור|מחילות|מחילה|מערה|מערות|כוך|עופות|"
        r"זוחלים|יונקים|דרבנ|חרדונים|פרפרים|ציפורים|אנפיות|לטאה|קרפדה|ראשנים)")),
    ("מחשופים ונוף", re.compile(
        W + r"(מחשוף|מחשופי|מחצב|מצוק|סלע|סלעים|בולדרים|מסלעה|לס(?![א-ת])|בתרון|בתרונות|"
        r"קירטון|קירטוני|קיר עפר|קירות עפר|תלכיד|ערוץ|רוץ|תצפית|פסגה|פסגת|גבעה|משטח|משטחי|"
        r"גב(?![א-ת])|מדרון|שקע|לימן|משיין|חתך גיאולוגי|מצוקון)")),
    ("עצים וחורשות", re.compile(
        W + r"(עץ|עצי|עצים|חורשה|חורשת|שדרת|שיזף|שיזפים|שיטה|שיטים|אשל(?![א-ת])|אשלים|חרוב|חרובים|"
        r"דקל|תמר|וושינגטוני|אקליפטוס|אורן|אורנים|ברוש|פיקוס|תאנה|שקמה|זית|אלת|אשחר)")),
    ("פריחה וצמחיית בר", re.compile(
        W + r"(ריכוז|כתם|מקבץ|כלנ|צבעוני|אירוס|שום|קדד|עדעד|שמשון|עירית|סתוונית|שלהבית|"
        r"זמזומי|נורית|נוריות|קורנית|צמר|מלוח|אטד|רותם|יפרוק|חצב|חבלבל|פריחה|גיאופיטים|גאופיטים|"
        r"שיחי|שיח(?![א-ת])|פגוניה|ציפורן|מתנן|רכפתן|סייפני|חמד|לענת|קנים|חישת|אכיליאה|"
        r"גלונית|עכובית|שיכרון|סירה|נץ-חלב|בן-חצב|זהביות|שיחיית|מצילות|פשתנית|כחלית|"
        r"ערטנית|טבק|סומקן|קרדריה|צמחי|צמחיית|צמחייה|צהרון|ינבוט|וושינגטוניה|חלקה|שיחני|זוגן|בוצין|סתוונ)")),
]
OTHER = "אחר"

SPECIES = [
    ("שיזף מצוי", W + r"שיזף"),
    ("שיטה סלילנית", W + r"(עץ )?(שיטה|שיטים|שיטות) סלילני|שיטה סלילנית"),
    ("אשל", W + r"אשל(?![א-ת])|" + W + r"אשלים"),
    ("אירוס שחום", W + r"אירוס"),
    ("כלניות", W + r"כלני"),
    ("צבעונים", W + r"צבעוני"),
    ("שום", W + r"שום(?![א-ת])"),
    ("קדד", W + r"קדד"),
    ("עדעד המדבר", W + r"עדעד"),
    ("שמשון הדור", W + r"שמשון"),
    ("עירית גדולה", W + r"עירית"),
    ("סתוונית הנגב", W + r"סתוונ"),
    ("שלהבית קיצרת-שיניים", W + r"שלהבית"),
    ("זמזומית", W + r"זמזומ"),
    ("נורית אסיה", W + r"נורית|" + W + r"נוריות"),
    ("קורנית מקורקפת", W + r"קורנית"),
    ("צמר מפוצל", W + r"צמר מפוצל"),
    ("מלוח קיפח", W + r"מלוח"),
    ("אטד", W + r"אטד"),
    ("רותם המדבר", W + r"רותם"),
    ("חרוב", W + r"חרוב"),
    ("דקל / תמר", W + r"(דקל|תמר)"),
    ("וושינגטוניה", W + r"וושינגטוני"),
    ("אקליפטוס", W + r"אקליפטוס"),
    ("אורן", W + r"אורנ|" + W + r"אורן"),
    ("תאנה / פיקוס", W + r"(תאנ|פיקוס)"),
    ("יפרוק", W + r"יפרוק"),
    ("חצב", W + r"חצב"),
]
SPECIES = [(n, re.compile(p)) for n, p in SPECIES]
DIM_RE = re.compile(r"(\d+)\s*על\s*(\d+)\s*מטר")


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _ranked(counts):
    """dict -> [(name, n)] sorted by count desc then name (total order)."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _prepare(df):
    out = df.copy()
    out["name"] = out["MainFeatur"].str.strip()
    out["latf"] = pd.to_numeric(out["lat"].str.strip(), errors="coerce")
    out["lonf"] = pd.to_numeric(out["lon"].str.strip(), errors="coerce")
    ok = (out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
          & (out["name"] != ""))
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    out["cat"] = out["name"].map(_category)
    out = out.sort_values(["name", "latf", "lonf"], kind="stable")
    return out.reset_index(drop=True), n_bad


def _category(text):
    for name, rx in CATEGORIES:
        if rx.search(text):
            return name
    return OTHER


def _bands(values, scale=100):
    """Equal-width degree bands -> (edges list [(lo, hi)], idx array)."""
    idx = np.floor(np.asarray(values) * scale + 1e-9).astype(int)
    lo, hi = int(idx.min()), int(idx.max())
    w = max(1, math.ceil((hi - lo + 1) / MAX_BANDS))
    lo = (lo // w) * w
    edges = [(a, a + w) for a in range(lo, hi + 1, w)]
    return edges, idx


def _band_label(a, b, scale=100):
    return f"{a / scale:.2f}-{b / scale:.2f}"


def _stack_by_band(df, col, cats, reverse):
    edges, idx = _bands(df[col].to_numpy())
    cat_arr = df["cat"].to_numpy()
    rows = []
    for a, b in edges:
        m = (idx >= a) & (idx < b)
        rows.append((_band_label(a, b), {c: int(((cat_arr == c) & m).sum()) for c in cats},
                     int(m.sum())))
    if reverse:
        rows = rows[::-1]
    return {
        "names": [r[0] for r in rows],
        "series": [{"name": c, "data": [r[1][c] for r in rows]} for c in cats],
    }, [{"name": r[0], "total": _int(r[2]),
         **{f"c{i}": _int(r[1][c]) for i, c in enumerate(cats)}} for r in rows]


def _grid(df):
    lat = df["latf"].to_numpy()
    lon = df["lonf"].to_numpy()
    step = GRID_DEG
    while (math.ceil((lat.max() - lat.min()) / step + 1e-9) > MAX_GRID
           or math.ceil((lon.max() - lon.min()) / step + 1e-9) > MAX_GRID):
        step *= 2
    lat0 = math.floor(lat.min() / step + 1e-9) * step
    lon0 = math.floor(lon.min() / step + 1e-9) * step
    yi = np.floor((lat - lat0) / step + 1e-9).astype(int)
    xi = np.floor((lon - lon0) / step + 1e-9).astype(int)
    ny, nx = int(yi.max()) + 1, int(xi.max()) + 1
    cells = np.zeros((ny, nx), dtype=int)
    for y, x in zip(yi, xi):
        cells[y, x] += 1
    xs = [f"{lon0 + i * step:.2f}" for i in range(nx)]
    ys = [f"{lat0 + j * step:.2f}" for j in range(ny)]
    data = [[i, j, int(cells[j, i])] for j in range(ny) for i in range(nx)]
    return {"x": xs, "y": ys, "data": data, "max": int(cells.max())}, cells, (lat0, lon0, step)


def _patches(df):
    """Sites that state a size ("20 על 50 מטר") -> (area m2, w, h, text)."""
    rows = []
    for t in df["name"]:
        m = DIM_RE.search(t)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            rows.append((w * h, w, h, t))
    return rows


def _patch_label(r):
    t = DIM_RE.sub("", r[3])
    t = re.sub(r"^ריכוז\s+|גיאופיטים-?\s*|גאופיטים-?\s*", "", t)
    t = re.sub(r"[\s,.\-–]+$", "", re.sub(r"\s+", " ", t)).strip()
    return f"{r[1]}×{r[2]} {_short(t, 22)}"


def _short(t, n=48):
    t = re.sub(r"\s+", " ", t)
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def insight_leader(cats, total):
    if len(cats) < 2:
        return None
    (a, na), (b, nb) = cats[0], cats[1]
    if (na - nb) / total < LEAD_MARGIN:
        return None
    return (f"סוג האתר השכיח ביותר הוא ״{a}״ עם {_int(na)} אתרים "
            f"({_pct(na / total, 1)}), לעומת {_int(nb)} ב״{b}״.")


def insight_concentration(species, total):
    if len(species) < 3:
        return None
    top = species[:3]
    s = sum(n for _, n in top)
    if s / total < 0.2:
        return None
    names = ", ".join(n for n, _ in top)
    return (f"שלושת המינים המוזכרים ביותר ({names}) מופיעים בתיאור של {_int(s)} אתרים "
            f"(סכום הזכרות, ייתכנו כמה מינים באתר אחד).")


def insight_flora(cats, total):
    d = dict(cats)
    f = d.get("פריחה וצמחיית בר", 0) + d.get("עצים וחורשות", 0)
    if f / total < TOP_SHARE:
        return None
    return (f"{_pct(f / total)} מהאתרים ({_int(f)}) מתמקדים בצמחייה: פריחה וצמחיית בר "
            f"או עצים וחורשות.")


def insight_species_top(species):
    if not species or species[0][1] < MIN_SPECIES:
        return None
    n, c = species[0]
    return f"המין המוזכר ביותר בתיאורי האתרים הוא {n}: הוא מופיע ב-{_int(c)} אתרים."


def insight_patch(patches):
    if len(patches) < MIN_PATCHES:
        return None
    best = sorted(patches, key=lambda r: (-r[0], r[3]))[0]
    km2 = best[0] / 1e6
    area = (f"{km2:.2f} קמ״ר" if best[0] >= 1_000_000 else f"{_int(best[0])} מ״ר")
    return (f"מתוך {_int(len(patches))} אתרים שמצוין להם גודל, הגדול ביותר הוא "
            f"״{_short(best[3], 70)}״ — כ-{area} ({_int(best[1])} על {_int(best[2])} מטרים).")


def insight_shift(df, cats, mlat, mlon):
    best = None
    k = math.cos(math.radians(mlat))
    for c, n in cats:
        if c == OTHER or n < SHIFT_MIN_SITES:
            continue
        g = df[df["cat"] == c]
        dy = (float(g["latf"].median()) - mlat) * math.radians(1) * R_KM
        dx = (float(g["lonf"].median()) - mlon) * math.radians(1) * R_KM * k
        r = math.hypot(dx, dy)
        if r >= SHIFT_MIN_KM and (best is None or r > best[0]):
            best = (r, c, n, dx, dy)
    if not best:
        return None
    r, c, n, dx, dy = best
    ns = "צפונית" if dy > 0 else "דרומית"
    ew = "מזרחית" if dx > 0 else "מערבית"
    parts = []
    if abs(dy) >= 0.5:
        parts.append(f"{abs(dy):.1f} ק״מ {ns}")
    if abs(dx) >= 0.5:
        parts.append(f"{abs(dx):.1f} ק״מ {ew}")
    return (f"אתרי ״{c}״ ({_int(n)}) מוסטים ביחס לכלל האתרים: מרכזם " + " ו-".join(parts)
            + " למרכז כלל האתרים.")


def insight_hot(cells, geo, total):
    top = int(cells.max())
    if top / total < HOT_SHARE:
        return None
    j, i = np.unravel_index(int(np.argmax(cells)), cells.shape)
    lat0, lon0, step = geo
    return (f"התא הצפוף ביותר ברשת (קו רוחב {lat0 + j * step:.2f}, קו אורך {lon0 + i * step:.2f}) "
            f"מכיל {_int(top)} אתרים, {_pct(top / total)} מכלל האתרים.")


def insight_repeat(df):
    vc = df["name"].value_counts()
    vc = vc[vc >= 2]
    if vc.empty:
        return None
    dup_rows = int(vc.sum())
    return (f"{_int(len(vc))} תיאורים חוזרים ביותר מאתר אחד ומכסים {_int(dup_rows)} אתרים; "
            f"כל אחד מהם מסומן בנקודה נפרדת.")


def compute(frames):
    df, n_bad = _prepare(frames["sites"])
    total = len(df)
    mlat = float(np.median(df["latf"]))
    mlon = float(np.median(df["lonf"]))

    cat_counts = {}
    for c in df["cat"]:
        cat_counts[c] = cat_counts.get(c, 0) + 1
    cats = _ranked(cat_counts)
    # "אחר" always last
    cats = [x for x in cats if x[0] != OTHER] + [x for x in cats if x[0] == OTHER]
    cat_names = [c for c, _ in cats]

    sp_counts = {}
    for name, rx in SPECIES:
        n = int(df["name"].map(lambda t: bool(rx.search(t))).sum())
        if n >= MIN_SPECIES:
            sp_counts[name] = n
    species = _ranked(sp_counts)
    top_sp = species[:TOP_SPECIES]

    lat_chart, t_lat = _stack_by_band(df, "latf", cat_names, reverse=True)
    lon_chart, t_lon = _stack_by_band(df, "lonf", cat_names, reverse=False)
    grid, cells, geo = _grid(df)
    patches = _patches(df)
    top_patches = sorted(patches, key=lambda r: (-r[0], r[3]))[:TOP_PATCHES]
    patch_chart = {"names": [_patch_label(r) for r in top_patches],
                   "values": [r[0] for r in top_patches]}
    t_patch = [{"name": _short(r[3], 70), "size": f"{_int(r[1])} על {_int(r[2])}",
                "area": _int(r[0])} for r in top_patches]

    other_n = cat_counts.get(OTHER, 0)
    ns_km = float((df["latf"].max() - df["latf"].min()) * math.radians(1) * R_KM)
    ew_km = float((df["lonf"].max() - df["lonf"].min()) * math.radians(1) * R_KM
                  * math.cos(math.radians(mlat)))
    distinct = int(df["name"].nunique())
    rep_share = 1 - distinct / total

    rules = [
        ("leader", insight_leader(cats, total)),
        ("flora", insight_flora(cats, total)),
        ("species", insight_species_top(species)),
        ("concentration", insight_concentration(species, total)),
        ("patch", insight_patch(patches)),
        ("shift", insight_shift(df, cats, mlat, mlon)),
        ("hot", insight_hot(cells, geo, total)),
        ("repeat", insight_repeat(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    kpis = {
        "total": {"display": _int(total), "tone": "brand", "label": "אתרי טבע במפה"},
        "cats": {"display": _int(len([c for c in cats if c[0] != OTHER])), "tone": "brand",
                 "label": "סוגי אתרים"},
        "species": {"display": _int(len(species)), "tone": "brand",
                    "label": "מינים שמוזכרים ב-3 אתרים או יותר" if MIN_SPECIES == 3 else "מינים"},
        "extent": {"display": f"{ns_km:.1f}", "tone": "info",
                   "label": f"ק״מ מצפון לדרום (ממערב למזרח: {ew_km:.1f})"},
    }
    for k in kpis.values():
        k["value"] = k["display"]

    bad_note = (f" {_int(n_bad)} רשומות בלי תיאור או בלי קואורדינטות תקינות לא נכללו."
                if n_bad else "")
    other_note = (f" {_int(other_n)} אתרים ({_pct(other_n / total)}) לא שויכו לסוג מוגדר."
                  if other_n / total >= 0.05 else "")
    labels = {
        "lede": (f"{_int(total)} נקודות שסומנו בסקר טבע עירוני בבאר שבע ובסביבתה, כל אחת עם תיאור "
                 f"חופשי של המאפיין העיקרי באתר ונקודת מיקום. התיאורים מסווגים לסוגי אתרים לפי "
                 f"מילות מפתח, והמינים שמוזכרים בהם נספרים. יש {_int(distinct)} תיאורים שונים; "
                 f"תיאורים זהים סומנו במקומות שונים.{other_note}{bad_note}"),
        "map_note": (f"{_int(total)} האתרים על המפה. לחצו על סמן כדי לקרוא את תיאור האתר; "
                     f"לחצו על אשכול כדי להתקרב."),
        "cat_note": ("מספר האתרים בכל סוג. כל אתר משויך לסוג אחד: הראשון שמתאים לתיאורו "
                     "לפי סדר קבוע (מים, מורשת, בעלי חיים, מחשופים ונוף, עצים, פריחה)."),
        "cat_aria": f"תרשים עמודות אופקי: מספר האתרים לפי סוג, {len(cats)} סוגים.",
        "cat_caption": "מספר האתרים לפי סוג אתר.",
        "species_note": (f"בכמה אתרים מוזכר כל מין בתיאור (הצגת {_int(len(top_sp))} המינים "
                         f"המוזכרים ביותר). אתר יכול להזכיר כמה מינים."),
        "species_aria": f"תרשים עמודות אופקי: מספר האתרים שמזכירים כל מין, {len(top_sp)} מינים.",
        "species_caption": "מספר האתרים שמזכירים כל מין.",
        "lat_note": "סוגי האתרים בכל רצועת קו רוחב, מהצפון (למעלה) לדרום.",
        "lat_aria": f"תרשים עמודות מוערם: סוגי אתרים לפי {len(lat_chart['names'])} רצועות קו רוחב.",
        "lat_caption": "מספר האתרים לפי רצועת קו רוחב וסוג.",
        "lon_note": "סוגי האתרים בכל רצועת קו אורך, ממערב (למעלה) למזרח.",
        "lon_aria": f"תרשים עמודות מוערם: סוגי אתרים לפי {len(lon_chart['names'])} רצועות קו אורך.",
        "lon_caption": "מספר האתרים לפי רצועת קו אורך וסוג.",
        "grid_note": (f"מספר האתרים בכל תא ברשת של כ-{GRID_DEG * 111:.0f} ק״מ. "
                      f"הצבע החזק מסמן ריכוז גבוה."),
        "grid_aria": (f"מפת חום: מספר האתרים בכל תא ברשת קווי רוחב ואורך, "
                      f"{len(grid['y'])} על {len(grid['x'])} תאים."),
        "patch_note": ("אתרים שהתיאור שלהם כולל מידות (״X על Y מטר״), לפי שטח משוער: "
                       "רוחב כפול אורך."),
        "patch_aria": f"תרשים עמודות אופקי: {len(top_patches)} האתרים הגדולים ביותר לפי שטח במ״ר.",
        "patch_caption": "האתרים הגדולים ביותר לפי השטח המשוער.",
    }
    cat_cols = [{"i": i, "name": c} for i, c in enumerate(cat_names)]
    t_cat = [{"name": c, "count": _int(n), "share": _pct(n / total, 1)} for c, n in cats]
    t_sp = [{"name": n, "count": _int(c), "share": _pct(c / total, 1)} for n, c in top_sp]

    return {
        "agent_data": {
            "summary_he": (f"מפת {_int(total)} אתרי טבע עירוני בבאר שבע לפי סקר, מסווגים ל-"
                           f"{_int(len(cats))} סוגי אתרים, עם ספירת המינים המוזכרים והתפלגות "
                           f"גיאוגרפית."),
            "dataset_kind": "map",
            "suggested_tags": ["טבע עירוני", "באר שבע", "סקר טבע", "אתרי טבע", "גיאוגרפיה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["5944b454-751c-4604-94d6-e676d7d34612",
                            "82a30a97-01b0-4281-854c-c7931f3445c0"],
        },
        "kpis": kpis,
        "charts": {
            "cat": {"names": [c for c, _ in cats], "values": [n for _, n in cats]},
            "species": {"names": [n for n, _ in top_sp], "values": [c for _, c in top_sp]},
            "lat": lat_chart, "lon": lon_chart, "grid": grid, "patch": patch_chart,
        },
        "tables": {"cat": t_cat, "species": t_sp, "lat": t_lat, "lon": t_lon,
                   "patch": t_patch},
        "cat_cols": cat_cols,
        "insights": insights,
        "has_species": bool(top_sp),
        "has_patch": len(patches) >= MIN_PATCHES,
        "labels": labels,
    }
