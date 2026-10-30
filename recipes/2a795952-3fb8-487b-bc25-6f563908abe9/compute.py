"""Interchange codes on Israel's interurban road network (משרד התחבורה, צוות חצב).

One row per interchange: a two-letter code, a name, a type (מחלף, מחלפון,
פיצול, מחלף מערכתי, ...), up to three connecting road numbers (0 = none) and
the traffic authority responsible for it. The layer is a "current state"
snapshot, so there is no time axis: the page is about the network's shape
(which roads carry the most interchanges, who runs them, how roads meet).

Every number on the page comes from here. Each insight rule returns a
sentence or None when its premise doesn't hold in the data.
"""
import pandas as pd

ROAD_COLS = ["ROAD1", "ROAD2", "ROAD3"]
MISSING = "לא צוין"
OTHER = "אחר"

TOP_AUTH = 9        # authorities shown before an "אחר" bucket
TOP_ROADS = 15      # roads in the ranking chart
DIR_ROADS = 8       # roads that get an interchange list
DIR_ROWS = 80       # cap per road list
JUNCTION_ROWS = 60  # cap on the system-interchange / split directory
JUNCTION_TYPES = ("מחלף מערכתי", "פיצול")

# Israeli road numbering: 1-2 digits = national/main road, 3 = regional,
# 4 = local/access road. Ordered from the highest class down.
CLASSES = [("ראשי", "כביש ראשי (ספרה או שתיים)"),
           ("אזורי", "כביש אזורי (שלוש ספרות)"),
           ("מקומי", "כביש מקומי (ארבע ספרות)")]


def _int(n):
    return f"{int(n):,}"


def _pct(part, whole):
    return f"{part / whole * 100:.1f}%" if whole else "0.0%"


def _road_class(r):
    k = len(str(r))
    if k <= 2:
        return "ראשי"
    if k == 3:
        return "אזורי"
    return "מקומי"


def _prepare(df):
    df = df.copy()
    for c in ["MIHCODE", "MIHNAME", "MIHTYPE", "TRAFAUTH"]:
        df[c] = df[c].astype(str).str.strip()
    df["type"] = df["MIHTYPE"].where(df["MIHTYPE"] != "", MISSING)
    df["auth"] = df["TRAFAUTH"].where(df["TRAFAUTH"] != "", MISSING)
    for c in ROAD_COLS:
        v = pd.to_numeric(df[c].str.replace(",", "", regex=False), errors="coerce")
        df[c] = v.fillna(0).round().astype(int)
    # Distinct positive road numbers per interchange, in ROAD1..3 order.
    roads = []
    for r1, r2, r3 in zip(df["ROAD1"], df["ROAD2"], df["ROAD3"]):
        seen = []
        for r in (r1, r2, r3):
            if r > 0 and r not in seen:
                seen.append(r)
        roads.append(seen)
    df["roads"] = roads
    df["n_roads"] = df["roads"].map(len)
    df = df[(df["MIHNAME"] != "") | (df["MIHCODE"] != "")]
    return df.sort_values(["MIHCODE", "MIHNAME"], kind="stable").reset_index(drop=True)


def _counts(series):
    """Value counts sorted by count desc, then name (total order)."""
    vc = series.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _road_stats(df):
    rows = []
    for name, code, typ, roads in zip(df["MIHNAME"], df["MIHCODE"], df["type"], df["roads"]):
        for r in roads:
            rows.append((r, name, code, typ, tuple(x for x in roads if x != r)))
    if not rows:
        return pd.DataFrame(columns=["road", "n", "partners"]), {}
    long = pd.DataFrame(rows, columns=["road", "name", "code", "type", "others"])
    stats = []
    lists = {}
    for road, g in long.groupby("road", sort=True):
        partners = sorted({o for t in g["others"] for o in t})
        stats.append({"road": int(road), "n": int(len(g)), "partners": len(partners)})
        lists[int(road)] = g.sort_values(["name", "code"], kind="stable")
    st = pd.DataFrame(stats).sort_values(["n", "road"], ascending=[False, True], kind="stable")
    return st.reset_index(drop=True), lists


def _pair_kind(roads):
    if len(roads) < 2:
        return None
    rank = [k for k, _ in CLASSES]
    cls = sorted((_road_class(r) for r in roads), key=rank.index)
    return f"{cls[0]} עם {cls[1]}"


# ---------------------------------------------------------------- insights

def insight_types(types, total):
    if types.empty or total == 0:
        return None
    lead, n = types.index[0], int(types.iloc[0])
    if n / total < 0.4:
        return None
    s = f"{_int(n)} מתוך {_int(total)} הרשומות ({_pct(n, total)}) מסווגות כ{lead}"
    if len(types) > 1:
        t2, n2 = types.index[1], int(types.iloc[1])
        s += f", ואחריהן {t2} עם {_int(n2)} ({_pct(n2, total)})"
    return s + "."


def insight_auth(auths, total):
    named = auths.drop(labels=[MISSING], errors="ignore")
    if named.empty or total == 0:
        return None
    lead, n = named.index[0], int(named.iloc[0])
    if n / total < 0.3:
        return None
    return (f"{lead} היא רשות התמרור של {_int(n)} מחלפים ({_pct(n, total)} מהרשת). "
            f"בסך הכול רשומות {_int(len(named))} רשויות תמרור שונות.")


def insight_municipal(df, total):
    muni = df[df["auth"].str.startswith("עיריית")]
    if muni.empty or total == 0:
        return None
    by = _counts(muni["auth"])
    parts = ", ".join(f"{a} ({_int(v)})" for a, v in by.items())
    return (f"{_int(len(muni))} מחלפים ({_pct(len(muni), total)}) נמצאים באחריות רשות מקומית "
            f"ולא של חברת דרכים: {parts}.")


def insight_top_road(st):
    if len(st) < 2:
        return None
    a, b = st.iloc[0], st.iloc[1]
    if a["n"] <= b["n"]:
        return None
    s = (f"כביש {a['road']} הוא העמוס ביותר במחלפים: {_int(a['n'])} מחלפים לאורכו, "
         f"לעומת {_int(b['n'])} בכביש {b['road']}.")
    hub = st.sort_values(["partners", "n", "road"], ascending=[False, False, True],
                         kind="stable").iloc[0]
    if hub["partners"] >= 3:
        s += f" כביש {hub['road']} מתחבר במחלפים למספר הכבישים הגדול ביותר: {_int(hub['partners'])} כבישים ממוספרים."
    return s


def insight_single(df, total):
    single = int((df["n_roads"] == 1).sum())
    if total == 0 or single / total < 0.1:
        return None
    return (f"ב-{_int(single)} מחלפים ({_pct(single, total)}) רשום כביש ממוספר אחד בלבד: "
            f"המחלף מחבר אותו לרחובות או לדרכים שאינם ממוספרים.")


def insight_triple(df):
    tri = df[df["n_roads"] >= 3]
    if tri.empty:
        return None
    if len(tri) == 1:
        r = tri.iloc[0]
        return f"רק מחלף אחד, {r['MIHNAME']}, מחבר שלושה כבישים ממוספרים."
    ex = tri.sort_values(["MIHNAME", "MIHCODE"], kind="stable").iloc[0]
    roads = ", ".join(str(x) for x in ex["roads"])
    return (f"{_int(len(tri))} מחלפים מחברים שלושה כבישים ממוספרים או יותר, "
            f"למשל {ex['MIHNAME']} (כבישים {roads}).")


def insight_missing(df):
    miss = df[(df["type"] == MISSING) | (df["auth"] == MISSING) | (df["n_roads"] == 0)]
    if miss.empty:
        return None
    if len(miss) == 1:
        return (f"רשומה אחת ({miss.iloc[0]['MIHNAME']}) חסרה סוג, רשות תמרור או מספר כביש; "
                f"היא נספרת בגרפים תחת \"{MISSING}\".")
    return (f"{_int(len(miss))} רשומות חסרות סוג, רשות תמרור או מספר כביש; "
            f"הן נספרות בגרפים תחת \"{MISSING}\".")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    total = int(len(df))

    types = _counts(df["type"])
    auths = _counts(df["auth"])
    st, lists = _road_stats(df)
    n_roads_served = int(len(st))

    # Authority x type (stacked), top authorities + אחר.
    auth_order = list(auths.index[:TOP_AUTH])
    auth_bucket = df["auth"].where(df["auth"].isin(auth_order), OTHER)
    if (auth_bucket == OTHER).any():
        auth_order.append(OTHER)
    type_order = list(types.index)
    ct = pd.crosstab(auth_bucket, df["type"]).reindex(index=auth_order, columns=type_order,
                                                     fill_value=0)
    auth_chart = {
        "names": auth_order,
        "totals": [int(ct.loc[a].sum()) for a in auth_order],
        "series": [{"name": t, "data": [int(ct.loc[a, t]) for a in auth_order]}
                   for t in type_order],
    }
    auth_table = [{"name": a, "total": _int(ct.loc[a].sum()),
                   "share": _pct(ct.loc[a].sum(), total),
                   "cells": [_int(ct.loc[a, t]) for t in type_order]} for a in auth_order]

    # Roads ranking.
    top = st.head(TOP_ROADS)
    roads_chart = {"names": [f"כביש {r}" for r in top["road"]],
                   "n": [int(v) for v in top["n"]],
                   "partners": [int(v) for v in top["partners"]]}
    roads_table = [{"name": f"כביש {r['road']}", "n": _int(r["n"]),
                    "partners": _int(r["partners"])} for _, r in top.iterrows()]

    # Number of numbered roads per interchange.
    nr = df["n_roads"].value_counts().sort_index()
    nr_labels = {0: "ללא כביש ממוספר", 1: "כביש אחד", 2: "שני כבישים", 3: "שלושה כבישים"}
    nroads_chart = {"names": [nr_labels.get(int(k), f"{int(k)} כבישים") for k in nr.index],
                    "values": [int(v) for v in nr]}
    nroads_table = [{"name": n, "count": _int(v), "share": _pct(v, total)}
                    for n, v in zip(nroads_chart["names"], nroads_chart["values"])]

    # Road classes: every road reference, and the class pair at multi-road interchanges.
    class_names = [k for k, _ in CLASSES]
    refs = pd.Series([_road_class(r) for rs in df["roads"] for r in rs], dtype=object)
    ref_counts = refs.value_counts().reindex(class_names, fill_value=0)
    n_refs = int(ref_counts.sum())
    pairs = _counts(pd.Series([p for p in df["roads"].map(_pair_kind) if p], dtype=object))
    n_multi = int(pairs.sum())
    class_chart = {"names": [lbl for _, lbl in CLASSES],
                   "values": [int(ref_counts[k]) for k in class_names]}
    class_table = [{"name": lbl, "count": _int(ref_counts[k]), "share": _pct(ref_counts[k], n_refs)}
                   for k, lbl in CLASSES]
    pair_chart = {"names": [f"{p}" for p in pairs.index], "values": [int(v) for v in pairs]}
    pair_table = [{"name": p, "count": _int(v), "share": _pct(v, n_multi)}
                  for p, v in pairs.items()]

    # Directory: system interchanges and splits.
    jx = df[df["type"].isin(JUNCTION_TYPES)].sort_values(["type", "MIHNAME", "MIHCODE"],
                                                         kind="stable")
    junctions = [{"name": r["MIHNAME"], "code": r["MIHCODE"], "type": r["type"],
                  "roads": ", ".join(str(x) for x in r["roads"]) or MISSING,
                  "auth": r["auth"]} for _, r in jx.head(JUNCTION_ROWS).iterrows()]
    n_junctions = int(len(jx))

    # Directory: interchanges along the busiest roads.
    road_dirs = []
    for road in st.head(DIR_ROADS)["road"]:
        g = lists[int(road)]
        rows = [{"name": r["name"], "code": r["code"], "type": r["type"],
                 "others": ", ".join(str(x) for x in r["others"]) or "ללא"}
                for _, r in g.head(DIR_ROWS).iterrows()]
        road_dirs.append({"road": int(road), "label": f"כביש {road}", "count": _int(len(g)),
                          "rows": rows, "truncated": len(g) > DIR_ROWS})

    full = int(types.get("מחלף", 0))
    ramp = int(types.get("מחלפון", 0))
    lead_auth = auths.drop(labels=[MISSING], errors="ignore")
    lead_auth_name = lead_auth.index[0] if not lead_auth.empty else MISSING
    lead_auth_n = int(lead_auth.iloc[0]) if not lead_auth.empty else 0
    top_road = int(st.iloc[0]["road"]) if n_roads_served else 0
    top_road_n = int(st.iloc[0]["n"]) if n_roads_served else 0

    rules = [
        ("types", insight_types(types, total)),
        ("auth", insight_auth(auths, total)),
        ("top_road", insight_top_road(st)),
        ("single", insight_single(df, total)),
        ("triple", insight_triple(df)),
        ("municipal", insight_municipal(df, total)),
        ("missing", insight_missing(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    summary = (f"איתור מחלף לפי קוד, שם או מספר כביש: {_int(total)} מחלפים, מחלפונים ופיצולים "
               f"ברשת הדרכים הבין עירונית, על {_int(n_roads_served)} כבישים ממוספרים.")

    lede = (f"שכבת קודי המחלפים של משרד התחבורה מונה {_int(total)} נקודות חיבור ברשת הבין עירונית: "
            f"{_int(full)} מחלפים, {_int(ramp)} מחלפונים ועוד פיצולים, מחלפים מערכתיים וצמתים. "
            f"לכל מחלף קוד בן שתי אותיות, שם, עד שלושה כבישים מתחברים ורשות התמרור האחראית עליו. "
            f"המחלפים פרושים על {_int(n_roads_served)} כבישים ממוספרים, והעמוס שבהם הוא כביש {top_road} "
            f"עם {_int(top_road_n)} מחלפים.")

    lead_type = types.index[0] if len(types) else MISSING
    top_hub = (st.sort_values(["partners", "n", "road"], ascending=[False, False, True],
                              kind="stable").iloc[0] if n_roads_served else None)

    labels = {
        "lede": lede,
        "total_kpi": "מחלפים ונקודות חיבור במאגר",
        "full_kpi": "מחלפים מלאים (סוג מחלף)",
        "roads_kpi": "כבישים ממוספרים עם מחלף",
        "lead_auth_kpi": f"באחריות {lead_auth_name}",
        "types_note": (f"הסוג הנפוץ הוא {lead_type} ({_int(types.iloc[0])} רשומות). מחלפון הוא מחלף חלקי "
                       f"עם מעט רמפות; פיצול ומחלף מערכתי הם נקודות מפגש בין שני כבישים בין עירוניים."),
        "types_aria": (f"תרשים עמודות: מחלפים לפי סוג. {lead_type} מוביל עם "
                       f"{_int(types.iloc[0])} מתוך {_int(total)}."),
        "auth_note": (f"{lead_auth_name} אחראית על {_int(lead_auth_n)} מחלפים ({_pct(lead_auth_n, total)}). "
                      f"העמודות מפוצלות לפי סוג המחלף."
                      + (f" מוצגות {_int(TOP_AUTH)} הרשויות הגדולות, והשאר מקובצות תחת \"{OTHER}\"."
                         if OTHER in auth_order else "")),
        "auth_aria": (f"תרשים עמודות מוערמות: מחלפים לפי רשות תמרור וסוג. {lead_auth_name} מובילה עם "
                      f"{_int(lead_auth_n)} מחלפים."),
        "roads_note": (f"{_int(len(top))} הכבישים עם מספר המחלפים הגדול ביותר, מתוך {_int(n_roads_served)}. "
                       f"מחלף נספר בכל כביש שרשום בו, כך שמחלף בין שני כבישים נספר פעמיים. "
                       f"העמודה השנייה מראה עם כמה כבישים ממוספרים שונים הכביש מתחבר."),
        "roads_aria": (f"תרשים עמודות: {_int(len(top))} הכבישים עם הכי הרבה מחלפים. כביש {top_road} מוביל עם "
                       f"{_int(top_road_n)} מחלפים"
                       + (f", וכביש {top_hub['road']} מתחבר ל-{_int(top_hub['partners'])} כבישים."
                          if top_hub is not None else ".")),
        "nroads_note": (f"כמה כבישים ממוספרים רשומים בכל מחלף. {_int((df['n_roads'] == 2).sum())} מחלפים "
                        f"({_pct((df['n_roads'] == 2).sum(), total)}) מחברים שני כבישים."),
        "nroads_aria": (f"תרשים עמודות: מחלפים לפי מספר הכבישים הממוספרים שהם מחברים, "
                        f"מתוך {_int(total)} מחלפים."),
        "class_note": (f"כל כביש שרשום במחלף, לפי דרגת הכביש (נגזרת ממספר הספרות במספרו). "
                       f"בסך הכול {_int(n_refs)} חיבורים בין מחלף לכביש."),
        "class_aria": (f"תרשים עמודות: {_int(n_refs)} חיבורי מחלף לכביש לפי דרגת הכביש. "
                       f"כבישים ראשיים: {_int(ref_counts['ראשי'])}."),
        "pair_note": (f"ב-{_int(n_multi)} המחלפים שמחברים שני כבישים או יותר: אילו דרגות כביש נפגשות. "
                      f"כשנפגשים יותר משני כבישים, מוצגות שתי הדרגות הגבוהות."),
        "pair_aria": (f"תרשים עמודות: {_int(n_multi)} מחלפים בין כמה כבישים לפי צירוף דרגות הכבישים"
                      + (f". הצירוף הנפוץ: {pairs.index[0]} ({_int(pairs.iloc[0])})." if n_multi else ".")),
        "junction_note": (f"{_int(n_junctions)} מחלפים מערכתיים ופיצולים: נקודות המפגש בין כבישים בין עירוניים"
                          + (f". מוצגים {_int(JUNCTION_ROWS)} הראשונים." if n_junctions > JUNCTION_ROWS
                             else ".")),
        "roaddir_note": (f"רשימת המחלפים לאורך {_int(len(road_dirs))} הכבישים העמוסים במחלפים, "
                         f"עם קוד המחלף והכבישים הנוספים שהוא מחבר."),
    }

    tone_lead = "info" if total and lead_auth_n / total >= 0.5 else "brand"
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["מחלפים", "קוד מחלף", "כבישים בין עירוניים", "רשות תמרור",
                               "תשתית תחבורה"],
            "related_ids": ["3bf88891-4cb3-4288-81ef-bad6a9f8d625",
                            "09cbcff5-64fc-429b-96e5-881cbcab96af",
                            "068ff53c-ad54-4848-8a29-bd9b178d9174",
                            "0b22997e-676d-48d3-baee-c79846a1939f",
                            "27047419-e1fc-4f1d-bb15-7f5f0805d226"],
            "spatial_coverage": "רשת הדרכים הבין עירונית בישראל",
        },
        "kpis": {
            "total": {"value": total, "display": _int(total), "tone": "brand"},
            "full": {"value": full, "display": _int(full), "tone": "brand"},
            "roads": {"value": n_roads_served, "display": _int(n_roads_served), "tone": "brand"},
            "lead_auth": {"value": lead_auth_n, "display": _pct(lead_auth_n, total),
                          "tone": tone_lead},
        },
        "charts": {
            "types": {"names": list(types.index), "values": [int(v) for v in types]},
            "auth": auth_chart,
            "roads": roads_chart,
            "nroads": nroads_chart,
            "classes": class_chart,
            "pairs": pair_chart,
        },
        "tables": {
            "types": [{"name": t, "count": _int(v), "share": _pct(v, total)} for t, v in types.items()],
            "type_cols": type_order,
            "auth": auth_table,
            "roads": roads_table,
            "nroads": nroads_table,
            "classes": class_table,
            "pairs": pair_table,
            "junctions": junctions,
            "road_dirs": road_dirs,
        },
        "flags": {"has_junctions": n_junctions > 0, "has_pairs": n_multi > 0,
                  "has_roads": n_roads_served > 0},
        "insights": insights,
        "labels": labels,
    }
