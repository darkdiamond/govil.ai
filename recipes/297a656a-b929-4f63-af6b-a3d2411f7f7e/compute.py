"""תעריפי חלקות קבר מחיים: the Ministry of Religious Services' tariff for
buying a burial plot during one's lifetime, one row per burial society /
locality (Kadisha), with the tariff in shekels (Rate) and the tariff year.

Searchers want "how much does a plot cost in city X", so the page leads with
the lookup and the spread of prices. Every number and sentence is computed
from the rows; rules whose premise doesn't hold return None.

Growth: the input is every resource carrying Kadisha/Rate/Year (concat). The
LATEST year in the data is the page's year (never hardcoded). If a second
year appears (a new file beside the old one, or several years in one file),
the previous year feeds an optional year-over-year section, matched by
society name.
"""
import math
import re

import pandas as pd

SUMMARY_MAX = 155
SHORT_MAX = 28
TOP_N = 15                 # most-expensive chart
TIER_MIN = 2               # a "tariff level" is a rounded price shared by >= this many rows
TIER_CHART_MAX = 10
TIER_INSIGHT_SHARE = 0.10  # tiers covering >= 10% of rows each are named in the insight
HIGH_MULT = 2.0            # "expensive" = at least 2x the median
SKEW_MIN = 0.15            # mean above median by >= 15% -> skew insight
CHANGE_FLAT = 0.005        # |median change| below 0.5% reads as "no change"
CHANGE_MIN_MATCH = 5       # year-over-year needs >= 5 societies in both years
GENERAL_WORDS = ("אינן ", "שאינן")  # catch-all rows ("... not listed above")
BAND_WIDTHS = (1000, 2000, 2500, 5000, 10000, 20000, 50000)
BAND_MAX = 15


# ---------------------------------------------------------------- helpers

def _clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _ils(v):
    return f"₪{int(round(v)):,}"


def _num(v):
    return f"{int(round(v)):,}"


def _pct(v):
    return f"{v * 100:.0f}%"


def _signed_pct(v):
    if abs(v) < 0.0005:
        return "0.0%"
    return ("+" if v > 0 else "−") + f"{abs(v) * 100:.1f}%"


def _count_he(n, one, many):
    """'חברה קדישא אחת' / '12 חברות קדישא'."""
    return one if n == 1 else f"{n:,} {many}"


def _is_general(name):
    return any(w in name for w in GENERAL_WORDS)


def _base(name):
    """Locality behind a row: 'ירושלים (למעט ...)' / 'חיפה בחלקות ...' -> 'ירושלים' / 'חיפה'."""
    s = name.split(" (")[0].split(",")[0].split(" בחלקות")[0]
    return s.strip() or name


def _short(name):
    if len(name) <= SHORT_MAX:
        return name
    out = ""
    for w in name.split(" "):
        if len(out) + len(w) + (1 if out else 0) > SHORT_MAX:
            break
        out = f"{out} {w}" if out else w
    return (out or name[:SHORT_MAX]) + "…"


def _labels(names):
    short = [_short(n) for n in names]
    return [s if short.count(s) == 1 else n for s, n in zip(short, names)]


def _join(items, limit=8):
    items = list(items)
    if len(items) <= limit:
        if len(items) <= 1:
            return "".join(items)
        return ", ".join(items[:-1]) + " ו" + items[-1]
    return ", ".join(items[:limit]) + f" ועוד {len(items) - limit:,}"


def _prepare(df):
    df = df.copy()
    df["name"] = df["Kadisha"].map(_clean)
    df["rate"] = pd.to_numeric(df["Rate"].astype(str).str.replace(",", "").str.replace("₪", "")
                               .str.strip(), errors="coerce")
    df["year"] = pd.to_numeric(df["Year"].astype(str).str.strip(), errors="coerce")
    df = df[(df["name"] != "") & df["rate"].notna() & (df["rate"] > 0)]
    df = df[["name", "rate", "year"]].drop_duplicates()
    return df.sort_values(["year", "name", "rate"], kind="stable", na_position="first")


def _pick_year(df):
    years = sorted(int(y) for y in df["year"].dropna().unique())
    if not years:
        return None, None, df, df.iloc[0:0]
    cur_y = years[-1]
    prev_y = years[-2] if len(years) > 1 else None
    cur = df[df["year"] == cur_y]
    prev = df[df["year"] == prev_y] if prev_y is not None else df.iloc[0:0]
    return cur_y, prev_y, cur, prev


def _one_per_name(df):
    """One tariff per society (a duplicated name keeps its highest tariff)."""
    d = df.sort_values(["name", "rate"], ascending=[True, False], kind="stable")
    return d.drop_duplicates("name", keep="first").reset_index(drop=True)


def _bands(rates):
    lo, hi = float(rates.min()), float(rates.max())
    width = BAND_WIDTHS[-1]
    for w in BAND_WIDTHS:
        if math.floor(hi / w) - math.floor(lo / w) + 1 <= BAND_MAX:
            width = w
            break
    start = math.floor(lo / width) * width
    n_bins = math.floor(hi / width) - math.floor(lo / width) + 1
    out = []
    for i in range(n_bins):
        a = start + i * width
        b = a + width
        cnt = int(((rates >= a) & (rates < b)).sum())
        out.append({"label": f"{a:,}-{b:,}", "count": cnt})
    return out, width


# ---------------------------------------------------------------- insights

def insight_range(cur, year):
    if len(cur) < 2:
        return None
    lo = cur["rate"].min()
    hi = cur["rate"].max()
    if round(hi) == round(lo):
        return None
    lo_names = sorted(cur[cur["rate"].round() == round(lo)]["name"].map(_base).unique())
    hi_names = sorted(cur[cur["rate"].round() == round(hi)]["name"].map(_base).unique())
    when = f" ב-{year}" if year else ""
    hi_part = (f"{_ils(hi)} ({_join(hi_names, 6)})" if len(hi_names) <= 6
               else f"{_ils(hi)} ({len(hi_names):,} חברות קדישא)")
    return (f"מחיר חלקת קבר מחיים{when} נע בין {_ils(lo)} ({_join(lo_names, 4)}) "
            f"ל-{hi_part}: פער של פי {hi / lo:.1f}.")


def insight_tiers(cur, tiers):
    n = len(cur)
    big = [t for t in tiers if t["count"] >= max(TIER_MIN, TIER_INSIGHT_SHARE * n)]
    if not big:
        return None
    covered = sum(t["count"] for t in big)
    parts = [f"{_ils(t['value'])} ({_count_he(t['count'], 'חברה קדישא אחת', 'חברות קדישא')})"
             for t in big]
    head = ("רמת תעריף אחת חלה" if len(big) == 1
            else f"{len(big):,} רמות תעריף בלבד חלות")
    return (f"{head} על {_pct(covered / n)} מהרשימה ({covered:,} מתוך {n:,}): "
            + ", ".join(parts) + ".")


def insight_expensive(cur, median):
    hi = cur[cur["rate"] >= HIGH_MULT * median].sort_values(
        ["rate", "name"], ascending=[False, True], kind="stable")
    if len(hi) < 2:
        return None
    bases = list(dict.fromkeys(hi["name"].map(_base)))
    where = "" if len(bases) == len(hi) else f" ב-{_count_he(len(bases), 'יישוב אחד', 'יישובים')}"
    return (f"{len(hi):,} תעריפים{where} גבוהים לפחות פי {HIGH_MULT:.0f} מהחציון "
            f"({_ils(median)}): {_join(bases, 10)}.")


def insight_split(cur):
    d = cur[~cur["name"].map(_is_general)].copy()
    d["base"] = d["name"].map(_base)
    parts = []
    for base, g in sorted(d.groupby("base"), key=lambda x: x[0]):
        if len(g) < 2 or round(g["rate"].max()) == round(g["rate"].min()):
            continue
        parts.append(f"{base} בין {_ils(g['rate'].min())} ל-{_ils(g['rate'].max())}")
    if not parts:
        return None
    lead = ("ביישוב אחד התעריף תלוי" if len(parts) == 1
            else f"ב-{len(parts):,} ערים התעריף תלוי")
    return f"{lead} בחברה קדישא שבחלקותיה נרכש הקבר: " + "; ".join(parts) + "."


def insight_general(cur, median):
    g = cur[cur["name"].map(_is_general)].sort_values(["rate", "name"], kind="stable")
    if g.empty:
        return None
    rates = sorted(set(int(round(r)) for r in g["rate"]))
    names = "; ".join(f"\"{n}\"" for n in g["name"])
    if len(rates) == 1:
        rel = ("מעל החציון" if rates[0] > round(median)
               else "מתחת לחציון" if rates[0] < round(median) else "כמו החציון")
        return (f"לצד היישובים המפורטים, נקבע תעריף כללי של {_ils(rates[0])} ({rel}, "
                f"{_ils(median)}) עבור: {names}.")
    return (f"לצד היישובים המפורטים, נקבעו תעריפים כלליים בין {_ils(rates[0])} "
            f"ל-{_ils(rates[-1])} עבור: {names}.")


def insight_skew(cur, median):
    mean = float(cur["rate"].mean())
    if len(cur) < 5 or median <= 0 or mean / median - 1 < SKEW_MIN:
        return None
    below = int((cur["rate"] < mean).sum())
    return (f"התעריף הממוצע ({_ils(mean)}) גבוה ב-{_pct(mean / median - 1)} מהחציון "
            f"({_ils(median)}), כי מעט תעריפים גבוהים במיוחד מושכים אותו מעלה: "
            f"{below:,} מתוך {len(cur):,} התעריפים נמוכים מהממוצע.")


def _changes(cur, prev):
    if prev.empty:
        return None
    m = cur.merge(prev, on="name", suffixes=("", "_prev"))
    m = m[m["rate_prev"] > 0]
    if len(m) < CHANGE_MIN_MATCH:
        return None
    m = m.assign(chg=m["rate"] / m["rate_prev"] - 1)
    return m.sort_values(["chg", "name"], ascending=[False, True], kind="stable")


def insight_change(ch, year, prev_year, med_chg):
    if ch is None:
        return None
    up = int((ch["chg"] > CHANGE_FLAT).sum())
    down = int((ch["chg"] < -CHANGE_FLAT).sum())
    if abs(med_chg) < CHANGE_FLAT:
        head = f"התעריף החציוני ב-{year} כמעט לא השתנה לעומת {prev_year}"
    else:
        word = "עלה" if med_chg > 0 else "ירד"
        head = f"התעריף החציוני {word} ב-{abs(med_chg) * 100:.1f}% בין {prev_year} ל-{year}"
    return (f"{head}. מתוך {len(ch):,} חברות קדישא שמופיעות בשתי השנים, "
            f"{up:,} העלו תעריף ו-{down:,} הורידו.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    year, prev_year, cur_raw, prev_raw = _pick_year(df)
    if year is None:
        cur_raw = df
    cur = _one_per_name(cur_raw)
    prev = _one_per_name(prev_raw) if not prev_raw.empty else prev_raw
    n = int(len(cur))
    median = float(cur["rate"].median())
    mean = float(cur["rate"].mean())
    lo_row = cur.sort_values(["rate", "name"], kind="stable").iloc[0]
    hi_rows = cur[cur["rate"].round() == round(cur["rate"].max())].sort_values("name", kind="stable")
    hi = float(cur["rate"].max())
    yr = str(year) if year is not None else ""
    yr_sfx = f" {yr}" if yr else ""

    # ---- tariff levels (rounded price shared by several rows)
    r = cur.assign(level=cur["rate"].round().astype(int))
    tiers = []
    for lvl, g in r.groupby("level"):
        if len(g) >= TIER_MIN:
            tiers.append({"value": int(lvl), "count": int(len(g)),
                          "names": sorted(g["name"].map(_base).unique())})
    tiers.sort(key=lambda t: (-t["count"], t["value"]))
    unique_n = int(n - sum(t["count"] for t in tiers))

    # ---- year over year
    ch = _changes(cur, prev)
    med_chg = None
    if ch is not None:
        med_chg = float(cur[cur["name"].isin(ch["name"])]["rate"].median()
                        / prev[prev["name"].isin(ch["name"])]["rate"].median() - 1)

    rules = [
        ("range", insight_range(cur, yr)),
        ("change", insight_change(ch, yr, prev_year, med_chg) if ch is not None else None),
        ("tiers", insight_tiers(cur, tiers)),
        ("expensive", insight_expensive(cur, median)),
        ("split", insight_split(cur)),
        ("skew", insight_skew(cur, median)),
        ("general", insight_general(cur, median)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    kpis, klabels, order = {}, {}, []

    def add(key, value, display, label, tone="brand"):
        kpis[key] = {"value": value, "display": display, "tone": tone}
        klabels[key] = label
        order.append(key)

    add("count", n, f"{n:,}", f"תעריפים ברשימת {yr}" if yr else "תעריפים ברשימה")
    add("median", round(median, 2), _num(median), "תעריף חציוני (₪)")
    add("min", round(float(lo_row["rate"]), 2), _num(lo_row["rate"]),
        f"התעריף הנמוך ביותר (₪): {_base(lo_row['name'])}", "ok")
    hi_who = (_base(hi_rows.iloc[0]["name"]) if len(hi_rows) == 1
              else f"{len(hi_rows):,} חברות קדישא")
    add("max", round(hi, 2), _num(hi), f"התעריף הגבוה ביותר (₪): {hi_who}",
        "warn" if hi >= HIGH_MULT * median else "brand")
    if med_chg is not None:
        tone = "brand" if abs(med_chg) < CHANGE_FLAT else ("warn" if med_chg > 0 else "ok")
        add("change", round(med_chg, 4), _signed_pct(med_chg),
            f"שינוי בתעריף החציוני לעומת {prev_year}", tone)

    # ---- charts
    bands, width = _bands(cur["rate"])
    top = cur.sort_values(["rate", "name"], ascending=[False, True], kind="stable").head(TOP_N)
    top_asc = top.iloc[::-1]
    chart_top = {"names": list(top_asc["name"]), "labels": _labels(list(top_asc["name"])),
                 "values": [round(float(v)) for v in top_asc["rate"]],
                 "median": round(median)}
    chart_tiers = {"labels": [_ils(t["value"]) for t in tiers[:TIER_CHART_MAX]],
                   "values": [t["count"] for t in tiers[:TIER_CHART_MAX]]}
    chart_bands = {"labels": [b["label"] for b in bands], "values": [b["count"] for b in bands]}

    change_rows = []
    chart_change = None
    if ch is not None:
        for _, row in ch.iterrows():
            change_rows.append({"name": row["name"], "prev": _num(row["rate_prev"]),
                                "cur": _num(row["rate"]), "chg": _signed_pct(row["chg"])})
        big = (ch.assign(mag=ch["chg"].abs())
               .sort_values(["mag", "name"], ascending=[False, True], kind="stable")
               .head(TOP_N).sort_values(["chg", "name"], ascending=[True, False], kind="stable"))
        chart_change = {"names": list(big["name"]), "labels": _labels(list(big["name"])),
                        "values": [round(float(v) * 100, 1) for v in big["chg"]]}

    # ---- full table (alphabetical)
    all_rows = []
    for _, row in cur.sort_values("name", kind="stable").iterrows():
        rel = row["rate"] / median - 1 if median else 0
        all_rows.append({"name": row["name"], "rate": _num(row["rate"]),
                         "rel": _signed_pct(rel)})

    peak_band = max(bands, key=lambda b: b["count"])
    max_tier = tiers[0] if tiers else None

    # ---- summary (meta description, <=155 chars, lookup first)
    soc = _count_he(n, "בחברה קדישא אחת", "חברות קדישא ויישובים")
    in_soc = soc if n == 1 else f"ב-{soc}"
    parts = [f"כמה עולה קבר מחיים{(' ב-' + yr) if yr else ''}? תעריפי רכישת חלקת קבר {in_soc}.",
             f"מ-{_ils(lo_row['rate'])} עד {_ils(hi)}, חציון {_ils(median)}."]
    summary = " ".join(parts)
    if len(summary) > SUMMARY_MAX:
        summary = parts[0][:SUMMARY_MAX]

    lede = (f"תעריפי רכישת חלקת קבר בחיים (קבר מחיים){(' לשנת ' + yr) if yr else ''}, "
            f"כפי שפרסם המשרד לשירותי דת: {_count_he(n, 'תעריף אחד', 'תעריפים')} לפי חברה קדישא, "
            f"יישוב או חלקת קבורה. המחיר נע בין {_ils(lo_row['rate'])} ל-{_ils(hi)}, "
            f"והתעריף החציוני הוא {_ils(median)}.")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "rankings",
        "suggested_tags": ["קבר מחיים", "חלקת קבר", "חברה קדישא", "תעריפים", "קבורה",
                           "שירותי דת"],
        "related_ids": ["fa316df9-3cc1-460e-a613-35d7bab3fb21",
                        "dfb26230-2d0c-46f9-a189-7cc0de547832",
                        "efcb2998-f68e-4dbf-a96e-620d50a8daae"],
        "spatial_coverage": "ישראל",
    }
    if year is not None:
        y0 = prev_year if prev_year is not None else year
        agent_data["temporal_coverage"] = f"{y0}/{year}"

    labels = {f"kpi_{k}": v for k, v in klabels.items()}
    labels.update({
        "h1": f"מחיר קבר מחיים{yr_sfx}: תעריפי רכישת חלקת קבר לפי יישוב",
        "lede": lede,
        "top_title": f"{_count_he(min(TOP_N, n), 'התעריף היקר', 'התעריפים היקרים')} ביותר",
        "top_lede": (f"חברות הקדישא עם התעריף הגבוה ביותר. הקו המקווקו מסמן את החציון "
                     f"({_ils(median)}); התעריף הגבוה ({_ils(hi)}) גבוה ממנו פי {hi / median:.1f}."),
        "top_aria": (f"תרשים עמודות אופקי: {min(TOP_N, n):,} התעריפים הגבוהים ביותר לרכישת קבר מחיים. "
                     f"הגבוה: {_base(top.iloc[0]['name'])}, {_ils(top.iloc[0]['rate'])}."),
        "top_caption": f"{min(TOP_N, n):,} התעריפים הגבוהים, בשקלים.",
        "bands_lede": (f"כמה חברות קדישא נמצאות בכל טווח מחירים (טווחים של {_ils(width)}). "
                       f"הטווח הנפוץ: {peak_band['label']} ₪, עם "
                       f"{_count_he(peak_band['count'], 'תעריף אחד', 'תעריפים')}."),
        "bands_aria": (f"תרשים עמודות: התפלגות {n:,} התעריפים לפי טווחי מחיר של {_ils(width)}. "
                       f"הטווח הנפוץ {peak_band['label']} ₪ עם {peak_band['count']:,} תעריפים."),
        "bands_caption": "מספר התעריפים בכל טווח מחיר, בשקלים.",
        "tiers_lede": ((f"תעריף זהה חל על כמה חברות קדישא. רמת התעריף הנפוצה, {_ils(max_tier['value'])}, "
                        f"חלה על {_count_he(max_tier['count'], 'חברה קדישא אחת', 'חברות קדישא')}; "
                        f"{_count_he(unique_n, 'תעריף אחד ייחודי', 'תעריפים ייחודיים')} לחברה קדישא אחת בלבד.")
                       if max_tier else ""),
        "tiers_aria": ((f"תרשים עמודות: רמות התעריף המשותפות לכמה חברות קדישא. "
                        f"הנפוצה {_ils(max_tier['value'])} עם {max_tier['count']:,} חברות קדישא.")
                       if max_tier else ""),
        "tiers_caption": "רמות תעריף משותפות: מחיר, מספר חברות קדישא ושמותיהן.",
        "all_lede": ((f"כל {n:,} התעריפים" if n > 1 else "התעריף") + " לפי סדר א-ב. "
                     f"העמודה האחרונה מראה את הפער מהתעריף החציוני ({_ils(median)})."),
        "all_caption": f"תעריף רכישת קבר מחיים לפי חברה קדישא{yr_sfx}, בשקלים.",
        "change_title": (f"שינוי בתעריף בין {prev_year} ל-{yr}" if ch is not None else ""),
        "change_lede": (f"{len(ch):,} חברות קדישא מופיעות בשתי השנים. בתרשים: "
                        f"{_count_he(min(TOP_N, len(ch)), 'השינוי הגדול', 'השינויים הגדולים')} באחוזים."
                        if ch is not None else ""),
        "change_aria": (f"תרשים עמודות אופקי: שינוי באחוזים בתעריף בין {prev_year} ל-{yr}."
                        if ch is not None else ""),
        "change_caption": (f"תעריף {prev_year} ו-{yr} ושינוי באחוזים, לכל חברה קדישא."
                           if ch is not None else ""),
        "prev_year": str(prev_year) if prev_year is not None else "",
        "year": yr,
    })

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": order,
        "charts": {"top": chart_top, "bands": chart_bands, "tiers": chart_tiers,
                   "change": chart_change},
        "insights": insights,
        "tables": {
            "top": [{"name": nm, "rate": _num(v)} for nm, v in
                    zip(top["name"], top["rate"])],
            "bands": bands,
            "tiers": [{"value": _num(t["value"]), "count": f"{t['count']:,}",
                       "names": ", ".join(t["names"])} for t in tiers],
            "all": all_rows,
            "change": change_rows,
        },
        "flags": {"has_tiers": bool(tiers), "has_change": ch is not None,
                  "has_bands": len(bands) >= 2},
        "labels": labels,
    }
