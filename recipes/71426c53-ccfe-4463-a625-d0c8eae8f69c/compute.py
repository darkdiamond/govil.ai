"""בתי ספר לנהיגה — Ministry of Transport list of licensed driving schools.

One row per (driving school, licensing region). The school code
(`cod_beit_sefer`) is NOT unique: the same code recurs in different licensing
regions under different names, so every row is counted as one school listing
in its region. Six 0/1 columns say which licence classes the school is
approved to teach (private car, truck, tractor, motorcycle, bus, tow/trailer).

The list is a snapshot, not a time series: schools come and go between
versions and regions can be added. Regions are mapped to the ministry's
districts through a small static gazetteer of the licensing-office towns
(geography, not data from another dataset); an unknown region goes to
"לא משויך" and the page says how many schools that covers.

Naming: driving schools are businesses and are named. School managers
(`menahel`) are counted, never named; phone numbers, street addresses and
permit numbers are not used. Rows whose name marks them as a placeholder
("פיקטיבי") are excluded and the page discloses how many.
"""
import math
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"

CLASSES = [  # column, label, colour
    ("prati", "רכב פרטי", "#0068f5"),
    ("masa", "משאית", "#0b3668"),
    ("ofnoa", "אופנוע", "#4d94ff"),
    ("grar", "גורר", "#003d91"),
    ("otobus", "אוטובוס", "#80b3ff"),
    ("traktor", "טרקטור", "#1a75ff"),
]
CLS_COLS = [c for c, _, _ in CLASSES]
CLS_LABEL = {c: l for c, l, _ in CLASSES}

SEG_CAR = "כולל רכב פרטי"
SEG_HEAVY = "רכב כבד / מקצועי בלבד"
SEG_NONE = "ללא סוג רכב רשום"
SEG_ORDER = [SEG_CAR, SEG_HEAVY, SEG_NONE]
SEG_COLOR = {SEG_CAR: "#0068f5", SEG_HEAVY: "#0b3668", SEG_NONE: "#c3cfe7"}

UNASSIGNED = "לא משויך"
DIST_ORDER = ["תל אביב", "מרכז", "חיפה", "צפון", "ירושלים", "דרום", "יהודה ושומרון"]
# Licensing-office towns (and nearby towns a renamed/new office may carry) →
# Ministry of Interior district (CBS classification). Matching is on a
# normalised spelling (hyphens, quotes and dots → spaces).
GAZETTEER = {
    "תל אביב": "תל אביב, תל אביב יפו, יפו, חולון, בת ים, הרצליה, רמת גן, גבעתיים, בני ברק, רמת השרון, אור יהודה",
    "מרכז": ("רמלה, לוד, רחובות, ראשון לציון, מודיעין, מודיעין מכבים רעות, פתח תקוה, פתח תקווה, כפר סבא, "
             "נתניה, יבנה, רעננה, הוד השרון, ראש העין, נס ציונה, שוהם, יהוד"),
    "חיפה": "חיפה, קרית אליעזר, חדרה, קרית אתא, קרית ביאליק, קרית מוצקין, טירת כרמל, זכרון יעקב, עתלית",
    "צפון": ("כרמיאל, עפולה, בית שאן, טבריה, נצרת עילית, נצרת עלית, נוף הגליל, נצרת, קרית שמונה, צפת, נהריה, "
             "עכו, שפרעם, מעלות, מעלות תרשיחא, יוקנעם, יוקנעם עילית, מגדל העמק, קצרין, סכנין"),
    "ירושלים": "ירושלים, בית שמש, מבשרת ציון",
    "דרום": ("אשדוד, אשקלון, קרית מלאכי, באר שבע, דימונה, ערד, נתיבות, אילת, קרית גת, שדרות, מצפה רמון, "
             "אופקים, רהט, ירוחם"),
    "יהודה ושומרון": "קרית ארבע, אריאל, מעלה אדומים, ביתר עילית, מודיעין עילית, קדומים",
}
TOP_OFFICES = 20
TOP_COMBOS = 10
FULL_CAP = 20
MIN_DIST = 15      # districts with fewer schools are not compared in insights
LEAD_RATIO = 1.25  # leader must exceed the runner-up by this factor


def norm_place(x):
    x = re.sub(r"[-–־'\"׳״.]", " ", str(x))
    x = re.sub(r"\s+", " ", x).strip()
    return re.sub(r"קריית", "קרית", x)


PLACE_DISTRICT = {norm_place(nm): dist for dist, names in GAZETTEER.items() for nm in names.split(",")}


def district_of(place):
    return PLACE_DISTRICT.get(norm_place(place), UNASSIGNED) if place else UNASSIGNED


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def records(k, verb_sg, verb_pl):
    """'רשומה אחת שסומנה' / '3 רשומות שסומנו'."""
    return f"רשומה אחת ש{verb_sg}" if k == 1 else f"{n(k)} רשומות ש{verb_pl}"


def p1(num, den):
    return round(num / den * 100, 1) if den else 0.0


def clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _flag(s):
    v = pd.to_numeric(s.astype(str).str.strip(), errors="coerce").fillna(0)
    return (v > 0).astype(int)


def _schools(raw):
    d = pd.DataFrame({
        "ecode": raw["cod_ezor"].map(clean),
        "office": raw["ezor"].map(clean),
        "code": raw["cod_beit_sefer"].map(clean),
        "name": raw["shem_beit_sefer"].map(clean),
        "mgr": raw["menahel"].map(clean),
    })
    for c in CLS_COLS:
        d[c] = _flag(raw[c])
    d = d[(d["name"] != "") | (d["code"] != "")]
    fake = d["name"].str.contains("פיקטיבי", regex=False)
    n_fake = int(fake.sum())
    d = d[~fake].copy()
    d.loc[d["office"] == "", "office"] = "אזור לא ידוע"
    d["district"] = d["office"].map(district_of)
    d["k"] = d[CLS_COLS].sum(axis=1).astype(int)
    d["seg"] = [SEG_CAR if p else (SEG_HEAVY if k else SEG_NONE) for p, k in zip(d["prati"], d["k"])]
    d["combo"] = d[CLS_COLS].astype(str).agg("".join, axis=1)
    d["ecn"] = pd.to_numeric(d["ecode"], errors="coerce").fillna(10 ** 6)
    d = d.sort_values(["ecn", "office", "name", "code", "combo", "mgr"], kind="mergesort").reset_index(drop=True)
    return d, n_fake


def _combo_label(combo):
    parts = [CLS_LABEL[c] for c, f in zip(CLS_COLS, combo) if f == "1"]
    if len(parts) == len(CLS_COLS):
        return "כל סוגי הרכב"
    return " + ".join(parts) if parts else SEG_NONE


def _dist_order(names):
    known = [x for x in DIST_ORDER if x in names]
    rest = sorted(x for x in names if x not in DIST_ORDER and x != UNASSIGNED)
    return known + rest + ([UNASSIGNED] if UNASSIGNED in names else [])


def compute(frames):
    d, n_fake = _schools(frames["main"])
    total = len(d)
    offices = d.groupby("office").agg(cnt=("name", "size"), ecn=("ecn", "min")).reset_index()
    for s in SEG_ORDER:
        offices[s] = offices["office"].map(d[d["seg"] == s].groupby("office").size()).fillna(0).astype(int)
    offices = offices.sort_values(["cnt", "ecn", "office"], ascending=[False, True, True], kind="mergesort")
    n_off = len(offices)

    cls_n = {c: int(d[c].sum()) for c in CLS_COLS}
    car_n = cls_n["prati"]
    seg_n = {s: int((d["seg"] == s).sum()) for s in SEG_ORDER}
    none_n = seg_n[SEG_NONE]
    heavy_n = seg_n[SEG_HEAVY]
    active = d[d["k"] > 0]
    n_active = len(active)

    # ---- offices (top N) ----
    top_off = offices.head(TOP_OFFICES)
    rest_off = n_off - len(top_off)
    rest_cnt = int(offices["cnt"].iloc[len(top_off):].sum())
    offices_chart = {
        "names": top_off["office"].tolist(),
        "series": [{"name": s, "data": top_off[s].astype(int).tolist(), "color": SEG_COLOR[s]} for s in SEG_ORDER
                   if int(top_off[s].sum()) > 0],
    }
    offices_table = [{"name": o, "count": n(c), "car": n(a), "heavy": n(h), "none": n(z)}
                     for o, c, a, h, z in zip(top_off["office"], top_off["cnt"], top_off[SEG_CAR],
                                              top_off[SEG_HEAVY], top_off[SEG_NONE])]

    # ---- districts ----
    dist_names = _dist_order(set(d["district"]))
    dg = d.groupby("district")
    dist_cnt = dg.size()
    dist_off = d.drop_duplicates(["district", "office"]).groupby("district").size()
    districts_chart = {
        "names": dist_names,
        "series": [{"name": s, "color": SEG_COLOR[s],
                    "data": [int(((d["district"] == x) & (d["seg"] == s)).sum()) for x in dist_names]}
                   for s in SEG_ORDER if seg_n[s] > 0],
    }
    districts_table = [{"name": x, "count": n(dist_cnt.get(x, 0)), "offices": n(dist_off.get(x, 0)),
                        "share": f"{p1(dist_cnt.get(x, 0), total):.1f}%"} for x in dist_names]
    unassigned_n = int(dist_cnt.get(UNASSIGNED, 0))

    # ---- classes ----
    cls_sorted = sorted(CLASSES, key=lambda t: (-cls_n[t[0]], CLS_COLS.index(t[0])))
    classes_chart = {"names": [l for _, l, _ in cls_sorted], "values": [cls_n[c] for c, _, _ in cls_sorted],
                     "shares": [p1(cls_n[c], total) for c, _, _ in cls_sorted]}
    classes_table = [{"name": l, "count": n(cls_n[c]), "share": f"{p1(cls_n[c], total):.1f}%"}
                     for c, l, _ in cls_sorted]

    # ---- breadth ----
    kmax = len(CLS_COLS)
    br = d["k"].value_counts()
    breadth_chart = {"names": [str(k) for k in range(kmax + 1)], "values": [int(br.get(k, 0)) for k in range(kmax + 1)]}
    breadth_table = [{"name": str(k), "count": n(br.get(k, 0)), "share": f"{p1(br.get(k, 0), total):.1f}%"}
                     for k in range(kmax + 1)]
    mean_k = round(math.fsum(active["k"].tolist()) / n_active, 1) if n_active else 0.0
    full_df = d[d["k"] == kmax].sort_values(["name", "office", "code"], kind="mergesort")
    full_n = len(full_df)

    # ---- combos ----
    cb = d.groupby("combo").size().reset_index(name="cnt")
    cb = cb.sort_values(["cnt", "combo"], ascending=[False, False], kind="mergesort")
    top_cb = cb.head(TOP_COMBOS)
    other_cb = int(cb["cnt"].iloc[len(top_cb):].sum())
    combo_names = [_combo_label(c) for c in top_cb["combo"]]
    combo_vals = top_cb["cnt"].astype(int).tolist()
    if other_cb:
        combo_names.append("צירופים אחרים")
        combo_vals.append(other_cb)
    combos_chart = {"names": combo_names, "values": combo_vals}
    combos_table = [{"name": a, "count": n(b), "share": f"{p1(b, total):.1f}%"} for a, b in zip(combo_names, combo_vals)]
    n_combos = len(cb)

    # ---- co-occurrence: of schools teaching row class, % that also teach column class ----
    cls_lab = [l for _, l, _ in cls_sorted]
    cls_c = [c for c, _, _ in cls_sorted]
    cells, cooc_rows = [], []
    for yi, a in enumerate(cls_c):
        sub = d[d[a] == 1]
        vals = []
        for xi, b in enumerate(cls_c):
            v = p1(int(sub[b].sum()), len(sub)) if len(sub) else 0.0
            cells.append([xi, yi, v, int(sub[b].sum())])
            vals.append(f"{v:.0f}%")
        cooc_rows.append({"name": cls_lab[yi], "vals": vals})
    cooc_chart = {"x": cls_lab, "y": cls_lab, "cells": cells}

    # ---- district × class share ----
    dist_cmp = [x for x in dist_names if x != UNASSIGNED]
    dcells, dc_rows = [], []
    dist_share = {}
    for yi, x in enumerate(dist_cmp):
        sub = d[d["district"] == x]
        vals = []
        for xi, c in enumerate(cls_c):
            v = p1(int(sub[c].sum()), len(sub))
            dist_share[(x, c)] = v
            dcells.append([xi, yi, v, int(sub[c].sum())])
            vals.append(f"{v:.0f}%")
        dc_rows.append({"name": x, "vals": vals})
    distclass_chart = {"x": cls_lab, "y": dist_cmp, "cells": dcells}

    # ---- gaps: licensing regions with no school for a class ----
    og = d.groupby("office")[CLS_COLS].sum()
    gaps = {c: int((og[c] == 0).sum()) for c in CLS_COLS}
    gap_sorted = sorted(CLASSES, key=lambda t: (-gaps[t[0]], CLS_COLS.index(t[0])))
    gaps_chart = {"names": [l for _, l, _ in gap_sorted], "values": [gaps[c] for c, _, _ in gap_sorted],
                  "covered": [n_off - gaps[c] for c, _, _ in gap_sorted], "total": n_off}
    gaps_table = [{"name": l, "missing": n(gaps[c]), "covered": n(n_off - gaps[c])} for c, l, _ in gap_sorted]

    # ---- full-range table ----
    full_table = [{"name": r.name or "ללא שם", "office": r.office, "district": r.district}
                  for r in full_df.head(FULL_CAP).itertuples(index=False)]
    full_more = max(0, full_n - FULL_CAP)

    # ---- managers ----
    mgr_known = d[d["mgr"] != ""]
    mgr_multi = int((mgr_known.groupby("mgr").size() > 1).sum())

    # ================= insights =================
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    def ins_leader():
        if n_off < 2:
            return None
        a, b = offices.iloc[0], offices.iloc[1]
        if a["cnt"] < b["cnt"] * LEAD_RATIO:
            return None
        top5 = int(offices["cnt"].head(5).sum())
        return (f"אזור הרישוי {a['office']} מוביל עם {n(a['cnt'])} בתי ספר לנהיגה ({pct(p1(a['cnt'], total))} מהרשימה) — "
                f"לעומת {n(b['cnt'])} ב{b['office']} שבמקום השני. חמשת האזורים הגדולים מרכזים יחד "
                f"{n(top5)} בתי ספר ({pct(p1(top5, total))}) מתוך {n(n_off)} אזורים.")

    def ins_car():
        if not total:
            return None
        s = (f"{n(car_n)} בתי ספר ({pct(p1(car_n, total))}) מורשים ללמד רכב פרטי")
        if heavy_n:
            s += (f"; {n(heavy_n)} נוספים אינם מלמדים רכב פרטי כלל ומתמחים רק ברכב כבד או מקצועי "
                  f"(משאית, אוטובוס, גורר, טרקטור או אופנוע)")
            hv = d[d["seg"] == SEG_HEAVY].groupby("combo").size().reset_index(name="k")
            hv = hv.sort_values(["k", "combo"], ascending=[False, False], kind="mergesort")
            if len(hv) and hv["k"].iloc[0] >= 2 and hv["k"].iloc[0] * 3 >= heavy_n:
                s += (f". הצירוף הנפוץ בקרב המתמחים: {_combo_label(hv['combo'].iloc[0])} — "
                      f"{n(hv['k'].iloc[0])} בתי ספר")
        return s + "."

    def ins_truck():
        cars = d[d["prati"] == 1]
        if len(cars) < 10:
            return None
        both = int(cars["masa"].sum())
        sh = p1(both, len(cars))
        if sh < 50:
            return None
        return (f"רוב בתי הספר לרכב פרטי מלמדים גם נהיגה במשאית: {n(both)} מתוך {n(len(cars))} ({pct(sh)}). "
                f"הצירוף הנפוץ ביותר ברשימה הוא {_combo_label(top_cb['combo'].iloc[0])} — "
                f"{n(top_cb['cnt'].iloc[0])} בתי ספר.")

    def ins_gap():
        c, l, _ = gap_sorted[0]
        if gaps[c] < 1 or n_off < 5:
            return None
        g2 = gap_sorted[1]
        s = f"ב-{n(gaps[c])} מתוך {n(n_off)} אזורי הרישוי אין אף בית ספר המורשה ללמד {l}"
        if gaps[g2[0]] >= 1:
            s += f", וב-{n(gaps[g2[0]])} אין בית ספר ל{g2[1]}"
        return s + "."

    def ins_full():
        if not full_n:
            return None
        names = [r["name"] for r in full_table[:3]]
        lead = "בהם " + ", ".join(names) if names else ""
        return (f"{n(full_n)} בתי ספר מורשים ללמד את כל {n(kmax)} סוגי הרכב ({lead}); "
                f"בתי ספר שמלמדים לפחות סוג אחד מלמדים בממוצע {mean_k:.1f} סוגים.")

    def ins_district():
        big = [x for x in dist_cmp if dist_cnt.get(x, 0) >= MIN_DIST]
        if len(big) < 3:
            return None
        best = None
        for c in cls_c:
            if c == "prati":
                continue
            vals = sorted(((dist_share[(x, c)], x) for x in big), key=lambda t: (t[0], t[1]))
            lo, hi = vals[0], vals[-1]
            gap = hi[0] - lo[0]
            if best is None or gap > best[0] + 1e-9:
                best = (gap, c, hi, lo)
        if best is None or best[0] < 15:
            return None
        gap, c, hi, lo = best
        return (f"הפער האזורי הגדול ביותר הוא ב{CLS_LABEL[c]}: במחוז {hi[1]} {pct(hi[0], 0)} מבתי הספר מלמדים אותו, "
                f"לעומת {pct(lo[0], 0)} בלבד במחוז {lo[1]} (מחוזות עם {n(MIN_DIST)} בתי ספר לפחות).")

    def ins_none():
        if not none_n:
            return None
        s = (f"{n(none_n)} רשומות ({pct(p1(none_n, total))}) אינן מסמנות אף סוג רכב — "
             f"ככל הנראה פער ברישום ולא בתי ספר ללא הרשאה")
        if n_fake:
            s += (f"; {records(n_fake, 'סומנה כפיקטיבית', 'סומנו כפיקטיביות')} "
                  f"{'הוצאה' if n_fake == 1 else 'הוצאו'} מכל הספירות")
        return s + "."

    add("leader", ins_leader())
    add("car", ins_car())
    add("truck", ins_truck())
    add("gap", ins_gap())
    add("district", ins_district())
    add("full", ins_full())
    add("none", ins_none())

    # ================= KPIs =================
    car_share = p1(car_n, total)
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "offices": {"value": n_off, "display": n(n_off), "tone": "brand"},
        "car": {"value": car_share, "display": f"{car_share:.1f}%", "tone": "info"},
        "full": {"value": full_n, "display": n(full_n), "tone": "ok" if full_n else "warn"},
        "none": {"value": none_n, "display": n(none_n),
                 "tone": "ok" if none_n == 0 else ("danger" if p1(none_n, total) >= 15 else "warn")},
    }

    lead = offices.iloc[0] if n_off else None
    top_cls = cls_sorted[0]
    rare_cls = cls_sorted[-1]
    fake_note = (f" {records(n_fake, 'סומנה כפיקטיבית', 'סומנו כפיקטיביות')} אינה נספרת." if n_fake == 1 else
                 f" {records(n_fake, 'סומנה כפיקטיבית', 'סומנו כפיקטיביות')} אינן נספרות." if n_fake else "")
    labels = {
        "lede": (f"רשימת משרד התחבורה של {n(total)} בתי ספר לנהיגה ב-{n(n_off)} אזורי רישוי, "
                 f"עם סוגי הרכב שכל בית ספר מורשה ללמד. {n(car_n)} מהם ({pct(car_share)}) מלמדים רכב פרטי; "
                 f"{rare_cls[1]} הוא הסוג הנדיר ביותר — {n(cls_n[rare_cls[0]])} בתי ספר בלבד.{fake_note}"),
        "total_kpi": "בתי ספר לנהיגה ברשימה",
        "offices_kpi": "אזורי רישוי",
        "car_kpi": "מלמדים רכב פרטי",
        "full_kpi": f"מורשים לכל {n(kmax)} סוגי הרכב",
        "none_kpi": "רשומות ללא סוג רכב",
        "offices_note": (f"{n(len(top_off))} אזורי הרישוי עם מספר בתי הספר הגדול ביותר, לפי סוג ההכשרה. "
                         + (f"מוביל: {lead['office']} עם {n(lead['cnt'])} בתי ספר. " if lead is not None else "")
                         + (f"{n(rest_off)} אזורים נוספים מונים יחד {n(rest_cnt)} בתי ספר." if rest_off else "")),
        "offices_aria": f"תרשים עמודות אופקי: בתי ספר לנהיגה ב-{n(len(top_off))} אזורי הרישוי הגדולים",
        "offices_caption": "בתי ספר לנהיגה לפי אזור רישוי ולפי סוג ההכשרה",
        "districts_note": (f"אזורי הרישוי שויכו למחוזות לפי היישוב שבו נמצאת לשכת הרישוי."
                           + (f" {n(unassigned_n)} בתי ספר באזורים שלא זוהו מופיעים תחת „{UNASSIGNED}”." if unassigned_n else "")),
        "districts_aria": "תרשים עמודות מוערמות: בתי ספר לנהיגה לפי מחוז ולפי סוג ההכשרה",
        "districts_caption": "בתי ספר לנהיגה ואזורי רישוי לפי מחוז",
        "classes_note": (f"{top_cls[1]} נלמד ב-{n(cls_n[top_cls[0]])} בתי ספר ({pct(p1(cls_n[top_cls[0]], total))}); "
                         f"{rare_cls[1]} ב-{n(cls_n[rare_cls[0]])} בלבד ({pct(p1(cls_n[rare_cls[0]], total))}). "
                         f"בית ספר יכול להיות מורשה לכמה סוגים, ולכן הסכום עולה על מספר בתי הספר."),
        "classes_aria": "תרשים עמודות: מספר בתי הספר המורשים ללמד כל סוג רכב",
        "classes_caption": "בתי ספר לנהיגה לפי סוג רכב נלמד",
        "breadth_note": (f"כמה סוגי רכב כל בית ספר מורשה ללמד. הקבוצה הגדולה: "
                         f"{breadth_chart['names'][max(range(kmax + 1), key=lambda k: (breadth_chart['values'][k], -k))]} סוגים "
                         f"({n(max(breadth_chart['values']))} בתי ספר); ממוצע {mean_k:.1f} סוגים בקרב בתי ספר עם סוג רשום."),
        "breadth_aria": "תרשים עמודות: התפלגות בתי הספר לפי מספר סוגי הרכב שהם מלמדים",
        "breadth_caption": "בתי ספר לנהיגה לפי מספר סוגי הרכב הנלמדים",
        "combos_note": (f"{n(n_combos)} צירופים שונים של סוגי רכב מופיעים ברשימה; "
                        f"{n(len(top_cb))} הנפוצים מכסים {n(sum(combo_vals) - other_cb)} בתי ספר "
                        f"({pct(p1(sum(combo_vals) - other_cb, total))})."),
        "combos_aria": f"תרשים עמודות אופקי: {n(len(top_cb))} צירופי סוגי הרכב הנפוצים",
        "combos_caption": "צירופי סוגי רכב נפוצים בבתי הספר לנהיגה",
        "cooc_note": ("כל שורה היא סוג רכב: איזה אחוז מבתי הספר שמלמדים אותו מלמדים גם את סוג הרכב שבעמודה. "
                      "למשל, השורה „אוטובוס” מראה מה עוד מציעים בתי הספר לאוטובוסים."),
        "cooc_aria": "מפת חום: שיעור בתי הספר המלמדים סוג רכב אחד שמלמדים גם סוג אחר",
        "cooc_caption": "שיעור בתי הספר המלמדים גם סוג רכב נוסף (שורה: הסוג הנלמד; עמודה: הסוג הנוסף)",
        "distclass_note": "אחוז בתי הספר בכל מחוז המורשים ללמד כל סוג רכב — היכן קל יותר למצוא הכשרה לרכב כבד.",
        "distclass_aria": "מפת חום: אחוז בתי הספר המלמדים כל סוג רכב, לפי מחוז",
        "distclass_caption": "אחוז בתי הספר המלמדים כל סוג רכב, לפי מחוז",
        "gaps_note": (f"בכמה מתוך {n(n_off)} אזורי הרישוי אין אף בית ספר המורשה ללמד כל סוג רכב, "
                      f"ובכמה יש לפחות אחד."),
        "gaps_aria": "תרשים עמודות מוערמות: אזורי רישוי עם ובלי בית ספר לכל סוג רכב",
        "gaps_caption": "אזורי רישוי ללא בית ספר לכל סוג רכב",
        "full_note": (f"{n(full_n)} בתי ספר מורשים ללמד את כל {n(kmax)} סוגי הרכב"
                      + (f"; מוצגים {n(FULL_CAP)} הראשונים לפי שם, ועוד {n(full_more)}." if full_more else ".")
                      + " השמות כפי שנרשמו במאגר (חלקם מקוצרים)."),
        "full_caption": "בתי ספר לנהיגה המורשים לכל סוגי הרכב",
        "mgr_note": (f"שמות המנהלים רשומים ב-{n(len(mgr_known))} רשומות; {n(mgr_multi)} מנהלים מופיעים ביותר מבית ספר אחד."),
    }

    charts = {
        "offices": offices_chart, "districts": districts_chart, "classes": classes_chart,
        "breadth": breadth_chart, "combos": combos_chart, "cooc": cooc_chart,
        "distclass": distclass_chart, "gaps": gaps_chart,
    }
    tables = {
        "offices": offices_table, "districts": districts_table, "classes": classes_table,
        "breadth": breadth_table, "combos": combos_table, "cooc": cooc_rows, "cls_cols": cls_lab,
        "distclass": dc_rows, "gaps": gaps_table, "full": full_table,
    }
    flags = {"full": bool(full_n), "distclass": len(dist_cmp) >= 2}

    return {
        "agent_data": {
            "summary_he": (f"רשימת משרד התחבורה של {n(total)} בתי ספר לנהיגה ב-{n(n_off)} אזורי רישוי — "
                           f"היכן הם פועלים ואילו סוגי רכב כל אחד מהם מורשה ללמד: רכב פרטי, משאית, אופנוע, "
                           f"אוטובוס, גורר וטרקטור."),
            "dataset_kind": "registry",
            "suggested_tags": ["בתי ספר לנהיגה", "רישיון נהיגה", "לימוד נהיגה", "רכב כבד", "משרד התחבורה"],
            "related_ids": ["35c791ca-8db2-4657-8c6f-eb092147a6bb",
                            "392abd0a-64f6-4c18-9d56-0111001411e6",
                            "0219b34f-43c7-435b-bdfe-e65e944cde50",
                            "0f16b39a-6016-408d-805d-31f40d5a0990"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
