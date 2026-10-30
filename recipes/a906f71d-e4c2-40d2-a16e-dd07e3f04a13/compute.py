"""מרכזים קהילתיים בבאר שבע: one small point layer (ID, name, address, neighbourhood, WGS84 lat/lon).

The municipality exports this layer from a GIS shapefile, so names and
addresses are cut to a fixed width and several names repeat ("מתנ"ס נוו" is
two different centres).  Every per-centre label is therefore "name
(neighbourhood)".  Single-letter neighbourhood codes (ד, ג, י'א) are Beer
Sheva's lettered neighbourhoods and are shown as "שכונה ד׳".  The page is
geometry over the centres: count per neighbourhood, distance from the median
centre, compass sector and nearest neighbouring centre.  The other three
resources are format / projection twins (XLSX, ITM) and are not read.

Order-independent: a total sort on (neighbourhood, name, address, coords).
"""
import math

import pandas as pd

M_PER_DEG = 111320.0
DIST_EDGES = [0, 1000, 2000, 3000, 4000]
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
NEIGH_TOP = 12
NN_TOP = 20
LIST_CAP = 200
OTHER = "אחר"


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def km(m):
    return f"{m / 1000:,.1f}"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def neigh_label(code):
    c = (code or "").strip()
    if c == "":
        return "לא צוינה"
    letters = c.replace("'", "").replace("׳", "").replace('"', "").replace("״", "").strip()
    if 1 <= len(letters) <= 2 and " " not in letters:
        if len(letters) == 1:
            return f"שכונה {letters}׳"
        return f"שכונה {letters[0]}״{letters[1]}"
    return c


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
    raw = frames["centers"].copy()
    n_raw = len(raw)
    df = pd.DataFrame({
        "idv": num(raw["ID"]),
        "name": raw["Name"].astype(str).str.strip(),
        "address": raw["Address"].astype(str).str.strip(),
        "ncode": raw["neighborho"].astype(str).str.strip(),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
    })
    df["neigh"] = df["ncode"].map(neigh_label)
    df["label"] = df["name"] + " (" + df["neigh"] + ")"
    df = df.sort_values(["neigh", "name", "address", "la", "lo"], kind="mergesort", na_position="last").reset_index(drop=True)
    n_c = len(df)
    n_noid = int((df["idv"].isna() | (df["idv"] <= 0)).sum())

    ok = df["la"].between(29, 34) & df["lo"].between(34, 36)
    n_bad_geo = int((~ok).sum())
    geo = df[ok].copy().reset_index(drop=True)
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

    xs, ys, labs = geo["x"].tolist(), geo["y"].tolist(), geo["label"].tolist()
    nn_d, nn_lab = [], []
    for i in range(n_geo):
        best = None
        for j in range(n_geo):
            if i == j:
                continue
            cand = (math.hypot(xs[i] - xs[j], ys[i] - ys[j]), labs[j], j)
            if best is None or cand < best:
                best = cand
        nn_d.append(best[0] if best else float("nan"))
        nn_lab.append(best[1] if best else "")
    geo["nn"] = nn_d
    geo["nn_label"] = nn_lab
    has_nn = n_geo >= 2

    charts, tables = {}, {}

    # neighbourhoods
    nc = df.groupby("neigh").size().reset_index(name="n")
    nc = nc.sort_values(["n", "neigh"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    n_neigh = len(nc)
    top_n = nc.head(NEIGH_TOP)
    rest = int(nc["n"].iloc[NEIGH_TOP:].sum()) if n_neigh > NEIGH_TOP else 0
    nnames = top_n["neigh"].tolist() + ([OTHER] if rest else [])
    nvals = [int(v) for v in top_n["n"]] + ([rest] if rest else [])
    charts["neigh"] = {"names": nnames, "values": nvals}
    tables["neigh"] = {"headers": ["שכונה", "מרכזים", "שיעור"],
                       "rows": [[a, fmt(v), pct(v / n_c)] for a, v in zip(nnames, nvals)]}
    n_single = int((nc["n"] == 1).sum())

    # distance bands
    geo["db"] = geo["d"].map(lambda v: band_index(v, DIST_EDGES))
    dl = band_labels(DIST_EDGES)
    dvals = [int((geo["db"] == i).sum()) for i in range(len(DIST_EDGES))]
    charts["dist"] = {"names": dl, "values": dvals}
    tables["dist"] = {"headers": ["מרחק מהמרכז", "מרכזים", "שיעור"],
                      "rows": [[l, fmt(v), pct(v / n_geo)] for l, v in zip(dl, dvals)]}
    med_d = float(geo["d"].median())

    # sectors
    svals = [int((geo["sec"] == i).sum()) for i in range(len(SECTORS))]
    charts["sectors"] = {"names": SECTORS, "values": svals}
    tables["sectors"] = {"headers": ["כיוון מהמרכז", "מרכזים"],
                         "rows": [[s, fmt(v)] for s, v in zip(SECTORS, svals)]}

    # nearest neighbour, most isolated first
    if has_nn:
        nn_sorted = geo.sort_values(["nn", "label", "address"], ascending=[False, True, True], kind="mergesort").reset_index(drop=True)
        top = nn_sorted.head(NN_TOP)
        charts["nn"] = {"names": top["label"].tolist(), "values": [int(round(v)) for v in top["nn"]]}
        tables["nn"] = {"headers": ["מרכז", "המרכז הקרוב", "מרחק (מ׳)"],
                        "rows": [[a, b, fmt(c)] for a, b, c in zip(top["label"], top["nn_label"], top["nn"])]}
        med_nn = float(geo["nn"].median())
    else:
        nn_sorted = geo
        charts["nn"] = {"names": [], "values": []}
        tables["nn"] = {"headers": [], "rows": []}
        med_nn = 0.0
    nn_more = max(0, n_geo - NN_TOP)

    # list
    gi = {r["label"] + "|" + r["address"]: r for _, r in geo.iterrows()}
    rows = []
    for _, r in df.head(LIST_CAP).iterrows():
        g = gi.get(r["label"] + "|" + r["address"])
        rows.append([
            r["name"], r["address"] or "לא צוינה", r["neigh"],
            fmt(g["d"]) if g is not None else "",
            (f"{g['nn_label']} ({fmt(g['nn'])} מ׳)" if (g is not None and has_nn) else ""),
        ])
    tables["list"] = {"headers": ["מרכז", "כתובת", "שכונה", "מרחק מהמרכז (מ׳)", "המרכז הקרוב"], "rows": rows}

    ns_span = float(geo["y"].max() - geo["y"].min()) if n_geo else 0.0
    ew_span = float(geo["x"].max() - geo["x"].min()) if n_geo else 0.0

    # ---------- insights ----------
    insights = []
    lead = nc.iloc[0]
    second = int(nc["n"].iloc[1]) if n_neigh > 1 else 0
    if int(lead["n"]) >= 2 and int(lead["n"]) > second and lead["neigh"] != "לא צוינה":
        insights.append({"id": "neigh", "text_he": (
            f"ב{lead['neigh']} יש {fmt(lead['n'])} מרכזים, יותר מבכל שכונה אחרת: {pct(lead['n'] / n_c)} "
            f"מכלל {fmt(n_c)} המרכזים במאגר, הפרושים על {fmt(n_neigh)} שכונות.")})

    if n_single >= 2:
        insights.append({"id": "single", "text_he": (
            f"ב־{fmt(n_single)} מתוך {fmt(n_neigh)} השכונות המופיעות במאגר רשום מרכז אחד בלבד.")})

    if has_nn and n_geo >= 3:
        iso = nn_sorted.iloc[0]
        ratio = float(iso["nn"]) / med_nn if med_nn > 0 else 0.0
        if ratio >= 1.5:
            insights.append({"id": "isolated", "text_he": (
                f"המרכז המבודד ביותר הוא {iso['label']}: המרכז הקרוב אליו, {iso['nn_label']}, נמצא במרחק "
                f"{km(iso['nn'])} ק״מ, פי {ratio:.1f} מהמרחק החציוני בין מרכז למרכז הקרוב אליו ({fmt(med_nn)} מ׳).")})
        close = geo.sort_values(["nn", "label", "address"], kind="mergesort").iloc[0]
        if float(close["nn"]) <= 0.6 * med_nn:
            a, b = sorted([close["label"], close["nn_label"]])
            insights.append({"id": "closest", "text_he": (
                f"הזוג הצמוד ביותר הוא {a} ו{b}, במרחק של כ־{fmt(close['nn'])} מ׳ בלבד זה מזה.")})

    if n_geo >= 5:
        top_s = max(range(len(SECTORS)), key=lambda i: (svals[i], -i))
        empty = [SECTORS[i] for i in range(len(SECTORS)) if svals[i] == 0]
        extent = f"המרכזים פרושים על כ־{km(ns_span)} ק״מ מצפון לדרום ועל כ־{km(ew_span)} ק״מ ממזרח למערב."
        if svals[top_s] / n_geo >= 0.25:
            txt = (f"הכיוון העמוס ביותר ממרכז החציון של המרכזים הוא {SECTORS[top_s]}, עם {fmt(svals[top_s])} מרכזים "
                   f"({pct(svals[top_s] / n_geo)}). " + extent)
        else:
            txt = "אין כיוון דומיננטי ממרכז החציון של המרכזים. " + extent
        insights.append({"id": "sector", "text_he": txt})

    if n_noid > 0:
        insights.append({"id": "ids", "text_he": (
            f"ל־{fmt(n_noid)} מתוך {fmt(n_c)} הרשומות אין מזהה (הערך 0 או ריק בשדה המזהה).")})

    if n_c >= 5:
        lens = df["name"].str.len()
        mode_len = int(sorted(lens.value_counts().items(), key=lambda kv: (-kv[1], kv[0]))[0][0])
        share = float((lens == mode_len).mean())
        dup_names = int(df["name"].duplicated(keep=False).sum())
        if share >= 0.6 and mode_len <= 12:
            tail = (f", ולכן {fmt(dup_names)} מרכזים שונים חולקים שם זהה במאגר" if dup_names >= 2 else "")
            insights.append({"id": "truncated", "text_he": (
                f"{pct(share)} משמות המרכזים באורך של {fmt(mode_len)} תווים בדיוק: נראה שהשמות קוצרו בשכבה הגאוגרפית{tail}. "
                f"בעמוד כל מרכז מוצג עם שם השכונה שלו.")})

    if n_bad_geo:
        insights.append({"id": "badgeo", "text_he": (
            f"ל־{fmt(n_bad_geo)} רשומות אין קואורדינטות תקינות, והן אינן נכללות בחישובי המרחק.")})

    # ---------- kpis ----------
    kpis = {
        "centers": {"value": n_c, "display": fmt(n_c), "tone": "brand", "label": "מתנ״סים ומרכזים קהילתיים"},
        "neigh": {"value": n_neigh, "display": fmt(n_neigh), "tone": "brand", "label": "שכונות עם מרכז"},
        "nn": {"value": int(round(med_nn)), "display": fmt(med_nn), "tone": "info",
               "label": "מרחק חציוני למרכז הקרוב (מטרים)"},
        "noid": {"value": n_noid, "display": fmt(n_noid), "tone": "warn" if n_noid else "ok",
                 "label": "רשומות ללא מזהה"},
    }

    summary = (
        f"איתור מתנ״סים ומרכזים קהילתיים בבאר שבע לפי שם, כתובת ושכונה, על מפה: "
        f"{fmt(n_c)} מרכזים ב־{fmt(n_neigh)} שכונות."
    )
    lede = (
        f"מפת המתנ״סים והמרכזים הקהילתיים של עיריית באר שבע: {fmt(n_c)} מרכזים ב־{fmt(n_neigh)} שכונות, "
        f"עם שם, כתובת ומיקום. המרחק החציוני בין מרכז למרכז הקרוב אליו הוא {fmt(med_nn)} מ׳. "
        f"לפי העירייה המאגר אינו מעודכן באופן מלא, וחלק מהמרכזים חסרים בו."
    )
    labels = {
        "lede": lede,
        "map_note": "כל נקודה היא מתנ״ס או מרכז קהילתי; לחיצה פותחת את השם, הכתובת והשכונה.",
        "neigh_note": (f"מספר המרכזים בכל שכונה, מתוך {fmt(n_c)} מרכזים."
                       + (f" מוצגות {fmt(NEIGH_TOP)} השכונות המובילות, והשאר תחת ״{OTHER}״." if rest else "")),
        "dist_note": f"מרחק כל מרכז ממרכז החציון של {fmt(n_geo)} המרכזים; החציון {fmt(med_d)} מ׳.",
        "sectors_note": "כמה מרכזים נמצאים בכל כיוון ביחס למרכז החציון של המרכזים.",
        "nn_note": (f"המרחק מכל מרכז למרכז הקרוב אליו, מהמבודד לצפוף; החציון {fmt(med_nn)} מ׳."
                    + (f" מוצגים {fmt(NN_TOP)} המרכזים המבודדים ביותר מתוך {fmt(n_geo)}." if nn_more else "")),
        "list_note": (f"כל {fmt(n_c)} המרכזים לפי שכונה, עם המרחק ממרכז החציון והמרכז הקרוב ביותר."
                      if n_c <= LIST_CAP else f"{fmt(LIST_CAP)} המרכזים הראשונים לפי שכונה; הרשימה המלאה בטבלת הנתונים."),
        "neigh_aria": "מרכזים קהילתיים לפי שכונה", "neigh_cap": "מרכזים קהילתיים לפי שכונה",
        "dist_aria": "מרכזים לפי מרחק ממרכז החציון", "dist_cap": "מרכזים לפי מרחק ממרכז החציון",
        "sectors_aria": "מרכזים לפי כיוון מהמרכז", "sectors_cap": "מרכזים לפי כיוון מהמרכז",
        "nn_aria": "מרחק כל מרכז למרכז הקרוב אליו", "nn_cap": "מרחק למרכז הקרוב",
        "list_cap": "רשימת המתנ״סים והמרכזים הקהילתיים",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["מרכזים קהילתיים", "מתנ״סים", "באר שבע", "פנאי וקהילה"],
            "related_ids": [
                "d25f8679-13bc-4082-bf6e-6156e1d2df60",
                "947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe",
                "dae759e1-aa71-421a-8649-b8974a82bf2d",
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
        "flags": {"nn": has_nn},
    }
