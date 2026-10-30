"""מתקני עגינת אופניים בבאר שבע: one point layer, one row per bike-rack site.

Columns: Address (the place name, e.g. a commercial centre or clinic), sign /
NoSign (stand counts with and without road marking; their sum is the site's
capacity) and WGS84 lat/lon.  The other three resources are an XLSX twin and
two ITM twins (same rows, ITM numbers in the lat/lon columns) and are not read.

The page is about capacity: how stands are spread over sites, sizes and
standard configurations, which kinds of places get racks (keyword classes on
the place name, with an "אחר" fallback so new names always flow through), the
largest sites, how much of the capacity is marked, and the geography (distance
bands and compass sectors from the median site).

Order-independent: every sort is total, with the place name and coordinates
as final tie-breaks.
"""
import math

import pandas as pd

M_PER_DEG = 111320.0
SIZE_BANDS = [(0, 0), (1, 3), (4, 5), (6, 7), (8, 10), (11, 15), (16, None)]
DIST_KM = 1000.0
DIST_MAX_BANDS = 6
TOP_SITES = 12
TOP_CONFIGS = 8
SECTORS = ["צפון", "צפון-מזרח", "מזרח", "דרום-מזרח", "דרום", "דרום-מערב", "מערב", "צפון-מערב"]
NO_NAME = "ללא שם"
OTHER = "אחר"

# (class, keywords) in precedence order; the first match wins.
TYPES = [
    ("בריאות", ["מרפא", "רפואי", "בריאות", "בית החולים", "סורוקה", "פקולטה לרפואה", "מגן דוד", "וטרינר"]),
    ("השכלה גבוהה", ["אוניברסיט", "מכללה", "מכללת", "סטודנט", "בניין המשפטים"]),
    ("בתי ספר וישיבות", ["מקיף", "תיכון", "ישיבה", "ישיבת", "בית ספר", "טכני"]),
    ("ספורט", ["ספורט", "אצטדיון", "סקייט", "טניס", "מגרש", "מתקני משחק"]),
    ("תחבורה", ["רכבת", "תחנה מרכזית", "רכזת", "רציפים", "צומת"]),
    ("מסחר וקניונים", ["מרכז מסחרי", "קניון", "שוק", "סופר", "מול", "מרכז ביג", "מרכז בי ", "בנק", "מלון", "פלאנט"]),
    ("תעסוקה והייטק", ["היי טק", "הי טק", "אזה\"ת", "אזור תעשיה", "אזור תעשייה"]),
    ("קהילה, דת ותרבות", ["מתנ\"ס", "בית הכנסת", "בית חב\"ד", "מועצה דתית", "משכן", "מוזיאון", "קונכיה",
                          "אשכול פיס", "בית הלוחם", "קליטה", "יד שרה", "מבקרים", "בית נועם", "בית שליט"]),
    ("מוסדות ציבור", ["עיריי", "קריית הממשלה", "בית משפט", "מינהל", "תאגיד", "כבאות", "משטרה"]),
    ("פארקים, גנים ורחובות", ["פארק", "גן ", "טיילת", "שצ\"פ", "שדר", "שדרות", "שרות ", "שד ", "כיכר", "מדרחוב", "אצל ", "פינת"]),
    ("מרכזים שכונתיים", ["מרכז"]),
]


def fmt(n):
    return f"{int(round(n)):,}"


def pct(x):
    return f"{x * 100:.1f}%"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def q(name):
    """Quote a place name with Hebrew gershayim, unless it already holds quotes."""
    return name if '"' in name else f"״{name}״"


def classify(name):
    s = (name or "").strip()
    if not s:
        return OTHER
    probe = s + " "
    for cls, kws in TYPES:
        for k in kws:
            if k in probe:
                return cls
    return OTHER


def band_label(lo, hi):
    if hi is None:
        return f"{lo}+"
    if lo == hi:
        return f"{lo}"
    return f"{lo}-{hi}"


def compute(frames):
    raw = frames["racks"]
    df = pd.DataFrame({
        "name": raw["Address"].astype(str).str.strip(),
        "s": num(raw["sign"]).fillna(0).clip(lower=0).round().astype(int),
        "n": num(raw["NoSign"]).fillna(0).clip(lower=0).round().astype(int),
        "la": num(raw["lat"]),
        "lo": num(raw["lon"]),
    })
    df["t"] = df["s"] + df["n"]
    df["label"] = df["name"].where(df["name"] != "", NO_NAME)
    df["kind"] = df["name"].map(classify)
    df = df.sort_values(["name", "la", "lo", "s", "n"], kind="mergesort", na_position="last").reset_index(drop=True)

    n_sites = len(df)
    tot = int(df["t"].sum())
    tot_s = int(df["s"].sum())
    tot_n = int(df["n"].sum())
    share_s = tot_s / tot if tot else 0.0
    active = df[df["t"] > 0]
    n_active = len(active)
    n_empty = n_sites - n_active
    med_size = float(active["t"].median()) if n_active else 0.0
    mean_size = tot / n_active if n_active else 0.0

    charts, tables = {}, {}

    # ---- size distribution ----
    snames, svals, sstands = [], [], []
    for lo, hi in SIZE_BANDS:
        m = (df["t"] >= lo) & ((df["t"] <= hi) if hi is not None else True)
        snames.append(band_label(lo, hi))
        svals.append(int(m.sum()))
        sstands.append(int(df.loc[m, "t"].sum()))
    charts["size"] = {"names": snames, "values": svals}
    tables["size"] = {"headers": ["עמדות במתקן", "מתקנים", "שיעור מהמתקנים", "סך העמדות"],
                      "rows": [[a, fmt(b), pct(b / n_sites if n_sites else 0), fmt(c)] for a, b, c in zip(snames, svals, sstands)]}

    # ---- standard configurations (active sites) ----
    cfg = active.groupby(["s", "n"]).size().reset_index(name="c")
    cfg = cfg.sort_values(["c", "s", "n"], ascending=[False, True, True], kind="mergesort").reset_index(drop=True)
    top_cfg = cfg.head(TOP_CONFIGS)
    rest_cfg = int(cfg["c"].iloc[TOP_CONFIGS:].sum()) if len(cfg) > TOP_CONFIGS else 0
    cnames = [f"{int(r.s)} מסומנות + {int(r.n)} לא מסומנות" for r in top_cfg.itertuples()]
    cvals = [int(v) for v in top_cfg["c"]]
    if rest_cfg:
        cnames.append(f"תצורות אחרות ({fmt(len(cfg) - TOP_CONFIGS)})")
        cvals.append(rest_cfg)
    charts["config"] = {"names": cnames, "values": cvals}
    tables["config"] = {"headers": ["תצורה", "מתקנים", "שיעור מהמתקנים הפעילים"],
                        "rows": [[a, fmt(b), pct(b / n_active if n_active else 0)] for a, b in zip(cnames, cvals)]}
    n_configs = len(cfg)

    # ---- place types ----
    kt = df.groupby("kind").agg(sites=("t", "size"), s=("s", "sum"), n=("n", "sum"), t=("t", "sum")).reset_index()
    kt["other"] = (kt["kind"] == OTHER).astype(int)
    kt = kt.sort_values(["other", "t", "sites", "kind"], ascending=[True, False, False, True], kind="mergesort").reset_index(drop=True)
    charts["types"] = {"names": kt["kind"].tolist(), "s": [int(v) for v in kt["s"]], "n": [int(v) for v in kt["n"]]}
    tables["types"] = {"headers": ["סוג מקום", "מתקנים", "עמדות", "ממוצע למתקן", "מסומנות"],
                       "rows": [[r.kind, fmt(r.sites), fmt(r.t), f"{(r.t / r.sites):.1f}", pct(r.s / r.t if r.t else 0)]
                                for r in kt.itertuples()]}

    # ---- largest sites (aggregated by place name) ----
    named = df[df["name"] != ""]
    sg = named.groupby("name").agg(sites=("t", "size"), s=("s", "sum"), n=("n", "sum"), t=("t", "sum")).reset_index()
    sg = sg[sg["t"] > 0].sort_values(["t", "s", "name"], ascending=[False, False, True], kind="mergesort").reset_index(drop=True)
    top = sg.head(TOP_SITES)
    charts["top"] = {"names": top["name"].tolist(), "s": [int(v) for v in top["s"]], "n": [int(v) for v in top["n"]]}
    tables["top"] = {"headers": ["מקום", "מתקנים", "מסומנות", "לא מסומנות", "סך עמדות"],
                     "rows": [[r.name, fmt(r.sites), fmt(r.s), fmt(r.n), fmt(r.t)] for r in top.itertuples()]}
    multi = sg[sg["sites"] > 1]
    n_multi = len(multi)

    # ---- marked vs unmarked balance per active site ----
    def bal(r):
        if r.s == 0:
            return 0
        if r.n == 0:
            return 4
        if r.s < r.n:
            return 1
        if r.s == r.n:
            return 2
        return 3
    bal_names = ["רק לא מסומנות", "רוב לא מסומנות", "חצי מסומנות", "רוב מסומנות", "רק מסומנות"]
    bals = [bal(r) for r in active.itertuples()]
    bvals = [sum(1 for b in bals if b == i) for i in range(5)]
    charts["balance"] = {"names": bal_names, "values": bvals}
    tables["balance"] = {"headers": ["יחס בין העמדות", "מתקנים", "שיעור מהמתקנים הפעילים"],
                         "rows": [[a, fmt(b), pct(b / n_active if n_active else 0)] for a, b in zip(bal_names, bvals)]}
    n_mostly_unmarked = bvals[0] + bvals[1]

    # ---- geography ----
    geo = df[df["la"].between(29, 34) & df["lo"].between(34, 36)].copy()
    n_geo = len(geo)
    n_bad_geo = n_sites - n_geo
    has_geo = n_geo >= 5
    dist = {"names": [], "sites": [], "stands": []}
    sect = {"names": SECTORS, "values": [0] * len(SECTORS)}
    med_d = 0.0
    within2 = 0
    ns_span = ew_span = 0.0
    if has_geo:
        la0 = float(geo["la"].median())
        lo0 = float(geo["lo"].median())
        coslat = math.cos(math.radians(la0))
        geo["y"] = (geo["la"] - la0) * M_PER_DEG
        geo["x"] = (geo["lo"] - lo0) * M_PER_DEG * coslat
        geo["d"] = (geo["x"] ** 2 + geo["y"] ** 2) ** 0.5
        med_d = float(geo["d"].median())
        ns_span = float(geo["y"].max() - geo["y"].min())
        ew_span = float(geo["x"].max() - geo["x"].min())
        nb = int(min(DIST_MAX_BANDS, max(1, math.ceil(float(geo["d"].max()) / DIST_KM))))
        geo["db"] = (geo["d"] // DIST_KM).astype(int).clip(upper=nb - 1)
        for i in range(nb):
            if i == nb - 1 and nb == DIST_MAX_BANDS:
                dist["names"].append(f"{i}+ ק״מ")
            else:
                dist["names"].append(f"{i}-{i + 1} ק״מ")
            m = geo["db"] == i
            dist["sites"].append(int(m.sum()))
            dist["stands"].append(int(geo.loc[m, "t"].sum()))
        within2 = int(geo.loc[geo["d"] < 2 * DIST_KM, "t"].sum())

        def sector(x, y):
            ang = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
            return int(((ang + 22.5) % 360.0) // 45.0)
        geo["sec"] = [sector(x, y) for x, y in zip(geo["x"], geo["y"])]
        sect["values"] = [int(geo.loc[geo["sec"] == i, "t"].sum()) for i in range(len(SECTORS))]
    charts["dist"] = dist
    charts["sectors"] = sect
    geo_tot = int(geo["t"].sum()) if n_geo else 0
    tables["dist"] = {"headers": ["מרחק מהמרכז", "מתקנים", "עמדות", "שיעור מהעמדות"],
                      "rows": [[a, fmt(b), fmt(c), pct(c / geo_tot if geo_tot else 0)]
                               for a, b, c in zip(dist["names"], dist["sites"], dist["stands"])]}
    tables["sectors"] = {"headers": ["כיוון מהמרכז", "עמדות", "שיעור"],
                         "rows": [[a, fmt(b), pct(b / geo_tot if geo_tot else 0)] for a, b in zip(SECTORS, sect["values"])]}

    # ---- concentration ----
    k10 = max(1, int(math.ceil(n_active * 0.1))) if n_active else 0
    top10_share = (float(active["t"].sort_values(ascending=False, kind="mergesort").head(k10).sum()) / tot) if tot else 0.0

    # ---------- insights ----------
    insights = []
    if tot:
        if share_s < 0.45:
            lead = "רוב העמדות אינן מסומנות"
        elif share_s > 0.55:
            lead = "רוב העמדות מסומנות"
        else:
            lead = "העמדות מתחלקות כמעט שווה בשווה בין מסומנות ללא מסומנות"
        insights.append({"id": "marked", "text_he": (
            f"{lead}: מתוך {fmt(tot)} עמדות עגינה ב־{fmt(n_sites)} מתקנים, {fmt(tot_s)} מסומנות ({pct(share_s)}) "
            f"ו־{fmt(tot_n)} ללא סימון ({pct(1 - share_s)}).")})

    if n_empty > 0 and n_sites:
        insights.append({"id": "empty", "text_he": (
            f"ל־{fmt(n_empty)} מתקנים ({pct(n_empty / n_sites)}) רשומות אפס עמדות, מסומנות ולא מסומנות: "
            f"הם מופיעים במפה אך אינם תורמים לקיבולת. שאר החישובים על גודל המתקן מתייחסים ל־{fmt(n_active)} המתקנים הפעילים.")})

    if n_active >= 10 and len(top_cfg):
        c0 = top_cfg.iloc[0]
        sh = int(c0["c"]) / n_active
        if sh >= 0.2:
            txt = (f"התצורה הנפוצה היא {int(c0['s'])} עמדות מסומנות ועוד {int(c0['n'])} לא מסומנות "
                   f"({fmt(int(c0['s']) + int(c0['n']))} בסך הכול), ב־{fmt(int(c0['c']))} מתקנים ({pct(sh)} מהפעילים)")
            if len(top_cfg) > 1:
                c1 = top_cfg.iloc[1]
                txt += (f"; אחריה {int(c1['s'])} ועוד {int(c1['n'])} ב־{fmt(int(c1['c']))} מתקנים. "
                        f"בסך הכול יש {fmt(n_configs)} תצורות שונות.")
            else:
                txt += "."
            insights.append({"id": "config", "text_he": txt})

    if n_active >= 3 and med_size > 0:
        big = active.sort_values(["t", "s", "name", "la", "lo"], ascending=[False, False, True, True, True], kind="mergesort")
        b0 = big.iloc[0]
        ratio = float(b0["t"]) / med_size
        if ratio >= 2:
            txt = (f"המתקן הגדול ביותר הוא {q(b0['label'])} עם {fmt(int(b0['t']))} עמדות "
                   f"({fmt(int(b0['s']))} מסומנות), פי {ratio:.1f} מהמתקן הפעיל החציוני ({fmt(med_size)} עמדות).")
            if len(sg) >= 2 and int(sg.iloc[0]["sites"]) > 1:
                g0 = int(sg.iloc[0]["t"])
                lead = sg[sg["t"] == g0]
                nm = " ו".join(q(x) for x in lead["name"])
                verb = "מרכזים" if len(lead) > 1 else "מרכז"
                txt += (f" בצירוף מתקנים סמוכים הנושאים אותו שם, {nm} {verb} את מספר העמדות הגבוה ביותר: "
                        f"{fmt(g0)} עמדות.")
            insights.append({"id": "largest", "text_he": txt})

    real = kt[kt["kind"] != OTHER]
    if len(real) >= 2 and tot:
        k0 = real.iloc[0]
        sh = float(k0["t"]) / tot
        if sh >= 0.2:
            k1 = real.iloc[1]
            insights.append({"id": "types", "text_he": (
                f"לפי שם המקום, {k0['kind']} מובילים עם {fmt(int(k0['t']))} עמדות ב־{fmt(int(k0['sites']))} מתקנים "
                f"({pct(sh)} מהקיבולת), ואחריהם {k1['kind']} עם {fmt(int(k1['t']))} עמדות ({pct(float(k1['t']) / tot)}).")})

    if n_active >= 20 and tot:
        if top10_share >= 0.2:
            insights.append({"id": "concentration", "text_he": (
                f"עשירית המתקנים הגדולים ביותר ({fmt(k10)} מתקנים) מחזיקה {pct(top10_share)} מכל העמדות, "
                f"ומתקן פעיל טיפוסי מכיל {fmt(med_size)} עמדות (ממוצע {mean_size:.1f}).")})

    if has_geo and geo_tot:
        sh2 = within2 / geo_tot
        insights.append({"id": "spread", "text_he": (
            f"{pct(sh2)} מהעמדות נמצאות עד {fmt(2)} ק״מ ממרכז הכובד של המתקנים, והמרחק החציוני של מתקן ממנו הוא "
            f"{med_d / 1000:.1f} ק״מ. הפריסה משתרעת על כ־{ns_span / 1000:.1f} ק״מ מצפון לדרום "
            f"ועל כ־{ew_span / 1000:.1f} ק״מ ממזרח למערב.")})

    if n_active >= 10:
        shu = n_mostly_unmarked / n_active
        if shu >= 0.5:
            insights.append({"id": "balance", "text_he": (
                f"ב־{fmt(n_mostly_unmarked)} מתוך {fmt(n_active)} המתקנים הפעילים ({pct(shu)}) מספר העמדות הלא מסומנות "
                f"גדול ממספר המסומנות, ורק ב־{fmt(bvals[3] + bvals[4])} המסומנות הן הרוב.")})

    if n_multi >= 2:
        insights.append({"id": "multi", "text_he": (
            f"{fmt(n_multi)} מקומות מופיעים ביותר ממתקן אחד, למשל {q(multi.sort_values(['sites', 't', 'name'], ascending=[False, False, True], kind='mergesort').iloc[0]['name'])} "
            f"עם {fmt(int(multi['sites'].max()))} מתקנים נפרדים: באותו מקום פזורות כמה נקודות עגינה.")})

    if n_bad_geo:
        insights.append({"id": "badgeo", "text_he": (
            f"ל־{fmt(n_bad_geo)} מתקנים אין קואורדינטות תקינות, והם אינם נכללים במפה ובחישובי המרחק.")})

    # ---------- kpis ----------
    kpis = {
        "sites": {"value": n_sites, "display": fmt(n_sites), "tone": "brand", "label": "מתקני עגינה"},
        "stands": {"value": tot, "display": fmt(tot), "tone": "brand", "label": "עמדות עגינה בסך הכול"},
        "marked": {"value": round(share_s * 100, 1), "display": pct(share_s),
                   "tone": "ok" if share_s >= 0.5 else "warn", "label": "שיעור העמדות המסומנות"},
        "empty": {"value": n_empty, "display": fmt(n_empty), "tone": "warn" if n_empty else "ok",
                  "label": "מתקנים ללא עמדות רשומות"},
    }

    summary = (
        f"איתור חניות ועמדות עגינה לאופניים בבאר שבע לפי מקום, על מפה: {fmt(n_sites)} מתקנים "
        f"עם {fmt(tot)} עמדות, {pct(share_s)} מהן מסומנות."
    )
    lede = (
        f"מאגר מתקני עגינת האופניים (חניות אופניים) של עיריית באר שבע: {fmt(n_sites)} מתקנים עם שם המקום, מיקום "
        f"ומספר העמדות בכל אחד, עם סימון וללא סימון. יחד הם מספקים {fmt(tot)} עמדות, "
        f"ומתקן פעיל טיפוסי מכיל {fmt(med_size)} עמדות."
    )
    labels = {
        "lede": lede,
        "map_note": "כל נקודה היא מתקן עגינה; לחיצה פותחת את שם המקום ואת מספר העמדות המסומנות והלא מסומנות.",
        "size_note": (f"כמה עמדות יש בכל מתקן, מתוך {fmt(n_sites)} מתקנים. החציון בין המתקנים הפעילים: "
                      f"{fmt(med_size)} עמדות."),
        "config_note": (f"צירופי עמדות מסומנות ולא מסומנות החוזרים על עצמם, בין {fmt(n_active)} המתקנים הפעילים "
                        f"({fmt(n_configs)} תצורות שונות)."),
        "types_note": ("סוג המקום מוסק ממילות מפתח בשם המתקן (מרפאה, מתנ״ס, קניון וכו׳); שמות שלא זוהו מסווגים "
                       "כ״אחר״. העמודות מראות את העמדות המסומנות והלא מסומנות."),
        "top_note": (f"המקומות עם הכי הרבה עמדות, אחרי איחוד מתקנים הנושאים אותו שם. מוצגים "
                     f"{fmt(len(top))} מתוך {fmt(len(sg))} מקומות."),
        "balance_note": f"בכל אחד מ־{fmt(n_active)} המתקנים הפעילים: האם רוב העמדות בו מסומנות או לא.",
        "dist_note": (f"מתקנים ועמדות לפי המרחק ממרכז הכובד (החציון) של המתקנים; המרחק החציוני "
                      f"{med_d / 1000:.1f} ק״מ."),
        "sectors_note": "סך העמדות בכל כיוון ביחס למרכז הכובד של המתקנים.",
        "size_aria": "מתקנים לפי מספר העמדות", "size_cap": "התפלגות גודל המתקנים",
        "config_aria": "תצורות העמדות הנפוצות", "config_cap": "תצורות העמדות הנפוצות",
        "types_aria": "עמדות לפי סוג המקום, מסומנות ולא מסומנות", "types_cap": "עמדות לפי סוג המקום",
        "top_aria": "המקומות עם הכי הרבה עמדות עגינה", "top_cap": "המקומות עם הכי הרבה עמדות",
        "balance_aria": "מתקנים לפי היחס בין עמדות מסומנות ללא מסומנות", "balance_cap": "יחס העמדות במתקנים",
        "dist_aria": "מתקנים ועמדות לפי מרחק מהמרכז", "dist_cap": "מתקנים ועמדות לפי מרחק מהמרכז",
        "sectors_aria": "עמדות לפי כיוון מהמרכז", "sectors_cap": "עמדות לפי כיוון מהמרכז",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "map",
            "suggested_tags": ["תחבורה", "אופניים", "חניית אופניים", "באר שבע", "תשתיות עירוניות"],
            "related_ids": [
                "001c72e3-cead-42ac-ac5c-17287aabf285",
                "d25f8679-13bc-4082-bf6e-6156e1d2df60",
                "bdf28cc0-680a-415c-af64-944a58079b2f",
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
        "flags": {"geo": has_geo},
    }
