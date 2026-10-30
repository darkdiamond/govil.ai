"""מועדונים חברתיים לקשיש בבאר שבע: one small point layer (name, address, type, WGS84 lat/lon).

The page counts distinct clubs (name + address + type + coordinates), breaks
them down by the free-text `type` field (raw values, top-N + "אחר") and by a
coarser family derived from it (day centre, club in a shelter or flat,
supportive-neighbourhood club, plain club, other), then does geometry over
the clubs: distance from the median centre, compass sector and nearest
neighbouring club.  `Id` is a constant 0 and is not read.  The other three
resources are format / projection twins (XLSX, ITM) and are not read.

Order-independent: dedup on a normalised key, then a total sort; ties broken
by name, address, type and coordinates.
"""
import math
import re

import pandas as pd

M_PER_DEG = 111320.0
DIST_EDGES = [0, 1000, 2000, 3000, 4000]
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
TYPE_TOP = 8
NN_TOP = 20
LIST_CAP = 200
OTHER = "אחר"
FAMILIES = ["מועדון חברתי", "מרכז יום", "מועדון במקלט או בדירה", "מועדון שכונה תומכת", "מסגרת אחרת"]
TRAIL_NUM = re.compile(r"[\s,]*\d+[א-ת]?\s*$")


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def km(m):
    return f"{m / 1000:,.1f}"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def family(t):
    t = (t or "").strip()
    if "מרכז יום" in t:
        return FAMILIES[1]
    if "מקלט" in t or "דירת" in t or "דירה" in t:
        return FAMILIES[2]
    if "שכונה תומכת" in t:
        return FAMILIES[3]
    if t == "מועדון":
        return FAMILIES[0]
    return FAMILIES[4]


def street(a):
    a = (a or "").strip()
    return TRAIL_NUM.sub("", a).strip()


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
    raw = frames["clubs"].copy()
    n_raw = len(raw)
    df = pd.DataFrame({
        "name": raw["name"].astype(str).str.strip(),
        "address": raw["address"].astype(str).str.strip(),
        "type": raw["type"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
    })
    df.loc[df["type"] == "", "type"] = "לא צוין"
    df["kla"] = df["la"].round(6)
    df["klo"] = df["lo"].round(6)
    uniq = df.drop_duplicates(subset=["name", "address", "type", "kla", "klo"]).copy()
    n_dup = n_raw - len(uniq)
    uniq = uniq.sort_values(["name", "address", "type", "kla", "klo"], kind="mergesort").reset_index(drop=True)
    n_cl = len(uniq)
    n_names = int(uniq["name"].nunique())
    uniq["fam"] = uniq["type"].map(family)
    uniq["street"] = uniq["address"].map(street)

    okgeo = uniq["la"].between(29, 34) & uniq["lo"].between(34, 36)
    n_bad_geo = int((~okgeo).sum())
    geo = uniq[okgeo].copy().reset_index(drop=True)
    n_geo = len(geo)
    has_geo = n_geo >= 3
    charts, tables = {}, {}

    # ---------- type (raw) ----------
    tc = uniq.groupby("type").size().reset_index(name="n")
    tc = tc.sort_values(["n", "type"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    n_types = len(tc)
    if n_types > TYPE_TOP + 1:
        head = tc.head(TYPE_TOP)
        rest = int(tc["n"].iloc[TYPE_TOP:].sum())
        t_names = head["type"].tolist() + [OTHER]
        t_vals = [int(v) for v in head["n"]] + [rest]
    else:
        t_names = tc["type"].tolist()
        t_vals = [int(v) for v in tc["n"]]
    charts["type"] = {"names": t_names, "values": t_vals}
    tables["type"] = {"headers": ["סוג המסגרת (כפי שנרשם)", "מועדונים", "שיעור"],
                      "rows": [[a, fmt(v), pct(v / n_cl)] for a, v in zip(t_names, t_vals)]}

    # ---------- family ----------
    fvals = [int((uniq["fam"] == f).sum()) for f in FAMILIES]
    fam_pairs = [(f, v) for f, v in zip(FAMILIES, fvals) if v > 0]
    charts["family"] = {"items": [{"name": f, "value": v} for f, v in fam_pairs]}
    tables["family"] = {"headers": ["סוג מסגרת", "מועדונים", "שיעור"],
                        "rows": [[f, fmt(v), pct(v / n_cl)] for f, v in fam_pairs]}
    n_day = fvals[1]
    n_shel = fvals[2]

    # ---------- geometry ----------
    med_d = med_nn = 0.0
    within = 0
    svals = [0] * len(SECTORS)
    ns_span = ew_span = 0.0
    nn_sorted = geo
    if has_geo:
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

        xs, ys = geo["x"].tolist(), geo["y"].tolist()
        names, addrs = geo["name"].tolist(), geo["address"].tolist()
        nn_d, nn_name = [], []
        for i in range(n_geo):
            best = None
            for j in range(n_geo):
                if i == j:
                    continue
                cand = (math.hypot(xs[i] - xs[j], ys[i] - ys[j]), names[j], addrs[j], j)
                if best is None or cand < best:
                    best = cand
            nn_d.append(best[0])
            nn_name.append(best[1])
        geo["nn"] = nn_d
        geo["nn_name"] = nn_name

        geo["db"] = geo["d"].map(lambda v: band_index(v, DIST_EDGES))
        dl = band_labels(DIST_EDGES)
        dvals = [int((geo["db"] == i).sum()) for i in range(len(DIST_EDGES))]
        charts["dist"] = {"names": dl, "values": dvals}
        tables["dist"] = {"headers": ["מרחק מהמרכז", "מועדונים", "שיעור"],
                          "rows": [[l, fmt(v), pct(v / n_geo)] for l, v in zip(dl, dvals)]}
        med_d = float(geo["d"].median())
        within = int((geo["d"] < 2000).sum())

        svals = [int((geo["sec"] == i).sum()) for i in range(len(SECTORS))]
        charts["sectors"] = {"names": SECTORS, "values": svals}
        tables["sectors"] = {"headers": ["כיוון מהמרכז", "מועדונים"],
                             "rows": [[s, fmt(v)] for s, v in zip(SECTORS, svals)]}

        nn_sorted = geo.sort_values(["nn", "name", "address"], ascending=[False, True, True], kind="mergesort")
        top = nn_sorted.head(NN_TOP)
        lab = [f"{a} ({s})" if names.count(a) > 1 else a for a, s in zip(top["name"], top["address"])]
        charts["nn"] = {"names": lab, "values": [int(round(v)) for v in top["nn"]]}
        tables["nn"] = {"headers": ["מועדון", "המועדון הקרוב", "מרחק (מ׳)"],
                        "rows": [[a, b, fmt(c)] for a, b, c in zip(lab, top["nn_name"], top["nn"])]}
        med_nn = float(geo["nn"].median())
        ns_span = float(geo["y"].max() - geo["y"].min())
        ew_span = float(geo["x"].max() - geo["x"].min())
    nn_more = max(0, n_geo - NN_TOP)

    # ---------- list ----------
    gi = geo.set_index(["name", "address", "type", "kla", "klo"]) if has_geo else None
    rows = []
    for _, r in uniq.head(LIST_CAP).iterrows():
        key = (r["name"], r["address"], r["type"], r["kla"], r["klo"])
        near = ""
        if gi is not None and key in gi.index:
            g = gi.loc[key]
            near = f"{g['nn_name']} ({fmt(g['nn'])} מ׳)"
        rows.append([r["name"], r["address"] or "לא צוינה", r["type"], near])
    tables["list"] = {"headers": ["מועדון", "כתובת", "סוג", "המועדון הקרוב"], "rows": rows}

    # ---------- insights ----------
    insights = []
    lead_t, lead_n = tc["type"].iloc[0], int(tc["n"].iloc[0])
    if n_types >= 2 and lead_n / n_cl >= 0.3:
        second = f"; אחריו ״{tc['type'].iloc[1]}״ עם {fmt(int(tc['n'].iloc[1]))}"
        insights.append({"id": "type", "text_he": (
            f"הסוג הנפוץ ביותר הוא ״{lead_t}״: {fmt(lead_n)} מתוך {fmt(n_cl)} המסגרות ({pct(lead_n / n_cl)}){second}. "
            f"בסך הכול מופיעים במאגר {fmt(n_types)} תיאורי סוג שונים.")})

    if n_day > 0:
        dual = int(((uniq["fam"] == FAMILIES[1]) & uniq["type"].str.contains("מועדון", regex=False)).sum())
        note = f" ({fmt(dual)} מהם מוגדרים מרכז יום ומועדון יחד)" if dual > 0 else ""
        insights.append({"id": "family", "text_he": (
            f"{fmt(n_day)} מהמסגרות ({pct(n_day / n_cl)}) הן מרכזי יום{note}, "
            f"ו־{fmt(fvals[0])} הן מועדונים חברתיים ללא תיאור נוסף.")})

    if n_shel > 0:
        nm = sorted(uniq.loc[uniq["fam"] == FAMILIES[2], "type"].unique().tolist())
        lead = "מועדון אחד פועל" if n_shel == 1 else f"{fmt(n_shel)} מועדונים פועלים"
        insights.append({"id": "sheltered", "text_he": (
            f"{lead} במקלט או בדירת מגורים ולא במבנה ייעודי: " + ", ".join(f"״{t}״" for t in nm) + ".")})

    if has_geo and n_geo >= 5:
        share = within / n_geo
        insights.append({"id": "centre", "text_he": (
            f"{fmt(within)} מתוך {fmt(n_geo)} המועדונים ({pct(share)}) נמצאים במרחק של עד {km(2000)} ק״מ "
            f"ממרכז החציון של המועדונים, והמרחק החציוני ממנו הוא {km(med_d)} ק״מ. "
            f"הפריסה משתרעת על כ־{km(ns_span)} ק״מ מצפון לדרום ועל כ־{km(ew_span)} ק״מ ממזרח למערב.")})

        top_v = max(svals)
        tops = [SECTORS[i] for i in range(len(SECTORS)) if svals[i] == top_v]
        empty = [SECTORS[i] for i in range(len(SECTORS)) if svals[i] == 0]
        if top_v / n_geo >= 0.2 and len(tops) <= 2:
            tail = (f" אין אף מועדון בכיוון {', '.join(empty)}." if 0 < len(empty) <= 3 else "")
            if len(tops) == 1:
                head = f"הכיוון העמוס ביותר ממרכז המועדונים הוא {tops[0]}, עם {fmt(top_v)} מועדונים ({pct(top_v / n_geo)})."
            else:
                head = (f"הכיוונים העמוסים ביותר ממרכז המועדונים הם {tops[0]} ו{tops[1]}, "
                        f"עם {fmt(top_v)} מועדונים בכל אחד ({pct(top_v / n_geo)}).")
            insights.append({"id": "sector", "text_he": head + tail})

        iso = nn_sorted.iloc[0]
        ratio = float(iso["nn"]) / med_nn if med_nn > 0 else 0.0
        if ratio >= 1.5:
            insights.append({"id": "isolated", "text_he": (
                f"המועדון המבודד ביותר הוא ״{iso['name']}״ ({iso['address']}): המועדון הקרוב אליו, ״{iso['nn_name']}״, "
                f"נמצא במרחק {km(iso['nn'])} ק״מ, פי {ratio:.1f} מהמרחק החציוני למועדון הקרוב ({km(med_nn)} ק״מ).")})
        close = geo.sort_values(["nn", "name", "address"], kind="mergesort").iloc[0]
        if float(close["nn"]) <= 400:
            a, b = sorted([close["name"], close["nn_name"]])
            insights.append({"id": "closest", "text_he": (
                f"הצמד הקרוב ביותר הוא ״{a}״ ו״{b}״, במרחק של כ־{fmt(close['nn'])} מ׳ בלבד זה מזה.")})

    sc = uniq[uniq["street"] != ""].groupby("street").size().reset_index(name="n")
    multi = sc[sc["n"] > 1].sort_values(["n", "street"], ascending=[False, True], kind="mergesort")
    if len(multi) > 0:
        parts = [f"רחוב {s} ({fmt(v)})" for s, v in zip(multi["street"], multi["n"])][:3]
        insights.append({"id": "streets", "text_he": (
            "יש רחובות שבהם פועל יותר ממועדון אחד: " + ", ".join(parts) + ".")})

    if n_names < n_cl:
        dn = uniq.groupby("name").size()
        dn = dn[dn > 1].sort_index()
        nm = ", ".join(f"״{k}״" for k in dn.index[:3])
        verb = f"השם {nm} משמש" if len(dn) == 1 else f"השמות {nm} משמשים"
        insights.append({"id": "names", "text_he": (
            f"יש {fmt(n_cl)} מועדונים אך רק {fmt(n_names)} שמות שונים: {verb} ליותר ממועדון אחד, "
            f"בכתובות שונות. כדאי לזהות מועדון לפי שם וכתובת יחד.")})

    if n_dup > 0:
        insights.append({"id": "dups", "text_he": (
            f"הקובץ מכיל {fmt(n_raw)} רשומות, מתוכן {fmt(n_dup)} כפילויות מלאות; החישובים בעמוד נעשים על {fmt(n_cl)} המועדונים השונים.")})
    if n_bad_geo:
        insights.append({"id": "badgeo", "text_he": (
            f"ל־{fmt(n_bad_geo)} מועדונים אין קואורדינטות תקינות, והם אינם נכללים בחישובי המרחק.")})

    # ---------- kpis ----------
    kpis = {
        "clubs": {"value": n_cl, "display": fmt(n_cl), "tone": "brand", "label": "מועדונים ומסגרות לקשיש"},
        "daycentres": {"value": n_day, "display": fmt(n_day), "tone": "info", "label": "מתוכם מרכזי יום"},
        "types": {"value": n_types, "display": fmt(n_types), "tone": "brand", "label": "תיאורי סוג שונים במאגר"},
        "nn": {"value": round(med_nn / 1000, 1), "display": km(med_nn), "tone": "info",
               "label": "מרחק חציוני למועדון הקרוב (ק״מ)"},
    }

    summary = (
        f"איתור מועדון חברתי או מרכז יום לקשיש בבאר שבע לפי שם וכתובת, על מפה: {fmt(n_cl)} מסגרות, "
        f"{fmt(n_day)} מהן מרכזי יום."
    )
    lede = (
        f"מאגר המועדונים החברתיים לקשיש של עיריית באר שבע (מועדוני גמלאים, מועדוני ותיקים ומרכזי יום): "
        f"{fmt(n_cl)} מסגרות עם שם, כתובת, סוג ומיקום. "
        f"{fmt(fvals[0])} הן מועדונים חברתיים, {fmt(n_day)} מרכזי יום, "
        f"והמרחק החציוני ממועדון למועדון הקרוב אליו הוא {km(med_nn)} ק״מ."
    )
    labels = {
        "lede": lede,
        "map_note": "כל נקודה היא מועדון או מרכז יום; לחיצה פותחת את השם, הכתובת והסוג.",
        "type_note": (f"סוג המסגרת כפי שנרשם במאגר, {fmt(n_cl)} מסגרות."
                      + (f" מוצגים {fmt(TYPE_TOP)} הסוגים הנפוצים והשאר תחת ״{OTHER}״." if n_types > TYPE_TOP + 1 else "")),
        "family_note": "קיבוץ תיאורי הסוג לקבוצות: מרכז יום, מועדון במקלט או בדירה, מועדון שכונה תומכת, מועדון חברתי ומסגרת אחרת.",
        "dist_note": f"מרחק כל מועדון ממרכז החציון של {fmt(n_geo)} המועדונים; החציון {km(med_d)} ק״מ.",
        "sectors_note": "כמה מועדונים נמצאים בכל כיוון ביחס למרכז החציון של המועדונים.",
        "nn_note": (f"המרחק מכל מועדון למועדון הקרוב אליו, מהמבודד לצפוף; החציון {km(med_nn)} ק״מ."
                    + (f" מוצגים {fmt(NN_TOP)} המבודדים ביותר מתוך {fmt(n_geo)}." if nn_more else "")),
        "list_note": (f"כל {fmt(n_cl)} המסגרות לפי שם, עם הכתובת, הסוג והמועדון הקרוב ביותר."
                      if n_cl <= LIST_CAP else f"{fmt(LIST_CAP)} המסגרות הראשונות לפי שם; הרשימה המלאה בטבלת הנתונים."),
        "type_aria": "מועדונים לפי סוג המסגרת", "type_cap": "מועדונים לפי סוג המסגרת",
        "family_aria": "מועדונים לפי קבוצת סוג", "family_cap": "מועדונים לפי קבוצת סוג",
        "dist_aria": "מועדונים לפי מרחק ממרכז המועדונים", "dist_cap": "מועדונים לפי מרחק ממרכז המועדונים",
        "sectors_aria": "מועדונים לפי כיוון מהמרכז", "sectors_cap": "מועדונים לפי כיוון מהמרכז",
        "nn_aria": "מרחק כל מועדון למועדון הקרוב אליו", "nn_cap": "מרחק למועדון הקרוב",
        "list_cap": "רשימת המועדונים החברתיים לקשיש",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["קשישים", "גיל הזהב", "רווחה", "מרכזי יום", "באר שבע", "פנאי"],
            "related_ids": [
                "d25f8679-13bc-4082-bf6e-6156e1d2df60",
                "dae759e1-aa71-421a-8649-b8974a82bf2d",
                "947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe",
                "82a30a97-01b0-4281-854c-c7931f3445c0",
                "b795e2e0-491e-4040-877e-f3681917f8be",
            ],
            "spatial_coverage": "באר שבע",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"geo": has_geo},
    }
