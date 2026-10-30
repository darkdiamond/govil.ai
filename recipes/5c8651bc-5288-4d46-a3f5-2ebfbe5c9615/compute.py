"""מרכזי ייעוץ למשפחות של נפגעי נפש: a small Ministry of Health directory
(one row per center: code, name, city, street, free-text address, email, two
phones, center type (community / hospital) and the population the center is
adapted to (general public / Haredi / Arab)).

The page is a lookup page first: searchers want "מרכז ייעוץ למשפחות ב<עיר>"
and a phone number, so the full directory sits near the top. Around it the
recipe computes what the registry can honestly say: the community/hospital
split, which centers are adapted to the Haredi or Arab public and where, the
operating networks (centers whose names share a first word, e.g. a network's
branches), the cities, and how complete the contact details are.

Growth: rows are overwritten in place. New cities, types, adaptations and
networks all flow through (no hardcoded category lists; top-N + "אחר" on the
city axis). The directory caps at DIR_CAP rows; past that the shell's
explorer is the full list (the page says so).
"""
import re

import pandas as pd

TOP_CITIES = 15
DIR_CAP = 120
SUMMARY_MAX = 155
CITY_NONE = "לא צוין"

# Generic first words that name a kind of place, not an operator: a name
# starting with one of these is its own group, never a network.
GENERIC_FIRST = {"מרכז", "המרכז", "בית", "מרפאה", "המרפאה", "מרפאת", "עמותת", "עמותה"}

# Public webmail: a center address there is someone's personal mailbox; kept off the
# page (counted and disclosed). Same list as the sibling recipe b08ed183.
WEBMAIL = ("gmail.com", "hotmail.com", "walla.co.il", "walla.com", "yahoo.com",
           "outlook.com", "live.com", "012.net.il", "bezeqint.net", "netvision.net.il",
           "icloud.com", "zahav.net.il")

HEB_COUNT = {1: "אחד", 2: "שני", 3: "שלושה", 4: "ארבעה", 5: "חמישה", 6: "שישה",
             7: "שבעה", 8: "שמונה", 9: "תשעה", 10: "עשרה"}


def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _n_centers(n):
    """'מרכז אחד', 'שני מרכזים', '12 מרכזים'."""
    if n == 1:
        return "מרכז אחד"
    if n in HEB_COUNT:
        return f"{HEB_COUNT[n]} מרכזים"
    return f"{n:,} מרכזים"


def _n_cities(n):
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


def _tel(display):
    return re.sub(r"[^\d*+]", "", display)


def _display_name(s):
    """Hebrew gershayim/geresh instead of ASCII quotes in labels."""
    return s.replace('"', "״").replace("'", "׳")


def _net_key(name):
    """Network key: the first word of the name without quotes."""
    first = name.split(" ")[0] if name else ""
    key = re.sub(r"[\"'״׳]", "", first)
    if not key or key in GENERIC_FIRST:
        return "=" + name  # its own group
    return key


def _adj_phrase(label):
    """'מותאם לציבור החרדי' -> 'מותאמים לציבור החרדי'; unknown labels are quoted."""
    if label.startswith("מותאם "):
        return "מותאמים " + label[len("מותאם "):]
    return f"בקבוצת ״{label}״"


def _prepare(df):
    out = pd.DataFrame({
        "code": df["institute_code"].map(_clean),
        "name": df["institute_name"].map(_clean),
        "city": df["city"].map(_clean),
        "address": df["full_address"].map(_clean),
        "email": df["email"].map(_clean),
        "phone": df["phone"].map(_clean),
        "phone2": df["phone2"].map(_clean),
        "ctype": df["families_center_type_name"].map(_clean),
        "adj": df["adjustment_name"].map(_clean),
    })
    out = out[out["name"] != ""]
    out = out.drop_duplicates()
    out["city"] = out["city"].where(out["city"] != "", CITY_NONE)
    out["ctype"] = out["ctype"].where(out["ctype"] != "", "סוג לא צוין")
    out["adj"] = out["adj"].where(out["adj"] != "", "התאמה לא צוינה")
    out["email"] = out["email"].where(
        out["email"].str.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "")
    webmail = out["email"].str.lower().str.rpartition("@")[2].isin(WEBMAIL)
    out["email_hidden"] = webmail & (out["email"] != "")
    out["email"] = out["email"].where(~webmail, "")
    out = out.sort_values(["city", "name", "code", "address", "phone"], kind="stable")
    return out.reset_index(drop=True)


def _counts(series):
    return (series.value_counts().rename_axis("k").reset_index(name="n")
            .sort_values(["n", "k"], ascending=[False, True], kind="stable")
            .set_index("k")["n"])


def _general_label(adj_counts):
    """The 'general public' adaptation label, if present (by wording, not position)."""
    for k in adj_counts.index:
        if "כל" in k:
            return k
    return None


# ---------------------------------------------------------------- insights

def insight_spread(df, city_counts):
    n = len(df)
    named = city_counts.drop(CITY_NONE, errors="ignore")
    if n == 0 or named.empty:
        return None
    s = f"במאגר {_n_centers(n)} לייעוץ למשפחות של נפגעי נפש ב-{_n_cities(len(named))}"
    if len(named) >= 2 and named.iloc[0] > named.iloc[1] and named.iloc[0] >= 2:
        s += f"; {named.index[0]} מובילה עם {_n_centers(int(named.iloc[0]))}"
    multi = int((named >= 2).sum())
    if multi and len(named) >= 3:
        s += f". ב-{(len(named) - multi):,} יישובים פועל מרכז יחיד"
    return s + "."


def insight_types(type_counts, n):
    if len(type_counts) < 2 or n < 4:
        return None
    parts = [f"{_n_centers(int(v))} {_type_phrase(k)} ({_pct(int(v), n)})"
             for k, v in type_counts.items()]
    return "חלוקה לפי סוג: " + _join(parts) + "."


def _type_phrase(label):
    """'מרכזי יעוץ למשפחות בקהילה' -> 'בקהילה'; unknown labels are quoted."""
    rest = re.sub(r"^מרכזי (?:יעוץ|ייעוץ) למשפחות\s*", "", label).strip()
    return rest if rest.startswith("ב") else f"מסוג ״{label}״"


def insight_adapted(df, adj_counts):
    gen = _general_label(adj_counts)
    special = [k for k in adj_counts.index if k != gen]
    if not special or len(df) < 4:
        return None
    parts = []
    for k in special:
        sub = df[df["adj"] == k]
        cities = sorted(set(sub["city"]) - {CITY_NONE})
        p = f"{_n_centers(len(sub))} {_adj_phrase(k)}"
        if 1 <= len(cities) <= 8:
            p += f" ({_join(cities)})"
        elif cities:
            p += f" ב-{_n_cities(len(cities))}"
        parts.append(p)
    return _join(parts) + "."


def insight_hosp_general(df, type_counts, adj_counts):
    """Whether the hospital-based centers are all general-public (or not)."""
    gen = _general_label(adj_counts)
    if gen is None:
        return None
    hosp = [k for k in type_counts.index if "חולים" in k]
    if not hosp:
        return None
    h = df[df["ctype"].isin(hosp)]
    c = df[~df["ctype"].isin(hosp)]
    if len(h) < 2 or c.empty:
        return None
    h_special = int((h["adj"] != gen).sum())
    c_special = int((c["adj"] != gen).sum())
    where = _type_phrase(c["ctype"].iloc[0]) if c["ctype"].nunique() == 1 else "מחוץ לבתי החולים"
    if h_special == 0 and c_special > 0:
        return (f"כל {len(h):,} המרכזים בבתי החולים מיועדים לכל הציבור; כל {c_special:,} "
                f"המרכזים המותאמים לציבור מסוים פועלים {where}.")
    if h_special > 0:
        return (f"{h_special:,} מתוך {len(h):,} המרכזים בבתי החולים מותאמים לציבור מסוים, "
                f"לעומת {c_special:,} מתוך {len(c):,} {where}.")
    return None


def insight_networks(nets):
    big = [r for r in nets if r["branches"] >= 3]
    if not big:
        return None
    top = big[0]
    s = (f"הרשת הגדולה במאגר היא {top['label']}: {_n_centers(top['branches'])} "
         f"ב-{_n_cities(top['cities'])}")
    if len(big) >= 2:
        others = [f"{r['label']} ({r['branches']:,})" for r in big[1:4]]
        s += "; אחריה " + _join(others)
    return s + ". השיוך לפי המילה הראשונה בשם המרכז."


def insight_shared_phone(df):
    ph = df[df["phone"] != ""]
    g = ph.groupby("phone")["net"].agg(["size", "nunique"])
    g = g[g["size"] >= 2]
    if g.empty:
        return None
    covered = int(g["size"].sum())
    same_net = int((g["nunique"] == 1).sum())
    s = (f"{covered:,} מתוך {len(df):,} המרכזים חולקים מספר טלפון עם מרכז אחר "
         f"({len(g):,} מספרים משותפים)")
    if same_net == len(g):
        s += ", כל אחד מהם קו משותף לשלוחות של אותה רשת"
    elif same_net > len(g) / 2:
        s += f"; {same_net:,} מהם משותפים לשלוחות של אותה רשת"
    return s + "."


def insight_contact(df):
    n = len(df)
    if n < 4:
        return None
    email = int(((df["email"] != "") | df["email_hidden"]).sum())  # published, shown or not
    addr = int((df["address"] != "").sum())
    phone = int(((df["phone"] != "") | (df["phone2"] != "")).sum())
    if email >= n / 2 and addr >= n / 2:
        return None  # nothing notable is missing
    s = (f"לכל {n:,} המרכזים מופיע מספר טלפון" if phone == n
         else f"ל-{phone:,} מתוך {n:,} המרכזים מופיע מספר טלפון")
    gaps = []
    if email < n / 2:
        gaps.append("לאף מרכז לא פורסם דוא״ל" if email == 0
                    else f"דוא״ל פורסם רק ל-{email:,}")
    if addr < n / 2:
        gaps.append("אין כתובות רחוב" if addr == 0
                    else f"כתובת רחוב מלאה רשומה רק ל-{addr:,}")
    return s + ", אבל " + " ו".join(gaps) + "."


def insight_no_city(df):
    none = df[df["city"] == CITY_NONE]
    if none.empty:
        return None
    names = sorted(none["name"])
    if len(names) <= 3:
        return "לגבי " + _join(names) + " לא רשום יישוב במאגר."
    return f"ל-{len(names):,} מרכזים לא רשום יישוב במאגר."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["centers"])
    n = int(len(df))

    city_counts = _counts(df["city"])
    type_counts = _counts(df["ctype"])
    adj_counts = _counts(df["adj"])
    gen = _general_label(adj_counts)
    # general public first, then the adapted groups by size
    adj_order = ([gen] if gen else []) + [k for k in adj_counts.index if k != gen]
    type_order = list(type_counts.index)

    # ---- networks: groups of names sharing a first word
    df["net"] = df["name"].map(_net_key)
    nets = []
    for key, sub in df.groupby("net", sort=True):
        if key.startswith("="):
            continue
        firsts = _counts(sub["name"].map(lambda s: s.split(" ")[0]))
        label = _display_name(firsts.index[0])
        nets.append({"key": key, "label": label, "branches": int(len(sub)),
                     "cities": int(len(set(sub["city"]) - {CITY_NONE}))})
    nets = [r for r in nets if r["branches"] >= 2]
    nets.sort(key=lambda r: (-r["branches"], -r["cities"], r["key"]))
    in_nets = int(sum(r["branches"] for r in nets))
    solo = n - in_nets

    rules = [
        ("spread", insight_spread(df, city_counts)),
        ("types", insight_types(type_counts, n)),
        ("adapted", insight_adapted(df, adj_counts)),
        ("hosp_general", insight_hosp_general(df, type_counts, adj_counts)),
        ("networks", insight_networks(nets)),
        ("shared_phone", insight_shared_phone(df)),
        ("contact", insight_contact(df)),
        ("no_city", insight_no_city(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    named_cities = city_counts.drop(CITY_NONE, errors="ignore")
    hosp_keys = [k for k in type_order if "חולים" in k]
    n_hosp = int(df["ctype"].isin(hosp_keys).sum())
    n_adapted = int((df["adj"] != gen).sum()) if gen else 0
    kpis = {
        "total": {"value": n, "display": f"{n:,}", "tone": "brand"},
        "cities": {"value": int(len(named_cities)), "display": f"{len(named_cities):,}",
                   "tone": "brand"},
        "hosp": {"value": n_hosp, "display": f"{n_hosp:,}", "tone": "brand"},
        "adapted": {"value": n_adapted, "display": f"{n_adapted:,}",
                    "tone": "info" if n_adapted else "brand"},
    }

    # ---- type chart (pie)
    type_rows = [{"name": k, "n": int(type_counts[k]), "pct": _pct(int(type_counts[k]), n)}
                 for k in type_order]
    type_chart = {"items": [{"name": r["name"], "value": r["n"]} for r in type_rows]}

    # ---- adaptation chart
    adj_rows = [{"name": k, "n": int(adj_counts[k]), "pct": _pct(int(adj_counts[k]), n)}
                for k in adj_order]
    adj_chart = {"names": [r["name"] for r in adj_rows], "values": [r["n"] for r in adj_rows]}

    # ---- cross: type x adaptation (stacked bars, one bar per type)
    cross = df.groupby(["ctype", "adj"]).size()
    cross_chart = {
        "types": type_order,
        "series": [{"name": a, "data": [int(cross.get((t, a), 0)) for t in type_order]}
                   for a in adj_order],
    }
    cross_rows = [{"name": t, "cells": [int(cross.get((t, a), 0)) for a in adj_order],
                   "n": int(type_counts[t])} for t in type_order]

    # ---- cities: top-N + אחר, stacked by adaptation, ascending for hbar
    keep = len(city_counts) if len(city_counts) <= TOP_CITIES + 2 else TOP_CITIES
    top = list(city_counts.index[:keep])
    rest_cities = list(city_counts.index[keep:])
    rest = int(city_counts.iloc[keep:].sum())
    cc = df.groupby(["city", "adj"]).size()
    city_rows = [{"name": c, "n": int(city_counts[c]),
                  "cells": [int(cc.get((c, a), 0)) for a in adj_order]} for c in top]
    if rest:
        city_rows.append({"name": f"אחר ({len(rest_cities):,} יישובים)", "n": rest,
                          "cells": [int(sum(cc.get((c, a), 0) for c in rest_cities))
                                    for a in adj_order]})
    rows_asc = city_rows[::-1]
    city_chart = {"names": [r["name"] for r in rows_asc],
                  "series": [{"name": a, "data": [r["cells"][i] for r in rows_asc]}
                             for i, a in enumerate(adj_order)]}

    # ---- networks chart
    net_rows = [{"name": r["label"], "n": r["branches"], "cities": r["cities"]} for r in nets]
    net_rows_t = net_rows + ([{"name": "מרכזים שאינם חלק מרשת", "n": solo, "cities": int(
        len(set(df[~df["net"].isin([r["key"] for r in nets])]["city"]) - {CITY_NONE}))}]
        if solo else [])
    net_chart = {"names": [r["name"] for r in net_rows_t][::-1],
                 "values": [r["n"] for r in net_rows_t][::-1]}

    # ---- reach: distinct cities per adaptation
    reach_rows = []
    for a in adj_order:
        sub = df[df["adj"] == a]
        reach_rows.append({"name": a, "n": int(len(set(sub["city"]) - {CITY_NONE})),
                           "centers": int(len(sub))})
    reach_chart = {"names": [r["name"] for r in reach_rows],
                   "centers": [r["centers"] for r in reach_rows],
                   "cities": [r["n"] for r in reach_rows]}

    # ---- contact completeness
    has_phone = int((df["phone"] != "").sum())
    has_two = int(((df["phone"] != "") & (df["phone2"] != "")).sum())
    has_email = int((df["email"] != "").sum())
    hidden_email = int(df["email_hidden"].sum())
    hidden_note = (f" {hidden_email:,} כתובות דוא״ל בשירותי דואר פרטיים אינן "
                   "מוצגות בעמוד." if hidden_email else "")
    has_addr = int((df["address"] != "").sum())
    shared = df[df["phone"] != ""].groupby("phone")["name"].transform("size")
    has_shared = int((shared >= 2).sum())
    contact_rows = [
        {"name": "טלפון", "n": has_phone},
        {"name": "טלפון נוסף", "n": has_two},
        {"name": "טלפון משותף לכמה מרכזים", "n": has_shared},
        {"name": "כתובת רחוב", "n": has_addr},
        {"name": "דוא״ל", "n": has_email},
    ]
    for r in contact_rows:
        r["pct"] = _pct(r["n"], n)
    contact_chart = {"names": [r["name"] for r in contact_rows],
                     "values": [r["n"] for r in contact_rows], "total": n}

    # ---- directory
    directory = []
    for _, r in df.head(DIR_CAP).iterrows():
        phones = [p for p in (r["phone"], r["phone2"]) if p and _tel(p)]
        directory.append({
            "name": r["name"],
            "city": r["city"],
            "address": r["address"],
            "phones": [{"display": p, "tel": _tel(p)} for p in phones],
            "email": r["email"],
            "type": _type_phrase(r["ctype"]),
            "adj": r["adj"],
            "special": bool(gen) and r["adj"] != gen,
        })

    # ---- summary (meta description)
    where = _join(_type_phrase(k) for k in type_order if not _type_phrase(k).startswith("מסוג"))
    summary = (f"איתור מרכז ייעוץ למשפחות של נפגעי נפש לפי עיר, עם טלפון: {_n_centers(n)} "
               f"ב-{_n_cities(len(named_cities))}" + (f", {where}." if where else "."))
    if len(summary) > SUMMARY_MAX:
        summary = (f"איתור מרכז ייעוץ למשפחות של נפגעי נפש לפי עיר: {_n_centers(n)} "
                   f"ב-{_n_cities(len(named_cities))}.")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "suggested_tags": ["בריאות הנפש", "תמיכה במשפחות", "מרכזי ייעוץ", "שיקום",
                           "שירותים בקהילה"],
        "related_ids": ["b54ae5a7-1bd5-4e7f-8b9d-f367f8eefd65",
                        "b08ed183-2c26-490f-aa13-f1a7529c3aca"],
        "spatial_coverage": "ישראל",
    }

    named = named_cities
    top_city = named.index[0] if len(named) else ""
    adj_bits = [f"{r['name']}: {r['n']:,}" for r in adj_rows]
    labels = {
        "kpi_total": "מרכזי ייעוץ למשפחות במאגר",
        "kpi_cities": "יישובים שבהם פועל לפחות מרכז אחד",
        "kpi_hosp": "מרכזים הפועלים בבתי חולים",
        "kpi_adapted": "מרכזים המותאמים לציבור מסוים (חרדי, ערבי ועוד)",
        "dir_lede": (f"כל המרכזים במאגר ({n:,}), ממוינים לפי יישוב. מספרי הטלפון מופיעים כפי "
                     "שפורסמו; כמה שלוחות של אותה רשת חולקות קו אחד." + hidden_note if n <= DIR_CAP else
                     f"{DIR_CAP:,} המרכזים הראשונים מתוך {n:,}, ממוינים לפי יישוב. "
                     "הרשימה המלאה בחיפוש החי שבתחתית העמוד." + hidden_note),
        "dir_caption": f"מדריך מרכזי הייעוץ למשפחות: {n:,} מרכזים, שם, יישוב, סוג, התאמה וטלפון.",
        "type_lede": (" ".join(f"{_n_centers(r['n'])} {_type_phrase(r['name'])} ({r['pct']})."
                               for r in type_rows)),
        "type_aria": ("תרשים עוגה: מרכזי הייעוץ לפי סוג. "
                      + ", ".join(f"{r['name']} {r['n']:,}" for r in type_rows) + "."),
        "adj_lede": ("למי המרכז מותאם, לפי שדה ההתאמה במאגר. "
                     + "; ".join(adj_bits) + "."),
        "adj_aria": "תרשים עמודות: מרכזים לפי התאמה לציבור. " + ", ".join(adj_bits) + ".",
        "cross_lede": ("כל עמודה היא סוג מרכז, מחולקת לפי ההתאמה לציבור. "
                       + ("מרכזי בתי החולים כולם לכל הציבור."
                          if n_hosp and gen and not int(((df["ctype"].isin(hosp_keys))
                                                         & (df["adj"] != gen)).sum())
                          else "")).strip(),
        "cross_aria": (f"תרשים עמודות מוערמות: {len(type_order):,} סוגי מרכזים לפי התאמה "
                       f"לציבור, {len(adj_order):,} קבוצות התאמה."),
        "city_lede": (f"{_n_centers(n)} ב-{_n_cities(len(named))}. "
                      + (f"{top_city} במקום הראשון עם {_n_centers(int(named.iloc[0]))}. "
                         if len(named) >= 2 and named.iloc[0] > named.iloc[1] else "")
                      + "הצבע מראה את ההתאמה לציבור."
                      + (f" מעבר ל-{keep:,} היישובים המובילים, השאר מקובצים ב״אחר״."
                         if rest else "")),
        "city_aria": (f"תרשים עמודות אופקי מוערם: מרכזים לפי יישוב והתאמה לציבור, "
                      f"{len(named):,} יישובים" + (f", המוביל {top_city}" if top_city else "")
                      + "."),
        "net_lede": ("מרכזים ששמם מתחיל באותה מילה (למשל שם הרשת ואחריו ״שלוחת …״) מקובצים "
                     f"כרשת אחת. {len(nets):,} רשתות מפעילות {in_nets:,} מתוך {n:,} המרכזים. "
                     "זהו שיוך לפי השם, לא שדה רשמי במאגר."),
        "net_aria": (f"תרשים עמודות אופקי: מספר המרכזים בכל רשת, {len(nets):,} רשתות"
                     + (f", הגדולה {nets[0]['label']} עם {nets[0]['branches']:,}" if nets else "")
                     + "."),
        "reach_lede": ("בכמה יישובים שונים יש מרכז מכל סוג התאמה, לצד מספר המרכזים. "
                       + "; ".join(f"{r['name']}: {r['centers']:,} מרכזים ב-{_n_cities(r['n'])}"
                                   for r in reach_rows) + "."),
        "reach_aria": ("תרשים עמודות: מספר המרכזים ומספר היישובים לכל קבוצת התאמה. "
                       + ", ".join(f"{r['name']} {r['centers']:,} מרכזים ו-{r['n']:,} יישובים"
                                   for r in reach_rows) + "."),
        "contact_lede": (f"כמה מהמרכזים מפרסמים כל פרט. {_pct(has_phone, n)} עם טלפון, "
                         f"{_pct(has_addr, n)} עם כתובת רחוב ו-{_pct(has_email, n)} עם דוא״ל מוצג."
                         + hidden_note),
        "contact_aria": (f"תרשים עמודות: זמינות פרטי קשר מתוך {n:,} מרכזים. טלפון {has_phone:,}, "
                         f"טלפון נוסף {has_two:,}, כתובת רחוב {has_addr:,}, דוא״ל {has_email:,}."),
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"types": type_chart, "adj": adj_chart, "cross": cross_chart,
                   "cities": city_chart, "networks": net_chart, "reach": reach_chart,
                   "contact": contact_chart},
        "insights": insights,
        "tables": {"types": type_rows, "adj": adj_rows, "adj_order": adj_order,
                   "cross": cross_rows, "cities": city_rows, "networks": net_rows_t,
                   "reach": reach_rows, "contact": contact_rows, "directory": directory},
        "flags": {"has_types": len(type_order) >= 2, "has_cross": len(type_order) >= 2
                  and len(adj_order) >= 2, "has_cities": len(named) >= 2,
                  "has_networks": len(nets) >= 1, "has_adj": len(adj_order) >= 2},
        "labels": labels,
    }
