"""סוחרי רכב — Ministry of Transport register of licensed motor-vehicle dealers.

One row per registered dealer (~11k): name, settlement, postal code, mailing
address and — for corporations only — a corporate registration number (ח"פ).
There are no dates, so the page is a snapshot: who the dealers are (sole
traders vs corporations, by legal form), where they are (settlements, postal
zones, concentration) and how they present themselves (address type, the
words corporations put in their names).

Privacy: the registration number is used only for its two-digit prefix (legal
form) and never reaches the page. Addresses are classified (P.O. box, street,
apartment, settlement only) and never shown. Dealers may be named under the
naming policy, but this page names none individually — only settlements,
postal zones and words in corporate names.

Legal form by prefix follows the Israeli registrar numbering: 50 public
bodies, 51 companies, 52 public companies, 54/55 partnerships, 57
co-operative societies, 58 non-profits; any other prefix flows through as
"תאגיד אחר". No number → sole trader.
"""
import re

import pandas as pd

SOLE = "סוחר יחיד"
FORMS = {"50": "גוף ציבורי", "51": "חברה בע״מ", "52": "חברה ציבורית",
         "54": "שותפות", "55": "שותפות", "57": "אגודה שיתופית", "58": "עמותה"}
OTHER_FORM = "תאגיד אחר"
FORM_ORDER = [SOLE, "חברה בע״מ", "חברה ציבורית", "גוף ציבורי", "שותפות",
              "אגודה שיתופית", "עמותה", OTHER_FORM]
CORP = "תאגיד"
SOLE_COLOR, CORP_COLOR = "#0068f5", "#0b3668"

TOP_CITIES = 15
SHARE_MIN = 50      # dealers needed for a settlement to enter the share ranking
SHARE_EACH = 8      # highest / lowest shown
BIG_CITY = 200
SMALL_CITY = 20
TOP_WORDS = 15
CURVE_MARKS = [1, 5, 10, 20, 50, 100]
BUCKETS = [(1, 1), (2, 4), (5, 9), (10, 24), (25, 49), (50, 99), (100, 199), (200, None)]

ADDR_PO = "תא דואר"
ADDR_APT = "רחוב, מספר ודירה"
ADDR_STREET = "רחוב ומספר"
ADDR_TOWN = "שם היישוב בלבד"
ADDR_NONUM = "ללא מספר בית"
ADDR_NONE = "ללא כתובת"
ADDR_ORDER = [ADDR_STREET, ADDR_PO, ADDR_APT, ADDR_TOWN, ADDR_NONUM, ADDR_NONE]
ADDR_COLOR = {ADDR_STREET: "#0068f5", ADDR_PO: "#0b3668", ADDR_APT: "#ffc107",
              ADDR_TOWN: "#198754", ADDR_NONUM: "#6c757d", ADDR_NONE: "#c3cfe7"}

PO_RE = re.compile(r"(?:^|[\s,])(?:ת\s*['\"״׳]{1,2}\s*ד|ת\.\s*ד|ת\s+ד|תיבת\s+דואר|ת\.ד)"
                   r"(?=$|[\s\d.,])")
APT_RE = re.compile(r"(?:^|\s)דירה(?:\s|$)")
LTD_RE = re.compile(r"בע\s*['\"״׳]*\s*מ(?![א-ת])|בעמ(?![א-ת])")
WORD_RE = re.compile(r"[א-ת]+(?:['\"״׳][א-ת]+)*")
STOP = {"חברה", "חב", "את", "של", "ושות", "ושותפיו", "שותפות", "מוגבלת", "כללית",
        "אי", "איי", "אס", "אר", "אל", "בי", "סי", "די", "טי", "וי", "אם", "אן",
        "אף", "איץ'", "ג'י", "קיי", "ע", "ר", "מ", "בע"}
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def p_disp(v, digits=1):
    return f"{v:.{digits}f}%"


def _city(s):
    s = re.sub(r"\s+", " ", s.replace("*", "").strip())
    return re.sub(r"\s*-\s*", "-", s)


def _addr_type(addr, city):
    a = re.sub(r"\s+", " ", addr.strip())
    if not a:
        return ADDR_NONE
    if PO_RE.search(a):
        return ADDR_PO
    if APT_RE.search(a):
        return ADDR_APT
    if re.search(r"\d", a):
        return ADDR_STREET
    if _city(a) == city:
        return ADDR_TOWN
    return ADDR_NONUM


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _prepare(df):
    hp = df["het_pei"].str.strip()
    form = hp.str[:2].map(lambda p: FORMS.get(p, OTHER_FORM))
    form = form.where(hp != "", SOLE)
    city = df["yishuv"].map(_city)
    mikud = df["mikud"].str.strip()
    zone = mikud.where(mikud.str.fullmatch(r"[1-9]\d{4}(\d{2})?"), "").str[:1]
    out = pd.DataFrame({
        "name": df["shem"].map(lambda s: re.sub(r"\s+", " ", s.strip())),
        "city": city,
        "zone": zone,
        "form": form,
        "corp": hp != "",
    })
    out["addr"] = [_addr_type(a, c) for a, c in zip(df["ktovet"], city)]
    return out


def _company_words(names):
    """Words used in corporate names: number of names containing each word."""
    per_name = []
    for s in names:
        s = LTD_RE.sub(" ", s)
        per_name.append([w.replace("״", '"') for w in WORD_RE.findall(s)])
    vocab = pd.Series([w for ws in per_name for w in ws]).value_counts()

    def fold(w):
        # "וסחר"/"לרכב" → "סחר"/"רכב" when the bare word is itself in use.
        if len(w) > 3 and w[0] in "ולהב" and vocab.get(w[1:], 0) >= 3:
            return w[1:]
        return w.replace("שרות", "שירות")

    counts = {}
    for ws in per_name:
        for w in {fold(w) for w in ws if len(w) > 1}:
            if w not in STOP:
                counts[w] = counts.get(w, 0) + 1
    s = pd.Series(counts, dtype="int64")
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _join(items):
    items = list(items)
    if len(items) == 1:
        return items[0]
    last = items[-1]
    return ", ".join(items[:-1]) + (" ו-" if last[:1].isdigit() else " ו") + last


# ---------------------------------------------------------------- insights

def insight_mix(total, corp_n, forms):
    if total == 0 or corp_n == 0 or corp_n == total:
        return None
    co = int(forms.get("חברה בע״מ", 0))
    s = (f"{pct((total - corp_n) / total * 100)} מהסוחרים הרשומים ({n(total - corp_n)}) הם "
         f"סוחרים יחידים ללא מספר תאגיד; {n(corp_n)} ({pct(corp_n / total * 100)}) הם תאגידים")
    if co / corp_n >= 0.5:
        s += f", רובם המכריע חברות בע״מ ({n(co)})"
    return s + "."


def insight_leader(cities, known):
    if known == 0 or len(cities) < 10:
        return None
    top, v = cities.index[0], int(cities.iloc[0])
    if v / known < 0.03:
        return None
    t10 = int(cities.head(10).sum())
    nxt = _join(cities.index[1:3])
    return (f"{top} מובילה עם {n(v)} סוחרי רכב ({pct(v / known * 100)}), ואחריה {nxt}; "
            f"עשרת היישובים המובילים מרכזים {pct(t10 / known * 100)} מהסוחרים, "
            f"מתוך {n(len(cities))} יישובים שיש בהם סוחר רשום.")


def insight_bigsmall(df, city_n):
    size = df["city"].map(city_n)
    big = df[size >= BIG_CITY]
    small = df[size < SMALL_CITY]
    if len(big) < 500 or len(small) < 500:
        return None
    b, s = big["corp"].mean() * 100, small["corp"].mean() * 100
    if abs(b - s) < 5:
        return None
    nb = int((city_n >= BIG_CITY).sum())
    return (f"ביישובים הגדולים ({n(nb)} יישובים עם {n(BIG_CITY)} סוחרים ומעלה) {pct(b, 0)} "
            f"מהסוחרים הם תאגידים, לעומת {pct(s, 0)} ביישובים שבהם פחות מ-{n(SMALL_CITY)} "
            f"סוחרים.")


def insight_share_range(share):
    if len(share) < 10:
        return None
    hi, lo = share.index[0], share.index[-1]
    vh, vl = share.iloc[0] * 100, share.iloc[-1] * 100
    if vh - vl < 20:
        return None
    return (f"שיעור התאגידים משתנה מאוד בין היישובים: ב{hi} {pct(vh, 0)} מהסוחרים הם "
            f"תאגידים, ואילו ב{lo} רק {pct(vl, 0)} — הנתון מתייחס ליישובים עם "
            f"{n(SHARE_MIN)} סוחרים לפחות.")


def insight_tail(buckets, n_cities):
    single = buckets[0][1] if buckets and buckets[0][0] == (1, 1) else 0
    if single < 10:
        return None
    small = sum(c for (lo, hi), c, _ in buckets if hi is not None and hi < 10)
    return (f"{n(single)} יישובים רשומים עם סוחר רכב אחד בלבד, ו-{n(small)} מתוך "
            f"{n(n_cities)} היישובים ({pct(small / n_cities * 100, 0)}) — עם פחות מעשרה.")


def insight_address(df):
    tot = len(df)
    if tot == 0:
        return None
    po = df["addr"] == ADDR_PO
    if po.mean() < 0.1:
        return None
    c, i = df[df["corp"]], df[~df["corp"]]
    s = f"{pct(po.mean() * 100)} מהסוחרים רשומים עם תא דואר במקום כתובת רחוב"
    if len(c) and len(i):
        s += (f" — {pct((c['addr'] == ADDR_PO).mean() * 100, 0)} מהתאגידים ו-"
              f"{pct((i['addr'] == ADDR_PO).mean() * 100, 0)} מהסוחרים היחידים")
    apt = (i["addr"] == ADDR_APT).mean() if len(i) else 0
    if apt >= 0.05:
        s += (f"; אצל {pct(apt * 100, 0)} מהסוחרים היחידים הכתובת כוללת מספר דירה, "
              f"כלומר כתובת מגורים")
    return s + "."


def insight_words(words, corp_n):
    if corp_n < 100 or len(words) < 3:
        return None
    (w1, v1), (w2, v2), (w3, v3) = list(words.items())[:3]
    if v1 / corp_n < 0.05:
        return None
    return (f"המילה הנפוצה ביותר בשמות התאגידים היא \"{w1}\" — ב-{n(v1)} שמות "
            f"({pct(v1 / corp_n * 100)}), ואחריה \"{w2}\" ({n(v2)}) ו-\"{w3}\" ({n(v3)}).")


def insight_public(forms):
    pub = int(forms.get("גוף ציבורי", 0))
    pubco = int(forms.get("חברה ציבורית", 0))
    coop = int(forms.get("אגודה שיתופית", 0))
    if pub + pubco + coop < 5:
        return None
    parts = []
    if pubco:
        parts.append(f"{n(pubco)} חברות ציבוריות")
    if pub:
        parts.append(f"{n(pub)} גופים ציבוריים")
    if coop:
        parts.append(f"{n(coop)} אגודות שיתופיות")
    return (f"לצד סוחרים יחידים וחברות פרטיות רשומים כסוחרי רכב גם {_join(parts)}.")


def insight_quality(df, raw_dups):
    no_zone = int((df["zone"] == "").sum())
    if no_zone == 0 and raw_dups == 0:
        return None
    parts = []
    if no_zone:
        parts.append(f"ל-{n(no_zone)} רשומות ({pct(no_zone / len(df) * 100)}) אין מיקוד תקין, "
                     f"והן אינן נכללות בפילוח לפי אזורי מיקוד")
    if raw_dups:
        parts.append(f"{n(raw_dups)} רשומות הן כפילות מלאה של רשומה אחרת במרשם")
    return "; ".join(parts) + "."


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["dealers"]
    df = _prepare(raw)
    total = len(df)
    raw_dups = int(raw.duplicated().sum())

    present = set(df["form"])
    forms_order = [f for f in FORM_ORDER if f in present] + sorted(present - set(FORM_ORDER))
    forms = df["form"].value_counts().reindex(forms_order).fillna(0).astype(int)
    corp_n = int(df["corp"].sum())
    sole_n = total - corp_n

    known = df[df["city"] != ""]
    cities = _sorted_counts(known["city"])
    n_cities = int(cities.size)
    unknown_city = total - len(known)
    corp_by_city = known.groupby("city")["corp"].sum()

    # Top settlements, sole vs corporate.
    top_c = list(cities.head(TOP_CITIES).index)
    top_rows = [{"name": c, "total": int(cities[c]), "corp": int(corp_by_city[c]),
                 "sole": int(cities[c] - corp_by_city[c])} for c in top_c]

    # Corporate share by settlement (settlements with >= SHARE_MIN dealers).
    elig = cities[cities >= SHARE_MIN]
    share = (corp_by_city.reindex(elig.index) / elig)
    share = (pd.DataFrame({"s": share, "c": share.index})
             .sort_values(["s", "c"], ascending=[False, True])["s"])
    if len(share) >= 2 * SHARE_EACH:
        pick = pd.concat([share.head(SHARE_EACH), share.tail(SHARE_EACH)])
    else:
        pick = share
    overall_share = corp_n / total * 100 if total else 0
    share_rows = [{"name": c, "share": round(float(v * 100), 1), "total": int(elig[c]),
                   "group": "high" if v * 100 >= overall_share else "low"}
                  for c, v in pick.items()]

    # Concentration curve.
    cum = cities.cumsum() / max(len(known), 1) * 100
    curve = [round(float(v), 1) for v in cum.values]
    marks = [m for m in CURVE_MARKS if m <= n_cities]
    half_k = int((cum >= 50).values.argmax()) + 1 if n_cities else 0

    # Settlement size buckets.
    buckets = []
    for lo, hi in BUCKETS:
        m = cities >= lo
        if hi is not None:
            m &= cities <= hi
        buckets.append(((lo, hi), int(m.sum()), int(cities[m].sum())))
    bucket_names = [(f"{lo}" if lo == hi else (f"{n(lo)} ומעלה" if hi is None else f"{lo} עד {hi}"))
                    for (lo, hi), _, _ in buckets]

    # Postal zones (first digit of the postal code).
    zoned = df[df["zone"] != ""]
    zones = sorted(zoned["zone"].unique())
    zone_rows = []
    for z in zones:
        sub = zoned[zoned["zone"] == z]
        lead = _sorted_counts(sub.loc[sub["city"] != "", "city"]).head(2)
        zone_rows.append({"zone": z, "label": f"{z} · " + ", ".join(lead.index),
                          "lead": list(lead.index), "total": len(sub),
                          "corp": int(sub["corp"].sum()), "sole": int((~sub["corp"]).sum())})

    # Address type by sole / corporate.
    addr_present = [a for a in ADDR_ORDER if a in set(df["addr"])]
    addr_ct = df.groupby(["corp", "addr"]).size()
    groups = [(False, SOLE, sole_n), (True, CORP, corp_n)]
    addr_series = [{"name": a, "color": ADDR_COLOR[a],
                    "data": [round(float(addr_ct.get((g, a), 0) / d * 100), 1) if d else 0
                             for g, _, d in groups]} for a in addr_present]

    words = _company_words(df.loc[df["corp"], "name"])
    top_words = words.head(TOP_WORDS)

    charts = {
        "forms": {"names": forms_order, "values": [int(forms[f]) for f in forms_order]},
        "cities": {"names": top_c,
                   "sole": [r["sole"] for r in top_rows], "corp": [r["corp"] for r in top_rows],
                   "sole_name": SOLE, "corp_name": CORP,
                   "colors": [SOLE_COLOR, CORP_COLOR]},
        "share": {"names": [r["name"] for r in share_rows],
                  "values": [r["share"] for r in share_rows],
                  "groups": [r["group"] for r in share_rows],
                  "overall": round(overall_share, 1)},
        "curve": {"x": list(range(1, n_cities + 1)), "y": curve, "names": list(cities.index)},
        "buckets": {"names": bucket_names, "cities": [b[1] for b in buckets],
                    "dealers": [b[2] for b in buckets]},
        "zones": {"names": [r["label"] for r in zone_rows],
                  "sole": [r["sole"] for r in zone_rows], "corp": [r["corp"] for r in zone_rows],
                  "sole_name": SOLE, "corp_name": CORP, "colors": [SOLE_COLOR, CORP_COLOR]},
        "address": {"groups": [g for _, g, _ in groups], "series": addr_series},
        "words": {"names": list(top_words.index), "values": [int(v) for v in top_words.values]},
    }

    rules = [
        ("mix", insight_mix(total, corp_n, forms)),
        ("leader", insight_leader(cities, len(known))),
        ("bigsmall", insight_bigsmall(known, cities)),
        ("share", insight_share_range(share)),
        ("tail", insight_tail(buckets, n_cities)),
        ("address", insight_address(df)),
        ("words", insight_words(words, corp_n)),
        ("public", insight_public(forms)),
        ("quality", insight_quality(df, raw_dups)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    t10 = float(cum.iloc[min(10, n_cities) - 1]) if n_cities else 0.0
    corp_pct = corp_n / total * 100 if total else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "corp": {"value": round(corp_pct, 1), "display": p_disp(corp_pct), "tone": "info"},
        "cities": {"value": n_cities, "display": n(n_cities), "tone": "brand"},
        "top10": {"value": round(t10, 1), "display": p_disp(t10),
                  "tone": "warn" if t10 >= 50 else "info"},
    }

    lead = cities.index[0] if n_cities else ""
    labels = {
        "lede": (f"מרשם סוחרי הרכב המנועי שבפיקוח משרד התחבורה: {n(total)} סוחרים רשומים "
                 f"ב-{n(n_cities)} יישובים — {n(sole_n)} סוחרים יחידים ו-{n(corp_n)} תאגידים. "
                 f"למרשם אין תאריכים, ולכן הדף מציג תמונת מצב: מי הסוחרים, היכן הם רשומים "
                 f"ואיך הם מציגים את עצמם."),
        "corp_kpi": f"תאגידים ({n(corp_n)} מתוך {n(total)})",
        "top10_kpi": "מהסוחרים רשומים בעשרת היישובים המובילים",
        "forms_note": ("הצורה המשפטית נגזרת מקידומת מספר התאגיד; לסוחר יחיד אין מספר תאגיד "
                       "במרשם. המספרים עצמם אינם מוצגים."),
        "forms_aria": f"תרשים טבעת: סוחרי רכב לפי צורה משפטית — {n(sole_n)} סוחרים יחידים ו-{n(corp_n)} תאגידים.",
        "forms_caption": "סוחרי רכב לפי צורה משפטית.",
        "cities_note": (f"{TOP_CITIES} היישובים עם מספר סוחרי הרכב הרשומים הגדול ביותר, בחלוקה "
                        f"לסוחרים יחידים ולתאגידים. {lead} בראש עם {n(cities.iloc[0]) if n_cities else 0} סוחרים."
                        + (f" {n(unknown_city)} רשומות ללא יישוב אינן נכללות." if unknown_city else "")),
        "cities_aria": (f"תרשים עמודות אופקי מוערם: {TOP_CITIES} היישובים המובילים במספר סוחרי רכב — "
                        f"{lead} בראש."),
        "cities_caption": f"סוחרי רכב לפי יישוב ({TOP_CITIES} המובילים).",
        "share_note": (f"שיעור התאגידים מכלל הסוחרים ביישוב — {SHARE_EACH} היישובים עם השיעור הגבוה "
                       f"ביותר ו-{SHARE_EACH} עם הנמוך ביותר, מבין {n(len(share))} יישובים שיש בהם "
                       f"{n(SHARE_MIN)} סוחרים לפחות. הקו המקווקו: הממוצע הארצי, {p_disp(overall_share)}."),
        "share_aria": (f"תרשים עמודות אופקי: שיעור התאגידים בקרב סוחרי הרכב ביישובים, "
                       f"מ-{share_rows[0]['name'] if share_rows else ''} ועד "
                       f"{share_rows[-1]['name'] if share_rows else ''}."),
        "share_caption": "שיעור התאגידים מכלל סוחרי הרכב ביישוב.",
        "curve_note": (f"היישובים מדורגים מהגדול לקטן, והקו מראה איזה חלק מכלל הסוחרים מרוכז "
                       f"ביישובים המובילים. מחצית מהסוחרים רשומים ב-{n(half_k)} יישובים בלבד."),
        "curve_aria": (f"גרף קו מצטבר: שיעור הסוחרים לפי מספר היישובים המובילים; עשרת הראשונים "
                       f"מרכזים {p_disp(t10)}."),
        "curve_caption": "שיעור מצטבר של סוחרים לפי מספר היישובים המובילים.",
        "buckets_note": "כמה יישובים יש בכל קבוצת גודל, לפי מספר סוחרי הרכב הרשומים בהם.",
        "buckets_aria": (f"תרשים עמודות: מספר היישובים לפי מספר סוחרי הרכב בהם — "
                         f"{n(buckets[0][1])} יישובים עם סוחר אחד."),
        "buckets_caption": "יישובים וסוחרים לפי מספר הסוחרים ביישוב.",
        "zones_note": ("הספרה הראשונה של המיקוד מחלקת את הארץ לאזורי דואר. לצד כל אזור מוצגים "
                       "שני היישובים עם מספר הסוחרים הגדול ביותר בו."
                       + (f" {n(total - len(zoned))} רשומות ללא מיקוד תקין אינן נכללות."
                          if total - len(zoned) else "")),
        "zones_aria": "תרשים עמודות אופקי מוערם: סוחרי רכב לפי אזור מיקוד, סוחרים יחידים ותאגידים.",
        "zones_caption": "סוחרי רכב לפי אזור מיקוד (הספרה הראשונה של המיקוד).",
        "address_note": ("סוג הכתובת שבה רשום הסוחר, באחוזים, בנפרד לסוחרים יחידים ולתאגידים. "
                         "כתובת עם מספר דירה היא בדרך כלל כתובת מגורים. הכתובות עצמן אינן מוצגות."),
        "address_aria": "תרשים עמודות מוערמות באחוזים: סוג הכתובת של סוחרים יחידים ושל תאגידים.",
        "address_caption": "התפלגות סוג הכתובת (באחוזים), סוחרים יחידים ותאגידים.",
        "words_note": (f"{TOP_WORDS} המילים הנפוצות בשמות {n(corp_n)} התאגידים — כמה שמות כוללים "
                       f"כל מילה. צורות כמו \"וסחר\" ו\"הרכב\" אוחדו עם המילה הבסיסית, "
                       f"ו\"בע״מ\" הושמט."),
        "words_aria": (f"תרשים עמודות אופקי: המילים הנפוצות בשמות תאגידי סוחרי הרכב — "
                       f"\"{top_words.index[0] if len(top_words) else ''}\" בראש."),
        "words_caption": "מספר שמות תאגידים הכוללים כל מילה.",
    }

    tables = {
        "forms": [{"name": f, "count": n(forms[f]), "share": p_disp(forms[f] / total * 100)}
                  for f in forms_order],
        "cities": [{"name": r["name"], "total": n(r["total"]), "sole": n(r["sole"]),
                    "corp": n(r["corp"]), "share": p_disp(r["corp"] / r["total"] * 100)}
                   for r in top_rows],
        "share": [{"name": r["name"], "total": n(r["total"]), "share": p_disp(r["share"])}
                  for r in share_rows],
        "curve": [{"k": n(m), "share": p_disp(curve[m - 1])} for m in marks],
        "buckets": [{"name": nm, "cities": n(c), "dealers": n(d),
                     "share": p_disp(d / max(len(known), 1) * 100)}
                    for nm, (_, c, d) in zip(bucket_names, buckets)],
        "zones": [{"zone": r["zone"], "lead": ", ".join(r["lead"]), "total": n(r["total"]),
                   "sole": n(r["sole"]), "corp": n(r["corp"])} for r in zone_rows],
        "address": [{"name": s["name"], "vals": [p_disp(v) for v in s["data"]]}
                    for s in addr_series],
        "address_cols": [g for _, g, _ in groups],
        "words": [{"name": k, "count": n(v)} for k, v in top_words.items()],
    }

    return {
        "agent_data": {
            "summary_he": (f"מרשם סוחרי הרכב של משרד התחבורה: {n(total)} סוחרים רשומים "
                           f"ב-{n(n_cities)} יישובים, מהם {n(corp_n)} תאגידים "
                           f"({p_disp(corp_pct)}); {lead} מובילה במספר הסוחרים."),
            "dataset_kind": "registry",
            "related_ids": ["35c791ca-8db2-4657-8c6f-eb092147a6bb",
                            "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                            "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                            "0219b34f-43c7-435b-bdfe-e65e944cde50",
                            "11369651-1c70-4d8f-8090-ee49354a7c52"],
            "suggested_tags": ["סוחרי רכב", "רכב", "משרד התחבורה", "רישוי עסקים",
                               "תאגידים", "תחבורה"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
