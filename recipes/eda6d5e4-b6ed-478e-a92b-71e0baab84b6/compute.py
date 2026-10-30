"""Sharia-court qadis (בתי הדין השרעיים - קאדים), Ministry of Justice.

One column, one row per entry: an honorific title followed by a name
("השופט אחמד כיאל", "הנשיא ..."), sometimes with a " - <place>" qualifier,
plus role entries that are not a person ("נותן ההחלטה קאדי תורן").

The page is a lookup roster of the serving qadis (public officials named in
their official capacity) plus the list's composition by title. Every count
and sentence is computed from the rows; nothing about the list is hardcoded.
"""

import re

COL = "קאדים"

# Known title prefixes, longest first so "השופטת" wins over "השופט".
# (prefix, display label, kind, female, rank)
#   kind: "person" for a named qadi, "role" for an entry naming a function.
TITLES = [
    ("סגנית הנשיא", "סגנית נשיא", "person", True, 1),
    ("סגן הנשיא", "סגן נשיא", "person", False, 1),
    ("הנשיאה", "נשיאה", "person", True, 0),
    ("הנשיא", "נשיא", "person", False, 0),
    ("השופטת", "שופטת", "person", True, 3),
    ("השופט", "שופט", "person", False, 2),
    ("הקאדית", "קאדית", "person", True, 3),
    ("הקאדי", "קאדי", "person", False, 2),
    ("נותן ההחלטה", "נותן ההחלטה", "role", False, 9),
    ("נותנת ההחלטה", "נותנת ההחלטה", "role", True, 9),
]
TITLES.sort(key=lambda t: -len(t[0]))
NO_TITLE = "ללא תואר"
ROLE_WORDS = ("תורן", "תורנית")
PLURAL = {
    "נשיא": ("נשיא", "נשיאים"), "נשיאה": ("נשיאה", "נשיאות"),
    "סגן נשיא": ("סגן נשיא", "סגני נשיא"), "סגנית נשיא": ("סגנית נשיא", "סגניות נשיא"),
    "שופט": ("שופט", "שופטים"), "שופטת": ("שופטת", "שופטות"),
    "קאדי": ("קאדי", "קאדים"), "קאדית": ("קאדית", "קאדיות"),
}
QUAL_RE = re.compile("\\s+[-\u2013]\\s+")


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _parse(raw):
    s = _norm(raw)
    if not s:
        return None
    parts = QUAL_RE.split(s, maxsplit=1)
    main = parts[0].strip()
    qual = parts[1].strip() if len(parts) > 1 else ""
    title, kind, female, rank, name, pfx = NO_TITLE, "person", False, 5, main, ""
    for prefix, label, k, f, r in TITLES:
        if main == prefix or main.startswith(prefix + " "):
            title, kind, female, rank, pfx = label, k, f, r, prefix
            name = main[len(prefix):].strip()
            break
    if any(w in name.split() for w in ROLE_WORDS):
        kind = "role"
    if not name:
        name = main
    return {"raw": s, "title": title, "kind": kind, "female": female,
            "rank": rank, "name": name, "qual": qual, "prefix": pfx}


def _count_he(n, label):
    one, many = PLURAL.get(label, (label, label))
    return one if n == 1 else f"{n:,} {many}"


def _join_he(items):
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    conj = " ו-" if re.match(r"[0-9\"]", items[-1]) else " ו"
    return ", ".join(items[:-1]) + conj + items[-1]


def _pct(x):
    return f"{x * 100:.1f}%"


# ---------------------------------------------------------------- insights

def insight_composition(title_counts, n_persons):
    if n_persons < 2:
        return None
    parts = [_count_he(c, t) for t, c in title_counts]
    return f"ברשימה {n_persons:,} קאדים: {_join_he(parts)}."


def insight_head(persons):
    heads = [p for p in persons if p["rank"] == 0]
    if len(heads) != 1:
        return None
    h = heads[0]
    word = "הנשיאה" if h["female"] else "הנשיא"
    return f"בראש הרשימה עומד{'ת' if h['female'] else ''} {word} {h['name']}."


def insight_women(persons):
    n = len(persons)
    if n < 5:
        return None
    women = [p["name"] for p in persons if p["female"]]
    if not women:
        return (f"כל {n:,} הקאדים ברשימה רשומים בתואר בלשון זכר; "
                "אין ברשימה שופטת.")
    if len(women) == 1:
        return f"ברשימה שופטת אחת מתוך {n:,} קאדים ({_pct(1 / n)}): {women[0]}."
    return (f"{len(women):,} מתוך {n:,} הקאדים ({_pct(len(women) / n)}) רשומות "
            f"בתואר בלשון נקבה: {_join_he(women)}.")


def insight_dups(dups):
    if not dups:
        return None
    out = []
    for name, quals in dups[:3]:
        named = [q for q in quals if q]
        if named:
            q = _join_he([f"\"{x}\"" for x in named])
            out.append(f"{name} ({len(quals):,} רשומות, אחת מהן בצירוף {q})"
                       if len(named) == 1 else
                       f"{name} ({len(quals):,} רשומות, בצירוף {q})")
        else:
            out.append(f"{name} ({len(quals):,} רשומות)")
    lead = ("קאדי אחד מופיע ברשימה יותר מפעם אחת" if len(dups) == 1
            else f"{len(dups):,} קאדים מופיעים ברשימה יותר מפעם אחת")
    more = f" ועוד {len(dups) - 3:,}" if len(dups) > 3 else ""
    return (f"{lead}: {_join_he(out)}{more}. "
            "לכן מספר הרשומות גבוה ממספר הקאדים.")


def insight_roles(roles):
    if not roles:
        return None
    names = _join_he([f"\"{r['raw']}\"" for r in roles])
    if len(roles) == 1:
        return (f"רשומה אחת אינה שם של אדם אלא תפקיד: {names}. "
                "היא מוצגת בנפרד ואינה נספרת בין הקאדים.")
    return (f"{len(roles):,} רשומות אינן שמות של אנשים אלא תפקידים: {names}. "
            "הן מוצגות בנפרד ואינן נספרות בין הקאדים.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = frames["qadis"]
    rows = [r for r in (_parse(v) for v in df[COL].tolist()) if r]
    # Total order: rank, name, qualifier, raw text.
    rows.sort(key=lambda r: (r["rank"], r["name"], r["qual"], r["raw"]))
    n_entries = len(rows)

    # Distinct persons by name; the best-ranked title wins.
    persons_by_name = {}
    quals_by_name = {}
    for r in rows:
        if r["kind"] != "person":
            continue
        quals_by_name.setdefault(r["name"], []).append(r["qual"])
        if r["name"] not in persons_by_name:
            persons_by_name[r["name"]] = r
    persons = sorted(persons_by_name.values(), key=lambda r: (r["rank"], r["name"]))
    roles = [r for r in rows if r["kind"] == "role"]
    n_persons = len(persons)
    dups = sorted(((n, sorted(q)) for n, q in quals_by_name.items() if len(q) > 1),
                  key=lambda t: t[0])

    # Composition by title (distinct persons), ordered by rank then label.
    tc = {}
    for p in persons:
        key = (p["rank"], p["title"])
        tc[key] = tc.get(key, 0) + 1
    title_counts = [(t, c) for (rk, t), c in sorted(tc.items())]
    n_women = sum(1 for p in persons if p["female"])
    share_w = n_women / n_persons if n_persons else 0.0

    chart_names = [t for t, _ in title_counts]
    chart_vals = [int(c) for _, c in title_counts]
    if roles:
        chart_names.append("רשומות תפקיד")
        chart_vals.append(len(roles))

    rules = [
        ("composition", insight_composition(title_counts, n_persons)),
        ("head", insight_head(persons)),
        ("women", insight_women(persons)),
        ("dups", insight_dups(dups)),
        ("roles", insight_roles(roles)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    heads = [p for p in persons if p["rank"] == 0]
    head_txt = f", ובראשם {heads[0]['prefix']} {heads[0]['name']}" if len(heads) == 1 else ""
    summary = (f"איתור קאדי בבתי הדין השרעיים לפי שם: רשימת {n_persons:,} "
               f"הקאדים המכהנים{head_txt}.")
    if len(summary) > 155:
        summary = f"איתור קאדי בבתי הדין השרעיים לפי שם: רשימת {n_persons:,} הקאדים המכהנים."

    roster = [{"title": r["title"], "name": r["name"], "qual": r["qual"],
               "role": r["kind"] == "role", "raw": r["raw"]} for r in rows]

    comp_aria = (f"תרשים עמודות: הרכב רשימת הקאדים לפי תואר. "
                 + _join_he([f"{t} {c:,}" for t, c in zip(chart_names, chart_vals)])
                 + ".")
    top_title = max(title_counts, key=lambda t: (t[1], -chart_names.index(t[0])))[0] \
        if title_counts else ""
    top_n = dict(title_counts).get(top_title, 0)
    comp_lede = ""
    top_tied = sum(1 for _, c in title_counts if c == top_n) > 1
    if n_persons and not (top_tied and top_n * 2 <= n_persons):
        lead = ("רוב הקאדים ברשימה רשומים בתואר" if top_n * 2 > n_persons
                else "התואר הנפוץ ביותר ברשימה הוא")
        comp_lede = (f"{lead} {top_title}: "
                     f"{top_n:,} מתוך {n_persons:,} קאדים ({_pct(top_n / n_persons)}).")

    roles_txt = ""
    if len(roles) == 1:
        roles_txt = " ורשומת תפקיד אחת"
    elif roles:
        roles_txt = f" ו-{len(roles):,} רשומות תפקיד"
    roster_lede = (f"כל {n_entries:,} הרשומות במאגר, לפי תואר ובסדר אלפביתי: "
                   f"{n_persons:,} קאדים שונים{roles_txt}.")

    kpis = {
        "persons": {"value": n_persons, "display": f"{n_persons:,}", "tone": "brand"},
        "entries": {"value": n_entries, "display": f"{n_entries:,}", "tone": "brand"},
        "women": {"value": n_women, "display": f"{n_women:,}",
                  "tone": "info" if n_women else "warn"},
        "women_share": {"value": round(share_w, 4), "display": _pct(share_w),
                        "tone": "info" if n_women else "warn"},
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["בתי דין שרעיים", "קאדים", "שופטים", "מערכת המשפט"],
            "related_ids": [
                "176f2727-476e-440e-bc8d-5d3461ea0e76",
                "669b2652-f75b-4de3-8e6b-0dfa17accef5",
                "713440a1-9963-4548-a7d9-9d9c9da54f62",
            ],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": ["persons", "women", "women_share", "entries"],
        "charts": {"composition": {"names": chart_names, "values": chart_vals}},
        "insights": insights,
        "tables": {
            "roster": roster,
            "composition": [{"name": n, "n": v} for n, v in zip(chart_names, chart_vals)],
        },
        "flags": {"has_chart": len(chart_names) >= 2, "has_roles": bool(roles)},
        "labels": {
            "kpi_persons": "קאדים ברשימה",
            "kpi_women": "שופטות",
            "kpi_women_share": "שיעור הנשים בין הקאדים",
            "kpi_entries": "רשומות במאגר",
            "composition_aria": comp_aria,
            "composition_lede": comp_lede,
            "roster_lede": roster_lede,
            "roster_caption": f"רשימת הקאדים בבתי הדין השרעיים: {n_entries:,} רשומות.",
        },
    }
