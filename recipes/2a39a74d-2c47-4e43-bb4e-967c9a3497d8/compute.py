"""מזרקות העיר באר שבע: one small point layer (name, address, YouTube link, WGS84 lat/lon).

The page splits the sites into fountains proper (name starts with מזרקה/מזרקת/
מזרקות) and other water features (an aqueduct, a stream, a pool, a steel mesh),
classifies the LINK column (valid YouTube video, malformed link, none) and then
does geometry over the distinct sites: distance from the median centre,
compass sector, nearest neighbouring site, and address detail.  The other three
resources are format / projection twins (XLSX, ITM) and are not read.

Order-independent: dedup on a normalised key, then a total sort; ties broken
by name, address and coordinates.
"""
import math
import re

import pandas as pd

M_PER_DEG = 111320.0
DIST_EDGES = [0, 1000, 2000, 3000, 4000]
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
NN_TOP = 20
LIST_CAP = 200
HAS_NUMBER = re.compile(r"\d")
YT_ID = re.compile(r"(?:[?&]v=|youtu\.be/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")
KIND_FOUNTAIN = "מזרקה"
KIND_OTHER = "מיצג או אתר מים אחר"
KIND_ORDER = [KIND_FOUNTAIN, KIND_OTHER]
VID_OK = "סרטון וידאו תקין"
VID_BAD = "קישור פגום"
VID_NONE = "ללא סרטון"
VID_ORDER = [VID_OK, VID_BAD, VID_NONE]
ADDR_ORDER = ["רחוב ומספר בית", "רחוב, צומת או כיכר בלבד", "ללא כתובת"]


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


def kind_of(name):
    first = (name or "").strip().split(" ")[0] if (name or "").strip() else ""
    return KIND_FOUNTAIN if first.startswith("מזרק") else KIND_OTHER


def video_of(link):
    link = (link or "").strip()
    if link == "":
        return VID_NONE, ""
    m = YT_ID.search(link)
    if m:
        return VID_OK, m.group(1)
    return VID_BAD, ""


def addr_kind(a):
    a = (a or "").strip()
    if a == "":
        return ADDR_ORDER[2]
    if HAS_NUMBER.search(a):
        return ADDR_ORDER[0]
    return ADDR_ORDER[1]


def compute(frames):
    raw = frames["fountains"].copy()
    n_raw = len(raw)
    df = pd.DataFrame({
        "name": raw["name"].astype(str).str.strip(),
        "address": raw["address"].astype(str).str.strip(),
        "link": raw["LINK"].astype(str).str.strip(),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
    })
    df["kla"] = df["la"].round(6)
    df["klo"] = df["lo"].round(6)
    uniq = df.drop_duplicates(subset=["name", "address", "link", "kla", "klo"]).copy()
    n_dup = n_raw - len(uniq)
    uniq = uniq.sort_values(["name", "address", "kla", "klo", "link"], kind="mergesort", na_position="last").reset_index(drop=True)
    n_st = len(uniq)
    uniq["kind"] = uniq["name"].map(kind_of)
    vid = uniq["link"].map(video_of)
    uniq["vstat"] = [v[0] for v in vid]
    uniq["vid"] = [v[1] for v in vid]
    uniq["ak"] = uniq["address"].map(addr_kind)

    # coordinates outside a broad Israel box are treated as unusable
    okmask = uniq["la"].between(29, 34) & uniq["lo"].between(34, 36)
    n_bad_geo = int((~okmask).sum())
    geo = uniq[okmask].copy().reset_index(drop=True)
    n_geo = len(geo)
    la0 = float(geo["la"].median()) if n_geo else 0.0
    lo0 = float(geo["lo"].median()) if n_geo else 0.0
    coslat = math.cos(math.radians(la0))
    geo["y"] = (geo["la"] - la0) * M_PER_DEG
    geo["x"] = (geo["lo"] - lo0) * M_PER_DEG * coslat
    geo["d"] = (geo["x"] ** 2 + geo["y"] ** 2) ** 0.5

    def sector(x, y):
        ang = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
        return int(((ang + 22.5) % 360.0) // 45.0)
    geo["sec"] = [sector(x, y) for x, y in zip(geo["x"], geo["y"])]

    # nearest neighbour among distinct sites (ties broken by name, then index)
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

    # kind split
    kvals = [int((uniq["kind"] == k).sum()) for k in KIND_ORDER]
    charts["kind"] = {"names": KIND_ORDER, "values": kvals}
    tables["kind"] = {"headers": ["סוג האתר", "אתרים", "שיעור"],
                      "rows": [[k, fmt(v), pct(v / n_st)] for k, v in zip(KIND_ORDER, kvals)]}
    n_fount, n_other = kvals

    # video status, split by kind
    vmat = [[int(((uniq["vstat"] == s) & (uniq["kind"] == k)).sum()) for s in VID_ORDER] for k in KIND_ORDER]
    vtot = [sum(vmat[ki][si] for ki in range(len(KIND_ORDER))) for si in range(len(VID_ORDER))]
    charts["video"] = {"names": VID_ORDER, "series": [{"name": k, "values": vmat[i]} for i, k in enumerate(KIND_ORDER)]}
    tables["video"] = {"headers": ["מצב הקישור"] + KIND_ORDER + ["סה״כ"],
                       "rows": [[s] + [fmt(vmat[ki][si]) for ki in range(len(KIND_ORDER))] + [fmt(vtot[si])]
                                for si, s in enumerate(VID_ORDER)]}
    n_vid, n_badlink, n_novid = vtot

    # distance bands
    geo["db"] = geo["d"].map(lambda v: band_index(v, DIST_EDGES))
    dl = band_labels(DIST_EDGES)
    dvals = [int((geo["db"] == i).sum()) for i in range(len(DIST_EDGES))]
    charts["dist"] = {"names": dl, "values": dvals}
    tables["dist"] = {"headers": ["מרחק מהמרכז", "אתרים", "שיעור"],
                      "rows": [[l, fmt(v), pct(v / n_geo if n_geo else 0)] for l, v in zip(dl, dvals)]}
    med_d = float(geo["d"].median()) if n_geo else 0.0
    within_2k = int((geo["d"] < 2000).sum())

    # sectors
    svals = [int((geo["sec"] == i).sum()) for i in range(len(SECTORS))]
    charts["sectors"] = {"names": SECTORS, "values": svals}
    tables["sectors"] = {"headers": ["כיוון מהמרכז", "אתרים"],
                         "rows": [[s, fmt(v)] for s, v in zip(SECTORS, svals)]}

    # nearest neighbour: most isolated first
    nn_sorted = geo.sort_values(["nn", "name", "address"], ascending=[False, True, True], kind="mergesort") if has_nn else geo
    top = nn_sorted.head(NN_TOP)
    charts["nn"] = {"names": top["name"].tolist(), "values": [int(round(v)) for v in top["nn"]] if has_nn else []}
    tables["nn"] = {"headers": ["אתר", "האתר הקרוב", "מרחק (מ׳)"],
                    "rows": [[a, b, fmt(c)] for a, b, c in zip(top["name"], top["nn_name"], top["nn"])] if has_nn else []}
    nn_more = max(0, n_geo - NN_TOP)
    med_nn = float(geo["nn"].median()) if has_nn else 0.0

    # address detail
    avals = [int((uniq["ak"] == k).sum()) for k in ADDR_ORDER]
    charts["addr"] = {"names": ADDR_ORDER, "values": avals}
    tables["addr"] = {"headers": ["פירוט הכתובת", "אתרים", "שיעור"],
                      "rows": [[k, fmt(v), pct(v / n_st)] for k, v in zip(ADDR_ORDER, avals)]}

    # site list (name order)
    gi = {}
    for _, g in geo.iterrows():
        gi[(g["name"], g["address"], g["kla"], g["klo"], g["link"])] = g
    rows = []
    for _, r in uniq.head(LIST_CAP).iterrows():
        g = gi.get((r["name"], r["address"], r["kla"], r["klo"], r["link"]))
        dist = fmt(g["d"]) if g is not None else ""
        near = (f"{g['nn_name']} ({fmt(g['nn'])} מ׳)" if (g is not None and has_nn) else "")
        rows.append({
            "name": r["name"],
            "kind": r["kind"],
            "address": r["address"] or "לא צוינה",
            "dist": dist,
            "near": near,
            "video": (f"https://www.youtube.com/watch?v={r['vid']}" if r["vid"] else ""),
            "vnote": ("" if r["vid"] else ("קישור פגום" if r["vstat"] == VID_BAD else "")),
        })
    tables["list"] = {"headers": ["אתר", "סוג", "כתובת", "מרחק מהמרכז (מ׳)", "האתר הקרוב", "סרטון"], "rows": rows}

    ns_span = float(geo["y"].max() - geo["y"].min()) if n_geo else 0.0
    ew_span = float(geo["x"].max() - geo["x"].min()) if n_geo else 0.0

    # ---------- insights ----------
    insights = []
    if n_st >= 3 and n_other > 0 and n_fount > 0:
        others = uniq[uniq["kind"] == KIND_OTHER]["name"].tolist()
        ex = "״, ״".join(others[:3])
        insights.append({"id": "kind", "text_he": (
            f"{fmt(n_fount)} מתוך {fmt(n_st)} האתרים ({pct(n_fount / n_st)}) רשומים כמזרקות (שמם מתחיל במילה מזרקה); "
            f"{fmt(n_other)} הנותרים הם מיצגי מים ואתרים אחרים, למשל ״{ex}״.")})

    if n_st >= 3:
        if n_vid > 0:
            tail = ""
            if n_badlink == 1:
                tail = " קישור אחד נוסף פגום ואינו מוביל לסרטון."
            elif n_badlink > 1:
                tail = f" {fmt(n_badlink)} קישורים נוספים פגומים ואינם מובילים לסרטון."
            fv = int(vmat[0][0])
            ov = int(vmat[1][0])
            split = ""
            if n_fount and n_other:
                split = (f" בקרב המזרקות {pct(fv / n_fount)} מתועדות בסרטון, "
                         f"לעומת {pct(ov / n_other)} מהמיצגים והאתרים האחרים.")
            insights.append({"id": "video", "text_he": (
                f"ל־{fmt(n_vid)} אתרים ({pct(n_vid / n_st)}) יש סרטון וידאו ביוטיוב, ול־{fmt(n_novid)} אין סרטון כלל."
                + split + tail)})
        elif n_badlink > 0:
            insights.append({"id": "video", "text_he": (
                f"אף אתר אינו מקושר לסרטון תקין: {fmt(n_badlink)} קישורים פגומים ול־{fmt(n_novid)} אתרים אין קישור.")})

    if n_geo >= 5:
        share = within_2k / n_geo
        lead = (f"{fmt(within_2k)} מתוך {fmt(n_geo)} האתרים ({pct(share)}) נמצאים במרחק של עד {km(2000)} ק״מ "
                f"ממרכז החציון של האתרים" if share >= 0.5 else
                f"האתרים פרושים על פני העיר: רק {fmt(within_2k)} מתוך {fmt(n_geo)} ({pct(share)}) במרחק של עד "
                f"{km(2000)} ק״מ ממרכז החציון")
        insights.append({"id": "centre", "text_he": (
            lead + f", והמרחק החציוני ממנו הוא {km(med_d)} ק״מ. "
            f"הפריסה משתרעת על כ־{km(ns_span)} ק״מ מצפון לדרום ועל כ־{km(ew_span)} ק״מ ממזרח למערב.")})

    if has_nn and n_geo >= 3:
        iso = nn_sorted.iloc[0]
        ratio = float(iso["nn"]) / med_nn if med_nn > 0 else 0.0
        if ratio >= 1.5:
            partner = nn_sorted.iloc[1]
            mutual = (partner["name"] == iso["nn_name"] and partner["nn_name"] == iso["name"]
                      and abs(float(partner["nn"]) - float(iso["nn"])) < 1)
            if mutual:
                a, b = sorted([iso["name"], iso["nn_name"]])
                txt = (f"״{a}״ ו״{b}״ הם הצמד המבודד ביותר: כל אחד מהם הוא האתר הקרוב לשני, במרחק {fmt(iso['nn'])} מ׳, "
                       f"פי {ratio:.1f} מהמרחק החציוני לאתר הקרוב ({fmt(med_nn)} מ׳).")
            else:
                txt = (f"האתר המבודד ביותר הוא ״{iso['name']}״: האתר הקרוב אליו (״{iso['nn_name']}״) נמצא "
                       f"במרחק {fmt(iso['nn'])} מ׳, פי {ratio:.1f} מהמרחק החציוני לאתר הקרוב ({fmt(med_nn)} מ׳).")
            insights.append({"id": "isolated", "text_he": txt})
        close = geo.sort_values(["nn", "name", "address"], kind="mergesort").iloc[0]
        if float(close["nn"]) <= 250:
            a, b = sorted([close["name"], close["nn_name"]])
            n_close = int((geo["nn"] <= 250).sum())
            insights.append({"id": "closest", "text_he": (
                f"הצמד הצפוף ביותר הוא ״{a}״ ו״{b}״, במרחק של כ־{fmt(close['nn'])} מ׳ בלבד זה מזה; "
                f"ל־{fmt(n_close)} אתרים יש אתר שכן במרחק של עד {fmt(250)} מ׳.")})

    if n_geo >= 8:
        top_s = max(range(len(SECTORS)), key=lambda i: (svals[i], -i))
        empty = [SECTORS[i] for i in range(len(SECTORS)) if svals[i] == 0]
        if svals[top_s] / n_geo >= 0.2:
            tail = (f" בכיוון {empty[0]} אין אף אתר." if len(empty) == 1 else
                    (f" ב־{fmt(len(empty))} כיוונים אין אף אתר." if empty else ""))
            insights.append({"id": "sector", "text_he": (
                f"הכיוון העמוס ביותר ממרכז האתרים הוא {SECTORS[top_s]}, עם {fmt(svals[top_s])} אתרים "
                f"({pct(svals[top_s] / n_geo)})." + tail)})

    addr_counts = uniq[uniq["address"] != ""].groupby("address").size()
    shared = addr_counts[addr_counts > 1].sort_index()
    if len(shared) > 0:
        n_sh_sites = int(shared.sum())
        ex = shared.index[0]
        insights.append({"id": "shared", "text_he": (
            f"{fmt(n_sh_sites)} אתרים חולקים כתובת עם אתר אחר "
            + (f"({fmt(len(shared))} כתובות משותפות), " if len(shared) > 1 else "(כתובת משותפת אחת), ")
            + f"למשל ״{ex}״ שבה {fmt(int(shared.iloc[0]))} אתרים; המיקום המדויק של כל אחד מופיע במפה.")})
    elif avals[0] < n_st and n_st >= 3:
        insights.append({"id": "addr", "text_he": (
            f"רק ל־{fmt(avals[0])} מתוך {fmt(n_st)} האתרים יש כתובת עם מספר בית; השאר מתוארים בשם רחוב, צומת או כיכר.")})

    if n_dup:
        insights.append({"id": "dups", "text_he": (
            f"הקובץ מכיל {fmt(n_raw)} רשומות, מהן {fmt(n_dup)} כפילויות מלאות; כל הנתונים בעמוד מחושבים על {fmt(n_st)} האתרים השונים.")})

    if n_bad_geo:
        insights.append({"id": "badgeo", "text_he": (
            f"ל־{fmt(n_bad_geo)} אתרים אין קואורדינטות תקינות, והם אינם נכללים בחישובי המרחק.")})

    # ---------- kpis ----------
    kpis = {
        "sites": {"value": n_st, "display": fmt(n_st), "tone": "brand", "label": "מזרקות ומיצגי מים"},
        "fountains": {"value": n_fount, "display": fmt(n_fount), "tone": "info", "label": "מתוכם מזרקות"},
        "videos": {"value": n_vid, "display": fmt(n_vid), "tone": "ok" if n_st and n_vid / n_st >= 0.5 else "warn",
                   "label": "אתרים עם סרטון וידאו"},
        "nn": {"value": int(round(med_nn)), "display": fmt(med_nn), "tone": "brand",
               "label": "מרחק חציוני לאתר הקרוב (מטרים)"},
    }

    summary = (
        f"מפת המזרקות ומיצגי המים בבאר שבע: איתור לפי שם וכתובת. {fmt(n_st)} אתרים, "
        f"{fmt(n_fount)} מהם מזרקות ו־{fmt(n_vid)} עם סרטון."
    )
    lede = (
        f"מאגר המזרקות של עיריית באר שבע ממפה {fmt(n_st)} מזרקות ומיצגי מים ברחבי העיר, עם שם, כתובת, מיקום "
        f"וקישור לסרטון ליוטיוב לחלק מהם. המרחק החציוני בין אתר לאתר הקרוב אליו הוא {fmt(med_nn)} מ׳, "
        f"והמרחק החציוני ממרכז האתרים הוא {km(med_d)} ק״מ."
    )
    labels = {
        "lede": lede,
        "map_note": "כל נקודה היא מזרקה או מיצג מים; לחיצה פותחת את שם האתר והכתובת.",
        "kind_note": f"סיווג לפי שם האתר: שם שמתחיל במילה מזרקה נספר כמזרקה, והשאר כמיצג או אתר מים אחר. סך הכול {fmt(n_st)} אתרים.",
        "video_note": "האם לאתר יש קישור לסרטון ביוטיוב, לפי סוג האתר.",
        "dist_note": f"מרחק כל אתר ממרכז החציון של {fmt(n_geo)} האתרים; החציון {km(med_d)} ק״מ.",
        "sectors_note": "כמה אתרים נמצאים בכל כיוון ביחס למרכז החציון של האתרים.",
        "nn_note": (f"המרחק מכל אתר לאתר הקרוב אליו, מהמבודד לצפוף; החציון {fmt(med_nn)} מ׳."
                    + (f" מוצגים {fmt(NN_TOP)} האתרים המבודדים ביותר מתוך {fmt(n_geo)}." if nn_more else "")),
        "addr_note": f"עד כמה כתובות האתרים מפורטות, מתוך {fmt(n_st)} אתרים.",
        "list_note": (f"כל {fmt(n_st)} האתרים לפי שם, עם המרחק ממרכז האתרים, האתר הקרוב וקישור לסרטון כשיש."
                      if n_st <= LIST_CAP else f"{fmt(LIST_CAP)} האתרים הראשונים לפי שם; הרשימה המלאה בטבלת הנתונים."),
        "kind_aria": "אתרים לפי סוג", "kind_cap": "אתרים לפי סוג",
        "video_aria": "אתרים לפי מצב קישור הסרטון וסוג האתר", "video_cap": "אתרים לפי מצב קישור הסרטון",
        "dist_aria": "אתרים לפי מרחק ממרכז האתרים", "dist_cap": "אתרים לפי מרחק ממרכז האתרים",
        "sectors_aria": "אתרים לפי כיוון מהמרכז", "sectors_cap": "אתרים לפי כיוון מהמרכז",
        "nn_aria": "מרחק כל אתר לאתר הקרוב אליו", "nn_cap": "מרחק לאתר הקרוב",
        "addr_aria": "אתרים לפי פירוט הכתובת", "addr_cap": "אתרים לפי פירוט הכתובת",
        "list_cap": "רשימת המזרקות ומיצגי המים",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["מזרקות", "באר שבע", "מים", "פנאי", "מרחב ציבורי"],
            "related_ids": [
                "b795e2e0-491e-4040-877e-f3681917f8be",
                "5944b454-751c-4604-94d6-e676d7d34612",
                "d25f8679-13bc-4082-bf6e-6156e1d2df60",
                "82a30a97-01b0-4281-854c-c7931f3445c0",
                "7edbd028-9704-440c-a1b6-a0ed566081bc",
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
