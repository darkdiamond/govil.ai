"""מרכזי חוסן: the Ministry of Health list of resilience centers (one row per
center: code, name, host city + street, free-text address, email, two phones,
a comma-separated list of the settlements/authorities the center serves, and
a free-text note).

The page is a lookup page first. People search "מרכז חוסן <יישוב>": which
center serves my settlement and how do I call it. So the recipe builds a
settlement -> center index (an in-page search box over it) and a directory of
every center with its phones and served settlements. Around that it computes
what the list can honestly say: how many settlements each center covers, how
regional vs. municipal the network is, settlements listed under two centers,
and how complete the contact details are.

Growth: rows are overwritten in place. New centers and new settlements flow
through (no hardcoded names; the per-center chart caps at TOP_CENTERS + "אחר",
the directory at DIR_CAP). Settlement names are split on commas and
whitespace-normalised, so a trailing comma or padding in the source is harmless.
"""
import re

import pandas as pd

TOP_CENTERS = 20
DIR_CAP = 80
SUMMARY_MAX = 155
# Settlement-count buckets for the "size" chart: (upper bound inclusive, label).
SIZE_BUCKETS = [(1, "יישוב אחד"), (10, "2-10 יישובים"), (30, "11-30 יישובים"),
                (60, "31-60 יישובים"), (None, "יותר מ-60 יישובים")]
LANG_WORDS = ["אנגלית", "ערבית", "רוסית", "אמהרית", "צרפתית", "ספרדית"]

# Public webmail: a center address there is someone's personal mailbox; kept off the page.
WEBMAIL = ("gmail.com", "hotmail.com", "walla.co.il", "walla.com", "yahoo.com",
           "outlook.com", "live.com", "012.net.il", "bezeqint.net", "netvision.net.il",
           "icloud.com", "zahav.net.il")

HEB_COUNT = {1: "אחד", 2: "שני", 3: "שלושה", 4: "ארבעה", 5: "חמישה", 6: "שישה",
             7: "שבעה", 8: "שמונה", 9: "תשעה", 10: "עשרה"}


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _n_centers(n):
    """'מרכז אחד', 'שני מרכזים', '16 מרכזים'."""
    if n == 1:
        return "מרכז אחד"
    if n in HEB_COUNT:
        return f"{HEB_COUNT[n]} מרכזים"
    return f"{n:,} מרכזים"


def _n_hosen(n):
    """'מרכז חוסן אחד', 'שני מרכזי חוסן', '16 מרכזי חוסן'."""
    if n == 1:
        return "מרכז חוסן אחד"
    if n == 2:
        return "שני מרכזי חוסן"
    return f"{n:,} מרכזי חוסן"


def _lamed(name):
    """'ל' + name: 'המרכז ...' -> 'למרכז ...', otherwise 'למרכז החוסן <name>'."""
    return "ל" + name[1:] if name.startswith("ה") else "למרכז החוסן " + name


def _label(name):
    """'מרכז החוסן <name>', unless the name already starts with the article."""
    return name if name.startswith("ה") else "מרכז החוסן " + name


def _n_places(n):
    return "יישוב אחד" if n == 1 else f"{n:,} יישובים"


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
    if m:
        return "*" + m.group(1)
    return s


def _tel(display):
    return re.sub(r"[^\d*+]", "", display)


def _phone_kind(p):
    digits = re.sub(r"\D", "", p)
    if p.startswith("*") or (3 <= len(digits) <= 5 and not digits.startswith("0")):
        return "short"
    if re.match(r"05\d", digits):
        return "mobile"
    if re.match(r"0[2-47-9]", digits):
        return "landline"
    return "other"


PHONE_KINDS = [("landline", "קו נייח"), ("mobile", "טלפון נייד"),
               ("short", "מספר מקוצר (כוכבית)"), ("other", "אחר")]


def _valid_email(e):
    e = _clean(e)
    if not re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", e):
        return ""
    return "" if e.lower().rpartition("@")[2] in WEBMAIL else e


def _places(raw):
    """Split the served-settlements cell; dedupe within the row, keep order."""
    out = []
    for part in str(raw).split(","):
        p = _clean(part)
        if p and p not in out:
            out.append(p)
    return out


def _prepare(df):
    out = pd.DataFrame({
        "code": df["institute_code"].map(_clean),
        "name": df["institute_name"].map(_clean),
        "city": df["city"].map(_clean),
        "street_code": df["streetCode"].map(_clean),
        "address": df["address"].map(_clean),
        "raw_email": df["email"].map(_clean),
        "email": df["email"].map(_valid_email),
        "phone": df["phone"].map(_phone),
        "phone2": df["phone2"].map(_phone),
        "places_raw": df["other_cities"].map(_clean),
        "note": df["el_notes"].map(_clean),
    })
    out = out[out["name"] != ""]
    out = out.drop_duplicates()
    out = out.sort_values(["code", "name", "city", "address", "places_raw"], kind="stable")
    out = out.reset_index(drop=True)
    out["places"] = out["places_raw"].map(_places)
    out["n_places"] = out["places"].map(len)
    return out


# ---------------------------------------------------------------- insights

def insight_spread(df, n_unique):
    n = len(df)
    if n == 0 or n_unique == 0:
        return None
    single = df[df["n_places"] == 1]
    regional = df[df["n_places"] >= 2]
    s = f"{_n_hosen(n)} משרתים יחד {_n_places(n_unique)} ורשויות"
    if len(regional) and len(single):
        s += f": {len(regional):,} מרכזים אזוריים שכל אחד מהם משרת כמה יישובים"
        names = sorted(single["name"])
        if len(names) <= 4:
            s += f", ו-{len(names):,} מרכזים עירוניים שמשרתים יישוב יחיד ({_join(names)})"
        else:
            s += f", ו-{len(names):,} מרכזים עירוניים שמשרתים יישוב יחיד"
    return s + "."


def insight_leader(ranked, total_mentions):
    if len(ranked) < 2 or total_mentions == 0:
        return None
    top, second = ranked.iloc[0], ranked.iloc[1]
    if top["n_places"] <= second["n_places"]:
        return None
    share = top["n_places"] / total_mentions
    if share < 0.15:
        return None
    return (f"{_label(top['name'])} משרת את מספר היישובים הגדול ביותר: "
            f"{_n_places(int(top['n_places']))}, {_pct(top['n_places'], total_mentions)} מכלל "
            f"השיוכים ברשימה. אחריו {second['name']} עם {_n_places(int(second['n_places']))}.")


def insight_concentration(ranked, total_mentions):
    if len(ranked) < 6 or total_mentions == 0:
        return None
    top3 = ranked.head(3)
    share = top3["n_places"].sum() / total_mentions
    if share < 0.4:
        return None
    return (f"שלושת המרכזים הגדולים ({_join(top3['name'])}) מרכזים "
            f"{_pct(top3['n_places'].sum(), total_mentions)} מכל שיוכי היישובים, "
            f"מתוך {_n_centers(len(ranked))} שיש להם רשימת יישובים.")


def insight_overlap(multi):
    if not multi:
        return None
    if len(multi) <= 3:
        parts = [f"{p} ({_join(cs)})" for p, cs in multi]
        verb = "מופיע" if len(multi) == 1 else "מופיעים"
        return (f"{_join(parts)} {verb} ברשימות של יותר ממרכז חוסן אחד; "
                "מומלץ לבדוק מול שני המרכזים לאיזה מהם לפנות.")
    return (f"{len(multi):,} יישובים מופיעים ברשימות של יותר ממרכז חוסן אחד, "
            "ולכן תושביהם יכולים למצוא יותר ממרכז אחד בחיפוש.")


def insight_unlisted(df):
    none = df[df["n_places"] == 0]
    if none.empty or len(df) < 3:
        return None
    names = sorted(none["name"])
    if len(names) == 1:
        nm = names[0]
        note = none.iloc[0]["note"]
        s = f"{_lamed(nm)} אין רשימת יישובים משויכים"
        if "ארצי" in nm and ("לא משוייכ" in note or "לא משויכ" in note):
            s += ("; לפי הערת המאגר זו הכתובת לתושבי יישובים שאינם משויכים "
                  "למרכז חוסן ייעודי")
        elif "ארצי" in nm:
            s += "; זהו מרכז ארצי"
        return s + "."
    return f"ל-{len(names):,} מרכזים אין רשימת יישובים משויכים במאגר."


def insight_shared_phone(df):
    rows = []
    for _, r in df.iterrows():
        for p in {r["phone"], r["phone2"]}:
            t = _tel(p)
            if t:
                rows.append((t, p, r["name"]))
    if not rows:
        return None
    g = pd.DataFrame(rows, columns=["tel", "disp", "name"]).drop_duplicates(["tel", "name"])
    g = g.sort_values(["tel", "name"], kind="stable").groupby("tel")
    shared = [(grp["disp"].iloc[0], sorted(grp["name"])) for _, grp in g if len(grp) >= 2]
    if not shared:
        return None
    if len(shared) == 1:
        disp, names = shared[0]
        return f"מרכזי החוסן {_join(names)} חולקים את אותו מספר טלפון ({disp}), כלומר מוקד פניות משותף."
    return f"{len(shared):,} מספרי טלפון משותפים ליותר ממרכז חוסן אחד (מוקדי פניות משותפים)."


def insight_short(df):
    stars = df[df["phone"].map(_phone_kind).eq("short") | df["phone2"].map(_phone_kind).eq("short")]
    if stars.empty:
        return None
    names = sorted(stars["name"])
    if len(names) == 1:
        return f"{_label(names[0])} זמין במספר מקוצר (כוכבית)."
    if len(names) <= 3:
        return "מרכזי החוסן " + _join(names) + " זמינים במספר מקוצר (כוכבית)."
    return f"{len(names):,} מרכזי חוסן זמינים במספר מקוצר (כוכבית)."


def insight_langs(df):
    hits = []
    for _, r in df.iterrows():
        langs = [w for w in LANG_WORDS if w in r["note"]]
        if langs:
            hits.append((r["name"], langs))
    if not hits:
        return None
    langs = [w for w in LANG_WORDS if any(w in ls for _, ls in hits)]
    names = sorted(n for n, _ in hits)
    if len(names) == 1:
        who = f"במרכז {names[0]}"
    elif len(names) <= 3:
        who = f"במרכזים {_join(names)}"
    else:
        who = f"ב-{len(names):,} מרכזים"
    return f"לפי הערות המאגר, {who} פועל מוקד טלפוני גם ב{_join(langs)}."


def insight_address(df):
    n = len(df)
    vague = df[(df["street_code"] == "") & (df["address"] == "")]
    if vague.empty or n < 3:
        return None
    return (f"ל-{len(vague):,} מתוך {n:,} המרכזים ({_pct(len(vague), n)}) לא רשומה כתובת במאגר, "
            "רק היישוב המארח; הפנייה אליהם היא בטלפון.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["centers"])
    n = int(len(df))

    # settlement -> centers index
    index = {}
    for _, r in df.iterrows():
        for p in r["places"]:
            index.setdefault(p, [])
            if r["name"] not in index[p]:
                index[p].append(r["name"])
    places_sorted = sorted(index)
    n_unique = len(places_sorted)
    total_mentions = int(df["n_places"].sum())
    multi = [(p, sorted(index[p])) for p in places_sorted if len(index[p]) >= 2]

    ranked = (df[df["n_places"] > 0]
              .sort_values(["n_places", "name", "code"], ascending=[False, True, True], kind="stable")
              .reset_index(drop=True))
    regional = int((df["n_places"] >= 2).sum())
    single = int((df["n_places"] == 1).sum())

    has_phone = int(((df["phone"] != "") | (df["phone2"] != "")).sum())
    has_two = int(((df["phone"] != "") & (df["phone2"] != "")).sum())
    has_email = int((df["email"] != "").sum())
    has_addr = int((df["address"] != "").sum())
    has_note = int((df["note"] != "").sum())

    rules = [
        ("spread", insight_spread(df, n_unique)),
        ("leader", insight_leader(ranked, total_mentions)),
        ("concentration", insight_concentration(ranked, total_mentions)),
        ("overlap", insight_overlap(multi)),
        ("unlisted", insight_unlisted(df)),
        ("shared_phone", insight_shared_phone(df)),
        ("short", insight_short(df)),
        ("langs", insight_langs(df)),
        ("address", insight_address(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    max_places = int(ranked["n_places"].iloc[0]) if len(ranked) else 0
    kpis = {
        "total": {"value": n, "display": f"{n:,}", "tone": "brand"},
        "places": {"value": n_unique, "display": f"{n_unique:,}", "tone": "brand"},
        "max": {"value": max_places, "display": f"{max_places:,}",
                "tone": "info" if max_places else "brand"},
        "phone": {"value": has_phone, "display": _pct(has_phone, n),
                  "tone": ("ok" if n and has_phone / n >= 0.9 else
                           "warn" if n and has_phone / n >= 0.6 else "danger")},
    }

    # ---- settlements per center (horizontal bars, largest on top)
    keep = len(ranked) if len(ranked) <= TOP_CENTERS + 2 else TOP_CENTERS
    top = ranked.head(keep)
    rest = ranked.iloc[keep:]
    served_rows = [{"name": r["name"], "n": int(r["n_places"])} for _, r in top.iterrows()]
    if len(rest):
        served_rows.append({"name": f"אחר ({len(rest):,} מרכזים)", "n": int(rest["n_places"].sum())})
    served_chart = {"names": [r["name"] for r in served_rows][::-1],
                    "values": [r["n"] for r in served_rows][::-1]}

    # ---- size buckets
    size_rows = []
    lo = 1
    for hi, label in SIZE_BUCKETS:
        m = (df["n_places"] >= lo) & ((df["n_places"] <= hi) if hi is not None else True)
        size_rows.append({"name": label, "n": int(m.sum())})
        lo = (hi or 0) + 1
    no_list = int((df["n_places"] == 0).sum())
    if no_list:
        size_rows.append({"name": "ללא רשימת יישובים", "n": no_list})
    size_chart = {"names": [r["name"] for r in size_rows], "values": [r["n"] for r in size_rows]}

    # ---- contact completeness
    contact_rows = [
        {"name": "טלפון", "n": has_phone},
        {"name": "שני מספרי טלפון", "n": has_two},
        {"name": "דוא״ל ארגוני", "n": has_email},
        {"name": "כתובת", "n": has_addr},
        {"name": "הערה או מוקד נוסף", "n": has_note},
    ]
    for r in contact_rows:
        r["pct"] = _pct(r["n"], n)
    contact_chart = {"names": [r["name"] for r in contact_rows],
                     "values": [r["n"] for r in contact_rows], "total": n}

    # ---- phone kinds (distinct numbers per center)
    kind_counts = {k: 0 for k, _ in PHONE_KINDS}
    for _, r in df.iterrows():
        for p in sorted({r["phone"], r["phone2"]}):
            if _tel(p):
                kind_counts[_phone_kind(p)] += 1
    phone_rows = [{"name": label, "n": kind_counts[k]} for k, label in PHONE_KINDS
                  if kind_counts[k] or k != "other"]
    n_numbers = sum(kind_counts.values())
    for r in phone_rows:
        r["pct"] = _pct(r["n"], n_numbers)
    phone_chart = {"names": [r["name"] for r in phone_rows],
                   "values": [r["n"] for r in phone_rows], "total": n_numbers}

    # ---- directory (sorted by name)
    directory = []
    for _, r in df.sort_values(["name", "code"], kind="stable").head(DIR_CAP).iterrows():
        phones = []
        for p in (r["phone"], r["phone2"]):
            if p and _tel(p) and p not in [x["display"] for x in phones]:
                phones.append({"display": p, "tel": _tel(p)})
        directory.append({
            "name": r["name"],
            "city": r["city"],
            "address": r["address"],
            "phones": phones,
            "email": r["email"],
            "note": r["note"],
            "places": r["places"],
            "n_places": int(r["n_places"]),
        })

    # ---- lookup index for the search box: [settlement, [center names]]
    lookup = {
        "places": [[p, sorted(index[p])] for p in places_sorted],
        "centers": {c["name"]: [x["display"] for x in c["phones"]] for c in directory},
    }

    # ---- summary (meta description)
    summary = (f"איתור מרכז חוסן לפי יישוב, עם טלפון וכתובת: {_n_hosen(n)} "
               f"המשרתים {_n_places(n_unique)}, מרשימת משרד הבריאות.")
    if len(summary) > SUMMARY_MAX:
        summary = f"איתור מרכז חוסן לפי יישוב: {_n_hosen(n)} המשרתים {_n_places(n_unique)}."

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["מרכזי חוסן", "בריאות הנפש", "חוסן", "טראומה", "נפגעי חרדה",
                           "תמיכה רגשית"],
        "related_ids": ["b54ae5a7-1bd5-4e7f-8b9d-f367f8eefd65",
                        "5c8651bc-5288-4d46-a3f5-2ebfbe5c9615"],
        "spatial_coverage": "ישראל",
    }

    top_name = ranked["name"].iloc[0] if len(ranked) else ""
    labels = {
        "kpi_total": "מרכזי חוסן ברשימה",
        "kpi_places": "יישובים ורשויות משויכים למרכז חוסן",
        "kpi_max": (f"יישובים במרכז הגדול ביותר ({top_name})" if top_name
                    else "יישובים במרכז הגדול ביותר"),
        "kpi_phone": f"מהמרכזים עם מספר טלפון במאגר ({has_phone:,} מתוך {n:,})",
        "lookup_lede": (f"הקלידו שם יישוב כדי לראות איזה מרכז חוסן משרת אותו. החיפוש עובר על "
                        f"{_n_places(n_unique)} שמופיעים ברשימות המרכזים."),
        "lookup_aria": "חיפוש מרכז חוסן לפי שם יישוב",
        "dir_lede": (f"כל מרכזי החוסן במאגר ({n:,}), לפי שם. טלפונים, דוא״ל וכתובת מופיעים כפי "
                     "שפורסמו; היכן שאין פרט, הוא חסר במקור. כתובת דוא״ל פרטית (כמו Gmail) "
                     "אינה מוצגת." if n <= DIR_CAP else
                     f"{DIR_CAP:,} המרכזים הראשונים מתוך {n:,}, לפי שם. "
                     "הרשימה המלאה בחיפוש החי שבתחתית העמוד."),
        "dir_caption": f"מדריך מרכזי החוסן: {n:,} מרכזים, יישוב, כתובת, טלפונים ויישובים בשירות.",
        "served_lede": (f"{_n_hosen(len(ranked))} עם רשימת יישובים, {total_mentions:,} שיוכים בסך הכול. "
                        + (f"{top_name} מוביל עם {_n_places(max_places)}. " if top_name else "")
                        + (f"מעבר ל-{keep:,} המרכזים המובילים, השאר מקובצים ב״אחר״." if len(rest) else "")).strip(),
        "served_aria": (f"תרשים עמודות אופקי: מספר היישובים שכל מרכז חוסן משרת, "
                        f"{len(ranked):,} מרכזים" + (f", המוביל {top_name}" if top_name else "") + "."),
        "size_lede": (f"{regional:,} מרכזים אזוריים (יותר מיישוב אחד) ו-{single:,} מרכזים עירוניים "
                      "שמשרתים יישוב יחיד"
                      + (f"; ל-{no_list:,} אין רשימת יישובים." if no_list else ".")),
        "size_aria": ("תרשים עמודות: התפלגות מרכזי החוסן לפי מספר היישובים שהם משרתים: "
                      + ", ".join(f"{r['name']} {r['n']:,}" for r in size_rows) + "."),
        "contact_lede": (f"כמה מהמרכזים מפרסמים כל פרט. {_pct(has_phone, n)} עם טלפון, "
                         f"{_pct(has_two, n)} עם מספר שני, {_pct(has_email, n)} עם דוא״ל ארגוני "
                         f"ו-{_pct(has_addr, n)} עם כתובת."),
        "contact_aria": (f"תרשים עמודות: זמינות פרטי קשר מתוך {n:,} מרכזים. טלפון {has_phone:,}, "
                         f"מספר שני {has_two:,}, דוא״ל {has_email:,}, כתובת {has_addr:,}."),
        "phone_lede": (f"{n_numbers:,} מספרי טלפון ברשימה, לפי סוג הקו: "
                       + ", ".join(f"{r['name']} {r['n']:,}" for r in phone_rows) + "."),
        "phone_aria": ("תרשים עמודות: מספרי הטלפון של מרכזי החוסן לפי סוג קו: "
                       + ", ".join(f"{r['name']} {r['n']:,}" for r in phone_rows) + "."),
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"served": served_chart, "size": size_chart,
                   "contact": contact_chart, "phones": phone_chart},
        "insights": insights,
        "tables": {"served": served_rows, "size": size_rows, "contact": contact_rows,
                   "phones": phone_rows, "directory": directory},
        "lookup": lookup,
        "flags": {"has_served": len(ranked) >= 2, "has_lookup": n_unique > 0,
                  "has_phones": n_numbers > 0},
        "labels": labels,
    }
