"""היתרי שריפת גזם חקלאי — Ministry of Agriculture pruning-burn permits.

One row per permit (~5.7k since 2014, appended daily). The dataset ships two
resources with identical rows: a Hebrew-header file (read here) and a twin
with transliterated headers (skipped). "Now" is the latest permit start date
in the data, never the wall clock; that year is partial unless it reaches
late December, and year-to-date comparisons cut the previous year at the
same calendar day.

Permit holders are private farmers: the page stays at settlement / district
/ crop level. Land-registry block and parcel numbers are never shown — only
the count of parcels a permit covers.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
WEEKDAYS_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
LRI, PDI = "⁦", "⁩"
MINUS = "−"

TOP_CROPS = 15
TOP_TOWNS = 15
HEAT_YEARS = 15          # year × month heatmap keeps the latest N years
VALIDITY_YEARS = 20      # validity-mix chart keeps the latest N years
SEASON_FAMS = 5          # families drawn in the seasonal-profile chart
TREEMAP_CROPS = 8        # crops per family in the treemap, rest grouped
WINDOW_DOMINANT = 0.75
WINTER = {11, 12, 1, 2, 3}
SUMMER = {6, 7, 8, 9}   # a burn window "rules" a month at this share

PARCEL_COLS = [("גוש ראשון", "חלקה ראשונה"), ("גוש שני", "חלקה שניה"),
               ("גוש שלישי", "חלקה שלישית")]

# Crop families — keyword rules over the crop label; order matters
# (nurseries and vegetables first so "משתלות הדרים" / "תפוחי אדמה" don't land
# in citrus / pome fruit). Unknown labels fall through to "אחר".
NURSERY = ["משתל", "תרביות"]
VEG = ["עגבני", "חציל", "פלפל", "מלפפון", "תות שדה", "תפוחי אדמה", "אספרגוס",
       "כותנה", "חיטה", "סורגום", "תלתן", 'גד"ש']
CITRUS_EXACT = {"אור", "אורה", "מיכל", "מירב", "טופז", "עידית", "ולנסיה",
                "נובה (סנטינה)", "שמוטי", "מינאולה", "מורקוט", "ספארי סנסט",
                "טרויטה תפוז"}
CITRUS = ["לימון", "ליים", "אשכולית", "פומל", "תפוח זהב", "אתרוג", "תפוז"]
ORNAMENTAL_EXACT = {"אורן"}
VINE = ["כרם", "גפן", "ענבי", "עינבי"]
DECIDUOUS = ["אפרסק", "נקטרינה", "שזיף", "משמש", "משמיש", "דובדבן", "תפוח",
             "אגס", "חבוש"]
ORCHARD = ["זית", "תמר", "דקל", "רימון", "אפרסמון", "תאנ", "שקד", "אבוקדו",
           "מנגו", "שסק", "קיוי", "ליצי", "גויאבה", "פקאנ", "אגוז", "חוחובה",
           "אנונה", "פסיפלורה", "בננה", "אננס", "שיזף", "מטע אורגני"]
ORNAMENTAL = ["צמחי גן", "נוי", "ורד", "שעווה", "הדס", "אקליפטוס", "שיטה",
              "מורן", "פרח", "ורוניקה", "מונסטרה", "אדמונית", "אילה", "עשב"]
F_DEC, F_CIT, F_ORCH, F_VINE = "נשירים", "הדרים", "מטעים אחרים", "גפן וכרמים"
F_ORN, F_VEG, F_NURS, F_OTHER = "נוי וענפי קטיף", 'ירקות וגד"ש', "משתלות", "אחר"

VALIDITY_BUCKETS = [(1, 1, "יום אחד"), (2, 2, "יומיים"), (3, 7, "3–7 ימים"),
                    (8, 30, "8–30 ימים"), (31, None, "31 ימים ומעלה")]


def family(crop):
    if any(k in crop for k in NURSERY):
        return F_NURS
    if any(k in crop for k in VEG):
        return F_VEG
    if crop in CITRUS_EXACT or any(k in crop for k in CITRUS):
        return F_CIT
    if crop in ORNAMENTAL_EXACT:
        return F_ORN
    if any(k in crop for k in VINE):
        return F_VINE
    if any(k in crop for k in DECIDUOUS):
        return F_DEC
    if any(k in crop for k in ORCHARD):
        return F_ORCH
    if any(k in crop for k in ORNAMENTAL):
        return F_ORN
    return F_OTHER


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def signed_pct(v):
    r = round(v, 1)
    if r == 0:
        return "0.0%"
    return (f"+{r:.1f}%" if r > 0 else f"{MINUS}{abs(r):.1f}%")


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def ranked(counts):
    """value_counts → total order: count desc, then label asc."""
    return counts.sort_index().sort_values(ascending=False, kind="stable")


def month_ranges(months):
    """Sorted circular runs of month numbers → 'יוני–ספטמבר, דצמבר–פברואר'."""
    ms = sorted(set(months))
    if not ms:
        return ""
    if len(ms) == 12:
        return "כל השנה"
    # rotate so that the list starts right after a gap
    start = next(m for m in ms if (m - 2) % 12 + 1 not in ms)
    order = [((start - 1 + i) % 12) + 1 for i in range(12)]
    runs, cur = [], []
    for m in order:
        if m in ms:
            cur.append(m)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    parts = []
    for r in runs:
        a, b = MONTHS_HE[r[0] - 1], MONTHS_HE[r[-1] - 1]
        parts.append(a if len(r) == 1 else f"{a}–{b}")
    return ", ".join(parts)


def join_he(items):
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ו" + items[-1]


def _prepare(df):
    out = pd.DataFrame({
        "town": df["ישוב"].str.strip(),
        "district": df["מחוז"].str.strip(),
        "crop": df["גידול"].str.replace("*", "", regex=False).str.split().str.join(" "),
        "window": df["שעות שריפה"].str.strip(),
        "start": pd.to_datetime(df["תאריך תחילת תוקף"].str.strip(), errors="coerce",
                                format="%d/%m/%Y"),
        "end": pd.to_datetime(df["תאריך סיום תוקף"].str.strip(), errors="coerce",
                              format="%d/%m/%Y"),
    })
    out["town"] = out["town"].replace("", "לא ידוע")
    out["district"] = out["district"].replace("", "לא ידוע")
    out["crop"] = out["crop"].fillna("").replace("", "לא צוין")
    out["window"] = out["window"].replace("", "לא צוין")
    parcels = sum(((df[g].str.strip() != "") | (df[c].str.strip() != "")).astype(int)
                  for g, c in PARCEL_COLS)
    out["parcels"] = parcels
    out["fam"] = out["crop"].map(family)
    out["days"] = (out["end"] - out["start"]).dt.days + 1
    return out


def validity_bucket(days):
    if pd.isna(days) or days < 1:
        return None
    for lo, hi, label in VALIDITY_BUCKETS:
        if days >= lo and (hi is None or days <= hi):
            return label
    return None


# ── insight rules ──────────────────────────────────────────────────────────

def insight_trend(per_year, full_years):
    s = per_year.reindex(full_years, fill_value=0)
    if len(s) < 4:
        return None
    peak_y = int(s.idxmax())
    peak_v = int(s[peak_y])
    last_y = full_years[-1]
    last_v = int(s[last_y])
    if peak_y == last_y:
        return (f"{last_y} היא שנת השיא בהיתרי שריפת גזם מאז {full_years[0]}, "
                f"עם {n(last_v)} היתרים.")
    after = s[s.index > peak_y]
    tr_y = int(after.idxmin())
    tr_v = int(after[tr_y])
    if tr_v == 0 or peak_v / tr_v < 1.3:
        return None
    drop = (1 - tr_v / peak_v) * 100
    text = (f"מספר ההיתרים השנתי ירד משיא של {n(peak_v)} ב-{peak_y} לשפל של {n(tr_v)} "
            f"ב-{tr_y} (ירידה של {pct(drop, 0)})")
    if tr_y != last_y and last_v / tr_v >= 1.2:
        text += (f", ומאז חלה התאוששות: ב-{last_y} ניתנו {n(last_v)} היתרים "
                 f"({pct((last_v / tr_v - 1) * 100, 0)} יותר מבשנת השפל)")
    elif tr_y != last_y:
        text += f"; ב-{last_y} ניתנו {n(last_v)} היתרים"
    return text + "."


def ytd_counts(df, ref):
    key = df["start"].dt.month * 100 + df["start"].dt.day
    cut = ref.month * 100 + ref.day
    cur = int(((df["start"].dt.year == ref.year) & (key <= cut)).sum())
    prev = int(((df["start"].dt.year == ref.year - 1) & (key <= cut)).sum())
    return cur, prev


def insight_ytd(cur, prev, ref, partial):
    if not partial or prev == 0:
        return None
    chg = (cur / prev - 1) * 100
    head = f"מתחילת {ref.year} ועד {d_he(ref)} ניתנו {n(cur)} היתרים"
    if abs(chg) < 5:
        return f"{head} — בדומה לתקופה המקבילה ב-{ref.year - 1} ({n(prev)})."
    word = "יותר" if chg > 0 else "פחות"
    return (f"{head} — {pct(abs(chg))} {word} מבתקופה המקבילה ב-{ref.year - 1} "
            f"({n(prev)}).")


def insight_season(df, fam_counts):
    total = len(df)
    by_m = df["start"].dt.month.value_counts()
    top_m = int(ranked(by_m).index[0]) if len(by_m) else None
    if top_m is None:
        return None
    text = (f"החודש העמוס ביותר הוא {MONTHS_HE[top_m - 1]}, עם "
            f"{pct(by_m[top_m] / total * 100)} מכל ההיתרים")
    big = [f for f in fam_counts.index
           if f != F_OTHER and fam_counts[f] >= 150 and fam_counts[f] / total >= 0.05][:2]
    if len(big) == 2:
        # Robust contrast: share of each family's permits in the winter
        # months (Nov–Mar) vs the summer months (Jun–Sep) — single-month
        # peaks are too noisy for a bimodal season.
        sh = []
        for f in big:
            m = df.loc[df["fam"] == f, "month"]
            sh.append((f, float(m.isin(WINTER).mean()), float(m.isin(SUMMER).mean())))
        (f1, w1, s1), (f2, w2, s2) = sh
        if abs(w1 - w2) >= 0.15:
            hi, lo = (sh[0], sh[1]) if w1 > w2 else (sh[1], sh[0])
            text += (f"; אך העונה תלויה בגידול — {pct(hi[1] * 100, 0)} מהיתרי ה{hi[0]} ניתנו "
                     f"בנובמבר–מרץ, לעומת {pct(lo[1] * 100, 0)} מהיתרי ה{lo[0]}, "
                     f"ש-{pct(lo[2] * 100, 0)} מהם ניתנו ביוני–ספטמבר")
    return text + "."


def insight_window(win_month):
    """win_month: DataFrame months(1..12) × window counts."""
    if win_month.empty or win_month.shape[1] < 2:
        return None
    share = win_month.div(win_month.sum(axis=1).where(lambda s: s > 0), axis=0)
    parts = []
    for w in sorted(win_month.columns):
        ms = [int(m) for m in share.index if share.loc[m, w] >= WINDOW_DOMINANT]
        if ms:
            parts.append(f"{LRI}{w}{PDI} ב{month_ranges(ms)}")
    if len(parts) < 2:
        return None
    return ("שעות השריפה המותרות נקבעות לפי העונה: " + "; ".join(parts)
            + f" (חלון שמופיע ב-{pct(WINDOW_DOMINANT * 100, 0)} ומעלה מהיתרי החודש).")


def insight_validity(vy, y0, y1):
    if y0 is None or y1 is None or y0 == y1:
        return None
    one = VALIDITY_BUCKETS[0][2]
    week = VALIDITY_BUCKETS[2][2]
    long_ = VALIDITY_BUCKETS[4][2]

    def share(y, b):
        row = vy.loc[y]
        tot = row.sum()
        return None if tot == 0 else row.get(b, 0) / tot

    a, b = share(y0, one), share(y1, one)
    w0, w1 = share(y0, week), share(y1, week)
    if a is None or b is None or abs(b - a) < 0.10:
        return None
    word = "עלה" if b > a else "ירד"
    text = (f"ההיתרים התקצרו: שיעור ההיתרים התקפים ליום אחד בלבד {word} מ-{pct(a * 100, 0)} "
            f"ב-{y0} ל-{pct(b * 100, 0)} ב-{y1}, ואילו היתרים של שלושה עד שבעה ימים "
            f"ירדו מ-{pct(w0 * 100, 0)} ל-{pct(w1 * 100, 0)}")
    if b < a:
        text = (f"שיעור ההיתרים התקפים ליום אחד בלבד {word} מ-{pct(a * 100, 0)} ב-{y0} "
                f"ל-{pct(b * 100, 0)} ב-{y1}")
    lg = share(y1, long_)
    if lg is not None and lg >= 0.05:
        text += (f"; לצדם הופיעו היתרים ארוכים של חודש ומעלה ({pct(lg * 100, 0)} "
                 f"מההיתרים ב-{y1})")
    return text + "."


def insight_district(df, dist_counts):
    total = len(df)
    lead, lv = dist_counts.index[0], int(dist_counts.iloc[0])
    text = f"מחוז {lead} מוביל עם {n(lv)} היתרים ({pct(lv / total * 100)})"
    tab = df.groupby(["district", "fam"]).size()
    spec = []
    for d in dist_counts.index:
        dn = int(dist_counts[d])
        if dn < 200:
            continue
        fams = ranked(tab[d])
        f, fv = fams.index[0], int(fams.iloc[0])
        if f != F_OTHER and fv / dn >= 0.4:
            spec.append((fv / dn, d, f))
    spec.sort(key=lambda t: (-t[0], t[1]))
    picked = []
    for t in spec:                      # two districts led by DIFFERENT families
        if all(t[2] != p[2] for p in picked):
            picked.append(t)
        if len(picked) == 2:
            break
    if len(picked) == 2:
        bits = [f"במחוז {d} {pct(s * 100, 0)} מההיתרים הם ל{f}" for s, d, f in picked]
        text += ". תמהיל הגידולים שונה מאזור לאזור: " + join_he(bits)
    return text + "."


def insight_towns(town_counts, total):
    if town_counts.empty:
        return None
    top10 = int(town_counts.head(10).sum())
    share = top10 / total
    if share < 0.2:
        return None
    name, v = town_counts.index[0], int(town_counts.iloc[0])
    return (f"ההיתרים ניתנו ב-{n(town_counts.size)} יישובים, אך עשרת המובילים מרכזים "
            f"{pct(share * 100)} מהם; בראש עומד {name} עם {n(v)} היתרים.")


def insight_weekday(wd_counts, total):
    if total == 0:
        return None
    weekend = int(wd_counts.get(5, 0) + wd_counts.get(6, 0))
    if weekend / total >= 0.05:
        return None
    lead = int(ranked(wd_counts).index[0])
    return (f"{pct((1 - weekend / total) * 100)} מההיתרים נכנסים לתוקף בימים ראשון–חמישי; "
            f"יום {WEEKDAYS_HE[lead]} מוביל עם {pct(wd_counts[lead] / total * 100)} "
            f"מתחילות התוקף.")


# ── compute ────────────────────────────────────────────────────────────────

def compute(frames):
    raw = frames["permits"]
    df = _prepare(raw)
    bad_dates = int(df["start"].isna().sum())
    df = df[df["start"].notna()].copy()
    total = len(df)

    ref = df["start"].max()
    ref_year = int(ref.year)
    first = df["start"].min()
    partial = not (ref.month == 12 and ref.day >= 20)
    last_full = ref_year - 1 if partial else ref_year
    first_full = int(first.year) if (first.month == 1 and first.day <= 15) else int(first.year) + 1
    full_years = list(range(first_full, last_full + 1))
    years = list(range(int(first.year), ref_year + 1))

    df["year"] = df["start"].dt.year.astype(int)
    df["month"] = df["start"].dt.month.astype(int)
    df["wd"] = (df["start"].dt.dayofweek.astype(int) + 1) % 7   # 0 = Sunday

    per_year = df.groupby("year").size()
    dist_counts = ranked(df["district"].value_counts())
    fam_counts = ranked(df["fam"].value_counts())
    crop_counts = ranked(df["crop"].value_counts())
    town_counts = ranked(df["town"].value_counts())
    districts = list(dist_counts.index)

    # 1. permits per year by district + active settlements
    yd = df.groupby(["year", "district"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    towns_y = df.groupby("year")["town"].nunique().reindex(years, fill_value=0)
    ch_years = {
        "x": [str(y) for y in years],
        "series": [{"name": d, "data": [int(v) for v in yd.get(d, pd.Series(0, index=years))]}
                   for d in districts],
        "towns": [int(v) for v in towns_y],
    }
    t_years = [{"year": str(y), "count": n(per_year.get(y, 0)), "towns": n(towns_y[y]),
                "partial": (y == ref_year and partial)} for y in years]

    # 2. year × month heatmap (latest HEAT_YEARS years)
    hy = years[-HEAT_YEARS:]
    ym = df.groupby(["year", "month"]).size()
    cells = [[m - 1, yi, int(ym.get((y, m), 0))] for yi, y in enumerate(hy) for m in range(1, 13)
             if not (y == ref_year and partial and m > ref.month)]
    ch_heat = {"x": MONTHS_HE, "y": [str(y) for y in hy], "cells": cells,
               "max": max([c[2] for c in cells] or [1])}

    # 3. seasonal profile per crop family (share of the family's permits by month)
    fm = df.groupby(["fam", "month"]).size().unstack(fill_value=0).reindex(columns=range(1, 13),
                                                                          fill_value=0)
    season_fams = [f for f in fam_counts.index if f != F_OTHER][:SEASON_FAMS]
    ch_season = {"x": MONTHS_HE, "series": [
        {"name": f, "data": [round(float(v) / float(fm.loc[f].sum()) * 100, 1) for v in fm.loc[f]]}
        for f in season_fams]}
    t_season = [{"month": MONTHS_HE[m - 1],
                 "cells": [pct(float(fm.loc[f, m]) / float(fm.loc[f].sum()) * 100) for f in season_fams]}
                for m in range(1, 13)]

    # 4. district × month heatmap (share of each district's permits)
    dm = df.groupby(["district", "month"]).size().unstack(fill_value=0).reindex(
        index=districts, columns=range(1, 13), fill_value=0)
    dm_cells = []
    for yi, d in enumerate(districts):
        tot = float(dm.loc[d].sum())
        for m in range(1, 13):
            dm_cells.append([m - 1, yi, round(float(dm.loc[d, m]) / tot * 100, 1), int(dm.loc[d, m])])
    ch_dm = {"x": MONTHS_HE, "y": districts, "cells": dm_cells,
             "max": max([c[2] for c in dm_cells] or [1])}
    t_dm = [{"district": d, "cells": [pct(c[2]) for c in dm_cells if c[1] == yi]}
            for yi, d in enumerate(districts)]

    # 5. crop families treemap
    fc = df.groupby(["fam", "crop"]).size()
    tree = []
    t_fams = []
    for f in fam_counts.index:
        crops = ranked(fc[f])
        kids = [{"name": c, "value": int(v)} for c, v in crops.head(TREEMAP_CROPS).items()]
        rest = int(crops.iloc[TREEMAP_CROPS:].sum())
        if rest:
            kids.append({"name": f"גידולים אחרים ({f})", "value": rest})
        tree.append({"name": f, "value": int(fam_counts[f]), "children": kids})
        t_fams.append({"fam": f, "count": n(fam_counts[f]),
                       "share": pct(fam_counts[f] / total * 100),
                       "crops": n(crops.size), "top": crops.index[0]})

    # 6. top crops
    cn = list(crop_counts.head(TOP_CROPS).index)
    cv = [int(v) for v in crop_counts.head(TOP_CROPS).values]
    c_other = int(crop_counts.iloc[TOP_CROPS:].sum())
    crop_fam = df.groupby("crop")["fam"].first()
    t_crops = [{"crop": c, "fam": crop_fam[c], "count": n(v)} for c, v in zip(cn, cv)]
    if c_other:
        t_crops.append({"crop": f"שאר הגידולים ({n(crop_counts.size - TOP_CROPS)})", "fam": "—",
                        "count": n(c_other)})
    ch_crops = {"names": cn, "values": cv}   # the long tail stays in the table only

    # 7. district × family mix (100% stacked)
    df_ = df.groupby(["district", "fam"]).size().unstack(fill_value=0).reindex(
        index=districts, columns=list(fam_counts.index), fill_value=0)
    ch_dfam = {"y": districts, "series": [
        {"name": f, "data": [round(float(df_.loc[d, f]) / float(df_.loc[d].sum()) * 100, 1)
                             for d in districts]} for f in fam_counts.index]}
    t_dfam = [{"district": d, "cells": [n(df_.loc[d, f]) for f in fam_counts.index],
               "total": n(df_.loc[d].sum())} for d in districts]

    # 8. burn window × month
    windows = sorted(df["window"].unique())
    wm = df.groupby(["month", "window"]).size().unstack(fill_value=0).reindex(
        index=range(1, 13), columns=windows, fill_value=0)
    ch_window = {"x": MONTHS_HE, "series": [{"name": w, "data": [int(v) for v in wm[w]]}
                                            for w in windows]}
    t_window = [{"month": MONTHS_HE[m - 1], "cells": [n(wm.loc[m, w]) for w in windows]}
                for m in range(1, 13)]

    # 9. validity length mix by year
    df["vb"] = df["days"].map(validity_bucket)
    bad_validity = int(df["vb"].isna().sum())
    vlabels = [b[2] for b in VALIDITY_BUCKETS]
    vy = df[df["vb"].notna()].groupby(["year", "vb"]).size().unstack(fill_value=0).reindex(
        index=years, columns=vlabels, fill_value=0)
    vyears = years[-VALIDITY_YEARS:]
    ch_validity = {"x": [str(y) for y in vyears], "series": [
        {"name": b, "data": [round(float(vy.loc[y, b]) / float(vy.loc[y].sum()) * 100, 1)
                             if vy.loc[y].sum() else 0 for y in vyears]} for b in vlabels]}
    t_validity = [{"year": str(y), "cells": [n(vy.loc[y, b]) for b in vlabels]} for y in vyears]
    vfull = [y for y in full_years if vy.loc[y].sum() >= 50]
    v_y0 = vfull[0] if vfull else None
    v_y1 = vfull[-1] if vfull else None

    # 10. weekday of validity start
    wd = df["wd"].value_counts().reindex(range(7), fill_value=0)
    ch_wd = {"names": WEEKDAYS_HE, "values": [int(v) for v in wd]}
    t_wd = [{"day": WEEKDAYS_HE[i], "count": n(wd[i]), "share": pct(wd[i] / total * 100)}
            for i in range(7)]

    # 11. top settlements (with their most frequent district)
    td = df.groupby(["town", "district"]).size().reset_index(name="k").sort_values(
        ["town", "k", "district"], ascending=[True, False, True]).drop_duplicates("town")
    town_dist = dict(zip(td["town"], td["district"]))
    tn = list(town_counts.head(TOP_TOWNS).index)
    ch_towns = {"names": tn, "values": [int(town_counts[t]) for t in tn],
                "districts": [town_dist[t] for t in tn]}
    t_towns = [{"town": t, "district": town_dist[t], "count": n(town_counts[t])} for t in tn]

    # ── KPIs ──
    cur, prev = ytd_counts(df, ref)
    if partial:
        a, b = cur, prev
        ytd_label = f"שינוי בהיתרים {ref_year} לעומת {ref_year - 1}, בתקופה המקבילה (עד {d_he(ref)})"
    else:
        a, b = int(per_year.get(ref_year, 0)), int(per_year.get(ref_year - 1, 0))
        ytd_label = f"שינוי בהיתרים {ref_year} לעומת {ref_year - 1}"
    chg = (a / b - 1) * 100 if b else 0.0
    # Fewer burn permits = less agricultural smoke: falling is "ok", rising "warn".
    ytd_tone = "ok" if chg <= -10 else ("warn" if chg >= 10 else "brand")
    one = VALIDITY_BUCKETS[0][2]
    one_y = v_y1 if v_y1 is not None else ref_year
    one_share = (vy.loc[one_y, one] / vy.loc[one_y].sum() * 100) if vy.loc[one_y].sum() else 0.0
    multi = float((df["parcels"] > 1).mean() * 100)

    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "towns": {"value": int(town_counts.size), "display": n(town_counts.size), "tone": "brand"},
        "ytd": {"value": round(chg, 1), "display": signed_pct(chg), "tone": ytd_tone},
        "one_day": {"value": round(float(one_share), 1), "display": f"{one_share:.1f}%",
                    "tone": "info"},
    }

    rules = [
        ("trend", insight_trend(per_year, full_years)),
        ("ytd", insight_ytd(cur, prev, ref, partial)),
        ("season", insight_season(df, fam_counts)),
        ("window", insight_window(wm)),
        ("validity", insight_validity(vy, v_y0, v_y1)),
        ("district", insight_district(df, dist_counts)),
        ("towns", insight_towns(town_counts, total)),
        ("weekday", insight_weekday(wd, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    partial_note = (f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else "")
    excl = ""
    if bad_dates:
        excl = f" {n(bad_dates)} רשומות ללא תאריך תחילת תוקף תקין אינן נכללות."
    labels = {
        "lede": (f"{n(total)} היתרים לשריפת גזם חקלאי שנתן משרד החקלאות וביטחון המזון "
                 f"מ-{d_he(first)} ועד {d_he(ref)}, ב-{n(town_counts.size)} יישובים "
                 f"ו-{len(districts)} מחוזות. ההיתר ניתן רק כשמדריך חקלאי קבע שהגזם עלול "
                 f"לשאת מחלה או מזיקים, והוא מגדיר גידול, חלון שעות ותקופת תוקף. "
                 f"{pct(multi)} מההיתרים חלים על יותר מחלקה אחת.{excl}"),
        "ytd_kpi": ytd_label,
        "one_day_kpi": f"מההיתרים ב-{one_y} תקפים ליום אחד בלבד",
        "years_note": (f"מספר ההיתרים בכל שנה לפי מחוז, והקו — מספר היישובים שקיבלו היתר "
                       f"באותה שנה.{partial_note}"),
        "years_aria": f"גרף עמודות מוערמות: היתרים לפי שנה ומחוז, {years[0]} עד {ref_year}, וקו מספר היישובים.",
        "years_caption": "היתרים ויישובים לפי שנה.",
        "heat_note": (f"כל תא — מספר ההיתרים שתוקפם התחיל באותו חודש"
                      + (f", ב-{len(hy)} השנים האחרונות" if len(years) > HEAT_YEARS else "")
                      + f".{partial_note}"),
        "heat_aria": f"מפת חום: היתרים לפי שנה וחודש, {hy[0]} עד {ref_year}.",
        "season_note": (f"איזה חלק מהיתרי כל קבוצת גידולים ניתן בכל חודש — {len(season_fams)} "
                        f"הקבוצות הגדולות, כל השנים יחד."),
        "season_aria": "גרף קווים: שיעור ההיתרים בכל חודש, לפי קבוצת גידולים.",
        "season_caption": "שיעור היתרי הקבוצה בכל חודש.",
        "dm_note": "שיעור היתרי כל מחוז שניתנו בכל חודש, כל השנים יחד — כך מחוזות בגדלים שונים ברי השוואה.",
        "dm_aria": "מפת חום: שיעור ההיתרים בכל חודש, לפי מחוז.",
        "dm_caption": "שיעור היתרי המחוז בכל חודש.",
        "fams_note": (f"{n(crop_counts.size)} שמות גידולים מקובצים ל-{len(fam_counts)} קבוצות; "
                      f"גודל כל מלבן — מספר ההיתרים."),
        "fams_aria": "מפת עץ: היתרים לפי קבוצת גידולים וגידול.",
        "fams_caption": "היתרים לפי קבוצת גידולים.",
        "crops_aria": f"תרשים עמודות: {TOP_CROPS} הגידולים עם מירב ההיתרים.",
        "crops_note": (f"{TOP_CROPS} הגידולים עם מירב ההיתרים מתוך {n(crop_counts.size)}; שאר "
                       f"הגידולים ({n(c_other)} היתרים) מופיעים בטבלה."),
        "crops_caption": f"{TOP_CROPS} הגידולים המובילים ושאר הגידולים.",
        "dfam_aria": "תרשים עמודות מוערמות: תמהיל קבוצות הגידולים בכל מחוז, באחוזים.",
        "dfam_caption": "היתרים לפי מחוז וקבוצת גידולים.",
        "window_aria": "תרשים עמודות מוערמות: היתרים לפי חודש וחלון שעות השריפה.",
        "window_caption": "היתרים לפי חודש וחלון שעות.",
        "validity_note": (f"משך התוקף — מיום התחלת התוקף ועד יום סיומו, כולל."
                          + (f" {n(bad_validity)} היתרים שתאריך הסיום שלהם קודם לתאריך ההתחלה "
                             f"אינם נכללים." if bad_validity else "")
                          + (f" מוצגות {VALIDITY_YEARS} השנים האחרונות." if len(years) > VALIDITY_YEARS else "")),
        "validity_aria": "תרשים עמודות מוערמות: משך תוקף ההיתרים בכל שנה, באחוזים.",
        "validity_caption": "היתרים לפי שנה ומשך תוקף.",
        "wd_aria": "תרשים עמודות: היתרים לפי יום בשבוע שבו התחיל התוקף.",
        "wd_caption": "היתרים לפי יום תחילת התוקף.",
        "towns_note": (f"{TOP_TOWNS} היישובים שקיבלו את מירב ההיתרים; בטבלה — המחוז שבו נרשמו "
                       f"רוב ההיתרים של כל יישוב."),
        "towns_aria": f"תרשים עמודות: {TOP_TOWNS} היישובים עם מירב ההיתרים.",
        "towns_caption": f"{TOP_TOWNS} היישובים המובילים.",
    }
    tables = {
        "years": t_years, "season": t_season, "season_fams": season_fams,
        "dm": t_dm, "fams": t_fams, "crops": t_crops, "dfam": t_dfam,
        "dfam_cols": list(fam_counts.index), "window": t_window, "windows": windows,
        "validity": t_validity, "vlabels": vlabels, "wd": t_wd, "towns": t_towns,
    }
    charts = {
        "years": ch_years, "heat": ch_heat, "season": ch_season, "dm": ch_dm,
        "fams": tree, "crops": ch_crops, "dfam": ch_dfam, "window": ch_window,
        "validity": ch_validity, "wd": ch_wd, "towns": ch_towns,
    }

    top_fam = fam_counts.index[0]
    return {
        "agent_data": {
            "summary_he": (f"{n(total)} היתרי שריפת גזם חקלאי של משרד החקלאות מאז {first.year}, "
                           f"ב-{n(town_counts.size)} יישובים: מגמה שנתית, עונתיות, גידולים "
                           f"(בראשם {top_fam}), מחוזות, חלונות שעות ומשך תוקף."),
            "dataset_kind": "timeseries",
            "suggested_tags": ["שריפת גזם", "חקלאות", "איכות הסביבה", "מטעים", "עונתיות",
                               "מזיקים"],
            "related_ids": ["fdf06a98-0fe3-47df-8c3e-18ee582d1445",
                            "7a6cbf55-8178-4d40-8613-a38909c7e96f",
                            "a11eddd8-8288-4a10-a991-76d65df3e6eb",
                            "5beb2241-cbca-4350-bdae-55d096373acf"],
            "temporal_coverage": f"{first.strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
    }
