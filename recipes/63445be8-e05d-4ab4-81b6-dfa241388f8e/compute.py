"""רשימת מומחים לבתי משפט — family-court expert list of the welfare ministry's
assistance units (יחידות הסיוע).

One row per listing (~135): district(s) served, employing institute, expert
name, address, local authority, phones, profession, whether they give
opinions, fee text, free-text notes and languages. The whole list is
republished on each update, so the page is a snapshot.

Privacy: phones, addresses and the free-text notes (which carry private
e-mails) never reach the page. Notes feed only a fixed keyword tagging of
focus areas (counts). Experts are not named on the page — everything is
aggregated by profession, district, city, language, institute and fee.

Data quality handled here (all disclosed in the copy):
- rows without an expert name are broken continuations of a multi-line note
  in the previous row → excluded;
- an expert listed at several addresses counts once in expert-level views
  (name + profession), while the city view counts listings;
- profession typos are mapped; a listing with two professions counts under
  the first; unknown professions pass through;
- fee text is free-form: amounts are classified as an hourly/session rate or
  an opinion fee by the nearest keyword, else by size (under 1,000 → rate);
  a range counts at its midpoint.
"""
import math
import re

import pandas as pd

TOP_CITIES = 12
TOP_INST = 10
MIN_BOX = 3
MIN_PROF = 3
PROF_COLORS = ["#0068f5", "#0b3668", "#6c9fd8", "#3d70b0", "#b7d2f7", "#2658a0"]
OTHER_COLOR = "#6c757d"
OTHER_PROF = "תחומים אחרים"
LRI, PDI = "⁦", "⁩"
NATIONAL = "ארצי"
OTHER = "אחר"
UNKNOWN = "לא צוין"
PROF_FIX = {"פסיכלוגיה": "פסיכולוגיה", "פסיכאטריה": "פסיכיאטריה"}
CITY_FIX = {"תל אביב": "תל אביב-יפו", "פתח תקווה": "פתח תקוה", "קרית ביאליק": "קריית ביאליק"}
TOPICS = [
    ("מסוגלות הורית", r"מסוגלות|תפקוד הורי"),
    ("ניכור הורי וחידוש קשר", r"ניכור|סרבנות קשר|חידוש\S* קשר"),
    ("תיאום הורי", r"תיאום הורי|תאום הורי"),
    ("משמורת וזמני שהות", r"משמורת|זמני שהות|הסדרי שהות|אחריות הורית"),
    ("אימוץ", r"אימוץ"),
    ("אפוטרופסות וכשירות", r"אפוטרופסות|כשירות|כשרות משפטית|תומך החלטות|צוואות"),
    ("מסוכנות ואלימות", r"מסוכנות|אלימות"),
    ("פגיעה מינית והתעללות", r"מיני|התעללות|הזנחה"),
    ("אבחונים", r"אבחון|אבחונים|פסיכודיאגנוסט|פסיכודיאנוסט"),
    ("הדרכת הורים", r"הדרכ\S* הור"),
    ("טיפול זוגי ומשפחתי", r"זוגי|טיפול משפחתי|מטפל\S* משפחתי"),
    ("ילדים ונוער", r"ילד|נוער|מתבגר"),
]
OP_KW = ("חוות דעת", "לחוות", "חוות הדעת")
HR_KW = ("לשעה", "שעתי", "שעת", "לטיפול", "לפגישה")
NUM_RE = re.compile(r"\d{1,3}(?:[,.]\d{3})+|\d+")
RANGE_JOIN = re.compile(r"^\s*(?:-|–|ל|עד)\s*$")
OP_BUCKETS = [(0, 2000), (2000, 5000), (5000, 10000), (10000, 15000), (15000, None)]
K = 1000


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def ils(v):
    return f"{int(round(v)):,} ₪"


def _ranked(s):
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _split(s):
    return [t.strip() for t in re.split(r"[,،]", s) if t.strip()]


def _first_kw(text, kws):
    pos = [text.find(k) for k in kws if k in text]
    return min(pos) if pos else None


def parse_fee(s):
    """Return (rate, opinion) — first amount of each class, or None."""
    s = s.replace("״", '"')
    ms = [m for m in NUM_RE.finditer(s) if int(re.sub(r"[,.]", "", m.group())) >= 100]
    groups = []
    for m in ms:
        v = int(re.sub(r"[,.]", "", m.group()))
        if groups and RANGE_JOIN.match(s[groups[-1]["end"]:m.start()]):
            groups[-1]["vals"].append(v)
            groups[-1]["end"] = m.end()
        else:
            groups.append({"start": m.start(), "end": m.end(), "vals": [v]})
    rate = opinion = None
    for i, g in enumerate(groups):
        after = s[g["end"]:groups[i + 1]["start"] if i + 1 < len(groups) else len(s)]
        before = s[groups[i - 1]["end"] if i else 0:g["start"]]
        val = (min(g["vals"]) + max(g["vals"])) / 2
        # Keywords count only within the number's own clause (up to a comma/period).
        after = re.split(r"[,.;]", after, maxsplit=1)[0]
        before = re.split(r"[,.;]", before)[-1]
        kind = None
        for ctx in (after, before):
            po, ph = _first_kw(ctx, OP_KW), _first_kw(ctx, HR_KW)
            if po is None and ph is None:
                continue
            if po is None or ph is None:
                kind = "hr" if po is None else "op"
            elif ctx is after:
                kind = "op" if po < ph else "hr"
            else:
                kind = "op" if po > ph else "hr"
            break
        if kind is None:
            kind = "hr" if val < 1000 else "op"
        if kind == "hr" and rate is None:
            rate = val
        elif kind == "op" and opinion is None:
            opinion = val
    return rate, opinion


def _quant(vals, q):
    v = sorted(vals)
    if not v:
        return 0.0
    pos = (len(v) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def _median(vals):
    return _quant(vals, 0.5)


def _prepare(raw):
    df = pd.DataFrame({
        "expert": raw["expert"].str.strip().values,
        "district": raw["district"].str.strip().values,
        "employer": raw["employer"].str.strip().values,
        "authority": raw["authority"].str.strip().values,
        "profession": raw["profession"].str.strip().values,
        "opinion": raw["opinion"].str.strip().values,
        "payment": raw["payment"].str.strip().values,
        "notes": raw["notes"].str.strip().values,
        "languages": raw["languages"].str.strip().values,
    })
    n_broken = int((df["expert"] == "").sum())
    df = df[df["expert"] != ""].copy()
    profs = df["profession"].map(lambda s: [PROF_FIX.get(t, t) for t in _split(s)])
    df["prof"] = profs.map(lambda p: p[0] if p else UNKNOWN)
    df["multi_prof"] = profs.map(len) > 1
    df = df.sort_values(["expert", "prof", "authority", "district", "employer", "payment",
                         "languages", "notes", "opinion"], kind="stable").reset_index(drop=True)
    return df, n_broken


# ---------------------------------------------------------------- insights

def insight_prof(prof_counts, total):
    if len(prof_counts) < 2:
        return None
    a, b = prof_counts.index[0], prof_counts.index[1]
    va, vb = int(prof_counts.iloc[0]), int(prof_counts.iloc[1])
    if va == vb:
        return f"{a} ו{b} מובילות יחד ברשימה, עם {n(va)} מומחים כל אחת."
    rest = ""
    if len(prof_counts) > 2:
        c = prof_counts.index[2]
        rest = f" ו{c} ({n(prof_counts.iloc[2])})"
    return (f"{a} הוא התחום הגדול ברשימה — {n(va)} מתוך {n(total)} המומחים "
            f"({pct(va / total * 100)}), ואחריו {b} ({n(vb)}){rest}.")


def insight_national(n_nat, total, district_counts):
    if total == 0 or n_nat == 0:
        return None
    share = n_nat / total
    regional = district_counts[district_counts.index != NATIONAL]
    if regional.empty:
        return None
    top = regional.index[0]
    return (f"{n(n_nat)} מומחים ({pct(share * 100)}) רשומים כארציים וזמינים לכל המחוזות; "
            f"מבין המחוזות, {top} מובילה עם {n(regional.iloc[0])} מומחים שרשומים לה במפורש.")


def insight_thin(district_counts, n_nat):
    regional = district_counts[district_counts.index != NATIONAL]
    if len(regional) < 2:
        return None
    lo, hi = regional.index[-1], regional.index[0]
    vlo, vhi = int(regional.iloc[-1]), int(regional.iloc[0])
    if vlo * 2 > vhi:
        return None
    return (f"במחוז {lo} רשומים במפורש רק {n(vlo)} מומחים, לעומת {n(vhi)} ב{hi} — "
            f"מעבר ל-{n(n_nat)} הארציים, ההיצע הייעודי למחוז מצומצם.")


def insight_cities(city_counts, n_with_city):
    known = city_counts[city_counts.index != UNKNOWN]
    if len(known) < 3 or n_with_city == 0:
        return None
    a, b = known.index[0], known.index[1]
    top2 = int(known.iloc[0]) + int(known.iloc[1])
    share = top2 / n_with_city
    if share < 0.15:
        return None
    return (f"{a} ({n(known.iloc[0])}) ו{b} ({n(known.iloc[1])}) מרכזות {pct(share * 100)} "
            f"מהרישומים שבהם צוינה רשות; הרישומים פרושים על פני {n(len(known))} רשויות.")


def insight_langs(lang_counts, hebrew_only, total, arabic):
    if total == 0:
        return None
    other = total - hebrew_only
    if other / total < 0.05:
        return None
    ar = (f" ערבית מציעים {n(arabic)} מומחים בלבד." if 0 < arabic and arabic / total < 0.15
          else (" אין ברשימה מומחה שמציין ערבית." if arabic == 0 else ""))
    nonheb = [x for x in lang_counts.index if x not in ("עברית", UNKNOWN)]
    lead = f", בעיקר {nonheb[0]} ({n(lang_counts[nonheb[0]])})" if nonheb else ""
    return (f"{n(hebrew_only)} מהמומחים ({pct(hebrew_only / total * 100)}) מציינים עברית בלבד; "
            f"{n(other)} מציעים שפה נוספת או אחרת{lead}.{ar}")


def insight_rates(box_rows):
    rows = [r for r in box_rows if r["n"] >= MIN_BOX]
    if len(rows) < 2:
        return None
    hi = max(rows, key=lambda r: (r["med"], r["name"]))
    lo = min(rows, key=lambda r: (r["med"], r["name"]))
    if lo["med"] <= 0 or hi["med"] / lo["med"] < 1.1:
        return None
    return (f"התעריף החציוני לשעה או לפגישה גבוה ביותר ב{hi['name']} — {ils(hi['med'])} "
            f"({n(hi['n'])} מומחים שציינו תעריף), לעומת {ils(lo['med'])} ב{lo['name']} "
            f"({n(lo['n'])}).")


def insight_opinion(ops):
    if len(ops) < 5:
        return None
    p25, p75 = _quant(ops, 0.25), _quant(ops, 0.75)
    return (f"{n(len(ops))} מומחים ציינו מחיר לחוות דעת: החציון {ils(_median(ops))}, ומחצית "
            f"המחירים נעים בין {ils(p25)} ל-{ils(p75)} — הזול ביותר {ils(min(ops))} והיקר "
            f"ביותר {ils(max(ops))}.")


def insight_op_prof(op_rows):
    rows = [r for r in op_rows if r["n"] >= 5]
    if len(rows) < 2:
        return None
    hi = max(rows, key=lambda r: (r["med"], r["name"]))
    lo = min(rows, key=lambda r: (r["med"], r["name"]))
    if lo["med"] <= 0 or hi["med"] / lo["med"] < 1.15:
        return None
    return (f"המחיר החציוני לחוות דעת גבוה ביותר ב{hi['name']} — {ils(hi['med'])} "
            f"({n(hi['n'])} מומחים), ונמוך ביותר ב{lo['name']} — {ils(lo['med'])} ({n(lo['n'])}).")


def insight_inst(n_inst, total, inst_counts):
    if total == 0 or inst_counts.empty:
        return None
    share = n_inst / total
    top = inst_counts.index[0]
    if int(inst_counts.iloc[0]) < 2:
        return None
    return (f"{n(total - n_inst)} מהמומחים ({pct((1 - share) * 100)}) רשומים ללא מכון; "
            f"{n(n_inst)} פועלים דרך {n(len(inst_counts))} מכונים, הגדול שבהם {top} "
            f"({n(inst_counts.iloc[0])} מומחים).")


def insight_topics(topic_counts, n_tagged):
    if n_tagged < 10 or topic_counts.empty:
        return None
    a = topic_counts.index[0]
    va = int(topic_counts.iloc[0])
    if va / n_tagged < 0.2:
        return None
    second = ""
    if len(topic_counts) > 1 and topic_counts.iloc[1] > 0:
        second = f", ואחריו {topic_counts.index[1]} ({n(topic_counts.iloc[1])})"
    return (f"התחום הנזכר הכי הרבה בתיאורי המומחים הוא {a} — {n(va)} מתוך {n(n_tagged)} "
            f"שתיאורם מזכיר תחום מוכר{second}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df, n_broken = _prepare(frames["experts"])
    n_listings = len(df)
    ex = df.drop_duplicates(["expert", "prof"], keep="first").reset_index(drop=True)
    total = len(ex)

    # professions
    raw_counts = _ranked(ex["prof"].value_counts())
    small = [p for p, v in raw_counts.items() if v < MIN_PROF or p == UNKNOWN]
    if len(small) == 1 and small[0] != UNKNOWN:
        small = []
    small_set = set(small)
    n_fields = int(sum(1 for p in raw_counts.index if p != UNKNOWN))
    for frame in (df, ex):
        frame["prof"] = frame["prof"].map(lambda p: OTHER_PROF if p in small_set else p)
    prof_counts = _ranked(ex["prof"].value_counts())
    profs = [p for p in prof_counts.index if p != OTHER_PROF] + \
        ([OTHER_PROF] if OTHER_PROF in prof_counts.index else [])
    prof_counts = prof_counts[profs]
    color = {p: (OTHER_COLOR if p == OTHER_PROF else PROF_COLORS[i % len(PROF_COLORS)])
             for i, p in enumerate(profs)}
    n_multi_prof = int(ex["multi_prof"].sum())

    # districts — expert-level union of the districts in all their listings
    dist_sets = {}
    for key, s in zip(zip(df["expert"], df["prof"]), df["district"]):
        dist_sets.setdefault(key, set()).update(_split(s))
    ex["dists"] = [frozenset(dist_sets.get((e, p), ())) for e, p in zip(ex["expert"], ex["prof"])]
    ex["national"] = ex["dists"].map(lambda d: NATIONAL in d)
    n_nat = int(ex["national"].sum())
    drows = []
    for prof, ds, nat in zip(ex["prof"], ex["dists"], ex["national"]):
        if nat:
            drows.append((NATIONAL, prof))
        elif not ds:
            drows.append((UNKNOWN, prof))
        else:
            drows.extend((d, prof) for d in ds)
    dd = pd.DataFrame(drows, columns=["d", "p"])
    district_counts = _ranked(dd["d"].value_counts())
    regional = [d for d in district_counts.index if d not in (NATIONAL, UNKNOWN)]
    dorder = [NATIONAL] * (NATIONAL in district_counts.index) + regional + \
        [UNKNOWN] * (UNKNOWN in district_counts.index)
    dx = dd.groupby(["d", "p"]).size()

    # cities (listings)
    cities = []
    for s in df["authority"]:
        toks = [CITY_FIX.get(t, t) for t in _split(s)] or [UNKNOWN]
        cities.extend(toks)
    cdf = pd.DataFrame({"c": cities})
    city_counts = _ranked(cdf["c"].value_counts())
    known_cities = [c for c in city_counts.index if c != UNKNOWN]
    n_unknown_city = int((df["authority"] == "").sum())
    n_with_city = n_listings - n_unknown_city
    top_c = known_cities[:TOP_CITIES]
    rest_c = known_cities[TOP_CITIES:]
    city_prof = []
    for s, p in zip(df["authority"], df["prof"]):
        for t in [CITY_FIX.get(t, t) for t in _split(s)]:
            city_prof.append((t if t in top_c else OTHER, p))
    cp = pd.DataFrame(city_prof, columns=["c", "p"]).groupby(["c", "p"]).size()
    c_names = top_c + ([OTHER] if rest_c else [])

    # languages
    lang_lists = ex["languages"].map(lambda s: [t for t in _split(s) if re.fullmatch(r"[א-ת]+ית", t)])
    lang_counts = _ranked(pd.Series([t for ls in lang_lists for t in ls], dtype=str).value_counts())
    n_no_lang = int(sum(1 for ls in lang_lists if not ls))
    if n_no_lang:
        lang_counts = pd.concat([lang_counts, pd.Series({UNKNOWN: n_no_lang})])
    hebrew_only = int(sum(1 for ls in lang_lists if ls == ["עברית"]))
    arabic = int(sum(1 for ls in lang_lists if "ערבית" in ls))
    n_multi_lang = int(sum(1 for ls in lang_lists if len(ls) >= 2))

    # institutes
    inst = ex["employer"]
    inst_valid = inst[(inst != "") & ~inst.str.fullmatch(r"[א-ת]+ית")]
    inst_counts = _ranked(inst_valid.value_counts())
    n_inst = int(len(inst_valid))
    top_i = list(inst_counts.index[:TOP_INST])
    rest_i = int(inst_counts.iloc[TOP_INST:].sum())

    # fees
    fees = ex["payment"].map(parse_fee)
    ex["rate"] = fees.map(lambda f: f[0])
    ex["op"] = fees.map(lambda f: f[1])
    n_fee_text = int((ex["payment"] != "").sum())
    n_parsed = int(sum(1 for r, o in fees if r is not None or o is not None))
    rates = [float(v) for v in ex["rate"] if v is not None and not pd.isna(v)]
    ops = [float(v) for v in ex["op"] if v is not None and not pd.isna(v)]
    box_rows = []
    for p in profs:
        v = sorted(float(x) for x in ex.loc[ex["prof"] == p, "rate"] if x is not None and not pd.isna(x))
        if not v:
            continue
        box_rows.append({"name": p, "n": len(v), "min": v[0], "q1": _quant(v, .25), "med": _median(v),
                         "q3": _quant(v, .75), "max": v[-1]})
    op_rows = []
    for p in profs:
        v = sorted(float(x) for x in ex.loc[ex["prof"] == p, "op"] if x is not None and not pd.isna(x))
        if v:
            op_rows.append({"name": p, "n": len(v), "med": _median(v)})
    box_shown = [r for r in box_rows if r["n"] >= MIN_BOX]
    for r in box_rows:
        v = sorted(float(x) for x in ex.loc[ex["prof"] == r["name"], "rate"] if x is not None and not pd.isna(x))
        iqr = r["q3"] - r["q1"]
        lo_f, hi_f = r["q1"] - 1.5 * iqr, r["q3"] + 1.5 * iqr
        inside = [x for x in v if lo_f <= x <= hi_f]
        r["wlo"], r["whi"] = inside[0], inside[-1]
        r["out"] = [x for x in v if x < lo_f or x > hi_f]
    box_hidden = [r for r in box_rows if r["n"] < MIN_BOX]
    op_labels = []
    for lo, hi in OP_BUCKETS:
        if lo == 0:
            op_labels.append(f"עד {hi // K} אלף")
        elif hi is None:
            op_labels.append(f"{lo // K} אלף ומעלה")
        else:
            op_labels.append(f"{lo // K} עד {hi // K} אלף")

    def _bucket(v):
        for i, (lo, hi) in enumerate(OP_BUCKETS):
            if v >= lo and (hi is None or v < hi):
                return i
        return len(OP_BUCKETS) - 1
    op_df = pd.DataFrame({"b": [_bucket(v) for v in ex["op"] if v is not None and not pd.isna(v)],
                          "p": [p for p, v in zip(ex["prof"], ex["op"]) if v is not None and not pd.isna(v)]})
    op_x = op_df.groupby(["b", "p"]).size() if len(op_df) else pd.Series(dtype=int)
    op_profs = [p for p in profs if len(op_df) and (op_df["p"] == p).any()]

    # topics from notes (keyword tagging; the notes themselves never reach the page)
    tag_rows = []
    for prof, note in zip(ex["prof"], ex["notes"]):
        hit = [name for name, rx in TOPICS if re.search(rx, note)]
        tag_rows.append((prof, hit))
    n_tagged = sum(1 for _, h in tag_rows if h)
    tflat = pd.DataFrame([(t, p) for p, h in tag_rows for t in h], columns=["t", "p"])
    topic_counts = _ranked(tflat["t"].value_counts()) if len(tflat) else pd.Series(dtype=int)
    tx = tflat.groupby(["t", "p"]).size() if len(tflat) else pd.Series(dtype=int)
    t_names = list(topic_counts.index)
    t_profs = [p for p in profs if len(tflat) and (tflat["p"] == p).any()]

    n_opinion = int((ex["opinion"] == "כן").sum())

    def stack(index_names, profs_list, series_lookup):
        return [{"name": p, "color": color[p],
                 "data": [int(series_lookup.get((k, p), 0)) for k in index_names]} for p in profs_list]

    charts = {
        "prof": {"names": profs, "values": [int(v) for v in prof_counts.values],
                 "colors": [color[p] for p in profs]},
        "districts": {"x": dorder, "series": stack(dorder, profs, dx)},
        "cities": {"names": c_names, "series": stack(c_names, profs, cp)},
        "topics": {"names": t_names, "series": stack(t_names, t_profs, tx)},
        "rates": {"names": [r["name"] for r in box_shown],
                  "boxes": [[r["wlo"], r["q1"], r["med"], r["q3"], r["whi"]] for r in box_shown],
                  "outliers": [[i, x] for i, r in enumerate(box_shown) for x in r["out"]]},
        "opinion": {"x": op_labels,
                    "series": [{"name": p, "color": color[p],
                                "data": [int(op_x.get((i, p), 0)) for i in range(len(OP_BUCKETS))]}
                               for p in op_profs]},
        "langs": {"names": list(lang_counts.index), "values": [int(v) for v in lang_counts.values]},
        "inst": {"names": top_i + (["מכונים אחרים"] if rest_i else []),
                 "values": [int(inst_counts[i]) for i in top_i] + ([rest_i] if rest_i else [])},
    }

    rules = [
        ("prof", insight_prof(prof_counts, total)),
        ("national", insight_national(n_nat, total, district_counts)),
        ("thin", insight_thin(district_counts[[d for d in district_counts.index if d != UNKNOWN]], n_nat)),
        ("cities", insight_cities(city_counts, n_with_city)),
        ("langs", insight_langs(lang_counts, hebrew_only, total, arabic)),
        ("rates", insight_rates(box_rows)),
        ("opinion", insight_opinion(ops)),
        ("op_prof", insight_op_prof(op_rows)),
        ("inst", insight_inst(n_inst, total, inst_counts)),
        ("topics", insight_topics(topic_counts, n_tagged)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    med_rate = _median(rates) if rates else 0
    med_op = _median(ops) if ops else 0
    nat_share = n_nat / total if total else 0
    kpis = {
        "experts": {"value": total, "display": n(total), "tone": "brand"},
        "national": {"value": round(nat_share * 100, 1), "display": f"{nat_share * 100:.0f}%",
                     "tone": "info"},
        "rate": {"value": med_rate, "display": n(round(med_rate)), "tone": "brand"},
        "opinion": {"value": med_op, "display": n(round(med_op)), "tone": "brand"},
    }

    dup_listings = n_listings - total
    excl = []
    if n_broken:
        excl.append("שורה אחת ללא שם מומחה (המשך שבור של שורה קודמת) הושמטה" if n_broken == 1 else
                    f"{n(n_broken)} שורות ללא שם מומחה (המשך שבור של שורה קודמת) הושמטו")
    if dup_listings:
        excl.append(f"מומחה הרשום בכמה כתובות נספר פעם אחת ({n(dup_listings)} רישומים כפולים)")
    excl_txt = ("; ".join(excl) + ".") if excl else ""
    opinion_txt = (f" כל המומחים ברשימה מסומנים כנותני חוות דעת." if n_opinion == total
                   else f" {n(n_opinion)} מהם מסומנים כנותני חוות דעת.")
    labels = {
        "lede": (f"רשימת המומחים שיחידות הסיוע של משרד הרווחה מעמידות לרשות בתי המשפט לענייני משפחה: "
                 f"{n(total)} מומחים ב-{n(n_fields)} תחומים, ב-{n(n_listings)} רישומים."
                 f"{opinion_txt} העמוד מציג את התמונה המצרפית — תחום, מחוז, רשות, שפה, מכון ושכר "
                 f"טרחה; פרטי הקשר של כל מומחה מופיעים בטבלת הנתונים שבתחתית העמוד. {excl_txt}"),
        "experts_kpi": "מומחים ברשימה",
        "national_kpi": "מהמומחים רשומים כארציים",
        "rate_kpi": f"תעריף חציוני לשעה או לפגישה (₪, {n(len(rates))} מומחים)",
        "opinion_kpi": f"מחיר חציוני לחוות דעת (₪, {n(len(ops))} מומחים)",
        "prof_note": ("מספר המומחים בכל תחום מקצועי."
                      + (f" {OTHER_PROF} ({', '.join(small)}) מקובצים יחד, כאן ובכל התרשימים." if small else "")
                      + ((" מומחה אחד שציין שני תחומים נספר לפי הראשון." if n_multi_prof == 1 else
                         f" {n(n_multi_prof)} מומחים שציינו שני תחומים נספרים לפי הראשון.") if n_multi_prof else "")),
        "prof_aria": (f"תרשים טבעת: מומחים לפי תחום — {profs[0]} בראש עם {n(prof_counts.iloc[0])} "
                      f"מתוך {n(total)}." if profs else "תרשים טבעת: מומחים לפי תחום."),
        "prof_caption": "מספר המומחים לפי תחום מקצועי.",
        "districts_note": (f"מספר המומחים הרשומים לכל מחוז, לפי תחום. {n(n_nat)} המומחים הארציים מוצגים בעמודה "
                           f"נפרדת וזמינים בכל המחוזות; מומחה הרשום בכמה מחוזות נספר בכל אחד מהם."),
        "districts_aria": (f"גרף עמודות אופקיות מוערמות: מומחים לפי מחוז ותחום — {n(n_nat)} ארציים, "
                           f"והמחוז המוביל {regional[0]}." if regional else "גרף עמודות אופקיות מוערמות: מומחים לפי מחוז."),
        "districts_caption": "מספר המומחים לפי מחוז ותחום.",
        "cities_note": (f"{len(top_c)} הרשויות עם הכי הרבה רישומים, לפי תחום (כל כתובת נספרת)"
                        + (f"; {n(len(rest_c))} רשויות נוספות מקובצות ב\"אחר\"" if rest_c else "")
                        + (f". ב-{n(n_unknown_city)} רישומים לא צוינה רשות והם אינם בתרשים." if n_unknown_city else ".")),
        "cities_aria": (f"תרשים עמודות אופקי: רישומים לפי רשות — {top_c[0]} בראש עם "
                        f"{n(city_counts[top_c[0]])}." if top_c else "תרשים עמודות אופקי: רישומים לפי רשות."),
        "cities_caption": "מספר הרישומים לפי רשות ותחום.",
        "topics_note": (f"כמה מומחים מזכירים כל תחום עיסוק בתיאור החופשי שלהם, לפי מילות מפתח "
                        f"({n(n_tagged)} מתוך {n(total)} תיאורים מזכירים תחום אחד לפחות; מומחה יכול להופיע בכמה תחומים)."),
        "topics_aria": (f"תרשים עמודות אופקי: תחומי עיסוק — {t_names[0]} בראש עם {n(topic_counts.iloc[0])} "
                        f"מומחים." if t_names else "תרשים עמודות אופקי: תחומי עיסוק."),
        "topics_caption": "מספר המומחים המזכירים כל תחום עיסוק, לפי תחום מקצועי.",
        "rates_note": (f"פיזור התעריף לשעה או לפגישה בכל תחום ({n(len(rates))} מומחים שציינו תעריף): "
                       f"הקופסה מסמנת את המחצית האמצעית והקו את החציון, בסולם לוגריתמי. סכומים בטקסט החופשי סווגו לפי "
                       f"המילה הסמוכה (\"לשעה\", \"לחוות דעת\"), ובהיעדרה לפי גודל — "
                       f"סכום מתחת ל-{n(1000)} ₪ נחשב תעריף; טווח נספר לפי אמצעו. נקודות מסמנות ערכים חריגים."
                       + (f" תחומים עם פחות מ-{MIN_BOX} תעריפים אינם מוצגים." if box_hidden else "")),
        "rates_aria": (f"תרשים קופסה בסולם לוגריתמי: תעריף לשעה לפי תחום, חציון כללי {ils(med_rate)}."),
        "rates_caption": "תעריף לשעה או לפגישה לפי תחום (₪).",
        "opinion_note": (f"מחיר חוות דעת שציינו {n(len(ops))} מומחים, לפי טווח מחיר ותחום (אלפי ₪; כל טווח "
                         f"כולל את גבולו התחתון בלבד). טווח מחירים שציין מומחה נספר לפי אמצעו."),
        "opinion_aria": (f"גרף עמודות אופקיות מוערמות: מחיר חוות דעת לפי טווח ותחום, חציון {ils(med_op)}."),
        "opinion_caption": "מספר המומחים לפי טווח מחיר חוות דעת ותחום.",
        "langs_note": (f"מספר המומחים המציינים כל שפה ({n(n_multi_lang)} מציינים שתי שפות או יותר)."),
        "langs_aria": (f"תרשים עמודות אופקי: מומחים לפי שפה — {lang_counts.index[0]} בראש עם "
                       f"{n(lang_counts.iloc[0])}."),
        "langs_caption": "מספר המומחים לפי שפה.",
        "inst_note": (f"{n(n_inst)} מומחים פועלים דרך מכון או מרכז; {n(total - n_inst)} רשומים ללא מכון."
                      + (f" מוצגים {len(top_i)} המכונים הגדולים." if rest_i else "")),
        "inst_aria": (f"תרשים עמודות אופקי: מומחים לפי מכון — {top_i[0]} בראש עם "
                      f"{n(inst_counts.iloc[0])}." if top_i else "תרשים עמודות אופקי: מומחים לפי מכון."),
        "inst_caption": "מספר המומחים לפי מכון.",
    }

    tables = {
        "prof": [{"name": p, "count": n(v), "share": f"{v / total * 100:.1f}%"}
                 for p, v in prof_counts.items()],
        "prof_cols": profs,
        "districts": [{"name": d, "vals": [n(dx.get((d, p), 0)) for p in profs],
                       "total": n(sum(int(dx.get((d, p), 0)) for p in profs))} for d in dorder],
        "cities": [{"name": c, "vals": [n(cp.get((c, p), 0)) for p in profs],
                    "total": n(sum(int(cp.get((c, p), 0)) for p in profs))} for c in c_names],
        "topics": [{"name": t, "count": n(topic_counts[t]),
                    "share": f"{topic_counts[t] / n_tagged * 100:.0f}%"} for t in t_names],
        "rates": [{"name": r["name"], "n": n(r["n"]), "min": n(r["min"]), "med": n(round(r["med"])),
                   "max": n(r["max"])} for r in box_rows],
        "opinion": [{"name": lab, "count": n(sum(int(op_x.get((i, p), 0)) for p in op_profs))}
                    for i, lab in enumerate(op_labels)],
        "langs": [{"name": k, "count": n(v)} for k, v in lang_counts.items()],
        "inst": [{"name": k, "count": n(v)} for k, v in zip(charts["inst"]["names"], charts["inst"]["values"])],
    }

    return {
        "agent_data": {
            "summary_he": (f"רשימת {n(total)} המומחים שיחידות הסיוע מעמידות לבתי המשפט לענייני משפחה — "
                           f"לפי תחום ({', '.join(profs[:3])}), מחוז, רשות, שפה ושכר טרחה."),
            "dataset_kind": "registry",
            "related_ids": ["409c1d81-feea-4729-b37d-796fba3f8658",
                            "edb5f516-28b1-439e-828a-43ec3a3cc82f",
                            "4f361ce6-f30f-4629-b4ba-1ad19039e745",
                            "12ac3fa6-ac57-41d6-8519-17a3435754a7",
                            "e941665c-53df-48b0-8a1f-e5ae719cf695"],
            "suggested_tags": ["מומחים לבתי משפט", "סכסוך משפחתי", "גירושין", "חוות דעת",
                               "יחידות סיוע"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"rates": len(box_shown) > 0, "opinion": len(ops) > 0, "topics": len(t_names) > 0,
                  "inst": len(top_i) > 0, "cities": len(top_c) > 0},
    }
