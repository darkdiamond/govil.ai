"""מספרי בתים ושמות הרחובות (באר שבע) — one row per marked house: CBS street
code, house number, optional letter/sub-number suffix, street name and a
WGS84 point.  The four resources (CSV, XLSX, and the same two with ITM
coordinates) are twins of one table; only the WGS84 CSV is read.

The page is about the street grid: how houses spread over streets, how
numbering behaves (parity, suffixes, outliers), where the houses sit and how
streets are oriented, plus how clean the register is.  Everything is a count,
a median or a min/max, so it does not depend on row order.
"""
import math
import re

import numpy as np
import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
KM_PER_DEG = 111.195
TOP_STREETS = 15
SIZE_BUCKETS = [(1, 5), (6, 10), (11, 20), (21, 40), (41, 80)]  # last = over 80
NUM_BUCKETS = [(1, 9), (10, 19), (20, 29), (30, 39), (40, 49), (50, 69), (70, 99)]  # last = 100+
TOP_LETTERS = 6
TOP_WORDS = 10
MIN_WORD_STREETS = 3
MAX_COLS = 24
BASE_CELL_KM = 0.5
RING_KM = 1
MAX_RINGS = 8
MIN_ORIENT_HOUSES = 5
MIN_ORIENT_KM = 0.15
MAX_SCATTER = 1500
HEAD_SHARE = 0.10
SMALL_STREET = 5
SMALL_SHARE_MIN = 0.05
PARITY_BALANCED_PP = 2.0
LETTER_MIN_SHARE = 0.005
OUTLIER_RATIO = 5
ORIENT_LEAD = 0.40
QUALITY_MIN_SHARE = 0.002
CENTER_KM = 2
CENTER_MIN_SHARE = 0.5
LONG_STREET_KM = 1.0
HEB_LETTER = re.compile(r"^[א-ת]$")
DIGITS = re.compile(r"^\d+$")


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _km(x):
    return f"{x:.1f}"


def _prepare(df):
    out = df.copy()
    for c in ("StreetCode", "HouseNuber", "streetName", "letter", "lat", "lon"):
        out[c] = out[c].str.strip()
    out["code"] = out["StreetCode"]
    out["num"] = pd.to_numeric(out["HouseNuber"], errors="coerce")
    out["latf"] = pd.to_numeric(out["lat"], errors="coerce")
    out["lonf"] = pd.to_numeric(out["lon"], errors="coerce")
    ok = (out["latf"].between(*LAT_RANGE) & out["lonf"].between(*LON_RANGE)
          & (out["num"] >= 1) & (out["streetName"] != ""))
    n_bad = int((~ok).sum())
    out = out[ok].copy()
    out["num"] = out["num"].astype(int)
    out["ident_street"] = ~((out["code"].isin(["0", ""])) & out["streetName"].str.match(DIGITS))
    return out, n_bad


def _street_table(df):
    """One row per street: key, main name, houses, extent_km, orientation."""
    s = df[df["ident_street"]].copy()
    s["key"] = np.where(s["code"].isin(["0", ""]), "n:" + s["streetName"], "c:" + s["code"])
    names = s.groupby(["key", "streetName"]).size().reset_index(name="c")
    names = names.sort_values(["key", "c", "streetName"], ascending=[True, False, True])
    main = names.drop_duplicates("key").set_index("key")["streetName"]
    g = s.groupby("key")
    t = pd.DataFrame({
        "name": main,
        "houses": g.size(),
        "latmin": g["latf"].min(), "latmax": g["latf"].max(),
        "lonmin": g["lonf"].min(), "lonmax": g["lonf"].max(),
    })
    t["code"] = [k[2:] if k.startswith("c:") else "" for k in t.index]
    lat0 = float(s["latf"].median())
    kx = KM_PER_DEG * math.cos(math.radians(lat0))
    t["dy"] = (t["latmax"] - t["latmin"]) * KM_PER_DEG
    t["dx"] = (t["lonmax"] - t["lonmin"]) * kx
    t["extent"] = np.hypot(t["dx"], t["dy"])
    t = t.reset_index().sort_values(["houses", "name", "key"], ascending=[False, True, True])
    return t.reset_index(drop=True), s


def _dedupe_labels(names, codes):
    seen = {}
    for n in names:
        seen[n] = seen.get(n, 0) + 1
    return [f"{n} ({c})" if seen[n] > 1 and c else n for n, c in zip(names, codes)]


def insight_top(t):
    if len(t) < 10:
        return None
    a, b = t.iloc[0], t.iloc[1]
    top10 = int(t["houses"].head(10).sum())
    total = int(t["houses"].sum())
    return (f"הרחוב עם מספר הבתים הגדול ביותר הוא {a['name']} עם {_int(a['houses'])} בתים, "
            f"אחריו {b['name']} עם {_int(b['houses'])}. עשרת הרחובות הגדולים מכילים "
            f"{_pct(top10 / total)} מכלל הבתים.")


def insight_concentration(t):
    n = len(t)
    if n < 20:
        return None
    k = max(1, int(math.ceil(n * HEAD_SHARE)))
    head = int(t["houses"].head(k).sum())
    total = int(t["houses"].sum())
    share = head / total
    if share <= HEAD_SHARE:
        return None
    return (f"{_pct(HEAD_SHARE, 0)} מהרחובות ({_int(k)} רחובות גדולים) מכילים "
            f"{_pct(share)} מהבתים המסומנים; חציון הרחובות הוא {_int(t['houses'].median())} בתים.")


def insight_small(t):
    n = len(t)
    if n < 20:
        return None
    small = int((t["houses"] <= SMALL_STREET).sum())
    if small / n < SMALL_SHARE_MIN:
        return None
    return (f"{_int(small)} רחובות ({_pct(small / n)}) מסומנים עם {_int(SMALL_STREET)} בתים או פחות, "
            f"ובהם {_int((t['houses'] == 1).sum())} עם בית אחד בלבד.")


def insight_parity(df):
    n = len(df)
    odd = int((df["num"] % 2 == 1).sum())
    even = n - odd
    diff = (odd - even) / n * 100
    if abs(diff) < PARITY_BALANCED_PP:
        return (f"חלוקת המספרים מאוזנת: {_pct(odd / n)} מספרים אי-זוגיים ו-{_pct(even / n)} זוגיים, "
                f"הפרש של {abs(diff):.1f} נקודות אחוז.")
    lead, share = ("אי-זוגיים", odd / n) if diff > 0 else ("זוגיים", even / n)
    return (f"מספרי הבתים {lead} בכ-{_pct(share)} מהרשומות "
            f"({_int(odd)} אי-זוגיים מול {_int(even)} זוגיים).")


def insight_letters(df, with_suffix, top_letter):
    n = len(df)
    if n == 0 or with_suffix / n < LETTER_MIN_SHARE:
        return None
    txt = f"{_int(with_suffix)} בתים ({_pct(with_suffix / n)}) נושאים סיומת למספר, אות או מספר משנה."
    if top_letter:
        txt += f" האות הנפוצה ביותר היא {top_letter[0]} ({_int(top_letter[1])} בתים)."
    return txt


def insight_outlier(df):
    q99 = float(df["num"].quantile(0.99))
    top = df.sort_values(["num", "streetName", "letter"], ascending=[False, True, True]).iloc[0]
    if q99 <= 0 or top["num"] < OUTLIER_RATIO * q99:
        return None
    cnt = int((df["num"] >= OUTLIER_RATIO * q99).sum())
    return (f"המספר הגבוה ביותר הוא {_int(top['num'])} ברחוב {top['streetName']}, "
            f"פי {top['num'] / q99:.0f} מהאחוזון ה-99 ({_int(q99)}); {_int(cnt)} רשומות חורגות כך "
            f"וייתכן שאינן מספר בית רגיל.")


def insight_center(within, total, center_km):
    share = within / total
    if share < CENTER_MIN_SHARE:
        return None
    return (f"{_pct(share)} מהבתים נמצאים עד {_int(center_km)} ק״מ מנקודת המרכז של הפריסה "
            f"({_int(within)} מתוך {_int(total)}).")


def insight_orient(counts, total):
    if total < 20:
        return None
    name, c = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if c / total < ORIENT_LEAD:
        return None
    return (f"הכיוון הנפוץ בין הרחובות הוא {name}: {_pct(c / total)} מהרחובות עם "
            f"{_int(MIN_ORIENT_HOUSES)} בתים ומעלה ({_int(c)} מתוך {_int(total)}).")


def insight_long(t):
    if t.empty:
        return None
    r = t.sort_values(["extent", "name", "key"], ascending=[False, True, True]).iloc[0]
    if r["extent"] < LONG_STREET_KM:
        return None
    return (f"הרחוב הארוך ביותר לפי פריסת הבתים הוא {r['name']}: כ-{_km(r['extent'])} ק״מ בין הבית "
            f"הראשון לאחרון, עם {_int(r['houses'])} בתים.")


def insight_quality(extra, identical, total):
    if extra / total < QUALITY_MIN_SHARE:
        return None
    txt = (f"ב-{_int(extra)} רשומות ({_pct(extra / total)}) הכתובת — רחוב, מספר ואות — "
           f"כבר הופיעה ברשומה אחרת")
    if identical:
        txt += f", ובהן {_int(identical)} כפילויות מלאות"
    return txt + "."


def compute(frames):
    df, n_bad = _prepare(frames["main"])
    total = len(df)
    t, s = _street_table(df)
    n_streets = len(t)

    # --- top streets
    top = t.head(TOP_STREETS)
    top_labels = _dedupe_labels(list(top["name"]), list(top["code"]))
    top_chart = {"names": top_labels, "values": [int(v) for v in top["houses"]]}
    t_top = [{"rank": i + 1, "name": n, "count": _int(v), "share": _pct(v / total)}
             for i, (n, v) in enumerate(zip(top_labels, top["houses"]))]

    # --- street size distribution
    sizes = []
    for lo, hi in SIZE_BUCKETS:
        sizes.append((str(lo) if lo == hi else f"{lo}-{hi}", int(((t["houses"] >= lo) & (t["houses"] <= hi)).sum())))
    over = SIZE_BUCKETS[-1][1]
    sizes.append((f"‎{over + 1}+", int((t["houses"] > over).sum())))
    size_chart = {"names": [a for a, _ in sizes], "values": [b for _, b in sizes]}
    t_size = [{"name": a, "count": _int(b), "share": _pct(b / n_streets)} for a, b in sizes]

    # --- house-number buckets by parity
    odd_m = df["num"] % 2 == 1
    nb_names, nb_odd, nb_even = [], [], []
    for lo, hi in NUM_BUCKETS:
        m = (df["num"] >= lo) & (df["num"] <= hi)
        nb_names.append(f"{lo}-{hi}")
        nb_odd.append(int((m & odd_m).sum()))
        nb_even.append(int((m & ~odd_m).sum()))
    over_n = NUM_BUCKETS[-1][1]
    m = df["num"] > over_n
    nb_names.append(f"‎{over_n + 1}+")
    nb_odd.append(int((m & odd_m).sum()))
    nb_even.append(int((m & ~odd_m).sum()))
    num_chart = {"names": nb_names, "odd": nb_odd, "even": nb_even}
    t_num = [{"name": n, "odd": _int(o), "even": _int(e), "total": _int(o + e)}
             for n, o, e in zip(nb_names, nb_odd, nb_even)]
    n_odd = int(odd_m.sum())

    # --- suffixes
    lt = df["letter"]
    suffixed = lt != ""
    with_suffix = int(suffixed.sum())
    letter_counts = lt[lt.map(lambda v: bool(HEB_LETTER.match(v)))].value_counts()
    letters = sorted(((k, int(v)) for k, v in letter_counts.items()), key=lambda kv: (-kv[1], kv[0]))
    shown = letters[:TOP_LETTERS]
    rest_letters = sum(v for _, v in letters[TOP_LETTERS:])
    slash = int(lt.str.startswith("/").sum())
    other = with_suffix - sum(v for _, v in letters) - slash
    suf = [(f"אות {k}", v) for k, v in shown]
    if rest_letters:
        suf.append(("אותיות אחרות", rest_letters))
    if slash:
        suf.append(("מספר משנה (לוכסן)", slash))
    if other > 0:
        suf.append(("סיומת אחרת", other))
    suf_chart = {"names": [a for a, _ in suf], "values": [b for _, b in suf]}
    t_suf = [{"name": a, "count": _int(b), "share": _pct(b / with_suffix)} for a, b in suf] if with_suffix else []

    # --- first word of street name
    t["first"] = t["name"].str.split().str[0]
    fw = t.groupby("first").agg(streets=("key", "size"), houses=("houses", "sum")).reset_index()
    fw = fw[fw["streets"] >= MIN_WORD_STREETS]
    fw = fw.sort_values(["streets", "houses", "first"], ascending=[False, False, True]).head(TOP_WORDS)
    word_chart = {"names": list(fw["first"]), "values": [int(v) for v in fw["streets"]]}
    t_word = [{"name": a, "streets": _int(b), "houses": _int(c)}
              for a, b, c in zip(fw["first"], fw["streets"], fw["houses"])]

    # --- geography: grid, rings (all houses)
    lat0 = float(df["latf"].median())
    lon0 = float(df["lonf"].median())
    kx = KM_PER_DEG * math.cos(math.radians(lat0))
    y_km = (df["latf"] - df["latf"].min()) * KM_PER_DEG
    x_km = (df["lonf"] - df["lonf"].min()) * kx
    span = max(float(x_km.max()), float(y_km.max()), 0.01)
    cell = BASE_CELL_KM * max(1, math.ceil(span / BASE_CELL_KM / MAX_COLS))
    cx = (x_km // cell).astype(int)
    cy = (y_km // cell).astype(int)
    cells = pd.DataFrame({"x": cx, "y": cy}).groupby(["x", "y"]).size().reset_index(name="c")
    nx, ny = int(cx.max()) + 1, int(cy.max()) + 1
    grid_chart = {
        "x": [_km(i * cell) for i in range(nx)],
        "y": [_km(j * cell) for j in range(ny)],
        "data": [[int(r.x), int(r.y), int(r.c)] for r in cells.itertuples()],
        "max": int(cells["c"].max()),
    }
    topcell = cells.sort_values(["c", "x", "y"], ascending=[False, True, True]).iloc[0]

    dist = np.hypot((df["lonf"] - lon0) * kx, (df["latf"] - lat0) * KM_PER_DEG)
    rings = []
    for k in range(MAX_RINGS):
        m = (dist >= k * RING_KM) & (dist < (k + 1) * RING_KM)
        rings.append((f"{k * RING_KM}-{(k + 1) * RING_KM}", int(m.sum())))
    tail = int((dist >= MAX_RINGS * RING_KM).sum())
    rings.append((f"‎{MAX_RINGS * RING_KM}+", tail))
    while len(rings) > 2 and rings[-1][1] == 0:
        rings.pop()
    ring_chart = {"names": [a for a, _ in rings], "values": [b for _, b in rings]}
    t_ring = [{"name": a, "count": _int(b), "share": _pct(b / total)} for a, b in rings]
    within = int((dist < CENTER_KM).sum())

    # --- orientation + street length vs size
    od = t[(t["houses"] >= MIN_ORIENT_HOUSES) & (t["extent"] >= MIN_ORIENT_KM)]
    ns = int((od["dy"] >= 2 * od["dx"]).sum())
    ew = int((od["dx"] >= 2 * od["dy"]).sum())
    diag = len(od) - ns - ew
    orient = [("צפון-דרום", ns), ("מזרח-מערב", ew), ("אלכסוני", diag)]
    orient_counts = dict(orient)
    orient_chart = {"names": [a for a, _ in orient], "values": [b for _, b in orient]}
    t_orient = [{"name": a, "count": _int(b), "share": _pct(b / len(od)) if len(od) else "0.0%"}
                for a, b in orient]
    sc = t.head(MAX_SCATTER)
    scatter_chart = {"data": [[round(float(e), 2), int(h), n] for e, h, n in
                              zip(sc["extent"], sc["houses"], sc["name"])]}

    # --- register quality
    addr_extra = int(df.duplicated(["code", "num", "letter"]).sum())
    identical = int(df.duplicated(["code", "num", "letter", "streetName", "lat", "lon"]).sum())
    ns_ = df[df["ident_street"] & ~df["code"].isin(["0", ""])]
    nm = ns_.groupby(["code", "streetName"]).size().reset_index(name="c")
    nm = nm.sort_values(["code", "c", "streetName"], ascending=[True, False, True])
    main_nm = nm.drop_duplicates("code").set_index("code")["streetName"]
    alt_spell = int((ns_["streetName"] != ns_["code"].map(main_nm)).sum())
    nocode = int((~df["ident_street"]).sum())
    qual = [("כתובת שחוזרת", addr_extra),
            ("כפילות מלאה", identical),
            ("כתיב שונה לקוד", alt_spell),
            ("ללא קוד רחוב", nocode),
            ("נשמטו (לא תקין)", n_bad)]
    qual_chart = {"names": [a for a, _ in qual], "values": [b for _, b in qual],
                  "pct": [round(b / (total + n_bad) * 100, 2) for _, b in qual]}
    t_qual = [{"name": a, "count": _int(b), "share": _pct(b / (total + n_bad), 2)} for a, b in qual]

    # --- insights
    top_letter = shown[0] if shown else None
    cands = [
        ("top", insight_top(t)),
        ("concentration", insight_concentration(t)),
        ("small", insight_small(t)),
        ("parity", insight_parity(df)),
        ("letters", insight_letters(df, with_suffix, top_letter)),
        ("outlier", insight_outlier(df)),
        ("center", insight_center(within, total, CENTER_KM)),
        ("orient", insight_orient(orient_counts, len(od))),
        ("long", insight_long(t)),
        ("quality", insight_quality(addr_extra, identical, total)),
    ]
    insights = [{"id": i, "text_he": x} for i, x in cands if x]

    med = float(t["houses"].median())
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand",
                  "label": "בתים מסומנים"},
        "streets": {"value": n_streets, "display": _int(n_streets), "tone": "brand",
                    "label": "רחובות"},
        "median": {"value": med, "display": f"{med:g}", "tone": "brand",
                   "label": "חציון בתים לרחוב"},
        "repeat": {"value": addr_extra, "display": _int(addr_extra),
                   "tone": "warn" if addr_extra / total >= QUALITY_MIN_SHARE * 5 else "ok",
                   "label": "כתובות שחוזרות ברשומות נוספות"},
    }

    ls = len(letters)
    labels = {
        "lede": (f"{_int(total)} בתים בבאר שבע, כל אחד עם מספר, שם רחוב וקוד רחוב של הלמ״ס ונקודה על המפה. "
                 f"הם פרושים על {_int(n_streets)} רחובות, וחציון הרחובות כולל {med:g} בתים."),
        "map_note": "כל נקודה היא בית מסומן; לחיצה על נקודה מציגה את הרחוב והמספר.",
        "top_note": f"{_int(len(top))} הרחובות עם מספר הבתים המסומנים הגדול ביותר.",
        "top_aria": f"תרשים עמודות אופקיות: {_int(len(top))} הרחובות עם הכי הרבה בתים, מ{top_labels[0]} עם {_int(top['houses'].iloc[0])} בתים.",
        "top_caption": "הרחובות הגדולים ביותר לפי מספר בתים.",
        "size_note": "כמה רחובות יש בכל טווח של גודל, לפי מספר הבתים המסומנים ברחוב.",
        "size_aria": f"תרשים עמודות: מספר הרחובות לפי גודל, {_int(len(sizes))} קבוצות.",
        "size_caption": "מספר הרחובות לפי טווח מספר הבתים.",
        "num_note": "התפלגות מספרי הבתים לפי טווח, עם פיצול בין מספרים אי-זוגיים וזוגיים.",
        "num_aria": f"תרשים עמודות מוערמות: מספרי בתים לפי טווח ולפי זוגיות, {_int(len(nb_names))} טווחים.",
        "num_caption": "מספר הבתים לפי טווח המספר וזוגיותו.",
        "suf_note": f"{_int(with_suffix)} בתים עם סיומת למספר, לפי סוג הסיומת.",
        "suf_aria": f"תרשים עמודות: סוגי הסיומות למספר הבית, {_int(len(suf))} סוגים.",
        "suf_caption": "מספר הבתים לפי סוג הסיומת.",
        "word_note": f"המילים הראשונות הנפוצות בשמות הרחובות, בין אלה שפותחות לפחות {_int(MIN_WORD_STREETS)} רחובות.",
        "word_aria": f"תרשים עמודות אופקיות: מספר הרחובות לפי המילה הראשונה בשם, {_int(len(fw))} מילים.",
        "word_caption": "מספר הרחובות ומספר הבתים לפי המילה הראשונה בשם הרחוב.",
        "grid_note": f"צפיפות הבתים לפי משבצות של {_km(cell)} ק״מ; הצירים מציגים מרחק בק״מ מהפינה הדרום-מערבית של הפריסה.",
        "grid_aria": f"מפת חום: מספר הבתים בכל משבצת, {_int(len(cells))} משבצות מאוכלסות.",
        "ring_note": f"מספר הבתים לפי מרחק מנקודת המרכז של הפריסה, בטבעות של {_int(RING_KM)} ק״מ.",
        "ring_aria": f"תרשים עמודות: מספר הבתים לפי מרחק מהמרכז, {_int(len(rings))} טבעות.",
        "ring_caption": "מספר הבתים לפי מרחק (ק״מ) מנקודת המרכז.",
        "orient_note": f"כיוון כל רחוב לפי מיקום הבית הראשון והאחרון בו, לרחובות עם {_int(MIN_ORIENT_HOUSES)} בתים ומעלה; רחוב נספר כצפון-דרום או מזרח-מערב כשאורכו בציר אחד לפחות כפול מאורכו בציר השני, ואחרת כאלכסוני.",
        "orient_aria": f"תרשים עמודות: מספר הרחובות לפי כיוון, {_int(len(od))} רחובות.",
        "orient_caption": "מספר הרחובות לפי כיוון עיקרי.",
        "scatter_note": "כל נקודה היא רחוב: הציר האופקי הוא אורך הפריסה בק״מ, והאנכי מספר הבתים.",
        "scatter_aria": f"תרשים פיזור: אורך פריסה מול מספר בתים, {_int(len(sc))} רחובות.",
        "qual_note": "ספירת רשומות חריגות: כתובת (רחוב, מספר ואות) שחוזרת ברשומה נוספת, מהן כפילות מלאה כולל הנקודה, כתיב שונה לאותו קוד רחוב, רשומה עם שם מספרי וללא קוד, ורשומות שנשמטו מהניתוח.",
        "qual_aria": f"תרשים עמודות אופקיות: {_int(len(qual))} בדיקות איכות על הרשומות.",
        "qual_caption": "בדיקות איכות לפי מספר רשומות.",
    }

    return {
        "agent_data": {
            "summary_he": (f"{_int(total)} בתים מסומנים בבאר שבע על פני {_int(n_streets)} רחובות, "
                           f"עם חציון של {med:g} בתים לרחוב. מפה, צפיפות לפי אזור, מספור ואיכות הרישום."),
            "dataset_kind": "map",
            "suggested_tags": ["באר שבע", "רחובות", "כתובות", "מספרי בתים", "מפה"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["82a30a97-01b0-4281-854c-c7931f3445c0",
                            "bdf28cc0-680a-415c-af64-944a58079b2f",
                            "7edbd028-9704-440c-a1b6-a0ed566081bc",
                            "5944b454-751c-4604-94d6-e676d7d34612",
                            "3c6d4061-41bf-4403-82e9-c8fae5df04dd"],
        },
        "kpis": kpis,
        "charts": {"top": top_chart, "size": size_chart, "num": num_chart, "suf": suf_chart,
                   "word": word_chart, "grid": grid_chart, "ring": ring_chart,
                   "orient": orient_chart, "scatter": scatter_chart, "qual": qual_chart},
        "tables": {"top": t_top, "size": t_size, "num": t_num, "suf": t_suf, "word": t_word,
                   "ring": t_ring, "orient": t_orient, "qual": t_qual},
        "insights": insights,
        "has_suf": bool(with_suffix),
        "has_word": bool(len(fw)),
        "has_orient": bool(len(od)),
        "labels": labels,
    }
