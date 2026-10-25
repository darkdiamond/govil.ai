"""סניפי ברזל — the Ministry of Economy's list of supermarket branches that
stay open during an emergency ("iron branches").

One row per listed branch: the chain (`store`), the branch name, the city,
the street address and ITM coordinates (X = easting, Y = northing, metres).
The list is a snapshot re-published with a fresh `report_date`; there is no
history inside the file, so the page describes the current list.

Normalisation (disclosed on the page):
- chain: a `store` value that starts with another `store` value + space or
  "(" is folded into the shorter one ("שופרסל דיל" -> "שופרסל",
  "היפר כהן (ח. כהן)" -> "היפר כהן"). Generic rule, no hardcoded chain list.
- city: spelling variants that differ only by a doubled yod are merged
  ("קריית"/"קרית", "נהרייה"/"נהריה") and the renamed נצרת עילית is folded into
  נוף הגליל; the most frequent spelling is displayed.
Distances are Euclidean in ITM metres (a conformal grid — good to well
under 1% over Israel). Latitude is a linear approximation from the ITM
northing, used only to place chains on a north–south axis.
"""
import math

import numpy as np
import pandas as pd

TOP_CHAINS = 12
TOP_CITIES = 15
HEAT_CHAINS = 8
HEAT_CITIES = 10
BOX_CHAINS = 10
BOX_MIN = 5
ISOLATED_N = 8
BAND_DEG = 0.2
ISOLATED_KM = 10
CITY_ALIASES = {"נצרת עילית": "נוף הגליל"}
# ITM origin northing and metres per degree of latitude near 31.7°N.
ITM_N0 = 626907.39
ITM_LAT0 = 31.7343936
M_PER_DEG = 110900.0
NN_BUCKETS = [(0, 0.05, "באותה נקודה (עד 50 מ׳)"), (0.05, 0.5, "50 מ׳–0.5 ק״מ"),
              (0.5, 1, "0.5–1 ק״מ"), (1, 2, "1–2 ק״מ"), (2, 5, "2–5 ק״מ"),
              (5, 10, "5–10 ק״מ"), (10, 20, "10–20 ק״מ"), (20, math.inf, "מעל 20 ק״מ")]
CITY_BUCKETS = [(1, 1, "סניף אחד"), (2, 2, "2 סניפים"), (3, 5, "3–5"), (6, 10, "6–10"),
                (11, 20, "11–20"), (21, 10**9, "21 ומעלה")]
CHAINS_CAP = 10


def _int(n):
    return f"{int(n):,}"


def _pct(x):
    return f"{x * 100:.1f}%"


def _km(x):
    return f"{x:.1f}"


def _sorted_counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _chain_roots(store):
    names = sorted(set(store))
    mapping = {}
    for s in names:
        best = s
        for w in names:
            if w != s and (s.startswith(w + " ") or s.startswith(w + "(")) and len(w) < len(best):
                best = w
        mapping[s] = best
    return store.map(mapping)


def _cities(city):
    c = city.map(lambda v: CITY_ALIASES.get(v, v))
    key = c.str.replace("יי", "י", regex=False)
    frame = pd.DataFrame({"key": key, "name": c})
    disp = (frame.groupby(["key", "name"]).size().reset_index(name="n")
            .sort_values(["key", "n", "name"], ascending=[True, False, True], kind="stable")
            .drop_duplicates("key"))
    return key.map(dict(zip(disp["key"], disp["name"])))


def _nearest_km(x, y):
    n = len(x)
    out = np.full(n, np.inf)
    if n < 2:
        return out
    step = 400
    for a in range(0, n, step):
        b = min(n, a + step)
        d = np.hypot(x[a:b, None] - x[None, :], y[a:b, None] - y[None, :])
        d[np.arange(b - a), np.arange(a, b)] = np.inf
        out[a:b] = d.min(axis=1)
    return out / 1000.0


def _prepare(df):
    out = pd.DataFrame({
        "store": df["store"].str.strip(),
        "branch": df["branch"].str.strip(),
        "city_raw": df["city"].str.strip(),
        "address": df["address"].str.replace(r"\s+", " ", regex=True).str.strip(),
        "x": pd.to_numeric(df["X"].str.replace(",", "", regex=False), errors="coerce"),
        "y": pd.to_numeric(df["Y"].str.replace(",", "", regex=False), errors="coerce"),
        "date": pd.to_datetime(df["report_date"].str.strip(), format="%d/%m/%Y", errors="coerce"),
    })
    out = out[out["store"] != ""].copy()
    out["chain"] = _chain_roots(out["store"])
    out["city"] = _cities(out["city_raw"])
    # Plausible ITM box for Israel; anything else is treated as missing.
    ok = out["x"].between(100000, 300000) & out["y"].between(350000, 820000)
    out.loc[~ok, ["x", "y"]] = np.nan
    out["lat"] = ITM_LAT0 + (out["y"] - ITM_N0) / M_PER_DEG
    return out


def _top(vc, n, other):
    head = [(k, int(v)) for k, v in vc.head(n).items()]
    rest = int(vc.iloc[n:].sum())
    if rest:
        head.append((other, rest))
    return head


def _bucket(values, buckets):
    res = []
    for lo, hi, label in buckets:
        res.append((label, int(((values >= lo) & (values <= hi)).sum())))
    return res


# ── insights ────────────────────────────────────────────────────────────

def insight_leader(df, chain_vc):
    n = len(df)
    if n < 20 or len(chain_vc) < 3:
        return None
    top, v = chain_vc.index[0], int(chain_vc.iloc[0])
    if v / n < 0.15:
        return None
    k = min(5, len(chain_vc))
    top_k = int(chain_vc.head(k).sum())
    return (f"{top} היא הרשת עם מספר סניפי הברזל הגבוה ביותר — {_int(v)} סניפים, "
            f"{_pct(v / n)} מהרשימה. {k} הרשתות הגדולות ({', '.join(chain_vc.index[:k])}) "
            f"מחזיקות יחד {_pct(top_k / n)} מהסניפים.")


def insight_cities(df, city_vc):
    if len(city_vc) < 5:
        return None
    top3 = city_vc.head(3)
    share = int(top3.sum()) / len(df)
    parts = ", ".join(f"{k} ({_int(v)})" for k, v in top3.items())
    return (f"היישובים עם מספר הסניפים הגבוה ביותר: {parts} — יחד {_pct(share)} מהסניפים, "
            f"מתוך {_int(len(city_vc))} יישובים ברשימה.")


def insight_single(df, per_city):
    single_chain = per_city[per_city["chains"] == 1]
    single_branch = per_city[per_city["branches"] == 1]
    if len(per_city) < 10 or len(single_chain) < 5:
        return None
    return (f"ב-{_int(len(single_chain))} מתוך {_int(len(per_city))} היישובים "
            f"({_pct(len(single_chain) / len(per_city))}) כל סניפי הברזל שייכים לרשת אחת, "
            f"וב-{_int(len(single_branch))} יישובים יש סניף ברזל אחד בלבד.")


def insight_isolated(iso, nn):
    valid = nn[np.isfinite(nn)]
    if len(valid) < 10 or not iso or iso[0]["km"] < 5:
        return None
    far = int((valid > ISOLATED_KM).sum())
    first = iso[0]
    tail = (f"{_int(far)} סניפים נמצאים במרחק של יותר מ-{ISOLATED_KM} ק״מ מסניף הברזל הקרוב אליהם"
            if far else f"אף סניף אינו רחוק יותר מ-{ISOLATED_KM} ק״מ מסניף הברזל הקרוב אליו")
    return (f"הסניף המבודד ביותר ברשימה הוא {first['chain']} ב{first['city']}: "
            f"סניף הברזל הקרוב אליו נמצא במרחק של כ-{_km(first['km'])} ק״מ בקו אווירי. "
            f"בסך הכול {tail}.")


def insight_dense(nn):
    valid = nn[np.isfinite(nn)]
    if len(valid) < 20:
        return None
    med = float(np.median(valid))
    within = int((valid <= 1).sum())
    return (f"הרשימה צפופה ברובה: לחצי מהסניפים יש סניף ברזל נוסף במרחק של עד "
            f"{_km(med)} ק״מ בקו אווירי, ול-{_pct(within / len(valid))} מהם — "
            f"במרחק של עד ק״מ אחד.")


def insight_regional(box):
    cands = [b for b in box if b["n"] >= 10]
    if len(cands) < 3:
        return None
    narrow = min(cands, key=lambda b: (b["iqr_km"], b["chain"]))
    wide = max(cands, key=lambda b: (b["iqr_km"], b["chain"]))
    if wide["iqr_km"] < 2 * narrow["iqr_km"]:
        return None
    return (f"בין הרשתות עם 10 סניפים ומעלה, סניפי {narrow['chain']} הם המרוכזים ביותר על ציר "
            f"צפון–דרום: מחציתם האמצעית בתוך רצועה של כ-{_int(round(narrow['iqr_km']))} ק״מ "
            f"(סביב {narrow['median_city']}). הרצועה הרחבה ביותר — כ-{_int(round(wide['iqr_km']))} ק״מ — "
            f"היא של {wide['chain']}.")


def insight_dupes(df):
    d = int(df.duplicated(["chain", "address"]).sum())
    if d < 3:
        return None
    return (f"{_int(d)} רשומות חוזרות על כתובת שכבר מופיעה ברשימה עבור אותה רשת — "
            f"ייתכן שמדובר ברישום כפול או בכמה סניפים באותו מתחם. בסך הכול יש ברשימה "
            f"{_int(df['address'].nunique())} כתובות ייחודיות ל-{_int(len(df))} רשומות.")


# ── compute ─────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["branches"])
    n = len(df)
    dates = df["date"].dropna()
    as_of = dates.max() if len(dates) else None
    as_of_he = f"{as_of.day}/{as_of.month}/{as_of.year}" if as_of is not None else ""

    chain_vc = _sorted_counts(df["chain"])
    city_vc = _sorted_counts(df["city"])

    # Chains: branches + cities reached
    chain_cities = df.groupby("chain")["city"].nunique()
    top_chains = list(chain_vc.index[:TOP_CHAINS])
    rest = chain_vc.index[TOP_CHAINS:]
    chains = {
        "names": top_chains + (["שאר הרשתות"] if len(rest) else []),
        "branches": [int(chain_vc[c]) for c in top_chains] + ([int(chain_vc[rest].sum())] if len(rest) else []),
        "cities": [int(chain_cities[c]) for c in top_chains]
        + ([int(df.loc[df["chain"].isin(rest), "city"].nunique())] if len(rest) else []),
    }

    towns = _top(city_vc, TOP_CITIES, "שאר היישובים")
    cities = {"names": [k for k, _ in towns], "values": [v for _, v in towns]}

    per_city = pd.DataFrame({"branches": city_vc,
                             "chains": df.groupby("city")["chain"].nunique()})
    city_size = _bucket(per_city["branches"], CITY_BUCKETS)
    cc = per_city["chains"].clip(upper=CHAINS_CAP).value_counts().sort_index()
    city_chains = {
        "names": [(f"{CHAINS_CAP} ומעלה" if k == CHAINS_CAP else str(int(k))) for k in cc.index],
        "values": [int(v) for v in cc.values],
    }

    # Chain × city heatmap
    hc = list(chain_vc.index[:HEAT_CHAINS])
    hy = list(city_vc.index[:HEAT_CITIES])
    ct = df[df["chain"].isin(hc) & df["city"].isin(hy)].groupby(["city", "chain"]).size()
    cells = []
    for i, cty in enumerate(hy):
        for j, ch in enumerate(hc):
            v = int(ct.get((cty, ch), 0))
            if v:
                cells.append([j, i, v])
    heat = {"x": hc, "y": hy, "cells": cells, "max": max((c[2] for c in cells), default=1)}

    # North–south bands (latitude, approximate)
    geo = df.dropna(subset=["lat"]).copy()
    geo["band"] = np.floor(geo["lat"] / BAND_DEG).astype(int)
    bands = {"names": [], "ranges": [], "values": []}
    if len(geo):
        bcount = geo.groupby("band").size()
        bcity = (geo.groupby(["band", "city"]).size().reset_index(name="n")
                 .sort_values(["band", "n", "city"], ascending=[True, False, True], kind="stable")
                 .drop_duplicates("band").set_index("band")["city"])
        for b in range(int(geo["band"].max()), int(geo["band"].min()) - 1, -1):
            lo, hi = b * BAND_DEG, (b + 1) * BAND_DEG
            bands["names"].append(str(bcity.get(b, "—")))
            bands["ranges"].append(f"{lo:.1f}°–{hi:.1f}°")
            bands["values"].append(int(bcount.get(b, 0)))

    # Chain latitude spread (boxplot)
    box = []
    for ch in chain_vc.index:
        sub = geo[geo["chain"] == ch]
        if len(sub) < BOX_MIN:
            continue
        q = np.percentile(np.sort(sub["lat"].to_numpy()), [0, 25, 50, 75, 100])
        med = float(q[2])
        near = sub.assign(dd=(sub["lat"] - med).abs()).sort_values(["dd", "city"], kind="stable")
        box.append({
            "chain": ch, "n": int(len(sub)), "q": [round(float(v), 3) for v in q],
            "iqr_km": float(q[3] - q[1]) * M_PER_DEG / 1000.0,
            "median_city": str(near["city"].iloc[0]),
            "north_city": str(sub.sort_values(["lat", "city"], ascending=[False, True], kind="stable")["city"].iloc[0]),
            "south_city": str(sub.sort_values(["lat", "city"], kind="stable")["city"].iloc[0]),
        })
        if len(box) >= BOX_CHAINS:
            break
    boxplot = {"names": [b["chain"] for b in box], "data": [b["q"] for b in box],
               "rows": [{"chain": b["chain"], "n": b["n"], "median": f"{b['q'][2]:.2f}°",
                         "iqr": _int(round(b["iqr_km"])), "north": b["north_city"],
                         "south": b["south_city"]} for b in box]}

    # Nearest neighbour
    nn = np.full(n, np.inf)
    gi = df.index.get_indexer(geo.index)
    nn_geo = _nearest_km(geo["x"].to_numpy(), geo["y"].to_numpy())
    nn[gi] = nn_geo
    df["nn"] = nn
    valid = nn[np.isfinite(nn)]
    nn_hist = []
    for lo, hi, label in NN_BUCKETS:
        if lo == 0:
            c = int((valid <= hi).sum())
        else:
            c = int(((valid > lo) & (valid <= hi)).sum())
        nn_hist.append((label, c))
    iso_df = (df[np.isfinite(df["nn"])]
              .sort_values(["nn", "chain", "city", "branch", "address"],
                           ascending=[False, True, True, True, True], kind="stable")
              .head(ISOLATED_N))
    iso = [{"chain": r.chain, "city": r.city, "km": float(r.nn),
            "label": f"{r.chain} · {r.city}"} for r in iso_df.itertuples()]
    isolated = {"names": [i["label"] for i in iso], "values": [round(i["km"], 1) for i in iso]}

    # KPIs
    n_chains = len(chain_vc)
    n_cities = len(city_vc)
    med_nn = float(np.median(valid)) if len(valid) else 0.0
    far = int((valid > ISOLATED_KM).sum())
    top_share = int(chain_vc.iloc[0]) / n if n else 0
    single_city = int((per_city["branches"] == 1).sum())

    rules = [
        ("leader", insight_leader(df, chain_vc)),
        ("cities", insight_cities(df, city_vc)),
        ("single", insight_single(df, per_city)),
        ("isolated", insight_isolated(iso, valid)),
        ("dense", insight_dense(valid)),
        ("regional", insight_regional(box)),
        ("dupes", insight_dupes(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    folded = int((df["store"] != df["chain"]).sum())
    no_geo = int(n - len(geo))
    top_city, top_city_n = city_vc.index[0], int(city_vc.iloc[0])

    return {
        "agent_data": {
            "summary_he": (f"רשימת סניפי הברזל — סניפי רשתות מזון שיישארו פתוחים בשעת חירום: "
                           f"{_int(n)} סניפים של {_int(n_chains)} רשתות ב-{_int(n_cities)} יישובים, "
                           f"נכון ל-{as_of_he}. {chain_vc.index[0]} מחזיקה {_pct(top_share)} מהסניפים."),
            "dataset_kind": "map",
            "suggested_tags": ["סניפי ברזל", "חירום", "רשתות שיווק", "מזון", "צרכנות", "סופרמרקטים"],
            "related_ids": ["8694e2a8-2f9b-416b-a30f-cb9cda4dde4b", "a7e4c07e-8898-414c-91eb-e1f9ed3eb4e6",
                            "013bf5b9-c7ff-4282-b402-73ed20deeacc", "89fbf87e-6bc0-4e26-acc7-a288c31b12a1"],
            "temporal_coverage": as_of.strftime("%Y-%m-%d") if as_of is not None else None,
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "branches": {"value": n, "display": _int(n), "tone": "brand"},
            "chains": {"value": n_chains, "display": _int(n_chains), "tone": "brand"},
            "cities": {"value": n_cities, "display": _int(n_cities), "tone": "brand"},
            "median_nn": {"value": round(med_nn, 2), "display": f"{med_nn:.1f}", "tone": "brand"},
            "far": {"value": far, "display": _int(far), "tone": "warn" if far else "ok"},
            "single_city": {"value": single_city, "display": _int(single_city),
                            "tone": "warn" if single_city else "ok"},
        },
        "charts": {
            "chains": chains,
            "cities": cities,
            "city_size": {"names": [k for k, _ in city_size], "values": [v for _, v in city_size]},
            "city_chains": city_chains,
            "heat": heat,
            "bands": bands,
            "box": {"names": boxplot["names"], "data": boxplot["data"]},
            "nn": {"names": [k for k, _ in nn_hist], "values": [v for _, v in nn_hist]},
            "isolated": isolated,
        },
        "tables": {"box": boxplot["rows"]},
        "insights": insights,
        "labels": {
            "lede": (f"{_int(n)} סניפי רשתות מזון שנקבעו להישאר פתוחים בשעת חירום, של {_int(n_chains)} "
                     f"רשתות ב-{_int(n_cities)} יישובים. הרשימה מתפרסמת מחדש כתמונת מצב; "
                     f"תאריך הדיווח האחרון: {as_of_he}."),
            "as_of": as_of_he,
            "branches_kpi": f"סניפי ברזל ברשימה ({as_of_he})",
            "chains_kpi": "רשתות שיווק",
            "cities_kpi": f"יישובים (המוביל: {top_city}, {_int(top_city_n)} סניפים)",
            "median_nn_kpi": "חציון המרחק לסניף הברזל הקרוב (ק״מ, קו אווירי)",
            "far_kpi": f"סניפים שהסניף הקרוב אליהם רחוק מ-{ISOLATED_KM} ק״מ",
            "single_city_kpi": "יישובים עם סניף ברזל אחד בלבד",
            "map_aria": (f"מפה אינטראקטיבית של {_int(n)} סניפי הברזל. גרסה נגישה: טבלת הנתונים "
                         f"וקובץ הנתונים בתחתית העמוד."),
            "map_note": (f"כל סניפי הרשימה לפי הקואורדינטות המדווחות; לחיצה על נקודה מציגה את הרשת, "
                         f"שם הסניף והכתובת." + (f" ל-{_int(no_geo)} סניפים אין קואורדינטות תקינות."
                                                  if no_geo else "")),
            "chains_note": ("מספר הסניפים ומספר היישובים שבהם פועלת כל רשת. שמות משנה של רשת "
                            f"(כמו תת-מותג או שם עם תוספת) אוחדו לשם הרשת — {_int(folded)} רשומות."),
            "chains_aria": (f"תרשים עמודות: סניפי הברזל לפי רשת, {len(chains['names'])} קטגוריות. "
                            f"{chain_vc.index[0]} מובילה עם {_int(chain_vc.iloc[0])} סניפים."),
            "cities_note": ("וריאציות כתיב של שם יישוב (קריית/קרית) אוחדו."),
            "cities_aria": (f"תרשים עמודות: {len(cities['names'])} היישובים עם מספר הסניפים הגבוה ביותר; "
                            f"{top_city} מובילה עם {_int(top_city_n)}."),
            "city_size_aria": (f"תרשים עמודות: {_int(n_cities)} היישובים לפי מספר סניפי הברזל בהם; "
                               f"ב-{_int(single_city)} יישובים סניף אחד."),
            "city_chains_aria": "תרשים עמודות: מספר היישובים לפי מספר הרשתות השונות הפועלות בהם.",
            "city_chains_note": f"היישובים לפי מספר הרשתות השונות שיש להן בהם סניף ברזל; {CHAINS_CAP} ומעלה מקובצים.",
            "heat_aria": (f"מפת חום: מספר הסניפים של {len(hc)} הרשתות הגדולות ב-{len(hy)} היישובים "
                          f"המובילים."),
            "heat_note": f"{len(hc)} הרשתות הגדולות מול {len(hy)} היישובים עם הכי הרבה סניפים; תא ריק = אין סניף.",
            "bands_aria": (f"תרשים עמודות: סניפי הברזל לפי רצועות רוחב של {BAND_DEG:.1f} מעלות, מצפון לדרום."),
            "bands_note": (f"הארץ מחולקת לרצועות רוחב של {BAND_DEG:.1f} מעלות (כ-{_int(round(BAND_DEG * M_PER_DEG / 1000))} ק״מ), "
                           f"מצפון לדרום; כל רצועה מסומנת ביישוב עם מספר הסניפים הגבוה ביותר בה, וקו מפריד מסמן רצועה ללא סניפים."),
            "box_aria": (f"תרשים קופסה: פיזור סניפי {len(box)} הרשתות הגדולות על ציר צפון–דרום (קו רוחב)."),
            "box_note": (f"קו רוחב משוער של הסניפים בכל רשת עם {BOX_MIN} סניפים לפחות: הקופסה מכסה את "
                         f"מחצית הסניפים האמצעית, והקו בתוכה הוא החציון. קופסה צרה = רשת שסניפיה מרוכזים באזור אחד."),
            "nn_aria": (f"תרשים עמודות: התפלגות המרחק מכל סניף לסניף הברזל הקרוב אליו; החציון "
                        f"{_km(med_nn)} ק״מ."),
            "nn_note": ("המרחק בקו אווירי מכל סניף לסניף הברזל הקרוב אליו ברשימה (מכל רשת). "
                        "מרחק קצר מאוד פירושו סניפים באותו מתחם או ברישום כפול."),
            "isolated_aria": (f"תרשים עמודות: {len(iso)} הסניפים שסניף הברזל הקרוב אליהם רחוק ביותר."
                              + (f" המבודד: {iso[0]['label']}, {_km(iso[0]['km'])} ק״מ." if iso else "")),
            "isolated_note": "הסניפים שהמרחק מהם לסניף הברזל הקרוב (בקו אווירי) הוא הגדול ביותר — שם אין חלופה קרובה.",
        },
    }
