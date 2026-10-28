"""רשימת רחובות בישראל עם סינונימים — the Population and Immigration Authority's
street list including the unofficial alternative names (synonyms).

One row per registered street NAME. `street_name_status` is either `official` or
`synonym of <code>`; a synonym row carries the official street's code in
`official_code`, and both live under the same locality code.

Street code 9000 is not a street: every locality has one official row with code
9000 named after the locality itself (the address used where it has no streets).
Synonyms of 9000 are alternative names of the LOCALITY, so they are counted
apart from street synonyms. "Official streets" excludes 9000.

`region_name` is the registry's region (named after its main city; the codes
71-77 are the registry's regions beyond the Green Line, shown under their
registry names). The list is republished whole on each update, so the page is a
snapshot of the current list. The dataset also keeps ten older monthly snapshots
(2016-2020) as separate resources; they are earlier versions of this same table,
not distinct tables, and are not read.

How a synonym differs from its official name is a heuristic comparison of the
two spellings (punctuation, spelling letters, leading ה, street-type words, word
order, shortened/extended forms); the page says so.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
PLACEHOLDER = 9000
TOP_LOCS = 20
TOP_REGIONS = 20
TOP_STREETS = 15
TOP_ALT = 15
RATIO_MIN_STREETS = 100   # localities with fewer official streets have too-noisy ratios
RATIO_EACH_SIDE = 10
SCATTER_MIN_NAMES = 20
SCATTER_MAX_POINTS = 500
KIND_MIN = 1000           # minimum synonyms for the kind insight to run

SYN_BUCKETS = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 9), (10, None)]

TYPE_WORDS = {
    "רח", "רחוב", "שד", "שדרות", "שדרת", "סמ", "סמטת", "סמטה", "שכ", "שכונת", "ש",
    "שיכון", "שכון", "דרך", "כיכר", "ככר", "מעלה", "מבוא", "משעול", "שביל", "רחבת",
    "טיילת", "קרית", "קריית", "אזור",
}
_PUNCT = re.compile(r"[\"'׳״.,\-־()]")
_SPELL = re.compile(r"[אויה]")

KIND_ORDER = ["punct", "spelling", "order", "subset", "overlap", "different"]
KIND_SHORT = {
    "punct": "מקף, גרש, רווח",
    "spelling": "כתיב שונה",
    "order": "סדר מילים",
    "subset": "מקוצר או מורחב",
    "overlap": "חפיפה חלקית",
    "different": "שם שונה לגמרי",
}
KIND_LABEL = {
    "punct": "הבדל במקף, גרש או רווח בלבד",
    "spelling": "כתיב שונה (אותיות א/ו/י/ה, ה׳ הידיעה, סוג רחוב)",
    "order": "אותן מילים בסדר אחר",
    "subset": "שם מקוצר או מורחב (תואר, שם פרטי)",
    "overlap": "חפיפה חלקית בין המילים",
    "different": "שם שונה לגמרי",
}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def share(a, b, digits=1):
    return pct(a / b * 100, digits) if b else pct(0, digits)


def ratio(a, b):
    return f"{a / b:.2f}" if b else "0.00"


_FLIP = str.maketrans("()", ")(")


def _clean(s):
    """Collapse whitespace; the registry stores some parentheses mirrored."""
    s = re.sub(r"\s+", " ", str(s)).strip()
    m = re.search(r"[()]", s)
    if m and m.group(0) == ")":
        s = s.translate(_FLIP)
    return s


def _ranked(s):
    """Sorted descending, ties broken by label."""
    return s.sort_index().sort_values(ascending=False, kind="stable")


def _words(s):
    return [w for w in _PUNCT.sub(" ", s).split() if w]


def _core(s):
    w = [x for x in _words(s) if x not in TYPE_WORDS]
    return [x[1:] if x.startswith("ה") and len(x) > 2 else x for x in w]


def _kind(syn, off):
    """How a synonym's spelling differs from the official name."""
    if "".join(_words(syn)) == "".join(_words(off)):
        return "punct"
    ca, co = _core(syn), _core(off)
    if _SPELL.sub("", "".join(ca)) == _SPELL.sub("", "".join(co)):
        return "spelling"
    if sorted(ca) == sorted(co):
        return "order"
    sa, so = set(ca), set(co)
    if sa < so or so < sa:
        return "subset"
    if sa & so:
        return "overlap"
    return "different"


# ---------------------------------------------------------------- insights

def insight_volume(n_rows, n_syn, n_off, n_streets_syn):
    if n_off == 0 or n_streets_syn == 0:
        return None
    return (f"לצד {n(n_off)} רחובות רשמיים רשומים {n(n_streets_syn)} שמות חלופיים (סינונימים) — "
            f"{share(n_streets_syn, n_streets_syn + n_off)} מכל שמות הרחובות, כלומר "
            f"{LRI}{n_streets_syn / n_off:.2f}{PDI} שמות חלופיים לכל רחוב רשמי.")


def insight_coverage(n_off, with_syn, max_row):
    if n_off == 0 or with_syn == 0:
        return None
    a = max_row
    tail = ""
    if a and a["count"] >= 5:
        tail = f" לרחוב {a['name']} ב{a['loc']} יש {n(a['count'])} שמות חלופיים, הכי הרבה ברשימה."
    return (f"{n(with_syn)} רחובות רשמיים ({share(with_syn, n_off)}) רשומים עם שם חלופי אחד לפחות; "
            f"בשאר אין שם חלופי.{tail}")


def insight_concentration(rows, n_names):
    if len(rows) < 10 or not n_names:
        return None
    a, b = rows[0], rows[1]
    if a["total"] <= b["total"]:
        return None
    s5 = sum(r["total"] for r in rows[:5])
    return (f"{a['name']} מובילה עם {n(a['total'])} שמות רחובות רשומים (רשמיים וחלופיים), "
            f"פי {LRI}{a['total'] / b['total']:.1f}{PDI} מ{b['name']}. חמשת הישובים הגדולים מרכזים "
            f"{share(s5, n_names)} מכלל שמות הרחובות.")


def insight_ratio_spread(rows):
    """rows: eligible localities sorted by ratio descending."""
    if len(rows) < 10:
        return None
    hi, lo = rows[0], rows[-1]
    if hi["ratio_v"] < lo["ratio_v"] * 1.5 or hi["ratio_v"] - lo["ratio_v"] < 0.5:
        return None
    low = (f"ב{lo['name']} רק {lo['ratio']}" if lo["ratio_v"] > 0
           else f"ב{lo['name']} אין שם חלופי כלל")
    return (f"בישובים עם {n(RATIO_MIN_STREETS)} רחובות רשמיים ומעלה, הפער גדול: ב{hi['name']} "
            f"{hi['ratio']} שמות חלופיים לכל רחוב רשמי, {low}.")


def insight_no_syn(zero, n_locs, zero_max_streets):
    if zero == 0 or not n_locs:
        return None
    return (f"{n(zero)} ישובים ({share(zero, n_locs)}) רשומים בלי אף שם חלופי לרחוב. "
            f"הגדול שבהם כולל {n(zero_max_streets)} רחובות רשמיים.")


def insight_kinds(kind_rows, n_syn):
    if n_syn < KIND_MIN:
        return None
    by = {r["key"]: r for r in kind_rows}
    light = by["punct"]["count"] + by["spelling"]["count"]
    diff = by["different"]["count"]
    return (f"{share(light, n_syn)} מהשמות החלופיים הם וריאציית כתיב של השם הרשמי (מקף, גרש, אותיות, ה׳ הידיעה "
            f"או סוג הרחוב), ו-{share(diff, n_syn)} ({n(diff)}) אינם חולקים עם השם הרשמי אף מילה, לפי "
            f"השוואה אוטומטית.")


def insight_region(rows):
    """rows: regions with at least RATIO_MIN_STREETS official streets, ratio-sorted desc."""
    if len(rows) < 4:
        return None
    hi, lo = rows[0], rows[-1]
    if lo["ratio_v"] <= 0 or hi["ratio_v"] < lo["ratio_v"] * 1.3:
        return None
    return (f"לפי אזורי הרישום, אזור {hi['name']} מוביל ב-{hi['ratio']} שמות חלופיים לכל רחוב רשמי, "
            f"לעומת {lo['ratio']} באזור {lo['name']}.")


def insight_alt_loc(n_alt, n_alt_locs, n_locs, top):
    if n_alt == 0 or not top:
        return None
    return (f"גם לישובים עצמם יש שמות חלופיים: {n(n_alt)} שמות ב-{n(n_alt_locs)} ישובים "
            f"({share(n_alt_locs, n_locs)} מהישובים). הכי הרבה ב{top[0]['name']} ({n(top[0]['count'])}).")


# ---------------------------------------------------------------- compute

def compute(frames):
    raw = frames["main"]
    status = raw["street_name_status"].str.strip().str.lower()
    df = pd.DataFrame({
        "region": pd.to_numeric(raw["region_code"].str.strip(), errors="coerce").values,
        "region_name": raw["region_name"].map(_clean).values,
        "city": pd.to_numeric(raw["city_code"].str.strip(), errors="coerce").values,
        "city_name": raw["city_name"].map(_clean).values,
        "code": pd.to_numeric(raw["street_code"].str.strip(), errors="coerce").values,
        "name": raw["street_name"].map(_clean).values,
        "official": pd.to_numeric(raw["official_code"].str.strip(), errors="coerce").values,
        "syn": status.str.startswith("synonym").values,
        "is_off": (status == "official").values,
    })
    df = df[df["city"].notna() & df["code"].notna() & (df["is_off"] | df["syn"])].copy()
    df["city"] = df["city"].astype(int)
    df["code"] = df["code"].astype(int)
    df = df.sort_values(["city", "code", "name"], kind="stable").drop_duplicates(["city", "code"])
    df["region"] = df["region"].fillna(-1).astype(int)
    df["official"] = df["official"].fillna(-1).astype(int)

    # Locality names (the placeholder row carries the locality's own name) and regions.
    city_name = (df.sort_values(["city", "is_off", "code"], ascending=[True, False, True], kind="stable")
                 .drop_duplicates("city").set_index("city")["city_name"])
    city_region = df.drop_duplicates("city").set_index("city")["region"]
    reg_name = (df.sort_values(["region", "region_name"], kind="stable")
                .drop_duplicates("region").set_index("region")["region_name"])
    cities = sorted(df["city"].unique())
    n_locs = len(cities)
    n_regions = int(df["region"].nunique())
    n_rows = len(df)

    ph = df["official"] == PLACEHOLDER
    off = df[df["is_off"] & (df["code"] != PLACEHOLDER) & (df["name"] != "")].copy()
    syn = df[df["syn"] & ~ph & (df["name"] != "")].copy()
    alt = df[df["syn"] & ph & (df["name"] != "")].copy()
    n_off, n_syn, n_alt = len(off), len(syn), len(alt)
    n_names = n_off + n_syn

    # Link each street synonym to its official street (same locality).
    off_name = {(c, k): nm for c, k, nm in zip(off["city"], off["code"], off["name"])}
    syn["off_name"] = [off_name.get((c, o)) for c, o in zip(syn["city"], syn["official"])]
    linked = syn[syn["off_name"].notna()].copy()

    # ---- per locality
    o_c = off.groupby("city").size().reindex(cities, fill_value=0)
    s_c = syn.groupby("city").size().reindex(cities, fill_value=0)
    loc_df = pd.DataFrame({"off": o_c, "syn": s_c})
    loc_df["total"] = loc_df["off"] + loc_df["syn"]
    loc_df["name"] = [city_name[c] for c in loc_df.index]
    loc_df["code"] = loc_df.index
    loc_rows = sorted(loc_df.to_dict("records"), key=lambda r: (-r["total"], r["name"], r["code"]))
    top_rows = [{"name": r["name"], "off": int(r["off"]), "syn": int(r["syn"]), "total": int(r["total"]),
                 "ratio": ratio(r["syn"], r["off"])} for r in loc_rows[:TOP_LOCS]]
    top_chart = {"names": [r["name"] for r in top_rows], "official": [r["off"] for r in top_rows],
                 "synonym": [r["syn"] for r in top_rows]}

    # ---- ratio extremes among larger localities
    elig = [r for r in loc_rows if r["off"] >= RATIO_MIN_STREETS]
    elig_rows = [{"name": r["name"], "code": int(r["code"]), "off": int(r["off"]), "syn": int(r["syn"]),
                  "ratio_v": r["syn"] / r["off"], "ratio": ratio(r["syn"], r["off"])} for r in elig]
    elig_rows.sort(key=lambda r: (-r["ratio_v"], r["name"], r["code"]))
    if len(elig_rows) >= 2 * RATIO_EACH_SIDE:
        hi_rows = elig_rows[:RATIO_EACH_SIDE]
        lo_rows = elig_rows[-RATIO_EACH_SIDE:]
        ratio_rows = hi_rows + lo_rows
        group = ["high"] * len(hi_rows) + ["low"] * len(lo_rows)
    else:
        ratio_rows = elig_rows
        hi_rows, lo_rows = elig_rows, []
        group = ["high"] * len(ratio_rows)
    ratio_chart = {"names": [r["name"] for r in ratio_rows],
                   "values": [round(r["ratio_v"], 2) for r in ratio_rows], "group": group,
                   "off": [r["off"] for r in ratio_rows], "syn": [r["syn"] for r in ratio_rows]}
    ratio_table = [{"name": r["name"], "off": r["off"], "syn": r["syn"], "ratio": r["ratio"],
                    "group": ("הגבוהים" if g == "high" else "הנמוכים")}
                   for r, g in zip(ratio_rows, group)]

    # ---- scatter (cap points; raise the floor as the list grows)
    floor = SCATTER_MIN_NAMES
    pts = [r for r in loc_rows if r["total"] >= floor]
    if len(pts) > SCATTER_MAX_POINTS:
        pts = pts[:SCATTER_MAX_POINTS]
        floor = int(pts[-1]["total"])
    scatter = {"points": [[int(r["off"]), int(r["syn"]), r["name"]] for r in pts]}
    scatter_n = len(pts)

    # ---- no-synonym localities
    zero_locs = loc_df[loc_df["syn"] == 0]
    zero = len(zero_locs)
    zero_max = int(zero_locs["off"].max()) if zero else 0

    # ---- synonyms per official street
    per_street = syn.groupby(["city", "official"]).size()
    sc = off[["city", "code", "name"]].copy()
    sc["k"] = [int(per_street.get((c, k), 0)) for c, k in zip(sc["city"], sc["code"])]
    with_syn = int((sc["k"] > 0).sum())
    bucket_rows = []
    for lo, hi in SYN_BUCKETS:
        m = (sc["k"] >= lo) if hi is None else ((sc["k"] >= lo) & (sc["k"] <= hi))
        label = f"{n(lo)} ומעלה" if hi is None else (n(lo) if lo == hi else f"{n(lo)} עד {n(hi)}")
        bucket_rows.append({"name": label, "count": int(m.sum()), "share": share(int(m.sum()), n_off)})
    dist_chart = {"names": [r["name"] for r in bucket_rows], "values": [r["count"] for r in bucket_rows]}

    # ---- streets with most synonyms
    top_st = sc.assign(loc=[city_name[c] for c in sc["city"]]).sort_values(
        ["k", "loc", "name", "code"], ascending=[False, True, True, True], kind="stable").head(TOP_STREETS)
    street_rows = [{"name": r["name"], "loc": r["loc"], "count": int(r["k"])} for r in top_st.to_dict("records")]
    street_chart = {"labels": [f"{r['name']} · {r['loc']}" for r in street_rows],
                    "values": [r["count"] for r in street_rows]}
    max_row = street_rows[0] if street_rows else None

    # ---- regions
    reg = pd.DataFrame({
        "off": off.groupby("region").size(), "syn": syn.groupby("region").size(),
    }).fillna(0).astype(int)
    reg["locs"] = df.groupby("region")["city"].nunique()
    reg["name"] = [reg_name[r] for r in reg.index]
    reg["code"] = reg.index
    reg["total"] = reg["off"] + reg["syn"]
    reg_all = sorted(reg.to_dict("records"), key=lambda r: (-r["total"], r["name"], r["code"]))
    shown, rest = reg_all[:TOP_REGIONS], reg_all[TOP_REGIONS:]
    region_rows = [{"name": r["name"], "off": int(r["off"]), "syn": int(r["syn"]), "locs": int(r["locs"]),
                    "ratio": ratio(r["syn"], r["off"])} for r in shown]
    if rest:
        ro, rs = sum(int(r["off"]) for r in rest), sum(int(r["syn"]) for r in rest)
        region_rows.append({"name": f"אחרים ({n(len(rest))} אזורים)", "off": ro, "syn": rs,
                            "locs": sum(int(r["locs"]) for r in rest), "ratio": ratio(rs, ro)})
    region_chart = {"names": [r["name"] for r in region_rows], "official": [r["off"] for r in region_rows],
                    "synonym": [r["syn"] for r in region_rows]}
    reg_elig = [{"name": r["name"], "code": int(r["code"]), "ratio_v": r["syn"] / r["off"],
                 "ratio": ratio(r["syn"], r["off"])} for r in reg_all if r["off"] >= RATIO_MIN_STREETS]
    reg_elig.sort(key=lambda r: (-r["ratio_v"], r["name"], r["code"]))
    rratio_rows = [{"name": r["name"], "ratio": r["ratio"]} for r in reg_elig[:TOP_REGIONS]]
    rratio_chart = {"names": [r["name"] for r in reg_elig[:TOP_REGIONS]],
                    "values": [round(r["ratio_v"], 2) for r in reg_elig[:TOP_REGIONS]]}

    # ---- how synonyms differ
    linked["kind"] = [_kind(a, b) for a, b in zip(linked["name"], linked["off_name"])]
    kc = linked.groupby("kind").size()
    kind_rows = []
    for k in KIND_ORDER:
        c = int(kc.get(k, 0))
        sub = linked[linked["kind"] == k]
        ex = ""
        if len(sub):
            e = sub.assign(L=(sub["name"].str.len() + sub["off_name"].str.len() - 24).abs()).sort_values(
                ["L", "city", "name", "off_name"], kind="stable").iloc[0]
            ex = f"{e['name']} ← {e['off_name']}"
        kind_rows.append({"key": k, "name": KIND_LABEL[k], "count": c,
                          "share": share(c, len(linked)), "example": ex})
    kinds_chart = {"names": [KIND_SHORT[r["key"]] for r in kind_rows], "values": [r["count"] for r in kind_rows]}

    # ---- alternative names of localities
    alt_c = alt.groupby("city").size()
    alt_rows = [{"name": city_name[c], "count": int(v), "code": int(c)} for c, v in alt_c.items()]
    alt_rows.sort(key=lambda r: (-r["count"], r["name"], r["code"]))
    alt_top = alt_rows[:TOP_ALT]
    alt_chart = {"names": [r["name"] for r in alt_top], "values": [r["count"] for r in alt_top]}
    n_alt_locs = len(alt_c)

    # ---- KPIs
    share_with = with_syn / n_off * 100 if n_off else 0.0
    kpis = {
        "names": {"value": n_rows, "display": n(n_rows), "tone": "brand"},
        "locs": {"value": n_locs, "display": n(n_locs), "tone": "brand"},
        "official": {"value": n_off, "display": n(n_off), "tone": "brand"},
        "synonyms": {"value": n_syn, "display": n(n_syn), "tone": "info"},
        "with_syn": {"value": with_syn, "display": f"{share_with:.1f}%", "tone": "brand"},
        "ratio": {"value": n_syn, "display": f"{n_syn / n_off:.2f}" if n_off else "0.00", "tone": "brand"},
    }

    insights = []
    for iid, txt in [
        ("volume", insight_volume(n_rows, n_syn, n_off, n_syn)),
        ("coverage", insight_coverage(n_off, with_syn, max_row)),
        ("concentration", insight_concentration(
            [{"name": r["name"], "total": r["total"]} for r in top_rows], n_names)),
        ("ratio_spread", insight_ratio_spread(elig_rows)),
        ("no_syn", insight_no_syn(zero, n_locs, zero_max)),
        ("kinds", insight_kinds(kind_rows, len(linked))),
        ("region", insight_region(reg_elig)),
        ("alt_loc", insight_alt_loc(n_alt, n_alt_locs, n_locs, alt_top)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    a0 = top_rows[0] if top_rows else {"name": "", "total": 0}
    lede = (f"רשות האוכלוסין וההגירה מפרסמת את רשימת הרחובות שבמרשם יחד עם שמותיהם הלא-רשמיים "
            f"(סינונימים): {n(n_rows)} שמות ב-{n(n_locs)} ישובים ו-{n(n_regions)} אזורי רישום. כל שם חלופי "
            f"מצביע על סמל הרחוב הרשמי באותו ישוב. העמוד מראה כמה שמות חלופיים יש, היכן הם מרוכזים, "
            f"ובמה הם נבדלים מהשם הרשמי.")
    labels = {
        "lede": lede,
        "names_kpi": "שמות רחובות ברשימה (רשמיים וחלופיים)",
        "locs_kpi": "ישובים",
        "official_kpi": "רחובות רשמיים",
        "synonyms_kpi": "שמות חלופיים לרחובות",
        "with_syn_kpi": "שיעור הרחובות הרשמיים עם שם חלופי",
        "ratio_kpi": "שמות חלופיים לכל רחוב רשמי",
        "top_note": (f"{n(len(top_rows))} הישובים עם מספר שמות הרחובות הגדול ביותר, מפוצלים לרשמיים וחלופיים. "
                     f"{a0['name']} מובילה עם {n(a0['total'])} שמות."),
        "top_aria": (f"גרף עמודות אופקי מוערם: רחובות רשמיים ושמות חלופיים ב-{n(len(top_rows))} הישובים הגדולים. "
                     f"{a0['name']} מובילה עם {n(a0['total'])} שמות."),
        "top_caption": "שמות רחובות רשמיים וחלופיים לפי ישוב",
        "dist_note": (f"כמה שמות חלופיים רשומים לכל רחוב רשמי. {n(n_off - with_syn)} רחובות ללא שם חלופי; "
                      f"בשאר מצטברים שמות חלופיים נוספים."),
        "dist_aria": f"גרף עמודות: התפלגות {n(n_off)} הרחובות הרשמיים לפי מספר השמות החלופיים שלהם.",
        "dist_caption": "רחובות רשמיים לפי מספר שמות חלופיים",
        "kinds_note": (f"השוואה אוטומטית בין {n(len(linked))} שמות חלופיים לשם הרשמי של אותו רחוב. "
                       f"הסיווג מבוסס על אותיות ומילים בלבד ולכן הוא הערכה, לא קביעה."),
        "kinds_aria": f"גרף עמודות אופקי: {n(len(linked))} השמות החלופיים לפי סוג ההבדל מהשם הרשמי.",
        "kinds_caption": "שמות חלופיים לפי סוג ההבדל מהשם הרשמי",
        "streets_note": (f"{n(len(street_rows))} הרחובות הרשמיים עם מספר השמות החלופיים הגדול ביותר."
                         + (f" {max_row['name']} ב{max_row['loc']} מובילה עם {n(max_row['count'])}." if max_row else "")),
        "streets_aria": "גרף עמודות אופקי: הרחובות הרשמיים עם הכי הרבה שמות חלופיים.",
        "streets_caption": "רחובות רשמיים עם הכי הרבה שמות חלופיים",
        "ratio_note": (f"שמות חלופיים לכל רחוב רשמי, בישובים עם {n(RATIO_MIN_STREETS)} רחובות רשמיים ומעלה "
                       f"({n(len(elig_rows))} ישובים). מוצגים {n(len(hi_rows))} "
                       f"הישובים עם היחס הגבוה ביותר" + (f" ו-{n(len(lo_rows))} עם הנמוך ביותר." if lo_rows else ".")),
        "ratio_aria": "גרף עמודות אופקי: שמות חלופיים לכל רחוב רשמי בישובים עם היחס הגבוה והנמוך ביותר.",
        "ratio_caption": "יחס שמות חלופיים לרחובות רשמיים לפי ישוב",
        "scatter_note": (f"כל נקודה היא ישוב עם לפחות {n(floor)} שמות רחובות ({n(scatter_n)} ישובים). "
                         f"הציר האופקי הוא מספר הרחובות הרשמיים, האנכי הוא מספר השמות החלופיים; שני הצירים לוגריתמיים וישוב ללא שם חלופי מוצג על הקו התחתון."),
        "scatter_aria": f"תרשים פיזור: רחובות רשמיים מול שמות חלופיים ב-{n(scatter_n)} ישובים.",
        "region_note": (f"רחובות רשמיים ושמות חלופיים לפי אזור רישום ({n(len(region_rows))} שורות; "
                        f"האזורים הקטנים מאוגדים תחת ״אחרים״ אם יש כאלה)."),
        "region_aria": "גרף עמודות אופקי מוערם: רחובות רשמיים ושמות חלופיים לפי אזור רישום.",
        "region_caption": "רחובות רשמיים ושמות חלופיים לפי אזור",
        "rratio_note": (f"שמות חלופיים לכל רחוב רשמי לפי אזור, באזורים עם {n(RATIO_MIN_STREETS)} רחובות רשמיים "
                        f"ומעלה."),
        "rratio_aria": "גרף עמודות אופקי: שמות חלופיים לכל רחוב רשמי לפי אזור רישום.",
        "rratio_caption": "יחס שמות חלופיים לרחובות רשמיים לפי אזור",
        "alt_note": (f"{n(n_alt)} שמות חלופיים לישובים עצמם (רשומים על סמל הרחוב {n(PLACEHOLDER)} של הישוב) "
                     f"ב-{n(n_alt_locs)} ישובים. מוצגים {n(len(alt_top))} הישובים עם הכי הרבה."),
        "alt_aria": "גרף עמודות אופקי: ישובים עם הכי הרבה שמות חלופיים לשם הישוב.",
        "alt_caption": "ישובים לפי מספר שמות חלופיים לשם הישוב",
    }

    first = top_rows[0] if top_rows else None
    agent_data = {
        "summary_he": (f"{n(n_rows)} שמות רחובות ב-{n(n_locs)} ישובים: {n(n_off)} רחובות רשמיים ו-{n(n_syn)} "
                       f"שמות חלופיים (סינונימים), {n_syn / n_off:.2f} לכל רחוב רשמי"
                       + (f"; {first['name']} מובילה עם {n(first['total'])} שמות." if first else ".")
                       if n_off else f"{n(n_rows)} שמות רחובות ב-{n(n_locs)} ישובים."),
        "dataset_kind": "registry",
        "suggested_tags": ["רחובות", "סינונימים", "שמות רחובות", "כתובות", "מרשם אוכלוסין", "ישובים"],
        "related_ids": [
            "d2581732-eca4-4988-b986-df8e791a1d60",
            "3fc54b81-25b3-4ac7-87db-248c3e1602de",
            "00172ee8-4433-4d5d-8fd4-11f0f08ce5c4",
        ],
        "spatial_coverage": "ישראל ויהודה והשומרון",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"top": top_chart, "dist": dist_chart, "kinds": kinds_chart, "streets": street_chart,
                   "ratio": ratio_chart, "scatter": scatter, "region": region_chart,
                   "rratio": rratio_chart, "alt": alt_chart},
        "insights": insights,
        "labels": labels,
        "tables": {
            "top": top_rows, "dist": bucket_rows,
            "kinds": [{k: v for k, v in r.items() if k != "key"} for r in kind_rows],
            "streets": street_rows, "ratio": ratio_table, "region": region_rows,
            "rratio": rratio_rows, "alt": alt_top,
        },
        "flags": {"alt": bool(alt_top), "kinds": bool(len(linked)), "ratio": bool(ratio_rows),
                  "rratio": bool(reg_elig), "scatter": bool(scatter_n)},
    }
