"""General permit holders for collecting, transferring or delivering letters
(courier / express / registered / international mail), Ministry of
Communications. One row per permit holder: name, contact channels, a
free-text address and the permit's expiry date.

The page aggregates: expiry calendar, city (parsed from the address),
legal form and service words in the business name, which contact channels
are listed and what kind of email domain. Contact details themselves are
never printed (the shell's explorer carries the rows).
"""
import re

import pandas as pd
from govlib import fmt, frame

NAME = "שם בעל היתר"
PHONE = "טלפון"
MOBILE = "נייד"
FAX = "פקס"
ADDRESS = "כתובת"
EMAIL = "מייל"
EMAIL2 = "מייל נוסף"
EXPIRY = "תוקף היתר עד ליום"

UNKNOWN_CITY = "לא זוהה"
TOP_CITIES = 10
YEAR_MIN, YEAR_MAX = 2000, 2100   # plausible permit-expiry years

# ── city from the free-text address ────────────────────────────────────────
# Known abbreviations and spellings → one name. Anything else passes through
# as written (hyphens → spaces), so a new city shows up under its own name.
CITY_ALIASES = {
    'ת"א': "תל אביב", "תא": "תל אביב", "תל אביב יפו": "תל אביב",
    'ר"ג': "רמת גן", 'רשל"צ': "ראשון לציון", 'פ"ת': "פתח תקווה",
    "פתח תקוה": "פתח תקווה", "קרית אתא": "קריית אתא", 'ב"ש': "באר שבע",
    'נתב"ג': "נתב״ג", "נמל התעופה בן גוריון": "נתב״ג",
    "נמל התעופה בין גוריון": "נתב״ג", "קריית שדה התעופה": "נתב״ג",
    "קרית שדה התעופה": "נתב״ג",
}
_PLACE_PREFIX = re.compile(r'^(?:א\.?ת\.?|אזור תעשייה|ד\.?נ\.?|ד"נ|ק"ק)\s+')
_SETTLEMENT = re.compile(r"(?:קיבוץ|מושב)\s+(.+)$")
_POBOX = re.compile(r'ת\.?\s?ד\.?\s*\d+|ת"ד\s*\d+')
_ZIP = re.compile(r"(?<!\d)\d{5,8}(?!\d)")
_AFTER_NUMBER = re.compile(r"\d+(?:[/-]\d+)?(?:\s?[א-ת]'?(?=\s|$))?\s+(.*)$")
_SPLIT = re.compile(r",|\.\s|\s-\s")


def _norm(s: str) -> str:
    s = s.replace("״", '"').replace("׳", "'")
    return re.sub(r"\s+", " ", s).strip(" ,.-:;")


def city_of(addr: str) -> str:
    s = _norm(addr)
    s = s.split("כתובת למשלוח דואר")[0]      # keep the street address
    s = re.sub(r"^.*?בפועל:", "", s)
    s = _POBOX.sub(" ", s)
    s = s.replace("מיקוד", " ")
    s = _ZIP.sub(" ", s)
    parts = [p for p in (_norm(p) for p in _SPLIT.split(s)) if p]
    for p in reversed(parts):
        m = _AFTER_NUMBER.search(p)
        cand = m.group(1) if m else p
        if re.search(r"\d", cand) or re.match(r"(?:רח'|רחוב|רח|דרך|שדרות)\s", cand):
            continue
        st = _SETTLEMENT.search(cand)
        if st:
            cand = st.group(1)
        prev = None
        while prev != cand:
            prev, cand = cand, _PLACE_PREFIX.sub("", cand)
        cand = _norm(cand)
        cand = CITY_ALIASES.get(cand, cand)
        cand = CITY_ALIASES.get(cand.replace("-", " "), cand.replace("-", " "))
        if cand and len(cand) <= 25:
            return cand
    return UNKNOWN_CITY


# ── what the business name says ────────────────────────────────────────────
# Known service words, multi-label. A name with none of them counts under
# NO_THEME, so new holders always land somewhere.
THEMES = [
    ("שליחויות ושליחים", r"שליח"),
    ("משלוחים והובלות", r"משלוח|הובל"),
    ("אקספרס ומהיר", r"אקספרס|מהיר|express"),
    ("דואר ודיוור", r"דואר|דיוור|הפצה|מייל|post|mail"),
    ("בלדרות", r"בלדר"),
    ("לוגיסטיקה ושילוח", r"לוגיסטי|שילוח|שינוע|קורייר|courier"),
    ("בינלאומי", r"בינלאומי|אינטרנשיונ|\bups\b|\bdhl\b|פדקס|fedex|\bips\b"),
    ("חקירות ושירותים משפטיים", r"חקיר|משפט|איסוף מידע"),
    ("דפוס", r"דפוס"),
]
NO_THEME = "ללא מילת שירות בשם"
_COMPANY = re.compile(r'בע"מ|בע״מ|בעמ\b|ltd', re.IGNORECASE)

# Email domains: free webmail and ISP mailboxes vs. the business's own domain.
FREE_MAIL = re.compile(r"^(?:gmail|googlemail|hotmail|outlook|live|yahoo|walla|icloud|me|msn|aol)\.")
ISP_MAIL = re.compile(r"^(?:bezeqint\.net|012\.net\.il|013\.net|zahav\.net\.il|netvision\.net\.il|"
                      r"inter\.net\.il|smile\.net\.il|barak\.net\.il|actcom\.co\.il|017\.net\.il)$")
EMAIL_KINDS = ["דומיין עסקי", "תיבה חינמית", "תיבה של ספק אינטרנט", "ללא דוא״ל תקין"]


def email_domain(s: str) -> str:
    s = s.strip().lower()
    m = re.search(r"@([a-z0-9.-]+\.[a-z]{2,})", s)
    return m.group(1).strip(".") if m else ""


def email_kind(dom: str) -> str:
    if not dom:
        return EMAIL_KINDS[3]
    if FREE_MAIL.match(dom):
        return EMAIL_KINDS[1]
    if ISP_MAIL.match(dom):
        return EMAIL_KINDS[2]
    return EMAIL_KINDS[0]


def has_digits(s: str, n: int = 7) -> bool:
    return len(re.sub(r"\D", "", s)) >= n


def kpi(value, display, tone="brand"):
    return {"value": value, "display": display, "tone": tone}


def share(n, d):
    return n / d if d else 0.0


def compute(frames):
    df = frames["main"].copy()
    for c in (NAME, PHONE, MOBILE, FAX, ADDRESS, EMAIL, EMAIL2, EXPIRY):
        df[c] = frame.clean_series(df[c])
    df = df[df[NAME] != ""].copy()
    df = df.sort_values([NAME, ADDRESS, EXPIRY], kind="stable").reset_index(drop=True)
    n = len(df)

    # expiry
    df["exp"] = pd.to_datetime(df[EXPIRY], format="%d/%m/%Y", errors="coerce")
    iso = pd.to_datetime(df[EXPIRY].str[:10], format="%Y-%m-%d", errors="coerce")
    df["exp"] = df["exp"].fillna(iso)
    # A mistyped year (2207, 1927) would stretch the year axis and become the
    # "earliest year" everywhere: treat implausible years as undated.
    df.loc[~df["exp"].dt.year.between(YEAR_MIN, YEAR_MAX), "exp"] = pd.NaT
    dated = df[df["exp"].notna()]
    n_dated = len(dated)
    years = dated["exp"].dt.year.astype(int)
    year_counts = years.value_counts().sort_index()
    y_min = int(year_counts.index.min()) if n_dated else None
    y_max = int(year_counts.index.max()) if n_dated else None
    exp_x, exp_y = [], []
    if n_dated:
        for y in range(y_min, y_max + 1):
            exp_x.append(str(y))
            exp_y.append(int(year_counts.get(y, 0)))
    first_year_n = exp_y[0] if exp_y else 0
    two_year_n = sum(exp_y[:2])
    earliest = dated["exp"].min() if n_dated else None
    latest = dated["exp"].max() if n_dated else None
    median_year = int(years.sort_values().iloc[(n_dated - 1) // 2]) if n_dated else None
    peak_year = int(year_counts.sort_index().idxmax()) if n_dated else None
    peak_n = int(year_counts.max()) if n_dated else 0
    soonest = dated.sort_values(["exp", NAME], kind="stable").head(5)
    soonest_rows = [[r[NAME], fmt.d_he(r["exp"])] for _, r in soonest.iterrows()]

    # cities
    df["city"] = df[ADDRESS].map(city_of)
    known = df[df["city"] != UNKNOWN_CITY]
    city_counts = frame.ranked(known["city"])
    n_cities = int(city_counts.size)
    c_labels, c_values = frame.top_other(city_counts, TOP_CITIES)
    n_unknown = int((df["city"] == UNKNOWN_CITY).sum())
    if n_unknown:
        c_labels.append(UNKNOWN_CITY)
        c_values.append(n_unknown)
    city_rows = [[lbl, fmt.int_he(v), fmt.pct(share(v, n))] for lbl, v in zip(c_labels, c_values)]

    # legal form
    df["company"] = df[NAME].str.contains(_COMPANY)
    n_company = int(df["company"].sum())
    n_other_form = n - n_company
    form = {"names": ["חברה בע״מ", "עוסק או עסק שאינו חברה"], "values": [n_company, n_other_form]}

    # service words
    low = df[NAME].str.lower()
    theme_counts = []
    matched_any = pd.Series(False, index=df.index)
    for label, rx in THEMES:
        hit = low.str.contains(rx, regex=True)
        matched_any |= hit
        theme_counts.append((label, int(hit.sum())))
    theme_counts.append((NO_THEME, int((~matched_any).sum())))
    theme_counts = [t for t in theme_counts if t[1] > 0]
    theme_counts.sort(key=lambda t: (t[0] == NO_THEME, -t[1], t[0]))
    themes = {"names": [t[0] for t in theme_counts], "values": [t[1] for t in theme_counts]}

    # contact channels
    has = {
        "טלפון": df[PHONE].map(has_digits),
        "טלפון נייד": df[MOBILE].map(has_digits),
        "פקס": df[FAX].map(has_digits),
        "דוא״ל": df[EMAIL].map(lambda s: bool(email_domain(s))),
        "דוא״ל נוסף": df[EMAIL2].map(lambda s: bool(email_domain(s))),
    }
    contacts = {"names": list(has), "counts": [int(v.sum()) for v in has.values()]}
    contacts["pct"] = [round(share(c, n) * 100, 1) for c in contacts["counts"]]
    n_fax = contacts["counts"][2]
    n_mobile = contacts["counts"][1]

    # email kind (primary address, falling back to the second one)
    df["dom"] = df[EMAIL].map(email_domain)
    df["dom2"] = df[EMAIL2].map(email_domain)
    df["dom_any"] = df["dom"].where(df["dom"] != "", df["dom2"])
    df["ekind"] = df["dom_any"].map(email_kind)
    ek = df["ekind"].value_counts()
    email = {"names": [k for k in EMAIL_KINDS if ek.get(k, 0)],
             "values": [int(ek.get(k, 0)) for k in EMAIL_KINDS if ek.get(k, 0)]}
    n_own = int(ek.get(EMAIL_KINDS[0], 0))
    n_free = int(ek.get(EMAIL_KINDS[1], 0))

    # holders that share a business email domain (same group / brand)
    biz = df[df["ekind"] == EMAIL_KINDS[0]]
    doms = set()
    for _, r in biz.iterrows():
        for d in {r["dom"], r["dom2"]}:
            if d and email_kind(d) == EMAIL_KINDS[0]:
                doms.add((d, r[NAME]))
    by_dom = {}
    for d, name in sorted(doms):
        by_dom.setdefault(d, []).append(name)
    shared = [(d, sorted(set(v))) for d, v in by_dom.items() if len(set(v)) >= 2]
    # one row per group of names (two domains can link the same pair)
    seen, groups = set(), []
    for d, names in sorted(shared, key=lambda t: (t[1], t[0])):
        key = tuple(names)
        if key in seen:
            continue
        seen.add(key)
        groups.append({"domain": d, "names": fmt.join_he(names), "count": len(names)})
    n_grouped = len({nm for g in shared for nm in g[1]})

    # ── KPIs ──
    kpis = {
        "holders": kpi(n, fmt.int_he(n)),
        "cities": kpi(n_cities, fmt.int_he(n_cities)),
        "company": kpi(round(share(n_company, n) * 100, 1), fmt.pct(share(n_company, n)), "info"),
    }
    if n_dated:
        kpis["first_year"] = kpi(first_year_n, fmt.int_he(first_year_n),
                                 "warn" if share(first_year_n, n_dated) >= 0.1 else "brand")
        kpis["span"] = kpi(y_max, f"{y_min}–{y_max}" if y_max != y_min else str(y_min))

    # ── insights ──
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    add("scale", f"הרשימה כוללת {fmt.int_he(n)} בעלי היתר כללי לאיסוף, העברה או מסירה של מכתבים"
        + (f", הרשומים ב-{fmt.int_he(n_cities)} יישובים." if n_cities > 1 else "."))

    if n_cities >= 2 and len(city_counts) >= 2:
        top_city, top_n = city_counts.index[0], int(city_counts.iloc[0])
        second_n = int(city_counts.iloc[1])
        if top_n > second_n and share(top_n, n) >= 0.15:
            top3 = city_counts.head(3)
            t = (f"{top_city} מובילה עם {fmt.int_he(top_n)} בעלי היתר ({fmt.pct(share(top_n, n))}),"
                 f" ושלושת היישובים המובילים ({fmt.join_he(top3.index)}) מרכזים"
                 f" {fmt.int_he(int(top3.sum()))} מהם ({fmt.pct(share(int(top3.sum()), n))}).")
            add("cities", t)

    if n_dated and n_dated >= 5:
        t = (f"תוקף ההיתרים ברשימה פג בין {fmt.d_he(earliest)} ל-{fmt.d_he(latest)}."
             f" {fmt.int_he(first_year_n)} היתרים ({fmt.pct(share(first_year_n, n_dated))}) פגים כבר ב-{y_min},"
             f" השנה המוקדמת ברשימה")
        if len(exp_y) >= 2:
            t += f", ו-{fmt.int_he(two_year_n)} ({fmt.pct(share(two_year_n, n_dated))}) עד סוף {y_min + 1}."
        else:
            t += "."
        add("expiry", t)
        if peak_year != y_min and peak_n >= 3:
            add("peak", f"שנת הפקיעה הנפוצה ביותר היא {peak_year}, עם {fmt.int_he(peak_n)} היתרים;"
                f" חציון שנת הפקיעה הוא {median_year}.")

    if n and 0 < n_company:
        if n_company == n:
            add("form", "כל בעלי ההיתר ברשימה הם חברות בע״מ.")
        else:
            add("form", f"{fmt.int_he(n_company)} מבעלי ההיתר ({fmt.pct(share(n_company, n))}) הם חברות בע״מ,"
                f" ו-{fmt.int_he(n_other_form)} רשומים בשם עסק או בשם אדם, ללא ציון חברה.")

    real_themes = [t for t in theme_counts if t[0] != NO_THEME]
    second_theme = real_themes[1][1] if len(real_themes) > 1 else 0
    if real_themes and real_themes[0][1] >= 3 and real_themes[0][1] > second_theme:
        lead, lead_n = real_themes[0]
        n_none = n - int(matched_any.sum())
        t = (f"מילות השירות הנפוצות בשמות העסקים הן מתחום \"{lead}\": {fmt.int_he(lead_n)} שמות"
             f" ({fmt.pct(share(lead_n, n))}).")
        if n_none:
            t += f" {fmt.int_he(n_none)} שמות ({fmt.pct(share(n_none, n))}) אינם כוללים מילת שירות כלל."
        add("themes", t)

    if n and share(n_fax, n) >= 0.5:
        add("fax", f"{fmt.int_he(n_fax)} מבעלי ההיתר ({fmt.pct(share(n_fax, n))}) עדיין מפרסמים מספר פקס,"
            f" לעומת {fmt.int_he(n_mobile)} ({fmt.pct(share(n_mobile, n))}) שמפרסמים טלפון נייד.")

    if n and n_own and n_free:
        add("email", f"{fmt.int_he(n_own)} בעלי היתר ({fmt.pct(share(n_own, n))}) מתכתבים מדומיין עסקי משלהם,"
            f" ו-{fmt.int_he(n_free)} ({fmt.pct(share(n_free, n))}) מתיבת דוא״ל חינמית.")

    if groups:
        ex = groups[0]["names"]
        add("groups", f"{fmt.int_he(n_grouped)} בעלי היתר חולקים דומיין דוא״ל עסקי עם בעל היתר נוסף"
            f" ({fmt.int_he(len(groups))} קבוצות), למשל {ex}: ככל הנראה עסקים קשורים הרשומים בנפרד.")

    # ── text ──
    top_city_txt = ""
    if len(city_counts):
        top_city_txt = f"{city_counts.index[0]} ({fmt.int_he(int(city_counts.iloc[0]))})"
    lede = (f"רשימת משרד התקשורת של {fmt.int_he(n)} בעלי היתר כללי לשירותי בלדרות, דואר שליחים, דואר מהיר,"
            f" דואר רשום ודואר בינלאומי, לפי חוק הדואר.")
    if top_city_txt:
        lede += f" בעלי ההיתר רשומים ב-{fmt.int_he(n_cities)} יישובים, בראשם {top_city_txt}."
    if n_dated:
        lede += f" תוקף ההיתרים פג בין {y_min} ל-{y_max}."
    summary = (f"{fmt.int_he(n)} בעלי היתר כללי לאיסוף, העברה ומסירה של מכתבים (בלדרות ושליחויות),"
               f" ב-{fmt.int_he(n_cities)} יישובים" + (f", בראשם {top_city_txt}." if top_city_txt else ".")
               + (f" תוקף ההיתרים פג בין {y_min} ל-{y_max}." if n_dated else ""))
    desc = (f"איתור חברת שליחויות או בלדרות בעלת היתר ממשרד התקשורת לפי שם או יישוב:"
            f" {fmt.int_he(n)} בעלי היתר" + (f", הבולטים ב{top_city_txt}." if top_city_txt else "."))

    labels = {
        "lede": lede,
        "holders_kpi": "בעלי היתר ברשימה",
        "cities_kpi": "יישובים",
        "company_kpi": "חברות בע״מ",
        "first_year_kpi": f"היתרים שתוקפם פג ב-{y_min}" if n_dated else "",
        "span_kpi": "טווח שנות פקיעת ההיתרים" if n_dated else "",
        "expiry_note": (f"מספר ההיתרים לפי שנת פקיעת התוקף. השנה המוקדמת ({y_min}) מודגשת:"
                        f" {fmt.int_he(first_year_n)} היתרים פגים בה." if n_dated else ""),
        "expiry_aria": (f"גרף עמודות: היתרים לפי שנת פקיעה, {y_min} עד {y_max}."
                        f" שיא ב-{peak_year} עם {fmt.int_he(peak_n)} היתרים." if n_dated else ""),
        "expiry_caption": "היתרים לפי שנת פקיעת התוקף",
        "soonest_note": "בעלי ההיתר שתוקף היתרם פג ראשון ברשימה.",
        "cities_note": (f"היישוב חולץ מהכתובת. מוצגים {TOP_CITIES} היישובים המובילים, והשאר מקובצים תחת \"אחר\"."
                        + (f" {fmt.int_he(n_unknown)} כתובות ללא יישוב מזוהה מוצגות בנפרד." if n_unknown else "")),
        "cities_aria": (f"גרף עמודות אופקי: בעלי היתר לפי יישוב. {top_city_txt} בראש." if top_city_txt
                        else "גרף עמודות אופקי: בעלי היתר לפי יישוב."),
        "cities_caption": "בעלי היתר לפי יישוב",
        "form_note": "לפי ציון \"בע״מ\" בשם בעל ההיתר.",
        "form_aria": (f"תרשים טבעת: {fmt.int_he(n_company)} חברות בע״מ ו-{fmt.int_he(n_other_form)}"
                      f" עסקים שאינם חברות."),
        "form_caption": "בעלי היתר לפי צורת התאגדות",
        "themes_note": "מילות שירות בשמות העסקים. שם יכול להיספר ביותר מתחום אחד.",
        "themes_aria": (f"גרף עמודות אופקי: מילות שירות בשמות העסקים. בראש: {themes['names'][0]}"
                        f" ({fmt.int_he(themes['values'][0])})." if themes["names"] else "גרף מילות שירות."),
        "themes_caption": "מילות שירות בשמות העסקים",
        "contacts_note": "שיעור בעלי ההיתר שמפרסמים כל ערוץ קשר ברשימה (הפרטים עצמם בטבלת הנתונים למטה).",
        "contacts_aria": (f"גרף עמודות אופקי: ערוצי קשר. {fmt.pct(share(n_fax, n))} מפרסמים פקס"
                          f" ו-{fmt.pct(share(n_mobile, n))} טלפון נייד."),
        "contacts_caption": "ערוצי קשר שמפרסמים בעלי ההיתר",
        "email_note": "סוג הדומיין של כתובת הדוא״ל הראשית (או הנוספת, כשהראשית חסרה).",
        "email_aria": (f"תרשים טבעת: {fmt.int_he(n_own)} בדומיין עסקי ו-{fmt.int_he(n_free)}"
                       f" בתיבה חינמית."),
        "email_caption": "סוג דומיין הדוא״ל של בעלי ההיתר",
        "groups_note": "בעלי היתר שכתובות הדוא״ל שלהם באותו דומיין עסקי: לרוב חברות קשורות או מותג אחד.",
        "groups_caption": "בעלי היתר החולקים דומיין דוא״ל",
    }

    charts = {
        "expiry": {"x": exp_x, "y": exp_y, "first": 0},
        "cities": {"names": c_labels, "values": c_values},
        "form": form,
        "themes": themes,
        "contacts": contacts,
        "email": email,
    }
    tables = {
        "expiry": [[x, fmt.int_he(y), fmt.pct(share(y, n_dated))] for x, y in zip(exp_x, exp_y)],
        "soonest": soonest_rows,
        "cities": city_rows,
        "form": [[nm, fmt.int_he(v), fmt.pct(share(v, n))] for nm, v in zip(form["names"], form["values"])],
        "themes": [[nm, fmt.int_he(v), fmt.pct(share(v, n))] for nm, v in zip(themes["names"], themes["values"])],
        "contacts": [[nm, fmt.int_he(c), fmt.pct_of(p)] for nm, c, p in
                     zip(contacts["names"], contacts["counts"], contacts["pct"])],
        "email": [[nm, fmt.int_he(v), fmt.pct(share(v, n))] for nm, v in zip(email["names"], email["values"])],
        "groups": [[g["names"], g["domain"]] for g in groups],
    }
    flags = {"has_expiry": bool(n_dated), "has_groups": bool(groups),
             "has_form": n_company > 0 and n_other_form > 0}

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "spatial_coverage": "ישראל",
        "seo": {
            "title": "בעלי היתר לשירותי בלדרות ושליחויות | משרד התקשורת",
            "description": desc,
            "name": "רשימת בעלי היתר כללי לאיסוף, העברה או מסירה של מכתבים",
            "alternate_names": [
                "רשימת חברות שליחויות בעלות היתר",
                "בעלי היתר בלדרות",
                "היתר כללי לשירותי דואר שליחים",
                "רשימת בעלי היתר כללי לאיסוף , העברה או מסירה של מכתבים",
            ],
        },
    }
    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
