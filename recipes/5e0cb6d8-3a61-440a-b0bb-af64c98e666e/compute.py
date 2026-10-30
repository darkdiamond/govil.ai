"""Sporting-driving event rules (נהיגה ספורטיבית): a document registry.

One row per rule document: domain (תחום), sub-domain (תת תחום), document
name and a link to the PDF / page on gov.il. compute() classifies each
document by its name into a rule type (event rules, technical, safety,
training, annex, general) and builds the page model: composition charts,
a sub-domain x type coverage view, link health, and a grouped catalog.
Every number and sentence is computed from the rows.
"""
import re

import pandas as pd

# Rule types, checked in this order against the document name (first match
# wins). Order = display order. Unmatched names fall to "general".
TYPES = [
    ("annex", "נספחים", ("נספח",)),
    ("training", "אימון, מיונים והכשרה",
     ("אימון", "הדרכה", "מתחילים", "מבחן שליטה", "יום עיון", "מיונים", "NOVIC")),
    ("event", "כללי אירוע", ("כללי אירוע", "כללי ארוע", "תקנון")),
    ("safety", "בטיחות וציוד מגן", ("בטיחות", "ציוד מגן", "כלוב")),
    ("technical", "כללים טכניים", ("טכני", "תקנות")),
]
GENERAL = ("general", "כללי נהיגה כלליים ואחרים")
TYPE_KEYS = [t[0] for t in TYPES] + [GENERAL[0]]
TYPE_LABEL = {t[0]: t[1] for t in TYPES}
TYPE_LABEL[GENERAL[0]] = GENERAL[1]

MAX_SUBS_CHART = 14   # stacked bar rows before an "other" bucket (mobile height)
MAX_DOMAINS_CHART = 6

YEAR_RE = re.compile(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)")
CLASS_RE = re.compile(r"קטגוריה|קבוצה|קטגוריות")


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _classify(name):
    for key, _label, words in TYPES:
        if any(w in name for w in words):
            return key
    return GENERAL[0]


URL_RE = re.compile(r"^https://([A-Za-z0-9.-]+)(?::443)?(/[^\s\x22\x27<>]*)?$")


def _safe_url(u):
    """Only https links to gov.il hosts reach the page (data is untrusted)."""
    u = (u or "").strip()
    m = URL_RE.match(u)
    if not m:
        return None
    host = m.group(1).lower()
    if not (host == "gov.il" or host.endswith(".gov.il")) or "data.gov.il" in host:
        return None
    return u


def _link_kind(u):
    if not isinstance(u, str):
        return "none"
    path = URL_RE.match(u).group(2) or ""
    path = re.split(r"[?#]", path, maxsplit=1)[0].lower()
    if path.endswith(".pdf"):
        return "pdf"
    if re.search(r"\.(docx?|xlsx?|pptx?|zip)$", path):
        return "file"
    return "page"


LINK_LABEL = {"pdf": "קובץ PDF", "page": "דף באתר gov.il", "file": "קובץ אחר",
              "none": "ללא קישור תקין"}
LINK_ORDER = ["pdf", "page", "file", "none"]


def _prepare(df):
    df = df.copy()
    for c in ("תחום", "תת תחום", "שם כלל", "לינק לכלל"):
        df[c] = df[c].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    df = df[df["שם כלל"] != ""].copy()
    df["domain"] = df["תחום"].where(df["תחום"] != "", "לא צוין")
    df["sub"] = df["תת תחום"].where(df["תת תחום"] != "", df["domain"])
    df["name"] = df["שם כלל"]
    df["type"] = df["name"].map(_classify)
    # object dtype keeps None as None: pandas 3 would store a missing link
    # in a str column as NaN, which crashes _link_kind and the JSON model.
    df["url"] = df["לינק לכלל"].map(_safe_url).astype(object)
    df["url"] = df["url"].where(df["url"].notna(), None)
    df["link_kind"] = df["url"].map(_link_kind)
    # Exact duplicate documents (same name + sub + link) count once.
    df = df.drop_duplicates(subset=["domain", "sub", "name", "לינק לכלל"])
    df = df.sort_values(["domain", "sub", "name", "לינק לכלל"], kind="stable")
    return df.reset_index(drop=True)


def _ranked(counts):
    """Series -> sorted by value desc, then label asc (total order)."""
    return counts.sort_index().sort_values(ascending=False, kind="stable")


# ---------------------------------------------------------------- insights

def insight_top_sub(by_sub, total, sub_label):
    if len(by_sub) < 2 or total == 0:
        return None
    (k1, v1), (_k2, v2) = list(by_sub.items())[:2]
    share = v1 / total
    if v1 == v2 or share < 0.12:
        return None
    return (f"{sub_label[k1]} הוא תת-התחום המוסדר ביותר: {_int(v1)} מסמכים, "
            f"{_pct(share)} מכלל {_int(total)} הכללים במאגר, לעומת {_int(v2)} "
            f"בתת-התחום השני בגודלו.")


def insight_top_domain(by_domain, total, n_subs_per_domain):
    if len(by_domain) < 2 or total == 0:
        return None
    k, v = by_domain.index[0], int(by_domain.iloc[0])
    if v == int(by_domain.iloc[1]):
        return None
    share = v / total
    if share < 0.4:
        return None
    return (f"תחום {k} מרכז {_int(v)} מתוך {_int(total)} הכללים ({_pct(share)}), "
            f"מפוזרים על פני {_int(n_subs_per_domain[k])} תתי-תחומים.")


def insight_type_mix(by_type, total):
    if total == 0 or by_type.empty:
        return None
    k, v = by_type.index[0], int(by_type.iloc[0])
    if len(by_type) > 1 and v == int(by_type.iloc[1]):
        return None
    share = v / total
    if share < 0.25:
        return None
    ev = int(by_type.get("event", 0))
    tail = f" מסמכי כללי אירוע מונים {_int(ev)}." if k != "event" and ev else ""
    return (f"הסוג הנפוץ ביותר הוא {TYPE_LABEL[k]}: {_int(v)} מסמכים, "
            f"{_pct(share)} מהמאגר (סיווג לפי שם המסמך).{tail}")


def insight_event_gap(missing, n_subs):
    if n_subs < 2:
        return None
    if not missing:
        return f"לכל {_int(n_subs)} תתי-התחומים יש לפחות מסמך כללי אירוע אחד."
    if len(missing) > 4:
        return (f"ל-{_int(len(missing))} מתוך {_int(n_subs)} תתי-תחומים אין מסמך "
                f"שכותרתו כללי אירוע.")
    names = ", ".join(missing)
    return (f"ל-{_int(n_subs - len(missing))} מתוך {_int(n_subs)} תתי-התחומים יש מסמך "
            f"כללי אירוע ייעודי. ללא מסמך כזה בשמו: {names}.")


def insight_classes(df, sub_label):
    m = df[df["name"].str.contains(CLASS_RE)]
    if len(m) < 3:
        return None
    by = _ranked(m.groupby(["domain", "sub"]).size())
    (dk, sk), v = by.index[0], int(by.iloc[0])
    if v < 3:
        return None
    return (f"{_int(len(m))} מסמכים מסדירים קטגוריה או קבוצת רכב מסוימת, "
            f"{_int(v)} מהם בתת-התחום {sub_label[(dk, sk)]}.")


def insight_shared(df):
    linked = df[df["url"].notna()]
    dup = linked.groupby("url")["name"].nunique()
    dup = dup[dup > 1]
    if dup.empty:
        return None
    n_docs = int(dup.sum())
    if len(dup) == 1:
        names = sorted(linked[linked["url"] == dup.index[0]]["name"].unique())
        return (f"{_int(n_docs)} כללים מפנים לאותו קובץ בדיוק: "
                + " ו".join(f"״{n}״" for n in names[:3]) + ".")
    return (f"{_int(len(dup))} קבצים משמשים יותר מכלל אחד, ובסך הכול {_int(n_docs)} "
            f"כללים חולקים קובץ עם כלל אחר.")


def _pdf_split(by_link, n_linked):
    pdf = int(by_link.get("pdf", 0))
    if n_linked <= 0:
        return ""
    if pdf * 2 > n_linked:
        return f"רובם ({_int(pdf)}) קובצי PDF להורדה."
    return f"{_int(pdf)} מהם קובצי PDF ו-{_int(n_linked - pdf)} דפים או קבצים אחרים."


def insight_links(by_link, total):
    none = int(by_link.get("none", 0))
    pdf = int(by_link.get("pdf", 0))
    if total == 0:
        return None
    if none == 0:
        return (f"לכל {_int(total)} הכללים יש קישור למסמך באתר gov.il, "
                f"{_int(pdf)} מהם קובצי PDF.")
    return (f"{_int(total - none)} מתוך {_int(total)} הכללים מקושרים למסמך באתר gov.il "
            f"({_int(pdf)} כקובץ PDF). ל-{_int(none)} אין קישור תקין במאגר.")


def insight_years(df):
    yrs = df["name"].str.extract(YEAR_RE)[0].dropna()
    if yrs.empty:
        return None
    y = sorted(int(v) for v in yrs)
    if len(y) == 1:
        row = df[df["name"].str.contains(str(y[0]))].iloc[0]
        return (f"רק מסמך אחד נושא שנה בשמו: ״{row['name']}״, "
                f"מ-{y[0]}. שאר הכללים אינם מתוארכים במאגר.")
    return (f"{_int(len(y))} מסמכים נושאים שנה בשמם, מ-{y[0]} עד {y[-1]}. "
            f"שאר הכללים אינם מתוארכים במאגר.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["rules"])
    total = int(len(df))

    by_domain = _ranked(df.groupby("domain").size())
    by_sub = _ranked(df.groupby(["domain", "sub"]).size())
    by_type = _ranked(df.groupby("type").size())
    by_link = df.groupby("link_kind").size()

    # A sub-domain name repeated under two domains gets the domain appended.
    sub_names = pd.Series([s for _d, s in by_sub.index])
    repeated = set(sub_names[sub_names.duplicated(keep=False)])
    sub_label = {}
    for d, s in by_sub.index:
        sub_label[(d, s)] = f"{s} ({d})" if s in repeated else s
    n_subs = int(len(by_sub))
    n_subs_per_domain = df.groupby("domain")["sub"].nunique().to_dict()

    # ----- domain chart (pie) + table
    dom_items = list(by_domain.items())
    if len(dom_items) > MAX_DOMAINS_CHART:
        head = dom_items[:MAX_DOMAINS_CHART - 1]
        rest = sum(v for _k, v in dom_items[MAX_DOMAINS_CHART - 1:])
        dom_items = head + [("תחומים נוספים", rest)]
    domains_chart = [{"name": k, "value": int(v)} for k, v in dom_items]
    domains_table = [{"name": k, "count": _int(v), "subs": _int(n_subs_per_domain.get(k, 0)),
                      "share": _pct(v / total) if total else "0.0%"}
                     for k, v in by_domain.items()]

    # ----- treemap domain -> sub
    tree = []
    for d, dv in by_domain.items():
        children = [{"name": s, "value": int(v)} for (dd, s), v in by_sub.items() if dd == d]
        tree.append({"name": d, "value": int(dv), "children": children})
    tree_table = [{"domain": d, "sub": s, "count": _int(v)} for (d, s), v in by_sub.items()]

    # ----- sub-domain x type stacked bars (top subs + other)
    ct = df.groupby(["domain", "sub", "type"]).size()
    sub_keys = list(by_sub.index)
    shown = sub_keys[:MAX_SUBS_CHART] if len(sub_keys) > MAX_SUBS_CHART + 1 else sub_keys
    rest = [k for k in sub_keys if k not in shown]
    types_present = [k for k in TYPE_KEYS if k in by_type.index]
    rows_y = [sub_label[k] for k in shown] + (["תתי-תחומים נוספים"] if rest else [])
    series = []
    for t in types_present:
        vals = [int(ct.get((d, s, t), 0)) for d, s in shown]
        if rest:
            vals.append(int(sum(ct.get((d, s, t), 0) for d, s in rest)))
        series.append({"name": TYPE_LABEL[t], "data": vals})
    matrix_table = []
    for d, s in sub_keys:
        matrix_table.append({
            "name": sub_label[(d, s)],
            "cells": [_int(ct.get((d, s, t), 0)) for t in types_present],
            "total": _int(by_sub[(d, s)]),
        })
    missing_event = [sub_label[k] for k in sub_keys if ct.get((k[0], k[1], "event"), 0) == 0]

    # ----- type bars
    types_chart = {"names": [TYPE_LABEL[k] for k in by_type.index],
                   "values": [int(v) for v in by_type.values]}
    types_table = [{"name": TYPE_LABEL[k], "count": _int(v),
                    "share": _pct(v / total) if total else "0.0%"} for k, v in by_type.items()]

    # ----- links
    link_items = [(k, int(by_link.get(k, 0))) for k in LINK_ORDER if int(by_link.get(k, 0)) > 0]
    links_chart = [{"name": LINK_LABEL[k], "value": v, "kind": k} for k, v in link_items]
    links_table = [{"name": LINK_LABEL[k], "count": _int(v),
                    "share": _pct(v / total) if total else "0.0%"} for k, v in link_items]
    n_linked = total - int(by_link.get("none", 0))

    # ----- catalog grouped domain -> sub, rules by type order then name
    type_rank = {k: i for i, k in enumerate(TYPE_KEYS)}
    catalog = []
    for d in by_domain.index:
        subs = []
        for (dd, s), v in by_sub.items():
            if dd != d:
                continue
            part = df[(df["domain"] == d) & (df["sub"] == s)].copy()
            part["_r"] = part["type"].map(type_rank)
            part = part.sort_values(["_r", "name", "לינק לכלל"], kind="stable")
            subs.append({
                "name": s,
                "count": _int(v),
                "rules": [{"name": r["name"], "url": r["url"], "type": TYPE_LABEL[r["type"]]}
                          for _i, r in part.iterrows()],
            })
        catalog.append({"name": d, "count": _int(by_domain[d]), "subs": subs})

    # ----- insights
    rules = [
        ("top_sub", insight_top_sub(by_sub, total, sub_label)),
        ("top_domain", insight_top_domain(by_domain, total, n_subs_per_domain)),
        ("type_mix", insight_type_mix(by_type, total)),
        ("event_gap", insight_event_gap(missing_event, n_subs)),
        ("classes", insight_classes(df, sub_label)),
        ("shared", insight_shared(df)),
        ("links", insight_links(by_link, total)),
        ("years", insight_years(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    n_tech = int(by_type.get("technical", 0))
    n_event = int(by_type.get("event", 0))
    n_with_event = n_subs - len(missing_event)
    top_sub_key = by_sub.index[0] if n_subs else None
    top_dom = by_domain.index[0] if len(by_domain) else ""

    summary = (f"כללי נהיגה ספורטיבית לאירועי מרוצים: איתור תקנון לפי ענף ({', '.join(by_domain.index[:3])}). "
               f"{_int(total)} מסמכים ב-{_int(n_subs)} תתי-תחומים, עם קישור למסמך.")
    if len(summary) > 155:
        summary = (f"כללי נהיגה ספורטיבית לאירועי מרוצים: איתור תקנון לפי ענף. "
                   f"{_int(total)} מסמכים ב-{_int(n_subs)} תתי-תחומים, עם קישור למסמך.")

    lede = (f"המאגר של משרד התרבות והספורט מרכז {_int(total)} מסמכי כללים ותקנונים "
            f"לאירועי נהיגה ספורטיבית, ב-{_int(len(by_domain))} תחומים "
            f"ו-{_int(n_subs)} תתי-תחומים (ענפים). "
            + ("לכל כלל מצורף קישור למסמך המלא באתר gov.il. " if n_linked == total
               else f"ל-{_int(n_linked)} מהם מצורף קישור למסמך המלא באתר gov.il. ")
            + f"בעמוד: התפלגות הכללים לפי ענף וסוג, ומדריך מלא לכל המסמכים.")

    labels = {
        "lede": lede,
        "domains_aria": (f"תרשים עוגה: כללים לפי תחום. תחום {top_dom} מוביל עם "
                         f"{_int(by_domain.iloc[0]) if len(by_domain) else 0} מסמכים."),
        "domains_lede": (f"{_int(len(by_domain))} תחומים: " + ", ".join(
            f"{k} {_int(v)}" for k, v in by_domain.items()) + "."),
        "tree_aria": (f"מפת שטחים: {_int(total)} כללים לפי תחום ותת-תחום. "
                      f"הגדול ביותר: {sub_label[top_sub_key] if top_sub_key else ''} עם "
                      f"{_int(by_sub.iloc[0]) if n_subs else 0} מסמכים."),
        "tree_lede": (f"גודל כל מלבן הוא מספר המסמכים בתת-התחום. "
                      f"{_int(n_subs)} תתי-תחומים, ובממוצע "
                      f"{(total / n_subs if n_subs else 0):.1f} מסמכים לכל אחד."),
        "matrix_aria": (f"תרשים עמודות מוערמות: סוגי הכללים בכל תת-תחום. "
                        f"ל-{_int(n_with_event)} מתוך {_int(n_subs)} תתי-תחומים יש מסמך כללי אירוע."),
        "matrix_lede": (f"כל עמודה מפרקת את מסמכי תת-התחום לפי סוג, כפי שעולה משם המסמך. "
                        f"ל-{_int(n_with_event)} מתוך {_int(n_subs)} תתי-תחומים יש מסמך כללי אירוע."
                        + (f" מוצגים {_int(len(shown))} תתי-התחומים הגדולים, והשאר מקובצים."
                           if rest else "")),
        "types_aria": (f"תרשים עמודות: כללים לפי סוג. "
                       f"{TYPE_LABEL[by_type.index[0]] if len(by_type) else ''} מוביל עם "
                       f"{_int(by_type.iloc[0]) if len(by_type) else 0} מסמכים."),
        "types_lede": (f"הסוג נקבע לפי מילות מפתח בשם המסמך (למשל ״טכני״, ״כללי אירוע״, "
                       f"״נספח״). {_int(n_tech)} מסמכים טכניים ו-{_int(n_event)} מסמכי כללי אירוע."),
        "links_aria": (f"תרשים עוגה: סוג הקישור למסמך. {_int(n_linked)} מתוך {_int(total)} "
                       f"כללים מקושרים למסמך באתר gov.il."),
        "links_lede": (f"{_int(n_linked)} מתוך {_int(total)} הכללים מקושרים למסמך באתר gov.il; "
                       + _pdf_split(by_link, n_linked)),
        "catalog_lede": (f"כל {_int(total)} המסמכים, מקובצים לפי תחום ותת-תחום. "
                         f"לחיצה על שם הכלל פותחת את המסמך באתר gov.il."),
        "search_hint": ("חיפוש חי בכל רשומות המאגר: תחום, תת תחום ("
                        + ", ".join(sub_label[k] for k in by_sub.index[:4])
                        + (" ועוד" if n_subs > 4 else "") + ") ושם הכלל"),
        "type_cols": [TYPE_LABEL[t] for t in types_present],
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["נהיגה ספורטיבית", "ספורט מוטורי", "מרוצים",
                               "כללי בטיחות", "תקנונים"],
            "related_ids": [
                "0ee9210f-dedc-453d-9b5f-90bff945c3da",
                "1950e30f-56f3-465a-b4b3-09317ad9d18e",
                "1d92d261-a196-4103-85c3-22ea2fe4932c",
                "3b460734-ecbf-422c-833b-11082288cd30",
                "5432f529-96e1-45d3-a343-fbeb1659b5f1",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "rules": {"value": total, "display": _int(total), "tone": "brand"},
            "subs": {"value": n_subs, "display": _int(n_subs), "tone": "brand"},
            "technical": {"value": n_tech, "display": _int(n_tech), "tone": "info"},
            "event_cov": {
                "value": n_with_event,
                "display": _int(n_with_event),
                "tone": "ok" if not missing_event else "warn",
            },
        },
        "charts": {
            "domains": domains_chart,
            "tree": tree,
            "matrix": {"y": rows_y, "series": series},
            "types": types_chart,
            "links": links_chart,
        },
        "tables": {
            "domains": domains_table,
            "tree": tree_table,
            "matrix": matrix_table,
            "types": types_table,
            "links": links_table,
        },
        "catalog": catalog,
        "insights": insights,
        "labels": labels,
    }
