"""רשימת חקלאים ללא חשש פרי ערלה — the Chief Rabbinate's list of growers whose
fruit is approved as free of orla concern (פירות ערלה — fruit of a tree's first
three years).

One row per approved (grower, locality, fruit/variety) line (~7.6k): locality,
grower/farm name, fruit or variety, the Rabbinate inspector who checked it, a
note (רבעי / דו שנתי ...), the approval's validity (a fixed date, or "N
months from the inspection") and — for some rows — the inspection date. The
whole list is replaced in place on each update (same resource id), so the page
is a snapshot.

Naming: growers are commercial (farms, wineries, kibbutzim, sole traders) and
the inspectors are Rabbinate officials — both may be named. The data carries
no ID numbers or phones; nothing else personal reaches the page.

Data handling (disclosed in the copy):
- exact duplicate rows are dropped;
- a grower is (name, locality);
- the fruit column mixes species ("תמר", "זית") and varieties ("מרלו",
  "אטינגר/האס", "ניוהול"). A fixed name map groups them into crop families;
  names it doesn't know stay "לא מסווג" and the classified share is stated;
- the reference date for "expired" is the latest inspection date in the list
  (never the clock).
"""
import math
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
UNCLASSIFIED = "לא מסווג"
OTHER = "אחר"
NOT_GIVEN = "לא צוין"
TOP_VARIETIES = 15
TOP_LOCALITIES = 15
TOP_GROWERS = 10
TOP_INSPECTORS = 12
TOP_FAM_STACK = 6
TOP_NOTES = 6
TREE_PER_FAM = 8
MAX_MONTHS = 24

# --- crop-family map ---------------------------------------------------------
# Avocado varieties appear alone or as "/"-joined mixed-orchard lists.
AVO = {"אטינגר", "אטינג", "האס", "ריד", "פינקרטון", "פינקרון", "פינקריטון", "פינקר", "ארד", "גליל",
       "BL", "BL-122", "ג'ם", "ארדיט", "פוארטה", "מלומה", "נאבל", "חורשים", "דאי", "טיג", "מוזס",
       "מוסה", "לביא", "עירית", "אירית", "מוטי", "ניר", "אורית", "וורץ", "הרווסט", "נילי", "בניק",
       "שילר", "מאיו", "חרות", "אורי", "כרמון", "נגב", "הר", "זרעים"}
AVO_NOT_ALONE = {"ניר", "אורי", "הר", "זרעים", "נגב"}
CITRUS_SUB = ["לימון", "ליים", "אשכולית", "פומלו", "פומלית", "פומלה", "תפוז", "קלמנטינה", "ולנסיה",
              "שמוטי", "ריו ראד", "סטאר רובי", "מנאולה", "מורקוט", "ראוסטנברג", "סצומה", "קומקואט",
              "קומקווט", "לימקואט", "אתרוג", "יוזו", "קרה קרה", "סנרייז", "ניוהול", "סמרגולד",
              "סאמר גולד", "גלנברג", "גלנורה"]
CITRUS_EXACT = {"מארש", "מיכל", "אור", "אורה", "אורה שני", "אודם", "מירב", "טמפל", "מור", "נאור",
                "יפעת", "סמי", "רדסון", "ציפי", "טבורי", "צ'נדלר", "צנדלר", "סנטינה", "מורו", "עידית",
                "עינב", "טופז", "עליזה", "סיגל"}
GRAPE_SUB = ["מרלו", "קברנה", "ורדו", "שירז", "סירה", "קארניאן", "שרדונה", "שנן בלאן", "סובניון",
             "סוביניון", "גראנש", "גרנאש", "ויוניה", "ויונייה", "גוורצטרימר", "גבורץ", "מלבק", "ברברה",
             "ריזלינג", "מורבדרה", "סמיון", "טמפרניו", "טמפריו", "טמפרניליו", "ארגמן", "רוסאן", "רוסן",
             "מרסלן", "מרסלאן", "מרסן", "מרסאן", "קולומבר", "קולובמבר", "פינו נואר", "פינו גרי",
             "פינטה גריי", "מוסקט", "טאנאט", "טנאט", "טאנט", "סנג'ובזה", "סנגובזה", "אליקנט", "אסרטיקו",
             "נביולו", "זינפנדל", "דולצ'טו", "דולצטו", "דולקטו", "ורדלו", "ורדליו", "סינסו", "סנסו",
             "סנסאו", "סאנסו", "מקאבו", "מקבאו", "קלאדוק", "קלדוק", "קאלדוק", "טוריגה", "קרימסון",
             "רד גלוב", "סוויט גלוב", "אוטם רויאל", "אוטם בלק", "שוגר קריספ", "שוגר-קריספ", "מידנייט",
             "מדנייט", "קוטון קנדי", "קותון קנדי", "כותן קנדי", "סלבריישן", "סליברשיין", "סילברשיין",
             "ביג פרל", "תומפסון", "טומפסון", "טימפסון", "סוויט סל", "פרנץ", "ג1", "רד לוש", "מיסטיק",
             "מיסטרי", "האני פופ", "האני פוס", "פינוטז'", "קונקורד", "איזבלה", "סייבל", "רגנט", "ARRA"]
FAMILY_WORDS = [
    ("נשירים", ["נקטרינה", "אפרסק", "משמש", "שזיף", "דובדבן", "תפוח", "אגס", "חבוש", "אפרסמון"]),
    ("תמר", ["תמר", "חלואני", "חלוואני"]),
    ("זית", ["זית"]),
    ("מנגו", ["מנגו"]),
    ("רימון", ["רימון"]),
    ("טרופיים וסובטרופיים", ["ליצ'י", "ליצי", "לונגן", "אנונה", "גויאבה", "פיטאיה", "קרמבולה", "ספודילה",
                             "פיג'ויה", "ג'בוטיקבה", "קניסטל", "ג'ק פרוט", "אצרולה", "ספוטה", "תפוח מים",
                             "פסיפלורה", "פפאיה", "אמברלה", "גואנבנה", "גרגר פנמה", "וומפי",
                             "ימבולנה", "פיטנגו", "שעועית הגלידה"]),
    ("פירות ואגוזים אחרים", ["תאנה", "פקאן", "אוכמניות", "צבר", "תות", "שקד", "פיסטוק", "מקדמיה", "חרוב",
                             "פטל", "דומדמניות", "גוג'י", "שסק", "קיווי", "שיזף"]),
]
FAMILY_ORDER = ["ענבים", "נשירים", "אבוקדו", "הדרים", "תמר", "זית", "מנגו", "רימון",
                "טרופיים וסובטרופיים", "פירות ואגוזים אחרים"]
FAMILY_LABEL = {"נשירים": "נשירים (גלעיניים ותפוחים)"}
FAMILY_COLORS = {"ענבים": "#0068f5", "נשירים": "#0b3668", "אבוקדו": "#6c9fd8", "הדרים": "#0053c4",
                 "תמר": "#3d70b0", "זית": "#0c3058", "מנגו": "#b7d2f7", "רימון": "#2658a0",
                 "טרופיים וסובטרופיים": "#8fb6ea", "פירות ואגוזים אחרים": "#0c1f3d",
                 UNCLASSIFIED: "#6c757d", OTHER: "#6c757d"}
LIGHT_COLORS = {"#6c9fd8", "#b7d2f7", "#8fb6ea"}
SPLIT_RE = re.compile(r"[/\\]")
MONTHS_RE = re.compile(r"(\d+)\s*חודש")


def classify(name):
    s = name.strip()
    if not s:
        return UNCLASSIFIED
    if "אבוקדו" in s:
        return "אבוקדו"
    if "ענב" in s and "קלמנטינה" not in s and s != "עינב":
        return "ענבים"
    toks = [t.strip() for t in SPLIT_RE.split(s) if t.strip()]
    if toks and all(t in AVO for t in toks) and not (len(toks) == 1 and toks[0] in AVO_NOT_ALONE):
        return "אבוקדו"
    if toks and all(t in CITRUS_EXACT or any(w in t for w in CITRUS_SUB) for t in toks):
        return "הדרים"
    if s in CITRUS_EXACT or any(w in s for w in CITRUS_SUB):
        return "הדרים"
    for fam, words in FAMILY_WORDS:
        if any(s == w or s.startswith(w) for w in words):
            if fam == "נשירים" and s.startswith("תפוח מים"):
                continue
            return fam
    if any(w in s for w in GRAPE_SUB):
        return "ענבים"
    return UNCLASSIFIED


# --- formatting ----------------------------------------------------------------
def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def pct_bare(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def dmy(ts):
    return ts.strftime("%d.%m.%Y")


HE_MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר",
             "אוקטובר", "נובמבר", "דצמבר"]


def month_label(p):
    return f"{HE_MONTHS[p.month - 1]} {p.year}"


def ranked(s):
    """Value counts sorted by count desc, then key asc (total order)."""
    s = s.sort_index(kind="stable")
    return s.sort_values(ascending=False, kind="stable")


def fam_label(f):
    return FAMILY_LABEL.get(f, f)


# --- prep ------------------------------------------------------------------------
def _prepare(raw):
    df = raw[["locality", "manufacturer", "fruits", "checked", "notes", "validity", "date"]].copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    dupes = before - len(df)
    df = df[(df["manufacturer"] != "") | (df["fruits"] != "")].reset_index(drop=True)
    df["locality"] = df["locality"].where(df["locality"] != "", NOT_GIVEN)
    df["checked"] = df["checked"].where(df["checked"] != "", NOT_GIVEN)
    df["grower"] = df["manufacturer"] + " (" + df["locality"] + ")"
    df["family"] = df["fruits"].map(classify)
    df["insp"] = pd.to_datetime(df["date"], format="%d/%m/%Y", errors="coerce")
    fixed = pd.to_datetime(df["validity"], format="%d/%m/%Y", errors="coerce")
    months = pd.to_numeric(df["validity"].str.extract(MONTHS_RE)[0], errors="coerce")
    rel = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    mask = months.notna() & df["insp"].notna()
    for m in sorted(months[mask].unique()):
        sel = mask & (months == m)
        rel[sel] = df.loc[sel, "insp"] + pd.DateOffset(months=int(m))
    df["expiry"] = fixed.where(fixed.notna(), rel)
    df["relative"] = months.notna()
    df["validity"] = df["validity"].where(df["validity"] != "", NOT_GIVEN)
    return df, dupes


# --- insights ----------------------------------------------------------------------
def insight_family(fam_rows, fam_growers, total, n_growers, classified_share):
    named = fam_rows.drop(UNCLASSIFIED, errors="ignore")
    if named.empty:
        return None
    top = named.index[0]
    share = named.iloc[0] / total
    if share < 0.2:
        return None
    second = named.index[1] if len(named) > 1 else None
    txt = (f"קבוצת הגידול הגדולה ברשימה היא {fam_label(top)}: {n(named.iloc[0])} שורות זן "
           f"({pct(share)}) אצל {n(fam_growers.get(top, 0))} מגדלים מתוך {n(n_growers)}")
    if second is not None:
        txt += (f"; אחריהם {fam_label(second)} עם {n(named.iloc[1])} שורות "
                f"אצל {n(fam_growers.get(second, 0))} מגדלים")
    txt += f". (הקבוצות סווגו לפי שם הזן; {pct(classified_share)} מהשורות סווגו.)"
    return txt


def insight_grapes(df):
    g = df[df["family"] == "ענבים"]
    if len(g) < 50:
        return None
    v = ranked(g["fruits"].value_counts())
    locs = ranked(g["locality"].value_counts())
    names = ", ".join(f"{k} ({n(c)})" for k, c in v.head(3).items())
    return (f"בענבים רשומים {n(g['fruits'].nunique())} שמות זן שונים אצל {n(g['grower'].nunique())} מגדלים — "
            f"המובילים {names}. היישוב עם מירב שורות הענבים הוא {locs.index[0]} ({n(locs.iloc[0])}).")


def insight_concentration(loc_rows, total):
    k = len(loc_rows)
    if k < 20:
        return None
    top10 = loc_rows.head(10).sum() / total
    singles = int((loc_rows == 1).sum())
    lead = ("אך עשרת היישובים המובילים מרכזים" if top10 >= 0.3 else
            "והפיזור רחב: עשרת היישובים המובילים מרכזים רק")
    return (f"האישורים פרוסים על {n(k)} יישובים, {lead} {pct(top10)} מהשורות; "
            f"בראשם {loc_rows.index[0]} ({n(loc_rows.iloc[0])}) ו{loc_rows.index[1]} ({n(loc_rows.iloc[1])}). "
            f"ב-{n(singles)} יישובים רשומה שורת זן אחת בלבד.")


def insight_top_locality(df, loc_rows):
    if loc_rows.empty:
        return None
    best = None
    for loc in loc_rows.head(5).index:
        sub = df[df["locality"] == loc]
        fc = ranked(sub["family"].value_counts()).drop(UNCLASSIFIED, errors="ignore")
        if fc.empty:
            continue
        share = fc.iloc[0] / len(sub)
        if share >= 0.6 and (best is None or share > best[2]):
            best = (loc, fc.index[0], share, len(sub), sub["grower"].nunique())
    if best is None:
        return None
    loc, fam, share, rows, growers = best
    return (f"חלק מהיישובים המובילים מתמחים בגידול אחד: ב{loc} ({n(rows)} שורות, {n(growers)} מגדלים) "
            f"{pct(share)} מהשורות הן {fam_label(fam)}.")


def insight_growers(per_grower, top_name, top_count):
    g = len(per_grower)
    if g < 20:
        return None
    single = (per_grower == 1).sum() / g
    med = float(per_grower.median())
    med_s = f"{med:.1f}".rstrip("0").rstrip(".")
    big = int((per_grower >= 10).sum())
    return (f"רוב המגדלים קטנים ברשימה: לחציון המגדלים {med_s} שורות זן, ול-{pct(single)} שורה אחת בלבד. "
            f"{n(big)} מגדלים רשומים עם עשר שורות או יותר; בראשם {top_name} עם {n(top_count)}.")


def insight_inspectors(insp_rows, total):
    real = insp_rows.drop(NOT_GIVEN, errors="ignore")
    if len(real) < 2:
        return None
    s1 = real.iloc[0] / total
    if s1 < 0.15:
        return None
    s2 = (real.iloc[0] + real.iloc[1]) / total
    return (f"{n(len(real))} בודקי הרבנות חתומים על הרשימה, אך שניים מהם — {real.index[0]} "
            f"({n(real.iloc[0])} שורות) ו{real.index[1]} ({n(real.iloc[1])}) — בדקו יחד {pct(s2)} מהאישורים.")


def insight_expired(df, ref):
    if ref is None:
        return None
    exp = df["expiry"]
    expired = int((exp < ref).sum())
    rel = df[df["relative"]]
    if expired > 0:
        by_label = ranked(df.loc[exp < ref, "validity"].value_counts())
        lab = by_label.index[0]
        return (f"נכון למועד הבדיקה האחרון ברשימה ({dmy(ref)}) פג תוקפן של {n(expired)} שורות זן "
                f"({pct(expired / len(df), 1)}), "
                + (f"כולן בתוקף \"{lab}\"" if int(by_label.iloc[0]) == expired
                   else f"מהן {n(by_label.iloc[0])} בתוקף \"{lab}\"")
                + " — והן עדיין מופיעות ברשימה.")
    fixed = df.loc[~df["relative"] & exp.notna(), "expiry"]
    if fixed.empty:
        return None
    first = fixed.min()
    cnt = int((fixed == first).sum())
    txt = (f"כל האישורים בתוקף נכון למועד הבדיקה האחרון ברשימה ({dmy(ref)}). המועד הקרוב לחידוש: "
           f"{dmy(first)}, עבור {n(cnt)} שורות ({pct(cnt / len(df))}).")
    if len(rel) > 0:
        txt += f" {n(len(rel))} שורות מאושרות לפרק זמן קצוב מיום הבדיקה."
    return txt


def insight_notes(df):
    nn = df[df["notes"] != ""]
    if len(nn) < 20:
        return None
    revai = nn[nn["notes"].str.contains("רבעי")]
    if len(revai) < 10:
        return None
    fc = ranked(revai["family"].value_counts()).drop(UNCLASSIFIED, errors="ignore")
    if fc.empty:
        return None
    fam_total = int((df["family"] == fc.index[0]).sum())
    return (f"{n(len(revai))} שורות ({pct(len(revai) / len(df), 1)}) מסומנות \"רבעי\" או \"גם רבעי\" — פרי בשנתו הרביעית של העץ, "
            f"שדינו פדיון. הסימון שכיח במיוחד ב{fam_label(fc.index[0])}: {n(fc.iloc[0])} שורות, "
            f"{pct(fc.iloc[0] / fam_total)} מהקבוצה.")


def insight_inspections(monthly, partial, dated_rows, dated_fam):
    if len(monthly) < 3 or dated_rows < 30:
        return None
    full = monthly.iloc[:-1] if partial else monthly
    if full.empty:
        return None
    peak = full.sort_index().idxmax()
    fam_txt = ""
    if not dated_fam.empty and dated_fam.iloc[0] / dated_rows >= 0.6:
        fam_txt = f" ({pct(dated_fam.iloc[0] / dated_rows)} מהן {fam_label(dated_fam.index[0])})"
    txt = (f"ל-{n(dated_rows)} שורות{fam_txt} נרשם תאריך בדיקה; החודש העמוס ביותר היה "
           f"{month_label(peak)} עם {n(full[peak])} שורות שנבדקו")
    if partial:
        txt += f" (החודש האחרון, {month_label(monthly.index[-1])}, חלקי ואינו נכלל בהשוואה)"
    return txt + "."


# --- main ------------------------------------------------------------------------------
def compute(frames):
    df, dupes = _prepare(frames["main"])
    total = len(df)
    n_growers = df["grower"].nunique()
    n_localities = df.loc[df["locality"] != NOT_GIVEN, "locality"].nunique()
    n_varieties = df.loc[df["fruits"] != "", "fruits"].nunique()

    ref = df["insp"].max()
    ref = None if pd.isna(ref) else ref

    # families
    fam_rows = df["family"].value_counts()
    fam_present = [f for f in FAMILY_ORDER if f in fam_rows.index]
    fam_sorted = sorted(fam_present, key=lambda f: (-int(fam_rows[f]), FAMILY_ORDER.index(f)))
    fam_rows_r = pd.Series({f: int(fam_rows[f]) for f in fam_sorted}, dtype="int64")
    if UNCLASSIFIED in fam_rows.index:
        fam_rows_r[UNCLASSIFIED] = int(fam_rows[UNCLASSIFIED])
    fam_growers = df.groupby("family")["grower"].nunique()
    fam_varieties = df.groupby("family")["fruits"].nunique()
    classified_share = 1 - fam_rows.get(UNCLASSIFIED, 0) / total if total else 0
    fam_names = list(fam_rows_r.index)
    charts = {
        "families": {
            "names": [fam_label(f) for f in fam_names],
            "rows": [int(fam_rows_r[f]) for f in fam_names],
            "growers": [int(fam_growers.get(f, 0)) for f in fam_names],
        }
    }

    # top varieties
    var_rows = ranked(df.loc[df["fruits"] != "", "fruits"].value_counts()).head(TOP_VARIETIES)
    var_fam = {v: classify(v) for v in var_rows.index}
    var_growers = df.groupby("fruits")["grower"].nunique()
    charts["varieties"] = {
        "names": list(var_rows.index),
        "values": [int(v) for v in var_rows.values],
        "colors": [FAMILY_COLORS[var_fam[v]] for v in var_rows.index],
        "fams": [fam_label(var_fam[v]) for v in var_rows.index],
    }

    # treemap family -> variety
    tree = []
    vc_by_fam = df[df["fruits"] != ""].groupby(["family", "fruits"]).size()
    for f in fam_names:
        if f not in vc_by_fam.index.get_level_values(0):
            continue
        sub = ranked(vc_by_fam.loc[f])
        kids = [{"name": k, "value": int(v)} for k, v in sub.head(TREE_PER_FAM).items()]
        rest = int(sub.iloc[TREE_PER_FAM:].sum())
        if rest:
            kids.append({"name": f"{OTHER} ({n(len(sub) - TREE_PER_FAM)} זנים)", "value": rest})
        txt_color = "#0c3058" if FAMILY_COLORS[f] in LIGHT_COLORS else "#ffffff"
        tree.append({"name": fam_label(f), "value": int(sub.sum()),
                     "itemStyle": {"color": FAMILY_COLORS[f]},
                     "label": {"color": txt_color}, "upperLabel": {"color": txt_color},
                     "children": kids})
    charts["tree"] = tree

    # localities stacked by family
    loc_rows = ranked(df.loc[df["locality"] != NOT_GIVEN, "locality"].value_counts())
    top_locs = list(loc_rows.head(TOP_LOCALITIES).index)
    stack_fams = [f for f in fam_sorted][:TOP_FAM_STACK]
    lf = df[df["locality"].isin(top_locs)].groupby(["locality", "family"]).size()
    loc_growers = df.groupby("locality")["grower"].nunique()
    series = []
    for f in stack_fams:
        series.append({"name": fam_label(f), "color": FAMILY_COLORS[f],
                       "data": [int(lf.get((loc, f), 0)) for loc in top_locs]})
    other_vals = [int(loc_rows[loc]) - sum(int(lf.get((loc, f), 0)) for f in stack_fams) for loc in top_locs]
    if any(other_vals):
        series.append({"name": "קבוצות אחרות ולא מסווג", "color": FAMILY_COLORS[OTHER], "data": other_vals})
    charts["localities"] = {"names": top_locs, "series": series}

    # locality size distribution
    loc_buckets = [(1, 1, "שורה אחת"), (2, 5, "2 עד 5"), (6, 10, "6 עד 10"), (11, 25, "11 עד 25"),
                   (26, 50, "26 עד 50"), (51, None, "51 ומעלה")]
    lb_names, lb_vals = [], []
    for lo, hi, lab in loc_buckets:
        m = (loc_rows >= lo) & ((loc_rows <= hi) if hi is not None else True)
        lb_names.append(lab)
        lb_vals.append(int(m.sum()))
    charts["loc_dist"] = {"names": lb_names, "values": lb_vals}

    # growers: size distribution + top growers
    per_grower = df.groupby("grower").size()
    g_buckets = [(1, 1, "1"), (2, 2, "2"), (3, 3, "3"), (4, 5, "4 עד 5"), (6, 9, "6 עד 9"),
                 (10, None, "10 ומעלה")]
    gb_names, gb_vals = [], []
    for lo, hi, lab in g_buckets:
        m = (per_grower >= lo) & ((per_grower <= hi) if hi is not None else True)
        gb_names.append(lab)
        gb_vals.append(int(m.sum()))
    charts["grower_size"] = {"names": gb_names, "values": gb_vals}

    pg = ranked(per_grower).head(TOP_GROWERS)
    def _main_fam(s):
        vc = ranked(s.value_counts())
        named = vc.drop(UNCLASSIFIED, errors="ignore")
        return named.index[0] if len(named) else vc.index[0]

    g_fams = df[df["grower"].isin(pg.index)].groupby("grower")["family"].agg(_main_fam)
    charts["top_growers"] = {
        "names": list(pg.index),
        "values": [int(v) for v in pg.values],
        "colors": [FAMILY_COLORS[g_fams[g]] for g in pg.index],
        "fams": [fam_label(g_fams[g]) for g in pg.index],
    }

    # inspectors x validity
    insp_rows = ranked(df["checked"].value_counts())
    top_insp = list(insp_rows.drop(NOT_GIVEN, errors="ignore").head(TOP_INSPECTORS).index)
    val_info = df.groupby("validity").agg(rows=("validity", "size"), exp=("expiry", "min"),
                                          rel=("relative", "max"))
    def _vkey(v):
        rel_v = bool(val_info.loc[v, "rel"])
        exp_v = val_info.loc[v, "exp"]
        has = (not rel_v) and pd.notna(exp_v)
        return (rel_v, not has, exp_v if has else pd.Timestamp(0), v)

    val_order = sorted(val_info.index, key=_vkey)
    iv = df.assign(ci=df["checked"].where(df["checked"].isin(top_insp), OTHER)).groupby(["ci", "validity"]).size()
    insp_names = top_insp + ([OTHER] if (~df["checked"].isin(top_insp)).any() else [])
    ramp = ["#0068f5", "#0b3668", "#6c9fd8", "#b7d2f7", "#3d70b0", "#2658a0", "#0c1f3d"]
    val_colors = {}
    for i, v in enumerate(val_order):
        exp = val_info.loc[v, "exp"]
        if ref is not None and not val_info.loc[v, "rel"] and pd.notna(exp) and exp < ref:
            val_colors[v] = "#dc3545"
        else:
            val_colors[v] = ramp[i % len(ramp)]
    charts["inspectors"] = {
        "names": insp_names,
        "series": [{"name": v, "color": val_colors[v],
                    "data": [int(iv.get((ci, v), 0)) for ci in insp_names]} for v in val_order],
    }

    # validity
    val_expired = {}
    for v in val_order:
        sub = df[df["validity"] == v]
        val_expired[v] = int((sub["expiry"] < ref).sum()) if ref is not None else 0
    charts["validity"] = {
        "names": val_order,
        "values": [int(val_info.loc[v, "rows"]) for v in val_order],
        "expired": [val_expired[v] for v in val_order],
    }

    # notes x family
    nn = df[df["notes"] != ""]
    note_rows = ranked(nn["notes"].value_counts())
    top_notes = list(note_rows.head(TOP_NOTES).index)
    nf = nn.groupby(["notes", "family"]).size()
    note_fams = [f for f in fam_sorted if any(nf.get((nt, f), 0) for nt in top_notes)][:TOP_FAM_STACK]
    nseries = [{"name": fam_label(f), "color": FAMILY_COLORS[f],
                "data": [int(nf.get((nt, f), 0)) for nt in top_notes]} for f in note_fams]
    nother = [int(note_rows[nt]) - sum(int(nf.get((nt, f), 0)) for f in note_fams) for nt in top_notes]
    if any(nother):
        nseries.append({"name": "קבוצות אחרות ולא מסווג", "color": FAMILY_COLORS[OTHER], "data": nother})
    charts["notes"] = {"names": top_notes, "series": nseries}

    # dated inspections by month
    dated = df[df["insp"].notna()]
    monthly = pd.Series(dtype="int64")
    partial = False
    if len(dated):
        per = dated["insp"].dt.to_period("M")
        rng = pd.period_range(per.min(), per.max(), freq="M")
        if len(rng) > MAX_MONTHS:
            rng = rng[-MAX_MONTHS:]
        counts = per.value_counts()
        monthly = pd.Series([int(counts.get(p, 0)) for p in rng], index=rng, dtype="int64")
        last_day = dated["insp"].max()
        partial = bool(last_day.day < last_day.days_in_month - 5) and len(monthly) > 1
    dated_fam = ranked(dated["family"].value_counts()).drop(UNCLASSIFIED, errors="ignore")
    charts["inspections"] = {
        "x": [month_label(p) for p in monthly.index],
        "y": [int(v) for v in monthly.values],
        "partial": partial,
    }

    # --- KPIs ---
    expired_total = int((df["expiry"] < ref).sum()) if ref is not None else 0
    revai_rows = int(df["notes"].str.contains("רבעי").sum())
    kpis = {
        "growers": {"value": int(n_growers), "display": n(n_growers), "tone": "brand"},
        "localities": {"value": int(n_localities), "display": n(n_localities), "tone": "brand"},
        "rows": {"value": int(total), "display": n(total), "tone": "brand"},
        "expired": {"value": expired_total, "display": n(expired_total),
                    "tone": ("danger" if expired_total / max(total, 1) >= 0.05 else
                             "warn" if expired_total > 0 else "ok")},
    }

    # --- insights ---
    top_g_name = pg.index[0] if len(pg) else ""
    top_g_count = int(pg.iloc[0]) if len(pg) else 0
    rules = [
        ("family", lambda: insight_family(fam_rows_r, fam_growers, total, n_growers, classified_share)),
        ("concentration", lambda: insight_concentration(loc_rows, total)),
        ("top_locality", lambda: insight_top_locality(df, loc_rows)),
        ("grapes", lambda: insight_grapes(df)),
        ("growers", lambda: insight_growers(per_grower, top_g_name, top_g_count)),
        ("expired", lambda: insight_expired(df, ref)),
        ("notes", lambda: insight_notes(df)),
        ("inspectors", lambda: insight_inspectors(insp_rows, total)),
        ("inspections", lambda: insight_inspections(monthly, partial, len(dated), dated_fam)),
    ]
    insights = []
    for rid, fn in rules:
        t = fn()
        if t:
            insights.append({"id": rid, "text_he": t})

    # --- labels ---
    top_fam = fam_sorted[0] if fam_sorted else UNCLASSIFIED
    ref_txt = dmy(ref) if ref is not None else ""
    labels = {
        "lede": (f"הרבנות הראשית מפרסמת את רשימת החקלאים שפירותיהם אושרו כנקיים מחשש ערלה (פרי משלוש השנים "
                 f"הראשונות לנטיעת העץ). הרשימה הנוכחית כוללת {n(total)} שורות זן מאושרות של {n(n_growers)} "
                 f"מגדלים ב-{n(n_localities)} יישובים, ב-{n(n_varieties)} שמות פרי וזן שונים; קבוצת הגידול "
                 f"הגדולה היא {fam_label(top_fam)}. כל שורה היא זן אחד של מגדל אחד, עם שם הבודק ותוקף האישור."
                 + (f" {n(dupes)} שורות כפולות זהות הוסרו." if dupes else "")),
        "growers_kpi": "מגדלים מאושרים (שם ויישוב)",
        "localities_kpi": "יישובים",
        "rows_kpi": "שורות זן מאושרות",
        "expired_kpi": (f"שורות שתוקפן פג עד {ref_txt} (מועד הבדיקה האחרון ברשימה)" if ref is not None
                        else "שורות שתוקפן פג (אין תאריכי בדיקה ברשימה)"),
        "families_note": (f"שורות הזן ומספר המגדלים בכל קבוצת גידול. עמודת הפרי מערבבת מינים (\"תמר\") וזנים "
                          f"(\"מרלו\", \"אטינגר/האס\"), ולכן הקבוצות סווגו לפי שם הזן; "
                          f"{pct(classified_share)} מהשורות סווגו, והשאר מוצגות כ\"{UNCLASSIFIED}\"."),
        "families_aria": (f"תרשים עמודות אופקי: שורות זן ומגדלים לפי קבוצת גידול — {fam_label(top_fam)} בראש עם "
                          f"{n(fam_rows_r.iloc[0]) if len(fam_rows_r) else n(0)} שורות."),
        "families_caption": "שורות זן, מגדלים ושמות זן לפי קבוצת גידול.",
        "varieties_note": (f"{len(var_rows)} שמות הפרי או הזן הנפוצים ברשימה, בצבע קבוצת הגידול. שם שמופיע "
                           f"כזן (\"מרלו\") ושם שמופיע כמין (\"תמר\") נספרים כל אחד בנפרד."),
        "varieties_aria": (f"תרשים עמודות אופקי: שמות הפרי הנפוצים — {var_rows.index[0]} בראש עם "
                           f"{n(var_rows.iloc[0])} שורות." if len(var_rows) else "תרשים עמודות אופקי: שמות הפרי הנפוצים."),
        "varieties_caption": "שמות הפרי והזן הנפוצים: שורות ומגדלים.",
        "tree_note": (f"כל מלבן הוא קבוצת גידול, ובתוכו עד {TREE_PER_FAM} הזנים הנפוצים בה; שטח המלבן יחסי "
                      f"למספר שורות הזן. לחיצה על קבוצה מתמקדת בה."),
        "tree_aria": f"מפת שטחים: שורות זן לפי קבוצת גידול וזן, {fam_label(top_fam)} הגדולה.",
        "localities_note": (f"{len(top_locs)} היישובים עם מירב שורות הזן המאושרות, מפולחים לפי קבוצת גידול "
                            f"(מתוך {n(n_localities)} יישובים)."),
        "localities_aria": (f"תרשים עמודות אופקיות מוערמות: יישובים מובילים — {top_locs[0]} בראש עם "
                            f"{n(loc_rows.iloc[0])} שורות." if top_locs else "תרשים יישובים מובילים."),
        "localities_caption": "היישובים המובילים: שורות זן ומגדלים.",
        "loc_dist_note": (f"מספר היישובים לפי כמות שורות הזן המאושרות בהם — רוב היישובים קטנים, ומעטים "
                          f"מרכזים חלק גדול מהרשימה."),
        "loc_dist_aria": f"תרשים עמודות: התפלגות {n(n_localities)} היישובים לפי מספר שורות הזן בכל יישוב.",
        "loc_dist_caption": "מספר היישובים לפי כמות שורות הזן.",
        "grower_size_note": (f"מספר המגדלים לפי כמות שורות הזן שאושרו להם. מגדל מזוהה לפי שמו ויישובו."),
        "grower_size_aria": f"תרשים עמודות: התפלגות {n(n_growers)} המגדלים לפי מספר שורות הזן.",
        "grower_size_caption": "מספר המגדלים לפי כמות שורות הזן.",
        "top_growers_note": (f"{len(pg)} המגדלים עם מירב שורות הזן המאושרות, בצבע קבוצת הגידול העיקרית שלהם."),
        "top_growers_aria": (f"תרשים עמודות אופקי: המגדלים המובילים — {top_g_name} בראש עם {n(top_g_count)} שורות."
                             if len(pg) else "תרשים המגדלים המובילים."),
        "top_growers_caption": "המגדלים המובילים לפי שורות זן.",
        "inspectors_note": (f"שורות הזן שאישר כל בודק, לפי תוקף האישור"
                            + (f" ({len(top_insp)} הבודקים המובילים)" if len(insp_names) > len(top_insp) else "")
                            + ". כל צבע הוא מועד תוקף אחר."),
        "inspectors_aria": (f"תרשים עמודות אופקיות מוערמות: אישורים לפי בודק ותוקף — {top_insp[0]} בראש."
                            if top_insp else "תרשים אישורים לפי בודק."),
        "inspectors_caption": "שורות זן לפי בודק ותוקף.",
        "validity_note": (f"שורות הזן לפי מועד פקיעת האישור. תוקף יחסי (\"חודשים מהבדיקה\") מחושב מתאריך הבדיקה "
                          f"שבשורה" + (f"; שורות שתוקפן פג עד {ref_txt} מסומנות באדום." if ref is not None else ".")),
        "validity_aria": (f"תרשים עמודות: שורות זן לפי תוקף האישור, {n(expired_total)} שתוקפן פג."),
        "validity_caption": "שורות זן לפי תוקף האישור.",
        "notes_note": (f"{n(len(nn))} שורות ({pct(len(nn) / max(total, 1), 1)}) נושאות הערה. \"רבעי\" — פרי "
                       f"בשנתו הרביעית של העץ; \"גם\" מציין שהאישור חל גם על פרי זה. פילוח לפי קבוצת גידול."),
        "notes_aria": (f"תרשים עמודות אופקיות מוערמות: הערות לפי קבוצת גידול — \"{top_notes[0]}\" השכיחה."
                       if top_notes else "תרשים הערות."),
        "notes_caption": "שורות זן לפי הערה וקבוצת גידול.",
        "inspections_note": (f"{n(len(dated))} שורות בלבד נושאות תאריך בדיקה — אלו מספר הבדיקות בכל חודש"
                             + (f"; החודש האחרון חלקי." if partial else ".")),
        "inspections_aria": (f"תרשים עמודות: בדיקות לפי חודש, {n(len(dated))} שורות עם תאריך."),
        "inspections_caption": "בדיקות לפי חודש.",
    }

    tables = {
        "families": [{"name": fam_label(f), "rows": n(fam_rows_r[f]), "growers": n(fam_growers.get(f, 0)),
                      "varieties": n(fam_varieties.get(f, 0)), "share": pct_bare(fam_rows_r[f] / total)}
                     for f in fam_names],
        "varieties": [{"name": v, "fam": fam_label(var_fam[v]), "rows": n(c), "growers": n(var_growers.get(v, 0))}
                      for v, c in var_rows.items()],
        "localities": [{"name": loc, "rows": n(loc_rows[loc]), "growers": n(loc_growers.get(loc, 0))}
                       for loc in top_locs],
        "loc_dist": [{"name": a, "count": n(b)} for a, b in zip(lb_names, lb_vals)],
        "grower_size": [{"name": a, "count": n(b)} for a, b in zip(gb_names, gb_vals)],
        "top_growers": [{"name": g, "fam": fam_label(g_fams[g]), "rows": n(c)} for g, c in pg.items()],
        "inspectors": [{"name": ci, "vals": [n(iv.get((ci, v), 0)) for v in val_order],
                        "total": n(sum(int(iv.get((ci, v), 0)) for v in val_order))} for ci in insp_names],
        "validity_cols": val_order,
        "validity": [{"name": v, "rows": n(val_info.loc[v, "rows"]), "expired": n(val_expired[v]),
                      "until": (dmy(val_info.loc[v, "exp"]) if pd.notna(val_info.loc[v, "exp"]) and not val_info.loc[v, "rel"]
                                else "יחסי לתאריך הבדיקה")} for v in val_order],
        "notes": [{"name": nt, "rows": n(note_rows[nt])} for nt in top_notes],
        "inspections": [{"name": month_label(p), "count": n(v)} for p, v in monthly.items()],
    }

    temporal = None
    if len(dated):
        y0, y1 = dated["insp"].min().year, dated["insp"].max().year
        temporal = f"{y0}/{y1}" if y0 != y1 else str(y0)

    agent_data = {
        "summary_he": (f"רשימת הרבנות הראשית של {n(n_growers)} מגדלים ב-{n(n_localities)} יישובים שפירותיהם אושרו "
                       f"ללא חשש ערלה — {n(total)} שורות זן, לפי קבוצת גידול, זן, יישוב, בודק ותוקף."),
        "dataset_kind": "registry",
        "suggested_tags": ["ערלה", "כשרות", "חקלאות", "מטעים", "רבנות ראשית", "פירות"],
        "related_ids": ["1a49cbba-3722-4a67-9c20-9895697d0373",
                        "6a8f3548-f991-4f8b-ab52-80240324ab4d",
                        "7a6cbf55-8178-4d40-8613-a38909c7e96f",
                        "b72acc9a-6512-4849-9529-3ce73370bff2"],
        "spatial_coverage": "ישראל",
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"notes": len(top_notes) > 0, "inspections": len(monthly) >= 2,
                  "tree": len(tree) > 0, "growers": len(pg) > 0},
    }
