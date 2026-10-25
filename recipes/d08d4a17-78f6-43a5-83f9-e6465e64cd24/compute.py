"""מאגר הנוטריונים — the Ministry of Justice register of active notaries.

One row per active notary (~7.7k): licence file number, full name,
settlement and the languages besides Hebrew the notary serves in (English
language names, ';'-separated; empty = none listed besides Hebrew).
There is no date column, so the page is a cross-section: geography,
language supply and their combination.

Licence file numbers are individual identifiers and never reach the page.
Names are used only in aggregate (most common surnames / first names).
Settlement spellings that differ only by spacing, hyphens, quotes or a
doubled ו/י are folded on a normalized key and shown under their most
common spelling. Language names are translated to Hebrew through a fixed
table; a language missing from the table is counted under "שפות אחרות" so
new codes flow through without putting Latin text on the page.
"""
import re
from itertools import combinations

import pandas as pd

LANG_HE = {
    "English": "אנגלית", "Arabic": "ערבית", "Russian": "רוסית", "French": "צרפתית",
    "Ukrainian": "אוקראינית", "Spanish": "ספרדית", "Romanian": "רומנית",
    "German": "גרמנית", "Portuguese": "פורטוגזית", "Italian": "איטלקית",
    "Belarusian": "בלארוסית", "Yiddish": "יידיש", "Bulgarian": "בולגרית",
    "Polish": "פולנית", "Dutch": "הולנדית", "Georgian": "גאורגית", "Herero": "הררו",
    "Czech": "צ׳כית", "Modern Greek (1453-)": "יוונית", "Greek": "יוונית",
    "Hungarian": "הונגרית", "Lithuanian": "ליטאית", "Slovak": "סלובקית",
    "Azerbaijani": "אזרית", "Afrikaans": "אפריקאנס", "Persian": "פרסית",
    "Turkish": "טורקית", "Chinese": "סינית", "Serbian": "סרבית", "Amharic": "אמהרית",
    "Uzbek": "אוזבקית", "Kazakh": "קזחית", "Latvian": "לטבית", "Tajik": "טג׳יקית",
    "Swedish": "שוודית", "Slovenian": "סלובנית", "Kirghiz": "קירגיזית",
    "Latin": "לטינית", "Armenian": "ארמנית", "Turkmen": "טורקמנית",
    "Icelandic": "איסלנדית", "Serbo-Croatian": "סרבו־קרואטית",
    "Luxembourgish": "לוקסמבורגית", "Danish": "דנית", "Norwegian": "נורווגית",
    "Bosnian": "בוסנית", "Croatian": "קרואטית", "Finnish": "פינית",
    "Esperanto": "אספרנטו", "Chechen": "צ׳צ׳נית", "Faroese": "פארואזית",
    "Romansh": "רומאנש", "Lingala": "לינגלה", "Macedonian": "מקדונית",
    "Estonian": "אסטונית", "Maltese": "מלטזית", "Basque": "בסקית",
    "Albanian": "אלבנית", "Welsh": "וולשית", "Irish": "אירית",
    "Scottish Gaelic": "גאלית סקוטית", "Hindi": "הינדי", "Japanese": "יפנית",
    "Korean": "קוריאנית", "Thai": "תאית", "Vietnamese": "וייטנאמית",
    "Tigrinya": "תגרינית", "Hebrew": "עברית", "Ladino": "לדינו",
    "Catalan": "קטלאנית", "Bengali": "בנגלית", "Urdu": "אורדו",
    "Indonesian": "אינדונזית", "Filipino": "פיליפינית", "Tagalog": "טגלוג",
    "Moldavian": "מולדבית", "Kurdish": "כורדית", "Swahili": "סווהילי",
    "Avaric": "אווארית", "Bashkir": "בשקירית", "Church Slavic": "סלאבית כנסייתית",
    "Chuvash": "צ׳ובשית", "Tatar": "טטרית",
}
OTHER_LANG = "שפות אחרות"
TOP_CITIES = 15
TOP_LANGS = 15
HEAT_CITIES = 12
HEAT_LANGS = 8
TOP_PAIRS = 10
TOP_NAMES = 15
RARE_MAX = 3
CITY_MIN = 30
NLANG_MAX = 5
SIZE_BUCKETS = [(1, 1), (2, 5), (6, 10), (11, 50), (51, 200), (201, None)]
MILESTONES = [1, 2, 5, 10, 20, 50, 100]
PARTICLES = {"בן", "בר", "אבו", "אל", "דה", "אבן", "בית", "עבד", "ואן", "פון", "די"}
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def _city_display(s):
    return re.sub(r"\s+", " ", s.strip())


def _city_key(s):
    k = re.sub(r"[\s\-–\"'״׳()]", "", s)
    return k.replace("וו", "ו").replace("יי", "י")


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _surname(tokens):
    if not tokens:
        return ""
    if len(tokens) >= 3 and tokens[-2] in PARTICLES:
        return " ".join(tokens[-2:])
    return tokens[-1] if len(tokens) >= 2 else ""


def _langs(s):
    out = []
    for t in s.split(";"):
        t = t.strip()
        if not t:
            continue
        he = LANG_HE.get(t, OTHER_LANG)
        if he not in out:
            out.append(he)
    return out


def _prepare(df):
    city = df["ישוב"].map(_city_display)
    known = city != ""
    key = city.map(_city_key)
    variants = (pd.DataFrame({"key": key[known], "city": city[known]})
                .groupby(["key", "city"]).size().reset_index(name="n")
                .sort_values(["key", "n", "city"], ascending=[True, False, True]))
    canon = variants.drop_duplicates("key").set_index("key")["city"]
    tokens = df["שם"].str.strip().str.split()
    out = pd.DataFrame({
        "city": key.map(canon).where(known, ""),
        "first": tokens.map(lambda t: t[0] if len(t) >= 2 else ""),
        "last": tokens.map(_surname),
        "langs": df["שפות"].map(_langs),
    })
    out["nl"] = out["langs"].map(len)
    return out


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " ו" + items[-1]


# ---------------------------------------------------------------- insights

def insight_concentration(cities, known_total):
    if known_total == 0 or len(cities) < 10:
        return None
    top2 = cities.head(2)
    s2 = top2.sum() / known_total
    s5 = cities.head(5).sum() / known_total
    if s5 < 0.2:
        return None
    return (f"{top2.index[0]} ({n(top2.iloc[0])}) ו{top2.index[1]} ({n(top2.iloc[1])}) לבדן "
            f"מרכזות {pct(s2 * 100)} מהנוטריונים שישובם ידוע, וחמשת הישובים המובילים — "
            f"{pct(s5 * 100)}.")


def insight_tail(cities, known_total):
    if len(cities) < 20:
        return None
    small = cities[cities <= 10]
    if len(small) / len(cities) < 0.5:
        return None
    single = int((cities == 1).sum())
    return (f"הנוטריונים פרוסים ב-{n(len(cities))} ישובים, אך ב-{n(len(small))} מהם "
            f"({pct(len(small) / len(cities) * 100, 0)}) יש עד עשרה נוטריונים בלבד — יחד "
            f"{n(small.sum())} נוטריונים ({pct(small.sum() / known_total * 100)}); "
            f"ב-{n(single)} ישובים יש נוטריון יחיד.")


def insight_foreign(df, lang_counts):
    total = len(df)
    with_l = int((df["nl"] > 0).sum())
    if total == 0 or with_l == 0 or lang_counts.empty:
        return None
    lead, lv = lang_counts.index[0], int(lang_counts.iloc[0])
    s = (f"{pct(with_l / total * 100)} מהנוטריונים ({n(with_l)}) מציינים לפחות שפה אחת נוספת "
         f"שבה הם נותנים שירות; {lead} מובילה בפער ({n(lv)} נוטריונים, "
         f"{pct(lv / with_l * 100, 0)} מהמציינים שפה)")
    nxt = [(k, int(v)) for k, v in lang_counts.iloc[1:3].items()]
    if len(nxt) == 2:
        s += f", ואחריה {nxt[0][0]} ({n(nxt[0][1])}) ו{nxt[1][0]} ({n(nxt[1][1])})"
    return s + "."


def insight_hotspot(df, lang_counts, city_sizes):
    """Second language (after the leader): the city where it is most over-represented."""
    if len(lang_counts) < 2:
        return None
    lang = lang_counts.index[1]
    has = df["langs"].map(lambda l: lang in l)
    nat = has.mean()
    big = city_sizes[city_sizes >= CITY_MIN].index
    if nat == 0 or len(big) < 3:
        return None
    sub = df[df["city"].isin(big)]
    share = has[sub.index].groupby(sub["city"]).mean()
    share = share.sort_index().sort_values(ascending=False, kind="stable")
    city, cs = share.index[0], float(share.iloc[0])
    if cs < 2 * nat:
        return None
    return (f"{lang} מוצעת בידי {pct(nat * 100)} מהנוטריונים בכלל הארץ, אך ב{city} — "
            f"{pct(cs * 100, 0)} מ-{n(city_sizes[city])} הנוטריונים בישוב (בין הישובים עם "
            f"{CITY_MIN} נוטריונים ומעלה).")


def insight_pairs(pairs, lead):
    if pairs.empty:
        return None
    (a, b), v = pairs.index[0], int(pairs.iloc[0])
    no_lead = pairs[[lead not in p for p in pairs.index]]
    s = f"צמד השפות הנפוץ ביותר הוא {a} ו{b} ({n(v)} נוטריונים)"
    if not no_lead.empty and lead in (a, b):
        (c, d), w = no_lead.index[0], int(no_lead.iloc[0])
        if w >= 10:
            s += f"; ללא {lead}, הצמד הנפוץ הוא {c} ו{d} ({n(w)})"
    return s + "."


def insight_multi(df, lang_counts):
    m3 = int((df["nl"] >= 3).sum())
    rare = lang_counts[(lang_counts <= RARE_MAX) & (lang_counts.index != OTHER_LANG)]
    if m3 < 10 and rare.empty:
        return None
    s = f"{n(m3)} נוטריונים מציינים שלוש שפות נוספות ומעלה"
    if len(rare) >= 3:
        s += (f"; {n(len(rare))} מתוך {n(int((lang_counts.index != OTHER_LANG).sum()))} השפות במאגר מוצעות בידי "
              f"{RARE_MAX} נוטריונים לכל היותר")
    return s + "."


def insight_surname(surnames, total):
    if len(surnames) < 2:
        return None
    (a, va), (b, vb) = list(surnames.items())[:2]
    if va < 1.3 * vb:
        return None
    return (f"שם המשפחה הנפוץ ביותר בקרב הנוטריונים הוא {a} ({n(va)}, {pct(va / total * 100)}), "
            f"ואחריו {b} ({n(vb)}).")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["notaries"])
    total = len(df)

    known = df[df["city"] != ""]
    known_total = len(known)
    unknown_city = total - known_total
    cities = _sorted_counts(known["city"])
    top_c = list(cities.head(TOP_CITIES).index)
    other_c = int(cities.iloc[TOP_CITIES:].sum())

    # Concentration curve: cumulative share by city rank.
    cum = (cities.cumsum() / known_total * 100) if known_total else cities
    curve = [round(float(v), 2) for v in cum.values]
    miles = [m for m in MILESTONES if m <= len(cities)]
    if len(cities) not in miles:
        miles.append(len(cities))

    # City-size buckets.
    size_rows = []
    for lo, hi in SIZE_BUCKETS:
        m = cities >= lo
        if hi is not None:
            m &= cities <= hi
        lab = (f"{lo} ומעלה" if hi is None else (str(lo) if lo == hi else f"{lo} עד {hi}"))
        size_rows.append({"label": lab, "cities": int(m.sum()), "notaries": int(cities[m].sum())})
    n_city = max(len(cities), 1)

    # Languages.
    exploded = df[["city", "langs"]].explode("langs").dropna(subset=["langs"])
    lang_counts = _sorted_counts(exploded["langs"])
    top_l = list(lang_counts.head(TOP_LANGS).index)
    lang_city = exploded[exploded["city"] != ""].groupby(["langs", "city"]).size()
    lang_rows = []
    for lg in top_l:
        lc = lang_city.loc[lg] if lg in lang_city.index.get_level_values(0) else pd.Series(dtype=int)
        lc = lc.sort_index().sort_values(ascending=False, kind="stable")
        lang_rows.append({"name": lg, "count": n(lang_counts[lg]),
                          "share": f"{lang_counts[lg] / total * 100:.1f}%",
                          "cities": n(len(lc)),
                          "lead": (f"{lc.index[0]} ({n(lc.iloc[0])})" if len(lc) else "—")})

    nl_vals = []
    for k in range(NLANG_MAX + 1):
        m = (df["nl"] >= k) if k == NLANG_MAX else (df["nl"] == k)
        nl_vals.append(int(m.sum()))
    nl_names = ["ללא שפה נוספת" if k == 0 else (f"{k} ומעלה" if k == NLANG_MAX else str(k))
                for k in range(NLANG_MAX + 1)]

    # Language pairs.
    pc = {}
    for l in df["langs"]:
        if len(l) >= 2:
            for p in combinations(sorted(l), 2):
                pc[p] = pc.get(p, 0) + 1
    pairs = pd.Series(pc, dtype=int)
    if not pairs.empty:
        pairs = pairs.sort_index().sort_values(ascending=False, kind="stable")
    top_pairs = pairs.head(TOP_PAIRS)
    pair_names = [f"{a} + {b}" for a, b in top_pairs.index]

    # Foreign-language share in the top cities.
    has_any = (df["nl"] > 0)
    nat_any = float(has_any.mean() * 100) if total else 0.0
    sub = df[df["city"].isin(top_c)]
    any_share = has_any[sub.index].groupby(sub["city"]).mean().reindex(top_c) * 100
    ls_order = any_share.sort_index().sort_values(ascending=False, kind="stable")

    # City × language heatmap (share of the city's notaries).
    hc = top_c[:HEAT_CITIES]
    hl = [l for l in top_l if l != OTHER_LANG][:HEAT_LANGS]
    cells, heat_rows = [], []
    for yi, c in enumerate(hc):
        size = int(cities[c])
        vals = []
        for xi, lg in enumerate(hl):
            cnt = int(lang_city.get((lg, c), 0))
            v = round(cnt / size * 100, 1) if size else 0.0
            cells.append([xi, yi, v, cnt])
            vals.append(f"{v:.1f}%")
        heat_rows.append({"name": c, "total": n(size), "vals": vals})

    # Names (aggregate only).
    surnames = _sorted_counts(df.loc[df["last"] != "", "last"])
    firsts = _sorted_counts(df.loc[df["first"] != "", "first"])

    city_sizes = cities
    lead_lang = lang_counts.index[0] if len(lang_counts) else ""
    rules = [
        ("concentration", insight_concentration(cities, known_total)),
        ("tail", insight_tail(cities, known_total)),
        ("foreign", insight_foreign(df, lang_counts)),
        ("hotspot", insight_hotspot(df, lang_counts, city_sizes)),
        ("pairs", insight_pairs(pairs, lead_lang)),
        ("multi", insight_multi(df, lang_counts)),
        ("surname", insight_surname(surnames, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    with_l = int(has_any.sum())
    n_langs = int(len([l for l in lang_counts.index if l != OTHER_LANG]))
    top_share = float(cities.iloc[0] / known_total * 100) if known_total else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "cities": {"value": int(len(cities)), "display": n(len(cities)), "tone": "brand"},
        "foreign": {"value": round(with_l / total * 100, 1) if total else 0,
                    "display": f"{with_l / total * 100:.1f}%" if total else "0%",
                    "tone": "info"},
        "langs": {"value": n_langs, "display": n(n_langs), "tone": "brand"},
    }

    s5 = cities.head(5).sum() / known_total * 100 if known_total else 0
    labels = {
        "lede": (f"רשימת הנוטריונים הפעילים של משרד המשפטים: {n(total)} נוטריונים "
                 f"ב-{n(len(cities))} ישובים, מהם {n(with_l)} ({nat_any:.1f}%) מציינים שפה נוספת "
                 f"שבה הם נותנים שירות — {n(n_langs)} שפות שונות בסך הכול. במאגר אין תאריכים, "
                 f"ולכן העמוד מתאר את תמונת המצב הנוכחית: היכן הנוטריונים ובאילו שפות."),
        "foreign_kpi": "מציינים לפחות שפה אחת נוספת",
        "cities_note": (f"{TOP_CITIES} הישובים עם מספר הנוטריונים הגדול ביותר; "
                        f"{n(other_c)} נוטריונים נוספים פזורים ב-{n(max(len(cities) - TOP_CITIES, 0))} "
                        f"ישובים אחרים. איות שמות ישובים שונה במקור אוחד (למשל פתח תקווה/פתח תקוה)"
                        + (f"; {n(unknown_city)} רשומות ללא ישוב אינן נכללות." if unknown_city else ".")),
        "cities_aria": (f"תרשים עמודות אופקי: {TOP_CITIES} הישובים עם הכי הרבה נוטריונים — "
                        f"{top_c[0]} בראש עם {n(cities.iloc[0])}."),
        "cities_caption": f"מספר נוטריונים לפי ישוב ({TOP_CITIES} המובילים).",
        "curve_note": (f"איזה חלק מהנוטריונים מרוכז בישובים הגדולים: הנקודה ה-k מראה את שיעור "
                       f"הנוטריונים ב-k הישובים המובילים. {top_c[0]} לבדה — {top_share:.1f}%, "
                       f"וחמשת הראשונים — {s5:.1f}%."),
        "curve_aria": (f"גרף שטח: שיעור מצטבר של נוטריונים לפי דירוג הישוב, מתוך "
                       f"{n(len(cities))} ישובים."),
        "curve_caption": "שיעור מצטבר של נוטריונים ב-k הישובים המובילים.",
        "sizes_note": ("הישובים מקובצים לפי מספר הנוטריונים בהם: שיעור הישובים בכל קבוצה, "
                       "לעומת שיעור הנוטריונים שהם מרכזים."),
        "sizes_aria": (f"תרשים עמודות: שיעור הישובים ושיעור הנוטריונים לפי גודל הישוב — "
                       f"{n(size_rows[-1]['cities'])} ישובים עם {SIZE_BUCKETS[-1][0]} נוטריונים "
                       f"ומעלה."),
        "sizes_caption": "ישובים ונוטריונים לפי מספר הנוטריונים בישוב.",
        "langs_note": (f"{TOP_LANGS} השפות הנוספות שבהן נותנים שירות הכי הרבה נוטריונים (נוטריון יכול "
                       f"לציין כמה שפות). עברית אינה מופיעה ברשימה."),
        "langs_aria": (f"תרשים עמודות אופקי: {TOP_LANGS} השפות הנפוצות — {lead_lang} בראש עם "
                       f"{n(lang_counts.iloc[0]) if len(lang_counts) else '0'} נוטריונים."),
        "langs_caption": "נוטריונים לפי שפה, מספר הישובים שבהם היא מוצעת והישוב המוביל.",
        "nl_note": "כמה שפות נוספות מציין כל נוטריון.",
        "nl_aria": (f"תרשים עמודות: נוטריונים לפי מספר השפות הנוספות — {n(nl_vals[0])} ללא שפה "
                    f"נוספת."),
        "nl_caption": "מספר נוטריונים לפי מספר השפות הנוספות שהם מציינים.",
        "share_note": (f"שיעור הנוטריונים שמציינים שפה נוספת כלשהי, ב-{TOP_CITIES} הישובים הגדולים. "
                       f"הקו המקווקו — הממוצע הארצי ({nat_any:.1f}%)."),
        "share_aria": (f"תרשים עמודות אופקי: שיעור הנוטריונים עם שפה נוספת לפי ישוב — "
                       f"{ls_order.index[0]} בראש עם {ls_order.iloc[0]:.0f}%."),
        "share_caption": "שיעור הנוטריונים עם שפה נוספת לפי ישוב.",
        "heat_note": (f"באילו שפות ניתן שירות בכל ישוב: שיעור הנוטריונים בישוב שמציינים כל אחת "
                      f"מ-{len(hl)} השפות הנפוצות, ב-{len(hc)} הישובים הגדולים."),
        "heat_aria": (f"מפת חום: שיעור הנוטריונים לפי ישוב ושפה, {len(hc)} ישובים ו-{len(hl)} "
                      f"שפות."),
        "heat_caption": "שיעור הנוטריונים בכל ישוב שמציינים כל שפה.",
        "pairs_note": (f"{TOP_PAIRS} צמדי השפות הנפוצים בקרב נוטריונים שמציינים שתי שפות נוספות "
                       f"ומעלה."),
        "pairs_aria": (f"תרשים עמודות אופקי: {TOP_PAIRS} צמדי השפות הנפוצים"
                       + (f" — {pair_names[0]} בראש." if pair_names else ".")),
        "pairs_caption": "מספר נוטריונים לפי צמד שפות.",
        "surnames_note": (f"{TOP_NAMES} שמות המשפחה הנפוצים (המילה האחרונה בשם המלא, כולל "
                          f"תחיליות כגון בן או אבו)."),
        "surnames_aria": (f"תרשים עמודות אופקי: {TOP_NAMES} שמות המשפחה הנפוצים — "
                          f"{surnames.index[0]} בראש."),
        "surnames_caption": "מספר נוטריונים לפי שם משפחה.",
        "firsts_note": f"{TOP_NAMES} השמות הפרטיים הנפוצים (המילה הראשונה בשם המלא).",
        "firsts_aria": (f"תרשים עמודות אופקי: {TOP_NAMES} השמות הפרטיים הנפוצים — "
                        f"{firsts.index[0]} בראש."),
        "firsts_caption": "מספר נוטריונים לפי שם פרטי.",
    }

    charts = {
        "cities": {"names": top_c, "values": [int(cities[c]) for c in top_c]},
        "curve": {"x": list(range(1, len(curve) + 1)), "y": curve},
        "sizes": {"names": [r["label"] for r in size_rows],
                  "cities": [round(r["cities"] / n_city * 100, 1) for r in size_rows],
                  "notaries": [round(r["notaries"] / max(known_total, 1) * 100, 1)
                               for r in size_rows]},
        "langs": {"names": top_l, "values": [int(lang_counts[l]) for l in top_l]},
        "nl": {"names": ["ללא" if k == 0 else nm for k, nm in enumerate(nl_names)],
               "values": nl_vals},
        "share": {"names": list(ls_order.index),
                  "values": [round(float(v), 1) for v in ls_order.values],
                  "avg": round(nat_any, 1)},
        "heat": {"x": hl, "y": hc, "cells": cells,
                 "max": max([c[2] for c in cells] or [1])},
        "pairs": {"names": pair_names, "values": [int(v) for v in top_pairs.values]},
        "surnames": {"names": list(surnames.head(TOP_NAMES).index),
                     "values": [int(v) for v in surnames.head(TOP_NAMES).values]},
        "firsts": {"names": list(firsts.head(TOP_NAMES).index),
                   "values": [int(v) for v in firsts.head(TOP_NAMES).values]},
    }
    tables = {
        "cities": [{"name": c, "count": n(cities[c]),
                    "share": f"{cities[c] / known_total * 100:.1f}%"} for c in top_c],
        "curve": [{"k": n(m), "share": f"{curve[m - 1]:.1f}%"} for m in miles],
        "sizes": [{"label": r["label"], "cities": n(r["cities"]), "notaries": n(r["notaries"])}
                  for r in size_rows],
        "langs": lang_rows,
        "nl": [{"name": a, "count": n(b), "share": f"{b / total * 100:.1f}%"}
               for a, b in zip(nl_names, nl_vals)],
        "share": [{"name": c, "share": f"{v:.1f}%"} for c, v in ls_order.items()],
        "heat_cols": hl,
        "heat": heat_rows,
        "pairs": [{"name": a, "count": n(b)} for a, b in zip(pair_names, top_pairs.values)],
        "surnames": [{"name": k, "count": n(v)} for k, v in surnames.head(TOP_NAMES).items()],
        "firsts": [{"name": k, "count": n(v)} for k, v in firsts.head(TOP_NAMES).items()],
    }

    return {
        "agent_data": {
            "summary_he": (f"רשימת הנוטריונים הפעילים של משרד המשפטים: {n(total)} נוטריונים "
                           f"ב-{n(len(cities))} ישובים, ובהם {n(with_l)} שמציינים שפה נוספת — "
                           f"פריסה גאוגרפית ושפות השירות."),
            "dataset_kind": "registry",
            "related_ids": ["713440a1-9963-4548-a7d9-9d9c9da54f62",
                            "669b2652-f75b-4de3-8e6b-0dfa17accef5",
                            "1806c96c-9cc4-47bf-98b3-80a18f061f98",
                            "176f2727-476e-440e-bc8d-5d3461ea0e76"],
            "suggested_tags": ["נוטריונים", "רישוי מקצועי", "משרד המשפטים",
                               "שירותים משפטיים", "שפות", "מרשמים מקצועיים"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
