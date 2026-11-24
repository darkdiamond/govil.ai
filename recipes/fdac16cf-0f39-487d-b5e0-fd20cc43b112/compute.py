"""ציוד אלחוטי - פריטים ביבוא אישי שלא קיבלו אישור משרד התקשורת: the
Ministry of Communications' list of wireless items (model, manufacturer,
product type) that were refused for personal import. One row per item.

The page is a lookup page first (is my model on the refused list), then what
the list says about itself: which kinds of products get refused (types and
broader families), which manufacturers dominate, how concentrated the list
is, and which product types are refused across the board ("ALL MODELS").

Product types are free English text with typos (TRANSCIEVER / TRANCIEVER),
so they are upper-cased, whitespace-collapsed and fixed word by word from a
small typo map; the page says so. Known types get a Hebrew name and every
type is put in a family by ordered keyword rules; an unknown type keeps its
English name and lands in "אחר", so new types flow through. Manufacturer
names are grouped by a normalized key (case, punctuation, legal suffixes),
labelled by the group's most common spelling.

Growth: the resource is replaced in place. Every category axis is top-N
with an "אחר" bucket; the blanket-ban list is short by nature, capped at
BANS_MAX rows. No dates in the data, so no time axis.
"""
import re

import pandas as pd
from govlib import fmt, frame

TOP_TYPES = 15
TOP_MAKERS = 15
STACK_MAKERS = 10
BANS_MAX = 20
SPECIALIST_SHARE = 0.8
MAIN_TYPE_SHARE = 0.5
TOP2_FAMILY_SHARE = 0.4

C_MODEL = "model"
C_MAKER = "manufacturer"
C_TYPE = "type_of_product"

ALL_MODELS = re.compile(r"^ALL\s+MODELS?$")
ALL_MAKERS = re.compile(r"^ALL\s+MANUFACTURERS?$")

# Word-level spelling fixes for product types seen in the list.
TYPO = {
    "TRANSCIEVER": "TRANSCEIVER", "TRANCIEVER": "TRANSCEIVER",
    "REAPITER": "REPEATER", "CMERA": "CAMERA", "TRANSMITTION": "TRANSMISSION",
    "SPRINKER": "SPRINKLER", "ANALAZER": "ANALYZER", "ANALAYZER": "ANALYZER",
    "WIRLESS": "WIRELESS",
}

TYPE_HE = {
    "WALKIE TALKIE": "מכשיר קשר נייד",
    "DRONE": "רחפן",
    "REMOTE CONTROL": "שלט רחוק",
    "MICROPHONE": "מיקרופון אלחוטי",
    "CORDLESS PHONE": "טלפון אלחוטי",
    "TRANSMITTER": "משדר",
    "ROUTER": "נתב",
    "MODULE": "מודול תקשורת",
    "RECEIVER": "מקלט",
    "TRANSCEIVER": "משדר-מקלט",
    "LORAWAN": "ציוד LoRaWAN",
    "DOG COLLAR": "קולר לכלב",
    "SMART HOME HUB": "רכזת בית חכם",
    "NETWORK CARD": "כרטיס רשת",
    "ACCESS POINT": "נקודת גישה",
    "RF DETECTOR": "גלאי תדרים",
    "INTERCOM SYSTEM": "מערכת אינטרקום",
    "CAR PLAY": "מתאם CarPlay לרכב",
    "WEATHER STATION": "תחנת מזג אוויר",
    "ADAPTER": "מתאם אלחוטי",
    "REPEATER": "מגדיל טווח",
    "MOBILE RADIO": "מכשיר קשר לרכב",
    "MONITOR SYSTEM": "מערכת ניטור",
    "RFID READER": "קורא RFID",
    "ALARM": "מערכת אזעקה",
    "SPRINKLER CONTROLLER": "בקר השקיה",
    "MEASURING EQUIPMENT": "ציוד מדידה",
    "VIDEO TRANSMISSION SYSTEM": "מערכת שידור וידאו",
    "SECURITY SYSTEM": "מערכת אבטחה",
    "BOARD": "לוח אלקטרוני",
    "MODEM": "מודם",
    "RADAR DETECTOR": "גלאי מכ״ם",
    "METAL DETECTOR": "גלאי מתכות",
    "SENSOR": "חיישן",
    "HEADPHONES": "אוזניות אלחוטיות",
    "GPS TRACKER": "משדר איתור GPS",
    "ANTENNA": "אנטנה",
    "CELLULAR AMPLIFIER": "מגבר סלולרי",
    "CELLULAR REPEATER": "ממסר סלולרי",
    "FREQUENCY JAMMER": "משבש תדרים",
    "CAMERA 900MHZ": "מצלמה אלחוטית בתדר 900MHZ",
    "CORDLESS PHONE DECT 6.0": "טלפון אלחוטי בתקן DECT 6.0",
    "MARINE RADIO": "מכשיר קשר ימי",
    "PROJECTOR": "מקרן",
    "TABLET": "טאבלט",
}

OTHER_FAMILY = "אחר"
# Ordered: the first matching rule wins (e.g. "RADIO MODULE" is a module,
# "CAMERA DETECTOR" a detector, "FLIGHT CONTROLLER" a drone part).
FAMILIES = [
    ("רחפנים ושליטה מרחוק",
     r"\bDRONES?\b|REMOTE CONTROL|RADIO CONTROL|FLIGHT CONTROLLER|\bFPV\b|\bROBOT|SMART TOY"),
    ("בית חכם ואבטחה",
     (r"SMART HOME|\bALARM|SECURITY|SAFETY|\bALERT|INTERCOM|MONITOR SYSTEM|SPRINKLER|WEATHER"
      r"|GATE OPENER|SMART PLUG|PETS? FEEDER|\bLED\b|LAWN MOWER|POWER METER|\bPLC\b")),
    ("מודולים ורכיבים",
     r"MODULE|\bBOARD\b|MICRO ?CONTROLLER|DEVELOPMENT KIT|RASPBERRY|\bSDR\b|\bIMU\b|DONGLE"),
    ("גלאים, סורקים ומדידה",
     (r"DETECTOR|SCANNER|ANALY[SZ]ER|MEASURING|RADAR|RADIOMETER|COUNTER|DYNAMOMETER|\bGPR\b"
      r"|\bVECTOR\b|SENSOR|RFID|READER")),
    ("רשתות, סלולר ואנטנות",
     (r"ROUTER|ACCESS POINT|NETWORK|\bLAN\b|MODEM|\bMESH\b|HOTSPOT|ADAPTER|LORA|POWERBEAM"
      r"|\bGSM\b|SIGNAL BOOSTER|CELLULAR|REPEATER|ANTENNA|JAMMER")),
    ("מכשירי קשר",
     r"WALKIE|TRANSCEIVER|\bRADIO\b|PAGER|BASE STATION"),
    ("שמע ומיקרופונים",
     r"MICROPHONE|HEADPHONE|\bEAR\b|SPEAKER|GUITAR|AMPLIFIER|MEGAPHONE"),
    ("טלפונים אלחוטיים", r"CORDLESS PHONE|\bDECT\b"),
    ("וידאו ומולטימדיה",
     r"VIDEO|\bTV\b|PROJECTOR|STREAMER|\bVR\b|GLASSES|TABLET|CAMERA"),
    ("רכב", r"CAR ?PLAY|DIAGNOSTIC"),
    ("איתור ומעקב", r"TRACKER|COLLAR|TRANSPONDER"),
    ("משדרים ומקלטים", r"TRANSMITTER|RECEIVER"),
]
FAMILY_RX = [(name, re.compile(rx)) for name, rx in FAMILIES]

SUFFIXES = {
    "CO", "COMPANY", "LTD", "LIMITED", "INC", "INCORPORATED", "CORP",
    "CORPORATION", "GMBH", "LLC", "PLC", "SA", "AG", "AB", "BV", "NV", "SRL",
    "SPA", "PTE", "KG", "OY", "AS", "SAS", "SL", "KK", "PTY", "THE",
}

BUCKETS = [(1, 1, "פריט אחד"), (2, 4, "2-4 פריטים"), (5, 9, "5-9 פריטים"),
           (10, 49, "10-49 פריטים"), (50, None, "50 פריטים ומעלה")]

NONE_LABEL = "לא צוין"
NONE_KEY = "\u0000none"
# Manufacturer cells that name no manufacturer.
PLACEHOLDER = re.compile(r"N/?A|NONE|UNKNOWN|NULL|NIL|-+|\.+|\?+|לא ידוע|לא צוין")


def _type_key(s):
    s = frame.clean(s).upper()
    return " ".join(TYPO.get(w, w) for w in s.split())


def _type_he(k):
    return TYPE_HE.get(k, k)


def _family(k):
    for name, rx in FAMILY_RX:
        if rx.search(k):
            return name
    return OTHER_FAMILY


def _maker_key(name):
    s = frame.clean(name).upper()
    s = re.sub(r"[^\w]+", " ", s).replace("_", " ")
    words = s.split()
    while len(words) > 1 and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def _pct(part, whole):
    if not whole:
        return "0%"
    v = part / whole * 100
    if 0 < v < 0.1:
        return "<0.1%"
    return f"{v:.1f}%"


def _display_names(df, key_col, raw_col):
    """key -> most common raw spelling (ties: alphabetical)."""
    g = (df.groupby([key_col, raw_col]).size().reset_index(name="n")
         .sort_values([key_col, "n", raw_col], ascending=[True, False, True], kind="mergesort"))
    g = g.drop_duplicates(key_col)
    return dict(zip(g[key_col], g[raw_col]))


def _ranked_df(df, key, label_map):
    out = (df.groupby(key).size().reset_index(name="n")
           .assign(name=lambda x: x[key].map(label_map))
           .sort_values(["n", "name", key], ascending=[False, True, True], kind="mergesort")
           .reset_index(drop=True))
    return out


def compute(frames):
    df = frames["items"].copy()
    for c in (C_MODEL, C_MAKER, C_TYPE):
        df[c] = df[c].map(frame.clean)
    df = df[(df[C_MODEL] != "") | (df[C_MAKER] != "") | (df[C_TYPE] != "")].copy()
    total = len(df)
    if total == 0:
        raise ValueError("the list is empty")

    df["tk"] = df[C_TYPE].map(_type_key)
    df.loc[df["tk"] == "", "tk"] = NONE_LABEL
    fam_of = {k: _family(k) for k in df["tk"].unique()}
    df["family"] = df["tk"].map(fam_of)
    df["all_models"] = df[C_MODEL].str.upper().str.match(ALL_MODELS)
    df["all_makers"] = df[C_MAKER].str.upper().str.match(ALL_MAKERS)
    no_maker = (df[C_MAKER] == "") | df[C_MAKER].str.upper().str.fullmatch(PLACEHOLDER)
    df["maker_raw"] = df[C_MAKER].where(~no_maker, NONE_LABEL)
    df["mk"] = df["maker_raw"].map(_maker_key)
    df.loc[no_maker, "mk"] = NONE_KEY
    df["mod_k"] = df[C_MODEL].str.upper().str.replace(r"\s+", "", regex=True)

    # ── product types ───────────────────────────────────────────────
    tc = (df.groupby("tk").size().reset_index(name="n")
          .sort_values(["n", "tk"], ascending=[False, True], kind="mergesort")
          .reset_index(drop=True))
    tc["he"] = tc["tk"].map(_type_he)
    tc["family"] = tc["tk"].map(fam_of)
    n_types = len(tc)
    n_raw_types = int(df[C_TYPE].nunique())
    types_rows = [{"he": r.he, "en": r.tk, "n": int(r.n), "pct": _pct(int(r.n), total)}
                  for r in tc.head(TOP_TYPES).itertuples()]
    rest_types = tc.iloc[TOP_TYPES:]
    types_chart = {"names": [r["he"] for r in types_rows], "en": [r["en"] for r in types_rows],
                   "values": [r["n"] for r in types_rows]}
    if len(rest_types):
        rest_n = int(rest_types["n"].sum())
        types_chart["names"].append(f"{len(rest_types):,} סוגים נוספים")
        types_chart["en"].append("")
        types_chart["values"].append(rest_n)
    top5_types = int(tc["n"].head(5).sum())

    # ── families ────────────────────────────────────────────────────
    fc = (df.groupby("family").size().reset_index(name="n"))
    fc["other"] = fc["family"] == OTHER_FAMILY
    fc = fc.sort_values(["other", "n", "family"], ascending=[True, False, True],
                        kind="mergesort").reset_index(drop=True)
    fam_types = tc.groupby("family").size().to_dict()
    fam_top = tc.drop_duplicates("family").set_index("family")["he"].to_dict()
    family_rows = [{"name": r.family, "n": int(r.n), "pct": _pct(int(r.n), total),
                    "types": int(fam_types.get(r.family, 0)), "top": fam_top.get(r.family, "")}
                   for r in fc.itertuples()]
    family_chart = {"names": [r["name"] for r in family_rows],
                    "values": [r["n"] for r in family_rows]}
    fam_rank = fc[~fc["other"]].reset_index(drop=True)
    n_other_family = int(fc.loc[fc["other"], "n"].sum())

    # ── manufacturers: "ALL MANUFACTURERS" and missing-maker rows excluded ──
    n_all_makers_rows = int(df["all_makers"].sum())
    n_no_maker = int((~df["all_makers"] & (df["mk"] == NONE_KEY)).sum())
    dm = df[~df["all_makers"] & (df["mk"] != NONE_KEY)]
    names = _display_names(dm, "mk", "maker_raw") if len(dm) else {}
    n_mk_rows = len(dm)
    mc = _ranked_df(dm, "mk", names) if n_mk_rows else pd.DataFrame(columns=["mk", "n", "name"])
    n_makers = len(mc)
    n_raw_makers = int(dm["maker_raw"].nunique()) if n_mk_rows else 0

    # main type per manufacturer
    mt = (dm.groupby(["mk", "tk"]).size().reset_index(name="n")
          .sort_values(["mk", "n", "tk"], ascending=[True, False, True], kind="mergesort")
          .drop_duplicates("mk").set_index("mk")) if n_mk_rows else pd.DataFrame()

    makers_rows = []
    for r in mc.head(TOP_MAKERS).itertuples():
        main_tk = mt.loc[r.mk, "tk"]
        main_n = int(mt.loc[r.mk, "n"])
        makers_rows.append({"name": r.name, "n": int(r.n), "pct": _pct(int(r.n), n_mk_rows),
                            "main": _type_he(main_tk), "main_pct": _pct(main_n, int(r.n)),
                            "main_share": main_n / int(r.n)})
    makers_chart = {"names": [r["name"] for r in makers_rows],
                    "values": [r["n"] for r in makers_rows]}

    # stacked: top manufacturers by family
    top_mk = list(mc.head(STACK_MAKERS)["mk"])
    ds = dm[dm["mk"].isin(set(top_mk))]
    sc = ds.groupby(["mk", "family"]).size()
    fam_in = (ds.groupby("family").size().reset_index(name="n")
              .assign(other=lambda x: x["family"] == OTHER_FAMILY)
              .sort_values(["other", "n", "family"], ascending=[True, False, True], kind="mergesort"))
    stack_fams = list(fam_in["family"])
    stack = {"makers": [names[k] for k in top_mk],
             "series": [{"name": f, "data": [int(sc.get((k, f), 0)) for k in top_mk]}
                        for f in stack_fams]}
    has_stack = len(top_mk) >= 3 and len(stack_fams) >= 2
    mk_n = dict(zip(mc["mk"], mc["n"]))
    fam_max = sc.groupby(level=0).max().to_dict() if len(sc) else {}
    n_fam_spec = sum(1 for k in top_mk if fam_max.get(k, 0) / mk_n[k] >= SPECIALIST_SHARE)

    # concentration buckets
    bucket_rows = []
    for lo, hi, label in BUCKETS:
        m = (mc["n"] >= lo) & ((mc["n"] <= hi) if hi is not None else True)
        nn = int(mc.loc[m, "n"].sum())
        bucket_rows.append({"name": label, "makers": int(m.sum()), "n": nn,
                            "pct": _pct(nn, n_mk_rows)})
    bucket_rows = [b for b in bucket_rows if b["makers"] > 0]
    buckets_chart = {"names": [b["name"] for b in bucket_rows],
                     "makers": [b["makers"] for b in bucket_rows],
                     "items": [b["n"] for b in bucket_rows]}
    singles = int((mc["n"] == 1).sum())
    cum = mc["n"].cumsum().tolist()

    # ── blanket bans ────────────────────────────────────────────────
    # Global (all makers + all models) rows dedupe on the type alone; an
    # all-makers row on (type, model); an all-models row on (type, maker key).
    bans = df[df["all_models"] | df["all_makers"]].copy()
    bans["glob"] = bans["all_models"] & bans["all_makers"]
    bans["scope"] = bans["glob"].map(lambda v: 0 if v else 1)
    bans["dkey"] = [("" if g else ("M\u0001" + mo if am else "K\u0001" + k))
                    for g, am, mo, k in zip(bans["glob"], bans["all_makers"], bans["mod_k"], bans["mk"])]
    bans["he"] = bans["tk"].map(_type_he)
    bans = (bans.sort_values(["scope", "dkey", "he", "tk", C_MAKER, C_MODEL], kind="mergesort")
            .drop_duplicates(["scope", "dkey", "tk"]))
    ban_rows = []
    for r in bans.itertuples():
        if r.glob:
            who, what, who_ltr, what_ltr = "כל היצרנים", "כל הדגמים", False, False
        elif r.all_makers:
            model = getattr(r, C_MODEL)
            who, what, who_ltr, what_ltr = "כל היצרנים", model or NONE_LABEL, False, bool(model)
        else:
            known = r.mk != NONE_KEY
            who = names.get(r.mk, r.maker_raw) if known else NONE_LABEL
            what, who_ltr, what_ltr = "כל הדגמים", known, False
        ban_rows.append({"type": r.he, "en": r.tk, "who": who, "what": what,
                         "who_ltr": who_ltr, "what_ltr": what_ltr, "global": bool(r.glob)})
    n_ban_rows = len(ban_rows)
    global_bans = [b for b in ban_rows if b["global"]]
    maker_bans = [b for b in ban_rows if not b["global"]]
    ban_rows = ban_rows[:BANS_MAX]

    # ── repeated models ─────────────────────────────────────────────
    dr = df[(df["mod_k"] != "") & ~df["all_models"]]
    rep = dr.groupby(["mod_k", "mk"]).size()
    rep2 = rep[rep >= 2]
    n_rep = len(rep2)
    n_rep_rows = int(rep2.sum())
    dr_k = dr[dr["mk"] != NONE_KEY]
    n_cross = int((dr_k.groupby("mod_k")["mk"].nunique() >= 2).sum()) if len(dr_k) else 0

    # ── KPIs ────────────────────────────────────────────────────────
    kpis = {
        "total": {"value": total, "display": f"{total:,}", "tone": "brand"},
        "makers": {"value": n_makers, "display": f"{n_makers:,}", "tone": "brand"},
        "types": {"value": n_types, "display": f"{n_types:,}", "tone": "brand"},
        "bans": {"value": len(global_bans), "display": f"{len(global_bans):,}",
                 "tone": "warn" if global_bans else "brand"},
    }

    # ── insights ────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def i_top_type():
        if len(tc) < 2:
            return None
        a, b = tc.iloc[0], tc.iloc[1]
        if int(a["n"]) <= int(b["n"]):
            return None
        return (f"סוג המוצר הנפוץ ביותר ברשימה הוא {a['he']} ({a['tk']}): "
                f"{int(a['n']):,} פריטים, {_pct(int(a['n']), total)} מהרשימה. "
                f"אחריו {b['he']} ({b['tk']}) עם {int(b['n']):,} פריטים.")

    def i_families():
        if len(fam_rank) < 3:
            return None
        a, b = fam_rank.iloc[0], fam_rank.iloc[1]
        both = int(a["n"]) + int(b["n"])
        if both / total < TOP2_FAMILY_SHARE:
            return None
        return (f"שתי קבוצות מוצרים מרכזות {_pct(both, total)} מהרשימה: "
                f"{a['family']} ({int(a['n']):,} פריטים) ו{b['family']} ({int(b['n']):,}).")

    def i_leader():
        if len(makers_rows) < 2:
            return None
        a, b = makers_rows[0], makers_rows[1]
        if a["n"] <= b["n"]:
            return None
        tail = ""
        if a["main_share"] >= MAIN_TYPE_SHARE:
            tail = f" {a['main_pct']} מהפריטים שלו הם מסוג {a['main']}."
        return (f"היצרן שמופיע ברשימה הכי הרבה פעמים הוא {a['name']}, עם {a['n']:,} פריטים "
                f"({a['pct']} מהפריטים שיש להם יצרן מוגדר), ואחריו {b['name']} עם {b['n']:,}.{tail}")

    def i_concentration():
        if n_makers < 20:
            return None
        head = "הרשימה מפוזרת בין" if cum[9] / n_mk_rows < 0.4 else "הרשימה כוללת"
        return (f"{head} {n_makers:,} יצרנים: עשרת הגדולים מחזיקים "
                f"{_pct(cum[9], n_mk_rows)} מהפריטים, ו-{singles:,} יצרנים "
                f"({_pct(singles, n_makers)} מהיצרנים) מופיעים בפריט אחד בלבד.")

    def i_specialists():
        top = makers_rows[:STACK_MAKERS]
        if len(top) < 5:
            return None
        spec = [r for r in top if r["main_share"] >= SPECIALIST_SHARE]
        if len(spec) < 3:
            return None
        ex = fmt.join_he([f"{r['name']} ({r['main']})" for r in spec[:3]])
        return (f"{len(spec):,} מתוך {len(top):,} היצרנים הגדולים ברשימה מתמחים בסוג מוצר אחד, "
                f"שהוא {int(SPECIALIST_SHARE * 100)}% או יותר מהפריטים שלהם, למשל {ex}.")

    def _maker_bans_text():
        if len(maker_bans) <= 3:
            parts = [(f"כל הדגמים של {b['who']} מסוג {b['type']}" if b["what"] == "כל הדגמים"
                      else f"הדגם {b['what']} מסוג {b['type']} אצל כל היצרנים")
                     for b in maker_bans]
            return f"נוסף על כך נפסלו ברשימה {fmt.join_he(parts)}."
        return (f"עוד {len(maker_bans):,} שורות פוסלות את כל הדגמים של יצרן מסוים"
                f" או את כל היצרנים של דגם מסוים.")

    def i_bans():
        if not global_bans:
            return None
        names_he = fmt.join_he([b["type"] for b in global_bans[:6]])
        more = f" ועוד {len(global_bans) - 6:,}" if len(global_bans) > 6 else ""
        s = (f"{len(global_bans):,} סוגי מוצרים מופיעים ברשימה לכל היצרנים ולכל הדגמים, "
             f"כלומר אף פריט מסוגם לא אושר: {names_he}{more}.")
        if maker_bans:
            s += " " + _maker_bans_text()
        return s

    def i_repeats():
        if n_rep < 3:
            return None
        txt = (f"{n_rep:,} דגמים מופיעים ברשימה יותר מפעם אחת אצל אותו יצרן "
               f"(יחד {n_rep_rows:,} שורות).")
        if n_cross >= 3:
            txt += f" בנפרד מזה, {n_cross:,} קודי דגם מופיעים אצל יותר מיצרן אחד."
        return txt

    add("top_type", i_top_type())
    add("families", i_families())
    add("leader", i_leader())
    add("concentration", i_concentration())
    add("specialists", i_specialists())
    add("bans", i_bans())
    add("repeats", i_repeats())

    # ── text ────────────────────────────────────────────────────────
    t1 = tc.iloc[0]
    top_types_he = fmt.join_he(list(tc["he"].head(3)))
    summary = (f"רשימת משרד התקשורת של {total:,} פריטי ציוד אלחוטי שלא אושרו ליבוא אישי, "
               f"של {n_makers:,} יצרנים. הסוגים הנפוצים: {top_types_he}.")
    desc = (f"בדיקה אם מכשיר אלחוטי נדחה ליבוא אישי, לפי דגם, יצרן או סוג מוצר: "
            f"{total:,} פריטים של {n_makers:,} יצרנים.")
    if len(desc) > 150:
        desc = f"בדיקה אם מכשיר אלחוטי נדחה ליבוא אישי, לפי דגם, יצרן או סוג: {total:,} פריטים."

    top_mk1 = makers_rows[0] if makers_rows else None
    fam1 = fam_rank.iloc[0] if len(fam_rank) else None
    labels = {
        "kpi_total": "פריטים ברשימה",
        "kpi_makers": "יצרנים (אחרי איחוד איותים)",
        "kpi_types": "סוגי מוצרים",
        "kpi_bans": "סוגי מוצרים שנפסלו לכל היצרנים",
        "families_lede": (
            "כל סוג מוצר שויך לקבוצה לפי מילות מפתח בשמו. "
            + (f"הקבוצה הגדולה היא {fam1['family']}, עם {int(fam1['n']):,} פריטים "
               f"({_pct(int(fam1['n']), total)}). " if fam1 is not None else "")
            + (f"{n_other_family:,} פריטים שסוגם לא שויך לאף קבוצה מופיעים תחת אחר."
               if n_other_family else "")).strip(),
        "families_aria": (f"גרף עמודות אופקי: פריטים לפי קבוצת מוצרים, {len(family_rows):,} קבוצות"
                          + (f". הגדולה: {fam1['family']} עם {int(fam1['n']):,} פריטים."
                             if fam1 is not None else ".")),
        "types_lede": (
            f"{len(types_rows):,} סוגי המוצרים הנפוצים מתוך {n_types:,}. חמשת הראשונים הם "
            f"{_pct(top5_types, total)} מהרשימה. הסוגים נרשמו באנגלית ובכמה איותים, ולכן אוחדו "
            f"(אותיות גדולות, רווחים ותיקון שגיאות כתיב כמו TRANCIEVER): "
            f"{n_raw_types:,} כתיבים שונים הפכו ל-{n_types:,} סוגים."),
        "types_aria": (f"גרף עמודות אופקי: {len(types_rows):,} סוגי המוצרים הנפוצים ברשימה. "
                       f"מוביל: {t1['he']} עם {int(t1['n']):,} פריטים."),
        "makers_lede": (
            f"{len(makers_rows):,} היצרנים שמופיעים ברשימה הכי הרבה פעמים. שמות היצרנים אוחדו "
            f"(בלי הבדלי אותיות גדולות וקטנות, סימני פיסוק וסיומות כמו Ltd או Inc): "
            f"{n_raw_makers:,} כתיבים שונים הפכו ל-{n_makers:,} יצרנים. "
            + ((f"{n_all_makers_rows:,} שורות שחלות על כל היצרנים לא נכללו. "
                if n_all_makers_rows > 1 else "שורה אחת שחלה על כל היצרנים לא נכללה. ")
               if n_all_makers_rows else "")
            + ((f"{n_no_maker:,} שורות בלי שם יצרן (ריק או N/A) לא נכללו."
                if n_no_maker > 1 else "שורה אחת בלי שם יצרן (ריק או N/A) לא נכללה.")
               if n_no_maker else "")).strip(),
        "makers_aria": (f"גרף עמודות אופקי: {len(makers_rows):,} היצרנים עם הכי הרבה פריטים ברשימה. "
                        f"מוביל: {top_mk1['name']} עם {top_mk1['n']:,} פריטים.") if top_mk1 else "",
        "stack_lede": (f"אילו סוגי מוצרים נדחו אצל כל אחד מ-{len(top_mk):,} היצרנים הגדולים, "
                       f"לפי קבוצת מוצרים. "
                       + (f"אצל {n_fam_spec:,} מהם, {int(SPECIALIST_SHARE * 100)}% או יותר "
                          f"מהפריטים שייכים לקבוצה אחת."
                          if top_mk and n_fam_spec * 2 > len(top_mk)
                          else "לכל יצרן מוצגת החלוקה בין הקבוצות.")),
        "stack_aria": (f"גרף עמודות מוערמות: פריטים של {len(top_mk):,} היצרנים הגדולים "
                       f"לפי {len(stack_fams):,} קבוצות מוצרים."),
        "buckets_lede": (
            f"{singles:,} מתוך {n_makers:,} יצרנים מופיעים ברשימה בפריט אחד בלבד"
            + (f", ויחד הם {bucket_rows[0]['pct']} מהפריטים שיש להם יצרן מוגדר."
               if bucket_rows and bucket_rows[0]["name"] == BUCKETS[0][2] else ".")),
        "buckets_aria": (f"גרף עמודות: יצרנים ופריטים לפי מספר הפריטים של כל יצרן. "
                         f"{singles:,} יצרנים עם פריט אחד בלבד."),
        "bans_lede": (
            (f"{len(global_bans):,} סוגי מוצרים נפסלו לכל היצרנים ולכל הדגמים. " if global_bans else "")
            + (_maker_bans_text() if maker_bans else "")).strip(),
        "bans_more": (f"מוצגות {BANS_MAX:,} מתוך {n_ban_rows:,} השורות."
                      if n_ban_rows > BANS_MAX else ""),
    }

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "seo": {
            "title": "ציוד אלחוטי שלא אושר ליבוא אישי | רשימת משרד התקשורת",
            "description": desc,
            "name": "ציוד אלחוטי שלא אושר ליבוא אישי",
            "alternate_names": [
                "ציוד אלחוטי - פריטים ביבוא אישי שלא קיבלו אישור משרד התקשורת",
                "רשימת מכשירים אלחוטיים שנדחו ביבוא אישי",
                "ייבוא אישי של ציוד אלחוטי: פריטים שלא אושרו",
            ],
        },
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "families": family_chart,
            "types": types_chart,
            "makers": makers_chart,
            "stack": stack,
            "buckets": buckets_chart,
        },
        "insights": insights,
        "tables": {
            "families": [[r["name"], f"{r['n']:,}", r["pct"], f"{r['types']:,}", r["top"]]
                         for r in family_rows],
            "types": [[r["he"], r["en"], f"{r['n']:,}", r["pct"]] for r in types_rows],
            "makers": [[r["name"], f"{r['n']:,}", r["pct"], r["main"]] for r in makers_rows],
            "stack": [[names[k]] + [f"{int(sc.get((k, f), 0)):,}" for f in stack_fams]
                      for k in top_mk],
            "stack_cols": ["יצרן"] + stack_fams,
            "buckets": [[b["name"], f"{b['makers']:,}", f"{b['n']:,}", b["pct"]] for b in bucket_rows],
            "bans": ban_rows,
        },
        "labels": labels,
        "flags": {
            "has_makers": len(makers_rows) >= 2,
            "has_stack": has_stack,
            "has_buckets": n_makers >= 10,
            "has_bans": n_ban_rows > 0,
        },
    }
