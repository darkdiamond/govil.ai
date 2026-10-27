"""איפה דפי — מפת מכשירי החייאה (AED) קהילתית.

One row per defibrillator.  The CSV export is dirty: ~13% of the rows are
fragments of multi-line cells (opening-hours text, licence boilerplate) that
spilled into the wrong columns.  A row counts as a device only when it has a
WGS84 point inside Israel's bounding box AND a real ISO creation date.

Privacy: contactName / contactPhone / free-text address columns are never read
(they hold private phones and volunteer names).  Only aggregates and coarse
venue categories reach the page.

Order-independent: integer counts and sorted aggregates only.
"""
import re

import pandas as pd

LAT_RANGE = (29.0, 34.0)
LON_RANGE = (34.0, 36.0)
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
UNKNOWN_CITY = {"", "No reverse-geocoding result"}
TOP_CITIES = 12
MIN_CITY_KNOWN = 50        # devices with a 24/7 value for a city to be ranked on it
MIN_CAT_KNOWN = 50
MAX_MONTHLY_POINTS = 150   # growth line: monthly -> quarterly -> yearly past this
PEAK_SHARE = 0.15
CHANGE_MIN = 0.10
CITY_LEAD_SHARE = 0.05
GAP_PP_CITY = 0.15
GAP_PP_CAT = 0.20
GROUND_MIN = 0.40
CAT_LEAD_SHARE = 0.05
OTHER = "אחר / לא מזוהה"
NO_NAME = "ללא שם מיקום"

# first match wins; order = priority
CATEGORIES = [
    ("דוכני הפיס", r"פיס"),
    ("קופות חולים ומרפאות", r"קופ|כללית|מכבי|מאוחדת|לאומית|מרפאה|רופא|בית חולים|בי\"ח|בית מרקחת|סופר.?פארם|טיפת חלב|קליניקה"),
    ("בתי כנסת ומוסדות דת", r"כנסת|בית כנסת|מסגד|כנסייה|ישיבה|מקווה|תלמוד|חב\"ד|בית מדרש"),
    ("חינוך", r"בית ספר|בי\"ס|ביה\"ס|גן ילדים|גן |אוניברסיטה|מכללה|סמינר|תיכון|אולפנה|חטיבה|בית הספר|מעון"),
    ("ספורט וכושר", r"ספורט|כושר|בריכה|אצטדיון|אולם|מגרש|היכל|קאנטרי|סטודיו|התעמלות"),
    ("קניונים ומסחר", r"קניון|מסחרי|סופר|שופרסל|רמי לוי|יוחננוף|איקאה|מכולת|חנות|מרכז קניות|עזריאלי|סינמה|גרנד|בנק|מלון|בית קפה|מסעדה|דלק|תחנת דלק|פז |סונול"),
    ("יישובים וקהילה", r"מזכירות|קיבוץ|מושב|יישוב|ישוב|מועצה|עירי|מתנ\"ס|מתנס|מועדון|בית העם|חדר אוכל|ועד|קהילה|מרכז קהילתי|ספרייה|תרבות"),
    ("מגורים ובתים פרטיים", r"בית פרטי|מגורים|דירה|בניין|בית משותף|וילה|חצר"),
    ("תחבורה ופארקים", r"תחנה|אוטובוס|רכבת|חניון|פארק|גן ציבורי|גינה|טיילת|חוף|נמל|שדה תעופה"),
    ("מפעלים ומשרדים", r"מפעל|חברה|משרד|בע\"מ|מכון|חשמל|תעשי|מרכז עסקים|פארק עסקים"),
]
CAT_RES = [(n, re.compile(p)) for n, p in CATEGORIES]
FLOOR_WORDS = {"ראשונה": 1, "שנייה": 2, "שניה": 2, "שלישית": 3, "רביעית": 4}


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _norm_city(s):
    s = re.sub(r"\s+", " ", s.replace("-", " ").replace("–", " ")).strip()
    return "" if s in UNKNOWN_CITY else s


def _category(name):
    n = name.strip()
    if not n:
        return NO_NAME
    for cat, rx in CAT_RES:
        if rx.search(n):
            return cat
    return OTHER


def _floor(s):
    s = s.strip()
    if not s:
        return None
    if re.match(r"^(-\s*\d+|\d+\s*-|מינוס|מרתף|חניון|תת)", s) or "מרתף" in s or "מינוס" in s:
        return "מתחת לקרקע"
    if re.search(r"בחוץ|רחוב|חוץ|חצר|מדרכה", s):
        return "בחוץ"
    if re.search(r"קרקע|כניסה|לובי|לובי", s) or s in ("ק", "0"):
        return "קרקע / כניסה"
    for w, n in FLOOR_WORDS.items():
        if w in s:
            return _floor_n(n)
    m = re.match(r"^(\d+)", s)
    if m:
        n = int(m.group(1))
        return "קרקע / כניסה" if n == 0 else _floor_n(n)
    return "אחר"


def _floor_n(n):
    return f"קומה {n}" if n <= 4 else "קומה 5 ומעלה"


FLOOR_ORDER = ["מתחת לקרקע", "קרקע / כניסה", "קומה 1", "קומה 2", "קומה 3", "קומה 4",
               "קומה 5 ומעלה", "בחוץ", "אחר"]


def _prepare(df):
    out = pd.DataFrame({
        "id": df["id"].str.strip(),
        "created": df["createdAt"].str.strip(),
        "updated": df["updatedAt"].str.strip(),
        "city": df["indexCity"].map(_norm_city),
        "name": df["locationName"].str.strip(),
        "floor": df["locationFloor"].str.strip(),
        "allday": df["locationOpenAllDay"].str.strip(),
        "image": df["imageURL"].str.strip().str.startswith("http"),
        "lat": pd.to_numeric(df["lat"].str.strip(), errors="coerce"),
        "lon": pd.to_numeric(df["lon"].str.strip(), errors="coerce"),
    })
    ok = (out["lat"].between(*LAT_RANGE) & out["lon"].between(*LON_RANGE)
          & out["created"].str.match(DATE_RE))
    n_bad = int((~ok).sum())
    # points the shell's map would still draw (any plausible WGS84 pair)
    n_map = int((out["lat"].abs().lt(90) & out["lon"].abs().lt(200)).sum())
    out = out[ok].copy()
    out["cdate"] = pd.to_datetime(out["created"], format="%Y-%m-%d", errors="coerce")
    out = out[out["cdate"].notna()].copy()
    out["udate"] = pd.to_datetime(out["updated"].where(out["updated"].str.match(DATE_RE), ""),
                                  format="%Y-%m-%d", errors="coerce")
    out["cat"] = out["name"].map(_category)
    out["flr"] = out["floor"].map(_floor)
    out["known"] = out["allday"].isin(["True", "False"])
    out["is24"] = out["allday"].eq("True")
    out = out.sort_values(["cdate", "id", "lat", "lon"], kind="stable").reset_index(drop=True)
    return out, n_bad, n_map


def _rank(series):
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _share24(g):
    k = int(g["known"].sum())
    return (int(g["is24"].sum()) / k) if k else None, k


def _stack(df, key, names):
    a, b, c = [], [], []
    for n in names:
        g = df[df[key] == n]
        t = int(g["is24"].sum())
        f = int((g["known"] & ~g["is24"]).sum())
        a.append(t)
        b.append(f)
        c.append(int(len(g)) - t - f)
    return {"names": names, "yes": a, "no": b, "unknown": c}


def _stack_table(ch):
    rows = []
    for i, n in enumerate(ch["names"]):
        tot = ch["yes"][i] + ch["no"][i] + ch["unknown"][i]
        known = ch["yes"][i] + ch["no"][i]
        rows.append({"name": n, "total": _int(tot), "yes": _int(ch["yes"][i]),
                     "share": _pct(ch["yes"][i] / known) if known else "—"})
    return rows


def _periods(df):
    lo, hi = df["cdate"].min(), df["cdate"].max()
    months = (hi.year - lo.year) * 12 + hi.month - lo.month + 1
    if months <= MAX_MONTHLY_POINTS:
        key, label = df["cdate"].dt.to_period("M"), "חודשי"
    elif months <= MAX_MONTHLY_POINTS * 3:
        key, label = df["cdate"].dt.to_period("Q"), "רבעוני"
    else:
        key, label = df["cdate"].dt.to_period("Y"), "שנתי"
    freq = key.dt.freq
    rng = pd.period_range(key.min(), key.max(), freq=freq)
    cnt = key.value_counts().reindex(rng, fill_value=0).sort_index()
    return [str(p) for p in rng], [int(v) for v in cnt.cumsum()], label


def insight_peak(years, total):
    ys = sorted(years.items(), key=lambda kv: (-kv[1], kv[0]))
    y, n = ys[0]
    if n / total < PEAK_SHARE:
        return None
    return f"שנת {y} הייתה שנת השיא בהוספת מכשירים: {_int(n)} רשומות, {_pct(n / total)} מכלל המאגר."


def insight_pace(years, last_year, partial, upto):
    full = sorted(y for y in years if y < last_year or not partial)
    if len(full) < 2:
        return None
    a, b = full[-2], full[-1]
    na, nb = years[a], years[b]
    if na == 0:
        return None
    ch = (nb - na) / na
    if abs(ch) < CHANGE_MIN:
        word = f"בקצב דומה ({_int(nb)} לעומת {_int(na)})"
    elif ch > 0:
        word = f"בעלייה של {_pct(ch)} ({_int(nb)} לעומת {_int(na)})"
    else:
        word = f"בירידה של {_pct(-ch)} ({_int(nb)} לעומת {_int(na)})"
    tail = (f" בשנת {last_year}, עד {upto}, נוספו {_int(years[last_year])}." if partial else "")
    return f"בשנת {b} נוספו מכשירים {word} ביחס לשנת {a}.{tail}"


def insight_city(cities, n_known, total):
    if cities.empty:
        return None
    top = cities.iloc[0]
    if top / total < CITY_LEAD_SHARE:
        return None
    top5 = int(cities.head(5).sum())
    names = ", ".join(cities.head(5).index)
    miss = total - n_known
    note = f" ({_int(miss)} רשומות ללא יישוב מזוהה אינן נספרות)" if miss else ""
    return (f"{cities.index[0]} מובילה עם {_int(top)} מכשירים ({_pct(top / total)}); "
            f"חמש הערים המובילות ({names}) מחזיקות יחד {_pct(top5 / total)} מהמאגר{note}.")


def insight_allday(df):
    s, k = _share24(df)
    if s is None or k < MIN_CAT_KNOWN:
        return None
    miss = len(df) - k
    note = f"; לגבי {_int(miss)} רשומות הנתון חסר" if miss else ""
    return (f"מתוך {_int(k)} מכשירים עם נתון על שעות פעילות, {_pct(s)} מסומנים כזמינים "
            f"מסביב לשעון{note}.")


def _gap_insight(df, key, minimum, gap_min, what):
    rows = []
    for n, g in df.groupby(key, sort=True):
        if n in (OTHER, NO_NAME) or n == "":
            continue
        s, k = _share24(g)
        if s is not None and k >= minimum:
            rows.append((n, s, k))
    if len(rows) < 2:
        return None
    hi = sorted(rows, key=lambda r: (-r[1], r[0]))[0]
    lo = sorted(rows, key=lambda r: (r[1], r[0]))[0]
    if hi[1] - lo[1] < gap_min:
        return None
    return (f"{what}: ב{hi[0]} {_pct(hi[1])} מהמכשירים זמינים מסביב לשעון, לעומת {_pct(lo[1])} "
            f"ב{lo[0]} (מקבוצות עם לפחות {_int(minimum)} רשומות עם נתון).")


def insight_cat(cats, total):
    ident = cats.drop(labels=[OTHER, NO_NAME], errors="ignore")
    if ident.empty:
        return None
    top = ident.iloc[0]
    if top / total < CAT_LEAD_SHARE:
        return None
    return (f"סוג המקום הנפוץ ביותר, לפי שם המיקום: {ident.index[0]} — {_int(top)} מכשירים "
            f"({_pct(top / total)}). {_pct(int(ident.sum()) / total)} מהרשומות סווגו לסוג מקום לפי מילות מפתח בשם.")


def insight_floor(df):
    f = df[df["flr"].notna()]
    if len(f) < MIN_CAT_KNOWN:
        return None
    g = int((f["flr"] == "קרקע / כניסה").sum())
    if g / len(f) < GROUND_MIN:
        return None
    under = int((f["flr"] == "מתחת לקרקע").sum())
    extra = f"; {_int(under)} מתחת לקרקע" if under else ""
    return (f"{_pct(g / len(f))} מ-{_int(len(f))} המכשירים עם נתון על קומה נמצאים בקומת הקרקע או "
            f"בכניסה{extra}.")


def insight_photo(df):
    n = int(df["image"].sum())
    if n == 0:
        return None
    return f"ל-{_int(n)} מכשירים ({_pct(n / len(df))}) מצורפת תמונה של המיקום."


def insight_updated(df):
    ok = df["udate"].notna()
    if ok.sum() < MIN_CAT_KNOWN:
        return None
    n = int((df["udate"] > df["cdate"]).sum())
    if n == 0:
        return None
    return (f"{_pct(n / int(ok.sum()))} מהרשומות עם תאריך עדכון עודכנו לאחר יצירתן; "
            f"עדכון אחרון במאגר: {df['udate'].max():%d.%m.%Y}.")


def insight_source(df):
    pref = df["id"].str.extract(r"^([A-Za-z]+)")[0].fillna("")
    vc = _rank(pref[pref != ""])
    if len(vc) < 2:
        return None
    top = vc.index[0]
    return (f"המזהים מגיעים מ-{_int(len(vc))} קידומות שונות; הקידומת ‎{top}‎ "
            f"מכסה {_pct(int(vc.iloc[0]) / len(df))} מהרשומות.")


def compute(frames):
    df, n_bad, n_map = _prepare(frames["main"])
    total = len(df)
    if total == 0:
        return {"agent_data": {"summary_he": "אין רשומות תקינות", "dataset_kind": "map"},
                "kpis": {}, "charts": {}, "insights": []}

    # growth
    df["year"] = df["cdate"].dt.year
    yc = df["year"].value_counts()
    y0, y1 = int(yc.index.min()), int(yc.index.max())
    years = {y: int(yc.get(y, 0)) for y in range(y0, y1 + 1)}
    maxd = df["cdate"].max()
    partial = not (maxd.month == 12 and maxd.day >= 25)
    upto = f"{maxd:%d.%m.%Y}"
    ynames = [str(y) for y in years]
    yvals = [years[y] for y in years]
    t_year = [{"name": n + (" (חלקית)" if partial and n == str(y1) else ""),
               "count": _int(v), "share": _pct(v / total, 1)} for n, v in zip(ynames, yvals)]
    cum_x, cum_y, gran = _periods(df)

    # cities
    cities_all = _rank(df.loc[df["city"] != "", "city"])
    n_city_known = int(cities_all.sum())
    top_c = list(cities_all.head(TOP_CITIES).index)
    city_stack = _stack(df, "city", top_c)
    t_city = _stack_table(city_stack)

    # venue categories
    cats = _rank(df["cat"])
    cat_names = [c for c in cats.index if c not in (OTHER, NO_NAME)]
    n_unclass = total - int(cats.drop(labels=[OTHER, NO_NAME], errors="ignore").sum())
    cat_stack = _stack(df, "cat", cat_names)
    t_cat = _stack_table(cat_stack)

    # floors
    fl = df["flr"].dropna()
    fvc = fl.value_counts()
    fnames = [n for n in FLOOR_ORDER if n in fvc.index]
    fvals = [int(fvc[n]) for n in fnames]
    t_floor = [{"name": n, "count": _int(v), "share": _pct(v / len(fl), 1)}
               for n, v in zip(fnames, fvals)]

    # 24/7 by creation year
    ay_n, ay_v, t_ay = [], [], []
    for y in years:
        g = df[df["year"] == y]
        s, k = _share24(g)
        if s is None or k < MIN_CAT_KNOWN:
            continue
        ay_n.append(str(y))
        ay_v.append(round(s * 100, 1))
        t_ay.append({"name": str(y), "known": _int(k), "share": _pct(s, 1)})

    # last update year
    ud = df.loc[df["udate"].notna(), "udate"].dt.year.value_counts().sort_index()
    ud_n = [str(int(y)) for y in ud.index]
    ud_v = [int(v) for v in ud.values]
    t_ud = [{"name": n, "count": _int(v), "share": _pct(v / sum(ud_v), 1)}
            for n, v in zip(ud_n, ud_v)]

    s24, k24 = _share24(df)
    last12 = int((df["cdate"] > maxd - pd.Timedelta(days=365)).sum())
    n_cities = int(cities_all.size)

    rules = [
        ("peak", insight_peak(years, total)),
        ("pace", insight_pace(years, y1, partial, upto)),
        ("city", insight_city(cities_all, n_city_known, total)),
        ("allday", insight_allday(df)),
        ("allday_city", _gap_insight(df[df["city"] != ""], "city", MIN_CITY_KNOWN, GAP_PP_CITY,
                                     "פער בין ערים")),
        ("allday_cat", _gap_insight(df, "cat", MIN_CAT_KNOWN, GAP_PP_CAT, "פער בין סוגי מקומות")),
        ("category", insight_cat(cats, total)),
        ("floor", insight_floor(df)),
        ("photo", insight_photo(df)),
        ("updated", insight_updated(df)),
        ("source", insight_source(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    kpis = {
        "total": {"value": total, "display": _int(total), "tone": "brand",
                  "label": "מכשירי החייאה במאגר"},
        "cities": {"value": n_cities, "display": _int(n_cities), "tone": "brand",
                   "label": "יישובים שונים"},
        "allday": {"value": s24 or 0, "display": _pct(s24) if s24 is not None else "—",
                   "tone": ("ok" if (s24 or 0) >= 0.5 else "info"),
                   "label": "מהמכשירים עם נתון זמינים מסביב לשעון"},
        "last12": {"value": last12, "display": _int(last12), "tone": "brand",
                   "label": f"מכשירים שנוספו ב-12 החודשים שעד {upto}"},
    }

    bad_note = (f" {_int(n_bad)} שורות בקובץ הן שאריות של תאים מרובי שורות או חסרות מיקום "
                f"ותאריך תקינים, ולכן לא נספרו." if n_bad else "")
    labels = {
        "lede": (f"{_int(total)} מכשירי החייאה (AED) שמופו על ידי מתנדבים ורשויות ב-"
                 f"{_int(n_cities)} יישובים, עם מיקום מדויק, קומה ושעות זמינות. המאגר גדל מ-"
                 f"{y0} עד {upto}.{bad_note}"),
        "map_note": (f"{_int(total)} מכשירים עם מיקום ותאריך תקינים. לחצו על סמן כדי לראות את שם המקום והקומה, "
                     f"ועל אשכול כדי להתקרב. פרטי קשר אינם מוצגים."
                     + (f" המפה מציגה {_int(n_map)} נקודות, כי שורות עם קואורדינטות שגויות במקור "
                        f"נשארות עליה." if n_map != total else "")),
        "year_note": (f"מספר המכשירים שנרשמו בכל שנה לפי תאריך היצירה"
                      + (f"; שנת {y1} חלקית (עד {upto})." if partial else ".")),
        "year_aria": f"תרשים עמודות: מכשירים שנוספו בכל שנה, {len(years)} שנים.",
        "year_caption": "מספר המכשירים שנוספו בכל שנה.",
        "cum_note": f"סך המכשירים במאגר לאורך זמן (מצטבר, {gran}), לפי תאריך היצירה.",
        "cum_aria": f"תרשים קו: מספר המכשירים המצטבר, {len(cum_x)} נקודות {gran}.",
        "city_note": (f"{len(top_c)} היישובים עם הכי הרבה מכשירים, לפי הישוב שזוהה מהמיקום. "
                      f"הצבע מראה כמה מהם זמינים מסביב לשעון."),
        "city_aria": f"תרשים עמודות אופקי מוערם: מכשירים ב-{len(top_c)} יישובים, לפי זמינות.",
        "city_caption": "מכשירים ויישוב, ושיעור הזמינים 24 שעות מתוך אלה עם נתון.",
        "cat_note": ("סוג המקום נקבע לפי מילות מפתח בשם המיקום (למשל קופת חולים, דוכן הפיס, "
                     "קיבוץ). " + f"{_int(n_unclass)} רשומות ({_pct(n_unclass / total)}) ללא שם מזוהה אינן בתרשים."),
        "cat_aria": f"תרשים עמודות אופקי מוערם: מכשירים לפי {len(cat_names)} סוגי מקומות וזמינות.",
        "cat_caption": "מכשירים לפי סוג מקום, ושיעור הזמינים 24 שעות.",
        "floor_note": f"קומת המכשיר כפי שדווחה, עבור {_int(len(fl))} רשומות עם נתון.",
        "floor_aria": f"תרשים עמודות: מכשירים לפי קומה, {len(fnames)} קבוצות.",
        "floor_caption": "מספר המכשירים לפי קומה.",
        "ay_note": ("שיעור המכשירים הזמינים מסביב לשעון, לפי שנת הוספה "
                    "(רק שנים עם מספיק רשומות עם נתון)."),
        "ay_aria": f"תרשים קו: שיעור המכשירים הזמינים 24 שעות לפי שנת הוספה, {len(ay_n)} שנים.",
        "ay_caption": "שיעור הזמינים 24 שעות לפי שנת הוספה.",
        "ud_note": "שנת העדכון האחרון של כל רשומה — כמה מהמאגר נבדק לאחרונה ומה נשאר ישן.",
        "ud_aria": f"תרשים עמודות: רשומות לפי שנת העדכון האחרון, {len(ud_n)} שנים.",
        "ud_caption": "מספר הרשומות לפי שנת העדכון האחרון.",
    }

    return {
        "agent_data": {
            "summary_he": (f"מפה של {_int(total)} מכשירי החייאה (AED) ב-{_int(n_cities)} יישובים, "
                           f"עם התפלגות לפי יישוב, סוג מקום, קומה וזמינות מסביב לשעון, "
                           f"וקצב הוספת המכשירים מ-{y0}."),
            "dataset_kind": "map",
            "suggested_tags": ["דפיברילטורים", "החייאה", "הצלת חיים", "בריאות בקהילה", "מפה"],
            "temporal_coverage": f"{y0}/{y1}",
            "spatial_coverage": "ישראל",
            "related_ids": ["75073d17-8db5-471e-9a93-3b447b79fb3c", "a906f71d-e4c2-40d2-a16e-dd07e3f04a13", "566c2420-1b00-4813-8a75-c6d8750c5ec8", "209fad5c-de35-49c4-a6f4-164a0c79632c", "d25f8679-13bc-4082-bf6e-6156e1d2df60"],
        },
        "kpis": kpis,
        "charts": {
            "year": {"names": ynames, "values": yvals},
            "cum": {"x": cum_x, "y": cum_y},
            "city": city_stack,
            "cat": cat_stack,
            "floor": {"names": fnames, "values": fvals},
            "ay": {"names": ay_n, "values": ay_v},
            "ud": {"names": ud_n, "values": ud_v},
        },
        "tables": {"year": t_year, "city": t_city, "cat": t_cat, "floor": t_floor,
                   "ay": t_ay, "ud": t_ud},
        "has_ay": len(ay_n) >= 2,
        "has_ud": len(ud_n) >= 2,
        "has_floor": len(fnames) >= 2,
        "has_city": len(top_c) >= 2,
        "labels": labels,
        "insights": insights,
    }
