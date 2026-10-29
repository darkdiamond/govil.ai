"""עמדות שירות עצמי לקבלת שירותי ממשלה (מערך הדיגיטל הלאומי).

One row per self-service government kiosk: a free-text `name` (a fixed
"עמדת שירות עצמי לקבלת שירותי ממשלה" prefix line, then the host site, e.g.
"סופר פארם קניון חולון"), a free-text address (`addr`), the list of services
the kiosk offers (`service`, comma-separated, today identical for every row),
the operating office (`office`, constant) and ITM easting/northing (`X`/`Y`).

There is no city column, so the locality is recognised from the address
(then the site name) against a lexicon of Israeli localities; anything not in
the lexicon is shown as "יישוב לא מזוהה" and the count is disclosed. The host
type (pharmacy, municipality, government office, community / service centre,
mall, mobile kiosk) is classified by keyword from the site name.

Distances: the ITM grid is metric, so the distance from each kiosk to the
nearest other kiosk is plain Euclidean distance in metres. Rows whose X/Y are
swapped (northing in the easting column) are swapped back for the distance
figures; rows without usable coordinates are left out of them (disclosed).

Growth: CKAN replaces the file in place. Locality axes are top-N + "אחר",
the directory is capped at DIR_MAX_ROWS rows, new host keywords fall into
"אחר", and services are parsed from the data. Every sort is total.
"""
import re

import numpy as np
import pandas as pd

TOP_CITIES = 15          # localities on the bar chart before "אחר"
DIR_MAX_ROWS = 400       # directory rows rendered in full
ISOLATED_N = 8           # rows in the "most remote kiosks" table
NEAR_KM = 5              # "another kiosk within N km" threshold
REMOTE_KM = 20           # a kiosk this far from the next one is "remote"
LEADER_MIN = 3           # a leading locality needs at least this many kiosks
PHARM_SHARE_MIN = 0.3    # pharmacy-share insight threshold
UNKNOWN_CITY = "יישוב לא מזוהה"
OTHER = "אחר"

PREFIX_RE = re.compile(r"עמדת שירות עצמי לקבלת שירותי ממשל[ה]?[,]?\s*(ניידת)?")

DIST_BANDS = [(0, 1, "עד 1 ק\"מ"), (1, 3, "1-3 ק\"מ"), (3, 5, "3-5 ק\"מ"),
              (5, 10, "5-10 ק\"מ"), (10, 20, "10-20 ק\"מ"),
              (20, None, "מעל 20 ק\"מ")]

# Host types, matched in order against the site name (mobile also on addr).
HOSTS = [
    ("עמדה ניידת", re.compile(r"(?<![א-ת])(ניידת|נייד)(?![א-ת])")),
    ("סופר-פארם ובתי מרקחת", re.compile(r"סופר ?-?פארם|בית מרקחת|פארם")),
    ("עירייה או מועצה", re.compile(r"עירי|עריה|עירית|מועצ|בית העירייה|בניין העירייה|בנין עירייה")),
    ("משרד ממשלתי", re.compile(r"קרית הממשלה|קריית הממשלה|לשכת")),
    ("מתנ\"ס או מרכז שירות", re.compile(r"מתנ\"ס|מרכז קהילתי|מרכז שירות|מרכז עוצמה|מחלקת")),
    ("קניון או מרכז מסחרי", re.compile(r"קניון|כניון|מרכז מסחרי|מרכז מסכרי|מרכז עסקים|סנטר")),
]
HOST_OTHER = "מקום אחר"

# canonical locality -> aliases (normalised: hyphens to spaces, gershayim to ").
CITIES = {
    "אום אל פחם": ["אום אל פחם", "אום אל פאחם"], "אופקים": [], "אור יהודה": [],
    "אור עקיבא": [], "אזור": [], "אילת": [], "אלעד": [], "אעבלין": [],
    "אריאל": [], "אשדוד": [], "אשקלון": [], "באקה אל גרביה": [], "באר יעקב": [],
    "באר שבע": ["ב\"ש"], "בועיינה נוג'ידאת": ["בועיינה נוגידאת", "בועיינה נוג'ידת"],
    "בית שאן": [], "בית שמש": [], "ביתר עילית": ["ביתר עלית"],
    "בני ברק": [], "בסמ\"ה": ["בסמה"], "בת ים": [], "ג'דיידה מכר": [],
    "ג'לג'וליה": [], "ג'סר א זרקא": ["ג'סר א-זרקא", "גסר א זרקא"], "גבעת שמואל": [],
    "גבעתיים": [], "גדרה": [], "גוש עציון": [], "גן יבנה": [],
    "דליית אל כרמל": ["דאלית אל כרמל"], "דימונה": [], "הוד השרון": [],
    "הרצליה": [], "זכרון יעקב": ["זיכרון יעקב"], "חדרה": [], "חולון": [],
    "חוף הכרמל": [], "חורה": [], "חיפה": [], "חריש": [], "טבריה": [],
    "טייבה": [], "טירה": [], "טירת כרמל": ["טירת הכרמל"], "טמרה": [],
    "יבנה": [], "יהוד מונוסון": ["יהוד"], "יפיע": [],
    "יקנעם עילית": ["יוקנעם עילית", "יקנעם", "יוקנעם"],
    "ירוחם": [], "ירושלים": ["מזרח ירושלים"], "כסיפה": ["כסייפה", "כסייפא"],
    "כפר יאסיף": [], "כפר יונה": [], "כפר כנא": [], "כפר סבא": [], "כפר קאסם": [],
    "כפר קרע": [], "כרמיאל": [], "לוד": [], "לקיה": [], "מבשרת ציון": [],
    "מגאר": [], "מג'ד אל כרום": [], "מגדל העמק": [], "מודיעין מכבים רעות": ["מודיעין"],
    "מודיעין עילית": [], "מעלה אדומים": [], "מעלות תרשיחא": ["מעלות"],
    "מצפה רמון": [], "נהריה": [], "נוף הגליל": ["נצרת עילית"], "נווה ירק": [],
    "נווה זוהר": [], "נס ציונה": [], "נעלה": [], "נצרת": [], "נשר": [],
    "נתיבות": [], "נתניה": [], "נמל התעופה בן גוריון": ["נתבג", "נתב\"ג"],
    "סביון": [], "סח'נין": ["סכנין"], "ספיר": [], "עכו": [], "עמק חפר": [],
    "עין מאהל": [], "עפולה": [], "עראבה": [], "ערד": [], "ערערה": ["עארה ערערה"],
    "ערערה בנגב": [], "פסגות": [], "פרדס חנה כרכור": ["פרדס חנה"],
    "פתח תקווה": ["פתח תקוה"], "צמח": [], "צפת": [], "קדימה צורן": [],
    "קצרין": [], "קרית אונו": [], "קרית אתא": [], "קרית ביאליק": [],
    "קרית גת": [], "קרית ים": [], "קרית מוצקין": [], "קרית מלאכי": [],
    "קרית עקרון": [], "קרית שדה התעופה": [], "קרית שמונה": [], "קרית טבעון": [],
    "קרית ארבע": [], "קרני שומרון": [], "ראש העין": [], "ראש פינה": [],
    "ראשון לציון": [], "רגבה": [], "רהט": [], "רחובות": [], "רכסים": [],
    "רמלה": [], "רמת גן": [], "רמת השרון": [], "רמת ישי": [], "רעננה": [],
    "שדרות": [], "שגב שלום": [], "שוהם": [], "שפרעם": [], "תל אביב-יפו":
    ["תל אביב", "תל אביב יפו", "ת\"א"], "תל שבע": [],
}


def n(v):
    return f"{int(v):,}"


def pct(x):
    return f"{x * 100:.0f}%"


def km(m):
    return f"{m / 1000:.1f}"


def _norm(s):
    s = str(s).replace("״", '"').replace("''", '"').replace("׳", "'")
    s = s.replace("קריית", "קרית")
    s = re.sub(r"[-–]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _build_city_patterns():
    pats = []
    for canon, aliases in CITIES.items():
        for a in [canon] + aliases:
            a2 = _norm(a)
            pats.append((canon, len(a2), re.compile(r"(?<![א-ת])" + re.escape(a2) + r"(?![א-ת])")))
    return pats


CITY_PATS = _build_city_patterns()


def find_city(text):
    """Rightmost match wins (cities close the address); ties go to the longer alias."""
    t = _norm(text)
    best = None
    for canon, ln, rx in CITY_PATS:
        for m in rx.finditer(t):
            key = (m.end(), ln, canon)
            if best is None or key > best:
                best = key
    return best[2] if best else None


def place_name(raw):
    lines = []
    for ln in str(raw).replace("\r", "").split("\n"):
        ln = PREFIX_RE.sub("", ln)
        ln = re.sub(r"[/\s]+$", "", re.sub(r"^[/\s,]+", "", ln))
        ln = re.sub(r"\s*/\s*", " ", ln)
        ln = re.sub(r"\s+", " ", ln).strip(" ,")
        if ln:
            lines.append(ln)
    return " ".join(lines)


def host_type(name_raw, place, addr):
    is_mobile = HOSTS[0][1].search(_norm(name_raw)) or HOSTS[0][1].search(_norm(addr))
    if is_mobile:
        return HOSTS[0][0]
    p = _norm(place)
    for label, rx in HOSTS[1:]:
        if rx.search(p):
            return label
    return HOST_OTHER


def _coords(xs, ys):
    """Parse ITM; swap rows whose northing sits in the easting column."""
    x = pd.to_numeric(xs.str.replace(",", "").str.strip(), errors="coerce")
    y = pd.to_numeric(ys.str.replace(",", "").str.strip(), errors="coerce")
    ok_x = lambda v: (v >= 100000) & (v <= 300000)
    ok_y = lambda v: (v >= 350000) & (v <= 820000)
    swap = ~(ok_x(x) & ok_y(y)) & ok_x(y) & ok_y(x)
    fx = x.where(~swap, y)
    fy = y.where(~swap, x)
    valid = ok_x(fx) & ok_y(fy)
    return fx.where(valid), fy.where(valid), int(swap.sum())


def _nearest(df):
    """Distance (m) from each kiosk with coordinates to the nearest other one."""
    pts = df.dropna(subset=["fx", "fy"])
    out = pd.Series(np.nan, index=df.index)
    if len(pts) < 2:
        return out
    xy = pts[["fx", "fy"]].to_numpy(dtype=float)
    res = np.empty(len(xy))
    for i in range(0, len(xy), 500):
        blk = xy[i:i + 500]
        d = np.sqrt(((blk[:, None, :] - xy[None, :, :]) ** 2).sum(axis=2))
        for j in range(len(blk)):
            d[j, i + j] = np.inf
        res[i:i + len(blk)] = d.min(axis=1)
    out.loc[pts.index] = res
    return out


def _services(series):
    """Ordered service list: the most common row's order first, then the rest."""
    rows = []
    for s in series:
        items = [re.sub(r"\s+", " ", it).strip(" .") for it in re.split(r"[,\n]", str(s))]
        items = [it for it in items if it and it != "ועוד"]
        rows.append(tuple(items))
    if not rows:
        return [], 0
    counts = pd.Series(rows).value_counts()
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    item_count = {}
    for r in rows:
        for it in set(r):
            item_count[it] = item_count.get(it, 0) + 1
    order = list(dict.fromkeys(top)) + sorted(k for k in item_count if k not in top)
    distinct_sets = len({frozenset(r) for r in rows})
    return [{"name": it, "count": item_count[it]} for it in order], distinct_sets


def compute(frames):
    raw = frames["main"].copy()
    df = pd.DataFrame(index=raw.index)
    df["place"] = raw["name"].map(place_name)
    df["addr"] = raw["addr"].map(lambda s: re.sub(r"\s+", " ", str(s)).strip(" ,"))
    df.loc[df["place"] == "", "place"] = df["addr"]
    df["host"] = [host_type(r, p, a) for r, p, a in zip(raw["name"], df["place"], df["addr"])]
    city_a = df["addr"].map(find_city)
    city_p = df["place"].map(find_city)
    df["city"] = city_a.where(city_a.notna(), city_p).fillna(UNKNOWN_CITY)
    df["fx"], df["fy"], n_swapped = _coords(raw["X"], raw["Y"])
    df["nn"] = _nearest(df)
    df = df.sort_values(["city", "place", "addr"], kind="mergesort").reset_index(drop=True)

    total = len(df)
    office = raw["office"].str.strip()
    offices = sorted(office[office != ""].unique())
    office_name = offices[0] if len(offices) == 1 else ""

    # ---- localities --------------------------------------------------------
    known = df[df["city"] != UNKNOWN_CITY]
    city_counts = known.groupby("city").size()
    city_rank = sorted(city_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    n_cities = len(city_rank)
    n_unknown = int((df["city"] == UNKNOWN_CITY).sum())
    top_c = city_rank[:TOP_CITIES]
    rest = sum(v for _, v in city_rank[TOP_CITIES:]) + n_unknown
    c_names = [k for k, _ in top_c]
    c_vals = [int(v) for _, v in top_c]
    if rest:
        c_names.append(f"{OTHER} ({n(len(city_rank) - len(top_c))} יישובים{', וללא יישוב מזוהה' if n_unknown else ''})")
        c_vals.append(int(rest))
    singles = sum(1 for _, v in city_rank if v == 1)

    # ---- host types --------------------------------------------------------
    host_counts = df.groupby("host").size()
    host_rank = sorted(host_counts.items(), key=lambda kv: (kv[0] == HOST_OTHER, -kv[1], kv[0]))
    host_table = [{"name": k, "count": n(v), "share": pct(v / total)} for k, v in host_rank]
    pharm = int(host_counts.get(HOSTS[1][0], 0))
    mobile = int(host_counts.get(HOSTS[0][0], 0))
    muni = int(host_counts.get(HOSTS[2][0], 0))

    # ---- nearest-neighbour distances -----------------------------------------
    nn = df["nn"].dropna()
    n_geo = len(nn)
    n_nogeo = total - int(df["fx"].notna().sum())
    band_vals = []
    for lo, hi, _ in DIST_BANDS:
        m = (nn >= lo * 1000) if hi is None else ((nn >= lo * 1000) & (nn < hi * 1000))
        band_vals.append(int(m.sum()))
    dist_table = [{"name": lab, "count": n(v), "share": pct(v / n_geo) if n_geo else "0%"}
                  for (_, _, lab), v in zip(DIST_BANDS, band_vals)]
    iso = df.dropna(subset=["nn"]).sort_values(["nn", "city", "place", "addr"],
                                               ascending=[False, True, True, True], kind="mergesort")
    iso_rows = [{"place": r.place, "city": r.city, "km": km(r.nn)} for r in iso.head(ISOLATED_N).itertuples()]
    med_nn = float(nn.median()) if n_geo else None
    near_share = float((nn < NEAR_KM * 1000).mean()) if n_geo else None
    n_remote = int((nn >= REMOTE_KM * 1000).sum())

    # ---- services ------------------------------------------------------------
    services, n_sets = _services(raw["service"])

    # ---- directory -------------------------------------------------------------
    directory = []
    rows_used = 0
    for city, cnt in sorted(df.groupby("city").size().items(),
                            key=lambda kv: (kv[0] == UNKNOWN_CITY, -kv[1], kv[0])):
        sub = df[df["city"] == city]
        rows = []
        if rows_used + len(sub) <= DIR_MAX_ROWS:
            rows = [{"place": r.place, "addr": r.addr, "host": r.host} for r in sub.itertuples()]
            rows_used += len(sub)
        directory.append({"name": city, "count": n(cnt), "rows": rows})
    dir_full = rows_used == total

    # ---- insights -----------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if city_rank and city_rank[0][1] >= LEADER_MIN:
        lead, lv = city_rank[0]
        second = [k for k, v in city_rank[1:] if v == lv]
        if second:
            add("leader", f"{lead} ו{second[0]} מובילות עם {n(lv)} עמדות כל אחת.")
        else:
            nxt = city_rank[1] if len(city_rank) > 1 else None
            tail = f", לפני {nxt[0]} ({n(nxt[1])})" if nxt else ""
            add("leader", f"ב{lead} פועלות הכי הרבה עמדות: {n(lv)} מתוך {n(total)} ({pct(lv / total)}){tail}.")

    if n_cities and singles / n_cities >= 0.4:
        add("singles", f"ב-{n(singles)} מתוך {n(n_cities)} היישובים המזוהים ({pct(singles / n_cities)}) יש עמדה אחת בלבד; "
                       f"רק ב-{n(n_cities - singles)} יישובים יש שתיים או יותר.")

    if total and pharm / total >= PHARM_SHARE_MIN:
        add("pharm", f"{n(pharm)} מהעמדות ({pct(pharm / total)}) מוצבות בסניפי סופר-פארם ובתי מרקחת, "
                     f"ו-{n(muni)} נוספות בבנייני עיריות ומועצות.")

    if med_nn is not None and near_share is not None and near_share > 0.5:
        add("near", f"לרוב העמדות יש עמדה נוספת בקרבה: חציון המרחק לעמדה הקרובה הוא {km(med_nn)} ק\"מ, "
                    f"ול-{pct(near_share)} מהן יש עמדה אחרת במרחק של פחות מ-{n(NEAR_KM)} ק\"מ.")

    if iso_rows and float(iso["nn"].iloc[0]) >= REMOTE_KM * 1000:
        r = iso_rows[0]
        where = r["place"] if r["city"] in _norm(r["place"]) else f"{r['place']} ({r['city']})"
        add("remote", f"העמדה המרוחקת ביותר היא {where}: {r['km']} ק\"מ בקו אוויר עד העמדה הבאה. "
                      f"{n(n_remote)} עמדות נמצאות {n(REMOTE_KM)} ק\"מ ויותר מהעמדה הקרובה אליהן.")

    if mobile:
        add("mobile", f"{n(mobile)} מהעמדות הן ניידות, ולכן מיקומן בפועל עשוי להשתנות ממה שמופיע במפה.")

    if services and n_sets == 1:
        add("services", f"כל {n(total)} העמדות מציעות את אותה רשימה של {n(len(services))} שירותים, "
                        "כך ששירות שזמין בעמדה אחת זמין, לפי המאגר, בכולן.")
    elif services:
        full = sum(1 for s in services if s["count"] == total)
        add("services", f"{n(full)} מתוך {n(len(services))} השירותים זמינים בכל העמדות; השאר רק בחלקן.")

    # ---- KPIs ---------------------------------------------------------------
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "cities": {"value": n_cities, "display": n(n_cities), "tone": "brand"},
        "pharm": {"value": round(pharm / total * 100, 1) if total else 0,
                  "display": pct(pharm / total) if total else "0%", "tone": "info"},
        "near": {"value": round(med_nn / 1000, 1) if med_nn is not None else 0,
                 "display": km(med_nn) if med_nn is not None else "0",
                 "tone": "ok" if med_nn is not None and med_nn < NEAR_KM * 1000 else "warn"},
    }

    # ---- labels -------------------------------------------------------------
    lead_txt = f" הריכוז הגדול ביותר ב{city_rank[0][0]} ({n(city_rank[0][1])})." if city_rank else ""
    rest_txt = ("שאר היישובים מקובצים ב\"" + OTHER + "\". ") if rest else ""
    venue_txt = (" רוב העמדות נמצאות בסניפי סופר-פארם, בעיריות ובמועצות מקומיות."
                 if total and (pharm + muni) / total >= 0.5 else
                 " העמדות מוצבות בסניפי סופר-פארם, בעיריות, במועצות ובמרכזי שירות.")
    lede = (f"{n(total)} עמדות שירות עצמי (קיוסקים ממשלתיים) ב-{n(n_cities)} יישובים, "
            f"{'שמפעיל ' + office_name + ', ' if office_name else ''}"
            "שבהן אפשר להנפיק אישורים ומסמכים ולשלם אגרות וקנסות בלי להגיע ללשכה: "
            "רישיון נהיגה ורכב, ספח תעודת זהות, שינוי כתובת, תמצית רישום ועוד."
            f"{lead_txt}{venue_txt}")

    unknown_note = (f" ל-{n(n_unknown)} עמדות לא זוהה יישוב מתוך הכתובת, והן נכללות ב\"{OTHER}\"."
                    if n_unknown else "")
    geo_note_parts = []
    if n_swapped:
        geo_note_parts.append(("ברשומה אחת" if n_swapped == 1 else f"ב-{n(n_swapped)} רשומות")
                              + " הקואורדינטות הוזנו בסדר הפוך (צפון במקום מזרח) ותוקנו לצורך חישוב המרחקים")
    if n_nogeo:
        geo_note_parts.append(f"{n(n_nogeo)} עמדות ללא קואורדינטות תקינות אינן נכללות")
    geo_note = ("; ".join(geo_note_parts) + ".") if geo_note_parts else ""

    summary = (f"איתור עמדת שירות עצמי ממשלתית לפי יישוב או כתובת: {n(total)} עמדות ב-{n(n_cities)} יישובים, "
               "לרישיון נהיגה, ספח ת\"ז, שינוי מען ותשלום קנסות.")
    if len(summary) > 155:
        summary = f"איתור עמדת שירות עצמי ממשלתית לפי יישוב או כתובת: {n(total)} עמדות ב-{n(n_cities)} יישובים."

    labels = {
        "lede": lede,
        "total_kpi": "עמדות שירות עצמי",
        "cities_kpi": "יישובים עם עמדה",
        "pharm_kpi": "מהעמדות בסופר-פארם ובתי מרקחת",
        "near_kpi": "חציון המרחק לעמדה הקרובה (ק\"מ)",
        "services_note": (f"הרשימה כפי שהיא מופיעה במאגר. כל {n(total)} העמדות מציעות אותה רשימה, והמאגר מוסיף \"ועוד\"."
                          if n_sets == 1 else
                          f"הרשימה כפי שהיא מופיעה במאגר; לצד כל שירות מספר העמדות (מתוך {n(total)}) שמציעות אותו."),
        "services_uniform": n_sets == 1,
        "map_note": ("כל נקודה היא עמדה; לחיצה מציגה את שם המקום והכתובת. "
                     "עמדות ניידות מוצגות במיקום הרשום במאגר."
                     + (" רשומה אחת במאגר, שהקואורדינטות שלה הוזנו בסדר הפוך, עשויה להופיע הרחק ממיקומה."
                        if n_swapped == 1 else
                        f" {n(n_swapped)} רשומות במאגר, שהקואורדינטות שלהן הוזנו בסדר הפוך, עשויות להופיע הרחק ממיקומן."
                        if n_swapped else "")),
        "dir_note": ((f"{n(n_cities)} יישובים, מהגדול לקטן, עם כתובת וסוג המקום של כל עמדה."
                      if dir_full else
                      f"{n(n_cities)} יישובים, מהגדול לקטן. כתובות מוצגות ליישובים הראשונים עד {n(DIR_MAX_ROWS)} עמדות; "
                      "לשאר השתמשו בחיפוש שבתחתית העמוד.") + unknown_note),
        "dir_caption": "עמדות שירות עצמי ביישוב",
        "city_note": (f"{n(len(top_c))} היישובים עם הכי הרבה עמדות; "
                      f"{rest_txt}"
                      f"היישוב זוהה מתוך הכתובת.{unknown_note}"),
        "city_aria": f"תרשים עמודות: מספר עמדות השירות העצמי ב-{n(len(top_c))} היישובים המובילים",
        "city_caption": "עמדות שירות עצמי לפי יישוב",
        "host_note": "סוג המקום זוהה לפי מילות מפתח בשם העמדה (למשל סופר פארם, עירייה, מועצה, מתנ\"ס, קניון).",
        "host_aria": "תרשים עמודות: עמדות שירות עצמי לפי סוג המקום",
        "host_caption": "עמדות שירות עצמי לפי סוג המקום",
        "dist_note": (f"המרחק בקו אוויר מכל עמדה לעמדה הקרובה אליה, לפי הקואורדינטות במאגר ({n(n_geo)} עמדות). "
                      + geo_note),
        "dist_aria": "תרשים עמודות: התפלגות המרחק מכל עמדה לעמדה הקרובה אליה",
        "dist_caption": "התפלגות המרחק לעמדה הקרובה",
        "iso_caption": "העמדות המרוחקות ביותר מעמדה אחרת",
        "iso_title": f"{n(len(iso_rows))} העמדות המרוחקות ביותר מעמדה אחרת",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["עמדות שירות", "שירות עצמי", "שירותי ממשלה", "רישיון נהיגה", "קיוסק ממשלתי"],
            "related_ids": [
                "009348a4-40d5-4bbe-92ab-ac19e4460fce",
                "7a6d0673-920c-470a-ad90-600d4ce3adcb",
                "df3b0e8d-b76a-4186-a6e1-df8eada5ef27",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "city": {"names": c_names, "values": c_vals},
            "host": {"names": [k for k, _ in host_rank], "values": [int(v) for _, v in host_rank]},
            "dist": {"names": [lab for _, _, lab in DIST_BANDS], "values": band_vals},
        },
        "tables": {
            "city": [{"name": a, "count": n(b)} for a, b in zip(c_names, c_vals)],
            "host": host_table,
            "dist": dist_table,
            "iso": iso_rows,
        },
        "services": services,
        "directory": directory,
        "insights": insights,
        "labels": labels,
        "flags": {"has_geo": n_geo >= 2},
    }
