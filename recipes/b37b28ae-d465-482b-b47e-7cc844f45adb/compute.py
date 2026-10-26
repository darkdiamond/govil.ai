"""תוצרים של כלי הרכב הפעילים — the Ministry of Transport make-code lookup table.

One row per make code (tozeret_cd): the full make name (often with the plant's
country appended and truncated), the bare make name (tozar) and the country of
manufacture. There are no vehicle counts here — every figure counts CODES
(make × plant-country entries), not vehicles. The fleet-weighted view lives on
the sibling makes-and-models page (45e317cf).

Codes are allocated in ascending order, so code ranges ("bands") are a rough
proxy for when a make entered the list; the page says "בקירוב" wherever it
leans on that.

Country normalisation (disclosed on the page): spelling variants are merged,
and a blank country is recovered from a known suffix of the full name
("קיה ד. קוריאה") — the same rule the sibling recipe uses. The rest stay
"לא ידוע".
"""
import math

import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"
UNKNOWN = "לא ידוע"

COUNTRY_FIX = {
    'ארהב"': "ארה״ב",
    "תורכיה": "טורקיה",
    "תורקיה": "טורקיה",
    "וייטאנם": "ויטנאם",
    "ד. אפריקה": "דרום אפריקה",
    "ד. קוריאה": "קוריאה הדרומית",
    "": UNKNOWN,
}
COUNTRY_FROM_NAME = [("קוריאה", "קוריאה הדרומית"), ("ד. קורי", "קוריאה הדרומית"),
                     ("ד. אפר", "דרום אפריקה"), ("ד.אפ", "דרום אפריקה")]

REGION = {
    "ישראל": "ישראל",
    "ארה״ב": "צפון אמריקה", "קנדה": "צפון אמריקה", "מקסיקו": "צפון אמריקה",
    "ברזיל": "דרום אמריקה", "ארגנטינה": "דרום אמריקה", "אקוודור": "דרום אמריקה",
    "סין": "מזרח אסיה", "יפן": "מזרח אסיה", "קוריאה הדרומית": "מזרח אסיה",
    "טאיוואן": "מזרח אסיה",
    "הודו": "דרום ודרום־מזרח אסיה", "תאילנד": "דרום ודרום־מזרח אסיה",
    "אינדונזיה": "דרום ודרום־מזרח אסיה", "ויטנאם": "דרום ודרום־מזרח אסיה",
    "טורקיה": "טורקיה",
    "מרוקו": "אפריקה", "מצרים": "אפריקה", "דרום אפריקה": "אפריקה",
    "אוסטרליה": "אוקיאניה", "ניו זילנד": "אוקיאניה",
    UNKNOWN: UNKNOWN,
}
EUROPE = {"בריטניה", "צ. אירלנד", "איטליה", "גרמניה", "ספרד", "צרפת", "הולנד", "פולין",
          "אוסטריה", "בלגיה", "צ'כיה", "רוסיה", "סלובקיה", "פורטוגל", "שבדיה", "הונגריה",
          "דנמרק", "פינלנד", "סלובניה", "סרביה", "רומניה", "אוקראינה", "ליטא", "יוון"}
OTHER_REGION = "אחר"

TOP_COUNTRIES = 15
BAND_COUNTRIES = 3
TOP_BRANDS = 15
MIN_BAND_ROWS = 40     # a code band needs this many makes to anchor a shift rule
SHIFT_PP = 10.0        # min share gain (percentage points) for the shift insight
LOSS_PP = 5.0
MULTI_MIN = 5          # "global brand": entries from at least this many countries


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def pts(v):
    return f"{LRI}{abs(v):.1f}{PDI} נקודות אחוז"


def _cnt(k):
    """'־22 תוצרים' / 'תוצר אחד' — to follow a prefix letter."""
    return f"־{n(k)} תוצרים" if k != 1 else "תוצר אחד"


def _country(country, maker_nm):
    c = country.strip()
    if c == "":
        for frag, name in COUNTRY_FROM_NAME:
            if frag in maker_nm:
                return name, True
    return COUNTRY_FIX.get(c, c), False


def _region(c):
    if c in EUROPE:
        return "אירופה"
    return REGION.get(c, OTHER_REGION)


def _brand(s):
    return " ".join(s.replace("-", " ").split())


def _band_label(lo, hi):
    return f"{lo:,} עד {hi:,}"


def _rank(counts):
    """dict -> list of (name, count) by count desc, name asc."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


# ---------------------------------------------------------------- insights

def insight_leader(ranked, total):
    if len(ranked) < 3:
        return None
    (c1, n1), (c2, n2), (c3, n3) = ranked[:3]
    if c1 == UNKNOWN or n1 <= n2:
        return None
    return (f"{c1} היא ארץ הייצור עם מספר התוצרים הגדול ביותר: {n(n1)} קודי תוצר "
            f"({pct(n1 / total * 100)} מהרשימה), ואחריה {c2} ({n(n2)}) ו{c3} ({n(n3)}).")


def insight_shift(bands):
    full = [b for b in bands if b["total"] >= MIN_BAND_ROWS]
    if len(full) < 2:
        return None
    first, last = full[0], full[-1]
    names = sorted((set(first["counts"]) | set(last["counts"])) - {UNKNOWN})
    if not names:
        return None

    def share(b, c):
        return b["counts"].get(c, 0) / b["total"] * 100

    deltas = sorted(((share(last, c) - share(first, c), c) for c in names),
                    key=lambda t: (-t[0], t[1]))
    gain, gc = deltas[0]
    if gain < SHIFT_PP:
        return None
    text = (f"בטווח הקודים {first['label']} רק {pct(share(first, gc))} מהתוצרים היו מ{gc}; "
            f"בטווח {last['label']}, שנוסף לרשימה מאוחר יותר, חלקה {pct(share(last, gc))} — "
            f"עלייה של {pts(gain)}.")
    loss, lc = min(deltas, key=lambda t: (t[0], t[1]))
    if -loss >= LOSS_PP and lc != gc:
        text += (f" חלקה של {lc} ירד באותה השוואה מ־{pct(share(first, lc))} "
                 f"ל־{pct(share(last, lc))}.")
    return text


def insight_region(region_ranked, total):
    if not region_ranked:
        return None
    r1, n1 = region_ranked[0]
    if r1 in (UNKNOWN, OTHER_REGION) or n1 / total < 0.3:
        return None
    return (f"{r1} מובילה בין האזורים עם {n(n1)} תוצרים — {pct(n1 / total * 100)} מכלל הקודים.")


def insight_global(brand_rows, n_brands):
    if not brand_rows:
        return None
    top = brand_rows[0]
    if top["countries"] < MULTI_MIN:
        return None
    k = sum(1 for r in brand_rows if r["countries"] >= MULTI_MIN)
    return (f"ל{top['name']} יש קודי תוצר מ־{n(top['countries'])} ארצות ייצור שונות — הפריסה הרחבה ביותר ברשימה. "
            f"{n(k)} מותגים רשומים מ־{n(MULTI_MIN)} ארצות או יותר.")


def insight_single(dist, n_brands):
    if n_brands == 0:
        return None
    one = dist.get(1, 0)
    if one / n_brands < 0.5:
        return None
    return (f"רוב המותגים קשורים לארץ ייצור אחת: {n(one)} מתוך {n(n_brands)} "
            f"({pct(one / n_brands * 100)}) מופיעים ברשימה ממדינה אחת בלבד.")


def insight_quality(n_unknown, n_inferred, n_merged, n_nobrand, total):
    parts = []
    if n_unknown:
        parts.append(f"ל{_cnt(n_unknown)} ({pct(n_unknown / total * 100)}) אין ארץ ייצור ידועה")
    if n_inferred:
        parts.append(f"ל{_cnt(n_inferred)} נוספים ארץ הייצור הושלמה משם התוצר" if n_inferred > 1
                     else "לתוצר אחד נוסף ארץ הייצור הושלמה משם התוצר")
    if n_merged:
        parts.append(f"{n(n_merged)} רשומות באיות חלופי של שם מדינה אוחדו" if n_merged > 1
                     else "רשומה אחת באיות חלופי של שם מדינה אוחדה")
    if n_nobrand:
        parts.append(f"ל{_cnt(n_nobrand)} אין שם מותג ללא מדינה, ולכן אינם נספרים בניתוח המותגים")
    if not parts:
        return None
    return "איכות הנתונים: " + "; ".join(parts) + "."


# ---------------------------------------------------------------- compute

def compute(frames):
    df = frames["makes"].copy()
    df["cd"] = pd.to_numeric(df["tozeret_cd"].str.strip(), errors="coerce")
    df = df[df["cd"].notna()].copy()
    df["cd"] = df["cd"].astype(int)
    df = df.sort_values(["cd", "tozeret_nm", "tozar", "tozeret_eretz_nm"], kind="mergesort")
    df = df.drop_duplicates(subset=["cd"], keep="first").reset_index(drop=True)
    total = len(df)

    raw = df["tozeret_eretz_nm"].str.strip()
    res = [_country(c, nm) for c, nm in zip(raw, df["tozeret_nm"])]
    df["country"] = [r[0] for r in res]
    n_inferred = sum(1 for r in res if r[1])
    n_merged = int(sum(1 for c in raw if c in COUNTRY_FIX and c not in ("", 'ארהב"', "לא ידוע")))
    df["region"] = df["country"].map(_region)
    df["brand"] = df["tozar"].map(_brand)

    known = df[df["country"] != UNKNOWN]
    n_unknown = total - len(known)
    country_counts = df["country"].value_counts().to_dict()
    ranked = _rank({k: v for k, v in country_counts.items() if k != UNKNOWN})
    n_countries = len(ranked)

    # --- top countries
    top = ranked[:TOP_COUNTRIES]
    rest = sum(v for _, v in ranked[TOP_COUNTRIES:])
    c_names = [c for c, _ in top] + (["ארצות אחרות"] if rest else [])
    c_vals = [v for _, v in top] + ([rest] if rest else [])
    if n_unknown:
        c_names.append(UNKNOWN)
        c_vals.append(n_unknown)
    countries_tbl = [{"name": a, "count": n(b), "share": f"{b / total * 100:.1f}%"}
                     for a, b in zip(c_names, c_vals)]

    # --- regions
    region_ranked = _rank(df["region"].value_counts().to_dict())
    regions_chart = [{"name": r, "value": v} for r, v in region_ranked]
    region_country_n = known.groupby("region")["country"].nunique().to_dict()
    regions_tbl = [{"name": r, "count": n(v), "share": f"{v / total * 100:.1f}%",
                    "countries": n(region_country_n.get(r, 0))} for r, v in region_ranked]

    # --- code bands
    max_cd = int(df["cd"].max())
    width = max(200, int(math.ceil(max_cd / 10 / 100.0)) * 100)
    df["band"] = (df["cd"] - 1) // width
    band_ids = sorted(df["band"].unique().tolist())
    band_top = [c for c, _ in ranked[:BAND_COUNTRIES]]
    grp = df.groupby(["band", "country"]).size().to_dict()
    bands = []
    for b in band_ids:
        lo, hi = b * width + 1, min((b + 1) * width, max_cd)
        counts = {c: v for (bb, c), v in grp.items() if bb == b}
        bands.append({"label": _band_label(lo, hi), "counts": counts,
                      "total": sum(counts.values())})
    band_series = []
    for c in band_top:
        band_series.append({"name": c, "data": [bd["counts"].get(c, 0) for bd in bands]})
    band_series.append({"name": "אחר / לא ידוע",
                        "data": [bd["total"] - sum(bd["counts"].get(c, 0) for c in band_top)
                                 for bd in bands]})
    band_chart = [{"name": s_["name"], "counts": s_["data"],
                   "data": [round(v / bd["total"] * 100, 1) if bd["total"] else 0
                            for v, bd in zip(s_["data"], bands)]} for s_ in band_series]
    bands_tbl = []
    for i, bd in enumerate(bands):
        bands_tbl.append({"label": bd["label"], "total": n(bd["total"]),
                          "cells": [f"{s['data'][i] / bd['total'] * 100:.0f}%" if bd["total"] else "—"
                                    for s in band_series]})

    # newest anchored band — KPI
    full = [bd for bd in bands if bd["total"] >= MIN_BAND_ROWS] or bands
    last = full[-1]
    lc_rank = _rank({k: v for k, v in last["counts"].items() if k != UNKNOWN})
    lead_c, lead_n = lc_rank[0] if lc_rank else (UNKNOWN, 0)
    lead_share = lead_n / last["total"] * 100 if last["total"] else 0.0
    first_share = (full[0]["counts"].get(lead_c, 0) / full[0]["total"] * 100) if full[0]["total"] else 0.0

    # --- brands
    br = df[df["brand"] != ""]
    n_nobrand = total - len(br)
    brk = br[br["country"] != UNKNOWN]
    b_codes = br.groupby("brand").size().to_dict()
    b_ctry = brk.groupby("brand")["country"].nunique().to_dict()
    brand_rows = sorted(({"name": b, "codes": int(v), "countries": int(b_ctry.get(b, 0))}
                         for b, v in b_codes.items()),
                        key=lambda r: (-r["countries"], -r["codes"], r["name"]))
    n_brands = len(brand_rows)
    top_brands = brand_rows[:TOP_BRANDS]
    brk_g = brk.groupby("brand")["country"].apply(lambda s: sorted(set(s))).to_dict()
    brands_tbl = [{"name": r["name"], "countries": n(r["countries"]), "codes": n(r["codes"]),
                   "list": ", ".join(brk_g.get(r["name"], []))}
                  for r in top_brands]

    # countries-per-brand distribution
    dist = {}
    for r in brand_rows:
        if r["countries"] == 0:
            continue
        dist[r["countries"]] = dist.get(r["countries"], 0) + 1
    n_brands_known = sum(dist.values())
    keys = sorted(dist)
    cap = 8
    d_names, d_vals = [], []
    for k in keys:
        if 1 < k < cap:
            d_names.append(str(k))
            d_vals.append(dist[k])
    over = sum(v for k, v in dist.items() if k >= cap)
    if over:
        d_names.append(f"{cap} ומעלה")
        d_vals.append(over)
    dist_tbl = [{"k": a, "count": n(b)} for a, b in zip(d_names, d_vals)]
    multi_n = sum(d_vals)

    # --- insights
    rules = [
        ("leader", insight_leader(ranked, total)),
        ("shift", insight_shift(bands)),
        ("region", insight_region(region_ranked, total)),
        ("global", insight_global(brand_rows, n_brands)),
        ("single", insight_single(dist, n_brands_known)),
        ("quality", insight_quality(n_unknown, n_inferred, n_merged, n_nobrand, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    top1 = ranked[0] if ranked else (UNKNOWN, 0)
    lede = (f"טבלת הקודים של משרד התחבורה ליצרני כלי הרכב הפעילים: {n(total)} קודי תוצר "
            f"של {n(n_brands)} מותגים מ־{n(n_countries)} ארצות ייצור. כל קוד מייצג צירוף של יצרן "
            f"וארץ ייצור, ולכן מותג אחד יכול להופיע בכמה קודים. {top1[0]} מובילה עם {n(top1[1])} תוצרים. "
            f"הטבלה אינה כוללת מספרי כלי רכב — היא סופרת יצרנים, לא רכבים.")

    summary = (f"{n(total)} קודי תוצר של כלי רכב פעילים — {n(n_brands)} מותגים מ־{n(n_countries)} "
               f"ארצות ייצור; {top1[0]} מובילה עם {n(top1[1])} תוצרים, ובטווח הקודים החדש ביותר "
               f"{lead_c} מובילה עם {pct(lead_share)}.")

    shift_tone = "info"
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "brands": {"value": n_brands, "display": n(n_brands), "tone": "brand"},
        "countries": {"value": n_countries, "display": n(n_countries), "tone": "brand"},
        "newest": {"value": round(lead_share, 1), "display": f"{lead_share:.1f}%",
                   "tone": shift_tone if lead_share - first_share >= SHIFT_PP else "brand"},
    }

    labels = {
        "lede": lede,
        "newest_kpi": f"חלקה של {lead_c} בקודים {last['label']}",
        "countries_note": (f"מספר קודי התוצר לכל ארץ ייצור — {n(TOP_COUNTRIES)} המובילות, "
                           f"והשאר מקובצות. {top1[0]} לבדה: {pct(top1[1] / total * 100)}."),
        "countries_aria": f"תרשים עמודות: מספר התוצרים ב־{n(len(top))} ארצות הייצור המובילות",
        "countries_caption": "מספר קודי תוצר לפי ארץ ייצור",
        "regions_note": (f"קיבוץ ארצות הייצור לאזורים. {region_ranked[0][0]} מרכזת "
                         f"{pct(region_ranked[0][1] / total * 100)} מהתוצרים. טורקיה מוצגת בנפרד."),
        "regions_aria": f"תרשים טבעת: חלוקת התוצרים ל־{n(len(region_ranked))} אזורים",
        "regions_caption": "מספר קודי תוצר לפי אזור",
        "bands_note": (f"הקודים מוקצים בסדר עולה, כך שכל טווח של {n(width)} קודים משקף בקירוב "
                       f"תקופה שבה נוספו יצרנים לרשימה. בטווח {last['label']} {lead_c} מובילה "
                       f"עם {pct(lead_share)}, לעומת {pct(first_share)} בטווח {full[0]['label']}. "
                       f"מוצגות {n(len(band_top))} ארצות הייצור הגדולות, והשאר מקובצות."),
        "bands_aria": f"תרשים עמודות מוערמות באחוזים: ארץ הייצור של התוצרים ב־{n(len(bands))} טווחי קוד",
        "bands_caption": "חלוקת ארצות הייצור בכל טווח קודים, באחוזים",
        "brands_note": (f"מותגים הרשומים מהמספר הגדול ביותר של ארצות ייצור — לפי שם המותג כפי "
                        f"שנרשם. {top_brands[0]['name'] if top_brands else ''} בראש עם "
                        f"{n(top_brands[0]['countries']) if top_brands else n(0)} ארצות."),
        "brands_aria": f"תרשים עמודות: {n(len(top_brands))} המותגים עם מספר ארצות הייצור הגבוה ביותר",
        "brands_caption": "מותגים לפי מספר ארצות הייצור וקודי התוצר",
        "dist_note": (f"בכמה ארצות ייצור רשום כל מותג, מבין {n(multi_n)} המותגים שרשומים מיותר "
                      f"ממדינה אחת. {n(dist.get(1, 0))} מתוך {n(n_brands_known)} המותגים עם ארץ ידועה "
                      f"רשומים ממדינה אחת בלבד ואינם מוצגים."),
        "dist_aria": f"תרשים עמודות: מספר המותגים לפי מספר ארצות הייצור",
        "dist_caption": "מספר המותגים לפי מספר ארצות הייצור",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["כלי רכב", "יצרני רכב", "ארץ ייצור", "תחבורה"],
            "related_ids": [
                "45e317cf-7bb1-4535-b8cf-be5e79ea341f",
                "1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4",
                "392abd0a-64f6-4c18-9d56-0111001411e6",
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
                "0219b34f-43c7-435b-bdfe-e65e944cde50",
            ],
        },
        "kpis": kpis,
        "charts": {
            "countries": {"names": c_names, "values": c_vals},
            "regions": regions_chart,
            "bands": {"x": [bd["label"] for bd in bands], "series": band_chart},
            "brands": {"names": [r["name"] for r in top_brands],
                       "values": [r["countries"] for r in top_brands],
                       "codes": [r["codes"] for r in top_brands]},
            "dist": {"names": d_names, "values": d_vals},
        },
        "tables": {
            "countries": countries_tbl,
            "regions": regions_tbl,
            "bands": bands_tbl,
            "band_cols": [s["name"] for s in band_series],
            "brands": brands_tbl,
            "dist": dist_tbl,
        },
        "insights": insights,
        "labels": labels,
    }
