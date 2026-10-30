"""מתקני ספורט בבאר שבע: one municipal point layer of sports facilities.

Each row is one facility (a court, hall, pool, fitness station …) at a named
site (school, park, club) with free-text attributes the municipality fills in
inconsistently: yes/no columns arrive as "קיים גידור"/"כן"/"לא"/"", facility
types mix catalogue labels with dimensions ("אולם ספורט קטן – 20x10 מ'") and
ad-hoc names, and the neighbourhood is spelled several ways ("ג'", "ג",
"שכונה ג'").  compute() normalises all of that with keyword rules that keep an
"אחר"/"לא צוין" bucket for anything unknown, so new values flow through.

A row with no name, no type-free fields and no coordinates (a broken CSV line)
is dropped and the drop is disclosed.  The XLSX and ITM resources are format /
projection twins of the CSV and are not read.

Order-independent: every grouping ends in a total sort with name tie-breaks.
"""
import re

import pandas as pd

TOP_NBHD = 12
TOP_SITES = 10
TOP_OPER = 8

# facility families, matched in order on the Type text (first hit wins)
FAMILIES = [
    ("בריכת שחייה", ["בריכ"]),
    ("אצטדיון ומסלול אתלטיקה", ["אצטדיון", "אתלטיקה"]),
    ("אולם ספורט", ["אולם"]),
    ("מתקן כושר", ["כושר"]),
    ("מגרש טניס", ["טניס"]),
    ("מגרש משולב", ["משולב"]),
    ("מגרש כדורגל", ["כדורגל", "מיני פיץ"]),
    ("מגרש קטרגל", ["קטרגל", "קט רגל"]),
    ("מגרש כדורסל", ["כדורסל", "כדוסל"]),
]
OTHER_FAM = "אחר או לא מסווג"

# yes/no attribute normalisation
YES_WORDS = {"כן", "קיים גידור", "קיימת תאורה", "נגיש לנכים", "מבנה סגור"}
NO_WORDS = {"לא", "אין", "אין גידור", "אין תאורה", "אין נגישות לנכים"}
AMEN = [
    ("fencing", "גידור"),
    ("lighting", "תאורה"),
    ("handicappe", "נגישות לנכים"),
]
STATE_NAMES = ["כן", "לא", "לא צוין"]

ACCESS_NAMES = ["פתוח ללא הגבלה", "בתיאום מראש", "לא צוין"]

# sports clubs named in the "associatio" column (known stems; others -> אחר)
CLUBS = [
    ("הפועל", ["הפועל"]),
    ("מכבי", ["מכבי"]),
    ("בית\"ר", ["בית\"ר", "בית״ר", "ביתר"]),
    ("כיוונים", ["כיוונים"]),
    ("אליצור", ["אליצור"]),
]
NO_CLUB = {"", "לא", "פתוח", "אין"}

# sport disciplines named in "SportType" (known stems; others -> אחר)
SPORTS = [
    ("כדורגל", ["כדורגל"]),
    ("כדורסל", ["כדורסל"]),
    ("קטרגל", ["קטרגל", "קט רגל"]),
    ("כושר", ["כושר"]),
    ("טניס", ["טניס", "טנ\"ש", "טנ״ש"]),
    ("התעמלות ומחול", ["התעמלות", "ריקוד", "מחול"]),
    ("אומנויות לחימה", ["ג'ודו", "האבקות", "סייף"]),
    ("חוגים כלליים", ["חוג", "כללי", "רב תכליתי"]),
]
NO_SPORT = {"", "לא"}

GERESH = "'׳`’"
NUMERAL_PAIRS = {"יא", "יב", "יג", "יד"}


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def clean(s):
    return re.sub(r"\s+", " ", str(s or "").replace(" ", " ")).strip()


def family(t):
    t = clean(t)
    for name, keys in FAMILIES:
        if any(k in t for k in keys):
            return name
    return OTHER_FAM


def yesno(v):
    v = clean(v)
    if v in YES_WORDS or v.startswith("קיים") or v.startswith("נגיש"):
        return "כן"
    if v in NO_WORDS or v.startswith("אין"):
        return "לא"
    return "לא צוין"


def access(v):
    v = clean(v)
    if "פתוח" in v:
        return "פתוח ללא הגבלה"
    if "תיאום" in v:
        return "בתיאום מראש"
    return "לא צוין"


def condition(v):
    v = clean(v)
    if v == "":
        return "לא צוין"
    if any(k in v for k in ["ליקוי", "הוסר", "תקול", "לא תקין", "לא פעיל", "סגור"]):
        return "ליקוי"
    if any(k in v for k in ["תקין", "פעיל", "טוב"]):
        return "כן"
    return "לא צוין"


def nbhd(v):
    v = clean(v)
    for ch in GERESH + "\"״":
        v = v.replace(ch, "")
    v = re.sub(r"^(שכונה|שכ)\s+", "", v).strip()
    v = v.replace("ייא", "יא")
    if v == "":
        return ""
    toks = []
    for t in v.split(" "):
        if len(t) == 1:
            toks.append(t + "׳")
        elif t in NUMERAL_PAIRS:
            toks.append(t[0] + "״" + t[1])
        else:
            toks.append(t)
    return " ".join(toks)


def operator(v):
    v = clean(v)
    if v in {"", "כן", "לא"}:
        return "לא צוין"
    if "כיוונים" in v:
        return "כיוונים"
    return v


def owner(v):
    v = clean(v)
    if v == "":
        return "לא צוין"
    if "כיוונים" in v:
        return "כיוונים"
    if "עירי" in v:
        return "עיריית באר שבע"
    return v


def tags(v, table, none_set):
    v = clean(v)
    if v in none_set:
        return []
    hits = [name for name, keys in table if any(k in v for k in keys)]
    return hits or ["אחר"]


def counts_table(items, order=None):
    s = pd.Series(items, dtype=object)
    vc = s.value_counts()
    keys = list(vc.index)
    if order is not None:
        keys = [k for k in order if k in vc.index] + sorted([k for k in keys if k not in order])
    else:
        keys = sorted(keys, key=lambda k: (-int(vc[k]), k))
    return [(k, int(vc[k])) for k in keys]


def compute(frames):
    raw = frames["facilities"].copy()
    n_raw = len(raw)
    df = pd.DataFrame({
        "type": raw["Type"].map(lambda v: clean(v).strip("\"'").strip()),
        "name": raw["Name"].map(clean),
        "street": raw["street"].map(clean),
        "house": num(raw["HouseNumbe"]),
        "nb": raw["neighborho"].map(nbhd),
        "oper": raw["Operator"].map(operator),
        "seats": num(raw["Seats"]).fillna(0),
        "acc": raw["Activity"].map(access),
        "fence": raw["fencing"].map(yesno),
        "light": raw["lighting"].map(yesno),
        "hcap": raw["handicappe"].map(yesno),
        "cond": raw["condition"].map(condition),
        "owner": raw["Owner"].map(owner),
        "school": raw["ForSchool"].map(clean),
        "clubs": raw["associatio"].map(lambda v: tags(v, CLUBS, NO_CLUB)),
        "sports": raw["SportType"].map(lambda v: tags(v, SPORTS, NO_SPORT)),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
    })
    geo_ok = df["la"].between(29, 34) & df["lo"].between(34, 36)
    # a broken CSV line: no name, no coordinates and no attribute filled
    attrs = raw[["Name", "street", "neighborho", "Operator", "Activity", "fencing", "lighting",
                 "handicappe", "condition", "Owner"]].apply(lambda c: c.map(clean))
    empty = (attrs == "").all(axis=1) & ~geo_ok
    n_broken = int(empty.sum())
    df = df[~empty].copy()
    df["fam"] = df["type"].map(family)
    df["site"] = df["name"].where(df["name"] != "", "ללא שם")
    df = df.sort_values(["site", "type", "street", "la", "lo"], kind="mergesort").reset_index(drop=True)
    n = len(df)
    n_geo = int((df["la"].between(29, 34) & df["lo"].between(34, 36)).sum())

    charts, tables = {}, {}

    # ---- facility families ----
    fam_rows = counts_table(df["fam"].tolist())
    fam_rows = [r for r in fam_rows if r[0] != OTHER_FAM] + [r for r in fam_rows if r[0] == OTHER_FAM]
    fam_order = [k for k, _ in fam_rows]
    charts["fam"] = {"names": fam_order, "values": [v for _, v in fam_rows]}
    tables["fam"] = {"headers": ["סוג מתקן", "מתקנים", "שיעור"],
                     "rows": [[k, fmt(v), pct(v / n)] for k, v in fam_rows]}
    top_fam, top_fam_n = fam_rows[0]

    # ---- amenities: fencing / lighting / accessibility / condition ----
    amen_cols = [("fence", "גידור"), ("light", "תאורה"), ("hcap", "נגישות לנכים"), ("cond", "תקין ופעיל")]
    amen = {"names": [lbl for _, lbl in amen_cols], "series": []}
    state_vals = {}
    for col, lbl in amen_cols:
        s = df[col]
        state_vals[col] = {
            "כן": int((s == "כן").sum()),
            "לא": int(((s == "לא") | (s == "ליקוי")).sum()),
            "לא צוין": int((s == "לא צוין").sum()),
        }
    for st in STATE_NAMES:
        amen["series"].append({"name": st, "data": [state_vals[c][st] for c, _ in amen_cols]})
    charts["amen"] = amen
    tables["amen"] = {"headers": ["מאפיין", "כן", "לא", "לא צוין"],
                      "rows": [[lbl] + [fmt(state_vals[c][st]) for st in STATE_NAMES] for c, lbl in amen_cols]}

    # ---- amenity rate by family (share "כן" of facilities in the family) ----
    fam_big = [k for k, v in fam_rows if v >= 3 and k != OTHER_FAM]
    fa = {"names": fam_big, "series": []}
    fa_rows = []
    for col, lbl in [("light", "תאורה"), ("hcap", "נגישות לנכים"), ("fence", "גידור")]:
        data = []
        for k in fam_big:
            sub = df[df["fam"] == k]
            data.append(round(float((sub[col] == "כן").mean()) * 100, 1) if len(sub) else 0.0)
        fa["series"].append({"name": lbl, "data": data})
    for i, k in enumerate(fam_big):
        sub = df[df["fam"] == k]
        fa_rows.append([k, fmt(len(sub))] + [f"{fa['series'][j]['data'][i]:.1f}%" for j in range(3)])
    charts["famamen"] = fa
    tables["famamen"] = {"headers": ["סוג מתקן", "מתקנים", "עם תאורה", "נגיש לנכים", "מגודר"], "rows": fa_rows}

    # ---- access mode by family ----
    acc_counts = {a: int((df["acc"] == a).sum()) for a in ACCESS_NAMES}
    ac = {"names": fam_order, "series": []}
    for a in ACCESS_NAMES:
        ac["series"].append({"name": a, "data": [int(((df["fam"] == k) & (df["acc"] == a)).sum()) for k in fam_order]})
    charts["acc"] = ac
    tables["acc"] = {"headers": ["סוג מתקן"] + ACCESS_NAMES,
                     "rows": [[k] + [fmt(ac["series"][j]["data"][i]) for j in range(len(ACCESS_NAMES))]
                              for i, k in enumerate(fam_order)]}

    # ---- neighbourhoods ----
    nb_known = df[df["nb"] != ""]
    nb_rows = counts_table(nb_known["nb"].tolist())
    n_nb = len(nb_rows)
    nb_top = nb_rows[:TOP_NBHD]
    nb_other = sum(v for _, v in nb_rows[TOP_NBHD:])
    nb_none = int((df["nb"] == "").sum())
    nb_names = [k for k, _ in nb_top] + (["שכונות אחרות"] if nb_other else []) + (["לא צוינה"] if nb_none else [])
    nb_vals = [v for _, v in nb_top] + ([nb_other] if nb_other else []) + ([nb_none] if nb_none else [])
    charts["nb"] = {"names": nb_names, "values": nb_vals}
    tables["nb"] = {"headers": ["שכונה", "מתקנים", "שיעור"],
                    "rows": [[k, fmt(v), pct(v / n)] for k, v in zip(nb_names, nb_vals)]}

    # ---- operators ----
    op_rows = counts_table(df["oper"].tolist())
    op_known = [r for r in op_rows if r[0] != "לא צוין"]
    op_top = op_known[:TOP_OPER]
    op_other = sum(v for _, v in op_known[TOP_OPER:])
    op_none = int((df["oper"] == "לא צוין").sum())
    op_names = [k for k, _ in op_top] + (["מפעילים אחרים"] if op_other else []) + (["לא צוין"] if op_none else [])
    op_vals = [v for _, v in op_top] + ([op_other] if op_other else []) + ([op_none] if op_none else [])
    charts["oper"] = {"names": op_names, "values": op_vals}
    tables["oper"] = {"headers": ["גורם מפעיל", "מתקנים", "שיעור"],
                      "rows": [[k, fmt(v), pct(v / n)] for k, v in zip(op_names, op_vals)]}
    own_rows = counts_table(df["owner"].tolist())

    # ---- sites with several facilities ----
    named = df[df["name"] != ""]
    site_rows = counts_table(named["name"].tolist())
    multi = [r for r in site_rows if r[1] >= 2]
    sites_top = multi[:TOP_SITES]
    site_fams = {}
    for k, _ in sites_top:
        fams = sorted(set(named.loc[named["name"] == k, "fam"]) - {OTHER_FAM}, key=lambda f: (fam_order.index(f), f))
        site_fams[k] = ", ".join(fams)
    charts["sites"] = {"names": [k for k, _ in sites_top], "values": [v for _, v in sites_top]}
    tables["sites"] = {"headers": ["אתר", "מתקנים", "סוגי מתקנים"],
                       "rows": [[k, fmt(v), site_fams[k]] for k, v in sites_top]}
    n_sites = len(site_rows)
    n_multi = len(multi)
    in_multi = sum(v for _, v in multi)

    # ---- clubs ----
    club_items = [c for lst in df["clubs"] for c in lst]
    club_rows = counts_table(club_items, order=[c for c, _ in CLUBS] + ["אחר"])
    n_with_club = int(df["clubs"].map(len).gt(0).sum())
    charts["clubs"] = {"names": [k for k, _ in club_rows], "values": [v for _, v in club_rows]}
    tables["clubs"] = {"headers": ["אגודה", "מתקנים שבהם היא פעילה"],
                       "rows": [[k, fmt(v)] for k, v in club_rows]}

    # ---- declared sports ----
    sport_items = [c for lst in df["sports"] for c in lst]
    sport_rows = counts_table(sport_items)
    sport_rows = [r for r in sport_rows if r[0] != "אחר"] + [r for r in sport_rows if r[0] == "אחר"]
    n_with_sport = int(df["sports"].map(len).gt(0).sum())
    charts["sports"] = {"names": [k for k, _ in sport_rows], "values": [v for _, v in sport_rows]}
    tables["sports"] = {"headers": ["ענף", "מתקנים"], "rows": [[k, fmt(v)] for k, v in sport_rows]}

    # ---- stands (seats) ----
    st = df[df["seats"] > 0].copy()
    st = st.sort_values(["seats", "site", "type"], ascending=[False, True, True], kind="mergesort")
    st_lbl = [f"{r.site}: {r.type}" if r.type else r.site for r in st.itertuples()]
    charts["seats"] = {"names": st_lbl[:TOP_SITES], "values": [int(v) for v in st["seats"].head(TOP_SITES)]}
    tables["seats"] = {"headers": ["מתקן", "מקומות ישיבה"],
                       "rows": [[a, fmt(b)] for a, b in zip(st_lbl[:TOP_SITES], st["seats"].head(TOP_SITES))]}
    n_seats = len(st)
    total_seats = int(st["seats"].sum())

    # ---- schools / addresses ----
    n_school = int((df["school"] != "").sum())
    n_schools = int(df.loc[df["school"] != "", "school"].nunique())
    n_house = int((df["house"].fillna(0) > 0).sum())
    n_nostreet = int((df["street"] == "").sum())

    # ---- KPIs ----
    acc_known = acc_counts["פתוח ללא הגבלה"] + acc_counts["בתיאום מראש"]
    hc = state_vals["hcap"]
    hc_known = hc["כן"] + hc["לא"]
    hc_share = hc["כן"] / hc_known if hc_known else 0.0
    outdoor = df[~df["fam"].isin(["אולם ספורט", "בריכת שחייה"])]
    od_known = outdoor[outdoor["light"] != "לא צוין"]
    od_lit = int((od_known["light"] == "כן").sum())
    od_dark = int((od_known["light"] == "לא").sum())
    lit_share = od_lit / len(od_known) if len(od_known) else 0.0
    open_share = acc_counts["פתוח ללא הגבלה"] / n if n else 0.0

    kpis = {
        "total": {"value": n, "display": fmt(n), "tone": "brand", "label": "מתקני ספורט במאגר"},
        "open": {"value": round(open_share * 100, 1), "display": pct(open_share),
                 "tone": "ok" if open_share >= 0.5 else "info", "label": "פתוחים לציבור ללא הגבלה"},
        "access": {"value": round(hc_share * 100, 1), "display": pct(hc_share),
                   "tone": "ok" if hc_share >= 0.9 else ("warn" if hc_share >= 0.7 else "danger"),
                   "label": "נגישים לנכים (מתוך מתקנים שדווחו)"},
        "lit": {"value": round(lit_share * 100, 1), "display": pct(lit_share),
                "tone": "ok" if lit_share >= 0.8 else ("warn" if lit_share >= 0.5 else "danger"),
                "label": "מתקני חוץ מוארים (מתוך מתקנים שדווחו)"},
        "nbhd": {"value": n_nb, "display": fmt(n_nb), "tone": "brand", "label": "שכונות עם מתקן ספורט"},
        "school": {"value": n_school, "display": fmt(n_school), "tone": "info", "label": "מתקנים המשרתים בית ספר"},
    }

    # ---- insights ----
    insights = []
    if n >= 5 and top_fam != OTHER_FAM:
        second = fam_rows[1] if len(fam_rows) > 1 else None
        txt = f"הסוג הנפוץ ביותר הוא {top_fam}: {fmt(top_fam_n)} מתוך {fmt(n)} המתקנים ({pct(top_fam_n / n)})"
        if second and second[0] != OTHER_FAM:
            txt += f", ואחריו {second[0]} עם {fmt(second[1])}"
        insights.append({"id": "fam", "text_he": txt + "."})

    if acc_known >= 5:
        o, c = acc_counts["פתוח ללא הגבלה"], acc_counts["בתיאום מראש"]
        halls = df[df["fam"] == "אולם ספורט"]
        h_coord = int((halls["acc"] == "בתיאום מראש").sum())
        txt = (f"{fmt(o)} מתקנים ({pct(o / n)}) פתוחים לציבור ללא הגבלה, ו־{fmt(c)} ({pct(c / n)}) "
               f"זמינים בתיאום מראש בלבד")
        if len(halls) >= 3 and h_coord / len(halls) >= 0.6:
            txt += f". באולמות הספורט התיאום הוא הכלל: {fmt(h_coord)} מתוך {fmt(len(halls))}"
        if acc_counts["לא צוין"]:
            txt += f". ל־{fmt(acc_counts['לא צוין'])} מתקנים אופן הפעילות לא צוין"
        insights.append({"id": "access", "text_he": txt + "."})

    if hc_known >= 5 and hc["לא"] > 0:
        insights.append({"id": "hcap", "text_he": (
            f"{fmt(hc['כן'])} מתוך {fmt(hc_known)} המתקנים שמצב הנגישות שלהם דווח ({pct(hc_share)}) נגישים לנכים, "
            f"ו־{fmt(hc['לא'])} אינם נגישים" + (f"; ל־{fmt(hc['לא צוין'])} מתקנים אין מידע על נגישות." if hc["לא צוין"] else "."))})

    if len(od_known) >= 5 and od_dark > 0:
        dark_fam = outdoor[outdoor["light"] == "לא"]["fam"].value_counts()
        dark_fam = sorted(dark_fam.items(), key=lambda kv: (-int(kv[1]), kv[0]))
        txt = (f"{fmt(od_dark)} ממתקני החוץ שמצב התאורה שלהם דווח ({pct(od_dark / len(od_known))}) אינם מוארים, "
               f"כך שאינם שמישים אחרי השקיעה")
        if dark_fam and dark_fam[0][1] >= 2:
            txt += f"; הבולטים ביניהם מסוג {dark_fam[0][0]} ({fmt(dark_fam[0][1])})"
        insights.append({"id": "light", "text_he": txt + "."})

    if n_nb >= 3:
        k1, v1 = nb_rows[0]
        txt = (f"המתקנים פרושים על פני {fmt(n_nb)} שכונות. בשכונה {k1} יש הכי הרבה מתקנים: {fmt(v1)} ({pct(v1 / n)})")
        if nb_none:
            txt += f". ל־{fmt(nb_none)} מתקנים לא צוינה שכונה"
        insights.append({"id": "nbhd", "text_he": txt + "."})

    def op_phrase(k, v):
        if k == "ניהול עצמי":
            return f"{fmt(v)} מתקנים ({pct(v / n)}) בניהול עצמי של המוסד שבו הם נמצאים"
        return f"{fmt(v)} מתקנים ({pct(v / n)}) בהפעלת {k}"

    if op_known:
        k1, v1 = op_known[0]
        if v1 / n >= 0.3:
            txt = "הגורם המפעיל הנפוץ: " + op_phrase(k1, v1)
            if len(op_known) > 1:
                k2, v2 = op_known[1]
                txt += ", ואחריו " + op_phrase(k2, v2)
            insights.append({"id": "oper", "text_he": txt + "."})

    if sites_top and sites_top[0][1] >= 3:
        k1, v1 = sites_top[0]
        insights.append({"id": "sites", "text_he": (
            f"״{k1}״ הוא האתר עם הכי הרבה מתקנים ({fmt(v1)}: {site_fams[k1]}). "
            f"בסך הכול {fmt(in_multi)} מתקנים מרוכזים ב־{fmt(n_multi)} אתרים שבכל אחד שני מתקנים או יותר.")})

    if n_seats >= 1:
        top = st.iloc[0]
        insights.append({"id": "seats", "text_he": (
            f"רק ב־{fmt(n_seats)} מתקנים צוינו מקומות ישיבה לקהל, בסך {fmt(total_seats)} מקומות. "
            f"הגדול הוא {top['type'] or 'המתקן'} ב״{top['site']}״ עם {fmt(top['seats'])} מקומות.")})

    if n_school >= 3:
        insights.append({"id": "school", "text_he": (
            f"{fmt(n_school)} מתקנים ({pct(n_school / n)}) רשומים כמשרתים בית ספר, {fmt(n_schools)} בתי ספר שונים בסך הכול.")})

    if n_broken:
        what = "שורה אחת ריקה" if n_broken == 1 else f"{fmt(n_broken)} שורות ריקות"
        verb = "ואינה נספרת" if n_broken == 1 else "ואינן נספרות"
        insights.append({"id": "broken", "text_he": (
            f"בקובץ {fmt(n_raw)} שורות, אך {what} (ללא שם, מאפיינים ומיקום) {verb}.")})

    # ---- texts ----
    summary = (f"איתור מתקני ספורט בבאר שבע על מפה: {fmt(n)} מגרשים, אולמות, בריכות ומתקני כושר ב־{fmt(n_nb)} שכונות, "
               f"{pct(open_share)} פתוחים לציבור.")
    lede = (f"מאגר מתקני הספורט של עיריית באר שבע: {fmt(n)} מתקנים, מגרשי כדורסל וכדורגל, אולמות ספורט, בריכות, "
            f"מגרשי טניס ומתקני כושר בפארקים, עם מיקום, שכונה, גורם מפעיל ומידע על נגישות, תאורה, גידור ושעות פעילות. "
            f"{fmt(acc_counts['פתוח ללא הגבלה'])} מהם פתוחים לציבור ללא הגבלה.")
    labels = {
        "lede": lede,
        "map_note": f"כל נקודה היא מתקן ספורט ({fmt(n_geo)} מתקנים עם מיקום). לחיצה פותחת את שם האתר, סוג המתקן והשכונה.",
        "map_aria": "מפה אינטראקטיבית של מתקני הספורט בבאר שבע. גרסה נגישה: ראו טבלת הנתונים למטה.",
        "fam_note": f"סוג המתקן מתוך תיאור המתקן במאגר, מקובץ לקבוצות; {fmt(len(fam_rows))} קבוצות.",
        "fam_aria": f"גרף עמודות: מתקני ספורט לפי סוג. המוביל: {top_fam} עם {fmt(top_fam_n)} מתקנים.",
        "fam_cap": "מתקני ספורט לפי סוג",
        "amen_note": "לכל מאפיין: כמה מתקנים דווחו כבעלי המאפיין, כמה לא, ולכמה המידע חסר.",
        "amen_aria": (f"גרף עמודות מוערמות: גידור, תאורה, נגישות ותקינות. "
                      f"{fmt(hc['כן'])} מתקנים נגישים לנכים."),
        "amen_cap": "מאפייני המתקנים",
        "famamen_note": "שיעור המתקנים בכל סוג שדווחו כמוארים, נגישים לנכים ומגודרים (סוגים עם שלושה מתקנים לפחות).",
        "famamen_aria": "גרף עמודות מקובצות: שיעור התאורה, הנגישות והגידור לפי סוג מתקן.",
        "famamen_cap": "תאורה, נגישות וגידור לפי סוג מתקן",
        "acc_note": "האם המתקן פתוח לציבור בכל עת או זמין בתיאום מראש בלבד, לפי סוג.",
        "acc_aria": (f"גרף עמודות מוערמות: אופן הפעילות לפי סוג מתקן. "
                     f"{fmt(acc_counts['פתוח ללא הגבלה'])} מתקנים פתוחים ללא הגבלה."),
        "acc_cap": "אופן הפעילות לפי סוג מתקן",
        "nb_note": (f"{fmt(min(TOP_NBHD, n_nb))} השכונות עם הכי הרבה מתקנים" +
                    (f"; שאר {fmt(n_nb - TOP_NBHD)} השכונות מקובצות יחד." if n_nb > TOP_NBHD else ".") +
                    " שמות השכונות אוחדו מכתיבים שונים."),
        "nb_aria": f"גרף עמודות: מתקני ספורט לפי שכונה. המובילה: {nb_rows[0][0] if nb_rows else ''}.",
        "nb_cap": "מתקני ספורט לפי שכונה",
        "oper_note": "הגוף שמפעיל את המתקן. ״ניהול עצמי״ הוא מתקן שמנוהל בידי בית הספר או המוסד שבו הוא נמצא.",
        "oper_aria": f"גרף עמודות: מתקנים לפי גורם מפעיל. המוביל: {op_known[0][0] if op_known else ''}.",
        "oper_cap": "מתקנים לפי גורם מפעיל",
        "own_note": "בעלות: " + ", ".join(f"{k} {fmt(v)}" for k, v in own_rows) + ".",
        "sites_note": (f"{fmt(n_multi)} אתרים (בתי ספר, מרכזי ספורט, פארקים) מרכזים שני מתקנים או יותר"
                       + (f"; מוצגים {fmt(TOP_SITES)} הגדולים." if n_multi > TOP_SITES else ".")),
        "sites_aria": (f"גרף עמודות אופקי: האתרים עם הכי הרבה מתקני ספורט. "
                       f"המוביל: {sites_top[0][0] if sites_top else ''}."),
        "sites_cap": "אתרים עם כמה מתקנים",
        "clubs_note": f"אגודות הספורט שצוינו כפעילות במתקן, ב־{fmt(n_with_club)} מתקנים. מתקן אחד יכול לארח כמה אגודות.",
        "clubs_aria": "גרף עמודות: אגודות ספורט לפי מספר המתקנים שבהם הן פעילות.",
        "clubs_cap": "אגודות ספורט במתקנים",
        "sports_note": f"ענפי הספורט שצוינו במתקן, ב־{fmt(n_with_sport)} מתקנים בלבד. מתקן יכול לשרת כמה ענפים.",
        "sports_aria": "גרף עמודות: ענפי ספורט מוצהרים לפי מספר מתקנים.",
        "sports_cap": "ענפי ספורט מוצהרים",
        "seats_note": f"מתקנים שצוינו בהם מקומות ישיבה לקהל: {fmt(n_seats)} מתקנים, {fmt(total_seats)} מקומות בסך הכול.",
        "seats_aria": "גרף עמודות אופקי: מקומות ישיבה לקהל לפי מתקן.",
        "seats_cap": "מקומות ישיבה לקהל",
        "addr_note": (f"ל־{fmt(n_house)} מתקנים צוין מספר בית, ול־{fmt(n_nostreet)} לא צוין רחוב; "
                      f"המיקום המדויק מופיע במפה."),
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["ספורט", "מתקני ספורט", "באר שבע", "פנאי", "נגישות"],
            "related_ids": [
                "b795e2e0-491e-4040-877e-f3681917f8be",
                "7edbd028-9704-440c-a1b6-a0ed566081bc",
                "947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe",
                "82a30a97-01b0-4281-854c-c7931f3445c0",
                "3c6d4061-41bf-4403-82e9-c8fae5df04dd",
            ],
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {
            "sites": len(sites_top) >= 2,
            "clubs": len(club_rows) >= 2,
            "sports": len(sport_rows) >= 2,
            "seats": n_seats >= 1,
            "famamen": len(fam_big) >= 2,
        },
    }
