"""מרפאות לטיפול בהתמכרות לתרופות מרשם: a Ministry of Health directory of
clinics treating prescription-drug addiction (one row per clinic: code,
name, city, street, free-text address, email, two phones, website, the
manager's first name).

The registry currently lists a single clinic, so the page is a lookup card
first: the clinic, its address and whatever contact details were published,
plus what the registry can honestly say about itself (how many clinics, in
how many places, how complete the contact details are). Every sentence is
computed from the rows, so it re-words itself when clinics are added.

Growth: the resource is re-uploaded in place. Optional sections switch on
from the data: the by-city chart from two cities, the contact-completeness
chart from three clinics. New cities flow through (top-N + "אחר"). The
directory caps at DIR_CAP cards; past that the shell's explorer is the list.
"""
import re

import pandas as pd

TOP_CITIES = 12
DIR_CAP = 120
MIN_CONTACT_CHART = 3
SUMMARY_MAX = 155

HEB_COUNT = {1: "אחת", 2: "שתי", 3: "שלוש", 4: "ארבע", 5: "חמש", 6: "שש",
             7: "שבע", 8: "שמונה", 9: "תשע", 10: "עשר"}
CITY_NONE = "לא צוין"

# Public webmail: a clinic address there is someone's personal mailbox; kept off the page.
WEBMAIL = ("gmail.com", "hotmail.com", "walla.co.il", "walla.com", "yahoo.com",
           "outlook.com", "live.com", "012.net.il", "bezeqint.net", "netvision.net.il",
           "icloud.com", "zahav.net.il")


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _n_clinics(n):
    """'מרפאה אחת', 'שתי מרפאות', '12 מרפאות'."""
    if n == 1:
        return "מרפאה אחת"
    if n in HEB_COUNT:
        return f"{HEB_COUNT[n]} מרפאות"
    return f"{n:,} מרפאות"


def _n_places(n):
    return "יישוב אחד" if n == 1 else f"{n:,} יישובים"


def _in_places(n):
    """'ביישוב אחד', 'ב-4 יישובים' (a hyphen before a digit)."""
    return "ביישוב אחד" if n == 1 else f"ב-{n:,} יישובים"


def _join(items):
    """'א', 'א וב', 'א, ב וג' ("ו-" before a non-Hebrew start)."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = "ו" if re.match(r"[א-ת]", last) else "ו-"
    return ", ".join(items[:-1]) + " " + conj + last


def _pct(part, whole):
    return f"{(part / whole * 100):.0f}%" if whole else "0%"


def _phone(raw):
    """Display form: '5123*' (RTL-typed star code) -> '*5123'."""
    s = _clean(raw)
    m = re.fullmatch(r"(\d{3,5})\s*\*", s)
    return "*" + m.group(1) if m else s


def _tel(display):
    return re.sub(r"[^\d*+]", "", display)


def _valid_url(u):
    u = _clean(u)
    return u if re.match(r"^https://[^\s\"'<>]+$", u, re.I) else ""


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
        "address": df["address"].map(_clean),
        "email": df["email"].map(_valid_email),
        "phone": df["phone"].map(_phone),
        "phone2": df["phone2"].map(_phone),
        "website": df["website"].map(_valid_url),
    })
    out = out[out["name"] != ""].drop_duplicates()
    out["city"] = out["city"].where(out["city"] != "", CITY_NONE)
    out = out.sort_values(["city", "name", "code", "address"], kind="stable")
    out["has_phone"] = (out["phone"] != "") | (out["phone2"] != "")
    out["has_any"] = out["has_phone"] | (out["email"] != "") | (out["website"] != "")
    out["street_addr"] = (out["address"] != "") & (out["address"] != out["city"])
    return out.reset_index(drop=True)


def _where(r):
    """'מרפאת נס בנתניה (רח' יד חרוצים 19)'."""
    s = f"{r['name']} ב{r['city']}" if r["city"] != CITY_NONE else r["name"]
    if r["street_addr"]:
        addr = r["address"]
        # "רח' יד חרוצים 19, נתניה" -> drop the trailing city already named
        addr = re.sub(r",\s*" + re.escape(r["city"]) + r"$", "", addr)
        s += f" ({addr})"
    return s


# ---------------------------------------------------------------- insights

def insight_spread(df, city_counts):
    n = len(df)
    if n == 0:
        return None
    if n == 1:
        return f"המאגר מונה כרגע מרפאה אחת בלבד: {_where(df.iloc[0])}."
    s = f"במאגר {_n_clinics(n)} לטיפול בהתמכרות לתרופות מרשם {_in_places(len(city_counts))}"
    if len(city_counts) >= 2 and city_counts.iloc[0] > city_counts.iloc[1]:
        s += f"; {city_counts.index[0]} מובילה עם {_n_clinics(int(city_counts.iloc[0]))}"
    elif len(city_counts) >= 2 and int(city_counts.max()) == 1:
        s += ", מרפאה אחת בכל יישוב"
    return s + "."


def insight_contact(df):
    n = len(df)
    if n == 0:
        return None
    phone, email, web = int(df["has_phone"].sum()), int((df["email"] != "").sum()), \
        int((df["website"] != "").sum())
    none = df[~df["has_any"]]
    if n == 1:
        r = df.iloc[0]
        if none.empty:
            got = [w for w, ok in (("טלפון", r["has_phone"]), ("דוא״ל", r["email"] != ""),
                                   ("אתר", r["website"] != "")) if ok]
            return f"למרפאה פורסמו {_join(got)}."
        return ("למרפאה לא פורסמו במאגר טלפון, דוא״ל או אתר; את פרטי הקשר יש לברר "
                "דרך משרד הבריאות או קופת החולים.")
    if none.empty and phone == n:
        return f"לכל {n:,} המרפאות במאגר מופיע מספר טלפון."
    got = [f"ל-{v:,} {what}" for v, what in ((phone, "טלפון"), (email, "דוא״ל"), (web, "אתר")) if v]
    s = (f"מתוך {n:,} המרפאות, פורסם {_join(got)}" if got
         else f"לאף אחת מ-{n:,} המרפאות לא פורסמו במאגר טלפון, דוא״ל או אתר")
    if not none.empty and got:
        names = sorted(none["name"])
        s += (f"; {_join(names)} " + ("מופיעה" if len(names) == 1 else "מופיעות")
              + " ללא כל פרט קשר") if len(names) <= 3 else f"; {len(names):,} ללא כל פרט קשר"
    return s + "."


def insight_address(df):
    vague = df[~df["street_addr"]]
    if df.empty:
        return None
    if vague.empty:
        if len(df) == 1:
            return "כתובת הרחוב של המרפאה רשומה במאגר, כך שאפשר להגיע אליה ישירות."
        return f"לכל {len(df):,} המרפאות רשומה כתובת רחוב."
    names = sorted(vague["name"])
    if len(names) == 1:
        return f"לגבי {names[0]} רשום במאגר רק שם היישוב, ללא כתובת רחוב."
    return f"לגבי {len(names):,} מרפאות רשום רק שם היישוב, ללא כתובת רחוב."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["clinics"])
    n = int(len(df))

    city_counts = (df.groupby("city").size().reset_index(name="n")
                   .sort_values(["n", "city"], ascending=[False, True], kind="stable")
                   .set_index("city")["n"])
    n_city = int(len(city_counts))
    has_phone = int(df["has_phone"].sum())
    has_email = int((df["email"] != "").sum())
    has_web = int((df["website"] != "").sum())
    has_any = int(df["has_any"].sum())
    none_any = n - has_any

    rules = [
        ("spread", insight_spread(df, city_counts)),
        ("contact", insight_contact(df)),
        ("address", insight_address(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    any_share = has_any / n if n else 0
    kpis = {
        "total": {"value": n, "display": f"{n:,}", "tone": "brand"},
        "cities": {"value": n_city, "display": f"{n_city:,}", "tone": "brand"},
        "contact": {"value": has_any, "display": _pct(has_any, n),
                    "tone": "ok" if any_share >= 0.8 else "warn" if any_share >= 0.5 else "danger"},
    }

    # ---- city chart (only from two cities): top-N + אחר, ascending for hbars
    keep = n_city if n_city <= TOP_CITIES + 2 else TOP_CITIES
    top = city_counts.head(keep)
    rest = int(city_counts.iloc[keep:].sum())
    city_rows = [{"name": c, "n": int(v)} for c, v in top.items()]
    if rest:
        city_rows.append({"name": f"אחר ({n_city - keep:,} יישובים)", "n": rest})
    city_chart = {"names": [r["name"] for r in city_rows][::-1],
                  "values": [r["n"] for r in city_rows][::-1]}

    contact_rows = [
        {"name": "טלפון", "n": has_phone},
        {"name": "דוא״ל", "n": has_email},
        {"name": "אתר אינטרנט", "n": has_web},
        {"name": "ללא כל פרט קשר", "n": none_any},
    ]
    for r in contact_rows:
        r["pct"] = _pct(r["n"], n)
    contact_chart = {"names": [r["name"] for r in contact_rows],
                     "values": [r["n"] for r in contact_rows], "total": n}

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
        })

    named = [c for c in city_counts.index if c != CITY_NONE]
    places = ("ב" + _join(named)) if 0 < len(named) == n_city <= 3 else _in_places(n_city)
    summary = (f"איתור מרפאה לטיפול בהתמכרות לתרופות מרשם, עם כתובת ופרטי קשר: "
               f"{_n_clinics(n)} {places}, לפי רשימת משרד הבריאות.")
    if len(summary) > SUMMARY_MAX:
        summary = (f"איתור מרפאה לטיפול בהתמכרות לתרופות מרשם: {_n_clinics(n)} "
                   f"{_in_places(n_city)}, לפי משרד הבריאות.")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["התמכרות", "תרופות מרשם", "מרפאות", "גמילה", "בריאות הנפש"],
        "related_ids": ["b54ae5a7-1bd5-4e7f-8b9d-f367f8eefd65",
                        "b08ed183-2c26-490f-aa13-f1a7529c3aca"],
        "spatial_coverage": "ישראל",
    }

    labels = {
        "kpi_total": "מרפאות במאגר" if n != 1 else "מרפאה במאגר",
        "kpi_cities": "יישובים שבהם פועלת מרפאה",
        "kpi_contact": f"מהמרפאות עם פרט קשר כלשהו ({has_any:,} מתוך {n:,})",
        "dir_title": "המרפאה ופרטי הקשר" if n == 1 else "רשימת המרפאות ופרטי הקשר",
        "dir_lede": (("פרטי המרפאה כפי שפרסם משרד הבריאות; היכן שאין פרט, הוא חסר במקור."
                      if n == 1 else
                      f"כל המרפאות במאגר ({n:,}), ממוינות לפי יישוב. פרטים חסרים חסרים במקור.")
                     if n <= DIR_CAP else
                     f"{DIR_CAP:,} המרפאות הראשונות מתוך {n:,}, ממוינות לפי יישוב. "
                     "הרשימה המלאה בחיפוש החי שבתחתית העמוד."),
        "dir_caption": f"מרפאות לטיפול בהתמכרות לתרופות מרשם: {n:,}, שם, יישוב, כתובת ופרטי קשר.",
        "city_lede": (f"{_n_clinics(n)} {_in_places(n_city)}."
                      + (f" {city_counts.index[0]} במקום הראשון עם "
                         f"{_n_clinics(int(city_counts.iloc[0]))}."
                         if n_city >= 2 and city_counts.iloc[0] > city_counts.iloc[1] else "")),
        "city_aria": f"תרשים עמודות אופקי: מספר המרפאות לפי יישוב, {n_city:,} יישובים.",
        "contact_lede": (f"כמה מהמרפאות מפרסמות כל ערוץ קשר: {_pct(has_phone, n)} עם טלפון, "
                         f"{_pct(has_email, n)} עם דוא״ל ו-{_pct(has_web, n)} עם אתר."),
        "contact_aria": (f"תרשים עמודות: זמינות פרטי קשר מתוך {n:,} מרפאות. טלפון {has_phone:,}, "
                         f"דוא״ל {has_email:,}, אתר {has_web:,}, ללא כל פרט {none_any:,}."),
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"cities": city_chart, "contact": contact_chart},
        "insights": insights,
        "tables": {"cities": city_rows, "contact": contact_rows, "directory": directory},
        "flags": {"has_cities": n_city >= 2, "has_contact": n >= MIN_CONTACT_CHART},
        "labels": labels,
    }
