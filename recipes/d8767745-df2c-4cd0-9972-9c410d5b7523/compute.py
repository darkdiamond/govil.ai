"""מספרי דרכים ארציות: משרד התחבורה (צוות חצב).

One row per road segment of the national road-numbering layer (the GIS
shapefile flattened to CSV, geometry dropped): the road number (`ROADNUMBER`,
empty on ramps), the road class (`ROADCLASS`: מהירה / ראשית / אזורית /
מקומית, empty or "<Null>" on ramps), the link type (`LINKTYPE`: numbered road,
ramp, service road), a ramp code or street name (`ROADNAME`, mostly blank on
numbered roads), a numbering-change code (`NUM_CHANGE`: 0 = unchanged,
otherwise a YYYYMM or YYYYMMDD stamp) and the segment length in metres
(`LENGT_M`; `Shape_Length` is the same value).

People search "רשימת דרכים" / "כביש <n>": the page leads with a lookup
callout to the explorer, lists every one- and two-digit road and every
three-digit road with its class and length, and then shows what the layer
carries: the longest roads, class mix, how the number of digits encodes the
class, the length distribution, how the numbering space is used, link types
and recent numbering changes.

Lengths are sums of segment lengths per road number (a divided road whose two
carriageways are drawn as separate segments counts both). Exact duplicate rows
(the same segment listed twice) are dropped, and the page says so.

Growth: the layer is replaced in place. New roads, classes and link types
flow through (known classes are ordered, unknown ones are appended), the
longest-roads chart is top-N, the regional list grows only up to the
three-digit space, and numbering-change codes are bucketed by month (an
unparseable code gets its own disclosed bucket).
"""
import pandas as pd

TOP_N = 20                 # longest roads on the bar chart
CLASS_ORDER = ["מהירה", "ראשית", "אזורית", "מקומית"]
CLASS_LABEL = {"מהירה": "דרך מהירה", "ראשית": "דרך ראשית",
               "אזורית": "דרך אזורית", "מקומית": "דרך מקומית"}
NO_CLASS = "ללא דרגה"
CLASS_PLURAL = {"מהירה": "דרכים מהירות", "ראשית": "דרכים ראשיות",
                "אזורית": "דרכים אזוריות", "מקומית": "דרכים מקומיות"}
NUMBERED = "דרך ממוספרת"
RAMP = "רמפה"
DIGIT_LABEL = {1: "חד-ספרתיות", 2: "דו-ספרתיות", 3: "תלת-ספרתיות", 4: "ארבע ספרות"}
DIGIT_PHRASE = {1: "בנות ספרה אחת", 2: "הדו-ספרתיות", 3: "התלת-ספרתיות", 4: "בנות ארבע הספרות"}
LEN_BINS = [(0, 1, "עד 1"), (1, 2, "1-2"), (2, 5, "2-5"), (5, 10, "5-10"),
            (10, 20, "10-20"), (20, 50, "20-50"), (50, 100, "50-100"),
            (100, float("inf"), "100 ומעלה")]
ALIGN_SHARE = 0.9          # "digits encode the class" needs >= this share per length
TOP10_SHARE = 0.15         # concentration insight threshold
LRI, PDI = "⁦", "⁩"


def n(v):
    return f"{int(round(v)):,}"


def km(v, digits=1):
    return f"{v:,.{digits}f}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def clean(s):
    return " ".join(str(s).split())


def class_key(c):
    return (CLASS_ORDER.index(c) if c in CLASS_ORDER else len(CLASS_ORDER), c)


def class_label(c):
    return CLASS_LABEL.get(c, c if c else NO_CLASS)


def change_month(code):
    """'202305' / '20250921' -> '2023-05'; '0' / '' -> None; garbage -> '?'."""
    c = clean(code)
    if c in ("", "0"):
        return None
    if c.isdigit() and len(c) in (6, 8):
        y, m = int(c[:4]), int(c[4:6])
        if 1948 <= y <= 2200 and 1 <= m <= 12:
            return f"{y:04d}-{m:02d}"
    return "?"


def month_he(key):
    y, m = key.split("-")
    return f"{m}/{y}"


def segs_he(k):
    return "מקטע אחד" if k == 1 else f"-{n(k)} מקטעים"


def roads_he(k):
    return "דרך אחת" if k == 1 else f"-{n(k)} דרכים"


def compute(frames):
    raw = frames["main"].copy()
    cols = ["ROADNUMBER", "ROADCLASS", "LINKTYPE", "NUM_CHANGE", "LENGT_M", "ROADNAME"]
    for c in cols:
        raw[c] = raw[c].map(clean)
    total_rows = len(raw)
    df = raw.drop_duplicates(subset=cols).copy()
    dup_rows = total_rows - len(df)
    df["L"] = pd.to_numeric(df["LENGT_M"].str.replace(",", "", regex=False), errors="coerce")
    df = df[df["L"].notna() & (df["L"] >= 0)].copy()
    df["cls"] = df["ROADCLASS"].where(~df["ROADCLASS"].isin(["", "<Null>"]), "")
    df["num"] = pd.to_numeric(df["ROADNUMBER"], errors="coerce")
    seg_total = len(df)
    km_total = df["L"].sum() / 1000

    # ---- link types ---------------------------------------------------
    lt = (df.assign(lt=df["LINKTYPE"].replace("", "לא צוין"))
            .groupby("lt").agg(segs=("L", "size"), m=("L", "sum")).reset_index())
    lt = lt.sort_values(["segs", "lt"], ascending=[False, True])
    link = {"names": lt["lt"].tolist(), "segs": [int(v) for v in lt["segs"]],
            "km": [round(v / 1000, 1) for v in lt["m"]]}
    ramps = df[df["LINKTYPE"] == RAMP]
    ramp_segs, ramp_km = len(ramps), ramps["L"].sum() / 1000

    # ---- numbered roads -----------------------------------------------
    r = df[(df["LINKTYPE"] == NUMBERED) & df["num"].notna() & (df["num"] > 0)].copy()
    r["rn"] = r["num"].astype(int)
    r["dig"] = r["rn"].astype(str).str.len()
    per_cls = (r.groupby(["rn", "cls"])["L"].sum().reset_index()
                 .sort_values(["rn", "L", "cls"], ascending=[True, False, True]))
    main_cls = per_cls.drop_duplicates("rn").set_index("rn")["cls"]
    roads = r.groupby("rn").agg(m=("L", "sum"), segs=("L", "size"),
                                ncls=("cls", "nunique"), dig=("dig", "first"))
    roads["cls"] = main_cls
    roads["km"] = roads["m"] / 1000
    roads = roads.reset_index()
    n_roads = len(roads)
    road_km = roads["km"].sum()

    # longest roads
    top = roads.sort_values(["km", "rn"], ascending=[False, True]).head(TOP_N)
    classes = sorted(set(roads["cls"]), key=class_key)
    top_chart = {
        "names": [f"כביש {v}" for v in top["rn"]],
        "km": [round(v, 1) for v in top["km"]],
        "cls": [class_label(c) for c in top["cls"]],
        "classes": [class_label(c) for c in classes],
    }
    top_table = [{"name": f"כביש {a.rn}", "cls": class_label(a.cls), "km": km(a.km),
                  "segs": n(a.segs)} for a in top.itertuples()]

    # by class (main class of each road; km by segment class)
    seg_cls = r.groupby("cls")["L"].sum() / 1000
    road_cls = roads.groupby("cls").size()
    cls_rows = [{"key": c, "name": class_label(c), "roads": int(road_cls.get(c, 0)),
                 "km": float(seg_cls.get(c, 0.0))} for c in classes]
    class_chart = {"names": [x["name"] for x in cls_rows],
                   "roads": [x["roads"] for x in cls_rows],
                   "km": [round(x["km"], 1) for x in cls_rows]}
    class_table = [{"name": x["name"], "roads": n(x["roads"]), "km": km(x["km"]),
                    "share": pct(x["km"] / road_km if road_km else 0)} for x in cls_rows]

    # digits x class
    digs = sorted(set(roads["dig"]))
    ct = roads.groupby(["dig", "cls"]).size()
    digit_chart = {
        "names": [DIGIT_LABEL.get(d, f"{d} ספרות") for d in digs],
        "series": [{"name": class_label(c), "data": [int(ct.get((d, c), 0)) for d in digs]}
                   for c in classes],
    }
    digit_table = []
    align = []
    for d in digs:
        sub = roads[roads["dig"] == d]
        counts = sub.groupby("cls").size().reset_index(name="k")
        counts["o"] = counts["cls"].map(lambda c: class_key(c))
        counts = counts.sort_values(["k", "o"], ascending=[False, True])
        lead_c, lead_k = counts.iloc[0]["cls"], int(counts.iloc[0]["k"])
        digit_table.append({"name": DIGIT_LABEL.get(d, f"{d} ספרות"), "roads": n(len(sub)),
                            "km": km(sub["km"].sum()), "lead": class_label(lead_c),
                            "share": pct(lead_k / len(sub))})
        align.append((d, lead_c, lead_k, len(sub)))

    # length distribution
    hist = []
    for lo, hi, lab in LEN_BINS:
        hist.append(int(((roads["km"] >= lo) & (roads["km"] < hi)).sum()))
    keep = list(range(len(hist)))
    len_chart = {"names": [LEN_BINS[i][2] for i in keep], "roads": [hist[i] for i in keep]}
    len_table = [{"name": LEN_BINS[i][2], "roads": n(hist[i]),
                  "share": pct(hist[i] / n_roads if n_roads else 0)} for i in keep]
    median_km = float(roads["km"].median()) if n_roads else 0.0

    # numbering space: leading digit x number of digits
    roads["lead"] = roads["rn"].astype(str).str[0].astype(int)
    space = roads.groupby(["dig", "lead"]).size()
    cells = []
    for yi, d in enumerate(digs):
        for xi, ld in enumerate(range(1, 10)):
            cells.append([xi, yi, int(space.get((d, ld), 0))])
    space_chart = {"x": [str(i) for i in range(1, 10)],
                   "y": [DIGIT_LABEL.get(d, f"{d} ספרות") for d in digs],
                   "cells": cells, "max": max([c[2] for c in cells] + [1])}
    space_table = [{"name": DIGIT_LABEL.get(d, f"{d} ספרות"),
                    "cells": [n(space.get((d, ld), 0)) for ld in range(1, 10)]} for d in digs]

    # road lists (1-2 digits shown open; 3 digits collapsed)
    def road_rows(sub):
        sub = sub.sort_values("rn")
        return [{"num": int(a.rn), "cls": class_label(a.cls), "km": km(a.km),
                 "segs": n(a.segs), "mixed": bool(a.ncls > 1)} for a in sub.itertuples()]
    main_list = road_rows(roads[roads["dig"] <= 2])
    regional_list = road_rows(roads[roads["dig"] == 3])
    local_count = int((roads["dig"] >= 4).sum())
    mixed = roads[roads["ncls"] > 1].sort_values("rn")

    # ---- numbering changes ----------------------------------------------
    df["chg"] = df["NUM_CHANGE"].map(change_month)
    ch = df[df["chg"].notna()].copy()
    ch_valid = ch[ch["chg"] != "?"]
    months = sorted(set(ch_valid["chg"]))
    bad_codes = int((ch["chg"] == "?").sum())
    def roads_in(sub):
        v = pd.to_numeric(sub["ROADNUMBER"], errors="coerce")
        return int(v[v > 0].nunique())
    change_chart = {"names": [month_he(m) for m in months],
                    "segs": [int((ch_valid["chg"] == m).sum()) for m in months],
                    "roads": [roads_in(ch_valid[ch_valid["chg"] == m]) for m in months]}
    change_table = [{"name": change_chart["names"][i], "segs": n(change_chart["segs"][i]),
                     "roads": n(change_chart["roads"][i])} for i in range(len(months))]
    if bad_codes:
        change_table.append({"name": "קוד שאינו תאריך", "segs": n(bad_codes),
                             "roads": n(roads_in(ch[ch["chg"] == "?"]))})
    ch_segs, ch_roads = len(ch), roads_in(ch)

    # ---- insights -------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if n_roads:
        lead = top.iloc[0]
        add("longest", f"כביש {int(lead.rn)} הוא הארוך ברשת: {km(lead.km)} ק\"מ של מקטעים "
            f"({class_label(lead.cls)}), {pct(lead.km / road_km)} מאורך כל הדרכים הממוספרות. "
            f"אחריו כביש {int(top.iloc[1].rn)} ({km(top.iloc[1].km)} ק\"מ) וכביש "
            f"{int(top.iloc[2].rn)} ({km(top.iloc[2].km)} ק\"מ)." if len(top) >= 3 else None)

    good = [a for a in align if a[3] >= 5 and a[2] / a[3] >= ALIGN_SHARE and a[1]]
    big = [a for a in align if a[0] >= 3 and a[3] >= 5]
    if big and all(a in good for a in big):
        parts = [f"{pct(a[2] / a[3], 0)} מהדרכים {DIGIT_PHRASE.get(a[0], f"בנות {a[0]} ספרות")} הן "
                 f"{CLASS_PLURAL.get(a[1], class_label(a[1]))}" for a in big]
        add("digits", "מספר הספרות מסגיר את דרגת הדרך: " + " ו-".join(parts) + ".")

    top10 = roads.sort_values(["km", "rn"], ascending=[False, True]).head(10)
    s10 = top10["km"].sum() / road_km if road_km else 0
    if n_roads >= 50 and s10 >= TOP10_SHARE:
        add("concentration", f"עשרת הכבישים הארוכים מחזיקים {pct(s10)} מאורך הרשת הממוספרת "
            f"({km(top10['km'].sum(), 0)} מתוך {km(road_km, 0)} ק\"מ), אף שהם פחות מ-"
            f"{pct(10 / n_roads)} מ-{n(n_roads)} הדרכים.")

    if n_roads >= 20:
        sh = roads[roads["km"] < 1]
        short = len(sh)
        loc_share = (sh["cls"] == "מקומית").mean() if short else 0
        add("median", f"החציון: {km(median_km)} ק\"מ לדרך. {n(short)} דרכים "
            f"({pct(short / n_roads)}) קצרות מקילומטר"
            + (f", {pct(loc_share, 0)} מהן דרכים מקומיות." if loc_share >= 0.5 else "."))

    if seg_total and ramp_segs / seg_total >= 0.1:
        add("ramps", f"{n(ramp_segs)} מתוך {n(seg_total)} המקטעים ({pct(ramp_segs / seg_total)}) "
            f"הם רמפות של מחלפים, באורך כולל של {km(ramp_km, 0)} ק\"מ. לרמפות אין מספר דרך.")

    if len(mixed) >= 2:
        ex = ", ".join(str(int(v)) for v in mixed["rn"].head(4))
        add("mixed", f"{n(len(mixed))} דרכים משנות דרגה לאורכן, למשל כבישים {ex}: "
            "מקטעים שונים של אותו כביש מסווגים בדרגות שונות.")

    if ch_segs >= 5 and months:
        last = months[-1]
        last_segs = int((ch_valid["chg"] == last).sum())
        last_roads = roads_in(ch_valid[ch_valid["chg"] == last])
        busiest = max(months, key=lambda m: (int((ch_valid["chg"] == m).sum()), m))
        busiest_segs = int((ch_valid["chg"] == busiest).sum())
        txt = (f"{n(ch_segs)} מקטעים ב-{n(ch_roads)} דרכים מסומנים בשינוי מספור. "
               f"העדכון האחרון ({month_he(last)}) נגע ב{segs_he(last_segs)} ב{roads_he(last_roads)}")
        if busiest != last:
            txt += f", והגדול ביותר ({month_he(busiest)}) ב-{n(busiest_segs)} מקטעים"
        add("changes", txt + ".")

    # ---- KPIs, labels -----------------------------------------------------
    kpis = {
        "roads": {"value": n_roads, "display": n(n_roads), "tone": "brand"},
        "km": {"value": round(road_km, 1), "display": km(road_km, 0), "tone": "brand"},
        "ramps": {"value": ramp_segs, "display": n(ramp_segs), "tone": "brand"},
        "changes": {"value": ch_segs, "display": n(ch_segs), "tone": "info" if ch_segs else "brand"},
    }
    lead_txt = (f"כביש {int(top.iloc[0].rn)} ({km(top.iloc[0].km, 0)} ק\"מ)" if n_roads else "")
    labels = {
        "lede": (f"רשימת מספרי הדרכים הארציות שקבע המפקח הארצי על התעבורה: {n(n_roads)} כבישים "
                 f"ממוספרים באורך מקטעים כולל של {km(road_km, 0)} ק\"מ, מכבישים ראשיים חד- ודו-ספרתיים "
                 f"ועד דרכים מקומיות בנות ארבע ספרות, ועוד {n(ramp_segs)} מקטעי רמפה. "
                 f"הארוך ביותר: {lead_txt}. לכל דרך מופיעים דרגתה (מהירה, ראשית, אזורית או מקומית) "
                 "ואורכה, וגם מקטעים שמספרם שונה לאחרונה."),
        "roads_kpi": "כבישים ממוספרים",
        "km_kpi": "ק\"מ מקטעים בדרכים ממוספרות",
        "ramps_kpi": "מקטעי רמפה במחלפים",
        "changes_kpi": "מקטעים עם שינוי מספור",
        "main_note": (f"{n(len(main_list))} הכבישים בעלי ספרה אחת או שתיים, לפי מספר. האורך הוא סכום "
                      "אורכי המקטעים של הדרך; בדרך מחולקת שני מסלוליה עשויים להיספר בנפרד. "
                      "הדרגה היא זו של רוב אורך הדרך."),
        "main_caption": "רשימת הכבישים החד- והדו-ספרתיים: דרגה, אורך ומספר מקטעים",
        "reg_summary": f"הצג את {n(len(regional_list))} הכבישים התלת-ספרתיים (דרכים אזוריות)",
        "reg_caption": "רשימת הכבישים התלת-ספרתיים: דרגה, אורך ומספר מקטעים",
        "local_note": (f"{n(local_count)} הדרכים המקומיות בנות ארבע הספרות מופיעות בחיפוש "
                       "שמתחת לעמוד (חיפוש לפי מספר הדרך)."),
        "top_note": (f"{len(top)} הכבישים הארוכים לפי סכום אורכי המקטעים, צבועים לפי דרגת רוב אורכם. "
                     f"{lead_txt} מוביל."),
        "top_aria": (f"גרף עמודות אופקי: {len(top)} הכבישים הארוכים בישראל לפי אורך מקטעים. "
                     f"המוביל {lead_txt}."),
        "top_caption": f"{len(top)} הכבישים הארוכים לפי אורך מקטעים",
        "class_note": " ".join(
            f"{x['name']}: {n(x['roads'])} כבישים, {km(x['km'], 0)} ק\"מ." for x in cls_rows),
        "class_aria": ("גרף עמודות: מספר הכבישים ואורך המקטעים לפי דרגת דרך. "
                       + " ".join(f"{x['name']} {km(x['km'], 0)} ק\"מ." for x in cls_rows)),
        "class_caption": "כבישים ואורך מקטעים לפי דרגת דרך",
        "digit_note": "מספר הכבישים לפי מספר הספרות במספר הדרך, מחולק לפי דרגת הדרך. "
                      + " ".join(f"{t['name']}: {t['roads']} כבישים, {t['share']} מהן {t['lead']}."
                                 for t in digit_table),
        "digit_aria": "גרף עמודות מוערמות: כבישים לפי מספר ספרות ודרגת דרך. "
                      + " ".join(f"{t['name']}: {t['roads']}." for t in digit_table),
        "digit_caption": "כבישים לפי מספר הספרות ודרגת הדרך המובילה",
        "len_note": (f"התפלגות אורך המקטעים לכל כביש (ק\"מ). החציון {km(median_km)} ק\"מ; "
                     f"{n(hist[-1])} כבישים ארוכים מ-{LEN_BINS[-1][0]} ק\"מ."),
        "len_aria": (f"היסטוגרמה: {n(n_roads)} כבישים לפי טווח אורך בק\"מ. "
                     f"החציון {km(median_km)} ק\"מ."),
        "len_caption": "כבישים לפי טווח אורך (ק\"מ)",
        "space_note": ("כמה מספרי דרך תפוסים לפי הספרה הראשונה ומספר הספרות. כל משבצת סופרת "
                       "כבישים, למשל כבישים תלת-ספרתיים שמתחילים בספרה מסוימת."),
        "space_aria": (f"מפת חום: {n(n_roads)} מספרי דרך לפי ספרה ראשונה ומספר ספרות. "
                       f"התא הצפוף ביותר מכיל {n(space_chart['max'])} כבישים."),
        "space_caption": "כבישים לפי ספרה ראשונה (עמודות) ומספר ספרות (שורות)",
        "link_note": " ".join(f"{a}: {n(b)} מקטעים, {km(c, 0)} ק\"מ."
                              for a, b, c in zip(link["names"], link["segs"], link["km"])),
        "link_aria": ("גרף עמודות: מקטעים לפי סוג קישור. "
                      + " ".join(f"{a} {n(b)}." for a, b in zip(link["names"], link["segs"]))),
        "link_caption": "מקטעים ואורך לפי סוג קישור",
        "change_note": (f"מקטעים שסומנו בקוד שינוי מספור, לפי חודש השינוי ({n(ch_segs)} מקטעים ב-"
                        f"{n(ch_roads)} דרכים)."
                        + (f" {n(bad_codes)} מקטעים נושאים קוד שאינו תאריך תקין ומופיעים בטבלה בלבד."
                           if bad_codes else "")),
        "change_aria": (f"גרף עמודות: מקטעים עם שינוי מספור לפי חודש, {n(len(months))} חודשים. "
                        + (f"האחרון {month_he(months[-1])}." if months else "")),
        "change_caption": "מקטעים ודרכים עם שינוי מספור לפי חודש",
        "method": (f"המאגר כולל {n(total_rows)} מקטעים"
                   + (f"; {n(dup_rows)} שורות כפולות זהות הוסרו מהחישוב" if dup_rows else "")
                   + ". שכבת ה-GIS המלאה (קבצי SHP ו-KMZ) זמינה להורדה מתחת לעמוד."),
    }

    flags = {"changes": bool(months), "regional": bool(regional_list),
             "mixed_any": bool(len(mixed))}

    return {
        "agent_data": {
            "summary_he": (f"רשימת מספרי הדרכים הארציות: איתור כביש לפי מספר, דרגה ואורך. "
                           f"{n(n_roads)} כבישים ממוספרים, {km(road_km, 0)} ק\"מ, "
                           f"הארוך כביש {int(top.iloc[0].rn)}." if n_roads else
                           "רשימת מספרי הדרכים הארציות: איתור כביש לפי מספר, דרגה ואורך."),
            "dataset_kind": "registry",
            "suggested_tags": ["דרכים", "כבישים", "מספרי דרכים", "תחבורה", "תשתית", "מחלפים"],
            "related_ids": ["2a795952-3fb8-487b-bc25-6f563908abe9",
                            "09cbcff5-64fc-429b-96e5-881cbcab96af",
                            "0b22997e-676d-48d3-baee-c79846a1939f",
                            "27047419-e1fc-4f1d-bb15-7f5f0805d226"],
            "spatial_coverage": "ארצי",
        },
        "kpis": kpis,
        "charts": {"top": top_chart, "cls": class_chart, "digits": digit_chart,
                   "len": len_chart, "space": space_chart, "link": link,
                   "change": change_chart},
        "tables": {"top": top_table, "cls": class_table, "digits": digit_table,
                   "len": len_table, "space": space_table, "space_x": space_chart["x"],
                   "link": [{"name": a, "segs": n(b), "km": km(c)} for a, b, c in
                            zip(link["names"], link["segs"], link["km"])],
                   "change": change_table, "main": main_list, "regional": regional_list},
        "insights": insights,
        "labels": labels,
        "flags": flags,
    }
