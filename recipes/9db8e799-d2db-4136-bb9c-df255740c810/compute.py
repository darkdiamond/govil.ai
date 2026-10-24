"""יבואנים ומחירוני רכב חדש — the official new-car price list: one row per
importer × model variant × model year, with the importer's list price (₪).

Every row is a price-list ENTRY (a variant offered), not a sale — counts and
medians describe what importers list, weighted by how many variants each
lists, and the page says so. "Now" is the latest model year in the data.

`tozeret_nm` packs brand + country of manufacture with truncated, inconsistent
country spellings ("גרמנ" / "גרמניה", 'ארהב"' / "ארה"); countries are
normalised with ordered prefix rules and the brand is the name minus its
country token. A spelling no rule knows becomes "לא מזוהה" — new spellings
only grow that bucket.
"""
import pandas as pd

YEARS_SHOWN = 20
TREND_YEARS = 10
TOP_BRANDS = 15
TOP_IMPORTERS = 15
TOP_COUNTRIES = 8
MIN_BRAND_ENTRIES = 30
MODELS_SHOWN = 6
LRI, PDI = "⁦", "⁩"
PRICE_BANDS = [(0, 150_000, "עד 150 אלף"), (150_000, 250_000, "150–250 אלף"),
               (250_000, 400_000, "250–400 אלף"), (400_000, 600_000, "400–600 אלף"),
               (600_000, 1_000_000, "600 אלף–מיליון"), (1_000_000, float("inf"), "מעל מיליון")]
# (prefix of the trailing token, country) — first match wins.
COUNTRY_RULES = [
    ("גרמנ", "גרמניה"), ("ארה", "ארה״ב"), ("יפן", "יפן"), ("אנגל", "אנגליה"),
    ("ספרד", "ספרד"), ("צרפת", "צרפת"), ("צ'כ", "צ׳כיה"), ("קוריא", "קוריאה"),
    ("ד.קור", "קוריאה"), ("סין", "סין"), ("טורק", "טורקיה"), ("תורכ", "טורקיה"),
    ("בלגי", "בלגיה"), ("סלוב", "סלובקיה"), ("מקסי", "מקסיקו"), ("איטלי", "איטליה"),
    ("שבדי", "שבדיה"), ("הונג", "הונגריה"), ("תאילנ", "תאילנד"), ("קנד", "קנדה"),
    ("פולי", "פולין"), ("רומני", "רומניה"), ("הולנד", "הולנד"), ("אוסט", "אוסטריה"),
    ("הודו", "הודו"), ("פורטוגל", "פורטוגל"), ("ברזיל", "ברזיל"), ("סלובנ", "סלובניה"),
    ("דרא", "דרום אפריקה"), ("אוסטרל", "אוסטרליה"), ("פינל", "פינלנד"), ("מרוקו", "מרוקו"),
    ("ארגנטינ", "ארגנטינה"), ("טייוו", "טייוואן"), ("ויאטנ", "וייטנאם"), ("אינדונ", "אינדונזיה"),
]
TYPE_HE = {"P": "פרטי", "M": "מסחרי"}


def nis(v):
    return f"{v:,.0f} ₪"


def k_nis(v):
    return f"{v / 1000:,.0f} אלף ₪"


def pct(v, digits=1, signed=False):
    s = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return f"{LRI}{s}%{PDI}"


def num(v, digits=1):
    return f"{LRI}{v:,.{digits}f}{PDI}"


def country_of(token):
    for prefix, name in COUNTRY_RULES:
        if token.startswith(prefix):
            return name
    return None


def split_maker(raw):
    """'מרצדס בנץ גרמנ' → ('מרצדס בנץ', 'גרמניה')."""
    name = " ".join((raw or "").split())
    if not name:
        return "", "לא מזוהה"
    head, _, last = name.rpartition(" ")
    for token in (last, last.split("-")[-1]):
        c = country_of(token.strip('"״'))
        if c:
            brand = head or name
            if "-" in last and token != last:
                brand = (head + " " + last.split("-")[0]).strip()
            return brand, c
    return name, "לא מזוהה"


def _prepare(df):
    out = pd.DataFrame({
        "importer_id": df["semel_yevuan"].str.strip(),
        "importer": df["shem_yevuan"].str.strip().str.replace(" בע\"מ", "", regex=False)
                    .str.replace(" בע״מ", "", regex=False),
        "kind": df["sug_degem"].str.strip().map(TYPE_HE).fillna("אחר"),
        "maker_cd": df["tozeret_cd"].str.strip(),
        "maker": df["tozeret_nm"],
        "model_cd": df["degem_cd"].str.strip(),
        "model_nm": df["degem_nm"].str.strip(),
        "year": pd.to_numeric(df["shnat_yitzur"], errors="coerce"),
        "price": pd.to_numeric(df["mehir"].str.replace(",", "", regex=False), errors="coerce"),
        "trade": df["kinuy_mishari"].str.strip(),
    }).dropna(subset=["year", "price"])
    out = out[out["price"] > 0]
    out["year"] = out["year"].astype(int)
    split = out["maker"].map(split_maker)
    out["brand"] = split.str[0]
    out["country"] = split.str[1]
    # Display name per importer id: most frequent spelling, ties alphabetical.
    names = (out.groupby(["importer_id", "importer"]).size().reset_index(name="n")
                .sort_values(["importer_id", "n", "importer"], ascending=[True, False, True])
                .drop_duplicates("importer_id"))
    out["importer"] = out["importer_id"].map(dict(zip(names["importer_id"], names["importer"])))
    return out.sort_values(["year", "importer_id", "maker_cd", "model_cd", "model_nm", "price"],
                           kind="stable").reset_index(drop=True)


# ── insights ─────────────────────────────────────────────────────────────


def insight_price_trend(med, last, l4l):
    """The median ENTRY moves with the mix of variants listed; the matched
    (like-for-like) change says how much prices of the same variants moved."""
    p = med.get("פרטי")
    if p is None:
        return None
    base = last - 5
    if last not in p.index or base not in p.index or p[base] <= 0:
        return None
    chg = p[last] / p[base] - 1
    word = "עלה" if chg > 0 else "ירד"
    text = (f"המחיר החציוני של רשומה במחירון הרכב הפרטי {word} מ-{nis(p[base])} בשנת הדגם {base} "
            f"ל-{nis(p[last])} בשנת הדגם {last} ({pct(chg * 100, signed=True)})")
    row = l4l.get(last)
    if row and row["matched"] >= 100 and abs(row["mean"]) < abs(chg * 100) / 2:
        text += (f" — בעיקר בגלל שינוי בתמהיל הגרסאות שבמחירון: גרסאות שמופיעות גם בשנת הדגם "
                 f"{last - 1} השתנו במחירן בממוצע ב-{pct(row['mean'], signed=True)}")
    return text + "."


def insight_like4like(l4l, last):
    row = l4l.get(last)
    if not row or row["matched"] < 100:
        return None
    text = (f"מבין {row['matched']:,} גרסאות שמופיעות במחירון גם בשנת הדגם {last - 1} וגם ב-{last}, "
            f"{pct(row['same'])} נשארו באותו מחיר, {pct(row['up'])} התייקרו ו-{pct(row['down'])} "
            f"הוזלו")
    prev = l4l.get(last - 1)
    if prev and row["same"] - prev["same"] >= 15:
        text += (f" — שיעור חריג של מחירים ללא שינוי (לעומת {pct(prev['same'])} בשנה הקודמת), "
                 f"שעשוי לשקף עדכון מחירים שנתי שטרם התפרסם")
    return text + "."


def insight_china(cshare, last):
    s = cshare.get("סין")
    if s is None or last not in s.index:
        return None
    base = last - 5
    then = s.get(base, 0.0)
    now = s[last]
    if now < 2:
        return None
    if now - then < 2:
        return f"דגמים מתוצרת סין מהווים {pct(now)} מהמחירון בשנת הדגם {last}."
    return (f"משקל הדגמים מתוצרת סין במחירון זינק מ-{pct(then)} בשנת הדגם {base} ל-{pct(now)} "
            f"בשנת הדגם {last}.")


def insight_brands(brand_med):
    if len(brand_med) < 3:
        return None
    hi = brand_med.sort_values(ascending=False, kind="stable")
    return (f"בין המותגים עם {MIN_BRAND_ENTRIES} רשומות לפחות בשנת הדגם האחרונה, המחיר החציוני "
            f"הגבוה ביותר — {nis(hi.iloc[0])} — ב{hi.index[0]}, והנמוך ביותר — {nis(hi.iloc[-1])} — "
            f"ב{hi.index[-1]}.")


def insight_importer(imp_counts):
    if imp_counts.empty:
        return None
    tot = imp_counts.sum()
    top = imp_counts.index[0]
    share = imp_counts.iloc[0] / tot
    top5 = imp_counts.head(5).sum() / tot
    return (f"{top} מחזיקה את המחירון הרחב ביותר בשנת הדגם האחרונה — {imp_counts.iloc[0]:,} "
            f"רשומות ({pct(share * 100)}); חמשת היבואנים הגדולים יחד — {pct(top5 * 100)}.")


def insight_luxury(cur_p):
    if len(cur_p) < 100:
        return None
    share = (cur_p["price"] >= 1_000_000).mean()
    under = (cur_p["price"] < 150_000).mean()
    return (f"בשנת הדגם האחרונה {pct(share * 100)} מרשומות הרכב הפרטי מתומחרות במיליון ₪ ומעלה, "
            f"ו-{pct(under * 100)} בלבד מתחת ל-150 אלף ₪.")


def insight_commercial(med, last):
    p, m = med.get("פרטי"), med.get("מסחרי")
    if p is None or m is None or last not in p.index or last not in m.index:
        return None
    gap = m[last] / p[last] - 1
    if abs(gap) < 0.05:
        return (f"המחיר החציוני של רכב מסחרי ({nis(m[last])}) דומה לזה של רכב פרטי בשנת הדגם "
                f"{last}.")
    word = "גבוה" if gap > 0 else "נמוך"
    return (f"המחיר החציוני של רשומת רכב מסחרי ({nis(m[last])}) {word} ב-{pct(abs(gap) * 100)} "
            f"מזה של רכב פרטי ({nis(p[last])}) בשנת הדגם {last}.")


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    df = _prepare(frames["prices"])
    last = int(df["year"].max())
    first_shown = last - YEARS_SHOWN + 1
    cur = df[df["year"] == last]
    cur_p = cur[cur["kind"] == "פרטי"]

    med = {k: g.groupby("year")["price"].median().sort_index() for k, g in df.groupby("kind")}
    cnt = df.pivot_table(index="year", columns="kind", values="price", aggfunc="count").fillna(0)
    years = [y for y in range(first_shown, last + 1) if y in cnt.index]
    kinds = [k for k in ("פרטי", "מסחרי") if k in cnt.columns]

    recent = df[df["year"] > last - TREND_YEARS]
    c = recent.pivot_table(index="year", columns="country", values="price", aggfunc="count").fillna(0)
    cshare_all = c.div(c.sum(axis=1), axis=0) * 100
    top_c = list(c.sum().sort_index().sort_values(ascending=False, kind="stable").head(TOP_COUNTRIES).index)
    cshare = cshare_all[top_c].copy()
    cshare["אחר"] = 100 - cshare.sum(axis=1)

    bcount = cur.groupby("brand").size().sort_index().sort_values(ascending=False, kind="stable")
    top_b = list(bcount.head(TOP_BRANDS).index)
    bmed = cur.groupby("brand")["price"].median()
    brand_rows = [(b, int(bcount[b]), float(bmed[b])) for b in top_b]
    big_brands = bmed[bcount[bcount >= MIN_BRAND_ENTRIES].index]

    imp = cur.groupby("importer").size().sort_index().sort_values(ascending=False, kind="stable")
    imp_brands = cur.groupby("importer")["brand"].nunique()
    top_i = imp.head(TOP_IMPORTERS)

    bands = []
    for lo, hi, label in PRICE_BANDS:
        n = int(((cur_p["price"] >= lo) & (cur_p["price"] < hi)).sum())
        bands.append((label, n))

    # Popular trade names with the longest run across the trend window.
    tw = df[(df["year"] > last - TREND_YEARS) & (df["kind"] == "פרטי") & (df["trade"] != "")]
    cover = tw.groupby("trade").agg(years=("year", "nunique"), n=("price", "size"))
    cover = cover.reset_index().sort_values(["years", "n", "trade"], ascending=[False, False, True])
    picks = list(cover["trade"].head(MODELS_SHOWN))
    mt = tw[tw["trade"].isin(picks)].groupby(["trade", "year"])["price"].median()
    trend_years = list(range(last - TREND_YEARS + 1, last + 1))

    # Like-for-like: the same importer × maker × model code × variant listed
    # in consecutive model years.
    key = ["importer_id", "maker_cd", "model_cd", "model_nm"]
    vp = df.groupby(key + ["year"])["price"].median().reset_index()
    l4l = {}
    for y in range(last - TREND_YEARS + 1, last + 1):
        a = vp[vp["year"] == y - 1].set_index(key)["price"]
        b = vp[vp["year"] == y].set_index(key)["price"]
        j = a.to_frame("a").join(b.to_frame("b"), how="inner")
        if j.empty:
            continue
        ch = (j["b"] / j["a"] - 1) * 100
        l4l[y] = {"matched": int(len(j)), "up": float((ch > 0.05).mean() * 100),
                  "same": float((ch.abs() <= 0.05).mean() * 100),
                  "down": float((ch < -0.05).mean() * 100), "mean": float(ch.mean())}

    china = cur[cur["country"] == "סין"].groupby("brand").size().sort_index().sort_values(ascending=False, kind="stable")

    rules = [
        ("price_trend", insight_price_trend(med, last, l4l)),
        ("like4like", insight_like4like(l4l, last)),
        ("china", insight_china({c: cshare_all[c] for c in ("סין",) if c in cshare_all.columns}, last)),
        ("brands", insight_brands(big_brands)),
        ("importer", insight_importer(imp)),
        ("luxury", insight_luxury(cur_p)),
        ("commercial", insight_commercial(med, last)),
    ]
    insights = [{"id": k, "text_he": v} for k, v in rules if v]

    p_med = med.get("פרטי")
    kpis = {
        "entries": {"value": int(len(df)), "display": f"{len(df):,}"},
        "last_year": {"value": last, "display": str(last)},
        "current": {"value": int(len(cur)), "display": f"{len(cur):,}"},
        "importers": {"value": int(imp.size), "display": f"{imp.size:,}"},
        "median_private": {"value": None if p_med is None or last not in p_med.index else float(p_med[last]),
                           "display": "—" if p_med is None or last not in p_med.index else k_nis(p_med[last])},
    }

    charts = {
        "median": {"x": [str(y) for y in years],
                   "series": [{"name": k, "data": [round(float(med[k][y])) if y in med[k].index else None
                                                   for y in years]} for k in kinds]},
        "counts": {"x": [str(y) for y in years],
                   "series": [{"name": k, "data": [int(cnt.loc[y, k]) for y in years]} for k in kinds]},
        "country": {"x": [str(y) for y in cshare.index],
                    "series": [{"name": col, "data": [round(float(v), 1) for v in cshare[col]]}
                               for col in cshare.columns]},
        "brands": {"names": [b for b, _, _ in brand_rows],
                   "median": [round(m / 1000) for _, _, m in brand_rows],
                   "count": [n for _, n, _ in brand_rows]},
        "importers": {"names": list(top_i.index), "values": [int(v) for v in top_i.values]},
        "bands": {"names": [b for b, _ in bands], "values": [n for _, n in bands]},
        "models": {"x": [str(y) for y in trend_years],
                   "series": [{"name": t, "data": [round(float(mt[(t, y)]) / 1000) if (t, y) in mt.index
                                                   else None for y in trend_years]} for t in picks]},
        "l4l": {"x": [str(y) for y in sorted(l4l)],
                "up": [round(l4l[y]["up"], 1) for y in sorted(l4l)],
                "same": [round(l4l[y]["same"], 1) for y in sorted(l4l)],
                "down": [round(l4l[y]["down"], 1) for y in sorted(l4l)],
                "mean": [round(l4l[y]["mean"], 2) for y in sorted(l4l)]},
        "china": {"names": list(china.head(TOP_BRANDS).index),
                  "values": [int(v) for v in china.head(TOP_BRANDS).values]},
    }

    tables = {
        "years": [{"year": str(y),
                   **{f"med_{i}": (nis(med[k][y]) if y in med[k].index else "—") for i, k in enumerate(kinds)},
                   **{f"n_{i}": f"{int(cnt.loc[y, k]):,}" for i, k in enumerate(kinds)}}
                  for y in years],
        "kinds": kinds,
        "country": [{"year": str(y), "cells": [num(cshare.loc[y, col]) for col in cshare.columns]}
                    for y in cshare.index],
        "country_cols": list(cshare.columns),
        "brands": [{"name": b, "count": f"{n:,}", "median": nis(m)} for b, n, m in brand_rows],
        "importers": [{"name": n, "count": f"{int(v):,}", "brands": f"{int(imp_brands[n]):,}"}
                      for n, v in top_i.items()],
        "bands": [{"name": b, "count": f"{n:,}",
                   "share": num(n / max(len(cur_p), 1) * 100)} for b, n in bands],
        "models": [{"year": str(y), "cells": [(k_nis(mt[(t, y)]) if (t, y) in mt.index else "—")
                                              for t in picks]} for y in trend_years],
        "model_names": picks,
        "china": [{"name": b, "count": f"{int(v):,}"} for b, v in china.head(TOP_BRANDS).items()],
        "l4l": [{"year": f"{y - 1}→{y}", "matched": f"{l4l[y]['matched']:,}", "up": num(l4l[y]["up"]),
                 "same": num(l4l[y]["same"]), "down": num(l4l[y]["down"]),
                 "mean": num(l4l[y]["mean"], 2)} for y in sorted(l4l)],
    }

    labels = {
        "last_year": str(last),
        "lede": (f"מחירון הרכב החדש כפי שמסרו היבואנים: {len(df):,} רשומות של דגמים וגרסאות משנות "
                 f"הדגם {int(df['year'].min())}–{last}, מ-{df['importer_id'].nunique():,} יבואנים. "
                 f"בשנת הדגם {last}: {len(cur):,} רשומות מ-{imp.size:,} יבואנים."),
        "entries_note": ("כל רשומה היא גרסת דגם במחירון, לא רכב שנמכר. חציונים ומספרים משקפים את "
                         "היצע המחירון — יצרן שמציע גרסאות רבות משפיע עליהם יותר."),
        "median_aria": f"גרף קווים: מחיר מחירון חציוני לפי שנת דגם, פרטי ומסחרי, {first_shown} עד {last}.",
        "counts_aria": f"תרשים עמודות: מספר רשומות במחירון לפי שנת דגם, {first_shown} עד {last}.",
        "country_aria": (f"תרשים עמודות מוערם: חלוקת רשומות המחירון לפי ארץ ייצור, "
                         f"{last - TREND_YEARS + 1} עד {last}, באחוזים."),
        "brands_aria": f"תרשים עמודות: מחיר חציוני במותגים עם הרשומות הרבות ביותר בשנת הדגם {last}.",
        "importers_aria": f"תרשים עמודות: מספר רשומות במחירון לפי יבואן, שנת הדגם {last}.",
        "bands_aria": f"תרשים עמודות: רשומות רכב פרטי לפי טווח מחיר, שנת הדגם {last}.",
        "models_aria": (f"גרף קווים: מחיר חציוני לפי שנת דגם של {len(picks)} כינויים מסחריים "
                        f"שמופיעים ברוב השנים האחרונות."),
        "china_aria": f"תרשים עמודות: רשומות במחירון של דגמים מתוצרת סין לפי מותג, שנת הדגם {last}.",
        "l4l_aria": ("תרשים עמודות מוערם: גרסאות שמופיעות בשתי שנות דגם עוקבות — אחוז שהתייקרו, "
                     "נשארו באותו מחיר או הוזלו, וממוצע שינוי המחיר."),
        "partial_note":(f"שנת הדגם {last} עשויה להיות חלקית — יבואנים מוסיפים דגמים במהלך השנה."),
    }

    return {
        "agent_data": {
            "summary_he": (f"מחירון הרכב החדש לפי יבואן: {len(df):,} רשומות משנות הדגם "
                           f"{int(df['year'].min())}–{last}. בשנת הדגם {last} המחיר החציוני של רשומת "
                           f"רכב פרטי: {kpis['median_private']['display']}."),
            "dataset_kind": "rankings",
            "related_ids": ["1c8e79c5-0ddb-461f-84ea-5bdcbaefaef4"],
            "suggested_tags": ["רכב", "מחירון רכב", "יבואני רכב", "מחירים", "תחבורה"],
            "temporal_coverage": f"{int(df['year'].min())}/{last}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
