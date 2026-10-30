"""רשימת תאגידים בנקאיים בישראל: Bank of Israel's directory of banking corporations.

One row per licensed banking corporation (Hebrew resource; an English twin
carries the same rows). Columns: category (commercial / foreign / financial
institution / joint service company), the bank code used in account numbers,
name, website, SWIFT/BIC, head-office address, city, zip, phone and fax.

A small registry (17 rows when authored): the page is a lookup directory first,
with honest charts of the category mix, head-office cities and how complete
each entity's contact details are. Everything is computed from the rows, so
a new bank, a new category or a moved head office flows through.
"""
import re

import pandas as pd

MISSING = "לא צוין"
TOP_CITIES = 10
# (field label, column) pairs for the completeness view; order = display order.
FIELDS = [
    ("אתר אינטרנט", "Internet_Address"),
    ("קוד SWIFT", "Swift_Code"),
    ("כתובת", "Address"),
    ("מיקוד", "Zip_Code"),
    ("טלפון", "Telephone"),
    ("פקס", "Fax"),
]
COUNT_WORDS = {2: "שני", 3: "שלושה", 4: "ארבעה", 5: "חמישה"}
_HOST_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")


def _int(n):
    return f"{int(n):,}"


def _pct(x, digits=0):
    return f"{x * 100:.{digits}f}%"


def _ranked(series):
    """value_counts with a total order: count desc, then label asc."""
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " ו" + ("-" if re.match(r"[A-Za-z0-9]", names[-1]) else "") + names[-1]


def short_name(name):
    """'בנק הפועלים בע"מ' -> 'בנק הפועלים' (labels only)."""
    return re.sub(r'\s*בע["״]?מ\.?\s*$', "", name.strip()) or name.strip()


def _city(v):
    v = re.sub(r"\s+", " ", v.strip())
    v = re.sub(r"\s*-\s*", "-", v)
    return v or MISSING


def _website(v):
    """Return (display host, https link or None). None link = not a usable URL."""
    v = v.strip()
    if not v:
        return "", None
    host = re.sub(r"^https?://", "", v, flags=re.IGNORECASE).split("/")[0].lower()
    if host.startswith("www."):
        disp = host[4:]
    else:
        disp = host
    if not _HOST_RE.match(host):
        return disp or v, None
    return disp, "https://" + host + "/"


def _prepare(df):
    out = pd.DataFrame()
    for c in ["Category", "Bank_Code", "Bank_Name", "Internet_Address", "Swift_Code",
              "Address", "City", "Zip_Code", "Telephone", "Fax"]:
        out[c] = df[c].astype(str).str.strip()
    out["category"] = out["Category"].replace("", MISSING)
    out["code"] = pd.to_numeric(out["Bank_Code"], errors="coerce")
    out["name"] = out["Bank_Name"].map(short_name)
    out["city"] = out["City"].map(_city)
    out["swift"] = out["Swift_Code"].str.upper().str.replace(" ", "", regex=False)
    web = out["Internet_Address"].map(_website)
    out["web_disp"] = web.map(lambda t: t[0])
    # object dtype keeps None as None: pandas 3 would store a missing link
    # in a str column as NaN, which the JSON model rejects.
    out["web_link"] = web.map(lambda t: t[1]).astype(object)
    out["web_link"] = out["web_link"].where(out["web_link"].notna(), None)
    out["address"] = out["Address"].str.replace(r"\s*;\s*", ", ", regex=True)
    out = out.sort_values(["code", "Bank_Code", "Bank_Name"], na_position="last", kind="stable")
    return out.reset_index(drop=True)


# ---------------------------------------------------------------- insights

def insight_mix(df, cats):
    top, n = cats.index[0], int(cats.iloc[0])
    if len(cats) == 1:
        return f"כל {_int(n)} התאגידים ברשימה מסווגים כ{top}."
    if n * 2 <= len(df):
        return None
    others = [f"{c} ({_int(v)})" for c, v in cats.iloc[1:].items()]
    tail = f"; השאר: {_join(others)}" if others else ""
    return (f"{_int(n)} מתוך {_int(len(df))} התאגידים ברשימה ({_pct(n / len(df))}) "
            f"מסווגים כ{top}{tail}.")


def insight_cities(df, cities):
    known = cities.drop(MISSING, errors="ignore")
    if known.empty:
        return None
    top_n = int(known.iloc[0])
    leaders = list(known[known == top_n].index)
    if top_n < 2 or len(leaders) > 2:
        return None
    lead_txt = (f"ב{leaders[0]} רשום המטה של {_int(top_n)} תאגידים ({_pct(top_n / len(df))})"
                if len(leaders) == 1 else
                f"ב{leaders[0]} וב{leaders[1]} רשומים המטות של {_int(top_n)} תאגידים בכל אחת")
    rest = known[known < top_n]
    second = ""
    if len(leaders) == 1 and len(rest):
        r_n = int(rest.iloc[0])
        r_lead = list(rest[rest == r_n].index)
        if r_n >= 2:
            if len(r_lead) == 1:
                second = f"; אחריה {r_lead[0]} ({_int(r_n)})"
            else:
                second = f"; אחריה {_join(r_lead)} ({_int(r_n)} בכל אחת)"
    return f"{lead_txt}{second}. בסך הכול המטות פרוסים ב-{_int(len(known))} יישובים."


def insight_swift(df):
    has = df[df["swift"] != ""]
    if has.empty:
        return None
    base = (f"ל-{_int(len(has))} מתוך {_int(len(df))} התאגידים רשום קוד SWIFT (BIC) "
            f"להעברות בינלאומיות")
    country = has["swift"].str[4:6]
    foreign = has[country != "IL"].sort_values(["code", "name"], kind="stable")
    if foreign.empty:
        return base + ", וכולם קודים ישראליים (IL)."
    parts = [f"{r['name']} ({r['swift'][4:6]})" for _, r in foreign.iterrows()]
    if len(foreign) == len(has):
        return base + f", כולם בקודי מדינה שאינם ישראל: {_join(parts)}."
    verb = "שרשום בקוד של מדינה אחרת" if len(parts) == 1 else "שרשומים בקודים של מדינות אחרות"
    return base + f". כולם קודים ישראליים (IL) מלבד {_join(parts)}, {verb}."


def insight_missing(df):
    """Entities with no website, phone and address at all."""
    bare = df[(df["Internet_Address"] == "") & (df["Telephone"] == "") & (df["Address"] == "")]
    if bare.empty:
        return None
    names = [f"{r['name']} ({r['category']})" for _, r in bare.iterrows()]
    if len(names) == 1:
        return (f"לתאגיד אחד ברשימה, {names[0]}, אין במאגר אתר, טלפון או כתובת, "
                f"רק שם, קוד ויישוב.")
    if len(names) > 4:
        return (f"ל-{_int(len(names))} תאגידים ברשימה אין במאגר אתר, טלפון או כתובת, "
                f"רק שם, קוד ויישוב.")
    return (f"ל{COUNT_WORDS.get(len(names), _int(len(names)))} תאגידים ברשימה אין במאגר אתר, "
            f"טלפון או כתובת, רק שם, קוד ויישוב: {_join(names)}.")


def insight_shared(df):
    """Entities that share a head-office zip code (e.g. a bank and its subsidiary)."""
    z = df[df["Zip_Code"] != ""]
    groups = []
    for zip_code, g in z.groupby("Zip_Code", sort=True):
        if len(g) >= 2:
            groups.append((-len(g), zip_code, list(g["name"])))
    if not groups:
        return None
    groups.sort()
    _, zip_code, names = groups[0]
    word = COUNT_WORDS.get(len(names), _int(len(names)))
    extra = ("" if len(groups) == 1 else " (ועוד מיקוד משותף אחד)" if len(groups) == 2
             else f" (ועוד {_int(len(groups) - 1)} מיקודים משותפים)")
    city = df.loc[df["Zip_Code"] == zip_code, "city"].iloc[0]
    return (f"{word} תאגידים רשומים באותו מיקוד מטה ב{city}: {_join(names)}{extra}.")


def insight_web(df):
    has = df[df["Internet_Address"] != ""]
    if has.empty:
        return None
    broken = has[has["web_link"].isna()]
    if broken.empty:
        return None
    verb = "רשומה באופן חלקי, ולכן מוצגת" if len(broken) == 1 else "רשומות באופן חלקי, ולכן מוצגות"
    noun = "כתובת האתר" if len(broken) == 1 else "כתובות האתר"
    return (f"ל-{_int(len(has))} מתוך {_int(len(df))} התאגידים רשום אתר אינטרנט. "
            f"{noun} של {_join(broken['name'])} {verb} בטבלה ללא קישור.")


def insight_codes(df):
    codes = df["code"].dropna()
    if len(codes) < 3:
        return None
    lo = df.loc[df["code"] == codes.min()].iloc[0]
    hi = df.loc[df["code"] == codes.max()].iloc[0]
    return (f"קודי הבנק ברשימה נעים בין {int(codes.min())} ({lo['name']}) ל-{int(codes.max())} "
            f"({hi['name']}). זהו המספר שמופיע בראש מספר החשבון ובשיקים.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["banks"])
    n = len(df)

    cats = _ranked(df["category"])
    cat_order = list(cats.index)
    cities = _ranked(df["city"])
    known_cities = cities.drop(MISSING, errors="ignore")
    top_cities = list(cities.index[:TOP_CITIES])
    other_cities = cities.iloc[TOP_CITIES:]

    # Head-office city, stacked by category.
    by_city_cat = df.groupby(["city", "category"]).size()
    city_names = top_cities + (["יישובים אחרים"] if len(other_cities) else [])
    city_chart = {
        "names": city_names,
        "series": [
            {"name": c,
             "data": [int(by_city_cat.get((ct, c), 0)) for ct in top_cities]
             + ([int(((~df["city"].isin(top_cities)) & (df["category"] == c)).sum())]
                if len(other_cities) else [])}
            for c in cat_order
        ],
    }
    t_cities = [{"name": ct,
                 "count": _int(cities[ct]),
                 "names": ", ".join(df.loc[df["city"] == ct, "name"])}
                for ct in cities.index]

    cat_chart = {"names": cat_order, "values": [int(v) for v in cats.values]}
    t_cats = [{"name": c, "count": _int(v), "share": _pct(v / n)} for c, v in cats.items()]

    # Contact-detail completeness: how many entities list each field.
    filled = [int((df[col] != "").sum()) for _, col in FIELDS]
    order = sorted(range(len(FIELDS)), key=lambda i: (-filled[i], i))
    fields_chart = {"names": [FIELDS[i][0] for i in order],
                    "filled": [filled[i] for i in order],
                    "missing": [n - filled[i] for i in order]}
    t_fields = [{"name": FIELDS[i][0], "filled": _int(filled[i]), "missing": _int(n - filled[i])}
                for i in order]
    complete = df[[c for _, c in FIELDS]].ne("").all(axis=1)
    n_complete = int(complete.sum())

    # Directory, grouped by category (largest first), bank code ascending.
    directory = []
    for c in cat_order:
        rows = df[df["category"] == c]
        directory.append({
            "category": c,
            "count": _int(len(rows)),
            "rows": [{
                "code": r["Bank_Code"] or MISSING,
                "name": r["Bank_Name"],
                "web_disp": r["web_disp"],
                "web_link": r["web_link"],
                "swift": r["swift"],
                "address": r["address"],
                "city": r["city"],
                "zip": r["Zip_Code"],
                "phone": r["Telephone"],
                "fax": r["Fax"],
            } for _, r in rows.iterrows()],
        })

    n_swift = int((df["swift"] != "").sum())
    n_web = int((df["Internet_Address"] != "").sum())
    cat1 = cat_order[0]
    cat2 = cat_order[1] if len(cat_order) > 1 else None
    complete_share = n_complete / n if n else 0.0

    kpis = {
        "total": {"value": n, "display": _int(n), "tone": "brand",
                  "label": "תאגידים בנקאיים ברשימה"},
        "top_cat": {"value": int(cats.iloc[0]), "display": _int(cats.iloc[0]), "tone": "brand",
                    "label": cat1},
        "swift": {"value": n_swift, "display": _int(n_swift), "tone": "info",
                  "label": "עם קוד SWIFT רשום"},
        "complete": {"value": n_complete, "display": _int(n_complete),
                     "tone": "ok" if complete_share >= 0.9 else "warn" if complete_share >= 0.6 else "danger",
                     "label": f"עם כל פרטי הקשר ({_pct(complete_share)} מהרשימה)"},
    }
    kpi_order = ["total", "top_cat", "swift", "complete"]

    rules = [
        ("mix", insight_mix(df, cats)),
        ("cities", insight_cities(df, cities)),
        ("swift", insight_swift(df)),
        ("shared", insight_shared(df)),
        ("missing", insight_missing(df)),
        ("web", insight_web(df)),
        ("codes", insight_codes(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    cat_list = _join([f"{c} ({_int(v)})" for c, v in cats.items()])
    labels = {
        "lede": (f"הרשימה הרשמית של בנק ישראל: {_int(n)} תאגידים בנקאיים הפועלים בישראל, "
                 f"{cat_list}. לכל תאגיד: קוד בנק (המספר שבראש מספר החשבון), אתר אינטרנט, "
                 f"קוד SWIFT, כתובת המטה, טלפון ופקס."),
        "kpi_order": kpi_order,
        "cat_aria": f"תרשים עמודות אופקי: {_int(n)} התאגידים הבנקאיים לפי סוג, {len(cat_order)} סוגים.",
        "cat_note": f"{_int(n)} התאגידים לפי הסיווג של בנק ישראל.",
        "cat_caption": "מספר התאגידים הבנקאיים לפי סוג.",
        "city_aria": (f"תרשים עמודות אופקי מוערם: מטות התאגידים לפי יישוב וסוג, "
                      f"{len(city_names)} יישובים."),
        "city_note": (f"היישוב שבו רשום מטה כל תאגיד. {_int(len(known_cities))} יישובים בסך הכול"
                      + (f"; מוצגים {TOP_CITIES} המובילים." if len(other_cities) else ".")),
        "city_caption": "מספר התאגידים ושמותיהם לפי יישוב המטה.",
        "fields_aria": (f"תרשים עמודות אופקי מוערם: לכמה מתוך {_int(n)} התאגידים רשום כל "
                        f"פרט קשר במאגר."),
        "fields_note": (f"לכמה מתוך {_int(n)} התאגידים רשום כל פרט במאגר. "
                        f"ל-{_int(n_complete)} תאגידים רשומים כל {len(FIELDS)} הפרטים."),
        "fields_caption": "מספר התאגידים שלהם רשום כל פרט קשר, ומספר החסרים.",
        "dir_note": (f"כל {_int(n)} התאגידים, מקובצים לפי סוג וממוינים לפי קוד בנק. "
                     f"ל-{_int(n_web)} מהם רשום אתר אינטרנט."),
        "dir_caption": "רשימת התאגידים הבנקאיים: קוד, שם, אתר, קוד SWIFT, כתובת וטלפון.",
    }

    summary = (f"איתור קוד בנק, קוד SWIFT, אתר, כתובת וטלפון של {_int(n)} התאגידים הבנקאיים "
               f"בישראל: {_int(cats.iloc[0])} {cat1}" + (f", {_int(cats.iloc[1])} {cat2}" if cat2 else "")
               + (" ועוד." if len(cat_order) > 2 else "."))
    if len(summary) > 155:
        summary = (f"איתור קוד בנק, קוד SWIFT, אתר, כתובת וטלפון של {_int(n)} התאגידים "
                   f"הבנקאיים בישראל.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["בנקים", "תאגידים בנקאיים", "קוד SWIFT", "קוד בנק", "פיקוח על הבנקים"],
            "related_ids": [
                "32348d0b-dc49-4bd0-a931-860e55709689",
                "9f357b63-99f6-4b52-8c9e-fa53c86e63e4",
                "67759a6a-4167-439b-af53-0eb792321264",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"categories": cat_chart, "cities": city_chart, "fields": fields_chart},
        "tables": {"categories": t_cats, "cities": t_cities, "fields": t_fields,
                   "directory": directory},
        "insights": insights,
        "labels": labels,
    }
