"""Druze religious-court qadis (בתי הדין הדרוזים - קאדים), Ministry of Justice.

One column, one row per entry. Most entries are a bare qadi name ("כמאל
קבלאן", no honorific title). Some are not a person but an administrative
decision-maker value ("החלטה בתיק הסטורי", "החלטה מנהלתית (מזכיר)"), and one
name can appear in two spellings that differ only in vowel letters
("מואפק טריף" / "מוופק טריף").

The page is a lookup roster of the qadis (public officials named in their
official capacity) plus the list's composition. Every count and sentence is
computed from the rows; nothing about the list is hardcoded.
"""

import re

COL = "קאדים"

# Words that mark an entry as an administrative value, not a person's name.
ADMIN_WORDS = {
    "החלטה", "החלטת", "החלטות", "מנהלתית", "מינהלתית", "מזכיר", "מזכירה",
    "מזכירות", "תורן", "תורנית", "נותן", "נותנת", "הסטורי", "היסטורי",
}
# Vowel letters (matres lectionis) and marks dropped to build a spelling key.
VOWEL_RE = re.compile("[אויה'\"׳״`ְ-ׇ]")
FINALS = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _is_admin(s):
    words = re.sub(r"[()\[\]{},.:;\-–]", " ", s).split()
    return any(w in ADMIN_WORDS for w in words)


def _skeleton(name):
    return " ".join(VOWEL_RE.sub("", w).translate(FINALS) for w in name.split())


def _join_he(items):
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    conj = " ו-" if re.match(r"[0-9\"A-Za-z]", items[-1]) else " ו"
    return ", ".join(items[:-1]) + conj + items[-1]


def _pct(x):
    return f"{x * 100:.1f}%"


# ---------------------------------------------------------------- insights

def insight_composition(persons):
    n = len(persons)
    if n < 2:
        return None
    if n <= 8:
        return f"ברשימה {n:,} קאדים: {_join_he([p['name'] for p in persons])}."
    return (f"ברשימה {n:,} קאדים, בהם "
            f"{_join_he([p['name'] for p in persons[:5]])} ועוד {n - 5:,}.")


def insight_variants(groups):
    if not groups:
        return None
    parts = [_join_he([f"\"{v}\"" for v in g]) for g in groups[:3]]
    more = f" ועוד {len(groups) - 3:,}" if len(groups) > 3 else ""
    if len(groups) == 1:
        g = groups[0]
        cnt = "שתי רשומות" if len(g) == 2 else f"{len(g):,} רשומות"
        return (f"{cnt} נבדלות רק באותיות אמות הקריאה: {parts[0]}. "
                "ככל הנראה זהו אותו קאדי בכתיב שונה, והוא נספר פעם אחת.")
    return (f"{len(groups):,} שמות מופיעים ברשימה ביותר מכתיב אחד: "
            f"{'; '.join(parts)}{more}. כל שם כזה נספר כקאדי אחד.")


def insight_admin(admin, n_entries, n_rows):
    if not admin:
        return None
    names = _join_he([f"\"{r}\"" for r in admin])
    if n_rows == 1:
        return (f"רשומה אחת מתוך {n_entries:,} אינה שם של קאדי אלא ערך מנהלי: "
                f"{names}. היא מוצגת בנפרד ואינה נספרת בין הקאדים.")
    return (f"{n_rows:,} מתוך {n_entries:,} הרשומות ({_pct(n_rows / n_entries)}) "
            f"אינן שמות של קאדים אלא ערכים מנהליים: {names}. "
            "הן מוצגות בנפרד ואינן נספרות בין הקאדים.")


def insight_dups(exact):
    if not exact:
        return None
    parts = [f"{name} ({c:,} פעמים)" for name, c in exact[:3]]
    more = f" ועוד {len(exact) - 3:,}" if len(exact) > 3 else ""
    lead = ("רשומה אחת חוזרת ברשימה באותו כתיב בדיוק" if len(exact) == 1
            else f"{len(exact):,} רשומות חוזרות ברשימה באותו כתיב בדיוק")
    return f"{lead}: {_join_he(parts)}{more}."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = frames["qadis"]
    raw = [s for s in (_norm(v) for v in df[COL].tolist()) if s]
    n_entries = len(raw)

    counts = {}
    for s in raw:
        counts[s] = counts.get(s, 0) + 1
    distinct = sorted(counts)
    exact = sorted(((s, c) for s, c in counts.items() if c > 1),
                   key=lambda t: (-t[1], t[0]))

    admin = [s for s in distinct if _is_admin(s)]
    names = [s for s in distinct if not _is_admin(s)]

    by_key = {}
    for s in names:
        by_key.setdefault(_skeleton(s), []).append(s)
    # One person per spelling key; the alphabetically first spelling is shown.
    persons = sorted(({"name": v[0], "spellings": v} for v in by_key.values()),
                     key=lambda p: p["name"])
    groups = [p["spellings"] for p in persons if len(p["spellings"]) > 1]
    n_persons = len(persons)
    n_admin_rows = sum(counts[s] for s in admin)
    n_name_rows = n_entries - n_admin_rows
    n_variant_rows = sum(len(g) - 1 for g in groups)

    roster = []
    for p in persons:
        for s in p["spellings"]:
            others = [o for o in p["spellings"] if o != s]
            note = f"מופיע גם בכתיב: {_join_he(others)}" if others else ""
            if counts[s] > 1:
                rep = f"מופיע {counts[s]:,} פעמים ברשימה"
                note = f"{note}; {rep}" if note else rep
            roster.append({"name": s, "kind": "קאדי", "admin": False, "note": note})
    for s in admin:
        note = f"מופיע {counts[s]:,} פעמים ברשימה" if counts[s] > 1 else "ערך שאינו שם של אדם"
        roster.append({"name": s, "kind": "ערך מנהלי", "admin": True, "note": note})

    comp = [("קאדים (שם יחיד)", n_persons)]
    if n_variant_rows:
        comp.append(("כתיב נוסף לאותו שם", n_variant_rows))
    n_exact_extra = n_name_rows - len(names)
    if n_exact_extra:
        comp.append(("רשומה חוזרת", n_exact_extra))
    if n_admin_rows:
        comp.append(("ערך מנהלי", n_admin_rows))
    chart_names = [c[0] for c in comp]
    chart_vals = [int(c[1]) for c in comp]

    rules = [
        ("composition", insight_composition(persons)),
        ("variants", insight_variants(groups)),
        ("admin", insight_admin(admin, n_entries, n_admin_rows)),
        ("dups", insight_dups(exact)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    summary = (f"איתור קאדי בבתי הדין הדתיים הדרוזיים לפי שם: רשימת {n_persons:,} "
               f"הקאדים במאגר משרד המשפטים, מתוך {n_entries:,} רשומות.")

    comp_aria = ("תרשים עמודות: הרכב רשומות המאגר. "
                 + _join_he([f"{t} {c:,}" for t, c in comp]) + ".")
    share_p = n_persons / n_entries if n_entries else 0.0
    if n_entries and n_persons == n_entries:
        comp_lede = f"כל {n_entries:,} הרשומות במאגר הן שמות של קאדים שונים."
    elif n_entries:
        comp_lede = (f"{n_persons:,} מתוך {n_entries:,} הרשומות ({_pct(share_p)}) "
                     "הן קאדים שונים. השאר: "
                     + _join_he([f"{t} ({c:,})" for t, c in comp[1:]]) + ".")
    else:
        comp_lede = ""

    admin_txt = ""
    if len(admin) == 1:
        admin_txt = " וערך מנהלי אחד"
    elif admin:
        admin_txt = f" ו-{len(admin):,} ערכים מנהליים"
    roster_lede = (f"כל הרשומות במאגר בסדר אלפביתי: {n_persons:,} קאדים{admin_txt}. "
                   "שם שמופיע ביותר מכתיב אחד מסומן בעמודת ההערה.")

    kpis = {
        "persons": {"value": n_persons, "display": f"{n_persons:,}", "tone": "brand"},
        "entries": {"value": n_entries, "display": f"{n_entries:,}", "tone": "brand"},
        "admin": {"value": n_admin_rows, "display": f"{n_admin_rows:,}",
                  "tone": "info" if n_admin_rows else "brand"},
        "variants": {"value": len(groups), "display": f"{len(groups):,}",
                     "tone": "warn" if groups else "ok"},
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["בתי דין דרוזיים", "קאדים", "העדה הדרוזית", "מערכת המשפט"],
            "related_ids": [
                "7368d9de-e3ea-43e9-9e7d-03ffffe79b5f",
                "eda6d5e4-b6ed-478e-a92b-71e0baab84b6",
                "176f2727-476e-440e-bc8d-5d3461ea0e76",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": ["persons", "entries", "admin", "variants"],
        "charts": {"composition": {"names": chart_names, "values": chart_vals}},
        "insights": insights,
        "tables": {
            "roster": roster,
            "composition": [{"name": n, "n": v} for n, v in zip(chart_names, chart_vals)],
        },
        "flags": {"has_chart": len(chart_names) >= 2},
        "labels": {
            "kpi_persons": "קאדים ברשימה",
            "kpi_entries": "רשומות במאגר",
            "kpi_admin": "ערכים מנהליים (לא שמות)",
            "kpi_variants": "שמות בכתיב כפול",
            "composition_aria": comp_aria,
            "composition_lede": comp_lede,
            "roster_lede": roster_lede,
            "roster_caption": f"רשימת הקאדים בבתי הדין הדרוזיים: {n_entries:,} רשומות.",
        },
    }
