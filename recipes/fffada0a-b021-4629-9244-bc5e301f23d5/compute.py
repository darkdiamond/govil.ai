"""התו הסגול בבאר שבע: one row per business that declared it meets the
Purple Badge (תו סגול) rules: business name, street (free text, often with a
house number or a shopping-centre name inside it), house number, ITM X/Y
(zero on part of the rows), a fixed disclaimer note and a WGS84 point.

The page asks: where are the businesses (shared points = shopping centres,
streets, density grid, distance rings, a live map), what kinds are they
(estimated from words in the business name, with the unclassified share
disclosed), how does the mix differ between shopping centres and streets,
which names repeat (chains, lottery stalls), and how complete the records are.

Order-independent: integer counts, sorted aggregates with full tie-breaks,
medians and fsum for coordinates.
"""
import math
import re

import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
SITE_DECIMALS = 4  # ~10 m: rows on the same rounded point share one site
SITE_MIN = 5  # a site needs this many records to be charted
TOP_SITES = 10
TOP_STREETS = 12
TOP_NAMES = 10
RING_KM = 1
MAX_RINGS = 5
MAX_CELLS = 18
CELL_KM = 0.5
NEAR_KM = 2
MIN_CLASSIFIED_FOR_MIX = 20
MIX_GAP_PP = 8

UNCLASSIFIED = "לא סווג"
NO_STREET = "ללא רחוב"
OTHER = "אחר"

# (category, words). A word matches a whole token of the name, optionally after
# one Hebrew prefix letter (ה/ו/ל/ב/מ/ש). Multi-word entries match as a phrase.
# First category that matches wins, so specific ones come first.
CATS = [
    ("דוכני מפעל הפיס", ["מפעל הפיס", "לוטו"]),
    ("מספרות ועיצוב שיער", ["מספרה", "מספרת", "מספרות", "שיער", "ברבר", "ברברשופ", "barber", "תספורת",
                            "hair", "סלון"]),
    ("בריאות ורפואה", ["מרפאה", "מרפאת", "שיניים", "דנט", "קליניקה", "קליניקת", "קלינקה", "רופא", "ד\"ר",
                       "אופטיקה", "אופטיק", "אופטיקנה", "פארם", "מרקחת", "פיזיותרפיה", "רפואה", "רפואי",
                       "רפואיות", "שמיעה", "פסיכולוג", "בריאות", "וטרינר", "וטרינרית", "optic"]),
    ("קוסמטיקה וטיפוח", ["קוסמטיקה", "קוסמטיקס", "קוסמטיקאית", "ציפורניים", "ציפורני", "לק", "יופי",
                         "ביוטי", "beauty", "טיפוח", "פרפומריה", "בשמים", "סבון", "סבונים", "גבות", "nails",
                         "אסתטיקה", "ספא", "spa", "קעקועים", "טאטו", "tattoo", "איפור"]),
    ("מסעדות, קפה ומזון", ["מסעדה", "מסעדת", "קפה", "cafe", "פיצה", "פיצרייה", "פלאפל", "שווארמה", "בורגר",
                           "בורגרס", "המבורגר", "סושי", "מאפייה", "מאפיית", "מאפית", "מאפה", "קונדיטוריה",
                           "קונדיטורית", "גלידה", "שיפודי", "שיפודיה", "ביסטרו", "פאב", "מזנון", "מיזנון",
                           "אוכל", "מקדונלדס", "גריל", "בייקרי", "ממתקים", "בירה", "קייטרינג", "חומוס",
                           "טוסט", "ארומה", "לנדוור", "קופיקס", "שוקולד", "מטעמים", "בורקס", "בשר", "יינות",
                           "משקאות", "פירות", "ירקות", "מעדניה", "מעדנייה", "קינוחים", "pizza", "coffee",
                           "food", "burger", "bakery", "דומינוס"]),
    ("סופרמרקטים, מכולות ונוחות", ["סופרמרקט", "מרקט", "מינימרקט", "מכולת", "שופרסל", "נוחות", "קיוסק",
                                   "פיצוציה", "כלבו", "market"]),
    ("רכב ותחבורה", ["מוסך", "רכב", "רכבים", "צמיגים", "נהיגה", "תדלוק", "דלק", "הובלות", "אוטו",
                     "מוניות", "אופנועים", "חלפים", "מוטורס"]),
    ("משרדים ושירותים מקצועיים", ["עו\"ד", "עורך דין", "עורכי דין", "רו\"ח", "ביטוח", "ביטוחים", "בטוח",
                                  "יועץ", "יועצים", "ייעוץ", "פיננסים", "פיננסיים", "נדל\"ן", "השקעות",
                                  "תיווך", "חשבונות", "אדריכלים", "אדריכלית", "מהנדסים", "שמאי", "פנסיה"]),
    ("חינוך והדרכה", ["בית ספר", "חינוך", "לימודים", "קורסים", "מכללה", "אקדמיה", "ברליץ"]),
    ("כושר, ספורט ופנאי", ["כושר", "ספורט", "פילאטיס", "יוגה", "ג'ים", "gym", "באולינג", "מחול", "ריקוד",
                           "דאנס", "dance", "טניס", "שחייה", "בריכה", "קלאב", "club", "fitness", "קולנוע",
                           "אירועים"]),
    ("אופנה, הנעלה ואביזרים", ["אופנה", "אופנת", "הלבשה", "נעלי", "נעליים", "בגדי", "בגדים", "בוטיק",
                               "תכשיטים", "תכשיטי", "שעונים", "תיקים", "תיק", "fashion", "ג'ינס", "גרביים",
                               "הנעלה", "טקסטיל", "כובעים", "שמלות"]),
    ("בית, ריהוט, חשמל ומתנות", ["חשמל", "אלקטריק", "רהיטים", "תאורה", "הום", "home", "ריצוף", "שיש",
                                 "מזרנים", "מטבחים", "וילונות", "שטיחים", "פרחים", "פרחי", "צעצועים", "ספרים",
                                 "סטימצקי", "צילום", "סלולר", "מובייל", "מחשבים", "אלקטרוניקה", "מתנות"]),
    ("תעשייה ומלאכה", ["תעשיות", "מתכות", "מתכת", "ברזל", "מפעל", "פלסטיק", "מסגרייה", "נגרייה", "דפוס",
                       "קבלן", "שיפוצים", "אלומיניום", "זכוכית", "מיסבים", "עפר"]),
]
PREFIX_LETTERS = "הולבמש"
TOKEN_SPLIT = re.compile(r"[\s\-–,/()\.]+")

# Words in the street text that mark a shopping centre / commercial complex.
# Whole words only ("ביג" must not match inside "אביגדור"); a medical centre is not a venue.
VENUE_RX = re.compile(r"(?:^|\s)(?:קניון|ביג|סנטר|פלאזה|פלנט|פלאנט|תחנה מרכזית|פסג'|מרכז(?! רפואי)|השדרה|דיזיין|מתחם)(?=\s|$)")
STREET_PREFIX_RX = re.compile(r"^(?:רחוב|רח'|שדרות|שד'|שד)\s+")
TRAILING_NUM_RX = re.compile(r"\s+\d+[\d/]*\s*$")
HAS_NUM_RX = re.compile(r"\d")


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def _norm_text(s):
    s = str(s).replace("״", '"').replace("׳", "'").replace("’", "'").replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def _num(s):
    try:
        v = float(str(s).replace(",", "").strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _tokens(name):
    return [t for t in TOKEN_SPLIT.split(name.lower()) if t]


def _categorize(name):
    if not name:
        return UNCLASSIFIED
    toks = _tokens(name)
    joined = " " + " ".join(toks) + " "
    tokset = set(toks)
    for cat, words in CATS:
        for w in words:
            w = w.lower()
            if " " in w:
                if " " + w + " " in joined or any(" " + p + w + " " in joined for p in PREFIX_LETTERS):
                    return cat
                continue
            if w in tokset:
                return cat
            for t in toks:
                if len(t) == len(w) + 1 and t[0] in PREFIX_LETTERS and t[1:] == w:
                    return cat
    return UNCLASSIFIED


def _venue(street):
    """The shopping-centre part of a street text, or None."""
    for part in re.split(r",|\s-\s?|\s?-\s", street):
        part = part.strip().rstrip(".").strip()
        part = re.sub(r"\s*באר שבע\s*$", "", part).strip()
        part = re.sub(r"\s+\d+\s*$", "", part).strip()
        if part and VENUE_RX.search(part):
            part = re.sub(r"^מתחם\s+", "", part.replace("קריית", "קרית"))
            if part == "ביג":
                part = "מרכז ביג"
            return part
    return None


def _street(street):
    s = street.split(",")[0]
    s = re.split(r"\s-\s?|\s?-\s|\(", s)[0]
    s = s.strip().rstrip(".").strip()
    s = re.sub(r"\s*באר שבע\s*$", "", s).strip()
    s = TRAILING_NUM_RX.sub("", s).strip()
    s = STREET_PREFIX_RX.sub("", s).strip()
    return s or NO_STREET


def _top(counter_items, n):
    """Sort (name, count) by count desc then name; keep n, rest into OTHER."""
    items = sorted(counter_items, key=lambda kv: (-kv[1], kv[0]))
    head = items[:n]
    rest = sum(c for _, c in items[n:])
    return head, rest


def _mode(values):
    vc = {}
    for v in values:
        vc[v] = vc.get(v, 0) + 1
    return sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if vc else None


def compute(frames):
    df = frames["main"]
    total = len(df)
    names = [_norm_text(v) for v in df["business"].tolist()]
    streets_raw = [_norm_text(v) for v in df["street"].tolist()]
    house = [_num(v) for v in df["house_numb"].tolist()]
    xs = [_num(v) for v in df["X"].tolist()]
    ys = [_num(v) for v in df["Y"].tolist()]
    notes = [_norm_text(v) for v in df["Note"].tolist()]
    lats = [_num(v) for v in df["lat"].tolist()]
    lons = [_num(v) for v in df["lon"].tolist()]

    geo = [la is not None and lo is not None and LAT_RANGE[0] <= la <= LAT_RANGE[1]
           and LON_RANGE[0] <= lo <= LON_RANGE[1] for la, lo in zip(lats, lons)]
    n_geo = sum(geo)

    cats = [_categorize(n) for n in names]
    venues = [_venue(s) if s else None for s in streets_raw]
    streets = [_street(s) if s else NO_STREET for s in streets_raw]
    in_venue = [v is not None for v in venues]
    n_venue = sum(in_venue)
    venue_share = n_venue / total if total else 0.0

    # ---------- categories
    cat_counts = {}
    for c in cats:
        cat_counts[c] = cat_counts.get(c, 0) + 1
    n_unclassified = cat_counts.get(UNCLASSIFIED, 0)
    n_classified = total - n_unclassified
    classified_share = n_classified / total if total else 0.0
    cat_items = sorted([(c, n) for c, n in cat_counts.items() if c != UNCLASSIFIED], key=lambda kv: (-kv[1], kv[0]))
    cats_chart = {"names": [c for c, _ in cat_items], "values": [n for _, n in cat_items]}
    t_cats = [{"name": c, "count": _int(n), "share": _pct(n / n_classified, 1) if n_classified else "0%"}
              for c, n in cat_items]

    # ---------- shopping centres vs streets: category mix (shares of classified)
    mix_rows = []
    v_cls = {}
    s_cls = {}
    for c, v in zip(cats, in_venue):
        if c == UNCLASSIFIED:
            continue
        d = v_cls if v else s_cls
        d[c] = d.get(c, 0) + 1
    nv = sum(v_cls.values())
    ns = sum(s_cls.values())
    has_mix = nv >= MIN_CLASSIFIED_FOR_MIX and ns >= MIN_CLASSIFIED_FOR_MIX
    if has_mix:
        for c, _ in cat_items:
            mix_rows.append((c, round(v_cls.get(c, 0) / nv * 100, 1), round(s_cls.get(c, 0) / ns * 100, 1),
                             v_cls.get(c, 0), s_cls.get(c, 0)))
    mix_chart = {"names": [r[0] for r in mix_rows], "venue": [r[1] for r in mix_rows],
                 "street": [r[2] for r in mix_rows]}
    t_mix = [{"name": r[0], "venue": f"{r[1]:.1f}%", "street": f"{r[2]:.1f}%"} for r in mix_rows]

    # ---------- venues (shopping centres named in the address)
    venue_counts = {}
    for v in venues:
        if v:
            venue_counts[v] = venue_counts.get(v, 0) + 1
    venue_items = sorted(venue_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top_venue = venue_items[0] if venue_items else None

    # ---------- sites: records sharing one rounded point
    site_rows = {}
    for i in range(total):
        if not geo[i]:
            continue
        key = (round(lats[i], SITE_DECIMALS), round(lons[i], SITE_DECIMALS))
        site_rows.setdefault(key, []).append(i)
    n_sites = len(site_rows)
    sites = []
    for key, idx in site_rows.items():
        if len(idx) < SITE_MIN:
            continue
        vs = [venues[i] for i in idx if venues[i]]
        if vs and len(vs) * 2 >= len(idx):
            label = _mode(vs)
        else:
            st = _mode([streets[i] for i in idx])
            nums = [int(house[i]) for i in idx if house[i] and streets[i] == st]
            label = st + (f" {_mode(nums)}" if nums else "")
        sites.append((label, len(idx), key))
    sites.sort(key=lambda r: (-r[1], r[0], r[2]))
    # merge duplicate labels (two nearby points of the same centre)
    merged = {}
    for label, n, _ in sites:
        merged[label] = merged.get(label, 0) + n
    site_items = sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_SITES]
    n_in_big_sites = sum(n for _, n, _ in sites)
    sites_chart = {"names": [s for s, _ in site_items], "values": [n for _, n in site_items]}
    t_sites = [{"name": s, "count": _int(n), "share": _pct(n / total, 1)} for s, n in site_items]
    big_site_share = n_in_big_sites / total if total else 0.0

    # ---------- streets
    st_counts = {}
    for s in streets:
        if s != NO_STREET:
            st_counts[s] = st_counts.get(s, 0) + 1
    n_streets = len(st_counts)
    st_head, _ = _top(st_counts.items(), TOP_STREETS)
    streets_chart = {"names": [s for s, _ in st_head], "values": [n for _, n in st_head]}
    t_streets = [{"name": s, "count": _int(n), "share": _pct(n / total, 1)} for s, n in st_head]
    top5_streets = sum(n for _, n in st_head[:5])

    # ---------- repeated names
    seen = set()
    name_counts = {}
    n_dupes = 0
    for i in range(total):
        sig = (names[i], streets_raw[i], house[i], lats[i], lons[i])
        if sig in seen:
            n_dupes += 1
        seen.add(sig)
        if names[i]:
            name_counts[names[i]] = name_counts.get(names[i], 0) + 1
    multi = [(n, c) for n, c in name_counts.items() if c >= 2]
    n_multi_names = len(multi)
    n_multi_rows = sum(c for _, c in multi)
    names_head, _ = _top(multi, TOP_NAMES)
    names_chart = {"names": [n for n, _ in names_head], "values": [c for _, c in names_head]}
    t_names = [{"name": n, "count": _int(c)} for n, c in names_head]
    n_distinct_names = len(name_counts)

    # ---------- distance rings around the median point
    map_view = {"center": [31.25, 34.79], "zoom": 13}
    ring_chart = {"names": [], "values": []}
    t_rings = []
    grid_chart = {"x": [], "y": [], "data": [], "max": 0}
    near_share = None
    lat0 = lon0 = None
    if n_geo:
        glat = sorted(la for la, g in zip(lats, geo) if g)
        glon = sorted(lo for lo, g in zip(lons, geo) if g)
        lat0 = (glat[(n_geo - 1) // 2] + glat[n_geo // 2]) / 2
        lon0 = (glon[(n_geo - 1) // 2] + glon[n_geo // 2]) / 2
        map_view = {"center": [round(lat0, 4), round(lon0, 4)], "zoom": 13}
        kx = 111.32 * math.cos(math.radians(lat0))
        ky = 110.57
        dists = []
        for la, lo, g in zip(lats, lons, geo):
            if g:
                dists.append(math.hypot((lo - lon0) * kx, (la - lat0) * ky))
        ring_n = [0] * MAX_RINGS
        for dkm in dists:
            ring_n[min(int(dkm // RING_KM), MAX_RINGS - 1)] += 1
        for r in range(MAX_RINGS):
            lo_km, hi_km = r * RING_KM, (r + 1) * RING_KM
            nm = f"{lo_km}-{hi_km}" if r < MAX_RINGS - 1 else f"{lo_km}+"
            ring_chart["names"].append(nm)
            ring_chart["values"].append(ring_n[r])
            t_rings.append({"name": nm, "count": _int(ring_n[r]), "share": _pct(ring_n[r] / n_geo, 1)})
        near_share = sum(1 for dkm in dists if dkm < NEAR_KM) / n_geo

        # density grid in km cells around the centre, growing the cell when the span grows
        xs_km = [(lo - lon0) * kx for lo, g in zip(lons, geo) if g]
        ys_km = [(la - lat0) * ky for la, g in zip(lats, geo) if g]
        span = max(max(xs_km) - min(xs_km), max(ys_km) - min(ys_km))
        cell = CELL_KM
        while span / cell > MAX_CELLS:
            cell *= 2
        x0 = math.floor(min(xs_km) / cell)
        y0 = math.floor(min(ys_km) / cell)
        x1 = math.floor(max(xs_km) / cell)
        y1 = math.floor(max(ys_km) / cell)
        cells = {}
        for xk, yk in zip(xs_km, ys_km):
            k = (math.floor(xk / cell) - x0, math.floor(yk / cell) - y0)
            cells[k] = cells.get(k, 0) + 1

        def _lab(v):
            s = f"{v * cell:.1f}"
            return s.replace("-", "−") if not s.startswith("-0.0") else "0.0"

        # x axis runs west to east; label each column by its west edge offset in km
        grid_chart = {
            "x": [_lab(x0 + i) for i in range(x1 - x0 + 1)],
            "y": [_lab(y0 + j) for j in range(y1 - y0 + 1)],
            "data": [[k[0], k[1], v] for k, v in sorted(cells.items())],
            "max": max(cells.values()),
        }
        cell_km = cell
    else:
        cell_km = CELL_KM

    # ---------- field completeness
    has_name = sum(1 for n in names if n)
    has_street = sum(1 for s in streets_raw if s)
    has_house = sum(1 for h, s in zip(house, streets_raw) if (h and h > 0) or HAS_NUM_RX.search(s))
    has_itm = sum(1 for x, y in zip(xs, ys) if x and y and x > 0 and y > 0)
    has_note = sum(1 for n in notes if n)
    field_rows = [("שם העסק", has_name), ("רחוב", has_street), ("מספר בית", has_house),
                  ("קואורדינטות גאוגרפיות", n_geo), ("רשת ישראל החדשה (X/Y)", has_itm),
                  ("הערת ההסתייגות", has_note)]
    fields_chart = {"names": [r[0] for r in field_rows],
                    "pct": [round(r[1] / total * 100, 1) if total else 0 for r in field_rows]}
    t_fields = [{"name": r[0], "count": _int(r[1]), "share": _pct(r[1] / total, 1) if total else "0%"}
                for r in field_rows]
    n_no_itm = total - has_itm

    # ---------- insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if site_items and site_items[0][1] / total >= 0.05:
        s, n = site_items[0]
        extra = ""
        if len(site_items) >= 3:
            n3 = sum(c for _, c in site_items[:3])
            extra = (f" יחד עם {site_items[1][0]} ו{site_items[2][0]}, שלוש הנקודות הגדולות מרכזות "
                     f"{_int(n3)} רשומות ({_pct(n3 / total)} מהמאגר).")
        add("site", f"{_int(n)} עסקים, {_pct(n / total, 1)} מכל הרשומות, רשומים בנקודה אחת: {s}.{extra}")

    if top_venue and venue_share >= 0.1:
        add("venue", (f"{_pct(venue_share)} מהעסקים ({_int(n_venue)}) רשומים בכתובת של מרכז קניות או מתחם מסחרי "
                      f"({_int(len(venue_items))} מתחמים שונים); הגדול שבהם {top_venue[0]} עם {_int(top_venue[1])} עסקים."))

    if len(cat_items) >= 2 and n_classified >= MIN_CLASSIFIED_FOR_MIX and cat_items[0][1] > cat_items[1][1]:
        (c1, n1), (c2, n2) = cat_items[0], cat_items[1]
        add("cats", (f"לפי מילים בשם העסק אפשר לסווג {_int(n_classified)} עסקים ({_pct(classified_share)}). "
                     f"הקבוצה הגדולה: {c1} עם {_int(n1)} עסקים ({_pct(n1 / n_classified)} מהמסווגים), "
                     f"ואחריה {c2} עם {_int(n2)}."))

    if has_mix:
        best = sorted(mix_rows, key=lambda r: (-abs(r[1] - r[2]), r[0]))[0]
        gap = best[1] - best[2]
        if abs(gap) >= MIX_GAP_PP:
            where_hi, where_lo = ("במרכזי הקניות", "ברחובות") if gap > 0 else ("ברחובות", "במרכזי הקניות")
            hi, lo = (best[1], best[2]) if gap > 0 else (best[2], best[1])
            add("mix", (f"התמהיל שונה בין מרכזי הקניות לרחובות: {best[0]} הם {hi:.1f}% מהעסקים המסווגים "
                        f"{where_hi}, לעומת {lo:.1f}% {where_lo}."))

    if names_head and names_head[0][1] >= 3:
        n, c = names_head[0]
        tail = ""
        if len(names_head) >= 2:
            tail = f" אחריו {names_head[1][0]} עם {_int(names_head[1][1])}."
        add("names", (f"{_int(n_multi_names)} שמות עסק מופיעים ביותר מרשומה אחת ({_int(n_multi_rows)} רשומות). "
                      f"השם הנפוץ ביותר: {n}, {_int(c)} רשומות.{tail}"))

    if st_head:
        s1, c1 = st_head[0]
        add("street", (f"העסקים פזורים על {_int(n_streets)} רחובות ומתחמים כפי שנרשמו; המוביל {s1} עם {_int(c1)} עסקים, "
                       f"וחמשת המובילים יחד מרכזים {_pct(top5_streets / total)} מהרשומות."))

    if near_share is not None and n_geo >= 10:
        add("near", (f"{_pct(near_share)} מהעסקים נמצאים בטווח {_int(NEAR_KM)} ק״מ ממרכז הפריסה "
                     f"(חציון קווי הרוחב והאורך)."))

    q = []
    if n_no_itm:
        q.append(f"ב-{_int(n_no_itm)} רשומות ({_pct(n_no_itm / total)}) שדות X/Y של רשת ישראל ריקים או אפס, "
                 f"אך קווי הרוחב והאורך מלאים ב-{_int(n_geo)} רשומות")
    if n_dupes:
        q.append(f"{_int(n_dupes)} רשומות הן כפילויות מלאות של רשומה אחרת")
    if q:
        add("quality", "איכות הנתונים: " + "; ".join(q) + ".")

    # ---------- KPIs
    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand", "label": "עסקים שהצהירו על התו הסגול"},
        "names": {"value": n_distinct_names, "display": _int(n_distinct_names), "tone": "brand",
                  "label": "שמות עסק שונים"},
        "venue": {"value": venue_share, "display": _pct(venue_share, 1), "tone": "info",
                  "label": "במרכזי קניות ומתחמים מסחריים"},
        "streets": {"value": n_streets, "display": _int(n_streets), "tone": "brand",
                    "label": "רחובות ומתחמים שונים"},
    }

    labels = {
        "lede": (f"{_int(total)} עסקים בבאר שבע הצהירו כי הם עומדים בתנאי התו הסגול, כללי ההתנהלות של משרד הבריאות "
                 f"ומשרד הכלכלה לפתיחת עסקים בתקופת הקורונה. המאגר מבוסס על הצהרת בעלי העסקים בלבד, ופרסומו "
                 f"על ידי העירייה אינו אישור שהעסק אכן עומד בתנאים. העמוד מראה היכן העסקים מרוכזים, באילו רחובות "
                 f"ומתחמים, מאילו תחומים הם ומה מצב השדות במאגר."),
        "map_note": ("העסקים על המפה, ממורכזת על מרכז הפריסה. לחצו על אשכול כדי להתקרב ועל סמן כדי לראות את שם העסק "
                     "והכתובת."),
        "sites_note": (f"נקודות שבהן רשומים לפחות {_int(SITE_MIN)} עסקים באותו מיקום (בדרך כלל מרכז קניות). "
                       f"{_int(n_sites)} נקודות שונות בסך הכול; הנקודות האלה מרכזות {_pct(big_site_share)} מהרשומות."),
        "sites_aria": f"תרשים עמודות אופקי: {len(site_items)} הנקודות עם הכי הרבה עסקים.",
        "sites_caption": "מספר העסקים בכל נקודה משותפת.",
        "cats_note": (f"תחום העסק אינו שדה במאגר, ולכן הוא הוערך לפי מילים בשם העסק (מספרה, קפה, מוסך וכדומה). "
                      f"{_int(n_classified)} עסקים סווגו ({_pct(classified_share)}); {_int(n_unclassified)} רשומות "
                      f"שהשם בהן אינו מעיד על התחום (לרוב שם מותג) לא נכללו."),
        "cats_aria": f"תרשים עמודות אופקי: מספר העסקים לפי תחום משוער, {len(cat_items)} תחומים.",
        "cats_caption": "מספר העסקים לפי תחום משוער (מתוך העסקים שסווגו).",
        "mix_note": (f"אחוז כל תחום מתוך העסקים שסווגו, בנפרד לעסקים בכתובת של מרכז קניות ({_int(nv)} מסווגים) "
                     f"ולעסקים ברחובות ({_int(ns)} מסווגים)."),
        "mix_aria": "תרשים עמודות אופקי כפול: אחוז כל תחום במרכזי הקניות לעומת הרחובות.",
        "mix_caption": "אחוז העסקים המסווגים בכל תחום, במרכזי קניות וברחובות.",
        "streets_note": (f"שם הרחוב כפי שנרשם, בלי מספר הבית ובלי שם המתחם שאחרי הפסיק. {len(st_head)} המובילים "
                         f"מתוך {_int(n_streets)}. איות שונה של אותו רחוב נספר בנפרד."),
        "streets_aria": f"תרשים עמודות אופקי: {len(st_head)} הרחובות עם הכי הרבה עסקים.",
        "streets_caption": "הרחובות והמתחמים עם מספר העסקים הגבוה ביותר.",
        "names_note": (f"שמות עסק שמופיעים ביותר מרשומה אחת: רשתות עם כמה סניפים, דוכנים ורשומות כפולות. "
                       f"{len(names_head)} המובילים מתוך {_int(n_multi_names)}."),
        "names_aria": f"תרשים עמודות אופקי: {len(names_head)} שמות העסק עם הכי הרבה רשומות.",
        "names_caption": "שמות העסק עם מספר הרשומות הגבוה ביותר.",
        "rings_note": (f"מספר העסקים בטבעות של {_int(RING_KM)} ק״מ סביב מרכז הפריסה (חציון קווי הרוחב והאורך). "
                       f"הטבעת האחרונה כוללת את כל המרוחקים יותר."),
        "rings_aria": f"תרשים עמודות: מספר העסקים לפי מרחק ממרכז הפריסה, {len(ring_chart['names'])} טבעות.",
        "rings_caption": "מספר העסקים לפי מרחק ממרכז הפריסה (ק״מ).",
        "grid_note": (f"צפיפות העסקים בתאי רשת של {cell_km:.1f} ק״מ. הצירים מראים את המרחק בק״מ ממרכז הפריסה: "
                      f"מזרחה וצפונה בערכים חיוביים. הצבע מציין את מספר העסקים בתא."),
        "grid_aria": "מפת חום: מספר העסקים בתאי רשת סביב מרכז הפריסה.",
        "fields_note": "אחוז הרשומות שבהן כל שדה מלא ותקין.",
        "fields_aria": "תרשים עמודות אופקי: אחוז הרשומות המלאות בכל שדה.",
        "fields_caption": "מספר ואחוז הרשומות שבהן השדה מלא.",
    }

    summary = (f"איתור עסקים עם התו הסגול בבאר שבע לפי שם או רחוב: {_int(total)} עסקים שהצהירו על עמידה בתנאים, "
               f"{_pct(venue_share)} מהם במרכזי קניות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["תו סגול", "באר שבע", "עסקים", "קורונה", "מרכזי קניות"],
            "spatial_coverage": "באר שבע",
            "related_ids": ["54b65747-904e-42e1-9316-0575ebbc1216", "82a30a97-01b0-4281-854c-c7931f3445c0",
                            "4491ecd9-5f9c-4299-a79f-43ed979651f9"],
        },
        "kpis": kpis,
        "charts": {"sites": sites_chart, "cats": cats_chart, "mix": mix_chart, "streets": streets_chart,
                   "names": names_chart, "rings": ring_chart, "grid": grid_chart, "fields": fields_chart},
        "tables": {"sites": t_sites, "cats": t_cats, "mix": t_mix, "streets": t_streets, "names": t_names,
                   "rings": t_rings, "fields": t_fields},
        "insights": insights,
        "map_view": map_view,
        "has_geo": bool(grid_chart["data"]),
        "has_sites": bool(site_items),
        "has_cats": bool(cat_items),
        "has_mix": has_mix,
        "has_names": bool(names_head),
        "labels": labels,
    }
