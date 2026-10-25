"""מאגר לאומי לנוכחות נגעים בישראל — the Plant Protection and Inspection
Services' national register of plant pests and pathogens present in Israel.

One row = one pest (נגע): causal-agent group (arthropods, fungi, viruses,
molluscs, nematodes, bacteria …), its taxonomy (kingdom → genus), Hebrew and
English common names, EPPO code, synonyms, the author who described the
species (often with the year of description), a ";"-separated list of host
plants, literature, a handful of free-text biology/damage fields (almost all
empty) and an export timestamp (TRANSFER_DATE, the same on every row).

Host plants carry no group column, so they are mapped to the crop-group
labels of the sibling pesticide registry recipe (7a6cbf55, "קבוצת גידולים")
with a fixed host→group map plus keyword rules; anything unmapped (wild and
ornamental species added later) falls to "צמחים אחרים".

The upstream CSV export has a broken row now and then (a multi-line record
split in two: the tail lands in the wrong columns with an empty scientific
name). Rows without a scientific name are dropped and the lede says how many.
"""
import math
import re
import statistics

import pandas as pd

EPPO = "CODE_EPPO"
AGENT = "CASUAL_AGENT"
SCI = "SCIENTIFIC_NAME"
HE_NAME = "COMMON_NAMES_IN_HEBREW"
EN_NAME = "COMMON_NAMES_IN_ENGLISH"
FAMILY = "FAMILY"
CLASS = "CLASS"
ORDER = "ORDER"
PHYLUM = "PHYLUM"
GENUS = "GENUS"
KINGDOM = "KINGDOM"
SYN = "SYNONYMES"
ACR = "ACRONYMS"
PRESENT = "NEGA_IN_ISRAEL"
COMMENTS = "COMMENTS"
STATUS = "STATUS"
LIT_HE = "LITERATURE_AND_LINKS"
LIT_EN = "LITERATURE_AND_LINKS_E"
PEST_CODE = "PESTICIDES_CODE"
HOST_HE = "HOST_HEBREW_NAME"
HOST_BOT = "HOST_BOTANIC_NAME"
DESCRIBER = "NEGA_DESCRIBER"
TRANSFER = "TRANSFER_DATE"
BIO_COLS = ["SYMPTOMS", "SYMPTOMS_E", "PLANT_PARTS_AFFECTED", "PLANT_PARTS_AFFECTED_E",
            "DAMAGE", "DAMAGE_E", "BIOLOGY", "BIOLOGY_E", "ADDITIONAL_INFORMATION",
            "ADDITIONAL_INFORMATION_E"]

UNSPEC = "לא צוין"
OTHER = "אחר"
OTHER_HOSTS = "צמחים אחרים"
MIN_GROUP = 5        # pests a causal-agent group needs to keep its own bar (else "אחר")
MIN_NODE = 8         # pests a taxon needs to keep its own sunburst slice
TOP_ORDERS = 15
TOP_FAMILIES = 15
TOP_HOSTS = 15
STACK_GROUPS = 4     # agent groups drawn as their own stack in the hosts chart
TOP_POLY = 10
TOP_AUTH = 12
TOP_LIT = 8
MIN_YEARS = 30       # parsed description years needed for the era chart/insight
PERIOD = 25          # years per bar in the description-era chart
MIN_CMP_GROUP = 30   # pests a group needs to enter the completeness-gap insight
LRI, PDI = "⁦", "⁩"
PALETTE_ORDER = [0, 1, 2, 6, 5, 9, 7, 3]   # GOVIL_PALETTE indices that stay distinct when stacked

GROUP_ORDER = ["ירקות", "נשירים", "הדרים", "סובטרופים", "צמחי תבלין", "גידולי שדה",
               "גידולי תעשיה", "מספוא", "פרחים", "עצי יער", "צמחי מרפא", OTHER_HOSTS]

HOST_GROUP = {}
for _g, _hosts in {
    "ירקות": ["תפוח אדמה", "עגבניה", "מלפפון", "מלון", "כרוב", "אבטיח", "דלעת", "לופה",
              "קישוא", "פלפל", "תות שדה", "בצל הגינה", "לפופית הבטטה", "שום הגינה", "חציל",
              "גזר", "חסה", "צנון", "כרוב הסיני", "לפת", "קולורבי", "כרוב הגינה לבן",
              "כרובית", "שעועית", "כרפס/סלרי", "פול", "תרד", "אספרגוס", "קנרס תרבותי",
              "במיה", "אפונה", "גזר הגינה", "ברוקולי", "דלעת הדלורית", "ארטישוק ירושלמי",
              "שום גבוה", "תירס"],
    "נשירים": ["תאנה", "נקטרינה", "אפרסק", "גפן", "תפוח עץ", "רימון", "שקד מצוי",
               "זית אירופאי", "זית", "שזיף", "משמש", "אגס", "דובדבן", "דובדבן מתוק (גודגדן)",
               "חבוש", "חבוש מוארך", "חרוב מצוי", "ענבים", "אגס סורי", "אגס מצוי",
               "אגוז המלך", "פיסטוק", "שזיף יפני", "תות לבן", "נשירים"],
    "הדרים": ["הדרים", "לימון", "אשכולית", "תפוז", "קליפים", "פומלו", "אתרוג", "מנדרינה",
              "הדר התפוז"],
    "סובטרופים": ["אבוקדו", "בננה", "מנגו", "תמר", "תמר מצוי", "שסק", "שסק יפני",
                  "גויאבה", "פפאיה", "אנונה", "ליצ'י", "פסיפלורה", "פסיפלורה נאכלת",
                  "קיווי", "אפרסמון יפני", "מקדמיה"],
    "צמחי תבלין": ["כוסברה", "ריחן מצוי (בזיל)", "בזיל אדום", "עירית בצלית", "עירית שומית",
                   "פטרוזיליה", "פטרוזיליה מסולסלת", "מנטה", "נענע חריפה", "נענע משובלת",
                   "לענה דרקונית", "מרווה", "שמיר", "צתרה", "קורנית לימון", "טימין",
                   "מליסה", "סייגית", "מיורם", "רוזמרין", "ער אציל (עלי דפנה)",
                   "כמנון האניס", "לאושטיאן רפואי", "כרוב הלפת מיזונה"],
    "גידולי שדה": ["שעורה תרבותית", "שעורה", "חיטת הלחם", "חיטה", "חיטה קשה",
                   "חימצה תרבותית (חומוס)", "דורה", "שבולת שועל", "צבר", "בקיה תרבותית"],
    "גידולי תעשיה": ["אגוז אדמה", "כותנה", "חמנית מצויה", "חמנית", "סלק סוכר",
                     "סימונדסיית החוחובה", "חריע", "טבק", "פישתן", "שומשום", "קיקיון",
                     "קנה-סוכר גבוה"],
    "מספוא": ["אספסת תרבותית", "תלתן"],
    "פרחים": ["גרניום", "גבסנית", "עצבונית", "ציפורן", "ציפורן הקרנפול", "כלנית", "שושן",
              "נורית", "ליאטריס", "נץ החלב", "אמריליס", "אסקלפיאס", "פרח שעווה", "נרקיס",
              "אדמונית", "טרכליון", "ארליה", "דשא", "מטה-זהב", "כף קנגורו", "ורד", "פיקוס",
              "היביסקוס", "גרברה", "פטוניה", "דורבנית", "פיטוספורום יפני", "בגוניה",
              "פרוטאה", "יסמין", "נרינה", "לנטנה", "טופח ריחני", "בשמת", "יפעה (ליזיאנטוס)",
              "אסטר", "חרצית הגננים", "גזניה", "אסטילבה"],
    "עצי יער": ["אלון", "אקליפטוס", "אורן", "אורן קפריסאי", "אורן ירושלים", "ברוש",
                "אלה אטלנטית", "אלה ארץ-ישראלית", "אלת המסטיק", "אלה", "אשל", "שיטה",
                "צפצפה", "ערבה", "בוקיצה", "קזוארינה", "אדר", "דולב", "ערער"],
    "צמחי מרפא": ["קנביס", "קנבוס תרבותי"],
}.items():
    for _h in _hosts:
        HOST_GROUP[_h] = _g

HOST_KEYS = [("הדר", "הדרים"), ("כרוב", "ירקות"), ("חיטה", "גידולי שדה"),
             ("שעורה", "גידולי שדה"), ("אורן", "עצי יער"), ("אלון", "עצי יער"),
             ("שזיף", "נשירים"), ("אגס", "נשירים")]

COMPLETE_FIELDS = [
    ("he", "שם עברי"), ("en", "שם אנגלי"), ("eppo", "קוד EPPO"), ("host", "צמחי מאכסן"),
    ("syn", "שמות נרדפים"), ("desc", "מתאר המין"), ("lit", "מקור ספרותי"),
    ("code", "קוד הדברה"), ("acr", "ראשי תיבות"), ("bio", "תיאור נזק/ביולוגיה"),
    ("note", "הערות"),
]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def pct_plain(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def iso(name):
    return f"{LRI}{name}{PDI}"


def ranked(counts):
    """Descending by value, ties by label — a total, shuffle-proof order."""
    return counts.sort_index().sort_values(ascending=False, kind="stable")


def host_group(h):
    g = HOST_GROUP.get(h)
    if g:
        return g
    for key, grp in HOST_KEYS:
        if key in h:
            return grp
    return OTHER_HOSTS


def split_list(s):
    out = []
    for x in s.split(";"):
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return out


YEAR_RE = re.compile(r"(1[7-9]\d\d|20\d\d)")


def describer_year(s):
    m = YEAR_RE.findall(s)
    return int(m[-1]) if m else None


def authority(s):
    """'(Linnaeus; 1758)' → 'Linnaeus' — the author string without year/brackets."""
    a = YEAR_RE.sub("", s.replace("(", " ").replace(")", " "))
    a = re.sub(r"\s+", " ", a).strip(" ;,.")
    a = re.sub(r"\s*;\s*$", "", a)
    return a


def short(s, k=60):
    return s if len(s) <= k else s[:k - 1].rstrip() + "…"


def _prepare(df):
    cols = [EPPO, AGENT, SCI, HE_NAME, EN_NAME, FAMILY, CLASS, ORDER, PHYLUM, GENUS, KINGDOM,
            SYN, ACR, PRESENT, COMMENTS, STATUS, LIT_HE, LIT_EN, PEST_CODE, HOST_HE, HOST_BOT,
            DESCRIBER, TRANSFER] + BIO_COLS
    out = pd.DataFrame({c: df[c].astype(str).str.strip() for c in cols})
    raw = len(out)
    out = out[out[SCI] != ""].copy()
    out = out.sort_values([SCI, AGENT, FAMILY, HOST_HE, DESCRIBER], kind="stable").reset_index(drop=True)
    out["agent"] = out[AGENT].replace("", UNSPEC)
    sizes = out.groupby("agent").size()
    small = set(sizes[sizes < MIN_GROUP].index) | {UNSPEC}
    out["grp"] = out["agent"].where(~out["agent"].isin(small), OTHER)
    out["hosts"] = out[HOST_HE].map(split_list)
    out["n_hosts"] = out["hosts"].map(len)
    out["year"] = out[DESCRIBER].map(describer_year)
    out["auth"] = out[DESCRIBER].map(authority)
    return out, raw - len(out)


def group_order(df):
    g = ranked(df.groupby("grp").size())
    names = [x for x in g.index if x != OTHER] + ([OTHER] if OTHER in g.index else [])
    return names, g


# ── insight rules ──────────────────────────────────────────────────────────

def insight_dominance(df, grp_counts):
    total = len(df)
    top = grp_counts.index[0]
    if top == OTHER or grp_counts.iloc[0] / total < 0.5:
        return None
    sub = df[df["grp"] == top]
    cls = ranked(sub[sub[CLASS] != ""].groupby(CLASS).size())
    s = (f"קבוצת {top} היא רוב המאגר: {n(grp_counts.iloc[0])} מתוך {n(total)} הנגעים "
         f"({pct(grp_counts.iloc[0] / total)})")
    if len(cls) and cls.iloc[0] / len(sub) >= 0.5:
        s += (f", ובתוכם מחלקת {iso(cls.index[0])} לבדה מונה {n(cls.iloc[0])} "
              f"({pct(cls.iloc[0] / total)} מכלל הנגעים)")
    if len(grp_counts) > 1:
        s += f". במקום השני: קבוצת {grp_counts.index[1]} ({n(grp_counts.iloc[1])})"
    return s + "."


def insight_family(fam):
    if len(fam) < 2 or fam.iloc[0]["pests"] <= fam.iloc[1]["pests"]:
        return None
    a, b = fam.iloc[0], fam.iloc[1]
    return (f"המשפחה המגוונת ביותר במאגר היא {iso(a['family'])} ({a['grp']}) עם {n(a['pests'])} "
            f"נגעים ב-{n(a['genera'])} סוגים, ואחריה {iso(b['family'])} ({b['grp']}) "
            f"עם {n(b['pests'])}.")


def insight_genus(df):
    g = ranked(df[df[GENUS] != ""].groupby(GENUS).size())
    if len(g) < 2 or g.iloc[0] <= g.iloc[1] or g.iloc[0] < 5:
        return None
    grp = ranked(df[df[GENUS] == g.index[0]].groupby("grp").size()).index[0]
    single = int((g == 1).sum())
    return (f"הסוג {iso(g.index[0])} ({grp}) מיוצג במאגר ב-{n(g.iloc[0])} נגעים — יותר מכל סוג "
            f"אחר — בעוד {n(single)} מתוך {n(len(g))} הסוגים ({pct(single / len(g))}) "
            f"מיוצגים בנגע יחיד.")


def insight_hosts(df, host_counts):
    with_host = int((df["n_hosts"] > 0).sum())
    if len(host_counts) < 3 or with_host == 0:
        return None
    (h1, v1), (h2, v2), (h3, v3) = list(host_counts.items())[:3]
    if v1 <= v2:
        return None
    return (f"ל-{n(with_host)} נגעים ({pct(with_host / len(df))}) רשומים צמחי מאכסן. "
            f"המאכסן השכיח ביותר הוא {h1} ({n(v1)} נגעים), ואחריו {h2} ({n(v2)}) "
            f"ו{h3} ({n(v3)}).")


def insight_crop_group(cg_total, cg_lead):
    rows = [(g, v) for g, v in cg_total.items() if g != OTHER_HOSTS]
    if len(rows) < 2 or rows[0][1] <= rows[1][1]:
        return None
    g, v = rows[0]
    lead, lv = cg_lead[g]
    s = (f"מבין קבוצות הגידולים, ב{g} רשומים הכי הרבה נגעים — {n(v)}, לעומת {n(rows[1][1])} "
         f"ב{rows[1][0]}")
    if lv / v >= 0.4:
        s += f"; {pct(lv / v, 0)} מהם בקבוצת {lead}"
    return s + "."


def insight_poly(df):
    h = df[df["n_hosts"] > 0].sort_values(["n_hosts", SCI], ascending=[False, True], kind="stable")
    if len(h) < 20:
        return None
    top, second = h.iloc[0], h.iloc[1]
    if top["n_hosts"] <= second["n_hosts"]:
        return None
    single = int((h["n_hosts"] == 1).sum())
    he = f" ({top[HE_NAME]})" if top[HE_NAME] else ""
    return (f"טווח המאכסנים הרחב ביותר במאגר הוא של {iso(top[SCI])}{he} — {n(top['n_hosts'])} "
            f"צמחי מאכסן. מנגד, {n(single)} מתוך {n(len(h))} הנגעים שרשומים להם מאכסנים "
            f"({pct(single / len(h))}) מתועדים על מאכסן יחיד.")


def insight_era(df):
    y = df.dropna(subset=["year"])
    if len(y) < MIN_YEARS:
        return None
    years = sorted(int(v) for v in y["year"])
    med = statistics.median(years)
    pre = sum(1 for v in years if v < 1900)
    y0 = years[0]
    k0 = sum(1 for v in years if v == y0)
    tail = (f"המוקדם ביותר — {iso(y[y['year'] == y0].iloc[0][SCI])}, שתואר ב-{y0}" if k0 == 1
            else f"-{n(k0)} המוקדמים ביותר תוארו ב-{y0}")
    return (f"ל-{n(len(y))} נגעים רשומה גם שנת התיאור המדעי של המין. החציון הוא {int(med)}, "
            f"{pct(pre / len(y))} מהם תוארו לפני 1900, ו{tail}.")


def insight_authority(auth):
    if len(auth) < 2 or auth.iloc[0] <= auth.iloc[1] or auth.iloc[0] < 5:
        return None
    return (f"המתאר השכיח ביותר הוא {iso(auth.index[0])}, שתיאר {n(auth.iloc[0])} מהנגעים "
            f"שבמאגר, ואחריו {iso(auth.index[1])} ({n(auth.iloc[1])}).")


def insight_completeness(df, groups):
    rows = []
    for g in groups:
        sub = df[df["grp"] == g]
        if g == OTHER or len(sub) < MIN_CMP_GROUP:
            continue
        rows.append((float((sub[HE_NAME] != "").mean()), g, len(sub)))
    if len(rows) < 2:
        return None
    hi = max(rows, key=lambda r: (r[0], r[1]))
    lo = min(rows, key=lambda r: (r[0], r[1]))
    if hi[0] - lo[0] < 0.2:
        return None
    total = float((df[HE_NAME] != "").mean())
    return (f"רק ל-{pct(total)} מהנגעים יש שם עברי. הפער בין הקבוצות גדול: בקבוצת {hi[1]} "
            f"{pct(hi[0])}, ובקבוצת {lo[1]} {pct(lo[0])} בלבד (קבוצות עם {n(MIN_CMP_GROUP)} "
            f"נגעים לפחות).")


# ── compute ────────────────────────────────────────────────────────────────

def compute(frames):
    df, dropped = _prepare(frames["main"])
    total = len(df)
    groups, grp_counts = group_order(df)

    # Agent groups.
    fam_per_grp = df[df[FAMILY] != ""].groupby("grp")[FAMILY].nunique()
    host_share_grp = df.groupby("grp")["n_hosts"].apply(lambda s: float((s > 0).mean()))
    agents_chart = {"names": groups, "values": [int(grp_counts[g]) for g in groups]}
    agents_table = [{"name": g, "count": n(grp_counts[g]),
                     "share": pct_plain(grp_counts[g] / total),
                     "families": n(fam_per_grp.get(g, 0)),
                     "hosts": pct_plain(host_share_grp[g])} for g in groups]

    # Taxonomy sunburst: kingdom → phylum → class.
    def node_frame(sub, col):
        v = sub[col].replace("", UNSPEC)
        c = v.value_counts()
        keep = set(c[c >= MIN_NODE].index) - {UNSPEC}
        return v.where(v.isin(keep), OTHER)

    def build(sub, cols):
        if not cols:
            return []
        lab = node_frame(sub, cols[0])
        cnt = ranked(lab.groupby(lab).size())
        order = [x for x in cnt.index if x != OTHER] + ([OTHER] if OTHER in cnt.index else [])
        out = []
        for name in order:
            part = sub[lab == name]
            kids = build(part, cols[1:]) if name != OTHER else []
            node = {"name": name, "value": int(len(part))}
            if kids and not (len(kids) == 1 and kids[0]["name"] in (OTHER, UNSPEC)):
                node["children"] = kids
            out.append(node)
        return out

    sunburst = build(df, [KINGDOM, PHYLUM, CLASS])

    # Orders and families.
    od = df[df[ORDER] != ""]
    ord_counts = ranked(od.groupby(ORDER).size())
    ord_fams = od[od[FAMILY] != ""].groupby(ORDER)[FAMILY].nunique()
    ord_grp = (od.groupby([ORDER, "grp"]).size().reset_index(name="k")
               .sort_values([ORDER, "k", "grp"], ascending=[True, False, True], kind="stable")
               .drop_duplicates(ORDER).set_index(ORDER)["grp"])
    top_ord = list(ord_counts.head(TOP_ORDERS).index)
    orders_chart = {"names": top_ord, "values": [int(ord_counts[o]) for o in top_ord],
                    "groups": [ord_grp[o] for o in top_ord], "legend": groups}
    orders_table = [{"name": o, "group": ord_grp[o], "pests": n(ord_counts[o]),
                     "families": n(ord_fams.get(o, 0))} for o in top_ord]

    fd = df[df[FAMILY] != ""]
    fam_counts = fd.groupby(FAMILY).size()
    fam_gen = fd[fd[GENUS] != ""].groupby(FAMILY)[GENUS].nunique()
    fam_grp = (fd.groupby([FAMILY, "grp"]).size().reset_index(name="k")
               .sort_values([FAMILY, "k", "grp"], ascending=[True, False, True], kind="stable")
               .drop_duplicates(FAMILY).set_index(FAMILY)["grp"])
    fam = pd.DataFrame({"family": fam_counts.index, "pests": fam_counts.values})
    fam["genera"] = fam["family"].map(lambda f: int(fam_gen.get(f, 0)))
    fam["grp"] = fam["family"].map(fam_grp)
    fam = fam.sort_values(["pests", "family"], ascending=[False, True], kind="stable").reset_index(drop=True)
    top_fam = fam.head(TOP_FAMILIES)
    families_chart = {"names": list(top_fam["family"]), "values": [int(v) for v in top_fam["pests"]],
                      "genera": [int(v) for v in top_fam["genera"]]}
    families_table = [{"name": r["family"], "group": r["grp"], "pests": n(r["pests"]),
                       "genera": n(r["genera"])} for _, r in top_fam.iterrows()]

    # Hosts (exploded once).
    ex = df[["grp", SCI, "hosts"]].explode("hosts").dropna(subset=["hosts"])
    ex = ex.rename(columns={"hosts": "host"})
    host_counts = ranked(ex.groupby("host").size())
    top_hosts = list(host_counts.head(TOP_HOSTS).index)
    host_grp = ranked(ex.groupby("grp")[SCI].nunique())
    stack = [g for g in host_grp.index if g != OTHER][:STACK_GROUPS]
    ex["sg"] = ex["grp"].where(ex["grp"].isin(stack), OTHER)
    hg = ex[ex["host"].isin(top_hosts)].groupby(["host", "sg"]).size()
    stack_names = stack + ([OTHER] if (ex["sg"] == OTHER).any() else [])
    hosts_chart = {"names": top_hosts,
                   "series": [{"name": s, "data": [int(hg.get((h, s), 0)) for h in top_hosts]}
                              for s in stack_names]}
    host_lead = (ex.groupby(["host", "grp"]).size().reset_index(name="k")
                 .sort_values(["host", "k", "grp"], ascending=[True, False, True], kind="stable")
                 .drop_duplicates("host").set_index("host"))
    hosts_table = [{"name": h, "pests": n(host_counts[h]), "group": host_lead.loc[h, "grp"],
                    "group_n": n(host_lead.loc[h, "k"]), "cgroup": host_group(h)} for h in top_hosts]
    n_hosts_distinct = int(len(host_counts))

    # Crop group × agent group (distinct pests per cell).
    ex["cg"] = ex["host"].map(host_group)
    cgp = ex[[SCI, "grp", "cg"]].drop_duplicates()
    cg_total = cgp.groupby("cg")[SCI].nunique()
    cg_rows = sorted(cg_total.index, key=lambda g: (GROUP_ORDER.index(g) if g in GROUP_ORDER
                                                    else len(GROUP_ORDER), g))
    cg_rows = [g for g in cg_rows if g != OTHER_HOSTS] + ([OTHER_HOSTS] if OTHER_HOSTS in cg_rows else [])
    cgc = cgp.groupby(["cg", "grp"])[SCI].nunique()
    heat_cols = [g for g in groups if any(cgc.get((r, g), 0) for r in cg_rows)]
    cells, heat_table, hmax = [], [], 0
    for yi, r in enumerate(cg_rows):
        row = []
        for xi, g in enumerate(heat_cols):
            v = int(cgc.get((r, g), 0))
            hmax = max(hmax, v)
            cells.append([xi, yi, v])
            row.append(n(v))
        heat_table.append({"name": r, "cells": row, "total": n(cg_total[r])})
    heat_chart = {"x": heat_cols, "y": cg_rows, "cells": cells, "max": hmax}
    cg_ranked = ranked(cg_total)
    cg_lead = {}
    for g in cg_ranked.index:
        sub = ranked(pd.Series({c: int(cgc.get((g, c), 0)) for c in heat_cols}))
        cg_lead[g] = (sub.index[0], int(sub.iloc[0]))

    # Host breadth (polyphagy).
    hp = df[df["n_hosts"] > 0]
    bins = [(1, 1, "1"), (2, 2, "2"), (3, 5, "3–5"), (6, 10, "6–10"), (11, 20, "11–20"),
            (21, math.inf, "מעל 20")]
    poly_names, poly_vals, poly_table = [], [], []
    for lo, hi, lab in bins:
        k = int(((hp["n_hosts"] >= lo) & (hp["n_hosts"] <= hi)).sum())
        poly_names.append(lab)
        poly_vals.append(k)
        poly_table.append({"name": lab, "count": n(k),
                           "share": pct_plain(k / len(hp)) if len(hp) else "0.0%"})
    poly_chart = {"names": poly_names, "values": poly_vals}
    tp = hp.sort_values(["n_hosts", SCI], ascending=[False, True], kind="stable").head(TOP_POLY)
    poly_top = [{"sci": r[SCI], "he": r[HE_NAME] or "—", "group": r["grp"],
                 "hosts": n(r["n_hosts"])} for _, r in tp.iterrows()]

    # Description era.
    yd = df.dropna(subset=["year"])
    era_chart = None
    era_table = []
    if len(yd) >= MIN_YEARS:
        y0 = int(yd["year"].min()) // PERIOD * PERIOD
        y1 = int(yd["year"].max())
        names, vals = [], []
        for s in range(y0, y1 + 1, PERIOD):
            k = int(((yd["year"] >= s) & (yd["year"] < s + PERIOD)).sum())
            names.append(f"{s}–{s + PERIOD - 1}")
            vals.append(k)
            era_table.append({"name": f"{s}–{s + PERIOD - 1}", "count": n(k)})
        era_chart = {"names": names, "values": vals}
    n_years = int(len(yd))

    # Authorities.
    au = df[df["auth"] != ""]
    auth = ranked(au.groupby("auth").size())
    top_auth = list(auth.head(TOP_AUTH).index)
    auth_chart = {"names": top_auth, "values": [int(auth[a]) for a in top_auth]}
    auth_first = yd.groupby("auth")["year"].min()
    auth_table = [{"name": a, "count": n(auth[a]),
                   "first": str(int(auth_first[a])) if a in auth_first.index else "—"}
                  for a in top_auth]

    # Completeness (share of pests with each field filled), by agent group.
    flags = pd.DataFrame({
        "he": df[HE_NAME] != "", "en": df[EN_NAME] != "", "eppo": df[EPPO] != "",
        "host": (df[HOST_HE] != "") | (df[HOST_BOT] != ""), "syn": df[SYN] != "",
        "desc": df[DESCRIBER] != "", "lit": (df[LIT_EN] != "") | (df[LIT_HE] != ""),
        "code": df[PEST_CODE] != "", "acr": df[ACR] != "",
        "bio": (df[BIO_COLS] != "").any(axis=1), "note": df[COMMENTS] != "",
    })
    flags["grp"] = df["grp"]
    by_g = flags.groupby("grp").mean()
    overall = flags.drop(columns="grp").mean()
    comp_groups = [g for g in groups if g != OTHER]
    comp_cols = comp_groups + ["כלל המאגר"]
    comp_cells, comp_table = [], []
    for yi, (key, label) in enumerate(COMPLETE_FIELDS):
        row = []
        for xi, g in enumerate(comp_cols):
            v = float(overall[key]) if xi == len(comp_groups) else float(by_g.loc[g, key])
            comp_cells.append([xi, yi, round(v * 100, 1)])
            row.append(pct_plain(v))
        comp_table.append({"name": label, "cells": row})
    complete_chart = {"x": comp_cols, "y": [lab for _, lab in COMPLETE_FIELDS], "cells": comp_cells}

    # Literature sources.
    lit = df[LIT_EN].where(df[LIT_EN] != "", df[LIT_HE])
    lit = lit[lit != ""]
    lit_counts = ranked(lit.groupby(lit).size())
    lit_table = [{"name": short(s, 110), "count": n(v), "share": pct_plain(v / total)}
                 for s, v in lit_counts.head(TOP_LIT).items()]
    n_lit = int(len(lit))

    # KPIs.
    with_host = int((df["n_hosts"] > 0).sum())
    he_share = float((df[HE_NAME] != "").mean())
    eppo_share = float((df[EPPO] != "").mean())
    host_share = with_host / total

    def share_tone(v):
        return "ok" if v >= 0.8 else ("warn" if v < 0.5 else "brand")

    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "groups": {"value": len(groups), "display": n(len(groups)), "tone": "brand"},
        "hosts": {"value": n_hosts_distinct, "display": n(n_hosts_distinct), "tone": "brand"},
        "host_share": {"value": round(host_share, 4), "display": pct_plain(host_share),
                       "tone": share_tone(host_share)},
        "he_share": {"value": round(he_share, 4), "display": pct_plain(he_share),
                     "tone": share_tone(he_share)},
        "eppo_share": {"value": round(eppo_share, 4), "display": pct_plain(eppo_share),
                       "tone": share_tone(eppo_share)},
    }

    # Lede.
    present = int((df[PRESENT].str.upper() == "YES").sum())
    active = int((df[STATUS] == "פעיל").sum())
    ts = pd.to_datetime(df[TRANSFER], errors="coerce", format="%d/%m/%Y %H:%M").dropna()
    asof = ts.max().strftime("%d.%m.%Y") if len(ts) else None
    lede = (f"המאגר מונה {n(total)} נגעים — מזיקים ופתוגנים של צמחים — ב-{n(len(groups))} "
            f"קבוצות של גורמי נזק, עם סיווג טקסונומי, שמות עבריים ואנגליים, קודי EPPO, "
            f"צמחי מאכסן ומקורות ספרותיים.")
    if present == total and active == total:
        lede += " כל הרשומות מסומנות כנוכחות בישראל וכפעילות."
    else:
        lede += (f" {n(present)} מהרשומות מסומנות כנוכחות בישראל ו-{n(active)} "
                 f"כפעילות.")
    if asof:
        lede += f" הנתונים נכונים ל-{asof}."
    if dropped == 1:
        lede += " רשומה שבורה אחת ללא שם מדעי בקובץ המקור הושמטה."
    elif dropped:
        lede += f" {n(dropped)} רשומות שבורות ללא שם מדעי בקובץ המקור הושמטו."

    insights = []
    for iid, txt in [
        ("dominance", insight_dominance(df, grp_counts)),
        ("family", insight_family(fam)),
        ("genus", insight_genus(df)),
        ("hosts", insight_hosts(df, host_counts)),
        ("crop-group", insight_crop_group(cg_ranked, cg_lead)),
        ("poly", insight_poly(df)),
        ("era", insight_era(df)),
        ("authority", insight_authority(auth)),
        ("completeness", insight_completeness(df, groups)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    top_grp = groups[0]
    labels = {
        "lede": lede,
        "agents_note": (f"קבוצת {top_grp} מובילה עם {n(grp_counts[top_grp])} נגעים "
                        f"({pct(grp_counts[top_grp] / total)}). קבוצות עם פחות מ-{n(MIN_GROUP)} "
                        f"נגעים או ללא סיווג מקובצות תחת „{OTHER}”."),
        "agents_aria": f"מספר הנגעים לפי קבוצת גורם הנזק, {n(len(groups))} קבוצות",
        "agents_caption": "נגעים לפי קבוצת גורם הנזק",
        "tax_note": (f"ממלכה ← מערכה ← מחלקה, לפי הסיווג במאגר. טקסונים עם פחות מ-{n(MIN_NODE)} "
                     f"נגעים מקובצים תחת „{OTHER}”. לחיצה על פלח מתמקדת בו."),
        "tax_aria": f"היררכיה טקסונומית של {n(total)} הנגעים: ממלכה, מערכה ומחלקה",
        "orders_note": (f"{n(TOP_ORDERS)} הסדרות עם מספר הנגעים הרב ביותר, מתוך "
                        f"{n(len(ord_counts))} סדרות במאגר. הצבע מציין את קבוצת גורם הנזק."),
        "orders_aria": f"{n(len(top_ord))} הסדרות המובילות לפי מספר נגעים",
        "orders_caption": "הסדרות המובילות",
        "families_note": (f"{n(TOP_FAMILIES)} המשפחות המובילות מתוך {n(len(fam))}; לצד מספר "
                          f"הנגעים — מספר הסוגים השונים בכל משפחה."),
        "families_aria": f"{n(len(top_fam))} המשפחות המובילות לפי מספר נגעים",
        "families_caption": "המשפחות המובילות",
        "hosts_note": (f"{n(TOP_HOSTS)} צמחי המאכסן שבהם רשומים הכי הרבה נגעים, מתוך "
                       f"{n(n_hosts_distinct)} מאכסנים שונים; ל-{n(with_host)} נגעים "
                       f"({pct(host_share)}) רשום מאכסן אחד לפחות."),
        "hosts_aria": f"{n(len(top_hosts))} צמחי המאכסן המובילים לפי מספר נגעים, לפי קבוצת גורם",
        "hosts_caption": "צמחי המאכסן המובילים",
        "heat_note": ("מספר הנגעים השונים בכל קבוצת גידולים, לפי גורם הנזק. המאכסנים ממופים "
                      "לקבוצות הגידולים של מאגר חומרי ההדברה; מאכסנים שאינם ממופים — "
                      f"צמחי בר, נוי ואחרים — מקובצים תחת „{OTHER_HOSTS}”. נגע עם כמה "
                      "מאכסנים באותה קבוצה נספר בה פעם אחת."),
        "heat_aria": f"מפת חום: נגעים לפי {n(len(cg_rows))} קבוצות גידולים ו-{n(len(heat_cols))} קבוצות גורם",
        "heat_caption": "נגעים לפי קבוצת גידולים וגורם נזק",
        "poly_note": (f"בכמה צמחי מאכסן רשום כל נגע, מבין {n(len(hp))} הנגעים שרשום להם "
                      f"מאכסן אחד לפחות."),
        "poly_aria": "התפלגות מספר צמחי המאכסן לנגע",
        "poly_caption": "נגעים לפי מספר צמחי מאכסן",
        "poly_top_caption": f"{n(len(poly_top))} הנגעים עם טווח המאכסנים הרחב ביותר",
        "era_note": (f"שנת התיאור המדעי מתוך שם המתאר, בתקופות של {n(PERIOD)} שנה; ידועה "
                     f"ל-{n(n_years)} נגעים ({pct(n_years / total)})."),
        "era_aria": f"התפלגות שנת התיאור המדעי של {n(n_years)} נגעים",
        "era_caption": "נגעים לפי תקופת התיאור המדעי",
        "auth_note": (f"{n(TOP_AUTH)} המתארים השכיחים — החוקרים שתיארו את המין לראשונה — "
                      f"מבין {n(len(au))} נגעים שהמתאר שלהם רשום."),
        "auth_aria": f"{n(len(top_auth))} המתארים השכיחים לפי מספר נגעים",
        "auth_caption": "המתארים השכיחים",
        "complete_note": ("שיעור הנגעים שבהם כל שדה מלא, לפי קבוצת גורם הנזק ובכלל המאגר "
                          f"(הקבוצה „{OTHER}” נכללת רק בכלל המאגר). "
                          "שדות התיאור (תסמינים, נזק, ביולוגיה, חלקי צמח) כמעט ריקים."),
        "complete_aria": f"מפת חום: שיעור מילוי של {n(len(COMPLETE_FIELDS))} שדות לפי קבוצת גורם",
        "complete_caption": "שיעור מילוי השדות לפי קבוצה",
        "lit_note": (f"המקורות הספרותיים הנפוצים במאגר; ל-{n(n_lit)} נגעים ({pct(n_lit / total)}) "
                     f"רשום מקור."),
        "lit_caption": "המקורות הספרותיים הנפוצים",
    }

    return {
        "agent_data": {
            "summary_he": (f"המאגר הלאומי של השירותים להגנת הצומח לנגעים הנוכחים בישראל: "
                           f"{n(total)} מזיקים ופתוגנים של צמחים, מהם {n(grp_counts[top_grp])} "
                           f"בקבוצת {top_grp}, עם סיווג טקסונומי ו-{n(n_hosts_distinct)} צמחי מאכסן "
                           f"רשומים."),
            "dataset_kind": "registry",
            "related_ids": ["7a6cbf55-8178-4d40-8613-a38909c7e96f",
                            "a11eddd8-8288-4a10-a991-76d65df3e6eb",
                            "bff9b8b5-0e09-47f5-8b84-c1a853a7ebc5",
                            "b4c32de1-627c-4b93-8d20-e58f6d44f733",
                            "4faf5604-c98f-45eb-bb9e-e0c4fe1c9c69"],
            "suggested_tags": ["הגנת הצומח", "מזיקים", "מחלות צמחים", "נגעים", "חקלאות",
                               "טקסונומיה"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "pal": PALETTE_ORDER,
            "agents": agents_chart,
            "tax": sunburst,
            "orders": orders_chart,
            "families": families_chart,
            "hosts": hosts_chart,
            "heat": heat_chart,
            "poly": poly_chart,
            "era": era_chart,
            "auth": auth_chart,
            "complete": complete_chart,
        },
        "tables": {
            "agents": agents_table,
            "orders": orders_table,
            "families": families_table,
            "hosts": hosts_table,
            "heat_cols": heat_cols,
            "heat": heat_table,
            "poly": poly_table,
            "poly_top": poly_top,
            "era": era_table,
            "auth": auth_table,
            "complete_cols": comp_cols,
            "complete": comp_table,
            "lit": lit_table,
        },
        "insights": insights,
        "labels": labels,
    }
