"""Annual data of air-monitoring stations: the station list behind the
Ministry of Environmental Protection's per-station ZIP downloads.

The table is a directory (number, name, link to a ZIP with the station's
yearly files). Everything on the page is computed from those three columns:
station kind (fixed / mobile / test record) from the name, numbering blocks
from the number, place clusters from the leading place name, and link
consistency (host, ZIP, file name == station number) from the link.
"""
import re

import pandas as pd
from govlib import fmt, frame

NUM, NAME, LINK = "num", "name_raw", "link_raw"
# The upstream column names have flipped between a Hebrew and an English set
# more than once; accept either, mapped to the internal names above.
COLUMN_SETS = [
    {"מספר תחנת ניטור": NUM, "שם תחנת ניטור": NAME, "קישור לתחנת ניטור": LINK},
    {"MonitoringStationNum": NUM, "MonitoringStationName": NAME, "File": LINK},
]


def _normalize_columns(df):
    for mapping in COLUMN_SETS:
        if all(c in df.columns for c in mapping):
            return df[list(mapping)].rename(columns=mapping)
    sets = " / ".join(", ".join(m) for m in COLUMN_SETS)
    raise ValueError(f"stations: neither column set is complete ({sets}); got {list(df.columns)}")
HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)

# Test records the ministry left in the list ("בדיקה", "תחנה חדשה", a bare
# "תחנה 1", and a few named after the person who keyed them).
# Hebrew-letter boundaries: punctuation and digits end a word, letters don't.
HEB = "\u05d0-\u05ea"
TEST_RE = re.compile(rf"בדיק|פרידי(?![{HEB}])|^תחנה\s+\d+$|^תחנה\s.*חדשה")
# Mobile units: vans ("ניידת") and trailers ("קרון").
# A one-letter prefix (ה/ב/ו/ל) is allowed: "הניידת", "בקרון".
MOBILE_RE = re.compile(rf"(?<![{HEB}])[הבול]?(?:ניידת|קרון)(?![{HEB}])")
KIND_ORDER = ["fixed", "mobile", "test"]
KIND_HE = {"fixed": "תחנה קבועה", "mobile": "יחידה ניידת", "test": "רשומת בדיקה"}

# Place names that need their second word to name the place.
PREFIX_WORDS = {
    "קרית", "נאות", "גן", "גבעת", "כפר", "בית", "יד", "ניר", "עין", "מעין",
    "שדה", "באר", "גליל", "דרך", "רמת", "שיכון", "בני", "אור", "נווה", "צומת",
    "דליית", "זכרון", "פרדס", "כרם", "כרמי", "חבל", "גוש", "פארק", "אחוזה",
    "עירוני", "מחנה", "אתר", "אורות", "בריכות", "נגב", "אום", "שגב", "יבנה",
    "תורן", "בת",
}
# Words that name the operator, not the place.
OPERATOR_WORDS = {"איגוד", "ערים"}
OPERATOR_RE = re.compile(r"-?\b(?:" + "|".join(sorted(OPERATOR_WORDS)) + r")\b-?")
HOST_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/:?#@]+)")
ZIP_RE = re.compile(r"/([^/?#]+)\.zip$", re.IGNORECASE)


def kind_of(name):
    if TEST_RE.search(name):
        return "test"
    if MOBILE_RE.search(name):
        return "mobile"
    return "fixed"


def place_of(name):
    """The place a station's name starts with: 'אילת 6 (שחמון)' → 'אילת',
    'נאות חובב צפונית(תחנה 2)' → 'נאות חובב', 'אשדוד-איגוד' → 'אשדוד'."""
    s = re.sub(r"\(.*?\)|\(.*$", " ", name)
    s = re.sub(r"\d+", " ", s)
    s = OPERATOR_RE.sub(" ", s)
    s = " ".join(w for w in s.split() if w).strip(" -\u2013")
    # A spaced dash or an en dash separates place from sub-site; a bare
    # hyphen joins a name ('אום אל-פאחם').
    pieces = [p.strip() for p in re.split(r"\s+-\s+|\s*\u2013\s*", s) if p.strip()]
    if not pieces:
        return ""
    w = pieces[0].split()
    if len(w) > 1 and w[0] in PREFIX_WORDS:
        return " ".join(w[:2])
    return w[0]


def _prepare(df):
    df = _normalize_columns(df)
    df["name"] = frame.clean_series(df[NAME])
    # The Hebrew-set link column holds a bare URL; the English `File` column
    # held an HTML anchor, so take its href when there is one.
    raw = frame.clean_series(df[LINK])
    href = raw.str.extract(HREF_RE)[0]
    df["link"] = href.where(href.notna(), raw.where(~raw.str.contains("<", regex=False), "")).fillna("").str.strip()
    df["num_s"] = frame.clean_series(df[NUM])
    df["n"] = pd.to_numeric(df["num_s"], errors="coerce")
    df = df[(df["name"] != "") | (df["num_s"] != "")].copy()
    df["kind"] = df["name"].map(kind_of)
    df["place"] = df["name"].map(place_of)
    df["sort_n"] = df["n"].fillna(10**9)
    return df.sort_values(["sort_n", "num_s", "name", "link"], kind="stable").reset_index(drop=True)


def _block_size(max_n):
    return 100 if max_n < 2000 else 1000


def _blocks(df):
    nums = df.dropna(subset=["n"])
    if nums.empty:
        return {"labels": [], "series": {k: [] for k in KIND_ORDER}}, []
    size = _block_size(nums["n"].max())
    nums = nums.assign(blk=(nums["n"] // size * size).astype(int))
    tab = nums.groupby(["blk", "kind"]).size().unstack(fill_value=0).sort_index()
    for k in KIND_ORDER:
        if k not in tab.columns:
            tab[k] = 0
    labels = [f"{b}-{b + size - 1}" for b in tab.index]
    series = {k: [int(v) for v in tab[k]] for k in KIND_ORDER}
    rows = [[lab, fmt.int_he(series["fixed"][i]), fmt.int_he(series["mobile"][i]),
             fmt.int_he(series["test"][i])] for i, lab in enumerate(labels)]
    return {"labels": labels, "series": series, "size": size}, rows


def _link_stats(df):
    links = df[df["link"] != ""]
    hosts = links["link"].str.extract(HOST_RE)[0].fillna("").str.lower()
    host_counts = frame.ranked(hosts[hosts != ""])
    stems = links["link"].str.extract(ZIP_RE)[0]
    is_zip = stems.notna()
    matches = is_zip & (stems == links["num_s"])
    return {
        "n_links": len(links),
        "n_missing": int((df["link"] == "").sum()),
        "n_hosts": int(host_counts.size),
        "top_host": str(host_counts.index[0]) if host_counts.size else "",
        "n_zip": int(is_zip.sum()),
        "n_match": int(matches.sum()),
    }


# ---------- insight rules: a sentence, or None when the premise fails ----------

def insight_mix(n_live, n_fixed, n_mobile):
    if n_live == 0:
        return None
    if n_mobile == 0:
        return f"כל {fmt.int_he(n_live)} התחנות ברשימה הן תחנות קבועות; אין בה יחידות ניטור ניידות."
    return (f"הרשימה כוללת {fmt.int_he(n_live)} תחנות ניטור: {fmt.int_he(n_fixed)} תחנות קבועות "
            f"ו-{fmt.int_he(n_mobile)} יחידות ניידות (ניידות וקרונות), "
            f"{fmt.pct(n_mobile / n_live)} מהרשימה.")


def insight_tests(test):
    n = len(test)
    if n == 0:
        return None
    nums = test["n"].dropna()
    rng = ""
    if len(nums) >= 2:
        rng = f" (מספרים {fmt.int_he(nums.min())} עד {fmt.int_he(nums.max())})"
    elif len(nums) == 1:
        rng = f" (מספר {fmt.int_he(nums.iloc[0])})"
    word = "רשומות" if n > 1 else "רשומה"
    return (f"{fmt.int_he(n)} {word}{rng} נראות כרשומות בדיקה ולא כתחנות אמיתיות, לפי שמן "
            "(למשל \"בדיקה\" או \"תחנה חדשה\"). הן אינן נכללות בספירת התחנות ובטבלת התחנות בעמוד.")


def insight_cluster(places):
    if places.empty or places.iloc[0] < 3:
        return None
    top = places[places == places.iloc[0]]
    if len(top) > 1:
        return None  # no single leading place
    name, v = str(places.index[0]), int(places.iloc[0])
    second = ""
    unique_second = len(places) == 2 or (len(places) > 2 and places.iloc[1] > places.iloc[2])
    if len(places) > 1 and places.iloc[1] >= 2 and unique_second:
        second = (f", ואחריו {places.index[1]} עם {fmt.int_he(places.iloc[1])} תחנות")
    return (f"הריכוז הגדול ביותר של תחנות קבועות באותו מקום הוא ב{name}: "
            f"{fmt.int_he(v)} תחנות ששמן מתחיל בשם המקום{second}.")


def insight_operator(live):
    n = int(live["name"].str.contains("איגוד", regex=False).sum())
    if n < 2:
        return None
    return (f"{fmt.int_he(n)} תחנות נושאות בשמן את המילה \"איגוד\", כלומר מזוהות עם "
            "איגוד ערים לאיכות הסביבה.")


def insight_links(ls):
    if ls["n_links"] == 0:
        return None
    if ls["n_hosts"] == 1 and ls["n_zip"] == ls["n_links"]:
        tail = ""
        if ls["n_match"] == ls["n_links"]:
            tail = " ושם כל קובץ הוא מספר התחנה"
        miss = ""
        if ls["n_missing"]:
            miss = f" ל-{fmt.int_he(ls['n_missing'])} רשומות אין קישור."
        return (f"כל {fmt.int_he(ls['n_links'])} הקישורים מפנים לקובצי ZIP בשרת אחד{tail}; "
                f"כל קובץ מרכז את הנתונים השנתיים של תחנה אחת.{miss}")
    if ls["n_zip"] < ls["n_links"]:
        return (f"{fmt.int_he(ls['n_zip'])} מתוך {fmt.int_he(ls['n_links'])} הקישורים מפנים "
                "לקובצי ZIP; השאר בפורמט אחר.")
    return None


def insight_numbering(live, size):
    nums = live["n"].dropna()
    if len(nums) < 2:
        return None
    lo, hi = int(nums.min()), int(nums.max())
    blk = (nums // size * size).astype(int)
    counts = frame.ranked(blk)
    b, v = int(counts.index[0]), int(counts.iloc[0])
    share = v / len(nums)
    if share < 0.25:
        return None
    gap = ""
    if nums.nunique() < hi - lo + 1:
        gap = f", אך רק {fmt.int_he(nums.nunique())} מספרים בטווח הזה תפוסים"
    return (f"מספרי התחנות נעים בין {fmt.int_he(lo)} ל-{fmt.int_he(hi)}{gap}. "
            f"{fmt.int_he(v)} תחנות ({fmt.pct(share)}) ממוספרות בטווח {b}-{b + size - 1}.")


def insight_duplicates(df):
    nums = df[df["num_s"] != ""]
    dup = int(nums["num_s"].duplicated(keep=False).sum())
    if dup == 0:
        return None
    return f"{fmt.int_he(dup)} רשומות חולקות מספר תחנה עם רשומה אחרת."


def compute(frames):
    df = _prepare(frames["stations"])
    live = df[df["kind"] != "test"]
    test = df[df["kind"] == "test"]
    fixed = live[live["kind"] == "fixed"]
    n_rows, n_live = len(df), len(live)
    n_fixed, n_mobile, n_test = len(fixed), len(live) - len(fixed), len(test)

    kind_counts = [int((df["kind"] == k).sum()) for k in KIND_ORDER]
    blocks, block_rows = _blocks(df)
    size = blocks.get("size", 100)

    places = frame.ranked(fixed.loc[fixed["place"] != "", "place"])
    multi = places[places >= 2]
    fam_labels, fam_values = frame.top_other(multi, 12)
    n_in_multi = int(multi.sum())

    ls = _link_stats(df)
    live_nums = live["n"].dropna()
    lo = int(live_nums.min()) if len(live_nums) else None
    hi = int(live_nums.max()) if len(live_nums) else None

    rules = [
        ("mix", insight_mix(n_live, n_fixed, n_mobile)),
        ("tests", insight_tests(test)),
        ("cluster", insight_cluster(places)),
        ("operator", insight_operator(live)),
        ("numbering", insight_numbering(live, size)),
        ("links", insight_links(ls)),
        ("duplicates", insight_duplicates(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    top_place = str(places.index[0]) if len(places) else ""
    summary = (f"רשימת {fmt.int_he(n_live)} תחנות הניטור של המשרד להגנת הסביבה "
               f"({fmt.int_he(n_fixed)} קבועות ו-{fmt.int_he(n_mobile)} ניידות), "
               + ("ולכל תחנה קישור לקובץ ZIP עם הנתונים השנתיים שלה."
                  if ls["n_missing"] == 0 and ls["n_zip"] == ls["n_links"] > 0
                  else "וקישורים לקובצי הנתונים השנתיים של התחנות."))
    if n_test:
        summary += f" הרשימה כוללת גם {fmt.int_he(n_test)} רשומות בדיקה."
    desc = (f"איתור תחנת ניטור איכות אוויר לפי שם או מספר והורדת הנתונים השנתיים שלה: "
            f"{fmt.int_he(n_live)} תחנות" + (f", מהן {fmt.int_he(n_mobile)} ניידות." if n_mobile else "."))

    directory = [[r["num_s"] or "–", r["name"] or "–", KIND_HE[r["kind"]]]
                 for r in live[["num_s", "name", "kind"]].to_dict("records")]

    span = f"{lo}–{hi}" if lo is not None else "–"
    blk_lead = ""
    if blocks["labels"]:
        tot = [sum(blocks["series"][k][i] for k in ("fixed", "mobile")) for i in range(len(blocks["labels"]))]
        bi = max(range(len(tot)), key=lambda i: (tot[i], -i))
        blk_lead = f"הטווח הצפוף ביותר הוא {blocks['labels'][bi]} עם {fmt.int_he(tot[bi])} תחנות (ללא רשומות בדיקה)."
    n_bad_num = int(df["n"].isna().sum())
    blocks_note = (f"מספר הרשומות בכל טווח של {fmt.int_he(size)} מספרים, לפי סוג. {blk_lead}")
    if n_bad_num:
        blocks_note += f" {fmt.int_he(n_bad_num)} רשומות ללא מספר תקין אינן מוצגות."

    fam_note = (f"מקומות שיש בהם לפחות שתי תחנות קבועות, לפי שם המקום שבתחילת שם התחנה "
                f"(קיבוץ לפי השם בלבד). {fmt.int_he(n_in_multi)} מתוך {fmt.int_he(n_fixed)} "
                "התחנות הקבועות שייכות לריכוזים כאלה.")
    kinds_note = (f"{fmt.int_he(n_rows)} רשומות ברשימה: {fmt.int_he(n_fixed)} תחנות קבועות, "
                  f"{fmt.int_he(n_mobile)} יחידות ניידות ו-{fmt.int_he(n_test)} רשומות בדיקה. "
                  "הסיווג נעשה לפי שם התחנה.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "תחנות ניטור איכות אוויר: רשימה ונתונים שנתיים",
                "description": desc,
                "name": "תחנות ניטור איכות האוויר: נתונים שנתיים",
                "alternate_names": [
                    "נתונים שנתיים של תחנות ניטור",
                    "צובר ניטור רציף",
                    "תחנות ניטור אוויר",
                    "רשימת תחנות ניטור זיהום אוויר",
                ],
            },
        },
        "kpis": {
            "stations": {"value": n_live, "display": fmt.int_he(n_live), "tone": "brand"},
            "fixed": {"value": n_fixed, "display": fmt.int_he(n_fixed), "tone": "brand"},
            "mobile": {"value": n_mobile, "display": fmt.int_he(n_mobile), "tone": "info"},
            "tests": {"value": n_test, "display": fmt.int_he(n_test),
                      "tone": "warn" if n_test else "ok"},
            "span": {"value": [lo, hi], "display": span, "tone": "brand"},
        },
        "charts": {
            "kinds": {"names": [KIND_HE[k] for k in KIND_ORDER], "values": kind_counts},
            "blocks": {"labels": blocks["labels"],
                       "names": [KIND_HE[k] for k in KIND_ORDER],
                       "series": [blocks["series"][k] for k in KIND_ORDER]},
            "places": {"names": fam_labels, "values": [int(v) for v in fam_values]},
        },
        "flags": {"places": len(multi) >= 2, "tests": n_test > 0},
        "insights": insights,
        "tables": {
            "kinds": [[KIND_HE[k], fmt.int_he(kind_counts[i])] for i, k in enumerate(KIND_ORDER)],
            "blocks": block_rows,
            "places": [[fam_labels[i], fmt.int_he(v)] for i, v in enumerate(fam_values)],
            "directory": directory,
        },
        "labels": {
            "kinds_note": kinds_note,
            "kinds_aria": (f"תרשים עמודות: סוגי הרשומות ברשימה. {fmt.int_he(n_fixed)} תחנות קבועות, "
                           f"{fmt.int_he(n_mobile)} יחידות ניידות, {fmt.int_he(n_test)} רשומות בדיקה."),
            "blocks_note": blocks_note,
            "blocks_aria": f"תרשים עמודות מוערמות: מספר הרשומות לפי טווח מספור וסוג. {blk_lead}",
            "places_note": fam_note,
            "places_aria": (f"תרשים עמודות אופקי: ריכוזי תחנות קבועות לפי מקום. "
                            f"המוביל: {top_place}, {fmt.int_he(places.iloc[0]) if len(places) else 0} תחנות."),
            "dir_note": (f"{fmt.int_he(n_live)} תחנות ויחידות ניידות, ממוינות לפי מספר התחנה "
                         "(ללא רשומות הבדיקה). הקישור לקובץ הנתונים של כל תחנה מופיע בטבלת הנתונים "
                         "שבתחתית העמוד."),
            "dir_cap": f"רשימת {fmt.int_he(n_live)} תחנות הניטור: מספר, שם וסוג.",
            "stations_kpi": "תחנות ויחידות ניטור",
            "fixed_kpi": "תחנות קבועות",
            "mobile_kpi": "יחידות ניידות",
            "tests_kpi": "רשומות בדיקה (לא נספרות)",
            "span_kpi": "טווח מספרי התחנות",
        },
    }
