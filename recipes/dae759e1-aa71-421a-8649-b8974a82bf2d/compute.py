"""בתי כנסת בבאר שבע: one point layer (neighbourhood, street, house number,
name, other name, WGS84 lat/lon) from the Beer Sheva municipality.

Every row is a site.  The page counts sites per neighbourhood and street,
classifies each site from its name (a synagogue in a public shelter, a
torah centre / yeshiva, a Chabad house, a mikveh, unnamed), measures how
complete the naming and the address are, and how far each distinct point
is from the nearest other one.  The XLSX and the two ITM resources are
format / projection twins and are not read.

Order-independent: every aggregate is a count followed by a total sort with
name tie-breaks; the nearest-neighbour pass runs over distinct points sorted
by their coordinates.
"""
import math
import re

import pandas as pd

M_PER_DEG = 111320.0
NEIGH_TOP = 15
SHELTER_TOP = 12
STREET_TOP = 10
NN_EDGES = [0, 100, 200, 300, 500, 800]
NEAR_M = 300

LETTERS = re.compile(r"^[א-ת]{1,2}$")
SYN_WORDS = re.compile(r'בית כנסת|בית הכנסת|בי"כ|ביה"כ|ביכ')
TORAH_WORDS = re.compile(r"מרכז תורני|ישיב|בית מדרש|כולל")
COMMUNITY_WORDS = re.compile(r"עולי|לעדה|עדת|אתיופ|תימ|פרס|לוב|הודו|אשכנז|ספרד|מרוקו|תוניס|בוכר|גרוזי|קווקז|איראן|עירק|תורכ|כורד")
PAN_COMMUNAL = re.compile(r"על עדתי|כלל עדתי")

TYPE_ORDER = [
    "בית כנסת",
    "בית כנסת במקלט",
    "מרכז תורני, ישיבה או בית מדרש",
    "בית חב״ד",
    "מקווה",
    "ללא שם",
]
NAME_ORDER = ["שם ושם נוסף", "שם בלבד", "שם נוסף בלבד", "ללא שם"]
ADDR_ORDER = ["רחוב ומספר בית", "רחוב בלבד", "ללא כתובת"]
STATUS = [("בהליך", "בהליך"), ("בנוי", "בנוי"), ("פנוי", "פנוי"), ("הקצאה", "בהקצאה"), ("לשעבר", "מבנה ששימש בעבר לייעוד אחר")]


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def clean(s):
    return s.astype(str).str.replace(r"\s+", " ", regex=True).str.strip()


def neigh_label(n):
    if n == "":
        return "לא צוינה"
    if LETTERS.match(n):
        return f"שכונה {n}׳"
    return n


def site_type(name, other):
    both = f"{name} {other}".strip()
    if both == "":
        return "ללא שם"
    if "מקלט" in name:
        return "בית כנסת במקלט"
    if "מקווה" in name and not SYN_WORDS.search(name):
        return "מקווה"
    if 'חב"ד' in both or "חב״ד" in both:
        return "בית חב״ד"
    if TORAH_WORDS.search(both):
        return "מרכז תורני, ישיבה או בית מדרש"
    return "בית כנסת"


def name_kind(name, other):
    if name and other:
        return NAME_ORDER[0]
    if name:
        return NAME_ORDER[1]
    if other:
        return NAME_ORDER[2]
    return NAME_ORDER[3]


def addr_kind(street, house):
    if street == "":
        return ADDR_ORDER[2]
    h = pd.to_numeric(house, errors="coerce")
    if h == h and h > 0:
        return ADDR_ORDER[0]
    return ADDR_ORDER[1]


def band_labels(edges):
    out = []
    for i, lo in enumerate(edges):
        if i == 0:
            out.append(f"עד {fmt(edges[1])} מ׳")
        elif i + 1 < len(edges):
            out.append(f"{fmt(lo)} עד {fmt(edges[i + 1])} מ׳")
        else:
            out.append(f"מעל {fmt(lo)} מ׳")
    return out


def band_index(v, edges):
    idx = 0
    for i, lo in enumerate(edges):
        if v >= lo:
            idx = i
    return idx


def ranked(counts):
    """[(label, count)] sorted by count desc, then label."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def compute(frames):
    raw = frames["syn"]
    n = len(raw)
    df = pd.DataFrame({
        "id": num(raw["Id"]),
        "neigh": clean(raw["neighborho"]),
        "street": clean(raw["street"]),
        "house": clean(raw["HouseNumbe"]),
        "name": clean(raw["name"]),
        "other": clean(raw["OtherName"]),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
    })
    df["nl"] = df["neigh"].map(neigh_label)
    df["type"] = [site_type(a, b) for a, b in zip(df["name"], df["other"])]
    df["nk"] = [name_kind(a, b) for a, b in zip(df["name"], df["other"])]
    df["ak"] = [addr_kind(a, b) for a, b in zip(df["street"], df["house"])]
    df["shelter"] = df["type"] == "בית כנסת במקלט"
    ok = df["la"].between(29, 34) & df["lo"].between(34, 36)
    n_geo = int(ok.sum())
    n_bad_geo = n - n_geo

    charts, tables = {}, {}

    # ---------- neighbourhoods ----------
    neigh_counts = ranked(df["nl"].value_counts().to_dict())
    n_neigh = len([k for k, _ in neigh_counts if k != "לא צוינה"])
    top = neigh_counts[:NEIGH_TOP]
    rest = neigh_counts[NEIGH_TOP:]
    nn_names = [k for k, _ in top]
    nn_vals = [int(v) for _, v in top]
    if rest:
        nn_names.append(f"אחר ({fmt(len(rest))} שכונות)")
        nn_vals.append(int(sum(v for _, v in rest)))
    charts["neigh"] = {"names": nn_names, "values": nn_vals}
    tables["neigh"] = {"headers": ["שכונה", "אתרים", "שיעור"],
                       "rows": [[a, fmt(b), pct(b / n)] for a, b in zip(nn_names, nn_vals)]}

    # ---------- site type ----------
    tcounts = df["type"].value_counts().to_dict()
    tnames = [t for t in TYPE_ORDER if tcounts.get(t, 0) > 0]
    tvals = [int(tcounts[t]) for t in tnames]
    charts["type"] = {"names": tnames, "values": tvals}
    tables["type"] = {"headers": ["סוג האתר (לפי השם)", "אתרים", "שיעור"],
                      "rows": [[a, fmt(b), pct(b / n)] for a, b in zip(tnames, tvals)]}
    n_shelter = int(df["shelter"].sum())

    # ---------- shelters by neighbourhood ----------
    g = df.groupby("nl").agg(total=("shelter", "size"), sh=("shelter", "sum")).reset_index()
    g["sh"] = g["sh"].astype(int)
    g = g.sort_values(["total", "sh", "nl"], ascending=[False, False, True], kind="mergesort")
    gs = g.head(SHELTER_TOP)
    charts["shelter"] = {"names": gs["nl"].tolist(),
                         "shelter": gs["sh"].tolist(),
                         "other": (gs["total"] - gs["sh"]).astype(int).tolist()}
    tables["shelter"] = {"headers": ["שכונה", "סך האתרים", "במקלט", "שיעור במקלט"],
                         "rows": [[a, fmt(t), fmt(s), pct(s / t)] for a, t, s in zip(gs["nl"], gs["total"], gs["sh"])]}
    gsh = g[g["sh"] > 0].sort_values(["sh", "total", "nl"], ascending=[False, True, True], kind="mergesort")

    # ---------- naming ----------
    ncounts = df["nk"].value_counts().to_dict()
    nvals = [int(ncounts.get(k, 0)) for k in NAME_ORDER]
    charts["names"] = {"names": NAME_ORDER, "values": nvals}
    tables["names"] = {"headers": ["פרטי השם", "אתרים", "שיעור"],
                       "rows": [[a, fmt(b), pct(b / n)] for a, b in zip(NAME_ORDER, nvals)]}

    # ---------- streets ----------
    st = df[df["street"] != ""]
    scounts = ranked(st["street"].value_counts().to_dict())
    n_streets = len(scounts)
    multi = [(k, v) for k, v in scounts if v >= 2]
    stop = multi[:STREET_TOP]
    charts["streets"] = {"names": [k for k, _ in stop], "values": [int(v) for _, v in stop]}
    tables["streets"] = {"headers": ["רחוב", "אתרים"], "rows": [[k, fmt(v)] for k, v in stop]}
    has_streets = len(stop) >= 3

    # ---------- address completeness ----------
    acounts = df["ak"].value_counts().to_dict()
    avals = [int(acounts.get(k, 0)) for k in ADDR_ORDER]
    charts["addr"] = {"names": ADDR_ORDER, "values": avals}
    tables["addr"] = {"headers": ["פירוט הכתובת", "אתרים", "שיעור"],
                      "rows": [[a, fmt(b), pct(b / n)] for a, b in zip(ADDR_ORDER, avals)]}

    # ---------- nearest neighbour over distinct points ----------
    geo = df[ok].copy()
    geo["kla"] = geo["la"].round(6)
    geo["klo"] = geo["lo"].round(6)
    pts = geo.groupby(["kla", "klo"]).size().reset_index(name="cnt").sort_values(["kla", "klo"], kind="mergesort")
    n_pts = len(pts)
    n_coloc_pts = int((pts["cnt"] > 1).sum())
    n_coloc_rows = int(pts.loc[pts["cnt"] > 1, "cnt"].sum())
    has_nn = n_pts >= 5
    nn = []
    med_nn = 0.0
    if has_nn:
        la0 = float(pts["kla"].median())
        lo0 = float(pts["klo"].median())
        coslat = math.cos(math.radians(la0))
        xs = [(v - lo0) * M_PER_DEG * coslat for v in pts["klo"]]
        ys = [(v - la0) * M_PER_DEG for v in pts["kla"]]
        for i in range(n_pts):
            best = None
            for j in range(n_pts):
                if i == j:
                    continue
                dd = math.hypot(xs[i] - xs[j], ys[i] - ys[j])
                if best is None or dd < best:
                    best = dd
            nn.append(best)
        med_nn = float(pd.Series(nn).median())
        ns_span = max(ys) - min(ys)
        ew_span = max(xs) - min(xs)
        bl = band_labels(NN_EDGES)
        bvals = [0] * len(NN_EDGES)
        for v in nn:
            bvals[band_index(v, NN_EDGES)] += 1
        charts["nn"] = {"names": bl, "values": bvals}
        tables["nn"] = {"headers": ["מרחק לאתר הקרוב", "נקודות", "שיעור"],
                        "rows": [[a, fmt(b), pct(b / n_pts)] for a, b in zip(bl, bvals)]}
    near_share = (sum(1 for v in nn if v <= NEAR_M) / n_pts) if has_nn else 0.0
    max_nn = max(nn) if nn else 0.0

    # ---------- status words and communities in names ----------
    status_counts = []
    for word, label in STATUS:
        c = int(df["name"].str.contains(word, regex=False).sum())
        if c:
            status_counts.append((label, c))
    comm_mask = [bool(COMMUNITY_WORDS.search(f"{a} {b}")) and not PAN_COMMUNAL.search(f"{a} {b}")
                 for a, b in zip(df["name"], df["other"])]
    comm = df[comm_mask]
    n_comm = len(comm)
    comm_examples = sorted({(a if COMMUNITY_WORDS.search(a) else b) for a, b in zip(comm["name"], comm["other"])})[:3]

    # ---------- ids ----------
    n_noid = int(((df["id"] <= 0) | df["id"].isna()).sum())
    idpos = df.loc[df["id"] > 0, "id"]
    n_dup_id = int(idpos.duplicated(keep=False).sum())

    # ---------- insights ----------
    insights = []
    lead_name, lead_v = neigh_counts[0]
    top3 = sum(v for _, v in neigh_counts[:3])
    if n >= 10 and lead_v / n >= 0.12:
        insights.append({"id": "neigh", "text_he": (
            f"{lead_name} מובילה עם {fmt(lead_v)} אתרים ({pct(lead_v / n)} מכלל {fmt(n)} האתרים), "
            f"ושלוש השכונות המובילות ({', '.join(k for k, _ in neigh_counts[:3])}) "
            f"מרכזות יחד {pct(top3 / n)} מהאתרים.")})

    if n_shelter >= 3 and len(gsh):
        s0 = gsh.iloc[0]
        insights.append({"id": "shelter", "text_he": (
            f"{fmt(n_shelter)} אתרים ({pct(n_shelter / n)}) הם בתי כנסת הפועלים במקלט ציבורי, לפי שמם ברשומה. "
            f"הכי הרבה בתי כנסת במקלט נמצאים ב{s0['nl']}: {fmt(s0['sh'])} מתוך {fmt(s0['total'])} האתרים בשכונה.")})

    no_name = nvals[3]
    only_other = nvals[2]
    if no_name + only_other >= 3:
        insights.append({"id": "names", "text_he": (
            f"ל־{fmt(no_name + only_other)} אתרים ({pct((no_name + only_other) / n)}) אין שם בשדה השם הראשי: "
            f"{fmt(only_other)} מזוהים רק בשם הנוסף, ול־{fmt(no_name)} אין שם כלל ({'מופיעים רק לפי מיקום' if no_name > 1 else 'מופיע רק לפי מיקום'}).")})

    if has_nn:
        insights.append({"id": "nn", "text_he": (
            f"בתי הכנסת צפופים: ל־{pct(near_share)} מ־{fmt(n_pts)} הנקודות במפה יש אתר נוסף במרחק של עד {fmt(NEAR_M)} מ׳, "
            f"והמרחק החציוני לאתר הקרוב הוא {fmt(med_nn)} מ׳. המרחק הגדול ביותר לאתר הקרוב הוא {fmt(max_nn)} מ׳.")
            if near_share >= 0.5 else (
            f"המרחק החציוני מבית כנסת לאתר הקרוב אליו הוא {fmt(med_nn)} מ׳, ורק ל־{pct(near_share)} מ־{fmt(n_pts)} "
            f"הנקודות יש אתר נוסף במרחק של עד {fmt(NEAR_M)} מ׳.")})

    if n_coloc_pts >= 2:
        insights.append({"id": "coloc", "text_he": (
            f"{fmt(n_coloc_rows)} רשומות חולקות {fmt(n_coloc_pts)} נקודות בלבד: כמה אתרים (למשל בית כנסת ומקווה) "
            f"רשומים באותו מיקום בדיוק, ולכן במפה יש {fmt(n_pts)} נקודות שונות.")})

    if sum(c for _, c in status_counts) >= 3:
        parts = ", ".join(f"״{lbl}״ ({fmt(c)})" for lbl, c in status_counts)
        insights.append({"id": "status", "text_he": (
            f"בחלק מהשמות משולב מצב המבנה: {parts}. אלה מילים מתוך שדה השם, לא שדה מצב נפרד.")})

    if n_comm >= 3:
        insights.append({"id": "community", "text_he": (
            f"{fmt(n_comm)} אתרים נושאים בשמם זיקה לעדה או לקהילת עולים, למשל "
            + ", ".join(f"״{e}״" for e in comm_examples) + ".")})

    if avals[1] + avals[2] >= 3:
        insights.append({"id": "addr", "text_he": (
            f"ל־{fmt(avals[0])} אתרים ({pct(avals[0] / n)}) יש כתובת מלאה עם מספר בית; {fmt(avals[1])} רשומים לפי רחוב בלבד "
            f"ול־{fmt(avals[2])} אין רחוב כלל, ואותם אפשר לאתר רק במפה.")})

    if n_bad_geo:
        insights.append({"id": "badgeo", "text_he": (
            f"{'לרשומה אחת' if n_bad_geo == 1 else f'ל־{fmt(n_bad_geo)} רשומות'} אין קואורדינטות תקינות, "
            f"ולכן {'היא אינה מופיעה' if n_bad_geo == 1 else 'הן אינן מופיעות'} במפה ובחישובי המרחק.")})

    if n_noid >= 2:
        insights.append({"id": "noid", "text_he": (
            f"ל־{fmt(n_noid)} רשומות אין מספר מזהה (הערך 0)"
            + (f", ו־{fmt(n_dup_id)} רשומות חולקות מספר מזהה עם רשומה אחרת." if n_dup_id else ".")
        )})

    # ---------- kpis ----------
    kpis = {
        "sites": {"value": n, "display": fmt(n), "tone": "brand", "label": "אתרים במאגר (בתי כנסת ומבני דת)"},
        "neigh": {"value": n_neigh, "display": fmt(n_neigh), "tone": "brand", "label": "שכונות"},
        "shelter": {"value": n_shelter, "display": fmt(n_shelter), "tone": "info", "label": "בתי כנסת במקלט ציבורי"},
        "nn": {"value": int(round(med_nn)), "display": fmt(med_nn), "tone": "ok" if has_nn and med_nn <= NEAR_M else "brand",
               "label": "מרחק חציוני לבית הכנסת הקרוב (מטרים)"},
    }

    summary = (
        f"איתור בתי כנסת בבאר שבע לפי שכונה, רחוב או שם, על מפה: {fmt(n)} אתרים ב־{fmt(n_neigh)} שכונות, "
        f"{fmt(n_shelter)} מהם במקלטים."
    )
    if len(summary) > 155:
        summary = f"איתור בתי כנסת בבאר שבע לפי שכונה, רחוב או שם, על מפה: {fmt(n)} אתרים ב־{fmt(n_neigh)} שכונות."
    lede = (
        f"מאגר בתי הכנסת של עיריית באר שבע: {fmt(n)} אתרים עם שכונה, רחוב, מספר בית, שם ומיקום. "
        f"השכונה עם הכי הרבה אתרים היא {lead_name} ({fmt(lead_v)})"
        + (f", והמרחק החציוני בין בית כנסת לאתר הקרוב אליו הוא {fmt(med_nn)} מ׳ בלבד." if has_nn else ".")
    )
    span_note = (f" הפריסה משתרעת על כ־{ns_span / 1000:,.1f} ק״מ מצפון לדרום ועל כ־{ew_span / 1000:,.1f} ק״מ ממזרח למערב."
                 if has_nn else "")
    labels = {
        "lede": lede,
        "map_note": "כל נקודה היא בית כנסת או אתר תפילה; לחיצה פותחת את השם, השכונה והכתובת." + span_note,
        "neigh_note": (f"מספר האתרים בכל שכונה, מתוך {fmt(n)}."
                       + (f" מוצגות {fmt(NEIGH_TOP)} השכונות המובילות, והשאר מקובצות תחת ״אחר״." if rest else "")),
        "type_note": "סיווג לפי מילים בשם האתר: מקלט, מרכז תורני, ישיבה, בית מדרש, חב״ד או מקווה. אתר בלי שם בשני שדות השם מסווג ״ללא שם״.",
        "shelter_note": (f"בכל שכונה: בתי כנסת במקלט ציבורי לעומת שאר האתרים. מוצגות {fmt(len(gs))} השכונות עם הכי הרבה אתרים."),
        "names_note": "לחלק מהאתרים יש שם ראשי ושם נוסף, לחלק רק אחד מהם, ולחלק אין שם כלל.",
        "streets_note": (f"רחובות שיש בהם לפחות שני אתרים, מתוך {fmt(n_streets)} רחובות במאגר. שמות הרחובות מופיעים כפי שנרשמו במקור."),
        "addr_note": f"עד כמה הכתובת של כל אתר מפורטת, מתוך {fmt(n)} אתרים.",
        "nn_note": (f"המרחק מכל נקודה במפה לנקודה הקרובה אליה ({fmt(n_pts)} נקודות שונות); החציון {fmt(med_nn)} מ׳."
                    if has_nn else ""),
        "neigh_aria": "בתי כנסת לפי שכונה", "neigh_cap": "בתי כנסת לפי שכונה",
        "type_aria": "אתרים לפי סוג", "type_cap": "אתרים לפי סוג",
        "shelter_aria": "בתי כנסת במקלט לפי שכונה", "shelter_cap": "בתי כנסת במקלט לפי שכונה",
        "names_aria": "אתרים לפי פרטי השם", "names_cap": "אתרים לפי פרטי השם",
        "streets_aria": "רחובות עם הכי הרבה בתי כנסת", "streets_cap": "רחובות עם הכי הרבה בתי כנסת",
        "addr_aria": "אתרים לפי פירוט הכתובת", "addr_cap": "אתרים לפי פירוט הכתובת",
        "nn_aria": "התפלגות המרחק לבית הכנסת הקרוב", "nn_cap": "התפלגות המרחק לבית הכנסת הקרוב",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["בתי כנסת", "באר שבע", "דת", "קהילה", "מקלטים"],
            "related_ids": [
                "947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe",
                "82a30a97-01b0-4281-854c-c7931f3445c0",
                "0e8a1152-1cf2-4a9d-9fe8-2bfd7f60d970",
                "3c6d4061-41bf-4403-82e9-c8fae5df04dd",
            ],
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"nn": has_nn, "streets": has_streets},
    }
