"""מרכזי טראומה: a small Ministry of Health directory of trauma clinics
(one row per clinic: code, name, city, street, free-text address, email,
two phones, website).

The page is a lookup page first: searchers want "מרכז טראומה ב<עיר>" and a
phone number, so the full directory table sits near the top. Around it the
recipe computes what the registry can honestly say: where the clinics are,
which audience a clinic's name declares (children/youth, adults, military
trauma), which body the contact details point to (by email/website domain),
and how complete the contact details are.

Growth: rows are overwritten in place. New cities, new domains and new names
all flow through (top-N + "אחר" on the city axis, unknown domains fall into
"אחר"). The directory table caps at DIR_CAP rows; past that the shell's
explorer is the full list (the page says so).
"""
import re

import pandas as pd

TOP_CITIES = 15
DIR_CAP = 120
SUMMARY_MAX = 155

# Audience declared in the clinic's own name. Checked in order; a name can
# match more than one group (each counted once per group).
AUDIENCES = [
    ("kids", "ילדים ונוער", ("ילד", "נוער")),
    ("adults", "מבוגרים", ("מבוגר",)),
    ("military", "טראומה צבאית וביטחונית", ("צבאי", "נכי", "משרד הביטחון", "קומבו")),
]
AUD_NONE = "לא צוין בשם המרפאה"

# Known contact domains -> the body they belong to. Matched on the domain
# suffix; anything else is "אחר". Email domain wins over website domain.
DOMAINS = [
    ("clalit.co.il", "שירותי בריאות כללית"),
    ("clalit.org.il", "שירותי בריאות כללית"),
    ("hadassah.org.il", "הדסה"),
    ("sheba.gov.il", "המרכז הרפואי שיבא"),
    ("tasmc.org.il", "המרכז הרפואי תל אביב"),
    ("barzilaimc.org.il", "המרכז הרפואי ברזילי"),
    ("lev-hasharon.co.il", "המרכז הרפואי לב השרון"),
    ("tiratcarmel-med.org.il", "המרכז הרפואי טירת כרמל"),
    ("psmh.health.gov.il", "המרכז הרפואי טירת כרמל"),
    ("mazor.health.gov.il", "המרכז הרפואי מזור"),
    ("rmc.gov.il", "הקריה הרפואית רמב״ם"),
    ("moh.gov.il", "משרד הבריאות"),
    ("health.gov.il", "משרד הבריאות"),
    ("gov.il", "אתר ממשלתי"),
]
DOM_OTHER = "אחר"
DOM_NONE = "ללא דוא״ל ואתר"

HEB_COUNT = {1: "אחת", 2: "שתי", 3: "שלוש", 4: "ארבע", 5: "חמש", 6: "שש",
             7: "שבע", 8: "שמונה", 9: "תשע", 10: "עשר"}


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _n_clinics(n):
    """'מרפאה אחת', 'שתי מרפאות', '12 מרפאות'."""
    if n == 1:
        return "מרפאה אחת"
    if n in HEB_COUNT:
        return f"{HEB_COUNT[n]} מרפאות"
    return f"{n:,} מרפאות"


def _join(items):
    """'א', 'א וב', 'א, ב וג' ("ו-" before a non-Hebrew start)."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = "ו" if re.match(r"[\u05d0-\u05ea]", last) else "ו-"
    return ", ".join(items[:-1]) + " " + conj + last


def _pct(part, whole):
    return f"{(part / whole * 100):.0f}%" if whole else "0%"


def _phone(raw):
    """Display form: '5123*' (RTL-typed star code) -> '*5123'."""
    s = _clean(raw)
    m = re.fullmatch(r"(\d{3,5})\s*\*", s)
    if m:
        return "*" + m.group(1)
    return s


def _tel(display):
    return re.sub(r"[^\d*+]", "", display)


def _host(url):
    s = _clean(url).lower()
    s = re.sub(r"^[a-z]+://", "", s)
    return s.split("/")[0].split("?")[0].split(":")[0]


def _domain_body(email, website):
    for host in (_clean(email).lower().rpartition("@")[2] if "@" in email else "",
                 _host(website) if _clean(website) else ""):
        if not host:
            continue
        for suffix, body in DOMAINS:
            if host == suffix or host.endswith("." + suffix):
                return body
        return DOM_OTHER
    return DOM_NONE


def _valid_url(u):
    u = _clean(u)
    return u if re.match(r"^https://[^\s\"'<>]+$", u, re.I) else ""


# Public webmail: a clinic address there is someone's personal mailbox; kept off the page.
WEBMAIL = ("gmail.com", "hotmail.com", "walla.co.il", "walla.com", "yahoo.com",
           "outlook.com", "live.com", "012.net.il", "bezeqint.net", "netvision.net.il",
           "icloud.com", "zahav.net.il")


def _valid_email(e):
    e = _clean(e)
    if not re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", e):
        return ""
    return "" if e.lower().rpartition("@")[2] in WEBMAIL else e


def _prepare(df):
    out = pd.DataFrame({
        "code": df["institute_code"].map(_clean),
        "name": df["institute_name"].map(_clean),
        "city": df["city"].map(_clean),
        "street_code": df["streetCode"].map(_clean),
        "street": df["street"].map(_clean),
        "address": df["address"].map(_clean),
        "email": df["email"].map(_valid_email),
        "phone": df["phone"].map(_phone),
        "phone2": df["phone2"].map(_phone),
        "website": df["website"].map(_valid_url),
    })
    out = out[out["name"] != ""]
    out = out.drop_duplicates()
    out["city"] = out["city"].where(out["city"] != "", "לא צוין")
    out = out.sort_values(["city", "name", "code", "address"], kind="stable")
    return out.reset_index(drop=True)


def _audiences(name):
    keys = [k for k, _, words in AUDIENCES if any(w in name for w in words)]
    return keys


# ---------------------------------------------------------------- insights

def insight_spread(df, city_counts):
    n, n_city = len(df), len(city_counts)
    if n == 0:
        return None
    s = f"במאגר {_n_clinics(n)} לטיפול בטראומה נפשית ב-{n_city:,} יישובים"
    top = city_counts.iloc[0]
    if n_city >= 2 and city_counts.iloc[0] > city_counts.iloc[1] and top >= 2:
        s += f"; {city_counts.index[0]} מובילה עם {_n_clinics(int(top))}"
    elif int(city_counts.max()) == 1:
        s += ", מרפאה אחת בכל יישוב"
    else:
        multi = list(city_counts[city_counts >= 2].index)
        if multi:
            s += "; יותר ממרפאה אחת יש רק ב" + ", ".join(multi)
    return s + "."


def insight_audience(df, aud_counts):
    n = len(df)
    kids = aud_counts.get("kids", 0)
    adults = aud_counts.get("adults", 0)
    mil = aud_counts.get("military", 0)
    none = aud_counts.get("none", 0)
    if n < 3 or (kids + adults + mil) == 0:
        return None
    parts = []
    if kids:
        parts.append(f"{_n_clinics(kids)} לילדים ולנוער")
    if adults:
        parts.append(f"{_n_clinics(adults)} למבוגרים")
    if mil:
        parts.append(f"{_n_clinics(mil)} לטראומה צבאית או לנכי מערכת הביטחון")
    s = "לפי שם המרפאה: " + ", ".join(parts)
    if none:
        s += f". ב-{none:,} מתוך {n:,} השם אינו מציין קהל יעד"
    return s + "."


def insight_contact(df):
    n = len(df)
    if n < 3:
        return None
    no_phone = df[(df["phone"] == "") & (df["phone2"] == "")]
    no_direct = no_phone[no_phone["email"] == ""]
    nothing = no_direct[no_direct["website"] == ""]
    if no_phone.empty:
        return f"לכל {n:,} המרפאות במאגר מופיע מספר טלפון."
    s = f"ל-{len(no_phone):,} מתוך {n:,} המרפאות ({_pct(len(no_phone), n)}) אין מספר טלפון במאגר"
    if not no_direct.empty:
        s += f", ול-{len(no_direct):,} מהן גם אין דוא״ל"
        if not nothing.empty:
            names = sorted(nothing["name"])
            if len(names) <= 3:
                s += "; " + _join(names) + (" מופיעה" if len(names) == 1 else " מופיעות") \
                     + " ללא כל פרט קשר"
            else:
                s += f"; {len(names):,} מופיעות ללא כל פרט קשר"
    return s + "."


def insight_bodies(body_counts):
    named = body_counts[~body_counts.index.isin([DOM_OTHER, DOM_NONE])]
    if named.empty:
        return None
    top = int(named.iloc[0])
    if top < 2:
        return None
    leaders = list(named[named == top].index)
    if len(leaders) == 1:
        s = (f"לפי כתובת הדוא״ל או האתר, {leaders[0]} הוא הגוף עם הכי הרבה מרפאות במאגר "
             f"({_n_clinics(top)})")
    else:
        s = (f"לפי כתובת הדוא״ל או האתר, {_join(leaders)} הם הגופים עם הכי הרבה מרפאות "
             f"במאגר, {_n_clinics(top)} לכל אחד")
    return s + "."


def insight_shared_address(df):
    # A city-only address is not a shared street address.
    key = df["address"].where((df["address"] != "") & (df["address"] != df["city"]), None)
    g = df[key.notna()].groupby("address")["name"].apply(lambda s: sorted(s))
    g = g[g.map(len) >= 2]
    if g.empty:
        return None
    g = g.sort_index()
    parts = [f"{addr}: {_join(names)}" for addr, names in g.items()]
    if len(g) == 1:
        head = f"{_n_clinics(len(g.iloc[0]))} פועלות באותה כתובת, "
    else:
        head = f"{len(g):,} כתובות משמשות יותר ממרפאה אחת. "
    return head + "; ".join(parts) + "."


def insight_star(df):
    stars = df[df["phone"].str.startswith("*") | df["phone2"].str.startswith("*")]
    if stars.empty:
        return None
    names = sorted(stars["name"])
    if len(names) == 1:
        return f"{names[0]} זמינה גם במספר מקוצר (כוכבית)."
    if len(names) <= 3:
        return (_join(names) + " זמינות גם במספר מקוצר (כוכבית).")
    return f"{len(names):,} מרפאות זמינות גם במספר מקוצר (כוכבית)."


def insight_address_detail(df):
    vague = df[(df["street_code"] == "") & ((df["address"] == "") | (df["address"] == df["city"]))]
    if vague.empty:
        return None
    names = sorted(vague["name"])
    if len(names) == 1:
        return f"לגבי {names[0]} רשום במאגר רק שם היישוב, ללא כתובת רחוב."
    if len(names) <= 3:
        return "רק שם היישוב, ללא כתובת רחוב, רשום לגבי " + _join(names) + "."
    return f"לגבי {len(names):,} מרפאות רשום רק שם היישוב, ללא כתובת רחוב."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["clinics"])
    n = int(len(df))

    city_counts = (df.groupby("city").size().reset_index(name="n")
                   .sort_values(["n", "city"], ascending=[False, True], kind="stable")
                   .set_index("city")["n"])

    aud_counts = {k: 0 for k, _, _ in AUDIENCES}
    aud_counts["none"] = 0
    aud_rows = []
    for name in df["name"]:
        keys = _audiences(name)
        aud_rows.append(keys)
        if not keys:
            aud_counts["none"] += 1
        for k in keys:
            aud_counts[k] += 1
    df = df.assign(aud=[",".join(k) for k in aud_rows])

    df["body"] = [_domain_body(e, w) for e, w in zip(df["email"], df["website"])]
    body_counts = (df.groupby("body").size().reset_index(name="n")
                   .sort_values(["n", "body"], ascending=[False, True], kind="stable")
                   .set_index("body")["n"])
    # keep "אחר" / "ללא" at the end of the chart
    tail = [b for b in (DOM_OTHER, DOM_NONE) if b in body_counts.index]
    body_counts = pd.concat([body_counts.drop(tail), body_counts[tail]])

    has_phone = int(((df["phone"] != "") | (df["phone2"] != "")).sum())
    has_email = int((df["email"] != "").sum())
    has_web = int((df["website"] != "").sum())
    has_two = int(((df["phone"] != "") & (df["phone2"] != "")).sum())
    none_any = int(((df["phone"] == "") & (df["phone2"] == "") & (df["email"] == "")
                    & (df["website"] == "")).sum())
    no_phone = n - has_phone

    rules = [
        ("spread", insight_spread(df, city_counts)),
        ("audience", insight_audience(df, aud_counts)),
        ("contact", insight_contact(df)),
        ("bodies", insight_bodies(body_counts)),
        ("shared_address", insight_shared_address(df)),
        ("star", insight_star(df)),
        ("address_detail", insight_address_detail(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    kpis = {
        "total": {"value": n, "display": f"{n:,}", "tone": "brand"},
        "cities": {"value": int(len(city_counts)), "display": f"{len(city_counts):,}",
                   "tone": "brand"},
        "kids": {"value": aud_counts["kids"], "display": f"{aud_counts['kids']:,}",
                 "tone": "info" if aud_counts["kids"] else "brand"},
        "phone": {"value": has_phone, "display": _pct(has_phone, n),
                  "tone": ("ok" if n and has_phone / n >= 0.8 else
                           "warn" if n and has_phone / n >= 0.5 else "danger")},
    }

    # ---- city chart: top-N + אחר, ascending for horizontal bars (largest on top)
    keep = len(city_counts) if len(city_counts) <= TOP_CITIES + 2 else TOP_CITIES
    top = city_counts.head(keep)
    rest = int(city_counts.iloc[keep:].sum())
    rest_n = int(max(len(city_counts) - keep, 0))
    city_rows = [{"name": c, "n": int(v)} for c, v in top.items()]
    if rest:
        city_rows.append({"name": f"אחר ({rest_n:,} יישובים)", "n": rest})
    city_chart = {"names": [r["name"] for r in city_rows][::-1],
                  "values": [r["n"] for r in city_rows][::-1]}

    # ---- audience chart
    aud_rows_t = [{"name": label, "n": aud_counts[k]} for k, label, _ in AUDIENCES]
    aud_rows_t.append({"name": AUD_NONE, "n": aud_counts["none"]})
    aud_chart = {"names": [r["name"] for r in aud_rows_t],
                 "values": [r["n"] for r in aud_rows_t]}

    # ---- contact completeness chart
    contact_rows = [
        {"name": "טלפון", "n": has_phone},
        {"name": "שני מספרי טלפון", "n": has_two},
        {"name": "דוא״ל", "n": has_email},
        {"name": "אתר אינטרנט", "n": has_web},
        {"name": "ללא כל פרט קשר", "n": none_any},
    ]
    for r in contact_rows:
        r["pct"] = _pct(r["n"], n)
    contact_chart = {"names": [r["name"] for r in contact_rows],
                     "values": [r["n"] for r in contact_rows], "total": n}

    # ---- bodies chart
    body_rows = [{"name": b, "n": int(v)} for b, v in body_counts.items()]
    body_chart = {"names": [r["name"] for r in body_rows][::-1],
                  "values": [r["n"] for r in body_rows][::-1]}

    # ---- directory
    aud_label = {k: label for k, label, _ in AUDIENCES}
    directory = []
    for _, r in df.head(DIR_CAP).iterrows():
        phones = [p for p in (r["phone"], r["phone2"]) if p]
        directory.append({
            "name": r["name"],
            "city": r["city"],
            "address": r["address"] or r["city"],
            "phones": [{"display": p, "tel": _tel(p)} for p in phones if _tel(p)],
            "email": r["email"],
            "website": r["website"],
            "audience": ", ".join(aud_label[k] for k in r["aud"].split(",") if k),
        })

    # ---- summary (meta description)
    cities_list = list(city_counts.index)
    summary = (f"איתור מרכז טראומה נפשית לפי עיר, עם כתובת וטלפון: {_n_clinics(n)} "
               f"ב-{len(city_counts):,} יישובים, מרשימת משרד הבריאות.")
    if len(summary) > SUMMARY_MAX:
        summary = f"איתור מרכז טראומה נפשית לפי עיר: {_n_clinics(n)} ב-{len(city_counts):,} יישובים."

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["טראומה", "בריאות הנפש", "מרפאות", "פוסט טראומה",
                           "טיפול נפשי", "חוסן"],
        "related_ids": ["b08ed183-2c26-490f-aa13-f1a7529c3aca",
                        "5c8651bc-5288-4d46-a3f5-2ebfbe5c9615"],
        "spatial_coverage": "ישראל",
    }

    top_city = city_counts.index[0] if n else ""
    labels = {
        "kpi_total": "מרפאות ומרכזים לטיפול בטראומה",
        "kpi_cities": "יישובים שבהם פועלת לפחות מרפאה אחת",
        "kpi_kids": "מרפאות שבשמן מצוין טיפול בילדים ובנוער",
        "kpi_phone": f"מהמרפאות עם מספר טלפון במאגר ({has_phone:,} מתוך {n:,})",
        "lookup_title": "איתור מרכז טראומה לפי שם או עיר ←",
        "dir_lede": (f"כל המרפאות במאגר ({n:,}), ממוינות לפי יישוב. טלפון, דוא״ל ואתר מופיעים כפי "
                     "שפורסמו; היכן שאין פרט, הוא חסר במקור." if n <= DIR_CAP else
                     f"{DIR_CAP:,} המרפאות הראשונות מתוך {n:,}, ממוינות לפי יישוב. "
                     "הרשימה המלאה בחיפוש החי שבתחתית העמוד."),
        "dir_caption": f"מדריך מרכזי הטראומה: {n:,} מרפאות, שם, יישוב, כתובת ופרטי קשר.",
        "city_lede": (f"{_n_clinics(n)} ב-{len(city_counts):,} יישובים. "
                      + (f"{top_city} במקום הראשון עם {_n_clinics(int(city_counts.iloc[0]))}."
                         if len(city_counts) >= 2 and city_counts.iloc[0] > city_counts.iloc[1]
                         else "אין יישוב אחד שמוביל לבדו.")
                      + (f" מעבר ל-{keep:,} היישובים המובילים, השאר מקובצים ב״אחר״."
                         if rest else "")),
        "city_aria": (f"תרשים עמודות אופקי: מספר מרכזי הטראומה לפי יישוב, {len(city_counts):,} "
                      "יישובים" + (f", המוביל {top_city}" if top_city else "") + "."),
        "aud_lede": ("שיוך לפי מילים בשם המרפאה (ילדים, נוער, מבוגרים, טראומה צבאית). "
                     "מרפאה ששמה אינו מציין קהל יעד עשויה לטפל בכולם; "
                     f"{aud_counts['none']:,} מתוך {n:,} כאלה."),
        "aud_aria": (f"תרשים עמודות: קהל היעד לפי שם המרפאה. ילדים ונוער {aud_counts['kids']:,}, "
                     f"מבוגרים {aud_counts['adults']:,}, טראומה צבאית {aud_counts['military']:,}, "
                     f"לא צוין {aud_counts['none']:,}."),
        "contact_lede": (f"כמה מהמרפאות מפרסמות כל ערוץ קשר. {_pct(has_phone, n)} עם טלפון, "
                         f"{_pct(has_email, n)} עם דוא״ל ו-{_pct(has_web, n)} עם אתר."),
        "contact_aria": (f"תרשים עמודות: זמינות פרטי קשר מתוך {n:,} מרפאות. טלפון {has_phone:,}, "
                         f"דוא״ל {has_email:,}, אתר {has_web:,}, ללא כל פרט {none_any:,}."),
        "body_lede": ("הגוף שאליו שייכים הדוא״ל או האתר של המרפאה (הדוא״ל קודם). זה רמז לגוף "
                      "המפעיל, לא שדה רשמי במאגר; דומיין שאינו מוכר נספר ב״אחר״."),
        "body_aria": (f"תרשים עמודות אופקי: מרפאות לפי הגוף שאליו שייכים פרטי הקשר, "
                      f"{len(body_rows):,} קבוצות."),
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"cities": city_chart, "audience": aud_chart,
                   "contact": contact_chart, "bodies": body_chart},
        "insights": insights,
        "tables": {"cities": city_rows, "audience": aud_rows_t,
                   "contact": contact_rows, "bodies": body_rows,
                   "directory": directory},
        "flags": {"has_cities": len(city_counts) >= 2,
                  "has_bodies": len(body_rows) >= 2},
        "labels": labels,
    }
