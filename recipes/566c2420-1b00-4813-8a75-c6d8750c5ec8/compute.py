"""צופרים בעיר באר שבע: one small point layer (ID, name, address, neighbourhood,
WGS84 lat/lon) of the city's warning-siren sites.

Read from the XLSX resource: the CSV's datastore copy has quote-shifted rows
where a stray quote slid the columns into each other.  The other two
resources are the same layer in ITM coordinates.

The neighbourhood field is free text ("ט" / "ט'", "יא" / "י\"א",
"ג" / "שכונה ג'", "אזור התרעה מערב - שכונה ג'"), so it is normalised to one
key per neighbourhood.  The site type is classified from the name by keyword
(school, kindergarten, shelter, synagogue, public service), with "אחר" for
everything else, so new names always land somewhere.  The rest is geometry
over the distinct sites: distance from the median centre, compass sector and
the nearest neighbouring siren.

Order-independent: dedup on a normalised key, then a total sort; ties broken
by name, address and coordinates.
"""
import math
import re

import pandas as pd

M_PER_DEG = 111320.0
DIST_EDGES = [0, 1000, 2000, 3000, 4000, 5000]
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
NN_TOP = 20
HOOD_TOP = 14
LIST_CAP = 200
NO_HOOD = "לא צוינה"
OTHER = "אחר"
WS = re.compile(r"\s+")
QUOTES = re.compile(r"[\"'׳״`]")

# (label, keywords); first match wins, order matters
TYPE_RULES = [
    ("גני ילדים ומעונות", ["גן ילדים", "גן ", "מעון"]),
    ("בתי ספר ומוסדות לימוד", ["בית ספר", "בי\"ס", "ביה\"ס", "מקיף", "ישיבת", "ישיבה", "תורני", "בית יעקב", "משכן"]),
    ("מקלטים", ["מקלט"]),
    ("בתי כנסת", ["בית כנסת", "ביכ\"נ", "בית הכנסת"]),
    ("מוסדות ציבור ושירותים", ["עיריית", "עירייה", "לאומי", "משטרה", "שיטור", "רווחה", "קליטה",
                               "בי\"ח", "בית חולים", "סורוקה", "אוניברסיטה", "מרכז מדעים", "חוסן"]),
]
TYPE_ORDER = [t for t, _ in TYPE_RULES] + [OTHER]


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def km(m):
    return f"{m / 1000:,.1f}"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def clean(s):
    return WS.sub(" ", str(s or "")).strip()


def site_type(name):
    n = name + " "
    for label, keys in TYPE_RULES:
        for k in keys:
            if n.startswith(k) or (" " + k) in (" " + n):
                return label
    return OTHER


def hood_key(raw):
    h = clean(raw)
    if " - " in h:
        h = h.split(" - ")[-1].strip()
    h = QUOTES.sub("", h).strip()
    if h.startswith("שכונה "):
        h = h[len("שכונה "):].strip()
    if h == "":
        return NO_HOOD
    if len(h) == 1:
        return "שכונה " + h + "׳"
    if len(h) == 2:
        return "שכונה " + h[0] + "״" + h[1]
    return h


def band_labels(edges):
    out = []
    for i, lo in enumerate(edges):
        if i == 0:
            out.append(f"עד {km(edges[1])} ק״מ")
        elif i + 1 < len(edges):
            out.append(f"{km(lo)} עד {km(edges[i + 1])} ק״מ")
        else:
            out.append(f"מעל {km(lo)} ק״מ")
    return out


def band_index(v, edges):
    idx = 0
    for i, lo in enumerate(edges):
        if v >= lo:
            idx = i
    return idx


def compute(frames):
    raw = frames["sirens"].copy()
    n_raw = len(raw)
    df = pd.DataFrame({
        "id": num(raw["ID"]),
        "name": raw["Name"].map(clean),
        "address": raw["Address"].map(clean),
        "hood": raw["Neiborhood"].map(hood_key),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
    })
    df = df[df["name"] != ""].copy()
    df["kla"] = df["la"].round(6)
    df["klo"] = df["lo"].round(6)
    uniq = df.drop_duplicates(subset=["name", "address", "kla", "klo"]).copy()
    n_dup = len(df) - len(uniq)
    uniq = uniq.sort_values(["name", "address", "kla", "klo"], kind="mergesort").reset_index(drop=True)
    uniq["type"] = uniq["name"].map(site_type)
    n_st = len(uniq)
    n_noid = int((uniq["id"].isna() | (uniq["id"] <= 0)).sum())

    okgeo = uniq["la"].between(29, 34) & uniq["lo"].between(34, 36)
    n_bad_geo = int((~okgeo).sum())
    geo = uniq[okgeo].copy().reset_index(drop=True)
    n_geo = len(geo)
    la0 = float(geo["la"].median())
    lo0 = float(geo["lo"].median())
    coslat = math.cos(math.radians(la0))
    geo["y"] = (geo["la"] - la0) * M_PER_DEG
    geo["x"] = (geo["lo"] - lo0) * M_PER_DEG * coslat
    geo["d"] = (geo["x"] ** 2 + geo["y"] ** 2) ** 0.5

    def sector(x, y):
        ang = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
        return int(((ang + 22.5) % 360.0) // 45.0)
    geo["sec"] = [sector(x, y) for x, y in zip(geo["x"], geo["y"])]

    xs, ys, names = geo["x"].tolist(), geo["y"].tolist(), geo["name"].tolist()
    nn_d, nn_name = [], []
    for i in range(n_geo):
        best = None
        for j in range(n_geo):
            if i == j:
                continue
            cand = (math.hypot(xs[i] - xs[j], ys[i] - ys[j]), names[j], j)
            if best is None or cand < best:
                best = cand
        nn_d.append(best[0] if best else None)
        nn_name.append(best[1] if best else "")
    geo["nn"] = nn_d
    geo["nn_name"] = nn_name
    has_nn = n_geo >= 2

    charts, tables = {}, {}

    # neighbourhoods: top-N + other, unassigned shown separately
    hc = uniq.groupby("hood").size().reset_index(name="n")
    named = hc[hc["hood"] != NO_HOOD].sort_values(["n", "hood"], ascending=[False, True], kind="mergesort")
    n_hoods = len(named)
    n_nohood = int(hc.loc[hc["hood"] == NO_HOOD, "n"].sum())
    top_h = named.head(HOOD_TOP)
    h_names, h_vals = top_h["hood"].tolist(), [int(v) for v in top_h["n"]]
    rest = int(named["n"].iloc[HOOD_TOP:].sum())
    n_rest_h = max(0, n_hoods - HOOD_TOP)
    if rest:
        h_names.append(f"{OTHER} ({fmt(n_rest_h)} שכונות)")
        h_vals.append(rest)
    if n_nohood:
        h_names.append(NO_HOOD)
        h_vals.append(n_nohood)
    charts["hoods"] = {"names": h_names, "values": h_vals}
    tables["hoods"] = {"headers": ["שכונה", "צופרים", "שיעור"],
                       "rows": [[a, fmt(b), pct(b / n_st)] for a, b in zip(h_names, h_vals)]}
    n_single = int((named["n"] == 1).sum())

    # site types
    tvals = [int((uniq["type"] == t).sum()) for t in TYPE_ORDER]
    charts["type"] = {"names": TYPE_ORDER, "values": tvals}
    tables["type"] = {"headers": ["סוג אתר", "צופרים", "שיעור"],
                      "rows": [[t, fmt(v), pct(v / n_st)] for t, v in zip(TYPE_ORDER, tvals)]}

    # distance bands
    geo["db"] = geo["d"].map(lambda v: band_index(v, DIST_EDGES))
    dl = band_labels(DIST_EDGES)
    dvals = [int((geo["db"] == i).sum()) for i in range(len(DIST_EDGES))]
    charts["dist"] = {"names": dl, "values": dvals}
    tables["dist"] = {"headers": ["מרחק מהמרכז", "צופרים", "שיעור"],
                      "rows": [[l, fmt(v), pct(v / n_geo)] for l, v in zip(dl, dvals)]}
    med_d = float(geo["d"].median())
    within_2k = int((geo["d"] < 2000).sum())

    # sectors
    svals = [int((geo["sec"] == i).sum()) for i in range(len(SECTORS))]
    charts["sectors"] = {"names": SECTORS, "values": svals}
    tables["sectors"] = {"headers": ["כיוון מהמרכז", "צופרים"],
                         "rows": [[s, fmt(v)] for s, v in zip(SECTORS, svals)]}

    # nearest neighbour: most isolated first
    nn_sorted = (geo.sort_values(["nn", "name", "address"], ascending=[False, True, True], kind="mergesort")
                 if has_nn else geo)
    top = nn_sorted.head(NN_TOP)
    charts["nn"] = {"names": top["name"].tolist(),
                    "values": [int(round(v)) for v in top["nn"]] if has_nn else []}
    tables["nn"] = {"headers": ["אתר הצופר", "הצופר הקרוב", "מרחק (מ׳)"],
                    "rows": [[a, b, fmt(c)] for a, b, c in zip(top["name"], top["nn_name"], top["nn"])] if has_nn else []}
    nn_more = max(0, n_geo - NN_TOP)
    med_nn = float(geo["nn"].median()) if has_nn else 0.0
    max_nn = float(geo["nn"].max()) if has_nn else 0.0

    # site list
    gi = {(r["name"], r["address"], r["kla"], r["klo"]): r for _, r in geo.iterrows()}
    rows = []
    for _, r in uniq.head(LIST_CAP).iterrows():
        g = gi.get((r["name"], r["address"], r["kla"], r["klo"]))
        rows.append([r["name"], r["address"] or "לא צוינה", r["hood"], r["type"],
                     (f"{g['nn_name']} ({fmt(g['nn'])} מ׳)" if g is not None and has_nn else "")])
    tables["list"] = {"headers": ["אתר הצופר", "כתובת", "שכונה", "סוג אתר", "הצופר הקרוב"], "rows": rows}

    ns_span = float(geo["y"].max() - geo["y"].min())
    ew_span = float(geo["x"].max() - geo["x"].min())

    # ---------- insights ----------
    insights = []

    if n_hoods >= 2:
        lead, second = named.iloc[0], named.iloc[1]
        share = int(lead["n"]) / n_st
        n_second = int((named["n"] == int(second["n"])).sum())
        runner = (f"לעומת {fmt(second['n'])} ב{second['hood']}, השנייה ברשימה. " if n_second == 1 else
                  f"לעומת {fmt(second['n'])} בכל אחת מ־{fmt(n_second)} השכונות הבאות. ")
        if int(lead["n"]) > int(second["n"]) and share >= 0.08:
            insights.append({"id": "hood", "text_he": (
                f"{lead['hood']} היא השכונה עם הכי הרבה צופרים: {fmt(lead['n'])} מתוך {fmt(n_st)} ({pct(share)}), "
                + runner +
                f"ב־{fmt(n_single)} מתוך {fmt(n_hoods)} השכונות הרשומות יש צופר אחד בלבד.")})

    lead_t = max(range(len(TYPE_ORDER) - 1), key=lambda i: (tvals[i], -i))
    n_public = n_st - tvals[-1]
    if tvals[lead_t] / n_st >= 0.2:
        edu = tvals[0] + tvals[1]
        head = (f"{fmt(n_public)} מתוך {fmt(n_st)} הצופרים ({pct(n_public / n_st)}) מוצבים במבני ציבור ומוסדות. "
                if n_public / n_st >= 0.5 else "")
        insights.append({"id": "type", "text_he": (
            head + f"סוג האתר הנפוץ ביותר הוא ״{TYPE_ORDER[lead_t]}״, עם {fmt(tvals[lead_t])} צופרים ({pct(tvals[lead_t] / n_st)})"
            + (f", ויחד עם גני הילדים מוסדות החינוך מארחים {fmt(edu)} צופרים ({pct(edu / n_st)})"
               if lead_t <= 1 and tvals[0] and tvals[1] else "")
            + f". {fmt(tvals[-1])} אתרים לא סווגו לאף אחד מהסוגים (הסיווג לפי שם האתר).")})

    if n_geo >= 5:
        share = within_2k / n_geo
        insights.append({"id": "centre", "text_he": (
            f"{fmt(within_2k)} מתוך {fmt(n_geo)} הצופרים ({pct(share)}) נמצאים במרחק של עד {km(2000)} ק״מ "
            f"ממרכז החציון של הצופרים. הפריסה משתרעת על כ־{km(ns_span)} ק״מ מצפון לדרום "
            f"ועל כ־{km(ew_span)} ק״מ ממזרח למערב.")})

    if has_nn and n_geo >= 3:
        iso = nn_sorted.iloc[0]
        ratio = float(iso["nn"]) / med_nn if med_nn > 0 else 0.0
        if ratio >= 1.5:
            partner = nn_sorted.iloc[1]
            mutual = (partner["name"] == iso["nn_name"] and partner["nn_name"] == iso["name"]
                      and abs(float(partner["nn"]) - float(iso["nn"])) < 1)
            if mutual:
                a, b = sorted([iso["name"], iso["nn_name"]])
                txt = (f"״{a}״ ו״{b}״ הם הצמד המבודד ביותר: כל אחד מהם הוא הצופר הקרוב לשני, במרחק {fmt(iso['nn'])} מ׳, "
                       f"פי {ratio:.1f} מהמרחק החציוני לצופר הקרוב ({fmt(med_nn)} מ׳).")
            else:
                txt = (f"הצופר המבודד ביותר הוא ״{iso['name']}״ ({iso['hood']}): הצופר הקרוב אליו (״{iso['nn_name']}״) "
                       f"נמצא במרחק {fmt(iso['nn'])} מ׳, פי {ratio:.1f} מהמרחק החציוני לצופר הקרוב ({fmt(med_nn)} מ׳).")
            insights.append({"id": "isolated", "text_he": txt})
        close = geo.sort_values(["nn", "name", "address"], kind="mergesort").iloc[0]
        if float(close["nn"]) <= 150:
            a, b = sorted([close["name"], close["nn_name"]])
            insights.append({"id": "closest", "text_he": (
                f"הצמד הצפוף ביותר הוא ״{a}״ ו״{b}״, במרחק של כ־{fmt(close['nn'])} מ׳ בלבד זה מזה.")})

    if n_nohood:
        insights.append({"id": "nohood", "text_he": (
            f"ל־{fmt(n_nohood)} צופרים לא צוינה שכונה במאגר; מיקומם מופיע במפה.")})

    if n_noid and n_noid < n_st:
        insights.append({"id": "noid", "text_he": (
            f"ל־{fmt(n_st - n_noid)} צופרים יש מספר מזהה במאגר, ו־{fmt(n_noid)} רשומות ({pct(n_noid / n_st)}) "
            f"נושאות את הערך 0, ככל הנראה אתרים שנוספו מאוחר יותר ללא מספור.")})

    n_noaddr = int((uniq["address"] == "").sum())
    if n_noaddr:
        insights.append({"id": "addr", "text_he": (
            f"ל־{fmt(n_noaddr)} אתרים אין כתובת במאגר, ומיקומם מסומן רק בקואורדינטות.")})

    if n_dup:
        insights.append({"id": "dups", "text_he": (
            f"{fmt(n_dup)} רשומות כפולות (אותו שם, כתובת ומיקום) הוסרו, והנתונים בעמוד מחושבים על {fmt(n_st)} אתרים שונים.")})

    if n_bad_geo:
        insights.append({"id": "badgeo", "text_he": (
            f"ל־{fmt(n_bad_geo)} אתרים אין קואורדינטות תקינות, והם אינם נכללים בחישובי המרחק.")})

    # ---------- kpis ----------
    kpis = {
        "sirens": {"value": n_st, "display": fmt(n_st), "tone": "brand", "label": "אתרי צופרים בעיר"},
        "hoods": {"value": n_hoods, "display": fmt(n_hoods), "tone": "brand", "label": "שכונות ואזורים עם צופר"},
        "nn": {"value": int(round(med_nn)), "display": fmt(med_nn), "tone": "info",
               "label": "מרחק חציוני לצופר הקרוב (מטרים)"},
        "maxnn": {"value": int(round(max_nn)), "display": fmt(max_nn),
                  "tone": "warn" if med_nn > 0 and max_nn >= 2.5 * med_nn else "brand",
                  "label": "המרחק הגדול ביותר לצופר הקרוב (מטרים)"},
    }

    summary = (
        f"מיקומי הצופרים בבאר שבע על מפה, לפי שם אתר, כתובת ושכונה: {fmt(n_st)} צופרים "
        f"ב־{fmt(n_hoods)} שכונות, במרחק חציוני של {fmt(med_nn)} מ׳ זה מזה."
    )
    lede = (
        f"מאגר צופרי ההתרעה של עיריית באר שבע: {fmt(n_st)} אתרים עם שם, כתובת, שכונה ומיקום מדויק. "
        f"הצופרים מוצבים ב־{fmt(n_hoods)} שכונות ואזורים"
        + (", רובם במבני ציבור כמו בתי ספר וגני ילדים. " if (n_st - tvals[-1]) / n_st >= 0.5 else ". ")
        + f"המרחק החציוני בין צופר לצופר הקרוב אליו הוא {fmt(med_nn)} מ׳."
    )
    labels = {
        "lede": lede,
        "map_note": "כל נקודה היא אתר צופר; לחיצה פותחת את שם האתר, הכתובת והשכונה.",
        "hoods_note": (f"מספר אתרי הצופרים בכל שכונה, מתוך {fmt(n_st)} אתרים"
                       + (f"; מוצגות {fmt(HOOD_TOP)} השכונות המובילות והשאר מקובצות." if n_rest_h else ".")),
        "type_note": f"סוג המבנה או האתר שעליו מוצב הצופר, מסווג לפי שם האתר, מתוך {fmt(n_st)} אתרים.",
        "dist_note": f"מרחק כל צופר ממרכז החציון של {fmt(n_geo)} הצופרים; החציון {fmt(med_d)} מ׳.",
        "sectors_note": "כמה צופרים נמצאים בכל כיוון ביחס למרכז החציון של הצופרים.",
        "nn_note": (f"המרחק מכל צופר לצופר הקרוב אליו, מהמבודד לצפוף; החציון {fmt(med_nn)} מ׳."
                    + (f" מוצגים {fmt(NN_TOP)} הצופרים המבודדים ביותר מתוך {fmt(n_geo)}." if nn_more else "")),
        "list_note": (f"כל {fmt(n_st)} אתרי הצופרים לפי שם, עם השכונה, סוג האתר והצופר הקרוב."
                      if n_st <= LIST_CAP else f"{fmt(LIST_CAP)} האתרים הראשונים לפי שם; הרשימה המלאה בטבלת הנתונים."),
        "hoods_aria": "צופרים לפי שכונה", "hoods_cap": "צופרים לפי שכונה",
        "type_aria": "צופרים לפי סוג אתר", "type_cap": "צופרים לפי סוג אתר",
        "dist_aria": "צופרים לפי מרחק ממרכז הצופרים", "dist_cap": "צופרים לפי מרחק ממרכז הצופרים",
        "sectors_aria": "צופרים לפי כיוון מהמרכז", "sectors_cap": "צופרים לפי כיוון מהמרכז",
        "nn_aria": "מרחק כל צופר לצופר הקרוב אליו", "nn_cap": "מרחק לצופר הקרוב",
        "list_cap": "רשימת אתרי הצופרים",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["צופרים", "ביטחון וחירום", "באר שבע", "התגוננות אזרחית", "מפה"],
            "related_ids": [
                "7edbd028-9704-440c-a1b6-a0ed566081bc",
                "82a30a97-01b0-4281-854c-c7931f3445c0",
                "947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe",
                "3c6d4061-41bf-4403-82e9-c8fae5df04dd",
                "dae759e1-aa71-421a-8649-b8974a82bf2d",
            ],
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"nn": has_nn},
    }
