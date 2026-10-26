"""נקודות מכירה ומחירים מרביים של מוצרי מזון מיובאים — Ministry of Economy.

One row per (point of sale, product): retail points that sell food imported
under the ministry's duty-free quotas, with the maximum consumer price
(incl. VAT) the importer committed to. Today the list covers two yellow-cheese
tracks (sliced at the deli counter / packed in the fridge), five importers and
~870 points; new products, importers and points can be added at any time, so
nothing below hardcodes them.

A point of sale is (point_name, city, address). `point_name` mixes chain and
branch ("רשת חנויות רמי לוי נתניה", "מחסני השוק -אילת"), so a retail chain is
derived from known name prefixes with a cleaned-name fallback for unknown
retailers. Prices are normalised to ₪ per 100 g (`max_price * 100 / weight`).
Every price aggregate uses math.fsum over sorted values, so it does not depend
on row order. Exact duplicate rows are dropped (disclosed in the note).
"""
import math
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"
TOP_CHAINS = 12
TOP_CITIES = 15
MAX_DATES = 24

# Known retail chains: name prefix → chain label (unknown names fall back to
# the cleaned point name itself).
CHAIN_RULES = [
    (r"^(רשת חנויות )?רמי לוי", "רמי לוי"),
    (r"^(מ\.\s*)?יוחננוף", "יוחננוף"),
    (r"^אושר עד", "אושר עד"),
    (r"^מחסני השוק", "מחסני השוק"),
    (r"^קרפור", "קרפור"),
    (r"^שוק העיר", "שוק העיר"),
    (r"^בית הפירות", "בית הפירות"),
    (r"^סופר ספיר", "סופר ספיר"),
    (r"^(סאלח|סלאח) דבאח", "סאלח דבאח"),
    (r"^(מחסני מזון )?חינם פלוס", "חינם פלוס"),
]
LEGAL_SUFFIX = re.compile(r"\s*(בע\"מ|בע״מ|בעמ)\s*$")

CITY_CANON = {
    "תל אביב": "תל אביב-יפו", "הרצלייה": "הרצליה", "נהרייה": "נהריה",
    "ביתר עילית": "בית\"ר עילית", "בורגתה": "בורגתא", "דיר אל-אסד": "דיר אל אסד",
    "טירת כרמל": "טירת הכרמל", "יד בינימין": "יד בנימין", "שער בינימין": "שער בנימין",
    "אירפורט סיטי": "איירפורט סיטי", "מודיעין-מכבים-רע": "מודיעין-מכבים-רעות",
    "מעלות": "מעלות-תרשיחא", "מעלות תרשיחא": "מעלות-תרשיחא", "קדימה צורן": "קדימה-צורן",
    "יוקנעם": "יקנעם עילית", "יקנעם": "יקנעם עילית", "בינימינה": "בנימינה",
    "פרדס חנה": "פרדס חנה-כרכור",
}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def money(v):
    return f"{v:.2f}"


def ils(v):
    return f"{LRI}{v:.2f} ₪{PDI}"


def fmean(vals):
    vals = sorted(vals)
    return math.fsum(vals) / len(vals) if vals else None


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _chain(name):
    for pat, label in CHAIN_RULES:
        if re.search(pat, name):
            return label
    return LEGAL_SUFFIX.sub("", name).strip() or name


def _city(c):
    c = re.sub(r"\s+", " ", c.strip())
    c = re.sub(r"\s*-\s*", "-", c)
    c = re.sub(r"^קרית ", "קריית ", c)
    return CITY_CANON.get(c, c) or "לא צוין"


def _short_products(products):
    """Drop the word prefix every product name shares ("גבינה צהובה …")."""
    if len(products) < 2:
        return {p: p for p in products}
    toks = [p.split() for p in products]
    k = 0
    while all(len(t) > k + 1 for t in toks) and len({t[k] for t in toks}) == 1:
        k += 1
    return {p: " ".join(t[k:]) for p, t in zip(products, toks)}


def _prepare(df):
    out = pd.DataFrame({
        "point_name": df["point_name"].str.strip().str.replace(r"\s+", " ", regex=True),
        "city": df["city"].map(_city),
        "address": df["address"].str.strip().str.replace(r"\s+", " ", regex=True),
        "product": df["product"].str.strip().str.replace(r"\s+", " ", regex=True).replace("", "לא צוין"),
        "importer": df["importer"].str.strip().str.replace(r"\s+", " ", regex=True).replace("", "לא צוין"),
        "price_raw": pd.to_numeric(df["max_price"].str.replace(",", "").str.strip(), errors="coerce"),
        "weight": pd.to_numeric(df["weight"].str.replace(",", "").str.strip(), errors="coerce"),
        "date": pd.to_datetime(df["last_update"].str.strip(), errors="coerce", format="%d/%m/%Y"),
    })
    before = len(out)
    out = out.drop_duplicates(subset=["point_name", "city", "address", "product", "importer",
                                      "price_raw", "weight", "date"]).copy()
    dups = before - len(out)
    ok_w = out["weight"] > 0
    out["price"] = (out["price_raw"] * 100 / out["weight"]).where(ok_w).round(2)
    out["point"] = out["point_name"] + "|" + out["city"] + "|" + out["address"]
    out["chain"] = out["point_name"].map(_chain)
    return out, dups


# ---------- insights ----------
def insight_importer(imp_points, points_n):
    if points_n == 0 or len(imp_points) < 2:
        return None
    lead, c = imp_points.index[0], int(imp_points.iloc[0])
    share = c / points_n
    if share < 0.4:
        return None
    second, c2 = imp_points.index[1], int(imp_points.iloc[1])
    return (f"היבואן «{lead}» מספק את המוצרים ב־{n(c)} מתוך {n(points_n)} נקודות המכירה "
            f"({pct(share * 100)}) — פי {c / c2:.1f} מהיבואן השני, «{second}» ({n(c2)} נקודות).")


def insight_spread(prod_stats, short):
    """The product with the widest gap between its lowest and highest ceiling."""
    cand = [s for s in prod_stats if s["levels"] >= 2 and s["min"] > 0]
    if not cand:
        return None
    s = sorted(cand, key=lambda x: (-(x["max"] / x["min"]), x["product"]))[0]
    gap = (s["max"] / s["min"] - 1) * 100
    if gap < 5:
        return None
    return (f"ב«{short[s['product']]}» התקרה נעה בין {ils(s['min'])} ל־{ils(s['max'])} ל־100 גרם — "
            f"פער של {pct(gap, 0)}: הזולה ביותר אצל {s['min_who']} ({n(s['min_points'])} נקודות), "
            f"והיקרה ביותר אצל {s['max_who']} ({n(s['max_points'])} נקודות).")


def insight_chain_mixed(mixed):
    """Chains whose own branches list different ceilings for the same product."""
    if not mixed:
        return None
    parts = [f"{m['chain']} ({' עד '.join(ils(v) for v in (m['lo'], m['hi']))})" for m in mixed[:3]]
    more = f" ועוד {n(len(mixed) - 3)}" if len(mixed) > 3 else ""
    return (f"באותה רשת התקרה יכולה להשתנות בין סניף לסניף — תלוי באיזה יבואן ובאיזו התחייבות מחיר "
            f"מדובר. כך ב־{n(len(mixed))} רשתות, ובהן " + ", ".join(parts) + more
            + "; כדאי לבדוק את התקרה של הסניף הספציפי.")


def insight_cities(cities, points_n, single_cities):
    if len(cities) < 3 or points_n == 0:
        return None
    lead, c = cities.index[0], int(cities.iloc[0])
    return (f"נקודות המכירה פרוסות ב־{n(len(cities))} יישובים. {lead} מובילה עם {n(c)} נקודות "
            f"({pct(c / points_n * 100)}), וב־{n(single_cities)} יישובים יש נקודת מכירה אחת בלבד.")


def insight_city_cheap(main_short, only_top, city_n, top_price):
    if city_n == 0 or only_top == 0 or only_top / city_n < 0.1:
        return None
    return (f"ב־{n(only_top)} מתוך {n(city_n)} היישובים שבהם נמכר המוצר «{main_short}» "
            f"({pct(only_top / city_n * 100)}) התקרה הנמוכה ביותר הזמינה היא {ils(top_price)} — "
            f"התקרה הגבוהה ברשימה; אין בהם נקודה במחיר מרבי נמוך יותר.")


def insight_both(both, points_n, short_names):
    if points_n == 0 or len(short_names) < 2:
        return None
    share = both / points_n
    if share < 0.05:
        return None
    allp = "את שני המוצרים" if len(short_names) == 2 else f"את כל {n(len(short_names))} המוצרים"
    return (f"{pct(share * 100)} מנקודות המכירה — {n(both)} מתוך {n(points_n)} — מציעות {allp}"
            ": " + " ו".join(f"«{x}»" for x in short_names) + "; השאר מציעות מוצר אחד בלבד.")


def insight_update(upd):
    if upd is None:
        return None
    t = (f"העדכון האחרון ברשימה הוא מ־{upd['last']}; {n(upd['recent_rows'])} רשומות "
         f"({pct(upd['recent_share'] * 100)}) עודכנו לאחרונה ב־{upd['recent_label']}.")
    if upd.get("diff") is not None and abs(upd["diff"]) >= 0.05:
        word = "גבוהה" if upd["diff"] > 0 else "נמוכה"
        t += (f" ב«{upd['product']}», התקרה הממוצעת ברשומות אלה היא {ils(upd['recent_mean'])}, "
              f"{word} ב־{pct(abs(upd['diff']) * 100, 0)} מזו שברשומות שעודכנו קודם ({ils(upd['old_mean'])}).")
    return t


# ---------- compute ----------
def compute(frames):
    df, dups = _prepare(frames["main"])
    rows = len(df)
    pr = df.dropna(subset=["price"])

    points = df.drop_duplicates("point").copy()
    points_n = len(points)

    # Products, ordered by number of points
    prod_points = _sorted_counts(df.drop_duplicates(["point", "product"])["product"])
    products = list(prod_points.index)
    short = _short_products(products)
    main_prod = products[0] if products else ""

    # Importers, by distinct points served
    imp_points = _sorted_counts(df.drop_duplicates(["point", "importer"])["importer"])
    importers = list(imp_points.index)
    ip = df.drop_duplicates(["point", "importer", "product"]).groupby(["importer", "product"]).size()

    # Price levels per product (point-weighted: one point, one product, one price)
    pp = pr.drop_duplicates(["point", "product", "price"])
    levels = sorted(pp["price"].unique().tolist())
    lvl = pp.groupby(["product", "price"]).size()
    lvl_imp = pp.groupby(["product", "price", "importer"]).size()

    prod_stats = []
    for p in products:
        g = pp[pp["product"] == p]
        if g.empty:
            continue
        lo, hi = float(g["price"].min()), float(g["price"].max())

        def who(price):
            sub = g[g["price"] == price]
            imps = _sorted_counts(sub["importer"])
            return " ו".join(f"«{i}»" for i in imps.index[:2]), len(sub)
        lo_who, lo_n = who(lo)
        hi_who, hi_n = who(hi)
        mode = _sorted_counts(g["price"].map(money))
        prod_stats.append({"product": p, "min": lo, "max": hi, "levels": int(g["price"].nunique()),
                           "mean": fmean(g["price"].tolist()), "min_who": lo_who, "min_points": lo_n,
                           "max_who": hi_who, "max_points": hi_n, "mode": mode.index[0],
                           "mode_share": int(mode.iloc[0]) / len(g), "points": len(g)})

    # Importer × product price table
    matrix = []
    for (imp, p), g in pp.groupby(["importer", "product"], sort=True):
        vals = sorted(g["price"].tolist())
        matrix.append({"importer": imp, "product": short[p], "points": n(len(g)),
                       "range": money(vals[0]) if vals[0] == vals[-1] else f"\u2066{money(vals[0])}–{money(vals[-1])}\u2069",
                       "mean": money(fmean(vals)), "_k": (importers.index(imp), products.index(p))})
    matrix.sort(key=lambda r: r["_k"])
    for r in matrix:
        del r["_k"]

    # Chains
    chain_points = _sorted_counts(points["chain"])
    top_ch = list(chain_points.index[:TOP_CHAINS])
    rest_ch_n = int(chain_points.iloc[TOP_CHAINS:].sum())
    cp = df.drop_duplicates(["point", "product"]).groupby(["chain", "product"]).size()
    chain_series = [{"name": short[p], "data": [int(cp.get((c, p), 0)) for c in top_ch]} for p in products]

    # Chain × price level for the main product (100% stacked)
    mp = pp[pp["product"] == main_prod]
    main_levels = sorted(mp["price"].unique().tolist())
    mp_chain = _sorted_counts(mp.drop_duplicates("point")["chain"])
    cp_ch = list(mp_chain.index[:TOP_CHAINS])
    cpl = mp.groupby(["chain", "price"]).size()
    cp_tot = mp.groupby("chain").size()
    cp_series = []
    for v in main_levels:
        cp_series.append({"name": money(v),
                          "data": [round(int(cpl.get((c, v), 0)) / int(cp_tot[c]) * 100, 1) for c in cp_ch]})
    cp_mean = {c: fmean(mp[mp["chain"] == c]["price"].tolist()) for c in cp_ch}

    # Chains whose branches carry ≥2 ceilings for the same product
    mixed = []
    for (c, p), g in pp.groupby(["chain", "product"], sort=True):
        vals = sorted(g["price"].unique().tolist())
        if len(vals) >= 2 and g["point"].nunique() >= 2:
            mixed.append({"chain": c, "product": p, "lo": vals[0], "hi": vals[-1],
                          "points": int(g["point"].nunique())})
    # one entry per chain (widest gap), largest chains first
    best = {}
    for m in mixed:
        cur = best.get(m["chain"])
        if cur is None or (m["hi"] - m["lo"], m["points"]) > (cur["hi"] - cur["lo"], cur["points"]):
            best[m["chain"]] = m
    mixed = sorted(best.values(), key=lambda m: (-int(chain_points.get(m["chain"], 0)), m["chain"]))

    # Cities
    cities = _sorted_counts(points["city"])
    top_c = list(cities.index[:TOP_CITIES])
    rest_c_n = int(cities.iloc[TOP_CITIES:].sum())
    cc = df.drop_duplicates(["point", "product"]).groupby(["city", "product"]).size()
    city_series = [{"name": short[p], "data": [int(cc.get((c, p), 0)) for c in top_c]} for p in products]
    single_cities = int((cities == 1).sum())

    # Cheapest ceiling of the main product available per city
    city_min = mp.groupby("city")["price"].min()
    cm = city_min.value_counts().sort_index()
    cheap_x = [money(v) for v in cm.index]
    cheap_y = [int(v) for v in cm.values]
    top_price = float(mp["price"].max()) if len(mp) else 0.0
    only_top = int((city_min == top_price).sum()) if len(mp) and len(main_levels) >= 2 else 0
    city_main_n = int(len(city_min))

    # Assortment: products per point
    per_point = df.drop_duplicates(["point", "product"]).groupby("point")["product"].apply(
        lambda s: " + ".join(short[p] for p in sorted(s.unique(), key=products.index)))
    assort = _sorted_counts(per_point)
    both = int((df.drop_duplicates(["point", "product"]).groupby("point").size() == len(products)).sum()) \
        if len(products) >= 2 else 0

    # Update dates
    dated = df.dropna(subset=["date"])
    upd = None
    upd_chart = {"x": [], "series": []}
    if len(dated):
        nd = dated["date"].nunique()
        monthly = nd > MAX_DATES
        key = dated["date"].dt.to_period("M").astype(str) if monthly else dated["date"].dt.strftime("%Y-%m-%d")
        dated = dated.assign(k=key)
        ks = sorted(dated["k"].unique().tolist())

        def lbl(k):
            if monthly:
                y, m = k.split("-")
                return f"{m}/{y}"
            y, m, d = k.split("-")
            return f"{d}/{m}/{y}"
        ku = dated.groupby(["k", "importer"]).size()
        upd_chart = {"x": [lbl(k) for k in ks], "monthly": monthly,
                     "series": [{"name": i, "data": [int(ku.get((k, i), 0)) for k in ks]} for i in importers]}
        last = dated["date"].max()
        recent_m = last.to_period("M")
        rec = dated[dated["date"].dt.to_period("M") == recent_m]
        upd = {"last": last.strftime("%d/%m/%Y"), "recent_rows": len(rec), "recent_share": len(rec) / rows,
               "recent_label": f"{recent_m.month:02d}/{recent_m.year}", "product": main_prod}
        r_main = rec[rec["product"] == main_prod]["price"].dropna().tolist()
        o_main = dated[(dated["date"].dt.to_period("M") != recent_m) & (dated["product"] == main_prod)]["price"].dropna().tolist()
        if len(r_main) >= 20 and len(o_main) >= 20 and len(rec) < rows:
            rm, om = fmean(r_main), fmean(o_main)
            upd.update({"recent_mean": rm, "old_mean": om, "diff": rm / om - 1})
        if len(rec) == rows:
            upd = None if nd < 2 else upd

    # ---------- KPIs ----------
    lo_all = float(pp["price"].min()) if len(pp) else 0.0
    hi_all = float(pp["price"].max()) if len(pp) else 0.0
    kpis = {
        "points": {"value": points_n, "display": n(points_n), "tone": "brand"},
        "cities": {"value": int(len(cities)), "display": n(len(cities)), "tone": "brand"},
        "chains": {"value": int(len(chain_points)), "display": n(len(chain_points)), "tone": "brand"},
        "range": {"value": [lo_all, hi_all],
                  "display": money(lo_all) if lo_all == hi_all else f"{money(lo_all)}–{money(hi_all)}",
                  "tone": "brand"},
    }

    # ---------- charts ----------
    charts = {
        "prices": {"x": [money(v) for v in levels],
                   "series": [{"name": short[p], "data": [int(lvl.get((p, v), 0)) or None for v in levels]}
                              for p in products]},
        "importers": {"names": importers,
                      "series": [{"name": short[p], "data": [int(ip.get((i, p), 0)) for i in importers]}
                                 for p in products]},
        "chains": {"names": top_ch, "series": chain_series},
        "chain_price": {"names": cp_ch, "series": cp_series},
        "cities": {"names": top_c, "series": city_series},
        "cheap": {"x": cheap_x, "y": cheap_y,
                  "hl": bool(only_top) and bool(cheap_x) and cheap_x[-1] == money(top_price)},
        "assort": {"names": list(assort.index), "values": [int(v) for v in assort.values]},
        "updates": upd_chart,
    }

    tables = {
        "product_names": [short[p] for p in products],
        "importer_names": importers,
        "prices": [{"price": money(v),
                    "cells": [n(lvl.get((p, v), 0)) for p in products],
                    "who": " · ".join(f"{i} ({n(c)})" for (pp_, vv, i), c in
                                      sorted(lvl_imp.items(), key=lambda x: (-x[1], x[0][2]))
                                      if vv == v)}
                   for v in levels],
        "matrix": matrix,
        "importers": [{"name": i, "cells": [n(ip.get((i, p), 0)) for p in products], "total": n(imp_points[i])}
                      for i in importers],
        "chains": [{"name": c, "cells": [n(cp.get((c, p), 0)) for p in products], "total": n(chain_points[c])}
                   for c in top_ch],
        "chain_price": [{"name": c, "cells": [pct(s["data"][k]) for s in cp_series],
                         "mean": money(cp_mean[c]), "points": n(cp_tot[c])} for k, c in enumerate(cp_ch)],
        "chain_levels": [money(v) for v in main_levels],
        "cities": [{"name": c, "cells": [n(cc.get((c, p), 0)) for p in products], "total": n(cities[c])}
                   for c in top_c],
        "cheap": [{"price": x, "count": n(y)} for x, y in zip(cheap_x, cheap_y)],
        "assort": [{"name": k, "count": n(v), "share": pct(v / points_n * 100)} for k, v in assort.items()],
    }

    # ---------- insights ----------
    insights = [
        ("importer", insight_importer(imp_points, points_n)),
        ("spread", insight_spread(prod_stats, {p: p for p in products})),
        ("chain_mixed", insight_chain_mixed(mixed)),
        ("city_cheap", insight_city_cheap(main_prod, only_top, city_main_n, top_price)),
        ("cities", insight_cities(cities, points_n, single_cities)),
        ("both", insight_both(both, points_n, products)),
        ("update", insight_update(upd)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in insights if t]

    # ---------- labels ----------
    prod_list = ", ".join(f"«{p}»" for p in products)
    lead_imp = importers[0] if importers else ""
    lead_city = top_c[0] if top_c else ""
    lead_chain = top_ch[0] if top_ch else ""
    stats_txt = "; ".join(f"«{short[s['product']]}» — התקרה השכיחה {s['mode']} ₪ "
                          f"({pct(s['mode_share'] * 100, 0)} מהנקודות)" for s in prod_stats)
    labels = {
        "lede": (f"משרד הכלכלה מתיר יבוא של מוצרי מזון במכסות פטורות ממכס, בתנאי שהיבואן מתחייב למחיר מרבי לצרכן. "
                 f"הרשימה מפרטת {n(points_n)} נקודות מכירה ב־{n(len(cities))} יישובים שבהן נמכרים "
                 f"{n(len(products))} מוצרים — {prod_list} — מאת {n(len(importers))} יבואנים, "
                 f"עם המחיר המרבי (כולל מע״מ) לכל נקודה. הדף משווה את התקרות בין יבואנים, רשתות ויישובים."),
        "points_kpi": "נקודות מכירה",
        "cities_kpi": "יישובים",
        "chains_kpi": "רשתות וקמעונאים",
        "range_kpi": "טווח המחיר המרבי (₪ ל־100 גרם, כולל מע״מ)",
        "prices_note": (f"מספר נקודות המכירה בכל רמת מחיר מרבי, לכל מוצר (₪ ל־100 גרם). {stats_txt}. "
                        f"המחיר הוא תקרה — בפועל מותר למכור בזול יותר."),
        "prices_aria": f"נקודות מכירה לפי מחיר מרבי ומוצר; טווח \u2066{kpis['range']['display']}\u2069 ₪ ל־100 גרם",
        "matrix_note": "המחיר המרבי של כל יבואן לכל מוצר — טווח וממוצע על פני נקודות המכירה (₪ ל־100 גרם).",
        "importers_note": (f"מספר נקודות המכירה שכל יבואן מספק להן, לפי מוצר. «{lead_imp}» מספק ל־"
                           f"{n(imp_points.iloc[0]) if len(imp_points) else 0} נקודות."),
        "importers_aria": f"נקודות מכירה לפי יבואן ומוצר; המוביל {lead_imp}",
        "chains_note": (f"הרשת חולצה משם נקודת המכירה. {n(len(top_ch))} הרשתות הגדולות מוצגות; "
                        f"עוד {n(rest_ch_n)} נקודות שייכות ל־{n(max(len(chain_points) - len(top_ch), 0))} "
                        f"רשתות וקמעונאים נוספים."),
        "chains_aria": f"נקודות מכירה לפי רשת ומוצר; המובילה {lead_chain}",
        "chain_price_note": (f"«{short.get(main_prod, '')}»: שיעור הסניפים של כל רשת בכל רמת מחיר מרבי, "
                             f"וממוצע התקרה ברשת. רשת שסניפיה מקבלים את המוצר מיבואנים שונים, או בהתחייבויות "
                             f"מחיר שונות, מציגה כמה רמות."),
        "chain_price_aria": f"שיעור הסניפים בכל רמת מחיר מרבי לפי רשת, עבור {short.get(main_prod, '')}",
        "cities_note": (f"{n(len(top_c))} היישובים עם מספר נקודות המכירה הגבוה ביותר; עוד {n(rest_c_n)} נקודות "
                        f"פזורות ב־{n(max(len(cities) - len(top_c), 0))} יישובים נוספים. שמות יישובים "
                        f"אוחדו בין כתיבים שונים."),
        "cities_aria": f"נקודות מכירה לפי יישוב; המוביל {lead_city}",
        "cheap_note": (f"לכל יישוב שבו נמכר המוצר «{short.get(main_prod, '')}» — המחיר המרבי הנמוך ביותר בין "
                       f"נקודות המכירה בו ({n(city_main_n)} יישובים)."),
        "cheap_aria": f"יישובים לפי המחיר המרבי הנמוך ביותר הזמין בהם עבור {short.get(main_prod, '')}",
        "assort_note": f"אילו מוצרים מציעה כל נקודת מכירה ({n(points_n)} נקודות).",
        "assort_aria": "נקודות מכירה לפי סל המוצרים שהן מציעות",
        "updates_note": (f"מתי עודכנה כל רשומה לאחרונה, לפי יבואן"
                         + (" (לפי חודש)" if upd_chart.get("monthly") else "") + ". "
                         + (f"הוסרו {n(dups)} רשומות כפולות זהות." if dups else "")),
        "updates_aria": "רשומות לפי תאריך העדכון האחרון ויבואן",
    }

    return {
        "agent_data": {
            "summary_he": (f"מחירים מרביים (כולל מע״מ) ונקודות מכירה של מזון מיובא במכסות פטורות ממכס: "
                           f"{n(points_n)} נקודות ב־{n(len(cities))} יישובים, {n(len(products))} מוצרים "
                           f"ו־{n(len(importers))} יבואנים; התקרה נעה בין {money(lo_all)} ל־{money(hi_all)} ₪ "
                           f"ל־100 גרם."),
            "dataset_kind": "registry",
            "related_ids": ["89fbf87e-6bc0-4e26-acc7-a288c31b12a1",
                            "a7e4c07e-8898-414c-91eb-e1f9ed3eb4e6",
                            "b87ef422-0355-4490-9506-d502b71e9b10"],
            "suggested_tags": ["מחירי מזון", "מכסות יבוא", "יבוא מזון", "גבינה צהובה", "פטור ממכס",
                               "רשתות שיווק", "יוקר המחיה"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
