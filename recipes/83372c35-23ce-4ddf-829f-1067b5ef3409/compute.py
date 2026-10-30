"""רשימת השמאים המכריעים: the Ministry of Justice list of decisive appraisers.

One row per appraiser (26 when authored): name, postal address (street or
PO box, then "~" and the settlement), landline, mobile, fax and e-mail.

Decisive appraisers act in a public, professional capacity (they decide
betterment-levy and compensation disputes under the Planning and Building
Law), so the page names them together with their settlement. Street
addresses, phone numbers and e-mail addresses never reach the page: they
stay in the shell's explorer. E-mail is read only for its domain class
(own office domain / public webmail / ISP mailbox); phones only for whether
the field is filled.

Settlements are mapped to the six Ministry of Interior districts (plus
Judea and Samaria) through a fixed lookup; a settlement missing from the
lookup lands in a disclosed "לא סווג" bucket, so new names flow through.
"""
import re

import pandas as pd

TOP_CITIES = 24
DIRECTORY_CAP = 120
NAME, ADDR, TEL, MOB, FAX, MAIL = "שם שמאי", "כתובת", "טלפון", "נייד", "פקס", "דוא~ל"

DISTRICTS = ["ירושלים", "הצפון", "חיפה", "המרכז", "תל אביב", "הדרום", "יהודה ושומרון"]
UNMAPPED = "לא סווג"
DISTRICT_OF = {}
for _d, _cities in {
    "ירושלים": "ירושלים|בית שמש|מבשרת ציון|מבוא ביתר|אורה|צור הדסה|אבו גוש|מוצא עילית|קריית יערים|"
               "נווה אילן|קריית ענבים|צובה|בית זית|אבן ספיר|עין כרם|טלז סטון",
    "הצפון": "נהריה|יפיע|נצרת|נוף הגליל|נצרת עילית|עפולה|טבריה|צפת|כרמיאל|מעלות-תרשיחא|מעלות תרשיחא|"
             "קריית שמונה|בית שאן|מגדל העמק|שפרעם|סח'נין|עכו|יקנעם עילית|קצרין|ראש פינה|"
             "ריינה|כפר כנא|טמרה|עראבה|מגאר|כפר ורדים|שלומי|מטולה|יוקנעם עילית|כנרת|"
             "יוקנעם",
    "חיפה": "חיפה|עתלית|בנימינה|בנימינה-גבעת עדה|חדרה|קריית אתא|קריית ביאליק|קריית מוצקין|קריית ים|"
            "נשר|טירת כרמל|פרדס חנה-כרכור|פרדס חנה|אור עקיבא|קיסריה|עספיא|דאלית אל-כרמל|"
            "טבעון|קריית טבעון|רכסים|יקנעם|פוריידיס|ג'סר א-זרקא|באקה אל-גרביה|"
            "מעגן מיכאל|עין הוד|גבעת עדה|זכרון יעקב|אום אל-פחם",
    "המרכז": "רעננה|ראשון לציון|הוד השרון|שוהם|רחובות|כפר יונה|יהוד-מונוסון|יהוד|מודיעין-מכבים-רעות|"
             "מודיעין|פתח תקווה|פתח תקוה|כפר סבא|נתניה|רמלה|לוד|נס ציונה|ראש העין|אלעד|"
             "גדרה|יבנה|באר יעקב|קדימה-צורן|קדימה|אבן יהודה|תל מונד|גני תקווה|סביון|"
             "כוכב יאיר|צור יגאל|ג'לג'וליה|טייבה|טירה|קלנסווה|כפר קאסם|מזכרת בתיה|"
             "קריית עקרון|גן יבנה|בית דגן",
    "תל אביב": "תל אביב-יפו|תל אביב|יפו|בני ברק|רמת השרון|הרצליה|רמת גן|גבעתיים|חולון|בת ים|"
               "קריית אונו|גבעת שמואל|אור יהודה|אזור|כפר שמריהו",
    "הדרום": "באר שבע|אשדוד|אשקלון|אילת|דימונה|קריית גת|נתיבות|שדרות|אופקים|ירוחם|מצפה רמון|"
             "קריית מלאכי|רהט|עומר|להבים|מיתר|ערד|באר טוביה|כרמים",
    "יהודה ושומרון": "אריאל|מעלה אדומים|ביתר עילית|מודיעין עילית|אפרת|קרני שומרון|אלפי מנשה|"
                     "קריית ארבע|עמנואל|אורנית|גבעת זאב|קדומים|בית אל|עלי|שילה|אלקנה|קדר|"
                     "הר אדר|כוכב יעקב",
}.items():
    for _c in _cities.split("|"):
        DISTRICT_OF.setdefault(_c, _d)

WEBMAIL = re.compile(r"^(g(oogle)?mail|yahoo|hotmail|outlook|live|msn|aol|icloud|me|walla|"
                     r"proton(mail)?|gmx|ymail|nana10?)\.")
ISP = re.compile(r"^(bezeqint|012|013|013net|netvision|zahav|internet-zahav|barak|smile|"
                 r"inter|actcom|017|018|hot|partner|orange|cellcom|bezeq)\.")
MAIL_OWN, MAIL_WEB, MAIL_ISP, MAIL_NONE = "דומיין משרדי עצמאי", "דוא״ל בספק ציבורי", "תיבה אצל ספק אינטרנט", "ללא דוא״ל"
MAIL_COLOR = {MAIL_OWN: "#0068f5", MAIL_WEB: "#6c9be8", MAIL_ISP: "#0b3668", MAIL_NONE: "#6c757d"}
WORDS = {1: "אחד", 2: "שני", 3: "שלושה", 4: "ארבעה", 5: "חמישה", 6: "שישה", 7: "שבעה",
         8: "שמונה", 9: "תשעה", 10: "עשרה"}


def n(v):
    return f"{int(v):,}"


def pct(a, b):
    return f"{a / b * 100:.0f}%" if b else "0%"


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ו" + ("-" if re.match(r"[A-Za-z0-9]", items[-1]) else "") + items[-1]


def appraisers(k):
    return "שמאי מכריע אחד" if k == 1 else f"{n(k)} שמאים מכריעים"


def _norm_city(raw):
    s = re.sub(r"\s*-\s*", "-", str(raw)).strip(" .,~\t")
    s = re.sub(r"\s+", " ", s)
    alias = {"תל אביב": "תל אביב-יפו", "תל-אביב-יפו": "תל אביב-יפו", "תל אביב יפו": "תל אביב-יפו",
             "מודיעין": "מודיעין-מכבים-רעות", "פתח תקוה": "פתח תקווה", "יהוד": "יהוד-מונוסון"}
    return alias.get(s, s)


def _city(addr):
    parts = [p.strip() for p in str(addr).split("~")]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return ""
    return _norm_city(parts[-1])


def _is_pobox(addr):
    s = str(addr).strip()
    return bool(re.match(r'^(ת\s*[.~"״׳\']\s*ד|תא דואר)', s))


def _mail_class(v):
    v = str(v).strip().lower()
    if "@" not in v:
        return MAIL_NONE
    dom = v.rsplit("@", 1)[1]
    if WEBMAIL.match(dom):
        return MAIL_WEB
    if ISP.match(dom):
        return MAIL_ISP
    return MAIL_OWN


def _filled(v):
    return len(re.sub(r"\D", "", str(v))) >= 7


def _counts(s):
    vc = s.value_counts()
    return sorted(((str(k), int(v)) for k, v in vc.items()), key=lambda kv: (-kv[1], kv[0]))


def compute(frames):
    raw = frames["main"].copy()
    for c in (NAME, ADDR, TEL, MOB, FAX, MAIL):
        raw[c] = raw[c].astype(str).str.strip()
    df = raw[raw[NAME] != ""].copy()
    df = df.drop_duplicates(subset=[NAME, ADDR, MOB, MAIL]).copy()
    df["name"] = df[NAME].str.replace(r"\s+", " ", regex=True)
    df["city"] = df[ADDR].map(_city)
    df["district"] = df["city"].map(lambda c: DISTRICT_OF.get(c, UNMAPPED) if c else UNMAPPED)
    df["pobox"] = df[ADDR].map(_is_pobox)
    df["mail"] = df[MAIL].map(_mail_class)
    df["has_tel"] = df[TEL].map(_filled)
    df["has_mob"] = df[MOB].map(_filled)
    df["has_fax"] = df[FAX].map(_filled)
    df = df.sort_values(["name", "city", ADDR, MOB, MAIL], kind="mergesort").reset_index(drop=True)

    total = len(df)
    if total == 0:
        raise ValueError("no appraisers in the list")

    # Districts (fixed order, unmapped last; empty districts kept so a gap is visible).
    dist_counts = df["district"].value_counts()
    dist_rows = [(d, int(dist_counts.get(d, 0))) for d in DISTRICTS]
    if int(dist_counts.get(UNMAPPED, 0)):
        dist_rows.append((UNMAPPED, int(dist_counts[UNMAPPED])))
    mapped = [(d, v) for d, v in dist_rows if d != UNMAPPED]
    top_d = max(v for _, v in mapped)
    lead_d = [d for d, v in mapped if v == top_d and v > 0]
    empty_d = [d for d, v in mapped if v == 0 and d != "יהודה ושומרון"]
    unmapped_n = int(dist_counts.get(UNMAPPED, 0))
    center_n = int(dist_counts.get("המרכז", 0)) + int(dist_counts.get("תל אביב", 0))
    periph_n = int(dist_counts.get("הצפון", 0)) + int(dist_counts.get("הדרום", 0))

    # Settlements.
    known = df[df["city"] != ""]
    cities = _counts(known["city"])
    n_cities = len(cities)
    top_c = cities[:TOP_CITIES]
    rest_c = sum(v for _, v in cities[TOP_CITIES:])
    no_city = total - len(known)
    single_cities = sum(1 for _, v in cities if v == 1)

    # Contact channels.
    ch = [("טלפון נייד", int(df["has_mob"].sum())), ("דוא״ל", int((df["mail"] != MAIL_NONE).sum())),
          ("טלפון נוסף", int(df["has_tel"].sum())), ("פקס", int(df["has_fax"].sum()))]
    mail_rows = [(k, int((df["mail"] == k).sum())) for k in (MAIL_OWN, MAIL_WEB, MAIL_ISP, MAIL_NONE)]
    mail_rows = [(k, v) for k, v in mail_rows if v > 0]
    own_n = int((df["mail"] == MAIL_OWN).sum())
    web_n = int((df["mail"] == MAIL_WEB).sum())
    with_mail = int((df["mail"] != MAIL_NONE).sum())
    pobox_n = int(df["pobox"].sum())

    # Directory: district → appraisers (name + settlement).
    order = {d: i for i, d in enumerate(DISTRICTS + [UNMAPPED])}
    directory = []
    for d in sorted(df["district"].unique(), key=lambda x: order.get(x, 99)):
        sub = df[df["district"] == d].sort_values(["city", "name"], kind="mergesort")
        for _, r in sub.iterrows():
            directory.append({"district": d, "name": r["name"], "city": r["city"] or "לא צוין"})
    dir_shown = directory[:DIRECTORY_CAP]

    # ---- insights -------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # District concentration.
    if total >= 5 and lead_d:
        share = top_d / total
        if len(lead_d) == 1:
            t = (f"מחוז {lead_d[0]} מוביל עם {appraisers(top_d)} מתוך {n(total)} ברשימה ({pct(top_d, total)}).")
        else:
            t = (f"מחוזות {join_he(lead_d)} מובילים בתיקו, עם {appraisers(top_d)} בכל אחד "
                 f"({pct(top_d, total)} מהרשימה כל אחד).")
        if center_n and len(lead_d) == 1 and share < 0.5:
            t += f" יחד, מחוזות המרכז ותל אביב מרכזים {n(center_n)} שמאים ({pct(center_n, total)})."
        add("districts", t)

    # Periphery coverage.
    if total >= 5:
        north = int(dist_counts.get("הצפון", 0))
        south = int(dist_counts.get("הדרום", 0))
        if south <= 2 or north <= 2:
            def cities_of(d):
                return join_he(sorted(df.loc[df["district"] == d, "city"].unique()))
            bits = []
            for d, k in (("הדרום", south), ("הצפון", north)):
                if k == 0:
                    bits.append(f"במחוז {d} אין אף שמאי מכריע ברשימה")
                elif k <= 2:
                    bits.append(f"במחוז {d} {'רשום' if k == 1 else 'רשומים'} רק {appraisers(k)} ({cities_of(d)})")
            if bits:
                add("periphery", "; ".join(bits) + f", לעומת {n(center_n)} במחוזות המרכז ותל אביב.")
    if empty_d and total >= 5:
        add("empty", f"אין ברשימה שמאי מכריע שכתובתו במחוז {join_he(empty_d)}." if len(empty_d) == 1
            else f"אין ברשימה שמאי מכריע שכתובתו במחוזות {join_he(empty_d)}.")

    # Settlements spread.
    if n_cities >= 3:
        top_v = cities[0][1]
        leaders = [c for c, v in cities if v == top_v]
        if top_v >= 2:
            if len(leaders) == 1:
                t = f"{leaders[0]} היא היישוב עם הכי הרבה שמאים מכריעים ({n(top_v)})"
            else:
                cnt = WORDS.get(top_v, n(top_v))
                t = f"{join_he(leaders)} מובילות עם {cnt} שמאים מכריעים כל אחת"
            t += f"; הרשימה פרושה על {n(n_cities)} יישובים, ובהם {n(single_cities)} עם שמאי יחיד."
        else:
            t = f"כל אחד מ-{n(total)} השמאים רשום ביישוב אחר: {n(n_cities)} יישובים בסך הכול."
        add("cities", t)

    # E-mail domain mix.
    if with_mail >= 5:
        if own_n > web_n:
            t = (f"{n(own_n)} מהשמאים ({pct(own_n, total)}) מתכתבים מדומיין משרדי עצמאי, "
                 f"ו-{n(web_n)} מתיבה בספק דוא״ל ציבורי.")
        elif web_n > own_n:
            t = (f"{n(web_n)} מהשמאים ({pct(web_n, total)}) משתמשים בתיבת דוא״ל בספק ציבורי, "
                 f"ו-{n(own_n)} בדומיין משרדי עצמאי.")
        else:
            t = f"מספר זהה של שמאים ({n(own_n)}) משתמש בדומיין משרדי עצמאי ובתיבת דוא״ל בספק ציבורי."
        add("mail", t)

    # Contact completeness.
    mob = ch[0][1]
    tel = ch[2][1]
    fax = ch[3][1]
    if total >= 5:
        if mob == total:
            t = f"לכל השמאים ברשימה מופיע טלפון נייד"
        else:
            t = f"ל-{n(mob)} מתוך {n(total)} השמאים מופיע טלפון נייד"
        t += f", ול-{n(tel)} בלבד מספר טלפון נוסף" if tel else ", ואף אחד לא מסר מספר טלפון נוסף"
        t += "; אף רשומה אינה כוללת מספר פקס." if fax == 0 else ("; רשומה אחת כוללת מספר פקס." if fax == 1 else f"; {n(fax)} רשומות כוללות מספר פקס.")
        add("contact", t)

    if pobox_n and total >= 5:
        add("pobox", (f"{appraisers(pobox_n)} מסר{'' if pobox_n == 1 else 'ו'} תא דואר במקום כתובת רחוב "
                      f"({pct(pobox_n, total)} מהרשימה)."))

    # ---- KPIs -----------------------------------------------------------
    lead_label = lead_d[0] if len(lead_d) == 1 else "מחוזות מובילים בתיקו"
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "cities": {"value": n_cities, "display": n(n_cities), "tone": "brand"},
        "lead": {"value": round(top_d / total * 100, 1), "display": pct(top_d, total),
                 "tone": "warn" if top_d / total >= 0.4 else "info"},
        "own": {"value": round(own_n / total * 100, 1), "display": pct(own_n, total), "tone": "brand"},
    }

    dist_names = [d for d, _ in dist_rows]
    dist_vals = [v for _, v in dist_rows]
    dist_colors = ["#6c757d" if d == UNMAPPED else ("#0b3668" if v == top_d and v > 0 else "#0068f5")
                   for d, v in dist_rows]
    city_names = [c for c, _ in top_c] + (["יישובים אחרים"] if rest_c else []) + (["לא צוין"] if no_city else [])
    city_vals = [v for _, v in top_c] + ([rest_c] if rest_c else []) + ([no_city] if no_city else [])

    lead_txt = lead_d[0] if len(lead_d) == 1 else join_he(lead_d)
    labels = {
        "lede": (f"רשימת השמאים המכריעים של משרד המשפטים כוללת {appraisers(total)}, "
                 f"הפרושים על {n(n_cities)} יישובים. השמאי המכריע מכריע במחלוקות על שומת היטל השבחה "
                 f"ועל פיצויים לפי חוק התכנון והבנייה (חוק התכנון והבניה). הדף מציג את פריסת השמאים לפי "
                 f"מחוז ויישוב, את דרכי ההתקשרות הזמינות ואת רשימת השמאים לפי מחוז; "
                 f"פרטי הקשר המלאים זמינים בחיפוש שבתחתית הדף."),
        "lead_kpi": f"משקל המחוז המוביל ({lead_label})",
        "dist_note": (f"מספר השמאים לפי מחוז, על פי היישוב שבכתובת. {lead_txt} "
                      f"{'מוביל' if len(lead_d) == 1 else 'מובילים'} עם {n(top_d)}."
                      + (f" {n(unmapped_n)} שמאים ביישובים שלא סווגו למחוז מוצגים בנפרד." if unmapped_n else "")),
        "dist_aria": (f"גרף עמודות: שמאים מכריעים לפי מחוז. {lead_txt} "
                      f"{'מוביל' if len(lead_d) == 1 else 'מובילים'} עם {n(top_d)} מתוך {n(total)}."),
        "dist_caption": "שמאים מכריעים לפי מחוז",
        "cities_note": (((f"היישובים שבהם רשומים הכי הרבה שמאים ({n(len(top_c))} המובילים; "
                          f"השאר מקובצים ב\"יישובים אחרים\")") if rest_c else "מספר השמאים בכל יישוב ברשימה")
                        + f". {n(single_cities)} מתוך {n(n_cities)} היישובים מופיעים פעם אחת בלבד."),
        "cities_aria": (f"גרף עמודות אופקי: שמאים מכריעים לפי יישוב. "
                        f"{cities[0][0] if cities else ''} בראש עם {n(cities[0][1]) if cities else '0'}."),
        "cities_caption": "שמאים מכריעים לפי יישוב",
        "ch_note": (f"בכמה רשומות מופיע כל ערוץ התקשרות (מתוך {n(total)} שמאים). "
                    f"ערוץ \"טלפון נוסף\" הוא שדה הטלפון הנפרד מהנייד."),
        "ch_aria": (f"גרף עמודות: ערוצי התקשרות. טלפון נייד ב-{n(mob)} רשומות, דוא״ל ב-{n(with_mail)}, "
                    f"טלפון נוסף ב-{n(tel)} ופקס ב-{n(fax)}."),
        "ch_caption": "ערוצי התקשרות ברשימה",
        "mail_note": ("סוג כתובת הדוא״ל לפי הדומיין בלבד: דומיין של משרד עצמאי, ספק דוא״ל ציבורי "
                      "(כמו ג׳ימייל) או תיבה אצל ספק אינטרנט. הכתובות עצמן אינן מוצגות כאן."),
        "mail_aria": (f"גרף טבעת: סוגי דוא״ל. דומיין משרדי עצמאי ל-{n(own_n)} שמאים, "
                      f"ספק ציבורי ל-{n(web_n)}."),
        "mail_caption": "שמאים לפי סוג כתובת הדוא״ל",
        "dir_note": (f"שמות השמאים והיישוב שבכתובתם, מקובצים לפי מחוז"
                     + (f" (מוצגים {n(len(dir_shown))} הראשונים מתוך {n(total)})" if len(directory) > len(dir_shown) else "")
                     + ". לכתובת, טלפון ודוא״ל: חיפוש לפי שם בתחתית הדף."),
        "dir_caption": "רשימת השמאים המכריעים לפי מחוז ויישוב",
    }

    summary = f"איתור שמאי מכריע לפי שם, יישוב או מחוז: {appraisers(total)} ב-{n(n_cities)} יישובים"
    if mob == total and with_mail == total:
        summary += ", עם טלפון ודוא״ל לכל שמאי ברשימת משרד המשפטים."
    else:
        summary += " ברשימת משרד המשפטים, עם פרטי קשר."
    if len(summary) > 155:
        summary = f"איתור שמאי מכריע לפי שם, יישוב או מחוז: {appraisers(total)} ב-{n(n_cities)} יישובים."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["שמאי מכריע", "שמאי מקרקעין", "היטל השבחה", "פיצויים", "תכנון ובנייה",
                               "משרד המשפטים"],
            "related_ids": ["669b2652-f75b-4de3-8e6b-0dfa17accef5", "713440a1-9963-4548-a7d9-9d9c9da54f62"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "districts": {"names": dist_names, "values": dist_vals, "colors": dist_colors},
            "cities": {"names": city_names, "values": city_vals},
            "channels": {"names": [k for k, _ in ch], "values": [v for _, v in ch], "total": total},
            "mail": {"items": [{"name": k, "value": v, "itemStyle": {"color": MAIL_COLOR[k]}} for k, v in mail_rows]},
        },
        "tables": {
            "districts": [{"name": d, "count": n(v), "share": pct(v, total)} for d, v in dist_rows],
            "cities": [{"name": c, "count": n(v)} for c, v in zip(city_names, city_vals)],
            "channels": [{"name": k, "count": n(v), "share": pct(v, total)} for k, v in ch],
            "mail": [{"name": k, "count": n(v), "share": pct(v, total)} for k, v in mail_rows],
            "directory": dir_shown,
        },
        "insights": insights,
        "labels": labels,
    }
