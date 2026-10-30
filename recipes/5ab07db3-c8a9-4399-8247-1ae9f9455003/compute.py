"""בעלי רישיון עיסוק בקנביס (יק"ר): משרד הבריאות.

One row per licence held by a body licensed by the Medical Cannabis Unit
(היחידה לקנביס רפואי, יק"ר) to work with medical/research cannabis. Columns:

- `company_name`: the licensed body (company, partnership, cooperative or a
  sole trader trading under their own name). A body appears once per licence.
- `type`: a numeric activity code (1-10). Code 10 is not an activity but a
  status: "a body whose licence or quality certificate was frozen or
  cancelled"; for those rows `notes` holds an HTML badge followed by the
  activity the body was licensed for.
- `type_description`: the code's Hebrew label.
- `notes`: free text. For labs: the service scope (research only / GAP /
  GMP batch release); for "other" licences: the sub-activity; for frozen or
  cancelled rows: the former activity (after the badge markup).

The page groups both active licences (by their description) and frozen or
cancelled ones (by the former activity in `notes`) into supply-chain stages
with one keyword classifier, so the two can be compared stage by stage.

Growth: the file is replaced in place. New codes or descriptions flow
through: the stage classifier falls back to the cleaned description itself,
unknown stages are appended after the known chain order (by size), and
sub-activity charts are capped at top-N plus a bucket for the rest. Exact
duplicate rows are dropped and the drop is disclosed.
"""
import re

import pandas as pd

MIN_STAGE_ROWS = 5      # a stage needs this many records for the frozen-rate chart/rule
HIGH_FROZEN = 0.40      # frozen share that counts as high for a stage
OTHER_TOP = 6           # sub-activities of "other" shown before folding
COMBO_TOP = 8           # stage combinations shown on the multi-licence chart
LEAD_SHARE = 0.25       # "other" share that earns its own insight

NOT_SPECIFIED = "לא צוין"

# (keyword(s), stage label) in match order. Order matters: "שתילי" before
# "גידול" (a former "אתר גידול (שתילי קנביס)" is a propagation site).
STAGE_RULES = [
    (("שתיל", "ריבוי"), "ריבוי שתילים"),
    (("תפרחות", "גידול"), "גידול תפרחות"),
    (("ייצור",), "מפעל ייצור"),
    (("שינוע",), "שינוע"),
    (("מסחר",), "בית מסחר"),
    (("מעבד",), "מעבדת בדיקה ומחקר"),
    (("התעדה",), "גוף התעדה"),
    (("השמדה",), "אתר השמדה"),
    (("עומס מיקרוביאלי", "אחר"), "אחר"),
]
STAGE_ORDER = [s for _, s in STAGE_RULES]
UPSTREAM = {"ריבוי שתילים", "גידול תפרחות"}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{v * 100:.{digits}f}%"


def clean(s):
    s = str(s).replace("\\n", " ")
    s = re.sub(r"<[^>]*>", " ", s)
    s = s.replace("​", "").replace("‏", "").replace("‎", "").replace("\xa0", " ")
    return " ".join(s.split())


def stage_of(text):
    t = clean(text)
    if not t:
        return NOT_SPECIFIED
    for keys, label in STAGE_RULES:
        if any(k in t for k in keys):
            return label
    t = re.sub(r"\s*בעל(?:ת)? רישיון עיסוק\s*$", "", t)
    return t or NOT_SPECIFIED


def is_frozen(code, desc):
    d = clean(desc)
    return ("הוקפא" in d) or ("בוטל" in d) or (clean(code) == "10" and not d)


def lab_scope(note):
    t = clean(note)
    if not t:
        return NOT_SPECIFIED
    if "GMP" in t:
        return "מחקר ושחרור אצוות GAP ו-GMP"
    if "GAP" in t:
        return "מחקר ושחרור אצוות GAP"
    if "מחקר" in t:
        return "שירותי מחקר בלבד"
    return t


def legal_form(name):
    s = clean(name)
    if re.search(r"אגש|אגודה", s):
        return "אגודה שיתופית"
    if re.search(r"שותפות", s):
        return "שותפות"
    if re.search(r"(?:בעי?|ע)\s*[\"'״׳]{1,2}\s*מ|בעמ(?:\s|$)|\bLtd\b", s, flags=re.I):
        return "חברה בע\"מ"
    if re.search(r"עמות|ע[\"'״׳]+ר(?:\s|$)", s):
        return "עמותה"
    return "ללא ציון צורה משפטית"


def name_key(s):
    s = clean(s).replace("''", '"').replace("״", '"').replace("׳", "'")
    return " ".join(s.split())


FORM_ORDER = ["חברה בע\"מ", "שותפות", "אגודה שיתופית", "עמותה", "ללא ציון צורה משפטית"]


def order_stages(present, counts):
    known = [s for s in STAGE_ORDER if s in present]
    extra = sorted([s for s in present if s not in STAGE_ORDER and s != NOT_SPECIFIED],
                   key=lambda s: (-int(counts.get(s, 0)), s))
    tail = [NOT_SPECIFIED] if NOT_SPECIFIED in present else []
    return known + extra + tail


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    last = items[-1]
    conj = " ו-" if last[:1].isdigit() else " ו"
    return ", ".join(items[:-1]) + conj + last


def compute(frames):
    raw = frames["main"]
    df = pd.DataFrame({
        "name": raw["company_name"].map(name_key),
        "code": raw["type"].map(clean),
        "desc": raw["type_description"].map(clean),
        "note": raw["notes"].map(clean),
    })
    total_raw = len(df)
    df = df[df["name"] != ""]
    no_name = total_raw - len(df)
    before = len(df)
    df = df.drop_duplicates(subset=["name", "code", "desc", "note"])
    dups = before - len(df)
    df = df.sort_values(["code", "desc", "name", "note"], kind="mergesort").reset_index(drop=True)
    total = len(df)

    df["frozen"] = [is_frozen(c, d) for c, d in zip(df["code"], df["desc"])]
    df["stage"] = [stage_of(nt) if fz else stage_of(d)
                   for fz, d, nt in zip(df["frozen"], df["desc"], df["note"])]
    act = df[~df["frozen"]]
    frz = df[df["frozen"]]
    n_act, n_frz = len(act), len(frz)
    bodies_all = int(df["name"].nunique())
    bodies_act = int(act["name"].nunique())
    frozen_share = n_frz / total if total else 0.0

    # ---- chain: active vs frozen per stage ------------------------------
    sc_all = df["stage"].value_counts()
    sa = act["stage"].value_counts()
    sf = frz["stage"].value_counts()
    stages = order_stages(set(df["stage"]), sc_all)
    chain = {
        "names": stages,
        "active": [int(sa.get(s, 0)) for s in stages],
        "frozen": [int(sf.get(s, 0)) for s in stages],
    }
    tbl_chain = []
    rate_rows = []
    for s in stages:
        a, f = int(sa.get(s, 0)), int(sf.get(s, 0))
        r = f / (a + f) if a + f else 0.0
        tbl_chain.append({"name": s, "active": n(a), "frozen": n(f), "rate": pct(r)})
        if a + f >= MIN_STAGE_ROWS and s != NOT_SPECIFIED:
            rate_rows.append((s, r, a, f))
    rate_rows.sort(key=lambda x: (-x[1], -(x[2] + x[3]), x[0]))
    chart_rate = {
        "names": [x[0] for x in rate_rows],
        "values": [round(x[1] * 100, 1) for x in rate_rows],
        "active": [x[2] for x in rate_rows],
        "frozen": [x[3] for x in rate_rows],
        "high": round(HIGH_FROZEN * 100, 1),
    }
    tbl_rate = [{"name": x[0], "rate": pct(x[1]), "active": n(x[2]), "frozen": n(x[3])}
                for x in rate_rows]

    # ---- multi-licence bodies -------------------------------------------
    per_body = act.groupby("name")["stage"].apply(lambda s: sorted(set(s))).to_dict()
    cnt_body = act.groupby("name").size()
    dist = cnt_body.value_counts()
    max_k = int(cnt_body.max()) if len(cnt_body) else 0
    dist_names, dist_vals = [], []
    for k in range(1, max_k + 1):
        if int(dist.get(k, 0)):
            dist_names.append("רישיון אחד" if k == 1 else f"{k} רישיונות")
            dist_vals.append(int(dist.get(k, 0)))
    multi = cnt_body[cnt_body > 1]
    n_multi = int(len(multi))
    combo_counts = {}
    for name in multi.index:
        key = " + ".join(per_body[name])
        combo_counts[key] = combo_counts.get(key, 0) + 1
    combos = sorted(combo_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = combos[:COMBO_TOP]
    rest = sum(v for _, v in combos[COMBO_TOP:])
    chart_combo = {"names": [k for k, _ in shown] + (["צירופים אחרים"] if rest else []),
                   "values": [v for _, v in shown] + ([rest] if rest else [])}
    tbl_multi = [{"name": nm, "count": n(cnt_body[nm]), "stages": ", ".join(per_body[nm])}
                 for nm in sorted(multi.index, key=lambda x: (-int(cnt_body[x]), x))]
    integrated = sum(1 for nm in multi.index if len(set(per_body[nm]) & UPSTREAM) == 2)

    # ---- labs scope ------------------------------------------------------
    labs = act[act["stage"] == "מעבדת בדיקה ומחקר"]
    lab_vc = labs["note"].map(lab_scope).value_counts()
    lab_order = ["שירותי מחקר בלבד", "מחקר ושחרור אצוות GAP", "מחקר ושחרור אצוות GAP ו-GMP"]
    lab_names = [x for x in lab_order if int(lab_vc.get(x, 0))]
    lab_names += sorted([x for x in lab_vc.index if x not in lab_order and x != NOT_SPECIFIED],
                        key=lambda x: (-int(lab_vc[x]), x))
    if int(lab_vc.get(NOT_SPECIFIED, 0)):
        lab_names.append(NOT_SPECIFIED)
    chart_labs = {"names": lab_names, "values": [int(lab_vc[x]) for x in lab_names]}
    n_labs = len(labs)
    n_gmp = int(lab_vc.get("מחקר ושחרור אצוות GAP ו-GMP", 0))
    n_research_only = int(lab_vc.get("שירותי מחקר בלבד", 0))

    # ---- "other" sub-activities ----------------------------------------
    oth = act[act["stage"] == "אחר"]
    ovc = oth["note"].map(lambda t: t if t else NOT_SPECIFIED).value_counts()
    o_spec = sorted([x for x in ovc.index if x != NOT_SPECIFIED], key=lambda x: (-int(ovc[x]), x))
    o_shown = o_spec[:OTHER_TOP]
    o_rest = sum(int(ovc[x]) for x in o_spec[OTHER_TOP:])
    o_names = list(o_shown) + (["פעילויות מפורטות אחרות"] if o_rest else [])
    o_vals = [int(ovc[x]) for x in o_shown] + ([o_rest] if o_rest else [])
    if int(ovc.get(NOT_SPECIFIED, 0)):
        o_names.append("ללא פירוט")
        o_vals.append(int(ovc[NOT_SPECIFIED]))
    chart_other = {"names": o_names, "values": o_vals}
    n_oth = len(oth)
    n_oth_spec = n_oth - int(ovc.get(NOT_SPECIFIED, 0))

    # ---- legal form (active bodies) -------------------------------------
    forms = pd.Series({nm: legal_form(nm) for nm in act["name"].unique()}, dtype=object)
    fvc = forms.value_counts()
    f_names = [f for f in FORM_ORDER if int(fvc.get(f, 0))]
    chart_form = {"names": f_names, "values": [int(fvc[f]) for f in f_names]}

    # ---- data quality ----------------------------------------------------
    both = sorted(set(act["name"]) & set(frz["name"]))
    frz_dupe_names = int((frz.groupby("name").size() > 1).sum())
    frz_unspec = int((frz["stage"] == NOT_SPECIFIED).sum())
    quality = [
        ("רשומות כפולות (אותו גוף, סוג והערה) שהוסרו מהספירה", dups),
        ("גופים המופיעים גם כפעילים וגם כמוקפאים או מבוטלים", len(both)),
        ("גופים מוקפאים או מבוטלים עם יותר מרשומה אחת", frz_dupe_names),
        ("רשומות מוקפאות או מבוטלות ללא ציון הפעילות הקודמת", frz_unspec),
    ]
    if no_name:
        quality.append(("רשומות ללא שם גוף", no_name))
    tbl_quality = [{"name": k, "count": n(v)} for k, v in quality]

    # ---- KPIs ----------------------------------------------------------
    tone_share = "danger" if frozen_share >= 0.30 else ("warn" if frozen_share >= 0.10 else "ok")
    kpis = {
        "active": {"value": n_act, "display": n(n_act), "tone": "brand"},
        "bodies": {"value": bodies_act, "display": n(bodies_act), "tone": "brand"},
        "frozen": {"value": n_frz, "display": n(n_frz), "tone": "warn" if n_frz else "ok"},
        "share": {"value": round(frozen_share * 100, 1), "display": pct(frozen_share, 1),
                  "tone": tone_share},
    }

    # ---- insights -----------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_lead():
        known = [(s, int(sa.get(s, 0))) for s in stages if s not in ("אחר", NOT_SPECIFIED)]
        known = [x for x in known if x[1] > 0]
        if not known or n_act == 0:
            return None
        known.sort(key=lambda x: (-x[1], STAGE_ORDER.index(x[0]) if x[0] in STAGE_ORDER else 99, x[0]))
        s1, v1 = known[0]
        txt = f"בין תחומי הפעילות המוגדרים, הנפוץ ביותר הוא {s1}: {n(v1)} רישיונות פעילים ({pct(v1 / n_act)})."
        if len(known) > 1:
            s2, v2 = known[1]
            if v2 == v1:
                return None
            txt += f" אחריו {s2} עם {n(v2)}."
        return txt
    add("lead", ins_lead())

    def ins_other():
        if n_act == 0 or n_oth / n_act < LEAD_SHARE:
            return None
        s = (f"{pct(n_oth / n_act)} מהרישיונות הפעילים ({n(n_oth)}) רשומים בקטגוריה \"אחר\", "
             f"הגדולה ברשימה.")
        if n_oth_spec < n_oth:
            s += f" רק ב-{n(n_oth_spec)} מהם ההערות מפרטות את סוג הפעילות."
        return s
    add("other", ins_other())

    def ins_frozen():
        if n_frz == 0 or total == 0:
            return None
        return (f"{n(n_frz)} מתוך {n(total)} הרשומות ({pct(frozen_share)}) הן של גופים "
                f"שרישיונם או תעודת האיכות שלהם הוקפאו או בוטלו. לפני התקשרות כדאי לבדוק "
                f"שהגוף מופיע ברשימה כבעל רישיון בתוקף.")
    add("frozen", ins_frozen())

    def ins_rate():
        if not rate_rows:
            return None
        s, r, a, f = rate_rows[0]
        if r < HIGH_FROZEN:
            return None
        if f > a:
            return (f"ב{s} יש יותר רישיונות מוקפאים או מבוטלים ({n(f)}) מרישיונות פעילים "
                    f"({n(a)}): {pct(r)} מהרשומות בתחום. זה שיעור ההקפאה הגבוה ביותר "
                    f"מבין התחומים עם {n(MIN_STAGE_ROWS)} רשומות לפחות.")
        return (f"שיעור ההקפאה או הביטול הגבוה ביותר הוא ב{s}: {pct(r)} ({n(f)} מוקפאים "
                f"או מבוטלים לעומת {n(a)} פעילים), מבין התחומים עם {n(MIN_STAGE_ROWS)} רשומות לפחות.")
    add("rate", ins_rate())

    def ins_multi():
        if n_multi < 2 or not combos:
            return None
        top, tv = combos[0]
        if tv == n_multi:
            return f"{n(n_multi)} גופים מחזיקים יותר מרישיון פעיל אחד, כולם בצירוף {top}."
        s = (f"{n(n_multi)} גופים מחזיקים יותר מרישיון פעיל אחד. הצירוף הנפוץ: {top} "
             f"({n(tv)} גופים).")
        if integrated and integrated != tv:
            s += f" {n(integrated)} גופים מחזיקים גם אתר ריבוי שתילים וגם אתר גידול תפרחות."
        return s
    add("multi", ins_multi())

    def ins_labs():
        if n_labs < 3:
            return None
        bits = []
        if n_gmp:
            bits.append(f"{n(n_gmp)} מורשות גם לבדיקות שחרור אצוות GMP")
        if n_research_only:
            bits.append(f"{n(n_research_only)} מורשות לשירותי מחקר בלבד")
        if not bits:
            return None
        return f"מתוך {n(n_labs)} מעבדות הבדיקה והמחקר הפעילות, {join_he(bits)}."
    add("labs", ins_labs())

    def ins_quality():
        if not dups and not both:
            return None
        bits = []
        if dups:
            bits.append("רשומה אחת מופיעה פעמיים ברשימה" if dups == 1
                        else f"{n(dups)} רשומות מופיעות פעמיים ברשימה")
        if both:
            bits.append("גוף אחד מופיע גם כפעיל וגם כמוקפא או מבוטל" if len(both) == 1
                        else f"{n(len(both))} גופים מופיעים גם כפעילים וגם כמוקפאים או מבוטלים")
        s = f"איכות הנתונים: {join_he(bits)}."
        if dups:
            s += " הכפילויות לא נספרו."
        return s
    add("quality", ins_quality())

    # ---- labels --------------------------------------------------------
    lede = (f"רשימת משרד הבריאות של הגופים בעלי רישיון מהיחידה לקנביס רפואי (יק\"ר) לעיסוק "
            f"בקנביס לשימוש רפואי ולמחקר: אתרי ריבוי וגידול, מפעלי ייצור, בתי מסחר, גופי שינוע, "
            f"מעבדות, גופי התעדה ואתרי השמדה. ברשימה {n(total)} רשומות של {n(bodies_all)} גופים: "
            f"{n(n_act)} רישיונות פעילים של {n(bodies_act)} גופים, ועוד {n(n_frz)} רשומות של גופים "
            f"שרישיונם הוקפא או בוטל.")
    seedling_grow = int(sum(1 for t in frz["note"] if "גידול" in t and "שתיל" in t))
    big_stage = max(stages, key=lambda s: (int(sc_all.get(s, 0)), s)) if stages else ""
    labels = {
        "lede": lede,
        "lookup_sub": (f"חיפוש חי בכל {n(total_raw)} הרשומות: שם החברה או הגוף, תחום הפעילות "
                       f"וההערות (כולל רישיון מוקפא או מבוטל)."),
        "active_kpi": "רישיונות עיסוק פעילים",
        "bodies_kpi": "גופים עם רישיון פעיל",
        "frozen_kpi": "רשומות מוקפאות או מבוטלות",
        "share_kpi": "שיעור המוקפאים או המבוטלים מכלל הרשומות",
        "chain_note": (f"מספר הרישיונות בכל שלב בשרשרת האספקה, פעילים לצד מוקפאים או מבוטלים "
                       f"(לפי הפעילות שצוינה להם). הגדול ביותר: {big_stage} "
                       f"({n(sc_all.get(big_stage, 0))} רשומות)."
                       + (f" {n(seedling_grow)} רשומות מוקפאות שתוארו כאתר גידול שתילים נספרו "
                          f"בריבוי שתילים." if seedling_grow else "")),
        "chain_aria": (f"גרף עמודות מוערמות: רישיונות פעילים ומוקפאים לפי תחום פעילות, "
                       f"{n(n_act)} פעילים ו-{n(n_frz)} מוקפאים או מבוטלים."),
        "rate_note": (f"שיעור הרשומות המוקפאות או המבוטלות מכלל הרשומות בכל תחום (תחומים עם "
                      f"{n(MIN_STAGE_ROWS)} רשומות לפחות). שיעור של {pct(HIGH_FROZEN)} ומעלה מסומן באדום."),
        "rate_aria": ("גרף עמודות: שיעור הרישיונות המוקפאים או המבוטלים בכל תחום פעילות"
                      + (f". הגבוה ביותר: {rate_rows[0][0]}, {pct(rate_rows[0][1])}." if rate_rows else ".")),
        "multi_note": (f"{n(n_multi)} מתוך {n(bodies_act)} הגופים הפעילים מחזיקים יותר מרישיון אחד. "
                       f"הגרף מראה אילו צירופי תחומים נפוצים אצלם."),
        "multi_aria": (f"גרף עמודות: צירופי תחומי פעילות של {n(n_multi)} גופים עם יותר מרישיון פעיל אחד."),
        "dist_aria": f"התפלגות {n(bodies_act)} הגופים הפעילים לפי מספר הרישיונות הפעילים שלהם.",
        "labs_note": (f"היקף השירותים של {n(n_labs)} מעבדות הבדיקה והמחקר הפעילות, לפי ההערות ברשימה."),
        "labs_aria": f"גרף עמודות: {n(n_labs)} מעבדות בדיקה ומחקר לפי היקף השירות.",
        "other_note": (f"{n(n_oth)} רישיונות פעילים רשומים בקטגוריה \"גוף עיסוק בקנביס - אחר\". "
                       f"בחלקם ההערות מפרטות את סוג הפעילות."),
        "other_aria": f"גרף עמודות: {n(n_oth)} רישיונות בקטגוריה אחר לפי הפעילות שצוינה.",
        "form_note": (f"צורת ההתאגדות של {n(bodies_act)} הגופים הפעילים, כפי שהיא עולה מהשם "
                      f"(בע\"מ, שותפות, אגודה שיתופית). שם ללא ציון צורה הוא לרוב עוסק או שם מסחרי."),
        "form_aria": (f"גרף עוגה: {n(bodies_act)} גופים פעילים לפי צורת ההתאגדות שבשם."
                      + (f" הנפוצה: {f_names[0]}, {n(fvc[f_names[0]])}." if f_names else "")),
        "quality_note": "ספירות שנבדקו ברשימה. הרשימה אינה כוללת תאריכי מתן רישיון, תוקף או יישוב.",
    }

    summary = (f"בדיקה אם לחברה יש רישיון עיסוק בקנביס רפואי מהיק\"ר: {n(n_act)} רישיונות פעילים "
               f"של {n(bodies_act)} גופים, ו-{n(n_frz)} מוקפאים או מבוטלים.")
    if len(summary) > 155:
        summary = f"בדיקה אם לחברה יש רישיון עיסוק בקנביס רפואי מהיק\"ר: {n(n_act)} רישיונות פעילים."

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["קנביס רפואי", "רישוי", "יק\"ר", "משרד הבריאות", "שרשרת אספקה"],
            "related_ids": [
                "0952e5e4-8910-477a-8ba3-cde48f4c048f",
                "2721d62d-d0da-45fd-93ac-5e7809849222",
                "54601127-7b82-4bd7-ad80-271a802fdeeb",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {"chain": chain, "rate": chart_rate, "combo": chart_combo,
                   "labs": chart_labs, "other": chart_other, "form": chart_form},
        "tables": {"chain": tbl_chain, "rate": tbl_rate, "multi": tbl_multi,
                   "dist": [{"name": a, "count": n(b)} for a, b in zip(dist_names, dist_vals)],
                   "combo": [{"name": a, "count": n(b)} for a, b in zip(chart_combo["names"], chart_combo["values"])],
                   "labs": [{"name": a, "count": n(b)} for a, b in zip(chart_labs["names"], chart_labs["values"])],
                   "other": [{"name": a, "count": n(b)} for a, b in zip(o_names, o_vals)],
                   "form": [{"name": a, "count": n(b)} for a, b in zip(f_names, chart_form["values"])],
                   "quality": tbl_quality},
        "insights": insights,
        "labels": labels,
        "flags": {
            "rate": len(rate_rows) >= 2,
            "multi": n_multi >= 2,
            "labs": len(lab_names) >= 2,
            "other": len(o_names) >= 2,
            "form": len(f_names) >= 2,
        },
    }
