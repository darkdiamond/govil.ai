"""אוגדן השכלות (נציבות שירות המדינה): degree catalogue used to check the
education threshold in civil-service tenders.

One row per (institution, field, degree). The CSV export carries rows broken
by multi-line explanation text: fragments of an explanation spill into the
next row's columns. A row is kept only when Degree_level looks like a degree
code (Latin letters, dots, slashes); the rest are counted and disclosed.
"""
import re

import pandas as pd
from govlib import fmt, frame

NONE_VALUES = {"", "אין", "-", "–"}
UNCLASSIFIED = "לא סווג"
NO_FACULTY = "לא צוין"

# Degree codes start with B/M/L/D/P (B.A, M.Sc, LL.B, D.M.D, PharmD); this also
# keeps spilled English fragments like "HTML" or "STEM" out.
DEG_RE = re.compile(r"\.?[BbMmLlDdPp][A-Za-z .\/]{0,24}")

# Known spellings of the same institution (fallback: the name as written).
INST_ALIASES = {
    "האוניברסיטה העברית": "האוניברסיטה העברית בירושלים",
    "אוניברסיטה העברית": "האוניברסיטה העברית בירושלים",
    "אוניברסיטה העברית בירושלים": "האוניברסיטה העברית בירושלים",
    "הטכניון": "טכניון",
    "אוניברסיטת בן גוריון בנגב": "אוניברסיטת בן גוריון",
    "אוניבסיטת חיפה": "אוניברסיטת חיפה",
    "אוניברסיטה הפתוחה": "האוניברסיטה הפתוחה",
    "המכרז הבינתחומי הרצליה (רייכמן)": "אוניברסיטת רייכמן",
    "אוניברסיטת רייכמן הרצליה": "אוניברסיטת רייכמן",
    "המרכז האקדמי למשפט ולעסקים": "המרכז האקדמי למשפט ועסקים",
    "המכרז האקדמי לב": "המרכז האקדמי לב",
    "המכון הטכנולוגי חולון": "מכון טכנולוגי חולון - HIT",
    "מכללה אקדמית הדסה ירושלים": "המכללה האקדמית הדסה ירושלים",
    "מכללת עמק יזרעאל": "המכללה האקדמית עמק יזרעאל",
    "המכללה האקדמית עמק ישראל": "המכללה האקדמית עמק יזרעאל",
    "המכללה האקדמית תל-אביב יפו": "המכללה האקדמית תל אביב יפו",
    "המכללה האקדמית תל-חי": "המכללה האקדמית תל חי",
}

# Content-world spellings that name the same CBS-style field group.
CW_ALIASES = {
    "מדעים ביולוגיה וחקלאות": "המדעים הביולוגיים וחקלאות",
    "מדעים ביולוגיים וחקלאות": "המדעים הביולוגיים וחקלאות",
    "מדעים פיזיקליים": "המדעים הפיזיקליים",
    "מתמטיקה סטטיסטיקה ומדעי מחשב": "מתמטיקה, סטטיסטיקה ומדעי מחשב",
    "מדעי רוח כלליים": "מדעי רוח הכללים",
}

# Words in an institution's name that place it abroad (or outside Israel's
# higher-education system). Order does not matter.
FOREIGN_MARKERS = (
    'ארה"ב', "ארצות הברית", "בריטניה", "אוקראינ", "רוסיה", "ברית המועצות",
    "גרמניה", "הולנד", "צרפת", "(ירדן)", "רבת עמון", "אירן", "ברזיל", "צ'ילה", "בלירוסיה",
    "גרוזיה", "אוזבקיסטן", "ניו יורק", "יהודה ושומרון", "אל-קודס",
    "בית לחם", "ביר זית", "קולג'", "יוניברסיטי", "המכון המלכותי",
)

T_UNI = "אוניברסיטאות"
T_EDU = "מכללות לחינוך"
T_COL = "מכללות ומרכזים אקדמיים"
T_FOR = "מוסדות מחוץ לישראל"
TYPE_ORDER = [T_UNI, T_EDU, T_COL, T_FOR]

S_BA = "תואר ראשון"
S_MA = "תואר שני"
S_DR = "תואר שלישי ומקצועות רפואה"
S_OT = "אחר"
STAGE_ORDER = [S_BA, S_MA, S_DR, S_OT]
DOCTOR_KEYS = {"MD", "DMD", "DVM", "PHARMD", "PHD"}

C_ONE, C_TWO, C_MIX = "חד-חוגי", "דו-חוגי", "משולב"


def _inst(name: str) -> str:
    return INST_ALIASES.get(name, name)


def _inst_key(name: str) -> str:
    # Spellings that differ only in dashes/spacing are one institution.
    return re.sub(r"[\s\-–]+", " ", name).strip()


def _inst_type(name: str) -> str:
    if any(m in name for m in FOREIGN_MARKERS):
        return T_FOR
    if "אוניברסיט" in name or "טכניון" in name or "מכון ויצמן" in name:
        return T_UNI
    if "לחינוך" in name or "הוראה" in name or "סמינר" in name:
        return T_EDU
    return T_COL


def _deg_key(raw: str) -> str:
    key = re.sub(r"[^A-Z/]", "", raw.upper())
    first = key.split("/")[0]
    return first or key.replace("/", "")


def _stage(key: str) -> str:
    if key in DOCTOR_KEYS:
        return S_DR
    if key.startswith("B") or key == "LLB":
        return S_BA
    if key.startswith("M") or key == "LLM":
        return S_MA
    return S_OT


def _world(v: str) -> str:
    v = CW_ALIASES.get(v, v)
    if v in NONE_VALUES or len(v) > 45 or any(ch in v for ch in '."״'):
        return UNCLASSIFIED
    return v


def _faculty(v: str) -> str:
    if v in NONE_VALUES or len(v) > 25 or any(ch in v for ch in '."״'):
        return NO_FACULTY
    return v


def _combo(v: str) -> str:
    if v.startswith("דו"):
        return C_TWO
    if v == "חד":
        return C_ONE
    if v == "משולב":
        return C_MIX
    return S_OT


def _short(s: str, n: int = 40) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _counts_in_order(series: pd.Series, order) -> list:
    vc = series.value_counts()
    return [int(vc.get(k, 0)) for k in order]


def _pct(part, whole) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def compute(frames):
    raw = frames["main"].copy()
    for c in raw.columns:
        raw[c] = frame.clean_series(raw[c])
    total_rows = len(raw)

    ok = (
        raw["Degree_level"].str.fullmatch(DEG_RE).fillna(False)
        & (raw["institution_name"] != "")
        & (raw["Field_of_Education"] != "")
        & (raw["institution_name"].str.len() <= 120)
    )
    df = raw[ok].copy()
    dropped = total_rows - len(df)
    if df.empty:
        raise ValueError("no well-formed rows")

    df["inst"] = df["institution_name"].map(_inst)
    # Display each institution under its most common spelling.
    ik = df["inst"].map(_inst_key)
    inst_disp = (
        df.assign(ik=ik).groupby(["ik", "inst"]).size().reset_index(name="c")
        .sort_values(["ik", "c", "inst"], ascending=[True, False, True], kind="stable")
        .drop_duplicates("ik").set_index("ik")["inst"]
    )
    df["inst"] = ik.map(inst_disp)
    df["itype"] = df["inst"].map(_inst_type)
    df["deg_key"] = df["Degree_level"].map(_deg_key)
    df["stage"] = df["deg_key"].map(_stage)
    df["world"] = df["Content_worlds"].map(_world)
    df["faculty"] = df["Faculty_Name"].map(_faculty)
    df["combo"] = df["One_Two_Combo"].map(_combo)
    df["field"] = df["Field_of_Education"].str.strip(" \"'״")
    df["has_parallel"] = ~df["Parallel_Foreign_Degree"].isin(NONE_VALUES)
    df["has_place"] = ~df["Placement_recommendations"].isin(NONE_VALUES)
    df["has_note"] = ~df["Regular_updates"].isin(NONE_VALUES)
    df["has_expl"] = ~df["Explanations"].isin(NONE_VALUES)

    n = len(df)
    n_inst = int(df["inst"].nunique())
    n_field = int(df["field"].nunique())

    # Degree display label: the most common spelling of each normalised code.
    spell = (
        df.assign(deg_disp=df["Degree_level"].str.strip(". "))
        .groupby(["deg_key", "deg_disp"]).size().reset_index(name="c")
        .sort_values(["deg_key", "c", "deg_disp"], ascending=[True, False, True], kind="stable")
        .drop_duplicates("deg_key")
        .set_index("deg_key")["deg_disp"]
    )
    df["deg_label"] = df["deg_key"].map(spell)

    charts, tables, labels, kpis = {}, {}, {}, {}

    # --- stages -------------------------------------------------------------
    stage_counts = _counts_in_order(df["stage"], STAGE_ORDER)
    stage_pairs = [(s, c) for s, c in zip(STAGE_ORDER, stage_counts) if c > 0]
    charts["stage"] = [{"name": s, "value": c} for s, c in stage_pairs]
    tables["stage"] = [[s, fmt.int_he(c), fmt.pct_of(_pct(c, n))] for s, c in stage_pairs]
    n_ba, n_ma, n_dr = stage_counts[0], stage_counts[1], stage_counts[2]
    stages_present = [s for s, _ in stage_pairs]

    # --- content worlds × stage -------------------------------------------
    wc = frame.ranked(df.loc[df["world"] != UNCLASSIFIED, "world"])
    w_labels, _ = frame.top_other(wc, 11)
    w_known = [w for w in w_labels if w != frame.OTHER]
    df["world_b"] = df["world"].where(df["world"].isin(w_known) | (df["world"] == UNCLASSIFIED), frame.OTHER)
    world_order = w_labels + ([UNCLASSIFIED] if (df["world"] == UNCLASSIFIED).any() else [])
    ws = df.groupby(["world_b", "stage"]).size()
    charts["world"] = {
        "names": world_order,
        "series": [
            {"name": s, "data": [int(ws.get((w, s), 0)) for w in world_order]}
            for s in stages_present
        ],
    }
    world_tot = df["world_b"].value_counts()
    tables["world"] = [
        [w] + [fmt.int_he(ws.get((w, s), 0)) for s in stages_present] + [fmt.int_he(world_tot.get(w, 0))]
        for w in world_order
    ]
    tables["world_cols"] = ["עולם תוכן"] + stages_present + ["סה״כ"]

    # --- faculty -------------------------------------------------------------
    fc = frame.ranked(df["faculty"])
    f_labels, f_values = frame.top_other(fc, 10)
    charts["faculty"] = {"names": f_labels, "values": f_values}
    tables["faculty"] = [[a, fmt.int_he(b), fmt.pct_of(_pct(b, n))] for a, b in zip(f_labels, f_values)]

    # --- degree titles -------------------------------------------------------
    dc = frame.ranked(df["deg_label"])
    d_labels, d_values = frame.top_other(dc, 12)
    charts["degrees"] = {"names": d_labels, "values": d_values}
    tables["degrees"] = [[a, fmt.int_he(b)] for a, b in zip(d_labels, d_values)]
    n_deg_titles = int(df["deg_key"].nunique())

    # --- institutions --------------------------------------------------------
    ic = frame.ranked(df["inst"])
    top_inst = list(ic.index[:15])
    ist = df[df["inst"].isin(top_inst)].groupby(["inst", "stage"]).size()
    charts["inst"] = {
        "names": top_inst,
        "series": [
            {"name": s, "data": [int(ist.get((i, s), 0)) for i in top_inst]}
            for s in stages_present
        ],
    }
    i_fields = df.groupby("inst")["field"].nunique()
    tables["inst"] = [[i, fmt.int_he(ic[i]), fmt.int_he(i_fields[i])] for i in top_inst]

    # --- institution types ---------------------------------------------------
    types_present = [t for t in TYPE_ORDER if (df["itype"] == t).any()]
    t_rows = _counts_in_order(df["itype"], types_present)
    t_inst = [int(df.loc[df["itype"] == t, "inst"].nunique()) for t in types_present]
    t_expl = [
        _pct(int(df.loc[df["itype"] == t, "has_expl"].sum()), c)
        for t, c in zip(types_present, t_rows)
    ]
    charts["types"] = {"names": types_present, "rows": t_rows, "inst": t_inst, "expl": t_expl}
    tables["types"] = [
        [t, fmt.int_he(r), fmt.int_he(i), fmt.pct_of(e)]
        for t, r, i, e in zip(types_present, t_rows, t_inst, t_expl)
    ]

    # --- heatmap: content world × institution type ---------------------------
    hm_worlds = [w for w in world_order if w not in (frame.OTHER, UNCLASSIFIED)][:10]
    ht = df[df["world"].isin(hm_worlds)].groupby(["world", "itype"]).size()
    cells, hm_max = [], 0
    for yi, w in enumerate(hm_worlds):
        for xi, t in enumerate(types_present):
            v = int(ht.get((w, t), 0))
            hm_max = max(hm_max, v)
            cells.append([xi, yi, v])
    charts["heat"] = {"x": types_present, "y": hm_worlds, "cells": cells, "max": hm_max}
    tables["heat"] = [[w] + [fmt.int_he(ht.get((w, t), 0)) for t in types_present] for w in hm_worlds]
    tables["heat_cols"] = ["עולם תוכן"] + types_present

    # --- most widespread fields --------------------------------------------
    fi = (
        df.groupby("field")["inst"].nunique().rename("k").reset_index()
        .sort_values(["k", "field"], ascending=[False, True], kind="stable")
    )
    fi_top = fi.head(15)
    charts["fields"] = {"names": fi_top["field"].tolist(), "values": [int(v) for v in fi_top["k"]]}
    f_rows = df.groupby("field").size()
    tables["fields"] = [[f, fmt.int_he(k), fmt.int_he(f_rows[f])] for f, k in zip(fi_top["field"], fi_top["k"])]
    single_inst_fields = int((fi["k"] == 1).sum())

    # --- parallel degrees ----------------------------------------------------
    par = df.loc[df["has_parallel"], "Parallel_Foreign_Degree"]
    n_par = len(par)
    if n_par:
        p_labels, p_values = frame.top_other(frame.ranked(par), 8)
        charts["parallel"] = {"names": [_short(x) for x in p_labels], "values": p_values}
        tables["parallel"] = [[a, fmt.int_he(b)] for a, b in zip(p_labels, p_values)]

    # --- placement recommendations ------------------------------------------
    plc = df.loc[df["has_place"], "Placement_recommendations"]
    n_place = len(plc)
    if n_place:
        q_labels, q_values = frame.top_other(frame.ranked(plc), 8)
        charts["place"] = {"names": [_short(x) for x in q_labels], "values": q_values}
        tables["place"] = [[a, fmt.int_he(b)] for a, b in zip(q_labels, q_values)]

    n_note = int(df["has_note"].sum())
    n_expl = int(df["has_expl"].sum())
    n_two = int((df["combo"] == C_TWO).sum())
    n_for = int((df["itype"] == T_FOR).sum())
    n_for_inst = int(df.loc[df["itype"] == T_FOR, "inst"].nunique())
    expl_share = _pct(n_expl, n)

    # --- KPIs --------------------------------------------------------------
    kpis["entries"] = {"value": n, "display": fmt.int_he(n), "tone": "brand"}
    kpis["inst"] = {"value": n_inst, "display": fmt.int_he(n_inst), "tone": "brand"}
    kpis["fields"] = {"value": n_field, "display": fmt.int_he(n_field), "tone": "brand"}
    kpis["expl"] = {
        "value": expl_share,
        "display": fmt.pct_of(expl_share),
        "tone": "ok" if expl_share >= 80 else ("warn" if expl_share < 50 else "info"),
    }
    kpis["place"] = {"value": n_place, "display": fmt.int_he(n_place), "tone": "info"}
    kpis["foreign"] = {"value": n_for, "display": fmt.int_he(n_for), "tone": "brand"}

    # --- insights ----------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_world():
        if wc.empty:
            return None
        w = wc.index[0]
        c = int(wc.iloc[0])
        share = c / n
        if share < 0.12:
            return None
        ba = int(ws.get((w, S_BA), 0))
        ma = int(ws.get((w, S_MA), 0))
        second = ""
        if len(wc) > 1:
            second = f" אחריו {wc.index[1]} ({fmt.int_he(wc.iloc[1])})."
        return (
            f"עולם התוכן הגדול באוגדן הוא {w}: {fmt.int_he(c)} תארים ({fmt.pct(share)}), "
            f"מהם {fmt.int_he(ba)} לתואר ראשון ו-{fmt.int_he(ma)} לתואר שני.{second}"
        )

    def ins_unis():
        uni = df["itype"] == T_UNI
        if not uni.any() or ic.empty:
            return None
        u_rows = int(uni.sum())
        u_n = int(df.loc[uni, "inst"].nunique())
        top, top_c = ic.index[0], int(ic.iloc[0])
        return (
            (f"{fmt.int_he(u_n)} אוניברסיטאות מחזיקות" if u_n > 1 else "אוניברסיטה אחת מחזיקה")
            + f" {fmt.int_he(u_rows)} מהתארים באוגדן "
            f"({fmt.pct(u_rows / n)}), אף שהאוגדן מונה {fmt.int_he(n_inst)} מוסדות. "
            f"המוסד עם מספר התארים הרב ביותר: {top} ({fmt.int_he(top_c)})."
        )

    def ins_field():
        if fi.empty:
            return None
        f, k = fi.iloc[0]["field"], int(fi.iloc[0]["k"])
        if k < 3:
            return None
        txt = f"תחום ההשכלה הנפוץ ביותר הוא {f}, שמופיע ב-{fmt.int_he(k)} מוסדות שונים."
        if single_inst_fields:
            txt += (
                f" מנגד, {fmt.int_he(single_inst_fields)} מתוך {fmt.int_he(n_field)} תחומי השכלה "
                f"({fmt.pct(single_inst_fields / n_field)}) מופיעים במוסד אחד בלבד."
            )
        return txt

    def ins_stage():
        if not n_ba or not n_ma:
            return None
        txt = f"באוגדן {fmt.int_he(n_ba)} תארים ראשונים ו-{fmt.int_he(n_ma)} תארים שניים"
        if n_dr:
            txt += f", לצד {fmt.int_he(n_dr)} תארי דוקטור ומקצועות רפואה"
        top_deg, top_c = dc.index[0], int(dc.iloc[0])
        return txt + f". רמת התואר הנפוצה: {fmt.isolate(top_deg)} ({fmt.int_he(top_c)} תארים, מתוך {fmt.int_he(n_deg_titles)} סימוני תואר)."

    def ins_two():
        if n_two < 5:
            return None
        tw = frame.ranked(df.loc[(df["combo"] == C_TWO) & (df["world"] != UNCLASSIFIED), "world"])
        txt = f"{fmt.int_he(n_two)} תארים ({fmt.pct(n_two / n)}) מסומנים כדו-חוגיים; השאר ברובם חד-חוגיים."
        if not tw.empty and int(tw.iloc[0]) >= 3:
            txt += f" הדו-חוגיים מרוכזים בעיקר ב{tw.index[0]} ({fmt.int_he(tw.iloc[0])})."
        return txt

    def ins_parallel():
        if n_par < 5:
            return None
        top_p = frame.ranked(par)
        txt = (
            f"ל-{fmt.int_he(n_par)} תארים צוין תחום השכלה מקביל, שאליו התואר מוקבל בבדיקת תנאי הסף. "
            f"המקבילה הנפוצה: {_short(top_p.index[0])} ({fmt.int_he(top_p.iloc[0])})"
        )
        if len(top_p) > 1:
            txt += f", ואחריה {_short(top_p.index[1])} ({fmt.int_he(top_p.iloc[1])})"
        return txt + "."

    def ins_foreign():
        if n_for < 3:
            return None
        fw = frame.ranked(df.loc[(df["itype"] == T_FOR) & (df["world"] != UNCLASSIFIED), "world"])
        txt = (
            f"{fmt.int_he(n_for)} רשומות עוסקות בתארים מ-{fmt.int_he(n_for_inst)} מוסדות "
            f"מחוץ לישראל (זוהו לפי שם המדינה או העיר בשם המוסד)"
        )
        if not fw.empty and int(fw.iloc[0]) / n_for >= 0.3:
            txt += f", בעיקר בתחום {fw.index[0]} ({fmt.int_he(fw.iloc[0])})"
        return txt + "."

    def ins_place():
        if n_place < 5:
            return None
        tp = frame.ranked(plc)
        txt = f"ל-{fmt.int_he(n_place)} תארים ({fmt.pct(n_place / n)}) יש המלצת שיבוץ לתחום עיסוק"
        if len(tp) > 1:
            txt += f", בראשן {_short(tp.index[0])} ({fmt.int_he(tp.iloc[0])}) ו{_short(tp.index[1])} ({fmt.int_he(tp.iloc[1])})"
        return txt + "."

    def ins_expl():
        if len(types_present) < 2:
            return None
        lo = min(range(len(types_present)), key=lambda i: (t_expl[i], i))
        hi = max(range(len(types_present)), key=lambda i: (t_expl[i], -i))
        if t_expl[hi] - t_expl[lo] < 10:
            return f"ל-{fmt.pct_of(expl_share)} מהתארים מצורף הסבר מילולי על תוכן הלימודים, בשיעור דומה בכל סוגי המוסדות."
        return (
            f"ל-{fmt.pct_of(expl_share)} מהתארים מצורף הסבר מילולי על תוכן הלימודים. "
            f"השיעור הגבוה ביותר ב{types_present[hi]} ({fmt.pct_of(t_expl[hi])}) והנמוך ביותר ב{types_present[lo]} ({fmt.pct_of(t_expl[lo])})."
        )

    def ins_quality():
        if dropped <= 0:
            return None
        txt = (
            f"{fmt.int_he(dropped)} מתוך {fmt.int_he(total_rows)} שורות בקובץ אינן רשומות תקינות "
            f"(קטעי טקסט הסבר שגלשו לשורה נפרדת) ולא נכללו בניתוח"
        )
        if n_note:
            txt += f"; ל-{fmt.int_he(n_note)} רשומות תקינות צורפה הערת עדכון של הנציבות"
        return txt + "."

    for iid, fn in [
        ("world", ins_world), ("unis", ins_unis), ("field", ins_field),
        ("stage", ins_stage), ("parallel", ins_parallel), ("place", ins_place),
        ("two", ins_two), ("foreign", ins_foreign), ("expl", ins_expl),
        ("quality", ins_quality),
    ]:
        add(iid, fn())

    # --- labels ------------------------------------------------------------
    top_world = wc.index[0] if not wc.empty else ""
    labels["lede"] = (
        f"אוגדן ההשכלות של נציבות שירות המדינה משמש לבדיקת תנאי סף השכלה במכרזי כוח אדם. "
        f"הוא מונה {fmt.int_he(n)} תארים אקדמיים מ-{fmt.int_he(n_inst)} מוסדות, ב-{fmt.int_he(n_field)} תחומי השכלה, "
        f"וכל רשומה מציינת את הפקולטה, רמת התואר, עולם התוכן, תחום מקביל והמלצת שיבוץ כשיש."
    )
    labels["world_note"] = (
        f"מספר התארים בכל עולם תוכן, בפילוח לפי רמת תואר. {top_world} מוביל עם {fmt.int_he(wc.iloc[0])} תארים."
        if top_world else "מספר התארים בכל עולם תוכן, בפילוח לפי רמת תואר."
    )
    labels["world_aria"] = f"גרף עמודות מוערמות: תארים לפי עולם תוכן ורמת תואר. המוביל: {top_world}."
    f_lead = next(((a, b) for a, b in zip(f_labels, f_values) if a not in (NO_FACULTY, frame.OTHER)), None)
    labels["faculty_note"] = "הפקולטה או החטיבה שבה נלמד התואר." + (
        f" {f_lead[0]} מובילה עם {fmt.int_he(f_lead[1])} תארים." if f_lead else "")
    labels["faculty_aria"] = "גרף עמודות: תארים לפי פקולטה." + (
        f" המובילה: {f_lead[0]} עם {fmt.int_he(f_lead[1])}." if f_lead else "")
    labels["stage_note"] = f"חלוקת {fmt.int_he(n)} התארים לפי שלב התואר, לפי סימון רמת התואר."
    labels["stage_aria"] = f"גרף טבעת: תארים לפי שלב. תואר ראשון {fmt.int_he(n_ba)}, תואר שני {fmt.int_he(n_ma)}."
    labels["degrees_note"] = f"סימוני התואר הנפוצים (מאוחדים בין כתיבים שונים, {fmt.int_he(n_deg_titles)} סימונים בסך הכול)."
    labels["degrees_aria"] = f"גרף עמודות: סימוני התואר הנפוצים. הנפוץ: {d_labels[0]} עם {fmt.int_he(d_values[0])}."
    labels["inst_note"] = (
        f"המוסדות עם מספר התארים הרב ביותר באוגדן, בפילוח לפי רמת תואר. {top_inst[0]} מוביל עם {fmt.int_he(ic.iloc[0])} תארים."
    )
    labels["inst_aria"] = f"גרף עמודות אופקי: מוסדות לפי מספר תארים. המוביל: {top_inst[0]}."
    labels["types_note"] = (
        "מספר התארים והמוסדות לפי סוג מוסד (נקבע לפי שם המוסד), ושיעור התארים שמצורף להם הסבר מילולי."
    )
    labels["types_aria"] = f"גרף עמודות: תארים ומוסדות לפי סוג מוסד. {types_present[0]}: {fmt.int_he(t_rows[0])} תארים."
    labels["heat_note"] = "כמה תארים מכל עולם תוכן מופיעים בכל סוג מוסד. גוון כהה יותר הוא יותר תארים."
    labels["heat_aria"] = "מפת חום: עולמות תוכן מול סוגי מוסדות, מספר התארים בכל צירוף."
    labels["fields_note"] = (
        f"תחומי ההשכלה שמופיעים במספר הרב ביותר של מוסדות. {fi_top.iloc[0]['field']} מופיע ב-{fmt.int_he(fi_top.iloc[0]['k'])} מוסדות."
    )
    labels["fields_aria"] = f"גרף עמודות אופקי: תחומי השכלה לפי מספר המוסדות. המוביל: {fi_top.iloc[0]['field']}."
    if n_par:
        labels["parallel_note"] = (
            f"{fmt.int_he(n_par)} תארים שצוין להם תחום השכלה מקביל, שלפיו נבחן התואר בתנאי הסף (בעיקר תארים דו-חוגיים ותארים ממוסדות מחוץ לישראל)."
        )
        labels["parallel_aria"] = f"גרף עמודות: תחומי השכלה מקבילים. הנפוץ: {charts['parallel']['names'][0]}."
    if n_place:
        labels["place_note"] = f"{fmt.int_he(n_place)} תארים שצוינה להם המלצת שיבוץ לתחום עיסוק בשירות המדינה."
        labels["place_aria"] = f"גרף עמודות: המלצות שיבוץ. הנפוצה: {charts['place']['names'][0]}."
    labels["entries_kpi"] = "תארים באוגדן"
    labels["inst_kpi"] = "מוסדות לימוד"
    labels["fields_kpi"] = "תחומי השכלה"
    labels["expl_kpi"] = "תארים עם הסבר מילולי"
    labels["place_kpi"] = "תארים עם המלצת שיבוץ"
    labels["foreign_kpi"] = "רשומות של מוסדות מחוץ לישראל"

    summary = (
        f"אוגדן השכלות של נציבות שירות המדינה לבדיקת תנאי סף במכרזי כוח אדם: "
        f"{fmt.int_he(n)} תארים מ-{fmt.int_he(n_inst)} מוסדות ב-{fmt.int_he(n_field)} תחומי השכלה"
        + (f", המובילים: {top_world}." if top_world else ".")
    )
    description = (
        f"בדיקת תנאי סף השכלה במכרזי שירות המדינה: {fmt.int_he(n)} תארים מ-{fmt.int_he(n_inst)} מוסדות, "
        f"עם עולם תוכן, תחום מקביל והמלצת שיבוץ."
    )

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "אוגדן השכלות: בדיקת תנאי סף השכלה במכרזי המדינה",
                "description": description,
                "name": "אוגדן השכלות לבדיקת תנאי סף במכרזי שירות המדינה",
                "alternate_names": [
                    'אוגדן השכלות - לצורך בדיקת תנאי סף השכלה במכרזי כ"א בשירות המדינה',
                    "אוגדן השכלות נציבות שירות המדינה",
                    "תנאי סף השכלה במכרזי שירות המדינה",
                    "אוגדן תארים אקדמיים מוכרים",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "insights": insights,
        "flags": {"parallel": bool(n_par), "place": bool(n_place), "heat": len(hm_worlds) >= 2 and len(types_present) >= 2},
    }
