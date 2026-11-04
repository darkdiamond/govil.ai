"""רשימת מתכננים ומודדים (משרד הבינוי והשיכון): the ministry's pool of
planners, surveyors and consultants.

One row = one (supplier, specialty, sub-classification). A supplier
(KOD_SAPAK) appears once per specialty it is listed in. The specialty
"רשויות ומשרדי ממשלה" lists public bodies (local councils, water
corporations, government offices), not professionals; the page keeps them
apart from the professional analysis and gives them their own section.

Privacy: KOD_SAPAK is an ID / company number. It is used only as the
grouping key and, via its registrar prefix, to classify the entity type in
aggregate; it never reaches the model. Street, house number and phone are
contact details and are not read for the page (the explorer has them).
"""
import re

import pandas as pd
from govlib import fmt, frame

AUTH_KEY = "רשויות"  # specialty naming the public-bodies list
AUTH_FAM = "רשויות ומשרדי ממשלה"

# Specialty -> professional family. First family whose keyword starts a word
# (optionally after a ו/ל/ה/ב prefix) wins; anything new falls to "אחר".
FAMILIES = [
    (AUTH_FAM, [AUTH_KEY]),
    ("מכרזים ייעודיים", ["מכרז", "חברות מתכננות"]),
    ("מדידות ומיפוי", ["מדיד", "מודד", "מיפוי", "צילומי אוויר", "רישום מקרקעין", "פוטוגרמ"]),
    ("נגישות ובטיחות", ["נגישות", "בטיחות", "חירום", "קוד הבניה", "חומרים מסוכנים"]),
    ("תנועה ותחבורה", ["תנועה", "תחבורה", "כביש", "רמזור", "תעופה", "מיסעות"]),
    ("מים, ביוב וניקוז", ["מים", "ביוב", "ניקוז", "הידרו", "השקיה"]),
    ("קונסטרוקציה וקרקע", ["קונסטרוק", "ביסוס", "גיאולוג", "סייסמ", "עוגני", "גיאופיז", "גשרים"]),
    ("חשמל ומערכות", ["חשמל", "מיזוג", "אינסטל", "מתזים", "מעליות", "תקשורת", "אקוסטי",
                      "בידוד", "מערכות במה"]),
    ("סביבה ואנרגיה", ["סביב", "אקלים", "אקולוג", "פסולת", "זיהום", "אנרגטית", "אבק",
                       "אגרונומ", "גינון"]),
    ("אדריכלות ונוף", ["אדריכ", "נוף", "עיצוב פנים", "שימור", "הדמי"]),
    ("ניהול ופיקוח", ["ניהול", "פיקוח", "בקרה", "בקרת", "לוחות זמנ", "הבטחת איכות",
                      "כתבי כמויות", "תאום", "מנהל", "BIM", "מתאם", "חסמים"]),
    ("שמאות, כלכלה וחברה", ["שמא", "כלכל", "חברתי", "שיתוף", "תיירות", "מיתוג", "הפקעות",
                            "מענקי"]),
    ("תכנון ומדיניות", ["מדיניות", "תב\"ע", "ערים חכמות", "גיאוגרפ", "תמא", "התחדשות"]),
]
FAM_RE = [(f, [re.compile(r"(?:^|[^א-ת])[ולהב]?" + re.escape(k)) for k in ks]) for f, ks in FAMILIES]

GRADES = ["א", "ב", "ג", "ד", "רגילה", "פירוט אחר"]
GRADE_LABELS = {"א": "דרגה א", "ב": "דרגה ב", "ג": "דרגה ג", "ד": "דרגה ד",
                "רגילה": "רגילה", "פירוט אחר": "פירוט אחר"}

ENTITY_ORDER = ["חברה", "עוסק יחיד", "שותפות", "עמותה או אגודה", "גוף ציבורי", "אחר"]

AUTH_TYPES = [
    ("עירייה", re.compile(r"^עירי")),
    ("מועצה מקומית", re.compile(r"^(מ\. ?מ\.|מועצה מקומית)")),
    ("מועצה אזורית", re.compile(r"^(מ\. ?א\.?|מ\"א|מועצה אזורית)")),
    ("מועצה דתית", re.compile(r"^מ\. ?ד\.")),
    ("איגוד ערים או רשות ניקוז", re.compile(r"^(איגוד|רשות ניקוז)")),
    ("משרד ממשלתי", re.compile(r"^(ה?משרד|לשכת)")),
    ("תאגיד מים וביוב", re.compile(r"(^מי[ -]|תאגיד|מים וביוב|^עין |^מעי?ינות|^יובלים|^פלג|^ימים)")),
    ("חברה עירונית או ממשלתית", re.compile(r"(^ה?חבר|חברה|בע\"מ)")),
]
AUTH_OTHER = "רשות או גוף אחר"

TOP_SPEC = 15
TOP_CITY = 15
HEAT_CITIES = 10
TOP_FIRMS = 10
MULTI_CAP = 6  # "6+" bucket for specialties per supplier
GRADE_MIN_ROWS = 40  # a family enters the grade comparison with this many graded rows


def _fam(sp):
    for f, pats in FAM_RE:
        if any(p.search(sp) for p in pats):
            return f
    return "אחר"


def _grade(s):
    m = re.match(r"^([א-ד])\s*[-–]", s)
    if m:
        return m.group(1)
    if s.startswith("רגיל"):
        return "רגילה"
    return "פירוט אחר"


def _entity(code):
    c = re.sub(r"\D", "", code)
    if not c:
        return "אחר"
    z = c.zfill(9)
    p = z[:2]
    if len(c) > 9:
        return "אחר"
    if p in ("51", "52"):
        return "חברה"
    if p in ("54", "55"):
        return "שותפות"
    if p in ("57", "58"):
        return "עמותה או אגודה"
    if p == "50":
        return "גוף ציבורי"
    if z[0] in "0123":
        return "עוסק יחיד"
    return "אחר"


def _auth_type(name):
    for t, pat in AUTH_TYPES:
        if pat.search(name):
            return t
    return AUTH_OTHER


def _mode(s):
    """Most common value, ties broken by the value itself."""
    r = frame.ranked(s)
    return r.index[0] if len(r) else ""


def _n(v):
    return fmt.int_he(v)


def _plural(n, one, many):
    return f"{one} אחד" if n == 1 else f"{_n(n)} {many}"


def _prepare(df):
    df = df.copy()
    df["key"] = frame.clean_series(df["KOD_SAPAK"])
    df["name"] = frame.clean_series(df["SHEM_SAPAK"])
    df["sp"] = frame.clean_series(df["HITMAHUT_DESCRIPTION"]).replace("", "לא צוין")
    df["sub"] = frame.clean_series(df["SUB_KOD_HITMAHUT_DESCRIPTION"])
    df["city_code"] = frame.clean_series(df["SEMEL_YISHUV"])
    df["city"] = frame.clean_series(df["SHEM_YISHUV"]).str.replace(r"\s*-\s*", "-", regex=True)
    df = df[df["key"] != ""]
    df["fam"] = df["sp"].map(_fam)
    df["grade"] = df["sub"].map(_grade)
    return df


def _suppliers(df):
    """One row per supplier: display name, locality, entity type."""
    names = (df.groupby("key")["name"].agg(_mode))
    codes = df.groupby("key")["city_code"].agg(_mode)
    code_name = (df[df["city"] != ""].groupby("city_code")["city"].agg(_mode))
    city = codes.map(lambda c: code_name.get(c, "")).replace("", "לא צוין")
    out = pd.DataFrame({"name": names, "city": city})
    out["entity"] = [(_entity(k)) for k in out.index]
    return out.sort_index()


# ---------------------------------------------------------------- insights

def ins_family(fam_counts, n_pro):
    if fam_counts.empty or n_pro == 0:
        return None
    f, v = fam_counts.index[0], int(fam_counts.iloc[0])
    share = v / n_pro
    if len(fam_counts) < 2 or share < 0.15:
        return None
    f2, v2 = fam_counts.index[1], int(fam_counts.iloc[1])
    return (f"תחום {f} הוא הגדול ברשימה: {_n(v)} ספקים ({fmt.pct(share)} מבעלי המקצוע), "
            f"ואחריו {f2} עם {_n(v2)}.")


def ins_specialty(spec_counts):
    if len(spec_counts) < 2:
        return None
    (s1, v1), (s2, v2) = list(spec_counts.items())[:2]
    return (f"תחום ההתמחות הנפוץ ביותר הוא \"{s1}\" עם {_n(v1)} ספקים, "
            f"ואחריו \"{s2}\" עם {_n(v2)}.")


def ins_authorities(n_auth, n_sup, auth_types):
    if n_auth == 0 or n_sup == 0:
        return None
    top = auth_types.index[0] if len(auth_types) else None
    tail = ""
    if top is not None and top != AUTH_OTHER:
        tail = f" הקבוצה הגדולה בהן: {top} ({_n(auth_types.iloc[0])})."
    return (f"{_n(n_auth)} מהספקים ברשימה ({fmt.pct(n_auth / n_sup)}) אינם בעלי מקצוע אלא "
            f"רשויות מקומיות, תאגידים ומשרדי ממשלה, הרשומים תחת \"{AUTH_FAM}\".{tail}")


def ins_multi(per_sup, firms):
    n = len(per_sup)
    if n < 10:
        return None
    multi = int((per_sup > 1).sum())
    share = multi / n
    if share < 0.1:
        return None
    s = (f"{fmt.pct(share)} מבעלי המקצוע ({_n(multi)}) רשומים ביותר מתחום התמחות אחד")
    top_n = int(per_sup.max())
    at_top = int((per_sup == top_n).sum())
    if firms and top_n > 1:
        name = firms[0]["name"]
        if at_top == 1:
            s += f"; המגוון ביותר, {name}, רשום ב-{_n(top_n)} תחומים."
        else:
            s += (f"; {_n(at_top)} ספקים רשומים ב-{_n(top_n)} תחומים, המספר הגבוה ביותר, "
                  f"ביניהם {name}.")
    else:
        s += "."
    return s


def ins_city(city_counts, n_pro):
    if len(city_counts) < 4 or n_pro == 0:
        return None
    top = city_counts.iloc[:3]
    share = top.sum() / n_pro
    names = fmt.join_he(list(top.index))
    lead, lv = city_counts.index[0], int(city_counts.iloc[0])
    if share < 0.2:
        return f"בעלי המקצוע מפוזרים ב-{_n(len(city_counts))} יישובים; המוביל, {lead}, מרכז {_n(lv)}."
    return (f"{fmt.pct(share)} מבעלי המקצוע יושבים בשלושה יישובים בלבד: {names}. "
            f"{lead} לבדה מרכזת {_n(lv)} ספקים, מתוך {_n(len(city_counts))} יישובים ברשימה.")


def ins_entity(ent_counts, n_pro):
    if n_pro == 0:
        return None
    co = int(ent_counts.get("חברה", 0))
    ind = int(ent_counts.get("עוסק יחיד", 0))
    if co + ind == 0:
        return None
    if co >= ind:
        lead, verb, lv, other, ov = "חברות", "מהוות", co, "עוסקים יחידים", ind
    else:
        lead, verb, lv, other, ov = "עוסקים יחידים", "מהווים", ind, "חברות", co
    return (f"{lead} {verb} {fmt.pct(lv / n_pro)} מבעלי המקצוע ({_n(lv)}), לעומת {_n(ov)} {other} "
            f"({fmt.pct(ov / n_pro)}); הסיווג נגזר ממבנה המספר המזהה של הספק.")


def ins_grade(grade_tab):
    """Which family is graded highest / lowest, among families with enough
    letter-graded rows."""
    rows = []
    for fam, r in grade_tab.items():
        lettered = sum(r[g] for g in ("א", "ב", "ג", "ד"))
        if lettered >= GRADE_MIN_ROWS:
            rows.append((fam, r["א"] / lettered, lettered))
    if len(rows) < 2:
        return None
    rows.sort(key=lambda t: (-t[1], t[0]))
    hi, lo = rows[0], rows[-1]
    if hi[1] - lo[1] < 0.15:
        return None
    return (f"שיעור הרישומים בדרגה א (הדרגה הגבוהה, לפרויקטים הגדולים) גבוה במיוחד ב{hi[0]}: "
            f"{fmt.pct(hi[1])}, לעומת {fmt.pct(lo[1])} בלבד ב{lo[0]} "
            f"(מתוך הרישומים המדורגים באותיות).")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    sup = _suppliers(df)
    n_rows = len(df)
    n_sup = len(sup)

    auth_rows = df[df["fam"] == AUTH_FAM]
    pro = df[df["fam"] != AUTH_FAM]
    auth_keys = sorted(set(auth_rows["key"]))
    pro_keys = sorted(set(pro["key"]))
    n_auth, n_pro = len(auth_keys), len(pro_keys)
    psup = sup.loc[pro_keys] if n_pro else sup.iloc[0:0]

    pairs = pro.drop_duplicates(["key", "sp"])
    n_spec = int(pro["sp"].nunique())

    # families (distinct suppliers)
    fam_counts = frame.ranked(pro.drop_duplicates(["key", "fam"])["fam"])
    spec_counts = frame.ranked(pairs["sp"])

    # treemap family -> specialty
    tree = []
    for f in fam_counts.index:
        sc = frame.ranked(pairs[pairs["fam"] == f]["sp"])
        tree.append({"name": f, "value": int(fam_counts[f]),
                     "children": [{"name": s, "value": int(v)} for s, v in sc.items()]})

    # top specialties
    sl, sv = frame.top_other(spec_counts, TOP_SPEC)
    top_fams = {s: _fam(s) for s in spec_counts.index}

    # grades by family (rows of the professional list)
    grade_tab = {}
    for f in fam_counts.index:
        g = pro[pro["fam"] == f]["grade"].value_counts()
        grade_tab[f] = {k: int(g.get(k, 0)) for k in GRADES}
    gcounts = pro["grade"].value_counts()
    grade_total = {k: int(gcounts.get(k, 0)) for k in GRADES}

    # specialties per supplier
    per_sup = pairs.groupby("key")["sp"].nunique()
    mc = per_sup.clip(upper=MULTI_CAP).value_counts()
    multi_x = [str(i) if i < MULTI_CAP else f"{MULTI_CAP}+" for i in range(1, MULTI_CAP + 1)]
    multi_y = [int(mc.get(i, 0)) for i in range(1, MULTI_CAP + 1)]
    fams_per = pro.drop_duplicates(["key", "fam"]).groupby("key")["fam"].nunique()

    # most versatile suppliers
    fdf = pd.DataFrame({"n": per_sup, "f": fams_per.reindex(per_sup.index).fillna(0).astype(int)})
    fdf["name"] = sup["name"].reindex(fdf.index)
    fdf["city"] = sup["city"].reindex(fdf.index)
    fdf = fdf[fdf["n"] > 1].reset_index()
    fdf = fdf.sort_values(["n", "f", "name", "key"], ascending=[False, False, True, True], kind="stable")
    firms = [{"name": r.name, "n": int(r.n), "f": int(r.f), "city": r.city}
             for r in fdf.head(TOP_FIRMS).itertuples()]

    # entity types
    ent = psup["entity"].value_counts()
    ent_counts = pd.Series({e: int(ent.get(e, 0)) for e in ENTITY_ORDER})
    ent_counts = ent_counts[ent_counts > 0]

    # cities
    city_counts = frame.ranked(psup["city"])
    cl, cv = frame.top_other(city_counts, TOP_CITY)
    n_cities = int((city_counts.index != "לא צוין").sum())

    # heatmap: top cities x families
    hc = [c for c in city_counts.index if c != "לא צוין"][:HEAT_CITIES]
    hf = list(fam_counts.index)
    fam_pairs = pro.drop_duplicates(["key", "fam"]).copy()
    fam_pairs["city"] = fam_pairs["key"].map(sup["city"])
    ct = fam_pairs.groupby(["city", "fam"]).size()
    cells, hmax = [], 0
    for yi, c in enumerate(hc):
        for xi, f in enumerate(hf):
            v = int(ct.get((c, f), 0))
            hmax = max(hmax, v)
            cells.append([xi, yi, v])

    # authorities
    asup = sup.loc[auth_keys] if n_auth else sup.iloc[0:0]
    at = frame.ranked(asup["name"].map(_auth_type)) if n_auth else pd.Series(dtype=int)

    # ------------------------------------------------ insights
    rules = [
        ("family", ins_family(fam_counts, n_pro)),
        ("specialty", ins_specialty(spec_counts)),
        ("grade", ins_grade(grade_tab)),
        ("multi", ins_multi(per_sup, firms)),
        ("city", ins_city(city_counts[city_counts.index != "לא צוין"], n_pro)),
        ("entity", ins_entity(ent_counts, n_pro)),
        ("authorities", ins_authorities(n_auth, n_sup, at)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    multi_share = float((per_sup > 1).mean()) if len(per_sup) else 0.0

    kpis = {
        "rows": {"value": n_rows, "display": _n(n_rows), "tone": "brand"},
        "suppliers": {"value": n_sup, "display": _n(n_sup), "tone": "brand"},
        "pros": {"value": n_pro, "display": _n(n_pro), "tone": "brand"},
        "specs": {"value": n_spec, "display": _n(n_spec), "tone": "brand"},
        "multi": {"value": round(multi_share * 100, 1), "display": fmt.pct(multi_share),
                  "tone": "info"},
        "cities": {"value": n_cities, "display": _n(n_cities), "tone": "brand"},
    }

    # ------------------------------------------------ labels
    lead_f = fam_counts.index[0] if len(fam_counts) else ""
    lead_fv = int(fam_counts.iloc[0]) if len(fam_counts) else 0
    lead_s = spec_counts.index[0] if len(spec_counts) else ""
    lead_sv = int(spec_counts.iloc[0]) if len(spec_counts) else 0
    lead_c = hc[0] if hc else ""
    lead_cv = int(city_counts.get(lead_c, 0)) if lead_c else 0
    one = multi_y[0]

    summary = (f"איתור מתכנן, מודד או יועץ במאגר משרד הבינוי והשיכון לפי שם, יישוב או תחום: "
               f"{_n(n_pro)} בעלי מקצוע ב-{_n(n_spec)} תחומי התמחות.")
    if len(summary) > 155:
        summary = f"איתור מתכנן, מודד או יועץ במאגר משרד הבינוי והשיכון: {_n(n_pro)} בעלי מקצוע."

    labels = {
        "lede": (f"רשימת המתכננים, המודדים והיועצים של משרד הבינוי והשיכון (מאגר היועצים של המשרד) "
                 f"כוללת {_n(n_rows)} רישומים של {_n(n_sup)} ספקים: {_n(n_pro)} בעלי מקצוע "
                 f"ב-{_n(n_spec)} תחומי התמחות, ועוד {_n(n_auth)} רשויות וגופים ציבוריים. "
                 f"כל ספק מופיע פעם אחת לכל תחום שבו הוא רשום, עם סיווג משנה (דרגה או היקף "
                 f"פרויקט). העמוד מנתח את פריסת בעלי המקצוע לפי תחום, דרגה, סוג גוף ויישוב."),
        "fam_lede": (f"תחומי ההתמחות קובצו ל-{_n(len(fam_counts))} משפחות מקצועיות לפי שמם. "
                     f"{lead_f} מובילה עם {_n(lead_fv)} ספקים. ספק הרשום בכמה משפחות נספר בכל אחת."),
        "fam_aria": (f"גרף עמודות אופקי: מספר בעלי המקצוע בכל משפחה מקצועית. "
                     f"המובילה: {lead_f}, {_n(lead_fv)} ספקים."),
        "tree_lede": (f"כל מלבן הוא תחום התמחות, בגודל מספר הספקים הרשומים בו, מקובץ לפי משפחה. "
                      f"לחיצה על משפחה מתמקדת בה. {_n(n_spec)} תחומים בסך הכול."),
        "tree_aria": (f"מפת עץ: {_n(n_spec)} תחומי התמחות מקובצים לפי משפחה מקצועית, "
                      f"בגודל מספר הספקים. הגדול: {lead_s}, {_n(lead_sv)} ספקים."),
        "spec_lede": (f"{_n(TOP_SPEC)} תחומי ההתמחות עם הכי הרבה ספקים רשומים"
                      f"{', וכל השאר מקובצים תחת אחר' if len(spec_counts) > TOP_SPEC + 1 else ''}. "
                      f"\"{lead_s}\" מוביל עם {_n(lead_sv)}."),
        "spec_aria": (f"גרף עמודות אופקי: תחומי ההתמחות המובילים לפי מספר ספקים. "
                      f"המוביל: {lead_s}, {_n(lead_sv)} ספקים."),
        "grade_lede": ("סיווג המשנה של כל רישום מגדיר לרוב דרגה באותיות: א לפרויקטים הגדולים "
                       "ביותר (למשל מספר יחידות דיור או היקף כספי גבוה), ב, ג ו-ד לקטנים יותר. "
                       "\"רגילה\" היא רישום ללא דרגה, ו\"פירוט אחר\" הוא סיווג לפי סוג מבנה או מכרז. "
                       "כל עמודה מציגה את התפלגות הרישומים במשפחה."),
        "grade_aria": (f"גרף עמודות מוערמות: התפלגות הרישומים לפי דרגה בכל משפחה מקצועית. "
                       f"בכלל הרשימה {_n(grade_total['א'])} רישומים בדרגה א."),
        "multi_lede": (f"{_n(one)} בעלי מקצוע רשומים בתחום אחד בלבד; "
                       f"{fmt.pct(multi_share)} רשומים בשניים ויותר."),
        "multi_aria": (f"גרף עמודות: מספר בעלי המקצוע לפי מספר תחומי ההתמחות שבהם הם רשומים. "
                       f"{_n(one)} רשומים בתחום אחד."),
        "firms_lede": ("הספקים הרשומים במספר התחומים הגדול ביותר, ובכמה משפחות מקצועיות הם "
                       "פרושים. אלה בעיקר משרדי הנדסה רב-תחומיים."),
        "firms_aria": (f"גרף עמודות אופקי: הספקים הרשומים במספר הרב ביותר של תחומי התמחות. "
                       f"המוביל: {firms[0]['name']}, {_n(firms[0]['n'])} תחומים." if firms else
                       "גרף עמודות אופקי: הספקים הרב-תחומיים."),
        "ent_lede": ("סוג הגוף נגזר ממבנה המספר המזהה של הספק: מספר חברה, שותפות או עמותה, "
                     "או תעודת זהות של עוסק יחיד. המספרים עצמם אינם מוצגים."),
        "ent_aria": ("תרשים טבעת: בעלי המקצוע לפי סוג הגוף. "
                     + "; ".join(f"{e}: {_n(v)}" for e, v in ent_counts.items()) + "."),
        "city_lede": (f"בעלי המקצוע רשומים ב-{_n(n_cities)} יישובים. {lead_c} מובילה עם {_n(lead_cv)} ספקים."
                      if lead_c else "פריסת בעלי המקצוע לפי יישוב."),
        "city_aria": (f"גרף עמודות אופקי: מספר בעלי המקצוע לפי יישוב. המוביל: {lead_c}, {_n(lead_cv)}."),
        "heat_lede": (f"{_n(len(hc))} היישובים המובילים מול המשפחות המקצועיות: כמה ספקים מכל תחום "
                      f"יושבים בכל יישוב."),
        "heat_aria": (f"מפת חום: מספר בעלי המקצוע לפי יישוב ומשפחה מקצועית ב-{_n(len(hc))} "
                      f"היישובים המובילים. התא הגבוה: {_n(hmax)} ספקים."),
        "auth_lede": (f"{_n(n_auth)} גופים ציבוריים רשומים תחת \"{AUTH_FAM}\". הסוג נקבע לפי "
                      f"שם הגוף; שם שאינו מזוהה נספר כ\"{AUTH_OTHER}\"."),
        "auth_aria": ("גרף עמודות אופקי: הגופים הציבוריים ברשימה לפי סוג. "
                      + "; ".join(f"{t}: {_n(v)}" for t, v in at.items()) + "."),
    }

    gt_rows = []
    for f in hf:
        r = grade_tab[f]
        gt_rows.append([f] + [_n(r[g]) for g in GRADES])

    tables = {
        "fam": [[f, _n(v), fmt.pct(v / n_pro) if n_pro else "0.0%"] for f, v in fam_counts.items()],
        "spec": [[s, _n(v)] for s, v in zip(sl, sv)],
        "grade": gt_rows,
        "multi": [[x, _n(y)] for x, y in zip(multi_x, multi_y)],
        "firms": [[f["name"], f["city"], _n(f["n"]), _n(f["f"])] for f in firms],
        "ent": [[e, _n(v), fmt.pct(v / n_pro) if n_pro else "0.0%"] for e, v in ent_counts.items()],
        "city": [[c, _n(v)] for c, v in zip(cl, cv)],
        "auth": [[t, _n(v)] for t, v in at.items()],
    }

    charts = {
        "fam": {"x": list(fam_counts.index), "y": [int(v) for v in fam_counts]},
        "tree": tree,
        "spec": {"x": sl, "y": sv, "fam": [top_fams.get(s, "") for s in sl]},
        "grade": {"fams": hf, "grades": [GRADE_LABELS[g] for g in GRADES],
                  "series": [[(grade_tab[f][g] / max(sum(grade_tab[f].values()), 1)) * 100
                              for f in hf] for g in GRADES],
                  "counts": [[grade_tab[f][g] for f in hf] for g in GRADES]},
        "multi": {"x": multi_x, "y": multi_y},
        "firms": {"x": [f["name"] for f in firms], "y": [f["n"] for f in firms],
                  "f": [f["f"] for f in firms]},
        "ent": {"names": list(ent_counts.index), "values": [int(v) for v in ent_counts]},
        "city": {"x": cl, "y": cv},
        "heat": {"cities": hc, "fams": hf, "cells": cells, "max": hmax},
        "auth": {"x": list(at.index), "y": [int(v) for v in at]},
    }
    # round the 100%-stack shares for a stable, small payload
    charts["grade"]["series"] = [[round(v, 2) for v in s] for s in charts["grade"]["series"]]

    flags = {"auth": n_auth > 0, "firms": len(firms) > 0, "heat": len(hc) >= 2 and len(hf) >= 2,
             "ent": len(ent_counts) > 0}

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "labels": labels,
        "tables": tables,
        "flags": flags,
        "cols": {"grade": ["משפחה"] + [GRADE_LABELS[g] for g in GRADES]},
    }
