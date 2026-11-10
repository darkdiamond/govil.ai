"""רשימת מומחים בתחום הנדסה אזרחית מטעם בתי המשפט.

One row per expert. Every field is free text the court administration types:
specialisations are sentences (one per line, sometimes run together),
districts are "<letter> - <name>" lists with inconsistent spacing, degrees are
" - "-separated sentences. compute() normalises each into sets per expert and
counts experts (never mentions), so an expert listed for six districts counts
once per district and once overall.
"""
import re
from collections import Counter

from govlib.fmt import int_he, join_he, pct

# Specialisation families, in the court administration's own order. An expert
# belongs to every family whose pattern matches; one matching none is "אחר".
FAMILIES = [
    ("ניהול פרויקטים ופיקוח", r"ניהול\s*פרויקטים|פיקוח"),
    ("ליקויי בנייה", r"ליקויי\s*בני"),
    ("חומרי בנייה", r"חומרי\s*בני"),
    ("הנדסת מבנים", r"הנדסת\s*מבנים|קונסטרוקציה|גאוטכני|ביסוס"),
    ("תשתיות", r"תשתיות|כבישים|אספלט|מסילות"),
    ("מערכות תברואה", r"תברואה|ביוב|ניקוז"),
    ("מנהור וגשרים", r"מנהור|גשר"),
]
OTHER = "אחר"
# Short chart labels (mobile axis width); tables and prose use the full names.
SHORT = {
    "ניהול פרויקטים ופיקוח": "ניהול ופיקוח",
    "ליקויי בנייה": "ליקויים",
    "חומרי בנייה": "חומרים",
    "הנדסת מבנים": "מבנים",
    "מערכות תברואה": "תברואה",
}


def _short(name):
    return SHORT.get(name, name)

# Highest academic degree named in the free text. "תואר ראשון (מוסמך)" is the
# Technion's B.Sc., so "מוסמך" alone is not a master's degree; a הנדסאי
# diploma is not an academic degree.
DEGREES = [
    ("תואר שלישי", r"תואר\s*שלישי|דוקטור|Ph\.?D"),
    ("תואר שני", r"תואר\s*שני|מגיסטר|M\.?Sc|M\.?B\.?A"),
    ("תואר ראשון", r"תואר\s*ראשון|B\.?Sc"),
]
NO_DEGREE = "ללא תואר אקדמי מפורט"

# Institutions recognised by name; anything else is not counted (disclosed).
INSTITUTIONS = [
    ("הטכניון", r"טכניון|מכון טכנולוגי לישראל"),
    ("אוניברסיטת תל אביב", r"אוניברסיטת\s*תל[\s-]*אביב|,\s*תל[\s-]*אביב"),
    ("אוניברסיטת אריאל", r"אריאל"),
    ("אוניברסיטת בן-גוריון", r"בן[\s-]*גוריון"),
    ("האוניברסיטה העברית", r"העברית"),
    ("אוניברסיטת חיפה", r"אוניברסיטת\s*חיפה"),
    ("מכללות להנדסה", r"מכללה|מכללת|אפקה|בראודה|סמי\s*שמעון|שנקר|עזריאלי"),
]

# Professional credentials beside the degree.
CREDENTIALS = [
    ("רישום בפנקס המהנדסים", r"פנקס\s*המהנדסים"),
    ("שמאות מקרקעין", r"שמאי|שמאות"),
    ("בוררות וגישור", r"בורר|גישור|גשור"),
    ("נגישות", r"נגישות"),
    ("בטיחות", r"בטיחות"),
    ("בקרת בנייה ותכן", r"בקר"),  # בקר תכן, בקרת בנייה, פנקס הבקרים, בקר מיגון
]

_DISTRICT_PREFIX = re.compile(r"^\s*([א-ת])\s*-\s*")
_SPACE = re.compile(r"\s+")


def _clean(s):
    return _SPACE.sub(" ", str(s)).strip()


def _families(text):
    found = [name for name, pat in FAMILIES if re.search(pat, text)]
    if not found and _clean(text):
        found = [OTHER]
    return found


def _districts(text):
    """{key: name} for one expert. The key is the district's letter code
    ('ד' for 'ד - תל אביב'), which is the court administration's district id
    and order, so a new spelling of the name ('ד - תל-אביב') stays the same
    district. A part with no letter prefix is keyed by its name (sorts last)."""
    out = {}
    for part in re.split(r"[,\n;]", text):
        part = _clean(part)
        if not part:
            continue
        m = _DISTRICT_PREFIX.match(part)
        name = _clean(part[m.end():] if m else part).strip(".")
        if name:
            out[m.group(1) if m else f"~{name}"] = name
    return out


def _languages(text):
    out = set()
    for part in re.split(r"[,\n;/]", text):
        part = _clean(part.replace("*", "")).strip(".")
        if part:
            out.add(part)
    return out


def _first_match(text, table, default):
    for name, pat in table:
        if re.search(pat, text, flags=re.IGNORECASE):
            return name
    return default


def _count_matches(texts, table):
    """Experts whose text matches each (name, pattern), ranked; zero counts dropped."""
    counts = Counter()
    for t in texts:
        for name, pat in table:
            if re.search(pat, t):
                counts[name] += 1
    return [(nm, c) for nm, c in _rank(counts) if c]


def _rank(counter, order=None):
    """(name, count) sorted by count desc, then a fixed order or the name."""
    key = order or {}
    return sorted(counter.items(), key=lambda kv: (-kv[1], key.get(kv[0], 99), kv[0]))


def _share_rows(ranked, total):
    return [{"name": n, "count": int_he(c), "share": pct(c / total)} for n, c in ranked]


def compute(frames):
    df = frames["experts"].copy()
    df["expert_name"] = df["expert_name"].map(_clean)
    df = df[df["expert_name"] != ""].sort_values("expert_name", kind="stable").reset_index(drop=True)
    n = len(df)
    if n == 0:
        raise ValueError("the expert list has no named experts")

    fams = df["secondary_specialization"].map(_families)
    dists = df["districts"].map(_districts)
    langs = df["languages"].map(_languages)
    degree_text = df["degrees_certificates"].map(_clean)

    # ── specialisations ──────────────────────────────────────────────────
    fam_order = {name: i for i, (name, _) in enumerate(FAMILIES)}
    fam_counts = Counter(f for fs in fams for f in fs)
    fam_ranked = _rank(fam_counts, fam_order)
    fam_names = [f for f, _ in fam_ranked]
    n_families = sum(1 for f in fam_names if f != OTHER)
    nspec = fams.map(len)
    nspec_buckets = [("לא צוין", int((nspec == 0).sum()))] if (nspec == 0).any() else []
    for k in range(1, 4):
        nspec_buckets.append((f"{k}", int((nspec == k).sum())))
    nspec_buckets.append(("4+", int((nspec >= 4).sum())))
    multi = int((nspec >= 2).sum())

    pairs = Counter()
    for fs in fams:
        s = sorted(fs, key=lambda f: fam_order.get(f, 99))
        for i in range(len(s)):
            for j in range(i + 1, len(s)):
                pairs[(s[i], s[j])] += 1
    pair_ranked = sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))[:8]

    # ── districts ────────────────────────────────────────────────────────
    # A district written without its letter ('ירושלים') joins the lettered
    # district spelled the same way, so it is never a second column.
    letter_by_name = {name: key for d in dists for key, name in d.items() if not key.startswith("~")}
    dists = dists.map(lambda d: {(letter_by_name.get(name, key) if key.startswith("~") else key): name
                                 for key, name in d.items()})
    spellings: dict[str, Counter] = {}
    for d in dists:
        for key, name in d.items():
            spellings.setdefault(key, Counter())[name] += 1
    dist_keys = sorted(spellings)  # letter order; prefix-less names (~) last
    # Each district shows its most common spelling (ties: alphabetical).
    name_of = {k: min(spellings[k].items(), key=lambda kv: (-kv[1], kv[0]))[0] for k in dist_keys}
    dist_names = [name_of[k] for k in dist_keys]
    dist_counts = {name_of[k]: sum(1 for d in dists if k in d) for k in dist_keys}
    n_dist = len(dist_names)
    ndist = dists.map(len)
    nationwide = int((ndist == n_dist).sum()) if n_dist > 1 else 0
    ndist_hist = [("לא צוין", int((ndist == 0).sum()))] if (ndist == 0).any() else []
    ndist_hist += [(f"{k}", int((ndist == k).sum())) for k in range(1, max(n_dist, 1) + 1)]
    single_district = int((ndist == 1).sum())

    # specialisation × district: experts available
    matrix = []
    for fi, f in enumerate(fam_names):
        for di, dn in enumerate(dist_names):
            k = dist_keys[di]
            v = sum(1 for fs, d in zip(fams, dists, strict=True) if f in fs and k in d)
            matrix.append([di, fi, v])
    cell = {(m[1], m[0]): m[2] for m in matrix}

    # ── languages ────────────────────────────────────────────────────────
    lang_counts = Counter(lng for ls in langs for lng in ls)
    lang_ranked = _rank(lang_counts)
    top_langs = lang_ranked[:8]
    rest = sum(c for _, c in lang_ranked[8:])
    if rest:
        top_langs = top_langs + [(OTHER, rest)]
    beyond_hebrew = int(sum(1 for ls in langs if ls - {"עברית"}))

    # ── education and credentials ────────────────────────────────────────
    deg = degree_text.map(lambda t: _first_match(t, DEGREES, NO_DEGREE))
    deg_order = [d for d, _ in DEGREES] + [NO_DEGREE]
    deg_counts = [(d, int((deg == d).sum())) for d in deg_order]
    deg_counts = [(d, c) for d, c in deg_counts if c]
    advanced = int(deg.isin(["תואר שלישי", "תואר שני"]).sum())

    inst_ranked = _count_matches(degree_text, INSTITUTIONS)
    inst_counts = dict(inst_ranked)
    cred_ranked = _count_matches(degree_text, CREDENTIALS)

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def lead_spec():
        if len(fam_ranked) < 2:
            return None
        (f1, c1), (f2, c2) = fam_ranked[0], fam_ranked[1]
        if c1 == c2:
            return None
        return (f"התחום הנפוץ ברשימה הוא {f1}: {int_he(c1)} מתוך {int_he(n)} המומחים "
                f"({pct(c1 / n)}) רשומים בו, ואחריו {f2} עם {int_he(c2)}. "
                "מומחה יכול להיות רשום בכמה תחומים.")

    def coverage():
        if n_dist < 2:
            return None
        best = max(dist_names, key=lambda d: (dist_counts[d], -dist_names.index(d)))
        worst = min(dist_names, key=lambda d: (dist_counts[d], dist_names.index(d)))
        if dist_counts[best] == dist_counts[worst]:
            return None
        return (f"מחוז {best} מכוסה בידי {int_he(dist_counts[best])} מומחים ({pct(dist_counts[best] / n)}), "
                f"ומחוז {worst} בידי {int_he(dist_counts[worst])} בלבד ({pct(dist_counts[worst] / n)}).")

    def nation():
        if n_dist < 2 or nationwide == 0:
            return None
        tail = (f", ו-{int_he(single_district)} רשומים במחוז אחד בלבד" if single_district else "")
        return (f"{int_he(nationwide)} מומחים ({pct(nationwide / n)}) מוכנים לקבל מינויים בכל "
                f"{int_he(n_dist)} המחוזות{tail}.")

    def thin_cell():
        best = None
        for fi, f in enumerate(fam_names):
            total = fam_counts[f]
            if total < 10 or f == OTHER:
                continue
            for di, dn in enumerate(dist_names):
                v = cell[(fi, di)]
                ratio = v / total
                if ratio < 0.5 and (best is None or (ratio, v, fi, di) < best[0]):
                    best = ((ratio, v, fi, di), f, dn, v, total)
        if best is None:
            return None
        _, f, dn, v, total = best
        return (f"הפער הגדול ביותר בכיסוי: מבין {int_he(total)} המומחים בתחום {f}, "
                f"רק {int_he(v)} ({pct(v / total)}) זמינים במחוז {dn}.")

    def multi_spec():
        if multi == 0 or not pair_ranked:
            return None
        (a, b), c = pair_ranked[0]
        return (f"{int_he(multi)} מומחים ({pct(multi / n)}) רשומים ביותר מתחום אחד. "
                f"הצירוף הנפוץ ביותר הוא {a} עם {b} ({int_he(c)} מומחים).")

    def language():
        if beyond_hebrew == 0:
            return None
        others = [(lng, c) for lng, c in lang_ranked if lng != "עברית"][:3]
        listed = join_he([f"{lng} ({int_he(c)})" for lng, c in others])
        return (f"{int_he(beyond_hebrew)} מומחים ({pct(beyond_hebrew / n)}) מציינים שפה נוספת על עברית. "
                f"הנפוצות: {listed}.")

    def education():
        tech = inst_counts.get("הטכניון", 0)
        if advanced == 0 and tech == 0:
            return None
        parts = []
        if advanced:
            parts.append(f"ל-{int_he(advanced)} מומחים ({pct(advanced / n)}) תואר מתקדם (שני או שלישי)")
        if tech:
            parts.append(f"{int_he(tech)} ({pct(tech / n)}) למדו בטכניון")
        return "לפי פרטי ההשכלה ברשימה, " + " ו-".join(parts) + "."

    def credentials():
        if not cred_ranked:
            return None
        top = cred_ranked[:3]
        return ("לצד ההשכלה ההנדסית, חלק מהמומחים מחזיקים בהכשרה נוספת: "
                + join_he([f"{nm} ({int_he(c)})" for nm, c in top]) + ".")

    add("lead_spec", lead_spec())
    add("coverage", coverage())
    add("thin_cell", thin_cell())
    add("nationwide", nation())
    add("multi", multi_spec())
    add("languages", language())
    add("education", education())
    add("credentials", credentials())

    # ── KPIs ─────────────────────────────────────────────────────────────
    worst = min(dist_names, key=lambda d: (dist_counts[d], dist_names.index(d))) if dist_names else None
    best_v = max(dist_counts.values()) if dist_counts else 0
    worst_v = dist_counts[worst] if worst else 0
    kpis = {
        "experts": {"value": n, "display": int_he(n), "tone": "brand"},
        "families": {"value": n_families, "display": int_he(n_families), "tone": "brand"},
        "nationwide": {"value": nationwide, "display": int_he(nationwide), "tone": "info"},
        "weakest": {"value": worst_v, "display": int_he(worst_v),
                    "tone": "warn" if best_v and worst_v < 0.6 * best_v else "brand"},
    }

    fam_top = fam_ranked[0][0] if fam_ranked else ""
    fam_top_n = fam_ranked[0][1] if fam_ranked else 0
    desc = (f"איתור מומחה מטעם בית המשפט בהנדסה אזרחית לפי שם, תחום ומחוז: {int_he(n)} מהנדסים, "
            f"{int_he(fam_top_n)} מהם בתחום {fam_top}.")

    labels = {
        "lede": (f"הנהלת בתי המשפט מעמידה לרשות השופטים רשימה של {int_he(n)} מומחים בהנדסה אזרחית "
                 f"שאפשר למנות לחוות דעת בתיק, ב-{int_he(n_families)} תחומי התמחות "
                 f"וב-{int_he(n_dist)} מחוזות שיפוט. הדף מנתח את הרשימה לפי תחום, מחוז, שפה והשכלה; "
                 "פרטי הקשר של כל מומחה מופיעים בטבלת הנתונים שבתחתית הדף."),
        "experts_kpi": "מומחים ברשימה",
        "families_kpi": "תחומי התמחות",
        "nationwide_kpi": f"מומחים הזמינים בכל {int_he(n_dist)} המחוזות",
        "weakest_kpi": f"מומחים הזמינים במחוז {worst}" if worst else "מומחים במחוז הפחות מכוסה",
        "spec_note": (f"מספר המומחים הרשומים בכל תחום. {int_he(multi)} מומחים רשומים ביותר מתחום אחד, "
                      "ולכן סכום העמודות גדול ממספר המומחים."),
        "spec_aria": f"מומחים לפי תחום התמחות, {int_he(n_families)} תחומים",
        "nspec_note": f"בכמה תחומים רשום כל מומחה. {pct(multi / n)} רשומים ביותר מתחום אחד.",
        "nspec_aria": "מומחים לפי מספר תחומי ההתמחות",
        "dist_note": (f"מומחה בוחר את המחוזות שבהם יקבל מינויים. {int_he(nationwide)} זמינים בכל המחוזות."),
        "dist_aria": f"מומחים זמינים לפי מחוז שיפוט, {int_he(n_dist)} מחוזות",
        "ndist_note": "בכמה מחוזות זמין כל מומחה."
                      + (f" {int_he(single_district)} רשומים במחוז אחד בלבד." if single_district else ""),
        "ndist_aria": "מומחים לפי מספר המחוזות שבהם הם זמינים",
        "matrix_note": "כמה מומחים זמינים בכל צירוף של תחום ומחוז. תא בהיר מסמן מחסור יחסי.",
        "matrix_aria": "מפת חום של מומחים לפי תחום התמחות ומחוז",
        "pairs_note": "התחומים שמומחים רשומים בהם יחד בתדירות הגבוהה ביותר.",
        "pairs_aria": "צירופי תחומים נפוצים",
        "langs_note": f"השפות שהמומחים מציינים. {int_he(beyond_hebrew)} מציינים שפה נוספת על עברית.",
        "langs_aria": "מומחים לפי שפה",
        "deg_note": "התואר הגבוה ביותר שמופיע בפרטי ההשכלה של כל מומחה.",
        "deg_aria": "מומחים לפי התואר האקדמי הגבוה ביותר",
        "inst_note": "מוסדות לימוד שזוהו לפי שמם בפרטי ההשכלה. מומחה שלמד בכמה מוסדות נספר בכל אחד.",
        "inst_aria": "מומחים לפי מוסד לימודים",
        "cred_note": "הכשרות ורישומים מקצועיים נוספים שמופיעים בפרטי ההשכלה.",
        "cred_aria": "מומחים לפי הכשרה מקצועית נוספת",
    }

    tables = {
        "spec": _share_rows(fam_ranked, n),
        "nspec": [{"name": k, "count": int_he(c)} for k, c in nspec_buckets],
        "dist": [{"name": d, "count": int_he(dist_counts[d]), "share": pct(dist_counts[d] / n)}
                 for d in dist_names],
        "ndist": [{"name": k, "count": int_he(c)} for k, c in ndist_hist],
        "matrix_cols": dist_names,
        "matrix": [{"name": f, "vals": [int_he(cell[(fi, di)]) for di in range(n_dist)]}
                   for fi, f in enumerate(fam_names)],
        "pairs": [{"name": f"{a} + {b}", "count": int_he(c)} for (a, b), c in pair_ranked],
        "langs": [{"name": lng, "count": int_he(c)} for lng, c in top_langs],
        "deg": _share_rows(deg_counts, n),
        "inst": [{"name": nm, "count": int_he(c)} for nm, c in inst_ranked],
        "cred": [{"name": nm, "count": int_he(c)} for nm, c in cred_ranked],
    }

    charts = {
        "spec": {"names": fam_names, "values": [c for _, c in fam_ranked]},
        "nspec": {"names": [k for k, _ in nspec_buckets], "values": [c for _, c in nspec_buckets]},
        "dist": {"names": dist_names, "values": [dist_counts[d] for d in dist_names]},
        "ndist": {"names": [k for k, _ in ndist_hist], "values": [c for _, c in ndist_hist]},
        "matrix": {"x": dist_names, "y": [_short(f) for f in fam_names], "full_y": fam_names,
                   "data": matrix, "max": max([m[2] for m in matrix] or [1])},
        "pairs": {"names": [f"{_short(a)} + {_short(b)}" for (a, b), _ in pair_ranked],
                  "values": [c for _, c in pair_ranked]},
        "langs": {"names": [lng for lng, _ in top_langs], "values": [c for _, c in top_langs]},
        "deg": {"names": [d for d, _ in deg_counts], "values": [c for _, c in deg_counts]},
        "inst": {"names": [nm for nm, _ in inst_ranked], "values": [c for _, c in inst_ranked]},
        "cred": {"names": [nm for nm, _ in cred_ranked], "values": [c for _, c in cred_ranked]},
    }

    flags = {
        "pairs": bool(pair_ranked),
        "districts": n_dist >= 2,
        "inst": bool(inst_ranked),
        "cred": bool(cred_ranked),
    }

    return {
        "agent_data": {
            "summary_he": desc,
            "dataset_kind": "registry",
            "spatial_coverage": f"{int_he(n_dist)} מחוזות שיפוט",
            "seo": {
                "title": "מומחים מטעם בית המשפט בהנדסה אזרחית: לפי תחום ומחוז",
                "description": desc,
                "name": "מומחים מטעם בית המשפט בהנדסה אזרחית",
                "alternate_names": [
                    "רשימת מומחים בתחום הנדסה אזרחית מטעם בתי המשפט",
                    "מהנדס מומחה מטעם בית המשפט",
                    "מומחה ליקויי בנייה מטעם בית משפט",
                    "מומחה בית משפט לניהול פרויקטים ופיקוח",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "labels": labels,
        "tables": tables,
        "flags": flags,
    }
