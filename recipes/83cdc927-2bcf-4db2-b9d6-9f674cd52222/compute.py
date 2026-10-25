"""אירועי מחלת הכלבת בישראל — confirmed rabies cases (Veterinary Services).

One row per laboratory-confirmed animal case (~900 rows since 2006), with
date, species, veterinary region, settlement, the virus lineage code and a
point in Web-Mercator metres (EPSG:3857 — x≈3.9M, y≈3.8M; NOT ITM, which is
why GovMap's wgs84/itm modes can't place them). Coordinates are converted
here with the closed-form spherical-Mercator inverse and aggregated per
location for an inline Leaflet bubble map.

"Now" is the latest case date in the data, never the wall clock. Rows whose
date doesn't parse (an upstream row split across two records, blank rows)
are dropped and the count is disclosed.
"""
import math
import re

import pandas as pd

R_EARTH = 6378137.0
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
UNKNOWN = "לא ידוע"
OTHER = "אחר"

# Animal groups: known species → group; anything new falls to "אחר".
G_DOG, G_WILD, G_FARM, G_OTHER = "כלבים", "חיות בר", "חיות משק", "חתולים ואחר"
GROUPS = [G_DOG, G_WILD, G_FARM, G_OTHER]
SPECIES_GROUP = {
    "כלב": G_DOG,
    "תן": G_WILD, "שועל": G_WILD, "זאב": G_WILD, "גירית": G_WILD,
    "נמיה": G_WILD, "דלק": G_WILD, "שפן סלע": G_WILD, "צבוע": G_WILD,
    "חזיר בר": G_WILD, "עטלף": G_WILD,
    "בקר": G_FARM, "צאן": G_FARM, "סוס": G_FARM, "חמור": G_FARM,
    "עז": G_FARM, "גמל": G_FARM,
}
TOP_SPECIES = 8
TOP_LOCATIONS = 12
HEAT_SPECIES = 6
PERIOD_YEARS = 5
MAP_MAX = 800
LINEAGE_RE = re.compile(r"^(?:[IVX]+[AB]?|V\d)$")
LAT_RANGE, LON_RANGE = (29.0, 33.6), (34.0, 36.5)


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _sorted_counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _top(counts, k):
    top = counts.head(k)
    other = int(counts.iloc[k:].sum())
    names = list(top.index) + ([OTHER] if other else [])
    vals = [int(v) for v in top.values] + ([other] if other else [])
    return names, vals


def _lineage(v):
    s = v.replace(" ", "").replace("​", "").upper()
    return s if LINEAGE_RE.match(s) else UNKNOWN


def _prepare(raw):
    df = pd.DataFrame({
        "date": pd.to_datetime(raw["Date"].str.strip(), errors="coerce", format="%Y-%m-%d"),
        "species": raw["SpeciesNameHeb"].str.strip(),
        "region": raw["RegionHeb"].str.strip(),
        "lineage": raw["Species"].map(_lineage),
        "settlement": raw["SettlementHeb"].str.strip().str.rstrip("*").str.strip(),
        "place": raw["LocationNotSettlementHeb"].str.strip(),
        "x": pd.to_numeric(raw["x"], errors="coerce"),
        "y": pd.to_numeric(raw["y"], errors="coerce"),
    })
    dropped = int(df["date"].isna().sum())
    df = df[df["date"].notna()].copy()
    df["species"] = df["species"].replace("", UNKNOWN)
    df["region"] = df["region"].replace("", UNKNOWN)
    df["group"] = df["species"].map(lambda s: SPECIES_GROUP.get(s, G_OTHER))
    df["year"] = df["date"].dt.year.astype(int)
    df["month"] = df["date"].dt.month.astype(int)
    df["loc"] = df["settlement"].where(df["settlement"] != "", df["place"])
    df["lon"] = df["x"] / R_EARTH * 180 / math.pi
    df["lat"] = (2 * (df["y"] / R_EARTH).map(lambda v: math.atan(math.exp(v)) if pd.notna(v) else float("nan"))
                 - math.pi / 2) * 180 / math.pi
    ok = df["lat"].between(*LAT_RANGE) & df["lon"].between(*LON_RANGE)
    df.loc[~ok, ["lat", "lon"]] = float("nan")
    return df, dropped


# ---------------------------------------------------------------- insights

def insight_record(per_year, ref, partial):
    top = per_year.sort_index().sort_values(ascending=False, kind="stable")
    best_y, best_v = int(top.index[0]), int(top.iloc[0])
    last_y = int(per_year.index.max())
    if len(per_year) < 3 or best_v < 5:
        return None
    if best_y == last_y:
        tail = f", אף שהנתונים מגיעים רק עד {d_he(ref)}" if partial else ""
        prev = per_year.drop(last_y)
        p = prev.sort_index().sort_values(ascending=False, kind="stable")
        return (f"{last_y} היא שנת השיא במאגר, עם {n(best_v)} אירועי כלבת{tail} — "
                f"יותר מהשיא הקודם ({n(p.iloc[0])} אירועים ב-{int(p.index[0])}).")
    last_v = int(per_year[last_y])
    tail = f" (עד {d_he(ref)})" if partial else ""
    return (f"שנת השיא במאגר היא {best_y}, עם {n(best_v)} אירועים; ב-{last_y}{tail} "
            f"נרשמו {n(last_v)} אירועים.")


def insight_12m(cur, prev, ref):
    if prev < 10 or cur + prev < 20:
        return None
    chg = cur / prev - 1
    head = f"ב-12 החודשים שעד {d_he(ref)} אושרו {n(cur)} אירועי כלבת"
    if abs(chg) < 0.15:
        return f"{head} — בדומה ל-12 החודשים שקדמו להם ({n(prev)})."
    word = "עלייה" if chg > 0 else "ירידה"
    return f"{head}, {word} של {pct(abs(chg) * 100)} לעומת 12 החודשים שקדמו להם ({n(prev)})."


def insight_dogs(df, ref):
    """Dog share, latest 12 months vs the 12 before; falls back to the
    all-time share when the year-on-year move is under 10 points."""
    w1, w0 = ref - pd.DateOffset(years=1), ref - pd.DateOffset(years=2)
    rec = df[df["date"] > w1]
    old = df[(df["date"] > w0) & (df["date"] <= w1)]
    if len(rec) >= 20 and len(old) >= 20:
        s1, s0 = (rec["group"] == G_DOG).mean(), (old["group"] == G_DOG).mean()
        if abs(s1 - s0) >= 0.10:
            word = "עלה" if s1 > s0 else "ירד"
            risk = " — הכלבים הם מקור החשיפה העיקרי של בני אדם לנגיף" if s1 > s0 else ""
            return (f"חלקם של הכלבים באירועים {word} ל-{pct(s1 * 100)} ב-12 החודשים האחרונים "
                    f"({n((rec['group'] == G_DOG).sum())} מתוך {n(len(rec))}), לעומת {pct(s0 * 100)} "
                    f"ב-12 החודשים שקדמו להם{risk}.")
    share = (df["group"] == G_DOG).mean()
    if len(df) < 50 or share < 0.2:
        return None
    return (f"כלבים הם {pct(share * 100)} מכלל האירועים במאגר "
            f"({n((df['group'] == G_DOG).sum())} מתוך {n(len(df))}).")


def insight_season(month_tot):
    total = month_tot.sum()
    if total < 50:
        return None
    best, best_s = None, -1
    for m in range(1, 13):
        win = [((m - 1 + k) % 12) + 1 for k in range(3)]
        s = sum(int(month_tot.get(w, 0)) for w in win)
        if s > best_s:
            best, best_s = win, s
    share = best_s / total
    if share < 0.30:
        return None
    lo, hi = MONTHS_HE[best[0] - 1], MONTHS_HE[best[2] - 1]
    return (f"שיא עונתי: {pct(share * 100)} מכלל האירועים אושרו בשלושת החודשים "
            f"{lo}–{hi}, לעומת כרבע שהיה צפוי בפיזור אחיד על פני השנה.")


def insight_region_shift(df, ref):
    cut = ref - pd.DateOffset(years=2)
    known = df[df["region"] != UNKNOWN]
    rec, old = known[known["date"] > cut], known[known["date"] <= cut]
    if len(rec) < 20 or len(old) < 20:
        return None
    s1 = rec["region"].value_counts(normalize=True)
    s0 = old["region"].value_counts(normalize=True)
    diff = (s1.sub(s0, fill_value=0)).sort_index().sort_values(ascending=False, kind="stable")
    reg, d = diff.index[0], diff.iloc[0]
    if d < 0.08:
        return None
    a, b = s0.get(reg, 0.0), s1.get(reg, 0.0)
    return (f"המחלה מתפשטת דרומה ומערבה: אזור {reg} היווה {pct(b * 100)} מהאירועים בשנתיים "
            f"האחרונות ({n((rec['region'] == reg).sum())}), לעומת {pct(a * 100, 1)} בלבד בשנים "
            f"שקדמו להן." if reg in ("השפלה וההר", "השרון", "הנגב") else
            f"חלקו של אזור {reg} באירועים עלה ל-{pct(b * 100)} בשנתיים האחרונות "
            f"({n((rec['region'] == reg).sum())}), לעומת {pct(a * 100, 1)} בשנים שקדמו להן.")


def insight_waves(per_year):
    if len(per_year) < 6:
        return None
    med = float(per_year.median())
    waves = per_year[per_year >= max(2 * med, 10)]
    if waves.empty or len(waves) > len(per_year) / 3:
        return None
    parts = ", ".join(f"{int(y)} ({n(v)})" for y, v in waves.sort_index().items())
    return (f"האירועים מגיעים בגלים: שנים שבהן נרשמו לפחות פי שניים מהחציון השנתי "
            f"({med:g} אירועים) — {parts}.")


def insight_lineage(df, ref):
    cut = ref - pd.DateOffset(years=2)
    rec = df[(df["date"] > cut) & (df["lineage"] != UNKNOWN)]
    if len(rec) < 20:
        return None
    vc = _sorted_counts(rec["lineage"])
    share = vc.iloc[0] / len(rec)
    if share < 0.4:
        return None
    second = ""
    if len(vc) > 1 and vc.iloc[1] / len(rec) >= 0.15:
        second = f", ואחריה {LRI}{vc.index[1]}{PDI} ({pct(vc.iloc[1] / len(rec) * 100)})"
    return (f"השושלת הגנטית הנפוצה של הנגיף בשנתיים האחרונות היא {LRI}{vc.index[0]}{PDI} "
            f"({pct(share * 100)} מהאירועים שסווגו){second}.")


def insight_hotspots(loc_counts, n_events):
    if loc_counts.empty:
        return None
    top_name, top_v = loc_counts.index[0], int(loc_counts.iloc[0])
    multi = int((loc_counts >= 5).sum())
    if top_v < 5:
        return None
    leaders = [k for k, v in loc_counts.items() if v == top_v]
    if len(leaders) == 1:
        lead = f"ובראשם {top_name} עם {n(top_v)}"
    elif len(leaders) <= 4:
        lead = f"ובראשם {', '.join(leaders[:-1])} ו{leaders[-1]}, עם {n(top_v)} אירועים כל אחד"
    else:
        lead = f"ובראשם {n(len(leaders))} מקומות עם {n(top_v)} אירועים כל אחד"
    return (f"האירועים פזורים על פני {n(len(loc_counts))} יישובים ואתרים; ב-{n(multi)} מהם "
            f"אושרו חמישה אירועים או יותר, {lead}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df, dropped = _prepare(frames["cases"])
    total = len(df)
    ref = df["date"].max()
    ref_year = int(ref.year)
    first_year = int(df["year"].min())
    partial = not (ref.month == 12 and ref.day >= 15)
    years = list(range(first_year, ref_year + 1))

    per_year = df.groupby("year").size().reindex(years, fill_value=0)

    # Yearly by animal group
    yg = df.groupby(["year", "group"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    groups = [g for g in GROUPS if g in yg.columns and yg[g].sum() > 0]
    chart_years = {"x": [str(y) for y in years],
                   "series": [{"name": g, "data": [int(v) for v in yg[g]]} for g in groups]}

    # Species
    species = _sorted_counts(df["species"])
    sp_names, sp_vals = _top(species, TOP_SPECIES)

    # Mix by period (fixed 5-year bins anchored at the first year)
    df["period"] = (df["year"] - first_year) // PERIOD_YEARS
    plabels = []
    for p in range(int(df["period"].max()) + 1):
        a = first_year + p * PERIOD_YEARS
        b = min(a + PERIOD_YEARS - 1, ref_year)
        plabels.append(f"{a}–{b}" if b > a else str(a))
    # LRM-prefixed twins for the canvas axis (a bare "2006–2010" renders
    # reversed in an RTL canvas run).
    plabels_axis = ["\u200e" + p for p in plabels]
    pg = df.groupby(["period", "group"]).size().unstack(fill_value=0).reindex(range(len(plabels)), fill_value=0)
    ptot = pg.sum(axis=1)
    mix = {"x": plabels_axis, "series": [
        {"name": g, "data": [round(float(pg.loc[i, g]) / ptot[i] * 100, 1) if ptot[i] else 0
                             for i in range(len(plabels))]}
        for g in groups if g in pg.columns]}
    mix_rows = [{"period": plabels[i], "n": n(ptot[i]),
                 "cells": [f"{(pg.loc[i, g] / ptot[i] * 100 if ptot[i] else 0):.0f}%" for g in groups]}
                for i in range(len(plabels))]

    # Seasonality
    month_tot = df.groupby("month").size().reindex(range(1, 13), fill_value=0)
    recent_years = [y for y in years if y >= ref_year - 2]
    rec = df[df["year"].isin(recent_years)]
    month_rec = rec.groupby("month").size().reindex(range(1, 13), fill_value=0)
    season = {"x": MONTHS_HE, "all": [int(v) for v in month_tot],
              "recent": [int(v) for v in month_rec]}

    # Month × year heatmap
    my = df.groupby(["year", "month"]).size()
    heat_cells = [[m - 1, yi, int(my.get((y, m), 0))] for yi, y in enumerate(years) for m in range(1, 13)]
    heat = {"x": MONTHS_HE, "y": [str(y) for y in years], "cells": heat_cells,
            "max": max([c[2] for c in heat_cells] or [1])}

    # Region × year
    regions = [r for r in _sorted_counts(df["region"]).index if r != UNKNOWN]
    ry = df.groupby(["region", "year"]).size()
    rheat_cells = [[yi, ri, int(ry.get((r, y), 0))] for ri, r in enumerate(regions) for yi, y in enumerate(years)]
    rheat = {"x": [str(y) for y in years], "y": regions, "cells": rheat_cells,
             "max": max([c[2] for c in rheat_cells] or [1])}

    # Region share: earlier vs last two years
    cut2 = ref - pd.DateOffset(years=2)
    known = df[df["region"] != UNKNOWN]
    r_old = known[known["date"] <= cut2]["region"].value_counts()
    r_new = known[known["date"] > cut2]["region"].value_counts()
    o_tot, n_tot = int(r_old.sum()), int(r_new.sum())
    reg_share = {"names": regions,
                 "old": [round(float(r_old.get(r, 0)) / o_tot * 100, 1) if o_tot else 0 for r in regions],
                 "new": [round(float(r_new.get(r, 0)) / n_tot * 100, 1) if n_tot else 0 for r in regions],
                 "old_name": f"עד {d_he(cut2)}", "new_name": "שנתיים אחרונות"}
    reg_rows = [{"name": r, "total": n((df["region"] == r).sum()),
                 "old": f"{reg_share['old'][i]:.1f}%", "new": f"{reg_share['new'][i]:.1f}%"}
                for i, r in enumerate(regions)]

    # Region × species
    hs = [s for s in species.index if s != UNKNOWN][:HEAT_SPECIES]
    rs = df.groupby(["region", "species"]).size()
    rs_cells = [[si, ri, int(rs.get((r, s), 0))] for ri, r in enumerate(regions) for si, s in enumerate(hs)]
    rsp = {"x": hs, "y": regions, "cells": rs_cells, "max": max([c[2] for c in rs_cells] or [1])}
    rsp_rows = [{"name": r, "cells": [n(rs.get((r, s), 0)) for s in hs]} for r in regions]

    # Lineage by year
    lin = _sorted_counts(df.loc[df["lineage"] != UNKNOWN, "lineage"])
    main_lin = list(lin.head(4).index)
    df["lin_grp"] = df["lineage"].where(df["lineage"].isin(main_lin) | (df["lineage"] == UNKNOWN), OTHER)
    ly = df.groupby(["year", "lin_grp"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    lin_order = main_lin + [g for g in (OTHER, UNKNOWN) if g in ly.columns]
    lineage = {"x": [str(y) for y in years],
               "series": [{"name": g, "data": [int(v) for v in ly[g]]} for g in lin_order if g in ly.columns]}
    lin_rows = [{"name": g, "count": n((df["lin_grp"] == g).sum()),
                 "first": str(int(df.loc[df["lin_grp"] == g, "year"].min())),
                 "last": str(int(df.loc[df["lin_grp"] == g, "year"].max()))}
                for g in lin_order if g in ly.columns]

    # Locations
    named = df[df["loc"] != ""]
    loc_counts = _sorted_counts(named["loc"])
    l_names, l_vals = list(loc_counts.head(TOP_LOCATIONS).index), [int(v) for v in loc_counts.head(TOP_LOCATIONS)]
    loc_rows = []
    for name in l_names:
        sub = named[named["loc"] == name]
        loc_rows.append({"name": name, "count": n(len(sub)),
                         "region": _sorted_counts(sub["region"]).index[0],
                         "years": (f"{sub['year'].min()}–{sub['year'].max()}"
                                   if sub["year"].min() != sub["year"].max() else str(sub["year"].min()))})

    # Map points: aggregate per location name (unnamed → rounded coordinate)
    geo = df[df["lat"].notna()].copy()
    geo["key"] = geo["loc"].where(geo["loc"] != "",
                                  "@" + geo["lat"].round(2).astype(str) + "," + geo["lon"].round(2).astype(str))
    pts = []
    for key, sub in geo.groupby("key", sort=True):
        top_sp = _sorted_counts(sub["species"]).index[0]
        pts.append([round(math.fsum(sub["lat"]) / len(sub), 4), round(math.fsum(sub["lon"]) / len(sub), 4), int(len(sub)),
                    "" if key.startswith("@") else key, int(sub["year"].min()), int(sub["year"].max()), top_sp])
    pts.sort(key=lambda p: (-p[2], p[3], p[0], p[1]))
    map_trim = len(pts) > MAP_MAX
    pts = pts[:MAP_MAX]
    recent_from = ref_year - 1
    no_geo = total - len(geo)
    # Initial view: the central 98% of cases, so a lone far-south case
    # doesn't zoom the whole country out (it stays on the map).
    bounds = ([[round(float(geo["lat"].quantile(0.01)), 3), round(float(geo["lon"].quantile(0.01)), 3)],
               [round(float(geo["lat"].quantile(0.99)), 3), round(float(geo["lon"].quantile(0.99)), 3)]]
              if len(geo) >= 20 else None)

    # 12-month windows
    w1 = ref - pd.DateOffset(years=1)
    w0 = ref - pd.DateOffset(years=2)
    cur12 = int((df["date"] > w1).sum())
    prev12 = int(((df["date"] > w0) & (df["date"] <= w1)).sum())

    rules = [
        ("record", insight_record(per_year, ref, partial)),
        ("trend12", insight_12m(cur12, prev12, ref)),
        ("dogs", insight_dogs(df, ref)),
        ("region_shift", insight_region_shift(df, ref)),
        ("season", insight_season(month_tot)),
        ("waves", insight_waves(per_year)),
        ("lineage", insight_lineage(df, ref)),
        ("hotspots", insight_hotspots(loc_counts, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # KPIs
    last_v = int(per_year[ref_year])
    prior_max = int(per_year.drop(ref_year).max()) if len(per_year) > 1 else 0
    year_tone = "danger" if last_v > prior_max else ("warn" if last_v >= 0.75 * prior_max else "brand")
    if prev12 >= 10:
        chg = cur12 / prev12 - 1
        chg_display = ("+" if chg >= 0 else "−") + f"{abs(chg) * 100:.0f}%"
        chg_tone = "danger" if chg > 0.15 else ("ok" if chg < -0.15 else "info")
    else:
        chg_display, chg_tone = "—", "brand"
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "last_year": {"value": last_v, "display": n(last_v), "tone": year_tone},
        "trend12": {"value": cur12, "display": chg_display, "tone": chg_tone},
        "locations": {"value": int(len(loc_counts)), "display": n(len(loc_counts)), "tone": "brand"},
    }

    dropped_note = (f" {n(dropped)} רשומות ללא תאריך תקין אינן נכללות." if dropped else "")
    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    labels = {
        "lede": (f"מאגר אירועי הכלבת של השירותים הווטרינריים: {n(total)} מקרי כלבת שאושרו "
                 f"במעבדה בבעלי חיים, מ-{first_year} ועד {d_he(ref)} — לפי מין בעל החיים, "
                 f"אזור, יישוב ושושלת גנטית של הנגיף.{dropped_note}"),
        "last_year_kpi": f"אירועים ב-{ref_year}" + (f" (עד {ref.day}.{ref.month})" if partial else ""),
        "trend12_kpi": f"שינוי ב-12 החודשים האחרונים ({n(cur12)} אירועים) לעומת השנה שקדמה",
        "years_note": (f"מספר האירועים בכל שנה, לפי קבוצת בעלי חיים.{partial_note}"),
        "years_aria": f"גרף עמודות מוערמות: אירועי כלבת לפי שנה וקבוצת בעלי חיים, {first_year} עד {ref_year}.",
        "years_caption": "אירועי כלבת לפי שנה וקבוצת בעלי חיים.",
        "species_aria": f"תרשים עמודות: אירועי כלבת לפי מין בעל החיים ({TOP_SPECIES} הנפוצים ואחר).",
        "species_caption": "מספר אירועי כלבת לפי מין בעל החיים.",
        "mix_note": (f"התפלגות האירועים בין קבוצות בעלי החיים בכל תקופה של {PERIOD_YEARS} שנים "
                     f"(באחוזים).{partial_note}"),
        "mix_aria": "גרף עמודות מוערמות: חלוקת אירועי הכלבת בין קבוצות בעלי חיים לפי תקופה, באחוזים.",
        "mix_caption": "חלוקת האירועים בין קבוצות בעלי חיים, לפי תקופה.",
        "season_note": (f"סך האירועים בכל חודש קלנדרי בכל השנים, לצד שלוש השנים האחרונות "
                        f"({recent_years[0]}–{ref_year})."),
        "season_recent": f"{recent_years[0]}–{ref_year}",
        "season_recent_axis": f"\u200e{recent_years[0]}–{ref_year}",
        "season_aria": "תרשים עמודות: אירועי כלבת לפי חודש בשנה, בכל השנים ובשלוש השנים האחרונות.",
        "season_caption": "מספר אירועי כלבת לפי חודש קלנדרי.",
        "heat_aria": f"מפת חום: אירועי כלבת לפי שנה וחודש, {first_year} עד {ref_year}.",
        "rheat_aria": f"מפת חום: אירועי כלבת לפי אזור ושנה, {first_year} עד {ref_year}.",
        "rshare_note": (f"חלקו של כל אזור מהאירועים בשנתיים האחרונות (מ-{d_he(cut2)}) לעומת כל "
                        f"התקופה שקדמה להן."),
        "rshare_aria": "תרשים עמודות: חלקו של כל אזור באירועים, שנתיים אחרונות לעומת התקופה שקדמה.",
        "rshare_caption": "אירועים לפי אזור וחלקו של כל אזור בשתי התקופות.",
        "rsp_aria": f"מפת חום: אירועי כלבת לפי אזור ומין בעל החיים ({HEAT_SPECIES} המינים הנפוצים).",
        "rsp_caption": "מספר אירועים לפי אזור ומין בעל החיים.",
        "lineage_aria": "גרף עמודות מוערמות: אירועי כלבת לפי שנה ושושלת גנטית של הנגיף.",
        "lineage_caption": "אירועים לפי שושלת גנטית, עם שנה ראשונה ואחרונה.",
        "loc_aria": f"תרשים עמודות: {TOP_LOCATIONS} היישובים והאתרים עם מספר אירועי הכלבת הגבוה ביותר.",
        "loc_caption": f"{TOP_LOCATIONS} היישובים והאתרים עם הכי הרבה אירועים.",
        "map_note": (f"כל עיגול הוא יישוב או אתר, וגודלו לפי מספר האירועים שאושרו בו. באדום — "
                     f"מקומות עם אירוע מ-{recent_from} ואילך; בכחול — מקומות שבהם האירוע האחרון "
                     f"מוקדם יותר."
                     + ((" אירוע אחד ללא מיקום תקין אינו מוצג." if no_geo == 1 else
                        f" {n(no_geo)} אירועים ללא מיקום תקין אינם מוצגים.") if no_geo else "")
                     + (f" מוצגים {n(MAP_MAX)} המקומות עם הכי הרבה אירועים." if map_trim else "")),
        "map_recent": f"אירוע מ-{recent_from} ואילך",
        "map_older": f"אירוע אחרון לפני {recent_from}",
        "map_aria": f"מפה: אירועי כלבת לפי יישוב, {first_year} עד {ref_year}.",
    }
    tables = {
        "years": [{"year": str(y), "total": n(per_year[y]),
                   "cells": [n(yg.loc[y, g]) for g in groups]} for y in reversed(years)],
        "groups": groups,
        "species": [{"name": k, "count": n(v)} for k, v in zip(sp_names, sp_vals)],
        "mix": mix_rows,
        "season": [{"month": MONTHS_HE[i], "all": n(month_tot.iloc[i]), "recent": n(month_rec.iloc[i])}
                   for i in range(12)],
        "regions": reg_rows,
        "rsp_x": hs,
        "rsp": rsp_rows,
        "lineage": lin_rows,
        "locations": loc_rows,
    }
    charts = {
        "years": chart_years,
        "species": {"names": sp_names, "values": sp_vals},
        "mix": mix,
        "season": season,
        "heat": heat,
        "rheat": rheat,
        "rshare": reg_share,
        "rsp": rsp,
        "lineage": lineage,
        "locations": {"names": l_names, "values": l_vals},
        "map": {"points": pts, "recent_from": recent_from, "bounds": bounds},
    }

    dog_n = int((df["group"] == G_DOG).sum())
    return {
        "agent_data": {
            "summary_he": (f"{n(total)} מקרי כלבת שאושרו בבעלי חיים בישראל מ-{first_year} עד "
                           f"{d_he(ref)}, מהם {n(dog_n)} בכלבים — לפי שנה, מין, אזור ויישוב, "
                           f"עם מפת מוקדים ועונתיות."),
            "dataset_kind": "map",
            "suggested_tags": ["כלבת", "מחלות בעלי חיים", "וטרינריה", "בריאות הציבור", "חיות בר"],
            "related_ids": ["b4c32de1-627c-4b93-8d20-e58f6d44f733",
                            "32d9a7b7-a47b-4592-a84d-fc84c1059ff4",
                            "a25e63f2-4f22-4eff-a696-e7c6d20c9e27",
                            "c27919df-83d8-4aba-8297-f307fa1737fd",
                            "28954732-da33-48d0-b22c-1c0c279aadca"],
            "temporal_coverage": f"{df['date'].min().strftime('%Y-%m-%d')}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"has_lineage": len(main_lin) >= 2, "has_map": len(pts) > 0},
    }
