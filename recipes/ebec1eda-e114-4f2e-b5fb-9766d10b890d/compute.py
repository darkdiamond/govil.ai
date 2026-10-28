"""מאגר רשם המפלגות — every party currently on the Registrar of Parties' list.

One row per party: name, registration number (59-900NNN-C, assigned in
sequence), stated aims (free text), registered address (free text), email and a
mostly-empty registration date. There is no time series and no amount, so the
page describes the register: how far the numbering runs and which numbers are
absent from the current list, where parties register their address (town
only — the address itself often sits at a private home, so it never reaches
the page), how they can be contacted (email type, PO box, c/o a law or
accounting office), what the stated aims mention (keyword themes) and how long
they are, and how names are built.

Neutrality: everything is a count of what the register says. No party is
characterised; themes are keyword matches over the party's own text, labelled
as such. Party names appear only in the lowest/highest-number tables.

Growth: monthly updates add parties at the top of the numbering and drop
deregistered ones. Number bands widen so there are never more than MAX_BANDS;
towns are top-N + "other"; themes and email-domain groups are fixed keyword
maps with a fallback bucket.
"""
import re
import statistics

import pandas as pd

TOP_TOWNS = 10
MAX_BANDS = 12
TOP_THEMES = 15
EDGE_N = 10

# Prefix-letter boundary for Hebrew keyword stems: not preceded by a Hebrew
# letter except up to three prefix letters (ו/ב/ל/ה/מ/ש/כ).
_PRE = "(?<![א-ת])[ובלהמשכ]{0,3}"

THEMES = [
    ("חינוך", ["חינוך", "חנוך"]),
    ("שוויון", ["שוויון", "שיוויון", "שויון"]),
    ("שלום", ["שלום"]),
    ("זכויות", ["זכויות"]),
    ("דמוקרטיה", ["דמוקרט"]),
    ("כלכלה ותעסוקה", ["כלכל", "תעסוק"]),
    ("ביטחון", ["ביטחון", "בטחון"]),
    ("רווחה", ["רווחה", "רווחת"]),
    ("בריאות", ["בריאות"]),
    ("דיור", ["דיור"]),
    ("נשים ומגדר", ["נשים", "מגדר", "אישה", "אשה"]),
    ("יהדות ומסורת", ["יהדות", "תורה", "מסורת"]),
    ("שחיתות וטוהר המידות", ["שחיתות", "טוהר המידות"]),
    ("ציונות", ["ציונ"]),
    ("חוקה", ["חוקה"]),
    ("אנשים עם מוגבלות", ["מוגבלות", "מוגבלויות", "נכים", "נכות"]),
    ("אזרחים ותיקים", ["גמלא", "גימלא", "אזרחים ותיקים", "אזרחים הותיקים", "קשיש"]),
    ("עלייה וקליטה", ["עולים(?! לדיון)", "קליטת", "קליטה"]),
    ("איכות הסביבה", ["איכות הסביבה", "סביבתי", "אקולוג"]),
    ("שלטון מקומי", ["שלטון המקומי", "שלטון מקומי", "רשויות המקומיות", "רשויות מקומיות",
                     "הרשות המקומית", "רשות מקומית"]),
]
_THEME_RX = [(name, re.compile(_PRE + "(?:" + "|".join(stems) + ")")) for name, stems in THEMES]

# Towns: canonical name -> spellings. Longer/more specific first where one
# spelling contains another (נצרת עילית before נצרת, תל אביב before יפו).
TOWNS = [
    ("תל אביב-יפו", ["תל אביב", "תל-אביב", "יפו"]),
    ("ירושלים", ["ירושלים"]),
    ("חיפה", ["חיפה"]),
    ("בני ברק", ["בני ברק", "בני-ברק"]),
    ("רמת גן", ["רמת גן", "רמת-גן"]),
    ("גבעתיים", ["גבעתיים"]),
    ("ראשון לציון", ["ראשון לציון"]),
    ("פתח תקווה", ["פתח תקווה", "פתח תקוה", "פתח-תקוה", "פתח-תקווה"]),
    ("חולון", ["חולון"]),
    ("בת ים", ["בת ים", "בת-ים"]),
    ("רחובות", ["רחובות"]),
    ("נתניה", ["נתניה"]),
    ("הרצליה", ["הרצליה"]),
    ("רעננה", ["רעננה"]),
    ("כפר סבא", ["כפר סבא"]),
    ("רמת השרון", ["רמת השרון"]),
    ("הוד השרון", ["הוד השרון"]),
    ("ראש העין", ["ראש העין"]),
    ("גבעת שמואל", ["גבעת שמואל"]),
    ("קריית אונו", ["קרית אונו", "קריית אונו"]),
    ("אור יהודה", ["אור יהודה"]),
    ("אלעד", ["אלעד"]),
    ("מודיעין", ["מודיעין"]),
    ("לוד", ["לוד"]),
    ("רמלה", ["רמלה"]),
    ("אשדוד", ["אשדוד"]),
    ("אשקלון", ["אשקלון"]),
    ("באר שבע", ["באר שבע", "באר-שבע"]),
    ("רהט", ["רהט"]),
    ("חורה", ["חורה"]),
    ("דימונה", ["דימונה"]),
    ("אילת", ["אילת"]),
    ("בית שמש", ["בית שמש"]),
    ("אפרת", ["אפרת", "אפרתה"]),
    ("אריאל", ["אריאל"]),
    ("קריית ארבע", ["קרית ארבע", "קריית ארבע"]),
    ("מעלה אדומים", ["מעלה אדומים"]),
    ("כפר אדומים", ["כפר אדומים"]),
    ("קריית יערים", ["קרית יערים", "קריית יערים"]),
    ("נצרת עילית", ["נצרת עלית", "נצרת עילית", "נוף הגליל"]),
    ("נצרת", ["נצרת"]),
    ("עפולה", ["עפולה"]),
    ("טבריה", ["טבריה"]),
    ("עכו", ["עכו"]),
    ("כרמיאל", ["כרמיאל"]),
    ("סח'נין", ["סח'נין", "סכנין"]),
    ("אעבלין", ["אעבלין"]),
    ("שפרעם", ["שפרעם"]),
    ("טמרה", ["טמרה"]),
    ("קריית אתא", ["קרית אתא", "קריית אתא"]),
    ("קריית טבעון", ["קרית טבעון", "קריית טבעון"]),
    ("קריית שמונה", ["קרית שמונה", "קריית שמונה"]),
    ("צפת", ["צפת"]),
    ("ראש פינה", ["ראש פינה"]),
    ("חדרה", ["חדרה"]),
    ("חריש", ["חריש"]),
    ("עתלית", ["עתלית"]),
    ("אום אל-פחם", ["אום אל פחם", "אום אל-פחם"]),
    ("טייבה", ["טייבה", "טיבה"]),
    ("טירה", ["טירה"]),
    ("כפר קרע", ["כפר קרע"]),
    ("אבן יהודה", ["אבן יהודה"]),
]
_TOWN_RX = [(name, re.compile("(?<![א-ת])[ב]?(?:" + "|".join(map(re.escape, sp)) + ")(?![א-ת])"))
            for name, sp in TOWNS]
RURAL = re.compile(r"(?<![א-ת])(?:קיבוץ|קבוץ|מושב)(?![א-ת])")
RURAL_TOWN = "קיבוץ או מושב (אחר)"
OTHER_TOWN = "יישובים אחרים"
UNKNOWN_TOWN = "לא זוהה יישוב"

FREE_MAIL = {"gmail.com": "Gmail"}
OTHER_FREE = ("walla.", "hotmail.", "yahoo.", "nana10.", "outlook.", "live.", "icloud.", "aol.")
ISP = ("netvision.", "012.", "013.", "013net.", "bezeqint.", "zahav.", "smile.", "inter.net.",
       "actcom.", "barak.")
EMAIL_GROUPS = ["Gmail", "שירות דואר חינמי אחר", "ספק אינטרנט", "דומיין ייעודי", "ללא דוא״ל"]

NAME_FEATURES = [
    ("שם עם כותרת משנה (מקף)", re.compile(r"\s[–-]|[–-]\s")),
    ("המילה „ישראל” בשם", re.compile(r"ישראל")),
    ("המילה „מפלגה” בשם", re.compile(r"מפלג")),
    ("המילה „תנועה” בשם", re.compile(r"תנוע")),
    ("„בראשות” בשם", re.compile(r"בראשות|בהנהגת")),
]


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _range(a, b):
    return f"{a:,} עד {b:,}"


def _clean(s):
    # Registrar export: '~' stands for '"' (ש~ס, עו~ד, ת~ד).
    return s.str.replace("~", '"', regex=False).str.replace(r"\s+", " ", regex=True).str.strip()


def _serial(num):
    digits = re.sub(r"\D", "", num)
    if len(digits) != 9:
        return None
    return int(digits[2:8]) - 900000


def _town(addr):
    best = None
    for name, rx in _TOWN_RX:
        for m in rx.finditer(addr):
            # Latest mention wins: the town follows the street in Israeli addresses.
            if best is None or m.start() > best[0]:
                best = (m.start(), name)
    if best:
        return best[1]
    # Small settlements outside the list: group kibbutz/moshav addresses.
    return RURAL_TOWN if RURAL.search(addr) else ""


def _email_group(raw):
    m = re.search(r"@([\w.-]+)", raw)
    if not m:
        return "ללא דוא״ל"
    dom = m.group(1).lower().rstrip(".")
    if dom in FREE_MAIL:
        return FREE_MAIL[dom]
    if dom.startswith(OTHER_FREE):
        return "שירות דואר חינמי אחר"
    if dom.startswith(ISP):
        return "ספק אינטרנט"
    return "דומיין ייעודי"


def _prepare(raw):
    df = pd.DataFrame({
        "name": _clean(raw["שם מפלגה"]),
        "num": raw["מספר מפלגה"].str.strip(),
        "aims": _clean(raw["מטרות"]),
        "addr": _clean(raw["כתובת"]),
        "email": raw["דואר אלקטרוני"].str.strip(),
        "regdate": _clean(raw["תאריך רישום"]),
    })
    df["serial"] = df["num"].map(_serial)
    df["town"] = df["addr"].map(_town)
    df["email_group"] = df["email"].map(_email_group)
    df["n_emails"] = df["email"].str.count("@")
    df["words"] = df["aims"].map(lambda t: len(t.split()))
    for name, rx in _THEME_RX:
        df["t:" + name] = df["aims"].map(lambda t, rx=rx: bool(rx.search(t)))
    df["po_box"] = df["addr"].str.contains(r'ת"ד|ת\.ד|(?<![א-ת])תד\s', regex=True)
    df["c_o"] = df["addr"].str.contains(r"(?<![א-ת])אצל|לידי", regex=True)
    df["office"] = df["addr"].str.contains(r'עו"ד|עורך דין|עורכי דין|עורכת דין|רו"ח|משרד', regex=True)
    df["reg_year"] = df["regdate"].str.extract(r"((?:19|20)\d\d)", expand=False).fillna("")
    return df.sort_values(["serial", "num", "name"], kind="stable", na_position="last").reset_index(drop=True)


def _bar(items):
    return {"names": [k for k, _ in items], "values": [int(v) for _, v in items]}


def _vc(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


# ---------------------------------------------------------------- insights

def insight_numbering(n, top, absent):
    if top is None:
        return None
    if not absent:
        return f"ברשימה {_int(n)} מפלגות, הנושאות את מספרי הרישום {_range(1, top)} ללא פערים."
    return (f"ברשימה {_int(n)} מפלגות. מספרי הרישום מוקצים ברצף ומגיעים עד {_int(top)}; "
            f"{_int(len(absent))} מספרים בטווח אינם מופיעים ברשימה הנוכחית.")


def insight_town(df):
    known = df[~df["town"].isin(["", RURAL_TOWN])]
    if len(known) < 20:
        return None
    vc = _vc(known["town"])
    lead, second = vc.index[0], vc.index[1] if len(vc) > 1 else None
    s1 = vc.iloc[0] / len(df)
    if s1 < 0.15 or second is None:
        return None
    s2 = vc.iloc[1] / len(df)
    return (f"{lead} היא יישוב הכתובת הרשומה של {_int(vc.iloc[0])} מפלגות ({_pct(s1)}), "
            f"ואחריה {second} עם {_int(vc.iloc[1])} ({_pct(s2)}) — יחד {_pct(s1 + s2)} מהרשימה.")


def insight_office(df):
    k = int(df["office"].sum())
    share = k / len(df)
    if share < 0.1:
        return None
    po = int(df["po_box"].sum())
    return (f"{_int(k)} מפלגות ({_pct(share)}) רשמו כתובת במשרד עורכי דין או רואי חשבון, "
            f"ו-{_int(po)} ({_pct(po / len(df))}) ציינו תיבת דואר.")


def insight_email(df):
    has = df[df["email_group"] != "ללא דוא״ל"]
    if not len(has):
        return None
    vc = _vc(has["email_group"])
    lead, lead_n = vc.index[0], int(vc.iloc[0])
    own = int((has["email_group"] == "דומיין ייעודי").sum())
    lead_txt = (f"{_pct(lead_n / len(has))} מהן בכתובת {lead}" if lead == "Gmail"
                else f"הקבוצה הנפוצה: {lead} ({_pct(lead_n / len(has))})")
    return (f"ל-{_int(len(has))} מפלגות ({_pct(len(has) / len(df))}) רשומה כתובת דוא״ל; "
            f"{lead_txt}, ו-{_int(own)} משתמשות בדומיין ייעודי של ארגון או משרד.")


def insight_themes(df, themes):
    if not themes or themes[0][1] / len(df) < 0.2:
        return None
    (a, na), (b, nb) = themes[0], themes[1]
    return (f"הנושא הנזכר במטרות של הכי הרבה מפלגות הוא {a} ({_int(na)} מפלגות, {_pct(na / len(df))}), "
            f"ואחריו {b} ({_int(nb)}) — לפי זיהוי מילות מפתח בטקסט המטרות.")


def insight_aims(df):
    w = df.loc[df["words"] > 0, "words"].tolist()
    if len(w) < 10:
        return None
    none = int((df["words"] == 0).sum())
    med = statistics.median(w)
    tail = f"; ל-{_int(none)} מפלגות לא רשומות מטרות כלל" if none else ""
    return (f"אורך המטרות החציוני הוא {med:,.0f} מילים, מ-{_int(min(w))} ועד {_int(max(w))} "
            f"מילים{tail}.")


def insight_leader(df):
    k = int(df["name"].str.contains(r"בראשות|בהנהגת", regex=True).sum())
    if k < 3:
        return None
    return f"{_int(k)} מפלגות כוללות בשמן את המילה „בראשות” או „בהנהגת” ואחריה שם העומד בראשן."


def insight_regdate(df):
    k = int((df["regdate"] != "").sum())
    if k == 0 or k / len(df) > 0.5:
        return None
    years = sorted(y for y in df["reg_year"].unique() if y)
    if len(years) == 1:
        yt = f"וכל הערכים בו מציינים את שנת {years[0]}"
    elif years:
        yt = f"והשנים המצוינות בו: {years[0]} עד {years[-1]}"
    else:
        yt = "אך ללא שנה מזוהה"
    return (f"שדה תאריך הרישום מולא ל-{_int(k)} מפלגות בלבד ({_pct(k / len(df))}), {yt}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames.pop("parties"))
    n = len(df)
    ser = df["serial"].dropna().astype(int)
    top = int(ser.max()) if len(ser) else None
    present = set(ser.tolist())
    absent = sorted(set(range(1, top + 1)) - present) if top else []

    # Number bands: width a multiple of 10, at most MAX_BANDS bands.
    width = 10
    while top and -(-top // width) > MAX_BANDS:
        width += 10
    bands = {"names": [], "present": [], "absent": []}
    for lo in range(1, (top or 0) + 1, width):
        hi = min(lo + width - 1, top)
        p = sum(1 for v in range(lo, hi + 1) if v in present)
        bands["names"].append(_range(lo, hi))
        bands["present"].append(p)
        bands["absent"].append(hi - lo + 1 - p)

    # Completeness of each field.
    fields = [
        ("שם מפלגה", (df["name"] != "").sum()),
        ("מספר מפלגה", df["serial"].notna().sum()),
        ("כתובת", (df["addr"] != "").sum()),
        ("מטרות", (df["aims"] != "").sum()),
        ("דואר אלקטרוני", (df["email_group"] != "ללא דוא״ל").sum()),
        ("תאריך רישום", (df["regdate"] != "").sum()),
    ]
    complete = _bar(fields)
    complete["shares"] = [round(v / n * 100, 1) for v in complete["values"]]

    # Towns.
    known = df[~df["town"].isin(["", RURAL_TOWN])]
    tvc = _vc(known["town"])
    towns = [(k, v) for k, v in tvc.head(TOP_TOWNS).items()]
    rest = int(tvc.iloc[TOP_TOWNS:].sum())
    if rest:
        towns.append((OTHER_TOWN, rest))
    rural = int((df["town"] == RURAL_TOWN).sum())
    if rural:
        towns.append((RURAL_TOWN, rural))
    unknown = int((df["town"] == "").sum())
    if unknown:
        towns.append((UNKNOWN_TOWN, unknown))
    towns_c = _bar(towns)

    # Address arrangement (non-exclusive flags).
    arr = _bar([
        ("כתובת „אצל”", df["c_o"].sum()),
        ("משרד עו״ד או רו״ח", df["office"].sum()),
        ("תיבת דואר", df["po_box"].sum()),
    ])
    arr["shares"] = [round(v / n * 100, 1) for v in arr["values"]]

    # Email groups (fixed order, drop empty groups).
    evc = df["email_group"].value_counts()
    email = _bar([(g, evc.get(g, 0)) for g in EMAIL_GROUPS if evc.get(g, 0)])
    multi = int((df["n_emails"] > 1).sum())

    # Themes.
    tcounts = [(name, int(df["t:" + name].sum())) for name, _ in THEMES]
    tcounts = [t for t in tcounts if t[1] > 0]
    tcounts.sort(key=lambda t: (-t[1], [x for x, _ in THEMES].index(t[0])))
    themes = _bar(tcounts[:TOP_THEMES])
    themes["shares"] = [round(v / n * 100, 1) for v in themes["values"]]
    tcols = ["t:" + name for name, _ in THEMES]
    per_party = df[tcols].sum(axis=1).astype(int)
    k_max = int(per_party.max()) if n else 0
    cap = 8
    tp_names = [str(i) for i in range(0, min(k_max, cap) + 1)]
    tp_vals = [int((per_party == i).sum()) for i in range(0, min(k_max, cap) + 1)]
    if k_max > cap:
        tp_names[-1] = f"{cap} ומעלה"
        tp_vals[-1] = int((per_party >= cap).sum())
    theme_per = {"names": tp_names, "values": tp_vals}
    with_aims = df["words"] > 0
    med_themes = statistics.median(per_party[with_aims].tolist()) if with_aims.any() else 0

    # Aims length bands (words).
    edges = [(1, 25), (26, 50), (51, 100), (101, 200), (201, None)]
    ln = [("ללא מטרות", int((df["words"] == 0).sum()))]
    for lo, hi in edges:
        m = (df["words"] >= lo) & ((df["words"] <= hi) if hi else True)
        ln.append((_range(lo, hi) if hi else f"{lo:,} ומעלה", int(m.sum())))
    if ln[0][1] == 0:
        ln = ln[1:]
    length = _bar(ln)
    med_words = statistics.median(df.loc[with_aims, "words"].tolist()) if with_aims.any() else 0

    # Name structure.
    names = _bar([(lab, df["name"].map(lambda t, rx=rx: bool(rx.search(t))).sum()) for lab, rx in NAME_FEATURES])
    names["shares"] = [round(v / n * 100, 1) for v in names["values"]]
    name_words = statistics.median(df["name"].map(lambda t: len(t.split())).tolist())

    # Lowest / highest registration numbers on the list.
    numbered = df[df["serial"].notna()]
    low = [{"serial": int(r.serial), "name": r.name} for r in numbered.head(EDGE_N).itertuples()]
    high = [{"serial": int(r.serial), "name": r.name}
            for r in numbered.tail(EDGE_N).iloc[::-1].itertuples()]

    rules = [
        ("numbering", insight_numbering(n, top, absent)),
        ("town", insight_town(df)),
        ("email", insight_email(df)),
        ("office", insight_office(df)),
        ("themes", insight_themes(df, tcounts)),
        ("aims", insight_aims(df)),
        ("leader", insight_leader(df)),
        ("regdate", insight_regdate(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    n_email = int((df["email_group"] != "ללא דוא״ל").sum())
    email_share = n_email / n
    n_reg = int((df["regdate"] != "").sum())
    n_towns = int(tvc.size)

    return {
        "agent_data": {
            "summary_he": (f"רשימת {_int(n)} המפלגות הרשומות אצל רשם המפלגות במשרד המשפטים, עם מספרי "
                           f"רישום עד {_int(top or 0)}: שם, מטרות, יישוב הכתובת הרשומה ודרכי יצירת קשר. "
                           f"{_pct(email_share)} מהמפלגות רשמו כתובת דוא״ל."),
            "dataset_kind": "registry",
            "suggested_tags": ["מפלגות", "רשם המפלגות", "בחירות", "משרד המשפטים", "תאגידים"],
            "related_ids": [
                "c5ac01fb-c7ef-4e5e-ba81-e9e11c6f7bd9",
                "246d949c-a253-4811-8a11-41a137d3d613",
                "ed98fd7a-0e62-4691-b733-1960a6ea2c73",
                "a52c0585-8af8-42bd-8c5c-03c6550682ea",
                "ebe5ec6f-3e37-4bd9-bbdc-926ad1e0d6b9",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "total": {"value": n, "display": _int(n), "tone": "brand"},
            "top": {"value": top or 0, "display": _int(top or 0), "tone": "brand"},
            "absent": {"value": len(absent), "display": _int(len(absent)), "tone": "info"},
            # Contact completeness: most parties reachable by email is good.
            "email": {"value": round(email_share * 100, 1), "display": _pct(email_share),
                      "tone": "ok" if email_share >= 0.8 else "warn" if email_share < 0.5 else "brand"},
            "regdate": {"value": n_reg, "display": _int(n_reg),
                        "tone": "warn" if n_reg / n < 0.5 else "brand"},
        },
        "charts": {
            "bands": bands,
            "complete": complete,
            "towns": towns_c,
            "arrangement": arr,
            "email": email,
            "themes": themes,
            "theme_per": theme_per,
            "length": length,
            "names": names,
        },
        "tables": {"low": low, "high": high},
        "insights": insights,
        "labels": {
            "lede": (f"{_int(n)} מפלגות רשומות כיום במרשם שמנהל רשם המפלגות במשרד המשפטים. מספרי "
                     f"הרישום מוקצים ברצף ומגיעים עד {_int(top or 0)}. העמוד מסכם את מה שהמפלגות "
                     f"מסרו לרשם — יישוב הכתובת, דרכי יצירת קשר, נושאי המטרות ומבנה השם — בלי "
                     f"לאפיין אף מפלגה."),
            "bands_note": (f"כל עמודה היא טווח של {_int(width)} מספרי רישום. בכחול — מספרים של מפלגות "
                           f"ברשימה הנוכחית; באפור — {_int(len(absent))} מספרים בטווח שאינם מופיעים בה."),
            "bands_aria": f"תרשים עמודות מוערמות: מספרי הרישום {_range(1, top or 0)} בטווחים, מופיעים ואינם מופיעים ברשימה.",
            "complete_note": f"כמה מתוך {_int(n)} המפלגות מילאו כל שדה במאגר.",
            "complete_aria": f"תרשים עמודות: מספר המפלגות שמילאו כל שדה, מתוך {_int(n)}.",
            "towns_note": (f"היישוב זוהה מתוך טקסט הכתובת ב-{_int(len(known))} מתוך {_int(n)} רשומות "
                           f"({_int(n_towns)} יישובים שונים). הכתובת המלאה אינה מוצגת."),
            "towns_aria": f"תרשים עמודות: {_int(min(TOP_TOWNS, n_towns))} היישובים עם מספר המפלגות הגבוה ביותר לפי הכתובת הרשומה.",
            "arrangement_note": "מאפייני הכתובת שמסרו המפלגות לרשם. מפלגה יכולה להופיע ביותר ממאפיין אחד.",
            "arrangement_aria": f"תרשים עמודות: מאפייני הכתובת הרשומה, מתוך {_int(n)} מפלגות.",
            "email_note": (f"לפי סוג הדומיין של כתובת הדוא״ל הראשונה („דומיין ייעודי” — כתובת בדומיין של "
                           f"ארגון או משרד); ל-{_int(multi)} מפלגות רשומה "
                           f"יותר מכתובת אחת. הכתובות עצמן אינן מוצגות."),
            "email_aria": f"תרשים טבעת: {_int(n)} המפלגות לפי סוג כתובת הדוא״ל.",
            "themes_note": (f"מספר המפלגות שבטקסט המטרות שלהן מופיעה מילת מפתח מכל נושא. זיהוי אוטומטי "
                            f"לפי מילים — לא סיווג של המפלגות; מפלגה יכולה להופיע בכמה נושאים."),
            "themes_aria": f"תרשים עמודות: {_int(len(themes['names']))} הנושאים הנזכרים במטרות של הכי הרבה מפלגות.",
            "theme_per_note": (f"בכמה מתוך {_int(len(THEMES))} הנושאים שנבדקו נוגע טקסט המטרות של כל "
                               f"מפלגה. החציון: {med_themes:,.0f} נושאים."),
            "theme_per_aria": "תרשים עמודות: מספר המפלגות לפי מספר הנושאים שזוהו במטרותיהן.",
            "length_note": f"אורך טקסט המטרות במילים. החציון: {med_words:,.0f} מילים.",
            "length_aria": "תרשים עמודות: מספר המפלגות לפי אורך טקסט המטרות במילים.",
            "names_note": (f"מילים ומבנים חוזרים בשמות המפלגות. אורך שם חציוני: {name_words:,.0f} מילים."),
            "names_aria": f"תרשים עמודות: מאפייני שמות המפלגות, מתוך {_int(n)}.",
            "edges_note": (f"מספרי הרישום מוקצים לפי סדר הרישום, ולכן המספרים הנמוכים הם הרישומים "
                           f"המוקדמים שעדיין ברשימה והגבוהים — המאוחרים."),
        },
    }
