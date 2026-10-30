"""סימני מסחר - סיווגים: the two classification schemes used when filing an
Israeli trade mark.

Two small code tables from the Israel Patent Office:

* nice: the Nice classification (one row per class: number, Hebrew and
  English heading). Classes 1-34 are goods and 35 onward are services; that
  boundary is part of the international standard, so it is a known-code
  mapping (any class above 45 is treated as services, which is where Nice
  has always added new classes).
* vienna: the Vienna classification of figurative elements (one row per
  division, code "category.division", Hebrew and English heading). The 29
  category titles are not in the data; a fixed Hebrew title map labels the
  known ones and an unknown category falls back to "קטגוריה N".

These are reference tables, not usage data: the page lays out their
structure (goods vs services, divisions per category, numbering gaps) and
gives a full visible lookup of the Nice classes. Every number comes from
the rows.
"""
import re

import pandas as pd

GOODS_MAX = 34  # Nice: classes 1-34 are goods, 35+ are services

VIENNA_TITLES = {
    1: "גרמי שמים, תופעות טבע ומפות",
    2: "בני אדם",
    3: "בעלי חיים",
    4: "יצורים על-טבעיים ודמיוניים",
    5: "צמחים",
    6: "נופים",
    7: "מבנים ובניינים",
    8: "מזון",
    9: "טקסטיל, הלבשה והנעלה",
    10: "טבק, מוצרי נסיעה וטואלט",
    11: "כלי בית",
    12: "רהיטים וכלים סניטריים",
    13: "תאורה, חימום, בישול וקירור",
    14: "פריטי מתכת, כלים וסולמות",
    15: "מכונות ומנועים",
    16: "תקשורת, מחשבים, צילום ואופטיקה",
    17: "שעונים, תכשיטים, משקלות ומידות",
    18: "תחבורה ותמרורים",
    19: "מכלים ואריזות",
    20: "צורכי כתיבה, משרד וספרים",
    21: "משחקים, צעצועים וספורט",
    22: "כלי נגינה, פעמונים, תמונות ופסלים",
    23: "כלי נשק, תחמושת ושריון",
    24: "הרלדיקה, מטבעות וסמלים",
    25: "מוטיבים קישוטיים ורקעים",
    26: "צורות גיאומטריות",
    27: "צורות כתב וספרות",
    28: "כיתובים באותיות שונות",
    29: "צבעים",
}

_PREFIX_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*")


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _clean(text, strip_dot=True):
    t = _PREFIX_RE.sub("", str(text)).strip()
    t = re.sub(r"\s+", " ", t)
    if strip_dot:
        t = t.rstrip(". ").strip()
    return t


def _vienna_title(cat):
    return VIENNA_TITLES.get(cat, f"קטגוריה {cat}")


def _prepare_nice(df):
    df = df.copy()
    df["cls"] = pd.to_numeric(df["סוג ניצה"].str.strip(), errors="coerce")
    df = df.dropna(subset=["cls"])
    df["cls"] = df["cls"].astype(int)
    df["he"] = df["תיאור בעברית"].map(_clean)
    df["en"] = df["תיאור באנגלית"].map(lambda s: _clean(s, strip_dot=False))
    df = df.sort_values(["cls", "he", "en"], kind="stable")
    df = df.drop_duplicates(subset=["cls"], keep="first")
    df["kind"] = df["cls"].map(lambda c: "goods" if c <= GOODS_MAX else "services")
    return df.reset_index(drop=True)


def _prepare_vienna(df):
    df = df.copy()
    code = df["סיווג וינה"].str.strip()
    parts = code.str.extract(r"^(\d+)\.(\d+)$")
    df["cat"] = pd.to_numeric(parts[0], errors="coerce")
    df["div"] = pd.to_numeric(parts[1], errors="coerce")
    df = df.dropna(subset=["cat", "div"])
    df["cat"] = df["cat"].astype(int)
    df["div"] = df["div"].astype(int)
    df["code"] = df["cat"].astype(str) + "." + df["div"].astype(str)
    df["he"] = df["תיאור בעברית"].map(_clean)
    df["en"] = df["תיאור באנגלית"].map(lambda s: _clean(s, strip_dot=False))
    df = df.sort_values(["cat", "div", "he", "en"], kind="stable")
    df = df.drop_duplicates(subset=["cat", "div"], keep="first")
    return df.reset_index(drop=True)


# ── insights ──────────────────────────────────────────────────────────────

def insight_goods_services(nice):
    n = len(nice)
    g = int((nice["kind"] == "goods").sum())
    s = n - g
    if n == 0 or g == 0 or s == 0:
        return None
    s_min = int(nice.loc[nice["kind"] == "services", "cls"].min())
    s_max = int(nice.loc[nice["kind"] == "services", "cls"].max())
    return (f"{_int(g)} מתוך {_int(n)} מחלקות ניצה ({_pct(g / n)}) מיועדות לסחורות, "
            f"ו-{_int(s)} בלבד לשירותים (מחלקות {s_min} עד {s_max}). "
            "בבקשה לרישום סימן יש לציין את המחלקות שבהן ישמש.")


def insight_vienna_leader(per_cat, total):
    if len(per_cat) < 3 or total == 0:
        return None
    top = per_cat.iloc[0]
    second = per_cat.iloc[1]
    if top["n"] < 2 * (total / len(per_cat)):
        return None  # no category clearly larger than the average
    tied = per_cat[per_cat["n"] == top["n"]]
    if len(tied) > 1:
        names = " ו-".join(f"{int(c)} ({_vienna_title(int(c))})" for c in tied["cat"])
        return (f"הקטגוריות המפורטות ביותר בסיווג וינה הן {names}, "
                f"עם {_int(top['n'])} חטיבות כל אחת, פי {top['n'] / (total / len(per_cat)):.1f} מהממוצע.")
    runners = per_cat[per_cat["n"] == second["n"]]
    if len(runners) > 1:
        rnames = " ו-".join(f"{int(c)} ({_vienna_title(int(c))})" for c in runners["cat"].head(3))
        after = f"ואחריה {rnames} עם {_int(second['n'])} כל אחת"
    else:
        after = f"ואחריה {int(second['cat'])} ({_vienna_title(int(second['cat']))}) עם {_int(second['n'])}"
    return (f"הקטגוריה המפורטת ביותר בסיווג וינה היא {int(top['cat'])} ({_vienna_title(int(top['cat']))}) "
            f"עם {_int(top['n'])} חטיבות, {after}. הממוצע הוא {total / len(per_cat):.1f} חטיבות לקטגוריה.")


def insight_vienna_single(per_cat):
    single = per_cat[per_cat["n"] == 1].sort_values("cat", kind="stable")
    if single.empty or len(per_cat) < 3:
        return None
    cats = [int(c) for c in single["cat"]]
    listed = ", ".join(f"{c} ({_vienna_title(c)})" for c in cats[:4])
    more = f" ועוד {len(cats) - 4}" if len(cats) > 4 else ""
    if len(cats) == 1:
        return f"קטגוריה {listed} בסיווג וינה כוללת חטיבה אחת בלבד."
    return f"{_int(len(cats))} קטגוריות בסיווג וינה כוללות חטיבה אחת בלבד: {listed}{more}."


def insight_vienna_gaps(per_cat):
    gapped = per_cat[per_cat["max_div"] > per_cat["n"]]
    if gapped.empty or len(per_cat) < 3:
        return None
    ex = gapped.assign(gap=gapped["max_div"] - gapped["n"]).sort_values(
        ["gap", "cat"], ascending=[False, True], kind="stable").iloc[0]
    where = (f"בכל {_int(len(per_cat))} הקטגוריות" if len(gapped) == len(per_cat)
             else f"ב-{_int(len(gapped))} מתוך {_int(len(per_cat))} הקטגוריות")
    return (f"מספור החטיבות אינו רציף {where}: "
            f"בקטגוריה {int(ex['cat'])} ({_vienna_title(int(ex['cat']))}) יש {_int(ex['n'])} חטיבות "
            f"בלבד, אך המספר הגבוה הוא {int(ex['cat'])}.{int(ex['max_div'])}. "
            "כלומר, קוד החטיבה הוא מזהה קבוע ולא מספר סידורי.")


def insight_concentration(by_size, total):
    """Top-5 share of divisions and the median category size."""
    if len(by_size) < 8 or total == 0:
        return None
    top5 = int(by_size["n"].head(5).sum())
    if top5 / total < 1.3 * 5 / len(by_size):
        return None  # close to an even split: no concentration to report
    med = float(by_size["n"].median())
    med_s = f"{med:.0f}" if med == int(med) else f"{med:.1f}"
    return (f"החלוקה אינה אחידה: 5 הקטגוריות הגדולות בסיווג וינה מכילות {_int(top5)} "
            f"מתוך {_int(total)} החטיבות ({_pct(top5 / total)}), ובמחצית מהקטגוריות "
            f"יש {med_s} חטיבות או פחות.")


def insight_text_categories(per_cat, vienna):
    """Lettering categories (27, 28) as a share of all divisions: a mark that
    is mostly text is coded there. Only when both are present."""
    sub = per_cat[per_cat["cat"].isin([27, 28])]
    if len(sub) < 2 or len(vienna) == 0:
        return None
    n = int(sub["n"].sum())
    scripts = vienna[vienna["cat"] == 28]
    has_he = bool(scripts["en"].str.contains("hebrew", case=False).any())
    he_note = ", ובהן חטיבה נפרדת לאותיות עבריות" if has_he else ""
    return (f"שתי קטגוריות עוסקות בכתב עצמו: 27 (צורות כתב וספרות) ו-28 (כיתובים באותיות שונות), "
            f"יחד {_int(n)} חטיבות ({_pct(n / len(vienna))} מהחטיבות){he_note}.")


# ── compute ───────────────────────────────────────────────────────────────

def compute(frames):
    nice = _prepare_nice(frames["nice"])
    vienna = _prepare_vienna(frames["vienna"])

    n_nice = len(nice)
    n_goods = int((nice["kind"] == "goods").sum())
    n_services = n_nice - n_goods
    n_div = len(vienna)

    per_cat = (vienna.groupby("cat")
               .agg(n=("div", "size"), max_div=("div", "max"), min_div=("div", "min"))
               .reset_index())
    n_cat = len(per_cat)
    by_size = per_cat.sort_values(["n", "cat"], ascending=[False, True], kind="stable").reset_index(drop=True)
    per_cat = per_cat.sort_values("cat", kind="stable").reset_index(drop=True)
    avg = n_div / n_cat if n_cat else 0.0

    # Nice table + treemap
    nice_rows = [{"cls": int(r.cls), "he": r.he, "en": r.en,
                  "kind": "סחורות" if r.kind == "goods" else "שירותים"}
                 for r in nice.itertuples()]
    nice_tree = []
    for kind, label in (("goods", "סחורות"), ("services", "שירותים")):
        part = nice[nice["kind"] == kind]
        if part.empty:
            continue
        nice_tree.append({
            "name": f"{label} ({len(part)})",
            "value": int(len(part)),
            "children": [{"name": f"{int(r.cls)} {r.he}", "value": 1} for r in part.itertuples()],
        })

    # Vienna by category
    cat_labels = [f"{int(c)} {_vienna_title(int(c))}" for c in by_size["cat"]]
    vienna_bar = {"names": cat_labels, "values": [int(v) for v in by_size["n"]]}
    vienna_table = [{"cat": int(r.cat), "name": _vienna_title(int(r.cat)), "n": int(r.n),
                     "range": f"{int(r.cat)}.{int(r.min_div)} עד {int(r.cat)}.{int(r.max_div)}"}
                    for r in by_size.itertuples()]

    vienna_tree = []
    for r in per_cat.itertuples():
        part = vienna[vienna["cat"] == r.cat]
        vienna_tree.append({
            "name": f"{int(r.cat)} {_vienna_title(int(r.cat))}",
            "value": int(r.n),
            "children": [{"name": f"{p.code} {p.he}", "value": 1} for p in part.itertuples()],
        })

    gaps = {"names": [str(int(c)) for c in per_cat["cat"]],
            "count": [int(v) for v in per_cat["n"]],
            "max_div": [int(v) for v in per_cat["max_div"]]}
    gaps_table = [{"cat": int(r.cat), "name": _vienna_title(int(r.cat)), "n": int(r.n),
                   "max": f"{int(r.cat)}.{int(r.max_div)}", "unused": int(r.max_div - r.n)}
                  for r in per_cat.itertuples()]
    n_gapped = int((per_cat["max_div"] > per_cat["n"]).sum())

    rules = [
        ("goods_services", insight_goods_services(nice)),
        ("vienna_leader", insight_vienna_leader(by_size, n_div)),
        ("concentration", insight_concentration(by_size, n_div)),
        ("vienna_single", insight_vienna_single(per_cat)),
        ("vienna_gaps", insight_vienna_gaps(per_cat)),
        ("text_categories", insight_text_categories(per_cat, vienna)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    top = by_size.iloc[0] if n_cat else None
    summary = (f"איתור סיווג לסימן מסחר: {_int(n_nice)} מחלקות ניצה לסחורות ושירותים "
               f"ו-{_int(n_div)} חטיבות בסיווג וינה לרכיבים ציוריים, בעברית ובאנגלית.")

    lede = (f"שתי טבלאות הסיווג שבהן משתמשים ברישום סימן מסחר בישראל. סיווג ניצה (Nice) "
            f"מחלק את הסחורות והשירותים ל-{_int(n_nice)} מחלקות: {_int(n_goods)} לסחורות "
            f"ו-{_int(n_services)} לשירותים. סיווג וינה (Vienna) מקטלג את הרכיבים הציוריים "
            f"של הסימן, כמו לוגו, דמות או צורה, ב-{_int(n_div)} חטיבות "
            f"תחת {_int(n_cat)} קטגוריות.")

    labels = {
        "lede": lede,
        "nice_note": (f"כל מחלקה היא ריבוע אחד. {_int(n_goods)} מחלקות הסחורות"
                      + (f" ו-{_int(n_services)} מחלקות השירותים" if n_services else "")
                      + ". הטבלה המלאה מופיעה מתחת לתרשים."),
        "nice_aria": (f"מפת ריבועים של {_int(n_nice)} מחלקות ניצה: {_int(n_goods)} סחורות"
                      f" ו-{_int(n_services)} שירותים."),
        "nice_caption": f"{_int(n_nice)} מחלקות ניצה עם תיאור בעברית ובאנגלית",
        "vienna_note": (f"מספר החטיבות בכל קטגוריה של סיווג וינה, בממוצע {avg:.1f} לקטגוריה."
                        + (f" הגדולה: {int(top['cat'])} {_vienna_title(int(top['cat']))} ({_int(top['n'])})."
                           if top is not None else "")),
        "vienna_aria": (f"תרשים עמודות: חטיבות ב-{_int(n_cat)} קטגוריות של סיווג וינה"
                        + (f", הגדולה {_vienna_title(int(top['cat']))} עם {_int(top['n'])}." if top is not None else ".")),
        "vienna_caption": f"חטיבות לפי קטגוריה בסיווג וינה, {_int(n_cat)} קטגוריות",
        "tree_note": (f"כל {_int(n_div)} החטיבות, מקובצות לפי קטגוריה. ריחוף על ריבוע מציג "
                      "את קוד החטיבה ותיאורה."),
        "tree_aria": f"מפת ריבועים של {_int(n_div)} חטיבות וינה ב-{_int(n_cat)} קטגוריות.",
        "gaps_note": (f"מספר החטיבות בפועל מול המספר הגבוה בכל קטגוריה. ב-{_int(n_gapped)} "
                      f"מתוך {_int(n_cat)} קטגוריות המספור מדלג על מספרים."),
        "gaps_aria": (f"תרשים עמודות כפול: חטיבות בפועל מול מספר החטיבה הגבוה, "
                      f"{_int(n_cat)} קטגוריות, {_int(n_gapped)} עם דילוגים."),
        "gaps_caption": "חטיבות בפועל ומספר החטיבה הגבוה בכל קטגוריה",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["סימני מסחר", "סיווג ניצה", "סיווג וינה", "קניין רוחני"],
            "related_ids": [
                "656f6e4c-ec04-40a5-b3bc-c556b2b127e0",
                "025c3e07-358d-4892-ac2d-1e28f66ba188",
                "8687fefe-51af-4e0b-af54-701929c40102",
                "6e207fff-abef-4f4d-aac7-61e669ba9ad5",
            ],
        },
        "kpis": {
            "nice": {"value": n_nice, "display": _int(n_nice), "tone": "brand"},
            "goods": {"value": n_goods, "display": _int(n_goods), "tone": "info"},
            "services": {"value": n_services, "display": _int(n_services), "tone": "info"},
            "categories": {"value": n_cat, "display": _int(n_cat), "tone": "brand"},
            "divisions": {"value": n_div, "display": _int(n_div), "tone": "brand"},
        },
        "charts": {
            "nice_tree": nice_tree,
            "vienna": vienna_bar,
            "vienna_tree": vienna_tree,
            "gaps": gaps,
        },
        "tables": {
            "nice": nice_rows,
            "vienna": vienna_table,
            "gaps": gaps_table,
        },
        "insights": insights,
        "labels": labels,
    }
