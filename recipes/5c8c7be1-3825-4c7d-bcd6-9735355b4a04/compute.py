"""שמאי רכב — Ministry of Transport register of licensed vehicle-damage appraisers.

One row per licence (~1k): licence number, first name, family name and
settlement. There are no dates, so the page is a snapshot: where appraisers
are registered (leading settlements, concentration, the long tail of
one-appraiser settlements), how the licence-number range is populated today
(a seniority proxy), which settlements hold newer or older licences, and the
common names in the profession.

Privacy: appraisers are licensed professionals and may be named, but this
page names none individually. Licence numbers are used only in aggregate
(blocks of numbers, above/below the register's median) — no individual
number, nor the register's highest number, ever reaches the page. The last
block (still being issued) gets no "missing" count, since that count plus
the listed count would reveal the highest number.

Seniority proxy: licence numbers are assumed to be issued in sequence, so a
lower number usually means an earlier licence. Copy says so ("בדרך כלל").
"""
import math
import re

import pandas as pd

TOP_CITIES = 15
TOP_NAMES = 10
NEWER_MIN = 10       # appraisers needed for a settlement to enter the newer-share ranking
NEWER_EACH = 10      # highest / lowest shown when more than 2*NEWER_EACH settlements qualify
CURVE_MARKS = [1, 5, 10, 20, 50, 100]
BUCKETS = [(1, 1), (2, 2), (3, 4), (5, 9), (10, 19), (20, 49), (50, None)]
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def p_disp(v, digits=1):
    return f"{v:.{digits}f}%"


def _city(s):
    s = re.sub(r"\s+", " ", s.replace("*", "").strip())
    s = re.sub(r"\s*-\s*", "-", s)
    # Gershayim lost upstream: "גבעת כ ח" → "גבעת כ״ח", "בסמ ה" → "בסמ״ה".
    return re.sub(r"([א-ת]) ([א-ת])$", "\\1״\\2", s)


def _clean(s):
    return re.sub(r"\s+", " ", s.strip())


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _join(items):
    items = list(items)
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " ו" + items[-1]


def _block_label(lo, hi):
    return f"{n(lo)} עד {n(hi)}"


# ---------------------------------------------------------------- insights

def insight_leader(cities, total):
    if total == 0 or len(cities) < 10:
        return None
    top, v = cities.index[0], int(cities.iloc[0])
    if v / total < 0.03:
        return None
    if len(cities) > 1 and cities.iloc[1] == v:
        return None  # tie at the top — no single leader
    t10 = int(cities.head(10).sum())
    return (f"{top} מובילה עם {n(v)} שמאי רכב ({pct(v / total * 100)}), ואחריה "
            f"{_join(cities.index[1:3])}; עשרת היישובים המובילים מרכזים "
            f"{pct(t10 / total * 100)} מהשמאים, מתוך {n(len(cities))} יישובים שיש בהם שמאי רשום.")


def insight_tail(cities):
    single = int((cities == 1).sum())
    if single < 10:
        return None
    share = single / len(cities) * 100
    return (f"{n(single)} יישובים ({pct(share, 0)} מהיישובים במרשם) רשומים עם שמאי רכב "
            f"אחד בלבד — יחד הם {pct(single / cities.sum() * 100)} מכלל השמאים.")


def insight_half(half_k, n_cities):
    if n_cities < 20 or half_k == 0:
        return None
    return (f"מחצית משמאי הרכב רשומים ב-{n(half_k)} יישובים בלבד, שהם "
            f"{pct(half_k / n_cities * 100)} מהיישובים שיש בהם שמאי.")


def insight_cohorts(full_blocks):
    """Early full blocks vs. late full blocks: share of numbers still listed."""
    if len(full_blocks) < 6:
        return None
    early, late = full_blocks[:3], full_blocks[-3:]
    e = sum(b["listed"] for b in early) / sum(b["size"] for b in early) * 100
    l_ = sum(b["listed"] for b in late) / sum(b["size"] for b in late) * 100
    if l_ - e < 20:
        return None
    return (f"מבין מספרי הרישיון {_block_label(early[0]['lo'], early[-1]['hi'])}, שניתנו בדרך כלל "
            f"ראשונים, רק {pct(e, 0)} מופיעים במרשם הנוכחי, לעומת {pct(l_, 0)} מהמספרים "
            f"{_block_label(late[0]['lo'], late[-1]['hi'])}; המספרים החסרים הם ככל הנראה רישיונות ותיקים שאינם פעילים עוד.")


def insight_newer(newer):
    if len(newer) < 6:
        return None
    hi, lo = newer.index[0], newer.index[-1]
    vh, vl = newer.iloc[0] * 100, newer.iloc[-1] * 100
    if vh - vl < 30:
        return None
    return (f"הוותק משתנה בין היישובים: ב{hi} {pct(vh, 0)} מהשמאים מחזיקים רישיון "
            f"מהמחצית החדשה של המרשם, ואילו ב{lo} רק {pct(vl, 0)} — בקרב יישובים עם "
            f"{n(NEWER_MIN)} שמאים לפחות.")


def insight_names(surnames, firsts, total):
    if total < 200 or len(surnames) < 2 or len(firsts) < 2:
        return None
    (s1, v1), (s2, v2) = list(surnames.items())[:2]
    (f1, w1), (f2, w2) = list(firsts.items())[:2]
    if v1 / total < 0.01 or v1 == v2 or w1 == w2:
        return None
    return (f"שם המשפחה הנפוץ בקרב שמאי הרכב הוא {s1} ({n(v1)} שמאים), ואחריו {s2} ({n(v2)}); "
            f"השם הפרטי הנפוץ הוא {f1} ({n(w1)}), ואחריו {f2} ({n(w2)}).")


def insight_dups(dup_pairs):
    if dup_pairs == 0:
        return None
    word = "צירוף אחד" if dup_pairs == 1 else f"{n(dup_pairs)} צירופים"
    return (f"{word} של שם מלא ויישוב מופיעים במרשם יותר מפעם אחת, כל פעם עם מספר רישיון "
            f"אחר — ייתכן שמדובר באותו שמאי שרשום פעמיים.")


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["appraisers"]
    lic = pd.to_numeric(raw["mispar_rishayon"].str.replace(",", "").str.strip(),
                        errors="coerce")
    df = pd.DataFrame({
        "lic": lic,
        "first": raw["shem_prati"].map(_clean),
        "last": raw["shem_mishpaha"].map(_clean),
        "city": raw["yishuv"].map(_city),
    })
    total = len(df)
    known = df[df["city"] != ""]
    unknown_city = total - len(known)
    cities = _sorted_counts(known["city"])
    n_cities = int(cities.size)
    lead = cities.index[0] if n_cities else ""

    # Concentration curve.
    cum = cities.cumsum() / max(len(known), 1) * 100
    curve = [round(float(v), 1) for v in cum.values]
    marks = [m for m in CURVE_MARKS if m <= n_cities]
    half_k = int((cum >= 50).values.argmax()) + 1 if n_cities else 0
    t10 = float(cum.iloc[min(10, n_cities) - 1]) if n_cities else 0.0

    # Settlement-size buckets.
    buckets = []
    for lo, hi in BUCKETS:
        m = cities >= lo
        if hi is not None:
            m &= cities <= hi
        name = f"{lo}" if lo == hi else (f"{n(lo)} ומעלה" if hi is None else f"{lo} עד {hi}")
        buckets.append({"name": name, "cities": int(m.sum()), "people": int(cities[m].sum())})

    # Licence-number blocks (seniority proxy). Block width grows with the range.
    valid = df.dropna(subset=["lic"])
    valid = valid[valid["lic"] >= 1]
    max_lic = int(valid["lic"].max()) if len(valid) else 0
    width = 100 * max(1, math.ceil(max_lic / 2000))
    block_ix = ((valid["lic"].astype(int) - 1) // width).value_counts()
    blocks = []
    for b in range(max_lic // width + (1 if max_lic % width else 0)):
        lo, hi = b * width + 1, (b + 1) * width
        listed = int(block_ix.get(b, 0))
        full = hi <= max_lic
        blocks.append({"lo": lo, "hi": hi, "size": width, "listed": listed, "full": full})
    full_blocks = [b for b in blocks if b["full"]]
    in_full = sum(b["listed"] for b in full_blocks)
    full_span = sum(b["size"] for b in full_blocks)

    # Newer-half share by settlement.
    median = float(valid["lic"].median()) if len(valid) else 0.0
    vk = valid[valid["city"] != ""].assign(newer=lambda x: x["lic"] > median)
    grp = vk.groupby("city")["newer"].agg(["size", "mean"])
    grp = grp[grp["size"] >= NEWER_MIN]
    order = (pd.DataFrame({"s": grp["mean"], "c": grp.index})
             .sort_values(["s", "c"], ascending=[False, True]))
    newer = order["s"]
    if len(newer) > 2 * NEWER_EACH:
        pick = pd.concat([newer.head(NEWER_EACH), newer.tail(NEWER_EACH)])
    else:
        pick = newer
    newer_rows = [{"name": c, "share": round(float(v * 100), 1), "total": int(grp.loc[c, "size"]),
                   "group": "high" if v >= 0.5 else "low"} for c, v in pick.items()]

    # Names.
    surnames = _sorted_counts(df.loc[df["last"] != "", "last"])
    firsts = _sorted_counts(df.loc[df["first"] != "", "first"])
    top_s, top_f = surnames.head(TOP_NAMES), firsts.head(TOP_NAMES)
    full_name = df[(df["first"] != "") & (df["last"] != "")]
    dup_pairs = int((full_name.groupby(["first", "last", "city"]).size() > 1).sum())

    top_c = cities.head(TOP_CITIES)
    charts = {
        "cities": {"names": list(top_c.index), "values": [int(v) for v in top_c.values]},
        "curve": {"x": list(range(1, n_cities + 1)), "y": curve, "names": list(cities.index)},
        "buckets": {"names": [b["name"] for b in buckets],
                    "cities": [b["cities"] for b in buckets],
                    "people": [b["people"] for b in buckets]},
        "cohorts": {"names": [_block_label(b["lo"], b["hi"]) for b in blocks],
                    "listed": [b["listed"] for b in blocks],
                    "missing": [b["size"] - b["listed"] if b["full"] else None for b in blocks]},
        "newer": {"names": [r["name"] for r in newer_rows],
                  "values": [r["share"] for r in newer_rows],
                  "groups": [r["group"] for r in newer_rows]},
        "surnames": {"names": list(top_s.index), "values": [int(v) for v in top_s.values]},
        "firsts": {"names": list(top_f.index), "values": [int(v) for v in top_f.values]},
    }

    rules = [
        ("leader", insight_leader(cities, len(known))),
        ("tail", insight_tail(cities)),
        ("half", insight_half(half_k, n_cities)),
        ("cohorts", insight_cohorts(full_blocks)),
        ("newer", insight_newer(newer)),
        ("names", insight_names(surnames, firsts, total)),
        ("dups", insight_dups(dup_pairs)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    single = int((cities == 1).sum())
    listed_pct = in_full / full_span * 100 if full_span else 0.0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "cities": {"value": n_cities, "display": n(n_cities), "tone": "brand"},
        "top10": {"value": round(t10, 1), "display": p_disp(t10),
                  "tone": "warn" if t10 >= 50 else "info"},
        "single": {"value": single, "display": n(single), "tone": "info"},
    }

    last_partial = bool(blocks) and not blocks[-1]["full"]
    labels = {
        "lede": (f"מרשם שמאי הרכב המורשים מטעם משרד התחבורה: {n(total)} שמאים רשומים "
                 f"ב-{n(n_cities)} יישובים, ו{lead} בראש עם {n(cities.iloc[0]) if n_cities else 0} שמאים. "
                 f"למרשם אין תאריכים, ולכן הדף מציג תמונת מצב: היכן השמאים רשומים, כמה מרוכזים "
                 f"הם, ואיך נראה הוותק שלהם לפי מספרי הרישיון."),
        "top10_kpi": "מהשמאים רשומים בעשרת היישובים המובילים",
        "single_kpi": f"יישובים עם שמאי אחד בלבד (מתוך {n(n_cities)})",
        "cities_note": (f"{TOP_CITIES} היישובים עם מספר שמאי הרכב הגדול ביותר. "
                        f"{lead} בראש עם {n(cities.iloc[0]) if n_cities else 0} שמאים."
                        + (f" {n(unknown_city)} רשומות ללא יישוב אינן נכללות." if unknown_city else "")),
        "cities_aria": f"תרשים עמודות אופקי: {TOP_CITIES} היישובים המובילים במספר שמאי רכב — {lead} בראש.",
        "cities_caption": f"שמאי רכב לפי יישוב ({TOP_CITIES} המובילים).",
        "curve_note": (f"היישובים מדורגים מהגדול לקטן, והקו מראה איזה חלק מהשמאים מרוכז ביישובים "
                       f"המובילים. מחצית מהשמאים רשומים ב-{n(half_k)} יישובים."),
        "curve_aria": f"גרף קו מצטבר: שיעור השמאים לפי מספר היישובים המובילים; עשרת הראשונים מרכזים {p_disp(t10)}.",
        "curve_caption": "שיעור מצטבר של שמאים לפי מספר היישובים המובילים.",
        "buckets_note": "כמה יישובים יש בכל קבוצת גודל לפי מספר השמאים הרשומים בהם, וכמה שמאים רשומים בכל קבוצה.",
        "buckets_aria": f"תרשים עמודות: יישובים ושמאים לפי מספר השמאים ביישוב — {n(single)} יישובים עם שמאי אחד.",
        "buckets_caption": "יישובים ושמאים לפי מספר השמאים ביישוב.",
        "cohorts_note": (f"כמה מספרי רישיון מכל טווח של {n(width)} מופיעים במרשם הנוכחי. מספרים נמוכים "
                         f"ניתנו בדרך כלל מוקדם יותר, ולכן מספר שאינו מופיע הוא ככל הנראה רישיון ותיק "
                         f"שכבר אינו פעיל. בטווחים המלאים מופיעים {pct(listed_pct)} מהמספרים."
                         + (" הטווח האחרון עדיין בהקצאה, ולכן לא מוצג לגביו מספר חסרים."
                            if last_partial else "")
                         + " מספרי הרישיון עצמם אינם מוצגים."),
        "cohorts_aria": "תרשים עמודות מוערמות: מספרי רישיון במרשם ומספרים שאינם במרשם, לפי טווחי מספרים.",
        "cohorts_caption": f"מספרי רישיון במרשם לפי טווחים של {n(width)}.",
        "newer_note": (f"שיעור השמאים ביישוב שמספר הרישיון שלהם במחצית העליונה של המרשם — כלומר "
                       f"רישיונות חדשים יחסית — ביישובים עם {n(NEWER_MIN)} שמאים לפחות"
                       + (f" ({NEWER_EACH} הגבוהים ו-{NEWER_EACH} הנמוכים מתוך {n(len(newer))})"
                          if len(newer) > 2 * NEWER_EACH else f" ({n(len(newer))} יישובים)")
                       + ". הקו המקווקו: מחצית."),
        "newer_aria": (f"תרשים עמודות אופקי: שיעור בעלי רישיון חדש יחסית ביישובים, "
                       f"מ{newer_rows[0]['name'] if newer_rows else ''} ועד "
                       f"{newer_rows[-1]['name'] if newer_rows else ''}."),
        "newer_caption": "שיעור השמאים עם רישיון מהמחצית החדשה של המרשם, לפי יישוב.",
        "names_note": (f"{TOP_NAMES} שמות המשפחה ו-{TOP_NAMES} השמות הפרטיים הנפוצים בקרב "
                       f"{n(total)} השמאים במרשם."),
        "surnames_aria": (f"תרשים עמודות אופקי: שמות המשפחה הנפוצים בקרב שמאי הרכב — "
                          f"{top_s.index[0] if len(top_s) else ''} בראש."),
        "surnames_caption": "שמות המשפחה הנפוצים בקרב שמאי הרכב.",
        "firsts_aria": (f"תרשים עמודות אופקי: השמות הפרטיים הנפוצים בקרב שמאי הרכב — "
                        f"{top_f.index[0] if len(top_f) else ''} בראש."),
        "firsts_caption": "השמות הפרטיים הנפוצים בקרב שמאי הרכב.",
    }

    tables = {
        "cities": [{"name": k, "count": n(v), "share": p_disp(v / max(len(known), 1) * 100)}
                   for k, v in top_c.items()],
        "curve": [{"k": n(m), "share": p_disp(curve[m - 1])} for m in marks],
        "buckets": [{"name": b["name"], "cities": n(b["cities"]), "people": n(b["people"]),
                     "share": p_disp(b["people"] / max(len(known), 1) * 100)} for b in buckets],
        "cohorts": [{"name": _block_label(b["lo"], b["hi"]), "listed": n(b["listed"]),
                     "share": p_disp(b["listed"] / b["size"] * 100) if b["full"] else "בהקצאה"}
                    for b in blocks],
        "newer": [{"name": r["name"], "total": n(r["total"]), "share": p_disp(r["share"])}
                  for r in newer_rows],
        "surnames": [{"name": k, "count": n(v)} for k, v in top_s.items()],
        "firsts": [{"name": k, "count": n(v)} for k, v in top_f.items()],
    }

    return {
        "agent_data": {
            "summary_he": (f"מרשם שמאי הרכב המורשים של משרד התחבורה: {n(total)} שמאים "
                           f"ב-{n(n_cities)} יישובים; {lead} מובילה, ועשרת היישובים המובילים "
                           f"מרכזים {p_disp(t10)} מהשמאים."),
            "dataset_kind": "registry",
            "related_ids": ["392abd0a-64f6-4c18-9d56-0111001411e6",
                            "35c791ca-8db2-4657-8c6f-eb092147a6bb",
                            "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                            "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                            "0219b34f-43c7-435b-bdfe-e65e944cde50"],
            "suggested_tags": ["שמאי רכב", "רכב", "משרד התחבורה", "רישוי מקצועי",
                               "ביטוח רכב", "תחבורה"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
