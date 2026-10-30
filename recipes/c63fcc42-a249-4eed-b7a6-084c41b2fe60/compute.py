"""תחנות דלק בבאר שבע: one small point layer (name, address, fuel company, WGS84 lat/lon).

The page reads the CSV resource only; the XLSX and the two ITM resources are
format / projection twins with the same rows.  Rows whose name or company is
"בתכנון" are planned sites, not stations: they are counted and listed, but the
brand, distance and nearest-neighbour views cover operating stations only (the
notes say so).  Company names are shown as listed in the file (the doubled
apostrophe the file uses for gershayim is rendered as ״); co-branded entries
such as "דלק+סד״ש" stay one category, so nothing is guessed about ownership.

Order-independent: dedup on a normalised key, then a total sort; ties broken
by name, address and coordinates.
"""
import math
import re

import pandas as pd

M_PER_DEG = 111320.0
PLANNED = "בתכנון"
NO_BRAND = "לא צוינה"
OTHER = "אחר"
BRAND_TOP = 10
SECTOR_BRANDS = 4
DIST_EDGES = [0, 1000, 2000, 3000, 4000]
NN_EDGES = [0, 100, 250, 500, 1000]
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
NN_TOP = 15
LIST_CAP = 200
HAS_NUMBER = re.compile(r"\d")
ADDR_ORDER = ["רחוב ומספר בית", "רחוב, צומת או תיאור מיקום", "ללא כתובת"]


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def km(m):
    return f"{m / 1000:,.1f}"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def clean(s):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s.replace("''", "״").replace('"', "״")


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
        return ADDR_ORDER[2]
    if HAS_NUMBER.search(a):
        return ADDR_ORDER[0]
    return ADDR_ORDER[1]


def compute(frames):
    raw = frames["stations"].copy()
    n_raw = len(raw)
    df = pd.DataFrame({
        "name": raw["Name"].map(clean),
        "address": raw["ADDRESS"].map(clean),
        "brand": raw["firma"].map(clean),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
    })
    df["kla"] = df["la"].round(6)
    df["klo"] = df["lo"].round(6)
    keys = ["name", "address", "brand", "kla", "klo"]
    uniq = df.drop_duplicates(subset=keys).copy()
    n_dup = n_raw - len(uniq)
    uniq = uniq.sort_values(keys, kind="mergesort", na_position="last").reset_index(drop=True)
    uniq["planned"] = (uniq["name"] == PLANNED) | (uniq["brand"] == PLANNED)
    uniq.loc[uniq["brand"] == "", "brand"] = NO_BRAND
    n_sites = len(uniq)
    n_planned = int(uniq["planned"].sum())
    ops = uniq[~uniq["planned"]].copy().reset_index(drop=True)
    n_ops = len(ops)
    n_nobrand = int((ops["brand"] == NO_BRAND).sum())

    # ---------- brands (operating stations) ----------
    bc = ops.groupby("brand").size().reset_index(name="n")
    bc = bc.sort_values(["n", "brand"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    named = bc[bc["brand"] != NO_BRAND].reset_index(drop=True)
    n_brands = len(named)
    # named brands: top N + other; stations with no company always get their own bar
    head = named.head(BRAND_TOP)
    rest = int(named["n"].iloc[BRAND_TOP:].sum()) if n_brands > BRAND_TOP else 0
    n_nb = int(bc.loc[bc["brand"] == NO_BRAND, "n"].sum())
    b_names = head["brand"].tolist() + ([OTHER] if rest else []) + ([NO_BRAND] if n_nb else [])
    b_vals = [int(v) for v in head["n"]] + ([rest] if rest else []) + ([n_nb] if n_nb else [])

    charts, tables = {}, {}
    charts["brand"] = {"names": b_names, "values": b_vals}
    tables["brand"] = {"headers": ["חברה", "תחנות", "שיעור"],
                       "rows": [[b, fmt(v), pct(v / n_ops)] for b, v in zip(b_names, b_vals)] if n_ops else []}

    # ---------- geometry (operating stations with valid coordinates) ----------
    ok = ops["la"].between(29, 34) & ops["lo"].between(34, 36)
    n_bad_geo = int((~ok).sum())
    geo = ops[ok].copy().reset_index(drop=True)
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

    xs, ys = geo["x"].tolist(), geo["y"].tolist()
    nms, brs = geo["name"].tolist(), geo["brand"].tolist()
    nn_d, nn_name, nn_brand = [], [], []
    for i in range(n_geo):
        best = None
        for j in range(n_geo):
            if i == j:
                continue
            cand = (math.hypot(xs[i] - xs[j], ys[i] - ys[j]), nms[j], brs[j], j)
            if best is None or cand < best:
                best = cand
        nn_d.append(best[0] if best else float("nan"))
        nn_name.append(best[1] if best else "")
        nn_brand.append(best[2] if best else "")
    geo["nn"] = nn_d
    geo["nn_name"] = nn_name
    geo["nn_brand"] = nn_brand
    has_nn = n_geo >= 2
    geo["rival"] = [(a != b) or a == NO_BRAND for a, b in zip(geo["brand"], geo["nn_brand"])]

    # distance from the median centre
    geo["db"] = geo["d"].map(lambda v: band_index(v, DIST_EDGES))
    dl = band_labels(DIST_EDGES)
    dvals = [int((geo["db"] == i).sum()) for i in range(len(DIST_EDGES))]
    charts["dist"] = {"names": dl, "values": dvals}
    tables["dist"] = {"headers": ["מרחק מהמרכז", "תחנות", "שיעור"],
                      "rows": [[l, fmt(v), pct(v / n_geo)] for l, v in zip(dl, dvals)] if n_geo else []}
    med_d = float(geo["d"].median()) if n_geo else 0.0
    within_2k = int((geo["d"] < 2000).sum())

    # compass sector x brand (top brands + other)
    sb = [b for b in named["brand"].head(SECTOR_BRANDS)]
    geo["sb"] = geo["brand"].map(lambda b: b if b in sb else OTHER)
    s_series = []
    for b in sb + [OTHER]:
        vals = [int(((geo["sec"] == i) & (geo["sb"] == b)).sum()) for i in range(len(SECTORS))]
        if sum(vals):
            s_series.append({"name": b, "values": vals})
    svals = [int((geo["sec"] == i).sum()) for i in range(len(SECTORS))]
    charts["sectors"] = {"names": SECTORS, "series": s_series}
    tables["sectors"] = {"headers": ["כיוון מהמרכז"] + [s["name"] for s in s_series] + ["סה״כ"],
                         "rows": [[SECTORS[i]] + [fmt(s["values"][i]) for s in s_series] + [fmt(svals[i])]
                                  for i in range(len(SECTORS))]}

    # nearest-neighbour distance bands, split by same / other company
    nl = band_labels(NN_EDGES)
    geo["nb"] = geo["nn"].map(lambda v: band_index(v, NN_EDGES) if v == v else -1)
    rival_v = [int(((geo["nb"] == i) & geo["rival"]).sum()) for i in range(len(NN_EDGES))]
    same_v = [int(((geo["nb"] == i) & ~geo["rival"]).sum()) for i in range(len(NN_EDGES))]
    charts["nnbands"] = {"names": nl, "rival": rival_v, "same": same_v}
    tables["nnbands"] = {"headers": ["מרחק לתחנה הקרובה", "של חברה אחרת", "של אותה חברה", "סה״כ"],
                         "rows": [[l, fmt(r), fmt(s), fmt(r + s)] for l, r, s in zip(nl, rival_v, same_v)]}
    med_nn = float(geo["nn"].median()) if has_nn else 0.0
    n_rival = int(geo["rival"].sum()) if has_nn else 0
    close_rival = int(((geo["nn"] <= NN_EDGES[1]) & geo["rival"]).sum()) if has_nn else 0

    # most isolated stations
    if has_nn:
        nn_sorted = geo.sort_values(["nn", "name", "address"], ascending=[False, True, True], kind="mergesort")
    else:
        nn_sorted = geo
    top = nn_sorted.head(NN_TOP)
    charts["nn"] = {"names": [f"{a} ({b})" for a, b in zip(top["name"], top["brand"])],
                    "values": [int(round(v)) for v in top["nn"]] if has_nn else []}
    tables["nn"] = {"headers": ["תחנה", "חברה", "התחנה הקרובה", "מרחק (מ׳)"],
                    "rows": [[a, b, c, fmt(d)] for a, b, c, d in
                             zip(top["name"], top["brand"], top["nn_name"], top["nn"])] if has_nn else []}

    # address completeness (all listed sites)
    uniq["ak"] = uniq["address"].map(addr_kind)
    avals = [int((uniq["ak"] == k).sum()) for k in ADDR_ORDER]
    charts["addr"] = {"names": ADDR_ORDER, "values": avals}
    tables["addr"] = {"headers": ["סוג כתובת", "אתרים", "שיעור"],
                      "rows": [[k, fmt(v), pct(v / n_sites)] for k, v in zip(ADDR_ORDER, avals)] if n_sites else []}

    # station list: brand, then name
    gi = {(r["name"], r["address"], r["kla"], r["klo"]): r for _, r in geo.iterrows()}
    lst = uniq.copy()
    lst["ord"] = lst["planned"].astype(int)
    lst = lst.sort_values(["ord", "brand", "name", "address", "kla", "klo"], kind="mergesort").head(LIST_CAP)
    rows = []
    for _, r in lst.iterrows():
        g = gi.get((r["name"], r["address"], r["kla"], r["klo"]))
        brand = "אתר בתכנון" if r["planned"] else r["brand"]
        near = f"{g['nn_name']} ({fmt(g['nn'])} מ׳)" if (g is not None and has_nn) else ""
        rows.append([r["name"], brand, r["address"] or "לא צוינה", near])
    tables["list"] = {"headers": ["תחנה", "חברה", "כתובת", "התחנה הקרובה"], "rows": rows}

    ns_span = float(geo["y"].max() - geo["y"].min()) if n_geo else 0.0
    ew_span = float(geo["x"].max() - geo["x"].min()) if n_geo else 0.0

    # ---------- insights ----------
    insights = []
    if n_brands >= 2:
        lead = named.iloc[0]
        second = named.iloc[1]
        lshare = int(lead["n"]) / n_ops
        if int(lead["n"]) > int(second["n"]):
            top3 = int(named["n"].head(3).sum())
            insights.append({"id": "leader", "text_he": (
                f"״{lead['brand']}״ מפעילה את מספר התחנות הגדול ביותר בעיר: {fmt(lead['n'])} מתוך {fmt(n_ops)} "
                f"התחנות הפעילות ({pct(lshare)}), לפני ״{second['brand']}״ עם {fmt(second['n'])}. "
                f"שלוש החברות הגדולות מחזיקות יחד {fmt(top3)} תחנות ({pct(top3 / n_ops)}).")})
        else:
            tied = named[named["n"] == lead["n"]]["brand"].tolist()
            insights.append({"id": "leader", "text_he": (
                f"אין חברה מובילה אחת: {', '.join('״' + t + '״' for t in tied)} מפעילות כל אחת {fmt(lead['n'])} "
                f"מתוך {fmt(n_ops)} התחנות הפעילות.")})
        singles = named[named["n"] == 1]["brand"].tolist()
        if len(singles) >= 2:
            insights.append({"id": "singles", "text_he": (
                f"לצד החברות הגדולות פועלות בעיר {fmt(n_brands)} חברות ושילובי מותגים שונים, ול־{fmt(len(singles))} "
                f"מהם תחנה אחת בלבד (למשל {', '.join('״' + s + '״' for s in singles[:3])}).")})

    if n_planned:
        insights.append({"id": "planned", "text_he": (
            f"{fmt(n_planned)} מתוך {fmt(n_sites)} האתרים ברשימה מסומנים ״בתכנון״ ולא כתחנות פעילות; "
            f"הם מוצגים במפה וברשימה אך אינם נכללים בחישובי החברות והמרחקים.")})

    if has_nn and n_geo >= 5:
        if close_rival >= 2:
            pair = geo[(geo["nn"] <= NN_EDGES[1]) & geo["rival"]].sort_values(
                ["nn", "name", "address"], kind="mergesort").iloc[0]
            insights.append({"id": "rivals", "text_he": (
                f"{fmt(close_rival)} תחנות פעילות נמצאות עד {fmt(NN_EDGES[1])} מ׳ מתחנה של חברה מתחרה. "
                f"הצמד הקרוב ביותר: ״{pair['name']}״ ({pair['brand']}) ו״{pair['nn_name']}״ ({pair['nn_brand']}), "
                f"כ־{fmt(pair['nn'])} מ׳ זו מזו.")})
        share_r = n_rival / n_geo
        if share_r >= 0.6:
            insights.append({"id": "rivalshare", "text_he": (
                f"אצל {fmt(n_rival)} מתוך {fmt(n_geo)} התחנות ({pct(share_r)}) התחנה הקרובה ביותר שייכת לחברה אחרת: "
                f"החברות אינן מתרכזות באזורים נפרדים אלא ממוקמות זו לצד זו.")})

        iso = nn_sorted.iloc[0]
        ratio = float(iso["nn"]) / med_nn if med_nn > 0 else 0.0
        if ratio >= 2:
            insights.append({"id": "isolated", "text_he": (
                f"התחנה המבודדת ביותר היא ״{iso['name']}״ ({iso['brand']}): התחנה הקרובה אליה, ״{iso['nn_name']}״, "
                f"נמצאת במרחק {km(iso['nn'])} ק״מ, פי {ratio:.1f} מהמרחק החציוני לתחנה הקרובה ({fmt(med_nn)} מ׳).")})

        top_s = max(range(len(SECTORS)), key=lambda i: (svals[i], -i))
        if svals[top_s] / n_geo >= 0.25:
            insights.append({"id": "sector", "text_he": (
                f"הכיוון העמוס ביותר ממרכז התחנות הוא {SECTORS[top_s]}, עם {fmt(svals[top_s])} תחנות "
                f"({pct(svals[top_s] / n_geo)}). התחנות פרושות על פני כ־{km(ns_span)} ק״מ מצפון לדרום "
                f"וכ־{km(ew_span)} ק״מ ממזרח למערב.")})

    if n_nobrand:
        if n_nobrand == 1:
            nm = ops.loc[ops["brand"] == NO_BRAND, "name"].iloc[0]
            txt = f"לתחנה ״{nm}״ לא צוינה החברה המפעילה; היא מופיעה בתרשים החברות תחת ״{NO_BRAND}״."
        else:
            txt = f"ל־{fmt(n_nobrand)} תחנות פעילות לא צוינה החברה המפעילה; הן מופיעות בתרשים החברות תחת ״{NO_BRAND}״."
        insights.append({"id": "nobrand", "text_he": txt})

    if n_dup:
        insights.append({"id": "dups", "text_he": (
            f"הקובץ מכיל {fmt(n_raw)} רשומות, מהן {fmt(n_dup)} כפילויות מלאות; כל החישובים בעמוד נעשים על "
            f"{fmt(n_sites)} האתרים השונים.")})

    if n_bad_geo:
        insights.append({"id": "badgeo", "text_he": (
            f"ל־{fmt(n_bad_geo)} תחנות פעילות אין קואורדינטות תקינות, והן אינן נכללות בחישובי המרחק.")})

    # ---------- kpis ----------
    lead_share = (int(named.iloc[0]["n"]) / n_ops) if (n_brands and n_ops) else 0.0
    kpis = {
        "stations": {"value": n_ops, "display": fmt(n_ops), "tone": "brand", "label": "תחנות דלק פעילות"},
        "brands": {"value": n_brands, "display": fmt(n_brands), "tone": "brand", "label": "חברות ומותגים שונים"},
        "lead": {"value": round(lead_share * 100, 1), "display": pct(lead_share),
                 "tone": "warn" if lead_share >= 0.4 else "info",
                 "label": (f"נתח התחנות של {named.iloc[0]['brand']}" if n_brands else "נתח החברה המובילה")},
        "planned": {"value": n_planned, "display": fmt(n_planned), "tone": "info" if n_planned else "brand",
                    "label": "אתרים בתכנון"},
    }

    lead_txt = (f"״{named.iloc[0]['brand']}״ מובילה עם {fmt(named.iloc[0]['n'])} תחנות" if n_brands else "")
    summary = (
        f"איתור תחנות דלק בבאר שבע לפי שם, כתובת וחברה, על מפה: {fmt(n_ops)} תחנות פעילות"
        + (f", {lead_txt}." if lead_txt else ".")
    )
    lede = (
        f"מאגר תחנות הדלק של עיריית באר שבע: {fmt(n_sites)} אתרים עם שם, כתובת, חברה מפעילה ומיקום, "
        f"מהם {fmt(n_ops)} תחנות פעילות של {fmt(n_brands)} חברות ומותגים"
        + (f" ו־{fmt(n_planned)} אתרים בתכנון" if n_planned else "")
        + f". המרחק החציוני בין תחנה לתחנה הקרובה אליה הוא {fmt(med_nn)} מ׳."
    )
    labels = {
        "lede": lede,
        "map_note": "כל נקודה היא תחנת דלק או אתר בתכנון; לחיצה פותחת את שם התחנה, החברה והכתובת.",
        "brand_note": (f"מספר התחנות הפעילות לכל חברה, כפי ששמה מופיע בקובץ (מותגים משולבים נספרים כקטגוריה אחת)."
                       + (f" מוצגות {fmt(BRAND_TOP)} הגדולות, והשאר תחת ״{OTHER}״." if rest else "")),
        "sectors_note": (f"כמה תחנות פעילות נמצאות בכל כיוון ביחס למרכז החציון של התחנות, לפי חברה "
                         f"({fmt(len(sb))} החברות הגדולות, והשאר תחת ״{OTHER}״)."),
        "dist_note": f"מרחק כל תחנה פעילה ממרכז החציון של {fmt(n_geo)} התחנות; החציון {fmt(med_d)} מ׳.",
        "nnbands_note": (f"המרחק מכל תחנה פעילה לתחנה הפעילה הקרובה אליה, ואם זו שייכת לחברה אחרת או לאותה חברה. "
                         f"החציון {fmt(med_nn)} מ׳."),
        "nn_note": (f"התחנות הפעילות הרחוקות ביותר מתחנה אחרת"
                    + (f" ({fmt(NN_TOP)} מתוך {fmt(n_geo)})" if n_geo > NN_TOP else "") + "."),
        "addr_note": f"עד כמה כתובות האתרים מפורטות, מתוך {fmt(n_sites)} אתרים (כולל אתרים בתכנון).",
        "list_note": (f"כל {fmt(n_sites)} האתרים לפי חברה ושם, עם התחנה הפעילה הקרובה ביותר."
                      if n_sites <= LIST_CAP else f"{fmt(LIST_CAP)} האתרים הראשונים; הרשימה המלאה בטבלת הנתונים."),
        "brand_aria": "תחנות דלק פעילות לפי חברה", "brand_cap": "תחנות דלק לפי חברה",
        "sectors_aria": "תחנות לפי כיוון מהמרכז ולפי חברה", "sectors_cap": "תחנות לפי כיוון ולפי חברה",
        "dist_aria": "תחנות לפי מרחק ממרכז התחנות", "dist_cap": "תחנות לפי מרחק ממרכז התחנות",
        "nnbands_aria": "מרחק לתחנה הקרובה, לפי חברה זהה או מתחרה", "nnbands_cap": "מרחק לתחנה הקרובה",
        "nn_aria": "התחנות המבודדות ביותר", "nn_cap": "התחנות המבודדות ביותר",
        "addr_aria": "אתרים לפי פירוט הכתובת", "addr_cap": "אתרים לפי פירוט הכתובת",
        "list_cap": "רשימת תחנות הדלק",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["תחבורה", "תחנות דלק", "באר שבע", "חברות דלק"],
            "related_ids": [
                "001c72e3-cead-42ac-ac5c-17287aabf285",
                "bdf28cc0-680a-415c-af64-944a58079b2f",
                "54b65747-904e-42e1-9316-0575ebbc1216",
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
        "flags": {"nn": has_nn, "sectors": n_geo >= 5},
    }
