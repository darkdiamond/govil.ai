"""Parameter codes for environmental sampling reports (Ministry of Environmental Protection).

A small controlled vocabulary: one row per (parameter, sampling type), with
an optional numeric parameter code. Every number on the page is computed
here. Chemical families come from an ordered keyword classifier with an
"אחר" fallback, so new parameters always flow through.
"""
import re

import pandas as pd

OTHER = "אחר"
NO_TYPE = "סוג דיגום לא צוין"
OTHER_TYPES = "סוגי דיגום אחרים"
MAX_TYPES = 4  # series cap on per-type charts (top-N + bucket)

# Ordered: first match wins. Domain mapping of known name stems; anything
# unmatched lands in OTHER, so new parameters never break the page.
FAMILIES = [
    ("רדיואקטיביים וקרינה", [r"^\d+\s*[A-Z][a-z]?\b", r"^\d+[A-Z][a-z]?", r"(?<!בליעת )קרינת(?!\s*UV)", r"רדיואקטיב"]),
    ("מיקרוביולוגיים", [r"קוליפורם", r"סטרפטוקוק", r"אנטרוקוק", r"E\.?coli", r"לגיונל",
                         r"סטפילוקוק", r"פסאודומונס", r"ספירה כללית"]),
    ("ערכים מסכמים וקבוצות (כולל TA-Luft)", [r"TA-Luft", r"ערך סכומי", r"^סך ", r"סריקת"]),
    ("חומרי הדברה", [r"DDT", r"אלדרין", r"אנדרין", r"לינדן", r"כלורדן", r"הפטאכלור", r"אטרזין",
                     r"סימזין", r"אלאכלור", r"מטולאכלור", r"כלורו?פיריפוס", r"דיאזינון", r"אזינופוס",
                     r"אבאמקטין", r"אוקסמיל", r"אלדיקרב", r"קרבופוראן", r"דימטואט", r"דינוסב",
                     r"דיקוואט", r"טריפלוראלין", r"סילבקס", r"ברומאציל", r"מתוקסיכלור", r"הדברה",
                     r"פנוקסי"]),
    ("מתכות ותרכובותיהן", [r"עופרת", r"ק[א]?דמיום", r"כספית", r"כרום", r"ניקל", r"נחושת", r"אבץ",
                          r"ארסן", r"ארסנ", r"ארסין", r"בריום", r"בריליום", r"^כסף", r"ו[א]?נ[א]?דיום", r"מ[א]?נג[א]?ן",
                          r"קוב[א]?לט", r"סלניום", r"אנטימון", r"תאליום", r"טלוריום", r"פלטינה",
                          r"פאלאדיום", r"רודיום", r"בדיל", r"מוליבדן", r"אלומיניום", r"ליתיום",
                          r"טיטניום", r"בורון", r"בורית", r"נתרן", r"מגנזיום", r"צורן"]),
    ("ארומטיים ופנולים", [r"בנז", r"טולו", r"קסיל", r"פנול", r"נ[א]?פת", r"סטירן", r"אנ[טת]ר",
                         r"פירן", r"פלואורן", r"פלואורא?נתן", r"ביפניל", r"קומן", r"קרסול", r"קריזול",
                         r"אנילין", r"פירידין", r"קרבאזול", r"דיאוקסינ", r"פוראן", r"פתאלאט", r"אצטופנון"]),
    ("הלוגנים ותרכובות מוכלרות", [r"כלור", r"ברו[םמ]", r"פלואור", r"יוד", r"הלוגנ", r"פוסגן", r"HBR"]),
    ("חנקן, זרחן, גופרית ותחמוצות", [r"חנק", r"חמצני", r"מרק[א]?[פט]", r"זרח", r"אמוני", r"אמון", r"גופר", r"גפרת", r"סולפ", r"פוספ",
                            r"ציאני", r"ציאנו", r"מימן", r"אוזון"]),
    ("פרמטרים כלליים ופיזיקליים", [r"pH", r"הגבה", r"BOD", r"COD", r"צח\"?ב", r"צריכת חמצן",
                                   r"מוצקים", r"TDS", r"TSS", r"עכירות", r"מוליכות", r"טמפרטורה",
                                   r"^צבע$", r"ריח", r"טעם", r"קשיות", r"אלקליניות", r"UV",
                                   r"חמצן מומס", r"מזג אוויר", r"TOC", r"SAR", r"לנגיליר",
                                   r"ביקרבונט", r"חלקיקים", r"שמנים", r"שומנים", r"שמן",
                                   r"דטרגנט", r"פעילי שטח", r"בדיקה", r"אבקת", r"ערפל", r"אסבסט"]),
    ("ממיסים ותרכובות אורגניות נדיפות", [r"אלכוהול", r"כוהל", r"כהל", r"אנול$", r"אתנול", r"מתאנול",
                                         r"קטון", r"אצט", r"אתר", r"אלדהיד", r"הקסאן", r"פנטאן",
                                         r"הפטאן", r"פרופ", r"בוטיל", r"VOC", r"נדיפ", r"אתילן",
                                         r"גליקול", r"אקריל", r"ממיסים", r"אורגני", r"אמין",
                                         r"פורמ", r"אולפינים", r"בוטאדיאן", r"מתאקרילאט", r"דיוקסאן",
                                         r"אמיד", r"ציקלו", r"הידרו"]),
]
_FAMILY_RX = [(label, re.compile("|".join(pats))) for label, pats in FAMILIES]
FAMILY_ORDER = [label for label, _ in FAMILIES] + [OTHER]


def _int(n):
    return f"{int(n):,}"


def _vav(w):
    """Hebrew "ו" glued before a Hebrew word, hyphenated before digits/Latin."""
    return f"ו{w}" if re.match(r"[\u0590-\u05FF]", str(w)) else f"ו-{w}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _norm_name(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    n = len(s)
    if n >= 4 and n % 2 == 0 and s[: n // 2] == s[n // 2:]:
        return s[: n // 2].strip()
    return s


def _is_doubled(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    n = len(s)
    return n >= 4 and n % 2 == 0 and s[: n // 2] == s[n // 2:]


def family_of(name):
    for label, rx in _FAMILY_RX:
        if rx.search(name):
            return label
    return OTHER


def _prepare(df):
    df = df.copy()
    df["raw_name"] = df["ParameterName"].astype(str)
    df["name"] = df["raw_name"].map(_norm_name)
    df["doubled"] = df["raw_name"].map(_is_doubled)
    df["type"] = df["SamplingType"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    df.loc[df["type"] == "", "type"] = NO_TYPE
    code = df["ParameterKod"].astype(str).str.replace(r"[\s,]", "", regex=True)
    df["code"] = code.where(code.str.fullmatch(r"\d+"), "")
    df["code"] = df["code"].str.lstrip("0").where(df["code"].str.lstrip("0") != "", df["code"])
    df["has_code"] = df["code"] != ""
    df = df[df["name"] != ""].copy()
    df["family"] = df["name"].map(family_of)
    return df


def _types_order(df):
    vc = df.groupby("type").size()
    return sorted(vc.index, key=lambda t: (-int(vc[t]), t))


def _type_bucket(types):
    """Map each type to itself (top MAX_TYPES) or the OTHER_TYPES bucket."""
    keep = list(types) if len(types) <= MAX_TYPES + 1 else list(types[:MAX_TYPES])
    return {t: (t if t in keep else OTHER_TYPES) for t in types}, (
        keep + ([OTHER_TYPES] if len(keep) < len(types) else []))


# ---------------------------------------------------------------- insights

def insight_lead_type(by_type, total):
    if len(by_type) < 2 or total == 0:
        return None
    (t1, v1), (t2, v2) = by_type[0], by_type[1]
    share = v1 / total
    if share < 0.4:
        return None
    if v1 == v2:
        return None
    return (f"סוג הדיגום הנפוץ ביותר במאגר הוא \"{t1}\" עם {_int(v1)} רשומות ({_pct(share)}), "
            f"ואחריו \"{t2}\" עם {_int(v2)} רשומות.")


def insight_code_gap(type_rows):
    cand = [r for r in type_rows if r["rows"] >= 20]
    if len(cand) < 1:
        return None
    worst = sorted(cand, key=lambda r: (r["coded_share"], r["name"]))[0]
    if worst["coded_share"] >= 0.7:
        return None
    best = sorted(cand, key=lambda r: (-r["coded_share"], r["name"]))[0]
    tail = ""
    if best["name"] != worst["name"] and best["coded_share"] - worst["coded_share"] >= 0.2:
        tail = f", לעומת {_pct(best['coded_share'])} ב\"{best['name']}\""
    return (f"ב\"{worst['name']}\" רק ל-{_int(worst['coded'])} מתוך {_int(worst['rows'])} "
            f"הפרמטרים ({_pct(worst['coded_share'])}) מופיע קוד פרמטר{tail}.")


def insight_overlap(name_types, t1, t2):
    if not t1 or not t2:
        return None
    in1 = {n for n, ts in name_types.items() if t1 in ts}
    in2 = {n for n, ts in name_types.items() if t2 in ts}
    both = in1 & in2
    if len(both) < 5:
        return None
    union = in1 | in2
    return (f"{_int(len(both))} פרמטרים מופיעים גם ב\"{t1}\" וגם ב\"{t2}\", "
            f"{_pct(len(both) / len(union))} מכלל {_int(len(union))} הפרמטרים של שני הסוגים.")


def insight_family(fam_type, t1, t2):
    def top(t):
        s = fam_type.get(t)
        if s is None:
            return None
        s = {f: v for f, v in s.items() if f != OTHER and v > 0}
        if not s:
            return None
        f = sorted(s, key=lambda k: (-s[k], FAMILY_ORDER.index(k)))[0]
        return f, s[f], sum(fam_type[t].values())
    a, b = top(t1) if t1 else None, top(t2) if t2 else None
    if not a or not b:
        return None
    if a[0] == b[0]:
        return (f"לפי סיווג השמות למשפחות, המשפחה הגדולה ביותר בשני סוגי הדיגום העיקריים היא \"{a[0]}\": "
                f"{_int(a[1])} פרמטרים ב\"{t1}\" ו-{_int(b[1])} ב\"{t2}\".")
    return (f"לפי סיווג השמות למשפחות, הרכב הפרמטרים שונה בין סוגי הדיגום: ב\"{t1}\" בולטת משפחת \"{a[0]}\" "
            f"({_int(a[1])} מתוך {_int(a[2])}), וב\"{t2}\" משפחת \"{b[0]}\" ({_int(b[1])} מתוך {_int(b[2])}).")


def insight_doubled(df):
    d = df[df["doubled"]]
    n = len(d)
    if n < 3:
        return None
    ex = sorted(set(d["name"]), key=lambda x: (len(x), x))[:1]
    return (f"ב-{_int(n)} רשומות שם הפרמטר מופיע כשהטקסט כפול (למשל {ex[0]}{ex[0]}), "
            f"כנראה תקלת ייצוא. בעמוד זה השמות אוחדו לצורך הניתוח.")


def insight_multi_code(df):
    c = df[df["has_code"]].groupby("name")["code"].nunique()
    m = sorted(c[c > 1].index)
    if len(m) < 3:
        return None
    return (f"ל-{_int(len(m))} פרמטרים יש יותר מקוד אחד במאגר (למשל {m[0]} {_vav(m[1])}), "
            f"בדרך כלל קוד שונה לכל סוג דיגום. כדאי לוודא שהקוד המדווח תואם לסוג הדיגום.")


# ------------------------------------------------------------------ compute

def compute(frames):
    df = _prepare(frames["params"])
    total = len(df)
    names = df["name"].nunique()
    types = _types_order(df)
    coded = int(df["has_code"].sum())
    coded_share = coded / total if total else 0.0

    # --- by type, with / without code
    type_rows = []
    for t in types:
        g = df[df["type"] == t]
        c = int(g["has_code"].sum())
        type_rows.append({"name": t, "rows": len(g), "coded": c, "uncoded": len(g) - c,
                          "coded_share": c / len(g) if len(g) else 0.0})
    ch_types = {"names": [r["name"] for r in type_rows],
                "coded": [r["coded"] for r in type_rows],
                "uncoded": [r["uncoded"] for r in type_rows]}
    tbl_types = [{"name": r["name"], "rows": _int(r["rows"]), "coded": _int(r["coded"]),
                  "share": _pct(r["coded_share"])} for r in type_rows]

    # --- families x type (types capped)
    bmap, bucket_order = _type_bucket(types)
    df["tbucket"] = df["type"].map(bmap)
    fam_counts = df.groupby("family").size()
    fams = sorted(fam_counts.index, key=lambda f: (-int(fam_counts[f]) if f != OTHER else 1, FAMILY_ORDER.index(f)))
    cross = df.groupby(["family", "tbucket"]).size()
    ch_fam = {"names": fams, "series": [
        {"name": b, "data": [int(cross.get((f, b), 0)) for f in fams]} for b in bucket_order]}
    fam_type = {}
    for (f, b), v in cross.items():
        fam_type.setdefault(b, {})[f] = int(v)
    tbl_fam = []
    for f in fams:
        ex = sorted(set(df.loc[df["family"] == f, "name"]),
                    key=lambda x: (x[:1].isdigit(), len(x), x))[:3]
        tbl_fam.append({"name": f, "total": _int(fam_counts[f]),
                        "cells": [_int(cross.get((f, b), 0)) for b in bucket_order],
                        "examples": ", ".join(ex)})

    # --- overlap: which combination of types each parameter name appears in
    name_types = {}
    for n, t in zip(df["name"], df["tbucket"]):
        name_types.setdefault(n, set()).add(t)
    combo = {}
    for n, ts in name_types.items():
        key = tuple(sorted(ts, key=lambda x: bucket_order.index(x)))
        combo[key] = combo.get(key, 0) + 1

    def combo_label(k):
        if len(k) == 1:
            return f"רק {k[0]}"
        return " + ".join(k)
    combos = sorted(combo.items(), key=lambda kv: (-kv[1], len(kv[0]), combo_label(kv[0])))
    ch_overlap = {"names": [combo_label(k) for k, _ in combos], "values": [v for _, v in combos]}
    tbl_overlap = [{"name": combo_label(k), "count": _int(v), "share": _pct(v / len(name_types))}
                   for k, v in combos]
    multi_type_names = sum(v for k, v in combo.items() if len(k) > 1)

    # --- code series (digit length) x type
    cd = df[df["has_code"]].copy()
    cd["len"] = cd["code"].str.len()
    lens = sorted(cd["len"].unique().tolist())
    lens_labels = [f"קוד בן {int(n)} ספרות" if n > 1 else "קוד בן ספרה אחת" for n in lens]
    cross2 = cd.groupby(["len", "tbucket"]).size()
    ch_series = {"names": lens_labels, "series": [
        {"name": b, "data": [int(cross2.get((n, b), 0)) for n in lens]} for b in bucket_order
        if any(cross2.get((n, b), 0) for n in lens)]}
    len_counts = cd.groupby("len").size()
    tbl_series = []
    for n, lab in zip(lens, lens_labels):
        codes = sorted(cd.loc[cd["len"] == n, "code"].astype(int).unique().tolist())
        tbl_series.append({"name": lab, "count": _int(len_counts[n]),
                           "distinct": _int(len(codes)),
                           "range": f"{codes[0]}-{codes[-1]}" if codes else ""})
    uniq_codes = cd["code"].nunique()

    # --- data quality
    code_names = cd.groupby("code")["name"].nunique()
    name_codes = cd.groupby("name")["code"].nunique()
    dup_in_type = int(df.duplicated(["name", "type"]).sum())
    quality = [
        ("רשומות ללא קוד פרמטר", total - coded),
        ("רשומות עם שם כפול (טקסט חוזר)", int(df["doubled"].sum())),
        ("פרמטרים עם יותר מקוד אחד", int((name_codes > 1).sum())),
        ("קודים עם יותר משם אחד", int((code_names > 1).sum())),
        ("שם שחוזר באותו סוג דיגום", dup_in_type),
    ]
    ch_quality = {"names": [q[0] for q in quality], "values": [q[1] for q in quality]}
    tbl_quality = [{"name": q[0], "count": _int(q[1])} for q in quality]

    # --- insights
    t1 = types[0] if len(types) > 0 else None
    t2 = types[1] if len(types) > 1 else None
    rules = [
        ("lead_type", insight_lead_type([(r["name"], r["rows"]) for r in type_rows], total)),
        ("code_gap", insight_code_gap(type_rows)),
        ("overlap", insight_overlap(name_types, t1, t2)),
        ("family", insight_family(fam_type, t1, t2)),
        ("multi_code", insight_multi_code(df)),
        ("doubled", insight_doubled(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    tone_code = "ok" if coded_share >= 0.9 else ("warn" if coded_share >= 0.6 else "danger")
    kpis = {
        "rows": {"value": total, "display": _int(total), "tone": "brand"},
        "names": {"value": int(names), "display": _int(names), "tone": "brand"},
        "codes": {"value": int(uniq_codes), "display": _int(uniq_codes), "tone": "brand"},
        "coded": {"value": round(coded_share * 100, 1), "display": _pct(coded_share), "tone": tone_code},
    }

    top_fam = [f for f in fams if f != OTHER]
    summary = (f"איתור קוד פרמטר לדיווחי דיגומים לפי שם החומר או סוג הדיגום: "
               f"{_int(names)} פרמטרים ב-{_int(len(types))} סוגי דיגום, "
               f"ל-{_pct(coded_share)} מהרשומות יש קוד.")
    lede = (f"המאגר הוא רשימת הפרמטרים (חומרים ומדדים) שהמשרד להגנת הסביבה מגדיר לדיווח תוצאות דיגום: "
            f"{_int(total)} רשומות של {_int(names)} פרמטרים שונים, המשויכים ל-{_int(len(types))} סוגי דיגום. "
            f"לכל פרמטר מופיעים שמו, סוג הדיגום שבו הוא מדווח, ולרוב גם קוד פרמטר מספרי "
            f"({_int(uniq_codes)} קודים שונים).")

    fam_lede = None
    if top_fam:
        f0 = top_fam[0]
        fam_lede = (f"המשפחה הגדולה היא \"{f0}\" עם {_int(fam_counts[f0])} רשומות. "
                    f"{_int(fam_counts.get(OTHER, 0))} רשומות לא שויכו למשפחה ומופיעות תחת \"{OTHER}\".")
    labels = {
        "lede": lede,
        "types_note": (f"מספר הרשומות בכל סוג דיגום, ובכמה מהן מופיע קוד פרמטר. "
                       f"בסך הכול {_int(coded)} מתוך {_int(total)} רשומות כוללות קוד."),
        "types_aria": (f"גרף עמודות מוערמות: רשומות לפי סוג דיגום, עם קוד וללא קוד. "
                       f"המוביל: {t1} עם {_int(type_rows[0]['rows'])} רשומות.") if t1 else "גרף עמודות: רשומות לפי סוג דיגום.",
        "fam_note": ("סיווג אוטומטי של שמות הפרמטרים למשפחות לפי מילות מפתח בשם החומר. "
                     + (fam_lede or "")),
        "fam_aria": (f"גרף עמודות מוערמות: פרמטרים לפי משפחה וסוג דיגום. "
                     f"המשפחה הגדולה: {top_fam[0]} עם {_int(fam_counts[top_fam[0]])} רשומות.") if top_fam else "גרף עמודות: פרמטרים לפי משפחה.",
        "overlap_note": (f"לכל שם פרמטר: באילו סוגי דיגום הוא מופיע. "
                         f"{_int(multi_type_names)} מתוך {_int(len(name_types))} הפרמטרים מופיעים ביותר מסוג דיגום אחד."),
        "overlap_aria": (f"גרף עמודות: מספר הפרמטרים לפי צירוף סוגי הדיגום שבהם הם מופיעים. "
                         f"{_int(multi_type_names)} פרמטרים משותפים ליותר מסוג אחד."),
        "series_note": (f"הקודים המספריים מתחלקים לסדרות לפי אורכם. "
                        f"{_int(uniq_codes)} קודים שונים מופיעים ב-{_int(coded)} רשומות."),
        "series_aria": (f"גרף עמודות מוערמות: רשומות עם קוד לפי אורך הקוד וסוג הדיגום, "
                        f"{_int(uniq_codes)} קודים שונים."),
        "quality_note": ("בדיקות עקביות על הרשימה: חוסרים, כפילויות וקודים לא חד-ערכיים. "
                         "שמות עם טקסט כפול אוחדו בכל הגרפים בעמוד."),
        "quality_aria": (f"גרף עמודות: ממצאי איכות נתונים. "
                         f"{_int(total - coded)} רשומות ללא קוד פרמטר."),
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["דיגום", "פרמטרים", "שפכי תעשייה", "פליטות לאוויר", "הגנת הסביבה"],
            "related_ids": [
                "04931a88-336c-4d95-8a13-9dc631c3e2d1",
                "5fc5c912-4fa5-4474-93c1-326e505e22cf",
                "422ff747-a1ee-4e8d-b515-43417f0d80d8",
                "780f8522-db2b-4147-b2ac-554aafaf1c1a",
                "19c40947-95f1-4ea0-8a04-ad56526726af",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "types": ch_types,
            "families": ch_fam,
            "overlap": ch_overlap,
            "series": ch_series,
            "quality": ch_quality,
        },
        "tables": {
            "types": tbl_types,
            "families": tbl_fam,
            "family_heads": bucket_order,
            "overlap": tbl_overlap,
            "series": tbl_series,
            "quality": tbl_quality,
        },
        "insights": insights,
        "labels": labels,
    }
