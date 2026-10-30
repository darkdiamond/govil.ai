"""תחנות מוניות בבאר שבע: one small point layer (name, address, WGS84 lat/lon).

The export repeats every station as an exact duplicate row, so the page
counts distinct stations (name + address + coordinates) and reports the
duplicates as a data-quality fact.  Everything else is geometry over the
distinct stations: distance from the median centre, compass sector, nearest
neighbouring station, and how complete the address field is.  The other
three resources are format / projection twins (XLSX, ITM) and are not read.

Order-independent: dedup on a normalised key, then a total sort; ties broken
by name, address and coordinates.
"""
import math
import re

import pandas as pd

M_PER_DEG = 111320.0
DIST_EDGES = [0, 500, 1000, 1500, 2000, 3000]
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
NN_TOP = 20
LIST_CAP = 200
HAS_NUMBER = re.compile(r"\d")


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def km(m):
    return f"{m / 1000:,.1f}"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


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


def addr_kind(a):
    a = (a or "").strip()
    if a == "":
        return "ללא כתובת"
    if HAS_NUMBER.search(a):
        return "רחוב ומספר בית"
    return "רחוב, צומת או שדרה בלבד"


ADDR_ORDER = ["רחוב ומספר בית", "רחוב, צומת או שדרה בלבד", "ללא כתובת"]


def compute(frames):
    raw = frames["stations"].copy()
    n_raw = len(raw)
    df = pd.DataFrame({
        "name": raw["Name"].astype(str).str.strip(),
        "address": raw["address"].astype(str).str.strip(),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
    })
    # coordinates outside a broad Israel box are treated as unusable
    ok = df["la"].between(29, 34) & df["lo"].between(34, 36)
    n_bad_geo = int((~ok).sum())
    df["kla"] = df["la"].round(6)
    df["klo"] = df["lo"].round(6)
    uniq = df.drop_duplicates(subset=["name", "address", "kla", "klo"]).copy()
    n_dup = n_raw - len(uniq)
    uniq = uniq.sort_values(["name", "address", "kla", "klo"], kind="mergesort").reset_index(drop=True)
    n_st = len(uniq)
    n_names = int(uniq["name"].nunique())

    geo = uniq[uniq["la"].between(29, 34) & uniq["lo"].between(34, 36)].copy().reset_index(drop=True)
    n_geo = len(geo)
    la0 = float(geo["la"].median())
    lo0 = float(geo["lo"].median())
    coslat = math.cos(math.radians(la0))
    geo["y"] = (geo["la"] - la0) * M_PER_DEG
    geo["x"] = (geo["lo"] - lo0) * M_PER_DEG * coslat
    geo["d"] = (geo["x"] ** 2 + geo["y"] ** 2) ** 0.5

    # compass sector from the median centre (0 = north, clockwise)
    def sector(x, y):
        ang = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
        return int(((ang + 22.5) % 360.0) // 45.0)
    geo["sec"] = [sector(x, y) for x, y in zip(geo["x"], geo["y"])]

    # nearest neighbour among distinct stations
    xs, ys, names = geo["x"].tolist(), geo["y"].tolist(), geo["name"].tolist()
    nn_d, nn_name = [], []
    for i in range(n_geo):
        best = None
        for j in range(n_geo):
            if i == j:
                continue
            dd = math.hypot(xs[i] - xs[j], ys[i] - ys[j])
            cand = (dd, names[j], j)
            if best is None or cand < best:
                best = cand
        nn_d.append(best[0] if best else None)
        nn_name.append(best[1] if best else "")
    geo["nn"] = nn_d
    geo["nn_name"] = nn_name
    has_nn = n_geo >= 2

    charts, tables = {}, {}

    # distance bands
    geo["db"] = geo["d"].map(lambda v: band_index(v, DIST_EDGES))
    dl = band_labels(DIST_EDGES)
    dvals = [int((geo["db"] == i).sum()) for i in range(len(DIST_EDGES))]
    charts["dist"] = {"names": dl, "values": dvals}
    tables["dist"] = {"headers": ["מרחק מהמרכז", "תחנות", "שיעור"],
                      "rows": [[l, fmt(v), pct(v / n_geo)] for l, v in zip(dl, dvals)]}
    med_d = float(geo["d"].median())
    within_1k = int((geo["d"] < 1000).sum())

    # sectors
    svals = [int((geo["sec"] == i).sum()) for i in range(len(SECTORS))]
    charts["sectors"] = {"names": SECTORS, "values": svals}
    tables["sectors"] = {"headers": ["כיוון מהמרכז", "תחנות"],
                         "rows": [[s, fmt(v)] for s, v in zip(SECTORS, svals)]}

    # nearest neighbour: most isolated first
    nn_sorted = geo.sort_values(["nn", "name", "address"], ascending=[False, True, True], kind="mergesort") if has_nn else geo
    top = nn_sorted.head(NN_TOP)
    charts["nn"] = {"names": top["name"].tolist(), "values": [int(round(v)) for v in top["nn"]] if has_nn else []}
    tables["nn"] = {"headers": ["תחנה", "התחנה הקרובה", "מרחק (מ׳)"],
                    "rows": [[a, b, fmt(c)] for a, b, c in zip(top["name"], top["nn_name"], top["nn"])] if has_nn else []}
    nn_more = max(0, n_geo - NN_TOP)
    med_nn = float(geo["nn"].median()) if has_nn else 0.0

    # address completeness
    uniq["ak"] = uniq["address"].map(addr_kind)
    avals = [int((uniq["ak"] == k).sum()) for k in ADDR_ORDER]
    charts["addr"] = {"names": ADDR_ORDER, "values": avals}
    tables["addr"] = {"headers": ["סוג כתובת", "תחנות", "שיעור"],
                      "rows": [[k, fmt(v), pct(v / n_st)] for k, v in zip(ADDR_ORDER, avals)]}
    n_noaddr = avals[2]

    # station list (name order)
    gi = geo.set_index(["name", "address", "kla", "klo"])
    rows = []
    for _, r in uniq.head(LIST_CAP).iterrows():
        key = (r["name"], r["address"], r["kla"], r["klo"])
        if key in gi.index:
            g = gi.loc[key]
            rows.append([r["name"], r["address"] or "לא צוינה", fmt(g["d"]),
                         (f"{g['nn_name']} ({fmt(g['nn'])} מ׳)" if has_nn else "")])
        else:
            rows.append([r["name"], r["address"] or "לא צוינה", "", ""])
    tables["list"] = {"headers": ["תחנה", "כתובת", "מרחק מהמרכז (מ׳)", "התחנה הקרובה"], "rows": rows}

    # extent
    ns_span = float(geo["y"].max() - geo["y"].min())
    ew_span = float(geo["x"].max() - geo["x"].min())

    # ---------- insights ----------
    insights = []
    if n_dup > 0:
        counts = df.groupby(["name", "address", "kla", "klo"]).size()
        all_twice = bool((counts == 2).all())
        tail = "כל תחנה מופיעה בדיוק פעמיים" if all_twice else f"{fmt(int((counts > 1).sum()))} תחנות מופיעות יותר מפעם אחת"
        insights.append({"id": "dups", "text_he": (
            f"הקובץ מכיל {fmt(n_raw)} רשומות, אך רק {fmt(n_st)} תחנות שונות: {tail}, "
            f"ו־{fmt(n_dup)} רשומות הן כפילויות מלאות. כל הנתונים בעמוד מחושבים על התחנות השונות.")})

    if n_geo >= 5:
        share = within_1k / n_geo
        if share >= 0.4:
            insights.append({"id": "centre", "text_he": (
                f"{fmt(within_1k)} מתוך {fmt(n_geo)} התחנות ({pct(share)}) נמצאות במרחק של עד {fmt(1000)} מ׳ "
                f"ממרכז החציון של התחנות, והמרחק החציוני ממנו הוא {fmt(med_d)} מ׳.")})
        else:
            insights.append({"id": "centre", "text_he": (
                f"התחנות פרושות על פני העיר: רק {fmt(within_1k)} מתוך {fmt(n_geo)} ({pct(share)}) במרחק של עד "
                f"{fmt(1000)} מ׳ ממרכז החציון, והמרחק החציוני ממנו הוא {fmt(med_d)} מ׳.")})

    if has_nn and n_geo >= 3:
        iso = nn_sorted.iloc[0]
        ratio = float(iso["nn"]) / med_nn if med_nn > 0 else 0.0
        if ratio >= 1.5:
            partner = nn_sorted.iloc[1]
            mutual = partner["name"] == iso["nn_name"] and partner["nn_name"] == iso["name"] and abs(float(partner["nn"]) - float(iso["nn"])) < 1
            if mutual:
                a, b = sorted([iso["name"], iso["nn_name"]])
                txt = (f"״{a}״ ו״{b}״ הן הצמד המבודד ביותר: כל אחת מהן היא התחנה הקרובה לשנייה, במרחק {fmt(iso['nn'])} מ׳, "
                       f"פי {ratio:.1f} מהמרחק החציוני לתחנה הקרובה ({fmt(med_nn)} מ׳).")
            else:
                txt = (f"התחנה המבודדת ביותר היא ״{iso['name']}״: התחנה הקרובה אליה (״{iso['nn_name']}״) נמצאת "
                       f"במרחק {fmt(iso['nn'])} מ׳, פי {ratio:.1f} מהמרחק החציוני לתחנה הקרובה ({fmt(med_nn)} מ׳).")
            insights.append({"id": "isolated", "text_he": txt})
        close = geo.sort_values(["nn", "name", "address"], kind="mergesort").iloc[0]
        if float(close["nn"]) <= 100:
            a, b = sorted([close["name"], close["nn_name"]])
            insights.append({"id": "closest", "text_he": (
                f"הזוג הצמוד ביותר הוא ״{a}״ ו״{b}״, במרחק של כ־{fmt(close['nn'])} מ׳ בלבד זו מזו.")})

    if n_geo >= 5:
        top_s = max(range(len(SECTORS)), key=lambda i: (svals[i], -i))
        extent = (f"פריסת התחנות משתרעת על כ־{km(ns_span)} ק״מ מצפון לדרום ועל כ־{km(ew_span)} ק״מ ממזרח למערב.")
        if svals[top_s] / n_geo >= 0.25:
            insights.append({"id": "sector", "text_he": (
                f"הכיוון העמוס ביותר ממרכז התחנות הוא {SECTORS[top_s]}, עם {fmt(svals[top_s])} תחנות ({pct(svals[top_s] / n_geo)}). " + extent)})
        elif min(svals) >= 1:
            insights.append({"id": "sector", "text_he": (
                f"אין כיוון דומיננטי: בכל אחד משמונת הכיוונים ממרכז התחנות יש בין {fmt(min(svals))} ל־{fmt(max(svals))} תחנות. " + extent)})

    if n_noaddr > 0 or avals[1] > 0:
        if n_noaddr == 1:
            nm = uniq.loc[uniq["ak"] == "ללא כתובת", "name"].iloc[0]
            tail = f", ולתחנה ״{nm}״ אין כתובת כלל (מיקומה מופיע במפה)."
        elif n_noaddr > 1:
            tail = f", ול־{fmt(n_noaddr)} תחנות אין כתובת כלל (מיקומן מופיע במפה)."
        else:
            tail = "."
        insights.append({"id": "addr", "text_he": (
            f"ל־{fmt(avals[0])} תחנות יש כתובת עם מספר בית; {fmt(avals[1])} מתוארות רק בשם רחוב, שדרה או צומת" + tail)})

    if n_names < n_st:
        insights.append({"id": "names", "text_he": (
            f"יש {fmt(n_st)} תחנות אך רק {fmt(n_names)} שמות שונים: חלק מהשמות משמשים ליותר ממיקום אחד.")})

    if n_bad_geo:
        insights.append({"id": "badgeo", "text_he": (
            f"ל־{fmt(n_bad_geo)} רשומות אין קואורדינטות תקינות, והן אינן נכללות בחישובי המרחק.")})

    # ---------- kpis ----------
    kpis = {
        "stations": {"value": n_st, "display": fmt(n_st), "tone": "brand", "label": "תחנות מוניות שונות"},
        "nn": {"value": int(round(med_nn)), "display": fmt(med_nn), "tone": "info",
               "label": "מרחק חציוני לתחנה הקרובה (מטרים)"},
        "dups": {"value": n_dup, "display": fmt(n_dup), "tone": "warn" if n_dup else "ok",
                 "label": "רשומות כפולות בקובץ"},
        "noaddr": {"value": n_noaddr, "display": fmt(n_noaddr), "tone": "warn" if n_noaddr else "ok",
                   "label": "תחנות ללא כתובת"},
    }

    summary = (
        f"איתור תחנות מוניות בבאר שבע לפי שם וכתובת, על מפה: {fmt(n_st)} תחנות, "
        f"{fmt(within_1k)} מהן עד {fmt(1000)} מ׳ ממרכז התחנות."
    )
    lede = (
        f"מאגר תחנות המוניות של עיריית באר שבע: {fmt(n_st)} תחנות עם שם, כתובת ומיקום. "
        f"המרחק החציוני בין תחנה לתחנה הקרובה אליה הוא {fmt(med_nn)} מ׳, "
        f"והמרחק החציוני ממרכז התחנות הוא {fmt(med_d)} מ׳."
    )
    labels = {
        "lede": lede,
        "map_note": "כל נקודה היא תחנת מוניות; לחיצה פותחת את שם התחנה והכתובת.",
        "dist_note": f"מרחק כל תחנה ממרכז החציון של {fmt(n_geo)} התחנות; החציון {fmt(med_d)} מ׳.",
        "sectors_note": "כמה תחנות נמצאות בכל כיוון ביחס למרכז החציון של התחנות.",
        "nn_note": (f"המרחק מכל תחנה לתחנה הקרובה אליה, מהמבודדת לצפופה; החציון {fmt(med_nn)} מ׳."
                    + (f" מוצגות {fmt(NN_TOP)} התחנות המבודדות ביותר מתוך {fmt(n_geo)}." if nn_more else "")),
        "addr_note": f"עד כמה כתובות התחנות מפורטות, מתוך {fmt(n_st)} תחנות.",
        "list_note": (f"כל {fmt(n_st)} התחנות לפי שם, עם המרחק ממרכז התחנות והתחנה הקרובה ביותר."
                      if n_st <= LIST_CAP else f"{fmt(LIST_CAP)} התחנות הראשונות לפי שם; הרשימה המלאה בטבלת הנתונים."),
        "dist_aria": "תחנות לפי מרחק ממרכז התחנות", "dist_cap": "תחנות לפי מרחק ממרכז התחנות",
        "sectors_aria": "תחנות לפי כיוון מהמרכז", "sectors_cap": "תחנות לפי כיוון מהמרכז",
        "nn_aria": "מרחק כל תחנה לתחנה הקרובה אליה", "nn_cap": "מרחק לתחנה הקרובה",
        "addr_aria": "תחנות לפי פירוט הכתובת", "addr_cap": "תחנות לפי פירוט הכתובת",
        "list_cap": "רשימת תחנות המוניות",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["תחבורה", "מוניות", "באר שבע", "תחבורה ציבורית"],
            "related_ids": [
                "82a30a97-01b0-4281-854c-c7931f3445c0",
                "bdf28cc0-680a-415c-af64-944a58079b2f",
                "3c6d4061-41bf-4403-82e9-c8fae5df04dd",
                "947814b2-f2a8-4f4b-a8ec-a5f4bd2f0abe",
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
