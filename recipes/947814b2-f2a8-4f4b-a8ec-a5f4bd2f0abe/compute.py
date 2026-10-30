"""Beersheba statistical areas (אג״ס) to neighborhoods conversion table.

One row per statistical area: its code and up to three neighborhood names
(an area that straddles a boundary lists every neighborhood it touches).
Every count and sentence on the page is computed here; a rule whose premise
doesn't hold in the data returns None.
"""
import re

import pandas as pd

NB_COLS = ["neighborhood_1", "neighborhood_2", "neighborhood_3"]
MAX_BARS = 30  # neighborhood axis cap; the rest fold into "אחר"
LETTER_RE = re.compile(r"^[א-ת]{1,2}$")


def _int(n):
    return f"{int(n):,}"


def _label(name):
    """Single-letter neighborhoods (ד, יא) read as "שכונה ד׳" / "שכונה י״א"."""
    if LETTER_RE.match(name):
        if len(name) == 1:
            return f"שכונה {name}׳"
        return f"שכונה {name[0]}״{name[1]}"
    return name


def _prepare(df):
    df = df.copy()
    df["code"] = pd.to_numeric(df["stat-area"].str.replace(",", "").str.strip(),
                               errors="coerce")
    df = df.dropna(subset=["code"])
    df["code"] = df["code"].astype(int)
    for c in NB_COLS:
        df[c] = df[c].str.strip()
    df = df.drop_duplicates(subset=["code"] + NB_COLS)
    rows = []
    for _, r in df.iterrows():
        names = []
        for c in NB_COLS:
            v = r[c]
            if v and v not in names:
                names.append(v)
        if names:
            rows.append((int(r["code"]), names))
    rows.sort(key=lambda t: (t[0], t[1]))
    # Merge duplicate codes (same code listed twice with different names).
    merged = {}
    for code, names in rows:
        cur = merged.setdefault(code, [])
        for n in names:
            if n not in cur:
                cur.append(n)
    return sorted(merged.items())


def _group(code):
    return (code // 100) * 100


def _group_label(g):
    return f"{g}-{g + 99}"


def insight_top(nb_counts, n_areas):
    if nb_counts.empty or n_areas == 0:
        return None
    top = nb_counts.iloc[0]
    if len(nb_counts) > 1 and nb_counts.iloc[1] == top:
        return None  # no single leader
    name = nb_counts.index[0]
    return (f"{_label(name)} מחולקת למספר הרב ביותר של אזורים סטטיסטיים: {_int(top)} "
            f"מתוך {_int(n_areas)} ({top / n_areas * 100:.1f}%).")


def insight_singles(nb_counts):
    singles = sorted(nb_counts[nb_counts == 1].index)
    if len(singles) < 2:
        return None
    shown = ", ".join(_label(n) for n in singles[:6])
    more = f" ועוד {_int(len(singles) - 6)}" if len(singles) > 6 else ""
    return (f"{_int(len(singles))} שכונות מתוך {_int(len(nb_counts))} חופפות לאזור סטטיסטי "
            f"אחד בלבד ({shown}{more}), כך שנתוני האג״ס שלהן הם למעשה נתוני השכונה.")


def insight_split(split_rows):
    if not split_rows:
        return None
    if len(split_rows) == 1:
        code, names = split_rows[0]
        return (f"רק אזור סטטיסטי אחד, מספר {code}, משויך ליותר משכונה אחת: "
                f"{', '.join(_label(n) for n in names)}. בהמרת נתונים יש לחלק אותו בין "
                f"השכונות או לשייך אותו לאחת מהן.")
    codes = ", ".join(str(c) for c, _ in split_rows[:8])
    return (f"{_int(len(split_rows))} אזורים סטטיסטיים משויכים ליותר משכונה אחת "
            f"(מספרים {codes}). בהמרת נתונים יש לחלק אותם בין השכונות.")


def insight_cross_group(nb_groups):
    cross = sorted((n, g) for n, g in nb_groups.items() if len(g) > 1)
    if not cross:
        return None
    parts = [f"{_label(n)} (קודים {' ו-'.join(_group_label(x) for x in sorted(g))})"
             for n, g in cross[:4]]
    if len(cross) == 1:
        return (f"שכונה אחת חוצה שתי קבוצות קוד של אזורים סטטיסטיים: {parts[0]}, "
                f"כך שקידומת הקוד לבדה אינה מספיקה כדי לזהות שכונה.")
    return (f"{_int(len(cross))} שכונות חוצות כמה קבוצות קוד: {', '.join(parts)}. "
            f"קידומת הקוד לבדה אינה מספיקה כדי לזהות שכונה.")


def insight_groups(group_areas, group_nbs, n_areas):
    if len(group_areas) < 2 or n_areas == 0:
        return None
    g = group_areas.index[0]
    v = group_areas.iloc[0]
    if group_areas.iloc[1] == v:
        return None
    return (f"קבוצת הקודים {_group_label(g)} היא הגדולה ביותר: {_int(v)} אזורים סטטיסטיים "
            f"({v / n_areas * 100:.1f}%) ב-{_int(group_nbs[g])} שכונות.")


def compute(frames):
    rows = _prepare(frames["main"])
    n_areas = len(rows)

    pairs = [(code, n) for code, names in rows for n in names]
    pdf = pd.DataFrame(pairs, columns=["code", "nb"])
    pdf["group"] = pdf["code"].map(_group)

    nb_counts = (pdf.groupby("nb")["code"].nunique().sort_index()
                 .sort_values(ascending=False, kind="stable"))
    nb_codes = {n: sorted(set(c)) for n, c in pdf.groupby("nb")["code"]}
    nb_groups = {n: sorted(set(g)) for n, g in pdf.groupby("nb")["group"]}
    n_nbs = int(nb_counts.size)

    split_rows = [(c, names) for c, names in rows if len(names) > 1]
    area_groups = pd.Series([_group(c) for c, _ in rows], dtype="int64")
    group_areas = (area_groups.value_counts().sort_index()
                   .sort_values(ascending=False, kind="stable"))
    group_nbs = pdf.groupby("group")["nb"].nunique()
    n_groups = int(group_areas.size)

    # Bar: areas per neighborhood (top MAX_BARS, rest into "אחר").
    top = nb_counts.iloc[:MAX_BARS]
    bar_names = [_label(n) for n in top.index]
    bar_values = [int(v) for v in top]
    rest = nb_counts.iloc[MAX_BARS:]
    if not rest.empty:
        bar_names.append(f"אחר ({_int(rest.size)} שכונות)")
        bar_values.append(int(rest.sum()))

    nb_table = [{"name": _label(n), "count": int(nb_counts[n]),
                 "codes": ", ".join(str(c) for c in nb_codes[n])}
                for n in nb_counts.index]

    # Treemap: code group -> neighborhood (area counts).
    treemap = []
    group_table = []
    for g in sorted(group_areas.index):
        sub = (pdf[pdf["group"] == g].groupby("nb")["code"].nunique().sort_index()
               .sort_values(ascending=False, kind="stable"))
        treemap.append({
            "name": f"קודים {_group_label(g)}",
            "value": int(group_areas[g]),
            "children": [{"name": _label(n), "value": int(v)} for n, v in sub.items()],
        })
        group_table.append({"name": _group_label(g), "areas": int(group_areas[g]),
                            "nbs": int(group_nbs[g]),
                            "list": ", ".join(_label(n) for n in sub.index)})

    split_table = [{"code": c, "names": ", ".join(_label(n) for n in names)}
                   for c, names in split_rows]

    codes = [c for c, _ in rows]
    c_min, c_max = min(codes), max(codes)

    rules = [
        ("top", insight_top(nb_counts, n_areas)),
        ("split", insight_split(split_rows)),
        ("singles", insight_singles(nb_counts)),
        ("cross_group", insight_cross_group(nb_groups)),
        ("groups", insight_groups(group_areas, group_nbs, n_areas)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    avg = len(pairs) / n_nbs if n_nbs else 0  # matches the bar chart, which counts a split area in each neighborhood
    top_name = _label(nb_counts.index[0])
    top_v = int(nb_counts.iloc[0])
    summary = (f"איתור השכונה בבאר שבע לפי מספר אזור סטטיסטי (אג״ס): טבלת המרה של "
               f"{_int(n_areas)} אזורים סטטיסטיים ל-{_int(n_nbs)} שכונות בעיר.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "misc",
            "suggested_tags": ["באר שבע", "שכונות", "אזורים סטטיסטיים", "גיאוגרפיה"],
            "related_ids": [
                "3c6d4061-41bf-4403-82e9-c8fae5df04dd",
                "82a30a97-01b0-4281-854c-c7931f3445c0",
                "bdf28cc0-680a-415c-af64-944a58079b2f",
                "5944b454-751c-4604-94d6-e676d7d34612",
            ],
            "spatial_coverage": "באר שבע",
        },
        "kpis": {
            "areas": {"value": n_areas, "display": _int(n_areas), "tone": "brand"},
            "nbs": {"value": n_nbs, "display": _int(n_nbs), "tone": "brand"},
            "split": {"value": len(split_rows), "display": _int(len(split_rows)),
                      "tone": "info" if split_rows else "ok"},
            "avg": {"value": round(avg, 1), "display": f"{avg:.1f}", "tone": "brand"},
        },
        "charts": {
            "nbs": {"names": bar_names, "values": bar_values},
            "treemap": treemap,
        },
        "tables": {"nbs": nb_table, "groups": group_table, "split": split_table},
        "flags": {"split": bool(split_rows), "other": not rest.empty},
        "insights": insights,
        "labels": {
            "lede": (f"הטבלה מתרגמת כל אחד מ-{_int(n_areas)} האזורים הסטטיסטיים של באר שבע "
                     f"(מספרים {c_min} עד {c_max}) לשכונה שבה הוא נמצא, כדי שאפשר יהיה להציג "
                     f"נתונים של הלשכה המרכזית לסטטיסטיקה ושל מאגרים עירוניים, המפורסמים "
                     f"ברמת אג״ס, ברמת {_int(n_nbs)} השכונות של העיר."),
            "areas_kpi": "אזורים סטטיסטיים (אג״ס)",
            "nbs_kpi": "שכונות בטבלה",
            "split_kpi": "אזורים המשויכים ליותר משכונה אחת",
            "avg_kpi": "ממוצע אזורים סטטיסטיים לשכונה",
            "nbs_lede": (f"{top_name} מובילה עם {_int(top_v)} אזורים סטטיסטיים; בממוצע "
                         f"{avg:.1f} אזורים לשכונה. אזור המשויך לכמה שכונות נספר בכל אחת מהן."
                         + (f" מוצגות {_int(MAX_BARS)} השכונות הגדולות, והשאר מקובצות תחת "
                            f"\"אחר\"." if not rest.empty else "")),
            "nbs_aria": (f"תרשים עמודות אופקי: מספר האזורים הסטטיסטיים בכל אחת מ-{_int(n_nbs)} "
                         f"השכונות. המובילה: {top_name} עם {_int(top_v)}."),
            "nbs_caption": (f"השכונות של באר שבע ומספרי האזורים הסטטיסטיים בכל אחת "
                            f"({_int(n_nbs)} שכונות)."),
            "treemap_lede": (f"ספרת המאות בקוד האג״ס מחלקת את העיר ל-{_int(n_groups)} קבוצות "
                             f"קוד. כל מלבן הוא שכונה, וגודלו כמספר האזורים הסטטיסטיים שלה "
                             f"בקבוצה."),
            "treemap_aria": (f"מפת עץ: {_int(n_areas)} אזורים סטטיסטיים לפי {_int(n_groups)} "
                             f"קבוצות קוד ולפי שכונה."),
            "groups_caption": f"אזורים סטטיסטיים ושכונות בכל אחת מ-{_int(n_groups)} קבוצות הקוד.",
            "split_lede": ("אזורים אלה חוצים גבול בין שכונות, ולכן בטבלה המקורית רשומה לצדם "
                           "יותר משכונה אחת."),
        },
    }
